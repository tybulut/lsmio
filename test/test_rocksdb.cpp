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
#include <rocksdb/convenience.h>
#include <rocksdb/table.h>
#include <rocksdb/utilities/options_util.h>

#include <algorithm>
#include <cstdint>
#include <filesystem>
#include <iostream>
#include <lsmio/manager/manager.hpp>
#include <lsmio/manager/store/store_rdb.hpp>
#include <memory>
#include <string>
#include <string_view>
#include <tuple>
#include <vector>

std::string TEST_DIR_RDB = "";

TEST(lsmioRocksDB, Flush) {
    bool success = true;
    std::string value;

    std::string key1 = "serdar";
    std::string key2 = "bulut";
    std::string value1 = "alpino";
    std::string value2 = "teomos";

    std::string dbName = "test-rdb-store-flush.db";
    std::string dbPath = TEST_DIR_RDB.empty() ? dbName : TEST_DIR_RDB + "/" + dbName;

    lsmio::LSMIOStoreRDB lc(dbPath);
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

TEST(lsmioRocksDB, Deferred) {
    bool success = true;
    std::string value;

    std::string key1 = "serdar";
    std::string key2 = "bulut";
    std::string value1 = "alpino";
    std::string value2 = "teomos";

    std::string dbName = "test-rdb-store-deferred.db";
    std::string dbPath = TEST_DIR_RDB.empty() ? dbName : TEST_DIR_RDB + "/" + dbName;

    lsmio::LSMIOStoreRDB lc(dbPath);
    LOG(INFO) << "Created a test database called: " << dbPath << std::endl;

    success = lc.put(key1, value1, false);
    EXPECT_EQ(success, true);

    success = lc.put(key2, value2, false);
    EXPECT_EQ(success, true);

    success = lc.get(key1, &value);
    EXPECT_EQ(success, true);

    LOG(INFO) << "Test value for key1: " << value << std::endl;
    EXPECT_EQ(value, value1);

    success = lc.get(key2, &value);
    EXPECT_EQ(success, true);

    LOG(INFO) << "Test value for key2: " << value << std::endl;
    EXPECT_EQ(value, value2);

    success = lc.metaPut(key1, value2, false);
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

    success = lc.del(key1);
    EXPECT_EQ(success, true);

    success = lc.del(key2);
    EXPECT_EQ(success, true);

    success = lc.writeBarrier();
    EXPECT_EQ(success, true);
}

// putBytes hands the caller's bytes to RocksDB, which copies them: the caller's buffer can change
// right after, with or without flush (RocksDB writes every put straight into its memtable)
TEST(lsmioRocksDB, PutBytesCopiesCallerBytes) {
    std::string dbName = "test-rdb-store-putbytes.db";
    std::string dbPath = TEST_DIR_RDB.empty() ? dbName : TEST_DIR_RDB + "/" + dbName;
    std::filesystem::remove_all(dbPath);

    auto expected = [](int i) {
        std::string v(i % 2 ? 100 : 4096, static_cast<char>('a' + i % 26));
        v[v.size() / 2] = '\0';  // binary-safe
        return v;
    };
    {
        lsmio::LSMIOStoreRDB lc(dbPath);
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

struct RdbOptionCase {
    const char* name;
    bool use_bloom_filter;
    bool compression;
    int cache_size;
    bool use_sync;
    bool enable_wal;
};

class LSMIORocksDBConfigTest : public ::testing::Test {
  protected:
    lsmio::LSMIOConfig m_backup_config;
    std::vector<std::string> m_paths;

    std::string dbPath(const std::string& name) {
        std::string path = "test-rdb-cov-" + name + ".db";
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

class LSMIORocksDBOptionsTest : public LSMIORocksDBConfigTest,
                                public ::testing::WithParamInterface<RdbOptionCase> {};

// Total size of the write-ahead log files (*.log) in the database directory
std::uintmax_t walBytes(const std::string& f_path) {
    std::uintmax_t total = 0;
    for (const auto& entry : std::filesystem::directory_iterator(f_path)) {
        if (entry.path().extension() == ".log") {
            total += std::filesystem::file_size(entry.path());
        }
    }
    return total;
}

}  // namespace

// Limit: the block cache that cacheSize > 0 installs (the "cache" row) has no effect a test can
// observe. RocksDB does not persist block_cache in its OPTIONS file (LoadLatestOptions returns it
// at its default), the store's info log is at ERROR level and _db is private. So the cache row only
// shows that the store opens, writes, reopens and reads back under that setting. The durability
// effect of sync is not observable either (it needs a power cut), so the sync rows assert the
// constructor's log lines and the WAL file size.
TEST_P(LSMIORocksDBOptionsTest, OpensAndRoundTrips) {
    const RdbOptionCase& option = GetParam();
    lsmio::gConfigLSMIO.useBloomFilter = option.use_bloom_filter;
    lsmio::gConfigLSMIO.compression = option.compression;
    lsmio::gConfigLSMIO.cacheSize = option.cache_size;
    lsmio::gConfigLSMIO.useSync = option.use_sync;
    lsmio::gConfigLSMIO.enableWAL = option.enable_wal;
    const std::string path = dbPath(option.name);

    // The constructor's INFO and WARNING lines reach stderr (initLSMIODebug). No ASSERT between
    // the capture and its end, so the capture always stops.
    testing::internal::CaptureStderr();
    auto lc = std::make_unique<lsmio::LSMIOStoreRDB>(path);
    const std::string log = testing::internal::GetCapturedStderr();

    EXPECT_TRUE(lc->put("opt-key", std::string("opt-value")));
    // Measured before the barrier: the memtable flush may retire the log file
    const std::uintmax_t wal_bytes = walBytes(path);
    std::string value;
    EXPECT_TRUE(lc->get("opt-key", &value));
    EXPECT_EQ(value, "opt-value");
    EXPECT_FALSE(lc->get("missing", &value));
    EXPECT_TRUE(lc->writeBarrier());
    lc.reset();  // closes the database

    {
        lsmio::LSMIOStoreRDB again(path);
        EXPECT_TRUE(again.get("opt-key", &value));
        EXPECT_EQ(value, "opt-value");
    }

    // RocksDB persists the options it opened the database with, in OPTIONS-<n>, at every open
    rocksdb::ConfigOptions config_options;
    rocksdb::DBOptions db_options;
    std::vector<rocksdb::ColumnFamilyDescriptor> cf_descs;
    const rocksdb::Status s =
        rocksdb::LoadLatestOptions(config_options, path, &db_options, &cf_descs);
    ASSERT_TRUE(s.ok()) << s.ToString();
    ASSERT_EQ(cf_descs.size(), 1u);
    ASSERT_EQ(cf_descs[0].name, "default");
    const rocksdb::ColumnFamilyOptions& cf = cf_descs[0].options;
    const auto* table = cf.table_factory->GetOptions<rocksdb::BlockBasedTableOptions>();
    ASSERT_NE(table, nullptr);

    // Each effect is checked in both directions: present when the option is on, absent when off
    EXPECT_EQ(table->filter_policy != nullptr, option.use_bloom_filter);
    // Compression on makes the store choose a codec the linked RocksDB supports (Snappy, LZ4 or
    // Zstd), so it is not kNoCompression when at least one codec is supported
    const std::vector<rocksdb::CompressionType>& supported = rocksdb::GetSupportedCompressions();
    const bool codec_supported = std::any_of(
        supported.begin(), supported.end(), [](rocksdb::CompressionType c) {
            return c == rocksdb::kSnappyCompression || c == rocksdb::kLZ4Compression ||
                   c == rocksdb::kZSTD;
        });
    if (codec_supported) {
        EXPECT_EQ(cf.compression == rocksdb::kNoCompression, !option.compression)
            << "persisted compression: " << static_cast<int>(cf.compression);
    } else {
        EXPECT_EQ(cf.compression, rocksdb::kNoCompression)
            << "persisted compression: " << static_cast<int>(cf.compression);
    }
    // LOG(INFO) is compiled out when NDEBUG is set (include/lsmio/lsmio.hpp sets GOOGLE_STRIP_LOG
    // 1 then). Release builds (itest, xtest) cannot see the sync line; DEBUG builds (coverage,
    // debug) can. The calibration line is an unconditional INFO of the same constructor, so the
    // DEBUG check cannot pass by seeing nothing. This file includes glog through lsmio.hpp just as
    // lib/ does, so GOOGLE_STRIP_LOG here has the store's value.
    const bool info_logged =
        log.find("LSMIOStoreRDB::LSMIOStoreRDB: Creating the database: ") != std::string::npos;
    const bool sync_logged =
        log.find("LSMIOStoreRDB::LSMIOStoreRDB: sync writes enabled.") != std::string::npos;
#if GOOGLE_STRIP_LOG == 0
    EXPECT_TRUE(info_logged) << log;
    EXPECT_EQ(sync_logged, option.use_sync && option.enable_wal) << log;
#else
    EXPECT_FALSE(info_logged) << log;
    EXPECT_FALSE(sync_logged) << log;
#endif
    EXPECT_EQ(log.find("LSMIOStoreRDB::LSMIOStoreRDB: ignoring sync writes enablement as WAL is "
                       "disabled.") != std::string::npos,
              option.use_sync && !option.enable_wal)
        << log;
    EXPECT_EQ(wal_bytes > 0, option.enable_wal) << "wal bytes: " << wal_bytes;
}

INSTANTIATE_TEST_SUITE_P(
    Options, LSMIORocksDBOptionsTest,
    ::testing::Values(RdbOptionCase{"bloom", true, false, 0, false, false},
                      RdbOptionCase{"compression", false, true, 0, false, false},
                      RdbOptionCase{"cache", false, false, 1 << 20, false, false},
                      RdbOptionCase{"syncWithWAL", false, false, 0, true, true},
                      RdbOptionCase{"syncWithoutWAL", false, false, 0, true, false},
                      RdbOptionCase{"walWithoutSync", false, false, 0, false, true}),
    [](const ::testing::TestParamInfo<RdbOptionCase>& info) {
        return std::string(info.param.name);
    });

TEST_F(LSMIORocksDBConfigTest, OverWriteDestroysExistingDatabase) {
    const std::string path = dbPath("overwrite");
    {
        lsmio::LSMIOStoreRDB lc(path);
        EXPECT_TRUE(lc.put("old", std::string("1")));
    }
    {
        lsmio::LSMIOStoreRDB lc(path, true);
        std::string value;
        EXPECT_FALSE(lc.get("old", &value));
        EXPECT_TRUE(lc.put("new", std::string("2")));
        EXPECT_TRUE(lc.get("new", &value));
        EXPECT_EQ(value, "2");
    }
    {
        lsmio::LSMIOStoreRDB lc(path);
        std::string value;
        EXPECT_FALSE(lc.get("old", &value));
        EXPECT_TRUE(lc.get("new", &value));
        EXPECT_EQ(value, "2");
    }
}

TEST_F(LSMIORocksDBConfigTest, OverWriteOnMissingPathCreatesDatabase) {
    const std::string path = dbPath("overwrite-fresh");
    ASSERT_FALSE(std::filesystem::exists(path));
    lsmio::LSMIOStoreRDB lc(path, true);
    EXPECT_TRUE(std::filesystem::is_directory(path));
    EXPECT_TRUE(lc.put("k", std::string("v")));
}

TEST_F(LSMIORocksDBConfigTest, GetPrefixReachesEndOfDatabase) {
    const std::string path = dbPath("prefix");
    lsmio::LSMIOStoreRDB lc(path);
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

TEST_F(LSMIORocksDBConfigTest, ReadBarrierAndUnbatchedDeferredWrites) {
    const std::string path = dbPath("barriers");
    lsmio::LSMIOStoreRDB lc(path);
    std::string value;
    EXPECT_TRUE(lc.put("k", std::string("v"), false));
    EXPECT_TRUE(lc.get("k", &value));
    EXPECT_EQ(value, "v");
    EXPECT_TRUE(lc.readBarrier());
    EXPECT_TRUE(lc.del("k", false));
    EXPECT_FALSE(lc.get("k", &value));
    EXPECT_TRUE(lc.readBarrier());
    EXPECT_TRUE(lc.writeBarrier());
    EXPECT_FALSE(lc.get("k", &value));
}

int main(int argc, char** argv) {
    lsmio::initLSMIODebug(argv[0]);
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
