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
#include <condition_variable>
#include <deque>
#include <fstream>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <utility>

namespace lsmio {

class FilePool {
  public:
    FilePool(const std::string& directory, const std::string& prefix, const std::string& suffix,
             size_t poolSize, uint64_t startId, size_t preAllocationSize = 0);
    ~FilePool();

    // Returns a pair of {file_path, file_stream}
    // The stream is open and ready for writing.
    // If the pool is empty, this blocks until a file is available.
    std::pair<std::string, std::unique_ptr<std::ofstream>> acquire();

  private:
    std::string _directory;
    std::string _prefix;
    std::string _suffix;
    size_t _poolSize;
    size_t _preAllocationSize;

    // Pool stores pairs of {path, stream}
    std::deque<std::pair<std::string, std::unique_ptr<std::ofstream>>> _pool;

    std::mutex _mutex;
    std::thread _worker;
    std::condition_variable _cv;
    std::condition_variable _cv_wait;  // Wait for item in pool
    std::atomic<bool> _shutdown{false};
    std::atomic<uint64_t> _next_id;

    void replenish();
};

}  // namespace lsmio

#endif
