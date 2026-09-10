#
# Copyright 2023 Serdar Bulut
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

import io
import os
import sys
import tempfile
import unittest
from unittest import TestCase
from unittest.mock import MagicMock, patch

from lsmiotool.lib import main, plot
from lsmiotool.lib.cli import CompareArchiveRequest, CompareVariantsRequest
from lsmiotool.lib.output import MissingDataError


def _writeSyntheticCsv(f_file_path: str, f_multiplier: float = 1.0) -> None:
    """Helper to write synthetic lsm-report.csv covering all 6 permutations."""
    content = [
        f"8,4,64K,read,{100.0 * f_multiplier},90.0,95.0,1000.0,1000,10",
        f"8,4,64K,write,{50.0 * f_multiplier},40.0,45.0,1000.0,1000,10",
        f"8,16,64K,read,{110.0 * f_multiplier},90.0,95.0,1000.0,1000,10",
        f"8,16,64K,write,{55.0 * f_multiplier},40.0,45.0,1000.0,1000,10",
        f"8,4,1M,read,{1000.0 * f_multiplier},900.0,950.0,2000.0,2000,10",
        f"8,4,1M,write,{500.0 * f_multiplier},400.0,450.0,2000.0,2000,10",
        f"8,16,1M,read,{1100.0 * f_multiplier},900.0,950.0,2000.0,2000,10",
        f"8,16,1M,write,{550.0 * f_multiplier},400.0,450.0,2000.0,2000,10",
        f"8,4,8M,read,{2000.0 * f_multiplier},1800.0,1900.0,4000.0,4000,10",
        f"8,4,8M,write,{1000.0 * f_multiplier},800.0,900.0,4000.0,4000,10",
        f"8,16,8M,read,{2200.0 * f_multiplier},1800.0,1900.0,4000.0,4000,10",
        f"8,16,8M,write,{1100.0 * f_multiplier},800.0,900.0,4000.0,4000,10",
    ]
    with open(f_file_path, "w") as f:
        f.write("\n".join(content) + "\n")


class CompareArchiveMainTest(TestCase):
    """Unit and functional test suite for CompareArchiveMain."""

    m_temp_dir: tempfile.TemporaryDirectory

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.m_temp_dir.cleanup()

    def testInitWithRequestAndDirectArgs(self) -> None:
        """Test construction with request object, direct keyword args, and positional args."""
        # 1. Construction with typed request
        req = CompareArchiveRequest(
            f_archive_folder="/path/to/archive",
            f_op="read",
            f_stripes=16,
            f_blocksize="8M",
            f_all=True,
            f_output_dir="/tmp/out",
        )
        cm_req = main.CompareArchiveMain(f_request=req)
        self.assertEqual(cm_req.request, req)
        self.assertEqual(cm_req.archive_folder, "/path/to/archive")
        self.assertEqual(cm_req.op, "read")
        self.assertEqual(cm_req.stripes, 16)
        self.assertEqual(cm_req.blocksize, "8M")
        self.assertTrue(cm_req.all)
        self.assertEqual(cm_req.output_dir, "/tmp/out")

        # 2. Construction with direct keyword arguments
        cm_direct = main.CompareArchiveMain(
            f_archive_folder="/path/to/archive2",
            f_op="write",
            f_stripes=4,
            f_blocksize="64K",
            f_all=False,
            f_output_dir="/tmp/out2",
        )
        self.assertEqual(cm_direct.archive_folder, "/path/to/archive2")
        self.assertEqual(cm_direct.op, "write")
        self.assertEqual(cm_direct.stripes, 4)
        self.assertEqual(cm_direct.blocksize, "64K")
        self.assertFalse(cm_direct.all)
        self.assertEqual(cm_direct.output_dir, "/tmp/out2")

        # 3. Construction with positional arguments
        cm_pos = main.CompareArchiveMain("/path/to/archive3", "read", 16, "1M")
        self.assertEqual(cm_pos.archive_folder, "/path/to/archive3")
        self.assertEqual(cm_pos.op, "read")
        self.assertEqual(cm_pos.stripes, 16)
        self.assertEqual(cm_pos.blocksize, "1M")
        self.assertFalse(cm_pos.all)
        self.assertIsNone(cm_pos.output_dir)

    def testResolveDirectory(self) -> None:
        """Test path resolution handling relative, absolute, and home-based paths."""
        cm = main.CompareArchiveMain(f_archive_folder="/path/to/archive")
        self.assertEqual(cm.resolveDirectory("/var/tmp"), "/var/tmp")
        self.assertEqual(
            cm.resolveDirectory("./sub"),
            os.path.abspath(os.path.join(os.getcwd(), "sub")),
        )
        self.assertEqual(
            cm.resolveDirectory("~/test_archive"),
            os.path.expanduser("~/test_archive"),
        )

    def testMissingArchiveFolderReturnsExitCode3(self) -> None:
        """Test that non-existent archive folder prints to stderr and returns exit code 3."""
        non_existent = os.path.join(self.m_temp_dir.name, "does_not_exist_xyz123")
        cm = main.CompareArchiveMain(f_archive_folder=non_existent)
        with patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
            ret = cm.run()
            self.assertEqual(ret, 3)
            self.assertIn(f"Archive folder not found: {non_existent}", mock_stderr.getvalue())

    def testEmptyOrNoVariantArchiveReturnsExitCode1(self) -> None:
        """Test that archive folder with no outputs-* subdirectories returns exit code 1."""
        empty_dir = os.path.join(self.m_temp_dir.name, "empty_archive")
        os.makedirs(empty_dir, exist_ok=True)
        # Add a non-matching directory
        os.makedirs(os.path.join(empty_dir, "not_outputs"), exist_ok=True)

        cm = main.CompareArchiveMain(f_archive_folder=empty_dir)
        with patch("lsmiotool.lib.log.Console.warning") as mock_warn:
            ret = cm.run()
            self.assertEqual(ret, 1)
            mock_warn.assert_called_with("No valid benchmark runs found in archive folder")

    def testParseOnDemandTriggeredWhenCsvMissing(self) -> None:
        """Test parse-on-demand is triggered when lsm-report.csv is missing."""
        archive_dir = os.path.join(self.m_temp_dir.name, "archive_parse_on_demand")
        variant_dir = os.path.join(archive_dir, "outputs-native")
        os.makedirs(variant_dir, exist_ok=True)
        out_dir = os.path.join(self.m_temp_dir.name, "plots")
        os.makedirs(out_dir, exist_ok=True)

        report_path = os.path.join(variant_dir, "lsm-report.csv")
        self.assertFalse(os.path.exists(report_path))

        def fakeGenerateReports(f_out_dir=None):
            _writeSyntheticCsv(report_path)

        with patch("lsmiotool.lib.output.LsmioAggOutput") as mock_agg_cls:
            mock_agg_instance = MagicMock()
            mock_agg_instance.generateReports.side_effect = fakeGenerateReports
            mock_agg_cls.return_value = mock_agg_instance

            cm = main.CompareArchiveMain(
                f_archive_folder=archive_dir,
                f_op="read",
                f_stripes=4,
                f_blocksize="1M",
                f_output_dir=out_dir,
            )
            ret = cm.run()
            self.assertEqual(ret, 0)
            mock_agg_cls.assert_called_once()
            mock_agg_instance.generateReports.assert_called_once()
            self.assertTrue(os.path.exists(report_path))

            expected_chart = os.path.join(
                out_dir, "compare-archive-archive_parse_on_demand-read-4-1M.png"
            )
            self.assertTrue(os.path.exists(expected_chart))
            self.assertGreater(os.path.getsize(expected_chart), 0)

    def testSkipCorruptedRuns(self) -> None:
        """Test that corrupted run raising MissingDataError is skipped while valid runs proceed."""
        archive_dir = os.path.join(self.m_temp_dir.name, "archive_corrupted")
        valid_dir = os.path.join(archive_dir, "outputs-native")
        corrupted_dir = os.path.join(archive_dir, "outputs-native-corrupted")
        os.makedirs(valid_dir, exist_ok=True)
        os.makedirs(corrupted_dir, exist_ok=True)

        _writeSyntheticCsv(os.path.join(valid_dir, "lsm-report.csv"))
        out_dir = os.path.join(self.m_temp_dir.name, "plots")

        def fakeAggOutput(f_dir, f_scale=None):
            if "corrupted" in f_dir:
                raise MissingDataError(f"Corrupted logs in {f_dir}")
            mock_inst = MagicMock()
            return mock_inst

        with patch("lsmiotool.lib.output.LsmioAggOutput", side_effect=fakeAggOutput):
            with patch("lsmiotool.lib.log.Console.warning") as mock_warn:
                cm = main.CompareArchiveMain(
                    f_archive_folder=archive_dir,
                    f_op="read",
                    f_stripes=4,
                    f_blocksize="1M",
                    f_output_dir=out_dir,
                )
                ret = cm.run()
                self.assertEqual(ret, 0)
                warning_messages = [str(call[0][0]) for call in mock_warn.call_args_list]
                self.assertTrue(
                    any("Failed to generate report for" in msg and "corrupted" in msg for msg in warning_messages)
                )
                expected_chart = os.path.join(
                    out_dir, "compare-archive-archive_corrupted-read-4-1M.png"
                )
                self.assertTrue(os.path.exists(expected_chart))

    def testAlphabeticalSortingAndSingleSeriesPlot(self) -> None:
        """Test variant labels are sorted alphabetically and MultiBarPlot receives single series."""
        archive_dir = os.path.join(self.m_temp_dir.name, "archive_sorting")
        v_footer = os.path.join(archive_dir, "outputs-native-footer")
        v_adios = os.path.join(archive_dir, "outputs-adios")
        v_default = os.path.join(archive_dir, "outputs-native")
        os.makedirs(v_footer, exist_ok=True)
        os.makedirs(v_adios, exist_ok=True)
        os.makedirs(v_default, exist_ok=True)

        _writeSyntheticCsv(os.path.join(v_footer, "lsm-report.csv"), 1.2)
        _writeSyntheticCsv(os.path.join(v_adios, "lsm-report.csv"), 0.8)
        _writeSyntheticCsv(os.path.join(v_default, "lsm-report.csv"), 1.0)

        out_dir = os.path.join(self.m_temp_dir.name, "plots")

        with patch("lsmiotool.lib.plot.MultiBarPlot") as mock_mbp:
            mock_instance = MagicMock()
            mock_mbp.return_value = mock_instance

            cm = main.CompareArchiveMain(
                f_archive_folder=archive_dir,
                f_op="read",
                f_stripes=4,
                f_blocksize="1M",
                f_output_dir=out_dir,
            )
            ret = cm.run()
            self.assertEqual(ret, 0)

            mock_mbp.assert_called_once()
            call_args = mock_mbp.call_args[0]
            # Must receive meta_data and exactly 1 PlotData series (INV-ARCH-8)
            self.assertEqual(len(call_args), 2)
            meta_data = call_args[0]
            plot_data = call_args[1]

            self.assertIsInstance(meta_data, plot.PlotMetaData)
            self.assertIsInstance(plot_data, plot.PlotData)
            self.assertEqual(plot_data.legend, "Read")

            # Must be strictly alphabetical: ['adios', 'default', 'footer'] (INV-ARCH-7)
            self.assertEqual(list(plot_data.x_series), ["adios", "default", "footer"])

    def testBothOperationGeneratesDualCharts(self) -> None:
        """Test op='both' generates both read and write comparison charts."""
        archive_dir = os.path.join(self.m_temp_dir.name, "archive_both")
        v_native = os.path.join(archive_dir, "outputs-native")
        os.makedirs(v_native, exist_ok=True)
        _writeSyntheticCsv(os.path.join(v_native, "lsm-report.csv"))

        out_dir = os.path.join(self.m_temp_dir.name, "plots")

        cm = main.CompareArchiveMain(
            f_archive_folder=archive_dir,
            f_op="both",
            f_stripes=4,
            f_blocksize="1M",
            f_output_dir=out_dir,
        )
        ret = cm.run()
        self.assertEqual(ret, 0)

        read_chart = os.path.join(out_dir, "compare-archive-archive_both-read-4-1M.png")
        write_chart = os.path.join(out_dir, "compare-archive-archive_both-write-4-1M.png")
        self.assertTrue(os.path.exists(read_chart), "Read chart must exist")
        self.assertTrue(os.path.exists(write_chart), "Write chart must exist")
        self.assertGreater(os.path.getsize(read_chart), 0)
        self.assertGreater(os.path.getsize(write_chart), 0)

    def testAllFlagGeneratesSixPermutations(self) -> None:
        """Test all=True generates charts across all 6 (stripes, blocksize) permutations."""
        archive_dir = os.path.join(self.m_temp_dir.name, "archive_all")
        v_native = os.path.join(archive_dir, "outputs-native")
        os.makedirs(v_native, exist_ok=True)
        _writeSyntheticCsv(os.path.join(v_native, "lsm-report.csv"))

        out_dir = os.path.join(self.m_temp_dir.name, "plots")

        cm = main.CompareArchiveMain(
            f_archive_folder=archive_dir,
            f_op="both",
            f_all=True,
            f_output_dir=out_dir,
        )
        ret = cm.run()
        self.assertEqual(ret, 0)

        permutations = [
            ("read", 4, "64K"),
            ("read", 16, "64K"),
            ("read", 4, "1M"),
            ("read", 16, "1M"),
            ("read", 4, "8M"),
            ("read", 16, "8M"),
            ("write", 4, "64K"),
            ("write", 16, "64K"),
            ("write", 4, "1M"),
            ("write", 16, "1M"),
            ("write", 4, "8M"),
            ("write", 16, "8M"),
        ]
        for op, stripes, bs in permutations:
            chart = os.path.join(
                out_dir, f"compare-archive-archive_all-{op}-{stripes}-{bs}.png"
            )
            self.assertTrue(os.path.exists(chart), f"Chart {chart} must exist")
            self.assertGreater(os.path.getsize(chart), 0)

    def testEndToEndAgainstSyntheticDataset(self) -> None:
        """Integration test against synthetic viking2 dataset if present."""
        dataset_path = "/home/sbulut/src/bulut/lsmio-data/synthetic/viking2/lsmio-2026-08-04"
        if not os.path.isdir(dataset_path):
            self.skipTest(f"Synthetic dataset {dataset_path} not found")

        out_dir = os.path.join(self.m_temp_dir.name, "plots")
        cm = main.CompareArchiveMain(
            f_archive_folder=dataset_path,
            f_op="both",
            f_stripes=4,
            f_blocksize="1M",
            f_output_dir=out_dir,
        )
        ret = cm.run()
        self.assertEqual(ret, 0)

        read_png = os.path.join(out_dir, "compare-archive-lsmio-2026-08-04-read-4-1M.png")
        write_png = os.path.join(out_dir, "compare-archive-lsmio-2026-08-04-write-4-1M.png")
        self.assertTrue(os.path.exists(read_png), f"{read_png} must exist")
        self.assertTrue(os.path.exists(write_png), f"{write_png} must exist")
        self.assertGreater(os.path.getsize(read_png), 0)
        self.assertGreater(os.path.getsize(write_png), 0)

    def testCompareMainPolymorphicDelegationToVariants(self) -> None:
        """Test CompareMain instantiated with CompareVariantsRequest delegates to CompareVariantsMain and executes run()."""
        archive_dir = os.path.join(self.m_temp_dir.name, "archive_poly")
        v_native = os.path.join(archive_dir, "outputs-native")
        os.makedirs(v_native, exist_ok=True)
        _writeSyntheticCsv(os.path.join(v_native, "lsm-report.csv"))

        out_dir = os.path.join(self.m_temp_dir.name, "plots_poly")

        req = CompareVariantsRequest(
            f_archive_folder=archive_dir,
            f_op="read",
            f_stripes=4,
            f_blocksize="1M",
            f_output_dir=out_dir,
        )
        cm = main.CompareMain(f_request=req)
        self.assertEqual(cm.submode, "variants")
        self.assertIsInstance(cm.m_delegate, main.CompareVariantsMain)
        ret = cm.run()
        self.assertEqual(ret, 0)

        expected_chart = os.path.join(
            out_dir, "compare-archive-archive_poly-read-4-1M.png"
        )
        self.assertTrue(os.path.exists(expected_chart))
        self.assertGreater(os.path.getsize(expected_chart), 0)

    def testCompareVariantsMainAlias(self) -> None:
        """Test CompareVariantsMain is identical to CompareArchiveMain alias."""
        self.assertIs(main.CompareArchiveMain, main.CompareVariantsMain)
        cm = main.CompareVariantsMain(f_archive_folder="/path/to/archive")
        self.assertIsInstance(cm, main.CompareArchiveMain)


if __name__ == "__main__":
    unittest.main()
