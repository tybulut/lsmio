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

#include <mpi.h>

#include <iostream>
#include <lsmio/benchmark.hpp>

class BMBase {
  protected:
    const std::string _keyPrefix = "benchmark:";

    std::string _lsmioBMPath = "";

    lsmio::Benchmark _bm;
    std::string _benchResultsWrite = "";
    std::string _benchResultsRead = "";

    int *pRandomKeyIndex;

    static bool useMPI;
    static int mpiWorldSize;
    static int mpiWorldRank;
    static int mpiSize;
    static int mpiRank;

    std::string genDBPath(bool opt1, bool opt2);

    int benchRead(long long *duration);
    int benchWrite(long long *duration);
    int benchIteration(int iteration, bool opt = false);

    virtual bool doRead(const std::string key, std::string *value) = 0;
    virtual bool doWrite(const std::string key, const std::string value) = 0;

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
    int valueSize = 65535;
};

std::string genOptionsToString();

extern BMConfig gConfigBM;

#endif
