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
#include <lsmio/manager/store/native/memtable.hpp>
#include <lsmio/manager/store/native/sstable_manager.hpp>

using namespace lsmio;

class SSTableManagerTest : public ::testing::Test {
  protected:
    std::string dbPath = "test_sstable_mgr_db";
    std::unique_ptr<SSTableManager> mgr;

    void SetUp() override {
        if (std::filesystem::exists(dbPath)) {
            std::filesystem::remove_all(dbPath);
        }
        std::filesystem::create_directories(dbPath);

        mgr = std::make_unique<SSTableManager>(dbPath, 10, 0);
    }

    void TearDown() override {
        mgr.reset();
        if (std::filesystem::exists(dbPath)) {
            std::filesystem::remove_all(dbPath);
        }
    }
};

TEST_F(SSTableManagerTest, FlushAndGet) {
    Memtable m;
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
        Memtable m;
        m.add("key1", "val1");
        std::vector<char> buf(1024);
        mgr->flushMemtable(m, buf);
    }

    // Simulate restart
    mgr.reset();  // Destroy old manager

    // Create new manager (triggers recovery in constructor)
    auto newMgr = std::make_unique<SSTableManager>(dbPath, 10, 0);

    std::string val;
    EXPECT_TRUE(newMgr->get("key1", val));
    EXPECT_EQ(val, "val1");
}

TEST_F(SSTableManagerTest, Tombstone) {
    Memtable m;
    m.add("key1", MEMTABLE_TOMBSTONE);
    std::vector<char> buf(1024);
    mgr->flushMemtable(m, buf);

    std::string val;
    EXPECT_TRUE(mgr->get("key1", val));
    EXPECT_EQ(val, MEMTABLE_TOMBSTONE);
}

TEST_F(SSTableManagerTest, Scan) {
    Memtable m1;
    m1.add("prefix/a", "1");
    std::vector<char> buf(1024);
    mgr->flushMemtable(m1, buf);

    Memtable m2;
    m2.add("prefix/b", "2");
    mgr->flushMemtable(m2, buf);

    std::map<std::string, std::string> results;
    std::set<std::string> deleted;

    EXPECT_TRUE(mgr->scan("prefix/", results, deleted));
    EXPECT_EQ(results.size(), 2);
    EXPECT_EQ(results["prefix/a"], "1");
    EXPECT_EQ(results["prefix/b"], "2");
}