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

#include "bm_base.hpp"

#include <fmt/format.h>
#include <signal.h>

#include <CLI/CLI.hpp>
#include <algorithm>
#include <array>
#include <filesystem>
#include <iostream>
#include <lsmio/Version.hpp>
#include <lsmio/lsmio.hpp>
#include <map>
#include <numeric>
#include <random>
#include <stdexcept>
#include <vector>

#include "KeyPermutation.hpp"
#include "PhaseTimeline.hpp"

BMConfig gConfigBM;

bool BMBase::useMPI = false;
int BMBase::mpiWorldSize = 0;
int BMBase::mpiWorldRank = 0;
int BMBase::mpiSize = 0;
int BMBase::mpiRank = 0;

BMBase::BMBase() {
    if (gConfigBM.dirName.empty()) {
        _lsmioBMPath = gConfigBM.fileName;
    } else {
        _lsmioBMPath = gConfigBM.dirName + "/" + gConfigBM.fileName;
    }
    if (gConfigBM.perRankPath) {
        _lsmioBMPath += ".mpirank" + std::to_string(mpiWorldRank);
    }

    // The own store is the read source until the read-shift exchange says otherwise.
    m_read_source.source_world_rank = useMPI ? mpiWorldRank : 0;
    m_read_source.source_base_path = _lsmioBMPath;
    m_read_source.is_self = true;
    m_read_source.same_host = true;
    m_read_source.self_ranks_world = 0;
    m_read_source.same_host_ranks_world = 0;

    LOG(WARNING) << "BMBase _lsmioBMPath: " << _lsmioBMPath
                 << " gConfigBM.valueSize: " << gConfigBM.valueSize << std::endl;
}

std::string BMBase::genDBPath(bool opt1, bool opt2) {
    return _lsmioBMPath + ":" + std::to_string(opt1) + ":" + std::to_string(opt2);
}

std::string BMBase::readDBPath(bool f_opt1, bool f_opt2) {
    return m_read_source.source_base_path + ":" + std::to_string(f_opt1) + ":" +
           std::to_string(f_opt2);
}

bool BMBase::supportsReadShift() const {
    return false;
}

std::string BMBase::engineHeaderLines() const {
    return "";
}

std::string readShiftRefusal(bool f_supported, int f_nodes, int f_world_size) {
    if (!f_supported) {
        return "--read-shift is not supported by this benchmark executable.";
    }
    if (f_nodes > f_world_size) {
        return "--read-shift-nodes " + std::to_string(f_nodes) +
               " is larger than the MPI world size " + std::to_string(f_world_size) + ".";
    }
    return "";
}

std::string duplicateStorePathRefusal(const std::vector<std::string>& f_paths) {
    std::map<std::string, int> first_rank_of_path;
    for (size_t rank = 0; rank < f_paths.size(); ++rank) {
        auto inserted = first_rank_of_path.emplace(f_paths[rank], static_cast<int>(rank));
        if (!inserted.second) {
            return "--read-shift needs one store per rank, but ranks " +
                   std::to_string(inserted.first->second) + " and " + std::to_string(rank) +
                   " use the same store path '" + f_paths[rank] +
                   "'. Give every rank its own path (--per-rank-path).";
        }
    }
    return "";
}

ReadSource makeReadSource(int f_world_rank, const std::vector<int>& f_node_ids,
                          const std::vector<std::string>& f_paths,
                          const std::vector<std::string>& f_names) {
    const std::vector<ReadShiftPeers> peers = mapReadShift(f_node_ids);
    const size_t rank = static_cast<size_t>(f_world_rank);
    const int source = peers[rank].source_world_rank;

    ReadSource result;
    result.source_world_rank = source;
    result.source_base_path = f_paths[static_cast<size_t>(source)];
    result.is_self = (source == f_world_rank);
    result.same_host = (f_names[static_cast<size_t>(source)] == f_names[rank]);
    result.self_ranks_world = 0;
    result.same_host_ranks_world = 0;
    for (size_t r = 0; r < peers.size(); ++r) {
        const size_t peer_source = static_cast<size_t>(peers[r].source_world_rank);
        if (peer_source == r) result.self_ranks_world++;
        if (f_names[peer_source] == f_names[r]) result.same_host_ranks_world++;
    }
    return result;
}

namespace {

// Every rank ends the run together (INV-6, INV-14): the verdict is the same on all of them.
[[noreturn]] void refuseReadShift(const std::string& f_message) {
    std::cerr << "ERROR: " << f_message << std::endl;
    LOG(ERROR) << "BMBase::setupReadSource: " << f_message << std::endl;
    MPI_Finalize();
    exit(1);
}

// One string per world rank, gathered on every rank (collective over MPI_COMM_WORLD).
std::vector<std::string> gatherStrings(const std::string& f_local, int f_world_size) {
    const size_t size = static_cast<size_t>(f_world_size);
    int length = static_cast<int>(f_local.size());
    std::vector<int> lengths(size);
    MPI_Allgather(&length, 1, MPI_INT, lengths.data(), 1, MPI_INT, MPI_COMM_WORLD);

    std::vector<int> displacements(size);
    int total = 0;
    for (size_t r = 0; r < size; ++r) {
        displacements[r] = total;
        total += lengths[r];
    }
    std::vector<char> all(static_cast<size_t>(total));
    MPI_Allgatherv(f_local.data(), length, MPI_CHAR, all.data(), lengths.data(),
                   displacements.data(), MPI_CHAR, MPI_COMM_WORLD);

    std::vector<std::string> result(size);
    for (size_t r = 0; r < size; ++r) {
        result[r].assign(all.data() + displacements[r], static_cast<size_t>(lengths[r]));
    }
    return result;
}

}  // namespace

void BMBase::setupReadSource() {
    if (m_read_source_ready) return;
    m_read_source_ready = true;

    if (!gConfigBM.readShift) {
        m_read_source.source_world_rank = useMPI ? mpiWorldRank : 0;
        m_read_source.source_base_path = _lsmioBMPath;
        m_read_source.is_self = true;
        m_read_source.same_host = true;
        m_read_source.self_ranks_world = 0;
        m_read_source.same_host_ranks_world = 0;
        return;
    }

    // Argv, executable and world size only: identical on all ranks.
    std::string refusal =
        readShiftRefusal(supportsReadShift(), gConfigBM.readShiftNodes, mpiWorldSize);
    if (!refusal.empty()) refuseReadShift(refusal);

    // Node id of every world rank.
    std::vector<int> node_ids(static_cast<size_t>(mpiWorldSize));
    if (gConfigBM.readShiftNodes > 0) {
        for (int r = 0; r < mpiWorldSize; ++r) {
            node_ids[static_cast<size_t>(r)] = r % gConfigBM.readShiftNodes;
        }
    } else {
        // The shared-memory split is independent of mpiAggType, so it also works under -w. Its key
        // is the world rank, so the smallest world rank in it is the node id.
        MPI_Comm node_comm;
        MPI_Comm_split_type(MPI_COMM_WORLD, MPI_COMM_TYPE_SHARED, mpiWorldRank, MPI_INFO_NULL,
                            &node_comm);
        int node_id = 0;
        MPI_Allreduce(&mpiWorldRank, &node_id, 1, MPI_INT, MPI_MIN, node_comm);
        MPI_Allgather(&node_id, 1, MPI_INT, node_ids.data(), 1, MPI_INT, MPI_COMM_WORLD);
        MPI_Comm_free(&node_comm);
    }

    // Every rank's base store path and processor name, from the writers over MPI (INV-16).
    char processor_name[MPI_MAX_PROCESSOR_NAME];
    int name_length = 0;
    MPI_Get_processor_name(processor_name, &name_length);
    std::vector<std::string> paths = gatherStrings(_lsmioBMPath, mpiWorldSize);
    std::vector<std::string> names =
        gatherStrings(std::string(processor_name, static_cast<size_t>(name_length)), mpiWorldSize);

    refusal = duplicateStorePathRefusal(paths);
    if (!refusal.empty()) refuseReadShift(refusal);

    m_read_source = makeReadSource(mpiWorldRank, node_ids, paths, names);
}

std::string BMBase::readShiftHeaderLines() const {
    if (!gConfigBM.readShift) return "";
    std::string nodes = gConfigBM.readShiftNodes > 0
                            ? "simulated:" + std::to_string(gConfigBM.readShiftNodes)
                            : "shared";
    return " rankShiftNodes: " + nodes +
           "\n rankShiftSource: " + std::to_string(m_read_source.source_world_rank) +
           "\n rankShiftSelfRanks: " + std::to_string(m_read_source.self_ranks_world) +
           "\n rankShiftSameHostRanks: " + std::to_string(m_read_source.same_host_ranks_world) +
           "\n";
}

void BMBase::beginPhaseTimeline() {
    m_phase_origin = std::chrono::steady_clock::now();
    m_phases.offset_us[static_cast<int>(PhaseSide::Write)]
                      [static_cast<int>(PhaseBoundary::BeforeOpen)] = 0;
}

void BMBase::capturePhase(PhaseSide f_side, PhaseBoundary f_boundary) {
    m_phases.offset_us[static_cast<int>(f_side)][static_cast<int>(f_boundary)] =
        std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now() -
                                                              m_phase_origin)
            .count();
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
    std::string valSuffix(gConfigBM.valueSize - 8, 'a');

    if (gConfigBM.useMPIBarrier) {
        MPI_Barrier(MPI_COMM_WORLD);
    }
    _bm.start();
    capturePhase(PhaseSide::Write, PhaseBoundary::AfterOpen);
    pRandomKeyIndex = m_put_keys.data();

    for (count = 0; count < gConfigBM.keyCount; count++) {
        bool success = true;
        std::string key(_keyPrefix + fmt::format("{:06}", pRandomKeyIndex[count]));
        std::string value(std::to_string(count) + "::" + valSuffix);

        success &= doWrite(key, std::move(value));
        if (success == false) {
            break;
        }
    }
    capturePhase(PhaseSide::Write, PhaseBoundary::BeforeClose);
    doWriteFinalize();

    if (gConfigBM.useMPIBarrier) {
        MPI_Barrier(MPI_COMM_WORLD);
    }
    capturePhase(PhaseSide::Write, PhaseBoundary::AfterClose);
    _bm.stop();

    *duration = _bm.duration();
    return (gConfigBM.keyCount - count);
}

int BMBase::benchRead(long long *duration) {
    int count;
    int exitCode = 0;
    std::string valSuffix(gConfigBM.valueSize - 8, 'a');

    if (gConfigBM.useMPIBarrier) {
        MPI_Barrier(MPI_COMM_WORLD);
    }
    _bm.start();
    capturePhase(PhaseSide::Read, PhaseBoundary::AfterOpen);
    pRandomKeyIndex = m_get_keys.data();

    for (count = 0; count < gConfigBM.keyCount; count++) {
        bool success = true;
        std::string key(_keyPrefix + fmt::format("{:06}", pRandomKeyIndex[count]));
        std::string pValue(std::to_string(count) + "::" + valSuffix);
        std::string value;

        success &= doRead(key, &value);
        if (success == false || pValue != value) {
            break;
        }
    }
    capturePhase(PhaseSide::Read, PhaseBoundary::BeforeClose);
    doReadFinalize();

    if (gConfigBM.useMPIBarrier) {
        MPI_Barrier(MPI_COMM_WORLD);
    }
    capturePhase(PhaseSide::Read, PhaseBoundary::AfterClose);
    _bm.stop();

    *duration = _bm.duration();
    return (gConfigBM.keyCount - count);
}

int BMBase::benchIteration(int iteration, bool opt) {
    int exitCode = lsmio::BM_SUCCESS;
    long long duration = 0;

    const bool barrier = gConfigBM.useMPIBarrier;
    constexpr int kWrite = static_cast<int>(PhaseSide::Write);
    constexpr int kRead = static_cast<int>(PhaseSide::Read);

    // Untimed setup before any window: the timeline record and both key orders (INV-13). The
    // writer's order is its own; the reader's is its source writer's (itself without read shift).
    m_phases = IterationPhases();
    m_phases.iteration = iteration;
    // Promote to double before the product: keyCount * valueSize * ranks overflows int (NB-R-P3).
    m_phases.bytes = static_cast<double>(gConfigBM.keyCount) * gConfigBM.valueSize *
                     (useMPI ? static_cast<double>(mpiWorldSize) : 1.0);
    m_put_keys = keyPermutation(useMPI ? mpiWorldRank : 0, iteration, gConfigBM.keyCount);
    m_get_keys = keyPermutation(m_read_source.source_world_rank, iteration, gConfigBM.keyCount);

    // The legacy rows keep their bytes (times mpiSize).
    double bytes = (double)gConfigBM.keyCount * gConfigBM.valueSize;
    if (useMPI) bytes *= mpiSize;

    // --- WRITE PHASE ---
    if (barrier) MPI_Barrier(MPI_COMM_WORLD);
    beginPhaseTimeline();
    writePrepare(opt);
    int writeStatus = benchWrite(&duration);
    writeCleanup();
    if (barrier) MPI_Barrier(MPI_COMM_WORLD);
    capturePhase(PhaseSide::Write, PhaseBoundary::AfterDelete);

    int localWriteFail = (writeStatus != 0) ? 1 : 0;
    int globalWriteFail = 0;

    if (useMPI) {
        MPI_Allreduce(&localWriteFail, &globalWriteFail, 1, MPI_INT, MPI_LOR, MPI_COMM_WORLD);
    } else {
        globalWriteFail = localWriteFail;
    }

    if (globalWriteFail != 0) {
        LOG(ERROR)
            << "BMBase::benchIteration: benchWrite failed on one or more ranks (localStatus: "
            << writeStatus << ")." << std::endl;
        exitCode |= lsmio::BM_ERR_WRITE;
        // Tier 1 suppression: DO NOT call _bm.addIteration("iwrite")!
    } else {
        _bm.addIteration("iwrite", duration, bytes, gConfigBM.keyCount);
        m_phases.side_recorded[kWrite] = true;
    }

    // Fail-Fast Check: If write phase failed, skip read phase entirely
    if (globalWriteFail == 0) {
        // --- READ PHASE ---
        if (barrier) MPI_Barrier(MPI_COMM_WORLD);
        capturePhase(PhaseSide::Read, PhaseBoundary::BeforeOpen);
        readPrepare(opt);
        int readStatus = benchRead(&duration);
        readCleanup();
        if (barrier) MPI_Barrier(MPI_COMM_WORLD);
        capturePhase(PhaseSide::Read, PhaseBoundary::AfterDelete);

        int localReadFail = (readStatus != 0) ? 1 : 0;
        int globalReadFail = 0;

        if (useMPI) {
            MPI_Allreduce(&localReadFail, &globalReadFail, 1, MPI_INT, MPI_LOR, MPI_COMM_WORLD);
        } else {
            globalReadFail = localReadFail;
        }

        if (globalReadFail != 0) {
            LOG(ERROR)
                << "BMBase::benchIteration: benchRead failed on one or more ranks (localStatus: "
                << readStatus << ")." << std::endl;
            exitCode |= lsmio::BM_ERR_READ;
            // Tier 1 suppression: DO NOT call _bm.addIteration("iread")!
        } else {
            _bm.addIteration("iread", duration, bytes, gConfigBM.keyCount);
            m_phases.side_recorded[kRead] = true;
        }
    }

    // One reduction per iteration, failed ones included, after the last failure reduction and never
    // between two captures of a side (INV-5). side_recorded derives from the reduced failure flags,
    // so it is the same on every rank.
    if (useMPI) {
        MPI_Allreduce(MPI_IN_PLACE, &m_phases.offset_us[0][0], 10, MPI_INT64_T, MPI_MAX,
                      MPI_COMM_WORLD);
    }
    m_suite_phase_rows += formatPhaseRows(m_phases);

    pRandomKeyIndex = nullptr;
    return exitCode;
}

int BMBase::benchSuite(std::string bmPrefix, bool opt) {
    int exitCode = lsmio::BM_SUCCESS;
    long long readTotal = 0, writeTotal = 0;

    // Once per object, before the first iteration and before any store is opened (INV-14).
    setupReadSource();

    for (int iter = 0; iter < gConfigBM.iterations; iter++) {
        int iterStatus = benchIteration(iter, opt);
        if (iterStatus != lsmio::BM_SUCCESS) {
            exitCode |= iterStatus;
            LOG(ERROR) << "BMBase::benchSuite: Iteration " << iter << " failed with status "
                       << iterStatus << ". Halting suite execution immediately without retry."
                       << std::endl;
            break;  // Zero Retries / Fail-Fast
        }
    }

    _benchResultsWrite += "\nIteration-WRITE: " + bmPrefix + "\n";
    _benchResultsWrite += _bm.formatIterations("iwrite");
    _benchResultsWrite += "\nBench-WRITE: " + bmPrefix + "\n" + _bm.formatSummary("");
    _benchResultsWrite += _bm.formatSummary("iwrite", "write");

    _benchResultsRead += "\nIteration-READ: " + bmPrefix + "\n";
    _benchResultsRead += _bm.formatIterations("iread");
    _benchResultsRead += "\nBench-READ: " + bmPrefix + "\n" + _bm.formatSummary("");
    _benchResultsRead += _bm.formatSummary("iread", "read");

    // One phase block per suite, even without rows; it is printed after all READ blocks.
    m_bench_results_phases += "\nPhases: " + bmPrefix + "\n" + m_suite_phase_rows;
    m_suite_phase_rows.clear();

    _bm.clearIterations();

    return exitCode;
}

void BMBase::writeBenchmarkResults() {
    if (mpiRank != 0) {
        LOG(INFO) << "BMBase::writeBenchmarkResults: MPI is rank: " << mpiRank
                  << ". Skipping results." << std::endl;
        return;
    }

    std::cout << "BENCHMARK PARAMETERS: \n\n"
              << (useMPI ? " MPI: Enabled\n" : "MPI: Disabled\n") << (useMPI ? " MPI Rank: " : "")
              << (useMPI ? std::to_string(mpiRank) : "") << (useMPI ? "\n" : "")
              << genOptionsToString() << readShiftHeaderLines() << engineHeaderLines() << "\n"
              << "BENCHMARK RESULTS: \n"
              << _benchResultsWrite << "\n"
              << _benchResultsRead << "\n"
              << m_bench_results_phases << std::endl;
}

std::string genOptionsToString() {
    std::stringstream optStream;

    optStream << " version: " << lsmio::getVersion() << "\n"
              << " gitBranch: " << lsmio::getGitBranch() << "\n"
              << " gitCommit: " << lsmio::getGitCommitHash() << "\n"
              << " fileName: " << gConfigBM.fileName << "\n dirName: " << gConfigBM.dirName
              << "\n useLSMIOPlugin: " << gConfigBM.useLSMIOPlugin
              << "\n loopAll: " << gConfigBM.loopAll << "\n verbose: " << gConfigBM.verbose
              << "\n debug: " << gConfigBM.debug << "\n mpi-barrier: " << gConfigBM.useMPIBarrier
              << "\n collective-IO: " << gConfigBM.enableCollectiveIO << "\n mpi-io-world: "
              << (lsmio::gConfigLSMIO.mpiAggType != lsmio::MPIAggType::Shared ? "world"
                                                                              : "host-group")
              << "\n mpiAggType: " << lsmio::to_string(lsmio::gConfigLSMIO.mpiAggType)
              << "\n iterations: " << gConfigBM.iterations
              << "\n segmentCount: " << gConfigBM.segmentCount
              << "\n keyCount: " << gConfigBM.keyCount << "\n valueSize: " << gConfigBM.valueSize
              << "\n\n useBloomFilter: " << lsmio::gConfigLSMIO.useBloomFilter
              << "\n useSync: " << lsmio::gConfigLSMIO.useSync
              << "\n enableWAL: " << lsmio::gConfigLSMIO.enableWAL
              << "\n enableMMAP: " << lsmio::gConfigLSMIO.enableMMAP
              << "\n enablePread: " << lsmio::gConfigLSMIO.enablePread << "\n useLevelDB: "
              << (lsmio::gConfigLSMIO.storageType == lsmio::StorageType::LevelDB ? "yes" : "no")
              << "\n useRocksDB: "
              << (lsmio::gConfigLSMIO.storageType == lsmio::StorageType::RocksDB ? "yes" : "no")
              << "\n useNativeDB: "
              << (lsmio::gConfigLSMIO.storageType == lsmio::StorageType::NativeDB ? "yes" : "no")
              << "\n compression: " << lsmio::gConfigLSMIO.compression
              << "\n blockSize: " << lsmio::gConfigLSMIO.blockSize
              << "\n transferSize: " << lsmio::gConfigLSMIO.transferSize
              << "\n\n alwaysFlush: " << lsmio::gConfigLSMIO.alwaysFlush
              << "\n asyncBatchSize: " << lsmio::gConfigLSMIO.asyncBatchSize
              << "\n asyncBatchBytes: " << lsmio::gConfigLSMIO.asyncBatchBytes
              << "\n\n cacheSize: " << lsmio::gConfigLSMIO.cacheSize
              << "\n writeBufferSize: " << lsmio::gConfigLSMIO.writeBufferSize
              << "\n writeFileSize: " << lsmio::gConfigLSMIO.writeFileSize
              << "\n preAllocate: " << lsmio::gConfigLSMIO.preAllocate
              << "\n disableAggDirStructure: " << lsmio::gConfigLSMIO.disableAggDirStructure
              << "\n filePoolSize: " << lsmio::gConfigLSMIO.filePoolSize
              << "\n storageType: " << lsmio::to_string(lsmio::gConfigLSMIO.storageType)
              << "\n memtable: " << lsmio::to_string(lsmio::gConfigLSMIO.memtable)
              << "\n maxKeyLen: " << lsmio::gConfigLSMIO.maxKeyLen
              << "\n maxValueLen: " << lsmio::gConfigLSMIO.getMaxValueLen()
              << "\n manualOffset: " << (lsmio::gConfigLSMIO.manualOffset ? "true" : "false")
              << "\n footerIndex: " << (lsmio::gConfigLSMIO.footerIndex ? "true" : "false")
              << "\n writeBufferNumber: " << lsmio::gConfigLSMIO.writeBufferNumber
              << "\n autoTuneParameters: "
              << (lsmio::gConfigLSMIO.autoTuneParameters ? "true" : "false")
              << "\n readOnly: " << (lsmio::gConfigLSMIO.readOnly ? "true" : "false")
              << "\n perRankPath: " << gConfigBM.perRankPath
              << "\n durability: " << lsmio::to_string(lsmio::gConfigLSMIO.durability)
              << "\n rankShift: " << gConfigBM.readShift << "\n";

    return optStream.str();
}

int BMBase::beginMain(int argc, char **argv) {
    CLI::App app{"LSMIO Benchmark"};
    try {
        std::string binaryName = std::filesystem::path(argv[0]).filename().string();
        std::string versionInfo = binaryName + " version " + lsmio::getVersion() +
                                  " (branch: " + lsmio::getGitBranch() +
                                  ", commit: " + lsmio::getGitCommitHash() + ")";
        app.set_version_flag("-V,--version", versionInfo, "Print version information and exit");

        app.add_option("-o,--output-file", gConfigBM.fileName, "output file")->required();
        app.add_option("-d,--output-dir", gConfigBM.dirName, "output directory");
        app.add_flag("-v,--verbose", gConfigBM.verbose, "verbose mode (default: not-verbose)");
        app.add_flag("-g,--debug", gConfigBM.debug, "debug mode (default: no)");
        app.add_flag("-m,--mpi-barrier", gConfigBM.useMPIBarrier,
                     "use mpi-barrier around every phase (before and after open, after close, "
                     "after delete) of the write and read sides");
        app.add_flag("-c,--collective-io", gConfigBM.enableCollectiveIO,
                     "use collective-io while benchmarking");
        bool flag_mpi_io_world = false;
        app.add_flag("-w,--mpi-io-world", flag_mpi_io_world,
                     "use MPI world in collective-io (default: host level grouping)");

        app.add_option("-i,--iterations", gConfigBM.iterations, "terations (default: 1)");
        app.add_flag("-l,--loop-all", gConfigBM.loopAll,
                     "loop all options (default: only specified run)");
        app.add_flag("-e,--sync", lsmio::gConfigLSMIO.useSync, "use sync API (default: false)");
        app.add_option("-k,--key-count", gConfigBM.keyCount, "number of keys (default: 1024)");
        app.add_option("-z,--value-size", gConfigBM.valueSize,
                       "size of the value for a key (default: 64K)");
        app.add_option("-s,--segment-count", gConfigBM.segmentCount,
                       "segment count (default: 1024)");

        app.add_flag("--lsmio-plugin", gConfigBM.useLSMIOPlugin,
                     "use lsmio plugin for adios benchmark (default: no plugin)");
        app.add_flag("--lsmio-bfilter", lsmio::gConfigLSMIO.useBloomFilter,
                     "use bloom filter (default: no bloom filter)");
        app.add_flag("--lsmio-wal", lsmio::gConfigLSMIO.enableWAL,
                     "use write-ahead log (default: no WAL)");
        app.add_flag("--lsmio-mmap", lsmio::gConfigLSMIO.enableMMAP,
                     "use MMAP read/write (default: no MMAP)");
        app.add_flag("--lsmio-pread,!--lsmio-no-pread", lsmio::gConfigLSMIO.enablePread,
                     "use persistent descriptor pread() read (default: pread)");

        bool flag_use_leveldb = false;
        bool flag_use_rocksdb = false;
        app.add_flag("--lsmio-use-leveldb", flag_use_leveldb,
                     "use LevelDB instead (default: use NativeDB)");
        app.add_flag("--lsmio-use-rocksdb", flag_use_rocksdb,
                     "use RocksDB instead (default: use NativeDB)");
        app.add_flag("--lsmio-compress", lsmio::gConfigLSMIO.compression,
                     "enable compression (default: no)");
        app.add_option("--lsmio-bs", lsmio::gConfigLSMIO.blockSize, "block size (default: 64K)");
        app.add_option("--lsmio-ts", lsmio::gConfigLSMIO.transferSize,
                       "transfer size (default: 64K)");

        app.add_flag("--lsmio-always-flush,--lsmo-always-flush", lsmio::gConfigLSMIO.alwaysFlush,
                     "disable batching and makes read available immediately after "
                     "write (default: no)");
        app.add_option("--lsmio-batch-size", lsmio::gConfigLSMIO.asyncBatchSize,
                       "batch size (default: 512)");
        app.add_option("--lsmio-batch-bytes", lsmio::gConfigLSMIO.asyncBatchBytes,
                       "deferred batch size (default: 32M)");

        app.add_option("--lsmio-cache", lsmio::gConfigLSMIO.cacheSize,
                       "LRU cache size (default: 0)");
        app.add_option("--lsmio-wbuffer", lsmio::gConfigLSMIO.writeBufferSize,
                       "write buffer size (default: 128M)");
        app.add_option("--lsmio-fsize", lsmio::gConfigLSMIO.writeFileSize,
                       "first-level file size (default: 8x write buffer size)");
        app.add_flag("--lsmio-prealloc", lsmio::gConfigLSMIO.preAllocate,
                     "enable file pre-allocation (uses write buffer size)");
        app.add_flag("--lsmio-disable-agg-dir-structure",
                     lsmio::gConfigLSMIO.disableAggDirStructure,
                     "disable the per-rank aggregation directory structure");
        app.add_option("--lsmio-pool", lsmio::gConfigLSMIO.filePoolSize,
                       "number of pre-allocated files (default: 4)");

        std::map<std::string, lsmio::MemtableType> memtableMap{
            {"vector-no-sort", lsmio::MemtableType::VectorNoSort},
            {"vector-sort", lsmio::MemtableType::VectorSort},
            {"map", lsmio::MemtableType::Map},
            {"btree", lsmio::MemtableType::BTree}};

        app.add_option("--lsmio-memtable", lsmio::gConfigLSMIO.memtable,
                       "memtable implementation to use: vector-no-sort, vector-sort, map, btree "
                       "(default: map)")
            ->transform(CLI::CheckedTransformer(memtableMap, CLI::ignore_case));
        app.add_option("--lsmio-max-key", lsmio::gConfigLSMIO.maxKeyLen,
                       "maximum accepted key length in bytes (default: 256K)");
        app.add_flag("--lsmio-manual-offset,!--lsmio-no-manual-offset",
                     lsmio::gConfigLSMIO.manualOffset,
                     "bypass tellp() and manually track offsets (default: true)");
        app.add_flag("--lsmio-footer-index,!--lsmio-no-footer-index",
                     lsmio::gConfigLSMIO.footerIndex,
                     "append the Dense Index Footer to the SSTable (default: true)");
        app.add_option("--lsmio-wbuffer-num", lsmio::gConfigLSMIO.writeBufferNumber,
                       "number of write buffers (default: 4)");
        app.add_flag("--lsmio-autotune,!--lsmio-no-autotune",
                     lsmio::gConfigLSMIO.autoTuneParameters,
                     "enable filesystem auto-tuning (default: false)");
        app.add_flag(
            "--lsmio-read-only,--lsmio-readonly,--lsmio-ro,"
            "!--lsmio-no-read-only,!--lsmio-no-readonly,!--lsmio-no-ro",
            lsmio::gConfigLSMIO.readOnly,
            "open store in read-only mode during read operations (default: true)");

        app.add_flag("--read-shift", gConfigBM.readShift,
                     "read the data of a peer rank on another node (needs -m, refused with -c, "
                     "and the executable must support it)");
        CLI::Option *read_shift_nodes_option = app.add_option(
            "--read-shift-nodes", gConfigBM.readShiftNodes,
            "simulate this many nodes when mapping peers (>= 1; needs --read-shift)");
        app.add_flag("--per-rank-path", gConfigBM.perRankPath,
                     "give every MPI rank its own store path, suffix .mpirank<N> (needs -m, "
                     "refused with -c)");

        std::map<std::string, lsmio::Durability> durabilityMap{
            {"engine", lsmio::Durability::Engine}, {"page-cache", lsmio::Durability::PageCache}};
        app.add_option("--lsmio-durability", lsmio::gConfigLSMIO.durability,
                       "durability mode of the RocksDB and LevelDB stores: engine, page-cache "
                       "(default: engine; page-cache is refused with -e/--sync)")
            ->transform(CLI::CheckedTransformer(durabilityMap, CLI::ignore_case));

        app.parse(argc, argv);

        lsmio::gConfigLSMIO.mpiAggType =
            flag_mpi_io_world ? lsmio::MPIAggType::Entire : lsmio::MPIAggType::Shared;

        lsmio::gConfigLSMIO.storageType = lsmio::StorageType::NativeDB;
        if (flag_use_leveldb) lsmio::gConfigLSMIO.storageType = lsmio::StorageType::LevelDB;
        if (flag_use_rocksdb) lsmio::gConfigLSMIO.storageType = lsmio::StorageType::RocksDB;

        if (gConfigBM.fileName.empty()) {
            throw std::runtime_error("ERROR: Output file is required.");
        }
        if (gConfigBM.valueSize < 8) {
            throw std::runtime_error("ERROR: Value-size has to be >= 8.");
        }
        if (lsmio::gConfigLSMIO.transferSize < lsmio::gConfigLSMIO.blockSize) {
            throw std::runtime_error("ERROR: Transfer-size has to be >= block-size.");
        }
        if (lsmio::gConfigLSMIO.getMaxValueLen() == 0) {
            throw std::runtime_error(
                "ERROR: --lsmio-wbuffer is too small: it must exceed --lsmio-max-key plus 1M of "
                "record overhead.");
        }
        // Argv-only refusals: every rank refuses identically before MPI starts.
        if (lsmio::gConfigLSMIO.durability == lsmio::Durability::PageCache &&
            lsmio::gConfigLSMIO.useSync) {
            throw std::runtime_error(
                "--lsmio-durability page-cache cannot be combined with -e/--sync.");
        }
        if (gConfigBM.perRankPath && !gConfigBM.useMPIBarrier) {
            throw std::runtime_error("--per-rank-path requires -m/--mpi-barrier.");
        }
        if (gConfigBM.perRankPath && gConfigBM.enableCollectiveIO) {
            throw std::runtime_error("--per-rank-path cannot be combined with -c/--collective-io.");
        }
        if (gConfigBM.readShift && !gConfigBM.useMPIBarrier) {
            throw std::runtime_error("--read-shift requires -m/--mpi-barrier.");
        }
        if (gConfigBM.readShift && gConfigBM.enableCollectiveIO) {
            throw std::runtime_error("--read-shift cannot be combined with -c/--collective-io.");
        }
        if (read_shift_nodes_option->count() > 0 && !gConfigBM.readShift) {
            throw std::runtime_error("--read-shift-nodes requires --read-shift.");
        }
        if (read_shift_nodes_option->count() > 0 && gConfigBM.readShiftNodes < 1) {
            throw std::runtime_error("--read-shift-nodes must be >= 1.");
        }
    } catch (const CLI::ParseError &e) {
        exit(app.exit(e));
    } catch (std::runtime_error &e) {
        std::cerr << "ERROR: " << e.what() << std::endl;
        std::cerr << app.help() << std::flush;
        exit(1);
    } catch (...) {
        std::cerr << "ERROR: Unknown" << std::endl;
        exit(2);
    }

    if (gConfigBM.verbose) {
        lsmio::initLSMIODebug(argv[0]);
    } else {
        lsmio::initLSMIORelease(argv[0]);
    }

    if (gConfigBM.debug) {
        signal(SIGSEGV, lsmio::handlerSIGSEGV);
    }

    if (gConfigBM.useMPIBarrier || gConfigBM.enableCollectiveIO) {
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
        } else {
            mpiSize = mpiWorldSize;
            mpiRank = mpiWorldRank;
        }

        LOG(INFO) << "BMBase::beginMain: MPI Barrier enabled: "
                  << " mpiSize: " << mpiSize << " mpiRank: " << mpiRank << " pName: " << pName
                  << std::endl;
    }

    if (useMPI && mpiRank != 0) {
        LOG(INFO) << "BMBase::beginMain: MPI is rank: " << mpiRank << ". Skipping options print."
                  << std::endl;
    } else {
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
