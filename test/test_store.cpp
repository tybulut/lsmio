/*
 * Copyright 2026 Serdar Bulut
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

#include <lsmio/lsmio.hpp>
#include <lsmio/manager/store/store.hpp>
#include <map>
#include <string>
#include <string_view>
#include <tuple>
#include <utility>
#include <vector>

namespace {

struct RecordedMutation {
    lsmio::MutationType type;
    std::string key;
    std::string value;
    bool flush;
};

// The smallest concrete LSMIOStore: an in-memory map that records every mutation. It does not
// override putBytes, put, del or the rvalue _batchMutation, so the base-class versions run; its
// writeBarrier calls the base LSMIOStore::writeBarrier explicitly.
class StubStore : public lsmio::LSMIOStore {
  public:
    explicit StubStore(const std::string& dbPath) : lsmio::LSMIOStore(dbPath) {}
    ~StubStore() override = default;

    std::vector<RecordedMutation> m_mutations;
    std::map<std::string, std::string> m_data;
    std::vector<std::string> m_prefix_queries;
    int m_stop_batch_calls = 0;
    bool m_stop_batch_result = true;

    const std::string& dbPath() const {
        return _dbPath;
    }
    int maxBatchSize() const {
        return _maxBatchSize;
    }
    int maxBatchBytes() const {
        return _maxBatchBytes;
    }
    const std::string& metaPrefix() const {
        return _metaPrefix;
    }

    void close() override {}

    bool get(const std::string key, std::string* value) override {
        auto it = m_data.find(key);
        if (it == m_data.end()) return false;
        *value = it->second;
        return true;
    }

    bool getPrefix(const std::string key,
                   std::vector<std::tuple<std::string, std::string>>* values) override {
        m_prefix_queries.push_back(key);
        for (auto it = m_data.lower_bound(key);
             it != m_data.end() && it->first.compare(0, key.size(), key) == 0; ++it) {
            values->emplace_back(it->first, it->second);
        }
        return true;
    }

    bool readBarrier() override {
        return true;
    }
    bool writeBarrier() override {
        return lsmio::LSMIOStore::writeBarrier();
    }

  protected:
    bool startBatch() override {
        return true;
    }
    bool stopBatch() override {
        ++m_stop_batch_calls;
        return m_stop_batch_result;
    }
    bool dbCleanup() override {
        m_data.clear();
        return true;
    }
    bool _batchMutation(lsmio::MutationType mType, const std::string& key, const std::string& value,
                        bool flush) override {
        m_mutations.push_back({mType, key, value, flush});
        if (mType == lsmio::MutationType::Put) {
            m_data[key] = value;
        } else {
            m_data.erase(key);
        }
        return true;
    }
};

class LSMIOStoreTest : public ::testing::Test {
  protected:
    lsmio::LSMIOConfig m_backup_config;
    void SetUp() override {
        m_backup_config = lsmio::gConfigLSMIO;
    }
    void TearDown() override {
        lsmio::gConfigLSMIO = m_backup_config;
    }
};

}  // namespace

TEST(LSMIOStoreMutationTypeTest, Names) {
    const std::vector<std::pair<lsmio::MutationType, std::string>> rows = {
        {lsmio::MutationType::Put, "Put"},
        {lsmio::MutationType::Del, "Del"},
        {static_cast<lsmio::MutationType>(7), ""},
    };
    for (const auto& row : rows) {
        SCOPED_TRACE(row.second);
        EXPECT_EQ(lsmio::getMutationType(row.first), row.second);
    }
}

TEST_F(LSMIOStoreTest, ConstructorSnapshotsConfig) {
    lsmio::gConfigLSMIO.asyncBatchSize = 7;
    lsmio::gConfigLSMIO.asyncBatchBytes = 1234;
    StubStore s("stub-store-path");
    lsmio::gConfigLSMIO.asyncBatchSize = 99;
    lsmio::gConfigLSMIO.asyncBatchBytes = 99;
    EXPECT_EQ(s.dbPath(), "stub-store-path");
    EXPECT_EQ(s.maxBatchSize(), 7);
    EXPECT_EQ(s.maxBatchBytes(), 1234);
    EXPECT_EQ(s.metaPrefix(), "__lsmio_md::");
    EXPECT_TRUE(s.m_mutations.empty());
}

TEST_F(LSMIOStoreTest, PutBytesCopiesIntoOnePutMutation) {
    StubStore s("stub");
    std::vector<char> buf = {'a', '\0', 'b', 'c'};
    EXPECT_TRUE(s.putBytes("k", std::string_view(buf.data(), buf.size()), false));
    buf.assign(buf.size(), 'X');
    ASSERT_EQ(s.m_mutations.size(), 1u);
    EXPECT_EQ(s.m_mutations[0].type, lsmio::MutationType::Put);
    EXPECT_EQ(s.m_mutations[0].key, "k");
    EXPECT_EQ(s.m_mutations[0].value, std::string("a\0bc", 4));
    EXPECT_FALSE(s.m_mutations[0].flush);
    std::string v;
    EXPECT_TRUE(s.get("k", &v));
    EXPECT_EQ(v, std::string("a\0bc", 4));
}

TEST_F(LSMIOStoreTest, PutBytesEmptyValueDefaultFlush) {
    StubStore s("stub");
    EXPECT_TRUE(s.putBytes("e", std::string_view()));
    ASSERT_EQ(s.m_mutations.size(), 1u);
    EXPECT_EQ(s.m_mutations[0].type, lsmio::MutationType::Put);
    EXPECT_EQ(s.m_mutations[0].key, "e");
    EXPECT_EQ(s.m_mutations[0].value, "");
    EXPECT_TRUE(s.m_mutations[0].flush);
    EXPECT_EQ(s.m_data.count("e"), 1u);
}

TEST_F(LSMIOStoreTest, RvaluePutAndDelUseBaseForwarder) {
    StubStore s("stub");
    std::string moved = "v2";
    EXPECT_TRUE(s.put("k2", std::move(moved), true));
    const std::string copied = "v3";
    EXPECT_TRUE(s.put("k3", copied, false));
    EXPECT_TRUE(s.del("k2", false));
    ASSERT_EQ(s.m_mutations.size(), 3u);
    EXPECT_EQ(s.m_mutations[0].type, lsmio::MutationType::Put);
    EXPECT_EQ(s.m_mutations[0].key, "k2");
    EXPECT_EQ(s.m_mutations[0].value, "v2");
    EXPECT_TRUE(s.m_mutations[0].flush);
    EXPECT_EQ(s.m_mutations[1].key, "k3");
    EXPECT_EQ(s.m_mutations[1].value, "v3");
    EXPECT_FALSE(s.m_mutations[1].flush);
    EXPECT_EQ(s.m_mutations[2].type, lsmio::MutationType::Del);
    EXPECT_EQ(s.m_mutations[2].key, "k2");
    EXPECT_EQ(s.m_mutations[2].value, "");
    EXPECT_FALSE(s.m_mutations[2].flush);
    EXPECT_EQ(s.m_data.count("k2"), 0u);
    EXPECT_EQ(s.m_data.at("k3"), "v3");
}

TEST_F(LSMIOStoreTest, WriteBarrierCallsStopBatch) {
    StubStore s("stub");
    EXPECT_TRUE(s.writeBarrier());
    EXPECT_EQ(s.m_stop_batch_calls, 1);
}

TEST_F(LSMIOStoreTest, WriteBarrierReportsStopBatchFailure) {
    StubStore s("stub");
    s.m_stop_batch_result = false;
    EXPECT_FALSE(s.writeBarrier());
    EXPECT_EQ(s.m_stop_batch_calls, 1);
}

TEST_F(LSMIOStoreTest, MetaGetAllWithAndWithoutInFix) {
    StubStore s("stub");
    EXPECT_TRUE(s.metaPut("a1", std::string("x1")));
    const std::string v2 = "x2";
    EXPECT_TRUE(s.metaPut("a2", v2));
    EXPECT_TRUE(s.metaPut("b1", std::string("y1")));
    EXPECT_TRUE(s.put("plain", std::string("p")));

    std::vector<std::tuple<std::string, std::string>> in_fixed;
    EXPECT_TRUE(s.metaGetAll(&in_fixed, "a"));
    EXPECT_EQ(s.m_prefix_queries.back(), "__lsmio_md::a");
    ASSERT_EQ(in_fixed.size(), 2u);
    EXPECT_EQ(in_fixed[0], std::make_tuple(std::string("__lsmio_md::a1"), std::string("x1")));
    EXPECT_EQ(in_fixed[1], std::make_tuple(std::string("__lsmio_md::a2"), std::string("x2")));

    std::vector<std::tuple<std::string, std::string>> all;
    EXPECT_TRUE(s.metaGetAll(&all));
    EXPECT_EQ(s.m_prefix_queries.back(), "__lsmio_md::");
    EXPECT_EQ(all.size(), 3u);

    std::vector<std::tuple<std::string, std::string>> none;
    EXPECT_TRUE(s.metaGetAll(&none, "zz"));
    EXPECT_EQ(s.m_prefix_queries.back(), "__lsmio_md::zz");
    EXPECT_TRUE(none.empty());

    std::string got;
    EXPECT_TRUE(s.metaGet("b1", &got));
    EXPECT_EQ(got, "y1");
    EXPECT_FALSE(s.metaGet("plain", &got));
}

int main(int argc, char** argv) {
    lsmio::initLSMIODebug(argv[0]);
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
