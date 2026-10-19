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

"""The worker's epocpp branch, run as the real lsmiotool-worker with a mock epocpp:
the deck, the repeats, their logs, the bytes on disk, the purge between runs and the
controller results."""

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Dict, List, Mapping, Optional, Tuple
import unittest

from lsmiotool.lib.artifacts import (
    STANDARD_COMBINATION_TUPLES,
    ArtifactLayout,
    ArtifactStore,
)
from lsmiotool.lib.benchmarks import EpocppAdapter
from lsmiotool.lib.evidence import EvidenceStore, JobHandle
from lsmiotool.lib.run import RunPlan, RunPlanner, RunRequest
from lsmiotool.lib.site import EnvironmentResolver
from lsmiotool.lib.worker import AllocationController

_SHARE_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "share")
)

# A stand-in for epocpp: reads the deck lsmiotool filled in, refuses a data dir that
# is not empty (the worker must purge between runs), writes three dumps unless the deck
# has no output, and prints what EPOCpp prints. MOCK_* variables make it fail.
_MOCK_EPOCPP = r"""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
deck_dir = args[args.index("-i") + 1]
data_dir = args[args.index("-o") + 1]
with open(os.path.join(os.environ["MOCK_LOG"], "calls.jsonl"), "a") as f:
    f.write(json.dumps({"argv": sys.argv, "cwd": os.getcwd(),
                        "data_before": sorted(os.listdir(data_dir)),
                        "data_inode": os.stat(data_dir).st_ino}) + "\n")
if os.listdir(data_dir):
    print("data dir not empty"); sys.exit(9)
deck = open(os.path.join(deck_dir, "input.deck")).read()
if os.environ.get("MOCK_LOCKED"):
    # A file the worker's purge cannot remove
    os.makedirs(os.path.join(data_dir, "locked"))
    open(os.path.join(data_dir, "locked", "stuck"), "w").close()
    os.chmod(os.path.join(data_dir, "locked"), 0o500)
fail = os.environ.get("MOCK_FAIL_COMBO")
if fail and data_dir.rstrip("/").endswith(fail.replace("_b", "/b")):
    print("Runtime = 1.0"); sys.exit(7)
ext = {"filetype = posix": "epc", "adios_engine = plugin": "lsp",
       "filetype = lsmio": "ldb"}
if "nstep_snapshot = 0" not in deck:
    e = next((v for k, v in ext.items() if k in deck), "bp5")
    for step in range(3):
        with open(os.path.join(data_dir, f"data{step:05d}_000.{e}"), "wb") as f:
            f.write(b"x" * 1000)
if "--io-benchmark" in args:
    print("BENCHMARK RESULTS: ")
    print("Iteration-WRITE: POSIX:data")
    print("iwrite,100.0,0.5,1")
    print("Bench-WRITE: POSIX:data")
    print("access,max(MiB)/s,min(MiB/s),mean(MiB/s),total(MiB),total(Ops),iteration")
    if os.environ.get("MOCK_BENCH_FAILED"):
        print("write, FAILED")
    else:
        print("write,100.00,90.00,95.00,3.00,3,3")
    print("read,200.00,180.00,190.00,3.00,3,3")
if not os.environ.get("MOCK_NO_RUNTIME"):
    print("Runtime = 1.250000")
sys.exit(0)
"""


class _EpocppWorkerHarness(unittest.TestCase):
    """A decoy home with a mock epocpp and lfs, and epocpp run roots to run the real
    worker on (no tests of its own)."""

    def setUp(self) -> None:
        self.m_temp_dir = os.path.realpath(
            tempfile.mkdtemp(prefix="lsmiotool-epocpp-worker-")
        )
        self.m_home = os.path.join(self.m_temp_dir, "home")
        self.m_cwd = os.path.join(self.m_temp_dir, "cwd")
        self.m_bin = os.path.join(self.m_home, "src", "usr", "bin")
        self.m_bench = os.path.join(self.m_home, ".lsmio-dev", "benchmark")
        self.m_log = os.path.join(self.m_temp_dir, "mock")
        for f_dir in (self.m_cwd, self.m_bin, self.m_bench, self.m_log):
            os.makedirs(f_dir, exist_ok=True)
        self.m_worker = Path(__file__).resolve().parents[2] / "lsmiotool-worker"
        for f_name, f_text in (
            ("lfs", "#!/bin/sh\nexit 0\n"),
            ("epocpp", _MOCK_EPOCPP),
        ):
            f_path = os.path.join(self.m_bin, f_name)
            with open(f_path, "w") as f_f:
                f_f.write(f_text)
            os.chmod(f_path, 0o755)
        self.m_profile = EnvironmentResolver.resolveProfile(
            "DEV", f_user="testuser", f_home=self.m_home
        )
        self.m_runs = 0

    def tearDown(self) -> None:
        for f_root, f_dirs, _ in os.walk(self.m_temp_dir):
            for f_dir in f_dirs:
                os.chmod(os.path.join(f_root, f_dir), 0o755)
        shutil.rmtree(self.m_temp_dir, ignore_errors=True)

    def _manifest(
        self, f_setup: str, f_repeats: int, f_scale: str = "local"
    ) -> Tuple[RunPlan, ArtifactLayout]:
        self.m_runs += 1
        f_run_id = f"run-20261018T000000Z-{self.m_runs:012x}"
        f_tokens = iter(range(self.m_runs * 100, self.m_runs * 100 + 100))
        f_plan = RunPlanner.createPlan(
            f_request=RunRequest(
                "epocpp", f_scale, f_setup=f_setup, f_repeats=f_repeats
            ),
            f_profile=self.m_profile,
            f_run_id_source=lambda: f_run_id,
            f_clock=lambda: "2026-10-18T00:00:00Z",
            f_token_source=lambda: f"lm-{next(f_tokens):024x}",
        )
        f_layout = ArtifactLayout(self.m_bench, f_run_id)
        f_store = ArtifactStore(f_layout)
        f_store.allocateRun(f_plan)
        f_evidence = EvidenceStore(f_layout, f_plan=f_plan)
        for f_idx, f_sp in enumerate(f_plan.scale_points):
            f_store.preparePoint(f_sp, f_ordinal=f_idx)
            f_evidence.recordSubmissionRequested(f_sp, "client", f_ordinal=f_idx)
            f_evidence.recordSubmissionDispatched(f_sp, "client", f_ordinal=f_idx)
            f_evidence.recordSubmissionRecorded(
                f_sp, "client", f_handle=JobHandle("fake", "1000"), f_ordinal=f_idx
            )
        return f_plan, f_layout

    def _runWorker(
        self,
        f_layout: ArtifactLayout,
        f_env: Optional[Mapping[str, str]] = None,
        f_point: str = "00-tasks-1",
    ) -> subprocess.CompletedProcess:
        f_environ = dict(os.environ)
        f_environ.update(
            {
                "HOME": self.m_home,
                "PATH": f"{self.m_bin}:{os.environ.get('PATH', '')}",
                "LSMIO_RANK": "0",
                "SLURMD_NODENAME": "node042",
                "MOCK_LOG": self.m_log,
                "PYTHONPATH": str(Path(__file__).resolve().parents[3]),
            }
        )
        f_environ.update(f_env or {})
        return subprocess.run(
            [
                sys.executable,
                str(self.m_worker),
                "allocation",
                f_layout.manifestPath,
                f_point,
            ],
            cwd=self.m_cwd,
            env=f_environ,
            capture_output=True,
            text=True,
            timeout=300,
        )

    def _calls(self) -> List[Dict]:
        with open(os.path.join(self.m_log, "calls.jsonl")) as f_f:
            return [json.loads(f_l) for f_l in f_f]

    def _results(self, f_plan: RunPlan, f_layout: ArtifactLayout) -> Dict[str, Dict]:
        f_ev = EvidenceStore(f_layout, f_plan=f_plan)
        f_sp = f_plan.scale_points[0]
        return {
            f_c.name: f_ev.readControllerResult(f_sp, f_c, f_ordinal=0).payload
            for f_c in f_plan.combinations
        }


class EpocppWorkerTest(_EpocppWorkerHarness):
    def testWallTimeArmRunsEveryRepeatOfEveryCombination(self) -> None:
        f_plan, f_layout = self._manifest("POSIX", 2)
        f_proc = self._runWorker(f_layout)
        self.assertEqual(f_proc.returncode, 0, f_proc.stdout + f_proc.stderr)
        f_sp = f_plan.scale_points[0]
        f_logs = f_layout.pointLogsDir(f_sp, 0)
        f_template = EpocppAdapter().readTemplate(
            EpocppAdapter.templatePath(_SHARE_ROOT)
        )
        f_calls = self._calls()
        self.assertEqual(len(f_calls), 12)
        for f_call in f_calls:
            # Every run starts on an empty data dir, with no --io-benchmark
            self.assertEqual(f_call["data_before"], [])
            self.assertNotIn("--io-benchmark", f_call["argv"])
        # The purge empties a combination's data dir but keeps it (and its striping):
        # both runs of a combination see the same directory
        for f_i in range(0, 12, 2):
            self.assertEqual(f_calls[f_i]["data_inode"], f_calls[f_i + 1]["data_inode"])
        f_results = self._results(f_plan, f_layout)
        for f_rf, f_bs in STANDARD_COMBINATION_TUPLES:
            f_combo = f"c{f_rf}_b{f_bs}"
            f_work = f_layout.pointCombinationWorkDir(f_sp, f_combo, 0)
            with open(os.path.join(f_work, "input.deck")) as f_f:
                self.assertEqual(
                    f_f.read(), EpocppAdapter().renderDeck(f_template, "POSIX", "small")
                )
            for f_repeat in (1, 2):
                f_log = AllocationController.epocppLogPath(f_logs, f_combo, f_repeat)
                with open(f_log) as f_f:
                    f_text = f_f.read()
                self.assertEqual(EpocppAdapter.runtimeOf(f_text), 1.25)
                self.assertIn("lsmiotool: data bytes = 3000 allocated = ", f_text)
                self.assertTrue(f_text.rstrip().endswith("files = 3"))
            # The data dir is left empty, its striping kept
            self.assertEqual(
                os.listdir(f_layout.pointDataSubdir(f_sp, f_rf, f_bs, 0)), []
            )
            f_payload = f_results[f_combo]
            self.assertEqual(f_payload["status"], "success")
            self.assertEqual(
                f_payload["output_path"],
                AllocationController.epocppLogPath(f_logs, f_combo, 1),
            )
            self.assertEqual(f_payload["host"], "node042")
        # The runs' argv: -i the work dir, -o the striped data dir
        f_first = f_calls[0]["argv"]
        self.assertEqual(
            f_first[1:3], ["-i", f_layout.pointCombinationWorkDir(f_sp, "c4_b1M", 0)]
        )
        self.assertEqual(
            f_first[3:5], ["-o", f_layout.pointDataSubdir(f_sp, 4, "1M", 0)]
        )

    def testBandwidthArmAndBaseline(self) -> None:
        f_plan, f_layout = self._manifest("NATIVE-BW", 1)
        self.assertEqual(self._runWorker(f_layout).returncode, 0)
        f_calls = self._calls()
        self.assertEqual(len(f_calls), 6)
        self.assertEqual(f_calls[0]["argv"][1:3], ["--io-benchmark", "-m"])
        f_sp = f_plan.scale_points[0]
        f_log = AllocationController.epocppLogPath(
            f_layout.pointLogsDir(f_sp, 0), "c16_b8M", 1
        )
        with open(f_log) as f_f:
            f_text = f_f.read()
        self.assertIn("BENCHMARK RESULTS:", f_text)
        self.assertIsNone(EpocppAdapter.checkOutput("NATIVE-BW", f_text))

        os.remove(os.path.join(self.m_log, "calls.jsonl"))
        f_plan, f_layout = self._manifest("NONE", 1)
        self.assertEqual(self._runWorker(f_layout).returncode, 0)
        f_sp = f_plan.scale_points[0]
        with open(
            AllocationController.epocppLogPath(
                f_layout.pointLogsDir(f_sp, 0), "c4_b1M", 1
            )
        ) as f_f:
            self.assertIn("data bytes = 0 allocated = 0 files = 0", f_f.read())
        self.assertTrue(
            all(
                f_r["status"] == "success"
                for f_r in self._results(f_plan, f_layout).values()
            )
        )

    def testAFailedRunFailsOnlyItsCombination(self) -> None:
        f_plan, f_layout = self._manifest("POSIX", 3)
        f_proc = self._runWorker(f_layout, {"MOCK_FAIL_COMBO": "c4_b64K"})
        self.assertEqual(f_proc.returncode, 7)
        f_results = self._results(f_plan, f_layout)
        self.assertEqual(f_results["c4_b64K"]["status"], "failed")
        self.assertEqual(f_results["c4_b64K"]["stage"], "execution")
        self.assertEqual(f_results["c4_b64K"]["exit_code"], 7)
        self.assertIn("repeat 1", f_results["c4_b64K"]["error"])
        # A failed run's bytes are still recorded: the count comes after it exits
        with open(f_results["c4_b64K"]["output_path"]) as f_f:
            self.assertIn("lsmiotool: data bytes = ", f_f.read())
        for f_combo, f_payload in f_results.items():
            if f_combo != "c4_b64K":
                self.assertEqual(f_payload["status"], "success", f_combo)
        # The failed combination stopped at its first run; the next began empty
        f_calls = self._calls()
        self.assertEqual(len(f_calls), 5 * 3 + 1)
        self.assertTrue(all(f_c["data_before"] == [] for f_c in f_calls))

    def testLargeScaleRunsTheLargeDeck(self) -> None:
        f_plan, f_layout = self._manifest("ADIOS2-BW", 1, f_scale="large")
        f_sp = f_plan.scale_points[0]
        self.assertEqual((f_sp.tasks, f_sp.nodes), (32, 8))
        f_point = f_layout.pointDirName(f_sp, 0)
        self.assertEqual(self._runWorker(f_layout, f_point=f_point).returncode, 0)
        f_template = EpocppAdapter().readTemplate(
            EpocppAdapter.templatePath(_SHARE_ROOT)
        )
        with open(
            os.path.join(
                f_layout.pointCombinationWorkDir(f_sp, "c16_b8M", 0), "input.deck"
            )
        ) as f_f:
            self.assertEqual(
                f_f.read(), EpocppAdapter().renderDeck(f_template, "ADIOS2-BW", "large")
            )

    def testAFailedPurgeFailsTheCombination(self) -> None:
        f_plan, f_layout = self._manifest("POSIX", 2)
        self.assertNotEqual(
            self._runWorker(f_layout, {"MOCK_LOCKED": "1"}).returncode, 0
        )
        for f_payload in self._results(f_plan, f_layout).values():
            self.assertEqual(f_payload["stage"], "purge")
            self.assertIn("not emptied", f_payload["error"])
        # No combination ran its second repeat on a dir that was not empty
        self.assertTrue(all(f_c["data_before"] == [] for f_c in self._calls()))

    def testAFailedRunIsAnExecutionFailureEvenIfItsPurgeFails(self) -> None:
        f_plan, f_layout = self._manifest("POSIX", 1)
        self._runWorker(f_layout, {"MOCK_FAIL_COMBO": "c4_b1M", "MOCK_LOCKED": "1"})
        f_payload = self._results(f_plan, f_layout)["c4_b1M"]
        self.assertEqual(f_payload["stage"], "execution")
        self.assertEqual(f_payload["exit_code"], 7)
        self.assertIn("and its purge", f_payload["error"])

    def testIncompleteOutputFails(self) -> None:
        for f_setup, f_env, f_why in (
            ("POSIX", {"MOCK_NO_RUNTIME": "1"}, "Runtime"),
            ("POSIX-BW", {"MOCK_BENCH_FAILED": "1"}, "write"),
        ):
            with self.subTest(f_setup=f_setup):
                f_plan, f_layout = self._manifest(f_setup, 2)
                self.assertNotEqual(self._runWorker(f_layout, f_env).returncode, 0)
                for f_payload in self._results(f_plan, f_layout).values():
                    self.assertEqual(f_payload["stage"], "output_validation")
                    self.assertIn(f_why, f_payload["error"])


class EpocppExportTest(_EpocppWorkerHarness):
    """A worker's run root exported as the archive holds it, its reports, and
    'parse <run root>'."""

    def testExportReportAndParseRunRoot(self) -> None:
        import io
        from unittest.mock import patch

        from lsmiotool.lib import epocppreport
        from lsmiotool.lib.cli import parseParseArguments
        from lsmiotool.lib.export import exportEpocppPoint, generateEpocppReports
        from lsmiotool.lib.main import ParseMain

        f_plan, f_layout = self._manifest("POSIX", 2)
        self.assertEqual(self._runWorker(f_layout).returncode, 0)
        f_sp = f_plan.scale_points[0]
        f_arm_dir = os.path.join(self.m_temp_dir, "archive", "outputs-epocpp-posix")
        f_written = exportEpocppPoint(
            f_layout=f_layout,
            f_evidence_store=EvidenceStore(f_layout, f_plan=f_plan),
            f_scale_point=f_sp,
            f_ordinal=0,
            f_combinations=f_plan.combinations,
            f_arm_id="epocpp-posix",
            f_repeats=2,
            f_node_dir=os.path.join(f_arm_dir, "1"),
        )
        self.assertEqual(f_written, 12)
        (f_date,) = [
            f_d
            for f_d in os.listdir(os.path.join(f_arm_dir, "1"))
            if f_d != "input.deck"
        ]
        self.assertEqual(
            sorted(os.listdir(os.path.join(f_arm_dir, "1", f_date))),
            sorted(
                f"out-epocpp-posix-{f_rf}-{f_bs}-{f_date}-node042-r{f_r:02d}.txt"
                for f_rf, f_bs in STANDARD_COMBINATION_TUPLES
                for f_r in (1, 2)
            ),
        )
        self.assertTrue(os.path.isfile(os.path.join(f_arm_dir, "1", "input.deck")))
        self.assertTrue(generateEpocppReports(f_arm_dir))
        with open(os.path.join(f_arm_dir, epocppreport.ARM_REPORT_FILE)) as f_f:
            f_rows = [f_l.strip().split(",") for f_l in f_f][1:]
        self.assertEqual(len(f_rows), 6)
        for f_row in f_rows:
            self.assertEqual(f_row[3:5], ["runtime", "1.250000"])
            self.assertEqual(f_row[7], "2")
            # The mock writes 3000 bytes, far less than the deck's particles
            self.assertEqual(f_row[9:], ["3000", "short"])

        # parse <run root>: the same, into --output-dir
        f_out = os.path.join(self.m_temp_dir, "parsed")
        f_stdout = io.StringIO()
        with patch("sys.stdout", f_stdout), patch("sys.stderr", io.StringIO()):
            f_rc = ParseMain(
                f_request=parseParseArguments([f_layout.runRoot, "--output-dir", f_out])
            ).run()
        self.assertEqual(f_rc, 0, f_stdout.getvalue())
        with (
            open(
                os.path.join(
                    f_out, "outputs-epocpp-posix", epocppreport.ARM_REPORT_FILE
                )
            ) as f_f,
            open(os.path.join(f_arm_dir, epocppreport.ARM_REPORT_FILE)) as f_g,
        ):
            self.assertEqual(f_f.read(), f_g.read())
        # Parsed again into the same place: the <nodes> directory there (maybe another
        # run's) is kept, with a warning, and the reports are rebuilt
        f_node_dir = os.path.join(f_out, "outputs-epocpp-posix", "1")
        f_marker = os.path.join(f_node_dir, "kept")
        with open(f_marker, "w") as f_f:
            f_f.write("x")
        f_stderr = io.StringIO()
        with patch("sys.stdout", io.StringIO()), patch("sys.stderr", f_stderr):
            f_rc = ParseMain(
                f_request=parseParseArguments([f_layout.runRoot, "--output-dir", f_out])
            ).run()
        self.assertEqual(f_rc, 0, f_stderr.getvalue())
        self.assertTrue(os.path.exists(f_marker))
        self.assertIn(f"'{f_node_dir}' exists; not replaced", f_stderr.getvalue())

    def testFailedRunRootAndMissingOutputs(self) -> None:
        import io
        from unittest.mock import patch

        from lsmiotool.lib.cli import parseParseArguments
        from lsmiotool.lib.export import ExportError, exportEpocppPoint
        from lsmiotool.lib.main import ParseMain

        # 'parse <run root>' of a run whose point failed: exit 4, nothing reported
        f_plan, f_layout = self._manifest("POSIX", 1)
        self._runWorker(f_layout, {"MOCK_FAIL_COMBO": "c16_b8M"})
        f_out = os.path.join(self.m_temp_dir, "parsed")
        with patch("sys.stdout", io.StringIO()), patch("sys.stderr", io.StringIO()):
            f_rc = ParseMain(
                f_request=parseParseArguments([f_layout.runRoot, "--output-dir", f_out])
            ).run()
        self.assertEqual(f_rc, 4)
        f_node_dir = os.path.join(f_out, "outputs-epocpp-posix", "1")
        self.assertFalse(os.path.exists(f_node_dir))
        # A <nodes> directory already there (another run's) does not make the failed
        # point count: still exit 4, the directory untouched
        os.makedirs(f_node_dir)
        f_marker = os.path.join(f_node_dir, "kept")
        with open(f_marker, "w") as f_f:
            f_f.write("x")
        f_stderr = io.StringIO()
        with patch("sys.stdout", io.StringIO()), patch("sys.stderr", f_stderr):
            f_rc = ParseMain(
                f_request=parseParseArguments([f_layout.runRoot, "--output-dir", f_out])
            ).run()
        self.assertEqual(f_rc, 4)
        self.assertEqual(os.listdir(f_node_dir), ["kept"])
        self.assertIn("did not succeed", f_stderr.getvalue())
        self.assertNotIn("not replaced", f_stderr.getvalue())
        shutil.rmtree(f_node_dir)
        # json is refused, before anything is exported
        with patch("sys.stdout", io.StringIO()), patch("sys.stderr", io.StringIO()):
            f_rc = ParseMain(
                f_request=parseParseArguments(
                    [f_layout.runRoot, "--output-dir", f_out, "--format", "json"]
                )
            ).run()
        self.assertEqual(f_rc, 2)

        # A missing run log, or a missing deck, fails the export and leaves nothing
        f_plan, f_layout = self._manifest("POSIX", 1)
        self.assertEqual(self._runWorker(f_layout).returncode, 0)
        f_sp = f_plan.scale_points[0]
        f_node = os.path.join(self.m_temp_dir, "archive", "outputs-epocpp-posix", "1")

        def _export() -> int:
            return exportEpocppPoint(
                f_layout=f_layout,
                f_evidence_store=EvidenceStore(f_layout, f_plan=f_plan),
                f_scale_point=f_sp,
                f_ordinal=0,
                f_combinations=f_plan.combinations,
                f_arm_id="epocpp-posix",
                f_repeats=1,
                f_node_dir=f_node,
            )

        f_log = AllocationController.epocppLogPath(
            f_layout.pointLogsDir(f_sp, 0), "c4_b8M", 1
        )
        os.rename(f_log, f_log + ".away")
        with self.assertRaisesRegex(ExportError, "Missing EPOCpp output"):
            _export()
        os.rename(f_log + ".away", f_log)
        self.assertFalse(os.path.exists(f_node))
        for f_rf, f_bs in STANDARD_COMBINATION_TUPLES:
            os.remove(
                os.path.join(
                    f_layout.pointCombinationWorkDir(f_sp, f"c{f_rf}_b{f_bs}", 0),
                    "input.deck",
                )
            )
        with self.assertRaisesRegex(ExportError, "Missing EPOCpp deck"):
            _export()
        self.assertFalse(os.path.exists(f_node))
        self.assertFalse(os.path.exists(f_node + ".partial"))


class EpocppOutputCheckTest(unittest.TestCase):
    """EpocppAdapter.checkOutput, runtimeOf and countAndRemove."""

    def testChecks(self) -> None:
        f_block = (
            "BENCHMARK RESULTS: \nwrite,1.5,1.0,1.2,3.0,3,3\nread,2.5,2.0,2.2,3.0,3,3\n"
        )
        self.assertEqual(EpocppAdapter.runtimeOf("x\nRuntime = 12.5\n"), 12.5)
        self.assertEqual(EpocppAdapter.runtimeOf("Runtime = 1e3\n"), 1000.0)
        self.assertIsNone(EpocppAdapter.runtimeOf("Runtime = soon\n"))
        self.assertIsNone(EpocppAdapter.checkOutput("NONE", "Runtime = 1.0\n"))
        self.assertIn("Runtime", EpocppAdapter.checkOutput("POSIX", "done\n"))
        self.assertIsNone(
            EpocppAdapter.checkOutput("POSIX-BW", f_block + "Runtime = 1\n")
        )
        self.assertIn(
            "BENCHMARK", EpocppAdapter.checkOutput("POSIX-BW", "Runtime = 1\n")
        )
        self.assertIn(
            "read",
            EpocppAdapter.checkOutput(
                "PLUGIN-BW",
                f_block.replace("read,2.5", "read, FAILED") + "Runtime = 1\n",
            ),
        )

    def testOutputHostNames(self) -> None:
        from lsmiotool.lib.export import _epocppFileHost

        self.assertEqual(_epocppFileHost({"host": "node042"}), "node042")
        self.assertEqual(_epocppFileHost({"host": "cn-12.cluster"}), "cn-12.cluster")
        for f_host in ("", "a b", "x/y", None):
            self.assertEqual(_epocppFileHost({"host": f_host}), "nodeunk")

    def testCountAndRemoveIgnoresSymlinks(self) -> None:
        f_dir = tempfile.mkdtemp(prefix="lsmiotool-epocpp-bytes-")
        f_outside = tempfile.mkdtemp(prefix="lsmiotool-epocpp-outside-")
        try:
            os.makedirs(os.path.join(f_dir, "sub", "deeper"))
            with open(os.path.join(f_dir, "a"), "wb") as f_f:
                f_f.write(b"1" * 10)
            with open(os.path.join(f_dir, "sub", "deeper", "b"), "wb") as f_f:
                f_f.write(b"2" * 5)
            with open(os.path.join(f_outside, "kept"), "wb") as f_f:
                f_f.write(b"3" * 7)
            f_kept = os.path.join(f_outside, "kept")
            os.symlink(f_kept, os.path.join(f_dir, "link"))
            os.symlink(f_kept, os.path.join(f_dir, "sub", "deeper", "link"))
            os.symlink(f_outside, os.path.join(f_dir, "dirlink"))
            os.symlink(f_outside, os.path.join(f_dir, "sub", "dirlink"))
            os.symlink(os.path.join(f_dir, "gone"), os.path.join(f_dir, "broken"))
            f_size, f_alloc, f_files = EpocppAdapter.countAndRemove(f_dir)
            self.assertEqual((f_size, f_files), (15, 2))
            self.assertGreaterEqual(f_alloc, 0)
            # Emptied, the dir itself kept; a symlinked dir's target is left alone
            self.assertEqual(os.listdir(f_dir), [])
            self.assertEqual(os.listdir(f_outside), ["kept"])
            with open(f_kept, "rb") as f_f:
                self.assertEqual(f_f.read(), b"3" * 7)
            self.assertEqual(EpocppAdapter.countAndRemove(f_dir), (0, 0, 0))
            self.assertEqual(
                EpocppAdapter.dataBytesLine(15, 4096, 2),
                "lsmiotool: data bytes = 15 allocated = 4096 files = 2\n",
            )
        finally:
            shutil.rmtree(f_dir, ignore_errors=True)
            shutil.rmtree(f_outside, ignore_errors=True)

    @unittest.skipIf(os.geteuid() == 0, "root removes files regardless of modes")
    def testCountAndRemoveLeavesWhatItCannotRemove(self) -> None:
        # A dump it cannot empty or read is left, with the error on stderr; the
        # worker then fails the run as 'data dir not emptied'
        f_dir = tempfile.mkdtemp(prefix="lsmiotool-epocpp-left-")
        f_locked = os.path.join(f_dir, "data0000_0001.bp5")
        f_unreadable = os.path.join(f_dir, "data0000_0002.bp5", "sub")
        f_closed = os.path.join(f_dir, "data0000_0003.bp5")
        try:
            os.makedirs(f_locked)
            os.makedirs(f_unreadable)
            os.makedirs(f_closed)
            for f_file in (
                os.path.join(f_locked, "data.0"),
                os.path.join(f_unreadable, "md.0"),
                os.path.join(f_closed, "md.0"),
                os.path.join(f_dir, "data0000_0000.epc"),
            ):
                with open(f_file, "wb") as f_f:
                    f_f.write(b"z" * 4)
            os.chmod(f_locked, 0o500)
            os.chmod(f_unreadable, 0o000)
            # A dump dir it cannot open at all must not stop the other ranks' dumps
            os.chmod(f_closed, 0o000)
            f_err = io.StringIO()
            with contextlib.redirect_stderr(f_err):
                f_size, _, f_files = EpocppAdapter.countAndRemove(f_dir, 4)
            self.assertEqual((f_size, f_files), (4, 1))
            self.assertEqual(
                sorted(os.listdir(f_dir)),
                ["data0000_0001.bp5", "data0000_0002.bp5", "data0000_0003.bp5"],
            )
            self.assertEqual(os.listdir(f_locked), ["data.0"])
            self.assertIn(f"failed to remove under '{f_locked}'", f_err.getvalue())
            self.assertIn("data0000_0002.bp5'", f_err.getvalue())
            self.assertIn(f"failed to remove under '{f_closed}'", f_err.getvalue())
        finally:
            for f_path in (f_locked, f_unreadable, f_closed):
                with contextlib.suppress(OSError):
                    os.chmod(f_path, 0o700)
            shutil.rmtree(f_dir, ignore_errors=True)

    def testCountAndRemoveSumsEveryRanksDumps(self) -> None:
        # Like a run's data dir: per-rank dump files and per-rank dump directories;
        # the threaded pass counts every file exactly once, whatever the thread count
        f_dir = tempfile.mkdtemp(prefix="lsmiotool-epocpp-ranks-")
        try:
            f_expect = f_count = 0
            for f_threads in (1, 4, 64):
                for f_rank in range(24):
                    for f_step in range(3):
                        f_name = f"data{f_step:04d}_{f_rank:04d}"
                        with open(os.path.join(f_dir, f_name + ".epc"), "wb") as f_f:
                            f_f.write(b"x" * (f_rank + f_step + 1))
                        f_bp = os.path.join(f_dir, f_name + ".bp5")
                        os.makedirs(os.path.join(f_bp, "sub"))
                        for f_part in ("data.0", "md.0", os.path.join("sub", "m")):
                            with open(os.path.join(f_bp, f_part), "wb") as f_f:
                                f_f.write(b"y" * 3)
                        if f_threads == 1:
                            f_expect += (f_rank + f_step + 1) + 9
                            f_count += 4
                self.assertEqual(
                    EpocppAdapter.countAndRemove(f_dir, f_threads)[::2],
                    (f_expect, f_count),
                    f_threads,
                )
                self.assertEqual(os.listdir(f_dir), [])
        finally:
            shutil.rmtree(f_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
