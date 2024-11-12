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
#include <lsmio/manager/client/client_adios.hpp>
#include <thread>  // NOLINT [build/c++11]

namespace lsmio {

LSMIOClientAdios::LSMIOClientAdios(adios2::helper::Comm *comm) : LSMIOClient() {
    _comm = comm;
    _rank = (_comm) ? _comm->Rank() : 0;
    _size = (_comm) ? _comm->Size() : 1;

    LOG(INFO) << "LSMIOClientAdios::LSMIOClientAdios(): "
              << " rank/size: " << _rank << "/" << _size << std::endl;
}

void LSMIOClientAdios::_barrier() { _comm->Barrier("LSMIOClientAdios::_barrier"); }

char **LSMIOClientAdios::_recvToBuffer(int *bufSizes) {
    const std::string hint = "LSMIOClientADIO::_recvToBuffer";
    int recv_i, req_count;

    char **buffer = new char *[_size];
    for (recv_i = 0, req_count = 0; recv_i < _size; recv_i++) {
        if (recv_i == _rank) continue;

        MPI_Status status;
        int bSize = 0;
        MPI_Probe(recv_i, MPI_ANY_TAG, adios2::helper::CommAsMPI(*_comm), &status);
        MPI_Get_count(&status, MPI_CHAR, &bSize);

        LOG(INFO) << "LSMIOClientAdios::_recvToBuffer:"
                  << " rank: " << recv_i << " Alloc cmd size: " << bSize << std::endl;
        buffer[recv_i] = new char[bSize];
        bufSizes[recv_i] = bSize;
        _comm->Recv(buffer[recv_i], bSize, recv_i, 0, hint);
    }

    return buffer;
}

bool LSMIOClientAdios::sendCommand(int rank, const std::string &command, const std::string &key,
                                   const std::string &value) {
    const std::string hint = "LSMIOClientADIO::sendCommand";

    std::string bufMPI;
    serializeCmd(&bufMPI, command, key, value);

    _comm->Send(bufMPI.c_str(), bufMPI.size(), rank, 0, hint);

    LOG(INFO) << "LSMIOClientAdios::sendCommandMPI:"
              << " myRank: " << _rank << " command : " << command << " key : " << key
              << " size : " << value.size()
              << " value : " << (value.size() > 80 ? value.substr(0, 80) + "..." : value)
              << " to: " << rank << std::endl;

    return true;
}

bool LSMIOClientAdios::recvCommand(int rank, std::string *command, std::string *key,
                                   std::string *value) {
    const std::string hint = "LSMIOClientADIO::recvCommand";

    int sizeReceived[3];
    _comm->Recv(sizeReceived, 3, rank, 0, hint);

    char cmdBuffer[sizeReceived[0]];
    char keyBuffer[sizeReceived[1]];
    char valBuffer[sizeReceived[2]];

    _comm->Recv(cmdBuffer, sizeReceived[0], rank, 0, hint);
    _comm->Recv(cmdBuffer, sizeReceived[1], rank, 0, hint);
    _comm->Recv(cmdBuffer, sizeReceived[2], rank, 0, hint);

    command->assign(cmdBuffer, sizeReceived[0]);
    key->assign(keyBuffer, sizeReceived[1]);
    value->assign(valBuffer, sizeReceived[2]);

    LOG(INFO) << "LSMIOClientAdios::recvCommandMPI:"
              << " rank: " << rank << " command: " << *command << " key: " << *key
              << " value: " << *value << std::endl;

    return true;
}

}  // namespace lsmio
