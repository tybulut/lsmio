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

#ifndef _LSMIO_STORE_LDB_HPP_
#define _LSMIO_STORE_LDB_HPP_

#include <leveldb/db.h>
#include <leveldb/filter_policy.h>

#include <string>

#include "store.hpp"

namespace lsmio {

class LSMIOStoreLDB : public LSMIOStore {
  private:
    leveldb::WriteOptions _wOptions;
    leveldb::ReadOptions _rOptions;
    leveldb::Options _options;
    leveldb::DB* _db;
    leveldb::WriteBatch* _batch;

    /// start / stop batching
    /// @return bool success
    bool startBatch();
    bool stopBatch();

    bool _batchMutation(MutationType mType, const std::string key, const std::string value,
                        bool flush);

    /// cleanup the ENTIRE store
    /// @return bool success
    virtual bool dbCleanup();

  public:
    LSMIOStoreLDB(const std::string& dbPath, const bool overWrite = false);
    ~LSMIOStoreLDB();

    /// get value given a key
    /// @return bool success
    bool get(const std::string key, std::string* value);
    bool getPrefix(const std::string key, std::vector<std::tuple<std::string, std::string>>* values);

    /// sync batching
    /// @return bool success
    bool readBarrier();
    bool writeBarrier();
};

}  // namespace lsmio

#endif
