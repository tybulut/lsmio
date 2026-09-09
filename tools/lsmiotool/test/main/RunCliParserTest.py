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

from lsmiotool.lib.cli import (
    CliParseError,
    RunCliParseError,
    RunCliParser,
    parseRunArguments,
)
from lsmiotool.lib.run import RunRequest
from lsmiotool.lib.site import StorageClass
from lsmiotool.lib.variants import UnknownVariantError


class RunCliParserTest(unittest.TestCase):
    """Unit tests for pure approved run CLI parser and exceptions."""

    def testCanonicalAndGlobalSsdEqual(self) -> None:
        """Validates that global --ssd before run and trailing --ssd produce identical RunRequest objects."""
        # 1. Trailing --ssd without leading 'run'
        f_req1 = parseRunArguments(["ior", "local", "--ssd"])
        # 2. Trailing --ssd with leading 'run'
        f_req2 = parseRunArguments(["run", "ior", "local", "--ssd"])
        # 3. Global --ssd before 'run'
        f_req3 = parseRunArguments(["--ssd", "run", "ior", "local"])
        # 4. f_global_ssd=True flag
        f_req4 = parseRunArguments(["ior", "local"], f_global_ssd=True)
        # 5. Direct RunCliParser.parse call
        f_req5 = RunCliParser.parse(["ior", "local", "--ssd"])

        f_expected = RunRequest(
            f_target="ior",
            f_scale="local",
            f_ssd=True,
            f_setup=None,
        )

        self.assertEqual(f_req1, f_expected)
        self.assertEqual(f_req2, f_expected)
        self.assertEqual(f_req3, f_expected)
        self.assertEqual(f_req4, f_expected)
        self.assertEqual(f_req5, f_expected)

        # All requests must have SSD storage class
        self.assertTrue(f_req1.ssd)
        self.assertTrue(f_req1.is_ssd)
        self.assertEqual(f_req1.storage, StorageClass.SSD)

    def testHddDefaultsAndSetups(self) -> None:
        """Validates default HDD storage class and custom setup values across targets."""
        # IOR with default HDD and custom setup
        f_req_ior = parseRunArguments(["ior", "small", "--setup", "hdf5"])
        self.assertFalse(f_req_ior.ssd)
        self.assertFalse(f_req_ior.is_ssd)
        self.assertEqual(f_req_ior.storage, StorageClass.HDD)
        self.assertEqual(f_req_ior.target, "ior")
        self.assertEqual(f_req_ior.scale, "small")
        self.assertEqual(f_req_ior.setup, "HDF5")

        # LSMIO with default HDD and custom setup
        f_req_lsmio = parseRunArguments(["lsmio", "bake", "--setup", "native-m"])
        self.assertFalse(f_req_lsmio.ssd)
        self.assertEqual(f_req_lsmio.storage, StorageClass.HDD)
        self.assertEqual(f_req_lsmio.target, "lsmio")
        self.assertEqual(f_req_lsmio.scale, "bake")
        self.assertEqual(f_req_lsmio.setup, "NATIVE-M")

        # LMP with default HDD and custom setup
        f_req_lmp = parseRunArguments(["lmp", "local", "--setup", "fs"])
        self.assertFalse(f_req_lmp.ssd)
        self.assertEqual(f_req_lmp.storage, StorageClass.HDD)
        self.assertEqual(f_req_lmp.target, "lmp")
        self.assertEqual(f_req_lmp.scale, "local")
        self.assertEqual(f_req_lmp.setup, "FS")

        # Plain HDD invocation with no setup
        f_req_plain = parseRunArguments(["ior", "large"])
        self.assertFalse(f_req_plain.ssd)
        self.assertEqual(f_req_plain.storage, StorageClass.HDD)
        self.assertIsNone(f_req_plain.setup)

    def testTrailingOptionOrders(self) -> None:
        """Validates trailing options in both orders (--ssd --setup <name> and --setup <name> --ssd)."""
        # Order 1: --ssd then --setup <name>
        f_req_order1 = parseRunArguments(
            ["ior", "small", "--ssd", "--setup", "collective"]
        )
        # Order 2: --setup <name> then --ssd
        f_req_order2 = parseRunArguments(
            ["ior", "small", "--setup", "collective", "--ssd"]
        )
        # With leading 'run'
        f_req_order3 = parseRunArguments(
            ["run", "ior", "small", "--ssd", "--setup", "collective"]
        )
        f_req_order4 = parseRunArguments(
            ["run", "ior", "small", "--setup", "collective", "--ssd"]
        )

        f_expected = RunRequest(
            f_target="ior",
            f_scale="small",
            f_ssd=True,
            f_setup="COLLECTIVE",
        )

        self.assertEqual(f_req_order1, f_expected)
        self.assertEqual(f_req_order2, f_expected)
        self.assertEqual(f_req_order3, f_expected)
        self.assertEqual(f_req_order4, f_expected)

    def testSetupEqualsAlwaysRejected(self) -> None:
        """Asserts --setup=<val> syntax is rejected with RunCliParseError."""
        f_rejected_argvs = [
            ["ior", "local", "--setup=BASE"],
            ["ior", "local", "--setup="],
            ["run", "ior", "local", "--setup=BASE"],
            ["--setup=BASE", "run", "ior", "local"],
            ["run", "--setup=BASE", "ior", "local"],
            ["run", "ior", "--setup=BASE", "local"],
            ["ior", "--setup=BASE", "local"],
            ["ior", "local", "--ssd", "--setup=BASE"],
            ["ior", "local", "--setup=BASE", "--ssd"],
        ]

        for f_argv in f_rejected_argvs:
            with self.assertRaises(RunCliParseError, msg=f"Failed to reject: {f_argv}"):
                parseRunArguments(f_argv)
            with self.assertRaises(CliParseError):
                parseRunArguments(f_argv)

    def testSetupOutsideOrMisplacedRejected(self) -> None:
        """Asserts --setup between positionals or before run is rejected."""
        f_misplaced_argvs = [
            # Before 'run'
            ["--setup", "BASE", "run", "ior", "local"],
            # Between 'run' and benchmark
            ["run", "--setup", "BASE", "ior", "local"],
            # Between benchmark and scale
            ["run", "ior", "--setup", "BASE", "local"],
            ["ior", "--setup", "BASE", "local"],
            # Before benchmark without 'run'
            ["--setup", "BASE", "ior", "local"],
            # Misplaced --ssd between positionals
            ["run", "ior", "--ssd", "local"],
            ["ior", "--ssd", "local"],
            # Misplaced --ssd before positionals
            ["--ssd", "ior", "local"],
            ["run", "--ssd", "ior", "local"],
        ]

        for f_argv in f_misplaced_argvs:
            with self.assertRaises(
                RunCliParseError, msg=f"Failed to reject misplaced: {f_argv}"
            ):
                parseRunArguments(f_argv)

    def testDuplicatesMissingUnknownExtraArity(self) -> None:
        """Asserts rejection of duplicate flags, missing arguments, unknown options, and extra arity."""
        # 1. Duplicate --ssd
        f_dup_ssd = [
            ["ior", "local", "--ssd", "--ssd"],
            ["run", "ior", "local", "--ssd", "--ssd"],
            ["--ssd", "--ssd", "run", "ior", "local"],
        ]
        for f_argv in f_dup_ssd:
            with self.assertRaises(
                RunCliParseError, msg=f"Failed to reject duplicate ssd: {f_argv}"
            ):
                parseRunArguments(f_argv)

        # Global SSD + trailing SSD
        with self.assertRaises(RunCliParseError):
            parseRunArguments(["ior", "local", "--ssd"], f_global_ssd=True)
        with self.assertRaises(RunCliParseError):
            parseRunArguments(["--ssd", "run", "ior", "local", "--ssd"])

        # 2. Duplicate --setup
        f_dup_setup = [
            ["ior", "local", "--setup", "BASE", "--setup", "HDF5"],
            ["run", "ior", "local", "--setup", "BASE", "--setup", "BASE"],
        ]
        for f_argv in f_dup_setup:
            with self.assertRaises(
                RunCliParseError, msg=f"Failed to reject duplicate setup: {f_argv}"
            ):
                parseRunArguments(f_argv)

        # 3. Missing arguments
        f_missing_args = [
            [],
            ["run"],
            ["ior"],
            ["run", "ior"],
        ]
        for f_argv in f_missing_args:
            with self.assertRaises(
                RunCliParseError, msg=f"Failed to reject missing args: {f_argv}"
            ):
                parseRunArguments(f_argv)

        # 4. Missing value after --setup
        f_missing_setup_val = [
            ["ior", "local", "--setup"],
            ["run", "ior", "local", "--setup"],
            ["ior", "local", "--setup", "--ssd"],
            ["run", "ior", "local", "--setup", "--ssd"],
            ["ior", "local", "--setup", ""],
            ["ior", "local", "--setup", "   "],
        ]
        for f_argv in f_missing_setup_val:
            with self.assertRaises(
                RunCliParseError, msg=f"Failed to reject missing setup value: {f_argv}"
            ):
                parseRunArguments(f_argv)

        # 5. Unknown options and flags
        f_unknown_opts = [
            ["ior", "local", "--foo"],
            ["ior", "local", "-x"],
            ["--unknown", "run", "ior", "local"],
            ["run", "ior", "local", "--bar", "baz"],
        ]
        for f_argv in f_unknown_opts:
            with self.assertRaises(
                RunCliParseError, msg=f"Failed to reject unknown option: {f_argv}"
            ):
                parseRunArguments(f_argv)

        # 6. Extra trailing positional arguments
        f_extra_pos = [
            ["ior", "local", "extra"],
            ["run", "ior", "local", "extra"],
            ["ior", "local", "--ssd", "extra"],
            ["ior", "local", "--setup", "BASE", "extra"],
        ]
        for f_argv in f_extra_pos:
            with self.assertRaises(
                RunCliParseError, msg=f"Failed to reject extra positional: {f_argv}"
            ):
                parseRunArguments(f_argv)

        # 7. Invalid benchmark and scale names
        with self.assertRaises(RunCliParseError):
            parseRunArguments(["invalid_bm", "local"])
        with self.assertRaises(RunCliParseError):
            parseRunArguments(["ior", "invalid_scale"])

        # 8. Invalid argument types
        with self.assertRaises(RunCliParseError):
            parseRunArguments(None)  # type: ignore
        with self.assertRaises(RunCliParseError):
            parseRunArguments("ior local")  # type: ignore
        with self.assertRaises(RunCliParseError):
            parseRunArguments(["ior", 123])  # type: ignore
        with self.assertRaises(RunCliParseError):
            parseRunArguments(["ior", "local"], f_global_ssd="not_bool")  # type: ignore

    def testCaseCanonicalization(self) -> None:
        """Asserts case canonicalization for target, scale, and setup."""
        f_req = parseRunArguments(["IOR", "LOCAL", "--setup", "hdf5", "--ssd"])
        self.assertEqual(f_req.target, "ior")
        self.assertEqual(f_req.scale, "local")
        self.assertEqual(f_req.setup, "HDF5")
        self.assertTrue(f_req.ssd)

        f_req2 = parseRunArguments(["LsMiO", "SmAlL", "--setup", "native-m"])
        self.assertEqual(f_req2.target, "lsmio")
        self.assertEqual(f_req2.scale, "small")
        self.assertEqual(f_req2.setup, "NATIVE-M")

        f_req3 = parseRunArguments(["LMP", "BAKE", "--setup", "lsmio-mmap"])
        self.assertEqual(f_req3.target, "lmp")
        self.assertEqual(f_req3.scale, "bake")
        self.assertEqual(f_req3.setup, "LSMIO-MMAP")

    def testInputListNotMutated(self) -> None:
        """Asserts that the passed input list is not modified (pure function)."""
        f_input = ["ior", "local", "--ssd", "--setup", "BASE"]
        f_input_copy = list(f_input)
        f_req = parseRunArguments(f_input)
        self.assertEqual(f_input, f_input_copy)
        self.assertEqual(f_req.target, "ior")
        self.assertEqual(f_req.scale, "local")
        self.assertTrue(f_req.ssd)
        self.assertEqual(f_req.setup, "BASE")

    def testBaselineScaleWithoutVariant(self) -> None:
        """Tasks 2.3.1: Asserts baseline scale parsing without variant key."""
        f_req = parseRunArguments(["lsmio", "baseline"])
        self.assertEqual(f_req.target, "lsmio")
        self.assertEqual(f_req.scale, "baseline")
        self.assertIsNone(f_req.variant)
        self.assertFalse(f_req.ssd)
        self.assertIsNone(f_req.setup)

        f_req_cmd = parseRunArguments(["run", "lsmio", "baseline"])
        self.assertEqual(f_req_cmd.target, "lsmio")
        self.assertEqual(f_req_cmd.scale, "baseline")
        self.assertIsNone(f_req_cmd.variant)

        f_req_ssd = parseRunArguments(["lsmio", "baseline", "--ssd"])
        self.assertEqual(f_req_ssd.target, "lsmio")
        self.assertEqual(f_req_ssd.scale, "baseline")
        self.assertIsNone(f_req_ssd.variant)
        self.assertTrue(f_req_ssd.ssd)

        f_req_setup = parseRunArguments(["lsmio", "baseline", "--setup", "native-m"])
        self.assertEqual(f_req_setup.target, "lsmio")
        self.assertEqual(f_req_setup.scale, "baseline")
        self.assertIsNone(f_req_setup.variant)
        self.assertEqual(f_req_setup.setup, "NATIVE-M")

    def testBaselineScaleWithVariant(self) -> None:
        """Tasks 2.3.2: Asserts baseline scale parsing with positional variant key."""
        f_req1 = parseRunArguments(["lsmio", "baseline", "footer-btree"])
        self.assertEqual(f_req1.target, "lsmio")
        self.assertEqual(f_req1.scale, "baseline")
        self.assertEqual(f_req1.variant, "footer-btree")
        self.assertFalse(f_req1.ssd)

        f_req2 = parseRunArguments(["run", "lsmio", "baseline", "footer"])
        self.assertEqual(f_req2.target, "lsmio")
        self.assertEqual(f_req2.scale, "baseline")
        self.assertEqual(f_req2.variant, "footer")

        f_req3 = parseRunArguments(["lsmio", "baseline", "wbuf-512m"])
        self.assertEqual(f_req3.target, "lsmio")
        self.assertEqual(f_req3.scale, "baseline")
        self.assertEqual(f_req3.variant, "wbuf-512m")

    def testBaselineScaleWithVariantAndOptions(self) -> None:
        """Tasks 2.3.2: Asserts baseline scale with variant followed by options."""
        f_req = parseRunArguments(
            ["lsmio", "baseline", "wbuf-512m", "--ssd", "--setup", "NATIVE-M"]
        )
        self.assertEqual(f_req.target, "lsmio")
        self.assertEqual(f_req.scale, "baseline")
        self.assertEqual(f_req.variant, "wbuf-512m")
        self.assertTrue(f_req.ssd)
        self.assertEqual(f_req.setup, "NATIVE-M")

        f_req2 = parseRunArguments(
            ["--ssd", "run", "lsmio", "baseline", "footer-prealloc", "--setup", "ROCKSDB-M"]
        )
        self.assertEqual(f_req2.target, "lsmio")
        self.assertEqual(f_req2.scale, "baseline")
        self.assertEqual(f_req2.variant, "footer-prealloc")
        self.assertTrue(f_req2.ssd)
        self.assertEqual(f_req2.setup, "ROCKSDB-M")

    def testBaselineDefaultAndBaseVariantsCanonicalized(self) -> None:
        """Tasks 2.3.2: Asserts default and base variant tokens canonicalize to None."""
        f_req_default = parseRunArguments(["lsmio", "baseline", "default"])
        self.assertIsNone(f_req_default.variant)

        f_req_base = parseRunArguments(["lsmio", "baseline", "base"])
        self.assertIsNone(f_req_base.variant)

        f_req_native_base = parseRunArguments(["lsmio", "baseline", "native-m-base"])
        self.assertIsNone(f_req_native_base.variant)

    def testBaselineUnknownVariantFailFast(self) -> None:
        """Tasks 2.3.3: Asserts unrecognized variant keys fail fast raising UnknownVariantError."""
        with self.assertRaises(UnknownVariantError) as f_ctx:
            parseRunArguments(["lsmio", "baseline", "invalid_variant"])
        self.assertIsInstance(f_ctx.exception, CliParseError)
        self.assertEqual(f_ctx.exception.variant, "invalid_variant")

        with self.assertRaises(UnknownVariantError):
            parseRunArguments(["lsmio", "baseline", "footer-unknown"])

    def testNonBaselinePositionalVariantRejected(self) -> None:
        """Tasks 2.3.4 (INV-ARCH-2): Asserts positional variants for legacy scales are strictly rejected."""
        for f_scale in ("local", "bake", "small", "large"):
            with self.assertRaises(RunCliParseError) as f_ctx:
                parseRunArguments(["lsmio", f_scale, "footer"])
            self.assertIn("Unexpected extra positional argument", str(f_ctx.exception))

    def testNonLsmioBenchmarkVariantRejected(self) -> None:
        """Tasks 2.3.5 (INV-ARCH-3): Asserts positional variants on non-lsmio benchmarks are strictly rejected."""
        with self.assertRaises(RunCliParseError) as f_ctx_ior:
            parseRunArguments(["ior", "baseline", "footer"])
        self.assertIn("variants are supported exclusively for 'lsmio'", str(f_ctx_ior.exception))

        with self.assertRaises(RunCliParseError) as f_ctx_lmp:
            parseRunArguments(["lmp", "baseline", "footer"])
        self.assertIn("variants are supported exclusively for 'lsmio'", str(f_ctx_lmp.exception))

    def testBaselineIorAndLmpAllowedWithoutVariant(self) -> None:
        """Tasks 2.3.5: Asserts baseline scale is accepted for IOR and LMP when variant is omitted."""
        f_req_ior = parseRunArguments(["ior", "baseline", "--ssd"])
        self.assertEqual(f_req_ior.target, "ior")
        self.assertEqual(f_req_ior.scale, "baseline")
        self.assertIsNone(f_req_ior.variant)
        self.assertTrue(f_req_ior.ssd)

        f_req_lmp = parseRunArguments(["lmp", "baseline", "--setup", "LSMIO"])
        self.assertEqual(f_req_lmp.target, "lmp")
        self.assertEqual(f_req_lmp.scale, "baseline")
        self.assertIsNone(f_req_lmp.variant)
        self.assertEqual(f_req_lmp.setup, "LSMIO")

