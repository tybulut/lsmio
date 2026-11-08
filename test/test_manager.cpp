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

#include <adios2/helper/adiosCommDummy.h>
#include <gtest/gtest.h>

#include <atomic>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <lsmio/manager/manager.hpp>
#include <string_view>
#include <thread>
#include <tuple>
#include <vector>

const std::string TEST_DIR_MGR = "";

TEST(lsmioManager, Flush) {
    bool success = true;
    std::string value;

    std::string key1 = "serdar";
    std::string key2 = "leo";
    std::string value1 = "bulut";
    std::string value2 = "alp";

    std::string dbName = "test-mgr-store-flush.db";
    std::string dbPath = TEST_DIR_MGR.empty() ? dbName : TEST_DIR_MGR + "/" + dbName;
    std::filesystem::remove_all(dbPath);

    {
        lsmio::LSMIOManager lm(dbName, TEST_DIR_MGR);
        LOG(INFO) << "Created a test database called: " << lm.getDbPath() << std::endl;

        EXPECT_EQ(lm.getDbPath(), dbPath);

        success = lm.put(key1, value1, true);
        EXPECT_EQ(success, true);

        success = lm.get(key1, &value);
        EXPECT_EQ(success, true);

        LOG(INFO) << "Test value for key1: wrote: " << value1 << std::endl;
        LOG(INFO) << "Test value for key1: read: " << value << std::endl;
        EXPECT_EQ(value, value1);

        success = lm.put(key2, value2, true);
        EXPECT_EQ(success, true);

        success = lm.get(key2, &value);
        EXPECT_EQ(success, true);

        LOG(INFO) << "Test value for key2: wrote: " << value2 << std::endl;
        LOG(INFO) << "Test value for key2: read: " << value << std::endl;
        EXPECT_EQ(value, value2);

        uint64_t rb, wb;
        uint64_t ro, wo;
        lm.getCounters(wb, rb, wo, ro);

        LOG(INFO) << "LSMIOManager::counters: writeB: " << wb << " readB: " << rb << std::endl;
        EXPECT_EQ(rb, (value1.length() + value2.length()));
        EXPECT_EQ(wb, (value1.length() + value2.length()));

        LOG(INFO) << "LSMIOManager::counters: writeO: " << wo << " readO: " << ro << std::endl;
        EXPECT_EQ(ro, 2);
        EXPECT_EQ(wo, 2);

        success = lm.del(key1, false);
        EXPECT_EQ(success, true);

        success = lm.del(key2, false);
        EXPECT_EQ(success, true);
    }

    std::filesystem::remove_all(dbPath);
}

TEST(lsmioManager, Deferred) {
    bool success = true;
    std::string value;

    std::string key1 = "serdar";
    std::string key2 = "bulut";
    std::string value1 = "alpino";
    std::string value2 = "teomos";

    std::string dbName = "test-mgr-store-deferred.db";
    std::string dbPath = TEST_DIR_MGR.empty() ? dbName : TEST_DIR_MGR + "/" + dbName;
    std::filesystem::remove_all(dbPath);

    {
        lsmio::LSMIOManager lm(dbName, TEST_DIR_MGR);
        LOG(INFO) << "Created a test database called: " << lm.getDbPath() << std::endl;
        EXPECT_EQ(lm.getDbPath(), dbPath);

        success = lm.put(key1, value1);
        EXPECT_EQ(success, true);

        success = lm.put(key2, value2.c_str(), value2.length());
        EXPECT_EQ(success, true);

        success = lm.writeBarrier();
        EXPECT_EQ(success, true);

        success = lm.get(key1, &value);
        EXPECT_EQ(success, true);

        LOG(INFO) << "Test value for key1: " << value << std::endl;
        EXPECT_EQ(value, value1);

        success = lm.get(key2, &value);
        EXPECT_EQ(success, true);

        LOG(INFO) << "Test value for key2: " << value << std::endl;
        EXPECT_EQ(value, value2);

        success = lm.del(key1);
        EXPECT_EQ(success, true);

        success = lm.del(key2);
        EXPECT_EQ(success, true);
    }

    std::filesystem::remove_all(dbPath);
}

// The raw-pointer puts and putBytes copy the caller's bytes before they return: the buffers are
// overwritten or freed right after, and the counters count each put once
TEST(lsmioManager, RawPutsCopyCallerBytes) {
    std::string dbName = "test-mgr-store-raw.db";
    std::string dbPath = TEST_DIR_MGR.empty() ? dbName : TEST_DIR_MGR + "/" + dbName;
    std::filesystem::remove_all(dbPath);

    auto expected = [](int i) {
        std::string v(1000 + i, static_cast<char>('a' + i));
        v[10] = '\0';  // binary-safe
        return v;
    };
    {
        lsmio::LSMIOManager lm(dbName, TEST_DIR_MGR);
        lm.resetCounters();
        uint64_t bytes = 0;
        for (int i = 0; i < 12; ++i) {
            const std::string key = "raw" + std::to_string(i);
            const std::string e = expected(i);
            char *buf = new char[e.size()];
            std::memcpy(buf, e.data(), e.size());
            switch (i % 3) {
                case 0:
                    EXPECT_TRUE(lm.put(key, buf, static_cast<std::streamsize>(e.size())));
                    break;
                case 1:
                    EXPECT_TRUE(lm.put(key, static_cast<const void *>(buf), 1, e.size()));
                    break;
                default:
                    EXPECT_TRUE(lm.putBytes(key, std::string_view(buf, e.size()), i % 2 == 0));
                    break;
            }
            std::memset(buf, 'X', e.size());
            delete[] buf;
            bytes += e.size();
        }
        std::string value;
        for (int i = 0; i < 12; ++i) {
            EXPECT_TRUE(lm.get("raw" + std::to_string(i), &value));
            EXPECT_EQ(value, expected(i)) << "key " << i;
        }
        uint64_t rb, wb, ro, wo;
        lm.getCounters(wb, rb, wo, ro);
        EXPECT_EQ(wb, bytes);
        EXPECT_EQ(wo, 12u);
    }
    std::filesystem::remove_all(dbPath);
}

TEST(lsmioManager, ReOpen_Write) {
    bool success = true;
    std::string value;

    std::string key1 = "serdar";
    std::string key2 = "bulut";
    std::string value1 = "alpino";
    std::string value2 = "teomos";

    std::string dbName = "test-mgr-store-rewrite.db";
    std::string dbPath = TEST_DIR_MGR.empty() ? dbName : TEST_DIR_MGR + "/" + dbName;
    std::filesystem::remove_all(dbPath);

    for (int i = 0; i < 2; i++) {
        lsmio::LSMIOManager lm(dbName, TEST_DIR_MGR);
        LOG(INFO) << ((i == 0) ? "Created" : "Opened")
                  << " a RW test database called: " << lm.getDbPath() << std::endl;

        success = lm.put(key1, value1, true);
        EXPECT_EQ(success, true);

        success = lm.put(key2, value2, true);
        EXPECT_EQ(success, true);
    }

    std::filesystem::remove_all(dbPath);
}

TEST(lsmioManager, ReOpen_Read) {
    bool success = true;
    std::string value;

    std::string key1 = "serdar";
    std::string key2 = "bulut";
    std::string value1 = "alpino";
    std::string value2 = "teomos";

    std::string dbName = "test-mgr-store-reread.db";
    std::string dbPath = TEST_DIR_MGR.empty() ? dbName : TEST_DIR_MGR + "/" + dbName;
    std::filesystem::remove_all(dbPath);

    for (int i = 0; i < 2; i++) {
        lsmio::LSMIOManager lm(dbName, TEST_DIR_MGR);
        LOG(INFO) << ((i == 0) ? "Created" : "Opened")
                  << " a RW test database called: " << lm.getDbPath() << std::endl;

        if (i == 0) {
            success = lm.put(key1, value1, true);
            EXPECT_EQ(success, true);

            success = lm.put(key2, value2, true);
            EXPECT_EQ(success, true);
        } else {
            success = lm.get(key1, &value);
            LOG(INFO) << "ReOpen read test value for key1: " << value << std::endl;
            EXPECT_EQ(success, true);

            success = lm.get(key2, &value);
            LOG(INFO) << "ReOpen read test value for key2: " << value << std::endl;
            EXPECT_EQ(success, true);
        }
    }

    std::filesystem::remove_all(dbPath);
}

TEST(lsmioManager, CounterAccountingRvalueAndRawBuffers) {
    std::string dbName = "test-mgr-counters.db";
    std::string dbPath = TEST_DIR_MGR.empty() ? dbName : TEST_DIR_MGR + "/" + dbName;
    std::filesystem::remove_all(dbPath);
    {
        lsmio::LSMIOManager lm(dbName, TEST_DIR_MGR);
        lm.resetCounters();
        uint64_t wb = 0, rb = 0, wo = 0, ro = 0;

        // Rvalue put:
        lm.put("k1", std::string(100, 'x'), true);
        lm.getCounters(wb, rb, wo, ro);
        EXPECT_EQ(wb, 100);
        EXPECT_EQ(wo, 1);

        // Raw buffer char* put:
        const char buf[50] = {0};
        lm.put("k2", buf, 50);
        lm.getCounters(wb, rb, wo, ro);
        EXPECT_EQ(wb, 150);
        EXPECT_EQ(wo, 2);

        // Raw buffer void* put:
        int arr[10] = {0};
        lm.put("k3", arr, sizeof(int), 10);
        lm.getCounters(wb, rb, wo, ro);
        EXPECT_EQ(wb, 150 + sizeof(int) * 10);
        EXPECT_EQ(wo, 3);
    }
    std::filesystem::remove_all(dbPath);
}

// A failed initialize leaves no instance, so a later one can succeed; misuse is refused
TEST(lsmioManager, InitializeLifecycle) {
    std::string blocker = "test-mgr-init-blocker";
    std::ofstream(blocker) << "not a directory";
    std::string dbName = "test-mgr-init.db";
    std::filesystem::remove_all(dbName);

    // The database directory would go under a regular file
    EXPECT_THROW(lsmio::LSMIOManager::initialize(dbName, blocker),
                 std::filesystem::filesystem_error);
    std::filesystem::remove(blocker);
    EXPECT_EQ(lsmio::LSMIOManager::getManager(), nullptr);
    EXPECT_FALSE(lsmio::LSMIOManager::cleanup());

    lsmio::LSMIOManager *lm = lsmio::LSMIOManager::initialize(dbName, TEST_DIR_MGR, true);
    ASSERT_NE(lm, nullptr);
    EXPECT_EQ(lsmio::LSMIOManager::initialize(dbName, TEST_DIR_MGR, true), nullptr);
    EXPECT_EQ(lsmio::LSMIOManager::getManager(), lm);

    EXPECT_TRUE(lsmio::LSMIOManager::cleanup());
    EXPECT_EQ(lsmio::LSMIOManager::getManager(), nullptr);
    EXPECT_FALSE(lsmio::LSMIOManager::cleanup());
    std::filesystem::remove_all(dbName);
}

// Threads that initialize at once: exactly one opens the database
TEST(lsmioManager, ConcurrentInitialize) {
    std::string dbName = "test-mgr-init-race.db";
    std::atomic<bool> go{false};
    std::atomic<int> opened{0};
    std::vector<std::thread> threads;

    for (int i = 0; i < 8; i++) {
        threads.emplace_back([&] {
            while (!go) std::this_thread::yield();
            if (lsmio::LSMIOManager::initialize(dbName, TEST_DIR_MGR, true)) opened++;
        });
    }
    go = true;
    for (auto &thread : threads) thread.join();

    EXPECT_EQ(opened, 1);
    EXPECT_TRUE(lsmio::LSMIOManager::cleanup());
    std::filesystem::remove_all(dbName);
}

// Defined in lib/manager/manager.cpp inside namespace lsmio and declared in no header
namespace lsmio {
void vectorTupleSerialize(const std::vector<std::tuple<std::string, std::string>> &values,
                          std::string &payload);
bool vectorTupleDeserialize(const std::string &payload,
                            std::vector<std::tuple<std::string, std::string>> &values);
}  // namespace lsmio

namespace {

std::string le64(uint64_t f_value) {
    std::string bytes(8, '\0');
    for (size_t i = 0; i < 8; ++i) {
        bytes[i] = static_cast<char>((f_value >> (i * 8)) & 0xFF);
    }
    return bytes;
}

std::string entryBytes(const std::string &f_key, const std::string &f_value) {
    return le64(f_key.size()) + f_key + le64(f_value.size()) + f_value;
}

using KeyValues = std::vector<std::tuple<std::string, std::string>>;

struct StorageCase {
    const char *name;
    lsmio::StorageType storage_type;
};

class LSMIOManagerTest : public ::testing::Test {
  protected:
    lsmio::LSMIOConfig m_backup_config;
    std::vector<std::string> m_paths;

    std::string dbName(const std::string &f_name) {
        std::string path = "test-mgr-cov-" + f_name + ".db";
        std::filesystem::remove_all(path);
        m_paths.push_back(path);
        return path;
    }

    void SetUp() override {
        m_backup_config = lsmio::gConfigLSMIO;
    }

    void TearDown() override {
        lsmio::gConfigLSMIO = m_backup_config;
        for (const auto &path : m_paths) std::filesystem::remove_all(path);
    }
};

class LSMIOManagerBackendTest : public LSMIOManagerTest,
                                public ::testing::WithParamInterface<StorageCase> {};

}  // namespace

TEST(LSMIOManagerHelperTest, LifecycleStateNameCoversEveryState) {
    EXPECT_STREQ(lsmio::lifecycleStateName(lsmio::LifecycleState::None), "None");
    EXPECT_STREQ(lsmio::lifecycleStateName(lsmio::LifecycleState::Initializing), "Initializing");
    EXPECT_STREQ(lsmio::lifecycleStateName(lsmio::LifecycleState::Ready), "Ready");
    EXPECT_STREQ(lsmio::lifecycleStateName(lsmio::LifecycleState::Cleaning), "Cleaning");
    EXPECT_STREQ(lsmio::lifecycleStateName(static_cast<lsmio::LifecycleState>(42)), "Unknown");
}

TEST(LSMIOManagerHelperTest, VectorTupleSerializeRoundTrip) {
    const KeyValues input = {{"k1", "v1"}, {"k2", ""}, {"", "v3"}};
    std::string serialized = "stale";
    lsmio::vectorTupleSerialize(input, serialized);
    EXPECT_EQ(serialized, entryBytes("k1", "v1") + entryBytes("k2", "") + entryBytes("", "v3"));

    KeyValues output;
    EXPECT_TRUE(lsmio::vectorTupleDeserialize(serialized, output));
    EXPECT_EQ(output, input);
}

TEST(LSMIOManagerHelperTest, VectorTupleSerializeEmpty) {
    std::string serialized = "stale";
    lsmio::vectorTupleSerialize(KeyValues{}, serialized);
    EXPECT_EQ(serialized, "");

    KeyValues output;
    EXPECT_TRUE(lsmio::vectorTupleDeserialize("", output));
    EXPECT_TRUE(output.empty());
}

TEST(LSMIOManagerHelperTest, VectorTupleDeserializeAppends) {
    KeyValues output = {{"kept", "first"}};
    std::string serialized;
    lsmio::vectorTupleSerialize({{"a", "1"}, {"b", "2"}}, serialized);
    EXPECT_TRUE(lsmio::vectorTupleDeserialize(serialized, output));
    const KeyValues expected = {{"kept", "first"}, {"a", "1"}, {"b", "2"}};
    EXPECT_EQ(output, expected);
}

TEST(LSMIOManagerHelperTest, VectorTupleRoundTripsDelimitersAndNul) {
    const KeyValues input = {{"a|b", "v"}, {"k", "line1\nline2"}, {std::string("n\0l", 3), std::string(1, '\0')}};
    std::string serialized;
    lsmio::vectorTupleSerialize(input, serialized);
    EXPECT_EQ(serialized, entryBytes("a|b", "v") + entryBytes("k", "line1\nline2") +
                              entryBytes(std::string("n\0l", 3), std::string(1, '\0')));

    KeyValues output;
    EXPECT_TRUE(lsmio::vectorTupleDeserialize(serialized, output));
    EXPECT_EQ(output, input);
}

TEST(LSMIOManagerHelperTest, VectorTupleDeserializeRejectsMalformedPayloads) {
    struct TestCase {
        std::string name;
        std::string payload;
    };
    const std::vector<TestCase> cases = {
        {"cut inside a key length", le64(1).substr(0, 5)},
        {"cut inside a key", le64(5) + "ab"},
        {"cut inside a value length", le64(1) + "a" + std::string(3, '\0')},
        {"cut inside a value", le64(1) + "a" + le64(4) + "xy"},
        {"trailing bytes", entryBytes("a", "1") + "\x01\x02\x03"},
        {"key length near 2^64", le64(UINT64_MAX) + "abc"},
        {"value length near 2^64", le64(1) + "a" + le64(UINT64_MAX - 3) + "abc"},
        {"good entry then cut (all-or-nothing)", entryBytes("a", "1") + le64(9) + "x"},
    };

    for (const auto &tc : cases) {
        SCOPED_TRACE(tc.name);
        KeyValues output = {{"kept", "first"}};
        EXPECT_FALSE(lsmio::vectorTupleDeserialize(tc.payload, output));
        const KeyValues expected = {{"kept", "first"}};
        EXPECT_EQ(output, expected);
    }
}

TEST_F(LSMIOManagerTest, AdiosCommWithoutMpiThrows) {
    const std::string db_name = dbName("adios-dummy");
    adios2::helper::Comm comm = adios2::helper::CommDummy();
    ASSERT_FALSE(comm.IsMPI());
    EXPECT_THROW(lsmio::LSMIOManager(db_name, "", false, &comm), std::invalid_argument);
    EXPECT_FALSE(std::filesystem::exists(db_name));
}

TEST_P(LSMIOManagerBackendTest, OpensAndRoundTrips) {
    const StorageCase &c = GetParam();
    lsmio::gConfigLSMIO.storageType = c.storage_type;
    const std::string db_name = dbName(std::string("backend-") + c.name);
    {
        lsmio::LSMIOManager lm(db_name);
        EXPECT_EQ(lm.getDbPath(), db_name);
        EXPECT_TRUE(lm.put("bk", std::string("bv"), true));
        EXPECT_TRUE(lm.metaPut("mk", "mv", true));
        std::string value;
        EXPECT_TRUE(lm.get("bk", &value));
        EXPECT_EQ(value, "bv");
        EXPECT_TRUE(lm.metaGet("mk", &value));
        EXPECT_EQ(value, "mv");
        EXPECT_TRUE(lm.close());
    }
    EXPECT_TRUE(std::filesystem::is_directory(db_name));
    {
        lsmio::LSMIOManager lm(db_name);
        std::string value;
        EXPECT_TRUE(lm.get("bk", &value));
        EXPECT_EQ(value, "bv");
    }
}

INSTANTIATE_TEST_SUITE_P(Backends, LSMIOManagerBackendTest,
                         ::testing::Values(StorageCase{"RocksDB", lsmio::StorageType::RocksDB},
                                           StorageCase{"LevelDB", lsmio::StorageType::LevelDB}),
                         [](const ::testing::TestParamInfo<StorageCase> &f_info) {
                             return std::string(f_info.param.name);
                         });

TEST_F(LSMIOManagerTest, UnknownStorageTypeIsRefused) {
    lsmio::gConfigLSMIO.storageType = static_cast<lsmio::StorageType>(42);
    const std::string db_name = dbName("unknown-storage");
    EXPECT_THROW(lsmio::LSMIOManager lm(db_name), std::invalid_argument);
    EXPECT_FALSE(std::filesystem::exists(db_name));
}

TEST_F(LSMIOManagerTest, UnknownStorageTypeIsRefusedBeforeAdiosComm) {
    lsmio::gConfigLSMIO.storageType = static_cast<lsmio::StorageType>(42);
    const std::string db_name = dbName("unknown-storage-adios");
    adios2::helper::Comm comm = adios2::helper::CommDummy();
    try {
        lsmio::LSMIOManager lm(db_name, "", false, &comm);
        FAIL() << "expected std::invalid_argument";
    } catch (const std::invalid_argument &e) {
        EXPECT_NE(std::string(e.what()).find("storageType"), std::string::npos);
    }
    EXPECT_FALSE(std::filesystem::exists(db_name));
}

TEST_F(LSMIOManagerTest, RvaluePutUsesAlwaysFlush) {
    lsmio::gConfigLSMIO.alwaysFlush = true;
    const std::string db_name = dbName("rvalue-default");
    lsmio::LSMIOManager lm(db_name);
    lm.resetCounters();
    EXPECT_TRUE(lm.put("rk", std::string("rvalue")));
    uint64_t wb = 0, rb = 0, wo = 0, ro = 0;
    lm.getCounters(wb, rb, wo, ro);
    EXPECT_EQ(wb, 6u);
    EXPECT_EQ(wo, 1u);
    std::string value;
    EXPECT_TRUE(lm.get("rk", &value));
    EXPECT_EQ(value, "rvalue");
}

TEST_F(LSMIOManagerTest, RejectedWritesReturnFalse) {
    const std::string db_name = dbName("rejected");
    lsmio::LSMIOManager lm(db_name);
    lm.resetCounters();
    const std::string long_key(lsmio::gConfigLSMIO.maxKeyLen + 1, 'k');
    uint64_t wb = 0, rb = 0, wo = 0, ro = 0;

    // A negative length is refused before anything is counted
    EXPECT_FALSE(lm.put("neg", "abc", static_cast<std::streamsize>(-1)));
    lm.getCounters(wb, rb, wo, ro);
    EXPECT_EQ(wo, 0u);
    EXPECT_EQ(wb, 0u);

    // The store refuses an over-long key; the manager has already counted the write
    EXPECT_FALSE(lm.put(long_key, std::string("v"), true));
    lm.getCounters(wb, rb, wo, ro);
    EXPECT_EQ(wo, 1u);
    EXPECT_EQ(wb, 1u);

    std::string value;
    EXPECT_FALSE(lm.get("neg", &value));
    EXPECT_TRUE(lm.put("ok", std::string("fine"), true));
    EXPECT_TRUE(lm.get("ok", &value));
    EXPECT_EQ(value, "fine");
}

TEST_F(LSMIOManagerTest, MetaGetAllAndReadBarrierLocal) {
    const std::string db_name = dbName("meta-all");
    lsmio::LSMIOManager lm(db_name);
    EXPECT_TRUE(lm.metaPut("a1", "x", true));
    EXPECT_TRUE(lm.metaPut("a2", "yy", true));
    EXPECT_TRUE(lm.metaPut("b1", "z", true));
    EXPECT_TRUE(lm.readBarrier());
    lm.resetCounters();

    KeyValues values;
    EXPECT_TRUE(lm.metaGetAll(&values, "a"));
    const KeyValues expected = {{"__lsmio_md::a1", "x"}, {"__lsmio_md::a2", "yy"}};
    EXPECT_EQ(values, expected);
    uint64_t wb = 0, rb = 0, wo = 0, ro = 0;
    lm.getCounters(wb, rb, wo, ro);
    EXPECT_EQ(ro, 1u);
    // Read bytes count value bytes, as get and metaGet do
    EXPECT_EQ(rb, 3u);

    KeyValues all;
    EXPECT_TRUE(lm.metaGetAll(&all));
    EXPECT_EQ(all.size(), 3u);
}

TEST_F(LSMIOManagerTest, MetaGetAllCountsOnlyAppendedValueBytes) {
    const std::string db_name = dbName("meta-prefilled");
    lsmio::LSMIOManager lm(db_name);
    EXPECT_TRUE(lm.metaPut("a1", "xyz", true));
    EXPECT_TRUE(lm.metaPut("a2", "vw", true));
    EXPECT_TRUE(lm.readBarrier());
    lm.resetCounters();

    KeyValues values = {{"pre", "12345"}};
    EXPECT_TRUE(lm.metaGetAll(&values, "a"));
    EXPECT_EQ(values.size(), 3u);
    EXPECT_EQ(values[0], std::make_tuple(std::string("pre"), std::string("12345")));
    uint64_t wb = 0, rb = 0, wo = 0, ro = 0;
    lm.getCounters(wb, rb, wo, ro);
    EXPECT_EQ(rb, 5u);
    EXPECT_EQ(ro, 1u);
}

TEST_F(LSMIOManagerTest, CallbackForCollectiveIOServesEveryCommand) {
    const std::string db_name = dbName("callback");
    lsmio::LSMIOManager lm(db_name);
    std::string value;

    EXPECT_TRUE(lm.callbackForCollectiveIO(1, lsmio::KV_CMD::PUT, "ck", &value, "cv"));
    EXPECT_TRUE(lm.callbackForCollectiveIO(1, lsmio::KV_CMD::WRITE_BARRIER, lsmio::KV_DUMMY, &value,
                                           lsmio::KV_DUMMY));
    // Not serving (no MPI group): the rank is not prefixed, so the key is the caller's key
    EXPECT_TRUE(lm.get("ck", &value));
    EXPECT_EQ(value, "cv");
    value.clear();
    EXPECT_TRUE(lm.callbackForCollectiveIO(1, lsmio::KV_CMD::GET, "ck", &value, ""));
    EXPECT_EQ(value, "cv");

    EXPECT_TRUE(lm.callbackForCollectiveIO(1, lsmio::KV_CMD::META_PUT, "1::m1", &value, "mv1"));
    EXPECT_TRUE(lm.callbackForCollectiveIO(1, lsmio::KV_CMD::META_PUT, "plain", &value, "mv2"));
    value.clear();
    EXPECT_TRUE(lm.callbackForCollectiveIO(1, lsmio::KV_CMD::META_GET, "plain", &value, ""));
    EXPECT_EQ(value, "mv2");

    // META_GET_ALL looks for the "<rank>::" infix, so only the key written with it is returned
    value = "stale";
    EXPECT_TRUE(
        lm.callbackForCollectiveIO(1, lsmio::KV_CMD::META_GET_ALL, lsmio::KV_DUMMY, &value, ""));
    EXPECT_EQ(value, entryBytes("__lsmio_md::1::m1", "mv1"));

    EXPECT_TRUE(lm.callbackForCollectiveIO(1, lsmio::KV_CMD::DEL, "ck", &value, ""));
    EXPECT_TRUE(lm.writeBarrier());
    EXPECT_FALSE(lm.get("ck", &value));

    // A failed read is not a write failure; an unknown command is refused
    EXPECT_FALSE(lm.callbackForCollectiveIO(1, lsmio::KV_CMD::GET, "missing", &value, ""));
    EXPECT_FALSE(lm.callbackForCollectiveIO(1, "BOGUS", "ck", &value, ""));
}

TEST_F(LSMIOManagerTest, CallbackForCollectiveIOReportsFailedWrites) {
    const std::string db_name = dbName("callback-fail");
    lsmio::LSMIOManager lm(db_name);
    std::string value;
    const std::string long_key(lsmio::gConfigLSMIO.maxKeyLen + 1, 'k');

    // The first failed write sets the collective failure flag and logs the failure. Later failed
    // writes find the flag set and do not log again, and a failed read neither logs nor sets it.
    // The flag itself is read only by a serve-local close(), which this single-process test cannot
    // reach, so the test observes it through the one-time log line.
    testing::internal::CaptureStderr();
    EXPECT_FALSE(lm.callbackForCollectiveIO(0, lsmio::KV_CMD::GET, "absent", &value, ""));
    EXPECT_FALSE(lm.callbackForCollectiveIO(0, lsmio::KV_CMD::PUT, long_key, &value, "v"));
    EXPECT_FALSE(lm.callbackForCollectiveIO(0, lsmio::KV_CMD::META_PUT, long_key, &value, "v"));
    const std::string err = testing::internal::GetCapturedStderr();

    const std::string needle = " failed for rank ";
    size_t count = 0;
    for (size_t pos = err.find(needle); pos != std::string::npos;
         pos = err.find(needle, pos + needle.size())) {
        ++count;
    }
    EXPECT_EQ(count, 1u) << err;
    // The first write logs (KV_CMD::PUT is "put", KV_CMD::META_PUT is "metaPut")
    EXPECT_NE(err.find("LSMIOManager::callbackForCollectiveIO: " + lsmio::KV_CMD::PUT +
                       " failed for rank 0"),
              std::string::npos)
        << err;
    EXPECT_EQ(err.find("LSMIOManager::callbackForCollectiveIO: " + lsmio::KV_CMD::META_PUT +
                       " failed for rank"),
              std::string::npos)
        << err;
    EXPECT_EQ(err.find("LSMIOManager::callbackForCollectiveIO: " + lsmio::KV_CMD::GET +
                       " failed for rank"),
              std::string::npos)
        << err;

    EXPECT_FALSE(lm.get(long_key, &value));
    // The local store is unaffected
    EXPECT_TRUE(lm.callbackForCollectiveIO(0, lsmio::KV_CMD::PUT, "good", &value, "g"));
    EXPECT_TRUE(lm.writeBarrier());
    EXPECT_TRUE(lm.get("good", &value));
    EXPECT_EQ(value, "g");
}

int main(int argc, char **argv) {
    lsmio::initLSMIODebug(argv[0]);
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
