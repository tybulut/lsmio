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

#include "PageCacheGate.hpp"

#include <leveldb/db.h>

#include <algorithm>
#include <atomic>
#include <stdexcept>
#include <string_view>

#include "PageCacheGateOverride.hpp"

// Platform strings come from preprocessor chains only, so no run-time condition depends on them.
#if defined(__linux__)
#define LSMIO_PLATFORM_OS "linux"
#elif defined(__APPLE__)
#define LSMIO_PLATFORM_OS "darwin"
#else
#define LSMIO_PLATFORM_OS "unknown"
#endif

#if defined(__x86_64__)
#define LSMIO_PLATFORM_ARCH "x86_64"
#elif defined(__APPLE__) && (defined(__aarch64__) || defined(__arm64__))
#define LSMIO_PLATFORM_ARCH "arm64"
#elif defined(__aarch64__)
#define LSMIO_PLATFORM_ARCH "aarch64"
#else
#define LSMIO_PLATFORM_ARCH "unknown"
#endif

namespace lsmio {

namespace {

// State of the INV-20b seam: no override, or the live GateDecision as an int.
constexpr int kNoOverride = -1;
std::atomic<int> g_override_state{kNoOverride};

std::optional<GateDecision> liveOverride() {
    const int state = g_override_state.load();
    if (state == kNoOverride) {
        return std::nullopt;
    }
    return static_cast<GateDecision>(state);
}

// Digits only, at most nine of them (so the value fits an int); anything else is nullopt.
std::optional<int> parseDigits(std::string_view f_text) {
    if (f_text.empty() || f_text.size() > 9) {
        return std::nullopt;
    }
    int value = 0;
    for (const char c : f_text) {
        if (c < '0' || c > '9') {
            return std::nullopt;
        }
        value = value * 10 + (c - '0');
    }
    return value;
}

// "<major>.<minor>[.<patch>] <platform>"; the parse-failure marker (major < 0) reads "unparsable".
std::string formatBuild(const LibraryBuild &f_build) {
    if (f_build.major < 0) {
        return "unparsable";
    }
    std::string text = std::to_string(f_build.major) + "." + std::to_string(f_build.minor);
    if (f_build.patch >= 0) {
        text += "." + std::to_string(f_build.patch);
    }
    return text + " " + f_build.platform;
}

#if LSMIO_ROCKSDB_NOSYNC_FS
// Stands for a run-time version string that did not parse: it can never equal a compile-time
// build (major >= 0), so resolveBuild() reports a disagreement and the store refuses.
const LibraryBuild kUnparsableRocksBuild{-1, -1, -1, "unparsable"};
#endif

}  // namespace

bool pageCacheWrapperCompiledIn(lsmio::StorageType f_engine) {
    if (f_engine == lsmio::StorageType::LevelDB) {
        return true;
    }
    if (f_engine == lsmio::StorageType::RocksDB) {
        return kRocksNoSyncCompiledIn;
    }
    return false;
}

std::string compiledPlatform() {
    return std::string(LSMIO_PLATFORM_OS "-" LSMIO_PLATFORM_ARCH);
}

std::optional<LibraryBuild> parseRocksVersion(const std::string &f_version,
                                              const std::string &f_platform) {
    const std::string_view text(f_version);
    const size_t first_dot = text.find('.');
    if (first_dot == std::string_view::npos) {
        return std::nullopt;
    }
    const size_t second_dot = text.find('.', first_dot + 1);
    if (second_dot == std::string_view::npos) {
        return std::nullopt;
    }
    // A further '.' stays in the patch part, where parseDigits() refuses it.
    const auto major = parseDigits(text.substr(0, first_dot));
    const auto minor = parseDigits(text.substr(first_dot + 1, second_dot - first_dot - 1));
    const auto patch = parseDigits(text.substr(second_dot + 1));
    if (!major || !minor || !patch) {
        return std::nullopt;
    }
    return LibraryBuild{*major, *minor, *patch, f_platform};
}

bool buildListed(const std::vector<VerifiedBuild> &f_table, lsmio::StorageType f_engine,
                 const LibraryBuild &f_build) {
    return std::any_of(f_table.begin(), f_table.end(), [&](const VerifiedBuild &f_entry) {
        return f_entry.engine == f_engine && f_entry.build == f_build;
    });
}

std::optional<LibraryBuild> resolveBuild(const LibraryBuild &f_compile_time,
                                         const std::optional<LibraryBuild> &f_run_time) {
    if (!f_run_time || *f_run_time == f_compile_time) {
        return f_compile_time;
    }
    return std::nullopt;
}

bool verifiedFor(const std::vector<VerifiedBuild> &f_table, lsmio::StorageType f_engine,
                 const std::optional<LibraryBuild> &f_running) {
    return f_running.has_value() && buildListed(f_table, f_engine, *f_running);
}

std::string describeBuild(lsmio::StorageType f_engine, const LibraryBuild &f_compile_time,
                          const std::optional<LibraryBuild> &f_run_time) {
    const std::string engine = lsmio::to_string(f_engine);
    if (f_run_time && !(*f_run_time == f_compile_time)) {
        return engine + " compile-time " + formatBuild(f_compile_time) + ", run-time " +
               formatBuild(*f_run_time) + " (disagree)";
    }
    return engine + " " + formatBuild(f_compile_time);
}

LibraryBuild compileTimeBuild(lsmio::StorageType f_engine) {
    if (f_engine == lsmio::StorageType::RocksDB) {
        return {ROCKSDB_MAJOR, ROCKSDB_MINOR, ROCKSDB_PATCH, compiledPlatform()};
    }
    if (f_engine == lsmio::StorageType::LevelDB) {
        return {leveldb::kMajorVersion, leveldb::kMinorVersion, -1, compiledPlatform()};
    }
    throw std::invalid_argument("compileTimeBuild: no page-cache gate for engine " +
                                lsmio::to_string(f_engine));
}

std::optional<LibraryBuild> runTimeBuild(lsmio::StorageType f_engine) {
#if LSMIO_ROCKSDB_NOSYNC_FS
    if (f_engine == lsmio::StorageType::RocksDB) {
        return parseRocksVersion(rocksdb::GetRocksVersionAsString(true), compiledPlatform())
            .value_or(kUnparsableRocksBuild);
    }
#else
    (void)f_engine;
#endif
    // LevelDB reports no run-time version; on a build without the RocksDB wrapper the store
    // refuses before the version matters.
    return std::nullopt;
}

std::string describeRunningBuild(lsmio::StorageType f_engine) {
    return describeBuild(f_engine, compileTimeBuild(f_engine), runTimeBuild(f_engine));
}

const std::vector<VerifiedBuild> &verifiedBuildTable() {
    // A build enters this table only on recorded evidence and a human-approved change. Each
    // evidence string is repeated in the benchmark/README.md section "Verified page-cache builds".
    static const std::vector<VerifiedBuild> table = {
        {lsmio::StorageType::RocksDB,
         {9, 11, 2, "linux-x86_64"},
         "E2 test form 2026-11-12, branch tybulut/benchmarkpp, base ae90360: RocksDBPageCache.* "
         "(3 tests, [  PASSED  ] 3 tests.) under strace -f: 0 fsync, 0 fdatasync, 0 msync, "
         "63 sync_file_range all flags 0. E2b benchmark form 2026-11-13, same branch and base: "
         "bm_rocksdb -i 2 -k 4096 --lsmio-durability page-cache under strace -f, plain, "
         "--lsmio-wal, --lsmio-mmap and a 3-rank mpirun run: every run exit 0 with its "
         "iwrite/iread rows for both iterations, 0 fsync, 0 fdatasync, 0 msync, 142 "
         "sync_file_range all flags 0; see benchmark/README.md section \"Verified page-cache "
         "builds\""},
        {lsmio::StorageType::LevelDB,
         {1, 23, -1, "linux-x86_64"},
         "E2 test form 2026-11-12, branch tybulut/benchmarkpp, base ae90360: LevelDBPageCache.* "
         "(3 tests, [  PASSED  ] 3 tests.) under strace -f: 0 fsync, 0 fdatasync, 0 msync, "
         "0 sync_file_range. E2b benchmark form 2026-11-13, same branch and base: bm_leveldb -i 2 "
         "-k 4096 --lsmio-durability page-cache under strace -f, plain, --lsmio-wal, --lsmio-mmap "
         "and a 3-rank mpirun run: every run exit 0 with its iwrite/iread rows for both "
         "iterations, 0 fsync, 0 fdatasync, 0 msync, 0 sync_file_range; see benchmark/README.md "
         "section \"Verified page-cache builds\""},
    };
    return table;
}

bool pageCacheVerified(lsmio::StorageType f_engine) {
    if (!pageCacheWrapperCompiledIn(f_engine)) {
        return false;
    }
    return verifiedFor(verifiedBuildTable(), f_engine,
                       resolveBuild(compileTimeBuild(f_engine), runTimeBuild(f_engine)));
}

bool pageCacheAdmitted(lsmio::StorageType f_engine) {
    if (!pageCacheWrapperCompiledIn(f_engine)) {
        return false;
    }
    const std::optional<GateDecision> decision = liveOverride();
    if (decision) {
        const bool admit = (*decision == GateDecision::Admit);
        LOG(WARNING) << "page-cache decision for " << lsmio::to_string(f_engine)
                     << " taken from the test override (" << (admit ? "admit" : "deny")
                     << "), verified-build table not consulted" << std::endl;
        return admit;
    }
    return pageCacheVerified(f_engine);
}

PageCacheGateOverride::PageCacheGateOverride(GateDecision f_decision) {
    int expected = kNoOverride;
    if (!g_override_state.compare_exchange_strong(expected, static_cast<int>(f_decision))) {
        throw std::logic_error("PageCacheGateOverride: an override is already live");
    }
}

PageCacheGateOverride::~PageCacheGateOverride() {
    g_override_state.store(kNoOverride);
}

}  // namespace lsmio
