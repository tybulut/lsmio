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

#include <filesystem>
#include <iostream>
#include <lsmio/manager/client/client_adios.hpp>
#include <lsmio/manager/client/client_mpi.hpp>
#include <lsmio/manager/manager.hpp>
#include <sstream>
#include <string>
#include <tuple>
#include <vector>

namespace lsmio {

LSMIOManager* LSMIOManager::_lm = nullptr;
std::atomic<int> LSMIOManager::_lmInitialized = 0;
std::atomic<int> LSMIOManager::_lmInitializing = 0;
std::atomic<int> LSMIOManager::_lmCleaning = 0;


void vectorTupleSerialize(const std::vector<std::tuple<std::string, std::string>>& values,
                          std::string& value) {
    std::stringstream ss;
    for (const auto& tup : values) {
        ss << std::get<0>(tup) << "|" << std::get<1>(tup) << "\n";
    }
    value = ss.str();
}

void vectorTupleDeserialize(const std::string& serialized_data,
                            std::vector<std::tuple<std::string, std::string>>& values) {
    std::stringstream ss(serialized_data);
    std::string line;

    while (std::getline(ss, line, '\n')) {
        if (line.empty()) {
            continue;
        }

        size_t delimiter_pos = line.find('|');
        if (delimiter_pos != std::string::npos) {
            std::string first_str = line.substr(0, delimiter_pos);
            std::string second_str = line.substr(delimiter_pos + 1);
            values.emplace_back(first_str, second_str);
        }
    }
}

LSMIOManager::LSMIOManager(const std::string& dbName, const std::string& dbDir,
                           const bool overWrite, MPI_Comm mpiComm) {
    _dbName = dbName;
    _dbDir = dbDir;
    _isOverWrite = overWrite;
    if (mpiComm) _mpiComm = mpiComm;

    LOG(INFO) << "LSMIOManager::LSMIOManager: Will initialize with MPI optionally." << std::endl;
    _init();
}

LSMIOManager::LSMIOManager(const std::string& dbName, const std::string& dbDir,
                           const bool overWrite, adios2::helper::Comm* adiosComm) {
    _dbName = dbName;
    _dbDir = dbDir;
    _isOverWrite = overWrite;
    _adiosComm = adiosComm;

    LOG(INFO) << "LSMIOManager::LSMIOManager: Will initialize with Adios." << std::endl;
    _init();
}

void LSMIOManager::_init() {
    if (_adiosComm) {
        LOG(INFO) << "LSMIOManager::_init: Adios comm object is not null." << std::endl;

        if (!_adiosComm->IsMPI()) {
            throw std::invalid_argument(
                "ERROR: LSMIOManager:_init: file opened in shared mode without MPI.");
            exit(1);
        }

        MPI_Comm_dup(adios2::helper::CommAsMPI(*_adiosComm), &_mpiComm);
    }

    if (_mpiComm) {
        LOG(INFO) << "LSMIOManager::_init: MPI comm object is not null." << std::endl;

        MPI_Comm_rank(_mpiComm, &_worldRank);
        MPI_Comm_size(_mpiComm, &_worldSize);

        if (_worldSize > 1) {
            LOG(INFO) << "LSMIOManager::_init: MPI comm world is greater than 1." << std::endl;
            _isShared = true;

            if (gConfigLSMIO.mpiAggType == MPIAggType::Shared) {
                _isSharedSplit = true;
                MPI_Comm_split_type(_mpiComm, MPI_COMM_TYPE_SHARED, AGGREGATION_RANK, MPI_INFO_NULL,
                                    &_aggComm);
            } else if (gConfigLSMIO.mpiAggType == MPIAggType::Split) {
                _isSharedSplit = true;
                int splitSize = _worldRank / 2;
                MPI_Comm_split(_mpiComm, splitSize, _worldRank, &_aggComm);
            } else {
                // gConfigLSMIO.mpiAggType == MPIAggType::Entire or MPIAggType::EntireSerial
                _aggComm = _mpiComm;
            }

            MPI_Comm_rank(_aggComm, &_aggRank);
            MPI_Comm_size(_aggComm, &_aggSize);
        }
    }

    if (_isShared && _isSharedSplit) {
        std::filesystem::path pathDBDir(_dbDir);
        pathDBDir /= AGGREGATION_DIR_INFIX;
        pathDBDir /= std::to_string(_worldRank);

        _dbDir = pathDBDir.string();
        if (_aggRank == AGGREGATION_RANK) {
            std::filesystem::create_directories(_dbDir);
        }
    }
    _dbPath = (_dbDir.empty()) ? _dbName : _dbDir + "/" + _dbName;

    // Startup: RDB first and MPI afterwards to ensure DB available before MPI messages are received
    if (_isOpenLocal()) {
        if (gConfigLSMIO.storageType == StorageType::NativeDB) {
            LOG(INFO) << "LSMIOManager::_init: setting up Native backend." << std::endl;
            _lcStore = new LSMIOStoreNative(_dbPath, _isOverWrite);
        } else if (gConfigLSMIO.storageType == StorageType::RocksDB) {
            LOG(INFO) << "LSMIOManager::_init: setting up RocksDB backend." << std::endl;
            _lcStore = new LSMIOStoreRDB(_dbPath, _isOverWrite);
        } else if (gConfigLSMIO.storageType == StorageType::LevelDB) {
            LOG(INFO) << "LSMIOManager::_init: setting up LevelDB backend." << std::endl;
            _lcStore = new LSMIOStoreLDB(_dbPath, _isOverWrite);
        } else {
            LOG(ERROR) << "LSMIOManager::_init: unknown gConfigLSMIO.storageType: "
                       << to_string(gConfigLSMIO.storageType) << std::endl;
            throw std::invalid_argument("ERROR: LSMIOManager: Unknown gConfigLSMIO.storageType.");
        }
    }

    if (_isOpenRemote() || _isServeLocal()) {
        _lcMPI = new LSMIOClientMPI(_aggComm);

        if (_isServeLocal()) {
            _lcMPI->checkThreadSupport();
        }
    }

    if (_isServeLocal()) {
        LOG(INFO) << "LSMIOManager::_init: starting collective I/O server." << std::endl;
        _lcMPI->startCollectiveIOServer(&LSMIOManager::callbackForCollectiveIO, this);
    } else if (_isOpenRemote()) {
        LOG(INFO) << "LSMIOManager::_init: starting collective I/O client." << std::endl;
        _lcMPI->startCollectiveIOClient();
    }

    LOG(INFO) << "LSMIOManager::_init: rank: " << _aggRank << std::endl;
}

LSMIOManager::~LSMIOManager() {
    close();
}

void LSMIOManager::close() {
    LOG(INFO) << "LSMIOManager::close(): rank: " << _aggRank << std::endl;
    // Delete MPI first because its cleanup might require RDB being open
    if (_lcMPI) {
        if (_isServeLocal()) {
            _lcMPI->stopCollectiveIOServer();
        } else if (_isOpenRemote()) {
            _lcMPI->stopCollectiveIOClient(AGGREGATION_RANK);
        }
        delete _lcMPI;
        _lcMPI = nullptr;
    }

    if (_lcStore) {
        _lcStore->close();
        delete _lcStore;
        _lcStore = nullptr;
    }
}

bool LSMIOManager::_isOpenLocal() const {
    return (!_isShared || _aggRank == AGGREGATION_RANK);
}

bool LSMIOManager::_isOpenRemote() const {
    return (_isShared && _aggRank != AGGREGATION_RANK);
}

bool LSMIOManager::_isServeLocal() const {
    return (_isShared && _aggRank == AGGREGATION_RANK && _aggSize > 1);
}

std::string LSMIOManager::_rankedKey(const int rank, const std::string& key) const {
    return (_isServeLocal()) ? (std::to_string(rank) + "::" + key) : key;
}

std::string LSMIOManager::_rankedKey(const std::string& key) const {
    return _rankedKey(_aggRank, key);
}

std::string LSMIOManager::getDbPath() const {
    return _dbPath;
}

bool LSMIOManager::get(const std::string& key, std::string* value) {
    bool retValue = true;

    LOG(INFO) << "LSMIOManager::get: for rank: " << _aggRank << " key: " << key << std::endl;
    if (_isOpenLocal()) {
        LOG(INFO) << "LSMIOManager::get: LOCAL for rank: " << _aggRank << std::endl;
        retValue = _lcStore->get(_rankedKey(key), value);

        _counterReadBytes += value->length();
        _counterReadOps++;

        return retValue;
    }

    if (_isOpenRemote()) {
        retValue &= _lcMPI->sendCommand(AGGREGATION_RANK, KV_CMD::GET, key, KV_DUMMY);

        std::string cCommand, cKey;
        retValue &= _lcMPI->recvCommand(AGGREGATION_RANK, &cCommand, &cKey, value);

        _counterReadBytes += value->length();
        _counterReadOps++;

        if (cCommand != KV_CMD_RETURN::GET) {
            LOG(ERROR) << "LSMIOManager::get: received incorrect command: " << cCommand
                       << std::endl;
            return false;
        }
    }

    return retValue;
}

bool LSMIOManager::put(const std::string& key, const std::string& value, bool flush) {
    bool retValue = true;

    LOG(INFO) << "LSMIOManager::put:flush: rank: " << _aggRank << " key: " << key << "("
              << key.length() << ")"
              << " value.len: " << value.length() << " flush: " << flush << std::endl;

    _counterWriteBytes += value.length();
    _counterWriteOps++;

    if (_isOpenLocal()) {
        LOG(INFO) << "LSMIOManager::put: LOCAL for rank: " << _aggRank << std::endl;
        return _lcStore->put(_rankedKey(key), value, flush);
    }

    if (_isOpenRemote()) {
        retValue &= _lcMPI->sendCommand(AGGREGATION_RANK, KV_CMD::PUT, key, value);
    }

    return retValue;
}

bool LSMIOManager::put(const std::string& key, const std::string& value) {
    LOG(INFO) << "LSMIOManager::put: for rank: " << _aggRank << " key: " << key << std::endl;
    return put(key, value, gConfigLSMIO.alwaysFlush);
}

bool LSMIOManager::put(const std::string& key, const char* value, std::streamsize n) {
    LOG(INFO) << "LSMIOManager::put: for char* for rank: " << _aggRank << " key: " << key
              << std::endl;
    std::string nValue(value, n);
    return put(key, nValue, gConfigLSMIO.alwaysFlush);
}

bool LSMIOManager::put(const std::string& key, const void* value, size_t size, size_t count) {
    LOG(INFO) << "LSMIOManager::put: for void* for rank: " << _aggRank << " key: " << key
              << std::endl;
    std::string nValue(static_cast<const char*>(value), size * count);
    return put(key, nValue, gConfigLSMIO.alwaysFlush);
}

bool LSMIOManager::del(const std::string& key, bool flush) {
    bool retValue = true;

    LOG(INFO) << "LSMIOManager::del:flush: for rank: " << _aggRank << " key: " << key << std::endl;
    if (_isOpenLocal()) {
        LOG(INFO) << "LSMIOManager::del: LOCAL for rank: " << _aggRank << std::endl;
        return _lcStore->del(_rankedKey(key), flush);
    }

    if (_isOpenRemote()) {
        retValue &= _lcMPI->sendCommand(AGGREGATION_RANK, KV_CMD::DEL, key, KV_DUMMY);
    }

    return retValue;
}

bool LSMIOManager::del(const std::string& key) {
    LOG(INFO) << "LSMIOManager::del: for rank: " << _aggRank << " key: " << key << std::endl;
    return del(key, gConfigLSMIO.alwaysFlush);
}

bool LSMIOManager::metaGet(const std::string& key, std::string* value) {
    bool retValue = true;

    LOG(INFO) << "LSMIOManager::metaGet: for rank: " << _aggRank << " key: " << key << std::endl;
    if (_isOpenLocal()) {
        LOG(INFO) << "LSMIOManager::metaGet: LOCAL for rank: " << _aggRank << std::endl;
        retValue = _lcStore->metaGet(_rankedKey(key), value);

        _counterReadBytes += value->length();
        _counterReadOps++;

        return retValue;
    }

    if (_isOpenRemote()) {
        retValue &= _lcMPI->sendCommand(AGGREGATION_RANK, KV_CMD::META_GET, key, KV_DUMMY);

        std::string cCommand, cKey;
        retValue &= _lcMPI->recvCommand(AGGREGATION_RANK, &cCommand, &cKey, value);

        _counterReadBytes += value->length();
        _counterReadOps++;

        if (cCommand != KV_CMD_RETURN::META_GET) {
            LOG(ERROR) << "LSMIOManager::metaGet: received incorrect command: " << cCommand
                       << std::endl;
            return false;
        }
    }

    return retValue;
}

bool LSMIOManager::metaGetAll(std::vector<std::tuple<std::string, std::string>>* values,
                              std::string inFix) {
    bool retValue = true;

    LOG(INFO) << "LSMIOManager::metaGetAll: for rank: " << _aggRank << std::endl;
    if (_isOpenLocal()) {
        LOG(INFO) << "LSMIOManager::metaGetAll: LOCAL for rank: " << _aggRank << std::endl;
        retValue = _lcStore->metaGetAll(values, inFix);

        _counterReadBytes += values->size();
        _counterReadOps++;

        return retValue;
    }

    if (_isOpenRemote()) {
        LOG(INFO) << "LSMIOManager::metaGetAll: REMOTE to rank: " << _aggRank << std::endl;
        retValue &= _lcMPI->sendCommand(AGGREGATION_RANK, KV_CMD::META_GET_ALL, KV_DUMMY, KV_DUMMY);

        std::string cCommand, cKey;
        std::string value;

        LOG(INFO) << "LSMIOManager::metaGetAll: waiting for REMOTE." << std::endl;
        retValue &= _lcMPI->recvCommand(AGGREGATION_RANK, &cCommand, &cKey, &value);
        LOG(INFO) << "LSMIOManager::metaGetAll: REMOTE response received len: " << value.length()
                  << std::endl;

        _counterReadBytes += value.length();
        _counterReadOps++;

        lsmio::vectorTupleDeserialize(value, *values);

        if (cCommand != KV_CMD_RETURN::META_GET_ALL) {
            LOG(ERROR) << "LSMIOManager::metaGetAll: received incorrect command: " << cCommand
                       << std::endl;
            return false;
        }
    }

    return retValue;
}

bool LSMIOManager::metaPut(const std::string& key, const std::string& value, bool flush) {
    bool retValue = true;

    LOG(INFO) << "LSMIOManager::metaPut: rank: " << _aggRank << " key: " << key << "("
              << key.length() << ")"
              << " value.len: " << value.length() << " flush: " << flush << std::endl;

    _counterWriteBytes += value.length();
    _counterWriteOps++;

    if (_isOpenLocal()) {
        LOG(INFO) << "LSMIOManager::metaPut: LOCAL for rank: " << _aggRank << std::endl;
        return _lcStore->metaPut(_rankedKey(key), value, flush);
    }

    if (_isOpenRemote()) {
        retValue &= _lcMPI->sendCommand(AGGREGATION_RANK, KV_CMD::META_PUT, key, value);
    }

    return retValue;
}

bool LSMIOManager::readBarrier() {
    bool retValue = true;

    LOG(INFO) << "LSMIOManager::readBarrier: for rank: " << _aggRank << std::endl;
    if (_isOpenLocal()) {
        LOG(INFO) << "LSMIOManager::readBarrier: LOCAL for rank: " << _aggRank << std::endl;
        return _lcStore->readBarrier();
    }

    if (_isOpenRemote()) {
        retValue &= _lcMPI->sendCommand(AGGREGATION_RANK, KV_CMD::READ_BARRIER, KV_DUMMY, KV_DUMMY);

        std::string cCommand, cKey, cValue;
        retValue &= _lcMPI->recvCommand(AGGREGATION_RANK, &cCommand, &cKey, &cValue);

        if (cCommand != KV_CMD_RETURN::READ_BARRIER) {
            LOG(ERROR) << "LSMIOManager::readBarrier: received incorrect command: " << cCommand
                       << std::endl;
            return false;
        }
    }

    return retValue;
}

bool LSMIOManager::writeBarrier() {
    bool retValue = true;

    LOG(INFO) << "LSMIOManager::writeBarrier: for rank: " << _aggRank << std::endl;
    if (_isOpenLocal()) {
        LOG(INFO) << "LSMIOManager::writeBarrier: LOCAL for rank: " << _aggRank << std::endl;
        return _lcStore->writeBarrier();
    }

    if (_isOpenRemote()) {
        retValue &=
            _lcMPI->sendCommand(AGGREGATION_RANK, KV_CMD::WRITE_BARRIER, KV_DUMMY, KV_DUMMY);

        std::string cCommand, cKey, cValue;
        retValue &= _lcMPI->recvCommand(AGGREGATION_RANK, &cCommand, &cKey, &cValue);

        if (cCommand != KV_CMD_RETURN::WRITE_BARRIER) {
            LOG(ERROR) << "LSMIOManager::writeBarrier: received incorrect command: " << cCommand
                       << std::endl;
            return false;
        }
    }

    return retValue;
}

void LSMIOManager::callbackForCollectiveIO(int rank, const std::string& command,
                                           const std::string& key, std::string* gValue,
                                           std::string pValue) {
    bool retValue = true;

    LOG(INFO) << "LSMIOManager::callbackForCollectiveIO: " << command << ": " << key << std::endl;

    if (command == KV_CMD::GET) {
        retValue &= _lcStore->get(_rankedKey(rank, key), gValue);
    } else if (command == KV_CMD::PUT) {
        retValue &= _lcStore->put(_rankedKey(rank, key), pValue, gConfigLSMIO.alwaysFlush);
    } else if (command == KV_CMD::DEL) {
        retValue &= _lcStore->del(_rankedKey(rank, key), gConfigLSMIO.alwaysFlush);
    } else if (command == KV_CMD::META_GET) {
        retValue &= _lcStore->metaGet(_rankedKey(rank, key), gValue);
    } else if (command == KV_CMD::META_GET_ALL) {
        std::vector<std::tuple<std::string, std::string>> values;
        std::string inFix = std::to_string(rank) + "::";  // _rankedKey
        retValue &= _lcStore->metaGetAll(&values, inFix);
        lsmio::vectorTupleSerialize(values, *gValue);
    } else if (command == KV_CMD::META_PUT) {
        retValue &= _lcStore->metaPut(_rankedKey(rank, key), pValue, gConfigLSMIO.alwaysFlush);
    } else if (command == KV_CMD::WRITE_BARRIER) {
        retValue &= _lcStore->writeBarrier();
    } else {
        LOG(ERROR) << "LSMIOManager::callbackForCollectiveIO: UNKNOWN command: " << command
                   << std::endl;
        retValue = false;
    }

    LOG(INFO) << "LSMIOManager::callbackForCollectiveIO: " << command << ": COMPLETED."
              << std::endl;
}

void LSMIOManager::resetCounters() {
    _counterWriteBytes = 0;
    _counterReadBytes = 0;
    _counterWriteOps = 0;
    _counterReadOps = 0;
}

void LSMIOManager::getCounters(uint64_t& writeBytes, uint64_t& readBytes, uint64_t& writeOps,
                               uint64_t& readOps) const {
    writeBytes = _counterWriteBytes;
    readBytes = _counterReadBytes;
    writeOps = _counterWriteOps;
    readOps = _counterReadOps;
}

LSMIOManager* LSMIOManager::initialize(const std::string& dbName, const std::string& dbDir,
                                       const bool overWrite, adios2::helper::Comm* comm) {
    if (_lmInitialized) {
        LOG(WARNING) << "LSMIOManager::initialize: already initialiazed: " << dbName << std::endl;
        return nullptr;
    }

    if (_lmInitializing) {
        LOG(WARNING) << "LSMIOManager::initialize: already initialiazing: " << dbName << std::endl;
        return nullptr;
    }

    _lmInitializing = 1;
    LOG(INFO) << "LSMIOManager::initialize: initialiazing: " << dbName << std::endl;

    _lm = new lsmio::LSMIOManager(dbName, dbDir, overWrite, comm);

    _lmInitializing = 0;
    _lmInitialized = 1;

    LOG(INFO) << "LSMIOManager::initialize: completed: " << dbName << std::endl;
    return _lm;
}

LSMIOManager* LSMIOManager::getManager() {
    if (!_lmInitialized || _lmInitializing) {
        if (!_lmInitialized)
            LOG(WARNING) << "LSMIOManager::getManager: not initialiazed." << std::endl;
        else
            LOG(WARNING) << "LSMIOManager::getManager: currently initialiaizing." << std::endl;
        return nullptr;
    }

    if (_lmCleaning) {
        LOG(WARNING) << "LSMIOManager::getManager: currently cleaning." << std::endl;
        return nullptr;
    }

    return _lm;
}

bool LSMIOManager::cleanup() {
    if (!_lmInitialized || _lmInitializing) {
        if (!_lmInitialized)
            LOG(WARNING) << "LSMIOManager::cleanup: not initialiazed." << std::endl;
        else
            LOG(WARNING) << "LSMIOManager::cleanup: currently initialiaizing." << std::endl;
        return false;
    }

    if (_lmCleaning) {
        LOG(WARNING) << "LSMIOManager::cleanup: already cleaning." << std::endl;
        return false;
    }

    _lmCleaning = 1;
    LOG(WARNING) << "LSMIOManager::cleanup: cleaning." << std::endl;

    delete _lm;
    _lm = nullptr;

    _lmCleaning = 0;
    _lmInitialized = 0;
    return true;
}

}  // namespace lsmio
