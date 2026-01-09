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

#include <algorithm>  // For std::sort
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <deque>
#include <filesystem>
#include <fstream>
#include <iomanip>  // For std::setw, std::setfill
#include <iostream>
#include <lsmio/manager/store/store_native.hpp>
#include <map>
#include <mutex>
#include <set>      // For getPrefix tracking
#include <sstream>  // For std::ostringstream
#include <string>
#include <thread>
#include <vector>

namespace lsmio {

// Define a special value to mark deletions.
const std::string TOMBSTONE_VALUE = "__LSM_TOMBSTONE_v1__";

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

    // Recover on-disk state
    RecoverStateFromDisk();

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
        // Release lock during I/O if possible? 
        // For simplicity and safety during shutdown, we can keep it or release it.
        // FlushMemtableToL0 acquires the lock internally, so we MUST release it.
        lock.unlock();
        FlushMemtableToL0(std::move(memtable_to_flush));
        lock.lock();
    }
}

void LSMIOStoreNative::FlushWorkLoop() {
    while (true) {
        std::unique_ptr<Memtable> memtable_to_flush;

        {
            std::unique_lock<std::mutex> lock(_state_mutex);
            // Wait until shutdown OR there's an immutable memtable to flush
            _flush_cv.wait(
                lock, [this] { return _shutting_down.load() || !_immutable_memtables.empty(); });

            if (_shutting_down.load() && _immutable_memtables.empty()) {
                return;  // Shutdown complete
            }

            if (!_immutable_memtables.empty()) {
                // Get the oldest immutable memtable from the front of the queue
                memtable_to_flush = std::move(_immutable_memtables.front());
                _immutable_memtables.pop_front();
                _flush_in_progress = true;
            }
        }  // Release lock

        // Notify any Put() threads that were waiting due to backpressure
        // Also notifies writeBarrier() waiting for queue to empty
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

    // SKIP SORTING for maximum write throughput (Bitcask style).
    // Since we have an in-memory index (L0Index), the on-disk order doesn't need to be sorted
    // for point lookups. It only hurts range scans, but significantly speeds up flush.
    /*
    std::sort(memtable->begin(), memtable->end(),
        [](const std::pair<std::string, std::string>& a, const std::pair<std::string, std::string>&
    b) { return a.first < b.first;
        }
    );
    */

    // 1. Generate a new, unique SSTable filename
    std::string sstable_path;
    uint64_t sstable_id = _next_sstable_id.fetch_add(1);

    {
        // Format ID with padding (e.g., L0-000001.sst)
        std::ostringstream oss;
        oss << "L0-" << std::setw(6) << std::setfill('0') << sstable_id << ".sst";
        sstable_path = (std::filesystem::path(_dbPath) / oss.str()).string();
    }

    // 2. Write file and build index
    std::ofstream sst_file;
    // Reuse the class-level buffer for the file stream
    sst_file.rdbuf()->pubsetbuf(_flush_buffer.data(), _flush_buffer.size());
    sst_file.open(sstable_path, std::ios::binary);

    if (!sst_file) {
        std::cerr << "[Flush Thread] ERROR: Failed to open SSTable file: " << sstable_path
                  << std::endl;
        return;
    }

    L0Index new_index;
    new_index.path = sstable_path;
    // Pre-allocate to avoid reallocations
    new_index.offsets.reserve(memtable->size());

    std::string serialization_buffer;
    serialization_buffer.reserve(1024 * 64);  // Pre-reserve to avoid frequent reallocs

    for (const auto& [key, value] : *memtable) {
        // Track offset
        uint64_t current_offset = sst_file.tellp();
        new_index.offsets.emplace_back(key, current_offset);

        uint32_t key_len = static_cast<uint32_t>(key.size());
        uint32_t val_len = static_cast<uint32_t>(value.size());

        // Batch serialization into a single buffer to reduce write calls
        serialization_buffer.clear();
        serialization_buffer.append(reinterpret_cast<const char*>(&key_len), sizeof(key_len));
        serialization_buffer.append(key.data(), key_len);
        serialization_buffer.append(reinterpret_cast<const char*>(&val_len), sizeof(val_len));
        serialization_buffer.append(value.data(), val_len);

        sst_file.write(serialization_buffer.data(), serialization_buffer.size());
    }

    sst_file.close();

    // --- Batch Indexing Optimization ---
    // 1. Sort by Key ASC, then Offset DESC (so the latest update is first)
    std::sort(
        new_index.offsets.begin(), new_index.offsets.end(),
        [](const std::pair<std::string, uint64_t>& a, const std::pair<std::string, uint64_t>& b) {
            if (a.first != b.first) return a.first < b.first;
            return a.second > b.second;  // Descending offset
        });

    // 2. Unique (Deduplicate) - Keep only the first occurrence (which is the latest offset)
    auto last =
        std::unique(new_index.offsets.begin(), new_index.offsets.end(),
                    [](const std::pair<std::string, uint64_t>& a,
                       const std::pair<std::string, uint64_t>& b) { return a.first == b.first; });
    new_index.offsets.erase(last, new_index.offsets.end());

    // 3. Add the new SSTable and Index to the lists (under lock)
    {
        std::unique_lock<std::mutex> lock(_state_mutex);
        _l0_files.push_back(sstable_path);
        _l0_indices.push_back(std::move(new_index));
    }
}

bool LSMIOStoreNative::ReadValueAt(const std::string& sstable_path, uint64_t offset,
                                   const std::string& key, std::string& out_value) {
    std::ifstream sst_file(sstable_path, std::ios::binary);
    if (!sst_file) {
        std::cerr << "ERROR: Failed to open SSTable for read: " << sstable_path << std::endl;
        return false;
    }

    // Seek to the precise offset
    sst_file.seekg(offset);
    if (sst_file.fail()) {
        std::cerr << "ERROR: Failed to seek to offset " << offset << " in " << sstable_path
                  << std::endl;
        return false;
    }

    uint32_t key_len;
    sst_file.read(reinterpret_cast<char*>(&key_len), sizeof(key_len));
    if (sst_file.fail()) return false;

    std::string key_from_file(key_len, '\0');
    sst_file.read(&key_from_file[0], key_len);
    if (sst_file.fail()) return false;

    // Sanity check
    if (key_from_file != key) {
        // This can happen if duplicates exist and we mapped to one, but read another?
        // No, offset is precise.
        std::cerr << "ERROR: Index mismatch! Expected key " << key << " but found " << key_from_file
                  << " at offset " << offset << " in " << sstable_path << std::endl;
        return false;
    }

    uint32_t val_len;
    sst_file.read(reinterpret_cast<char*>(&val_len), sizeof(val_len));
    if (sst_file.fail()) return false;

    std::string val_from_file(val_len, '\0');
    sst_file.read(&val_from_file[0], val_len);
    if (sst_file.fail()) return false;

    out_value = val_from_file;
    sst_file.close();
    return true;
}

void LSMIOStoreNative::RecoverStateFromDisk() {
    if (!std::filesystem::exists(_dbPath)) {
        return;
    }

    uint64_t max_id = 0;
    std::vector<std::pair<uint64_t, std::string>> found_files;

    for (const auto& entry : std::filesystem::directory_iterator(_dbPath)) {
        std::string filename = entry.path().filename().string();
        if (filename.rfind("L0-", 0) == 0 && filename.rfind(".sst") == filename.size() - 4) {
            try {
                // Extract the ID (e.g., from "L0-000001.sst")
                uint64_t id = std::stoull(filename.substr(3, filename.size() - 7));
                found_files.push_back({id, entry.path().string()});
                if (id > max_id) {
                    max_id = id;
                }
            } catch (...) {
                std::cerr << "Warning: Could not parse SSTable ID from: " << filename << std::endl;
            }
        }
    }

    // Sort files by ID to maintain correct search order (newest is last)
    std::sort(found_files.begin(), found_files.end());

    // Scan files to rebuild index
    std::cout << "[NATIVE] Recovering state. Indexing " << found_files.size() << " SSTables..."
              << std::endl;
    for (const auto& [id, path] : found_files) {
        _l0_files.push_back(path);

        L0Index new_index;
        new_index.path = path;

        std::ifstream sst_file(path, std::ios::binary);
        if (sst_file) {
            while (sst_file.peek() != EOF) {
                uint64_t current_offset = sst_file.tellg();

                uint32_t key_len;
                sst_file.read(reinterpret_cast<char*>(&key_len), sizeof(key_len));
                if (sst_file.fail()) break;

                std::string key(key_len, '\0');
                sst_file.read(&key[0], key_len);
                if (sst_file.fail()) break;

                uint32_t val_len;
                sst_file.read(reinterpret_cast<char*>(&val_len), sizeof(val_len));
                if (sst_file.fail()) break;

                // Skip value
                sst_file.seekg(val_len, std::ios::cur);
                if (sst_file.fail()) break;

                new_index.offsets.emplace_back(key, current_offset);
            }
            sst_file.close();
        }

        // --- Batch Indexing Optimization (Recovery) ---
        // 1. Sort by Key ASC, then Offset DESC
        std::sort(new_index.offsets.begin(), new_index.offsets.end(),
                  [](const std::pair<std::string, uint64_t>& a,
                     const std::pair<std::string, uint64_t>& b) {
                      if (a.first != b.first) return a.first < b.first;
                      return a.second > b.second;  // Descending offset
                  });

        // 2. Unique (Deduplicate)
        auto last = std::unique(
            new_index.offsets.begin(), new_index.offsets.end(),
            [](const std::pair<std::string, uint64_t>& a,
               const std::pair<std::string, uint64_t>& b) { return a.first == b.first; });
        new_index.offsets.erase(last, new_index.offsets.end());

        _l0_indices.push_back(std::move(new_index));
    }

    _next_sstable_id = max_id + 1;
    std::cout << "[NATIVE] Recovery complete." << std::endl;
}

bool LSMIOStoreNative::startBatch() {
    return true;
}

bool LSMIOStoreNative::stopBatch() {
    // Equivalent to writeBarrier for this store
    return writeBarrier();
}

bool LSMIOStoreNative::_batchMutation(MutationType mType, const std::string key,
                                      const std::string value, bool flush) {
    std::string actual_value = value;
    if (mType == MutationType::Del) {
        actual_value = TOMBSTONE_VALUE;
    }

    size_t entry_size = key.size() + actual_value.size();

    std::unique_lock<std::mutex> lock(_state_mutex);

    // --- 1. Check if active memtable needs to be rotated ---
    if (_active_memtable_size + entry_size > _memtable_max_size_bytes &&
        _active_memtable_size > 0) {
        // --- 2. Apply Backpressure ---
        if (_immutable_memtables.size() >= _max_immutable_memtables) {
            _backpressure_cv.wait(
                lock, [this] { return _immutable_memtables.size() < _max_immutable_memtables; });
        }

        // --- 3. Rotate Memtables ---
        _immutable_memtables.push_back(std::move(_active_memtable));
        _active_memtable = std::make_unique<Memtable>();
        _active_memtable_size = 0;

        // Notify the flush thread that there is new work
        _flush_cv.notify_one();
    }

    // --- 4. Write to active memtable ---
    // Fast append O(1) with move
    // We need to cast const away or make a copy to move?
    // The interface is const std::string& value. We must copy at least once from the caller.
    // But we can construct directly in place.
    _active_memtable->emplace_back(key, value);
    _active_memtable_size += entry_size;

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

    std::vector<L0Index> indices_snapshot;

    {
        std::unique_lock<std::mutex> lock(_state_mutex);

        // --- 1. Check active memtable (Reverse Scan) ---
        // Scan active memtable from back to front (newest first)
        for (auto it = _active_memtable->rbegin(); it != _active_memtable->rend(); ++it) {
            if (it->first == key) {
                result = it->second;
                found = true;
                break;
            }
        }

        if (!found) {
            // --- 2. Check immutable memtables (Newest to oldest, each reverse scanned) ---
            for (auto it = _immutable_memtables.rbegin(); it != _immutable_memtables.rend(); ++it) {
                for (auto it_entry = (*it)->rbegin(); it_entry != (*it)->rend(); ++it_entry) {
                    if (it_entry->first == key) {
                        result = it_entry->second;
                        found = true;
                        break;
                    }
                }
                if (found) break;
            }
        }

        // --- 3. Get snapshot of L0 Indices ---
        if (!found) {
            indices_snapshot = _l0_indices;
        }

    }  // Release lock

    // --- 4. Check L0 Indices (Bitcask style: Index Lookup + Direct Read) ---
    if (!found && !indices_snapshot.empty()) {
        // Search newest to oldest
        for (auto it = indices_snapshot.rbegin(); it != indices_snapshot.rend(); ++it) {
            // Binary search on sorted vector
            auto offset_it =
                std::lower_bound(it->offsets.begin(), it->offsets.end(), key,
                                 [](const std::pair<std::string, uint64_t>& entry,
                                    const std::string& val) { return entry.first < val; });

            if (offset_it != it->offsets.end() && offset_it->first == key) {
                // Found in index! Read from disk at offset.
                if (ReadValueAt(it->path, offset_it->second, key, result)) {
                    found = true;
                    break;
                }
            }
        }
    }

    // --- 5. Final result processing ---
    if (found && result != TOMBSTONE_VALUE) {
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

    // We must hold the lock while checking in-memory state.
    std::vector<L0Index> indices_snapshot;

    {
        std::unique_lock<std::mutex> lock(_state_mutex);

        // --- 1. Check active memtable ---
        // Linear scan required for vector
        for (const auto& entry : *_active_memtable) {
            if (entry.first.compare(0, prefix_key.size(), prefix_key) == 0) {
                if (entry.second == TOMBSTONE_VALUE) {
                    deleted_keys.insert(entry.first);
                    results.erase(entry.first);
                } else {
                    results[entry.first] = entry.second;
                    deleted_keys.erase(entry.first);
                    found_any = true;
                }
            }
        }

        // --- 2. Immutable memtables ---
        for (auto it = _immutable_memtables.rbegin(); it != _immutable_memtables.rend(); ++it) {
            for (const auto& entry : **it) {
                if (entry.first.compare(0, prefix_key.size(), prefix_key) == 0) {
                    if (results.find(entry.first) == results.end() &&
                        deleted_keys.find(entry.first) == deleted_keys.end()) {
                        if (entry.second == TOMBSTONE_VALUE) {
                            deleted_keys.insert(entry.first);
                        } else {
                            results[entry.first] = entry.second;
                            found_any = true;
                        }
                    }
                }
            }
        }
        indices_snapshot = _l0_indices;
    }

    // --- 4. Check L0 Indices ---
    for (auto it = indices_snapshot.rbegin(); it != indices_snapshot.rend(); ++it) {
        // Binary search for the first key >= prefix_key
        auto it_idx = std::lower_bound(it->offsets.begin(), it->offsets.end(), prefix_key,
                                       [](const std::pair<std::string, uint64_t>& entry,
                                          const std::string& val) { return entry.first < val; });

        for (; it_idx != it->offsets.end(); ++it_idx) {
            const auto& key = it_idx->first;
            uint64_t offset = it_idx->second;

            if (key.compare(0, prefix_key.size(), prefix_key) != 0) break;

            if (results.find(key) == results.end() &&
                deleted_keys.find(key) == deleted_keys.end()) {
                std::string val_from_disk;
                if (ReadValueAt(it->path, offset, key, val_from_disk)) {
                    if (val_from_disk == TOMBSTONE_VALUE) {
                        deleted_keys.insert(key);
                    } else {
                        results[key] = val_from_disk;
                        found_any = true;
                    }
                }
            }
        }
    }

    for (const auto& [key, value] : results) {
        if (deleted_keys.find(key) == deleted_keys.end()) {
            values->emplace_back(key, value);
        }
    }

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
        _active_memtable_size = 0;
        _flush_cv.notify_one();
    }

    _barrier_cv.wait(lock, [this] { return _immutable_memtables.empty() && !_flush_in_progress; });

    return true;
}

}  // namespace lsmio
