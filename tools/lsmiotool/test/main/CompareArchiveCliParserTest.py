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
    CompareArchiveCliParseError,
    CompareArchiveCliParser,
    CompareArchiveRequest,
    parseCompareArchiveArguments,
)
from lsmiotool.lib.variants import (
    VariantResolutionResult,
    VariantReverseResolver,
)


class CompareArchiveCliParserTest(unittest.TestCase):
    """Unit tests for CompareArchiveRequest, CompareArchiveCliParser, and VariantReverseResolver."""

    def testRequestValueObjectImmutability(self) -> None:
        """Validates CompareArchiveRequest construction, properties, immutability, and hashing."""
        req = CompareArchiveRequest(
            f_archive_folder="/path/to/archive",
            f_op="read",
            f_stripes=16,
            f_blocksize="8M",
            f_all=True,
            f_output_dir="/tmp/charts",
        )

        # Property access (both snake_case and camelCase)
        self.assertEqual(req.archive_folder, "/path/to/archive")
        self.assertEqual(req.archiveFolder, "/path/to/archive")
        self.assertEqual(req.op, "read")
        self.assertEqual(req.stripes, 16)
        self.assertEqual(req.blocksize, "8M")
        self.assertTrue(req.all)
        self.assertEqual(req.output_dir, "/tmp/charts")
        self.assertEqual(req.outputDir, "/tmp/charts")

        # Default values
        req_default = CompareArchiveRequest(f_archive_folder="/path/to/archive")
        self.assertEqual(req_default.archive_folder, "/path/to/archive")
        self.assertEqual(req_default.op, "both")
        self.assertEqual(req_default.stripes, 4)
        self.assertEqual(req_default.blocksize, "1M")
        self.assertFalse(req_default.all)
        self.assertIsNone(req_default.output_dir)

        # Immutability guards
        with self.assertRaises(AttributeError):
            req.m_op = "write"  # type: ignore
        with self.assertRaises(AttributeError):
            req.op = "write"  # type: ignore
        with self.assertRaises(AttributeError):
            req.m_stripes = 4  # type: ignore
        with self.assertRaises(AttributeError):
            del req.m_stripes  # type: ignore
        with self.assertRaises(AttributeError):
            del req.stripes  # type: ignore

        # toDict serialization
        expected_dict = {
            "archive_folder": "/path/to/archive",
            "op": "read",
            "stripes": 16,
            "blocksize": "8M",
            "all": True,
            "output_dir": "/tmp/charts",
        }
        self.assertEqual(req.toDict(), expected_dict)

        # __repr__
        self.assertIn("CompareArchiveRequest(", repr(req))
        self.assertIn("archive_folder='/path/to/archive'", repr(req))
        self.assertIn("op='read'", repr(req))
        self.assertIn("stripes=16", repr(req))
        self.assertIn("blocksize='8M'", repr(req))
        self.assertIn("all=True", repr(req))
        self.assertIn("output_dir='/tmp/charts'", repr(req))

        # __eq__ and __hash__
        req_same = CompareArchiveRequest(
            f_archive_folder="/path/to/archive",
            f_op="READ",
            f_stripes=16,
            f_blocksize="8m",
            f_all=True,
            f_output_dir="/tmp/charts",
        )
        self.assertEqual(req, req_same)
        self.assertEqual(hash(req), hash(req_same))
        self.assertNotEqual(req, req_default)
        self.assertFalse(req == "non_request_object")
        self.assertFalse(req == 123)

        req_set = {req, req_same, req_default}
        self.assertEqual(len(req_set), 2)

        # Constructor validation errors
        with self.assertRaises(ValueError):
            CompareArchiveRequest(f_archive_folder="")
        with self.assertRaises(ValueError):
            CompareArchiveRequest(f_archive_folder="   ")
        with self.assertRaises(ValueError):
            CompareArchiveRequest(f_archive_folder=None)  # type: ignore
        with self.assertRaises(ValueError):
            CompareArchiveRequest(f_archive_folder="/path", f_op="delete")
        with self.assertRaises(ValueError):
            CompareArchiveRequest(f_archive_folder="/path", f_op="")
        with self.assertRaises(ValueError):
            CompareArchiveRequest(f_archive_folder="/path", f_stripes=8)
        with self.assertRaises(ValueError):
            CompareArchiveRequest(f_archive_folder="/path", f_stripes=True)  # type: ignore
        with self.assertRaises(ValueError):
            CompareArchiveRequest(f_archive_folder="/path", f_blocksize="2M")
        with self.assertRaises(ValueError):
            CompareArchiveRequest(f_archive_folder="/path", f_blocksize="")
        with self.assertRaises(ValueError):
            CompareArchiveRequest(f_archive_folder="/path", f_all="yes")  # type: ignore
        with self.assertRaises(ValueError):
            CompareArchiveRequest(f_archive_folder="/path", f_output_dir="")
        with self.assertRaises(ValueError):
            CompareArchiveRequest(f_archive_folder="/path", f_output_dir="   ")

    def testValidPositionalArguments(self) -> None:
        """Validates positional argument parsing for archive folder, operation, stripes, and blocksize."""
        # Minimal positional: archive folder only
        req1 = parseCompareArchiveArguments(["/path/to/archive"])
        self.assertEqual(req1.archive_folder, "/path/to/archive")
        self.assertEqual(req1.op, "both")
        self.assertEqual(req1.stripes, 4)
        self.assertEqual(req1.blocksize, "1M")
        self.assertFalse(req1.all)
        self.assertIsNone(req1.output_dir)

        # Leading subcommand token
        req1_sub = parseCompareArchiveArguments(["compare-archive", "/path/to/archive"])
        self.assertEqual(req1_sub, req1)

        # Direct parser call
        req1_direct = CompareArchiveCliParser.parse(["/path/to/archive"])
        self.assertEqual(req1_direct, req1)

        # Positional operation: read, write, both (case-insensitive)
        req_read = parseCompareArchiveArguments(["/path/to/archive", "read"])
        self.assertEqual(req_read.op, "read")
        self.assertEqual(req_read.stripes, 4)
        self.assertEqual(req_read.blocksize, "1M")

        req_write = parseCompareArchiveArguments(["/path/to/archive", "WRITE"])
        self.assertEqual(req_write.op, "write")

        req_both = parseCompareArchiveArguments(["/path/to/archive", "both"])
        self.assertEqual(req_both.op, "both")

        # Positional stripes: 4, 16
        req_stripes = parseCompareArchiveArguments(["/path/to/archive", "read", "16"])
        self.assertEqual(req_stripes.op, "read")
        self.assertEqual(req_stripes.stripes, 16)
        self.assertEqual(req_stripes.blocksize, "1M")

        # Positional blocksize: 64K, 1M, 8M (case-insensitive)
        req_bs1 = parseCompareArchiveArguments(
            ["/path/to/archive", "read", "4", "64K"]
        )
        self.assertEqual(req_bs1.blocksize, "64K")

        req_bs2 = parseCompareArchiveArguments(
            ["/path/to/archive", "both", "16", "8m"]
        )
        self.assertEqual(req_bs2.blocksize, "8M")
        self.assertEqual(req_bs2.stripes, 16)
        self.assertEqual(req_bs2.op, "both")

    def testValidOptionsPermutations(self) -> None:
        """Validates options parsing (--all, --output-dir) across permutations and ordering."""
        # --all flag alone
        req_all = parseCompareArchiveArguments(["/path/to/archive", "--all"])
        self.assertTrue(req_all.all)
        self.assertEqual(req_all.op, "both")
        self.assertEqual(req_all.stripes, 4)
        self.assertEqual(req_all.blocksize, "1M")
        self.assertIsNone(req_all.output_dir)

        # --output-dir option alone
        req_out = parseCompareArchiveArguments(
            ["/path/to/archive", "--output-dir", "/tmp/charts"]
        )
        self.assertEqual(req_out.output_dir, "/tmp/charts")
        self.assertEqual(req_out.outputDir, "/tmp/charts")
        self.assertFalse(req_out.all)

        # All positionals + --all + --output-dir
        req_full = parseCompareArchiveArguments([
            "/path/to/archive",
            "read",
            "16",
            "8M",
            "--all",
            "--output-dir",
            "/tmp/charts",
        ])
        self.assertEqual(req_full.archive_folder, "/path/to/archive")
        self.assertEqual(req_full.op, "read")
        self.assertEqual(req_full.stripes, 16)
        self.assertEqual(req_full.blocksize, "8M")
        self.assertTrue(req_full.all)
        self.assertEqual(req_full.output_dir, "/tmp/charts")

        # Inverted options order: --output-dir before --all
        req_inv = parseCompareArchiveArguments([
            "/path/to/archive",
            "--output-dir",
            "/tmp/charts",
            "--all",
        ])
        self.assertTrue(req_inv.all)
        self.assertEqual(req_inv.output_dir, "/tmp/charts")

    def testCliParseErrors(self) -> None:
        """Asserts that invalid CLI syntax, missing args, unknown flags, and invalid values raise CompareArchiveCliParseError."""
        # Empty args or missing archive folder
        with self.assertRaises(CompareArchiveCliParseError):
            parseCompareArchiveArguments([])
        with self.assertRaises(CompareArchiveCliParseError):
            parseCompareArchiveArguments(["compare-archive"])

        # Options placed before archive folder
        with self.assertRaises(CompareArchiveCliParseError):
            parseCompareArchiveArguments(["--all", "/path/to/archive"])
        with self.assertRaises(CompareArchiveCliParseError):
            parseCompareArchiveArguments([
                "--output-dir",
                "/tmp",
                "/path/to/archive",
            ])

        # Invalid operation
        with self.assertRaises(CompareArchiveCliParseError):
            parseCompareArchiveArguments(["/path/to/archive", "delete"])
        with self.assertRaises(CompareArchiveCliParseError):
            parseCompareArchiveArguments(["/path/to/archive", "run"])

        # Invalid stripes
        with self.assertRaises(CompareArchiveCliParseError):
            parseCompareArchiveArguments(["/path/to/archive", "read", "8"])
        with self.assertRaises(CompareArchiveCliParseError):
            parseCompareArchiveArguments(["/path/to/archive", "read", "abc"])

        # Invalid blocksize
        with self.assertRaises(CompareArchiveCliParseError):
            parseCompareArchiveArguments(["/path/to/archive", "read", "4", "2M"])
        with self.assertRaises(CompareArchiveCliParseError):
            parseCompareArchiveArguments(["/path/to/archive", "read", "4", "512K"])

        # Prohibited --all=val and --output-dir=val syntax
        with self.assertRaises(CompareArchiveCliParseError):
            parseCompareArchiveArguments(["/path/to/archive", "--all=true"])
        with self.assertRaises(CompareArchiveCliParseError):
            parseCompareArchiveArguments([
                "/path/to/archive",
                "--output-dir=/tmp/charts",
            ])

        # Missing or option-like value after --output-dir
        with self.assertRaises(CompareArchiveCliParseError):
            parseCompareArchiveArguments(["/path/to/archive", "--output-dir"])
        with self.assertRaises(CompareArchiveCliParseError):
            parseCompareArchiveArguments([
                "/path/to/archive",
                "--output-dir",
                "--all",
            ])
        with self.assertRaises(CompareArchiveCliParseError):
            parseCompareArchiveArguments(["/path/to/archive", "--output-dir", ""])
        with self.assertRaises(CompareArchiveCliParseError):
            parseCompareArchiveArguments([
                "/path/to/archive",
                "--output-dir",
                "   ",
            ])

        # Duplicate options
        with self.assertRaises(CompareArchiveCliParseError):
            parseCompareArchiveArguments(["/path/to/archive", "--all", "--all"])
        with self.assertRaises(CompareArchiveCliParseError):
            parseCompareArchiveArguments([
                "/path/to/archive",
                "--output-dir",
                "/a",
                "--output-dir",
                "/b",
            ])

        # Unknown options
        with self.assertRaises(CompareArchiveCliParseError):
            parseCompareArchiveArguments(["/path/to/archive", "--foo"])
        with self.assertRaises(CompareArchiveCliParseError):
            parseCompareArchiveArguments(["/path/to/archive", "-x"])
        with self.assertRaises(CompareArchiveCliParseError):
            parseCompareArchiveArguments(["/path/to/archive", "--ssd"])

        # Unexpected extra positional arguments
        with self.assertRaises(CompareArchiveCliParseError):
            parseCompareArchiveArguments([
                "/path/to/archive",
                "read",
                "4",
                "1M",
                "unexpected",
            ])
        with self.assertRaises(CompareArchiveCliParseError):
            parseCompareArchiveArguments([
                "/path/to/archive",
                "--all",
                "unexpected",
            ])
        with self.assertRaises(CompareArchiveCliParseError):
            parseCompareArchiveArguments([
                "/path/to/archive",
                "--output-dir",
                "/tmp",
                "unexpected",
            ])

        # Unexpected token before compare-archive
        with self.assertRaises(CompareArchiveCliParseError):
            parseCompareArchiveArguments([
                "unexpected",
                "compare-archive",
                "/path/to/archive",
            ])

        # Invalid argv types
        with self.assertRaises(CompareArchiveCliParseError):
            parseCompareArchiveArguments(None)  # type: ignore
        with self.assertRaises(CompareArchiveCliParseError):
            parseCompareArchiveArguments("string")  # type: ignore
        with self.assertRaises(CompareArchiveCliParseError):
            parseCompareArchiveArguments(123)  # type: ignore
        with self.assertRaises(CompareArchiveCliParseError):
            parseCompareArchiveArguments(["/path/to/archive", 123])  # type: ignore

    def testVariantReverseResolutionTruthTable(self) -> None:
        """Exhaustively validates all 10 canonical rows of the Reverse-Resolution Truth Table."""
        # Row 1: outputs-native -> backend 'native', variant 'default', collision None, display 'default'
        r1 = VariantReverseResolver.resolve("outputs-native")
        self.assertIsNotNone(r1)
        self.assertEqual(r1.backend, "native")
        self.assertEqual(r1.variant, "default")
        self.assertIsNone(r1.collision)
        self.assertEqual(r1.display_label, "default")
        self.assertEqual(r1.raw_directory, "outputs-native")

        # Row 2: outputs-native-1 -> backend 'native', variant 'default', collision '1', display 'default-1'
        r2 = VariantReverseResolver.resolve("outputs-native-1")
        self.assertIsNotNone(r2)
        self.assertEqual(r2.backend, "native")
        self.assertEqual(r2.variant, "default")
        self.assertEqual(r2.collision, "1")
        self.assertEqual(r2.display_label, "default-1")

        # Row 3: outputs-native-footer -> backend 'native', variant 'footer', collision None, display 'footer'
        r3 = VariantReverseResolver.resolve("outputs-native-footer")
        self.assertIsNotNone(r3)
        self.assertEqual(r3.backend, "native")
        self.assertEqual(r3.variant, "footer")
        self.assertIsNone(r3.collision)
        self.assertEqual(r3.display_label, "footer")

        # Row 4: outputs-native-footer-2 -> backend 'native', variant 'footer', collision '2', display 'footer-2'
        r4 = VariantReverseResolver.resolve("outputs-native-footer-2")
        self.assertIsNotNone(r4)
        self.assertEqual(r4.backend, "native")
        self.assertEqual(r4.variant, "footer")
        self.assertEqual(r4.collision, "2")
        self.assertEqual(r4.display_label, "footer-2")

        # Row 5: outputs-native-footer-btree -> backend 'native', variant 'footer-btree', collision None, display 'footer-btree'
        r5 = VariantReverseResolver.resolve("outputs-native-footer-btree")
        self.assertIsNotNone(r5)
        self.assertEqual(r5.backend, "native")
        self.assertEqual(r5.variant, "footer-btree")
        self.assertIsNone(r5.collision)
        self.assertEqual(r5.display_label, "footer-btree")

        # Row 6: outputs-native-pool-8 -> backend 'native', variant 'pool-8', collision None, display 'pool-8'
        r6 = VariantReverseResolver.resolve("outputs-native-pool-8")
        self.assertIsNotNone(r6)
        self.assertEqual(r6.backend, "native")
        self.assertEqual(r6.variant, "pool-8")
        self.assertIsNone(r6.collision)
        self.assertEqual(r6.display_label, "pool-8")

        # Row 7: outputs-native-pool-8-3 -> backend 'native', variant 'pool-8', collision '3', display 'pool-8-3'
        r7 = VariantReverseResolver.resolve("outputs-native-pool-8-3")
        self.assertIsNotNone(r7)
        self.assertEqual(r7.backend, "native")
        self.assertEqual(r7.variant, "pool-8")
        self.assertEqual(r7.collision, "3")
        self.assertEqual(r7.display_label, "pool-8-3")

        # Row 8: outputs-adios -> backend 'adios', variant 'default', collision None, display 'adios'
        r8 = VariantReverseResolver.resolve("outputs-adios")
        self.assertIsNotNone(r8)
        self.assertEqual(r8.backend, "adios")
        self.assertEqual(r8.variant, "default")
        self.assertIsNone(r8.collision)
        self.assertEqual(r8.display_label, "adios")

        # Row 9: outputs-adios-2 -> backend 'adios', variant 'default', collision '2', display 'adios-2'
        r9 = VariantReverseResolver.resolve("outputs-adios-2")
        self.assertIsNotNone(r9)
        self.assertEqual(r9.backend, "adios")
        self.assertEqual(r9.variant, "default")
        self.assertEqual(r9.collision, "2")
        self.assertEqual(r9.display_label, "adios-2")

        # Row 10: outputs-adios-footer-1 -> backend 'adios', variant 'footer', collision '1', display 'adios-footer-1'
        r10 = VariantReverseResolver.resolve("outputs-adios-footer-1")
        self.assertIsNotNone(r10)
        self.assertEqual(r10.backend, "adios")
        self.assertEqual(r10.variant, "footer")
        self.assertEqual(r10.collision, "1")
        self.assertEqual(r10.display_label, "adios-footer-1")

    def testNonMatchingDirectoryIgnored(self) -> None:
        """Asserts that directories not matching 'outputs-*' return None."""
        self.assertIsNone(VariantReverseResolver.resolve("some-random-folder"))
        self.assertIsNone(VariantReverseResolver.resolve("inputs-native"))
        self.assertIsNone(VariantReverseResolver.resolve("outputs"))
        self.assertIsNone(VariantReverseResolver.resolve("output-native"))
        self.assertIsNone(VariantReverseResolver.resolve("outputs_native"))
        self.assertIsNone(VariantReverseResolver.resolve("archive"))

    def testCompareArchiveHelpText(self) -> None:
        """Asserts that COMPARE_ARCHIVE_HELP_TEXT and LSMIOTOOL_HELP are defined and synchronized."""
        from lsmiotool.lib.cli import COMPARE_ARCHIVE_HELP_TEXT, LSMIOTOOL_HELP

        self.assertIn("lsmiotool compare-archive", COMPARE_ARCHIVE_HELP_TEXT)
        self.assertIn("<archive_folder>", COMPARE_ARCHIVE_HELP_TEXT)
        self.assertIn("--all", COMPARE_ARCHIVE_HELP_TEXT)
        self.assertIn("--output-dir", COMPARE_ARCHIVE_HELP_TEXT)
        self.assertIn("compare-archive <archive_folder>", LSMIOTOOL_HELP)

    def testEntryPointsHelpFlag(self) -> None:
        """Asserts that 'lsmiotool compare-archive --help' and 'lsmiotool --help' succeed with code 0."""
        from pathlib import Path
        import subprocess
        import sys
        from lsmiotool.lib.cli import COMPARE_ARCHIVE_HELP_TEXT

        executable = Path(__file__).resolve().parents[2] / "lsmiotool"
        res_sub = subprocess.run(
            [sys.executable, str(executable), "compare-archive", "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res_sub.returncode, 0)
        self.assertEqual(res_sub.stdout.rstrip(), COMPARE_ARCHIVE_HELP_TEXT.rstrip())

        res_sub_h = subprocess.run(
            [sys.executable, str(executable), "compare-archive", "-h"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res_sub_h.returncode, 0)
        self.assertEqual(res_sub_h.stdout.rstrip(), COMPARE_ARCHIVE_HELP_TEXT.rstrip())

        res_top = subprocess.run(
            [sys.executable, str(executable), "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res_top.returncode, 0)
        self.assertIn("compare-archive <archive_folder>", res_top.stdout)


if __name__ == "__main__":
    unittest.main()
