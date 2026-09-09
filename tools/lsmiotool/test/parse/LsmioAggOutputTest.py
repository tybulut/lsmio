#
# Copyright 2026 Serdar Bulut
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
from typing import List

from lsmiotool.lib import output
from lsmiotool.test.fixtures.MockLogGenerator import MockLogGenerator


class LsmioAggOutputTest(unittest.TestCase):
    """Unit tests for LsmioAggOutput baseline node scoping and log aggregation."""

    STANDARD_NODE_COUNTS: List[str] = [
        "1",
        "2",
        "4",
        "8",
        "16",
        "24",
        "32",
        "40",
        "48",
    ]

    m_temp_dir: tempfile.TemporaryDirectory
    m_mock_gen: MockLogGenerator

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.TemporaryDirectory()
        self.m_mock_gen = MockLogGenerator(self.m_temp_dir.name)

    def tearDown(self) -> None:
        self.m_temp_dir.cleanup()

    def testStandardNodeCountsWhenScaleNotBaseline(self) -> None:
        """Asserts that _node_counts contains standard 9 node counts when scale is not baseline."""
        # When f_scale is omitted or None (standard legacy scales)
        # We test the node configuration without calling super().__init__ by inspecting class attribute
        self.assertEqual(output.LsmioAggOutput._node_counts, self.STANDARD_NODE_COUNTS)

        # Generate standard mock directory tree with all 9 nodes
        self.m_mock_gen.generateMockDirectoryTree(
            self.m_temp_dir.name,
            f_bench_type="lsmio",
            f_nodes=self.STANDARD_NODE_COUNTS,
            f_stripes=["4", "16"],
            f_sizes=["64K", "1M", "8M"],
        )

        agg_default = output.LsmioAggOutput(self.m_temp_dir.name)
        self.assertEqual(agg_default._node_counts, self.STANDARD_NODE_COUNTS)

        agg_local = output.LsmioAggOutput(self.m_temp_dir.name, f_scale="local")
        self.assertEqual(agg_local._node_counts, self.STANDARD_NODE_COUNTS)

    def testBaselineNodeCountsScopedToEight(self) -> None:
        """Asserts that _node_counts is scoped strictly to ['8'] when scale is baseline."""
        # Generate mock directory tree containing only node '8'
        self.m_mock_gen.generateMockDirectoryTree(
            self.m_temp_dir.name,
            f_bench_type="lsmio",
            f_nodes=["8"],
            f_stripes=["4", "16"],
            f_sizes=["64K", "1M", "8M"],
        )

        # Lowercase baseline
        agg_baseline = output.LsmioAggOutput(self.m_temp_dir.name, f_scale="baseline")
        self.assertEqual(agg_baseline._node_counts, ["8"])

        # Uppercase BASELINE (case insensitivity)
        agg_baseline_upper = output.LsmioAggOutput(
            self.m_temp_dir.name, f_scale="BASELINE"
        )
        self.assertEqual(agg_baseline_upper._node_counts, ["8"])

    def testBaselineOutputProcessingWithoutMissingDataError(self) -> None:
        """Asserts that baseline scale processes successfully without MissingDataError for absent nodes."""
        # Generate mock directory tree containing only node '8'
        self.m_mock_gen.generateMockDirectoryTree(
            self.m_temp_dir.name,
            f_bench_type="lsmio",
            f_nodes=["8"],
            f_stripes=["4", "16"],
            f_sizes=["64K", "1M", "8M"],
        )

        # Processing with f_scale='baseline' must succeed cleanly without MissingDataError
        agg = output.LsmioAggOutput(self.m_temp_dir.name, f_scale="baseline")
        agg_map = agg.getMap()

        self.assertIn("8", agg_map)
        self.assertNotIn("1", agg_map)
        self.assertNotIn("2", agg_map)
        self.assertNotIn("16", agg_map)

        # Verify metrics aggregated for node 8
        self.assertIn("4", agg_map["8"])
        self.assertIn("16", agg_map["8"])
        self.assertIn("64K", agg_map["8"]["4"])
        self.assertIn("write", agg_map["8"]["4"]["64K"])
        self.assertIn("read", agg_map["8"]["4"]["64K"])

    def testMissingDataErrorOnIncompleteNodeEightFiles(self) -> None:
        """Asserts that MissingDataError is raised when expected file count for node 8 mismatches actual files."""
        base = self.m_temp_dir.name
        n_dir = os.path.join(base, "8", "2026-09-09")
        os.makedirs(n_dir, exist_ok=True)
        # Create only 1 file when 8 are expected for node 8
        f1 = os.path.join(n_dir, "out-lsmio-4-64K-2026-09-09-node000-0.txt.8")
        self.m_mock_gen.generateLsmioFile(f1, 8, 4, "64K")

        with self.assertRaises(output.MissingDataError):
            output.LsmioAggOutput(base, f_scale="baseline")


if __name__ == "__main__":
    unittest.main()
