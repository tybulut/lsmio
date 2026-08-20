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
import shutil
import tempfile
from unittest import TestCase
from lsmiotool.lib import output, main


class TestEndToEndParse(TestCase):
    """End-to-end integration test against ground truth synthetic benchmarking dataset."""

    m_temp_dir: tempfile.TemporaryDirectory
    m_ground_truth_dir: str
    m_ground_truth_report: str

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.TemporaryDirectory()
        candidate_paths = [
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "lsmio-data", "synthetic", "viking", "lsmio-small-hdd", "lsmio-adios"),
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "lsmio-data", "synthetic", "viking", "lsmio-small-hdd", "lsmio-adios"),
            "/Users/sbulut/src/bulut/lsmio-data/synthetic/viking/lsmio-small-hdd/lsmio-adios",
            os.path.expanduser("~/src/lsmio-data/synthetic/viking/lsmio-small-hdd/lsmio-adios")
        ]
        self.m_ground_truth_dir = ""
        for p in candidate_paths:
            p_abs = os.path.abspath(p)
            if os.path.exists(p_abs):
                self.m_ground_truth_dir = p_abs
                break
        self.m_ground_truth_report = os.path.join(
            self.m_ground_truth_dir,
            "lsm-report.csv"
        )

    def tearDown(self) -> None:
        self.m_temp_dir.cleanup()

    def testEndToEndLsmioParseParity(self) -> None:
        """Verify that parsed and aggregated LSMIO reports match ground truth lsm-report.csv byte-for-byte."""
        if not os.path.exists(self.m_ground_truth_dir):
            self.skipTest(f"Synthetic ground truth directory not found: {self.m_ground_truth_dir}")

        temp_target = self.m_temp_dir.name
        # Copy only the node directories and raw log files into temp dir (excluding pre-existing reports)
        for item in os.listdir(self.m_ground_truth_dir):
            src_item = os.path.join(self.m_ground_truth_dir, item)
            dst_item = os.path.join(temp_target, item)
            if os.path.isdir(src_item) and item.isdigit():
                # Copy directory tree
                shutil.copytree(
                    src_item,
                    dst_item,
                    ignore=shutil.ignore_patterns("agg-*.csv", "*.csv")
                )

        # Run aggregation and report generation
        agg = output.LsmioAggOutput(temp_target)
        agg.generateReports(temp_target)

        # Generated master report
        generated_report = os.path.join(temp_target, "lsm-report.csv")
        self.assertTrue(os.path.exists(generated_report), "Generated lsm-report.csv must exist")

        with open(self.m_ground_truth_report, "r") as f_expected:
            expected_content = f_expected.read()

        with open(generated_report, "r") as f_actual:
            actual_content = f_actual.read()

        expected_lines = [l.strip() for l in expected_content.strip().splitlines() if l.strip()]
        actual_lines = [l.strip() for l in actual_content.strip().splitlines() if l.strip()]

        self.assertEqual(len(actual_lines), len(expected_lines), f"Line count mismatch: expected {len(expected_lines)}, got {len(actual_lines)}")

        for i, (act, exp) in enumerate(zip(actual_lines, expected_lines)):
            self.assertEqual(act, exp, f"Row {i + 1} mismatch: \nActual:   {act}\nExpected: {exp}")

        # Assert full string match
        self.assertEqual(actual_content.strip(), expected_content.strip())
