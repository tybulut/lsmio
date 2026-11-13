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

// T4: the BMBase iteration orchestration and the read-source exchange under MPI (2 ranks), with a
// mock engine whose store is a file, so a reader serves its source's data and not its own memory.

#include <gtest/gtest.h>
#include <mpi.h>
#include <unistd.h>

#include <filesystem>
#include <fstream>
#include <lsmio/lsmio.hpp>
#include <map>
#include <sstream>
#include <string>
#include <vector>

#include "bm_base.hpp"

namespace {

// A benchmark whose store is the file at genDBPath(false, false). The writer keeps its pairs in
// memory and writes them at finalize; the reader loads the file at readDBPath(false, false) and
// serves from it.
class FileBackedBM : public BMBase {
  public:
    int failWriteOnRank = -1;
    int failReadOnRank = -1;
    std::string lastReadPath;

    using BMBase::doWrite;

    static void setWorld(bool f_use_mpi, int f_size, int f_rank) {
        useMPI = f_use_mpi;
        mpiWorldSize = f_size;
        mpiWorldRank = f_rank;
        mpiSize = f_size;
        mpiRank = f_rank;
    }

    bool supportsReadShift() const override {
        return true;
    }

    bool doWrite(const std::string &key, const std::string &value) override {
        if (failWriteOnRank == mpiWorldRank) return false;
        m_written[key] = value;
        return true;
    }

    bool doWriteFinalize() override {
        std::ofstream file(m_write_path, std::ios::trunc);
        for (const auto &pair : m_written) {
            file << pair.first << '\t' << pair.second << '\n';
        }
        return file.good();
    }

    bool doRead(const std::string key, std::string *value) override {
        if (failReadOnRank == mpiWorldRank) return false;
        auto it = m_loaded.find(key);
        if (it == m_loaded.end()) return false;
        *value = it->second;
        return true;
    }

    int writePrepare(bool) override {
        m_write_path = genDBPath(false, false);
        std::filesystem::remove(m_write_path);
        std::ofstream(m_write_path).close();
        m_written.clear();
        return 0;
    }

    int readPrepare(bool) override {
        lastReadPath = readDBPath(false, false);
        m_loaded.clear();
        std::ifstream file(lastReadPath);
        std::string line;
        while (std::getline(file, line)) {
            size_t tab = line.find('\t');
            if (tab != std::string::npos) {
                m_loaded[line.substr(0, tab)] = line.substr(tab + 1);
            }
        }
        return 0;
    }

    int run(const std::string &f_prefix) {
        return benchSuite(f_prefix);
    }
    const std::string &basePath() const {
        return _lsmioBMPath;
    }
    const std::string &phaseText() const {
        return m_bench_results_phases;
    }
    const std::string &writeResults() const {
        return _benchResultsWrite;
    }
    const std::string &readResults() const {
        return _benchResultsRead;
    }
    const ReadSource &readSource() const {
        return m_read_source;
    }
    std::string shiftLines() const {
        return readShiftHeaderLines();
    }

  private:
    std::map<std::string, std::string> m_written;
    std::map<std::string, std::string> m_loaded;
    std::string m_write_path;
};

int countOf(const std::string &f_text, const std::string &f_needle) {
    int count = 0;
    for (size_t at = f_text.find(f_needle); at != std::string::npos;
         at = f_text.find(f_needle, at + 1)) {
        count++;
    }
    return count;
}

bool endsWith(const std::string &f_text, const std::string &f_suffix) {
    return f_text.size() >= f_suffix.size() &&
           f_text.compare(f_text.size() - f_suffix.size(), f_suffix.size(), f_suffix) == 0;
}

// Every rank holds the bytes of rank 0 (a collective).
void expectSameOnAllRanks(const std::string &f_text) {
    int length = static_cast<int>(f_text.size());
    MPI_Bcast(&length, 1, MPI_INT, 0, MPI_COMM_WORLD);
    std::string root(static_cast<size_t>(length), '\0');
    int rank = 0;
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    if (rank == 0) root = f_text;
    MPI_Bcast(root.data(), length, MPI_CHAR, 0, MPI_COMM_WORLD);
    EXPECT_EQ(root, f_text);
}

}  // namespace

class MPIBMBaseTest : public ::testing::Test {
  protected:
    int m_size = 0;
    int m_rank = 0;
    std::filesystem::path m_dir;

    void SetUp() override {
        MPI_Comm_size(MPI_COMM_WORLD, &m_size);
        MPI_Comm_rank(MPI_COMM_WORLD, &m_rank);
        ASSERT_EQ(m_size, 2);

        // Same directory and file name on every rank: derived from the test name and the user.
        const std::string test_name = ::testing::UnitTest::GetInstance()->current_test_info()->name();
        m_dir = std::filesystem::temp_directory_path() /
                ("lsmio_mpi_bm_base_" + std::to_string(getuid()) + "_" + test_name);
        std::error_code ignored;
        std::filesystem::create_directories(m_dir, ignored);
        MPI_Barrier(MPI_COMM_WORLD);

        FileBackedBM::setWorld(true, m_size, m_rank);
        gConfigBM = BMConfig();
        gConfigBM.keyCount = 16;
        gConfigBM.valueSize = 64;
        gConfigBM.iterations = 1;
        gConfigBM.useMPIBarrier = true;
        gConfigBM.perRankPath = true;
        gConfigBM.fileName = "store";
        gConfigBM.dirName = m_dir.string();
    }

    void TearDown() override {
        MPI_Barrier(MPI_COMM_WORLD);
        if (m_rank == 0) {
            std::error_code ignored;
            std::filesystem::remove_all(m_dir, ignored);
        }
        MPI_Barrier(MPI_COMM_WORLD);
        FileBackedBM::setWorld(false, 0, 0);
        gConfigBM = BMConfig();
    }

    // One rank fails its write (or read) in the first iteration: both ranks must return the same
    // status, suppress the same rows and print the same phase text (INV-6, INV-7, INV-8).
    void runFailureCase(bool f_shift, bool f_write_failure) {
        gConfigBM.iterations = 2;
        gConfigBM.readShift = f_shift;
        gConfigBM.readShiftNodes = f_shift ? 2 : 0;

        FileBackedBM bm;
        if (f_write_failure) {
            bm.failWriteOnRank = 1;
        } else {
            bm.failReadOnRank = 1;
        }
        const int expected = f_write_failure ? lsmio::BM_ERR_WRITE : lsmio::BM_ERR_READ;
        const int status = bm.run("Failure");

        EXPECT_EQ(status, expected);
        int lowest = 0;
        int highest = 0;
        MPI_Allreduce(&status, &lowest, 1, MPI_INT, MPI_MIN, MPI_COMM_WORLD);
        MPI_Allreduce(&status, &highest, 1, MPI_INT, MPI_MAX, MPI_COMM_WORLD);
        EXPECT_EQ(lowest, highest);

        EXPECT_EQ(bm.readSource().is_self, !f_shift);
        EXPECT_EQ(bm.readSource().source_world_rank, f_shift ? 1 - m_rank : m_rank);

        // The suite halts at the failed first iteration. A write failure suppresses both sides'
        // rows; a read failure keeps the write row and suppresses the read row.
        EXPECT_EQ(countOf(bm.phaseText(), "phase,write,"), f_write_failure ? 0 : 1);
        EXPECT_EQ(countOf(bm.phaseText(), "phase,read,"), 0);
        EXPECT_EQ(bm.writeResults().find("iwrite,") != std::string::npos, !f_write_failure);
        EXPECT_EQ(bm.readResults().find("iread,"), std::string::npos);
        expectSameOnAllRanks(bm.phaseText());
    }
};

TEST_F(MPIBMBaseTest, NoShiftRankLocalWriteFailure) {
    runFailureCase(false, true);
}

TEST_F(MPIBMBaseTest, NoShiftRankLocalReadFailure) {
    runFailureCase(false, false);
}

TEST_F(MPIBMBaseTest, ShiftRankLocalWriteFailure) {
    runFailureCase(true, true);
}

TEST_F(MPIBMBaseTest, ShiftRankLocalReadFailure) {
    runFailureCase(true, false);
}

TEST_F(MPIBMBaseTest, NoShiftSuccessReadsOwnStoreAndPrintsNoShiftLines) {
    gConfigBM.iterations = 2;
    FileBackedBM bm;
    ASSERT_EQ(bm.run("Own"), lsmio::BM_SUCCESS);

    EXPECT_TRUE(endsWith(bm.basePath(), ".mpirank" + std::to_string(m_rank)));
    EXPECT_TRUE(bm.readSource().is_self);
    EXPECT_EQ(bm.readSource().source_world_rank, m_rank);
    EXPECT_TRUE(endsWith(bm.lastReadPath, ".mpirank" + std::to_string(m_rank) + ":0:0"));
    EXPECT_EQ(bm.shiftLines(), "");
    EXPECT_EQ(countOf(bm.phaseText(), "phase,"), 4);  // 2 iterations, write and read each
    expectSameOnAllRanks(bm.phaseText());
}

TEST_F(MPIBMBaseTest, ShiftSimulatedTwoNodes) {
    gConfigBM.iterations = 2;
    gConfigBM.readShift = true;
    gConfigBM.readShiftNodes = 2;
    FileBackedBM bm;
    // Success means every value read from the peer's store matched the peer's permutation (INV-13).
    ASSERT_EQ(bm.run("Shift"), lsmio::BM_SUCCESS);

    const int peer = 1 - m_rank;
    EXPECT_TRUE(endsWith(bm.basePath(), ".mpirank" + std::to_string(m_rank)));
    EXPECT_EQ(bm.readSource().source_world_rank, peer);
    EXPECT_FALSE(bm.readSource().is_self);
    EXPECT_TRUE(endsWith(bm.readSource().source_base_path, ".mpirank" + std::to_string(peer)));
    EXPECT_EQ(bm.readSource().self_ranks_world, 0);
    // The reader opened the peer's store, not its own.
    EXPECT_TRUE(endsWith(bm.lastReadPath, ".mpirank" + std::to_string(peer) + ":0:0"));

    // Every iteration has its read row, in the legacy and in the phase rows.
    EXPECT_NE(bm.readResults().find("iread,"), std::string::npos);
    EXPECT_EQ(bm.readResults().find("FAILED"), std::string::npos);
    EXPECT_EQ(countOf(bm.phaseText(), "phase,read,"), 2);
    EXPECT_EQ(countOf(bm.phaseText(), "phase,write,"), 2);
    expectSameOnAllRanks(bm.phaseText());

    // Header lines of this printer.
    const std::string lines = bm.shiftLines();
    EXPECT_NE(lines.find(" rankShiftNodes: simulated:2\n"), std::string::npos);
    EXPECT_NE(lines.find(" rankShiftSource: " + std::to_string(peer) + "\n"), std::string::npos);
    EXPECT_NE(lines.find(" rankShiftSelfRanks: 0\n"), std::string::npos);
    EXPECT_NE(lines.find(" rankShiftSameHostRanks: "), std::string::npos);

    testing::internal::CaptureStdout();
    bm.writeBenchmarkResults();
    const std::string out = testing::internal::GetCapturedStdout();
    if (m_rank == 0) {
        size_t flag = out.find(" rankShift: 1\n");
        size_t detail = out.find(" rankShiftNodes: simulated:2\n");
        size_t results = out.find("BENCHMARK RESULTS:");
        ASSERT_NE(flag, std::string::npos);
        ASSERT_NE(detail, std::string::npos);
        ASSERT_NE(results, std::string::npos);
        EXPECT_LT(flag, detail);
        EXPECT_LT(detail, results);
    } else {
        EXPECT_EQ(out, "");  // only the printing rank prints
    }
}

TEST_F(MPIBMBaseTest, ShiftSimulatedOneNode) {
    gConfigBM.readShift = true;
    gConfigBM.readShiftNodes = 1;
    FileBackedBM bm;
    ASSERT_EQ(bm.run("OneNode"), lsmio::BM_SUCCESS);

    EXPECT_TRUE(bm.readSource().is_self);
    EXPECT_EQ(bm.readSource().source_world_rank, m_rank);
    EXPECT_EQ(bm.readSource().self_ranks_world, 2);
    EXPECT_TRUE(endsWith(bm.lastReadPath, ".mpirank" + std::to_string(m_rank) + ":0:0"));
    EXPECT_NE(bm.shiftLines().find(" rankShiftSelfRanks: 2\n"), std::string::npos);
    expectSameOnAllRanks(bm.phaseText());
}

TEST_F(MPIBMBaseTest, ShiftSharedNodesUsesTheRealNodeSplit) {
    // No simulated node count: the node ids come from the shared-memory split. Under one launcher
    // on one host both ranks share a node, so each reads itself (the split is the real topology).
    gConfigBM.readShift = true;
    FileBackedBM bm;
    ASSERT_EQ(bm.run("Shared"), lsmio::BM_SUCCESS);

    EXPECT_NE(bm.shiftLines().find(" rankShiftNodes: shared\n"), std::string::npos);
    int is_self = bm.readSource().is_self ? 1 : 0;
    int self_total = 0;
    MPI_Allreduce(&is_self, &self_total, 1, MPI_INT, MPI_SUM, MPI_COMM_WORLD);
    EXPECT_EQ(self_total, bm.readSource().self_ranks_world);
    expectSameOnAllRanks(bm.phaseText());
}

TEST_F(MPIBMBaseTest, SetupRunsOncePerObjectAndEachObjectRunsItsOwn) {
    // Two objects in one process with different settings each run their own setup (NB25).
    gConfigBM.readShift = true;
    gConfigBM.readShiftNodes = 2;
    {
        FileBackedBM first;
        ASSERT_EQ(first.run("A"), lsmio::BM_SUCCESS);
        ASSERT_EQ(first.run("B"), lsmio::BM_SUCCESS);  // the second suite does not set up again
        EXPECT_EQ(first.readSource().source_world_rank, 1 - m_rank);
    }
    gConfigBM.readShiftNodes = 1;
    {
        FileBackedBM second;
        ASSERT_EQ(second.run("C"), lsmio::BM_SUCCESS);
        EXPECT_EQ(second.readSource().source_world_rank, m_rank);
    }
}
