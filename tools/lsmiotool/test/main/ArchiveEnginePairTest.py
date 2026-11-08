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
            run_target, base_target = ArchiveEngine.resolvePairTargetDirectories(
                temp_dir, arm_id
            )

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

    def testInvalidInputsRaiseArchiveError(self) -> None:
        """Asserts that invalid inputs raise ArchiveError."""
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ArchiveError):
                ArchiveEngine.resolvePairTargetDirectories("", "native")
            with self.assertRaises(ArchiveError):
                ArchiveEngine.resolvePairTargetDirectories(temp_dir, "")

    def testVersionedArmIdPairResolution(self) -> None:
        """Validates that versioned arm IDs resolve to symmetrical :run and :base targets."""
        with tempfile.TemporaryDirectory() as temp_dir:
            arm_id = "native-version-main-a1b2c3d"
            run_tgt, base_tgt = ArchiveEngine.resolvePairTargetDirectories(
                temp_dir, arm_id
            )
            self.assertEqual(run_tgt, os.path.join(temp_dir, f"outputs-{arm_id}:run"))
            self.assertEqual(base_tgt, os.path.join(temp_dir, f"outputs-{arm_id}:base"))

    def testVersionedWithVariantArmIdPairResolution(self) -> None:
        """Validates that versioned arm IDs with variant suffix resolve symmetrically."""
        with tempfile.TemporaryDirectory() as temp_dir:
            arm_id = "native-version-tybulut-bugfixes-437400d-legacy"
            run_tgt, base_tgt = ArchiveEngine.resolvePairTargetDirectories(
                temp_dir, arm_id
            )
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
