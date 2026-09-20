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

from lsmiotool.lib.archive import (
    ArchiveEngine,
    ArchiveError,
)


class ArchiveEnginePairTest(unittest.TestCase):
    """Unit tests for ArchiveEngine paired archiving methods and synchronized collision avoidance."""

    def testResolvePairTargetDirectoriesInitial(self) -> None:
        """Asserts that on clean directory, resolvePairTargetDirectories returns synchronized unsuffixed paths."""
        with tempfile.TemporaryDirectory() as temp_dir:
            arm_id = "native-footer"
            run_target, base_target = ArchiveEngine.resolvePairTargetDirectories(temp_dir, arm_id)

            expected_run = os.path.join(temp_dir, "outputs-native-footer:run")
            expected_base = os.path.join(temp_dir, "outputs-native-footer:base")

            self.assertEqual(run_target, expected_run)
            self.assertEqual(base_target, expected_base)
            self.assertIsInstance(run_target, str)
            self.assertIsInstance(base_target, str)

    def testResolvePairTargetDirectoriesSynchronizedCollision(self) -> None:
        """Asserts that if either role exists, both paths advance to the identical collision suffix."""
        with tempfile.TemporaryDirectory() as temp_dir:
            arm_id = "native-footer"
            run_0, base_0 = ArchiveEngine.resolvePairTargetDirectories(temp_dir, arm_id)

            # Scenario A: Only run_0 exists on disk
            os.makedirs(run_0)
            run_1, base_1 = ArchiveEngine.resolvePairTargetDirectories(temp_dir, arm_id)

            expected_run_1 = os.path.join(temp_dir, "outputs-native-footer:run-1")
            expected_base_1 = os.path.join(temp_dir, "outputs-native-footer:base-1")

            self.assertEqual(run_1, expected_run_1)
            self.assertEqual(base_1, expected_base_1)

            # Scenario B: base_1 exists on disk -> bump to -2 for both
            os.makedirs(base_1)
            run_2, base_2 = ArchiveEngine.resolvePairTargetDirectories(temp_dir, arm_id)

            expected_run_2 = os.path.join(temp_dir, "outputs-native-footer:run-2")
            expected_base_2 = os.path.join(temp_dir, "outputs-native-footer:base-2")

            self.assertEqual(run_2, expected_run_2)
            self.assertEqual(base_2, expected_base_2)

    def testExecutePairedArchiveAtomicExecution(self) -> None:
        """Asserts executePairedArchive moves run output, replicates baseline, and returns string tuple."""
        with tempfile.TemporaryDirectory() as temp_root:
            run_source = os.path.join(temp_root, "outputs_run")
            base_source = os.path.join(temp_root, "outputs_base")
            dest_root = os.path.join(temp_root, "archive")

            os.makedirs(run_source)
            os.makedirs(base_source)

            with open(os.path.join(run_source, "run.log"), "w") as f:
                f.write("variant run output")
            with open(os.path.join(base_source, "base.log"), "w") as f:
                f.write("baseline output")

            target_run, target_base = ArchiveEngine.executePairedArchive(
                f_run_source_dir=run_source,
                f_base_source_dir=base_source,
                f_dest_root=dest_root,
                f_arm_id="native-footer",
            )

            # Check return types
            self.assertIsInstance(target_run, str)
            self.assertIsInstance(target_base, str)

            # Check target files exist
            self.assertTrue(os.path.isfile(os.path.join(target_run, "run.log")))
            self.assertTrue(os.path.isfile(os.path.join(target_base, "base.log")))

            # Verify active run source directory was recreated cleanly
            self.assertTrue(os.path.isdir(run_source))
            self.assertEqual(os.listdir(run_source), [])

            # Verify base source directory was copied (remains intact)
            self.assertTrue(os.path.isdir(base_source))
            self.assertTrue(os.path.isfile(os.path.join(base_source, "base.log")))

    def testReplicateArchive(self) -> None:
        """Asserts replicateArchive creates destination copy without modifying source."""
        with tempfile.TemporaryDirectory() as temp_root:
            source_dir = os.path.join(temp_root, "staging")
            dest_root = os.path.join(temp_root, "dest")
            os.makedirs(source_dir)

            with open(os.path.join(source_dir, "meta.txt"), "w") as f:
                f.write("staged content")

            target = ArchiveEngine.replicateArchive(
                f_source_dir=source_dir,
                f_dest_root=dest_root,
                f_arm_id="native-footer",
                f_role="base",
            )

            self.assertIsInstance(target, str)
            self.assertTrue(os.path.isfile(os.path.join(target, "meta.txt")))
            self.assertTrue(os.path.isfile(os.path.join(source_dir, "meta.txt")))

    def testInvalidInputsRaiseArchiveError(self) -> None:
        """Asserts that invalid inputs or non-existent directories raise ArchiveError."""
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ArchiveError):
                ArchiveEngine.resolvePairTargetDirectories("", "native")
            with self.assertRaises(ArchiveError):
                ArchiveEngine.resolvePairTargetDirectories(temp_dir, "")

            with self.assertRaises(ArchiveError):
                ArchiveEngine.replicateArchive(
                    os.path.join(temp_dir, "nonexistent"),
                    temp_dir,
                    "native",
                )

    def testExecuteArchiveAutoReportGeneration(self) -> None:
        """Asserts executeArchive invokes LsmioAggOutput when benchmark logs exist and report is missing."""
        from unittest.mock import MagicMock, patch

        with tempfile.TemporaryDirectory() as temp_root:
            source_dir = os.path.join(temp_root, "outputs")
            dest_root = os.path.join(temp_root, "archive")
            log_dir = os.path.join(source_dir, "8", "2026-09-12")
            os.makedirs(log_dir)
            with open(os.path.join(log_dir, "out-native-4-1M-test.txt"), "w") as f:
                f.write("mock log")

            with patch("lsmiotool.lib.output.LsmioAggOutput") as mock_agg_cls:
                mock_agg = MagicMock()
                mock_agg_cls.return_value = mock_agg

                target = ArchiveEngine.executeArchive(
                    f_source_dir=source_dir,
                    f_dest_root=dest_root,
                    f_arm_id="native-footer",
                )

                mock_agg_cls.assert_called_once_with(os.path.abspath(source_dir), f_scale="variants")
                mock_agg.generateReports.assert_called_once_with(f_out_dir=os.path.abspath(source_dir))
                self.assertTrue(os.path.exists(target))

    def testVersionedArmIdPairResolution(self) -> None:
        """Validates that versioned arm IDs resolve to symmetrical :run and :base targets."""
        with tempfile.TemporaryDirectory() as temp_dir:
            arm_id = "native-version-main-a1b2c3d"
            run_tgt, base_tgt = ArchiveEngine.resolvePairTargetDirectories(temp_dir, arm_id)
            self.assertEqual(run_tgt, os.path.join(temp_dir, f"outputs-{arm_id}:run"))
            self.assertEqual(base_tgt, os.path.join(temp_dir, f"outputs-{arm_id}:base"))

    def testVersionedWithVariantArmIdPairResolution(self) -> None:
        """Validates that versioned arm IDs with variant suffix resolve symmetrically."""
        with tempfile.TemporaryDirectory() as temp_dir:
            arm_id = "native-version-tybulut-bugfixes-437400d-legacy"
            run_tgt, base_tgt = ArchiveEngine.resolvePairTargetDirectories(temp_dir, arm_id)
            self.assertEqual(run_tgt, os.path.join(temp_dir, f"outputs-{arm_id}:run"))
            self.assertEqual(base_tgt, os.path.join(temp_dir, f"outputs-{arm_id}:base"))

    def testVersionedArmIdSynchronizedCollision(self) -> None:
        """Validates that pre-existing versioned directories advance both twins synchronously."""
        with tempfile.TemporaryDirectory() as temp_dir:
            arm_id = "native-version-main-a1b2c3d"
            run_0 = os.path.join(temp_dir, f"outputs-{arm_id}:run")
            os.makedirs(run_0)

            run_1, base_1 = ArchiveEngine.resolvePairTargetDirectories(temp_dir, arm_id)
            self.assertEqual(run_1, os.path.join(temp_dir, f"outputs-{arm_id}:run-1"))
            self.assertEqual(base_1, os.path.join(temp_dir, f"outputs-{arm_id}:base-1"))


if __name__ == "__main__":
    unittest.main()

