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

#include <chrono>
#include <cmath>
#include <iostream>
#include <limits>
#include <lsmio/benchmark.hpp>
#include <lsmio/lsmio.hpp>
#include <stdexcept>
#include <string>
#include <thread>

namespace {

// Runs f_fn, which must throw std::invalid_argument with exactly the given message.
template <typename F>
void expectInvalidArgument(F &&f_fn, const std::string &f_expected) {
    try {
        f_fn();
        ADD_FAILURE() << "expected std::invalid_argument: " << f_expected;
    } catch (const std::invalid_argument &e) {
        EXPECT_EQ(std::string(e.what()), f_expected);
    }
}

}  // namespace

TEST(lsmioBenchmark, Duration) {
    lsmio::Benchmark bm;
    long long duration = 0.00;
    const int loopWaitMS = 10;

    bm.start();
    std::this_thread::sleep_for(std::chrono::milliseconds(loopWaitMS));
    bm.stop();
    duration = bm.duration();

    LOG(INFO) << "test_lsmioBenchmarkDuration:: duration: " << duration << std::endl;
    EXPECT_GT(duration, (loopWaitMS * 1000));
}

TEST(lsmioBenchmark, Format) {
    lsmio::Benchmark bm;
    std::string name = "test";
    double min, mean, max;
    double totalBytes, totalOps;
    int iterations;

    bm.addIteration(name, 10 * 1000, 20 * 1024 * 1024, 10);
    bm.addIteration(name, 10 * 1000, 40 * 1024 * 1024, 20);
    bm.addIteration(name, 10 * 1000, 60 * 1024 * 1024, 30);
    bm.addIteration(name, 10 * 1000, 80 * 1024 * 1024, 40);

    bm.summaryIteration(name, min, mean, max, iterations, totalBytes, totalOps);
    std::string output = bm.formatSummary(name);

    LOG(INFO) << "test_lsmioBenchmarkFormat:: "
              << " min: " << min << " max: " << max << " mean: " << mean
              << " totalBytes: " << totalBytes << " totalOps: " << totalOps
              << " iterations: " << iterations << std::endl;

    LOG(INFO) << "test_lsmioBenchmarkFormat:: [" << output << "]" << std::endl;
    EXPECT_EQ(output, "test,8000.00,2000.00,5000.00,200.00,100,4");
}

TEST(lsmioBenchmark, NegativeDurationRejection) {
    lsmio::Benchmark bm;
    std::string name = "test";

    bm.addIteration(name, -1, 1024, 1);
    EXPECT_EQ(bm.failedIterations(name), 1);
    EXPECT_EQ(bm.getFailedCount(name), 1);

    double min = 0.0, mean = 0.0, max = 0.0;
    double totalBytes = 0.0, totalOps = 0.0;
    int iterations = -1;
    bm.summaryIteration(name, min, mean, max, iterations, totalBytes, totalOps);
    EXPECT_EQ(iterations, 0);
    EXPECT_DOUBLE_EQ(totalBytes, 0.0);

    std::string summary = bm.formatSummary(name);
    EXPECT_EQ(summary, "test, FAILED");
}

TEST(lsmioBenchmark, ZeroDurationProtection) {
    lsmio::Benchmark bm;
    std::string name = "test";

    bm.addIteration(name, 0, 1024, 1);
    EXPECT_EQ(bm.failedIterations(name), 1);

    double min = -1.0, mean = -1.0, max = -1.0;
    double totalBytes = -1.0, totalOps = -1.0;
    int iterations = -1;
    bm.summaryIteration(name, min, mean, max, iterations, totalBytes, totalOps);
    EXPECT_EQ(iterations, 0);
    EXPECT_FALSE(std::isinf(min));
    EXPECT_FALSE(std::isnan(min));
    EXPECT_DOUBLE_EQ(min, 0.0);
    EXPECT_DOUBLE_EQ(mean, 0.0);
    EXPECT_DOUBLE_EQ(max, 0.0);
    EXPECT_DOUBLE_EQ(totalBytes, 0.0);
    EXPECT_DOUBLE_EQ(totalOps, 0.0);

    std::string summary = bm.formatSummary(name);
    EXPECT_EQ(summary, "test, FAILED");
}

TEST(lsmioBenchmark, MixedValidAndInvalidIterations) {
    lsmio::Benchmark bm;
    std::string name = "test";

    // 2 valid iterations: 10ms (10000us) with 20MiB and 40MiB
    bm.addIteration(name, 10 * 1000, 20 * 1024 * 1024, 10);
    bm.addIteration(name, 10 * 1000, 40 * 1024 * 1024, 20);

    // 2 invalid iterations: negative duration and negative bytes
    bm.addIteration(name, -5000, 20 * 1024 * 1024, 10);
    bm.addIteration(name, 10 * 1000, -1024, 10);

    EXPECT_EQ(bm.failedIterations(name), 2);

    double min, mean, max;
    double totalBytes, totalOps;
    int iterations;
    bm.summaryIteration(name, min, mean, max, iterations, totalBytes, totalOps);

    EXPECT_EQ(iterations, 2);
    EXPECT_DOUBLE_EQ(min, 2000.00);
    EXPECT_DOUBLE_EQ(max, 4000.00);
    EXPECT_DOUBLE_EQ(mean, 3000.00);
    EXPECT_DOUBLE_EQ(totalBytes, 60.0 * 1024 * 1024);
    EXPECT_DOUBLE_EQ(totalOps, 30.0);

    std::string summary = bm.formatSummary(name);
    EXPECT_EQ(summary, "test,4000.00,2000.00,3000.00,60.00,30,2");
}

TEST(lsmioBenchmark, FailedSummaryFormatting) {
    lsmio::Benchmark bm;
    // Verify formatSummary returns "sumName, FAILED" without trailing newline when zero valid
    // iterations exist
    std::string summary = bm.formatSummary("iwrite", "write");
    EXPECT_EQ(summary, "write, FAILED");

    // Add invalid iteration, formatSummary should still return "write, FAILED"
    bm.addIteration("iwrite", -100, 1024, 1);
    summary = bm.formatSummary("iwrite", "write");
    EXPECT_EQ(summary, "write, FAILED");

    // Without optSumName, it uses name
    summary = bm.formatSummary("iwrite");
    EXPECT_EQ(summary, "iwrite, FAILED");
}

TEST(lsmioBenchmark, NonNegativeBandwidthInvariant) {
    lsmio::Benchmark bm;
    std::string name = "test";

    // Valid iteration with 0 bytes
    bm.addIteration(name, 1000, 0, 0);

    double min, mean, max;
    double totalBytes, totalOps;
    int iterations;
    bm.summaryIteration(name, min, mean, max, iterations, totalBytes, totalOps);

    EXPECT_GE(min, 0.0);
    EXPECT_GE(mean, 0.0);
    EXPECT_GE(max, 0.0);

    std::string iters = bm.formatIterations(name);
    EXPECT_NE(iters.find("0.00"), std::string::npos);
}

TEST(lsmioBenchmark, ClearIterationsResetsFailures) {
    lsmio::Benchmark bm;
    std::string name = "test";

    bm.addIteration(name, -1000, 1024, 1);
    bm.addIteration(name, 1000, 1024, 1);
    EXPECT_EQ(bm.failedIterations(name), 1);
    EXPECT_EQ(bm.getFailedCount(name), 1);

    bm.clearIterations();
    EXPECT_EQ(bm.failedIterations(name), 0);
    EXPECT_EQ(bm.getFailedCount(name), 0);

    double min, mean, max;
    double totalBytes, totalOps;
    int iterations;
    bm.summaryIteration(name, min, mean, max, iterations, totalBytes, totalOps);
    EXPECT_EQ(iterations, 0);
}

TEST(lsmioBenchmark, StartTwiceThrows) {
    lsmio::Benchmark bm;
    bm.start();

    expectInvalidArgument([&] { bm.start(); },
                          "ERROR: lsmio::Benchmark::start: method ran but it is already started.");

    // The rejected start must leave the running benchmark running.
    EXPECT_NO_THROW((void)bm.sofar());
    EXPECT_NO_THROW(bm.stop());
    EXPECT_GE(bm.duration(), 0);
}

TEST(lsmioBenchmark, StopWithoutStartThrows) {
    lsmio::Benchmark bm;

    expectInvalidArgument([&] { bm.stop(); },
                          "ERROR: lsmio::Benchmark::stop: method ran without starting.");
    expectInvalidArgument([&] { bm.stop(false); },
                          "ERROR: lsmio::Benchmark::stop: method ran without starting.");

    // Nothing was started, so no stop time was recorded.
    EXPECT_EQ(bm.duration(), 0);
}

TEST(lsmioBenchmark, StopIdempotentWithoutStartIsNoop) {
    lsmio::Benchmark bm;

    EXPECT_NO_THROW(bm.stop(true));
    EXPECT_EQ(bm.duration(), 0);

    // The idempotent stop did not start the benchmark, so sofar() still refuses.
    expectInvalidArgument([&] { (void)bm.sofar(); },
                          "ERROR: lsmio::Benchmark::sofar: method ran without starting.");
}

TEST(lsmioBenchmark, StopIdempotentAfterStopKeepsDuration) {
    lsmio::Benchmark bm;
    bm.start();
    bm.stop();
    const int64_t d1 = bm.duration();

    EXPECT_NO_THROW(bm.stop(true));
    EXPECT_EQ(bm.duration(), d1);

    // The object can be restarted after the idempotent stop.
    EXPECT_NO_THROW(bm.start());
    bm.stop();
}

TEST(lsmioBenchmark, SofarRequiresRunning) {
    lsmio::Benchmark bm;

    expectInvalidArgument([&] { (void)bm.sofar(); },
                          "ERROR: lsmio::Benchmark::sofar: method ran without starting.");

    bm.start();
    bm.stop();
    expectInvalidArgument([&] { (void)bm.sofar(); },
                          "ERROR: lsmio::Benchmark::sofar: method ran without starting.");
}

// sofar() counts microseconds of steady_clock, the clock sleep_for waits on, so a 2 ms sleep
// advances it by at least 2000. A sofar() that returns a constant fails the lower bound.
TEST(lsmioBenchmark, SofarWhileRunningIsMonotonic) {
    lsmio::Benchmark bm;
    bm.start();

    const int64_t s1 = bm.sofar();
    std::this_thread::sleep_for(std::chrono::milliseconds(2));
    const int64_t s2 = bm.sofar();
    bm.stop();

    EXPECT_GE(s1, 0);
    EXPECT_GE(s2 - s1, 2000);
    EXPECT_GE(bm.duration(), s2);
}

TEST(lsmioBenchmark, DurationWhileRunningThrows) {
    lsmio::Benchmark bm;
    bm.start();

    expectInvalidArgument([&] { (void)bm.duration(); },
                          "ERROR: lsmio::Benchmark::duration: method ran while running.");

    // The rejected duration() call must leave the run intact.
    EXPECT_NO_THROW(bm.stop());
    EXPECT_GE(bm.duration(), 0);
}

TEST(lsmioBenchmark, NegativeOpsRejection) {
    lsmio::Benchmark bm;
    std::string name = "test";
    bm.addIteration(name, 1000, 1024, -1);

    double min = -1.0, mean = -1.0, max = -1.0;
    double total_bytes = -1.0, total_ops = -1.0;
    int iterations = -1;
    bm.summaryIteration(name, min, mean, max, iterations, total_bytes, total_ops);

    EXPECT_EQ(bm.formatSummary(name), "test, FAILED");
    EXPECT_EQ(bm.failedIterations(name), 1);
    EXPECT_EQ(iterations, 0);
    EXPECT_DOUBLE_EQ(total_bytes, 0.0);
    EXPECT_DOUBLE_EQ(total_ops, 0.0);
}

TEST(lsmioBenchmark, NonFiniteBytesAndOpsRejected) {
    const double nan = std::numeric_limits<double>::quiet_NaN();
    const double inf = std::numeric_limits<double>::infinity();

    lsmio::Benchmark a;
    lsmio::Benchmark b;
    lsmio::Benchmark c;
    lsmio::Benchmark d;
    lsmio::Benchmark e;

    a.addIteration("test", 1000, nan, 1);
    b.addIteration("test", 1000, 1024, nan);
    c.addIteration("test", 1000, inf, 1);
    d.addIteration("test", 1000, 1024, inf);
    e.addIteration("test", 1000, -inf, 1);

    auto checkRejected = [](lsmio::Benchmark &bm) {
        EXPECT_EQ(bm.formatSummary("test"), "test, FAILED");
        EXPECT_EQ(bm.failedIterations("test"), 1);

        double min = -1.0, mean = -1.0, max = -1.0;
        double total_bytes = -1.0, total_ops = -1.0;
        int iterations = -1;
        bm.summaryIteration("test", min, mean, max, iterations, total_bytes, total_ops);
        EXPECT_EQ(iterations, 0);
        EXPECT_DOUBLE_EQ(total_bytes, 0.0);
        EXPECT_DOUBLE_EQ(total_ops, 0.0);
    };

    checkRejected(a);
    checkRejected(b);
    checkRejected(c);
    checkRejected(d);
    checkRejected(e);

    lsmio::Benchmark f;
    f.addIteration("test", 1000, nan, 1);
    f.addIteration("test", 1000, 1024, 1);
    EXPECT_EQ(f.failedIterations("test"), 1);

    double min = -1.0, mean = -1.0, max = -1.0;
    double total_bytes = -1.0, total_ops = -1.0;
    int iterations = -1;
    f.summaryIteration("test", min, mean, max, iterations, total_bytes, total_ops);
    EXPECT_EQ(iterations, 1);
    EXPECT_DOUBLE_EQ(total_bytes, 1024.0);
}

TEST(lsmioBenchmark, FormatIterationsKeepsHeader) {
    lsmio::Benchmark bm;
    bm.addIteration("iwrite", 10 * 1000, 20 * 1024 * 1024, 10);

    const std::string expected_header =
        "access,max(MiB)/s,min(MiB/s),mean(MiB/s),total(MiB),total(Ops),iteration\n"
        "------,----------,----------,-----------,-----------,----------,----------\n";

    const std::string out = bm.formatIterations("iwrite");
    EXPECT_EQ(out, expected_header + "iwrite,2000.00,2000.00,2000.00,20.00,10,1\n");

    EXPECT_EQ(out.rfind(bm.formatSummary(""), 0), 0u);
    EXPECT_EQ(bm.failedIterations("iwrite"), 0);

    lsmio::Benchmark bm2;
    bm2.addIteration("a,b", 10 * 1000, 20 * 1024 * 1024, 10);
    EXPECT_EQ(bm2.formatIterations("a,b"),
              expected_header + "ab,2000.00,2000.00,2000.00,20.00,10,1\n");
}

int main(int argc, char **argv) {
    lsmio::initLSMIODebug(argv[0]);
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
