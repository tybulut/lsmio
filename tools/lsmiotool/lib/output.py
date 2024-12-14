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
from lsmiotool.lib.debuggable import DebuggableObject
from lsmiotool.lib.log import Console
from lsmiotool.lib import data


class TraverseDir(DebuggableObject):
  def __init__(self, target_dir):
    self.root_dir = target_dir
    self.dir_recursive = self._gather(target_dir)

  #ior-outputs/4/2023-07-21/
  #  out-collective-16-1M-2023-07-21-node109-0.txt.2
  #  out-collective-16-1M-2023-07-21-node110-0.txt.2
  #  out-collective-16-1M-2023-07-21-node116-0.txt.2
  #  out-collective-16-1M-2023-07-21-node120-0.txt.2
  #  out-collective-16-64K-2023-07-21-node109-0.txt.2
  #  out-collective-16-64K-2023-07-21-node110-0.txt.2
  #  out-collective-16-64K-2023-07-21-node116-0.txt.2
  #  out-collective-16-64K-2023-07-21-node120-0.txt.2
  def _gather(self, gather_dir):
    folder_dict = {}
    for root, dirs, files in os.walk(gather_dir):
        for file in files:
            file_path = os.path.join(root, file)
            folder_dict[file] = os.path.getsize(file_path)
        for odir in dirs:
            folder_dict[odir] = self._gather(os.path.join(root, odir))
        break
    return folder_dict


  def getMap(self):
    #Console.debug("self.dir_recursive: " + pprint.pformat(self.dir_recursive))
    return self.dir_recursive


#{'1': {'2023-07-21':
#                               {'out-collective-16-1M-2023-07-21-node169-0.txt.2': 6952,
#                                'out-collective-16-64K-2023-07-21-node169-0.txt.2': 6969,
#                                'out-collective-16-8M-2023-07-21-node169-0.txt.2': 6949,
#                                'out-collective-4-1M-2023-07-21-node169-0.txt.2': 6949,
#                                'out-collective-4-64K-2023-07-21-node169-0.txt.2': 6966,
#                                'out-collective-4-8M-2023-07-21-node169-0.txt.2': 6947},
# ...
class IorOutputDir(TraverseDir):

  def getMap(self):
    meta_dict = {}
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
    #Console.debug("meta_dict: " + pprint.pformat(meta_dict))
    return meta_dict


class LsmioOutputDir(IorOutputDir):
    pass


class IorAggOutput(DebuggableObject):
  _operations = ['read', 'write']
  _stripe_counts = ['4', '16']
  _stripe_sizes = ['64K', '1M', '8M']
  _node_counts= ['1', '2', '4', '8', '16', '24', '32', '40', '48']

  def __init__(self, output_dir):
    self.out_dir = output_dir
    ior_dir = IorOutputDir(self.out_dir)
    dir_map = ior_dir.getMap()
    self.agg_data = {}
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


  def _processAggFies(self, f_files, f_count):
    sim_data = []
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


  def getMap(self):
    #Console.debug("self.agg_data: " + pprint.pformat(self.agg_data))
    return self.agg_data


class LsmioAggOutput(IorAggOutput):

  #access,max(MiB)/s,min(MiB/s),mean(MiB/s),total(MiB),total(Ops),iteration
  #write,473.28,318.5,441.18,5119.92,81920,10
  #read,2646.78,2180.84,2427.9,5119.92,81920,10
  def _processAggFies(self, f_files, f_count):
    sim_data = []
    for file in f_files:
        file_meta = f_files[file]
        sr_data = data.LsmioSingleRunData(file_meta["path"])
        sr_map = sr_data.getMap()
        sim_data.append(sr_map)
        #Console.debug("Lsmio path: " + file_meta["path"])
        #Console.debug("Lsmio sim: " + pprint.pformat(sr_map))
    if len(sim_data) != f_count:
        self._logError({ 0: 'number of simulation data does not match node count)' })
    agg_map = {
        'read': {
            'max(MiB)/s' : float(0.00),
            'min(MiB/s)' : float(0.00),
            'mean(MiB/s)' : float(0.00),
            'total(MiB)' : float(0),
            'total(Ops)' : float(0),
            'iteration' : int(0)
        },
        'write': {
            'max(MiB)/s' : float(0.00),
            'min(MiB/s)' : float(0.00),
            'mean(MiB/s)' : float(0.00),
            'total(MiB)' : float(0),
            'total(Ops)' : float(0),
            'iteration' : int(0)
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


# class IorSumOutput
#
#    self.out_data = {
#      # operation -> numStripes -> stripeSize -> numNodes
#    }
#          if numNodes not in self.csv_data[operation][numStripes][stripeSize]:
#              self.csv_data[operation][numStripes][stripeSize][numNodes] = {}
#          partData = {
#            'maxMB': float(0.00),
#            'minMB': float(0.00),
#            'meanMB': float(0.00),
#          }
#          if row[4]: partData['maxMB'] = float(row[4])
#          if row[5]: partData['minMB'] = float(row[5])
#          if row[6]: partData['meanMB'] = float(row[6])
#          self.csv_data[operation][numStripes][stripeSize][numNodes] = partData
#
#  def timeSeries(self, isRead: bool, numStripes: int, stripeSize: str):
#    operation = 'read' if isRead == True else 'write'
#    partData = self.csv_data[operation][numStripes][stripeSize]
#    xSeries = []
#    ySeries = []
#    for node in sorted(partData):
#        xSeries.append(node)
#        ySeries.append(partData[node]['maxMB'])
#    return (xSeries, ySeries)
#

