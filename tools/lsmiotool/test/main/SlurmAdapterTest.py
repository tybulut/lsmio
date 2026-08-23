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
    validateTimeout,
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

        # 2. Active query command: ['squeue', '--noheader', f'--jobs={job_id}', '--format=%i|%T']
        f_active_argv = SlurmSchedulerAdapter.activeQueryCommand("123456")
        self.assertEqual(
            f_active_argv, ["squeue", "--noheader", "--jobs=123456", "--format=%i|%T"]
        )

        # 3. Accounting query command: ['sacct', '--noheader', '--parsable2', f'--jobs={job_id}', '--format=JobIDRaw,JobName,State,ExitCode']
        f_acct_argv = SlurmSchedulerAdapter.accountingQueryCommand("123456")
        self.assertEqual(
            f_acct_argv,
            [
                "sacct",
                "--noheader",
                "--parsable2",
                "--jobs=123456",
                "--format=JobIDRaw,JobName,State,ExitCode",
            ],
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

    testApprovedLiteralArgvEveryOperation = testExactArgvForEveryOperation

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
        self.assertEqual(
            f_act_argv,
            ["squeue", "--noheader", "--jobs=00123456", "--format=%i|%T"],
        )

        # Assert accounting query uses exact string
        f_acct_argv = f_adapter.accountingQueryCommand(f_result.job_handle.job_id)
        self.assertEqual(
            f_acct_argv,
            [
                "sacct",
                "--noheader",
                "--parsable2",
                "--jobs=00123456",
                "--format=JobIDRaw,JobName,State,ExitCode",
            ],
        )

        # Assert cancel command uses exact string
        f_cancel_argv = f_adapter.cancelCommand(f_result.job_handle.job_id)
        self.assertEqual(f_cancel_argv, ["scancel", "00123456"])

        # Verify evidence store recorded handle
        f_sub_records = self.m_evidence_store.readSubmissionRecords(f_point)
        f_recorded = f_sub_records["submission_recorded"]
        self.assertEqual(f_recorded.payload["handle"]["job_id"], "00123456")
        self.assertEqual(f_recorded.payload["handle"]["backend"], "slurm")

    testExactHandleUnchangedAcrossDispatchWaitCancelEvidence = testExactNumericHandlePersistsThroughQueryAccountingCancelAndEvidence

    def testExactOutputFieldAndRootRowParsing(self) -> None:
        """Verifies root-row extraction and step-row filtering in sacct output."""
        # 1. Standard sacct output with root row and step rows (4-column format)
        f_sacct_output = (
            "123456|lm-0123456789abcdef01234567|COMPLETED|0:0\n"
            "123456.batch|batch|COMPLETED|0:0\n"
            "123456.extern|extern|COMPLETED|0:0\n"
            "123456.0|0|COMPLETED|0:0\n"
            "123456.1|1|COMPLETED|0:0\n"
        )
        f_state, f_exit = SlurmSchedulerAdapter.parseAccountingQuery(f_sacct_output, f_job_id="123456")
        self.assertEqual(f_state, SchedulerJobState.SUCCEEDED)
        self.assertEqual(f_exit, 0)

        # 2. 3-column format (JobIDRaw, State, ExitCode)
        f_sacct_3col = (
            "123456|COMPLETED|0:0\n"
            "123456.batch|COMPLETED|0:0\n"
            "123456.extern|COMPLETED|0:0\n"
        )
        f_state_3, f_exit_3 = SlurmSchedulerAdapter.parseAccountingQuery(f_sacct_3col, f_job_id="123456")
        self.assertEqual(f_state_3, SchedulerJobState.SUCCEEDED)
        self.assertEqual(f_exit_3, 0)

        # 3. Filtering specific root row when other jobs exist in output
        f_multi_job_output = (
            "789012|other-job|FAILED|1:0\n"
            "789012.batch|batch|FAILED|1:0\n"
            "123456|lm-0123456789abcdef01234567|COMPLETED|0:0\n"
            "123456.batch|batch|COMPLETED|0:0\n"
        )
        f_state_match, f_exit_match = SlurmSchedulerAdapter.parseAccountingQuery(
            f_multi_job_output, f_job_id="123456"
        )
        self.assertEqual(f_state_match, SchedulerJobState.SUCCEEDED)
        self.assertEqual(f_exit_match, 0)

        # 4. Step row malformed (missing fields) causes error
        f_corrupt_step = (
            "123456|lm-job|COMPLETED|0:0\n"
            "123456.batch|COMPLETED\n"
        )
        with self.assertRaises(SchedulerError):
            SlurmSchedulerAdapter.parseAccountingQuery(f_corrupt_step, f_job_id="123456")

        # 5. Conflicting root rows for same job ID causes error
        f_conflict_roots = (
            "123456|lm-job|COMPLETED|0:0\n"
            "123456|lm-job|FAILED|1:0\n"
        )
        with self.assertRaises(SchedulerError):
            SlurmSchedulerAdapter.parseAccountingQuery(f_conflict_roots, f_job_id="123456")

        # 6. No matching root row returns UNKNOWN
        f_no_match = "789012|other-job|COMPLETED|0:0\n"
        f_state_un, f_exit_un = SlurmSchedulerAdapter.parseAccountingQuery(f_no_match, f_job_id="123456")
        self.assertEqual(f_state_un, SchedulerJobState.UNKNOWN)
        self.assertIsNone(f_exit_un)

    testAccountingFourFieldsRootStepsCardinality = testExactOutputFieldAndRootRowParsing

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
            f_parsed = SlurmSchedulerAdapter.parseActiveQuery(f"123456|{f_state_str}\n")
            self.assertEqual(
                f_parsed,
                f_expected_state,
                msg=f"Active query failed for state: {f_state_str}",
            )

        # Test accounting queries (sacct: JobIDRaw|JobName|State|ExitCode)
        f_acct_cases = [
            ("123456|lm-job|PENDING|0:0", SchedulerJobState.QUEUED, 0),
            ("123456|lm-job|CONFIGURING|0:0", SchedulerJobState.QUEUED, 0),
            ("123456|lm-job|RUNNING|0:0", SchedulerJobState.ACTIVE, 0),
            ("123456|lm-job|COMPLETING|0:0", SchedulerJobState.ACTIVE, 0),
            ("123456|lm-job|SUSPENDED|0:0", SchedulerJobState.ACTIVE, 0),
            ("123456|lm-job|COMPLETED|0:0", SchedulerJobState.SUCCEEDED, 0),
            ("123456|lm-job|COMPLETED|1:0", SchedulerJobState.FAILED, 1),
            ("123456|lm-job|COMPLETED|2:0", SchedulerJobState.FAILED, 2),
            ("123456|lm-job|COMPLETED|0:15", SchedulerJobState.FAILED, 143),
            ("123456|lm-job|FAILED|1:0", SchedulerJobState.FAILED, 1),
            ("123456|lm-job|BOOT_FAIL|0:0", SchedulerJobState.FAILED, 0),
            ("123456|lm-job|NODE_FAIL|0:0", SchedulerJobState.FAILED, 0),
            ("123456|lm-job|OUT_OF_MEMORY|0:0", SchedulerJobState.FAILED, 0),
            ("123456|lm-job|DEADLINE|0:0", SchedulerJobState.FAILED, 0),
            ("123456|lm-job|PREEMPTED|0:0", SchedulerJobState.FAILED, 0),
            ("123456|lm-job|REVOKED|0:0", SchedulerJobState.FAILED, 0),
            ("123456|lm-job|SPECIAL_EXIT|0:0", SchedulerJobState.FAILED, 0),
            ("123456|lm-job|CANCELLED|0:0", SchedulerJobState.CANCELLED, 0),
            ("123456|lm-job|CANCELLED by 1000|0:0", SchedulerJobState.CANCELLED, 0),
            ("123456|lm-job|TIMEOUT|0:0", SchedulerJobState.TIMEOUT, 0),
            ("123456|lm-job|UNKNOWN_XYZ|0:0", SchedulerJobState.UNKNOWN, 0),
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

    testStateExitTableAndUnknownNonSuccess = testStateExitTable

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

    testRecoveryManifestUtcExactNameZeroOneMany = testRecoveryZeroOneManyExactTokenNeverResubmits

    def testCancelConfirmationBranches(self) -> None:
        """Tests bounded confirmation polling upon cancel."""
        # 1. Job transitioning to CANCELLED
        f_responses = [
            ProcessResult(0, "", "", 0.01),  # scancel
            ProcessResult(0, "123456|RUNNING\n", "", 0.01),  # squeue 1
            ProcessResult(0, "123456|CANCELLED\n", "", 0.01),  # squeue 2
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
            ProcessResult(0, "123456|lm-job|COMPLETED|0:0\n", "", 0.01),  # sacct
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

        f_runner_timeout = MockProcessRunner(f_returncode=0, f_stdout="123456|RUNNING\n")
        f_adapter_timeout = SlurmSchedulerAdapter(f_command_runner=SchedulerCommandRunner(f_runner_timeout))
        f_final_timeout = f_adapter_timeout.cancelAndConfirm(
            "123456",
            f_poll_interval=0.01,
            f_grace_seconds=10.0,
            f_clock=clock_mock,
            f_sleep=lambda _: None,
        )
        self.assertEqual(f_final_timeout, SchedulerJobState.UNKNOWN)

    def testSqueueParsingValidMalformedTokenCounts(self) -> None:
        """Tests pipe-delimited squeue parsing across valid token counts (2, 3, 7) and strict rejection of malformed outputs."""
        # 1. Valid 2 tokens: %i|%T
        self.assertEqual(
            SlurmSchedulerAdapter.parseActiveQuery("123456|RUNNING\n"),
            SchedulerJobState.ACTIVE,
        )
        self.assertEqual(
            SlurmSchedulerAdapter.parseActiveQuery("123456|PENDING\n"),
            SchedulerJobState.QUEUED,
        )

        # 2. Valid 3 tokens: %i|%j|%T
        self.assertEqual(
            SlurmSchedulerAdapter.parseActiveQuery("123456|lm-job|CONFIGURING\n"),
            SchedulerJobState.QUEUED,
        )

        # 3. Valid 7 tokens: %i|%T|%M|%l|%j|%u|%b
        self.assertEqual(
            SlurmSchedulerAdapter.parseActiveQuery("123456|RUNNING|00:10|01:00|lm-job|sbulut|nodes\n"),
            SchedulerJobState.ACTIVE,
        )

        # 4. Array job ID handles: 123456_0 or 123456
        self.assertEqual(
            SlurmSchedulerAdapter.parseActiveQuery("123456_0|RUNNING\n", f_job_id="123456"),
            SchedulerJobState.ACTIVE,
        )
        self.assertEqual(
            SlurmSchedulerAdapter.parseActiveQuery("123456_1|RUNNING\n", f_job_id="123456"),
            SchedulerJobState.ACTIVE,
        )

        # 5. Malformed token counts raise SchedulerError
        f_malformed_token_counts = [
            "RUNNING\n",  # 1 token
            "123456|a|b|RUNNING\n",  # 4 tokens
            "123456|a|b|c|RUNNING\n",  # 5 tokens
            "123456|a|b|c|d|RUNNING\n",  # 6 tokens
            "123456|a|b|c|d|e|f|RUNNING\n",  # 8 tokens
        ]
        for f_bad in f_malformed_token_counts:
            with self.assertRaises(SchedulerError, msg=f"Should reject token count: {f_bad!r}"):
                SlurmSchedulerAdapter.parseActiveQuery(f_bad)

        # 6. Malformed Job IDs raise SchedulerError
        f_bad_ids = [
            "abc|RUNNING\n",
            "123.456|RUNNING\n",
            "-123|RUNNING\n",
            "123;cluster|RUNNING\n",
        ]
        for f_bad in f_bad_ids:
            with self.assertRaises(SchedulerError, msg=f"Should reject Job ID: {f_bad!r}"):
                SlurmSchedulerAdapter.parseActiveQuery(f_bad)

        # 7. Empty output and headers
        self.assertIsNone(SlurmSchedulerAdapter.parseActiveQuery(""))
        self.assertIsNone(SlurmSchedulerAdapter.parseActiveQuery("   \n\t  \n"))
        self.assertIsNone(SlurmSchedulerAdapter.parseActiveQuery("JOBID|STATE\n"))

        # 8. Non-string input raises SchedulerError
        with self.assertRaises(SchedulerError):
            SlurmSchedulerAdapter.parseActiveQuery(123)  # type: ignore

    def testSacctParsingAllStatesExitCodesSignals(self) -> None:
        """Tests sacct parsing across all supported column counts, states, flags, exit codes, and signal numbers."""
        # 1. Supported column formats (4, 3, 5, 10 tokens)
        self.assertEqual(
            SlurmSchedulerAdapter.parseAccountingQuery("123456|lm-job|COMPLETED|0:0\n", f_job_id="123456"),
            (SchedulerJobState.SUCCEEDED, 0),
        )
        self.assertEqual(
            SlurmSchedulerAdapter.parseAccountingQuery("123456|COMPLETED|0:0\n", f_job_id="123456"),
            (SchedulerJobState.SUCCEEDED, 0),
        )
        self.assertEqual(
            SlurmSchedulerAdapter.parseAccountingQuery(
                "123456|lm-job|COMPLETED|0:0|2026-08-20T12:00:00\n", f_job_id="123456"
            ),
            (SchedulerJobState.SUCCEEDED, 0),
        )
        self.assertEqual(
            SlurmSchedulerAdapter.parseAccountingQuery(
                "123456|COMPLETED|0:0|00:05:00|4|1|node1|2026-08-20|2026-08-20|2026-08-20\n",
                f_job_id="123456",
            ),
            (SchedulerJobState.SUCCEEDED, 0),
        )

        # 2. Exit codes and signal parsing
        f_exit_cases = [
            ("0:0", SchedulerJobState.SUCCEEDED, 0),
            ("1:0", SchedulerJobState.FAILED, 1),
            ("2:0", SchedulerJobState.FAILED, 2),
            ("127:0", SchedulerJobState.FAILED, 127),
            ("0:9", SchedulerJobState.FAILED, 137),  # 128 + 9 = 137 (SIGKILL)
            ("0:15", SchedulerJobState.FAILED, 143),  # 128 + 15 = 143 (SIGTERM)
            ("0:2", SchedulerJobState.FAILED, 130),  # 128 + 2 = 130 (SIGINT)
            ("0:6", SchedulerJobState.FAILED, 134),  # 128 + 6 = 134 (SIGABRT)
            ("0", SchedulerJobState.SUCCEEDED, 0),
            ("42", SchedulerJobState.FAILED, 42),
        ]
        for f_exit_str, f_exp_state, f_exp_code in f_exit_cases:
            f_row = f"123456|lm-job|COMPLETED|{f_exit_str}\n"
            f_st, f_ec = SlurmSchedulerAdapter.parseAccountingQuery(f_row, f_job_id="123456")
            self.assertEqual(f_st, f_exp_state, msg=f"State mismatch for exit string: {f_exit_str}")
            self.assertEqual(f_ec, f_exp_code, msg=f"Exit code mismatch for exit string: {f_exit_str}")

        # 3. State flags: COMPLETED+, FAILED+, CANCELLED by 123
        self.assertEqual(
            SlurmSchedulerAdapter.parseAccountingQuery("123456|lm-job|COMPLETED+|0:0\n", f_job_id="123456"),
            (SchedulerJobState.SUCCEEDED, 0),
        )
        self.assertEqual(
            SlurmSchedulerAdapter.parseAccountingQuery("123456|lm-job|FAILED+|1:0\n", f_job_id="123456"),
            (SchedulerJobState.FAILED, 1),
        )
        self.assertEqual(
            SlurmSchedulerAdapter.parseAccountingQuery("123456|lm-job|CANCELLED by 12345|0:0\n", f_job_id="123456"),
            (SchedulerJobState.CANCELLED, 0),
        )

        # 4. Malformed exit codes and column counts
        with self.assertRaises(SchedulerError):
            SlurmSchedulerAdapter.parseAccountingQuery("123456|lm-job|COMPLETED|invalid_exit\n")
        with self.assertRaises(SchedulerError):
            SlurmSchedulerAdapter.parseAccountingQuery("123456|lm-job|COMPLETED|0:invalid_sig\n")
        with self.assertRaises(SchedulerError):
            SlurmSchedulerAdapter.parseAccountingQuery("123456|COMPLETED\n")  # 2 columns
        with self.assertRaises(SchedulerError):
            SlurmSchedulerAdapter.parseAccountingQuery("123456|a|b|c|d|COMPLETED\n")  # 6 columns

    def testActiveExactIdZeroOneAndMalformedMany(self) -> None:
        """Tests zero, one, and conflicting active records, as well as malformed lines."""
        # Zero rows -> None
        self.assertIsNone(SlurmSchedulerAdapter.parseActiveQuery("", f_job_id="123456"))
        self.assertIsNone(SlurmSchedulerAdapter.parseActiveQuery("999999|RUNNING\n", f_job_id="123456"))

        # One matching row
        self.assertEqual(
            SlurmSchedulerAdapter.parseActiveQuery("123456|RUNNING\n", f_job_id="123456"),
            SchedulerJobState.ACTIVE,
        )

        # Multiple rows with conflicting states for same job ID raises SchedulerError
        f_conflict = "123456|RUNNING\n123456|CANCELLED\n"
        with self.assertRaises(SchedulerError):
            SlurmSchedulerAdapter.parseActiveQuery(f_conflict, f_job_id="123456")

        # Malformed lines raise SchedulerError
        with self.assertRaises(SchedulerError):
            SlurmSchedulerAdapter.parseActiveQuery("123456\n", f_job_id="123456")

    def testTokenRecoveryMatchesExactJobName(self) -> None:
        """Tests that token recovery matches exact job name / correlation token and ignores non-exact candidates."""
        f_target_token = "lm-0123456789abcdef01234567"
        f_squeue_out = (
            f"123456|{f_target_token}|RUNNING\n"
            f"123457|{f_target_token}-extra|RUNNING\n"
            f"123458|prefix-{f_target_token}|RUNNING\n"
            f"123459|other-token|RUNNING\n"
        )
        f_sacct_out = (
            f"123456|{f_target_token}|RUNNING|0:0\n"
            f"123460|{f_target_token}_suffix|COMPLETED|0:0\n"
        )

        def recovery_handler(f_argv: Sequence[str]) -> ProcessResult:
            if "squeue" in f_argv:
                return ProcessResult(0, f_squeue_out, "", 0.01)
            elif "sacct" in f_argv:
                return ProcessResult(0, f_sacct_out, "", 0.01)
            return ProcessResult(0, "", "", 0.01)

        f_runner = MockProcessRunner(f_custom_handler=recovery_handler)
        f_adapter = SlurmSchedulerAdapter(f_command_runner=SchedulerCommandRunner(f_runner))
        f_recovered = f_adapter.recoverDispatchedSubmission(f_target_token)

        self.assertIsNotNone(f_recovered)
        self.assertEqual(f_recovered.job_id, "123456")
        self.assertEqual(f_recovered.backend, "slurm")

    def testStateTransitionsActiveToCompletedFailedCancelled(self) -> None:
        """Tests queryJobState orchestration: squeue active, sacct fallback, non-zero query handling."""
        f_adapter = SlurmSchedulerAdapter()

        # Case 1: Active in squeue -> returns (ACTIVE, None)
        f_r1 = MockProcessRunner(f_returncode=0, f_stdout="123456|RUNNING\n")
        f_adapter.m_command_runner = SchedulerCommandRunner(f_r1)
        self.assertEqual(f_adapter.queryJobState("123456"), (SchedulerJobState.ACTIVE, None))

        # Case 2: Queued in squeue -> returns (QUEUED, None)
        f_r2 = MockProcessRunner(f_returncode=0, f_stdout="123456|PENDING\n")
        f_adapter.m_command_runner = SchedulerCommandRunner(f_r2)
        self.assertEqual(f_adapter.queryJobState("123456"), (SchedulerJobState.QUEUED, None))

        # Case 3: Missing in squeue, sacct returns COMPLETED 0:0 -> returns (SUCCEEDED, 0)
        def h_completed(f_argv: Sequence[str]) -> ProcessResult:
            if "squeue" in f_argv:
                return ProcessResult(0, "", "", 0.01)
            elif "sacct" in f_argv:
                return ProcessResult(0, "123456|lm-job|COMPLETED|0:0\n", "", 0.01)
            return ProcessResult(0, "", "", 0.01)

        f_adapter.m_command_runner = SchedulerCommandRunner(MockProcessRunner(f_custom_handler=h_completed))
        self.assertEqual(f_adapter.queryJobState("123456"), (SchedulerJobState.SUCCEEDED, 0))

        # Case 4: squeue fails with non-zero exit, sacct succeeds with FAILED 1:0 -> returns (FAILED, 1)
        def h_squeue_fail(f_argv: Sequence[str]) -> ProcessResult:
            if "squeue" in f_argv:
                return ProcessResult(1, "", "squeue: error: controller not responding\n", 0.01)
            elif "sacct" in f_argv:
                return ProcessResult(0, "123456|lm-job|FAILED|1:0\n", "", 0.01)
            return ProcessResult(0, "", "", 0.01)

        f_adapter.m_command_runner = SchedulerCommandRunner(MockProcessRunner(f_custom_handler=h_squeue_fail))
        self.assertEqual(f_adapter.queryJobState("123456"), (SchedulerJobState.FAILED, 1))

        # Case 5: squeue empty, sacct returns CANCELLED -> returns (CANCELLED, 0)
        def h_cancelled(f_argv: Sequence[str]) -> ProcessResult:
            if "squeue" in f_argv:
                return ProcessResult(0, "", "", 0.01)
            elif "sacct" in f_argv:
                return ProcessResult(0, "123456|lm-job|CANCELLED by 1000|0:0\n", "", 0.01)
            return ProcessResult(0, "", "", 0.01)

        f_adapter.m_command_runner = SchedulerCommandRunner(MockProcessRunner(f_custom_handler=h_cancelled))
        self.assertEqual(f_adapter.queryJobState("123456"), (SchedulerJobState.CANCELLED, 0))

        # Case 6: squeue empty, sacct returns TIMEOUT -> returns (TIMEOUT, 0)
        def h_timeout(f_argv: Sequence[str]) -> ProcessResult:
            if "squeue" in f_argv:
                return ProcessResult(0, "", "", 0.01)
            elif "sacct" in f_argv:
                return ProcessResult(0, "123456|lm-job|TIMEOUT|0:0\n", "", 0.01)
            return ProcessResult(0, "", "", 0.01)

        f_adapter.m_command_runner = SchedulerCommandRunner(MockProcessRunner(f_custom_handler=h_timeout))
        self.assertEqual(f_adapter.queryJobState("123456"), (SchedulerJobState.TIMEOUT, 0))

    def testEmptyUnrecognizedAndCorruptedOutputYieldsUnknown(self) -> None:
        """Tests that empty, unrecognized, or corrupted outputs across queries yield (UNKNOWN, None)."""
        f_adapter = SlurmSchedulerAdapter()

        # Both empty
        def h_empty(f_argv: Sequence[str]) -> ProcessResult:
            return ProcessResult(0, "", "", 0.01)

        f_adapter.m_command_runner = SchedulerCommandRunner(MockProcessRunner(f_custom_handler=h_empty))
        self.assertEqual(f_adapter.queryJobState("123456"), (SchedulerJobState.UNKNOWN, None))

        # Both fail with non-zero exit
        def h_both_fail(f_argv: Sequence[str]) -> ProcessResult:
            return ProcessResult(1, "", "Command failed\n", 0.01)

        f_adapter.m_command_runner = SchedulerCommandRunner(MockProcessRunner(f_custom_handler=h_both_fail))
        self.assertEqual(f_adapter.queryJobState("123456"), (SchedulerJobState.UNKNOWN, None))

        # Corrupted / unparseable outputs
        def h_corrupt(f_argv: Sequence[str]) -> ProcessResult:
            return ProcessResult(0, "corrupted_non_pipe_delimited_output\n", "", 0.01)

        f_adapter.m_command_runner = SchedulerCommandRunner(MockProcessRunner(f_custom_handler=h_corrupt))
        self.assertEqual(f_adapter.queryJobState("123456"), (SchedulerJobState.UNKNOWN, None))

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

    def testCredentialWhitespaceEmptyMalformedAndInjectionRejected(self) -> None:
        """Verifies account and email validator rejection of whitespace, empty, malformed, shell, and injection tokens."""
        # 1. Account validation: valid cases
        f_valid_accounts = ["e281", "proj_01", "account-123.v1", "A1", "my-account_2"]
        for f_acc in f_valid_accounts:
            self.assertEqual(SlurmScriptRenderer.validateAccount(f_acc), f_acc)
            self.assertEqual(SchedulerScriptRenderer.validateAccount(f_acc), f_acc)

        # 1a. Account validation: non-string types
        for f_bad in (None, 123, [], {}, True, False):
            with self.assertRaises(SchedulerScriptError):
                SlurmScriptRenderer.validateAccount(f_bad)

        # 1b. Account validation: empty and whitespace
        for f_bad in ("", "   ", "\t", "\n", "\r\n"):
            with self.assertRaises(SchedulerScriptError):
                SlurmScriptRenderer.validateAccount(f_bad)

        # 1c. Account validation: control characters and NUL
        for f_bad in ("acct\0", "acct\n", "acct\r", "acct\x1f", "acct\x7f"):
            with self.assertRaises(SchedulerScriptError):
                SlurmScriptRenderer.validateAccount(f_bad)

        # 1d. Account validation: directive injection
        for f_bad in (
            "acct\n#SBATCH --export=ALL",
            "acct#SBATCH",
            "acct#PBS",
            "acct\r#SBATCH",
            "acct\n#PBS",
        ):
            with self.assertRaises(SchedulerScriptError):
                SlurmScriptRenderer.validateAccount(f_bad)

        # 1e. Account validation: shell tokens and malformed regex
        for f_bad in (
            "-starts-with-dash",
            ".starts-with-dot",
            "_starts-with-underscore",
            "has space",
            "bad$char",
            "bad@char",
            "bad%char",
            "acct; rm -rf /",
            "acct$(whoami)",
            "acct`whoami`",
            "acct|cat",
            "acct&",
        ):
            with self.assertRaises(SchedulerScriptError):
                SlurmScriptRenderer.validateAccount(f_bad)

        # 2. Mail user validation: valid cases
        f_valid_emails = [
            "user@epcc.ed.ac.uk",
            "admin+tag@sub.domain.org",
            "a.b_c-d@host.net",
            "user123@viking.york.ac.uk",
        ]
        for f_em in f_valid_emails:
            self.assertEqual(SlurmScriptRenderer.validateMailUser(f_em), f_em)
            self.assertEqual(SchedulerScriptRenderer.validateMailUser(f_em), f_em)

        # 2a. Mail user validation: non-string types
        for f_bad in (None, 123, [], {}, True, False):
            with self.assertRaises(SchedulerScriptError):
                SlurmScriptRenderer.validateMailUser(f_bad)

        # 2b. Mail user validation: empty and whitespace
        for f_bad in ("", "   ", "\t", "\n", "\r\n"):
            with self.assertRaises(SchedulerScriptError):
                SlurmScriptRenderer.validateMailUser(f_bad)

        # 2c. Mail user validation: control characters and NUL
        for f_bad in ("u@d.com\0", "u@d.com\n", "u@d.com\r", "u\x01@d.com", "u@d.com\x7f"):
            with self.assertRaises(SchedulerScriptError):
                SlurmScriptRenderer.validateMailUser(f_bad)

        # 2d. Mail user validation: directive injection
        for f_bad in (
            "u@d.com\n#SBATCH --mail-type=ALL",
            "u@d.com#SBATCH",
            "u@d.com#PBS",
            "u@d.com\r#SBATCH",
        ):
            with self.assertRaises(SchedulerScriptError):
                SlurmScriptRenderer.validateMailUser(f_bad)

        # 2e. Mail user validation: shell tokens and malformed regex
        for f_bad in (
            "notanemail",
            "@nodomain.com",
            "user@",
            "user space@domain.com",
            "user@domain with spaces.com",
            "user@@domain.com",
            "u@d.com; scancel 123",
            "u@d.com$(id)",
            "u@d.com`id`",
            "u@d.com|cat",
        ):
            with self.assertRaises(SchedulerScriptError):
                SlurmScriptRenderer.validateMailUser(f_bad)

        # 3. Directives rendering with valid account and email
        f_dirs = SlurmScriptRenderer.renderDirectives(
            f_point=self.m_small_point,
            f_profile=self.m_viking_profile,
            f_job_name=self.m_job_name,
            f_output_path=self.m_output_path,
            f_error_path=self.m_error_path,
            f_account="e281_prj",
            f_mail_user="user@epcc.ed.ac.uk",
            f_mail_mode=SlurmMailMode.END_FAIL,
        )
        self.assertIn("#SBATCH --account=e281_prj", f_dirs)
        self.assertIn("#SBATCH --mail-user=user@epcc.ed.ac.uk", f_dirs)
        self.assertIn("#SBATCH --mail-type=END,FAIL", f_dirs)

        # Exact sequence check: account, mail-user, mail-type
        f_acc_idx = f_dirs.index("#SBATCH --account=e281_prj")
        f_mail_idx = f_dirs.index("#SBATCH --mail-user=user@epcc.ed.ac.uk")
        f_type_idx = f_dirs.index("#SBATCH --mail-type=END,FAIL")
        self.assertEqual(f_mail_idx, f_acc_idx + 1)
        self.assertEqual(f_type_idx, f_mail_idx + 1)

        # 4. Directives rendering rejection with invalid account or email
        with self.assertRaises(SchedulerScriptError):
            SlurmScriptRenderer.renderDirectives(
                f_point=self.m_small_point,
                f_profile=self.m_viking_profile,
                f_job_name=self.m_job_name,
                f_output_path=self.m_output_path,
                f_error_path=self.m_error_path,
                f_account="bad account spaces",
                f_mail_user="user@epcc.ed.ac.uk",
            )

        with self.assertRaises(SchedulerScriptError):
            SlurmScriptRenderer.renderDirectives(
                f_point=self.m_small_point,
                f_profile=self.m_viking_profile,
                f_job_name=self.m_job_name,
                f_output_path=self.m_output_path,
                f_error_path=self.m_error_path,
                f_account="e281_prj",
                f_mail_user="not-an-email",
            )

        # 5. Render job script from JobSpec
        f_spec = JobSpec(
            f_point_id="0-tasks-8",
            f_script_path=os.path.join(self.m_temp_dir.name, "job.sh"),
            f_working_dir=self.m_temp_dir.name,
            f_account="e281_prj",
            f_mail_user="user@epcc.ed.ac.uk",
            f_mail_mode=SlurmMailMode.END_FAIL,
            f_output_path=self.m_output_path,
            f_error_path=self.m_error_path,
            f_job_name=self.m_job_name,
        )
        f_rendered = SlurmScriptRenderer.renderJobScript(
            f_point=self.m_small_point,
            f_profile=self.m_viking_profile,
            f_spec=f_spec,
            f_worker_executable=self.m_worker_path,
            f_manifest_path=os.path.join(self.m_temp_dir.name, "manifest.json"),
        )
        self.assertIn("#SBATCH --account=e281_prj", f_rendered)
        self.assertIn("#SBATCH --mail-user=user@epcc.ed.ac.uk", f_rendered)
        self.assertIn("#SBATCH --mail-type=END,FAIL", f_rendered)

    def testCancelCommandAndQueriesShareOneDeadline(self) -> None:
        """Verifies that cancel and confirmation queries share a single monotonic deadline with min(cmd_timeout, remaining_grace)."""
        f_current_time = 100.0

        def mock_clock() -> float:
            return f_current_time

        f_sleep_durations: List[float] = []

        def mock_sleep(f_dur: float) -> None:
            nonlocal f_current_time
            f_sleep_durations.append(f_dur)
            f_current_time += f_dur

        # 1. Normal cancel-confirm sharing monotonic deadline
        f_runner = MockProcessRunner(f_returncode=0, f_stdout="123456|RUNNING\n")
        f_adapter = SlurmSchedulerAdapter(
            f_command_runner=SchedulerCommandRunner(f_runner),
            f_timeout=60.0,
        )

        def custom_handler_with_time(f_argv: Sequence[str]) -> ProcessResult:
            nonlocal f_current_time
            if f_argv[0] == "scancel":
                f_current_time += 2.0  # scancel takes 2.0s
                return ProcessResult(0, "", "", 2.0)
            elif f_argv[0] == "squeue":
                f_current_time += 1.0  # squeue takes 1.0s
                if f_current_time >= 106.0:
                    return ProcessResult(0, "123456|CANCELLED\n", "", 1.0)
                return ProcessResult(0, "123456|RUNNING\n", "", 1.0)
            return ProcessResult(0, "", "", 0.01)

        f_runner.m_custom_handler = custom_handler_with_time

        f_final = f_adapter.cancelAndConfirm(
            "123456",
            f_poll_interval=1.5,
            f_grace_seconds=10.0,
            f_clock=mock_clock,
            f_sleep=mock_sleep,
        )
        self.assertEqual(f_final, SchedulerJobState.CANCELLED)
        # Verify scancel got remaining grace min(60.0, 10.0) = 10.0
        self.assertEqual(f_runner.m_invoked_kwargs[0].get("f_timeout"), 10.0)
        # Verify subsequent queries received remaining grace bounded by deadline
        for f_kw in f_runner.m_invoked_kwargs[1:]:
            self.assertLessEqual(f_kw.get("f_timeout"), 8.0)
            self.assertGreater(f_kw.get("f_timeout"), 0.0)

        # 2. Cancel command consuming all grace seconds
        f_current_time = 200.0
        f_runner_all_grace = MockProcessRunner()

        def custom_cancel_consumes_grace(f_argv: Sequence[str]) -> ProcessResult:
            nonlocal f_current_time
            if f_argv[0] == "scancel":
                f_current_time += 15.0  # Consumes all 10s grace
                return ProcessResult(0, "", "", 15.0)
            return ProcessResult(0, "", "", 0.01)

        f_runner_all_grace.m_custom_handler = custom_cancel_consumes_grace
        f_adapter_all_grace = SlurmSchedulerAdapter(
            f_command_runner=SchedulerCommandRunner(f_runner_all_grace),
            f_timeout=60.0,
        )
        f_state_all_grace = f_adapter_all_grace.cancelAndConfirm(
            "123456",
            f_poll_interval=1.0,
            f_grace_seconds=10.0,
            f_clock=mock_clock,
            f_sleep=mock_sleep,
        )
        self.assertEqual(f_state_all_grace, SchedulerJobState.UNKNOWN)
        # Proves no query command was issued after deadline expired
        self.assertEqual(len(f_runner_all_grace.m_invoked_argv), 1)
        self.assertEqual(f_runner_all_grace.m_invoked_argv[0][0], "scancel")

        # 3. Sleep truncation when poll_interval > remaining_grace
        f_current_time = 300.0
        f_sleep_durations.clear()
        f_runner_trunc = MockProcessRunner(f_returncode=0, f_stdout="123456|RUNNING\n")

        def custom_trunc_handler(f_argv: Sequence[str]) -> ProcessResult:
            nonlocal f_current_time
            if f_argv[0] == "scancel":
                f_current_time += 3.0  # 3s elapsed, 2s remaining
                return ProcessResult(0, "", "", 3.0)
            elif f_argv[0] == "squeue":
                f_current_time += 0.5  # 3.5s elapsed, 1.5s remaining
                return ProcessResult(0, "123456|RUNNING\n", "", 0.5)
            return ProcessResult(0, "", "", 0.01)

        f_runner_trunc.m_custom_handler = custom_trunc_handler
        f_adapter_trunc = SlurmSchedulerAdapter(
            f_command_runner=SchedulerCommandRunner(f_runner_trunc),
            f_timeout=60.0,
        )
        f_state_trunc = f_adapter_trunc.cancelAndConfirm(
            "123456",
            f_poll_interval=5.0,  # poll interval 5.0 is larger than 1.5s remaining
            f_grace_seconds=5.0,
            f_clock=mock_clock,
            f_sleep=mock_sleep,
        )
        self.assertEqual(f_state_trunc, SchedulerJobState.UNKNOWN)
        self.assertTrue(any(abs(f_d - 1.5) < 1e-4 for f_d in f_sleep_durations))

        # 4. Command exception handling during queries
        f_current_time = 400.0
        f_runner_exc = MockProcessRunner()

        def custom_exc_handler(f_argv: Sequence[str]) -> ProcessResult:
            nonlocal f_current_time
            if f_argv[0] == "scancel":
                f_current_time += 1.0
                return ProcessResult(0, "", "", 1.0)
            elif f_argv[0] == "squeue":
                f_current_time += 1.0
                raise ProcessExecutionError("squeue failed")
            elif f_argv[0] == "sacct":
                f_current_time += 1.0
                raise ProcessExecutionError("sacct failed")
            return ProcessResult(0, "", "", 0.01)

        f_runner_exc.m_custom_handler = custom_exc_handler
        f_adapter_exc = SlurmSchedulerAdapter(
            f_command_runner=SchedulerCommandRunner(f_runner_exc),
            f_timeout=60.0,
        )
        f_state_exc = f_adapter_exc.cancelAndConfirm(
            "123456",
            f_poll_interval=1.0,
            f_grace_seconds=5.0,
            f_clock=mock_clock,
            f_sleep=mock_sleep,
        )
        self.assertEqual(f_state_exc, SchedulerJobState.UNKNOWN)

    def testTimeoutBeforeAfterAcceptanceIsNonSuccess(self) -> None:
        """Verifies that timeouts at submission, recovery, and queries are non-success and enforce token recovery."""
        f_ev_store = EvidenceStore(self.m_temp_dir.name, f_run_id="test_run_123")
        f_point = self.m_small_point
        f_spec = JobSpec(
            f_point_id=f_point,
            f_script_path=os.path.join(self.m_temp_dir.name, "job.sh"),
            f_working_dir=self.m_temp_dir.name,
            f_job_name=self.m_job_name,
        )

        # 1. Timed out submit command raises SubmissionDispatchError and records dispatched with timed_out=True
        f_runner_timeout = MockProcessRunner(
            f_returncode=-9,
            f_stdout="",
            f_stderr="timed out",
        )
        # Mark as timed_out
        def custom_timeout_submit(f_argv: Sequence[str]) -> ProcessResult:
            return ProcessResult(
                f_returncode=-9,
                f_stdout="",
                f_stderr="command timed out",
                f_elapsed_seconds=0.2,
                f_timed_out=True,
            )

        f_runner_timeout.m_custom_handler = custom_timeout_submit
        f_adapter_timeout = SlurmSchedulerAdapter(
            f_command_runner=SchedulerCommandRunner(f_runner_timeout),
            f_evidence_store=f_ev_store,
            f_timeout=10.0,
        )

        with self.assertRaises(SubmissionDispatchError) as f_ctx:
            f_adapter_timeout.dispatchSubmission(f_point, f_spec)
        self.assertIn("timed out", str(f_ctx.exception))

        # Check evidence store has submission_dispatched (pre-spawn record)
        f_records = f_ev_store.readSubmissionRecords(f_point)
        self.assertIsNotNone(f_records["submission_requested"])
        self.assertIsNotNone(f_records["submission_dispatched"])
        self.assertIsNone(f_records["submission_recorded"])
        f_disp_record = f_records["submission_dispatched"]
        self.assertIsNotNone(f_disp_record)
        self.assertEqual(f_disp_record.payload.get("job_name"), self.m_job_name)
        self.assertNotIn("timed_out", f_disp_record.payload)

        # 2. Resubmission attempt for same point enters crash recovery by token, never blind resubmit
        f_runner_rec_zero = MockProcessRunner(f_returncode=0, f_stdout="")
        f_adapter_rec_zero = SlurmSchedulerAdapter(
            f_command_runner=SchedulerCommandRunner(f_runner_rec_zero),
            f_evidence_store=f_ev_store,
        )
        with self.assertRaises(SubmissionDispatchError) as f_ctx2:
            f_adapter_rec_zero.dispatchSubmission(f_point, f_spec)
        self.assertIn("0 candidate jobs", str(f_ctx2.exception))
        # Ensure no second sbatch was run
        self.assertEqual(len([f_c for f_c in f_runner_rec_zero.m_invoked_argv if f_c[0] == "sbatch"]), 0)

        # 3. Crash recovery finding exactly 1 job succeeds and records handle
        f_runner_rec_single = MockProcessRunner(
            f_returncode=0,
            f_stdout=f"123456|{self.m_job_name}|RUNNING\n",
        )
        f_adapter_rec_single = SlurmSchedulerAdapter(
            f_command_runner=SchedulerCommandRunner(f_runner_rec_single),
            f_evidence_store=f_ev_store,
        )
        f_rec_res = f_adapter_rec_single.dispatchSubmission(f_point, f_spec)
        self.assertEqual(f_rec_res.job_handle.job_id, "123456")
        self.assertTrue(f_rec_res.is_success)

        # 4. Recovery query timeout returns 0 candidate jobs
        f_runner_rec_timeout = MockProcessRunner(f_returncode=-9)
        f_runner_rec_timeout.m_custom_handler = lambda f_argv: ProcessResult(
            f_returncode=-9, f_stdout="123456|name|R\n", f_stderr="", f_elapsed_seconds=0.2, f_timed_out=True
        )
        f_adapter_rec_timeout = SlurmSchedulerAdapter(
            f_command_runner=SchedulerCommandRunner(f_runner_rec_timeout)
        )
        f_cands = f_adapter_rec_timeout.recoverCandidateJobIds(self.m_job_name)
        self.assertEqual(len(f_cands), 0)

    def testZeroNegativeNanInfinityTimeoutRejected(self) -> None:
        """Validates that zero, negative, NaN, infinity, bool, string, and None timeouts are strictly rejected."""
        f_invalid_timeouts = [
            0,
            0.0,
            -1,
            -0.001,
            -100.0,
            float("nan"),
            float("inf"),
            float("-inf"),
            True,
            False,
            "120",
            None,
        ]

        # 1. validateTimeout directly
        for f_bad_val in f_invalid_timeouts:
            with self.assertRaises(SchedulerError):
                SlurmSchedulerAdapter.validateTimeout(f_bad_val)

        # 2. SlurmSchedulerAdapter constructor
        for f_bad_val in f_invalid_timeouts:
            if f_bad_val is None:
                continue
            with self.assertRaises(SchedulerError):
                SlurmSchedulerAdapter(f_timeout=f_bad_val)

            with self.assertRaises(SchedulerError):
                SlurmSchedulerAdapter(f_command_timeout=f_bad_val)

        # 3. cancelAndConfirm arguments
        f_adapter = SlurmSchedulerAdapter()
        for f_bad_val in f_invalid_timeouts:
            if f_bad_val is not None:
                with self.assertRaises(SchedulerError):
                    f_adapter.cancelAndConfirm("123456", f_grace_seconds=f_bad_val)

                with self.assertRaises(SchedulerError):
                    f_adapter.cancelAndConfirm("123456", f_timeout=f_bad_val)

            with self.assertRaises(SchedulerError):
                f_adapter.cancelAndConfirm("123456", f_poll_interval=f_bad_val)


if __name__ == "__main__":
    unittest.main()
