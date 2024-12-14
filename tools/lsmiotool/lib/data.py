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
from lsmiotool.lib.debuggable import DebuggableObject
from lsmiotool.lib.log import Console


class IorSingleRunData(DebuggableObject):
  def __init__(self, file_name):
    self.file_name = file_name
    self.run_data = {
        "read": {},
        "write": {}
    }
    #Summary of all tests:
    #Operation   Max(MiB)   Min(MiB)  Mean(MiB)     StdDev   Max(OPs)   Min(OPs)  Mean(OPs)     StdDev    Mean(s) Stonewall(s) Stonewall(MiB) Test# #Tasks tPN reps fPP reord reordoff reordrand seed segcnt   blksiz    xsize aggs(MiB)   API RefNum
    #write        4214.58    2752.91    3571.98     466.80    4214.58    2752.91    3571.98     466.80    0.14599         NA            NA     0      4   1   10   0     0        1         0    0    128  1048576  1048576     512.0 POSIX      0
    #read        14959.41   10729.26   13695.54    1195.05   14959.41   10729.26   13695.54    1195.05    0.03771         NA            NA     0      4   1   10   0     0        1         0    0    128  1048576  1048576     512.0 POSIX      0
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
            if heads[i] in ["Max(MiB)", "Min(MiB)", "Mean(MiB)", "StdDev", "Max(OPs)", "Min(OPs)", "Mean(OPs)"]:
                self.run_data["read"][heads[i]] = float(reads[i])
                self.run_data["write"][heads[i]] = float(writes[i])
            else:
                self.run_data["read"][heads[i]] = reads[i]
                self.run_data["write"][heads[i]] = writes[i]

  def getMap(self):
    return self.run_data


class LsmioSingleRunData(DebuggableObject):
  def __init__(self, file_name):
    self.file_name = file_name
    self.run_data = {
        "read": {},
        "write": {}
    }
    #Bench-WRITE: RocksDB SYN: false BLF: false
    #access,bw(MiB/s),Latency(ms),block(KiB),xfer(KiB),iter
    #------,---------,----------,----------,---------,----
    #write,167.46,1.529,1048576,1048576,10
    #
    #Bench-READ: RocksDB SYN: false BLF: false
    #access,bw(MiB/s),Latency(ms),block(KiB),xfer(KiB),iter
    #------,---------,----------,----------,---------,----
    #read,320.78,0.798,1048576,1048576,10
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
        #Console.debug("Lsmio heads: " + head_line)
        #Console.debug("Lsmio reads: " + read_line)
        #Console.debug("Lsmio writes: " + write_line)
        heads = head_line.rstrip().split(",")[1:]
        reads = read_line.rstrip().split(",")[1:]
        writes = write_line.rstrip().split(",")[1:]
        for i in range(len(heads)):
            if heads[i] in ["bw(MiB/s)", "Latency(ms)", "block(KiB)", "xfer(KiB)"]:
                self.run_data["read"][heads[i]] = float(reads[i])
                self.run_data["write"][heads[i]] = float(writes[i])
            else:
                self.run_data["read"][heads[i]] = reads[i]
                self.run_data["write"][heads[i]] = writes[i]

  def getMap(self):
    return self.run_data


class IorSummaryData(DebuggableObject):
  def __init__(self, file_name):
    self.file_name = file_name
    self.csv_data = {
      # operation -> numStripes -> stripeSize -> numNodes
    }
    # N,Stripes,BlockSize,Operation,Max(MiB),Min(MiB),Mean(MiB),StdDev,...
    # 1,16,8M,read,5353.38,5160.61,5293.08,49.88,66...
    with open(file_name, newline='') as csvfile:
      csvReader = csv.reader(csvfile, delimiter=',', quotechar='|')
      for row in csvReader:
          operation = row[3]
          if operation not in self.csv_data:
              self.csv_data[operation] = {}
          numStripes = int(row[1])
          if numStripes not in self.csv_data[operation]:
              self.csv_data[operation][numStripes] = {}
          stripeSize = row[2]
          if stripeSize not in self.csv_data[operation][numStripes]:
              self.csv_data[operation][numStripes][stripeSize] = {}
          numNodes = int(row[0])
          if numNodes not in self.csv_data[operation][numStripes][stripeSize]:
              self.csv_data[operation][numStripes][stripeSize][numNodes] = {}
          partData = {
            'maxMB': float(0.00),
            'minMB': float(0.00),
            'meanMB': float(0.00),
          }
          if row[4]: partData['maxMB'] = float(row[4])
          if row[5]: partData['minMB'] = float(row[5])
          if row[6]: partData['meanMB'] = float(row[6])
          self.csv_data[operation][numStripes][stripeSize][numNodes] = partData

  def timeSeries(self, isRead: bool, numStripes: int, stripeSize: str):
    operation = 'read' if isRead == True else 'write'
    partData = self.csv_data[operation][numStripes][stripeSize]
    xSeries = []
    ySeries = []
    for node in sorted(partData):
        xSeries.append(node)
        ySeries.append(partData[node]['maxMB'])
    return (xSeries, ySeries)


class LsmioSummaryData(IorSummaryData):
  pass

