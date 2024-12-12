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


class IorSingleRunData(object):
  def __init__(self, fileName):
    self.fileName = fileName
    self.csvData = {
      # operation -> numStripes -> stripeSize -> numNodes
    }
    # N,Stripes,BlockSize,Operation,Max(MiB),Min(MiB),Mean(MiB),StdDev,...
    # 1,16,8M,read,5353.38,5160.61,5293.08,49.88,66...
    with open(fileName, newline='') as csvfile:
      csvReader = csv.reader(csvfile, delimiter=',', quotechar='|')
      for row in csvReader:
          operation = row[3]
          if operation not in self.csvData:
              self.csvData[operation] = {}
          numStripes = int(row[1])
          if numStripes not in self.csvData[operation]:
              self.csvData[operation][numStripes] = {}
          stripeSize = row[2]
          if stripeSize not in self.csvData[operation][numStripes]:
              self.csvData[operation][numStripes][stripeSize] = {}
          numNodes = int(row[0])
          if numNodes not in self.csvData[operation][numStripes][stripeSize]:
              self.csvData[operation][numStripes][stripeSize][numNodes] = {}
          partData = {
            'maxMB': float(0.00),
            'minMB': float(0.00),
            'meanMB': float(0.00),
          }
          if row[4]: partData['maxMB'] = float(row[4])
          if row[5]: partData['minMB'] = float(row[5])
          if row[6]: partData['meanMB'] = float(row[6])
          self.csvData[operation][numStripes][stripeSize][numNodes] = partData

  def timeSeries(self, isRead: bool, numStripes: int, stripeSize: str):
    operation = 'read' if isRead == True else 'write'
    partData = self.csvData[operation][numStripes][stripeSize]
    xSeries = []
    ySeries = []
    for node in sorted(partData):
        xSeries.append(node)
        ySeries.append(partData[node]['maxMB'])
    return (xSeries, ySeries)


# N,Stripes,BlockSize,Operation,max(MiB)/s,min(MiB/s),mean(MiB/s),total(MiB),
# 1,16,1M,write,58.48,44.21,55.79,2559.96,40960,10
class LsmioSingleRunData(IorSingleRunData):
  pass

class IorSummaryData(object):
  def __init__(self, fileName):
    self.fileName = fileName
    self.csvData = {
      # operation -> numStripes -> stripeSize -> numNodes
    }
    # N,Stripes,BlockSize,Operation,Max(MiB),Min(MiB),Mean(MiB),StdDev,...
    # 1,16,8M,read,5353.38,5160.61,5293.08,49.88,66...
    with open(fileName, newline='') as csvfile:
      csvReader = csv.reader(csvfile, delimiter=',', quotechar='|')
      for row in csvReader:
          operation = row[3]
          if operation not in self.csvData:
              self.csvData[operation] = {}
          numStripes = int(row[1])
          if numStripes not in self.csvData[operation]:
              self.csvData[operation][numStripes] = {}
          stripeSize = row[2]
          if stripeSize not in self.csvData[operation][numStripes]:
              self.csvData[operation][numStripes][stripeSize] = {}
          numNodes = int(row[0])
          if numNodes not in self.csvData[operation][numStripes][stripeSize]:
              self.csvData[operation][numStripes][stripeSize][numNodes] = {}
          partData = {
            'maxMB': float(0.00),
            'minMB': float(0.00),
            'meanMB': float(0.00),
          }
          if row[4]: partData['maxMB'] = float(row[4])
          if row[5]: partData['minMB'] = float(row[5])
          if row[6]: partData['meanMB'] = float(row[6])
          self.csvData[operation][numStripes][stripeSize][numNodes] = partData

  def timeSeries(self, isRead: bool, numStripes: int, stripeSize: str):
    operation = 'read' if isRead == True else 'write'
    partData = self.csvData[operation][numStripes][stripeSize]
    xSeries = []
    ySeries = []
    for node in sorted(partData):
        xSeries.append(node)
        ySeries.append(partData[node]['maxMB'])
    return (xSeries, ySeries)


# N,Stripes,BlockSize,Operation,max(MiB)/s,min(MiB/s),mean(MiB/s),total(MiB),
# 1,16,1M,write,58.48,44.21,55.79,2559.96,40960,10
class LsmioSummaryData(IorSummaryData):
  pass

