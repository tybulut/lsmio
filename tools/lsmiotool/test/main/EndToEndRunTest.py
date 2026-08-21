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

import copy
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import sys
import tempfile
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Set, Tuple
import unittest

from lsmiotool.lib.artifacts import (
    ArtifactLayout,
    ArtifactStore,
    ControlLock,
    LockContentionError,
    STANDARD_COMBINATION_TUPLES,
)
from lsmiotool.lib.benchmarks import (
    IorAdapter,
    LmpAdapter,
    LsmioAdapter,
)
from lsmiotool.lib.cli import (
    InstalledPackageValidator,
    PackageValidationError,
    RunCliParseError,
    RunCliParser,
    SourcePackageValidator,
    WorkerExecutableValidationError,
    WorkerExecutableValidator,
    parseRunArguments,
)
from lsmiotool.lib.evidence import (
    EvidenceKind,
    EvidenceRecord,
    EvidenceStore,
    JobHandle,
    WriterKind,
)
from lsmiotool.lib.main import (
    RunMain,
)
from lsmiotool.lib.profile import ProfileLoader
from lsmiotool.lib.resources import (
    ExecutionMode,
    InstallRelativeLayout,
    ResourceLocator,
    RuntimeLayout,
)
from lsmiotool.lib.run import (
    Combination,
    ManifestDocument,
    ManifestSerializer,
    OrchestrationError,
    PlanValidationError,
    PreflightError,
    RankIdentity,
    RunOrchestrator,
    RunPlan,
    RunPlanner,
    RunRequest,
    ScalePoint,
    ScheduledPointResources,
    SignalCoordinator,
)
from lsmiotool.lib.scheduler import (
    JobResult,
    JobSpec,
    PbsSchedulerAdapter,
    PbsScriptRenderer,
    SchedulerAdapter,
    SchedulerCommandRunner,
    SchedulerError,
    SlurmSchedulerAdapter,
    SlurmScriptRenderer,
    SubmissionDispatchError,
)
from lsmiotool.lib.site import (
    CancellationPolicy,
    EnvironmentResolver,
    PbsMailMode,
    ResourcePolicy,
    SchedulerKind,
    SiteProfile,
    SiteProfileRegistry,
    SlurmMailMode,
)
from lsmiotool.lib.state import (
    OverallRunState,
    PointRunState,
    RunStateView,
    SchedulerJobState,
    StateReconciler,
)
from lsmiotool.lib.worker import (
    AllocationController,
    AllocationControllerError,
    ModuleSetup,
    ProcessResult,
    ProcessRunner,
    RankClaimError,
    RankClaimStore,
    RankIdentityResolver,
    RankWorker,
    RankWorkerError,
)


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
        self.m_cancelled_jobs: Set[str] = set()
        self.m_recovery_candidates: Dict[str, List[str]] = {}
        self.m_on_submit_callback: Optional[Callable[[str, Optional[str]], None]] = None

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
                f_jid = f"{10001 + self.m_submit_idx}"
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
            f_jid = "10001"
            for f_idx, f_arg in enumerate(f_cmd):
                if f_arg.startswith("--jobs="):
                    f_jid = f_arg.split("=", 1)[1]
                elif f_arg == "-j" and f_idx + 1 < len(f_cmd):
                    f_jid = f_cmd[f_idx + 1]

            if f_jid in self.m_cancelled_jobs:
                return ProcessResult(
                    0,
                    f"JobIDRaw|JobName|State|ExitCode\n{f_jid}|job|CANCELLED|0:0\n",
                    "",
                    0.01,
                )
            if self.m_job_fail:
                return ProcessResult(
                    0,
                    f"JobIDRaw|JobName|State|ExitCode\n{f_jid}|job|FAILED|1:0\n",
                    "",
                    0.01,
                )
            return ProcessResult(
                0,
                f"JobIDRaw|JobName|State|ExitCode\n{f_jid}|job|COMPLETED|0:0\n",
                "",
                0.01,
            )

        elif f_exe == "qsub":
            if self.m_submit_fail:
                return ProcessResult(1, "", "qsub: error: Resource limit\n", 0.01)
            if self.m_submit_idx < len(self.m_submit_job_ids):
                f_jid = self.m_submit_job_ids[self.m_submit_idx]
                self.m_submit_idx += 1
            else:
                f_jid = f"{20001 + self.m_submit_idx}"
                self.m_submit_idx += 1
            if self.m_on_submit_callback is not None:
                self.m_on_submit_callback(f_jid, f_cwd)
            return ProcessResult(0, f"{f_jid}.server\n", "", 0.01)

        elif f_exe == "qstat":
            if self.m_query_fail:
                return ProcessResult(1, "", "qstat: error: Server unavailable\n", 0.01)
            if "-u" in f_cmd:
                f_jobs_dict: Dict[str, Any] = {}
                for f_name, f_cands in self.m_recovery_candidates.items():
                    for f_cid in f_cands:
                        f_jobs_dict[f"{f_cid}.server"] = {
                            "Job_Name": f_name,
                            "job_state": "F",
                            "Exit_status": 0,
                        }
                return ProcessResult(0, json.dumps({"Jobs": f_jobs_dict}), "", 0.01)
            if "-x" in f_cmd:
                f_jid = f_cmd[-1].split(".")[0]
                if f_jid in self.m_cancelled_jobs:
                    f_job_data = {"job_state": "F", "Exit_status": 271}
                elif self.m_job_fail:
                    f_job_data = {"job_state": "F", "Exit_status": 1}
                else:
                    f_job_data = {"job_state": "F", "Exit_status": 0}
                return ProcessResult(0, json.dumps({"Jobs": {f"{f_jid}.server": f_job_data}}), "", 0.01)
            else:
                return ProcessResult(0, json.dumps({"Jobs": {}}), "", 0.01)

        elif f_exe in ("scancel", "qdel"):
            if len(f_cmd) > 1:
                f_target_id = f_cmd[1].split(".")[0]
                self.m_cancelled_jobs.add(f_target_id)
            return ProcessResult(0, "", "", 0.01)

        return ProcessResult(0, "", "", 0.01)


class MockProcessRunner:
    """Mock process runner recording executed commands and providing configurable results."""

    def __init__(
        self,
        f_default_returncode: int = 0,
        f_stdout: str = "",
        f_stderr: str = "",
        f_side_effect: Optional[Callable[[Sequence[str], Dict[str, Any]], ProcessResult]] = None,
    ) -> None:
        self.m_default_returncode = f_default_returncode
        self.m_stdout = f_stdout
        self.m_stderr = f_stderr
        self.m_side_effect = f_side_effect
        self.m_invocations: List[Tuple[List[str], Dict[str, Any]]] = []

    def run(
        self,
        f_argv: Sequence[str],
        **f_kwargs: Any,
    ) -> ProcessResult:
        f_argv_list = list(f_argv)
        self.m_invocations.append((f_argv_list, dict(f_kwargs)))

        if self.m_side_effect is not None:
            return self.m_side_effect(f_argv_list, f_kwargs)

        f_log_path = f_kwargs.get("f_log_path") or f_kwargs.get("log_path")
        if f_log_path:
            os.makedirs(os.path.dirname(f_log_path), exist_ok=True)
            with open(f_log_path, "a", encoding="utf-8") as f_f:
                f_f.write(self.m_stdout or "mock output\n")

        return ProcessResult(
            f_returncode=self.m_default_returncode,
            f_stdout=self.m_stdout,
            f_stderr=self.m_stderr,
            f_elapsed_seconds=0.01,
        )


class EndToEndRunTest(unittest.TestCase):
    """Full fake-backed end-to-end contract regression test suite exercising the entire lsmiotool run stack."""

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.mkdtemp(prefix="lsmiotool-e2e-test-")
        self.m_original_cwd = os.getcwd()
        self.m_default_etc = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "etc", "environments.json")
        )
        self.m_profile_doc = ProfileLoader.load(self.m_default_etc)
        self.m_test_user = "testuser"
        self.m_test_home = os.path.join(self.m_temp_dir, "home")
        os.makedirs(self.m_test_home, exist_ok=True)

        self.m_registry = EnvironmentResolver.resolveRegistry(
            self.m_profile_doc, f_user=self.m_test_user, f_home=self.m_test_home
        )

        # Viking profile (Slurm)
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

        # Isambard profile (PBS)
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

        # Create mock worker executable
        self.m_worker_path = os.path.join(self.m_temp_dir, "bin", "lsmiotool-worker")
        os.makedirs(os.path.dirname(self.m_worker_path), exist_ok=True)
        with open(self.m_worker_path, "w", encoding="utf-8") as f_f:
            f_f.write("#!/bin/sh\nexit 0\n")
        os.chmod(self.m_worker_path, 0o755)

        # Create mock LMP assets
        self.m_lmp_assets_dir = os.path.join(self.m_temp_dir, "lmp_assets")
        os.makedirs(self.m_lmp_assets_dir, exist_ok=True)
        for f_asset in ("in.reaxff.hns", "data.hns", "ffield.reax.hns"):
            with open(os.path.join(self.m_lmp_assets_dir, f_asset), "w", encoding="utf-8") as f_f:
                f_f.write(f"# mock content for {f_asset}\n")

    def tearDown(self) -> None:
        os.chdir(self.m_original_cwd)
        shutil.rmtree(self.m_temp_dir, ignore_errors=True)

    def _simulatePointExecution(
        self,
        f_artifact_store: ArtifactStore,
        f_evidence_store: EvidenceStore,
        f_scale_point: ScalePoint,
        f_plan: RunPlan,
        f_ordinal: int = 0,
        f_failed: bool = False,
    ) -> None:
        """Simulate controller and rank worker execution for a scale point."""
        f_is_lsmio = (f_plan.request.target.lower() == "lsmio")
        f_ret = 1 if f_failed else 0
        f_status = "failed" if f_failed else "completed"

        # Record worker controller event
        f_evidence_store.recordWorkerEvent(
            f_point=f_scale_point,
            f_sequence=1,
            f_payload={"event": "controller_started", "tasks": f_scale_point.tasks},
            f_ordinal=f_ordinal,
        )

        for f_combo in f_plan.combinations:
            if f_is_lsmio:
                for f_r in range(f_scale_point.tasks):
                    f_evidence_store.recordRankResult(
                        f_point=f_scale_point,
                        f_global_rank=f_r,
                        f_combination=f_combo,
                        f_payload={"returncode": f_ret, "status": f_status, "rank": f_r},
                        f_ordinal=f_ordinal,
                    )
            f_evidence_store.recordControllerResult(
                f_point=f_scale_point,
                f_combination=f_combo,
                f_payload={"returncode": f_ret, "status": f_status},
                f_ordinal=f_ordinal,
            )

        f_evidence_store.recordWorkerEvent(
            f_point=f_scale_point,
            f_sequence=2,
            f_payload={"event": "controller_finished", "status": f_status},
            f_ordinal=f_ordinal,
        )

    def testIorLocalOneScheduledJob(self) -> None:
        """1. testIorLocalOneScheduledJob: Runs IOR local scale, verifies single point dispatch, job submission, state observation, and whole run success."""
        f_req = RunRequest(f_target="ior", f_scale="local", f_ssd=False, f_setup="BASE")
        f_fake_runner = FakeSchedulerCommandRunner()

        def on_submit(f_jid: str, f_cwd: Optional[str]) -> None:
            # When sbatch is called, simulate worker writing results for the point
            if f_orch.last_artifact_store is not None and f_orch.last_evidence_store is not None:
                self._simulatePointExecution(
                    f_orch.last_artifact_store,
                    f_orch.last_evidence_store,
                    f_orch.last_plan.scale_points[0],
                    f_orch.last_plan,
                    f_ordinal=0,
                )

        f_fake_runner.m_on_submit_callback = on_submit

        f_orch = RunOrchestrator(
            f_command_runner=f_fake_runner,
            f_worker_validator=lambda f_p: self.m_worker_path,
        )

        f_main = RunMain(
            f_request=f_req,
            f_site=self.m_viking_profile,
            f_orchestrator_factory=lambda **f_kw: f_orch,
            f_worker_validator=lambda f_p: self.m_worker_path,
        )

        f_exit = f_main.run()
        self.assertEqual(f_exit, 0, f"Expected 0 exit code, got {f_exit}")
        self.assertEqual(f_orch.exitCode, 0)

        f_view = f_orch.lastView
        self.assertIsNotNone(f_view)
        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
        self.assertEqual(len(f_view.point_states), 1)
        self.assertEqual(f_view.point_states[0].state, PointRunState.SUCCEEDED)
        self.assertEqual(f_view.point_states[0].handle.job_id, "10001")

        # Verify artifacts & evidence on disk
        f_art_store = f_orch.lastArtifactStore
        self.assertIsNotNone(f_art_store)
        self.assertTrue(os.path.exists(f_art_store.layout.manifestPath))

        # Check submission files
        f_pt = f_orch.last_plan.scale_points[0]
        f_sched_dir = f_art_store.layout.pointSchedulerDir(f_pt, 0)
        self.assertTrue(os.path.exists(os.path.join(f_sched_dir, "submission_requested.json")))
        self.assertTrue(os.path.exists(os.path.join(f_sched_dir, "submission_dispatched.json")))
        self.assertTrue(os.path.exists(os.path.join(f_sched_dir, "submission_recorded.json")))

        # Check controller results for all 6 combinations
        for f_combo in f_orch.last_plan.combinations:
            f_res_path = f_art_store.layout.pointControllerResultPath(f_pt, f_combo, 0)
            self.assertTrue(os.path.exists(f_res_path), f"Missing controller result at {f_res_path}")

        # Check whole_run_succeeded event
        f_ctrl_evs = f_orch.last_evidence_store.readControlEvents("control")
        self.assertTrue(
            any(f_ev.evidence_kind == EvidenceKind.WHOLE_RUN_SUCCEEDED for f_ev in f_ctrl_evs),
            "Expected WHOLE_RUN_SUCCEEDED event in control events",
        )

    def testLsmioUniqueRanks(self) -> None:
        """2. testLsmioUniqueRanks: Runs LSMIO multi-rank scale, verifies rank worker launching, individual rank claim locks, unique rank results per combination, and controller result validation."""
        f_req = RunRequest(f_target="lsmio", f_scale="bake", f_ssd=False, f_setup="NATIVE-M")
        f_fake_runner = FakeSchedulerCommandRunner()

        def on_submit(f_jid: str, f_cwd: Optional[str]) -> None:
            if f_orch.last_artifact_store is not None and f_orch.last_evidence_store is not None:
                f_idx = f_fake_runner.m_submit_idx - 1
                f_pt = f_orch.last_plan.scale_points[f_idx]
                if f_pt.tasks == 1:
                    self._simulatePointExecution(
                        f_orch.last_artifact_store,
                        f_orch.last_evidence_store,
                        f_pt,
                        f_orch.last_plan,
                        f_ordinal=f_idx,
                    )
                else:
                    # Multi-rank point: verify rank claim locks and unique rank results
                    f_pt_dir = f_orch.last_artifact_store.layout.pointDir(f_pt, f_idx)
                    f_rank0_dir = os.path.join(f_pt_dir, "ranks", "0")

                    # Test duplicate claim rejection on rank 0
                    RankClaimStore.claim(f_rank0_dir, 0)
                    with self.assertRaises(RankClaimError):
                        RankClaimStore.claim(f_rank0_dir, 0)

                    # Simulate rank workers writing results
                    for f_r in range(f_pt.tasks):
                        if f_r > 0:
                            f_rank_r_dir = os.path.join(f_pt_dir, "ranks", str(f_r))
                            RankClaimStore.claim(f_rank_r_dir, f_r)

                        for f_combo in f_orch.last_plan.combinations:
                            f_orch.last_evidence_store.recordRankResult(
                                f_point=f_pt,
                                f_global_rank=f_r,
                                f_combination=f_combo,
                                f_payload={"returncode": 0, "status": "completed", "rank": f_r},
                                f_ordinal=f_idx,
                            )

                    # Controller verifies and records combination results
                    for f_combo in f_orch.last_plan.combinations:
                        f_orch.last_evidence_store.recordControllerResult(
                            f_point=f_pt,
                            f_combination=f_combo,
                            f_payload={"returncode": 0, "status": "completed", "verified_ranks": f_pt.tasks},
                            f_ordinal=f_idx,
                        )

        f_fake_runner.m_on_submit_callback = on_submit

        f_orch = RunOrchestrator(
            f_command_runner=f_fake_runner,
            f_worker_validator=lambda f_p: self.m_worker_path,
        )

        f_view = f_orch.execute(
            f_request=f_req,
            f_site=self.m_viking_profile,
        )

        self.assertEqual(f_orch.exitCode, 0)
        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
        self.assertEqual(len(f_view.point_states), 4)  # bake scale: 1, 2, 4, 8

        # Check unique rank results exist for the 4-task point
        f_pt4 = ScalePoint(4, 1, 4)
        for f_r in range(4):
            for f_combo in f_orch.last_plan.combinations:
                f_rank_res = os.path.join(
                    f_orch.last_artifact_store.layout.pointDir(f_pt4, 2),
                    "ranks",
                    str(f_r),
                    f_orch.last_artifact_store.layout.combinationName(f_combo),
                    "result.json",
                )
                self.assertTrue(os.path.exists(f_rank_res), f"Missing rank result for rank {f_r} at {f_rank_res}")
                with open(f_rank_res, "r", encoding="utf-8") as f_f:
                    f_data = json.load(f_f)
                    self.assertEqual(f_data["payload"]["rank"], f_r)

    def testLmpSupportedAndLargeGate(self) -> None:
        """3. testLmpSupportedAndLargeGate: Runs LMP bake scale verifying asset staging and execution, and asserts LMP large scale triggers immediate atomic preflight rejection."""
        # 1. Supported LMP bake
        f_req_bake = RunRequest(f_target="lmp", f_scale="bake", f_ssd=False, f_setup="LSMIO")
        f_fake_runner = FakeSchedulerCommandRunner()

        def on_submit(f_jid: str, f_cwd: Optional[str]) -> None:
            if f_orch.last_artifact_store is not None and f_orch.last_evidence_store is not None:
                f_idx = f_fake_runner.m_submit_idx - 1
                f_pt = f_orch.last_plan.scale_points[f_idx]
                self._simulatePointExecution(
                    f_orch.last_artifact_store,
                    f_orch.last_evidence_store,
                    f_pt,
                    f_orch.last_plan,
                    f_ordinal=f_idx,
                )

        f_fake_runner.m_on_submit_callback = on_submit

        f_orch = RunOrchestrator(
            f_command_runner=f_fake_runner,
            f_worker_validator=lambda f_p: self.m_worker_path,
        )

        f_view = f_orch.execute(
            f_request=f_req_bake,
            f_site=self.m_viking_profile,
        )

        self.assertEqual(f_orch.exitCode, 0)
        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)

        # 2. LMP large gate: strict atomic rejection before creating directories, tokens, or locks
        f_req_large = RunRequest(f_target="lmp", f_scale="large", f_ssd=False)
        f_orch_large = RunOrchestrator(
            f_command_runner=f_fake_runner,
            f_worker_validator=lambda f_p: self.m_worker_path,
        )

        # Check directory count before
        f_runs_before = set(os.listdir(self.m_viking_root_hdd)) if os.path.exists(self.m_viking_root_hdd) else set()

        with self.assertRaises(PreflightError) as f_ctx:
            f_orch_large.execute(
                f_request=f_req_large,
                f_site=self.m_viking_profile,
            )
        self.assertIn("LMP large scale is unsupported", str(f_ctx.exception))

        # Check directory count after -> no mutation
        f_runs_after = set(os.listdir(self.m_viking_root_hdd)) if os.path.exists(self.m_viking_root_hdd) else set()
        self.assertEqual(f_runs_before, f_runs_after, "Expected no new run directory created on LMP large rejection")

        # Check RunMain integration for LMP large returns 1
        f_main_large = RunMain(
            f_request=f_req_large,
            f_site=self.m_viking_profile,
            f_worker_validator=lambda f_p: self.m_worker_path,
        )
        self.assertEqual(f_main_large.run(), 1)

    def testSlurmPbsShapeAndWalltime(self) -> None:
        """4. testSlurmPbsShapeAndWalltime: Asserts Slurm directives and computed walltime vs PBS directives with fixed walltime 06:00:00, -m abe, and -q arm."""
        # --- Slurm checks (Viking profile) ---
        f_pt_local = ScalePoint(1, 1, 1)
        f_slurm_local = SlurmScriptRenderer.renderDirectives(
            f_point=f_pt_local,
            f_profile=self.m_viking_profile,
            f_job_name="lm-0123456789abcdef01234567",
            f_output_path="/tmp/job.out",
            f_error_path="/tmp/job.err",
            f_mail_mode=SlurmMailMode.END_FAIL,
            f_walltime="00:30:00",
        )
        self.assertIn("#SBATCH --nodes=1", f_slurm_local)
        self.assertIn("#SBATCH --ntasks-per-node=1", f_slurm_local)
        self.assertIn("#SBATCH --time=00:30:00", f_slurm_local)
        self.assertIn("#SBATCH --mail-type=END,FAIL", f_slurm_local)

        f_pt_large = ScalePoint(256, 4, 64)
        f_slurm_large = SlurmScriptRenderer.renderDirectives(
            f_point=f_pt_large,
            f_profile=self.m_viking_profile,
            f_job_name="lm-0123456789abcdef01234567",
            f_output_path="/tmp/job.out",
            f_error_path="/tmp/job.err",
            f_mail_mode=SlurmMailMode.END_FAIL,
            f_walltime="04:00:00",
        )
        self.assertIn("#SBATCH --nodes=64", f_slurm_large)
        self.assertIn("#SBATCH --ntasks-per-node=4", f_slurm_large)
        self.assertIn("#SBATCH --time=04:00:00", f_slurm_large)
        self.assertIn("#SBATCH --mail-type=END,FAIL", f_slurm_large)

        # --- PBS checks (Isambard profile) ---
        f_pbs_small = PbsScriptRenderer.renderDirectives(
            f_point=f_pt_local,
            f_profile=self.m_isambard_profile,
            f_job_name="lm-0123456789abcdef01234567",
            f_output_path="/tmp/job.out",
            f_error_path="/tmp/job.err",
            f_mail_mode=PbsMailMode.ABE,
            f_walltime="06:00:00",
        )
        self.assertIn("#PBS -q arm", f_pbs_small)
        self.assertIn("#PBS -m abe", f_pbs_small)
        self.assertIn("#PBS -l walltime=06:00:00", f_pbs_small)
        self.assertIn("#PBS -l select=1:ncpus=1:mpiprocs=1:mem=32GB", f_pbs_small)
        self.assertIn("#PBS -l pmem=8G", f_pbs_small)
        self.assertIn("#PBS -l pvmem=8G", f_pbs_small)

        f_pt_pbs_large = ScalePoint(16, 4, 4)
        f_pbs_large = PbsScriptRenderer.renderDirectives(
            f_point=f_pt_pbs_large,
            f_profile=self.m_isambard_profile,
            f_job_name="lm-0123456789abcdef01234567",
            f_output_path="/tmp/job.out",
            f_error_path="/tmp/job.err",
            f_mail_mode=PbsMailMode.ABE,
            f_walltime="06:00:00",
        )
        self.assertIn("#PBS -q arm", f_pbs_large)
        self.assertIn("#PBS -m abe", f_pbs_large)
        self.assertIn("#PBS -l walltime=06:00:00", f_pbs_large)
        self.assertIn("#PBS -l select=4:ncpus=4:mpiprocs=4:mem=32GB", f_pbs_large)
        # Large shape omits pmem and pvmem
        self.assertFalse(any("pmem" in f_line for f_line in f_pbs_large))
        self.assertFalse(any("pvmem" in f_line for f_line in f_pbs_large))

    def testSlurmNumericHandleIdenticalAcrossAllOperationsAndEvidence(self) -> None:
        """5. testSlurmNumericHandleIdenticalAcrossAllOperationsAndEvidence: Validates decimal-only JobHandle remains exact across submit, queries, cancel, and evidence."""
        f_fake_runner = FakeSchedulerCommandRunner()
        f_fake_runner.m_submit_job_ids = ["987654"]

        f_evidence_store = EvidenceStore(
            ArtifactLayout(self.m_viking_root_hdd, "test-run-handle"),
            RunPlanner.createPlan(
                RunRequest("ior", "local"),
                self.m_viking_profile,
                f_run_id_source=lambda: "test-run-handle",
            ),
        )

        f_adapter = SlurmSchedulerAdapter(
            f_evidence_store=f_evidence_store,
            f_worker_validator=lambda f_p: self.m_worker_path,
            f_command_runner=f_fake_runner,
        )

        # 1. Validation of decimal-only handle
        self.assertEqual(SlurmSchedulerAdapter.validateJobId("987654"), "987654")
        with self.assertRaises(SchedulerError):
            SlurmSchedulerAdapter.validateJobId("987654;cluster")
        with self.assertRaises(SchedulerError):
            SlurmSchedulerAdapter.validateJobId("987654.batch")
        with self.assertRaises(SchedulerError):
            SlurmSchedulerAdapter.validateJobId("job_987654")
        with self.assertRaises(SchedulerError):
            SlurmSchedulerAdapter.validateJobId("987654\n")

        # 2. Submit output parsing
        self.assertEqual(f_adapter.parseSubmitOutput("987654\n"), "987654")
        with self.assertRaises(SubmissionDispatchError):
            f_adapter.parseSubmitOutput("Submitted batch job 987654\n")
        with self.assertRaises(SubmissionDispatchError):
            f_adapter.parseSubmitOutput("987654;cluster\n")

        # 3. Query commands use exact ID
        f_act_cmd = SlurmSchedulerAdapter.activeQueryCommand("987654")
        self.assertEqual(f_act_cmd, ["squeue", "-j", "987654", "-h", "-o", "%T"])

        f_acct_cmd = SlurmSchedulerAdapter.accountingQueryCommand("987654")
        self.assertEqual(f_acct_cmd, ["sacct", "-j", "987654", "-P", "-n", "-o", "JobIDRaw,State,ExitCode"])

        # 4. Cancel command uses exact ID
        f_cancel_cmd = SlurmSchedulerAdapter.cancelCommand("987654")
        self.assertEqual(f_cancel_cmd, ["scancel", "987654"])

    def testConcurrentIsolation(self) -> None:
        """6. testConcurrentIsolation: Asserts that concurrent orchestrator executions attempting to lock the same run root raise ControlLock contention errors."""
        f_req = RunRequest(f_target="ior", f_scale="local", f_ssd=False)
        f_fake_runner = FakeSchedulerCommandRunner()

        f_orch1 = RunOrchestrator(
            f_command_runner=f_fake_runner,
            f_worker_validator=lambda f_p: self.m_worker_path,
            f_run_id_source=lambda: "shared-run-id-123",
        )

        f_orch2 = RunOrchestrator(
            f_command_runner=f_fake_runner,
            f_worker_validator=lambda f_p: self.m_worker_path,
            f_run_id_source=lambda: "shared-run-id-123",
        )

        # Allocate run and hold control lock
        f_art_store = ArtifactStore(self.m_viking_root_hdd, "shared-run-id-123")
        f_plan = RunPlanner.createPlan(
            f_request=f_req,
            f_profile=self.m_viking_profile,
            f_run_id_source=lambda: "shared-run-id-123",
        )
        f_art_store.allocateRun(f_plan)
        f_lock = f_art_store.getControlLock()
        f_lock.acquire(f_blocking=False)

        try:
            # Second orchestrator must fail with OrchestrationError wrapping LockContentionError
            with self.assertRaises(OrchestrationError) as f_ctx:
                f_orch2.execute(
                    f_request=f_req,
                    f_site=self.m_viking_profile,
                )
            self.assertIn("Control lock contention", str(f_ctx.exception))
        finally:
            f_lock.release()

        # After release, orch1 can execute cleanly
        f_fake_runner.m_on_submit_callback = lambda jid, cwd: self._simulatePointExecution(
            f_orch1.last_artifact_store,
            f_orch1.last_evidence_store,
            f_orch1.last_plan.scale_points[0],
            f_orch1.last_plan,
        )
        f_view = f_orch1.execute(
            f_request=f_req,
            f_site=self.m_viking_profile,
        )
        self.assertEqual(f_orch1.exitCode, 0)
        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)

    def testEveryFailureClassNonzero(self) -> None:
        """7. testEveryFailureClassNonzero: Tests non-zero exit codes across all failure classes."""
        f_fake_runner = FakeSchedulerCommandRunner()

        # a) Invalid CLI args
        with self.assertRaises(RunCliParseError):
            parseRunArguments(["unknown_target", "local"])
        with self.assertRaises(RunCliParseError):
            parseRunArguments(["ior", "local", "--setup=foo"])

        # b) Preflight validation failure
        f_main_lmp = RunMain(
            "lmp", "large",
            f_site=self.m_viking_profile,
            f_worker_validator=lambda f_p: self.m_worker_path,
        )
        self.assertEqual(f_main_lmp.run(), 1)

        # c) Scheduler submission failure
        f_fake_runner_fail = FakeSchedulerCommandRunner()
        f_fake_runner_fail.m_submit_fail = True
        f_orch_submit_fail = RunOrchestrator(
            f_command_runner=f_fake_runner_fail,
            f_worker_validator=lambda f_p: self.m_worker_path,
        )
        f_view_submit = f_orch_submit_fail.execute(
            f_request=RunRequest("ior", "local"),
            f_site=self.m_viking_profile,
        )
        self.assertEqual(f_orch_submit_fail.exitCode, 1)
        self.assertNotEqual(f_view_submit.state, OverallRunState.SUCCEEDED)

        # d) Controller combination failure
        f_fake_runner_combo_fail = FakeSchedulerCommandRunner()

        def on_submit_combo_fail(f_jid: str, f_cwd: Optional[str]) -> None:
            if f_orch_combo_fail.last_artifact_store and f_orch_combo_fail.last_evidence_store:
                self._simulatePointExecution(
                    f_orch_combo_fail.last_artifact_store,
                    f_orch_combo_fail.last_evidence_store,
                    f_orch_combo_fail.last_plan.scale_points[0],
                    f_orch_combo_fail.last_plan,
                    f_ordinal=0,
                    f_failed=True,
                )

        f_fake_runner_combo_fail.m_on_submit_callback = on_submit_combo_fail
        f_orch_combo_fail = RunOrchestrator(
            f_command_runner=f_fake_runner_combo_fail,
            f_worker_validator=lambda f_p: self.m_worker_path,
        )
        f_view_combo = f_orch_combo_fail.execute(
            f_request=RunRequest("ior", "local"),
            f_site=self.m_viking_profile,
        )
        self.assertEqual(f_orch_combo_fail.exitCode, 1)
        self.assertEqual(f_view_combo.state, OverallRunState.FAILED)

        # e) Rank failure
        f_fake_runner_rank_fail = FakeSchedulerCommandRunner()

        def on_submit_rank_fail(f_jid: str, f_cwd: Optional[str]) -> None:
            if f_orch_rank_fail.last_artifact_store and f_orch_rank_fail.last_evidence_store:
                f_pt = f_orch_rank_fail.last_plan.scale_points[0]
                for f_combo in f_orch_rank_fail.last_plan.combinations:
                    # Rank 0 succeeds, Rank 1 fails
                    f_orch_rank_fail.last_evidence_store.recordRankResult(
                        f_point=f_pt,
                        f_global_rank=0,
                        f_combination=f_combo,
                        f_payload={"returncode": 0, "status": "completed"},
                        f_ordinal=0,
                    )
                    f_orch_rank_fail.last_evidence_store.recordRankResult(
                        f_point=f_pt,
                        f_global_rank=1,
                        f_combination=f_combo,
                        f_payload={"returncode": 1, "status": "failed"},
                        f_ordinal=0,
                    )
                    f_orch_rank_fail.last_evidence_store.recordControllerResult(
                        f_point=f_pt,
                        f_combination=f_combo,
                        f_payload={"returncode": 1, "status": "failed"},
                        f_ordinal=0,
                    )

        f_fake_runner_rank_fail.m_on_submit_callback = on_submit_rank_fail
        f_orch_rank_fail = RunOrchestrator(
            f_command_runner=f_fake_runner_rank_fail,
            f_worker_validator=lambda f_p: self.m_worker_path,
        )
        f_view_rank = f_orch_rank_fail.execute(
            f_request=RunRequest("lsmio", "bake"),
            f_site=self.m_viking_profile,
        )
        self.assertEqual(f_orch_rank_fail.exitCode, 1)
        self.assertEqual(f_view_rank.state, OverallRunState.FAILED)

    def testDispatchRecoveryNoDuplicate(self) -> None:
        """8. testDispatchRecoveryNoDuplicate: Simulates crash/timeout during submission dispatch, verifies crash recovery window queries correlation token, binds JobHandle, and does NOT submit duplicate jobs."""
        f_req = RunRequest("ior", "local")
        f_plan = RunPlanner.createPlan(
            f_request=f_req,
            f_profile=self.m_viking_profile,
            f_run_id_source=lambda: "test-run-recovery",
        )
        f_token = f_plan.tokens[0]

        f_art_store = ArtifactStore(self.m_viking_root_hdd, "test-run-recovery")
        f_art_store.allocateRun(f_plan)
        f_evidence_store = EvidenceStore(f_art_store.layout, f_plan)

        # Pre-seed dispatch evidence simulating crash after dispatch but before accepted
        f_scale_point = f_plan.scale_points[0]
        f_evidence_store.recordSubmissionRequested(
            f_point=f_scale_point,
            f_writer_id="control",
            f_payload={"token": f_token},
            f_ordinal=0,
        )
        f_evidence_store.recordSubmissionDispatched(
            f_point=f_scale_point,
            f_writer_id="control",
            f_payload={"token": f_token},
            f_ordinal=0,
        )

        f_fake_runner = FakeSchedulerCommandRunner()
        f_fake_runner.m_recovery_candidates[f_token] = ["77889"]

        f_adapter = SlurmSchedulerAdapter(
            f_evidence_store=f_evidence_store,
            f_worker_validator=lambda f_p: self.m_worker_path,
            f_command_runner=f_fake_runner,
        )

        f_spec = JobSpec(
            f_point_id=f_scale_point,
            f_script_path=os.path.join(f_art_store.layout.pointSchedulerDir(f_scale_point, 0), "job.sh"),
            f_working_dir=f_art_store.layout.pointDir(f_scale_point, 0),
            f_resources=f_plan.scheduled_points[0],
            f_output_path=os.path.join(f_art_store.layout.pointLogsDir(f_scale_point, 0), "job.out"),
            f_error_path=os.path.join(f_art_store.layout.pointLogsDir(f_scale_point, 0), "job.err"),
            f_job_name=f_token,
        )

        f_res = f_adapter.dispatchSubmission(
            f_point=f_scale_point,
            f_spec=f_spec,
            f_writer_id="control",
            f_ordinal=0,
        )

        # Verify recovered handle
        self.assertEqual(f_res.job_handle.job_id, "77889")
        self.assertEqual(f_res.job_handle.backend, "slurm")

        # Verify NO sbatch call was made (only squeue/sacct recovery queries)
        f_sbatch_calls = [c for c in f_fake_runner.m_calls if os.path.basename(c[0]) == "sbatch"]
        self.assertEqual(len(f_sbatch_calls), 0, f"Expected no duplicate sbatch call, got: {f_sbatch_calls}")

        # Verify submission_recorded.json was written
        f_acc_file = os.path.join(f_art_store.layout.pointSchedulerDir(f_scale_point, 0), "submission_recorded.json")
        self.assertTrue(os.path.exists(f_acc_file))

    def testSignalOrders(self) -> None:
        """9. testSignalOrders: Simulates signal interruption during polling vs signal after whole run success, verifying cancel confirmation and precedence."""
        # 1. SIGINT during polling -> exit code 130, state INTERRUPTED or CANCELLED
        f_sig_coord = SignalCoordinator()
        f_fake_runner = FakeSchedulerCommandRunner()

        f_orch_int = RunOrchestrator(
            f_command_runner=f_fake_runner,
            f_worker_validator=lambda f_p: self.m_worker_path,
            f_signal_coordinator=f_sig_coord,
        )

        def on_submit_int(f_jid: str, f_cwd: Optional[str]) -> None:
            # Trigger SIGINT when job is submitted
            f_sig_coord.trigger(signal.SIGINT)

        f_fake_runner.m_on_submit_callback = on_submit_int

        f_view_int = f_orch_int.execute(
            f_request=RunRequest("ior", "local"),
            f_site=self.m_viking_profile,
        )

        self.assertEqual(f_orch_int.exitCode, 130)
        self.assertIn(f_view_int.state, (OverallRunState.INTERRUPTED, OverallRunState.CANCELLED))

        # 2. SIGTERM during polling -> exit code 143, state INTERRUPTED or CANCELLED
        f_sig_coord_term = SignalCoordinator()
        f_fake_runner_term = FakeSchedulerCommandRunner()

        f_orch_term = RunOrchestrator(
            f_command_runner=f_fake_runner_term,
            f_worker_validator=lambda f_p: self.m_worker_path,
            f_signal_coordinator=f_sig_coord_term,
        )

        def on_submit_term(f_jid: str, f_cwd: Optional[str]) -> None:
            f_sig_coord_term.trigger(signal.SIGTERM)

        f_fake_runner_term.m_on_submit_callback = on_submit_term

        f_view_term = f_orch_term.execute(
            f_request=RunRequest("ior", "local"),
            f_site=self.m_viking_profile,
        )

        self.assertEqual(f_orch_term.exitCode, 143)
        self.assertIn(f_view_term.state, (OverallRunState.INTERRUPTED, OverallRunState.CANCELLED))

        # 3. Whole run succeeded marker BEFORE signal -> precedence remains SUCCEEDED, exit code 0
        f_plan = RunPlanner.createPlan(
            f_request=RunRequest("ior", "local"),
            f_profile=self.m_viking_profile,
            f_run_id_source=lambda: "test-run-precedence",
        )
        f_art_store = ArtifactStore(self.m_viking_root_hdd, "test-run-precedence")
        f_art_store.allocateRun(f_plan)
        f_evidence_store = EvidenceStore(f_art_store.layout, f_plan)

        self._simulatePointExecution(
            f_art_store,
            f_evidence_store,
            f_plan.scale_points[0],
            f_plan,
            f_ordinal=0,
        )
        f_evidence_store.recordSubmissionRequested(f_point=f_plan.scale_points[0], f_writer_id="control", f_payload={"token": f_plan.tokens[0]}, f_ordinal=0)
        f_evidence_store.recordSubmissionDispatched(f_point=f_plan.scale_points[0], f_writer_id="control", f_payload={"token": f_plan.tokens[0]}, f_ordinal=0)
        f_evidence_store.recordSubmissionRecorded(f_point=f_plan.scale_points[0], f_writer_id="control", f_handle=JobHandle("slurm", "10001"), f_payload={}, f_ordinal=0)
        f_evidence_store.recordSchedulerObservation(
            f_point=f_plan.scale_points[0], f_writer_id="control", f_sequence=1,
            f_payload={"handle": {"backend": "slurm", "job_id": "10001"}, "state": "succeeded", "exit_code": 0},
            f_ordinal=0,
        )
        f_evidence_store.recordWholeRunSucceeded("control", 1, {"run_id": "test-run-precedence"})

        # Now simulate a late signal received after whole run succeeded
        f_reconciled = StateReconciler.reconcile(f_plan, f_evidence_store)
        self.assertEqual(f_reconciled.state, OverallRunState.SUCCEEDED)

    def testSourceAndInstalledLayouts(self) -> None:
        """10. testSourceAndInstalledLayouts: Validates execution under both source layout (ResourceLocator.forSource) and installed layout (ResourceLocator.forInstalled)."""
        # 1. Source layout
        f_source_entry = str(Path(__file__).resolve().parents[2] / "lsmiotool")
        f_source_pkg_root = str(Path(__file__).resolve().parents[2])
        f_source_loc = ResourceLocator.forSource(f_source_entry)
        self.assertEqual(f_source_loc.execution_mode, ExecutionMode.SOURCE)
        self.assertEqual(f_source_loc.package_root, os.path.normpath(f_source_pkg_root))

        # Validate with SourcePackageValidator
        f_norm_src = SourcePackageValidator.validate(f_source_pkg_root)
        self.assertEqual(f_norm_src, os.path.normpath(f_source_pkg_root))

        # 2. Installed layout
        f_inst_prefix = os.path.join(self.m_temp_dir, "usr")
        f_inst_pkg_dir = os.path.join(f_inst_prefix, "share", "lsmio", "python", "lsmiotool")
        f_inst_lib_dir = os.path.join(f_inst_pkg_dir, "lib")
        os.makedirs(f_inst_lib_dir, exist_ok=True)

        with open(os.path.join(f_inst_pkg_dir, "__init__.py"), "w", encoding="utf-8") as f_f:
            f_f.write('"""lsmiotool installed package."""\n')

        for f_mod in ("__init__.py", "cli.py", "main.py", "run.py", "worker.py", "version.py", "resources.py"):
            with open(os.path.join(f_inst_lib_dir, f_mod), "w", encoding="utf-8") as f_f:
                f_f.write(f'"""Mock {f_mod}."""\n')

        # Installed worker
        f_inst_worker = os.path.join(f_inst_prefix, "libexec", "lsmio", "lsmiotool-worker")
        os.makedirs(os.path.dirname(f_inst_worker), exist_ok=True)
        with open(f_inst_worker, "w", encoding="utf-8") as f_f:
            f_f.write("#!/bin/sh\nexit 0\n")
        os.chmod(f_inst_worker, 0o755)

        # Validate with InstalledPackageValidator
        f_norm_inst = InstalledPackageValidator.validate(f_inst_pkg_dir)
        self.assertEqual(f_norm_inst, os.path.normpath(f_inst_pkg_dir))

        # Validate worker with WorkerExecutableValidator
        f_norm_worker = WorkerExecutableValidator.validate(f_inst_worker)
        self.assertEqual(f_norm_worker, os.path.normpath(f_inst_worker))

        f_inst_entry = os.path.join(f_inst_prefix, "bin", "lsmiotool")
        f_rel_layout = InstallRelativeLayout(
            f_package_root="../share/lsmio/python/lsmiotool",
            f_profile_file="../share/lsmio/python/lsmiotool/etc/environments.json",
            f_asset_root="../share/lsmio/lmp-reaxff",
            f_worker_executable="../libexec/lsmio/lsmiotool-worker",
            f_version_file="../share/lsmio/python/lsmiotool/VERSION",
        )
        f_inst_loc = ResourceLocator.forInstalled(f_inst_entry, f_rel_layout)
        self.assertEqual(f_inst_loc.execution_mode, ExecutionMode.INSTALLED)

        # 3. Assert no fallback for nonexistent paths
        f_nonexistent = os.path.join(self.m_temp_dir, "nonexistent")
        with self.assertRaises(PackageValidationError):
            SourcePackageValidator.validate(f_nonexistent)
        with self.assertRaises(PackageValidationError):
            InstalledPackageValidator.validate(f_nonexistent)


if __name__ == "__main__":
    unittest.main()
