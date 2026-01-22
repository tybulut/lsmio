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

#include "file_closer.hpp"
#include "file_pool.hpp"
#include "memtable.hpp"

namespace lsmio {

class SSTableManager {
  public:
    SSTableManager(const std::string& dbPath, size_t filePoolSize, size_t preAllocBytes);
    ~SSTableManager();

    // Flush a memtable to disk as a new SSTable
    // Uses the provided buffer for I/O buffering
    bool flushMemtable(const Memtable& memtable, std::vector<char>& buffer);

    // Read a value from disk
    // Returns true if found (populates value).
    // If found and value is TOMBSTONE, returns true and value is MEMTABLE_TOMBSTONE.
    bool get(const std::string& key, std::string& value);

    // Scan for prefix
    // Populates results and deleted_keys
    // Returns true if any keys were found (including deleted ones)
    bool scan(const std::string& prefix, std::map<std::string, std::string>& results,
              std::set<std::string>& deleted_keys);

    void close();

  private:
    std::string _dbPath;
    std::unique_ptr<FilePool> _filePool;
    std::unique_ptr<FileCloser> _fileCloser;

    struct L0Index {
        std::string path;
        // Sorted vector of {key, offset}
        std::vector<std::pair<std::string, uint64_t>> offsets;
    };

    struct IndexNode {
        L0Index index;
        IndexNode* next;
        IndexNode(L0Index&& idx) : index(std::move(idx)), next(nullptr) {}
    };

    std::atomic<IndexNode*> _head{nullptr};

    // Helper to read from specific file/offset
    bool readValueAt(const std::string& path, uint64_t offset, const std::string& key,
                     std::string& out_value);

    // Internal recovery
    void recoverState(size_t filePoolSize, size_t preAllocBytes);
};

}  // namespace lsmio

#endif