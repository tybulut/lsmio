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

#ifndef _LSMIO_STORE_HPP_
#define _LSMIO_STORE_HPP_

#include <atomic>
#include <lsmio/lsmio.hpp>
#include <mutex>
#include <string>

namespace lsmio {

enum class MutationType { Put, Del };

std::string getMutationType(MutationType mType);

class LSMIOStore {
  protected:
    std::string _dbPath;
    int _maxBatchSize;
    int _maxBatchBytes;
    bool _writeSync;

    const std::string _metaPrefix = "__lsmio_md::";

    std::atomic<uint> _batchSize = {0};
    std::atomic<uint> _batchBytes = {0};
    std::mutex _batchMutex;

    /// start / stop batching
    /// @return bool success
    virtual bool startBatch() = 0;
    virtual bool stopBatch() = 0;

    virtual bool _batchMutation(MutationType mType, const std::string key, const std::string value,
                                bool flush) = 0;

    /// cleanup the ENTIRE store
    /// @return bool success
    virtual bool dbCleanup() = 0;

  public:
    LSMIOStore(const std::string& dbPath, const bool overWrite = false);
    virtual ~LSMIOStore();

    /// get value given a key
    /// @return bool success
    virtual bool get(const std::string key, std::string* value) = 0;
    virtual bool getPrefix(const std::string key, std::vector<std::tuple<std::string, std::string>>* values) = 0;

    /// put value given a key
    /// @return bool success
    virtual bool put(const std::string key, const std::string value, bool flush = true);

    /// delete value given a key
    /// @return bool success
    virtual bool del(const std::string key, bool flush = true);

    /// meta operations
    /// @return bool success
    virtual bool metaGet(const std::string key, std::string* value);
    virtual bool metaGetAll(std::vector<std::tuple<std::string, std::string>>* values);
    virtual bool metaPut(const std::string key, const std::string value, bool flush = true);

    /// sync barriers
    /// @return bool success
    virtual bool readBarrier() = 0;
    virtual bool writeBarrier() = 0;
};

}  // namespace lsmio

#endif
