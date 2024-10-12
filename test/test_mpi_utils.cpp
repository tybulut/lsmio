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

MPI_Comm getMPIComm(MPIWorld worldSize) {
  MPI_Comm comm;
  std::string commType;

  int numProcesses, processRank;
  MPI_Comm_size(MPI_COMM_WORLD, &numProcesses);
  MPI_Comm_rank(MPI_COMM_WORLD, &processRank);

  if (worldSize == MPIWorld::Shared) {
    commType = "mpiSharedMem";
    int key = 0;
    MPI_Comm_split_type(MPI_COMM_WORLD, MPI_COMM_TYPE_SHARED, key, MPI_INFO_NULL, &comm);
  }
  else if (worldSize == MPIWorld::Entire) {
    commType = "mpiWorld";
    comm = MPI_COMM_WORLD;
  }
  else if (worldSize == MPIWorld::Self) {
    commType = "mpiSelf";
    comm = MPI_COMM_SELF;
  }
  else {
    commType = "mpiSplit";
    int splitSize = processRank / 2;
    MPI_Comm_split(MPI_COMM_WORLD, splitSize, processRank, &comm);
  }

  int nameLen;
  char processName[MPI_MAX_PROCESSOR_NAME];
  MPI_Get_processor_name(processName, &nameLen);
  std::string pName(processName, nameLen);

  LOG(INFO) << "_getMPIComm:"
            << " comm: " << commType
            << " process: " << processName
            << " number: " << processRank
            << " out of: " << numProcesses << std::endl;

  return comm;
}


lsmio::MPIAggType translateAggType(MPIWorld worldSize) {
  if (worldSize == MPIWorld::Shared) {
    return lsmio::MPIAggType::Shared;
  }
  else if (worldSize == MPIWorld::Entire) {
    return lsmio::MPIAggType::Entire;
  }
  else if (worldSize == MPIWorld::EntireSerial) {
    return lsmio::MPIAggType::EntireSerial;
  }
  else { // if (worldSize == MPIWorld::Split) {
    return lsmio::MPIAggType::Split;
  }
}


std::string generateRankString(int processRank) {
  std::string returnVal = "HelloWorld";
  for(int i=0; i < processRank; i++) {
    returnVal += ":" + std::to_string(i);
  }

  return returnVal;
}


std::string genPreFix(const bool &valBool, const MPIWorld &valWorld) {
  return mpiWorldToString(valWorld) + ":" + std::to_string(valBool);
}


std::string mpiWorldToString(const MPIWorld& worldSize) {
  if (worldSize == MPIWorld::Shared) {
    return "mpiSharedMem";
  }
  else if (worldSize == MPIWorld::Entire) {
    return "mpiWorld";
  }
  else if (worldSize == MPIWorld::EntireSerial) {
    return "mpiWorldSerial";
  }
  else if (worldSize == MPIWorld::Self) {
    return "mpiSelf";
  }
  else if (worldSize == MPIWorld::Split) {
    return "mpiSplit";
  }
  else {
    return "(unknown)";
  }
}


void PrintTo(const MPIWorld& worldSize, std::ostream* os) {
  *os << mpiWorldToString(worldSize);
}

}


int main(int argc, char **argv) {
  lsmio::initLSMIODebug(argv[0]);

  bool gtestListTests = false;
  for(int i=0; i < argc; i++) {
    if (! strcmp(argv[i], "--gtest_list_tests")) {
      gtestListTests = true;
      break;
    }
  }

  int errorCode;
  if (gtestListTests) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
  }

  int provided;
  MPI_Init_thread(&argc, &argv, MPI_THREAD_MULTIPLE, &provided);

  int numProcesses;
  MPI_Comm_size(MPI_COMM_WORLD, &numProcesses);

  if (numProcesses > 1) {
    ::testing::InitGoogleTest(&argc, argv);
    errorCode = RUN_ALL_TESTS();
  }
  else {
    LOG(ERROR) << "lsmioTestMPI: The MPI process size should be > 1." << std::endl;
    std::copy(argv+1, argv+argc, std::ostream_iterator<const char*>(LOG(ERROR), "\n"));
    errorCode = 1;
  }

  MPI_Finalize();

  return errorCode;
}
