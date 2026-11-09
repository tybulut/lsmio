/*
 * Copyright 2026 Serdar Bulut
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

#include <csignal>
#include <cstdlib>
#include <lsmio/lsmio.hpp>
#include <sstream>
#include <string>
#include <type_traits>
#include <utility>
#include <vector>

// Defined at namespace scope in lib/lsmio.cpp but declared in no header. Read only: it tells
// whether initLSMIODebug ran in this process.
namespace lsmio {
extern bool defaultLogDebug;
}

namespace {

// Detects whether `std::ostream& << const T&` compiles.
template <typename T, typename = void>
struct IsStreamable : std::false_type {};
template <typename T>
struct IsStreamable<
    T, std::void_t<decltype(std::declval<std::ostream &>() << std::declval<const T &>())>>
    : std::true_type {};

// Death-test child bodies: each check failure exits with its own code, success exits 0.
[[noreturn]] void releaseInitChild() {
    char name[] = "test_lsmio_release";
    lsmio::initLSMIORelease(name);
    if (!FLAGS_logtostderr || FLAGS_minloglevel != google::ERROR) std::exit(3);
    if (lsmio::defaultLogDebug) std::exit(4);
    std::exit(0);
}

[[noreturn]] void debugInitThenDefaultChild() {
    char name[] = "test_lsmio_debug";
    lsmio::initLSMIODebug(name);
    if (!lsmio::defaultLogDebug || !FLAGS_logtostderr || FLAGS_minloglevel != google::INFO)
        std::exit(3);
    FLAGS_minloglevel = google::FATAL;
    FLAGS_logtostderr = false;
    lsmio::defaultLSMIOLogging();
    if (!FLAGS_logtostderr || FLAGS_minloglevel != google::INFO) std::exit(4);
    std::exit(0);
}

class LSMIOLoggingTest : public ::testing::Test {
  protected:
    void SetUp() override {
        m_minloglevel = FLAGS_minloglevel;
        m_logtostderr = FLAGS_logtostderr;
    }
    void TearDown() override {
        FLAGS_minloglevel = m_minloglevel;
        FLAGS_logtostderr = m_logtostderr;
    }

  private:
    int m_minloglevel = 0;
    bool m_logtostderr = false;
};

class LSMIOHelperTest : public ::testing::Test {
  protected:
    const std::string m_key = "test_lsmio_flag";
    void TearDown() override {
        lsmio::LSMIOHelper::setFlag(m_key, false);
        lsmio::LSMIOHelper::setFlag("", false);
        lsmio::LSMIOHelper::setFlag(lsmio::LSMIOHelper::FLAG_DUAL, false);
        lsmio::LSMIOHelper::setFlag(lsmio::LSMIOHelper::FLAG_FALLBACK, false);
    }
};

// Streams a value into a fresh stream and returns what it wrote. Checks that the
// shift expression returns the stream it was given.
template <typename T>
std::string streamOne(const T &f_value) {
    std::ostringstream os;
    std::ostream &ret = (os << f_value);
    EXPECT_EQ(&ret, &os);
    return os.str();
}

}  // namespace

using H = lsmio::LSMIOHelper;

// ID 002: logging level helpers (lib/lsmio.cpp L72-88)

TEST_F(LSMIOLoggingTest, IncreaseSetsInfo) {
    FLAGS_minloglevel = google::ERROR;
    FLAGS_logtostderr = false;
    lsmio::increaseLSMIOLogging();
    EXPECT_EQ(FLAGS_minloglevel, google::INFO);
    EXPECT_FALSE(FLAGS_logtostderr);
}

TEST_F(LSMIOLoggingTest, DecreaseSetsWarning) {
    FLAGS_minloglevel = google::INFO;
    FLAGS_logtostderr = false;
    lsmio::decreaseLSMIOLogging();
    EXPECT_EQ(FLAGS_minloglevel, google::WARNING);
    EXPECT_FALSE(FLAGS_logtostderr);
}

TEST_F(LSMIOLoggingTest, DefaultWithoutDebugInitSetsError) {
    ASSERT_FALSE(lsmio::defaultLogDebug);
    FLAGS_minloglevel = google::INFO;
    FLAGS_logtostderr = false;
    lsmio::defaultLSMIOLogging();
    EXPECT_EQ(FLAGS_minloglevel, google::ERROR);
    EXPECT_TRUE(FLAGS_logtostderr);
    EXPECT_FALSE(lsmio::defaultLogDebug);
}

TEST_F(LSMIOLoggingTest, DefaultOverridesIncrease) {
    FLAGS_minloglevel = google::WARNING;
    lsmio::increaseLSMIOLogging();
    EXPECT_EQ(FLAGS_minloglevel, google::INFO);
    lsmio::defaultLSMIOLogging();
    EXPECT_EQ(FLAGS_minloglevel, google::ERROR);
}

// ID 003: LSMIOHelper::getFlag / setFlag (lib/lsmio.cpp L90-107)

TEST_F(LSMIOHelperTest, AbsentFlagIsFalse) {
    EXPECT_FALSE(H::getFlag(m_key));
}

TEST_F(LSMIOHelperTest, SetTrueThenGetIsTrue) {
    H::setFlag(m_key, true);
    EXPECT_TRUE(H::getFlag(m_key));
    H::setFlag(m_key, true);
    EXPECT_TRUE(H::getFlag(m_key));
}

TEST_F(LSMIOHelperTest, SetFalseRemovesPresentFlag) {
    H::setFlag(m_key, true);
    ASSERT_TRUE(H::getFlag(m_key));
    H::setFlag(m_key, false);
    EXPECT_FALSE(H::getFlag(m_key));
    H::setFlag(m_key, true);
    EXPECT_TRUE(H::getFlag(m_key));
}

TEST_F(LSMIOHelperTest, SetFalseOnAbsentFlagIsNoop) {
    H::setFlag(H::FLAG_DUAL, true);
    H::setFlag(m_key, false);
    EXPECT_FALSE(H::getFlag(m_key));
    EXPECT_TRUE(H::getFlag(H::FLAG_DUAL));
}

TEST_F(LSMIOHelperTest, EmptyKeyIsAnOrdinaryKey) {
    EXPECT_FALSE(H::getFlag(""));
    H::setFlag("", true);
    EXPECT_TRUE(H::getFlag(""));
    EXPECT_FALSE(H::getFlag(m_key));
    H::setFlag("", false);
    EXPECT_FALSE(H::getFlag(""));
}

TEST_F(LSMIOHelperTest, FlagConstantsAreDistinct) {
    EXPECT_EQ(H::FLAG_DUAL, "flag_dual");
    EXPECT_EQ(H::FLAG_FALLBACK, "flag_fallback");
    H::setFlag(H::FLAG_DUAL, true);
    EXPECT_TRUE(H::getFlag(H::FLAG_DUAL));
    EXPECT_FALSE(H::getFlag(H::FLAG_FALLBACK));
}

// ID 005: to_string (lib/lsmio.cpp L125-183). Each test is a fixed table of distinct
// enumerators with its expected text, plus one out-of-range value that falls through
// every case.

TEST(LSMIOToStringTest, MPIAggType) {
    const std::vector<std::pair<lsmio::MPIAggType, std::string>> rows = {
        {lsmio::MPIAggType::Shared, "mpiShared"},
        {lsmio::MPIAggType::Entire, "mpiEntire"},
        {lsmio::MPIAggType::EntireSerial, "mpiEntireSerial"},
        {lsmio::MPIAggType::Split, "mpiSplit"},
        {static_cast<lsmio::MPIAggType>(99), ""},
    };
    for (const auto &row : rows) {
        SCOPED_TRACE(row.second);
        EXPECT_EQ(lsmio::to_string(row.first), row.second);
    }
}

TEST(LSMIOToStringTest, StorageType) {
    const std::vector<std::pair<lsmio::StorageType, std::string>> rows = {
        {lsmio::StorageType::NativeDB, "NativeDB"},
        {lsmio::StorageType::LevelDB, "LevelDB"},
        {lsmio::StorageType::RocksDB, "RocksDB"},
        {static_cast<lsmio::StorageType>(99), ""},
    };
    for (const auto &row : rows) {
        SCOPED_TRACE(row.second);
        EXPECT_EQ(lsmio::to_string(row.first), row.second);
    }
}

TEST(LSMIOToStringTest, MemtableType) {
    const std::vector<std::pair<lsmio::MemtableType, std::string>> rows = {
        {lsmio::MemtableType::VectorNoSort, "vector-no-sort"},
        {lsmio::MemtableType::VectorSort, "vector-sort"},
        {lsmio::MemtableType::Map, "map"},
        {lsmio::MemtableType::BTree, "btree"},
        {static_cast<lsmio::MemtableType>(99), ""},
    };
    for (const auto &row : rows) {
        SCOPED_TRACE(row.second);
        EXPECT_EQ(lsmio::to_string(row.first), row.second);
    }
}

// IDs 001 and 004: process-level functions, death tests (suite name ends in DeathTest, so
// gtest runs these first). Each EXPECT_EXIT body runs in a child process.

TEST(LSMIODeathTest, InitReleaseSetsErrorLevel) {
    EXPECT_EXIT(releaseInitChild(), ::testing::ExitedWithCode(0), "");
}

TEST(LSMIODeathTest, InitDebugThenDefaultKeepsInfo) {
    EXPECT_EXIT(debugInitThenDefaultChild(), ::testing::ExitedWithCode(0), "");
}

TEST(LSMIODeathTest, HandlerSIGSEGVPrintsAndExitsFailure) {
    // Regression guard: the handler writes its message with write(2) and exits through
    // _exit(EXIT_FAILURE); the child writes no coverage profile, so the handler's lines are
    // the recorded coverage exception.
    EXPECT_EXIT(lsmio::handlerSIGSEGV(SIGSEGV), ::testing::ExitedWithCode(EXIT_FAILURE),
                "LSMIO caught signal: SIGSEGV\\.");
}

TEST(LSMIODeathTest, HandlerSIGSEGVWritesTraceAfterMessage) {
    EXPECT_EXIT(lsmio::handlerSIGSEGV(SIGSEGV), ::testing::ExitedWithCode(EXIT_FAILURE),
                "LSMIO caught signal: SIGSEGV\\.\n[^\n]*0x[0-9a-fA-F]+");
}

// ID 006: the operator<< overloads (lib/lsmio.cpp)

TEST(LSMIOStreamOperatorTest, StreamsEachEnum) {
    EXPECT_EQ(streamOne(lsmio::MPIAggType::Entire), "mpiEntire");
    EXPECT_EQ(streamOne(lsmio::StorageType::LevelDB), "LevelDB");
    EXPECT_EQ(streamOne(lsmio::MemtableType::VectorSort), "vector-sort");
}

TEST(LSMIOStreamOperatorTest, StreamsConstLvalues) {
    const lsmio::MPIAggType mpi = lsmio::MPIAggType::EntireSerial;
    const lsmio::StorageType storage = lsmio::StorageType::RocksDB;
    const lsmio::MemtableType memtable = lsmio::MemtableType::BTree;
    EXPECT_EQ(streamOne(mpi), "mpiEntireSerial");
    EXPECT_EQ(streamOne(storage), "RocksDB");
    EXPECT_EQ(streamOne(memtable), "btree");
}

TEST(LSMIOStreamOperatorTest, AppendsToExistingContent) {
    const lsmio::MPIAggType shared = lsmio::MPIAggType::Shared;
    std::ostringstream os;
    os << "agg=" << lsmio::MPIAggType::Split << ";" << shared;
    EXPECT_EQ(os.str(), "agg=mpiSplit;mpiShared");
}

TEST(LSMIOStreamOperatorTest, ShiftExpressionCompiles) {
    // The enums stream through operator<< in namespace lsmio, found by ADL.
    EXPECT_TRUE(IsStreamable<lsmio::MPIAggType>::value);
    EXPECT_TRUE(IsStreamable<lsmio::StorageType>::value);
    EXPECT_TRUE(IsStreamable<lsmio::MemtableType>::value);
    EXPECT_TRUE(IsStreamable<int>::value);
}

int main(int argc, char **argv) {
    // No lsmio::initLSMIODebug here: the parent process keeps defaultLogDebug false.
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
