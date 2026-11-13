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

#include "ReadShift.hpp"

#include <iterator>
#include <map>

std::vector<ReadShiftPeers> mapReadShift(const std::vector<int>& f_node_id_by_world_rank) {
    const size_t size = f_node_id_by_world_rank.size();

    // local index -> (node id ascending -> world rank): one cycle per local index
    std::map<int, std::map<int, int>> cycles;
    std::map<int, int> ranks_seen_on_node;
    for (size_t rank = 0; rank < size; ++rank) {
        const int node_id = f_node_id_by_world_rank[rank];
        const int local_index = ranks_seen_on_node[node_id]++;
        cycles[local_index][node_id] = static_cast<int>(rank);
    }

    std::vector<ReadShiftPeers> peers(size);
    for (const auto& cycle : cycles) {
        const auto& members = cycle.second;
        for (auto it = members.begin(); it != members.end(); ++it) {
            auto next = std::next(it);
            const int source = (next == members.end()) ? members.begin()->second : next->second;
            peers[static_cast<size_t>(it->second)].source_world_rank = source;
            peers[static_cast<size_t>(source)].sink_world_rank = it->second;
        }
    }
    return peers;
}
