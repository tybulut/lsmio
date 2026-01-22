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

#include <lsmio/lsmio.hpp>
#include <lsmio/posix/posix.hpp>

namespace lsmio {

std::map<std::string, std::streamoff> LSMIOStream::_fileMap;

LSMIOManager* LSMIOStream::_lm = nullptr;
std::atomic<int> LSMIOStream::_lsmioInitialized = 0;
std::atomic<int> LSMIOStream::_lsmioInitializing = 0;
std::atomic<int> LSMIOStream::_lsmioCleaning = 0;

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
    if (!_lsmioInitialized) {
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

    if (!_lsmioInitialized) {
        throw std::invalid_argument("ERROR: LSMIOStream::write called without initializing");
    }

    _lm->put(_genKey(), s);
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
    return (_lsmioInitialized == 1);
}

bool LSMIOStream::fail() const {
    return (_lsmioInitialized != 1);
}

LSMIOStream& LSMIOStream::flush() {
    return *this;
}

void LSMIOStream::close() {
    _fileMap[_filePath] = 0;
}

bool LSMIOStream::initialize(const std::string& dbName, const std::string& dbDir) {
    if (_lsmioInitialized) {
        LOG(WARNING) << "LSMIOStream::initialize: already initialiazed: " << dbName << std::endl;
        return false;
    }

    if (_lsmioInitializing) {
        LOG(WARNING) << "LSMIOStream::initialize: already initialiazing: " << dbName << std::endl;
        return false;
    }

    _lsmioInitializing = 1;
    LOG(INFO) << "LSMIOStream::initialize: initialiazing: " << dbName << std::endl;

    _lm = new lsmio::LSMIOManager(dbName, dbDir);

    _lsmioInitializing = 0;
    _lsmioInitialized = 1;

    LOG(INFO) << "LSMIOStream::initialize: completed: " << dbName << std::endl;
    return true;
}

bool LSMIOStream::cleanup() {
    if (!_lsmioInitialized || _lsmioInitializing) {
        if (!_lsmioInitialized)
            LOG(WARNING) << "LSMIOStream::cleanup: not initialiazed." << std::endl;
        else
            LOG(WARNING) << "LSMIOStream::cleanup: currently initialiaizing." << std::endl;
        return false;
    }

    if (_lsmioCleaning) {
        LOG(WARNING) << "LSMIOStream::cleanup: already cleaning." << std::endl;
        return false;
    }

    _lsmioCleaning = 1;
    LOG(WARNING) << "LSMIOStream::cleanup: cleaning." << std::endl;

    delete _lm;
    _lm = nullptr;

    _lsmioCleaning = 0;
    _lsmioInitialized = 0;
    return true;
}

bool LSMIOStream::writeBarrier() {
    if (!_lsmioInitialized) {
        throw std::invalid_argument("ERROR: LSMIOStream::write called without initializing");
    }

    _lm->writeBarrier();
    ;

    return true;
}

}  // namespace lsmio
