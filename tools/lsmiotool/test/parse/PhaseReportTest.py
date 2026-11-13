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

"""Tests of lsmiotool.lib.phasereport over logs in the real benchmark output format."""

import csv
import os
import tempfile
import unittest
from typing import Dict, List, Sequence, Tuple
from unittest.mock import MagicMock, patch

from lsmiotool.lib import phasereport
from lsmiotool.lib.phasereport import (
    LSM_PHASE_REPORT_FILE,
    PHASE_REPORT_COLUMNS,
    LegacyRow,
    parseRankLog,
    phaseRowsForSet,
    writePhaseReport,
)

PREFIX = "RocksDB Flush: false BLF: false"
BM_HEADER = [
    "access,max(MiB)/s,min(MiB/s),mean(MiB/s),total(MiB),total(Ops),iteration",
    "------,----------,----------,-----------,-----------,----------,----------",
]
BARRIER_HEADER = [" mpi-barrier: 1", " durability: engine", " rankShift: 0"]
ONE_MIB = 1024 * 1024


def timeline(
    f_start: int,
    f_open: int = 2000,
    f_data: int = 1000000,
    f_close: int = 500000,
    f_delete: int = 50000,
) -> List[int]:
    """Return the five boundary offsets of a side that starts at f_start."""
    f_after_open = f_start + f_open
    f_before_close = f_after_open + f_data
    f_after_close = f_before_close + f_close
    return [f_start, f_after_open, f_before_close, f_after_close, f_after_close + f_delete]


def phaseRow(f_side: str, f_iteration: int, f_bytes: int, f_offsets: Sequence[int]) -> str:
    """Render a 'phase,' row as benchmark/PhaseTimeline.cpp formatPhaseRows prints it."""
    return ",".join(["phase", f_side, str(f_iteration), str(f_bytes)] + [str(f_o) for f_o in f_offsets])


def legacyRow(f_name: str, f_bytes: int, f_us: float) -> str:
    """Render an 'iwrite,'/'iread,' row for a duration, as lib/benchmark.cpp prints it."""
    f_bw = f_bytes / f_us / 1.024 / 1.024
    f_mib = f_bytes / ONE_MIB
    return f"{f_name},{f_bw:.2f},{f_bw:.2f},{f_bw:.2f},{f_mib:.2f},4096,1"


def legacyBlock(f_kind: str, f_prefix: str, f_rows: Sequence[str]) -> List[str]:
    """Render the Iteration-<kind> block and the Bench-<kind> block that follows it."""
    return (
        ["", f"Iteration-{f_kind}: {f_prefix}"]
        + BM_HEADER
        + list(f_rows)
        + ["", f"Bench-{f_kind}: {f_prefix}"]
        + BM_HEADER
        + [f"{f_kind.lower()},1.00,1.00,1.00,1.00,1,1"]
    )


def rankLogLines(
    f_suites: Sequence[Tuple[str, Sequence[str], Sequence[str], Sequence[str]]],
    f_header: Sequence[str] = BARRIER_HEADER,
) -> List[str]:
    """Render a log: header, legacy blocks per suite, then the Phases: blocks.

    Each suite is (prefix, iwrite rows, iread rows, phase rows).
    """
    f_lines = list(f_header) + ["", "BENCHMARK RESULTS: "]
    for f_prefix, f_writes, f_reads, _ in f_suites:
        f_lines += legacyBlock("WRITE", f_prefix, f_writes)
        f_lines += legacyBlock("READ", f_prefix, f_reads)
    for f_prefix, _, _, f_phases in f_suites:
        f_lines += ["", f"Phases: {f_prefix}"] + list(f_phases)
    return f_lines


def sampleSuite(
    f_prefix: str = PREFIX,
    f_iterations: int = 2,
    f_bytes: int = 100 * ONE_MIB,
    f_skew_us: int = 300,
) -> Tuple[str, List[str], List[str], List[str]]:
    """Return a suite whose legacy rows agree with its phase windows up to f_skew_us."""
    f_writes, f_reads, f_phases = [], [], []
    for f_iteration in range(f_iterations):
        f_write = timeline(10000 + f_iteration * 4000000)
        f_read = timeline(f_write[4] + 100000)
        f_phases += [
            phaseRow("write", f_iteration, f_bytes, f_write),
            phaseRow("read", f_iteration, f_bytes, f_read),
        ]
        f_writes.append(legacyRow("iwrite", f_bytes, f_write[3] - f_write[1] - f_skew_us))
        f_reads.append(legacyRow("iread", f_bytes, f_read[3] - f_read[1] - f_skew_us))
    return (f_prefix, f_writes, f_reads, f_phases)


def exactInterval(f_bw_text: str, f_mib_text: str) -> Tuple[float, float]:
    """Return the durations that print as these two-decimal bw and MiB (NB18)."""
    f_bw, f_mib = float(f_bw_text), float(f_mib_text)
    return (
        (f_mib - 0.005) / (f_bw + 0.005) * 10 ** 6,
        (f_mib + 0.005) / (f_bw - 0.005) * 10 ** 6,
    )


class PhaseReportTest(unittest.TestCase):
    """Parsing, windows, legacy cross-check, set rules and the CSV writer."""

    m_temp_dir: tempfile.TemporaryDirectory

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.m_temp_dir.cleanup)

    def writeLog(self, f_name: str, f_lines: Sequence[str]) -> str:
        """Write a rank log under the temp dir and return its path."""
        f_path = os.path.join(self.m_temp_dir.name, f_name)
        os.makedirs(os.path.dirname(f_path), exist_ok=True)
        with open(f_path, "w", encoding="utf-8") as f_f:
            f_f.write("\n".join(f_lines) + "\n")
        return f_path

    def setRows(
        self, f_lines: Sequence[str], f_nodes: str = "4"
    ) -> Tuple[List[Dict[str, str]], MagicMock]:
        """Return the rows of a one-log set and the mocked Console.warning."""
        f_path = self.writeLog("rank_0.log", f_lines)
        with patch.object(phasereport.Console, "warning") as f_warn:
            f_rows = phaseRowsForSet(f_nodes, "4", "1M", [f_path], self.m_temp_dir.name)
        return f_rows, f_warn

    # ---- parsing ----

    def testHeaderValuesAndMpiDisabled(self) -> None:
        f_parsed = parseRankLog(
            [
                " MPI: Enabled",
                " mpi-barrier: 1",
                " durability: page-cache",
                " rankShift: 1",
                " rankShiftNodes: simulated:3",
                " rankShiftSource: 1",
                " rankShiftSelfRanks: 0",
                " rankShiftSameHostRanks: 1",
                " perRankPath: 1",
                " rocksdbVersion: 9.11.2",
                " leveldbVersion: 1.23",
                " leveldbCloseFlush: 0",
                " durability: engine",
            ]
        )
        self.assertEqual(
            f_parsed.m_headers,
            {
                "mpi-barrier": "1",
                "durability": "page-cache",
                "rankShift": "1",
                "rankShiftNodes": "simulated:3",
                "rankShiftSelfRanks": "0",
                "rankShiftSameHostRanks": "1",
                "perRankPath": "1",
                "rocksdbVersion": "9.11.2",
                "leveldbVersion": "1.23",
                "leveldbCloseFlush": "0",
            },
        )
        self.assertFalse(f_parsed.m_mpi_disabled)
        self.assertFalse(f_parsed.hasRecords())
        self.assertTrue(parseRankLog(["MPI: Disabled"]).m_mpi_disabled)

    def testBlocksAndPrefixWhitespace(self) -> None:
        f_bytes = 100 * ONE_MIB
        f_parsed = parseRankLog(
            [
                "Phases: RocksDB Flush: false BLF: false ",
                phaseRow("write", 0, f_bytes, timeline(0)),
                "",
                "Phases:   Native Flush: true BLF: false",
                phaseRow("read", 3, f_bytes, timeline(5)),
            ]
        )
        self.assertEqual(f_parsed.m_blocks, [PREFIX, "Native Flush: true BLF: false"])
        self.assertEqual(list(f_parsed.m_records[PREFIX]), [(0, "write")])
        f_record = f_parsed.m_records["Native Flush: true BLF: false"][(3, "read")]
        self.assertEqual(f_record.bytes_text, str(f_bytes))
        self.assertEqual(
            (f_record.before_open, f_record.after_delete), (5, 5 + 2000 + 1000000 + 500000 + 50000)
        )
        self.assertEqual(
            set(f_parsed.recordSet()),
            {(PREFIX, 0, "write"), ("Native Flush: true BLF: false", 3, "read")},
        )

    def testMalformedRowsAreSkippedWithWarning(self) -> None:
        f_good = phaseRow("write", 0, 1024, timeline(0))
        f_bad_rows = [
            "phase,write,0,1024,1,2,3,4",  # 8 fields
            "phase,write,0,1024,1,2,3,4,5,6",  # 10 fields
            "phase,erase,0,1024,1,2,3,4,5",  # unknown side
            "phase,write,x,1024,1,2,3,4,5",  # iteration not an integer
            "phase,write,0,12k,1,2,3,4,5",  # bytes not a number
            "phase,write,0,1024,1,2,three,4,5",  # offset not an integer
        ]
        with patch.object(phasereport.Console, "warning") as f_warn:
            f_parsed = parseRankLog(["Phases: p"] + f_bad_rows + [f_good], "rank_0.log")
        self.assertEqual(f_warn.call_count, len(f_bad_rows))
        for f_call, f_row in zip(f_warn.call_args_list, f_bad_rows):
            self.assertIn("malformed phase row skipped", f_call.args[0])
            self.assertIn(f_row, f_call.args[0])
            self.assertIn("rank_0.log", f_call.args[0])
        self.assertEqual(list(f_parsed.m_records["p"]), [(0, "write")])

    def testNegativeOffsetsAndFractionalBytesParse(self) -> None:
        f_parsed = parseRankLog(["Phases: p", "phase,read,0,1024.5,-5,0,0,0,7"])
        f_record = f_parsed.m_records["p"][(0, "read")]
        self.assertEqual((f_record.bytes_text, f_record.before_open, f_record.after_delete), ("1024.5", -5, 7))

    def testRowBeforeAnyBlockIsIgnoredWithWarning(self) -> None:
        with patch.object(phasereport.Console, "warning") as f_warn:
            f_parsed = parseRankLog([phaseRow("write", 0, 1024, timeline(0))])
        self.assertEqual(f_warn.call_count, 1)
        self.assertIn("before any 'Phases:' block", f_warn.call_args.args[0])
        self.assertFalse(f_parsed.hasRecords())
        self.assertEqual(f_parsed.m_blocks, [])

    def testRepeatedBlockAndRepeatedRecordKeepTheFirst(self) -> None:
        f_first = phaseRow("write", 0, 1024, timeline(0))
        f_other = phaseRow("write", 0, 2048, timeline(50))
        with patch.object(phasereport.Console, "warning") as f_warn:
            f_parsed = parseRankLog(
                [
                    "Phases: p",
                    f_first,
                    f_other,  # same (iteration, side): skipped, one warning
                    "Phases: q",
                    phaseRow("read", 1, 1024, timeline(0)),
                    "Phases: p ",  # same prefix again: whole block skipped, one warning
                    phaseRow("write", 7, 1024, timeline(0)),
                    "Phases: p",
                ]
            )
        self.assertEqual(f_warn.call_count, 3)
        self.assertIn("repeated phase row skipped", f_warn.call_args_list[0].args[0])
        self.assertIn("repeated 'Phases: p' block ignored", f_warn.call_args_list[1].args[0])
        self.assertEqual(f_parsed.m_blocks, ["p", "q"])
        self.assertEqual(f_parsed.m_records["p"][(0, "write")].bytes_text, "1024")
        self.assertEqual(list(f_parsed.m_records["p"]), [(0, "write")])

    def testLegacyBlockStaysOpenAcrossHeaderLines(self) -> None:
        f_parsed = parseRankLog(
            legacyBlock(
                "WRITE",
                PREFIX + " ",
                ["iwrite,66.67,66.67,66.67,100.00,4096,1", "iwrite,50.00,50.00,50.00,100.00,4096,1"],
            )
            + legacyBlock("READ", PREFIX, ["iread,10.00,10.00,10.00,20.00,4096,1"])
            + ["iwrite,1.00,1.00,1.00,1.00,1,1"]  # after Bench-READ: no block is open
        )
        self.assertEqual(
            f_parsed.m_legacy[("write", PREFIX)],
            [LegacyRow(66.67, 100.0), LegacyRow(50.0, 100.0)],
        )
        self.assertEqual(f_parsed.m_legacy[("read", PREFIX)], [LegacyRow(10.0, 20.0)])

    def testLegacyBlockClosesAtNextBlockHeaderAndKeepsItsOwnSide(self) -> None:
        f_parsed = parseRankLog(
            [
                "Iteration-WRITE: a",
                "iwrite,1.00,1.00,1.00,2.00,1,1",
                "iread,9.00,9.00,9.00,9.00,1,1",  # a read row inside a WRITE block
                "Phases: b",  # the next block header closes the legacy block
                "iwrite,3.00,3.00,3.00,3.00,1,1",
            ]
        )
        self.assertEqual(f_parsed.m_legacy, {("write", "a"): [LegacyRow(1.0, 2.0)]})

    def testUnreadableLegacyRowsKeepTheirPlace(self) -> None:
        f_parsed = parseRankLog(
            [
                "Iteration-READ: a",
                "iread,short",
                "iread,x,x,x,2.00,1,1",
                "iread,2.00,2.00,2.00,y,1,1",
            ]
        )
        self.assertEqual(
            f_parsed.m_legacy[("read", "a")],
            [LegacyRow(None, None), LegacyRow(None, 2.0), LegacyRow(2.0, None)],
        )

    def testRepeatedLegacyBlockKeepsTheFirst(self) -> None:
        with patch.object(phasereport.Console, "warning") as f_warn:
            f_parsed = parseRankLog(
                [
                    "Iteration-WRITE: a",
                    "iwrite,1.00,1.00,1.00,2.00,1,1",
                    "Iteration-WRITE: a",
                    "iwrite,5.00,5.00,5.00,5.00,1,1",
                ]
            )
        self.assertEqual(f_warn.call_count, 1)
        self.assertIn("repeated 'Iteration-WRITE: a' block ignored", f_warn.call_args.args[0])
        self.assertEqual(f_parsed.m_legacy[("write", "a")], [LegacyRow(1.0, 2.0)])

    # ---- windows ----

    def testWindowsAndMibPerSecondOnAHandComputedRecord(self) -> None:
        # 100 MiB; open 2000 us, data 1 s, close 0.5 s, delete 50 ms
        f_rows, f_warn = self.setRows(
            rankLogLines(
                [
                    (
                        PREFIX,
                        [legacyRow("iwrite", 100 * ONE_MIB, 1500000)],
                        [legacyRow("iread", 100 * ONE_MIB, 1500000)],
                        [
                            phaseRow("write", 0, 100 * ONE_MIB, timeline(1000)),
                            phaseRow("read", 0, 100 * ONE_MIB, [1558000, 1560000, 2560000, 3060000, 3110000]),
                        ],
                    )
                ]
            )
        )
        f_warn.assert_not_called()
        self.assertEqual(len(f_rows), 2)
        f_write, f_read = f_rows
        self.assertEqual(
            {f_k: f_write[f_k] for f_k in PHASE_REPORT_COLUMNS[:20]},
            {
                "nodes": "4",
                "stripe": "4",
                "block": "1M",
                "prefix": PREFIX,
                "iteration": "0",
                "side": "write",
                "bytes": "104857600",
                "full_us": "1552000",
                "open_us": "2000",
                "data_us": "1000000",
                "close_us": "500000",
                "delete_us": "50000",
                "legacy_us": "1500000",
                "full_mibs": "64.43",
                "open_mibs": "50000.00",
                "data_mibs": "100.00",
                "close_mibs": "200.00",
                "delete_mibs": "2000.00",
                "legacy_mibs": "66.67",
                "gap_us": "",
            },
        )
        # gap = read.beforeOpen - write.afterDelete = 1558000 - 1553000
        self.assertEqual(f_read["gap_us"], "5000")
        self.assertEqual(f_read["side"], "read")
        self.assertEqual(f_write["legacy_check"], "ok")
        self.assertEqual(f_write["source_log"], "rank_0.log")

    def testZeroAndNegativeWindowsHaveNoMibPerSecond(self) -> None:
        f_rows, _ = self.setRows(
            [
                "Phases: p",
                # open 0 us, data -4 us, close 10 us, delete 0 us
                "phase,write,0,1048576,100,100,96,106,106",
            ]
        )
        f_row = f_rows[0]
        self.assertEqual((f_row["open_us"], f_row["open_mibs"]), ("0", ""))
        self.assertEqual((f_row["data_us"], f_row["data_mibs"]), ("-4", ""))
        self.assertEqual((f_row["delete_us"], f_row["delete_mibs"]), ("0", ""))
        self.assertEqual((f_row["close_us"], f_row["close_mibs"]), ("10", "100000.00"))
        self.assertEqual((f_row["legacy_us"], f_row["legacy_mibs"]), ("6", "166666.67"))

    def testGapOnlyOnReadRowsWithAWriteRecord(self) -> None:
        f_rows, _ = self.setRows(
            [
                "Phases: p",
                phaseRow("write", 0, 1024, [0, 1, 2, 3, 4]),
                phaseRow("read", 0, 1024, [10, 11, 12, 13, 14]),
                phaseRow("read", 1, 1024, [20, 21, 22, 23, 24]),  # no write record for iteration 1
            ]
        )
        self.assertEqual(
            [(f_r["iteration"], f_r["side"], f_r["gap_us"]) for f_r in f_rows],
            [("0", "write", ""), ("0", "read", "6"), ("1", "read", "")],
        )

    # ---- legacy cross-check ----

    def checkResults(self, f_lines: Sequence[str]) -> Tuple[List[Tuple[str, str]], MagicMock]:
        """Return (legacy_row_us, legacy_check) per row and the mocked Console.warning."""
        f_rows, f_warn = self.setRows(f_lines)
        return [(f_r["legacy_row_us"], f_r["legacy_check"]) for f_r in f_rows], f_warn

    def testCrossCheckOkWithinToleranceAndMismatchOutside(self) -> None:
        f_bytes = 100 * ONE_MIB
        f_window_us = 1500000
        f_suite = sampleSuite(f_iterations=1, f_bytes=f_bytes)
        # the fixture's row decodes to ~1499700 us: well inside the exact interval plus 1 ms
        f_fields = f_suite[1][0].split(",")
        f_low, f_high = exactInterval(f_fields[1], f_fields[4])
        self.assertLess(f_low - 1000 + 100, f_window_us)
        self.assertGreater(f_high + 1000 - 100, f_window_us)
        f_results, f_warn = self.checkResults(rankLogLines([f_suite]))
        self.assertEqual([f_r[1] for f_r in f_results], ["ok", "ok"])
        self.assertEqual(f_results[0][0], str(round(100 * 10 ** 6 / float(f_fields[1]))))
        f_warn.assert_not_called()

        # 50 ms apart: far outside the interval plus 1 ms; one warning for the set
        f_bad = (PREFIX, [legacyRow("iwrite", f_bytes, f_window_us - 50000)], [f_suite[2][0]], f_suite[3][:2])
        f_bad_fields = f_bad[1][0].split(",")
        _, f_bad_high = exactInterval(f_bad_fields[1], f_bad_fields[4])
        self.assertGreater(f_window_us, f_bad_high + 1000 + 1000)
        f_results, f_warn = self.checkResults(rankLogLines([f_bad]))
        self.assertEqual([f_r[1] for f_r in f_results], ["mismatch", "ok"])
        self.assertEqual(f_warn.call_count, 1)
        self.assertIn("disagrees with its iwrite/iread rows", f_warn.call_args.args[0])

    def testCrossCheckAtLowBandwidthUsesTheRoundingInterval(self) -> None:
        # 1 MiB in about 1 s prints bw 1.00 and MiB 1.00: each rounds by up to 0.005
        f_row = legacyRow("iwrite", ONE_MIB, 1000000)
        f_fields = f_row.split(",")
        self.assertEqual((f_fields[1], f_fields[4]), ("1.00", "1.00"))
        f_low, f_high = exactInterval("1.00", "1.00")
        self.assertAlmostEqual(f_high - 10 ** 6, 10050.1, delta=1)

        def results(f_legacy_us: int) -> str:
            f_lines = [
                " mpi-barrier: 1",
                "Iteration-WRITE: p",
                f_row,
                "Phases: p",
                phaseRow("write", 0, ONE_MIB, [0, 0, 0, f_legacy_us, f_legacy_us]),
            ]
            return self.checkResults(f_lines)[0][0][1]

        self.assertTrue(f_low < 1005000 < f_high)
        self.assertEqual(results(1005000), "ok")  # inside the interval
        self.assertTrue(f_high < 1010500 < f_high + 1000 - 400)
        self.assertEqual(results(1010500), "ok")  # above the interval, inside the 1 ms slack
        self.assertLess(f_high + 1000 + 3000, 1030000)
        self.assertEqual(results(1030000), "mismatch")

    def legacyCheckFor(self, f_row: str, f_legacy_us: int) -> str:
        """Return the legacy_check of one write record with that window against one legacy row."""
        f_lines = [
            " mpi-barrier: 1",
            "Iteration-WRITE: p",
            f_row,
            "Phases: p",
            phaseRow("write", 0, ONE_MIB, [0, 0, 0, f_legacy_us, f_legacy_us]),
        ]
        return self.checkResults(f_lines)[0][0][1]

    def testCrossCheckBoundariesOfTheRoundingIntervalPlusSlack(self) -> None:
        f_row = "iwrite,1.00,1.00,1.00,1.00,1,1"
        f_low, f_high = exactInterval("1.00", "1.00")
        # lo = 0.995e6/1.005 = 990049.75 us and hi = 1.005e6/0.995 = 1010050.25 us
        self.assertAlmostEqual(f_low, 990049.75, delta=0.01)
        self.assertAlmostEqual(f_high, 1010050.25, delta=0.01)
        # the window is an integer: the accepted range is [989049.75, 1011050.25]
        self.assertEqual(self.legacyCheckFor(f_row, 1011050), "ok")  # just inside, above
        self.assertEqual(self.legacyCheckFor(f_row, 1011051), "mismatch")  # just outside, above
        self.assertEqual(self.legacyCheckFor(f_row, 989050), "ok")  # just inside, below
        self.assertEqual(self.legacyCheckFor(f_row, 989049), "mismatch")  # just outside, below

    def testCrossCheckSlowLongSideIsOkWhereTheOldFormulaMismatched(self) -> None:
        # bw 0.10 MiB/s over 1.00 MiB: the old tolerance was 1e7 x (0.005/0.1 + 0.005/1) + 1000
        # = 551000 us, but the figures allow durations up to 1.005e6/0.095 = 10578947 us
        f_row = "iwrite,0.10,0.10,0.10,1.00,1,1"
        f_low, f_high = exactInterval("0.10", "1.00")
        self.assertAlmostEqual(f_high, 10578947.37, delta=0.01)
        f_window_us = 10570000
        self.assertGreater(f_window_us - 10 ** 7, 551000)  # the old formula said mismatch
        self.assertLess(f_window_us, f_high)
        self.assertEqual(self.legacyCheckFor(f_row, f_window_us), "ok")
        self.assertEqual(self.legacyCheckFor(f_row, 10579947), "ok")  # hi + 1000, inside
        self.assertEqual(self.legacyCheckFor(f_row, 10579948), "mismatch")  # just outside
        self.assertAlmostEqual(f_low, 9476190.48, delta=0.01)
        self.assertEqual(self.legacyCheckFor(f_row, 9475191), "ok")  # lo - 1000, inside
        self.assertEqual(self.legacyCheckFor(f_row, 9475190), "mismatch")  # just outside

    def testCrossCheckUnboundedAboveWhenBandwidthCanRoundFromZero(self) -> None:
        # a figure within half a step of 0 allows any long duration; MiB below half a step
        # allows a zero duration (the Python parser reads any number, the binaries print 2 decimals)
        f_row = "iwrite,0.004,0.004,0.004,0.004,1,1"
        self.assertEqual(self.legacyCheckFor(f_row, 900000000), "ok")
        self.assertEqual(self.legacyCheckFor(f_row, 0), "ok")
        self.assertEqual(self.checkResults([
            " mpi-barrier: 1", "Iteration-WRITE: p", "iwrite,0.00,0.00,0.00,1.00,1,1",
            "Phases: p", phaseRow("write", 0, ONE_MIB, [0, 0, 0, 5, 5]),
        ])[0][0], ("", "n/a"))

    def testCrossCheckUnpairedOnCountMismatch(self) -> None:
        f_suite = sampleSuite(f_iterations=2)
        f_short = (f_suite[0], f_suite[1][:1], f_suite[2], f_suite[3])
        f_results, f_warn = self.checkResults(rankLogLines([f_short]))
        # records in order: write 0, read 0, write 1, read 1; only the write side is short
        self.assertEqual(
            f_results,
            [("", "unpaired"), (f_results[1][0], "ok"), ("", "unpaired"), (f_results[3][0], "ok")],
        )
        self.assertNotEqual(f_results[1][0], "")
        f_warn.assert_not_called()

    def testCrossCheckNotApplicableWithoutBarriers(self) -> None:
        f_suite = sampleSuite(f_iterations=1)
        for f_header in (
            [],
            [" mpi-barrier: 0"],
            [" mpi-barrier: 0", " durability: engine"],
        ):
            f_results, _ = self.checkResults(rankLogLines([f_suite], f_header))
            self.assertEqual(f_results, [("", "n/a"), ("", "n/a")])

    def testCrossCheckRunsWithMpiDisabled(self) -> None:
        f_results, _ = self.checkResults(rankLogLines([sampleSuite(f_iterations=1)], ["MPI: Disabled", " mpi-barrier: 0"]))
        self.assertEqual([f_r[1] for f_r in f_results], ["ok", "ok"])

    def testCrossCheckNotApplicableForZeroOrUnreadableRows(self) -> None:
        f_suite = sampleSuite(f_iterations=1)
        f_zero = (f_suite[0], ["iwrite,0.00,0.00,0.00,100.00,4096,1"], ["iread,10.00,10.00,10.00,0.00,4096,1"], f_suite[3])
        f_results, f_warn = self.checkResults(rankLogLines([f_zero]))
        self.assertEqual(f_results, [("", "n/a"), ("", "n/a")])
        f_broken = (f_suite[0], ["iwrite,short"], ["iread,x,x,x,x,1,1"], f_suite[3])
        f_results, f_warn = self.checkResults(rankLogLines([f_broken]))
        self.assertEqual(f_results, [("", "n/a"), ("", "n/a")])
        f_warn.assert_not_called()

    def testBlocksPairWithTheirOwnPrefix(self) -> None:
        f_a = sampleSuite("Native Flush: false BLF: false", 1)
        f_b = sampleSuite("RocksDB Flush: true BLF: false", 2)
        f_rows, f_warn = self.setRows(rankLogLines([f_a, f_b]))
        f_warn.assert_not_called()
        self.assertEqual(
            [(f_r["prefix"], f_r["iteration"], f_r["side"], f_r["legacy_check"]) for f_r in f_rows],
            [(f_a[0], "0", "write", "ok"), (f_a[0], "0", "read", "ok")]
            + [(f_b[0], str(f_i), f_s, "ok") for f_i in (0, 1) for f_s in ("write", "read")],
        )

    # ---- header columns ----

    def testHeaderColumnsAndRankShiftColumns(self) -> None:
        f_header = BARRIER_HEADER[:2] + [
            " rankShift: 1",
            " rankShiftNodes: simulated:3",
            " rankShiftSource: 1",
            " rankShiftSelfRanks: 0",
            " rankShiftSameHostRanks: 2",
            " perRankPath: 1",
            " rocksdbVersion: 9.11.2",
        ]
        f_rows, _ = self.setRows(rankLogLines([sampleSuite(f_iterations=1)], f_header))
        f_row = f_rows[0]
        self.assertEqual(
            [f_row[f_c] for f_c in PHASE_REPORT_COLUMNS[22:]],
            ["engine", "1", "simulated:3", "0", "2", "1", "9.11.2", "", "", "rank_0.log"],
        )
        # rankShift 0 or absent: the three shift columns stay empty whatever the log says
        for f_shift in ([" rankShift: 0"], []):
            f_header = (
                BARRIER_HEADER[:1] + f_shift + [" rankShiftNodes: shared", " rankShiftSelfRanks: 3", " rankShiftSameHostRanks: 3"]
            )
            f_rows, _ = self.setRows(rankLogLines([sampleSuite(f_iterations=1)], f_header))
            self.assertEqual(
                [f_rows[0][f_c] for f_c in PHASE_REPORT_COLUMNS[23:28]],
                [f_shift[0].split(": ")[1] if f_shift else "", "", "", "", ""],
            )

    # ---- set rules ----

    def testSourceLogIsTheFirstLogWithRows(self) -> None:
        f_suite = sampleSuite(f_iterations=1)
        f_empty = self.writeLog("a/rank_0.log", [" mpi-barrier: 1", "BENCHMARK RESULTS: "])
        f_first = self.writeLog("b/rank_1.log", rankLogLines([f_suite]))
        f_second = self.writeLog("c/rank_2.log", rankLogLines([f_suite]))
        with patch.object(phasereport.Console, "warning") as f_warn:
            f_rows = phaseRowsForSet("4", "4", "1M", [f_empty, f_first, f_second], self.m_temp_dir.name)
        f_warn.assert_not_called()
        self.assertEqual({f_r["source_log"] for f_r in f_rows}, {"b/rank_1.log"})
        self.assertEqual(len(f_rows), 2)
        with patch.object(phasereport.Console, "warning") as f_warn:
            self.assertEqual(phaseRowsForSet("4", "4", "1M", [f_empty], self.m_temp_dir.name), [])
            self.assertEqual(phaseRowsForSet("4", "4", "1M", [], self.m_temp_dir.name), [])
        f_warn.assert_not_called()

    def testDisagreeingPrinterGivesOneWarningAndKeepsTheSourceValues(self) -> None:
        f_suite = sampleSuite(f_iterations=1)
        f_other = (f_suite[0], f_suite[1], f_suite[2], [phaseRow("write", 0, 100 * ONE_MIB, timeline(99999))] + f_suite[3][1:])
        f_source = self.writeLog("n/rank_0.log", rankLogLines([f_suite]))
        f_agree = self.writeLog("n/rank_1.log", rankLogLines([f_suite]))
        f_differ_1 = self.writeLog("n/rank_2.log", rankLogLines([f_other]))
        f_differ_2 = self.writeLog("n/rank_3.log", rankLogLines([f_other]))
        f_fewer = self.writeLog("n/rank_4.log", rankLogLines([(f_suite[0], f_suite[1], f_suite[2], f_suite[3][:1])]))
        with patch.object(phasereport.Console, "warning") as f_warn:
            f_agreed_rows = phaseRowsForSet("4", "4", "1M", [f_source, f_agree], self.m_temp_dir.name)
            f_warn.assert_not_called()
            f_rows = phaseRowsForSet(
                "4", "4", "1M", [f_source, f_agree, f_differ_1, f_differ_2, f_fewer], self.m_temp_dir.name
            )
        self.assertEqual(f_warn.call_count, 1)
        self.assertIn("n/rank_2.log", f_warn.call_args.args[0])
        self.assertIn("n/rank_0.log", f_warn.call_args.args[0])
        self.assertEqual(f_rows, f_agreed_rows)
        # a set of records that differs only by a missing record also counts as a difference
        with patch.object(phasereport.Console, "warning") as f_warn:
            phaseRowsForSet("4", "4", "1M", [f_source, f_fewer], self.m_temp_dir.name)
        self.assertEqual(f_warn.call_count, 1)

    def testMissingOrUnreadablePathIsSkippedWithWarning(self) -> None:
        f_good = self.writeLog("n/rank_0.log", rankLogLines([sampleSuite(f_iterations=1)]))
        f_missing = os.path.join(self.m_temp_dir.name, "n", "gone.log")
        with patch.object(phasereport.Console, "warning") as f_warn:
            f_rows = phaseRowsForSet("4", "4", "1M", [f_missing, f_good], self.m_temp_dir.name)
        self.assertEqual(f_warn.call_count, 1)
        self.assertIn("n/gone.log", f_warn.call_args.args[0])
        self.assertEqual(len(f_rows), 2)

    # ---- writer ----

    def readReport(self, f_dir: str) -> List[List[str]]:
        """Return the rows of lsm-phase-report.csv in f_dir, header included."""
        with open(os.path.join(f_dir, LSM_PHASE_REPORT_FILE), newline="", encoding="utf-8") as f_f:
            return list(csv.reader(f_f))

    def testWriterOrdersRowsAndHasTheContractColumns(self) -> None:
        f_log = self.writeLog("log.log", rankLogLines([sampleSuite(f_iterations=2), sampleSuite("Native Flush: false BLF: false", 1)]))
        f_sets = [
            ("16", "16", "8M", [f_log]),
            ("4", "16", "1M", [f_log]),
            ("16", "4", "64K", [f_log]),
            ("4", "4", "8M", [f_log]),
            ("4", "4", "64K", [f_log]),
            ("4", "4", "1M", [f_log]),
            ("16", "4", "1G", [f_log]),
            ("4", "16", "64k", [f_log]),
        ]
        f_out = os.path.join(self.m_temp_dir.name, "out")
        os.makedirs(f_out)
        with patch.object(phasereport.Console, "warning") as f_warn:
            f_path = writePhaseReport(f_out, f_sets, self.m_temp_dir.name)
        f_warn.assert_not_called()
        self.assertEqual(f_path, os.path.join(f_out, "lsm-phase-report.csv"))
        with open(f_path, "rb") as f_f:
            f_raw = f_f.read().decode("utf-8")
        self.assertTrue(f_raw.startswith(",".join(PHASE_REPORT_COLUMNS) + "\n"))
        self.assertNotIn("\r", f_raw)
        f_table = self.readReport(f_out)
        self.assertEqual(len(f_table[0]), 32)
        self.assertEqual(tuple(f_table[0]), PHASE_REPORT_COLUMNS)
        self.assertTrue(all(len(f_r) == 32 for f_r in f_table))
        f_rows = [dict(zip(f_table[0], f_r)) for f_r in f_table[1:]]
        self.assertEqual(len(f_rows), len(f_sets) * 6)
        f_set_order = []
        for f_r in f_rows:
            f_set = (f_r["nodes"], f_r["stripe"], f_r["block"])
            if not f_set_order or f_set_order[-1] != f_set:
                f_set_order.append(f_set)
        self.assertEqual(
            f_set_order,
            [
                ("4", "4", "64K"),
                ("4", "4", "1M"),
                ("4", "4", "8M"),
                ("4", "16", "64k"),
                ("4", "16", "1M"),
                ("16", "4", "64K"),
                ("16", "4", "1G"),
                ("16", "16", "8M"),
            ],
        )
        # within a set: blocks in log order, iteration ascending, write before read
        f_first = [(f_r["prefix"], f_r["iteration"], f_r["side"]) for f_r in f_rows[:6]]
        self.assertEqual(
            f_first,
            [
                (PREFIX, "0", "write"),
                (PREFIX, "0", "read"),
                (PREFIX, "1", "write"),
                (PREFIX, "1", "read"),
                ("Native Flush: false BLF: false", "0", "write"),
                ("Native Flush: false BLF: false", "0", "read"),
            ],
        )
        f_keys = [tuple(f_r[f_c] for f_c in ("nodes", "stripe", "block", "prefix", "iteration", "side")) for f_r in f_rows]
        self.assertEqual(len(f_keys), len(set(f_keys)))

    def testWriterRowKeyIsUniqueAcrossTwoStripes(self) -> None:
        f_log_4 = self.writeLog("s4/rank_0.log", rankLogLines([sampleSuite(f_iterations=2)]))
        f_log_16 = self.writeLog("s16/rank_0.log", rankLogLines([sampleSuite(f_iterations=2)]))
        f_out = os.path.join(self.m_temp_dir.name, "out")
        os.makedirs(f_out)
        writePhaseReport(f_out, [("8", "4", "1M", [f_log_4]), ("8", "16", "1M", [f_log_16])], self.m_temp_dir.name)
        f_table = self.readReport(f_out)
        f_keys = [tuple(f_r[:6]) for f_r in f_table[1:]]
        self.assertEqual(len(f_keys), 8)
        self.assertEqual(len(set(f_keys)), 8)
        self.assertEqual({f_r[31] for f_r in f_table[1:]}, {"s4/rank_0.log", "s16/rank_0.log"})

    def testWriterWritesNothingWithoutRowsAndKeepsAnExistingFile(self) -> None:
        f_old = self.writeLog("old/rank_0.log", [" mpi-barrier: 1", "BENCHMARK RESULTS: "])
        f_out = os.path.join(self.m_temp_dir.name, "out")
        os.makedirs(f_out)
        self.assertIsNone(writePhaseReport(f_out, [("4", "4", "1M", [f_old])], self.m_temp_dir.name))
        self.assertIsNone(writePhaseReport(f_out, [], self.m_temp_dir.name))
        self.assertFalse(os.path.exists(os.path.join(f_out, LSM_PHASE_REPORT_FILE)))
        f_existing = os.path.join(f_out, LSM_PHASE_REPORT_FILE)
        with open(f_existing, "w", encoding="utf-8") as f_f:
            f_f.write("earlier run\n")
        self.assertIsNone(writePhaseReport(f_out, [("4", "4", "1M", [f_old])], self.m_temp_dir.name))
        with open(f_existing, encoding="utf-8") as f_f:
            self.assertEqual(f_f.read(), "earlier run\n")

    def testWriterOrdersNonNumericSetsAfterNumbersAndNeverTouchesOtherReports(self) -> None:
        f_log = self.writeLog("log.log", rankLogLines([sampleSuite(f_iterations=1)]))
        f_out = os.path.join(self.m_temp_dir.name, "out")
        os.makedirs(f_out)
        f_other_files = {}
        for f_name in ("agg-4-1M-report.csv", "lsm-report.csv", "lsm-report.json"):
            f_other_files[f_name] = self.writeLog(os.path.join("out", f_name), [f_name])
        f_sets = [("x", "4", "1M", [f_log]), ("4", "y", "1M", [f_log]), ("4", "4", "weird", [f_log]), ("4", "4", "1M", [f_log])]
        writePhaseReport(f_out, f_sets, self.m_temp_dir.name)
        f_rows = self.readReport(f_out)[1:]
        self.assertEqual(
            [(f_r[0], f_r[1], f_r[2]) for f_r in f_rows[::2]],
            [("4", "4", "1M"), ("4", "4", "weird"), ("4", "y", "1M"), ("x", "4", "1M")],
        )
        for f_name, f_path in f_other_files.items():
            with open(f_path, encoding="utf-8") as f_f:
                self.assertEqual(f_f.read(), f_name + "\n")
        self.assertEqual(
            sorted(os.listdir(f_out)),
            sorted(list(f_other_files) + [LSM_PHASE_REPORT_FILE]),
        )


if __name__ == "__main__":
    unittest.main()
