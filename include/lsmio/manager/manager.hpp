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

#ifndef _LSMIO_MANAGER_HPP_
#define _LSMIO_MANAGER_HPP_

#include <adios2.h>
#include <adios2/helper/adiosComm.h>
#include <adios2/helper/adiosCommMPI.h>
#include <mpi.h>

#include <lsmio/lsmio.hpp>
#include <lsmio/manager/client/client.hpp>
#include <lsmio/manager/store/store_ldb.hpp>
#include <lsmio/manager/store/store_rdb.hpp>
#include <string>

#if ADIOS2_USE_MPI
#else
#error "ERROR: ADIOS2 does not have MPI (ADIOS2_USE_MPI=0)"
#endif

namespace lsmio {

/**
 * @class LSMIOManager
 * @brief Class for managing LSMIO operations.
 */
class LSMIOManager {
  private:
    /// @brief Name of the database.
    std::string _dbName;
    /// @brief Directory of the database.
    std::string _dbDir;
    /// @brief Path to the database.
    std::string _dbPath;

    /// @brief Store instance.
    LSMIOStore *_lcStore = nullptr;
    /// @brief Client instance.
    LSMIOClient *_lcMPI = nullptr;

    /// @brief Flag to indicate overwrite.
    bool _isOverWrite = false;
    /// @brief Flag to indicate sharing mode.
    bool _isShared = false;
    /// @brief Flag to indicate shared split mode.
    bool _isSharedSplit = false;

    /// @brief Counter for written bytes.
    uint64_t _counterWriteBytes = 0;
    /// @brief Counter for read bytes.
    uint64_t _counterReadBytes = 0;
    /// @brief Counter for write operations.
    uint64_t _counterWriteOps = 0;
    /// @brief Counter for read operations.
    uint64_t _counterReadOps = 0;

    /// @brief Adios communication instance.
    adios2::helper::Comm *_adiosComm = nullptr;
    /// @brief MPI communication instance.
    MPI_Comm _mpiComm = 0;
    /// @brief Rank in the world communicator.
    int _worldRank = 0;
    /// @brief Size of the world communicator.
    int _worldSize = 1;

    /// @brief Aggregator communication instance.
    MPI_Comm _aggComm = 0;
    /// @brief Rank in the aggregator communicator.
    int _aggRank = 0;
    /// @brief Size of the aggregator communicator.
    int _aggSize = 1;

    /// @brief Static instance of LSMIOManager.
    static LSMIOManager *_lm;
    /// @brief Initialization status.
    static std::atomic<int> _lmInitialized;
    /// @brief Initializing status.
    static std::atomic<int> _lmInitializing;
    /// @brief Cleaning status.
    static std::atomic<int> _lmCleaning;

    /**
     * @brief Initialize the LSMIOManager instance.
     */
    void _init();

    bool _isOpenLocal() const;
    bool _isOpenRemote() const;
    bool _isServeLocal() const;

    std::string _rankedKey(const int rank, const std::string &key) const;
    std::string _rankedKey(const std::string &key) const;

  public:
    /// @brief Aggregation rank constant.
    const int AGGREGATION_RANK = 0;
    /// @brief Infix for aggregation directory.
    const std::string AGGREGATION_DIR_INFIX = "agg";

    /**
     * @brief Constructor with MPI communicator.
     */
    LSMIOManager(const std::string &dbName, const std::string &dbDir = "",
                 const bool overWrite = false, MPI_Comm mpiComm = 0);

    /**
     * @brief Constructor with Adios communicator.
     */
    LSMIOManager(const std::string &dbName, const std::string &dbDir, const bool overWrite,
                 adios2::helper::Comm *adiosComm);

    /**
     * @brief Destructor.
     */
    ~LSMIOManager();

    /// callback for collective I/O
    void callbackForCollectiveIO(int rank, const std::string &command, const std::string &key,
                                 std::string *gValue, std::string pValue);

    /// Get DB path
    /// @return dbName
    std::string getDbPath() const;

    /**
     * @brief Get a value associated with a key into the database.
     *
     * @param key The key associated with the value.
     * @param value The value to write the retrieved value to.
     * @return Returns true if the operation is successful, false otherwise.
     */
    bool get(const std::string &key, std::string *value);

    /**
     * @brief Put a value associated with a key into the database.
     *
     * @param key The key associated with the value.
     * ...
     * @return Returns true if the operation is successful, false otherwise.
     */
    bool put(const std::string &key, const std::string &value, bool flush);
    bool put(const std::string &key, const std::string &value);
    bool put(const std::string &key, const char *value, std::streamsize n);
    bool put(const std::string &key, const void *ptr, size_t size, size_t count);

    /**
     * @brief Append a value to an existing key in the database.
     *
     * @param key The key associated with the value.
     * @param value The value to append.
     * @param flush Whether to flush after appending.
     * @return Returns true if the operation is successful, false otherwise.
     */
    bool append(const std::string &key, const std::string &value, bool flush);

    /**
     * @brief Delete a value associated with a key from the database.
     *
     * @param key The key associated with the value to delete.
     * ...
     * @return Returns true if the operation is successful, false otherwise.
     */
    bool del(const std::string &key, bool flush);
    bool del(const std::string &key);

    /// read and write barrier for async operations
    /// @return bool success
    bool readBarrier();
    bool writeBarrier();

    void resetCounters();
    void getCounters(uint64_t &writeBytes, uint64_t &readBytes, uint64_t &writeOps,
                     uint64_t &readOps) const;

    static LSMIOManager *initialize(const std::string &dbName = "lsmiodb",
                                    const std::string &dbDir = "", const bool overWrite = false,
                                    adios2::helper::Comm *adiosComm = nullptr);
    static LSMIOManager *getManager();
    static bool cleanup();
};

}  // namespace lsmio

#endif  // INCLUDE_LSMIO_MANAGER_MANAGER_HPP_
