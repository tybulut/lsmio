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
#include <unistd.h>

#include <cstring>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <lsmio/manager/store/native/FilePool.hpp>
#include <sstream>

namespace lsmio {

FilePool::FilePool(const std::string& f_directory, const std::string& f_prefix,
                   const std::string& f_suffix, size_t f_pool_size, uint64_t f_start_id,
                   size_t f_pre_allocation_size)
    : m_directory(f_directory),
      m_prefix(f_prefix),
      m_suffix(f_suffix),
      m_pool_size(f_pool_size),
      m_next_id(f_start_id),
      m_pre_allocation_size(f_pre_allocation_size) {
    m_worker = std::thread(&FilePool::replenish, this);
}

FilePool::~FilePool() {
    {
        std::unique_lock<std::mutex> lock(m_mutex);
        m_shutdown = true;
    }
    m_cv.notify_all();
    if (m_worker.joinable()) {
        m_worker.join();
    }
}

std::pair<std::string, std::unique_ptr<std::ofstream>> FilePool::acquire() {
    std::unique_lock<std::mutex> lock(m_mutex);
    m_cv_wait.wait(lock, [this] { return !m_pool.empty() || m_shutdown; });

    if (m_shutdown && m_pool.empty()) {
        // Fallback or throw? Throwing seems safer to indicate state.
        throw std::runtime_error("FilePool is shutting down");
    }

    auto result = std::move(m_pool.front());
    m_pool.pop_front();

    // Wake up worker to replenish
    m_cv.notify_one();

    return result;
}

void FilePool::replenish() {
    while (true) {
        bool needed = false;

        {
            std::unique_lock<std::mutex> lock(m_mutex);
            m_cv.wait(lock, [this] { return m_pool.size() < m_pool_size || m_shutdown; });

            if (m_shutdown) return;
            needed = true;
        }

        if (needed) {
            // Generate file outside lock (mostly)
            uint64_t id = m_next_id.fetch_add(1);

            std::ostringstream oss;
            oss << m_prefix << std::setw(6) << std::setfill('0') << id << m_suffix;
            std::string filename = oss.str();
            std::filesystem::path path = std::filesystem::path(m_directory) / filename;
            std::string full_path = path.string();

            if (m_pre_allocation_size > 0) {
                int fd = ::open(full_path.c_str(), O_WRONLY | O_CREAT, 0644);
                if (fd >= 0) {
#ifdef __APPLE__
                    fstore_t store = {F_ALLOCATECONTIG, F_PEOFPOSMODE, 0,
                                      (off_t)m_pre_allocation_size};
                    if (fcntl(fd, F_PREALLOCATE, &store) == -1) {
                        store.fst_flags = F_ALLOCATEALL;
                        fcntl(fd, F_PREALLOCATE, &store);
                    }
                    ftruncate(fd, m_pre_allocation_size);
#else
                    posix_fallocate(fd, 0, m_pre_allocation_size);
#endif
                    ::close(fd);
                } else {
                    std::cerr << "[FilePool] Pre-alloc open failed: " << full_path << " "
                              << strerror(errno) << std::endl;
                }
            }

            auto mode = std::ios::binary | std::ios::out;
            if (m_pre_allocation_size > 0) {
                mode |= std::ios::in;
            }

            auto ofs = std::make_unique<std::ofstream>(full_path, mode);
            if (!ofs || !ofs->is_open()) {
                std::cerr << "[FilePool] Failed to open " << full_path << " Mode: " << mode
                          << " Errno: " << errno << " (" << strerror(errno) << ")" << std::endl;
                // Sleep briefly to avoid busy loop if FS is bad
                std::this_thread::sleep_for(std::chrono::milliseconds(100));
                continue;
            }

            if (m_pre_allocation_size > 0) {
                ofs->seekp(0);  // Ensure we start writing from beginning
            }

            {
                std::unique_lock<std::mutex> lock(m_mutex);
                if (m_shutdown) {
                    ofs->close();  // Cleanup
                    return;
                }
                m_pool.push_back({full_path, std::move(ofs)});
                m_cv_wait.notify_one();
            }
        }
    }
}

}  // namespace lsmio
