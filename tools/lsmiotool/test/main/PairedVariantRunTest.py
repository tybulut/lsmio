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
from unittest.mock import patch

from lsmiotool.lib.main import (
    CompareVariantsMain,
    PairedVariantRun,
)
from lsmiotool.lib.variants import (
    VariantResolutionResult,
)


class PairedVariantRunTest(unittest.TestCase):
    """Unit tests for PairedVariantRun model, directory pairing, and delta computation."""

    def testModelInstantiationAndSerialization(self) -> None:
        """Asserts PairedVariantRun fields, toDict(), fromDict(), and round-trip equality."""
        pair = PairedVariantRun(
            backend="native",
            variant="footer",
            collision=1,
            display_label="footer-1",
            run_dir="/tmp/archive/outputs-native-footer:run-1",
            base_dir="/tmp/archive/outputs-native-footer:base-1",
            run_metadata={"backend": "native", "variant": "footer", "role": "run", "collision": "1"},
            base_metadata={"backend": "native", "variant": "footer", "role": "base", "collision": "1"},
        )

        self.assertEqual(pair.backend, "native")
        self.assertEqual(pair.variant, "footer")
        self.assertEqual(pair.collision, 1)
        self.assertEqual(pair.display_label, "footer-1")
        self.assertEqual(pair.run_dir, "/tmp/archive/outputs-native-footer:run-1")
        self.assertEqual(pair.base_dir, "/tmp/archive/outputs-native-footer:base-1")

        # toDict serialization
        d = pair.toDict()
        self.assertEqual(d["backend"], "native")
        self.assertEqual(d["variant"], "footer")
        self.assertEqual(d["collision"], 1)
        self.assertEqual(d["display_label"], "footer-1")
        self.assertEqual(d["run_dir"], "/tmp/archive/outputs-native-footer:run-1")
        self.assertEqual(d["base_dir"], "/tmp/archive/outputs-native-footer:base-1")

        # fromDict deserialization
        restored = PairedVariantRun.fromDict(d)
        self.assertEqual(pair, restored)

    def testPairDirectoriesTwinMatching(self) -> None:
        """Asserts _pairDirectories matches :run with twin :base sharing the same collision index."""
        cm = CompareVariantsMain(f_archive_folder="/tmp/fake")

        res_run = VariantResolutionResult(
            raw_directory="outputs-native-footer:run-1",
            backend="native",
            variant="footer",
            collision="1",
            display_label="footer-1",
            role="run",
        )
        res_base = VariantResolutionResult(
            raw_directory="outputs-native-footer:base-1",
            backend="native",
            variant="footer",
            collision="1",
            display_label="footer-1",
            role="base",
        )

        valid_runs = [
            (res_run, "/path/to/outputs-native-footer:run-1"),
            (res_base, "/path/to/outputs-native-footer:base-1"),
        ]

        paired = cm._pairDirectories(valid_runs)
        self.assertEqual(len(paired), 1)
        self.assertEqual(paired[0].backend, "native")
        self.assertEqual(paired[0].variant, "footer")
        self.assertEqual(paired[0].collision, 1)
        self.assertEqual(paired[0].run_dir, "/path/to/outputs-native-footer:run-1")
        self.assertEqual(paired[0].base_dir, "/path/to/outputs-native-footer:base-1")

    def testPairDirectoriesFallbackToStandaloneBase(self) -> None:
        """Asserts _pairDirectories matches :run with standalone baseline if twin :base is absent."""
        cm = CompareVariantsMain(f_archive_folder="/tmp/fake")

        res_run = VariantResolutionResult(
            raw_directory="outputs-native-footer:run",
            backend="native",
            variant="footer",
            collision=None,
            display_label="footer",
            role="run",
        )
        res_standalone_base = VariantResolutionResult(
            raw_directory="outputs-native",
            backend="native",
            variant="default",
            collision=None,
            display_label="default",
            role=None,
        )

        valid_runs = [
            (res_run, "/path/to/outputs-native-footer:run"),
            (res_standalone_base, "/path/to/outputs-native"),
        ]

        paired = cm._pairDirectories(valid_runs)
        self.assertEqual(len(paired), 1)
        self.assertEqual(paired[0].run_dir, "/path/to/outputs-native-footer:run")
        self.assertEqual(paired[0].base_dir, "/path/to/outputs-native")

    def testPairDirectoriesOrphanedRunOmitted(self) -> None:
        """Asserts orphaned :run with no matching baseline is omitted with warning."""
        cm = CompareVariantsMain(f_archive_folder="/tmp/fake")

        res_run = VariantResolutionResult(
            raw_directory="outputs-native-footer:run",
            backend="native",
            variant="footer",
            collision=None,
            display_label="footer",
            role="run",
        )

        valid_runs = [(res_run, "/path/to/outputs-native-footer:run")]

        with patch("lsmiotool.lib.log.Console.warning") as mock_warn:
            paired = cm._pairDirectories(valid_runs)
            self.assertEqual(len(paired), 0)
            mock_warn.assert_called_once()
            self.assertIn("Orphaned variant run omitted", mock_warn.call_args[0][0])

    def testComputeDeltaRelativeAndAbsolute(self) -> None:
        """Asserts _computeDelta calculates relative % and absolute throughput preserving negatives (INV-PAIR-4)."""
        cm = CompareVariantsMain(f_archive_folder="/tmp/fake")

        # Positive improvement: 120 vs 100 -> +20.0%
        self.assertAlmostEqual(cm._computeDelta(120.0, 100.0, "percent"), 20.0)

        # Negative regression: 80 vs 100 -> -20.0% (preserved, NOT clamped)
        self.assertAlmostEqual(cm._computeDelta(80.0, 100.0, "percent"), -20.0)

        # Zero base guard: returns 0.0
        self.assertEqual(cm._computeDelta(80.0, 0.0, "percent"), 0.0)
        self.assertEqual(cm._computeDelta(80.0, -5.0, "percent"), 0.0)

        # Absolute delta
        self.assertAlmostEqual(cm._computeDelta(125.0, 100.0, "abs"), 25.0)
        self.assertAlmostEqual(cm._computeDelta(75.0, 100.0, "abs"), -25.0)

    def testGenerateDeltaChartExecution(self) -> None:
        """Asserts _generateDeltaChart produces delta chart file with proper naming."""
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_dir = os.path.join(temp_dir, "archive")
            out_dir = os.path.join(temp_dir, "charts")
            os.makedirs(archive_dir)

            cm = CompareVariantsMain(f_archive_folder=archive_dir, f_output_dir=out_dir)
            delta_data = [("footer", 15.0), ("btree", -8.5)]

            chart_path = cm._generateDeltaChart(
                op="read",
                stripes=4,
                blocksize="1M",
                delta_data=delta_data,
                metric="percent",
                out_dir=out_dir,
            )

            self.assertTrue(os.path.isfile(chart_path))
            self.assertIn("compare-variants-delta-archive-read-4-1M.png", os.path.basename(chart_path))
            self.assertGreater(os.path.getsize(chart_path), 0)


if __name__ == "__main__":
    unittest.main()
