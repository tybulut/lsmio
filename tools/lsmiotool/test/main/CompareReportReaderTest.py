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

import ast
import csv
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import lsmiotool
from lsmiotool.lib import epocppreport
from lsmiotool.lib.compare import (
    CompareDataset,
    CompareError,
    CompareFigure,
    CompareFolderError,
    CompareKindError,
    CompareNoDataError,
    ComparePanel,
    ComparePng,
    ComparePoints,
    CompareReportError,
    CompareReportReader,
    CompareSelectionError,
    CompareSeries,
    warningLine,
)


class CompareReportReaderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.m_tmp_dir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.m_tmp_dir, ignore_errors=True)

    def testLsmReportFiniteValues(self) -> None:
        f_path = os.path.join(self.m_tmp_dir, "lsm_finite.csv")
        with open(f_path, "w", encoding="utf-8") as f_f:
            f_f.write("N,Stripes,BlockSize,Operation,Max(MiB)\n")
            f_f.write("01,4,64K,write,100.5\n")
            f_f.write("1,4,64K,read,200.5\n")
            f_f.write("2,16,1M,write,300.5\n")
            f_f.write("2,16,1M,read,400.5\n")
            f_f.write("1,4,64K,write,150.5\n")
            f_f.write("1,4,64K\n")
            f_f.write("\n")
            f_f.write("1,8,1M,write,500.0\n")
            f_f.write("1,4,2M,write,600.0\n")

        f_pts = CompareReportReader.readLsmReport(f_path)
        self.assertEqual(f_pts.unreadable_rows, 0)
        self.assertIsNone(warningLine(f_pts))
        f_expected = {
            ("", "write", 1, 4, "64K"): 150.5,
            ("", "read", 1, 4, "64K"): 200.5,
            ("", "write", 2, 16, "1M"): 300.5,
            ("", "read", 2, 16, "1M"): 400.5,
        }
        self.assertEqual(f_pts.values, f_expected)

    def testLsmReportBrokenValues(self) -> None:
        f_cases = (
            "",
            "abc",
            "NA",
            "nan",
            "N/A",
            "NULL",
            "none",
            "inf",
            "-inf",
            None,
        )
        for f_idx, f_cell in enumerate(f_cases):
            with self.subTest(cell=f_cell):
                f_path = os.path.join(self.m_tmp_dir, f"broken_{f_idx}.csv")
                with open(f_path, "w", encoding="utf-8") as f_f:
                    f_f.write("2,4,64K,read,123.45\n")
                    if f_cell is None:
                        f_f.write("2,4,1M,write\n")
                    else:
                        f_f.write(f"2,4,1M,write,{f_cell}\n")
                f_pts = CompareReportReader.readLsmReport(f_path)
                self.assertTrue(math.isnan(f_pts.values[("", "write", 2, 4, "1M")]))
                self.assertEqual(f_pts.values[("", "read", 2, 4, "64K")], 123.45)
                f_warn = warningLine(f_pts)
                self.assertIsNotNone(f_warn)
                self.assertIn(f_path, f_warn)
                self.assertIn("1 broken value(s)", f_warn)
                self.assertIn("write 4/1M N=2", f_warn)

    def testLsmReportUnreadableRows(self) -> None:
        f_path = os.path.join(self.m_tmp_dir, "unreadable_rows.csv")
        with open(f_path, "w", encoding="utf-8") as f_f:
            f_f.write("x,4,64K,write,100\n")
            f_f.write("0,4,64K,write,100\n")
            f_f.write("1.5,4,64K,write,100\n")
            f_f.write("1e1,4,64K,write,100\n")
            f_f.write("-1,4,64K,write,100\n")
            f_f.write(",4,64K,write,100\n")
            f_f.write("2,four,64K,write,100\n")
            f_f.write("2,4,,write,100\n")
            f_f.write("x,4,64K,speed,100\n")
        f_pts = CompareReportReader.readLsmReport(f_path)
        self.assertEqual(f_pts.unreadable_rows, 8)
        self.assertEqual(len(f_pts.values), 0)
        f_warn = warningLine(f_pts)
        self.assertIsNotNone(f_warn)
        self.assertIn("8 unreadable row(s) left out", f_warn)
        self.assertNotIn("broken", f_warn)

    def testZeroAndNegativeValuesAreFinite(self) -> None:
        self.assertEqual(CompareReportReader.valueOf("0.0"), 0.0)
        self.assertEqual(CompareReportReader.valueOf("0"), 0.0)
        self.assertEqual(CompareReportReader.valueOf("-5.0"), -5.0)
        self.assertFalse(math.isnan(CompareReportReader.valueOf("0.0")))
        self.assertFalse(math.isnan(CompareReportReader.valueOf("-5.0")))

    def testUnreadableReports(self) -> None:
        f_missing = os.path.join(self.m_tmp_dir, "missing.csv")
        f_dir = os.path.join(self.m_tmp_dir, "is_a_dir")
        os.makedirs(f_dir, exist_ok=True)

        f_bad_bytes = os.path.join(self.m_tmp_dir, "bad_bytes.csv")
        with open(f_bad_bytes, "wb") as f_f:
            f_f.write(b"\xff\xfe\x00bad")

        f_large_field = os.path.join(self.m_tmp_dir, "large_field.csv")
        with open(f_large_field, "w", encoding="utf-8") as f_f:
            f_f.write("a" * 131073 + "\n")

        f_unknown_arm = os.path.join(self.m_tmp_dir, "unknown_arm.csv")
        with open(f_unknown_arm, "w", encoding="utf-8") as f_f:
            f_f.write("Col1,Col2,Col3\n1,2,3\n")

        f_cost_with_arm_header = os.path.join(self.m_tmp_dir, "cost_arm_hdr.csv")
        with open(f_cost_with_arm_header, "w", encoding="utf-8") as f_f:
            f_f.write(",".join(epocppreport.REPORT_HEADER) + "\n")

        f_cases = (
            (CompareReportReader.readLsmReport, f_missing, FileNotFoundError),
            (CompareReportReader.readLsmReport, f_dir, IsADirectoryError),
            (CompareReportReader.readLsmReport, f_bad_bytes, UnicodeDecodeError),
            (CompareReportReader.readLsmReport, f_large_field, csv.Error),
            (
                CompareReportReader.readEpocppArmReport,
                f_unknown_arm,
                ValueError,
            ),
            (
                CompareReportReader.readEpocppCostReport,
                f_cost_with_arm_header,
                ValueError,
            ),
        )
        for f_reader, f_path, f_expected_cause in f_cases:
            with self.subTest(reader=f_reader.__name__, path=f_path):
                with self.assertRaises(CompareReportError) as f_cm:
                    f_reader(f_path)
                self.assertEqual(f_cm.exception.path, f_path)
                self.assertIsInstance(f_cm.exception.cause, f_expected_cause)

    def testEpocppArmReportValues(self) -> None:
        f_path_full = os.path.join(self.m_tmp_dir, "arm_full.csv")
        f_path_legacy = os.path.join(self.m_tmp_dir, "arm_legacy.csv")
        f_data_rows = [
            ("1", "4", "64K", "runtime", "12.5"),
            ("1", "4", "64K", "write", "350.0"),
            ("1", "4", "64K", "read", "450.0"),
        ]
        with open(f_path_full, "w", encoding="utf-8") as f_f:
            f_f.write(",".join(epocppreport.REPORT_HEADER) + "\n")
            for f_row in f_data_rows:
                f_full_row = list(f_row) + [""] * 8
                f_f.write(",".join(f_full_row) + "\n")

        with open(f_path_legacy, "w", encoding="utf-8") as f_f:
            f_f.write(",".join(epocppreport._LEGACY_REPORT_HEADER) + "\n")
            for f_row in f_data_rows:
                f_leg_row = list(f_row) + [""] * 6
                f_f.write(",".join(f_leg_row) + "\n")

        f_pts_full = CompareReportReader.readEpocppArmReport(f_path_full)
        f_pts_legacy = CompareReportReader.readEpocppArmReport(f_path_legacy)
        self.assertEqual(f_pts_full.values, f_pts_legacy.values)
        self.assertEqual(f_pts_full.unreadable_rows, 0)
        self.assertEqual(f_pts_legacy.unreadable_rows, 0)
        self.assertEqual(f_pts_full.values[("", "runtime", 1, 4, "64K")], 12.5)
        self.assertEqual(f_pts_full.values[("", "write", 1, 4, "64K")], 350.0)
        self.assertEqual(f_pts_full.values[("", "read", 1, 4, "64K")], 450.0)

        f_path_edge = os.path.join(self.m_tmp_dir, "arm_edge.csv")
        with open(f_path_edge, "w", encoding="utf-8") as f_f:
            f_f.write(",".join(epocppreport.REPORT_HEADER) + "\n")
            f_f.write("1,4,64K,other,99.9\n")
            f_f.write("2,4,64K,runtime,\n")
            f_f.write("2,4,1M,runtime,abc\n")
            f_f.write("2,4,8M,runtime,inf\n")
            f_f.write("1,16,64K,runtime\n")
            f_f.write("x,4,64K,runtime,10.0\n")
            f_f.write("x,4,64K,other,10.0\n")

        f_pts_edge = CompareReportReader.readEpocppArmReport(f_path_edge)
        self.assertNotIn(("", "other", 1, 4, "64K"), f_pts_edge.values)
        self.assertTrue(math.isnan(f_pts_edge.values[("", "runtime", 2, 4, "64K")]))
        self.assertTrue(math.isnan(f_pts_edge.values[("", "runtime", 2, 4, "1M")]))
        self.assertTrue(math.isnan(f_pts_edge.values[("", "runtime", 2, 4, "8M")]))
        self.assertTrue(math.isnan(f_pts_edge.values[("", "runtime", 1, 16, "64K")]))
        self.assertEqual(f_pts_edge.unreadable_rows, 1)

    def testEpocppCostReportValues(self) -> None:
        f_path = os.path.join(self.m_tmp_dir, "cost.csv")
        with open(f_path, "w", encoding="utf-8") as f_f:
            f_f.write(",".join(epocppreport.COST_HEADER) + "\n")
            f_f.write("1,4,64K,posix,10.0,12.0,-2.0\n")
            f_f.write("2,4,1M,adios2,15.0,10.0,abc\n")
            f_f.write("x,4,8M,plugin,20.0,10.0,10.0\n")
            f_f.write("1,16,64K,,10.0,10.0,0.0\n")

        f_pts = CompareReportReader.readEpocppCostReport(f_path)
        self.assertIn(("posix", "cost", 1, 4, "64K"), f_pts.values)
        self.assertEqual(f_pts.values[("posix", "cost", 1, 4, "64K")], -2.0)
        self.assertTrue(math.isnan(f_pts.values[("adios2", "cost", 2, 4, "1M")]))
        self.assertEqual(f_pts.unreadable_rows, 1)
        self.assertNotIn(("", "cost", 1, 16, "64K"), f_pts.values)
        f_warn = warningLine(f_pts)
        self.assertIsNotNone(f_warn)
        self.assertIn("adios2 cost 4/1M N=2", f_warn)

    def testWarningLineTruncatesLongKeyLists(self) -> None:
        f_values = {}
        for f_n in range(1, 16):
            f_values[("", "write", f_n, 4, "64K")] = math.nan
        f_pts = ComparePoints(
            path="/tmp/fake.csv",
            values=f_values,
            unreadable_rows=0,
        )
        f_warn = warningLine(f_pts)
        self.assertIsNotNone(f_warn)
        self.assertNotIn("\n", f_warn)
        self.assertIn("15 broken value(s) drawn as gaps", f_warn)
        self.assertIn("(+5 more)", f_warn)

    def testFigureSpecAndErrorTypes(self) -> None:
        self.assertEqual(CompareSeries._fields, ("label", "colour"))
        self.assertEqual(
            ComparePanel._fields,
            (
                "title",
                "y_label",
                "values",
                "no_data",
                "zero_line",
                "value_labels",
            ),
        )
        self.assertEqual(
            CompareFigure._fields,
            (
                "title",
                "x_label",
                "x_categories",
                "grid",
                "series",
                "legend",
            ),
        )
        self.assertEqual(ComparePng._fields, ("path", "figure"))
        self.assertEqual(CompareDataset._fields, ("output_dir", "pngs"))

        self.assertTrue(issubclass(CompareFolderError, CompareError))
        self.assertTrue(issubclass(CompareKindError, CompareError))
        self.assertTrue(issubclass(CompareSelectionError, CompareError))
        self.assertTrue(issubclass(CompareNoDataError, CompareError))

        f_err = CompareReportError("/path/to/file.csv", ValueError("corrupt"))
        self.assertIn("/path/to/file.csv", str(f_err))
        self.assertIn("ValueError", str(f_err))
        self.assertIn("corrupt", str(f_err))
        self.assertEqual(f_err.path, "/path/to/file.csv")
        self.assertIsInstance(f_err.cause, ValueError)

    def testCompareModuleImportsNoMatplotlib(self) -> None:
        import lsmiotool.lib.compare as comp_mod

        f_compare_file = comp_mod.__file__
        with open(f_compare_file, "r", encoding="utf-8") as f_f:
            f_tree = ast.parse(f_f.read(), filename=f_compare_file)

        for f_node in ast.walk(f_tree):
            if isinstance(f_node, ast.Import):
                for f_alias in f_node.names:
                    self.assertNotIn("matplotlib", f_alias.name)
                    self.assertNotIn("lsmiotool.lib.plot", f_alias.name)
            elif isinstance(f_node, ast.ImportFrom) and f_node.module:
                self.assertNotIn("matplotlib", f_node.module)
                self.assertNotIn("lsmiotool.lib.plot", f_node.module)

        f_tools_dir = os.path.dirname(
            os.path.dirname(os.path.abspath(lsmiotool.__file__))
        )
        f_env = dict(os.environ)
        f_env["MPLBACKEND"] = "Agg"
        f_proc = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; import lsmiotool.lib.compare; "
                    "print('matplotlib' in sys.modules, 'lsmiotool.lib.plot' in sys.modules)"
                ),
            ],
            cwd=f_tools_dir,
            env=f_env,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(f_proc.stdout.strip(), "False False")


if __name__ == "__main__":
    unittest.main()
