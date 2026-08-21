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
import os
import re
import shlex
import sys
import tempfile
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Union
import unittest

from lsmiotool.lib.artifacts import ArtifactLayout
from lsmiotool.lib.evidence import (
    EvidenceError,
    EvidenceKind,
    EvidenceRecord,
    EvidenceStore,
    JobHandle,
    WriterKind,
)
from lsmiotool.lib.profile import ProfileLoader
from lsmiotool.lib.run import (
    Combination,
    RunPlan,
    RunPlanner,
    RunRequest,
    ScalePoint,
    ScheduledPointResources,
)
from lsmiotool.lib.scheduler import (
    JobResult,
    JobSpec,
    SchedulerAdapter,
    SchedulerCommandRunner,
    SchedulerError,
    SchedulerScriptError,
    SchedulerScriptRenderer,
    SlurmSchedulerAdapter,
    SlurmScriptRenderer,
    SubmissionDispatchError,
    WorkerExecutableValidator,
)
from lsmiotool.lib.site import (
    EnvironmentResolver,
    LauncherPolicy,
    PbsMailMode,
    ResourcePolicy,
    SchedulerKind,
    SiteProfile,
    SlurmMailMode,
    StorageClass,
)
from lsmiotool.lib.state import SchedulerJobState
from lsmiotool.lib.worker import (
    ModuleSetup,
    ProcessExecutionError,
    ProcessResult,
    ProcessRunner,
)


class MockProcessRunner:
    """Mock process runner for recording command argv and returning custom responses."""

    def __init__(
        self,
        f_returncode: int = 0,
        f_stdout: str = "",
        f_stderr: str = "",
        f_response_sequence: Optional[Sequence[ProcessResult]] = None,
        f_custom_handler: Optional[Callable[[Sequence[str]], ProcessResult]] = None,
    ) -> None:
        self.m_returncode = f_returncode
        self.m_stdout = f_stdout
        self.m_stderr = f_stderr
        self.m_response_sequence = list(f_response_sequence) if f_response_sequence is not None else None
        self.m_response_idx = 0
        self.m_custom_handler = f_custom_handler
        self.m_invoked_argv: List[List[str]] = []
        self.m_invoked_kwargs: List[Dict[str, Any]] = []

    def run(
        self,
        f_argv: Sequence[str],
        **f_kwargs: Any,
    ) -> ProcessResult:
        self.m_invoked_argv.append(list(f_argv))
        self.m_invoked_kwargs.append(dict(f_kwargs))

        if self.m_custom_handler is not None:
            return self.m_custom_handler(f_argv)

        if self.m_response_sequence is not None:
            if self.m_response_idx < len(self.m_response_sequence):
                f_res = self.m_response_sequence[self.m_response_idx]
                self.m_response_idx += 1
                return f_res
            else:
                return self.m_response_sequence[-1]

        return ProcessResult(
            f_returncode=self.m_returncode,
            f_stdout=self.m_stdout,
            f_stderr=self.m_stderr,
            f_elapsed_seconds=0.01,
        )


class SlurmAdapterTest(unittest.TestCase):
    """Unit test suite verifying exact Slurm scheduler commands, parsing, recovery, cancellation, and rendering."""

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.TemporaryDirectory()
        self.m_etc_path = os.path.normpath(
            os.path.join(
                os.path.dirname(__file__), "..", "..", "etc", "environments.json"
            )
        )
        self.m_profile_doc = ProfileLoader.load(self.m_etc_path)
        self.m_viking_profile = EnvironmentResolver.resolveProfile(
            "VIKING", f_user="testuser", f_home="/tmp"
        )
        self.m_viking2_profile = EnvironmentResolver.resolveProfile(
            "VIKING2", f_user="testuser", f_home="/tmp"
        )
        self.m_archer2_profile = EnvironmentResolver.resolveProfile(
            "ARCHER2", f_user="testuser", f_home="/tmp"
        )
        self.m_dev_profile = EnvironmentResolver.resolveProfile(
            "DEV", f_user="testuser", f_home="/tmp"
        )

        # Scale Points
        self.m_small_point = ScalePoint(f_tasks=8, f_ppn=1, f_nodes=8)
        self.m_large_point = ScalePoint(f_tasks=8, f_ppn=4, f_nodes=2)

        # Standard test parameters
        self.m_worker_path = "/opt/lsmio/bin/lsmiotool-worker"
        self.m_manifest_path = "/tmp/benchmark/runs/run_001/manifest.json"
        self.m_job_name = "lm-0123456789abcdef01234567"
        self.m_output_path = "/tmp/benchmark/runs/run_001/logs/0-tasks-8.out"
        self.m_error_path = "/tmp/benchmark/runs/run_001/logs/0-tasks-8.err"
        self.m_account = "myaccount"
        self.m_mail_user = "user@example.com"

        # Artifact Layout & Evidence Store
        self.m_layout = ArtifactLayout(self.m_temp_dir.name, "run_001")
        self.m_request = RunRequest(
            f_target="ior",
            f_scale="small",
            f_ssd=False,
            f_setup="BASE",
        )
        f_token_idx = 0

        def token_gen() -> str:
            nonlocal f_token_idx
            f_tok = f"lm-{f_token_idx:024x}"
            f_token_idx += 1
            return f_tok

        self.m_plan = RunPlanner.createPlan(
            f_request=self.m_request,
            f_profile=self.m_viking_profile,
            f_run_id_source=lambda: "run_001",
            f_clock=lambda: "2026-08-20T12:00:00Z",
            f_token_source=token_gen,
        )
        self.m_evidence_store = EvidenceStore(self.m_layout, f_plan=self.m_plan)

    def tearDown(self) -> None:
        self.m_temp_dir.cleanup()

    def testExactArgvForEveryOperation(self) -> None:
        """Validates exact command argv for submit, active query, accounting query, recovery, and cancel."""
        # 1. Submit command: ['sbatch', '--parsable', <script>]
        f_submit_argv = SlurmSchedulerAdapter.submitCommand("/path/to/job.sh")
        self.assertEqual(f_submit_argv, ["sbatch", "--parsable", "/path/to/job.sh"])

        # 2. Active query command: ['squeue', '-j', <job_id>, '-h', '-o', '%T']
        f_active_argv = SlurmSchedulerAdapter.activeQueryCommand("123456")
        self.assertEqual(f_active_argv, ["squeue", "-j", "123456", "-h", "-o", "%T"])

        # 3. Accounting query command: ['sacct', '-j', <job_id>, '-P', '-n', '-o', 'JobIDRaw,State,ExitCode']
        f_acct_argv = SlurmSchedulerAdapter.accountingQueryCommand("123456")
        self.assertEqual(
            f_acct_argv,
            ["sacct", "-j", "123456", "-P", "-n", "-o", "JobIDRaw,State,ExitCode"],
        )

        # 4. Cancel command: ['scancel', <job_id>]
        f_cancel_argv = SlurmSchedulerAdapter.cancelCommand("123456")
        self.assertEqual(f_cancel_argv, ["scancel", "123456"])

        # 5. Recovery active command: ['squeue', '--noheader', '--name=<job_name>', '--format=%i|%j|%T']
        f_rec_active_argv = SlurmSchedulerAdapter.recoveryActiveCommand(self.m_job_name)
        self.assertEqual(
            f_rec_active_argv,
            ["squeue", "--noheader", f"--name={self.m_job_name}", "--format=%i|%j|%T"],
        )

        # 6. Recovery terminal command: ['sacct', '--noheader', '--parsable2', '--name=<job_name>', '--format=JobIDRaw,JobName,State,ExitCode']
        f_rec_terminal_argv = SlurmSchedulerAdapter.recoveryTerminalCommand(self.m_job_name)
        self.assertEqual(
            f_rec_terminal_argv,
            [
                "sacct",
                "--noheader",
                "--parsable2",
                f"--name={self.m_job_name}",
                "--format=JobIDRaw,JobName,State,ExitCode",
            ],
        )

        # With start time
        f_rec_terminal_start = SlurmSchedulerAdapter.recoveryTerminalCommand(
            self.m_job_name, f_start_time="2026-08-20T12:00:00"
        )
        self.assertEqual(
            f_rec_terminal_start,
            [
                "sacct",
                "--noheader",
                "--parsable2",
                f"--name={self.m_job_name}",
                "--format=JobIDRaw,JobName,State,ExitCode",
                "--starttime=2026-08-20T12:00:00",
            ],
        )

    def testAcceptsOnlySingleDecimalParsableOutput(self) -> None:
        """Confirms acceptance of single decimal string and strict rejection of malformed outputs."""
        f_adapter = SlurmSchedulerAdapter()

        # Valid decimal outputs
        self.assertEqual(f_adapter.parseSubmitOutput("123456\n"), "123456")
        self.assertEqual(f_adapter.parseSubmitOutput("99999999\r\n"), "99999999")
        self.assertEqual(f_adapter.parseSubmitOutput("123456"), "123456")
        self.assertEqual(f_adapter.parseSubmitOutput("1\n"), "1")
        self.assertEqual(f_adapter.parseSubmitOutput("00123456\n"), "00123456")

        # Rejected invalid / whitespace / multiline outputs
        f_bad_outputs = [
            "",
            "\n",
            "\r\n",
            "   ",
            " 123456\n",
            "123456 \n",
            " 123456 \n",
            "123456\n789012\n",
            "123456\n\n",
            "Submitted batch job 123456\n",
            "abc123\n",
            "-123456\n",
            "123.456\n",
            "123456\0\n",
        ]
        for f_bad in f_bad_outputs:
            with self.assertRaises(SubmissionDispatchError, msg=f"Should reject: {f_bad!r}"):
                f_adapter.parseSubmitOutput(f_bad)

    def testRejectsClusterQualifiedParsableOutput(self) -> None:
        """Asserts rejection of cluster-qualified format (e.g. 123456;cluster)."""
        f_adapter = SlurmSchedulerAdapter()

        f_cluster_outputs = [
            "123456;cluster\n",
            "123456;viking\n",
            "123456;cluster\r\n",
            "123456;cluster",
            "123456;archer2",
            "123456;cluster_01\n",
        ]
        for f_cluster_out in f_cluster_outputs:
            with self.assertRaises(
                SubmissionDispatchError,
                msg=f"Should reject cluster-qualified output: {f_cluster_out!r}",
            ):
                f_adapter.parseSubmitOutput(f_cluster_out)

    def testExactNumericHandlePersistsThroughQueryAccountingCancelAndEvidence(self) -> None:
        """Asserts decimal string is preserved unmodified across all operations and evidence."""
        f_mock_runner = MockProcessRunner(f_returncode=0, f_stdout="00123456\n")
        f_cmd_runner = SchedulerCommandRunner(f_mock_runner)
        f_adapter = SlurmSchedulerAdapter(
            f_command_runner=f_cmd_runner,
            f_evidence_store=self.m_evidence_store,
        )

        f_spec = JobSpec(
            f_point_id="0-tasks-8",
            f_script_path="/tmp/job.sh",
            f_working_dir=self.m_temp_dir.name,
            f_job_name=self.m_job_name,
        )

        f_point = self.m_plan.scale_points[0]
        f_result = f_adapter.dispatchSubmission(f_point=f_point, f_spec=f_spec)

        # Assert returned handle preserves exact string representation
        self.assertEqual(f_result.job_handle.job_id, "00123456")
        self.assertEqual(f_result.job_handle.backend, "slurm")

        # Assert active query uses exact string
        f_act_argv = f_adapter.activeQueryCommand(f_result.job_handle.job_id)
        self.assertEqual(f_act_argv[2], "00123456")

        # Assert accounting query uses exact string
        f_acct_argv = f_adapter.accountingQueryCommand(f_result.job_handle.job_id)
        self.assertEqual(f_acct_argv[2], "00123456")

        # Assert cancel command uses exact string
        f_cancel_argv = f_adapter.cancelCommand(f_result.job_handle.job_id)
        self.assertEqual(f_cancel_argv[1], "00123456")

        # Verify evidence store recorded handle
        f_sub_records = self.m_evidence_store.readSubmissionRecords(f_point)
        f_recorded = f_sub_records["submission_recorded"]
        self.assertEqual(f_recorded.payload["handle"]["job_id"], "00123456")
        self.assertEqual(f_recorded.payload["handle"]["backend"], "slurm")

    def testExactOutputFieldAndRootRowParsing(self) -> None:
        """Verifies root-row extraction and step-row filtering in sacct output."""
        # 1. Standard sacct output with root row and step rows
        f_sacct_output = (
            "123456|COMPLETED|0:0\n"
            "123456.batch|COMPLETED|0:0\n"
            "123456.extern|COMPLETED|0:0\n"
            "123456.0|COMPLETED|0:0\n"
            "123456.1|COMPLETED|0:0\n"
        )
        f_state, f_exit = SlurmSchedulerAdapter.parseAccountingQuery(f_sacct_output, f_job_id="123456")
        self.assertEqual(f_state, SchedulerJobState.SUCCEEDED)
        self.assertEqual(f_exit, 0)

        # 2. 4-column format (JobIDRaw, JobName, State, ExitCode)
        f_sacct_4col = (
            "123456|lm-0123456789abcdef01234567|COMPLETED|0:0\n"
            "123456.batch|batch|COMPLETED|0:0\n"
            "123456.extern|extern|COMPLETED|0:0\n"
        )
        f_state_4, f_exit_4 = SlurmSchedulerAdapter.parseAccountingQuery(f_sacct_4col, f_job_id="123456")
        self.assertEqual(f_state_4, SchedulerJobState.SUCCEEDED)
        self.assertEqual(f_exit_4, 0)

        # 3. Filtering specific root row when other jobs exist in output
        f_multi_job_output = (
            "789012|FAILED|1:0\n"
            "789012.batch|FAILED|1:0\n"
            "123456|COMPLETED|0:0\n"
            "123456.batch|COMPLETED|0:0\n"
        )
        f_state_match, f_exit_match = SlurmSchedulerAdapter.parseAccountingQuery(
            f_multi_job_output, f_job_id="123456"
        )
        self.assertEqual(f_state_match, SchedulerJobState.SUCCEEDED)
        self.assertEqual(f_exit_match, 0)

        # 4. Step row malformed (missing fields) causes error
        f_corrupt_step = (
            "123456|COMPLETED|0:0\n"
            "123456.batch|COMPLETED\n"
        )
        with self.assertRaises(SchedulerError):
            SlurmSchedulerAdapter.parseAccountingQuery(f_corrupt_step, f_job_id="123456")

        # 5. Conflicting root rows for same job ID causes error
        f_conflict_roots = (
            "123456|COMPLETED|0:0\n"
            "123456|FAILED|1:0\n"
        )
        with self.assertRaises(SchedulerError):
            SlurmSchedulerAdapter.parseAccountingQuery(f_conflict_roots, f_job_id="123456")

        # 6. No matching root row returns UNKNOWN
        f_no_match = "789012|COMPLETED|0:0\n"
        f_state_un, f_exit_un = SlurmSchedulerAdapter.parseAccountingQuery(f_no_match, f_job_id="123456")
        self.assertEqual(f_state_un, SchedulerJobState.UNKNOWN)
        self.assertIsNone(f_exit_un)

    def testStateExitTable(self) -> None:
        """Tests full state mapping table between Slurm outputs and normalized SchedulerJobState."""
        # Test active queries (squeue)
        f_active_cases = [
            ("PENDING", SchedulerJobState.QUEUED),
            ("CONFIGURING", SchedulerJobState.QUEUED),
            ("PD", SchedulerJobState.QUEUED),
            ("CF", SchedulerJobState.QUEUED),
            ("RUNNING", SchedulerJobState.ACTIVE),
            ("COMPLETING", SchedulerJobState.ACTIVE),
            ("SUSPENDED", SchedulerJobState.ACTIVE),
            ("R", SchedulerJobState.ACTIVE),
            ("CG", SchedulerJobState.ACTIVE),
            ("COMPLETED", SchedulerJobState.SUCCEEDED),
            ("CANCELLED", SchedulerJobState.CANCELLED),
            ("CANCELLED by 1000", SchedulerJobState.CANCELLED),
            ("TIMEOUT", SchedulerJobState.TIMEOUT),
            ("FAILED", SchedulerJobState.FAILED),
            ("BOOT_FAIL", SchedulerJobState.FAILED),
            ("NODE_FAIL", SchedulerJobState.FAILED),
            ("OUT_OF_MEMORY", SchedulerJobState.FAILED),
            ("DEADLINE", SchedulerJobState.FAILED),
            ("PREEMPTED", SchedulerJobState.FAILED),
            ("REVOKED", SchedulerJobState.FAILED),
            ("SPECIAL_EXIT", SchedulerJobState.FAILED),
            ("UNKNOWN_STATE_XYZ", SchedulerJobState.UNKNOWN),
        ]
        for f_state_str, f_expected_state in f_active_cases:
            f_parsed = SlurmSchedulerAdapter.parseActiveQuery(f"{f_state_str}\n")
            self.assertEqual(
                f_parsed,
                f_expected_state,
                msg=f"Active query failed for state: {f_state_str}",
            )

        # Test accounting queries (sacct: JobIDRaw|State|ExitCode)
        f_acct_cases = [
            ("123456|PENDING|0:0", SchedulerJobState.QUEUED, 0),
            ("123456|CONFIGURING|0:0", SchedulerJobState.QUEUED, 0),
            ("123456|RUNNING|0:0", SchedulerJobState.ACTIVE, 0),
            ("123456|COMPLETING|0:0", SchedulerJobState.ACTIVE, 0),
            ("123456|SUSPENDED|0:0", SchedulerJobState.ACTIVE, 0),
            ("123456|COMPLETED|0:0", SchedulerJobState.SUCCEEDED, 0),
            ("123456|COMPLETED|1:0", SchedulerJobState.FAILED, 1),
            ("123456|COMPLETED|2:0", SchedulerJobState.FAILED, 2),
            ("123456|COMPLETED|0:15", SchedulerJobState.FAILED, 143),
            ("123456|FAILED|1:0", SchedulerJobState.FAILED, 1),
            ("123456|BOOT_FAIL|0:0", SchedulerJobState.FAILED, 0),
            ("123456|NODE_FAIL|0:0", SchedulerJobState.FAILED, 0),
            ("123456|OUT_OF_MEMORY|0:0", SchedulerJobState.FAILED, 0),
            ("123456|DEADLINE|0:0", SchedulerJobState.FAILED, 0),
            ("123456|PREEMPTED|0:0", SchedulerJobState.FAILED, 0),
            ("123456|REVOKED|0:0", SchedulerJobState.FAILED, 0),
            ("123456|SPECIAL_EXIT|0:0", SchedulerJobState.FAILED, 0),
            ("123456|CANCELLED|0:0", SchedulerJobState.CANCELLED, 0),
            ("123456|CANCELLED by 1000|0:0", SchedulerJobState.CANCELLED, 0),
            ("123456|TIMEOUT|0:0", SchedulerJobState.TIMEOUT, 0),
            ("123456|UNKNOWN_XYZ|0:0", SchedulerJobState.UNKNOWN, 0),
        ]
        for f_line, f_exp_state, f_exp_exit in f_acct_cases:
            f_parsed_state, f_parsed_exit = SlurmSchedulerAdapter.parseAccountingQuery(
                f"{f_line}\n", f_job_id="123456"
            )
            self.assertEqual(
                f_parsed_state,
                f_exp_state,
                msg=f"Accounting state mismatch for: {f_line}",
            )
            self.assertEqual(
                f_parsed_exit,
                f_exp_exit,
                msg=f"Accounting exit mismatch for: {f_line}",
            )

    def testRecoveryZeroOneManyExactTokenNeverResubmits(self) -> None:
        """Verifies recovery logic (0 -> unrecovered, 1 -> recovered, >1 -> error) and exact token matching."""
        # 1. Zero candidate jobs
        f_runner_zero = MockProcessRunner(f_returncode=0, f_stdout="")
        f_adapter_zero = SlurmSchedulerAdapter(f_command_runner=SchedulerCommandRunner(f_runner_zero))
        f_recovered_zero = f_adapter_zero.recoverDispatchedSubmission(self.m_job_name)
        self.assertIsNone(f_recovered_zero)

        # 2. Exactly one candidate job in squeue
        f_sq_single = f"123456|{self.m_job_name}|RUNNING\n"
        f_runner_single = MockProcessRunner(f_returncode=0, f_stdout=f_sq_single)
        f_adapter_single = SlurmSchedulerAdapter(f_command_runner=SchedulerCommandRunner(f_runner_single))
        f_recovered_single = f_adapter_single.recoverDispatchedSubmission(self.m_job_name)
        self.assertIsNotNone(f_recovered_single)
        self.assertEqual(f_recovered_single.backend, "slurm")
        self.assertEqual(f_recovered_single.job_id, "123456")

        # 3. Exact token matching: partial/prefix match is rejected
        f_sq_prefix = f"123456|{self.m_job_name}-extra|RUNNING\n"
        f_runner_prefix = MockProcessRunner(f_returncode=0, f_stdout=f_sq_prefix)
        f_adapter_prefix = SlurmSchedulerAdapter(f_command_runner=SchedulerCommandRunner(f_runner_prefix))
        f_recovered_prefix = f_adapter_prefix.recoverDispatchedSubmission(self.m_job_name)
        self.assertIsNone(f_recovered_prefix)

        # 4. Multiple distinct candidate jobs in squeue + sacct raises error (fails closed)
        def handler_multi(f_argv: Sequence[str]) -> ProcessResult:
            if "squeue" in f_argv:
                return ProcessResult(0, f"123456|{self.m_job_name}|RUNNING\n", "", 0.01)
            elif "sacct" in f_argv:
                return ProcessResult(0, f"789012|{self.m_job_name}|COMPLETED|0:0\n", "", 0.01)
            return ProcessResult(0, "", "", 0.01)

        f_runner_multi = MockProcessRunner(f_custom_handler=handler_multi)
        f_adapter_multi = SlurmSchedulerAdapter(f_command_runner=SchedulerCommandRunner(f_runner_multi))
        with self.assertRaises(SubmissionDispatchError):
            f_adapter_multi.recoverDispatchedSubmission(self.m_job_name)

        # 5. Union of squeue and sacct finding same candidate de-duplicates to single handle
        def handler_same(f_argv: Sequence[str]) -> ProcessResult:
            if "squeue" in f_argv:
                return ProcessResult(0, f"123456|{self.m_job_name}|RUNNING\n", "", 0.01)
            elif "sacct" in f_argv:
                return ProcessResult(0, f"123456|{self.m_job_name}|RUNNING|0:0\n", "", 0.01)
            return ProcessResult(0, "", "", 0.01)

        f_runner_same = MockProcessRunner(f_custom_handler=handler_same)
        f_adapter_same = SlurmSchedulerAdapter(f_command_runner=SchedulerCommandRunner(f_runner_same))
        f_recovered_same = f_adapter_same.recoverDispatchedSubmission(self.m_job_name)
        self.assertEqual(f_recovered_same.job_id, "123456")

        # 6. Crash recovery in dispatchSubmission when submission_dispatched exists
        f_point = self.m_plan.scale_points[0]
        self.m_evidence_store.recordSubmissionRequested(
            f_point=f_point,
            f_writer_id="control",
            f_payload={"job_name": self.m_job_name},
        )
        self.m_evidence_store.recordSubmissionDispatched(
            f_point=f_point,
            f_writer_id="control",
            f_payload={"job_name": self.m_job_name},
        )

        f_spec = JobSpec(
            f_point_id=f_point.tasks,
            f_script_path="/tmp/job.sh",
            f_working_dir=self.m_temp_dir.name,
            f_job_name=self.m_job_name,
        )

        # Case A: exactly 1 candidate -> recovers and records submission_recorded
        f_adapter_dispatch = SlurmSchedulerAdapter(
            f_command_runner=SchedulerCommandRunner(f_runner_single),
            f_evidence_store=self.m_evidence_store,
        )
        f_res = f_adapter_dispatch.dispatchSubmission(f_point=f_point, f_spec=f_spec)
        self.assertEqual(f_res.job_handle.job_id, "123456")
        self.assertTrue(
            self.m_evidence_store.readSubmissionRecords(f_point)["submission_recorded"].payload.get("recovered")
        )

    def testCancelConfirmationBranches(self) -> None:
        """Tests bounded confirmation polling upon cancel."""
        # 1. Job transitioning to CANCELLED
        f_responses = [
            ProcessResult(0, "", "", 0.01),  # scancel
            ProcessResult(0, "RUNNING\n", "", 0.01),  # squeue 1
            ProcessResult(0, "CANCELLED\n", "", 0.01),  # squeue 2
        ]
        f_runner = MockProcessRunner(f_response_sequence=f_responses)
        f_adapter = SlurmSchedulerAdapter(f_command_runner=SchedulerCommandRunner(f_runner))
        f_final_state = f_adapter.cancelAndConfirm(
            "123456",
            f_poll_interval=0.01,
            f_grace_seconds=5.0,
            f_sleep=lambda _: None,
        )
        self.assertEqual(f_final_state, SchedulerJobState.CANCELLED)

        # 2. Already terminal job (SUCCEEDED) returns immediately
        f_responses_term = [
            ProcessResult(0, "", "", 0.01),  # scancel
            ProcessResult(0, "", "", 0.01),  # squeue (empty, no longer active)
            ProcessResult(0, "123456|COMPLETED|0:0\n", "", 0.01),  # sacct
        ]
        f_runner_term = MockProcessRunner(f_response_sequence=f_responses_term)
        f_adapter_term = SlurmSchedulerAdapter(f_command_runner=SchedulerCommandRunner(f_runner_term))
        f_final_term = f_adapter_term.cancelAndConfirm(
            "123456",
            f_poll_interval=0.01,
            f_grace_seconds=5.0,
            f_sleep=lambda _: None,
        )
        self.assertEqual(f_final_term, SchedulerJobState.SUCCEEDED)

        # 3. Grace period timeout returns UNKNOWN
        f_call_count = 0

        def clock_mock() -> float:
            nonlocal f_call_count
            f_call_count += 1
            return float(f_call_count * 100.0)

        f_runner_timeout = MockProcessRunner(f_returncode=0, f_stdout="RUNNING\n")
        f_adapter_timeout = SlurmSchedulerAdapter(f_command_runner=SchedulerCommandRunner(f_runner_timeout))
        f_final_timeout = f_adapter_timeout.cancelAndConfirm(
            "123456",
            f_poll_interval=0.01,
            f_grace_seconds=10.0,
            f_clock=clock_mock,
            f_sleep=lambda _: None,
        )
        self.assertEqual(f_final_timeout, SchedulerJobState.UNKNOWN)

    def testGoldenVikingViking2Archer2ScriptsUseEndFail(self) -> None:
        """Validates golden scripts across Viking, Viking2, and Archer2 with strict directive order and END,FAIL."""
        # 1. Golden Viking Script (small shape: ppn=1, nodes=8, tasks=8)
        f_script_viking = SlurmScriptRenderer.render(
            f_point=self.m_small_point,
            f_profile=self.m_viking_profile,
            f_worker_executable=self.m_worker_path,
            f_manifest_path=self.m_manifest_path,
            f_job_name=self.m_job_name,
            f_output_path=self.m_output_path,
            f_error_path=self.m_error_path,
            f_account=self.m_account,
            f_mail_user=self.m_mail_user,
            f_mail_mode=SlurmMailMode.END_FAIL,
        )
        f_lines_viking = [f_l.strip() for f_l in f_script_viking.splitlines() if f_l.strip()]
        self.assertEqual(f_lines_viking[0], "#!/bin/bash")
        self.assertEqual(f_lines_viking[1], f"#SBATCH --job-name={self.m_job_name}")
        self.assertEqual(f_lines_viking[2], "#SBATCH --ntasks=8")
        self.assertEqual(f_lines_viking[3], "#SBATCH --nodes=8")
        self.assertEqual(f_lines_viking[4], "#SBATCH --ntasks-per-node=1")
        self.assertEqual(f_lines_viking[5], "#SBATCH --ntasks-per-socket=1")
        self.assertEqual(f_lines_viking[6], "#SBATCH --cpus-per-task=1")
        self.assertEqual(f_lines_viking[7], "#SBATCH --distribution=cyclic:cyclic")
        self.assertEqual(f_lines_viking[8], "#SBATCH --time=04:00:00")  # 2 + 8//3 = 4
        self.assertEqual(f_lines_viking[9], f"#SBATCH --account={self.m_account}")
        self.assertEqual(f_lines_viking[10], f"#SBATCH --mail-user={self.m_mail_user}")
        self.assertEqual(f_lines_viking[11], "#SBATCH --mail-type=END,FAIL")
        self.assertEqual(f_lines_viking[12], "#SBATCH --mem=8gb")
        self.assertEqual(f_lines_viking[13], f"#SBATCH --output={self.m_output_path}")
        self.assertEqual(f_lines_viking[14], f"#SBATCH --error={self.m_error_path}")
        self.assertEqual(f_lines_viking[15], "set -euo pipefail")
        self.assertEqual(f_lines_viking[16], "module purge")
        self.assertEqual(
            f_lines_viking[-1],
            f"exec {self.m_worker_path} allocation {self.m_manifest_path} 0-tasks-8",
        )

        # 2. Golden Viking2 Script (large shape: ppn=4, nodes=2, tasks=8)
        f_script_viking2 = SlurmScriptRenderer.render(
            f_point=self.m_large_point,
            f_profile=self.m_viking2_profile,
            f_worker_executable=self.m_worker_path,
            f_manifest_path=self.m_manifest_path,
            f_job_name=self.m_job_name,
            f_output_path=self.m_output_path,
            f_error_path=self.m_error_path,
            f_account=self.m_account,
            f_mail_user=self.m_mail_user,
            f_mail_mode=SlurmMailMode.END_FAIL,
        )
        f_lines_viking2 = [f_l.strip() for f_l in f_script_viking2.splitlines() if f_l.strip()]
        self.assertEqual(f_lines_viking2[0], "#!/bin/bash")
        self.assertEqual(f_lines_viking2[1], f"#SBATCH --job-name={self.m_job_name}")
        self.assertEqual(f_lines_viking2[2], "#SBATCH --ntasks=8")
        self.assertEqual(f_lines_viking2[3], "#SBATCH --nodes=2")
        self.assertEqual(f_lines_viking2[4], "#SBATCH --ntasks-per-node=4")
        self.assertEqual(f_lines_viking2[5], "#SBATCH --ntasks-per-socket=2")
        self.assertEqual(f_lines_viking2[6], "#SBATCH --ntasks-per-core=1")
        self.assertEqual(f_lines_viking2[7], "#SBATCH --distribution=cyclic:cyclic")
        self.assertEqual(f_lines_viking2[8], "#SBATCH --time=02:00:00")  # 2 + 2//3 = 2
        self.assertEqual(f_lines_viking2[9], f"#SBATCH --account={self.m_account}")
        self.assertEqual(f_lines_viking2[10], f"#SBATCH --mail-user={self.m_mail_user}")
        self.assertEqual(f_lines_viking2[11], "#SBATCH --mail-type=END,FAIL")
        self.assertEqual(f_lines_viking2[12], "#SBATCH --mem=8gb")
        self.assertEqual(f_lines_viking2[13], f"#SBATCH --output={self.m_output_path}")
        self.assertEqual(f_lines_viking2[14], f"#SBATCH --error={self.m_error_path}")
        self.assertEqual(f_lines_viking2[15], "set -euo pipefail")

        # 3. Golden Archer2 Script (small shape: ppn=1, nodes=8, tasks=8, partition=standard, qos=standard, NO mem)
        f_script_archer2 = SlurmScriptRenderer.render(
            f_point=self.m_small_point,
            f_profile=self.m_archer2_profile,
            f_worker_executable=self.m_worker_path,
            f_manifest_path=self.m_manifest_path,
            f_job_name=self.m_job_name,
            f_output_path=self.m_output_path,
            f_error_path=self.m_error_path,
            f_account=self.m_account,
            f_mail_user=self.m_mail_user,
            f_mail_mode=SlurmMailMode.END_FAIL,
        )
        f_lines_archer2 = [f_l.strip() for f_l in f_script_archer2.splitlines() if f_l.strip()]
        self.assertEqual(f_lines_archer2[0], "#!/bin/bash")
        self.assertEqual(f_lines_archer2[1], f"#SBATCH --job-name={self.m_job_name}")
        self.assertEqual(f_lines_archer2[2], "#SBATCH --ntasks=8")
        self.assertEqual(f_lines_archer2[3], "#SBATCH --nodes=8")
        self.assertEqual(f_lines_archer2[4], "#SBATCH --ntasks-per-node=1")
        self.assertEqual(f_lines_archer2[5], "#SBATCH --ntasks-per-socket=1")
        self.assertEqual(f_lines_archer2[6], "#SBATCH --cpus-per-task=1")
        self.assertEqual(f_lines_archer2[7], "#SBATCH --distribution=cyclic:cyclic")
        self.assertEqual(f_lines_archer2[8], "#SBATCH --time=04:00:00")
        self.assertEqual(f_lines_archer2[9], f"#SBATCH --account={self.m_account}")
        self.assertEqual(f_lines_archer2[10], f"#SBATCH --mail-user={self.m_mail_user}")
        self.assertEqual(f_lines_archer2[11], "#SBATCH --mail-type=END,FAIL")
        self.assertEqual(f_lines_archer2[12], "#SBATCH --partition=standard")
        self.assertEqual(f_lines_archer2[13], "#SBATCH --qos=standard")
        self.assertFalse(any("--mem=" in f_l for f_l in f_lines_archer2))
        self.assertEqual(f_lines_archer2[14], f"#SBATCH --output={self.m_output_path}")
        self.assertEqual(f_lines_archer2[15], f"#SBATCH --error={self.m_error_path}")
        self.assertEqual(f_lines_archer2[16], "set -euo pipefail")

    def testRejectsPbsRawAndInjectedMailModes(self) -> None:
        """Asserts rejection of PbsMailMode, raw strings, cross-backend, or injected mail values."""
        # 1. PbsMailMode passed to Slurm renderer
        with self.assertRaises(SchedulerScriptError):
            SlurmScriptRenderer.renderDirectives(
                f_point=self.m_small_point,
                f_profile=self.m_viking_profile,
                f_job_name=self.m_job_name,
                f_output_path=self.m_output_path,
                f_error_path=self.m_error_path,
                f_mail_mode=PbsMailMode.ABE,
            )

        # 2. Raw strings
        with self.assertRaises(SchedulerScriptError):
            SlurmScriptRenderer.renderDirectives(
                f_point=self.m_small_point,
                f_profile=self.m_viking_profile,
                f_job_name=self.m_job_name,
                f_output_path=self.m_output_path,
                f_error_path=self.m_error_path,
                f_mail_mode="END,FAIL",
            )

        with self.assertRaises(SchedulerScriptError):
            SlurmScriptRenderer.renderDirectives(
                f_point=self.m_small_point,
                f_profile=self.m_viking_profile,
                f_job_name=self.m_job_name,
                f_output_path=self.m_output_path,
                f_error_path=self.m_error_path,
                f_mail_mode="abe",
            )

        # 3. Injected values
        with self.assertRaises(SchedulerScriptError):
            SlurmScriptRenderer.renderDirectives(
                f_point=self.m_small_point,
                f_profile=self.m_viking_profile,
                f_job_name=self.m_job_name,
                f_output_path=self.m_output_path,
                f_error_path=self.m_error_path,
                f_mail_mode="END,FAIL\n#SBATCH --account=evil",
            )

    def testComputedWalltimeBoundaries(self) -> None:
        """Validates computed walltime formatting across all node boundaries."""
        # 2 + nodes // 3 hours
        f_expected_walltimes = {
            1: "02:00:00",
            2: "02:00:00",
            3: "03:00:00",
            4: "03:00:00",
            8: "04:00:00",
            16: "07:00:00",
            24: "10:00:00",
            32: "12:00:00",
            40: "15:00:00",
            48: "18:00:00",
            64: "23:00:00",
            128: "44:00:00",
            192: "66:00:00",
            256: "87:00:00",
        }
        for f_nodes, f_exp in f_expected_walltimes.items():
            self.assertEqual(
                SlurmScriptRenderer.computeWalltime(f_nodes),
                f_exp,
                msg=f"Walltime calculation failed for nodes: {f_nodes}",
            )

        # Invalid node counts
        with self.assertRaises(SchedulerScriptError):
            SlurmScriptRenderer.computeWalltime(0)
        with self.assertRaises(SchedulerScriptError):
            SlurmScriptRenderer.computeWalltime(-1)
        with self.assertRaises(SchedulerScriptError):
            SlurmScriptRenderer.computeWalltime("8")  # type: ignore

    def testDirectiveAdversaries(self) -> None:
        """Tests prevention of directive injection in job name, account, mail user, and paths."""
        # 1. Job name injection
        f_bad_names = [
            "lm-job\n#SBATCH --account=evil",
            "lm-job\r\n#SBATCH --mem=999",
            "lm-job\0",
            "lm-job; scancel 123",
            "lm-job`rm -rf /`",
        ]
        for f_bad in f_bad_names:
            with self.assertRaises(SchedulerScriptError):
                SlurmScriptRenderer.renderDirectives(
                    f_point=self.m_small_point,
                    f_profile=self.m_viking_profile,
                    f_job_name=f_bad,
                    f_output_path=self.m_output_path,
                    f_error_path=self.m_error_path,
                )

        # 2. Account injection
        f_bad_accounts = [
            "myaccount\n#SBATCH --qos=evil",
            "myaccount\0",
            "myaccount; rm -rf /",
            "myaccount`whoami`",
        ]
        for f_bad in f_bad_accounts:
            with self.assertRaises(SchedulerScriptError):
                SlurmScriptRenderer.renderDirectives(
                    f_point=self.m_small_point,
                    f_profile=self.m_viking_profile,
                    f_job_name=self.m_job_name,
                    f_output_path=self.m_output_path,
                    f_error_path=self.m_error_path,
                    f_account=f_bad,
                )

        # 3. Mail user injection
        f_bad_emails = [
            "user@example.com\n#SBATCH --evil=1",
            "user@example.com\0",
            "not-an-email",
            "user@example.com; scancel 123",
        ]
        for f_bad in f_bad_emails:
            with self.assertRaises(SchedulerScriptError):
                SlurmScriptRenderer.renderDirectives(
                    f_point=self.m_small_point,
                    f_profile=self.m_viking_profile,
                    f_job_name=self.m_job_name,
                    f_output_path=self.m_output_path,
                    f_error_path=self.m_error_path,
                    f_mail_user=f_bad,
                )

        # 4. Path injection & non-absolute paths
        f_bad_paths = [
            "relative/path/out.log",
            "/tmp/out.log\n#SBATCH --evil",
            "/tmp/out.log\0",
            "/tmp/out.log; rm -rf /",
            "/tmp/out.log`id`",
        ]
        for f_bad in f_bad_paths:
            with self.assertRaises(SchedulerScriptError):
                SlurmScriptRenderer.renderDirectives(
                    f_point=self.m_small_point,
                    f_profile=self.m_viking_profile,
                    f_job_name=self.m_job_name,
                    f_output_path=f_bad,
                    f_error_path=self.m_error_path,
                )


if __name__ == "__main__":
    unittest.main()
