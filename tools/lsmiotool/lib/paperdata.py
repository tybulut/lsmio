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

"""Paper data: turn benchmark reports into the TSV files a paper's charts read.

A paper keeps a `sources.yaml` that says, for every TSV, which archived report it comes
from, which node counts are stitched in from another run, and how runs that never
completed are shown. `generate` rebuilds every TSV from the reports, so a figure can be
traced back to the raw archive and regenerated.

sources.yaml (schema 1):

    schema: 1
    grid: {nodes: [1, 2, 4], stripes: [4, 16]}         # optional; also per dataset
    datasets:
      - output: hdd/ior/ior-report-base.tsv            # relative to the output dir
        kind: ior                                      # ior or lsmio
        source: viking/ior-hdd/small/output-ior-reverse  # relative to the data dir
        stitch:                                        # optional
          - {source: viking/lsmio-hdd/small/output-adios-2,
             nodes: [24], stripes: [4], block_sizes: [1M]}
        missing: placeholder                           # or error; default placeholder
        fill: nan                                      # or zero; default nan
    figures: [...]                                     # used by 'latex plots'

The grid lists the rows every TSV must have (each node count times each stripe count,
block size and operation); an omitted list takes its values from the report, and a row
outside the grid is an error. A stitch rule overlays the rows of its selection (an
omitted selector matches all) with the rows of its own source. A combination that no
report has is a "placeholder", and a run whose measurements are all empty (a failed run)
has no data either; both are warned about. With fill nan their measurements are written
as nan (a gap in a chart) and a placeholder's other columns as NA. With fill zero the
measurements are zeros and an IOR placeholder copies its other columns from the
preceding node count's run, or from the one a placeholders rule names.
"""

import csv
import math
import os
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence, Tuple

from lsmiotool.lib.log import Console

SCHEMA_VERSION = 1
LINE_END = "\r\n"

IOR_HEADER: List[str] = [
    "Concurrency",
    "Replication",
    "Block Size",
    "Operation",
    "Max(MiB)",
    "Min(MiB)",
    "Mean(MiB)",
    "StdDev",
    "Max(OPs)",
    "Min(OPs)",
    "Mean(OPs)",
    "StdDev",
    "Mean(s)",
    "Stonewall(s)",
    "Stonewall(MiB)",
    "Test#",
    "#Tasks",
    "tPN",
    "reps",
    "fPP",
    "reord",
    "reordoff",
    "reordrand",
    "seed",
    "segcnt",
    "blksiz",
    "xsize",
    "aggs(MiB)",
    "API",
    "RefNum",
]
LSMIO_HEADER: List[str] = [
    "Concurrency",
    "Replication",
    "Block size",
    "Access",
    "Max (MiBs)",
    "Min (MiB/s)",
    "Mean (MiB/s)",
    "Total (MiB)",
    "Total (Ops)",
    "Iterations",
]

# Per kind: the report file name in a source directory, the TSV header, the columns
# [first, last] that must be numbers and are written with two decimals (an empty cell
# becomes 0.00), the columns that may also be NA, empty or an integer (IOR's stonewall
# columns; only decimals are rewritten), the measurement columns that are either all
# filled or all empty (a run without data), the columns zeroed in a placeholder row, and
# the column (IOR's aggs(MiB)) written as an integer.
KINDS: Dict[str, Dict[str, Any]] = {
    "ior": {
        "report": "ior-report.csv",
        "header": IOR_HEADER,
        "decimals": (4, 12),
        "optional_decimals": (13, 14),
        "measured": (4, 12),
        "zeroed": (4, 12),
        "integer": 27,
    },
    "lsmio": {
        "report": "lsm-report.csv",
        "header": LSMIO_HEADER,
        "decimals": (4, 9),
        "optional_decimals": None,
        "measured": (4, 8),
        "zeroed": (4, 9),
        "integer": None,
    },
}

MISSING_PLACEHOLDER = "placeholder"
MISSING_ERROR = "error"
FILL_NAN = "nan"
FILL_ZERO = "zero"

_FLOAT_RE = re.compile(r"^-?\d+\.\d+$", re.ASCII)
_INT_RE = re.compile(r"^-?\d+$", re.ASCII)
_NUMBER_RE = re.compile(r"^[-+]?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?$", re.ASCII)
_SELECTORS = ("nodes", "stripes", "block_sizes", "ops")
_TOP_FIELDS = ("schema", "grid", "datasets", "figures")
_DATASET_FIELDS = ("output", "kind", "source", "grid", "stitch", "missing", "fill", "placeholders")
_FIGURE_FIELDS = ("file", "title", "y_label", "y_divisor", "series")
_SERIES_FIELDS = ("label", "dataset", "stripes", "block_size", "op")

RowKey = Tuple[int, int, str, str]


class PaperDataError(Exception):
    """A sources.yaml or a benchmark report cannot be turned into paper data."""


class Selection:
    """Rows picked by node counts, stripe counts, block sizes and operations. A selector
    that is None matches everything."""

    def __init__(
        self,
        f_nodes: Optional[Sequence[int]] = None,
        f_stripes: Optional[Sequence[int]] = None,
        f_block_sizes: Optional[Sequence[str]] = None,
        f_ops: Optional[Sequence[str]] = None,
    ) -> None:
        self.nodes: Optional[Sequence[int]] = f_nodes
        self.stripes: Optional[Sequence[int]] = f_stripes
        self.block_sizes: Optional[Sequence[str]] = f_block_sizes
        self.ops: Optional[Sequence[str]] = f_ops

    def selects(self, f_key: RowKey) -> bool:
        """True when f_key (node, stripes, block size, operation) is in the selection."""
        f_node, f_stripes, f_block_size, f_op = f_key
        return (
            (self.nodes is None or f_node in self.nodes)
            and (self.stripes is None or f_stripes in self.stripes)
            and (self.block_sizes is None or f_block_size in self.block_sizes)
            and (self.ops is None or f_op in self.ops)
        )


class StitchRule:
    """Rows of one report that replace the matching rows of a dataset's own report."""

    def __init__(self, f_source: str, f_selection: Selection) -> None:
        self.source: str = f_source
        self.selection: Selection = f_selection


class PlaceholderRule:
    """Which node count's run an IOR placeholder row copies its settings from, in place of
    the preceding node count's."""

    def __init__(self, f_selection: Selection, f_copy_from_node: int) -> None:
        self.selection: Selection = f_selection
        self.copy_from_node: int = f_copy_from_node


class DatasetSpec:
    """One TSV: where its rows come from, which rows it must have and how missing runs
    are shown. A grid selector that is None takes its values from the report."""

    def __init__(
        self,
        f_output: str,
        f_kind: str,
        f_source: str,
        f_stitch: Sequence[StitchRule] = (),
        f_missing: str = MISSING_PLACEHOLDER,
        f_placeholders: Sequence[PlaceholderRule] = (),
        f_grid: Optional[Selection] = None,
        f_fill: str = FILL_NAN,
    ) -> None:
        self.output: str = f_output
        self.kind: str = f_kind
        self.source: str = f_source
        self.stitch: List[StitchRule] = list(f_stitch)
        self.missing: str = f_missing
        self.placeholders: List[PlaceholderRule] = list(f_placeholders)
        self.grid: Selection = f_grid if f_grid is not None else Selection()
        self.fill: str = f_fill


class SeriesSpec:
    """One line of a figure: a stripe count, block size and operation of a dataset."""

    def __init__(
        self,
        f_label: str,
        f_dataset: str,
        f_stripes: int,
        f_block_size: str,
        f_op: str,
    ) -> None:
        self.label: str = f_label
        self.dataset: str = f_dataset
        self.stripes: int = f_stripes
        self.block_size: str = f_block_size
        self.op: str = f_op


class FigureSpec:
    """One figure: a file name, a title and the series it draws."""

    def __init__(
        self,
        f_file: str,
        f_title: str,
        f_y_label: str,
        f_y_divisor: float,
        f_series: Sequence[SeriesSpec],
    ) -> None:
        self.file: str = f_file
        self.title: str = f_title
        self.y_label: str = f_y_label
        self.y_divisor: float = f_y_divisor
        self.series: List[SeriesSpec] = list(f_series)


class PaperSources:
    """A parsed sources.yaml."""

    def __init__(self, f_datasets: Sequence[DatasetSpec], f_figures: Sequence[FigureSpec]) -> None:
        self.datasets: List[DatasetSpec] = list(f_datasets)
        self.figures: List[FigureSpec] = list(f_figures)


def _requireString(f_obj: Dict[str, Any], f_name: str, f_where: str) -> str:
    f_value = f_obj.get(f_name)
    if not isinstance(f_value, str) or not f_value:
        raise PaperDataError(f"{f_where}: '{f_name}' must be a non-empty string")
    return f_value


def _checkRelative(f_path: str, f_where: str) -> None:
    """A path under the output or data dir must stay inside it."""
    f_parts = f_path.replace("\\", "/").split("/")
    if os.path.isabs(f_path) or ".." in f_parts:
        raise PaperDataError(f"{f_where}: '{f_path}' must be a relative path without '..'")


def _intList(f_value: Any, f_where: str) -> Optional[List[int]]:
    if f_value is None:
        return None
    if not isinstance(f_value, list) or not all(
        isinstance(f_item, int) and not isinstance(f_item, bool) for f_item in f_value
    ):
        raise PaperDataError(f"{f_where} must be a list of integers")
    return list(f_value)


def _strList(f_value: Any, f_where: str) -> Optional[List[str]]:
    if f_value is None:
        return None
    if not isinstance(f_value, list) or not all(isinstance(f_item, str) for f_item in f_value):
        raise PaperDataError(f"{f_where} must be a list of strings")
    return list(f_value)


def _checkFields(f_obj: Dict[Any, Any], f_allowed: Sequence[str], f_where: str) -> None:
    """A misspelt field would be ignored without a word; any field not in f_allowed is an
    error."""
    f_unknown = sorted(str(f_key) for f_key in set(f_obj) - set(f_allowed))
    if f_unknown:
        raise PaperDataError(f"{f_where}: unknown field(s) {', '.join(f_unknown)}")


def _parseSelection(f_obj: Dict[str, Any], f_where: str, f_extra: Sequence[str]) -> Selection:
    """The selectors of f_obj; f_extra names the other fields the object may carry."""
    _checkFields(f_obj, tuple(_SELECTORS) + tuple(f_extra), f_where)
    return Selection(
        _intList(f_obj.get("nodes"), f"{f_where}.nodes"),
        _intList(f_obj.get("stripes"), f"{f_where}.stripes"),
        _strList(f_obj.get("block_sizes"), f"{f_where}.block_sizes"),
        _strList(f_obj.get("ops"), f"{f_where}.ops"),
    )


def _parseStitch(f_obj: Any, f_where: str) -> StitchRule:
    if not isinstance(f_obj, dict):
        raise PaperDataError(f"{f_where} must be an object")
    f_source = _requireString(f_obj, "source", f_where)
    _checkRelative(f_source, f"{f_where}.source")
    return StitchRule(f_source, _parseSelection(f_obj, f_where, ("source",)))


def _parsePlaceholder(f_obj: Any, f_where: str) -> PlaceholderRule:
    if not isinstance(f_obj, dict):
        raise PaperDataError(f"{f_where} must be an object")
    f_copy = f_obj.get("copy_from_node")
    if isinstance(f_copy, bool) or not isinstance(f_copy, int):
        raise PaperDataError(f"{f_where}: copy_from_node must be an integer")
    return PlaceholderRule(_parseSelection(f_obj, f_where, ("copy_from_node",)), f_copy)


def _parseGrid(f_obj: Any, f_where: str) -> Selection:
    """The rows a dataset must have: every node count times every (stripe count, block
    size, operation) of the given lists; an omitted list takes its values from the report."""
    if not isinstance(f_obj, dict):
        raise PaperDataError(f"{f_where} must be an object")
    f_grid = _parseSelection(f_obj, f_where, ())
    for f_name in _SELECTORS:
        if f_obj.get(f_name) == []:
            raise PaperDataError(f"{f_where}.{f_name} must not be empty")
    return f_grid


def _parseDataset(f_obj: Any, f_index: int, f_default_grid: Selection) -> DatasetSpec:
    f_where = f"datasets[{f_index}]"
    if not isinstance(f_obj, dict):
        raise PaperDataError(f"{f_where} must be an object")
    _checkFields(f_obj, _DATASET_FIELDS, f_where)
    f_output = _requireString(f_obj, "output", f_where)
    _checkRelative(f_output, f"{f_where}.output")
    f_kind = _requireString(f_obj, "kind", f_where)
    if f_kind not in KINDS:
        raise PaperDataError(
            f"{f_where}: kind '{f_kind}' must be one of {', '.join(sorted(KINDS))}"
        )
    f_source = _requireString(f_obj, "source", f_where)
    _checkRelative(f_source, f"{f_where}.source")
    f_missing = f_obj.get("missing", MISSING_PLACEHOLDER)
    if f_missing not in (MISSING_PLACEHOLDER, MISSING_ERROR):
        raise PaperDataError(
            f"{f_where}: missing '{f_missing}' must be '{MISSING_PLACEHOLDER}' or '{MISSING_ERROR}'"
        )
    f_stitch_objs = f_obj.get("stitch", [])
    if not isinstance(f_stitch_objs, list):
        raise PaperDataError(f"{f_where}.stitch must be a list")
    f_stitch = [
        _parseStitch(f_item, f"{f_where}.stitch[{f_pos}]")
        for f_pos, f_item in enumerate(f_stitch_objs)
    ]
    for f_pos, f_rule in enumerate(f_stitch):
        if os.path.normpath(f_rule.source) == os.path.normpath(f_source):
            raise PaperDataError(
                f"{f_where}.stitch[{f_pos}]: source '{f_rule.source}' is the dataset's own "
                f"source; a stitch rule takes rows from another run"
            )
    f_placeholder_objs = f_obj.get("placeholders", [])
    if not isinstance(f_placeholder_objs, list):
        raise PaperDataError(f"{f_where}.placeholders must be a list")
    f_placeholders = [
        _parsePlaceholder(f_item, f"{f_where}.placeholders[{f_pos}]")
        for f_pos, f_item in enumerate(f_placeholder_objs)
    ]
    f_fill = f_obj.get("fill", FILL_NAN)
    if f_fill not in (FILL_NAN, FILL_ZERO):
        raise PaperDataError(f"{f_where}: fill {f_fill!r} must be '{FILL_NAN}' or '{FILL_ZERO}'")
    if f_placeholders and f_kind != "ior":
        raise PaperDataError(f"{f_where}: placeholders apply to ior datasets only")
    if f_placeholders and f_fill != FILL_ZERO:
        raise PaperDataError(
            f"{f_where}: placeholders rules copy settings into zero-filled rows; they need "
            f"fill '{FILL_ZERO}'"
        )
    f_grid = f_default_grid
    if "grid" in f_obj:
        f_grid = _parseGrid(f_obj["grid"], f"{f_where}.grid")
    return DatasetSpec(
        f_output, f_kind, f_source, f_stitch, f_missing, f_placeholders, f_grid, f_fill
    )


def _parseFigure(f_obj: Any, f_index: int, f_outputs: Sequence[str]) -> FigureSpec:
    f_where = f"figures[{f_index}]"
    if not isinstance(f_obj, dict):
        raise PaperDataError(f"{f_where} must be an object")
    _checkFields(f_obj, _FIGURE_FIELDS, f_where)
    f_file = _requireString(f_obj, "file", f_where)
    _checkRelative(f_file, f"{f_where}.file")
    if not f_file.endswith(".pdf"):
        raise PaperDataError(f"{f_where}: file '{f_file}' must end in .pdf")
    f_title = _requireString(f_obj, "title", f_where)
    f_y_label = _requireString(f_obj, "y_label", f_where)
    f_divisor = f_obj.get("y_divisor", 1)
    try:
        f_usable = (
            not isinstance(f_divisor, bool)
            and isinstance(f_divisor, (int, float))
            and math.isfinite(f_divisor)
            and f_divisor > 0
        )
    except OverflowError:  # an int too large for a float
        f_usable = False
    if not f_usable:
        raise PaperDataError(f"{f_where}: y_divisor must be a positive finite number")
    f_series_objs = f_obj.get("series")
    if not isinstance(f_series_objs, list) or not f_series_objs:
        raise PaperDataError(f"{f_where}: series must be a non-empty list")
    f_series: List[SeriesSpec] = []
    for f_pos, f_item in enumerate(f_series_objs):
        f_where_series = f"{f_where}.series[{f_pos}]"
        if not isinstance(f_item, dict):
            raise PaperDataError(f"{f_where_series} must be an object")
        _checkFields(f_item, _SERIES_FIELDS, f_where_series)
        f_dataset = _requireString(f_item, "dataset", f_where_series)
        if os.path.normpath(f_dataset) not in [os.path.normpath(f_out) for f_out in f_outputs]:
            raise PaperDataError(
                f"{f_where_series}: dataset '{f_dataset}' is not the output of any dataset"
            )
        f_stripes = f_item.get("stripes")
        if isinstance(f_stripes, bool) or not isinstance(f_stripes, int):
            raise PaperDataError(f"{f_where_series}: stripes must be an integer")
        f_op = _requireString(f_item, "op", f_where_series)
        if f_op not in ("read", "write"):
            raise PaperDataError(f"{f_where_series}: op '{f_op}' must be 'read' or 'write'")
        f_series.append(
            SeriesSpec(
                _requireString(f_item, "label", f_where_series),
                f_dataset,
                f_stripes,
                _requireString(f_item, "block_size", f_where_series),
                f_op,
            )
        )
    return FigureSpec(f_file, f_title, f_y_label, float(f_divisor), f_series)


def _readYaml(f_path: str) -> Any:
    """The document of the YAML file f_path, read with PyYAML's safe loader. A mapping that
    repeats a key is an error (plain PyYAML keeps the last value without a word); a key that
    overrides one merged in with '<<' is not a repeat.

    Raises:
        PaperDataError: PyYAML is not installed, or the file cannot be read or is not YAML.
    """
    try:
        import yaml
    except ImportError:
        raise PaperDataError(f"reading {f_path} needs PyYAML (pip install pyyaml)")

    class _UniqueKeyLoader(yaml.SafeLoader):
        """The safe loader, rejecting a mapping that repeats a key."""

    def _constructMapping(f_loader: Any, f_node: Any) -> Dict[Any, Any]:
        f_seen = set()
        for f_key_node, _ in f_node.value:
            if f_key_node.tag == "tag:yaml.org,2002:merge":
                continue
            f_key = f_loader.construct_object(f_key_node, deep=True)
            try:
                f_repeated = f_key in f_seen
            except TypeError:
                break  # an unhashable key; construct_mapping reports it
            if f_repeated:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    f_node.start_mark,
                    f"found the key {f_key!r} twice",
                    f_key_node.start_mark,
                )
            f_seen.add(f_key)
        return yaml.SafeLoader.construct_mapping(f_loader, f_node, deep=True)

    _UniqueKeyLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _constructMapping
    )
    try:
        with open(f_path, "r", encoding="utf-8") as f_file:
            return yaml.load(f_file, Loader=_UniqueKeyLoader)
    except OSError as f_err:
        raise PaperDataError(f"cannot read {f_path}: {f_err}")
    except (yaml.YAMLError, UnicodeDecodeError) as f_err:
        raise PaperDataError(f"{f_path} is not valid YAML: {f_err}")


def loadSources(f_path: str) -> PaperSources:
    """Read and validate a sources.yaml.

    Raises:
        PaperDataError: PyYAML is missing, or the file cannot be read, is not YAML, or breaks
            the schema.
    """
    f_doc = _readYaml(f_path)
    if not isinstance(f_doc, dict):
        raise PaperDataError(f"{f_path}: the top level must be an object")
    _checkFields(f_doc, _TOP_FIELDS, f_path)
    f_schema = f_doc.get("schema")
    if type(f_schema) is not int or f_schema != SCHEMA_VERSION:
        raise PaperDataError(f"{f_path}: schema must be {SCHEMA_VERSION}, found {f_schema!r}")
    f_default_grid = Selection()
    if "grid" in f_doc:
        f_default_grid = _parseGrid(f_doc["grid"], "grid")
    f_dataset_objs = f_doc.get("datasets")
    if not isinstance(f_dataset_objs, list) or not f_dataset_objs:
        raise PaperDataError(f"{f_path}: datasets must be a non-empty list")
    f_datasets = [
        _parseDataset(f_obj, f_pos, f_default_grid) for f_pos, f_obj in enumerate(f_dataset_objs)
    ]
    f_outputs = [f_dataset.output for f_dataset in f_datasets]
    # 'a.tsv' and './a.tsv' are one file, and so are 'a.tsv' and 'A.tsv' on a file system
    # that ignores case (macOS by default); 'a.tsv.tmp' is the temporary name of 'a.tsv',
    # and 'x' cannot be a file when 'x/a.tsv' is one
    for f_output in f_outputs:
        if f_output.endswith(("/", "\\")) or os.path.normpath(f_output) == ".":
            raise PaperDataError(f"{f_path}: output '{f_output}' must name a file")
    f_normalized = [os.path.normpath(f_output).lower() for f_output in f_outputs]
    if len(set(f_normalized)) != len(f_normalized):
        raise PaperDataError(
            f"{f_path}: two datasets write the same output (paths are compared ignoring case)"
        )
    for f_output in f_normalized:
        if f_output + ".tmp" in f_normalized:
            raise PaperDataError(
                f"{f_path}: output {f_output}.tmp is the temporary file of output {f_output}"
            )
        for f_other in f_normalized:
            if f_other.startswith(f_output + os.sep):
                raise PaperDataError(
                    f"{f_path}: output {f_output} is a directory of output {f_other}"
                )
    f_figure_objs = f_doc.get("figures", [])
    if not isinstance(f_figure_objs, list):
        raise PaperDataError(f"{f_path}: figures must be a list")
    f_figures = [_parseFigure(f_obj, f_pos, f_outputs) for f_pos, f_obj in enumerate(f_figure_objs)]
    f_files = [os.path.normpath(f_figure.file).lower() for f_figure in f_figures]
    if len(set(f_files)) != len(f_files):
        raise PaperDataError(
            f"{f_path}: two figures write the same file (paths are compared ignoring case)"
        )
    return PaperSources(f_datasets, f_figures)


def _rowKey(f_row: Sequence[str]) -> RowKey:
    return (int(f_row[0]), int(f_row[1]), f_row[2].strip(), f_row[3].strip())


def readReport(f_path: str) -> Dict[RowKey, List[str]]:
    """Read a report CSV: data rows only (those starting with a node count), by key.

    Raises:
        PaperDataError: the report cannot be read, has a malformed row, lists one run
            (node count, stripe count, block size, operation) twice, or has no data row.
    """
    f_rows: Dict[RowKey, List[str]] = {}
    try:
        with open(f_path, newline="") as f_file:
            for f_row in csv.reader(f_file):
                if len(f_row) < 4 or not f_row[0].strip().isdigit():
                    continue
                f_key = _rowKey(f_row)
                if f_key in f_rows:
                    raise PaperDataError(
                        f"report {f_path} lists the run for {_describe(f_key)} twice; keep "
                        f"one of them in the report"
                    )
                f_rows[f_key] = [f_cell.strip() for f_cell in f_row]
    except OSError as f_err:
        raise PaperDataError(f"cannot read report {f_path}: {f_err}")
    except (ValueError, csv.Error) as f_err:
        raise PaperDataError(f"malformed row in report {f_path}: {f_err}")
    if not f_rows:
        raise PaperDataError(f"report {f_path} has no data rows")
    return f_rows


def _twoDecimals(f_cell: str) -> str:
    """f_cell with two decimals, halves rounded up as a spreadsheet does (not to even).

    Raises:
        PaperDataError: f_cell is not a finite number.
    """
    if f_cell == "":
        return "0.00"
    if f_cell.lower().lstrip("+-") in ("nan", "inf", "infinity"):
        raise PaperDataError(f"{f_cell!r} is not a finite number")
    if not _NUMBER_RE.match(f_cell):
        raise PaperDataError(f"{f_cell!r} is not a number")
    try:
        return str(Decimal(f_cell).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except InvalidOperation:
        raise PaperDataError(f"{f_cell!r} is too large to write with two decimals")


def _describe(f_key: RowKey) -> str:
    """A run as the messages name it."""
    return f"nodes={f_key[0]} stripes={f_key[1]} block size={f_key[2]} {f_key[3]}"


def _unusedValues(f_selection: Selection, f_keys: Sequence[RowKey]) -> str:
    """The values a rule's selectors list that match none of f_keys, as 'nodes 99;
    block_sizes 8M'; empty when every listed value matches. Such a value is stale: the
    rule says something about runs it never touches."""
    f_parts = []
    for f_pos, f_name in enumerate(_SELECTORS):
        f_values = getattr(f_selection, f_name)
        if f_values is None:
            continue
        f_unused = [f_v for f_v in f_values if not any(f_k[f_pos] == f_v for f_k in f_keys)]
        if f_unused:
            f_parts.append(f"{f_name} {', '.join(str(f_v) for f_v in f_unused)}")
    return "; ".join(f_parts)


def _formatCell(f_kind_spec: Dict[str, Any], f_col: int, f_cell: str) -> str:
    """One cell of a report row as the paper writes it.

    Raises:
        PaperDataError: a number column holds something else.
    """
    f_first, f_last = f_kind_spec["decimals"]
    if f_first <= f_col <= f_last:
        return _twoDecimals(f_cell)
    f_optional = f_kind_spec["optional_decimals"]
    if f_optional is not None and f_optional[0] <= f_col <= f_optional[1]:
        if _FLOAT_RE.match(f_cell):
            return _twoDecimals(f_cell)
        if f_cell not in ("", "NA") and not _INT_RE.match(f_cell):
            raise PaperDataError(f"{f_cell!r} is not NA, an integer or a decimal")
        return f_cell
    if f_col == f_kind_spec["integer"] and _FLOAT_RE.match(f_cell):
        return str(int(Decimal(f_cell)))
    return f_cell


def formatRow(f_kind: str, f_row: Sequence[str]) -> List[str]:
    """One report row as the paper writes it: node and stripe counts without padding, the
    measurements with two decimals (an empty one as 0.00), IOR's aggs(MiB) as an integer,
    the rest as is. A row shorter than the header (a run cut short) is padded with empty
    cells.

    Raises:
        PaperDataError: a measurement is not a finite number, or the row is wider than the
            header.
    """
    f_kind_spec = KINDS[f_kind]
    f_out = [str(int(f_row[0])), str(int(f_row[1])), f_row[2].strip(), f_row[3].strip()]
    if len(f_row) > len(f_kind_spec["header"]):
        f_key = (int(f_row[0]), int(f_row[1]), f_out[2], f_out[3])
        raise PaperDataError(
            f"the row for {_describe(f_key)} has {len(f_row)} columns, more than the "
            f"header's {len(f_kind_spec['header'])}"
        )
    for f_col in range(4, len(f_row)):
        try:
            f_out.append(_formatCell(f_kind_spec, f_col, f_row[f_col].strip()))
        except PaperDataError as f_err:
            f_name = f_kind_spec["header"][f_col] if f_col < len(f_kind_spec["header"]) else f_col
            f_key = (int(f_row[0]), int(f_row[1]), f_out[2], f_out[3])
            raise PaperDataError(f"{f_err} in column '{f_name}' of the row for {_describe(f_key)}")
    f_out += [""] * (len(f_kind_spec["header"]) - len(f_out))
    return f_out


def _placeholderRow(
    f_kind: str,
    f_key: RowKey,
    f_rows: Dict[RowKey, List[str]],
    f_rules: Sequence[PlaceholderRule] = (),
    f_fill: str = FILL_ZERO,
) -> List[str]:
    """A row for a run that has no report row. With fill nan its measurements are nan and
    its other columns NA. With fill zero its measurements are zeros, and an IOR row also
    keeps the settings of another node count's run, the preceding one unless a rule names
    one.

    Raises:
        PaperDataError: an IOR row with fill zero has no run to copy its settings from.
    """
    f_node, f_stripes, f_block_size, f_op = f_key
    f_first, f_last = KINDS[f_kind]["zeroed"]
    f_width = len(KINDS[f_kind]["header"])
    if f_fill == FILL_NAN:
        # only the measurements are nan; settings such as LSMIO's Iterations are NA
        f_m_first, f_m_last = KINDS[f_kind]["measured"]
        f_base = [str(f_node), str(f_stripes), f_block_size, f_op] + ["NA"] * (f_width - 4)
        for f_col in range(f_m_first, f_m_last + 1):
            f_base[f_col] = "nan"
        return f_base
    if f_kind == "ior":
        f_from: Optional[int] = None
        for f_rule in f_rules:
            if f_rule.selection.selects(f_key):
                f_from = f_rule.copy_from_node
                break
        if f_from is None:
            f_before = [f_k[0] for f_k in f_rows if f_k[1:] == f_key[1:] and f_k[0] < f_node]
            if not f_before:
                raise PaperDataError(
                    f"no earlier node count to copy the placeholder for {_describe(f_key)} from"
                )
            f_from = max(f_before)
        f_source_key = (f_from, f_stripes, f_block_size, f_op)
        if f_source_key not in f_rows:
            raise PaperDataError(
                f"no run for {_describe(f_source_key)} to copy the placeholder for "
                f"{_describe(f_key)} from"
            )
        f_base = formatRow(f_kind, f_rows[f_source_key])
    else:
        f_base = [str(f_node), str(f_stripes), f_block_size, f_op] + ["0.00"] * (f_width - 4)
    f_base[0] = str(f_node)
    for f_col in range(f_first, f_last + 1):
        f_base[f_col] = "0.00"
    return f_base


class DatasetResult:
    """The built lines of one TSV and where its rows came from."""

    def __init__(
        self,
        f_spec: DatasetSpec,
        f_lines: List[str],
        f_provenance: List[str],
        f_placeholders: List[RowKey],
        f_padded: Optional[List[RowKey]] = None,
        f_empty: Optional[List[RowKey]] = None,
    ) -> None:
        self.spec: DatasetSpec = f_spec
        self.lines: List[str] = f_lines
        self.provenance: List[str] = f_provenance
        self.placeholders: List[RowKey] = f_placeholders
        self.padded: List[RowKey] = f_padded if f_padded is not None else []
        self.empty: List[RowKey] = f_empty if f_empty is not None else []


def buildDataset(f_spec: DatasetSpec, f_data_dir: str) -> DatasetResult:
    """Build the lines of one TSV (header first, no line ends) from its reports.

    Raises:
        PaperDataError: a report is missing, empty, malformed or lists a run twice; a
            measurement is not a number; a run has only some of its measurements; a row
            is outside the grid; a stitch or placeholder rule applies to no run; or a run
            is missing or has no measurements and the spec says missing is an error.
    """
    f_kind_spec = KINDS[f_spec.kind]
    f_report = f_kind_spec["report"]
    f_rows = readReport(os.path.join(f_data_dir, f_spec.source, f_report))
    f_origin: Dict[RowKey, str] = {f_key: f_spec.source for f_key in f_rows}
    f_stitched: Dict[RowKey, str] = {}  # the runs a stitch rule has taken, by rule source
    for f_rule in f_spec.stitch:
        f_rule_rows = readReport(os.path.join(f_data_dir, f_rule.source, f_report))
        f_taken = [f_key for f_key in f_rule_rows if f_rule.selection.selects(f_key)]
        if not f_taken:
            raise PaperDataError(f"{f_spec.output}: stitch from {f_rule.source} selects no row")
        f_unused = _unusedValues(f_rule.selection, f_taken)
        if f_unused:
            raise PaperDataError(
                f"{f_spec.output}: stitch from {f_rule.source} selects no row for {f_unused}"
            )
        for f_key in f_taken:
            if f_key in f_stitched:
                raise PaperDataError(
                    f"{f_spec.output}: stitch rules from {f_stitched[f_key]} and "
                    f"{f_rule.source} both select the run for {_describe(f_key)}"
                )
            f_stitched[f_key] = f_rule.source
            f_rows[f_key] = f_rule_rows[f_key]
            f_origin[f_key] = f_rule.source
    f_grid = f_spec.grid
    f_nodes = sorted(set(f_grid.nodes if f_grid.nodes is not None else (k[0] for k in f_rows)))
    if f_grid.stripes is None and f_grid.block_sizes is None and f_grid.ops is None:
        f_combos = sorted({f_key[1:] for f_key in f_rows})
    else:
        f_stripe_values = f_grid.stripes if f_grid.stripes is not None else {k[1] for k in f_rows}
        f_size_values = (
            f_grid.block_sizes if f_grid.block_sizes is not None else {k[2] for k in f_rows}
        )
        f_op_values = f_grid.ops if f_grid.ops is not None else {k[3] for k in f_rows}
        f_combos = sorted(
            {
                (f_s, f_b, f_o)
                for f_s in f_stripe_values
                for f_b in f_size_values
                for f_o in f_op_values
            }
        )
    f_combo_set = set(f_combos)
    f_outside = sorted(
        f_key for f_key in f_rows if f_key[0] not in f_nodes or f_key[1:] not in f_combo_set
    )
    if f_outside:
        raise PaperDataError(
            f"{f_spec.output}: {len(f_outside)} run(s) outside the grid, the first for "
            f"{_describe(f_outside[0])}"
        )
    # A run with every measurement empty (a failed run) has no data, like a missing one, and
    # is written as fill says; a run with only some of them empty is an error
    f_m_first, f_m_last = f_kind_spec["measured"]
    f_empty: List[RowKey] = []
    for f_key in sorted(f_rows):
        f_cells = [
            f_rows[f_key][f_col] if f_col < len(f_rows[f_key]) else ""
            for f_col in range(f_m_first, f_m_last + 1)
        ]
        if all(f_cells):
            continue
        if any(f_cells):
            raise PaperDataError(
                f"{f_spec.output}: the run for {_describe(f_key)} has only some of its measurements"
            )
        if f_spec.missing == MISSING_ERROR:
            raise PaperDataError(f"{f_spec.output}: the run for {_describe(f_key)} has no data")
        f_empty.append(f_key)
    f_placeholders: List[RowKey] = []
    for f_combo in f_combos:
        for f_node in f_nodes:
            f_key = (f_node,) + f_combo
            if f_key in f_rows:
                continue
            if f_spec.missing == MISSING_ERROR:
                raise PaperDataError(f"{f_spec.output}: no run for {_describe(f_key)}")
            f_placeholders.append(f_key)
    for f_pos, f_rule in enumerate(f_spec.placeholders):
        f_matched = [f_key for f_key in f_placeholders if f_rule.selection.selects(f_key)]
        if not f_matched:
            raise PaperDataError(
                f"{f_spec.output}: placeholder rule {f_pos} applies to no missing run; "
                f"remove it if the run now exists"
            )
        f_unused = _unusedValues(f_rule.selection, f_matched)
        if f_unused:
            raise PaperDataError(
                f"{f_spec.output}: placeholder rule {f_pos} matches no missing run for "
                f"{f_unused}; remove those values if the runs now exist"
            )
    f_header_width = len(f_kind_spec["header"])
    f_padded = sorted(f_key for f_key, f_row in f_rows.items() if len(f_row) < f_header_width)
    try:
        f_out_rows: Dict[RowKey, List[str]] = {
            f_key: formatRow(f_spec.kind, f_row) for f_key, f_row in f_rows.items()
        }
        for f_key in f_placeholders:
            f_out_rows[f_key] = _placeholderRow(
                f_spec.kind, f_key, f_rows, f_spec.placeholders, f_spec.fill
            )
            f_origin[f_key] = "placeholder"
    except PaperDataError as f_err:
        raise PaperDataError(f"{f_spec.output}: {f_err}")
    if f_spec.fill == FILL_NAN:
        # a failed run keeps its reported settings (LSMIO's Iterations too); only its empty
        # measurements become nan
        for f_key in f_empty:
            for f_col in range(f_m_first, f_m_last + 1):
                f_out_rows[f_key][f_col] = "nan"
    f_order = sorted(f_out_rows, key=lambda f_k: (f_k[1], f_k[2], f_k[3], f_k[0]))
    f_lines = ["\t".join(f_kind_spec["header"])]
    f_lines += ["\t".join(f_out_rows[f_key]) for f_key in f_order]
    f_counts: Dict[str, int] = {}
    for f_key in f_order:
        f_counts[f_origin[f_key]] = f_counts.get(f_origin[f_key], 0) + 1
    f_provenance = [f"{f_source}: {f_count} rows" for f_source, f_count in f_counts.items()]
    return DatasetResult(f_spec, f_lines, f_provenance, sorted(f_placeholders), f_padded, f_empty)


def writeLines(f_path: str, f_lines: Sequence[str]) -> None:
    """Write f_lines with CRLF line ends, the last one too, as the paper's TSVs have."""
    os.makedirs(os.path.dirname(f_path) or ".", exist_ok=True)
    with open(f_path, "w", newline="") as f_file:
        for f_line in f_lines:
            f_file.write(f_line + LINE_END)


def generate(f_sources: PaperSources, f_data_dir: str, f_output_dir: str) -> List[DatasetResult]:
    """Rebuild every dataset's TSV under f_output_dir. Runs without data (placeholders and
    failed runs, written as nan or zeros as the dataset's fill says) and rows padded to the
    header's width are logged as warnings; the caller reports the written files from the
    results.

    Every dataset is built before anything is written, and the TSVs are written to
    temporary names first and renamed into place once all of them were written, so a
    dataset that cannot be built or a file that cannot be written leaves the existing
    TSVs as they were. Only a rename failing midway, which is rare once every temporary
    file is written, can leave some of them replaced.

    Raises:
        PaperDataError: see buildDataset; or an output file cannot be written.
    """
    f_results = [buildDataset(f_spec, f_data_dir) for f_spec in f_sources.datasets]
    for f_result in f_results:
        f_path = os.path.join(f_output_dir, f_result.spec.output)
        if os.path.isdir(f_path):
            raise PaperDataError(f"cannot write the output: {f_path} is a directory")
    f_staged: List[Tuple[str, str]] = []
    try:
        for f_result in f_results:
            f_path = os.path.join(f_output_dir, f_result.spec.output)
            f_staged.append((f_path + ".tmp", f_path))
            writeLines(f_path + ".tmp", f_result.lines)
        for f_tmp, f_path in f_staged:
            os.replace(f_tmp, f_path)
    except OSError as f_err:
        raise PaperDataError(f"cannot write the output: {f_err}")
    finally:
        for f_tmp, _ in f_staged:
            if os.path.exists(f_tmp):
                try:
                    os.remove(f_tmp)
                except OSError:
                    pass
    for f_result in f_results:
        f_output = f_result.spec.output
        f_written = "nan (a gap)" if f_result.spec.fill == FILL_NAN else "zeros"
        for f_key in f_result.placeholders:
            Console.warning(
                f"  {f_output}: no run for {_describe(f_key)}; written as a placeholder of "
                f"{f_written}"
            )
        for f_key in f_result.empty:
            Console.warning(
                f"  {f_output}: the run for {_describe(f_key)} has no data (a failed run); "
                f"written as {f_written}"
            )
        for f_key in f_result.padded:
            Console.warning(
                f"  {f_output}: the run for {_describe(f_key)} has fewer columns than the "
                f"header (a run cut short); padded with empty cells"
            )
    return f_results


def readSeries(f_tsv_path: str, f_series: SeriesSpec) -> Tuple[List[int], List[float]]:
    """The (node count, max bandwidth) points of one series of a paper TSV, by node count.

    Raises:
        PaperDataError: the TSV cannot be read or has a malformed row.
    """
    f_points: List[Tuple[int, float]] = []
    try:
        with open(f_tsv_path, newline="") as f_file:
            for f_row in csv.reader(f_file, delimiter="\t"):
                if len(f_row) < 5 or not f_row[0].strip().isdigit():
                    continue
                if (
                    int(f_row[1]) == f_series.stripes
                    and f_row[2] == f_series.block_size
                    and f_row[3] == f_series.op
                ):
                    f_points.append((int(f_row[0]), float(f_row[4])))
    except OSError as f_err:
        raise PaperDataError(f"cannot read {f_tsv_path}: {f_err}")
    except (ValueError, csv.Error) as f_err:
        raise PaperDataError(f"malformed row in {f_tsv_path}: {f_err}")
    f_points.sort()
    return [f_x for f_x, _ in f_points], [f_y for _, f_y in f_points]
