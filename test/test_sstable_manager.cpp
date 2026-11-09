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
#include <sys/stat.h>
#include <unistd.h>

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iterator>
#include <lsmio/manager/store/native/MemtableVectorNoSort.hpp>
#include <lsmio/manager/store/native/SSTableManager.hpp>
#include <lsmio/manager/store/native/StoreNative.hpp>
#include <sstream>
#include <stdexcept>
#include <thread>
#include <utility>
#include <vector>

#if defined(__linux__)
#if defined(__has_feature)
#if __has_feature(address_sanitizer) || __has_feature(thread_sanitizer) || \
    __has_feature(memory_sanitizer)
#define LSMIO_TEST_RLIMIT_AS 0
#endif
#endif
#if !defined(LSMIO_TEST_RLIMIT_AS) && \
    (defined(__SANITIZE_ADDRESS__) || defined(__SANITIZE_THREAD__))
#define LSMIO_TEST_RLIMIT_AS 0
#endif
#if !defined(LSMIO_TEST_RLIMIT_AS)
#define LSMIO_TEST_RLIMIT_AS 1
#endif
#else
#define LSMIO_TEST_RLIMIT_AS 0
#endif

using namespace lsmio;

class SSTableManagerTest : public ::testing::Test {
  protected:
    std::string dbPath = "test_sstable_mgr_db";
    std::unique_ptr<SSTableManager> mgr;
    LSMIOConfig m_backup_config;

    void SetUp() override {
        m_backup_config = gConfigLSMIO;
        const testing::TestInfo* const test_info =
            testing::UnitTest::GetInstance()->current_test_info();
        dbPath = std::string("test_sstable_mgr_db_") + test_info->name();

        if (std::filesystem::exists(dbPath)) {
            std::filesystem::remove_all(dbPath);
        }
        std::filesystem::create_directories(dbPath);

        mgr = std::make_unique<SSTableManager>(dbPath, 10, 0);
    }

    void TearDown() override {
        gConfigLSMIO = m_backup_config;
        mgr.reset();
        if (std::filesystem::exists(dbPath)) {
            std::filesystem::remove_all(dbPath);
        }
    }
};

TEST_F(SSTableManagerTest, FlushAndGet) {
    MemtableVectorNoSort m;
    m.add("key1", "val1");
    m.add("key2", "val2");

    std::vector<char> buf(1024);
    ASSERT_TRUE(mgr->flushMemtable(m, buf));

    std::string val;
    EXPECT_TRUE(mgr->get("key1", val));
    EXPECT_EQ(val, "val1");

    EXPECT_TRUE(mgr->get("key2", val));
    EXPECT_EQ(val, "val2");

    EXPECT_FALSE(mgr->get("key3", val));
}

TEST_F(SSTableManagerTest, Recovery) {
    {
        MemtableVectorNoSort m;
        m.add("key1", "val1");
        std::vector<char> buf(1024);
        mgr->flushMemtable(m, buf);
    }

    // Simulate restart
    mgr.reset();  // Destroy old manager

    // Create new manager (triggers recovery in constructor)
    auto new_mgr = std::make_unique<SSTableManager>(dbPath, 10, 0);

    std::string val;
    EXPECT_TRUE(new_mgr->get("key1", val));
    EXPECT_EQ(val, "val1");
}

TEST_F(SSTableManagerTest, Tombstone) {
    MemtableVectorNoSort m;
    m.add("key1", MEMTABLE_TOMBSTONE);
    std::vector<char> buf(1024);
    mgr->flushMemtable(m, buf);

    std::string val;
    EXPECT_TRUE(mgr->get("key1", val));
    EXPECT_EQ(val, MEMTABLE_TOMBSTONE);
}

TEST_F(SSTableManagerTest, Scan) {
    MemtableVectorNoSort m1;
    m1.add("prefix/a", "1");
    std::vector<char> buf(1024);
    mgr->flushMemtable(m1, buf);

    MemtableVectorNoSort m2;
    m2.add("prefix/b", "2");
    mgr->flushMemtable(m2, buf);

    std::map<std::string, std::string> results;
    std::set<std::string> deleted;

    EXPECT_TRUE(mgr->scan("prefix/", results, deleted));
    EXPECT_EQ(results.size(), 2);
    EXPECT_EQ(results["prefix/a"], "1");
    EXPECT_EQ(results["prefix/b"], "2");
}

TEST_F(SSTableManagerTest, FooterIndexWithManualOffset) {
    gConfigLSMIO.footerIndex = true;
    gConfigLSMIO.manualOffset = true;

    {
        MemtableVectorNoSort m;
        m.add("key1", "val1");
        std::vector<char> buf(1024);
        mgr->flushMemtable(m, buf);
    }

    mgr.reset();
    auto new_mgr = std::make_unique<SSTableManager>(dbPath, 10, 0);
    std::string val;
    EXPECT_TRUE(new_mgr->get("key1", val));
    EXPECT_EQ(val, "val1");
}

TEST_F(SSTableManagerTest, CorruptedFooterFallback) {
    gConfigLSMIO.footerIndex = true;
    {
        MemtableVectorNoSort m;
        m.add("key1", "val1");
        std::vector<char> buf(1024);
        mgr->flushMemtable(m, buf);
    }
    mgr.reset();

    // Corrupt the footer manually
    for (const auto& entry : std::filesystem::directory_iterator(dbPath)) {
        if (entry.path().extension() == ".sst") {
            std::fstream f(entry.path(), std::ios::in | std::ios::out | std::ios::binary);
            f.seekp(0, std::ios::end);
            f.seekp(-4, std::ios::cur);
            char bad_magic[4] = {'B', 'A', 'D', '0'};
            f.write(bad_magic, 4);
            f.close();
            break;
        }
    }

    auto new_mgr = std::make_unique<SSTableManager>(dbPath, 10, 0);
    std::string val;
    EXPECT_TRUE(new_mgr->get("key1", val));  // Should fallback to sequential slow path
    EXPECT_EQ(val, "val1");
}

TEST_F(SSTableManagerTest, PreallocAndFooterIndex) {
    gConfigLSMIO.preAllocate = true;
    gConfigLSMIO.footerIndex = true;

    // The fixture manager was built without preallocation; shut it down and
    // recreate it with a real preallocation size so the .sst is ftruncated large
    // and the flush must trim it back for the footer magic to land at physical EOF.
    mgr.reset();
    std::filesystem::remove_all(dbPath);
    std::filesystem::create_directories(dbPath);

    constexpr size_t pre_alloc_bytes = 64 * 1024;
    mgr = std::make_unique<SSTableManager>(dbPath, 10, pre_alloc_bytes);
    {
        MemtableVectorNoSort m;
        m.add("key1", "val1");
        std::vector<char> buf(1024);
        ASSERT_TRUE(mgr->flushMemtable(m, buf));
    }
    mgr.reset();

    // The flushed SSTable must have been resized down from the preallocated
    // size, leaving the footer magic at physical EOF. Untouched pool files may
    // remain at the full preallocated size, so look for at least one trimmed file.
    bool found_trimmed_sst = false;
    for (const auto& entry : std::filesystem::directory_iterator(dbPath)) {
        auto size = std::filesystem::file_size(entry.path());
        if (entry.path().extension() == ".sst" && size > 0 && size < pre_alloc_bytes) {
            found_trimmed_sst = true;
        }
    }
    EXPECT_TRUE(found_trimmed_sst);

    auto new_mgr = std::make_unique<SSTableManager>(dbPath, 10, 0);
    std::string val;
    EXPECT_TRUE(new_mgr->get("key1", val));
    EXPECT_EQ(val, "val1");
}

TEST_F(SSTableManagerTest, CreateMemtableThrowsOnUnknown) {
    gConfigLSMIO.memtable = static_cast<lsmio::MemtableType>(999);
    // The library builds with -fno-rtti, so an exception thrown inside the
    // lsmio dylib cannot be matched by type across the library boundary on
    // macOS; only a catch-all sees it. The throw site is
    // LSMIOStoreNative::createMemtable (std::invalid_argument).
    EXPECT_ANY_THROW(LSMIOStoreNative(dbPath, true));
}

TEST_F(SSTableManagerTest, MmapRead) {
    gConfigLSMIO.enableMMAP = true;
    gConfigLSMIO.enablePread = false;

    MemtableVectorNoSort m;
    m.add("mmap_k1", "mmap_v1");
    m.add("mmap_k2", "mmap_v2");
    m.add("mmap_k3", "mmap_v3");

    std::vector<char> buf(1024);
    ASSERT_TRUE(mgr->flushMemtable(m, buf));

    std::string val;
    EXPECT_TRUE(mgr->get("mmap_k1", val));
    EXPECT_EQ(val, "mmap_v1");

    EXPECT_TRUE(mgr->get("mmap_k2", val));
    EXPECT_EQ(val, "mmap_v2");

    EXPECT_TRUE(mgr->get("mmap_k3", val));
    EXPECT_EQ(val, "mmap_v3");

    EXPECT_FALSE(mgr->get("mmap_missing", val));

    // Test scan under mmap
    std::map<std::string, std::string> results;
    std::set<std::string> deleted;
    EXPECT_TRUE(mgr->scan("mmap_k", results, deleted));
    EXPECT_EQ(results.size(), 3);
    EXPECT_EQ(results["mmap_k1"], "mmap_v1");
    EXPECT_EQ(results["mmap_k2"], "mmap_v2");
    EXPECT_EQ(results["mmap_k3"], "mmap_v3");

    // Test recovery under mmap
    mgr.reset();
    auto new_mgr = std::make_unique<SSTableManager>(dbPath, 10, 0);
    val.clear();
    EXPECT_TRUE(new_mgr->get("mmap_k2", val));
    EXPECT_EQ(val, "mmap_v2");

    results.clear();
    deleted.clear();
    EXPECT_TRUE(new_mgr->scan("mmap_k", results, deleted));
    EXPECT_EQ(results.size(), 3);
}

TEST_F(SSTableManagerTest, PreadReadSmallAndLarge) {
    gConfigLSMIO.enableMMAP = false;
    gConfigLSMIO.enablePread = true;

    MemtableVectorNoSort m;
    m.add("small_key", "small_val");

    // Medium value: 65,535 B (baseline benchmark value size, which with framing is 65,559 B).
    // Under 64 KiB buffer this was missing the speculative fast path (BUG-3).
    // Under 128 KiB buffer this hits the single-stage fast path.
    std::string medium_val(65535, 'M');
    m.add("medium_key", medium_val);

    // Large value > 128 KiB to trigger pread speculative buffer slow path (2-stage pread)
    std::string large_val(160 * 1024, 'Z');
    m.add("large_key", large_val);

    std::vector<char> buf(128 * 1024);
    ASSERT_TRUE(mgr->flushMemtable(m, buf));

    std::string val;
    // Fast path (< 128 KiB)
    EXPECT_TRUE(mgr->get("small_key", val));
    EXPECT_EQ(val, "small_val");

    EXPECT_TRUE(mgr->get("medium_key", val));
    EXPECT_EQ(val.size(), 65535);
    EXPECT_EQ(val, medium_val);
    // BUG-3 regression: this exact size (8 + 10-byte key + 65535 = 65553 B)
    // exceeded the old 64 KiB buffer and would have silently taken the slow
    // path there. Both paths return the correct value, so only a counter
    // (not the value assertions above) can prove the fast path was taken.
    EXPECT_EQ(mgr->getPreadSlowPathCount(), 0u);

    // Slow path (> 128 KiB)
    EXPECT_TRUE(mgr->get("large_key", val));
    EXPECT_EQ(val.size(), 160 * 1024);
    EXPECT_EQ(val, large_val);
    EXPECT_EQ(mgr->getPreadSlowPathCount(), 1u);

    EXPECT_FALSE(mgr->get("non_existent", val));

    // Test scan under pread
    std::map<std::string, std::string> results;
    std::set<std::string> deleted;
    EXPECT_TRUE(mgr->scan("large_", results, deleted));
    EXPECT_EQ(results.size(), 1);
    EXPECT_EQ(results["large_key"], large_val);

    // Test recovery under pread
    mgr.reset();
    auto new_mgr = std::make_unique<SSTableManager>(dbPath, 10, 0);
    val.clear();
    EXPECT_TRUE(new_mgr->get("large_key", val));
    EXPECT_EQ(val, large_val);
    EXPECT_TRUE(new_mgr->get("medium_key", val));
    EXPECT_EQ(val, medium_val);
    EXPECT_TRUE(new_mgr->get("small_key", val));
    EXPECT_EQ(val, "small_val");
}

// BUG-3's original defect was an off-by-23 miscalculation of the speculative
// buffer's fast/slow-path boundary. PreadReadSmallAndLarge above tests values
// comfortably clear of that boundary on both sides; this test pins the exact
// edge the `>=` comparison in readValueAt() must get right.
TEST_F(SSTableManagerTest, PreadBufferExactBoundary) {
    gConfigLSMIO.enableMMAP = false;
    gConfigLSMIO.enablePread = true;

    // Both keys are the same length so the record-length arithmetic differs
    // only in val_len, isolating exactly the boundary being tested.
    const std::string key_at_edge = "edge_key_a";
    const std::string key_over_edge = "edge_key_b";
    ASSERT_EQ(key_at_edge.size(), key_over_edge.size());

    const size_t framing = 8;
    const size_t val_at_edge =
        SSTableManager::PREAD_SPECULATIVE_BUF_SIZE - framing - key_at_edge.size();
    const size_t val_over_edge = val_at_edge + 1;

    std::string val_edge_data(val_at_edge, 'E');
    std::string val_over_data(val_over_edge, 'O');

    MemtableVectorNoSort m;
    m.add(key_at_edge, val_edge_data);
    m.add(key_over_edge, val_over_data);

    std::vector<char> buf(128 * 1024);
    ASSERT_TRUE(mgr->flushMemtable(m, buf));

    std::string val;
    // Exactly fills the buffer: total_record_len == PREAD_SPECULATIVE_BUF_SIZE,
    // so the `>=` comparison must take the fast path.
    EXPECT_TRUE(mgr->get(key_at_edge, val));
    EXPECT_EQ(val, val_edge_data);
    EXPECT_EQ(mgr->getPreadSlowPathCount(), 0u);

    // One byte over: total_record_len == PREAD_SPECULATIVE_BUF_SIZE + 1, so
    // the `>=` comparison must take the slow path.
    EXPECT_TRUE(mgr->get(key_over_edge, val));
    EXPECT_EQ(val, val_over_data);
    EXPECT_EQ(mgr->getPreadSlowPathCount(), 1u);
}

// The fix moved the pread scratch buffer from a per-call stack array (safe by
// construction -- every call frame owns its own copy) to a thread_local array
// (safe per-thread, but shared across sequential calls on that thread).
// readValueAt() is non-reentrant so this is safe today; this test guards
// against a future edit that accidentally drops `thread_local`, which would
// let concurrent threads observe each other's buffer contents.
TEST_F(SSTableManagerTest, ConcurrentPreadNoCrossThreadCorruption) {
    gConfigLSMIO.enableMMAP = false;
    gConfigLSMIO.enablePread = true;

    const int num_threads = 8;
    const size_t val_size = 50000;
    MemtableVectorNoSort m;
    std::vector<std::string> expected(num_threads);
    for (int t = 0; t < num_threads; ++t) {
        std::string key = "thread_key_" + std::to_string(t);
        expected[t] = std::string(val_size, static_cast<char>('A' + t));
        m.add(key, expected[t]);
    }

    std::vector<char> buf(128 * 1024);
    ASSERT_TRUE(mgr->flushMemtable(m, buf));

    std::atomic<int> mismatches{0};
    std::vector<std::thread> threads;
    for (int t = 0; t < num_threads; ++t) {
        threads.emplace_back([&, t]() {
            std::string key = "thread_key_" + std::to_string(t);
            for (int i = 0; i < 20; ++i) {
                std::string val;
                if (!mgr->get(key, val) || val != expected[t]) {
                    mismatches.fetch_add(1);
                }
            }
        });
    }
    for (auto& th : threads) {
        th.join();
    }

    EXPECT_EQ(mismatches.load(), 0);
}

TEST_F(SSTableManagerTest, MmapAndPreadCombined) {
    gConfigLSMIO.enableMMAP = true;
    gConfigLSMIO.enablePread = true;

    MemtableVectorNoSort m;
    m.add("combo_k1", "combo_v1");
    std::string large_val(80 * 1024, 'W');
    m.add("combo_k2", large_val);

    std::vector<char> buf(128 * 1024);
    ASSERT_TRUE(mgr->flushMemtable(m, buf));

    std::string val;
    EXPECT_TRUE(mgr->get("combo_k1", val));
    EXPECT_EQ(val, "combo_v1");
    EXPECT_TRUE(mgr->get("combo_k2", val));
    EXPECT_EQ(val, large_val);

    mgr.reset();
    auto new_mgr = std::make_unique<SSTableManager>(dbPath, 10, 0);
    val.clear();
    EXPECT_TRUE(new_mgr->get("combo_k2", val));
    EXPECT_EQ(val, large_val);
}

TEST_F(SSTableManagerTest, FallbackStreamWhenBothDisabled) {
    gConfigLSMIO.enableMMAP = false;
    gConfigLSMIO.enablePread = false;

    MemtableVectorNoSort m;
    m.add("stream_k", "stream_v");
    std::vector<char> buf(1024);
    ASSERT_TRUE(mgr->flushMemtable(m, buf));

    std::string val;
    EXPECT_TRUE(mgr->get("stream_k", val));
    EXPECT_EQ(val, "stream_v");
}

TEST_F(SSTableManagerTest, PreallocManualOffsetAndFooterIndex) {
    gConfigLSMIO.preAllocate = true;
    gConfigLSMIO.manualOffset = true;
    gConfigLSMIO.footerIndex = true;

    mgr.reset();
    std::filesystem::remove_all(dbPath);
    std::filesystem::create_directories(dbPath);

    constexpr size_t pre_alloc_bytes = 128 * 1024;
    mgr = std::make_unique<SSTableManager>(dbPath, 4, pre_alloc_bytes);

    MemtableVectorNoSort m;
    for (int i = 0; i < 50; ++i) {
        m.add("key_" + std::to_string(i), "value_" + std::to_string(i));
    }
    std::vector<char> buf(4096);
    ASSERT_TRUE(mgr->flushMemtable(m, buf));
    mgr.reset();

    // Verify trimmed SSTable file size and trailer magic
    bool found_trimmed = false;
    for (const auto& entry : std::filesystem::directory_iterator(dbPath)) {
        if (entry.path().extension() == ".sst") {
            auto sz = std::filesystem::file_size(entry.path());
            if (sz > 0 && sz < pre_alloc_bytes) {
                found_trimmed = true;
                // Verify magic bytes at end of trimmed file
                std::ifstream f(entry.path(), std::ios::binary);
                ASSERT_TRUE(f.is_open());
                f.seekg(sz - 4);
                char magic_buf[4];
                f.read(magic_buf, 4);
                uint32_t magic = (static_cast<uint8_t>(magic_buf[0])) |
                                 (static_cast<uint8_t>(magic_buf[1]) << 8) |
                                 (static_cast<uint8_t>(magic_buf[2]) << 16) |
                                 (static_cast<uint8_t>(magic_buf[3]) << 24);
                EXPECT_EQ(magic, lsmio::SSTableManager::FOOTER_MAGIC);
            }
        }
    }
    EXPECT_TRUE(found_trimmed);

    // Verify state recovery and all keys present
    auto new_mgr = std::make_unique<SSTableManager>(dbPath, 4, 0);
    for (int i = 0; i < 50; ++i) {
        std::string val;
        EXPECT_TRUE(new_mgr->get("key_" + std::to_string(i), val));
        EXPECT_EQ(val, "value_" + std::to_string(i));
    }
}

namespace {

// Builds the bytes of a crafted SSTable in SSTableManager's on-disk format. A record is
// {u32 key_len, key, u32 val_len, value}; the optional dense index footer is
// {u32 num_entries, {u32 key_len, key, u64 offset} per entry, u64 footer_offset,
// u32 FOOTER_MAGIC}. Every integer is little-endian.
class CraftedSSTable {
  public:
    // Appends a well-formed record and returns its offset.
    uint64_t addRecord(const std::string& f_key, const std::string& f_value) {
        const uint64_t offset = m_bytes.size();
        addLe32(static_cast<uint32_t>(f_key.size()));
        m_bytes.append(f_key);
        addLe32(static_cast<uint32_t>(f_value.size()));
        m_bytes.append(f_value);
        return offset;
    }

    void addRaw(const std::string& f_bytes) {
        m_bytes.append(f_bytes);
    }

    void addLe32(uint32_t f_val) {
        for (int i = 0; i < 4; ++i) {
            m_bytes.push_back(static_cast<char>((f_val >> (8 * i)) & 0xFF));
        }
    }

    void addLe64(uint64_t f_val) {
        for (int i = 0; i < 8; ++i) {
            m_bytes.push_back(static_cast<char>((f_val >> (8 * i)) & 0xFF));
        }
    }

    // Appends one index entry {u32 key_len, key, u64 offset}.
    void addIndexEntry(const std::string& f_key, uint64_t f_offset) {
        addLe32(static_cast<uint32_t>(f_key.size()));
        m_bytes.append(f_key);
        addLe64(f_offset);
    }

    // Appends the last 12 bytes of a footer: u64 footer_offset, u32 FOOTER_MAGIC.
    void addTrailer(uint64_t f_footer_offset) {
        addLe64(f_footer_offset);
        addLe32(SSTableManager::FOOTER_MAGIC);
    }

    // Appends a well-formed footer that lists f_entries; the footer starts at the current size.
    void addFooter(const std::vector<std::pair<std::string, uint64_t>>& f_entries) {
        const uint64_t footer_offset = m_bytes.size();
        addLe32(static_cast<uint32_t>(f_entries.size()));
        for (const auto& entry : f_entries) {
            addIndexEntry(entry.first, entry.second);
        }
        addTrailer(footer_offset);
    }

    // Size in bytes of the footer that addFooter(f_entries) appends.
    static uint64_t footerSize(const std::vector<std::pair<std::string, uint64_t>>& f_entries) {
        uint64_t size = 4 + 12;
        for (const auto& entry : f_entries) {
            size += 4 + entry.first.size() + 8;
        }
        return size;
    }

    uint64_t size() const {
        return m_bytes.size();
    }
    const std::string& bytes() const {
        return m_bytes;
    }

    void writeTo(const std::string& f_path) const {
        std::ofstream out(f_path, std::ios::binary | std::ios::trunc);
        out.write(m_bytes.data(), static_cast<std::streamsize>(m_bytes.size()));
    }

  private:
    std::string m_bytes;
};

// File name FilePool gives the SSTable with id f_id ("L0-000001.sst").
std::string tableFileName(uint64_t f_id) {
    std::ostringstream oss;
    oss << "L0-" << std::setw(6) << std::setfill('0') << f_id << ".sst";
    return oss.str();
}

// Fixture for tests that place crafted .sst files in the DB directory before the manager is
// built (recovery runs in the constructor). One directory per test, named after the test.
class LSMIOSSTableCraftedTest : public ::testing::Test {
  protected:
    std::string m_db_path;
    std::unique_ptr<SSTableManager> m_mgr;
    LSMIOConfig m_backup_config;

    void SetUp() override {
        m_backup_config = gConfigLSMIO;
        const ::testing::TestInfo* info = ::testing::UnitTest::GetInstance()->current_test_info();
        m_db_path =
            std::string("test_sstable_crafted_") + info->test_suite_name() + "_" + info->name();
        std::replace(m_db_path.begin(), m_db_path.end(), '/', '_');
        std::filesystem::remove_all(m_db_path);
        std::filesystem::create_directories(m_db_path);
        gConfigLSMIO.enableMMAP = false;
        gConfigLSMIO.enablePread = true;
        gConfigLSMIO.footerIndex = true;
        gConfigLSMIO.manualOffset = true;
        gConfigLSMIO.preAllocate = false;
    }

    void TearDown() override {
        m_mgr.reset();
        gConfigLSMIO = m_backup_config;
        std::filesystem::remove_all(m_db_path);
    }

    std::string tablePath(uint64_t f_id) const {
        return m_db_path + "/" + tableFileName(f_id);
    }

    // Builds the manager on m_db_path without a file pool; recovery reads the crafted files.
    void openManager() {
        m_mgr = std::make_unique<SSTableManager>(m_db_path, 0, 0);
    }
};

}  // namespace

// 036: two records of one key in a footer-less table; the sequential scan keeps the newest.
TEST_F(LSMIOSSTableCraftedTest, SequentialScanKeepsNewestDuplicate) {
    CraftedSSTable table;
    table.addRecord("dup", "old");
    table.addRecord("other", "x");
    table.addRecord("dup", "new");
    table.writeTo(tablePath(1));

    openManager();
    std::string value;
    EXPECT_TRUE(m_mgr->get("dup", value));
    EXPECT_EQ(value, "new");
    EXPECT_TRUE(m_mgr->get("other", value));
    EXPECT_EQ(value, "x");

    std::map<std::string, std::string> results;
    std::set<std::string> deleted;
    EXPECT_TRUE(m_mgr->scan("", results, deleted));
    EXPECT_EQ(results, (std::map<std::string, std::string>{{"dup", "new"}, {"other", "x"}}));
    EXPECT_TRUE(deleted.empty());
}

// Control for the footer cases below: a valid footer is authoritative, so a record it does not
// list stays invisible.
TEST_F(LSMIOSSTableCraftedTest, ValidFooterIsUsedAsIndex) {
    CraftedSSTable table;
    table.addRecord("k1", "v1");
    table.addRecord("k2", "v2");
    table.addFooter({{"k1", 0}});
    table.writeTo(tablePath(1));

    openManager();
    std::string value;
    EXPECT_TRUE(m_mgr->get("k1", value));
    EXPECT_EQ(value, "v1");
    EXPECT_FALSE(m_mgr->get("k2", value));
}

namespace {

struct FooterCase {
    const char* name;
    // Appends a malformed footer that lists only "k1" (at offset 0) to a table holding the
    // records k1 and k2; f_footer_offset is where the footer starts.
    void (*append_footer)(CraftedSSTable& f_table, uint64_t f_footer_offset);
};

class LSMIOSSTableFooterRejectTest : public LSMIOSSTableCraftedTest,
                                     public ::testing::WithParamInterface<FooterCase> {};

}  // namespace

// 037: every malformed footer is refused, so recovery falls back to the sequential scan and finds
// k2 too (with a valid footer k2 would be invisible, see ValidFooterIsUsedAsIndex).
TEST_P(LSMIOSSTableFooterRejectTest, FallsBackToSequentialScan) {
    CraftedSSTable table;
    table.addRecord("k1", "v1");
    table.addRecord("k2", "v2");
    GetParam().append_footer(table, table.size());
    table.writeTo(tablePath(1));

    openManager();
    std::string value;
    EXPECT_TRUE(m_mgr->get("k1", value));
    EXPECT_EQ(value, "v1");
    EXPECT_TRUE(m_mgr->get("k2", value));
    EXPECT_EQ(value, "v2");
}

INSTANTIATE_TEST_SUITE_P(
    Footers, LSMIOSSTableFooterRejectTest,
    ::testing::Values(FooterCase{"offset_beyond_trailer",
                                 [](CraftedSSTable& f_table, uint64_t) {
                                     f_table.addTrailer(1ULL << 40);
                                 }},
                      FooterCase{"count_exceeds_entries",
                                 [](CraftedSSTable& f_table, uint64_t f_footer_offset) {
                                     f_table.addLe32(2);
                                     f_table.addIndexEntry("k1", 0);
                                     f_table.addTrailer(f_footer_offset);
                                 }},
                      FooterCase{"key_len_over_limit",
                                 [](CraftedSSTable& f_table, uint64_t f_footer_offset) {
                                     f_table.addLe32(1);
                                     f_table.addLe32(64 * 1024 * 1024 + 1);
                                     f_table.addRaw("k1");
                                     f_table.addTrailer(f_footer_offset);
                                 }},
                      FooterCase{"key_past_index_end",
                                 [](CraftedSSTable& f_table, uint64_t f_footer_offset) {
                                     f_table.addLe32(1);
                                     f_table.addLe32(100);
                                     f_table.addRaw("k1");
                                     f_table.addTrailer(f_footer_offset);
                                 }},
                      FooterCase{"offset_bytes_missing",
                                 [](CraftedSSTable& f_table, uint64_t f_footer_offset) {
                                     f_table.addLe32(1);
                                     f_table.addLe32(2);
                                     f_table.addRaw("k1");
                                     f_table.addLe32(0);
                                     f_table.addTrailer(f_footer_offset);
                                 }},
                      FooterCase{"count_below_entries",
                                 [](CraftedSSTable& f_table, uint64_t f_footer_offset) {
                                     f_table.addLe32(1);
                                     f_table.addIndexEntry("k1", 0);
                                     f_table.addIndexEntry("k2", 12);
                                     f_table.addTrailer(f_footer_offset);
                                 }}),
    [](const ::testing::TestParamInfo<FooterCase>& f_info) {
        return std::string(f_info.param.name);
    });

namespace {

struct TailCase {
    const char* name;
    // Appends a malformed record after the valid record "good".
    void (*append_tail)(CraftedSSTable& f_table);
};

class LSMIOSSTableTruncatedTailTest : public LSMIOSSTableCraftedTest,
                                      public ::testing::WithParamInterface<TailCase> {};

}  // namespace

// 038: the sequential scan stops at a malformed record and keeps the records before it.
TEST_P(LSMIOSSTableTruncatedTailTest, KeepsRecordsBeforeTheBadOne) {
    CraftedSSTable table;
    table.addRecord("good", "1");
    GetParam().append_tail(table);
    table.writeTo(tablePath(1));

    openManager();
    std::string value;
    EXPECT_TRUE(m_mgr->get("good", value));
    EXPECT_EQ(value, "1");

    std::map<std::string, std::string> results;
    std::set<std::string> deleted;
    EXPECT_TRUE(m_mgr->scan("", results, deleted));
    EXPECT_EQ(results, (std::map<std::string, std::string>{{"good", "1"}}));
}

INSTANTIATE_TEST_SUITE_P(Tails, LSMIOSSTableTruncatedTailTest,
                         ::testing::Values(TailCase{"header_truncated",
                                                    [](CraftedSSTable& f_table) {
                                                        f_table.addRaw(std::string("\x01\x00", 2));
                                                    }},
                                           TailCase{"key_len_over_limit",
                                                    [](CraftedSSTable& f_table) {
                                                        f_table.addLe32(64 * 1024 * 1024 + 1);
                                                    }},
                                           TailCase{"key_truncated",
                                                    [](CraftedSSTable& f_table) {
                                                        f_table.addLe32(10);
                                                        f_table.addRaw("abc");
                                                    }},
                                           TailCase{"val_len_truncated",
                                                    [](CraftedSSTable& f_table) {
                                                        f_table.addLe32(3);
                                                        f_table.addRaw("bad");
                                                        f_table.addRaw(std::string("\x05\x00", 2));
                                                    }},
                                           TailCase{"val_len_over_limit",
                                                    [](CraftedSSTable& f_table) {
                                                        f_table.addLe32(3);
                                                        f_table.addRaw("bad");
                                                        f_table.addLe32(0x80000000u);
                                                    }}),
                         [](const ::testing::TestParamInfo<TailCase>& f_info) {
                             return std::string(f_info.param.name);
                         });

// 038: a record with an empty key and a non-empty value is not the padding marker; it is indexed
// and the scan continues past it.
TEST_F(LSMIOSSTableCraftedTest, EmptyKeyRecordIsIndexed) {
    CraftedSSTable table;
    table.addRecord("", "hello");
    table.addRecord("after", "2");
    table.writeTo(tablePath(1));

    openManager();
    std::string value;
    EXPECT_TRUE(m_mgr->get("", value));
    EXPECT_EQ(value, "hello");
    EXPECT_TRUE(m_mgr->get("after", value));
    EXPECT_EQ(value, "2");
}

// Format rule: an all-zero 8-byte header (empty key, empty value) ends a footer-less scan,
// since it marks the zero padding of an untrimmed preallocated file; LSMIOStoreNative refuses
// empty keys, so the store never writes such a record.
TEST_F(LSMIOSSTableCraftedTest, ZeroHeaderEndsFooterlessScan) {
    gConfigLSMIO.footerIndex = false;
    openManager();
    MemtableVectorNoSort memtable;
    memtable.add("", "");
    memtable.add("after", "2");
    std::vector<char> buffer(1024);
    ASSERT_TRUE(m_mgr->flushMemtable(memtable, buffer));
    std::string value;
    EXPECT_TRUE(m_mgr->get("after", value));
    EXPECT_EQ(value, "2");

    m_mgr.reset();
    openManager();
    EXPECT_FALSE(m_mgr->get("after", value));
}

// 044: in a footer-less table, a torn tail record is dropped at recovery and not indexed.
TEST_F(LSMIOSSTableCraftedTest, FooterlessTornTailIsNotIndexed) {
    gConfigLSMIO.footerIndex = false;
    CraftedSSTable table;
    table.addRecord("a", "1");
    table.addRecord("b", "2");
    table.addLe32(1);
    table.addRaw("c");
    table.addLe32(50);
    table.addRaw("xyz");
    table.writeTo(tablePath(1));

    openManager();
    std::string value;
    EXPECT_TRUE(m_mgr->get("a", value));
    EXPECT_EQ(value, "1");
    EXPECT_TRUE(m_mgr->get("b", value));
    EXPECT_EQ(value, "2");

    value = "sentinel";
    EXPECT_FALSE(m_mgr->get("c", value));
    EXPECT_EQ(value, "sentinel");
    EXPECT_EQ(m_mgr->getPreadSlowPathCount(), 0u);

    std::map<std::string, std::string> results;
    std::set<std::string> deleted;
    EXPECT_TRUE(m_mgr->scan("", results, deleted));
    EXPECT_EQ(results, (std::map<std::string, std::string>{{"a", "1"}, {"b", "2"}}));
    EXPECT_TRUE(deleted.empty());
}

// 044: in a footer-less table with duplicate keys, a torn newer record does not hide an older
// complete record.
TEST_F(LSMIOSSTableCraftedTest, FooterlessTornDuplicateKeepsCompleteRecord) {
    gConfigLSMIO.footerIndex = false;
    CraftedSSTable table;
    table.addRecord("k", "complete");
    table.addLe32(1);
    table.addRaw("k");
    table.addLe32(50);
    table.addRaw("abc");
    table.writeTo(tablePath(1));

    openManager();
    std::string value;
    EXPECT_TRUE(m_mgr->get("k", value));
    EXPECT_EQ(value, "complete");

    std::map<std::string, std::string> results;
    std::set<std::string> deleted;
    EXPECT_TRUE(m_mgr->scan("", results, deleted));
    EXPECT_EQ(results, (std::map<std::string, std::string>{{"k", "complete"}}));
}

// 038: a DB directory that does not exist recovers nothing and is not created.
TEST_F(LSMIOSSTableCraftedTest, MissingDirectoryRecoversNothing) {
    std::filesystem::remove_all(m_db_path);
    openManager();
    EXPECT_FALSE(std::filesystem::exists(m_db_path));
    std::string value;
    EXPECT_FALSE(m_mgr->get("any", value));
    std::map<std::string, std::string> results;
    std::set<std::string> deleted;
    EXPECT_FALSE(m_mgr->scan("", results, deleted));
    EXPECT_TRUE(results.empty());
}

// 038: only L0-<number>.sst files are recovered; the next table id follows the highest one.
TEST_F(LSMIOSSTableCraftedTest, IgnoresForeignAndMalformedFileNames) {
    const std::vector<std::string> ignored_names = {"notes.txt", "L0-000001.log", "L0-abc.sst"};
    for (size_t i = 0; i < ignored_names.size(); ++i) {
        CraftedSSTable ghost;
        ghost.addRecord("ghost" + std::to_string(i), "x");
        ghost.writeTo(m_db_path + "/" + ignored_names[i]);
    }
    CraftedSSTable real;
    real.addRecord("real", "1");
    real.writeTo(tablePath(2));

    openManager();
    std::string value;
    EXPECT_TRUE(m_mgr->get("real", value));
    EXPECT_EQ(value, "1");
    for (size_t i = 0; i < ignored_names.size(); ++i) {
        EXPECT_FALSE(m_mgr->get("ghost" + std::to_string(i), value)) << ignored_names[i];
    }

    MemtableVectorNoSort memtable;
    memtable.add("fresh", "2");
    std::vector<char> buffer(1024);
    ASSERT_TRUE(m_mgr->flushMemtable(memtable, buffer));
    EXPECT_TRUE(std::filesystem::exists(tablePath(3)));
    EXPECT_TRUE(m_mgr->get("fresh", value));
    EXPECT_EQ(value, "2");
}

namespace {

std::string readWholeFile(const std::string& f_path) {
    std::ifstream in(f_path, std::ios::binary);
    return std::string(std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>());
}

std::vector<std::string> listDirectory(const std::string& f_path) {
    std::vector<std::string> names;
    if (std::filesystem::exists(f_path)) {
        for (const auto& entry : std::filesystem::directory_iterator(f_path)) {
            names.push_back(entry.path().filename().string());
        }
        std::sort(names.begin(), names.end());
    }
    return names;
}

#ifdef __linux__
size_t countOpenDescriptors() {
    size_t count = 0;
    for (const auto& entry : std::filesystem::directory_iterator("/proc/self/fd")) {
        (void)entry;
        ++count;
    }
    return count;
}
#endif

}  // namespace

// 044: recovery fails and throws std::runtime_error when an SSTable cannot be opened.
TEST_F(LSMIOSSTableCraftedTest, UnreadableTableFailsRecovery) {
    if (::geteuid() == 0) {
        GTEST_SKIP() << "root ignores file permissions";
    }
    gConfigLSMIO.enableMMAP = true;
    gConfigLSMIO.enablePread = false;
    CraftedSSTable table;
    table.addRecord("k1", "v1");
    table.addFooter({{"k1", 0}});
    table.writeTo(tablePath(1));
    const auto before = listDirectory(m_db_path);
    ASSERT_EQ(::chmod(tablePath(1).c_str(), 0), 0);

    EXPECT_THROW(openManager(), std::runtime_error);
    ASSERT_EQ(::chmod(tablePath(1).c_str(), 0644), 0);
    EXPECT_EQ(m_mgr.get(), nullptr);
    EXPECT_EQ(listDirectory(m_db_path), before);
    EXPECT_EQ(readWholeFile(tablePath(1)), table.bytes());
}

// 044: a dangling symlink fails recovery even for root, and writes nothing to the DB directory.
// The pool worker is asynchronous, so a regression that built the pool before recovery shows on
// most runs, not on every run. A correct implementation never fails.
TEST_F(LSMIOSSTableCraftedTest, DanglingSymlinkTableFailsRecovery) {
    std::filesystem::create_symlink(m_db_path + "/missing-target", tablePath(1));
    const auto before = listDirectory(m_db_path);

    try {
        SSTableManager mgr(m_db_path, 2, 0);
        ADD_FAILURE() << "Expected std::runtime_error";
    } catch (const std::runtime_error& e) {
        EXPECT_NE(std::string(e.what()).find(tableFileName(1)), std::string::npos);
    }
    EXPECT_EQ(listDirectory(m_db_path), before);
}

// 044: a failed recovery releases the descriptors of tables it opened before the failure.
TEST_F(LSMIOSSTableCraftedTest, FailedRecoveryReleasesDescriptors) {
#ifndef __linux__
    GTEST_SKIP() << "Counting /proc/self/fd requires Linux";
#else
    CraftedSSTable table;
    table.addRecord("k1", "v1");
    table.addFooter({{"k1", 0}});
    table.writeTo(tablePath(1));
    std::filesystem::create_symlink(m_db_path + "/missing-target", tablePath(2));

    const size_t fds_before = countOpenDescriptors();
    EXPECT_THROW(openManager(), std::runtime_error);
    const size_t fds_after = countOpenDescriptors();
    EXPECT_EQ(fds_after, fds_before);
#endif
}

// 040: an empty memtable is a successful no-op.
TEST_F(LSMIOSSTableCraftedTest, EmptyMemtableFlushWritesNoFile) {
    openManager();
    MemtableVectorNoSort memtable;
    std::vector<char> buffer(16);
    EXPECT_TRUE(m_mgr->flushMemtable(memtable, buffer));
    EXPECT_TRUE(std::filesystem::is_empty(m_db_path));
}

// 040: without a file pool the table is created on demand; with the directory gone that fails and
// the flush reports it.
TEST_F(LSMIOSSTableCraftedTest, FlushFailsWhenDirectoryIsGone) {
    openManager();
    std::filesystem::remove_all(m_db_path);
    MemtableVectorNoSort memtable;
    memtable.add("k", "v");
    std::vector<char> buffer(1024);
    EXPECT_FALSE(m_mgr->flushMemtable(memtable, buffer));
    std::string value;
    EXPECT_FALSE(m_mgr->get("k", value));
    EXPECT_FALSE(std::filesystem::exists(m_db_path));
}

namespace {

struct FlushLayoutCase {
    const char* name;
    bool manual_offset;
    bool footer_index;
    bool pre_allocate;
    size_t buffer_size;
};

class LSMIOSSTableFlushLayoutTest : public LSMIOSSTableCraftedTest,
                                    public ::testing::WithParamInterface<FlushLayoutCase> {};

}  // namespace

// 040: the flushed file holds exactly the records (and the footer when enabled), whether offsets
// come from the running count or from tellp(), and the table reads back before and after restart.
TEST_P(LSMIOSSTableFlushLayoutTest, WritesExactBytes) {
    const FlushLayoutCase& c = GetParam();
    gConfigLSMIO.manualOffset = c.manual_offset;
    gConfigLSMIO.footerIndex = c.footer_index;
    gConfigLSMIO.preAllocate = c.pre_allocate;
    m_mgr = std::make_unique<SSTableManager>(m_db_path, 0, c.pre_allocate ? 4096 : 0);

    MemtableVectorNoSort memtable;
    memtable.add("bb", "22");
    memtable.add("a", "1");
    std::vector<char> buffer(c.buffer_size);
    ASSERT_TRUE(m_mgr->flushMemtable(memtable, buffer));

    CraftedSSTable expected;
    const uint64_t offset_a = expected.addRecord("a", "1");
    const uint64_t offset_bb = expected.addRecord("bb", "22");
    if (c.footer_index) {
        expected.addFooter({{"a", offset_a}, {"bb", offset_bb}});
    }
    m_mgr.reset();
    EXPECT_EQ(readWholeFile(tablePath(1)), expected.bytes());

    openManager();
    std::string value;
    EXPECT_TRUE(m_mgr->get("a", value));
    EXPECT_EQ(value, "1");
    EXPECT_TRUE(m_mgr->get("bb", value));
    EXPECT_EQ(value, "22");
}

INSTANTIATE_TEST_SUITE_P(
    Layouts, LSMIOSSTableFlushLayoutTest,
    ::testing::Values(FlushLayoutCase{"tellp_offsets_footer_prealloc", false, true, true, 0},
                      FlushLayoutCase{"manual_offsets_no_footer", true, false, false, 64}),
    [](const ::testing::TestParamInfo<FlushLayoutCase>& f_info) {
        return std::string(f_info.param.name);
    });

// 041: a newer table shadows an older one in a scan: a key already returned is not read again, and
// a key deleted in the newer table is not resurrected from the older one.
TEST_F(LSMIOSSTableCraftedTest, ScanSkipsKeysSeenInNewerTables) {
    openManager();
    std::vector<char> buffer(1024);
    MemtableVectorNoSort older;
    older.add("p/a", "old");
    older.add("p/b", "b-old");
    ASSERT_TRUE(m_mgr->flushMemtable(older, buffer));
    MemtableVectorNoSort newer;
    newer.add("p/a", "new");
    newer.add("p/b", MEMTABLE_TOMBSTONE);
    ASSERT_TRUE(m_mgr->flushMemtable(newer, buffer));

    std::map<std::string, std::string> results;
    std::set<std::string> deleted;
    EXPECT_TRUE(m_mgr->scan("p/", results, deleted));
    EXPECT_EQ(results, (std::map<std::string, std::string>{{"p/a", "new"}}));
    EXPECT_EQ(deleted, (std::set<std::string>{"p/b"}));

    std::string value;
    EXPECT_TRUE(m_mgr->get("p/b", value));
    EXPECT_EQ(value, MEMTABLE_TOMBSTONE);
}

// 041: an index entry whose record cannot be read is skipped by scan and missed by get; get then
// falls through to the older table.
TEST_F(LSMIOSSTableCraftedTest, UnreadableIndexEntryIsSkipped) {
    CraftedSSTable older;
    older.addRecord("p/y", "older");
    older.addFooter({{"p/y", 0}});
    older.writeTo(tablePath(1));
    CraftedSSTable newer;
    newer.addRecord("p/x", "1");
    newer.addFooter({{"p/x", 0}, {"p/y", 1ULL << 40}});
    newer.writeTo(tablePath(2));

    openManager();
    std::map<std::string, std::string> results;
    std::set<std::string> deleted;
    EXPECT_TRUE(m_mgr->scan("p/", results, deleted));
    EXPECT_EQ(results, (std::map<std::string, std::string>{{"p/x", "1"}, {"p/y", "older"}}));

    std::string value;
    EXPECT_TRUE(m_mgr->get("p/y", value));
    EXPECT_EQ(value, "older");
}

// Out of contract. The test shrinks an SSTable under an open store, which breaks AI-5's premise
// that SSTables are immutable once their node exists. It checks that the read fails safely when
// that precondition is broken (a miss, an empty output, no garbage). It does not describe a
// supported use, and "a shrunk file reads as absent" is not a store guarantee.
TEST_F(LSMIOSSTableCraftedTest, PreadShortSecondReadClearsValue) {
    CraftedSSTable table;
    table.addRecord("k", std::string(200 * 1024, 'v'));
    table.addFooter({{"k", 0}});
    table.writeTo(tablePath(1));

    openManager();
    std::filesystem::resize_file(tablePath(1), 150 * 1024);

    std::string value = "sentinel";
    EXPECT_FALSE(m_mgr->get("k", value));
    EXPECT_EQ(value, "");
    EXPECT_EQ(m_mgr->getPreadSlowPathCount(), 1u);
}

namespace {

enum class ReadMode {
    Mmap,
    Pread,
    Stream
};

// Crafted tables whose index (footer or sequential scan) points get() at a record it must refuse.
enum class BadLayout {
    OffsetFar,        // footer entry "k1" at offset 2^64 - 16
    OffsetInMagic,    // footer entry "k1" at the last 4 bytes (the magic)
    OffsetInLastTwo,  // footer entry "k1" at the last 2 bytes
    KeyLenMismatch,   // footer entry "kkk" at the record of "k1"
    KeyBytesDiffer,   // footer entry "k2" at the record of "k1"
    ValLenOverLimit,  // footer entry "big" at a record whose val_len is 0xFFFFFFFF
    KeyPastEnd5,      // footer entry (5 bytes) at the trailer; 4 bytes remain after its key
    KeyPastEnd9,      // footer entry (9 bytes) at the trailer; only 8 bytes remain for its key
    ValueTruncated,   // footer lists "k" at 0; record "k" declares 100 value bytes, the file holds
                      // 41
    FileRemovedAfterOpen  // valid footer; the file is deleted after recovery
};

struct ReadRefusalCase {
    const char* name;
    ReadMode mode;
    BadLayout layout;
    const char* key;
    size_t key_size;          // the key may hold NUL bytes
    const char* value_after;  // value left in the output string; get() starts from "sentinel"
};

// Builds the table for f_layout.
CraftedSSTable buildBadLayout(BadLayout f_layout) {
    CraftedSSTable table;
    switch (f_layout) {
        case BadLayout::OffsetFar:
            table.addRecord("k1", "v1");
            table.addFooter({{"k1", ~0ULL - 15}});
            break;
        case BadLayout::OffsetInMagic:
        case BadLayout::OffsetInLastTwo: {
            table.addRecord("k1", "v1");
            const uint64_t total = table.size() + CraftedSSTable::footerSize({{"k1", 0}});
            const uint64_t back = (f_layout == BadLayout::OffsetInMagic) ? 4 : 2;
            table.addFooter({{"k1", total - back}});
            break;
        }
        case BadLayout::KeyLenMismatch:
            table.addRecord("k1", "v1");
            table.addFooter({{"kkk", 0}});
            break;
        case BadLayout::KeyBytesDiffer:
            table.addRecord("k1", "v1");
            table.addFooter({{"k2", 0}});
            break;
        case BadLayout::ValLenOverLimit:
            table.addLe32(3);
            table.addRaw("big");
            table.addLe32(0xFFFFFFFFu);
            table.addFooter({{"big", 0}});
            break;
        case BadLayout::KeyPastEnd5:
        case BadLayout::KeyPastEnd9: {
            // The data section is key_size filler bytes, so the trailer's u64 footer_offset
            // starts with u32 key_size: the entry at the trailer reads as a record header whose
            // key is the next key_size bytes (4 zero bytes, then the magic "IMSL").
            const size_t key_size = (f_layout == BadLayout::KeyPastEnd5) ? 5 : 9;
            table.addRaw(std::string(key_size, 'z'));
            const std::string key = (f_layout == BadLayout::KeyPastEnd5)
                                        ? std::string("\0\0\0\0I", 5)
                                        : std::string(9, 'q');
            const uint64_t total = table.size() + CraftedSSTable::footerSize({{key, 0}});
            table.addFooter({{key, total - 12}});
            break;
        }
        case BadLayout::ValueTruncated:
            table.addLe32(1);
            table.addRaw("k");
            table.addLe32(100);
            table.addRaw("abc");
            table.addFooter({{"k", 0}});
            break;
        case BadLayout::FileRemovedAfterOpen:
            table.addRecord("k1", "v1");
            table.addFooter({{"k1", 0}});
            break;
    }
    return table;
}

class LSMIOSSTableReadRefusalTest : public LSMIOSSTableCraftedTest,
                                    public ::testing::WithParamInterface<ReadRefusalCase> {};

}  // namespace

// 042/043: each read path (mmap, pread, stream) refuses a record that does not fit the file or
// does not match the key; get() then reports a miss.
TEST_P(LSMIOSSTableReadRefusalTest, GetRefusesBadRecord) {
    const ReadRefusalCase& c = GetParam();
    gConfigLSMIO.enableMMAP = (c.mode == ReadMode::Mmap);
    gConfigLSMIO.enablePread = (c.mode == ReadMode::Pread);
    buildBadLayout(c.layout).writeTo(tablePath(1));

    openManager();
    if (c.layout == BadLayout::FileRemovedAfterOpen) {
        ASSERT_TRUE(std::filesystem::remove(tablePath(1)));
    }
    std::string value = "sentinel";
    EXPECT_FALSE(m_mgr->get(std::string(c.key, c.key_size), value));
    EXPECT_EQ(value, c.value_after);
}

INSTANTIATE_TEST_SUITE_P(
    ReadPaths, LSMIOSSTableReadRefusalTest,
    ::testing::Values(ReadRefusalCase{"mmap_offset_far", ReadMode::Mmap, BadLayout::OffsetFar, "k1",
                                      2, "sentinel"},
                      ReadRefusalCase{"mmap_offset_in_magic", ReadMode::Mmap,
                                      BadLayout::OffsetInMagic, "k1", 2, "sentinel"},
                      ReadRefusalCase{"mmap_key_len_mismatch", ReadMode::Mmap,
                                      BadLayout::KeyLenMismatch, "kkk", 3, "sentinel"},
                      ReadRefusalCase{"mmap_key_past_end", ReadMode::Mmap, BadLayout::KeyPastEnd5,
                                      "\0\0\0\0I", 5, "sentinel"},
                      ReadRefusalCase{"mmap_key_bytes_differ", ReadMode::Mmap,
                                      BadLayout::KeyBytesDiffer, "k2", 2, "sentinel"},
                      ReadRefusalCase{"mmap_val_len_over_limit", ReadMode::Mmap,
                                      BadLayout::ValLenOverLimit, "big", 3, "sentinel"},
                      ReadRefusalCase{"mmap_value_truncated", ReadMode::Mmap,
                                      BadLayout::ValueTruncated, "k", 1, "sentinel"},
                      ReadRefusalCase{"pread_offset_far", ReadMode::Pread, BadLayout::OffsetFar,
                                      "k1", 2, "sentinel"},
                      ReadRefusalCase{"pread_key_len_mismatch", ReadMode::Pread,
                                      BadLayout::KeyLenMismatch, "kkk", 3, "sentinel"},
                      ReadRefusalCase{"pread_key_bytes_differ", ReadMode::Pread,
                                      BadLayout::KeyBytesDiffer, "k2", 2, "sentinel"},
                      ReadRefusalCase{"pread_val_len_over_limit", ReadMode::Pread,
                                      BadLayout::ValLenOverLimit, "big", 3, "sentinel"},
                      ReadRefusalCase{"pread_value_truncated", ReadMode::Pread,
                                      BadLayout::ValueTruncated, "k", 1, "sentinel"},
                      ReadRefusalCase{"stream_offset_far", ReadMode::Stream, BadLayout::OffsetFar,
                                      "k1", 2, "sentinel"},
                      ReadRefusalCase{"stream_offset_in_last_two", ReadMode::Stream,
                                      BadLayout::OffsetInLastTwo, "k1", 2, "sentinel"},
                      ReadRefusalCase{"stream_offset_in_magic", ReadMode::Stream,
                                      BadLayout::OffsetInMagic, "k1", 2, "sentinel"},
                      ReadRefusalCase{"stream_key_short", ReadMode::Stream, BadLayout::KeyPastEnd9,
                                      "qqqqqqqqq", 9, "sentinel"},
                      ReadRefusalCase{"stream_key_bytes_differ", ReadMode::Stream,
                                      BadLayout::KeyBytesDiffer, "k2", 2, "sentinel"},
                      ReadRefusalCase{"stream_val_len_missing", ReadMode::Stream,
                                      BadLayout::KeyPastEnd5, "\0\0\0\0I", 5, "sentinel"},
                      ReadRefusalCase{"stream_val_len_over_limit", ReadMode::Stream,
                                      BadLayout::ValLenOverLimit, "big", 3, "sentinel"},
                      ReadRefusalCase{"stream_value_truncated", ReadMode::Stream,
                                      BadLayout::ValueTruncated, "k", 1, "sentinel"},
                      ReadRefusalCase{"stream_file_removed", ReadMode::Stream,
                                      BadLayout::FileRemovedAfterOpen, "k1", 2, "sentinel"}),
    [](const ::testing::TestParamInfo<ReadRefusalCase>& f_info) {
        return std::string(f_info.param.name);
    });

class LSMIOSSTableRecordPastEndTest : public LSMIOSSTableCraftedTest,
                                      public ::testing::WithParamInterface<ReadMode> {};

// 044: a record whose declared value length extends past the end of the file is refused before
// any value buffer is allocated.
TEST_P(LSMIOSSTableRecordPastEndTest, IsRefusedBeforeAllocation) {
    const ReadMode mode = GetParam();
    gConfigLSMIO.enableMMAP = (mode == ReadMode::Mmap);
    gConfigLSMIO.enablePread = (mode == ReadMode::Pread);
    buildBadLayout(BadLayout::ValueTruncated).writeTo(tablePath(1));

    openManager();
    std::string value = "sentinel";
    EXPECT_FALSE(m_mgr->get("k", value));
    EXPECT_EQ(value, "sentinel");

    std::map<std::string, std::string> results;
    std::set<std::string> deleted;
    EXPECT_FALSE(m_mgr->scan("", results, deleted));
    EXPECT_TRUE(results.empty());
    EXPECT_TRUE(deleted.empty());
    EXPECT_EQ(m_mgr->getPreadSlowPathCount(), 0u);
}

INSTANTIATE_TEST_SUITE_P(PastEnd, LSMIOSSTableRecordPastEndTest,
                         ::testing::Values(ReadMode::Mmap, ReadMode::Pread, ReadMode::Stream),
                         [](const ::testing::TestParamInfo<ReadMode>& f_info) {
                             switch (f_info.param) {
                                 case ReadMode::Mmap:
                                     return "mmap";
                                 case ReadMode::Pread:
                                     return "pread";
                                 case ReadMode::Stream:
                                     return "stream";
                             }
                             return "unknown";
                         });

class LSMIOSSTableAllocationDeathTest : public LSMIOSSTableCraftedTest {};

// 044: under a lowered RLIMIT_AS, the stream read path refuses a huge declared value length
// without allocating the value buffer.
TEST_F(LSMIOSSTableAllocationDeathTest, StreamPathRefusesHugeRecordUnderAddressLimit) {
#if !LSMIO_TEST_RLIMIT_AS
    GTEST_SKIP() << "RLIMIT_AS check needs Linux and no sanitizer";
#else
    GTEST_FLAG_SET(death_test_style, "threadsafe");
    gConfigLSMIO.enableMMAP = false;
    gConfigLSMIO.enablePread = false;

    CraftedSSTable table;
    table.addLe32(3);
    table.addRaw("big");
    table.addLe32(0x7FFF0000u);
    table.addRaw("abc");
    table.addFooter({{"big", 0}});
    table.writeTo(tablePath(1));

    EXPECT_EXIT(
        [&]() {
            int rc = 0;
            {
                SSTableManager mgr(m_db_path, 0, 0);

                long page_size = ::sysconf(_SC_PAGESIZE);
                uint64_t pages = 0;
                std::ifstream statm("/proc/self/statm");
                if (!(statm >> pages) || page_size <= 0) {
                    std::exit(11);
                }
                uint64_t current = pages * static_cast<uint64_t>(page_size);

                struct rlimit saved;
                if (::getrlimit(RLIMIT_AS, &saved) != 0) {
                    std::exit(11);
                }
                uint64_t target_limit = current + 256ULL * 1024 * 1024;
                if (saved.rlim_max != RLIM_INFINITY && target_limit > saved.rlim_max) {
                    std::exit(11);
                }
                struct rlimit target = saved;
                target.rlim_cur = target_limit;
                if (::setrlimit(RLIMIT_AS, &target) != 0) {
                    std::exit(11);
                }

                std::string value = "sentinel";
                bool found = false;
                try {
                    found = mgr.get("big", value);
                } catch (const std::bad_alloc&) {
                    rc = 30;
                }

                if (rc == 0) {
                    rc = found ? 20 : (value != "sentinel" ? 21 : 0);
                }

                ::setrlimit(RLIMIT_AS, &saved);
            }
            std::exit(rc);
        }(),
        ::testing::ExitedWithCode(0), "");
#endif
}

// 044: under a lowered RLIMIT_AS, the pread slow path refuses a huge declared value length
// without allocating the value buffer.
TEST_F(LSMIOSSTableAllocationDeathTest, PreadSlowPathRefusesHugeRecordUnderAddressLimit) {
#if !LSMIO_TEST_RLIMIT_AS
    GTEST_SKIP() << "RLIMIT_AS check needs Linux and no sanitizer";
#else
    GTEST_FLAG_SET(death_test_style, "threadsafe");
    gConfigLSMIO.enableMMAP = false;
    gConfigLSMIO.enablePread = true;

    CraftedSSTable table;
    table.addLe32(3);
    table.addRaw("big");
    table.addLe32(0x7FFF0000u);
    table.addRaw("abc");
    table.addFooter({{"big", 0}});
    table.writeTo(tablePath(1));

    EXPECT_EXIT(
        [&]() {
            int rc = 0;
            {
                SSTableManager mgr(m_db_path, 0, 0);

                long page_size = ::sysconf(_SC_PAGESIZE);
                uint64_t pages = 0;
                std::ifstream statm("/proc/self/statm");
                if (!(statm >> pages) || page_size <= 0) {
                    std::exit(11);
                }
                uint64_t current = pages * static_cast<uint64_t>(page_size);

                struct rlimit saved;
                if (::getrlimit(RLIMIT_AS, &saved) != 0) {
                    std::exit(11);
                }
                uint64_t target_limit = current + 256ULL * 1024 * 1024;
                if (saved.rlim_max != RLIM_INFINITY && target_limit > saved.rlim_max) {
                    std::exit(11);
                }
                struct rlimit target = saved;
                target.rlim_cur = target_limit;
                if (::setrlimit(RLIMIT_AS, &target) != 0) {
                    std::exit(11);
                }

                std::string value = "sentinel";
                bool found = false;
                try {
                    found = mgr.get("big", value);
                } catch (const std::bad_alloc&) {
                    rc = 30;
                }

                if (rc == 0) {
                    rc = found ? 20 : (value != "sentinel" ? 21 : 0);
                }

                ::setrlimit(RLIMIT_AS, &saved);
            }
            std::exit(rc);
        }(),
        ::testing::ExitedWithCode(0), "");
#endif
}

namespace {

void appendToFile(const std::string& f_path, const std::string& f_bytes) {
    std::ofstream sst_file(f_path, std::ios::binary | std::ios::app);
    sst_file.write(f_bytes.data(), static_cast<std::streamsize>(f_bytes.size()));
}

struct StreamRestartParam {
    std::string name;
    bool manual_offset;
    bool footer_index;
};

class LSMIOSSTableStreamRestartTest : public LSMIOSSTableCraftedTest,
                                      public ::testing::WithParamInterface<StreamRestartParam> {};

TEST_P(LSMIOSSTableStreamRestartTest, ReadsBackBeforeAndAfterRestart) {
    const auto& param = GetParam();
    gConfigLSMIO.enableMMAP = false;
    gConfigLSMIO.enablePread = false;
    gConfigLSMIO.manualOffset = param.manual_offset;
    gConfigLSMIO.footerIndex = param.footer_index;
    gConfigLSMIO.preAllocate = false;

    openManager();

    MemtableVectorNoSort memtable;
    memtable.add("a", "1");
    memtable.add("bb", "22");
    memtable.add("ccc", std::string(300, 'c'));

    std::vector<char> buffer(1024);
    ASSERT_TRUE(m_mgr->flushMemtable(memtable, buffer));

    // Expected 1 (flush length)
    std::string value = "sentinel";
    EXPECT_TRUE(m_mgr->get("a", value));
    EXPECT_EQ(value, "1");

    value = "sentinel";
    EXPECT_TRUE(m_mgr->get("bb", value));
    EXPECT_EQ(value, "22");

    value = "sentinel";
    EXPECT_TRUE(m_mgr->get("ccc", value));
    EXPECT_EQ(value, std::string(300, 'c'));

    std::map<std::string, std::string> results;
    std::set<std::string> deleted;
    EXPECT_TRUE(m_mgr->scan("", results, deleted));
    std::map<std::string, std::string> expected_results = {
        {"a", "1"}, {"bb", "22"}, {"ccc", std::string(300, 'c')}};
    EXPECT_EQ(results, expected_results);
    EXPECT_TRUE(deleted.empty());

    // Action 2: restart
    m_mgr.reset();
    openManager();

    // Expected 2 (recovery length)
    value = "sentinel";
    EXPECT_TRUE(m_mgr->get("a", value));
    EXPECT_EQ(value, "1");

    value = "sentinel";
    EXPECT_TRUE(m_mgr->get("bb", value));
    EXPECT_EQ(value, "22");

    value = "sentinel";
    EXPECT_TRUE(m_mgr->get("ccc", value));
    EXPECT_EQ(value, std::string(300, 'c'));

    results.clear();
    deleted.clear();
    EXPECT_TRUE(m_mgr->scan("", results, deleted));
    EXPECT_EQ(results, expected_results);
    EXPECT_TRUE(deleted.empty());
}

INSTANTIATE_TEST_SUITE_P(Layouts, LSMIOSSTableStreamRestartTest,
                         ::testing::Values(StreamRestartParam{"footer_manual", true, true},
                                           StreamRestartParam{"footerless_manual", true, false},
                                           StreamRestartParam{"footerless_tellp", false, false}),
                         [](const ::testing::TestParamInfo<StreamRestartParam>& info) {
                             return info.param.name;
                         });

enum class FooterRegionLayout {
    EndsAtEof,
    OnePastEof,
    HugeInFooter
};

struct FooterRegionParam {
    std::string name;
    ReadMode mode;
    FooterRegionLayout layout;
};

class LSMIOSSTableFooterRegionTest : public LSMIOSSTableCraftedTest,
                                     public ::testing::WithParamInterface<FooterRegionParam> {};

TEST_P(LSMIOSSTableFooterRegionTest, ReadMatchesFileLength) {
    const auto& param = GetParam();
    gConfigLSMIO.enableMMAP = (param.mode == ReadMode::Mmap);
    gConfigLSMIO.enablePread = (param.mode == ReadMode::Pread);

    CraftedSSTable table;
    std::string test_key;
    if (param.layout == FooterRegionLayout::EndsAtEof) {
        test_key = "k";
        table.addLe32(1);
        table.addRaw("k");
        table.addLe32(31);
        table.addRaw("ab");
        table.addFooter({{"k", 0}});
    } else if (param.layout == FooterRegionLayout::OnePastEof) {
        test_key = "k";
        table.addLe32(1);
        table.addRaw("k");
        table.addLe32(32);
        table.addRaw("ab");
        table.addFooter({{"k", 0}});
    } else {
        test_key = std::string("\x01", 1);
        table.addRecord("x", "1");
        table.addFooter({{std::string("\x01", 1), 10}});
        ASSERT_EQ(table.bytes().substr(10, 9),
                  std::string("\x01\x00\x00\x00\x01\x00\x00\x00\x01", 9));
    }
    table.writeTo(tablePath(1));

    // Write empty newer table to cover m_file_len > 0 false side in initReader
    CraftedSSTable().writeTo(tablePath(2));

    openManager();

    if (param.layout == FooterRegionLayout::EndsAtEof) {
        std::string value = "sentinel";
        EXPECT_TRUE(m_mgr->get(test_key, value));
        EXPECT_EQ(value, table.bytes().substr(9));
        std::map<std::string, std::string> results;
        std::set<std::string> deleted;
        EXPECT_TRUE(m_mgr->scan("", results, deleted));
        std::map<std::string, std::string> expected_results = {{test_key, table.bytes().substr(9)}};
        EXPECT_EQ(results, expected_results);
        EXPECT_TRUE(deleted.empty());
        EXPECT_EQ(m_mgr->getPreadSlowPathCount(), 0u);
    } else {
        std::string value = "sentinel";
        EXPECT_FALSE(m_mgr->get(test_key, value));
        EXPECT_EQ(value, "sentinel");
        std::map<std::string, std::string> results;
        std::set<std::string> deleted;
        EXPECT_FALSE(m_mgr->scan("", results, deleted));
        EXPECT_TRUE(results.empty());
        EXPECT_TRUE(deleted.empty());
        EXPECT_EQ(m_mgr->getPreadSlowPathCount(), 0u);
    }
}

INSTANTIATE_TEST_SUITE_P(
    Layouts, LSMIOSSTableFooterRegionTest,
    ::testing::Values(
        FooterRegionParam{"ends_at_eof_mmap", ReadMode::Mmap, FooterRegionLayout::EndsAtEof},
        FooterRegionParam{"ends_at_eof_pread", ReadMode::Pread, FooterRegionLayout::EndsAtEof},
        FooterRegionParam{"ends_at_eof_stream", ReadMode::Stream, FooterRegionLayout::EndsAtEof},
        FooterRegionParam{"one_past_eof_mmap", ReadMode::Mmap, FooterRegionLayout::OnePastEof},
        FooterRegionParam{"one_past_eof_pread", ReadMode::Pread, FooterRegionLayout::OnePastEof},
        FooterRegionParam{"one_past_eof_stream", ReadMode::Stream, FooterRegionLayout::OnePastEof},
        FooterRegionParam{"huge_in_footer_mmap", ReadMode::Mmap, FooterRegionLayout::HugeInFooter},
        FooterRegionParam{"huge_in_footer_pread", ReadMode::Pread,
                          FooterRegionLayout::HugeInFooter},
        FooterRegionParam{"huge_in_footer_stream", ReadMode::Stream,
                          FooterRegionLayout::HugeInFooter}),
    [](const ::testing::TestParamInfo<FooterRegionParam>& info) { return info.param.name; });

}  // namespace

// Out-of-contract: a table shrunk after open breaks AI-5's premise. Verifies the stream path
// uses the stored length, allocating then clearing the value on a failed read; not a supported use.
TEST_F(LSMIOSSTableCraftedTest, StreamShrunkAfterOpenClearsValue) {
    gConfigLSMIO.enableMMAP = false;
    gConfigLSMIO.enablePread = false;

    CraftedSSTable table;
    table.addRecord("k", std::string(100, 'v'));
    table.addFooter({{"k", 0}});
    table.writeTo(tablePath(1));

    openManager();
    std::filesystem::resize_file(tablePath(1), 50);

    std::string value = "sentinel";
    EXPECT_FALSE(m_mgr->get("k", value));
    EXPECT_EQ(value, "");

    std::map<std::string, std::string> results;
    std::set<std::string> deleted;
    EXPECT_FALSE(m_mgr->scan("", results, deleted));
    EXPECT_TRUE(results.empty());
}

// Out-of-contract: a table grown after open breaks AI-5's premise. Verifies AI-15's fail-closed
// stream check refuses a record past the stored length; not a supported use.
TEST_F(LSMIOSSTableCraftedTest, StreamGrownAfterOpenRefusesRecordPastStoredLength) {
    gConfigLSMIO.enableMMAP = false;
    gConfigLSMIO.enablePread = false;

    CraftedSSTable table;
    table.addRecord("x", "1");
    table.addFooter({{"x", 0}, {"k", 52}});
    table.writeTo(tablePath(1));

    openManager();

    CraftedSSTable append_table;
    append_table.addRecord("k", "abc");
    appendToFile(tablePath(1), append_table.bytes());

    std::string value = "sentinel";
    EXPECT_FALSE(m_mgr->get("k", value));
    EXPECT_EQ(value, "sentinel");

    value = "sentinel";
    EXPECT_TRUE(m_mgr->get("x", value));
    EXPECT_EQ(value, "1");
}

// Out-of-contract: a table grown after open breaks AI-5's premise. Verifies AI-15's pread
// slow-path check refuses a record past the stored length before the slow-path counter; not a
// supported use.
TEST_F(LSMIOSSTableCraftedTest, PreadGrownAfterOpenRefusesSlowPathPastStoredLength) {
    CraftedSSTable table;
    table.addRecord("x", "1");
    table.addFooter({{"x", 0}, {"k", 53}});
    table.writeTo(tablePath(1));

    openManager();

    CraftedSSTable append_table;
    append_table.addRaw("z");
    append_table.addRecord("k", std::string(204800, 'v'));
    appendToFile(tablePath(1), append_table.bytes());

    std::string value = "sentinel";
    EXPECT_FALSE(m_mgr->get("k", value));
    EXPECT_EQ(value, "sentinel");
    EXPECT_EQ(m_mgr->getPreadSlowPathCount(), 0u);

    value = "sentinel";
    EXPECT_TRUE(m_mgr->get("x", value));
    EXPECT_EQ(value, "1");
    EXPECT_EQ(m_mgr->getPreadSlowPathCount(), 0u);
}
