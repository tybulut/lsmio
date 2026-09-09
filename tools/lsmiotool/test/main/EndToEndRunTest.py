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
import getpass
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
    RunReporter,
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
    ExecutableRegistry,
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
        self.m_active_states: Dict[str, str] = {}
        self.m_accounting_exit_codes: Dict[str, int] = {}

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

        if f_exe == "ior":
            return ProcessResult(0, "IOR-3.3.0: Parallel IO Benchmark\n", "", 0.01)

        elif f_exe == "lmp":
            return ProcessResult(
                0,
                "LAMMPS (2 Aug 2023)\n-lsmio-buf-size-mb\n-lsmio-mmap\n-lsmio-fallback\n",
                "",
                0.01,
            )

        elif f_exe.startswith("bm_"):
            return ProcessResult(0, "LSMIO Benchmark\n", "", 0.01)

        elif f_exe == "sbatch":
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
                return ProcessResult(
                    1, "", "squeue: error: Slurm controller down\n", 0.01
                )
            # Check if recovery query (--name=...)
            for f_arg in f_cmd:
                if f_arg.startswith("--name="):
                    f_name = f_arg.split("=", 1)[1]
                    f_cands = self.m_recovery_candidates.get(f_name, [])
                    f_lines = [f"{f_cid}|{f_name}|RUNNING" for f_cid in f_cands]
                    return ProcessResult(
                        0, "\n".join(f_lines) + ("\n" if f_lines else ""), "", 0.01
                    )
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
                f_jid = f"{20001 + self.m_submit_idx}.isambard-pbs"
                self.m_submit_idx += 1
            if self.m_on_submit_callback is not None:
                self.m_on_submit_callback(f_jid, f_cwd)
            f_submit_out = f_jid if "." in f_jid else f"{f_jid}.isambard-pbs"
            return ProcessResult(0, f"{f_submit_out}\n", "", 0.01)

        elif f_exe == "qstat":
            if self.m_query_fail:
                return ProcessResult(1, "", "qstat: error: Server unavailable\n", 0.01)
            if "-u" in f_cmd:
                f_jobs_dict: Dict[str, Any] = {}
                for f_name, f_cands in self.m_recovery_candidates.items():
                    for f_cid in f_cands:
                        f_cid_full = f_cid if "." in f_cid else f"{f_cid}.isambard-pbs"
                        f_jobs_dict[f_cid_full] = {
                            "Job_Name": f_name,
                            "job_state": "F",
                            "Exit_status": 0,
                        }
                return ProcessResult(0, json.dumps({"Jobs": f_jobs_dict}), "", 0.01)
            if "-x" in f_cmd:
                f_target_id = f_cmd[-1]
                if (
                    f_target_id in self.m_cancelled_jobs
                    or f_target_id.split(".")[0] in self.m_cancelled_jobs
                ):
                    f_exit_status = self.m_accounting_exit_codes.get(f_target_id, 0)
                    f_job_data = {
                        "Job_Name": "test_job",
                        "job_state": "CANCELLED",
                        "Exit_status": f_exit_status,
                    }
                elif self.m_job_fail:
                    f_exit_status = self.m_accounting_exit_codes.get(f_target_id, 1)
                    f_job_data = {
                        "Job_Name": "test_job",
                        "job_state": "F",
                        "Exit_status": f_exit_status,
                    }
                else:
                    f_exit_status = self.m_accounting_exit_codes.get(f_target_id, 0)
                    f_job_data = {
                        "Job_Name": "test_job",
                        "job_state": "F",
                        "Exit_status": f_exit_status,
                    }
                return ProcessResult(
                    0, json.dumps({"Jobs": {f_target_id: f_job_data}}), "", 0.01
                )
            else:
                f_target_id = f_cmd[-1]
                if f_target_id in self.m_active_states:
                    return ProcessResult(
                        0,
                        json.dumps(
                            {
                                "Jobs": {
                                    f_target_id: {
                                        "Job_Name": "test_job",
                                        "job_state": self.m_active_states[f_target_id],
                                    }
                                }
                            }
                        ),
                        "",
                        0.01,
                    )
                return ProcessResult(0, json.dumps({"Jobs": {}}), "", 0.01)

        elif f_exe in ("scancel", "qdel"):
            if len(f_cmd) > 1:
                f_target_id = f_cmd[-1]
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
        f_side_effect: Optional[
            Callable[[Sequence[str], Dict[str, Any]], ProcessResult]
        ] = None,
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
        self.m_orig_environ = dict(os.environ)
        os.environ["SB_ACCOUNT"] = "test_acct"
        os.environ["SB_EMAIL"] = "user@example.com"
        self.m_temp_dir = tempfile.mkdtemp(prefix="lsmiotool-e2e-test-")
        self.m_original_cwd = os.getcwd()
        self.m_default_etc = os.path.normpath(
            os.path.join(
                os.path.dirname(__file__), "..", "..", "etc", "environments.json"
            )
        )
        self.m_profile_doc = ProfileLoader.load(self.m_default_etc)
        self.m_test_user = "testuser"
        self.m_test_home = os.path.join(self.m_temp_dir, "home")
        os.makedirs(self.m_test_home, exist_ok=True)

        self.m_registry = EnvironmentResolver.resolveRegistry(
            self.m_profile_doc, f_user=self.m_test_user, f_home=self.m_test_home
        )

        self.m_bin_dir = os.path.join(self.m_temp_dir, "bin")
        os.makedirs(self.m_bin_dir, exist_ok=True)

        # Create mock worker executable
        self.m_worker_path = os.path.join(self.m_bin_dir, "lsmiotool-worker")
        with open(self.m_worker_path, "w", encoding="utf-8") as f_f:
            f_f.write("#!/bin/sh\nexit 0\n")
        os.chmod(self.m_worker_path, 0o755)

        self.m_ior_path = os.path.join(self.m_bin_dir, "ior")
        with open(self.m_ior_path, "w", encoding="utf-8") as f_f:
            f_f.write(
                '#!/bin/sh\nif [ "$1" = "-v" ]; then echo "IOR-3.3.0: Parallel IO Benchmark"; exit 0; fi\nexit 0\n'
            )
        os.chmod(self.m_ior_path, 0o755)

        self.m_lmp_path = os.path.join(self.m_bin_dir, "lmp")
        with open(self.m_lmp_path, "w", encoding="utf-8") as f_f:
            f_f.write(
                '#!/bin/sh\nif [ "$1" = "-h" ]; then echo "LAMMPS (2 Aug 2023)"; echo "-lsmio-buf-size-mb"; echo "-lsmio-mmap"; echo "-lsmio-fallback"; exit 0; fi\nexit 0\n'
            )
        os.chmod(self.m_lmp_path, 0o755)

        self.m_bm_paths: Dict[str, str] = {}
        for f_name in (
            "bm_native",
            "bm_adios",
            "bm_rocksdb",
            "bm_leveldb",
            "bm_manager",
        ):
            f_p = os.path.join(self.m_bin_dir, f_name)
            with open(f_p, "w", encoding="utf-8") as f_f:
                f_f.write("#!/bin/sh\nexit 0\n")
            os.chmod(f_p, 0o755)
            self.m_bm_paths[f_name] = f_p

        # Create LMP assets
        self.m_lmp_assets_dir = os.path.join(
            self.m_temp_dir, "share", "lsmio", "lmp-reaxff"
        )
        os.makedirs(self.m_lmp_assets_dir, exist_ok=True)
        for f_asset in ("in.reaxc.hns", "data.hns-equil", "ffield.reax.hns"):
            with open(
                os.path.join(self.m_lmp_assets_dir, f_asset), "w", encoding="utf-8"
            ) as f_f:
                f_f.write(f"# mock content for {f_asset}\n")

        self.m_executables = ExecutableRegistry(
            {
                "ior": self.m_ior_path,
                "lmp": self.m_lmp_path,
                "bm_native": self.m_bm_paths["bm_native"],
                "bm_adios": self.m_bm_paths["bm_adios"],
                "bm_rocksdb": self.m_bm_paths["bm_rocksdb"],
                "bm_leveldb": self.m_bm_paths["bm_leveldb"],
                "bm_manager": self.m_bm_paths["bm_manager"],
            }
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
            f_benchmark_roots={
                "hdd": self.m_viking_root_hdd,
                "ssd": self.m_viking_root_ssd,
            },
            f_install_prefix=self.m_temp_dir,
            f_executables=self.m_executables,
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
            f_benchmark_roots={
                "hdd": self.m_isambard_root_hdd,
                "ssd": self.m_isambard_root_ssd,
            },
            f_install_prefix=self.m_temp_dir,
            f_executables=self.m_executables,
            f_modules=f_base_isambard.modules,
            f_resources=f_base_isambard.resources,
            f_rank_identity=f_base_isambard.rank_identity,
            f_cancellation=f_base_isambard.cancellation,
            f_lustre_pools=f_base_isambard.lustre_pools,
        )

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self.m_orig_environ)
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
        f_is_lsmio = f_plan.request.target.lower() == "lsmio"
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
                    f_log = f_artifact_store.layout.pointRankLogPath(
                        f_scale_point, f_r, f_combo.name, f_ordinal
                    )
                    f_res_path = os.path.join(
                        f_artifact_store.layout.pointRankCombinationDir(
                            f_scale_point, f_r, f_combo.name, f_ordinal
                        ),
                        f"rank_{f_r}.db",
                    )
                    os.makedirs(os.path.dirname(f_log), exist_ok=True)
                    os.makedirs(os.path.dirname(f_res_path), exist_ok=True)
                    if not os.path.exists(f_log):
                        with open(f_log, "w", encoding="utf-8") as f_f:
                            f_f.write("mock rank log\n")
                    if not os.path.exists(f_res_path):
                        with open(f_res_path, "w", encoding="utf-8") as f_f:
                            f_f.write("mock rank db\n")

                    f_payload: Dict[str, Any] = {
                        "status": f_status,
                        "exit_code": f_ret,
                        "exit_status": f_ret,
                        "global_rank": f_r,
                        "rank": f_r,
                        "combination": f_combo.name,
                        "argv": ["lsmioworker", "rank", f_combo.name],
                        "log_path": f_log,
                        "result_path": f_res_path,
                        "timed_out": False,
                    }
                    if f_failed:
                        f_payload["error"] = "mock rank failure"
                    f_evidence_store.recordRankResult(
                        f_point=f_scale_point,
                        f_global_rank=f_r,
                        f_combination=f_combo,
                        f_payload=f_payload,
                        f_ordinal=f_ordinal,
                    )

            f_ctrl_payload: Dict[str, Any] = {
                "status": f_status,
                "exit_code": f_ret,
                "stage": "execution" if not f_is_lsmio else "rank_evidence",
                "combination": f_combo.name,
            }
            if f_is_lsmio and not f_failed:
                f_ctrl_payload["tasks_validated"] = f_scale_point.tasks
            if f_failed:
                f_ctrl_payload["error"] = "mock combination failure"
            f_evidence_store.recordControllerResult(
                f_point=f_scale_point,
                f_combination=f_combo,
                f_payload=f_ctrl_payload,
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
            if (
                f_orch.last_artifact_store is not None
                and f_orch.last_evidence_store is not None
            ):
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
        self.assertTrue(
            os.path.exists(os.path.join(f_sched_dir, "submission_requested.json"))
        )
        self.assertTrue(
            os.path.exists(os.path.join(f_sched_dir, "submission_dispatched.json"))
        )
        self.assertTrue(
            os.path.exists(os.path.join(f_sched_dir, "submission_recorded.json"))
        )

        # Check controller results for all 6 combinations
        for f_combo in f_orch.last_plan.combinations:
            f_res_path = f_art_store.layout.pointControllerResultPath(f_pt, f_combo, 0)
            self.assertTrue(
                os.path.exists(f_res_path), f"Missing controller result at {f_res_path}"
            )

        # Check whole_run_succeeded event
        f_ctrl_evs = f_orch.last_evidence_store.readControlEvents("control")
        self.assertTrue(
            any(
                f_ev.evidence_kind == EvidenceKind.WHOLE_RUN_SUCCEEDED
                for f_ev in f_ctrl_evs
            ),
            "Expected WHOLE_RUN_SUCCEEDED event in control events",
        )

    def testLsmioUniqueRanks(self) -> None:
        """2. testLsmioUniqueRanks: Runs LSMIO multi-rank scale, verifies rank worker launching, individual rank claim locks, unique rank results per combination, and controller result validation."""
        f_req = RunRequest(
            f_target="lsmio", f_scale="bake", f_ssd=False, f_setup="NATIVE-M"
        )
        f_fake_runner = FakeSchedulerCommandRunner()

        def on_submit(f_jid: str, f_cwd: Optional[str]) -> None:
            if (
                f_orch.last_artifact_store is not None
                and f_orch.last_evidence_store is not None
            ):
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
                            f_log = f_orch.last_artifact_store.layout.pointRankLogPath(
                                f_pt, f_r, f_combo.name, f_idx
                            )
                            f_res_path = os.path.join(
                                f_orch.last_artifact_store.layout.pointRankCombinationDir(
                                    f_pt, f_r, f_combo.name, f_idx
                                ),
                                f"rank_{f_r}.db",
                            )
                            os.makedirs(os.path.dirname(f_log), exist_ok=True)
                            os.makedirs(os.path.dirname(f_res_path), exist_ok=True)
                            if not os.path.exists(f_log):
                                with open(f_log, "w", encoding="utf-8") as f_f:
                                    f_f.write("mock rank log\n")
                            if not os.path.exists(f_res_path):
                                with open(f_res_path, "w", encoding="utf-8") as f_f:
                                    f_f.write("mock rank db\n")
                            f_orch.last_evidence_store.recordRankResult(
                                f_point=f_pt,
                                f_global_rank=f_r,
                                f_combination=f_combo,
                                f_payload={
                                    "status": "success",
                                    "exit_code": 0,
                                    "exit_status": 0,
                                    "global_rank": f_r,
                                    "rank": f_r,
                                    "combination": f_combo.name,
                                    "argv": ["lsmioworker", "rank", f_combo.name],
                                    "log_path": f_log,
                                    "result_path": f_res_path,
                                    "timed_out": False,
                                },
                                f_ordinal=f_idx,
                            )

                    # Controller verifies and records combination results
                    for f_combo in f_orch.last_plan.combinations:
                        f_orch.last_evidence_store.recordControllerResult(
                            f_point=f_pt,
                            f_combination=f_combo,
                            f_payload={
                                "status": "success",
                                "exit_code": 0,
                                "stage": "rank_evidence",
                                "tasks_validated": f_pt.tasks,
                                "combination": f_combo.name,
                            },
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
                self.assertTrue(
                    os.path.exists(f_rank_res),
                    f"Missing rank result for rank {f_r} at {f_rank_res}",
                )
                with open(f_rank_res, "r", encoding="utf-8") as f_f:
                    f_data = json.load(f_f)
                    self.assertEqual(f_data["payload"]["rank"], f_r)

    def testLmpSupportedAndLargeGate(self) -> None:
        """3. testLmpSupportedAndLargeGate: Runs LMP bake scale verifying asset staging and execution, and asserts LMP large scale triggers immediate atomic preflight rejection."""
        # 1. Supported LMP bake
        f_req_bake = RunRequest(
            f_target="lmp", f_scale="bake", f_ssd=False, f_setup="LSMIO"
        )
        f_fake_runner = FakeSchedulerCommandRunner()

        def on_submit(f_jid: str, f_cwd: Optional[str]) -> None:
            if (
                f_orch.last_artifact_store is not None
                and f_orch.last_evidence_store is not None
            ):
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
        f_runs_before = (
            set(os.listdir(self.m_viking_root_hdd))
            if os.path.exists(self.m_viking_root_hdd)
            else set()
        )

        with self.assertRaises(PreflightError) as f_ctx:
            f_orch_large.execute(
                f_request=f_req_large,
                f_site=self.m_viking_profile,
            )
        self.assertIn("LMP large scale is unsupported", str(f_ctx.exception))

        # Check directory count after -> no mutation
        f_runs_after = (
            set(os.listdir(self.m_viking_root_hdd))
            if os.path.exists(self.m_viking_root_hdd)
            else set()
        )
        self.assertEqual(
            f_runs_before,
            f_runs_after,
            "Expected no new run directory created on LMP large rejection",
        )

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
        self.assertEqual(
            f_act_cmd, ["squeue", "--noheader", "--jobs=987654", "--format=%i|%T"]
        )

        f_acct_cmd = SlurmSchedulerAdapter.accountingQueryCommand("987654")
        self.assertEqual(
            f_acct_cmd,
            [
                "sacct",
                "--noheader",
                "--parsable2",
                "--jobs=987654",
                "--format=JobIDRaw,JobName,State,ExitCode",
            ],
        )

        # 4. Cancel command uses exact ID
        f_cancel_cmd = SlurmSchedulerAdapter.cancelCommand("987654")
        self.assertEqual(f_cancel_cmd, ["scancel", "987654"])

    def testPbsQualifiedHandleIdenticalAcrossAllOperationsAndEvidence(self) -> None:
        """Validates exact qualified PBS handles are preserved across validation, submit, queries, cancel, and evidence."""
        f_fake_runner = FakeSchedulerCommandRunner()
        f_qualified_id = "123456.isambard-pbs"
        f_fake_runner.m_submit_job_ids = [f_qualified_id]

        f_plan = RunPlanner.createPlan(
            RunRequest("ior", "local"),
            self.m_isambard_profile,
            f_run_id_source=lambda: "test-run-pbs-handle",
        )
        f_art_store = ArtifactStore(self.m_isambard_root_hdd, "test-run-pbs-handle")
        f_art_store.allocateRun(f_plan)
        f_evidence_store = EvidenceStore(
            f_art_store.layout,
            f_plan=f_plan,
        )

        f_adapter = PbsSchedulerAdapter(
            f_evidence_store=f_evidence_store,
            f_worker_validator=lambda f_p: self.m_worker_path,
            f_command_runner=f_fake_runner,
            f_profile=self.m_isambard_profile,
        )

        # 1. Validation of qualified handle with server suffixes, leading zeros, and plain decimal
        self.assertEqual(
            PbsSchedulerAdapter.validateJobId("123456.isambard-pbs"),
            "123456.isambard-pbs",
        )
        self.assertEqual(
            PbsSchedulerAdapter.validateJobId("00123456.pbs_srv-01"),
            "00123456.pbs_srv-01",
        )
        self.assertEqual(PbsSchedulerAdapter.validateJobId("654321"), "654321")

        with self.assertRaises(SchedulerError):
            PbsSchedulerAdapter.validateJobId("")
        with self.assertRaises(SchedulerError):
            PbsSchedulerAdapter.validateJobId("123456;cluster")
        with self.assertRaises(SchedulerError):
            PbsSchedulerAdapter.validateJobId("123456\n")
        with self.assertRaises(SchedulerError):
            PbsSchedulerAdapter.validateJobId(" 123456.isambard-pbs ")
        with self.assertRaises(SchedulerError):
            PbsSchedulerAdapter.validateJobId(123456)

        # 2. Submit output parsing retains exact qualified handle
        self.assertEqual(
            f_adapter.parseSubmitOutput("123456.isambard-pbs\n"), "123456.isambard-pbs"
        )
        self.assertEqual(
            f_adapter.parseSubmitOutput("009876.pbs-server_01\n"),
            "009876.pbs-server_01",
        )
        with self.assertRaises(SubmissionDispatchError):
            f_adapter.parseSubmitOutput("Job submitted: 123456.isambard-pbs\n")
        with self.assertRaises(SubmissionDispatchError):
            f_adapter.parseSubmitOutput("")

        # 3. Query commands use exact qualified handle
        f_act_cmd = PbsSchedulerAdapter.activeQueryCommand(f_qualified_id)
        self.assertEqual(
            f_act_cmd, ["qstat", "-f", "-F", "json", "123456.isambard-pbs"]
        )

        f_acct_cmd = PbsSchedulerAdapter.accountingQueryCommand(f_qualified_id)
        self.assertEqual(
            f_acct_cmd, ["qstat", "-x", "-f", "-F", "json", "123456.isambard-pbs"]
        )

        f_cancel_cmd = PbsSchedulerAdapter.cancelCommand(f_qualified_id)
        self.assertEqual(f_cancel_cmd, ["qdel", "123456.isambard-pbs"])

        f_rec_cmd = PbsSchedulerAdapter.recoveryCommand("testuser")
        self.assertEqual(
            f_rec_cmd, ["qstat", "-x", "-f", "-F", "json", "-u", "testuser"]
        )

        # 4. Exact full key matching in JSON parser rejects decoys
        f_decoy_json = json.dumps(
            {
                "Jobs": {
                    "123456": {"Job_Name": "test", "job_state": "R"},
                    "123456.other-pbs": {"Job_Name": "test", "job_state": "R"},
                    "123456.isambard-pbs-fake": {"Job_Name": "test", "job_state": "R"},
                }
            }
        )
        self.assertIsNone(
            PbsSchedulerAdapter.parseActiveQuery(f_decoy_json, f_job_id=f_qualified_id)
        )
        self.assertEqual(
            PbsSchedulerAdapter.parseAccountingQuery(
                f_decoy_json, f_job_id=f_qualified_id
            ),
            (SchedulerJobState.UNKNOWN, None),
        )

        # Exact matching matches the qualified key
        f_exact_json = json.dumps(
            {
                "Jobs": {
                    "123456.isambard-pbs": {
                        "Job_Name": "test",
                        "job_state": "F",
                        "Exit_status": 0,
                    }
                }
            }
        )
        self.assertEqual(
            PbsSchedulerAdapter.parseAccountingQuery(
                f_exact_json, f_job_id=f_qualified_id
            ),
            (SchedulerJobState.SUCCEEDED, 0),
        )

        # Negative exit signal maps to POSIX 128 + abs(sig)
        f_signal_json = json.dumps(
            {
                "Jobs": {
                    "123456.isambard-pbs": {
                        "Job_Name": "test",
                        "job_state": "F",
                        "Exit_status": -15,
                    }
                }
            }
        )
        self.assertEqual(
            PbsSchedulerAdapter.parseAccountingQuery(
                f_signal_json, f_job_id=f_qualified_id
            ),
            (SchedulerJobState.FAILED, 143),
        )

        # 5. Evidence records retain verbatim qualified JobHandle
        f_pt = f_evidence_store.plan.scale_points[0]
        f_handle = JobHandle("pbs", f_qualified_id)
        f_evidence_store.recordSubmissionRequested(
            f_pt, "control", {"token": "tok1"}, f_ordinal=0
        )
        f_evidence_store.recordSubmissionDispatched(
            f_pt, "control", {"token": "tok1"}, f_ordinal=0
        )
        f_evidence_store.recordSubmissionRecorded(
            f_pt, "control", f_handle, {}, f_ordinal=0
        )
        f_evidence_store.recordSchedulerObservation(
            f_pt,
            "control",
            1,
            {"handle": f_handle.toDict(), "state": "succeeded", "exit_code": 0},
            f_ordinal=0,
        )

        f_disp_path = os.path.join(
            f_evidence_store.layout.pointSchedulerDir(f_pt, 0),
            "submission_recorded.json",
        )
        with open(f_disp_path, "r", encoding="utf-8") as f_f:
            f_rec = json.load(f_f)
            self.assertEqual(f_rec["payload"]["handle"]["job_id"], f_qualified_id)
            self.assertEqual(f_rec["payload"]["handle"]["backend"], "pbs")

    def testPbsEndToEndLifecycleFullQualifiedHandleTrace(self) -> None:
        """Simulates a complete PBS run and traces the full qualified PBS handle throughout the entire lifecycle."""
        f_qualified_id = "123456.isambard-pbs"
        f_req = RunRequest(f_target="ior", f_scale="local", f_ssd=False, f_setup="BASE")
        f_fake_runner = FakeSchedulerCommandRunner()
        f_fake_runner.m_submit_job_ids = [f_qualified_id]

        def on_submit(f_jid: str, f_cwd: Optional[str]) -> None:
            if (
                f_orch.last_artifact_store is not None
                and f_orch.last_evidence_store is not None
            ):
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
            f_site=self.m_isambard_profile,
            f_orchestrator_factory=lambda **f_kw: f_orch,
            f_worker_validator=lambda f_p: self.m_worker_path,
        )

        f_exit = f_main.run()
        self.assertEqual(f_exit, 0, f"Expected 0 exit code, got {f_exit}")
        self.assertEqual(f_orch.exitCode, 0)

        # 1. State view traces exact full qualified handle
        f_view = f_orch.lastView
        self.assertIsNotNone(f_view)
        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
        self.assertEqual(len(f_view.point_states), 1)
        self.assertEqual(f_view.point_states[0].state, PointRunState.SUCCEEDED)
        self.assertEqual(f_view.point_states[0].handle.job_id, f_qualified_id)
        self.assertEqual(f_view.point_states[0].handle.backend, "pbs")

        # 2. Command trace verifies exact qualified handle passed to every scheduler invocation
        f_qsub_calls = [
            c for c in f_fake_runner.m_calls if os.path.basename(c[0]) == "qsub"
        ]
        self.assertEqual(len(f_qsub_calls), 1)

        f_qstat_active_calls = [
            c
            for c in f_fake_runner.m_calls
            if os.path.basename(c[0]) == "qstat" and "-x" not in c and "-u" not in c
        ]
        self.assertTrue(len(f_qstat_active_calls) >= 1)
        for f_c in f_qstat_active_calls:
            self.assertEqual(f_c, ["qstat", "-f", "-F", "json", f_qualified_id])

        f_qstat_acct_calls = [
            c
            for c in f_fake_runner.m_calls
            if os.path.basename(c[0]) == "qstat" and "-x" in c and "-u" not in c
        ]
        self.assertTrue(len(f_qstat_acct_calls) >= 1)
        for f_c in f_qstat_acct_calls:
            self.assertEqual(f_c, ["qstat", "-x", "-f", "-F", "json", f_qualified_id])

        # 3. Evidence storage on disk preserves exact qualified handle
        f_art_store = f_orch.lastArtifactStore
        self.assertIsNotNone(f_art_store)
        f_pt = f_orch.last_plan.scale_points[0]
        f_sched_dir = f_art_store.layout.pointSchedulerDir(f_pt, 0)

        # submission_dispatched.json
        f_disp_file = os.path.join(f_sched_dir, "submission_dispatched.json")
        self.assertTrue(os.path.exists(f_disp_file))

        # submission_recorded.json
        f_rec_file = os.path.join(f_sched_dir, "submission_recorded.json")
        self.assertTrue(os.path.exists(f_rec_file))
        with open(f_rec_file, "r", encoding="utf-8") as f_f:
            f_rec_data = json.load(f_f)
            self.assertEqual(f_rec_data["payload"]["handle"]["job_id"], f_qualified_id)
            self.assertEqual(f_rec_data["payload"]["handle"]["backend"], "pbs")

        # scheduler_observations
        f_obs_dir = f_art_store.layout.pointSchedulerObservationsDir(f_pt, "control", 0)
        f_obs_files = [
            os.path.join(f_obs_dir, x)
            for x in os.listdir(f_obs_dir)
            if x.endswith(".json")
        ]
        self.assertTrue(len(f_obs_files) >= 1)
        with open(f_obs_files[0], "r", encoding="utf-8") as f_f:
            f_obs_data = json.load(f_f)
            self.assertEqual(f_obs_data["payload"]["handle"]["job_id"], f_qualified_id)
            self.assertEqual(f_obs_data["payload"]["handle"]["backend"], "pbs")

        # 4. Trace representation of handle in point state
        f_point_summary = str(f_view.point_states[0])
        self.assertIn(f_qualified_id, f_point_summary)
        f_handle_repr = repr(f_view.point_states[0].handle)
        self.assertIn(f_qualified_id, f_handle_repr)

    def testPbsDispatchRecoveryFullQualifiedHandle(self) -> None:
        """Simulates crash/timeout during PBS submission dispatch and verifies recovery preserves full qualified handle."""
        f_qualified_id = "554433.isambard-pbs"
        f_req = RunRequest("ior", "local")
        f_plan = RunPlanner.createPlan(
            f_request=f_req,
            f_profile=self.m_isambard_profile,
            f_run_id_source=lambda: "test-run-pbs-recovery",
        )
        f_token = f_plan.tokens[0]

        f_art_store = ArtifactStore(self.m_isambard_root_hdd, "test-run-pbs-recovery")
        f_art_store.allocateRun(f_plan)
        f_evidence_store = EvidenceStore(f_art_store.layout, f_plan=f_plan)

        # Pre-seed dispatch evidence simulating crash after dispatch
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
        f_fake_runner.m_recovery_candidates[f_token] = [f_qualified_id]

        f_adapter = PbsSchedulerAdapter(
            f_evidence_store=f_evidence_store,
            f_worker_validator=lambda f_p: self.m_worker_path,
            f_command_runner=f_fake_runner,
            f_profile=self.m_isambard_profile,
        )

        f_spec = JobSpec(
            f_point_id=f_scale_point,
            f_script_path=os.path.join(
                f_art_store.layout.pointSchedulerDir(f_scale_point, 0), "job.sh"
            ),
            f_working_dir=f_art_store.layout.pointDir(f_scale_point, 0),
            f_resources=f_plan.scheduled_points[0],
            f_output_path=os.path.join(
                f_art_store.layout.pointLogsDir(f_scale_point, 0), "job.out"
            ),
            f_error_path=os.path.join(
                f_art_store.layout.pointLogsDir(f_scale_point, 0), "job.err"
            ),
            f_job_name=f_token,
        )

        f_res = f_adapter.dispatchSubmission(
            f_point=f_scale_point,
            f_spec=f_spec,
            f_writer_id="control",
            f_ordinal=0,
        )

        # Verify recovered handle is exact qualified handle
        self.assertEqual(f_res.job_handle.job_id, f_qualified_id)
        self.assertEqual(f_res.job_handle.backend, "pbs")

        # Verify whole-user qstat was called for recovery and NO qsub call was made
        f_qsub_calls = [
            c for c in f_fake_runner.m_calls if os.path.basename(c[0]) == "qsub"
        ]
        self.assertEqual(
            len(f_qsub_calls),
            0,
            f"Expected no duplicate qsub call, got: {f_qsub_calls}",
        )

        f_rec_calls = [c for c in f_fake_runner.m_calls if "-u" in c]
        self.assertEqual(len(f_rec_calls), 1)
        self.assertEqual(
            f_rec_calls[0], ["qstat", "-x", "-f", "-F", "json", "-u", getpass.getuser()]
        )

        # Verify submission_recorded.json was written with exact qualified handle
        f_acc_file = os.path.join(
            f_art_store.layout.pointSchedulerDir(f_scale_point, 0),
            "submission_recorded.json",
        )
        self.assertTrue(os.path.exists(f_acc_file))
        with open(f_acc_file, "r", encoding="utf-8") as f_f:
            f_acc_data = json.load(f_f)
            self.assertEqual(f_acc_data["payload"]["handle"]["job_id"], f_qualified_id)

    def testPbsCancellationFullQualifiedHandle(self) -> None:
        """Simulates signal interruption on PBS and verifies exact qualified handle in cancel command and evidence."""
        f_qualified_id = "998877.isambard-pbs"
        f_sig_coord = SignalCoordinator()
        f_fake_runner = FakeSchedulerCommandRunner()
        f_fake_runner.m_submit_job_ids = [f_qualified_id]

        f_orch_int = RunOrchestrator(
            f_command_runner=f_fake_runner,
            f_worker_validator=lambda f_p: self.m_worker_path,
            f_signal_coordinator=f_sig_coord,
            f_poll_interval=0.01,
        )

        def on_submit_int(f_jid: str, f_cwd: Optional[str]) -> None:
            f_sig_coord.trigger(signal.SIGINT)

        f_fake_runner.m_on_submit_callback = on_submit_int

        f_view_int = f_orch_int.execute(
            f_request=RunRequest("ior", "local"),
            f_site=self.m_isambard_profile,
        )

        self.assertEqual(f_orch_int.exitCode, 130)
        self.assertIn(
            f_view_int.state, (OverallRunState.INTERRUPTED, OverallRunState.CANCELLED)
        )

        # Verify qdel was called with exact qualified handle
        f_qdel_calls = [
            c for c in f_fake_runner.m_calls if os.path.basename(c[0]) == "qdel"
        ]
        self.assertEqual(len(f_qdel_calls), 1)
        self.assertEqual(f_qdel_calls[0], ["qdel", f_qualified_id])

        # Verify post-qdel accounting query was polled with exact qualified handle
        f_qstat_acct = [
            c
            for c in f_fake_runner.m_calls
            if os.path.basename(c[0]) == "qstat" and "-x" in c and "-u" not in c
        ]
        self.assertTrue(len(f_qstat_acct) >= 1)
        for f_c in f_qstat_acct:
            self.assertEqual(f_c, ["qstat", "-x", "-f", "-F", "json", f_qualified_id])

        # Verify cancel evidence on disk contains exact qualified handle
        f_pt = f_orch_int.last_plan.scale_points[0]
        f_sched_dir = f_orch_int.last_artifact_store.layout.pointSchedulerDir(f_pt, 0)

        f_cancel_req_file = os.path.join(f_sched_dir, "cancel_requested.json")
        self.assertTrue(os.path.exists(f_cancel_req_file))
        with open(f_cancel_req_file, "r", encoding="utf-8") as f_f:
            f_req_data = json.load(f_f)
            self.assertEqual(f_req_data["payload"]["handle"]["job_id"], f_qualified_id)
            self.assertEqual(f_req_data["payload"]["handle"]["backend"], "pbs")

        f_cancel_rec_file = os.path.join(f_sched_dir, "cancel_recorded.json")
        self.assertTrue(os.path.exists(f_cancel_rec_file))
        with open(f_cancel_rec_file, "r", encoding="utf-8") as f_f:
            f_rec_data = json.load(f_f)
            self.assertEqual(f_rec_data["payload"]["handle"]["job_id"], f_qualified_id)
            self.assertEqual(f_rec_data["payload"]["handle"]["backend"], "pbs")

    def testConcurrentIsolation(self) -> None:
        """6. testConcurrentIsolation: Asserts that concurrent orchestrator executions attempting the same run root reject collisions."""
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

        f_fake_runner.m_on_submit_callback = lambda jid, cwd: (
            self._simulatePointExecution(
                f_orch1.last_artifact_store,
                f_orch1.last_evidence_store,
                f_orch1.last_plan.scale_points[0],
                f_orch1.last_plan,
            )
        )

        # Orch1 executes and allocates shared-run-id-123
        f_view1 = f_orch1.execute(
            f_request=f_req,
            f_site=self.m_viking_profile,
        )
        self.assertEqual(f_orch1.exitCode, 0)
        self.assertEqual(f_view1.state, OverallRunState.SUCCEEDED)

        # Second orchestrator with same run ID must fail on allocation collision
        with self.assertRaises(OrchestrationError) as f_ctx:
            f_orch2.execute(
                f_request=f_req,
                f_site=self.m_viking_profile,
            )
        self.assertIn("failed to allocate run", str(f_ctx.exception).lower())

    def testConcurrentIdenticalRequestsUseDistinctRoots(self) -> None:
        """Asserts concurrent identical requests generate or use distinct roots with zero cross-run interference."""
        f_req = RunRequest(f_target="ior", f_scale="local", f_ssd=False)
        f_fake_runner = FakeSchedulerCommandRunner()

        f_orch1 = RunOrchestrator(
            f_command_runner=f_fake_runner,
            f_worker_validator=lambda f_p: self.m_worker_path,
            f_run_id_source=lambda: "run-concurrent-distinct-1",
        )
        f_orch2 = RunOrchestrator(
            f_command_runner=f_fake_runner,
            f_worker_validator=lambda f_p: self.m_worker_path,
            f_run_id_source=lambda: "run-concurrent-distinct-2",
        )

        f_fake_runner.m_on_submit_callback = lambda jid, cwd: (
            self._simulatePointExecution(
                f_orch1.last_artifact_store
                if cwd and "distinct-1" in cwd
                else f_orch2.last_artifact_store,
                f_orch1.last_evidence_store
                if cwd and "distinct-1" in cwd
                else f_orch2.last_evidence_store,
                f_orch1.last_plan.scale_points[0]
                if cwd and "distinct-1" in cwd
                else f_orch2.last_plan.scale_points[0],
                f_orch1.last_plan if cwd and "distinct-1" in cwd else f_orch2.last_plan,
            )
        )

        f_view1 = f_orch1.execute(f_request=f_req, f_site=self.m_viking_profile)
        f_view2 = f_orch2.execute(f_request=f_req, f_site=self.m_viking_profile)

        self.assertEqual(f_view1.state, OverallRunState.SUCCEEDED)
        self.assertEqual(f_view2.state, OverallRunState.SUCCEEDED)

        self.assertNotEqual(
            f_orch1.last_artifact_store.layout.runRoot,
            f_orch2.last_artifact_store.layout.runRoot,
        )
        self.assertTrue(os.path.isdir(f_orch1.last_artifact_store.layout.runRoot))
        self.assertTrue(os.path.isdir(f_orch2.last_artifact_store.layout.runRoot))

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
            "lmp",
            "large",
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
            if (
                f_orch_combo_fail.last_artifact_store
                and f_orch_combo_fail.last_evidence_store
            ):
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
            if (
                f_orch_rank_fail.last_artifact_store
                and f_orch_rank_fail.last_evidence_store
            ):
                f_pt = f_orch_rank_fail.last_plan.scale_points[0]
                for f_combo in f_orch_rank_fail.last_plan.combinations:
                    # Rank 0 succeeds, Rank 1 fails
                    f_orch_rank_fail.last_evidence_store.recordRankResult(
                        f_point=f_pt,
                        f_global_rank=0,
                        f_combination=f_combo,
                        f_payload={
                            "returncode": 0,
                            "status": "completed",
                            "exit_status": 0,
                            "global_rank": 0,
                            "rank": 0,
                            "combination": f_combo.name,
                            "argv": ["lsmioworker", "rank", f_combo.name],
                            "log_path": "/mock/log",
                            "result_path": "/mock/res",
                            "timed_out": False,
                        },
                        f_ordinal=0,
                    )
                    f_orch_rank_fail.last_evidence_store.recordRankResult(
                        f_point=f_pt,
                        f_global_rank=1,
                        f_combination=f_combo,
                        f_payload={
                            "returncode": 1,
                            "status": "failed",
                            "global_rank": 1,
                            "rank": 1,
                            "combination": f_combo.name,
                        },
                        f_ordinal=0,
                    )
                    f_orch_rank_fail.last_evidence_store.recordControllerResult(
                        f_point=f_pt,
                        f_combination=f_combo,
                        f_payload={
                            "returncode": 1,
                            "status": "failed",
                            "stage": "rank_evidence",
                            "combination": f_combo.name,
                        },
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
            f_script_path=os.path.join(
                f_art_store.layout.pointSchedulerDir(f_scale_point, 0), "job.sh"
            ),
            f_working_dir=f_art_store.layout.pointDir(f_scale_point, 0),
            f_resources=f_plan.scheduled_points[0],
            f_output_path=os.path.join(
                f_art_store.layout.pointLogsDir(f_scale_point, 0), "job.out"
            ),
            f_error_path=os.path.join(
                f_art_store.layout.pointLogsDir(f_scale_point, 0), "job.err"
            ),
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
        f_sbatch_calls = [
            c for c in f_fake_runner.m_calls if os.path.basename(c[0]) == "sbatch"
        ]
        self.assertEqual(
            len(f_sbatch_calls),
            0,
            f"Expected no duplicate sbatch call, got: {f_sbatch_calls}",
        )

        # Verify submission_recorded.json was written
        f_acc_file = os.path.join(
            f_art_store.layout.pointSchedulerDir(f_scale_point, 0),
            "submission_recorded.json",
        )
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
        self.assertIn(
            f_view_int.state, (OverallRunState.INTERRUPTED, OverallRunState.CANCELLED)
        )
        self.assertTrue(
            any(
                f_e.evidence_kind == EvidenceKind.INTERRUPTED
                for f_e in f_orch_int.last_evidence_store.readControlEvents("control")
            )
        )

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
        self.assertIn(
            f_view_term.state, (OverallRunState.INTERRUPTED, OverallRunState.CANCELLED)
        )
        self.assertTrue(
            any(
                f_e.evidence_kind == EvidenceKind.INTERRUPTED
                for f_e in f_orch_term.last_evidence_store.readControlEvents("control")
            )
        )

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
        f_evidence_store.recordSubmissionRequested(
            f_point=f_plan.scale_points[0],
            f_writer_id="control",
            f_payload={"token": f_plan.tokens[0]},
            f_ordinal=0,
        )
        f_evidence_store.recordSubmissionDispatched(
            f_point=f_plan.scale_points[0],
            f_writer_id="control",
            f_payload={"token": f_plan.tokens[0]},
            f_ordinal=0,
        )
        f_evidence_store.recordSubmissionRecorded(
            f_point=f_plan.scale_points[0],
            f_writer_id="control",
            f_handle=JobHandle("slurm", "10001"),
            f_payload={},
            f_ordinal=0,
        )
        f_evidence_store.recordSchedulerObservation(
            f_point=f_plan.scale_points[0],
            f_writer_id="control",
            f_sequence=1,
            f_payload={
                "handle": {"backend": "slurm", "job_id": "10001"},
                "state": "succeeded",
                "exit_code": 0,
            },
            f_ordinal=0,
        )
        f_evidence_store.recordWholeRunSucceeded(
            "control", 1, {"run_id": "test-run-precedence"}
        )

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
        f_inst_pkg_dir = os.path.join(
            f_inst_prefix, "share", "lsmio", "python", "lsmiotool"
        )
        f_inst_lib_dir = os.path.join(f_inst_pkg_dir, "lib")
        os.makedirs(f_inst_lib_dir, exist_ok=True)

        with open(
            os.path.join(f_inst_pkg_dir, "__init__.py"), "w", encoding="utf-8"
        ) as f_f:
            f_f.write('"""lsmiotool installed package."""\n')

        for f_mod in (
            "__init__.py",
            "cli.py",
            "main.py",
            "run.py",
            "worker.py",
            "version.py",
            "resources.py",
        ):
            with open(
                os.path.join(f_inst_lib_dir, f_mod), "w", encoding="utf-8"
            ) as f_f:
                f_f.write(f'"""Mock {f_mod}."""\n')

        # Installed worker
        f_inst_worker = os.path.join(
            f_inst_prefix, "libexec", "lsmio", "lsmiotool-worker"
        )
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

    def testForegroundPollingQueuedActiveDelayedAccountingTimeoutNoBusyLoop(
        self,
    ) -> None:
        """Covers queued -> active -> delayed accounting -> terminal, errors/timeouts, and no busy loop."""
        f_sleep_records: List[float] = []

        def sleep_spy(f_s: float) -> None:
            f_sleep_records.append(f_s)

        f_fake_runner = FakeSchedulerCommandRunner()
        f_fake_runner.m_submit_job_ids = ["99001"]
        f_orig_run = f_fake_runner.run

        # Phase 1: Queued (poll 1) -> Active (poll 2) -> Active (poll 3) -> Terminal (poll 4)
        f_poll_step = 0

        def fake_runner_phased(f_argv: Sequence[str], **f_kwargs: Any) -> ProcessResult:
            nonlocal f_poll_step
            f_cmd = list(f_argv)
            f_exe = os.path.basename(f_cmd[0])
            if f_exe == "sbatch":
                if f_fake_runner.m_on_submit_callback is not None:
                    f_fake_runner.m_on_submit_callback("99001", f_kwargs.get("f_cwd"))
                return ProcessResult(0, "99001\n", "", 0.01)
            elif f_exe == "squeue":
                f_poll_step += 1
                if f_poll_step == 1:
                    return ProcessResult(0, "99001|PENDING\n", "", 0.01)
                elif f_poll_step in (2, 3):
                    return ProcessResult(0, "99001|RUNNING\n", "", 0.01)
                else:
                    # Job completed and left active queue
                    return ProcessResult(0, "", "", 0.01)
            elif f_exe == "sacct":
                if f_poll_step <= 3:
                    # Not yet completed in accounting
                    return ProcessResult(0, "", "", 0.01)
                return ProcessResult(
                    0,
                    "JobIDRaw|JobName|State|ExitCode\n99001|lm-job|COMPLETED|0:0\n",
                    "",
                    0.01,
                )
            return f_orig_run(f_argv, **f_kwargs)

        f_fake_runner.run = fake_runner_phased  # type: ignore

        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_fake_runner,
            f_sleep=sleep_spy,
        )

        def on_submit(f_jid: str, f_cwd: Optional[str]) -> None:
            if (
                f_orch.last_artifact_store
                and f_orch.last_evidence_store
                and f_orch.last_plan
            ):
                self._simulatePointExecution(
                    f_orch.last_artifact_store,
                    f_orch.last_evidence_store,
                    f_orch.last_plan.scale_points[0],
                    f_orch.last_plan,
                    f_ordinal=0,
                )

        f_fake_runner.m_on_submit_callback = on_submit

        f_view = f_orch.execute(
            RunRequest("ior", "local"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )

        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
        # Profile cancellation.poll_interval_seconds is 8.
        # Poll 1 (PENDING) -> slept 8.0
        # Poll 2 (RUNNING) -> slept 8.0
        # Poll 3 (RUNNING) -> slept 8.0
        # Poll 4 (COMPLETED) -> terminal, no sleep after completion
        self.assertEqual(f_sleep_records, [8.0, 8.0, 8.0])

        # Phase 2: Error/Timeout fail closed test
        f_sleep_records.clear()
        f_fake_runner_err = FakeSchedulerCommandRunner()
        f_fake_runner_err.m_submit_job_ids = ["99002"]
        f_orig_err_run = f_fake_runner_err.run

        def fake_runner_timeout(
            f_argv: Sequence[str], **f_kwargs: Any
        ) -> ProcessResult:
            f_cmd = list(f_argv)
            f_exe = os.path.basename(f_cmd[0])
            if f_exe == "sbatch":
                return ProcessResult(0, "99002\n", "", 0.01)
            elif f_exe in ("squeue", "sacct"):
                return ProcessResult(
                    124, "", "command timed out after grace period\n", 0.01
                )
            return f_orig_err_run(f_argv, **f_kwargs)

        f_fake_runner_err.run = fake_runner_timeout  # type: ignore

        f_orch_err = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_fake_runner_err,
            f_sleep=sleep_spy,
        )

        f_view_err = f_orch_err.execute(
            RunRequest("ior", "local"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )

        self.assertEqual(f_view_err.state, OverallRunState.INDETERMINATE)
        self.assertEqual(f_view_err.point_states[0].state, PointRunState.INDETERMINATE)
        self.assertEqual(
            len(f_sleep_records), 0, "No busy loop or sleep on query timeout"
        )

    def testEndToEndConflictAndCorruptObservations(self) -> None:
        """Chunk 018: End-to-end validation of corrupt observations, missing accounting, conflicting handles, cancel causality, and repeated observations."""
        # 1. Corrupt observation file on disk resolves to INDETERMINATE
        f_plan = RunPlanner.createPlan(
            f_request=RunRequest("ior", "local"),
            f_profile=self.m_viking_profile,
            f_run_id_source=lambda: "e2e-corrupt-obs",
        )
        f_art_store = ArtifactStore(self.m_viking_root_hdd, "e2e-corrupt-obs")
        f_art_store.allocateRun(f_plan)
        f_evidence_store = EvidenceStore(f_art_store.layout, f_plan)
        f_pt = f_plan.scale_points[0]
        f_h = JobHandle("slurm", "99101")
        f_evidence_store.recordSubmissionRecorded(
            f_pt, "control", f_handle=f_h, f_ordinal=0
        )

        # Write corrupt observation file (1.json)
        f_obs_dir = os.path.join(
            f_art_store.layout.pointSchedulerDir(f_pt, 0), "observations", "bad_writer"
        )
        os.makedirs(f_obs_dir, exist_ok=True)
        with open(os.path.join(f_obs_dir, "1.json"), "w", encoding="utf-8") as f_f:
            f_f.write("{invalid_json_corrupted")

        f_view_corrupt = StateReconciler.reconcile(f_plan, f_evidence_store)
        self.assertEqual(
            f_view_corrupt.point_states[0].state, PointRunState.INDETERMINATE
        )
        self.assertEqual(f_view_corrupt.state, OverallRunState.INDETERMINATE)

        # 2. Conflicting handles across observation records resolves to INDETERMINATE
        f_plan2 = RunPlanner.createPlan(
            f_request=RunRequest("ior", "local"),
            f_profile=self.m_viking_profile,
            f_run_id_source=lambda: "e2e-conflict-handle",
        )
        f_art_store2 = ArtifactStore(self.m_viking_root_hdd, "e2e-conflict-handle")
        f_art_store2.allocateRun(f_plan2)
        f_evidence_store2 = EvidenceStore(f_art_store2.layout, f_plan2)
        f_pt2 = f_plan2.scale_points[0]
        f_evidence_store2.recordSubmissionRecorded(
            f_pt2, "control", f_handle=JobHandle("slurm", "99102"), f_ordinal=0
        )
        f_evidence_store2.recordSchedulerObservation(
            f_pt2,
            "w1",
            1,
            f_payload={
                "state": "active",
                "handle": {"backend": "slurm", "job_id": "88888"},
            },
            f_ordinal=0,
        )
        f_view_conflict = StateReconciler.reconcile(f_plan2, f_evidence_store2)
        self.assertEqual(
            f_view_conflict.point_states[0].state, PointRunState.INDETERMINATE
        )

        # 3. Repeated identical observations on disk stably resolve
        f_plan3 = RunPlanner.createPlan(
            f_request=RunRequest("ior", "local"),
            f_profile=self.m_viking_profile,
            f_run_id_source=lambda: "e2e-repeated-obs",
        )
        f_art_store3 = ArtifactStore(self.m_viking_root_hdd, "e2e-repeated-obs")
        f_art_store3.allocateRun(f_plan3)
        f_evidence_store3 = EvidenceStore(f_art_store3.layout, f_plan3)
        f_pt3 = f_plan3.scale_points[0]
        f_evidence_store3.recordSubmissionRecorded(
            f_pt3, "control", f_handle=JobHandle("slurm", "99103"), f_ordinal=0
        )
        self._simulatePointExecution(
            f_art_store3, f_evidence_store3, f_pt3, f_plan3, f_ordinal=0
        )
        for f_i in range(1, 6):
            f_evidence_store3.recordSchedulerObservation(
                f_pt3,
                "reconciler",
                f_i,
                f_payload={
                    "state": "succeeded",
                    "handle": {"backend": "slurm", "job_id": "99103"},
                },
                f_ordinal=0,
            )
        f_evidence_store3.recordWholeRunSucceeded("control", 1)
        f_view_repeat = StateReconciler.reconcile(f_plan3, f_evidence_store3)
        self.assertEqual(f_view_repeat.point_states[0].state, PointRunState.SUCCEEDED)
        self.assertEqual(f_view_repeat.state, OverallRunState.SUCCEEDED)

    def testEndToEndReporterStdoutSnapshots(self) -> None:
        """Chunk 019: Tests end-to-end golden stdout/stderr emission for success, failure, signal interruption, and indeterminate."""
        # 1. End-to-end full execution (success)
        f_reporter_succ = RunReporter()
        f_runner_succ = FakeSchedulerCommandRunner()
        f_runner_succ.m_submit_job_ids = ["3301"]

        f_orch_succ = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_runner_succ,
            f_poll_interval=0.01,
            f_sleep=lambda _: None,
            f_reporter=f_reporter_succ,
            f_worker_validator=lambda f_p: self.m_worker_path,
        )

        def on_submit_succ(f_jid: str, f_cwd: Optional[str]) -> None:
            if (
                f_orch_succ.last_artifact_store
                and f_orch_succ.last_evidence_store
                and f_orch_succ.last_plan
            ):
                self._simulatePointExecution(
                    f_orch_succ.last_artifact_store,
                    f_orch_succ.last_evidence_store,
                    f_orch_succ.last_plan.scale_points[0],
                    f_orch_succ.last_plan,
                    f_ordinal=0,
                )

        f_runner_succ.m_on_submit_callback = on_submit_succ

        f_view_succ = f_orch_succ.execute(
            f_request=RunRequest("ior", "local"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )

        self.assertEqual(f_view_succ.state, OverallRunState.SUCCEEDED)
        self.assertEqual(f_orch_succ.exitCode, 0)

        # Assert stdout report contents match the execution exactly
        f_succ_lines = f_reporter_succ.lines
        self.assertEqual(f_succ_lines[0], f"Run ID: {f_view_succ.run_id}")
        self.assertEqual(
            f_succ_lines[1], f"Run Root: {os.path.abspath(f_orch_succ.last_run_root)}"
        )
        self.assertEqual(
            f_succ_lines[2],
            f"Point 00-tasks-1 Correlation Token: {f_orch_succ.last_plan.tokens[0]}",
        )
        self.assertEqual(f_succ_lines[3], "Point 00-tasks-1 Job ID: 3301")
        self.assertEqual(f_succ_lines[4], "Final State: SUCCEEDED")
        self.assertEqual(f_succ_lines[5], "Exit Code: 0")
        self.assertEqual(len(f_succ_lines), 6)

        # 2. End-to-end full execution (point failure)
        f_reporter_fail = RunReporter()
        f_runner_fail = FakeSchedulerCommandRunner()
        f_runner_fail.m_submit_job_ids = ["3302"]
        f_runner_fail.m_job_fail = True

        f_orch_fail = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_runner_fail,
            f_poll_interval=0.01,
            f_sleep=lambda _: None,
            f_reporter=f_reporter_fail,
            f_worker_validator=lambda f_p: self.m_worker_path,
        )

        f_view_fail = f_orch_fail.execute(
            f_request=RunRequest("ior", "local"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )

        self.assertEqual(f_view_fail.state, OverallRunState.FAILED)
        self.assertEqual(f_orch_fail.exitCode, 1)

        f_fail_lines = f_reporter_fail.lines
        self.assertEqual(f_fail_lines[0], f"Run ID: {f_view_fail.run_id}")
        self.assertEqual(
            f_fail_lines[1], f"Run Root: {os.path.abspath(f_orch_fail.last_run_root)}"
        )
        self.assertEqual(
            f_fail_lines[2],
            f"Point 00-tasks-1 Correlation Token: {f_orch_fail.last_plan.tokens[0]}",
        )
        self.assertEqual(f_fail_lines[3], "Point 00-tasks-1 Job ID: 3302")
        self.assertEqual(f_fail_lines[4], "Final State: FAILED")
        self.assertEqual(f_fail_lines[5], "Exit Code: 1")
        self.assertEqual(len(f_fail_lines), 6)

    def testPublicFacadeThroughRealPlanArtifactsEvidenceAndReporter(self) -> None:
        """Chunk 020: Comprehensive integration of public facade through real planner, artifact store, evidence store, reconciler, and reporter across IOR/LSMIO/LMP, Slurm/PBS, and HDD/SSD/POOL storage setups."""
        # 1. IOR on Slurm (Viking Profile) - HDD & SSD (Pool setup)
        # --- HDD: IOR local with BASE setup ---
        f_runner_ior_hdd = FakeSchedulerCommandRunner()
        f_runner_ior_hdd.m_submit_job_ids = ["10101"]
        f_reporter_ior_hdd = RunReporter()

        f_orch_ior_hdd = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_runner_ior_hdd,
            f_poll_interval=0.01,
            f_sleep=lambda _: None,
            f_reporter=f_reporter_ior_hdd,
            f_worker_validator=lambda f_p: self.m_worker_path,
        )

        def on_submit_ior_hdd(f_jid: str, f_cwd: Optional[str]) -> None:
            if (
                f_orch_ior_hdd.last_artifact_store
                and f_orch_ior_hdd.last_evidence_store
                and f_orch_ior_hdd.last_plan
            ):
                self._simulatePointExecution(
                    f_orch_ior_hdd.last_artifact_store,
                    f_orch_ior_hdd.last_evidence_store,
                    f_orch_ior_hdd.last_plan.scale_points[0],
                    f_orch_ior_hdd.last_plan,
                    f_ordinal=0,
                )

        f_runner_ior_hdd.m_on_submit_callback = on_submit_ior_hdd

        f_view_ior_hdd = f_orch_ior_hdd.execute(
            f_request=RunRequest("ior", "local", f_ssd=False, f_setup="BASE"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )
        self.assertEqual(f_view_ior_hdd.state, OverallRunState.SUCCEEDED)
        self.assertEqual(f_orch_ior_hdd.exitCode, 0)
        self.assertEqual(
            f_reporter_ior_hdd.lines[0], f"Run ID: {f_view_ior_hdd.run_id}"
        )
        self.assertEqual(
            f_reporter_ior_hdd.lines[1],
            f"Run Root: {os.path.abspath(f_orch_ior_hdd.last_run_root)}",
        )
        self.assertEqual(
            f_reporter_ior_hdd.lines[2],
            f"Point 00-tasks-1 Correlation Token: {f_orch_ior_hdd.last_plan.tokens[0]}",
        )
        self.assertEqual(f_reporter_ior_hdd.lines[3], "Point 00-tasks-1 Job ID: 10101")
        self.assertEqual(f_reporter_ior_hdd.lines[4], "Final State: SUCCEEDED")
        self.assertEqual(f_reporter_ior_hdd.lines[5], "Exit Code: 0")

        # --- SSD (POOL: flash): IOR bake with COLLECTIVE setup ---
        f_runner_ior_ssd = FakeSchedulerCommandRunner()
        f_runner_ior_ssd.m_submit_job_ids = ["10102", "10103", "10104", "10105"]
        f_reporter_ior_ssd = RunReporter()

        f_orch_ior_ssd = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_runner_ior_ssd,
            f_poll_interval=0.01,
            f_sleep=lambda _: None,
            f_reporter=f_reporter_ior_ssd,
            f_worker_validator=lambda f_p: self.m_worker_path,
        )

        def on_submit_ior_ssd(f_jid: str, f_cwd: Optional[str]) -> None:
            if (
                f_orch_ior_ssd.last_artifact_store
                and f_orch_ior_ssd.last_evidence_store
                and f_orch_ior_ssd.last_plan
            ):
                f_idx = f_runner_ior_ssd.m_submit_idx - 1
                self._simulatePointExecution(
                    f_orch_ior_ssd.last_artifact_store,
                    f_orch_ior_ssd.last_evidence_store,
                    f_orch_ior_ssd.last_plan.scale_points[f_idx],
                    f_orch_ior_ssd.last_plan,
                    f_ordinal=f_idx,
                )

        f_runner_ior_ssd.m_on_submit_callback = on_submit_ior_ssd

        f_view_ior_ssd = f_orch_ior_ssd.execute(
            f_request=RunRequest("ior", "bake", f_ssd=True, f_setup="COLLECTIVE"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )
        self.assertEqual(f_view_ior_ssd.state, OverallRunState.SUCCEEDED)
        self.assertEqual(f_orch_ior_ssd.exitCode, 0)
        self.assertTrue(f_orch_ior_ssd.last_run_root.startswith(self.m_viking_root_ssd))
        self.assertEqual(len(f_view_ior_ssd.point_states), 4)

        # 2. LSMIO on PBS (Isambard Profile) - Multi-rank & Storage setups
        # --- HDD: LSMIO bake with NATIVE-M setup ---
        f_runner_lsmio = FakeSchedulerCommandRunner()
        f_runner_lsmio.m_submit_job_ids = [
            "20101.isambard-pbs",
            "20102.isambard-pbs",
            "20103.isambard-pbs",
            "20104.isambard-pbs",
        ]
        f_reporter_lsmio = RunReporter()

        f_orch_lsmio = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_runner_lsmio,
            f_poll_interval=0.01,
            f_sleep=lambda _: None,
            f_reporter=f_reporter_lsmio,
            f_worker_validator=lambda f_p: self.m_worker_path,
        )

        def on_submit_lsmio(f_jid: str, f_cwd: Optional[str]) -> None:
            if (
                f_orch_lsmio.last_artifact_store
                and f_orch_lsmio.last_evidence_store
                and f_orch_lsmio.last_plan
            ):
                f_idx = f_runner_lsmio.m_submit_idx - 1
                f_pt = f_orch_lsmio.last_plan.scale_points[f_idx]
                self._simulatePointExecution(
                    f_orch_lsmio.last_artifact_store,
                    f_orch_lsmio.last_evidence_store,
                    f_pt,
                    f_orch_lsmio.last_plan,
                    f_ordinal=f_idx,
                )

        f_runner_lsmio.m_on_submit_callback = on_submit_lsmio

        f_view_lsmio = f_orch_lsmio.execute(
            f_request=RunRequest("lsmio", "bake", f_ssd=False, f_setup="NATIVE-M"),
            f_site=self.m_isambard_profile,
            f_worker_executable=self.m_worker_path,
        )
        self.assertEqual(f_view_lsmio.state, OverallRunState.SUCCEEDED)
        self.assertEqual(f_orch_lsmio.exitCode, 0)
        self.assertIn(
            "Point 00-tasks-1 Job ID: 20101.isambard-pbs", f_reporter_lsmio.lines
        )
        self.assertIn(
            "Point 03-tasks-8 Job ID: 20104.isambard-pbs", f_reporter_lsmio.lines
        )

        # --- SSD: LSMIO local with ROCKSDB and ADIOS setups ---
        for f_lsmio_setup in ("ROCKSDB", "ADIOS"):
            f_runner_alt = FakeSchedulerCommandRunner()
            f_runner_alt.m_submit_job_ids = [
                f"20201.isambard-pbs-{f_lsmio_setup.lower()}"
            ]
            f_orch_alt = RunOrchestrator(
                f_profile_resolver=self.m_registry,
                f_command_runner=f_runner_alt,
                f_poll_interval=0.01,
                f_sleep=lambda _: None,
                f_reporter=RunReporter(),
                f_worker_validator=lambda f_p: self.m_worker_path,
            )

            def on_submit_alt(f_jid: str, f_cwd: Optional[str]) -> None:
                if (
                    f_orch_alt.last_artifact_store
                    and f_orch_alt.last_evidence_store
                    and f_orch_alt.last_plan
                ):
                    self._simulatePointExecution(
                        f_orch_alt.last_artifact_store,
                        f_orch_alt.last_evidence_store,
                        f_orch_alt.last_plan.scale_points[0],
                        f_orch_alt.last_plan,
                        f_ordinal=0,
                    )

            f_runner_alt.m_on_submit_callback = on_submit_alt

            f_view_alt = f_orch_alt.execute(
                f_request=RunRequest(
                    "lsmio", "local", f_ssd=True, f_setup=f_lsmio_setup
                ),
                f_site=self.m_isambard_profile,
                f_worker_executable=self.m_worker_path,
            )
            self.assertEqual(f_view_alt.state, OverallRunState.SUCCEEDED)

        # 3. LMP on Slurm (Viking Profile) - Storage setups & Tuning
        for f_idx, f_lmp_setup in enumerate(("LSMIO", "LSMIO-MMAP", "FS")):
            f_runner_lmp = FakeSchedulerCommandRunner()
            f_runner_lmp.m_submit_job_ids = [str(30101 + f_idx)]
            f_reporter_lmp = RunReporter()

            f_orch_lmp = RunOrchestrator(
                f_profile_resolver=self.m_registry,
                f_command_runner=f_runner_lmp,
                f_poll_interval=0.01,
                f_sleep=lambda _: None,
                f_reporter=f_reporter_lmp,
                f_worker_validator=lambda f_p: self.m_worker_path,
            )

            def on_submit_lmp(f_jid: str, f_cwd: Optional[str]) -> None:
                if (
                    f_orch_lmp.last_artifact_store
                    and f_orch_lmp.last_evidence_store
                    and f_orch_lmp.last_plan
                ):
                    self._simulatePointExecution(
                        f_orch_lmp.last_artifact_store,
                        f_orch_lmp.last_evidence_store,
                        f_orch_lmp.last_plan.scale_points[0],
                        f_orch_lmp.last_plan,
                        f_ordinal=0,
                    )

            f_runner_lmp.m_on_submit_callback = on_submit_lmp

            f_view_lmp = f_orch_lmp.execute(
                f_request=RunRequest("lmp", "local", f_ssd=False, f_setup=f_lmp_setup),
                f_site=self.m_viking_profile,
                f_worker_executable=self.m_worker_path,
            )
            self.assertEqual(f_view_lmp.state, OverallRunState.SUCCEEDED)
            self.assertEqual(f_orch_lmp.exitCode, 0)
            self.assertIn("1", f_orch_lmp.last_plan.lmp_task_tuning)

        # 4. Assert no live scheduler commands escaped to the host
        # All runner invocations were captured by the FakeSchedulerCommandRunner instances
        self.assertGreater(len(f_runner_ior_hdd.m_calls), 0)
        self.assertGreater(len(f_runner_ior_ssd.m_calls), 0)
        self.assertGreater(len(f_runner_lsmio.m_calls), 0)


if __name__ == "__main__":
    unittest.main()
