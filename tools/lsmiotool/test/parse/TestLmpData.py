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
import tempfile
import unittest
from unittest import TestCase
from lsmiotool.lib import data
from lsmiotool.test.fixtures.MockLogGenerator import MockLogGenerator


class TestLmpData(TestCase):
    """Unit tests for LMP data parsing and summary classes."""

    m_temp_dir: tempfile.TemporaryDirectory
    m_mock_gen: MockLogGenerator

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.TemporaryDirectory()
        self.m_mock_gen = MockLogGenerator(self.m_temp_dir.name)

    def tearDown(self) -> None:
        self.m_temp_dir.cleanup()

    def testLmpSingleRunData(self) -> None:
        """Test extraction of throughput from standard LMP output log."""
        f_path = os.path.join(self.m_temp_dir.name, "out-lmp-4-64K-node0-0.txt")
        self.m_mock_gen.generateLmpFile(f_path, 1, 4, "64K", 345.67)

        lmp_run = data.LmpSingleRunData(f_path)
        run_map = lmp_run.getMap()

        self.assertIn("write", run_map)
        self.assertAlmostEqual(run_map["write"]["throughput"], 345.67)
        self.assertAlmostEqual(run_map["write"]["bw(MiB/s)"], 345.67)

    def testLmpSingleRunDataFloatFallback(self) -> None:
        """Test graceful degradation when encountering non-numeric or corrupted metrics."""
        f_path = os.path.join(self.m_temp_dir.name, "out-corrupt.txt")
        with open(f_path, "w") as f:
            f.write(".write, bw: CORRUPTED_VALUE, total: INVALID\n")
            f.write("write,64K,NOT_A_NUMBER\n")

        lmp_run = data.LmpSingleRunData(f_path)
        run_map = lmp_run.getMap()
        self.assertEqual(run_map["write"]["throughput"], 0.0)

    def testLmpSingleRunDataMissingFile(self) -> None:
        """Test handling of non-existent file path."""
        lmp_run = data.LmpSingleRunData(os.path.join(self.m_temp_dir.name, "nonexistent.txt"))
        run_map = lmp_run.getMap()
        self.assertEqual(run_map["write"]["throughput"], 0.0)

    def testLmpSummaryData(self) -> None:
        """Test LMP summary data CSV parsing and time series extraction."""
        csv_path = os.path.join(self.m_temp_dir.name, "lmp-report.csv")
        content = """1,4,64K,120.5
2,4,64K,240.8
4,4,64K,480.2
1,16,1M,150.0
2,16,1M,300.0
4,16,1M,600.0
"""
        with open(csv_path, "w") as f:
            f.write(content)

        summary = data.LmpSummaryData(csv_path)
        x_series, y_series = summary.timeSeries(False, 4, "64K")
        self.assertEqual(x_series, [1, 2, 4])
        self.assertEqual(y_series, [120.5, 240.8, 480.2])

        x_series_16, y_series_16 = summary.timeSeries(False, 16, "1M")
        self.assertEqual(x_series_16, [1, 2, 4])
        self.assertEqual(y_series_16, [150.0, 300.0, 600.0])

    def testLmpSummaryDataWithCorruptRows(self) -> None:
        """Test summary data robustness against corrupted rows and NaN sentinels."""
        csv_path = os.path.join(self.m_temp_dir.name, "lmp-corrupt-report.csv")
        content = """1,4,64K,NA
2,4,64K,NaN
4,4,64K,480.2
INVALID_ROW
"""
        with open(csv_path, "w") as f:
            f.write(content)

        summary = data.LmpSummaryData(csv_path)
        x_series, y_series = summary.timeSeries(False, 4, "64K")
        self.assertEqual(x_series, [1, 2, 4])
        self.assertEqual(y_series, [0.0, 0.0, 480.2])
