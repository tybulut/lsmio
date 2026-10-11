#
# Copyright 2023 Serdar Bulut
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

import csv
import glob
import math
import os
import re
from typing import Dict, List, Union, Tuple, Any, Optional, Sequence
from lsmiotool.lib.compat import TypedDict, Final

from lsmiotool.lib.debuggable import DebuggableObject
from lsmiotool.lib.log import Console


def parseFloat(f_val: Any, f_fallback: float = 0.0) -> float:
    """Robustly parse float with sentinel fallback.

    Args:
        f_val: Value to convert to float.
        f_fallback: Fallback value if conversion fails (default 0.0).

    Returns:
        Converted float value or fallback.
    """
    if f_val is None:
        return f_fallback
    try:
        val_str = str(f_val).strip()
        if not val_str or val_str.upper() in ["NA", "NAN", "N/A", "NULL", "NONE"]:
            return f_fallback
        return float(val_str)
    except (ValueError, TypeError):
        return f_fallback


def parseInt(f_val: Any, f_fallback: int = 0) -> int:
    """Robustly parse integer with sentinel fallback.

    Args:
        f_val: Value to convert to integer.
        f_fallback: Fallback value if conversion fails (default 0).

    Returns:
        Converted int value or fallback.
    """
    if f_val is None:
        return f_fallback
    try:
        val_str = str(f_val).strip()
        if not val_str or val_str.upper() in ["NA", "NAN", "N/A", "NULL", "NONE"]:
            return f_fallback
        return int(float(val_str))
    except (ValueError, TypeError):
        return f_fallback


# IOR's summary header names two columns 'StdDev' (MiB/s, then OPs); the second one is
# keyed under this name so it does not overwrite the first
IOR_OPS_STDDEV_KEY: Final[str] = "StdDev(OPs)"


def iorSummaryKeys(f_heads: Sequence[str]) -> List[str]:
    """Unique dictionary keys for IOR summary header names, in column order.

    The second 'StdDev' becomes IOR_OPS_STDDEV_KEY; any other repeated name gets a
    '#<n>' suffix.
    """
    f_keys: List[str] = []
    f_seen: Dict[str, int] = {}
    for f_head in f_heads:
        f_count = f_seen.get(f_head, 0) + 1
        f_seen[f_head] = f_count
        if f_count == 1:
            f_keys.append(f_head)
        elif f_head == "StdDev" and f_count == 2:
            f_keys.append(IOR_OPS_STDDEV_KEY)
        else:
            f_keys.append(f"{f_head}#{f_count}")
    return f_keys


class RunDataMetrics(TypedDict):
    """Metrics for a single run."""

    max_mib: float  # Max(MiB)
    min_mib: float  # Min(MiB)
    mean_mib: float  # Mean(MiB)
    stddev: float  # StdDev
    max_ops: float  # Max(OPs)
    min_ops: float  # Min(OPs)
    mean_ops: float  # Mean(OPs)


class RunData(TypedDict):
    """Data for read/write operations."""

    read: Dict[str, Union[float, str]]
    write: Dict[str, Union[float, str]]


class IorSingleRunData(DebuggableObject):
    """Process single IOR run data."""

    m_file_name: str
    m_run_data: RunData

    def __init__(self, f_file_name: str) -> None:
        """Initialize IOR single run data processor.

        Args:
            f_file_name: Path to IOR output file
        """
        super().__init__()
        self.m_file_name = f_file_name
        self.m_run_data = {"read": {}, "write": {}}
        # Summary of all tests:
        # Operation   Max(MiB)   Min(MiB)  Mean(MiB)     StdDev   Max(OPs)   Min(OPs)  Mean(OPs)     StdDev    Mean(s) Stonewall(s) Stonewall(MiB) Test# #Tasks tPN reps fPP reord reordoff reordrand seed segcnt   blksiz    xsize aggs(MiB)   API RefNum
        # write        4214.58    2752.91    3571.98     466.80    4214.58    2752.91    3571.98     466.80    0.14599         NA            NA     0      4   1   10   0     0        1         0    0    128  1048576  1048576     512.0 POSIX      0
        # read        14959.41   10729.26   13695.54    1195.05   14959.41   10729.26   13695.54    1195.05    0.03771         NA            NA     0      4   1   10   0     0        1         0    0    128  1048576  1048576     512.0 POSIX      0
        try:
            with open(f_file_name, newline="") as infile:
                head_line = ""
                read_line = ""
                write_line = ""
                found_summary = False
                for line in infile:
                    if not found_summary:
                        if line.startswith("Summary of all tests"):
                            found_summary = True
                        continue
                    if line.startswith("Operation   Max(MiB)"):
                        head_line = line
                        continue
                    if line.startswith("write"):
                        write_line = line
                        continue
                    if line.startswith("read"):
                        read_line = line
                        continue
                    if head_line and read_line and write_line:
                        break
                heads = iorSummaryKeys(
                    head_line.rstrip().split()[1:] if head_line else []
                )
                reads = read_line.rstrip().split()[1:] if read_line else []
                writes = write_line.rstrip().split()[1:] if write_line else []
                numeric_fields = [
                    "Max(MiB)",
                    "Min(MiB)",
                    "Mean(MiB)",
                    "StdDev",
                    "Max(OPs)",
                    "Min(OPs)",
                    "Mean(OPs)",
                    IOR_OPS_STDDEV_KEY,
                ]
                for i in range(len(heads)):
                    h = heads[i]
                    if h in numeric_fields:
                        r_val = parseFloat(reads[i]) if i < len(reads) else 0.0
                        w_val = parseFloat(writes[i]) if i < len(writes) else 0.0
                        self.m_run_data["read"][h] = r_val
                        self.m_run_data["write"][h] = w_val
                    else:
                        self.m_run_data["read"][h] = reads[i] if i < len(reads) else ""
                        self.m_run_data["write"][h] = (
                            writes[i] if i < len(writes) else ""
                        )
        except (IOError, OSError) as err:
            Console.debug(f"IorSingleRunData: error opening {f_file_name}: {err}")

    @property
    def file_name(self) -> str:
        return self.m_file_name

    @property
    def run_data(self) -> RunData:
        return self.m_run_data

    def getMap(self) -> RunData:
        """Get the run data map.

        Returns:
            Dictionary containing read/write metrics
        """
        return self.m_run_data

    get_map = getMap


class LsmioSingleRunData(DebuggableObject):
    """Process single LSMIO run data."""

    m_file_name: str
    m_run_data: RunData
    m_iter_data: Dict[str, List[float]]

    def __init__(self, f_file_name: str) -> None:
        """Initialize LSMIO single run data processor.

        Args:
            f_file_name: Path to LSMIO output file
        """
        super().__init__()
        self.m_file_name = f_file_name
        self.m_run_data = {"read": {}, "write": {}}
        self.m_iter_data = {"read": [], "write": []}
        # Bench-WRITE: RocksDB SYN: false BLF: false
        # access,bw(MiB/s),Latency(ms),block(KiB),xfer(KiB),iter
        # ------,---------,----------,----------,---------,----
        # write,167.46,1.529,1048576,1048576,10
        #
        # Bench-READ: RocksDB SYN: false BLF: false
        # access,bw(MiB/s),Latency(ms),block(KiB),xfer(KiB),iter
        # ------,---------,----------,----------,---------,----
        # read,320.78,0.798,1048576,1048576,10
        #
        try:
            with open(f_file_name, newline="") as infile:
                head_line = ""
                read_line = ""
                write_line = ""
                found_w_summary = False
                found_r_summary = False
                for line in infile:
                    line_s = line.strip()
                    if line_s.startswith("iwrite,"):
                        parts = line_s.split(",")
                        if len(parts) > 1:
                            self.m_iter_data["write"].append(parseFloat(parts[1]))
                    elif line_s.startswith("iread,"):
                        parts = line_s.split(",")
                        if len(parts) > 1:
                            self.m_iter_data["read"].append(parseFloat(parts[1]))
                    if not found_w_summary and not write_line:
                        if line.startswith("Bench-WRITE:"):
                            found_w_summary = True
                            continue
                    if found_w_summary:
                        if line.startswith("access,"):
                            head_line = line
                        if line.startswith("write"):
                            found_w_summary = False
                            write_line = line
                        continue
                    if not found_r_summary and not read_line:
                        if line.startswith("Bench-READ:"):
                            found_r_summary = True
                            continue
                    if found_r_summary:
                        if line.startswith("read"):
                            found_r_summary = False
                            read_line = line
                        continue
                heads = head_line.rstrip().split(",")[1:] if head_line else []
                reads = read_line.rstrip().split(",")[1:] if read_line else []
                writes = write_line.rstrip().split(",")[1:] if write_line else []
                numeric_fields = [
                    "bw(MiB/s)",
                    "Latency(ms)",
                    "block(KiB)",
                    "xfer(KiB)",
                    "max(MiB)/s",
                    "min(MiB/s)",
                    "mean(MiB/s)",
                    "total(MiB)",
                    "total(Ops)",
                ]
                for i in range(len(heads)):
                    h = heads[i]
                    if h in numeric_fields:
                        r_val = parseFloat(reads[i]) if i < len(reads) else 0.0
                        w_val = parseFloat(writes[i]) if i < len(writes) else 0.0
                        self.m_run_data["read"][h] = r_val
                        self.m_run_data["write"][h] = w_val
                    else:
                        self.m_run_data["read"][h] = reads[i] if i < len(reads) else ""
                        self.m_run_data["write"][h] = (
                            writes[i] if i < len(writes) else ""
                        )
        except (IOError, OSError) as err:
            Console.debug(f"LsmioSingleRunData: error opening {f_file_name}: {err}")

    @property
    def file_name(self) -> str:
        return self.m_file_name

    @property
    def run_data(self) -> RunData:
        return self.m_run_data

    @property
    def iter_data(self) -> Dict[str, List[float]]:
        return self.m_iter_data

    def getMap(self) -> RunData:
        """Get the run data map.

        Returns:
            Dictionary containing read/write metrics
        """
        return self.m_run_data

    get_map = getMap

    def getIterData(self) -> Dict[str, List[float]]:
        """Get iteration performance data.

        Returns:
            Dictionary mapping access type to list of iteration bandwidths.
        """
        return self.m_iter_data

    get_iter_data = getIterData


class LmpSingleRunData(DebuggableObject):
    """Process single LMP run data."""

    m_file_name: str
    m_bmtool_line: Optional[str]
    m_run_data: Dict[str, Any]
    m_iter_data: Dict[str, List[float]]

    def __init__(self, f_file_name: str) -> None:
        """Initialize LMP single run data processor.

        Mirrors tools/bmtool/parse/lmp-parse.sh: the last line matching '^.write,'
        (LSMIO's per-iteration 'iwrite,<MiB/s>,...' lines in an LSMIO-enabled LAMMPS
        log) is the run's result line, and its second comma field the write
        throughput. Logs without such a line fall back to the first number of the
        last 'write,' / 'write:' line.

        Args:
            f_file_name: Path to LMP output file
        """
        super().__init__()
        self.m_file_name = f_file_name
        self.m_bmtool_line = None
        self.m_run_data = {
            "write": {"throughput": 0.0, "bw(MiB/s)": 0.0},
            "read": {"throughput": 0.0, "bw(MiB/s)": 0.0},
        }
        self.m_iter_data = {"write": [], "read": []}
        try:
            f_lines = readBmtoolLines(f_file_name)
        except (IOError, OSError) as err:
            Console.debug(f"LmpSingleRunData: error opening {f_file_name}: {err}")
            return

        f_fallback: Optional[float] = None
        for f_line in f_lines:
            if isLmpResultLine(f_line):
                self.m_bmtool_line = f_line
                self.m_iter_data["write"].append(lmpLineThroughput(f_line))
                continue
            f_stripped = f_line.strip()
            if f_stripped.startswith("write,") or f_stripped.startswith("write:"):
                f_fallback = lmpLineThroughput(f_stripped)

        if self.m_bmtool_line is not None:
            f_val = lmpLineThroughput(self.m_bmtool_line)
        elif f_fallback is not None:
            f_val = f_fallback
            self.m_iter_data["write"].append(f_val)
        else:
            return
        self.m_run_data["write"]["throughput"] = f_val
        self.m_run_data["write"]["bw(MiB/s)"] = f_val

    @property
    def bmtool_line(self) -> Optional[str]:
        return self.m_bmtool_line

    @property
    def bmtoolLine(self) -> Optional[str]:
        """The last '^.write,' line (lmp-parse.sh's result line), or None."""
        return self.m_bmtool_line

    @property
    def file_name(self) -> str:
        return self.m_file_name

    @property
    def run_data(self) -> Dict[str, Any]:
        return self.m_run_data

    @property
    def iter_data(self) -> Dict[str, List[float]]:
        return self.m_iter_data

    def getMap(self) -> Dict[str, Any]:
        """Get the run data map.

        Returns:
            Dictionary containing LMP metrics
        """
        return self.m_run_data

    get_map = getMap

    def getIterData(self) -> Dict[str, List[float]]:
        """Get iteration performance data.

        Returns:
            Dictionary mapping access type to list of iteration metrics.
        """
        return self.m_iter_data

    get_iter_data = getIterData


class PartData(TypedDict):
    """Performance data for a single part."""

    maxMB: float
    minMB: float
    meanMB: float


class CsvData(TypedDict):
    """CSV data structure."""

    read: Dict[int, Dict[str, Dict[int, PartData]]]
    write: Dict[int, Dict[str, Dict[int, PartData]]]


class IorSummaryData(DebuggableObject):
    """Process IOR summary data."""

    m_file_name: str
    m_csv_data: Dict[str, Dict[int, Dict[str, Dict[int, PartData]]]]

    def __init__(self, f_file_name: str) -> None:
        """Initialize IOR summary data processor.

        Args:
            f_file_name: Path to IOR summary CSV file
        """
        super().__init__()
        self.m_file_name = f_file_name
        self.m_csv_data = {}
        # N,Stripes,BlockSize,Operation,Max(MiB),Min(MiB),Mean(MiB),StdDev,...
        # 1,16,8M,read,5353.38,5160.61,5293.08,49.88,66...
        try:
            with open(f_file_name, newline="") as csvfile:
                csv_reader = csv.reader(csvfile, delimiter=",", quotechar="|")
                for row in csv_reader:
                    if not row or len(row) < 4:
                        continue
                    access = row[3].strip()
                    if access not in self.m_csv_data:
                        self.m_csv_data[access] = {}
                    num_stripes = parseInt(row[1], 0)
                    if num_stripes not in self.m_csv_data[access]:
                        self.m_csv_data[access][num_stripes] = {}
                    stripe_size = row[2].strip()
                    if stripe_size not in self.m_csv_data[access][num_stripes]:
                        self.m_csv_data[access][num_stripes][stripe_size] = {}
                    num_nodes = parseInt(row[0], 0)
                    if (
                        num_nodes
                        not in self.m_csv_data[access][num_stripes][stripe_size]
                    ):
                        self.m_csv_data[access][num_stripes][stripe_size][
                            num_nodes
                        ] = {}
                    part_data: PartData = {
                        "maxMB": float(0.00),
                        "minMB": float(0.00),
                        "meanMB": float(0.00),
                    }
                    if len(row) > 4 and row[4]:
                        part_data["maxMB"] = parseFloat(row[4])
                    if len(row) > 5 and row[5]:
                        part_data["minMB"] = parseFloat(row[5])
                    if len(row) > 6 and row[6]:
                        part_data["meanMB"] = parseFloat(row[6])
                    self.m_csv_data[access][num_stripes][stripe_size][num_nodes] = (
                        part_data
                    )
        except (IOError, OSError) as err:
            Console.debug(f"IorSummaryData: error opening {f_file_name}: {err}")

    @property
    def file_name(self) -> str:
        return self.m_file_name

    @property
    def csv_data(self) -> Dict[str, Dict[int, Dict[str, Dict[int, PartData]]]]:
        return self.m_csv_data

    def timeSeries(
        self, f_read: bool, f_num_stripes: int, f_stripe_size: str
    ) -> Tuple[List[int], List[float]]:
        """Get time series data for the specified parameters.

        Args:
            f_read: Whether to get read or write data
            f_num_stripes: Number of stripes
            f_stripe_size: Size of stripes

        Returns:
            Tuple of node counts and corresponding performance values
        """
        access = "read" if f_read else "write"
        x_series: List[int] = []
        y_series: List[float] = []
        if access in self.m_csv_data:
            if f_num_stripes in self.m_csv_data[access]:
                if f_stripe_size in self.m_csv_data[access][f_num_stripes]:
                    for num_nodes in sorted(
                        self.m_csv_data[access][f_num_stripes][f_stripe_size].keys()
                    ):
                        x_series.append(num_nodes)
                        y_series.append(
                            self.m_csv_data[access][f_num_stripes][f_stripe_size][
                                num_nodes
                            ]["maxMB"]
                        )
        return x_series, y_series

    time_series = timeSeries


class LsmioSummaryData(IorSummaryData):
    """Process LSMIO summary data."""

    def __init__(self, f_file_name: str) -> None:
        """Initialize LSMIO summary data processor.

        Args:
            f_file_name: Path to LSMIO summary CSV file
        """
        super().__init__(f_file_name)


class LmpSummaryData(DebuggableObject):
    """Process LMP summary data."""

    m_file_name: str
    m_csv_data: Dict[str, Dict[int, Dict[str, Dict[int, PartData]]]]

    def __init__(self, f_file_name: str) -> None:
        """Initialize LMP summary data processor.

        Reads bmtool's lmp-parse.sh rows `$n,$rf,$bs,<matched log line>` (e.g.
        `8,4,64K,iwrite,512.3,512.3,512.3,18.25,1,1`: the throughput is the field
        after the 'iwrite' label) as well as `$n,$rf,$bs,$throughput` and
        `$n,$rf,$bs,write,$throughput,...`.

        Args:
            f_file_name: Path to LMP summary CSV file
        """
        super().__init__()
        self.m_file_name = f_file_name
        self.m_csv_data = {"write": {}}
        try:
            with open(f_file_name, newline="") as csvfile:
                csv_reader = csv.reader(csvfile, delimiter=",", quotechar="|")
                for row in csv_reader:
                    if not row or len(row) < 4:
                        continue
                    num_nodes = parseInt(row[0], 0)
                    num_stripes = parseInt(row[1], 0)
                    stripe_size = row[2].strip()

                    # Determine access type and value column. bmtool rows carry the
                    # whole matched log line after n,rf,bs ('iwrite,<MiB/s>,...'), so a
                    # label ending in write/read is followed by the throughput
                    f_label = row[3].strip().lower()
                    if f_label.endswith("write") or f_label.endswith("read"):
                        access = "read" if f_label.endswith("read") else "write"
                        val = lmpLineThroughput(",".join(row[3:]))
                    else:
                        access = "write"
                        val = parseFloat(row[3])

                    if access not in self.m_csv_data:
                        self.m_csv_data[access] = {}
                    if num_stripes not in self.m_csv_data[access]:
                        self.m_csv_data[access][num_stripes] = {}
                    if stripe_size not in self.m_csv_data[access][num_stripes]:
                        self.m_csv_data[access][num_stripes][stripe_size] = {}

                    part_data: PartData = {
                        "maxMB": val,
                        "minMB": val,
                        "meanMB": val,
                    }
                    self.m_csv_data[access][num_stripes][stripe_size][num_nodes] = (
                        part_data
                    )
        except (IOError, OSError) as err:
            Console.debug(f"LmpSummaryData: error opening {f_file_name}: {err}")

    @property
    def file_name(self) -> str:
        return self.m_file_name

    @property
    def csv_data(self) -> Dict[str, Dict[int, Dict[str, Dict[int, PartData]]]]:
        return self.m_csv_data

    def timeSeries(
        self, f_read: bool, f_num_stripes: int, f_stripe_size: str
    ) -> Tuple[List[int], List[float]]:
        """Get time series data for LMP benchmark parameters.

        Args:
            f_read: Whether to get read or write data (LMP is typically write-only)
            f_num_stripes: Number of stripes
            f_stripe_size: Size of stripes

        Returns:
            Tuple of node counts and corresponding performance values
        """
        access = "read" if f_read else "write"
        x_series: List[int] = []
        y_series: List[float] = []
        if access in self.m_csv_data:
            if f_num_stripes in self.m_csv_data[access]:
                if f_stripe_size in self.m_csv_data[access][f_num_stripes]:
                    for num_nodes in sorted(
                        self.m_csv_data[access][f_num_stripes][f_stripe_size].keys()
                    ):
                        x_series.append(num_nodes)
                        y_series.append(
                            self.m_csv_data[access][f_num_stripes][f_stripe_size][
                                num_nodes
                            ]["maxMB"]
                        )
        return x_series, y_series

    time_series = timeSeries


# ---------------------------------------------------------------------------
# bmtool parity: tools/bmtool/parse/lsmio-parse.sh replica
#
# generate_aggregates() greps every rank file N/*/out-*-<rf>-<bs>-*.txt*, sums
# columns 2-6 of the 'write,' and 'read,' lines across ranks and keeps the max
# of column 7 (awk, default OFMT %.6g); generate_report() turns the last two
# write/read lines of every N/agg-<rf>-<bs>-report.csv into
# 'N,rf,bs,<access>,...' rows of lsm-report.csv. Everything below reproduces
# that output byte for byte.
# ---------------------------------------------------------------------------

# Node counts lsmio-parse.sh generate_aggregates() visits for each scale
BMTOOL_SCALE_NODES: Final[Dict[str, Tuple[str, ...]]] = {
    "bake": ("1", "2", "4", "8"),
    "small": ("1", "2", "4", "8", "16", "24", "32", "40", "48"),
    "large": ("1", "2", "4", "8", "16", "32", "48", "64"),
    "variants": ("8",),
    "baseline": ("8",),
    "local": ("1",),
}
BMTOOL_STRIPE_COUNTS: Final[Tuple[str, ...]] = ("4", "16")
BMTOOL_BLOCK_SIZES: Final[Tuple[str, ...]] = ("64K", "1M", "8M")
LSM_REPORT_FILE: Final[str] = "lsm-report.csv"

_AWK_SPACE: Final[str] = " \t\n\r\f\v"
_AWK_NUM_PREFIX_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_AWK_STRNUM_RE = re.compile(
    r"^[ \t\n\r\f\v]*[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?[ \t\n\r\f\v]*$"
)


def awkToNumber(f_text: str) -> float:
    """Convert a field to a number the way awk does (leading numeric prefix, else 0)."""
    f_match = _AWK_NUM_PREFIX_RE.match(f_text.lstrip(_AWK_SPACE))
    return float(f_match.group(0)) if f_match else 0.0


def awkIsStrNum(f_text: str) -> bool:
    """Return True when awk treats a field as a numeric string in comparisons."""
    return bool(_AWK_STRNUM_RE.match(f_text))


def formatAwkNumber(f_val: float) -> str:
    """Format a number as awk's print does: integral values as %d, others with OFMT %.6g."""
    if math.isfinite(f_val) and f_val == math.floor(f_val) and abs(f_val) < 2**63:
        return str(int(f_val))
    return "%.6g" % f_val


def bmtoolCollationKey(f_text: str) -> Tuple[str, str, str]:
    """Sort key reproducing the order of a shell glob under glibc en_US.UTF-8 collation.

    Punctuation ('/', '-', '.', ':') is ignored at the first level and case is folded,
    so '16/agg-...' sorts before '1/agg-...' exactly as in bmtool-produced reports.
    """
    f_primary = "".join(f_ch.lower() for f_ch in f_text if f_ch.isalnum())
    return (f_primary, f_text.lower(), f_text)


def bmtoolGlob(f_dir: str, f_pattern: str) -> List[str]:
    """Expand '<f_dir>/<f_pattern>' in shell-glob order (see bmtoolCollationKey)."""
    f_paths = glob.glob(os.path.join(glob.escape(f_dir), f_pattern))
    return sorted(f_paths, key=bmtoolCollationKey)


def readBmtoolLines(f_path: str) -> List[str]:
    """Read a file as grep sees it: '\\n'-separated lines, bytes preserved (no CR stripping).

    Raises:
        OSError: If the file cannot be read.
    """
    with open(f_path, "rb") as f_f:
        f_text = f_f.read().decode("utf-8", errors="surrogateescape")
    f_lines = f_text.split("\n")
    if f_lines and f_lines[-1] == "":
        f_lines.pop()
    return f_lines


def writeBmtoolLines(f_path: str, f_lines: Sequence[str]) -> None:
    """Write lines as 'echo' would (each terminated by '\\n'), bytes preserved."""
    os.makedirs(os.path.dirname(os.path.abspath(f_path)), exist_ok=True)
    f_text = "".join(f"{f_line}\n" for f_line in f_lines)
    with open(f_path, "wb") as f_f:
        f_f.write(f_text.encode("utf-8", errors="surrogateescape"))


def aggReportFileName(f_stripe_count: Union[int, str], f_block_size: str) -> str:
    """Return the bmtool per-node aggregate file name: agg-<rf>-<bs>-report.csv."""
    return f"agg-{f_stripe_count}-{f_block_size}-report.csv"


def bmtoolReportRows(f_rel_path: str, f_agg_lines: Sequence[str]) -> List[str]:
    """Turn one agg file into lsm-report.csv rows (generate_report pipeline).

    Reproduces: egrep -H '^write|^read' | tail -2 | sed 's/:/  /' |
    sed 's|<base>/||' | sed 's|agg-||' | sed 's|-report.csv||' |
    perl 's/^(\\d+)\\/(\\d+)-(\\d+[MK])/$1  $2  $3/' | perl 's/ +/,/g'.

    Args:
        f_rel_path: Agg file path relative to the outputs root ('8/agg-4-1M-report.csv').
        f_agg_lines: Lines of the agg file.

    Returns:
        Report rows such as '8,4,1M,write,4169.77,1435.94,3556.32,20479.7,327680,10'.
    """
    f_matched = [
        f_line
        for f_line in f_agg_lines
        if f_line.startswith("write") or f_line.startswith("read")
    ][-2:]
    f_rows: List[str] = []
    for f_line in f_matched:
        f_row = f"{f_rel_path}  {f_line}"
        f_row = f_row.replace("agg-", "", 1)
        f_row = re.sub(r"-report.csv", "", f_row, count=1)
        f_row = re.sub(r"^(\d+)/(\d+)-(\d+[MK])", r"\1  \2  \3", f_row)
        f_row = re.sub(r" +", ",", f_row)
        f_rows.append(f_row)
    return f_rows


class LsmioBmtoolAggregate(DebuggableObject):
    """Cross-rank aggregate of one (nodes, stripe count, block size) combination.

    Feed every rank log in shell-glob order with addFile()/addLines(); aggLines()
    then returns the three lines bmtool writes to agg-<rf>-<bs>-report.csv.
    """

    ACCESSES: Final[Tuple[str, ...]] = ("write", "read")

    m_header: Optional[str]
    m_file_count: int
    m_line_counts: Dict[str, int]
    m_sums: Dict[str, List[float]]
    m_iter_text: Dict[str, str]
    m_iter_value: Dict[str, float]

    def __init__(self) -> None:
        super().__init__()
        self.m_header = None
        self.m_file_count = 0
        self.m_line_counts = {f_acc: 0 for f_acc in self.ACCESSES}
        self.m_sums = {f_acc: [0.0] * 5 for f_acc in self.ACCESSES}
        self.m_iter_text = {f_acc: "0" for f_acc in self.ACCESSES}
        self.m_iter_value = {f_acc: 0.0 for f_acc in self.ACCESSES}

    @property
    def file_count(self) -> int:
        return self.m_file_count

    @property
    def fileCount(self) -> int:
        return self.m_file_count

    def lineCount(self, f_access: str) -> int:
        """Number of rank summary lines aggregated for f_access ('write' or 'read')."""
        return self.m_line_counts[f_access]

    def sums(self, f_access: str) -> List[float]:
        """Summed columns 2-6 (max, min, mean MiB/s, total MiB, total ops) for f_access."""
        return list(self.m_sums[f_access])

    def iteration(self, f_access: str) -> str:
        """Max iteration column (column 7) text for f_access."""
        return self.m_iter_text[f_access]

    def addLines(self, f_lines: Sequence[str]) -> None:
        """Aggregate the lines of one rank log."""
        if self.m_file_count == 0:
            # bmtool takes the header from the first file in glob order only
            self.m_header = next(
                (f_line for f_line in f_lines if f_line.startswith("access,")), ""
            )
        self.m_file_count += 1
        for f_line in f_lines:
            for f_access in self.ACCESSES:
                if f_line.startswith(f_access + ","):
                    self._accumulate(f_access, f_line)

    def addFile(self, f_path: str) -> bool:
        """Aggregate one rank log file; an unreadable file is skipped with a warning."""
        try:
            f_lines = readBmtoolLines(f_path)
        except OSError as f_err:
            Console.warning(f"Skipping unreadable rank log '{f_path}': {f_err}")
            self.addLines([])
            return False
        self.addLines(f_lines)
        return True

    def _accumulate(self, f_access: str, f_line: str) -> None:
        f_fields = f_line.split(",")
        f_fields.extend([""] * (7 - len(f_fields)))

        self.m_line_counts[f_access] += 1
        f_sums = self.m_sums[f_access]
        for f_idx in range(5):
            f_sums[f_idx] += awkToNumber(f_fields[f_idx + 1])

        # awk: if ($7 > 0+it) it = $7  (numeric compare for numeric strings, else string)
        f_iter = f_fields[6]
        if awkIsStrNum(f_iter):
            f_greater = awkToNumber(f_iter) > self.m_iter_value[f_access]
        else:
            f_greater = f_iter > formatAwkNumber(self.m_iter_value[f_access])
        if f_greater:
            self.m_iter_text[f_access] = f_iter
            self.m_iter_value[f_access] = awkToNumber(f_iter)

    def row(self, f_access: str) -> str:
        """Return the aggregated '<access>,sumMX,sumMN,sumME,sumMB,sumIO,it' line."""
        if self.m_line_counts[f_access] == 0:
            # awk prints never-assigned sums as empty strings
            f_vals = [""] * 5
        else:
            f_vals = [formatAwkNumber(f_v) for f_v in self.m_sums[f_access]]
        return ",".join([f_access] + f_vals + [self.m_iter_text[f_access]])

    def aggLines(self) -> List[str]:
        """Return [header, write row, read row] as bmtool writes them to the agg file."""
        return [self.m_header or "", self.row("write"), self.row("read")]

    agg_lines = aggLines
    add_file = addFile
    add_lines = addLines
    line_count = lineCount


def writeBmtoolMasterReport(f_out_dir: str) -> Optional[str]:
    """Regenerate <f_out_dir>/lsm-report.csv from its */agg-*-report.csv files.

    A report with no rows is never written (an empty lsm-report.csv would later be
    mistaken for a parsed result); a warning is logged instead.

    Returns:
        Path of the written report, or None when there were no rows.
    """
    f_rows: List[str] = []
    for f_agg_path in bmtoolGlob(f_out_dir, os.path.join("*", "agg-*-report.csv")):
        if not os.path.isfile(f_agg_path):
            continue
        try:
            f_lines = readBmtoolLines(f_agg_path)
        except OSError as f_err:
            Console.warning(f"Skipping unreadable aggregate '{f_agg_path}': {f_err}")
            continue
        f_rel = os.path.relpath(f_agg_path, f_out_dir).replace(os.sep, "/")
        f_rows.extend(bmtoolReportRows(f_rel, f_lines))

    f_report = os.path.join(f_out_dir, LSM_REPORT_FILE)
    if not f_rows:
        Console.warning(
            f"No aggregate rows found under '{f_out_dir}'; not writing {LSM_REPORT_FILE}"
        )
        return None
    writeBmtoolLines(f_report, f_rows)
    return f_report


def isUsableReport(f_path: str) -> bool:
    """True when f_path is a non-empty regular file (a zero-byte report counts as missing)."""
    try:
        return os.path.isfile(f_path) and os.path.getsize(f_path) > 0
    except OSError:
        return False


# ---------------------------------------------------------------------------
# bmtool parity: tools/bmtool/parse/ior-parse.sh and lmp-parse.sh replicas
#
# ior-parse.sh copies the last two '^write|^read' lines (IOR's summary rows) of every
# file <outputs>/*/*/* verbatim into ior-report.csv, prefixed with the node count,
# stripe count and block size taken from the path and with runs of spaces turned
# into commas. lmp-parse.sh writes, for each n/rf/bs, 'n,rf,bs,' followed by the
# third ':'-separated field of the last 'grep -Hn ^.write,' hit ('path:line:text'),
# i.e. the matched log line up to its first colon.
# ---------------------------------------------------------------------------

IOR_REPORT_FILE: Final[str] = "ior-report.csv"
LMP_REPORT_FILE: Final[str] = "lmp-report.csv"
# Node counts lmp-parse.sh generate_report() visits (fixed, whatever the scale)
BMTOOL_LMP_NODES: Final[Tuple[str, ...]] = (
    "1",
    "2",
    "4",
    "8",
    "16",
    "24",
    "32",
    "40",
    "48",
)

# The sed steps of ior-parse.sh after the path prefix is removed, in order
_IOR_SED_STEPS: Final[Tuple[Any, ...]] = (
    re.compile(r"/20..-..-.."),
    re.compile(r"-20..-..-..-node...-0.txt.2"),
    re.compile(r"-20..-..-..-node...-0.txt"),
    re.compile(r"-20..-..-..-nid.....-0.txt.2"),
    re.compile(r"-20..-..-..-nid.....-0.txt"),
)
_IOR_PERL_STEPS: Final[Tuple[Any, ...]] = (
    re.compile(r"^(.|..)/out-[a-z0-9]+-([0-9]+)-([0-9]+[MK])"),
    re.compile(r"^(.|..)/out-[a-z0-9]+-c-([0-9]+)-([0-9]+[MK])"),
)
_FIRST_NUMBER_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def bmtoolIorReportRows(
    f_base_dir: str, f_path: str, f_lines: Sequence[str]
) -> List[str]:
    """Turn one IOR output file into ior-report.csv rows (ior-parse.sh pipeline).

    Reproduces: egrep -H '^write|^read' <file> | tail -2 | sed 's/:/  /' |
    sed 's|<base>/||' | the date/host seds | the two 'out-' perl rewrites |
    perl 's/ +/,/g'.

    Args:
        f_base_dir: The outputs directory as it prefixes f_path ($IOR_DIR_OBASE).
        f_path: Path of the output file as the glob produced it.
        f_lines: Lines of the file.

    Returns:
        Rows such as '1,16,1M,write,985.34,829.51,...,MPIIO,0'.
    """
    f_matched = [
        f_line
        for f_line in f_lines
        if f_line.startswith("write") or f_line.startswith("read")
    ][-2:]
    f_prefix = f_base_dir.rstrip("/") + "/"
    f_rows: List[str] = []
    for f_line in f_matched:
        f_row = f"{f_path}:{f_line}".replace(":", "  ", 1)
        f_row = f_row.replace(f_prefix, "", 1)
        for f_sed in _IOR_SED_STEPS:
            f_row = f_sed.sub("", f_row, count=1)
        for f_perl in _IOR_PERL_STEPS:
            f_row = f_perl.sub(r"\1  \2  \3", f_row, count=1)
        f_rows.append(re.sub(r" +", ",", f_row))
    return f_rows


def bmtoolIorRow(
    f_nodes: Union[int, str],
    f_stripe_count: Union[int, str],
    f_block_size: str,
    f_line: str,
) -> str:
    """ior-report.csv row for one IOR summary line of a known node/stripe/block point."""
    return f"{f_nodes},{f_stripe_count},{f_block_size}," + re.sub(r" +", ",", f_line)


def iorSummaryLines(f_lines: Sequence[str]) -> List[str]:
    """The lines ior-parse.sh reports from one IOR output: the last two '^write|^read'."""
    return [
        f_line
        for f_line in f_lines
        if f_line.startswith("write") or f_line.startswith("read")
    ][-2:]


def generateBmtoolIorReport(
    f_out_dir: str, f_report_dir: Optional[str] = None
) -> Optional[str]:
    """Write ior-report.csv for a bmtool-layout IOR outputs dir, like ior-parse.sh.

    Every regular, non-empty file <f_out_dir>/*/*/* (shell glob order) contributes
    its last two write/read lines. A report without rows is not written.

    Returns:
        Path of the written report, or None when there were no rows.
    """
    f_rows: List[str] = []
    for f_path in bmtoolGlob(f_out_dir, os.path.join("*", "*", "*")):
        try:
            if not os.path.isfile(f_path) or os.path.getsize(f_path) == 0:
                continue
            f_lines = readBmtoolLines(f_path)
        except OSError as f_err:
            Console.warning(f"Skipping unreadable IOR output '{f_path}': {f_err}")
            continue
        f_rows.extend(bmtoolIorReportRows(f_out_dir, f_path, f_lines))

    f_report = os.path.join(f_report_dir or f_out_dir, IOR_REPORT_FILE)
    if not f_rows:
        Console.warning(
            f"No IOR summary rows found under '{f_out_dir}'; not writing {IOR_REPORT_FILE}"
        )
        return None
    writeBmtoolLines(f_report, f_rows)
    return f_report


def isLmpResultLine(f_line: str) -> bool:
    """True for a line lmp-parse.sh's "grep '^.write,'" matches (e.g. 'iwrite,...')."""
    return len(f_line) >= 7 and f_line[1:7] == "write,"


def lmpLineThroughput(f_line: str) -> float:
    """Write throughput (MiB/s) of an LMP result line: the first number in its second
    comma field ('iwrite,512.30,...' -> 512.3); 0.0 when there is none."""
    f_fields = f_line.split(",")
    if len(f_fields) < 2:
        return 0.0
    f_match = _FIRST_NUMBER_RE.search(f_fields[1])
    return float(f_match.group(0)) if f_match else 0.0


def lmpReportField(f_grep_line: str) -> str:
    """awk -F: '{print $3}' of a 'grep -Hn' hit 'path:lineno:text'."""
    f_fields = f_grep_line.split(":")
    return f_fields[2] if len(f_fields) > 2 else ""


def lmpLastResult(f_paths: Sequence[str]) -> Optional[Tuple[str, int, str]]:
    """(path, line number, line) of the last '^.write,' hit across f_paths, in order."""
    f_last: Optional[Tuple[str, int, str]] = None
    for f_path in f_paths:
        try:
            if not os.path.isfile(f_path):
                continue
            f_lines = readBmtoolLines(f_path)
        except OSError as f_err:
            Console.warning(f"Skipping unreadable LMP output '{f_path}': {f_err}")
            continue
        for f_num, f_line in enumerate(f_lines, start=1):
            if isLmpResultLine(f_line):
                f_last = (f_path, f_num, f_line)
    return f_last


def bmtoolLmpRow(
    f_nodes: Union[int, str],
    f_stripe_count: Union[int, str],
    f_block_size: str,
    f_path: str,
    f_line_number: int,
    f_line: str,
) -> str:
    """lmp-report.csv row 'n,rf,bs,<field 3 of path:lineno:line>'."""
    f_field = lmpReportField(f"{f_path}:{f_line_number}:{f_line}")
    return f"{f_nodes},{f_stripe_count},{f_block_size},{f_field}"


def generateBmtoolLmpReport(
    f_out_dir: str, f_report_dir: Optional[str] = None
) -> Optional[str]:
    """Write lmp-report.csv for a bmtool-layout LMP outputs dir, like lmp-parse.sh.

    For each n in BMTOOL_LMP_NODES, rf in 4 16 and bs in 64K 1M 8M, the last
    '^.write,' line of <f_out_dir>/n/*/out-*-rf-bs-*.txt gives one row. A report
    without rows is not written.

    Returns:
        Path of the written report, or None when there were no rows.
    """
    f_rows: List[str] = []
    for f_n in BMTOOL_LMP_NODES:
        for f_rf in BMTOOL_STRIPE_COUNTS:
            for f_bs in BMTOOL_BLOCK_SIZES:
                f_last = lmpLastResult(
                    bmtoolGlob(
                        f_out_dir,
                        os.path.join(f_n, "*", f"out-*-{f_rf}-{f_bs}-*.txt"),
                    )
                )
                if f_last is not None:
                    f_rows.append(bmtoolLmpRow(f_n, f_rf, f_bs, *f_last))

    f_report = os.path.join(f_report_dir or f_out_dir, LMP_REPORT_FILE)
    if not f_rows:
        Console.warning(
            f"No LMP result lines found under '{f_out_dir}'; not writing {LMP_REPORT_FILE}"
        )
        return None
    writeBmtoolLines(f_report, f_rows)
    return f_report
