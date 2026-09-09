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
import signal
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Set
import unittest

from lsmiotool.lib.artifacts import (
    ArtifactLayout,
    ArtifactStore,
    ControlLock,
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
from lsmiotool.lib.site import (
    CancellationPolicy,
    EnvironmentResolver,
    SchedulerKind,
    SiteProfile,
)
from lsmiotool.lib.state import (
    OverallRunState,
    PointRunState,
    RunStateView,
    SchedulerJobState,
    StateReconciler,
)
from lsmiotool.lib.worker import ProcessResult


class FakeInterruptionSchedulerCommandRunner(SchedulerCommandRunner):
    """Configurable test fake for SchedulerCommandRunner simulating Slurm / PBS commands with interruption/cancel hooks."""

    def __init__(self) -> None:
        super().__init__()
        self.m_calls: List[List[str]] = []
        self.m_submit_job_ids: List[str] = []
        self.m_submit_idx = 0
        self.m_submit_fail = False
        self.m_query_fail = False
        self.m_job_fail = False
        self.m_cancel_confirmed_state = "CANCELLED"
        self.m_cancel_fail = False
        self.m_cancelled_jobs: Set[str] = set()
        self.m_recovery_candidates: Dict[str, List[str]] = {}
        self.m_on_submit_callback = None
        self.m_on_query_callback = None
        self.m_on_acct_callback = None
        self.m_on_cancel_callback = None
        self.m_active_running_count = 0

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
                return ProcessResult(
                    1, "", "squeue: error: Slurm controller down\n", 0.01
                )
            # Recovery query
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
                for f_idx, f_arg in enumerate(f_cmd):
                    if f_arg.startswith("--jobs="):
                        f_jid = f_arg.split("=", 1)[1]
                return ProcessResult(0, f"{f_jid}|RUNNING\n", "", 0.01)

            return ProcessResult(0, "", "", 0.01)

        elif f_exe == "sacct":
            if self.m_query_fail:
                return ProcessResult(1, "", "sacct: error: Slurmdbd down\n", 0.01)
            for f_arg in f_cmd:
                if f_arg.startswith("--name="):
                    f_name = f_arg.split("=", 1)[1]
                    f_cands = self.m_recovery_candidates.get(f_name, [])
                    f_lines = ["JobIDRaw|JobName|State|ExitCode"] + [
                        f"{f_cid}|{f_name}|COMPLETED|0:0" for f_cid in f_cands
                    ]
                    return ProcessResult(0, "\n".join(f_lines) + "\n", "", 0.01)

            f_jid = "1000"
            for f_idx, f_arg in enumerate(f_cmd):
                if f_arg.startswith("--jobs="):
                    f_jid = f_arg.split("=", 1)[1]
                elif f_arg == "-j" and f_idx + 1 < len(f_cmd):
                    f_jid = f_cmd[f_idx + 1]

            if self.m_on_acct_callback is not None:
                self.m_on_acct_callback(f_jid, f_cmd)

            if self.m_job_fail:
                return ProcessResult(0, f"{f_jid}|FAILED|1:0\n", "", 0.01)
            if f_jid in self.m_cancelled_jobs:
                if self.m_cancel_confirmed_state == "CANCELLED":
                    return ProcessResult(0, f"{f_jid}|CANCELLED|0:0\n", "", 0.01)
                elif self.m_cancel_confirmed_state == "FAILED":
                    return ProcessResult(0, f"{f_jid}|FAILED|2:0\n", "", 0.01)
                elif self.m_cancel_confirmed_state == "COMPLETED":
                    return ProcessResult(0, f"{f_jid}|COMPLETED|0:0\n", "", 0.01)
                elif self.m_cancel_confirmed_state == "TIMEOUT":
                    return ProcessResult(0, f"{f_jid}|TIMEOUT|0:0\n", "", 0.01)
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

            if self.m_on_query_callback is not None:
                self.m_on_query_callback(f_cmd)

            if "-x" in f_cmd:
                f_jid = f_cmd[-1].split(".")[0]
                if self.m_on_acct_callback is not None:
                    self.m_on_acct_callback(f_jid, f_cmd)
                if f_jid in self.m_cancelled_jobs:
                    if self.m_cancel_confirmed_state == "CANCELLED":
                        f_job_data = {"job_state": "F", "Exit_status": 271}
                    elif self.m_cancel_confirmed_state == "FAILED" or self.m_job_fail:
                        f_job_data = {"job_state": "F", "Exit_status": 1}
                    else:
                        f_job_data = {"job_state": "F", "Exit_status": 0}
                elif self.m_job_fail:
                    f_job_data = {"job_state": "F", "Exit_status": 1}
                else:
                    f_job_data = {"job_state": "F", "Exit_status": 0}
                return ProcessResult(
                    0, json.dumps({"Jobs": {f"{f_jid}.server": f_job_data}}), "", 0.01
                )
            else:
                if self.m_active_running_count > 0:
                    self.m_active_running_count -= 1
                    f_jid = f_cmd[-1].split(".")[0]
                    return ProcessResult(
                        0,
                        json.dumps({"Jobs": {f"{f_jid}.server": {"job_state": "R"}}}),
                        "",
                        0.01,
                    )
                return ProcessResult(0, json.dumps({"Jobs": {}}), "", 0.01)

        elif f_exe in ("scancel", "qdel"):
            if self.m_on_cancel_callback is not None:
                self.m_on_cancel_callback(f_cmd)
            if self.m_cancel_fail:
                return ProcessResult(
                    1, "", f"{f_exe}: error: connection failed\n", 0.01
                )
            f_jid = f_cmd[-1].split(".")[0]
            self.m_cancelled_jobs.add(f_jid)
            return ProcessResult(0, "", "", 0.01)

        return ProcessResult(0, "", "", 0.01)


class InterruptionTest(unittest.TestCase):
    """Unit tests for SignalCoordinator, exact-job cancellation confirmation, and temporal races."""

    def setUp(self) -> None:
        self.m_orig_environ = dict(os.environ)
        os.environ["SB_ACCOUNT"] = "test_acct"
        os.environ["SB_EMAIL"] = "user@example.com"
        self.m_temp_dir = tempfile.mkdtemp(prefix="lsmiotool-interruption-test-")
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

        f_test_cancellation = CancellationPolicy(
            f_poll_interval_seconds=1, f_grace_seconds=1
        )

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
            f_install_prefix=f_base_viking.install_prefix,
            f_executables=f_base_viking.executables,
            f_modules=f_base_viking.modules,
            f_resources=f_base_viking.resources,
            f_rank_identity=f_base_viking.rank_identity,
            f_cancellation=f_test_cancellation,
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
            f_benchmark_roots={
                "hdd": self.m_isambard_root_hdd,
                "ssd": self.m_isambard_root_ssd,
            },
            f_install_prefix=f_base_isambard.install_prefix,
            f_executables=f_base_isambard.executables,
            f_modules=f_base_isambard.modules,
            f_resources=f_base_isambard.resources,
            f_rank_identity=f_base_isambard.rank_identity,
            f_cancellation=f_test_cancellation,
            f_lustre_pools=f_base_isambard.lustre_pools,
        )

        self.m_fake_worker = os.path.join(self.m_temp_dir, "bin", "lsmiotool-worker")
        os.makedirs(os.path.dirname(self.m_fake_worker), exist_ok=True)
        with open(self.m_fake_worker, "w") as f_f:
            f_f.write("#!/bin/sh\nexit 0\n")
        os.chmod(self.m_fake_worker, 0o755)

        self.m_worker_validator = lambda f_path: f_path

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self.m_orig_environ)
        shutil.rmtree(self.m_temp_dir, ignore_errors=True)

    def test130And143(self) -> None:
        """Validates exit codes 130 for SIGINT and 143 for SIGTERM."""
        f_coord_int = SignalCoordinator()
        f_coord_int.trigger(signal.SIGINT)
        self.assertTrue(f_coord_int.is_interrupted)
        self.assertEqual(f_coord_int.interrupted_signal, signal.SIGINT)
        self.assertEqual(f_coord_int.exit_code, 130)
        self.assertEqual(f_coord_int.signal_name, "SIGINT")

        f_coord_term = SignalCoordinator()
        f_coord_term.trigger(signal.SIGTERM)
        self.assertTrue(f_coord_term.is_interrupted)
        self.assertEqual(f_coord_term.interrupted_signal, signal.SIGTERM)
        self.assertEqual(f_coord_term.exit_code, 143)
        self.assertEqual(f_coord_term.signal_name, "SIGTERM")

    def testRepeatedSignal(self) -> None:
        """Tests latching first signal and ignoring duplicate/mixed signals."""
        # 1. SIGINT followed by SIGTERM -> latches SIGINT
        f_coord_1 = SignalCoordinator()
        f_coord_1.trigger(signal.SIGINT)
        f_coord_1.trigger(signal.SIGTERM)
        f_coord_1.trigger(signal.SIGINT)
        self.assertEqual(f_coord_1.interrupted_signal, signal.SIGINT)
        self.assertEqual(f_coord_1.exit_code, 130)
        self.assertEqual(f_coord_1.signal_name, "SIGINT")

        # 2. SIGTERM followed by SIGINT -> latches SIGTERM
        f_coord_2 = SignalCoordinator()
        f_coord_2.trigger(signal.SIGTERM)
        f_coord_2.trigger(signal.SIGINT)
        self.assertEqual(f_coord_2.interrupted_signal, signal.SIGTERM)
        self.assertEqual(f_coord_2.exit_code, 143)
        self.assertEqual(f_coord_2.signal_name, "SIGTERM")

    def testBeforeAndBetweenNoSubmit(self) -> None:
        """Asserts signals before submission or between points prevent new point submissions."""
        # Case A: Interrupted before submission (before point 0)
        f_runner_a = FakeInterruptionSchedulerCommandRunner()
        f_sig_a = SignalCoordinator()
        f_sig_a.trigger(signal.SIGINT)

        f_orch_a = RunOrchestrator(
            f_worker_validator=self.m_worker_validator,
            f_command_runner=f_runner_a,
            f_signal_coordinator=f_sig_a,
        )

        f_req = RunRequest("ior", "local")
        f_view_a = f_orch_a.execute(
            f_request=f_req,
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_fake_worker,
        )

        self.assertIsNotNone(f_view_a)
        self.assertEqual(f_view_a.state, OverallRunState.INTERRUPTED)
        self.assertEqual(f_orch_a.exit_code, 130)
        # Ensure zero sbatch commands were executed
        f_sbatch_calls = [
            f_c for f_c in f_runner_a.m_calls if os.path.basename(f_c[0]) == "sbatch"
        ]
        self.assertEqual(len(f_sbatch_calls), 0)

        # Check evidence store
        f_ev_store_a = f_orch_a.last_evidence_store
        f_ctrl_events = f_ev_store_a.readControlEvents("control")
        self.assertTrue(
            any(f_e.evidence_kind == EvidenceKind.INTERRUPTED for f_e in f_ctrl_events)
        )

        # Case B: Interrupted between points (point 0 finishes, signal triggered before point 1)
        f_runner_b = FakeInterruptionSchedulerCommandRunner()
        f_sig_b = SignalCoordinator()

        def _onSubmitB(f_jid: str, f_cwd: Optional[str]) -> None:
            # Simulate worker results for point 0
            if (
                f_orch_b.last_plan is not None
                and f_orch_b.last_evidence_store is not None
            ):
                f_plan = f_orch_b.last_plan
                f_store = f_orch_b.last_evidence_store
                f_pt_idx = 0 if f_jid == "1000" else 1
                f_pt = f_plan.scale_points[f_pt_idx]
                for f_combo in f_plan.combinations:
                    f_store.recordControllerResult(
                        f_point=f_pt,
                        f_combination=f_combo,
                        f_payload={"exit_code": 0, "status": "succeeded"},
                        f_ordinal=f_pt_idx,
                    )

        def _onAcctB(f_jid: str, f_cmd: List[str]) -> None:
            # When point 0 sacct query executes and point 0 completes, trigger signal before point 1
            if f_jid == "1000":
                f_sig_b.trigger(signal.SIGTERM)

        f_runner_b.m_on_submit_callback = _onSubmitB
        f_runner_b.m_on_acct_callback = _onAcctB

        f_orch_b = RunOrchestrator(
            f_worker_validator=self.m_worker_validator,
            f_command_runner=f_runner_b,
            f_signal_coordinator=f_sig_b,
            f_poll_interval=0.01,
        )

        f_req_bake = RunRequest("ior", "bake")  # bake has 4 scale points: 1, 2, 4, 8
        f_view_b = f_orch_b.execute(
            f_request=f_req_bake,
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_fake_worker,
        )

        self.assertIsNotNone(f_view_b)
        self.assertEqual(f_view_b.state, OverallRunState.INTERRUPTED)
        self.assertEqual(f_orch_b.exit_code, 143)
        # Point 0 succeeded, points 1, 2, 3 were not started
        self.assertEqual(f_view_b.point_states[0].state, PointRunState.SUCCEEDED)
        self.assertEqual(f_view_b.point_states[1].state, PointRunState.NOT_STARTED)
        # Only 1 sbatch call was executed (for point 0)
        f_sbatch_calls_b = [
            f_c for f_c in f_runner_b.m_calls if os.path.basename(f_c[0]) == "sbatch"
        ]
        self.assertEqual(len(f_sbatch_calls_b), 1)

    def testExactCancelConfirm(self) -> None:
        """Asserts cancellation targets exact active JobHandle with bounded confirmation."""
        f_runner = FakeInterruptionSchedulerCommandRunner()
        f_sig = SignalCoordinator()
        f_runner.m_active_running_count = 5  # job starts active

        def _onQuery(f_cmd: List[str]) -> None:
            # When active query runs, trigger signal
            f_sig.trigger(signal.SIGINT)

        f_runner.m_on_query_callback = _onQuery
        f_runner.m_cancel_confirmed_state = "CANCELLED"

        f_orch = RunOrchestrator(
            f_worker_validator=self.m_worker_validator,
            f_command_runner=f_runner,
            f_signal_coordinator=f_sig,
            f_poll_interval=0.01,
        )

        f_req = RunRequest("ior", "local")
        f_view = f_orch.execute(
            f_request=f_req,
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_fake_worker,
        )

        self.assertIsNotNone(f_view)
        self.assertEqual(f_view.point_states[0].state, PointRunState.CANCELLED)
        self.assertEqual(f_view.state, OverallRunState.CANCELLED)
        self.assertEqual(f_orch.exit_code, 130)

        # Verify exact scancel was invoked with exact handle '1000'
        f_scancel_calls = [
            f_c for f_c in f_runner.m_calls if os.path.basename(f_c[0]) == "scancel"
        ]
        self.assertTrue(len(f_scancel_calls) >= 1)
        self.assertEqual(f_scancel_calls[0], ["scancel", "1000"])

        # Verify cancel evidence files
        f_store = f_orch.last_evidence_store
        f_sub_recs = f_store.readSubmissionRecords(
            f_orch.last_plan.scale_points[0], f_ordinal=0
        )
        self.assertIsNotNone(f_sub_recs.get("cancel_requested"))
        self.assertIsNotNone(f_sub_recs.get("cancel_recorded"))
        self.assertEqual(
            f_sub_recs["cancel_recorded"].payload.get("outcome"), "confirmed"
        )

    def testFailureQueryGraceIndeterminate(self) -> None:
        """Asserts unconfirmed cancellation or query failure yields INDETERMINATE point state."""
        f_runner = FakeInterruptionSchedulerCommandRunner()
        f_sig = SignalCoordinator()
        f_runner.m_active_running_count = 5

        def _onQuery(f_cmd: List[str]) -> None:
            f_sig.trigger(signal.SIGINT)
            # Make subsequent queries fail (causing cancelAndConfirm to return UNKNOWN)
            f_runner.m_query_fail = True

        f_runner.m_on_query_callback = _onQuery

        f_sim_time = [0.0]

        def _clock() -> float:
            f_sim_time[0] += 50.0
            return f_sim_time[0]

        f_orch = RunOrchestrator(
            f_worker_validator=self.m_worker_validator,
            f_command_runner=f_runner,
            f_signal_coordinator=f_sig,
            f_poll_interval=0.01,
            f_clock_float=_clock,
            f_sleep=lambda f_s: None,
        )

        f_req = RunRequest("ior", "local")
        f_view = f_orch.execute(
            f_request=f_req,
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_fake_worker,
        )

        self.assertIsNotNone(f_view)
        self.assertEqual(f_view.point_states[0].state, PointRunState.INDETERMINATE)
        self.assertEqual(f_view.state, OverallRunState.INDETERMINATE)

        # Verify cancel_unconfirmed.json exists
        f_store = f_orch.last_evidence_store
        f_unconf_path = os.path.join(
            f_store.layout.pointSchedulerDir(f_orch.last_plan.scale_points[0], 0),
            "cancel_unconfirmed.json",
        )
        self.assertTrue(os.path.exists(f_unconf_path))

    def testAlreadyTerminal(self) -> None:
        """Asserts cancellation of already-terminal job completes immediately without error."""
        f_runner = FakeInterruptionSchedulerCommandRunner()
        f_sig = SignalCoordinator()
        f_runner.m_active_running_count = 5

        def _onQuery(f_cmd: List[str]) -> None:
            f_sig.trigger(signal.SIGINT)

        f_runner.m_on_query_callback = _onQuery
        # Job was already COMPLETED when cancel confirmation query runs
        f_runner.m_cancel_confirmed_state = "COMPLETED"

        f_orch = RunOrchestrator(
            f_worker_validator=self.m_worker_validator,
            f_command_runner=f_runner,
            f_signal_coordinator=f_sig,
            f_poll_interval=0.01,
        )

        f_req = RunRequest("ior", "local")
        f_view = f_orch.execute(
            f_request=f_req,
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_fake_worker,
        )

        self.assertIsNotNone(f_view)
        # Cancel recorded outcome is 'already_terminal'
        f_store = f_orch.last_evidence_store
        f_sub_recs = f_store.readSubmissionRecords(
            f_orch.last_plan.scale_points[0], f_ordinal=0
        )
        self.assertIsNotNone(f_sub_recs.get("cancel_recorded"))
        self.assertEqual(
            f_sub_recs["cancel_recorded"].payload.get("outcome"), "already_terminal"
        )

    def testPriorFailure(self) -> None:
        """Asserts prior independent failure retains FAILED overall state despite subsequent interruption."""
        f_runner = FakeInterruptionSchedulerCommandRunner()
        f_sig = SignalCoordinator()
        f_runner.m_job_fail = True  # Point fails

        f_orch = RunOrchestrator(
            f_worker_validator=self.m_worker_validator,
            f_command_runner=f_runner,
            f_signal_coordinator=f_sig,
            f_poll_interval=0.01,
        )

        f_req = RunRequest("ior", "local")
        f_view = f_orch.execute(
            f_request=f_req,
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_fake_worker,
        )

        # Trigger interruption after failure
        f_sig.trigger(signal.SIGINT)

        self.assertIsNotNone(f_view)
        self.assertEqual(f_view.point_states[0].state, PointRunState.FAILED)
        self.assertEqual(f_view.state, OverallRunState.FAILED)

    def testFinalLateSuccessInterrupted(self) -> None:
        """Asserts point late success after interruption permanently yields INTERRUPTED overall run state."""
        f_runner = FakeInterruptionSchedulerCommandRunner()
        f_sig = SignalCoordinator()

        # Interrupted before point starts
        f_sig.trigger(signal.SIGINT)

        f_orch = RunOrchestrator(
            f_worker_validator=self.m_worker_validator,
            f_command_runner=f_runner,
            f_signal_coordinator=f_sig,
        )

        f_req = RunRequest("ior", "local")
        f_view = f_orch.execute(
            f_request=f_req,
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_fake_worker,
        )

        f_plan = f_orch.last_plan
        f_store = f_orch.last_evidence_store
        f_point = f_plan.scale_points[0]

        # Simulate late point success evidence recorded after the interruption event
        f_store.recordSubmissionRecorded(
            f_point, "control", f_handle=JobHandle("slurm", "1000"), f_ordinal=0
        )
        f_store.recordWorkerEvent(
            f_point, 1, EvidenceKind.CONTROLLER_STARTED, f_ordinal=0
        )
        for f_combo in f_plan.combinations:
            f_store.recordControllerResult(
                f_point,
                f_combo,
                f_payload={"exit_code": 0, "status": "succeeded"},
                f_ordinal=0,
            )
        f_store.recordSchedulerObservation(
            f_point,
            "control",
            1,
            f_payload={"state": "succeeded", "status": "succeeded", "exit_code": 0},
            f_ordinal=0,
        )

        # Reconcile authoritative state
        f_reconciled_view = StateReconciler.reconcile(f_plan, f_store)
        self.assertEqual(
            f_reconciled_view.point_states[0].state, PointRunState.SUCCEEDED
        )
        self.assertTrue(f_reconciled_view.has_interruption)
        self.assertFalse(f_reconciled_view.has_success_marker)
        self.assertEqual(f_reconciled_view.state, OverallRunState.INTERRUPTED)

    def testMarkerFirstSucceeded(self) -> None:
        """Asserts WHOLE_RUN_SUCCEEDED recorded before interruption retains SUCCEEDED overall run state."""
        f_runner = FakeInterruptionSchedulerCommandRunner()
        f_sig = SignalCoordinator()

        def _onSubmit(f_jid: str, f_cwd: Optional[str]) -> None:
            if f_orch.last_plan is not None and f_orch.last_evidence_store is not None:
                f_plan = f_orch.last_plan
                f_store = f_orch.last_evidence_store
                f_point = f_plan.scale_points[0]
                for f_combo in f_plan.combinations:
                    f_store.recordControllerResult(
                        f_point=f_point,
                        f_combination=f_combo,
                        f_payload={"exit_code": 0, "status": "succeeded"},
                        f_ordinal=0,
                    )

        f_runner.m_on_submit_callback = _onSubmit

        f_orch = RunOrchestrator(
            f_worker_validator=self.m_worker_validator,
            f_command_runner=f_runner,
            f_signal_coordinator=f_sig,
            f_poll_interval=0.01,
        )

        f_req = RunRequest("ior", "local")
        f_view = f_orch.execute(
            f_request=f_req,
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_fake_worker,
        )

        self.assertIsNotNone(f_view)
        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)
        self.assertEqual(f_orch.exit_code, 0)

        # Now record late interruption at sequence 2 (after whole_run_succeeded at sequence 1)
        f_store = f_orch.last_evidence_store
        f_ctrl_seq = len(f_store.readControlEvents("control")) + 1
        f_store.recordInterruption(
            "control", f_ctrl_seq, f_payload={"reason": "Late signal"}
        )

        f_reconciled_view = StateReconciler.reconcile(f_orch.last_plan, f_store)
        self.assertTrue(f_reconciled_view.has_success_marker)
        self.assertEqual(f_reconciled_view.state, OverallRunState.SUCCEEDED)

    def testDispatchWindowRecoveryNoResubmit(self) -> None:
        """Asserts interruption during dispatch recovery window does not resubmit jobs."""
        f_runner = FakeInterruptionSchedulerCommandRunner()
        f_sig = SignalCoordinator()

        # Simulate candidate already in scheduler
        f_req = RunRequest("ior", "local")
        f_plan = RunPlanner.createPlan(
            f_request=f_req,
            f_profile=self.m_viking_profile,
        )
        f_token = f_plan.tokens[0]
        f_runner.m_recovery_candidates[f_token] = ["1000"]
        f_runner.m_submit_fail = True  # sbatch fails, forcing recovery
        f_runner.m_cancel_confirmed_state = "CANCELLED"

        # Signal is triggered
        f_sig.trigger(signal.SIGINT)

        f_orch = RunOrchestrator(
            f_worker_validator=self.m_worker_validator,
            f_command_runner=f_runner,
            f_signal_coordinator=f_sig,
            f_planner=type("PlanStub", (), {"createPlan": lambda **kwargs: f_plan}),
            f_poll_interval=0.01,
        )

        f_view = f_orch.execute(
            f_request=f_req,
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_fake_worker,
        )

        self.assertIsNotNone(f_view)
        self.assertEqual(f_view.state, OverallRunState.INTERRUPTED)

        # Verify no second submit occurred
        f_sbatch_calls = [
            f_c for f_c in f_runner.m_calls if os.path.basename(f_c[0]) == "sbatch"
        ]
        self.assertEqual(len(f_sbatch_calls), 0)

    def testInterruptionDurableBeforeAnyCancelCall(self) -> None:
        """Asserts that durable interruption event is persisted BEFORE any cancellation command is executed."""
        f_runner = FakeInterruptionSchedulerCommandRunner()
        f_sig = SignalCoordinator()
        f_runner.m_active_running_count = 5

        f_interruption_existed_at_cancel: List[bool] = []

        def _onQuery(f_cmd: List[str]) -> None:
            f_sig.trigger(signal.SIGINT)

        def _onCancel(f_cmd: List[str]) -> None:
            # Check if durable interruption event already exists on disk when cancel runs
            if f_orch.last_evidence_store is not None:
                f_store = f_orch.last_evidence_store
                f_events = f_store.readControlEvents("control")
                f_has_interrupt = any(
                    f_e.evidence_kind == EvidenceKind.INTERRUPTED for f_e in f_events
                )
                f_interruption_existed_at_cancel.append(f_has_interrupt)

        f_runner.m_on_query_callback = _onQuery
        f_runner.m_on_cancel_callback = _onCancel

        f_orch = RunOrchestrator(
            f_worker_validator=self.m_worker_validator,
            f_command_runner=f_runner,
            f_signal_coordinator=f_sig,
            f_poll_interval=0.01,
        )

        f_view = f_orch.execute(
            f_request=RunRequest("ior", "local"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_fake_worker,
        )

        self.assertIsNotNone(f_view)
        self.assertEqual(len(f_interruption_existed_at_cancel), 1)
        self.assertTrue(
            f_interruption_existed_at_cancel[0],
            "Interruption event must be durable on disk BEFORE cancel command runs",
        )
        self.assertEqual(f_orch.exit_code, 130)
        self.assertIn(
            f_view.state, (OverallRunState.CANCELLED, OverallRunState.INTERRUPTED)
        )

    def testInterruptionWriteFailureSurfacedAndNeverSuccess(self) -> None:
        """Asserts write failure during interruption recording is surfaced, never writes success, and still cancels active job."""
        f_runner = FakeInterruptionSchedulerCommandRunner()
        f_sig = SignalCoordinator()
        f_runner.m_active_running_count = 5

        def _onQuery(f_cmd: List[str]) -> None:
            f_sig.trigger(signal.SIGINT)

        f_runner.m_on_query_callback = _onQuery

        f_orch = RunOrchestrator(
            f_worker_validator=self.m_worker_validator,
            f_command_runner=f_runner,
            f_signal_coordinator=f_sig,
            f_poll_interval=0.01,
        )

        import unittest.mock

        with unittest.mock.patch.object(
            EvidenceStore,
            "recordInterruption",
            side_effect=OSError("Disk write failed: simulate permission/disk error"),
        ):
            f_view = f_orch.execute(
                f_request=RunRequest("ior", "local"),
                f_site=self.m_viking_profile,
                f_worker_executable=self.m_fake_worker,
            )

        self.assertIsNotNone(f_view)
        # 1. Write failure was surfaced
        self.assertIsNotNone(f_orch.last_interruption_error)
        # 2. Never writes success / overall state is not SUCCEEDED
        self.assertNotEqual(f_view.state, OverallRunState.SUCCEEDED)
        # 3. Retains signal exit code 130
        self.assertEqual(f_orch.exit_code, 130)
        # 4. Attempted cancellation for cluster safety: scancel was still called
        f_scancel_calls = [
            f_c for f_c in f_runner.m_calls if os.path.basename(f_c[0]) == "scancel"
        ]
        self.assertTrue(len(f_scancel_calls) >= 1)

    def testBeforeRequestRequestedBeforeDispatchAfterDispatchAfterAcceptanceActiveBetweenPointsFinalPoint(
        self,
    ) -> None:
        """Tests signal handling at every distinct phase of execution."""
        # 1. Before request (before execute starts)
        f_sig_1 = SignalCoordinator()
        f_sig_1.trigger(signal.SIGINT)
        f_runner_1 = FakeInterruptionSchedulerCommandRunner()
        f_orch_1 = RunOrchestrator(
            f_worker_validator=self.m_worker_validator,
            f_command_runner=f_runner_1,
            f_signal_coordinator=f_sig_1,
        )
        f_v1 = f_orch_1.execute(
            f_request=RunRequest("ior", "local"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_fake_worker,
        )
        self.assertEqual(f_v1.state, OverallRunState.INTERRUPTED)
        self.assertEqual(f_orch_1.exit_code, 130)
        self.assertEqual(
            len([c for c in f_runner_1.m_calls if os.path.basename(c[0]) == "sbatch"]),
            0,
        )

        # 2. Between points (point 0 finishes, signal before point 1)
        f_sig_2 = SignalCoordinator()
        f_runner_2 = FakeInterruptionSchedulerCommandRunner()

        def _onSubmit2(f_jid: str, f_cwd: Optional[str]) -> None:
            if (
                f_orch_2.last_plan is not None
                and f_orch_2.last_evidence_store is not None
            ):
                f_plan = f_orch_2.last_plan
                f_store = f_orch_2.last_evidence_store
                f_pt = f_plan.scale_points[0]
                for f_combo in f_plan.combinations:
                    f_store.recordControllerResult(
                        f_point=f_pt,
                        f_combination=f_combo,
                        f_payload={"exit_code": 0, "status": "succeeded"},
                        f_ordinal=0,
                    )

        def _onAcct2(f_jid: str, f_cmd: List[str]) -> None:
            if f_jid == "1000":
                f_sig_2.trigger(signal.SIGTERM)

        f_runner_2.m_on_submit_callback = _onSubmit2
        f_runner_2.m_on_acct_callback = _onAcct2
        f_orch_2 = RunOrchestrator(
            f_worker_validator=self.m_worker_validator,
            f_command_runner=f_runner_2,
            f_signal_coordinator=f_sig_2,
            f_poll_interval=0.01,
        )
        f_v2 = f_orch_2.execute(
            f_request=RunRequest("ior", "bake"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_fake_worker,
        )
        self.assertEqual(f_v2.state, OverallRunState.INTERRUPTED)
        self.assertEqual(f_orch_2.exit_code, 143)
        self.assertEqual(f_v2.point_states[0].state, PointRunState.SUCCEEDED)
        self.assertEqual(f_v2.point_states[1].state, PointRunState.NOT_STARTED)
        self.assertEqual(
            len([c for c in f_runner_2.m_calls if os.path.basename(c[0]) == "sbatch"]),
            1,
        )

        # 3. Active during polling
        f_sig_3 = SignalCoordinator()
        f_runner_3 = FakeInterruptionSchedulerCommandRunner()
        f_runner_3.m_active_running_count = 5
        f_runner_3.m_on_query_callback = lambda cmd: f_sig_3.trigger(signal.SIGINT)
        f_orch_3 = RunOrchestrator(
            f_worker_validator=self.m_worker_validator,
            f_command_runner=f_runner_3,
            f_signal_coordinator=f_sig_3,
            f_poll_interval=0.01,
        )
        f_v3 = f_orch_3.execute(
            f_request=RunRequest("ior", "local"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_fake_worker,
        )
        self.assertEqual(f_v3.point_states[0].state, PointRunState.CANCELLED)
        self.assertEqual(f_orch_3.exit_code, 130)

        # 4. Final point of multi-point run
        f_sig_4 = SignalCoordinator()
        f_runner_4 = FakeInterruptionSchedulerCommandRunner()

        def _onSubmit4(f_jid: str, f_cwd: Optional[str]) -> None:
            if (
                f_orch_4.last_plan is not None
                and f_orch_4.last_evidence_store is not None
            ):
                f_plan = f_orch_4.last_plan
                f_store = f_orch_4.last_evidence_store
                if f_jid == "1000":
                    f_pt = f_plan.scale_points[0]
                    for f_combo in f_plan.combinations:
                        f_store.recordControllerResult(
                            f_point=f_pt,
                            f_combination=f_combo,
                            f_payload={"exit_code": 0, "status": "succeeded"},
                            f_ordinal=0,
                        )
                else:
                    f_runner_4.m_active_running_count = 5

        def _onQuery4(f_cmd: List[str]) -> None:
            for f_arg in f_cmd:
                if f_arg.startswith("--jobs=1001"):
                    f_sig_4.trigger(signal.SIGINT)

        f_runner_4.m_on_submit_callback = _onSubmit4
        f_runner_4.m_on_query_callback = _onQuery4
        f_orch_4 = RunOrchestrator(
            f_worker_validator=self.m_worker_validator,
            f_command_runner=f_runner_4,
            f_signal_coordinator=f_sig_4,
            f_poll_interval=0.01,
        )
        f_v4 = f_orch_4.execute(
            f_request=RunRequest("ior", "bake"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_fake_worker,
        )
        self.assertEqual(f_v4.point_states[0].state, PointRunState.SUCCEEDED)
        self.assertEqual(f_v4.point_states[1].state, PointRunState.CANCELLED)
        self.assertEqual(f_orch_4.exit_code, 130)

    def testExactRecoveredHandleCancelledNoResubmit(self) -> None:
        """Asserts signal during dispatch window recovers exact token candidate, cancels it, and never resubmits."""
        f_runner = FakeInterruptionSchedulerCommandRunner()
        f_sig = SignalCoordinator()

        f_req = RunRequest("ior", "local")
        f_plan = RunPlanner.createPlan(
            f_request=f_req,
            f_profile=self.m_viking_profile,
        )
        f_token = f_plan.tokens[0]
        f_runner.m_recovery_candidates[f_token] = ["1000"]
        f_runner.m_submit_fail = True
        f_runner.m_cancel_confirmed_state = "CANCELLED"

        f_sig.trigger(signal.SIGINT)

        f_orch = RunOrchestrator(
            f_worker_validator=self.m_worker_validator,
            f_command_runner=f_runner,
            f_signal_coordinator=f_sig,
            f_planner=type("PlanStub", (), {"createPlan": lambda **kwargs: f_plan}),
            f_poll_interval=0.01,
        )

        f_view = f_orch.execute(
            f_request=f_req,
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_fake_worker,
        )

        self.assertIsNotNone(f_view)
        self.assertEqual(f_view.state, OverallRunState.INTERRUPTED)
        self.assertEqual(f_orch.exit_code, 130)

        # Ensure 0 sbatch calls executed and no duplicate submit
        f_sbatch_calls = [
            f_c for f_c in f_runner.m_calls if os.path.basename(f_c[0]) == "sbatch"
        ]
        self.assertEqual(len(f_sbatch_calls), 0)

    def testCancelTimeoutErrorGraceUnconfirmed(self) -> None:
        """Asserts cancellation timeout or query error records unconfirmed and yields INDETERMINATE."""
        f_runner = FakeInterruptionSchedulerCommandRunner()
        f_sig = SignalCoordinator()
        f_runner.m_active_running_count = 5

        def _onQuery(f_cmd: List[str]) -> None:
            f_sig.trigger(signal.SIGINT)
            f_runner.m_query_fail = True

        f_runner.m_on_query_callback = _onQuery

        f_sim_time = [0.0]

        def _clock() -> float:
            f_sim_time[0] += 50.0
            return f_sim_time[0]

        f_orch = RunOrchestrator(
            f_worker_validator=self.m_worker_validator,
            f_command_runner=f_runner,
            f_signal_coordinator=f_sig,
            f_poll_interval=0.01,
            f_clock_float=_clock,
            f_sleep=lambda f_s: None,
        )

        f_view = f_orch.execute(
            f_request=RunRequest("ior", "local"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_fake_worker,
        )

        self.assertIsNotNone(f_view)
        self.assertEqual(f_view.point_states[0].state, PointRunState.INDETERMINATE)
        self.assertEqual(f_view.state, OverallRunState.INDETERMINATE)
        self.assertEqual(f_orch.exit_code, 130)

        f_store = f_orch.last_evidence_store
        f_unconf_path = os.path.join(
            f_store.layout.pointSchedulerDir(f_orch.last_plan.scale_points[0], 0),
            "cancel_unconfirmed.json",
        )
        self.assertTrue(os.path.exists(f_unconf_path))

    def testAlreadyTerminalEveryState(self) -> None:
        """Asserts cancellation of already-terminal job in every terminal state (COMPLETED, FAILED, TIMEOUT, CANCELLED)."""
        for f_state in ("COMPLETED", "FAILED", "TIMEOUT", "CANCELLED"):
            with self.subTest(terminal_state=f_state):
                f_runner = FakeInterruptionSchedulerCommandRunner()
                f_sig = SignalCoordinator()
                f_runner.m_active_running_count = 5

                def _onQuery(f_cmd: List[str]) -> None:
                    f_sig.trigger(signal.SIGINT)

                f_runner.m_on_query_callback = _onQuery
                f_runner.m_cancel_confirmed_state = f_state

                f_orch = RunOrchestrator(
                    f_worker_validator=self.m_worker_validator,
                    f_command_runner=f_runner,
                    f_signal_coordinator=f_sig,
                    f_poll_interval=0.01,
                )

                f_view = f_orch.execute(
                    f_request=RunRequest("ior", "local"),
                    f_site=self.m_viking_profile,
                    f_worker_executable=self.m_fake_worker,
                )

                self.assertIsNotNone(f_view)
                self.assertEqual(f_orch.exit_code, 130)
                f_store = f_orch.last_evidence_store
                f_sub_recs = f_store.readSubmissionRecords(
                    f_orch.last_plan.scale_points[0], f_ordinal=0
                )
                self.assertIsNotNone(f_sub_recs.get("cancel_recorded"))
                if f_state == "CANCELLED":
                    self.assertEqual(
                        f_sub_recs["cancel_recorded"].payload.get("outcome"),
                        "confirmed",
                    )
                else:
                    self.assertEqual(
                        f_sub_recs["cancel_recorded"].payload.get("outcome"),
                        "already_terminal",
                    )

    def testFirstMixedSignalWinsAnd130Or143(self) -> None:
        """Tests first mixed signal wins (SIGINT -> 130, SIGTERM -> 143) and ignores subsequent signals."""
        f_coord_1 = SignalCoordinator()
        f_coord_1.trigger(signal.SIGINT)
        f_coord_1.trigger(signal.SIGTERM)
        self.assertEqual(f_coord_1.interrupted_signal, signal.SIGINT)
        self.assertEqual(f_coord_1.exit_code, 130)
        self.assertEqual(f_coord_1.signal_name, "SIGINT")

        f_coord_2 = SignalCoordinator()
        f_coord_2.trigger(signal.SIGTERM)
        f_coord_2.trigger(signal.SIGINT)
        self.assertEqual(f_coord_2.interrupted_signal, signal.SIGTERM)
        self.assertEqual(f_coord_2.exit_code, 143)
        self.assertEqual(f_coord_2.signal_name, "SIGTERM")

    def testMarkerBeforeVsInterruptionBeforeLateSuccess(self) -> None:
        """Asserts temporal precedence between WHOLE_RUN_SUCCEEDED marker and interruption events."""
        # Case A: Interruption before late success of point
        f_runner_a = FakeInterruptionSchedulerCommandRunner()
        f_sig_a = SignalCoordinator()
        f_sig_a.trigger(signal.SIGINT)
        f_orch_a = RunOrchestrator(
            f_worker_validator=self.m_worker_validator,
            f_command_runner=f_runner_a,
            f_signal_coordinator=f_sig_a,
        )
        f_view_a = f_orch_a.execute(
            f_request=RunRequest("ior", "local"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_fake_worker,
        )
        f_plan_a = f_orch_a.last_plan
        f_store_a = f_orch_a.last_evidence_store
        f_pt_a = f_plan_a.scale_points[0]
        # Late point success recorded
        f_store_a.recordSubmissionRecorded(
            f_pt_a, "control", f_handle=JobHandle("slurm", "1000"), f_ordinal=0
        )
        for f_combo in f_plan_a.combinations:
            f_store_a.recordControllerResult(
                f_pt_a,
                f_combo,
                f_payload={"exit_code": 0, "status": "succeeded"},
                f_ordinal=0,
            )
        f_store_a.recordSchedulerObservation(
            f_pt_a,
            "control",
            1,
            f_payload={"state": "succeeded", "status": "succeeded", "exit_code": 0},
            f_ordinal=0,
        )
        f_rec_view_a = StateReconciler.reconcile(f_plan_a, f_store_a)
        self.assertEqual(f_rec_view_a.point_states[0].state, PointRunState.SUCCEEDED)
        self.assertEqual(f_rec_view_a.state, OverallRunState.INTERRUPTED)

        # Case B: WHOLE_RUN_SUCCEEDED recorded before interruption
        f_runner_b = FakeInterruptionSchedulerCommandRunner()
        f_sig_b = SignalCoordinator()

        def _onSubmitB(f_jid: str, f_cwd: Optional[str]) -> None:
            if (
                f_orch_b.last_plan is not None
                and f_orch_b.last_evidence_store is not None
            ):
                f_plan = f_orch_b.last_plan
                f_store = f_orch_b.last_evidence_store
                f_pt = f_plan.scale_points[0]
                for f_combo in f_plan.combinations:
                    f_store.recordControllerResult(
                        f_point=f_pt,
                        f_combination=f_combo,
                        f_payload={"exit_code": 0, "status": "succeeded"},
                        f_ordinal=0,
                    )

        f_runner_b.m_on_submit_callback = _onSubmitB
        f_orch_b = RunOrchestrator(
            f_worker_validator=self.m_worker_validator,
            f_command_runner=f_runner_b,
            f_signal_coordinator=f_sig_b,
            f_poll_interval=0.01,
        )
        f_view_b = f_orch_b.execute(
            f_request=RunRequest("ior", "local"),
            f_site=self.m_viking_profile,
            f_worker_executable=self.m_fake_worker,
        )
        self.assertEqual(f_view_b.state, OverallRunState.SUCCEEDED)
        self.assertEqual(f_orch_b.exit_code, 0)
        # Late interruption at sequence 2
        f_store_b = f_orch_b.last_evidence_store
        f_ctrl_seq = len(f_store_b.readControlEvents("control")) + 1
        f_store_b.recordInterruption(
            "control", f_ctrl_seq, f_payload={"reason": "Late signal"}
        )
        f_rec_view_b = StateReconciler.reconcile(f_orch_b.last_plan, f_store_b)
        self.assertEqual(f_rec_view_b.state, OverallRunState.SUCCEEDED)


if __name__ == "__main__":
    unittest.main()
