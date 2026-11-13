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

// No-sync RocksDB file system of the page-cache durability mode (INV-17, INV-19).
//
// Internal header: it lives under lib/, never under include/lsmio/**, so the wrapper types are
// not part of the public interface. The RocksDB store installs noSyncRocksEnv() in its options
// in page-cache mode only.
//
// The wrapper is compiled only for the RocksDB versions whose file-system headers were read
// (LSMIO_ROCKSDB_NOSYNC_FS, PageCacheGate.hpp). On every other version only
// interceptedRocksDBSyncCount() exists, and it returns 0; no RocksDB file-system class is named.

#include <cstdint>

#include "PageCacheGate.hpp"

#if LSMIO_ROCKSDB_NOSYNC_FS
#include <rocksdb/env.h>
#include <rocksdb/file_system.h>

#include <memory>
#endif

namespace lsmio {

// Observation point for tests: how many sync-like calls the wrapper has intercepted (monotonic).
// Writable-file Sync/Fsync/RangeSync, random-RW-file Sync/Fsync and directory
// Fsync/FsyncWithDirOptions each count once per call.
std::uint64_t interceptedRocksDBSyncCount();

#if LSMIO_ROCKSDB_NOSYNC_FS
// The process-lifetime no-sync file system over FileSystem::Default(). Every sync-like call
// becomes a flush or a no-op, and no data is dropped (INV-17). Created on first use and never
// destroyed, so it outlives every DB and DestroyDB that uses it (INV-19).
std::shared_ptr<rocksdb::FileSystem> noSyncRocksFileSystem();

// The process-lifetime Env made over noSyncRocksFileSystem(). Never destroyed (INV-19); the
// result belongs to the library and must never be deleted.
rocksdb::Env* noSyncRocksEnv();
#endif

}  // namespace lsmio
