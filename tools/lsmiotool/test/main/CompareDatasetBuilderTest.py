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

"""Unit test suite for CompareDatasetBuilder in lsmiotool compare."""

import colorsys
import csv
import math
import os
import tempfile
import unittest
from typing import Any, Sequence
from unittest.mock import patch

from lsmiotool.lib import cli, epocppreport, output
from lsmiotool.lib.compare import (
    COMBINATIONS,
    CompareDatasetBuilder,
    CompareFolderError,
    CompareKindError,
    CompareNoDataError,
    CompareReportReader,
    CompareSelectionError,
    baselineGrey,
    ensureEpocppReports,
    lsmioBaseLabel,
    paletteColour,
    seriesRank,
)


class CompareDatasetBuilderTest(unittest.TestCase):
    """Test suite verifying folder admission, kind checking, and dataset building."""

    m_temp_dir: tempfile.TemporaryDirectory
    m_base_path: str

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.TemporaryDirectory()
        self.m_base_path = self.m_temp_dir.name

    def tearDown(self) -> None:
        self.m_temp_dir.cleanup()

    def _lsmReport(self, f_dir: str, f_rows: Sequence[Any]) -> str:
        os.makedirs(f_dir, exist_ok=True)
        f_path = os.path.join(f_dir, "lsm-report.csv")
        with open(f_path, "w", encoding="utf-8", newline="") as f_f:
            f_writer = csv.writer(f_f)
            for f_r in f_rows:
                f_writer.writerow(list(f_r))
        return f_path

    def _iorReport(self, f_dir: str, f_rows: Sequence[Any]) -> str:
        os.makedirs(f_dir, exist_ok=True)
        f_path = os.path.join(f_dir, "ior-report.csv")
        with open(f_path, "w", encoding="utf-8", newline="") as f_f:
            f_writer = csv.writer(f_f)
            for f_r in f_rows:
                f_writer.writerow(list(f_r))
        return f_path

    def _epocppArm(self, f_dir: str, f_rows: Sequence[Any]) -> str:
        os.makedirs(f_dir, exist_ok=True)
        f_path = os.path.join(f_dir, epocppreport.ARM_REPORT_FILE)
        with open(f_path, "w", encoding="utf-8", newline="") as f_f:
            f_writer = csv.writer(f_f)
            f_writer.writerow(list(epocppreport.REPORT_HEADER))
            for f_r in f_rows:
                if isinstance(f_r, dict):
                    f_writer.writerow(
                        [f_r.get(f_col, "") for f_col in epocppreport.REPORT_HEADER]
                    )
                else:
                    f_writer.writerow(list(f_r))
        return f_path

    def _cost(self, f_dir: str, f_rows: Sequence[Any]) -> str:
        os.makedirs(f_dir, exist_ok=True)
        f_path = os.path.join(f_dir, epocppreport.COST_REPORT_FILE)
        with open(f_path, "w", encoding="utf-8", newline="") as f_f:
            f_writer = csv.writer(f_f)
            f_writer.writerow(list(epocppreport.COST_HEADER))
            for f_r in f_rows:
                if isinstance(f_r, dict):
                    f_writer.writerow(
                        [f_r.get(f_col, "") for f_col in epocppreport.COST_HEADER]
                    )
                else:
                    f_writer.writerow(list(f_r))
        return f_path

    def _request(
        self, f_word: str, f_folders: Sequence[str], **f_kw: Any
    ) -> cli.CompareRequest:
        return cli.CompareRequest(f_benchmark=f_word, f_folders=f_folders, **f_kw)

    def testMissingFolderIsAFolderErrorBeforeAnyListing(self) -> None:
        f_dir1 = os.path.join(self.m_base_path, "exist")
        os.makedirs(f_dir1, exist_ok=True)
        f_dir2 = os.path.join(self.m_base_path, "missing")

        req = self._request("lsmio", [f_dir1, f_dir2])
        builder = CompareDatasetBuilder(req)

        with (
            patch("lsmiotool.lib.output.ensureLsmioReports") as mock_ensure,
            patch("os.listdir", wraps=os.listdir) as mock_listdir,
        ):
            with self.assertRaises(CompareFolderError) as ctx:
                builder.load()
            self.assertIn("missing", str(ctx.exception))
            mock_ensure.assert_not_called()
            mock_listdir.assert_not_called()

        f_file = os.path.join(self.m_base_path, "a_file.txt")
        with open(f_file, "w", encoding="utf-8") as f_f:
            f_f.write("content")
        req2 = self._request("lsmio", [f_file])
        with self.assertRaises(CompareFolderError) as ctx2:
            CompareDatasetBuilder(req2).load()
        self.assertIn("a_file.txt", str(ctx2.exception))

    def testFolderGivenTwiceIsLoadedOnce(self) -> None:
        f_dir = os.path.join(self.m_base_path, "folder1")
        f_child = os.path.join(f_dir, "outputs-native")
        self._lsmReport(
            f_child,
            [
                (
                    1,
                    4,
                    "1M",
                    "write",
                    1000.0,
                    900.0,
                    950.0,
                    10.0,
                    1000.0,
                    900.0,
                    950.0,
                    10.0,
                    0.5,
                )
            ],
        )

        f_dir_abs = os.path.abspath(f_dir)
        f_dir_slash = f_dir_abs + "/"
        f_dir_rel = os.path.relpath(f_dir_abs, start=self.m_base_path)

        with (
            patch("os.getcwd", return_value=self.m_base_path),
            patch(
                "lsmiotool.lib.output.ensureLsmioReports",
                wraps=output.ensureLsmioReports,
            ) as mock_ensure,
        ):
            req = self._request("lsmio", [f_dir_abs, f_dir_slash, f_dir_rel])
            load = CompareDatasetBuilder(req).load()
            self.assertEqual(len(load.folders), 1)
            self.assertEqual(load.folders[0], f_dir_abs)
            self.assertEqual(mock_ensure.call_count, 1)

    def testKindsAdmitted(self) -> None:
        f_backends = os.path.join(self.m_base_path, "backends")
        f_ior = os.path.join(self.m_base_path, "ior_dir")
        f_b_child = os.path.join(f_backends, "outputs-native")
        f_i_child = os.path.join(f_ior, "outputs-ior")
        self._lsmReport(
            f_b_child,
            [
                (
                    1,
                    4,
                    "1M",
                    "write",
                    1000.0,
                    900.0,
                    950.0,
                    10.0,
                    1000.0,
                    900.0,
                    950.0,
                    10.0,
                    0.5,
                )
            ],
        )
        self._iorReport(
            f_i_child,
            [
                (
                    1,
                    4,
                    "1M",
                    "write",
                    1200.0,
                    1100.0,
                    1150.0,
                    10.0,
                    1200.0,
                    1100.0,
                    1150.0,
                    10.0,
                    0.5,
                )
            ],
        )

        load1 = CompareDatasetBuilder(
            self._request("lsmio", [f_backends, f_ior])
        ).load()
        self.assertEqual(len(load1.arms), 2)

        load2 = CompareDatasetBuilder(self._request("ior", [f_ior, f_backends])).load()
        self.assertEqual(len(load2.arms), 2)

        f_legacy = os.path.join(self.m_base_path, "legacy")
        f_leg_child = os.path.join(f_legacy, "01")
        self._lsmReport(
            f_leg_child,
            [
                (
                    1,
                    4,
                    "1M",
                    "write",
                    1000.0,
                    900.0,
                    950.0,
                    10.0,
                    1000.0,
                    900.0,
                    950.0,
                    10.0,
                    0.5,
                )
            ],
        )
        load3 = CompareDatasetBuilder(self._request("lsmio", [f_legacy])).load()
        self.assertEqual(len(load3.arms), 1)
        self.assertEqual(load3.arms[0].base_label, "01")

        f_unpaired = os.path.join(self.m_base_path, "unpaired_var")
        f_u_child = os.path.join(f_unpaired, "outputs-native-legacy")
        self._lsmReport(
            f_u_child,
            [
                (
                    1,
                    4,
                    "1M",
                    "write",
                    1000.0,
                    900.0,
                    950.0,
                    10.0,
                    1000.0,
                    900.0,
                    950.0,
                    10.0,
                    0.5,
                )
            ],
        )
        load4 = CompareDatasetBuilder(self._request("lsmio", [f_unpaired])).load()
        self.assertEqual(len(load4.arms), 1)

    def testKindsRefused(self) -> None:
        # 1. lsmio with epocpp folder
        f_epo1 = os.path.join(self.m_base_path, "refuse_epo1")
        os.makedirs(os.path.join(f_epo1, "outputs-epocpp-posix"), exist_ok=True)

        # 2. ior with IOR-only, then epocpp folder
        f_ior1 = os.path.join(self.m_base_path, "refuse_ior1")
        os.makedirs(os.path.join(f_ior1, "outputs-ior"), exist_ok=True)
        f_epo2 = os.path.join(self.m_base_path, "refuse_epo2")
        os.makedirs(os.path.join(f_epo2, "outputs-epocpp-posix"), exist_ok=True)

        # 3. variants with epocpp folder
        f_epo3 = os.path.join(self.m_base_path, "refuse_epo3")
        os.makedirs(os.path.join(f_epo3, "outputs-epocpp-posix"), exist_ok=True)

        # 4. variants with IOR-only folder
        f_ior2 = os.path.join(self.m_base_path, "refuse_ior2")
        os.makedirs(os.path.join(f_ior2, "outputs-ior"), exist_ok=True)

        # 5. epocpp with IOR-only folder
        f_ior3 = os.path.join(self.m_base_path, "refuse_ior3")
        os.makedirs(os.path.join(f_ior3, "outputs-ior"), exist_ok=True)

        # 6. epocpp with backends folder
        f_back1 = os.path.join(self.m_base_path, "refuse_back1")
        os.makedirs(os.path.join(f_back1, "outputs-native"), exist_ok=True)

        # 7. epocpp with outputs-epocpp-posix + outputs-native
        f_mix1 = os.path.join(self.m_base_path, "refuse_mix1")
        os.makedirs(os.path.join(f_mix1, "outputs-epocpp-posix"), exist_ok=True)
        os.makedirs(os.path.join(f_mix1, "outputs-native"), exist_ok=True)

        # 8. lsmio with IOR-only first
        f_ior4 = os.path.join(self.m_base_path, "refuse_ior4")
        os.makedirs(os.path.join(f_ior4, "outputs-ior"), exist_ok=True)

        # 9. ior with backends first
        f_back2 = os.path.join(self.m_base_path, "refuse_back2")
        os.makedirs(os.path.join(f_back2, "outputs-native"), exist_ok=True)

        # 10. lsmio with role entries
        f_role1 = os.path.join(self.m_base_path, "refuse_role1")
        os.makedirs(os.path.join(f_role1, "outputs-native-footer:run"), exist_ok=True)
        os.makedirs(os.path.join(f_role1, "outputs-native-footer:base"), exist_ok=True)

        # 11. ior with IOR-only, then role entries
        f_ior5 = os.path.join(self.m_base_path, "refuse_ior5")
        os.makedirs(os.path.join(f_ior5, "outputs-ior"), exist_ok=True)
        f_role2 = os.path.join(self.m_base_path, "refuse_role2")
        os.makedirs(os.path.join(f_role2, "outputs-native-footer:run"), exist_ok=True)

        # 12. variants with unpaired + paired
        f_unp = os.path.join(self.m_base_path, "refuse_unp")
        os.makedirs(os.path.join(f_unp, "outputs-native"), exist_ok=True)
        f_prd = os.path.join(self.m_base_path, "refuse_prd")
        os.makedirs(os.path.join(f_prd, "outputs-native-footer:run"), exist_ok=True)

        # 13. variants with paired + versioned
        f_ver = os.path.join(self.m_base_path, "refuse_ver")
        os.makedirs(
            os.path.join(f_ver, "outputs-native-version-main-437400d:run"),
            exist_ok=True,
        )

        matrix = [
            ("lsmio", [f_epo1], ["not a lsmio folder", "use 'compare epocpp'"], False),
            ("ior", [f_ior1, f_epo2], [f_epo2, "use 'compare epocpp'"], False),
            ("variants", [f_epo3], ["use 'compare epocpp'"], False),
            ("variants", [f_ior2], ["use 'compare ior'"], False),
            ("epocpp", [f_ior3], ["use 'compare ior'"], False),
            ("epocpp", [f_back1], ["use 'compare lsmio'"], False),
            ("epocpp", [f_mix1], ["outputs-native"], True),
            ("lsmio", [f_ior4], ["use 'compare ior'"], False),
            ("ior", [f_back2], ["use 'compare lsmio'"], False),
            ("lsmio", [f_role1], ["use 'compare variants'"], False),
            ("ior", [f_ior5, f_role2], ["use 'compare variants'"], False),
            (
                "variants",
                [f_unp, f_prd],
                ["different kinds", "unpaired", "paired"],
                False,
            ),
            ("variants", [f_prd, f_ver], ["paired", "versioned"], False),
        ]

        for f_word, f_dirs, f_subs, f_no_use in matrix:
            with (
                self.subTest(word=f_word, dirs=f_dirs),
                patch("lsmiotool.lib.output.ensureLsmioReports") as mock_ensure,
                patch("lsmiotool.lib.compare.ensureEpocppReports") as mock_epo,
                patch("lsmiotool.lib.export.generateIorReports") as mock_ior_gen,
            ):
                req = self._request(f_word, f_dirs)
                with self.assertRaises(CompareKindError) as ctx:
                    CompareDatasetBuilder(req).load()
                for f_sub in f_subs:
                    self.assertIn(f_sub, str(ctx.exception))
                if f_no_use:
                    self.assertNotIn("use '", str(ctx.exception))
                mock_ensure.assert_not_called()
                mock_epo.assert_not_called()
                mock_ior_gen.assert_not_called()

    def testVariantsKindComesFromTheListing(self) -> None:
        f_dir1 = os.path.join(self.m_base_path, "var_listing1")
        f_empty_run = os.path.join(f_dir1, "outputs-native-footer:run")
        os.makedirs(f_empty_run, exist_ok=True)
        f_legacy = os.path.join(f_dir1, "outputs-native-legacy")
        self._lsmReport(
            f_legacy,
            [
                (
                    1,
                    4,
                    "1M",
                    "write",
                    1000.0,
                    900.0,
                    950.0,
                    10.0,
                    1000.0,
                    900.0,
                    950.0,
                    10.0,
                    0.5,
                )
            ],
        )

        req1 = self._request("variants", [f_dir1])
        load1 = CompareDatasetBuilder(req1).load()
        self.assertEqual(load1.variants_kind, "paired")
        self.assertEqual(len(load1.arms), 0)

        f_dir2 = os.path.join(self.m_base_path, "var_unpaired2")
        f_unp = os.path.join(f_dir2, "outputs-native")
        self._lsmReport(
            f_unp,
            [
                (
                    1,
                    4,
                    "1M",
                    "write",
                    1000.0,
                    900.0,
                    950.0,
                    10.0,
                    1000.0,
                    900.0,
                    950.0,
                    10.0,
                    0.5,
                )
            ],
        )

        req2 = self._request("variants", [f_dir1, f_dir2])
        with self.assertRaises(CompareKindError) as ctx:
            CompareDatasetBuilder(req2).load()
        self.assertIn("different kinds", str(ctx.exception))
        self.assertIn("paired", str(ctx.exception))
        self.assertIn("unpaired", str(ctx.exception))

    def testLsmioBaseLabels(self) -> None:
        self.assertEqual(lsmioBaseLabel("outputs-adios"), "adios2")
        self.assertEqual(lsmioBaseLabel("outputs-adios2"), "adios2")
        self.assertEqual(lsmioBaseLabel("adios2"), "adios2")
        self.assertEqual(lsmioBaseLabel("outputs-native"), "native")
        self.assertEqual(lsmioBaseLabel("outputs-plugin"), "plugin")
        self.assertEqual(lsmioBaseLabel("rocksdb"), "rocksdb")
        self.assertEqual(lsmioBaseLabel("leveldb"), "leveldb")
        self.assertEqual(lsmioBaseLabel("outputs-adios-sync"), "adios2-sync")
        self.assertEqual(lsmioBaseLabel("outputs-plugin-sync-1"), "plugin-sync")
        self.assertEqual(lsmioBaseLabel("my-leveldb-run"), "leveldb")
        self.assertEqual(lsmioBaseLabel("my-rocksdb-run"), "rocksdb")
        self.assertEqual(lsmioBaseLabel("arm-adios"), "adios2")
        self.assertEqual(lsmioBaseLabel("native"), "native")
        self.assertEqual(lsmioBaseLabel("adios2-plugin-run"), "plugin")
        self.assertEqual(lsmioBaseLabel("outputs-weird"), "outputs-weird")

        self.assertEqual(seriesRank("adios2-sync"), 1)
        self.assertEqual(seriesRank("ior-collective"), 11)
        self.assertEqual(seriesRank("epocpp-posix-bw"), 25)
        self.assertEqual(seriesRank("x"), 999)

    def testLsmioAndIorPoints(self) -> None:
        f_dir = os.path.join(self.m_base_path, "points_test")
        f_lsm = os.path.join(f_dir, "outputs-native")
        f_ior1 = os.path.join(f_dir, "outputs-ior")
        f_ior2 = os.path.join(f_dir, "outputs-ior-collective")

        self._lsmReport(
            f_lsm,
            [
                (
                    1,
                    4,
                    "1M",
                    "write",
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    0.5,
                ),
                (
                    2,
                    4,
                    "1M",
                    "write",
                    200.0,
                    190.0,
                    195.0,
                    10.0,
                    200.0,
                    190.0,
                    195.0,
                    10.0,
                    0.5,
                ),
                (
                    16,
                    4,
                    "1M",
                    "write",
                    1600.0,
                    1500.0,
                    1550.0,
                    10.0,
                    1600.0,
                    1500.0,
                    1550.0,
                    10.0,
                    0.5,
                ),
            ],
        )
        self._iorReport(
            f_ior1,
            [
                (
                    1,
                    4,
                    "1M",
                    "read",
                    110.0,
                    100.0,
                    105.0,
                    10.0,
                    110.0,
                    100.0,
                    105.0,
                    10.0,
                    0.5,
                ),
                (
                    2,
                    4,
                    "1M",
                    "read",
                    210.0,
                    200.0,
                    205.0,
                    10.0,
                    210.0,
                    200.0,
                    205.0,
                    10.0,
                    0.5,
                ),
                (
                    16,
                    4,
                    "1M",
                    "read",
                    1610.0,
                    1500.0,
                    1550.0,
                    10.0,
                    1610.0,
                    1500.0,
                    1550.0,
                    10.0,
                    0.5,
                ),
            ],
        )
        self._iorReport(
            f_ior2,
            [
                (
                    1,
                    4,
                    "1M",
                    "write",
                    120.0,
                    110.0,
                    115.0,
                    10.0,
                    120.0,
                    110.0,
                    115.0,
                    10.0,
                    0.5,
                ),
                (
                    2,
                    4,
                    "1M",
                    "write",
                    220.0,
                    210.0,
                    215.0,
                    10.0,
                    220.0,
                    210.0,
                    215.0,
                    10.0,
                    0.5,
                ),
                (
                    16,
                    4,
                    "1M",
                    "write",
                    1620.0,
                    1500.0,
                    1550.0,
                    10.0,
                    1620.0,
                    1500.0,
                    1550.0,
                    10.0,
                    0.5,
                ),
            ],
        )

        load = CompareDatasetBuilder(self._request("lsmio", [f_dir])).load()
        self.assertEqual(len(load.arms), 3)

        arm_native = next(a for a in load.arms if a.child == "outputs-native")
        arm_ior = next(a for a in load.arms if a.child == "outputs-ior")
        arm_col = next(a for a in load.arms if a.child == "outputs-ior-collective")

        self.assertEqual(arm_native.base_label, "native")
        self.assertEqual(arm_ior.base_label, "ior")
        self.assertEqual(arm_col.base_label, "ior-collective")

        idx_native = load.arms.index(arm_native)
        idx_ior = load.arms.index(arm_ior)
        idx_col = load.arms.index(arm_col)

        self.assertEqual(load.points[(idx_native, "write", 1, 4, "1M")], 100.0)
        self.assertEqual(load.points[(idx_native, "write", 2, 4, "1M")], 200.0)
        self.assertEqual(load.points[(idx_native, "write", 16, 4, "1M")], 1600.0)

        self.assertEqual(load.points[(idx_ior, "read", 1, 4, "1M")], 110.0)
        self.assertEqual(load.points[(idx_ior, "read", 2, 4, "1M")], 210.0)
        self.assertEqual(load.points[(idx_ior, "read", 16, 4, "1M")], 1610.0)

        self.assertEqual(load.points[(idx_col, "write", 1, 4, "1M")], 120.0)
        self.assertEqual(load.points[(idx_col, "write", 2, 4, "1M")], 220.0)
        self.assertEqual(load.points[(idx_col, "write", 16, 4, "1M")], 1620.0)

    def testEpocppPointsAndPlacement(self) -> None:
        f_dir = os.path.join(self.m_base_path, "epocpp_pts")
        os.makedirs(os.path.join(f_dir, "notes"), exist_ok=True)

        self._epocppArm(
            os.path.join(f_dir, "outputs-epocpp-baseline"),
            [
                {
                    "N": 4,
                    "Stripes": 4,
                    "BlockSize": "1M",
                    "Metric": "runtime",
                    "Best": 10.0,
                }
            ],
        )
        self._epocppArm(
            os.path.join(f_dir, "outputs-epocpp-posix"),
            [
                {
                    "N": 4,
                    "Stripes": 4,
                    "BlockSize": "1M",
                    "Metric": "runtime",
                    "Best": 12.0,
                }
            ],
        )
        self._epocppArm(
            os.path.join(f_dir, "outputs-epocpp-posix-bw"),
            [
                {
                    "N": 4,
                    "Stripes": 4,
                    "BlockSize": "1M",
                    "Metric": "write",
                    "Best": 500.0,
                },
                {
                    "N": 4,
                    "Stripes": 4,
                    "BlockSize": "1M",
                    "Metric": "read",
                    "Best": 600.0,
                },
            ],
        )
        self._cost(
            f_dir,
            [
                {
                    "N": 4,
                    "Stripes": 4,
                    "BlockSize": "1M",
                    "Backend": "posix",
                    "IOCost": 2.0,
                }
            ],
        )

        load = CompareDatasetBuilder(self._request("epocpp", [f_dir])).load()
        self.assertEqual(len(load.arms), 3)

        arm_base = next(a for a in load.arms if a.child == "outputs-epocpp-baseline")
        arm_posix = next(a for a in load.arms if a.child == "outputs-epocpp-posix")
        arm_bw = next(a for a in load.arms if a.child == "outputs-epocpp-posix-bw")

        self.assertTrue(arm_base.is_baseline)
        self.assertFalse(arm_posix.is_baseline)
        self.assertFalse(arm_bw.is_baseline)

        idx_base = load.arms.index(arm_base)
        idx_posix = load.arms.index(arm_posix)
        idx_bw = load.arms.index(arm_bw)

        # baseline: runtime points only
        self.assertIn((idx_base, "runtime", 4, 4, "1M"), load.points)
        self.assertNotIn((idx_base, "write", 4, 4, "1M"), load.points)
        self.assertNotIn((idx_base, "read", 4, 4, "1M"), load.points)
        self.assertNotIn((idx_base, "cost", 4, 4, "1M"), load.points)

        # posix: runtime points and cost points only
        self.assertIn((idx_posix, "runtime", 4, 4, "1M"), load.points)
        self.assertEqual(load.points[(idx_posix, "cost", 4, 4, "1M")], 2.0)
        self.assertNotIn((idx_posix, "write", 4, 4, "1M"), load.points)
        self.assertNotIn((idx_posix, "read", 4, 4, "1M"), load.points)

        # posix-bw: write and read only
        self.assertEqual(load.points[(idx_bw, "write", 4, 4, "1M")], 500.0)
        self.assertEqual(load.points[(idx_bw, "read", 4, 4, "1M")], 600.0)
        self.assertNotIn((idx_bw, "runtime", 4, 4, "1M"), load.points)
        self.assertNotIn((idx_bw, "cost", 4, 4, "1M"), load.points)

        # notes/ ignored
        self.assertNotIn("notes", [a.child for a in load.arms])

    def testOnDemandReportsBuiltOnceAndFailuresWarn(self) -> None:
        # IOR failure
        f_dir_ior = os.path.join(self.m_base_path, "ondemand_ior")
        f_child_ior = os.path.join(f_dir_ior, "outputs-ior")
        os.makedirs(f_child_ior, exist_ok=True)
        with (
            patch(
                "lsmiotool.lib.export.generateIorReports",
                side_effect=RuntimeError("build failed"),
            ) as mock_gen,
            patch("lsmiotool.lib.log.Console.warning") as mock_warn,
        ):
            load_ior = CompareDatasetBuilder(self._request("ior", [f_dir_ior])).load()
            self.assertEqual(mock_gen.call_count, 1)
            self.assertEqual(len(load_ior.arms), 0)
            mock_warn.assert_any_call(
                f"Failed to generate report for {f_child_ior}: build failed"
            )

        # lsmio ensureLsmioReports returning False
        f_dir_lsm = os.path.join(self.m_base_path, "ondemand_lsm")
        f_child_lsm = os.path.join(f_dir_lsm, "outputs-native")
        os.makedirs(f_child_lsm, exist_ok=True)
        with patch(
            "lsmiotool.lib.output.ensureLsmioReports", return_value=False
        ) as mock_ensure:
            load_lsm = CompareDatasetBuilder(self._request("lsmio", [f_dir_lsm])).load()
            self.assertEqual(mock_ensure.call_count, 1)
            self.assertEqual(len(load_lsm.arms), 0)

        # epocpp writeArmReport raising for one arm
        f_dir_epo = os.path.join(self.m_base_path, "ondemand_epo")
        f_arm1 = os.path.join(f_dir_epo, "outputs-epocpp-baseline")
        f_arm2 = os.path.join(f_dir_epo, "outputs-epocpp-posix")
        os.makedirs(f_arm1, exist_ok=True)
        os.makedirs(f_arm2, exist_ok=True)
        self._epocppArm(
            f_arm2,
            [
                {
                    "N": 4,
                    "Stripes": 4,
                    "BlockSize": "1M",
                    "Metric": "runtime",
                    "Best": 12.0,
                }
            ],
        )

        def _raiseForArm1(path: str) -> None:
            if path == f_arm1:
                raise RuntimeError("arm1 error")
            self._epocppArm(
                path,
                [
                    {
                        "N": 4,
                        "Stripes": 4,
                        "BlockSize": "1M",
                        "Metric": "runtime",
                        "Best": 10.0,
                    }
                ],
            )

        with (
            patch(
                "lsmiotool.lib.epocppreport.writeArmReport",
                side_effect=_raiseForArm1,
            ),
            patch("lsmiotool.lib.epocppreport.writeCostReport"),
            patch(
                "lsmiotool.lib.compare.ensureEpocppReports",
                wraps=ensureEpocppReports,
            ) as mock_ensure_epo,
            patch("lsmiotool.lib.log.Console.warning") as mock_warn_epo,
        ):
            load_epo = CompareDatasetBuilder(
                self._request("epocpp", [f_dir_epo])
            ).load()
            self.assertEqual(mock_ensure_epo.call_count, 1)
            mock_warn_epo.assert_any_call(
                f"Failed to generate report for {f_arm1}: arm1 error"
            )
            self.assertEqual(len(load_epo.arms), 1)
            self.assertEqual(load_epo.arms[0].child, "outputs-epocpp-posix")

    def testEachReportIsReadOnce(self) -> None:
        f_dir = os.path.join(self.m_base_path, "shared_base")
        f_base = os.path.join(f_dir, "outputs-native")
        self._lsmReport(
            f_base,
            [
                (
                    1,
                    4,
                    "1M",
                    "write",
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    0.5,
                )
            ],
        )
        f_run1 = os.path.join(f_dir, "outputs-native-opt1:run")
        self._lsmReport(
            f_run1,
            [
                (
                    1,
                    4,
                    "1M",
                    "write",
                    120.0,
                    110.0,
                    115.0,
                    10.0,
                    120.0,
                    110.0,
                    115.0,
                    10.0,
                    0.5,
                )
            ],
        )
        f_run2 = os.path.join(f_dir, "outputs-native-opt2:run")
        self._lsmReport(
            f_run2,
            [
                (
                    1,
                    4,
                    "1M",
                    "write",
                    130.0,
                    120.0,
                    125.0,
                    10.0,
                    130.0,
                    120.0,
                    125.0,
                    10.0,
                    0.5,
                )
            ],
        )

        with patch.object(
            CompareReportReader,
            "readLsmReport",
            wraps=CompareReportReader.readLsmReport,
        ) as mock_read:
            load = CompareDatasetBuilder(self._request("variants", [f_dir])).load()
            self.assertEqual(len(load.arms), 2)
            base_report_path = os.path.join(os.path.abspath(f_base), "lsm-report.csv")
            calls_for_base = [
                c for c in mock_read.call_args_list if c[0][0] == base_report_path
            ]
            self.assertEqual(len(calls_for_base), 1)
            self.assertEqual(mock_read.call_count, 3)

    def testUnreadableReportLeavesOutOnlyThatArm(self) -> None:
        # 1. lsmio folder: undecodable lsm-report.csv
        f_dir_lsm = os.path.join(self.m_base_path, "unreadable_lsm")
        f_good = os.path.join(f_dir_lsm, "outputs-native")
        f_bad = os.path.join(f_dir_lsm, "outputs-plugin")
        self._lsmReport(
            f_good,
            [
                (
                    1,
                    4,
                    "1M",
                    "write",
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    0.5,
                )
            ],
        )
        os.makedirs(f_bad, exist_ok=True)
        with open(os.path.join(f_bad, "lsm-report.csv"), "wb") as f_f:
            f_f.write(b"\xff\xfe\x00invalid")

        with patch("lsmiotool.lib.log.Console.warning") as mock_warn:
            load_lsm = CompareDatasetBuilder(self._request("lsmio", [f_dir_lsm])).load()
            self.assertEqual(len(load_lsm.arms), 1)
            self.assertEqual(load_lsm.arms[0].base_label, "native")
            warn_msgs = [c[0][0] for c in mock_warn.call_args_list]
            self.assertTrue(
                any("unreadable report" in m and f_bad in m for m in warn_msgs)
            )

        # 2. variants folder: undecodable lsm-report.csv
        f_dir_var = os.path.join(self.m_base_path, "unreadable_var")
        f_v_good = os.path.join(f_dir_var, "outputs-native")
        f_v_bad = os.path.join(f_dir_var, "outputs-native-pool")
        self._lsmReport(
            f_v_good,
            [
                (
                    1,
                    4,
                    "1M",
                    "write",
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    0.5,
                )
            ],
        )
        os.makedirs(f_v_bad, exist_ok=True)
        with open(os.path.join(f_v_bad, "lsm-report.csv"), "wb") as f_f:
            f_f.write(b"\xff\xfe\x00invalid")

        with patch("lsmiotool.lib.log.Console.warning"):
            load_var = CompareDatasetBuilder(
                self._request("variants", [f_dir_var])
            ).load()
            self.assertEqual(len(load_var.arms), 1)
            self.assertEqual(load_var.arms[0].base_label, "default")

        # 3. epocpp arm report with a bad header
        f_dir_epo = os.path.join(self.m_base_path, "unreadable_epo")
        f_e_base = os.path.join(f_dir_epo, "outputs-epocpp-baseline")
        f_e_bad = os.path.join(f_dir_epo, "outputs-epocpp-posix")
        self._epocppArm(
            f_e_base,
            [
                {
                    "N": 4,
                    "Stripes": 4,
                    "BlockSize": "1M",
                    "Metric": "runtime",
                    "Best": 10.0,
                }
            ],
        )
        os.makedirs(f_e_bad, exist_ok=True)
        with open(
            os.path.join(f_e_bad, epocppreport.ARM_REPORT_FILE),
            "w",
            encoding="utf-8",
        ) as f_f:
            f_f.write("Bad,Header,Here\n1,2,3\n")
        self._cost(
            f_dir_epo,
            [
                {
                    "N": 4,
                    "Stripes": 4,
                    "BlockSize": "1M",
                    "Backend": "posix",
                    "IOCost": 2.0,
                }
            ],
        )

        with patch("lsmiotool.lib.log.Console.warning"):
            load_epo = CompareDatasetBuilder(
                self._request("epocpp", [f_dir_epo])
            ).load()
            self.assertEqual(len(load_epo.arms), 1)
            self.assertEqual(load_epo.arms[0].child, "outputs-epocpp-baseline")

        # 4. unreadable epocpp-cost.csv
        f_dir_epo2 = os.path.join(self.m_base_path, "unreadable_cost")
        f_e_posix2 = os.path.join(f_dir_epo2, "outputs-epocpp-posix")
        self._epocppArm(
            f_e_posix2,
            [
                {
                    "N": 4,
                    "Stripes": 4,
                    "BlockSize": "1M",
                    "Metric": "runtime",
                    "Best": 12.0,
                }
            ],
        )
        os.makedirs(f_dir_epo2, exist_ok=True)
        with open(os.path.join(f_dir_epo2, epocppreport.COST_REPORT_FILE), "wb") as f_f:
            f_f.write(b"\xff\xfe\x00invalid")

        with patch("lsmiotool.lib.log.Console.warning"):
            load_epo2 = CompareDatasetBuilder(
                self._request("epocpp", [f_dir_epo2])
            ).load()
            self.assertEqual(len(load_epo2.arms), 1)
            self.assertEqual(load_epo2.points[(0, "runtime", 4, 4, "1M")], 12.0)
            self.assertNotIn((0, "cost", 4, 4, "1M"), load_epo2.points)

    def testCostBuildFailureLosesFolderCostPoints(self) -> None:
        f_dir = os.path.join(self.m_base_path, "cost_failure")
        f_base = os.path.join(f_dir, "outputs-epocpp-baseline")
        f_posix = os.path.join(f_dir, "outputs-epocpp-posix")

        self._epocppArm(
            f_base,
            [
                {
                    "N": 2,
                    "Stripes": 4,
                    "BlockSize": "1M",
                    "Metric": "runtime",
                    "Best": 10.0,
                },
                {
                    "N": 4,
                    "Stripes": 4,
                    "BlockSize": "1M",
                    "Metric": "runtime",
                    "Best": 10.0,
                },
            ],
        )
        self._epocppArm(
            f_posix,
            [
                {
                    "N": 2,
                    "Stripes": 4,
                    "BlockSize": "1M",
                    "Metric": "runtime",
                    "Best": "abc",
                },
                {
                    "N": 4,
                    "Stripes": 4,
                    "BlockSize": "1M",
                    "Metric": "runtime",
                    "Best": 12.0,
                },
            ],
        )

        with patch("lsmiotool.lib.log.Console.warning") as mock_warn:
            load = CompareDatasetBuilder(self._request("epocpp", [f_dir])).load()

            warn_msgs = [c[0][0] for c in mock_warn.call_args_list]
            self.assertTrue(
                any(
                    "Failed to generate the cost report of" in m and f_dir in m
                    for m in warn_msgs
                )
            )
            self.assertTrue(
                any(
                    "1 broken value(s) drawn as gaps (runtime 4/1M N=2)" in m
                    for m in warn_msgs
                )
            )

            idx_posix = next(
                i for i, a in enumerate(load.arms) if a.child == "outputs-epocpp-posix"
            )
            self.assertTrue(math.isnan(load.points[(idx_posix, "runtime", 2, 4, "1M")]))
            self.assertEqual(load.points[(idx_posix, "runtime", 4, 4, "1M")], 12.0)
            for k in load.points:
                self.assertNotEqual(k[1], "cost")

    def testVariantsUnpairedArms(self) -> None:
        f_dir = os.path.join(self.m_base_path, "var_unpaired_arms")
        os.makedirs(os.path.join(f_dir, "notes"), exist_ok=True)
        with open(os.path.join(f_dir, "somefile.txt"), "w", encoding="utf-8") as f_f:
            f_f.write("text")

        f_arm1 = os.path.join(f_dir, "outputs-native-pool")
        self._lsmReport(
            f_arm1,
            [
                (
                    1,
                    4,
                    "1M",
                    "write",
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    0.5,
                )
            ],
        )

        f_arm2 = os.path.join(f_dir, "outputs-native-legacy")
        os.makedirs(f_arm2, exist_ok=True)

        with patch(
            "lsmiotool.lib.output.ensureLsmioReports",
            wraps=output.ensureLsmioReports,
        ) as mock_ensure:
            load = CompareDatasetBuilder(self._request("variants", [f_dir])).load()
            self.assertEqual(len(load.arms), 1)
            self.assertEqual(load.arms[0].base_label, "pool")

            for c in mock_ensure.call_args_list:
                self.assertEqual(c.kwargs.get("f_scale"), "variants")
                self.assertFalse(c.kwargs.get("f_require_logs"))

            self.assertFalse(os.path.exists(os.path.join(f_arm2, "lsm-report.csv")))

    def testVariantsPairedPoints(self) -> None:
        f_dir = os.path.join(self.m_base_path, "var_paired_points")

        # 1. Twin pair: :run-1 with :base-1
        f_r1 = os.path.join(f_dir, "outputs-native-twin:run-1")
        f_b1 = os.path.join(f_dir, "outputs-native-twin:base-1")
        self._lsmReport(
            f_r1,
            [
                (
                    4,
                    4,
                    "1M",
                    "write",
                    120.0,
                    110.0,
                    115.0,
                    10.0,
                    120.0,
                    110.0,
                    115.0,
                    10.0,
                    0.5,
                ),
                (
                    8,
                    4,
                    "1M",
                    "write",
                    240.0,
                    230.0,
                    235.0,
                    10.0,
                    240.0,
                    230.0,
                    235.0,
                    10.0,
                    0.5,
                ),
                (
                    16,
                    4,
                    "1M",
                    "write",
                    500.0,
                    490.0,
                    495.0,
                    10.0,
                    500.0,
                    490.0,
                    495.0,
                    10.0,
                    0.5,
                ),
            ],
        )
        self._lsmReport(
            f_b1,
            [
                (
                    4,
                    4,
                    "1M",
                    "write",
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    0.5,
                ),
                (
                    8,
                    4,
                    "1M",
                    "write",
                    200.0,
                    190.0,
                    195.0,
                    10.0,
                    200.0,
                    190.0,
                    195.0,
                    10.0,
                    0.5,
                ),
            ],
        )

        # 2. Standalone fallback pair: :run with outputs-native
        f_r2 = os.path.join(f_dir, "outputs-native-pool:run")
        f_stand = os.path.join(f_dir, "outputs-native")
        self._lsmReport(
            f_r2,
            [
                (
                    4,
                    4,
                    "1M",
                    "write",
                    "abc",
                    10.0,
                    10.0,
                    10.0,
                    10.0,
                    10.0,
                    10.0,
                    10.0,
                    0.5,
                ),
                (
                    8,
                    4,
                    "1M",
                    "write",
                    150.0,
                    10.0,
                    10.0,
                    10.0,
                    10.0,
                    10.0,
                    10.0,
                    10.0,
                    0.5,
                ),
            ],
        )
        self._lsmReport(
            f_stand,
            [
                (
                    4,
                    4,
                    "1M",
                    "write",
                    100.0,
                    10.0,
                    10.0,
                    10.0,
                    10.0,
                    10.0,
                    10.0,
                    10.0,
                    0.5,
                ),
                (
                    8,
                    4,
                    "1M",
                    "write",
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.5,
                ),
            ],
        )

        # 3. Orphan run (no base)
        f_orph = os.path.join(f_dir, "outputs-rocksdb-opt:run")
        self._lsmReport(
            f_orph,
            [
                (
                    4,
                    4,
                    "1M",
                    "write",
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    0.5,
                )
            ],
        )

        with patch("lsmiotool.lib.log.Console.warning") as mock_warn:
            load = CompareDatasetBuilder(self._request("variants", [f_dir])).load()

            self.assertNotIn("outputs-native", [a.child for a in load.arms])
            self.assertNotIn("outputs-native-twin:base-1", [a.child for a in load.arms])

            warn_msgs = [c[0][0] for c in mock_warn.call_args_list]
            self.assertTrue(
                any(
                    "Orphaned variant run omitted (no matching baseline)" in m
                    for m in warn_msgs
                )
            )

            self.assertEqual(len(load.arms), 2)
            idx_twin = next(i for i, a in enumerate(load.arms) if "twin" in a.child)
            idx_pool = next(i for i, a in enumerate(load.arms) if "pool" in a.child)

            self.assertAlmostEqual(load.points[(idx_twin, "write", 4, 4, "1M")], 20.0)
            self.assertAlmostEqual(load.points[(idx_twin, "write", 8, 4, "1M")], 20.0)
            self.assertNotIn((idx_twin, "write", 16, 4, "1M"), load.points)

            self.assertTrue(math.isnan(load.points[(idx_pool, "write", 4, 4, "1M")]))
            self.assertTrue(math.isnan(load.points[(idx_pool, "write", 8, 4, "1M")]))

            self.assertTrue(
                any(
                    "broken % change point(s) drawn as gaps" in m
                    and f_r2 in m
                    and f_stand in m
                    for m in warn_msgs
                )
            )

    def testVariantsVersionedKindAndLabels(self) -> None:
        f_dir = os.path.join(self.m_base_path, "var_versioned")
        f_run = os.path.join(f_dir, "outputs-native-version-main-437400d:run")
        f_base = os.path.join(f_dir, "outputs-native-version-main-437400d:base")

        self._lsmReport(
            f_run,
            [
                (
                    4,
                    4,
                    "1M",
                    "write",
                    120.0,
                    110.0,
                    115.0,
                    10.0,
                    120.0,
                    110.0,
                    115.0,
                    10.0,
                    0.5,
                )
            ],
        )
        self._lsmReport(
            f_base,
            [
                (
                    4,
                    4,
                    "1M",
                    "write",
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    0.5,
                )
            ],
        )

        load = CompareDatasetBuilder(self._request("variants", [f_dir])).load()
        self.assertEqual(load.variants_kind, "versioned")
        self.assertEqual(len(load.arms), 1)
        self.assertEqual(load.arms[0].base_label, "main (437400d)")

    def testDefaultChartsEverythingByNodes(self) -> None:
        f_dir = os.path.join(self.m_base_path, "archive", "backends", "small")
        f_arm1 = os.path.join(f_dir, "outputs-native")
        f_arm2 = os.path.join(f_dir, "outputs-plugin")
        f_rows1 = []
        f_rows2 = []
        for f_n in (1, 2, 4):
            for f_op in ("write", "read"):
                f_rows1.append(
                    (
                        f_n,
                        16,
                        "8M",
                        f_op,
                        150.0,
                        140.0,
                        145.0,
                        10.0,
                        150.0,
                        140.0,
                        145.0,
                        10.0,
                        0.5,
                    )
                )
                f_rows1.append(
                    (
                        f_n,
                        4,
                        "1M",
                        f_op,
                        100.0,
                        90.0,
                        95.0,
                        10.0,
                        100.0,
                        90.0,
                        95.0,
                        10.0,
                        0.5,
                    )
                )
                f_rows2.append(
                    (
                        f_n,
                        16,
                        "8M",
                        f_op,
                        160.0,
                        150.0,
                        155.0,
                        10.0,
                        160.0,
                        150.0,
                        155.0,
                        10.0,
                        0.5,
                    )
                )
                f_rows2.append(
                    (
                        f_n,
                        4,
                        "1M",
                        f_op,
                        110.0,
                        100.0,
                        105.0,
                        10.0,
                        110.0,
                        100.0,
                        105.0,
                        10.0,
                        0.5,
                    )
                )
        self._lsmReport(f_arm1, f_rows1)
        self._lsmReport(f_arm2, f_rows2)

        req = self._request("lsmio", [f_dir])
        builder = CompareDatasetBuilder(req)
        mock_cwd = os.path.join(self.m_base_path, "mock_cwd")
        with patch("os.getcwd", return_value=mock_cwd):
            ds = builder.build()

        self.assertEqual(len(ds.pngs), 1)
        expected_path = os.path.join(mock_cwd, "compare-small-lsmio-by-nodes.png")
        self.assertEqual(ds.pngs[0].path, expected_path)
        self.assertFalse(os.path.exists(ds.pngs[0].path))

        fig = ds.pngs[0].figure
        self.assertEqual(len(fig.grid), 2)
        self.assertEqual(len(fig.grid[0]), 2)
        self.assertEqual(len(fig.grid[1]), 2)
        self.assertEqual(fig.x_label, "Nodes")
        self.assertEqual(fig.x_categories, ("1", "2", "4"))
        self.assertEqual(fig.grid[0][0].title, "Write, 4 stripes / 1M blocks")
        self.assertEqual(fig.grid[0][1].title, "Read, 4 stripes / 1M blocks")
        self.assertEqual(fig.grid[1][0].title, "Write, 16 stripes / 8M blocks")
        self.assertEqual(fig.grid[1][1].title, "Read, 16 stripes / 8M blocks")
        for f_row in fig.grid:
            for f_panel in f_row:
                self.assertEqual(f_panel.y_label, "Max MiB/s")
                self.assertFalse(f_panel.no_data)

    def testByCombinations(self) -> None:
        f_dir = os.path.join(self.m_base_path, "archive", "backends", "small")
        f_arm1 = os.path.join(f_dir, "outputs-native")
        f_rows = []
        for f_n in (1, 2, 4):
            for f_op in ("write", "read"):
                f_rows.append(
                    (
                        f_n,
                        4,
                        "1M",
                        f_op,
                        100.0,
                        90.0,
                        95.0,
                        10.0,
                        100.0,
                        90.0,
                        95.0,
                        10.0,
                        0.5,
                    )
                )
                f_rows.append(
                    (
                        f_n,
                        16,
                        "8M",
                        f_op,
                        150.0,
                        140.0,
                        145.0,
                        10.0,
                        150.0,
                        140.0,
                        145.0,
                        10.0,
                        0.5,
                    )
                )
        self._lsmReport(f_arm1, f_rows)

        req = self._request("lsmio", [f_dir], f_by="combinations")
        ds = CompareDatasetBuilder(req).build()

        self.assertEqual(len(ds.pngs), 3)
        self.assertTrue(
            ds.pngs[0].path.endswith("compare-small-lsmio-by-combinations-1.png")
        )
        self.assertTrue(
            ds.pngs[1].path.endswith("compare-small-lsmio-by-combinations-2.png")
        )
        self.assertTrue(
            ds.pngs[2].path.endswith("compare-small-lsmio-by-combinations-4.png")
        )

        for f_idx, f_n in enumerate((1, 2, 4)):
            f_fig = ds.pngs[f_idx].figure
            self.assertEqual(len(f_fig.grid), 2)
            self.assertEqual(len(f_fig.grid[0]), 1)
            self.assertEqual(len(f_fig.grid[1]), 1)
            self.assertEqual(f_fig.grid[0][0].title, "Write")
            self.assertEqual(f_fig.grid[1][0].title, "Read")
            self.assertEqual(f_fig.x_label, "Stripes / block size")
            self.assertEqual(
                f_fig.x_categories,
                ("4 stripes\n1M blocks", "16 stripes\n8M blocks"),
            )
            self.assertTrue(f_fig.title.endswith(f", {f_n} nodes"))

    def testCombinationOrderIsStripesMajor(self) -> None:
        f_dir = os.path.join(self.m_base_path, "all_combs")
        f_arm = os.path.join(f_dir, "outputs-native")
        f_rows = []
        for f_s, f_bl in COMBINATIONS:
            f_rows.append(
                (
                    1,
                    f_s,
                    f_bl,
                    "write",
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    0.5,
                )
            )
        self._lsmReport(f_arm, f_rows)

        req = self._request("lsmio", [f_dir], f_metrics=("write",))
        ds = CompareDatasetBuilder(req).build()
        fig = ds.pngs[0].figure
        self.assertEqual(len(fig.grid), 6)
        expected_titles = [
            "Write, 4 stripes / 64K blocks",
            "Write, 4 stripes / 1M blocks",
            "Write, 4 stripes / 8M blocks",
            "Write, 16 stripes / 64K blocks",
            "Write, 16 stripes / 1M blocks",
            "Write, 16 stripes / 8M blocks",
        ]
        self.assertEqual([row[0].title for row in fig.grid], expected_titles)

    def testNarrowingChartsOnlyTheGivenValues(self) -> None:
        f_dir = os.path.join(self.m_base_path, "narrow_suite")
        f_arm = os.path.join(f_dir, "outputs-native")
        f_rows = []
        for f_n in (1, 2, 4):
            for f_s in (4, 16):
                for f_bl in ("64K", "1M", "8M"):
                    for f_op in ("write", "read"):
                        f_rows.append(
                            (
                                f_n,
                                f_s,
                                f_bl,
                                f_op,
                                100.0,
                                90.0,
                                95.0,
                                10.0,
                                100.0,
                                90.0,
                                95.0,
                                10.0,
                                0.5,
                            )
                        )
        self._lsmReport(f_arm, f_rows)

        with self.subTest(option="nodes"):
            req = self._request("lsmio", [f_dir], f_nodes=(2,))
            ds = CompareDatasetBuilder(req).build()
            self.assertEqual(ds.pngs[0].figure.x_categories, ("2",))

        with self.subTest(option="stripes"):
            req = self._request("lsmio", [f_dir], f_stripes=(16,))
            ds = CompareDatasetBuilder(req).build()
            fig = ds.pngs[0].figure
            self.assertEqual(len(fig.grid), 3)
            self.assertTrue(all("16 stripes" in row[0].title for row in fig.grid))

        with self.subTest(option="block"):
            req = self._request("lsmio", [f_dir], f_blocks=("1M", "8M"))
            ds = CompareDatasetBuilder(req).build()
            fig = ds.pngs[0].figure
            self.assertEqual(len(fig.grid), 4)
            self.assertTrue(all("64K blocks" not in row[0].title for row in fig.grid))

        with self.subTest(option="metrics"):
            req = self._request("lsmio", [f_dir], f_metrics=("read", "write"))
            ds = CompareDatasetBuilder(req).build()
            fig = ds.pngs[0].figure
            self.assertTrue(fig.grid[0][0].title.startswith("Read"))
            self.assertTrue(fig.grid[0][1].title.startswith("Write"))

    def testUnheldExplicitValuesAreSelectionErrors(self) -> None:
        f_dir = os.path.join(self.m_base_path, "unheld_err")
        f_arm = os.path.join(f_dir, "outputs-native")
        f_rows = []
        for f_n in (1, 2, 4):
            f_rows.append(
                (
                    f_n,
                    16,
                    "1M",
                    "write",
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    0.5,
                )
            )
        self._lsmReport(f_arm, f_rows)

        with self.subTest(case="nodes"):
            req = self._request("lsmio", [f_dir], f_nodes=(61,))
            with self.assertRaises(CompareSelectionError) as ctx:
                CompareDatasetBuilder(req).build()
            self.assertIn("--nodes 61", str(ctx.exception))
            self.assertIn("1, 2, 4", str(ctx.exception))

        with self.subTest(case="stripes"):
            req = self._request("lsmio", [f_dir], f_stripes=(4,))
            with self.assertRaises(CompareSelectionError) as ctx:
                CompareDatasetBuilder(req).build()
            self.assertIn("--stripes 4", str(ctx.exception))
            self.assertIn("16", str(ctx.exception))

        with self.subTest(case="narrowed_dimensions"):
            f_narrow_dir = os.path.join(self.m_base_path, "narrow_fix")
            f_n_arm = os.path.join(f_narrow_dir, "outputs-native")
            f_n_rows = [
                (
                    1,
                    4,
                    "1M",
                    "write",
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    0.5,
                ),
                (
                    2,
                    4,
                    "1M",
                    "write",
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    0.5,
                ),
                (
                    4,
                    4,
                    "1M",
                    "write",
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    0.5,
                ),
                (
                    4,
                    4,
                    "8M",
                    "write",
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    0.5,
                ),
            ]
            self._lsmReport(f_n_arm, f_n_rows)
            req = self._request(
                "lsmio", [f_narrow_dir], f_nodes=(1, 2), f_blocks=("1M", "8M")
            )
            with self.assertRaises(CompareSelectionError) as ctx:
                CompareDatasetBuilder(req).build()
            self.assertEqual(str(ctx.exception), "--block 8M: the folders hold 1M")

        with self.subTest(case="check_order"):
            req = self._request("lsmio", [f_dir], f_nodes=(61,), f_blocks=("64K",))
            with self.assertRaises(CompareSelectionError) as ctx:
                CompareDatasetBuilder(req).build()
            self.assertIn("--nodes 61", str(ctx.exception))
            self.assertNotIn("--block", str(ctx.exception))

        with self.subTest(case="epocpp_metrics"):
            f_epocpp_dir = os.path.join(self.m_base_path, "epocpp_bw_only")
            f_bw_arm = os.path.join(f_epocpp_dir, "outputs-epocpp-posix-bw")
            self._epocppArm(
                f_bw_arm,
                [
                    {
                        "Metric": "write",
                        "Best": "100.0",
                        "Stripes": "4",
                        "BlockSize": "1M",
                        "N": "1",
                    },
                    {
                        "Metric": "read",
                        "Best": "100.0",
                        "Stripes": "4",
                        "BlockSize": "1M",
                        "N": "1",
                    },
                ],
            )
            req = self._request("epocpp", [f_epocpp_dir], f_metrics=("runtime",))
            with self.assertRaises(CompareSelectionError) as ctx:
                CompareDatasetBuilder(req).build()
            self.assertIn("--metrics runtime", str(ctx.exception))
            self.assertIn("write, read", str(ctx.exception))

    def testCostOnlyAskedAfterFailedCostBuildIsASelectionError(self) -> None:
        f_dir = os.path.join(self.m_base_path, "cost_failed_sel")
        f_arm_posix = os.path.join(f_dir, "outputs-epocpp-posix")
        self._epocppArm(
            f_arm_posix,
            [
                {
                    "Metric": "runtime",
                    "Best": "abc",
                    "Stripes": "4",
                    "BlockSize": "1M",
                    "N": "2",
                },
                {
                    "Metric": "runtime",
                    "Best": "10.0",
                    "Stripes": "4",
                    "BlockSize": "1M",
                    "N": "4",
                },
            ],
        )
        req = self._request("epocpp", [f_dir], f_metrics=("cost",))
        with self.assertRaises(CompareSelectionError) as ctx:
            CompareDatasetBuilder(req).build()
        self.assertIn("cost", str(ctx.exception))
        self.assertIn("runtime", str(ctx.exception))

    def testValueHeldOnlyByBrokenPointsIsHeld(self) -> None:
        f_dir = os.path.join(self.m_base_path, "broken_only")
        f_arm = os.path.join(f_dir, "outputs-native")
        self._lsmReport(
            f_arm,
            [
                (
                    8,
                    4,
                    "1M",
                    "write",
                    "NaN",
                    "NaN",
                    "NaN",
                    10.0,
                    "NaN",
                    "NaN",
                    "NaN",
                    10.0,
                    0.5,
                )
            ],
        )
        req = self._request("lsmio", [f_dir], f_nodes=(8,), f_metrics=("write",))
        ds = CompareDatasetBuilder(req).build()
        fig = ds.pngs[0].figure
        self.assertTrue(fig.grid[0][0].no_data)
        self.assertTrue(math.isnan(fig.grid[0][0].values[0][1][0]))

    def testDefaultMetricsWithoutDataAreLeftOutWithAWarning(self) -> None:
        f_dir = os.path.join(self.m_base_path, "wall_time_only")
        f_arm = os.path.join(f_dir, "outputs-epocpp-baseline")
        self._epocppArm(
            f_arm,
            [
                {
                    "Metric": "runtime",
                    "Best": "12.0",
                    "Stripes": "4",
                    "BlockSize": "1M",
                    "N": "1",
                }
            ],
        )
        req = self._request("epocpp", [f_dir])
        with patch("lsmiotool.lib.log.Console.warning") as mock_warn:
            ds = CompareDatasetBuilder(req).build()

        fig = ds.pngs[0].figure
        self.assertEqual(len(fig.grid[0]), 1)
        self.assertEqual(fig.grid[0][0].title, "Runtime, 4 stripes / 1M blocks")
        warn_msgs = [call.args[0] for call in mock_warn.call_args_list]
        self.assertTrue(any("write, read" in m and "left out" in m for m in warn_msgs))

    def testNoDataIsAnError(self) -> None:
        with self.subTest(case="empty_lsmio"):
            f_dir = os.path.join(self.m_base_path, "empty_lsmio")
            os.makedirs(f_dir, exist_ok=True)
            req = self._request("lsmio", [f_dir])
            with self.assertRaises(CompareNoDataError) as ctx:
                CompareDatasetBuilder(req).build()
            self.assertIn("Nothing to chart for compare lsmio", str(ctx.exception))
            self.assertIn("no arm with a report", str(ctx.exception))

        with self.subTest(case="paired_no_pair"):
            f_dir = os.path.join(self.m_base_path, "paired_no_pair")
            os.makedirs(os.path.join(f_dir, "outputs-native-run:run-1"), exist_ok=True)
            os.makedirs(
                os.path.join(f_dir, "outputs-native-base:base-2"), exist_ok=True
            )
            self._lsmReport(
                os.path.join(f_dir, "outputs-native-run:run-1"),
                [
                    (
                        1,
                        4,
                        "1M",
                        "write",
                        10.0,
                        10.0,
                        10.0,
                        1.0,
                        10.0,
                        10.0,
                        10.0,
                        1.0,
                        0.5,
                    )
                ],
            )
            self._lsmReport(
                os.path.join(f_dir, "outputs-native-base:base-2"),
                [
                    (
                        1,
                        4,
                        "1M",
                        "write",
                        10.0,
                        10.0,
                        10.0,
                        1.0,
                        10.0,
                        10.0,
                        10.0,
                        1.0,
                        0.5,
                    )
                ],
            )
            req = self._request("variants", [f_dir])
            with self.assertRaises(CompareNoDataError) as ctx:
                CompareDatasetBuilder(req).build()
            self.assertIn("Nothing to chart for compare variants", str(ctx.exception))
            self.assertIn("no :run entry with a matching base", str(ctx.exception))

        with self.subTest(case="unpaired_no_reports"):
            f_dir = os.path.join(self.m_base_path, "unpaired_no_rep")
            os.makedirs(os.path.join(f_dir, "outputs-native"), exist_ok=True)
            req = self._request("variants", [f_dir])
            with self.assertRaises(CompareNoDataError) as ctx:
                CompareDatasetBuilder(req).build()
            self.assertIn("Nothing to chart for compare variants", str(ctx.exception))
            self.assertIn("no arm with a report", str(ctx.exception))

    def testSeriesOrderAndLabels(self) -> None:
        f_dir = os.path.join(self.m_base_path, "scrambled_backends")
        f_child_names = [
            "outputs-plugin",
            "outputs-adios",
            "outputs-rocksdb-1",
            "outputs-native",
            "outputs-rocksdb",
            "outputs-rocksdb-sync",
            "outputs-leveldb",
            "outputs-plugin-sync",
            "outputs-native-sync",
            "outputs-leveldb-sync",
            "outputs-adios-sync",
            "outputs-ior",
        ]
        for f_name in f_child_names:
            f_c_dir = os.path.join(f_dir, f_name)
            if f_name == "outputs-ior":
                self._iorReport(
                    f_c_dir,
                    [
                        (
                            1,
                            4,
                            "1M",
                            "write",
                            100.0,
                            90.0,
                            95.0,
                            10.0,
                            100.0,
                            90.0,
                            95.0,
                            10.0,
                            0.5,
                        )
                    ],
                )
            else:
                self._lsmReport(
                    f_c_dir,
                    [
                        (
                            1,
                            4,
                            "1M",
                            "write",
                            100.0,
                            90.0,
                            95.0,
                            10.0,
                            100.0,
                            90.0,
                            95.0,
                            10.0,
                            0.5,
                        )
                    ],
                )

        req = self._request("lsmio", [f_dir])
        ds = CompareDatasetBuilder(req).build()
        expected = [
            "adios2",
            "adios2-sync",
            "native",
            "native-sync",
            "plugin",
            "plugin-sync",
            "rocksdb",
            "rocksdb",
            "rocksdb-sync",
            "leveldb",
            "leveldb-sync",
            "ior",
        ]
        self.assertEqual([s.label for s in ds.pngs[0].figure.series], expected)

        # Collision across folders
        f_dir_a = os.path.join(self.m_base_path, "x", "a", "backends", "small")
        f_dir_b = os.path.join(self.m_base_path, "x", "b", "backends", "small")
        self._lsmReport(
            os.path.join(f_dir_a, "outputs-native"),
            [
                (
                    1,
                    4,
                    "1M",
                    "write",
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    0.5,
                )
            ],
        )
        self._lsmReport(
            os.path.join(f_dir_b, "outputs-native"),
            [
                (
                    1,
                    4,
                    "1M",
                    "write",
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    0.5,
                )
            ],
        )
        req_ab = self._request("lsmio", [f_dir_a, f_dir_b])
        ds_ab = CompareDatasetBuilder(req_ab).build()
        self.assertEqual(
            [s.label for s in ds_ab.pngs[0].figure.series],
            ["native (a/backends/small)", "native (b/backends/small)"],
        )

        # Identical series tuple across PNGs in --by combinations
        f_multi_n = os.path.join(self.m_base_path, "multi_n")
        self._lsmReport(
            os.path.join(f_multi_n, "outputs-native"),
            [
                (
                    1,
                    4,
                    "1M",
                    "write",
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    0.5,
                ),
                (
                    2,
                    4,
                    "1M",
                    "write",
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    0.5,
                ),
            ],
        )
        req_comb = self._request("lsmio", [f_multi_n], f_by="combinations")
        ds_comb = CompareDatasetBuilder(req_comb).build()
        self.assertEqual(ds_comb.pngs[0].figure.series, ds_comb.pngs[1].figure.series)

    def testEpocppMetricPlacement(self) -> None:
        f_dir = os.path.join(self.m_base_path, "epocpp_place")
        f_base = os.path.join(f_dir, "outputs-epocpp-baseline")
        f_posix = os.path.join(f_dir, "outputs-epocpp-posix")
        f_posix_bw = os.path.join(f_dir, "outputs-epocpp-posix-bw")
        self._epocppArm(
            f_base,
            [
                {
                    "Metric": "runtime",
                    "Best": "10.0",
                    "Stripes": "4",
                    "BlockSize": "1M",
                    "N": "1",
                }
            ],
        )
        self._epocppArm(
            f_posix,
            [
                {
                    "Metric": "runtime",
                    "Best": "15.0",
                    "Stripes": "4",
                    "BlockSize": "1M",
                    "N": "1",
                }
            ],
        )
        self._cost(
            f_dir,
            [
                {
                    "Backend": "posix",
                    "IOCost": "5.0",
                    "Stripes": "4",
                    "BlockSize": "1M",
                    "N": "1",
                }
            ],
        )
        self._epocppArm(
            f_posix_bw,
            [
                {
                    "Metric": "write",
                    "Best": "200.0",
                    "Stripes": "4",
                    "BlockSize": "1M",
                    "N": "1",
                },
                {
                    "Metric": "read",
                    "Best": "220.0",
                    "Stripes": "4",
                    "BlockSize": "1M",
                    "N": "1",
                },
            ],
        )

        req_def = self._request("epocpp", [f_dir])
        ds_def = CompareDatasetBuilder(req_def).build()
        fig_def = ds_def.pngs[0].figure
        self.assertEqual(len(fig_def.grid[0]), 3)
        self.assertEqual(fig_def.grid[0][0].title, "Runtime, 4 stripes / 1M blocks")
        self.assertEqual(fig_def.grid[0][1].title, "Write, 4 stripes / 1M blocks")
        self.assertEqual(fig_def.grid[0][2].title, "Read, 4 stripes / 1M blocks")
        self.assertEqual(len(fig_def.grid[0][0].values), 2)
        self.assertEqual(len(fig_def.grid[0][1].values), 1)
        self.assertEqual(len(fig_def.grid[0][2].values), 1)

        req_cw = self._request("epocpp", [f_dir], f_metrics=("cost", "write"))
        ds_cw = CompareDatasetBuilder(req_cw).build()
        fig_cw = ds_cw.pngs[0].figure
        self.assertEqual(fig_cw.grid[0][0].title, "I/O cost, 4 stripes / 1M blocks")
        self.assertTrue(fig_cw.grid[0][0].zero_line)
        self.assertEqual(len(fig_cw.grid[0][0].values), 1)
        self.assertEqual(
            fig_cw.series[fig_cw.grid[0][0].values[0][0]].label, "epocpp-posix"
        )

    def testPanelValuesKeepAbsentAndBrokenApart(self) -> None:
        f_dir = os.path.join(self.m_base_path, "panel_val_types")
        f_arm1 = os.path.join(f_dir, "outputs-epocpp-posix")
        self._epocppArm(
            f_arm1,
            [
                {
                    "Metric": "runtime",
                    "Best": "10.0",
                    "Stripes": "4",
                    "BlockSize": "1M",
                    "N": "1",
                },
                {
                    "Metric": "runtime",
                    "Best": "NaN",
                    "Stripes": "4",
                    "BlockSize": "1M",
                    "N": "2",
                },
            ],
        )
        self._cost(
            f_dir,
            [
                {
                    "Backend": "posix",
                    "IOCost": "-2.5",
                    "Stripes": "4",
                    "BlockSize": "1M",
                    "N": "1",
                },
                {
                    "Backend": "posix",
                    "IOCost": "-1.5",
                    "Stripes": "4",
                    "BlockSize": "1M",
                    "N": "2",
                },
            ],
        )
        req = self._request("epocpp", [f_dir], f_metrics=("cost", "runtime"))
        ds = CompareDatasetBuilder(req).build()
        fig = ds.pngs[0].figure
        cost_panel = fig.grid[0][0]
        self.assertEqual(cost_panel.values[0][1][0], -2.5)
        rt_panel = fig.grid[0][1]
        self.assertEqual(rt_panel.values[0][1][0], 10.0)
        self.assertTrue(math.isnan(rt_panel.values[0][1][1]))
        self.assertFalse(rt_panel.no_data)

        f_vdir = os.path.join(self.m_base_path, "var_vl")
        f_vrun = os.path.join(f_vdir, "outputs-native-twin:run-1")
        f_vbase = os.path.join(f_vdir, "outputs-native-twin:base-1")
        self._lsmReport(
            f_vrun,
            [
                (
                    1,
                    4,
                    "1M",
                    "write",
                    120.0,
                    100.0,
                    100.0,
                    1.0,
                    120.0,
                    100.0,
                    100.0,
                    1.0,
                    0.5,
                )
            ],
        )
        self._lsmReport(
            f_vbase,
            [
                (
                    1,
                    4,
                    "1M",
                    "write",
                    100.0,
                    100.0,
                    100.0,
                    1.0,
                    100.0,
                    100.0,
                    100.0,
                    1.0,
                    0.5,
                )
            ],
        )

        req_bars = self._request("variants", [f_vdir], f_style="bars")
        ds_bars = CompareDatasetBuilder(req_bars).build()
        self.assertTrue(ds_bars.pngs[0].figure.grid[0][0].value_labels)
        self.assertEqual(ds_bars.pngs[0].figure.grid[0][0].y_label, "% change vs base")

        req_lines = self._request("variants", [f_vdir], f_style="lines")
        ds_lines = CompareDatasetBuilder(req_lines).build()
        self.assertFalse(ds_lines.pngs[0].figure.grid[0][0].value_labels)

        self.assertFalse(cost_panel.value_labels)

    def testColours(self) -> None:
        f_dir1 = os.path.join(self.m_base_path, "ep_c1")
        f_dir2 = os.path.join(self.m_base_path, "ep_c2")
        self._epocppArm(
            os.path.join(f_dir1, "outputs-epocpp-baseline"),
            [
                {
                    "Metric": "runtime",
                    "Best": "10.0",
                    "Stripes": "4",
                    "BlockSize": "1M",
                    "N": "1",
                }
            ],
        )
        self._epocppArm(
            os.path.join(f_dir1, "outputs-epocpp-posix"),
            [
                {
                    "Metric": "runtime",
                    "Best": "12.0",
                    "Stripes": "4",
                    "BlockSize": "1M",
                    "N": "1",
                }
            ],
        )
        self._epocppArm(
            os.path.join(f_dir2, "outputs-epocpp-baseline"),
            [
                {
                    "Metric": "runtime",
                    "Best": "11.0",
                    "Stripes": "4",
                    "BlockSize": "1M",
                    "N": "1",
                }
            ],
        )

        req = self._request("epocpp", [f_dir1, f_dir2])
        ds = CompareDatasetBuilder(req).build()
        series = ds.pngs[0].figure.series
        self.assertEqual(series[0].colour, "#6f6e69")
        self.assertEqual(series[1].colour, "#a3a19b")
        self.assertEqual(series[2].colour, "#2a78d6")

        self.assertEqual(len({s.colour for s in series}), len(series))

        for s in series[:2]:
            r = int(s.colour[1:3], 16) / 255.0
            g = int(s.colour[3:5], 16) / 255.0
            b = int(s.colour[5:7], 16) / 255.0
            _, sat, _ = colorsys.rgb_to_hsv(r, g, b)
            self.assertLess(sat, 0.15)

        f_lsm_dir = os.path.join(self.m_base_path, "lsm_25")
        for i in range(1, 26):
            arm_name = f"outputs-a{i:02d}"
            self._lsmReport(
                os.path.join(f_lsm_dir, arm_name),
                [
                    (
                        1,
                        4,
                        "1M",
                        "write",
                        10.0,
                        10.0,
                        10.0,
                        1.0,
                        10.0,
                        10.0,
                        10.0,
                        1.0,
                        0.5,
                    )
                ],
            )
        req_25 = self._request("lsmio", [f_lsm_dir])
        ds_25 = CompareDatasetBuilder(req_25).build()
        series_25 = ds_25.pngs[0].figure.series
        self.assertEqual(len(series_25), 25)
        self.assertEqual(len({s.colour for s in series_25}), 25)
        for s in series_25:
            r = int(s.colour[1:3], 16) / 255.0
            g = int(s.colour[3:5], 16) / 255.0
            b = int(s.colour[5:7], 16) / 255.0
            _, sat, _ = colorsys.rgb_to_hsv(r, g, b)
            self.assertGreaterEqual(sat, 0.35)

    def testColourGeneratorsBoundedTerminationAndDistinctness(self) -> None:
        """B1 regression test: baselineGrey and paletteColour terminate in bounded time with distinct hexes and valid saturations."""
        greys = [baselineGrey(i) for i in range(101)]
        self.assertEqual(len(greys), 101)
        self.assertEqual(len(set(greys)), 101)
        self.assertEqual(greys[0], "#6f6e69")
        for g in greys:
            r = int(g[1:3], 16) / 255.0
            g_val = int(g[3:5], 16) / 255.0
            b = int(g[5:7], 16) / 255.0
            _, sat, _ = colorsys.rgb_to_hsv(r, g_val, b)
            self.assertLess(sat, 0.15)

        palette = [paletteColour(i) for i in range(2001)]
        self.assertEqual(len(palette), 2001)
        self.assertEqual(len(set(palette)), 2001)
        self.assertEqual(palette[0], "#2a78d6")
        for p in palette:
            r = int(p[1:3], 16) / 255.0
            g_val = int(p[3:5], 16) / 255.0
            b = int(p[5:7], 16) / 255.0
            _, sat, _ = colorsys.rgb_to_hsv(r, g_val, b)
            self.assertGreaterEqual(sat, 0.35)

    def testLegendListsSeriesDrawnInEachFigure(self) -> None:
        f_dir = os.path.join(self.m_base_path, "legend_diff")
        f_arm1 = os.path.join(f_dir, "outputs-native")
        f_arm2 = os.path.join(f_dir, "outputs-plugin")
        self._lsmReport(
            f_arm1,
            [
                (
                    1,
                    4,
                    "1M",
                    "write",
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    0.5,
                ),
                (
                    2,
                    4,
                    "1M",
                    "write",
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    0.5,
                ),
            ],
        )
        self._lsmReport(
            f_arm2,
            [
                (
                    1,
                    4,
                    "1M",
                    "write",
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    0.5,
                )
            ],
        )
        req = self._request("lsmio", [f_dir], f_by="combinations")
        ds = CompareDatasetBuilder(req).build()
        self.assertEqual(len(ds.pngs), 2)
        self.assertEqual(ds.pngs[0].figure.legend, (0, 1))
        self.assertEqual(ds.pngs[1].figure.legend, (0,))
        self.assertEqual(ds.pngs[0].figure.series, ds.pngs[1].figure.series)

    def testVariantsLayoutByNodes(self) -> None:
        f_dir = os.path.join(self.m_base_path, "archive", "variants")
        f_arm1 = os.path.join(f_dir, "outputs-native-default")
        f_arm2 = os.path.join(f_dir, "outputs-native-footer")
        self._lsmReport(
            f_arm1,
            [
                (
                    8,
                    4,
                    "64K",
                    "write",
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    0.5,
                ),
                (
                    16,
                    16,
                    "8M",
                    "write",
                    200.0,
                    190.0,
                    195.0,
                    10.0,
                    200.0,
                    190.0,
                    195.0,
                    10.0,
                    0.5,
                ),
            ],
        )
        self._lsmReport(
            f_arm2,
            [
                (
                    8,
                    4,
                    "64K",
                    "write",
                    110.0,
                    100.0,
                    105.0,
                    10.0,
                    110.0,
                    100.0,
                    105.0,
                    10.0,
                    0.5,
                ),
                (
                    16,
                    16,
                    "8M",
                    "write",
                    210.0,
                    200.0,
                    205.0,
                    10.0,
                    210.0,
                    200.0,
                    205.0,
                    10.0,
                    0.5,
                ),
            ],
        )
        req = self._request("variants", [f_dir], f_by="nodes", f_metrics=("write",))
        ds = CompareDatasetBuilder(req).build()

        self.assertEqual(len(ds.pngs), 1)
        self.assertTrue(
            ds.pngs[0].path.endswith("compare-variants-variants-by-nodes.png")
        )

        fig = ds.pngs[0].figure
        self.assertEqual(len(fig.grid), 4)
        self.assertEqual(fig.grid[0][0].title, "Write, 4 stripes / 64K blocks, 8 nodes")
        self.assertEqual(
            fig.grid[1][0].title, "Write, 4 stripes / 64K blocks, 16 nodes"
        )
        self.assertEqual(fig.grid[2][0].title, "Write, 16 stripes / 8M blocks, 8 nodes")
        self.assertEqual(
            fig.grid[3][0].title, "Write, 16 stripes / 8M blocks, 16 nodes"
        )

        self.assertFalse(fig.grid[0][0].no_data)
        self.assertTrue(fig.grid[1][0].no_data)
        self.assertTrue(fig.grid[2][0].no_data)
        self.assertFalse(fig.grid[3][0].no_data)

        self.assertEqual(fig.x_categories, ("default", "footer"))
        self.assertEqual(len(fig.series), 1)
        self.assertEqual(fig.series[0].label, "archive/variants")
        self.assertEqual(fig.grid[0][0].y_label, "Max MiB/s")

    def testVariantsLayoutByCombinations(self) -> None:
        f_dir = os.path.join(self.m_base_path, "archive", "variants-versioned")
        f_run = os.path.join(f_dir, "outputs-native-version-main-437400d:run")
        f_base = os.path.join(f_dir, "outputs-native-version-main-437400d:base")
        f_rows_run = [
            (
                4,
                4,
                "1M",
                "write",
                120.0,
                100.0,
                100.0,
                1.0,
                120.0,
                100.0,
                100.0,
                1.0,
                0.5,
            ),
            (
                8,
                4,
                "1M",
                "write",
                140.0,
                100.0,
                100.0,
                1.0,
                140.0,
                100.0,
                100.0,
                1.0,
                0.5,
            ),
        ]
        f_rows_base = [
            (
                4,
                4,
                "1M",
                "write",
                100.0,
                100.0,
                100.0,
                1.0,
                100.0,
                100.0,
                100.0,
                1.0,
                0.5,
            ),
            (
                8,
                4,
                "1M",
                "write",
                100.0,
                100.0,
                100.0,
                1.0,
                100.0,
                100.0,
                100.0,
                1.0,
                0.5,
            ),
        ]
        self._lsmReport(f_run, f_rows_run)
        self._lsmReport(f_base, f_rows_base)

        req = self._request(
            "variants", [f_dir], f_by="combinations", f_metrics=("write",)
        )
        ds = CompareDatasetBuilder(req).build()

        self.assertEqual(len(ds.pngs), 2)
        self.assertTrue(
            ds.pngs[0].path.endswith(
                "compare-variants-versioned-variants-by-combinations-4.png"
            )
        )
        self.assertTrue(
            ds.pngs[1].path.endswith(
                "compare-variants-versioned-variants-by-combinations-8.png"
            )
        )

        for png in ds.pngs:
            fig = png.figure
            self.assertEqual(fig.x_categories, ("main (437400d)",))
            self.assertEqual(fig.grid[0][0].y_label, "% change vs base")
            self.assertTrue(fig.grid[0][0].zero_line)

    def testVariantCategoriesAcrossFolders(self) -> None:
        f_dir_a = os.path.join(self.m_base_path, "var_a")
        f_dir_b = os.path.join(self.m_base_path, "var_b")
        self._lsmReport(
            os.path.join(f_dir_a, "outputs-native"),
            [
                (
                    1,
                    4,
                    "1M",
                    "write",
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    100.0,
                    90.0,
                    95.0,
                    10.0,
                    0.5,
                )
            ],
        )
        self._lsmReport(
            os.path.join(f_dir_a, "outputs-native-native"),
            [
                (
                    1,
                    4,
                    "1M",
                    "write",
                    110.0,
                    90.0,
                    95.0,
                    10.0,
                    110.0,
                    90.0,
                    95.0,
                    10.0,
                    0.5,
                )
            ],
        )
        self._lsmReport(
            os.path.join(f_dir_a, "outputs-native-footer"),
            [
                (
                    1,
                    4,
                    "1M",
                    "write",
                    120.0,
                    90.0,
                    95.0,
                    10.0,
                    120.0,
                    90.0,
                    95.0,
                    10.0,
                    0.5,
                )
            ],
        )

        self._lsmReport(
            os.path.join(f_dir_b, "outputs-native"),
            [
                (
                    1,
                    4,
                    "1M",
                    "write",
                    130.0,
                    90.0,
                    95.0,
                    10.0,
                    130.0,
                    90.0,
                    95.0,
                    10.0,
                    0.5,
                )
            ],
        )
        self._lsmReport(
            os.path.join(f_dir_b, "outputs-native-footer"),
            [
                (
                    1,
                    4,
                    "1M",
                    "write",
                    140.0,
                    90.0,
                    95.0,
                    10.0,
                    140.0,
                    90.0,
                    95.0,
                    10.0,
                    0.5,
                )
            ],
        )

        req = self._request("variants", [f_dir_a, f_dir_b], f_metrics=("write",))
        ds = CompareDatasetBuilder(req).build()
        fig = ds.pngs[0].figure
        expected_cats = (
            "default",
            "default (outputs-native)",
            "default (outputs-native-native)",
            "footer",
        )
        self.assertEqual(fig.x_categories, expected_cats)
        panel = fig.grid[0][0]
        val_map = {series_idx: vals for series_idx, vals in panel.values}
        self.assertEqual(val_map[0][3], 120.0)
        self.assertEqual(val_map[1][3], 140.0)

    def testVariantsLinesStyleIsAllowed(self) -> None:
        f_dir = os.path.join(self.m_base_path, "var_lines")
        f_run = os.path.join(f_dir, "outputs-native-twin:run-1")
        f_base = os.path.join(f_dir, "outputs-native-twin:base-1")
        self._lsmReport(
            f_run,
            [
                (
                    1,
                    4,
                    "1M",
                    "write",
                    120.0,
                    100.0,
                    100.0,
                    1.0,
                    120.0,
                    100.0,
                    100.0,
                    1.0,
                    0.5,
                )
            ],
        )
        self._lsmReport(
            f_base,
            [
                (
                    1,
                    4,
                    "1M",
                    "write",
                    100.0,
                    100.0,
                    100.0,
                    1.0,
                    100.0,
                    100.0,
                    100.0,
                    1.0,
                    0.5,
                )
            ],
        )
        req = self._request("variants", [f_dir], f_style="lines")
        ds = CompareDatasetBuilder(req).build()
        self.assertTrue(len(ds.pngs) > 0)
        for png in ds.pngs:
            for row in png.figure.grid:
                for panel in row:
                    self.assertFalse(panel.value_labels)

    def testFileNames(self) -> None:
        f_small = os.path.join(self.m_base_path, "backends", "small")
        self._lsmReport(
            os.path.join(f_small, "outputs-native"),
            [
                (
                    1,
                    4,
                    "1M",
                    "write",
                    10.0,
                    10.0,
                    10.0,
                    1.0,
                    10.0,
                    10.0,
                    10.0,
                    1.0,
                    0.5,
                )
            ],
        )

        with self.subTest(case="small_alone"):
            ds = CompareDatasetBuilder(self._request("lsmio", [f_small])).build()
            self.assertTrue(
                ds.pngs[0].path.endswith("compare-small-lsmio-by-nodes.png")
            )

        with self.subTest(case="ior_small_alone"):
            f_ior = os.path.join(self.m_base_path, "ior", "small")
            self._iorReport(
                os.path.join(f_ior, "outputs-ior"),
                [
                    (
                        1,
                        4,
                        "1M",
                        "write",
                        10.0,
                        10.0,
                        10.0,
                        1.0,
                        10.0,
                        10.0,
                        10.0,
                        1.0,
                        0.5,
                    )
                ],
            )
            ds = CompareDatasetBuilder(self._request("ior", [f_ior])).build()
            self.assertTrue(ds.pngs[0].path.endswith("compare-small-ior-by-nodes.png"))

        with self.subTest(case="backends_plus_ior"):
            f_ior = os.path.join(self.m_base_path, "ior", "small")
            ds = CompareDatasetBuilder(self._request("lsmio", [f_small, f_ior])).build()
            self.assertTrue(
                ds.pngs[0].path.endswith(
                    "compare-small-lsmio-backends+ior-by-nodes.png"
                )
            )

        with self.subTest(case="small_plus_large"):
            f_large = os.path.join(self.m_base_path, "backends", "large")
            self._lsmReport(
                os.path.join(f_large, "outputs-native"),
                [
                    (
                        1,
                        4,
                        "1M",
                        "write",
                        10.0,
                        10.0,
                        10.0,
                        1.0,
                        10.0,
                        10.0,
                        10.0,
                        1.0,
                        0.5,
                    )
                ],
            )
            ds = CompareDatasetBuilder(
                self._request("lsmio", [f_small, f_large])
            ).build()
            self.assertTrue(
                ds.pngs[0].path.endswith("compare-small-lsmio-small+large-by-nodes.png")
            )

        with self.subTest(case="legacy_archive_run"):
            f_legacy = os.path.join(self.m_base_path, "legacy_archive_run")
            self._lsmReport(
                os.path.join(f_legacy, "outputs-native"),
                [
                    (
                        1,
                        4,
                        "1M",
                        "write",
                        10.0,
                        10.0,
                        10.0,
                        1.0,
                        10.0,
                        10.0,
                        10.0,
                        1.0,
                        0.5,
                    )
                ],
            )
            ds = CompareDatasetBuilder(self._request("lsmio", [f_legacy])).build()
            self.assertTrue(
                ds.pngs[0].path.endswith(
                    "compare-legacy_archive_run-lsmio-by-nodes.png"
                )
            )

        with self.subTest(case="epocpp_bake"):
            f_bake = os.path.join(self.m_base_path, "epocpp", "bake")
            self._epocppArm(
                os.path.join(f_bake, "outputs-epocpp-baseline"),
                [
                    {
                        "Metric": "runtime",
                        "Best": "10.0",
                        "Stripes": "4",
                        "BlockSize": "1M",
                        "N": "1",
                    }
                ],
            )
            ds = CompareDatasetBuilder(self._request("epocpp", [f_bake])).build()
            self.assertTrue(
                ds.pngs[0].path.endswith("compare-bake-epocpp-by-nodes.png")
            )

        with self.subTest(case="exceed_120_chars"):
            d1 = os.path.join(self.m_base_path, "p1" * 30, "small")
            d2 = os.path.join(self.m_base_path, "p2" * 30, "small")
            d3 = os.path.join(self.m_base_path, "p3" * 30, "small")
            self._lsmReport(
                os.path.join(d1, "outputs-native"),
                [
                    (
                        1,
                        4,
                        "1M",
                        "write",
                        10.0,
                        10.0,
                        10.0,
                        1.0,
                        10.0,
                        10.0,
                        10.0,
                        1.0,
                        0.5,
                    )
                ],
            )
            self._lsmReport(
                os.path.join(d2, "outputs-native"),
                [
                    (
                        1,
                        4,
                        "1M",
                        "write",
                        10.0,
                        10.0,
                        10.0,
                        1.0,
                        10.0,
                        10.0,
                        10.0,
                        1.0,
                        0.5,
                    )
                ],
            )
            self._lsmReport(
                os.path.join(d3, "outputs-native"),
                [
                    (
                        1,
                        4,
                        "1M",
                        "write",
                        10.0,
                        10.0,
                        10.0,
                        1.0,
                        10.0,
                        10.0,
                        10.0,
                        1.0,
                        0.5,
                    )
                ],
            )
            ds = CompareDatasetBuilder(self._request("lsmio", [d1, d2, d3])).build()
            basename = os.path.basename(ds.pngs[0].path)
            prefix = "compare-small-lsmio-"
            suffix = "-by-nodes.png"
            names_part = basename[len(prefix) : -len(suffix)]
            self.assertEqual(len(names_part), 120)
            self.assertEqual(names_part[-9], "-")

        with (
            self.subTest(case="expand_user"),
            patch(
                "os.path.expanduser",
                side_effect=lambda p: "/mock/user/x" if p == "~/x" else p,
            ),
        ):
            req = self._request("lsmio", [f_small], f_output_dir="~/x")
            ds = CompareDatasetBuilder(req).build()
            self.assertEqual(ds.output_dir, "/mock/user/x")

        with self.subTest(case="folder_given_twice"):
            ds = CompareDatasetBuilder(
                self._request("lsmio", [f_small, f_small])
            ).build()
            self.assertTrue(
                ds.pngs[0].path.endswith("compare-small-lsmio-by-nodes.png")
            )
            self.assertNotIn("+", ds.pngs[0].path)

    def testFigureTitlesNameBenchmarkScaleAndFolders(self) -> None:
        f_dir_a = os.path.join(self.m_base_path, "x", "a", "backends", "small")
        f_dir_b = os.path.join(self.m_base_path, "x", "b", "backends", "small")
        self._lsmReport(
            os.path.join(f_dir_a, "outputs-native"),
            [
                (
                    1,
                    4,
                    "1M",
                    "write",
                    10.0,
                    10.0,
                    10.0,
                    1.0,
                    10.0,
                    10.0,
                    10.0,
                    1.0,
                    0.5,
                )
            ],
        )
        self._lsmReport(
            os.path.join(f_dir_b, "outputs-native"),
            [
                (
                    1,
                    4,
                    "1M",
                    "write",
                    10.0,
                    10.0,
                    10.0,
                    1.0,
                    10.0,
                    10.0,
                    10.0,
                    1.0,
                    0.5,
                )
            ],
        )
        ds = CompareDatasetBuilder(self._request("lsmio", [f_dir_a, f_dir_b])).build()
        title = ds.pngs[0].figure.title
        self.assertIn("compare lsmio", title)
        self.assertIn("small", title)
        self.assertIn("a/backends/small", title)
        self.assertIn("b/backends/small", title)
