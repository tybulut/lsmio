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
    LatexCliParseError,
    LatexRequest,
    parseLatexArguments,
)


class LatexCliParserTest(unittest.TestCase):
    """Unit tests for LatexRequest, LatexCliParseError and parseLatexArguments."""

    def testDataModeWithBothDirectories(self) -> None:
        """latex data takes the sources.yaml, --data-dir and --output-dir, in any option order."""
        f_req = parseLatexArguments(
            ["latex", "data", "s.yaml", "--output-dir", "out", "--data-dir", "raw"]
        )
        self.assertIsInstance(f_req, LatexRequest)
        self.assertEqual(f_req.mode, "data")
        self.assertEqual(f_req.sources_path, "s.yaml")
        self.assertEqual(f_req.data_dir, "raw")
        self.assertEqual(f_req.output_dir, "out")
        self.assertIsNone(f_req.tsv_dir)

    def testPlotsModeOutputDirIsOptional(self) -> None:
        """latex plots needs --tsv-dir; --output-dir may be left out."""
        f_req = parseLatexArguments(["latex", "plots", "s.yaml", "--tsv-dir", "tsv"])
        self.assertEqual((f_req.mode, f_req.tsv_dir), ("plots", "tsv"))
        self.assertIsNone(f_req.output_dir)
        self.assertIsNone(f_req.data_dir)
        f_req = parseLatexArguments(
            ["latex", "plots", "s.yaml", "--tsv-dir", "tsv", "--output-dir", "pdf"]
        )
        self.assertEqual(f_req.output_dir, "pdf")

    def testValuesAreStripped(self) -> None:
        """Surrounding whitespace is removed from the path and the option values."""
        f_req = parseLatexArguments(
            ["latex", "data", " s.yaml ", "--data-dir", " raw ", "--output-dir", " out "]
        )
        self.assertEqual(
            (f_req.sources_path, f_req.data_dir, f_req.output_dir), ("s.yaml", "raw", "out")
        )

    def assertRejected(self, f_argv: object, f_text: str) -> None:
        with self.assertRaises(LatexCliParseError) as f_ctx:
            parseLatexArguments(f_argv)  # type: ignore[arg-type]
        self.assertIn(f_text, str(f_ctx.exception))

    def testRejectsAMissingOrUnknownMode(self) -> None:
        """The mode must be data or plots."""
        self.assertRejected(["latex"], "needs a mode")
        self.assertRejected(["latex", "viking"], "Unknown latex mode: 'viking'")
        self.assertRejected(["parse", "data", "s.yaml"], "Not a 'latex' command")
        self.assertRejected([], "Not a 'latex' command")

    def testRejectsAMissingOrEmptySourcesPath(self) -> None:
        """The sources.yaml path comes right after the mode."""
        self.assertRejected(["latex", "data"], "needs the path of a sources.yaml")
        self.assertRejected(
            ["latex", "data", "--data-dir", "d", "--output-dir", "o"],
            "needs the path of a sources.yaml",
        )
        self.assertRejected(
            ["latex", "data", "  ", "--data-dir", "d", "--output-dir", "o"], "cannot be empty"
        )

    def testRejectsMissingRequiredOptions(self) -> None:
        """Each mode names the options it cannot do without."""
        self.assertRejected(["latex", "data", "s.yaml", "--data-dir", "d"], "needs --output-dir")
        self.assertRejected(["latex", "data", "s.yaml", "--output-dir", "o"], "needs --data-dir")
        self.assertRejected(["latex", "plots", "s.yaml"], "needs --tsv-dir")

    def testRejectsOptionsOfTheOtherMode(self) -> None:
        """--tsv-dir belongs to plots and --data-dir to data."""
        self.assertRejected(
            ["latex", "data", "s.yaml", "--data-dir", "d", "--output-dir", "o", "--tsv-dir", "t"],
            "Unknown option for latex data: '--tsv-dir'",
        )
        self.assertRejected(
            ["latex", "plots", "s.yaml", "--tsv-dir", "t", "--data-dir", "d"],
            "Unknown option for latex plots: '--data-dir'",
        )

    def testRejectsBadOptionValues(self) -> None:
        """Duplicate options, missing, empty or option-like values, and stray words are errors."""
        f_ok = ["latex", "data", "s.yaml", "--data-dir", "d", "--output-dir", "o"]
        self.assertRejected(f_ok + ["--data-dir", "e"], "Duplicate '--data-dir'")
        self.assertRejected(f_ok[:-1], "Missing value after '--output-dir'")
        self.assertRejected(
            ["latex", "data", "s.yaml", "--data-dir"], "Missing value after '--data-dir'"
        )
        self.assertRejected(
            ["latex", "data", "s.yaml", "--data-dir", "--output-dir", "o"], "option-like token"
        )
        self.assertRejected(
            ["latex", "data", "s.yaml", "--data-dir", "  ", "--output-dir", "o"], "cannot be empty"
        )
        self.assertRejected(f_ok + ["extra"], "Unexpected extra positional argument: 'extra'")

    def testRejectsANonSequence(self) -> None:
        """argv must be a sequence of strings."""
        self.assertRejected(None, "must be a sequence")
        self.assertRejected("latex data", "must be a sequence")

    def testErrorsAreCliParseErrors(self) -> None:
        """LatexCliParseError can be caught as the common CliParseError."""
        with self.assertRaises(CliParseError):
            parseLatexArguments(["latex"])


if __name__ == "__main__":
    unittest.main()
