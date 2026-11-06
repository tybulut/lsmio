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

"""The archive report format: LSMIO, IOR and LMP reports, aggregation and run-root parsing."""

import io
import os
import re
import shutil
import tempfile
import unittest
from typing import Any, List, Optional, Set, Tuple
from unittest.mock import patch

from lsmiotool.lib import data, output
from lsmiotool.lib.cli import parseParseArguments
from lsmiotool.lib.main import CompareVariantsMain, ParseMain
from lsmiotool.lib.runparse import (
    ArchivedArtifactLayout,
    RunRootResolver,
    extractRun,
    generateReports,
)
from lsmiotool.test.fixtures.ArchiveLayoutFixtures import (
    AGG_HEADER,
    rankLog,
    rankValues,
    readTree,
    writeBmtoolLayout,
)

EXAMPLE_IOR_OUTPUTS = os.path.join(os.path.dirname(__file__), "example", "ior-outputs")


def lmpLog(f_bws: List[float], f_extra: Optional[List[str]] = None) -> str:
    """A constructed LSMIO-enabled LAMMPS (in.reaxc.hns) log, one rank's run_tee output.

    No real LMP output exists locally: the LAMMPS part follows LAMMPS' log format for
    bmtool's input (thermo every 10 of 100 steps, 'restart 10'), the LSMIO part the
    lsmio::Benchmark formatIterations/formatSummary output ('iwrite,<MiB/s>,...' per
    restart write, then 'write,<max>,<min>,<mean>,...'), which is what lmp-parse.sh's
    "grep '^.write,'" selects.
    """
    f_lines = [
        "LAMMPS (29 Oct 2020)",
        "  using 1 OpenMP thread(s) per MPI task",
        "Reading data file ...",
        "  triclinic box = (0.0000000 0.0000000 0.0000000) to (13.759000 14.734000 "
        "10.528000) with tilt (0.0000000 -5.4260000 0.0000000)",
        "  1 by 1 by 1 MPI processor grid",
        "  reading atoms ...",
        "  304 atoms",
        "  read_data CPU = 0.002 seconds",
        "Replicating atoms ...",
        "  19456 atoms",
        "  replicate CPU = 0.004 seconds",
        "Setting up Verlet run ...",
        "  Unit style    : real",
        "  Current step  : 0",
        "  Time step     : 0.1",
        "Per MPI rank memory allocation (min/avg/max) = 1031 | 1031 | 1031 Mbytes",
        "Step Temp PotEng Press E_vdwl E_coul Volume ",
    ]
    for f_step in range(0, 101, 10):
        f_lines.append(
            f"{f_step:8d}   {300 - f_step * 0.07:10.4f}   -113.27833    "
            f"{437.52 + f_step:10.4f}   -111.57687   -1.7014647    1731859.9 "
        )
    f_lines += [
        "Loop time of 812.345 on 4 procs for 100 steps with 19456 atoms",
        "",
        "Performance: 0.001 ns/day, 22565.139 hours/ns, 0.123 timesteps/s",
        "99.6% CPU use with 4 MPI tasks x 1 OpenMP threads",
        "",
        "BENCHMARK RESULTS: ",
        "",
        "Iteration-WRITE: LSMIO SYN: false BLF: false",
        "accessmax(MiB)/smin(MiB/s)mean(MiB/s)total(MiB)total(Ops)iteration",
    ]
    f_lines += [f"iwrite,{f_bw:.2f},{f_bw:.2f},{f_bw:.2f},18.25,1,1" for f_bw in f_bws]
    f_lines += [
        "",
        "Bench-WRITE: LSMIO SYN: false BLF: false",
        AGG_HEADER,
        "------,----------,----------,-----------,-----------,----------,----------",
        f"write,{max(f_bws):.2f},{min(f_bws):.2f},{sum(f_bws) / len(f_bws):.2f},"
        f"{18.25 * len(f_bws):.2f},{len(f_bws)},{len(f_bws)}",
        "",
    ]
    f_lines += f_extra or []
    f_lines.append("Total wall time: 0:13:40")
    return "\n".join(f_lines) + "\n"


class AwkPrimitivesTest(unittest.TestCase):
    """awk number formatting, glob collation and per-combination aggregation."""

    def testAwkNumberFormatting(self) -> None:
        self.assertEqual(data.formatAwkNumber(20479.68), "20479.7")
        self.assertEqual(data.formatAwkNumber(163838.4), "163838")
        self.assertEqual(data.formatAwkNumber(2621440.0), "2621440")
        self.assertEqual(data.formatAwkNumber(3634.912), "3634.91")
        self.assertEqual(data.formatAwkNumber(0.0), "0")
        self.assertEqual(data.formatAwkNumber(1234567.5), "1.23457e+06")
        self.assertEqual(data.awkToNumber(" 12.5x"), 12.5)
        self.assertEqual(data.awkToNumber("abc"), 0.0)
        self.assertTrue(data.awkIsStrNum(" 10\r"))
        self.assertFalse(data.awkIsStrNum("10x"))

    def testShellGlobCollationOrder(self) -> None:
        """bmtool's glob under en_US.UTF-8 puts '16/...' before '1/...' (punctuation ignored)."""
        f_paths = [
            "1/agg-4-1M-report.csv",
            "16/agg-16-1M-report.csv",
            "2/agg-16-8M-report.csv",
            "24/agg-4-64K-report.csv",
            "8/agg-16-64K-report.csv",
            "8/agg-16-1M-report.csv",
            "8/agg-4-1M-report.csv",
        ]
        self.assertEqual(
            sorted(f_paths, key=data.bmtoolCollationKey),
            [
                "16/agg-16-1M-report.csv",
                "1/agg-4-1M-report.csv",
                "24/agg-4-64K-report.csv",
                "2/agg-16-8M-report.csv",
                "8/agg-16-1M-report.csv",
                "8/agg-16-64K-report.csv",
                "8/agg-4-1M-report.csv",
            ],
        )

    def testAggregateSumsColumnsAndMaxIteration(self) -> None:
        """Columns 2-6 are summed across ranks; column 7 is the maximum."""
        f_agg = data.LsmioBmtoolAggregate()
        f_agg.addLines(
            rankLog(
                "write,521.21,179.48,444.53,2559.96,40960,10",
                "read,2089.25,1916.17,2016.48,2559.96,40960,10",
            ).split("\n")
        )
        f_agg.addLines(
            rankLog(
                "write,500.5,170.25,440.1,2559.96,40960,9",
                "read,2000.75,1900,2000,2559.96,40960,12",
            ).split("\n")
        )
        self.assertEqual(
            f_agg.aggLines(),
            [
                AGG_HEADER,
                "write,1021.71,349.73,884.63,5119.92,81920,10",
                "read,4090,3816.17,4016.48,5119.92,81920,12",
            ],
        )
        self.assertEqual(f_agg.fileCount, 2)

    def testAggregateWithoutSummaryLinesMatchesAwk(self) -> None:
        """A combination whose ranks never reached 'read,' prints awk's empty sums."""
        f_agg = data.LsmioBmtoolAggregate()
        f_agg.addLines(rankLog("write,10.5,1,2,3,4,10", None).split("\n"))
        self.assertEqual(f_agg.row("write"), "write,10.5,1,2,3,4,10")
        self.assertEqual(f_agg.row("read"), "read,,,,,,0")

    def testReportRowsTransform(self) -> None:
        """generate_report keeps the last two write/read lines, prefixed 'N,rf,bs,'."""
        self.assertEqual(
            data.bmtoolReportRows(
                "8/agg-16-1M-report.csv",
                [
                    AGG_HEADER,
                    "write,3634.91,2746.7,3376.47,20479.7,327680,10",
                    "read,18104.3,13845.5,15947.3,20479.7,327680,10",
                ],
            ),
            [
                "8,16,1M,write,3634.91,2746.7,3376.47,20479.7,327680,10",
                "8,16,1M,read,18104.3,13845.5,15947.3,20479.7,327680,10",
            ],
        )


def readFile(f_path: str) -> bytes:
    with open(f_path, "rb") as f_f:
        return f_f.read()


class IorLmpReportTest(unittest.TestCase):
    """ior-report.csv and lmp-report.csv: the IOR writer and the LMP report reader."""

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.mkdtemp(prefix="lsmiotool-iorlmp-")

    def tearDown(self) -> None:
        shutil.rmtree(self.m_temp_dir, ignore_errors=True)

    def _iorOutputs(self, f_dir: str) -> str:
        """The example IOR outputs plus edge cases: a '-c-' setup infix, trailing
        blanks, an empty file, a hidden file and a 2-digit node directory."""
        shutil.copytree(EXAMPLE_IOR_OUTPUTS, f_dir)
        f_src = os.path.join(
            f_dir, "1", "2023-07-21", "out-collective-4-1M-2023-07-21-node169-0.txt.2"
        )
        with open(f_src) as f_f:
            f_text = f_f.read()
        f_day = os.path.join(f_dir, "16", "2023-07-22")
        os.makedirs(f_day)
        with open(
            os.path.join(f_day, "out-hdf5-c-16-8M-2023-07-22-nid001234-0.txt"), "w"
        ) as f_f:
            f_f.write(re.sub(r"(?m)^(write|read)( .*)$", r"\1\2   ", f_text))
        open(
            os.path.join(f_day, "out-base-4-64K-2023-07-22-node001-0.txt"), "w"
        ).close()
        with open(
            os.path.join(f_day, ".out-base-4-1M-2023-07-22-node001-0.txt.rc"), "w"
        ) as f_f:
            f_f.write("write 1 2 3\n")
        return f_dir

    def testIorReportLiteralRows(self) -> None:
        """The report written by IorAggOutput holds these literal rows."""
        f_py = self._iorOutputs(os.path.join(self.m_temp_dir, "py"))
        output.IorAggOutput(f_py).generateReports()
        f_report = readFile(os.path.join(f_py, data.IOR_REPORT_FILE))
        # Both StdDev columns survive (466.80 must not become the OPs StdDev)
        self.assertIn(
            b"1,16,64K,write,887.21,773.61,839.98,35.41,14195.36,12377.73,13439.62,566.57,",
            f_report,
        )
        # The row key expects 5-character nid names (ARCHER2 has 6), and trailing
        # blanks become a trailing comma
        self.assertIn(b"16,16,8M-2023-07-22-nid001234-0.txt,write,", f_report)
        self.assertIn(b",MPIIO,0,\n", f_report)

    def testIorReportIntoOtherDirectory(self) -> None:
        f_src = self._iorOutputs(os.path.join(self.m_temp_dir, "src"))
        f_out = os.path.join(self.m_temp_dir, "out")
        output.IorAggOutput(f_src).generateReports(f_out)
        self.assertTrue(data.isUsableReport(os.path.join(f_out, data.IOR_REPORT_FILE)))
        self.assertFalse(os.path.exists(os.path.join(f_src, data.IOR_REPORT_FILE)))

    def testIorSingleRunDataKeepsBothStdDev(self) -> None:
        f_path = os.path.join(
            EXAMPLE_IOR_OUTPUTS,
            "1",
            "2023-07-21",
            "out-collective-16-64K-2023-07-21-node169-0.txt.2",
        )
        f_map = data.IorSingleRunData(f_path).getMap()
        self.assertEqual(f_map["write"]["StdDev"], 35.41)
        self.assertEqual(f_map["write"][data.IOR_OPS_STDDEV_KEY], 566.57)
        self.assertEqual(
            data.iorSummaryKeys(["a", "StdDev", "b", "StdDev", "a"]),
            ["a", "StdDev", "b", data.IOR_OPS_STDDEV_KEY, "a#2"],
        )

    def testLmpSummaryDataReadsLabelRowThroughput(self) -> None:
        """LmpSummaryData reads the throughput of a label row ('iwrite' / '#write'),
        not row[3] (the label) as 0."""
        f_path = os.path.join(self.m_temp_dir, data.LMP_REPORT_FILE)
        with open(f_path, "w") as f_f:
            f_f.write("1,4,64K,iwrite,164.00,164.00,164.00,18.25,1,1\n")
            f_f.write("2,16,8M,#write,1.5\n")
        f_summary = data.LmpSummaryData(f_path)
        self.assertEqual(f_summary.timeSeries(False, 4, "64K"), ([1], [164.0]))
        self.assertEqual(f_summary.timeSeries(False, 16, "8M"), ([2], [1.5]))

    def testIsLmpResultLine(self) -> None:
        """The LMP run-root parser selects a result line by its 6-character label tail."""
        self.assertTrue(data.isLmpResultLine("iwrite,1"))
        self.assertFalse(data.isLmpResultLine("write,1"))


class LsmioAggOutputReportTest(unittest.TestCase):
    """LsmioAggOutput.generateReports: agg-*-report.csv and lsm-report.csv."""

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.mkdtemp(prefix="lsmiotool-lsmioreport-")

    def tearDown(self) -> None:
        shutil.rmtree(self.m_temp_dir, ignore_errors=True)

    def testKnownValuesAcrossRanks(self) -> None:
        """Sums, not rank 0's line, reach the agg files and lsm-report.csv."""
        f_root = os.path.join(self.m_temp_dir, "outputs-native")
        writeBmtoolLayout(f_root, ["2"])
        output.LsmioAggOutput(f_root).generateReports(f_out_dir=f_root)

        f_r0 = rankValues(0, 0 + 2)["write"].split(",")
        f_r1 = rankValues(1, 0 + 2)["write"].split(",")
        f_expected = "write," + ",".join(
            [
                data.formatAwkNumber(float(f_r0[f_i]) + float(f_r1[f_i]))
                for f_i in range(1, 6)
            ]
            + ["10"]
        )
        self.assertNotEqual(f_expected, rankValues(0, 2)["write"])
        with open(os.path.join(f_root, "2", "agg-4-64K-report.csv")) as f_f:
            f_agg = f_f.read().split("\n")
        self.assertEqual(f_agg[0], AGG_HEADER)
        self.assertEqual(f_agg[1], f_expected)

        with open(os.path.join(f_root, data.LSM_REPORT_FILE)) as f_f:
            f_rows = f_f.read().splitlines()
        self.assertEqual(len(f_rows), 12)
        self.assertIn("2,4,64K," + f_expected, f_rows)
        self.assertTrue(all(len(f_row.split(",")) == 10 for f_row in f_rows))
        self.assertTrue(f_rows[0].startswith("2,16,1M,write,"))

    def testReportRowOrderFollowsShellGlobCollation(self) -> None:
        """lsm-report.csv rows go node dir by node dir in glob collation order
        ('16' before '1', then '2', '4'), then by agg file in the same order."""
        f_root = os.path.join(self.m_temp_dir, "outputs-native")
        writeBmtoolLayout(f_root, ["1", "2", "4", "16"])
        with patch("lsmiotool.lib.log.Console.warning"):
            output.LsmioAggOutput(f_root, f_scale="small").generateReports(
                f_out_dir=f_root
            )
        with open(os.path.join(f_root, data.LSM_REPORT_FILE)) as f_f:
            f_rows = f_f.read().splitlines()
        self.assertEqual(len(f_rows), 48)
        f_keys = [",".join(f_row.split(",")[:4]) for f_row in f_rows]
        self.assertEqual(
            f_keys[:12],
            [
                "16,16,1M,write",
                "16,16,1M,read",
                "16,16,64K,write",
                "16,16,64K,read",
                "16,16,8M,write",
                "16,16,8M,read",
                "16,4,1M,write",
                "16,4,1M,read",
                "16,4,64K,write",
                "16,4,64K,read",
                "16,4,8M,write",
                "16,4,8M,read",
            ],
        )
        f_nodes = [f_key.split(",")[0] for f_key in f_keys]
        self.assertEqual(
            [f_n for f_i, f_n in enumerate(f_nodes) if f_i % 12 == 0],
            ["16", "1", "2", "4"],
        )

    def testMissingNodeDirAndCombinationAreSkippedWithWarning(self) -> None:
        """Missing node dirs / combos warn instead of raising, like bmtool."""
        f_root = os.path.join(self.m_temp_dir, "outputs-native")
        writeBmtoolLayout(f_root, ["2"])
        for f_name in os.listdir(os.path.join(f_root, "2", "2026-10-07")):
            if "-16-8M-" in f_name:
                os.remove(os.path.join(f_root, "2", "2026-10-07", f_name))

        with patch("lsmiotool.lib.log.Console.warning") as f_warn:
            output.LsmioAggOutput(f_root, f_scale="bake").generateReports()
        f_msgs = [str(f_c[0][0]) for f_c in f_warn.call_args_list]
        self.assertTrue(any("skipping node 1" in f_m for f_m in f_msgs))
        self.assertTrue(any("16-8M" in f_m for f_m in f_msgs))
        self.assertFalse(
            os.path.exists(os.path.join(f_root, "2", "agg-16-8M-report.csv"))
        )
        with open(os.path.join(f_root, data.LSM_REPORT_FILE)) as f_f:
            self.assertEqual(len(f_f.read().splitlines()), 10)

    def testPartialRankFilesDoNotRaise(self) -> None:
        """A node dir holding fewer rank files than nodes still yields reports."""
        f_root = os.path.join(self.m_temp_dir, "outputs-native")
        writeBmtoolLayout(f_root, ["8"])
        f_day = os.path.join(f_root, "8", "2026-10-07")
        for f_name in os.listdir(f_day):
            if "node107" in f_name:
                os.remove(os.path.join(f_day, f_name))

        f_agg = output.LsmioAggOutput(f_root, f_scale="variants")
        f_agg.generateReports(f_out_dir=f_root)
        self.assertTrue(data.isUsableReport(os.path.join(f_root, data.LSM_REPORT_FILE)))
        with self.assertRaises(output.MissingDataError):
            f_agg.getMap()

    def testNoRowsNeverWritesEmptyReport(self) -> None:
        """Regeneration without data writes no lsm-report.csv."""
        f_root = os.path.join(self.m_temp_dir, "outputs-empty")
        os.makedirs(f_root)
        with patch("lsmiotool.lib.log.Console.warning") as f_warn:
            output.LsmioAggOutput(f_root, f_scale="variants").generateReports()
        self.assertFalse(os.path.exists(os.path.join(f_root, data.LSM_REPORT_FILE)))
        self.assertTrue(
            any("not writing" in str(f_c[0][0]) for f_c in f_warn.call_args_list)
        )

    def testZeroByteReportCountsAsMissing(self) -> None:
        """ensureLsmioReports regenerates over a zero-byte lsm-report.csv."""
        f_root = os.path.join(self.m_temp_dir, "outputs-native")
        writeBmtoolLayout(f_root, ["1"])
        f_report = os.path.join(f_root, data.LSM_REPORT_FILE)
        open(f_report, "w").close()
        self.assertTrue(output.ensureLsmioReports(f_root))
        self.assertGreater(os.path.getsize(f_report), 0)


class RunParseReportTest(unittest.TestCase):
    """Manifest-layout runs (pristine and archived) report like the archive layout."""

    def setUp(self) -> None:
        from lsmiotool.test.parse.RunParseTest import RunParseTest

        self.m_helper = RunParseTest("testExplicitSucceededPaths")
        self.m_helper.setUp()
        self.m_temp_dir = self.m_helper.m_temp_dir

    def tearDown(self) -> None:
        self.m_helper.tearDown()

    def _writeRankLogs(self, f_run_root: str) -> None:
        f_resolved = RunRootResolver.resolve(f_run_root)
        for f_pt in f_resolved.points:
            for f_salt, f_combo in enumerate(f_resolved.plan.combinations):
                f_dir = os.path.join(f_pt.pointDir, "logs", f_combo.name)
                os.makedirs(f_dir, exist_ok=True)
                for f_rank in range(f_pt.scalePoint.tasks):
                    f_vals = rankValues(f_rank, f_salt)
                    with open(os.path.join(f_dir, f"rank_{f_rank}.log"), "w") as f_f:
                        f_f.write(rankLog(f_vals["write"], f_vals["read"]))

    def _bmtoolEquivalent(self, f_run_root: str, f_dest: str) -> None:
        """Lay the run's rank logs out like bmtool and aggregate them with LsmioAggOutput."""
        f_resolved = RunRootResolver.resolve(f_run_root)
        for f_pt in f_resolved.points:
            for f_combo in f_resolved.plan.combinations:
                for f_rank in range(f_pt.scalePoint.tasks):
                    f_src = os.path.join(
                        f_pt.pointDir, "logs", f_combo.name, f"rank_{f_rank}.log"
                    )
                    f_dst = os.path.join(
                        f_dest,
                        str(f_pt.scalePoint.nodes),
                        "2026-10-07",
                        f"out-native-{f_combo.stripe_count}-{f_combo.block_size}"
                        f"-2026-10-07-node{100 + f_rank:03d}-0.txt",
                    )
                    os.makedirs(os.path.dirname(f_dst), exist_ok=True)
                    shutil.copyfile(f_src, f_dst)
        output.LsmioAggOutput(f_dest).generateReports(f_out_dir=f_dest)

    def testArchivedRunRootParsesLikeArchiveLayout(self) -> None:
        """A run root moved to '<dest>/outputs-<arm>:run' resolves and sums ranks."""
        f_run_root, _f_plan, _ = self.m_helper._setupSucceededRun(
            "run-archived-001", "lsmio", "bake"
        )
        self._writeRankLogs(f_run_root)
        f_archived = os.path.join(
            self.m_temp_dir, "lsmio-archive", "variants", "outputs-native-legacy:run"
        )
        os.makedirs(os.path.dirname(f_archived))
        shutil.move(f_run_root, f_archived)
        os.makedirs(f_run_root)  # an empty run-root directory is left behind

        f_resolved = RunRootResolver.resolve(f_archived)
        self.assertEqual(f_resolved.runRoot, f_archived)
        self.assertEqual(f_resolved.runId, "run-archived-001")
        self.assertTrue(
            all(f_pt.pointDir.startswith(f_archived) for f_pt in f_resolved.points)
        )

        f_out = os.path.join(self.m_temp_dir, "reports")
        f_files = generateReports(f_resolved, extractRun(f_resolved), f_out)
        self.assertIn("lsm-report.csv", f_files)

        f_bm = os.path.join(self.m_temp_dir, "bm-equivalent")
        self._bmtoolEquivalent(f_archived, f_bm)
        self.assertEqual(readTree(f_out), readTree(f_bm))

    def _setupPartialRun(self, f_run_id: str) -> Tuple[str, Set[Tuple[int, str]]]:
        """An lsmio 'bake' run (points of 1, 2, 4, 8 tasks) that failed at point 1.

        Point 0 succeeded. Point 1 ran combinations 0-3 cleanly, rank 1 of
        combination 4 failed and combination 5 never ran (rank logs exist for all
        six); its job ended FAILED. Points 2 and 3 never ran. Returns the run root and
        the (point ordinal, combination) pairs with complete output.
        """
        from lsmiotool.lib.artifacts import ArtifactStore
        from lsmiotool.lib.evidence import EvidenceKind, EvidenceStore, JobHandle

        f_plan = self.m_helper._createPlan(f_run_id, "lsmio", "bake")
        f_store = ArtifactStore(self.m_temp_dir, f_run_id)
        f_store.allocateRun(f_plan)
        f_ev = EvidenceStore(f_store.layout, f_plan=f_plan)
        f_complete: Set[Tuple[int, str]] = set()

        for f_idx in (0, 1):
            f_sp = f_plan.scale_points[f_idx]
            f_store.preparePoint(f_sp, f_ordinal=f_idx)
            f_handle = JobHandle("slurm", f"77{f_idx}")
            f_ev.recordSubmissionRequested(f_sp, "client", f_ordinal=f_idx)
            f_ev.recordSubmissionDispatched(f_sp, "client", f_ordinal=f_idx)
            f_ev.recordSubmissionRecorded(
                f_sp, "client", f_handle=f_handle, f_ordinal=f_idx
            )
            f_ev.recordWorkerEvent(
                f_sp, 1, EvidenceKind.CONTROLLER_STARTED, f_ordinal=f_idx
            )
            for f_c_idx, f_combo in enumerate(f_plan.combinations):
                if f_idx == 1 and f_c_idx == 5:
                    continue
                f_failed = f_idx == 1 and f_c_idx == 4
                f_ev.recordControllerResult(
                    f_sp,
                    f_combo,
                    f_payload={"exit_code": 1 if f_failed else 0},
                    f_ordinal=f_idx,
                )
                for f_rank in range(f_sp.tasks):
                    f_ev.recordRankResult(
                        f_sp,
                        f_rank,
                        f_combo,
                        f_payload={"exit_code": 1 if f_failed and f_rank == 1 else 0},
                        f_ordinal=f_idx,
                    )
                if not f_failed:
                    f_complete.add((f_idx, f_combo.name))
            f_ev.recordSchedulerObservation(
                f_sp,
                "reconciler",
                1,
                f_payload={
                    "state": "failed" if f_idx else "succeeded",
                    "handle": f_handle.toDict(),
                },
                f_ordinal=f_idx,
            )

        # Rank logs for every combination of points 0 and 1
        for f_idx in (0, 1):
            f_sp = f_plan.scale_points[f_idx]
            f_pt_dir = f_store.layout.pointDir(f_sp, f_idx)
            for f_salt, f_combo in enumerate(f_plan.combinations):
                f_dir = os.path.join(f_pt_dir, "logs", f_combo.name)
                os.makedirs(f_dir, exist_ok=True)
                for f_rank in range(f_sp.tasks):
                    f_vals = rankValues(f_rank, f_salt)
                    with open(os.path.join(f_dir, f"rank_{f_rank}.log"), "w") as f_f:
                        f_f.write(rankLog(f_vals["write"], f_vals["read"]))
        return f_store.layout.runRoot, f_complete

    def _bmtoolEquivalentOf(
        self, f_run_root: str, f_complete: Set[Tuple[int, str]], f_dest: str
    ) -> None:
        """bmtool layout of just the complete combinations, aggregated by LsmioAggOutput."""
        f_resolved = RunRootResolver.resolve(f_run_root, f_allow_partial=True)
        for f_pt in f_resolved.points:
            for f_combo in f_resolved.plan.combinations:
                if (f_pt.ordinal, f_combo.name) not in f_complete:
                    continue
                for f_rank in range(f_pt.scalePoint.tasks):
                    f_dst = os.path.join(
                        f_dest,
                        str(f_pt.scalePoint.nodes),
                        "2026-10-07",
                        f"out-native-{f_combo.stripe_count}-{f_combo.block_size}"
                        f"-2026-10-07-node{100 + f_rank:03d}-0.txt",
                    )
                    os.makedirs(os.path.dirname(f_dst), exist_ok=True)
                    shutil.copyfile(
                        os.path.join(
                            f_pt.pointDir, "logs", f_combo.name, f"rank_{f_rank}.log"
                        ),
                        f_dst,
                    )
        with patch("lsmiotool.lib.log.Console.warning"):
            output.LsmioAggOutput(f_dest).generateReports(f_out_dir=f_dest)

    def testPartiallyFailedRunReportsCompleteCombinations(self) -> None:
        """'parse' reports every combination with complete rank output, warns about
        the rest and keeps exit code 4 (the run did not succeed)."""
        f_run_root, f_complete = self._setupPartialRun("run-partial-001")
        self.assertEqual(len(f_complete), 10)
        with self.assertRaises(Exception):
            RunRootResolver.resolve(f_run_root)  # strict resolution still refuses

        f_out = os.path.join(self.m_temp_dir, "reports")
        f_inst = ParseMain(
            f_request=parseParseArguments([f_run_root, "--output-dir", f_out])
        )
        f_stdout, f_stderr = io.StringIO(), io.StringIO()
        with patch("sys.stdout", f_stdout), patch("sys.stderr", f_stderr):
            f_code = f_inst.run()
        self.assertEqual(f_code, 4, f_stderr.getvalue())
        f_err = f_stderr.getvalue()
        self.assertIn("did not succeed", f_err)
        self.assertIn("01-tasks-2", f_err)
        self.assertIn("rank 1 has no successful result", f_err)
        self.assertIn("02-tasks-4", f_err)
        self.assertIn("c4_b64K", f_stdout.getvalue())

        f_bm = os.path.join(self.m_temp_dir, "bm-equivalent")
        self._bmtoolEquivalentOf(f_run_root, f_complete, f_bm)
        f_tree = readTree(f_out)
        self.assertEqual(f_tree, readTree(f_bm))
        self.assertEqual(len(f_tree), 11)  # 10 agg files + lsm-report.csv

        # The same run moved into an archive regenerates in place without raising
        f_arch = os.path.join(self.m_temp_dir, "variants", "outputs-native:run")
        shutil.copytree(f_run_root, f_arch)
        with patch("lsmiotool.lib.log.Console.warning"):
            self.assertIsNotNone(output.regenerateLsmioReports(f_arch))
        self.assertEqual(
            readFile(os.path.join(f_arch, data.LSM_REPORT_FILE)),
            readFile(os.path.join(f_bm, data.LSM_REPORT_FILE)),
        )

    def testRunWithNothingCompleteKeepsExitCode(self) -> None:
        """No complete combination: no report, exit 4 for a failed run."""
        f_run_root, _f_complete = self._setupPartialRun("run-partial-002")
        f_layout_logs = os.path.join(f_run_root, "points")
        for f_dir, _f_sub, f_files in os.walk(f_layout_logs):
            for f_name in f_files:
                if f_name.startswith("rank_") and f_name.endswith(".log"):
                    os.remove(os.path.join(f_dir, f_name))
        f_out = os.path.join(self.m_temp_dir, "reports-none")
        f_inst = ParseMain(
            f_request=parseParseArguments([f_run_root, "--output-dir", f_out])
        )
        f_stderr = io.StringIO()
        with patch("sys.stdout", io.StringIO()), patch("sys.stderr", f_stderr):
            self.assertEqual(f_inst.run(), 4)
        self.assertIn("no point/combination has complete output", f_stderr.getvalue())
        self.assertFalse(os.path.exists(os.path.join(f_out, data.LSM_REPORT_FILE)))

    def _parseRunAndBmtoolLayout(
        self, f_target: str, f_setup: str, f_log_for: Any
    ) -> Tuple[bytes, str]:
        """Parse a succeeded <f_target> 'local' run whose combination logs come from
        f_log_for(combo), and lay the same logs out in the archive layout. Returns the
        run parser's report and the layout directory."""
        f_run_root, f_plan, _ = self.m_helper._setupSucceededRun(
            f"run-{f_target}-bm-001", f_target, "local", f_setup
        )
        f_bm = os.path.join(self.m_temp_dir, f"bm-{f_target}")
        f_logs = os.path.join(f_run_root, "points", "00-tasks-1", "logs")
        os.makedirs(f_logs, exist_ok=True)
        for f_combo in f_plan.combinations:
            f_text = f_log_for(f_combo)
            with open(
                os.path.join(f_logs, f"{f_target}_{f_combo.name}.stdout"), "w"
            ) as f_f:
                f_f.write(f_text)
            if f_target != "ior":
                continue  # only the IOR test compares with the archive layout
            f_dst = os.path.join(
                f_bm,
                "1",
                "2026-10-07",
                f"out-{f_setup.lower()}-{f_combo.stripe_count}-{f_combo.block_size}"
                "-2026-10-07-node100-0.txt",
            )
            os.makedirs(os.path.dirname(f_dst), exist_ok=True)
            with open(f_dst, "w") as f_f:
                f_f.write(f_text)

        f_out = os.path.join(self.m_temp_dir, f"out-{f_target}")
        f_inst = ParseMain(
            f_request=parseParseArguments([f_run_root, "--output-dir", f_out])
        )
        f_stderr = io.StringIO()
        with patch("sys.stdout", io.StringIO()), patch("sys.stderr", f_stderr):
            self.assertEqual(f_inst.run(), 0, f_stderr.getvalue())
        f_name = data.IOR_REPORT_FILE if f_target == "ior" else data.LMP_REPORT_FILE
        return readFile(os.path.join(f_out, f_name)), f_bm

    def testRunParseIorReportLikeArchiveLayout(self) -> None:
        """The run parser's ior-report.csv rows equal the archive-layout writer's for the same logs."""
        f_example = os.path.join(EXAMPLE_IOR_OUTPUTS, "2", "2023-07-21")

        def logFor(f_combo: Any) -> str:
            f_name = next(
                f_n
                for f_n in sorted(os.listdir(f_example))
                if f"-{f_combo.stripe_count}-{f_combo.block_size}-" in f_n
            )
            with open(os.path.join(f_example, f_name)) as f_f:
                return f_f.read()

        f_ours, f_bm = self._parseRunAndBmtoolLayout("ior", "BASE", logFor)
        data.generateBmtoolIorReport(f_bm)
        self.assertEqual(f_ours, readFile(os.path.join(f_bm, data.IOR_REPORT_FILE)))
        self.assertEqual(len(f_ours.splitlines()), 12)

    def testRunParseLmpReportRows(self) -> None:
        """The run parser's lmp-report.csv holds, per combination, the last result
        line of its log (constructed fixture only)."""

        def logFor(f_combo: Any) -> str:
            f_seed = f_combo.stripe_count + len(f_combo.block_size)
            return lmpLog([100.0 + f_seed + f_i for f_i in range(10)])

        f_ours, _f_bm = self._parseRunAndBmtoolLayout("lmp", "LSMIO", logFor)
        self.assertEqual(
            f_ours.decode().splitlines(),
            [
                "1,4,64K,iwrite,116.00,116.00,116.00,18.25,1,1",
                "1,4,1M,iwrite,115.00,115.00,115.00,18.25,1,1",
                "1,4,8M,iwrite,115.00,115.00,115.00,18.25,1,1",
                "1,16,64K,iwrite,128.00,128.00,128.00,18.25,1,1",
                "1,16,1M,iwrite,127.00,127.00,127.00,18.25,1,1",
                "1,16,8M,iwrite,127.00,127.00,127.00,18.25,1,1",
            ],
        )

    def testArchivedLayoutPinsRunRoot(self) -> None:
        f_layout = ArchivedArtifactLayout("/a/b/outputs-x:run", "run-1")
        self.assertEqual(f_layout.runRoot, "/a/b/outputs-x:run")
        self.assertEqual(f_layout.manifestPath, "/a/b/outputs-x:run/manifest.json")
        self.assertEqual(f_layout.runId, "run-1")

    def testParseInfersLatestRunFromBenchmarkRootFilteredByTarget(self) -> None:
        """'parse lsmio' searches <benchmark_root>/runs and ignores other targets."""
        f_lsm_root, _p, _ = self.m_helper._setupSucceededRun(
            "run-20261001T000000Z-aaaa", "lsmio", "local"
        )
        self._writeRankLogs(f_lsm_root)
        self.m_helper._setupSucceededRun(
            "run-20261009T000000Z-bbbb", "ior", "local", "BASE"
        )
        # A bmtool working dir named after the benchmark must not shadow <root>/runs
        os.makedirs(os.path.join(self.m_temp_dir, "lsmio", "outputs"))

        f_out = os.path.join(self.m_temp_dir, "reports")
        f_inst = ParseMain(
            f_request=parseParseArguments(["lsmio", "--output-dir", f_out]),
            f_benchmark_root=self.m_temp_dir,
        )
        f_stdout, f_stderr = io.StringIO(), io.StringIO()
        with patch("sys.stdout", f_stdout), patch("sys.stderr", f_stderr):
            f_code = f_inst.run()
        self.assertEqual(f_code, 0, f_stderr.getvalue())
        self.assertTrue(data.isUsableReport(os.path.join(f_out, data.LSM_REPORT_FILE)))

        # Scale filter: no lsmio 'small' run exists
        f_inst = ParseMain(
            f_request=parseParseArguments(["lsmio", "small", "--output-dir", f_out]),
            f_benchmark_root=self.m_temp_dir,
        )
        with patch("sys.stdout", io.StringIO()), patch("sys.stderr", io.StringIO()):
            self.assertEqual(f_inst.run(), 3)


class ParseArchiveModeTest(unittest.TestCase):
    """'parse lsmio backends <scale>' / 'parse <archive dir>' / compare on archives."""

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.mkdtemp(prefix="lsmiotool-parsearchive-")

    def tearDown(self) -> None:
        shutil.rmtree(self.m_temp_dir, ignore_errors=True)

    def _run(self, f_argv: List[str]) -> int:
        f_inst = ParseMain(
            f_request=parseParseArguments(f_argv), f_benchmark_root=self.m_temp_dir
        )
        with patch("sys.stdout", io.StringIO()), patch("sys.stderr", io.StringIO()):
            with patch("lsmiotool.lib.log.Console.warning"):
                return f_inst.run()

    def testCliAcceptsScaleForms(self) -> None:
        self.assertEqual(parseParseArguments(["lsmio", "small"]).scale, "small")
        self.assertEqual(parseParseArguments(["lsmio", "baseline"]).scale, "variants")
        f_req = parseParseArguments(["lsmio", "backends", "small"])
        self.assertEqual((f_req.mode, f_req.scale), ("backends", "small"))

    def testParseBackendsRegeneratesEveryArm(self) -> None:
        f_dest = os.path.join(self.m_temp_dir, "lsmio-archive", "backends", "small")
        for f_arm in ("adios", "native"):
            writeBmtoolLayout(
                os.path.join(f_dest, f"outputs-{f_arm}"), ["1", "2"], f_arm
            )
        self.assertEqual(self._run(["lsmio", "backends", "small"]), 0)
        for f_arm in ("adios", "native"):
            f_report = os.path.join(f_dest, f"outputs-{f_arm}", data.LSM_REPORT_FILE)
            with open(f_report) as f_f:
                f_rows = f_f.read().splitlines()
            self.assertEqual(len(f_rows), 24)
            self.assertTrue(f_rows[0].startswith("1,16,1M,write,"))

    def testParseIorRegeneratesIorArchiveOnly(self) -> None:
        """'parse ior <scale>' rebuilds ior-report.csv (ior-parse.sh) in every IOR setup
        'run ior' archived to lsmio-archive/ior/<scale>; 'parse lsmio backends' never
        reads IOR outputs, even one moved next to the backends."""
        from lsmiotool.test.main.ArmGroupTest import IOR_SUMMARY

        def iorArm(f_dir: str) -> str:
            f_day = os.path.join(f_dir, "2", "2026-10-14")
            os.makedirs(f_day)
            with open(
                os.path.join(f_day, "out-collective-16-8M-2026-10-14-node097-0.txt"),
                "w",
            ) as f_f:
                f_f.write(IOR_SUMMARY)
            return f_dir

        f_archive = os.path.join(self.m_temp_dir, "lsmio-archive")
        f_ior = iorArm(
            os.path.join(f_archive, "ior", "small", "outputs-ior-collective")
        )
        self.assertEqual(self._run(["ior", "small"]), 0)
        with open(os.path.join(f_ior, data.IOR_REPORT_FILE)) as f_f:
            f_rows = f_f.read().splitlines()
        self.assertEqual(
            [f_r.split(",")[:5] for f_r in f_rows],
            [
                ["2", "16", "8M", "write", "1650.38"],
                ["2", "16", "8M", "read", "12824.95"],
            ],
        )
        self.assertFalse(os.path.exists(os.path.join(f_ior, data.LSM_REPORT_FILE)))

        f_dest = os.path.join(f_archive, "backends", "small")
        writeBmtoolLayout(os.path.join(f_dest, "outputs-native"), ["1"], "native")
        f_stray = iorArm(os.path.join(f_dest, "outputs-ior"))
        self.assertEqual(self._run(["lsmio", "backends", "small"]), 0)
        self.assertEqual(os.listdir(f_stray), ["2"])
        self.assertTrue(
            data.isUsableReport(
                os.path.join(f_dest, "outputs-native", data.LSM_REPORT_FILE)
            )
        )
        # An archive with no IOR setup has nothing for 'parse ior'
        self.assertEqual(self._run(["ior", "large"]), 3)

        # Path form: an IOR arm, or a folder holding one, gets ior-report.csv only
        os.remove(os.path.join(f_ior, data.IOR_REPORT_FILE))
        self.assertEqual(self._run([os.path.dirname(f_ior)]), 0)
        self.assertTrue(data.isUsableReport(os.path.join(f_ior, data.IOR_REPORT_FILE)))
        os.remove(os.path.join(f_ior, data.IOR_REPORT_FILE))
        self.assertEqual(self._run([f_ior]), 0)
        self.assertTrue(data.isUsableReport(os.path.join(f_ior, data.IOR_REPORT_FILE)))
        self.assertEqual(self._run([f_dest]), 0)
        self.assertTrue(
            data.isUsableReport(os.path.join(f_stray, data.IOR_REPORT_FILE))
        )
        # --output-dir: the report goes there, the arm is left as it is
        f_out = os.path.join(self.m_temp_dir, "reports")
        os.remove(os.path.join(f_ior, data.IOR_REPORT_FILE))
        self.assertEqual(self._run([f_ior, "--output-dir", f_out]), 0)
        self.assertTrue(data.isUsableReport(os.path.join(f_out, data.IOR_REPORT_FILE)))
        self.assertFalse(os.path.exists(os.path.join(f_ior, data.IOR_REPORT_FILE)))
        # IOR outputs are reported as csv only, like 'parse ior <scale>'
        for f_target in (f_ior, os.path.dirname(f_ior), f_dest):
            self.assertEqual(self._run([f_target, "--format", "json"]), 2)
        for f_dir in (f_ior, f_stray):
            self.assertFalse(os.path.exists(os.path.join(f_dir, data.LSM_REPORT_FILE)))
            self.assertEqual(
                [
                    f_n
                    for f_n in os.listdir(os.path.join(f_dir, "2"))
                    if f_n.startswith("agg-")
                ],
                [],
            )

    def testBareBenchmarkNameIsNeverACwdDirectory(self) -> None:
        """'parse lsmio <scale>' resolves runs even when the cwd has a lsmio/ dir with
        outputs-* children (bmtool leaves $BM_PATH/lsmio/outputs-failed); './lsmio' parses it."""
        f_cwd = os.path.join(self.m_temp_dir, "cwd")
        f_failed = os.path.join(f_cwd, "lsmio", "outputs-failed")
        writeBmtoolLayout(f_failed, ["8"], "native")
        f_orig_cwd = os.getcwd()
        os.chdir(f_cwd)
        try:
            self.assertEqual(self._run(["lsmio", "small"]), 3)  # no runs to parse
            self.assertFalse(
                os.path.exists(os.path.join(f_failed, data.LSM_REPORT_FILE))
            )
            self.assertEqual(self._run(["./lsmio"]), 0)
        finally:
            os.chdir(f_orig_cwd)
        self.assertTrue(
            data.isUsableReport(os.path.join(f_failed, data.LSM_REPORT_FILE))
        )

    def testParseVariantsParsesRunsNotArchive(self) -> None:
        """Like bmtool lsmio-parse.sh, only backends mode reads the archive: 'parse lsmio
        variants' parses the latest run and leaves archived arms alone (R4)."""
        f_dest = os.path.join(self.m_temp_dir, "lsmio-archive", "variants")
        f_arm = os.path.join(f_dest, "outputs-native-autotune:run")
        writeBmtoolLayout(f_arm, ["8"], "native-autotune")
        self.assertEqual(self._run(["lsmio", "variants"]), 3)  # no runs to parse
        self.assertFalse(os.path.exists(os.path.join(f_arm, data.LSM_REPORT_FILE)))
        # An archive dest is still parsed when named explicitly
        self.assertEqual(self._run([f_dest]), 0)
        self.assertTrue(data.isUsableReport(os.path.join(f_arm, data.LSM_REPORT_FILE)))

    def testParseMissingArchiveDestination(self) -> None:
        self.assertEqual(self._run(["lsmio", "backends", "large"]), 3)

    def testParseBmtoolLayoutDirectory(self) -> None:
        f_dir = os.path.join(self.m_temp_dir, "outputs-native")
        writeBmtoolLayout(f_dir, ["1"])
        self.assertEqual(self._run([f_dir]), 0)
        self.assertTrue(data.isUsableReport(os.path.join(f_dir, data.LSM_REPORT_FILE)))

    def testCompareVariantsNeverWritesEmptyReport(self) -> None:
        """compare variants regenerates bmtool-layout arms and leaves data-less ones alone."""
        f_archive = os.path.join(self.m_temp_dir, "variants")
        writeBmtoolLayout(
            os.path.join(f_archive, "outputs-native-autotune"), ["8"], "native-autotune"
        )
        f_empty_arm = os.path.join(f_archive, "outputs-native-legacy")
        os.makedirs(f_empty_arm)
        f_zero_arm = os.path.join(f_archive, "outputs-native-mmap")
        os.makedirs(f_zero_arm)
        open(os.path.join(f_zero_arm, data.LSM_REPORT_FILE), "w").close()

        f_cm = CompareVariantsMain(
            f_archive_folder=f_archive,
            f_op="write",
            f_stripes=4,
            f_blocksize="1M",
            f_output_dir=os.path.join(self.m_temp_dir, "plots"),
        )
        with (
            patch("lsmiotool.lib.log.Console.warning"),
            patch("lsmiotool.lib.log.Console.info"),
        ):
            self.assertEqual(f_cm.run(), 0)
        self.assertTrue(
            data.isUsableReport(
                os.path.join(f_archive, "outputs-native-autotune", data.LSM_REPORT_FILE)
            )
        )
        self.assertFalse(
            os.path.exists(os.path.join(f_empty_arm, data.LSM_REPORT_FILE))
        )
        self.assertEqual(
            os.path.getsize(os.path.join(f_zero_arm, data.LSM_REPORT_FILE)), 0
        )


class ParseIorOutputsDirTest(unittest.TestCase):
    """'parse <dir>' routes an IOR outputs dir by name or by the IOR banner."""

    IOR_ROW = (
        "1,16,64K,write,887.21,773.61,839.98,35.41,14195.36,12377.73,13439.62,566.57,"
    )

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.mkdtemp(prefix="lsmiotool-iordir-")

    def tearDown(self) -> None:
        shutil.rmtree(self.m_temp_dir, ignore_errors=True)

    def _copyExample(self, f_name: str) -> str:
        f_dir = os.path.join(self.m_temp_dir, f_name)
        shutil.copytree(EXAMPLE_IOR_OUTPUTS, f_dir)
        return f_dir

    def _run(self, f_argv: List[str]) -> Tuple[int, str, str]:
        f_inst = ParseMain(
            f_request=parseParseArguments(f_argv), f_benchmark_root=self.m_temp_dir
        )
        f_stdout, f_stderr = io.StringIO(), io.StringIO()
        with patch("sys.stdout", f_stdout), patch("sys.stderr", f_stderr):
            with patch("lsmiotool.lib.log.Console.warning"):
                f_code = f_inst.run()
        return f_code, f_stdout.getvalue(), f_stderr.getvalue()

    def _assertNoLsmioFiles(self, f_dir: str) -> None:
        self.assertEqual(readTree(f_dir), {})

    def _truncateLogs(self, f_dir: str) -> None:
        """Keep the banner and a few header lines: no write/read summary rows."""
        for f_root, _f_subdirs, f_files in os.walk(f_dir):
            for f_name in f_files:
                f_path = os.path.join(f_root, f_name)
                with open(f_path) as f_f:
                    f_head = f_f.readlines()[:5]
                with open(f_path, "w") as f_f:
                    f_f.writelines(f_head)

    def testContentClassifiedDirectory(self) -> None:
        f_dir = self._copyExample("output-ior-reverse")
        f_twin = self._copyExample("twin")
        f_code, f_out, f_err = self._run([f_dir])
        self.assertEqual(f_code, 0, f_err)
        f_report = os.path.join(f_dir, data.IOR_REPORT_FILE)
        self.assertTrue(f_out.rstrip("\n").endswith(f_report), f_out)
        self.assertIn("=== Generating report for output-ior-reverse ===", f_out)
        output.IorAggOutput(f_twin).generateReports()
        f_bytes = readFile(f_report)
        self.assertIn(self.IOR_ROW.encode(), f_bytes)
        self.assertEqual(f_bytes, readFile(os.path.join(f_twin, data.IOR_REPORT_FILE)))
        self._assertNoLsmioFiles(f_dir)

    def testOutputDirOptionAndJson(self) -> None:
        f_dir = self._copyExample("output-ior-reverse")
        f_snapshot = sorted(
            os.path.join(r, n) for r, _d, fs in os.walk(f_dir) for n in fs
        )
        f_dest = os.path.join(self.m_temp_dir, "reports")
        f_code, f_out, f_err = self._run([f_dir, "--output-dir", f_dest])
        self.assertEqual(f_code, 0, f_err)
        f_report = os.path.join(f_dest, data.IOR_REPORT_FILE)
        self.assertEqual(f_out.strip(), f_report)
        self.assertIn(self.IOR_ROW.encode(), readFile(f_report))
        self.assertEqual(
            f_snapshot,
            sorted(os.path.join(r, n) for r, _d, fs in os.walk(f_dir) for n in fs),
        )
        self.assertEqual(self._run([f_dir, "--format", "json"])[0], 2)

    def testNoBannerInFirstSortedLogStillIor(self) -> None:
        f_dir = self._copyExample("output-ior-hdf5")
        f_first = os.path.join(f_dir, "0", "2023-07-21")
        os.makedirs(f_first)
        with open(os.path.join(f_first, "out-hdf5-4-1M-x-node001-0.txt"), "w") as f_f:
            f_f.write("HDF5-DIAG: Error detected in HDF5 (1.14.0) MPI-process 0:\n")
        f_code, f_out, f_err = self._run([f_dir])
        self.assertEqual(f_code, 0, f_err)
        self.assertTrue(
            data.isUsableReport(os.path.join(f_dir, data.IOR_REPORT_FILE))
        )
        self.assertIn("=== Generating report for output-ior-hdf5 ===", f_out)
        self._assertNoLsmioFiles(f_dir)

    def testExistingReportWithoutSummaryRowsIsKept(self) -> None:
        for f_name in ("outputs-ior", "output-ior-x"):
            f_dir = self._copyExample(f_name)
            self._truncateLogs(f_dir)
            f_report = os.path.join(f_dir, data.IOR_REPORT_FILE)
            with open(f_report, "w") as f_f:
                f_f.write("old,report\n")
            f_code, f_out, f_err = self._run([f_dir])
            self.assertEqual(f_code, 5, f_name)
            self.assertIn(f"Warning: no IOR results found in {f_dir}", f_err)
            self.assertEqual(readFile(f_report), b"old,report\n", f_name)
            self.assertNotIn(f_report, f_out)

            f_dest = os.path.join(self.m_temp_dir, f"dest-{f_name}")
            os.makedirs(f_dest)
            with open(os.path.join(f_dest, data.IOR_REPORT_FILE), "w") as f_f:
                f_f.write("stale\n")
            f_code, f_out, f_err = self._run([f_dir, "--output-dir", f_dest])
            self.assertEqual(f_code, 5, f_name)
            self.assertIn("Warning: no IOR results found", f_err)
            self.assertEqual(
                readFile(os.path.join(f_dest, data.IOR_REPORT_FILE)), b"stale\n"
            )
            self.assertEqual(readFile(f_report), b"old,report\n")

    def testWriterExceptionMapping(self) -> None:
        for f_name in ("outputs-ior", "output-ior-x"):
            f_dir = self._copyExample(f_name)
            with patch(
                "lsmiotool.lib.data.generateBmtoolIorReport",
                side_effect=RuntimeError("boom"),
            ):
                f_code, _f_out, f_err = self._run([f_dir])
                self.assertEqual(f_code, 5, f_name)
                self.assertIn(f"Error: failed to parse {f_dir}: boom", f_err)
                f_dest = os.path.join(self.m_temp_dir, f"dest-{f_name}")
                f_code, _f_out, f_err = self._run([f_dir, "--output-dir", f_dest])
                self.assertEqual(f_code, 1, f_name)
                self.assertIn("Error: boom", f_err)

    def testParentTargetClassifiesEachChild(self) -> None:
        f_parent = os.path.join(self.m_temp_dir, "parent")
        f_native = os.path.join(f_parent, "outputs-native")
        writeBmtoolLayout(f_native, ["1"], "native")
        shutil.copytree(EXAMPLE_IOR_OUTPUTS, os.path.join(f_parent, "outputs-reverse"))
        f_code, _f_out, f_err = self._run([f_parent])
        self.assertEqual(f_code, 0, f_err)
        self.assertTrue(
            data.isUsableReport(os.path.join(f_native, data.LSM_REPORT_FILE))
        )
        self.assertFalse(os.path.exists(os.path.join(f_native, data.IOR_REPORT_FILE)))
        f_reverse = os.path.join(f_parent, "outputs-reverse")
        self.assertTrue(
            data.isUsableReport(os.path.join(f_reverse, data.IOR_REPORT_FILE))
        )
        self._assertNoLsmioFiles(f_reverse)
        self.assertEqual(self._run([f_parent, "--format", "json"])[0], 2)


if __name__ == "__main__":
    unittest.main()
