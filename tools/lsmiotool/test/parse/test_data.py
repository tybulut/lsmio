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

from unittest import TestCase
from io import StringIO
from typing import List, Dict, Tuple, Union, Any
from lsmiotool.lib.log import Console
from lsmiotool.lib import data

import os
from pathlib import Path
import pprint

MY_DIR = Path(__file__).parent.resolve()

class DataUnitTestCase(TestCase):

  # N,Stripes,BlockSize,Operation,Max(MiB),Min(MiB),Mean(MiB),StdDev,...
  # 1,16,8M,read,5353.38,5160.61,5293.08,49.88,66...
  def test_ior_data(self) -> None:
    data_file_list = ['example', 'ior-report.csv']
    data_file = os.path.join(MY_DIR, *data_file_list)
    Console.debug('Reading IOR CSV file: ' + data_file + '.')
    ior_run = data.IorSummaryData(data_file)
    (xSeries, ySeries) = ior_run.time_series(False, 4, '64K')
    #Console.debug("test_ior_data: " + str(ySeries))
    self.assertEqual(xSeries, [1, 2, 4, 8, 16, 24, 32, 40, 48])
    self.assertEqual(ySeries, [885.43, 1693.98, 3482.97, 888.5, 366.97, 237.68, 180.52, 154.18, 147.4])


  def test_lsm_data(self) -> None:
    data_file_list = ['example', 'lsmio-report.csv']
    data_file = os.path.join(MY_DIR, *data_file_list)
    Console.debug('Reading LSMIO CSV file: ' + data_file + '.')
    lsmio_run = data.LsmioSummaryData(data_file)
    (xSeries, ySeries) = lsmio_run.time_series(False, 4, '64K')
    #Console.debug("test_lsm_data: " + str(ySeries))
    self.assertEqual(xSeries, [1, 2, 4, 8, 16, 24, 32, 40, 48])
    self.assertEqual(ySeries, [224.62, 473.28, 841.07, 1518.08, 3220.35, 3466.01, 3617.18, 3911.51, 4165.44])


  #Summary of all tests:
  #Operation   Max(MiB)   Min(MiB)  Mean(MiB)     StdDev   Max(OPs)   Min(OPs)  Mean(OPs)     StdDev    Mean(s) Stonewall(s) Stonewall(MiB) Test# #Tasks tPN reps fPP reord reordoff reordrand seed segcnt   blksiz    xsize aggs(MiB)   API RefNum
  #write        4214.58    2752.91    3571.98     466.80    4214.58    2752.91    3571.98     466.80    0.14599         NA            NA     0      4   1   10   0     0        1         0    0    128  1048576  1048576     512.0 POSIX      0
  #read        14959.41   10729.26   13695.54    1195.05   14959.41   10729.26   13695.54    1195.05    0.03771         NA            NA     0      4   1   10   0     0        1         0    0    128  1048576  1048576     512.0 POSIX      0
  def test_ior_run_data(self) -> None:
    data_file_list = ['example', 'ior-single-run.txt']
    data_file = os.path.join(MY_DIR, *data_file_list)
    Console.debug('Reading IOR single run file: ' + data_file + '.')
    ior_run = data.IorSingleRunData(data_file)
    run_data = ior_run.get_map()
    #Console.debug("test_ior_run_data: " + pprint.pformat(run_data))
    self.assertTrue("read" in run_data)
    self.assertTrue("write" in run_data)
    self.assertEqual(run_data["write"]["Max(MiB)"], 4214.58)
    self.assertEqual(run_data["write"]["StdDev"], 466.8)
    self.assertEqual(run_data["write"]["Mean(OPs)"], 3571.98)
    self.assertEqual(run_data["read"]["Min(MiB)"], 10729.26)
    self.assertEqual(run_data["read"]["StdDev"], 1195.05)
    self.assertEqual(run_data["read"]["Min(OPs)"], 10729.26)


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
  def test_lsm_run_data(self) -> None:
    data_file_list = ['example', 'lsmio-single-run.txt']
    data_file = os.path.join(MY_DIR, *data_file_list)
    Console.debug('Reading LSMO single run file: ' + data_file + '.')
    lsm_run = data.LsmioSingleRunData(data_file)
    run_data = lsm_run.get_map()
    #Console.debug("test_lsm_run_data: " + pprint.pformat(run_data))
    self.assertTrue("read" in run_data)
    self.assertTrue("write" in run_data)
    self.assertEqual(run_data["write"]["bw(MiB/s)"], 167.46)
    self.assertEqual(run_data["write"]["Latency(ms)"], 1.529)
    self.assertEqual(run_data["read"]["bw(MiB/s)"], 320.78)
    self.assertEqual(run_data["read"]["Latency(ms)"], 0.798)

