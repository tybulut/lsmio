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
from typing import List, Optional
from unittest.mock import MagicMock, patch

from lsmiotool.lib import main, plot
from lsmiotool.lib.cli import CompareNodesRequest


class CompareNodesTest(unittest.TestCase):
    """Unit and functional verification suite for CompareNodesMain.

    Verifies:
    - Canonical legend mapping (INV-BACKEND-5).
    - Strict canonical sorting order [adios2, native, rocksdb] (INV-BACKEND-5).
    - Approach 2 mirrored output directory architecture (INV-BACKEND-4).
    - Workload parameter preservation and defaults (INV-BACKEND-5).
    - Strict Python 3.9+ type annotations (INV-BACKEND-6).
    """

    m_temp_dir: tempfile.TemporaryDirectory
    m_base_path: str

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.TemporaryDirectory()
        self.m_base_path = self.m_temp_dir.name

    def tearDown(self) -> None:
        self.m_temp_dir.cleanup()

    def _create_report(
        self,
        f_dir: str,
        f_stripes: int = 4,
        f_bs: str = "1M",
        f_op: str = "write",
        f_bw: float = 1200.0,
    ) -> str:
        """Create a synthetic lsm-report.csv with specified workload parameters."""
        os.makedirs(f_dir, exist_ok=True)
        report_file = os.path.join(f_dir, "lsm-report.csv")
        content = (
            "N,Stripes,BlockSize,Operation,Max(MiB),Min(MiB),Mean(MiB),StdDev,Max(OPs),Min(OPs),Mean(OPs),StdDev,Mean(s)\n"
            f"1,{f_stripes},{f_bs},{f_op},{f_bw},{f_bw * 0.9},{f_bw * 0.95},20.0,{f_bw},{f_bw * 0.9},{f_bw * 0.95},20.0,0.5\n"
            f"2,{f_stripes},{f_bs},{f_op},{f_bw * 1.8},{f_bw * 1.6},{f_bw * 1.7},40.0,{f_bw * 1.8},{f_bw * 1.6},{f_bw * 1.7},40.0,0.5\n"
        )
        with open(report_file, "w") as f:
            f.write(content)
        return report_file

    def testCanonicalLegendMapping(self) -> None:
        """Verifies directory names map to canonical legends ('adios2', 'native', 'rocksdb')."""
        target_dir = os.path.join(self.m_base_path, "archive", "backends", "small")
        self._create_report(os.path.join(target_dir, "outputs-adios"), 4, "1M", "write", 1000.0)
        self._create_report(os.path.join(target_dir, "outputs-native"), 4, "1M", "write", 1500.0)
        self._create_report(os.path.join(target_dir, "outputs-rocksdb"), 4, "1M", "write", 800.0)

        out_dir = os.path.join(self.m_base_path, "png")
        req = CompareNodesRequest(
            f_folder=target_dir,
            f_op="write",
            f_stripes=4,
            f_blocksize="1M",
            f_output_dir=out_dir,
        )
        cnm = main.CompareNodesMain(f_request=req)

        with patch("lsmiotool.lib.plot.MultiBarPlot") as mock_plot_cls:
            mock_plot_instance = MagicMock()
            mock_plot_cls.return_value = mock_plot_instance

            exit_code = cnm.run()
            self.assertEqual(exit_code, 0)
            mock_plot_cls.assert_called_once()

            args, _ = mock_plot_cls.call_args
            # First argument is PlotMetaData, subsequent arguments are PlotData objects
            meta_data: plot.PlotMetaData = args[0]
            plot_data_list: List[plot.PlotData] = list(args[1:])

            self.assertEqual(len(plot_data_list), 3)
            legends = [p.legend for p in plot_data_list]
            self.assertEqual(legends, ["adios2", "native", "rocksdb"])

    def testCanonicalSortingOrderScrambledInput(self) -> None:
        """Verifies plot data is sorted strictly in [adios2, native, rocksdb] order regardless of folder order."""
        target_dir = os.path.join(self.m_base_path, "archive", "backends", "bake")
        # Deliberately create in reverse order: rocksdb, native, adios
        self._create_report(os.path.join(target_dir, "outputs-rocksdb"), 4, "1M", "read", 700.0)
        self._create_report(os.path.join(target_dir, "outputs-native"), 4, "1M", "read", 1200.0)
        self._create_report(os.path.join(target_dir, "outputs-adios"), 4, "1M", "read", 950.0)

        out_dir = os.path.join(self.m_base_path, "png")
        cnm = main.CompareNodesMain(
            f_folder=target_dir,
            f_op="read",
            f_stripes=4,
            f_blocksize="1M",
            f_output_dir=out_dir,
        )

        with patch("lsmiotool.lib.plot.MultiBarPlot") as mock_plot_cls:
            mock_plot_instance = MagicMock()
            mock_plot_cls.return_value = mock_plot_instance

            exit_code = cnm.run()
            self.assertEqual(exit_code, 0)

            args, _ = mock_plot_cls.call_args
            plot_data_list: List[plot.PlotData] = list(args[1:])
            legends = [p.legend for p in plot_data_list]
            self.assertEqual(legends, ["adios2", "native", "rocksdb"])

    def testFallbackPatternMapping(self) -> None:
        """Verifies substring pattern matching for non-standard directory names containing backend keywords."""
        target_dir = os.path.join(self.m_base_path, "archive", "backends", "local")
        self._create_report(os.path.join(target_dir, "my-rocksdb-run"), 4, "1M", "write", 600.0)
        self._create_report(os.path.join(target_dir, "arm-adios"), 4, "1M", "write", 850.0)
        self._create_report(os.path.join(target_dir, "native"), 4, "1M", "write", 1100.0)

        out_dir = os.path.join(self.m_base_path, "png")
        cnm = main.CompareNodesMain(target_dir, "write", 4, "1M", out_dir)

        with patch("lsmiotool.lib.plot.MultiBarPlot") as mock_plot_cls:
            mock_plot_instance = MagicMock()
            mock_plot_cls.return_value = mock_plot_instance

            exit_code = cnm.run()
            self.assertEqual(exit_code, 0)

            args, _ = mock_plot_cls.call_args
            plot_data_list: List[plot.PlotData] = list(args[1:])
            legends = [p.legend for p in plot_data_list]
            self.assertEqual(legends, ["adios2", "native", "rocksdb"])

    def testApproach2PathMirroringBackends(self) -> None:
        """Verifies Approach 2 output path mirroring under <out_dir>/backends/<scale>/."""
        target_dir = os.path.join(self.m_base_path, "lsmio-archive", "backends", "small")
        self._create_report(os.path.join(target_dir, "outputs-adios"), 4, "1M", "write")
        self._create_report(os.path.join(target_dir, "outputs-native"), 4, "1M", "write")

        out_dir = os.path.join(self.m_base_path, "png")
        req = CompareNodesRequest(
            f_folder=target_dir,
            f_op="write",
            f_stripes=4,
            f_blocksize="1M",
            f_output_dir=out_dir,
        )
        cnm = main.CompareNodesMain(f_request=req)

        with patch("lsmiotool.lib.plot.MultiBarPlot") as mock_plot_cls:
            mock_plot_instance = MagicMock()
            mock_plot_cls.return_value = mock_plot_instance

            exit_code = cnm.run()
            self.assertEqual(exit_code, 0)

            expected_dir = os.path.join(out_dir, "backends", "small")
            expected_file = os.path.join(expected_dir, "compare-small-write-4-1M.png")

            self.assertTrue(os.path.isdir(expected_dir), f"Directory {expected_dir} must be created")
            mock_plot_instance.plot.assert_called_once_with(expected_file)

    def testApproach2PathMirroringVariants(self) -> None:
        """Verifies Approach 2 output path mirroring under <out_dir>/variants/."""
        target_dir = os.path.join(self.m_base_path, "lsmio-archive", "variants")
        self._create_report(os.path.join(target_dir, "native-variant-a"), 4, "1M", "read")
        self._create_report(os.path.join(target_dir, "native-variant-b"), 4, "1M", "read")

        out_dir = os.path.join(self.m_base_path, "png")
        req = CompareNodesRequest(
            f_folder=target_dir,
            f_op="read",
            f_stripes=4,
            f_blocksize="1M",
            f_output_dir=out_dir,
        )
        cnm = main.CompareNodesMain(f_request=req)

        with patch("lsmiotool.lib.plot.MultiBarPlot") as mock_plot_cls:
            mock_plot_instance = MagicMock()
            mock_plot_cls.return_value = mock_plot_instance

            exit_code = cnm.run()
            self.assertEqual(exit_code, 0)

            expected_dir = os.path.join(out_dir, "variants")
            expected_file = os.path.join(expected_dir, "compare-variants-read-4-1M.png")

            self.assertTrue(os.path.isdir(expected_dir), f"Directory {expected_dir} must be created")
            mock_plot_instance.plot.assert_called_once_with(expected_file)

    def testLegacyFlatArchivePathFallback(self) -> None:
        """Verifies legacy unpartitioned archives save directly to <out_dir>/ without subfolder."""
        target_dir = os.path.join(self.m_base_path, "legacy_archive_run")
        self._create_report(os.path.join(target_dir, "outputs-native"), 4, "1M", "write")

        out_dir = os.path.join(self.m_base_path, "custom_plots")
        req = CompareNodesRequest(
            f_folder=target_dir,
            f_op="write",
            f_stripes=4,
            f_blocksize="1M",
            f_output_dir=out_dir,
        )
        cnm = main.CompareNodesMain(f_request=req)

        with patch("lsmiotool.lib.plot.MultiBarPlot") as mock_plot_cls:
            mock_plot_instance = MagicMock()
            mock_plot_cls.return_value = mock_plot_instance

            exit_code = cnm.run()
            self.assertEqual(exit_code, 0)

            expected_file = os.path.join(out_dir, "compare-legacy_archive_run-write-4-1M.png")
            self.assertTrue(os.path.isdir(out_dir))
            mock_plot_instance.plot.assert_called_once_with(expected_file)

    def testWorkloadParameterPreservationAndDefaults(self) -> None:
        """Verifies default workload parameters (stripes=4, bs=1M) and custom values."""
        target_dir = os.path.join(self.m_base_path, "archive", "backends", "large")
        self._create_report(os.path.join(target_dir, "outputs-adios"), 4, "1M", "write")
        self._create_report(os.path.join(target_dir, "outputs-native"), 4, "1M", "write")

        # 1. Defaults: stripes=4, bs=1M
        cnm_default = main.CompareNodesMain(f_folder=target_dir, f_op="write")
        self.assertEqual(cnm_default.stripes, 4)
        self.assertEqual(cnm_default.bs, "1M")
        self.assertEqual(cnm_default.blocksize, "1M")

        with patch("lsmiotool.lib.plot.MultiBarPlot") as mock_plot_cls, patch("os.getcwd", return_value=self.m_base_path):
            mock_plot_instance = MagicMock()
            mock_plot_cls.return_value = mock_plot_instance

            exit_code = cnm_default.run()
            self.assertEqual(exit_code, 0)

            args, _ = mock_plot_cls.call_args
            meta_data: plot.PlotMetaData = args[0]
            self.assertIn("4 stripes", meta_data.title)
            self.assertIn("1M", meta_data.title)
            self.assertIn("WRITE", meta_data.title)

        # 2. Custom parameters: stripes=16, bs=8M, op=read
        self._create_report(os.path.join(target_dir, "outputs-adios"), 16, "8M", "read")
        self._create_report(os.path.join(target_dir, "outputs-native"), 16, "8M", "read")

        out_dir = os.path.join(self.m_base_path, "custom_out")
        cnm_custom = main.CompareNodesMain(
            f_folder=target_dir,
            f_op="read",
            f_stripes=16,
            f_blocksize="8M",
            f_output_dir=out_dir,
        )
        self.assertEqual(cnm_custom.stripes, 16)
        self.assertEqual(cnm_custom.bs, "8M")

        with patch("lsmiotool.lib.plot.MultiBarPlot") as mock_plot_cls:
            mock_plot_instance = MagicMock()
            mock_plot_cls.return_value = mock_plot_instance

            exit_code = cnm_custom.run()
            self.assertEqual(exit_code, 0)

            args, _ = mock_plot_cls.call_args
            meta_data = args[0]
            self.assertIn("16 stripes", meta_data.title)
            self.assertIn("8M", meta_data.title)
            self.assertIn("READ", meta_data.title)

            expected_file = os.path.join(out_dir, "backends", "large", "compare-large-read-16-8M.png")
            mock_plot_instance.plot.assert_called_once_with(expected_file)

    def testEndToEndPlotFileGeneration(self) -> None:
        """Functional end-to-end test verifying actual image file creation on disk without mock."""
        target_dir = os.path.join(self.m_base_path, "archive", "backends", "bake")
        self._create_report(os.path.join(target_dir, "outputs-adios"), 4, "1M", "write", 1100.0)
        self._create_report(os.path.join(target_dir, "outputs-native"), 4, "1M", "write", 1400.0)
        self._create_report(os.path.join(target_dir, "outputs-rocksdb"), 4, "1M", "write", 950.0)

        out_dir = os.path.join(self.m_base_path, "png")
        req = CompareNodesRequest(
            f_folder=target_dir,
            f_op="write",
            f_stripes=4,
            f_blocksize="1M",
            f_output_dir=out_dir,
        )
        cnm = main.CompareNodesMain(f_request=req)
        exit_code = cnm.run()
        self.assertEqual(exit_code, 0)

        expected_png = os.path.join(out_dir, "backends", "bake", "compare-bake-write-4-1M.png")
        self.assertTrue(os.path.isfile(expected_png), f"Generated plot {expected_png} must exist on disk")
        self.assertGreater(os.path.getsize(expected_png), 0, "Generated plot file must not be empty")

    def testMissingDirectoryExitsWithError(self) -> None:
        """Verifies non-existent directory causes system exit with code 1."""
        non_existent_dir = os.path.join(self.m_base_path, "does_not_exist_xyz")
        cnm = main.CompareNodesMain(non_existent_dir, "read")
        with self.assertRaises(SystemExit) as cm:
            cnm.run()
        self.assertEqual(cm.exception.code, 1)

    def testNoBenchmarkDataReturnsZero(self) -> None:
        """Verifies directory with empty subdirectories returns 0 with warning."""
        empty_dir = os.path.join(self.m_base_path, "archive", "backends", "empty_scale")
        os.makedirs(os.path.join(empty_dir, "outputs-empty"), exist_ok=True)

        cnm = main.CompareNodesMain(empty_dir, "read", 4, "1M")
        with patch("lsmiotool.lib.log.Console.warning") as mock_warn:
            exit_code = cnm.run()
            self.assertEqual(exit_code, 0)
            mock_warn.assert_called_once()


if __name__ == "__main__":
    unittest.main()
