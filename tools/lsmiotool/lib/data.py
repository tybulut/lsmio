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
from typing import Dict, List, Union, Tuple, Any
from lsmiotool.lib.compat import TypedDict

from lsmiotool.lib.debuggable import DebuggableObject
from lsmiotool.lib.log import Console


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

    def __init__(self, file_name: str) -> None:
        """
        Initialize IOR single run data processor.

        Args:
            file_name: Path to IOR output file
        """
        super().__init__()
        self.file_name: str = file_name
        self.run_data: RunData = {
            "read": {},
            "write": {}
        }
        # Summary of all tests:
        # Operation   Max(MiB)   Min(MiB)  Mean(MiB)     StdDev   Max(OPs)   Min(OPs)  Mean(OPs)     StdDev    Mean(s) Stonewall(s) Stonewall(MiB) Test# #Tasks tPN reps fPP reord reordoff reordrand seed segcnt   blksiz    xsize aggs(MiB)   API RefNum
        # write        4214.58    2752.91    3571.98     466.80    4214.58    2752.91    3571.98     466.80    0.14599         NA            NA     0      4   1   10   0     0        1         0    0    128  1048576  1048576     512.0 POSIX      0
        # read        14959.41   10729.26   13695.54    1195.05   14959.41   10729.26   13695.54    1195.05    0.03771         NA            NA     0      4   1   10   0     0        1         0    0    128  1048576  1048576     512.0 POSIX      0
        with open(file_name, newline='') as infile:
            head_line = ''
            read_line = ''
            write_line = ''
            found_summary = False
            for line in infile:
                if not found_summary:
                    if line.startswith('Summary of all tests'):
                        found_summary = True
                    continue
                if line.startswith('Operation   Max(MiB)'):
                    head_line = line
                    continue
                if line.startswith('write'):
                    write_line = line
                    continue
                if line.startswith('read'):
                    read_line = line
                    continue
                if head_line and read_line and write_line:
                    break
            heads = head_line.rstrip().split()[1:]
            reads = read_line.rstrip().split()[1:]
            writes = write_line.rstrip().split()[1:]
            for i in range(len(heads)):
                if heads[i] in [
                    "Max(MiB)", "Min(MiB)", "Mean(MiB)", "StdDev",
                    "Max(OPs)", "Min(OPs)", "Mean(OPs)"
                ]:
                    self.run_data["read"][heads[i]] = float(reads[i])
                    self.run_data["write"][heads[i]] = float(writes[i])
                else:
                    self.run_data["read"][heads[i]] = reads[i]
                    self.run_data["write"][heads[i]] = writes[i]

    def get_map(self) -> RunData:
        """
        Get the run data map.

        Returns:
            Dictionary containing read/write metrics
        """
        return self.run_data


class LsmioSingleRunData(DebuggableObject):
    """Process single LSMIO run data."""

    def __init__(self, file_name: str) -> None:
        """
        Initialize LSMIO single run data processor.

        Args:
            file_name: Path to LSMIO output file
        """
        super().__init__()
        self.file_name: str = file_name
        self.run_data: RunData = {
            "read": {},
            "write": {}
        }
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
        with open(file_name, newline='') as infile:
            head_line = ''
            read_line = ''
            write_line = ''
            found_w_summary = False
            found_r_summary = False
            for line in infile:
                if not found_w_summary and not write_line:
                    if line.startswith('Bench-WRITE:'):
                        found_w_summary = True
                        continue
                if found_w_summary:
                    if line.startswith('access,'):
                        head_line = line
                    if line.startswith('write'):
                        found_w_summary = False
                        write_line = line
                    continue
                if not found_r_summary and not read_line:
                    if line.startswith('Bench-READ:'):
                        found_r_summary = True
                        continue
                if found_r_summary:
                    if line.startswith('read'):
                        read_line = line
                    continue
                if head_line and read_line and write_line:
                    break
            heads = head_line.rstrip().split(",")[1:]
            reads = read_line.rstrip().split(",")[1:]
            writes = write_line.rstrip().split(",")[1:]
            for i in range(len(heads)):
                if heads[i] in [
                    "bw(MiB/s)", "Latency(ms)", "block(KiB)", "xfer(KiB)"
                ]:
                    self.run_data["read"][heads[i]] = float(reads[i])
                    self.run_data["write"][heads[i]] = float(writes[i])
                else:
                    self.run_data["read"][heads[i]] = reads[i]
                    self.run_data["write"][heads[i]] = writes[i]

    def get_map(self) -> RunData:
        """
        Get the run data map.

        Returns:
            Dictionary containing read/write metrics
        """
        return self.run_data


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

    def __init__(self, file_name: str) -> None:
        """
        Initialize IOR summary data processor.

        Args:
            file_name: Path to IOR summary CSV file
        """
        super().__init__()
        self.file_name: str = file_name
        self.csv_data: Dict[str, Dict[int, Dict[str, Dict[int, PartData]]]] = {}
        # N,Stripes,BlockSize,Operation,Max(MiB),Min(MiB),Mean(MiB),StdDev,...
        # 1,16,8M,read,5353.38,5160.61,5293.08,49.88,66...
        with open(file_name, newline='') as csvfile:
            csv_reader = csv.reader(csvfile, delimiter=',', quotechar='|')
            for row in csv_reader:
                access = row[3]
                if access not in self.csv_data:
                    self.csv_data[access] = {}
                num_stripes = int(row[1])
                if num_stripes not in self.csv_data[access]:
                    self.csv_data[access][num_stripes] = {}
                stripe_size = row[2]
                if stripe_size not in self.csv_data[access][num_stripes]:
                    self.csv_data[access][num_stripes][stripe_size] = {}
                num_nodes = int(row[0])
                if num_nodes not in self.csv_data[access][num_stripes][stripe_size]:
                    self.csv_data[access][num_stripes][stripe_size][num_nodes] = {}
                part_data: PartData = {
                    'maxMB': float(0.00),
                    'minMB': float(0.00),
                    'meanMB': float(0.00),
                }
                if row[4]:
                    part_data['maxMB'] = float(row[4])
                if row[5]:
                    part_data['minMB'] = float(row[5])
                if row[6]:
                    part_data['meanMB'] = float(row[6])
                self.csv_data[access][num_stripes][stripe_size][num_nodes] = part_data

    def time_series(
        self,
        is_read: bool,
        num_stripes: int,
        stripe_size: str
    ) -> Tuple[List[int], List[float]]:
        """
        Get time series data for the specified parameters.

        Args:
            is_read: Whether to get read or write data
            num_stripes: Number of stripes
            stripe_size: Size of stripes

        Returns:
            Tuple of node counts and corresponding performance values
        """
        access = "read" if is_read else "write"
        x_series: List[int] = []
        y_series: List[float] = []
        if access in self.csv_data:
            if num_stripes in self.csv_data[access]:
                if stripe_size in self.csv_data[access][num_stripes]:
                    for num_nodes in sorted(
                        self.csv_data[access][num_stripes][stripe_size].keys()
                    ):
                        x_series.append(num_nodes)
                        y_series.append(
                            self.csv_data[access][num_stripes][stripe_size][num_nodes]['maxMB']
                        )
        return x_series, y_series


class LsmioSummaryData(IorSummaryData):
    """Process LSMIO summary data."""

    def __init__(self, file_name: str) -> None:
        """
        Initialize LSMIO summary data processor.

        Args:
            file_name: Path to LSMIO summary CSV file
        """
        super().__init__(file_name)
