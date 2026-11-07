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

"""Dataset builder of lsmiotool compare, with no matplotlib."""

import colorsys
import csv
import hashlib
import math
import os
import re
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

from lsmiotool.lib import arms, cli, data, epocppreport, export, log, output, variants

# (stripes, block) combinations recognized across benchmarks
COMBINATIONS: Tuple[Tuple[int, str], ...] = (
    (4, "64K"),
    (4, "1M"),
    (4, "8M"),
    (16, "64K"),
    (16, "1M"),
    (16, "8M"),
)
_COMBINATIONS_SET = set(COMBINATIONS)
_COMBINATIONS_INDEX: Dict[Tuple[int, str], int] = {
    f_comb: f_idx for f_idx, f_comb in enumerate(COMBINATIONS)
}

METRIC_TITLES: Dict[str, str] = {
    "write": "Write",
    "read": "Read",
    "runtime": "Runtime",
    "cost": "I/O cost",
}

METRIC_Y_LABELS: Dict[str, str] = {
    "write": "Max MiB/s",
    "read": "Max MiB/s",
    "runtime": "Min runtime (s)",
    "cost": "I/O cost (s): Min runtime minus the baseline's",
}

DELTA_Y_LABEL = "% change vs base"

_METRIC_SORT_ORDER: Dict[str, int] = {
    "runtime": 0,
    "cost": 1,
    "write": 2,
    "read": 3,
}

_INT_RE = re.compile(r"^[0-9]+$")
_NAN_TOKENS = frozenset({"NA", "NAN", "N/A", "NULL", "NONE"})

PALETTE: Tuple[str, ...] = (
    "#2a78d6",
    "#eb6834",
    "#1baf7a",
    "#eda100",
    "#8a5cd1",
    "#d14f8a",
    "#3aa9c9",
    "#7f9a2e",
    "#c0562d",
    "#4b5fb3",
)

BASELINE_GREYS: Tuple[str, ...] = (
    "#6f6e69",
    "#a3a19b",
    "#4a4945",
    "#c4c2bc",
)

_PALETTE_CACHE: List[str] = list(PALETTE)
_PALETTE_SET = set(PALETTE)


def _palette_candidates():
    # Primary candidate (0.65, 0.85) then variations across V and S
    # ensuring saturation >= 0.35 and unique hexes on collision
    sv_candidates = [(0.65, 0.85)]
    for v in (0.95, 0.75, 0.60, 0.45, 0.85, 0.70):
        for s in (0.80, 0.50, 0.95, 0.38, 0.65):
            if (s, v) not in sv_candidates:
                sv_candidates.append((s, v))
    f_step = len(PALETTE)
    while True:
        f_h = (f_step * 0.618033988749895) % 1.0
        yield f_h, sv_candidates
        f_step += 1


_PALETTE_GEN = _palette_candidates()


def paletteColour(f_index: int) -> str:
    """Deterministic palette colour generator (fixed PALETTE, then golden ratio hue)."""
    if f_index < len(_PALETTE_CACHE):
        return _PALETTE_CACHE[f_index]
    while len(_PALETTE_CACHE) <= f_index:
        f_h, sv_cands = next(_PALETTE_GEN)
        for s_cand, v_cand in sv_cands:
            f_r, f_g, f_b = colorsys.hsv_to_rgb(f_h, s_cand, v_cand)
            f_hex = f"#{round(f_r * 255):02x}{round(f_g * 255):02x}{round(f_b * 255):02x}"
            f_rf = int(f_hex[1:3], 16) / 255.0
            f_gf = int(f_hex[3:5], 16) / 255.0
            f_bf = int(f_hex[5:7], 16) / 255.0
            _, f_sat, _ = colorsys.rgb_to_hsv(f_rf, f_gf, f_bf)
            if f_hex not in _PALETTE_SET and f_sat >= 0.35:
                _PALETTE_CACHE.append(f_hex)
                _PALETTE_SET.add(f_hex)
                break
    return _PALETTE_CACHE[f_index]


_GREYS_CACHE: List[str] = list(BASELINE_GREYS)
_GREYS_SET = set(BASELINE_GREYS)


def _grey_candidates():
    # Systematic generator varying value and fine RGB deltas
    # guaranteeing saturation <= 0.068 and bounded termination for any index
    d = 0
    while True:
        dr_vals = (-d, 0, d) if d > 0 else (0,)
        dg_vals = (-d, 0, d) if d > 0 else (0,)
        db_vals = (-d, 0, d) if d > 0 else (0,)
        for dr in dr_vals:
            for dg in dg_vals:
                for db in db_vals:
                    for base in range(60, 235):
                        r = base + dr
                        g = base + dg
                        b = base + db
                        if 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255:
                            rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
                            _, sat, _ = colorsys.rgb_to_hsv(rf, gf, bf)
                            if sat <= 0.068:
                                yield f"#{r:02x}{g:02x}{b:02x}"
        d += 1


_GREYS_GEN = _grey_candidates()


def baselineGrey(f_index: int) -> str:
    """Deterministic baseline grey generator (fixed BASELINE_GREYS, then stepped value and fine RGB)."""
    if f_index < len(_GREYS_CACHE):
        return _GREYS_CACHE[f_index]
    f_v_candidates = [0.30, 0.40, 0.50, 0.60, 0.70, 0.80]
    f_step = len(_GREYS_CACHE)
    while len(_GREYS_CACHE) <= f_index and f_step < 34:
        f_s = 0.04
        f_v = f_v_candidates[
            (f_step - len(BASELINE_GREYS)) % len(f_v_candidates)
        ] + 0.01 * ((f_step // len(f_v_candidates)) % 5)
        f_h = 0.1
        f_r, f_g, f_b = colorsys.hsv_to_rgb(f_h, f_s, f_v)
        f_hex = f"#{round(f_r * 255):02x}{round(f_g * 255):02x}{round(f_b * 255):02x}"
        f_rf = int(f_hex[1:3], 16) / 255.0
        f_gf = int(f_hex[3:5], 16) / 255.0
        f_bf = int(f_hex[5:7], 16) / 255.0
        _, f_sat, _ = colorsys.rgb_to_hsv(f_rf, f_gf, f_bf)
        if f_hex not in _GREYS_SET and f_sat < 0.15:
            _GREYS_CACHE.append(f_hex)
            _GREYS_SET.add(f_hex)
        f_step += 1

    while len(_GREYS_CACHE) <= f_index:
        f_hex = next(_GREYS_GEN)
        if f_hex not in _GREYS_SET:
            _GREYS_CACHE.append(f_hex)
            _GREYS_SET.add(f_hex)

    return _GREYS_CACHE[f_index]


class CompareError(Exception):
    """Base error class for compare operations."""


class CompareFolderError(CompareError):
    """A folder does not exist or is not a directory (exit 3)."""


class CompareKindError(CompareError):
    """A folder the word does not admit or incompatible kinds (exit 1)."""


class CompareSelectionError(CompareError):
    """An explicit value that is not held (exit 1)."""


class CompareNoDataError(CompareError):
    """Empty dataset with no explicit narrowing (exit 1)."""


class CompareReportError(Exception):
    """Raised by report readers on unreadable reports."""

    def __init__(self, f_path: str, f_cause: BaseException) -> None:
        super().__init__(
            f"{f_path}: unreadable report ({f_cause.__class__.__name__}: {f_cause})"
        )
        self.m_path = f_path
        self.m_cause = f_cause

    @property
    def path(self) -> str:
        return self.m_path

    @property
    def cause(self) -> BaseException:
        return self.m_cause


class CompareSeries(NamedTuple):
    label: str
    colour: str


class ComparePanel(NamedTuple):
    title: str
    y_label: str
    values: Tuple[Tuple[int, Tuple[Optional[float], ...]], ...]
    no_data: bool
    zero_line: bool
    value_labels: bool


class CompareFigure(NamedTuple):
    title: str
    x_label: str
    x_categories: Tuple[str, ...]
    grid: Tuple[Tuple[ComparePanel, ...], ...]
    series: Tuple[CompareSeries, ...]
    legend: Tuple[int, ...]


class ComparePng(NamedTuple):
    path: str
    figure: CompareFigure


class CompareDataset(NamedTuple):
    output_dir: str
    pngs: Tuple[ComparePng, ...]


class ComparePoints(NamedTuple):
    path: str
    values: Dict[Tuple[str, str, int, int, str], float]
    unreadable_rows: int


class CompareArm(NamedTuple):
    folder: str
    position: int
    child: str
    reading: str
    base_label: str
    rank: int
    is_baseline: bool
    base_child: Optional[str]


class CompareLoad(NamedTuple):
    folders: Tuple[str, ...]
    variants_kind: Optional[str]
    arms: Tuple[CompareArm, ...]
    points: Dict[Tuple[int, str, int, int, str], float]


def warningLine(f_points: ComparePoints) -> Optional[str]:
    """Emit warning line for broken points or unreadable rows, or None."""
    f_broken_keys = [f_k for f_k, f_v in f_points.values.items() if math.isnan(f_v)]
    f_broken_count = len(f_broken_keys)
    f_unreadable_count = f_points.unreadable_rows

    if f_broken_count == 0 and f_unreadable_count == 0:
        return None

    def _sortKey(
        f_k: Tuple[str, str, int, int, str],
    ) -> Tuple[str, int, int, int]:
        f_backend, f_metric, f_nodes, f_stripes, f_block = f_k
        return (
            f_backend,
            _METRIC_SORT_ORDER.get(f_metric, 999),
            f_nodes,
            _COMBINATIONS_INDEX.get((f_stripes, f_block), 999),
        )

    f_broken_keys.sort(key=_sortKey)

    def _formatKey(f_k: Tuple[str, str, int, int, str]) -> str:
        f_backend, f_metric, f_nodes, f_stripes, f_block = f_k
        if f_backend:
            return f"{f_backend} {f_metric} {f_stripes}/{f_block} N={f_nodes}"
        return f"{f_metric} {f_stripes}/{f_block} N={f_nodes}"

    f_clauses = []
    if f_broken_count > 0:
        f_shown = [_formatKey(f_k) for f_k in f_broken_keys[:10]]
        if f_broken_count > 10:
            f_rem = f_broken_count - 10
            f_keys_text = f"{', '.join(f_shown)}, ... (+{f_rem} more)"
        else:
            f_keys_text = ", ".join(f_shown)
        f_clauses.append(
            f"{f_broken_count} broken value(s) drawn as gaps ({f_keys_text})"
        )

    if f_unreadable_count > 0:
        f_clauses.append(f"{f_unreadable_count} unreadable row(s) left out")

    return f"{f_points.path}: {'; '.join(f_clauses)}"


class CompareReportReader:
    """Report readers and parsing helpers for compare benchmarks."""

    warningLine = staticmethod(warningLine)

    @staticmethod
    def valueOf(f_cell: Optional[str]) -> float:
        if not isinstance(f_cell, str):
            return math.nan
        f_s = f_cell.strip()
        if not f_s or f_s.upper() in _NAN_TOKENS:
            return math.nan
        try:
            f_v = float(f_s)
        except (ValueError, TypeError):
            return math.nan
        if not math.isfinite(f_v):
            return math.nan
        return f_v

    @staticmethod
    def nodesOf(f_cell: Optional[str]) -> Optional[int]:
        if not isinstance(f_cell, str):
            return None
        f_s = f_cell.strip()
        if not _INT_RE.match(f_s):
            return None
        f_n = int(f_s)
        if f_n <= 0:
            return None
        return f_n

    @staticmethod
    def stripesOf(f_cell: Optional[str]) -> Optional[int]:
        if not isinstance(f_cell, str):
            return None
        f_s = f_cell.strip()
        if not _INT_RE.match(f_s):
            return None
        return int(f_s)

    @staticmethod
    def blockOf(f_cell: Optional[str]) -> Optional[str]:
        if not isinstance(f_cell, str):
            return None
        f_s = f_cell.strip()
        if not f_s:
            return None
        return f_s

    @classmethod
    def readLsmReport(cls, f_path: str) -> ComparePoints:
        f_values: Dict[Tuple[str, str, int, int, str], float] = {}
        f_unreadable_rows = 0
        try:
            with open(f_path, encoding="utf-8", newline="") as f_f:
                f_reader = csv.reader(f_f, delimiter=",", quotechar="|")
                for f_row in f_reader:
                    if not f_row or len(f_row) < 4:
                        continue
                    f_op = f_row[3].strip()
                    if f_op not in ("write", "read"):
                        continue
                    f_nodes = cls.nodesOf(f_row[0])
                    f_stripes = cls.stripesOf(f_row[1])
                    f_block = cls.blockOf(f_row[2])
                    if f_nodes is None or f_stripes is None or f_block is None:
                        f_unreadable_rows += 1
                        continue
                    if (f_stripes, f_block) not in _COMBINATIONS_SET:
                        continue
                    f_val_cell = f_row[4] if len(f_row) > 4 else None
                    f_values[("", f_op, f_nodes, f_stripes, f_block)] = cls.valueOf(
                        f_val_cell
                    )
        except (OSError, UnicodeDecodeError, csv.Error) as f_err:
            raise CompareReportError(f_path, f_err) from f_err

        return ComparePoints(
            path=f_path,
            values=f_values,
            unreadable_rows=f_unreadable_rows,
        )

    @classmethod
    def readEpocppArmReport(cls, f_path: str) -> ComparePoints:
        f_values: Dict[Tuple[str, str, int, int, str], float] = {}
        f_unreadable_rows = 0
        try:
            with open(f_path, encoding="utf-8", newline="") as f_f:
                f_reader = csv.DictReader(f_f)
                f_fieldnames = tuple(f_reader.fieldnames or ())
                if f_fieldnames not in (
                    epocppreport.REPORT_HEADER,
                    epocppreport._LEGACY_REPORT_HEADER,
                ):
                    raise CompareReportError(
                        f_path,
                        ValueError(f"{f_path} is not an epocpp arm report"),
                    )
                for f_row in f_reader:
                    if not f_row:
                        continue
                    f_metric_cell = f_row.get("Metric")
                    if f_metric_cell is None:
                        continue
                    f_metric = f_metric_cell.strip()
                    if f_metric not in ("runtime", "write", "read"):
                        continue
                    f_nodes = cls.nodesOf(f_row.get("N"))
                    f_stripes = cls.stripesOf(f_row.get("Stripes"))
                    f_block = cls.blockOf(f_row.get("BlockSize"))
                    if f_nodes is None or f_stripes is None or f_block is None:
                        f_unreadable_rows += 1
                        continue
                    if (f_stripes, f_block) not in _COMBINATIONS_SET:
                        continue
                    f_values[("", f_metric, f_nodes, f_stripes, f_block)] = cls.valueOf(
                        f_row.get("Best")
                    )
        except (OSError, UnicodeDecodeError, csv.Error) as f_err:
            raise CompareReportError(f_path, f_err) from f_err

        return ComparePoints(
            path=f_path,
            values=f_values,
            unreadable_rows=f_unreadable_rows,
        )

    @classmethod
    def readEpocppCostReport(cls, f_path: str) -> ComparePoints:
        f_values: Dict[Tuple[str, str, int, int, str], float] = {}
        f_unreadable_rows = 0
        try:
            with open(f_path, encoding="utf-8", newline="") as f_f:
                f_reader = csv.DictReader(f_f)
                f_fieldnames = tuple(f_reader.fieldnames or ())
                if f_fieldnames != epocppreport.COST_HEADER:
                    raise CompareReportError(
                        f_path,
                        ValueError(f"{f_path} is not an epocpp cost report"),
                    )
                for f_row in f_reader:
                    if not f_row:
                        continue
                    f_backend_cell = f_row.get("Backend")
                    if f_backend_cell is None:
                        continue
                    f_backend = f_backend_cell.strip()
                    if not f_backend:
                        continue
                    f_nodes = cls.nodesOf(f_row.get("N"))
                    f_stripes = cls.stripesOf(f_row.get("Stripes"))
                    f_block = cls.blockOf(f_row.get("BlockSize"))
                    if f_nodes is None or f_stripes is None or f_block is None:
                        f_unreadable_rows += 1
                        continue
                    if (f_stripes, f_block) not in _COMBINATIONS_SET:
                        continue
                    f_values[(f_backend, "cost", f_nodes, f_stripes, f_block)] = (
                        cls.valueOf(f_row.get("IOCost"))
                    )
        except (OSError, UnicodeDecodeError, csv.Error) as f_err:
            raise CompareReportError(f_path, f_err) from f_err

        return ComparePoints(
            path=f_path,
            values=f_values,
            unreadable_rows=f_unreadable_rows,
        )


CANONICAL_BACKEND_LABELS: Dict[str, str] = {
    "outputs-adios": "adios2",
    "outputs-adios2": "adios2",
    "adios": "adios2",
    "adios2": "adios2",
    "outputs-native": "native",
    "native": "native",
    "outputs-plugin": "plugin",
    "plugin": "plugin",
    # The -sync arms ('run lsmio backends', --lsmio-always-flush)
    "outputs-adios-sync": "adios2-sync",
    "adios-sync": "adios2-sync",
    "adios2-sync": "adios2-sync",
    "outputs-native-sync": "native-sync",
    "native-sync": "native-sync",
    "outputs-plugin-sync": "plugin-sync",
    "plugin-sync": "plugin-sync",
    "outputs-rocksdb-sync": "rocksdb-sync",
    "rocksdb-sync": "rocksdb-sync",
    "outputs-leveldb-sync": "leveldb-sync",
    "leveldb-sync": "leveldb-sync",
    "outputs-rocksdb": "rocksdb",
    "rocksdb": "rocksdb",
    "outputs-leveldb": "leveldb",
    "leveldb": "leveldb",
}

CANONICAL_ORDER: Dict[str, int] = {
    # Each backend, then its -sync arm
    "adios2": 0,
    "adios2-sync": 1,
    "native": 2,
    "native-sync": 3,
    "plugin": 4,
    "plugin-sync": 5,
    "rocksdb": 6,
    "rocksdb-sync": 7,
    "leveldb": 8,
    "leveldb-sync": 9,
    # EPOCpp arms ('run epocpp backends'), by kind then backend
    "epocpp-baseline": 20,
    "epocpp-posix": 21,
    "epocpp-adios2": 22,
    "epocpp-plugin": 23,
    "epocpp-native": 24,
    "epocpp-posix-bw": 25,
    "epocpp-adios2-bw": 26,
    "epocpp-plugin-bw": 27,
    "epocpp-native-bw": 28,
    # IOR arms archived by 'run ior' (outputs-ior[-<setup>]), charted after the backends
    "ior": 10,
    "ior-collective": 11,
    "ior-hdf5": 12,
    "ior-hdf5-collective": 13,
    "ior-fsync": 14,
    "ior-reverse": 15,
}


def lsmioBaseLabel(f_entry: str) -> str:
    """Canonical label for an lsmio backend or -sync arm."""
    f_legend = CANONICAL_BACKEND_LABELS.get(f_entry)
    if f_legend is not None:
        return f_legend
    f_entry_lower = f_entry.lower()
    # A -sync arm (e.g. outputs-plugin-sync-1, collision-suffixed) is
    # labelled as its backend, then -sync
    f_sync = re.search(r"-sync(-\d+)?$", f_entry_lower) is not None
    if f_sync:
        f_entry_lower = re.sub(r"-sync(-\d+)?$", "", f_entry_lower)
    # "plugin" first: plugin runs are ADIOS2 too (e.g. "adios2-plugin")
    if "plugin" in f_entry_lower:
        f_legend = "plugin"
    elif "adios" in f_entry_lower:
        f_legend = "adios2"
    elif f_entry_lower in ("outputs-native", "native"):
        f_legend = "native"
    elif "rocksdb" in f_entry_lower:
        f_legend = "rocksdb"
    elif "leveldb" in f_entry_lower:
        f_legend = "leveldb"
    else:
        f_legend = f_entry
    if f_sync and f_legend != f_entry:
        f_legend += "-sync"
    return f_legend


def seriesRank(f_label: str) -> int:
    """Canonical sort rank of an arm label."""
    return CANONICAL_ORDER.get(f_label, 999)


def uniqueTails(f_paths: Sequence[str], f_min_depth: int) -> List[str]:
    """The last path parts of each of f_paths (at least f_min_depth), as many as tell
    them apart: ['/a/backends/small', '/b/backends/small'] -> ['a/backends/small', ...]."""
    if not f_paths:
        return []
    f_parts = [os.path.normpath(f_p).strip(os.sep).split(os.sep) for f_p in f_paths]
    f_depth = f_min_depth
    while f_depth < max(len(f_p) for f_p in f_parts) and len(
        {tuple(f_p[-f_depth:]) for f_p in f_parts}
    ) < len(f_parts):
        f_depth += 1
    return ["/".join(f_p[-f_depth:]) for f_p in f_parts]


MAX_COMBINED_NAME: int = 120


def computeScaleName(f_target_dir: str) -> str:
    """Determine scale name for output naming (backends/<scale> -> <scale>, variants -> variants, else base)."""
    f_norm = os.path.normpath(f_target_dir)
    f_parts = f_norm.split(os.sep)
    f_base = os.path.basename(f_norm)
    f_b_indices = [i for i, part in enumerate(f_parts) if part == "backends"]
    f_v_indices = [i for i, part in enumerate(f_parts) if part == "variants"]
    if f_b_indices:
        f_b_idx = f_b_indices[-1]
        return f_parts[f_b_idx + 1] if f_b_idx + 1 < len(f_parts) else f_base
    if f_v_indices:
        return "variants"
    return f_base


def computeCombinedNames(f_folders: Sequence[str]) -> str:
    """Determine <names> segment when multiple folders are compared."""
    if len(f_folders) < 2:
        return ""
    f_dirs = [os.path.normpath(f_d) for f_d in f_folders]
    f_parents = [os.path.basename(os.path.dirname(f_d)) for f_d in f_dirs]
    if all(f_parents) and len(set(f_parents)) == len(f_parents):
        f_names = f_parents
    else:
        f_names = [f_t.replace("/", "_") for f_t in uniqueTails(f_dirs, 1)]
    f_combined = "+".join(f_names)
    if len(f_combined) > MAX_COMBINED_NAME:
        f_hash = hashlib.sha1(f_combined.encode()).hexdigest()[:8]
        f_combined = f_combined[: MAX_COMBINED_NAME - 9] + "-" + f_hash
    return f_combined


def armEntries(f_dir: str) -> Tuple[str, ...]:
    """Sorted names of child directories starting with outputs-."""
    return tuple(
        sorted(
            f_e
            for f_e in os.listdir(f_dir)
            if f_e.startswith("outputs-") and os.path.isdir(os.path.join(f_dir, f_e))
        )
    )


def isIorOnly(f_dir: str) -> bool:
    """f_dir's outputs-* directories are all IOR arms ('run ior' archives), and it has one."""
    f_arms = [f_e[len("outputs-") :] for f_e in armEntries(f_dir)]
    return bool(f_arms) and all(arms.isIorArmId(f_a) for f_a in f_arms)


def isEpocppOnly(f_dir: str) -> bool:
    """f_dir's outputs-* directories are all epocpp arms ('run epocpp backends'
    archives), and it has one."""
    f_arms = [f_e[len("outputs-") :] for f_e in armEntries(f_dir)]
    return bool(f_arms) and all(arms.isEpocppArmId(f_a) for f_a in f_arms)


def hasRoleEntries(f_dir: str) -> bool:
    """True if some arm entry resolves with role 'run' or 'base'."""
    for f_e in armEntries(f_dir):
        f_res = variants.VariantReverseResolver.resolve(f_e)
        if f_res is not None and f_res.role in ("run", "base"):
            return True
    return False


def variantsKind(f_dir: str) -> str:
    """Variants kind of a folder: versioned, paired, or unpaired."""
    f_has_run = False
    for f_e in armEntries(f_dir):
        f_res = variants.VariantReverseResolver.resolve(f_e)
        if f_res is not None and f_res.role == "run":
            f_has_run = True
            if f_res.variant.startswith("version-"):
                return "versioned"
    if f_has_run:
        return "paired"
    return "unpaired"


def fittingWord(f_dir: str) -> Optional[str]:
    """Best fitting compare benchmark word for a folder, or None."""
    if isEpocppOnly(f_dir):
        return "epocpp"
    f_entries = armEntries(f_dir)
    f_has_epocpp = any(arms.isEpocppArmId(f_e[len("outputs-") :]) for f_e in f_entries)
    f_has_ior = any(arms.isIorArmId(f_e[len("outputs-") :]) for f_e in f_entries)
    f_has_role = hasRoleEntries(f_dir)
    if f_has_role and not f_has_ior and not f_has_epocpp:
        return "variants"
    if isIorOnly(f_dir):
        return "ior"
    if not f_has_epocpp and not f_has_role:
        return "lsmio"
    return None


def ensureEpocppReports(f_dir: str) -> None:
    """Build the epocpp reports f_dir lacks: every arm's first, then the cost
    report, which needs the baseline's and each backend's."""
    f_arms = [
        os.path.join(f_dir, f_e)
        for f_e in sorted(os.listdir(f_dir))
        if f_e.startswith("outputs-")
        and arms.isEpocppArmId(f_e[len("outputs-") :])
        and os.path.isdir(os.path.join(f_dir, f_e))
    ]
    f_missing = [
        f_a
        for f_a in f_arms
        if not os.path.isfile(os.path.join(f_a, epocppreport.ARM_REPORT_FILE))
    ]
    f_cost = os.path.join(f_dir, epocppreport.COST_REPORT_FILE)
    if not f_missing and (not f_arms or os.path.isfile(f_cost)):
        return
    # One unusable arm loses only its own report
    for f_arm in f_missing:
        try:
            epocppreport.writeArmReport(f_arm)
        except Exception as f_err:
            log.Console.warning(f"Failed to generate report for {f_arm}: {f_err}")
    try:
        epocppreport.writeCostReport(f_dir)
    except Exception as f_err:
        log.Console.warning(f"Failed to generate the cost report of {f_dir}: {f_err}")


class PairedVariantRun(NamedTuple):
    """Encapsulates a verified paired variant run directory and its control baseline directory."""

    backend: str
    variant: str
    collision: Optional[int]
    display_label: str
    run_dir: str
    base_dir: str
    run_metadata: Dict[str, Any]
    base_metadata: Dict[str, Any]

    def toDict(self) -> Dict[str, Any]:
        return {
            "backend": self.backend,
            "variant": self.variant,
            "collision": self.collision,
            "display_label": self.display_label,
            "run_dir": self.run_dir,
            "base_dir": self.base_dir,
            "run_metadata": dict(self.run_metadata),
            "base_metadata": dict(self.base_metadata),
        }

    @classmethod
    def fromDict(cls, f_data: Dict[str, Any]) -> "PairedVariantRun":
        return cls(
            backend=str(f_data["backend"]),
            variant=str(f_data["variant"]),
            collision=int(f_data["collision"])
            if f_data.get("collision") is not None
            else None,
            display_label=str(f_data["display_label"]),
            run_dir=str(f_data["run_dir"]),
            base_dir=str(f_data["base_dir"]),
            run_metadata=dict(f_data["run_metadata"]),
            base_metadata=dict(f_data["base_metadata"]),
        )


def pairDirectories(
    f_valid_runs: List[Tuple[Any, str]],
) -> List[PairedVariantRun]:
    """Pair variant runs with their baseline within a directory."""
    variant_runs: List[Tuple[Any, str]] = []
    twin_bases: Dict[Tuple[str, str, Optional[int]], Tuple[Any, str]] = {}
    standalone_bases: Dict[Tuple[str, Optional[int]], Tuple[Any, str]] = {}

    for res, path in f_valid_runs:
        coll_int = int(res.collision) if res.collision is not None else None
        if res.role == "run":
            variant_runs.append((res, path))
        elif res.role == "base":
            twin_bases[(res.backend, res.variant, coll_int)] = (res, path)
        elif res.role is None and res.variant == "default":
            standalone_bases[(res.backend, coll_int)] = (res, path)

    paired_results: List[PairedVariantRun] = []
    for meta_run, path_run in variant_runs:
        coll_int = int(meta_run.collision) if meta_run.collision is not None else None
        base_match = twin_bases.get((meta_run.backend, meta_run.variant, coll_int))
        if base_match is None:
            base_match = standalone_bases.get(
                (meta_run.backend, coll_int)
            ) or standalone_bases.get((meta_run.backend, None))
        if base_match is not None:
            meta_base, path_base = base_match
            paired_results.append(
                PairedVariantRun(
                    backend=meta_run.backend,
                    variant=meta_run.variant,
                    collision=coll_int,
                    display_label=meta_run.display_label,
                    run_dir=path_run,
                    base_dir=path_base,
                    run_metadata=meta_run._asdict(),
                    base_metadata=meta_base._asdict(),
                )
            )
        else:
            log.Console.warning(
                f"Orphaned variant run omitted (no matching baseline): {meta_run.raw_directory}"
            )

    return sorted(paired_results, key=lambda x: x.display_label)


def percentChange(f_run: float, f_base: float) -> float:
    """Calculate percentage change vs baseline."""
    if math.isnan(f_run) or math.isnan(f_base) or f_base <= 0.0:
        return math.nan
    return 100.0 * (f_run - f_base) / f_base


class CompareDatasetBuilder:
    """Builds load and figures for lsmiotool compare."""

    def __init__(self, f_request: cli.CompareRequest) -> None:
        if not isinstance(f_request, cli.CompareRequest):
            raise TypeError(f"Expected CompareRequest, got {type(f_request).__name__}")
        self.m_request: cli.CompareRequest = f_request
        self.m_reports: Dict[str, Optional[ComparePoints]] = {}

    def _readReport(
        self,
        f_path: str,
        f_kind: str,
    ) -> Optional[ComparePoints]:
        f_abs = os.path.abspath(f_path)
        if f_abs in self.m_reports:
            return self.m_reports[f_abs]
        try:
            if f_kind == "lsm":
                f_points = CompareReportReader.readLsmReport(f_abs)
            elif f_kind == "epocpp_arm":
                f_points = CompareReportReader.readEpocppArmReport(f_abs)
            elif f_kind == "epocpp_cost":
                f_points = CompareReportReader.readEpocppCostReport(f_abs)
            else:
                raise ValueError(f"Unknown report kind: {f_kind}")
        except CompareReportError as f_err:
            self.m_reports[f_abs] = None
            log.Console.warning(str(f_err))
            return None

        self.m_reports[f_abs] = f_points
        f_warn = CompareReportReader.warningLine(f_points)
        if f_warn is not None:
            log.Console.warning(f_warn)
        return f_points

    def load(self) -> CompareLoad:
        # 1. Folders (exit 3 class)
        f_resolved_folders: List[Tuple[str, str]] = []
        f_seen_abs = set()
        for f_given in self.m_request.folders:
            f_abs = os.path.abspath(os.path.expanduser(f_given))
            if f_abs not in f_seen_abs:
                f_seen_abs.add(f_abs)
                f_resolved_folders.append((f_given, f_abs))

        for f_given, f_abs in f_resolved_folders:
            if not os.path.isdir(f_abs):
                raise CompareFolderError(f"Folder not found: {f_given} ({f_abs})")

        f_folders: Tuple[str, ...] = tuple(f_abs for _, f_abs in f_resolved_folders)

        # 2. Kinds (exit 1 class), from listings only
        f_benchmark = self.m_request.benchmark
        for f_idx, f_folder in enumerate(f_folders):
            f_entries = armEntries(f_folder)
            f_is_ior_only = isIorOnly(f_folder)
            f_is_epocpp_only = isEpocppOnly(f_folder)
            f_has_role = hasRoleEntries(f_folder)
            f_has_epocpp = any(
                arms.isEpocppArmId(f_e[len("outputs-") :]) for f_e in f_entries
            )
            f_has_ior = any(
                arms.isIorArmId(f_e[len("outputs-") :]) for f_e in f_entries
            )

            if f_benchmark == "epocpp":
                if not f_is_epocpp_only:
                    if f_is_ior_only:
                        f_what = "IOR arms only"
                    else:
                        f_offending = [
                            f_e
                            for f_e in f_entries
                            if not arms.isEpocppArmId(f_e[len("outputs-") :])
                        ]
                        f_what = (
                            ", ".join(f_offending[:3])
                            if f_offending
                            else "no epocpp arm entries"
                        )
                    f_fit = fittingWord(f_folder)
                    f_sug = (
                        f"; use 'compare {f_fit}'"
                        if f_fit and f_fit != f_benchmark
                        else ""
                    )
                    raise CompareKindError(
                        f"{f_folder}: not an epocpp folder: {f_what}{f_sug}"
                    )

            elif f_benchmark == "lsmio":
                if f_idx == 0 and f_is_ior_only:
                    raise CompareKindError(
                        f"{f_folder}: not a lsmio folder: holds IOR arms only; use 'compare ior'"
                    )
                if f_has_epocpp or f_has_role:
                    f_offending = [
                        f_e
                        for f_e in f_entries
                        if arms.isEpocppArmId(f_e[len("outputs-") :])
                        or (
                            variants.VariantReverseResolver.resolve(f_e) is not None
                            and variants.VariantReverseResolver.resolve(f_e).role
                            in ("run", "base")
                        )
                    ]
                    f_what = (
                        ", ".join(f_offending[:3])
                        if f_offending
                        else "incompatible arm entries"
                    )
                    f_fit = fittingWord(f_folder)
                    f_sug = (
                        f"; use 'compare {f_fit}'"
                        if f_fit and f_fit != f_benchmark
                        else ""
                    )
                    raise CompareKindError(
                        f"{f_folder}: not a lsmio folder: {f_what}{f_sug}"
                    )

            elif f_benchmark == "ior":
                if f_idx == 0 and not f_is_ior_only:
                    f_offending = [
                        f_e
                        for f_e in f_entries
                        if not arms.isIorArmId(f_e[len("outputs-") :])
                    ]
                    f_what = (
                        ", ".join(f_offending[:3])
                        if f_offending
                        else "no IOR arm entries"
                    )
                    f_fit = fittingWord(f_folder)
                    f_sug = (
                        f"; use 'compare {f_fit}'"
                        if f_fit and f_fit != f_benchmark
                        else ""
                    )
                    raise CompareKindError(
                        f"{f_folder}: not an ior folder: {f_what}{f_sug}"
                    )
                if f_has_epocpp or f_has_role:
                    f_offending = [
                        f_e
                        for f_e in f_entries
                        if arms.isEpocppArmId(f_e[len("outputs-") :])
                        or (
                            variants.VariantReverseResolver.resolve(f_e) is not None
                            and variants.VariantReverseResolver.resolve(f_e).role
                            in ("run", "base")
                        )
                    ]
                    f_what = (
                        ", ".join(f_offending[:3])
                        if f_offending
                        else "incompatible arm entries"
                    )
                    f_fit = fittingWord(f_folder)
                    f_sug = (
                        f"; use 'compare {f_fit}'"
                        if f_fit and f_fit != f_benchmark
                        else ""
                    )
                    raise CompareKindError(
                        f"{f_folder}: not an ior folder: {f_what}{f_sug}"
                    )

            elif f_benchmark == "variants" and (f_has_ior or f_has_epocpp):
                if f_is_ior_only:
                    f_what = "IOR arms only"
                else:
                    f_offending = [
                        f_e
                        for f_e in f_entries
                        if arms.isIorArmId(f_e[len("outputs-") :])
                        or arms.isEpocppArmId(f_e[len("outputs-") :])
                    ]
                    f_what = (
                        ", ".join(f_offending[:3])
                        if f_offending
                        else "incompatible arm entries"
                    )
                f_fit = fittingWord(f_folder)
                f_sug = (
                    f"; use 'compare {f_fit}'" if f_fit and f_fit != f_benchmark else ""
                )
                raise CompareKindError(
                    f"{f_folder}: not a variants folder: {f_what}{f_sug}"
                )

        if f_benchmark == "variants":
            f_kinds = [(f_f, variantsKind(f_f)) for f_f in f_folders]
            if len({f_k for _, f_k in f_kinds}) > 1:
                f_desc = ", ".join(f"{f_f} ({f_k})" for f_f, f_k in f_kinds)
                raise CompareKindError(f"variants folders of different kinds: {f_desc}")
            f_variants_kind: Optional[str] = f_kinds[0][1]
        else:
            f_variants_kind = None

        # 3. Arms and points
        f_arms: List[CompareArm] = []
        f_points: Dict[Tuple[int, str, int, int, str], float] = {}
        f_allowed_metrics = cli.CompareCliParser.BENCHMARK_METRICS[f_benchmark]

        if f_benchmark == "epocpp":
            for f_pos, f_folder in enumerate(f_folders):
                ensureEpocppReports(f_folder)
                f_cost_path = os.path.join(f_folder, epocppreport.COST_REPORT_FILE)
                f_cost_points: Optional[ComparePoints] = None
                if os.path.isfile(f_cost_path):
                    f_cost_points = self._readReport(f_cost_path, "epocpp_cost")

                for f_child_name in sorted(os.listdir(f_folder)):
                    f_child_path = os.path.join(f_folder, f_child_name)
                    if not os.path.isdir(f_child_path):
                        continue
                    if not (
                        f_child_name.startswith("outputs-")
                        and arms.isEpocppArmId(f_child_name[len("outputs-") :])
                    ):
                        continue
                    f_arm_report_path = os.path.join(
                        f_child_path, epocppreport.ARM_REPORT_FILE
                    )
                    if not os.path.isfile(f_arm_report_path):
                        continue
                    f_arm_pts = self._readReport(f_arm_report_path, "epocpp_arm")
                    if f_arm_pts is None:
                        continue

                    f_arm_id = f_child_name[len("outputs-") :]
                    f_is_baseline = (
                        f_child_name == "outputs-" + arms.EPOCPP_BASELINE_ARM
                    )
                    f_arm = CompareArm(
                        folder=f_folder,
                        position=f_pos,
                        child=f_child_name,
                        reading="epocpp",
                        base_label=f_arm_id,
                        rank=seriesRank(f_arm_id),
                        is_baseline=f_is_baseline,
                        base_child=None,
                    )
                    f_arm_idx = len(f_arms)
                    f_arms.append(f_arm)

                    for (
                        _,
                        f_metric,
                        f_nodes,
                        f_stripes,
                        f_block,
                    ), f_val in f_arm_pts.values.items():
                        if f_metric in f_allowed_metrics:
                            f_points[
                                (f_arm_idx, f_metric, f_nodes, f_stripes, f_block)
                            ] = f_val

                    # Wall-time backend arm gets cost points
                    if not f_is_baseline and not f_arm_id.endswith("-bw"):
                        f_backend = f_child_name[len("outputs-epocpp-") :]
                        if f_cost_points is not None and "cost" in f_allowed_metrics:
                            for (
                                f_b,
                                f_m,
                                f_nodes,
                                f_stripes,
                                f_block,
                            ), f_val in f_cost_points.values.items():
                                if f_b == f_backend and f_m == "cost":
                                    f_points[
                                        (
                                            f_arm_idx,
                                            "cost",
                                            f_nodes,
                                            f_stripes,
                                            f_block,
                                        )
                                    ] = f_val

        elif f_benchmark in ("lsmio", "ior"):
            for f_pos, f_folder in enumerate(f_folders):
                for f_child_name in sorted(os.listdir(f_folder)):
                    f_child_path = os.path.join(f_folder, f_child_name)
                    if not os.path.isdir(f_child_path):
                        continue

                    f_is_ior = f_child_name.startswith("outputs-") and arms.isIorArmId(
                        f_child_name[len("outputs-") :]
                    )

                    if f_is_ior:
                        f_ior_report = os.path.join(f_child_path, data.IOR_REPORT_FILE)
                        if not data.isUsableReport(f_ior_report):
                            try:
                                export.generateIorReports(f_child_path)
                            except Exception as f_err:
                                log.Console.warning(
                                    f"Failed to generate report for {f_child_path}: {f_err}"
                                )
                        if not data.isUsableReport(f_ior_report):
                            continue
                        f_pts = self._readReport(f_ior_report, "lsm")
                        if f_pts is None:
                            continue
                        f_arm_id = f_child_name[len("outputs-") :]
                        f_arm = CompareArm(
                            folder=f_folder,
                            position=f_pos,
                            child=f_child_name,
                            reading="ior",
                            base_label=f_arm_id,
                            rank=seriesRank(f_arm_id),
                            is_baseline=False,
                            base_child=None,
                        )
                    else:
                        if not output.ensureLsmioReports(f_child_path):
                            continue
                        f_lsm_report = os.path.join(f_child_path, "lsm-report.csv")
                        f_pts = self._readReport(f_lsm_report, "lsm")
                        if f_pts is None:
                            continue
                        f_base_label = lsmioBaseLabel(f_child_name)
                        f_arm = CompareArm(
                            folder=f_folder,
                            position=f_pos,
                            child=f_child_name,
                            reading="lsmio",
                            base_label=f_base_label,
                            rank=seriesRank(f_base_label),
                            is_baseline=False,
                            base_child=None,
                        )

                    f_arm_idx = len(f_arms)
                    f_arms.append(f_arm)
                    for (
                        _,
                        f_op,
                        f_nodes,
                        f_stripes,
                        f_block,
                    ), f_val in f_pts.values.items():
                        if f_op in f_allowed_metrics:
                            f_points[(f_arm_idx, f_op, f_nodes, f_stripes, f_block)] = (
                                f_val
                            )

        elif f_benchmark == "variants":
            for f_pos, f_folder in enumerate(f_folders):
                f_valid_runs: List[Tuple[Any, str]] = []
                for f_child_name in sorted(os.listdir(f_folder)):
                    f_child_path = os.path.join(f_folder, f_child_name)
                    if not os.path.isdir(f_child_path):
                        continue
                    f_res = variants.VariantReverseResolver.resolve(f_child_name)
                    if f_res is None:
                        continue
                    if output.ensureLsmioReports(
                        f_child_path, f_scale="variants", f_require_logs=False
                    ):
                        f_valid_runs.append((f_res, f_child_path))

                if f_variants_kind == "unpaired":
                    for f_res, f_child_path in f_valid_runs:
                        f_report = os.path.join(f_child_path, "lsm-report.csv")
                        f_pts = self._readReport(f_report, "lsm")
                        if f_pts is None:
                            continue
                        f_arm = CompareArm(
                            folder=f_folder,
                            position=f_pos,
                            child=f_res.raw_directory,
                            reading="variants",
                            base_label=f_res.display_label,
                            rank=0,
                            is_baseline=False,
                            base_child=None,
                        )
                        f_arm_idx = len(f_arms)
                        f_arms.append(f_arm)
                        for (
                            _,
                            f_op,
                            f_nodes,
                            f_stripes,
                            f_block,
                        ), f_val in f_pts.values.items():
                            if f_op in f_allowed_metrics:
                                f_points[
                                    (f_arm_idx, f_op, f_nodes, f_stripes, f_block)
                                ] = f_val
                else:
                    # paired or versioned
                    f_pairs = pairDirectories(f_valid_runs)
                    for f_pair in f_pairs:
                        f_run_report = os.path.join(f_pair.run_dir, "lsm-report.csv")
                        f_base_report = os.path.join(f_pair.base_dir, "lsm-report.csv")
                        f_run_pts = self._readReport(f_run_report, "lsm")
                        f_base_pts = self._readReport(f_base_report, "lsm")
                        if f_run_pts is None or f_base_pts is None:
                            continue

                        f_run_child = os.path.basename(f_pair.run_dir)
                        f_base_child = os.path.basename(f_pair.base_dir)
                        f_arm = CompareArm(
                            folder=f_folder,
                            position=f_pos,
                            child=f_run_child,
                            reading="variants",
                            base_label=f_pair.display_label,
                            rank=0,
                            is_baseline=False,
                            base_child=f_base_child,
                        )
                        f_arm_idx = len(f_arms)
                        f_arms.append(f_arm)

                        f_broken_delta_keys: List[Tuple[str, str, int, int, str]] = []
                        # Points: for every key in both run's and base's values
                        for f_k, f_run_val in f_run_pts.values.items():
                            if f_k in f_base_pts.values:
                                _, f_op, f_nodes, f_stripes, f_block = f_k
                                if f_op not in f_allowed_metrics:
                                    continue
                                f_base_val = f_base_pts.values[f_k]
                                f_delta = percentChange(f_run_val, f_base_val)
                                f_points[
                                    (f_arm_idx, f_op, f_nodes, f_stripes, f_block)
                                ] = f_delta
                                if math.isnan(f_delta):
                                    f_broken_delta_keys.append(f_k)

                        if f_broken_delta_keys:
                            f_broken_count = len(f_broken_delta_keys)

                            def _sortKey(
                                f_k: Tuple[str, str, int, int, str],
                            ) -> Tuple[str, int, int, int]:
                                f_b, f_m, f_n, f_s, f_bl = f_k
                                return (
                                    f_b,
                                    _METRIC_SORT_ORDER.get(f_m, 999),
                                    f_n,
                                    _COMBINATIONS_INDEX.get((f_s, f_bl), 999),
                                )

                            f_broken_delta_keys.sort(key=_sortKey)
                            f_shown = [
                                f"{f_k[1]} {f_k[3]}/{f_k[4]} N={f_k[2]}"
                                for f_k in f_broken_delta_keys[:10]
                            ]
                            if f_broken_count > 10:
                                f_rem = f_broken_count - 10
                                f_keys_str = (
                                    f"{', '.join(f_shown)}, ... (+{f_rem} more)"
                                )
                            else:
                                f_keys_str = ", ".join(f_shown)
                            log.Console.warning(
                                f"{f_pair.run_dir} vs {f_pair.base_dir}: "
                                f"{f_broken_count} broken % change point(s) drawn as gaps ({f_keys_str})"
                            )

        return CompareLoad(
            folders=f_folders,
            variants_kind=f_variants_kind,
            arms=tuple(f_arms),
            points=f_points,
        )

    def build(self) -> CompareDataset:
        """Execute selection, series resolution, layouts, figure specs, and naming."""
        f_load = self.load()
        f_benchmark = self.m_request.benchmark

        # Step 1: Selection (4.5)
        # M is request.metrics or DEFAULT_METRICS[benchmark]
        f_req_metrics = self.m_request.metrics
        f_m: Tuple[str, ...] = (
            f_req_metrics
            if f_req_metrics is not None
            else cli.CompareCliParser.DEFAULT_METRICS[f_benchmark]
        )

        # A: every point of every arm (all in f_load.points)
        # U: points in A whose metric is in M
        f_a_points = f_load.points
        f_u_points = {f_k: f_v for f_k, f_v in f_a_points.items() if f_k[1] in f_m}

        # Check explicit dimensions in order: metrics, nodes, stripes, blocks
        # 1. metrics
        if f_req_metrics is not None:
            f_canon_metrics = [
                f_met
                for f_met in cli.CompareCliParser.BENCHMARK_METRICS[f_benchmark]
                if f_met in f_req_metrics
            ]
            # P'(metric) is A narrowed by nodes, stripes, blocks (each given)
            f_p_prime_metric = {
                f_k: f_v
                for f_k, f_v in f_a_points.items()
                if (self.m_request.nodes is None or f_k[2] in self.m_request.nodes)
                and (self.m_request.stripes is None or f_k[3] in self.m_request.stripes)
                and (self.m_request.blocks is None or f_k[4] in self.m_request.blocks)
            }
            f_held_metrics_set = {f_k[1] for f_k in f_p_prime_metric}
            for f_metric_val in f_canon_metrics:
                if f_metric_val not in f_held_metrics_set:
                    f_held_list = [
                        f_met
                        for f_met in cli.CompareCliParser.BENCHMARK_METRICS[f_benchmark]
                        if f_met in f_held_metrics_set
                    ]
                    raise CompareSelectionError(
                        f"--metrics {f_metric_val}: the folders hold {', '.join(f_held_list)}"
                    )

        # 2. nodes
        if self.m_request.nodes is not None:
            f_canon_nodes = sorted(self.m_request.nodes)
            # P'(nodes) is U narrowed by stripes and blocks (each given)
            f_p_prime_nodes = {
                f_k: f_v
                for f_k, f_v in f_u_points.items()
                if (self.m_request.stripes is None or f_k[3] in self.m_request.stripes)
                and (self.m_request.blocks is None or f_k[4] in self.m_request.blocks)
            }
            f_held_nodes_set = {f_k[2] for f_k in f_p_prime_nodes}
            for f_node_val in f_canon_nodes:
                if f_node_val not in f_held_nodes_set:
                    f_held_list_n = sorted(f_held_nodes_set)
                    raise CompareSelectionError(
                        f"--nodes {f_node_val}: the folders hold {', '.join(str(f_n) for f_n in f_held_list_n)}"
                    )

        # 3. stripes
        if self.m_request.stripes is not None:
            f_canon_stripes = sorted(self.m_request.stripes)
            # P'(stripes) is U narrowed by nodes and blocks (each given)
            f_p_prime_stripes = {
                f_k: f_v
                for f_k, f_v in f_u_points.items()
                if (self.m_request.nodes is None or f_k[2] in self.m_request.nodes)
                and (self.m_request.blocks is None or f_k[4] in self.m_request.blocks)
            }
            f_held_stripes_set = {f_k[3] for f_k in f_p_prime_stripes}
            for f_stripe_val in f_canon_stripes:
                if f_stripe_val not in f_held_stripes_set:
                    f_held_list_s = [
                        f_s for f_s in (4, 16) if f_s in f_held_stripes_set
                    ]
                    raise CompareSelectionError(
                        f"--stripes {f_stripe_val}: the folders hold {', '.join(str(f_s) for f_s in f_held_list_s)}"
                    )

        # 4. blocks
        if self.m_request.blocks is not None:
            f_canon_blocks = [
                f_b for f_b in ("64K", "1M", "8M") if f_b in self.m_request.blocks
            ]
            # P'(blocks) is U narrowed by nodes and stripes (each given)
            f_p_prime_blocks = {
                f_k: f_v
                for f_k, f_v in f_u_points.items()
                if (self.m_request.nodes is None or f_k[2] in self.m_request.nodes)
                and (self.m_request.stripes is None or f_k[3] in self.m_request.stripes)
            }
            f_held_blocks_set = {f_k[4] for f_k in f_p_prime_blocks}
            for f_block_val in f_canon_blocks:
                if f_block_val not in f_held_blocks_set:
                    f_held_list_b = [
                        f_b for f_b in ("64K", "1M", "8M") if f_b in f_held_blocks_set
                    ]
                    raise CompareSelectionError(
                        f"--block {f_block_val}: the folders hold {', '.join(f_held_list_b)}"
                    )

        # P: points of U whose nodes, stripes and block are in request's given dimensions
        f_p_points = {
            f_k: f_v
            for f_k, f_v in f_u_points.items()
            if (self.m_request.nodes is None or f_k[2] in self.m_request.nodes)
            and (self.m_request.stripes is None or f_k[3] in self.m_request.stripes)
            and (self.m_request.blocks is None or f_k[4] in self.m_request.blocks)
        }

        # If P is empty: raise CompareNoDataError
        if not f_p_points:
            f_folders_str = ", ".join(f_load.folders)
            if not f_load.arms:
                if f_load.variants_kind in ("paired", "versioned"):
                    f_cause = "no :run entry with a matching base"
                else:
                    f_cause = "no arm with a report"
            else:
                f_cause = "no point in the reports"
            raise CompareNoDataError(
                f"Nothing to chart for compare {f_benchmark} in {f_folders_str}: {f_cause}"
            )

        # Charted metrics: M's metrics that P holds, in M's order
        f_p_metrics_set = {f_k[1] for f_k in f_p_points}
        f_charted_metrics = tuple(f_met for f_met in f_m if f_met in f_p_metrics_set)

        # Default metrics left out warning (when no explicit --metrics)
        if f_req_metrics is None:
            f_left_out = [f_met for f_met in f_m if f_met not in f_p_metrics_set]
            if f_left_out:
                log.Console.warning(
                    f"No data for metric(s) {', '.join(f_left_out)}: left out"
                )

        # Charted node counts: ascending
        f_charted_nodes = tuple(sorted({f_k[2] for f_k in f_p_points}))

        # Charted combinations: COMBINATIONS order
        f_held_comb_set = {(f_k[3], f_k[4]) for f_k in f_p_points}
        f_charted_combinations = tuple(
            f_c for f_c in COMBINATIONS if f_c in f_held_comb_set
        )

        # Step 2: Series (4.3) and Step 3: Variant categories (4.3, P3)
        if f_benchmark == "variants":
            f_arm_cat_map: Dict[int, str] = {}
            for f_f_path in f_load.folders:
                f_folder_arms = [
                    (f_i, f_a)
                    for f_i, f_a in enumerate(f_load.arms)
                    if f_a.folder == f_f_path
                ]
                f_counts: Dict[str, int] = {}
                for _, f_a in f_folder_arms:
                    f_counts[f_a.base_label] = f_counts.get(f_a.base_label, 0) + 1
                for f_i, f_a in f_folder_arms:
                    if f_counts[f_a.base_label] > 1:
                        f_arm_cat_map[f_i] = f"{f_a.base_label} ({f_a.child})"
                    else:
                        f_arm_cat_map[f_i] = f_a.base_label

            f_held_cats_set = {f_arm_cat_map[f_k[0]] for f_k in f_p_points}
            f_charted_categories = tuple(sorted(f_held_cats_set))

            f_unique_folder_tails = uniqueTails(f_load.folders, 2)
            f_series_list: List[CompareSeries] = []
            f_series_folders: List[str] = []

            f_folders_with_p = {f_load.arms[f_k[0]].folder for f_k in f_p_points}
            f_color_idx = 0
            for f_pos, f_folder in enumerate(f_load.folders):
                if f_folder in f_folders_with_p:
                    f_lbl = f_unique_folder_tails[f_pos]
                    f_colour = paletteColour(f_color_idx)
                    f_color_idx += 1
                    f_series_folders.append(f_folder)
                    f_series_list.append(CompareSeries(label=f_lbl, colour=f_colour))

            f_all_series = tuple(f_series_list)

        else:
            f_active_arm_indices = sorted({f_k[0] for f_k in f_p_points})
            f_sorted_arm_indices = sorted(
                f_active_arm_indices,
                key=lambda f_idx: (
                    f_load.arms[f_idx].rank,
                    f_load.arms[f_idx].base_label,
                    f_load.arms[f_idx].position,
                    f_load.arms[f_idx].child,
                ),
            )

            f_base_label_folders: Dict[str, set] = {}
            for f_arm_idx in f_sorted_arm_indices:
                f_arm = f_load.arms[f_arm_idx]
                f_base_label_folders.setdefault(f_arm.base_label, set()).add(
                    f_arm.folder
                )

            f_tail_maps: Dict[str, Dict[str, str]] = {}
            for f_bl, f_f_set in f_base_label_folders.items():
                if len(f_f_set) >= 2:
                    f_f_sorted = sorted(f_f_set)
                    f_tails = uniqueTails(f_f_sorted, 2)
                    f_tail_maps[f_bl] = dict(zip(f_f_sorted, f_tails))

            f_series_list = []
            f_arm_to_series_idx: Dict[int, int] = {}
            f_grey_idx = 0
            f_palette_idx = 0
            for f_arm_idx in f_sorted_arm_indices:
                f_arm = f_load.arms[f_arm_idx]
                if f_arm.base_label in f_tail_maps:
                    f_label = f"{f_arm.base_label} ({f_tail_maps[f_arm.base_label][f_arm.folder]})"
                else:
                    f_label = f_arm.base_label

                if f_arm.is_baseline:
                    f_colour = baselineGrey(f_grey_idx)
                    f_grey_idx += 1
                else:
                    f_colour = paletteColour(f_palette_idx)
                    f_palette_idx += 1

                f_arm_to_series_idx[f_arm_idx] = len(f_series_list)
                f_series_list.append(CompareSeries(label=f_label, colour=f_colour))

            f_all_series = tuple(f_series_list)

        # Step 5: Scale and Names
        f_scale_name = computeScaleName(f_load.folders[0])
        f_names_part = computeCombinedNames(f_load.folders)
        f_names_suffix = f"-{f_names_part}" if f_names_part else ""

        f_out_dir = (
            os.path.abspath(os.path.expanduser(self.m_request.output_dir))
            if self.m_request.output_dir is not None
            else os.getcwd()
        )

        f_folder_tails = uniqueTails(f_load.folders, 2)
        f_tails_str = " + ".join(f_folder_tails)
        f_base_fig_title = f"compare {f_benchmark}: {f_scale_name}, {f_tails_str}"

        # Generate PNGs
        f_pngs: List[ComparePng] = []

        if f_benchmark == "variants":
            if self.m_request.by == "nodes":
                f_file_name = (
                    f"compare-{f_scale_name}-{f_benchmark}{f_names_suffix}-by-nodes.png"
                )
                f_path = os.path.join(f_out_dir, f_file_name)

                f_grid_rows: List[Tuple[ComparePanel, ...]] = []
                for f_s, f_bl in f_charted_combinations:
                    for f_n in f_charted_nodes:
                        f_row_panels: List[ComparePanel] = []
                        for f_metric in f_charted_metrics:
                            f_p_title = f"{METRIC_TITLES[f_metric]}, {f_s} stripes / {f_bl} blocks, {f_n} nodes"
                            f_y_label = (
                                DELTA_Y_LABEL
                                if f_load.variants_kind in ("paired", "versioned")
                                else METRIC_Y_LABELS[f_metric]
                            )
                            f_zero_line = f_load.variants_kind in (
                                "paired",
                                "versioned",
                            )
                            f_value_labels = (
                                f_load.variants_kind in ("paired", "versioned")
                                and self.m_request.style == "bars"
                            )

                            f_panel_values: List[
                                Tuple[int, Tuple[Optional[float], ...]]
                            ] = []
                            for f_s_idx, _ in enumerate(f_all_series):
                                f_folder = f_series_folders[f_s_idx]
                                f_cells: List[Optional[float]] = []
                                f_has_point = False
                                for f_cat in f_charted_categories:
                                    f_arm_idx_opt = None
                                    for f_a_idx, f_arm in enumerate(f_load.arms):
                                        if (
                                            f_arm.folder == f_folder
                                            and f_arm_cat_map[f_a_idx] == f_cat
                                        ):
                                            f_arm_idx_opt = f_a_idx
                                            break
                                    if f_arm_idx_opt is not None:
                                        f_key = (
                                            f_arm_idx_opt,
                                            f_metric,
                                            f_n,
                                            f_s,
                                            f_bl,
                                        )
                                        if f_key in f_p_points:
                                            f_val = f_p_points[f_key]
                                            f_cells.append(f_val)
                                            f_has_point = True
                                        else:
                                            f_cells.append(None)
                                    else:
                                        f_cells.append(None)

                                if f_has_point:
                                    f_panel_values.append((f_s_idx, tuple(f_cells)))

                            f_no_data = not any(
                                f_v is not None and math.isfinite(f_v)
                                for _, f_vals in f_panel_values
                                for f_v in f_vals
                            )

                            f_row_panels.append(
                                ComparePanel(
                                    title=f_p_title,
                                    y_label=f_y_label,
                                    values=tuple(f_panel_values),
                                    no_data=f_no_data,
                                    zero_line=f_zero_line,
                                    value_labels=f_value_labels,
                                )
                            )
                        f_grid_rows.append(tuple(f_row_panels))

                f_legend = tuple(
                    sorted(
                        {
                            f_s_idx
                            for f_row in f_grid_rows
                            for f_p in f_row
                            for f_s_idx, _ in f_p.values
                        }
                    )
                )

                f_fig = CompareFigure(
                    title=f_base_fig_title,
                    x_label="Variant",
                    x_categories=f_charted_categories,
                    grid=tuple(f_grid_rows),
                    series=f_all_series,
                    legend=f_legend,
                )
                f_pngs.append(ComparePng(path=f_path, figure=f_fig))

            else:
                for f_n in f_charted_nodes:
                    f_file_name = f"compare-{f_scale_name}-{f_benchmark}{f_names_suffix}-by-combinations-{f_n}.png"
                    f_path = os.path.join(f_out_dir, f_file_name)
                    f_fig_title = f"{f_base_fig_title}, {f_n} nodes"

                    f_grid_rows = []
                    for f_s, f_bl in f_charted_combinations:
                        f_row_panels = []
                        for f_metric in f_charted_metrics:
                            f_p_title = f"{METRIC_TITLES[f_metric]}, {f_s} stripes / {f_bl} blocks"
                            f_y_label = (
                                DELTA_Y_LABEL
                                if f_load.variants_kind in ("paired", "versioned")
                                else METRIC_Y_LABELS[f_metric]
                            )
                            f_zero_line = f_load.variants_kind in (
                                "paired",
                                "versioned",
                            )
                            f_value_labels = (
                                f_load.variants_kind in ("paired", "versioned")
                                and self.m_request.style == "bars"
                            )

                            f_panel_values = []
                            for f_s_idx, _ in enumerate(f_all_series):
                                f_folder = f_series_folders[f_s_idx]
                                f_cells = []
                                f_has_point = False
                                for f_cat in f_charted_categories:
                                    f_arm_idx_opt = None
                                    for f_a_idx, f_arm in enumerate(f_load.arms):
                                        if (
                                            f_arm.folder == f_folder
                                            and f_arm_cat_map[f_a_idx] == f_cat
                                        ):
                                            f_arm_idx_opt = f_a_idx
                                            break
                                    if f_arm_idx_opt is not None:
                                        f_key = (
                                            f_arm_idx_opt,
                                            f_metric,
                                            f_n,
                                            f_s,
                                            f_bl,
                                        )
                                        if f_key in f_p_points:
                                            f_val = f_p_points[f_key]
                                            f_cells.append(f_val)
                                            f_has_point = True
                                        else:
                                            f_cells.append(None)
                                    else:
                                        f_cells.append(None)

                                if f_has_point:
                                    f_panel_values.append((f_s_idx, tuple(f_cells)))

                            f_no_data = not any(
                                f_v is not None and math.isfinite(f_v)
                                for _, f_vals in f_panel_values
                                for f_v in f_vals
                            )

                            f_row_panels.append(
                                ComparePanel(
                                    title=f_p_title,
                                    y_label=f_y_label,
                                    values=tuple(f_panel_values),
                                    no_data=f_no_data,
                                    zero_line=f_zero_line,
                                    value_labels=f_value_labels,
                                )
                            )
                        f_grid_rows.append(tuple(f_row_panels))

                    f_legend = tuple(
                        sorted(
                            {
                                f_s_idx
                                for f_row in f_grid_rows
                                for f_p in f_row
                                for f_s_idx, _ in f_p.values
                            }
                        )
                    )

                    f_fig = CompareFigure(
                        title=f_fig_title,
                        x_label="Variant",
                        x_categories=f_charted_categories,
                        grid=tuple(f_grid_rows),
                        series=f_all_series,
                        legend=f_legend,
                    )
                    f_pngs.append(ComparePng(path=f_path, figure=f_fig))

        else:
            if self.m_request.by == "nodes":
                f_file_name = (
                    f"compare-{f_scale_name}-{f_benchmark}{f_names_suffix}-by-nodes.png"
                )
                f_path = os.path.join(f_out_dir, f_file_name)

                f_x_categories = tuple(str(f_n) for f_n in f_charted_nodes)

                f_grid_rows = []
                for f_s, f_bl in f_charted_combinations:
                    f_row_panels = []
                    for f_metric in f_charted_metrics:
                        f_p_title = (
                            f"{METRIC_TITLES[f_metric]}, {f_s} stripes / {f_bl} blocks"
                        )
                        f_y_label = METRIC_Y_LABELS[f_metric]
                        f_zero_line = f_metric == "cost"
                        f_value_labels = False

                        f_panel_values = []
                        for f_arm_idx in f_sorted_arm_indices:
                            f_s_idx = f_arm_to_series_idx[f_arm_idx]
                            f_cells = []
                            f_has_point = False
                            for f_n in f_charted_nodes:
                                f_key = (f_arm_idx, f_metric, f_n, f_s, f_bl)
                                if f_key in f_p_points:
                                    f_val = f_p_points[f_key]
                                    f_cells.append(f_val)
                                    f_has_point = True
                                else:
                                    f_cells.append(None)
                            if f_has_point:
                                f_panel_values.append((f_s_idx, tuple(f_cells)))

                        f_no_data = not any(
                            f_v is not None and math.isfinite(f_v)
                            for _, f_vals in f_panel_values
                            for f_v in f_vals
                        )

                        f_row_panels.append(
                            ComparePanel(
                                title=f_p_title,
                                y_label=f_y_label,
                                values=tuple(f_panel_values),
                                no_data=f_no_data,
                                zero_line=f_zero_line,
                                value_labels=f_value_labels,
                            )
                        )
                    f_grid_rows.append(tuple(f_row_panels))

                f_legend = tuple(
                    sorted(
                        {
                            f_s_idx
                            for f_row in f_grid_rows
                            for f_p in f_row
                            for f_s_idx, _ in f_p.values
                        }
                    )
                )

                f_fig = CompareFigure(
                    title=f_base_fig_title,
                    x_label="Nodes",
                    x_categories=f_x_categories,
                    grid=tuple(f_grid_rows),
                    series=f_all_series,
                    legend=f_legend,
                )
                f_pngs.append(ComparePng(path=f_path, figure=f_fig))

            else:
                f_x_categories = tuple(
                    f"{f_s} stripes\n{f_bl} blocks"
                    for f_s, f_bl in f_charted_combinations
                )

                for f_n in f_charted_nodes:
                    f_file_name = f"compare-{f_scale_name}-{f_benchmark}{f_names_suffix}-by-combinations-{f_n}.png"
                    f_path = os.path.join(f_out_dir, f_file_name)
                    f_fig_title = f"{f_base_fig_title}, {f_n} nodes"

                    f_grid_rows = []
                    for f_metric in f_charted_metrics:
                        f_p_title = f"{METRIC_TITLES[f_metric]}"
                        f_y_label = METRIC_Y_LABELS[f_metric]
                        f_zero_line = f_metric == "cost"
                        f_value_labels = False

                        f_panel_values = []
                        for f_arm_idx in f_sorted_arm_indices:
                            f_s_idx = f_arm_to_series_idx[f_arm_idx]
                            f_cells = []
                            f_has_point = False
                            for f_s, f_bl in f_charted_combinations:
                                f_key = (f_arm_idx, f_metric, f_n, f_s, f_bl)
                                if f_key in f_p_points:
                                    f_val = f_p_points[f_key]
                                    f_cells.append(f_val)
                                    f_has_point = True
                                else:
                                    f_cells.append(None)
                            if f_has_point:
                                f_panel_values.append((f_s_idx, tuple(f_cells)))

                        f_no_data = not any(
                            f_v is not None and math.isfinite(f_v)
                            for _, f_vals in f_panel_values
                            for f_v in f_vals
                        )

                        f_row_panels = [
                            ComparePanel(
                                title=f_p_title,
                                y_label=f_y_label,
                                values=tuple(f_panel_values),
                                no_data=f_no_data,
                                zero_line=f_zero_line,
                                value_labels=f_value_labels,
                            )
                        ]
                        f_grid_rows.append(tuple(f_row_panels))

                    f_legend = tuple(
                        sorted(
                            {
                                f_s_idx
                                for f_row in f_grid_rows
                                for f_p in f_row
                                for f_s_idx, _ in f_p.values
                            }
                        )
                    )

                    f_fig = CompareFigure(
                        title=f_fig_title,
                        x_label="Stripes / block size",
                        x_categories=f_x_categories,
                        grid=tuple(f_grid_rows),
                        series=f_all_series,
                        legend=f_legend,
                    )
                    f_pngs.append(ComparePng(path=f_path, figure=f_fig))

        return CompareDataset(output_dir=f_out_dir, pngs=tuple(f_pngs))
