#include <gtest/gtest.h>
#include <lsmio/manager/store/file_pool.hpp>
#include <filesystem>
#include <fstream>
#include <thread>

class FilePoolTest : public ::testing::Test {
protected:
    std::string test_dir;

    void SetUp() override {
        const ::testing::TestInfo* const test_info =
            ::testing::UnitTest::GetInstance()->current_test_info();
        test_dir = (std::filesystem::current_path() / (std::string("test_pool_") + test_info->name())).string();

        if (std::filesystem::exists(test_dir)) {
            std::filesystem::remove_all(test_dir);
        }
        std::filesystem::create_directory(test_dir);
    }

    void TearDown() override {
        if (std::filesystem::exists(test_dir)) {
            std::filesystem::remove_all(test_dir);
        }
    }
};

TEST_F(FilePoolTest, BasicAcquire) {
    lsmio::FilePool pool(test_dir, "L0-", ".sst", 5, 1);
    
    // Give it a moment to replenish
    std::this_thread::sleep_for(std::chrono::milliseconds(200));

    auto file1 = pool.acquire();
    EXPECT_TRUE(file1.second->is_open());
    // Check suffix
    std::string suffix1 = "L0-000001.sst";
    EXPECT_EQ(file1.first.compare(file1.first.length() - suffix1.length(), suffix1.length(), suffix1), 0);
    file1.second->close();

    auto file2 = pool.acquire();
    EXPECT_TRUE(file2.second->is_open());
    std::string suffix2 = "L0-000002.sst";
    EXPECT_EQ(file2.first.compare(file2.first.length() - suffix2.length(), suffix2.length(), suffix2), 0);
    file2.second->close();
}

TEST_F(FilePoolTest, PoolReplenish) {
    lsmio::FilePool pool(test_dir, "L0-", ".sst", 2, 10);
    
    // Acquire 3 files (more than pool size)
    auto f1 = pool.acquire();
    auto f2 = pool.acquire();
    auto f3 = pool.acquire(); // Should wait for replenish
    
    EXPECT_TRUE(f1.second->is_open());
    EXPECT_TRUE(f2.second->is_open());
    EXPECT_TRUE(f3.second->is_open());
}

TEST_F(FilePoolTest, PreAllocation) {
    size_t size = 1024 * 1024; // 1MB
    lsmio::FilePool pool(test_dir, "L0-", ".sst", 2, 20, size);
    
    // Wait for replenish
    std::this_thread::sleep_for(std::chrono::milliseconds(200));

    auto f1 = pool.acquire();
    f1.second->close();
    
    auto fsize = std::filesystem::file_size(f1.first);
    EXPECT_EQ(fsize, size);
}
