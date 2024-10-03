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

#include <iostream>
#include <algorithm>
#include <array>
#include <signal.h>
#include <stdexcept>

#include <fmt/format.h>
#include <boost/program_options.hpp>
#include <CLI/CLI.hpp>

#include <lsmio/lsmio.hpp>

#include "bm_base.hpp"

namespace bpo = boost::program_options;

BMConfig gConfigBM;

bool BMBase::useMPI = false;
int BMBase::mpiWorldSize = 0;
int BMBase::mpiWorldRank = 0;
int BMBase::mpiSize = 0;
int BMBase::mpiRank = 0;


BMBase::BMBase() {
  if (gConfigBM.dirName.empty()) {
    _lsmioBMPath = gConfigBM.fileName;
  }
  else {
    _lsmioBMPath = gConfigBM.dirName + "/" + gConfigBM.fileName;
  }

  LOG(WARNING) << "BMBase _lsmioBMPath: " << _lsmioBMPath
               << " gConfigBM.valueSize: " << gConfigBM.valueSize
               << std::endl;
}


std::string BMBase::genDBPath(bool opt1, bool opt2) {
  return _lsmioBMPath + ":" + std::to_string(opt1) + ":" + std::to_string(opt2);
}


bool BMBase::doReadFinalize() {
  return true;
}


bool BMBase::doWriteFinalize() {
  return true;
}


int BMBase::readCleanup() {
  return 0;
}


int BMBase::writeCleanup() {
  return 0;
}


int BMBase::benchWrite(long long *duration) {
  int count;
  std::string valSuffix(gConfigBM.valueSize-8, 'a');

  if (gConfigBM.useMPIBarrier) { MPI_Barrier(MPI_COMM_WORLD); }
  _bm.start();

  for(count=0; count < gConfigBM.keyCount; count++) {
    bool success = true;
    std::string key(_keyPrefix + fmt::format("{:06}", pRandomKeyIndex[count]));
    std::string value(std::to_string(count) + "::" + valSuffix);

    success &= doWrite(key, value);
    if (success == false) {
      break;
    }
  }
  doWriteFinalize();

  if (gConfigBM.useMPIBarrier) { MPI_Barrier(MPI_COMM_WORLD); }
  _bm.stop();

  *duration = _bm.duration();
  return (gConfigBM.keyCount - count);
}


int BMBase::benchRead(long long *duration) {
  int count;
  int exitCode = 0;
  std::string valSuffix(gConfigBM.valueSize-8, 'a');

  if (gConfigBM.useMPIBarrier) { MPI_Barrier(MPI_COMM_WORLD); }
  _bm.start();

  for(count=0; count < gConfigBM.keyCount; count++) {
    bool success = true;
    std::string key(_keyPrefix + fmt::format("{:06}", pRandomKeyIndex[count]));
    std::string pValue(std::to_string(count) + "::" + valSuffix);
    std::string value;

    success &= doRead(key, &value);
    if (success == false || pValue != value) {
      break;
    }
  }
  doReadFinalize();

  if (gConfigBM.useMPIBarrier) { MPI_Barrier(MPI_COMM_WORLD); }
  _bm.stop();

  *duration = _bm.duration();
  return (gConfigBM.keyCount - count);
}


int BMBase::benchIteration(int iteration, bool opt) {
  int exitCode = 0;
  long long duration = 0;

  pRandomKeyIndex = new int[gConfigBM.keyCount];
  for(int i=0; i< gConfigBM.keyCount; i++) pRandomKeyIndex[i] = i;
  std::random_shuffle(&pRandomKeyIndex[0], &pRandomKeyIndex[gConfigBM.keyCount]);

  double bytes = (double) gConfigBM.keyCount * gConfigBM.valueSize;
  if (useMPI) bytes *= mpiSize;

  writePrepare(opt);
  if (benchWrite(&duration) != 0) {
    LOG(ERROR) << "ERROR: benchWrite(): failed." << std::endl;
    duration = -1;
    exitCode += 1;
  }
  _bm.addIteration("iwrite", duration, bytes, gConfigBM.keyCount);
  writeCleanup();

  readPrepare(opt);
  if (benchRead(&duration) != 0) {
    LOG(ERROR) << "ERROR: benchRead(): failed." << std::endl;
    duration = -1;
    exitCode += 1;
  }
  _bm.addIteration("iread", duration, bytes, gConfigBM.keyCount);
  readCleanup();

  return exitCode;
}


int BMBase::benchSuite(std::string bmPrefix, bool opt) {
  int exitCode = 0;
  long long readTotal = 0, writeTotal = 0;

  for(int iter=0; iter < gConfigBM.iterations; iter++) {
    benchIteration(iter, opt);
  }

  _benchResultsWrite += "\nIteration-WRITE: " + bmPrefix + "\n";
  _benchResultsWrite += _bm.formatIterations("iwrite");
  _benchResultsWrite += "\nBench-WRITE: " + bmPrefix + "\n"
                     + _bm.formatSummary("");
  _benchResultsWrite += _bm.formatSummary("iwrite", "write");

  _benchResultsRead += "\nIteration-READ: " + bmPrefix + "\n";
  _benchResultsRead += _bm.formatIterations("iread");
  _benchResultsRead += "\nBench-READ: " + bmPrefix + "\n"
                     + _bm.formatSummary("");
  _benchResultsRead += _bm.formatSummary("iread", "read");

  _bm.clearIterations();

  return exitCode;
}


void BMBase::writeBenchmarkResults() {
  if (mpiRank != 0) {
    LOG(INFO) << "BMBase::writeBenchmarkResults: MPI is rank: " << mpiRank << ". Skipping results." << std::endl;
    return;
  }

  std::cout << "BENCHMARK PARAMETERS: \n\n"
            << (useMPI ? " MPI: Enabled\n" : "MPI: Disabled\n")
            << (useMPI ? " MPI Rank: " : "")
            << (useMPI ? std::to_string(mpiRank) : "")
            << (useMPI ? "\n" : "")
            << genOptionsToString() << "\n"
            << "BENCHMARK RESULTS: \n"
            << _benchResultsWrite << "\n"
            << _benchResultsRead << "\n"
            << std::endl;
}


std::string genOptionsToString() {
  std::stringstream optStream;

  optStream << " fileName: " << gConfigBM.fileName
            << "\n dirName: " << gConfigBM.dirName
            << "\n useLSMIOPlugin: " << gConfigBM.useLSMIOPlugin
            << "\n loopAll: " << gConfigBM.loopAll
            << "\n verbose: " << gConfigBM.verbose
            << "\n debug: " << gConfigBM.debug
            << "\n mpi-barrier: " << gConfigBM.useMPIBarrier
            << "\n collective-IO: " << gConfigBM.enableCollectiveIO
            << "\n mpi-io-world: " << (lsmio::gConfigLSMIO.mpiAggType != lsmio::MPIAggType::Shared ? "world" : "host-group")
            << "\n iterations: " << gConfigBM.iterations
            << "\n segmentCount: " << gConfigBM.segmentCount
            << "\n keyCount: " << gConfigBM.keyCount
            << "\n valueSize: " << gConfigBM.valueSize
            << "\n\n useBloomFilter: " << lsmio::gConfigLSMIO.useBloomFilter
            << "\n useSync: " << lsmio::gConfigLSMIO.useSync
            << "\n enableWAL: " << lsmio::gConfigLSMIO.enableWAL
            << "\n enableMMAP: " << lsmio::gConfigLSMIO.enableMMAP
            << "\n compression: " << lsmio::gConfigLSMIO.compression
            << "\n blockSize: " << lsmio::gConfigLSMIO.blockSize
            << "\n transferSize: " << lsmio::gConfigLSMIO.transferSize
            << "\n\n alwaysFlush: " << lsmio::gConfigLSMIO.alwaysFlush
            << "\n asyncBatchSize: " << lsmio::gConfigLSMIO.asyncBatchSize
            << "\n asyncBatchBytes: " << lsmio::gConfigLSMIO.asyncBatchBytes
            << "\n\n cacheSize: " << lsmio::gConfigLSMIO.cacheSize
            << "\n writeBufferSize: " << lsmio::gConfigLSMIO.writeBufferSize
            << "\n writeFileSize: " << lsmio::gConfigLSMIO.writeFileSize
            << "\n";

  return optStream.str();
}


int BMBase::beginMain(int argc, char **argv) {
  CLI::App app{"LSMIO Benchmark"};
  try {
    app.add_option("-o,--output-file", gConfigBM.fileName,
            "output file")
            ->required();
    app.add_option("-d,--output-dir", gConfigBM.dirName,
            "output directory");
    app.add_option("-v,--verbose", gConfigBM.verbose,
            "verbose mode (default: not-verbose)");
    app.add_option("-g,--debug", gConfigBM.debug,
            "debug mode (default: no)");
    app.add_option("-m,--mpi-barrier", gConfigBM.useMPIBarrier,
            "use mpi-barrier to start and stop the benchmark");
    app.add_option("-c,--collective-io", gConfigBM.enableCollectiveIO,
            "use collective-io while benchmarking");
    bool flag_mpi_io_world = false;
    app.add_option("-w,--mpi-io-world", flag_mpi_io_world,
            "use MPI world in collective-io (default: host level grouping)");

    app.add_option("-i,--iterations", gConfigBM.iterations,
            "terations (default: 1)");
    app.add_option("-l,--loop-all", gConfigBM.loopAll,
            "loop all options (default: only specified run)");
    app.add_option("-e,--sync", lsmio::gConfigLSMIO.useSync,
            "use sync API (default: false)");
    app.add_option("-k,--key-count", gConfigBM.keyCount,
            "number of keys (default: 1024)");
    app.add_option("-z,--value-size", gConfigBM.valueSize,
            "size of the value for a key (default: 64K)");
    app.add_option("-s,--segment-count", gConfigBM.segmentCount,
            "segment count (default: 1024)");

    app.add_option("--lsmio-plugin", gConfigBM.useLSMIOPlugin,
            "use lsmio plugin for adios benchmark (default: no plugin)");
    app.add_option("--lsmio-bfilter", lsmio::gConfigLSMIO.useBloomFilter,
            "use bloom filter (default: no bloom filter)");
    app.add_option("--lsmio-wal", lsmio::gConfigLSMIO.enableWAL,
            "use write-ahead log (default: no WAL)");
    app.add_option("--lsmio-mmap", lsmio::gConfigLSMIO.enableMMAP,
            "use MMAP read/write (default: no MMAP)");
    app.add_option("--lsmio-compress", lsmio::gConfigLSMIO.compression,
            "enable compression (default: no)");
    app.add_option("--lsmio-bs", lsmio::gConfigLSMIO.blockSize,
            "block size (default: 64K)");
    app.add_option("--lsmio-ts", lsmio::gConfigLSMIO.transferSize,
            "transfer size (default: 64K)");

    app.add_option("--ldb-always-flush", lsmio::gConfigLSMIO.alwaysFlush,
            "[leveldb] disable batching and makes read available immediately after write (default: no)");
    app.add_option("--ldb-batch-size", lsmio::gConfigLSMIO.asyncBatchSize,
            "[leveldb] deferred batch size (default: 512)");
    app.add_option("--ldb-batch-bytes", lsmio::gConfigLSMIO.asyncBatchBytes,
            "[leveldb] deferred batch size (default: 32M)");

    app.add_option("--lsmio-cache", lsmio::gConfigLSMIO.cacheSize,
            "LRU cache size (default: 0)");
    app.add_option("--lsmio-wbuffer", lsmio::gConfigLSMIO.writeBufferSize,
            "write buffer size (default: 32M)");
    app.add_option("--lsmio-fsize", lsmio::gConfigLSMIO.writeFileSize,
            "first-level file size (default: 32M)");

    app.parse(argc, argv);

    lsmio::gConfigLSMIO.mpiAggType = flag_mpi_io_world ? lsmio::MPIAggType::Entire : lsmio::MPIAggType::Shared;

    if (gConfigBM.fileName.empty()) {
      throw std::runtime_error("ERROR: Output file is required.");
    }
    if (gConfigBM.valueSize < 8) {
      throw std::runtime_error("ERROR: Value-size has to be >= 8.");
    }
    if (lsmio::gConfigLSMIO.transferSize < lsmio::gConfigLSMIO.blockSize) {
      throw std::runtime_error("ERROR: Transfer-size has to be >= block-size.");
    }
  }
  catch(const CLI::CallForHelp &e) {
    exit(app.exit(e));
  }
  catch (std::runtime_error &e) {
    std::cerr << "ERROR: " << e.what() << std::endl;
    std::cerr << app.help() << std::flush;
    exit(1);
  }
  catch (...) {
    std::cerr << "ERROR: Uknown" << std::endl;
    exit(2);
  }

  if (gConfigBM.verbose) {
    lsmio::initLSMIODebug(argv[0]);
  }
  else {
    lsmio::initLSMIORelease(argv[0]);
  }

  if (gConfigBM.debug) {
    signal(SIGSEGV, lsmio::handlerSIGSEGV);
  }

  if (gConfigBM.useMPIBarrier
      || gConfigBM.enableCollectiveIO) {
    useMPI = true;
  }

  if (useMPI) {
    int provided;
    MPI_Init_thread(nullptr, nullptr, MPI_THREAD_MULTIPLE, &provided);

    MPI_Comm_size(MPI_COMM_WORLD, &mpiWorldSize);
    MPI_Comm_rank(MPI_COMM_WORLD, &mpiWorldRank);

    int nameLen;
    char processName[MPI_MAX_PROCESSOR_NAME];
    MPI_Get_processor_name(processName, &nameLen);
    std::string pName(processName, nameLen);

    if (lsmio::gConfigLSMIO.mpiAggType == lsmio::MPIAggType::Shared) {
      MPI_Comm aggComm;
      MPI_Comm_split_type(MPI_COMM_WORLD, MPI_COMM_TYPE_SHARED, 0, MPI_INFO_NULL, &aggComm);
      MPI_Comm_size(aggComm, &mpiSize);
      MPI_Comm_rank(aggComm, &mpiRank);
    }
    else {
      mpiSize = mpiWorldSize;
      mpiRank = mpiWorldRank;
    }


    LOG(INFO) << "BMBase::beginMain: MPI Barrier enabled: "
              << " mpiSize: " << mpiSize
              << " mpiRank: " << mpiRank
              << " pName: " << pName
              << std::endl;
  }


  if (useMPI && mpiRank != 0) {
    LOG(INFO) << "BMBase::beginMain: MPI is rank: " << mpiRank << ". Skipping options print." << std::endl;
  }
  else {
    LOG(INFO) << "BMBase::beginMain: \n" << genOptionsToString() << std::endl;
  }

  return 0;
}


int BMBase::endMain() {
  if (useMPI) {
    MPI_Finalize();
    LOG(INFO) << "BMBase::endMain: MPI finalize on program end." << std::endl;
  }

  return 0;
}
