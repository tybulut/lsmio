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

#include <lsmio/manager/store/native/memtable.hpp>

using namespace lsmio;

TEST(MemtableTest, BasicAddGet) {
    Memtable m;
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
    Memtable m;
    m.add("key1", "value1");
    m.add("key1", "value2");

    std::string val;
    EXPECT_TRUE(m.get("key1", val));
    EXPECT_EQ(val, "value2");  // Expect latest value
}

TEST(MemtableTest, Tombstone) {
    Memtable m;
    m.add("key1", "value1");
    m.add("key1", MEMTABLE_TOMBSTONE);  // logical delete

    std::string val;
    EXPECT_TRUE(m.get("key1", val));     // It exists in memtable
    EXPECT_EQ(val, MEMTABLE_TOMBSTONE);  // But it is a tombstone
}

TEST(MemtableTest, ScanPrefix) {
    Memtable m;
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
    Memtable m;
    EXPECT_EQ(m.sizeBytes(), 0);

    m.add("k", "v");
    // "k" (1) + "v" (1) = 2
    EXPECT_EQ(m.sizeBytes(), 2);

    m.add("k", "v2");
    // Previous entry remains in vector logic, so size accumulates
    // "k" (1) + "v2" (2) = 3. Total 5.
    EXPECT_EQ(m.sizeBytes(), 5);
}
