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

#include <rocksdb/cache.h>
#include <rocksdb/merge_operator.h>
#include <rocksdb/slice.h>
#include <rocksdb/table.h>
#include <rocksdb/utilities/options_type.h>
#include <rocksdb/write_batch.h>

#include <algorithm>
#include <atomic>
#include <filesystem>
#include <iostream>
#include <lsmio/manager/store/store_rdb.hpp>

namespace lsmio {

namespace {
static std::unordered_map<std::string, rocksdb::OptionTypeInfo> stringappend_merge_type_info = {
    {"delimiter",
     {0, rocksdb::OptionType::kString, rocksdb::OptionVerificationType::kNormal,
      rocksdb::OptionTypeFlags::kNone}},
};
}

LSMIOStoreRDB::LSMIOStoreRDB(const std::string dbPath, const bool overWrite)
    : LSMIOStore(dbPath, overWrite) {
    rocksdb::Status status;
    rocksdb::BlockBasedTableOptions tableOptions;

    _options.create_if_missing = true;
    _batch = nullptr;

    if (gConfigLSMIO.useBloomFilter) {
        tableOptions.filter_policy.reset(rocksdb::NewBloomFilterPolicy(10));
    }

    if (!gConfigLSMIO.compression) {
        _options.compression = rocksdb::kNoCompression;
    }

    if (gConfigLSMIO.cacheSize > 0) {
        tableOptions.block_cache = rocksdb::NewLRUCache(gConfigLSMIO.cacheSize);
    }

    tableOptions.block_size = gConfigLSMIO.blockSize;

    _options.write_buffer_size = gConfigLSMIO.writeBufferSize;
    _options.max_write_buffer_number = gConfigLSMIO.writeBufferNumber;
    _options.writable_file_max_buffer_size = gConfigLSMIO.writeFileSize;
    _options.max_write_batch_group_size_bytes = gConfigLSMIO.asyncBatchBytes;

    _options.compaction_style = rocksdb::kCompactionStyleNone;
    _options.level0_file_num_compaction_trigger = 1024;
    /* TODO(tybulut): Further tunables:
     * _options.min_write_buffer_number_to_merge = 1;
     * _options.max_background_jobs = std::clamp(gConfigLSMIO.writeBufferNumber, 2, 8);
     */

    _options.disable_auto_compactions = true;        // false
    _options.info_log_level = rocksdb::ERROR_LEVEL;  // DEBUG_LEVEL
    _options.skip_stats_update_on_db_open = false;

    _options.allow_mmap_writes = gConfigLSMIO.enableMMAP;
    _options.allow_mmap_reads = gConfigLSMIO.enableMMAP;
    // _options.unordered_write = true;  // false

    _options.max_successive_merges = 4096;

    _wOptions.disableWAL = !gConfigLSMIO.enableWAL;
    // _options.enable_pipelined_write = true;  // false

    if (gConfigLSMIO.useSync) {
        if (gConfigLSMIO.enableWAL) {
            _wOptions.sync = gConfigLSMIO.useSync;
            LOG(INFO) << "LSMIOStoreRDB::LSMIOStoreRDB: sync writes enabled." << std::endl;
        } else {
            LOG(WARNING) << "LSMIOStoreRDB::LSMIOStoreRDB: ignoring sync writes enablement as WAL "
                            "is disabled."
                         << std::endl;
        }
    }

    _options.table_factory.reset(rocksdb::NewBlockBasedTableFactory(tableOptions));

    if (overWrite) {
        LOG(INFO) << "LSMIOStoreRDB::LSMIOStoreRDB: overWrite is set for the  database: " << _dbPath
                  << std::endl;
        dbCleanup();
    }

    LOG(INFO) << "LSMIOStoreRDB::LSMIOStoreRDB: Creating the database: " << _dbPath << std::endl;
    status = rocksdb::DB::Open(_options, _dbPath, &_db);
    if (status.ok()) {
        LOG(INFO) << "LSMIOStoreRDB::LSMIOStoreRDB: Successfully created the database."
                  << std::endl;
    } else {
        LOG(FATAL) << status.ToString() << std::endl;
        throw std::invalid_argument(
            "ERROR: LSMIOStoreRDB::LSMIOStoreRDB: Failed to open database.");
    }

    if (_db == nullptr) {
        LOG(FATAL) << "LSMIOStoreRDB::LSMIOStoreRDB: Failed to create the database." << std::endl;
        throw std::invalid_argument(
            "ERROR: LSMIOStoreRDB::LSMIOStoreRDB: Failed to create database.");
    }
}

LSMIOStoreRDB::~LSMIOStoreRDB() {
    LOG(INFO) << "LSMIOStoreRDB::~LSMIOStoreRDB(): cleaning up." << std::endl;
    writeBarrier();
    delete _db;
}

bool LSMIOStoreRDB::get(const std::string key, std::string* value) {
    rocksdb::Status s;

    LOG(INFO) << "LSMIOStoreRDB::get(): key: " << key << std::endl;
    s = _db->Get(_rOptions, key, value);
    return s.ok();
}

bool LSMIOStoreRDB::getPrefix(const std::string key, std::vector<std::tuple<std::string, std::string>>* values) {
    rocksdb::Status s;

    LOG(INFO) << "LSMIOStoreRDB::getPrefix(): key: " << key << std::endl;
    rocksdb::Iterator* it = _db->NewIterator(_rOptions);

    it->Seek(key);
    while (it->Valid() && it->key().starts_with(key)) {
        values->emplace_back(it->key().ToString(), it->value().ToString());
        it->Next();
    }

    s = it->status();
    delete it;

    return s.ok();
}

bool LSMIOStoreRDB::_batchMutation(MutationType mType, const std::string key,
                                   const std::string value, bool flush) {
    rocksdb::Status s;
    bool retValue;

    const unsigned int futureSize = _batchSize + 1;
    const unsigned int futureBytes = _batchBytes + value.size();

    LOG(INFO) << "LSMIOStoreRDB::_batchMutation: key: " << key
              << " flush (not-applicable): " << flush << " size: " << value.size()
              << " futureSize: " << futureSize << " futureBytes: " << futureBytes << std::endl;

    LOG(INFO) << "LSMIOStoreRDB::_batchMutation: mutation: " << getMutationType(mType) << std::endl;
    if (mType == MutationType::Put) {
        s = _db->Put(_wOptions, key, value);
    } else if (mType == MutationType::Del) {
        s = _db->Delete(_wOptions, key);
    } else {
        throw std::invalid_argument(
            "ERROR: LSMIOStoreRDB:::_batchMutation: Mutation not implemented.");
    }

    retValue = s.ok();
    return retValue;
}

bool LSMIOStoreRDB::startBatch() {
    LOG(INFO) << "LSMIOStoreRDB::startBatch(): (not-applicable)" << std::endl;
    return true;
}

bool LSMIOStoreRDB::stopBatch() {
    LOG(INFO) << "LSMIOStoreRDB::stopBatch(): not-applicable)" << std::endl;
    return true;
}

bool LSMIOStoreRDB::dbCleanup() {
    rocksdb::Status s;

    LOG(WARNING) << "LSMIOStoreRDB::overWrite: ENTIRE database: " << _dbPath << std::endl;

    s = rocksdb::DestroyDB(_dbPath, _options);
    if (!s.ok()) {
        LOG(FATAL) << s.ToString() << std::endl;
        throw std::invalid_argument("ERROR: LSMIOStoreRDB:::overWrite: Failed to remove database.");
    }

    std::filesystem::remove_all(_dbPath);

    return s.ok();
}

bool LSMIOStoreRDB::readBarrier() { return true; }

bool LSMIOStoreRDB::writeBarrier() {
    rocksdb::Status s;
    rocksdb::FlushOptions fOptions;

    LOG(INFO) << "LSMIOStoreRDB::writeBarrier: " << std::endl;
    s = _db->Flush(fOptions);
    return s.ok();
}

}  // namespace lsmio
