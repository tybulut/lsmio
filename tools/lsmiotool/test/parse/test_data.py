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
from lsmiotool.lib.log import Console
from lsmiotool.lib import data

import os
from pathlib import Path

MY_DIR = Path(__file__).parent.resolve()

# N,Stripes,BlockSize,Operation,Max(MiB),Min(MiB),Mean(MiB),StdDev,...
# 1,16,8M,read,5353.38,5160.61,5293.08,49.88,66...
class DataUnitTestCase(TestCase):

  def test_ior_data(self):
    dataFileList = ['example', 'ior-report.csv']
    dataFile = os.path.join(MY_DIR, *dataFileList)
    Console.debug('Reading IOR CSV file: ' + dataFile + '.')
    iorRun = data.IorSummaryData(dataFile)
    (xSeries, ySeries) = iorRun.timeSeries(False, 4, '64K')
    self.assertEqual(xSeries, [1, 2, 4, 8, 16, 24, 32, 40, 48])
    self.assertEqual(ySeries, [885.43, 1693.98, 3482.97, 888.5, 366.97, 237.68, 180.52, 154.18, 147.4])

  def test_lsm_data(self):
    dataFileList = ['example', 'lsm-report.csv']
    dataFile = os.path.join(MY_DIR, *dataFileList)
    Console.debug('Reading LSMIO CSV file: ' + dataFile + '.')
    lsmioRun = data.LsmioSummaryData(dataFile)
    (xSeries, ySeries) = lsmioRun.timeSeries(False, 4, '64K')
    self.assertEqual(xSeries, [1, 2, 4, 8, 16, 24, 32, 40, 48])
    self.assertEqual(ySeries, [224.62, 473.28, 841.07, 1518.08, 3220.35, 3466.01, 3617.18, 3911.51, 4165.44])

