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

#include <cerrno>
#include <chrono>
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
      m_pre_allocation_size(f_pre_allocation_size),
      m_next_id(f_start_id) {
    if (m_pool_size > 0) {
        m_worker = std::thread(&FilePool::replenish, this);
    }
}

FilePool::~FilePool() {
    shutdown();
}

void FilePool::shutdown() {
    {
        std::unique_lock<std::mutex> lock(m_mutex);
        m_shutdown = true;
    }
    m_cv.notify_all();
    m_cv_wait.notify_all();
    if (m_worker.joinable()) {
        m_worker.join();
    }
}

std::pair<std::string, std::unique_ptr<std::ofstream>> FilePool::acquire() {
    // If pool size is 0, synchronously create on demand without worker thread
    if (m_pool_size == 0) {
        if (m_shutdown.load(std::memory_order_acquire)) {
            return {"", nullptr};
        }
        return createFile();
    }

    std::unique_lock<std::mutex> lock(m_mutex);
    m_cv_wait.wait_for(lock, std::chrono::seconds(2), [this] {
        return !m_pool.empty() || m_shutdown.load(std::memory_order_relaxed);
    });

    if (m_shutdown.load(std::memory_order_relaxed) && m_pool.empty()) {
        return {"", nullptr};
    }

    if (!m_pool.empty()) {
        auto result = std::move(m_pool.front());
        m_pool.pop_front();

        // Wake up worker to replenish
        m_cv.notify_one();

        return result;
    }

    // Pool is starved (background worker delayed by MDS contention or rapid flush rate).
    // Do NOT abort the store; release lock and fall back to synchronous on-demand file creation.
    lock.unlock();

    static std::atomic<bool> warned_starved{false};
    if (!warned_starved.exchange(true)) {
        std::cerr << "[FilePool] WARNING: Pool starved or wait expired; creating SSTable "
                     "synchronously on demand"
                  << std::endl;
    }

    m_fallback_creations.fetch_add(1, std::memory_order_relaxed);
    return createFile();
}

std::pair<std::string, std::unique_ptr<std::ofstream>> FilePool::createFile() {
    uint64_t id = m_next_id.fetch_add(1);

    std::ostringstream oss;
    oss << m_prefix << std::setw(6) << std::setfill('0') << id << m_suffix;
    std::string filename = oss.str();
    std::filesystem::path path = std::filesystem::path(m_directory) / filename;
    std::string full_path = path.string();

    if (m_pre_allocation_size > 0) {
        int fd = ::open(full_path.c_str(), O_WRONLY | O_CREAT, 0644);
        if (fd < 0) {
            std::cerr << "[FilePool] Pre-alloc open failed: " << full_path << " " << strerror(errno)
                      << std::endl;
            return {"", nullptr};
        }

#ifdef __APPLE__
        fstore_t store = {F_ALLOCATECONTIG, F_PEOFPOSMODE, 0, (off_t)m_pre_allocation_size};
        if (fcntl(fd, F_PREALLOCATE, &store) == -1) {
            store.fst_flags = F_ALLOCATEALL;
            fcntl(fd, F_PREALLOCATE, &store);
        }
        int tr_res = ::ftruncate(fd, m_pre_allocation_size);
        if (tr_res != 0) {
            std::cerr << "[FilePool] ftruncate failed on " << full_path << ": " << strerror(errno)
                      << std::endl;
            ::close(fd);
            std::error_code ec;
            std::filesystem::remove(full_path, ec);
            return {"", nullptr};
        }
#else
        int falloc_ret = 0;
        do {
            falloc_ret = posix_fallocate(fd, 0, m_pre_allocation_size);
        } while (falloc_ret == EINTR);

        if (falloc_ret == EOPNOTSUPP || falloc_ret == ENOTSUP) {
            static std::atomic<bool> warned_unsupported{false};
            if (!warned_unsupported.exchange(true)) {
                std::cerr << "[FilePool] WARNING: posix_fallocate not supported on filesystem for "
                          << full_path << "; falling back to ftruncate" << std::endl;
            }
            int trunc_ret = ::ftruncate(fd, m_pre_allocation_size);
            if (trunc_ret != 0) {
                int err = errno;
                std::cerr << "[FilePool] ERROR: ftruncate fallback failed for " << full_path << ": "
                          << strerror(err) << std::endl;
                ::close(fd);
                std::error_code ec;
                std::filesystem::remove(full_path, ec);
                return {"", nullptr};
            }
        } else if (falloc_ret != 0) {
            std::cerr << "[FilePool] ERROR: posix_fallocate failed for " << full_path << ": "
                      << strerror(falloc_ret) << " (code " << falloc_ret << ")" << std::endl;
            ::close(fd);
            std::error_code ec;
            std::filesystem::remove(full_path, ec);
            return {"", nullptr};
        }
#endif
        ::close(fd);
    }

    auto mode = std::ios::binary | std::ios::out;
    if (m_pre_allocation_size > 0) {
        mode |= std::ios::in;
    }

    auto ofs = std::make_unique<std::ofstream>(full_path, mode);
    if (!ofs || !ofs->is_open() || ofs->fail()) {
        std::cerr << "[FilePool] Failed to open " << full_path << " Mode: " << mode
                  << " Errno: " << errno << " (" << strerror(errno) << ")" << std::endl;
        if (ofs && ofs->is_open()) {
            ofs->close();
        }
        std::error_code ec;
        std::filesystem::remove(full_path, ec);
        return {"", nullptr};
    }

    if (m_pre_allocation_size > 0) {
        ofs->seekp(0);
        if (ofs->fail()) {
            std::cerr << "[FilePool] seekp(0) failed on preallocated file: " << full_path
                      << std::endl;
            ofs->close();
            std::error_code ec;
            std::filesystem::remove(full_path, ec);
            return {"", nullptr};
        }
    }

    return {full_path, std::move(ofs)};
}

void FilePool::replenish() {
    while (true) {
        {
            std::unique_lock<std::mutex> lock(m_mutex);
            m_cv.wait(lock, [this] { return m_pool.size() < m_pool_size || m_shutdown; });

            if (m_shutdown) return;
        }

        // Generate file outside lock
        auto file_entry = createFile();
        if (!file_entry.second) {
            // Creation failed; back off briefly before retrying
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
            continue;
        }

        {
            std::unique_lock<std::mutex> lock(m_mutex);
            if (m_shutdown) {
                file_entry.second->close();
                std::error_code ec;
                std::filesystem::remove(file_entry.first, ec);
                return;
            }
            m_pool.push_back(std::move(file_entry));
            m_cv_wait.notify_one();
        }
    }
}

}  // namespace lsmio
