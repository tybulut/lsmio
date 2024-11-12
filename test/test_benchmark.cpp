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

int main(int argc, char **argv) {
    lsmio::initLSMIODebug(argv[0]);
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
