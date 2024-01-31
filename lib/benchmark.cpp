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

#include <fmt/format.h>

#include <iostream>
#include <algorithm>
#include <regex>  // NOLINT [build/c++11]

#include <lsmio/lsmio.hpp>
#include <lsmio/benchmark.hpp>


namespace sch = std::chrono;

namespace lsmio {

const std::string BM_HEADER = std::string("access,max(MiB)/s,min(MiB/s),mean(MiB/s),total(MiB),total(Ops),iteration\n")
                              + "------,----------,----------,-----------,-----------,----------,----------\n";

Benchmark::Benchmark() {
  _isStarted = false;
  _iterations = {};
}


Benchmark::~Benchmark() {
  clearIterations();
}


void Benchmark::start() {
  if (_isStarted) {
    throw std::invalid_argument("ERROR: lsmio::Benchmark::start: method ran but it is already started.");
  }

  LOG(INFO) << "Benchmark::start: Disabling g-logging." << std::endl;
  //decreaseLSMIOLogging();
  _isStarted = true;
  _start = sch::steady_clock::now();
}


void Benchmark::stop(bool idempotent) {
  if (!_isStarted) {
    if (idempotent) {
      LOG(INFO) << "Benchmark::stop: idempotent: ignoring successive stops." << std::endl;
      return;
    } else {
      throw std::invalid_argument("ERROR: lsmio::Benchmark::stop: method ran without starting.");
    }
  }

  _stop = sch::steady_clock::now();
  _isStarted = false;
  //defaultLSMIOLogging();
  LOG(INFO) << "Benchmark::stop: Renabling g-logging." << std::endl;
}


int64_t Benchmark::sofar() const {
  if (!_isStarted) {
    throw std::invalid_argument("ERROR: lsmio::Benchmark::stop: method ran without starting.");
  }

  auto delta = sch::duration_cast<sch::microseconds>(sch::steady_clock::now() - _start);
  return (int64_t) delta.count();
}


int64_t Benchmark::duration() const {
  if (_isStarted) {
    throw std::invalid_argument("ERROR: lsmio::Benchmark::stop: method ran while running.");
  }

  auto delta = sch::duration_cast<sch::microseconds>(_stop - _start);
  return (int64_t) delta.count();
}


void Benchmark::addIteration(const std::string& name, int64_t duration, double bytes, double ops) {
  _iterations.insert({name, {duration, bytes, ops}});
}


void Benchmark::summaryIteration(const std::string& name, double &min, double &mean, double &max,
                                      int &iterations, double &totalBytes, double &totalOps) {
  int64_t duration;
  double bytes, ops;
  double bw, totalBW = 0.00;

  iterations = 0;
  min = mean = max = 0.00;
  totalBytes = totalOps = 0.00;
  for (auto const& entry : _iterations) {
    if (entry.first != name) continue;

    std::tie(duration, bytes, ops) = entry.second;
    bw = bytes / duration / 1.024 / 1.024;

    if (0 == iterations++) { min = max = bw; }
    else {
      if (bw < min) min = bw;
      else if (bw > max) max = bw;
    }

    totalBW += bw;
    totalBytes += bytes;
    totalOps += ops;

    LOG(INFO) << "Benchmark::summaryIteration: "
              << " min: " << min
              << " max: " << max
              << " totalBytes: " << totalBytes
              << " totalOps: " << totalOps
              << " iterations: " << iterations << std::endl;
  }

  if (iterations) {
    mean = static_cast<double>(totalBW / iterations);
  }

  LOG(INFO) << "Benchmark::summaryIteration: "
            << " min: " << min
            << " max: " << max
            << " mean: " << mean
            << " totalBytes: " << totalBytes
            << " totalOps: " << totalOps
            << " iterations: " << iterations << std::endl;
}


std::string Benchmark::formatIterations(const std::string& name) {
  std::string output;
  int64_t duration;
  double bytes, bw, ops;

  output = BM_HEADER;

  for (auto const& entry : _iterations) {
    if (entry.first != name) continue;

    std::tie(duration, bytes, ops) = entry.second;
    bw = bytes / duration / 1.024 / 1.024;

    output += name + ":"
         + fmt::format("{:.2f}", bw) + ":"
         + fmt::format("{:.2f}", bw) + ":"
         + fmt::format("{:.2f}", bw) + ":"
         + fmt::format("{:.2f}", bytes / 1024 / 1024) + ":"
         + fmt::format("{:.0f}", ops) + ":"
         + "1\n";
  }

  output = std::regex_replace(output, std::regex(","), "");
  output = std::regex_replace(output, std::regex(":"), ",");

  return output;
}


std::string Benchmark::formatSummary(const std::string& name, const std::string& optSumName) {
  std::string output;
  double min, mean, max;
  double totalBytes, totalOps;
  int iterations;
  std::string sumName = (optSumName.empty()) ? name : optSumName;

  summaryIteration(name, min, mean, max, iterations, totalBytes, totalOps);
  if (name.empty()) {
    return BM_HEADER;
  }

  if (totalBytes <= 0) {
    return name + ", FAILED\n";
  }

  output = sumName + ":"
         + fmt::format("{:.2f}", max) + ":"
         + fmt::format("{:.2f}", min) + ":"
         + fmt::format("{:.2f}", mean) + ":"
         + fmt::format("{:.2f}", totalBytes / 1024 / 1024) + ":"
         + fmt::format("{:.0f}", totalOps) + ":"
         + std::to_string(iterations);

  output = std::regex_replace(output, std::regex(","), "");
  output = std::regex_replace(output, std::regex(":"), ",");

  return output;
}


void Benchmark::clearIterations() {
  _iterations.clear();
}

}  // namespace lsmio
