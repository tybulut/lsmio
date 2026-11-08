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

#include <algorithm>
#include <atomic>
#include <csignal>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iostream>
#include <iterator>
#include <lsmio/manager/store/store_ldb.hpp>
#include <memory>
#include <string>
#include <string_view>
#include <sys/resource.h>
#include <thread>
#include <tuple>
#include <vector>

const std::string TEST_DIR_LDB = "";

TEST(lsmioLevelDB, Flush) {
    bool success = true;
    std::string value;

    std::string key1 = "serdar";
    std::string key2 = "bulut";
    std::string value1 = "alpino";
    std::string value2 = "teomos";

    std::string dbName = "test-ldb-store-flush.db";
    std::string dbPath = TEST_DIR_LDB.empty() ? dbName : TEST_DIR_LDB + "/" + dbName;

    lsmio::LSMIOStoreLDB lc(dbPath);
    LOG(INFO) << "Created a test database called: " << dbPath << std::endl;

    success = lc.put(key1, value1);
    EXPECT_EQ(success, true);

    success = lc.get(key1, &value);
    EXPECT_EQ(success, true);

    LOG(INFO) << "Test value for key1: " << value << std::endl;
    EXPECT_EQ(value, value1);

    success = lc.put(key2, value2);
    EXPECT_EQ(success, true);

    success = lc.get(key2, &value);
    EXPECT_EQ(success, true);

    LOG(INFO) << "Test value for key2: " << value << std::endl;
    EXPECT_EQ(value, value2);

    success = lc.metaPut(key1, value2);
    EXPECT_EQ(success, true);

    success = lc.metaGet(key1, &value);
    EXPECT_EQ(success, true);

    LOG(INFO) << "Test value for meta-key1: " << value << std::endl;
    EXPECT_EQ(value, value2);

    std::vector<std::tuple<std::string, std::string>> values;
    success = lc.metaGetAll(&values);
    EXPECT_EQ(values.size(), 1);
    for (const auto& [mKey, mValue] : values) {
        EXPECT_EQ(mValue, value2);
    }

    success = lc.del(key1, false);
    EXPECT_EQ(success, true);

    success = lc.del(key2, false);
    EXPECT_EQ(success, true);
}

TEST(lsmioLevelDB, Deferred) {
    bool success = true;
    std::string value;

    std::string key1 = "serdar";
    std::string key2 = "bulut";
    std::string value1 = "alpino";
    std::string value2 = "teomos";

    std::string dbName = "test-ldb-store-deferred.db";
    std::string dbPath = TEST_DIR_LDB.empty() ? dbName : TEST_DIR_LDB + "/" + dbName;

    lsmio::LSMIOStoreLDB lc(dbPath);
    LOG(INFO) << "Created a test database called: " << dbPath << std::endl;

    success = lc.put(key1, value1, false);
    EXPECT_EQ(success, true);

    success = lc.put(key2, value2, false);
    EXPECT_EQ(success, true);

    success = lc.readBarrier();
    EXPECT_EQ(success, true);

    success = lc.get(key1, &value);
    EXPECT_EQ(success, true);

    LOG(INFO) << "Test value for key1: " << value << std::endl;
    EXPECT_EQ(value, value1);

    success = lc.get(key2, &value);
    EXPECT_EQ(success, true);

    LOG(INFO) << "Test value for key2: " << value << std::endl;
    EXPECT_EQ(value, value2);

    success = lc.del(key1);
    EXPECT_EQ(success, true);

    success = lc.del(key2);
    EXPECT_EQ(success, true);

    success = lc.writeBarrier();
    EXPECT_EQ(success, true);
}

// putBytes hands the caller's bytes to LevelDB, which copies them: the caller's buffer can change
// right after, with or without flush (LevelDB batches small values put without flush)
TEST(lsmioLevelDB, PutBytesCopiesCallerBytes) {
    std::string dbName = "test-ldb-store-putbytes.db";
    std::string dbPath = TEST_DIR_LDB.empty() ? dbName : TEST_DIR_LDB + "/" + dbName;
    std::filesystem::remove_all(dbPath);

    auto expected = [](int i) {
        std::string v(i % 2 ? 100 : 4096, static_cast<char>('a' + i % 26));
        v[v.size() / 2] = '\0';  // binary-safe
        return v;
    };
    {
        lsmio::LSMIOStoreLDB lc(dbPath);
        for (int i = 0; i < 16; ++i) {
            const bool flush = (i % 4) < 2;
            const std::string e = expected(i);
            std::vector<char> buf(e.begin(), e.end());
            EXPECT_TRUE(lc.putBytes("key" + std::to_string(i),
                                    std::string_view(buf.data(), buf.size()), flush));
            std::fill(buf.begin(), buf.end(), 'X');
            if (flush) {
                std::string value;
                EXPECT_TRUE(lc.get("key" + std::to_string(i), &value));
                EXPECT_EQ(value, e) << "key " << i;
            }
        }
        EXPECT_TRUE(lc.writeBarrier());
        for (int i = 0; i < 16; ++i) {
            std::string value;
            EXPECT_TRUE(lc.get("key" + std::to_string(i), &value));
            EXPECT_EQ(value, expected(i)) << "key " << i;
        }
        lc.close();
    }
    std::filesystem::remove_all(dbPath);
}

namespace {

struct LdbOptionCase {
    const char* name;
    bool use_bloom_filter;
    bool compression;
    bool use_sync;
    int cache_size;
    bool enable_mmap;
};

class LSMIOLevelDBConfigTest : public ::testing::Test {
  protected:
    lsmio::LSMIOConfig m_backup_config;
    std::vector<std::string> m_paths;

    std::string dbPath(const std::string& name) {
        std::string path = "test-ldb-cov-" + name + ".db";
        std::filesystem::remove_all(path);
        m_paths.push_back(path);
        return path;
    }

    void SetUp() override {
        m_backup_config = lsmio::gConfigLSMIO;
    }

    void TearDown() override {
        lsmio::gConfigLSMIO = m_backup_config;
        for (const auto& path : m_paths) {
            std::filesystem::remove_all(path);
        }
    }
};

class LSMIOLevelDBOptionsTest : public LSMIOLevelDBConfigTest,
                                public ::testing::WithParamInterface<LdbOptionCase> {};

class LSMIOLevelDBWriteFailureDeathTest : public LSMIOLevelDBConfigTest {};

void runDeathChild(
    const std::string& path,
    const std::function<void(std::unique_ptr<lsmio::LSMIOStoreLDB>&, struct rlimit&)>& body) {
    signal(SIGXFSZ, SIG_IGN);
    auto store = std::make_unique<lsmio::LSMIOStoreLDB>(path);
    struct rlimit saved;
    if (getrlimit(RLIMIT_FSIZE, &saved) != 0) {
        std::exit(11);
    }
    bool found_log = false;
    std::uintmax_t max_log_size = 0;
    for (const auto& entry : std::filesystem::directory_iterator(path)) {
        const std::string name = entry.path().filename().string();
        if (name == "LOG" || name == "LOG.old") {
            continue;
        }
        if (entry.path().extension() == ".log") {
            found_log = true;
            const auto sz = std::filesystem::file_size(entry.path());
            if (sz > max_log_size) {
                max_log_size = sz;
            }
        }
    }
    if (!found_log) {
        std::exit(11);
    }
    struct rlimit new_limit;
    new_limit.rlim_cur = max_log_size;
    new_limit.rlim_max = saved.rlim_max;
    if (setrlimit(RLIMIT_FSIZE, &new_limit) != 0) {
        std::exit(11);
    }
    if (store->put("probe", std::string("x"), true)) {
        setrlimit(RLIMIT_FSIZE, &saved);
        store.reset();
        std::exit(10);
    }
    body(store, saved);
    setrlimit(RLIMIT_FSIZE, &saved);
    store.reset();
    std::exit(0);
}

}  // namespace

// Limit: the block cache that cacheSize > 0 installs (the "cache" and "all" rows) has no effect a
// test can observe, because _options is private and LevelDB logs no options. Those rows only show
// that the store opens, writes, reopens and reads back under that setting. The durability effect
// of sync is not observable either (it needs a power cut), so the sync row asserts the
// constructor's log line.
TEST_P(LSMIOLevelDBOptionsTest, OpensAndRoundTrips) {
    const LdbOptionCase& option = GetParam();
    lsmio::gConfigLSMIO.useBloomFilter = option.use_bloom_filter;
    lsmio::gConfigLSMIO.compression = option.compression;
    lsmio::gConfigLSMIO.useSync = option.use_sync;
    lsmio::gConfigLSMIO.cacheSize = option.cache_size;
    lsmio::gConfigLSMIO.enableMMAP = option.enable_mmap;
    const std::string path = dbPath(option.name);

    // The constructor's INFO and WARNING lines reach stderr (initLSMIODebug). No ASSERT between
    // the capture and its end, so the capture always stops.
    testing::internal::CaptureStderr();
    auto lc = std::make_unique<lsmio::LSMIOStoreLDB>(path);
    const std::string log = testing::internal::GetCapturedStderr();

    EXPECT_TRUE(lc->put("opt-key", std::string("opt-value")));
    std::string value;
    EXPECT_TRUE(lc->get("opt-key", &value));
    EXPECT_EQ(value, "opt-value");
    EXPECT_FALSE(lc->get("missing", &value));
    // 32 KiB of one byte: its table size shows whether Snappy compressed the data block
    const std::string big(32768, 'z');
    EXPECT_TRUE(lc->put("opt-big", big));
    lc.reset();  // closes the database

    {
        lsmio::LSMIOStoreLDB again(path);
        EXPECT_TRUE(again.get("opt-key", &value));
        EXPECT_EQ(value, "opt-value");
        EXPECT_TRUE(again.get("opt-big", &value));
        EXPECT_EQ(value, big);
    }

    // LevelDB writes the log records out as a level-0 table when the reopen recovers them, with the
    // reopening store's options. Read every table file the directory holds.
    std::string tables;
    std::uintmax_t ldb_bytes = 0;
    int ldb_files = 0;
    for (const auto& entry : std::filesystem::directory_iterator(path)) {
        if (entry.path().extension() != ".ldb") continue;
        ++ldb_files;
        ldb_bytes += std::filesystem::file_size(entry.path());
        std::ifstream in(entry.path(), std::ios::binary);
        tables.append(std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>());
    }
    ASSERT_GT(ldb_files, 0);

    // Each effect is checked in both directions: present when the option is on, absent when off
    EXPECT_EQ(tables.find("filter.leveldb.BuiltinBloomFilter2") != std::string::npos,
              option.use_bloom_filter)
        << log;
    // Snappy (the LevelDB default, kept when compression is on) shrinks the table below 8 KiB;
    // kNoCompression keeps the 32 KiB value whole
    EXPECT_EQ(ldb_bytes < 8192, option.compression) << "table bytes: " << ldb_bytes;
    if (!option.compression) {
        EXPECT_GE(ldb_bytes, 32768u);
    }
    // LOG(INFO) is compiled out when NDEBUG is set (include/lsmio/lsmio.hpp sets GOOGLE_STRIP_LOG
    // 1 then). Release builds (itest, xtest) cannot see the sync line; DEBUG builds (coverage,
    // debug) can. The calibration line is an unconditional INFO of the same constructor, so the
    // DEBUG check cannot pass by seeing nothing. This file includes glog through lsmio.hpp just as
    // lib/ does, so GOOGLE_STRIP_LOG here has the store's value.
    const bool info_logged =
        log.find("LSMIOStoreLDB::LSMIOStoreLDB: Creating the database: ") != std::string::npos;
    const bool sync_logged =
        log.find("LSMIOStoreLDB::LSMIOStoreLDB: sync writes enabled.") != std::string::npos;
#if GOOGLE_STRIP_LOG == 0
    EXPECT_TRUE(info_logged) << log;
    EXPECT_EQ(sync_logged, option.use_sync) << log;
#else
    EXPECT_FALSE(info_logged) << log;
    EXPECT_FALSE(sync_logged) << log;
#endif
    EXPECT_EQ(log.find("LSMIOStoreLDB: enableMMAP=false requested") != std::string::npos,
              !option.enable_mmap)
        << log;

    EXPECT_TRUE(std::filesystem::is_directory(path));
}

INSTANTIATE_TEST_SUITE_P(
    Options, LSMIOLevelDBOptionsTest,
    ::testing::Values(LdbOptionCase{"bloom", true, false, false, 0, false},
                      LdbOptionCase{"compression", false, true, false, 0, false},
                      LdbOptionCase{"sync", false, false, true, 0, false},
                      LdbOptionCase{"cache", false, false, false, 1 << 20, false},
                      LdbOptionCase{"mmap", false, false, false, 0, true},
                      LdbOptionCase{"all", true, true, true, 1 << 20, true}),
    [](const ::testing::TestParamInfo<LdbOptionCase>& info) {
        return std::string(info.param.name);
    });

TEST_F(LSMIOLevelDBConfigTest, OverWriteDestroysExistingDatabase) {
    const std::string path = dbPath("overwrite");
    {
        lsmio::LSMIOStoreLDB lc(path);
        EXPECT_TRUE(lc.put("old", std::string("1")));
    }
    {
        lsmio::LSMIOStoreLDB lc(path, true);
        std::string value;
        EXPECT_FALSE(lc.get("old", &value));
        EXPECT_TRUE(lc.put("new", std::string("2")));
        EXPECT_TRUE(lc.get("new", &value));
        EXPECT_EQ(value, "2");
    }
    {
        lsmio::LSMIOStoreLDB lc(path);
        std::string value;
        EXPECT_FALSE(lc.get("old", &value));
        EXPECT_TRUE(lc.get("new", &value));
    }
}

TEST_F(LSMIOLevelDBConfigTest, OverWriteOnMissingPathCreatesDatabase) {
    const std::string path = dbPath("overwrite-fresh");
    ASSERT_FALSE(std::filesystem::exists(path));
    lsmio::LSMIOStoreLDB lc(path, true);
    EXPECT_TRUE(std::filesystem::is_directory(path));
    EXPECT_TRUE(lc.put("k", std::string("v")));
}

TEST_F(LSMIOLevelDBConfigTest, GetPrefixReachesEndOfDatabase) {
    const std::string path = dbPath("prefix");
    lsmio::LSMIOStoreLDB lc(path);
    EXPECT_TRUE(lc.put("a1", std::string("x")));
    EXPECT_TRUE(lc.put("b1", std::string("y1")));
    EXPECT_TRUE(lc.put("b2", std::string("y2")));

    std::vector<std::tuple<std::string, std::string>> values;
    EXPECT_TRUE(lc.getPrefix("b", &values));
    ASSERT_EQ(values.size(), 2u);
    EXPECT_EQ(values[0], std::make_tuple(std::string("b1"), std::string("y1")));
    EXPECT_EQ(values[1], std::make_tuple(std::string("b2"), std::string("y2")));

    std::vector<std::tuple<std::string, std::string>> none;
    EXPECT_TRUE(lc.getPrefix("zz", &none));
    EXPECT_TRUE(none.empty());

    std::vector<std::tuple<std::string, std::string>> all;
    EXPECT_TRUE(lc.getPrefix("", &all));
    EXPECT_EQ(all.size(), 3u);
}

TEST_F(LSMIOLevelDBConfigTest, DeferredBatchWrittenAtCountLimit) {
    lsmio::gConfigLSMIO.asyncBatchSize = 3;
    const std::string path = dbPath("batch-count");
    lsmio::LSMIOStoreLDB lc(path);
    std::string value;
    EXPECT_TRUE(lc.put("k1", std::string("1"), false));
    EXPECT_TRUE(lc.put("k2", std::string("2"), false));
    EXPECT_FALSE(lc.get("k1", &value));
    EXPECT_TRUE(lc.put("k3", std::string("3"), false));
    EXPECT_TRUE(lc.get("k1", &value));
    EXPECT_EQ(value, "1");
    EXPECT_TRUE(lc.get("k2", &value));
    EXPECT_EQ(value, "2");
    EXPECT_FALSE(lc.get("k3", &value));
    EXPECT_TRUE(lc.writeBarrier());
    EXPECT_TRUE(lc.get("k3", &value));
    EXPECT_EQ(value, "3");
}

TEST_F(LSMIOLevelDBConfigTest, DeferredBatchWrittenAtByteLimit) {
    lsmio::gConfigLSMIO.asyncBatchSize = 100;
    lsmio::gConfigLSMIO.asyncBatchBytes = 8;
    const std::string path = dbPath("batch-bytes");
    lsmio::LSMIOStoreLDB lc(path);
    std::string value;
    EXPECT_TRUE(lc.put("a", std::string("aaaa"), false));
    EXPECT_FALSE(lc.get("a", &value));
    EXPECT_TRUE(lc.put("b", std::string("bbbb"), false));
    EXPECT_TRUE(lc.get("a", &value));
    EXPECT_EQ(value, "aaaa");
    EXPECT_FALSE(lc.get("b", &value));
    EXPECT_TRUE(lc.readBarrier());
    EXPECT_TRUE(lc.get("b", &value));
    EXPECT_EQ(value, "bbbb");
}

TEST_F(LSMIOLevelDBConfigTest, BarriersWriteDeferredWritesAndSucceedWithNothingPending) {
    const std::string path = dbPath("barriers");
    lsmio::LSMIOStoreLDB lc(path);
    std::string value;
    EXPECT_TRUE(lc.put("k", std::string("v"), false));
    EXPECT_FALSE(lc.get("k", &value));
    EXPECT_TRUE(lc.readBarrier());
    EXPECT_TRUE(lc.get("k", &value));
    EXPECT_EQ(value, "v");
    EXPECT_TRUE(lc.del("k", false));
    EXPECT_TRUE(lc.get("k", &value));
    EXPECT_TRUE(lc.writeBarrier());
    EXPECT_FALSE(lc.get("k", &value));
    // With nothing pending both barriers return true (AI-1); a failed batch write is tested by
    // LSMIOLevelDBWriteFailureDeathTest.
    EXPECT_TRUE(lc.readBarrier());
    EXPECT_TRUE(lc.writeBarrier());
}

TEST_F(LSMIOLevelDBConfigTest, DeferredValueAtCountLimitStaysInBatch) {
    lsmio::gConfigLSMIO.asyncBatchSize = 4;
    const std::string path = dbPath("batch-bypass");
    lsmio::LSMIOStoreLDB lc(path);
    std::string value;
    EXPECT_TRUE(lc.put("small", std::string("123"), false));
    EXPECT_FALSE(lc.get("small", &value));
    EXPECT_TRUE(lc.put("big", std::string("1234"), false));
    EXPECT_FALSE(lc.get("big", &value));
    EXPECT_FALSE(lc.get("small", &value));
    EXPECT_TRUE(lc.writeBarrier());
    EXPECT_TRUE(lc.get("big", &value));
    EXPECT_EQ(value, "1234");
    EXPECT_TRUE(lc.get("small", &value));
    EXPECT_EQ(value, "123");
}

TEST_F(LSMIOLevelDBConfigTest, DeferredValueAtByteLimitBypassesBatchAfterPending) {
    lsmio::gConfigLSMIO.asyncBatchSize = 100;
    lsmio::gConfigLSMIO.asyncBatchBytes = 8;
    const std::string path = dbPath("batch-bytes-bypass");
    lsmio::LSMIOStoreLDB lc(path);
    std::string value;

    EXPECT_TRUE(lc.put("k", std::string("old"), false));
    EXPECT_FALSE(lc.get("k", &value));

    EXPECT_TRUE(lc.put("k", std::string("newvalue"), false));
    EXPECT_TRUE(lc.get("k", &value));
    EXPECT_EQ(value, "newvalue");

    EXPECT_TRUE(lc.put("x", std::string(9, 'x'), false));
    EXPECT_TRUE(lc.get("x", &value));
    EXPECT_EQ(value, std::string(9, 'x'));

    EXPECT_TRUE(lc.writeBarrier());
}

TEST_F(LSMIOLevelDBConfigTest, ConcurrentDeferredWritersKeepEveryKey) {
    lsmio::gConfigLSMIO.asyncBatchSize = 16;
    lsmio::gConfigLSMIO.asyncBatchBytes = 4096;
    const std::string path = dbPath("concurrent");
    lsmio::LSMIOStoreLDB lc(path);

    auto valueFor = [](int t, int i) {
        const size_t sz = (i % 3 == 0) ? 100 : ((i % 3 == 1) ? 1000 : 5000);
        std::string val(sz, static_cast<char>('a' + (i % 26)));
        val[0] = static_cast<char>('0' + t);
        return val;
    };

    std::atomic<int> failure_count{0};
    auto worker = [&](int t) {
        for (int i = 0; i < 400; ++i) {
            const std::string key = "t" + std::to_string(t) + "-" + std::to_string(i);
            const std::string val = valueFor(t, i);
            if (!lc.put(key, val, false)) {
                failure_count++;
            }
            if ((i + 1) % 64 == 0) {
                if (!lc.writeBarrier()) {
                    failure_count++;
                }
            }
        }
    };

    std::thread t0(worker, 0);
    std::thread t1(worker, 1);
    t0.join();
    t1.join();

    EXPECT_EQ(failure_count.load(), 0);
    EXPECT_TRUE(lc.writeBarrier());

    for (int t = 0; t < 2; ++t) {
        for (int i = 0; i < 400; ++i) {
            const std::string key = "t" + std::to_string(t) + "-" + std::to_string(i);
            std::string val;
            EXPECT_TRUE(lc.get(key, &val)) << "key " << key;
            EXPECT_EQ(val, valueFor(t, i)) << "key " << key;
        }
    }
}

TEST_F(LSMIOLevelDBWriteFailureDeathTest, FailedBatchWriteFailsWriteBarrier) {
    GTEST_FLAG_SET(death_test_style, "threadsafe");
    const std::string path = dbPath("fail-batch-write-wb");
    EXPECT_EXIT(
        runDeathChild(path, [](auto& store, auto& saved) {
            auto fail = [&](int rc) {
                setrlimit(RLIMIT_FSIZE, &saved);
                store.reset();
                std::exit(rc);
            };
            if (!store->put("k", std::string("v"), false)) fail(20);
            if (store->writeBarrier()) fail(21);
            if (store->readBarrier()) fail(22);
            setrlimit(RLIMIT_FSIZE, &saved);
            if (store->writeBarrier()) fail(23);
            if (!store->put("k2", std::string("v2"), false)) fail(24);
            if (store->writeBarrier()) fail(25);
            std::string val;
            if (!store->get("k2", &val) || val != "v2") fail(26);
            if (store->get("k", &val)) fail(27);
        }),
        ::testing::ExitedWithCode(0), "");
}

TEST_F(LSMIOLevelDBWriteFailureDeathTest, FailedBatchWriteFailsReadBarrier) {
    GTEST_FLAG_SET(death_test_style, "threadsafe");
    const std::string path = dbPath("fail-batch-write-rb");
    EXPECT_EXIT(
        runDeathChild(path, [](auto& store, auto& saved) {
            auto fail = [&](int rc) {
                setrlimit(RLIMIT_FSIZE, &saved);
                store.reset();
                std::exit(rc);
            };
            if (!store->put("k", std::string("v"), false)) fail(20);
            if (store->readBarrier()) fail(21);
            setrlimit(RLIMIT_FSIZE, &saved);
            if (store->writeBarrier()) fail(22);
        }),
        ::testing::ExitedWithCode(0), "");
}

TEST_F(LSMIOLevelDBWriteFailureDeathTest, FailedBatchFullFlushFailsPut) {
    GTEST_FLAG_SET(death_test_style, "threadsafe");
    lsmio::gConfigLSMIO.asyncBatchSize = 2;
    const std::string path = dbPath("fail-batch-full");
    EXPECT_EXIT(
        runDeathChild(path, [](auto& store, auto& saved) {
            auto fail = [&](int rc) {
                setrlimit(RLIMIT_FSIZE, &saved);
                store.reset();
                std::exit(rc);
            };
            if (!store->put("k1", std::string("1"), false)) fail(20);
            if (store->put("k2", std::string("2"), false)) fail(21);
            setrlimit(RLIMIT_FSIZE, &saved);
            if (store->writeBarrier()) fail(22);
            std::string val;
            if (!store->get("k2", &val) || val != "2") fail(23);
            if (store->get("k1", &val)) fail(24);
        }),
        ::testing::ExitedWithCode(0), "");
}

// Test-file comment for FailedFlushBeforeDirectPutIsSticky: the direct put's own write also fails
// at the limit, so check 21 holds before the fix too. Only check 22 discriminates. That the put
// reports the failed flush itself is not checked by any test (decision 15, Q1, accepted).
TEST_F(LSMIOLevelDBWriteFailureDeathTest, FailedFlushBeforeDirectPutIsSticky) {
    GTEST_FLAG_SET(death_test_style, "threadsafe");
    const std::string path = dbPath("fail-flush-direct-sticky");
    EXPECT_EXIT(
        runDeathChild(path, [](auto& store, auto& saved) {
            auto fail = [&](int rc) {
                setrlimit(RLIMIT_FSIZE, &saved);
                store.reset();
                std::exit(rc);
            };
            if (!store->put("k", std::string("v"), false)) fail(20);
            if (store->put("d", std::string("x"), true)) fail(21);
            setrlimit(RLIMIT_FSIZE, &saved);
            if (store->writeBarrier()) fail(22);
        }),
        ::testing::ExitedWithCode(0), "");
}

int main(int argc, char** argv) {
    lsmio::initLSMIODebug(argv[0]);
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
