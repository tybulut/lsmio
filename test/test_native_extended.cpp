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
#include <lsmio/manager/store/native/StoreNative.hpp>

using namespace lsmio;

class NativeStoreExtendedTest : public ::testing::Test {
  protected:
    LSMIOConfig m_backup_config;

    // TearDown runs even when a test body exits early via FAIL(), so config
    // mutations can never leak into later tests.
    void SetUp() override {
        m_backup_config = gConfigLSMIO;
    }

    void TearDown() override {
        gConfigLSMIO = m_backup_config;
    }

    void CleanDir(const std::string& path) {
        std::error_code ec;
        if (std::filesystem::exists(path, ec)) {
            std::filesystem::remove_all(path, ec);
        }
    }
};

TEST_F(NativeStoreExtendedTest, PrefixScan) {
    std::string dbPath = "test_native_prefix";
    CleanDir(dbPath);
    {
        LSMIOStoreNative store(dbPath, true);

        store.put("prefix/1", "val1");
        store.put("prefix/2", "val2");
        store.put("other/3", "val3");
        store.put("prefix/4", "val4");
        store.del("prefix/2");

        std::vector<std::tuple<std::string, std::string>> results;
        EXPECT_TRUE(store.getPrefix("prefix/", &results));
        EXPECT_EQ(results.size(), 2);
    }
    CleanDir(dbPath);
}

TEST_F(NativeStoreExtendedTest, DoubleClose) {
    std::string dbPath = "test_native_doubleclose";
    CleanDir(dbPath);
    {
        LSMIOStoreNative store(dbPath, true);
        store.put("k", "v");
        store.close();
        store.close();
    }
    CleanDir(dbPath);
}

TEST_F(NativeStoreExtendedTest, DBCleanup) {
    std::string dbPath = "test_native_cleanup";
    CleanDir(dbPath);
    {
        LSMIOStoreNative store(dbPath, true);
        store.put("k", "v");
        // We can't call dbCleanup directly as it is protected.
        // But we can test if directory exists
        EXPECT_TRUE(std::filesystem::exists(dbPath));
    }
    CleanDir(dbPath);
}

TEST_F(NativeStoreExtendedTest, PersistenceAndRecovery) {
    std::string dbPath = "test_native_persistence";
    CleanDir(dbPath);
    {
        {
            LSMIOStoreNative store(dbPath, true);
            for (int i = 0; i < 100; ++i) {
                store.put("key" + std::to_string(i), "value" + std::to_string(i));
            }
            store.writeBarrier();
            store.close();
        }

        LSMIOStoreNative store(dbPath, false);
        std::string val;
        for (int i = 0; i < 100; ++i) {
            EXPECT_TRUE(store.get("key" + std::to_string(i), &val)) << "Key " << i << " not found";
            EXPECT_EQ(val, "value" + std::to_string(i));
        }
    }
    CleanDir(dbPath);
}

TEST_F(NativeStoreExtendedTest, LargeWriteFlush) {
    std::string dbPath = "test_native_large";
    CleanDir(dbPath);

    // Config is restored by the fixture's TearDown, even if the test fails.
    gConfigLSMIO.writeBufferSize = 2 * 1024 * 1024;
    gConfigLSMIO.maxKeyLen = 256;
    gConfigLSMIO.filePoolSize = 1;  // Force immediate close in FileCloser

    try {
        LSMIOStoreNative store(dbPath, true);
        std::string large_val(512 * 1024, 'a');

        for (int i = 0; i < 10; ++i) {
            store.put("key" + std::to_string(i), large_val);
        }
        EXPECT_TRUE(store.writeBarrier());

        std::string val;
        for (int i = 0; i < 10; ++i) {
            EXPECT_TRUE(store.get("key" + std::to_string(i), &val)) << "Key " << i << " not found";
            EXPECT_EQ(val, large_val);
        }
    } catch (const std::exception& e) {
        std::cerr << "EXCEPTION: " << e.what() << std::endl;
        FAIL() << "Exception thrown";
    }

    CleanDir(dbPath);
}

TEST_F(NativeStoreExtendedTest, AutoTuneLustre) {
    std::string dbPath = "test_native_autotune_lustre";
    CleanDir(dbPath);

    // Explicitly set baseline parameters before tuning
    gConfigLSMIO.autoTuneParameters = true;
    gConfigLSMIO.footerIndex = false;
    gConfigLSMIO.manualOffset = false;
    gConfigLSMIO.writeBufferNumber = 4;
    gConfigLSMIO.filePoolSize = 4;

    try {
        LSMIOStoreNative store(dbPath, true);
        store.autoTuneParameters(LUSTRE_SUPER_MAGIC);

        EXPECT_TRUE(gConfigLSMIO.footerIndex);
        EXPECT_TRUE(gConfigLSMIO.manualOffset);
        EXPECT_EQ(gConfigLSMIO.filePoolSize, 2 * gConfigLSMIO.writeBufferNumber);
        EXPECT_EQ(gConfigLSMIO.filePoolSize, 8);
    } catch (const std::exception& e) {
        FAIL() << "Exception during AutoTuneLustre: " << e.what();
    }

    CleanDir(dbPath);
}

TEST_F(NativeStoreExtendedTest, AutoTuneGPFS) {
    std::string dbPath = "test_native_autotune_gpfs";
    CleanDir(dbPath);

    gConfigLSMIO.autoTuneParameters = true;
    gConfigLSMIO.footerIndex = false;
    gConfigLSMIO.manualOffset = false;
    gConfigLSMIO.writeBufferNumber = 6;
    gConfigLSMIO.filePoolSize = 4;

    try {
        LSMIOStoreNative store(dbPath, true);
        store.autoTuneParameters(GPFS_SUPER_MAGIC);

        EXPECT_TRUE(gConfigLSMIO.footerIndex);
        EXPECT_TRUE(gConfigLSMIO.manualOffset);
        EXPECT_EQ(gConfigLSMIO.filePoolSize, 2 * gConfigLSMIO.writeBufferNumber);
        EXPECT_EQ(gConfigLSMIO.filePoolSize, 12);
    } catch (const std::exception& e) {
        FAIL() << "Exception during AutoTuneGPFS: " << e.what();
    }

    CleanDir(dbPath);
}

TEST_F(NativeStoreExtendedTest, AutoTuneLocalFsNoMutation) {
    std::string dbPath = "test_native_autotune_local";
    CleanDir(dbPath);

    gConfigLSMIO.autoTuneParameters = true;
    gConfigLSMIO.footerIndex = false;
    gConfigLSMIO.manualOffset = false;
    gConfigLSMIO.writeBufferNumber = 4;
    gConfigLSMIO.filePoolSize = 4;

    try {
        LSMIOStoreNative store(dbPath, true);
        // 0xEF53 is EXT4_SUPER_MAGIC
        store.autoTuneParameters(0xEF53);

        EXPECT_FALSE(gConfigLSMIO.footerIndex);
        EXPECT_FALSE(gConfigLSMIO.manualOffset);
        EXPECT_EQ(gConfigLSMIO.filePoolSize, 4);
    } catch (const std::exception& e) {
        FAIL() << "Exception during AutoTuneLocalFsNoMutation: " << e.what();
    }

    CleanDir(dbPath);
}

TEST_F(NativeStoreExtendedTest, AutoTuneDisabledBypass) {
    std::string dbPath = "test_native_autotune_disabled";
    CleanDir(dbPath);

    gConfigLSMIO.autoTuneParameters = false;
    gConfigLSMIO.footerIndex = false;
    gConfigLSMIO.manualOffset = false;
    gConfigLSMIO.writeBufferNumber = 4;
    gConfigLSMIO.filePoolSize = 4;

    try {
        LSMIOStoreNative store(dbPath, true);
        store.autoTuneParameters(LUSTRE_SUPER_MAGIC);

        EXPECT_FALSE(gConfigLSMIO.footerIndex);
        EXPECT_FALSE(gConfigLSMIO.manualOffset);
        EXPECT_EQ(gConfigLSMIO.filePoolSize, 4);
    } catch (const std::exception& e) {
        FAIL() << "Exception during AutoTuneDisabledBypass: " << e.what();
    }

    CleanDir(dbPath);
}
