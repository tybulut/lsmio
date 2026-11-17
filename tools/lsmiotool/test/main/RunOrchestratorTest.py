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

import contextlib
import errno
import io
import json
import os
import shutil
import signal
import socket
import tempfile
import time
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Sequence
import unittest
from unittest.mock import MagicMock, call, patch
from lsmiotool.lib.archive import ArchiveEngine, ArchiveError
from lsmiotool.lib.artifacts import (
    ArtifactError,
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
from lsmiotool.lib.relocate import RelocationError
from lsmiotool.lib.run import (
    ORCHESTRATOR_PID_FILE,
    OrchestrationError,
    PlanValidationError,
    PreflightError,
    RunOrchestrator,
    RunPlan,
    RunPlanner,
    RunReporter,
    RunRequest,
    ScalePoint,
    SignalCoordinator,
    orchestratorPidPath,
    readOrchestratorPid,
    validateBenchmarkExecutable,
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
from lsmiotool.lib.benchmarks import CapabilityState
from lsmiotool.lib.site import (
    EnvironmentResolver,
    ExecutableRegistry,
    LauncherPolicy,
    ResourcePolicy,
    SchedulerKind,
    SiteProfile,
    SiteResolutionError,
)
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
        self.m_cancelled_jobs: Set[str] = set()
        self.m_recovery_candidates: Dict[str, List[str]] = {}
        self.m_on_submit_callback = None
        self.m_on_query_callback = None
        self.m_on_cancel_callback = None
        self.m_active_running_count = 0

    @property
    def m_submit_calls(self) -> List[List[str]]:
        return [c for c in self.m_calls if os.path.basename(c[0]) in ("sbatch", "qsub")]

    @property
    def m_cancel_calls(self) -> List[List[str]]:
        return [
            c for c in self.m_calls if os.path.basename(c[0]) in ("scancel", "qdel")
        ]

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
                f_jid = f"{1000 + self.m_submit_idx}"
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
            if self.m_on_query_callback is not None:
                self.m_on_query_callback(f_cmd)
            if self.m_active_running_count > 0:
                self.m_active_running_count -= 1
                f_jid = "1000"
                for f_arg in f_cmd:
                    if f_arg.startswith("--jobs="):
                        f_jid = f_arg.split("=", 1)[1]
                return ProcessResult(0, f"{f_jid}|RUNNING\n", "", 0.01)
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
                if f_arg.startswith("--jobs="):
                    f_jid = f_arg.split("=", 1)[1]
                elif f_arg == "-j" and f_idx + 1 < len(f_cmd):
                    f_jid = f_cmd[f_idx + 1]
            if self.m_job_fail:
                return ProcessResult(0, f"{f_jid}|lm-job|FAILED|1:0\n", "", 0.01)
            if f_jid in self.m_cancelled_jobs:
                return ProcessResult(0, f"{f_jid}|lm-job|CANCELLED|0:0\n", "", 0.01)
            return ProcessResult(0, f"{f_jid}|lm-job|COMPLETED|0:0\n", "", 0.01)

        elif f_exe == "qsub":
            if self.m_submit_fail:
                return ProcessResult(1, "", "qsub: error: Resource limit\n", 0.01)
            if self.m_submit_idx < len(self.m_submit_job_ids):
                f_jid = self.m_submit_job_ids[self.m_submit_idx]
                self.m_submit_idx += 1
            else:
                f_jid = f"{2000 + self.m_submit_idx}"
                self.m_submit_idx += 1
            f_full_id = f_jid if "." in f_jid else f"{f_jid}.server"
            if self.m_on_submit_callback is not None:
                self.m_on_submit_callback(f_full_id, f_cwd)
            return ProcessResult(0, f"{f_full_id}\n", "", 0.01)

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
                f_query_id = f_cmd[-1]
                f_base_id = f_query_id.split(".")[0]
                if (
                    f_base_id in self.m_cancelled_jobs
                    or f_query_id in self.m_cancelled_jobs
                ):
                    f_job_data = {"job_state": "F", "Exit_status": 271}
                elif self.m_job_fail:
                    f_job_data = {"job_state": "F", "Exit_status": 1}
                else:
                    f_job_data = {"job_state": "F", "Exit_status": 0}
                return ProcessResult(
                    0, json.dumps({"Jobs": {f_query_id: f_job_data}}), "", 0.01
                )
            else:
                # Active query -> empty Jobs object
                return ProcessResult(0, json.dumps({"Jobs": {}}), "", 0.01)

        elif f_exe in ("scancel", "qdel"):
            if self.m_on_cancel_callback is not None:
                self.m_on_cancel_callback(f_cmd)
            if len(f_cmd) > 1:
                f_target_id = f_cmd[-1].split(".")[0]
                self.m_cancelled_jobs.add(f_target_id)
            return ProcessResult(0, "", "", 0.01)

        # Default fallback (e.g. fake scheduler submissions)
        if self.m_submit_idx < len(self.m_submit_job_ids):
            f_jid = self.m_submit_job_ids[self.m_submit_idx]
            self.m_submit_idx += 1
        else:
            f_jid = f"{3000 + self.m_submit_idx}"
            self.m_submit_idx += 1
        if self.m_on_submit_callback is not None:
            self.m_on_submit_callback(f_jid, f_cwd)
        return ProcessResult(0, f"{f_jid}\n", "", 0.01)


class RunOrchestratorTest(unittest.TestCase):
    """Unit tests for RunOrchestrator covering all Chunk 024 contract and plan requirements."""

    def setUp(self) -> None:
        self.m_orig_environ = dict(os.environ)
        os.environ["SB_ACCOUNT"] = "test_acct"
        os.environ["SB_EMAIL"] = "user@example.com"
        self.m_temp_dir = tempfile.mkdtemp(prefix="lsmiotool-orchestrator-test-")
        self.m_default_profile_path = os.path.normpath(
            os.path.join(
                os.path.dirname(__file__), "..", "..", "etc", "environments.json"
            )
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

        f_base_isambard = self.m_registry.getProfile("ISAMBARD")
        self.m_isambard_root_hdd = os.path.join(self.m_temp_dir, "isambard_hdd")
        self.m_isambard_root_ssd = os.path.join(self.m_temp_dir, "isambard_ssd")
        os.makedirs(self.m_isambard_root_hdd, exist_ok=True)
        os.makedirs(self.m_isambard_root_ssd, exist_ok=True)

        self.m_fake_runner = FakeSchedulerCommandRunner()
        self.m_bin_dir = os.path.join(self.m_temp_dir, "bin")
        os.makedirs(self.m_bin_dir, exist_ok=True)

        self.m_worker_path = os.path.join(self.m_bin_dir, "lsmiotool-worker")
        with open(self.m_worker_path, "w") as f_f:
            f_f.write("#!/bin/sh\nexit 0\n")
        os.chmod(self.m_worker_path, 0o755)

        self.m_ior_path = os.path.join(self.m_bin_dir, "ior")
        with open(self.m_ior_path, "w") as f_f:
            f_f.write(
                '#!/bin/sh\nif [ "$1" = "-v" ]; then echo "IOR-3.3.0: Parallel IO Benchmark"; exit 0; fi\nexit 0\n'
            )
        os.chmod(self.m_ior_path, 0o755)

        self.m_lmp_path = os.path.join(self.m_bin_dir, "lmp")
        with open(self.m_lmp_path, "w") as f_f:
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
            with open(f_p, "w") as f_f:
                f_f.write("#!/bin/sh\nexit 0\n")
            os.chmod(f_p, 0o755)
            self.m_bm_paths[f_name] = f_p

        self.m_lmp_assets_dir = os.path.join(
            self.m_temp_dir, "share", "lsmio", "lmp-reaxff"
        )
        os.makedirs(self.m_lmp_assets_dir, exist_ok=True)
        for f_asset in ("in.reaxc.hns", "data.hns-equil", "ffield.reax.hns"):
            with open(os.path.join(self.m_lmp_assets_dir, f_asset), "w") as f_f:
                f_f.write(f"# asset content for {f_asset}\n")

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

        self.m_fake_runner = FakeSchedulerCommandRunner()
        self.m_worker_path = os.path.join(self.m_temp_dir, "bin", "lsmiotool-worker")
        os.makedirs(os.path.dirname(self.m_worker_path), exist_ok=True)
        with open(self.m_worker_path, "w") as f_f:
            f_f.write("#!/bin/sh\nexit 0\n")
        os.chmod(self.m_worker_path, 0o755)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self.m_orig_environ)
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
        f_is_lsmio = f_plan.request.target.lower() == "lsmio"
        for f_combo in f_plan.combinations:
            f_ret = 1 if f_failed else 0
            f_evidence_store.recordControllerResult(
                f_point=f_scale_point,
                f_combination=f_combo,
                f_payload={
                    "returncode": f_ret,
                    "status": "failed" if f_failed else "completed",
                },
                f_ordinal=f_ordinal,
            )
            if f_is_lsmio:
                for f_r in range(f_scale_point.tasks):
                    f_evidence_store.recordRankResult(
                        f_point=f_scale_point,
                        f_global_rank=f_r,
                        f_combination=f_combo,
                        f_payload={
                            "returncode": f_ret,
                            "status": "failed" if f_failed else "completed",
                        },
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
        self.assertEqual(
            len(self.m_fake_runner.m_calls), 0, "No scheduler commands should be run"
        )

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

    def testSameIdCollisionRejectsWithoutAnyWriteOrSubmit(self) -> None:
        """Asserts normal execute on existing run ID rejects collision before point preparation, scripts, evidence, or submit."""
        f_run_id = "test-collision-run-id"
        f_plan = RunPlanner.createPlan(
            RunRequest("ior", "local"),
            self.m_viking_profile,
            f_run_id_source=lambda: f_run_id,
        )
        f_broot = self.m_viking_profile.benchmark_roots["hdd"]
        f_store = ArtifactStore(f_broot, f_run_id)
        f_store.allocateRun(f_plan)

        # Write sentinel data in the winner root
        f_sentinel_path = os.path.join(f_store.layout.runRoot, "sentinel.dat")
        with open(f_sentinel_path, "wb") as f_f:
            f_f.write(b"existing-winner-data-123")

        f_submit_calls_before = len(
            [c for c in self.m_fake_runner.m_calls if c[0] == "sbatch"]
        )

        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
            f_run_id_source=lambda: f_run_id,
            f_poll_interval=0.01,
        )

        with self.assertRaises(OrchestrationError) as f_ctx:
            f_orch.execute(
                RunRequest("ior", "local"),
                f_site=self.m_viking_profile,
                f_worker_executable=self.m_worker_path,
            )

        self.assertIn("failed to allocate run", str(f_ctx.exception).lower())
        # Zero scheduler submit commands
        f_submit_calls_after = len(
            [c for c in self.m_fake_runner.m_calls if c[0] == "sbatch"]
        )
        self.assertEqual(f_submit_calls_after, f_submit_calls_before)

        # Zero point preparation, script, or evidence modifications
        with open(f_sentinel_path, "rb") as f_f:
            self.assertEqual(f_f.read(), b"existing-winner-data-123")
        self.assertFalse(
            os.path.exists(os.path.join(f_store.layout.runRoot, "points", "00-tasks-1"))
        )

    def testArtifactFactoryExistingRootCannotBypassAllocation(self) -> None:
        """Asserts custom artifact store factory returning existing root cannot bypass allocation collision check."""
        f_run_id = "test-factory-existing-root"
        f_plan = RunPlanner.createPlan(
            RunRequest("ior", "local"),
            self.m_viking_profile,
            f_run_id_source=lambda: f_run_id,
        )
        f_broot = self.m_viking_profile.benchmark_roots["hdd"]
        f_store = ArtifactStore(f_broot, f_run_id)
        f_store.allocateRun(f_plan)

        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
            f_artifact_store_factory=lambda root, rid: f_store,
            f_run_id_source=lambda: f_run_id,
        )

        with self.assertRaises(OrchestrationError) as f_ctx:
            f_orch.execute(
                RunRequest("ior", "local"),
                f_site=self.m_viking_profile,
                f_worker_executable=self.m_worker_path,
            )

        self.assertIn("failed to allocate run", str(f_ctx.exception).lower())

    def testEveryBoundaryFailure(self) -> None:
        """Submit failure and lost job state stop the run; a failed job does not stop later points (bmtool)."""
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
        f_submit_calls = [
            f_c for f_c in f_runner_submit_fail.m_calls if f_c[0] == "sbatch"
        ]
        self.assertEqual(
            len(f_submit_calls), 1, "Must not submit point 2 after point 1 submit fails"
        )

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
        f_submit_calls_2 = [
            f_c for f_c in f_runner_query_fail.m_calls if f_c[0] == "sbatch"
        ]
        self.assertEqual(
            len(f_submit_calls_2),
            1,
            "Must not submit point 2 after query failure on point 1",
        )

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
        f_submit_calls_3 = [
            f_c for f_c in f_runner_job_fail.m_calls if f_c[0] == "sbatch"
        ]
        self.assertEqual(
            len(f_submit_calls_3),
            4,
            "A failed point must not stop later points from being submitted",
        )

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
            f_e
            for f_e in f_ctrl_events
            if f_e.evidence_kind == EvidenceKind.WHOLE_RUN_SUCCEEDED
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
        """Asserts concurrent orchestrator normal execution is rejected on collision."""
        f_plan = RunPlanner.createPlan(
            RunRequest("ior", "local"),
            self.m_viking_profile,
        )
        f_broot = self.m_viking_profile.benchmark_roots["hdd"]
        f_store = ArtifactStore(f_broot, f_plan.run_id)
        f_store.allocateRun(f_plan)

        f_lock_1 = f_store.getControlLock()
        f_lock_1.acquire(f_blocking=False)
        self.assertTrue(f_lock_1.is_locked)

        try:
            f_orch_2 = RunOrchestrator(
                f_profile_resolver=self.m_registry,
                f_command_runner=self.m_fake_runner,
                f_run_id_source=lambda: f_plan.run_id,
            )

            # 1. Normal execute on existing run root must reject collision immediately
            with self.assertRaises(OrchestrationError) as f_ctx:
                f_orch_2.execute(
                    RunRequest("ior", "local"),
                    f_site=self.m_viking_profile,
                    f_worker_executable=self.m_worker_path,
                )
            self.assertIn("failed to allocate run", str(f_ctx.exception).lower())
        finally:
            f_lock_1.release()

    def testReportsIdsRootState(self) -> None:
        """Asserts returned view and reporter contain run_id, root, and final reconciled state."""
        f_reporter = RunReporter()
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
            f_poll_interval=0.01,
            f_reporter=f_reporter,
        )
        self.assertEqual(f_orch.reporter, f_reporter)

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

        # Assert reporter lines
        f_lines = f_reporter.lines
        self.assertIn(f"Run ID: {f_view.run_id}", f_lines)
        self.assertIn(f"Run Root: {os.path.abspath(f_orch.last_run_root)}", f_lines)
        self.assertIn("Point 00-tasks-1 Job ID: 1001", f_lines)
        self.assertIn("Final State: SUCCEEDED", f_lines)
        self.assertIn("Exit Code: 0", f_lines)

    def testDetectedNameResolvedThroughSelectedProfileFile(self) -> None:
        """Asserts detected name is resolved through selected profile file without passing user/home to detect."""
        # 1. Create a custom profile file in a temporary location with known path
        f_custom_profile_dir = os.path.join(self.m_temp_dir, "custom_etc")
        os.makedirs(f_custom_profile_dir, exist_ok=True)
        f_custom_profile_file = os.path.join(f_custom_profile_dir, "environments.json")
        with open(self.m_default_profile_path, "r", encoding="utf-8") as f_src:
            f_profile_data = json.load(f_src)
        with open(f_custom_profile_file, "w", encoding="utf-8") as f_dst:
            json.dump(f_profile_data, f_dst)

        # 2. Construct a RuntimeLayout using this profile file authority
        f_layout = RuntimeLayout(
            f_execution_mode=ExecutionMode.SOURCE,
            f_package_root=os.path.join(self.m_temp_dir, "pkg"),
            f_profile_file=f_custom_profile_file,
            f_asset_root=os.path.join(self.m_temp_dir, "assets"),
            f_worker_executable=self.m_worker_path,
            f_version_file=os.path.join(self.m_temp_dir, "VERSION"),
        )

        f_orch = RunOrchestrator(
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

        f_detect_calls = []
        f_resolve_calls = []

        def spy_detect(*args: Any, **kwargs: Any) -> str:
            f_detect_calls.append((args, kwargs))
            return "VIKING"

        def spy_resolve(*args: Any, **kwargs: Any) -> SiteProfile:
            f_resolve_calls.append((args, kwargs))
            return self.m_viking_profile

        with patch.object(EnvironmentResolver, "detect", side_effect=spy_detect):
            with patch.object(
                EnvironmentResolver, "resolveProfile", side_effect=spy_resolve
            ):
                f_view = f_orch.execute(
                    RunRequest("ior", "local"),
                    f_site=None,
                    f_runtime_layout=f_layout,
                    f_worker_executable=self.m_worker_path,
                    f_user=self.m_test_user,
                    f_home=self.m_test_home,
                )

        # Assert detect called exactly once with test_mode only, NO user or home
        self.assertEqual(len(f_detect_calls), 1)
        _, f_det_kw = f_detect_calls[0]
        self.assertNotIn("f_user", f_det_kw)
        self.assertNotIn("f_home", f_det_kw)
        self.assertNotIn("user", f_det_kw)
        self.assertNotIn("home", f_det_kw)

        # Assert resolveProfile called with detected name, user, home, and selected profile_file
        self.assertEqual(len(f_resolve_calls), 1)
        f_res_args, f_res_kw = f_resolve_calls[0]
        self.assertEqual(f_res_args[0], "VIKING")
        self.assertEqual(f_res_kw.get("f_user"), self.m_test_user)
        self.assertEqual(f_res_kw.get("f_home"), self.m_test_home)
        self.assertEqual(f_res_kw.get("f_env_file"), f_custom_profile_file)

        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)

    def testExplicitNameAndProfile(self) -> None:
        """Asserts explicit SiteProfile is used unchanged, and explicit name resolves without detection."""
        f_orch = RunOrchestrator(
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
        self.m_fake_runner.m_submit_job_ids = ["1001", "1002"]

        # 1. Explicit SiteProfile instance
        f_detect_mock = MagicMock()
        f_resolve_mock = MagicMock()
        with patch.object(EnvironmentResolver, "detect", f_detect_mock):
            with patch.object(EnvironmentResolver, "resolveProfile", f_resolve_mock):
                f_view_1 = f_orch.execute(
                    RunRequest("ior", "local"),
                    f_site=self.m_viking_profile,
                    f_worker_executable=self.m_worker_path,
                )
        self.assertEqual(f_view_1.state, OverallRunState.SUCCEEDED)
        f_detect_mock.assert_not_called()
        f_resolve_mock.assert_not_called()

        # 2. Explicit string name
        with patch.object(EnvironmentResolver, "detect", f_detect_mock):
            with patch.object(
                EnvironmentResolver,
                "resolveProfile",
                return_value=self.m_viking_profile,
            ) as mock_resolve:
                f_view_2 = f_orch.execute(
                    RunRequest("ior", "local"),
                    f_site="VIKING",
                    f_worker_executable=self.m_worker_path,
                    f_user=self.m_test_user,
                    f_home=self.m_test_home,
                )
        self.assertEqual(f_view_2.state, OverallRunState.SUCCEEDED)
        f_detect_mock.assert_not_called()
        mock_resolve.assert_called_once_with(
            "VIKING", f_user=self.m_test_user, f_home=self.m_test_home, f_env_file=None
        )

        # 3. Injected profile resolver returning SiteProfile vs string name
        f_runner_3 = FakeSchedulerCommandRunner()
        f_runner_3.m_submit_job_ids = ["2001"]
        mock_resolver = MagicMock(spec=["resolveProfile"])
        mock_resolver.resolveProfile.return_value = self.m_viking_profile
        f_orch_custom = RunOrchestrator(
            f_profile_resolver=mock_resolver,
            f_command_runner=f_runner_3,
            f_poll_interval=0.01,
        )

        def on_submit_3(f_jid: str, f_cwd: Optional[str]) -> None:
            if f_orch_custom.last_evidence_store and f_orch_custom.last_plan:
                self._mockWritePointResults(
                    f_orch_custom.last_evidence_store,
                    f_orch_custom.last_plan.scale_points[0],
                    f_orch_custom.last_plan,
                    f_ordinal=0,
                )

        f_runner_3.m_on_submit_callback = on_submit_3

        f_view_3 = f_orch_custom.execute(
            RunRequest("ior", "local"),
            f_site="VIKING",
            f_worker_executable=self.m_worker_path,
            f_user=self.m_test_user,
            f_home=self.m_test_home,
        )
        self.assertEqual(f_view_3.state, OverallRunState.SUCCEEDED)
        mock_resolver.resolveProfile.assert_called_once()

    def testUnknownAmbiguousAndDevProductionFailBeforePlan(self) -> None:
        """Asserts unknown, ambiguous, DEV without opt-in, and bad schema fail before planning with zero mutation."""
        f_run_id_spy = MagicMock(return_value="run-should-not-exist")
        f_store_factory_spy = MagicMock()
        f_command_spy = MagicMock()
        f_worker_val_spy = MagicMock()

        f_orch = RunOrchestrator(
            f_run_id_source=f_run_id_spy,
            f_artifact_store_factory=f_store_factory_spy,
            f_command_runner=f_command_spy,
            f_worker_validator=f_worker_val_spy,
            f_test_mode=False,
        )

        # 1. Unknown host in production (f_test_mode=False)
        with patch.object(
            EnvironmentResolver,
            "detect",
            side_effect=SiteResolutionError("Unknown HPC environment"),
        ):
            with self.assertRaises(PreflightError) as ctx:
                f_orch.execute(
                    RunRequest("ior", "local"),
                    f_site=None,
                    f_worker_executable=self.m_worker_path,
                )
            self.assertIn("Failed to detect site profile", str(ctx.exception))
            f_run_id_spy.assert_not_called()
            f_store_factory_spy.assert_not_called()
            f_command_spy.assert_not_called()
            f_worker_val_spy.assert_not_called()

        # 2. Ambiguous host in production
        with patch.object(
            EnvironmentResolver,
            "detect",
            side_effect=SiteResolutionError(
                "Ambiguous site detection: matched ['VIKING', 'VIKING2']"
            ),
        ):
            with self.assertRaises(PreflightError) as ctx:
                f_orch.execute(
                    RunRequest("ior", "local"),
                    f_site=None,
                    f_worker_executable=self.m_worker_path,
                )
            self.assertIn("Ambiguous site detection", str(ctx.exception))
            f_run_id_spy.assert_not_called()
            f_store_factory_spy.assert_not_called()
            f_command_spy.assert_not_called()

        # 3. DEV environment in production without opt-in (f_test_mode=False)
        with patch.dict(os.environ, {"LSMIO_ENV": "DEV"}):
            with self.assertRaises(PreflightError) as ctx:
                f_orch.execute(
                    RunRequest("ior", "local"),
                    f_site=None,
                    f_worker_executable=self.m_worker_path,
                    f_test_mode=False,
                )
            self.assertIn(
                "DEV environment requires explicit test_mode=True", str(ctx.exception)
            )
            f_run_id_spy.assert_not_called()
            f_store_factory_spy.assert_not_called()

        # 4. Invalid profile schema (corrupted file)
        f_bad_profile_file = os.path.join(self.m_temp_dir, "bad_environments.json")
        with open(f_bad_profile_file, "w", encoding="utf-8") as f_f:
            f_f.write("{ invalid json")

        f_bad_layout = RuntimeLayout(
            f_execution_mode=ExecutionMode.SOURCE,
            f_package_root=os.path.join(self.m_temp_dir, "pkg"),
            f_profile_file=f_bad_profile_file,
            f_asset_root=os.path.join(self.m_temp_dir, "assets"),
            f_worker_executable=self.m_worker_path,
            f_version_file=os.path.join(self.m_temp_dir, "VERSION"),
        )
        with patch.object(EnvironmentResolver, "detect", return_value="VIKING"):
            with self.assertRaises(PreflightError) as ctx:
                f_orch.execute(
                    RunRequest("ior", "local"),
                    f_site=None,
                    f_runtime_layout=f_bad_layout,
                    f_worker_executable=self.m_worker_path,
                )
            self.assertIn("Failed to resolve detected site profile", str(ctx.exception))
            f_run_id_spy.assert_not_called()
            f_store_factory_spy.assert_not_called()

        # 5. Invalid user/home expansion (path traversal)
        with patch.object(EnvironmentResolver, "detect", return_value="VIKING"):
            with self.assertRaises(PreflightError) as ctx:
                f_orch.execute(
                    RunRequest("ior", "local"),
                    f_site=None,
                    f_worker_executable=self.m_worker_path,
                    f_user="../bad_user",
                    f_home="/tmp",
                )
            self.assertIn("Failed to resolve detected site profile", str(ctx.exception))
            f_run_id_spy.assert_not_called()
            f_store_factory_spy.assert_not_called()

    def testInjectedTestModeIsExplicit(self) -> None:
        """Asserts injected test mode is explicit and never inferred to fall back to DEV."""
        f_orch_prod = RunOrchestrator(
            f_command_runner=self.m_fake_runner,
            f_poll_interval=0.01,
            f_test_mode=False,
        )
        self.assertFalse(f_orch_prod.testMode)
        self.assertFalse(f_orch_prod.test_mode)

        # 1. On unknown host with f_test_mode=False, detect fails and does not yield DEV
        with patch.object(
            EnvironmentResolver,
            "detect",
            wraps=EnvironmentResolver.detect,
        ) as spy_detect:
            with patch("platform.node", return_value="unknown-laptop"):
                with patch("grp.getgrgid", side_effect=Exception("no groups")):
                    with patch.dict(os.environ, {}, clear=True):
                        with self.assertRaises(PreflightError):
                            f_orch_prod.execute(
                                RunRequest("ior", "local"),
                                f_site=None,
                                f_worker_executable=self.m_worker_path,
                                f_test_mode=False,
                            )
                        spy_detect.assert_called_once_with(f_test_mode=False)

        # 2. With explicit f_test_mode=True, unknown host yields DEV
        f_orch_test = RunOrchestrator(
            f_command_runner=self.m_fake_runner,
            f_poll_interval=0.01,
            f_test_mode=True,
        )
        self.assertTrue(f_orch_test.testMode)

        def on_submit(f_jid: str, f_cwd: Optional[str]) -> None:
            if f_orch_test.last_evidence_store and f_orch_test.last_plan:
                self._mockWritePointResults(
                    f_orch_test.last_evidence_store,
                    f_orch_test.last_plan.scale_points[0],
                    f_orch_test.last_plan,
                    f_ordinal=0,
                )

        self.m_fake_runner.m_on_submit_callback = on_submit
        self.m_fake_runner.m_submit_job_ids = ["1001"]

        with patch.object(
            EnvironmentResolver,
            "detect",
            return_value="DEV",
        ) as spy_detect_dev:
            with patch.object(
                EnvironmentResolver,
                "resolveProfile",
                return_value=self.m_viking_profile,
            ) as spy_resolve_dev:
                f_view = f_orch_test.execute(
                    RunRequest("ior", "local"),
                    f_site=None,
                    f_worker_executable=self.m_worker_path,
                    f_user=self.m_test_user,
                    f_home=self.m_test_home,
                )
                self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
                spy_detect_dev.assert_called_once_with(f_test_mode=True)
                spy_resolve_dev.assert_called_once_with(
                    "DEV",
                    f_user=self.m_test_user,
                    f_home=self.m_test_home,
                    f_env_file=None,
                )

    def testSlurmCredentialsBeforeAllMutation(self) -> None:
        """Verifies missing, whitespace, control, injected, or malformed Slurm credentials fail before any mutation."""
        f_base_viking2 = self.m_registry.getProfile("VIKING2")
        f_viking2_profile = SiteProfile(
            f_name=f_base_viking2.name,
            f_scheduler=f_base_viking2.scheduler,
            f_launcher=f_base_viking2.launcher,
            f_certification=f_base_viking2.certification,
            f_test_only=True,
            f_benchmark_roots={
                "hdd": self.m_viking_root_hdd,
                "ssd": self.m_viking_root_ssd,
            },
            f_install_prefix=f_base_viking2.install_prefix,
            f_executables=f_base_viking2.executables,
            f_modules=f_base_viking2.modules,
            f_resources=f_base_viking2.resources,
            f_rank_identity=f_base_viking2.rank_identity,
            f_cancellation=f_base_viking2.cancellation,
            f_lustre_pools=f_base_viking2.lustre_pools,
        )

        f_base_archer2 = self.m_registry.getProfile("ARCHER2")
        f_archer2_profile = SiteProfile(
            f_name=f_base_archer2.name,
            f_scheduler=f_base_archer2.scheduler,
            f_launcher=f_base_archer2.launcher,
            f_certification=f_base_archer2.certification,
            f_test_only=True,
            f_benchmark_roots={
                "hdd": self.m_viking_root_hdd,
                "ssd": self.m_viking_root_ssd,
            },
            f_install_prefix=f_base_archer2.install_prefix,
            f_executables=f_base_archer2.executables,
            f_modules=f_base_archer2.modules,
            f_resources=f_base_archer2.resources,
            f_rank_identity=f_base_archer2.rank_identity,
            f_cancellation=f_base_archer2.cancellation,
            f_lustre_pools=f_base_archer2.lustre_pools,
        )

        f_slurm_profiles = [
            self.m_viking_profile,
            f_viking2_profile,
            f_archer2_profile,
        ]

        f_bad_environ_cases = [
            {},
            {"SB_EMAIL": "user@epcc.ed.ac.uk"},
            {"SB_ACCOUNT": "e281"},
            {"SB_ACCOUNT": "", "SB_EMAIL": "user@epcc.ed.ac.uk"},
            {"SB_ACCOUNT": "   ", "SB_EMAIL": "user@epcc.ed.ac.uk"},
            {"SB_ACCOUNT": "e281", "SB_EMAIL": ""},
            {"SB_ACCOUNT": "e281", "SB_EMAIL": "   "},
            {"SB_ACCOUNT": "acct\n", "SB_EMAIL": "user@epcc.ed.ac.uk"},
            {"SB_ACCOUNT": "acct\0", "SB_EMAIL": "user@epcc.ed.ac.uk"},
            {"SB_ACCOUNT": "acct\r", "SB_EMAIL": "user@epcc.ed.ac.uk"},
            {"SB_ACCOUNT": "e281", "SB_EMAIL": "u\n@epcc.ed.ac.uk"},
            {"SB_ACCOUNT": "e281", "SB_EMAIL": "u\0@epcc.ed.ac.uk"},
            {"SB_ACCOUNT": "e281", "SB_EMAIL": "u\r@epcc.ed.ac.uk"},
            {
                "SB_ACCOUNT": "e281\n#SBATCH --export=ALL",
                "SB_EMAIL": "user@epcc.ed.ac.uk",
            },
            {"SB_ACCOUNT": "e281#SBATCH", "SB_EMAIL": "user@epcc.ed.ac.uk"},
            {"SB_ACCOUNT": "e281#PBS", "SB_EMAIL": "user@epcc.ed.ac.uk"},
            {
                "SB_ACCOUNT": "e281",
                "SB_EMAIL": "user@epcc.ed.ac.uk\n#SBATCH --mail-type=ALL",
            },
            {"SB_ACCOUNT": "e281", "SB_EMAIL": "user@epcc.ed.ac.uk#SBATCH"},
            {"SB_ACCOUNT": "-start-dash", "SB_EMAIL": "user@epcc.ed.ac.uk"},
            {"SB_ACCOUNT": "my account with spaces", "SB_EMAIL": "user@epcc.ed.ac.uk"},
            {"SB_ACCOUNT": "e281", "SB_EMAIL": "notanemail"},
            {"SB_ACCOUNT": "e281", "SB_EMAIL": "user @epcc.ed.ac.uk"},
            {"SB_ACCOUNT": "acct; rm -rf /", "SB_EMAIL": "user@epcc.ed.ac.uk"},
            {"SB_ACCOUNT": "acct$(whoami)", "SB_EMAIL": "user@epcc.ed.ac.uk"},
        ]

        for f_prof in f_slurm_profiles:
            for f_bad_env in f_bad_environ_cases:
                f_clock_calls = 0
                f_run_id_calls = 0
                f_token_calls = 0

                def clock_spy() -> str:
                    nonlocal f_clock_calls
                    f_clock_calls += 1
                    return "2026-08-22T12:00:00Z"

                def run_id_spy() -> str:
                    nonlocal f_run_id_calls
                    f_run_id_calls += 1
                    return "1234567890abcdef12345678"

                def token_spy() -> str:
                    nonlocal f_token_calls
                    f_token_calls += 1
                    return "lm-1234567890abcdef12345678"

                f_fake_runner = FakeSchedulerCommandRunner()
                f_orch = RunOrchestrator(
                    f_command_runner=f_fake_runner,
                    f_clock=clock_spy,
                    f_run_id_source=run_id_spy,
                    f_token_source=token_spy,
                    f_environ=f_bad_env,
                )

                # Benchmark root is empty before execution
                f_root = f_prof.benchmark_roots["hdd"]
                self.assertEqual(len(os.listdir(f_root)), 0)

                with self.assertRaises(PreflightError):
                    f_orch.execute(
                        RunRequest("ior", "local"),
                        f_site=f_prof,
                        f_worker_executable=self.m_worker_path,
                        f_environ=f_bad_env,
                    )

                # Verify ZERO mutations occurred
                self.assertEqual(
                    len(os.listdir(f_root)),
                    0,
                    "No run root directories should be created",
                )
                self.assertEqual(
                    len(f_fake_runner.m_calls),
                    0,
                    "No scheduler commands should be executed",
                )
                self.assertEqual(f_clock_calls, 0, "Clock should not be called")
                self.assertEqual(
                    f_run_id_calls, 0, "Run ID source should not be called"
                )
                self.assertEqual(f_token_calls, 0, "Token source should not be called")
                self.assertIsNone(f_orch.last_plan, "last_plan must remain None")
                self.assertIsNone(
                    f_orch.last_artifact_store, "last_artifact_store must remain None"
                )
                self.assertIsNone(
                    f_orch.last_run_root, "last_run_root must remain None"
                )

    def testCredentialsReachEverySlurmPointUnchanged(self) -> None:
        """Verifies valid credentials reach every point script and JobSpec without entering immutable plan."""
        f_valid_env = {
            "SB_ACCOUNT": "e281_prj",
            "SB_EMAIL": "researcher@epcc.ed.ac.uk",
        }
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
            f_poll_interval=0.01,
            f_environ=f_valid_env,
        )

        f_job_ids = ["20001", "20002", "20003", "20004"]
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
            f_environ=f_valid_env,
        )

        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
        self.assertEqual(len(f_view.point_states), 4)

        f_layout = f_orch.last_artifact_store.layout
        for f_idx, f_pt in enumerate(f_orch.last_plan.scale_points):
            f_script_path = os.path.join(
                f_layout.pointSchedulerDir(f_pt, f_idx), "job.sh"
            )
            self.assertTrue(os.path.exists(f_script_path))
            with open(f_script_path, "r", encoding="utf-8") as f_f:
                f_script_content = f_f.read()
            self.assertIn("#SBATCH --account=e281_prj", f_script_content)
            self.assertIn(
                "#SBATCH --mail-user=researcher@epcc.ed.ac.uk", f_script_content
            )
            self.assertIn("#SBATCH --mail-type=END,FAIL", f_script_content)

        # Verify immutable plan and manifest do NOT contain credentials
        f_plan_dict = f_orch.last_plan.toDict()
        f_plan_str = json.dumps(f_plan_dict)
        self.assertNotIn("SB_ACCOUNT", f_plan_str)
        self.assertNotIn("SB_EMAIL", f_plan_str)
        self.assertNotIn("e281_prj", f_plan_str)
        self.assertNotIn("researcher@epcc.ed.ac.uk", f_plan_str)

        with open(f_layout.manifestPath, "r", encoding="utf-8") as f_f:
            f_manifest_content = f_f.read()
        self.assertNotIn("SB_ACCOUNT", f_manifest_content)
        self.assertNotIn("SB_EMAIL", f_manifest_content)
        self.assertNotIn("e281_prj", f_manifest_content)
        self.assertNotIn("researcher@epcc.ed.ac.uk", f_manifest_content)

    def testPbsAndDevDoNotReadOrRenderSlurmCredentials(self) -> None:
        """Verifies PBS and DEV ignore absent or poisoned Slurm credentials and render no Slurm directives."""
        f_poisoned_env = {
            "SB_ACCOUNT": "BAD ACCOUNT WITH SPACES",
            "SB_EMAIL": "notanemail",
        }

        # 1. PBS with empty environment
        f_fake_runner_pbs = FakeSchedulerCommandRunner()
        f_orch_pbs = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_fake_runner_pbs,
            f_poll_interval=0.01,
            f_environ={},
        )
        f_fake_runner_pbs.m_submit_job_ids = ["30001"]

        def on_submit_pbs(f_jid: str, f_cwd: Optional[str]) -> None:
            if f_orch_pbs.last_evidence_store and f_orch_pbs.last_plan:
                self._mockWritePointResults(
                    f_orch_pbs.last_evidence_store,
                    f_orch_pbs.last_plan.scale_points[0],
                    f_orch_pbs.last_plan,
                    f_ordinal=0,
                )

        f_fake_runner_pbs.m_on_submit_callback = on_submit_pbs

        f_view_pbs_1 = f_orch_pbs.execute(
            RunRequest("ior", "local"),
            f_site=self.m_isambard_profile,
            f_worker_executable=self.m_worker_path,
            f_environ={},
        )
        self.assertEqual(f_view_pbs_1.state, OverallRunState.SUCCEEDED)

        # 2. PBS with poisoned Slurm environment (must succeed and render NO Slurm account/email)
        f_fake_runner_pbs_2 = FakeSchedulerCommandRunner()
        f_orch_pbs_2 = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_fake_runner_pbs_2,
            f_poll_interval=0.01,
            f_environ=f_poisoned_env,
        )
        f_fake_runner_pbs_2.m_submit_job_ids = ["30002"]

        def on_submit_pbs_2(f_jid: str, f_cwd: Optional[str]) -> None:
            if f_orch_pbs_2.last_evidence_store and f_orch_pbs_2.last_plan:
                self._mockWritePointResults(
                    f_orch_pbs_2.last_evidence_store,
                    f_orch_pbs_2.last_plan.scale_points[0],
                    f_orch_pbs_2.last_plan,
                    f_ordinal=0,
                )

        f_fake_runner_pbs_2.m_on_submit_callback = on_submit_pbs_2

        f_view_pbs_2 = f_orch_pbs_2.execute(
            RunRequest("ior", "local"),
            f_site=self.m_isambard_profile,
            f_worker_executable=self.m_worker_path,
            f_environ=f_poisoned_env,
        )
        self.assertEqual(f_view_pbs_2.state, OverallRunState.SUCCEEDED)

        # Check PBS job script content
        f_pbs_layout = f_orch_pbs_2.last_artifact_store.layout
        f_pbs_script_path = os.path.join(
            f_pbs_layout.pointSchedulerDir(f_orch_pbs_2.last_plan.scale_points[0], 0),
            "job.sh",
        )
        with open(f_pbs_script_path, "r", encoding="utf-8") as f_f:
            f_pbs_content = f_f.read()

        self.assertIn("#PBS -q arm", f_pbs_content)
        self.assertIn("#PBS -l walltime=06:00:00", f_pbs_content)
        self.assertIn("#PBS -m abe", f_pbs_content)
        self.assertNotIn("#SBATCH", f_pbs_content)
        self.assertNotIn("--account", f_pbs_content)
        self.assertNotIn("--mail-user", f_pbs_content)
        self.assertNotIn("BAD ACCOUNT WITH SPACES", f_pbs_content)
        self.assertNotIn("notanemail", f_pbs_content)

        # 3. DEV profile with empty and poisoned environment
        f_base_dev = self.m_registry.getProfile("DEV")
        f_dev_root = os.path.join(self.m_temp_dir, "dev_root")
        os.makedirs(f_dev_root, exist_ok=True)
        f_dev_prof_isolated = SiteProfile(
            f_name=f_base_dev.name,
            f_scheduler=f_base_dev.scheduler,
            f_launcher=f_base_dev.launcher,
            f_certification=f_base_dev.certification,
            f_test_only=True,
            f_benchmark_roots={"hdd": f_dev_root, "ssd": f_dev_root},
            f_install_prefix=self.m_temp_dir,
            f_executables=self.m_executables,
            f_modules=f_base_dev.modules,
            f_resources=f_base_dev.resources,
            f_rank_identity=f_base_dev.rank_identity,
            f_cancellation=f_base_dev.cancellation,
            f_lustre_pools=f_base_dev.lustre_pools,
        )

        f_fake_runner_dev = FakeSchedulerCommandRunner()
        f_orch_dev = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_fake_runner_dev,
            f_poll_interval=0.01,
            f_environ={},
            f_test_mode=True,
        )
        f_fake_runner_dev.m_submit_job_ids = ["40001"]

        def on_submit_dev(f_jid: str, f_cwd: Optional[str]) -> None:
            if f_orch_dev.last_evidence_store and f_orch_dev.last_plan:
                self._mockWritePointResults(
                    f_orch_dev.last_evidence_store,
                    f_orch_dev.last_plan.scale_points[0],
                    f_orch_dev.last_plan,
                    f_ordinal=0,
                )

        f_fake_runner_dev.m_on_submit_callback = on_submit_dev

        f_view_dev = f_orch_dev.execute(
            RunRequest("ior", "local"),
            f_site=f_dev_prof_isolated,
            f_worker_executable=self.m_worker_path,
            f_environ=f_poisoned_env,
            f_test_mode=True,
        )
        self.assertEqual(f_view_dev.state, OverallRunState.SUCCEEDED)

    def testEveryProbeablePreflightBeforeRunIdAndMutation(self) -> None:
        """Verify preflight runs before run ID generation, tokens, or filesystem mutation for all benchmarks."""
        f_run_id_calls = 0
        f_token_calls = 0

        def run_id_source() -> str:
            nonlocal f_run_id_calls
            f_run_id_calls += 1
            return "run-test-probeable-001"

        def token_source() -> str:
            nonlocal f_token_calls
            f_token_calls += 1
            return "tok-12345678"

        # 1. Invalid Worker Path (missing / non-executable)
        f_orch_bad_worker = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_run_id_source=run_id_source,
            f_token_source=token_source,
            f_command_runner=self.m_fake_runner,
        )
        with self.assertRaises(PreflightError):
            f_orch_bad_worker.execute(
                RunRequest("ior", "local"),
                f_site=self.m_viking_profile,
                f_worker_executable=os.path.join(self.m_temp_dir, "nonexistent_worker"),
            )
        self.assertEqual(f_run_id_calls, 0)
        self.assertEqual(f_token_calls, 0)

        # 2. Missing benchmark executable
        f_bad_executables = ExecutableRegistry(
            {
                "ior": os.path.join(self.m_temp_dir, "bin", "missing_ior"),
                "lmp": self.m_lmp_path,
                "bm_native": self.m_bm_paths["bm_native"],
                "bm_adios": self.m_bm_paths["bm_adios"],
                "bm_rocksdb": self.m_bm_paths["bm_rocksdb"],
                "bm_leveldb": self.m_bm_paths["bm_leveldb"],
                "bm_manager": self.m_bm_paths["bm_manager"],
            }
        )
        f_bad_prof = SiteProfile(
            f_name=self.m_viking_profile.name,
            f_scheduler=self.m_viking_profile.scheduler,
            f_launcher=self.m_viking_profile.launcher,
            f_certification=self.m_viking_profile.certification,
            f_test_only=True,
            f_benchmark_roots=self.m_viking_profile.benchmark_roots,
            f_install_prefix=self.m_temp_dir,
            f_executables=f_bad_executables,
            f_modules=self.m_viking_profile.modules,
            f_resources=self.m_viking_profile.resources,
            f_rank_identity=self.m_viking_profile.rank_identity,
            f_cancellation=self.m_viking_profile.cancellation,
            f_lustre_pools=self.m_viking_profile.lustre_pools,
        )
        with self.assertRaises(PreflightError):
            f_orch_bad_worker.execute(
                RunRequest("ior", "local"),
                f_site=f_bad_prof,
                f_worker_executable=self.m_worker_path,
            )
        self.assertEqual(f_run_id_calls, 0)
        self.assertEqual(f_token_calls, 0)

        # 3. Failing IOR probe (nonzero exit / unsupported)
        f_failing_runner = FakeSchedulerCommandRunner()
        f_failing_runner.run = lambda argv, **kw: ProcessResult(
            1, "", "IOR: failed probe", 0.01
        )  # type: ignore

        f_orch_probe_fail = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_run_id_source=run_id_source,
            f_token_source=token_source,
            f_command_runner=f_failing_runner,
        )
        with self.assertRaises(PreflightError):
            f_orch_probe_fail.execute(
                RunRequest("ior", "local"),
                f_site=self.m_viking_profile,
                f_worker_executable=self.m_worker_path,
            )
        self.assertEqual(f_run_id_calls, 0)
        self.assertEqual(f_token_calls, 0)

        # 4. Failing LMP probe (missing required setup flag)
        f_bad_lmp_runner = FakeSchedulerCommandRunner()
        f_bad_lmp_runner.run = lambda argv, **kw: ProcessResult(
            0, "LAMMPS (2 Aug 2023)\n-lsmio-fallback\n", "", 0.01
        )  # type: ignore

        f_orch_lmp_fail = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_run_id_source=run_id_source,
            f_token_source=token_source,
            f_command_runner=f_bad_lmp_runner,
        )
        with self.assertRaises(PreflightError):
            f_orch_lmp_fail.execute(
                RunRequest("lmp", "small", f_setup="LSMIO"),
                f_site=self.m_viking_profile,
                f_worker_executable=self.m_worker_path,
            )
        self.assertEqual(f_run_id_calls, 0)
        self.assertEqual(f_token_calls, 0)

    def testRealExecutableFixturesAndCapabilityMismatch(self) -> None:
        """Test real executable fixtures on disk and capability verification vs configured separation."""
        # 1. Real IOR probe -> VERIFIED
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
            f_poll_interval=0.01,
        )
        self.m_fake_runner.m_submit_job_ids = ["50001"]

        def on_sub(f_jid: str, f_cwd: Optional[str]) -> None:
            if f_orch.last_evidence_store and f_orch.last_plan:
                self._mockWritePointResults(
                    f_orch.last_evidence_store,
                    f_orch.last_plan.scale_points[0],
                    f_orch.last_plan,
                    f_ordinal=0,
                )

        self.m_fake_runner.m_on_submit_callback = on_sub

        f_view = f_orch.execute(
            RunRequest("ior", "local"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )
        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
        self.assertEqual(f_orch.last_capability_state, CapabilityState.VERIFIED)
        self.assertEqual(f_orch.lastCapabilityState, CapabilityState.VERIFIED)

        # 2. Real LSMIO executable -> CONFIGURED (unverified per Critic P-02)
        f_orch_lsmio = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
            f_poll_interval=0.01,
        )
        self.m_fake_runner.m_submit_job_ids = ["50002"]

        def on_sub_lsmio(f_jid: str, f_cwd: Optional[str]) -> None:
            if f_orch_lsmio.last_evidence_store and f_orch_lsmio.last_plan:
                self._mockWritePointResults(
                    f_orch_lsmio.last_evidence_store,
                    f_orch_lsmio.last_plan.scale_points[0],
                    f_orch_lsmio.last_plan,
                    f_ordinal=0,
                )

        self.m_fake_runner.m_on_submit_callback = on_sub_lsmio

        f_view_lsmio = f_orch_lsmio.execute(
            RunRequest("lsmio", "local", f_setup="NATIVE"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )
        self.assertEqual(f_view_lsmio.state, OverallRunState.SUCCEEDED)
        self.assertEqual(f_orch_lsmio.last_capability_state, CapabilityState.CONFIGURED)

        # 3. Real LMP executable with setup flag verification
        f_orch_lmp = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
            f_poll_interval=0.01,
        )
        self.m_fake_runner.m_submit_job_ids = ["50003"]

        def on_sub_lmp(f_jid: str, f_cwd: Optional[str]) -> None:
            if f_orch_lmp.last_evidence_store and f_orch_lmp.last_plan:
                self._mockWritePointResults(
                    f_orch_lmp.last_evidence_store,
                    f_orch_lmp.last_plan.scale_points[0],
                    f_orch_lmp.last_plan,
                    f_ordinal=0,
                )

        self.m_fake_runner.m_on_submit_callback = on_sub_lmp

        f_view_lmp = f_orch_lmp.execute(
            RunRequest("lmp", "local", f_setup="LSMIO-MMAP"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )
        self.assertEqual(f_view_lmp.state, OverallRunState.SUCCEEDED)
        self.assertEqual(f_orch_lmp.last_capability_state, CapabilityState.VERIFIED)

    def testMissingSymlinkWrongTypeUnreadableNonExecutable(self) -> None:
        """Verify strict preflight validation for benchmark executables: missing, symlink, directory, non-executable, unreadable."""
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
        )

        def make_prof_with_ior(f_path: str) -> SiteProfile:
            f_exes = ExecutableRegistry(
                {
                    "ior": f_path,
                    "lmp": self.m_lmp_path,
                    "bm_native": self.m_bm_paths["bm_native"],
                    "bm_adios": self.m_bm_paths["bm_adios"],
                    "bm_rocksdb": self.m_bm_paths["bm_rocksdb"],
                    "bm_leveldb": self.m_bm_paths["bm_leveldb"],
                    "bm_manager": self.m_bm_paths["bm_manager"],
                }
            )
            return SiteProfile(
                f_name=self.m_viking_profile.name,
                f_scheduler=self.m_viking_profile.scheduler,
                f_launcher=self.m_viking_profile.launcher,
                f_certification=self.m_viking_profile.certification,
                f_test_only=True,
                f_benchmark_roots=self.m_viking_profile.benchmark_roots,
                f_install_prefix=self.m_temp_dir,
                f_executables=f_exes,
                f_modules=self.m_viking_profile.modules,
                f_resources=self.m_viking_profile.resources,
                f_rank_identity=self.m_viking_profile.rank_identity,
                f_cancellation=self.m_viking_profile.cancellation,
                f_lustre_pools=self.m_viking_profile.lustre_pools,
            )

        # 1. Missing executable
        with self.assertRaises(PreflightError) as f_ctx:
            f_orch.execute(
                RunRequest("ior", "local"),
                f_site=make_prof_with_ior(
                    os.path.join(self.m_temp_dir, "missing_binary")
                ),
                f_worker_executable=self.m_worker_path,
            )
        self.assertIn("does not exist", str(f_ctx.exception))

        # 2. Symlink executable
        f_sym_path = os.path.join(self.m_bin_dir, "ior_symlink")
        if os.path.islink(f_sym_path):
            os.unlink(f_sym_path)
        os.symlink(self.m_ior_path, f_sym_path)
        with self.assertRaises(PreflightError) as f_ctx:
            f_orch.execute(
                RunRequest("ior", "local"),
                f_site=make_prof_with_ior(f_sym_path),
                f_worker_executable=self.m_worker_path,
            )
        self.assertIn("must not be a symlink", str(f_ctx.exception))

        # 3. Directory instead of executable
        f_dir_path = os.path.join(self.m_temp_dir, "dir_as_exe")
        os.makedirs(f_dir_path, exist_ok=True)
        with self.assertRaises(PreflightError) as f_ctx:
            f_orch.execute(
                RunRequest("ior", "local"),
                f_site=make_prof_with_ior(f_dir_path),
                f_worker_executable=self.m_worker_path,
            )
        self.assertIn("must be a regular file", str(f_ctx.exception))

        # 4. Non-executable file (mode 0644)
        f_no_x_path = os.path.join(self.m_bin_dir, "ior_no_exec")
        with open(f_no_x_path, "w") as f_f:
            f_f.write("#!/bin/sh\nexit 0\n")
        os.chmod(f_no_x_path, 0o644)
        with self.assertRaises(PreflightError) as f_ctx:
            f_orch.execute(
                RunRequest("ior", "local"),
                f_site=make_prof_with_ior(f_no_x_path),
                f_worker_executable=self.m_worker_path,
            )
        self.assertIn("execute permissions", str(f_ctx.exception))

        # 5. Unreadable file (mode 0000)
        f_no_r_path = os.path.join(self.m_bin_dir, "ior_no_read")
        with open(f_no_r_path, "w") as f_f:
            f_f.write("#!/bin/sh\nexit 0\n")
        os.chmod(f_no_r_path, 0o000)
        try:
            with self.assertRaises(PreflightError):
                f_orch.execute(
                    RunRequest("ior", "local"),
                    f_site=make_prof_with_ior(f_no_r_path),
                    f_worker_executable=self.m_worker_path,
                )
        finally:
            os.chmod(f_no_r_path, 0o644)

    def testLmpAssetsPreflightAndStageRevalidation(self) -> None:
        """Verify LMP asset root preflight before allocation and zero side effects on failure."""
        f_run_id_calls = 0

        def run_id_src() -> str:
            nonlocal f_run_id_calls
            f_run_id_calls += 1
            return "run-lmp-assets-001"

        # 1. Missing asset file raises PreflightError with zero mutations
        f_bad_asset_root = os.path.join(
            self.m_temp_dir, "bad_prefix", "share", "lsmio", "lmp-reaxff"
        )
        os.makedirs(f_bad_asset_root, exist_ok=True)
        with open(os.path.join(f_bad_asset_root, "in.reaxc.hns"), "w") as f_f:
            f_f.write("mock")
        # Missing data.hns-equil and ffield.reax.hns

        f_bad_prof = SiteProfile(
            f_name=self.m_viking_profile.name,
            f_scheduler=self.m_viking_profile.scheduler,
            f_launcher=self.m_viking_profile.launcher,
            f_certification=self.m_viking_profile.certification,
            f_test_only=True,
            f_benchmark_roots=self.m_viking_profile.benchmark_roots,
            f_install_prefix=os.path.join(self.m_temp_dir, "bad_prefix"),
            f_executables=self.m_executables,
            f_modules=self.m_viking_profile.modules,
            f_resources=self.m_viking_profile.resources,
            f_rank_identity=self.m_viking_profile.rank_identity,
            f_cancellation=self.m_viking_profile.cancellation,
            f_lustre_pools=self.m_viking_profile.lustre_pools,
        )

        f_orch_assets = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_run_id_source=run_id_src,
            f_command_runner=self.m_fake_runner,
        )
        with self.assertRaises(PreflightError) as f_ctx:
            f_orch_assets.execute(
                RunRequest("lmp", "small", f_setup="LSMIO"),
                f_site=f_bad_prof,
                f_worker_executable=self.m_worker_path,
            )
        self.assertIn("LMP asset validation failed", str(f_ctx.exception))
        self.assertEqual(f_run_id_calls, 0)

    def testProductionDefaultUsesRealSleepFunction(self) -> None:
        """Production default sleeper is time.sleep and default clock is time.monotonic."""
        f_orch = RunOrchestrator()
        self.assertIs(f_orch.sleep, time.sleep)
        self.assertIs(f_orch.sleep_fn, time.sleep)
        self.assertIs(f_orch.clock_float, time.monotonic)
        self.assertIs(f_orch.clock_fn, time.monotonic)

    def testInjectedSleepReceivesProfileIntervals(self) -> None:
        """Injected sleeper receives exact profile poll intervals during active polling."""
        f_sleep_calls: List[float] = []

        def sleep_spy(f_s: float) -> None:
            f_sleep_calls.append(f_s)

        f_runner = FakeSchedulerCommandRunner()
        f_runner.m_submit_job_ids = ["55001"]
        f_orig_run = f_runner.run

        f_current_orch: Optional[RunOrchestrator] = None

        # Track query count to transition from ACTIVE -> COMPLETED after 2 sleep intervals
        f_query_count = 0

        def fake_run(f_argv: Sequence[str], **f_kwargs: Any) -> ProcessResult:
            nonlocal f_query_count
            f_cmd = list(f_argv)
            f_exe = os.path.basename(f_cmd[0])
            if f_exe == "sbatch":
                if f_runner.m_on_submit_callback is not None:
                    f_runner.m_on_submit_callback("55001", f_kwargs.get("f_cwd"))
                return ProcessResult(0, "55001\n", "", 0.01)
            elif f_exe == "squeue":
                f_query_count += 1
                if f_query_count <= 2:
                    return ProcessResult(0, "55001|RUNNING\n", "", 0.01)
                return ProcessResult(0, "", "", 0.01)
            elif f_exe == "sacct":
                return ProcessResult(0, "55001|lm-job|COMPLETED|0:0\n", "", 0.01)
            return f_orig_run(f_argv, **f_kwargs)

        f_runner.run = fake_run  # type: ignore

        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_runner,
            f_sleep=sleep_spy,
        )
        f_current_orch = f_orch

        def on_submit(f_jid: str, f_cwd: Optional[str]) -> None:
            if (
                f_current_orch
                and f_current_orch.last_evidence_store
                and f_current_orch.last_plan
            ):
                self._mockWritePointResults(
                    f_current_orch.last_evidence_store,
                    f_current_orch.last_plan.scale_points[0],
                    f_current_orch.last_plan,
                    f_ordinal=0,
                )

        f_runner.m_on_submit_callback = on_submit

        f_view = f_orch.execute(
            RunRequest("ior", "local"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )

        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
        # Profile cancellation.poll_interval_seconds for VIKING is 8
        self.assertEqual(f_sleep_calls, [8.0, 8.0])

        # Now test with explicit f_poll_interval override
        f_sleep_calls.clear()
        f_query_count = 0
        f_orch_override = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_runner,
            f_sleep=sleep_spy,
            f_poll_interval=2.5,
        )
        f_current_orch = f_orch_override
        f_view_override = f_orch_override.execute(
            RunRequest("ior", "local"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )
        self.assertEqual(f_view_override.state, OverallRunState.SUCCEEDED)
        self.assertEqual(f_sleep_calls, [2.5, 2.5])

    def testQueryFailureErrorOrTimeoutImmediatelyBecomesIndeterminate(self) -> None:
        """Query failure/error/timeout (UNKNOWN) is retried up to UNKNOWN_POLL_LIMIT, then fails closed."""
        f_sleep_calls: List[float] = []

        def sleep_spy(f_s: float) -> None:
            f_sleep_calls.append(f_s)

        f_runner = FakeSchedulerCommandRunner()
        f_runner.m_submit_job_ids = ["66001"]
        f_orig_run = f_runner.run

        # Simulate query failure (e.g. squeue / sacct error)
        def fake_run(f_argv: Sequence[str], **f_kwargs: Any) -> ProcessResult:
            f_cmd = list(f_argv)
            f_exe = os.path.basename(f_cmd[0])
            if f_exe == "sbatch":
                return ProcessResult(0, "66001\n", "", 0.01)
            elif f_exe in ("squeue", "sacct"):
                return ProcessResult(1, "", "slurm error: daemon unreachable\n", 0.01)
            return f_orig_run(f_argv, **f_kwargs)

        f_runner.run = fake_run  # type: ignore

        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_runner,
            f_sleep=sleep_spy,
        )

        f_view = f_orch.execute(
            RunRequest("ior", "local"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )

        # Retries a bounded number of polls, then terminates as INDETERMINATE
        self.assertEqual(f_view.state, OverallRunState.INDETERMINATE)
        self.assertEqual(f_view.point_states[0].state, PointRunState.INDETERMINATE)
        self.assertEqual(len(f_sleep_calls), RunOrchestrator.UNKNOWN_POLL_LIMIT)
        self.assertEqual(f_orch.exitCode, 1)

        # Confirm no whole_run_succeeded marker is written
        f_layout = f_orch.last_artifact_store.layout
        self.assertFalse(os.path.exists(f_layout.controlEventPath("control", 1)))

    def testTransientUnknownKeepsPollingUntilCompleted(self) -> None:
        """A few failed squeue/sacct queries (e.g. sacct lag) do not end monitoring of the job."""
        f_runner = FakeSchedulerCommandRunner()
        f_sleep_calls: List[float] = []
        f_query_count = 0
        f_orig_run = f_runner.run

        def fake_run(f_argv: Sequence[str], **f_kwargs: Any) -> ProcessResult:
            nonlocal f_query_count
            f_exe = os.path.basename(list(f_argv)[0])
            if f_exe == "sbatch":
                if f_runner.m_on_submit_callback is not None:
                    f_runner.m_on_submit_callback("77101", f_kwargs.get("f_cwd"))
                return ProcessResult(0, "77101\n", "", 0.01)
            elif f_exe == "squeue":
                f_query_count += 1
                return ProcessResult(1 if f_query_count <= 3 else 0, "", "", 0.01)
            elif f_exe == "sacct":
                if f_query_count <= 3:
                    return ProcessResult(1, "", "sacct: error\n", 0.01)
                return ProcessResult(0, "77101|lm-job|COMPLETED|0:0\n", "", 0.01)
            return f_orig_run(f_argv, **f_kwargs)

        f_runner.run = fake_run  # type: ignore

        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_runner,
            f_sleep=f_sleep_calls.append,
        )

        def on_submit(f_jid: str, f_cwd: Optional[str]) -> None:
            self._mockWritePointResults(
                f_orch.last_evidence_store,
                f_orch.last_plan.scale_points[0],
                f_orch.last_plan,
                f_ordinal=0,
            )

        f_runner.m_on_submit_callback = on_submit

        f_view = f_orch.execute(
            RunRequest("ior", "local"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )

        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
        self.assertEqual(len(f_sleep_calls), 3)

    def testActiveAccountingSequenceUsesExactHandle(self) -> None:
        """Active and accounting queries receive exact handles and finite command timeouts."""
        f_runner = FakeSchedulerCommandRunner()
        f_runner.m_submit_job_ids = ["77001"]
        f_query_argvs: List[List[str]] = []
        f_orig_run = f_runner.run

        def fake_run(f_argv: Sequence[str], **f_kwargs: Any) -> ProcessResult:
            f_cmd = list(f_argv)
            f_query_argvs.append(f_cmd)
            f_exe = os.path.basename(f_cmd[0])
            if f_exe == "sbatch":
                if f_runner.m_on_submit_callback is not None:
                    f_runner.m_on_submit_callback("77001", f_kwargs.get("f_cwd"))
                return ProcessResult(0, "77001\n", "", 0.01)
            elif f_exe == "squeue":
                return ProcessResult(0, "", "", 0.01)
            elif f_exe == "sacct":
                return ProcessResult(0, "77001|lm-job|COMPLETED|0:0\n", "", 0.01)
            return f_orig_run(f_argv, **f_kwargs)

        f_runner.run = fake_run  # type: ignore

        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_runner,
            f_sleep=lambda _: None,
        )

        def on_submit(f_jid: str, f_cwd: Optional[str]) -> None:
            if f_orch.last_evidence_store and f_orch.last_plan:
                self._mockWritePointResults(
                    f_orch.last_evidence_store,
                    f_orch.last_plan.scale_points[0],
                    f_orch.last_plan,
                    f_ordinal=0,
                )

        f_runner.m_on_submit_callback = on_submit

        f_view = f_orch.execute(
            RunRequest("ior", "local"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )

        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
        # Check that squeue used --jobs=77001 and sacct used --jobs=77001
        f_squeue_calls = [f_c for f_c in f_query_argvs if f_c[0] == "squeue"]
        f_sacct_calls = [f_c for f_c in f_query_argvs if f_c[0] == "sacct"]
        self.assertTrue(
            any(
                "--jobs=77001" in f_arg for f_call in f_squeue_calls for f_arg in f_call
            )
        )
        self.assertTrue(
            any("--jobs=77001" in f_arg for f_call in f_sacct_calls for f_arg in f_call)
        )

    def testNoLaterPointAfterUnknown(self) -> None:
        """Later scale points are never submitted when an earlier point encounters UNKNOWN."""
        f_runner = FakeSchedulerCommandRunner()
        f_runner.m_submit_job_ids = ["88001", "88002", "88003", "88004"]
        f_submitted_jids: List[str] = []
        f_orig_run = f_runner.run

        def fake_run(f_argv: Sequence[str], **f_kwargs: Any) -> ProcessResult:
            f_cmd = list(f_argv)
            f_exe = os.path.basename(f_cmd[0])
            if f_exe == "sbatch":
                f_jid = f_runner.m_submit_job_ids[len(f_submitted_jids)]
                f_submitted_jids.append(f_jid)
                return ProcessResult(0, f"{f_jid}\n", "", 0.01)
            elif f_exe in ("squeue", "sacct"):
                # Always return unparseable / error for job state query
                return ProcessResult(1, "", "sacct: fatal error\n", 0.01)
            return f_orig_run(f_argv, **f_kwargs)

        f_runner.run = fake_run  # type: ignore

        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_runner,
            f_sleep=lambda _: None,
        )

        f_view = f_orch.execute(
            RunRequest("ior", "bake"),  # 4 scale points
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )

        self.assertEqual(f_view.state, OverallRunState.INDETERMINATE)
        self.assertEqual(f_view.point_states[0].state, PointRunState.INDETERMINATE)
        # Scale points 1, 2, 3 must NOT be submitted
        self.assertEqual(
            len(f_submitted_jids), 1, "Only point 0 should have been submitted"
        )
        self.assertEqual(f_submitted_jids, ["88001"])

    def testInterruptionBeforeExecutionStopsWithoutSubmitting(self) -> None:
        """Asserts that latched signal before execution blocks point submission and returns INTERRUPTED view."""
        f_runner = FakeSchedulerCommandRunner()
        f_sig = SignalCoordinator()
        f_sig.trigger(signal.SIGINT)

        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_runner,
            f_signal_coordinator=f_sig,
        )

        f_view = f_orch.execute(
            RunRequest("ior", "local"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )

        self.assertIsNotNone(f_view)
        self.assertEqual(f_view.state, OverallRunState.INTERRUPTED)
        self.assertEqual(f_orch.exitCode, 130)
        self.assertEqual(len(f_runner.m_submit_calls), 0)

        # Check durable interruption event
        f_store = f_orch.last_evidence_store
        self.assertIsNotNone(f_store)
        f_events = f_store.readControlEvents("control")
        self.assertTrue(
            any(f_e.evidence_kind == EvidenceKind.INTERRUPTED for f_e in f_events)
        )

    def testInterruptionDuringActivePollingCancelsExactHandle(self) -> None:
        """Asserts that signal during active polling cancels exact handle with exit code 130."""
        f_runner = FakeSchedulerCommandRunner()
        f_runner.m_active_running_count = 5
        f_sig = SignalCoordinator()

        def fake_query(f_cmd: Sequence[str]) -> None:
            f_sig.trigger(signal.SIGINT)

        f_runner.m_on_query_callback = fake_query

        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_runner,
            f_signal_coordinator=f_sig,
            f_sleep=lambda _: None,
            f_poll_interval=0.01,
        )

        f_view = f_orch.execute(
            RunRequest("ior", "local"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )

        self.assertIsNotNone(f_view)
        self.assertEqual(f_orch.exitCode, 130)
        self.assertIn(
            f_view.state, (OverallRunState.CANCELLED, OverallRunState.INTERRUPTED)
        )
        # Ensure cancel command was executed
        self.assertTrue(len(f_runner.m_cancel_calls) >= 1)

    def testInterruptionDurableBeforeCancellation(self) -> None:
        """Asserts that durable interruption event exists before any cancel command is executed."""
        f_runner = FakeSchedulerCommandRunner()
        f_runner.m_active_running_count = 5
        f_sig = SignalCoordinator()

        f_interruption_existed = []

        def fake_query(f_cmd: Sequence[str]) -> None:
            f_sig.trigger(signal.SIGTERM)

        def fake_cancel(f_cmd: Sequence[str]) -> None:
            if f_orch.last_evidence_store is not None:
                f_events = f_orch.last_evidence_store.readControlEvents("control")
                f_has_int = any(
                    f_e.evidence_kind == EvidenceKind.INTERRUPTED for f_e in f_events
                )
                f_interruption_existed.append(f_has_int)

        f_runner.m_on_query_callback = fake_query
        f_runner.m_on_cancel_callback = fake_cancel

        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_runner,
            f_signal_coordinator=f_sig,
            f_sleep=lambda _: None,
            f_poll_interval=0.01,
        )

        f_view = f_orch.execute(
            RunRequest("ior", "local"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )

        self.assertIsNotNone(f_view)
        self.assertEqual(f_orch.exitCode, 143)
        self.assertEqual(len(f_interruption_existed), 1)
        self.assertTrue(
            f_interruption_existed[0],
            "Interruption record must be durable before cancel command runs",
        )

    def testRunReporterCustomCallbackAndStream(self) -> None:
        """Chunk 019: Tests RunReporter stream and callback integration, resilient stream failure, and properties."""
        f_called = []

        def my_cb(line: str) -> None:
            f_called.append(line)

        f_stream = io.StringIO()
        f_reporter = RunReporter(f_stream=f_stream, f_callback=my_cb)

        self.assertEqual(f_reporter.stream, f_stream)
        self.assertEqual(f_reporter.callback, my_cb)

        f_reporter.reportRunIdentity("run-test-id", "/bench/root")
        f_reporter.reportPointSubmission("00-tasks-1", "lm-token123", "999")
        f_reporter.reportCompletion(OverallRunState.SUCCEEDED, 0)

        # Assert callback called with all lines
        self.assertEqual(
            f_called,
            [
                "Run ID: run-test-id",
                "Run Root: /bench/root",
                "Point 00-tasks-1 Correlation Token: lm-token123",
                "Point 00-tasks-1 Job ID: 999",
                "Final State: SUCCEEDED",
                "Exit Code: 0",
            ],
        )

        # Assert stream contains same lines
        self.assertEqual(f_stream.getvalue(), f_reporter.output)

        # Test broken stream handling (write raises Exception)
        class BrokenStream:
            def write(self, s: str) -> None:
                raise IOError("disk full or pipe broken")

            def flush(self) -> None:
                raise IOError("flush error")

        f_broken_rep = RunReporter(f_stream=BrokenStream(), f_callback=None)
        # Should not raise exception
        f_broken_rep.emit("Line 1")
        self.assertEqual(f_broken_rep.lines, ["Line 1"])

    def testMultiPointReportingNoDuplicateLines(self) -> None:
        """Chunk 019: Tests multi-point orchestration reports sequential submissions and dedupes identity/completion lines."""
        f_reporter = RunReporter()
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
            f_poll_interval=0.01,
            f_reporter=f_reporter,
        )

        f_submitted = []

        def on_submit(f_jid: str, f_cwd: Optional[str]) -> None:
            f_submitted.append(f_jid)
            f_idx = len(f_submitted) - 1
            if f_orch.last_evidence_store and f_orch.last_plan:
                self._mockWritePointResults(
                    f_orch.last_evidence_store,
                    f_orch.last_plan.scale_points[f_idx],
                    f_orch.last_plan,
                    f_ordinal=f_idx,
                )

        self.m_fake_runner.m_on_submit_callback = on_submit
        self.m_fake_runner.m_submit_job_ids = [str(2001 + i) for i in range(12)]

        f_view = f_orch.execute(
            RunRequest("ior", "small"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )

        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
        self.assertEqual(len(f_submitted), len(f_view.point_states))

        # Verify reporter lines
        f_out = f_reporter.output
        self.assertEqual(f_out.count(f"Run ID: {f_view.run_id}"), 1)
        self.assertEqual(
            f_out.count(f"Run Root: {os.path.abspath(f_orch.last_run_root)}"), 1
        )
        self.assertEqual(f_out.count("Point 00-tasks-1 Job ID: 2001"), 1)
        self.assertEqual(f_out.count("Point 01-tasks-2 Job ID: 2002"), 1)
        self.assertEqual(f_out.count("Final State: SUCCEEDED"), 1)
        self.assertEqual(f_out.count("Exit Code: 0"), 1)

    def testQualifiedPbsIdPreservedInReport(self) -> None:
        """Chunk 019: Asserts qualified PBS job IDs (with server dot suffix) are reported verbatim."""
        f_fake_runner_pbs = FakeSchedulerCommandRunner()
        f_reporter = RunReporter()
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_fake_runner_pbs,
            f_poll_interval=0.01,
            f_reporter=f_reporter,
        )

        def on_submit(f_jid: str, f_cwd: Optional[str]) -> None:
            if f_orch.last_evidence_store and f_orch.last_plan:
                self._mockWritePointResults(
                    f_orch.last_evidence_store,
                    f_orch.last_plan.scale_points[0],
                    f_orch.last_plan,
                    f_ordinal=0,
                )

        f_fake_runner_pbs.m_on_submit_callback = on_submit
        f_fake_runner_pbs.m_submit_job_ids = ["123456.isambard-pbs.epcc.ed.ac.uk"]

        f_view = f_orch.execute(
            RunRequest("ior", "local"),
            f_site=self.m_isambard_profile,
            f_worker_executable=self.m_worker_path,
        )

        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
        f_lines = f_reporter.lines
        self.assertIn(
            "Point 00-tasks-1 Job ID: 123456.isambard-pbs.epcc.ed.ac.uk", f_lines
        )

    def _groupOnSubmit(
        self,
        f_orch: RunOrchestrator,
        f_fail_labels: Sequence[str] = (),
        f_missing_labels: Sequence[str] = (),
    ) -> Any:
        """Submit callback writing results for every arm of the shared allocation."""

        def on_submit(f_jid: str, f_cwd: Optional[str]) -> None:
            for f_run in f_orch.groupRuns:
                f_ev = f_run.get("evidence")
                if f_ev is None or f_run["arm"].label in f_missing_labels:
                    continue
                for f_idx, f_sp in enumerate(f_run["plan"].scale_points):
                    # Prepared for this job (the worker would run it) and not yet run
                    f_point_dir = f_run["store"].layout.pointDir(f_sp, f_idx)
                    if (
                        os.path.isdir(f_point_dir)
                        and f_ev.readControllerResult(
                            f_sp, f_run["plan"].combinations[0], f_ordinal=f_idx
                        )
                        is None
                    ):
                        self._mockWritePointResults(
                            f_ev,
                            f_sp,
                            f_run["plan"],
                            f_ordinal=f_idx,
                            f_failed=f_run["arm"].label in f_fail_labels,
                        )

        return on_submit

    @staticmethod
    def _submittedScripts(f_runner: Any) -> List[str]:
        f_out = []
        for f_call in f_runner.m_submit_calls:
            with open(f_call[-1], "r", encoding="utf-8") as f_f:
                f_out.append(f_f.read())
        return f_out

    def testPairedVariantsShareOneAllocation(self) -> None:
        """bmtool INV-PAIR-1: the baseline and every variant run in ONE job on the same nodes."""
        f_fake_runner = FakeSchedulerCommandRunner()
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_fake_runner,
            f_poll_interval=0.01,
            f_reporter=RunReporter(),
        )
        f_fake_runner.m_on_submit_callback = self._groupOnSubmit(f_orch)
        f_fake_runner.m_submit_job_ids = ["9001"]

        f_req = RunRequest(
            "lsmio", "baseline", f_variants=["no-footer", "no-manoff"], f_archive=False
        )
        f_view = f_orch.execute(
            f_req,
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )

        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
        self.assertEqual(len(f_fake_runner.m_submit_calls), 1)
        self.assertEqual(
            [f_r["arm"].label for f_r in f_orch.groupRuns],
            ["baseline", "no-footer", "no-manoff"],
        )
        self.assertEqual(
            [f_r["plan"].request.variant for f_r in f_orch.groupRuns],
            [None, "no-footer", "no-manoff"],
        )
        (f_script,) = self._submittedScripts(f_fake_runner)
        f_tail = f_script.strip().splitlines()[-1]
        self.assertIn(" allocation-group ", f_tail)
        self.assertIn("stop-after-first-failure", f_tail)
        for f_r in f_orch.groupRuns:
            self.assertIn(f_r["store"].layout.manifestPath, f_tail)
            f_sub = f_r["evidence"].readSubmissionRecords(
                f_r["plan"].scale_points[0], f_ordinal=0
            )
            self.assertEqual(
                f_sub["submission_recorded"].payload["handle"]["job_id"], "9001"
            )
        self.assertEqual(len(f_orch.views), 3)
        self.assertEqual(f_orch.exitCode, 0)

    def testFailedVariantDoesNotFailOtherArms(self) -> None:
        """One failing arm is reported (exit 1) while the other arms of the job still succeed."""
        f_fake_runner = FakeSchedulerCommandRunner()
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_fake_runner,
            f_poll_interval=0.01,
        )
        f_fake_runner.m_on_submit_callback = self._groupOnSubmit(
            f_orch, f_fail_labels=("no-footer",)
        )
        f_fake_runner.m_submit_job_ids = ["9002"]

        f_orch.execute(
            RunRequest(
                "lsmio",
                "variants",
                f_variants=["no-footer", "no-manoff"],
                f_archive=False,
            ),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )
        f_states = {f_r["arm"].label: f_r["view"].state for f_r in f_orch.groupRuns}
        self.assertEqual(f_states["baseline"], OverallRunState.SUCCEEDED)
        self.assertEqual(f_states["no-manoff"], OverallRunState.SUCCEEDED)
        self.assertNotEqual(f_states["no-footer"], OverallRunState.SUCCEEDED)
        self.assertEqual(f_orch.exitCode, 1)

    def testResumptionSkipsExistingArchive(self) -> None:
        """INV-MULTI-3 / INV-PAIR-7: a variant whose :run archive exists is skipped under --resume."""
        from lsmiotool.lib.archive import ArchiveEngine

        with tempfile.TemporaryDirectory() as f_tmpdir:
            f_fake_runner = FakeSchedulerCommandRunner()
            f_reporter = RunReporter()
            f_orch = RunOrchestrator(
                f_profile_resolver=self.m_registry,
                f_command_runner=f_fake_runner,
                f_poll_interval=0.01,
                f_reporter=f_reporter,
            )

            f_arm_id = ArchiveEngine.resolveArmId("NATIVE", "no-footer")
            os.makedirs(os.path.join(f_tmpdir, f"outputs-{f_arm_id}:run"))

            f_view = f_orch.execute(
                RunRequest(
                    "lsmio",
                    "baseline",
                    f_variants=["no-footer"],
                    f_resume=True,
                    f_out_dir=f_tmpdir,
                ),
                f_site=self.m_viking_profile,
                f_worker_executable=self.m_worker_path,
            )

            # Nothing is left to run, so not even the baseline is submitted
            self.assertEqual(len(f_fake_runner.m_submit_calls), 0)
            self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
            self.assertEqual(f_orch.exitCode, 0)
            self.assertTrue(
                any(
                    "[RESUME] Skipping variant 'no-footer'" in f_l
                    for f_l in f_reporter.lines
                )
            )

    def testResumptionRunsOnlyMissingVariants(self) -> None:
        """Under --resume only the variants without a :run archive run, with the baseline."""
        from lsmiotool.lib.archive import ArchiveEngine

        with tempfile.TemporaryDirectory() as f_tmpdir:
            f_fake_runner = FakeSchedulerCommandRunner()
            f_orch = RunOrchestrator(
                f_profile_resolver=self.m_registry,
                f_command_runner=f_fake_runner,
                f_poll_interval=0.01,
            )
            f_fake_runner.m_on_submit_callback = self._groupOnSubmit(f_orch)
            os.makedirs(
                os.path.join(
                    f_tmpdir,
                    f"outputs-{ArchiveEngine.resolveArmId('NATIVE', 'no-footer')}:run",
                )
            )
            with (
                patch("lsmiotool.lib.export.exportPoint"),
                patch("lsmiotool.lib.export.generateReports", return_value=True),
            ):
                f_orch.execute(
                    RunRequest(
                        "lsmio",
                        "variants",
                        f_variants=["no-footer", "no-manoff"],
                        f_resume=True,
                        f_out_dir=f_tmpdir,
                    ),
                    f_site=self.m_viking_profile,
                    f_worker_executable=self.m_worker_path,
                )
            self.assertEqual(
                [f_r["arm"].label for f_r in f_orch.groupRuns],
                ["baseline", "no-manoff"],
            )
            self.assertEqual(len(f_fake_runner.m_submit_calls), 1)
            self.assertEqual(f_orch.exitCode, 0)

    def testAutoArchivePairsRunAndBase(self) -> None:
        """INV-PAIR-2: each variant is archived as outputs-<arm>:run with the baseline as :base."""
        with tempfile.TemporaryDirectory() as f_tmpdir:
            f_fake_runner = FakeSchedulerCommandRunner()
            f_orch = RunOrchestrator(
                f_profile_resolver=self.m_registry,
                f_command_runner=f_fake_runner,
                f_poll_interval=0.01,
            )
            f_fake_runner.m_on_submit_callback = self._groupOnSubmit(f_orch)
            f_fake_runner.m_submit_job_ids = ["9101"]

            with (
                patch("lsmiotool.lib.export.exportPoint") as f_export,
                patch(
                    "lsmiotool.lib.export.generateReports", return_value=True
                ) as f_reports,
            ):
                f_view = f_orch.execute(
                    RunRequest(
                        "lsmio",
                        "baseline",
                        f_variants=["no-footer", "no-manoff"],
                        f_out_dir=f_tmpdir,
                    ),
                    f_site=self.m_viking_profile,
                    f_worker_executable=self.m_worker_path,
                )
            self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
            f_node_dirs = sorted(
                os.path.relpath(f_c.kwargs["f_node_dir"], f_tmpdir)
                for f_c in f_export.call_args_list
            )
            f_nodes = str(f_orch.groupRuns[0]["plan"].scale_points[0].nodes)
            self.assertEqual(
                f_node_dirs,
                sorted(
                    os.path.join(f"outputs-native-{f_v}:{f_role}", f_nodes)
                    for f_v in ("no-footer", "no-manoff")
                    for f_role in ("run", "base")
                ),
            )
            # Baseline output is exported with the baseline's infix
            f_infixes = {
                os.path.basename(os.path.dirname(f_c.kwargs["f_node_dir"])): f_c.kwargs[
                    "f_infix"
                ]
                for f_c in f_export.call_args_list
            }
            self.assertEqual(f_infixes["outputs-native-no-footer:base"], "native")
            self.assertEqual(
                f_infixes["outputs-native-no-footer:run"], "native-no-footer"
            )
            self.assertEqual(f_reports.call_count, 4)
            self.assertEqual(f_orch.exitCode, 0)

    def testVersionedRunsReferenceBaselineFromMainBinary(self) -> None:
        """--versioned: bm_native:main reference (:base) and the current binary per variant
        (:run) in one job, archived as outputs-native-version-<branch>-<hash>-<v>."""
        f_main = os.path.join(self.m_bin_dir, "bm_native:main")
        with open(f_main, "w") as f_f:
            f_f.write("#!/bin/sh\nexit 0\n")
        os.chmod(f_main, 0o755)

        with tempfile.TemporaryDirectory() as f_tmpdir:
            f_fake_runner = FakeSchedulerCommandRunner()
            f_orch = RunOrchestrator(
                f_profile_resolver=self.m_registry,
                f_command_runner=f_fake_runner,
                f_poll_interval=0.01,
            )
            f_fake_runner.m_on_submit_callback = self._groupOnSubmit(f_orch)
            with (
                patch("lsmiotool.lib.export.exportPoint") as f_export,
                patch("lsmiotool.lib.export.generateReports", return_value=True),
            ):
                f_orch.execute(
                    RunRequest(
                        "lsmio",
                        "variants",
                        f_variants=["legacy", "autotune"],
                        f_versioned=True,
                        f_out_dir=f_tmpdir,
                    ),
                    f_site=self.m_viking_profile,
                    f_worker_executable=self.m_worker_path,
                    f_version_tag="tybulut-str-overhead-6eccef7",
                )

            self.assertEqual(len(f_fake_runner.m_submit_calls), 1)
            f_ref = f_orch.groupRuns[0]
            self.assertEqual(f_ref["arm"].label, "reference")
            self.assertEqual(f_ref["plan"].profile.executables.bm_native, f_main)
            with open(f_ref["store"].layout.manifestPath) as f_f:
                self.assertEqual(
                    json.load(f_f)["site"]["executables"]["bm_native"], f_main
                )
            self.assertEqual(
                f_orch.groupRuns[1]["plan"].profile.executables.bm_native,
                self.m_bm_paths["bm_native"],
            )
            f_dirs = sorted(
                os.path.basename(os.path.dirname(f_c.kwargs["f_node_dir"]))
                for f_c in f_export.call_args_list
            )
            self.assertEqual(
                f_dirs,
                sorted(
                    f"outputs-native-version-tybulut-str-overhead-6eccef7-{f_v}:{f_r}"
                    for f_v in ("legacy", "autotune")
                    for f_r in ("run", "base")
                ),
            )
            # The shared job asks for bmtool's versioned walltime (2 + 3 runs * 2h), and
            # every arm's manifest records that, not the arm's own
            f_sp = f_ref["plan"].scale_points[0]
            with open(
                os.path.join(f_ref["store"].layout.pointSchedulerDir(f_sp, 0), "job.sh")
            ) as f_f:
                self.assertIn("--time=08:00:00", f_f.read())
            for f_run in f_orch.groupRuns:
                with open(f_run["store"].layout.manifestPath) as f_f:
                    self.assertEqual(
                        [f_p["walltime"] for f_p in json.load(f_f)["points"]],
                        ["08:00:00"],
                    )
            self.assertEqual(f_orch.exitCode, 0)

    def testVersionedDefaultsToVariantsVersionedArchive(self) -> None:
        """Without --out-dir, a --versioned run archives under lsmio-archive/variants-versioned,
        apart from the variant matrix archive in lsmio-archive/variants."""
        f_main = os.path.join(self.m_bin_dir, "bm_native:main")
        with open(f_main, "w") as f_f:
            f_f.write("#!/bin/sh\nexit 0\n")
        os.chmod(f_main, 0o755)

        f_fake_runner = FakeSchedulerCommandRunner()
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_fake_runner,
            f_poll_interval=0.01,
        )
        f_fake_runner.m_on_submit_callback = self._groupOnSubmit(f_orch)
        with (
            patch("lsmiotool.lib.export.exportPoint") as f_export,
            patch("lsmiotool.lib.export.generateReports", return_value=True),
        ):
            f_orch.execute(
                RunRequest(
                    "lsmio", "variants", f_variants=["legacy"], f_versioned=True
                ),
                f_site=self.m_viking_profile,
                f_worker_executable=self.m_worker_path,
                f_version_tag="b-abc1234",
            )
        f_dest = os.path.join(
            self.m_viking_root_hdd, "lsmio-archive", "variants-versioned"
        )
        self.assertEqual(
            sorted(
                os.path.dirname(f_c.kwargs["f_node_dir"])
                for f_c in f_export.call_args_list
            ),
            sorted(
                os.path.join(f_dest, f"outputs-native-version-b-abc1234-legacy:{f_r}")
                for f_r in ("run", "base")
            ),
        )
        self.assertEqual(f_orch.exitCode, 0)

    def testVersionedResumeChecksVariantsVersioned(self) -> None:
        """--resume of a --versioned run looks for its :run archive in the default
        variants-versioned folder, where the run archives it."""
        f_main = os.path.join(self.m_bin_dir, "bm_native:main")
        with open(f_main, "w") as f_f:
            f_f.write("#!/bin/sh\nexit 0\n")
        os.chmod(f_main, 0o755)
        os.makedirs(
            os.path.join(
                self.m_viking_root_hdd,
                "lsmio-archive",
                "variants-versioned",
                "outputs-native-version-b-abc1234-legacy:run",
            )
        )

        f_fake_runner = FakeSchedulerCommandRunner()
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_fake_runner,
            f_poll_interval=0.01,
        )
        f_view = f_orch.execute(
            RunRequest(
                "lsmio",
                "variants",
                f_variants=["legacy"],
                f_versioned=True,
                f_resume=True,
            ),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
            f_version_tag="b-abc1234",
        )
        self.assertEqual(len(f_fake_runner.m_submit_calls), 0)
        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
        self.assertEqual(f_orch.exitCode, 0)

    def testVersionedRequiresMainBinary(self) -> None:
        """--versioned fails before submitting when bm_native:main is not installed."""
        f_fake_runner = FakeSchedulerCommandRunner()
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry, f_command_runner=f_fake_runner
        )
        with self.assertRaises(PreflightError) as f_ctx:
            f_orch.execute(
                RunRequest("lsmio", "variants", f_versioned=True),
                f_site=self.m_viking_profile,
                f_worker_executable=self.m_worker_path,
                f_version_tag="b-abc1234",
            )
        self.assertIn("install:main", str(f_ctx.exception))
        self.assertEqual(len(f_fake_runner.m_submit_calls), 0)

    def testBackendsRunEveryBackendPerScalePoint(self) -> None:
        """INV-BACKEND-1: one job per scale point runs every backend; each backend's points are
        archived under backends/<scale>/outputs-<arm>/<nodes>."""
        f_lib = os.path.join(self.m_temp_dir, "lib")
        os.makedirs(f_lib, exist_ok=True)
        open(os.path.join(f_lib, "liblsmio_adios.so"), "w").close()

        with tempfile.TemporaryDirectory() as f_tmpdir:
            f_fake_runner = FakeSchedulerCommandRunner()
            f_orch = RunOrchestrator(
                f_profile_resolver=self.m_registry,
                f_command_runner=f_fake_runner,
                f_poll_interval=0.01,
            )
            f_fake_runner.m_on_submit_callback = self._groupOnSubmit(f_orch)
            with (
                patch("lsmiotool.lib.export.exportPoint") as f_export,
                patch("lsmiotool.lib.export.generateReports", return_value=True),
            ):
                f_orch.execute(
                    RunRequest("lsmio", "bake", f_mode="backends", f_out_dir=f_tmpdir),
                    f_site=self.m_viking_profile,
                    f_worker_executable=self.m_worker_path,
                )

            f_runs = f_orch.groupRuns
            self.assertEqual(
                [f_r["arm"].label for f_r in f_runs],
                ["adios2", "native", "plugin", "rocksdb"],
            )
            self.assertEqual(
                [f_r["plan"].request.setup for f_r in f_runs],
                ["ADIOS", "NATIVE", "PLUGIN", "ROCKSDB"],
            )
            f_points = f_runs[0]["plan"].scale_points
            self.assertEqual(len(f_fake_runner.m_submit_calls), len(f_points))
            for f_script in self._submittedScripts(f_fake_runner):
                f_tail = f_script.strip().splitlines()[-1]
                self.assertIn(" allocation-group ", f_tail)
                self.assertIn(" continue ", f_tail)
                for f_r in f_runs:
                    self.assertIn(f_r["store"].layout.manifestPath, f_tail)
            f_dirs = sorted(
                os.path.relpath(f_c.kwargs["f_node_dir"], f_tmpdir)
                for f_c in f_export.call_args_list
            )
            self.assertEqual(
                f_dirs,
                sorted(
                    os.path.join(f"outputs-{f_a}", str(f_sp.nodes))
                    for f_a in ("adios", "native", "plugin", "rocksdb")
                    for f_sp in f_points
                ),
            )
            self.assertEqual(f_orch.exitCode, 0)

    def testBackendsSyncArmsRunAndArchive(self) -> None:
        """The -sync arms run in the backends job like any backend: their sub-requests plan
        with the -SYNC setups and their points are archived as outputs-<backend>-sync/<nodes>."""
        f_lib = os.path.join(self.m_temp_dir, "lib")
        os.makedirs(f_lib, exist_ok=True)
        open(os.path.join(f_lib, "liblsmio_adios.so"), "w").close()

        with tempfile.TemporaryDirectory() as f_tmpdir:
            f_fake_runner = FakeSchedulerCommandRunner()
            f_orch = RunOrchestrator(
                f_profile_resolver=self.m_registry,
                f_command_runner=f_fake_runner,
                f_poll_interval=0.01,
            )
            f_fake_runner.m_on_submit_callback = self._groupOnSubmit(f_orch)
            with (
                patch("lsmiotool.lib.export.exportPoint") as f_export,
                patch("lsmiotool.lib.export.generateReports", return_value=True),
            ):
                f_orch.execute(
                    RunRequest(
                        "lsmio",
                        "bake",
                        f_mode="backends",
                        f_backends=(
                            "adios2",
                            "adios2-sync",
                            "native-sync",
                            "plugin-sync",
                        ),
                        f_out_dir=f_tmpdir,
                    ),
                    f_site=self.m_viking_profile,
                    f_worker_executable=self.m_worker_path,
                )

            f_runs = f_orch.groupRuns
            self.assertEqual(
                [f_r["plan"].request.setup for f_r in f_runs],
                ["ADIOS", "ADIOS-SYNC", "NATIVE-SYNC", "PLUGIN-SYNC"],
            )
            f_points = f_runs[0]["plan"].scale_points
            self.assertEqual(len(f_fake_runner.m_submit_calls), len(f_points))
            self.assertEqual(
                sorted(
                    os.path.relpath(f_c.kwargs["f_node_dir"], f_tmpdir)
                    for f_c in f_export.call_args_list
                ),
                sorted(
                    os.path.join(f"outputs-{f_a}", str(f_sp.nodes))
                    for f_a in ("adios", "adios-sync", "native-sync", "plugin-sync")
                    for f_sp in f_points
                ),
            )
            self.assertEqual(f_orch.exitCode, 0)

    def testBackendsNodesRunOnlyThosePoints(self) -> None:
        """--nodes: an lsmio backends run submits and archives only those points."""
        f_lib = os.path.join(self.m_temp_dir, "lib")
        os.makedirs(f_lib, exist_ok=True)
        open(os.path.join(f_lib, "liblsmio_adios.so"), "w").close()
        with tempfile.TemporaryDirectory() as f_tmpdir:
            f_fake_runner = FakeSchedulerCommandRunner()
            f_orch = RunOrchestrator(
                f_profile_resolver=self.m_registry,
                f_command_runner=f_fake_runner,
                f_poll_interval=0.01,
            )
            f_fake_runner.m_on_submit_callback = self._groupOnSubmit(f_orch)
            with (
                patch("lsmiotool.lib.export.exportPoint") as f_export,
                patch("lsmiotool.lib.export.generateReports", return_value=True),
            ):
                f_orch.execute(
                    RunRequest(
                        "lsmio",
                        "bake",
                        f_mode="backends",
                        f_backends=["native"],
                        f_out_dir=f_tmpdir,
                        f_nodes=[8, 2],
                    ),
                    f_site=self.m_viking_profile,
                    f_worker_executable=self.m_worker_path,
                )
            self.assertEqual(f_orch.exitCode, 0)
            (f_run,) = f_orch.groupRuns
            self.assertEqual(
                [f_sp.nodes for f_sp in f_run["plan"].scale_points], [2, 8]
            )
            self.assertEqual(f_run["plan"].request.nodes, (2, 8))
            self.assertEqual(len(f_fake_runner.m_submit_calls), 2)
            self.assertEqual(
                sorted(
                    os.path.relpath(f_c.kwargs["f_node_dir"], f_tmpdir)
                    for f_c in f_export.call_args_list
                ),
                [
                    os.path.join("outputs-native", "2"),
                    os.path.join("outputs-native", "8"),
                ],
            )

    def testIorNodesArchiveAndResumeOnlyThosePoints(self) -> None:
        """--nodes on 'run ior': only those points run and are archived; with --resume
        an archived one is skipped and the others still run."""
        f_dest = os.path.join(self.m_viking_root_hdd, "lsmio-archive", "ior", "bake")
        f_orch, f_runner, _ = self._iorRun(
            RunRequest(
                "ior", "bake", f_mode="backends", f_backends=["base"], f_nodes=[4]
            )
        )
        self.assertEqual(f_orch.exitCode, 0)
        self.assertEqual(len(f_runner.m_submit_calls), 1)
        self.assertIn("--nodes=4", self._submittedScripts(f_runner)[0])
        f_arm_dir = os.path.join(f_dest, "outputs-ior")
        self.assertEqual([f_n for f_n in os.listdir(f_arm_dir) if f_n.isdigit()], ["4"])
        f_orch, f_runner, _ = self._iorRun(
            RunRequest(
                "ior",
                "bake",
                f_mode="backends",
                f_backends=["base"],
                f_nodes=[2, 4],
                f_resume=True,
            )
        )
        self.assertEqual(f_orch.exitCode, 0)
        self.assertEqual(len(f_runner.m_submit_calls), 1)
        self.assertIn("--nodes=2", self._submittedScripts(f_runner)[0])
        self.assertEqual(
            sorted(f_n for f_n in os.listdir(f_arm_dir) if f_n.isdigit()), ["2", "4"]
        )

    def testIorRunEverySetupPerScalePoint(self) -> None:
        """'run ior <scale>': one job per scale point runs every IOR setup; each setup's
        points are archived like a backend's, as outputs-ior[-<setup>]/<nodes> in
        lsmio-archive/ior/<scale>, with its outputs named by the IOR setup and
        ior-report.csv; --resume skips the archived points."""
        f_dest = os.path.join(self.m_viking_root_hdd, "lsmio-archive", "ior", "bake")
        f_fake_runner = FakeSchedulerCommandRunner()
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_fake_runner,
            f_poll_interval=0.01,
        )
        f_fake_runner.m_on_submit_callback = self._groupOnSubmit(f_orch)

        def fake_export(**f_kw: Any) -> int:
            os.makedirs(f_kw["f_node_dir"], exist_ok=True)
            return 1

        with (
            patch(
                "lsmiotool.lib.export.exportIorPoint", side_effect=fake_export
            ) as f_ior,
            patch("lsmiotool.lib.export.exportPoint") as f_lsmio,
            patch(
                "lsmiotool.lib.export.generateIorReports", return_value=True
            ) as f_rep,
            patch("lsmiotool.lib.export.generateReports") as f_lsm_rep,
        ):
            f_orch.execute(
                RunRequest("ior", "bake", f_mode="backends"),
                f_site=self.m_viking_profile,
                f_worker_executable=self.m_worker_path,
            )
        f_runs = f_orch.groupRuns
        self.assertEqual(
            [(f_r["arm"].label, f_r["plan"].request.setup) for f_r in f_runs],
            [
                ("base", "BASE"),
                ("collective", "COLLECTIVE"),
                ("hdf5", "HDF5"),
                ("hdf5-collective", "HDF5-C"),
            ],
        )
        f_points = f_runs[0]["plan"].scale_points
        self.assertEqual(len(f_fake_runner.m_submit_calls), len(f_points))
        self.assertEqual(f_lsmio.call_count, 0)
        self.assertEqual(f_lsm_rep.call_count, 0)
        self.assertTrue(f_rep.called)
        f_arms = ("ior", "ior-collective", "ior-hdf5", "ior-hdf5-collective")
        self.assertEqual(
            sorted(
                (
                    os.path.relpath(f_c.kwargs["f_node_dir"], f_dest),
                    f_c.kwargs["f_infix"],
                )
                for f_c in f_ior.call_args_list
            ),
            sorted(
                (os.path.join(f"outputs-{f_a}", str(f_sp.nodes)), f_i)
                for f_a, f_i in zip(f_arms, ("base", "collective", "hdf5", "hdf5-c"))
                for f_sp in f_points
            ),
        )
        self.assertEqual(f_orch.exitCode, 0)

        # Every point of the setups is archived: --resume submits nothing
        f_resume_runner = FakeSchedulerCommandRunner()
        f_view = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_resume_runner,
            f_poll_interval=0.01,
        ).execute(
            RunRequest("ior", "bake", f_mode="backends", f_resume=True),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )
        self.assertEqual(len(f_resume_runner.m_submit_calls), 0)
        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)

    def _iorRun(self, f_request: RunRequest, f_site: Optional[Any] = None) -> Any:
        """Run f_request (on f_site, default viking) with a fake worker that writes each
        combination's IOR output and a controller result naming it and the node (as the
        IOR worker does). Returns (orchestrator, scheduler runner, reporter)."""
        from lsmiotool.test.main.ArmGroupTest import IOR_SUMMARY

        def write_ior(
            f_ev: Any,
            f_sp: Any,
            f_plan: Any,
            f_ordinal: int = 0,
            f_failed: bool = False,
        ) -> None:
            f_logs = f_ev.layout.pointLogsDir(f_sp, f_ordinal)
            os.makedirs(f_logs, exist_ok=True)
            for f_combo in f_plan.combinations:
                f_out = os.path.join(f_logs, f"ior_{f_combo.name}.stdout")
                with open(f_out, "w") as f_f:
                    f_f.write(IOR_SUMMARY)
                f_ev.recordControllerResult(
                    f_point=f_sp,
                    f_combination=f_combo,
                    f_payload={
                        "status": "success",
                        "exit_code": 0,
                        "stage": "execution",
                        "output_path": f_out,
                        "host": "node042",
                    },
                    f_ordinal=f_ordinal,
                )

        f_runner = FakeSchedulerCommandRunner()
        f_reporter = RunReporter()
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_runner,
            f_poll_interval=0.01,
            f_reporter=f_reporter,
        )
        f_runner.m_on_submit_callback = self._groupOnSubmit(f_orch)
        with (
            patch.object(self, "_mockWritePointResults", side_effect=write_ior),
            patch("lsmiotool.lib.log.Console.warning"),
        ):
            f_orch.execute(
                f_request,
                f_site=f_site or self.m_viking_profile,
                f_worker_executable=self.m_worker_path,
            )
        return f_orch, f_runner, f_reporter

    def testIorRunOnPbsGetsTheFixedWalltimePerSetup(self) -> None:
        """'run ior' on a PBS site (isambard): one job per scale point gets the fixed
        walltime once per IOR setup (--time is ignored), and is archived as on Slurm."""
        f_orch, f_runner, _ = self._iorRun(
            RunRequest(
                "ior",
                "bake",
                f_mode="backends",
                f_backends=["base", "hdf5", "fsync"],
                f_wallhour=2,
            ),
            f_site=self.m_isambard_profile,
        )
        self.assertEqual(f_orch.exitCode, 0)
        f_points = f_orch.groupRuns[0]["plan"].scale_points
        f_scripts = self._submittedScripts(f_runner)
        self.assertEqual(len(f_scripts), len(f_points))
        for f_script in f_scripts:
            self.assertIn("#PBS -l walltime=18:00:00", f_script)
        f_dest = os.path.join(self.m_isambard_root_hdd, "lsmio-archive", "ior", "bake")
        self.assertEqual(
            sorted(os.listdir(f_dest)),
            ["outputs-ior", "outputs-ior-fsync", "outputs-ior-hdf5"],
        )
        for f_arm in os.listdir(f_dest):
            self.assertTrue(
                os.path.isfile(os.path.join(f_dest, f_arm, "ior-report.csv"))
            )

    def testRunWithTimeRecordsItInTheManifest(self) -> None:
        """--time is kept in each arm's manifest (which must read back) and sets each
        job's Slurm walltime in place of the backends formula."""
        f_orch, f_runner, _ = self._iorRun(
            RunRequest(
                "ior", "bake", f_mode="backends", f_backends=["base"], f_wallhour=3
            )
        )
        self.assertEqual(f_orch.exitCode, 0)
        for f_script in self._submittedScripts(f_runner):
            self.assertIn("#SBATCH --time=03:00:00", f_script)
        with open(
            os.path.join(f_orch.groupRuns[0]["store"].layout.runRoot, "manifest.json")
        ) as f_f:
            self.assertEqual(json.load(f_f)["request"]["wallhour"], 3)

    def testArchiveGroupRunNeverReplacesAnotherRunsIorPoint(self) -> None:
        """Archiving an IOR run after the fact (--no-archive, then 'archive ior --source')
        fills in the missing <nodes> dirs of each setup but never replaces one holding
        another run's results."""
        from lsmiotool.lib.archive import ArchiveEngine

        f_orch, _, _ = self._iorRun(
            RunRequest(
                "ior",
                "bake",
                f_mode="backends",
                f_backends=["base", "hdf5"],
                f_archive=False,
            )
        )
        self.assertEqual(f_orch.exitCode, 0)
        f_nodes = sorted(
            str(f_sp.nodes) for f_sp in f_orch.groupRuns[0]["plan"].scale_points
        )
        f_dest = os.path.join(self.m_temp_dir, "dest")
        f_newer = os.path.join(f_dest, "outputs-ior", f_nodes[0])
        os.makedirs(f_newer)
        ArchiveEngine.writeRunMarker(
            os.path.dirname(f_newer), "run-newer", f_newer, ["00-tasks-1"]
        )
        f_lines: List[str] = []
        f_ok, f_dirs = RunOrchestrator().archiveGroupRun(
            f_orch.groupRuns[0]["store"].layout.runRoot,
            f_dest_root=f_dest,
            f_reporter=f_lines.append,
        )
        self.assertTrue(f_ok)
        self.assertIn(f"Not archived: {f_newer} holds another run's results", f_lines)
        # The other run's point is kept as it was, the rest of each setup archived
        self.assertEqual(os.listdir(f_newer), [])
        for f_arm, f_want in (("ior", f_nodes[1:]), ("ior-hdf5", f_nodes)):
            f_arm_dir = os.path.join(f_dest, f"outputs-{f_arm}")
            self.assertEqual(
                sorted(
                    f_n
                    for f_n in os.listdir(f_arm_dir)
                    if f_n.isdigit() and os.listdir(os.path.join(f_arm_dir, f_n))
                ),
                f_want,
            )
            self.assertFalse(os.path.exists(os.path.join(f_arm_dir, "lsm-report.csv")))
        self.assertTrue(
            os.path.isfile(os.path.join(f_dest, "outputs-ior-hdf5", "ior-report.csv"))
        )

    def testIorRunArchivesRealOutputsAndResumesMissingPoints(self) -> None:
        """'run ior' end to end, nothing mocked in export or reports: bmtool's IOR file
        names and ior-report.csv per setup; --resume reruns only a missing point; an
        unarchived setup is archived with 'archive ior --source <its run root>'."""
        from lsmiotool.lib.main import ArchiveMain

        f_dest = os.path.join(self.m_viking_root_hdd, "lsmio-archive", "ior", "bake")
        f_orch, _, _ = self._iorRun(
            RunRequest(
                "ior", "bake", f_mode="backends", f_backends=["base", "hdf5-collective"]
            )
        )
        self.assertEqual(f_orch.exitCode, 0)
        f_points = f_orch.groupRuns[0]["plan"].scale_points
        f_nodes = sorted(str(f_sp.nodes) for f_sp in f_points)
        for f_arm, f_infix in (("ior", "base"), ("ior-hdf5-collective", "hdf5-c")):
            f_arm_dir = os.path.join(f_dest, f"outputs-{f_arm}")
            self.assertEqual(
                sorted(f_n for f_n in os.listdir(f_arm_dir) if f_n.isdigit()), f_nodes
            )
            (f_day,) = os.listdir(os.path.join(f_arm_dir, f_nodes[0]))
            self.assertEqual(
                sorted(os.listdir(os.path.join(f_arm_dir, f_nodes[0], f_day))),
                sorted(
                    f"out-{f_infix}-{f_c.stripe_count}-{f_c.block_size}-{f_day}-node042-0.txt"
                    for f_c in f_orch.groupRuns[0]["plan"].combinations
                ),
            )
            with open(os.path.join(f_arm_dir, "ior-report.csv")) as f_f:
                f_rows = f_f.read().split()
            self.assertEqual(len(f_rows), 2 * 6 * len(f_points))
            self.assertIn(f"{f_nodes[0]},4,1M,write,1650.38", ",".join(f_rows))
            self.assertFalse(os.path.exists(os.path.join(f_arm_dir, "lsm-report.csv")))

        # --resume: only the point whose archive is missing runs, in one job
        shutil.rmtree(os.path.join(f_dest, "outputs-ior-hdf5-collective", f_nodes[-1]))
        f_orch, f_runner, f_reporter = self._iorRun(
            RunRequest(
                "ior",
                "bake",
                f_mode="backends",
                f_backends=["base", "hdf5-collective"],
                f_resume=True,
            )
        )
        self.assertEqual(f_orch.exitCode, 0)
        self.assertEqual(len(f_runner.m_submit_calls), 1)
        self.assertTrue(
            any("[RESUME] Skipping arm 'base'" in f_l for f_l in f_reporter.lines)
        )
        self.assertTrue(
            os.path.isdir(
                os.path.join(f_dest, "outputs-ior-hdf5-collective", f_nodes[-1])
            )
        )

        # --no-archive, then 'archive ior <scale> --source <its run root>'
        f_orch, _, _ = self._iorRun(
            RunRequest(
                "ior", "bake", f_mode="backends", f_backends=["fsync"], f_archive=False
            )
        )
        self.assertFalse(os.path.exists(os.path.join(f_dest, "outputs-ior-fsync")))
        with patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(
                ArchiveMain(
                    [
                        "ior",
                        "bake",
                        "--source",
                        f_orch.groupRuns[0]["store"].layout.runRoot,
                    ],
                    f_benchmark_root=self.m_viking_root_hdd,
                ).run(),
                0,
            )
        f_fsync = os.path.join(f_dest, "outputs-ior-fsync")
        self.assertEqual(
            sorted(f_n for f_n in os.listdir(f_fsync) if f_n.isdigit()), f_nodes
        )
        self.assertTrue(os.path.isfile(os.path.join(f_fsync, "ior-report.csv")))

    def testBackendsPluginRequiresLibrary(self) -> None:
        """The plugin backend fails preflight when liblsmio_adios is missing."""
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=FakeSchedulerCommandRunner(),
        )
        with self.assertRaises(PreflightError) as f_ctx:
            f_orch.execute(
                RunRequest("lsmio", "local", f_mode="backends"),
                f_site=self.m_viking_profile,
                f_worker_executable=self.m_worker_path,
            )
        self.assertIn("liblsmio_adios", str(f_ctx.exception))

    def testBackendsPluginSyncRequiresLibrary(self) -> None:
        """The plugin-sync backend (the plugin with --lsmio-always-flush) needs liblsmio_adios too."""
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=FakeSchedulerCommandRunner(),
        )
        with self.assertRaises(PreflightError) as f_ctx:
            f_orch.execute(
                RunRequest(
                    "lsmio", "local", f_mode="backends", f_backends=("plugin-sync",)
                ),
                f_site=self.m_viking_profile,
                f_worker_executable=self.m_worker_path,
            )
        self.assertIn("liblsmio_adios", str(f_ctx.exception))
        self.assertIn("plugin-sync", str(f_ctx.exception))

    def testJobFailureKeepsFinishedArms(self) -> None:
        """R1: when the shared job fails (walltime, OOM, node failure), arms that finished
        before it ended still succeed and are archived; only unfinished arms fail."""
        with tempfile.TemporaryDirectory() as f_tmpdir:
            f_fake_runner = FakeSchedulerCommandRunner()
            f_fake_runner.m_job_fail = True
            f_orch = RunOrchestrator(
                f_profile_resolver=self.m_registry,
                f_command_runner=f_fake_runner,
                f_poll_interval=0.01,
            )
            # no-manoff was still running when the job died
            f_fake_runner.m_on_submit_callback = self._groupOnSubmit(
                f_orch, f_missing_labels=("no-manoff",)
            )
            with (
                patch("lsmiotool.lib.export.exportPoint") as f_export,
                patch("lsmiotool.lib.export.generateReports", return_value=True),
            ):
                f_orch.execute(
                    RunRequest(
                        "lsmio",
                        "variants",
                        f_variants=["no-footer", "no-manoff"],
                        f_out_dir=f_tmpdir,
                    ),
                    f_site=self.m_viking_profile,
                    f_worker_executable=self.m_worker_path,
                )
            f_states = {f_r["arm"].label: f_r["view"].state for f_r in f_orch.groupRuns}
            self.assertEqual(f_states["baseline"], OverallRunState.SUCCEEDED)
            self.assertEqual(f_states["no-footer"], OverallRunState.SUCCEEDED)
            self.assertEqual(f_states["no-manoff"], OverallRunState.FAILED)
            f_dirs = sorted(
                os.path.basename(os.path.dirname(f_c.kwargs["f_node_dir"]))
                for f_c in f_export.call_args_list
            )
            self.assertEqual(
                f_dirs,
                ["outputs-native-no-footer:base", "outputs-native-no-footer:run"],
            )
            self.assertEqual(f_orch.exitCode, 1)

    def testInterruptionCancelsAllArmsConsistently(self) -> None:
        """R2: every arm sharing the cancelled job gets the cancellation evidence, so all of
        them reconcile the same way (none INDETERMINATE)."""
        f_runner = FakeSchedulerCommandRunner()
        f_runner.m_active_running_count = 5
        f_sig = SignalCoordinator()
        f_runner.m_on_query_callback = lambda f_cmd: f_sig.trigger(signal.SIGINT)
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_runner,
            f_signal_coordinator=f_sig,
            f_sleep=lambda _: None,
            f_poll_interval=0.01,
        )
        f_orch.execute(
            RunRequest("lsmio", "variants", f_variants=["no-footer", "no-manoff"]),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )
        self.assertEqual(f_orch.exitCode, 130)
        self.assertEqual(len(f_runner.m_cancel_calls), 1)
        f_point_states = set()
        for f_r in f_orch.groupRuns:
            f_sp = f_r["plan"].scale_points[0]
            f_recs = f_r["evidence"].readSubmissionRecords(f_sp, f_ordinal=0)
            self.assertIsNotNone(f_recs.get("cancel_requested"), f_r["arm"].label)
            f_view = StateReconciler.reconcile(f_r["plan"], f_r["evidence"])
            f_point_states.add(f_view.point_states[0].state)
        self.assertEqual(len(f_point_states), 1, f_point_states)
        self.assertNotIn(PointRunState.INDETERMINATE, f_point_states)

    def testFinishedPointsArchivedBeforeInterruption(self) -> None:
        """R3: each point is archived as its job ends, so an interrupt keeps finished points."""
        f_lib = os.path.join(self.m_temp_dir, "lib")
        os.makedirs(f_lib, exist_ok=True)
        open(os.path.join(f_lib, "liblsmio_adios.so"), "w").close()

        with tempfile.TemporaryDirectory() as f_tmpdir:
            f_runner = FakeSchedulerCommandRunner()
            f_sig = SignalCoordinator()
            f_orch = RunOrchestrator(
                f_profile_resolver=self.m_registry,
                f_command_runner=f_runner,
                f_signal_coordinator=f_sig,
                f_sleep=lambda _: None,
                f_poll_interval=0.01,
            )
            f_runner.m_on_submit_callback = self._groupOnSubmit(f_orch)

            def interrupt_second_job(f_cmd: Sequence[str]) -> None:
                if len(f_runner.m_submit_calls) == 2:
                    f_sig.trigger(signal.SIGINT)

            f_runner.m_on_query_callback = interrupt_second_job
            with (
                patch("lsmiotool.lib.export.exportPoint") as f_export,
                patch("lsmiotool.lib.export.generateReports", return_value=True),
            ):
                f_orch.execute(
                    RunRequest(
                        "lsmio",
                        "bake",
                        f_mode="backends",
                        f_backends=["native", "rocksdb"],
                        f_out_dir=f_tmpdir,
                    ),
                    f_site=self.m_viking_profile,
                    f_worker_executable=self.m_worker_path,
                )
            f_first = f_orch.groupRuns[0]["plan"].scale_points[0].nodes
            self.assertEqual(
                sorted(
                    os.path.relpath(f_c.kwargs["f_node_dir"], f_tmpdir)
                    for f_c in f_export.call_args_list
                ),
                sorted(
                    os.path.join(f"outputs-{f_a}", str(f_first))
                    for f_a in ("native", "rocksdb")
                ),
            )
            self.assertEqual(f_orch.exitCode, 130)

    def testResumeDoesNotSkipStandaloneRuns(self) -> None:
        """There is no resume for a standalone (default-only) variants run or a
        versioned run without variants: they rerun and archive to a -N suffix."""
        f_main = os.path.join(self.m_bin_dir, "bm_native:main")
        with open(f_main, "w") as f_f:
            f_f.write("#!/bin/sh\nexit 0\n")
        os.chmod(f_main, 0o755)
        with tempfile.TemporaryDirectory() as f_tmpdir:
            os.makedirs(os.path.join(f_tmpdir, "outputs-native"))
            os.makedirs(os.path.join(f_tmpdir, "outputs-native-version-b-abc1234:run"))
            for f_req in (
                RunRequest(
                    "lsmio",
                    "variants",
                    f_archive=True,
                    f_resume=True,
                    f_out_dir=f_tmpdir,
                ),
                RunRequest(
                    "lsmio",
                    "variants",
                    f_versioned=True,
                    f_resume=True,
                    f_out_dir=f_tmpdir,
                ),
            ):
                f_runner = FakeSchedulerCommandRunner()
                f_orch = RunOrchestrator(
                    f_profile_resolver=self.m_registry,
                    f_command_runner=f_runner,
                    f_poll_interval=0.01,
                )
                f_runner.m_on_submit_callback = self._groupOnSubmit(f_orch)
                with (
                    patch("lsmiotool.lib.export.exportPoint"),
                    patch("lsmiotool.lib.export.generateReports", return_value=True),
                ):
                    f_orch.execute(
                        f_req,
                        f_site=self.m_viking_profile,
                        f_worker_executable=self.m_worker_path,
                        f_version_tag="b-abc1234",
                    )
                self.assertEqual(len(f_runner.m_submit_calls), 1, f_req)

    def testInheritedArchiveDestIsIgnored(self) -> None:
        """An exported BM_ARCHIVE_DEST does not redirect a run's archive;
        only --dest does, so parse/compare find it at the default destination."""
        f_runner = FakeSchedulerCommandRunner()
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_runner,
            f_poll_interval=0.01,
        )
        f_runner.m_on_submit_callback = self._groupOnSubmit(f_orch)
        with (
            patch.dict(os.environ, {"BM_ARCHIVE_DEST": "/inherited/dest"}),
            patch("lsmiotool.lib.export.exportPoint") as f_export,
            patch("lsmiotool.lib.export.generateReports", return_value=True),
        ):
            f_orch.execute(
                RunRequest("lsmio", "variants", f_variants=["no-footer"]),
                f_site=self.m_viking_profile,
                f_worker_executable=self.m_worker_path,
            )
        f_expected_root = os.path.join(
            self.m_viking_profile.benchmark_roots["hdd"], "lsmio-archive", "variants"
        )
        self.assertTrue(f_export.call_args_list)
        for f_c in f_export.call_args_list:
            self.assertTrue(f_c.kwargs["f_node_dir"].startswith(f_expected_root))

    def testGroupRunsAreMarkedForArchive(self) -> None:
        """Arms of a multi-arm run carry an arm marker, their archive dirs a run marker,
        so 'lsmiotool archive' never re-exports a group arm as a standalone run."""
        from lsmiotool.lib.archive import ArchiveEngine
        from lsmiotool.lib.main import ArchiveMain

        def fake_export(**f_kw: Any) -> int:
            os.makedirs(f_kw["f_node_dir"], exist_ok=True)
            return 1

        with tempfile.TemporaryDirectory() as f_tmpdir:
            f_runner = FakeSchedulerCommandRunner()
            f_orch = RunOrchestrator(
                f_profile_resolver=self.m_registry,
                f_command_runner=f_runner,
                f_poll_interval=0.01,
            )
            f_runner.m_on_submit_callback = self._groupOnSubmit(f_orch)
            with (
                patch("lsmiotool.lib.export.exportPoint", side_effect=fake_export),
                patch("lsmiotool.lib.export.generateReports", return_value=True),
            ):
                f_orch.execute(
                    RunRequest(
                        "lsmio",
                        "variants",
                        f_variants=["no-footer"],
                        f_out_dir=f_tmpdir,
                    ),
                    f_site=self.m_viking_profile,
                    f_worker_executable=self.m_worker_path,
                )
            f_base, f_footer = f_orch.groupRuns
            for f_r in (f_base, f_footer):
                f_marker = ArchiveEngine.readArmMarker(f_r["store"].layout.runRoot)
                self.assertEqual(f_marker["group_kind"], "paired")
                self.assertEqual(f_marker["label"], f_r["arm"].label)
            self.assertEqual(
                ArchiveEngine.findArchivedRun(f_tmpdir, f_footer["plan"].run_id),
                os.path.join(f_tmpdir, "outputs-native-no-footer:run"),
            )
            self.assertEqual(
                ArchiveEngine.findArchivedRun(f_tmpdir, f_base["plan"].run_id),
                os.path.join(f_tmpdir, "outputs-native-no-footer:base"),
            )
            f_archive = ArchiveMain(["lsmio", "variants", "--dest", f_tmpdir])
            self.assertIsNone(
                f_archive._latestRunRoot(
                    self.m_viking_profile.benchmark_roots["hdd"], None
                )
            )

    def testArchiveCommandArchivesWhatAGroupRunLeft(self) -> None:
        """'archive --source <arm run root>' archives a group run's finished points
        as :run/:base pairs when the run did not (here --no-archive; likewise a lost
        session or a failed archive step), leaves out an arm that failed, and is idempotent."""
        from lsmiotool.lib.main import ArchiveMain

        def fake_export(**f_kw: Any) -> int:
            os.makedirs(f_kw["f_node_dir"], exist_ok=True)
            return 1

        with tempfile.TemporaryDirectory() as f_dest:
            f_runner = FakeSchedulerCommandRunner()
            f_orch = RunOrchestrator(
                f_profile_resolver=self.m_registry,
                f_command_runner=f_runner,
                f_poll_interval=0.01,
            )
            f_runner.m_on_submit_callback = self._groupOnSubmit(
                f_orch, f_fail_labels=("no-manoff",)
            )
            with patch("lsmiotool.lib.export.exportPoint") as f_export:
                f_orch.execute(
                    RunRequest(
                        "lsmio",
                        "variants",
                        f_variants=["no-footer", "no-manoff"],
                        f_archive=False,
                    ),
                    f_site=self.m_viking_profile,
                    f_worker_executable=self.m_worker_path,
                )
            self.assertEqual(f_export.call_count, 0)
            f_footer_root = f_orch.groupRuns[1]["store"].layout.runRoot

            def archive() -> int:
                with (
                    patch("lsmiotool.lib.export.exportPoint", side_effect=fake_export),
                    patch("lsmiotool.lib.export.generateReports", return_value=True),
                    patch("sys.stdout", new_callable=io.StringIO),
                ):
                    return ArchiveMain(
                        [
                            "lsmio",
                            "variants",
                            "--source",
                            f_footer_root,
                            "--dest",
                            f_dest,
                        ]
                    ).run()

            self.assertEqual(archive(), 0)
            f_pair = ["outputs-native-no-footer:base", "outputs-native-no-footer:run"]
            self.assertEqual(sorted(os.listdir(f_dest)), f_pair)
            # Archived points are not archived again
            self.assertEqual(archive(), 0)
            self.assertEqual(sorted(os.listdir(f_dest)), f_pair)

    def testArchiveGroupRunUsesTheRunsDestinationPerBackendPoint(self) -> None:
        """Without --dest a group run is archived where the run would have archived it
        (recorded in its arm markers): backends/<scale>/outputs-<arm>/<nodes>."""
        f_lib = os.path.join(self.m_temp_dir, "lib")
        os.makedirs(f_lib, exist_ok=True)
        open(os.path.join(f_lib, "liblsmio_adios.so"), "w").close()

        def fake_export(**f_kw: Any) -> int:
            os.makedirs(f_kw["f_node_dir"], exist_ok=True)
            return 1

        f_runner = FakeSchedulerCommandRunner()
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_runner,
            f_poll_interval=0.01,
        )
        f_runner.m_on_submit_callback = self._groupOnSubmit(f_orch)
        f_orch.execute(
            RunRequest("lsmio", "local", f_mode="backends", f_archive=False),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )
        f_dest = os.path.join(
            self.m_viking_root_hdd, "lsmio-archive", "backends", "local"
        )
        self.assertFalse(os.path.exists(f_dest))
        with (
            patch("lsmiotool.lib.export.exportPoint", side_effect=fake_export),
            patch("lsmiotool.lib.export.generateReports", return_value=True),
        ):
            f_ok, f_dirs = RunOrchestrator().archiveGroupRun(
                f_orch.groupRuns[2]["store"].layout.runRoot, f_reporter=lambda f_l: None
            )
            self.assertTrue(f_ok)
            self.assertEqual(
                sorted(f_dirs),
                sorted(
                    os.path.join(f_dest, f"outputs-{f_a}")
                    for f_a in ("adios", "native", "plugin", "rocksdb")
                ),
            )
            for f_a in ("adios", "native", "plugin", "rocksdb"):
                self.assertTrue(
                    os.path.isdir(os.path.join(f_dest, f"outputs-{f_a}", "1"))
                )
            self.assertEqual(
                RunOrchestrator().archiveGroupRun(
                    f_orch.groupRuns[0]["store"].layout.runRoot,
                    f_reporter=lambda f_l: None,
                ),
                (True, []),
            )

    def testRunRecordsItsPidWhileRunningAndArchiveWaitsForIt(self) -> None:
        """Every arm's control dir names the orchestrator while it runs (f_on_ready sees
        it); it is removed at the end; 'archive --source' refuses a run that is live."""
        from lsmiotool.lib.archive import ArchiveError
        from lsmiotool.lib.run import readOrchestratorPid, writeOrchestratorPid

        f_seen: List[Any] = []

        def on_ready(f_roots: List[str]) -> None:
            f_seen.append([readOrchestratorPid(f_r) for f_r in f_roots])

        f_runner = FakeSchedulerCommandRunner()
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_runner,
            f_poll_interval=0.01,
        )
        f_runner.m_on_submit_callback = self._groupOnSubmit(f_orch)
        f_orch.execute(
            RunRequest("lsmio", "variants", f_variants=["no-footer"], f_archive=False),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
            f_on_ready=on_ready,
        )
        self.assertEqual(len(f_seen), 1)
        self.assertEqual([f_d["pid"] for f_d in f_seen[0]], [os.getpid()] * 2)
        f_roots = [f_r["store"].layout.runRoot for f_r in f_orch.groupRuns]
        self.assertEqual([readOrchestratorPid(f_r) for f_r in f_roots], [None, None])

        writeOrchestratorPid(f_roots[:1])
        with self.assertRaises(ArchiveError) as f_ctx:
            RunOrchestrator().archiveGroupRun(f_roots[1], f_reporter=lambda f_l: None)
        self.assertIn("still running", str(f_ctx.exception))

    def testArchiveGroupRunNeedsEveryRankToSucceed(self) -> None:
        """A run with a failed step (any failed rank) stays out of the
        archive: a point is archived only when every rank result succeeded too."""
        f_runner = FakeSchedulerCommandRunner()
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_runner,
            f_poll_interval=0.01,
        )
        f_runner.m_on_submit_callback = self._groupOnSubmit(f_orch)
        f_orch.execute(
            RunRequest("lsmio", "variants", f_variants=["no-footer"], f_archive=False),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )
        f_footer = f_orch.groupRuns[1]
        f_sp = f_footer["plan"].scale_points[0]
        os.remove(
            f_footer["store"].layout.pointRankResultPath(
                f_sp, 1, f_footer["plan"].combinations[2], f_ordinal=0
            )
        )
        f_lines: List[str] = []
        with patch("lsmiotool.lib.export.exportPoint") as f_export:
            f_result = RunOrchestrator().archiveGroupRun(
                f_footer["store"].layout.runRoot, f_reporter=f_lines.append
            )
        self.assertEqual(f_result, (True, []))
        self.assertEqual(f_export.call_count, 0)
        self.assertTrue(
            any(f_l.startswith("Not archived: arm 'no-footer'") for f_l in f_lines)
        )

    def testArchiveGroupRunNeverReplacesAnotherRunsBackendPoint(self) -> None:
        """Archiving a backends run after the fact fills in missing <nodes> dirs but
        never replaces one holding another run's results (only a job replaces, as bmtool)."""
        from lsmiotool.lib.archive import ArchiveEngine

        f_lib = os.path.join(self.m_temp_dir, "lib")
        os.makedirs(f_lib, exist_ok=True)
        open(os.path.join(f_lib, "liblsmio_adios.so"), "w").close()

        def fake_export(**f_kw: Any) -> int:
            os.makedirs(f_kw["f_node_dir"], exist_ok=True)
            return 1

        f_runner = FakeSchedulerCommandRunner()
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_runner,
            f_poll_interval=0.01,
        )
        f_runner.m_on_submit_callback = self._groupOnSubmit(f_orch)
        f_orch.execute(
            RunRequest("lsmio", "local", f_mode="backends", f_archive=False),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )
        f_dest = os.path.join(self.m_temp_dir, "dest")
        f_newer = os.path.join(f_dest, "outputs-native", "1")
        os.makedirs(f_newer)
        ArchiveEngine.writeRunMarker(
            os.path.dirname(f_newer), "run-newer", f_newer, ["00-tasks-1"]
        )
        f_lines: List[str] = []
        with (
            patch(
                "lsmiotool.lib.export.exportPoint", side_effect=fake_export
            ) as f_export,
            patch("lsmiotool.lib.export.generateReports", return_value=True),
        ):
            f_ok, f_dirs = RunOrchestrator().archiveGroupRun(
                f_orch.groupRuns[0]["store"].layout.runRoot,
                f_dest_root=f_dest,
                f_reporter=f_lines.append,
            )
        self.assertTrue(f_ok)
        self.assertEqual(
            sorted(os.path.basename(f_d) for f_d in f_dirs),
            ["outputs-adios", "outputs-plugin", "outputs-rocksdb"],
        )
        self.assertNotIn(
            f_newer, [f_c.kwargs["f_node_dir"] for f_c in f_export.call_args_list]
        )
        self.assertIn(f"Not archived: {f_newer} holds another run's results", f_lines)
        self.assertEqual(
            ArchiveEngine.findArchivedRun(f_dest, "run-newer"),
            os.path.dirname(f_newer),
        )

    def testRunGoesOnAttachedWhenDetachingFails(self) -> None:
        """A failing f_on_ready (e.g. fork or the console log failing) does not abandon the
        allocated run: it warns, goes on attached, and still removes its pid files."""
        from lsmiotool.lib.run import readOrchestratorPid

        def on_ready(f_roots: List[str]) -> None:
            raise OSError("cannot fork")

        f_lines: List[str] = []
        f_runner = FakeSchedulerCommandRunner()
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_runner,
            f_poll_interval=0.01,
        )
        f_runner.m_on_submit_callback = self._groupOnSubmit(f_orch)
        f_orch.execute(
            RunRequest("lsmio", "variants", f_variants=["no-footer"], f_archive=False),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
            f_on_ready=on_ready,
            f_reporter=f_lines.append,
        )
        self.assertEqual(f_orch.exitCode, 0)
        self.assertTrue(
            any("detaching the run failed (cannot fork)" in f_l for f_l in f_lines)
        )
        self.assertEqual(
            [
                readOrchestratorPid(f_r["store"].layout.runRoot)
                for f_r in f_orch.groupRuns
            ],
            [None, None],
        )

    def testArchiveRefusesToMoveAnArchiveOrFailedOutputs(self) -> None:
        """--source must be a run root: an archive dir (run marker), anything inside an
        archive destination and any other non-run-root directory are refused and left
        untouched."""
        from lsmiotool.lib.archive import ArchiveEngine
        from lsmiotool.lib.main import ArchiveMain

        f_root = self.m_viking_root_hdd

        def rankLogs(f_dir: str) -> str:
            os.makedirs(os.path.join(f_dir, "8", "2026-10-10"), exist_ok=True)
            with open(
                os.path.join(f_dir, "8", "2026-10-10", "out-native-4-1M.txt"), "w"
            ) as f_f:
                f_f.write("write,1,1,1,1,1,10\n")
            return f_dir

        f_marked = rankLogs(os.path.join(self.m_temp_dir, "copied-archive"))
        ArchiveEngine.writeRunMarker(f_marked, "run-x", f_marked, ["00-tasks-8"])
        f_cases = [
            f_marked,
            rankLogs(
                os.path.join(
                    f_root, "lsmio-archive", "variants", "outputs-native-no-footer:run"
                )
            ),
            rankLogs(os.path.join(f_root, "lsmio", "outputs-failed", "job-1")),
        ]
        f_dest = os.path.join(self.m_temp_dir, "dest")
        with patch.object(ArchiveMain, "_benchmarkRoot", return_value=f_root):
            for f_src in f_cases:
                with patch("sys.stderr", new_callable=io.StringIO) as f_err:
                    f_rc = ArchiveMain(
                        [
                            "lsmio",
                            "variants",
                            "no-footer",
                            "--source",
                            f_src,
                            "--dest",
                            f_dest,
                        ]
                    ).run()
                self.assertEqual(f_rc, 1, f_src)
                self.assertIn("refusing", f_err.getvalue())
                self.assertTrue(os.path.isdir(os.path.join(f_src, "8")))
            self.assertFalse(os.path.exists(f_dest))

    def testSubmitErrorFailsAllArms(self) -> None:
        """A rejected submission of the shared job fails the whole request."""
        f_fake_runner = FakeSchedulerCommandRunner()
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_fake_runner,
            f_poll_interval=0.01,
        )
        f_fake_runner.m_submit_error = "Slurm sbatch rejection"

        f_view = f_orch.execute(
            RunRequest("lsmio", "baseline", f_variants=["no-footer", "no-manoff"]),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )

        self.assertNotEqual(f_view.state, OverallRunState.SUCCEEDED)
        self.assertEqual(len(f_fake_runner.m_submit_calls), 1)
        self.assertEqual(len(f_orch.views), 3)
        self.assertNotEqual(f_orch.exitCode, 0)

    # ------------------------------------------------------------------
    # execute() preflight, profile resolution and allocation
    # ------------------------------------------------------------------

    def _profileAt(
        self,
        f_label: str,
        f_ssd_root: Optional[str] = None,
        f_executables: Optional[ExecutableRegistry] = None,
    ) -> SiteProfile:
        """The Viking test profile under its own install prefix (and optionally its
        own ssd root and executables), so a resolver's choice shows in the worker path
        it yields."""
        f_base = self.m_viking_profile
        return SiteProfile(
            f_name=f_base.name,
            f_scheduler=f_base.scheduler,
            f_launcher=f_base.launcher,
            f_certification=f_base.certification,
            f_test_only=True,
            f_benchmark_roots={
                "hdd": self.m_viking_root_hdd,
                "ssd": self.m_viking_root_ssd if f_ssd_root is None else f_ssd_root,
            },
            f_install_prefix=self._prefixOf(f_label),
            f_executables=(
                f_executables if f_executables is not None else self.m_executables
            ),
            f_modules=f_base.modules,
            f_resources=f_base.resources,
            f_rank_identity=f_base.rank_identity,
            f_cancellation=f_base.cancellation,
            f_lustre_pools=f_base.lustre_pools,
        )

    def _prefixOf(self, f_label: str) -> str:
        return os.path.join(self.m_temp_dir, f"prefix-{f_label}")

    def _assertNothingAllocated(self, f_profile: Optional[SiteProfile] = None) -> None:
        """No run root under any benchmark root and nothing submitted (preflight failed)."""
        f_prof = f_profile if f_profile is not None else self.m_viking_profile
        for f_root in f_prof.benchmark_roots.values():
            self.assertEqual(os.listdir(f_root), [], f"{f_root} was mutated")
        self.assertEqual(self.m_fake_runner.m_submit_calls, [])

    def _probeResolution(
        self, f_resolver: Any, f_site: Any, f_test_mode: bool = True
    ) -> Any:
        """Run execute() with a worker validator that stops the run right after profile
        resolution. Returns (install prefix of the resolved profile, None) when
        resolution succeeded, or (None, error text) when it failed."""
        f_seen: List[str] = []

        def validator(f_path: str) -> str:
            f_seen.append(f_path)
            raise RuntimeError("stop after resolution")

        f_orch = RunOrchestrator(
            f_profile_resolver=f_resolver,
            f_worker_validator=validator,
            f_command_runner=self.m_fake_runner,
        )
        with self.assertRaises(PreflightError) as f_ctx:
            f_orch.execute(
                RunRequest("ior", "local"),
                f_site=f_site,
                f_user=self.m_test_user,
                f_home=self.m_test_home,
                f_test_mode=f_test_mode,
            )
        self._assertNothingAllocated()
        if f_seen:
            self.assertEqual(len(f_seen), 1)
            self.assertEqual(
                str(f_ctx.exception),
                f"Worker executable validation failed for '{f_seen[0]}': "
                "stop after resolution",
            )
            return os.path.dirname(os.path.dirname(f_seen[0])), None
        return None, str(f_ctx.exception)

    def _executePreflight(
        self,
        f_request: Any,
        f_site: Optional[SiteProfile] = None,
        f_worker_validator: Any = None,
        f_planner: Any = None,
        **f_kwargs: Any,
    ) -> str:
        """execute() that must fail preflight: returns the PreflightError text."""
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
            f_worker_validator=f_worker_validator,
            f_planner=f_planner,
        )
        f_kwargs.setdefault("f_worker_executable", self.m_worker_path)
        with self.assertRaises(PreflightError) as f_ctx:
            f_orch.execute(
                f_request,
                f_site=f_site if f_site is not None else self.m_viking_profile,
                **f_kwargs,
            )
        return str(f_ctx.exception)

    # ------------------------------------------------------------------ C1

    def testExecuteRejectsANonRequest(self) -> None:
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry, f_command_runner=self.m_fake_runner
        )
        with self.assertRaises(PreflightError) as f_ctx:
            f_orch.execute("not a request", f_site=self.m_viking_profile)
        self.assertEqual(str(f_ctx.exception), "f_request must be RunRequest, got: str")
        self._assertNothingAllocated()

    def testExplicitSiteNameResolverShapes(self) -> None:
        f_calls: List[Any] = []

        def resolve_no_env_file(
            f_name: str, f_user: Optional[str] = None, f_home: Optional[str] = None
        ) -> SiteProfile:
            f_calls.append(("resolveProfile", f_name, f_user, f_home))
            return self._profileAt("a")

        def resolve_with_env_file(
            f_name: str,
            f_user: Optional[str] = None,
            f_home: Optional[str] = None,
            f_env_file: Optional[str] = None,
        ) -> SiteProfile:
            f_calls.append(("resolveProfile", f_name, f_user, f_home, f_env_file))
            return self._profileAt("b")

        def get_profile(f_name: str) -> SiteProfile:
            f_calls.append(("getProfile", f_name))
            return self._profileAt("c")

        def call_resolver(f_name: str) -> SiteProfile:
            f_calls.append(("call", f_name))
            return self._profileAt("d")

        f_home = self.m_test_home
        f_rows = [
            (
                "resolveProfile that does not take f_env_file is retried without it",
                SimpleNamespace(resolveProfile=resolve_no_env_file),
                "a",
                [("resolveProfile", "VIKING", "alice", f_home)],
            ),
            (
                "resolveProfile that takes f_env_file gets None without a layout",
                SimpleNamespace(resolveProfile=resolve_with_env_file),
                "b",
                [("resolveProfile", "VIKING", "alice", f_home, None)],
            ),
            (
                "getProfile only",
                SimpleNamespace(getProfile=get_profile),
                "c",
                [("getProfile", "VIKING")],
            ),
            ("a plain callable", call_resolver, "d", [("call", "VIKING")]),
        ]
        for f_label, f_resolver, f_expected, f_expected_calls in f_rows:
            with self.subTest(f_label):
                f_calls.clear()
                f_prefix, f_error = self._probeResolution(f_resolver, "VIKING")
                self.assertIsNone(f_error)
                self.assertEqual(f_prefix, self._prefixOf(f_expected))
                self.assertEqual(f_calls, f_expected_calls)

    def testExplicitSiteNameResolutionFailures(self) -> None:
        def raising_get_profile(f_name: str) -> SiteProfile:
            raise SiteResolutionError(f"no such site {f_name}")

        f_rows = [
            (
                "an object that is no resolver",
                SimpleNamespace(),
                "VIKING",
                "Failed to resolve site profile 'VIKING': Unsupported profile resolver",
            ),
            (
                "a resolver that raises",
                SimpleNamespace(getProfile=raising_get_profile),
                "VIKING",
                "Failed to resolve site profile 'VIKING': no such site VIKING",
            ),
            (
                "a callable that yields nothing",
                lambda f_name: None,
                "VIKING",
                "Resolved profile is not a SiteProfile, got: None",
            ),
            (
                "a callable that yields a name",
                lambda f_name: "VIKING",
                "VIKING",
                "Resolved profile is not a SiteProfile, got: str",
            ),
            (
                "no resolver and an unknown name",
                None,
                "NOSUCHSITE",
                "Failed to resolve site profile 'NOSUCHSITE'",
            ),
        ]
        for f_label, f_resolver, f_site, f_fragment in f_rows:
            with self.subTest(f_label):
                f_prefix, f_error = self._probeResolution(f_resolver, f_site)
                self.assertIsNone(f_prefix)
                self.assertIn(f_fragment, f_error)

        with self.subTest("a site that is neither a name nor a profile"):
            f_prefix, f_error = self._probeResolution(None, 42)
            self.assertIsNone(f_prefix)
            self.assertEqual(f_error, "Invalid f_site argument: 42")

    def testDetectedSiteResolverShapes(self) -> None:
        f_calls: List[Any] = []
        f_home = self.m_test_home

        def detect_profile(f_test_mode: bool = False) -> SiteProfile:
            f_calls.append(("detect", f_test_mode))
            return self._profileAt("a")

        def detect_name(f_test_mode: bool = False) -> str:
            f_calls.append(("detect", f_test_mode))
            return "SITE9"

        def resolve_no_env_file(
            f_name: str, f_user: Optional[str] = None, f_home: Optional[str] = None
        ) -> SiteProfile:
            f_calls.append(("resolveProfile", f_name, f_user, f_home))
            return self._profileAt("b")

        def get_profile(f_name: str) -> SiteProfile:
            f_calls.append(("getProfile", f_name))
            return self._profileAt("c")

        class DetectingCallable:
            """A resolver that detects and is also callable."""

            def __init__(self, f_profile: SiteProfile) -> None:
                self.m_profile = f_profile

            def detect(self, f_test_mode: bool = False) -> str:
                f_calls.append(("detect", f_test_mode))
                return "SITE9"

            def __call__(self, f_name: str) -> SiteProfile:
                f_calls.append(("call", f_name))
                return self.m_profile

        def profile_callable(f_name: Optional[str]) -> SiteProfile:
            f_calls.append(("call", f_name))
            return self._profileAt("f")

        def name_then_profile_callable(f_name: Optional[str]) -> Any:
            f_calls.append(("call", f_name))
            return "SITE9" if f_name is None else self._profileAt("e")

        f_rows = [
            (
                "detect yields a profile, used as it is",
                SimpleNamespace(detect=detect_profile),
                "a",
                [("detect", True)],
            ),
            (
                "detect yields a name, resolveProfile without f_env_file",
                SimpleNamespace(detect=detect_name, resolveProfile=resolve_no_env_file),
                "b",
                [("detect", True), ("resolveProfile", "SITE9", "alice", f_home)],
            ),
            (
                "detect yields a name, getProfile",
                SimpleNamespace(detect=detect_name, getProfile=get_profile),
                "c",
                [("detect", True), ("getProfile", "SITE9")],
            ),
            (
                "detect yields a name, the resolver is also a callable",
                DetectingCallable(self._profileAt("d")),
                "d",
                [("detect", True), ("call", "SITE9")],
            ),
            (
                "a callable yields a profile",
                profile_callable,
                "f",
                [("call", None)],
            ),
            (
                "a callable yields a name that the callable then resolves",
                name_then_profile_callable,
                "e",
                [("call", None), ("call", "SITE9")],
            ),
        ]
        for f_label, f_resolver, f_expected, f_expected_calls in f_rows:
            with self.subTest(f_label):
                f_calls.clear()
                f_prefix, f_error = self._probeResolution(f_resolver, None)
                self.assertIsNone(f_error)
                self.assertEqual(f_prefix, self._prefixOf(f_expected))
                self.assertEqual(f_calls, f_expected_calls)

    def testDetectionFallsBackToTheEnvironmentResolver(self) -> None:
        f_calls: List[Any] = []

        # A resolver with resolveProfile only: the detection is the environment's, with
        # the test mode passed through, and the name goes to the resolver
        def resolve(
            f_name: str, f_user: Optional[str] = None, f_home: Optional[str] = None
        ) -> SiteProfile:
            f_calls.append(("resolveProfile", f_name))
            return self._profileAt("a")

        for f_mode in (True, False):
            with self.subTest(f"resolveProfile-only resolver, test mode {f_mode}"):
                f_calls.clear()
                with patch.object(
                    EnvironmentResolver, "detect", return_value="SITE9"
                ) as f_detect:
                    f_prefix, f_error = self._probeResolution(
                        SimpleNamespace(resolveProfile=resolve),
                        None,
                        f_test_mode=f_mode,
                    )
                self.assertIsNone(f_error)
                self.assertEqual(f_prefix, self._prefixOf("a"))
                f_detect.assert_called_once_with(f_test_mode=f_mode)
                self.assertEqual(f_calls, [("resolveProfile", "SITE9")])

        # A resolver that only detects: the name goes to the environment resolver, with
        # the user, the home and the profile file authority (none here)
        with self.subTest("detect-only resolver"):
            with patch.object(
                EnvironmentResolver,
                "resolveProfile",
                return_value=self._profileAt("b"),
            ) as f_resolve:
                f_prefix, f_error = self._probeResolution(
                    SimpleNamespace(detect=lambda f_test_mode=False: "SITE9"), None
                )
            self.assertIsNone(f_error)
            self.assertEqual(f_prefix, self._prefixOf("b"))
            f_resolve.assert_called_once_with(
                "SITE9",
                f_user=self.m_test_user,
                f_home=self.m_test_home,
                f_env_file=None,
            )

        with self.subTest("the environment resolver yields nothing"):
            with patch.object(EnvironmentResolver, "resolveProfile", return_value=None):
                f_prefix, f_error = self._probeResolution(
                    SimpleNamespace(detect=lambda f_test_mode=False: "SITE9"), None
                )
            self.assertIsNone(f_prefix)
            self.assertEqual(f_error, "Resolved profile is not a SiteProfile, got: None")

    def testDetectionFailures(self) -> None:
        def detect_raises(f_test_mode: bool = False) -> str:
            raise SiteResolutionError("no site here")

        def get_raises(f_name: str) -> SiteProfile:
            raise SiteResolutionError(f"cannot load {f_name}")

        f_rows = [
            (
                "detect yields another type",
                SimpleNamespace(detect=lambda f_test_mode=False: 42),
                "Failed to detect site profile: Resolver detect returned unexpected type: int",
            ),
            (
                "a callable yields another type",
                lambda f_name: 42,
                "Failed to detect site profile: Resolver callable returned unexpected type: int",
            ),
            (
                "an object that is no resolver",
                SimpleNamespace(),
                "Failed to detect site profile: Unsupported profile resolver",
            ),
            (
                "detect raises",
                SimpleNamespace(detect=detect_raises),
                "Failed to detect site profile: no site here",
            ),
            (
                "the detected name cannot be resolved",
                SimpleNamespace(
                    detect=lambda f_test_mode=False: "SITE9", getProfile=get_raises
                ),
                "Failed to resolve detected site profile 'SITE9': cannot load SITE9",
            ),
        ]
        for f_label, f_resolver, f_fragment in f_rows:
            with self.subTest(f_label):
                f_prefix, f_error = self._probeResolution(f_resolver, None)
                self.assertIsNone(f_prefix)
                self.assertIn(f_fragment, f_error)

    # ------------------------------------------------------------------ C2

    def testNonSlurmSitesRunWithoutAnyCredentials(self) -> None:
        """The credential stage cannot fail a PBS or fake-scheduler site: with
        SB_ACCOUNT and SB_EMAIL unset the real validateCredentials(None, None) returns,
        and execute() allocates a run and submits a script with no Slurm credentials."""
        f_base_dev = self.m_registry.getProfile("DEV")
        f_dev_root = os.path.join(self.m_temp_dir, "dev_root")
        os.makedirs(f_dev_root, exist_ok=True)
        f_dev_profile = SiteProfile(
            f_name=f_base_dev.name,
            f_scheduler=f_base_dev.scheduler,
            f_launcher=f_base_dev.launcher,
            f_certification=f_base_dev.certification,
            f_test_only=True,
            f_benchmark_roots={"hdd": f_dev_root, "ssd": f_dev_root},
            f_install_prefix=self.m_temp_dir,
            f_executables=self.m_executables,
            f_modules=f_base_dev.modules,
            f_resources=f_base_dev.resources,
            f_rank_identity=f_base_dev.rank_identity,
            f_cancellation=f_base_dev.cancellation,
            f_lustre_pools=f_base_dev.lustre_pools,
        )
        self.assertEqual(f_dev_profile.scheduler, SchedulerKind.FAKE)
        for f_profile in (self.m_isambard_profile, f_dev_profile):
            with self.subTest(site=f_profile.name):
                self.assertNotEqual(f_profile.scheduler, SchedulerKind.SLURM)
                # The real check returns for no credentials at all
                self.assertIsNone(f_profile.validateCredentials(None, None))
                f_runner = FakeSchedulerCommandRunner()
                f_orch = RunOrchestrator(
                    f_profile_resolver=self.m_registry,
                    f_command_runner=f_runner,
                    f_poll_interval=0.01,
                    f_environ={},
                )

                def on_submit(f_jid: str, f_cwd: Optional[str]) -> None:
                    self._mockWritePointResults(
                        f_orch.last_evidence_store,
                        f_orch.last_plan.scale_points[0],
                        f_orch.last_plan,
                        f_ordinal=0,
                    )

                f_runner.m_on_submit_callback = on_submit
                f_view = f_orch.execute(
                    RunRequest("ior", "local"),
                    f_site=f_profile,
                    f_worker_executable=self.m_worker_path,
                    f_environ={},
                )
                self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
                f_layout = f_orch.last_artifact_store.layout
                self.assertTrue(os.path.isdir(f_layout.runRoot))
                f_script = os.path.join(
                    f_layout.pointSchedulerDir(f_orch.last_plan.scale_points[0], 0),
                    "job.sh",
                )
                with open(f_script, "r", encoding="utf-8") as f_f:
                    f_text = f_f.read()
                for f_forbidden in ("#SBATCH", "--account", "--mail-user"):
                    self.assertNotIn(f_forbidden, f_text)

    def testLsmioEnvSetupIsRejected(self) -> None:
        f_error = self._executePreflight(RunRequest("lsmio", "small", f_setup="ENV"))
        self.assertEqual(
            f_error,
            "LSMIO setup 'ENV' is a diagnostic mode and cannot be used as a run "
            "benchmark setup",
        )
        self._assertNothingAllocated()

    def testRelocationFailureIsAPreflightError(self) -> None:
        with patch(
            "lsmiotool.lib.relocate.relocateForSite",
            side_effect=RelocationError("work root is under a home prefix"),
        ) as f_relocate:
            f_error = self._executePreflight(RunRequest("ior", "local"))
        self.assertEqual(f_error, "work root is under a home prefix")
        f_relocate.assert_called_once()
        f_args = f_relocate.call_args[0]
        self.assertIs(f_args[0], self.m_viking_profile)
        self.assertEqual(f_args[1], self.m_worker_path)
        self._assertNothingAllocated()

    def testWorkerValidatorThatIsNoValidatorIsRejected(self) -> None:
        f_validator = SimpleNamespace(marker=1)
        f_error = self._executePreflight(
            RunRequest("ior", "local"), f_worker_validator=f_validator
        )
        self.assertEqual(
            f_error,
            f"Worker executable validation failed for '{self.m_worker_path}': "
            f"Unsupported worker validator: {f_validator!r}",
        )
        self._assertNothingAllocated()

    def testBenchmarkExecutableWithALoneSurrogateIsAPreflightError(self) -> None:
        """A benchmark path holding a lone surrogate (an environments.json "\\ud800"
        escape gives one, and ExecutableRegistry accepts it as absolute) makes os.lstat
        raise UnicodeEncodeError, which validateBenchmarkExecutable does not catch. This
        pins that current behaviour: the function leaks the UnicodeEncodeError, and
        execute() turns it into a PreflightError that keeps it as the cause."""
        f_bad_path = "/opt/\ud800/bm_native"
        f_executables = ExecutableRegistry(
            {
                "ior": f_bad_path,
                "lmp": self.m_lmp_path,
                "bm_native": self.m_bm_paths["bm_native"],
                "bm_adios": self.m_bm_paths["bm_adios"],
                "bm_rocksdb": self.m_bm_paths["bm_rocksdb"],
                "bm_leveldb": self.m_bm_paths["bm_leveldb"],
                "bm_manager": self.m_bm_paths["bm_manager"],
            }
        )
        f_profile = self._profileAt("a", f_executables=f_executables)
        self.assertEqual(f_profile.executables.ior, f_bad_path)

        # The function itself: not a PreflightError
        with self.assertRaises(UnicodeEncodeError) as f_direct:
            validateBenchmarkExecutable(f_bad_path)
        self.assertNotIsInstance(f_direct.exception, PreflightError)

        # Its caller: a PreflightError that chains the real error, with nothing mutated
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry, f_command_runner=self.m_fake_runner
        )
        with self.assertRaises(PreflightError) as f_ctx:
            f_orch.execute(
                RunRequest("ior", "local"),
                f_site=f_profile,
                f_worker_executable=self.m_worker_path,
            )
        self.assertIsInstance(f_ctx.exception.__cause__, UnicodeEncodeError)
        self.assertEqual(
            str(f_ctx.exception),
            f"Benchmark executable validation failed for '{f_bad_path}': "
            f"{f_ctx.exception.__cause__}",
        )
        self._assertNothingAllocated(f_profile)

    # ------------------------------------------------------------------ C3

    def testLmpAssetRootComesFromTheRuntimeLayout(self) -> None:
        f_layout_assets = os.path.join(self.m_temp_dir, "layout-assets")
        f_layout = RuntimeLayout(
            f_execution_mode=ExecutionMode.SOURCE,
            f_package_root=os.path.join(self.m_temp_dir, "pkg"),
            f_profile_file=self.m_default_profile_path,
            f_asset_root=f_layout_assets,
            f_worker_executable=self.m_worker_path,
            f_version_file=os.path.join(self.m_temp_dir, "VERSION"),
        )
        # The profile's own asset root exists and is complete; the layout's does not
        self.assertTrue(os.path.isdir(self.m_lmp_assets_dir))
        f_error = self._executePreflight(
            RunRequest("lmp", "small", f_setup="LSMIO"),
            f_runtime_layout=f_layout,
        )
        self.assertIn(
            f"LMP asset validation failed for asset root '{f_layout_assets}'", f_error
        )
        self._assertNothingAllocated()

    def testArmErrorIsAPreflightError(self) -> None:
        f_error = self._executePreflight(
            RunRequest("ior", "local", f_mode="backends", f_backends=["base", "ior"])
        )
        self.assertEqual(f_error, "IOR setup listed twice: [ior]")
        self._assertNothingAllocated()

    def testResourcesPlanFailures(self) -> None:
        f_rows = [
            (
                "a plan validation error keeps its text",
                PlanValidationError("walltime does not fit"),
                "walltime does not fit",
            ),
            (
                "any other error is wrapped",
                ValueError("planner broke"),
                "Plan creation failed: planner broke",
            ),
        ]
        for f_label, f_raised, f_expected in f_rows:
            with self.subTest(f_label):
                f_planner = _FailingPlanner(1, f_raised)
                f_error = self._executePreflight(
                    RunRequest("ior", "local"), f_planner=f_planner
                )
                self.assertEqual(f_error, f_expected)
                self.assertEqual(f_planner.m_calls, 1)
                self._assertNothingAllocated()

    # ------------------------------------------------------------------ C4

    def testArmPlanFailureAfterTheResourcesPlan(self) -> None:
        f_rows = [
            (
                "a plan validation error keeps its text",
                PlanValidationError("arm does not fit"),
                "arm does not fit",
            ),
            (
                "any other error is wrapped",
                ValueError("arm planner broke"),
                "Plan creation failed: arm planner broke",
            ),
        ]
        for f_label, f_raised, f_expected in f_rows:
            with self.subTest(f_label):
                f_planner = _FailingPlanner(2, f_raised)
                f_error = self._executePreflight(
                    RunRequest("ior", "local"), f_planner=f_planner
                )
                self.assertEqual(f_error, f_expected)
                # The resources plan was made, then the arm's plan failed
                self.assertEqual(f_planner.m_calls, 2)
                self._assertNothingAllocated()

    def testControlLockFailuresAfterAllocation(self) -> None:
        f_rows = [
            (
                "another orchestrator holds the lock",
                LockContentionError("held by pid 77"),
                "Control lock contention on run 'run-lock-1': held by pid 77",
            ),
            (
                "the lock cannot be opened",
                ArtifactError("cannot open the lock file"),
                "Failed to acquire control lock on run 'run-lock-1': "
                "cannot open the lock file",
            ),
        ]
        for f_label, f_raised, f_expected in f_rows:
            with self.subTest(f_label):
                f_lock = _FailingLock(f_raised)
                f_reporter = _IdentityFailingReporter()
                f_orch = RunOrchestrator(
                    f_profile_resolver=self.m_registry,
                    f_command_runner=self.m_fake_runner,
                    f_run_id_source=lambda: "run-lock-1",
                    f_artifact_store_factory=lambda f_root, f_rid: _LockFailingStore(
                        f_root, f_rid, f_lock
                    ),
                    f_reporter=f_reporter,
                )
                with self.assertRaises(OrchestrationError) as f_ctx:
                    f_orch.execute(
                        RunRequest("ior", "local"),
                        f_site=self.m_viking_profile,
                        f_worker_executable=self.m_worker_path,
                    )
                self.assertNotIsInstance(f_ctx.exception, PreflightError)
                self.assertEqual(str(f_ctx.exception), f_expected)
                self.assertEqual(f_lock.m_acquires, 1)
                f_store = f_orch.last_artifact_store
                # The run root was allocated, and the failing identity report did not
                # stop the run before the lock was taken
                self.assertTrue(os.path.isdir(f_store.layout.runRoot))
                self.assertEqual(
                    f_reporter.m_identity_calls,
                    [("run-lock-1", f_store.layout.runRoot)],
                )
                self.assertEqual(self.m_fake_runner.m_submit_calls, [])
                shutil.rmtree(f_store.layout.runRoot)

    def testSecondArmAllocationFailureReleasesTheFirstArmsLock(self) -> None:
        f_rows = [
            ("the first lock releases cleanly", None),
            ("the first lock's release raises", RuntimeError("release failed")),
        ]
        for f_label, f_release_error in f_rows:
            with self.subTest(f_label):
                f_stores: List[Any] = []
                f_events: List[str] = []
                f_real_locks: List[Any] = []

                def factory(f_root: str, f_rid: str) -> Any:
                    if not f_stores:
                        f_store: Any = _ArmStore(
                            f_root, f_rid, f_events, f_real_locks, f_release_error
                        )
                    else:
                        f_store = _ArmStore(
                            f_root,
                            f_rid,
                            f_events,
                            f_real_locks,
                            None,
                            f_allocate_error=ArtifactError("disk full"),
                        )
                    f_stores.append(f_store)
                    return f_store

                f_orch = RunOrchestrator(
                    f_profile_resolver=self.m_registry,
                    f_command_runner=self.m_fake_runner,
                    f_artifact_store_factory=factory,
                )
                with self.assertRaises(OrchestrationError) as f_ctx:
                    f_orch.execute(
                        RunRequest(
                            "lsmio",
                            "baseline",
                            f_variants=["no-footer", "no-manoff"],
                            f_archive=False,
                        ),
                        f_site=self.m_viking_profile,
                        f_worker_executable=self.m_worker_path,
                    )
                self.assertEqual(
                    str(f_ctx.exception), "Failed to allocate run: disk full"
                )
                self.assertEqual(len(f_stores), 2)
                # Only the first arm held a lock: it was taken and then released, and the
                # real lock is no longer held
                self.assertEqual(f_events, ["acquire", "release"])
                self.assertEqual(len(f_real_locks), 1)
                self.assertFalse(f_real_locks[0].is_locked)
                self.assertTrue(os.path.isdir(f_stores[0].layout.runRoot))
                self.assertEqual(self.m_fake_runner.m_submit_calls, [])
                for f_store in f_stores:
                    shutil.rmtree(f_store.layout.runRoot, ignore_errors=True)

    def testUnwritableArmMarkerIsReportedAndTheRunGoesOn(self) -> None:
        f_lines: List[str] = []
        f_sig = SignalCoordinator()
        f_sig.trigger(signal.SIGINT)
        f_stores: List[Any] = []

        def factory(f_root: str, f_rid: str) -> Any:
            f_store = _MarkerBlockingStore(f_root, f_rid)
            f_stores.append(f_store)
            return f_store

        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
            f_artifact_store_factory=factory,
            f_signal_coordinator=f_sig,
            f_reporter=RunReporter(f_callback=f_lines.append),
        )
        f_view = f_orch.execute(
            RunRequest(
                "lsmio",
                "baseline",
                f_variants=["no-footer", "no-manoff"],
                f_archive=False,
            ),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )
        # The run went on to its (latched) interruption: no arm started
        self.assertEqual(f_view.state, OverallRunState.NOT_STARTED)
        self.assertEqual(
            [f_v.state for f_v in f_orch.views], [OverallRunState.NOT_STARTED] * 3
        )
        self.assertEqual(f_orch.exitCode, 130)
        self.assertEqual(self.m_fake_runner.m_submit_calls, [])
        self.assertEqual(len(f_stores), 3)
        for f_store in f_stores:
            f_run_id = f_store.layout.runId
            f_warnings = [
                f_l
                for f_l in f_lines
                if f_l.startswith(
                    f"WARNING: cannot write the arm marker of {f_run_id}:"
                )
            ]
            self.assertEqual(len(f_warnings), 1, f_lines)
            # The blocked marker path is still the directory that blocked it
            self.assertTrue(
                os.path.isdir(
                    os.path.join(f_store.layout.runRoot, ".lsmiotool-arm.json")
                )
            )

    def testEveryArmNamesThisProcessAndHostWhileTheRunIsLive(self) -> None:
        """While a multi-arm run is live, each arm's control dir holds a pid file naming
        this process and this host; the files are gone when the run ends."""
        f_seen: List[Any] = []

        def on_ready(f_roots: List[str]) -> None:
            f_seen.append(
                [
                    (
                        f_root,
                        readOrchestratorPid(f_root),
                        os.listdir(os.path.join(f_root, "control")),
                    )
                    for f_root in f_roots
                ]
            )

        f_runner = FakeSchedulerCommandRunner()
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_runner,
            f_poll_interval=0.01,
        )
        f_runner.m_on_submit_callback = self._groupOnSubmit(f_orch)
        f_orch.execute(
            RunRequest(
                "lsmio",
                "baseline",
                f_variants=["no-footer", "no-manoff"],
                f_archive=False,
            ),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
            f_on_ready=on_ready,
        )
        self.assertEqual(len(f_seen), 1)
        self.assertEqual(len(f_seen[0]), 3)
        f_roots = [f_r["store"].layout.runRoot for f_r in f_orch.groupRuns]
        self.assertEqual([f_s[0] for f_s in f_seen[0]], f_roots)
        for f_root, f_doc, f_names in f_seen[0]:
            self.assertEqual(f_doc["pid"], os.getpid(), f_root)
            self.assertEqual(f_doc["host"], socket.gethostname(), f_root)
            self.assertIn(ORCHESTRATOR_PID_FILE, f_names)
        for f_root in f_roots:
            self.assertIsNone(readOrchestratorPid(f_root))
            self.assertFalse(os.path.exists(orchestratorPidPath(f_root)))

    # ------------------------------------------------------------------ D1/D2/D3
    # The single-run loop, the arm-group loop and the archive step

    def _hookedFactory(self, f_adapters: List[Any], **f_hooks: Any) -> Any:
        """A scheduler adapter factory (the injection contract of D3) whose adapters are
        a real Slurm adapter behind _HookedAdapter; f_adapters collects them."""

        def factory(
            f_profile: Any, f_evidence: Any, f_validator: Any, f_runner: Any
        ) -> Any:
            f_adapter = _HookedAdapter(
                SlurmSchedulerAdapter(
                    f_evidence_store=f_evidence,
                    f_worker_validator=f_validator,
                    f_command_runner=f_runner,
                ),
                **f_hooks,
            )
            f_adapters.append(f_adapter)
            return f_adapter

        return factory

    def _resultsOnSubmit(self, f_orch: RunOrchestrator, f_runner: Any) -> None:
        """Make each submitted job of a single run write its point's results (the worker)."""

        def on_submit(f_jid: str, f_cwd: Optional[str]) -> None:
            f_idx = len(f_runner.m_submit_calls) - 1
            self._mockWritePointResults(
                f_orch.last_evidence_store,
                f_orch.last_plan.scale_points[f_idx],
                f_orch.last_plan,
                f_ordinal=f_idx,
            )

        f_runner.m_on_submit_callback = on_submit

    def _executeSingle(
        self, f_orch: RunOrchestrator, f_request: Any = None, **f_kwargs: Any
    ) -> Any:
        return f_orch.execute(
            f_request if f_request is not None else RunRequest("ior", "local"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
            **f_kwargs,
        )

    def _installPluginAndReference(self) -> None:
        """What backends and versioned arms need at preflight: the ADIOS2 plugin library
        and the bm_native:main reference executable."""
        f_lib = os.path.join(self.m_temp_dir, "lib")
        os.makedirs(f_lib, exist_ok=True)
        open(os.path.join(f_lib, "liblsmio_adios.so"), "w").close()
        f_main = os.path.join(self.m_bin_dir, "bm_native:main")
        with open(f_main, "w") as f_f:
            f_f.write("#!/bin/sh\nexit 0\n")
        os.chmod(f_main, 0o755)

    def _controlKinds(self, f_orch: RunOrchestrator) -> List[Any]:
        return [
            f_e.evidence_kind
            for f_e in f_orch.last_evidence_store.readControlEvents("control")
        ]

    def testSingleRunUsesTheInjectedAdapterFactory(self) -> None:
        f_adapters: List[Any] = []
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
            f_poll_interval=0.01,
            f_scheduler_adapter_factory=self._hookedFactory(f_adapters),
        )
        self._resultsOnSubmit(f_orch, self.m_fake_runner)
        f_view = self._executeSingle(f_orch)
        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
        # The loop got its adapter from the factory, built on the run's own evidence
        # store, and submitted through it
        self.assertEqual(len(f_adapters), 1)
        f_inner = f_adapters[0].m_inner
        self.assertIs(f_inner.m_evidence_store, f_orch.last_evidence_store)
        self.assertIs(f_inner.m_command_runner, self.m_fake_runner)
        self.assertEqual(f_adapters[0].m_dispatches, 1)
        self.assertEqual(len(self.m_fake_runner.m_submit_calls), 1)

    def testInterruptionBeforeTheLoopSurvivesAFailingCompletionReport(self) -> None:
        f_sig = SignalCoordinator()
        f_sig.trigger(signal.SIGINT)
        f_reporter = _HookReporter(f_failing=("reportCompletion",))
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
            f_signal_coordinator=f_sig,
            f_reporter=f_reporter,
        )
        f_view = self._executeSingle(f_orch)
        self.assertEqual(f_view.state, OverallRunState.INTERRUPTED)
        self.assertEqual(f_orch.exitCode, 130)
        self.assertEqual(self.m_fake_runner.m_submit_calls, [])
        # The report was attempted, with the interrupted state, and its failure ignored
        self.assertEqual(
            [f_c[0] for f_c in f_reporter.m_calls if f_c[0] == "reportCompletion"],
            ["reportCompletion"],
        )
        self.assertEqual(
            self._controlKinds(f_orch), [EvidenceKind.INTERRUPTED]
        )

    def testInterruptionAtTheTopOfTheSecondPointKeepsTheFirst(self) -> None:
        f_sig = _InterruptedAfterReads(self.m_fake_runner, 4)
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
            f_poll_interval=0.01,
            f_signal_coordinator=f_sig,
        )
        self._resultsOnSubmit(f_orch, self.m_fake_runner)
        # A signal that arrives after the first point's last check and before the
        # second point's first one: no hook runs between those two reads (D5), so the
        # coordinator turns interrupted on the read that counts
        f_view = self._executeSingle(f_orch, RunRequest("ior", "bake"))
        self.assertEqual(f_view.state, OverallRunState.INTERRUPTED)
        self.assertEqual(f_orch.exitCode, 130)
        self.assertEqual(len(self.m_fake_runner.m_submit_calls), 1)
        self.assertEqual(
            [f_p.state for f_p in f_view.point_states],
            [
                PointRunState.SUCCEEDED,
                PointRunState.NOT_STARTED,
                PointRunState.NOT_STARTED,
                PointRunState.NOT_STARTED,
            ],
        )
        self.assertEqual(self._controlKinds(f_orch), [EvidenceKind.INTERRUPTED])

    def testInterruptionBetweenTheSpecAndTheDispatchSubmitsNothing(self) -> None:
        f_sig = SignalCoordinator()
        f_adapters: List[Any] = []
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
            f_signal_coordinator=f_sig,
            f_scheduler_adapter_factory=self._hookedFactory(
                f_adapters, f_on_render=lambda: f_sig.trigger(signal.SIGINT)
            ),
        )
        f_view = self._executeSingle(f_orch)
        self.assertEqual(f_view.state, OverallRunState.INTERRUPTED)
        self.assertEqual(f_orch.exitCode, 130)
        # The script was rendered, then the run stopped before the dispatch
        self.assertEqual(f_adapters[0].m_renders, 1)
        self.assertEqual(f_adapters[0].m_dispatches, 0)
        self.assertEqual(self.m_fake_runner.m_submit_calls, [])
        self.assertEqual(self._controlKinds(f_orch), [EvidenceKind.INTERRUPTED])

    def testFailingSubmissionReportDoesNotStopASingleRun(self) -> None:
        f_reporter = _HookReporter(f_failing=("reportPointSubmission",))
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
            f_poll_interval=0.01,
            f_reporter=f_reporter,
        )
        self.m_fake_runner.m_submit_job_ids = ["9301"]
        self._resultsOnSubmit(f_orch, self.m_fake_runner)
        f_view = self._executeSingle(f_orch)
        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
        f_submissions = [f_c for f_c in f_reporter.m_calls if f_c[0] == "reportPointSubmission"]
        self.assertEqual(len(f_submissions), 1)
        self.assertEqual(f_submissions[0][1][2], "9301")
        self.assertEqual(f_orch.exitCode, 0)

    def _interruptedInDispatch(
        self,
        f_on_dispatch: Any,
        f_runner: Optional[FakeSchedulerCommandRunner] = None,
        f_reporter: Optional[RunReporter] = None,
        f_hidden: Sequence[str] = (),
        f_sig: Optional[SignalCoordinator] = None,
        f_token: Optional[str] = None,
    ) -> Any:
        """Single run whose dispatch (a hook on a real Slurm adapter) is where the
        interruption arrives. Returns (orchestrator, view, runner)."""
        f_signal = f_sig if f_sig is not None else SignalCoordinator()
        f_runner_used = f_runner if f_runner is not None else self.m_fake_runner
        f_hook = (
            None
            if f_on_dispatch is None
            else lambda f_inner, f_kw: f_on_dispatch(f_signal, f_inner, f_kw)
        )
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_runner_used,
            f_poll_interval=0.01,
            f_signal_coordinator=f_signal,
            f_reporter=f_reporter,
            f_token_source=(lambda: f_token) if f_token else None,
            f_scheduler_adapter_factory=self._hookedFactory(
                [], f_on_dispatch=f_hook, f_hidden=f_hidden
            ),
        )
        f_view = self._executeSingle(f_orch)
        return f_orch, f_view, f_runner_used

    def testInterruptedDispatchWithoutAJobHandleCancelsNothing(self) -> None:
        def lost(f_sig: Any, f_inner: Any, f_kw: Any) -> Any:
            f_sig.trigger(signal.SIGINT)
            # A result that carries no handle: nothing to report and nothing to cancel
            return SimpleNamespace(job_handle=None)

        f_orch, f_view, f_runner = self._interruptedInDispatch(lost)
        self.assertEqual(f_view.state, OverallRunState.INTERRUPTED)
        self.assertEqual(f_orch.exitCode, 130)
        self.assertEqual(f_runner.m_submit_calls, [])
        self.assertEqual(f_runner.m_cancel_calls, [])
        self.assertEqual(self._controlKinds(f_orch), [EvidenceKind.INTERRUPTED])

    def testInterruptedFailedDispatchRecoversTheJobHandleFromTheEvidence(self) -> None:
        def raise_after(f_sig: Any, f_inner: Any, f_kw: Any) -> Any:
            f_sig.trigger(signal.SIGINT)
            raise SubmissionDispatchError("reply lost")

        def submit_then_raise(f_sig: Any, f_inner: Any, f_kw: Any) -> Any:
            f_inner.dispatchSubmission(**f_kw)
            return raise_after(f_sig, f_inner, f_kw)

        def record_without_handle(f_sig: Any, f_inner: Any, f_kw: Any) -> Any:
            f_ev = f_inner.m_evidence_store
            f_ev.recordRecord(
                os.path.join(
                    f_ev.m_layout.pointSchedulerDir(
                        f_kw["f_point"], f_kw["f_ordinal"]
                    ),
                    "submission_recorded.json",
                ),
                EvidenceRecord(
                    f_writer_kind=WriterKind.CONTROL,
                    f_writer_id="control",
                    f_sequence_number=3,
                    f_evidence_kind=EvidenceKind.SUBMISSION_RECORDED,
                    f_payload={"note": "no handle"},
                    f_run_id=f_ev.m_layout.runId,
                    f_point_id=f_ev.m_layout.pointDirName(
                        f_kw["f_point"], f_kw["f_ordinal"]
                    ),
                ),
            )
            return raise_after(f_sig, f_inner, f_kw)

        def corrupt_the_record(f_sig: Any, f_inner: Any, f_kw: Any) -> Any:
            f_ev = f_inner.m_evidence_store
            f_path = os.path.join(
                f_ev.m_layout.pointSchedulerDir(f_kw["f_point"], f_kw["f_ordinal"]),
                "submission_recorded.json",
            )
            with open(f_path, "w", encoding="utf-8") as f_f:
                f_f.write("{ torn write")
            return raise_after(f_sig, f_inner, f_kw)

        # Rows: (label, dispatch hook, hidden adapter attributes, expected cancel ids)
        f_rows = [
            ("nothing recorded: no job to cancel", raise_after, (), []),
            (
                "a recorded handle is rebuilt and cancelled",
                submit_then_raise,
                (),
                ["9101"],
            ),
            ("a record without a handle dict", record_without_handle, (), []),
            ("a record that cannot be read", corrupt_the_record, (), []),
        ]
        for f_label, f_hook, f_hidden, f_cancelled in f_rows:
            with self.subTest(f_label):
                f_runner = FakeSchedulerCommandRunner()
                f_runner.m_submit_job_ids = ["9101"]
                f_orch, f_view, _ = self._interruptedInDispatch(
                    f_hook, f_runner=f_runner, f_hidden=f_hidden
                )
                self.assertEqual(f_orch.exitCode, 130)
                self.assertEqual(
                    [f_c[-1] for f_c in f_runner.m_cancel_calls], f_cancelled
                )
                self.assertEqual(
                    [os.path.basename(f_c[0]) for f_c in f_runner.m_cancel_calls],
                    ["scancel"] * len(f_cancelled),
                )

    def testInterruptedAfterAnUnansweredSubmitRecoversTheJobByItsToken(self) -> None:
        f_token = "lm-0123456789abcdef01234567"

        class LostReplyRunner(FakeSchedulerCommandRunner):
            """sbatch is interrupted after the scheduler took the job: it exits non-zero."""

            def __init__(self, f_sig: SignalCoordinator) -> None:
                super().__init__()
                self.m_sig = f_sig

            def run(self, f_argv: Sequence[str], *f_args: Any, **f_kw: Any) -> Any:
                if os.path.basename(f_argv[0]) == "sbatch":
                    self.m_calls.append(list(f_argv))
                    self.m_sig.trigger(signal.SIGINT)
                    return ProcessResult(130, "", "sbatch: interrupted\n", 0.01)
                return super().run(f_argv, *f_args, **f_kw)

        # (label, scheduler job ids found under the token, reporter, hidden attributes)
        f_rows = [
            ("recovered and reported", ["9202"], _HookReporter(), ()),
            (
                "the report of the recovered job fails",
                ["9202"],
                _HookReporter(f_failing=("reportPointSubmission",)),
                (),
            ),
            ("recovered with no reporter", ["9202"], None, ()),
            ("the scheduler knows no such job", [], _HookReporter(), ()),
            (
                "an adapter that cannot recover",
                ["9202"],
                _HookReporter(),
                ("recoverJobHandle",),
            ),
        ]
        for f_label, f_ids, f_reporter, f_hidden in f_rows:
            with self.subTest(f_label):
                f_sig = SignalCoordinator()
                f_runner = LostReplyRunner(f_sig)
                f_runner.m_recovery_candidates[f_token] = list(f_ids)
                f_orch, f_view, _ = self._interruptedInDispatch(
                    None,
                    f_runner=f_runner,
                    f_reporter=f_reporter,
                    f_hidden=f_hidden,
                    f_sig=f_sig,
                    f_token=f_token,
                )
                self.assertEqual(f_orch.exitCode, 130)
                f_ev = f_orch.last_evidence_store
                f_sp = f_orch.last_plan.scale_points[0]
                f_records = f_ev.readSubmissionRecords(f_sp, f_ordinal=0)
                self.assertIsNotNone(f_records["submission_dispatched"])
                f_recovered = bool(f_ids) and "recoverJobHandle" not in f_hidden
                if f_recovered:
                    f_payload = f_records["submission_recorded"].payload
                    self.assertTrue(f_payload["recovered"])
                    self.assertEqual(f_payload["handle"]["job_id"], "9202")
                    self.assertEqual(
                        [f_c[-1] for f_c in f_runner.m_cancel_calls], ["9202"]
                    )
                else:
                    self.assertIsNone(f_records["submission_recorded"])
                    self.assertEqual(f_runner.m_cancel_calls, [])
                if f_reporter is not None:
                    f_reported = [
                        f_c for f_c in f_reporter.m_calls
                        if f_c[0] == "reportPointSubmission"
                    ]
                    self.assertEqual(
                        [f_c[1][2] for f_c in f_reported],
                        ["9202"] if f_recovered else [],
                    )

    def testObservationsContinueAfterTheOnesAlreadyOnDisk(self) -> None:
        def seed_one_observation(f_inner: Any, f_kw: Any) -> Any:
            f_result = f_inner.dispatchSubmission(**f_kw)
            f_inner.m_evidence_store.recordSchedulerObservation(
                f_point=f_kw["f_point"],
                f_writer_id="control",
                f_sequence=1,
                f_payload={
                    "handle": f_result.job_handle.toDict(),
                    "state": "queued",
                    "status": "queued",
                    "exit_code": None,
                },
                f_ordinal=f_kw["f_ordinal"],
            )
            return f_result

        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
            f_poll_interval=0.01,
            f_scheduler_adapter_factory=self._hookedFactory(
                [], f_on_dispatch=seed_one_observation
            ),
        )
        self._resultsOnSubmit(f_orch, self.m_fake_runner)
        f_view = self._executeSingle(f_orch)
        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
        f_obs = f_orch.last_evidence_store.readSchedulerObservations(
            f_orch.last_plan.scale_points[0], "control", f_ordinal=0
        )
        # The seeded observation is first; the loop's own continue at the next number
        self.assertEqual([f_o.sequence_number for f_o in f_obs][:2], [1, 2])
        self.assertEqual(f_obs[0].payload["state"], "queued")
        self.assertNotEqual(f_obs[1].payload["state"], "queued")

    def testAnEarlierInterruptionEventKeepsTheWholeRunSuccessUnrecorded(self) -> None:
        def seed_interruption(f_inner: Any, f_kw: Any) -> Any:
            f_result = f_inner.dispatchSubmission(**f_kw)
            f_inner.m_evidence_store.recordInterruption(
                f_writer_id="control",
                f_sequence=1,
                f_payload={"signal": 2, "signal_name": "SIGINT", "exit_code": 130},
            )
            return f_result

        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
            f_poll_interval=0.01,
            f_scheduler_adapter_factory=self._hookedFactory(
                [], f_on_dispatch=seed_interruption
            ),
        )
        self._resultsOnSubmit(f_orch, self.m_fake_runner)
        self._executeSingle(f_orch)
        # The coordinator itself was never interrupted, yet the evidence holds an
        # interruption, so the run is not recorded as a success
        self.assertFalse(f_orch.isInterrupted)
        self.assertNotIn(
            EvidenceKind.WHOLE_RUN_SUCCEEDED, self._controlKinds(f_orch)
        )

    def testFailedWholeRunRecordIsReconciledAnyway(self) -> None:
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
            f_poll_interval=0.01,
        )
        self._resultsOnSubmit(f_orch, self.m_fake_runner)
        # The disk fills up while the whole-run record is written (a real OSError)
        with patch.object(
            EvidenceStore,
            "recordWholeRunSucceeded",
            side_effect=OSError(errno.ENOSPC, "No space left on device"),
        ) as f_record:
            f_view = self._executeSingle(f_orch)
        f_record.assert_called_once()
        self.assertNotIn(
            EvidenceKind.WHOLE_RUN_SUCCEEDED, self._controlKinds(f_orch)
        )
        self.assertEqual(
            [f_p.state for f_p in f_view.point_states], [PointRunState.SUCCEEDED]
        )
        self.assertIs(f_view, f_orch.last_view)

    def testFailingCompletionReportDoesNotChangeTheOutcome(self) -> None:
        f_reporter = _HookReporter(f_failing=("reportCompletion",))
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
            f_poll_interval=0.01,
            f_reporter=f_reporter,
        )
        self._resultsOnSubmit(f_orch, self.m_fake_runner)
        f_view = self._executeSingle(f_orch)
        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
        self.assertEqual(f_orch.exitCode, 0)
        f_calls = [f_c for f_c in f_reporter.m_calls if f_c[0] == "reportCompletion"]
        self.assertEqual(len(f_calls), 1)
        self.assertEqual(f_calls[0][1][0], OverallRunState.SUCCEEDED)

    # ------------------------------------------------------------------ D2

    def _groupOrch(
        self,
        f_reporter: Optional[RunReporter] = None,
        f_fail_labels: Sequence[str] = (),
        **f_kwargs: Any,
    ) -> RunOrchestrator:
        """An orchestrator whose submitted jobs write results for every arm (the worker)."""
        f_runner = f_kwargs.pop("f_command_runner", self.m_fake_runner)
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_runner,
            f_poll_interval=0.01,
            f_reporter=f_reporter,
            **f_kwargs,
        )
        f_runner.m_on_submit_callback = self._groupOnSubmit(
            f_orch, f_fail_labels=f_fail_labels
        )
        return f_orch

    @staticmethod
    def _pairedRequest(**f_kwargs: Any) -> RunRequest:
        f_kwargs.setdefault("f_archive", False)
        return RunRequest("lsmio", "baseline", f_variants=["no-footer"], **f_kwargs)

    def testArmGroupSubmissionFailuresAreReportedAndStopTheGroup(self) -> None:
        def no_handle(f_inner: Any, f_kw: Any) -> Any:
            # A dispatch result that carries no job handle
            return SimpleNamespace(job_handle=None)

        # Rows: (label, adapter factory hook or None, scheduler refuses, reason)
        f_rows = [
            (
                "a dispatch without a handle",
                no_handle,
                False,
                "Submission returned no job handle",
            ),
            (
                "the scheduler refuses the submission",
                None,
                True,
                "Scheduler submission failed with return code 1: "
                "sbatch: error: Invalid partition",
            ),
        ]
        for f_label, f_hook, f_refuse, f_reason in f_rows:
            with self.subTest(f_label):
                f_runner = FakeSchedulerCommandRunner()
                f_runner.m_submit_fail = f_refuse
                f_reporter = _HookReporter()
                f_kwargs: Dict[str, Any] = {}
                if f_hook is not None:
                    f_kwargs["f_scheduler_adapter_factory"] = self._hookedFactory(
                        [], f_on_dispatch=f_hook
                    )
                f_orch = self._groupOrch(
                    f_reporter, f_command_runner=f_runner, **f_kwargs
                )
                self._executeSingle(f_orch, self._pairedRequest())
                f_lines = [
                    f_l
                    for f_l in f_reporter.lines
                    if f_l.startswith("Submission failed for point ")
                ]
                self.assertEqual(len(f_lines), 1, f_reporter.lines)
                self.assertTrue(f_lines[0].endswith(f": {f_reason}"), f_lines[0])
                # The group stops: one refused submit at most, no job, and every arm is
                # reported as not having succeeded
                self.assertEqual(len(f_runner.m_submit_calls), 1 if f_refuse else 0)
                self.assertEqual(len(f_orch.views), 2)
                for f_view in f_orch.views:
                    self.assertNotEqual(f_view.state, OverallRunState.SUCCEEDED)
                self.assertEqual(f_orch.exitCode, 1)

    def testFailingSubmissionReportDoesNotStopAnArmGroup(self) -> None:
        f_reporter = _HookReporter(f_failing=("reportPointSubmission",))
        f_orch = self._groupOrch(f_reporter)
        self.m_fake_runner.m_submit_job_ids = ["9401"]
        f_view = self._executeSingle(f_orch, self._pairedRequest())
        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
        f_calls = [f_c for f_c in f_reporter.m_calls if f_c[0] == "reportPointSubmission"]
        self.assertEqual([f_c[1][2] for f_c in f_calls], ["9401"])
        self.assertEqual(f_orch.exitCode, 0)

    def testFailingProgressReportDoesNotChangeAnArmGroupOutcome(self) -> None:
        f_reporter = _HookReporter(f_failing=("reportProgress",))
        f_orch = self._groupOrch(f_reporter)
        f_view = self._executeSingle(f_orch, self._pairedRequest())
        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
        # Each arm's closing line was attempted, and its failure ignored
        f_arm_lines = [
            f_c[1][0]
            for f_c in f_reporter.m_calls
            if f_c[0] == "reportProgress" and f_c[1][0].startswith("Arm ")
        ]
        self.assertEqual(
            f_arm_lines, ["Arm baseline: SUCCEEDED", "Arm no-footer: SUCCEEDED"]
        )
        self.assertEqual(f_orch.exitCode, 0)

    def testFailingLockReleasesDoNotChangeAnArmGroupOutcome(self) -> None:
        f_events: List[str] = []
        f_real_locks: List[Any] = []
        f_orch = self._groupOrch(
            f_artifact_store_factory=lambda f_root, f_rid: _ArmStore(
                f_root, f_rid, f_events, f_real_locks, RuntimeError("release failed")
            )
        )
        f_view = self._executeSingle(f_orch, self._pairedRequest())
        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
        # Both arms took their lock and tried to release it; the real locks are free
        self.assertEqual(f_events, ["acquire"] * 2 + ["release"] * 2)
        self.assertEqual([f_l.is_locked for f_l in f_real_locks], [False, False])
        self.assertEqual(f_orch.exitCode, 0)

    def testFailedWholeRunRecordInAnArmGroupIsReconciledAnyway(self) -> None:
        f_orch = self._groupOrch()
        # The disk fills up while a whole-run record is written (a real OSError)
        with patch.object(
            EvidenceStore,
            "recordWholeRunSucceeded",
            side_effect=OSError(errno.ENOSPC, "No space left on device"),
        ) as f_record:
            self._executeSingle(f_orch, self._pairedRequest())
        self.assertEqual(f_record.call_count, 2)
        for f_run in f_orch.groupRuns:
            f_kinds = [
                f_e.evidence_kind
                for f_e in f_run["evidence"].readControlEvents("control")
            ]
            self.assertNotIn(EvidenceKind.WHOLE_RUN_SUCCEEDED, f_kinds)
            self.assertEqual(
                [f_p.state for f_p in f_run["view"].point_states],
                [PointRunState.SUCCEEDED],
            )

    # ------------------------------------------------------------------ D3

    def _archiveDirs(self, f_dest: str) -> List[str]:
        return sorted(os.listdir(f_dest))

    def testFailedPairedArchiveStepFailsTheRun(self) -> None:
        f_reporter = _HookReporter()
        f_orch = self._groupOrch(f_reporter)
        with tempfile.TemporaryDirectory() as f_dest:
            # The export fails like a full disk would
            with patch(
                "lsmiotool.lib.export.exportPoint",
                side_effect=OSError(errno.ENOSPC, "No space left on device"),
            ):
                f_view = self._executeSingle(
                    f_orch, self._pairedRequest(f_archive=True, f_out_dir=f_dest)
                )
            self.assertIn(
                "ERROR: archiving arm 'no-footer' failed: "
                "[Errno 28] No space left on device",
                f_reporter.lines,
            )
            # Nothing was archived, but both arms ran: the failed archive fails the run
            self.assertEqual(
                [f_v.state for f_v in f_orch.views],
                [OverallRunState.SUCCEEDED, OverallRunState.SUCCEEDED],
            )
            self.assertEqual(f_orch.exitCode, 1)
            self.assertFalse(
                [f_d for f_d in os.listdir(f_dest) if f_d.startswith("outputs-")
                 and os.path.exists(os.path.join(f_dest, f_d, ".lsmiotool-run.json"))]
            )

    def testPairedArchiveWarnsWhenTheReportsHaveNoRowsOrFail(self) -> None:
        # (label, generateReports patch arguments, warning prefix, warning suffix)
        f_rows = [
            ("no rows", {"return_value": False}, "WARNING: no lsm-report.csv rows for ", ""),
            (
                "the report generator fails",
                {"side_effect": OSError("cannot read the result files")},
                "WARNING: report generation failed for ",
                ": cannot read the result files",
            ),
        ]
        for f_label, f_patch, f_prefix, f_suffix in f_rows:
            with self.subTest(f_label):
                f_reporter = _HookReporter()
                f_orch = self._groupOrch(f_reporter)
                with tempfile.TemporaryDirectory() as f_dest:
                    with (
                        patch(
                            "lsmiotool.lib.export.exportPoint",
                            side_effect=_exportCreatingNodeDir,
                        ),
                        patch("lsmiotool.lib.export.generateReports", **f_patch),
                    ):
                        f_view = self._executeSingle(
                            f_orch,
                            self._pairedRequest(f_archive=True, f_out_dir=f_dest),
                        )
                    f_run_dir = os.path.join(f_dest, "outputs-native-no-footer:run")
                    f_base_dir = os.path.join(f_dest, "outputs-native-no-footer:base")
                    for f_dir in (f_run_dir, f_base_dir):
                        self.assertIn(f"{f_prefix}{f_dir}{f_suffix}", f_reporter.lines)
                    # A warning does not fail the run, and the points are archived
                    self.assertIn(
                        f"Archived: {f_run_dir} and {f_base_dir}", f_reporter.lines
                    )
                self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
                self.assertEqual(f_orch.exitCode, 0)

    def testBackendsArchiveSkipsFailedArmsAndReportsFailedExports(self) -> None:
        def export_or_fail(**f_kw: Any) -> int:
            if f_kw["f_infix"] == "rocksdb":
                raise OSError(errno.EIO, "Input/output error")
            return _exportCreatingNodeDir(**f_kw)

        self._installPluginAndReference()
        f_reporter = _HookReporter()
        f_orch = self._groupOrch(f_reporter, f_fail_labels=("native",))
        with tempfile.TemporaryDirectory() as f_dest:
            with (
                patch("lsmiotool.lib.export.exportPoint", side_effect=export_or_fail),
                patch("lsmiotool.lib.export.generateReports", return_value=True),
            ):
                self._executeSingle(
                    f_orch,
                    RunRequest("lsmio", "local", f_mode="backends", f_out_dir=f_dest),
                )
            f_text = "\n".join(f_reporter.lines)
            # The failed arm is skipped without a word; the failing export is reported
            self.assertNotIn("outputs-native", f_text)
            self.assertIn("ERROR: archiving arm 'rocksdb' failed: ", f_text)
            self.assertIn(f"Archived: {os.path.join(f_dest, 'outputs-adios')}", f_text)
            self.assertIn(f"Archived: {os.path.join(f_dest, 'outputs-plugin')}", f_text)
            self.assertEqual(
                [f_d for f_d in self._archiveDirs(f_dest) if f_d.startswith("outputs-")],
                ["outputs-adios", "outputs-plugin"],
            )
            self.assertEqual(f_orch.exitCode, 1)

    def testSingleRunArchiveExportsItsPointsOrFailsTheRun(self) -> None:
        # (label, exportPoint patch arguments, expected exit code)
        f_rows = [
            ("the archive succeeds", {"side_effect": _exportCreatingNodeDir}, 0),
            (
                "the export fails",
                {"side_effect": OSError(errno.EIO, "Input/output error")},
                1,
            ),
        ]
        for f_label, f_patch, f_exit in f_rows:
            with self.subTest(f_label):
                f_reporter = _HookReporter()
                f_runner = FakeSchedulerCommandRunner()
                f_orch = RunOrchestrator(
                    f_profile_resolver=self.m_registry,
                    f_command_runner=f_runner,
                    f_poll_interval=0.01,
                    f_reporter=f_reporter,
                )
                self._resultsOnSubmit(f_orch, f_runner)
                with tempfile.TemporaryDirectory() as f_dest:
                    with (
                        patch("lsmiotool.lib.export.exportPoint", **f_patch),
                        patch("lsmiotool.lib.export.generateReports", return_value=True),
                    ):
                        f_view = self._executeSingle(
                            f_orch,
                            RunRequest(
                                "lsmio", "variants", f_archive=True, f_out_dir=f_dest
                            ),
                        )
                    f_dir = os.path.join(f_dest, "outputs-native")
                    self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
                    self.assertEqual(f_orch.exitCode, f_exit)
                    if f_exit == 0:
                        self.assertIn(f"Archived: {f_dir}", f_reporter.lines)
                        self.assertTrue(os.path.isdir(os.path.join(f_dir, "8")))
                        with open(
                            os.path.join(f_dir, ".lsmiotool-run.json"),
                            "r",
                            encoding="utf-8",
                        ) as f_f:
                            f_marker = json.load(f_f)
                        self.assertEqual(f_marker["run_id"], f_orch.last_plan.run_id)
                        self.assertEqual(
                            f_marker["points"],
                            [
                                f_orch.last_artifact_store.layout.pointDirName(
                                    f_orch.last_plan.scale_points[0], 0
                                )
                            ],
                        )
                    else:
                        self.assertIn(
                            "ERROR: archiving failed: [Errno 5] Input/output error",
                            f_reporter.lines,
                        )
                        self.assertFalse(os.path.exists(f_dir))

    # ------------------------------------------------------------------ D4

    def _finishedGroup(self, f_request: RunRequest, **f_kwargs: Any) -> Any:
        """Run a multi-arm request to its end and return (orchestrator, run roots)."""
        self._installPluginAndReference()
        f_orch = self._groupOrch()
        with (
            patch("lsmiotool.lib.export.exportPoint", side_effect=_exportCreatingNodeDir),
            patch("lsmiotool.lib.export.generateReports", return_value=True),
        ):
            self._executeSingle(f_orch, f_request, **f_kwargs)
        return f_orch, [f_r["store"].layout.runRoot for f_r in f_orch.groupRuns]

    @staticmethod
    def _markerPath(f_root: str) -> str:
        return os.path.join(f_root, ArchiveEngine.ARM_MARKER_FILE)

    def _rewriteMarker(self, f_root: str, f_edit: Any) -> str:
        """Apply f_edit to the arm marker's document; returns the original text."""
        with open(self._markerPath(f_root), "r", encoding="utf-8") as f_f:
            f_original = f_f.read()
        f_doc = json.loads(f_original)
        f_edit(f_doc)
        with open(self._markerPath(f_root), "w", encoding="utf-8") as f_f:
            json.dump(f_doc, f_f)
        return f_original

    def testArchiveGroupRunRefusesRunsItCannotRebuild(self) -> None:
        f_orch, f_roots = self._finishedGroup(self._pairedRequest())
        f_runs_dir = os.path.dirname(f_roots[0])
        f_manifest = os.path.join(f_roots[1], "manifest.json")
        with open(f_manifest, "rb") as f_f:
            f_manifest_bytes = f_f.read()
        f_loose = os.path.join(self.m_temp_dir, "not-an-arm")
        os.makedirs(f_loose)

        def kind(f_doc: Dict[str, Any]) -> None:
            f_doc["group_kind"] = "single"

        def ghost(f_doc: Dict[str, Any]) -> None:
            f_doc["group_run_ids"] = list(f_doc["group_run_ids"]) + ["ghost-run"]

        def nobody(f_doc: Dict[str, Any]) -> None:
            f_doc["group_run_ids"] = []

        def remove_manifest() -> None:
            os.remove(f_manifest)

        def corrupt_manifest() -> None:
            with open(f_manifest, "wb") as f_f:
                f_f.write(b"{ not a manifest")

        # (label, root archived, marker edit, manifest edit, message, cause type)
        f_rows = [
            (
                "not an arm",
                f_loose,
                None,
                None,
                f"{f_loose} is not an arm of a multi-arm run",
                None,
            ),
            (
                "unknown group kind",
                f_roots[0],
                kind,
                None,
                f"{f_roots[0]}: unknown group kind 'single'",
                None,
            ),
            (
                "a listed run has no arm marker",
                f_roots[0],
                ghost,
                None,
                f"{os.path.join(f_runs_dir, 'ghost-run')}: missing the arm marker "
                "of run ghost-run",
                None,
            ),
            (
                "a listed run has no manifest",
                f_roots[0],
                None,
                remove_manifest,
                f"{f_roots[1]}: cannot read its manifest: ",
                FileNotFoundError,
            ),
            (
                "a listed run has a manifest that does not parse",
                f_roots[0],
                None,
                corrupt_manifest,
                f"{f_roots[1]}: cannot read its manifest: ",
                Exception,
            ),
            (
                "the marker lists no runs",
                f_roots[0],
                nobody,
                None,
                f"{f_roots[0]}: its arm marker lists no runs",
                None,
            ),
        ]
        for f_label, f_root, f_marker_edit, f_manifest_edit, f_message, f_cause in f_rows:
            with self.subTest(f_label):
                f_original = None
                if f_marker_edit is not None:
                    f_original = self._rewriteMarker(f_roots[0], f_marker_edit)
                if f_manifest_edit is not None:
                    f_manifest_edit()
                try:
                    with self.assertRaises(ArchiveError) as f_ctx:
                        f_orch.archiveGroupRun(f_root, f_reporter=lambda f_l: None)
                finally:
                    if f_original is not None:
                        with open(
                            self._markerPath(f_roots[0]), "w", encoding="utf-8"
                        ) as f_f:
                            f_f.write(f_original)
                    with open(f_manifest, "wb") as f_f:
                        f_f.write(f_manifest_bytes)
                self.assertTrue(str(f_ctx.exception).startswith(f_message))
                if f_cause is None:
                    self.assertIsNone(f_ctx.exception.__cause__)
                else:
                    self.assertIsInstance(f_ctx.exception.__cause__, f_cause)

    def testArchiveGroupRunDefaultsTheDestinationForOlderMarkers(self) -> None:
        # (label, request, expected archive dir under the benchmark root)
        f_rows = [
            (
                "a paired variants run",
                self._pairedRequest(),
                os.path.join("lsmio-archive", "variants"),
            ),
            (
                "a versioned run",
                # A versioned run always archives, here to a directory of its own
                RunRequest(
                    "lsmio",
                    "variants",
                    f_versioned=True,
                    f_out_dir=os.path.join(self.m_temp_dir, "elsewhere"),
                ),
                os.path.join("lsmio-archive", "variants-versioned"),
            ),
            (
                "a backends run",
                RunRequest("lsmio", "local", f_mode="backends", f_archive=False),
                os.path.join("lsmio-archive", "backends", "local"),
            ),
        ]
        for f_label, f_request, f_expected in f_rows:
            with self.subTest(f_label):
                self.m_fake_runner = FakeSchedulerCommandRunner()
                f_orch, f_roots = self._finishedGroup(
                    f_request, f_version_tag="b-abc1234"
                )

                def drop_dest(f_doc: Dict[str, Any]) -> None:
                    del f_doc["archive_dest"]

                for f_root in f_roots:
                    self._rewriteMarker(f_root, drop_dest)
                f_lines: List[str] = []
                with (
                    patch(
                        "lsmiotool.lib.export.exportPoint",
                        side_effect=_exportCreatingNodeDir,
                    ),
                    patch("lsmiotool.lib.export.generateReports", return_value=True),
                ):
                    f_ok, f_archived = f_orch.archiveGroupRun(
                        f_roots[0], f_reporter=f_lines.append
                    )
                f_dest = os.path.join(self.m_viking_root_hdd, f_expected)
                self.assertTrue(f_ok)
                self.assertTrue(f_archived)
                for f_dir in f_archived:
                    self.assertEqual(os.path.dirname(f_dir), f_dest, f_dir)
                    self.assertTrue(os.path.isdir(f_dir))
                    shutil.rmtree(f_dir)


def _exportCreatingNodeDir(**f_kwargs: Any) -> int:
    """Stands for exportPoint: the exported <nodes> directory exists afterwards."""
    os.makedirs(f_kwargs["f_node_dir"], exist_ok=True)
    return 1


class _HookedAdapter:
    """Stands for an injected scheduler adapter: every attribute is the real adapter's,
    except renderScript and dispatchSubmission, which run a test hook, and the attributes
    named in f_hidden, which the adapter does not offer (duck-typed callers use hasattr)."""

    def __init__(
        self,
        f_inner: Any,
        f_on_render: Optional[Any] = None,
        f_on_dispatch: Optional[Any] = None,
        f_hidden: Sequence[str] = (),
    ) -> None:
        self.m_inner = f_inner
        self.m_on_render = f_on_render
        self.m_on_dispatch = f_on_dispatch
        self.m_hidden = tuple(f_hidden)
        self.m_renders = 0
        self.m_dispatches = 0

    def __getattr__(self, f_name: str) -> Any:
        if f_name.startswith("m_") or f_name in self.m_hidden:
            raise AttributeError(f_name)
        return getattr(self.m_inner, f_name)

    def renderScript(self, **f_kwargs: Any) -> str:
        self.m_renders += 1
        if self.m_on_render is not None:
            self.m_on_render()
        return self.m_inner.renderScript(**f_kwargs)

    def dispatchSubmission(self, **f_kwargs: Any) -> Any:
        self.m_dispatches += 1
        if self.m_on_dispatch is None:
            return self.m_inner.dispatchSubmission(**f_kwargs)
        return self.m_on_dispatch(self.m_inner, f_kwargs)


class _HookReporter(RunReporter):
    """A RunReporter that records its calls and raises in the named methods."""

    def __init__(self, f_failing: Sequence[str] = ()) -> None:
        super().__init__(f_callback=lambda f_line: None)
        self.m_failing = tuple(f_failing)
        self.m_calls: List[Any] = []

    def _hook(self, f_name: str, f_args: Any) -> None:
        self.m_calls.append((f_name, f_args))
        if f_name in self.m_failing:
            raise RuntimeError(f"{f_name} failed")

    def reportProgress(self, f_line: str) -> None:
        self._hook("reportProgress", (f_line,))
        super().reportProgress(f_line)

    def reportPointSubmission(
        self, f_point_id: str, f_token: str, f_job_id: str
    ) -> None:
        self._hook("reportPointSubmission", (f_point_id, f_token, f_job_id))
        super().reportPointSubmission(f_point_id, f_token, f_job_id)

    def reportCompletion(self, f_final_state: Any, f_exit_code: int) -> None:
        self._hook("reportCompletion", (f_final_state, f_exit_code))
        super().reportCompletion(f_final_state, f_exit_code)


class _InterruptedAfterReads(SignalCoordinator):
    """A coordinator that reads not interrupted until the first job has been submitted
    and f_reads reads have followed, then latches SIGINT exactly as a real signal does."""

    def __init__(self, f_runner: Any, f_reads: int) -> None:
        super().__init__()
        self.m_runner = f_runner
        self.m_reads_left = f_reads

    @property
    def is_interrupted(self) -> bool:
        if self.m_interrupted_signal is None and self.m_runner.m_submit_calls:
            self.m_reads_left -= 1
            if self.m_reads_left <= 0:
                self.trigger(signal.SIGINT)
        return self.m_interrupted_signal is not None


class _FailingPlanner:
    """A planner whose createPlan is the real one until call f_fail_on, then raises."""

    def __init__(self, f_fail_on: int, f_error: BaseException) -> None:
        self.m_fail_on = f_fail_on
        self.m_error = f_error
        self.m_calls = 0

    def createPlan(self, **f_kwargs: Any) -> Any:
        self.m_calls += 1
        if self.m_calls >= self.m_fail_on:
            raise self.m_error
        return RunPlanner.createPlan(**f_kwargs)


class _IdentityFailingReporter:
    """A reporter object whose run-identity report raises."""

    def __init__(self) -> None:
        self.m_progress: List[str] = []
        self.m_identity_calls: List[Any] = []

    def reportProgress(self, f_line: str) -> None:
        self.m_progress.append(f_line)

    def reportRunIdentity(self, f_run_id: str, f_run_root: str) -> None:
        self.m_identity_calls.append((f_run_id, f_run_root))
        raise RuntimeError("terminal closed")


class _FailingLock:
    """A control lock whose acquire raises."""

    def __init__(self, f_error: BaseException) -> None:
        self.m_error = f_error
        self.m_acquires = 0

    def acquire(self, f_blocking: bool = False) -> bool:
        self.m_acquires += 1
        raise self.m_error

    def release(self) -> None:
        pass


class _LockFailingStore(ArtifactStore):
    """A real ArtifactStore whose control lock is the given duck."""

    def __init__(self, f_root: str, f_run_id: str, f_lock: Any) -> None:
        self.m_lock_duck = f_lock
        super().__init__(f_root, f_run_id)

    def getControlLock(self) -> Any:
        return self.m_lock_duck


class _RecordingLock:
    """Wraps a real ControlLock, records acquire and release, and can fail release."""

    def __init__(
        self,
        f_real: ControlLock,
        f_events: List[str],
        f_release_error: Optional[BaseException],
    ) -> None:
        self.m_real = f_real
        self.m_events = f_events
        self.m_release_error = f_release_error

    def acquire(self, f_blocking: bool = False) -> bool:
        self.m_events.append("acquire")
        return self.m_real.acquire(f_blocking=f_blocking)

    def release(self) -> None:
        self.m_events.append("release")
        self.m_real.release()
        if self.m_release_error is not None:
            raise self.m_release_error


class _ArmStore(ArtifactStore):
    """A real ArtifactStore with a recording control lock and an optional allocation error."""

    def __init__(
        self,
        f_root: str,
        f_run_id: str,
        f_events: List[str],
        f_real_locks: List[Any],
        f_release_error: Optional[BaseException],
        f_allocate_error: Optional[BaseException] = None,
    ) -> None:
        self.m_events = f_events
        self.m_real_locks = f_real_locks
        self.m_release_error = f_release_error
        self.m_allocate_error = f_allocate_error
        super().__init__(f_root, f_run_id)

    def allocateRun(self, f_plan: Any = None) -> str:
        if self.m_allocate_error is not None:
            raise self.m_allocate_error
        return super().allocateRun(f_plan)

    def getControlLock(self) -> Any:
        f_real = super().getControlLock()
        self.m_real_locks.append(f_real)
        return _RecordingLock(f_real, self.m_events, self.m_release_error)


class _MarkerBlockingStore(ArtifactStore):
    """A real ArtifactStore that puts a directory where the arm marker file goes."""

    def allocateRun(self, f_plan: Any = None) -> str:
        f_root = super().allocateRun(f_plan)
        os.mkdir(os.path.join(self.layout.runRoot, ".lsmiotool-arm.json"))
        return f_root


class ValidateBenchmarkExecutableTest(unittest.TestCase):
    """validateBenchmarkExecutable called directly: input shape, normalization, permissions."""

    def setUp(self) -> None:
        self.m_tmp = tempfile.TemporaryDirectory()
        self.m_exe = os.path.join(self.m_tmp.name, "bm_tool")
        with open(self.m_exe, "w") as f_f:
            f_f.write("#!/bin/sh\n")
        os.chmod(self.m_exe, 0o755)

    def tearDown(self) -> None:
        self.m_tmp.cleanup()

    def testRejectsMalformedPathArguments(self) -> None:
        for f_value, f_message in (
            (None, "path cannot be None"),
            (42, "path must be a string, got: int"),
            (b"/bin/sh", "path must be a string, got: bytes"),
            ("", "path cannot be empty"),
            ("   ", "path cannot be empty"),
            ("\t\n", "path cannot be empty"),
            (self.m_exe + "\0x", "contains NUL byte"),
        ):
            with self.subTest(value=f_value):
                with self.assertRaisesRegex(PreflightError, f_message):
                    validateBenchmarkExecutable(f_value)  # type: ignore[arg-type]

    def testReturnsAnAbsoluteNormalizedPath(self) -> None:
        self.assertEqual(validateBenchmarkExecutable(self.m_exe), self.m_exe)
        f_messy = os.path.join(self.m_tmp.name, ".", "sub", "..", "bm_tool")
        self.assertEqual(validateBenchmarkExecutable(f_messy), self.m_exe)
        # Surrounding whitespace is stripped; a relative path is made absolute
        self.assertEqual(validateBenchmarkExecutable(f"  {self.m_exe}\n"), self.m_exe)
        f_relative = os.path.relpath(self.m_exe)
        f_result = validateBenchmarkExecutable(f_relative)
        self.assertTrue(os.path.isabs(f_result))
        self.assertEqual(f_result, os.path.abspath(f_relative))

    def testRejectsExecutableThatIsNotReadable(self) -> None:
        if os.geteuid() == 0:
            self.skipTest("root can read any file, so no file is unreadable")
        os.chmod(self.m_exe, 0o111)
        with self.assertRaisesRegex(
            PreflightError, f"is not readable: {self.m_exe}"
        ):
            validateBenchmarkExecutable(self.m_exe)

    def testRejectsMissingNonExecutableAndNonRegularFiles(self) -> None:
        f_dir = os.path.join(self.m_tmp.name, "a_dir")
        os.mkdir(f_dir)
        f_link = os.path.join(self.m_tmp.name, "a_link")
        os.symlink(self.m_exe, f_link)
        f_plain = os.path.join(self.m_tmp.name, "plain")
        with open(f_plain, "w") as f_f:
            f_f.write("data")
        os.chmod(f_plain, 0o644)
        for f_path, f_message in (
            (os.path.join(self.m_tmp.name, "absent"), "does not exist or cannot"),
            (f_link, "must not be a symlink"),
            (f_dir, "must be a regular file"),
            (f_plain, "does not have execute permissions"),
        ):
            with self.subTest(path=os.path.basename(f_path)):
                with self.assertRaisesRegex(PreflightError, f_message):
                    validateBenchmarkExecutable(f_path)


class _FailingEvidenceStore(EvidenceStore):
    """A real EvidenceStore whose named methods raise, to drive swallowed-error paths."""

    def __init__(self, f_layout: ArtifactLayout, f_failing: Sequence[str]) -> None:
        self.m_failing = tuple(f_failing)
        super().__init__(f_layout)

    def _maybeFail(self, f_name: str) -> None:
        if f_name in self.m_failing:
            raise RuntimeError(f"injected failure in {f_name}")

    def recordCancelRequested(self, *f_args: Any, **f_kwargs: Any) -> Any:
        self._maybeFail("recordCancelRequested")
        return super().recordCancelRequested(*f_args, **f_kwargs)

    def recordCancelRecorded(self, *f_args: Any, **f_kwargs: Any) -> Any:
        self._maybeFail("recordCancelRecorded")
        return super().recordCancelRecorded(*f_args, **f_kwargs)

    def readSubmissionRecords(self, *f_args: Any, **f_kwargs: Any) -> Any:
        self._maybeFail("readSubmissionRecords")
        return super().readSubmissionRecords(*f_args, **f_kwargs)


class RunOrchestratorInternalsTest(unittest.TestCase):
    """RunOrchestrator helpers called directly with duck collaborators: constructor
    aliases and accessors, the interruption control event, the cancel and query protocol
    fallbacks for injected adapters, and the small reporting and polling helpers."""

    def setUp(self) -> None:
        self.m_tmp = tempfile.TemporaryDirectory()
        self.m_sp = ScalePoint(4, 4, 1)
        self.m_handle = JobHandle("slurm", "4242")
        self.m_next_run = 0

    def tearDown(self) -> None:
        self.m_tmp.cleanup()

    def _newStore(self, f_failing: Sequence[str] = ()) -> Any:
        """A fresh real EvidenceStore under its own run id, and its layout."""
        self.m_next_run += 1
        f_layout = ArtifactLayout(self.m_tmp.name, f"run-{self.m_next_run}")
        if f_failing:
            return _FailingEvidenceStore(f_layout, f_failing), f_layout
        return EvidenceStore(f_layout), f_layout

    @staticmethod
    def _interrupted() -> SignalCoordinator:
        f_coord = SignalCoordinator()
        f_coord.trigger(signal.SIGINT)
        return f_coord

    # ------------------------------------------------------------------ B1

    def testConstructorKeywordAliases(self) -> None:
        f_store = object()
        f_resolver = object()
        f_other = object()
        self.assertIs(RunOrchestrator(f_profile_store=f_store).profileResolver, f_store)
        self.assertIs(
            RunOrchestrator(
                f_profile_resolver=f_resolver, f_profile_store=f_store
            ).profileResolver,
            f_resolver,
        )

        def factory(f_root: str, f_rid: str) -> Any:
            return f_other

        # A callable artifact store is the factory itself; any other object is wrapped
        self.assertIs(
            RunOrchestrator(f_artifact_store=factory).m_artifact_store_factory, factory
        )
        f_wrapped = RunOrchestrator(f_artifact_store=f_store).m_artifact_store_factory
        self.assertIs(f_wrapped("root", "run-1"), f_store)
        self.assertIs(f_wrapped("another", "run-2"), f_store)
        self.assertIs(
            RunOrchestrator(
                f_artifact_store_factory=factory, f_artifact_store=f_store
            ).m_artifact_store_factory,
            factory,
        )

        # The same for the scheduler adapter: a callable is the factory, an object is returned as is
        f_calls: List[Any] = []

        def adapter_factory(*f_args: Any) -> Any:
            f_calls.append(f_args)
            return f_other

        f_orch = RunOrchestrator(f_scheduler_adapter=adapter_factory)
        self.assertIs(f_orch.m_scheduler_adapter_factory, adapter_factory)
        f_profile = SimpleNamespace(scheduler=SchedulerKind.SLURM)
        self.assertIs(f_orch._makeSchedulerAdapter(f_profile, "evidence"), f_other)
        self.assertEqual(f_calls, [(f_profile, "evidence", None, None)])
        f_orch = RunOrchestrator(f_scheduler_adapter=f_store)
        self.assertIs(f_orch._makeSchedulerAdapter(f_profile, "evidence"), f_store)

        f_clock = lambda: "2026-11-17T00:00:00Z"
        self.assertIs(RunOrchestrator(f_time_source=f_clock).clock, f_clock)
        f_primary = lambda: "primary"
        self.assertIs(
            RunOrchestrator(f_clock=f_primary, f_time_source=f_clock).clock, f_primary
        )

    def testConstructorEnvironmentSleepClockAndPollAliases(self) -> None:
        f_env = {"A": "1"}
        f_other_env = {"B": "2"}
        self.assertIs(RunOrchestrator(environ=f_env).environ, f_env)
        self.assertIs(RunOrchestrator(environment=f_env).environment, f_env)
        self.assertIs(RunOrchestrator(f_environment=f_env).environ, f_env)
        self.assertIs(
            RunOrchestrator(f_environ=f_other_env, f_environment=f_env).environ,
            f_other_env,
        )
        self.assertIsNone(RunOrchestrator().environ)

        f_sleep = lambda f_s: None
        f_sleep2 = lambda f_s: None
        self.assertIs(RunOrchestrator(f_sleep_fn=f_sleep).sleep, f_sleep)
        self.assertIs(RunOrchestrator(sleep_fn=f_sleep).sleep_fn, f_sleep)
        self.assertIs(RunOrchestrator(f_sleep=f_sleep2, f_sleep_fn=f_sleep).sleep, f_sleep2)
        self.assertIs(RunOrchestrator().sleep, time.sleep)

        f_cf = lambda: 1.0
        f_cf2 = lambda: 2.0
        self.assertIs(RunOrchestrator(f_clock_fn=f_cf).clockFloat, f_cf)
        self.assertIs(RunOrchestrator(clock_fn=f_cf).clock_float, f_cf)
        self.assertIs(RunOrchestrator(f_clock_float=f_cf2, f_clock_fn=f_cf).clockFn, f_cf2)
        self.assertIs(RunOrchestrator().clock_fn, time.monotonic)

        self.assertEqual(RunOrchestrator(poll_interval=3.5).pollInterval, 3.5)
        self.assertEqual(RunOrchestrator(f_poll_interval=2.0).poll_interval, 2.0)
        self.assertIsNone(RunOrchestrator().poll_interval)

    def testPlainCallableReporterIsWrappedInARunReporter(self) -> None:
        f_lines: List[str] = []
        for f_label, f_orch in (
            ("f_reporter", RunOrchestrator(f_reporter=f_lines.append)),
            ("reporter kwarg", RunOrchestrator(reporter=f_lines.append)),
        ):
            with self.subTest(how=f_label):
                f_reporter = f_orch.reporter
                self.assertIsInstance(f_reporter, RunReporter)
                self.assertIs(f_orch.f_reporter, f_reporter)
                self.assertEqual(f_reporter.callback, f_lines.append)
                f_reporter.emit("hello")
        self.assertEqual(f_lines, ["hello", "hello"])
        f_own = RunReporter(f_callback=f_lines.append)
        self.assertIs(RunOrchestrator(f_reporter=f_own).reporter, f_own)
        self.assertIsNone(RunOrchestrator().reporter)

    def testAccessorAliasesReturnTheInjectedObjects(self) -> None:
        f_coord = SignalCoordinator()
        f_objs = {
            name: object()
            for name in (
                "resolver",
                "planner",
                "reconciler",
                "validator",
                "runner",
                "clock",
                "run_id",
                "token",
                "sleep",
                "clock_float",
                "environ",
                "plan",
                "evidence",
                "view",
                "capability",
                "error",
            )
        }
        f_store = SimpleNamespace(layout=SimpleNamespace(runRoot="/x/run-1"))
        f_orch = RunOrchestrator(
            f_profile_resolver=f_objs["resolver"],
            f_planner=f_objs["planner"],
            f_reconciler=f_objs["reconciler"],
            f_worker_validator=f_objs["validator"],
            f_command_runner=f_objs["runner"],
            f_clock=f_objs["clock"],
            f_run_id_source=f_objs["run_id"],
            f_token_source=f_objs["token"],
            f_poll_interval=2.5,
            f_sleep=f_objs["sleep"],
            f_signal_coordinator=f_coord,
            f_clock_float=f_objs["clock_float"],
            f_test_mode=True,
            f_environ=f_objs["environ"],
        )
        self.assertIsNone(f_orch.lastRunRoot)
        self.assertIsNone(f_orch.last_run_root)
        for f_attr, f_value in (
            ("m_last_plan", f_objs["plan"]),
            ("m_last_artifact_store", f_store),
            ("m_last_evidence_store", f_objs["evidence"]),
            ("m_last_view", f_objs["view"]),
            ("m_last_capability_state", f_objs["capability"]),
            ("m_last_interruption_error", f_objs["error"]),
        ):
            object.__setattr__(f_orch, f_attr, f_value)
        for f_names, f_expected in (
            (("environ", "environment"), f_objs["environ"]),
            (("profileResolver", "profile_resolver"), f_objs["resolver"]),
            (("planner",), f_objs["planner"]),
            (("reconciler",), f_objs["reconciler"]),
            (("workerValidator", "worker_validator"), f_objs["validator"]),
            (("commandRunner", "command_runner"), f_objs["runner"]),
            (("clock",), f_objs["clock"]),
            (("runIdSource", "run_id_source"), f_objs["run_id"]),
            (("tokenSource", "token_source"), f_objs["token"]),
            (("sleep", "sleep_fn"), f_objs["sleep"]),
            (
                ("clockFloat", "clock_float", "clockFn", "clock_fn"),
                f_objs["clock_float"],
            ),
            (("signalCoordinator", "signal_coordinator"), f_coord),
            (("lastPlan", "last_plan"), f_objs["plan"]),
            (("lastArtifactStore", "last_artifact_store"), f_store),
            (("lastEvidenceStore", "last_evidence_store"), f_objs["evidence"]),
            (("lastView", "last_view"), f_objs["view"]),
            (("lastCapabilityState", "last_capability_state"), f_objs["capability"]),
            (("lastInterruptionError", "last_interruption_error"), f_objs["error"]),
        ):
            for f_name in f_names:
                with self.subTest(accessor=f_name):
                    self.assertIs(getattr(f_orch, f_name), f_expected)
        for f_name in ("testMode", "test_mode"):
            self.assertIs(getattr(f_orch, f_name), True)
        for f_name in ("pollInterval", "poll_interval"):
            self.assertEqual(getattr(f_orch, f_name), 2.5)
        for f_name in ("lastRunRoot", "last_run_root"):
            self.assertEqual(getattr(f_orch, f_name), "/x/run-1")
        self.assertIs(RunOrchestrator().testMode, False)

    def testInterruptionAccessorsFollowTheCoordinator(self) -> None:
        f_idle = RunOrchestrator()
        for f_name in ("isInterrupted", "is_interrupted"):
            self.assertIs(getattr(f_idle, f_name), False)
        for f_name in ("interruptedSignal", "interrupted_signal"):
            self.assertIsNone(getattr(f_idle, f_name))

        f_coord = SignalCoordinator()
        f_orch = RunOrchestrator(f_signal_coordinator=f_coord)
        self.assertIs(f_orch.isInterrupted, False)
        self.assertIsNone(f_orch.interruptedSignal)
        f_coord.trigger(signal.SIGINT)
        for f_name in ("isInterrupted", "is_interrupted"):
            self.assertIs(getattr(f_orch, f_name), True)
        for f_name in ("interruptedSignal", "interrupted_signal"):
            self.assertEqual(getattr(f_orch, f_name), signal.SIGINT)
        self.assertEqual(f_orch.exitCode, 130)
        self.assertEqual(f_orch.exit_code, 130)

    def testExitCodeFollowsTheLastViewWhenNothingTriggered(self) -> None:
        f_untriggered = SignalCoordinator()
        self.assertIsNone(f_untriggered.exit_code)
        for f_label, f_orch, f_state, f_expected in (
            ("interrupted, no coordinator", RunOrchestrator(), OverallRunState.INTERRUPTED, 130),
            (
                "interrupted, untriggered coordinator",
                RunOrchestrator(f_signal_coordinator=f_untriggered),
                OverallRunState.INTERRUPTED,
                130,
            ),
            ("failed", RunOrchestrator(), OverallRunState.FAILED, 1),
            ("succeeded", RunOrchestrator(), OverallRunState.SUCCEEDED, 0),
            ("no view and no group result", RunOrchestrator(), None, 1),
        ):
            with self.subTest(case=f_label):
                if f_state is not None:
                    object.__setattr__(
                        f_orch, "m_last_view", SimpleNamespace(state=f_state)
                    )
                self.assertEqual(f_orch.exitCode, f_expected)
        # A group result takes precedence over the last view
        f_group = RunOrchestrator()
        object.__setattr__(
            f_group, "m_last_view", SimpleNamespace(state=OverallRunState.SUCCEEDED)
        )
        object.__setattr__(f_group, "m_group_failed", True)
        self.assertEqual(f_group.exitCode, 1)

    # ------------------------------------------------------------------ B2

    def testInterruptionControlEvent(self) -> None:
        f_orch = RunOrchestrator()
        f_coord = self._interrupted()
        self.assertFalse(f_orch._recordInterruptionControlEvent(None, f_coord))

        f_store, _ = self._newStore()
        # A control stream that already holds another event gets the next sequence
        f_store.recordWholeRunSucceeded("control", 1, {"note": "earlier"})
        self.assertTrue(f_orch._recordInterruptionControlEvent(f_store, f_coord))
        f_events = f_store.readControlEvents("control")
        self.assertEqual(
            [f_e.evidence_kind for f_e in f_events],
            [EvidenceKind.WHOLE_RUN_SUCCEEDED, EvidenceKind.INTERRUPTED],
        )
        self.assertEqual(f_events[1].sequence_number, 2)
        self.assertEqual(
            f_events[1].payload,
            {"signal": signal.SIGINT, "signal_name": "SIGINT", "exit_code": 130},
        )
        # Already recorded: reported as True, and nothing more is written
        self.assertTrue(f_orch._recordInterruptionControlEvent(f_store, f_coord))
        self.assertEqual(len(f_store.readControlEvents("control")), 2)
        self.assertIsNone(f_orch.lastInterruptionError)

    # ------------------------------------------------------------------ B3

    def _cancel(
        self,
        f_adapter: Any,
        f_store: Any,
        f_layout: ArtifactLayout,
        f_profile: Any,
        f_obs_seq: Optional[int] = None,
    ) -> None:
        RunOrchestrator()._cancelActiveJob(
            f_adapter,
            f_store,
            SimpleNamespace(layout=f_layout),
            self.m_sp,
            0,
            self.m_handle,
            self._interrupted(),
            7.0,
            f_profile,
            self.m_clock,
            self.m_sleep,
            f_obs_seq,
        )

    def m_clock(self) -> float:
        return 0.0

    def m_sleep(self, f_seconds: float) -> None:
        return None

    def testCancelActiveJobAdapterProtocolFallbacks(self) -> None:
        f_no_cancellation = SimpleNamespace(cancellation=None)
        f_with_grace = SimpleNamespace(cancellation=SimpleNamespace(grace_seconds=30))
        f_states = SchedulerJobState

        def confirming(f_calls: List[Any], f_state: Any) -> Any:
            def cancel_and_confirm(**f_kwargs: Any) -> Any:
                f_calls.append(f_kwargs)
                return f_state

            return SimpleNamespace(cancel_and_confirm=cancel_and_confirm)

        def handle_based(f_attr: str, f_calls: List[Any], f_state: Any) -> Any:
            def cancel(f_handle: Any) -> Any:
                f_calls.append(f_handle)
                return f_state

            return SimpleNamespace(**{f_attr: cancel})

        def raising(f_calls: List[Any]) -> Any:
            def cancelJob(f_handle: Any) -> Any:
                f_calls.append(f_handle)
                raise RuntimeError("scheduler unreachable")

            return SimpleNamespace(cancelJob=cancelJob)

        f_rows = (
            # name, adapter builder, profile, expected outcome (None: unconfirmed)
            ("cancel_and_confirm", lambda c: confirming(c, f_states.CANCELLED), f_no_cancellation, "confirmed"),
            ("cancel_and_confirm, grace 30", lambda c: confirming(c, f_states.CANCELLED), f_with_grace, "confirmed"),
            ("cancelJob, already done", lambda c: handle_based("cancelJob", c, f_states.SUCCEEDED), f_no_cancellation, "already_terminal"),
            ("cancel_job", lambda c: handle_based("cancel_job", c, f_states.CANCELLED), f_no_cancellation, "confirmed"),
            ("no cancel method", lambda c: SimpleNamespace(), f_no_cancellation, "confirmed"),
            ("cancelJob raises", raising, f_no_cancellation, None),
        )
        for f_name, f_build, f_profile, f_outcome in f_rows:
            with self.subTest(adapter=f_name):
                f_store, f_layout = self._newStore()
                f_calls: List[Any] = []
                self._cancel(f_build(f_calls), f_store, f_layout, f_profile)
                f_records = f_store.readSubmissionRecords(self.m_sp, 0)
                f_req = f_records["cancel_requested"]
                self.assertIsNotNone(f_req)
                self.assertEqual(f_req.payload["reason"], "Interrupted by SIGINT")
                self.assertEqual(f_req.payload["handle"], self.m_handle.toDict())
                f_unconf = os.path.join(
                    f_layout.pointSchedulerDir(self.m_sp, 0), "cancel_unconfirmed.json"
                )
                if f_outcome is None:
                    self.assertEqual(f_calls, [self.m_handle])
                    self.assertIsNone(f_records["cancel_recorded"])
                    f_rec = f_store.readRecordIfExists(f_unconf)
                    self.assertEqual(f_rec.payload["outcome"], "unconfirmed")
                    self.assertEqual(
                        f_rec.payload["handle"], self.m_handle.toDict()
                    )
                else:
                    self.assertFalse(os.path.exists(f_unconf))
                    f_rec = f_records["cancel_recorded"]
                    self.assertEqual(f_rec.payload["outcome"], f_outcome)
                    if f_name == "no cancel method":
                        self.assertEqual(f_rec.payload["terminal_state"], "cancelled")
                    if f_name.startswith("cancel_and_confirm"):
                        f_grace = 30.0 if "grace" in f_name else 120.0
                        self.assertEqual(len(f_calls), 1)
                        self.assertEqual(f_calls[0]["f_job_id"], "4242")
                        self.assertEqual(f_calls[0]["f_poll_interval"], 7.0)
                        self.assertEqual(f_calls[0]["f_grace_seconds"], f_grace)
                        self.assertEqual(f_calls[0]["f_clock"], self.m_clock)
                        self.assertEqual(f_calls[0]["f_sleep"], self.m_sleep)
                    elif f_name != "no cancel method":
                        self.assertEqual(f_calls, [self.m_handle])

    def testCancelActiveJobWritesObservationWhenGivenASequence(self) -> None:
        f_store, f_layout = self._newStore()
        f_adapter = SimpleNamespace(cancel_job=lambda f_h: SchedulerJobState.CANCELLED)
        self._cancel(f_adapter, f_store, f_layout, SimpleNamespace(cancellation=None), 1)
        f_obs = f_store.readSchedulerObservations(self.m_sp, "control", 0)
        self.assertEqual(len(f_obs), 1)
        self.assertEqual(f_obs[0].payload["state"], "cancelled")
        self.assertEqual(f_obs[0].payload["handle"], self.m_handle.toDict())

    def testCancelActiveJobSwallowsEvidenceWriteFailures(self) -> None:
        f_profile = SimpleNamespace(cancellation=None)
        f_calls: List[Any] = []

        def cancel(f_handle: Any) -> Any:
            f_calls.append(f_handle)
            return SchedulerJobState.CANCELLED

        f_adapter = SimpleNamespace(cancelJob=cancel)
        # The cancel request cannot be recorded: the job is still cancelled and recorded
        f_store, f_layout = self._newStore(["recordCancelRequested"])
        self._cancel(f_adapter, f_store, f_layout, f_profile)
        self.assertEqual(f_calls, [self.m_handle])
        f_records = EvidenceStore(f_layout).readSubmissionRecords(self.m_sp, 0)
        self.assertIsNone(f_records["cancel_requested"])
        self.assertEqual(f_records["cancel_recorded"].payload["outcome"], "confirmed")
        # The outcome cannot be recorded: nothing is written, and no error escapes
        f_store, f_layout = self._newStore(["recordCancelRecorded"])
        f_calls.clear()
        self._cancel(f_adapter, f_store, f_layout, f_profile, 1)
        self.assertEqual(f_calls, [self.m_handle])
        f_records = EvidenceStore(f_layout).readSubmissionRecords(self.m_sp, 0)
        self.assertIsNotNone(f_records["cancel_requested"])
        self.assertIsNone(f_records["cancel_recorded"])
        self.assertEqual(
            EvidenceStore(f_layout).readSchedulerObservations(self.m_sp, "control", 0), []
        )

    # ------------------------------------------------------------------ B4

    def testQueryJobStateUsesTheAdapterQueryMethods(self) -> None:
        f_value = (SchedulerJobState.ACTIVE, None)
        f_seen: List[Any] = []

        def with_timeout(f_self_name: str) -> Any:
            def query(f_job_id: str, f_timeout: Optional[float] = None) -> Any:
                f_seen.append((f_self_name, f_job_id, f_timeout))
                return f_value

            return query

        def without_timeout(f_self_name: str) -> Any:
            def query(f_job_id: str) -> Any:
                f_seen.append((f_self_name, f_job_id))
                return f_value

            return query

        def by_handle(f_self_name: str) -> Any:
            def query(f_handle: Any) -> Any:
                f_seen.append((f_self_name, f_handle))
                return f_value

            return query

        f_no_cancellation = SimpleNamespace(cancellation=None)
        f_grace = SimpleNamespace(cancellation=SimpleNamespace(grace_seconds=45))
        f_rows = (
            ("queryJobState", with_timeout, None, ("queryJobState", "4242", 120.0)),
            ("queryJobState", with_timeout, f_no_cancellation, ("queryJobState", "4242", 120.0)),
            ("queryJobState", with_timeout, f_grace, ("queryJobState", "4242", 45.0)),
            ("queryJobState", without_timeout, f_grace, ("queryJobState", "4242")),
            ("query_job_state", with_timeout, f_grace, ("query_job_state", "4242", 45.0)),
            ("query_job_state", without_timeout, f_grace, ("query_job_state", "4242")),
            ("queryJob", by_handle, f_grace, ("queryJob", self.m_handle)),
            ("query_job", by_handle, f_grace, ("query_job", self.m_handle)),
        )
        for f_attr, f_build, f_profile, f_expected in f_rows:
            with self.subTest(method=f_attr, build=f_build.__name__, profile=f_profile):
                f_seen.clear()
                f_adapter = SimpleNamespace(**{f_attr: f_build(f_attr)})
                f_result = RunOrchestrator()._queryJobState(
                    f_adapter, self.m_handle, f_profile
                )
                self.assertIs(f_result, f_value)
                self.assertEqual(f_seen[-1], f_expected)

    @staticmethod
    def _scripted(f_script: List[Any], f_calls: List[Any]) -> Any:
        """_runCommand duck: records (argv, timeout), then returns or raises the next scripted item."""

        def run_command(f_argv: Sequence[str], f_timeout: Optional[float] = None) -> Any:
            f_calls.append((list(f_argv), f_timeout))
            f_item = f_script.pop(0)
            if isinstance(f_item, Exception):
                raise f_item
            return ProcessResult(f_item[0], f_item[1], "", 0.0)

        return SimpleNamespace(_runCommand=run_command)

    def _commandTables(self) -> List[Dict[str, Any]]:
        f_pbs_done = '{"Jobs": {"4242": {"job_state": "F", "Exit_status": %d}}}'
        return [
            {
                "kind": SchedulerKind.SLURM,
                "active": ["squeue", "--noheader", "--jobs=4242", "--format=%i|%T"],
                "accounting": [
                    "sacct", "--noheader", "--parsable2", "--jobs=4242",
                    "--format=JobIDRaw,JobName,State,ExitCode",
                ],
                "running": "4242|RUNNING\n",
                "queued": "4242|PENDING\n",
                "active_done": "4242|COMPLETED\n",
                "active_done_state": SchedulerJobState.SUCCEEDED,
                "no_record": ["JOBID|STATE\n", "9999|RUNNING\n", "4242|WEIRD\n"],
                "ok": "4242|bm|COMPLETED|0:0\n",
                "bad": "4242|bm|FAILED|3:0\n",
                "bad_code": 3,
                "garbage": "garbage\n",
            },
            {
                "kind": SchedulerKind.PBS,
                "active": ["qstat", "-f", "-F", "json", "4242"],
                "accounting": ["qstat", "-x", "-f", "-F", "json", "4242"],
                "running": '{"Jobs": {"4242": {"job_state": "R"}}}',
                "queued": '{"Jobs": {"4242": {"job_state": "Q"}}}',
                "active_done": f_pbs_done % 0,
                "active_done_state": SchedulerJobState.SUCCEEDED,
                "no_record": [
                    '{"Jobs": {"9999": {"job_state": "R"}}}',
                    '{"Jobs": {}}',
                    '{"Jobs": {"4242": {"job_state": "X"}}}',
                ],
                "ok": f_pbs_done % 0,
                "bad": f_pbs_done % 2,
                "bad_code": 2,
                "garbage": "not json",
            },
        ]

    def testQueryJobStateFallsBackToTheSchedulerCommands(self) -> None:
        S = SchedulerJobState
        for f_t in self._commandTables():
            f_profile = SimpleNamespace(scheduler=f_t["kind"], cancellation=None)
            f_act, f_acc = f_t["active"], f_t["accounting"]
            f_rows = [
                ("running", [(0, f_t["running"])], (S.ACTIVE, None), [f_act]),
                ("queued", [(0, f_t["queued"])], (S.QUEUED, None), [f_act]),
                (
                    "terminal in the active output",
                    [(0, f_t["active_done"])],
                    (f_t["active_done_state"], None),
                    [f_act],
                ),
                ("accounting success", [(0, ""), (0, f_t["ok"])], (S.SUCCEEDED, 0), [f_act, f_acc]),
                (
                    "accounting failure",
                    [(0, ""), (0, f_t["bad"])],
                    (S.FAILED, f_t["bad_code"]),
                    [f_act, f_acc],
                ),
                ("both empty", [(0, ""), (0, "")], (S.UNKNOWN, None), [f_act, f_acc]),
                ("accounting not successful", [(0, ""), (1, "x")], (S.UNKNOWN, None), [f_act, f_acc]),
                ("active not successful", [(1, "err"), (0, f_t["ok"])], (S.SUCCEEDED, 0), [f_act, f_acc]),
                (
                    "active query raises",
                    [RuntimeError("down"), (0, f_t["ok"])],
                    (S.SUCCEEDED, 0),
                    [f_act, f_acc],
                ),
                (
                    "both queries raise",
                    [RuntimeError("down"), RuntimeError("down")],
                    (S.UNKNOWN, None),
                    [f_act, f_acc],
                ),
                (
                    "unparseable accounting output",
                    [(0, ""), (0, f_t["garbage"])],
                    (S.UNKNOWN, None),
                    [f_act, f_acc],
                ),
            ]
            for f_i, f_out in enumerate(f_t["no_record"]):
                f_rows.append(
                    (
                        f"active output without this job {f_i}",
                        [(0, f_out), (0, f_t["ok"])],
                        (S.SUCCEEDED, 0),
                        [f_act, f_acc],
                    )
                )
            for f_name, f_script, f_expected, f_argvs in f_rows:
                with self.subTest(scheduler=f_t["kind"].value, case=f_name):
                    f_calls: List[Any] = []
                    f_adapter = self._scripted(list(f_script), f_calls)
                    f_result = RunOrchestrator()._queryJobState(
                        f_adapter, self.m_handle, f_profile
                    )
                    self.assertEqual(f_result, f_expected)
                    self.assertEqual([f_c[0] for f_c in f_calls], f_argvs)
                    for f_c in f_calls:
                        self.assertEqual(f_c[1], 120.0)

    def testQueryJobStateRejectsInvalidJobIdsWithoutRunningACommand(self) -> None:
        for f_kind in (SchedulerKind.SLURM, SchedulerKind.PBS):
            for f_job_id in ("not-a-number", "42 42"):
                with self.subTest(scheduler=f_kind.value, job_id=f_job_id):
                    f_calls: List[Any] = []
                    f_adapter = self._scripted([(0, "should not run")], f_calls)
                    f_result = RunOrchestrator()._queryJobState(
                        f_adapter,
                        SimpleNamespace(job_id=f_job_id),
                        SimpleNamespace(scheduler=f_kind, cancellation=None),
                    )
                    self.assertEqual(f_result, (SchedulerJobState.UNKNOWN, None))
                    self.assertEqual(f_calls, [])

    def testQueryJobStateThroughACommandRunnerDuck(self) -> None:
        S = SchedulerJobState
        for f_t in self._commandTables():
            f_profile = SimpleNamespace(
                scheduler=f_t["kind"],
                cancellation=SimpleNamespace(grace_seconds=15),
            )
            f_script = [(0, ""), (0, f_t["ok"])]
            f_expected_argvs = [f_t["active"], f_t["accounting"]]

            def accepting_run(f_argv: Sequence[str], f_timeout: Optional[float] = None) -> Any:
                f_timeouts.append(f_timeout)
                f_argvs.append(list(f_argv))
                return ProcessResult(*f_remaining.pop(0), "", 0.0)

            def strict_run(f_argv: Sequence[str]) -> Any:
                f_argvs.append(list(f_argv))
                return ProcessResult(*f_remaining.pop(0), "", 0.0)

            for f_name, f_run, f_expected_timeouts in (
                ("accepts f_timeout", accepting_run, [15.0, 15.0]),
                ("TypeError on f_timeout, retried without it", strict_run, []),
            ):
                with self.subTest(scheduler=f_t["kind"].value, runner=f_name):
                    f_remaining = list(f_script)
                    f_timeouts: List[Any] = []
                    f_argvs: List[Any] = []
                    f_adapter = SimpleNamespace(
                        command_runner=SimpleNamespace(run=f_run)
                    )
                    f_result = RunOrchestrator()._queryJobState(
                        f_adapter, self.m_handle, f_profile
                    )
                    self.assertEqual(f_result, (S.SUCCEEDED, 0))
                    self.assertEqual(f_argvs, f_expected_argvs)
                    self.assertEqual(f_timeouts, f_expected_timeouts)

    def testQueryJobStateWithoutAnyRunnerIsUnknown(self) -> None:
        for f_kind in (SchedulerKind.SLURM, SchedulerKind.PBS):
            for f_name, f_adapter in (
                ("empty adapter", SimpleNamespace()),
                ("command_runner without run", SimpleNamespace(command_runner=object())),
            ):
                with self.subTest(scheduler=f_kind.value, adapter=f_name):
                    f_result = RunOrchestrator()._queryJobState(
                        f_adapter,
                        self.m_handle,
                        SimpleNamespace(scheduler=f_kind, cancellation=None),
                    )
                    self.assertEqual(f_result, (SchedulerJobState.UNKNOWN, None))

    # ------------------------------------------------------------------ B5

    def testReportProgressRoutesToTheUsableReporterMethod(self) -> None:
        f_out = io.StringIO()
        with contextlib.redirect_stdout(f_out):
            RunOrchestrator._reportProgress(None, "to stdout")
        self.assertEqual(f_out.getvalue(), "to stdout\n")

        f_emitted: List[str] = []
        RunOrchestrator._reportProgress(SimpleNamespace(emit=f_emitted.append), "m1")
        f_called: List[str] = []
        RunOrchestrator._reportProgress(f_called.append, "m2")
        f_progress: List[str] = []
        RunOrchestrator._reportProgress(
            SimpleNamespace(reportProgress=f_progress.append, emit=f_emitted.append), "m3"
        )
        self.assertEqual((f_emitted, f_called, f_progress), (["m1"], ["m2"], ["m3"]))

        # Failures and objects with no usable method are ignored
        def explode(f_msg: str) -> None:
            f_progress.append(f"tried {f_msg}")
            raise RuntimeError("reporter broke")

        RunOrchestrator._reportProgress(SimpleNamespace(reportProgress=explode), "m4")
        RunOrchestrator._reportProgress(SimpleNamespace(), "m5")
        RunOrchestrator._reportProgress(object(), "m6")
        self.assertEqual(f_progress, ["m3", "tried m4"])
        self.assertEqual((f_emitted, f_called), (["m1"], ["m2"]))

    def testMakeSchedulerAdapterWithAFactoryAndForTheFakeScheduler(self) -> None:
        f_validator = object()
        f_runner = object()
        f_profile = SimpleNamespace(scheduler=SchedulerKind.SLURM)
        f_built = object()
        f_calls: List[Any] = []

        def factory(*f_args: Any) -> Any:
            f_calls.append(f_args)
            return f_built

        f_orch = RunOrchestrator(
            f_scheduler_adapter_factory=factory,
            f_worker_validator=f_validator,
            f_command_runner=f_runner,
        )
        self.assertIs(f_orch._makeSchedulerAdapter(f_profile, "evidence"), f_built)
        self.assertEqual(f_calls, [(f_profile, "evidence", f_validator, f_runner)])

        f_fake = RunOrchestrator()._makeSchedulerAdapter(
            SimpleNamespace(scheduler=SchedulerKind.FAKE), None
        )
        self.assertIs(type(f_fake), SchedulerAdapter)
        self.assertEqual(f_fake.backend, SchedulerKind.FAKE)

    def testRenderPointDirectivesForTheFakeScheduler(self) -> None:
        f_lines, f_mail = RunOrchestrator._renderPointDirectives(
            SimpleNamespace(scheduler=SchedulerKind.FAKE),
            self.m_sp,
            SimpleNamespace(),
            "tok-1",
            "/o/out.log",
            "/o/err.log",
            None,
            None,
        )
        self.assertEqual(
            f_lines,
            [
                "#FAKE --job-name=tok-1",
                "#FAKE --output=/o/out.log",
                "#FAKE --error=/o/err.log",
            ],
        )
        self.assertIsNone(f_mail)

    def testResolvePollingDefaultsAndOverrides(self) -> None:
        f_sleep = lambda f_s: None
        f_clock = lambda: 1.0
        f_orch = RunOrchestrator()
        f_profile_poll = SimpleNamespace(
            cancellation=SimpleNamespace(poll_interval_seconds=5)
        )
        # No override: the profile's interval, else 8 s; the process sleep and clock
        self.assertEqual(
            f_orch._resolvePolling(f_profile_poll, {}), (5.0, time.sleep, time.monotonic)
        )
        for f_profile in (
            SimpleNamespace(cancellation=None),
            SimpleNamespace(cancellation=SimpleNamespace(poll_interval_seconds=None)),
        ):
            with self.subTest(profile=f_profile):
                self.assertEqual(f_orch._resolvePolling(f_profile, {})[0], 8.0)
        # An override wins: the keyword, either spelling, or the constructor's interval
        f_none = SimpleNamespace(cancellation=None)
        self.assertEqual(f_orch._resolvePolling(f_none, {"f_poll_interval": "2"})[0], 2.0)
        self.assertEqual(f_orch._resolvePolling(f_none, {"poll_interval": 3})[0], 3.0)
        self.assertEqual(
            RunOrchestrator(f_poll_interval=4.5)._resolvePolling(f_profile_poll, {})[0],
            4.5,
        )
        # The sleep and clock keywords are passed through, either spelling
        self.assertEqual(
            f_orch._resolvePolling(
                f_none, {"f_sleep_fn": f_sleep, "f_clock_fn": f_clock}
            ),
            (8.0, f_sleep, f_clock),
        )
        self.assertEqual(
            f_orch._resolvePolling(
                f_none, {"f_sleep": f_sleep, "f_clock_float": f_clock}
            ),
            (8.0, f_sleep, f_clock),
        )
        f_set = RunOrchestrator(f_sleep=f_sleep, f_clock_float=f_clock)
        self.assertEqual(f_set._resolvePolling(f_none, {})[1:], (f_sleep, f_clock))

    # ------------------------------------------------------------------ B6

    def _mirrorSetup(self, f_disp_failing: Sequence[str] = (), f_ctx_failing: Sequence[str] = ()) -> Any:
        f_disp_store, f_disp_layout = self._newStore(f_disp_failing)
        f_ctx_store, f_ctx_layout = self._newStore(f_ctx_failing)
        f_disp = {"evidence": f_disp_store, "store": SimpleNamespace(layout=f_disp_layout)}
        f_ctx = {
            "evidence": f_ctx_store,
            "store": SimpleNamespace(layout=f_ctx_layout),
            "obs_seq": 1,
        }
        return f_disp, f_ctx, f_disp_store, f_ctx_store

    def testMirrorCancelRecordsCopiesTheDispatchingArmsEvidence(self) -> None:
        f_disp, f_ctx, f_src, f_dst = self._mirrorSetup()
        f_src.recordCancelRequested(
            self.m_sp, "control", self.m_handle, {"reason": "r"}, f_ordinal=0
        )
        f_src.recordCancelRecorded(
            self.m_sp,
            "control",
            self.m_handle,
            {"outcome": "confirmed", "terminal_state": "cancelled"},
            f_ordinal=0,
        )
        RunOrchestrator._mirrorCancelRecords(f_disp, f_ctx, self.m_sp, 0, self.m_handle)
        f_recs = f_dst.readSubmissionRecords(self.m_sp, 0)
        self.assertEqual(f_recs["cancel_requested"].payload["reason"], "r")
        self.assertEqual(f_recs["cancel_recorded"].payload["outcome"], "confirmed")
        f_obs = f_dst.readSchedulerObservations(self.m_sp, "control", 0)
        self.assertEqual([f_o.payload["state"] for f_o in f_obs], ["cancelled"])
        self.assertEqual(f_ctx["obs_seq"], 2)

    def testMirrorCancelRecordsPartialEvidence(self) -> None:
        # A cancellation without a terminal state writes no observation
        f_disp, f_ctx, f_src, f_dst = self._mirrorSetup()
        f_src.recordCancelRequested(self.m_sp, "control", self.m_handle, {}, f_ordinal=0)
        f_src.recordCancelRecorded(
            self.m_sp, "control", self.m_handle, {"outcome": "confirmed"}, f_ordinal=0
        )
        RunOrchestrator._mirrorCancelRecords(f_disp, f_ctx, self.m_sp, 0, self.m_handle)
        f_recs = f_dst.readSubmissionRecords(self.m_sp, 0)
        self.assertIsNotNone(f_recs["cancel_requested"])
        self.assertEqual(f_recs["cancel_recorded"].payload["outcome"], "confirmed")
        self.assertEqual(f_dst.readSchedulerObservations(self.m_sp, "control", 0), [])
        self.assertEqual(f_ctx["obs_seq"], 1)

        # No cancel request: only the recorded outcome is mirrored
        f_disp, f_ctx, f_src, f_dst = self._mirrorSetup()
        f_src.recordCancelRecorded(
            self.m_sp, "control", self.m_handle, {"outcome": "already_terminal"}, f_ordinal=0
        )
        RunOrchestrator._mirrorCancelRecords(f_disp, f_ctx, self.m_sp, 0, self.m_handle)
        f_recs = f_dst.readSubmissionRecords(self.m_sp, 0)
        self.assertIsNone(f_recs["cancel_requested"])
        self.assertEqual(f_recs["cancel_recorded"].payload["outcome"], "already_terminal")

        # Nothing to mirror at all
        f_disp, f_ctx, f_src, f_dst = self._mirrorSetup()
        RunOrchestrator._mirrorCancelRecords(f_disp, f_ctx, self.m_sp, 0, self.m_handle)
        f_recs = f_dst.readSubmissionRecords(self.m_sp, 0)
        self.assertIsNone(f_recs["cancel_requested"])
        self.assertIsNone(f_recs["cancel_recorded"])

    def testMirrorCancelRecordsSwallowsEvidenceFailures(self) -> None:
        # The dispatching arm's records cannot be read: nothing is written
        f_disp, f_ctx, f_src, f_dst = self._mirrorSetup(["readSubmissionRecords"])
        RunOrchestrator._mirrorCancelRecords(f_disp, f_ctx, self.m_sp, 0, self.m_handle)
        f_recs = f_dst.readSubmissionRecords(self.m_sp, 0)
        self.assertIsNone(f_recs["cancel_requested"])
        self.assertIsNone(f_recs["cancel_recorded"])
        self.assertEqual(f_ctx["obs_seq"], 1)

        # A write into the sharing arm fails: swallowed, and obs_seq stays
        f_disp, f_ctx, f_src, f_dst = self._mirrorSetup(f_ctx_failing=["recordCancelRequested"])
        f_src.recordCancelRequested(self.m_sp, "control", self.m_handle, {}, f_ordinal=0)
        RunOrchestrator._mirrorCancelRecords(f_disp, f_ctx, self.m_sp, 0, self.m_handle)
        f_recs = f_dst.readSubmissionRecords(self.m_sp, 0)
        self.assertIsNone(f_recs["cancel_requested"])
        self.assertEqual(f_ctx["obs_seq"], 1)

    # ------------------------------------------------------------------ B7

    def testArmPointHelpersReturnFalseWhenEvidenceCannotBeRead(self) -> None:
        def unreadable(*f_args: Any, **f_kwargs: Any) -> Any:
            raise RuntimeError("evidence unreadable")

        f_ctx = {
            "arm": SimpleNamespace(arm_id="native"),
            "plan": SimpleNamespace(
                scale_points=[self.m_sp], combinations=[object()]
            ),
            "evidence": SimpleNamespace(
                readControllerResult=unreadable, readRankResult=unreadable
            ),
        }
        self.assertIs(RunOrchestrator._armPointComplete(f_ctx, self.m_sp, 0), False)
        self.assertIs(RunOrchestrator._armPointSucceeded(f_ctx, 0), False)
        # With readable results the same helpers say True
        f_ok = SimpleNamespace(payload={"status": "success"})
        f_ctx["evidence"] = SimpleNamespace(
            readControllerResult=lambda *f_a, **f_k: f_ok,
            readRankResult=lambda *f_a, **f_k: f_ok,
        )
        self.assertIs(RunOrchestrator._armPointComplete(f_ctx, self.m_sp, 0), True)
        self.assertIs(RunOrchestrator._armPointSucceeded(f_ctx, 0), True)
