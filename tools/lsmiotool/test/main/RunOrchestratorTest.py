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

import json
import os
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Sequence
import unittest

from lsmiotool.lib.artifacts import (
    ArtifactLayout,
    ArtifactStore,
    ControlLock,
    LockContentionError,
)
from lsmiotool.lib.evidence import (
    EvidenceKind,
    EvidenceRecord,
    EvidenceStore,
    JobHandle,
    WriterKind,
)
from lsmiotool.lib.profile import ProfileLoader
from lsmiotool.lib.resources import ExecutionMode, RuntimeLayout
from lsmiotool.lib.run import (
    OrchestrationError,
    PreflightError,
    RunOrchestrator,
    RunPlan,
    RunPlanner,
    RunRequest,
    ScalePoint,
)
from lsmiotool.lib.scheduler import (
    JobResult,
    JobSpec,
    PbsSchedulerAdapter,
    SchedulerAdapter,
    SchedulerCommandRunner,
    SlurmSchedulerAdapter,
    SubmissionDispatchError,
)
from lsmiotool.lib.site import EnvironmentResolver, SchedulerKind, SiteProfile
from lsmiotool.lib.state import (
    OverallRunState,
    PointRunState,
    RunStateView,
    SchedulerJobState,
    StateReconciler,
)
from lsmiotool.lib.worker import ProcessResult


class FakeSchedulerCommandRunner(SchedulerCommandRunner):
    """Configurable test fake for SchedulerCommandRunner simulating Slurm / PBS commands."""

    def __init__(self) -> None:
        super().__init__()
        self.m_calls: List[List[str]] = []
        self.m_submit_job_ids: List[str] = []
        self.m_submit_idx = 0
        self.m_submit_fail = False
        self.m_query_fail = False
        self.m_job_fail = False
        self.m_recovery_candidates: Dict[str, List[str]] = {}
        self.m_on_submit_callback = None

    def run(
        self,
        f_argv: Sequence[str],
        f_cwd: Optional[str] = None,
        f_environment: Optional[Dict[str, str]] = None,
        f_log_path: Optional[str] = None,
    ) -> ProcessResult:
        f_cmd = list(f_argv)
        self.m_calls.append(f_cmd)
        f_exe = os.path.basename(f_cmd[0])

        if f_exe == "sbatch":
            if self.m_submit_fail:
                return ProcessResult(1, "", "sbatch: error: Invalid partition\n", 0.01)
            if self.m_submit_idx < len(self.m_submit_job_ids):
                f_jid = self.m_submit_job_ids[self.m_submit_idx]
                self.m_submit_idx += 1
            else:
                f_jid = f"{1000 + self.m_submit_idx}"
                self.m_submit_idx += 1
            if self.m_on_submit_callback is not None:
                self.m_on_submit_callback(f_jid, f_cwd)
            return ProcessResult(0, f"{f_jid}\n", "", 0.01)

        elif f_exe == "squeue":
            if self.m_query_fail:
                return ProcessResult(1, "", "squeue: error: Slurm controller down\n", 0.01)
            # Check if recovery query (--name=...)
            for f_arg in f_cmd:
                if f_arg.startswith("--name="):
                    f_name = f_arg.split("=", 1)[1]
                    f_cands = self.m_recovery_candidates.get(f_name, [])
                    f_lines = [f"{f_cid}|{f_name}|RUNNING" for f_cid in f_cands]
                    return ProcessResult(0, "\n".join(f_lines) + ("\n" if f_lines else ""), "", 0.01)
            # Ordinary active query -> return empty so it falls back to accounting (completed)
            return ProcessResult(0, "", "", 0.01)

        elif f_exe == "sacct":
            if self.m_query_fail:
                return ProcessResult(1, "", "sacct: error: Slurmdbd down\n", 0.01)
            # Check if recovery query (--name=...)
            for f_arg in f_cmd:
                if f_arg.startswith("--name="):
                    f_name = f_arg.split("=", 1)[1]
                    f_cands = self.m_recovery_candidates.get(f_name, [])
                    f_lines = ["JobIDRaw|JobName|State|ExitCode"] + [
                        f"{f_cid}|{f_name}|COMPLETED|0:0" for f_cid in f_cands
                    ]
                    return ProcessResult(0, "\n".join(f_lines) + "\n", "", 0.01)
            # Extract job ID if present
            f_jid = "1000"
            for f_idx, f_arg in enumerate(f_cmd):
                if f_arg == "-j" and f_idx + 1 < len(f_cmd):
                    f_jid = f_cmd[f_idx + 1]
            if self.m_job_fail:
                return ProcessResult(0, f"{f_jid}|FAILED|1:0\n", "", 0.01)
            return ProcessResult(0, f"{f_jid}|COMPLETED|0:0\n", "", 0.01)

        elif f_exe == "qsub":
            if self.m_submit_fail:
                return ProcessResult(1, "", "qsub: error: Resource limit\n", 0.01)
            if self.m_submit_idx < len(self.m_submit_job_ids):
                f_jid = self.m_submit_job_ids[self.m_submit_idx]
                self.m_submit_idx += 1
            else:
                f_jid = f"{2000 + self.m_submit_idx}"
                self.m_submit_idx += 1
            if self.m_on_submit_callback is not None:
                self.m_on_submit_callback(f_jid, f_cwd)
            return ProcessResult(0, f"{f_jid}.server\n", "", 0.01)

        elif f_exe == "qstat":
            if self.m_query_fail:
                return ProcessResult(1, "", "qstat: error: Server unavailable\n", 0.01)
            # If -u <user> whole-user recovery
            if "-u" in f_cmd:
                f_jobs_dict = {}
                for f_name, f_cands in self.m_recovery_candidates.items():
                    for f_cid in f_cands:
                        f_jobs_dict[f"{f_cid}.server"] = {
                            "Job_Name": f_name,
                            "job_state": "F",
                            "Exit_status": 0,
                        }
                return ProcessResult(0, json.dumps({"Jobs": f_jobs_dict}), "", 0.01)
            # Job query: check if -x (historical)
            if "-x" in f_cmd:
                f_jid = f_cmd[-1].split(".")[0]
                if self.m_job_fail:
                    f_job_data = {"job_state": "F", "Exit_status": 1}
                else:
                    f_job_data = {"job_state": "F", "Exit_status": 0}
                return ProcessResult(0, json.dumps({"Jobs": {f"{f_jid}.server": f_job_data}}), "", 0.01)
            else:
                # Active query -> empty Jobs object
                return ProcessResult(0, json.dumps({"Jobs": {}}), "", 0.01)

        elif f_exe == "scancel" or f_exe == "qdel":
            return ProcessResult(0, "", "", 0.01)

        # Default fallback
        return ProcessResult(0, "", "", 0.01)


class RunOrchestratorTest(unittest.TestCase):
    """Unit tests for RunOrchestrator covering all Chunk 024 contract and plan requirements."""

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.mkdtemp(prefix="lsmiotool-orchestrator-test-")
        self.m_default_profile_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "etc", "environments.json")
        )
        self.m_profile_doc = ProfileLoader.load(self.m_default_profile_path)
        self.m_test_user = "alice"
        self.m_test_home = os.path.join(self.m_temp_dir, "home")
        os.makedirs(self.m_test_home, exist_ok=True)
        self.m_registry = EnvironmentResolver.resolveRegistry(
            self.m_profile_doc, f_user=self.m_test_user, f_home=self.m_test_home
        )

        # Create isolated test profiles pointing roots to self.m_temp_dir
        f_base_viking = self.m_registry.getProfile("VIKING")
        self.m_viking_root_hdd = os.path.join(self.m_temp_dir, "viking_hdd")
        self.m_viking_root_ssd = os.path.join(self.m_temp_dir, "viking_ssd")
        os.makedirs(self.m_viking_root_hdd, exist_ok=True)
        os.makedirs(self.m_viking_root_ssd, exist_ok=True)

        self.m_viking_profile = SiteProfile(
            f_name=f_base_viking.name,
            f_scheduler=f_base_viking.scheduler,
            f_launcher=f_base_viking.launcher,
            f_certification=f_base_viking.certification,
            f_test_only=True,
            f_benchmark_roots={"hdd": self.m_viking_root_hdd, "ssd": self.m_viking_root_ssd},
            f_install_prefix=f_base_viking.install_prefix,
            f_executables=f_base_viking.executables,
            f_modules=f_base_viking.modules,
            f_resources=f_base_viking.resources,
            f_rank_identity=f_base_viking.rank_identity,
            f_cancellation=f_base_viking.cancellation,
            f_lustre_pools=f_base_viking.lustre_pools,
        )

        f_base_isambard = self.m_registry.getProfile("ISAMBARD")
        self.m_isambard_root_hdd = os.path.join(self.m_temp_dir, "isambard_hdd")
        self.m_isambard_root_ssd = os.path.join(self.m_temp_dir, "isambard_ssd")
        os.makedirs(self.m_isambard_root_hdd, exist_ok=True)
        os.makedirs(self.m_isambard_root_ssd, exist_ok=True)

        self.m_isambard_profile = SiteProfile(
            f_name=f_base_isambard.name,
            f_scheduler=f_base_isambard.scheduler,
            f_launcher=f_base_isambard.launcher,
            f_certification=f_base_isambard.certification,
            f_test_only=True,
            f_benchmark_roots={"hdd": self.m_isambard_root_hdd, "ssd": self.m_isambard_root_ssd},
            f_install_prefix=f_base_isambard.install_prefix,
            f_executables=f_base_isambard.executables,
            f_modules=f_base_isambard.modules,
            f_resources=f_base_isambard.resources,
            f_rank_identity=f_base_isambard.rank_identity,
            f_cancellation=f_base_isambard.cancellation,
            f_lustre_pools=f_base_isambard.lustre_pools,
        )

        self.m_fake_runner = FakeSchedulerCommandRunner()
        self.m_worker_path = os.path.join(self.m_temp_dir, "bin", "lsmiotool-worker")
        os.makedirs(os.path.dirname(self.m_worker_path), exist_ok=True)
        with open(self.m_worker_path, "w") as f_f:
            f_f.write("#!/bin/sh\nexit 0\n")
        os.chmod(self.m_worker_path, 0o755)

    def tearDown(self) -> None:
        shutil.rmtree(self.m_temp_dir, ignore_errors=True)

    def _mockWritePointResults(
        self,
        f_evidence_store: EvidenceStore,
        f_scale_point: ScalePoint,
        f_plan: RunPlan,
        f_ordinal: int = 0,
        f_failed: bool = False,
    ) -> None:
        """Helper to write controller results and LSMIO rank results for all combinations in a point."""
        f_is_lsmio = (f_plan.request.target.lower() == "lsmio")
        for f_combo in f_plan.combinations:
            f_ret = 1 if f_failed else 0
            f_evidence_store.recordControllerResult(
                f_point=f_scale_point,
                f_combination=f_combo,
                f_payload={"returncode": f_ret, "status": "failed" if f_failed else "completed"},
                f_ordinal=f_ordinal,
            )
            if f_is_lsmio:
                for f_r in range(f_scale_point.tasks):
                    f_evidence_store.recordRankResult(
                        f_point=f_scale_point,
                        f_global_rank=f_r,
                        f_combination=f_combo,
                        f_payload={"returncode": f_ret, "status": "failed" if f_failed else "completed"},
                        f_ordinal=f_ordinal,
                    )

    def testPreflightBeforeMutation(self) -> None:
        """Asserts preflight failure aborts before creating run directory or writing manifest."""
        f_benchmark_root = self.m_viking_profile.benchmark_roots["hdd"]
        if os.path.exists(f_benchmark_root):
            shutil.rmtree(f_benchmark_root)
        os.makedirs(f_benchmark_root, exist_ok=True)

        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
        )

        # Invalid target raises PreflightError
        with self.assertRaises(PreflightError):
            f_orch.execute(
                RunRequest("invalid_target", "local"),
                f_site=self.m_viking_profile,
            )

        # Invalid scale raises PreflightError
        with self.assertRaises(PreflightError):
            f_orch.execute(
                RunRequest("ior", "invalid_scale"),
                f_site=self.m_viking_profile,
            )

        # Invalid setup raises PreflightError
        with self.assertRaises(PreflightError):
            f_orch.execute(
                RunRequest("ior", "local", f_setup="INVALID_SETUP"),
                f_site=self.m_viking_profile,
            )

        # Verify no run directories were created
        self.assertFalse(
            os.path.exists(os.path.join(f_benchmark_root, "runs")),
            "Runs directory should not exist after preflight failure",
        )

    def testInjectedWorkerValidationFailureBeforeMutation(self) -> None:
        """Asserts injected worker validator failure prevents run allocation."""
        f_benchmark_root = self.m_viking_profile.benchmark_roots["hdd"]

        def failing_validator(f_path: str) -> str:
            raise ValueError(f"Worker executable at '{f_path}' is corrupted or invalid")

        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_worker_validator=failing_validator,
            f_command_runner=self.m_fake_runner,
        )

        with self.assertRaises(PreflightError) as f_ctx:
            f_orch.execute(
                RunRequest("ior", "local"),
                f_site=self.m_viking_profile,
                f_worker_executable="/path/to/corrupt/worker",
            )
        self.assertIn("validation failed", str(f_ctx.exception))

        # Verify no directory or lock or manifest was created
        self.assertFalse(
            os.path.exists(os.path.join(f_benchmark_root, "runs")),
            "Runs directory should not exist after worker validation failure",
        )

    def testRuntimeLayoutIsNeverUsedAsValidator(self) -> None:
        """Uses spy to assert RuntimeLayout methods are not used for filesystem validation."""
        f_layout = RuntimeLayout(
            f_execution_mode=ExecutionMode.SOURCE,
            f_package_root="/usr/local/lsmio",
            f_profile_file="/usr/local/lsmio/environments.json",
            f_asset_root="/usr/local/lsmio/assets",
            f_worker_executable=self.m_worker_path,
            f_version_file="/usr/local/lsmio/VERSION",
        )

        f_accessed_attrs = []
        f_original_getattr = RuntimeLayout.__getattribute__

        def spy_getattr(self_obj: Any, f_name: str) -> Any:
            f_accessed_attrs.append(f_name)
            return f_original_getattr(self_obj, f_name)

        f_validator_called = False

        def tracking_validator(f_path: str) -> str:
            nonlocal f_validator_called
            f_validator_called = True
            self.assertEqual(f_path, self.m_worker_path)
            return f_path

        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_worker_validator=tracking_validator,
            f_command_runner=self.m_fake_runner,
            f_poll_interval=0.01,
        )

        def on_submit(f_jid: str, f_cwd: Optional[str]) -> None:
            if f_orch.last_evidence_store and f_orch.last_plan:
                self._mockWritePointResults(
                    f_orch.last_evidence_store,
                    f_orch.last_plan.scale_points[0],
                    f_orch.last_plan,
                    f_ordinal=0,
                )

        self.m_fake_runner.m_on_submit_callback = on_submit
        self.m_fake_runner.m_submit_job_ids = ["1001"]

        try:
            RuntimeLayout.__getattribute__ = spy_getattr
            f_view = f_orch.execute(
                RunRequest("ior", "local"),
                f_site=self.m_viking_profile,
                f_runtime_layout=f_layout,
            )
        finally:
            RuntimeLayout.__getattribute__ = f_original_getattr

        self.assertTrue(f_validator_called, "Injected validator must be called")
        self.assertIn("worker_executable", f_accessed_attrs)
        for f_forbidden in ("exists", "is_file", "is_dir", "stat", "lstat", "access"):
            self.assertNotIn(f_forbidden, f_accessed_attrs)
        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)

    def testLmpLargeZeroEverything(self) -> None:
        """Asserts lmp large request fails closed immediately with zero ID/token/disk side effects."""
        f_run_id_called = 0
        f_token_called = 0
        f_clock_called = 0

        def run_id_gen() -> str:
            nonlocal f_run_id_called
            f_run_id_called += 1
            return "run-test-123"

        def token_gen() -> str:
            nonlocal f_token_called
            f_token_called += 1
            return "lm-0123456789abcdef01234567"

        def clock_gen() -> str:
            nonlocal f_clock_called
            f_clock_called += 1
            return "2026-08-20T12:00:00Z"

        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_run_id_source=run_id_gen,
            f_token_source=token_gen,
            f_clock=clock_gen,
            f_command_runner=self.m_fake_runner,
        )

        with self.assertRaises(PreflightError) as f_ctx:
            f_orch.execute(
                RunRequest("lmp", "large"),
                f_site=self.m_viking_profile,
            )

        self.assertIn("LMP large scale is unsupported", str(f_ctx.exception))
        self.assertEqual(f_run_id_called, 0, "run_id_source must not be called")
        self.assertEqual(f_token_called, 0, "token_source must not be called")
        self.assertEqual(f_clock_called, 0, "clock must not be called")
        self.assertEqual(len(self.m_fake_runner.m_calls), 0, "No scheduler commands should be run")

    def testLocalOneJob(self) -> None:
        """Validates single-job local scale execution."""
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
            f_poll_interval=0.01,
        )

        def on_submit(f_jid: str, f_cwd: Optional[str]) -> None:
            if f_orch.last_evidence_store and f_orch.last_plan:
                self._mockWritePointResults(
                    f_orch.last_evidence_store,
                    f_orch.last_plan.scale_points[0],
                    f_orch.last_plan,
                    f_ordinal=0,
                )

        self.m_fake_runner.m_on_submit_callback = on_submit
        self.m_fake_runner.m_submit_job_ids = ["1001"]

        f_view = f_orch.execute(
            RunRequest("ior", "local"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )

        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
        self.assertEqual(len(f_view.point_states), 1)
        self.assertEqual(f_view.point_states[0].state, PointRunState.SUCCEEDED)
        self.assertEqual(f_view.point_states[0].handle, JobHandle("slurm", "1001"))
        self.assertTrue(f_view.has_success_marker)

        # Verify artifacts and evidence on disk
        f_layout = f_orch.last_artifact_store.layout
        self.assertTrue(os.path.exists(f_layout.manifestPath))
        self.assertTrue(
            os.path.exists(
                os.path.join(
                    f_layout.pointSchedulerDir(f_orch.last_plan.scale_points[0], 0),
                    "submission_recorded.json",
                )
            )
        )
        self.assertTrue(
            os.path.exists(f_layout.controlEventPath("control", 1)),
            "whole_run_succeeded control event must exist",
        )

    def testSequentialExactHandles(self) -> None:
        """Validates sequential execution preserving exact JobHandle decimal strings."""
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
            f_poll_interval=0.01,
        )

        f_job_ids = ["10001", "10002", "10003", "10004"]
        self.m_fake_runner.m_submit_job_ids = list(f_job_ids)

        def on_submit(f_jid: str, f_cwd: Optional[str]) -> None:
            if f_orch.last_evidence_store and f_orch.last_plan:
                f_idx = f_job_ids.index(f_jid)
                self._mockWritePointResults(
                    f_orch.last_evidence_store,
                    f_orch.last_plan.scale_points[f_idx],
                    f_orch.last_plan,
                    f_ordinal=f_idx,
                )

        self.m_fake_runner.m_on_submit_callback = on_submit

        f_view = f_orch.execute(
            RunRequest("ior", "bake"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )

        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
        self.assertEqual(len(f_view.point_states), 4)

        for f_idx, f_expected_id in enumerate(f_job_ids):
            f_pt_view = f_view.point_states[f_idx]
            self.assertEqual(f_pt_view.state, PointRunState.SUCCEEDED)
            self.assertEqual(f_pt_view.handle.job_id, f_expected_id)

    def testDispatchCrashRecoveryOutcomesNoDuplicate(self) -> None:
        """Validates crash recovery during dispatch window without duplicate submissions."""
        # ---------------------------------------------------------------------
        # Scenario A: Dispatched exists, exactly 1 recovery candidate found -> recovers handle without duplicate submit
        # ---------------------------------------------------------------------
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
            f_poll_interval=0.01,
        )

        f_plan = RunPlanner.createPlan(
            RunRequest("ior", "local"),
            self.m_viking_profile,
        )
        f_store = ArtifactStore(self.m_viking_profile.benchmark_roots["hdd"], f_plan.run_id)
        f_store.allocateRun(f_plan)
        f_store.preparePoint(f_plan.scale_points[0], f_plan.combinations, f_ordinal=0)
        f_ev_store = EvidenceStore(f_store.layout, f_plan)
        f_ev_store.recordSubmissionRequested(f_plan.scale_points[0], "control", f_ordinal=0)
        f_ev_store.recordSubmissionDispatched(f_plan.scale_points[0], "control", f_ordinal=0)

        f_token = f_plan.tokens[0]
        self.m_fake_runner.m_recovery_candidates[f_token] = ["99991"]

        self._mockWritePointResults(f_ev_store, f_plan.scale_points[0], f_plan, f_ordinal=0)

        f_orch_recovered = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
            f_artifact_store_factory=lambda f_root, f_rid: f_store,
            f_run_id_source=lambda: f_plan.run_id,
            f_token_source=lambda: f_token,
            f_poll_interval=0.01,
        )

        f_submit_calls_before = len([f_c for f_c in self.m_fake_runner.m_calls if f_c[0] == "sbatch"])
        f_view = f_orch_recovered.execute(
            RunRequest("ior", "local"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )
        f_submit_calls_after = len([f_c for f_c in self.m_fake_runner.m_calls if f_c[0] == "sbatch"])

        self.assertEqual(
            f_submit_calls_before,
            f_submit_calls_after,
            "Must NOT submit again during crash recovery",
        )
        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
        self.assertEqual(f_view.point_states[0].handle.job_id, "99991")

        # ---------------------------------------------------------------------
        # Scenario B: Dispatched exists, 0 recovery candidates -> fails closed
        # ---------------------------------------------------------------------
        f_plan_b = RunPlanner.createPlan(RunRequest("ior", "local"), self.m_viking_profile)
        f_store_b = ArtifactStore(self.m_viking_profile.benchmark_roots["hdd"], f_plan_b.run_id)
        f_store_b.allocateRun(f_plan_b)
        f_store_b.preparePoint(f_plan_b.scale_points[0], f_plan_b.combinations, f_ordinal=0)
        f_ev_store_b = EvidenceStore(f_store_b.layout, f_plan_b)
        f_ev_store_b.recordSubmissionRequested(f_plan_b.scale_points[0], "control", f_ordinal=0)
        f_ev_store_b.recordSubmissionDispatched(f_plan_b.scale_points[0], "control", f_ordinal=0)

        self.m_fake_runner.m_recovery_candidates[f_plan_b.tokens[0]] = []

        f_orch_b = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
            f_artifact_store_factory=lambda f_root, f_rid: f_store_b,
            f_run_id_source=lambda: f_plan_b.run_id,
            f_token_source=lambda: f_plan_b.tokens[0],
            f_poll_interval=0.01,
        )

        f_view_b = f_orch_b.execute(
            RunRequest("ior", "local"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )
        self.assertNotEqual(f_view_b.state, OverallRunState.SUCCEEDED)

        # ---------------------------------------------------------------------
        # Scenario C: Dispatched exists, >1 recovery candidates -> indeterminate fail closed
        # ---------------------------------------------------------------------
        f_plan_c = RunPlanner.createPlan(RunRequest("ior", "local"), self.m_viking_profile)
        f_store_c = ArtifactStore(self.m_viking_profile.benchmark_roots["hdd"], f_plan_c.run_id)
        f_store_c.allocateRun(f_plan_c)
        f_store_c.preparePoint(f_plan_c.scale_points[0], f_plan_c.combinations, f_ordinal=0)
        f_ev_store_c = EvidenceStore(f_store_c.layout, f_plan_c)
        f_ev_store_c.recordSubmissionRequested(f_plan_c.scale_points[0], "control", f_ordinal=0)
        f_ev_store_c.recordSubmissionDispatched(f_plan_c.scale_points[0], "control", f_ordinal=0)

        self.m_fake_runner.m_recovery_candidates[f_plan_c.tokens[0]] = ["99992", "99993"]

        f_orch_c = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
            f_artifact_store_factory=lambda f_root, f_rid: f_store_c,
            f_run_id_source=lambda: f_plan_c.run_id,
            f_token_source=lambda: f_plan_c.tokens[0],
            f_poll_interval=0.01,
        )

        f_view_c = f_orch_c.execute(
            RunRequest("ior", "local"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )
        self.assertNotEqual(f_view_c.state, OverallRunState.SUCCEEDED)

    def testEveryBoundaryFailure(self) -> None:
        """Tests immediate termination on submit failure, query failure, and job execution failure."""
        # Boundary 1: Submit command failure
        f_runner_submit_fail = FakeSchedulerCommandRunner()
        f_runner_submit_fail.m_submit_fail = True

        f_orch_1 = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_runner_submit_fail,
            f_poll_interval=0.01,
        )

        f_view_1 = f_orch_1.execute(
            RunRequest("ior", "bake"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )
        self.assertNotEqual(f_view_1.state, OverallRunState.SUCCEEDED)
        f_submit_calls = [f_c for f_c in f_runner_submit_fail.m_calls if f_c[0] == "sbatch"]
        self.assertEqual(len(f_submit_calls), 1, "Must not submit point 2 after point 1 submit fails")

        # Boundary 2: Query failure during polling
        f_runner_query_fail = FakeSchedulerCommandRunner()
        f_runner_query_fail.m_query_fail = True

        f_orch_2 = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_runner_query_fail,
            f_poll_interval=0.01,
        )

        f_view_2 = f_orch_2.execute(
            RunRequest("ior", "bake"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )
        self.assertNotEqual(f_view_2.state, OverallRunState.SUCCEEDED)
        f_submit_calls_2 = [f_c for f_c in f_runner_query_fail.m_calls if f_c[0] == "sbatch"]
        self.assertEqual(len(f_submit_calls_2), 1, "Must not submit point 2 after query failure on point 1")

        # Boundary 3: Job execution failure (sacct reports FAILED)
        f_runner_job_fail = FakeSchedulerCommandRunner()
        f_runner_job_fail.m_job_fail = True

        f_orch_3 = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_runner_job_fail,
            f_poll_interval=0.01,
        )

        f_view_3 = f_orch_3.execute(
            RunRequest("ior", "bake"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )
        self.assertNotEqual(f_view_3.state, OverallRunState.SUCCEEDED)
        self.assertEqual(f_view_3.point_states[0].state, PointRunState.FAILED)
        f_submit_calls_3 = [f_c for f_c in f_runner_job_fail.m_calls if f_c[0] == "sbatch"]
        self.assertEqual(len(f_submit_calls_3), 1, "Must not submit point 2 after point 1 execution fails")

    def testMarkerOnlyAfterComplete(self) -> None:
        """Asserts WHOLE_RUN_SUCCEEDED is recorded ONLY after all points complete successfully."""
        f_runner = FakeSchedulerCommandRunner()
        f_runner.m_submit_job_ids = ["3001", "3002"]

        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_runner,
            f_poll_interval=0.01,
        )

        def on_submit(f_jid: str, f_cwd: Optional[str]) -> None:
            if f_orch.last_evidence_store and f_orch.last_plan:
                if f_jid == "3001":
                    self._mockWritePointResults(
                        f_orch.last_evidence_store,
                        f_orch.last_plan.scale_points[0],
                        f_orch.last_plan,
                        f_ordinal=0,
                        f_failed=False,
                    )
                elif f_jid == "3002":
                    self._mockWritePointResults(
                        f_orch.last_evidence_store,
                        f_orch.last_plan.scale_points[1],
                        f_orch.last_plan,
                        f_ordinal=1,
                        f_failed=True,
                    )

        f_runner.m_on_submit_callback = on_submit

        f_view = f_orch.execute(
            RunRequest("ior", "bake"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )

        self.assertFalse(f_view.has_success_marker)
        self.assertNotEqual(f_view.state, OverallRunState.SUCCEEDED)
        f_ctrl_events = f_orch.last_evidence_store.readControlEvents("control")
        f_success_markers = [
            f_e for f_e in f_ctrl_events if f_e.evidence_kind == EvidenceKind.WHOLE_RUN_SUCCEEDED
        ]
        self.assertEqual(len(f_success_markers), 0)

    def testMarkerFailure(self) -> None:
        """Asserts marker write failure prevents overall success."""
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
            f_poll_interval=0.01,
        )

        def on_submit(f_jid: str, f_cwd: Optional[str]) -> None:
            if f_orch.last_evidence_store and f_orch.last_plan:
                self._mockWritePointResults(
                    f_orch.last_evidence_store,
                    f_orch.last_plan.scale_points[0],
                    f_orch.last_plan,
                    f_ordinal=0,
                )

                def failing_marker(*args: Any, **kwargs: Any) -> Any:
                    raise OSError("Simulated disk error writing success marker")

                f_orch.last_evidence_store.recordWholeRunSucceeded = failing_marker

        self.m_fake_runner.m_on_submit_callback = on_submit
        self.m_fake_runner.m_submit_job_ids = ["1001"]

        f_view = f_orch.execute(
            RunRequest("ior", "local"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )

        self.assertFalse(f_view.has_success_marker)
        self.assertNotEqual(f_view.state, OverallRunState.SUCCEEDED)

    def testControlExclusion(self) -> None:
        """Asserts concurrent orchestrator attempts are blocked by ControlLock."""
        f_plan = RunPlanner.createPlan(
            RunRequest("ior", "local"),
            self.m_viking_profile,
        )
        f_store = ArtifactStore(self.m_viking_profile.benchmark_roots["hdd"], f_plan.run_id)

        f_lock_1 = f_store.getControlLock()
        f_lock_1.acquire(f_blocking=False)
        self.assertTrue(f_lock_1.is_locked)

        try:
            f_orch_2 = RunOrchestrator(
                f_profile_resolver=self.m_registry,
                f_command_runner=self.m_fake_runner,
                f_artifact_store_factory=lambda f_root, f_rid: f_store,
                f_run_id_source=lambda: f_plan.run_id,
            )

            with self.assertRaises(OrchestrationError) as f_ctx:
                f_orch_2.execute(
                    RunRequest("ior", "local"),
                    f_site=self.m_viking_profile,
                    f_worker_executable=self.m_worker_path,
                )
            self.assertIn("lock contention", str(f_ctx.exception).lower())
        finally:
            f_lock_1.release()

    def testReportsIdsRootState(self) -> None:
        """Asserts returned view contains run_id, root, and final reconciled state."""
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
            f_poll_interval=0.01,
        )

        def on_submit(f_jid: str, f_cwd: Optional[str]) -> None:
            if f_orch.last_evidence_store and f_orch.last_plan:
                self._mockWritePointResults(
                    f_orch.last_evidence_store,
                    f_orch.last_plan.scale_points[0],
                    f_orch.last_plan,
                    f_ordinal=0,
                )

        self.m_fake_runner.m_on_submit_callback = on_submit
        self.m_fake_runner.m_submit_job_ids = ["1001"]

        f_view = f_orch.execute(
            RunRequest("ior", "local"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )

        self.assertIsInstance(f_view, RunStateView)
        self.assertTrue(f_view.run_id.startswith("run-"))
        self.assertEqual(f_view.run_id, f_orch.last_plan.run_id)
        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
        self.assertIsNotNone(f_orch.last_run_root)
        self.assertTrue(os.path.exists(f_orch.last_run_root))
        self.assertIn(f_view.run_id, f_orch.last_run_root)
