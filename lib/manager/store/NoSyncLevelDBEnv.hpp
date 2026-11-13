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

// No-sync LevelDB Env of the page-cache durability mode (INV-17, INV-19).
//
// Internal header: it lives under lib/, never under include/lsmio/**, so the wrapper types are
// not part of the public interface. The LevelDB store installs noSyncLevelDBEnv() in its options
// in page-cache mode only.

#include <leveldb/env.h>

#include <cstdint>

namespace lsmio {

// The process-lifetime Env that replaces every WritableFile::Sync() by Flush() (sync replaced by
// flush, data never dropped). It is created on first use and never destroyed, so it outlives
// every DB and every DestroyDB that uses it, also during static destruction (INV-19). The
// result belongs to the library and must never be deleted.
leveldb::Env* noSyncLevelDBEnv();

// Observation point for tests: how many Sync() calls the wrapper has replaced (monotonic).
std::uint64_t interceptedLevelDBSyncCount();

}  // namespace lsmio
