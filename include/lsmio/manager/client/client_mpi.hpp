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

#ifndef _LSMIO_CLIENT_MPI_HPP_
#define _LSMIO_CLIENT_MPI_HPP_

#include <mpi.h>

#include <string>

#include "client.hpp"

namespace lsmio {

/**
 * @class LSMIOClientMPI
 * @brief MPI implementation of the LSM IO client.
 *
 * This class provides an implementation of the LSMIOClient for
 * parallel operations using the Message Passing Interface (MPI).
 */
class LSMIOClientMPI : public LSMIOClient {
  private:
    /// Pointer to the MPI communicator.
    MPI_Comm *_mpiComm;

  protected:
    /**
     * @brief Implements a barrier mechanism using MPI_Barrier.
     */
    void _barrier() override;

    /**
     * @brief Receives data from all other MPI processes.
     * @param bufSizes Pointer to an integer array storing the sizes of the received buffers.
     * @return A pointer to the array of received data buffers.
     */
    char **_recvToBuffer(int *bufSizes) override;

  public:
    /**
     * @brief Constructor to initialize the MPI client.
     * @param comm Reference to the MPI communicator.
     */
    explicit LSMIOClientMPI(MPI_Comm &comm);

    /**
     * @brief Sends a command to a specific MPI rank.
     * @param rank The target MPI rank.
     * @param command The command to send.
     * @param key The key associated with the command.
     * @param value The value associated with the command.
     * @return True if the command was sent successfully, false otherwise.
     */
    bool sendCommand(int rank, const std::string &command, const std::string &key,
                     const std::string &value) override;

    /**
     * @brief Receives a command from a specific MPI rank.
     * @param rank The source MPI rank.
     * @param command Pointer to the received command string.
     * @param key Pointer to the received key string.
     * @param value Pointer to the received value string.
     * @return True if the command was received successfully, false otherwise.
     */
    bool recvCommand(int rank, std::string *command, std::string *key, std::string *value) override;
};

}  // namespace lsmio

#endif  // _LSMIO_CLIENT_MPI_HPP_
