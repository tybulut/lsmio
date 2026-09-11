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
#include <lsmio/manager/store/store.hpp>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <tlx/container/btree_map.hpp>
#include <vector>

#include "FileCloser.hpp"
#include "FilePool.hpp"
#include "MemtableOrdered.hpp"
#include "MemtableVectorNoSort.hpp"
#include "MemtableVectorSort.hpp"
#include "SSTableManager.hpp"

#ifndef LUSTRE_SUPER_MAGIC
#define LUSTRE_SUPER_MAGIC 0x0BD00BD0
#endif

#ifndef GPFS_SUPER_MAGIC
#define GPFS_SUPER_MAGIC 0x47504653
#endif

namespace lsmio {

class LSMIOStoreNative : public LSMIOStore {
  private:
    // LSMTree Logic
    size_t m_memtable_max_size_bytes;
    size_t m_max_immutable_memtables;

    // Entry-size limits, snapshotted from gConfigLSMIO at construction so the
    // hot write path neither re-derives them per put nor races config mutations.
    size_t m_max_key_len;
    size_t m_max_value_len;

    std::unique_ptr<IMemtable> m_active_memtable;
    std::deque<std::unique_ptr<IMemtable>> m_immutable_memtables;

    std::unique_ptr<SSTableManager> m_sstable_manager;
    std::unique_ptr<IMemtable> createMemtable() const;

    std::mutex m_state_mutex;
    std::vector<char> m_flush_buffer;
    std::thread m_flush_thread;
    std::condition_variable m_flush_cv;
    std::condition_variable m_backpressure_cv;
    std::condition_variable m_barrier_cv;
    std::atomic<bool> m_shutting_down{false};
    std::atomic<bool> m_flush_in_progress{false};
    std::atomic<bool> m_bg_error{false};

    void FlushWorkLoop();
    void FlushMemtableToL0(std::unique_ptr<IMemtable> f_memtable);

    // LSMIOStore Overrides
    bool startBatch() override;
    bool stopBatch() override;
    bool _batchMutation(MutationType f_m_type, const std::string f_key, const std::string f_value,
                        bool f_flush) override;
    bool dbCleanup() override;

  public:
    LSMIOStoreNative(const std::string& f_db_path, const bool f_over_write = false);
    ~LSMIOStoreNative() override;

    void autoTuneParameters(uint64_t f_fs_magic);

    void close() override;

    bool get(const std::string f_key, std::string* f_value) override;
    bool getPrefix(const std::string f_key,
                   std::vector<std::tuple<std::string, std::string>>* f_values) override;

    bool readBarrier() override;
    bool writeBarrier() override;

    // Accessors for testing
    size_t getMemtableMaxSize() const {
        return m_memtable_max_size_bytes;
    }
    size_t getMaxImmutableMemtables() const {
        return m_max_immutable_memtables;
    }
};

}  // namespace lsmio

#endif
