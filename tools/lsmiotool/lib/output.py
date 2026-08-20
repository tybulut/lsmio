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
from typing import Dict, List, Union, Tuple, Optional, Any
from lsmiotool.lib.compat import TypedDict, Final

from lsmiotool.lib.debuggable import DebuggableObject
from lsmiotool.lib.log import Console
from lsmiotool.lib import data


class MissingDataError(Exception):
    """Exception raised when actual file counts mismatch expected counts."""
    pass


class FileMetadata(TypedDict):
    """Type definition for file metadata."""
    size: int  # File size in bytes
    path: str  # Absolute path to file


class DirMap(TypedDict):
    """Type definition for directory structure mapping."""
    size: Union[int, Dict[str, 'DirMap']]  # Size in bytes or nested directory


class MetricData(TypedDict):
    """Type definition for I/O performance metrics."""
    max_mib_per_s: float  # Maximum throughput in MiB/s
    min_mib_per_s: float  # Minimum throughput in MiB/s
    mean_mib_per_s: float  # Mean throughput in MiB/s
    total_mib: float  # Total data transferred in MiB
    total_ops: float  # Total I/O operations
    iteration: int  # Iteration count


class AccessData(TypedDict):
    """Type definition for read/write access metrics."""
    read: MetricData  # Read performance metrics
    write: MetricData  # Write performance metrics


class AggData(TypedDict):
    """Type definition for aggregated performance data."""
    size: Union[
        Dict[str, Dict[str, Dict[str, AccessData]]],  # Nested performance data
        None  # No data available
    ]


class TraverseDir(DebuggableObject):
    """Base class for directory traversal and mapping."""

    m_root_dir: str
    m_dir_recursive: DirMap

    def __init__(self, f_target_dir: str) -> None:
        """Initialize directory traversal.

        Args:
            f_target_dir: Root directory to traverse
        """
        super().__init__()
        self.m_root_dir = f_target_dir
        self.m_dir_recursive = self._gather(f_target_dir)

    @property
    def root_dir(self) -> str:
        return self.m_root_dir

    @property
    def dir_recursive(self) -> DirMap:
        return self.m_dir_recursive

    def _gather(self, f_gather_dir: str) -> DirMap:
        """Recursively gather directory structure.

        Args:
            f_gather_dir: Directory to gather information from

        Returns:
            Dictionary mapping of directory structure
        """
        folder_dict: DirMap = {}
        for root, dirs, files in os.walk(f_gather_dir):
            # Process files in current directory
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    folder_dict[str(file)] = os.path.getsize(file_path)
                except OSError:
                    folder_dict[str(file)] = 0

            # Process subdirectories
            for dir_name in dirs:
                folder_dict[str(dir_name)] = self._gather(
                    os.path.join(root, dir_name)
                )
            break
        return folder_dict

    def getMap(self) -> DirMap:
        """Get the directory structure map.

        Returns:
            Complete directory structure mapping
        """
        return self.m_dir_recursive

    get_map = getMap


class IorOutputDir(TraverseDir):
    """Directory traversal specialized for IOR output files."""

    def getMap(self) -> Dict[str, Dict[str, Dict[str, Dict[str, FileMetadata]]]]:
        """Get IOR output file mapping.

        Returns:
            Dictionary mapping of IOR output files organized by size, stripe count,
            and stripe size.
        """
        meta_dict: Dict[str, Dict[str, Dict[str, Dict[str, FileMetadata]]]] = {}

        # Process each field size directory
        for field_size in self.m_dir_recursive:
            value_size = self.m_dir_recursive[field_size]
            if not isinstance(value_size, dict):
                Console.debug(f"Unexpected field_size: {field_size}")
                Console.debug(f"Unexpected value_size: {value_size}")
                continue

            # Initialize field size entry
            if field_size not in meta_dict:
                meta_dict[field_size] = {}

            # Process date directories
            for date_dir in value_size:
                value_date = value_size[date_dir]
                if not isinstance(value_date, dict):
                    continue  # Skip date entries (e.g. '2023-07-21')

                # Process output files
                for key in value_date:
                    val = value_date[key]
                    if isinstance(val, dict):
                        continue  # Skip nested directories

                    # Parse output file name
                    pattern = (
                        r"out-[a-zA-Z\d-]*-(\d+)-(\d+[KMGTB])-"
                        r"\d+-\d+-\d+-[a-zA-Z\d]+-\d+\.\w+\.\d+"
                    )
                    match = re.match(pattern, key)
                    if not match:
                        # Also support format without trailing suffix: out-*-rf-bs-*.txt*
                        pattern_alt = r"out-[a-zA-Z\d-]*-(\d+)-(\d+[KMGTB])-.*"
                        match = re.match(pattern_alt, key)
                    if not match:
                        Console.debug(f"Unexpected file pattern: {key}")
                        continue

                    # Extract stripe information
                    stripe_count = str(match.group(1))
                    stripe_size = str(match.group(2))

                    # Initialize stripe entries
                    if stripe_count not in meta_dict[field_size]:
                        meta_dict[field_size][stripe_count] = {}
                    if stripe_size not in meta_dict[field_size][stripe_count]:
                        meta_dict[field_size][stripe_count][stripe_size] = {}

                    # Add file metadata
                    key_dir_list = [field_size, date_dir, key]
                    meta_dict[field_size][stripe_count][stripe_size][key] = {
                        "size": val,
                        "path": os.path.join(self.m_root_dir, *key_dir_list)
                    }

        return meta_dict

    get_map = getMap


class LsmioOutputDir(IorOutputDir):
    """Directory traversal specialized for LSMIO output files."""
    pass


class LmpOutputDir(IorOutputDir):
    """Directory traversal specialized for LMP output files."""

    def getMap(self) -> Dict[str, Dict[str, Dict[str, Dict[str, FileMetadata]]]]:
        """Get LMP output file mapping.

        Returns:
            Dictionary mapping of LMP output files organized by node count, stripe count,
            and stripe size.
        """
        meta_dict: Dict[str, Dict[str, Dict[str, Dict[str, FileMetadata]]]] = {}

        for field_size in self.m_dir_recursive:
            value_size = self.m_dir_recursive[field_size]
            if not isinstance(value_size, dict):
                continue

            if field_size not in meta_dict:
                meta_dict[field_size] = {}

            for date_dir in value_size:
                value_date = value_size[date_dir]
                if not isinstance(value_date, dict):
                    continue

                for key in value_date:
                    val = value_date[key]
                    if isinstance(val, dict):
                        continue

                    pattern = r"out-[a-zA-Z\d-]*-(\d+)-(\d+[KMGTB])-.*"
                    match = re.match(pattern, key)
                    if not match:
                        continue

                    stripe_count = str(match.group(1))
                    stripe_size = str(match.group(2))

                    if stripe_count not in meta_dict[field_size]:
                        meta_dict[field_size][stripe_count] = {}
                    if stripe_size not in meta_dict[field_size][stripe_count]:
                        meta_dict[field_size][stripe_count][stripe_size] = {}

                    key_dir_list = [field_size, date_dir, key]
                    meta_dict[field_size][stripe_count][stripe_size][key] = {
                        "size": val,
                        "path": os.path.join(self.m_root_dir, *key_dir_list)
                    }

        return meta_dict

    get_map = getMap


class IorAggOutput(DebuggableObject):
    """Aggregate IOR output data processor."""

    # Configuration constants
    _operations: List[str] = ['read', 'write']
    _stripe_counts: List[str] = ['4', '16']
    _stripe_sizes: List[str] = ['64K', '1M', '8M']
    _node_counts: List[str] = [
        '1', '2', '4', '8', '16', '24', '32', '40', '48'
    ]

    m_out_dir: str
    m_agg_data: AggData

    def __init__(self, f_output_dir: str) -> None:
        """Initialize IOR output data processor.

        Args:
            f_output_dir: Directory containing IOR output files
        """
        super().__init__()
        self.m_out_dir = f_output_dir
        ior_dir = IorOutputDir(self.m_out_dir)
        dir_map = ior_dir.getMap()
        self.m_agg_data = {}

        # Process data for each node count
        for n_count in self._node_counts:
            self.m_agg_data[n_count] = {}

            # Process data for each stripe configuration
            for s_count in self._stripe_counts:
                self.m_agg_data[n_count][s_count] = {}

                # Process data for each stripe size
                for s_size in self._stripe_sizes:
                    self.m_agg_data[n_count][s_count][s_size] = []

                    # Validate directory structure
                    if n_count not in dir_map:
                        self._log_error({
                            n_count: 'node count not found in output directory'
                        })
                        continue
                    if s_count not in dir_map[n_count]:
                        self._log_error({
                            s_count: 'stripe count not found in output directory'
                        })
                        continue
                    if s_size not in dir_map[n_count][s_count]:
                        self._log_error({
                            s_count: 'stripe size not found in output directory'
                        })
                        continue
                    if len(dir_map[n_count][s_count][s_size]) != int(n_count):
                        self._log_error({
                            0: 'number of files does not match node count'
                        })

                    # Process aggregated files
                    self.m_agg_data[n_count][s_count][s_size] = \
                        self._processAggFiles(
                            dir_map[n_count][s_count][s_size],
                            n_count
                        )

    @property
    def out_dir(self) -> str:
        return self.m_out_dir

    @property
    def agg_data(self) -> AggData:
        return self.m_agg_data

    def _processAggFiles(
        self,
        f_files: Dict[str, FileMetadata],
        f_count: str
    ) -> AccessData:
        """Process aggregated IOR output files.

        Args:
            f_files: Dictionary of output files to process
            f_count: Expected number of files

        Returns:
            Aggregated access data from all files
        """
        sim_data: List[AccessData] = []

        # Process each output file
        for file in f_files:
            file_meta = f_files[file]
            if file_meta["size"] == 0:
                continue

            # Parse file data
            sr_data = data.IorSingleRunData(file_meta["path"])
            sr_map = sr_data.getMap()
            sim_data.append(sr_map)

        # Validate data
        if len(sim_data) != 1 and len(sim_data) != int(f_count):
            self._log_error({
                0: 'number of simulation data does not match node count'
            })

        return sim_data[0] if sim_data else {}

    _process_agg_files = _processAggFiles

    def getMap(self) -> AggData:
        """Get the aggregated data map.

        Returns:
            Complete mapping of aggregated performance data
        """
        return self.m_agg_data

    get_map = getMap

    def exportCsv(self, f_agg_data: Any, f_out_file: str) -> None:
        """Export aggregated data to a CSV file.

        Args:
            f_agg_data: Data to write to CSV (list of rows or string lines).
            f_out_file: Target CSV file path.
        """
        os.makedirs(os.path.dirname(os.path.abspath(f_out_file)), exist_ok=True)
        with open(f_out_file, 'w', newline='') as f:
            if isinstance(f_agg_data, list):
                writer = csv.writer(f)
                for row in f_agg_data:
                    if isinstance(row, (list, tuple)):
                        writer.writerow(row)
                    elif isinstance(row, str):
                        f.write(row.rstrip() + "\n")
            elif isinstance(f_agg_data, str):
                f.write(f_agg_data)

    def generateReports(self, f_out_dir: Optional[str] = None) -> None:
        """Generate IOR master CSV report.

        Args:
            f_out_dir: Destination directory for report (defaults to m_out_dir).
        """
        target_dir = f_out_dir or self.m_out_dir
        report_file = os.path.join(target_dir, "ior-report.csv")
        ior_dir = IorOutputDir(target_dir)
        dir_map = ior_dir.getMap()
        rows: List[str] = []

        for n_count in sorted(dir_map.keys(), key=lambda x: int(x) if x.isdigit() else 0):
            for s_count in ['16', '4']:
                if s_count not in dir_map[n_count]:
                    continue
                for s_size in ['1M', '64K', '8M']:
                    if s_size not in dir_map[n_count][s_count]:
                        continue
                    files_dict = dir_map[n_count][s_count][s_size]
                    for key in sorted(files_dict.keys()):
                        f_path = files_dict[key]["path"]
                        if not os.path.exists(f_path) or os.path.getsize(f_path) == 0:
                            continue
                        sr = data.IorSingleRunData(f_path)
                        r_map = sr.getMap()
                        node_str = f"{int(n_count):02d}" if n_count.isdigit() else n_count
                        for op in ['write', 'read']:
                            if op in r_map and r_map[op]:
                                vals = [str(r_map[op].get(k, '')) for k in [
                                    "Max(MiB)", "Min(MiB)", "Mean(MiB)", "StdDev",
                                    "Max(OPs)", "Min(OPs)", "Mean(OPs)", "StdDev",
                                    "Mean(s)", "Stonewall(s)", "Stonewall(MiB)",
                                    "Test#", "#Tasks", "tPN", "reps", "fPP",
                                    "reord", "reordoff", "reordrand", "seed",
                                    "segcnt", "blksiz", "xsize", "aggs(MiB)",
                                    "API", "RefNum"
                                ]]
                                row_str = f"{node_str},{s_count},{s_size},{op}," + ",".join(vals)
                                rows.append(row_str)

        self.exportCsv(rows, report_file)
        Console.debug(f"Generated IOR master report: {report_file}")


class LsmioAggOutput(IorAggOutput):
    """Aggregate LSMIO output data processor."""

    def _processAggFiles(
        self,
        f_files: Dict[str, FileMetadata],
        f_count: str
    ) -> AccessData:
        """Process aggregated LSMIO output files using math.fsum for numerical stability.

        Args:
            f_files: Dictionary of output files to process
            f_count: Expected number of files

        Returns:
            Aggregated access data from all files
        """
        sim_data: List[AccessData] = []

        # Process each output file
        for file in sorted(f_files.keys()):
            file_meta = f_files[file]
            sr_data = data.LsmioSingleRunData(file_meta["path"])
            sr_map = sr_data.getMap()
            sim_data.append(sr_map)

        # Validate data
        if len(sim_data) != int(f_count):
            self._log_error({
                0: 'number of simulation data does not match node count'
            })
            raise MissingDataError(
                f"Number of simulation data files ({len(sim_data)}) does not match expected node count ({f_count})"
            )

        # Initialize aggregated metrics
        agg_map: AccessData = {
            'read': {
                'max(MiB)/s': float(0.00),
                'min(MiB/s)': float(0.00),
                'mean(MiB/s)': float(0.00),
                'total(MiB)': float(0),
                'total(Ops)': float(0),
                'iteration': int(0)
            },
            'write': {
                'max(MiB)/s': float(0.00),
                'min(MiB/s)': float(0.00),
                'mean(MiB/s)': float(0.00),
                'total(MiB)': float(0),
                'total(Ops)': float(0),
                'iteration': int(0)
            }
        }

        # Aggregate metrics from all files using math.fsum
        read_max_list: List[float] = []
        read_min_list: List[float] = []
        read_mean_list: List[float] = []
        read_total_list: List[float] = []
        read_ops_list: List[float] = []

        write_max_list: List[float] = []
        write_min_list: List[float] = []
        write_mean_list: List[float] = []
        write_total_list: List[float] = []
        write_ops_list: List[float] = []

        for sim in sim_data:
            if 'read' in sim and sim['read']:
                read_max_list.append(data.parseFloat(sim['read'].get('max(MiB)/s', sim['read'].get('bw(MiB/s)', 0.0))))
                read_min_list.append(data.parseFloat(sim['read'].get('min(MiB/s)', sim['read'].get('Latency(ms)', 0.0))))
                read_mean_list.append(data.parseFloat(sim['read'].get('mean(MiB/s)', 0.0)))
                read_total_list.append(data.parseFloat(sim['read'].get('total(MiB)', sim['read'].get('block(KiB)', 0.0))))
                read_ops_list.append(data.parseFloat(sim['read'].get('total(Ops)', sim['read'].get('xfer(KiB)', 0.0))))
                agg_map['read']['iteration'] = max(agg_map['read']['iteration'], data.parseInt(sim['read'].get('iteration', sim['read'].get('iter', 0))))

            if 'write' in sim and sim['write']:
                write_max_list.append(data.parseFloat(sim['write'].get('max(MiB)/s', sim['write'].get('bw(MiB/s)', 0.0))))
                write_min_list.append(data.parseFloat(sim['write'].get('min(MiB/s)', sim['write'].get('Latency(ms)', 0.0))))
                write_mean_list.append(data.parseFloat(sim['write'].get('mean(MiB/s)', 0.0)))
                write_total_list.append(data.parseFloat(sim['write'].get('total(MiB)', sim['write'].get('block(KiB)', 0.0))))
                write_ops_list.append(data.parseFloat(sim['write'].get('total(Ops)', sim['write'].get('xfer(KiB)', 0.0))))
                agg_map['write']['iteration'] = max(agg_map['write']['iteration'], data.parseInt(sim['write'].get('iteration', sim['write'].get('iter', 0))))

        agg_map['read']['max(MiB)/s'] = math.fsum(read_max_list)
        agg_map['read']['min(MiB/s)'] = math.fsum(read_min_list)
        agg_map['read']['mean(MiB/s)'] = math.fsum(read_mean_list)
        agg_map['read']['total(MiB)'] = math.fsum(read_total_list)
        agg_map['read']['total(Ops)'] = math.fsum(read_ops_list)

        agg_map['write']['max(MiB)/s'] = math.fsum(write_max_list)
        agg_map['write']['min(MiB/s)'] = math.fsum(write_min_list)
        agg_map['write']['mean(MiB/s)'] = math.fsum(write_mean_list)
        agg_map['write']['total(MiB)'] = math.fsum(write_total_list)
        agg_map['write']['total(Ops)'] = math.fsum(write_ops_list)

        return agg_map

    _process_agg_files = _processAggFiles

    def generateReports(self, f_out_dir: Optional[str] = None) -> None:
        """Generate Stage 1 aggregate reports and Stage 2 master lsm-report.csv.

        Args:
            f_out_dir: Destination directory for reports (defaults to m_out_dir).
        """
        target_dir = f_out_dir or self.m_out_dir
        lsm_dir = LsmioOutputDir(target_dir)
        dir_map = lsm_dir.getMap()

        # Stage 1: Generate agg-{stripe_count}-{stripe_size}-report.csv in each node directory
        for n_count in dir_map:
            for s_count in dir_map[n_count]:
                for s_size in dir_map[n_count][s_count]:
                    files_dict = dir_map[n_count][s_count][s_size]
                    if not files_dict:
                        continue

                    # Collect first file's summary and all iteration values
                    sorted_files = sorted(files_dict.keys())
                    first_file_meta = files_dict[sorted_files[0]]
                    first_path = first_file_meta["path"]

                    first_w_line = ""
                    first_r_line = ""
                    header_line = "access,bw(MiB/s),Latency(ms),block(KiB),xfer(KiB),iter"

                    w_iters: List[float] = []
                    r_iters: List[float] = []

                    for f_key in sorted_files:
                        f_meta = files_dict[f_key]
                        sr = data.LsmioSingleRunData(f_meta["path"])
                        it_data = sr.getIterData()
                        w_iters.extend(it_data["write"])
                        r_iters.extend(it_data["read"])

                        if not first_w_line or not first_r_line:
                            try:
                                with open(f_meta["path"], "r") as inf:
                                    for line in inf:
                                        l_s = line.strip()
                                        if l_s.startswith("write,") and not first_w_line:
                                            first_w_line = l_s
                                        elif l_s.startswith("read,") and not first_r_line:
                                            first_r_line = l_s
                            except (IOError, OSError):
                                pass

                    if not first_w_line:
                        first_w_line = "write,0.0,0.0,0,0,0"
                    if not first_r_line:
                        first_r_line = "read,0.0,0.0,0,0,0"

                    max_w = max(w_iters) if w_iters else 0.0
                    min_w = min(w_iters) if w_iters else 0.0
                    sum_w = 0.0
                    for w in w_iters:
                        sum_w += w
                    mean_w = (sum_w / len(w_iters)) if w_iters else 0.0

                    max_r = max(r_iters) if r_iters else 0.0
                    min_r = min(r_iters) if r_iters else 0.0
                    sum_r = 0.0
                    for r in r_iters:
                        sum_r += r
                    mean_r = (sum_r / len(r_iters)) if r_iters else 0.0

                    agg_out_lines = [
                        header_line,
                        f"{first_w_line},{max_w:.2f},{min_w:.2f},{mean_w:.6g}",
                        f"{first_r_line},{max_r:.2f},{min_r:.2f},{mean_r:.6g}"
                    ]

                    agg_file_path = os.path.join(
                        target_dir, str(n_count), f"agg-{s_count}-{s_size}-report.csv"
                    )
                    self.exportCsv(agg_out_lines, agg_file_path)

        # Stage 2: Master lsm-report.csv
        master_file = os.path.join(target_dir, "lsm-report.csv")
        master_rows: List[str] = []

        agg_files = sorted(
            glob.glob(os.path.join(target_dir, "*", "agg-*-report.csv")),
            key=lambda p: re.sub(r'[^a-zA-Z0-9]', '', os.path.relpath(p, target_dir))
        )
        for agg_file in agg_files:
            rel = os.path.relpath(agg_file, target_dir)
            parts = rel.split(os.sep)
            if len(parts) != 2:
                continue
            n_part = parts[0]
            file_part = parts[1]  # agg-16-1M-report.csv
            pattern = r"agg-(\d+)-(\d+[KMGTB])-report\.csv"
            m = re.match(pattern, file_part)
            if not m:
                continue
            rf = m.group(1)
            bs = m.group(2)

            try:
                with open(agg_file, "r") as inf:
                    for line in inf:
                        l_s = line.strip()
                        if l_s.startswith("write,") or l_s.startswith("read,"):
                            master_rows.append(f"{n_part},{rf},{bs},{l_s}")
            except (IOError, OSError):
                pass

        self.exportCsv(master_rows, master_file)
        Console.debug(f"Generated LSMIO master report: {master_file}")


class LmpAggOutput(IorAggOutput):
    """Aggregate LMP output data processor."""

    def __init__(self, f_output_dir: str) -> None:
        """Initialize LMP output data processor.

        Args:
            f_output_dir: Directory containing LMP output files
        """
        super(IorAggOutput, self).__init__()
        self.m_out_dir = f_output_dir
        lmp_dir = LmpOutputDir(self.m_out_dir)
        dir_map = lmp_dir.getMap()
        self.m_agg_data = {}

        for n_count in self._node_counts:
            self.m_agg_data[n_count] = {}
            for s_count in self._stripe_counts:
                self.m_agg_data[n_count][s_count] = {}
                for s_size in self._stripe_sizes:
                    self.m_agg_data[n_count][s_count][s_size] = []
                    if n_count not in dir_map or s_count not in dir_map[n_count] or s_size not in dir_map[n_count][s_count]:
                        continue
                    self.m_agg_data[n_count][s_count][s_size] = \
                        self._processAggFiles(
                            dir_map[n_count][s_count][s_size],
                            n_count
                        )

    def _processAggFiles(
        self,
        f_files: Dict[str, FileMetadata],
        f_count: str
    ) -> AccessData:
        """Process aggregated LMP output files.

        Args:
            f_files: Dictionary of output files to process
            f_count: Expected number of files

        Returns:
            Aggregated performance data
        """
        sim_data: List[Dict[str, Any]] = []

        for file in sorted(f_files.keys()):
            file_meta = f_files[file]
            sr_data = data.LmpSingleRunData(file_meta["path"])
            sim_data.append(sr_data.getMap())

        if len(sim_data) != int(f_count):
            self._log_error({
                0: 'number of simulation data does not match node count'
            })
            raise MissingDataError(
                f"Number of simulation data files ({len(sim_data)}) does not match expected node count ({f_count})"
            )

        tp_list: List[float] = [
            data.parseFloat(s['write'].get('throughput', 0.0)) for s in sim_data
        ]
        sum_tp = math.fsum(tp_list)

        agg_map: AccessData = {
            'read': {
                'max(MiB)/s': 0.0,
                'min(MiB/s)': 0.0,
                'mean(MiB/s)': 0.0,
                'total(MiB)': 0.0,
                'total(Ops)': 0.0,
                'iteration': 0
            },
            'write': {
                'max(MiB)/s': sum_tp,
                'min(MiB/s)': sum_tp,
                'mean(MiB/s)': sum_tp,
                'total(MiB)': sum_tp,
                'total(Ops)': 0.0,
                'iteration': 0
            }
        }
        return agg_map

    _process_agg_files = _processAggFiles

    def generateReports(self, f_out_dir: Optional[str] = None) -> None:
        """Generate LMP master CSV report (lmp-report.csv).

        Args:
            f_out_dir: Destination directory for report (defaults to m_out_dir).
        """
        target_dir = f_out_dir or self.m_out_dir
        report_file = os.path.join(target_dir, "lmp-report.csv")
        lmp_dir = LmpOutputDir(target_dir)
        dir_map = lmp_dir.getMap()
        rows: List[str] = []

        for n in self._node_counts:
            if n not in dir_map:
                continue
            for rf in self._stripe_counts:
                if rf not in dir_map[n]:
                    continue
                for bs in self._stripe_sizes:
                    if bs not in dir_map[n][rf]:
                        continue
                    files_dict = dir_map[n][rf][bs]
                    for key in sorted(files_dict.keys()):
                        f_path = files_dict[key]["path"]
                        sr = data.LmpSingleRunData(f_path)
                        tp = sr.getMap()["write"].get("throughput", 0.0)
                        rows.append(f"{n},{rf},{bs},{tp}")

        self.exportCsv(rows, report_file)
        Console.debug(f"Generated LMP master report: {report_file}")


class IorFullOutput(IorAggOutput):
    """Full IOR output data processor."""

    def getMap(self) -> AggData:
        """Get the complete aggregated data map.

        Returns:
            Complete mapping of aggregated performance data
        """
        return self.m_agg_data

    get_map = getMap

    def timeSeries(
        self,
        f_read: bool,
        f_stripe_count: int,
        f_stripe_size: str
    ) -> Tuple[List[str], List[float]]:
        """Get time series data for a specific stripe configuration.

        Args:
            f_read: Whether to get read or write data
            f_stripe_count: Stripe count
            f_stripe_size: Stripe size

        Returns:
            Time series data for the specified stripe configuration
        """
        sum_data = self.getMap()
        access = 'read' if f_read else 'write'
        x_series = self._node_counts
        y_series: List[float] = []
        for n_count in x_series:
            y_series.append(sum_data[n_count][str(f_stripe_count)][f_stripe_size][access]['Max(MiB)'])
        return (x_series, y_series)

    time_series = timeSeries


class LsmioFullOutput(LsmioAggOutput):
    """Full LSMIO output data processor."""

    def getMap(self) -> AggData:
        """Get the complete aggregated data map.

        Returns:
            Complete mapping of aggregated performance data
        """
        return self.m_agg_data

    get_map = getMap

    def timeSeries(
        self,
        f_read: bool,
        f_stripe_count: int,
        f_stripe_size: str
    ) -> Tuple[List[str], List[float]]:
        """Get time series data for a specific stripe configuration.

        Args:
            f_read: Whether to get read or write data
            f_stripe_count: Stripe count
            f_stripe_size: Stripe size

        Returns:
            Time series data for the specified stripe configuration
        """
        sum_data = self.getMap()
        access = 'read' if f_read else 'write'
        x_series = self._node_counts
        y_series: List[float] = []
        for n_count in x_series:
            y_series.append(sum_data[n_count][str(f_stripe_count)][f_stripe_size][access]['max(MiB)/s'])
        return (x_series, y_series)

    time_series = timeSeries


class LmpFullOutput(LmpAggOutput):
    """Full LMP output data processor."""

    def getMap(self) -> AggData:
        """Get the complete aggregated data map.

        Returns:
            Complete mapping of aggregated performance data
        """
        return self.m_agg_data

    get_map = getMap

    def timeSeries(
        self,
        f_read: bool,
        f_stripe_count: int,
        f_stripe_size: str
    ) -> Tuple[List[str], List[float]]:
        """Get time series data for a specific stripe configuration.

        Args:
            f_read: Whether to get read or write data
            f_stripe_count: Stripe count
            f_stripe_size: Stripe size

        Returns:
            Time series data for the specified stripe configuration
        """
        sum_data = self.getMap()
        access = 'read' if f_read else 'write'
        x_series = self._node_counts
        y_series: List[float] = []
        for n_count in x_series:
            y_series.append(sum_data[n_count][str(f_stripe_count)][f_stripe_size][access]['max(MiB)/s'])
        return (x_series, y_series)

    time_series = timeSeries
