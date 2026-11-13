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
#include <sys/resource.h>

#include <algorithm>
#include <atomic>
#include <csignal>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iostream>
#include <iterator>
#include <leveldb/db.h>
#include <lsmio/manager/store/store_ldb.hpp>
#include <manager/store/NoSyncLevelDBEnv.hpp>
#include <manager/store/PageCacheGate.hpp>
#include <manager/store/PageCacheGateOverride.hpp>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <string_view>
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

TEST_F(LSMIOLevelDBConfigTest, SuccessfulBatchWriteIsNotResent) {
    lsmio::LSMIOStoreLDB lc(dbPath("batch-not-resent"));

    EXPECT_TRUE(lc.put("k", std::string("old"), false));
    EXPECT_TRUE(lc.writeBarrier());
    EXPECT_TRUE(lc.put("k", std::string("new"), true));
    EXPECT_TRUE(lc.put("k2", std::string("x"), false));
    EXPECT_TRUE(lc.writeBarrier());

    std::string val_k;
    EXPECT_TRUE(lc.get("k", &val_k));
    EXPECT_EQ(val_k, "new");

    std::string val_k2;
    EXPECT_TRUE(lc.get("k2", &val_k2));
    EXPECT_EQ(val_k2, "x");
}

TEST_F(LSMIOLevelDBWriteFailureDeathTest, FailedBatchWriteFailsWriteBarrier) {
    GTEST_FLAG_SET(death_test_style, "threadsafe");
    const std::string path = dbPath("fail-batch-write-wb");
    EXPECT_EXIT(runDeathChild(path,
                              [](auto& store, auto& saved) {
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
    EXPECT_EXIT(runDeathChild(path,
                              [](auto& store, auto& saved) {
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
    EXPECT_EXIT(runDeathChild(path,
                              [](auto& store, auto& saved) {
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
    EXPECT_EXIT(runDeathChild(path,
                              [](auto& store, auto& saved) {
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

// No-sync LevelDB Env (INV-17, INV-19), exercised directly through the Env without a store.
namespace {

class NoSyncLevelDBEnvTest : public LSMIOLevelDBConfigTest {
  protected:
    std::string filePath(const std::string& name) {
        std::string path = "test-ldb-nosync-" + name + ".bin";
        std::filesystem::remove(path);
        m_paths.push_back(path);
        return path;
    }

    static std::string readAll(const std::string& path) {
        std::ifstream in(path, std::ios::binary);
        return std::string(std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>());
    }
};

}  // namespace

TEST_F(NoSyncLevelDBEnvTest, WritableFileSyncIsCountedAndDataSurvives) {
    const std::string path = filePath("writable");
    leveldb::WritableFile* file = nullptr;
    ASSERT_TRUE(lsmio::noSyncLevelDBEnv()->NewWritableFile(path, &file).ok());
    ASSERT_NE(file, nullptr);
    std::unique_ptr<leveldb::WritableFile> owner(file);

    const std::uint64_t before = lsmio::interceptedLevelDBSyncCount();
    EXPECT_TRUE(owner->Append("hello ").ok());
    EXPECT_TRUE(owner->Append("world").ok());
    EXPECT_TRUE(owner->Sync().ok());
    EXPECT_EQ(lsmio::interceptedLevelDBSyncCount(), before + 1);
    // Sync replaced by flush, never by dropping data (INV-17): the bytes are in the file after
    // Sync and before Close (Close flushes on its own, so only this read sees a no-op Sync).
    EXPECT_EQ(readAll(path), "hello world");
    EXPECT_TRUE(owner->Close().ok());
    EXPECT_EQ(readAll(path), "hello world");
}

TEST_F(NoSyncLevelDBEnvTest, AppendableFileAppendsAndSyncIsCounted) {
    const std::string path = filePath("appendable");
    {
        std::ofstream out(path, std::ios::binary);
        out << "first,";
    }
    leveldb::WritableFile* file = nullptr;
    ASSERT_TRUE(lsmio::noSyncLevelDBEnv()->NewAppendableFile(path, &file).ok());
    ASSERT_NE(file, nullptr);
    std::unique_ptr<leveldb::WritableFile> owner(file);

    const std::uint64_t before = lsmio::interceptedLevelDBSyncCount();
    EXPECT_TRUE(owner->Append("second").ok());
    EXPECT_TRUE(owner->Sync().ok());
    EXPECT_EQ(lsmio::interceptedLevelDBSyncCount(), before + 1);
    EXPECT_TRUE(owner->Close().ok());
    EXPECT_EQ(readAll(path), "first,second");
}

TEST_F(NoSyncLevelDBEnvTest, FlushForwardsBeforeClose) {
    const std::string path = filePath("flush");
    leveldb::WritableFile* file = nullptr;
    ASSERT_TRUE(lsmio::noSyncLevelDBEnv()->NewWritableFile(path, &file).ok());
    std::unique_ptr<leveldb::WritableFile> owner(file);

    const std::uint64_t before = lsmio::interceptedLevelDBSyncCount();
    EXPECT_TRUE(owner->Append("buffered").ok());
    EXPECT_TRUE(owner->Flush().ok());
    EXPECT_EQ(readAll(path), "buffered");
    EXPECT_EQ(lsmio::interceptedLevelDBSyncCount(), before);
    EXPECT_TRUE(owner->Close().ok());
}

TEST_F(NoSyncLevelDBEnvTest, FactoryFailuresReturnTargetStatusAndCountNothing) {
    const std::string path = "test-ldb-nosync-missing-dir/file.bin";
    const std::uint64_t before = lsmio::interceptedLevelDBSyncCount();

    leveldb::WritableFile* file = nullptr;
    EXPECT_FALSE(lsmio::noSyncLevelDBEnv()->NewWritableFile(path, &file).ok());
    EXPECT_EQ(file, nullptr);
    EXPECT_FALSE(lsmio::noSyncLevelDBEnv()->NewAppendableFile(path, &file).ok());
    EXPECT_EQ(file, nullptr);
    EXPECT_EQ(lsmio::interceptedLevelDBSyncCount(), before);
}

TEST_F(NoSyncLevelDBEnvTest, EnvIsOneProcessLifetimeObject) {
    leveldb::Env* first = lsmio::noSyncLevelDBEnv();
    EXPECT_NE(first, nullptr);
    EXPECT_EQ(first, lsmio::noSyncLevelDBEnv());
    EXPECT_NE(first, leveldb::Env::Default());
}

// Verified-build gate (INV-20) and its test admission seam (INV-20b), LevelDB rows. They repeat
// the rows of test_rocksdb.cpp so the LevelDB gate is also checked from the LevelDB binary.
TEST(LevelDBGateTest, CompileTimeAndRunTimeBuild) {
    const lsmio::LibraryBuild level = lsmio::compileTimeBuild(lsmio::StorageType::LevelDB);
    EXPECT_TRUE(level == (lsmio::LibraryBuild{leveldb::kMajorVersion, leveldb::kMinorVersion, -1,
                                              lsmio::compiledPlatform()}));
    EXPECT_EQ(level.patch, -1);
    EXPECT_FALSE(lsmio::runTimeBuild(lsmio::StorageType::LevelDB).has_value());
    EXPECT_NE(lsmio::describeRunningBuild(lsmio::StorageType::LevelDB)
                  .find(std::to_string(leveldb::kMajorVersion) + "." +
                        std::to_string(leveldb::kMinorVersion)),
              std::string::npos);
}

TEST(LevelDBGateTest, WrapperIsAlwaysCompiledIn) {
    EXPECT_TRUE(lsmio::pageCacheWrapperCompiledIn(lsmio::StorageType::LevelDB));
}

TEST(LevelDBGateOverrideTest, AdmitDenyAndRestore) {
    const lsmio::StorageType engine = lsmio::StorageType::LevelDB;
    EXPECT_EQ(lsmio::pageCacheAdmitted(engine), lsmio::pageCacheVerified(engine));
    {
        lsmio::PageCacheGateOverride admit(lsmio::GateDecision::Admit);
        EXPECT_TRUE(lsmio::pageCacheAdmitted(engine));
    }
    {
        lsmio::PageCacheGateOverride deny(lsmio::GateDecision::Deny);
        EXPECT_FALSE(lsmio::pageCacheAdmitted(engine));
    }
    EXPECT_EQ(lsmio::pageCacheAdmitted(engine), lsmio::pageCacheVerified(engine));
}

// LevelDB store page-cache mode (INV-2, INV-17, INV-20): gate refusals and the E3 round trips.
namespace {

struct FileState {
    std::uintmax_t size;
    std::filesystem::file_time_type mtime;
    bool operator==(const FileState& other) const {
        return size == other.size && mtime == other.mtime;
    }
};
using DirSnapshot = std::map<std::string, FileState>;

DirSnapshot snapshotDir(const std::string& path) {
    DirSnapshot snap;
    for (const auto& entry : std::filesystem::directory_iterator(path)) {
        snap[entry.path().filename().string()] = {entry.file_size(), entry.last_write_time()};
    }
    return snap;
}

class LevelDBPageCacheBase : public LSMIOLevelDBConfigTest {
  protected:
    void setMode(lsmio::Durability f_mode, bool f_use_sync = false) {
        lsmio::gConfigLSMIO.durability = f_mode;
        lsmio::gConfigLSMIO.useSync = f_use_sync;
    }

    // Creates a store with data in engine mode, closes it and returns its snapshot.
    DirSnapshot makeEngineStore(const std::string& path) {
        setMode(lsmio::Durability::Engine);
        {
            lsmio::LSMIOStoreLDB store(path, true);
            EXPECT_TRUE(store.put("existing", std::string("value"), true));
            EXPECT_TRUE(store.writeBarrier());
            store.close();
        }
        return snapshotDir(path);
    }

    static std::string readText(const std::string& path) {
        std::ifstream in(path, std::ios::binary);
        return std::string(std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>());
    }
};

class LevelDBDurabilityGate : public LevelDBPageCacheBase {};

class LevelDBPageCache : public LevelDBPageCacheBase {
  protected:
    static std::string valueFor(int f_key, int f_round) {
        return "round" + std::to_string(f_round) + "-key" + std::to_string(f_key) +
               std::string(200, 'v');
    }

    // Writer, reader, overWrite open through the no-sync Env with a small write buffer and enough
    // overlapping rounds for memtable flushes and a level-0 compaction (E3).
    void roundTrip(const std::string& f_name) {
        const std::string path = dbPath(f_name);
        const int keys = 1500;
        const int rounds = 6;
        lsmio::gConfigLSMIO.writeBufferSize = 64 * 1024;
        lsmio::gConfigLSMIO.writeFileSize = 1024 * 1024;
        setMode(lsmio::Durability::PageCache);
        lsmio::PageCacheGateOverride admit(lsmio::GateDecision::Admit);

        const std::uint64_t before = lsmio::interceptedLevelDBSyncCount();
        {
            lsmio::LSMIOStoreLDB writer(path, true);
            for (int round = 0; round < rounds; ++round) {
                for (int key = 0; key < keys; ++key) {
                    ASSERT_TRUE(writer.put("key" + std::to_string(key), valueFor(key, round), false));
                }
                ASSERT_TRUE(writer.writeBarrier());
            }
            writer.close();
        }
        EXPECT_GT(lsmio::interceptedLevelDBSyncCount(), before);

        {
            lsmio::LSMIOStoreLDB reader(path, false);
            for (int key = 0; key < keys; ++key) {
                std::string value;
                ASSERT_TRUE(reader.get("key" + std::to_string(key), &value));
                EXPECT_EQ(value, valueFor(key, rounds - 1));
            }
            reader.close();
        }
        // Opening the store renames the previous LOG to LOG.old, so look in both.
        const std::string log_text = readText(path + "/LOG") + readText(path + "/LOG.old");
        EXPECT_NE(log_text.find("Compacting"), std::string::npos);

        {
            lsmio::LSMIOStoreLDB again(path, true);
            std::string value;
            EXPECT_FALSE(again.get("key0", &value));
            again.close();
        }
    }
};

}  // namespace

TEST_F(LevelDBDurabilityGate, DenyRefusesBeforeTouchingFiles) {
    const std::string path = dbPath("gate-deny");
    const DirSnapshot before = makeEngineStore(path);
    setMode(lsmio::Durability::PageCache);
    lsmio::PageCacheGateOverride deny(lsmio::GateDecision::Deny);
    try {
        lsmio::LSMIOStoreLDB store(path, true);
        FAIL() << "page-cache open under Deny must throw";
    } catch (const std::invalid_argument& e) {
        const std::string what = e.what();
        EXPECT_NE(what.find("LevelDB"), std::string::npos);
        EXPECT_NE(what.find("page-cache"), std::string::npos);
        EXPECT_NE(what.find("1.23"), std::string::npos);
    }
    EXPECT_TRUE(snapshotDir(path) == before);
}

TEST_F(LevelDBDurabilityGate, NoOverrideFollowsTable) {
    const std::string path = dbPath("gate-table");
    const bool verified = lsmio::pageCacheVerified(lsmio::StorageType::LevelDB);
    EXPECT_EQ(lsmio::pageCacheAdmitted(lsmio::StorageType::LevelDB), verified);
    setMode(lsmio::Durability::PageCache);
    if (verified) {
        lsmio::LSMIOStoreLDB store(path, true);
        EXPECT_TRUE(store.put("k", std::string("v"), true));
        store.close();
        EXPECT_TRUE(std::filesystem::exists(path));
    } else {
        try {
            lsmio::LSMIOStoreLDB store(path, true);
            FAIL() << "page-cache open of an unverified build must throw";
        } catch (const std::invalid_argument& e) {
            const std::string what = e.what();
            EXPECT_NE(what.find("LevelDB"), std::string::npos);
            EXPECT_NE(what.find("page-cache"), std::string::npos);
            EXPECT_NE(what.find("1.23"), std::string::npos);
        }
        EXPECT_FALSE(std::filesystem::exists(path));
    }
}

TEST_F(LevelDBDurabilityGate, EngineModeIgnoresDeny) {
    const std::string path = dbPath("gate-engine");
    setMode(lsmio::Durability::Engine);
    lsmio::PageCacheGateOverride deny(lsmio::GateDecision::Deny);
    {
        lsmio::LSMIOStoreLDB store(path, true);
        EXPECT_TRUE(store.put("key", std::string("value"), true));
        EXPECT_TRUE(store.writeBarrier());
        store.close();
    }
    lsmio::LSMIOStoreLDB reader(path, false);
    std::string value;
    EXPECT_TRUE(reader.get("key", &value));
    EXPECT_EQ(value, "value");
}

TEST_F(LevelDBDurabilityGate, UseSyncRefusedBeforeGate) {
    const std::string path = dbPath("gate-usesync");
    const DirSnapshot before = makeEngineStore(path);
    setMode(lsmio::Durability::PageCache, true);
    for (const lsmio::GateDecision decision :
         {lsmio::GateDecision::Admit, lsmio::GateDecision::Deny}) {
        lsmio::PageCacheGateOverride scope(decision);
        try {
            lsmio::LSMIOStoreLDB store(path, true);
            FAIL() << "page-cache with useSync must throw";
        } catch (const std::invalid_argument& e) {
            const std::string what = e.what();
            EXPECT_NE(what.find("useSync"), std::string::npos);
            EXPECT_NE(what.find("page-cache"), std::string::npos);
            // The useSync refusal comes first, so the gate's build text is not in it (NB21).
            EXPECT_EQ(what.find("verified page-cache build"), std::string::npos);
        }
        EXPECT_TRUE(snapshotDir(path) == before);
    }

    setMode(lsmio::Durability::Engine, true);
    lsmio::LSMIOStoreLDB store(path, false);
    std::string value;
    EXPECT_TRUE(store.put("synced", std::string("yes"), true));
    EXPECT_TRUE(store.get("existing", &value));
    EXPECT_EQ(value, "value");
    EXPECT_TRUE(store.get("synced", &value));
    EXPECT_EQ(value, "yes");
}

TEST_F(LevelDBPageCache, DefaultFlagsRoundTrip) {
    roundTrip("e3-default");
}

TEST_F(LevelDBPageCache, WalFlagRoundTrip) {
    lsmio::gConfigLSMIO.enableWAL = true;
    roundTrip("e3-wal");
}

TEST_F(LevelDBPageCache, MmapFlagRoundTrip) {
    lsmio::gConfigLSMIO.enableMMAP = true;
    roundTrip("e3-mmap");
}

namespace {

// Opens the protected batch entry points of the store, which are private in LSMIOStoreLDB and have
// no caller outside the store
class LdbBatchAccess : public lsmio::LSMIOStoreLDB {
  public:
    using lsmio::LSMIOStoreLDB::LSMIOStoreLDB;
    using lsmio::LSMIOStore::_batchMutation;
    using lsmio::LSMIOStore::startBatch;
    using lsmio::LSMIOStore::stopBatch;
    unsigned int pendingBatchSize() {
        return _batchSize;
    }
    unsigned int pendingBatchBytes() {
        return _batchBytes;
    }
};

const lsmio::MutationType kUnknownMutation = static_cast<lsmio::MutationType>(99);

class LevelDBStoreFailure : public LSMIOLevelDBConfigTest {};

std::string failureMessage(const std::function<void()>& f_body) {
    try {
        f_body();
    } catch (const std::invalid_argument& e) {
        return e.what();
    }
    return "";
}

}  // namespace

TEST_F(LevelDBStoreFailure, OpenFailureThrowsAndCreatesNothing) {
    const std::string blocker = dbPath("open-blocker");
    {
        std::ofstream out(blocker);
        out << "not a directory";
    }
    const std::string path = blocker + "/db";

    const std::string message = failureMessage([&] { lsmio::LSMIOStoreLDB store(path); });
    EXPECT_NE(message.find("Failed to open database"), std::string::npos) << message;

    EXPECT_TRUE(std::filesystem::is_regular_file(blocker));
    EXPECT_EQ(std::filesystem::file_size(blocker), std::string("not a directory").size());
    EXPECT_FALSE(std::filesystem::exists(path));
}

TEST_F(LevelDBStoreFailure, OverWriteOfOpenStoreFailsAndKeepsTheLiveStore) {
    const std::string path = dbPath("destroy-held");
    lsmio::LSMIOStoreLDB live(path);
    ASSERT_TRUE(live.put("held", std::string("value")));
    ASSERT_TRUE(live.writeBarrier());

    // This process already holds the database LOCK, so DestroyDB cannot take it
    const std::string message = failureMessage([&] { lsmio::LSMIOStoreLDB again(path, true); });
    EXPECT_NE(message.find("Failed to remove database"), std::string::npos) << message;

    std::string value;
    EXPECT_TRUE(live.get("held", &value));
    EXPECT_EQ(value, "value");
    EXPECT_TRUE(live.put("after", std::string("still-writable")));
    EXPECT_TRUE(live.get("after", &value));
    EXPECT_EQ(value, "still-writable");
}

TEST_F(LevelDBStoreFailure, StartAndStopBatchTrackThePendingBatch) {
    LdbBatchAccess store(dbPath("batch-access"));

    EXPECT_TRUE(store.startBatch());  // nothing pending
    EXPECT_EQ(store.pendingBatchSize(), 0u);

    EXPECT_TRUE(store.put("pending", std::string("v"), false));
    EXPECT_EQ(store.pendingBatchSize(), 1u);
    EXPECT_FALSE(store.startBatch());  // one write is pending
    std::string value;
    EXPECT_FALSE(store.get("pending", &value));  // not written yet

    EXPECT_TRUE(store.stopBatch());
    EXPECT_EQ(store.pendingBatchSize(), 0u);
    EXPECT_TRUE(store.startBatch());
    EXPECT_TRUE(store.get("pending", &value));
    EXPECT_EQ(value, "v");
}

TEST_F(LevelDBStoreFailure, UnknownMutationThrowsOnDirectPathAndLeavesTheStoreUsable) {
    LdbBatchAccess store(dbPath("unknown-direct"));
    ASSERT_TRUE(store.put("k", std::string("v")));

    const std::string message = failureMessage(
        [&] { store._batchMutation(kUnknownMutation, "k", std::string("x"), true); });
    EXPECT_NE(message.find("Unknown mutation"), std::string::npos) << message;

    std::string value;
    EXPECT_TRUE(store.get("k", &value));
    EXPECT_EQ(value, "v");
}

TEST_F(LevelDBStoreFailure, UnknownMutationOnBatchPathThrowsAndLeavesTheBatchUnchanged) {
    LdbBatchAccess store(dbPath("unknown-batch"));
    ASSERT_TRUE(store._batchMutation(lsmio::MutationType::Put, "pending", std::string("v"), false));
    ASSERT_EQ(store.pendingBatchSize(), 1u);
    const unsigned int bytesBefore = store.pendingBatchBytes();

    const std::string message = failureMessage(
        [&] { store._batchMutation(kUnknownMutation, "ghost", std::string("xxxx"), false); });
    EXPECT_NE(message.find("Unknown mutation"), std::string::npos) << message;

    EXPECT_EQ(store.pendingBatchSize(), 1u);
    EXPECT_EQ(store.pendingBatchBytes(), bytesBefore);
    EXPECT_TRUE(store.stopBatch());

    std::string value;
    EXPECT_FALSE(store.get("ghost", &value));
    EXPECT_TRUE(store.get("pending", &value));
    EXPECT_EQ(value, "v");
}

int main(int argc, char** argv) {
    lsmio::initLSMIODebug(argv[0]);
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
