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

#include "PhaseTimeline.hpp"

#include <fmt/core.h>

std::string formatPhaseRows(const IterationPhases &f_phases) {
    static const char *const side_names[2] = {"write", "read"};
    std::string rows;
    for (int side = 0; side < 2; side++) {
        if (!f_phases.side_recorded[side]) {
            continue;
        }
        const int64_t *offsets = f_phases.offset_us[side];
        rows += fmt::format("phase,{},{},{:.0f},{},{},{},{},{}\n", side_names[side], f_phases.iteration,
                            f_phases.bytes, offsets[static_cast<int>(PhaseBoundary::BeforeOpen)],
                            offsets[static_cast<int>(PhaseBoundary::AfterOpen)],
                            offsets[static_cast<int>(PhaseBoundary::BeforeClose)],
                            offsets[static_cast<int>(PhaseBoundary::AfterClose)],
                            offsets[static_cast<int>(PhaseBoundary::AfterDelete)]);
    }
    return rows;
}
