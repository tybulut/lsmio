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

#include <gtest/gtest.h>
#include <mpi.h>

#include <iostream>
#include <lsmio/manager/manager.hpp>
#include <stdexcept>
#include <vector>

#include "test_mpi_utils.hpp"

#if ADIOS2_USE_MPI
#else
#error "ERROR: ADIOS2 does not have MPI (ADIOS2_USE_MPI=0)"
#endif

namespace lsmioTest {

const std::string TEST_DIR_MGR = "";

struct managerMPITests : public ::testing::TestWithParam<std::tuple<bool, MPIWorld>> {};

std::string getDBFile(const std::string &prefix, const bool &useWorld, const int &worldRank) {
    std::string m_file = "test-mpi-mgr-" + prefix;
    if (!useWorld) m_file += "-" + std::to_string(worldRank);
    m_file += ".db";
    return m_file;
}

TEST_P(managerMPITests, Flush) {
    bool useWorld = std::get<0>(GetParam());
    MPIWorld worldSize = std::get<1>(GetParam());
    MPI_Barrier(MPI_COMM_WORLD);

    int numProcesses, worldRank;
    MPI_Comm_size(MPI_COMM_WORLD, &numProcesses);
    MPI_Comm_rank(MPI_COMM_WORLD, &worldRank);

    LOG(INFO) << "lsmioTest::ManagerMPI: :"
              << " number: " << worldRank << " out of: " << numProcesses << std::endl;

    std::string prefix = genPreFix(useWorld, worldSize);
    std::string dbFile = getDBFile(prefix, useWorld, worldRank);
    lsmio::LSMIOManager *lm = nullptr;

    if (useWorld) {
        lsmio::gConfigLSMIO.mpiAggType = translateAggType(worldSize);
        lm = new lsmio::LSMIOManager(dbFile, TEST_DIR_MGR, true, MPI_COMM_WORLD);
    } else
        lm = new lsmio::LSMIOManager(dbFile, TEST_DIR_MGR, true, MPI_COMM_SELF);

    bool success = true;
    std::string value;

    std::string key1 = "serdar";
    std::string key2 = "bulut";
    std::string value1 = "alpino";
    std::string value2 = "teomos";

    success = lm->put(key1, value1);
    EXPECT_EQ(success, true);

    success = lm->put(key2, value2.c_str(), value2.length());
    EXPECT_EQ(success, true);

    success = lm->writeBarrier();
    EXPECT_EQ(success, true);

    success = lm->get(key1, &value);
    EXPECT_EQ(success, true);

    LOG(INFO) << "Test value for key1: " << value << std::endl;
    EXPECT_EQ(value, value1);

    success = lm->get(key2, &value);
    EXPECT_EQ(success, true);

    LOG(INFO) << "Test value for key2: " << value << std::endl;
    EXPECT_EQ(value, value2);

    success = lm->del(key1);
    EXPECT_EQ(success, true);

    success = lm->del(key2);
    EXPECT_EQ(success, true);

    delete lm;
}

INSTANTIATE_TEST_SUITE_P(lsmioTest, managerMPITests,
                         ::testing::Values(std::make_tuple(false, MPIWorld::Shared),
                                           std::make_tuple(true, MPIWorld::Shared),
                                           std::make_tuple(true, MPIWorld::Entire),
                                           std::make_tuple(true, MPIWorld::EntireSerial),
                                           std::make_tuple(true, MPIWorld::Split)));

}  // namespace lsmioTest
