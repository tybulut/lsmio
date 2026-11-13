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

"""Phase report of the LSMIO benchmarks: lsm-phase-report.csv.

A benchmark rank log prints, per suite, a 'Phases: <prefix>' block of
'phase,<side>,<iteration>,<bytes>,<5 offsets in us>' rows (benchmark/PhaseTimeline.cpp)
next to the legacy 'iwrite,'/'iread,' rows. This module parses those rows and derives the
windows of each record (full, open, data, close, delete, legacy) into a separate CSV.
It reads rank logs only; it never touches agg-*-report.csv, lsm-report.csv or
lsm-report.json (INV-22), and it writes nothing when no log holds a phase row (INV-23).
"""

import csv
import os
import re
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

from lsmiotool.lib.data import readBmtoolLines
from lsmiotool.lib.log import Console

LSM_PHASE_REPORT_FILE = "lsm-phase-report.csv"

PHASE_REPORT_COLUMNS: Tuple[str, ...] = (
    "nodes",
    "stripe",
    "block",
    "prefix",
    "iteration",
    "side",
    "bytes",
    "full_us",
    "open_us",
    "data_us",
    "close_us",
    "delete_us",
    "legacy_us",
    "full_mibs",
    "open_mibs",
    "data_mibs",
    "close_mibs",
    "delete_mibs",
    "legacy_mibs",
    "gap_us",
    "legacy_row_us",
    "legacy_check",
    "durability",
    "rank_shift",
    "rank_shift_nodes",
    "rank_shift_self_ranks",
    "rank_shift_same_host_ranks",
    "per_rank_path",
    "rocksdb_version",
    "leveldb_version",
    "leveldb_close_flush",
    "source_log",
)

# Header keys read from a log (first occurrence), as printed by bm_base.cpp and the engines
_HEADER_KEYS = frozenset(
    (
        "durability",
        "rankShift",
        "rankShiftNodes",
        "rankShiftSelfRanks",
        "rankShiftSameHostRanks",
        "perRankPath",
        "rocksdbVersion",
        "leveldbVersion",
        "leveldbCloseFlush",
        "mpi-barrier",
    )
)

_SIDES = ("write", "read")
_LEGACY_ROW_SIDE = {"iwrite": "write", "iread": "read"}
_INTEGER = re.compile(r"-?\d+")
_NUMBER = re.compile(r"\d+(\.\d+)?")
_SIZE = re.compile(r"(\d+)([KMGkmg]?)")
_SIZE_FACTOR = {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}

# Legacy cross-check: the 'iwrite,'/'iread,' bandwidth and MiB are printed
# with '{:.2f}' (lib/benchmark.cpp), so each true value lies within half of 0.01 of the figure.
# The window must lie in the exact interval of durations those figures allow, widened by 1 ms
# of barrier-exit skew on each side.
_LEGACY_HALF_STEP = 0.005
_LEGACY_SLACK_US = 1000

# Marks a block or legacy section that is skipped because it repeats an earlier one
_SKIPPED = object()


class PhaseRecord(NamedTuple):
    """One 'phase,' row: the five boundary offsets are microseconds since the run start."""

    prefix: str
    side: str
    iteration: int
    bytes_text: str
    before_open: int
    after_open: int
    before_close: int
    after_close: int
    after_delete: int


class LegacyRow(NamedTuple):
    """The bandwidth and total MiB of one 'iwrite,'/'iread,' row (None when unreadable)."""

    bw: Optional[float]
    mib: Optional[float]


class ParsedLog:
    """What one rank log holds: header values, phase records and legacy rows."""

    def __init__(self) -> None:
        self.m_headers: Dict[str, str] = {}
        self.m_mpi_disabled = False
        # Phases: block prefixes in log order; records per prefix keyed by (iteration, side)
        self.m_blocks: List[str] = []
        self.m_records: Dict[str, Dict[Tuple[int, str], PhaseRecord]] = {}
        # Legacy rows per (side, prefix), in log order
        self.m_legacy: Dict[Tuple[str, str], List[LegacyRow]] = {}

    def hasRecords(self) -> bool:
        """Return True when the log holds at least one phase record."""
        return any(self.m_records.values())

    def recordSet(self) -> Dict[Tuple[str, int, str], PhaseRecord]:
        """Return all records keyed by (prefix, iteration, side), for comparing two logs."""
        return {
            (f_prefix, f_iteration, f_side): f_record
            for f_prefix, f_by_key in self.m_records.items()
            for (f_iteration, f_side), f_record in f_by_key.items()
        }


def _phasePrefix(f_text: str) -> str:
    """Return the prefix of a 'Phases:' or 'Iteration-*:' header: the text after the colon."""
    return f_text.partition(":")[2].strip()


def _parseRecord(f_prefix: str, f_fields: Sequence[str]) -> Optional[PhaseRecord]:
    """Build a record from the comma fields of a 'phase,' row, or None when malformed."""
    if len(f_fields) != 9 or f_fields[1] not in _SIDES:
        return None
    if _INTEGER.fullmatch(f_fields[2]) is None or _NUMBER.fullmatch(f_fields[3]) is None:
        return None
    if any(_INTEGER.fullmatch(f_field) is None for f_field in f_fields[4:]):
        return None
    f_offsets = [int(f_field) for f_field in f_fields[4:]]
    return PhaseRecord(
        f_prefix, f_fields[1], int(f_fields[2]), f_fields[3], *f_offsets
    )


def _parseLegacyRow(f_fields: Sequence[str]) -> LegacyRow:
    """Read bw (field 1) and MiB (field 4) of an 'iwrite,'/'iread,' row."""
    if len(f_fields) < 5:
        return LegacyRow(None, None)
    f_bw, f_mib = (
        float(f_field) if _NUMBER.fullmatch(f_field) else None
        for f_field in (f_fields[1], f_fields[4])
    )
    return LegacyRow(f_bw, f_mib)


def parseRankLog(f_lines: Sequence[str], f_source: str = "log") -> ParsedLog:
    """Parse the lines of one rank log (see data.readBmtoolLines).

    Malformed or repeated content is skipped with a warning naming f_source; nothing raises.
    The legacy block opened by 'Iteration-WRITE:'/'Iteration-READ:' stays open across the
    'access,...' and '------,...' header lines until 'Bench-*:' or the next block header.
    """
    f_parsed = ParsedLog()
    f_block: object = None  # current Phases prefix, None before any block, or _SKIPPED
    f_legacy: object = None  # current (side, prefix), None outside a block, or _SKIPPED
    for f_line in f_lines:
        f_text = f_line.strip()
        f_key, _, f_value = f_text.partition(":")
        if f_text == "MPI: Disabled":
            f_parsed.m_mpi_disabled = True
        elif f_key in _HEADER_KEYS:
            f_parsed.m_headers.setdefault(f_key, f_value.strip())
        elif f_key == "Phases":
            f_legacy = None
            f_prefix = _phasePrefix(f_text)
            if f_prefix in f_parsed.m_records:
                Console.warning(f"{f_source}: repeated 'Phases: {f_prefix}' block ignored")
                f_block = _SKIPPED
            else:
                f_parsed.m_blocks.append(f_prefix)
                f_parsed.m_records[f_prefix] = {}
                f_block = f_prefix
        elif f_key in ("Iteration-WRITE", "Iteration-READ"):
            f_side = f_key.partition("-")[2].lower()
            f_legacy_key = (f_side, _phasePrefix(f_text))
            if f_legacy_key in f_parsed.m_legacy:
                Console.warning(f"{f_source}: repeated '{f_text}' block ignored")
                f_legacy = _SKIPPED
            else:
                f_parsed.m_legacy[f_legacy_key] = []
                f_legacy = f_legacy_key
        elif f_key in ("Bench-WRITE", "Bench-READ"):
            f_legacy = None
        elif f_text.startswith("phase,"):
            if f_block is None:
                Console.warning(f"{f_source}: phase row before any 'Phases:' block ignored")
            elif f_block is not _SKIPPED:
                _addRecord(f_parsed, str(f_block), f_text, f_source)
        elif isinstance(f_legacy, tuple):
            f_fields = f_text.split(",")
            if _LEGACY_ROW_SIDE.get(f_fields[0]) == f_legacy[0]:
                f_parsed.m_legacy[f_legacy].append(_parseLegacyRow(f_fields))
    return f_parsed


def _addRecord(f_parsed: ParsedLog, f_prefix: str, f_text: str, f_source: str) -> None:
    """Add one 'phase,' row to its block; a malformed or repeated row is skipped."""
    f_record = _parseRecord(f_prefix, f_text.split(","))
    if f_record is None:
        Console.warning(f"{f_source}: malformed phase row skipped: {f_text}")
        return
    f_by_key = f_parsed.m_records[f_prefix]
    f_key = (f_record.iteration, f_record.side)
    if f_key in f_by_key:
        Console.warning(f"{f_source}: repeated phase row skipped: {f_text}")
        return
    f_by_key[f_key] = f_record


def _recordOrder(f_key: Tuple[int, str]) -> Tuple[int, int]:
    """Sort key of (iteration, side): iteration ascending, write before read."""
    return (f_key[0], _SIDES.index(f_key[1]))


def _mibs(f_bytes: float, f_window_us: int) -> str:
    """Return bytes over the window in MiB/s with two decimals; empty for a window <= 0."""
    if f_window_us <= 0:
        return ""
    return f"{f_bytes / f_window_us / 1.024 / 1.024:.2f}"


def _legacyInterval(f_bw: float, f_mib: float) -> Tuple[float, float]:
    """Return (lo, hi) in us: the durations whose bw and MiB round to the printed figures.

    The duration is MiB x 10^6 / bw, so lo pairs the smallest MiB with the largest bw and hi
    the largest MiB with the smallest bw; hi is infinite when the smallest bw reaches 0.
    """
    f_lo = max(0.0, f_mib - _LEGACY_HALF_STEP) * 10 ** 6 / (f_bw + _LEGACY_HALF_STEP)
    if f_bw <= _LEGACY_HALF_STEP:
        return (f_lo, float("inf"))
    return (f_lo, (f_mib + _LEGACY_HALF_STEP) * 10 ** 6 / (f_bw - _LEGACY_HALF_STEP))


def _legacyChecks(
    f_parsed: ParsedLog, f_prefix: str, f_side: str, f_records: Sequence[PhaseRecord]
) -> List[Tuple[str, str]]:
    """Return (legacy_row_us, legacy_check) per record, which are in iteration order."""
    f_barriers = (
        f_parsed.m_headers.get("mpi-barrier") == "1" or f_parsed.m_mpi_disabled
    )
    if not f_barriers:
        return [("", "n/a") for _ in f_records]
    f_rows = f_parsed.m_legacy.get((f_side, f_prefix), [])
    if len(f_rows) != len(f_records):
        return [("", "unpaired") for _ in f_records]
    f_results = []
    for f_record, f_row in zip(f_records, f_rows):
        if f_row.bw is None or f_row.mib is None or f_row.bw <= 0 or f_row.mib <= 0:
            f_results.append(("", "n/a"))
            continue
        f_row_us = f_row.mib * 10 ** 6 / f_row.bw
        f_legacy_us = f_record.after_close - f_record.after_open
        f_lo, f_hi = _legacyInterval(f_row.bw, f_row.mib)
        f_inside = f_lo - _LEGACY_SLACK_US <= f_legacy_us <= f_hi + _LEGACY_SLACK_US
        f_status = "ok" if f_inside else "mismatch"
        f_results.append((str(round(f_row_us)), f_status))
    return f_results


def _logRows(
    f_parsed: ParsedLog, f_set_columns: Dict[str, str], f_source_log: str
) -> List[Dict[str, str]]:
    """Return the report rows of a source log: blocks in log order, iterations, write first."""
    f_headers = f_parsed.m_headers
    f_shifted = f_headers.get("rankShift", "0") not in ("", "0")
    f_header_columns = {
        "durability": f_headers.get("durability", ""),
        "rank_shift": f_headers.get("rankShift", ""),
        "rank_shift_nodes": f_headers.get("rankShiftNodes", "") if f_shifted else "",
        "rank_shift_self_ranks": f_headers.get("rankShiftSelfRanks", "") if f_shifted else "",
        "rank_shift_same_host_ranks": (
            f_headers.get("rankShiftSameHostRanks", "") if f_shifted else ""
        ),
        "per_rank_path": f_headers.get("perRankPath", ""),
        "rocksdb_version": f_headers.get("rocksdbVersion", ""),
        "leveldb_version": f_headers.get("leveldbVersion", ""),
        "leveldb_close_flush": f_headers.get("leveldbCloseFlush", ""),
        "source_log": f_source_log,
    }
    f_rows: List[Dict[str, str]] = []
    for f_prefix in f_parsed.m_blocks:
        f_by_key = f_parsed.m_records[f_prefix]
        f_sorted = {
            f_side: [f_by_key[f_key] for f_key in sorted(f_by_key) if f_key[1] == f_side]
            for f_side in _SIDES
        }
        f_checks = {
            (f_record.iteration, f_side): f_check
            for f_side in _SIDES
            for f_record, f_check in zip(
                f_sorted[f_side],
                _legacyChecks(f_parsed, f_prefix, f_side, f_sorted[f_side]),
            )
        }
        for f_key in sorted(f_by_key, key=_recordOrder):
            f_record = f_by_key[f_key]
            f_rows.append(
                _recordRow(
                    f_record,
                    f_by_key.get((f_record.iteration, "write")),
                    f_checks[f_key],
                    {**f_set_columns, **f_header_columns},
                )
            )
    return f_rows


def _recordRow(
    f_record: PhaseRecord,
    f_write: Optional[PhaseRecord],
    f_check: Tuple[str, str],
    f_columns: Dict[str, str],
) -> Dict[str, str]:
    """Return the report row of one record; f_write is the same iteration's write record."""
    f_windows = {
        "full": f_record.after_delete - f_record.before_open,
        "open": f_record.after_open - f_record.before_open,
        "data": f_record.before_close - f_record.after_open,
        "close": f_record.after_close - f_record.before_close,
        "delete": f_record.after_delete - f_record.after_close,
        "legacy": f_record.after_close - f_record.after_open,
    }
    f_row = dict(f_columns)
    f_row.update(
        prefix=f_record.prefix,
        iteration=str(f_record.iteration),
        side=f_record.side,
        bytes=f_record.bytes_text,
        gap_us="",
        legacy_row_us=f_check[0],
        legacy_check=f_check[1],
    )
    for f_name, f_us in f_windows.items():
        f_row[f"{f_name}_us"] = str(f_us)
        f_row[f"{f_name}_mibs"] = _mibs(float(f_record.bytes_text), f_us)
    if f_record.side == "read" and f_write is not None:
        f_row["gap_us"] = str(f_record.before_open - f_write.after_delete)
    return f_row


def phaseRowsForSet(
    f_nodes: str,
    f_stripe: str,
    f_block: str,
    f_log_paths: Sequence[str],
    f_source_root: str,
) -> List[Dict[str, str]]:
    """Return the report rows of one (nodes, stripe, block) set of rank logs.

    The source log is the first readable path that holds a phase row; logs without rows are
    ignored (INV-23). Any other log with rows that differ from it gives one warning for the
    set; the source log's values stay. A missing or unreadable path is skipped with a warning.
    """
    f_source: Optional[Tuple[str, ParsedLog]] = None
    f_disagreed = False
    for f_path in f_log_paths:
        f_name = _relativeName(f_path, f_source_root)
        try:
            f_lines = readBmtoolLines(f_path)
        except OSError as f_error:
            Console.warning(f"{f_name}: rank log skipped, not readable: {f_error}")
            continue
        f_parsed = parseRankLog(f_lines, f_name)
        if not f_parsed.hasRecords():
            continue
        if f_source is None:
            f_source = (f_name, f_parsed)
        elif not f_disagreed and f_parsed.recordSet() != f_source[1].recordSet():
            f_disagreed = True
            Console.warning(
                f"Phase records of {f_name} differ from those of {f_source[0]}"
                f" (nodes {f_nodes}, stripe {f_stripe}, block {f_block}); keeping {f_source[0]}"
            )
    if f_source is None:
        return []
    f_set_columns = {"nodes": f_nodes, "stripe": f_stripe, "block": f_block}
    f_rows = _logRows(f_source[1], f_set_columns, f_source[0])
    if any(f_row["legacy_check"] == "mismatch" for f_row in f_rows):
        Console.warning(
            f"Legacy window of {f_source[0]} disagrees with its iwrite/iread rows"
            f" (nodes {f_nodes}, stripe {f_stripe}, block {f_block})"
        )
    return f_rows


def _relativeName(f_path: str, f_source_root: str) -> str:
    """Return f_path relative to f_source_root with '/' separators."""
    return os.path.relpath(f_path, f_source_root).replace(os.sep, "/")


def _numberKey(f_text: str) -> Tuple[int, int, str]:
    """Sort key: numbers by value, anything else after them by text."""
    if f_text.isdigit():
        return (0, int(f_text), "")
    return (1, 0, f_text)


def _blockKey(f_text: str) -> Tuple[int, int, str]:
    """Sort key of a block size such as 64K, 1M or 8M: by size, anything else after."""
    f_match = _SIZE.fullmatch(f_text)
    if f_match is None:
        return (1, 0, f_text)
    return (0, int(f_match.group(1)) * _SIZE_FACTOR[f_match.group(2).upper()], "")


def writePhaseReport(
    f_target_dir: str,
    f_sets: Sequence[Tuple[str, str, str, Sequence[str]]],
    f_source_root: str,
) -> Optional[str]:
    """Write lsm-phase-report.csv into f_target_dir and return its path.

    f_sets holds (nodes, stripe, block, log_paths) per set. Rows are ordered by nodes, stripe
    and block size, then as phaseRowsForSet gives them. With no row at all nothing is written
    (INV-23), an existing file stays, and None is returned.
    """
    f_ordered = sorted(
        f_sets,
        key=lambda f_set: (_numberKey(f_set[0]), _numberKey(f_set[1]), _blockKey(f_set[2])),
    )
    f_rows: List[Dict[str, str]] = []
    for f_nodes, f_stripe, f_block, f_log_paths in f_ordered:
        f_rows += phaseRowsForSet(f_nodes, f_stripe, f_block, f_log_paths, f_source_root)
    if not f_rows:
        return None
    f_path = os.path.join(f_target_dir, LSM_PHASE_REPORT_FILE)
    with open(f_path, "w", newline="", encoding="utf-8", errors="surrogateescape") as f_f:
        f_writer = csv.DictWriter(
            f_f, fieldnames=PHASE_REPORT_COLUMNS, lineterminator="\n"
        )
        f_writer.writeheader()
        f_writer.writerows(f_rows)
    return f_path
