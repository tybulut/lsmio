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
import math
from typing import Dict, List, Union, Tuple, Any, Optional
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
                heads = head_line.rstrip().split()[1:] if head_line else []
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
    m_run_data: Dict[str, Any]
    m_iter_data: Dict[str, List[float]]

    def __init__(self, f_file_name: str) -> None:
        """Initialize LMP single run data processor.

        Extracts lines starting with `write,` or `^.write,` and extracts
        the 3rd field (or throughput metric).

        Args:
            f_file_name: Path to LMP output file
        """
        super().__init__()
        self.m_file_name = f_file_name
        self.m_run_data = {
            "write": {"throughput": 0.0, "bw(MiB/s)": 0.0},
            "read": {"throughput": 0.0, "bw(MiB/s)": 0.0},
        }
        self.m_iter_data = {"write": [], "read": []}
        try:
            with open(f_file_name, newline="") as infile:
                for line in infile:
                    line_s = line.strip()
                    # Match write lines: .write, or write, or write:
                    if (
                        line_s.startswith(".write,")
                        or line_s.startswith("write,")
                        or line_s.startswith("write:")
                    ):
                        # Split by comma or colon
                        if ":" in line_s:
                            parts = [p.strip() for p in line_s.split(":")]
                        else:
                            parts = [p.strip() for p in line_s.split(",")]
                        if len(parts) >= 3:
                            val = parseFloat(parts[2], 0.0)
                            self.m_run_data["write"]["throughput"] = val
                            self.m_run_data["write"]["bw(MiB/s)"] = val
                            self.m_iter_data["write"].append(val)
                        elif len(parts) >= 2:
                            val = parseFloat(parts[1], 0.0)
                            self.m_run_data["write"]["throughput"] = val
                            self.m_run_data["write"]["bw(MiB/s)"] = val
                            self.m_iter_data["write"].append(val)
        except (IOError, OSError) as err:
            Console.debug(f"LmpSingleRunData: error opening {f_file_name}: {err}")

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

        Supports both standard summary CSVs and LMP CSV format:
        `$n,$rf,$bs,$throughput` or `$n,$rf,$bs,write,$throughput,...`

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

                    # Determine access type and value column
                    if row[3].strip().lower() in ["write", "read"]:
                        access = row[3].strip().lower()
                        val = parseFloat(row[4]) if len(row) > 4 else 0.0
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
