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

import math
import unittest
from unittest.mock import patch

from lsmiotool.lib.compare import (
    PairedVariantRun,
    pairDirectories,
    percentChange,
)
from lsmiotool.lib.variants import (
    VariantResolutionResult,
)


class PairedVariantRunTest(unittest.TestCase):
    """Unit tests for PairedVariantRun model, directory pairing, and percentChange."""

    def testModelInstantiationAndSerialization(self) -> None:
        """Asserts PairedVariantRun fields, toDict(), fromDict(), and round-trip equality."""
        pair = PairedVariantRun(
            backend="native",
            variant="footer",
            collision=1,
            display_label="footer-1",
            run_dir="/tmp/archive/outputs-native-footer:run-1",
            base_dir="/tmp/archive/outputs-native-footer:base-1",
            run_metadata={
                "backend": "native",
                "variant": "footer",
                "role": "run",
                "collision": "1",
            },
            base_metadata={
                "backend": "native",
                "variant": "footer",
                "role": "base",
                "collision": "1",
            },
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
        """Asserts pairDirectories matches :run with twin :base sharing the same collision index."""
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

        paired = pairDirectories(valid_runs)
        self.assertEqual(len(paired), 1)
        self.assertEqual(paired[0].backend, "native")
        self.assertEqual(paired[0].variant, "footer")
        self.assertEqual(paired[0].collision, 1)
        self.assertEqual(paired[0].run_dir, "/path/to/outputs-native-footer:run-1")
        self.assertEqual(paired[0].base_dir, "/path/to/outputs-native-footer:base-1")

    def testPairDirectoriesFallbackToStandaloneBase(self) -> None:
        """Asserts pairDirectories matches :run with standalone baseline if twin :base is absent."""
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

        paired = pairDirectories(valid_runs)
        self.assertEqual(len(paired), 1)
        self.assertEqual(paired[0].run_dir, "/path/to/outputs-native-footer:run")
        self.assertEqual(paired[0].base_dir, "/path/to/outputs-native")

    def testPairDirectoriesOrphanedRunOmitted(self) -> None:
        """Asserts orphaned :run with no matching baseline is omitted with warning."""
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
            paired = pairDirectories(valid_runs)
            self.assertEqual(len(paired), 0)
            mock_warn.assert_called_once()
            self.assertIn("Orphaned variant run omitted", mock_warn.call_args[0][0])

    def testPercentChange(self) -> None:
        """Asserts percentChange relative delta, non-positive bases, and NaN handling."""
        self.assertAlmostEqual(percentChange(120.0, 100.0), 20.0)
        self.assertAlmostEqual(percentChange(80.0, 100.0), -20.0)
        self.assertTrue(math.isnan(percentChange(80.0, 0.0)))
        self.assertTrue(math.isnan(percentChange(80.0, -5.0)))
        self.assertTrue(math.isnan(percentChange(float("nan"), 100.0)))


if __name__ == "__main__":
    unittest.main()
