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

#ifndef _READ_SHIFT_HPP_
#define _READ_SHIFT_HPP_

// C3, MPI-free part: the rank-shifted read mapping and the types of the read source.

#include <string>
#include <vector>

// The writers a rank is connected to by the shift: it reads the store of source_world_rank and its
// own store is read by sink_world_rank.
struct ReadShiftPeers {
    int source_world_rank;
    int sink_world_rank;
};

// Pure function over the node id of every world rank (index = world rank; a node id is any int,
// for example the world rank of the node's leader, or the world rank modulo a simulated node
// count). The local index of a rank is its position among the world ranks with the same node id.
// The ranks with the same local index, ordered by node id ascending, form a cycle: the source of a
// rank is its successor and its sink its predecessor (wrapping). A local index held by one node
// only gives source = sink = the rank itself. Empty input gives an empty result.
std::vector<ReadShiftPeers> mapReadShift(const std::vector<int>& f_node_id_by_world_rank);

// C3, MPI part: computed once per process (INV-14 timing); immutable afterwards. Filled by the
// exchange; declared here so that this MPI-free header holds every C3 type.
struct ReadSource {
    int source_world_rank;         // writer whose store this rank reads (self when no shift);
                                   // also the writer rank of the get permutation (INV-13)
    std::string source_base_path;  // that writer's _lsmioBMPath, per-rank suffix included (INV-14b)
    bool is_self;
    bool same_host;                // processor-name equality (diagnostic)
    int self_ranks_world;          // world sums printed in the header (INV-15)
    int same_host_ranks_world;
};

#endif  // _READ_SHIFT_HPP_
