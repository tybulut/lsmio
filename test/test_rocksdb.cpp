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
#include <rocksdb/version.h>

#include <algorithm>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iostream>
#include <iterator>
#include <leveldb/db.h>
#include <lsmio/manager/manager.hpp>
#include <lsmio/manager/store/store_rdb.hpp>
#include <manager/store/NoSyncRocksFileSystem.hpp>
#include <manager/store/PageCacheGate.hpp>
#include <manager/store/PageCacheGateOverride.hpp>
#include <map>
#include <memory>
#include <optional>
#include <stdexcept>
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
    const bool codec_supported =
        std::any_of(supported.begin(), supported.end(), [](rocksdb::CompressionType c) {
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

// Read-only store (INV-18, GT6). The suite name starts with RocksDB (plan 0.4 naming rule).
namespace {

struct RdbFileState {
    std::uintmax_t size;
    std::filesystem::file_time_type mtime;
    bool operator==(const RdbFileState& other) const {
        return size == other.size && mtime == other.mtime;
    }
};
using RdbDirSnapshot = std::map<std::string, RdbFileState>;

RdbDirSnapshot snapshotRdbDir(const std::string& f_path) {
    RdbDirSnapshot snap;
    for (const auto& entry : std::filesystem::directory_iterator(f_path)) {
        snap[entry.path().filename().string()] = {entry.file_size(), entry.last_write_time()};
    }
    return snap;
}

class RocksDBReadOnlyTest : public LSMIORocksDBConfigTest {
  protected:
    static constexpr int kKeys = 50;

    static std::string keyOf(int f_index) {
        return "key" + std::to_string(f_index);
    }

    static std::string valueOf(int f_index) {
        return "value" + std::to_string(f_index);
    }

    // Writer (overWrite) puts kKeys keys and closes.
    void writeStore(const std::string& f_path) {
        lsmio::LSMIOStoreRDB writer(f_path, true);
        for (int i = 0; i < kKeys; i++) {
            ASSERT_TRUE(writer.put(keyOf(i), valueOf(i)));
        }
        writer.close();
    }

    void expectAllKeys(lsmio::LSMIOStoreRDB& f_store) {
        for (int i = 0; i < kKeys; i++) {
            std::string value;
            EXPECT_TRUE(f_store.get(keyOf(i), &value)) << keyOf(i);
            EXPECT_EQ(value, valueOf(i));
        }
    }
};

}  // namespace

TEST_F(RocksDBReadOnlyTest, ReadsWhatWriterWrote) {
    const std::string path = dbPath("ro-reads");
    writeStore(path);

    lsmio::LSMIOStoreRDB reader(path, false, true);
    expectAllKeys(reader);
    std::string value;
    EXPECT_FALSE(reader.get("absent", &value));
}

TEST_F(RocksDBReadOnlyTest, BarrierAndCloseDoNotFlush) {
    const std::string path = dbPath("ro-barrier");
    writeStore(path);
    const RdbDirSnapshot before = snapshotRdbDir(path);

    lsmio::LSMIOStoreRDB reader(path, false, true);
    EXPECT_TRUE(reader.writeBarrier());
    EXPECT_TRUE(reader.readBarrier());
    expectAllKeys(reader);
    reader.close();

    EXPECT_TRUE(snapshotRdbDir(path) == before);
}

TEST_F(RocksDBReadOnlyTest, MutationsReturnFalse) {
    const std::string path = dbPath("ro-mutations");
    writeStore(path);
    const RdbDirSnapshot before = snapshotRdbDir(path);

    {
        lsmio::LSMIOStoreRDB reader(path, false, true);
        EXPECT_FALSE(reader.put("new-put", std::string("v")));
        EXPECT_FALSE(reader.put("new-put-moved", std::string("v"), false));
        EXPECT_FALSE(reader.putBytes("new-bytes", std::string_view("v")));
        EXPECT_FALSE(reader.metaPut("new-meta", std::string("v")));
        EXPECT_FALSE(reader.del(keyOf(0)));

        std::string value;
        EXPECT_FALSE(reader.get("new-put", &value));
        EXPECT_FALSE(reader.get("new-bytes", &value));
        EXPECT_TRUE(reader.get(keyOf(0), &value));
        EXPECT_EQ(value, valueOf(0));
    }
    EXPECT_TRUE(snapshotRdbDir(path) == before);

    lsmio::LSMIOStoreRDB writer(path);
    std::string value;
    EXPECT_FALSE(writer.get("new-put", &value));
    EXPECT_FALSE(writer.get("new-put-moved", &value));
    EXPECT_FALSE(writer.get("new-bytes", &value));
    EXPECT_FALSE(writer.metaGet("new-meta", &value));
    expectAllKeys(writer);
}

TEST_F(RocksDBReadOnlyTest, OverWriteWithReadOnlyRefused) {
    const std::string path = dbPath("ro-overwrite");
    writeStore(path);
    const RdbDirSnapshot before = snapshotRdbDir(path);

    try {
        lsmio::LSMIOStoreRDB refused(path, true, true);
        FAIL() << "overWrite with readOnly must throw";
    } catch (const std::invalid_argument& e) {
        EXPECT_NE(std::string(e.what()).find("overWrite and readOnly"), std::string::npos);
    }
    EXPECT_TRUE(snapshotRdbDir(path) == before);

    lsmio::LSMIOStoreRDB reader(path, false, true);
    expectAllKeys(reader);
}

TEST_F(RocksDBReadOnlyTest, WalWrittenStoreReadsBack) {
    lsmio::gConfigLSMIO.enableWAL = true;
    const std::string path = dbPath("ro-wal");

    const std::string crash_image = dbPath("ro-wal-image");

    lsmio::LSMIOStoreRDB writer(path, true);
    for (int i = 0; i < kKeys; i++) {
        ASSERT_TRUE(writer.put(keyOf(i), valueOf(i)));
    }
    // The writer has not flushed, so the keys are only in its write-ahead log. A copy of the
    // directory taken now is a crash image with no writer attached: it holds the log and no table,
    // so a read-only open of it can read the keys only by replaying the log. No store is opened
    // read-only while the writer is open (rocksdb/db.h: undefined for the read-only instance).
    ASSERT_GT(walBytes(path), 0u);
    std::filesystem::copy(path, crash_image, std::filesystem::copy_options::recursive);
    ASSERT_GT(walBytes(crash_image), 0u);
    writer.close();

    {
        lsmio::LSMIOStoreRDB image_reader(crash_image, false, true);
        expectAllKeys(image_reader);
    }

    // The plan's order: after the writer closed (flushed), a read-only store reads every key.
    lsmio::LSMIOStoreRDB reader(path, false, true);
    expectAllKeys(reader);
}

// Verified-build gate (INV-20) and its test admission seam (INV-20b). This binary links the store
// library, which holds both engines, so it reaches every branch of PageCacheGate.cpp.
namespace {

using lsmio::LibraryBuild;
using lsmio::StorageType;
using lsmio::VerifiedBuild;

const std::string kLinux = "linux-x86_64";

std::vector<VerifiedBuild> oneEntryTable() {
    return {{StorageType::RocksDB, {9, 11, 2, kLinux}, "synthetic"}};
}

}  // namespace

TEST(RocksDBGateTest, BuildListedMatchesExactBuildOnly) {
    const auto table = oneEntryTable();
    EXPECT_TRUE(lsmio::buildListed(table, StorageType::RocksDB, {9, 11, 2, kLinux}));
    EXPECT_FALSE(lsmio::buildListed(table, StorageType::RocksDB, {9, 11, 3, kLinux}));
    EXPECT_FALSE(lsmio::buildListed(table, StorageType::RocksDB, {9, 12, 2, kLinux}));
    EXPECT_FALSE(lsmio::buildListed(table, StorageType::RocksDB, {10, 11, 2, kLinux}));
    EXPECT_FALSE(lsmio::buildListed(table, StorageType::RocksDB, {9, 11, 2, "darwin-arm64"}));
    EXPECT_FALSE(lsmio::buildListed(table, StorageType::LevelDB, {9, 11, 2, kLinux}));
    EXPECT_FALSE(lsmio::buildListed({}, StorageType::RocksDB, {9, 11, 2, kLinux}));
}

TEST(RocksDBGateTest, BuildListedMatchesLevelDBWithoutPatch) {
    const std::vector<VerifiedBuild> table = {
        {StorageType::LevelDB, {1, 23, -1, kLinux}, "synthetic"}};
    EXPECT_TRUE(lsmio::buildListed(table, StorageType::LevelDB, {1, 23, -1, kLinux}));
    EXPECT_FALSE(lsmio::buildListed(table, StorageType::LevelDB, {1, 23, 0, kLinux}));
    EXPECT_FALSE(lsmio::buildListed(table, StorageType::RocksDB, {1, 23, -1, kLinux}));
}

TEST(RocksDBGateTest, ResolveBuildAgreesOrReportsDisagreement) {
    const LibraryBuild compile_time{9, 11, 2, kLinux};
    const auto absent = lsmio::resolveBuild(compile_time, std::nullopt);
    ASSERT_TRUE(absent.has_value());
    EXPECT_TRUE(*absent == compile_time);

    const auto equal = lsmio::resolveBuild(compile_time, compile_time);
    ASSERT_TRUE(equal.has_value());
    EXPECT_TRUE(*equal == compile_time);

    EXPECT_FALSE(lsmio::resolveBuild(compile_time, LibraryBuild{9, 11, 3, kLinux}).has_value());
}

TEST(RocksDBGateTest, VerifiedForRefusesDisagreementAndUnlistedBuilds) {
    const auto table = oneEntryTable();
    EXPECT_FALSE(lsmio::verifiedFor(table, StorageType::RocksDB, std::nullopt));
    EXPECT_TRUE(
        lsmio::verifiedFor(table, StorageType::RocksDB, LibraryBuild{9, 11, 2, kLinux}));
    EXPECT_FALSE(
        lsmio::verifiedFor(table, StorageType::RocksDB, LibraryBuild{9, 11, 3, kLinux}));
}

TEST(RocksDBGateTest, DescribeBuildNamesEngineAndBothVersionsOnDisagreement) {
    const LibraryBuild rocks{9, 11, 2, kLinux};
    EXPECT_EQ(lsmio::describeBuild(StorageType::RocksDB, rocks, std::nullopt),
              "RocksDB 9.11.2 linux-x86_64");
    EXPECT_EQ(lsmio::describeBuild(StorageType::RocksDB, rocks, rocks), "RocksDB 9.11.2 linux-x86_64");

    const std::string disagree =
        lsmio::describeBuild(StorageType::RocksDB, rocks, LibraryBuild{9, 11, 3, kLinux});
    EXPECT_NE(disagree.find("9.11.2"), std::string::npos) << disagree;
    EXPECT_NE(disagree.find("9.11.3"), std::string::npos) << disagree;
    EXPECT_NE(disagree.find("disagree"), std::string::npos) << disagree;

    EXPECT_EQ(lsmio::describeBuild(StorageType::LevelDB, {1, 23, -1, kLinux}, std::nullopt),
              "LevelDB 1.23 linux-x86_64");
}

TEST(RocksDBGateTest, DescribeBuildReadsAnUnparsableRunTimeVersionAsSuch) {
    // The marker runTimeBuild() uses for a version string that does not parse (NB36).
    const std::string text = lsmio::describeBuild(StorageType::RocksDB, {9, 11, 2, kLinux},
                                                  LibraryBuild{-1, -1, -1, "unparsable"});
    EXPECT_NE(text.find("run-time unparsable"), std::string::npos) << text;
    EXPECT_NE(text.find("disagree"), std::string::npos) << text;
    EXPECT_EQ(text.find("-1"), std::string::npos) << text;
}

TEST(RocksDBGateTest, ParseRocksVersionAcceptsExactTriples) {
    const auto nine = lsmio::parseRocksVersion("9.11.2", kLinux);
    ASSERT_TRUE(nine.has_value());
    EXPECT_TRUE(*nine == (LibraryBuild{9, 11, 2, kLinux}));

    const auto ten = lsmio::parseRocksVersion("10.6.2", "darwin-arm64");
    ASSERT_TRUE(ten.has_value());
    EXPECT_TRUE(*ten == (LibraryBuild{10, 6, 2, "darwin-arm64"}));
}

TEST(RocksDBGateTest, ParseRocksVersionRefusesEverythingElse) {
    for (const char* bad :
         {"", "9", "9.11", "9.11.2.1", "9.x.2", "x.11.2", "9.11.x", "9.11.2-rc", "-9.11.2",
          "9..2", "9.11.", "99999999999.1.1", "+9.11.2", " 9.11.2"}) {
        EXPECT_FALSE(lsmio::parseRocksVersion(bad, kLinux).has_value()) << "'" << bad << "'";
    }
}

TEST(RocksDBGateTest, CompiledPlatformIsOsDashArch) {
    const std::string platform = lsmio::compiledPlatform();
    EXPECT_FALSE(platform.empty());
    EXPECT_NE(platform.find('-'), std::string::npos) << platform;
}

TEST(RocksDBGateTest, EveryTableEntryNamesItsEvidence) {
    for (const auto& entry : lsmio::verifiedBuildTable()) {
        EXPECT_FALSE(entry.evidence.empty());
    }
}

TEST(RocksDBGateTest, WrapperCompiledInPerEngine) {
    EXPECT_FALSE(lsmio::pageCacheWrapperCompiledIn(StorageType::NativeDB));
    EXPECT_TRUE(lsmio::pageCacheWrapperCompiledIn(StorageType::LevelDB));
    EXPECT_EQ(lsmio::pageCacheWrapperCompiledIn(StorageType::RocksDB), lsmio::kRocksNoSyncCompiledIn);
    EXPECT_EQ(lsmio::kRocksNoSyncCompiledIn, LSMIO_ROCKSDB_NOSYNC_FS != 0);
}

TEST(RocksDBGateTest, NativeDBHasNoGate) {
    EXPECT_FALSE(lsmio::pageCacheVerified(StorageType::NativeDB));
    EXPECT_FALSE(lsmio::pageCacheAdmitted(StorageType::NativeDB));
    EXPECT_THROW(lsmio::compileTimeBuild(StorageType::NativeDB), std::invalid_argument);
}

TEST(RocksDBGateTest, CompileTimeBuildReportsTheHeaderVersions) {
    const LibraryBuild rocks = lsmio::compileTimeBuild(StorageType::RocksDB);
    EXPECT_TRUE(rocks == (LibraryBuild{ROCKSDB_MAJOR, ROCKSDB_MINOR, ROCKSDB_PATCH,
                                       lsmio::compiledPlatform()}));
    const LibraryBuild level = lsmio::compileTimeBuild(StorageType::LevelDB);
    EXPECT_TRUE(level == (LibraryBuild{leveldb::kMajorVersion, leveldb::kMinorVersion, -1,
                                       lsmio::compiledPlatform()}));
}

TEST(RocksDBGateTest, RunTimeBuildPerEngine) {
    EXPECT_FALSE(lsmio::runTimeBuild(StorageType::LevelDB).has_value());
#if LSMIO_ROCKSDB_NOSYNC_FS
    const auto running = lsmio::runTimeBuild(StorageType::RocksDB);
    ASSERT_TRUE(running.has_value());
    EXPECT_TRUE(*running == lsmio::compileTimeBuild(StorageType::RocksDB));
#else
    EXPECT_FALSE(lsmio::runTimeBuild(StorageType::RocksDB).has_value());
#endif
}

TEST(RocksDBGateTest, DescribeRunningBuildNamesTheVersions) {
    const std::string rocks = std::to_string(ROCKSDB_MAJOR) + "." + std::to_string(ROCKSDB_MINOR) +
                              "." + std::to_string(ROCKSDB_PATCH);
    EXPECT_NE(lsmio::describeRunningBuild(StorageType::RocksDB).find(rocks), std::string::npos);
    const std::string level =
        std::to_string(leveldb::kMajorVersion) + "." + std::to_string(leveldb::kMinorVersion);
    EXPECT_NE(lsmio::describeRunningBuild(StorageType::LevelDB).find(level), std::string::npos);
}

TEST(RocksDBGateOverrideTest, NoOverrideDecidesFromTheTable) {
    for (const StorageType engine : {StorageType::RocksDB, StorageType::LevelDB}) {
        EXPECT_EQ(lsmio::pageCacheAdmitted(engine), lsmio::pageCacheVerified(engine));
    }
}

TEST(RocksDBGateOverrideTest, AdmitAndDenyScopesDecideAndRestore) {
    {
        lsmio::PageCacheGateOverride admit(lsmio::GateDecision::Admit);
        EXPECT_EQ(lsmio::pageCacheAdmitted(StorageType::RocksDB),
                  lsmio::pageCacheWrapperCompiledIn(StorageType::RocksDB));
        EXPECT_TRUE(lsmio::pageCacheAdmitted(StorageType::LevelDB));
        // The seam never admits an engine without a wrapper.
        EXPECT_FALSE(lsmio::pageCacheAdmitted(StorageType::NativeDB));
    }
    {
        lsmio::PageCacheGateOverride deny(lsmio::GateDecision::Deny);
        EXPECT_FALSE(lsmio::pageCacheAdmitted(StorageType::RocksDB));
        EXPECT_FALSE(lsmio::pageCacheAdmitted(StorageType::LevelDB));
    }
    for (const StorageType engine : {StorageType::RocksDB, StorageType::LevelDB}) {
        EXPECT_EQ(lsmio::pageCacheAdmitted(engine), lsmio::pageCacheVerified(engine));
    }
}

TEST(RocksDBGateOverrideTest, SecondOverrideThrowsAndTheFirstStillDecides) {
    lsmio::PageCacheGateOverride first(lsmio::GateDecision::Deny);
    EXPECT_THROW(lsmio::PageCacheGateOverride second(lsmio::GateDecision::Admit),
                 std::logic_error);
    EXPECT_FALSE(lsmio::pageCacheAdmitted(StorageType::LevelDB));
}

namespace {

class NoSyncRocksFileSystemTest : public LSMIORocksDBConfigTest {
  protected:
    // A fresh directory for the test's files (removed in TearDown through the base class).
    std::string workDir(const std::string& name) {
        const std::string path = dbPath(name);
        std::filesystem::create_directories(path);
        return path;
    }

    static std::string readAll(const std::string& path) {
        std::ifstream in(path, std::ios::binary);
        return std::string(std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>());
    }
};

}  // namespace

#if LSMIO_ROCKSDB_NOSYNC_FS

namespace {

const rocksdb::IOOptions kIoOptions;
const rocksdb::FileOptions kFileOptions;

std::shared_ptr<rocksdb::FileSystem> noSyncFs() {
    return lsmio::noSyncRocksFileSystem();
}

}  // namespace

TEST_F(NoSyncRocksFileSystemTest, WritableFileSyncsAreCountedAndDataSurvives) {
    const std::string path = workDir("nosync-writable") + "/a.log";
    const std::uint64_t before = lsmio::interceptedRocksDBSyncCount();

    std::unique_ptr<rocksdb::FSWritableFile> file;
    ASSERT_TRUE(noSyncFs()->NewWritableFile(path, kFileOptions, &file, nullptr).ok());
    ASSERT_NE(file, nullptr);
    ASSERT_TRUE(file->Append(rocksdb::Slice("hello world"), kIoOptions, nullptr).ok());
    EXPECT_TRUE(file->Sync(kIoOptions, nullptr).ok());
    // Sync is a flush: the bytes are visible before Close (INV-17, nothing dropped).
    EXPECT_EQ(readAll(path), "hello world");
    EXPECT_EQ(lsmio::interceptedRocksDBSyncCount(), before + 1);
    EXPECT_TRUE(file->Fsync(kIoOptions, nullptr).ok());
    EXPECT_TRUE(file->RangeSync(0, 5, kIoOptions, nullptr).ok());
    EXPECT_EQ(lsmio::interceptedRocksDBSyncCount(), before + 3);
    EXPECT_TRUE(file->Close(kIoOptions, nullptr).ok());
    EXPECT_EQ(readAll(path), "hello world");
}

TEST_F(NoSyncRocksFileSystemTest, ReopenWritableFileAppendsAndSyncCounts) {
    const std::string path = workDir("nosync-reopen") + "/a.log";
    {
        std::ofstream out(path, std::ios::binary);
        out << "first,";
    }
    const std::uint64_t before = lsmio::interceptedRocksDBSyncCount();

    std::unique_ptr<rocksdb::FSWritableFile> file;
    ASSERT_TRUE(noSyncFs()->ReopenWritableFile(path, kFileOptions, &file, nullptr).ok());
    ASSERT_NE(file, nullptr);
    ASSERT_TRUE(file->Append(rocksdb::Slice("second"), kIoOptions, nullptr).ok());
    EXPECT_TRUE(file->Sync(kIoOptions, nullptr).ok());
    EXPECT_EQ(readAll(path), "first,second");
    EXPECT_EQ(lsmio::interceptedRocksDBSyncCount(), before + 1);
    EXPECT_TRUE(file->Close(kIoOptions, nullptr).ok());
}

TEST_F(NoSyncRocksFileSystemTest, ReuseWritableFileGivesFileWhoseSyncCounts) {
    const std::string dir = workDir("nosync-reuse");
    const std::string old_path = dir + "/old.log";
    const std::string new_path = dir + "/new.log";
    {
        std::ofstream out(old_path, std::ios::binary);
        out << "stale";
    }
    const std::uint64_t before = lsmio::interceptedRocksDBSyncCount();

    std::unique_ptr<rocksdb::FSWritableFile> file;
    const rocksdb::IOStatus status =
        noSyncFs()->ReuseWritableFile(new_path, old_path, kFileOptions, &file, nullptr);
    ASSERT_TRUE(status.ok()) << status.ToString();
    ASSERT_NE(file, nullptr);
    ASSERT_TRUE(file->Append(rocksdb::Slice("fresh"), kIoOptions, nullptr).ok());
    EXPECT_TRUE(file->Sync(kIoOptions, nullptr).ok());
    EXPECT_EQ(lsmio::interceptedRocksDBSyncCount(), before + 1);
    EXPECT_TRUE(file->Close(kIoOptions, nullptr).ok());
    EXPECT_FALSE(std::filesystem::exists(old_path));
    EXPECT_NE(readAll(new_path).find("fresh"), std::string::npos);
}

TEST_F(NoSyncRocksFileSystemTest, RandomRWFileSyncsAreCountedAndDataSurvives) {
    const std::string path = workDir("nosync-rw") + "/a.rw";
    {
        std::ofstream out(path, std::ios::binary);  // NewRandomRWFile opens an existing file
    }
    const std::uint64_t before = lsmio::interceptedRocksDBSyncCount();

    std::unique_ptr<rocksdb::FSRandomRWFile> file;
    ASSERT_TRUE(noSyncFs()->NewRandomRWFile(path, kFileOptions, &file, nullptr).ok());
    ASSERT_NE(file, nullptr);
    ASSERT_TRUE(file->Write(0, rocksdb::Slice("random"), kIoOptions, nullptr).ok());
    EXPECT_TRUE(file->Sync(kIoOptions, nullptr).ok());
    EXPECT_EQ(readAll(path), "random");
    EXPECT_TRUE(file->Fsync(kIoOptions, nullptr).ok());
    EXPECT_EQ(lsmio::interceptedRocksDBSyncCount(), before + 2);
    EXPECT_TRUE(file->Close(kIoOptions, nullptr).ok());
    EXPECT_EQ(readAll(path), "random");
}

TEST_F(NoSyncRocksFileSystemTest, DirectoryFsyncsAreCountedAndReportSuccess) {
    const std::string dir = workDir("nosync-dir");
    const std::uint64_t before = lsmio::interceptedRocksDBSyncCount();

    std::unique_ptr<rocksdb::FSDirectory> directory;
    ASSERT_TRUE(noSyncFs()->NewDirectory(dir, kIoOptions, &directory, nullptr).ok());
    ASSERT_NE(directory, nullptr);
    EXPECT_TRUE(directory->Fsync(kIoOptions, nullptr).ok());
    EXPECT_TRUE(directory->FsyncWithDirOptions(kIoOptions, nullptr, rocksdb::DirFsyncOptions())
                    .ok());
    EXPECT_EQ(lsmio::interceptedRocksDBSyncCount(), before + 2);
    EXPECT_TRUE(directory->Close(kIoOptions, nullptr).ok());
}

TEST_F(NoSyncRocksFileSystemTest, FactoryFailuresReturnTargetStatusAndCountNothing) {
    const std::string dir = workDir("nosync-fail");
    const std::string missing = dir + "/missing/x";
    const std::string missing_dir = dir + "/missing";
    const std::uint64_t before = lsmio::interceptedRocksDBSyncCount();

    std::unique_ptr<rocksdb::FSWritableFile> writable;
    EXPECT_FALSE(noSyncFs()->NewWritableFile(missing, kFileOptions, &writable, nullptr).ok());
    EXPECT_EQ(writable, nullptr);
    EXPECT_FALSE(noSyncFs()->ReopenWritableFile(missing, kFileOptions, &writable, nullptr).ok());
    EXPECT_EQ(writable, nullptr);
    // Reuse: the old name is missing and the new name is inside a missing directory.
    EXPECT_FALSE(
        noSyncFs()->ReuseWritableFile(missing, dir + "/no-old", kFileOptions, &writable, nullptr)
            .ok());
    EXPECT_EQ(writable, nullptr);

    std::unique_ptr<rocksdb::FSRandomRWFile> random_rw;
    EXPECT_FALSE(noSyncFs()->NewRandomRWFile(missing, kFileOptions, &random_rw, nullptr).ok());
    EXPECT_EQ(random_rw, nullptr);

    std::unique_ptr<rocksdb::FSDirectory> directory;
    EXPECT_FALSE(noSyncFs()->NewDirectory(missing_dir, kIoOptions, &directory, nullptr).ok());
    EXPECT_EQ(directory, nullptr);

    EXPECT_EQ(lsmio::interceptedRocksDBSyncCount(), before);
}

TEST_F(NoSyncRocksFileSystemTest, EnvIsOneProcessLifetimeObjectOverTheNoSyncFileSystem) {
    rocksdb::Env* env = lsmio::noSyncRocksEnv();
    ASSERT_NE(env, nullptr);
    EXPECT_EQ(env, lsmio::noSyncRocksEnv());
    EXPECT_NE(env, rocksdb::Env::Default());
    EXPECT_STREQ(env->GetFileSystem()->Name(), "LsmioNoSyncFileSystem");
    EXPECT_EQ(env->GetFileSystem().get(), noSyncFs().get());
    EXPECT_EQ(noSyncFs().get(), lsmio::noSyncRocksFileSystem().get());
}

#else

TEST_F(NoSyncRocksFileSystemTest, WrapperIsCompiledOutAndInterceptsNothing) {
    EXPECT_FALSE(lsmio::pageCacheWrapperCompiledIn(StorageType::RocksDB));
    EXPECT_EQ(lsmio::interceptedRocksDBSyncCount(), 0u);
}

#endif

// RocksDB store page-cache mode (INV-2, INV-17, INV-20): gate refusals and the E3 round trips.
namespace {

class RocksDBPageCacheBase : public LSMIORocksDBConfigTest {
  protected:
    void setMode(lsmio::Durability f_mode, bool f_use_sync = false) {
        lsmio::gConfigLSMIO.durability = f_mode;
        lsmio::gConfigLSMIO.useSync = f_use_sync;
    }

    static std::string rocksVersion() {
        return std::to_string(ROCKSDB_MAJOR) + "." + std::to_string(ROCKSDB_MINOR) + "." +
               std::to_string(ROCKSDB_PATCH);
    }

    // Creates a store with data in engine mode, closes it and returns its snapshot.
    RdbDirSnapshot makeEngineStore(const std::string& f_path) {
        setMode(lsmio::Durability::Engine);
        {
            lsmio::LSMIOStoreRDB store(f_path, true);
            EXPECT_TRUE(store.put("existing", std::string("value")));
            EXPECT_TRUE(store.writeBarrier());
            store.close();
        }
        return snapshotRdbDir(f_path);
    }

    static std::size_t sstCount(const std::string& f_path) {
        std::size_t count = 0;
        for (const auto& entry : std::filesystem::directory_iterator(f_path)) {
            if (entry.path().extension() == ".sst") {
                count++;
            }
        }
        return count;
    }
};

class RocksDBDurabilityGate : public RocksDBPageCacheBase {};

class RocksDBPageCache : public RocksDBPageCacheBase {
  protected:
    static constexpr int kKeys = 2000;

    static std::string keyOf(int f_index) {
        return "key" + std::to_string(f_index);
    }

    static std::string valueOf(int f_index) {
        return "value" + std::to_string(f_index) + std::string(300, 'v');
    }

    // Writer, read-only reader, overWrite reopen, all through the no-sync file system, with a
    // small write buffer and more data than it holds (E3). On a build without the wrapper the
    // page-cache open is refused instead, and no file is touched (INV-20 "Builds without the
    // wrapper").
    void roundTrip(const std::string& f_name) {
        const std::string path = dbPath(f_name);
        lsmio::gConfigLSMIO.writeBufferSize = 256 * 1024;
        setMode(lsmio::Durability::PageCache);
        lsmio::PageCacheGateOverride admit(lsmio::GateDecision::Admit);

#if LSMIO_ROCKSDB_NOSYNC_FS
        const std::uint64_t before = lsmio::interceptedRocksDBSyncCount();
        {
            lsmio::LSMIOStoreRDB writer(path, true);
            for (int i = 0; i < kKeys; i++) {
                ASSERT_TRUE(writer.put(keyOf(i), valueOf(i)));
            }
            ASSERT_TRUE(writer.writeBarrier());
            writer.close();
        }
        EXPECT_GT(lsmio::interceptedRocksDBSyncCount(), before);
        EXPECT_GE(sstCount(path), 1u);

        {
            lsmio::LSMIOStoreRDB reader(path, false, true);
            for (int i = 0; i < kKeys; i++) {
                std::string value;
                ASSERT_TRUE(reader.get(keyOf(i), &value)) << keyOf(i);
                EXPECT_EQ(value, valueOf(i));
            }
        }

        {
            lsmio::LSMIOStoreRDB again(path, true);
            std::string value;
            EXPECT_FALSE(again.get(keyOf(0), &value));
            again.close();
        }
#else
        try {
            lsmio::LSMIOStoreRDB writer(path, true);
            FAIL() << "page-cache open on a build without the wrapper must throw";
        } catch (const std::invalid_argument& e) {
            const std::string what = e.what();
            EXPECT_NE(what.find("RocksDB"), std::string::npos);
            EXPECT_NE(what.find("page-cache"), std::string::npos);
        }
        EXPECT_FALSE(std::filesystem::exists(path));
#endif
    }
};

}  // namespace

TEST_F(RocksDBDurabilityGate, DenyRefusesBeforeTouchingFiles) {
    const std::string path = dbPath("gate-deny");
    const RdbDirSnapshot before = makeEngineStore(path);
    setMode(lsmio::Durability::PageCache);
    lsmio::PageCacheGateOverride deny(lsmio::GateDecision::Deny);
    try {
        lsmio::LSMIOStoreRDB store(path, true);
        FAIL() << "page-cache open under Deny must throw";
    } catch (const std::invalid_argument& e) {
        const std::string what = e.what();
        EXPECT_NE(what.find("RocksDB"), std::string::npos);
        EXPECT_NE(what.find("page-cache"), std::string::npos);
        EXPECT_NE(what.find(rocksVersion()), std::string::npos);
    }
    EXPECT_TRUE(snapshotRdbDir(path) == before);
}

TEST_F(RocksDBDurabilityGate, NoOverrideFollowsTable) {
    const std::string path = dbPath("gate-table");
    const bool verified = lsmio::pageCacheVerified(lsmio::StorageType::RocksDB);
    EXPECT_EQ(lsmio::pageCacheAdmitted(lsmio::StorageType::RocksDB), verified);
    setMode(lsmio::Durability::PageCache);
    if (verified) {
        lsmio::LSMIOStoreRDB store(path, true);
        EXPECT_TRUE(store.put("k", std::string("v")));
        store.close();
        EXPECT_TRUE(std::filesystem::exists(path));
    } else {
        try {
            lsmio::LSMIOStoreRDB store(path, true);
            FAIL() << "page-cache open of an unverified build must throw";
        } catch (const std::invalid_argument& e) {
            const std::string what = e.what();
            EXPECT_NE(what.find("RocksDB"), std::string::npos);
            EXPECT_NE(what.find("page-cache"), std::string::npos);
            EXPECT_NE(what.find(rocksVersion()), std::string::npos);
        }
        EXPECT_FALSE(std::filesystem::exists(path));
    }
}

TEST_F(RocksDBDurabilityGate, EngineModeIgnoresDeny) {
    const std::string path = dbPath("gate-engine");
    setMode(lsmio::Durability::Engine);
    lsmio::PageCacheGateOverride deny(lsmio::GateDecision::Deny);
    {
        lsmio::LSMIOStoreRDB store(path, true);
        EXPECT_TRUE(store.put("key", std::string("value")));
        EXPECT_TRUE(store.writeBarrier());
        store.close();
    }
    lsmio::LSMIOStoreRDB reader(path, false);
    std::string value;
    EXPECT_TRUE(reader.get("key", &value));
    EXPECT_EQ(value, "value");
}

TEST_F(RocksDBDurabilityGate, UseSyncRefusedBeforeGate) {
    const std::string path = dbPath("gate-usesync");
    const RdbDirSnapshot before = makeEngineStore(path);
    setMode(lsmio::Durability::PageCache, true);
    for (const lsmio::GateDecision decision :
         {lsmio::GateDecision::Admit, lsmio::GateDecision::Deny}) {
        lsmio::PageCacheGateOverride scope(decision);
        try {
            lsmio::LSMIOStoreRDB store(path, true);
            FAIL() << "page-cache with useSync must throw";
        } catch (const std::invalid_argument& e) {
            const std::string what = e.what();
            EXPECT_NE(what.find("useSync"), std::string::npos);
            EXPECT_NE(what.find("page-cache"), std::string::npos);
            // The useSync refusal comes first, so the gate's build text is not in it (NB21).
            EXPECT_EQ(what.find("verified page-cache build"), std::string::npos);
        }
        EXPECT_TRUE(snapshotRdbDir(path) == before);
    }

    // Engine mode with useSync opens as before, with the WAL off (sync ignored) and on (sync).
    for (const bool wal : {false, true}) {
        setMode(lsmio::Durability::Engine, true);
        lsmio::gConfigLSMIO.enableWAL = wal;
        lsmio::LSMIOStoreRDB store(path, false);
        std::string value;
        EXPECT_TRUE(store.put("synced" + std::to_string(wal), std::string("yes")));
        EXPECT_TRUE(store.get("existing", &value));
        EXPECT_EQ(value, "value");
        EXPECT_TRUE(store.get("synced" + std::to_string(wal), &value));
        EXPECT_EQ(value, "yes");
    }
}

TEST_F(RocksDBPageCache, DefaultFlagsRoundTrip) {
    roundTrip("e3-default");
}

TEST_F(RocksDBPageCache, WalFlagRoundTrip) {
    lsmio::gConfigLSMIO.enableWAL = true;
    roundTrip("e3-wal");
}

TEST_F(RocksDBPageCache, MmapFlagRoundTrip) {
    lsmio::gConfigLSMIO.enableMMAP = true;
    roundTrip("e3-mmap");
}

// RocksDB's mmap writer extends files only through fallocate; without it the first table file dies
// with SIGBUS. The store therefore turns allow_fallocate on for mmap and warns when preAllocate
// did not ask for it.
namespace {

class RocksDBMmapFallocate : public RocksDBPageCacheBase {
  protected:
    static constexpr int kKeys = 2000;

    // Opens a store with the given flags, writes enough for a table file, closes, reopens and
    // reads every value back, and returns the constructor's stderr and the persisted
    // allow_fallocate. The capture holds only the constructor, with no ASSERT inside it.
    void run(const std::string& f_name, bool f_mmap, bool f_prealloc, std::string* f_log,
             bool* f_fallocate) {
        const std::string path = dbPath(f_name);
        lsmio::gConfigLSMIO.writeBufferSize = 256 * 1024;
        lsmio::gConfigLSMIO.enableMMAP = f_mmap;
        lsmio::gConfigLSMIO.preAllocate = f_prealloc;
        {
            testing::internal::CaptureStderr();
            auto writer = std::make_unique<lsmio::LSMIOStoreRDB>(path, true);
            *f_log = testing::internal::GetCapturedStderr();
            for (int i = 0; i < kKeys; i++) {
                ASSERT_TRUE(writer->put("key" + std::to_string(i),
                                        "value" + std::to_string(i) + std::string(300, 'v')));
            }
            ASSERT_TRUE(writer->writeBarrier());
            writer->close();
        }
        EXPECT_GE(sstCount(path), 1u);
        {
            lsmio::LSMIOStoreRDB reader(path, false, true);
            for (int i = 0; i < kKeys; i++) {
                std::string value;
                ASSERT_TRUE(reader.get("key" + std::to_string(i), &value)) << i;
                EXPECT_EQ(value, "value" + std::to_string(i) + std::string(300, 'v'));
            }
        }
        rocksdb::ConfigOptions config_options;
        rocksdb::DBOptions db_options;
        std::vector<rocksdb::ColumnFamilyDescriptor> cf_descs;
        const rocksdb::Status s =
            rocksdb::LoadLatestOptions(config_options, path, &db_options, &cf_descs);
        ASSERT_TRUE(s.ok()) << s.ToString();
        *f_fallocate = db_options.allow_fallocate;
    }

    static bool warned(const std::string& f_log) {
        return f_log.find("mmap writes need fallocate; enabling allow_fallocate (preAllocate not "
                          "set)") != std::string::npos;
    }
};

}  // namespace

TEST_F(RocksDBMmapFallocate, MmapWithoutPreAllocateEnablesFallocateAndWarns) {
    std::string log;
    bool fallocate = false;
    run("mmap-only", true, false, &log, &fallocate);
    EXPECT_TRUE(fallocate);
    EXPECT_TRUE(warned(log)) << log;
}

TEST_F(RocksDBMmapFallocate, MmapWithPreAllocateDoesNotWarn) {
    std::string log;
    bool fallocate = false;
    run("mmap-prealloc", true, true, &log, &fallocate);
    EXPECT_TRUE(fallocate);
    EXPECT_FALSE(warned(log)) << log;
}

TEST_F(RocksDBMmapFallocate, PreAllocateWithoutMmapDoesNotWarn) {
    std::string log;
    bool fallocate = false;
    run("prealloc-only", false, true, &log, &fallocate);
    EXPECT_TRUE(fallocate);
    EXPECT_FALSE(warned(log)) << log;
}

TEST_F(RocksDBMmapFallocate, NeitherLeavesFallocateOffAndDoesNotWarn) {
    std::string log;
    bool fallocate = true;
    run("neither", false, false, &log, &fallocate);
    EXPECT_FALSE(fallocate);
    EXPECT_FALSE(warned(log)) << log;
}

#if LSMIO_ROCKSDB_NOSYNC_FS
// Page-cache mode exists only on builds with the no-sync wrapper; the others refuse it.
TEST_F(RocksDBMmapFallocate, PageCacheDurabilityWarnsToo) {
    setMode(lsmio::Durability::PageCache);
    lsmio::PageCacheGateOverride admit(lsmio::GateDecision::Admit);
    std::string log;
    bool fallocate = false;
    run("mmap-pagecache", true, false, &log, &fallocate);
    EXPECT_TRUE(fallocate);
    EXPECT_TRUE(warned(log)) << log;
}
#endif

namespace {

// Opens the protected batch entry points of the store, which are private in LSMIOStoreRDB
class RdbBatchAccess : public lsmio::LSMIOStoreRDB {
  public:
    using lsmio::LSMIOStoreRDB::LSMIOStoreRDB;
    using lsmio::LSMIOStore::_batchMutation;
    using lsmio::LSMIOStore::startBatch;
    using lsmio::LSMIOStore::stopBatch;
};

const lsmio::MutationType kRdbUnknownMutation = static_cast<lsmio::MutationType>(99);

class RocksDBStoreFailure : public LSMIORocksDBConfigTest {
  protected:
    static std::string failureMessage(const std::function<void()>& f_body) {
        try {
            f_body();
        } catch (const std::invalid_argument& e) {
            return e.what();
        }
        return "";
    }
};

}  // namespace

TEST_F(RocksDBStoreFailure, ReadOnlyOpenOfMissingDatabaseThrowsAndCreatesNothing) {
    const std::string path = dbPath("fail-ro-missing");

    const std::string message =
        failureMessage([&] { lsmio::LSMIOStoreRDB store(path, false, true); });
    EXPECT_NE(message.find("Failed to open database"), std::string::npos) << message;
    // RocksDB may leave an empty directory for its info log, but no database
    EXPECT_FALSE(std::filesystem::exists(path + "/CURRENT"));
}

TEST_F(RocksDBStoreFailure, ReadWriteOpenUnderRegularFileThrowsAndLeavesItUntouched) {
    const std::string blocker = dbPath("fail-rw-blocker");
    {
        std::ofstream out(blocker);
        out << "not a directory";
    }
    const std::string path = blocker + "/db";

    const std::string message = failureMessage([&] { lsmio::LSMIOStoreRDB store(path); });
    EXPECT_NE(message.find("Failed to open database"), std::string::npos) << message;

    EXPECT_TRUE(std::filesystem::is_regular_file(blocker));
    EXPECT_EQ(std::filesystem::file_size(blocker), std::string("not a directory").size());
    EXPECT_FALSE(std::filesystem::exists(path));
}

TEST_F(RocksDBStoreFailure, OverWriteOfOpenStoreFailsAndKeepsTheLiveStore) {
    const std::string path = dbPath("fail-destroy-held");
    lsmio::LSMIOStoreRDB live(path);
    ASSERT_TRUE(live.put("held", std::string("value")));
    ASSERT_TRUE(live.writeBarrier());

    // This process already holds the database LOCK, so DestroyDB cannot take it
    const std::string message = failureMessage([&] { lsmio::LSMIOStoreRDB again(path, true); });
    EXPECT_NE(message.find("Failed to remove database"), std::string::npos) << message;

    std::string value;
    EXPECT_TRUE(live.get("held", &value));
    EXPECT_EQ(value, "value");
    EXPECT_TRUE(live.put("after", std::string("still-writable")));
    EXPECT_TRUE(live.get("after", &value));
    EXPECT_EQ(value, "still-writable");
}

TEST_F(RocksDBStoreFailure, StartAndStopBatchAreNoOpsThatSucceed) {
    RdbBatchAccess store(dbPath("fail-batch-access"));

    EXPECT_TRUE(store.startBatch());
    EXPECT_TRUE(store.put("direct", std::string("v"), false));  // writes at once
    EXPECT_TRUE(store.stopBatch());

    std::string value;
    EXPECT_TRUE(store.get("direct", &value));
    EXPECT_EQ(value, "v");
}

TEST_F(RocksDBStoreFailure, UnknownMutationThrowsAndLeavesTheStoreUsable) {
    RdbBatchAccess store(dbPath("fail-unknown"));
    ASSERT_TRUE(store.put("k", std::string("v")));

    const std::string message = failureMessage(
        [&] { store._batchMutation(kRdbUnknownMutation, "k", std::string("x"), true); });
    EXPECT_NE(message.find("Mutation not implemented"), std::string::npos) << message;

    std::string value;
    EXPECT_TRUE(store.get("k", &value));
    EXPECT_EQ(value, "v");
}

TEST_F(RocksDBStoreFailure, UnknownMutationOnDeferredPathThrowsAndLeavesTheStoreUsable) {
    RdbBatchAccess store(dbPath("fail-unknown-deferred"));
    ASSERT_TRUE(store.put("k", std::string("v")));

    const std::string message = failureMessage(
        [&] { store._batchMutation(kRdbUnknownMutation, "k", std::string("x"), false); });
    EXPECT_NE(message.find("Mutation not implemented"), std::string::npos) << message;

    std::string value;
    EXPECT_TRUE(store.get("k", &value));
    EXPECT_EQ(value, "v");
}

int main(int argc, char** argv) {
    lsmio::initLSMIODebug(argv[0]);
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
