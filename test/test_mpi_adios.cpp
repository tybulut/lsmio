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

#include <adios2.h>
#include <mpi.h>

#include <iostream>
#include <lsmio/lsmio.hpp>
#include <stdexcept>
#include <vector>

#include "test_mpi_utils.hpp"

#if ADIOS2_USE_MPI
#else
#error "ERROR: ADIOS2 does not have MPI (ADIOS2_USE_MPI=0)"
#endif

namespace lsmioTest {

const std::string TEST_KEY = "Greeting";
const std::string TEST_VALUE = "Test Plugin Greeting";

class adiosMPITests : public ::testing::TestWithParam<std::tuple<AdiosEngine, MPIWorld>> {
  protected:
    // engine:
    // - should be false when the return value is used by adios.writer
    // - should be set correctly when called by genAdiosParams for the plugin to work correctly
    std::string getAdiosFile(const AdiosEngine &engine, const MPIWorld &worldSize,
                             const int &worldRank) {
        std::string m_file = "test-mpi";
        m_file += (engine == AdiosEngine::Plugin) ? "-plugin" : "-adios";
        m_file += "-" + genPreFix((engine == AdiosEngine::Plugin), worldSize);
        if (worldSize == MPIWorld::Self) m_file += "-" + std::to_string(worldRank);
        m_file += (engine == AdiosEngine::Plugin) ? ".db" : ".bp";
        return m_file;
    }

    adios2::Params genAdiosParams(const AdiosEngine &engine, const MPIWorld &worldSize,
                                  const int &worldRank) {
        adios2::Params params;

        if (engine == AdiosEngine::Plugin) {
            params["PluginName"] = "LSMIOPlugin";
            params["PluginLibrary"] = "liblsmio_adios";
            params["FileName"] = getAdiosFile(engine, worldSize, worldRank);
        }

        if (worldSize != MPIWorld::Self) {
            if (worldSize == MPIWorld::Entire)
                params["AggregationType"] = "EveryoneWrites";
            else if (worldSize == MPIWorld::Split) {
                params["AggregationType"] = "EveryoneWrites";
                params["AggregatorRatio"] = "2";
            } else if (worldSize == MPIWorld::EntireSerial)
                params["AggregationType"] = "EveryoneWritesSerial";
            else  // (worldSize == MPIWorld::Shared)
                params["AggregationType"] = "TwoLevelShm";

            LOG(INFO) << "genAdiosParams: param: AggregationType: " << params["AggregationType"]
                      << std::endl;
        } else {
            LOG(INFO) << "genAdiosParams: param: AggregationType: MPIWorld::Self" << std::endl;
        }

        return params;
    }

    std::string adiosWriter(adios2::ADIOS &adios, const AdiosEngine &engine,
                            const MPIWorld &worldSize, const int &worldRank) {
        const std::string m_io_name = "test-mpi-adios-writer";
        const std::string m_file = getAdiosFile(AdiosEngine::BP5, worldSize, worldRank);
        const std::string k_greeting = TEST_KEY + ":" + std::to_string(worldRank);
        const std::string v_greeting = TEST_VALUE + ": " + std::to_string(worldRank);

        LOG(INFO) << "adiosWriter 00: rank: " << worldRank << " m_io_name: " << m_io_name
                  << " m_file: " << m_file << " k_greeting: " << k_greeting << std::endl;

        adios2::IO io = adios.DeclareIO(m_io_name);
        if (engine == AdiosEngine::Plugin) {
            io.SetEngine("Plugin");
        }
        io.SetParameters(genAdiosParams(engine, worldSize, worldRank));

        adios2::Variable<std::string> varGreeting = io.DefineVariable<std::string>(k_greeting);

        adios2::Engine writer = io.Open(m_file, adios2::Mode::Write);
        writer.BeginStep();

        writer.Put(varGreeting, v_greeting);
        writer.PerformPuts();

        writer.EndStep();
        writer.Close();

        return v_greeting;
    }

    std::string adiosReader(adios2::ADIOS &adios, const AdiosEngine &engine,
                            const MPIWorld &worldSize, const int &worldRank) {
        const std::string m_io_name = "test-mpi-adios-read";
        const std::string m_file = getAdiosFile(AdiosEngine::BP5, worldSize, worldRank);
        const std::string k_greeting = TEST_KEY + ":" + std::to_string(worldRank);
        std::string v_greeting;

        LOG(INFO) << "adiosReader 00: rank: " << worldRank << " m_io_name: " << m_io_name
                  << " m_file: " << m_file << " k_greeting: " << k_greeting << std::endl;

        adios2::IO io = adios.DeclareIO(m_io_name);
        if (engine == AdiosEngine::Plugin) {
            io.SetEngine("Plugin");
        }
        io.SetParameters(genAdiosParams(engine, worldSize, worldRank));

        adios2::Engine reader = io.Open(m_file, adios2::Mode::Read);
        reader.BeginStep();

        adios2::Variable<std::string> varGreeting = io.InquireVariable<std::string>(k_greeting);
        reader.Get(varGreeting, v_greeting);

        reader.EndStep();
        reader.Close();

        return v_greeting;
    }
};


TEST_P(adiosMPITests, ReadWrite) {
    AdiosEngine engine = std::get<0>(GetParam());
    MPIWorld worldSize = std::get<1>(GetParam());
    MPI_Barrier(MPI_COMM_WORLD);

    int numProcesses, worldRank;
    MPI_Comm_size(MPI_COMM_WORLD, &numProcesses);
    MPI_Comm_rank(MPI_COMM_WORLD, &worldRank);

    const std::string greeting = "Hello World from ADIOS2";
    std::string msgWritten, msgRead;

    if (worldSize == MPIWorld::Self) {
        adios2::ADIOS adiosSelf(MPI_COMM_SELF);
        msgWritten = adiosWriter(adiosSelf, engine, worldSize, worldRank);
        msgRead = adiosReader(adiosSelf, engine, worldSize, worldRank);
    } else {
        adios2::ADIOS adiosWorld(MPI_COMM_WORLD);
        msgWritten = adiosWriter(adiosWorld, engine, worldSize, worldRank);
        msgRead = adiosReader(adiosWorld, engine, worldSize, worldRank);
    }

    LOG(INFO) << "test_mpi_adios: " << msgRead << std::endl;
    EXPECT_EQ(msgWritten, msgRead);
}


auto adiosTV = ::testing::Values(std::make_tuple(AdiosEngine::BP5, MPIWorld::Shared),
                                 std::make_tuple(AdiosEngine::BP5, MPIWorld::Entire),
                                 std::make_tuple(AdiosEngine::BP5, MPIWorld::EntireSerial),
                                 std::make_tuple(AdiosEngine::BP5, MPIWorld::Self),
                                 std::make_tuple(AdiosEngine::BP5, MPIWorld::Split),
                                 std::make_tuple(AdiosEngine::Plugin, MPIWorld::Shared),
                                 std::make_tuple(AdiosEngine::Plugin, MPIWorld::Entire),
                                 std::make_tuple(AdiosEngine::Plugin, MPIWorld::EntireSerial),
                                 std::make_tuple(AdiosEngine::Plugin, MPIWorld::Self),
                                 std::make_tuple(AdiosEngine::Plugin, MPIWorld::Split));


INSTANTIATE_TEST_SUITE_P(lsmioTest, adiosMPITests, adiosTV);

}  // namespace lsmioTest
