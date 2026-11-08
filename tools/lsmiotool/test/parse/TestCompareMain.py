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
from unittest.mock import patch

from lsmiotool.lib import main
from lsmiotool.lib.cli import CompareRequest


class TestCompareMain(unittest.TestCase):
    """Unit and functional tests for CompareMain command."""

    m_temp_dir: tempfile.TemporaryDirectory

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.m_temp_dir.cleanup()

    def _setupLsmioArchive(self, f_scale: str = "small") -> str:
        scale_dir = os.path.join(self.m_temp_dir.name, "archive", "backends", f_scale)
        native_dir = os.path.join(scale_dir, "outputs-native")
        os.makedirs(native_dir, exist_ok=True)
        report_file = os.path.join(native_dir, "lsm-report.csv")
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(
                "N,Stripes,BlockSize,Operation,Max(MiB),Min(MiB),Mean(MiB),StdDev,Max(OPs),Min(OPs),Mean(OPs),StdDev,Mean(s)\n"
                "1,4,1M,write,100.0,90.0,95.0,2.0,100,90,95,2,0.5\n"
                "1,4,1M,read,80.0,70.0,75.0,2.0,80,70,75,2,0.5\n"
                "2,4,1M,write,190.0,180.0,185.0,2.0,190,180,185,2,0.5\n"
                "2,4,1M,read,150.0,140.0,145.0,2.0,150,140,145,2,0.5\n"
            )
        return scale_dir

    def testInitTakesOnlyACompareRequest(self) -> None:
        """T18: CompareMain requires a CompareRequest and exposes .request; has no delegate or submode."""
        req = CompareRequest("lsmio", ("/tmp/bench",))
        cm = main.CompareMain(f_request=req)
        self.assertIs(cm.request, req)
        self.assertFalse(hasattr(cm, "delegate"))
        self.assertFalse(hasattr(cm, "submode"))

        with self.assertRaises(TypeError):
            main.CompareMain("f", "read")  # type: ignore
        with self.assertRaises(TypeError):
            main.CompareMain(f_request="x")  # type: ignore
        with self.assertRaises(TypeError):
            main.CompareMain(["nodes", "f", "read"])  # type: ignore

    def testMissingFolderExits3(self) -> None:
        """T4: Non-existent folder exits 3, names folder in error, creates no output dir."""
        missing = os.path.join(self.m_temp_dir.name, "does_not_exist")
        out_dir = os.path.join(self.m_temp_dir.name, "png_out")
        req = CompareRequest("lsmio", (missing,), f_output_dir=out_dir)
        cm = main.CompareMain(f_request=req)

        with patch("lsmiotool.lib.log.Console.error") as mock_err:
            code = cm.run()

        self.assertEqual(code, 3)
        mock_err.assert_called_once()
        self.assertIn(missing, mock_err.call_args[0][0])
        self.assertFalse(os.path.exists(out_dir))

    def testKindErrorExits1WithoutOutputDir(self) -> None:
        """T5: Folder of wrong benchmark kind exits 1, creates no output dir."""
        epocpp_dir = os.path.join(self.m_temp_dir.name, "epocpp_archive")
        os.makedirs(os.path.join(epocpp_dir, "outputs-epocpp-posix"), exist_ok=True)
        out_dir = os.path.join(self.m_temp_dir.name, "png_out")

        req = CompareRequest("lsmio", (epocpp_dir,), f_output_dir=out_dir)
        cm = main.CompareMain(f_request=req)

        with patch("lsmiotool.lib.log.Console.error") as mock_err:
            code = cm.run()

        self.assertEqual(code, 1)
        mock_err.assert_called_once()
        self.assertIn("not a lsmio folder", mock_err.call_args[0][0])
        self.assertFalse(os.path.exists(out_dir))

    def testSelectionErrorExits1WithoutOutputDir(self) -> None:
        """T6: Request with unavailable selection exits 1, creates no output dir."""
        scale_dir = self._setupLsmioArchive()
        out_dir = os.path.join(self.m_temp_dir.name, "png_out")

        req = CompareRequest("lsmio", (scale_dir,), f_nodes=(61,), f_output_dir=out_dir)
        cm = main.CompareMain(f_request=req)

        with patch("lsmiotool.lib.log.Console.error") as mock_err:
            code = cm.run()

        self.assertEqual(code, 1)
        mock_err.assert_called_once()
        self.assertIn("61", mock_err.call_args[0][0])
        self.assertFalse(os.path.exists(out_dir))

    def testNoDataExits1(self) -> None:
        """No data in admitted folder exits 1."""
        empty_dir = os.path.join(self.m_temp_dir.name, "empty_bench")
        os.makedirs(empty_dir, exist_ok=True)

        req = CompareRequest("lsmio", (empty_dir,))
        cm = main.CompareMain(f_request=req)

        with patch("lsmiotool.lib.log.Console.error") as mock_err:
            code = cm.run()

        self.assertEqual(code, 1)
        mock_err.assert_called_once()

    def testChartsWrittenAndLogged(self) -> None:
        """T7, T15, T9: Real plotting on lsmio fixture with --by nodes, combinations, and cwd fallback."""
        scale_dir = self._setupLsmioArchive()
        out_dir = os.path.join(self.m_temp_dir.name, "png", "x")
        self.assertFalse(os.path.exists(out_dir))

        # 1. Standard --by nodes
        req = CompareRequest("lsmio", (scale_dir,), f_output_dir=out_dir)
        cm = main.CompareMain(f_request=req)

        with patch("lsmiotool.lib.log.Console.info") as mock_info:
            ret = cm.run()

        self.assertEqual(ret, 0)
        self.assertTrue(os.path.isdir(out_dir))
        subdirs = [
            e for e in os.listdir(out_dir) if os.path.isdir(os.path.join(out_dir, e))
        ]
        self.assertEqual(subdirs, [])

        png_path = os.path.join(out_dir, "compare-small-lsmio-by-nodes.png")
        self.assertTrue(os.path.exists(png_path))
        self.assertGreater(os.path.getsize(png_path), 0)
        mock_info.assert_called_with(f"Comparison plot saved to {png_path}")

        # 2. --style lines --by combinations: one PNG per node count (1 and 2)
        comb_out = os.path.join(self.m_temp_dir.name, "png", "comb")
        req_comb = CompareRequest(
            "lsmio",
            (scale_dir,),
            f_by="combinations",
            f_style="lines",
            f_output_dir=comb_out,
        )
        ret_comb = main.CompareMain(f_request=req_comb).run()
        self.assertEqual(ret_comb, 0)
        png_1 = os.path.join(comb_out, "compare-small-lsmio-by-combinations-1.png")
        png_2 = os.path.join(comb_out, "compare-small-lsmio-by-combinations-2.png")
        self.assertTrue(os.path.exists(png_1))
        self.assertTrue(os.path.exists(png_2))
        self.assertGreater(os.path.getsize(png_1), 0)
        self.assertGreater(os.path.getsize(png_2), 0)

        # 3. No --output-dir: PNG goes to patched cwd
        cwd_dir = os.path.join(self.m_temp_dir.name, "cwd_test")
        os.makedirs(cwd_dir, exist_ok=True)
        req_cwd = CompareRequest("lsmio", (scale_dir,))
        with patch("os.getcwd", return_value=cwd_dir):
            ret_cwd = main.CompareMain(f_request=req_cwd).run()
        self.assertEqual(ret_cwd, 0)
        self.assertTrue(
            os.path.exists(os.path.join(cwd_dir, "compare-small-lsmio-by-nodes.png"))
        )

    def testOutputDirCannotBeCreatedExits1(self) -> None:
        """T16: Failure to create output directory exits 1 with error."""
        scale_dir = self._setupLsmioArchive()
        blocked_file = os.path.join(self.m_temp_dir.name, "blocked_file")
        with open(blocked_file, "w", encoding="utf-8") as f:
            f.write("data")
        out_dir = os.path.join(blocked_file, "out")

        req = CompareRequest("lsmio", (scale_dir,), f_output_dir=out_dir)
        with patch("lsmiotool.lib.log.Console.error") as mock_err:
            ret = main.CompareMain(f_request=req).run()

        self.assertEqual(ret, 1)
        mock_err.assert_called_once()
        self.assertIn("Cannot create the output directory", mock_err.call_args[0][0])

    def testPngNotSavedExits1KeepingEarlierPngs(self) -> None:
        """T16: Save failure on later PNG exits 1, keeping earlier PNGs."""
        scale_dir = self._setupLsmioArchive()
        out_dir = os.path.join(self.m_temp_dir.name, "png_collide")
        os.makedirs(out_dir, exist_ok=True)
        collide_path = os.path.join(
            out_dir, "compare-small-lsmio-by-combinations-2.png"
        )
        os.makedirs(collide_path, exist_ok=True)

        req = CompareRequest(
            "lsmio", (scale_dir,), f_by="combinations", f_output_dir=out_dir
        )
        with patch("lsmiotool.lib.log.Console.error") as mock_err:
            ret = main.CompareMain(f_request=req).run()

        self.assertEqual(ret, 1)
        mock_err.assert_called_once()
        self.assertIn(collide_path, mock_err.call_args[0][0])

        png_1 = os.path.join(out_dir, "compare-small-lsmio-by-combinations-1.png")
        self.assertTrue(os.path.exists(png_1))

    def testBrokenPointsOnlyStillWritesPngs(self) -> None:
        """T21, T9: All values broken still writes PNG with no_data; verifies style passed to ComparePanelPlot."""
        scale_dir = os.path.join(self.m_temp_dir.name, "archive", "backends", "broken")
        native_dir = os.path.join(scale_dir, "outputs-native")
        os.makedirs(native_dir, exist_ok=True)
        report_file = os.path.join(native_dir, "lsm-report.csv")
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(
                "N,Stripes,BlockSize,Operation,Max(MiB),Min(MiB),Mean(MiB),StdDev,Max(OPs),Min(OPs),Mean(OPs),StdDev,Mean(s)\n"
                "1,4,1M,write,abc,abc,abc,abc,abc,abc,abc,abc,abc\n"
                "1,4,1M,read,abc,abc,abc,abc,abc,abc,abc,abc,abc\n"
            )

        out_dir = os.path.join(self.m_temp_dir.name, "png_broken")
        req_default = CompareRequest("lsmio", (scale_dir,), f_output_dir=out_dir)

        # 1. Default style is "bars"; panels have no_data True
        with patch("lsmiotool.lib.plot.ComparePanelPlot") as mock_plot_cls:
            mock_plot_instance = mock_plot_cls.return_value
            mock_plot_instance.plot.return_value = None
            ret = main.CompareMain(f_request=req_default).run()
            self.assertEqual(ret, 0)
            self.assertTrue(mock_plot_cls.called)
            for call in mock_plot_cls.call_args_list:
                self.assertEqual(call[0][1], "bars")
                fig = call[0][0]
                for row in fig.grid:
                    for panel in row:
                        self.assertTrue(panel.no_data)

        # 2. Explicit style="lines" passes "lines" to ComparePanelPlot
        req_lines = CompareRequest(
            "lsmio", (scale_dir,), f_style="lines", f_output_dir=out_dir
        )
        with patch("lsmiotool.lib.plot.ComparePanelPlot") as mock_plot_cls:
            mock_plot_instance = mock_plot_cls.return_value
            mock_plot_instance.plot.return_value = None
            ret = main.CompareMain(f_request=req_lines).run()
            self.assertEqual(ret, 0)
            self.assertTrue(mock_plot_cls.called)
            for call in mock_plot_cls.call_args_list:
                self.assertEqual(call[0][1], "lines")


if __name__ == "__main__":
    unittest.main()
