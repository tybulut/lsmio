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

#ifndef _LSMIO_STORE_NATIVE_HPP_
#define _LSMIO_STORE_NATIVE_HPP_

#include <atomic>
#include <condition_variable>
#include <deque>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "file_closer.hpp"
#include "file_pool.hpp"
#include "store.hpp"

namespace lsmio {

class LSMIOStoreNative : public LSMIOStore {
  private:
    // LSMTree Logic
    // Using vector instead of map for O(1) amortized append during Put.
    // Sorting happens in the background Flush thread.
    using Memtable = std::vector<std::pair<std::string, std::string>>;

    size_t _memtable_max_size_bytes;
    size_t _max_immutable_memtables;

    std::unique_ptr<Memtable> _active_memtable;
    std::atomic<size_t> _active_memtable_size{0};
    std::deque<std::unique_ptr<Memtable>> _immutable_memtables;

    std::vector<std::string> _l0_files;

    // In-memory index for L0 files (Bitcask style: key -> file_offset)
    struct L0Index {
        std::string path;
        // Optimization: Use sorted vector instead of map for batch indexing & cache locality
        std::vector<std::pair<std::string, uint64_t>> offsets;
    };
    std::vector<L0Index> _l0_indices;  // Parallel to _l0_files

    std::atomic<uint64_t> _next_sstable_id{0};
    std::unique_ptr<FilePool> _file_pool;
    std::unique_ptr<FileCloser> _file_closer;

    std::mutex _state_mutex;
    std::vector<char> _flush_buffer;
    std::thread _flush_thread;
    std::condition_variable _flush_cv;
    std::condition_variable _backpressure_cv;
    std::condition_variable _barrier_cv;
    std::atomic<bool> _shutting_down{false};
    std::atomic<bool> _flush_in_progress{false};

    void FlushWorkLoop();
    void FlushMemtableToL0(std::unique_ptr<Memtable> memtable);
    bool ReadValueAt(const std::string& sstable_path, uint64_t offset, const std::string& key,
                     std::string& out_value);
    void RecoverStateFromDisk();

    // LSMIOStore Overrides
    bool startBatch() override;
    bool stopBatch() override;
    bool _batchMutation(MutationType mType, const std::string key, const std::string value,
                        bool flush) override;
    bool dbCleanup() override;

  public:
    LSMIOStoreNative(const std::string& dbPath, const bool overWrite = false);
    ~LSMIOStoreNative() override;

    void close() override;

    bool get(const std::string key, std::string* value) override;
    bool getPrefix(const std::string key,
                   std::vector<std::tuple<std::string, std::string>>* values) override;

    bool readBarrier() override;
    bool writeBarrier() override;
};

}  // namespace lsmio

#endif