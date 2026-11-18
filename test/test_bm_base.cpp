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

#include <chrono>
#include <lsmio/lsmio.hpp>
#include <string>
#include <thread>
#include <unordered_map>

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
};

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
}

int main(int argc, char **argv) {
    lsmio::initLSMIODebug(argv[0]);
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
