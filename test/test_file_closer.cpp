#include <gtest/gtest.h>
#include <lsmio/manager/store/native/file_closer.hpp>
#include <fstream>
#include <thread>
#include <filesystem>

class FileCloserTest : public ::testing::Test {
protected:
    std::string test_dir = "test_closer_dir";
    void SetUp() override { 
         if(std::filesystem::exists(test_dir)) std::filesystem::remove_all(test_dir);
         std::filesystem::create_directory(test_dir); 
    }
    void TearDown() override { 
         if(std::filesystem::exists(test_dir)) std::filesystem::remove_all(test_dir); 
    }
};

TEST_F(FileCloserTest, BatchClose) {
    lsmio::FileCloser closer(2);
    
    std::string p1 = test_dir + "/f1.txt";
    auto f1 = std::make_unique<std::ofstream>(p1);
    
    std::string p2 = test_dir + "/f2.txt";
    auto f2 = std::make_unique<std::ofstream>(p2);
    
    closer.scheduleClose(std::move(f1));
    closer.scheduleClose(std::move(f2)); // Should trigger close

    std::this_thread::sleep_for(std::chrono::milliseconds(200));
    
    EXPECT_TRUE(std::filesystem::exists(p1));
    EXPECT_TRUE(std::filesystem::exists(p2));
}
