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

import io
import os
import shutil
import sys
import tempfile
from typing import Tuple
import unittest

from lsmiotool.lib.artifacts import ArtifactStore
from lsmiotool.lib.cli import ParseCliParseError, ParseRequest
from lsmiotool.lib.evidence import EvidenceKind, EvidenceStore, JobHandle
from lsmiotool.lib.main import ParseMain
from lsmiotool.lib.profile import ProfileLoader
from lsmiotool.lib.run import (
    RunPlan,
    RunPlanner,
    RunRequest,
)
from lsmiotool.lib.site import EnvironmentResolver


class ParseMainTest(unittest.TestCase):
    """Unit and functional end-to-end tests for modern ParseMain controller and strict exit codes."""

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.mkdtemp(prefix="lsmiotool-parsemain-test-")
        self.m_default_profile_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "etc", "environments.json")
        )
        self.m_profile_doc = ProfileLoader.load(self.m_default_profile_path)
        self.m_test_user = "alice"
        self.m_test_home = "/home/alice"
        self.m_registry = EnvironmentResolver.resolveRegistry(
            self.m_profile_doc, f_user=self.m_test_user, f_home=self.m_test_home
        )
        self.m_viking_profile = self.m_registry.getProfile("VIKING")
        self.m_original_cwd = os.getcwd()

    def tearDown(self) -> None:
        os.chdir(self.m_original_cwd)
        shutil.rmtree(self.m_temp_dir, ignore_errors=True)

    def _createPlan(
        self,
        f_run_id: str,
        f_target: str = "lsmio",
        f_scale: str = "local",
        f_setup: str = "NATIVE-M",
        f_ssd: bool = False,
    ) -> RunPlan:
        f_req = RunRequest(
            f_target=f_target,
            f_scale=f_scale,
            f_ssd=f_ssd,
            f_setup=f_setup,
        )
        f_tokens = [f"lm-{f_i:024d}" for f_i in range(1, 30)]
        f_tok_idx = 0

        def token_gen() -> str:
            nonlocal f_tok_idx
            f_tok = f_tokens[f_tok_idx]
            f_tok_idx += 1
            return f_tok

        return RunPlanner.createPlan(
            f_request=f_req,
            f_profile=self.m_viking_profile,
            f_run_id_source=lambda: f_run_id,
            f_clock=lambda: "2026-08-21T12:00:00Z",
            f_token_source=token_gen,
        )

    def _setupSucceededRun(
        self,
        f_run_id: str,
        f_target: str = "lsmio",
        f_scale: str = "local",
        f_setup: str = "NATIVE-M",
        f_ssd: bool = False,
        f_base_dir: str = "",
    ) -> Tuple[str, RunPlan]:
        f_plan = self._createPlan(f_run_id, f_target=f_target, f_scale=f_scale, f_setup=f_setup, f_ssd=f_ssd)
        f_runs_base = f_base_dir if f_base_dir else self.m_temp_dir
        f_art_store = ArtifactStore(f_runs_base, f_run_id)
        f_art_store.allocateRun(f_plan)
        f_evidence_store = EvidenceStore(f_art_store.layout, f_plan=f_plan)

        f_is_lsmio = (f_target.lower() == "lsmio")

        for f_idx, f_sp in enumerate(f_plan.scale_points):
            f_art_store.preparePoint(f_sp, f_ordinal=f_idx)
            f_handle = JobHandle("slurm", f"100{f_idx + 1}")

            f_evidence_store.recordSubmissionRequested(f_sp, "client", f_ordinal=f_idx)
            f_evidence_store.recordSubmissionDispatched(f_sp, "client", f_ordinal=f_idx)
            f_evidence_store.recordSubmissionRecorded(f_sp, "client", f_handle=f_handle, f_ordinal=f_idx)
            f_evidence_store.recordWorkerEvent(f_sp, 1, EvidenceKind.CONTROLLER_STARTED, f_ordinal=f_idx)

            for f_combo in f_plan.combinations:
                f_evidence_store.recordControllerResult(
                    f_sp, f_combo, f_payload={"exit_code": 0, "status": "success"}, f_ordinal=f_idx
                )
                if f_is_lsmio:
                    for f_rank in range(f_sp.tasks):
                        f_evidence_store.recordRankResult(
                            f_sp,
                            f_global_rank=f_rank,
                            f_combination=f_combo,
                            f_payload={"exit_code": 0, "status": "success"},
                            f_ordinal=f_idx,
                        )

            f_evidence_store.recordSchedulerObservation(
                f_sp,
                "reconciler",
                1,
                f_payload={"state": "succeeded", "handle": f_handle.toDict()},
                f_ordinal=f_idx,
            )

        f_evidence_store.recordWholeRunSucceeded("client", 1, f_payload={"summary": "all passed"})
        return f_art_store.layout.runRoot, f_plan

    def _writeMockLogs(self, f_run_root: str, f_plan: RunPlan) -> None:
        """Write synthetic valid output logs for all scale points and combinations."""
        f_target = f_plan.request.target.lower()

        for f_idx, f_sp in enumerate(f_plan.scale_points):
            f_pt_dir_name = f"{f_idx:02d}-tasks-{f_sp.tasks}"
            f_logs_dir = os.path.join(f_run_root, "points", f_pt_dir_name, "logs")
            os.makedirs(f_logs_dir, exist_ok=True)

            for f_combo in f_plan.combinations:
                if f_target == "ior":
                    f_log_path = os.path.join(f_logs_dir, f"ior_{f_combo.name}.stdout")
                    with open(f_log_path, "w") as f_f:
                        f_f.write(
                            "IOR-3.3.0: MPI Coordinated Test of Parallel I/O\n"
                            "Summary of all tests:\n"
                            "Operation   Max(MiB)   Min(MiB)  Mean(MiB)     StdDev   Max(OPs)   Min(OPs)  Mean(OPs)     StdDev    Mean(s) Stonewl(s) Stonewl(MiB) Test# #Tasks tPN reps fPP reord reordoff reordrand seed segcnt blksiz    xsize aggs(MiB)   API RefNum\n"
                            "write        1200.00    1000.00    1100.00      50.00    1200.00    1000.00    1100.00      50.00     1.500         NA           NA     0      1   1    1   0     0        1         0    0      1 1048576  1048576       1.0 POSIX      0\n"
                            "read         2400.00    2000.00    2200.00      60.00    2400.00    2000.00    2200.00      60.00     0.750         NA           NA     0      1   1    1   0     0        1         0    0      1 1048576  1048576       1.0 POSIX      0\n"
                        )
                elif f_target == "lsmio":
                    f_combo_dir = os.path.join(f_logs_dir, f_combo.name)
                    os.makedirs(f_combo_dir, exist_ok=True)
                    for f_rank in range(f_sp.tasks):
                        f_rank_path = os.path.join(f_combo_dir, f"rank_{f_rank}.log")
                        with open(f_rank_path, "w") as f_f:
                            f_f.write(
                                "LSMIO initialization...\n"
                                "Bench-WRITE:\n"
                                "write,1200.0,0.85,1024,1024,5\n"
                                "iwrite,1100.0\n"
                                "iwrite,1200.0\n"
                                "iwrite,1300.0\n"
                                "Bench-READ:\n"
                                "read,2400.0,0.42,1024,1024,5\n"
                                "iread,2300.0\n"
                                "iread,2400.0\n"
                                "iread,2500.0\n"
                            )
                elif f_target in ("lmp", "lammps"):
                    f_log_path = os.path.join(f_logs_dir, f"lmp_{f_combo.name}.stdout")
                    with open(f_log_path, "w") as f_f:
                        f_f.write(
                            "LAMMPS output log\n"
                            "write, 1MB, 500.00\n"
                            "Total wall time: 0:00:10\n"
                        )

    def testParseMainSuccessExitCodeZero(self) -> None:
        """Tests successful end-to-end execution of ParseMain across LSMIO, IOR, and LAMMPS returning exit code 0."""
        # 1. LSMIO end-to-end parse
        f_run_root_lsm, f_plan_lsm = self._setupSucceededRun("run-e2e-lsm-001", "lsmio", "local", "NATIVE-M")
        self._writeMockLogs(f_run_root_lsm, f_plan_lsm)
        f_out_dir_lsm = os.path.join(self.m_temp_dir, "out_lsm")

        f_stdout_capture = io.StringIO()
        f_stderr_capture = io.StringIO()

        f_inst_lsm = ParseMain(f_run_root_lsm, "--output-dir", f_out_dir_lsm)
        self.assertEqual(f_inst_lsm.target, f_run_root_lsm)
        self.assertEqual(f_inst_lsm.output_dir, f_out_dir_lsm)
        self.assertEqual(f_inst_lsm.outputDir, f_out_dir_lsm)
        self.assertEqual(f_inst_lsm.format, "csv")
        self.assertIsNotNone(f_inst_lsm.request)

        with unittest.mock.patch("sys.stdout", f_stdout_capture), unittest.mock.patch("sys.stderr", f_stderr_capture):
            f_exit_code = f_inst_lsm.run()

        self.assertEqual(f_exit_code, 0)
        self.assertEqual(f_stderr_capture.getvalue(), "")
        self.assertIn("Benchmark", f_stdout_capture.getvalue())
        self.assertIn("LSMIO", f_stdout_capture.getvalue())
        self.assertTrue(os.path.isfile(os.path.join(f_out_dir_lsm, "lsm-report.csv")))
        f_first_c = f_plan_lsm.combinations[0]
        self.assertTrue(os.path.isfile(os.path.join(f_out_dir_lsm, "1", f"agg-{f_first_c.stripe_count}-{f_first_c.block_size}-report.csv")))

        # 2. IOR end-to-end parse with JSON output
        f_run_root_ior, f_plan_ior = self._setupSucceededRun("run-e2e-ior-002", "ior", "local", "BASE")
        self._writeMockLogs(f_run_root_ior, f_plan_ior)
        f_out_dir_ior = os.path.join(self.m_temp_dir, "out_ior")

        f_inst_ior = ParseMain(f_run_root_ior, "--output-dir", f_out_dir_ior, "--format", "json")
        self.assertEqual(f_inst_ior.format, "json")

        f_stdout_capture = io.StringIO()
        f_stderr_capture = io.StringIO()
        with unittest.mock.patch("sys.stdout", f_stdout_capture), unittest.mock.patch("sys.stderr", f_stderr_capture):
            f_exit_code = f_inst_ior.run()

        self.assertEqual(f_exit_code, 0)
        self.assertIn("IOR", f_stdout_capture.getvalue())
        self.assertTrue(os.path.isfile(os.path.join(f_out_dir_ior, "ior-report.csv")))
        self.assertTrue(os.path.isfile(os.path.join(f_out_dir_ior, "ior-report.json")))

        # 3. LAMMPS end-to-end parse
        f_run_root_lmp, f_plan_lmp = self._setupSucceededRun("run-e2e-lmp-003", "lmp", "local", "FS")
        self._writeMockLogs(f_run_root_lmp, f_plan_lmp)
        f_out_dir_lmp = os.path.join(self.m_temp_dir, "out_lmp")

        f_inst_lmp = ParseMain(f_run_root_lmp, "--output-dir", f_out_dir_lmp)
        f_stdout_capture = io.StringIO()
        f_stderr_capture = io.StringIO()
        with unittest.mock.patch("sys.stdout", f_stdout_capture), unittest.mock.patch("sys.stderr", f_stderr_capture):
            f_exit_code = f_inst_lmp.run()

        self.assertEqual(f_exit_code, 0)
        self.assertIn("LMP", f_stdout_capture.getvalue())
        self.assertTrue(os.path.isfile(os.path.join(f_out_dir_lmp, "lmp-report.csv")))

    def testParseMainInvalidArgumentsExitCodeTwo(self) -> None:
        """Tests that invalid CLI arguments, options, or flags result in exit code 2 and diagnostics on stderr."""
        f_invalid_cases = [
            [],
            ["--output-dir", "/tmp/reports"],
            ["--format", "json"],
            ["ior", "--format", "xml"],
            ["ior", "--format", "csv", "--format", "json"],
            ["ior", "--output-dir", "/tmp/1", "--output-dir", "/tmp/2"],
            ["ior", "--unknown-flag"],
            ["ior", "-x"],
            ["ior", "--output-dir"],
            ["ior", "extra", "positional"],
        ]

        for f_args in f_invalid_cases:
            f_inst = ParseMain(*f_args)
            f_stderr = io.StringIO()
            with unittest.mock.patch("sys.stderr", f_stderr):
                f_code = f_inst.run()
            self.assertEqual(
                f_code, 2, f"Expected exit code 2 for args {f_args}, got {f_code}"
            )
            self.assertTrue(
                len(f_stderr.getvalue()) > 0, f"Expected stderr output for args {f_args}"
            )

        # Direct invalid kwargs
        f_inst_kw = ParseMain(target="", format="csv")
        f_stderr = io.StringIO()
        with unittest.mock.patch("sys.stderr", f_stderr):
            f_code = f_inst_kw.run()
        self.assertEqual(f_code, 2)

    def testParseMainMissingArtifactsExitCodeThree(self) -> None:
        """Tests that missing run root, missing manifest.json, or symlink violations return exit code 3."""
        # 1. Non-existent run root directory
        f_non_existent = os.path.join(self.m_temp_dir, "runs", "non-existent-run-001")
        f_inst1 = ParseMain(f_non_existent)
        f_stderr = io.StringIO()
        with unittest.mock.patch("sys.stderr", f_stderr):
            f_code = f_inst1.run()
        self.assertEqual(f_code, 3)
        self.assertIn("does not exist", f_stderr.getvalue())

        # 2. Directory missing manifest.json
        f_no_man_dir = os.path.join(self.m_temp_dir, "runs", "no-man-run-002")
        os.makedirs(f_no_man_dir, exist_ok=True)
        f_inst2 = ParseMain(f_no_man_dir)
        f_stderr = io.StringIO()
        with unittest.mock.patch("sys.stderr", f_stderr):
            f_code = f_inst2.run()
        self.assertEqual(f_code, 3)
        self.assertIn("manifest.json", f_stderr.getvalue())

        # 3. Symlinked run root directory
        f_real_root, _ = self._setupSucceededRun("run-real-003", "lsmio", "local")
        f_sym_root = os.path.join(self.m_temp_dir, "runs", "sym-run-003")
        os.symlink(f_real_root, f_sym_root)
        f_inst3 = ParseMain(f_sym_root)
        f_stderr = io.StringIO()
        with unittest.mock.patch("sys.stderr", f_stderr):
            f_code = f_inst3.run()
        self.assertEqual(f_code, 3)
        self.assertIn("must not be a symlink", f_stderr.getvalue())

        # 4. Target is a regular file, not a directory
        f_file_target = os.path.join(self.m_temp_dir, "runs", "file-target-004")
        with open(f_file_target, "w") as f_f:
            f_f.write("regular file")
        f_inst4 = ParseMain(f_file_target)
        f_stderr = io.StringIO()
        with unittest.mock.patch("sys.stderr", f_stderr):
            f_code = f_inst4.run()
        self.assertEqual(f_code, 3)
        self.assertIn("must be a directory", f_stderr.getvalue())

    def testParseMainIncompleteStateExitCodeFour(self) -> None:
        """Tests that incomplete, interrupted, or failed run roots return exit code 4."""
        # 1. Unstarted run (only allocated)
        f_plan_unstarted = self._createPlan("run-unstarted-001", "lsmio", "local")
        f_store_unstarted = ArtifactStore(self.m_temp_dir, "run-unstarted-001")
        f_store_unstarted.allocateRun(f_plan_unstarted)

        f_inst1 = ParseMain(f_store_unstarted.layout.runRoot)
        f_stderr = io.StringIO()
        with unittest.mock.patch("sys.stderr", f_stderr):
            f_code = f_inst1.run()
        self.assertEqual(f_code, 4)
        self.assertIn("did not succeed", f_stderr.getvalue())

        # 2. Interrupted run (point 0 done, point 1 interrupted)
        f_plan_int = self._createPlan("run-interrupted-002", "lsmio", "bake")
        f_store_int = ArtifactStore(self.m_temp_dir, "run-interrupted-002")
        f_store_int.allocateRun(f_plan_int)
        f_ev_int = EvidenceStore(f_store_int.layout, f_plan=f_plan_int)

        # Complete point 0
        f_sp0 = f_plan_int.scale_points[0]
        f_store_int.preparePoint(f_sp0, f_ordinal=0)
        f_handle0 = JobHandle("slurm", "4001")
        f_ev_int.recordSubmissionRequested(f_sp0, "client", f_ordinal=0)
        f_ev_int.recordSubmissionDispatched(f_sp0, "client", f_ordinal=0)
        f_ev_int.recordSubmissionRecorded(f_sp0, "client", f_handle=f_handle0, f_ordinal=0)
        f_ev_int.recordWorkerEvent(f_sp0, 1, EvidenceKind.CONTROLLER_STARTED, f_ordinal=0)
        for f_c in f_plan_int.combinations:
            f_ev_int.recordControllerResult(f_sp0, f_c, f_payload={"exit_code": 0}, f_ordinal=0)
            f_ev_int.recordRankResult(f_sp0, 0, f_c, f_payload={"exit_code": 0}, f_ordinal=0)
        f_ev_int.recordSchedulerObservation(
            f_sp0, "reconciler", 1, f_payload={"state": "succeeded", "handle": f_handle0.toDict()}, f_ordinal=0
        )

        # Prepare point 1 and record interruption
        f_sp1 = f_plan_int.scale_points[1]
        f_store_int.preparePoint(f_sp1, f_ordinal=1)
        f_ev_int.recordInterruption("client", 1, f_payload={"reason": "SIGINT"})

        f_inst2 = ParseMain(f_store_int.layout.runRoot)
        f_stderr = io.StringIO()
        with unittest.mock.patch("sys.stderr", f_stderr):
            f_code = f_inst2.run()
        self.assertEqual(f_code, 4)

        # 3. Failed run (combination failed)
        f_plan_fail = self._createPlan("run-failed-003", "lsmio", "local")
        f_store_fail = ArtifactStore(self.m_temp_dir, "run-failed-003")
        f_store_fail.allocateRun(f_plan_fail)
        f_sp_f = f_plan_fail.scale_points[0]
        f_store_fail.preparePoint(f_sp_f, f_ordinal=0)
        f_ev_f = EvidenceStore(f_store_fail.layout, f_plan=f_plan_fail)
        f_handle_f = JobHandle("slurm", "4002")
        f_ev_f.recordSubmissionRequested(f_sp_f, "client", f_ordinal=0)
        f_ev_f.recordSubmissionDispatched(f_sp_f, "client", f_ordinal=0)
        f_ev_f.recordSubmissionRecorded(f_sp_f, "client", f_handle=f_handle_f, f_ordinal=0)
        f_ev_f.recordWorkerEvent(f_sp_f, 1, EvidenceKind.CONTROLLER_STARTED, f_ordinal=0)
        for f_c in f_plan_fail.combinations:
            f_ev_f.recordControllerResult(f_sp_f, f_c, f_payload={"exit_code": 1}, f_ordinal=0)
            f_ev_f.recordRankResult(f_sp_f, 0, f_c, f_payload={"exit_code": 1}, f_ordinal=0)
        f_ev_f.recordSchedulerObservation(
            f_sp_f, "reconciler", 1, f_payload={"state": "failed", "handle": f_handle_f.toDict()}, f_ordinal=0
        )

        f_inst3 = ParseMain(f_store_fail.layout.runRoot)
        f_stderr = io.StringIO()
        with unittest.mock.patch("sys.stderr", f_stderr):
            f_code = f_inst3.run()
        self.assertEqual(f_code, 4)

    def testParseMainExtractionErrorExitCodeFive(self) -> None:
        """Tests that missing or malformed output log files return exit code 5."""
        # 1. Missing log files in a succeeded LSMIO run
        f_run_root_lsm, _ = self._setupSucceededRun("run-ext-err-lsm-001", "lsmio", "local", "NATIVE-M")
        # Do NOT write mock logs
        f_inst1 = ParseMain(f_run_root_lsm)
        f_stderr = io.StringIO()
        with unittest.mock.patch("sys.stderr", f_stderr):
            f_code = f_inst1.run()
        self.assertEqual(f_code, 5)
        self.assertIn("Rank log file does not exist", f_stderr.getvalue())

        # 2. Malformed log file in a succeeded IOR run
        f_run_root_ior, f_plan_ior = self._setupSucceededRun("run-ext-err-ior-002", "ior", "local", "BASE")
        self._writeMockLogs(f_run_root_ior, f_plan_ior)
        # Create corrupted log file for combination 0
        f_pt_dir = os.path.join(f_run_root_ior, "points", "00-tasks-1", "logs")
        with open(os.path.join(f_pt_dir, f"ior_{f_plan_ior.combinations[0].name}.stdout"), "w") as f_f:
            f_f.write("Corrupted log file without summary tables\n")

        f_inst2 = ParseMain(f_run_root_ior)
        f_stderr = io.StringIO()
        with unittest.mock.patch("sys.stderr", f_stderr):
            f_code = f_inst2.run()
        self.assertEqual(f_code, 5)
        self.assertIn("missing 'Summary of all tests'", f_stderr.getvalue())

    def testParseMainTargetResolutionBenchmarkName(self) -> None:
        """Tests target resolution via benchmark name alias and manifest.json path."""
        # Setup benchmark folder hierarchy under temp_dir: <temp_dir>/benchmarks/ior/runs/<run_id>
        f_bm_root = os.path.join(self.m_temp_dir, "benchmarks", "ior")
        f_runs_dir = os.path.join(f_bm_root, "runs")
        os.makedirs(f_runs_dir, exist_ok=True)

        f_run_root_ior, f_plan_ior = self._setupSucceededRun(
            "2026-08-21T12-00-00Z-ior-local", "ior", "local", "BASE", f_base_dir=f_bm_root
        )
        self._writeMockLogs(f_run_root_ior, f_plan_ior)

        # Switch cwd to temp_dir so inferLatestRun discovers cwd/benchmarks/ior/runs
        os.chdir(self.m_temp_dir)

        # 1. Parse via benchmark name "ior"
        f_out_dir = os.path.join(self.m_temp_dir, "reports_bm_name")
        f_inst_name = ParseMain("ior", "--output-dir", f_out_dir)

        f_stdout = io.StringIO()
        f_stderr = io.StringIO()
        with unittest.mock.patch("sys.stdout", f_stdout), unittest.mock.patch("sys.stderr", f_stderr):
            f_code = f_inst_name.run()

        self.assertEqual(f_code, 0)
        self.assertEqual(f_stderr.getvalue(), "")
        self.assertTrue(os.path.isfile(os.path.join(f_out_dir, "ior-report.csv")))

        # 2. Parse via manifest.json path
        f_manifest_path = os.path.join(f_run_root_ior, "manifest.json")
        f_out_dir_man = os.path.join(self.m_temp_dir, "reports_man")
        f_inst_man = ParseMain(f_manifest_path, "--output-dir", f_out_dir_man)

        f_stdout = io.StringIO()
        f_stderr = io.StringIO()
        with unittest.mock.patch("sys.stdout", f_stdout), unittest.mock.patch("sys.stderr", f_stderr):
            f_code = f_inst_man.run()

        self.assertEqual(f_code, 0)
        self.assertEqual(f_stderr.getvalue(), "")
        self.assertTrue(os.path.isfile(os.path.join(f_out_dir_man, "ior-report.csv")))

    def testParseMainConstructorsAndValidation(self) -> None:
        """Tests ParseMain constructor flexibility and type validation."""
        f_req = ParseRequest("ior", "/tmp/out", "json")

        # 1. Constructor with ParseRequest object
        f_m1 = ParseMain(f_request=f_req)
        self.assertEqual(f_m1.target, "ior")
        self.assertEqual(f_m1.output_dir, "/tmp/out")
        self.assertEqual(f_m1.format, "json")

        # 2. Positional ParseRequest
        f_m2 = ParseMain(f_req)
        self.assertEqual(f_m2.target, "ior")

        # 3. List of tokens
        f_m3 = ParseMain(["ior", "--output-dir", "/tmp/out", "--format", "csv"])
        self.assertEqual(f_m3.target, "ior")
        self.assertEqual(f_m3.output_dir, "/tmp/out")
        self.assertEqual(f_m3.format, "csv")

        # 4. Keyword arguments
        f_m4 = ParseMain(target="lsmio", output_dir="/tmp/out2", format="json")
        self.assertEqual(f_m4.target, "lsmio")
        self.assertEqual(f_m4.output_dir, "/tmp/out2")
        self.assertEqual(f_m4.format, "json")

        # 5. Invalid f_request type raises ValueError
        with self.assertRaises(ValueError):
            ParseMain(f_request="not_a_request")


if __name__ == "__main__":
    unittest.main()
