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

#ifndef _LSMIO_SSTABLE_MANAGER_HPP_
#define _LSMIO_SSTABLE_MANAGER_HPP_

#include <atomic>
#include <map>
#include <memory>
#include <set>
#include <string>
#include <vector>

#include "FileCloser.hpp"
#include "FilePool.hpp"
#include "IMemtable.hpp"

namespace lsmio {

class SSTableManager {
  public:
    static constexpr uint32_t FOOTER_MAGIC = 0x4C534D49;

    // Size of the speculative single-pass pread buffer in readValueAt(). Sized
    // with headroom over the current benchmark default (8 + 16-byte key +
    // 65535-byte value = 65559 B) so the common case never falls back to a
    // second pread (BUG-3). It is a fixed constant, not a config-derived
    // value: LSMIOConfig::getMaxValueLen() is a write-buffer capacity ceiling
    // (~127 MB by default), not a record-size estimate, and would be
    // actively wrong to use here. Any record whose framing + key + value
    // exceeds this still falls back to the correct (but slower) two-pread
    // path — see getPreadSlowPathCount() for visibility into how often that
    // happens.
    static constexpr size_t PREAD_SPECULATIVE_BUF_SIZE = 128 * 1024;

    SSTableManager(const std::string& f_db_path, size_t f_file_pool_size, size_t f_pre_alloc_bytes);
    ~SSTableManager();

    // Flush a memtable to disk as a new SSTable
    // Uses the provided buffer for I/O buffering
    bool flushMemtable(const IMemtable& f_memtable, std::vector<char>& f_buffer);

    // Read a value from disk
    // Returns true if found (populates value).
    // If found and value is TOMBSTONE, returns true and value is MEMTABLE_TOMBSTONE.
    bool get(const std::string& f_key, std::string& f_value);

    // Scan for prefix
    // Populates results and deleted_keys
    // Returns true if any keys were found (including deleted ones)
    bool scan(const std::string& f_prefix, std::map<std::string, std::string>& f_results,
              std::set<std::string>& f_deleted_keys);

    void close();

    // Count of pread() reads that exceeded PREAD_SPECULATIVE_BUF_SIZE and
    // fell back to the second, tail-fetching pread (BUG-3's slow path).
    // A nonzero, growing count on a workload expected to fit in one pass is
    // the signal that the fixed buffer size is now undersized for the
    // configured record size.
    uint64_t getPreadSlowPathCount() const noexcept {
        return m_pread_slow_path_count.load(std::memory_order_relaxed);
    }

  private:
    std::string m_db_path;
    std::unique_ptr<FilePool> m_file_pool;
    std::unique_ptr<FileCloser> m_file_closer;

    struct L0Index {
        std::string path;
        // Sorted vector of {key, offset}
        std::vector<std::pair<std::string, uint64_t>> offsets;
    };

    struct IndexNode {
        L0Index index;
        IndexNode* next{nullptr};

        // Persistent Reader Resources
        int m_read_fd{-1};
        char* m_mmap_ptr{nullptr};
        size_t m_mmap_len{0};

        explicit IndexNode(L0Index&& idx);
        ~IndexNode();

        // Non-copyable, non-movable to guarantee resource ownership
        IndexNode(const IndexNode&) = delete;
        IndexNode& operator=(const IndexNode&) = delete;
        IndexNode(IndexNode&&) = delete;
        IndexNode& operator=(IndexNode&&) = delete;

        // Lifecycle Management
        void initReader(bool f_enable_mmap, bool f_enable_pread);
        void closeReader() noexcept;
    };

    std::atomic<IndexNode*> m_head{nullptr};
    std::atomic<uint64_t> m_pread_slow_path_count{0};

    // Helper to read from specific node/offset
    bool readValueAt(const IndexNode& f_node, uint64_t f_offset, const std::string& f_key,
                     std::string& f_out_value);

    // Backward-compatible stream fallback overload
    bool readValueAt(const std::string& f_path, uint64_t f_offset, const std::string& f_key,
                     std::string& f_out_value);

    // Internal recovery
    void recoverState(size_t f_file_pool_size, size_t f_pre_alloc_bytes);
};

}  // namespace lsmio

#endif