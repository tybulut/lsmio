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

import json
import os
import sys
import tempfile
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from lsmiotool.lib import paperdata
from lsmiotool.lib.paperdata import (
    DatasetSpec,
    PaperDataError,
    PlaceholderRule,
    Selection,
    StitchRule,
)

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), *[".."] * 5))

# Only 'latex' needs PyYAML; the tests that read a sources.yaml skip without it
try:
    import yaml  # noqa: F401

    _HAVE_YAML = True
except ImportError:
    _HAVE_YAML = False
_NO_YAML = "PyYAML is not installed (only 'lsmiotool latex' needs it)"


def iorRow(
    f_node: str,
    f_stripes: int,
    f_block_size: str,
    f_op: str,
    f_max: str = "100.00",
    f_mean_s: str = "0.17078",
    f_aggs: str = "128.0",
    f_tasks: Optional[str] = None,
) -> List[str]:
    """A 30-column IOR report row."""
    return [
        f_node,
        str(f_stripes),
        f_block_size,
        f_op,
        f_max,
        "50.00",
        "75.00",
        "1.50",
        f_max,
        "50.00",
        "75.00",
        "1.50",
        f_mean_s,
        "NA",
        "NA",
        "0",
        f_tasks if f_tasks is not None else str(int(f_node)),
        "1",
        "10",
        "0",
        "1",
        "1",
        "0",
        "0",
        "128",
        "1048576",
        "1048576",
        f_aggs,
        "POSIX",
        "0",
    ]


def lsmRow(
    f_node: str,
    f_stripes: int,
    f_block_size: str,
    f_op: str,
    f_max: str = "100",
    f_min: str = "50",
    f_mean: str = "75",
    f_iterations: str = "10",
) -> List[str]:
    """A 10-column LSMIO report row."""
    return [
        f_node,
        str(f_stripes),
        f_block_size,
        f_op,
        f_max,
        f_min,
        f_mean,
        "2559.96",
        "40960",
        f_iterations,
    ]


def writeReport(f_data_dir: str, f_source: str, f_name: str, f_rows: List[List[str]]) -> None:
    """Write f_rows as the report f_name of the source directory f_source."""
    f_dir = os.path.join(f_data_dir, f_source)
    os.makedirs(f_dir, exist_ok=True)
    with open(os.path.join(f_dir, f_name), "w") as f_file:
        for f_row in f_rows:
            f_file.write(",".join(f_row) + "\n")


class PaperDataFormatTest(unittest.TestCase):
    """formatRow: the rules that turn a report row into a TSV row."""

    def testIorRowDropsPaddingAndRoundsMeanSecondsHalfUp(self) -> None:
        """Node counts lose their zero padding; 1.115 becomes 1.12 (half up, not half even)."""
        f_row = paperdata.formatRow("ior", iorRow("01", 16, "1M", "write", f_mean_s="1.115"))
        self.assertEqual(f_row[0], "1")
        self.assertEqual(f_row[1], "16")
        self.assertEqual(f_row[12], "1.12")
        f_row = paperdata.formatRow("ior", iorRow("2", 4, "64K", "read", f_mean_s="0.125"))
        self.assertEqual(f_row[12], "0.13")

    def testIorRowKeepsMeasurementsAndWritesAggsAsInteger(self) -> None:
        """Two-decimal measurements stay as they are; aggs(MiB) 1024.0 becomes 1024."""
        f_row = paperdata.formatRow("ior", iorRow("8", 4, "8M", "write", f_aggs="1024.0"))
        self.assertEqual(f_row[4:12], ["100.00", "50.00", "75.00", "1.50"] * 2)
        self.assertEqual(f_row[13:15], ["NA", "NA"])
        self.assertEqual(f_row[27], "1024")
        self.assertEqual(f_row[28:], ["POSIX", "0"])
        self.assertEqual(len(f_row), 30)

    def testIorRowRoundsLongLatencyInTruncatedRuns(self) -> None:
        """A run cut short has a long decimal where Min(OPs) goes; it is rounded too."""
        f_src = iorRow("24", 4, "64K", "write")
        f_src[9] = "0.343171"
        self.assertEqual(paperdata.formatRow("ior", f_src)[9], "0.34")

    def testIorRowShorterThanTheHeaderIsPadded(self) -> None:
        """A cut-short run's 14-column row is padded with empty cells to 30 columns."""
        f_row = paperdata.formatRow("ior", iorRow("24", 4, "64K", "write")[:14])
        self.assertEqual(len(f_row), 30)
        self.assertEqual(f_row[14:], [""] * 16)

    def testLsmioRowWritesMeasurementsWithTwoDecimals(self) -> None:
        """Every measurement and count column of an LSMIO row has two decimals."""
        f_row = paperdata.formatRow(
            "lsmio", lsmRow("24", 4, "1M", "write", "1158", "859.94", "1035.36")
        )
        self.assertEqual(
            f_row,
            [
                "24",
                "4",
                "1M",
                "write",
                "1158.00",
                "859.94",
                "1035.36",
                "2559.96",
                "40960.00",
                "10.00",
            ],
        )

    def testLsmioEmptyMeasurementsBecomeZero(self) -> None:
        """A run with no data (empty fields, 0 iterations) is written as zeros."""
        f_row = paperdata.formatRow("lsmio", lsmRow("24", 4, "1M", "read", "", "", "", "0"))
        self.assertEqual(f_row[4:7], ["0.00", "0.00", "0.00"])
        self.assertEqual(f_row[9], "0.00")

    def testIorMeasurementMustBeAFiniteNumber(self) -> None:
        """An IOR measurement that is not a finite number is an error; any other number,
        an integer or an exponent too, gets two decimals."""
        for f_cell in ("nan", "abc", "inf"):
            with self.subTest(f_cell=f_cell):
                with self.assertRaises(PaperDataError) as f_ctx:
                    paperdata.formatRow("ior", iorRow("2", 4, "1M", "write", f_max=f_cell))
                self.assertIn("column 'Max(MiB)'", str(f_ctx.exception))
                self.assertIn("nodes=2 stripes=4 block size=1M write", str(f_ctx.exception))
        f_row = paperdata.formatRow("ior", iorRow("2", 4, "1M", "write", f_max="250"))
        self.assertEqual(f_row[4], "250.00")
        f_row = paperdata.formatRow("ior", iorRow("2", 4, "1M", "write", f_max="1e3"))
        self.assertEqual(f_row[4], "1000.00")

    def testNumbersPythonAcceptsButAReportShouldNotHaveAreErrors(self) -> None:
        """'1_000', non-ASCII digits and numbers too large for two decimals are errors, not
        tracebacks or silently rewritten values."""
        for f_cell, f_text in [
            ("1_000", "is not a number"),
            ("١٢", "is not a number"),
            ("1e30", "too large to write with two decimals"),
        ]:
            with self.subTest(f_cell=f_cell):
                with self.assertRaises(PaperDataError) as f_ctx:
                    paperdata.formatRow("lsmio", lsmRow("1", 4, "1M", "write", f_cell))
                self.assertIn(f_text, str(f_ctx.exception))

    def testHugeAggsIsWrittenExactly(self) -> None:
        """aggs(MiB) goes through Decimal, not float: no overflow, no lost digits."""
        f_big = "9" * 400
        f_row = paperdata.formatRow("ior", iorRow("2", 4, "1M", "write", f_aggs=f_big + ".0"))
        self.assertEqual(f_row[27], f_big)

    def testIorStonewallColumnsTakeNaIntegersAndDecimals(self) -> None:
        """Stonewall cells may be NA, empty or an integer (kept) or a decimal (two decimals)."""
        for f_cell, f_written in [("NA", "NA"), ("", ""), ("12", "12"), ("1.5", "1.50")]:
            with self.subTest(f_cell=f_cell):
                f_src = iorRow("2", 4, "1M", "write")
                f_src[13] = f_cell
                self.assertEqual(paperdata.formatRow("ior", f_src)[13], f_written)
        f_src = iorRow("2", 4, "1M", "write")
        f_src[14] = "fast"
        with self.assertRaises(PaperDataError) as f_ctx:
            paperdata.formatRow("ior", f_src)
        self.assertIn("is not NA, an integer or a decimal", str(f_ctx.exception))
        self.assertIn("column 'Stonewall(MiB)'", str(f_ctx.exception))


class PaperDataBuildTest(unittest.TestCase):
    """buildDataset: sorting, stitching and placeholders."""

    def setUp(self) -> None:
        self.m_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.m_tmp.cleanup)
        self.m_dir: str = self.m_tmp.name

    def lsmio(self, f_source: str, f_rows: List[List[str]]) -> None:
        writeReport(self.m_dir, f_source, "lsm-report.csv", f_rows)

    def ior(self, f_source: str, f_rows: List[List[str]]) -> None:
        writeReport(self.m_dir, f_source, "ior-report.csv", f_rows)

    def testSortsByStripesBlockSizeOperationThenNodeCount(self) -> None:
        """Rows are ordered by stripe count, block size, operation (as text), node count (as a number)."""
        f_rows = [
            lsmRow("10", 16, "1M", "write"),
            lsmRow("2", 4, "64K", "write"),
            lsmRow("10", 4, "1M", "write"),
            lsmRow("2", 4, "1M", "write"),
            lsmRow("10", 4, "1M", "read"),
            lsmRow("2", 16, "1M", "write"),
            lsmRow("2", 4, "1M", "read"),
            lsmRow("10", 4, "64K", "write"),
        ]
        self.lsmio("src", f_rows)
        f_result = paperdata.buildDataset(DatasetSpec("o.tsv", "lsmio", "src"), self.m_dir)
        self.assertEqual(f_result.lines[0], "\t".join(paperdata.LSMIO_HEADER))
        f_keys = [tuple(f_line.split("\t")[:4]) for f_line in f_result.lines[1:]]
        self.assertEqual(
            f_keys,
            [
                ("2", "4", "1M", "read"),
                ("10", "4", "1M", "read"),
                ("2", "4", "1M", "write"),
                ("10", "4", "1M", "write"),
                ("2", "4", "64K", "write"),
                ("10", "4", "64K", "write"),
                ("2", "16", "1M", "write"),
                ("10", "16", "1M", "write"),
            ],
        )
        self.assertEqual(f_result.placeholders, [])

    def testIgnoresReportLinesThatAreNotDataRows(self) -> None:
        """A header or blank line in a report is not a data row."""
        writeReport(
            self.m_dir,
            "src",
            "lsm-report.csv",
            [["access", "max"], [], lsmRow("1", 4, "1M", "write")],
        )
        f_result = paperdata.buildDataset(DatasetSpec("o.tsv", "lsmio", "src"), self.m_dir)
        self.assertEqual(len(f_result.lines), 2)

    def testStitchReplacesOnlyTheSelectedRows(self) -> None:
        """A stitch rule takes its selection from the other report and leaves the rest."""
        self.lsmio(
            "a",
            [
                lsmRow("1", 4, "1M", "write", "10"),
                lsmRow("2", 4, "1M", "write", "20"),
                lsmRow("1", 4, "64K", "write", "29"),
                lsmRow("2", 4, "64K", "write", "30"),
            ],
        )
        self.lsmio(
            "b",
            [
                lsmRow("1", 4, "1M", "write", "11"),
                lsmRow("2", 4, "1M", "write", "21"),
                lsmRow("1", 4, "64K", "write", "28"),
                lsmRow("2", 4, "64K", "write", "31"),
            ],
        )
        f_rule = StitchRule("b", Selection([2], [4], ["1M"]))
        f_result = paperdata.buildDataset(DatasetSpec("o.tsv", "lsmio", "a", [f_rule]), self.m_dir)
        f_max = {tuple(f_l.split("\t")[:3]): f_l.split("\t")[4] for f_l in f_result.lines[1:]}
        self.assertEqual(f_max[("1", "4", "1M")], "10.00")
        self.assertEqual(f_max[("2", "4", "1M")], "21.00")
        self.assertEqual(f_max[("1", "4", "64K")], "29.00")
        self.assertEqual(f_max[("2", "4", "64K")], "30.00")
        self.assertEqual(sorted(f_result.provenance), ["a: 3 rows", "b: 1 rows"])

    def testStitchFillsARowThatHasNoData(self) -> None:
        """A run with empty fields in the base report is replaced by the other report's run."""
        self.lsmio("a", [lsmRow("24", 4, "1M", "write", "", "", "", "0")])
        self.lsmio("b", [lsmRow("24", 4, "1M", "write", "1158", "859.94", "1035.36")])
        f_rule = StitchRule("b", Selection([24], [4], ["1M"], ["write"]))
        f_result = paperdata.buildDataset(DatasetSpec("o.tsv", "lsmio", "a", [f_rule]), self.m_dir)
        self.assertEqual(f_result.lines[1].split("\t")[4:7], ["1158.00", "859.94", "1035.36"])
        self.assertEqual(f_result.lines[1].split("\t")[9], "10.00")

    def testStitchThatSelectsNothingIsAnError(self) -> None:
        """A stitch rule that matches no row of its report is a mistake, not a no-op."""
        self.lsmio("a", [lsmRow("1", 4, "1M", "write")])
        self.lsmio("b", [lsmRow("1", 4, "1M", "write")])
        f_rule = StitchRule("b", Selection([48]))
        with self.assertRaises(PaperDataError) as f_ctx:
            paperdata.buildDataset(DatasetSpec("o.tsv", "lsmio", "a", [f_rule]), self.m_dir)
        self.assertIn("selects no row", str(f_ctx.exception))

    def testStitchValueThatSelectsNothingIsAnError(self) -> None:
        """A stitch rule whose listed value takes no row is partly stale, not a no-op."""
        self.lsmio("a", [lsmRow("1", 4, "1M", "write"), lsmRow("2", 4, "1M", "write")])
        self.lsmio("b", [lsmRow("2", 4, "1M", "write", "21")])
        f_rule = StitchRule("b", Selection([2, 99], [4], ["1M", "8M"]))
        with self.assertRaises(PaperDataError) as f_ctx:
            paperdata.buildDataset(DatasetSpec("o.tsv", "lsmio", "a", [f_rule]), self.m_dir)
        self.assertIn("stitch from b selects no row for nodes 99", str(f_ctx.exception))
        f_rule = StitchRule("b", Selection([2], [4], ["1M", "8M"]))
        with self.assertRaises(PaperDataError) as f_ctx:
            paperdata.buildDataset(DatasetSpec("o.tsv", "lsmio", "a", [f_rule]), self.m_dir)
        self.assertIn("selects no row for block_sizes 8M", str(f_ctx.exception))

    def iorWithAGap(self) -> None:
        """Nodes 1, 2, 4 for 1M/write; only 1, 2 for 1M/read, so (4, 1M, read) is missing."""
        self.ior(
            "src",
            [iorRow(f_n, 4, "1M", "write") for f_n in ("1", "2", "4")]
            + [iorRow(f_n, 4, "1M", "read") for f_n in ("1", "2")],
        )

    def testPlaceholderIsNanWithNaSettingsByDefault(self) -> None:
        """By default a missing IOR run has nan measurements (a gap) and NA settings."""
        self.iorWithAGap()
        f_result = paperdata.buildDataset(DatasetSpec("o.tsv", "ior", "src"), self.m_dir)
        self.assertEqual(f_result.placeholders, [(4, 4, "1M", "read")])
        f_rows = [f_l.split("\t") for f_l in f_result.lines[1:] if f_l.startswith("4\t4\t1M\tread")]
        f_row = f_rows[0]
        self.assertEqual(f_row[4:13], ["nan"] * 9)
        self.assertEqual(f_row[13:], ["NA"] * 17)
        self.assertEqual(len(f_row), 30)

    def testLsmioPlaceholderIsNanByDefault(self) -> None:
        """By default a missing LSMIO run is a row of nan under its own key."""
        self.lsmio(
            "src",
            [
                lsmRow("1", 4, "1M", "write"),
                lsmRow("2", 4, "1M", "write"),
                lsmRow("1", 4, "1M", "read"),
            ],
        )
        f_result = paperdata.buildDataset(DatasetSpec("o.tsv", "lsmio", "src"), self.m_dir)
        f_row = [f_l for f_l in f_result.lines[1:] if f_l.startswith("2\t4\t1M\tread")][0]
        # Iterations is a setting, not a measurement: NA like an IOR placeholder's settings
        self.assertEqual(f_row, "2\t4\t1M\tread" + "\tnan" * 5 + "\tNA")

    def testNanPlaceholderNeedsNoEarlierNodeCount(self) -> None:
        """A nan placeholder copies nothing, so the first node count may be missing too."""
        self.ior(
            "src",
            [
                iorRow("1", 4, "1M", "write"),
                iorRow("2", 4, "1M", "write"),
                iorRow("2", 4, "1M", "read"),
            ],
        )
        f_result = paperdata.buildDataset(DatasetSpec("o.tsv", "ior", "src"), self.m_dir)
        self.assertEqual(f_result.placeholders, [(1, 4, "1M", "read")])

    def testPlaceholderCopiesThePrecedingNodeCountWithZeroedMeasurements(self) -> None:
        """With fill zero a missing IOR run is written with zeros and the settings of the
        preceding node count."""
        self.iorWithAGap()
        f_result = paperdata.buildDataset(
            DatasetSpec("o.tsv", "ior", "src", f_fill=paperdata.FILL_ZERO), self.m_dir
        )
        self.assertEqual(f_result.placeholders, [(4, 4, "1M", "read")])
        f_rows = [f_l.split("\t") for f_l in f_result.lines[1:] if f_l.startswith("4\t4\t1M\tread")]
        f_row = f_rows[0]
        self.assertEqual(f_row[4:13], ["0.00"] * 9)
        self.assertEqual(f_row[16], "2")
        self.assertEqual(f_row[27], "128")
        self.assertIn("placeholder: 1 rows", f_result.provenance)

    def testPlaceholderRuleNamesTheNodeCountToCopyFrom(self) -> None:
        """A placeholder rule picks the node count whose settings are copied."""
        self.iorWithAGap()
        f_rule = PlaceholderRule(Selection([4], [4], ["1M"], ["read"]), 1)
        f_result = paperdata.buildDataset(
            DatasetSpec("o.tsv", "ior", "src", f_placeholders=[f_rule], f_fill=paperdata.FILL_ZERO),
            self.m_dir,
        )
        f_rows = [f_l.split("\t") for f_l in f_result.lines[1:] if f_l.startswith("4\t4\t1M\tread")]
        f_row = f_rows[0]
        self.assertEqual(f_row[16], "1")
        self.assertEqual(f_row[4:13], ["0.00"] * 9)

    def testPlaceholderRuleCopyingFromAMissingRunIsAnError(self) -> None:
        """A placeholder rule that names a node count with no run in the report fails."""
        self.iorWithAGap()
        f_rule = PlaceholderRule(Selection([4]), 48)
        with self.assertRaises(PaperDataError) as f_ctx:
            paperdata.buildDataset(
                DatasetSpec(
                    "o.tsv", "ior", "src", f_placeholders=[f_rule], f_fill=paperdata.FILL_ZERO
                ),
                self.m_dir,
            )
        self.assertIn(
            "o.tsv: no run for nodes=48 stripes=4 block size=1M read", str(f_ctx.exception)
        )

    def testPlaceholderForTheFirstNodeCountHasNothingToCopy(self) -> None:
        """With fill zero an IOR placeholder needs an earlier node count to copy from."""
        self.ior(
            "src",
            [
                iorRow("1", 4, "1M", "write"),
                iorRow("2", 4, "1M", "write"),
                iorRow("2", 4, "1M", "read"),
            ],
        )
        with self.assertRaises(PaperDataError) as f_ctx:
            paperdata.buildDataset(
                DatasetSpec("o.tsv", "ior", "src", f_fill=paperdata.FILL_ZERO), self.m_dir
            )
        self.assertIn("o.tsv: no earlier node count", str(f_ctx.exception))
        self.assertIn("nodes=1 stripes=4 block size=1M read", str(f_ctx.exception))

    def testLsmioPlaceholderIsAllZeros(self) -> None:
        """With fill zero a missing LSMIO run is a row of zeros under its own key."""
        self.lsmio(
            "src",
            [
                lsmRow("1", 4, "1M", "write"),
                lsmRow("2", 4, "1M", "write"),
                lsmRow("1", 4, "1M", "read"),
            ],
        )
        f_result = paperdata.buildDataset(
            DatasetSpec("o.tsv", "lsmio", "src", f_fill=paperdata.FILL_ZERO), self.m_dir
        )
        self.assertEqual(f_result.placeholders, [(2, 4, "1M", "read")])
        f_row = [f_l for f_l in f_result.lines[1:] if f_l.startswith("2\t4\t1M\tread")][0]
        self.assertEqual(f_row, "2\t4\t1M\tread" + "\t0.00" * 6)

    def testMissingRunIsAnErrorWhenTheSpecSaysSo(self) -> None:
        """With missing=error a gap in the grid stops the build."""
        self.iorWithAGap()
        with self.assertRaises(PaperDataError) as f_ctx:
            paperdata.buildDataset(
                DatasetSpec("o.tsv", "ior", "src", f_missing=paperdata.MISSING_ERROR), self.m_dir
            )
        self.assertIn("no run for", str(f_ctx.exception))

    def testMissingReportIsAnError(self) -> None:
        """A source directory without its report cannot be built."""
        with self.assertRaises(PaperDataError) as f_ctx:
            paperdata.buildDataset(DatasetSpec("o.tsv", "ior", "nowhere"), self.m_dir)
        self.assertIn("cannot read report", str(f_ctx.exception))

    def testMalformedRowIsAnError(self) -> None:
        """A row whose stripe count is not a number is reported, not skipped."""
        writeReport(self.m_dir, "src", "lsm-report.csv", [lsmRow("1", 4, "1M", "write")])
        f_bad = lsmRow("2", 4, "1M", "write")
        f_bad[1] = "x"
        writeReport(self.m_dir, "bad", "lsm-report.csv", [f_bad])
        with self.assertRaises(PaperDataError) as f_ctx:
            paperdata.buildDataset(DatasetSpec("o.tsv", "lsmio", "bad"), self.m_dir)
        self.assertIn("malformed row", str(f_ctx.exception))

    def testReportWithoutDataRowsIsAnError(self) -> None:
        """A report with no data row would write a header-only TSV; it is an error instead."""
        writeReport(self.m_dir, "src", "lsm-report.csv", [["access", "max"], []])
        with self.assertRaises(PaperDataError) as f_ctx:
            paperdata.buildDataset(DatasetSpec("o.tsv", "lsmio", "src"), self.m_dir)
        self.assertIn("has no data rows", str(f_ctx.exception))

    def testRunListedTwiceIsAnError(self) -> None:
        """Two rows for one run are not resolved silently; a stitch rule has to choose."""
        self.lsmio(
            "src", [lsmRow("1", 4, "1M", "write", "10"), lsmRow("01", 4, "1M", "write", "11")]
        )
        with self.assertRaises(PaperDataError) as f_ctx:
            paperdata.buildDataset(DatasetSpec("o.tsv", "lsmio", "src"), self.m_dir)
        self.assertIn("twice", str(f_ctx.exception))

    def testMeasurementThatIsNotAFiniteNumberIsAnError(self) -> None:
        """A non-number or non-finite measurement is reported with its column and run."""
        for f_cell, f_text in [
            ("N/A", "is not a number"),
            ("inf", "is not a finite number"),
            ("nan", "is not a finite number"),
        ]:
            with self.subTest(f_cell=f_cell):
                self.lsmio("src", [lsmRow("1", 4, "1M", "write", f_cell)])
                with self.assertRaises(PaperDataError) as f_ctx:
                    paperdata.buildDataset(DatasetSpec("o.tsv", "lsmio", "src"), self.m_dir)
                self.assertIn(f_text, str(f_ctx.exception))
                self.assertIn("column 'Max (MiBs)'", str(f_ctx.exception))
                self.assertIn("nodes=1 stripes=4 block size=1M write", str(f_ctx.exception))
                self.assertIn("o.tsv", str(f_ctx.exception))

    def testRowShorterThanTheHeaderIsReportedAsPadded(self) -> None:
        """A run cut short is listed in the result so generate can warn about it."""
        self.ior("src", [iorRow("1", 4, "1M", "write")[:14], iorRow("2", 4, "1M", "write")])
        f_result = paperdata.buildDataset(DatasetSpec("o.tsv", "ior", "src"), self.m_dir)
        self.assertEqual(f_result.padded, [(1, 4, "1M", "write")])
        self.assertEqual(f_result.placeholders, [])

    def testPlaceholderRuleThatMatchesNoMissingRunIsAnError(self) -> None:
        """A placeholder rule for a run that exists is stale and stops the build."""
        self.iorWithAGap()
        f_rule = PlaceholderRule(Selection([2], [4], ["1M"], ["read"]), 1)
        with self.assertRaises(PaperDataError) as f_ctx:
            paperdata.buildDataset(
                DatasetSpec(
                    "o.tsv", "ior", "src", f_placeholders=[f_rule], f_fill=paperdata.FILL_ZERO
                ),
                self.m_dir,
            )
        self.assertIn("applies to no missing run", str(f_ctx.exception))

    def testPlaceholderRuleValueThatMatchesNoMissingRunIsAnError(self) -> None:
        """A placeholder rule listing a run that exists next to one that is missing is
        partly stale."""
        self.iorWithAGap()
        f_rule = PlaceholderRule(Selection([4, 2], [4], ["1M"], ["read"]), 1)
        with self.assertRaises(PaperDataError) as f_ctx:
            paperdata.buildDataset(
                DatasetSpec(
                    "o.tsv", "ior", "src", f_placeholders=[f_rule], f_fill=paperdata.FILL_ZERO
                ),
                self.m_dir,
            )
        self.assertIn("placeholder rule 0 matches no missing run for nodes 2", str(f_ctx.exception))

    def lsmioWithAFailedRun(self) -> None:
        """Nodes 1 and 2 for 4/1M write; the 2-node run has every measurement empty."""
        self.lsmio(
            "src",
            [lsmRow("1", 4, "1M", "write"), ["2", "4", "1M", "write", "", "", "", "", "", "0"]],
        )

    def testRunWithoutDataIsWrittenAsNanAndReported(self) -> None:
        """A failed run (every measurement empty) gets nan measurements by default and is
        listed in the result; its reported settings, LSMIO's Iterations too, stay."""
        self.lsmioWithAFailedRun()
        f_result = paperdata.buildDataset(DatasetSpec("o.tsv", "lsmio", "src"), self.m_dir)
        self.assertEqual(f_result.empty, [(2, 4, "1M", "write")])
        self.assertEqual(f_result.lines[2], "2\t4\t1M\twrite" + "\tnan" * 5 + "\t0.00")
        self.lsmio(
            "isrc10",
            [lsmRow("1", 4, "1M", "write"), ["2", "4", "1M", "write", "", "", "", "", "", "10"]],
        )
        f_result = paperdata.buildDataset(DatasetSpec("o.tsv", "lsmio", "isrc10"), self.m_dir)
        self.assertEqual(f_result.lines[2], "2\t4\t1M\twrite" + "\tnan" * 5 + "\t10.00")
        f_failed = iorRow("2", 4, "1M", "write")
        f_failed[4:13] = [""] * 9
        self.ior("isrc", [iorRow("1", 4, "1M", "write"), f_failed])
        f_row = (
            paperdata.buildDataset(DatasetSpec("o.tsv", "ior", "isrc"), self.m_dir)
            .lines[2]
            .split("\t")
        )
        self.assertEqual(f_row[4:13], ["nan"] * 9)
        self.assertEqual(f_row[16], "2")

    def testRunWithoutDataIsWrittenAsZerosWithFillZero(self) -> None:
        """With fill zero a failed run is written as zeros."""
        self.lsmioWithAFailedRun()
        f_result = paperdata.buildDataset(
            DatasetSpec("o.tsv", "lsmio", "src", f_fill=paperdata.FILL_ZERO), self.m_dir
        )
        self.assertEqual(f_result.lines[2], "2\t4\t1M\twrite" + "\t0.00" * 6)

    def testOverlappingStitchRulesAreAnError(self) -> None:
        """Two stitch rules that select one run would let the last one win silently."""
        self.lsmio("a", [lsmRow("1", 4, "1M", "write")])
        self.lsmio("b", [lsmRow("1", 4, "1M", "write", "11")])
        self.lsmio("c", [lsmRow("1", 4, "1M", "write", "12")])
        f_spec = DatasetSpec(
            "o.tsv", "lsmio", "a", [StitchRule("b", Selection()), StitchRule("c", Selection())]
        )
        with self.assertRaises(PaperDataError) as f_ctx:
            paperdata.buildDataset(f_spec, self.m_dir)
        self.assertIn(
            "stitch rules from b and c both select the run for nodes=1", str(f_ctx.exception)
        )

    def testRowWiderThanTheHeaderIsAnError(self) -> None:
        """Extra cells would be written past the header without a word."""
        self.lsmio("src", [lsmRow("1", 4, "1M", "write") + ["x", "y"]])
        with self.assertRaises(PaperDataError) as f_ctx:
            paperdata.buildDataset(DatasetSpec("o.tsv", "lsmio", "src"), self.m_dir)
        self.assertIn("has 12 columns, more than the header's 10", str(f_ctx.exception))

    def testRunWithoutDataIsAnErrorWhenMissingIsError(self) -> None:
        """With missing=error a failed run stops the build like a missing one."""
        self.lsmioWithAFailedRun()
        with self.assertRaises(PaperDataError) as f_ctx:
            paperdata.buildDataset(
                DatasetSpec("o.tsv", "lsmio", "src", f_missing=paperdata.MISSING_ERROR), self.m_dir
            )
        self.assertIn("nodes=2 stripes=4 block size=1M write has no data", str(f_ctx.exception))

    def testRunWithSomeMeasurementsEmptyIsAnError(self) -> None:
        """A run with only some measurements empty is not a failed run; it is an error."""
        self.lsmio("src", [lsmRow("1", 4, "1M", "write", "100", "", "75")])
        with self.assertRaises(PaperDataError) as f_ctx:
            paperdata.buildDataset(DatasetSpec("o.tsv", "lsmio", "src"), self.m_dir)
        self.assertIn("has only some of its measurements", str(f_ctx.exception))

    def testGridAddsPlaceholdersForANodeCountNoRunHas(self) -> None:
        """A node count of the grid missing from the whole report becomes placeholders."""
        self.lsmio("src", [lsmRow("1", 4, "1M", "write"), lsmRow("2", 4, "1M", "write")])
        f_spec = DatasetSpec("o.tsv", "lsmio", "src", f_grid=Selection([1, 2, 4]))
        f_result = paperdata.buildDataset(f_spec, self.m_dir)
        self.assertEqual(f_result.placeholders, [(4, 4, "1M", "write")])
        self.assertEqual(len(f_result.lines), 4)

    def testGridAddsPlaceholdersForACombinationNoRunHas(self) -> None:
        """Every stripe count, block size and operation of the grid is expected."""
        self.lsmio("src", [lsmRow("1", 4, "1M", "write")])
        f_spec = DatasetSpec(
            "o.tsv", "lsmio", "src", f_grid=Selection(None, None, None, ["read", "write"])
        )
        f_result = paperdata.buildDataset(f_spec, self.m_dir)
        self.assertEqual(f_result.placeholders, [(1, 4, "1M", "read")])

    def testRunOutsideTheGridIsAnError(self) -> None:
        """A report row the grid does not list is an error, not an extra chart row."""
        self.lsmio("src", [lsmRow("1", 4, "1M", "write"), lsmRow("2", 4, "1M", "write")])
        with self.assertRaises(PaperDataError) as f_ctx:
            paperdata.buildDataset(
                DatasetSpec("o.tsv", "lsmio", "src", f_grid=Selection([1])), self.m_dir
            )
        self.assertIn("1 run(s) outside the grid", str(f_ctx.exception))
        self.assertIn("nodes=2 stripes=4 block size=1M write", str(f_ctx.exception))

    def testCorruptCsvIsAnError(self) -> None:
        """A field over the csv module's limit (an unbalanced quote) is reported, not a traceback."""
        f_dir = os.path.join(self.m_dir, "src")
        os.makedirs(f_dir)
        with open(os.path.join(f_dir, "lsm-report.csv"), "w") as f_file:
            f_file.write('1,4,"' + "x" * 200000 + "\n")
        with self.assertRaises(PaperDataError) as f_ctx:
            paperdata.buildDataset(DatasetSpec("o.tsv", "lsmio", "src"), self.m_dir)
        self.assertIn("malformed row", str(f_ctx.exception))


class PaperDataGenerateTest(unittest.TestCase):
    """generate: writing the TSVs."""

    def setUp(self) -> None:
        self.m_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.m_tmp.cleanup)
        self.m_data: str = os.path.join(self.m_tmp.name, "data")
        self.m_out: str = os.path.join(self.m_tmp.name, "out")
        writeReport(
            self.m_data,
            "a",
            "lsm-report.csv",
            [lsmRow("1", 4, "1M", "write"), lsmRow("2", 4, "1M", "write")],
        )

    def testWritesEveryTsvWithCrlfLineEnds(self) -> None:
        """Files land under the output dir, each line ends in CRLF, the last one too."""
        f_sources = paperdata.PaperSources(
            [DatasetSpec("hdd/bm/a.tsv", "lsmio", "a"), DatasetSpec("b.tsv", "lsmio", "a")], []
        )
        f_results = paperdata.generate(f_sources, self.m_data, self.m_out)
        self.assertEqual(len(f_results), 2)
        with open(os.path.join(self.m_out, "hdd", "bm", "a.tsv"), "rb") as f_file:
            f_bytes = f_file.read()
        self.assertTrue(f_bytes.endswith(b"\r\n"))
        self.assertEqual(f_bytes.count(b"\n"), f_bytes.count(b"\r\n"))
        self.assertEqual(f_bytes.count(b"\r\n"), 3)
        self.assertTrue(os.path.isfile(os.path.join(self.m_out, "b.tsv")))
        self.assertEqual(sorted(os.listdir(self.m_out)), ["b.tsv", "hdd"])
        self.assertEqual(os.listdir(os.path.join(self.m_out, "hdd", "bm")), ["a.tsv"])

    def testLeavesTheExistingTsvsWhenAFileCannotBeWritten(self) -> None:
        """A write failure is a PaperDataError; the old TSVs stay and no temporary file is left."""
        os.makedirs(os.path.join(self.m_out, "b.tsv.tmp"))
        with open(os.path.join(self.m_out, "a.tsv"), "wb") as f_file:
            f_file.write(b"old")
        f_sources = paperdata.PaperSources(
            [DatasetSpec("a.tsv", "lsmio", "a"), DatasetSpec("b.tsv", "lsmio", "a")], []
        )
        with self.assertRaises(PaperDataError) as f_ctx:
            paperdata.generate(f_sources, self.m_data, self.m_out)
        self.assertIn("cannot write the output", str(f_ctx.exception))
        with open(os.path.join(self.m_out, "a.tsv"), "rb") as f_file:
            self.assertEqual(f_file.read(), b"old")
        self.assertFalse(os.path.exists(os.path.join(self.m_out, "a.tsv.tmp")))
        self.assertFalse(os.path.exists(os.path.join(self.m_out, "b.tsv")))

    def testWarnsForEveryPaddedRow(self) -> None:
        """Each run cut short is reported as a warning naming the run."""
        writeReport(
            self.m_data,
            "short",
            "ior-report.csv",
            [iorRow("1", 4, "1M", "write")[:14], iorRow("2", 4, "1M", "write")],
        )
        f_sources = paperdata.PaperSources([DatasetSpec("short.tsv", "ior", "short")], [])
        with patch.object(paperdata.Console, "warning") as f_warning:
            paperdata.generate(f_sources, self.m_data, self.m_out)
        f_warning.assert_called_once()
        self.assertIn("nodes=1 stripes=4 block size=1M write", f_warning.call_args[0][0])
        self.assertIn("fewer columns than the header", f_warning.call_args[0][0])

    def testWarnsForEveryRunWithoutData(self) -> None:
        """Each failed run is reported as a warning naming the run and how it was written."""
        writeReport(
            self.m_data,
            "failed",
            "lsm-report.csv",
            [lsmRow("1", 4, "1M", "write"), ["2", "4", "1M", "write", "", "", "", "", "", "0"]],
        )
        for f_fill, f_written in [
            (paperdata.FILL_NAN, "written as nan (a gap)"),
            (paperdata.FILL_ZERO, "written as zeros"),
        ]:
            with self.subTest(f_fill=f_fill):
                f_spec = DatasetSpec("failed.tsv", "lsmio", "failed", f_fill=f_fill)
                with patch.object(paperdata.Console, "warning") as f_warning:
                    paperdata.generate(
                        paperdata.PaperSources([f_spec], []), self.m_data, self.m_out
                    )
                f_warning.assert_called_once()
                self.assertIn(
                    "nodes=2 stripes=4 block size=1M write has no data", f_warning.call_args[0][0]
                )
                self.assertIn(f_written, f_warning.call_args[0][0])

    def testTargetThatIsADirectoryChangesNothing(self) -> None:
        """An output path that is a directory is found before any TSV is replaced."""
        os.makedirs(os.path.join(self.m_out, "b.tsv"))
        with open(os.path.join(self.m_out, "a.tsv"), "wb") as f_file:
            f_file.write(b"old")
        f_sources = paperdata.PaperSources(
            [DatasetSpec("a.tsv", "lsmio", "a"), DatasetSpec("b.tsv", "lsmio", "a")], []
        )
        with self.assertRaises(PaperDataError) as f_ctx:
            paperdata.generate(f_sources, self.m_data, self.m_out)
        self.assertIn("is a directory", str(f_ctx.exception))
        with open(os.path.join(self.m_out, "a.tsv"), "rb") as f_file:
            self.assertEqual(f_file.read(), b"old")
        self.assertFalse(os.path.exists(os.path.join(self.m_out, "a.tsv.tmp")))

    def testWritesNothingWhenADatasetFailsToBuild(self) -> None:
        """A failing dataset stops the run before any TSV is written."""
        f_sources = paperdata.PaperSources(
            [DatasetSpec("a.tsv", "lsmio", "a"), DatasetSpec("b.tsv", "lsmio", "nowhere")], []
        )
        with self.assertRaises(PaperDataError):
            paperdata.generate(f_sources, self.m_data, self.m_out)
        self.assertFalse(os.path.exists(os.path.join(self.m_out, "a.tsv")))

    def testWarnsForEveryPlaceholder(self) -> None:
        """Each placeholder row is reported as a warning naming the run."""
        writeReport(
            self.m_data,
            "gap",
            "lsm-report.csv",
            [
                lsmRow("1", 4, "1M", "write"),
                lsmRow("2", 4, "1M", "write"),
                lsmRow("1", 4, "1M", "read"),
            ],
        )
        f_sources = paperdata.PaperSources([DatasetSpec("gap.tsv", "lsmio", "gap")], [])
        with patch.object(paperdata.Console, "warning") as f_warning:
            paperdata.generate(f_sources, self.m_data, self.m_out)
        f_warning.assert_called_once()
        self.assertIn("nodes=2 stripes=4 block size=1M read", f_warning.call_args[0][0])
        self.assertIn("placeholder of nan (a gap)", f_warning.call_args[0][0])


def sourcesDoc() -> Dict[str, Any]:
    """A valid sources.yaml document with one ior dataset and one figure."""
    return {
        "schema": 1,
        "datasets": [
            {
                "output": "hdd/a.tsv",
                "kind": "ior",
                "source": "viking/a",
                "stitch": [{"source": "viking/b", "nodes": [24], "block_sizes": ["1M"]}],
                "fill": "zero",
                "placeholders": [{"nodes": [24], "copy_from_node": 16}],
            }
        ],
        "figures": [
            {
                "file": "f.pdf",
                "title": "T",
                "y_label": "Y",
                "y_divisor": 1024,
                "series": [
                    {
                        "label": "L",
                        "dataset": "hdd/a.tsv",
                        "stripes": 4,
                        "block_size": "64K",
                        "op": "write",
                    }
                ],
            }
        ],
    }


class PaperSourcesWithoutYamlTest(unittest.TestCase):
    """loadSources on a host without PyYAML."""

    def testMissingPyYamlIsReported(self) -> None:
        """Without PyYAML the error says what to install instead of a traceback."""
        with tempfile.TemporaryDirectory() as f_dir:
            f_path = os.path.join(f_dir, "sources.yaml")
            with open(f_path, "w") as f_file:
                f_file.write(json.dumps(sourcesDoc()))
            with patch.dict(sys.modules, {"yaml": None}):
                with self.assertRaises(PaperDataError) as f_ctx:
                    paperdata.loadSources(f_path)
        self.assertIn("needs PyYAML", str(f_ctx.exception))


@unittest.skipUnless(_HAVE_YAML, _NO_YAML)
class PaperSourcesTest(unittest.TestCase):
    """loadSources: validation of sources.yaml."""

    def setUp(self) -> None:
        self.m_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.m_tmp.cleanup)
        self.m_path: str = os.path.join(self.m_tmp.name, "sources.yaml")

    def doc(self) -> Dict[str, Any]:
        return sourcesDoc()

    def load(self, f_doc: Any) -> paperdata.PaperSources:
        with open(self.m_path, "w") as f_file:
            # JSON is YAML; the YAML-only behaviour is tested with YAML text below
            f_file.write(f_doc if isinstance(f_doc, str) else json.dumps(f_doc))
        return paperdata.loadSources(self.m_path)

    def testLoadsAValidDocument(self) -> None:
        """A valid sources.yaml yields its datasets, stitch rules, placeholder rules and figures."""
        f_sources = self.load(self.doc())
        f_spec = f_sources.datasets[0]
        self.assertEqual(
            (f_spec.output, f_spec.kind, f_spec.source), ("hdd/a.tsv", "ior", "viking/a")
        )
        self.assertEqual(f_spec.missing, paperdata.MISSING_PLACEHOLDER)
        self.assertEqual(f_spec.stitch[0].source, "viking/b")
        self.assertTrue(f_spec.stitch[0].selection.selects((24, 4, "1M", "write")))
        self.assertFalse(f_spec.stitch[0].selection.selects((16, 4, "1M", "write")))
        self.assertFalse(f_spec.stitch[0].selection.selects((24, 4, "64K", "write")))
        self.assertEqual(f_spec.placeholders[0].copy_from_node, 16)
        f_figure = f_sources.figures[0]
        self.assertEqual((f_figure.file, f_figure.y_divisor), ("f.pdf", 1024.0))
        self.assertEqual(f_figure.series[0].label, "L")

    def testFiguresAreOptionalAndDivisorDefaultsToOne(self) -> None:
        """Without figures a sources.yaml is valid for 'latex data'; y_divisor defaults to 1."""
        f_doc = self.doc()
        del f_doc["figures"]
        self.assertEqual(self.load(f_doc).figures, [])
        f_doc = self.doc()
        del f_doc["figures"][0]["y_divisor"]
        self.assertEqual(self.load(f_doc).figures[0].y_divisor, 1.0)

    def assertRejected(self, f_doc: Any, f_text: str) -> None:
        with self.assertRaises(PaperDataError) as f_ctx:
            self.load(f_doc)
        self.assertIn(f_text, str(f_ctx.exception))

    def testRejectsADocumentThatIsNotUsable(self) -> None:
        """Unreadable, non-YAML, wrongly shaped or wrong-schema documents are rejected."""
        with self.assertRaises(PaperDataError) as f_ctx:
            paperdata.loadSources(os.path.join(self.m_tmp.name, "missing.yaml"))
        self.assertIn("cannot read", str(f_ctx.exception))
        self.assertRejected("{not yaml", "not valid YAML")
        self.assertRejected("", "top level must be an object")
        self.assertRejected([], "top level must be an object")
        f_doc = self.doc()
        f_doc["schema"] = 2
        self.assertRejected(f_doc, "schema must be 1")
        f_doc = self.doc()
        f_doc["datasets"] = []
        self.assertRejected(f_doc, "datasets must be a non-empty list")

    def testRejectsBadDatasets(self) -> None:
        """Each field of a dataset is checked."""
        for f_change, f_text in [
            ({"output": "/abs/a.tsv"}, "relative path"),
            ({"output": "../a.tsv"}, "relative path"),
            ({"source": "../x"}, "relative path"),
            ({"kind": "lmp"}, "kind 'lmp'"),
            ({"output": ""}, "'output' must be a non-empty string"),
            ({"missing": "zero"}, "missing 'zero'"),
            ({"stitch": {}}, "stitch must be a list"),
            ({"stitch": [{"source": "viking/b", "colour": 1}]}, "unknown field"),
            ({"stitch": [{"source": "viking/b", "nodes": ["24"]}]}, "list of integers"),
            ({"stitch": [{"source": "viking/b", "ops": [1]}]}, "list of strings"),
            ({"stitch": ["x"]}, "must be an object"),
            ({"placeholders": {}}, "placeholders must be a list"),
            ({"placeholders": [{"nodes": [1]}]}, "copy_from_node must be an integer"),
            ({"placeholders": ["x"]}, "must be an object"),
            ({"kind": "lsmio"}, "placeholders apply to ior datasets only"),
            ({"stiches": []}, "unknown field(s) stiches"),
            ({"stitch": [{"source": "./viking/a"}]}, "is the dataset's own source"),
            ({"grid": []}, "grid must be an object"),
            ({"grid": {"nodes": []}}, "grid.nodes must not be empty"),
            ({"grid": {"node": [1]}}, "unknown field(s) node"),
        ]:
            with self.subTest(f_change=f_change):
                f_doc = self.doc()
                f_doc["datasets"][0].update(f_change)
                self.assertRejected(f_doc, f_text)
        f_doc = self.doc()
        f_doc["datasets"] = ["x"]
        self.assertRejected(f_doc, "must be an object")

    def testRejectsTwoDatasetsWithTheSameOutput(self) -> None:
        """Two datasets may not write one file."""
        f_doc = self.doc()
        f_doc["datasets"].append(dict(f_doc["datasets"][0]))
        self.assertRejected(f_doc, "write the same output")
        f_doc = self.doc()
        f_doc["datasets"].append(dict(f_doc["datasets"][0], output="./hdd/a.tsv"))
        self.assertRejected(f_doc, "write the same output")
        # one file on a file system that ignores case (macOS by default)
        f_doc = self.doc()
        f_doc["datasets"].append(dict(f_doc["datasets"][0], output="HDD/A.tsv"))
        self.assertRejected(f_doc, "write the same output")

    def testRejectsTwoFiguresWithTheSameFile(self) -> None:
        """The second figure would overwrite the first PDF; case is ignored, as for outputs."""
        f_doc = self.doc()
        f_doc["figures"].append(dict(f_doc["figures"][0], file="./F.pdf"))
        self.assertRejected(f_doc, "two figures write the same file")
        f_doc = self.doc()
        f_doc["datasets"].append(dict(f_doc["datasets"][0], output="hdd/a.tsv.tmp"))
        self.assertRejected(f_doc, "is the temporary file of output hdd/a.tsv")

    def testRejectsUnknownFieldsEverywhere(self) -> None:
        """A misspelt field at the top level, in a figure or in a series is an error."""
        f_doc = self.doc()
        f_doc["figure"] = []
        self.assertRejected(f_doc, "unknown field(s) figure")
        f_doc = self.doc()
        f_doc["figures"][0]["ylabel"] = "Y"
        self.assertRejected(f_doc, "figures[0]: unknown field(s) ylabel")
        f_doc = self.doc()
        f_doc["figures"][0]["series"][0]["stripe"] = 4
        self.assertRejected(f_doc, "figures[0].series[0]: unknown field(s) stripe")

    def testSchemaMustBeTheInteger1(self) -> None:
        """YAML's true equals 1 in Python; it is not schema 1."""
        f_doc = self.doc()
        f_doc["schema"] = True
        self.assertRejected(f_doc, "schema must be 1, found True")

    def testGridAtTheTopIsTheDefaultAndADatasetGridReplacesIt(self) -> None:
        """The top-level grid applies to every dataset without a grid of its own."""
        f_doc = self.doc()
        f_doc["grid"] = {"nodes": [1, 2], "ops": ["read", "write"]}
        f_doc["datasets"].append(
            {"output": "b.tsv", "kind": "lsmio", "source": "viking/c", "grid": {"stripes": [4]}}
        )
        f_first, f_second = self.load(f_doc).datasets
        self.assertEqual((f_first.grid.nodes, f_first.grid.ops), ([1, 2], ["read", "write"]))
        self.assertEqual((f_second.grid.nodes, f_second.grid.stripes), (None, [4]))

    def testSeriesMayNameItsDatasetWithAnEquivalentPath(self) -> None:
        """'./hdd/a.tsv' names the dataset whose output is 'hdd/a.tsv'."""
        f_doc = self.doc()
        f_doc["figures"][0]["series"][0]["dataset"] = "./hdd/a.tsv"
        self.assertEqual(self.load(f_doc).figures[0].series[0].dataset, "./hdd/a.tsv")

    def testRejectsAKeyGivenTwice(self) -> None:
        """A repeated key is an error, not PyYAML's silent last-one-wins."""
        self.assertRejected(
            "schema: 1\n"
            "datasets:\n"
            "  - output: hdd/a.tsv\n"
            "    kind: ior\n"
            "    kind: lsmio\n"
            "    source: viking/a\n",
            "found the key 'kind' twice",
        )

    def testMergedKeysMayBeOverridden(self) -> None:
        """A key that overrides one merged in with '<<' is not a repeat."""
        f_sources = self.load(
            "schema: 1\n"
            "datasets:\n"
            "  - {output: hdd/a.tsv, kind: ior, source: viking/a}\n"
            "figures:\n"
            "  - file: f.pdf\n"
            "    title: T\n"
            "    y_label: Y\n"
            "    series:\n"
            "      - &write {label: W, dataset: hdd/a.tsv, stripes: 4, block_size: 64K, op: write}\n"
            "      - {<<: *write, label: R, op: read}\n"
        )
        f_read = f_sources.figures[0].series[1]
        self.assertEqual((f_read.label, f_read.op, f_read.block_size), ("R", "read", "64K"))

    def testUnquotedYesOrNoIsRejected(self) -> None:
        """YAML reads an unquoted no as a boolean; the schema check catches it."""
        self.assertRejected(
            "schema: 1\n"
            "datasets:\n"
            "  - output: hdd/a.tsv\n"
            "    kind: ior\n"
            "    source: viking/a\n"
            "    stitch:\n"
            "      - {source: viking/b, ops: [no]}\n",
            "list of strings",
        )

    def testYamlNanOrInfinityIsNotADivisor(self) -> None:
        """YAML's .nan and .inf are floats; neither is a usable y_divisor."""
        for f_value in (".nan", ".inf"):
            with self.subTest(f_value=f_value):
                self.assertRejected(
                    "schema: 1\n"
                    "datasets: [{output: a.tsv, kind: lsmio, source: s}]\n"
                    "figures:\n"
                    f"  - {{file: f.pdf, title: T, y_label: Y, y_divisor: {f_value},\n"
                    "     series: [{label: L, dataset: a.tsv, stripes: 4, block_size: 1M, op: read}]}\n",
                    "y_divisor must be a positive finite number",
                )

    def testSchemaMustNotBeAFloat(self) -> None:
        """schema 1.0 equals 1 in Python; it is not the integer schema 1."""
        f_doc = self.doc()
        f_doc["schema"] = 1.0
        self.assertRejected(f_doc, "schema must be 1, found 1.0")

    def testRejectsFillAndPlaceholderRulesThatDoNotFit(self) -> None:
        """fill is nan or zero; placeholder rules copy settings, so they need fill zero."""
        f_doc = self.doc()
        f_doc["datasets"][0]["fill"] = "blank"
        self.assertRejected(f_doc, "fill 'blank' must be 'nan' or 'zero'")
        f_doc = self.doc()
        del f_doc["datasets"][0]["fill"]
        self.assertRejected(f_doc, "they need fill 'zero'")
        f_doc = self.doc()
        del f_doc["datasets"][0]["placeholders"]
        del f_doc["datasets"][0]["fill"]
        self.assertEqual(self.load(f_doc).datasets[0].fill, paperdata.FILL_NAN)

    def testRejectsOutputsThatAreNotFilesOrNestInEachOther(self) -> None:
        """An output must name a file, and one output cannot be the directory of another."""
        for f_output in (".", "sub/"):
            with self.subTest(f_output=f_output):
                f_doc = self.doc()
                f_doc["datasets"][0]["output"] = f_output
                del f_doc["figures"]
                self.assertRejected(f_doc, "must name a file")
        f_doc = self.doc()
        f_doc["datasets"].append({"output": "hdd", "kind": "lsmio", "source": "viking/c"})
        self.assertRejected(f_doc, "output hdd is a directory of output hdd/a.tsv")

    def testRejectsBadFigures(self) -> None:
        """Each field of a figure and its series is checked, including the dataset reference."""
        for f_change, f_text in [
            ({"y_divisor": 0}, "y_divisor must be a positive finite number"),
            ({"y_divisor": "1"}, "y_divisor must be a positive finite number"),
            ({"file": "f.png"}, "must end in .pdf"),
            ({"y_divisor": 10**400}, "y_divisor must be a positive finite number"),
            ({"series": []}, "series must be a non-empty list"),
            ({"series": ["x"]}, "must be an object"),
            ({"title": ""}, "'title' must be a non-empty string"),
        ]:
            with self.subTest(f_change=f_change):
                f_doc = self.doc()
                f_doc["figures"][0].update(f_change)
                self.assertRejected(f_doc, f_text)
        for f_change, f_text in [
            ({"dataset": "hdd/other.tsv"}, "is not the output of any dataset"),
            ({"stripes": "4"}, "stripes must be an integer"),
            ({"op": "append"}, "must be 'read' or 'write'"),
            ({"label": ""}, "'label' must be a non-empty string"),
        ]:
            with self.subTest(f_change=f_change):
                f_doc = self.doc()
                f_doc["figures"][0]["series"][0].update(f_change)
                self.assertRejected(f_doc, f_text)
        f_doc = self.doc()
        f_doc["figures"] = {}
        self.assertRejected(f_doc, "figures must be a list")
        f_doc = self.doc()
        f_doc["figures"] = ["x"]
        self.assertRejected(f_doc, "must be an object")


class PaperDataReadSeriesTest(unittest.TestCase):
    """readSeries: the points of one series of a TSV."""

    def testReturnsTheSeriesSortedByNodeCount(self) -> None:
        """Only the rows of the series' stripe count, block size and operation, by node count."""
        with tempfile.TemporaryDirectory() as f_dir:
            f_path = os.path.join(f_dir, "x.tsv")
            with open(f_path, "w", newline="") as f_file:
                f_file.write("Concurrency\tReplication\tBlock size\tAccess\tMax\r\n")
                for f_row in [
                    "10\t4\t64K\twrite\t300.00",
                    "2\t4\t64K\twrite\t200.00",
                    "2\t4\t64K\tread\t999.00",
                    "2\t16\t64K\twrite\t998.00",
                    "2\t4\t1M\twrite\t997.00",
                ]:
                    f_file.write(f_row + "\r\n")
            f_series = paperdata.SeriesSpec("L", "x.tsv", 4, "64K", "write")
            self.assertEqual(paperdata.readSeries(f_path, f_series), ([2, 10], [200.0, 300.0]))
            f_none = paperdata.SeriesSpec("L", "x.tsv", 4, "8M", "write")
            self.assertEqual(paperdata.readSeries(f_path, f_none), ([], []))

    def testMissingTsvIsAnError(self) -> None:
        """A TSV that 'latex data' has not written is reported."""
        f_series = paperdata.SeriesSpec("L", "x.tsv", 4, "64K", "write")
        with self.assertRaises(PaperDataError):
            paperdata.readSeries("/nonexistent/x.tsv", f_series)

    def testMalformedRowIsAnError(self) -> None:
        """A TSV row whose bandwidth is not a number is reported, not a traceback."""
        with tempfile.TemporaryDirectory() as f_dir:
            f_path = os.path.join(f_dir, "x.tsv")
            with open(f_path, "w", newline="") as f_file:
                f_file.write("2\t4\t64K\twrite\tfast\r\n")
            f_series = paperdata.SeriesSpec("L", "x.tsv", 4, "64K", "write")
            with self.assertRaises(PaperDataError) as f_ctx:
                paperdata.readSeries(f_path, f_series)
            self.assertIn("malformed row", str(f_ctx.exception))
            with open(f_path, "w", newline="") as f_file:
                f_file.write('2\t4\t"' + "x" * 200000 + "\r\n")
            with self.assertRaises(PaperDataError) as f_ctx:
                paperdata.readSeries(f_path, f_series)
            self.assertIn("malformed row", str(f_ctx.exception))


@unittest.skipUnless(_HAVE_YAML, _NO_YAML)
@unittest.skipUnless(
    os.path.isfile(os.path.join(_REPO_ROOT, "docs", "paper-journal", "sources.yaml"))
    and os.path.isdir(os.path.join(_REPO_ROOT, "lsmio-data", "synthetic", "viking")),
    "the paper's sources.yaml or the lsmio-data archive is not checked out",
)
class PaperDataGoldenTest(unittest.TestCase):
    """The paper's own sources.yaml reproduces the paper's TSVs byte for byte."""

    def testGeneratedTsvsEqualThePapersTsvs(self) -> None:
        """Every dataset of docs/paper-journal/sources.yaml regenerates its checked-in TSV."""
        f_paper = os.path.join(_REPO_ROOT, "docs", "paper-journal")
        f_sources = paperdata.loadSources(os.path.join(f_paper, "sources.yaml"))
        with tempfile.TemporaryDirectory() as f_out:
            with patch.object(paperdata.Console, "warning"):
                f_results = paperdata.generate(
                    f_sources, os.path.join(_REPO_ROOT, "lsmio-data", "synthetic"), f_out
                )
            self.assertEqual(len(f_results), 7)
            for f_result in f_results:
                f_name = f_result.spec.output
                with open(os.path.join(f_out, f_name), "rb") as f_new:
                    with open(os.path.join(f_paper, "data", f_name), "rb") as f_old:
                        self.assertEqual(f_new.read(), f_old.read(), f_name)

    def testTheFourMissingHdf5RunsAreThePlaceholders(self) -> None:
        """Only the HDF5 TSV has placeholders: the four runs that never completed."""
        f_paper = os.path.join(_REPO_ROOT, "docs", "paper-journal")
        f_sources = paperdata.loadSources(os.path.join(f_paper, "sources.yaml"))
        with tempfile.TemporaryDirectory() as f_out:
            with patch.object(paperdata.Console, "warning"):
                f_results = paperdata.generate(
                    f_sources, os.path.join(_REPO_ROOT, "lsmio-data", "synthetic"), f_out
                )
        f_gaps = {f_r.spec.output: f_r.placeholders for f_r in f_results if f_r.placeholders}
        self.assertEqual(
            f_gaps,
            {
                "hdd/ior/ior-report-hdf5.tsv": [
                    (16, 4, "8M", "read"),
                    (16, 4, "8M", "write"),
                    (24, 4, "64K", "read"),
                    (24, 16, "64K", "read"),
                ]
            },
        )


if __name__ == "__main__":
    unittest.main()
