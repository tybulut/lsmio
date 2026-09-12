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
import json
import os
import shutil
import signal
import tempfile
import time
from typing import Any, Dict, List, Optional, Sequence
import unittest
from unittest.mock import MagicMock, call, patch
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
    RunReporter,
    RunRequest,
    ScalePoint,
    SignalCoordinator,
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
        f_broot = self.m_viking_profile.benchmark_roots["hdd"]
        f_store = ArtifactStore(f_broot, f_plan.run_id)
        f_store.allocateRun(f_plan)
        f_store.preparePoint(f_plan.scale_points[0], f_plan.combinations, f_ordinal=0)
        f_ev_store = EvidenceStore(f_store.layout, f_plan)
        f_ev_store.recordSubmissionRequested(
            f_plan.scale_points[0], "control", f_ordinal=0
        )
        f_ev_store.recordSubmissionDispatched(
            f_plan.scale_points[0], "control", f_ordinal=0
        )

        f_token = f_plan.tokens[0]
        self.m_fake_runner.m_recovery_candidates[f_token] = ["99991"]

        self._mockWritePointResults(
            f_ev_store, f_plan.scale_points[0], f_plan, f_ordinal=0
        )

        f_orch_recovered = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
            f_poll_interval=0.01,
        )

        f_submit_calls_before = len(
            [f_c for f_c in self.m_fake_runner.m_calls if f_c[0] == "sbatch"]
        )
        f_view = f_orch_recovered.recoverRun(
            f_plan,
            f_broot,
            f_worker_executable=self.m_worker_path,
        )
        f_submit_calls_after = len(
            [f_c for f_c in self.m_fake_runner.m_calls if f_c[0] == "sbatch"]
        )

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
        f_plan_b = RunPlanner.createPlan(
            RunRequest("ior", "local"), self.m_viking_profile
        )
        f_store_b = ArtifactStore(
            self.m_viking_profile.benchmark_roots["hdd"], f_plan_b.run_id
        )
        f_store_b.allocateRun(f_plan_b)
        f_store_b.preparePoint(
            f_plan_b.scale_points[0], f_plan_b.combinations, f_ordinal=0
        )
        f_ev_store_b = EvidenceStore(f_store_b.layout, f_plan_b)
        f_ev_store_b.recordSubmissionRequested(
            f_plan_b.scale_points[0], "control", f_ordinal=0
        )
        f_ev_store_b.recordSubmissionDispatched(
            f_plan_b.scale_points[0], "control", f_ordinal=0
        )

        self.m_fake_runner.m_recovery_candidates[f_plan_b.tokens[0]] = []

        f_orch_b = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
            f_poll_interval=0.01,
        )

        f_view_b = f_orch_b.recoverRun(
            f_plan_b,
            self.m_viking_profile.benchmark_roots["hdd"],
            f_worker_executable=self.m_worker_path,
        )
        self.assertNotEqual(f_view_b.state, OverallRunState.SUCCEEDED)

        # ---------------------------------------------------------------------
        # Scenario C: Dispatched exists, >1 recovery candidates -> indeterminate fail closed
        # ---------------------------------------------------------------------
        f_plan_c = RunPlanner.createPlan(
            RunRequest("ior", "local"), self.m_viking_profile
        )
        f_store_c = ArtifactStore(
            self.m_viking_profile.benchmark_roots["hdd"], f_plan_c.run_id
        )
        f_store_c.allocateRun(f_plan_c)
        f_store_c.preparePoint(
            f_plan_c.scale_points[0], f_plan_c.combinations, f_ordinal=0
        )
        f_ev_store_c = EvidenceStore(f_store_c.layout, f_plan_c)
        f_ev_store_c.recordSubmissionRequested(
            f_plan_c.scale_points[0], "control", f_ordinal=0
        )
        f_ev_store_c.recordSubmissionDispatched(
            f_plan_c.scale_points[0], "control", f_ordinal=0
        )

        self.m_fake_runner.m_recovery_candidates[f_plan_c.tokens[0]] = [
            "99992",
            "99993",
        ]

        f_orch_c = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
            f_poll_interval=0.01,
        )

        f_view_c = f_orch_c.recoverRun(
            f_plan_c,
            self.m_viking_profile.benchmark_roots["hdd"],
            f_worker_executable=self.m_worker_path,
        )
        self.assertNotEqual(f_view_c.state, OverallRunState.SUCCEEDED)

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

    def testInternalRecoverRunRequiresManifestMatchAndControlLock(self) -> None:
        """Asserts internal recoverRun requires exact manifest match and acquires control lock."""
        f_run_id = "test-internal-recover-run"
        f_plan = RunPlanner.createPlan(
            RunRequest("ior", "local"),
            self.m_viking_profile,
            f_run_id_source=lambda: f_run_id,
        )
        f_broot = self.m_viking_profile.benchmark_roots["hdd"]
        f_store = ArtifactStore(f_broot, f_run_id)
        f_store.allocateRun(f_plan)

        # Pre-seed dispatch evidence
        f_ev_store = EvidenceStore(f_store.layout, f_plan)
        f_ev_store.recordSubmissionRequested(
            f_plan.scale_points[0], "control", f_ordinal=0
        )
        f_ev_store.recordSubmissionDispatched(
            f_plan.scale_points[0], "control", f_ordinal=0
        )
        f_token = f_plan.tokens[0]
        self.m_fake_runner.m_recovery_candidates[f_token] = ["88881"]
        self._mockWritePointResults(
            f_ev_store, f_plan.scale_points[0], f_plan, f_ordinal=0
        )

        # 1. Lock contention test
        f_lock = f_store.getControlLock()
        f_lock.acquire(f_blocking=False)
        self.assertTrue(f_lock.is_locked)

        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
            f_poll_interval=0.01,
        )

        try:
            with self.assertRaises(OrchestrationError) as f_ctx:
                f_orch.recoverRun(
                    f_plan,
                    f_broot,
                    f_worker_executable=self.m_worker_path,
                )
            self.assertIn("control lock contention", str(f_ctx.exception).lower())
        finally:
            f_lock.release()

        # 2. Manifest mismatch test
        f_mismatched_plan = RunPlanner.createPlan(
            RunRequest("ior", "bake"),
            self.m_viking_profile,
            f_run_id_source=lambda: f_run_id,
        )
        with self.assertRaises(OrchestrationError) as f_ctx:
            f_orch.recoverRun(
                f_mismatched_plan,
                f_broot,
                f_worker_executable=self.m_worker_path,
            )
        self.assertIn("does not match plan", str(f_ctx.exception).lower())

        # 3. Successful recovery with matching manifest and free lock
        f_view = f_orch.recoverRun(
            f_plan,
            f_broot,
            f_worker_executable=self.m_worker_path,
        )
        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
        self.assertEqual(f_view.point_states[0].handle.job_id, "88881")

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
            1,
            "Must not submit point 2 after point 1 execution fails",
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
        """Asserts concurrent orchestrator normal execution is rejected on collision and recovery is blocked by ControlLock."""
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

            # 2. Internal recoverRun on existing store must fail with lock contention while lock is held
            with self.assertRaises(OrchestrationError) as f_ctx_rec:
                f_orch_2.recoverRun(
                    f_plan,
                    f_broot,
                    f_worker_executable=self.m_worker_path,
                )
            self.assertIn("lock contention", str(f_ctx_rec.exception).lower())
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
            RunRequest("lsmio", "local", f_setup="NATIVE-M"),
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
        """Query failure/error/timeout or UNKNOWN immediately fails closed without 3-unknown retries."""
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

        # Immediately terminates as INDETERMINATE, does NOT retry with 3 unknowns
        self.assertEqual(f_view.state, OverallRunState.INDETERMINATE)
        self.assertEqual(f_view.point_states[0].state, PointRunState.INDETERMINATE)
        self.assertEqual(
            len(f_sleep_calls), 0, "Must not sleep/retry on query failure/UNKNOWN"
        )
        self.assertEqual(f_orch.exitCode, 1)

        # Confirm no whole_run_succeeded marker is written
        f_layout = f_orch.last_artifact_store.layout
        self.assertFalse(os.path.exists(f_layout.controlEventPath("control", 1)))

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

    def testRecoveredHandleReportingInCrashRecovery(self) -> None:
        """Chunk 019: Asserts recoverRun emits recovered point token and exact job ID."""
        # Create a valid plan and store with a point already recorded
        f_plan = RunPlanner.createPlan(
            f_request=RunRequest("ior", "local"),
            f_profile=self.m_viking_profile,
        )
        f_store = ArtifactStore(self.m_temp_dir, f_plan.run_id)
        f_store.allocateRun(f_plan)

        f_ev = EvidenceStore(f_store.layout, f_plan)
        f_handle = JobHandle(
            f_backend="slurm",
            f_job_id="998877",
        )
        f_ev.recordSubmissionRecorded(
            f_point=f_plan.scale_points[0],
            f_writer_id="control",
            f_handle=f_handle,
            f_ordinal=0,
        )
        self._mockWritePointResults(f_ev, f_plan.scale_points[0], f_plan, f_ordinal=0)

        f_reporter = RunReporter()
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=self.m_fake_runner,
            f_poll_interval=0.01,
            f_reporter=f_reporter,
        )

        f_view = f_orch.recoverRun(
            f_plan=f_plan,
            f_root=f_store.layout.runRoot,
            f_worker_executable=self.m_worker_path,
        )

        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
        f_lines = f_reporter.lines
        self.assertIn(f"Run ID: {f_plan.run_id}", f_lines)
        self.assertIn(f"Run Root: {os.path.abspath(f_store.layout.runRoot)}", f_lines)
        self.assertIn(
            f"Point 00-tasks-1 Correlation Token: {f_plan.tokens[0]}", f_lines
        )
        self.assertIn("Point 00-tasks-1 Job ID: 998877", f_lines)
        self.assertIn("Final State: SUCCEEDED", f_lines)
        self.assertIn("Exit Code: 0", f_lines)

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

    def testMultiVariantSequentialExecution(self) -> None:
        """Task 2.6.1: Asserts orchestrator executes multiple variants sequentially and populates self.views."""
        f_fake_runner = FakeSchedulerCommandRunner()
        f_reporter = RunReporter()
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_fake_runner,
            f_poll_interval=0.01,
            f_reporter=f_reporter,
        )

        f_submitted_variants = []

        def on_submit(f_jid: str, f_cwd: Optional[str]) -> None:
            if f_orch.last_evidence_store and f_orch.last_plan:
                f_submitted_variants.append(f_orch.last_plan.request.variant)
                self._mockWritePointResults(
                    f_orch.last_evidence_store,
                    f_orch.last_plan.scale_points[0],
                    f_orch.last_plan,
                    f_ordinal=0,
                )

        f_fake_runner.m_on_submit_callback = on_submit
        f_fake_runner.m_submit_job_ids = ["9001", "9002"]

        f_req = RunRequest("lsmio", "baseline", f_variants=["footer", "manoff"], f_archive=False)
        f_view = f_orch.execute(
            f_req,
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )

        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
        self.assertEqual(f_submitted_variants, ["footer", "manoff"])
        self.assertEqual(len(f_orch.views), 2)
        self.assertEqual(f_orch.exitCode, 0)

    def testResumptionSkipsExistingArchive(self) -> None:
        """Task 2.6.2 (INV-MULTI-3): Asserts variant is skipped if archive directory exists under --resume."""
        import tempfile
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

            # Pre-create archive target for 'footer'
            f_arm_id = ArchiveEngine.resolveArmId("NATIVE-M", "footer")
            f_target_dir = os.path.join(f_tmpdir, f"outputs-{f_arm_id}")
            os.makedirs(f_target_dir, exist_ok=True)

            f_req = RunRequest(
                "lsmio",
                "baseline",
                f_variants=["footer"],
                f_resume=True,
                f_out_dir=f_tmpdir,
            )

            f_view = f_orch.execute(
                f_req,
                f_site=self.m_viking_profile,
                f_worker_executable=self.m_worker_path,
            )

            # 0 jobs submitted because variant was skipped via resumption
            self.assertEqual(len(f_fake_runner.m_submit_calls), 0)
            self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
            self.assertEqual(f_orch.exitCode, 0)
            f_resume_logs = [l for l in f_reporter.lines if "[RESUME] Skipping variant 'footer'" in l]
            self.assertTrue(len(f_resume_logs) > 0)

    def testAutoArchiveMultiVariant(self) -> None:
        """Task 2.6.3: Asserts ArchiveEngine.executeArchive is invoked after variant execution when auto-archive is active."""
        import tempfile
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as f_tmpdir:
            f_fake_runner = FakeSchedulerCommandRunner()
            f_reporter = RunReporter()
            f_orch = RunOrchestrator(
                f_profile_resolver=self.m_registry,
                f_command_runner=f_fake_runner,
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

            f_fake_runner.m_on_submit_callback = on_submit
            f_fake_runner.m_submit_job_ids = ["9101"]

            with patch("lsmiotool.lib.archive.ArchiveEngine.executeArchive") as f_mock_archive:
                f_req = RunRequest("lsmio", "baseline", f_variants=["footer", "manoff"], f_out_dir=f_tmpdir)
                f_view = f_orch.execute(
                    f_req,
                    f_site=self.m_viking_profile,
                    f_worker_executable=self.m_worker_path,
                )
                self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
                self.assertEqual(f_mock_archive.call_count, 2)

    def testFailFastOnVariantError(self) -> None:
        """Task 2.6.4: Asserts multi-variant execution halts immediately upon first variant failure without running subsequent variants."""
        f_fake_runner = FakeSchedulerCommandRunner()
        f_reporter = RunReporter()
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_fake_runner,
            f_poll_interval=0.01,
            f_reporter=f_reporter,
        )

        f_fake_runner.m_submit_error = "Slurm sbatch rejection"

        f_req = RunRequest("lsmio", "baseline", f_variants=["footer", "manoff"])
        f_view = f_orch.execute(
            f_req,
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
        )

        self.assertEqual(f_view.state, OverallRunState.FAILED)
        self.assertEqual(len(f_fake_runner.m_submit_calls), 1)
        self.assertEqual(len(f_orch.views), 1)
        self.assertNotEqual(f_orch.exitCode, 0)

