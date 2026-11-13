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

#ifndef _PHASE_TIMELINE_HPP_
#define _PHASE_TIMELINE_HPP_

// C1: one iteration's phase timeline on this process. MPI-free and glog-free, so that the
// benchmark test binary can compile it without the MPI machinery.

#include <cstdint>
#include <string>

enum class PhaseSide { Write, Read };

enum class PhaseBoundary { BeforeOpen, AfterOpen, BeforeClose, AfterClose, AfterDelete };

// Offsets are microseconds since the iteration's reference point (INV-4). A side that did not run
// keeps zeros and side_recorded[side] == false (INV-7).
struct IterationPhases {
    int iteration;                // benchSuite's iter (0-based)
    double bytes;                 // world-total bytes of one side
    int64_t offset_us[2][5] = {};  // [PhaseSide][PhaseBoundary]
    bool side_recorded[2] = {};
};

// One line per recorded side, write first, then read:
//   phase,<write|read>,<iteration>,<bytes>,<beforeOpen>,<afterOpen>,<beforeClose>,<afterClose>,<afterDelete>\n
// <bytes> is printed as an integer with no decimal point. A side that is not recorded has no line,
// so the result is empty when neither side is recorded.
std::string formatPhaseRows(const IterationPhases &f_phases);

#endif  // _PHASE_TIMELINE_HPP_
