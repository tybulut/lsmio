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

#include <lsmio/manager/store/native/MemtableBTree.hpp>
#include <lsmio/manager/store/native/MemtableOrdered.hpp>
#include <lsmio/manager/store/native/MemtableVectorNoSort.hpp>
#include <lsmio/manager/store/native/MemtableVectorSort.hpp>

using namespace lsmio;

TEST(MemtableTest, BasicAddGet) {
    MemtableVectorNoSort m;
    m.add("key1", "value1");
    m.add("key2", "value2");

    std::string val;
    EXPECT_TRUE(m.get("key1", val));
    EXPECT_EQ(val, "value1");
    EXPECT_TRUE(m.get("key2", val));
    EXPECT_EQ(val, "value2");
    EXPECT_FALSE(m.get("key3", val));
}

TEST(MemtableTest, Overwrite) {
    MemtableVectorNoSort m;
    m.add("key1", "value1");
    m.add("key1", "value2");

    std::string val;
    EXPECT_TRUE(m.get("key1", val));
    EXPECT_EQ(val, "value2");  // Expect latest value
}

TEST(MemtableTest, Tombstone) {
    MemtableVectorNoSort m;
    m.add("key1", "value1");
    m.add("key1", MEMTABLE_TOMBSTONE);  // logical delete

    std::string val;
    EXPECT_TRUE(m.get("key1", val));     // It exists in memtable
    EXPECT_EQ(val, MEMTABLE_TOMBSTONE);  // But it is a tombstone
}

TEST(MemtableTest, ScanPrefix) {
    MemtableVectorNoSort m;
    m.add("prefix/a", "1");
    m.add("prefix/b", "2");
    m.add("other/c", "3");
    m.add("prefix/d", "4");
    m.add("prefix/b", MEMTABLE_TOMBSTONE);  // delete 'prefix/b'

    std::map<std::string, std::string> results;
    std::set<std::string> deleted;

    m.scan("prefix/", results, deleted);

    EXPECT_EQ(results.size(), 2);
    EXPECT_EQ(results["prefix/a"], "1");
    EXPECT_EQ(results["prefix/d"], "4");

    EXPECT_TRUE(deleted.find("prefix/b") != deleted.end());
    EXPECT_FALSE(results.count("prefix/b"));
}

TEST(MemtableTest, SizeTracking) {
    MemtableVectorNoSort m;
    EXPECT_EQ(m.sizeBytes(), 0);

    m.add("k", "v");
    // "k" (1) + "v" (1) = 2
    EXPECT_EQ(m.sizeBytes(), 2);

    m.add("k", "v2");
    // Previous entry remains in vector logic, so size accumulates
    // "k" (1) + "v2" (2) = 3. Total 5.
    EXPECT_EQ(m.sizeBytes(), 5);
}

TEST(MemtableTest, MemtableVectorNoSort_MoveAdd) {
    std::string k = "vec_ns_k";
    std::string v = "vec_ns_val";
    const std::string exp_v = v;
    const size_t exp_bytes = k.size() + v.size();
    MemtableVectorNoSort m;
    m.add(k, std::move(v));
    std::string out;
    EXPECT_TRUE(m.get(k, out));
    EXPECT_EQ(out, exp_v);
    EXPECT_EQ(m.sizeBytes(), exp_bytes);
}

TEST(MemtableTest, MemtableVectorSort_MoveAddAndOverwrite) {
    std::string k = "vec_s_k";
    std::string v = "vec_s_val";
    const std::string exp_v = v;
    const size_t exp_bytes = k.size() + v.size();
    MemtableVectorSort m;
    m.add(k, std::move(v));
    std::string out;
    EXPECT_TRUE(m.get(k, out));
    EXPECT_EQ(out, exp_v);
    EXPECT_EQ(m.sizeBytes(), exp_bytes);

    // Overwrite:
    std::string v2 = "longer_vec_s_val";
    const std::string exp_v2 = v2;
    const size_t exp_bytes2 = k.size() + v2.size();
    m.add(k, std::move(v2));
    EXPECT_TRUE(m.get(k, out));
    EXPECT_EQ(out, exp_v2);
    EXPECT_EQ(m.count(), 1);
    EXPECT_EQ(m.sizeBytes(), exp_bytes2);
}

TEST(MemtableTest, MemtableOrderedMap_MoveAddAndOverwrite) {
    MemtableOrdered<std::map<std::string, std::string>> m;
    std::string k = "map_k";
    std::string v = "map_val";
    const std::string exp_v = v;
    const size_t exp_bytes = k.size() + v.size();
    m.add(k, std::move(v));
    std::string out;
    EXPECT_TRUE(m.get(k, out));
    EXPECT_EQ(out, exp_v);
    EXPECT_EQ(m.sizeBytes(), exp_bytes);

    // Overwrite:
    std::string v2 = "new_map_val_longer";
    const std::string exp_v2 = v2;
    const size_t exp_bytes2 = k.size() + v2.size();
    m.add(k, std::move(v2));
    EXPECT_TRUE(m.get(k, out));
    EXPECT_EQ(out, exp_v2);
    EXPECT_EQ(m.count(), 1);
    EXPECT_EQ(m.sizeBytes(), exp_bytes2);
}

TEST(MemtableTest, MemtableBTree_MoveAddAndOverwrite) {
    MemtableBTree m;
    // Insert path:
    std::string k = "btree_k";
    std::string v = "btree_val";
    const std::string exp_v = v;
    const size_t exp_bytes = k.size() + v.size();
    m.add(k, std::move(v));
    std::string out;
    EXPECT_TRUE(m.get(k, out));
    EXPECT_EQ(out, exp_v);
    EXPECT_EQ(m.sizeBytes(), exp_bytes);

    // Overwrite path:
    std::string v2 = "btree_val_updated_longer";
    const std::string exp_v2 = v2;
    const size_t exp_bytes2 = k.size() + v2.size();
    m.add(k, std::move(v2));
    EXPECT_TRUE(m.get(k, out));
    EXPECT_EQ(out, exp_v2);
    EXPECT_EQ(m.count(), 1);
    EXPECT_EQ(m.sizeBytes(), exp_bytes2);
}

// A value added by const reference is copied: changing the caller's string afterwards does not
// reach the memtable, on insert and on overwrite
template <typename M>
static void expectConstRefAddCopies() {
    M m;
    std::string v = "first";
    m.add("k", v);
    v.assign("XXXXX");
    std::string out;
    EXPECT_TRUE(m.get("k", out));
    EXPECT_EQ(out, "first");

    std::string v2 = "second_longer";
    m.add("k", v2);
    v2.assign("YYYYYYYYYYYYY");
    EXPECT_TRUE(m.get("k", out));
    EXPECT_EQ(out, "second_longer");
}

TEST(MemtableTest, ConstRefAddCopies) {
    expectConstRefAddCopies<MemtableVectorNoSort>();
    expectConstRefAddCopies<MemtableVectorSort>();
    expectConstRefAddCopies<MemtableOrdered<std::map<std::string, std::string>>>();
    expectConstRefAddCopies<MemtableBTree>();
}

// A key that is absent but lies between stored keys, below the first key or above the last key is
// a miss: get returns false and never writes the output
TEST(MemtableTest, MemtableVectorSort_GetMissBetweenKeys) {
    MemtableVectorSort m;
    m.add("a", "va");
    m.add("c", "vc");
    std::string out = "sentinel";

    EXPECT_FALSE(m.get("b", out));  // lower bound lands on "c"
    EXPECT_EQ(out, "sentinel");
    EXPECT_FALSE(m.get("", out));  // lower bound lands on "a"
    EXPECT_EQ(out, "sentinel");
    EXPECT_FALSE(m.get("d", out));  // lower bound is end()
    EXPECT_EQ(out, "sentinel");
    EXPECT_EQ(m.count(), 2u);

    EXPECT_TRUE(m.get("c", out));  // the neighbour is intact
    EXPECT_EQ(out, "vc");
}

// scan walks from the prefix's lower bound while the prefix matches; it stops at the first key
// past the prefix and merges every entry through applyScanEntry
TEST(MemtableTest, MemtableVectorSort_ScanEmpty) {
    MemtableVectorSort m;
    std::map<std::string, std::string> results;
    std::set<std::string> deleted;

    m.scan("a", results, deleted);

    EXPECT_TRUE(results.empty());
    EXPECT_TRUE(deleted.empty());
}

TEST(MemtableTest, MemtableVectorSort_ScanStopsAtPrefixEnd) {
    MemtableVectorSort m;
    m.add("a1", "v1");
    m.add("a2", "v2");
    m.add("b1", "v3");
    std::map<std::string, std::string> results;
    std::set<std::string> deleted;

    m.scan("a", results, deleted);

    EXPECT_EQ(results, (std::map<std::string, std::string>{{"a1", "v1"}, {"a2", "v2"}}));
    EXPECT_TRUE(deleted.empty());  // stops at "b1"
}

TEST(MemtableTest, MemtableVectorSort_ScanRunsToEnd) {
    MemtableVectorSort m;
    m.add("a1", "v1");
    m.add("a2", "v2");
    m.add("b1", "v3");
    std::map<std::string, std::string> results;
    std::set<std::string> deleted;

    m.scan("b", results, deleted);

    EXPECT_EQ(results, (std::map<std::string, std::string>{{"b1", "v3"}}));
    EXPECT_TRUE(deleted.empty());  // the loop ends at end(), no break
}

TEST(MemtableTest, MemtableVectorSort_ScanAbsentPrefix) {
    MemtableVectorSort m;
    m.add("a1", "v1");
    m.add("a2", "v2");
    m.add("b1", "v3");

    // "aa": lower bound "b1"; "z": lower bound end(); "a1x": lower bound "a2"
    for (const char* prefix : {"aa", "z", "a1x"}) {
        SCOPED_TRACE(prefix);
        std::map<std::string, std::string> results;
        std::set<std::string> deleted;
        m.scan(prefix, results, deleted);
        EXPECT_TRUE(results.empty());
        EXPECT_TRUE(deleted.empty());
    }
}

TEST(MemtableTest, MemtableVectorSort_ScanEmptyPrefixReturnsAll) {
    MemtableVectorSort m;
    m.add("a1", "v1");
    m.add("a2", "v2");
    m.add("b1", "v3");
    std::map<std::string, std::string> results;
    std::set<std::string> deleted;

    m.scan("", results, deleted);

    EXPECT_EQ(results,
              (std::map<std::string, std::string>{{"a1", "v1"}, {"a2", "v2"}, {"b1", "v3"}}));
    EXPECT_TRUE(deleted.empty());
}

TEST(MemtableTest, MemtableVectorSort_ScanMergesTombstones) {
    MemtableVectorSort m;
    m.add("a1", "v1");
    m.add("a2", "v2");
    m.add("b1", "v3");
    m.add("a3", MEMTABLE_TOMBSTONE);
    // As a newer table's caller holds them from an older one: a3 live, a1 deleted
    std::map<std::string, std::string> results{{"a3", "older"}};
    std::set<std::string> deleted{"a1"};

    m.scan("a", results, deleted);

    // a3's older value is retracted by its tombstone; a1 is re-added and its deletion retracted
    EXPECT_EQ(results, (std::map<std::string, std::string>{{"a1", "v1"}, {"a2", "v2"}}));
    EXPECT_EQ(deleted, std::set<std::string>{"a3"});
    EXPECT_EQ(m.count(), 4u);  // the scan does not change the memtable
}

// The B+ tree holds slots, the values live beside it: many inserts (node splits) and overwrites
// keep every key on its own value, in key order, with exact size accounting
TEST(MemtableTest, MemtableBTree_ManyKeysOrderAndOverwrite) {
    MemtableBTree m;
    std::map<std::string, std::string> model;
    size_t bytes = 0;
    for (int i = 0; i < 5000; ++i) {
        const int k = (i * 7919) % 3000;  // revisits keys: inserts and overwrites interleave
        std::string key = "key" + std::to_string(k);
        std::string val(1 + (i % 97), static_cast<char>('a' + i % 26));
        auto it = model.find(key);
        if (it == model.end()) {
            bytes += key.size() + val.size();
        } else {
            bytes += val.size();
            bytes -= it->second.size();
        }
        model[key] = val;
        if (i % 2) {
            m.add(key, val);
        } else {
            m.add(key, std::move(val));
        }
    }
    EXPECT_EQ(m.count(), model.size());
    EXPECT_EQ(m.sizeBytes(), bytes);

    auto expected = model.begin();
    m.forEach([&](const std::string& f_key, const std::string& f_value) {
        ASSERT_NE(expected, model.end());
        EXPECT_EQ(f_key, expected->first);
        EXPECT_EQ(f_value, expected->second);
        ++expected;
    });
    EXPECT_EQ(expected, model.end());

    std::map<std::string, std::string> results;
    std::set<std::string> deleted;
    m.add("key12", MEMTABLE_TOMBSTONE);
    m.scan("key12", results, deleted);
    EXPECT_EQ(deleted.count("key12"), 1u);
    for (const auto& [key, value] : results) {
        EXPECT_EQ(key.compare(0, 5, "key12"), 0);
        EXPECT_EQ(value, model[key]);
    }
    EXPECT_EQ(results.size(), 110u);  // key120..key129 and key1200..key1299; key12 is deleted
}
