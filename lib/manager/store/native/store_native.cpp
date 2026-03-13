/*
 * Copyright 2023 Serdar Bulut
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are met:
 *
 * 1. Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 *
 * 2. Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the distribution.
 *
 * 3. Neither the name of the copyright holder nor the names of its
 *    contributors may be used to endorse or promote products derived from
 *    this software without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
 * AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 * IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
 * ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
 * LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
 * CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
 * SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
 * INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
 * CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
 * ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
 * POSSIBILITY OF SUCH DAMAGE.
 */

#include <sys/vfs.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <deque>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <lsmio/lsmio.hpp>
#include <lsmio/manager/store/native/store_native.hpp>
#include <map>
#include <mutex>
#include <set>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#ifndef LUSTRE_SUPER_MAGIC
#define LUSTRE_SUPER_MAGIC 0x0BD00BD0
#endif

#ifndef GPFS_SUPER_MAGIC
#define GPFS_SUPER_MAGIC 0x47504653
#endif

namespace lsmio {

LSMIOStoreNative::LSMIOStoreNative(const std::string& dbPath, const bool overWrite,
                                   int num_parallel_processes)
    : LSMIOStore(dbPath, overWrite),
      _memtable_max_size_bytes(gConfigLSMIO.writeBufferSize > 0 ? gConfigLSMIO.writeBufferSize
                                                                : 32 * 1024 * 1024),
      _max_immutable_memtables(gConfigLSMIO.writeBufferNumber > 0 ? gConfigLSMIO.writeBufferNumber
                                                                  : 4),  // Default 4
      _active_memtable(std::make_unique<Memtable>()) {
    // Ensure database directory exists
    if (overWrite) {
        std::filesystem::remove_all(_dbPath);
    }
    std::filesystem::create_directories(_dbPath);

    // 1. Detect Filesystem and Tune Parameters
    struct statfs fs_info;
    uint64_t fs_magic = 0;
    if (statfs(_dbPath.c_str(), &fs_info) == 0) {
        fs_magic = fs_info.f_type;
    }
    tuneParameters(fs_magic, num_parallel_processes);

    // 2. Allocate aligned buffer pool (after tuning)
    _flush_buffers.resize(_flush_thread_count);
    for (size_t i = 0; i < _flush_thread_count; ++i) {
        if (::posix_memalign(reinterpret_cast<void**>(&_flush_buffers[i]), 4096,
                             _flush_buffer_capacity) != 0) {
            throw std::runtime_error("Failed to allocate aligned flush buffer");
        }
    }

    size_t pre_alloc_bytes = 0;
    if (gConfigLSMIO.preAllocate) {
        pre_alloc_bytes = _memtable_max_size_bytes;
    }

    // Initialize SSTableManager (which handles FilePool, Recovery, etc.)
    _sstable_manager =
        std::make_unique<SSTableManager>(_dbPath, gConfigLSMIO.filePoolSize, pre_alloc_bytes);

    // Start the background flush thread pool
    _shutting_down = false;
    for (size_t i = 0; i < _flush_thread_count; ++i) {
        _flush_threads.emplace_back(&LSMIOStoreNative::FlushWorkLoop, this, i);
    }
}

void LSMIOStoreNative::tuneParameters(uint64_t fs_magic, int num_parallel_processes) {
    std::string fs_type = "Unknown/Local";
    bool is_parallel_fs = false;

    if (fs_magic == LUSTRE_SUPER_MAGIC) {
        fs_type = "Lustre";
        is_parallel_fs = true;
    } else if (fs_magic == GPFS_SUPER_MAGIC) {
        fs_type = "GPFS";
        is_parallel_fs = true;
    }

    LOG(INFO) << "[NATIVE] Tuning parameters for filesystem: " << fs_type << " (Magic: 0x"
              << std::hex << fs_magic << std::dec << ")"
              << ", Parallel Processes: " << num_parallel_processes;

    // Establish baseline from config
    _memtable_max_size_bytes =
        gConfigLSMIO.writeBufferSize > 0 ? gConfigLSMIO.writeBufferSize : 32 * 1024 * 1024;
    _max_immutable_memtables =
        gConfigLSMIO.writeBufferNumber > 0 ? gConfigLSMIO.writeBufferNumber : 4;

    size_t total_memory_budget =
        static_cast<size_t>(_memtable_max_size_bytes) * _max_immutable_memtables;
    _flush_buffer_capacity = _memtable_max_size_bytes;
    _flush_thread_count = 1;  // Default

    LOG(INFO) << "[NATIVE] Initial Config: writeBufferSize="
              << (_memtable_max_size_bytes / 1024 / 1024)
              << "MB, writeBufferNumber=" << _max_immutable_memtables
              << ", Total Budget=" << (total_memory_budget / 1024 / 1024) << "MB";

    if (is_parallel_fs && gConfigLSMIO.blockSize > 0) {
        // Align and potentially increase buffer size to match filesystem stripe/block size
        size_t stripe_multiple =
            4 * 1024 * 1024;  // Default 4MB for parallel FS if blockSize is small
        if (gConfigLSMIO.blockSize > static_cast<int>(stripe_multiple)) {
            stripe_multiple = gConfigLSMIO.blockSize;
        }

        LOG(INFO) << "[NATIVE] Parallel FS detected. Aligning to stripe multiple: "
                  << (stripe_multiple / 1024) << "KB";

        // Align _flush_buffer_capacity to stripe_multiple
        _flush_buffer_capacity =
            ((_flush_buffer_capacity + stripe_multiple - 1) / stripe_multiple) * stripe_multiple;

        // If capacity increased, decrease number of buffers to keep total memory constant
        if (_flush_buffer_capacity > _memtable_max_size_bytes) {
            _memtable_max_size_bytes = _flush_buffer_capacity;
            _max_immutable_memtables = total_memory_budget / _memtable_max_size_bytes;
            if (_max_immutable_memtables < 1) _max_immutable_memtables = 1;
            LOG(INFO) << "[NATIVE] Applied Parallel FS Optimization: Increased writeBufferSize to "
                      << (_memtable_max_size_bytes / 1024 / 1024)
                      << "MB, Decreased writeBufferNumber to " << _max_immutable_memtables;
        }

        // Refined Thread Count Logic:
        // Use max(1, 4 / num_parallel_processes) to avoid over-subscribing the 4 OSTs
        _flush_thread_count = 4 / num_parallel_processes;
        if (_flush_thread_count < 1) _flush_thread_count = 1;
        // Also don't use more threads than we have memtable slots
        if (_flush_thread_count > _max_immutable_memtables)
            _flush_thread_count = _max_immutable_memtables;

    } else if (gConfigLSMIO.blockSize > 0) {
        // Basic alignment for local FS
        size_t old_cap = _flush_buffer_capacity;
        _flush_buffer_capacity =
            ((_flush_buffer_capacity + gConfigLSMIO.blockSize - 1) / gConfigLSMIO.blockSize) *
            gConfigLSMIO.blockSize;
        _memtable_max_size_bytes = _flush_buffer_capacity;
        if (_flush_buffer_capacity != old_cap) {
            LOG(INFO) << "[NATIVE] Aligned buffer to blockSize: " << (_flush_buffer_capacity / 1024)
                      << "KB";
        }
    }

    LOG(INFO) << "[NATIVE] Final Tuning: writeBufferSize="
              << (_memtable_max_size_bytes / 1024 / 1024)
              << "MB, writeBufferNumber=" << _max_immutable_memtables
              << ", FlushBufferCapacity=" << (_flush_buffer_capacity / 1024 / 1024) << "MB"
              << ", ParallelFlushThreads=" << _flush_thread_count;
}

LSMIOStoreNative::~LSMIOStoreNative() {
    close();
    for (char* ptr : _flush_buffers) {
        if (ptr) std::free(ptr);
    }
    _flush_buffers.clear();
}

void LSMIOStoreNative::close() {
    // Prevent double closing
    bool expected = false;
    if (!_shutting_down.compare_exchange_strong(expected, true)) {
        return;
    }

    _flush_cv.notify_all();  // Wake up all flush threads
    for (auto& t : _flush_threads) {
        if (t.joinable()) {
            t.join();
        }
    }

    std::unique_lock<std::mutex> lock(_state_mutex);
    // Final flush of any remaining in-memory data.
    if (!_active_memtable->empty()) {
        _immutable_memtables.push_back(std::move(_active_memtable));
    }
    while (!_immutable_memtables.empty()) {
        auto memtable_to_flush = std::move(_immutable_memtables.front());
        _immutable_memtables.pop_front();
        uint64_t flush_id = _next_flush_id++;

        lock.unlock();
        // Use the first buffer for the final sequential flushes
        FlushMemtableToL0(std::move(memtable_to_flush), 0, flush_id);
        lock.lock();
    }

    // Ensure all background file operations are finished
    if (_sstable_manager) {
        _sstable_manager->close();
    }
}

void LSMIOStoreNative::FlushWorkLoop(size_t thread_id) {
    while (true) {
        std::unique_ptr<Memtable> memtable_to_flush;
        uint64_t flush_id = 0;

        {
            std::unique_lock<std::mutex> lock(_state_mutex);
            _flush_cv.wait(
                lock, [this] { return _shutting_down.load() || !_immutable_memtables.empty(); });

            if (_shutting_down.load() && _immutable_memtables.empty()) {
                return;  // Shutdown complete
            }

            if (!_immutable_memtables.empty()) {
                memtable_to_flush = std::move(_immutable_memtables.front());
                _immutable_memtables.pop_front();
                flush_id = _next_flush_id++;
                _active_flush_count++;
            }
        }  // Release lock

        _backpressure_cv.notify_all();

        if (memtable_to_flush) {
            try {
                FlushMemtableToL0(std::move(memtable_to_flush), thread_id, flush_id);
            } catch (const std::exception& e) {
                LOG(ERROR) << "[NATIVE] ERROR in FlushWorkLoop: " << e.what();
            } catch (...) {
                LOG(ERROR) << "[NATIVE] UNKNOWN ERROR in FlushWorkLoop";
            }

            {
                std::unique_lock<std::mutex> lock(_state_mutex);
                _active_flush_count--;
            }
            _barrier_cv.notify_all();
        }
    }
}

void LSMIOStoreNative::FlushMemtableToL0(std::unique_ptr<Memtable> memtable, size_t thread_id,
                                         uint64_t flush_id) {
    if (!memtable) {
        return;
    }

    // Delegate to SSTableManager
    _sstable_manager->flushMemtable(*memtable, _flush_buffers[thread_id], _flush_buffer_capacity,
                                    flush_id);
}

bool LSMIOStoreNative::startBatch() {
    return true;
}

bool LSMIOStoreNative::stopBatch() {
    return writeBarrier();
}

bool LSMIOStoreNative::_batchMutation(MutationType mType, const std::string key,
                                      const std::string value, bool flush) {
    std::string actual_value = value;
    if (mType == MutationType::Del) {
        actual_value = MEMTABLE_TOMBSTONE;
    }

    size_t entry_size = key.size() + actual_value.size();

    std::unique_lock<std::mutex> lock(_state_mutex);

    // --- 1. Check if active memtable needs to be rotated ---
    if (_active_memtable->sizeBytes() + entry_size > _memtable_max_size_bytes &&
        _active_memtable->sizeBytes() > 0) {
        // --- 2. Apply Backpressure ---
        if (_immutable_memtables.size() >= _max_immutable_memtables) {
            _backpressure_cv.wait(
                lock, [this] { return _immutable_memtables.size() < _max_immutable_memtables; });
        }

        // --- 3. Rotate Memtables ---
        _immutable_memtables.push_back(std::move(_active_memtable));
        _active_memtable = std::make_unique<Memtable>();

        // Notify the flush thread that there is new work
        _flush_cv.notify_one();
    }

    // --- 4. Write to active memtable ---
    _active_memtable->add(key, actual_value);

    return true;
}

bool LSMIOStoreNative::dbCleanup() {
    if (std::filesystem::exists(_dbPath)) {
        std::filesystem::remove_all(_dbPath);
        return true;
    }
    return false;
}

bool LSMIOStoreNative::get(const std::string key, std::string* value) {
    std::string result;
    bool found = false;

    {
        std::unique_lock<std::mutex> lock(_state_mutex);

        // --- 1. Check active memtable ---
        if (_active_memtable->get(key, result)) {
            found = true;
        }

        if (!found) {
            // --- 2. Check immutable memtables (Newest to oldest) ---
            for (auto it = _immutable_memtables.rbegin(); it != _immutable_memtables.rend(); ++it) {
                if ((*it)->get(key, result)) {
                    found = true;
                    break;
                }
            }
        }
    }  // Release lock

    // --- 3. Check SSTables ---
    if (!found) {
        if (_sstable_manager->get(key, result)) {
            found = true;
        }
    }

    // --- 4. Final result processing ---
    if (found && result != MEMTABLE_TOMBSTONE) {
        *value = result;
        return true;
    }

    return false;
}

bool LSMIOStoreNative::getPrefix(const std::string prefix_key,
                                 std::vector<std::tuple<std::string, std::string>>* values) {
    std::map<std::string, std::string> results;
    std::set<std::string> deleted_keys;
    bool found_any = false;

    {
        std::unique_lock<std::mutex> lock(_state_mutex);

        // --- 1. Check active memtable ---
        _active_memtable->scan(prefix_key, results, deleted_keys);

        // --- 2. Immutable memtables ---
        for (auto it = _immutable_memtables.rbegin(); it != _immutable_memtables.rend(); ++it) {
            (*it)->scan(prefix_key, results, deleted_keys);
        }
    }

    // --- 3. Check SSTables ---
    _sstable_manager->scan(prefix_key, results, deleted_keys);

    for (const auto& [key, value] : results) {
        if (deleted_keys.find(key) == deleted_keys.end()) {
            values->emplace_back(key, value);
        }
    }

    // If we found anything in map, found_any should be true
    if (!results.empty()) found_any = true;

    return found_any;
}

bool LSMIOStoreNative::readBarrier() {
    return true;
}

bool LSMIOStoreNative::writeBarrier() {
    std::unique_lock<std::mutex> lock(_state_mutex);

    if (!_active_memtable->empty()) {
        _immutable_memtables.push_back(std::move(_active_memtable));
        _active_memtable = std::make_unique<Memtable>();
        _flush_cv.notify_one();
    }

    _barrier_cv.wait(lock,
                     [this] { return _immutable_memtables.empty() && _active_flush_count == 0; });

    return true;
}

}  // namespace lsmio
