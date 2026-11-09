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

#include <atomic>
#include <filesystem>
#include <fstream>
#include <ios>
#include <iostream>
#include <lsmio/posix/posix.hpp>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

const std::string TEST_DIR_PSX = "";

TEST(lsmioPosix, Stream) {
    std::string value;

    const char *file1 = "serdar";
    const char *file2 = "bulut";
    std::string value1 = "alpino";
    std::string value2 = "teomos";

    std::string dbName = "test-psx-store-stream.db";
    std::string dbPath = TEST_DIR_PSX.empty() ? dbName : TEST_DIR_PSX + "/" + dbName;

    EXPECT_TRUE(lsmio::LSMIOStream::initialize(dbName, TEST_DIR_PSX));
    LOG(INFO) << "Created a test database called: " << dbName << std::endl;

    lsmio::LSMIOStream ls1;
    ls1.open(file1);
    ls1.write(value1.c_str(), value1.size());

    lsmio::LSMIOStream ls2(file2);
    ls2.write(value2.c_str(), value2.size());

    EXPECT_TRUE(lsmio::LSMIOStream::writeBarrier());

    std::vector<char> rVal1(value1.size());
    std::vector<char> rVal2(value2.size());

    ls1.seekp(0);
    ls1.read(rVal1.data(), value1.size());
    value.assign(rVal1.data(), value1.size());

    LOG(INFO) << "Test value for file1: " << value << std::endl;
    EXPECT_EQ(value, value1);

    ls2.seekp(0);
    ls2.read(rVal2.data(), value2.size());
    value.assign(rVal2.data(), value2.size());

    LOG(INFO) << "Test value for file2: " << value << std::endl;
    EXPECT_EQ(value, value2);

    EXPECT_TRUE(lsmio::LSMIOStream::cleanup());
}

// A failed initialize throws and leaves the stream uninitialised, so a later one can succeed
TEST(lsmioPosix, StreamInitializeFailure) {
    std::string blocker = "test-psx-init-blocker";
    std::ofstream(blocker) << "not a directory";
    std::string dbName = "test-psx-init.db";

    // The database directory would go under a regular file
    EXPECT_THROW(lsmio::LSMIOStream::initialize(dbName, blocker),
                 std::filesystem::filesystem_error);
    EXPECT_FALSE(lsmio::LSMIOStream::cleanup());

    EXPECT_TRUE(lsmio::LSMIOStream::initialize(dbName, TEST_DIR_PSX));
    EXPECT_TRUE(lsmio::LSMIOStream::cleanup());
    std::filesystem::remove(blocker);
    std::filesystem::remove_all(dbName);
}

// Threads that initialize at once: exactly one opens the database
TEST(lsmioPosix, StreamConcurrentInitialize) {
    std::string dbName = "test-psx-init-race.db";
    std::atomic<bool> go{false};
    std::atomic<int> opened{0};
    std::vector<std::thread> threads;

    for (int i = 0; i < 8; i++) {
        threads.emplace_back([&] {
            while (!go) std::this_thread::yield();
            if (lsmio::LSMIOStream::initialize(dbName, TEST_DIR_PSX)) opened++;
        });
    }
    go = true;
    for (auto &thread : threads) thread.join();

    EXPECT_EQ(opened, 1);
    EXPECT_TRUE(lsmio::LSMIOStream::cleanup());
    EXPECT_FALSE(lsmio::LSMIOStream::cleanup());
    std::filesystem::remove_all(dbName);
}

TEST(lsmioPosix, StreamMulti) {
    bool success = true;
    std::string value;

    const char *file1 = "serdarM";
    std::string value1 = "alpinoM";
    std::string value2 = "teomosM";

    std::string dbName = "test-psx-store-multi.db";
    std::string dbPath = TEST_DIR_PSX.empty() ? dbName : TEST_DIR_PSX + "/" + dbName;

    EXPECT_TRUE(lsmio::LSMIOStream::initialize(dbName, TEST_DIR_PSX));
    LOG(INFO) << "Created a test database called: " << dbName << std::endl;

    lsmio::LSMIOStream ls1;
    ls1.open(file1);
    ls1.write(value1.c_str(), value1.size());
    ls1.write(value2);

    EXPECT_TRUE(lsmio::LSMIOStream::writeBarrier());

    std::vector<char> rVal1(value1.size());
    std::vector<char> rVal2(value2.size());

    ls1.seekp(0);
    ls1.read(rVal1.data(), value1.size());
    value.assign(rVal1.data(), value1.size());

    LOG(INFO) << "Test value for file1: " << value << std::endl;
    EXPECT_EQ(value, value1);

    ls1.read(rVal2.data(), value2.size());
    value.assign(rVal2.data(), value2.size());

    LOG(INFO) << "Test value for file1: " << value << std::endl;
    EXPECT_EQ(value, value2);

    EXPECT_TRUE(lsmio::LSMIOStream::cleanup());
}

class LSMIOPosixStreamTest : public ::testing::Test {
  protected:
    // One database directory per test. Each test runs as its own ctest process and ctest -j runs
    // them at once, so a shared name would let one test remove another test's database.
    std::string m_db_name;
    lsmio::LSMIOConfig m_backup_config;

    void SetUp() override {
        const ::testing::TestInfo *const test_info =
            ::testing::UnitTest::GetInstance()->current_test_info();
        m_db_name = std::string("test-psx-cov-") + test_info->name() + ".db";

        m_backup_config = lsmio::gConfigLSMIO;
        std::filesystem::remove_all(m_db_name);
    }
    void TearDown() override {
        lsmio::LSMIOStream::cleanup();  // false (and harmless) when the test did not initialize
        lsmio::gConfigLSMIO = m_backup_config;
        std::filesystem::remove_all(m_db_name);
    }
};

TEST_F(LSMIOPosixStreamTest, ReopenKeepsOffset) {
    lsmio::LSMIOStream ls;
    ls.open("psx-open-keep");
    EXPECT_EQ(ls.tellp(), 0);
    ls.seekp(5);
    ls.open("psx-open-keep");
    EXPECT_EQ(ls.tellp(), 5);
    lsmio::LSMIOStream other("psx-open-keep");
    EXPECT_EQ(other.tellp(), 5);
}

TEST_F(LSMIOPosixStreamTest, OpenTruncResetsOffset) {
    lsmio::LSMIOStream ls("psx-open-trunc");
    ls.seekp(9);
    ASSERT_EQ(ls.tellp(), 9);
    ls.open("psx-open-trunc", std::ios::trunc);
    EXPECT_EQ(ls.tellp(), 0);
}

TEST_F(LSMIOPosixStreamTest, OpenOutTruncResetsOffset) {
    lsmio::LSMIOStream ls("psx-open-outtrunc");
    ls.seekp(9);
    ls.open("psx-open-outtrunc", std::ios::out | std::ios::trunc);
    EXPECT_EQ(ls.tellp(), 0);
}

TEST_F(LSMIOPosixStreamTest, CloseFlushAndRdbuf) {
    lsmio::LSMIOStream ls("psx-close");
    ls.seekp(4);
    EXPECT_EQ(&ls.flush(), &ls);
    EXPECT_EQ(ls.tellp(), 4);
    std::streambuf *buf = ls.rdbuf();
    ASSERT_NE(buf, nullptr);
    EXPECT_EQ(ls.rdbuf(), buf);
    EXPECT_FALSE(static_cast<std::filebuf *>(buf)->is_open());
    ls.close();
    EXPECT_EQ(ls.tellp(), 0);
}

TEST_F(LSMIOPosixStreamTest, GoodAndFailFollowLifecycle) {
    lsmio::LSMIOStream ls;
    EXPECT_FALSE(ls.good());
    EXPECT_TRUE(ls.fail());
    ASSERT_TRUE(lsmio::LSMIOStream::initialize(m_db_name));
    EXPECT_TRUE(ls.good());
    EXPECT_FALSE(ls.fail());
    ASSERT_TRUE(lsmio::LSMIOStream::cleanup());
    EXPECT_FALSE(ls.good());
    EXPECT_TRUE(ls.fail());
}

TEST_F(LSMIOPosixStreamTest, UninitializedOperationsThrow) {
    lsmio::LSMIOStream ls("psx-uninit");
    char buf[4] = {0};
    EXPECT_THROW(ls.read(buf, 4), std::invalid_argument);
    EXPECT_THROW(ls.write(std::string("abcd")), std::invalid_argument);
    EXPECT_THROW(ls.write("abcd", 4), std::invalid_argument);
    EXPECT_THROW(lsmio::LSMIOStream::writeBarrier(), std::invalid_argument);
    try {
        lsmio::LSMIOStream::writeBarrier();
    } catch (const std::invalid_argument &e) {
        EXPECT_NE(std::string(e.what()).find("LSMIOStream::writeBarrier"), std::string::npos);
    }
    EXPECT_EQ(ls.tellp(), 0);
}

TEST_F(LSMIOPosixStreamTest, ReadWrongLengthThrows) {
    ASSERT_TRUE(lsmio::LSMIOStream::initialize(m_db_name));
    lsmio::LSMIOStream ls("psx-read-len");
    ls.write(std::string("abc"));
    EXPECT_EQ(ls.tellp(), 3);
    // The manager's barrier succeeds here. The discarded result is tested by
    // WriteBarrierReportsFailedManagerBarrier.
    EXPECT_TRUE(lsmio::LSMIOStream::writeBarrier());
    ls.seekp(0);
    char buf[5] = {0};
    EXPECT_THROW(ls.read(buf, 5), std::invalid_argument);
    EXPECT_EQ(ls.tellp(), 0);
    ls.read(buf, 3);
    EXPECT_EQ(std::string(buf, 3), "abc");
    EXPECT_EQ(ls.tellp(), 3);
}

// The barrier's flush writes an SSTable into the DB directory. The posix path opens the native
// store with a zero-size file pool, so the flush creates that file on demand; with the directory
// removed the create fails, the store fails, and LSMIOManager::writeBarrier() returns false.
// LSMIOStream::writeBarrier returns that result. filePoolSize = 0 is a guard for the same setup.
TEST_F(LSMIOPosixStreamTest, WriteBarrierReportsFailedManagerBarrier) {
    lsmio::gConfigLSMIO.storageType = lsmio::StorageType::NativeDB;
    lsmio::gConfigLSMIO.filePoolSize = 0;
    ASSERT_TRUE(lsmio::LSMIOStream::initialize(m_db_name));
    lsmio::LSMIOStream ls("psx-barrier-fail");
    ls.write(std::string("abc"));
    EXPECT_EQ(ls.tellp(), 3);

    // The flush that the barrier starts now fails, so LSMIOManager::writeBarrier() returns false
    std::filesystem::remove_all(m_db_name);

    EXPECT_FALSE(lsmio::LSMIOStream::writeBarrier());

    // Evidence that the manager's barrier failed, so the pin is not vacuous: a failed store refuses
    // later puts, and posix.cpp turns the refusal into the throw
    EXPECT_THROW(ls.write(std::string("def")), std::ios_base::failure);
    EXPECT_EQ(ls.tellp(), 3);
}

TEST_F(LSMIOPosixStreamTest, WriteRejectedByStoreThrows) {
    lsmio::gConfigLSMIO.maxKeyLen = 64;  // the native store reads it when initialize opens it
    ASSERT_TRUE(lsmio::LSMIOStream::initialize(m_db_name));
    const std::string long_name(100, 'f');
    lsmio::LSMIOStream ls(long_name.c_str());
    EXPECT_THROW(ls.write(std::string("data")), std::ios_base::failure);
    EXPECT_EQ(ls.tellp(), 0);
    lsmio::LSMIOStream ok("psx-short");
    ok.write(std::string("data"));
    EXPECT_EQ(ok.tellp(), 4);
}

TEST_F(LSMIOPosixStreamTest, SeekpOnlyFromBeginning) {
    lsmio::LSMIOStream ls("psx-seek");
    ls.seekp(3);
    EXPECT_THROW(ls.seekp(1, std::ios::end), std::invalid_argument);
    EXPECT_THROW(ls.seekp(1, std::ios::cur), std::invalid_argument);
    EXPECT_EQ(ls.tellp(), 3);
}

TEST_F(LSMIOPosixStreamTest, EmptyWriteAndZeroRead) {
    ASSERT_TRUE(lsmio::LSMIOStream::initialize(m_db_name));
    lsmio::LSMIOStream ls("psx-empty");
    ls.write(std::string());
    EXPECT_EQ(ls.tellp(), 0);
    EXPECT_TRUE(lsmio::LSMIOStream::writeBarrier());
    ls.seekp(0);
    char buf[1] = {'z'};
    ls.read(buf, 0);
    EXPECT_EQ(ls.tellp(), 0);
    EXPECT_EQ(buf[0], 'z');
}

TEST_F(LSMIOPosixStreamTest, ReadOfUnwrittenOffsetThrowsNotFound) {
    ASSERT_TRUE(lsmio::LSMIOStream::initialize(m_db_name));
    lsmio::LSMIOStream ls("psx-never-written");
    char buf[2] = {'y', 'y'};
    EXPECT_THROW(ls.read(buf, 0), std::ios_base::failure);
    EXPECT_EQ(ls.tellp(), 0);
    EXPECT_THROW(ls.read(buf, 2), std::ios_base::failure);
    EXPECT_EQ(ls.tellp(), 0);
    EXPECT_EQ(buf[0], 'y');
    EXPECT_EQ(buf[1], 'y');
    try {
        ls.read(buf, 2);
    } catch (const std::ios_base::failure &e) {
        EXPECT_NE(std::string(e.what()).find("psx-never-written"), std::string::npos);
    }
}

int main(int argc, char **argv) {
    lsmio::initLSMIODebug(argv[0]);
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
