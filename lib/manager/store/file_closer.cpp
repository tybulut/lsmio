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
#include <lsmio/manager/store/file_closer.hpp>

namespace lsmio {

FileCloser::FileCloser(size_t batchSize) : _batchSize(batchSize) {
    _worker = std::thread(&FileCloser::workerLoop, this);
}

FileCloser::~FileCloser() {
    {
        std::unique_lock<std::mutex> lock(_mutex);
        _shutdown = true;
    }
    _cv.notify_one();
    if (_worker.joinable()) {
        _worker.join();
    }
    // Close remaining
    for (auto& f : _pending) {
        if (f && f->is_open()) f->close();
    }
}

void FileCloser::scheduleClose(std::unique_ptr<std::ofstream> file) {
    std::unique_lock<std::mutex> lock(_mutex);
    _pending.push_back(std::move(file));
    if (_pending.size() >= _batchSize || _shutdown) {
        _cv.notify_one();
    }
}

void FileCloser::workerLoop() {
    while (true) {
        std::vector<std::unique_ptr<std::ofstream>> to_close;

        {
            std::unique_lock<std::mutex> lock(_mutex);
            _cv.wait(lock, [this] { return _pending.size() >= _batchSize || _shutdown; });

            if (_shutdown && _pending.empty()) return;

            to_close.swap(_pending);
        }

        for (auto& f : to_close) {
            if (f && f->is_open()) {
                f->close();
            }
        }
    }
}

}  // namespace lsmio
