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
    ParseCliParseError,
    ParseCliParser,
    ParseRequest,
    parseParseArguments,
)


class ParseCliParserTest(unittest.TestCase):
    """Unit tests for ParseRequest, ParseCliParseError, ParseCliParser, and parseParseArguments."""

    def testValidPositionalTarget(self) -> None:
        """Validates positional target parsing across run roots, manifest paths, and benchmark names."""
        # 1. Benchmark name targets
        f_req_ior = parseParseArguments(["ior"])
        self.assertEqual(f_req_ior.target, "ior")
        self.assertIsNone(f_req_ior.output_dir)
        self.assertIsNone(f_req_ior.outputDir)
        self.assertEqual(f_req_ior.format, "csv")

        f_req_lsmio = parseParseArguments(["lsmio"])
        self.assertEqual(f_req_lsmio.target, "lsmio")

        f_req_lmp = parseParseArguments(["lmp"])
        self.assertEqual(f_req_lmp.target, "lmp")

        # 2. Explicit run root directory path
        f_run_root = "/path/to/benchmark/runs/2026-08-21T12-00-00Z-ior-local"
        f_req_path = parseParseArguments([f_run_root])
        self.assertEqual(f_req_path.target, f_run_root)

        # 3. Explicit manifest.json path
        f_manifest_path = (
            "/path/to/benchmark/runs/2026-08-21T12-00-00Z-ior-local/manifest.json"
        )
        f_req_man = parseParseArguments([f_manifest_path])
        self.assertEqual(f_req_man.target, f_manifest_path)

        # 4. Leading 'parse' subcommand token
        f_req_sub1 = parseParseArguments(["parse", "ior"])
        self.assertEqual(f_req_sub1, f_req_ior)

        f_req_sub2 = parseParseArguments(["parse", f_run_root])
        self.assertEqual(f_req_sub2, f_req_path)

        # 5. Direct ParseCliParser.parse call
        f_req_direct = ParseCliParser.parse(["ior"])
        self.assertEqual(f_req_direct, f_req_ior)

    def testValidOptionsOutputDirAndFormat(self) -> None:
        """Validates --output-dir and --format option parsing with various orders and combinations."""
        # 1. Output directory only
        f_req1 = parseParseArguments(["ior", "--output-dir", "/tmp/reports"])
        self.assertEqual(f_req1.target, "ior")
        self.assertEqual(f_req1.output_dir, "/tmp/reports")
        self.assertEqual(f_req1.outputDir, "/tmp/reports")
        self.assertEqual(f_req1.format, "csv")

        # 2. Format json
        f_req2 = parseParseArguments(["lsmio", "--format", "json"])
        self.assertEqual(f_req2.target, "lsmio")
        self.assertIsNone(f_req2.output_dir)
        self.assertEqual(f_req2.format, "json")

        # 3. Format CSV uppercase normalization
        f_req3 = parseParseArguments(["lmp", "--format", "CSV"])
        self.assertEqual(f_req3.format, "csv")

        # 4. Format JSON uppercase normalization
        f_req4 = parseParseArguments(["ior", "--format", "JSON"])
        self.assertEqual(f_req4.format, "json")

        # 5. Both options: --output-dir then --format
        f_req5 = parseParseArguments(
            ["ior", "--output-dir", "/tmp/reports", "--format", "json"]
        )
        self.assertEqual(f_req5.target, "ior")
        self.assertEqual(f_req5.output_dir, "/tmp/reports")
        self.assertEqual(f_req5.format, "json")

        # 6. Both options: --format then --output-dir
        f_req6 = parseParseArguments(
            ["ior", "--format", "json", "--output-dir", "/tmp/reports"]
        )
        self.assertEqual(f_req6, f_req5)

        # 7. With leading 'parse' token
        f_req7 = parseParseArguments(
            ["parse", "ior", "--output-dir", "/tmp/reports", "--format", "json"]
        )
        self.assertEqual(f_req7, f_req5)

    def testMissingTargetRaisesError(self) -> None:
        """Asserts missing or empty target raises ParseCliParseError."""
        f_missing_targets = [
            [],
            ["parse"],
            ["--output-dir", "/tmp/reports"],
            ["--format", "json"],
            ["parse", "--output-dir", "/tmp/reports"],
            ["parse", "--format", "json"],
            [""],
            ["   "],
            ["parse", ""],
            ["parse", "   "],
        ]

        for f_argv in f_missing_targets:
            with self.assertRaises(
                ParseCliParseError, msg=f"Failed to reject missing target: {f_argv}"
            ):
                parseParseArguments(f_argv)
            with self.assertRaises(CliParseError):
                parseParseArguments(f_argv)

    def testInvalidFormatRaisesError(self) -> None:
        """Asserts invalid format options raise ParseCliParseError."""
        f_invalid_formats = [
            ["ior", "--format", "xml"],
            ["ior", "--format", "html"],
            ["ior", "--format", "txt"],
            ["ior", "--format", "yaml"],
            ["ior", "--format", "123"],
            ["parse", "ior", "--format", "parquet"],
        ]

        for f_argv in f_invalid_formats:
            with self.assertRaises(
                ParseCliParseError, msg=f"Failed to reject invalid format: {f_argv}"
            ):
                parseParseArguments(f_argv)

    def testDuplicateOptionsRaiseError(self) -> None:
        """Asserts duplicate option flags raise ParseCliParseError."""
        f_duplicates = [
            ["ior", "--output-dir", "/tmp/1", "--output-dir", "/tmp/2"],
            ["ior", "--format", "csv", "--format", "json"],
            ["ior", "--format", "json", "--format", "json"],
            ["parse", "ior", "--output-dir", "/tmp/1", "--output-dir", "/tmp/2"],
        ]

        for f_argv in f_duplicates:
            with self.assertRaises(
                ParseCliParseError, msg=f"Failed to reject duplicate options: {f_argv}"
            ):
                parseParseArguments(f_argv)

    def testMissingValuesRaiseError(self) -> None:
        """Asserts missing values after options raise ParseCliParseError."""
        f_missing_values = [
            ["ior", "--output-dir"],
            ["ior", "--format"],
            ["ior", "--output-dir", "--format", "json"],
            ["ior", "--format", "--output-dir", "/tmp/reports"],
            ["parse", "ior", "--output-dir"],
            ["parse", "ior", "--format"],
            ["ior", "--output-dir", ""],
            ["ior", "--output-dir", "   "],
            ["ior", "--format", ""],
            ["ior", "--format", "   "],
        ]

        for f_argv in f_missing_values:
            with self.assertRaises(
                ParseCliParseError,
                msg=f"Failed to reject missing option value: {f_argv}",
            ):
                parseParseArguments(f_argv)

    def testUnknownOptionRaisesError(self) -> None:
        """Asserts unknown option flags raise ParseCliParseError."""
        f_unknown_opts = [
            ["ior", "--unknown"],
            ["ior", "-x"],
            ["ior", "--fast"],
            ["ior", "-v"],
            ["ior", "--ssd"],
            ["parse", "ior", "--verbose"],
            ["parse", "ior", "--output-dir", "/tmp", "--extra-flag"],
        ]

        for f_argv in f_unknown_opts:
            with self.assertRaises(
                ParseCliParseError, msg=f"Failed to reject unknown option: {f_argv}"
            ):
                parseParseArguments(f_argv)

    def testExtraPositionalArgumentsRaiseError(self) -> None:
        """Asserts unexpected extra positional arguments raise ParseCliParseError."""
        f_extra_positionals = [
            ["ior", "extra"],
            ["ior", "local", "bake"],
            ["ior", "--output-dir", "/tmp/reports", "extra"],
            ["ior", "--format", "json", "extra"],
            ["parse", "ior", "extra"],
            ["parse", "ior", "small", "--ssd"],
        ]

        for f_argv in f_extra_positionals:
            with self.assertRaises(
                ParseCliParseError, msg=f"Failed to reject extra positional: {f_argv}"
            ):
                parseParseArguments(f_argv)

    def testInvalidArgvTypesRaiseError(self) -> None:
        """Asserts invalid argv types raise ParseCliParseError."""
        with self.assertRaises(ParseCliParseError):
            parseParseArguments(None)  # type: ignore
        with self.assertRaises(ParseCliParseError):
            parseParseArguments("ior")  # type: ignore
        with self.assertRaises(ParseCliParseError):
            parseParseArguments(b"ior")  # type: ignore
        with self.assertRaises(ParseCliParseError):
            parseParseArguments(123)  # type: ignore
        with self.assertRaises(ParseCliParseError):
            parseParseArguments(["ior", 123])  # type: ignore
        with self.assertRaises(ParseCliParseError):
            parseParseArguments(["ior", None])  # type: ignore

    def testParseRequestImmutabilityAndEquality(self) -> None:
        """Validates ParseRequest initialization, immutability, equality, and serialization."""
        f_req1 = ParseRequest(f_target="ior", f_output_dir="/tmp/out", f_format="json")
        f_req2 = ParseRequest(f_target="ior", f_output_dir="/tmp/out", f_format="json")
        f_req3 = ParseRequest(f_target="ior", f_output_dir=None, f_format="csv")
        f_req4 = ParseRequest(
            f_target="lsmio", f_output_dir="/tmp/out", f_format="json"
        )

        # Equality
        self.assertEqual(f_req1, f_req2)
        self.assertNotEqual(f_req1, f_req3)
        self.assertNotEqual(f_req1, f_req4)
        self.assertFalse(f_req1 == "not_a_request")
        self.assertFalse(f_req1 == 123)

        # Immutability
        with self.assertRaises(AttributeError):
            f_req1.m_target = "lmp"  # type: ignore
        with self.assertRaises(AttributeError):
            f_req1.target = "lmp"  # type: ignore
        with self.assertRaises(AttributeError):
            f_req1.output_dir = "/other"  # type: ignore
        with self.assertRaises(AttributeError):
            f_req1.format = "csv"  # type: ignore
        with self.assertRaises(AttributeError):
            del f_req1.m_target  # type: ignore

        # toDict serialization
        f_dict = f_req1.toDict()
        self.assertEqual(
            f_dict,
            {"target": "ior", "output_dir": "/tmp/out", "format": "json"},
        )

        # __repr__
        self.assertIn("ParseRequest(", repr(f_req1))
        self.assertIn("target='ior'", repr(f_req1))
        self.assertIn("output_dir='/tmp/out'", repr(f_req1))
        self.assertIn("format='json'", repr(f_req1))

        # Direct construction validation errors
        with self.assertRaises(ValueError):
            ParseRequest(f_target="")
        with self.assertRaises(ValueError):
            ParseRequest(f_target="   ")
        with self.assertRaises(ValueError):
            ParseRequest(f_target=None)  # type: ignore
        with self.assertRaises(ValueError):
            ParseRequest(f_target="ior", f_output_dir="")
        with self.assertRaises(ValueError):
            ParseRequest(f_target="ior", f_output_dir="   ")
        with self.assertRaises(ValueError):
            ParseRequest(f_target="ior", f_format="")
        with self.assertRaises(ValueError):
            ParseRequest(f_target="ior", f_format="xml")


if __name__ == "__main__":
    unittest.main()
