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

"""The epocpp reports (lib/epocppreport.py): run logs, the deck payload, each arm's
epocpp-report.csv (Min() of Runtime, Max() of bandwidth), the scale's epocpp-cost.csv,
'parse epocpp backends', 'archive epocpp' and 'compare nodes' on an epocpp archive."""

import csv
import io
import os
import shutil
import tempfile
from typing import Dict, List, Optional, Sequence, Tuple
import unittest
from unittest.mock import MagicMock, patch

from lsmiotool.lib import epocppreport, main, plot
from lsmiotool.lib.benchmarks import EpocppAdapter
from lsmiotool.lib.cli import (
    ArchiveCliParseError,
    CompareCliParseError,
    CompareNodesRequest,
    ParseCliParseError,
    parseArchiveArguments,
    parseCompareArguments,
    parseParseArguments,
)

_SHARE_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "share")
)


def _log(
    f_runtime: Optional[float],
    f_bytes: Optional[int] = None,
    f_write: Optional[Sequence[float]] = None,
    f_read: Optional[Sequence[float]] = None,
    f_dumps: Optional[Dict[str, Sequence[Tuple[float, float]]]] = None,
) -> str:
    """An EPOCpp run's log as the worker leaves it; f_write/f_read are (max, min, mean,
    MiB) of an lsmio::Benchmark summary, f_dumps the (MiB/s, MiB) of each dump's
    iwrite/iread row (a summary then counts its rows, else 11 iterations)."""
    f_lines = ["EPOC++ version v1.0.0", "MPI processor split: 2, 2"]
    if f_write is not None or f_read is not None:
        f_lines += ["BENCHMARK RESULTS: ", "Iteration-WRITE: POSIX:data"]
        for f_op, f_rows in (f_dumps or {}).items():
            for f_bw, f_mib in f_rows:
                f_lines.append(
                    f"{f_op},{f_bw:.2f},{f_bw:.2f},{f_bw:.2f},{f_mib:.2f},33,1"
                )
        for f_op, f_vals in (("write", f_write), ("read", f_read)):
            if f_vals is not None:
                f_iters = len((f_dumps or {}).get("i" + f_op, ())) or 11
                f_lines.append(
                    f"{f_op},{f_vals[0]:.2f},{f_vals[1]:.2f},{f_vals[2]:.2f},{f_vals[3]:.2f},33,{f_iters}"
                )
    if f_runtime is not None:
        f_lines.append(f"Runtime = {f_runtime:f}")
    f_text = "\n".join(f_lines) + "\n"
    if f_bytes is not None:
        f_text += EpocppAdapter.dataBytesLine(f_bytes, f_bytes + 4096, 22)
    return f_text


class EpocppRunLogTest(unittest.TestCase):
    def testParseRunLog(self) -> None:
        f_r = epocppreport.parseRunLog(
            _log(2.5, 1000, (100.0, 50.0, 75.0, 3.0), (200.0, 150.0, 175.0, 3.0))
        )
        self.assertEqual(f_r.runtime, 2.5)
        self.assertEqual(f_r.data_bytes, 1000)
        self.assertEqual(
            f_r.write, epocppreport.Summary(100.0, 50.0, 75.0, 3.0, 33, 11)
        )
        self.assertEqual(f_r.read.max, 200.0)
        f_r = epocppreport.parseRunLog("write, FAILED\nRuntime = 1.0\n")
        self.assertIsNone(f_r.write)
        self.assertIsNone(f_r.data_bytes)

    def testDeckPayload(self) -> None:
        f_adapter = EpocppAdapter()
        f_template = f_adapter.readTemplate(EpocppAdapter.templatePath(_SHARE_ROOT))
        # 2 species, 128^2 cells, 64 per cell, 6 x 8 bytes per particle, 11 dumps
        self.assertEqual(
            epocppreport.deckPayloadBytes(
                f_adapter.renderDeck(f_template, "POSIX", "small")
            ),
            2 * 128 * 128 * 64 * 48 * 11,
        )
        self.assertEqual(
            epocppreport.deckPayloadBytes(
                f_adapter.renderDeck(f_template, "NATIVE-BW", "large")
            ),
            2 * 1024 * 1024 * 128 * 48 * 11,
        )
        self.assertEqual(
            epocppreport.deckPayloadBytes(f_adapter.renderDeck(f_template, "NONE")), 0
        )
        self.assertIsNone(epocppreport.deckPayloadBytes("begin:control\nend:control\n"))


class EpocppArchiveFixture(unittest.TestCase):
    """A synthetic epocpp archive: <root>/lsmio-archive/epocpp/small/outputs-*."""

    def setUp(self) -> None:
        self.m_dir = tempfile.mkdtemp(prefix="lsmiotool-epocpp-report-")
        self.m_scale = os.path.join(self.m_dir, "lsmio-archive", "epocpp", "small")
        f_template = EpocppAdapter().readTemplate(
            EpocppAdapter.templatePath(_SHARE_ROOT)
        )
        self.m_decks = {
            f_setup: EpocppAdapter().renderDeck(f_template, f_setup, "small")
            for f_setup in ("NONE", "POSIX", "POSIX-BW")
        }
        self.m_payload = epocppreport.deckPayloadBytes(self.m_decks["POSIX"])

    def tearDown(self) -> None:
        shutil.rmtree(self.m_dir, ignore_errors=True)

    def _arm(self, f_arm: str, f_setup: str, f_runs: Dict[tuple, List[str]]) -> str:
        """outputs-<f_arm> with f_runs[(nodes, rf, bs)] = the runs' logs."""
        f_arm_dir = os.path.join(self.m_scale, f"outputs-{f_arm}")
        for (f_n, f_rf, f_bs), f_logs in f_runs.items():
            f_date_dir = os.path.join(f_arm_dir, str(f_n), "2026-10-19")
            os.makedirs(f_date_dir, exist_ok=True)
            with open(os.path.join(f_arm_dir, str(f_n), "input.deck"), "w") as f_f:
                f_f.write(self.m_decks[f_setup])
            for f_rep, f_text in enumerate(f_logs, start=1):
                with open(
                    os.path.join(
                        f_date_dir,
                        f"out-{f_arm}-{f_rf}-{f_bs}-2026-10-19-node042-r{f_rep:02d}.txt",
                    ),
                    "w",
                ) as f_f:
                    f_f.write(f_text)
        return f_arm_dir

    def _standardArchive(self) -> None:
        self._arm(
            "epocpp-baseline",
            "NONE",
            {
                (2, 4, "1M"): [_log(10.0, 0), _log(9.0, 0), _log(11.0, 0)],
                (4, 4, "1M"): [_log(5.0, 0), _log(6.0, 0)],
            },
        )
        self._arm(
            "epocpp-posix",
            "POSIX",
            {
                (2, 4, "1M"): [
                    _log(15.0, self.m_payload + 9),
                    _log(13.5, self.m_payload),
                ],
                (4, 4, "1M"): [
                    _log(8.0, self.m_payload - 1),
                    _log(7.0, self.m_payload),
                ],
                (2, 16, "8M"): [_log(20.0)],
            },
        )
        self._arm(
            "epocpp-posix-bw",
            "POSIX-BW",
            {
                (2, 4, "1M"): [
                    _log(
                        30.0,
                        4 * 1024 * 1024,
                        (100.0, 40.0, 70.0, 3.0),
                        (300.0, 90.0, 200.0, 3.0),
                    ),
                    _log(
                        31.0,
                        4 * 1024 * 1024,
                        (120.0, 30.0, 80.0, 3.0),
                        (250.0, 95.0, 210.0, 3.0),
                    ),
                ],
            },
        )


def _rows(f_path: str) -> List[Dict[str, str]]:
    with open(f_path, newline="") as f_f:
        return list(csv.DictReader(f_f))


class EpocppReportTest(EpocppArchiveFixture):
    def testArmReports(self) -> None:
        self._standardArchive()
        f_path = epocppreport.writeArmReport(
            os.path.join(self.m_scale, "outputs-epocpp-posix")
        )
        with open(f_path) as f_f:
            self.assertEqual(
                f_f.readline().strip(), ",".join(epocppreport.REPORT_HEADER)
            )
        f_rows = _rows(f_path)
        # Rows by node count, then combination in run order (4/1M before 16/8M)
        self.assertEqual(
            [(f_r["N"], f_r["Stripes"], f_r["BlockSize"]) for f_r in f_rows],
            [("2", "4", "1M"), ("2", "16", "8M"), ("4", "4", "1M")],
        )
        self.assertEqual(f_rows[0]["Metric"], "runtime")
        # Min() of Runtime, the mean and the Max()
        self.assertEqual(
            (
                f_rows[0]["Best"],
                f_rows[0]["Mean"],
                f_rows[0]["Worst"],
                f_rows[0]["Runs"],
            ),
            ("13.500000", "14.250000", "15.000000", "2"),
        )
        self.assertEqual(f_rows[0]["PayloadBytes"], str(self.m_payload))
        # The fewest bytes a run left: every run must cover the payload
        self.assertEqual(f_rows[0]["DataBytes"], str(self.m_payload))
        self.assertEqual(f_rows[0]["DataCheck"], "ok")
        # One short run among them is 'short'; no byte count is 'unknown'
        self.assertEqual(f_rows[2]["DataBytes"], str(self.m_payload - 1))
        self.assertEqual(f_rows[2]["DataCheck"], "short")
        self.assertEqual(f_rows[1]["DataCheck"], "unknown")

        f_rows = _rows(
            epocppreport.writeArmReport(
                os.path.join(self.m_scale, "outputs-epocpp-posix-bw")
            )
        )
        self.assertEqual([f_r["Metric"] for f_r in f_rows], ["write", "read"])
        # Max() of the runs' max and mean, Min() of their min
        self.assertEqual(
            (f_rows[0]["Best"], f_rows[0]["Mean"], f_rows[0]["Worst"]),
            ("120.00", "80.00", "30.00"),
        )
        self.assertEqual((f_rows[1]["Best"], f_rows[1]["Mean"]), ("300.00", "210.00"))
        self.assertEqual(f_rows[0]["PayloadBytes"], str(3 * 1024 * 1024))
        self.assertEqual(f_rows[0]["DataCheck"], "ok")
        self.assertEqual(f_rows[1]["DataCheck"], "")
        # Without per-dump rows there is no whole-run rate
        self.assertEqual((f_rows[0]["Effective"], f_rows[0]["StallFactor"]), ("", ""))

        f_rows = _rows(
            epocppreport.writeArmReport(
                os.path.join(self.m_scale, "outputs-epocpp-baseline")
            )
        )
        self.assertEqual(f_rows[0]["Best"], "9.000000")
        self.assertEqual(f_rows[0]["PayloadBytes"], "0")
        self.assertEqual(f_rows[0]["DataCheck"], "ok")

    def testDataChecks(self) -> None:
        self._arm(
            "epocpp-posix", "POSIX", {(2, 4, "1M"): [_log(1.0, self.m_payload - 1)]}
        )
        self._arm("epocpp-baseline", "NONE", {(2, 4, "1M"): [_log(1.0, 5)]})
        self._arm(
            "epocpp-native-bw",
            "POSIX-BW",
            {
                (2, 4, "1M"): [
                    _log(1.0, 1024, (1.0, 1.0, 1.0, 1.0), (1.0, 1.0, 1.0, 1.0))
                ]
            },
        )
        for f_arm, f_check in (
            ("epocpp-posix", "short"),
            ("epocpp-baseline", "unexpected"),
            ("epocpp-native-bw", "short"),
        ):
            f_rows = _rows(
                epocppreport.writeArmReport(
                    os.path.join(self.m_scale, f"outputs-{f_arm}")
                )
            )
            self.assertEqual(f_rows[0]["DataCheck"], f_check, f_arm)

    def testCostReportOrdersBackendsAsTheyRun(self) -> None:
        self._standardArchive()
        self._arm(
            "epocpp-adios2",
            "POSIX",
            {(2, 4, "1M"): [_log(12.0)], (4, 4, "1M"): [_log(6.5)]},
        )
        self._arm("epocpp-native", "POSIX", {(2, 4, "1M"): [_log(11.0)]})
        for f_e in os.listdir(self.m_scale):
            epocppreport.writeArmReport(os.path.join(self.m_scale, f_e))
        f_rows = _rows(epocppreport.writeCostReport(self.m_scale))
        self.assertEqual(
            [(f_r["N"], f_r["Backend"]) for f_r in f_rows],
            [
                ("2", "posix"),
                ("2", "adios2"),
                ("2", "native"),
                ("4", "posix"),
                ("4", "adios2"),
            ],
        )

    def testCostReport(self) -> None:
        self._standardArchive()
        for f_arm in ("epocpp-baseline", "epocpp-posix", "epocpp-posix-bw"):
            epocppreport.writeArmReport(os.path.join(self.m_scale, f"outputs-{f_arm}"))
        f_rows = _rows(epocppreport.writeCostReport(self.m_scale))
        # Only node counts and combinations the baseline has; bandwidth arms not at all
        self.assertEqual(
            [(f_r["N"], f_r["Backend"], f_r["IOCost"]) for f_r in f_rows],
            [("2", "posix", "4.500000"), ("4", "posix", "2.000000")],
        )
        self.assertEqual(f_rows[0]["BestRuntime"], "13.500000")
        self.assertEqual(f_rows[0]["BaselineBestRuntime"], "9.000000")

    def testEffectiveBandwidthAndStallFactor(self) -> None:
        # Run 1 has a fast dump and a stalled one; run 2's dumps take alike. Best is
        # the fastest dump of any run, Effective the best run's MiB over its dumps' time
        f_arm = self._arm(
            "epocpp-posix-bw",
            "POSIX-BW",
            {
                (2, 4, "1M"): [
                    _log(
                        5.0,
                        3 * 1024 * 1024,
                        (100.0, 1.0, 67.0, 3.0),
                        (90.0, 30.0, 60.0, 3.0),
                        {
                            "iwrite": [(100.0, 1.0), (100.0, 1.0), (1.0, 1.0)],
                            "iread": [(90.0, 1.0), (30.0, 1.0), (60.0, 1.0)],
                        },
                    ),
                    _log(
                        5.0,
                        3 * 1024 * 1024,
                        (50.0, 50.0, 50.0, 3.0),
                        (40.0, 40.0, 40.0, 3.0),
                        {"iwrite": [(50.0, 1.0)] * 3, "iread": [(40.0, 1.0)] * 3},
                    ),
                ],
            },
        )
        f_write, f_read = _rows(epocppreport.writeArmReport(f_arm))
        self.assertEqual(f_write["Best"], "100.00")
        self.assertEqual(
            (f_write["Effective"], f_write["StallFactor"]), ("50.00", "2.00")
        )
        # Run 1 reads 3 MiB in 1/90 + 1/30 + 1/60 s: 49.09 MiB/s, more than run 2's 40
        self.assertEqual(f_read["Best"], "90.00")
        self.assertEqual(
            (f_read["Effective"], f_read["StallFactor"]), ("49.09", "1.83")
        )
        f_run = epocppreport.parseRunLog(
            _log(
                1.0,
                None,
                (100.0, 1.0, 67.0, 3.0),
                None,
                {"iwrite": [(100.0, 1.0), (1.0, 1.0)]},
            )
        )
        self.assertAlmostEqual(f_run.write_effective or 0, 2 / 1.01)
        self.assertIsNone(f_run.read_effective)
        # A summary counting a dump with no row (a mangled line) leaves the rate open
        f_text = _log(
            1.0, None, (100.0, 1.0, 67.0, 3.0), None, {"iwrite": [(100.0, 1.0)] * 3}
        )
        self.assertIsNone(
            epocppreport.parseRunLog(
                f_text.replace("iwrite,100.00,100.00,100.00,1.00,33,1\n", "", 1)
            ).write_effective
        )
        # A dump without a rate leaves the run's rate open
        self.assertIsNone(
            epocppreport.parseRunLog(
                _log(
                    1.0,
                    None,
                    (1.0, 0.0, 1.0, 2.0),
                    None,
                    {"iwrite": [(1.0, 1.0), (0.0, 1.0)]},
                )
            ).write_effective
        )

    def testWallTimeRowsHaveNoRate(self) -> None:
        f_arm = self._arm("epocpp-posix", "POSIX", {(2, 4, "1M"): [_log(1.0)]})
        f_row = _rows(epocppreport.writeArmReport(f_arm))[0]
        self.assertEqual((f_row["Effective"], f_row["StallFactor"]), ("", ""))

    def testReportsFromBeforeTheRateColumnsAreStillRead(self) -> None:
        # A report written with the header before Effective and StallFactor
        f_arm = self._arm("epocpp-baseline", "NONE", {(2, 4, "1M"): [_log(1.0, 0)]})
        f_path = os.path.join(f_arm, epocppreport.ARM_REPORT_FILE)
        with open(f_path, "w", encoding="utf-8") as f_f:
            f_f.write(",".join(epocppreport.REPORT_HEADER[:-2]) + "\n")
            f_f.write("2,4,1M,runtime,1.000000,1.000000,1.000000,1,0,0,ok\n")
        self.assertEqual(epocppreport.readReport(f_path)[0]["Best"], "1.000000")

    def testStaleArmReportAndUncountedRuns(self) -> None:
        # A run without its byte count leaves the data check open
        f_arm = self._arm(
            "epocpp-posix",
            "POSIX",
            {(2, 4, "1M"): [_log(1.0), _log(2.0, self.m_payload)]},
        )
        f_report = os.path.join(f_arm, epocppreport.ARM_REPORT_FILE)
        self.assertEqual(
            _rows(epocppreport.writeArmReport(f_arm))[0]["DataCheck"], "unknown"
        )
        # Without runs any more, the old report goes
        shutil.rmtree(os.path.join(f_arm, "2"))
        self.assertIsNone(epocppreport.writeArmReport(f_arm))
        self.assertFalse(os.path.exists(f_report))

    def testNoBaselineNoCost(self) -> None:
        self._arm("epocpp-posix", "POSIX", {(2, 4, "1M"): [_log(1.0)]})
        epocppreport.writeArmReport(os.path.join(self.m_scale, "outputs-epocpp-posix"))
        # A cost report left from before goes too
        f_stale = os.path.join(self.m_scale, epocppreport.COST_REPORT_FILE)
        with open(f_stale, "w") as f_f:
            f_f.write("stale\n")
        self.assertIsNone(epocppreport.writeCostReport(self.m_scale))
        self.assertFalse(os.path.exists(f_stale))
        self.assertIsNone(
            epocppreport.writeArmReport(self._arm("epocpp-plugin", "POSIX", {}))
        )

    def testTimeSeries(self) -> None:
        self._standardArchive()
        from lsmiotool.lib.export import generateEpocppReports

        for f_arm in ("epocpp-baseline", "epocpp-posix", "epocpp-posix-bw"):
            self.assertTrue(
                generateEpocppReports(os.path.join(self.m_scale, f"outputs-{f_arm}"))
            )
        self.assertTrue(
            os.path.isfile(os.path.join(self.m_scale, epocppreport.COST_REPORT_FILE))
        )
        f_posix = os.path.join(self.m_scale, "outputs-epocpp-posix")
        f_bw = os.path.join(self.m_scale, "outputs-epocpp-posix-bw")
        self.assertEqual(
            epocppreport.timeSeries(f_posix, "runtime", 4, "1M"), ([2, 4], [13.5, 7.0])
        )
        self.assertEqual(
            epocppreport.timeSeries(f_posix, "cost", 4, "1M"), ([2, 4], [4.5, 2.0])
        )
        self.assertEqual(epocppreport.timeSeries(f_posix, "write", 4, "1M"), ([], []))
        self.assertEqual(
            epocppreport.timeSeries(f_bw, "write", 4, "1M"), ([2], [120.0])
        )
        self.assertEqual(epocppreport.timeSeries(f_bw, "read", 4, "1M"), ([2], [300.0]))
        self.assertEqual(epocppreport.timeSeries(f_bw, "runtime", 4, "1M"), ([], []))

    def testCompareNodesChartsEpocppArms(self) -> None:
        self._standardArchive()
        f_out = os.path.join(self.m_dir, "png")
        for f_op, f_legends, f_label in (
            ("runtime", ["epocpp-baseline", "epocpp-posix"], "Min Runtime in s"),
            (
                "cost",
                ["epocpp-posix"],
                "I/O cost in s (Min Runtime - no-output baseline)",
            ),
            ("write", ["epocpp-posix-bw"], "Max BW in MiB/s"),
        ):
            with (
                self.subTest(f_op=f_op),
                patch("lsmiotool.lib.plot.MultiBarPlot") as f_plot,
            ):
                f_plot.return_value = MagicMock()
                f_req = CompareNodesRequest(
                    f_folder=self.m_scale,
                    f_op=f_op,
                    f_stripes=4,
                    f_blocksize="1M",
                    f_output_dir=f_out,
                )
                self.assertEqual(main.CompareNodesMain(f_request=f_req).run(), 0)
                f_args, _ = f_plot.call_args
                f_meta: plot.PlotMetaData = f_args[0]
                self.assertEqual([f_p.legend for f_p in f_args[1:]], f_legends)
                self.assertEqual(f_meta.y_label, f_label)
                f_name = f_plot.return_value.plot.call_args[0][0]
                self.assertEqual(
                    os.path.basename(f_name), f"compare-small-epocpp-{f_op}-4-1M.png"
                )

    def testCostChartWithoutReportsHasEveryBackend(self) -> None:
        # No reports yet: adios2 sorts before the baseline, but is charted all the same
        self._standardArchive()
        self._arm("epocpp-adios2", "POSIX", {(2, 4, "1M"): [_log(12.0)]})
        # An LSMIO arm in the folder (real bmtool outputs) has no runtime or cost
        shutil.copytree(
            os.path.join(
                os.path.dirname(__file__), "..", "parse", "example", "lsmio-outputs"
            ),
            os.path.join(self.m_scale, "outputs-native"),
        )
        with patch("lsmiotool.lib.plot.MultiBarPlot") as f_plot:
            f_plot.return_value = MagicMock()
            f_req = CompareNodesRequest(
                f_folder=self.m_scale,
                f_op="cost",
                f_stripes=4,
                f_blocksize="1M",
                f_output_dir=os.path.join(self.m_dir, "png"),
            )
            self.assertEqual(main.CompareNodesMain(f_request=f_req).run(), 0)
            self.assertEqual(
                [f_p.legend for f_p in f_plot.call_args[0][1:]],
                ["epocpp-posix", "epocpp-adios2"],
            )
        with patch("lsmiotool.lib.plot.MultiBarPlot") as f_plot:
            f_plot.return_value = MagicMock()
            f_req = CompareNodesRequest(
                f_folder=self.m_scale,
                f_op="runtime",
                f_stripes=4,
                f_blocksize="1M",
                f_output_dir=os.path.join(self.m_dir, "png"),
            )
            self.assertEqual(main.CompareNodesMain(f_request=f_req).run(), 0)
            self.assertNotIn("native", [f_p.legend for f_p in f_plot.call_args[0][1:]])
        # ... though it is charted for bandwidth, with the epocpp bandwidth arm
        with patch("lsmiotool.lib.plot.MultiBarPlot") as f_plot:
            f_plot.return_value = MagicMock()
            f_req = CompareNodesRequest(
                f_folder=self.m_scale,
                f_op="write",
                f_stripes=4,
                f_blocksize="1M",
                f_output_dir=os.path.join(self.m_dir, "png"),
            )
            self.assertEqual(main.CompareNodesMain(f_request=f_req).run(), 0)
            f_legends = [f_p.legend for f_p in f_plot.call_args[0][1:]]
            self.assertIn("native", f_legends)
            self.assertIn("epocpp-posix-bw", f_legends)
            # Mixed with LSMIO's MB/s, the label stays LSMIO's
            self.assertEqual(f_plot.call_args[0][0].y_label, "Max BW in MB")

    def testAnUnusableArmLosesOnlyItsOwnChart(self) -> None:
        self._standardArchive()
        # Sorts before every other arm; its summary cannot be read
        f_bad = self._arm("epocpp-adios2-bw", "POSIX-BW", {(2, 4, "1M"): [_log(1.0)]})
        for f_root, _, f_files in os.walk(f_bad):
            for f_name in f_files:
                if f_name.startswith("out-"):
                    with open(os.path.join(f_root, f_name), "a") as f_f:
                        f_f.write("write,1.2.3,1,1,1,3,3\n")
        with patch("lsmiotool.lib.plot.MultiBarPlot") as f_plot:
            f_plot.return_value = MagicMock()
            f_req = CompareNodesRequest(
                f_folder=self.m_scale,
                f_op="cost",
                f_stripes=4,
                f_blocksize="1M",
                f_output_dir=os.path.join(self.m_dir, "png"),
            )
            self.assertEqual(main.CompareNodesMain(f_request=f_req).run(), 0)
            self.assertEqual(
                [f_p.legend for f_p in f_plot.call_args[0][1:]], ["epocpp-posix"]
            )

    def testParseOfTheArchiveDirNeverAggregatesEpocppLogs(self) -> None:
        # 'parse <dir>' of an epocpp archive, or of one arm: never LSMIO's reports
        self._standardArchive()
        for f_target in (
            self.m_scale,
            os.path.join(self.m_scale, "outputs-epocpp-posix-bw"),
        ):
            with self.subTest(f_target=f_target):
                f_req = parseParseArguments(["parse", f_target])
                with (
                    patch("sys.stdout", io.StringIO()),
                    patch("sys.stderr", io.StringIO()),
                ):
                    self.assertEqual(main.ParseMain(f_request=f_req).run(), 0)
                for f_root, _, f_files in os.walk(self.m_scale):
                    self.assertNotIn("lsm-report.csv", f_files, f_root)
                    self.assertFalse(
                        any(f_n.startswith("agg-") for f_n in f_files), f_root
                    )
        f_rows = _rows(
            os.path.join(
                self.m_scale, "outputs-epocpp-posix-bw", epocppreport.ARM_REPORT_FILE
            )
        )
        self.assertEqual(f_rows[0]["Best"], "120.00")
        for f_argv in (
            ["parse", self.m_scale, "--format", "json"],
            [
                "parse",
                os.path.join(self.m_scale, "outputs-epocpp-posix"),
                "--output-dir",
                self.m_dir,
            ],
        ):
            with (
                self.subTest(f_argv=f_argv),
                patch("sys.stdout", io.StringIO()),
                patch("sys.stderr", io.StringIO()),
            ):
                self.assertEqual(
                    main.ParseMain(f_request=parseParseArguments(f_argv)).run(), 2
                )

    def testParseEpocppBackendsRegeneratesReports(self) -> None:
        self._standardArchive()
        f_req = parseParseArguments(
            ["parse", "epocpp", "backends", "small", "--output-dir", self.m_scale]
        )
        self.assertEqual(
            (f_req.target, f_req.mode, f_req.scale), ("epocpp", "backends", "small")
        )
        # An LSMIO arm next to them is not an epocpp arm
        os.makedirs(os.path.join(self.m_scale, "outputs-native"))
        f_out = io.StringIO()
        with patch("sys.stdout", f_out), patch("sys.stderr", io.StringIO()):
            self.assertEqual(main.ParseMain(f_request=f_req).run(), 0)
        for f_arm in ("epocpp-baseline", "epocpp-posix", "epocpp-posix-bw"):
            self.assertTrue(
                os.path.isfile(
                    os.path.join(
                        self.m_scale, f"outputs-{f_arm}", epocppreport.ARM_REPORT_FILE
                    )
                )
            )
        self.assertFalse(
            os.path.exists(
                os.path.join(self.m_scale, "outputs-native", "epocpp-report.csv")
            )
        )
        self.assertIn(epocppreport.COST_REPORT_FILE, f_out.getvalue())


class EpocppCommandLineTest(unittest.TestCase):
    def testParseArchiveAndCompareGrammar(self) -> None:
        for f_argv in (
            ["parse", "epocpp"],
            ["parse", "epocpp", "small"],
            ["parse", "epocpp", "backends", "variants"],
            ["parse", "epocpp", "backends", "small", "--format", "json"],
        ):
            with self.subTest(f_argv=f_argv), self.assertRaises(ParseCliParseError):
                parseParseArguments(f_argv)
        f_req = parseArchiveArguments(["archive", "epocpp", "large", "--source", "/r"])
        self.assertEqual((f_req.target, f_req.scale), ("epocpp", "large"))
        with self.assertRaises(ArchiveCliParseError):
            parseArchiveArguments(["archive", "epocpp", "variants"])
        for f_op in ("runtime", "cost"):
            self.assertEqual(
                parseCompareArguments(["nodes", "/a/b", f_op, "16", "8M"]).op, f_op
            )
        with self.assertRaises(CompareCliParseError):
            parseCompareArguments(["nodes", "/a/b", "speed"])

    def testArchiveEpocppNeedsAnArmRunRoot(self) -> None:
        f_req = parseArchiveArguments(["archive", "epocpp", "small"])
        f_err = io.StringIO()
        with patch("sys.stderr", f_err), patch("sys.stdout", io.StringIO()):
            self.assertEqual(main.ArchiveMain(f_request=f_req).run(), 1)
        self.assertIn("--source", f_err.getvalue())


if __name__ == "__main__":
    unittest.main()
