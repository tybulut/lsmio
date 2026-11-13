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

#include <glog/logging.h>
#include <gtest/gtest.h>
#include <sys/wait.h>
#include <unistd.h>

#include <algorithm>
#include <cstdlib>
#include <lsmio/lsmio.hpp>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

#include "KeyPermutation.hpp"
#include "PhaseTimeline.hpp"
#include "ReadShift.hpp"
#include "bm_base.hpp"

class MockBM : public BMBase {
  public:
    bool failWrite = false;
    bool failRead = false;
    int writeFailureCount = 0;
    int readFailureCount = 0;
    int writePrepareCalls = 0;
    int readPrepareCalls = 0;
    int writeCleanupCalls = 0;
    int readCleanupCalls = 0;
    std::unordered_map<std::string, std::string> kvStore;

    using BMBase::doWrite;

    bool doWrite(const std::string &key, const std::string &value) override {
        if (failWrite) {
            writeFailureCount++;
            return false;
        }
        kvStore[key] = value;
        return true;
    }

    virtual bool doRead(const std::string key, std::string *value) override {
        if (failRead) {
            readFailureCount++;
            return false;
        }
        auto it = kvStore.find(key);
        if (it != kvStore.end()) {
            *value = it->second;
            return true;
        }
        return false;
    }

    virtual int writePrepare(bool opt = false) override {
        writePrepareCalls++;
        return 0;
    }

    virtual int writeCleanup() override {
        writeCleanupCalls++;
        return 0;
    }

    virtual int readPrepare(bool opt = false) override {
        readPrepareCalls++;
        return 0;
    }

    virtual int readCleanup() override {
        readCleanupCalls++;
        return 0;
    }

    // Public inspectors for internal BMBase protected state
    const std::string &getBenchResultsWrite() const {
        return _benchResultsWrite;
    }
    const std::string &getBenchResultsRead() const {
        return _benchResultsRead;
    }
    const lsmio::Benchmark &getBenchmark() const {
        return _bm;
    }
    int *getRandomKeyIndex() const {
        return pRandomKeyIndex;
    }
    const std::string &getBMPath() const {
        return _lsmioBMPath;
    }
    std::string path(bool f_opt1, bool f_opt2) {
        return genDBPath(f_opt1, f_opt2);
    }
    std::string readPath(bool f_opt1, bool f_opt2) {
        return readDBPath(f_opt1, f_opt2);
    }
    static void setWorldRank(int f_rank) {
        mpiWorldRank = f_rank;
    }
    const std::string &getPhaseText() const {
        return m_bench_results_phases;
    }
    const ReadSource &readSource() const {
        return m_read_source;
    }
    std::string shiftLines() const {
        return readShiftHeaderLines();
    }

    std::string headerLines;  // returned by the engineHeaderLines hook
    std::string engineHeaderLines() const override {
        return headerLines;
    }
};

class BMBaseTest : public ::testing::Test {
  protected:
    void SetUp() override {
        gConfigBM.keyCount = 16;
        gConfigBM.valueSize = 64;
        gConfigBM.iterations = 1;
        gConfigBM.useMPIBarrier = false;
        gConfigBM.fileName = "mock_test_db";
        gConfigBM.dirName = "";
    }

    void TearDown() override {
        gConfigBM = BMConfig();
        MockBM::setWorldRank(0);
    }
};

TEST_F(BMBaseTest, PerRankPathSuffix) {
    MockBM::setWorldRank(5);
    gConfigBM.perRankPath = true;
    {
        MockBM bm;
        EXPECT_EQ(bm.getBMPath(), "mock_test_db.mpirank5");
        EXPECT_EQ(bm.path(false, true), "mock_test_db.mpirank5:0:1");
        EXPECT_EQ(bm.readPath(false, true), "mock_test_db.mpirank5:0:1");
    }
    gConfigBM.dirName = "some_dir";
    {
        MockBM bm;
        EXPECT_EQ(bm.getBMPath(), "some_dir/mock_test_db.mpirank5");
        EXPECT_EQ(bm.path(true, false), "some_dir/mock_test_db.mpirank5:1:0");
    }
    gConfigBM.perRankPath = false;
    {
        MockBM bm;
        EXPECT_EQ(bm.getBMPath(), "some_dir/mock_test_db");
        EXPECT_EQ(bm.readPath(true, true), "some_dir/mock_test_db:1:1");
    }
}

TEST_F(BMBaseTest, HappyPathSuccess) {
    MockBM bm;
    int status = bm.benchSuite("MockSuccess");
    EXPECT_EQ(status, lsmio::BM_SUCCESS);
    EXPECT_EQ(bm.writePrepareCalls, 1);
    EXPECT_EQ(bm.readPrepareCalls, 1);
    EXPECT_EQ(bm.writeCleanupCalls, 1);
    EXPECT_EQ(bm.readCleanupCalls, 1);
    EXPECT_EQ(bm.getRandomKeyIndex(), nullptr);
    EXPECT_EQ(bm.getBenchResultsWrite().find("write, FAILED"), std::string::npos);
}

TEST_F(BMBaseTest, WriteFailureHaltsImmediatelyWithoutRetry) {
    MockBM bm;
    bm.failWrite = true;
    gConfigBM.iterations = 5;  // Multi-iteration suite

    int status = bm.benchSuite("MockWriteFail");
    // Assert exit code indicates write failure
    EXPECT_EQ(status, lsmio::BM_ERR_WRITE);
    // Assert INV-ERR-7: Halted immediately after iteration 0, ZERO RETRIES!
    EXPECT_EQ(bm.writePrepareCalls, 1);
    // Assert read phase was skipped entirely
    EXPECT_EQ(bm.readPrepareCalls, 0);
    EXPECT_EQ(bm.readCleanupCalls, 0);
    EXPECT_EQ(bm.writeCleanupCalls, 1);
    // Assert summary row emitted FAILED
    EXPECT_NE(bm.getBenchResultsWrite().find("write, FAILED"), std::string::npos);
    EXPECT_EQ(bm.getRandomKeyIndex(), nullptr);
}

TEST_F(BMBaseTest, ReadFailurePropagates) {
    MockBM bm;
    bm.failRead = true;
    gConfigBM.iterations = 3;

    int status = bm.benchSuite("MockReadFail");
    EXPECT_EQ(status, lsmio::BM_ERR_READ);
    EXPECT_EQ(bm.writePrepareCalls, 1);
    EXPECT_EQ(bm.readPrepareCalls, 1);
    EXPECT_EQ(bm.writeCleanupCalls, 1);
    EXPECT_EQ(bm.readCleanupCalls, 1);
    // Assert read summary row emitted FAILED
    EXPECT_NE(bm.getBenchResultsRead().find("read, FAILED"), std::string::npos);
    EXPECT_EQ(bm.getRandomKeyIndex(), nullptr);
}

TEST_F(BMBaseTest, FailedSummaryRowEmitted) {
    MockBM bm;
    bm.failWrite = true;
    bm.benchSuite("MockWriteFail");
    EXPECT_NE(bm.getBenchResultsWrite().find("write, FAILED"), std::string::npos);
    EXPECT_NE(bm.getBenchResultsRead().find("read, FAILED"), std::string::npos);
}

TEST_F(BMBaseTest, MemorySafetyNoLeak) {
    MockBM bm;
    gConfigBM.iterations = 10;
    int status = bm.benchSuite("MockLeakTest");
    EXPECT_EQ(status, lsmio::BM_SUCCESS);
    EXPECT_EQ(bm.writePrepareCalls, 10);
    EXPECT_EQ(bm.readPrepareCalls, 10);
    EXPECT_EQ(bm.getRandomKeyIndex(), nullptr);
}

TEST_F(BMBaseTest, VirtualFallbackRvalueForwarding) {
    MockBM bm;
    bm.doWrite("test_key", std::string("test_val"));
    EXPECT_EQ(bm.kvStore["test_key"], "test_val");
}

namespace {

// The "phase," rows of a phase text as comma-split fields:
// phase,<side>,<iteration>,<bytes>,<beforeOpen>,<afterOpen>,<beforeClose>,<afterClose>,<afterDelete>
std::vector<std::vector<std::string>> phaseRows(const std::string &f_text) {
    std::vector<std::vector<std::string>> rows;
    std::istringstream lines(f_text);
    std::string line;
    while (std::getline(lines, line)) {
        if (line.rfind("phase,", 0) != 0) continue;
        std::vector<std::string> fields;
        std::istringstream cells(line);
        std::string cell;
        while (std::getline(cells, cell, ',')) fields.push_back(cell);
        rows.push_back(fields);
    }
    return rows;
}

}  // namespace

TEST_F(BMBaseTest, PhaseRowsOnSuccess) {
    gConfigBM.iterations = 3;
    MockBM bm;
    ASSERT_EQ(bm.benchSuite("MockSuccess"), lsmio::BM_SUCCESS);

    const std::string &text = bm.getPhaseText();
    EXPECT_NE(text.find("Phases: MockSuccess\n"), std::string::npos);
    std::vector<std::vector<std::string>> rows = phaseRows(text);
    ASSERT_EQ(rows.size(), 6u);  // per iteration, write then read
    for (int iter = 0; iter < 3; iter++) {
        const std::vector<std::string> &w = rows[2 * iter];
        const std::vector<std::string> &r = rows[2 * iter + 1];
        ASSERT_EQ(w.size(), 9u);
        ASSERT_EQ(r.size(), 9u);
        EXPECT_EQ(w[1], "write");
        EXPECT_EQ(r[1], "read");
        EXPECT_EQ(w[2], std::to_string(iter));
        EXPECT_EQ(r[2], std::to_string(iter));
        EXPECT_EQ(w[3], std::to_string(16 * 64));  // keyCount * valueSize, no MPI
        EXPECT_EQ(r[3], std::to_string(16 * 64));
        long long wo[5], ro[5];
        for (int b = 0; b < 5; b++) {
            wo[b] = std::stoll(w[4 + b]);
            ro[b] = std::stoll(r[4 + b]);
        }
        EXPECT_EQ(wo[0], 0);
        for (int b = 1; b < 5; b++) {
            EXPECT_LE(wo[b - 1], wo[b]);
            EXPECT_LE(ro[b - 1], ro[b]);
        }
        EXPECT_GE(ro[0], wo[4]);
    }
}

TEST_F(BMBaseTest, WriteFailureSuppressesBothPhaseRows) {
    gConfigBM.iterations = 3;
    MockBM bm;
    bm.failWrite = true;
    EXPECT_EQ(bm.benchSuite("MockWriteFail"), lsmio::BM_ERR_WRITE);

    EXPECT_NE(bm.getPhaseText().find("Phases: MockWriteFail\n"), std::string::npos);
    EXPECT_EQ(bm.getPhaseText().find("phase,write"), std::string::npos);
    EXPECT_EQ(bm.getPhaseText().find("phase,read"), std::string::npos);
    EXPECT_TRUE(phaseRows(bm.getPhaseText()).empty());
    // The legacy write row is suppressed in the same way.
    EXPECT_EQ(bm.getBenchResultsWrite().find("iwrite,"), std::string::npos);
    EXPECT_EQ(bm.getRandomKeyIndex(), nullptr);
}

TEST_F(BMBaseTest, ReadFailureSuppressesReadPhaseRow) {
    gConfigBM.iterations = 3;
    MockBM bm;
    bm.failRead = true;
    EXPECT_EQ(bm.benchSuite("MockReadFail"), lsmio::BM_ERR_READ);

    // The suite halts at the first failed iteration: one write row, no read row.
    std::vector<std::vector<std::string>> rows = phaseRows(bm.getPhaseText());
    ASSERT_EQ(rows.size(), 1u);
    EXPECT_EQ(rows[0][1], "write");
    EXPECT_EQ(rows[0][2], "0");
    EXPECT_EQ(bm.getPhaseText().find("phase,read"), std::string::npos);
    // The legacy rows agree: the iwrite row exists, the iread row does not.
    EXPECT_NE(bm.getBenchResultsWrite().find("iwrite"), std::string::npos);
    EXPECT_EQ(bm.getBenchResultsRead().find("iread"), std::string::npos);
    EXPECT_EQ(bm.getRandomKeyIndex(), nullptr);
}

TEST_F(BMBaseTest, TwoSuitesTwoPhaseBlocks) {
    MockBM bm;
    ASSERT_EQ(bm.benchSuite("First Suite"), lsmio::BM_SUCCESS);
    ASSERT_EQ(bm.benchSuite("Second Suite"), lsmio::BM_SUCCESS);

    const std::string &text = bm.getPhaseText();
    size_t first = text.find("Phases: First Suite\n");
    size_t second = text.find("Phases: Second Suite\n");
    ASSERT_NE(first, std::string::npos);
    ASSERT_NE(second, std::string::npos);
    EXPECT_LT(first, second);
    EXPECT_EQ(text.find("Phases: First Suite\n", first + 1), std::string::npos);
    // Each block holds its own suite's rows only (1 iteration: a write and a read row each).
    EXPECT_EQ(phaseRows(text.substr(first, second - first)).size(), 2u);
    EXPECT_EQ(phaseRows(text.substr(second)).size(), 2u);
}

TEST_F(BMBaseTest, ReadsOwnPermutation) {
    // Without read shift the reader's source is itself, so every iteration reads back the values
    // its own permutation wrote (INV-13).
    gConfigBM.iterations = 3;
    MockBM bm;
    EXPECT_EQ(bm.benchSuite("MockOwn"), lsmio::BM_SUCCESS);
    EXPECT_EQ(bm.readFailureCount, 0);
    EXPECT_EQ(phaseRows(bm.getPhaseText()).size(), 6u);
    EXPECT_EQ(bm.getBenchResultsRead().find("read, FAILED"), std::string::npos);
}

TEST_F(BMBaseTest, ResultsPrintEngineHeaderLinesAndPhaseBlocks) {
    MockBM bm;
    bm.headerLines = " mockEngine: 7\n";
    ASSERT_EQ(bm.benchSuite("MockPrint"), lsmio::BM_SUCCESS);

    testing::internal::CaptureStdout();
    bm.writeBenchmarkResults();
    std::string out = testing::internal::GetCapturedStdout();

    size_t header = out.find(" mockEngine: 7\n");
    size_t results = out.find("BENCHMARK RESULTS: \n");
    size_t readBlock = out.find("Iteration-READ: MockPrint");
    size_t phases = out.find("Phases: MockPrint\n");
    ASSERT_NE(header, std::string::npos);
    ASSERT_NE(results, std::string::npos);
    ASSERT_NE(readBlock, std::string::npos);
    ASSERT_NE(phases, std::string::npos);
    EXPECT_LT(out.find(" rankShift: 0"), header);  // after the generated header
    EXPECT_LT(header, results);                    // before the results
    EXPECT_LT(readBlock, phases);                  // phases after every READ block
}

TEST(BMBaseVersionTest, CleanExitOnVersionFlag) {
    char *argv[] = {(char *)"test_bm_base", (char *)"--version", nullptr};
    int argc = 2;

    ASSERT_EXIT(
        {
            dup2(STDERR_FILENO, STDOUT_FILENO);
            BMBase::beginMain(argc, argv);
        },
        ::testing::ExitedWithCode(0), ".*version.*branch:.*commit:.*");
}

TEST(BMBaseVersionTest, CleanExitOnShortVersionFlag) {
    char *argv[] = {(char *)"test_bm_base", (char *)"-V", nullptr};
    int argc = 2;

    ASSERT_EXIT(
        {
            dup2(STDERR_FILENO, STDOUT_FILENO);
            BMBase::beginMain(argc, argv);
        },
        ::testing::ExitedWithCode(0), ".*version.*branch:.*commit:.*");
}

TEST(BMBaseVersionTest, ParameterHeaderContainsGitProvenance) {
    std::string optStr = genOptionsToString();
    EXPECT_NE(optStr.find("version: "), std::string::npos);
    EXPECT_NE(optStr.find("gitBranch: "), std::string::npos);
    EXPECT_NE(optStr.find("gitCommit: "), std::string::npos);
    EXPECT_NE(optStr.find("readOnly: true"), std::string::npos);
    EXPECT_NE(optStr.find(" perRankPath: 0"), std::string::npos);
    EXPECT_NE(optStr.find(" durability: engine"), std::string::npos);
    EXPECT_NE(optStr.find(" rankShift: 0"), std::string::npos);
}

TEST_F(BMBaseTest, NoShiftSetupKeepsSelfSourceAndPrintsNoShiftLines) {
    gConfigBM.iterations = 2;
    MockBM bm;
    ASSERT_EQ(bm.benchSuite("MockNoShift"), lsmio::BM_SUCCESS);
    ASSERT_EQ(bm.benchSuite("MockNoShiftAgain"), lsmio::BM_SUCCESS);  // setup runs once per object

    EXPECT_EQ(bm.readSource().source_world_rank, 0);
    EXPECT_EQ(bm.readSource().source_base_path, "mock_test_db");
    EXPECT_TRUE(bm.readSource().is_self);
    EXPECT_EQ(bm.shiftLines(), "");

    testing::internal::CaptureStdout();
    bm.writeBenchmarkResults();
    std::string out = testing::internal::GetCapturedStdout();
    EXPECT_EQ(out.find("rankShiftNodes"), std::string::npos);
    EXPECT_EQ(out.find("rankShiftSource"), std::string::npos);
}

TEST_F(BMBaseTest, ShiftHeaderLinesSharedAndSimulated) {
    gConfigBM.readShift = true;
    {
        MockBM bm;  // the constructor's self source
        EXPECT_EQ(bm.shiftLines(),
                  " rankShiftNodes: shared\n rankShiftSource: 0\n rankShiftSelfRanks: 0\n"
                  " rankShiftSameHostRanks: 0\n");
    }
    gConfigBM.readShiftNodes = 3;
    {
        MockBM bm;
        EXPECT_EQ(bm.shiftLines().rfind(" rankShiftNodes: simulated:3\n", 0), 0u);
    }
}

TEST(BMBaseReadSourceTest, RefusalNeedsSupportAndEnoughRanks) {
    EXPECT_EQ(readShiftRefusal(true, 0, 4), "");
    EXPECT_EQ(readShiftRefusal(true, 4, 4), "");
    EXPECT_EQ(readShiftRefusal(true, 1, 4), "");
    EXPECT_NE(readShiftRefusal(false, 0, 4).find("not supported"), std::string::npos);
    std::string too_many = readShiftRefusal(true, 5, 4);
    EXPECT_NE(too_many.find("--read-shift-nodes 5"), std::string::npos);
    EXPECT_NE(too_many.find("world size 4"), std::string::npos);
    // Support is checked before the node count.
    EXPECT_NE(readShiftRefusal(false, 9, 4).find("not supported"), std::string::npos);
}

TEST(BMBaseReadSourceTest, DuplicatePathsAreRefusedWithAdvice) {
    EXPECT_EQ(duplicateStorePathRefusal({}), "");
    EXPECT_EQ(duplicateStorePathRefusal({"a.mpirank0", "a.mpirank1", "a.mpirank2"}), "");
    std::string message = duplicateStorePathRefusal({"db", "other", "db"});
    EXPECT_NE(message.find("ranks 0 and 2"), std::string::npos);
    EXPECT_NE(message.find("'db'"), std::string::npos);
    EXPECT_NE(message.find("--per-rank-path"), std::string::npos);
}

TEST(BMBaseReadSourceTest, MakeReadSourceTwoNodesTwoRanksEach) {
    // Ranks 0,1 on node 0 and ranks 2,3 on node 1: every rank reads the same local index on the
    // other node.
    const std::vector<int> nodes = {0, 0, 2, 2};
    const std::vector<std::string> paths = {"p0", "p1", "p2", "p3"};
    const std::vector<std::string> names = {"hostA", "hostA", "hostB", "hostB"};
    ReadSource r0 = makeReadSource(0, nodes, paths, names);
    EXPECT_EQ(r0.source_world_rank, 2);
    EXPECT_EQ(r0.source_base_path, "p2");
    EXPECT_FALSE(r0.is_self);
    EXPECT_FALSE(r0.same_host);
    EXPECT_EQ(r0.self_ranks_world, 0);
    EXPECT_EQ(r0.same_host_ranks_world, 0);
    ReadSource r3 = makeReadSource(3, nodes, paths, names);
    EXPECT_EQ(r3.source_world_rank, 1);
    EXPECT_EQ(r3.source_base_path, "p1");
}

TEST(BMBaseReadSourceTest, MakeReadSourceCountsSelfAndSameHostRanks) {
    // One node only: every rank is its own source on the same host.
    ReadSource one = makeReadSource(1, {5, 5}, {"p0", "p1"}, {"h", "h"});
    EXPECT_EQ(one.source_world_rank, 1);
    EXPECT_EQ(one.source_base_path, "p1");
    EXPECT_TRUE(one.is_self);
    EXPECT_TRUE(one.same_host);
    EXPECT_EQ(one.self_ranks_world, 2);
    EXPECT_EQ(one.same_host_ranks_world, 2);

    // Two nodes that share one processor name (simulated nodes on one host): not self, same host.
    ReadSource sim = makeReadSource(0, {0, 1}, {"p0", "p1"}, {"h", "h"});
    EXPECT_EQ(sim.source_world_rank, 1);
    EXPECT_FALSE(sim.is_self);
    EXPECT_TRUE(sim.same_host);
    EXPECT_EQ(sim.self_ranks_world, 0);
    EXPECT_EQ(sim.same_host_ranks_world, 2);

    // Three ranks, node 0 holds two and node 1 one: local index 1 has one node, so rank 1 reads
    // itself while ranks 0 and 2 swap.
    ReadSource mixed = makeReadSource(1, {0, 0, 1}, {"p0", "p1", "p2"}, {"a", "a", "b"});
    EXPECT_TRUE(mixed.is_self);
    EXPECT_EQ(mixed.self_ranks_world, 1);
    EXPECT_EQ(mixed.same_host_ranks_world, 1);
}

namespace {

// Runs beginMain on the given arguments in a death-test child and returns only if it did
// not exit; the refusals and CLI11 errors exit the child.
void runBeginMain(std::vector<std::string> f_args) {
    std::vector<char *> argv;
    for (std::string &arg : f_args) {
        argv.push_back(arg.data());
    }
    argv.push_back(nullptr);
    dup2(STDERR_FILENO, STDOUT_FILENO);
    BMBase::beginMain(static_cast<int>(f_args.size()), argv.data());
}

bool exitedNonZero(int f_status) {
    return WIFEXITED(f_status) && WEXITSTATUS(f_status) != 0;
}

}  // namespace

TEST(BMBaseCliTest, DurabilityPageCacheWithSyncIsRefused) {
    ASSERT_EXIT(runBeginMain({"test_bm_base", "-o", "x", "--lsmio-durability", "page-cache", "-e"}),
                ::testing::ExitedWithCode(1),
                "--lsmio-durability page-cache cannot be combined with -e/--sync");
}

TEST(BMBaseCliTest, PerRankPathWithoutMpiBarrierIsRefused) {
    ASSERT_EXIT(runBeginMain({"test_bm_base", "-o", "x", "--per-rank-path"}),
                ::testing::ExitedWithCode(1), "--per-rank-path requires -m/--mpi-barrier");
}

TEST(BMBaseCliTest, PerRankPathWithCollectiveIoIsRefused) {
    ASSERT_EXIT(runBeginMain({"test_bm_base", "-o", "x", "-m", "-c", "--per-rank-path"}),
                ::testing::ExitedWithCode(1),
                "--per-rank-path cannot be combined with -c/--collective-io");
}

TEST(BMBaseCliTest, ReadShiftWithoutMpiBarrierIsRefused) {
    ASSERT_EXIT(runBeginMain({"test_bm_base", "-o", "x", "--read-shift"}),
                ::testing::ExitedWithCode(1), "--read-shift requires -m/--mpi-barrier");
}

TEST(BMBaseCliTest, ReadShiftWithCollectiveIoIsRefused) {
    ASSERT_EXIT(runBeginMain({"test_bm_base", "-o", "x", "-m", "-c", "--read-shift"}),
                ::testing::ExitedWithCode(1),
                "--read-shift cannot be combined with -c/--collective-io");
}

TEST(BMBaseCliTest, ReadShiftNodesWithoutReadShiftIsRefused) {
    ASSERT_EXIT(runBeginMain({"test_bm_base", "-o", "x", "--read-shift-nodes", "2"}),
                ::testing::ExitedWithCode(1), "--read-shift-nodes requires --read-shift");
}

TEST(BMBaseCliTest, ReadShiftNodesBelowOneIsRefused) {
    ASSERT_EXIT(runBeginMain({"test_bm_base", "-o", "x", "-m", "--read-shift",
                              "--read-shift-nodes", "0"}),
                ::testing::ExitedWithCode(1), "--read-shift-nodes must be >= 1");
}

TEST(BMBaseCliTest, UnknownDurabilityModeExitsNonZero) {
    ASSERT_EXIT(runBeginMain({"test_bm_base", "-o", "x", "--lsmio-durability", "fsync"}),
                exitedNonZero, "fsync");
}

namespace {

// The child ran the whole beginMain, which calls InitGoogleLogging a second time (the test
// main already ran initLSMIODebug), so it shuts glog down first.
void runAcceptedDurability(const std::string &f_value, lsmio::Durability f_expected) {
    google::ShutdownGoogleLogging();
    runBeginMain({"test_bm_base", "-o", "x", "--lsmio-durability", f_value});
    exit(lsmio::gConfigLSMIO.durability == f_expected ? 0 : 3);
}

}  // namespace

TEST(BMBaseCliTest, DurabilityPageCacheIsAccepted) {
    ASSERT_EXIT(runAcceptedDurability("page-cache", lsmio::Durability::PageCache),
                ::testing::ExitedWithCode(0), "");
}

TEST(BMBaseCliTest, DurabilityValueIsCaseInsensitive) {
    ASSERT_EXIT(runAcceptedDurability("PAGE-CACHE", lsmio::Durability::PageCache),
                ::testing::ExitedWithCode(0), "");
}

TEST(BMBaseCliTest, DurabilityEngineIsAccepted) {
    ASSERT_EXIT(runAcceptedDurability("engine", lsmio::Durability::Engine),
                ::testing::ExitedWithCode(0), "");
}

TEST(BMBasePhaseTest, BothSidesRecordedGiveTwoExactLines) {
    IterationPhases phases{};
    phases.iteration = 3;
    phases.bytes = 1048576.0;
    phases.side_recorded[static_cast<int>(PhaseSide::Write)] = true;
    phases.side_recorded[static_cast<int>(PhaseSide::Read)] = true;
    int64_t value = 10;
    for (int side = 0; side < 2; side++) {
        for (int boundary = 0; boundary < 5; boundary++) {
            phases.offset_us[side][boundary] = value;
            value += 10;
        }
    }
    EXPECT_EQ(formatPhaseRows(phases),
              "phase,write,3,1048576,10,20,30,40,50\n"
              "phase,read,3,1048576,60,70,80,90,100\n");
}

TEST(BMBasePhaseTest, OnlyWriteRecordedGivesOneWriteLine) {
    IterationPhases phases{};
    phases.iteration = 0;
    phases.bytes = 4096.0;
    phases.side_recorded[static_cast<int>(PhaseSide::Write)] = true;
    phases.offset_us[static_cast<int>(PhaseSide::Write)][static_cast<int>(PhaseBoundary::AfterDelete)] = 7;
    // The read offsets are set but the side is not recorded: no read row.
    phases.offset_us[static_cast<int>(PhaseSide::Read)][static_cast<int>(PhaseBoundary::AfterOpen)] = 99;
    EXPECT_EQ(formatPhaseRows(phases), "phase,write,0,4096,0,0,0,0,7\n");
}

TEST(BMBasePhaseTest, OnlyReadRecordedGivesOneReadLine) {
    IterationPhases phases{};
    phases.iteration = 1;
    phases.bytes = 8.0;
    phases.side_recorded[static_cast<int>(PhaseSide::Read)] = true;
    phases.offset_us[static_cast<int>(PhaseSide::Read)][static_cast<int>(PhaseBoundary::BeforeOpen)] = 5;
    EXPECT_EQ(formatPhaseRows(phases), "phase,read,1,8,5,0,0,0,0\n");
}

TEST(BMBasePhaseTest, NeitherSideRecordedGivesEmptyString) {
    IterationPhases phases{};
    phases.iteration = 2;
    phases.bytes = 100.0;
    phases.offset_us[0][0] = 5;
    EXPECT_EQ(formatPhaseRows(phases), "");
}

TEST(BMBasePhaseTest, BytesPrintAsIntegerWithoutDecimalPoint) {
    IterationPhases phases{};
    phases.bytes = 2147352576.0;
    phases.side_recorded[static_cast<int>(PhaseSide::Write)] = true;
    EXPECT_EQ(formatPhaseRows(phases), "phase,write,0,2147352576,0,0,0,0,0\n");
    // Above the 32-bit range the value still prints in full.
    phases.bytes = 4294967296.0 * 4.0;
    EXPECT_EQ(formatPhaseRows(phases), "phase,write,0,17179869184,0,0,0,0,0\n");
}

TEST(BMBasePhaseTest, OffsetsPrintAsIntegers) {
    IterationPhases phases{};
    phases.iteration = 4;
    phases.bytes = 1.0;
    phases.side_recorded[static_cast<int>(PhaseSide::Read)] = true;
    phases.offset_us[static_cast<int>(PhaseSide::Read)][static_cast<int>(PhaseBoundary::BeforeOpen)] = 0;
    phases.offset_us[static_cast<int>(PhaseSide::Read)][static_cast<int>(PhaseBoundary::AfterOpen)] = 1;
    phases.offset_us[static_cast<int>(PhaseSide::Read)][static_cast<int>(PhaseBoundary::BeforeClose)] =
        3000000000LL;
    phases.offset_us[static_cast<int>(PhaseSide::Read)][static_cast<int>(PhaseBoundary::AfterClose)] =
        9007199254740993LL;
    phases.offset_us[static_cast<int>(PhaseSide::Read)][static_cast<int>(PhaseBoundary::AfterDelete)] = -1;
    EXPECT_EQ(formatPhaseRows(phases), "phase,read,4,1,0,1,3000000000,9007199254740993,-1\n");
}

TEST(BMBaseKeyPermutationTest, ResultIsAPermutationOfZeroToCountMinusOne) {
    const int ranks[] = {0, 1, 7, 63};
    const int iterations[] = {0, 1, 9};
    const int counts[] = {1, 2, 16, 1000};
    for (int rank : ranks) {
        for (int iteration : iterations) {
            for (int count : counts) {
                std::vector<int> keys = keyPermutation(rank, iteration, count);
                ASSERT_EQ(keys.size(), static_cast<size_t>(count));
                std::vector<int> sorted = keys;
                std::sort(sorted.begin(), sorted.end());
                for (int i = 0; i < count; i++) {
                    ASSERT_EQ(sorted[i], i) << "rank " << rank << " iteration " << iteration << " count " << count;
                }
            }
        }
    }
}

TEST(BMBaseKeyPermutationTest, SameArgumentsGiveEqualResults) {
    EXPECT_EQ(keyPermutation(3, 2, 64), keyPermutation(3, 2, 64));
    EXPECT_EQ(keyPermutation(0, 0, 1000), keyPermutation(0, 0, 1000));
}

TEST(BMBaseKeyPermutationTest, DifferentRanksOrIterationsGiveDifferentResults) {
    EXPECT_NE(keyPermutation(0, 0, 16), keyPermutation(1, 0, 16));
    EXPECT_NE(keyPermutation(0, 0, 16), keyPermutation(0, 1, 16));
}

TEST(BMBaseKeyPermutationTest, ZeroCountGivesEmptyVector) {
    EXPECT_TRUE(keyPermutation(2, 5, 0).empty());
}

TEST(BMBaseKeyPermutationTest, NegativeCountThrowsInvalidArgument) {
    EXPECT_THROW(keyPermutation(0, 0, -1), std::invalid_argument);
}

namespace {

// The T2 properties that hold for every placement: the sources are a bijection on the world ranks,
// the sink is the inverse of the source, and the source is on another node exactly when the
// reader's local index exists on two or more nodes (self otherwise). With f_equal_nodes (every node
// holds the same ranks per node, as under cyclic and block placement) the source's node is also the
// next node id, wrapping.
void expectReadShiftProperties(const std::vector<int> &f_node_ids, bool f_equal_nodes) {
    const std::vector<ReadShiftPeers> peers = mapReadShift(f_node_ids);
    const size_t size = f_node_ids.size();
    ASSERT_EQ(peers.size(), size);

    std::vector<int> local_index(size);
    std::map<int, int> seen_on_node;
    std::map<int, std::set<int>> nodes_of_local_index;
    for (size_t r = 0; r < size; r++) {
        local_index[r] = seen_on_node[f_node_ids[r]]++;
        nodes_of_local_index[local_index[r]].insert(f_node_ids[r]);
    }
    std::set<int> distinct_nodes(f_node_ids.begin(), f_node_ids.end());
    std::vector<int> node_order(distinct_nodes.begin(), distinct_nodes.end());

    std::set<int> sources;
    for (size_t r = 0; r < size; r++) {
        const int source = peers[r].source_world_rank;
        ASSERT_GE(source, 0);
        ASSERT_LT(source, static_cast<int>(size));
        sources.insert(source);
        EXPECT_EQ(peers[static_cast<size_t>(source)].sink_world_rank, static_cast<int>(r)) << "rank " << r;
        EXPECT_EQ(peers[static_cast<size_t>(peers[r].sink_world_rank)].source_world_rank, static_cast<int>(r))
            << "rank " << r;
        EXPECT_EQ(local_index[static_cast<size_t>(source)], local_index[r]) << "rank " << r;
        if (nodes_of_local_index[local_index[r]].size() >= 2) {
            EXPECT_NE(f_node_ids[static_cast<size_t>(source)], f_node_ids[r]) << "rank " << r;
        } else {
            EXPECT_EQ(source, static_cast<int>(r));
            EXPECT_EQ(peers[r].sink_world_rank, static_cast<int>(r));
        }
        if (f_equal_nodes) {
            const size_t at = static_cast<size_t>(
                std::find(node_order.begin(), node_order.end(), f_node_ids[r]) - node_order.begin());
            EXPECT_EQ(f_node_ids[static_cast<size_t>(source)], node_order[(at + 1) % node_order.size()])
                << "rank " << r;
        }
    }
    EXPECT_EQ(sources.size(), size);
}

std::vector<int> sourcesOf(const std::vector<int> &f_node_ids) {
    std::vector<int> sources;
    for (const ReadShiftPeers &peer : mapReadShift(f_node_ids)) {
        sources.push_back(peer.source_world_rank);
    }
    return sources;
}

}  // namespace

TEST(BMBaseReadShiftMapTest, CyclicPlacementThreeNodesTwoRanks) {
    const std::vector<int> nodes = {0, 1, 2, 0, 1, 2};
    EXPECT_EQ(sourcesOf(nodes), (std::vector<int>{1, 2, 0, 4, 5, 3}));
    expectReadShiftProperties(nodes, true);
}

TEST(BMBaseReadShiftMapTest, BlockPlacementThreeNodesTwoRanksWithLeaderNodeIds) {
    const std::vector<int> nodes = {0, 0, 2, 2, 4, 4};
    EXPECT_EQ(sourcesOf(nodes), (std::vector<int>{2, 3, 4, 5, 0, 1}));
    expectReadShiftProperties(nodes, true);
}

TEST(BMBaseReadShiftMapTest, OneNodeEveryRankReadsItself) {
    const std::vector<int> nodes = {0, 0, 0};
    EXPECT_EQ(sourcesOf(nodes), (std::vector<int>{0, 1, 2}));
    expectReadShiftProperties(nodes, true);
}

TEST(BMBaseReadShiftMapTest, OneRankPerNodeFourNodes) {
    const std::vector<int> nodes = {0, 1, 2, 3};
    EXPECT_EQ(sourcesOf(nodes), (std::vector<int>{1, 2, 3, 0}));
    expectReadShiftProperties(nodes, true);
}

TEST(BMBaseReadShiftMapTest, UnequalRanksPerNode) {
    const std::vector<int> nodes = {0, 0, 0, 3, 3, 5};
    // local index 0 cycles over nodes 0, 3, 5; index 1 over nodes 0, 3; index 2 is on node 0 only
    EXPECT_EQ(sourcesOf(nodes), (std::vector<int>{3, 4, 2, 5, 1, 0}));
    expectReadShiftProperties(nodes, false);
}

TEST(BMBaseReadShiftMapTest, SimulatedNodesRankModThree) {
    const std::vector<int> nodes = {0, 1, 2};
    EXPECT_EQ(sourcesOf(nodes), (std::vector<int>{1, 2, 0}));
    expectReadShiftProperties(nodes, true);
}

TEST(BMBaseReadShiftMapTest, NodeIdsAreNotWorldRanksAndNeedNotBeSorted) {
    // node ids 7 and -2: ordered by node id, -2 comes first, so 7 wraps to -2
    const std::vector<int> nodes = {7, -2, 7, -2};
    EXPECT_EQ(sourcesOf(nodes), (std::vector<int>{1, 0, 3, 2}));
    expectReadShiftProperties(nodes, true);
}

TEST(BMBaseReadShiftMapTest, EmptyInputGivesEmptyResult) {
    EXPECT_TRUE(mapReadShift({}).empty());
}

int main(int argc, char **argv) {
    lsmio::initLSMIODebug(argv[0]);
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
