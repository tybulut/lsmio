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

import math
import os
import tempfile
from typing import Dict, List, Any
from unittest import TestCase
from lsmiotool.lib import output, data
from lsmiotool.test.fixtures.MockLogGenerator import MockLogGenerator


class MockTwoNodeLsmioAggOutput(output.LsmioAggOutput):
    """Subclass configured for 1 and 2 node testing."""

    _node_counts: List[str] = ["1", "2"]


class MockTwoNodeLmpAggOutput(output.LmpAggOutput):
    """Subclass configured for 1 and 2 node testing."""

    _node_counts: List[str] = ["1", "2"]


class TestOutputAggregation(TestCase):
    """Unit tests for output aggregation, math stability, and reporting."""

    m_temp_dir: tempfile.TemporaryDirectory
    m_mock_gen: MockLogGenerator

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.TemporaryDirectory()
        self.m_mock_gen = MockLogGenerator(self.m_temp_dir.name)

    def tearDown(self) -> None:
        self.m_temp_dir.cleanup()

    def testLsmioMathStabilityFsum(self) -> None:
        """Test that math.fsum prevents floating point accumulation drift."""
        # Generate 2 nodes for LSMIO
        self.m_mock_gen.generateMockDirectoryTree(
            self.m_temp_dir.name,
            f_bench_type="lsmio",
            f_nodes=["1", "2"],
            f_stripes=["4", "16"],
            f_sizes=["64K", "1M", "8M"],
        )

        lsm_agg = MockTwoNodeLsmioAggOutput(self.m_temp_dir.name)
        agg_map = lsm_agg.getMap()

        self.assertIn("1", agg_map)
        self.assertIn("2", agg_map)
        # Node 2 write total should be exactly 2 * 167.46 = 334.92
        node2_write_max = agg_map["2"]["4"]["64K"]["write"]["max(MiB)/s"]
        self.assertAlmostEqual(node2_write_max, 334.92, places=5)

    def testMissingDataErrorOnIncompleteFiles(self) -> None:
        """Test that MissingDataError is raised when expected file counts mismatch actual files."""
        # Generate incomplete directory: 2 node count requested but only 1 file present
        base = self.m_temp_dir.name
        n_dir = os.path.join(base, "2", "2023-07-01")
        os.makedirs(n_dir, exist_ok=True)
        # Only 1 file created for node count 2
        f1 = os.path.join(n_dir, "out-lsmio-4-64K-2023-07-01-node000-0.txt.2")
        self.m_mock_gen.generateLsmioFile(f1, 2, 4, "64K")

        # Initializing MockTwoNodeLsmioAggOutput should raise MissingDataError
        with self.assertRaises(output.MissingDataError):
            MockTwoNodeLsmioAggOutput(base)

    def testLmpOutputDirAndAggOutput(self) -> None:
        """Test LMP directory traversal and aggregation."""
        self.m_mock_gen.generateMockDirectoryTree(
            self.m_temp_dir.name,
            f_bench_type="lmp",
            f_nodes=["1", "2"],
            f_stripes=["4", "16"],
            f_sizes=["64K", "1M", "8M"],
        )

        lmp_dir = output.LmpOutputDir(self.m_temp_dir.name)
        d_map = lmp_dir.getMap()
        self.assertIn("1", d_map)
        self.assertIn("2", d_map)

        lmp_agg = MockTwoNodeLmpAggOutput(self.m_temp_dir.name)
        agg_map = lmp_agg.getMap()
        self.assertIn("1", agg_map)
        self.assertIn("2", agg_map)

        # 2 files for node 2, each 123.45 -> sum = 246.90
        sum_tp = agg_map["2"]["4"]["64K"]["write"]["max(MiB)/s"]
        self.assertAlmostEqual(sum_tp, 246.90, places=4)

    def testGenerateReportsStage1AndStage2(self) -> None:
        """Test generation of Stage 1 intermediate and Stage 2 master report CSVs."""
        self.m_mock_gen.generateMockDirectoryTree(
            self.m_temp_dir.name,
            f_bench_type="lsmio",
            f_nodes=["1", "2"],
            f_stripes=["4", "16"],
            f_sizes=["64K", "1M", "8M"],
        )

        lsm_agg = MockTwoNodeLsmioAggOutput(self.m_temp_dir.name)
        lsm_agg.generateReports(self.m_temp_dir.name)

        # Verify Stage 1 files exist
        stage1_file = os.path.join(self.m_temp_dir.name, "1", "agg-4-64K-report.csv")
        self.assertTrue(os.path.exists(stage1_file))

        # Verify Stage 2 master report exists
        master_file = os.path.join(self.m_temp_dir.name, "lsm-report.csv")
        self.assertTrue(os.path.exists(master_file))

        # Read master file and verify rows
        with open(master_file, "r") as f:
            lines = f.readlines()
        self.assertTrue(len(lines) > 0)
        first_line = lines[0].strip()
        # Row format should be n,rf,bs,write/read,...
        parts = first_line.split(",")
        self.assertIn(parts[0], ["1", "2"])
        self.assertIn(parts[1], ["4", "16"])
        self.assertIn(parts[2], ["64K", "1M", "8M"])
