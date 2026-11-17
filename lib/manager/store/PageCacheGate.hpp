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

#pragma once

// Verified-build gate of the page-cache durability mode (INV-20).
//
// Internal header: it lives under lib/, never under include/lsmio/**. The stores include it and
// ask pageCacheAdmitted() once, in their constructor, before they touch a file. The test
// admission seam (INV-20b) is declared in PageCacheGateOverride.hpp, which this header does not
// include, so only tests and PageCacheGate.cpp can reach it.

#include <rocksdb/version.h>

#include <lsmio/lsmio.hpp>
#include <optional>
#include <string>
#include <tuple>
#include <vector>

// 1 exactly when the RocksDB headers report a version whose file-system classes were read and
// found to carry the no-sync wrapper's interface (9.11.2 and 10.6.2), else 0. On every other
// version the wrapper is compiled out and the RocksDB store refuses page-cache (INV-20, "Builds
// without the wrapper").
#if (ROCKSDB_MAJOR == 9 && ROCKSDB_MINOR == 11 && ROCKSDB_PATCH == 2) || \
    (ROCKSDB_MAJOR == 10 && ROCKSDB_MINOR == 6 && ROCKSDB_PATCH == 2)
#define LSMIO_ROCKSDB_NOSYNC_FS 1
#else
#define LSMIO_ROCKSDB_NOSYNC_FS 0
#endif

namespace lsmio {

inline constexpr bool kRocksNoSyncCompiledIn = (LSMIO_ROCKSDB_NOSYNC_FS != 0);

/** Identity of a storage library build; `patch` is -1 for LevelDB (its header has no patch). */
struct LibraryBuild {
    int major;
    int minor;
    int patch;
    std::string platform;
};

inline bool operator==(const LibraryBuild &f_a, const LibraryBuild &f_b) {
    return std::tie(f_a.major, f_a.minor, f_a.patch, f_a.platform) ==
           std::tie(f_b.major, f_b.minor, f_b.patch, f_b.platform);
}

/** One verified-build table entry: the engine, the exact build and the evidence that admitted it. */
struct VerifiedBuild {
    lsmio::StorageType engine;
    LibraryBuild build;
    std::string evidence;
};

// Pure functions: no global state, testable with synthetic data.

/** True when the engine's no-sync wrapper is part of this build (LevelDB always, RocksDB per macro). */
bool pageCacheWrapperCompiledIn(lsmio::StorageType f_engine);

/** "<os>-<arch>" of the compiler's target, from predefined macros ("unknown" parts when unrecognised). */
std::string compiledPlatform();

/** Parses exactly "<int>.<int>.<int>" (digits only); anything else is nullopt. */
std::optional<LibraryBuild> parseRocksVersion(const std::string &f_version,
                                              const std::string &f_platform);

/** True iff an entry has the same engine and exactly the same build. */
bool buildListed(const std::vector<VerifiedBuild> &f_table, lsmio::StorageType f_engine,
                 const LibraryBuild &f_build);

/** Run-time absent or equal: the compile-time build; a disagreement: nullopt. */
std::optional<LibraryBuild> resolveBuild(const LibraryBuild &f_compile_time,
                                         const std::optional<LibraryBuild> &f_run_time);

/** True iff a build was resolved and it is listed; a disagreement (nullopt) is never verified. */
bool verifiedFor(const std::vector<VerifiedBuild> &f_table, lsmio::StorageType f_engine,
                 const std::optional<LibraryBuild> &f_running);

/** Text for refusal messages, e.g. "RocksDB 9.11.2 linux-x86_64" or a compile-time/run-time disagreement. */
std::string describeBuild(lsmio::StorageType f_engine, const LibraryBuild &f_compile_time,
                          const std::optional<LibraryBuild> &f_run_time);

// Process functions: compose the pure ones with this build's facts.

/** The build the library was compiled against; throws std::invalid_argument for NativeDB. */
LibraryBuild compileTimeBuild(lsmio::StorageType f_engine);

/** The version the loaded library reports at run time; nullopt when it reports none (LevelDB). */
std::optional<LibraryBuild> runTimeBuild(lsmio::StorageType f_engine);

/** describeBuild() of this process's engine build, for store refusals. */
std::string describeRunningBuild(lsmio::StorageType f_engine);

/** The real verified-build table: the builds admitted by recorded evidence (E2, E2b). */
const std::vector<VerifiedBuild> &verifiedBuildTable();

/** True when the running build is listed in the real table. No test-only behaviour. */
bool pageCacheVerified(lsmio::StorageType f_engine);

/** The seam's decision if one is live (the wrapper must still be compiled in), else pageCacheVerified. */
bool pageCacheAdmitted(lsmio::StorageType f_engine);

}  // namespace lsmio
