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

#ifndef _LSMIO_POSIX_HPP_
#define _LSMIO_POSIX_HPP_

#include <atomic>
#include <fstream>
#include <iostream>
#include <lsmio/manager/manager.hpp>
#include <map>
#include <string>

/**
 * @namespace lsmio
 * @brief Namespace dedicated to LSMIO operations.
 */
namespace lsmio {

/**
 * @class LSMIOStream
 * @brief Provides a stream interface for LSMIO operations.
 */
class LSMIOStream {
  private:
    /// @brief Internal buffer for file operations.
    std::fstream _buf;

    /// @brief Path to the currently associated file.
    std::string _filePath;

    /// @brief Static map to keep track of file offsets.
    static std::map<std::string, std::streamoff> _fileMap;

    /// @brief Static instance of the LSMIO manager.
    static LSMIOManager* _lm;

    /// @brief Atomic flags to indicate the initialization status of LSMIO.
    static std::atomic<int> _lsmioInitialized, _lsmioInitializing, _lsmioCleaning;

    /**
     * @brief Generates a unique key for LSM database operations.
     * @return String containing the generated key.
     */
    std::string _genKey();

  public:
    /**
     * @brief Constructor that can also open a file.
     * @param filename Path to the file (default is nullptr).
     * @param mode File open mode (default is std::ios::out).
     */
    explicit LSMIOStream(const char* filename = nullptr, std::ios::openmode mode = std::ios::out);

    /// @brief Destructor.
    ~LSMIOStream();

    /**
     * @brief Opens a file with the given mode.
     * @param filename Path to the file.
     * @param mode File open mode (default is std::ios::out).
     */
    void open(const char* filename, std::ios::openmode mode = std::ios::out);

    /**
     * @brief Reads data from the LSM database.
     * @param s Pointer to the character buffer.
     * @param n Number of characters to read.
     * @return Reference to the LSMIOStream instance.
     */
    LSMIOStream& read(char* s, std::streamsize n);

    /**
     * @brief Writes data to the LSM database.
     * @param s Pointer to the character buffer containing data.
     * @param n Number of characters to write.
     * @return Reference to the LSMIOStream instance.
     */
    LSMIOStream& write(const char* s, std::streamsize n);

    /**
     * @brief Writes a string to the LSM database.
     * @param s The string to write.
     * @return Reference to the LSMIOStream instance.
     */
    LSMIOStream& write(const std::string& s);

    /**
     * @brief Sets the position of the write pointer.
     * @param off Offset value.
     * @param way Position to seek from (default is std::ios::beg).
     * @return Reference to the LSMIOStream instance.
     */
    LSMIOStream& seekp(std::streamoff off, std::ios::seekdir way = std::ios::beg);

    /**
     * @brief Gets the current position of the write pointer.
     * @return The current position of the write pointer.
     */
    std::streampos tellp();

    /**
     * @brief Retrieves the stream buffer.
     * @return Pointer to the stream buffer.
     */
    std::streambuf* rdbuf() const;

    /**
     * @brief Checks if any IO operations have failed.
     * @return True if there was a failure, false otherwise.
     */
    bool fail() const;

    /**
     * @brief Checks if IO operations are in a good state.
     * @return True if operations are good, false otherwise.
     */
    bool good() const;

    /**
     * @brief Flushes the stream.
     * @return Reference to the LSMIOStream instance.
     */
    LSMIOStream& flush();

    /// @brief Closes the associated file and resets its position in the map.
    void close();

    /**
     * @brief Initializes the LSMIO system.
     * @param dbName Name of the LSM database (default is "lsmio.db").
     * @param dbDir Directory of the LSM database (default is "").
     * @return True if initialization was successful, false otherwise.
     */
    static bool initialize(const std::string& dbName = "lsmio.db", const std::string& dbDir = "");

    /**
     * @brief Cleans up resources used by the LSMIO system.
     * @return True if cleanup was successful, false otherwise.
     */
    static bool cleanup();

    /**
     * @brief Writes and ensures data is saved in the LSM database.
     * @return True if the barrier was successful, false otherwise.
     */
    static bool writeBarrier();
};

}  // namespace lsmio

#endif  // _LSMIO_POSIX_HPP_
