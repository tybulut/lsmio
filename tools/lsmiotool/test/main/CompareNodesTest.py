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
from lsmiotool.lib.cli import CompareNodesRequest, parseCompareArguments


class CompareNodesTest(unittest.TestCase):
    """Unit and functional verification suite for CompareNodesMain.

    Verifies:
    - Canonical legend mapping (INV-BACKEND-5).
    - Strict canonical sorting order [adios2, native, plugin, rocksdb] (INV-BACKEND-5).
    - Plots written straight into the output directory, named by scale.
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
        self._create_report(
            os.path.join(target_dir, "outputs-adios"), 4, "1M", "write", 1000.0
        )
        self._create_report(
            os.path.join(target_dir, "outputs-native"), 4, "1M", "write", 1500.0
        )
        self._create_report(
            os.path.join(target_dir, "outputs-rocksdb"), 4, "1M", "write", 800.0
        )

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
        """Verifies plot data is sorted strictly in [adios2, native, plugin, rocksdb, leveldb] order regardless of folder order."""
        target_dir = os.path.join(self.m_base_path, "archive", "backends", "bake")
        # Deliberately create in reverse order: leveldb, rocksdb, plugin, native, adios
        self._create_report(
            os.path.join(target_dir, "outputs-leveldb"), 4, "1M", "read", 500.0
        )
        self._create_report(
            os.path.join(target_dir, "outputs-rocksdb"), 4, "1M", "read", 700.0
        )
        self._create_report(
            os.path.join(target_dir, "outputs-plugin"), 4, "1M", "read", 1100.0
        )
        self._create_report(
            os.path.join(target_dir, "outputs-native"), 4, "1M", "read", 1200.0
        )
        self._create_report(
            os.path.join(target_dir, "outputs-adios"), 4, "1M", "read", 950.0
        )

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
            self.assertEqual(
                legends, ["adios2", "native", "plugin", "rocksdb", "leveldb"]
            )

    def testSyncArmsPlottedAfterTheirBackends(self) -> None:
        """outputs-<backend>-sync folders are labelled <backend>-sync (adios2-sync for
        outputs-adios-sync), not folded into their backend, and each is plotted right after
        its backend."""
        target_dir = os.path.join(self.m_base_path, "archive", "backends", "bake")
        for f_arm, f_bw in (
            ("leveldb-sync", 400.0),
            ("rocksdb-sync", 600.0),
            ("plugin-sync", 1000.0),
            ("native-sync", 1150.0),
            ("adios-sync", 900.0),
            ("rocksdb", 700.0),
            ("plugin", 1100.0),
            ("native", 1200.0),
            ("adios", 950.0),
        ):
            self._create_report(
                os.path.join(target_dir, f"outputs-{f_arm}"), 4, "1M", "write", f_bw
            )
        cnm = main.CompareNodesMain(
            f_folder=target_dir,
            f_op="write",
            f_stripes=4,
            f_blocksize="1M",
            f_output_dir=os.path.join(self.m_base_path, "png"),
        )
        with patch("lsmiotool.lib.plot.MultiBarPlot") as mock_plot_cls:
            mock_plot_cls.return_value = MagicMock()
            self.assertEqual(cnm.run(), 0)
            args, _ = mock_plot_cls.call_args
            self.assertEqual(
                [p.legend for p in args[1:]],
                [
                    "adios2",
                    "adios2-sync",
                    "native",
                    "native-sync",
                    "plugin",
                    "plugin-sync",
                    "rocksdb",
                    "rocksdb-sync",
                    "leveldb-sync",
                ],
            )

    def testSyncArmsWithSuffixAndIorArms(self) -> None:
        """A collision-suffixed -sync folder keeps its -sync label, and IOR arms charted
        alongside come after every backend, the -sync arms included."""
        from lsmiotool.test.main.ArmGroupTest import IOR_SUMMARY

        target_dir = os.path.join(self.m_base_path, "archive", "backends", "small")
        for f_arm in ("plugin-sync-1", "rocksdb-sync-2", "adios-sync", "native"):
            self._create_report(
                os.path.join(target_dir, f"outputs-{f_arm}"), 4, "1M", "write", 1000.0
            )
        f_day = os.path.join(target_dir, "outputs-ior", "2", "2026-10-14")
        os.makedirs(f_day)
        with open(
            os.path.join(f_day, "out-base-4-1M-2026-10-14-node097-0.txt"), "w"
        ) as f_f:
            f_f.write(IOR_SUMMARY)
        cnm = main.CompareNodesMain(
            f_folder=target_dir,
            f_op="write",
            f_stripes=4,
            f_blocksize="1M",
            f_output_dir=os.path.join(self.m_base_path, "png"),
        )
        with patch("lsmiotool.lib.plot.MultiBarPlot") as mock_plot_cls:
            mock_plot_cls.return_value = MagicMock()
            self.assertEqual(cnm.run(), 0)
            args, _ = mock_plot_cls.call_args
            self.assertEqual(
                [p.legend for p in args[1:]],
                ["adios2-sync", "native", "plugin-sync", "rocksdb-sync", "ior"],
            )

    def testIorArmsPlottedAfterBackends(self) -> None:
        """IOR arms in an archive folder are charted from ior-report.csv (built
        from their bmtool-layout outputs when missing), after the backends, by arm."""
        from lsmiotool.test.main.ArmGroupTest import IOR_SUMMARY

        target_dir = os.path.join(self.m_base_path, "archive", "backends", "small")
        self._create_report(
            os.path.join(target_dir, "outputs-native"), 4, "1M", "write", 1500.0
        )
        for f_arm, f_infix in (
            ("ior-hdf5-collective", "hdf5-c"),
            ("ior", "base"),
            ("ior-collective", "collective"),
        ):
            f_day = os.path.join(target_dir, f"outputs-{f_arm}", "2", "2026-10-14")
            os.makedirs(f_day)
            with open(
                os.path.join(f_day, f"out-{f_infix}-4-1M-2026-10-14-node097-0.txt"), "w"
            ) as f_f:
                f_f.write(IOR_SUMMARY)

        cnm = main.CompareNodesMain(
            f_folder=target_dir,
            f_op="write",
            f_stripes=4,
            f_blocksize="1M",
            f_output_dir=os.path.join(self.m_base_path, "png"),
        )
        with patch("lsmiotool.lib.plot.MultiBarPlot") as mock_plot_cls:
            mock_plot_cls.return_value = MagicMock()
            self.assertEqual(cnm.run(), 0)
            args, _ = mock_plot_cls.call_args
            f_series = {p.legend: p for p in args[1:]}
            self.assertEqual(
                [p.legend for p in args[1:]],
                ["native", "ior", "ior-collective", "ior-hdf5-collective"],
            )
            self.assertEqual(list(f_series["ior"].x_series), [2])
            self.assertEqual(list(f_series["ior"].y_series), [1650.38])
        for f_arm in ("ior", "ior-collective", "ior-hdf5-collective"):
            f_dir = os.path.join(target_dir, f"outputs-{f_arm}")
            self.assertTrue(os.path.isfile(os.path.join(f_dir, "ior-report.csv")))
            # Never aggregated as LSMIO rank logs
            self.assertFalse(os.path.exists(os.path.join(f_dir, "lsm-report.csv")))

    def testIorFolderAloneNamedApart(self) -> None:
        """A folder of IOR setups alone (lsmio-archive/ior/<scale>) names its charts
        compare-<scale>-ior-*, never those of the backends of that scale."""
        from lsmiotool.test.main.ArmGroupTest import IOR_SUMMARY

        f_archive = os.path.join(self.m_base_path, "archive")
        f_ior = os.path.join(f_archive, "ior", "small")
        f_day = os.path.join(f_ior, "outputs-ior", "2", "2026-10-14")
        os.makedirs(f_day)
        with open(
            os.path.join(f_day, "out-base-4-1M-2026-10-14-node097-0.txt"), "w"
        ) as f_f:
            f_f.write(IOR_SUMMARY)
        self._create_report(
            os.path.join(f_archive, "backends", "small", "outputs-native"),
            4,
            "1M",
            "write",
            1500.0,
        )
        f_out = os.path.join(self.m_base_path, "png")
        for f_folder, f_name, f_title in (
            (f_ior, "compare-small-ior-write-4-1M.png", "Comparison: small, ior ("),
            (
                os.path.join(f_archive, "backends", "small"),
                "compare-small-write-4-1M.png",
                "Comparison: small (",
            ),
        ):
            with patch("lsmiotool.lib.plot.MultiBarPlot") as mock_plot_cls:
                mock_plot_cls.return_value = MagicMock()
                main.CompareNodesMain(
                    f_folder=f_folder, f_op="write", f_output_dir=f_out
                ).run()
                args, _ = mock_plot_cls.call_args
                self.assertTrue(args[0].title.startswith(f_title), args[0].title)
                mock_plot_cls.return_value.plot.assert_called_once_with(
                    os.path.join(f_out, f_name)
                )

    def testReportTriedOncePerRun(self) -> None:
        """--all builds a missing report once per folder, not once per chart, and the
        "no benchmark data" warning names every folder."""
        f_backends = os.path.join(self.m_base_path, "archive", "backends", "small")
        f_ior = os.path.join(self.m_base_path, "archive", "ior", "small")
        os.makedirs(os.path.join(f_backends, "outputs-native"))
        os.makedirs(os.path.join(f_ior, "outputs-ior"))
        f_req = parseCompareArguments(
            [
                "nodes",
                f_backends,
                f_ior,
                "write",
                "--all",
                "--output-dir",
                self.m_base_path,
            ]
        )
        with (
            patch(
                "lsmiotool.lib.export.generateIorReports",
                side_effect=RuntimeError("bad"),
            ) as mock_gen,
            patch(
                "lsmiotool.lib.output.ensureLsmioReports", return_value=False
            ) as mock_ensure,
            patch("lsmiotool.lib.log.Console.warning") as mock_warn,
        ):
            self.assertEqual(main.CompareNodesMain(f_request=f_req).run(), 0)
        self.assertEqual(mock_gen.call_count, 1)
        self.assertEqual(mock_ensure.call_count, 1)
        f_no_data = [
            f_c.args[0]
            for f_c in mock_warn.call_args_list
            if f_c.args[0].startswith("No benchmark data")
        ]
        self.assertEqual(len(f_no_data), 6)
        self.assertIn(f"{f_backends}, {f_ior} for write", f_no_data[0])

    def testSeveralFoldersChartedTogether(self) -> None:
        """'compare nodes <folder> <folder> ...': the IOR setups of lsmio-archive/ior with
        the backends; the first folder names the plots, and an arm present in several
        folders is labelled with its folder."""
        from lsmiotool.lib.cli import parseCompareArguments
        from lsmiotool.test.main.ArmGroupTest import IOR_SUMMARY

        f_archive = os.path.join(self.m_base_path, "archive")
        f_backends = os.path.join(f_archive, "backends", "small")
        f_ior = os.path.join(f_archive, "ior", "small")
        f_old = os.path.join(f_archive, "backends-old", "small")
        self._create_report(
            os.path.join(f_backends, "outputs-native"), 4, "1M", "write", 1500.0
        )
        self._create_report(
            os.path.join(f_old, "outputs-native"), 4, "1M", "write", 900.0
        )
        f_day = os.path.join(f_ior, "outputs-ior", "2", "2026-10-14")
        os.makedirs(f_day)
        with open(
            os.path.join(f_day, "out-base-4-1M-2026-10-14-node097-0.txt"), "w"
        ) as f_f:
            f_f.write(IOR_SUMMARY)

        f_out = os.path.join(self.m_base_path, "png")
        f_req = parseCompareArguments(
            ["nodes", f_backends, f_ior, f_old, "write", "--output-dir", f_out]
        )
        self.assertEqual(f_req.folders, (f_backends, f_ior, f_old))
        self.assertEqual(f_req.op, "write")
        with patch("lsmiotool.lib.plot.MultiBarPlot") as mock_plot_cls:
            mock_plot_cls.return_value = MagicMock()
            self.assertEqual(main.CompareNodesMain(f_request=f_req).run(), 0)
            args, _ = mock_plot_cls.call_args
            self.assertEqual(
                [p.legend for p in args[1:]],
                ["native (backends/small)", "native (backends-old/small)", "ior"],
            )
            self.assertEqual(
                args[0].title,
                "Comparison: small, backends + ior + backends-old (WRITE - 4 stripes - 1M)",
            )
            # Named after every folder, never replacing the backends-only chart
            mock_plot_cls.return_value.plot.assert_called_once_with(
                os.path.join(
                    f_out, "compare-small-backends+ior+backends-old-write-4-1M.png"
                )
            )

        # Same-named folders get as much of their path as tells them apart; a folder given
        # twice is charted once
        f_other = os.path.join(
            self.m_base_path, "other", "archive", "backends", "small"
        )
        self._create_report(
            os.path.join(f_other, "outputs-native"), 4, "1M", "write", 700.0
        )
        f_req = parseCompareArguments(
            ["nodes", f_backends, f_other, f_backends, "write", "--output-dir", f_out]
        )
        with patch("lsmiotool.lib.plot.MultiBarPlot") as mock_plot_cls:
            mock_plot_cls.return_value = MagicMock()
            self.assertEqual(main.CompareNodesMain(f_request=f_req).run(), 0)
            args, _ = mock_plot_cls.call_args
            f_tail = os.path.basename(self.m_base_path)
            self.assertEqual(
                [p.legend for p in args[1:]],
                [
                    f"native ({f_tail}/archive/backends/small)",
                    "native (other/archive/backends/small)",
                ],
            )
            mock_plot_cls.return_value.plot.assert_called_once_with(
                os.path.join(
                    f_out,
                    f"compare-small-{f_tail}_archive_backends_small"
                    "+other_archive_backends_small-write-4-1M.png",
                )
            )

        f_req = parseCompareArguments(["nodes", f_backends, f_ior, "--all"])
        self.assertEqual((f_req.folders, f_req.op), ((f_backends, f_ior), "both"))
        f_req = parseCompareArguments(["nodes", f_backends, "read", "16", "8M"])
        self.assertEqual(f_req.folders, (f_backends,))
        with self.assertRaises(SystemExit):
            main.CompareNodesMain(
                f_request=parseCompareArguments(
                    ["nodes", f_backends, os.path.join(f_archive, "missing"), "write"]
                )
            ).run()

        # A stripe count is never a folder, even with a directory of that name here
        from lsmiotool.lib.cli import CompareCliParseError

        f_cwd = os.getcwd()
        os.makedirs(os.path.join(self.m_base_path, "cwd", "4"))
        os.chdir(os.path.join(self.m_base_path, "cwd"))
        try:
            with self.assertRaises(CompareCliParseError):
                parseCompareArguments(["nodes", f_backends, "4", "--all"])
            self.assertEqual(
                parseCompareArguments(["nodes", f_backends, "./4", "--all"]).folders,
                (f_backends, "./4"),
            )
        finally:
            os.chdir(f_cwd)

    def testCombinedNameOfFoldersSharingAParent(self) -> None:
        """Folders with one parent (backends/small, backends/large) are named by their own
        tails, so two such charts never share a file; a long name is cut with a hash."""
        f_root = os.path.join(self.m_base_path, "archive", "backends")
        for f_scale in ("small", "large", "bake"):
            self._create_report(
                os.path.join(f_root, f_scale, "outputs-native"), 4, "1M", "write", 900.0
            )
        f_out = os.path.join(self.m_base_path, "png")
        f_names = []
        for f_other in ("large", "bake"):
            with patch("lsmiotool.lib.plot.MultiBarPlot") as mock_plot_cls:
                mock_plot_cls.return_value = MagicMock()
                main.CompareNodesMain(
                    f_request=parseCompareArguments(
                        [
                            "nodes",
                            os.path.join(f_root, "small"),
                            os.path.join(f_root, f_other),
                            "write",
                            "--output-dir",
                            f_out,
                        ]
                    )
                ).run()
                f_names.append(mock_plot_cls.return_value.plot.call_args[0][0])
        self.assertEqual(
            [os.path.basename(f_n) for f_n in f_names],
            [
                "compare-small-small+large-write-4-1M.png",
                "compare-small-small+bake-write-4-1M.png",
            ],
        )

        f_deep = os.path.join(self.m_base_path, *(["d" * 40] * 4))
        f_dirs = []
        for f_i in range(4):
            f_d = os.path.join(f_deep, f"{'x' * 50}{f_i}", "small")
            self._create_report(
                os.path.join(f_d, "outputs-native"), 4, "1M", "write", 900.0
            )
            f_dirs.append(f_d)
        with patch("lsmiotool.lib.plot.MultiBarPlot") as mock_plot_cls:
            mock_plot_cls.return_value = MagicMock()
            main.CompareNodesMain(
                f_request=parseCompareArguments(
                    ["nodes"] + f_dirs + ["write", "--output-dir", f_out]
                )
            ).run()
            f_name = os.path.basename(mock_plot_cls.return_value.plot.call_args[0][0])
        self.assertLessEqual(len(f_name), 255)
        self.assertRegex(
            f_name, r"^compare-small-x{50}0\+x{50}1\+x*-[0-9a-f]{8}-write-4-1M\.png$"
        )

    def testSameArmTwiceInOneFolderKeepsItsLabel(self) -> None:
        """Only arms of different folders get a folder label (a second rocksdb archive in
        one folder stays 'rocksdb', as before several folders were supported)."""
        target_dir = os.path.join(self.m_base_path, "archive", "backends", "small")
        self._create_report(
            os.path.join(target_dir, "outputs-rocksdb"), 4, "1M", "write", 800.0
        )
        self._create_report(
            os.path.join(target_dir, "outputs-rocksdb-1"), 4, "1M", "write", 900.0
        )
        with patch("lsmiotool.lib.plot.MultiBarPlot") as mock_plot_cls:
            mock_plot_cls.return_value = MagicMock()
            main.CompareNodesMain(
                f_folder=target_dir,
                f_op="write",
                f_output_dir=os.path.join(self.m_base_path, "png"),
            ).run()
            args, _ = mock_plot_cls.call_args
            self.assertEqual([p.legend for p in args[1:]], ["rocksdb", "rocksdb"])

    def testFallbackPatternMapping(self) -> None:
        """Verifies substring pattern matching for non-standard directory names containing backend keywords."""
        target_dir = os.path.join(self.m_base_path, "archive", "backends", "local")
        self._create_report(
            os.path.join(target_dir, "my-leveldb-run"), 4, "1M", "write", 500.0
        )
        self._create_report(
            os.path.join(target_dir, "my-rocksdb-run"), 4, "1M", "write", 600.0
        )
        self._create_report(
            os.path.join(target_dir, "arm-adios"), 4, "1M", "write", 850.0
        )
        self._create_report(
            os.path.join(target_dir, "native"), 4, "1M", "write", 1100.0
        )
        # Contains "adios" too: must map to plugin, not adios2
        self._create_report(
            os.path.join(target_dir, "adios2-plugin-run"), 4, "1M", "write", 1000.0
        )

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
            self.assertEqual(
                legends, ["adios2", "native", "plugin", "rocksdb", "leveldb"]
            )

    def testBackendsPlotGoesStraightIntoOutputDir(self) -> None:
        """A backends/<scale> archive's plot is <out_dir>/compare-<scale>-..., no subdirs."""
        target_dir = os.path.join(
            self.m_base_path, "lsmio-archive", "backends", "small"
        )
        self._create_report(os.path.join(target_dir, "outputs-adios"), 4, "1M", "write")
        self._create_report(
            os.path.join(target_dir, "outputs-native"), 4, "1M", "write"
        )

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

            expected_file = os.path.join(out_dir, "compare-small-write-4-1M.png")

            self.assertTrue(os.path.isdir(out_dir))
            self.assertFalse(os.path.exists(os.path.join(out_dir, "backends")))
            mock_plot_instance.plot.assert_called_once_with(expected_file)

    def testVariantsPlotGoesStraightIntoOutputDir(self) -> None:
        """A variants archive's plot is <out_dir>/compare-variants-..., no subdirs."""
        target_dir = os.path.join(self.m_base_path, "lsmio-archive", "variants")
        self._create_report(
            os.path.join(target_dir, "native-variant-a"), 4, "1M", "read"
        )
        self._create_report(
            os.path.join(target_dir, "native-variant-b"), 4, "1M", "read"
        )

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

            expected_file = os.path.join(out_dir, "compare-variants-read-4-1M.png")

            self.assertTrue(os.path.isdir(out_dir))
            self.assertFalse(os.path.exists(os.path.join(out_dir, "variants")))
            mock_plot_instance.plot.assert_called_once_with(expected_file)

    def testLegacyFlatArchivePathFallback(self) -> None:
        """Verifies legacy unpartitioned archives save directly to <out_dir>/ without subfolder."""
        target_dir = os.path.join(self.m_base_path, "legacy_archive_run")
        self._create_report(
            os.path.join(target_dir, "outputs-native"), 4, "1M", "write"
        )

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

            expected_file = os.path.join(
                out_dir, "compare-legacy_archive_run-write-4-1M.png"
            )
            self.assertTrue(os.path.isdir(out_dir))
            mock_plot_instance.plot.assert_called_once_with(expected_file)

    def testWorkloadParameterPreservationAndDefaults(self) -> None:
        """Verifies default workload parameters (stripes=4, bs=1M) and custom values."""
        target_dir = os.path.join(self.m_base_path, "archive", "backends", "large")
        self._create_report(os.path.join(target_dir, "outputs-adios"), 4, "1M", "write")
        self._create_report(
            os.path.join(target_dir, "outputs-native"), 4, "1M", "write"
        )

        # 1. Defaults: stripes=4, bs=1M
        cnm_default = main.CompareNodesMain(f_folder=target_dir, f_op="write")
        self.assertEqual(cnm_default.stripes, 4)
        self.assertEqual(cnm_default.bs, "1M")
        self.assertEqual(cnm_default.blocksize, "1M")

        with (
            patch("lsmiotool.lib.plot.MultiBarPlot") as mock_plot_cls,
            patch("os.getcwd", return_value=self.m_base_path),
        ):
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
        self._create_report(
            os.path.join(target_dir, "outputs-native"), 16, "8M", "read"
        )

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

            expected_file = os.path.join(out_dir, "compare-large-read-16-8M.png")
            mock_plot_instance.plot.assert_called_once_with(expected_file)

    def testEndToEndPlotFileGeneration(self) -> None:
        """Functional end-to-end test verifying actual image file creation on disk without mock."""
        target_dir = os.path.join(self.m_base_path, "archive", "backends", "bake")
        self._create_report(
            os.path.join(target_dir, "outputs-adios"), 4, "1M", "write", 1100.0
        )
        self._create_report(
            os.path.join(target_dir, "outputs-native"), 4, "1M", "write", 1400.0
        )
        self._create_report(
            os.path.join(target_dir, "outputs-rocksdb"), 4, "1M", "write", 950.0
        )

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

        expected_png = os.path.join(out_dir, "compare-bake-write-4-1M.png")
        self.assertTrue(
            os.path.isfile(expected_png),
            f"Generated plot {expected_png} must exist on disk",
        )
        self.assertGreater(
            os.path.getsize(expected_png), 0, "Generated plot file must not be empty"
        )

    def testAllGeneratesEveryChart(self) -> None:
        """--all draws one chart per (operation, stripes, blocksize): 12 without an
        operation, 6 with one."""
        target_dir = os.path.join(self.m_base_path, "archive", "backends", "bake")
        for f_backend, f_bw in (("outputs-adios", 1100.0), ("outputs-native", 1400.0)):
            f_dir = os.path.join(target_dir, f_backend)
            os.makedirs(f_dir)
            with open(os.path.join(f_dir, "lsm-report.csv"), "w") as f_f:
                for f_op in ("write", "read"):
                    for f_s in (4, 16):
                        for f_b in ("64K", "1M", "8M"):
                            for f_n in (1, 2):
                                f_f.write(
                                    f"{f_n},{f_s},{f_b},{f_op},{f_bw * f_n},1,1,1,1,10\n"
                                )

        def charts(f_op: Optional[str]) -> List[str]:
            f_out = os.path.join(self.m_base_path, f"png-{f_op}")
            req = CompareNodesRequest(
                f_folder=target_dir, f_op=f_op, f_output_dir=f_out, f_all=True
            )
            self.assertEqual(main.CompareNodesMain(f_request=req).run(), 0)
            return sorted(os.listdir(f_out))

        f_expected = sorted(
            f"compare-bake-{f_op}-{f_s}-{f_b}.png"
            for f_op in ("write", "read")
            for f_s in (4, 16)
            for f_b in ("64K", "1M", "8M")
        )
        self.assertEqual(charts(None), f_expected)
        self.assertEqual(
            charts("write"), [f_c for f_c in f_expected if "-write-" in f_c]
        )

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
