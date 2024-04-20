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

#include <lsmio/lsmio.hpp>

#include "test_mpi_utils.hpp"


namespace lsmioTest {

struct MPITests: public ::testing::TestWithParam<MPIWorld> {
};


TEST_P(MPITests, PassTokenAsync) {
  MPIWorld worldSize = GetParam();
  MPI_Comm comm = getMPIComm(worldSize);
  MPI_Barrier(comm);

  int numProcesses, processRank;
  MPI_Comm_size(comm, &numProcesses);
  MPI_Comm_rank(comm, &processRank);

  int send_token = 1337;
  int recv_token;
  MPI_Request reqs[2];
  MPI_Status statuses[2];

  MPI_Isend(&send_token, 1, MPI_INT, (processRank + 1) % numProcesses, 0, comm, &reqs[0]);
  LOG(INFO) << "testPassToken:"
            << " rank: " << processRank
            << " sent : " << send_token
            << " to: " << (processRank + 1) % numProcesses << std::endl;

  MPI_Irecv(&recv_token, 1, MPI_INT, (processRank - 1) % numProcesses, 0, comm, &reqs[1]);
  MPI_Waitall(2, reqs, statuses) ; 

  LOG(INFO) << "testPassToken:"
            << " rank: " << processRank
            << " received : " << recv_token
            << " from: " << (processRank + 1) % numProcesses << std::endl;

  EXPECT_EQ(send_token, recv_token);
}

TEST_P(MPITests, PassTokenSync) {
  MPIWorld worldSize = GetParam();
  MPI_Comm comm = getMPIComm(worldSize);
  MPI_Barrier(comm);

  int numProcesses, processRank;
  MPI_Comm_size(comm, &numProcesses);
  MPI_Comm_rank(comm, &processRank);

  int send_token = 1337;
  int recv_token;


  if (worldSize == MPIWorld::Self || numProcesses == 1) {
    MPI_Request req;
    MPI_Status status;

    MPI_Irecv(&recv_token, 1, MPI_INT, (processRank - 1) % numProcesses, 0, comm, &req);
    MPI_Send(&send_token, 1, MPI_INT, (processRank + 1) % numProcesses, 0, comm);

    MPI_Wait(&req, &status);
    EXPECT_EQ(send_token, recv_token);
    return;
  }

  if (processRank != 0) {
    MPI_Recv(&recv_token, 1, MPI_INT, (processRank - 1) % numProcesses, 0, comm, MPI_STATUS_IGNORE);
    LOG(INFO) << "test_pass_token:"
            << " rank: " << processRank
            << " received : " << recv_token
            << " from: " << (processRank - 1) << std::endl;
  }

  MPI_Send(&send_token, 1, MPI_INT, (processRank + 1) % numProcesses, 0, comm);
  if (processRank == 0) {
    MPI_Recv(&recv_token, 1, MPI_INT, (numProcesses - 1) % numProcesses, 0, comm, MPI_STATUS_IGNORE);
    LOG(INFO) << "test_pass_token:"
            << " rank: " << processRank
            << " received : " << recv_token
            << " from: " << (numProcesses - 1) << std::endl;
  }

  EXPECT_EQ(send_token, recv_token);
}


TEST_P(MPITests, AggregateTokens) {
  MPIWorld worldSize = GetParam();
  MPI_Comm comm = getMPIComm(worldSize);
  MPI_Barrier(comm);

  int numProcesses, processRank;
  MPI_Comm_size(comm, &numProcesses);
  MPI_Comm_rank(comm, &processRank);

  int send_token = 10000 + processRank;
  int aggregatorRank = 0;
  MPI_Request reqs[numProcesses];
  MPI_Status statuses[numProcesses];

  if (processRank != aggregatorRank) {
    MPI_Isend(&send_token, 1, MPI_INT, aggregatorRank, 0, comm, &reqs[processRank]);
    LOG(INFO) << "test_aggregate_tokens:"
            << " rank: " << processRank
            << " sent : " << send_token
            << " to: " << aggregatorRank << std::endl;
    MPI_Wait(&reqs[processRank], &statuses[processRank]) ; 
    return;
  }

  int recv_i, req_count;
  int token_received[numProcesses];
  for(recv_i =0, req_count=0; recv_i < numProcesses; recv_i++) {
    if (recv_i == aggregatorRank) continue;

    MPI_Irecv(&token_received[recv_i], 1, MPI_INT, recv_i, 0, comm, &reqs[req_count++]);
  }

  LOG(INFO) << "test_aggregate_tokens: Waiting for all."  << std::endl;
  MPI_Waitall(req_count, reqs, statuses); 

  for(recv_i =0; recv_i < numProcesses; recv_i++) {
    if (recv_i == aggregatorRank) continue;

    EXPECT_EQ(token_received[recv_i], (send_token + recv_i)) << "test_aggregate_tokens:"
              << " rank: " << processRank
              << " WRONGLY received : " << token_received[recv_i]
              << " from: " << std::to_string(recv_i);
  }
}


TEST_P(MPITests, AggregateBuffer) {
  MPIWorld worldSize = GetParam();
  MPI_Comm comm = getMPIComm(worldSize);
  MPI_Barrier(comm);

  int numProcesses, processRank;
  MPI_Comm_size(comm, &numProcesses);
  MPI_Comm_rank(comm, &processRank);

  std::string tokenString = "HelloWorld";
  int aggregatorRank = 0;
  MPI_Request reqs[numProcesses];
  MPI_Status statuses[numProcesses];

  if (processRank != aggregatorRank) {
    MPI_Isend(tokenString.c_str(), tokenString.size(), MPI_CHAR,
              aggregatorRank, 0, comm, &reqs[processRank]);
    LOG(INFO) << "test_aggregate_buffer:"
            << " rank: " << processRank
            << " sent : " << tokenString
            << " to: " << aggregatorRank << std::endl;
    MPI_Wait(&reqs[processRank], &statuses[processRank]) ; 
    return;
  }

  int recv_i, req_count;
  char **bufReceived = new char *[numProcesses];
  for(recv_i =0, req_count=0; recv_i < numProcesses; recv_i++) {
    if (recv_i == aggregatorRank) continue;

    bufReceived[recv_i] = new char [tokenString.size()];
    MPI_Irecv(bufReceived[recv_i], tokenString.size(), MPI_CHAR,
              recv_i, 0, comm, &reqs[req_count++]);
  }

  LOG(INFO) << "test_aggregate_buffer: Waiting for all."  << std::endl;
  MPI_Waitall(req_count, reqs, statuses); 

  for(recv_i =0; recv_i < numProcesses; recv_i++) {
    if (recv_i == aggregatorRank) continue;

    std::string str_received(bufReceived[recv_i], tokenString.size());
    EXPECT_EQ(str_received, tokenString) << "test_aggregate_buffer:"
              << " rank: " << processRank
              << " WRONGLY received : " << str_received
              << " from: " << recv_i;

    delete bufReceived[recv_i];
  }

  delete bufReceived;
}


TEST_P(MPITests, ProbeSize) {
  MPIWorld worldSize = GetParam();
  MPI_Comm comm = getMPIComm(worldSize);
  MPI_Barrier(comm);

  int numProcesses, processRank;
  MPI_Comm_size(comm, &numProcesses);
  MPI_Comm_rank(comm, &processRank);

  std::string tokenString = "HelloWorld";
  int aggregatorRank = 0;
  MPI_Request reqs[numProcesses];
  MPI_Status statuses[numProcesses];

  if (processRank != aggregatorRank) {
    MPI_Isend(tokenString.c_str(), tokenString.size(), MPI_CHAR,
              aggregatorRank, 0, comm, &reqs[processRank]);
    LOG(INFO) << "test_aggregate_buffer:"
            << " rank: " << processRank
            << " sent : " << tokenString
            << " to: " << aggregatorRank << std::endl;
    MPI_Wait(&reqs[processRank], &statuses[processRank]) ; 
    return;
  }

  int recv_i, req_count;
  char **bufReceived = new char *[numProcesses];
  for(recv_i =0, req_count=0; recv_i < numProcesses; recv_i++) {
    if (recv_i == aggregatorRank) continue;

    int bSize = 0;
    MPI_Probe(recv_i, MPI_ANY_TAG, comm, &statuses[recv_i]);
    MPI_Get_count(&statuses[recv_i], MPI_CHAR, &bSize);

    LOG(INFO) << "LSMIOClientMPI::_recvToBuffer:"
              << " rank: " << recv_i
              << " received size: " << bSize << std::endl;

    EXPECT_EQ(tokenString.size(), bSize) << "MPITests::ProbeSize: Wrong size:"
              << " rank: " << processRank
              << " sent : " << tokenString.size()
              << " received : " << bSize;

    bufReceived[recv_i] = new char [bSize+1];
    MPI_Irecv(bufReceived[recv_i], bSize, MPI_CHAR, recv_i, 0, comm, &reqs[req_count++]);
    bufReceived[recv_i][bSize] = '\0';
  }

  LOG(INFO) << "test_aggregate_buffer: Waiting for all."  << std::endl;
  MPI_Waitall(req_count, reqs, statuses); 

  for(recv_i =0; recv_i < numProcesses; recv_i++) {
    if (recv_i == aggregatorRank) continue;

    std::string str_received(bufReceived[recv_i], tokenString.size());
    EXPECT_EQ(str_received, tokenString) << "MPITests::ProbeSize: :"
              << " rank: " << processRank
              << " WRONGLY received : " << str_received
              << " from: " << recv_i;

    delete bufReceived[recv_i];
  }

  delete bufReceived;
}


TEST_P(MPITests, AggregateString) {
  MPIWorld worldSize = GetParam();
  MPI_Comm comm = getMPIComm(worldSize);
  MPI_Barrier(comm);

  int numProcesses, processRank;
  MPI_Comm_size(comm, &numProcesses);
  MPI_Comm_rank(comm, &processRank);

  std::string tokenString = generateRankString(processRank);
  int tokenSize = tokenString.size();
  int aggregatorRank = 0;
  MPI_Request reqs[numProcesses];
  MPI_Status statuses[numProcesses];

  if (processRank != aggregatorRank) {
    MPI_Isend(&tokenSize, 1, MPI_INT, aggregatorRank, 0, comm, &reqs[processRank]);
    MPI_Isend(tokenString.c_str(), tokenString.size(), MPI_CHAR,
              aggregatorRank, 0, comm, &reqs[processRank]);
    LOG(INFO) << "test_aggregate_string:"
            << " rank: " << processRank
            << " sent : " << tokenString
            << " to: " << aggregatorRank << std::endl;
    MPI_Wait(&reqs[processRank], &statuses[processRank]) ; 
    return;
  }

  int recv_i, req_count;
  int sizeReceived[numProcesses];
  for(recv_i =0, req_count=0; recv_i < numProcesses; recv_i++) {
    if (recv_i == aggregatorRank) continue;

    MPI_Irecv(&sizeReceived[recv_i], 1, MPI_INT, recv_i, 0, comm, &reqs[req_count++]);
  }

  LOG(INFO) << "test_aggregate_string: Waiting for all sizes."  << std::endl;
  MPI_Waitall(req_count, reqs, statuses); 

  char **bufReceived = new char *[numProcesses];
  for(recv_i =0, req_count=0; recv_i < numProcesses; recv_i++) {
    if (recv_i == aggregatorRank) continue;

    bufReceived[recv_i] = new char [sizeReceived[recv_i]];
    MPI_Irecv(bufReceived[recv_i], sizeReceived[recv_i], MPI_CHAR,
              recv_i, 0, comm, &reqs[req_count++]);
  }

  LOG(INFO) << "test_aggregate_string: Waiting for all buffers."  << std::endl;
  MPI_Waitall(req_count, reqs, statuses); 

  for(recv_i =0; recv_i < numProcesses; recv_i++) {
    if (recv_i == aggregatorRank) continue;

    std::string str_received(bufReceived[recv_i], sizeReceived[recv_i]);
    EXPECT_EQ(str_received, generateRankString(recv_i)) << "test_aggregate_string:"
              << " rank: " << processRank
              << " WRONGLY received : " << str_received
              << " from: " << recv_i;

    delete bufReceived[recv_i];
  }

  delete bufReceived;
}


INSTANTIATE_TEST_CASE_P(
  lsmioTest,
  MPITests,
  ::testing::Values(
    MPIWorld::Shared,
    MPIWorld::Entire,
    MPIWorld::Self,
    MPIWorld::Split
  )
);

}
