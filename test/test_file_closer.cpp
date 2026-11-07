#include <gtest/gtest.h>

#include <filesystem>
#include <fstream>
#include <iterator>
#include <lsmio/manager/store/native/FileCloser.hpp>
#include <memory>
#include <string>
#include <thread>

class FileCloserTest : public ::testing::Test {
  protected:
    std::string test_dir;
    void SetUp() override {
        const ::testing::TestInfo* const test_info =
            ::testing::UnitTest::GetInstance()->current_test_info();
        test_dir =
            (std::filesystem::current_path() / (std::string("test_closer_") + test_info->name()))
                .string();

        if (std::filesystem::exists(test_dir)) std::filesystem::remove_all(test_dir);
        std::filesystem::create_directory(test_dir);
    }
    void TearDown() override {
        if (std::filesystem::exists(test_dir)) std::filesystem::remove_all(test_dir);
    }
};

// Whole file content. An std::ofstream keeps small writes in its buffer until it is flushed, which
// close() does and so does the destructor. Finding the text on disk shows the stream was flushed,
// not which of the two did it; tests that must show the closer called close() use RecordingStream.
static std::string readAll(const std::string& f_path) {
    std::ifstream in(f_path);
    return std::string(std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>());
}

TEST_F(FileCloserTest, BatchClose) {
    lsmio::FileCloser closer(2);

    std::string p1 = test_dir + "/f1.txt";
    auto f1 = std::make_unique<std::ofstream>(p1);

    std::string p2 = test_dir + "/f2.txt";
    auto f2 = std::make_unique<std::ofstream>(p2);

    closer.scheduleClose(std::move(f1));
    closer.scheduleClose(std::move(f2));  // Should trigger close

    std::this_thread::sleep_for(std::chrono::milliseconds(200));

    EXPECT_TRUE(std::filesystem::exists(p1));
    EXPECT_TRUE(std::filesystem::exists(p2));
}

TEST_F(FileCloserTest, ZeroBatchSizeNoWorker) {
    lsmio::FileCloser closer(0);

    std::string p1 = test_dir + "/f1_zero.txt";
    auto f1 = std::make_unique<std::ofstream>(p1);
    *f1 << "test_content";

    closer.scheduleClose(std::move(f1));

    EXPECT_TRUE(std::filesystem::exists(p1));
}

TEST_F(FileCloserTest, ZeroBatchSizeClosesFile) {
    lsmio::FileCloser closer(0);

    std::string p1 = test_dir + "/f1_zero_batch.txt";
    auto f1 = std::make_unique<std::ofstream>(p1);
    *f1 << "test_data";

    closer.scheduleClose(std::move(f1));
    std::this_thread::sleep_for(std::chrono::milliseconds(100));

    EXPECT_TRUE(std::filesystem::exists(p1));
    std::ifstream in(p1);
    std::string content;
    in >> content;
    EXPECT_EQ(content, "test_data");
}

TEST_F(FileCloserTest, ZeroBatchSizeIgnoresNullFile) {
    lsmio::FileCloser closer(0);
    const std::string p = test_dir + "/after_null.txt";

    EXPECT_NO_THROW(closer.scheduleClose(nullptr));

    auto f = std::make_unique<std::ofstream>(p);
    *f << "after_null";
    closer.scheduleClose(std::move(f));

    // Batch size 0 closes in the caller's thread, so the text is on disk at once.
    EXPECT_EQ(readAll(p), "after_null");
}

TEST_F(FileCloserTest, ZeroBatchSizeIgnoresClosedFile) {
    lsmio::FileCloser closer(0);
    const std::string p = test_dir + "/closed_zero.txt";

    auto f = std::make_unique<std::ofstream>(p);
    *f << "early";
    f->close();
    ASSERT_FALSE(f->is_open());

    auto never = std::make_unique<std::ofstream>();  // default-constructed, never opened

    EXPECT_NO_THROW(closer.scheduleClose(std::move(f)));
    EXPECT_NO_THROW(closer.scheduleClose(std::move(never)));

    // The caller closed the file first, so the closer leaves it alone.
    EXPECT_EQ(readAll(p), "early");
}

TEST_F(FileCloserTest, WorkerSkipsNullAndClosedFiles) {
    const std::string p_closed = test_dir + "/closed_worker.txt";
    const std::string p_open = test_dir + "/open_worker.txt";

    auto closed = std::make_unique<std::ofstream>(p_closed);
    *closed << "closed_before";
    closed->close();

    auto open = std::make_unique<std::ofstream>(p_open);
    *open << "payload";

    {
        lsmio::FileCloser closer(3);
        closer.scheduleClose(nullptr);
        closer.scheduleClose(std::move(closed));
        closer.scheduleClose(std::move(open));  // third call reaches the batch size
    }  // destructor joins the worker, which has closed the batch

    EXPECT_EQ(readAll(p_open), "payload");
    EXPECT_EQ(readAll(p_closed), "closed_before");
}

TEST_F(FileCloserTest, WorkerHandlesNullOnlyBatch) {
    const std::string p = test_dir + "/after_null_batch.txt";

    {
        lsmio::FileCloser closer(1);
        closer.scheduleClose(nullptr);

        auto f = std::make_unique<std::ofstream>(p);
        *f << "next_batch";
        closer.scheduleClose(std::move(f));
    }  // destructor joins the worker

    // A batch holding only a null does not stop the worker from closing later batches.
    EXPECT_EQ(readAll(p), "next_batch");
}

namespace {

// What a stream saw when it was destroyed. The records outlive the closer, so the test can read
// them after the closer's destructor has joined the worker.
struct CloseRecord {
    bool destroyed = false;
    bool open_at_destruction = true;
};

// An ofstream that notes whether it was still open when destroyed. Destroying an open ofstream
// flushes and closes it too, so disk content cannot tell whether FileCloser called close().
class RecordingStream : public std::ofstream {
  public:
    RecordingStream(const std::string& f_path, CloseRecord* f_record)
        : std::ofstream(f_path), m_record(f_record) {}
    ~RecordingStream() override {
        m_record->open_at_destruction = is_open();
        m_record->destroyed = true;
    }

  private:
    CloseRecord* m_record;
};

}  // namespace

// Shutdown must close the pending files itself. The stream's own destructor would also flush them,
// so the test checks that each stream was closed before it was destroyed.
TEST_F(FileCloserTest, DestructorDrainsBelowBatchSize) {
    const std::string p1 = test_dir + "/drain1.txt";
    const std::string p2 = test_dir + "/drain2.txt";
    CloseRecord r1;
    CloseRecord r2;

    {
        lsmio::FileCloser closer(5);

        auto f1 = std::make_unique<RecordingStream>(p1, &r1);
        *f1 << "one";
        auto f2 = std::make_unique<RecordingStream>(p2, &r2);
        *f2 << "two";

        // Two pending, below the batch size 5: only shutdown wakes the worker.
        closer.scheduleClose(std::move(f1));
        closer.scheduleClose(std::move(f2));
    }  // destructor drains the files below the batch size

    EXPECT_TRUE(r1.destroyed);
    EXPECT_FALSE(r1.open_at_destruction);
    EXPECT_TRUE(r2.destroyed);
    EXPECT_FALSE(r2.open_at_destruction);
    EXPECT_EQ(readAll(p1), "one");
    EXPECT_EQ(readAll(p2), "two");
}
