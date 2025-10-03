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

#ifndef _LSMIO_LSMIO_H
#define _LSMIO_LSMIO_H

#ifdef NDEBUG
#define GOOGLE_STRIP_LOG 1
#endif

#include <glog/logging.h>

#include <map>
#include <string>

// TODO(sbulut): RDMA
// TODO(sbulut): High number of variables

namespace lsmio {

/**
 * Initialize LSMIO for release mode.
 * @param name Name used for initializing Google Logging.
 */
void initLSMIORelease(char *name);

/**
 * Initialize LSMIO for debug mode.
 * @param name Name used for initializing Google Logging.
 */
void initLSMIODebug(char *name);

/// Increase the verbosity of LSMIO logging.
void increaseLSMIOLogging();

/// Decrease the verbosity of LSMIO logging.
void decreaseLSMIOLogging();

/// Set the default logging behavior for LSMIO.
void defaultLSMIOLogging();

/**
 * Enum representing the types of MPI aggregation.
 */
enum class MPIAggType { Shared, Entire, EntireSerial, Split };

/**
 * Enum representing the storage types supported by LSMIO.
 */
enum class StorageType { LevelDB, RocksDB };

/**
 * Configuration class for LSMIO settings.
 */
class LSMIOConfig {
  public:
    /// @brief Default storage type.
    StorageType storageType = StorageType::RocksDB;
    /// @brief Default MPI aggregation type.
    MPIAggType mpiAggType = MPIAggType::Shared;

    // General settings
    /// @brief Flag to use Bloom Filter.
    bool useBloomFilter = false;
    /// @brief Flag for synchronous operations.
    bool useSync = false;
    /// @brief Flag to enable memory-mapped files.
    bool enableMMAP = false;
    /// @brief Flag to enable data compression.
    bool compression = false;

    /// @brief Default block size.
    int blockSize = 512 * 1024;
    /// @brief Default transfer size.
    int transferSize = 512 * 1024;

    // RocksDB specific settings
    /// @brief Flag to enable write-ahead logging.
    bool enableWAL = false;
    /// @brief Number of write buffers.
    int writeBufferNumber = 2;

    // LevelDB specific settings
    /// @brief Flag for batch flushing.
    bool alwaysFlush = false;  // BATCH

    /// @brief Default cache size.
    int cacheSize = 0;
    /// @brief Default write buffer size.
    int writeBufferSize = 64 * 1024 * 1024;
    /// @brief Default write file size.
    int writeFileSize = 8 * 1024 * 1024;
};

/// Global configuration instance for LSMIO.
extern LSMIOConfig gConfigLSMIO;

/**
 * Helper class for LSMIO.
 * Provides utility functions for managing flags.
 */
class LSMIOHelper {
  public:
    /// @brief Flag for dual write mode.
    static const std::string FLAG_DUAL;
    /// @brief Flag for fallback write mode.
    static const std::string FLAG_FALLBACK;

    /**
     * Retrieve the value of a given flag.
     * @param key Flag key.
     * @return true if the flag is set, false otherwise.
     */
    static bool getFlag(const std::string key);

    /**
     * Set the value of a given flag.
     * @param key Flag key.
     * @param value Value to set the flag to.
     */
    static void setFlag(const std::string key, const bool value);
};

/**
 * Prints stack trace after a segmentation fault
 * @param signal the signal that is caught
 */
void handlerSIGSEGV(int signal);

/**
 * Convert an MPIAggType value to its string representation.
 * @param v MPIAggType value.
 * @return String representation of v.
 */
std::string to_string(const MPIAggType v);

/**
 * Convert a StorageType value to its string representation.
 * @param v StorageType value.
 * @return String representation of v.
 */
std::string to_string(const StorageType v);

}  // namespace lsmio

/// Stream overload for MPIAggType.
std::ostream &operator<<(std::ostream &os, lsmio::MPIAggType v);

/// Stream overload for StorageType.
std::ostream &operator<<(std::ostream &os, lsmio::StorageType v);

/// Stream overload for MPIAggType (const reference).
std::ostream &operator<<(std::ostream &os, const lsmio::MPIAggType &v);

/// Stream overload for StorageType (const reference).
std::ostream &operator<<(std::ostream &os, const lsmio::StorageType &v);

#endif  // _LSMIO_LSMIO_H
