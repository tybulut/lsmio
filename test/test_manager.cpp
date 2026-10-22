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
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <lsmio/manager/manager.hpp>
#include <string_view>
#include <thread>
#include <vector>

const std::string TEST_DIR_MGR = "";

TEST(lsmioManager, Flush) {
    bool success = true;
    std::string value;

    std::string key1 = "serdar";
    std::string key2 = "leo";
    std::string value1 = "bulut";
    std::string value2 = "alp";

    std::string dbName = "test-mgr-store-flush.db";
    std::string dbPath = TEST_DIR_MGR.empty() ? dbName : TEST_DIR_MGR + "/" + dbName;
    std::filesystem::remove_all(dbPath);

    {
        lsmio::LSMIOManager lm(dbName, TEST_DIR_MGR);
        LOG(INFO) << "Created a test database called: " << lm.getDbPath() << std::endl;

        EXPECT_EQ(lm.getDbPath(), dbPath);

        success = lm.put(key1, value1, true);
        EXPECT_EQ(success, true);

        success = lm.get(key1, &value);
        EXPECT_EQ(success, true);

        LOG(INFO) << "Test value for key1: wrote: " << value1 << std::endl;
        LOG(INFO) << "Test value for key1: read: " << value << std::endl;
        EXPECT_EQ(value, value1);

        success = lm.put(key2, value2, true);
        EXPECT_EQ(success, true);

        success = lm.get(key2, &value);
        EXPECT_EQ(success, true);

        LOG(INFO) << "Test value for key2: wrote: " << value2 << std::endl;
        LOG(INFO) << "Test value for key2: read: " << value << std::endl;
        EXPECT_EQ(value, value2);

        uint64_t rb, wb;
        uint64_t ro, wo;
        lm.getCounters(wb, rb, wo, ro);

        LOG(INFO) << "LSMIOManager::counters: writeB: " << wb << " readB: " << rb << std::endl;
        EXPECT_EQ(rb, (value1.length() + value2.length()));
        EXPECT_EQ(wb, (value1.length() + value2.length()));

        LOG(INFO) << "LSMIOManager::counters: writeO: " << wo << " readO: " << ro << std::endl;
        EXPECT_EQ(ro, 2);
        EXPECT_EQ(wo, 2);

        success = lm.del(key1, false);
        EXPECT_EQ(success, true);

        success = lm.del(key2, false);
        EXPECT_EQ(success, true);
    }

    std::filesystem::remove_all(dbPath);
}

TEST(lsmioManager, Deferred) {
    bool success = true;
    std::string value;

    std::string key1 = "serdar";
    std::string key2 = "bulut";
    std::string value1 = "alpino";
    std::string value2 = "teomos";

    std::string dbName = "test-mgr-store-deferred.db";
    std::string dbPath = TEST_DIR_MGR.empty() ? dbName : TEST_DIR_MGR + "/" + dbName;
    std::filesystem::remove_all(dbPath);

    {
        lsmio::LSMIOManager lm(dbName, TEST_DIR_MGR);
        LOG(INFO) << "Created a test database called: " << lm.getDbPath() << std::endl;
        EXPECT_EQ(lm.getDbPath(), dbPath);

        success = lm.put(key1, value1);
        EXPECT_EQ(success, true);

        success = lm.put(key2, value2.c_str(), value2.length());
        EXPECT_EQ(success, true);

        success = lm.writeBarrier();
        EXPECT_EQ(success, true);

        success = lm.get(key1, &value);
        EXPECT_EQ(success, true);

        LOG(INFO) << "Test value for key1: " << value << std::endl;
        EXPECT_EQ(value, value1);

        success = lm.get(key2, &value);
        EXPECT_EQ(success, true);

        LOG(INFO) << "Test value for key2: " << value << std::endl;
        EXPECT_EQ(value, value2);

        success = lm.del(key1);
        EXPECT_EQ(success, true);

        success = lm.del(key2);
        EXPECT_EQ(success, true);
    }

    std::filesystem::remove_all(dbPath);
}

// The raw-pointer puts and putBytes copy the caller's bytes before they return: the buffers are
// overwritten or freed right after, and the counters count each put once
TEST(lsmioManager, RawPutsCopyCallerBytes) {
    std::string dbName = "test-mgr-store-raw.db";
    std::string dbPath = TEST_DIR_MGR.empty() ? dbName : TEST_DIR_MGR + "/" + dbName;
    std::filesystem::remove_all(dbPath);

    auto expected = [](int i) {
        std::string v(1000 + i, static_cast<char>('a' + i));
        v[10] = '\0';  // binary-safe
        return v;
    };
    {
        lsmio::LSMIOManager lm(dbName, TEST_DIR_MGR);
        lm.resetCounters();
        uint64_t bytes = 0;
        for (int i = 0; i < 12; ++i) {
            const std::string key = "raw" + std::to_string(i);
            const std::string e = expected(i);
            char *buf = new char[e.size()];
            std::memcpy(buf, e.data(), e.size());
            switch (i % 3) {
                case 0:
                    EXPECT_TRUE(lm.put(key, buf, static_cast<std::streamsize>(e.size())));
                    break;
                case 1:
                    EXPECT_TRUE(lm.put(key, static_cast<const void *>(buf), 1, e.size()));
                    break;
                default:
                    EXPECT_TRUE(lm.putBytes(key, std::string_view(buf, e.size()), i % 2 == 0));
                    break;
            }
            std::memset(buf, 'X', e.size());
            delete[] buf;
            bytes += e.size();
        }
        std::string value;
        for (int i = 0; i < 12; ++i) {
            EXPECT_TRUE(lm.get("raw" + std::to_string(i), &value));
            EXPECT_EQ(value, expected(i)) << "key " << i;
        }
        uint64_t rb, wb, ro, wo;
        lm.getCounters(wb, rb, wo, ro);
        EXPECT_EQ(wb, bytes);
        EXPECT_EQ(wo, 12u);
    }
    std::filesystem::remove_all(dbPath);
}

TEST(lsmioManager, ReOpen_Write) {
    bool success = true;
    std::string value;

    std::string key1 = "serdar";
    std::string key2 = "bulut";
    std::string value1 = "alpino";
    std::string value2 = "teomos";

    std::string dbName = "test-mgr-store-rewrite.db";
    std::string dbPath = TEST_DIR_MGR.empty() ? dbName : TEST_DIR_MGR + "/" + dbName;
    std::filesystem::remove_all(dbPath);

    for (int i = 0; i < 2; i++) {
        lsmio::LSMIOManager lm(dbName, TEST_DIR_MGR);
        LOG(INFO) << ((i == 0) ? "Created" : "Opened")
                  << " a RW test database called: " << lm.getDbPath() << std::endl;

        success = lm.put(key1, value1, true);
        EXPECT_EQ(success, true);

        success = lm.put(key2, value2, true);
        EXPECT_EQ(success, true);
    }

    std::filesystem::remove_all(dbPath);
}

TEST(lsmioManager, ReOpen_Read) {
    bool success = true;
    std::string value;

    std::string key1 = "serdar";
    std::string key2 = "bulut";
    std::string value1 = "alpino";
    std::string value2 = "teomos";

    std::string dbName = "test-mgr-store-reread.db";
    std::string dbPath = TEST_DIR_MGR.empty() ? dbName : TEST_DIR_MGR + "/" + dbName;
    std::filesystem::remove_all(dbPath);

    for (int i = 0; i < 2; i++) {
        lsmio::LSMIOManager lm(dbName, TEST_DIR_MGR);
        LOG(INFO) << ((i == 0) ? "Created" : "Opened")
                  << " a RW test database called: " << lm.getDbPath() << std::endl;

        if (i == 0) {
            success = lm.put(key1, value1, true);
            EXPECT_EQ(success, true);

            success = lm.put(key2, value2, true);
            EXPECT_EQ(success, true);
        } else {
            success = lm.get(key1, &value);
            LOG(INFO) << "ReOpen read test value for key1: " << value << std::endl;
            EXPECT_EQ(success, true);

            success = lm.get(key2, &value);
            LOG(INFO) << "ReOpen read test value for key2: " << value << std::endl;
            EXPECT_EQ(success, true);
        }
    }

    std::filesystem::remove_all(dbPath);
}

TEST(lsmioManager, CounterAccountingRvalueAndRawBuffers) {
    std::string dbName = "test-mgr-counters.db";
    std::string dbPath = TEST_DIR_MGR.empty() ? dbName : TEST_DIR_MGR + "/" + dbName;
    std::filesystem::remove_all(dbPath);
    {
        lsmio::LSMIOManager lm(dbName, TEST_DIR_MGR);
        lm.resetCounters();
        uint64_t wb = 0, rb = 0, wo = 0, ro = 0;

        // Rvalue put:
        lm.put("k1", std::string(100, 'x'), true);
        lm.getCounters(wb, rb, wo, ro);
        EXPECT_EQ(wb, 100);
        EXPECT_EQ(wo, 1);

        // Raw buffer char* put:
        const char buf[50] = {0};
        lm.put("k2", buf, 50);
        lm.getCounters(wb, rb, wo, ro);
        EXPECT_EQ(wb, 150);
        EXPECT_EQ(wo, 2);

        // Raw buffer void* put:
        int arr[10] = {0};
        lm.put("k3", arr, sizeof(int), 10);
        lm.getCounters(wb, rb, wo, ro);
        EXPECT_EQ(wb, 150 + sizeof(int) * 10);
        EXPECT_EQ(wo, 3);
    }
    std::filesystem::remove_all(dbPath);
}

// A failed initialize leaves no instance, so a later one can succeed; misuse is refused
TEST(lsmioManager, InitializeLifecycle) {
    std::string blocker = "test-mgr-init-blocker";
    std::ofstream(blocker) << "not a directory";
    std::string dbName = "test-mgr-init.db";
    std::filesystem::remove_all(dbName);

    // The database directory would go under a regular file
    EXPECT_THROW(lsmio::LSMIOManager::initialize(dbName, blocker),
                 std::filesystem::filesystem_error);
    std::filesystem::remove(blocker);
    EXPECT_EQ(lsmio::LSMIOManager::getManager(), nullptr);
    EXPECT_FALSE(lsmio::LSMIOManager::cleanup());

    lsmio::LSMIOManager *lm = lsmio::LSMIOManager::initialize(dbName, TEST_DIR_MGR, true);
    ASSERT_NE(lm, nullptr);
    EXPECT_EQ(lsmio::LSMIOManager::initialize(dbName, TEST_DIR_MGR, true), nullptr);
    EXPECT_EQ(lsmio::LSMIOManager::getManager(), lm);

    EXPECT_TRUE(lsmio::LSMIOManager::cleanup());
    EXPECT_EQ(lsmio::LSMIOManager::getManager(), nullptr);
    EXPECT_FALSE(lsmio::LSMIOManager::cleanup());
    std::filesystem::remove_all(dbName);
}

// Threads that initialize at once: exactly one opens the database
TEST(lsmioManager, ConcurrentInitialize) {
    std::string dbName = "test-mgr-init-race.db";
    std::atomic<bool> go{false};
    std::atomic<int> opened{0};
    std::vector<std::thread> threads;

    for (int i = 0; i < 8; i++) {
        threads.emplace_back([&] {
            while (!go) std::this_thread::yield();
            if (lsmio::LSMIOManager::initialize(dbName, TEST_DIR_MGR, true)) opened++;
        });
    }
    go = true;
    for (auto &thread : threads) thread.join();

    EXPECT_EQ(opened, 1);
    EXPECT_TRUE(lsmio::LSMIOManager::cleanup());
    std::filesystem::remove_all(dbName);
}

int main(int argc, char **argv) {
    lsmio::initLSMIODebug(argv[0]);
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
