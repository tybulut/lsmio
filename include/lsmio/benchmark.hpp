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

#ifndef _LSMIO_BENCHMARK_HPP_
#define _LSMIO_BENCHMARK_HPP_

#include <chrono>  // NOLINT [build/c++11]
#include <lsmio/lsmio.hpp>
#include <map>
#include <string>
#include <tuple>

namespace lsmio {

/**
 * @class Benchmark
 * @brief Provides benchmarking utility for logging performance metrics.
 */
class Benchmark {
  private:
    bool _isStarted;
    std::chrono::steady_clock::time_point _start;
    std::chrono::steady_clock::time_point _stop;
    std::multimap<std::string, std::tuple<int64_t, double, double>> _iterations;

  public:
    /**
     * Default constructor.
     */
    Benchmark();

    /**
     * Destructor.
     */
    ~Benchmark();

    /**
     * Start the benchmark.
     */
    void start();

    /**
     * Stop the benchmark.
     * @param idempotent If set to true, suppresses errors on multiple stops without a start.
     */
    void stop(bool idempotent = false);

    /**
     * Get the elapsed time since the benchmark started.
     * @return Elapsed time in microseconds.
     */
    int64_t sofar() const;

    /**
     * Get the total duration of the benchmark.
     * @return Duration in microseconds.
     */
    int64_t duration() const;

    /**
     * Record an iteration with its metrics.
     * @param name Name of the iteration.
     * @param duration Duration of the iteration.
     * @param bytes Number of bytes processed in the iteration.
     * @param ops Number of operations in the iteration.
     */
    void addIteration(const std::string &name, int64_t duration, double bytes, double ops);

    /**
     * Compute summary metrics for a given iteration name.
     * @param name Name of the iteration.
     * @param min Minimum throughput observed.
     * @param mean Average throughput.
     * @param max Maximum throughput observed.
     * @param iterations Number of recorded iterations.
     * @param totalBytes Total bytes processed.
     * @param totalOps Total operations.
     */
    void summaryIteration(const std::string &name, double &min, double &mean, double &max,
                          int &iterations, double &totalBytes, double &totalOps);

    /**
     * Format the iteration metrics into a string.
     * @param name Name of the iteration.
     * @return Formatted string.
     */
    std::string formatIterations(const std::string &name);

    /**
     * Format the summary metrics into a string.
     * @param name Name of the iteration.
     * @param optSumName Optional name for the summary, defaulting to iteration name.
     * @return Formatted string.
     */
    std::string formatSummary(const std::string &name, const std::string &optSumName = "");

    /**
     * Clear all recorded iterations.
     */
    void clearIterations();
};

}  // namespace lsmio

#endif  // _LSMIO_BENCHMARK_HPP_
