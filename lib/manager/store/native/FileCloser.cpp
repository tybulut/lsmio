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

#include <iostream>
#include <lsmio/manager/store/native/FileCloser.hpp>

namespace lsmio {

FileCloser::FileCloser(size_t f_batch_size) : m_batch_size(f_batch_size) {
    m_worker = std::thread(&FileCloser::workerLoop, this);
}

FileCloser::~FileCloser() {
    {
        std::unique_lock<std::mutex> lock(m_mutex);
        m_shutdown = true;
    }
    m_cv.notify_one();
    if (m_worker.joinable()) {
        m_worker.join();
    }
    // Close remaining
    for (auto& f : m_pending) {
        if (f && f->is_open()) f->close();
    }
}

void FileCloser::scheduleClose(std::unique_ptr<std::ofstream> file) {
    std::unique_lock<std::mutex> lock(m_mutex);
    m_pending.push_back(std::move(file));
    if (m_pending.size() >= m_batch_size || m_shutdown) {
        m_cv.notify_one();
    }
}

void FileCloser::workerLoop() {
    while (true) {
        std::vector<std::unique_ptr<std::ofstream>> to_close;

        {
            std::unique_lock<std::mutex> lock(m_mutex);
            m_cv.wait(lock, [this] { return m_pending.size() >= m_batch_size || m_shutdown; });

            if (m_shutdown && m_pending.empty()) return;

            to_close.swap(m_pending);
        }

        for (auto& f : to_close) {
            if (f && f->is_open()) {
                f->close();
            }
        }
    }
}

}  // namespace lsmio
