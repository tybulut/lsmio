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

import csv
import os
import tempfile
import unittest
from typing import Dict, List, Sequence
from unittest.mock import patch

from lsmiotool.lib import output
from lsmiotool.lib.phasereport import LSM_PHASE_REPORT_FILE, PHASE_REPORT_COLUMNS
from lsmiotool.test.fixtures.ArchiveLayoutFixtures import readTree, writeBmtoolLayout
from lsmiotool.test.fixtures.MockLogGenerator import MockLogGenerator
from lsmiotool.test.parse.PhaseReportTest import BM_HEADER, ONE_MIB, sampleSuite

LAYOUT_DATE = "2026-10-07"
PHASE_HEADER = [
    " mpi-barrier: 1",
    " durability: engine",
    " rankShift: 1",
    " rankShiftNodes: shared",
    " rankShiftSelfRanks: 8",
    " rankShiftSameHostRanks: 8",
    " perRankPath: 1",
]
FOUR_PREFIXES = [
    "Native Flush: true BLF: false",
    "Native Flush: false BLF: true",
    "Native Flush: true BLF: true",
    "Native Sync: true",
]


def rankLogPath(f_root: str, f_stripe: str, f_block: str, f_rank: int) -> str:
    """Path of one rank log that writeBmtoolLayout creates for node count 8."""
    return os.path.join(
        f_root,
        "8",
        LAYOUT_DATE,
        f"out-native-{f_stripe}-{f_block}-{LAYOUT_DATE}-node{100 + f_rank:03d}-0.txt",
    )


def phasedLog(f_plain: str, f_bytes: int, f_header: Sequence[str] = PHASE_HEADER) -> str:
    """Wrap a plain rank log: header block first, four suites' iteration rows and Phases: blocks after.

    The appended legacy rows are iwrite/iread rows only (no write/read summary lines), so the
    bmtool aggregate of the log is that of the plain log.
    """
    f_suites = [
        sampleSuite(f_prefix, f_bytes=f_bytes + f_idx * ONE_MIB)
        for f_idx, f_prefix in enumerate(FOUR_PREFIXES)
    ]
    f_lines = list(f_header) + [f_plain.rstrip("\n")]
    for f_prefix, f_writes, f_reads, _ in f_suites:
        f_lines += ["", f"Iteration-WRITE: {f_prefix}"] + BM_HEADER + f_writes
        f_lines += ["", f"Iteration-READ: {f_prefix}"] + BM_HEADER + f_reads
    for f_prefix, _, _, f_phases in f_suites:
        f_lines += ["", f"Phases: {f_prefix}"] + f_phases
    return "\n".join(f_lines) + "\n"


class LsmioAggOutputTest(unittest.TestCase):
    """Unit tests for LsmioAggOutput baseline node scoping and log aggregation."""

    STANDARD_NODE_COUNTS: List[str] = [
        "1",
        "2",
        "4",
        "8",
        "16",
        "24",
        "32",
        "40",
        "48",
    ]

    m_temp_dir: tempfile.TemporaryDirectory
    m_mock_gen: MockLogGenerator

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.TemporaryDirectory()
        self.m_mock_gen = MockLogGenerator(self.m_temp_dir.name)

    def tearDown(self) -> None:
        self.m_temp_dir.cleanup()

    def testStandardNodeCountsWhenScaleNotBaseline(self) -> None:
        """Asserts that _node_counts contains standard 9 node counts when scale is not baseline."""
        # When f_scale is omitted or None (standard legacy scales)
        # We test the node configuration without calling super().__init__ by inspecting class attribute
        self.assertEqual(output.LsmioAggOutput._node_counts, self.STANDARD_NODE_COUNTS)

        # Generate standard mock directory tree with all 9 nodes
        self.m_mock_gen.generateMockDirectoryTree(
            self.m_temp_dir.name,
            f_bench_type="lsmio",
            f_nodes=self.STANDARD_NODE_COUNTS,
            f_stripes=["4", "16"],
            f_sizes=["64K", "1M", "8M"],
        )

        agg_default = output.LsmioAggOutput(self.m_temp_dir.name)
        self.assertEqual(agg_default._node_counts, self.STANDARD_NODE_COUNTS)

        agg_local = output.LsmioAggOutput(self.m_temp_dir.name, f_scale="local")
        self.assertEqual(agg_local._node_counts, self.STANDARD_NODE_COUNTS)

    def testBaselineNodeCountsScopedToEight(self) -> None:
        """Asserts that _node_counts is scoped strictly to ['8'] when scale is baseline."""
        # Generate mock directory tree containing only node '8'
        self.m_mock_gen.generateMockDirectoryTree(
            self.m_temp_dir.name,
            f_bench_type="lsmio",
            f_nodes=["8"],
            f_stripes=["4", "16"],
            f_sizes=["64K", "1M", "8M"],
        )

        # Lowercase baseline
        agg_baseline = output.LsmioAggOutput(self.m_temp_dir.name, f_scale="baseline")
        self.assertEqual(agg_baseline._node_counts, ["8"])

        # Uppercase BASELINE (case insensitivity)
        agg_baseline_upper = output.LsmioAggOutput(
            self.m_temp_dir.name, f_scale="BASELINE"
        )
        self.assertEqual(agg_baseline_upper._node_counts, ["8"])

    def testBaselineOutputProcessingWithoutMissingDataError(self) -> None:
        """Asserts that baseline scale processes successfully without MissingDataError for absent nodes."""
        # Generate mock directory tree containing only node '8'
        self.m_mock_gen.generateMockDirectoryTree(
            self.m_temp_dir.name,
            f_bench_type="lsmio",
            f_nodes=["8"],
            f_stripes=["4", "16"],
            f_sizes=["64K", "1M", "8M"],
        )

        # Processing with f_scale='baseline' must succeed cleanly without MissingDataError
        agg = output.LsmioAggOutput(self.m_temp_dir.name, f_scale="baseline")
        agg_map = agg.getMap()

        self.assertIn("8", agg_map)
        self.assertNotIn("1", agg_map)
        self.assertNotIn("2", agg_map)
        self.assertNotIn("16", agg_map)

        # Verify metrics aggregated for node 8
        self.assertIn("4", agg_map["8"])
        self.assertIn("16", agg_map["8"])
        self.assertIn("64K", agg_map["8"]["4"])
        self.assertIn("write", agg_map["8"]["4"]["64K"])
        self.assertIn("read", agg_map["8"]["4"]["64K"])

    def testMissingDataErrorOnIncompleteNodeEightFiles(self) -> None:
        """Asserts that MissingDataError is raised when expected file count for node 8 mismatches actual files."""
        base = self.m_temp_dir.name
        n_dir = os.path.join(base, "8", "2026-09-09")
        os.makedirs(n_dir, exist_ok=True)
        # Create only 1 file when 8 are expected for node 8
        f1 = os.path.join(n_dir, "out-lsmio-4-64K-2026-09-09-node000-0.txt.8")
        self.m_mock_gen.generateLsmioFile(f1, 8, 4, "64K")

        # Construction stays lazy so report generation never raises; the strict
        # per-node map does
        agg = output.LsmioAggOutput(base, f_scale="baseline")
        with self.assertRaises(output.MissingDataError):
            agg.getMap()

    def _writePhasedTree(self, f_root: str) -> None:
        """Layout of node count 8 with phase rows in the stripe 4 and 16, block 1M logs.

        Stripe 4: rank 0 prints (source), rank 1 prints the same records, rank 2 prints
        other records, rank 3 has the header lines but no phase row, ranks 4-7 are old-format
        logs. Stripe 16: rank 0 prints 200 MiB records; the others are old-format logs.
        """
        writeBmtoolLayout(f_root, ["8"], f_date=LAYOUT_DATE)
        for f_stripe, f_ranks in (("4", range(4)), ("16", range(1))):
            for f_rank in f_ranks:
                f_path = rankLogPath(f_root, f_stripe, "1M", f_rank)
                with open(f_path, "r", encoding="utf-8") as f_f:
                    f_plain = f_f.read()
                if f_stripe == "4" and f_rank == 3:
                    f_text = "\n".join(PHASE_HEADER) + "\n" + f_plain
                else:
                    f_bytes = 200 if f_stripe == "16" else 100 + (f_rank == 2)
                    f_text = phasedLog(f_plain, f_bytes * ONE_MIB)
                with open(f_path, "w", encoding="utf-8") as f_f:
                    f_f.write(f_text)

    def _generate(self, f_root: str, f_out_dir: str = "") -> List[str]:
        """Run generateReports with baseline scale; return the phase report's warnings."""
        f_agg = output.LsmioAggOutput(f_root, f_scale="baseline")
        with patch.object(output.Console, "warning") as f_warn:
            f_agg.generateReports(f_out_dir or None)
        return [str(f_call.args[0]) for f_call in f_warn.call_args_list]

    def testPhaseReportFromBmtoolLayout(self) -> None:
        """Phase rows in rank logs give lsm-phase-report.csv; every other report is unchanged (INV-22)."""
        f_phased = os.path.join(self.m_temp_dir.name, "phased")
        f_plain = os.path.join(self.m_temp_dir.name, "plain")
        self._writePhasedTree(f_phased)
        writeBmtoolLayout(f_plain, ["8"], f_date=LAYOUT_DATE)

        f_warnings = self._generate(f_phased)
        self.assertEqual(self._generate(f_plain), [])

        # Only the disagreeing printer warns, once, naming both logs
        self.assertEqual(len(f_warnings), 1, f_warnings)
        self.assertIn(os.path.basename(rankLogPath(f_phased, "4", "1M", 2)), f_warnings[0])
        self.assertIn(os.path.basename(rankLogPath(f_phased, "4", "1M", 0)), f_warnings[0])

        f_phase_path = os.path.join(f_phased, LSM_PHASE_REPORT_FILE)
        with open(f_phase_path, "r", encoding="utf-8") as f_f:
            self.assertEqual(f_f.readline().rstrip("\n"), ",".join(PHASE_REPORT_COLUMNS))
            f_f.seek(0)
            f_rows = list(csv.DictReader(f_f))
        # 2 stripes x 4 prefixes x 2 iterations x 2 sides; stripe 4 before stripe 16
        self.assertEqual(len(f_rows), 32)
        self.assertEqual([f_r["stripe"] for f_r in f_rows], ["4"] * 16 + ["16"] * 16)
        for f_stripe, f_first in (("4", 0), ("16", 16)):
            f_set = f_rows[f_first : f_first + 16]
            f_source = os.path.join("8", LAYOUT_DATE, os.path.basename(rankLogPath(f_phased, f_stripe, "1M", 0)))
            self.assertEqual(
                [f_r["prefix"] for f_r in f_set],
                [f_p for f_p in FOUR_PREFIXES for _ in range(4)],
            )
            self.assertEqual(
                [(f_r["iteration"], f_r["side"]) for f_r in f_set],
                [("0", "write"), ("0", "read"), ("1", "write"), ("1", "read")] * 4,
            )
            f_bytes = 200 if f_stripe == "16" else 100
            for f_idx, f_row in enumerate(f_set):
                self.assertEqual(f_row["nodes"], "8")
                self.assertEqual(f_row["block"], "1M")
                self.assertEqual(f_row["bytes"], str((f_bytes + f_idx // 4) * ONE_MIB))
                self.assertEqual(f_row["source_log"], f_source.replace(os.sep, "/"))
                self.assertEqual(f_row["legacy_check"], "ok")
                self.assertEqual(f_row["durability"], "engine")
                self.assertEqual(f_row["rank_shift"], "1")
                self.assertEqual(f_row["rank_shift_nodes"], "shared")
                self.assertEqual(f_row["rank_shift_self_ranks"], "8")
                self.assertEqual(f_row["rank_shift_same_host_ranks"], "8")
                self.assertEqual(f_row["per_rank_path"], "1")
                self.assertEqual(f_row["full_us"], "1552000")
                self.assertEqual(f_row["gap_us"], "100000" if f_row["side"] == "read" else "")
            # 100 MiB / 1.552 s and 200 MiB / 1.552 s (hand-computed, see PhaseReportTest)
            self.assertEqual(f_set[0]["full_mibs"], "128.87" if f_stripe == "16" else "64.43")

        # INV-22: the agg and master reports equal those of the tree without phase rows
        f_phased_tree = readTree(f_phased)
        self.assertEqual(f_phased_tree, readTree(f_plain))
        self.assertIn("lsm-report.csv", f_phased_tree)
        self.assertIn(os.path.join("8", "agg-4-1M-report.csv"), f_phased_tree)
        self.assertIn(os.path.join("8", "agg-16-1M-report.csv"), f_phased_tree)
        self.assertFalse(os.path.exists(os.path.join(f_plain, LSM_PHASE_REPORT_FILE)))

    def testNoPhaseReportWithoutPhaseRows(self) -> None:
        """Old logs only give no lsm-phase-report.csv (INV-23); an earlier file stays (NB23)."""
        f_root = self.m_temp_dir.name
        writeBmtoolLayout(f_root, ["8"], f_date=LAYOUT_DATE)
        self.assertEqual(self._generate(f_root), [])
        f_path = os.path.join(f_root, LSM_PHASE_REPORT_FILE)
        self.assertFalse(os.path.exists(f_path))
        self.assertIn("lsm-report.csv", readTree(f_root))

        with open(f_path, "w", encoding="utf-8") as f_f:
            f_f.write("earlier report\n")
        self.assertEqual(self._generate(f_root), [])
        with open(f_path, "r", encoding="utf-8") as f_f:
            self.assertEqual(f_f.read(), "earlier report\n")

    def testPhaseReportGoesToTargetDirectory(self) -> None:
        """With f_out_dir, rank logs are read from the source and the phase report is written to the target."""
        f_root = os.path.join(self.m_temp_dir.name, "source")
        f_target = os.path.join(self.m_temp_dir.name, "target")
        self._writePhasedTree(f_root)
        self._generate(f_root, f_target)

        self.assertFalse(os.path.exists(os.path.join(f_root, LSM_PHASE_REPORT_FILE)))
        with open(os.path.join(f_target, LSM_PHASE_REPORT_FILE), "r", encoding="utf-8") as f_f:
            f_rows: List[Dict[str, str]] = list(csv.DictReader(f_f))
        self.assertEqual(len(f_rows), 32)
        # source_log is relative to the directory the rank logs were read from
        self.assertEqual(
            f_rows[0]["source_log"],
            f"8/{LAYOUT_DATE}/{os.path.basename(rankLogPath(f_root, '4', '1M', 0))}",
        )
        self.assertIn("lsm-report.csv", readTree(f_target))


def touch(f_path: str, f_text: str = "") -> str:
    """Create f_path (and its parent directories) with f_text and return it."""
    os.makedirs(os.path.dirname(f_path), exist_ok=True)
    with open(f_path, "w", encoding="utf-8") as f_f:
        f_f.write(f_text)
    return f_path


def loggedMessages(f_mock) -> List[str]:
    """The message text of every call of a mocked IorAggOutput._log_error."""
    return [str(list(f_call.args[0].values())[0]) for f_call in f_mock.call_args_list]


class OutputDirectoryTraversalTest(unittest.TestCase):
    """TraverseDir and IorOutputDir: what they map and what they skip."""

    def setUp(self) -> None:
        self.m_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.m_tmp.cleanup)
        self.m_root = self.m_tmp.name

    def testTraverseDirExposesRootAndRecursiveMap(self) -> None:
        touch(os.path.join(self.m_root, "a.txt"), "12345")
        touch(os.path.join(self.m_root, "d", "b.txt"))

        traverse = output.TraverseDir(self.m_root)

        self.assertEqual(traverse.root_dir, self.m_root)
        self.assertEqual(traverse.dir_recursive, {"a.txt": 5, "d": {"b.txt": 0}})
        self.assertIs(traverse.getMap(), traverse.dir_recursive)

    def testMissingDirectoryMapsToNothing(self) -> None:
        traverse = output.TraverseDir(os.path.join(self.m_root, "absent"))

        self.assertEqual(traverse.dir_recursive, {})

    def testUnreadableFileSizeCountsAsZero(self) -> None:
        touch(os.path.join(self.m_root, "a.txt"), "12345")

        with patch("os.path.getsize", side_effect=OSError("denied")):
            traverse = output.TraverseDir(self.m_root)

        self.assertEqual(traverse.dir_recursive, {"a.txt": 0})

    def testIorOutputDirSkipsNestedDirectoriesAndForeignNames(self) -> None:
        touch(os.path.join(self.m_root, "stray.txt"), "x")
        touch(os.path.join(self.m_root, "1", "loose.txt"), "x")
        date_dir = os.path.join(self.m_root, "1", "2023-07-21")
        valid = touch(os.path.join(date_dir, "out-ior-4-64K-x.txt"), "abc")
        touch(os.path.join(date_dir, "nested", "out-ior-8-1M-y.txt"), "abc")
        touch(os.path.join(date_dir, "notes.txt"), "abc")

        mapping = output.IorOutputDir(self.m_root).getMap()

        self.assertEqual(
            mapping,
            {"1": {"4": {"64K": {"out-ior-4-64K-x.txt": {"size": 3, "path": valid}}}}},
        )


class IorAggOutputGapTest(unittest.TestCase):
    """IorAggOutput on partial directories, its accessors and its CSV export."""

    def setUp(self) -> None:
        self.m_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.m_tmp.cleanup)
        self.m_root = self.m_tmp.name

    def testPartialLayoutLogsEachMissingPartAndKeepsEmptyEntries(self) -> None:
        date_dir = os.path.join(self.m_root, "1", "2023-07-21")
        touch(os.path.join(date_dir, "out-ior-4-64K-a.txt"))
        touch(os.path.join(date_dir, "out-ior-4-64K-b.txt"))

        agg = output.IorAggOutput(self.m_root)
        with patch.object(output.IorAggOutput, "_log_error") as log_error:
            agg_data = agg.getMap()

        messages = loggedMessages(log_error)
        for expected in (
            "node count not found in output directory",
            "stripe count not found in output directory",
            "stripe size not found in output directory",
            "number of files does not match node count",
            "number of simulation data does not match node count",
        ):
            self.assertIn(expected, messages)
        # Both rank logs are empty, so they carry no data
        self.assertEqual(agg_data["1"]["4"]["64K"], {})
        self.assertEqual(agg_data["1"]["4"]["1M"], [])
        self.assertEqual(agg_data["1"]["16"]["64K"], [])
        self.assertEqual(agg_data["2"]["4"]["64K"], [])
        self.assertEqual(agg.out_dir, self.m_root)
        self.assertIs(agg.agg_data, agg_data)

    def testExportCsvWritesRowsLinesAndText(self) -> None:
        agg = output.IorAggOutput(self.m_root)
        cases = (
            ("rows", [("a", "b"), ["1", "2"], "text  ", 5], "a,b\r\n1,2\r\ntext\n"),
            ("text", "x,y\n", "x,y\n"),
            ("other", None, ""),
        )
        for name, rows, expected in cases:
            with self.subTest(name):
                out_file = os.path.join(self.m_root, "new-dir", f"{name}.csv")
                agg.exportCsv(rows, out_file)
                with open(out_file, "r", encoding="utf-8", newline="") as f_f:
                    self.assertEqual(f_f.read(), expected)


class LsmioAggOutputGapTest(unittest.TestCase):
    """LsmioAggOutput accessors, partial metric records and the report-generation guards."""

    def setUp(self) -> None:
        self.m_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.m_tmp.cleanup)
        self.m_root = self.m_tmp.name

    @staticmethod
    def metrics(f_scale: float) -> Dict[str, object]:
        return {
            "max(MiB)/s": f_scale * 4.0,
            "min(MiB/s)": f_scale * 1.0,
            "mean(MiB/s)": f_scale * 2.0,
            "total(MiB)": f_scale * 10.0,
            "total(Ops)": f_scale * 20.0,
            "iteration": 3,
        }

    def aggregate(self, f_sim: Dict[str, object]) -> Dict[str, Dict[str, object]]:
        """Run _processAggFiles on one rank file whose parsed record is f_sim."""
        agg = output.LsmioAggOutput(self.m_root)
        files = {"rank-0": {"size": 1, "path": "unused"}}
        with patch("lsmiotool.lib.output.data.LsmioSingleRunData") as single:
            single.return_value.getMap.return_value = f_sim
            return agg._processAggFiles(files, "1")

    def testScaleAndAggDataAccessors(self) -> None:
        agg = output.LsmioAggOutput(self.m_root, f_scale=" Variants ")

        self.assertEqual(agg.scale, "variants")
        self.assertEqual(list(agg.getMap()), ["8"])
        self.assertIs(agg.agg_data, agg.getMap())
        self.assertIsNone(output.LsmioAggOutput(self.m_root).scale)

    def testRecordWithoutReadSideAggregatesOnlyWrites(self) -> None:
        result = self.aggregate({"write": self.metrics(1.0)})

        self.assertEqual(result["read"]["total(MiB)"], 0.0)
        self.assertEqual(result["read"]["iteration"], 0)
        self.assertEqual(result["write"]["total(MiB)"], 10.0)
        self.assertEqual(result["write"]["max(MiB)/s"], 4.0)
        self.assertEqual(result["write"]["iteration"], 3)

    def testRecordWithEmptyWriteSideAggregatesOnlyReads(self) -> None:
        result = self.aggregate({"read": self.metrics(2.0), "write": {}})

        self.assertEqual(result["read"]["total(Ops)"], 40.0)
        self.assertEqual(result["read"]["iteration"], 3)
        self.assertEqual(result["write"]["total(Ops)"], 0.0)
        self.assertEqual(result["write"]["iteration"], 0)

    def testUnlistableOutputDirectoryHasNoNodes(self) -> None:
        agg = output.LsmioAggOutput(os.path.join(self.m_root, "absent"))

        with patch.object(output.Console, "warning") as warning:
            self.assertEqual(agg._reportNodeCounts(), [])

        warning.assert_called_once()
        self.assertIn("Cannot list output directory", warning.call_args.args[0])

    def testIsBmtoolOutputDirNeedsNumericNodeDirectoryAndRegularFile(self) -> None:
        touch(os.path.join(self.m_root, "abc", "2026-10-07", "out-1.txt"))
        os.makedirs(os.path.join(self.m_root, "2", "2026-10-07", "out-2.txt"))
        self.assertFalse(output.isBmtoolOutputDir(self.m_root))

        touch(os.path.join(self.m_root, "4", "agg-4-1M-report.csv"))
        self.assertTrue(output.isBmtoolOutputDir(self.m_root))

    def testEnsureReportsWithoutLogsOrManifestGeneratesNothing(self) -> None:
        with patch.object(output, "regenerateLsmioReports") as regenerate:
            self.assertFalse(output.ensureLsmioReports(self.m_root))

        regenerate.assert_not_called()
        self.assertEqual(os.listdir(self.m_root), [])

    def testEnsureReportsLogsAFailedRegenerationAndReturnsFalse(self) -> None:
        touch(os.path.join(self.m_root, "1", "2026-10-07", "out-x.txt"))

        with patch.object(
            output, "regenerateLsmioReports", side_effect=RuntimeError("boom")
        ), patch.object(output.Console, "warning") as warning:
            self.assertFalse(output.ensureLsmioReports(self.m_root))

        warning.assert_called_once()
        self.assertIn("Failed to generate report", warning.call_args.args[0])
        self.assertIn("boom", warning.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
