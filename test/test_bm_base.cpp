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
#include <unistd.h>

#include <algorithm>
#include <chrono>
#include <lsmio/lsmio.hpp>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

#include "KeyPermutation.hpp"
#include "PhaseTimeline.hpp"
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
    std::string fillerAtWritePrepare;
    std::string fillerAtReadPrepare;
    std::unordered_map<std::string, std::string> kvStore;
    // Sleep in each write and read, so that a timed phase lasts at least a microsecond and
    // is not skipped by Benchmark::summaryIteration (which ignores zero durations)
    std::chrono::microseconds opDelay{0};

    using BMBase::doWrite;

    bool doWrite(const std::string &key, const std::string &value) override {
        if (opDelay.count() > 0) {
            std::this_thread::sleep_for(opDelay);
        }
        if (failWrite) {
            writeFailureCount++;
            return false;
        }
        kvStore[key] = value;
        return true;
    }

    virtual bool doRead(const std::string key, std::string *value) override {
        if (opDelay.count() > 0) {
            std::this_thread::sleep_for(opDelay);
        }
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
        fillerAtWritePrepare = _filler;
        return 0;
    }

    virtual int writeCleanup() override {
        writeCleanupCalls++;
        return 0;
    }

    virtual int readPrepare(bool opt = false) override {
        readPrepareCalls++;
        fillerAtReadPrepare = _filler;
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
    lsmio::Benchmark &getBenchmark() {
        return _bm;
    }
    int *getRandomKeyIndex() const {
        return pRandomKeyIndex;
    }
    using BMBase::benchIteration;
    using BMBase::makeFiller;
    using BMBase::makeKey;
    using BMBase::makeValue;
    const std::string &getBMPath() const {
        return _lsmioBMPath;
    }
    std::string path(bool f_opt1, bool f_opt2) {
        return genDBPath(f_opt1, f_opt2);
    }
    static void setWorldRank(int f_rank) {
        mpiWorldRank = f_rank;
    }
    const std::string &getPhaseText() const {
        return m_bench_results_phases;
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
        gConfigBM.recordSize = 64;
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

TEST_F(BMBaseTest, EveryRecordIsExactlyRecordSize) {
    MockBM bm;
    // 16 keys: the value header is "0::" to "9::" (3 bytes) or "10::" to "15::" (4 bytes)
    int status = bm.benchSuite("MockRecordSize");
    EXPECT_EQ(status, lsmio::BM_SUCCESS);
    ASSERT_EQ(bm.kvStore.size(), 16u);
    for (const auto &[key, value] : bm.kvStore) {
        EXPECT_EQ(key.size(), 16u) << key;
        EXPECT_EQ(key.size() + value.size(), 64u) << key;
    }
}

TEST_F(BMBaseTest, ReportedBytesAreKeyCountTimesRecordSize) {
    MockBM bm;
    bm.opDelay = std::chrono::microseconds(10);
    // Bandwidth is computed on whole records (key and value), 16 x 64 bytes, not on values
    ASSERT_EQ(bm.benchIteration(0), lsmio::BM_SUCCESS);

    for (const std::string name : {"iwrite", "iread"}) {
        double min = 0, mean = 0, max = 0, totalBytes = 0, totalOps = 0;
        int iterations = 0;
        bm.getBenchmark().summaryIteration(name, min, mean, max, iterations, totalBytes, totalOps);
        EXPECT_EQ(iterations, 1) << name;
        EXPECT_DOUBLE_EQ(totalBytes, 16.0 * 64.0) << name;
        EXPECT_DOUBLE_EQ(totalOps, 16.0) << name;
    }
}

TEST_F(BMBaseTest, KeyAndValueLayout) {
    EXPECT_EQ(MockBM::makeKey(7), "benchmark:000007");
    EXPECT_EQ(MockBM::makeKey(1234567), "benchmark:1234567");

    gConfigBM.recordSize = 24;
    const std::string filler = MockBM::makeFiller();
    EXPECT_EQ(MockBM::makeValue(3, 16, filler), "3::aaaaa");
    EXPECT_EQ(MockBM::makeValue(12, 16, filler), "12::aaaa");
    // A key one byte longer takes that byte from the value
    EXPECT_EQ(MockBM::makeValue(3, 17, filler), "3::aaaa");
    // The record size comes from the filler, not from gConfigBM
    gConfigBM.recordSize = 64;
    EXPECT_EQ(MockBM::makeValue(3, 16, filler), "3::aaaaa");
}

TEST_F(BMBaseTest, FillerIsRecordSizeBytes) {
    gConfigBM.recordSize = 24;
    EXPECT_EQ(MockBM::makeFiller(), std::string(24, 'a'));
    gConfigBM.recordSize = 0;
    EXPECT_EQ(MockBM::makeFiller(), "");
    gConfigBM.recordSize = -5;
    EXPECT_EQ(MockBM::makeFiller(), "");
}

TEST_F(BMBaseTest, FillerIsBuiltBeforeWritePhase) {
    MockBM bm;
    EXPECT_EQ(bm.benchSuite("MockFiller"), lsmio::BM_SUCCESS);
    EXPECT_EQ(bm.fillerAtWritePrepare, std::string(64, 'a'));
    EXPECT_EQ(bm.fillerAtReadPrepare, std::string(64, 'a'));
}

TEST_F(BMBaseTest, ValueIsHeaderAloneBelowMinRecordSize) {
    gConfigBM.recordSize = 18;
    EXPECT_EQ(MockBM::makeValue(12, 16, MockBM::makeFiller()), "12::");
    gConfigBM.recordSize = 0;
    EXPECT_EQ(MockBM::makeValue(12, 16, MockBM::makeFiller()), "12::");
    gConfigBM.recordSize = -5;
    EXPECT_EQ(MockBM::makeValue(12, 16, MockBM::makeFiller()), "12::");
}

TEST(BMBaseRecordSizeTest, MinRecordSizeHoldsLongestKeyAndHeader) {
    // key "benchmark:" + 6 digits, header "<count>::"
    EXPECT_EQ(BMBase::minRecordSize(1), 16 + 3);
    EXPECT_EQ(BMBase::minRecordSize(10), 16 + 3);
    EXPECT_EQ(BMBase::minRecordSize(11), 16 + 4);
    EXPECT_EQ(BMBase::minRecordSize(32768), 16 + 7);
    EXPECT_EQ(BMBase::minRecordSize(1000000), 16 + 8);
    // From 7 index digits on the key grows too
    EXPECT_EQ(BMBase::minRecordSize(1000001), 17 + 9);
    EXPECT_EQ(BMBase::minRecordSize(0), 16 + 3);
}

TEST(BMBaseRecordSizeTest, RecordSizeBelowMinimumIsRejected) {
    char *argv[] = {(char *)"test_bm_base", (char *)"-o", (char *)"mock_test_db",
                    (char *)"--key-count",  (char *)"16", (char *)"--record-size",
                    (char *)"19",           nullptr};
    int argc = 7;

    ASSERT_EXIT(BMBase::beginMain(argc, argv), ::testing::ExitedWithCode(1),
                "Record-size has to be >= 20 for this key-count");
}

TEST(BMBaseRecordSizeTest, RecordSizeAtMinimumIsAccepted) {
    // 20 is the minimum for 16 keys. A later check (transfer size below block size) fails on
    // purpose, so beginMain exits before it sets up logging, and its message shows that the
    // record-size check passed.
    char *argv[] = {(char *)"test_bm_base", (char *)"-o",         (char *)"mock_test_db",
                    (char *)"--key-count",  (char *)"16",         (char *)"--record-size",
                    (char *)"20",           (char *)"--lsmio-bs", (char *)"2048",
                    (char *)"--lsmio-ts",   (char *)"1024",       nullptr};
    int argc = 11;

    ASSERT_EXIT(BMBase::beginMain(argc, argv), ::testing::ExitedWithCode(1),
                "Transfer-size has to be >= block-size");

    // At the minimum, the value of the longest header is that header alone
    gConfigBM.recordSize = 20;
    const std::string filler = MockBM::makeFiller();
    EXPECT_EQ(MockBM::makeValue(15, 16, filler), "15::");
    EXPECT_EQ(MockBM::makeValue(9, 16, filler), "9::a");
}

TEST(BMBaseRecordSizeTest, KeyCountBelowOneIsRejected) {
    char *argv[] = {(char *)"test_bm_base", (char *)"-o", (char *)"mock_test_db",
                    (char *)"--key-count",  (char *)"0",  nullptr};
    int argc = 5;

    ASSERT_EXIT(BMBase::beginMain(argc, argv), ::testing::ExitedWithCode(1),
                "Key-count has to be >= 1");
}

TEST(BMBaseRecordSizeTest, ValueSizeOptionIsGone) {
    char *argv[] = {(char *)"test_bm_base", (char *)"-o", (char *)"mock_test_db",
                    (char *)"--value-size", (char *)"64", nullptr};
    int argc = 5;

    ASSERT_EXIT(
        BMBase::beginMain(argc, argv),
        [](int status) { return WIFEXITED(status) && WEXITSTATUS(status) != 0; }, "");
}

TEST(BMBaseRecordSizeTest, ParameterHeaderPrintsRecordSize) {
    gConfigBM.recordSize = 8388608;
    std::string optStr = genOptionsToString();
    EXPECT_NE(optStr.find("\n recordSize: 8388608"), std::string::npos);
    EXPECT_EQ(optStr.find("valueSize"), std::string::npos);
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
        EXPECT_EQ(w[3], std::to_string(16 * 64));  // keyCount * recordSize, no MPI
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

}  // namespace

TEST(BMBaseCliTest, PerRankPathWithoutMpiBarrierIsRefused) {
    ASSERT_EXIT(runBeginMain({"test_bm_base", "-o", "x", "--per-rank-path"}),
                ::testing::ExitedWithCode(1), "--per-rank-path requires -m/--mpi-barrier");
}

TEST(BMBaseCliTest, PerRankPathWithCollectiveIoIsRefused) {
    ASSERT_EXIT(runBeginMain({"test_bm_base", "-o", "x", "-m", "-c", "--per-rank-path"}),
                ::testing::ExitedWithCode(1),
                "--per-rank-path cannot be combined with -c/--collective-io");
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

int main(int argc, char **argv) {
    lsmio::initLSMIODebug(argv[0]);
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
