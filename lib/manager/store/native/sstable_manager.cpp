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
#include <filesystem>
#include <fstream>
#include <iostream>
#include <lsmio/manager/store/native/sstable_manager.hpp>

namespace lsmio {

SSTableManager::SSTableManager(const std::string& dbPath, size_t filePoolSize, size_t preAllocBytes)
    : _dbPath(dbPath) {
    recoverState(filePoolSize, preAllocBytes);
}

SSTableManager::~SSTableManager() {
    IndexNode* curr = _head.load(std::memory_order_relaxed);
    while (curr) {
        IndexNode* next = curr->next;
        delete curr;
        curr = next;
    }
}

bool SSTableManager::flushMemtable(const Memtable& memtable, std::vector<char>& buffer) {
    if (memtable.empty()) {
        return true;
    }

    auto [sstable_path, sst_file_ptr] = _filePool->acquire();
    std::ofstream& sst_file = *sst_file_ptr;

    if (!buffer.empty()) {
        sst_file.rdbuf()->pubsetbuf(buffer.data(), buffer.size());
    }

    if (!sst_file) {
        std::cerr << "[SSTableManager] ERROR: Failed to acquire SSTable file: " << sstable_path
                  << std::endl;
        return false;
    }

    L0Index new_index;
    new_index.path = sstable_path;
    new_index.offsets.reserve(memtable.count());

    std::string serialization_buffer;
    serialization_buffer.reserve(1024 * 64);

    const auto& data = memtable.getData();
    for (const auto& [key, value] : data) {
        uint64_t current_offset = sst_file.tellp();
        new_index.offsets.emplace_back(key, current_offset);

        uint32_t key_len = static_cast<uint32_t>(key.size());
        uint32_t val_len = static_cast<uint32_t>(value.size());

        serialization_buffer.clear();
        serialization_buffer.append(reinterpret_cast<const char*>(&key_len), sizeof(key_len));
        serialization_buffer.append(key.data(), key_len);
        serialization_buffer.append(reinterpret_cast<const char*>(&val_len), sizeof(val_len));
        serialization_buffer.append(value.data(), val_len);

        sst_file.write(serialization_buffer.data(), serialization_buffer.size());
    }

    sst_file.flush();
    _fileCloser->scheduleClose(std::move(sst_file_ptr));

    std::sort(
        new_index.offsets.begin(), new_index.offsets.end(),
        [](const std::pair<std::string, uint64_t>& a, const std::pair<std::string, uint64_t>& b) {
            if (a.first != b.first) return a.first < b.first;
            return a.second > b.second;
        });

    auto last =
        std::unique(new_index.offsets.begin(), new_index.offsets.end(),
                    [](const std::pair<std::string, uint64_t>& a,
                       const std::pair<std::string, uint64_t>& b) { return a.first == b.first; });
    new_index.offsets.erase(last, new_index.offsets.end());

    // Lock-free prepend (LIFO)
    IndexNode* newNode = new IndexNode(std::move(new_index));
    newNode->next = _head.load(std::memory_order_relaxed);
    while (!_head.compare_exchange_weak(newNode->next, newNode, std::memory_order_release,
                                        std::memory_order_relaxed));
    return true;
}

void SSTableManager::close() {
    _fileCloser.reset();
    _filePool.reset();
}

bool SSTableManager::get(const std::string& key, std::string& value) {
    // Traverse the linked list (Newest -> Oldest)
    IndexNode* curr = _head.load(std::memory_order_acquire);
    while (curr) {
        const auto& offsets = curr->index.offsets;
        auto offset_it = std::lower_bound(offsets.begin(), offsets.end(), key,
                                          [](const std::pair<std::string, uint64_t>& entry,
                                             const std::string& val) { return entry.first < val; });

        if (offset_it != offsets.end() && offset_it->first == key) {
            if (readValueAt(curr->index.path, offset_it->second, key, value)) {
                return true;
            }
        }
        curr = curr->next;
    }
    return false;
}

bool SSTableManager::scan(const std::string& prefix, std::map<std::string, std::string>& results,
                          std::set<std::string>& deleted_keys) {
    bool found_any = false;
    IndexNode* curr = _head.load(std::memory_order_acquire);

    while (curr) {
        const auto& offsets = curr->index.offsets;
        auto it_idx = std::lower_bound(offsets.begin(), offsets.end(), prefix,
                                       [](const std::pair<std::string, uint64_t>& entry,
                                          const std::string& val) { return entry.first < val; });

        for (; it_idx != offsets.end(); ++it_idx) {
            const auto& key = it_idx->first;
            uint64_t offset = it_idx->second;

            if (key.compare(0, prefix.size(), prefix) != 0) break;

            if (results.find(key) == results.end() &&
                deleted_keys.find(key) == deleted_keys.end()) {
                std::string val_from_disk;
                if (readValueAt(curr->index.path, offset, key, val_from_disk)) {
                    if (val_from_disk == MEMTABLE_TOMBSTONE) {
                        deleted_keys.insert(key);
                    } else {
                        results[key] = val_from_disk;
                        found_any = true;
                    }
                }
            }
        }
        curr = curr->next;
    }
    return found_any;
}

bool SSTableManager::readValueAt(const std::string& sstable_path, uint64_t offset,
                                 const std::string& key, std::string& out_value) {
    std::ifstream sst_file(sstable_path, std::ios::binary);
    if (!sst_file) {
        std::cerr << "ERROR: Failed to open SSTable for read: " << sstable_path << std::endl;
        return false;
    }

    sst_file.seekg(offset);
    if (sst_file.fail()) return false;

    uint32_t key_len;
    sst_file.read(reinterpret_cast<char*>(&key_len), sizeof(key_len));
    if (sst_file.fail()) return false;

    std::string key_from_file(key_len, '\0');
    sst_file.read(&key_from_file[0], key_len);
    if (sst_file.fail()) return false;

    if (key_from_file != key) {
        std::cerr << "ERROR: Index mismatch! Expected " << key << " found " << key_from_file
                  << std::endl;
        return false;
    }

    uint32_t val_len;
    sst_file.read(reinterpret_cast<char*>(&val_len), sizeof(val_len));
    if (sst_file.fail()) return false;

    std::string val_from_file(val_len, '\0');
    sst_file.read(&val_from_file[0], val_len);
    if (sst_file.fail()) return false;

    out_value = val_from_file;
    return true;
}

void SSTableManager::recoverState(size_t filePoolSize, size_t preAllocBytes) {
    uint64_t max_id = 0;

    if (std::filesystem::exists(_dbPath)) {
        std::vector<std::pair<uint64_t, std::string>> found_files;
        for (const auto& entry : std::filesystem::directory_iterator(_dbPath)) {
            std::string filename = entry.path().filename().string();
            if (filename.rfind("L0-", 0) == 0 && filename.rfind(".sst") == filename.size() - 4) {
                try {
                    uint64_t id = std::stoull(filename.substr(3, filename.size() - 7));
                    found_files.push_back({id, entry.path().string()});
                    if (id > max_id) max_id = id;
                } catch (...) {
                }
            }
        }

        // Sort files by ID (Oldest to Newest)
        std::sort(found_files.begin(), found_files.end());
        std::cout << "[NATIVE] Recovering state. Indexing " << found_files.size() << " SSTables..."
                  << std::endl;

        for (const auto& [id, path] : found_files) {
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

                    sst_file.seekg(val_len, std::ios::cur);  // Skip value

                    new_index.offsets.emplace_back(key, current_offset);
                }
            }

            std::sort(new_index.offsets.begin(), new_index.offsets.end(),
                      [](const std::pair<std::string, uint64_t>& a,
                         const std::pair<std::string, uint64_t>& b) {
                          if (a.first != b.first) return a.first < b.first;
                          return a.second > b.second;
                      });

            auto last = std::unique(
                new_index.offsets.begin(), new_index.offsets.end(),
                [](const std::pair<std::string, uint64_t>& a,
                   const std::pair<std::string, uint64_t>& b) { return a.first == b.first; });
            new_index.offsets.erase(last, new_index.offsets.end());

            // Prepend during recovery to maintain newest-to-oldest order
            // Since we iterate found_files Oldest -> Newest, prepending each results in Newest at
            // head.
            IndexNode* newNode = new IndexNode(std::move(new_index));
            newNode->next = _head.load(std::memory_order_relaxed);
            _head.store(newNode, std::memory_order_relaxed);
        }
        std::cout << "[NATIVE] Recovery complete." << std::endl;
    }

    _filePool =
        std::make_unique<FilePool>(_dbPath, "L0-", ".sst", filePoolSize, max_id + 1, preAllocBytes);
    _fileCloser = std::make_unique<FileCloser>(filePoolSize);
}

}  // namespace lsmio