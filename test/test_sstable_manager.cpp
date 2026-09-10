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

#include <filesystem>
#include <fstream>
#include <lsmio/manager/store/native/MemtableVectorNoSort.hpp>
#include <lsmio/manager/store/native/SSTableManager.hpp>
#include <lsmio/manager/store/native/StoreNative.hpp>
#include <stdexcept>

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

    // Large value > 64 KiB to trigger pread speculative buffer slow path (2-stage pread)
    std::string large_val(70 * 1024, 'Z');
    m.add("large_key", large_val);

    std::vector<char> buf(128 * 1024);
    ASSERT_TRUE(mgr->flushMemtable(m, buf));

    std::string val;
    // Fast path (< 64 KiB)
    EXPECT_TRUE(mgr->get("small_key", val));
    EXPECT_EQ(val, "small_val");

    // Slow path (> 64 KiB)
    EXPECT_TRUE(mgr->get("large_key", val));
    EXPECT_EQ(val.size(), 70 * 1024);
    EXPECT_EQ(val, large_val);

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
    EXPECT_TRUE(new_mgr->get("small_key", val));
    EXPECT_EQ(val, "small_val");
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

