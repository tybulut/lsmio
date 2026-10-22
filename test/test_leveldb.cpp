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

#include <algorithm>
#include <filesystem>
#include <iostream>
#include <lsmio/manager/store/store_ldb.hpp>
#include <string>
#include <string_view>
#include <vector>

const std::string TEST_DIR_LDB = "";

TEST(lsmioLevelDB, Flush) {
    bool success = true;
    std::string value;

    std::string key1 = "serdar";
    std::string key2 = "bulut";
    std::string value1 = "alpino";
    std::string value2 = "teomos";

    std::string dbName = "test-ldb-store-flush.db";
    std::string dbPath = TEST_DIR_LDB.empty() ? dbName : TEST_DIR_LDB + "/" + dbName;

    lsmio::LSMIOStoreLDB lc(dbPath);
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

TEST(lsmioLevelDB, Deferred) {
    bool success = true;
    std::string value;

    std::string key1 = "serdar";
    std::string key2 = "bulut";
    std::string value1 = "alpino";
    std::string value2 = "teomos";

    std::string dbName = "test-ldb-store-deferred.db";
    std::string dbPath = TEST_DIR_LDB.empty() ? dbName : TEST_DIR_LDB + "/" + dbName;

    lsmio::LSMIOStoreLDB lc(dbPath);
    LOG(INFO) << "Created a test database called: " << dbPath << std::endl;

    success = lc.put(key1, value1, false);
    EXPECT_EQ(success, true);

    success = lc.put(key2, value2, false);
    EXPECT_EQ(success, true);

    success = lc.readBarrier();
    EXPECT_EQ(success, true);

    success = lc.get(key1, &value);
    EXPECT_EQ(success, true);

    LOG(INFO) << "Test value for key1: " << value << std::endl;
    EXPECT_EQ(value, value1);

    success = lc.get(key2, &value);
    EXPECT_EQ(success, true);

    LOG(INFO) << "Test value for key2: " << value << std::endl;
    EXPECT_EQ(value, value2);

    success = lc.del(key1);
    EXPECT_EQ(success, true);

    success = lc.del(key2);
    EXPECT_EQ(success, true);

    success = lc.writeBarrier();
    EXPECT_EQ(success, true);
}

// putBytes hands the caller's bytes to LevelDB, which copies them: the caller's buffer can change
// right after, with or without flush (LevelDB batches small values put without flush)
TEST(lsmioLevelDB, PutBytesCopiesCallerBytes) {
    std::string dbName = "test-ldb-store-putbytes.db";
    std::string dbPath = TEST_DIR_LDB.empty() ? dbName : TEST_DIR_LDB + "/" + dbName;
    std::filesystem::remove_all(dbPath);

    auto expected = [](int i) {
        std::string v(i % 2 ? 100 : 4096, static_cast<char>('a' + i % 26));
        v[v.size() / 2] = '\0';  // binary-safe
        return v;
    };
    {
        lsmio::LSMIOStoreLDB lc(dbPath);
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

int main(int argc, char** argv) {
    lsmio::initLSMIODebug(argv[0]);
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
