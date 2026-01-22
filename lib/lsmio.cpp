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

#include <execinfo.h>
#include <signal.h>
#include <unistd.h>

#include <iostream>
/*
#include <stdlib.h>
*/

#include <lsmio/lsmio.hpp>

namespace lsmio {

/// Define the FLAG_DUAL for LSMIOHelper.
const std::string LSMIOHelper::FLAG_DUAL = "flag_dual";

/// Define the FLAG_FALLBACK for LSMIOHelper.
const std::string LSMIOHelper::FLAG_FALLBACK = "flag_fallback";

/// Global configuration object for LSMIO.
LSMIOConfig gConfigLSMIO;

/// Default logging behavior flag.
bool defaultLogDebug = false;

/// Internal configuration map for LSMIO flags.
static std::map<std::string, bool> _LSMIOconfigMap;

void initLSMIORelease(char *name) {
    google::InitGoogleLogging(name);
    FLAGS_logtostderr = true;
    FLAGS_minloglevel = google::ERROR;
}

void initLSMIODebug(char *name) {
    defaultLogDebug = true;
    google::InitGoogleLogging(name);
    FLAGS_logtostderr = true;
    FLAGS_minloglevel = google::INFO;
}

void increaseLSMIOLogging() {
    FLAGS_minloglevel = google::INFO;
}

void decreaseLSMIOLogging() {
    FLAGS_minloglevel = google::WARNING;
}

void defaultLSMIOLogging() {
    if (defaultLogDebug) {
        FLAGS_logtostderr = true;
        FLAGS_minloglevel = google::INFO;
    } else {
        FLAGS_logtostderr = true;
        FLAGS_minloglevel = google::ERROR;
    }
}

bool LSMIOHelper::getFlag(const std::string key) {
    auto it = _LSMIOconfigMap.find(key);
    if (it == _LSMIOconfigMap.end()) {
        return false;
    }
    return true;
}

void LSMIOHelper::setFlag(const std::string key, const bool value) {
    if (value) {
        _LSMIOconfigMap[key] = true;
    } else {
        auto it = _LSMIOconfigMap.find(key);
        if (it != _LSMIOconfigMap.end()) {
            _LSMIOconfigMap.erase(key);
        }
    }
}

void handlerSIGSEGV(int signal) {
    const int TRACE_SIZE = 24;
    void *array[TRACE_SIZE];
    size_t size;

    size = backtrace(array, TRACE_SIZE);

    fprintf(stderr, "LSMIO caught signal: SIGSEGV.\n");
    backtrace_symbols_fd(array, size, STDERR_FILENO);

    // SIGSEGV handler must exit
    exit(EXIT_FAILURE);
}

std::string to_string(const MPIAggType v) {
    std::string sVal;

    switch (v) {
        case MPIAggType::Shared:
            sVal = "mpiShared";
            break;
        case MPIAggType::Entire:
            sVal = "mpiEntire";
            break;
        case MPIAggType::EntireSerial:
            sVal = "mpiEntireSerial";
            break;
        case MPIAggType::Split:
            sVal = "mpiSplit";
            break;
    }

    return sVal;
}

std::string to_string(const StorageType v) {
    std::string sVal;

    switch (v) {
        case StorageType::LevelDB:
            sVal = "LevelDB";
            break;
        case StorageType::RocksDB:
            sVal = "RocksDB";
            break;
    }

    return sVal;
}

}  // namespace lsmio

std::ostream &operator<<(std::ostream &os, lsmio::MPIAggType v) {
    os << lsmio::to_string(v);
    return os;
}

std::ostream &operator<<(std::ostream &os, lsmio::StorageType v) {
    os << lsmio::to_string(v);
    return os;
}

std::ostream &operator<<(std::ostream &os, const lsmio::MPIAggType &v) {
    os << lsmio::to_string(v);
    return os;
}

std::ostream &operator<<(std::ostream &os, const lsmio::StorageType &v) {
    os << lsmio::to_string(v);
    return os;
}
