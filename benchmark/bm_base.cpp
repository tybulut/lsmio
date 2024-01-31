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

#include <fmt/format.h>
#include <boost/program_options.hpp>

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
  try {
    bpo::options_description desc("Program options");

    desc.add_options()
    ("help,h", "print this help screen")
    //
    ("output-file,o", bpo::value<std::string>(&gConfigBM.fileName), "output file (required)")
    ("output-dir,d", bpo::value<std::string>(&gConfigBM.dirName), "output directory (optional)")
    ("verbose,v", "verbose mode (default: not-verbose)")
    //
    ("mpi-barrier,m", "use mpi-barrier to start and stop the benchmark")
    ("collective-io,c", "use collective-io while benchmarking")
    ("mpi-io-world,w", "use MPI world in collective-io (default: host level grouping)")
    //
    ("iterations,i", bpo::value<int>(&gConfigBM.iterations), "terations (default: 1)")
    ("loop-all,l", "loop all options (default: only specified run)")
    ("sync,e", "use sync API (default: false)")
    ("key-count,k", bpo::value<int>(&gConfigBM.keyCount), "number of keys (default: 1024)")
    ("value-size,z", bpo::value<int>(&gConfigBM.valueSize), "size of the value for a key (default: 64K)")
    ("segment-count,s", bpo::value<int>(&gConfigBM.segmentCount), "segment count (default: 1024)")
    //
    ("lsmio-plugin", "use lsmio plugin for adios benchmark (default: no plugin)")
    ("lsmio-bfilter", "use bloom filter (default: no bloom filter)")
    ("lsmio-wal", "use write-ahead log (default: no WAL)")
    ("lsmio-mmap", "use MMAP read/write (default: no MMAP)")
    ("lsmio-compress", "enable compression (default: no)")
    ("lsmio-bs", bpo::value<int>(&lsmio::gConfigLSMIO.blockSize), "block size (default: 64K)")
    ("lsmio-ts", bpo::value<int>(&lsmio::gConfigLSMIO.transferSize), "transfer size (default: 64K)")
    //
    ("ldb-always-flush", "[leveldb] disable batching and makes read available immediately after write (default: no)")
    ("ldb-batch-size", bpo::value<int>(&lsmio::gConfigLSMIO.asyncBatchSize), "[leveldb] deferred batch size (default: 512)")
    ("ldb-batch-bytes", bpo::value<int>(&lsmio::gConfigLSMIO.asyncBatchBytes), "[leveldb] deferred batch size (default: 32M)")
    //
    ("lsmio-cache", bpo::value<int>(&lsmio::gConfigLSMIO.cacheSize), "LRU cache size (default: 0)")
    ("lsmio-wbuffer", bpo::value<int>(&lsmio::gConfigLSMIO.writeBufferSize), "write buffer size (default: 32M)")
    ("lsmio-fsize", bpo::value<int>(&lsmio::gConfigLSMIO.writeFileSize), "first-level file size (default: 32M)")
    ;

    bpo::variables_map vm;
    bpo::store(parse_command_line(argc, argv, desc), vm);
    bpo::notify(vm);

    if (vm.count("help")) {
      std::cerr << desc << std::endl;
      exit(0);
    }

    lsmio::gConfigLSMIO.useSync = vm.count("sync");
    lsmio::gConfigLSMIO.alwaysFlush = vm.count("ldb-always-flush");
    lsmio::gConfigLSMIO.useBloomFilter = vm.count("lsmio-bfilter");
    lsmio::gConfigLSMIO.enableWAL = vm.count("lsmio-wal");
    lsmio::gConfigLSMIO.enableMMAP = vm.count("lsmio-mmap");
    lsmio::gConfigLSMIO.compression = vm.count("lsmio-compress");
    lsmio::gConfigLSMIO.mpiAggType = vm.count("mpi-io-world") ? lsmio::MPIAggType::Entire : lsmio::MPIAggType::Shared;
    gConfigBM.useLSMIOPlugin = vm.count("lsmio-plugin");
    gConfigBM.loopAll = vm.count("loop-all");
    gConfigBM.verbose = vm.count("verbose");
    gConfigBM.useMPIBarrier = vm.count("mpi-barrier");
    gConfigBM.enableCollectiveIO = vm.count("collective-io");

    if (gConfigBM.fileName.empty()) {
      std::cerr << "ERROR: Output file is required."
                << std::endl << std::endl << desc << std::endl;
      exit(1);
    }
    if (gConfigBM.valueSize < 8) {
      std::cerr << "ERROR: Value-size has to be >= 8."
                << std::endl << std::endl << desc << std::endl;
      exit(1);
    }
    if (lsmio::gConfigLSMIO.transferSize < lsmio::gConfigLSMIO.blockSize) {
      std::cerr << "ERROR: Transfer-size has to be >= block-size."
                << std::endl << std::endl << desc << std::endl;
      exit(1);
    }
  }
  catch (std::exception &e) {
    std::cerr << e.what() << std::endl;
    exit(1);
  }

  if (gConfigBM.verbose) {
    lsmio::initLSMIODebug(argv[0]);
  }
  else {
    lsmio::initLSMIORelease(argv[0]);
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
