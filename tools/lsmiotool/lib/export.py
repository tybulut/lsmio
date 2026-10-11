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

"""Export of completed lsmio run points into bmtool's archive layout.

bmtool archives the raw rank outputs of a run as
    outputs-<arm>[:role]/<nodes>/<YYYY-MM-DD>/out-<infix>-<rf>-<bs>-<YYYY-MM-DD>-<host>-<local>.txt
plus <nodes>/agg-<rf>-<bs>-report.csv and a top-level lsm-report.csv, which is what
`parse` and `compare` read. lsmiotool keeps each rank's output in the run root as
points/<point>/logs/c<rf>_b<bs>/rank_<n>.log; this module copies those into that layout.
"""

import os
import shutil
from datetime import datetime, timezone
from typing import Any, List, Optional


class ExportError(Exception):
    """Raised when a run point cannot be exported."""


def _fileHost(f_payload: Any, f_rank: int) -> str:
    """<host> of a rank's file: the node's hostname, as bmtool names it. Rank results
    written before 'host' was recorded have only node_rank, a Slurm node index there."""
    f_host = f_payload.get("host")
    if f_host:
        return str(f_host)
    f_node = str(f_payload.get("node_rank", f_rank))
    return f"node{f_node}" if f_node.isdigit() else f_node


def exportPoint(
    f_layout: Any,
    f_evidence_store: Any,
    f_scale_point: Any,
    f_ordinal: int,
    f_combinations: Any,
    f_infix: str,
    f_node_dir: str,
) -> int:
    """Copy one point's rank logs into f_node_dir (replaced if present).

    Returns the number of files written.
    """
    f_tmp_dir = f_node_dir.rstrip(os.sep) + ".partial"
    shutil.rmtree(f_tmp_dir, ignore_errors=True)
    f_written = 0
    try:
        for f_combo in f_combinations:
            f_combo_name = f_layout.combinationName(f_combo)
            f_stripe = getattr(f_combo, "stripe_count")
            f_block = getattr(f_combo, "block_size")
            for f_rank in range(f_scale_point.tasks):
                f_rec = f_evidence_store.readRankResult(
                    f_scale_point, f_rank, f_combo, f_ordinal=f_ordinal
                )
                f_payload = (f_rec.payload if f_rec is not None else None) or {}
                # The recorded path, else the layout's (the run root may have moved)
                f_layout_log = f_layout.pointRankLogPath(
                    f_scale_point, f_rank, f_combo_name, f_ordinal=f_ordinal
                )
                f_log = next(
                    (
                        f_p
                        for f_p in (f_payload.get("log_path"), f_layout_log)
                        if f_p and os.path.isfile(f_p)
                    ),
                    None,
                )
                if f_log is None:
                    raise ExportError(
                        f"Missing rank log for rank {f_rank}, {f_combo_name}: {f_layout_log}"
                    )
                f_date = _recordDate(f_rec)
                f_host = _fileHost(f_payload, f_rank)
                # bmtool's suffix is SLURM_LOCALID, or ALPS_APP_PE (the global rank) on PBS
                f_local = f_payload.get("local_rank")
                f_local = f_rank if f_local is None else f_local
                f_name = f"out-{f_infix}-{f_stripe}-{f_block}-{f_date}-{f_host}-{f_local}.txt"
                f_dest_dir = os.path.join(f_tmp_dir, f_date)
                os.makedirs(f_dest_dir, exist_ok=True)
                f_dest = os.path.join(f_dest_dir, f_name)
                if os.path.exists(f_dest):
                    f_dest = os.path.join(
                        f_dest_dir,
                        f"out-{f_infix}-{f_stripe}-{f_block}-{f_date}-{f_host}-{f_local}-r{f_rank}.txt",
                    )
                shutil.copyfile(f_log, f_dest)
                f_written += 1
        shutil.rmtree(f_node_dir, ignore_errors=True)
        os.makedirs(os.path.dirname(f_node_dir.rstrip(os.sep)), exist_ok=True)
        os.rename(f_tmp_dir, f_node_dir)
    except Exception:
        shutil.rmtree(f_tmp_dir, ignore_errors=True)
        raise
    return f_written


def generateReports(f_archive_dir: str) -> bool:
    """(Re)generate agg-*-report.csv and lsm-report.csv in an archive dir, like bmtool's
    lsmio-parse.sh. Returns True when lsm-report.csv was written."""
    from lsmiotool.lib.output import regenerateLsmioReports

    # Every node dir present: a backends archive accumulates several node counts
    return regenerateLsmioReports(str(f_archive_dir), f_scale=None) is not None


def _recordDate(f_rec: Optional[Any]) -> str:
    f_ts = getattr(f_rec, "created_at_utc", None) if f_rec is not None else None
    if isinstance(f_ts, str) and len(f_ts) >= 10:
        return f_ts[:10]
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
