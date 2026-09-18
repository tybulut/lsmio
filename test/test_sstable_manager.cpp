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
#include <lsmio/manager/store/native/MemtableVectorNoSort.hpp>
#include <lsmio/manager/store/native/SSTableManager.hpp>
#include <lsmio/manager/store/native/StoreNative.hpp>
#include <stdexcept>
#include <thread>

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

    // The fixture manager was built without preallocation; recreate it with a
    // real preallocation size so the .sst is ftruncated large and the flush
    // must trim it back for the footer magic to land at physical EOF.
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
