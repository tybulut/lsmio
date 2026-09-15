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

#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

#include <algorithm>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <lsmio/lsmio.hpp>
#include <lsmio/manager/store/native/SSTableManager.hpp>

namespace {

// On-disk format sanity bounds for deserialization. These are fixed format
// constants, deliberately independent of the runtime-mutable gConfigLSMIO
// limits: a file written under one configuration must stay readable under
// another. They only exist to stop corrupt length fields from triggering
// multi-GB allocations, so they must remain above any configurable
// write-side limit (keys <= maxKeyLen, values <= getMaxValueLen() <=
// writeBufferSize which is int-sized).
constexpr uint32_t READ_MAX_KEY_LEN = 64 * 1024 * 1024;
constexpr uint32_t READ_MAX_VAL_LEN = 0x7FFFFFFF;

inline void packLe32(uint32_t f_val, char* f_buf) {
    f_buf[0] = static_cast<char>(f_val & 0xFF);
    f_buf[1] = static_cast<char>((f_val >> 8) & 0xFF);
    f_buf[2] = static_cast<char>((f_val >> 16) & 0xFF);
    f_buf[3] = static_cast<char>((f_val >> 24) & 0xFF);
}

inline uint32_t unpackLe32(const char* f_buf) {
    return static_cast<uint32_t>(static_cast<uint8_t>(f_buf[0])) |
           (static_cast<uint32_t>(static_cast<uint8_t>(f_buf[1])) << 8) |
           (static_cast<uint32_t>(static_cast<uint8_t>(f_buf[2])) << 16) |
           (static_cast<uint32_t>(static_cast<uint8_t>(f_buf[3])) << 24);
}

inline void packLe64(uint64_t f_val, char* f_buf) {
    f_buf[0] = static_cast<char>(f_val & 0xFF);
    f_buf[1] = static_cast<char>((f_val >> 8) & 0xFF);
    f_buf[2] = static_cast<char>((f_val >> 16) & 0xFF);
    f_buf[3] = static_cast<char>((f_val >> 24) & 0xFF);
    f_buf[4] = static_cast<char>((f_val >> 32) & 0xFF);
    f_buf[5] = static_cast<char>((f_val >> 40) & 0xFF);
    f_buf[6] = static_cast<char>((f_val >> 48) & 0xFF);
    f_buf[7] = static_cast<char>((f_val >> 56) & 0xFF);
}

inline uint64_t unpackLe64(const char* f_buf) {
    return static_cast<uint64_t>(static_cast<uint8_t>(f_buf[0])) |
           (static_cast<uint64_t>(static_cast<uint8_t>(f_buf[1])) << 8) |
           (static_cast<uint64_t>(static_cast<uint8_t>(f_buf[2])) << 16) |
           (static_cast<uint64_t>(static_cast<uint8_t>(f_buf[3])) << 24) |
           (static_cast<uint64_t>(static_cast<uint8_t>(f_buf[4])) << 32) |
           (static_cast<uint64_t>(static_cast<uint8_t>(f_buf[5])) << 40) |
           (static_cast<uint64_t>(static_cast<uint8_t>(f_buf[6])) << 48) |
           (static_cast<uint64_t>(static_cast<uint8_t>(f_buf[7])) << 56);
}

inline bool readLe32(std::ifstream& f_file, uint32_t& f_out) {
    char buf4[4];
    f_file.read(buf4, 4);
    if (f_file.fail()) return false;
    f_out = unpackLe32(buf4);
    return true;
}

inline void appendLe32(std::string& f_buf, uint32_t f_val) {
    char buf4[4];
    packLe32(f_val, buf4);
    f_buf.append(buf4, 4);
}

inline void appendLe64(std::string& f_buf, uint64_t f_val) {
    char buf8[8];
    packLe64(f_val, buf8);
    f_buf.append(buf8, 8);
}

// Comparator for lower_bound over the sorted (key, offset) index.
struct OffsetEntryKeyLess {
    bool operator()(const std::pair<std::string, uint64_t>& f_entry,
                    const std::string& f_key) const {
        return f_entry.first < f_key;
    }
};

// Sort by key; for duplicate keys keep only the newest record (highest
// offset). Shared by flush and recovery so both resolve duplicates to the
// same physical record.
void dedupOffsets(std::vector<std::pair<std::string, uint64_t>>& f_offsets) {
    std::sort(f_offsets.begin(), f_offsets.end(),
              [](const std::pair<std::string, uint64_t>& a,
                 const std::pair<std::string, uint64_t>& b) {
                  if (a.first != b.first) return a.first < b.first;
                  return a.second > b.second;
              });

    auto last = std::unique(f_offsets.begin(), f_offsets.end(),
                            [](const std::pair<std::string, uint64_t>& a,
                               const std::pair<std::string, uint64_t>& b) {
                                return a.first == b.first;
                            });
    f_offsets.erase(last, f_offsets.end());
}

// Attempts the Dense Index Footer fast path. On success fills f_offsets,
// shrinks f_file_size to the end of the data section (footer excluded) and
// returns true. On any validation failure returns false with f_offsets empty
// and f_file_size untouched, so the caller can fall back to the full scan.
bool tryLoadFooterIndex(std::ifstream& f_file, uint64_t& f_file_size,
                        std::vector<std::pair<std::string, uint64_t>>& f_offsets) {
    if (f_file_size < 12) return false;

    char buf8[8];
    uint32_t magic_bytes;
    f_file.seekg(f_file_size - 4);
    if (!readLe32(f_file, magic_bytes) || magic_bytes != lsmio::SSTableManager::FOOTER_MAGIC) {
        return false;
    }

    f_file.seekg(f_file_size - 12);
    f_file.read(buf8, 8);
    if (f_file.fail()) return false;
    uint64_t footer_offset = unpackLe64(buf8);
    if (footer_offset >= f_file_size - 12) return false;

    f_file.seekg(footer_offset);
    uint32_t num_entries;
    if (!readLe32(f_file, num_entries)) return false;

    uint64_t index_size = (f_file_size - 12) - (footer_offset + 4);
    if (index_size > 256ULL * 1024ULL * 1024ULL) return false;

    std::vector<char> index_buffer(index_size);
    f_file.read(index_buffer.data(), index_size);
    if (f_file.fail()) return false;

    const char* ptr = index_buffer.data();
    const char* end = index_buffer.data() + index_size;

    for (uint32_t i = 0; i < num_entries; ++i) {
        if (ptr + 4 > end) {
            f_offsets.clear();
            return false;
        }
        uint32_t key_len = unpackLe32(ptr);
        ptr += 4;

        if (key_len > READ_MAX_KEY_LEN || ptr + key_len > end) {
            f_offsets.clear();
            return false;
        }
        std::string key(ptr, key_len);
        ptr += key_len;

        if (ptr + 8 > end) {
            f_offsets.clear();
            return false;
        }
        uint64_t offset = unpackLe64(ptr);
        ptr += 8;

        f_offsets.emplace_back(std::move(key), offset);
    }

    // The declared entry count must consume the index block exactly.
    if (ptr != end) {
        f_offsets.clear();
        return false;
    }

    f_file_size = footer_offset;
    return true;
}

}  // namespace

namespace lsmio {

SSTableManager::IndexNode::IndexNode(L0Index&& idx) : index(std::move(idx)) {}

SSTableManager::IndexNode::~IndexNode() {
    closeReader();
}

void SSTableManager::IndexNode::initReader(bool f_enable_mmap, bool f_enable_pread) {
    if (f_enable_mmap) {
        int fd = ::open(index.path.c_str(), O_RDONLY);
        if (fd >= 0) {
            struct stat st;
            bool stat_ok = (::fstat(fd, &st) == 0);
            if (stat_ok && st.st_size > 0) {
                void* ptr = ::mmap(nullptr, static_cast<size_t>(st.st_size), PROT_READ, MAP_SHARED, fd, 0);
                if (ptr != MAP_FAILED) {
                    m_mmap_ptr = static_cast<char*>(ptr);
                    m_mmap_len = static_cast<size_t>(st.st_size);
                    ::posix_madvise(m_mmap_ptr, m_mmap_len, POSIX_MADV_WILLNEED);
                    if (!f_enable_pread) {
                        ::close(fd);
                        fd = -1;
                    } else {
                        m_read_fd = fd;
                        fd = -1;
                    }
                }
            }
            if (fd >= 0) {
                if (f_enable_pread && stat_ok && st.st_size > 0) {
                    m_read_fd = fd;
                } else {
                    ::close(fd);
                }
            }
        }
    } else if (f_enable_pread) {
        m_read_fd = ::open(index.path.c_str(), O_RDONLY);
    }
}

void SSTableManager::IndexNode::closeReader() noexcept {
    if (m_mmap_ptr != nullptr && m_mmap_ptr != MAP_FAILED) {
        ::munmap(m_mmap_ptr, m_mmap_len);
        m_mmap_ptr = nullptr;
        m_mmap_len = 0;
    }
    if (m_read_fd >= 0) {
        ::close(m_read_fd);
        m_read_fd = -1;
    }
}

SSTableManager::SSTableManager(const std::string& f_db_path, size_t f_file_pool_size, size_t f_pre_alloc_bytes)
    : m_db_path(f_db_path) {
    recoverState(f_file_pool_size, f_pre_alloc_bytes);
}

SSTableManager::~SSTableManager() {
    IndexNode* curr = m_head.load(std::memory_order_relaxed);
    while (curr) {
        IndexNode* next = curr->next;
        delete curr;
        curr = next;
    }
}

bool SSTableManager::flushMemtable(const IMemtable& f_memtable, std::vector<char>& f_buffer) {
    if (f_memtable.empty()) {
        return true;
    }

    // Snapshot the flags so a mid-flush config mutation cannot desync the
    // write/offset/footer decisions from each other.
    const bool manual_offset = gConfigLSMIO.manualOffset;
    const bool footer_index = gConfigLSMIO.footerIndex;
    const bool pre_allocate = gConfigLSMIO.preAllocate;

    auto [sstable_path, sst_file_ptr] = m_file_pool->acquire();
    std::ofstream& sst_file = *sst_file_ptr;

    if (!f_buffer.empty()) {
        sst_file.rdbuf()->pubsetbuf(f_buffer.data(), f_buffer.size());
    }

    if (!sst_file) {
        std::cerr << "[SSTableManager] ERROR: Failed to acquire SSTable file: " << sstable_path
                  << std::endl;
        return false;
    }

    L0Index new_index;
    new_index.path = sstable_path;
    new_index.offsets.reserve(f_memtable.count());

    std::string record_buf;
    uint64_t current_offset = sst_file.tellp();

    f_memtable.forEach([&](const std::string& f_key, const std::string& f_value) {
        if (!manual_offset) {
            current_offset = static_cast<uint64_t>(sst_file.tellp());
        }
        new_index.offsets.emplace_back(f_key, current_offset);

        record_buf.clear();
        appendLe32(record_buf, static_cast<uint32_t>(f_key.size()));
        record_buf.append(f_key);
        appendLe32(record_buf, static_cast<uint32_t>(f_value.size()));
        record_buf.append(f_value);
        sst_file.write(record_buf.data(), record_buf.size());

        if (manual_offset) {
            current_offset += record_buf.size();
        }
    });

    if (footer_index) {
        uint64_t footer_offset = current_offset;
        if (!manual_offset) {
            footer_offset = static_cast<uint64_t>(sst_file.tellp());
        }

        record_buf.clear();
        appendLe32(record_buf, static_cast<uint32_t>(new_index.offsets.size()));
        sst_file.write(record_buf.data(), record_buf.size());

        for (const auto& entry : new_index.offsets) {
            record_buf.clear();
            appendLe32(record_buf, static_cast<uint32_t>(entry.first.size()));
            record_buf.append(entry.first);
            appendLe64(record_buf, entry.second);
            sst_file.write(record_buf.data(), record_buf.size());
        }

        record_buf.clear();
        appendLe64(record_buf, footer_offset);
        appendLe32(record_buf, SSTableManager::FOOTER_MAGIC);
        sst_file.write(record_buf.data(), record_buf.size());
    }

    sst_file.flush();
    if (sst_file.fail()) {
        std::cerr << "[SSTableManager] ERROR: Failed to write or flush SSTable: " << sstable_path
                  << std::endl;
        sst_file.close();
        std::filesystem::remove(sstable_path);
        return false;
    }

    if (pre_allocate) {
        uint64_t final_eof = static_cast<uint64_t>(sst_file.tellp());
        sst_file.close();
        std::error_code ec;
        std::filesystem::resize_file(sstable_path, final_eof, ec);
        if (ec) {
            // The data is fully written and flushed; only the preallocation
            // padding could not be trimmed. Keep the file: this session's
            // index is valid, and recovery treats the zero padding as
            // end-of-data. Deleting here would destroy durable data.
            std::cerr << "[SSTableManager] WARNING: Failed to trim preallocated SSTable "
                      << sstable_path << ": " << ec.message()
                      << " (data intact; footer fast-path recovery disabled for this file)"
                      << std::endl;
        }
    } else {
        m_file_closer->scheduleClose(std::move(sst_file_ptr));
    }

    dedupOffsets(new_index.offsets);

    IndexNode* new_node = new IndexNode(std::move(new_index));
    new_node->initReader(gConfigLSMIO.enableMMAP, gConfigLSMIO.enablePread);
    IndexNode* old_head = m_head.load(std::memory_order_relaxed);
    do {
        new_node->next = old_head;
    } while (!m_head.compare_exchange_weak(old_head, new_node, std::memory_order_release, std::memory_order_relaxed));
    return true;
}

void SSTableManager::close() {
    m_file_closer.reset();
    m_file_pool.reset();
}

bool SSTableManager::get(const std::string& f_key, std::string& f_value) {
    // Traverse the linked list (Newest -> Oldest)
    IndexNode* curr = m_head.load(std::memory_order_acquire);
    while (curr) {
        const auto& offsets = curr->index.offsets;
        auto offset_it =
            std::lower_bound(offsets.begin(), offsets.end(), f_key, OffsetEntryKeyLess{});

        if (offset_it != offsets.end() && offset_it->first == f_key) {
            if (readValueAt(*curr, offset_it->second, f_key, f_value)) {
                return true;
            }
        }
        curr = curr->next;
    }
    return false;
}

bool SSTableManager::scan(const std::string& f_prefix, std::map<std::string, std::string>& f_results,
                          std::set<std::string>& f_deleted_keys) {
    bool found_any = false;
    IndexNode* curr = m_head.load(std::memory_order_acquire);

    while (curr) {
        const auto& offsets = curr->index.offsets;
        auto it_idx =
            std::lower_bound(offsets.begin(), offsets.end(), f_prefix, OffsetEntryKeyLess{});

        for (; it_idx != offsets.end(); ++it_idx) {
            const auto& key = it_idx->first;
            uint64_t offset = it_idx->second;

            if (key.compare(0, f_prefix.size(), f_prefix) != 0) break;

            if (f_results.find(key) == f_results.end() &&
                f_deleted_keys.find(key) == f_deleted_keys.end()) {
                std::string val_from_disk;
                if (readValueAt(*curr, offset, key, val_from_disk)) {
                    if (val_from_disk == MEMTABLE_TOMBSTONE) {
                        f_deleted_keys.insert(key);
                    } else {
                        f_results[key] = val_from_disk;
                        found_any = true;
                    }
                }
            }
        }
        curr = curr->next;
    }
    return found_any;
}

bool SSTableManager::readValueAt(const IndexNode& f_node, uint64_t f_offset,
                                 const std::string& f_key, std::string& f_out_value) {
    if (f_node.m_mmap_ptr != nullptr) {
        if (f_offset > f_node.m_mmap_len || f_node.m_mmap_len - f_offset < 8) {
            return false;
        }

        uint32_t key_len = unpackLe32(f_node.m_mmap_ptr + f_offset);
        if (key_len != f_key.size() || key_len > READ_MAX_KEY_LEN ||
            f_node.m_mmap_len - (f_offset + 8) < key_len) {
            return false;
        }

        if (std::memcmp(f_node.m_mmap_ptr + f_offset + 4, f_key.data(), key_len) != 0) {
            return false;
        }

        uint32_t val_len = unpackLe32(f_node.m_mmap_ptr + f_offset + 4 + key_len);
        if (val_len > READ_MAX_VAL_LEN ||
            f_node.m_mmap_len - (f_offset + 8 + key_len) < val_len) {
            return false;
        }

        f_out_value.assign(f_node.m_mmap_ptr + f_offset + 8 + key_len, val_len);
        return true;
    } else if (f_node.m_read_fd >= 0) {
        constexpr size_t PREAD_SPECULATIVE_BUF_SIZE = 64 * 1024;
        char stack_buf[PREAD_SPECULATIVE_BUF_SIZE];
        ssize_t bytes_read = ::pread(f_node.m_read_fd, stack_buf, sizeof(stack_buf), f_offset);
        if (bytes_read < static_cast<ssize_t>(8 + f_key.size())) {
            return false;
        }

        uint32_t key_len = unpackLe32(stack_buf);
        if (key_len != f_key.size() || key_len > READ_MAX_KEY_LEN) {
            return false;
        }

        if (std::memcmp(stack_buf + 4, f_key.data(), key_len) != 0) {
            return false;
        }

        uint32_t val_len = unpackLe32(stack_buf + 4 + key_len);
        if (val_len > READ_MAX_VAL_LEN) {
            return false;
        }

        uint64_t total_record_len = 8ULL + key_len + val_len;
        if (static_cast<uint64_t>(bytes_read) >= total_record_len) {
            f_out_value.assign(stack_buf + 8 + key_len, val_len);
            return true;
        } else {
            f_out_value.resize(val_len);
            uint64_t val_in_buf = static_cast<uint64_t>(bytes_read) - (8ULL + key_len);
            std::memcpy(f_out_value.data(), stack_buf + 8 + key_len, val_in_buf);
            uint64_t remaining_bytes = val_len - val_in_buf;
            uint64_t second_offset = f_offset + static_cast<uint64_t>(bytes_read);
            ssize_t n2 = ::pread(f_node.m_read_fd, f_out_value.data() + val_in_buf,
                                 remaining_bytes, second_offset);
            if (n2 != static_cast<ssize_t>(remaining_bytes)) {
                f_out_value.clear();
                return false;
            }
            return true;
        }
    } else {
        return readValueAt(f_node.index.path, f_offset, f_key, f_out_value);
    }
}

bool SSTableManager::readValueAt(const std::string& f_path, uint64_t f_offset,
                                 const std::string& f_key, std::string& f_out_value) {
    std::ifstream sst_file(f_path, std::ios::binary);
    if (!sst_file) {
        std::cerr << "ERROR: Failed to open SSTable for read: " << f_path << std::endl;
        return false;
    }

    sst_file.seekg(f_offset);
    if (sst_file.fail()) return false;

    uint32_t key_len;
    if (!readLe32(sst_file, key_len)) return false;
    if (key_len > READ_MAX_KEY_LEN) return false;

    std::string key_from_file(key_len, '\0');
    sst_file.read(key_from_file.data(), key_len);
    if (sst_file.fail()) return false;

    if (key_from_file != f_key) {
        std::cerr << "ERROR: Index mismatch! Expected " << f_key << " found " << key_from_file
                  << std::endl;
        return false;
    }

    uint32_t val_len;
    if (!readLe32(sst_file, val_len)) return false;
    if (val_len > READ_MAX_VAL_LEN) return false;

    f_out_value.resize(val_len);
    sst_file.read(f_out_value.data(), val_len);
    if (sst_file.fail()) {
        f_out_value.clear();
        return false;
    }
    return true;
}

void SSTableManager::recoverState(size_t f_file_pool_size, size_t f_pre_alloc_bytes) {
    uint64_t max_id = 0;

    if (std::filesystem::exists(m_db_path)) {
        std::vector<std::pair<uint64_t, std::string>> found_files;
        for (const auto& entry : std::filesystem::directory_iterator(m_db_path)) {
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
                sst_file.seekg(0, std::ios::end);
                uint64_t file_size = sst_file.tellg();

                if (!tryLoadFooterIndex(sst_file, file_size, new_index.offsets)) {
                    sst_file.clear();
                    sst_file.seekg(0, std::ios::beg);

                    while (static_cast<uint64_t>(sst_file.tellg()) < file_size &&
                           sst_file.peek() != EOF) {
                        uint64_t current_offset = sst_file.tellg();

                        uint32_t key_len;
                        if (!readLe32(sst_file, key_len)) break;
                        if (key_len > READ_MAX_KEY_LEN) break;

                        std::string key(key_len, '\0');
                        sst_file.read(key.data(), key_len);
                        if (sst_file.fail()) break;

                        uint32_t val_len;
                        if (!readLe32(sst_file, val_len)) break;
                        if (val_len > READ_MAX_VAL_LEN) break;

                        // A zero-length key and value marks the zero padding
                        // of a preallocated file that could not be trimmed:
                        // end of real data.
                        if (key_len == 0 && val_len == 0) break;

                        sst_file.seekg(val_len, std::ios::cur);  // Skip value

                        new_index.offsets.emplace_back(std::move(key), current_offset);
                    }
                }
            }

            dedupOffsets(new_index.offsets);

            // Prepend during recovery to maintain newest-to-oldest order
            // Since we iterate found_files Oldest -> Newest, prepending each results in Newest at
            // head. No mutex needed during initialization single-thread context.
            IndexNode* new_node = new IndexNode(std::move(new_index));
            new_node->initReader(gConfigLSMIO.enableMMAP, gConfigLSMIO.enablePread);
            IndexNode* old_head = m_head.load(std::memory_order_relaxed);
            new_node->next = old_head;
            m_head.store(new_node, std::memory_order_relaxed);
        }
        std::cout << "[NATIVE] Recovery complete." << std::endl;
    }

    m_file_pool =
        std::make_unique<FilePool>(m_db_path, "L0-", ".sst", f_file_pool_size, max_id + 1, f_pre_alloc_bytes);
    m_file_closer = std::make_unique<FileCloser>(f_file_pool_size);
}

}  // namespace lsmio
