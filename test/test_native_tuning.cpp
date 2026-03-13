#include <gtest/gtest.h>
#include <sys/vfs.h>

#include <filesystem>
#include <lsmio/lsmio.hpp>
#include <lsmio/manager/store/native/store_native.hpp>

#ifndef LUSTRE_SUPER_MAGIC
#define LUSTRE_SUPER_MAGIC 0x0BD00BD0
#endif

#ifndef GPFS_SUPER_MAGIC
#define GPFS_SUPER_MAGIC 0x47504653
#endif

namespace lsmio {

class NativeTuningTest : public ::testing::Test {
  protected:
    std::string test_dir;
    void SetUp() override {
        test_dir = "test_db_tuning_" + std::to_string(getpid()) + "_" + 
                   std::to_string(std::chrono::steady_clock::now().time_since_epoch().count());
        std::filesystem::create_directories(test_dir);
    }

    void TearDown() override {
        std::filesystem::remove_all(test_dir);
    }
};

TEST_F(NativeTuningTest, LocalFSAlignment) {
    gConfigLSMIO.writeBufferSize = 32 * 1024 * 1024;  // 32MB
    gConfigLSMIO.writeBufferNumber = 4;
    gConfigLSMIO.blockSize = 1024 * 1024;  // 1MB

    LSMIOStoreNative store(test_dir, true);

    // For local FS, it should align but not necessarily change the budget logic
    EXPECT_EQ(store.getFlushBufferCapacity(), 32 * 1024 * 1024);
    EXPECT_EQ(store.getMemtableMaxSize(), 32 * 1024 * 1024);
    EXPECT_EQ(store.getMaxImmutableMemtables(), 4);
    EXPECT_EQ(store.getFlushThreadCount(), 1);
}

TEST_F(NativeTuningTest, LustreAdaptiveTuning) {
    // Start with 16MB buffers, 8 of them (Total 128MB budget)
    gConfigLSMIO.writeBufferSize = 16 * 1024 * 1024;
    gConfigLSMIO.writeBufferNumber = 8;
    // Set a large block size (e.g. 32MB) to force tuning
    gConfigLSMIO.blockSize = 32 * 1024 * 1024;

    LSMIOStoreNative store(test_dir, true);

    // Explicitly call tuneParameters with Lustre magic
    store.tuneParameters(LUSTRE_SUPER_MAGIC, 1);

    // Expect:
    // 1. Buffer size increased to 32MB (to match blockSize)
    // 2. Buffer count decreased to 4 (to keep 128MB budget: 16*8 = 32*4)
    // 3. Thread count matches max buffers (4)
    EXPECT_EQ(store.getMemtableMaxSize(), 32 * 1024 * 1024);
    EXPECT_EQ(store.getFlushBufferCapacity(), 32 * 1024 * 1024);
    EXPECT_EQ(store.getMaxImmutableMemtables(), 4);
    EXPECT_EQ(store.getFlushThreadCount(), 4);

    // Verify total budget remains constant (128MB)
    EXPECT_EQ(store.getMemtableMaxSize() * store.getMaxImmutableMemtables(), 128 * 1024 * 1024);
}

TEST_F(NativeTuningTest, GPFSAdaptiveTuning) {
    // Start with 10MB buffers, 10 of them (Total 100MB budget)
    gConfigLSMIO.writeBufferSize = 10 * 1024 * 1024;
    gConfigLSMIO.writeBufferNumber = 10;
    // Set 16MB block size
    gConfigLSMIO.blockSize = 16 * 1024 * 1024;

    LSMIOStoreNative store(test_dir, true);

    // Explicitly call tuneParameters with GPFS magic
    store.tuneParameters(GPFS_SUPER_MAGIC, 1);

    // Expect:
    // 1. Buffer size increased to 16MB (to match blockSize)
    // 2. Buffer count decreased to 6 (100MB / 16MB = 6.25 -> 6)
    // 3. Thread count is limited by stripe count (4)
    EXPECT_EQ(store.getMemtableMaxSize(), 16 * 1024 * 1024);
    EXPECT_EQ(store.getMaxImmutableMemtables(), 6);
    EXPECT_EQ(store.getFlushThreadCount(), 4);

    // Verify budget is adhered to (should not exceed 100MB)
    EXPECT_LE(store.getMemtableMaxSize() * store.getMaxImmutableMemtables(), 100 * 1024 * 1024);
}

TEST_F(NativeTuningTest, LustreMultiProcessTuning) {
    // 4 processes, stripe count 4
    gConfigLSMIO.writeBufferSize = 16 * 1024 * 1024;
    gConfigLSMIO.writeBufferNumber = 8;
    gConfigLSMIO.blockSize = 32 * 1024 * 1024;

    LSMIOStoreNative store(test_dir, true);

    // Call with 4 parallel processes
    store.tuneParameters(LUSTRE_SUPER_MAGIC, 4);

    // Expect:
    // 1. Thread count = max(1, 4 / 4) = 1 thread per process
    EXPECT_EQ(store.getFlushThreadCount(), 1);
}

TEST_F(NativeTuningTest, HighProcessCountLustre) {
    // 100 processes, stripe count 4
    gConfigLSMIO.writeBufferSize = 32 * 1024 * 1024;
    gConfigLSMIO.writeBufferNumber = 4;
    gConfigLSMIO.blockSize = 1024 * 1024;

    LSMIOStoreNative store(test_dir, true);

    // 100 processes sharing 4 OSTs
    store.tuneParameters(LUSTRE_SUPER_MAGIC, 100);

    // Should still use at least 1 thread
    EXPECT_GE(store.getFlushThreadCount(), 1);
    EXPECT_LE(store.getFlushThreadCount(), 1);
}

TEST_F(NativeTuningTest, SmallBudgetLargeStripe) {
    // Total budget 16MB (8MB * 2)
    gConfigLSMIO.writeBufferSize = 8 * 1024 * 1024;
    gConfigLSMIO.writeBufferNumber = 2;
    // FS requires 32MB blocks
    gConfigLSMIO.blockSize = 32 * 1024 * 1024;

    LSMIOStoreNative store(test_dir, true);
    store.tuneParameters(LUSTRE_SUPER_MAGIC, 1);

    // Should increase size to 32MB and reduce count to 1 (minimum)
    EXPECT_EQ(store.getMemtableMaxSize(), 32 * 1024 * 1024);
    EXPECT_EQ(store.getMaxImmutableMemtables(), 1);
}

TEST_F(NativeTuningTest, ZeroBlockSize) {
    gConfigLSMIO.writeBufferSize = 32 * 1024 * 1024;
    gConfigLSMIO.writeBufferNumber = 4;
    gConfigLSMIO.blockSize = 0;  // Disabled alignment

    LSMIOStoreNative store(test_dir, true);
    store.tuneParameters(LUSTRE_SUPER_MAGIC, 1);

    // Should fall back to default logic but not crash
    EXPECT_EQ(store.getMemtableMaxSize(), 32 * 1024 * 1024);
    EXPECT_GE(store.getFlushThreadCount(), 1);
}

TEST_F(NativeTuningTest, MinimumBuffers) {
    // Only 1 buffer allowed
    gConfigLSMIO.writeBufferSize = 32 * 1024 * 1024;
    gConfigLSMIO.writeBufferNumber = 1;
    gConfigLSMIO.blockSize = 64 * 1024 * 1024;

    LSMIOStoreNative store(test_dir, true);
    store.tuneParameters(LUSTRE_SUPER_MAGIC, 1);

    // Budget would suggest 0.5 buffers, but must stay at 1
    EXPECT_EQ(store.getMaxImmutableMemtables(), 1);
    EXPECT_EQ(store.getMemtableMaxSize(), 64 * 1024 * 1024);
}

}  // namespace lsmio

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    google::InitGoogleLogging(argv[0]);
    FLAGS_logtostderr = true;
    return RUN_ALL_TESTS();
}
