#include <gtest/gtest.h>

#include <filesystem>
#include <fstream>
#include <lsmio/manager/store/native/FilePool.hpp>
#include <thread>

class FilePoolTest : public ::testing::Test {
  protected:
    std::string test_dir;

    void SetUp() override {
        const ::testing::TestInfo* const test_info =
            ::testing::UnitTest::GetInstance()->current_test_info();
        test_dir =
            (std::filesystem::current_path() / (std::string("test_pool_") + test_info->name()))
                .string();

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
    EXPECT_EQ(
        file1.first.compare(file1.first.length() - suffix1.length(), suffix1.length(), suffix1), 0);
    file1.second->close();

    auto file2 = pool.acquire();
    EXPECT_TRUE(file2.second->is_open());
    std::string suffix2 = "L0-000002.sst";
    EXPECT_EQ(
        file2.first.compare(file2.first.length() - suffix2.length(), suffix2.length(), suffix2), 0);
    file2.second->close();
}

TEST_F(FilePoolTest, PoolReplenish) {
    lsmio::FilePool pool(test_dir, "L0-", ".sst", 2, 10);

    // Acquire 3 files (more than pool size)
    auto f1 = pool.acquire();
    auto f2 = pool.acquire();
    auto f3 = pool.acquire();  // Should wait for replenish

    EXPECT_TRUE(f1.second->is_open());
    EXPECT_TRUE(f2.second->is_open());
    EXPECT_TRUE(f3.second->is_open());
}

TEST_F(FilePoolTest, PreAllocation) {
    size_t size = 1024 * 1024;  // 1MB
    lsmio::FilePool pool(test_dir, "L0-", ".sst", 2, 20, size);

    // Wait for replenish
    std::this_thread::sleep_for(std::chrono::milliseconds(200));

    auto f1 = pool.acquire();
    f1.second->close();

    auto fsize = std::filesystem::file_size(f1.first);
    EXPECT_EQ(fsize, size);
}

TEST_F(FilePoolTest, ZeroPoolSizeOnDemand) {
    size_t size = 1024 * 1024;  // 1MB
    lsmio::FilePool pool(test_dir, "L0-", ".sst", 0, 100, size);

    // No worker thread was spawned; zero files should exist initially
    size_t file_count = 0;
    for (const auto& entry : std::filesystem::directory_iterator(test_dir)) {
        if (entry.path().extension() == ".sst") {
            file_count++;
        }
    }
    EXPECT_EQ(file_count, 0);

    // acquire() must create file synchronously on-demand
    auto f = pool.acquire();
    ASSERT_TRUE(f.second != nullptr);
    EXPECT_TRUE(f.second->is_open());
    f.second->close();

    EXPECT_TRUE(std::filesystem::exists(f.first));
    EXPECT_EQ(std::filesystem::file_size(f.first), size);
}

TEST_F(FilePoolTest, GracefulShutdownDrain) {
    auto pool = std::make_unique<lsmio::FilePool>(test_dir, "L0-", ".sst", 2, 200, 0);
    // Acquire files until empty
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    auto f1 = pool->acquire();
    auto f2 = pool->acquire();

    // Call shutdown explicitly and verify acquire() on empty shutdown pool returns {"", nullptr}
    pool->shutdown();
    auto f3 = pool->acquire();
    EXPECT_EQ(f3.first, "");
    EXPECT_EQ(f3.second, nullptr);

    // Reset pool while empty (invoking destructor with shutdown flag)
    pool.reset();

    // Acquire on empty shutdown pool with pool_size = 0 must return {"", nullptr} without throwing
    lsmio::FilePool empty_pool(test_dir, "L0-", ".sst", 0, 300, 0);
    empty_pool.shutdown();
    auto f4 = empty_pool.acquire();
    EXPECT_EQ(f4.first, "");
    EXPECT_EQ(f4.second, nullptr);
}

TEST_F(FilePoolTest, RapidAcquiresNeverDropUnderStarvation) {
    size_t size = 64 * 1024;
    lsmio::FilePool pool(test_dir, "L0-", ".sst", 1, 500, size);

    // Rapid consecutive acquires must never return nullptr even when pool is drained
    std::vector<std::pair<std::string, std::unique_ptr<std::ofstream>>> files;
    std::set<std::string> unique_paths;

    for (int i = 0; i < 10; ++i) {
        auto f = pool.acquire();
        ASSERT_NE(f.second, nullptr) << "acquire() returned null stream on iteration " << i;
        EXPECT_TRUE(f.second->is_open());
        EXPECT_TRUE(std::filesystem::exists(f.first));
        unique_paths.insert(f.first);
        files.push_back(std::move(f));
    }

    EXPECT_EQ(files.size(), 10);
    EXPECT_EQ(unique_paths.size(), 10);

    for (auto& f : files) {
        f.second->close();
        EXPECT_EQ(std::filesystem::file_size(f.first), size);
    }
}

TEST_F(FilePoolTest, ConcurrentAcquiresNoDataLoss) {
    size_t size = 64 * 1024;
    lsmio::FilePool pool(test_dir, "L0-", ".sst", 2, 600, size);

    const int num_threads = 8;
    const int acquires_per_thread = 5;
    std::vector<std::thread> threads;
    std::mutex paths_mutex;
    std::set<std::string> acquired_paths;
    std::atomic<bool> any_failed{false};

    for (int t = 0; t < num_threads; ++t) {
        threads.emplace_back([&]() {
            for (int i = 0; i < acquires_per_thread; ++i) {
                auto f = pool.acquire();
                if (!f.second || !f.second->is_open()) {
                    any_failed.store(true);
                    return;
                }
                f.second->close();
                std::lock_guard<std::mutex> guard(paths_mutex);
                acquired_paths.insert(f.first);
            }
        });
    }

    for (auto& th : threads) {
        th.join();
    }

    EXPECT_FALSE(any_failed.load());
    EXPECT_EQ(acquired_paths.size(), num_threads * acquires_per_thread);
}

TEST_F(FilePoolTest, NonExistentDirectoryFailureClean) {
    std::string bad_dir = test_dir + "/non_existent_subdir/nested";
    lsmio::FilePool pool(bad_dir, "L0-", ".sst", 0, 400, 1024 * 1024);
    auto f = pool.acquire();
    EXPECT_EQ(f.first, "");
    EXPECT_EQ(f.second, nullptr);
}
