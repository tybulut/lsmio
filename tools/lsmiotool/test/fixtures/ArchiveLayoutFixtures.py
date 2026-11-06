#
# Copyright 2026 Serdar Bulut
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived from
#    this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#

"""Rank-log and archive-layout builders shared by the archive and report-format tests.

The layout is '<nodes>/<date>/out-*' rank logs of an LSMIO benchmark. This module is
not a test module: its name matches no discovery pattern.
"""

import os
import re
from typing import Dict, List, Optional

from lsmiotool.lib import data

AGG_HEADER = "access,max(MiB)/s,min(MiB/s),mean(MiB/s),total(MiB),total(Ops),iteration"


def rankLog(
    f_write: Optional[str],
    f_read: Optional[str],
) -> str:
    """Render a bm_* rank log with the given 'write,...'/'read,...' summary lines."""
    f_lines = [
        "BENCHMARK RESULTS: ",
        "",
        "Iteration-WRITE: Native Flush: false BLF: false",
        "accessmax(MiB)/smin(MiB/s)mean(MiB/s)total(MiB)total(Ops)iteration",
        "iwrite,179.48,179.48,179.48,256.00,4096,1",
        "",
    ]
    if f_write is not None:
        f_lines += [
            "Bench-WRITE: Native Flush: false BLF: false",
            AGG_HEADER,
            "------,----------,----------,-----------,-----------,----------,----------",
            f_write,
            "",
        ]
    if f_read is not None:
        f_lines += [
            "Bench-READ: Native Flush: false BLF: false",
            AGG_HEADER,
            "------,----------,----------,-----------,-----------,----------,----------",
            f_read,
            "",
        ]
    return "\n".join(f_lines) + "\n"


def rankValues(f_rank: int, f_salt: int) -> Dict[str, str]:
    """Deterministic, non-trivial per-rank summary lines."""
    f_w = 400.0 + ((f_rank * 37 + f_salt * 11) % 211) + ((f_rank * 13) % 100) / 100.0
    f_r = 1900.0 + ((f_rank * 53 + f_salt * 7) % 307) + ((f_rank * 29) % 100) / 100.0
    return {
        "write": f"write,{f_w:.2f},{f_w - 341.73:.2f},{f_w - 76.68:.2f},2559.96,40960,10",
        "read": f"read,{f_r:.2f},{f_r - 173.08:.2f},{f_r - 72.77:.2f},2559.96,40960,10",
    }


def writeBmtoolLayout(
    f_root: str,
    f_nodes: List[str],
    f_infix: str = "native",
    f_date: str = "2026-10-07",
) -> None:
    """Create '<nodes>/<date>/out-<infix>-<rf>-<bs>-<date>-<host>-<localid>.txt' rank logs."""
    for f_n in f_nodes:
        for f_salt, (f_rf, f_bs) in enumerate(
            (f_rf, f_bs)
            for f_rf in data.BMTOOL_STRIPE_COUNTS
            for f_bs in data.BMTOOL_BLOCK_SIZES
        ):
            for f_rank in range(int(f_n)):
                f_vals = rankValues(f_rank, f_salt + int(f_n))
                f_path = os.path.join(
                    f_root,
                    f_n,
                    f_date,
                    f"out-{f_infix}-{f_rf}-{f_bs}-{f_date}-node{100 + f_rank:03d}-0.txt",
                )
                os.makedirs(os.path.dirname(f_path), exist_ok=True)
                with open(f_path, "w") as f_f:
                    f_f.write(rankLog(f_vals["write"], f_vals["read"]))


def readTree(f_root: str) -> Dict[str, bytes]:
    """Map relative path -> bytes for every report file under f_root."""
    f_out: Dict[str, bytes] = {}
    for f_dir, _f_subdirs, f_files in os.walk(f_root):
        for f_name in f_files:
            if f_name == data.LSM_REPORT_FILE or re.match(
                r"agg-.*-report\.csv$", f_name
            ):
                f_path = os.path.join(f_dir, f_name)
                with open(f_path, "rb") as f_f:
                    f_out[os.path.relpath(f_path, f_root)] = f_f.read()
    return f_out
