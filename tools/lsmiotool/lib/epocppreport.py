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

"""Reports of the epocpp workload (`run epocpp backends`), from its archive.

An arm's archive,
<dest>/outputs-<arm>/<nodes>/<date>/out-<arm>-<rf>-<bs>-<date>-<host>-r<NN>.txt,
holds one EPOCpp output per run (a combination runs --repeats times). Its report,
outputs-<arm>/epocpp-report.csv, has a row per node count, combination and metric:

    N,Stripes,BlockSize,Metric,Best,Mean,Worst,Runs,PayloadBytes,DataBytes,DataCheck,Effective,StallFactor

- A wall-time arm (epocpp-baseline, epocpp-<backend>) has a 'runtime' row: Best is the
  Min() of EPOCpp's Runtime over the runs (seconds), Mean their mean, Worst their Max().
- A bandwidth arm (epocpp-<backend>-bw) has 'write' and 'read' rows from
  lsmio::Benchmark's summaries: Best is the Max() of the runs' max MiB/s, Mean the
  Max() of their mean MiB/s, Worst the Min() of their min MiB/s. Best is thus the
  fastest single dump; Effective is the Max() over the runs of a run's whole rate (its
  dumps' MiB over their total time, from the per-dump iwrite/iread rows), the rate a
  run's wall time reflects (exactly, for an epocpp whose Runtime covers every dump:
  from 2026-10-20), and StallFactor is Best / Effective: near 1 when the dumps take
  alike, large when some dumps stall. Best and Effective may come from different
  runs. Both are empty for a wall-time arm, and for a run whose per-dump rows do not
  match its summary's iteration count (one output block per run, as the deck has).
- PayloadBytes is what the runs must have written (a bandwidth arm's write summary; for
  a wall-time arm a lower bound from the archived deck: every particle's positions,
  momenta and id in every dump), DataBytes the fewest bytes a run left on disk (the
  most, for the baseline), and DataCheck 'ok' when every run covers the payload (the
  baseline: no run wrote anything), 'short' (or for the baseline 'unexpected') when
  one did not, 'unknown' when a run has no byte count.

<dest>/epocpp-cost.csv has each backend's I/O cost per node count and combination: the
Min() of its Runtime minus the Min() of the no-output baseline's.
"""

import csv
import math
import os
import re
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

from lsmiotool.lib.benchmarks import EpocppAdapter

ARM_REPORT_FILE = "epocpp-report.csv"
COST_REPORT_FILE = "epocpp-cost.csv"
DECK_FILE = "input.deck"
REPORT_HEADER = (
    "N",
    "Stripes",
    "BlockSize",
    "Metric",
    "Best",
    "Mean",
    "Worst",
    "Runs",
    "PayloadBytes",
    "DataBytes",
    "DataCheck",
    "Effective",
    "StallFactor",
)
# The header before Effective and StallFactor, still read (a report made then)
_LEGACY_REPORT_HEADER = REPORT_HEADER[:-2]
COST_HEADER = (
    "N",
    "Stripes",
    "BlockSize",
    "Backend",
    "BestRuntime",
    "BaselineBestRuntime",
    "IOCost",
)
BASELINE_ARM = "epocpp-baseline"
# epocpp-cost.csv lists backends in run order (arms.DEFAULT_EPOCPP_BACKENDS)
BACKEND_ORDER: Tuple[str, ...] = ("posix", "adios2", "plugin", "native")
# The 6 combinations in run order (RunPlanner.ORDERED_COMBINATIONS)
COMBINATION_ORDER: Tuple[Tuple[int, str], ...] = (
    (4, "1M"),
    (4, "64K"),
    (4, "8M"),
    (16, "1M"),
    (16, "64K"),
    (16, "8M"),
)

_OUT_RE = re.compile(
    r"^out-(?P<arm>epocpp-[a-z0-9-]+?)-(?P<rf>\d+)-(?P<bs>\d+[KM])-"
    r"(?P<date>\d{4}-\d{2}-\d{2})-(?P<host>.+)-r(?P<rep>\d+)\.txt$"
)
_DATA_RE = re.compile(
    r"^lsmiotool: data bytes = (\d+) allocated = (\d+) files = (\d+)\s*$", re.M
)
# A per-dump row of lsmio::Benchmark: access,bw,bw,bw,MiB,ops,1
_ITERATION_RE = re.compile(
    r"^(iwrite|iread),([0-9.eE+-]+),[0-9.eE+-]+,[0-9.eE+-]+,([0-9.eE+-]+),\d+,\d+\s*$",
    re.M,
)
_SUMMARY_RE = re.compile(
    r"^(write|read),([0-9.eE+-]+),([0-9.eE+-]+),([0-9.eE+-]+),([0-9.eE+-]+),(\d+),(\d+)\s*$",
    re.M,
)


class Summary(NamedTuple):
    """One lsmio::Benchmark summary line (MiB/s and totals)."""

    max: float
    min: float
    mean: float
    mib: float
    ops: int
    iterations: int


class RunResult(NamedTuple):
    """What one archived EPOCpp run reported."""

    runtime: Optional[float]
    data_bytes: Optional[int]
    write: Optional[Summary]
    read: Optional[Summary]
    # The run's whole write/read rate in MiB/s: its dumps' MiB over their total time;
    # None without per-dump rows or with a dump of no rate
    write_effective: Optional[float] = None
    read_effective: Optional[float] = None


def _effective(f_dumps: List[Tuple[float, float]]) -> Optional[float]:
    """Total MiB over total seconds of (MiB/s, MiB) dumps; None if any has no rate."""
    if not f_dumps or any(f_bw <= 0 for f_bw, _ in f_dumps):
        return None
    f_seconds = math.fsum(f_mib / f_bw for f_bw, f_mib in f_dumps)
    return (
        math.fsum(f_mib for _, f_mib in f_dumps) / f_seconds if f_seconds > 0 else None
    )


def parseRunLog(f_text: str) -> RunResult:
    """A run's Runtime, the bytes lsmiotool counted and the write/read summaries."""
    f_data = _DATA_RE.findall(f_text)
    f_summaries: Dict[str, Summary] = {}
    for f_m in _SUMMARY_RE.finditer(f_text):
        f_summaries[f_m.group(1)] = Summary(
            float(f_m.group(2)),
            float(f_m.group(3)),
            float(f_m.group(4)),
            float(f_m.group(5)),
            int(f_m.group(6)),
            int(f_m.group(7)),
        )
    f_dumps: Dict[str, List[Tuple[float, float]]] = {"iwrite": [], "iread": []}
    for f_m in _ITERATION_RE.finditer(f_text):
        f_dumps[f_m.group(1)].append((float(f_m.group(2)), float(f_m.group(3))))

    def _rate(f_op: str) -> Optional[float]:
        # Every dump the summary counted, or no rate: a missing row would hide its time
        f_summary = f_summaries.get(f_op)
        f_rows = f_dumps["i" + f_op]
        if f_summary is None or len(f_rows) != f_summary.iterations:
            return None
        return _effective(f_rows)

    return RunResult(
        EpocppAdapter.runtimeOf(f_text),
        int(f_data[-1][0]) if f_data else None,
        f_summaries.get("write"),
        f_summaries.get("read"),
        _rate("write"),
        _rate("read"),
    )


def collectArmRuns(f_arm_dir: str) -> Dict[Tuple[int, int, str], List[RunResult]]:
    """Every run of an arm's archive, by (nodes, stripes, block size)."""
    f_runs: Dict[Tuple[int, int, str], List[RunResult]] = {}
    if not os.path.isdir(f_arm_dir):
        return f_runs
    for f_node in os.listdir(f_arm_dir):
        f_node_dir = os.path.join(f_arm_dir, f_node)
        if not f_node.isdigit() or not os.path.isdir(f_node_dir):
            continue
        for f_date in sorted(os.listdir(f_node_dir)):
            f_date_dir = os.path.join(f_node_dir, f_date)
            if not os.path.isdir(f_date_dir) or os.path.islink(f_date_dir):
                continue
            for f_name in sorted(os.listdir(f_date_dir)):
                f_m = _OUT_RE.match(f_name)
                f_path = os.path.join(f_date_dir, f_name)
                if f_m is None or os.path.islink(f_path) or not os.path.isfile(f_path):
                    continue
                with open(f_path, encoding="utf-8", errors="replace") as f_f:
                    f_result = parseRunLog(f_f.read())
                f_runs.setdefault(
                    (int(f_node), int(f_m.group("rf")), f_m.group("bs")), []
                ).append(f_result)
    return f_runs


def deckPayloadBytes(f_deck: str) -> Optional[int]:
    """A lower bound of what a run of f_deck writes: every particle's 2D position,
    3 momenta and id (6 x 8 bytes) in every dump; 0 when the deck never dumps. None when
    the deck is not one lsmiotool filled in (two_stream.deck.in)."""

    def _value(f_key: str) -> Optional[str]:
        f_m = re.search(rf"^\s*{f_key}\s*=\s*(\S+)\s*$", f_deck, re.M)
        return f_m.group(1) if f_m else None

    try:
        f_nx = int(_value("nx") or "")
        f_nppc = int(_value("nppc") or "")
        f_nsteps = int(_value("nsteps") or "")
        f_snapshot = int(_value("nstep_snapshot") or "")
    except ValueError:
        return None
    if _value("ny") not in ("nx", str(f_nx)):
        return None
    f_first = _value("dump_first") == "T"
    f_last = _value("dump_last") == "T"
    if f_snapshot <= 0:
        f_dumps = int(f_first) + int(f_last and f_nsteps > 0)
    else:
        f_dumps = (
            f_nsteps // f_snapshot
            + int(f_first)
            + int(f_last and f_nsteps % f_snapshot != 0)
        )
    f_species = len(re.findall(r"^\s*begin:species\s*$", f_deck, re.M))
    return f_species * f_nx * f_nx * f_nppc * 6 * 8 * f_dumps


def _number(f_value: float, f_digits: int) -> str:
    return f"{f_value:.{f_digits}f}"


def _orderKey(f_key: Tuple[int, int, str]) -> Tuple[int, int]:
    f_n, f_rf, f_bs = f_key
    f_combo = (f_rf, f_bs)
    return (
        f_n,
        COMBINATION_ORDER.index(f_combo)
        if f_combo in COMBINATION_ORDER
        else len(COMBINATION_ORDER),
    )


def _dataCheck(
    f_payload: Optional[int],
    f_data: Optional[int],
    f_baseline: bool,
    f_all_counted: bool = True,
) -> str:
    # A run without its byte count leaves the check open
    if f_data is None or not f_all_counted:
        return "unknown"
    if f_baseline:
        return "ok" if f_data == 0 else "unexpected"
    if f_payload is None:
        return "unknown"
    return "ok" if f_data >= f_payload else "short"


def armReportRows(f_arm_dir: str) -> List[List[str]]:
    """The rows of an arm's epocpp-report.csv (without the header)."""
    f_arm = os.path.basename(os.path.normpath(f_arm_dir))[len("outputs-") :]
    f_bandwidth = f_arm.endswith("-bw")
    f_baseline = f_arm == BASELINE_ARM
    f_rows: List[List[str]] = []
    f_deck_payload: Dict[int, Optional[int]] = {}
    for f_key, f_runs in sorted(
        collectArmRuns(f_arm_dir).items(), key=lambda f_i: _orderKey(f_i[0])
    ):
        f_n, f_rf, f_bs = f_key
        if f_n not in f_deck_payload:
            f_deck_path = os.path.join(f_arm_dir, str(f_n), DECK_FILE)
            f_deck_payload[f_n] = None
            if os.path.isfile(f_deck_path) and not os.path.islink(f_deck_path):
                with open(f_deck_path, encoding="utf-8", errors="replace") as f_f:
                    f_deck_payload[f_n] = deckPayloadBytes(f_f.read())
        f_sizes = [f_r.data_bytes for f_r in f_runs if f_r.data_bytes is not None]
        # The run that wrote the least must cover the payload; the baseline's that
        # wrote the most must have written nothing
        f_data = (max(f_sizes) if f_baseline else min(f_sizes)) if f_sizes else None
        f_counted = len(f_sizes) == len(f_runs)
        f_common = [str(f_n), str(f_rf), f_bs]
        if f_bandwidth:
            for f_op in ("write", "read"):
                f_sums = [getattr(f_r, f_op) for f_r in f_runs if getattr(f_r, f_op)]
                if not f_sums:
                    continue
                f_payload = (
                    int(round(max(f_s.mib for f_s in f_sums) * 1024 * 1024))
                    if f_op == "write"
                    else None
                )
                f_best = max(f_s.max for f_s in f_sums)
                f_rates = [
                    f_e
                    for f_e in (getattr(f_r, f_op + "_effective") for f_r in f_runs)
                    if f_e is not None
                ]
                f_eff = max(f_rates) if f_rates else None
                f_rows.append(
                    f_common
                    + [
                        f_op,
                        _number(f_best, 2),
                        _number(max(f_s.mean for f_s in f_sums), 2),
                        _number(min(f_s.min for f_s in f_sums), 2),
                        str(len(f_sums)),
                        "" if f_payload is None else str(f_payload),
                        "" if f_data is None else str(f_data),
                        _dataCheck(f_payload, f_data, False, f_counted)
                        if f_op == "write"
                        else "",
                        "" if f_eff is None else _number(f_eff, 2),
                        "" if not f_eff else _number(f_best / f_eff, 2),
                    ]
                )
        else:
            f_times = [f_r.runtime for f_r in f_runs if f_r.runtime is not None]
            if not f_times:
                continue
            f_payload = 0 if f_baseline else f_deck_payload[f_n]
            f_rows.append(
                f_common
                + [
                    "runtime",
                    _number(min(f_times), 6),
                    _number(math.fsum(f_times) / len(f_times), 6),
                    _number(max(f_times), 6),
                    str(len(f_times)),
                    "" if f_payload is None else str(f_payload),
                    "" if f_data is None else str(f_data),
                    _dataCheck(f_payload, f_data, f_baseline, f_counted),
                    "",
                    "",
                ]
            )
    return f_rows


def _writeCsv(f_path: str, f_header: Sequence[str], f_rows: List[List[str]]) -> None:
    f_tmp = f_path + ".partial"
    with open(f_tmp, "w", encoding="utf-8", newline="") as f_f:
        f_writer = csv.writer(f_f, lineterminator="\n")
        f_writer.writerow(f_header)
        f_writer.writerows(f_rows)
    os.replace(f_tmp, f_path)


def writeArmReport(f_arm_dir: str) -> Optional[str]:
    """(Re)write outputs-<arm>/epocpp-report.csv; its path, or None without rows (a
    report left from before is then removed)."""
    f_rows = armReportRows(f_arm_dir)
    f_path = os.path.join(f_arm_dir, ARM_REPORT_FILE)
    if not f_rows:
        if os.path.isfile(f_path):
            os.remove(f_path)
        return None
    _writeCsv(f_path, REPORT_HEADER, f_rows)
    return f_path


def readReport(f_path: str) -> List[Dict[str, str]]:
    with open(f_path, encoding="utf-8", newline="") as f_f:
        f_reader = csv.DictReader(f_f)
        if tuple(f_reader.fieldnames or ()) not in (
            REPORT_HEADER,
            _LEGACY_REPORT_HEADER,
            COST_HEADER,
        ):
            raise ValueError(f"{f_path} is not an epocpp report")
        return list(f_reader)


def _bestRuntimes(f_arm_dir: str) -> Dict[Tuple[int, int, str], float]:
    f_path = os.path.join(f_arm_dir, ARM_REPORT_FILE)
    if not os.path.isfile(f_path):
        return {}
    return {
        (int(f_r["N"]), int(f_r["Stripes"]), f_r["BlockSize"]): float(f_r["Best"])
        for f_r in readReport(f_path)
        if f_r["Metric"] == "runtime"
    }


def writeCostReport(f_scale_dir: str) -> Optional[str]:
    """(Re)write <dest>/epocpp-cost.csv from the arms' reports there; its path, or None
    without the baseline or a wall-time backend arm (a report left from before is then
    removed)."""
    f_path = os.path.join(f_scale_dir, COST_REPORT_FILE)

    def _none() -> None:
        if os.path.isfile(f_path):
            os.remove(f_path)

    f_baseline = _bestRuntimes(os.path.join(f_scale_dir, f"outputs-{BASELINE_ARM}"))
    if not f_baseline:
        return _none()
    f_rows: List[Tuple[Tuple[int, int], str, List[str]]] = []
    for f_entry in sorted(os.listdir(f_scale_dir)):
        f_arm = f_entry[len("outputs-") :] if f_entry.startswith("outputs-") else ""
        if (
            not f_arm.startswith("epocpp-")
            or f_arm == BASELINE_ARM
            or f_arm.endswith("-bw")
        ):
            continue
        f_backend = f_arm[len("epocpp-") :]
        for f_key, f_best in _bestRuntimes(os.path.join(f_scale_dir, f_entry)).items():
            if f_key not in f_baseline:
                continue
            f_n, f_rf, f_bs = f_key
            f_rows.append(
                (
                    _orderKey(f_key),
                    f_backend,
                    [
                        str(f_n),
                        str(f_rf),
                        f_bs,
                        f_backend,
                        _number(f_best, 6),
                        _number(f_baseline[f_key], 6),
                        _number(f_best - f_baseline[f_key], 6),
                    ],
                )
            )
    if not f_rows:
        return _none()
    _writeCsv(
        f_path,
        COST_HEADER,
        [
            f_r
            for _, _, f_r in sorted(
                f_rows,
                key=lambda f_t: (
                    f_t[0],
                    BACKEND_ORDER.index(f_t[1])
                    if f_t[1] in BACKEND_ORDER
                    else len(BACKEND_ORDER),
                    f_t[1],
                ),
            )
        ],
    )
    return f_path


def timeSeries(
    f_arm_dir: str, f_metric: str, f_stripes: int, f_bs: str
) -> Tuple[List[int], List[float]]:
    """(node counts, values) of an arm for 'compare nodes': the Best of 'write'/'read'
    (bandwidth arms), 'runtime' (wall-time arms) or 'cost' (wall-time backend arms, from
    the scale's epocpp-cost.csv); empty when the arm has no such metric."""
    f_points: Dict[int, float] = {}
    if f_metric == "cost":
        f_arm = os.path.basename(os.path.normpath(f_arm_dir))[len("outputs-epocpp-") :]
        f_path = os.path.join(
            os.path.dirname(os.path.normpath(f_arm_dir)), COST_REPORT_FILE
        )
        if os.path.isfile(f_path):
            for f_r in readReport(f_path):
                if (
                    f_r["Backend"] == f_arm
                    and int(f_r["Stripes"]) == f_stripes
                    and f_r["BlockSize"] == f_bs
                ):
                    f_points[int(f_r["N"])] = float(f_r["IOCost"])
    else:
        f_path = os.path.join(f_arm_dir, ARM_REPORT_FILE)
        if os.path.isfile(f_path):
            for f_r in readReport(f_path):
                if (
                    f_r["Metric"] == f_metric
                    and int(f_r["Stripes"]) == f_stripes
                    and f_r["BlockSize"] == f_bs
                ):
                    f_points[int(f_r["N"])] = float(f_r["Best"])
    f_nodes = sorted(f_points)
    return f_nodes, [f_points[f_n] for f_n in f_nodes]
