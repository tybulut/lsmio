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

#include <exception>
#include <lsmio/lsmio.hpp>
#include <lsmio/posix/posix.hpp>

namespace lsmio {

std::map<std::string, std::streamoff> LSMIOStream::_fileMap;

LSMIOManager* LSMIOStream::_lm = nullptr;
std::atomic<LifecycleState> LSMIOStream::_lsmioState{LifecycleState::None};

LSMIOStream::LSMIOStream(const char* filename, std::ios::openmode mode) {
    if (filename) {
        open(filename, mode);
    }
}

LSMIOStream::~LSMIOStream() {}

std::string LSMIOStream::_genKey() {
    return _filePath + "::" + std::to_string(_fileMap[_filePath]);
}

void LSMIOStream::open(const char* filename, std::ios::openmode mode) {
    LOG(INFO) << "LSMIOStream::open: filename: " << filename << std::endl;

    auto it = _fileMap.find(filename);
    if (it == _fileMap.end()) {
        _fileMap[filename] = 0;
    } else if (mode == std::ios::trunc) {
        _fileMap[filename] = 0;
    }
    _filePath = filename;
}

LSMIOStream& LSMIOStream::read(char* s, std::streamsize n) {
    if (_lsmioState != LifecycleState::Ready) {
        throw std::invalid_argument("ERROR: LSMIOStream::read called without initializing");
    }

    std::string value;
    _lm->get(_genKey(), &value);

    if (value.size() != n) {
        throw std::invalid_argument("ERROR: LSMIOStream::read unexpected length of data");
    }

    value.copy(s, n);
    _fileMap[_filePath] = _fileMap[_filePath] + n;

    return *this;
}

LSMIOStream& LSMIOStream::write(const char* s, std::streamsize n) {
    LOG(INFO) << "LSMIOStream::write:c: filename: " << _filePath << " streamsize: " << n
              << std::endl;
    std::string value(s, n);

    return write(value);
}

LSMIOStream& LSMIOStream::write(const std::string& s) {
    LOG(INFO) << "LSMIOStream::write:s: filename: " << _filePath << " streamsize: " << s.size()
              << std::endl;

    if (_lsmioState != LifecycleState::Ready) {
        throw std::invalid_argument("ERROR: LSMIOStream::write called without initializing");
    }

    if (!_lm->put(_genKey(), s)) {
        throw std::ios_base::failure("ERROR: LSMIOStream::write failed to persist " +
                                     std::to_string(s.size()) + " bytes to " + _filePath);
    }
    _fileMap[_filePath] = _fileMap[_filePath] + s.size();

    return *this;
}

LSMIOStream& LSMIOStream::seekp(std::streamoff off, std::ios::seekdir way) {
    LOG(INFO) << "LSMIOStream::seekp: off: " << off << std::endl;

    if (way == std::ios::beg) {
        _fileMap[_filePath] = off;
    } else { /* std::ios::end */
        throw std::invalid_argument("ERROR: LSMIOStream::seekp is not called from beginning");
    }

    return *this;
}

std::streampos LSMIOStream::tellp() {
    return _fileMap[_filePath];
}

std::streambuf* LSMIOStream::rdbuf() const {
    return _buf.rdbuf();
}

bool LSMIOStream::good() const {
    return (_lsmioState == LifecycleState::Ready);
}

bool LSMIOStream::fail() const {
    return (_lsmioState != LifecycleState::Ready);
}

LSMIOStream& LSMIOStream::flush() {
    return *this;
}

void LSMIOStream::close() {
    _fileMap[_filePath] = 0;
}

bool LSMIOStream::initialize(const std::string& dbName, const std::string& dbDir) {
    LifecycleState state = LifecycleState::None;
    if (!_lsmioState.compare_exchange_strong(state, LifecycleState::Initializing)) {
        LOG(WARNING) << "LSMIOStream::initialize: refused, state is " << lifecycleStateName(state)
                     << ": " << dbName << std::endl;
        return false;
    }

    LOG(INFO) << "LSMIOStream::initialize: initialiazing: " << dbName << std::endl;

    // On failure the state goes back to None so that initialize may be called again, and the cause
    // is logged at the default level (a manager that failed part-way may still hold its store)
    try {
        _lm = new lsmio::LSMIOManager(dbName, dbDir);
    } catch (const std::exception& e) {
        _lsmioState = LifecycleState::None;
        LOG(ERROR) << "LSMIOStream::initialize: failed: " << dbName << ": " << e.what()
                   << std::endl;
        throw;
    } catch (...) {
        _lsmioState = LifecycleState::None;
        LOG(ERROR) << "LSMIOStream::initialize: failed: " << dbName << std::endl;
        throw;
    }

    _lsmioState = LifecycleState::Ready;

    LOG(INFO) << "LSMIOStream::initialize: completed: " << dbName << std::endl;
    return true;
}

bool LSMIOStream::cleanup() {
    LifecycleState state = LifecycleState::Ready;
    if (!_lsmioState.compare_exchange_strong(state, LifecycleState::Cleaning)) {
        LOG(WARNING) << "LSMIOStream::cleanup: refused, state is " << lifecycleStateName(state)
                     << std::endl;
        return false;
    }

    LOG(WARNING) << "LSMIOStream::cleanup: cleaning." << std::endl;

    delete _lm;
    _lm = nullptr;

    _lsmioState = LifecycleState::None;
    return true;
}

bool LSMIOStream::writeBarrier() {
    if (_lsmioState != LifecycleState::Ready) {
        throw std::invalid_argument("ERROR: LSMIOStream::write called without initializing");
    }

    _lm->writeBarrier();
    ;

    return true;
}

}  // namespace lsmio
