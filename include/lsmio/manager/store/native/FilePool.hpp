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

#ifndef _LSMIO_FILE_POOL_HPP_
#define _LSMIO_FILE_POOL_HPP_

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <deque>
#include <fstream>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <utility>

namespace lsmio {

class FilePool {
  public:
    // f_acquire_timeout bounds how long acquire() waits for the background
    // replenish thread before falling back to synchronous on-demand creation
    // on the caller thread (BUG-5). The default preserves production behavior;
    // tests may pass a short timeout to make starvation reliably reachable
    // without waiting out a production-length window.
    // f_test_replenish_delay_hook, if set, is invoked once per replenish()
    // loop iteration immediately before createFile() on the background
    // thread only. It exists to make acquire()'s starvation/fallback path
    // deterministically testable (blocking the hook stalls the pool
    // indefinitely without depending on real, environment-variable file
    // creation latency) and MUST remain a no-op (nullptr) in production use.
    FilePool(const std::string& f_directory, const std::string& f_prefix,
             const std::string& f_suffix, size_t f_pool_size, uint64_t f_start_id,
             size_t f_pre_allocation_size = 0,
             std::chrono::milliseconds f_acquire_timeout = std::chrono::seconds(2),
             std::function<void()> f_test_replenish_delay_hook = nullptr);
    ~FilePool();

    // Returns a pair of {file_path, file_stream}
    // The stream is open and ready for writing.
    // If the pool is empty, this blocks until a file is available.
    std::pair<std::string, std::unique_ptr<std::ofstream>> acquire();
    void shutdown();

    size_t getFallbackCreations() const noexcept {
        return m_fallback_creations.load(std::memory_order_relaxed);
    }

  private:
    std::string m_directory;
    std::string m_prefix;
    std::string m_suffix;
    size_t m_pool_size;
    size_t m_pre_allocation_size;
    std::chrono::milliseconds m_acquire_timeout;
    std::function<void()> m_test_replenish_delay_hook;

    // Pool stores pairs of {path, stream}
    std::deque<std::pair<std::string, std::unique_ptr<std::ofstream>>> m_pool;

    std::mutex m_mutex;
    std::thread m_worker;
    std::condition_variable m_cv;
    std::condition_variable m_cv_wait;  // Wait for item in pool
    std::atomic<bool> m_shutdown{false};
    std::atomic<uint64_t> m_next_id;
    std::atomic<size_t> m_fallback_creations{0};

    std::pair<std::string, std::unique_ptr<std::ofstream>> createFile();

    void replenish();
};

}  // namespace lsmio

#endif
