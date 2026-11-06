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

#ifndef _LSMIO_CLIENT_HPP_
#define _LSMIO_CLIENT_HPP_

#include <atomic>
#include <functional>
#include <future>  // NOLINT [build/c++11]
#include <lsmio/lsmio.hpp>
#include <string>
#include <string_view>
#include <thread>  // NOLINT [build/c++11]
#include <vector>

namespace lsmio {

/**
 * @class KV_CMD
 * @brief Constants representing supported Key-Value commands.
 *
 * This class contains string constants that represent the types
 * of commands available in the LSM IO framework.
 */
class KV_CMD {
  public:
    /// @brief Command for retrieving a key-value.
    static const std::string GET;
    /// @brief Command for storing a key-value.
    static const std::string PUT;
    /// @brief Command for deleting a key-value.
    static const std::string DEL;
    /// @brief Command for metadata operations
    static const std::string META_GET;
    static const std::string META_GET_ALL;
    static const std::string META_PUT;
    /// @brief Command for read synchronization.
    static const std::string READ_BARRIER;
    /// @brief Command for write synchronization.
    static const std::string WRITE_BARRIER;
};

/**
 * @class KV_CMD_RETURN
 * @brief Constants representing return values of Key-Value commands.
 *
 * This class contains string constants that represent the return
 * values or responses corresponding to the Key-Value commands.
 */
class KV_CMD_RETURN {
  public:
    /// @brief Return command after a "get" operation.
    static const std::string GET;
    /// A GET whose key was not found or could not be read
    static const std::string GET_FAIL;
    static const std::string META_GET;
    /// A META_GET whose key was not found or could not be read
    static const std::string META_GET_FAIL;
    static const std::string META_GET_ALL;
    /// @brief Return command after a read barrier.
    static const std::string READ_BARRIER;
    /// @brief Return command after a write barrier.
    static const std::string WRITE_BARRIER;
};

/// Dummy key-value string used for unknown or placeholder values.
const std::string KV_DUMMY = "DUMMY";

class LSMIOManager;

/**
 * @typedef LSMIOClientCallback
 * @brief Type definition for the LSMIO client callback function.
 *
 * This callback function type represents the method signature for
 * handling responses or events within the LSMIO client.
 */
using LSMIOClientCallback = bool (LSMIOManager::*)(int, const std::string &, const std::string &,
                                                   std::string *, std::string);

/**
 * @class LSMIOClient
 * @brief Represents the client-side logic for the LSM IO operations.
 *
 * This abstract class defines the basic operations and attributes
 * required for a client in the LSM IO framework.
 */
class LSMIOClient {
  protected:
    /// @brief Rank of the client in the cluster.
    int _rank;
    /// @brief Total number of clients in the cluster.
    int _size;
    /// @brief Atomic flag to check if the server loop is running.
    std::atomic<int> _loopRunning = {0};
    /// @brief Thread handling the server-side operations.
    std::thread _serverThread;

    // TODO(sbulut): Adjust _loopWaitMS for production use
    /// @brief Wait time in the loop. Adjust for production use.
    const int _loopWaitMS = 10;

    /// End-of-Line command string, used to signal the end of a command sequence.
    const std::string _EOL_COMMAND = "__EOL";
    /// Column separator string, used in serialization.
    const std::string _COL_SEPARATOR_STR = ";";
    /// Column separator character, used in deserialization.
    const char _COL_SEPARATOR_CHAR = ';';

    /**
     * @brief Serializes the provided command, key, and value into a string buffer.
     * @param buf Buffer where the serialized string will be stored.
     * @param command The command to serialize.
     * @param key The key to serialize.
     * @param value The value to serialize.
     */
    void serializeCmd(std::string *buf, const std::string &command, const std::string &key,
                      std::string_view value);

    /**
     * @brief Deserializes the provided buffer into command, key, and value.
     * @param buf The buffer containing the serialized string.
     * @param len The length of the buffer.
     * @param command Output parameter for the deserialized command.
     * @param key Output parameter for the deserialized key.
     * @param value Output parameter for the deserialized value.
     */
    void deSerializeCmd(const char *buf, const int &len, std::string *command, std::string *key,
                        std::string *value);

    /**
     * @brief Waits for a command to arrive and processes it using the provided callback function.
     * @param func The callback function to handle the command.
     * @param lm The LSMIO manager instance.
     */
    void _waitForCommand(LSMIOClientCallback func, LSMIOManager *lm);

    /// @brief Cancels the waiting state for incoming commands.
    void _cancelWaitForCommand();

    /// @brief Virtual function to implement a barrier mechanism.
    virtual void _barrier() = 0;

    /// @brief Virtual function returning the maximum of value over the ranks of this client's
    /// communicator, i.e. the aggregation group (a barrier that carries a value).
    virtual int _allreduceMax(int value) = 0;

    /**
     * @brief Virtual function to receive data into a buffer.
     * @param bufSizes Pointer to an integer storing the size of the received buffer.
     * @param eolRanks Ranks that have sent their end-of-life command: nothing is received from
     * them (their buffer is null).
     * @return A pointer to the received data.
     */
    virtual char **_recvToBuffer(int *bufSizes, const std::vector<int> &eolRanks) = 0;

  public:
    /// @brief Default constructor for LSMIOClient.
    LSMIOClient();

    /// @brief Destructor for LSMIOClient, responsible for cleanup.
    virtual ~LSMIOClient();

    /**
     * @brief Static function to create a helper thread for the client.
     * @param ctx The context of the LSMIO client.
     * @param func The callback function to handle commands.
     * @param lm The LSMIO manager instance.
     * @param threadBarrier A promise object used for thread synchronization.
     */
    static void helperThread(LSMIOClient *ctx, LSMIOClientCallback func, LSMIOManager *lm,
                             std::promise<void> threadBarrier);

    /// @brief Returns whether MPI provides MPI_THREAD_MULTIPLE, which aggregated I/O needs.
    static bool checkThreadSupport();

    /**
     * @brief Starts the server thread for collective IO operations.
     * @param func The callback function to handle commands.
     * @param lm The LSMIO manager instance.
     * @return True if the server was started successfully, false otherwise.
     */
    bool startCollectiveIOServer(LSMIOClientCallback func, LSMIOManager *lm);

    /// @brief Starts the client for collective IO operations.
    bool startCollectiveIOClient();

    /**
     * @brief Stops the server thread for collective IO operations.
     * @param finish Called once every client's commands are processed: flushes the store and
     * returns false if any of them failed.
     * @return False if finish or any rank reported a failure.
     */
    bool stopCollectiveIOServer(const std::function<bool()> &finish);

    /**
     * @brief Stops the client for collective IO operations.
     * @param rank The rank of the client to be stopped.
     * @return False if any rank reported a failure (e.g. a put the aggregator could not store).
     */
    bool stopCollectiveIOClient(int rank);

    /**
     * @brief Sends a command to a specific rank.
     * @param rank The rank of the target client.
     * @param command The command to send.
     * @param key The key associated with the command.
     * @param value The value associated with the command.
     * @return True if the command was sent successfully, false otherwise.
     */
    virtual bool sendCommand(int rank, const std::string &command, const std::string &key,
                             std::string_view value) = 0;

    /**
     * @brief Receives a command from a specific rank.
     * @param rank The rank of the source client.
     * @param command The command to receive.
     * @param key The key associated with the command.
     * @param value The value associated with the command.
     * @return True if the command was received successfully, false otherwise.
     */
    virtual bool recvCommand(int rank, std::string *command, std::string *key,
                             std::string *value) = 0;
};

}  // namespace lsmio

#endif  // _LSMIO_CLIENT_HPP_
