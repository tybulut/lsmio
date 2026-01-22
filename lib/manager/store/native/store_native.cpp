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

#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <deque>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <lsmio/manager/store/native/store_native.hpp>
#include <map>
#include <mutex>
#include <set>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

namespace lsmio {

LSMIOStoreNative::LSMIOStoreNative(const std::string& dbPath, const bool overWrite)
    : LSMIOStore(dbPath, overWrite),
      _memtable_max_size_bytes(gConfigLSMIO.writeBufferSize > 0 ? gConfigLSMIO.writeBufferSize
                                                                : 1024 * 1024),
      _max_immutable_memtables(gConfigLSMIO.writeBufferNumber > 0 ? gConfigLSMIO.writeBufferNumber
                                                                  : 2),  // Default 2
      _active_memtable(std::make_unique<Memtable>()),
      _flush_buffer(1024 * 1024) {
    // Ensure database directory exists
    if (overWrite) {
        std::filesystem::remove_all(_dbPath);
    }
    std::filesystem::create_directories(_dbPath);

    size_t pre_alloc_bytes = 0;
    if (gConfigLSMIO.preAllocate) {
        pre_alloc_bytes = _memtable_max_size_bytes;
    }

    // Initialize SSTableManager (which handles FilePool, Recovery, etc.)
    _sstable_manager =
        std::make_unique<SSTableManager>(_dbPath, gConfigLSMIO.filePoolSize, pre_alloc_bytes);

    // Start the background flush thread
    _shutting_down = false;
    _flush_thread = std::thread(&LSMIOStoreNative::FlushWorkLoop, this);
}

LSMIOStoreNative::~LSMIOStoreNative() {
    close();
}

void LSMIOStoreNative::close() {
    // Prevent double closing
    bool expected = false;
    if (!_shutting_down.compare_exchange_strong(expected, true)) {
        return;
    }

    _flush_cv.notify_one();  // Wake up the flush thread
    if (_flush_thread.joinable()) {
        _flush_thread.join();
    }

    std::unique_lock<std::mutex> lock(_state_mutex);
    // Final flush of any remaining in-memory data.
    if (!_active_memtable->empty()) {
        _immutable_memtables.push_back(std::move(_active_memtable));
    }
    while (!_immutable_memtables.empty()) {
        auto memtable_to_flush = std::move(_immutable_memtables.front());
        _immutable_memtables.pop_front();

        lock.unlock();
        FlushMemtableToL0(std::move(memtable_to_flush));
        lock.lock();
    }

    // Ensure all background file operations are finished
    if (_sstable_manager) {
        _sstable_manager->close();
    }
}

void LSMIOStoreNative::FlushWorkLoop() {
    while (true) {
        std::unique_ptr<Memtable> memtable_to_flush;

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
                _flush_in_progress = true;
            }
        }  // Release lock

        _backpressure_cv.notify_all();

        if (memtable_to_flush) {
            try {
                FlushMemtableToL0(std::move(memtable_to_flush));
            } catch (const std::exception& e) {
                std::cerr << "[NATIVE] ERROR in FlushWorkLoop: " << e.what() << std::endl;
            } catch (...) {
                std::cerr << "[NATIVE] UNKNOWN ERROR in FlushWorkLoop" << std::endl;
            }

            {
                std::unique_lock<std::mutex> lock(_state_mutex);
                _flush_in_progress = false;
            }
            _barrier_cv.notify_all();
        }
    }
}

void LSMIOStoreNative::FlushMemtableToL0(std::unique_ptr<Memtable> memtable) {
    if (!memtable || memtable->empty()) {
        return;
    }

    // Delegate to SSTableManager
    // We pass _flush_buffer for reuse
    _sstable_manager->flushMemtable(*memtable, _flush_buffer);
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

    _barrier_cv.wait(lock, [this] { return _immutable_memtables.empty() && !_flush_in_progress; });

    return true;
}

}  // namespace lsmio
