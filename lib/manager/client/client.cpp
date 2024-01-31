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

#include <mpi.h>

#include <chrono>  // NOLINT [build/c++11]
#include <iostream>
#include <map>
#include <thread>  // NOLINT [build/c++11]

#include <boost/circular_buffer.hpp>

#include <lsmio/manager/client/client.hpp>


/**
 * @brief Converts an MPI thread level to its string representation.
 */
#define MPI_THREAD_TO_STR(tLevel)  \
          (tLevel == MPI_THREAD_SINGLE ? "MPI_THREAD_SINGLE" : \
          (tLevel == MPI_THREAD_FUNNELED ? "MPI_THREAD_FUNNELED" : \
          (tLevel == MPI_THREAD_SERIALIZED ? "MPI_THREAD_SERIALIZED" : \
          (tLevel == MPI_THREAD_MULTIPLE ? "MPI_THREAD_MULTIPLE" : \
          "UNKNOWN"))))


namespace lsmio {


const std::string KV_CMD::GET = "get";
const std::string KV_CMD::PUT = "put";
const std::string KV_CMD::DEL = "del";
const std::string KV_CMD::APPEND = "append";
const std::string KV_CMD::READ_BARRIER = "rBarrier";
const std::string KV_CMD::WRITE_BARRIER = "wBarrier";

const std::string KV_CMD_RETURN::GET = "getBack";
const std::string KV_CMD_RETURN::READ_BARRIER = "rBarrierBack";
const std::string KV_CMD_RETURN::WRITE_BARRIER = "wBarrierBack";


LSMIOClient::LSMIOClient() {
  _size = 1;
  _rank = 0;
}


LSMIOClient::~LSMIOClient() {
  LOG(INFO) << "LSMIOClient::~LSMIOClient(): " << std::endl;
  if (_loopRunning) {
    LOG(INFO) << "LSMIOClient::~LSMIOClient(): Barrier reached. Cleaning up server..." << std::endl;
  } else {
    LOG(INFO) << "LSMIOClient::~LSMIOClient(): Barrier reached. Cleaning up client..." << std::endl;
  }
}


void LSMIOClient::helperThread(LSMIOClient *ctx, LSMIOClientCallback func,
                               LSMIOManager *lm, std::promise<void> threadBarrier) {
  LOG(INFO) << "LSMIOClient::helperThread: Threading..." << std::endl;
  threadBarrier.set_value();
  LOG(INFO) << "LSMIOClient::helperThread: Threads are synchronized." << std::endl;

  try {
    (ctx->_waitForCommand)(func, lm);
  }
  catch (std::exception &e) {
    LOG(ERROR) << "LSMIOClient::helperThread: Exception: " << e.what() << "\n";
    exit(1);
  }
}


bool LSMIOClient::checkThreadSupport() {
  int provided, is_main_thread;
  MPI_Query_thread(&provided);
  MPI_Is_thread_main(&is_main_thread);
  LOG(INFO) << "LSMIOClient::checkThreadSupport: Processes started:"
            << " thread support: " << MPI_THREAD_TO_STR(provided)
            << " thread id: " << (is_main_thread ? "main" : "not main") << std::endl;

  return (provided != MPI_THREAD_MULTIPLE);
}


void LSMIOClient::serializeCmd(std::string *buf, const std::string& command,
                  const std::string& key, const std::string& value) {
  buf->append(command + _COL_SEPARATOR_STR + key + _COL_SEPARATOR_STR + value);
  LOG(INFO) << "LSMIOClient::serializeCmd: "
            << " size : " << buf->size()
            << " buf : " << (buf->size() > 80 ? buf->substr(0, 80) + "..." : *buf)
            << std::endl;
}


// "cmd;key;value"
// "0123456789012"
void LSMIOClient::deSerializeCmd(const char *buf, const int& len, std::string *command,
                  std::string *key, std::string *value) {
  int cmdSize = strchr(buf, _COL_SEPARATOR_CHAR) - buf;
  command->assign(buf, cmdSize);

  cmdSize += 1;
  int keySize = strchr(buf+cmdSize, _COL_SEPARATOR_CHAR) - (buf+cmdSize);
  key->assign(buf+cmdSize, keySize);

  keySize += 1;
  int valSize = len - (keySize + cmdSize);
  value->assign(buf+cmdSize+keySize, valSize);

  LOG(INFO) << "LSMIOClient::deSerializeCmd:"
            << " my rank: " << _rank
            << " command : " << *command
            << " key : " << *key
            << " size : " << value->size()
            << " value : " << (value->size() > 80 ? value->substr(0, 80) + "..." : *value)
            << std::endl;
}


bool LSMIOClient::stopCollectiveIOServer() {
  std::thread::id main_thread_id = std::this_thread::get_id();
  LOG(INFO) << "LSMIOClient::stopCollectiveIOServer: waiting for the server thread to join..." << std::endl;
  LOG(INFO) << "LSMIOClient::stopCollectiveIOServer: "
            << " main thread: " << std::this_thread::get_id()
            << " server thread: " << _serverThread.get_id() << std::endl;

  _serverThread.join();
  LOG(INFO) << "LSMIOClient::stopCollectiveIOServer: the server thread has joined." << std::endl;

  _barrier();  // B99: server/client: End Process
  LOG(INFO) << "LSMIOClient::stopCollectiveIOServer: Barrier reached." << std::endl;
  return true;
}


bool LSMIOClient::stopCollectiveIOClient(int rank) {
  LOG(INFO) << "LSMIOClient::stopCollectiveIOClient: aggregation rank: " << rank << std::endl;
  std::string retValue;
  sendCommand(rank, _EOL_COMMAND, KV_DUMMY, retValue);
  LOG(INFO) << "LSMIOClient::stopCollectiveIOClient: sent for _EOL_COMMAND: " << std::endl;
  _barrier();  // B99: server/client: End Process
  LOG(INFO) << "LSMIOClient::stopCollectiveIOClient(): Barrier reached. Cleaning up client..." << std::endl;
  return true;
}


bool LSMIOClient::startCollectiveIOClient() {
  LOG(INFO) << "LSMIOClient::startCollectiveIOClient: ..." << std::endl;
  _barrier();  // B99: server/client: End Process
  LOG(INFO) << "LSMIOClient::startCollectiveIOClient: Barrier reached." << std::endl;

  return true;
}


bool LSMIOClient::startCollectiveIOServer(LSMIOClientCallback func, LSMIOManager *lm) {
  LOG(INFO) << "LSMIOClient::startCollectiveIOServer: Starting..." << std::endl;

  std::promise<void> threadBarrier;
  std::future<void> barrierFuture = threadBarrier.get_future();
  std::thread mpiThread(&LSMIOClient::helperThread, this, func, lm, std::move(threadBarrier));
  _serverThread = std::move(mpiThread);

  LOG(INFO) << "LSMIOClient::startCollectiveIOServer: Waiting for threads to start." << std::endl;
  barrierFuture.wait();
  LOG(INFO) << "LSMIOClient::startCollectiveIOServer: Threads synchronized." << std::endl;

  _barrier();  // B01: server/client
  LOG(INFO) << "LSMIOClient::startCollectiveIOServer: Barrier reached." << std::endl;

  LOG(INFO) << "LSMIOClient::startCollectiveIOServer: Startup completed." << std::endl;
  return true;
}


void LSMIOClient::_cancelWaitForCommand() {
  LOG(INFO) << "LSMIOClient::_cancelWaitForCommand: " << _loopRunning  << std::endl;
  _loopRunning = 0;
  _serverThread.join();
}


void LSMIOClient::_waitForCommand(LSMIOClientCallback func, LSMIOManager *lm) {
  unsigned int loopCounter = 0;
  int eolRanks[_size] = {};

  LOG(INFO) << "LSMIOClient::_waitForCommand: Starting..." << std::endl;

  _loopRunning = 1;
  while (true) {
    bool allClientsShutDown = true;
    int recv_i, req_count;

    for (recv_i = 0; recv_i < _size; recv_i++) {
      if (recv_i == _rank) continue;
      if (eolRanks[recv_i] != 1) {
        allClientsShutDown = false;
        break;
      }
    }

    if (allClientsShutDown) {
      LOG(INFO) << "LSMIOClient::_waitForCommand: All clients shut down." << std::endl;
      break;
    }

    LOG(INFO) << "LSMIOClient::_waitForCommand: Waiting for buffers to be filled..." << std::endl;
    int *bufSizes = new int[_size];
    char **recvBuf = _recvToBuffer(bufSizes);

    for (recv_i = 0, req_count=0; recv_i < _size; recv_i++) {
      if (recv_i == _rank) continue;

      std::string str_cmd, str_key, str_val;
      deSerializeCmd(recvBuf[recv_i], bufSizes[recv_i], &str_cmd, &str_key, &str_val);

      LOG(INFO) << "LSMIOClient::_waitForCommand: "
                << " rank: " << recv_i
                << " cmd: " << str_cmd
                << " key: " << str_key
                << " val.size: " << str_val.size()
                << " val: " << (str_val.size() > 80 ? str_val.substr(0, 80) + "..." : str_val)
                << std::endl;

      delete recvBuf[recv_i];

      if (str_cmd == _EOL_COMMAND) {
        eolRanks[recv_i] = 1;
        continue;
      }

      // callback time
      std::string retValue;
      (lm->*func)(recv_i, str_cmd, str_key, &retValue, str_val);

      if (str_cmd == KV_CMD::GET) {
        sendCommand(recv_i, KV_CMD_RETURN::GET, str_key, retValue);
      } else if (str_cmd == KV_CMD::READ_BARRIER) {
        sendCommand(recv_i, KV_CMD_RETURN::READ_BARRIER, str_key, retValue);
      } else if (str_cmd == KV_CMD::WRITE_BARRIER) {
        sendCommand(recv_i, KV_CMD_RETURN::WRITE_BARRIER, str_key, retValue);
      }
    }

    delete recvBuf;

    LOG(INFO) << "LSMIOClient::_waitForCommand: Completed loop: " << loopCounter++ << std::endl;
  }

  _loopRunning = 0;
  LOG(INFO) << "LSMIOClient::_waitForCommand: Complete..." << std::endl;
}


}  // namespace lsmio
