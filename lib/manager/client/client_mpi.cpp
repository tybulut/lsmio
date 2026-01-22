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

#include <chrono>  // NOLINT [build/c++11]
#include <iostream>
#include <lsmio/manager/client/client_mpi.hpp>
#include <thread>  // NOLINT [build/c++11]

#define MPI_COMM_TO_STR(cLevel)                          \
    (cLevel == MPI_IDENT                                 \
         ? "MPI_IDENT"                                   \
         : (cLevel == MPI_CONGRUENT                      \
                ? "MPI_CONGRUENT"                        \
                : (cLevel == MPI_SIMILAR ? "MPI_SIMILAR" \
                                         : (cLevel == MPI_UNEQUAL ? "MPI_UNEQUAL" : "UNKNOWN"))))

namespace lsmio {

LSMIOClientMPI::LSMIOClientMPI(MPI_Comm &comm) : LSMIOClient() {
    _mpiComm = &comm;
    MPI_Comm_size(*_mpiComm, &_size);
    MPI_Comm_rank(*_mpiComm, &_rank);

    int result;
    MPI_Comm_compare(*_mpiComm, MPI_COMM_WORLD, &result);

    LOG(INFO) << "LSMIOClientMPI::LSMIOClientMPI(): "
              << " _mpiComm:world: " << MPI_COMM_TO_STR(result) << " rank/size: " << _rank << "/"
              << _size << std::endl;
}

void LSMIOClientMPI::_barrier() {
    MPI_Barrier(*_mpiComm);
}

char **LSMIOClientMPI::_recvToBuffer(int *bufSizes) {
    MPI_Request reqs[_size - 1];
    MPI_Status statuses[_size - 1];
    int recv_i, req_count;

    char **buffer = new char *[_size];
    for (recv_i = 0, req_count = 0; recv_i < _size; recv_i++) {
        if (recv_i == _rank) continue;

        int bSize = 0;
        MPI_Probe(recv_i, MPI_ANY_TAG, *_mpiComm, &statuses[req_count]);
        MPI_Get_count(&statuses[req_count], MPI_CHAR, &bSize);

        LOG(INFO) << "LSMIOClientMPI::_recvToBuffer:"
                  << " rank: " << recv_i << " alloc size: " << bSize << std::endl;

        buffer[recv_i] = new char[bSize];
        bufSizes[recv_i] = bSize;
        MPI_Irecv(buffer[recv_i], bSize, MPI_CHAR, recv_i, 0, *_mpiComm, &reqs[req_count++]);
    }

    LOG(INFO) << "LSMIOClientMPI::_recvToBuffer: Waiting for buffers for ALL." << std::endl;
    MPI_Waitall(req_count, reqs, statuses);

    return buffer;
}

bool LSMIOClientMPI::sendCommand(int rank, const std::string &command, const std::string &key,
                                 const std::string &value) {
    MPI_Request reqs[4];
    MPI_Status statuses[4];

    std::string bufMPI;
    serializeCmd(&bufMPI, command, key, value);
    MPI_Send(bufMPI.c_str(), bufMPI.size(), MPI_CHAR, rank, 0, *_mpiComm);

    LOG(INFO) << "LSMIOClientMPI::sendCommandMPI:"
              << " my rank: " << _rank << " command : " << command << " key : " << key
              << " size : " << value.size()
              << " value : " << (value.size() > 80 ? value.substr(0, 80) + "..." : value)
              << " to: " << rank << std::endl;

    return true;
}

bool LSMIOClientMPI::recvCommand(int rank, std::string *command, std::string *key,
                                 std::string *value) {
    MPI_Status status;

    int bSize = 0;
    MPI_Probe(rank, MPI_ANY_TAG, *_mpiComm, &status);
    MPI_Get_count(&status, MPI_CHAR, &bSize);

    char *bufReceived = new char[bSize];
    MPI_Recv(bufReceived, bSize, MPI_CHAR, rank, 0, *_mpiComm, &status);

    deSerializeCmd(bufReceived, bSize, command, key, value);

    LOG(INFO) << "LSMIOClientMPI::recvCommandMPI:"
              << " rank: " << rank << " command: " << *command << " key: " << *key
              << " size: " << value->size()
              << " value: " << (value->size() > 80 ? (*value).substr(0, 80) + "..." : *value)
              << std::endl;

    return true;
}

}  // namespace lsmio
