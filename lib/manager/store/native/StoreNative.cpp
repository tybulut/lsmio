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

#ifdef __linux__
#include <sys/vfs.h>
#else
#include <sys/mount.h>
#include <sys/param.h>
#endif

#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <deque>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <lsmio/manager/store/native/StoreNative.hpp>
#include <map>
#include <mutex>
#include <set>
#include <sstream>
#include <string>
#include <thread>
#include <vector>
#include <stdexcept>

#ifndef LUSTRE_SUPER_MAGIC
#define LUSTRE_SUPER_MAGIC 0x0BD00BD0
#endif

#ifndef GPFS_SUPER_MAGIC
#define GPFS_SUPER_MAGIC 0x47504653
#endif

namespace lsmio {

std::unique_ptr<IMemtable> LSMIOStoreNative::createMemtable() const {
    switch (gConfigLSMIO.memtable) {
        case MemtableType::VectorSort: return std::make_unique<MemtableVectorSort>();
        case MemtableType::Map: return std::make_unique<MemtableOrdered<std::map<std::string, std::string>>>();
        case MemtableType::BTree: return std::make_unique<MemtableOrdered<tlx::btree_map<std::string, std::string>>>();
        case MemtableType::VectorNoSort: return std::make_unique<MemtableVectorNoSort>();
        default: throw std::invalid_argument("Unknown MemtableType");
    }
}

LSMIOStoreNative::LSMIOStoreNative(const std::string& f_db_path, const bool f_over_write)
    : LSMIOStore(f_db_path, f_over_write),
      m_memtable_max_size_bytes(gConfigLSMIO.writeBufferSize > 0 ? gConfigLSMIO.writeBufferSize
                                                                : 32 * 1024 * 1024),
      m_max_immutable_memtables(gConfigLSMIO.writeBufferNumber > 0 ? gConfigLSMIO.writeBufferNumber
                                                                  : 4),  // Default 4
      m_max_key_len(gConfigLSMIO.maxKeyLen),
      m_max_value_len(gConfigLSMIO.getMaxValueLen()),
      m_active_memtable(createMemtable()),
      m_flush_buffer(m_memtable_max_size_bytes) {
    if (m_max_value_len == 0) throw std::invalid_argument("writeBufferSize is too small to accommodate maxKeyLen and overhead");
    // Ensure database directory exists
    if (f_over_write) {
        std::filesystem::remove_all(_dbPath);
    }
    std::filesystem::create_directories(_dbPath);

    if (gConfigLSMIO.autoTuneParameters) {
        struct statfs fs_info;
        uint64_t fs_magic = 0;
        if (statfs(_dbPath.c_str(), &fs_info) == 0) {
            fs_magic = fs_info.f_type;
        }
        autoTuneParameters(fs_magic);
    }

    size_t pre_alloc_bytes = 0;
    if (gConfigLSMIO.preAllocate) {
        pre_alloc_bytes = m_memtable_max_size_bytes;
    }

    // Initialize SSTableManager (which handles FilePool, Recovery, etc.)
    m_sstable_manager =
        std::make_unique<SSTableManager>(_dbPath, gConfigLSMIO.filePoolSize, pre_alloc_bytes);

    // Start the background flush thread
    m_shutting_down = false;
    m_flush_thread = std::thread(&LSMIOStoreNative::FlushWorkLoop, this);
}

void LSMIOStoreNative::autoTuneParameters(uint64_t f_fs_magic) {
    std::string fs_type = "Unknown/Local";
    bool is_parallel_fs = false;

    if (f_fs_magic == LUSTRE_SUPER_MAGIC) {
        fs_type = "Lustre";
        is_parallel_fs = true;
    } else if (f_fs_magic == GPFS_SUPER_MAGIC) {
        fs_type = "GPFS";
        is_parallel_fs = true;
    }

    LOG(INFO) << "[NATIVE] Tuning parameters for filesystem: " << fs_type << " (Magic: 0x"
              << std::hex << f_fs_magic << std::dec << ")";

    if (is_parallel_fs) {
        // TODO(tybulut): Adjust writer thread pool size
    }

    LOG(INFO) << "[NATIVE] Final Tuning: writeBufferSize="
              << (m_memtable_max_size_bytes / 1024 / 1024)
              << "MB, writeBufferNumber=" << m_max_immutable_memtables;
}

LSMIOStoreNative::~LSMIOStoreNative() {
    close();
}

void LSMIOStoreNative::close() {
    // Prevent double closing
    bool expected = false;
    if (!m_shutting_down.compare_exchange_strong(expected, true)) {
        return;
    }

    m_flush_cv.notify_one();  // Wake up the flush thread
    if (m_flush_thread.joinable()) {
        m_flush_thread.join();
    }

    std::unique_lock<std::mutex> lock(m_state_mutex);
    // Final flush of any remaining in-memory data.
    if (!m_active_memtable->empty()) {
        m_immutable_memtables.push_back(std::move(m_active_memtable));
    }
    while (!m_immutable_memtables.empty()) {
        auto memtable_to_flush = std::move(m_immutable_memtables.front());
        m_immutable_memtables.pop_front();

        lock.unlock();
        FlushMemtableToL0(std::move(memtable_to_flush));
        lock.lock();
    }

    // Ensure all background file operations are finished
    if (m_sstable_manager) {
        m_sstable_manager->close();
    }
}

void LSMIOStoreNative::FlushWorkLoop() {
    while (true) {
        std::unique_ptr<IMemtable> memtable_to_flush;

        {
            std::unique_lock<std::mutex> lock(m_state_mutex);
            m_flush_cv.wait(
                lock, [this] { return m_shutting_down.load() || !m_immutable_memtables.empty(); });

            if (m_shutting_down.load() && m_immutable_memtables.empty()) {
                return;  // Shutdown complete
            }

            if (!m_immutable_memtables.empty()) {
                memtable_to_flush = std::move(m_immutable_memtables.front());
                m_immutable_memtables.pop_front();
                m_flush_in_progress = true;
            }
        }  // Release lock

        m_backpressure_cv.notify_all();

        if (memtable_to_flush) {
            try {
                FlushMemtableToL0(std::move(memtable_to_flush));
            } catch (const std::exception& e) {
                std::cerr << "[NATIVE] ERROR in FlushWorkLoop: " << e.what() << std::endl;
            } catch (...) {
                std::cerr << "[NATIVE] UNKNOWN ERROR in FlushWorkLoop" << std::endl;
            }

            {
                std::unique_lock<std::mutex> lock(m_state_mutex);
                m_flush_in_progress = false;
            }
            m_barrier_cv.notify_all();
        }
    }
}

void LSMIOStoreNative::FlushMemtableToL0(std::unique_ptr<IMemtable> f_memtable) {
    if (!f_memtable || f_memtable->empty()) {
        return;
    }

    // Delegate to SSTableManager
    // We pass m_flush_buffer for reuse
    if (!m_sstable_manager->flushMemtable(*f_memtable, m_flush_buffer)) {
        m_bg_error = true;
    }
}

bool LSMIOStoreNative::startBatch() {
    return true;
}

bool LSMIOStoreNative::stopBatch() {
    return writeBarrier();
}

bool LSMIOStoreNative::_batchMutation(MutationType f_m_type, const std::string f_key,
                                      const std::string f_value, bool f_flush) {
    if (m_bg_error.load(std::memory_order_relaxed)) return false;
    std::string actual_value = f_value;
    if (f_m_type == MutationType::Del) {
        actual_value = MEMTABLE_TOMBSTONE;
    }
    // Validate what will actually be stored: for deletes that is the
    // tombstone sentinel, not the caller-supplied value.
    if (f_key.size() > m_max_key_len || actual_value.size() > m_max_value_len) return false;

    size_t entry_size = f_key.size() + actual_value.size();

    std::unique_lock<std::mutex> lock(m_state_mutex);

    // --- 1. Check if active memtable needs to be rotated ---
    if (m_active_memtable->sizeBytes() + entry_size > m_memtable_max_size_bytes &&
        m_active_memtable->sizeBytes() > 0) {
        // --- 2. Apply Backpressure ---
        if (m_immutable_memtables.size() >= m_max_immutable_memtables) {
            m_backpressure_cv.wait(
                lock, [this] { return m_immutable_memtables.size() < m_max_immutable_memtables; });
        }

        // --- 3. Rotate Memtables ---
        auto next_memtable = createMemtable();
        m_immutable_memtables.push_back(std::move(m_active_memtable));
        m_active_memtable = std::move(next_memtable);

        // Notify the flush thread that there is new work
        m_flush_cv.notify_one();
    }

    // --- 4. Write to active memtable ---
    m_active_memtable->add(f_key, actual_value);

    return true;
}

bool LSMIOStoreNative::dbCleanup() {
    if (std::filesystem::exists(_dbPath)) {
        std::filesystem::remove_all(_dbPath);
        return true;
    }
    return false;
}

bool LSMIOStoreNative::get(const std::string f_key, std::string* f_value) {
    if (f_key.size() > m_max_key_len) return false;
    std::string result;
    bool found = false;

    {
        std::unique_lock<std::mutex> lock(m_state_mutex);

        // --- 1. Check active memtable ---
        if (m_active_memtable->get(f_key, result)) {
            found = true;
        }

        if (!found) {
            // --- 2. Check immutable memtables (Newest to oldest) ---
            for (auto it = m_immutable_memtables.rbegin(); it != m_immutable_memtables.rend(); ++it) {
                if ((*it)->get(f_key, result)) {
                    found = true;
                    break;
                }
            }
        }
    }  // Release lock

    // --- 3. Check SSTables ---
    if (!found) {
        if (m_sstable_manager->get(f_key, result)) {
            found = true;
        }
    }

    // --- 4. Final result processing ---
    if (found && result != MEMTABLE_TOMBSTONE) {
        *f_value = result;
        return true;
    }

    return false;
}

bool LSMIOStoreNative::getPrefix(const std::string f_prefix_key,
                                 std::vector<std::tuple<std::string, std::string>>* f_values) {
    if (f_prefix_key.size() > m_max_key_len) return false;
    std::map<std::string, std::string> results;
    std::set<std::string> deleted_keys;
    bool found_any = false;

    {
        std::unique_lock<std::mutex> lock(m_state_mutex);

        // --- 1. Check active memtable ---
        m_active_memtable->scan(f_prefix_key, results, deleted_keys);

        // --- 2. Immutable memtables ---
        for (auto it = m_immutable_memtables.rbegin(); it != m_immutable_memtables.rend(); ++it) {
            (*it)->scan(f_prefix_key, results, deleted_keys);
        }
    }

    // --- 3. Check SSTables ---
    m_sstable_manager->scan(f_prefix_key, results, deleted_keys);

    for (const auto& [key, value] : results) {
        if (deleted_keys.find(key) == deleted_keys.end()) {
            f_values->emplace_back(key, value);
        }
    }

    // If we found anything in map, found_any should be true
    if (!results.empty()) found_any = true;

    return found_any;
}

bool LSMIOStoreNative::readBarrier() {
    // Reads themselves stay valid after a background flush failure, but the
    // barrier contract ("everything written is now visible") does not hold.
    return !m_bg_error.load(std::memory_order_relaxed);
}

bool LSMIOStoreNative::writeBarrier() {
    if (m_bg_error.load(std::memory_order_relaxed)) return false;
    std::unique_lock<std::mutex> lock(m_state_mutex);

    if (!m_active_memtable->empty()) {
        auto next_memtable = createMemtable();
        m_immutable_memtables.push_back(std::move(m_active_memtable));
        m_active_memtable = std::move(next_memtable);
        m_flush_cv.notify_one();
    }

    // m_bg_error is part of the predicate: a flush that fails while this
    // barrier is already waiting must wake it AND make it report failure,
    // not satisfy it via the cleared m_flush_in_progress.
    m_barrier_cv.wait(lock, [this] {
        return m_bg_error.load(std::memory_order_relaxed) ||
               (m_immutable_memtables.empty() && !m_flush_in_progress);
    });

    return !m_bg_error.load(std::memory_order_relaxed);
}

}  // namespace lsmio
