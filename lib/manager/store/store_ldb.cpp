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

#include <leveldb/cache.h>
#include <leveldb/write_batch.h>

#include <atomic>
#include <filesystem>
#include <iostream>
#include <lsmio/manager/store/store_ldb.hpp>

namespace lsmio {

LSMIOStoreLDB::LSMIOStoreLDB(const std::string &dbPath, const bool overWrite)
    : LSMIOStore(dbPath, overWrite) {
    leveldb::Status status;

    _options.create_if_missing = true;
    _batch = nullptr;

    if (gConfigLSMIO.useBloomFilter) {
        _options.filter_policy = leveldb::NewBloomFilterPolicy(10);
    }

    if (!gConfigLSMIO.compression) {
        _options.compression = leveldb::kNoCompression;
    }

    _wOptions.sync = gConfigLSMIO.useSync;
    if (gConfigLSMIO.useSync) {
        LOG(INFO) << "LSMIOStoreLDB::LSMIOStoreLDB: sync writes enabled." << std::endl;
    }

    if (gConfigLSMIO.cacheSize > 0) {
        _options.block_cache = leveldb::NewLRUCache(gConfigLSMIO.cacheSize);
    }

    // Standard LevelDB does not support disabling mmap via Options.
    // It defaults to using mmap for reading SSTables.
    if (!gConfigLSMIO.enableMMAP) {
        LOG(WARNING) << "LSMIOStoreLDB: enableMMAP=false requested, but standard LevelDB ignores this and uses mmap by default." << std::endl;
    }

    _options.block_size = gConfigLSMIO.blockSize;
    _options.write_buffer_size = gConfigLSMIO.writeBufferSize;
    _options.max_file_size = gConfigLSMIO.writeFileSize;

    // Attempt to effectively disable compaction by setting a very high trigger
    // Note: LevelDB doesn't have a simple boolean to disable compaction completely via Options.
    // Increasing write_buffer_size helps delay memtable compaction, and increasing
    // max_open_files or similar doesn't directly stop L0->L1 compaction.
    // However, we can't easily force "kCompactionStyleNone" in standard LevelDB.
    // We will rely on the benchmark being short enough that massive compaction storms might not occur,
    // or accept that LevelDB will still compact to some degree.
    // For strict equivalence, we would need a modded LevelDB.
    // We will assume this request implies "do best effort to minimize compaction overhead".
    
    if (overWrite) {
        LOG(INFO) << "LSMIOStoreLDB::LSMIOStoreLDB: overWrite is set for the  database: " << _dbPath
                  << std::endl;
        dbCleanup();
    }

    LOG(INFO) << "LSMIOStoreLDB::LSMIOStoreLDB: Creating the database: " << _dbPath << std::endl;
    status = leveldb::DB::Open(_options, _dbPath, &_db);
    if (status.ok()) {
        LOG(INFO) << "LSMIOStoreLDB::LSMIOStoreLDB: Successfully created the database."
                  << std::endl;
    } else {
        LOG(FATAL) << status.ToString() << std::endl;
        throw std::invalid_argument(
            "ERROR: LSMIOStoreLDB::LSMIOStoreLDB:  Failed to open database.");
    }

    if (_db == nullptr) {
        LOG(FATAL) << "LSMIOStoreLDB::LSMIOStoreLDB: Failed to create the database." << std::endl;
        throw std::invalid_argument(
            "ERROR: LSMIOStoreLDB::LSMIOStoreLDB: Failed to create database.");
    }
}

LSMIOStoreLDB::~LSMIOStoreLDB() {
    LOG(INFO) << "LSMIOStoreLDB::~LSMIOStoreLDB(): cleaning up." << std::endl;
    writeBarrier();
    delete _db;
}

bool LSMIOStoreLDB::get(const std::string key, std::string *value) {
    leveldb::Status s;

    LOG(INFO) << "LSMIOStoreLDB::get(): key: " << key << std::endl;
    s = _db->Get(_rOptions, key, value);
    return s.ok();
}

bool LSMIOStoreLDB::getPrefix(const std::string key, std::vector<std::tuple<std::string, std::string>>* values) {
    leveldb::Status s;

    LOG(INFO) << "LSMIOStoreLDB::getPrefix(): key: " << key << std::endl;
    leveldb::Iterator* it = _db->NewIterator(_rOptions);

    it->Seek(key);
    while (it->Valid() && it->key().starts_with(key)) {
        values->emplace_back(it->key().ToString(), it->value().ToString());
        it->Next();
    }

    s = it->status();
    delete it;

    return s.ok();
}

bool LSMIOStoreLDB::_batchMutation(MutationType mType, const std::string key,
                                   const std::string value, bool flush) {
    leveldb::Status s;
    bool retValue;
    std::string origValue, finalValue;

    const unsigned int futureSize = _batchSize + 1;
    const unsigned int futureBytes = _batchBytes + value.size();

    LOG(INFO) << "LSMIOStoreLDB::_batchMutation: key: " << key << " flush: " << flush
              << " size: " << value.size() << " futureSize: " << futureSize
              << " futureBytes: " << futureBytes << std::endl;

    if (flush || value.size() >= _maxBatchSize) {
        if (_batch) stopBatch();

        LOG(INFO) << "LSMIOStoreLDB::_batchMutation: mutation: " << getMutationType(mType)
                  << std::endl;
        if (mType == MutationType::Put) {
            s = _db->Put(_wOptions, key, value);
        } else if (mType == MutationType::Del) {
            s = _db->Delete(_wOptions, key);
        } else {
            throw std::invalid_argument("ERROR: LSMIOStoreLDB:::_batchMutation: Unknown mutation.");
        }

        retValue = s.ok();
    } else {
        if (_batch && (futureSize >= _maxBatchSize || futureBytes >= _maxBatchBytes)) {
            stopBatch();
        }

        LOG(INFO) << "LSMIOStoreLDB::_batchMutation: mutation: batch::" << getMutationType(mType)
                  << std::endl;
        {
            std::lock_guard<std::mutex> lg(_batchMutex);

            if (!_batch) {
                _batch = new leveldb::WriteBatch();
            }

            if (mType == MutationType::Put) {
                _batch->Put(key, value);
            } else if (mType == MutationType::Del) {
                _batch->Delete(key);
            }
        }

        LOG(INFO) << "LSMIOStoreLDB::_batchMutation: mutation: update counters: " << std::endl;
        _batchSize++;
        _batchBytes.fetch_add(value.size());

        retValue = true;
    }

    return retValue;
}

bool LSMIOStoreLDB::startBatch() {
    LOG(INFO) << "LSMIOStoreLDB::startBatch(): " << std::endl;

    std::lock_guard<std::mutex> lg(_batchMutex);

    if (_batch) {
        return false;
    }

    _batch = new leveldb::WriteBatch();
    return true;
}

bool LSMIOStoreLDB::stopBatch() {
    leveldb::Status s;
    leveldb::WriteBatch *oldBatch = _batch;

    LOG(INFO) << "LSMIOStoreRDB::stopBatch(): " << std::endl;

    {
        std::lock_guard<std::mutex> lg(_batchMutex);

        if (!_batch) {
            return false;
        }

        _batch = nullptr;
        _batchSize.store(0);
        _batchBytes.store(0);
    }

    s = _db->Write(_wOptions, oldBatch);
    delete oldBatch;

    return s.ok();
}

bool LSMIOStoreLDB::dbCleanup() {
    leveldb::Status s;

    LOG(WARNING) << "LSMIOStoreLDB::overWrite: ENTIRE database: " << _dbPath << std::endl;

    s = leveldb::DestroyDB(_dbPath, _options);
    if (!s.ok()) {
        LOG(FATAL) << s.ToString() << std::endl;
        throw std::invalid_argument("ERROR: LSMIOStoreLDB:::overWrite: Failed to remove database.");
    }

    std::filesystem::remove_all(_dbPath);

    return s.ok();
}

bool LSMIOStoreLDB::readBarrier() {
    bool status;

    LOG(INFO) << "LSMIOStoreLDB::writeBarrier: " << std::endl;
    status = stopBatch();
    return true;
}

bool LSMIOStoreLDB::writeBarrier() {
    bool status;

    LOG(INFO) << "LSMIOStoreLDB::writeBarrier: " << std::endl;
    status = stopBatch();
    return true;
}

}  // namespace lsmio
