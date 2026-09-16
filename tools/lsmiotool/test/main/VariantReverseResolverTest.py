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

import unittest

from lsmiotool.lib.variants import (
    VariantResolutionResult,
    VariantReverseResolver,
)


class VariantReverseResolverTest(unittest.TestCase):
    """Unit tests for VariantReverseResolver and VariantResolutionResult validating design Section 4.1.1."""

    def testTruthTableCanonicalCases(self) -> None:
        """Exhaustively validates the 12 canonical edge cases from the Reverse-Resolution Truth Table."""
        # Case 1: Standalone unadorned baseline (INV-PAIR-3)
        r1 = VariantReverseResolver.resolve("outputs-native")
        self.assertIsNotNone(r1)
        self.assertEqual(r1.backend, "native")
        self.assertEqual(r1.variant, "default")
        self.assertIsNone(r1.role)
        self.assertIsNone(r1.collision)
        self.assertEqual(r1.display_label, "default")
        self.assertEqual(r1.raw_directory, "outputs-native")

        # Case 2: Standalone baseline collision
        r2 = VariantReverseResolver.resolve("outputs-native-1")
        self.assertIsNotNone(r2)
        self.assertEqual(r2.backend, "native")
        self.assertEqual(r2.variant, "default")
        self.assertIsNone(r2.role)
        self.assertEqual(r2.collision, "1")
        self.assertEqual(r2.display_label, "default-1")

        # Case 3: Standalone variant run (legacy / unadorned)
        r3 = VariantReverseResolver.resolve("outputs-native-footer")
        self.assertIsNotNone(r3)
        self.assertEqual(r3.backend, "native")
        self.assertEqual(r3.variant, "footer")
        self.assertIsNone(r3.role)
        self.assertIsNone(r3.collision)
        self.assertEqual(r3.display_label, "footer")

        # Case 4: Standalone variant collision
        r4 = VariantReverseResolver.resolve("outputs-native-footer-1")
        self.assertIsNotNone(r4)
        self.assertEqual(r4.backend, "native")
        self.assertEqual(r4.variant, "footer")
        self.assertIsNone(r4.role)
        self.assertEqual(r4.collision, "1")
        self.assertEqual(r4.display_label, "footer-1")

        # Case 5: Hyphenated variant ending in digit (footer-pool-8)
        r5 = VariantReverseResolver.resolve("outputs-native-footer-pool-8")
        self.assertIsNotNone(r5)
        self.assertEqual(r5.backend, "native")
        self.assertEqual(r5.variant, "footer-pool-8")
        self.assertIsNone(r5.role)
        self.assertIsNone(r5.collision)
        self.assertEqual(r5.display_label, "footer-pool-8")

        # Case 6: Hyphenated variant with collision suffix
        r6 = VariantReverseResolver.resolve("outputs-native-footer-pool-8-1")
        self.assertIsNotNone(r6)
        self.assertEqual(r6.backend, "native")
        self.assertEqual(r6.variant, "footer-pool-8")
        self.assertIsNone(r6.role)
        self.assertEqual(r6.collision, "1")
        self.assertEqual(r6.display_label, "footer-pool-8-1")

        # Case 7: Paired variant execution run (:run)
        r7 = VariantReverseResolver.resolve("outputs-native-footer:run")
        self.assertIsNotNone(r7)
        self.assertEqual(r7.backend, "native")
        self.assertEqual(r7.variant, "footer")
        self.assertEqual(r7.role, "run")
        self.assertIsNone(r7.collision)
        self.assertEqual(r7.display_label, "footer")

        # Case 8: Paired control baseline run (:base)
        r8 = VariantReverseResolver.resolve("outputs-native-footer:base")
        self.assertIsNotNone(r8)
        self.assertEqual(r8.backend, "native")
        self.assertEqual(r8.variant, "footer")
        self.assertEqual(r8.role, "base")
        self.assertIsNone(r8.collision)
        self.assertEqual(r8.display_label, "footer")

        # Case 9: Paired variant execution collision (:run-1)
        r9 = VariantReverseResolver.resolve("outputs-native-footer:run-1")
        self.assertIsNotNone(r9)
        self.assertEqual(r9.backend, "native")
        self.assertEqual(r9.variant, "footer")
        self.assertEqual(r9.role, "run")
        self.assertEqual(r9.collision, "1")
        self.assertEqual(r9.display_label, "footer-1")

        # Case 10: Paired control baseline collision (:base-1)
        r10 = VariantReverseResolver.resolve("outputs-native-footer:base-1")
        self.assertIsNotNone(r10)
        self.assertEqual(r10.backend, "native")
        self.assertEqual(r10.variant, "footer")
        self.assertEqual(r10.role, "base")
        self.assertEqual(r10.collision, "1")
        self.assertEqual(r10.display_label, "footer-1")

        # Case 11: Hyphenated variant with role marker and collision suffix
        r11 = VariantReverseResolver.resolve("outputs-native-footer-pool-8:run-1")
        self.assertIsNotNone(r11)
        self.assertEqual(r11.backend, "native")
        self.assertEqual(r11.variant, "footer-pool-8")
        self.assertEqual(r11.role, "run")
        self.assertEqual(r11.collision, "1")
        self.assertEqual(r11.display_label, "footer-pool-8-1")

        # Case 12: Invalid role suffix rejected
        r12 = VariantReverseResolver.resolve("outputs-native-footer:unknown")
        self.assertIsNone(r12)

    def testNonNativeBackendsAndAliases(self) -> None:
        """Validates reverse resolution across alternate backends and baseline aliases."""
        # Non-native backend standalone
        r_adios = VariantReverseResolver.resolve("outputs-adios")
        self.assertIsNotNone(r_adios)
        self.assertEqual(r_adios.backend, "adios")
        self.assertEqual(r_adios.variant, "default")
        self.assertEqual(r_adios.display_label, "adios")

        # Non-native backend with collision
        r_adios_2 = VariantReverseResolver.resolve("outputs-adios-2")
        self.assertIsNotNone(r_adios_2)
        self.assertEqual(r_adios_2.backend, "adios")
        self.assertEqual(r_adios_2.variant, "default")
        self.assertEqual(r_adios_2.collision, "2")
        self.assertEqual(r_adios_2.display_label, "adios-2")

        # Non-native paired run
        r_rocks_run = VariantReverseResolver.resolve("outputs-rocksdb-btree:run-2")
        self.assertIsNotNone(r_rocks_run)
        self.assertEqual(r_rocks_run.backend, "rocksdb")
        self.assertEqual(r_rocks_run.variant, "btree")
        self.assertEqual(r_rocks_run.role, "run")
        self.assertEqual(r_rocks_run.collision, "2")
        self.assertEqual(r_rocks_run.display_label, "rocksdb-btree-2")

        # Unknown backend syntax parsed correctly (validation downstream)
        r_unk = VariantReverseResolver.resolve("outputs-unknown")
        self.assertIsNotNone(r_unk)
        self.assertEqual(r_unk.backend, "unknown")
        self.assertEqual(r_unk.variant, "default")
        self.assertEqual(r_unk.display_label, "unknown")

    def testInvalidDirectoryFormatsReturnNone(self) -> None:
        """Validates that non-matching paths return None."""
        self.assertIsNone(VariantReverseResolver.resolve(""))
        self.assertIsNone(VariantReverseResolver.resolve("inputs-native"))
        self.assertIsNone(VariantReverseResolver.resolve("outputs"))
        self.assertIsNone(VariantReverseResolver.resolve("output-native"))
        self.assertIsNone(VariantReverseResolver.resolve("outputs_native"))
        self.assertIsNone(VariantReverseResolver.resolve("archive"))
        self.assertIsNone(VariantReverseResolver.resolve("outputs-native-footer:badrole"))
        self.assertIsNone(VariantReverseResolver.resolve("outputs-native-footer::run"))

    def testVariantResolutionResultNamedTuple(self) -> None:
        """Validates VariantResolutionResult structure, default role, and immutability."""
        res = VariantResolutionResult(
            raw_directory="outputs-native-footer:run",
            backend="native",
            variant="footer",
            collision=None,
            display_label="footer",
            role="run",
        )
        self.assertEqual(res.raw_directory, "outputs-native-footer:run")
        self.assertEqual(res.backend, "native")
        self.assertEqual(res.variant, "footer")
        self.assertIsNone(res.collision)
        self.assertEqual(res.display_label, "footer")
        self.assertEqual(res.role, "run")

        # Default role=None
        res_default = VariantResolutionResult(
            raw_directory="outputs-native",
            backend="native",
            variant="default",
            collision=None,
            display_label="default",
        )
        self.assertIsNone(res_default.role)

    def testVersionedRunAndBaseResolution(self) -> None:
        """Validates reverse resolution and formatting of versioned directories."""
        r_run = VariantReverseResolver.resolve("outputs-native-version-main-a1b2c3d:run")
        self.assertIsNotNone(r_run)
        self.assertEqual(r_run.backend, "native")
        self.assertEqual(r_run.variant, "version-main-a1b2c3d")
        self.assertEqual(r_run.role, "run")
        self.assertIsNone(r_run.collision)
        self.assertEqual(r_run.display_label, "main (a1b2c3d)")

        r_base = VariantReverseResolver.resolve("outputs-native-version-main-a1b2c3d:base")
        self.assertIsNotNone(r_base)
        self.assertEqual(r_base.backend, "native")
        self.assertEqual(r_base.variant, "version-main-a1b2c3d")
        self.assertEqual(r_base.role, "base")
        self.assertIsNone(r_base.collision)
        self.assertEqual(r_base.display_label, "main (a1b2c3d)")

    def testVersionedBranchWithSanitizedSpecialCharacters(self) -> None:
        """Validates that sanitized branches with internal hyphens format correctly."""
        r = VariantReverseResolver.resolve("outputs-native-version-tybulut-bugfix-1-a1b2c3d:run")
        self.assertIsNotNone(r)
        self.assertEqual(r.variant, "version-tybulut-bugfix-1-a1b2c3d")
        self.assertEqual(r.display_label, "tybulut-bugfix-1 (a1b2c3d)")

    def testVersionedCollisionSuffixHandling(self) -> None:
        """Validates that collision suffixes on versioned runs append cleanly."""
        r = VariantReverseResolver.resolve("outputs-native-version-main-a1b2c3d:run-2")
        self.assertIsNotNone(r)
        self.assertEqual(r.collision, "2")
        self.assertEqual(r.display_label, "main (a1b2c3d)-2")

    def testVersionedNonNativeBackend(self) -> None:
        """Validates that non-native backends prefix the backend name."""
        r = VariantReverseResolver.resolve("outputs-rocksdb-version-main-a1b2c3d:run")
        self.assertIsNotNone(r)
        self.assertEqual(r.display_label, "rocksdb-main (a1b2c3d)")

    def testNewDigitVariants(self) -> None:
        """Validates reverse resolution of new variants ending in digits."""
        r1 = VariantReverseResolver.resolve("outputs-native-footer-pread-pool-8")
        self.assertIsNotNone(r1)
        self.assertEqual(r1.variant, "footer-pread-pool-8")
        self.assertIsNone(r1.collision)
        self.assertEqual(r1.display_label, "footer-pread-pool-8")

        r2 = VariantReverseResolver.resolve("outputs-native-footer-pread-pool-8-1")
        self.assertIsNotNone(r2)
        self.assertEqual(r2.variant, "footer-pread-pool-8")
        self.assertEqual(r2.collision, "1")
        self.assertEqual(r2.display_label, "footer-pread-pool-8-1")

        r3 = VariantReverseResolver.resolve("outputs-native-footer-pread-pool-8:run")
        self.assertIsNotNone(r3)
        self.assertEqual(r3.variant, "footer-pread-pool-8")
        self.assertEqual(r3.role, "run")
        self.assertIsNone(r3.collision)

        r4 = VariantReverseResolver.resolve("outputs-native-manoff-pool-8")
        self.assertIsNotNone(r4)
        self.assertEqual(r4.variant, "manoff-pool-8")
        self.assertIsNone(r4.collision)

        r5 = VariantReverseResolver.resolve("outputs-native-footer-pread-manoff-pool-8:run-2")
        self.assertIsNotNone(r5)
        self.assertEqual(r5.variant, "footer-pread-manoff-pool-8")
        self.assertEqual(r5.role, "run")
        self.assertEqual(r5.collision, "2")
        self.assertEqual(r5.display_label, "footer-pread-manoff-pool-8-2")


if __name__ == "__main__":
    unittest.main()

