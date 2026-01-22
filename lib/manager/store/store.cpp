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
#include <lsmio/manager/store/store.hpp>

namespace lsmio {

std::string getMutationType(MutationType mType) {
    std::string sVal;

    switch (mType) {
        case MutationType::Put:
            sVal = "Put";
            break;
        case MutationType::Del:
            sVal = "Del";
            break;
    }

    return sVal;
}

LSMIOStore::LSMIOStore(const std::string& dbPath, const bool overWrite) {
    _dbPath = dbPath;
    _maxBatchSize = gConfigLSMIO.asyncBatchSize;
    _maxBatchBytes = gConfigLSMIO.asyncBatchBytes;
}

LSMIOStore::~LSMIOStore() {}

bool LSMIOStore::metaGet(const std::string key, std::string* value) {
    LOG(INFO) << "LSMIOStore::metaGet: " << std::endl;
    return get(_metaPrefix + key, value);
}

bool LSMIOStore::metaGetAll(std::vector<std::tuple<std::string, std::string>>* values,
                            std::string inFix) {
    LOG(INFO) << "LSMIOStore::metaGetAll: " << std::endl;
    std::string prefix = _metaPrefix + (inFix.empty() ? "" : inFix);
    return getPrefix(prefix, values);
}

bool LSMIOStore::metaPut(const std::string key, const std::string value, bool flush) {
    LOG(INFO) << "LSMIOStore::metaPut: " << std::endl;
    return put(_metaPrefix + key, value, flush);
}

bool LSMIOStore::put(const std::string key, const std::string value, bool flush) {
    bool retValue;

    LOG(INFO) << "LSMIOStore::put: key: " << key << " flush: " << flush << " size: " << value.size()
              << std::endl;

    return _batchMutation(MutationType::Put, key, value, flush);
}

bool LSMIOStore::del(const std::string key, bool flush) {
    bool retValue;

    LOG(INFO) << "LSMIOStore::del: key: " << key << " flush: " << flush << std::endl;

    return _batchMutation(MutationType::Del, key, "", flush);
}

bool LSMIOStore::writeBarrier() {
    bool status;

    LOG(INFO) << "LSMIOStore::writeBarrier: " << std::endl;
    status = stopBatch();
    return true;
}

}  // namespace lsmio
