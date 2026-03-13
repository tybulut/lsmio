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

#include <cstdlib>
#include <filesystem>
#include <lsmio/manager/store/native/sstable_manager.hpp>

class SSTableManagerTest : public ::testing::Test {
  protected:
    std::string test_dir = "test_sstable_mgr_dir";
    char* buf{nullptr};
    size_t buf_capacity = 1024 * 1024;

    void SetUp() override {
        if (std::filesystem::exists(test_dir)) std::filesystem::remove_all(test_dir);
        std::filesystem::create_directory(test_dir);
        if (::posix_memalign(reinterpret_cast<void**>(&buf), 4096, buf_capacity) != 0) {
            throw std::runtime_error("posix_memalign failed in test setup");
        }
    }
    void TearDown() override {
        if (std::filesystem::exists(test_dir)) std::filesystem::remove_all(test_dir);
        if (buf) std::free(buf);
    }
};

TEST_F(SSTableManagerTest, FlushAndGet) {
    auto mgr = std::make_unique<lsmio::SSTableManager>(test_dir, 2, 0);
    lsmio::Memtable m;
    m.add("key1", "value1");
    m.add("key2", "value2");

    ASSERT_TRUE(mgr->flushMemtable(m, buf, buf_capacity, 0));

    std::string val;
    EXPECT_TRUE(mgr->get("key1", val));
    EXPECT_EQ(val, "value1");
    EXPECT_TRUE(mgr->get("key2", val));
    EXPECT_EQ(val, "value2");
    EXPECT_FALSE(mgr->get("key3", val));
}

TEST_F(SSTableManagerTest, Recovery) {
    {
        auto mgr = std::make_unique<lsmio::SSTableManager>(test_dir, 2, 0);
        lsmio::Memtable m;
        m.add("a", "1");
        mgr->flushMemtable(m, buf, buf_capacity, 0);
    }

    // New manager should recover
    auto mgr2 = std::make_unique<lsmio::SSTableManager>(test_dir, 2, 0);
    std::string val;
    EXPECT_TRUE(mgr2->get("a", val));
    EXPECT_EQ(val, "1");
}

TEST_F(SSTableManagerTest, Tombstone) {
    auto mgr = std::make_unique<lsmio::SSTableManager>(test_dir, 2, 0);
    lsmio::Memtable m;
    m.add("deleted", lsmio::MEMTABLE_TOMBSTONE);
    mgr->flushMemtable(m, buf, buf_capacity, 0);

    std::string val;
    EXPECT_TRUE(mgr->get("deleted", val));
    EXPECT_EQ(val, lsmio::MEMTABLE_TOMBSTONE);
}

TEST_F(SSTableManagerTest, Scan) {
    auto mgr = std::make_unique<lsmio::SSTableManager>(test_dir, 2, 0);
    lsmio::Memtable m1;
    m1.add("prefix/a", "1");
    mgr->flushMemtable(m1, buf, buf_capacity, 0);

    lsmio::Memtable m2;
    m2.add("prefix/b", "2");
    mgr->flushMemtable(m2, buf, buf_capacity, 1);

    std::map<std::string, std::string> results;
    std::set<std::string> deleted;

    EXPECT_TRUE(mgr->scan("prefix/", results, deleted));
    EXPECT_EQ(results.size(), 2);
    EXPECT_EQ(results["prefix/a"], "1");
    EXPECT_EQ(results["prefix/b"], "2");
}
