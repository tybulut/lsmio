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

#include <lsmio/lsmio.hpp>
#include <string>
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
    std::unordered_map<std::string, std::string> kvStore;

    virtual bool doWrite(const std::string key, const std::string value) override {
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
