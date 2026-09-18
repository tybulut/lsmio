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
#include <lsmio/benchmark.hpp>
#include <lsmio/lsmio.hpp>
#include <thread>

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

int main(int argc, char **argv) {
    lsmio::initLSMIODebug(argv[0]);
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
