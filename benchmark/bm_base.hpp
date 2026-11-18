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

#ifndef _BM_BASE_HPP_
#define _BM_BASE_HPP_

#include <fmt/format.h>
#include <mpi.h>

#include <iostream>
#include <lsmio/benchmark.hpp>
#include <string>

namespace lsmio {

enum BMExitStatus : int {
    BM_SUCCESS     = 0,      // All phases succeeded (0x00)
    BM_ERR_WRITE   = 1 << 0, // Write phase encountered failure (0x01)
    BM_ERR_READ    = 1 << 1, // Read phase encountered failure (0x02)
    BM_ERR_PREPARE = 1 << 2  // Setup/prepare phase failure (0x04)
};

}  // namespace lsmio

class BMBase {
  protected:
    inline static const std::string _keyPrefix = "benchmark:";
    /// Keys are the prefix and the key index, zero-padded to this many digits.
    static constexpr int KEY_INDEX_MIN_DIGITS = 6;

    std::string _lsmioBMPath = "";

    lsmio::Benchmark _bm;
    std::string _benchResultsWrite = "";
    std::string _benchResultsRead = "";

    int *pRandomKeyIndex = nullptr;
    /// Filler of every value, built before the benchmark starts.
    std::string _filler;

    static bool useMPI;
    static int mpiWorldSize;
    static int mpiWorldRank;
    static int mpiSize;
    static int mpiRank;

    std::string genDBPath(bool opt1, bool opt2);

    /// The key of the record with this key index.
    static inline std::string makeKey(int keyIndex) {
        return _keyPrefix + fmt::format("{:0{}}", keyIndex, KEY_INDEX_MIN_DIGITS);
    }
    /// Filler for records of gConfigBM.recordSize bytes; makeValue takes the record size from it.
    static std::string makeFiller();
    /// The value of the count-th record: its header ("<count>::") and filler, sized so that
    /// the key (keyLen bytes) and the value together are filler.size() bytes.
    static inline std::string makeValue(int count, size_t keyLen, const std::string &filler) {
        std::string value(std::to_string(count));
        value.append("::");
        // A record size below minRecordSize() gives a value of the header alone
        const size_t used = keyLen + value.size();
        if (filler.size() > used) {
            value.append(filler, 0, filler.size() - used);
        }
        return value;
    }

    int benchRead(long long *duration);
    int benchWrite(long long *duration);
    int benchIteration(int iteration, bool opt = false);

    virtual bool doRead(const std::string key, std::string *value) = 0;
    virtual bool doWrite(const std::string& key, const std::string& value) = 0;
    virtual bool doWrite(const std::string& key, std::string&& value) {
        return doWrite(key, value);
    }

    virtual bool doReadFinalize();
    virtual bool doWriteFinalize();

    virtual int readPrepare(bool opt = false) = 0;
    virtual int readCleanup();

    virtual int writePrepare(bool opt = false) = 0;
    virtual int writeCleanup();

  public:
    BMBase();

    int benchSuite(std::string bmPrefix, bool opt = false);
    void writeBenchmarkResults();

    static int beginMain(int argc, char **argv);
    static int endMain();

    /// The smallest record size that holds the longest key and value header of keyCount
    /// records.
    static int minRecordSize(int keyCount);
};

class BMConfig {
  public:
    std::string fileName;
    std::string dirName = "";

    bool useLSMIOPlugin = false;
    bool loopAll = false;
    bool verbose = false;
    bool debug = false;

    bool useMPIBarrier = false;
    bool enableCollectiveIO = false;

    int iterations = 1;       // TODO
    int segmentCount = 1024;  // TODO

    int keyCount = 4096;
    /// Bytes of one record: a key and its value. The value takes what the key leaves.
    int recordSize = 65536;
};

std::string genOptionsToString();

extern BMConfig gConfigBM;

#endif
