#include <gtest/gtest.h>

#include <fcntl.h>
#include <unistd.h>

#include <filesystem>
#include <lsmio/manager/store/native/file_closer.hpp>
#include <thread>

class FileCloserTest : public ::testing::Test {
  protected:
    std::string test_dir = "test_closer_dir";
    void SetUp() override {
        if (std::filesystem::exists(test_dir)) std::filesystem::remove_all(test_dir);
        std::filesystem::create_directory(test_dir);
    }
    void TearDown() override {
        if (std::filesystem::exists(test_dir)) std::filesystem::remove_all(test_dir);
    }
};

TEST_F(FileCloserTest, BatchClose) {
    lsmio::FileCloser closer(2);

    std::string p1 = test_dir + "/f1.txt";
    int f1 = ::open(p1.c_str(), O_WRONLY | O_CREAT, 0644);
    ASSERT_GE(f1, 0);

    std::string p2 = test_dir + "/f2.txt";
    int f2 = ::open(p2.c_str(), O_WRONLY | O_CREAT, 0644);
    ASSERT_GE(f2, 0);

    closer.scheduleClose(f1);
    closer.scheduleClose(f2);  // Should trigger close

    std::this_thread::sleep_for(std::chrono::milliseconds(200));

    EXPECT_TRUE(std::filesystem::exists(p1));
    EXPECT_TRUE(std::filesystem::exists(p2));
}
