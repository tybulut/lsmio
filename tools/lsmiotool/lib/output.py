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

import os
import re
from typing import Dict, List, Union, Tuple, Optional, Any
from lsmiotool.lib.compat import TypedDict

from lsmiotool.lib.debuggable import DebuggableObject
from lsmiotool.lib.log import Console
from lsmiotool.lib import data

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

    def __init__(self, target_dir: str) -> None:
        """Initialize directory traversal.

        Args:
            target_dir: Root directory to traverse
        """
        self.root_dir: str = target_dir
        self.dir_recursive: DirMap = self._gather(target_dir)

    def _gather(self, gather_dir: str) -> DirMap:
        """Recursively gather directory structure.

        Args:
            gather_dir: Directory to gather information from

        Returns:
            Dictionary mapping of directory structure
        """
        folder_dict: DirMap = {}
        for root, dirs, files in os.walk(gather_dir):
            # Process files in current directory
            for file in files:
                file_path = os.path.join(root, file)
                folder_dict[str(file)] = os.path.getsize(file_path)

            # Process subdirectories
            for dir_name in dirs:
                folder_dict[str(dir_name)] = self._gather(
                    os.path.join(root, dir_name)
                )
            break
        return folder_dict

    def get_map(self) -> DirMap:
        """Get the directory structure map.

        Returns:
            Complete directory structure mapping
        """
        return self.dir_recursive

class IorOutputDir(TraverseDir):
    """Directory traversal specialized for IOR output files."""

    def get_map(self) -> Dict[str, Dict[str, Dict[str, FileMetadata]]]:
        """Get IOR output file mapping.

        Returns:
            Dictionary mapping of IOR output files organized by size, stripe count,
            and stripe size.
        """
        meta_dict: Dict[str, Dict[str, Dict[str, FileMetadata]]] = {}

        # Process each field size directory
        for field_size in self.dir_recursive:
            value_size = self.dir_recursive[field_size]
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
                        "path": os.path.join(self.root_dir, *key_dir_list)
                    }

        return meta_dict

class LsmioOutputDir(IorOutputDir):
    """Directory traversal specialized for LSMIO output files.

    This class inherits from IorOutputDir as LSMIO uses the same output
    file structure.
    """

class IorAggOutput(DebuggableObject):
    """Aggregate IOR output data processor."""

    # Configuration constants
    _operations: List[str] = ['read', 'write']
    _stripe_counts: List[str] = ['4', '16']
    _stripe_sizes: List[str] = ['64K', '1M', '8M']
    _node_counts: List[str] = [
        '1', '2', '4', '8', '16', '24', '32', '40', '48'
    ]

    def __init__(self, output_dir: str) -> None:
        """Initialize IOR output data processor.

        Args:
            output_dir: Directory containing IOR output files
        """
        self.out_dir: str = output_dir
        ior_dir = IorOutputDir(self.out_dir)
        dir_map = ior_dir.get_map()
        self.agg_data: AggData = {}

        # Process data for each node count
        for n_count in self._node_counts:
            self.agg_data[n_count] = {}

            # Process data for each stripe configuration
            for s_count in self._stripe_counts:
                self.agg_data[n_count][s_count] = {}

                # Process data for each stripe size
                for s_size in self._stripe_sizes:
                    self.agg_data[n_count][s_count][s_size] = []

                    # Validate directory structure
                    if n_count not in dir_map:
                        self._log_error({
                            n_count: 'node count not found in output directory'
                        })
                    if s_count not in dir_map[n_count]:
                        self._log_error({
                            s_count: 'stripe count not found in output directory'
                        })
                    if s_size not in dir_map[n_count][s_count]:
                        self._log_error({
                            s_count: 'stripe size not found in output directory'
                        })
                    if len(dir_map[n_count][s_count][s_size]) != int(n_count):
                        self._log_error({
                            0: 'number of files does not match node count'
                        })

                    # Process aggregated files
                    self.agg_data[n_count][s_count][s_size] = \
                        self._process_agg_files(
                            dir_map[n_count][s_count][s_size],
                            n_count
                        )

    def _process_agg_files(
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
            sr_map = sr_data.get_map()
            sim_data.append(sr_map)

        # Validate data
        if len(sim_data) != 1:
            self._log_error({
                0: 'number of simulation data does not match node count'
            })

        return sim_data[0]

    def get_map(self) -> AggData:
        """Get the aggregated data map.

        Returns:
            Complete mapping of aggregated performance data
        """
        return self.agg_data

class LsmioAggOutput(IorAggOutput):
    """Aggregate LSMIO output data processor."""

    def _process_agg_files(
        self,
        f_files: Dict[str, FileMetadata],
        f_count: str
    ) -> AccessData:
        """Process aggregated LSMIO output files.

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
            sr_data = data.LsmioSingleRunData(file_meta["path"])
            sr_map = sr_data.get_map()
            sim_data.append(sr_map)

        # Validate data
        if len(sim_data) != int(f_count):
            self._log_error({
                0: 'number of simulation data does not match node count'
            })

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

        # Aggregate metrics from all files
        for sim in sim_data:
            # Aggregate read metrics
            agg_map['read']['max(MiB)/s'] += float(
                sim['read']['max(MiB)/s']
            )
            agg_map['read']['min(MiB/s)'] += float(
                sim['read']['min(MiB/s)'
            ])
            agg_map['read']['mean(MiB/s)'] += float(
                sim['read']['mean(MiB/s)'
            ])
            agg_map['read']['total(MiB)'] += float(
                sim['read']['total(MiB)'
            ])
            agg_map['read']['total(Ops)'] += float(
                sim['read']['total(Ops)']
            )
            # Store iteration count
            agg_map['read']['iteration'] = int(sim['read']['iteration'])

            # Aggregate write metrics
            agg_map['write']['max(MiB)/s'] += float(
                sim['write']['max(MiB)/s']
            )
            agg_map['write']['min(MiB/s)'] += float(
                sim['write']['min(MiB/s)']
            )
            agg_map['write']['mean(MiB/s)'] += float(
                sim['write']['mean(MiB/s)']
            )
            agg_map['write']['total(MiB)'] += float(
                sim['write']['total(MiB)']
            )
            agg_map['write']['total(Ops)'] += float(
                sim['write']['total(Ops)']
            )
            agg_map['write']['iteration'] = int(sim['write']['iteration'])

        return agg_map

class IorFullOutput(IorAggOutput):
    """Full IOR output data processor.

    This class inherits from IorAggOutput and provides access to the complete
    aggregated data without any additional processing.
    """

    def get_map(self) -> AggData:
        """Get the complete aggregated data map.

        Returns:
            Complete mapping of aggregated performance data
        """
        return self.agg_data

    def time_series(
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
        sum_data = self.get_map()
        access = 'read' if f_read else 'write'
        x_series = self._node_counts
        y_series: List[float] = []
        for n_count in x_series:
            y_series.append(sum_data[n_count][str(f_stripe_count)][f_stripe_size][access]['Max(MiB)'])
        return (x_series, y_series)

class LsmioFullOutput(LsmioAggOutput):
    def time_series(self, f_read: bool, f_stripe_count: int, f_stripe_size: str) -> Tuple[List[str], List[float]]:
        sum_data = self.get_map()
        access = 'read' if f_read else 'write'
        xSeries = self._node_counts
        ySeries: List[float] = []
        for n_count in xSeries:
            ySeries.append(sum_data[n_count][str(f_stripe_count)][f_stripe_size][access]['max(MiB)/s'])
        return (xSeries, ySeries)
