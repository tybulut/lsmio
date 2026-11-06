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

#include <cstring>
#include <iostream>
#include <lsmio/lsmio.hpp>
#include <stdexcept>
#include <utility>
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

// The plugin under each aggregation layout: arrays, local values and attributes round-trip,
// and a put the aggregator cannot store fails the Close of every rank in its group
class pluginMPITests : public ::testing::TestWithParam<MPIWorld> {
  protected:
    std::string getFile(const std::string &name, MPIWorld worldSize, int worldRank) {
        std::string file = "test-mpi-plugin-" + name + "-" + genPreFix(true, worldSize);
        if (worldSize == MPIWorld::Self) file += "-" + std::to_string(worldRank);
        return file + ".db";
    }

    adios2::Params getParams(const std::string &file, MPIWorld worldSize) {
        adios2::Params params;
        params["PluginName"] = "LSMIOPlugin";
        params["PluginLibrary"] = "liblsmio_adios";
        params["FileName"] = file;
        if (worldSize == MPIWorld::Entire) {
            params["AggregationType"] = "EveryoneWrites";
        } else if (worldSize == MPIWorld::Split) {
            params["AggregationType"] = "EveryoneWrites";
            params["AggregatorRatio"] = "2";
        } else if (worldSize == MPIWorld::EntireSerial) {
            params["AggregationType"] = "EveryoneWritesSerial";
        } else if (worldSize == MPIWorld::Shared) {
            params["AggregationType"] = "TwoLevelShm";
        }
        return params;
    }

    // This rank's rank and size in its aggregation group, formed as LSMIOManager forms it
    // (group rank 0 is the aggregator)
    std::pair<int, int> aggGroup(MPIWorld worldSize, int worldRank) {
        if (worldSize == MPIWorld::Self) return {0, 1};
        MPI_Comm comm = MPI_COMM_WORLD;
        if (worldSize == MPIWorld::Shared) {
            MPI_Comm_split_type(MPI_COMM_WORLD, MPI_COMM_TYPE_SHARED, 0, MPI_INFO_NULL, &comm);
        } else if (worldSize == MPIWorld::Split) {
            MPI_Comm_split(MPI_COMM_WORLD, worldRank / 2, worldRank, &comm);
        }
        int rank, size;
        MPI_Comm_rank(comm, &rank);
        MPI_Comm_size(comm, &size);
        if (comm != MPI_COMM_WORLD) MPI_Comm_free(&comm);
        return {rank, size};
    }

    adios2::Engine open(adios2::ADIOS &adios, const std::string &ioName, const std::string &file,
                        MPIWorld worldSize, adios2::Mode mode) {
        adios2::IO io = adios.DeclareIO(ioName);
        io.SetEngine("Plugin");
        io.SetParameters(getParams(file, worldSize));
        return io.Open(file, mode);
    }
};

TEST_P(pluginMPITests, ArraysAndAttributes) {
    const MPIWorld worldSize = GetParam();
    int numProcesses, worldRank;
    MPI_Comm_size(MPI_COMM_WORLD, &numProcesses);
    MPI_Comm_rank(MPI_COMM_WORLD, &worldRank);
    MPI_Barrier(MPI_COMM_WORLD);

    const size_t n = 1000;
    std::vector<double> block(n);
    for (size_t i = 0; i < n; i++) block[i] = (worldRank * 1e6 + i) / 3.0;
    const std::string basePath = "/data/%T/;x";
    const std::string file = getFile("arrays", worldSize, worldRank);

    adios2::ADIOS adios(worldSize == MPIWorld::Self ? MPI_COMM_SELF : MPI_COMM_WORLD);
    const size_t ranks = (worldSize == MPIWorld::Self) ? 1 : numProcesses;
    const size_t offset = (worldSize == MPIWorld::Self) ? 0 : n * worldRank;

    {
        adios2::Engine writer = open(adios, "writer", file, worldSize, adios2::Mode::Write);
        adios2::IO io = adios.AtIO("writer");
        auto field = io.DefineVariable<double>("field", {n * ranks}, {offset}, {n});
        auto rank = io.DefineVariable<int>("rank", {adios2::LocalValueDim});
        io.DefineAttribute<int>("io_version", 3);
        io.DefineAttribute<std::string>("basePath", basePath);
        writer.Put(field, block.data(), adios2::Mode::Sync);
        writer.Put(rank, worldRank, adios2::Mode::Sync);
        writer.Close();
    }

    std::vector<double> read;
    int rankRead = -1;
    {
        adios2::Engine reader = open(adios, "reader", file, worldSize, adios2::Mode::Read);
        adios2::IO io = adios.AtIO("reader");
        auto field = io.InquireVariable<double>("field");
        ASSERT_TRUE(field);
        field.SetSelection({{offset}, {n}});
        reader.Get(field, read, adios2::Mode::Sync);
        reader.Get(io.InquireVariable<int>("rank"), rankRead, adios2::Mode::Sync);

        auto version = io.InquireAttribute<int>("io_version");
        ASSERT_TRUE(version);
        EXPECT_EQ(version.Data(), std::vector<int>{3});
        auto base = io.InquireAttribute<std::string>("basePath");
        ASSERT_TRUE(base);
        EXPECT_EQ(base.Data(), std::vector<std::string>{basePath});
        reader.Close();
    }

    ASSERT_EQ(read.size(), n);
    EXPECT_EQ(std::memcmp(read.data(), block.data(), n * sizeof(double)), 0);
    EXPECT_EQ(rankRead, worldRank);
}

// A put the store refuses (a key longer than maxKeyLen), made by a client (group rank 1) and
// then by an aggregator (group rank 0): the rank that puts to its own store throws at Put, and
// with aggregation every rank of the group throws at Close. Works for any number of ranks
TEST_P(pluginMPITests, FailedPutReportedAtClose) {
    const MPIWorld worldSize = GetParam();
    int numProcesses, worldRank;
    MPI_Comm_size(MPI_COMM_WORLD, &numProcesses);
    MPI_Comm_rank(MPI_COMM_WORLD, &worldRank);
    if (numProcesses < 2) GTEST_SKIP() << "needs at least 2 ranks";
    const auto [aggRank, aggSize] = aggGroup(worldSize, worldRank);

    for (const int badRank : {1, 0}) {
        MPI_Barrier(MPI_COMM_WORLD);
        const std::string file =
            getFile("failed-put-" + std::to_string(badRank), worldSize, worldRank);
        adios2::ADIOS adios(worldSize == MPIWorld::Self ? MPI_COMM_SELF : MPI_COMM_WORLD);
        adios2::Engine writer = open(adios, "writer", file, worldSize, adios2::Mode::Write);
        adios2::IO io = adios.AtIO("writer");

        auto ok = io.DefineVariable<int>("ok", {adios2::LocalValueDim});
        writer.Put(ok, worldRank, adios2::Mode::Sync);

        bool putThrew = false, closeThrew = false;
        if (aggRank == badRank) {
            auto bad = io.DefineVariable<int>(std::string(lsmio::gConfigLSMIO.maxKeyLen + 1, 'k'));
            try {
                writer.Put(bad, 1, adios2::Mode::Sync);
            } catch (const std::exception &) {
                putThrew = true;
            }
        }
        try {
            writer.Close();
        } catch (const std::exception &) {
            closeThrew = true;
        }
        // ADIOS keeps an engine open when its Close throws: closing again must be safe
        if (closeThrew) EXPECT_NO_THROW(writer.Close());

        const bool aggregated = (aggSize > 1);
        EXPECT_EQ(putThrew, aggRank == badRank && (!aggregated || aggRank == 0))
            << "rank " << worldRank << " bad rank " << badRank;
        EXPECT_EQ(closeThrew, aggregated && badRank < aggSize)
            << "rank " << worldRank << " bad rank " << badRank;
    }
}

INSTANTIATE_TEST_SUITE_P(lsmioTest, pluginMPITests,
                         ::testing::Values(MPIWorld::Shared, MPIWorld::Entire,
                                           MPIWorld::EntireSerial, MPIWorld::Self,
                                           MPIWorld::Split));

}  // namespace lsmioTest
