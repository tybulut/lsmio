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

import os, re, pprint
from typing import Dict, List, Union, TypedDict, Tuple, Optional
from lsmiotool.lib.debuggable import DebuggableObject
from lsmiotool.lib.log import Console
from lsmiotool.lib import data

class FileMetadata(TypedDict):
    size: int
    path: str

class DirMap(TypedDict):
    size: Union[int, Dict[str, 'DirMap']]

class MetricData(TypedDict):
    max_mib_per_s: float  # max(MiB)/s
    min_mib_per_s: float  # min(MiB/s)
    mean_mib_per_s: float  # mean(MiB/s)
    total_mib: float  # total(MiB)
    total_ops: float  # total(Ops)
    iteration: int

class AccessData(TypedDict):
    read: MetricData
    write: MetricData

class AggData(TypedDict):
    size: Union[Dict[str, Dict[str, Dict[str, AccessData]]], None]

class TraverseDir(DebuggableObject):
    def __init__(self, target_dir: str) -> None:
        self.root_dir: str = target_dir
        self.dir_recursive: DirMap = self._gather(target_dir)

    def _gather(self, gather_dir: str) -> DirMap:
        folder_dict: DirMap = {}
        for root, dirs, files in os.walk(gather_dir):
            for file in files:
                file_path = os.path.join(root, file)
                folder_dict[str(file)] = os.path.getsize(file_path)
            for odir in dirs:
                folder_dict[str(odir)] = self._gather(os.path.join(root, odir))
            break
        return folder_dict

    def getMap(self) -> DirMap:
        return self.dir_recursive

class IorOutputDir(TraverseDir):
    def getMap(self) -> Dict[str, Dict[str, Dict[str, FileMetadata]]]:
        meta_dict: Dict[str, Dict[str, Dict[str, FileMetadata]]] = {}
        for field_size in self.dir_recursive:
            value_size = self.dir_recursive[field_size]
            if not isinstance(value_size, dict):
                Console.debug("Unexpeted field_size: " + field_size)
                Console.debug("Unexpeted value_size: " + str(value_size))
                continue
            if field_size not in meta_dict:
                meta_dict[field_size] = {}
            for date_dir in value_size:
                value_date = value_size[date_dir]
                if not isinstance(value_date, dict):
                    continue # date: '2023-07-21'
                for key in value_date:
                    val = value_date[key]
                    if isinstance(val, dict):
                        continue # something else...
                    pattern = r"out-[a-zA-Z\d-]*-(\d+)-(\d+[KMGTB])-\d+-\d+-\d+-[a-zA-Z\d]+-\d+\.\w+\.\d+"
                    match = re.match(pattern, key)
                    if not match:
                        Console.debug("Unexpected file pattern: " + key)
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
                        "path": os.path.join(self.root_dir, *key_dir_list)
                    }
        return meta_dict

class LsmioOutputDir(IorOutputDir):
    pass

class IorAggOutput(DebuggableObject):
    _operations: List[str] = ['read', 'write']
    _stripe_counts: List[str] = ['4', '16']
    _stripe_sizes: List[str] = ['64K', '1M', '8M']
    _node_counts: List[str] = ['1', '2', '4', '8', '16', '24', '32', '40', '48']

    def __init__(self, output_dir: str) -> None:
        self.out_dir: str = output_dir
        ior_dir = IorOutputDir(self.out_dir)
        dir_map = ior_dir.getMap()
        self.agg_data: AggData = {}

        for n_count in self._node_counts:
            self.agg_data[n_count] = {}
            for s_count in self._stripe_counts:
                self.agg_data[n_count][s_count] = {}
                for s_size in self._stripe_sizes:
                    self.agg_data[n_count][s_count][s_size] = []
                    # Sanity check dir_map
                    if n_count not in dir_map:
                        self._logError({ n_count: 'node count not found in output directory)' })
                    if s_count not in dir_map[n_count]:
                        self._logError({ s_count: 'stripe count not found in output directory)' })
                    if s_size not in dir_map[n_count][s_count]:
                        self._logError({ s_count: 'stripe size not found in output directory)' })
                    if len(dir_map[n_count][s_count][s_size]) != n_count:
                        self._logError({ 0: 'number of files does not match node count)' })
                    # Back to establishing its own data structure
                    if n_count not in self.agg_data:
                        self._logError({ n_count: 'node count not found in output directory)' })
                    if s_count not in dir_map[n_count]:
                        self._logError({ s_count: 'stripe count not found in output directory)' })
                    self.agg_data[n_count][s_count][s_size] = self._processAggFies(dir_map[n_count][s_count][s_size], n_count)

    def _processAggFies(self, f_files: Dict[str, FileMetadata], f_count: str) -> AccessData:
        sim_data: List[AccessData] = []
        for file in f_files:
            file_meta = f_files[file]
            if file_meta["size"] == 0:
                continue
            sr_data = data.IorSingleRunData(file_meta["path"])
            sr_map = sr_data.getMap()
            sim_data.append(sr_map)
        if len(sim_data) != 1:
            self._logError({ 0: 'number of simulation data does not match node count)' })
        return sim_data[0]

    def getMap(self) -> AggData:
        return self.agg_data

class LsmioAggOutput(IorAggOutput):
    def _processAggFies(self, f_files: Dict[str, FileMetadata], f_count: str) -> AccessData:
        sim_data: List[AccessData] = []
        for file in f_files:
            file_meta = f_files[file]
            sr_data = data.LsmioSingleRunData(file_meta["path"])
            sr_map = sr_data.getMap()
            sim_data.append(sr_map)
        if len(sim_data) != int(f_count):
            self._logError({ 0: 'number of simulation data does not match node count)' })
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
        for sim in sim_data:
            agg_map['read']['max(MiB)/s'] += float(sim['read']['max(MiB)/s'])
            agg_map['read']['min(MiB/s)'] += float(sim['read']['min(MiB/s)'])
            agg_map['read']['mean(MiB/s)'] += float(sim['read']['mean(MiB/s)'])
            agg_map['read']['total(MiB)'] += float(sim['read']['total(MiB)'])
            agg_map['read']['total(Ops)'] += float(sim['read']['total(Ops)'])
            agg_map['read']['iteration'] = int(sim['read']['iteration'])
            agg_map['write']['max(MiB)/s'] += float(sim['write']['max(MiB)/s'])
            agg_map['write']['min(MiB/s)'] += float(sim['write']['min(MiB/s)'])
            agg_map['write']['mean(MiB/s)'] += float(sim['write']['mean(MiB/s)'])
            agg_map['write']['total(MiB)'] += float(sim['write']['total(MiB)'])
            agg_map['write']['total(Ops)'] += float(sim['write']['total(Ops)'])
            agg_map['write']['iteration'] = int(sim['write']['iteration'])
        return agg_map

class IorFullOutput(IorAggOutput):
    def timeSeries(self, f_read: bool, f_stripe_count: int, f_stripe_size: str) -> Tuple[List[str], List[float]]:
        sum_data = self.getMap()
        access = 'read' if f_read else 'write'
        xSeries = self._node_counts
        ySeries: List[float] = []
        for n_count in xSeries:
            ySeries.append(sum_data[n_count][str(f_stripe_count)][f_stripe_size][access]['Max(MiB)'])
        return (xSeries, ySeries)

class LsmioFullOutput(LsmioAggOutput):
    def timeSeries(self, f_read: bool, f_stripe_count: int, f_stripe_size: str) -> Tuple[List[str], List[float]]:
        sum_data = self.getMap()
        access = 'read' if f_read else 'write'
        xSeries = self._node_counts
        ySeries: List[float] = []
        for n_count in xSeries:
            ySeries.append(sum_data[n_count][str(f_stripe_count)][f_stripe_size][access]['max(MiB)/s'])
        return (xSeries, ySeries)
