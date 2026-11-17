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

// INV-20b test admission seam of the page-cache verified-build gate.
//
// Internal header, included only by test/** and by lib/manager/store/PageCacheGate.cpp. No
// benchmark, tool, plugin, manager, POSIX layer or store includes it, and no command-line flag,
// environment variable, LSMIOConfig field or CMake option reaches it.

namespace lsmio {

/** The decision a test imposes on every RocksDB and LevelDB store opened while the override lives. */
enum class GateDecision { Admit, Deny };

/**
 * Scoped override of the gate's decision: while it lives, pageCacheAdmitted() answers from it
 * instead of from the verified-build table (it never overrides a missing wrapper). Its
 * destruction restores the table decision.
 *
 * At most one is live per process: constructing a second one while one is live throws
 * std::logic_error and leaves the first in place. Construct and destroy it only while no store
 * is being opened.
 */
class PageCacheGateOverride {
  public:
    explicit PageCacheGateOverride(GateDecision f_decision);
    ~PageCacheGateOverride();

    PageCacheGateOverride(const PageCacheGateOverride &) = delete;
    PageCacheGateOverride &operator=(const PageCacheGateOverride &) = delete;
};

}  // namespace lsmio
