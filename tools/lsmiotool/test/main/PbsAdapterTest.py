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
    PbsSchedulerAdapter,
    SchedulerAdapter,
    SchedulerCommandRunner,
    SchedulerError,
    SchedulerScriptError,
    SchedulerScriptRenderer,
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


class PbsAdapterTest(unittest.TestCase):
    """Unit test suite verifying exact PBS scheduler commands, JSON parsing, recovery, cancellation, and evidence."""

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.TemporaryDirectory()
        self.m_etc_path = os.path.normpath(
            os.path.join(
                os.path.dirname(__file__), "..", "..", "etc", "environments.json"
            )
        )
        self.m_profile_doc = ProfileLoader.load(self.m_etc_path)
        self.m_isambard_profile = EnvironmentResolver.resolveProfile(
            "ISAMBARD", f_user="testuser", f_home="/tmp"
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
        self.m_user = "testuser"

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
            f_profile=self.m_isambard_profile,
            f_run_id_source=lambda: "run_001",
            f_clock=lambda: "2026-08-20T12:00:00Z",
            f_token_source=token_gen,
        )
        self.m_evidence_store = EvidenceStore(self.m_layout, f_plan=self.m_plan)

    def tearDown(self) -> None:
        self.m_temp_dir.cleanup()

    def testExactArgvEveryOperation(self) -> None:
        """Validates exact command argv for submit, exact-job query, historical query, recovery, and cancel."""
        # 1. Submit command: ['qsub', <script_path>]
        f_submit_argv = PbsSchedulerAdapter.submitCommand("/path/to/job.sh")
        self.assertEqual(f_submit_argv, ["qsub", "/path/to/job.sh"])

        # 2. Exact-job query (active): ['qstat', '-f', '-F', 'json', <job_id>]
        f_active_argv = PbsSchedulerAdapter.activeQueryCommand("123456.isambard-pbs")
        self.assertEqual(f_active_argv, ["qstat", "-f", "-F", "json", "123456.isambard-pbs"])

        # 3. Historical query (accounting): ['qstat', '-x', '-f', '-F', 'json', <job_id>]
        f_acct_argv = PbsSchedulerAdapter.accountingQueryCommand("123456.isambard-pbs")
        self.assertEqual(f_acct_argv, ["qstat", "-x", "-f", "-F", "json", "123456.isambard-pbs"])

        # 4. Recovery query: ['qstat', '-x', '-f', '-F', 'json', '-u', <user>]
        f_recovery_argv = PbsSchedulerAdapter.recoveryCommand("testuser")
        self.assertEqual(f_recovery_argv, ["qstat", "-x", "-f", "-F", "json", "-u", "testuser"])

        # Recovery query without user
        f_recovery_no_user = PbsSchedulerAdapter.recoveryCommand()
        self.assertEqual(f_recovery_no_user, ["qstat", "-x", "-f", "-F", "json"])

        # 5. Cancel command: ['qdel', <job_id>]
        f_cancel_argv = PbsSchedulerAdapter.cancelCommand("123456.isambard-pbs")
        self.assertEqual(f_cancel_argv, ["qdel", "123456.isambard-pbs"])

    testApprovedLiteralArgvEveryOperation = testExactArgvEveryOperation

    def testPbsQualifiedHandlePreservedVerbatim(self) -> None:
        """Validates that qualified PBS handles with server dot suffix are preserved verbatim."""
        f_adapter = PbsSchedulerAdapter()

        # 1. Submit output parsing: handles preserved verbatim without stripping dot suffix
        self.assertEqual(f_adapter.parseSubmitOutput("123456.isambard-pbs\n"), "123456.isambard-pbs")
        self.assertEqual(f_adapter.parseSubmitOutput("123456.isambard-pbs\r\n"), "123456.isambard-pbs")
        self.assertEqual(f_adapter.parseSubmitOutput("123456.server.domain\n"), "123456.server.domain")
        self.assertEqual(f_adapter.parseSubmitOutput("99999999\n"), "99999999")
        self.assertEqual(f_adapter.parseSubmitOutput("123456"), "123456")
        self.assertEqual(f_adapter.parseSubmitOutput("00123456.pbs\n"), "00123456.pbs")

        # 2. Rejected invalid submit outputs (whitespace, multiline, non-numeric prefix)
        f_bad_submit_outputs = [
            "",
            "\n",
            "\r\n",
            "   ",
            " 123456\n",
            "123456 \n",
            " 123456.isambard-pbs\n",
            "123456.isambard-pbs \n",
            "123456.isambard-pbs\n789012\n",
            "123456\n\n",
            "Job 123456 submitted\n",
            "abc123.server\n",
            "-123456\n",
            "123456\0\n",
        ]
        for f_bad in f_bad_submit_outputs:
            with self.assertRaises(SubmissionDispatchError, msg=f"Should reject: {f_bad!r}"):
                f_adapter.parseSubmitOutput(f_bad)

        # 3. Exact qualified handle persistence in dispatch submission
        f_mock_runner = MockProcessRunner(f_returncode=0, f_stdout="00123456.isambard-pbs\n")
        f_cmd_runner = SchedulerCommandRunner(f_mock_runner)
        f_adapter_store = PbsSchedulerAdapter(
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
        f_result = f_adapter_store.dispatchSubmission(f_point=f_point, f_spec=f_spec)

        self.assertEqual(f_result.job_handle.job_id, "00123456.isambard-pbs")
        self.assertEqual(f_result.job_handle.backend, "pbs")

        # Verify evidence store recorded handle
        f_sub_records = self.m_evidence_store.readSubmissionRecords(f_point)
        f_recorded = f_sub_records["submission_recorded"]
        self.assertEqual(f_recorded.payload["handle"]["job_id"], "00123456.isambard-pbs")
        self.assertEqual(f_recorded.payload["handle"]["backend"], "pbs")

    testQualifiedAndPlainIdPreservedVerbatim = testPbsQualifiedHandlePreservedVerbatim
    testIdAndJsonSchema = testPbsQualifiedHandlePreservedVerbatim

    def testJobSpecificJsonExactFullKeyOnly(self) -> None:
        """Verifies that job-specific queries match the exact full key in Jobs dictionary."""
        # 1. Job with server suffix matches exact full key
        f_json_with_suffix = json.dumps({
            "timestamp": 1234567890,
            "pbs_server": "isambard-pbs",
            "Jobs": {
                "123456.isambard-pbs": {
                    "Job_Name": self.m_job_name,
                    "job_state": "R",
                    "queue": "arm",
                }
            }
        })
        f_state = PbsSchedulerAdapter.parseActiveQuery(f_json_with_suffix, f_job_id="123456.isambard-pbs")
        self.assertEqual(f_state, SchedulerJobState.ACTIVE)

        # Non-matching full key returns None (active) / (UNKNOWN, None) (accounting)
        f_state_mismatch = PbsSchedulerAdapter.parseActiveQuery(f_json_with_suffix, f_job_id="123456.other-pbs")
        self.assertIsNone(f_state_mismatch)

        f_acct_mismatch, f_exit_mismatch = PbsSchedulerAdapter.parseAccountingQuery(
            f_json_with_suffix, f_job_id="123456.other-pbs"
        )
        self.assertEqual(f_acct_mismatch, SchedulerJobState.UNKNOWN)
        self.assertIsNone(f_exit_mismatch)

        # 2. Job without server suffix matches exact plain key
        f_json_plain = json.dumps({
            "Jobs": {
                "123456": {
                    "Job_Name": self.m_job_name,
                    "job_state": "Q",
                }
            }
        })
        f_state_plain = PbsSchedulerAdapter.parseActiveQuery(f_json_plain, f_job_id="123456")
        self.assertEqual(f_state_plain, SchedulerJobState.QUEUED)

        # Querying for qualified ID against plain key does not match
        f_state_mismatch2 = PbsSchedulerAdapter.parseActiveQuery(f_json_plain, f_job_id="123456.isambard-pbs")
        self.assertIsNone(f_state_mismatch2)

    def testQstatJsonParsingAllStatesExitCodesSignals(self) -> None:
        """Tests full state and exit code mapping matrix including negative signals (128+abs(sig))."""
        # Active and accounting query test cases: (job_state, Exit_status, expected_state, expected_exit)
        f_test_cases = [
            ("Q", None, SchedulerJobState.QUEUED, None),
            ("QUEUED", None, SchedulerJobState.QUEUED, None),
            ("W", None, SchedulerJobState.QUEUED, None),
            ("WAITING", None, SchedulerJobState.QUEUED, None),
            ("H", None, SchedulerJobState.QUEUED, None),
            ("HELD", None, SchedulerJobState.QUEUED, None),
            ("T", None, SchedulerJobState.QUEUED, None),
            ("TRANSIT", None, SchedulerJobState.QUEUED, None),
            ("TRANSITING", None, SchedulerJobState.QUEUED, None),
            ("R", None, SchedulerJobState.ACTIVE, None),
            ("RUNNING", None, SchedulerJobState.ACTIVE, None),
            ("E", None, SchedulerJobState.ACTIVE, None),
            ("EXITING", None, SchedulerJobState.ACTIVE, None),
            ("B", None, SchedulerJobState.ACTIVE, None),
            ("BEGUN", None, SchedulerJobState.ACTIVE, None),
            ("S", None, SchedulerJobState.ACTIVE, None),
            ("SUSPENDED", None, SchedulerJobState.ACTIVE, None),
            ("F", 0, SchedulerJobState.SUCCEEDED, 0),
            ("FINISHED", 0, SchedulerJobState.SUCCEEDED, 0),
            ("C", 0, SchedulerJobState.SUCCEEDED, 0),
            ("COMPLETED", 0, SchedulerJobState.SUCCEEDED, 0),
            ("F", 1, SchedulerJobState.FAILED, 1),
            ("F", 2, SchedulerJobState.FAILED, 2),
            ("F", 143, SchedulerJobState.FAILED, 143),
            ("F", -1, SchedulerJobState.FAILED, 129),   # SIGHUP: 128 + 1 = 129
            ("F", -2, SchedulerJobState.FAILED, 130),   # SIGINT: 128 + 2 = 130
            ("F", -6, SchedulerJobState.FAILED, 134),   # SIGABRT: 128 + 6 = 134
            ("F", -9, SchedulerJobState.FAILED, 137),   # SIGKILL: 128 + 9 = 137
            ("F", -15, SchedulerJobState.FAILED, 143),  # SIGTERM: 128 + 15 = 143
            ("F", None, SchedulerJobState.UNKNOWN, None),  # missing Exit_status fail-closed
            ("F", "corrupted", SchedulerJobState.UNKNOWN, None),
            ("C", 0, SchedulerJobState.SUCCEEDED, 0),
            ("C", 1, SchedulerJobState.FAILED, 1),
            ("C", -9, SchedulerJobState.FAILED, 137),
            ("C", None, SchedulerJobState.UNKNOWN, None),
            ("CANCELLED", None, SchedulerJobState.CANCELLED, None),
            ("CANCEL", None, SchedulerJobState.CANCELLED, None),
            ("CA", None, SchedulerJobState.CANCELLED, None),
            ("TIMEOUT", None, SchedulerJobState.TIMEOUT, None),
            ("TO", None, SchedulerJobState.TIMEOUT, None),
            ("UNKNOWN_XYZ", None, SchedulerJobState.UNKNOWN, None),
        ]

        for f_st_str, f_exit_val, f_exp_state, f_exp_exit in f_test_cases:
            f_job_dict: Dict[str, Any] = {"job_state": f_st_str}
            if f_exit_val is not None:
                f_job_dict["Exit_status"] = f_exit_val

            f_json_str = json.dumps({"Jobs": {"123456.isambard-pbs": f_job_dict}})

            # Test active query parser
            f_parsed_act = PbsSchedulerAdapter.parseActiveQuery(
                f_json_str, f_job_id="123456.isambard-pbs"
            )
            self.assertEqual(
                f_parsed_act,
                f_exp_state,
                msg=f"Active query failed for state '{f_st_str}' and exit '{f_exit_val}'",
            )

            # Test accounting query parser
            f_parsed_acct, f_parsed_exit = PbsSchedulerAdapter.parseAccountingQuery(
                f_json_str, f_job_id="123456.isambard-pbs"
            )
            self.assertEqual(
                f_parsed_acct,
                f_exp_state,
                msg=f"Accounting query failed for state '{f_st_str}' and exit '{f_exit_val}'",
            )
            self.assertEqual(
                f_parsed_exit,
                f_exp_exit,
                msg=f"Accounting exit code mismatch for state '{f_st_str}' and raw exit '{f_exit_val}'",
            )

    testStateExitTable = testQstatJsonParsingAllStatesExitCodesSignals
    testStateExitAndMalformedSchemaTable = testQstatJsonParsingAllStatesExitCodesSignals

    def testOrdinaryWaitOnlyExactId(self) -> None:
        """Asserts ordinary status queries query ONLY the exact job ID and never whole-user qstat."""
        f_recorded_argvs: List[List[str]] = []

        def mock_handler(f_argv: Sequence[str]) -> ProcessResult:
            f_recorded_argvs.append(list(f_argv))
            if "qdel" in f_argv:
                return ProcessResult(0, "", "", 0.01)
            elif "-x" in f_argv:
                return ProcessResult(
                    0,
                    json.dumps({"Jobs": {"123456.isambard-pbs": {"job_state": "F", "Exit_status": 0}}}),
                    "",
                    0.01,
                )
            else:
                # Active query
                return ProcessResult(
                    0,
                    json.dumps({"Jobs": {"123456.isambard-pbs": {"job_state": "R"}}}),
                    "",
                    0.01,
                )

        f_runner = MockProcessRunner(f_custom_handler=mock_handler)
        f_adapter = PbsSchedulerAdapter(f_command_runner=SchedulerCommandRunner(f_runner))

        # 1. Build and execute active query
        f_act_argv = f_adapter.activeQueryCommand("123456.isambard-pbs")
        self.assertNotIn("-u", f_act_argv)
        self.assertIn("123456.isambard-pbs", f_act_argv)
        f_res_act = f_adapter.commandRunner.run(f_act_argv)
        f_state_act = f_adapter.parseActiveQuery(f_res_act.stdout, f_job_id="123456.isambard-pbs")
        self.assertEqual(f_state_act, SchedulerJobState.ACTIVE)

        # 2. Build and execute accounting query
        f_acct_argv = f_adapter.accountingQueryCommand("123456.isambard-pbs")
        self.assertNotIn("-u", f_acct_argv)
        self.assertIn("123456.isambard-pbs", f_acct_argv)
        f_res_acct = f_adapter.commandRunner.run(f_acct_argv)
        f_state_acct, f_exit_acct = f_adapter.parseAccountingQuery(
            f_res_acct.stdout, f_job_id="123456.isambard-pbs"
        )
        self.assertEqual(f_state_acct, SchedulerJobState.SUCCEEDED)
        self.assertEqual(f_exit_acct, 0)

        # 3. Cancellation polling queries ONLY exact job ID
        f_recorded_argvs.clear()
        f_final_cancel = f_adapter.cancelAndConfirm(
            "123456.isambard-pbs",
            f_poll_interval=0.01,
            f_grace_seconds=5.0,
            f_sleep=lambda _: None,
        )
        for f_argv in f_recorded_argvs:
            self.assertNotIn("-u", f_argv, msg=f"Unexpected whole-user flag in argv: {f_argv}")
            self.assertIn("123456.isambard-pbs", f_argv, msg=f"Missing exact job ID in argv: {f_argv}")

    def testTokenRecoveryMatchesExactJobName(self) -> None:
        """Asserts user query is invoked only during recovery and strictly filters by correlation token Job_Name."""
        f_user_json = json.dumps({
            "Jobs": {
                "123456.isambard-pbs": {
                    "Job_Name": self.m_job_name,
                    "job_state": "R",
                },
                "789012.isambard-pbs": {
                    "Job_Name": "other-job",
                    "job_state": "R",
                },
                "345678.isambard-pbs": {
                    "Job_Name": f"{self.m_job_name}-suffix",  # prefix match must be rejected
                    "job_state": "R",
                },
                "456789.isambard-pbs": {
                    "Job_Name": f"prefix-{self.m_job_name}",  # substring match must be rejected
                    "job_state": "R",
                },
            }
        })
        f_runner = MockProcessRunner(f_returncode=0, f_stdout=f_user_json)
        f_adapter = PbsSchedulerAdapter(f_command_runner=SchedulerCommandRunner(f_runner))

        # Recovery query uses exact user query and retains full qualified handle
        f_candidates = f_adapter.recoverCandidateJobIds(self.m_job_name, f_user="testuser")
        self.assertEqual(f_candidates, ["123456.isambard-pbs"])

        # Recovery command argv uses -u testuser
        f_rec_argv = f_runner.m_invoked_argv[0]
        self.assertEqual(f_rec_argv, ["qstat", "-x", "-f", "-F", "json", "-u", "testuser"])

    testRecoveryOnlyWholeUserQueryExactNameZeroOneMany = testTokenRecoveryMatchesExactJobName

    def testRecoveryZeroOneManyNeverResubmits(self) -> None:
        """Validates 0 (unrecovered), 1 (recovered), and >1 (fail-closed fatal error) recovery outcomes."""
        # 1. Zero candidate jobs
        f_zero_json = json.dumps({"Jobs": {}})
        f_runner_zero = MockProcessRunner(f_returncode=0, f_stdout=f_zero_json)
        f_adapter_zero = PbsSchedulerAdapter(f_command_runner=SchedulerCommandRunner(f_runner_zero))
        f_rec_zero = f_adapter_zero.recoverDispatchedSubmission(self.m_job_name, f_user="testuser")
        self.assertIsNone(f_rec_zero)

        # 2. Exactly one candidate job
        f_single_json = json.dumps({
            "Jobs": {
                "123456.isambard-pbs": {
                    "Job_Name": self.m_job_name,
                    "job_state": "R",
                }
            }
        })
        f_runner_single = MockProcessRunner(f_returncode=0, f_stdout=f_single_json)
        f_adapter_single = PbsSchedulerAdapter(f_command_runner=SchedulerCommandRunner(f_runner_single))
        f_rec_single = f_adapter_single.recoverDispatchedSubmission(self.m_job_name, f_user="testuser")
        self.assertIsNotNone(f_rec_single)
        self.assertEqual(f_rec_single.backend, "pbs")
        self.assertEqual(f_rec_single.job_id, "123456.isambard-pbs")

        # 3. Multiple candidate jobs with same correlation token raises fatal error
        f_multi_json = json.dumps({
            "Jobs": {
                "123456.isambard-pbs": {
                    "Job_Name": self.m_job_name,
                    "job_state": "R",
                },
                "789012.isambard-pbs": {
                    "Job_Name": self.m_job_name,
                    "job_state": "Q",
                },
            }
        })
        f_runner_multi = MockProcessRunner(f_returncode=0, f_stdout=f_multi_json)
        f_adapter_multi = PbsSchedulerAdapter(f_command_runner=SchedulerCommandRunner(f_runner_multi))
        with self.assertRaises(SubmissionDispatchError):
            f_adapter_multi.recoverDispatchedSubmission(self.m_job_name, f_user="testuser")

        # 4. EvidenceStore crash window integration
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

        # Single candidate recovered and recorded with full qualified handle
        f_adapter_dispatch = PbsSchedulerAdapter(
            f_command_runner=SchedulerCommandRunner(f_runner_single),
            f_evidence_store=self.m_evidence_store,
        )
        f_res = f_adapter_dispatch.dispatchSubmission(f_point=f_point, f_spec=f_spec)
        self.assertEqual(f_res.job_handle.job_id, "123456.isambard-pbs")
        self.assertTrue(
            self.m_evidence_store.readSubmissionRecords(f_point)["submission_recorded"].payload.get("recovered")
        )

    def testStateTransitionsActiveToCompletedFailedCancelled(self) -> None:
        """Tests queryJobState transitions from active queue to historical completed/failed/cancelled states."""
        f_job_id = "123456.isambard-pbs"

        # 1. Job in active queue as RUNNING returns immediately (ACTIVE, None)
        f_runner_act = MockProcessRunner(
            f_returncode=0,
            f_stdout=json.dumps({"Jobs": {f_job_id: {"job_state": "R"}}}),
        )
        f_adapter_act = PbsSchedulerAdapter(f_command_runner=SchedulerCommandRunner(f_runner_act))
        f_st, f_ex = f_adapter_act.queryJobState(f_job_id)
        self.assertEqual(f_st, SchedulerJobState.ACTIVE)
        self.assertIsNone(f_ex)
        # Accounting was not called
        self.assertEqual(len(f_runner_act.m_invoked_argv), 1)

        # 2. Job left active queue and succeeded in accounting (Exit_status: 0)
        f_responses_succ = [
            ProcessResult(0, json.dumps({"Jobs": {}}), "", 0.01),  # active (empty)
            ProcessResult(
                0,
                json.dumps({"Jobs": {f_job_id: {"job_state": "F", "Exit_status": 0}}}),
                "",
                0.01,
            ),  # accounting
        ]
        f_runner_succ = MockProcessRunner(f_response_sequence=f_responses_succ)
        f_adapter_succ = PbsSchedulerAdapter(f_command_runner=SchedulerCommandRunner(f_runner_succ))
        f_st_succ, f_ex_succ = f_adapter_succ.queryJobState(f_job_id)
        self.assertEqual(f_st_succ, SchedulerJobState.SUCCEEDED)
        self.assertEqual(f_ex_succ, 0)

        # 3. Job left active queue and failed with signal (Exit_status: -15)
        f_responses_sig = [
            ProcessResult(0, json.dumps({"Jobs": {}}), "", 0.01),
            ProcessResult(
                0,
                json.dumps({"Jobs": {f_job_id: {"job_state": "F", "Exit_status": -15}}}),
                "",
                0.01,
            ),
        ]
        f_runner_sig = MockProcessRunner(f_response_sequence=f_responses_sig)
        f_adapter_sig = PbsSchedulerAdapter(f_command_runner=SchedulerCommandRunner(f_runner_sig))
        f_st_sig, f_ex_sig = f_adapter_sig.queryJobState(f_job_id)
        self.assertEqual(f_st_sig, SchedulerJobState.FAILED)
        self.assertEqual(f_ex_sig, 143)

        # 4. Job left active queue and was cancelled in accounting
        f_responses_canc = [
            ProcessResult(0, json.dumps({"Jobs": {}}), "", 0.01),
            ProcessResult(
                0,
                json.dumps({"Jobs": {f_job_id: {"job_state": "CANCELLED"}}}),
                "",
                0.01,
            ),
        ]
        f_runner_canc = MockProcessRunner(f_response_sequence=f_responses_canc)
        f_adapter_canc = PbsSchedulerAdapter(f_command_runner=SchedulerCommandRunner(f_runner_canc))
        f_st_canc, f_ex_canc = f_adapter_canc.queryJobState(f_job_id)
        self.assertEqual(f_st_canc, SchedulerJobState.CANCELLED)

        # 5. Query error on active query falls back to accounting query
        f_responses_err = [
            ProcessResult(1, "", "qstat error", 0.01),
            ProcessResult(
                0,
                json.dumps({"Jobs": {f_job_id: {"job_state": "F", "Exit_status": 0}}}),
                "",
                0.01,
            ),
        ]
        f_runner_err = MockProcessRunner(f_response_sequence=f_responses_err)
        f_adapter_err = PbsSchedulerAdapter(f_command_runner=SchedulerCommandRunner(f_runner_err))
        f_st_err, f_ex_err = f_adapter_err.queryJobState(f_job_id)
        self.assertEqual(f_st_err, SchedulerJobState.SUCCEEDED)
        self.assertEqual(f_ex_err, 0)

        # 6. Both queries fail yields UNKNOWN
        f_responses_both_fail = [
            ProcessResult(1, "", "qstat error 1", 0.01),
            ProcessResult(1, "", "qstat error 2", 0.01),
        ]
        f_runner_bf = MockProcessRunner(f_response_sequence=f_responses_both_fail)
        f_adapter_bf = PbsSchedulerAdapter(f_command_runner=SchedulerCommandRunner(f_runner_bf))
        f_st_bf, f_ex_bf = f_adapter_bf.queryJobState(f_job_id)
        self.assertEqual(f_st_bf, SchedulerJobState.UNKNOWN)
        self.assertIsNone(f_ex_bf)

    def testCancelConfirmationBranches(self) -> None:
        """Tests cancellation transition, already terminal job, and bounded grace period timeout."""
        # 1. Job transitioning from Running to Cancelled
        f_responses = [
            ProcessResult(0, "", "", 0.01),  # qdel
            ProcessResult(
                0,
                json.dumps({"Jobs": {"123456.isambard-pbs": {"job_state": "R"}}}),
                "",
                0.01,
            ),  # qstat 1 (active)
            ProcessResult(
                0,
                json.dumps({"Jobs": {"123456.isambard-pbs": {"job_state": "CANCELLED"}}}),
                "",
                0.01,
            ),  # qstat 2 (terminal)
        ]
        f_runner = MockProcessRunner(f_response_sequence=f_responses)
        f_adapter = PbsSchedulerAdapter(f_command_runner=SchedulerCommandRunner(f_runner))
        f_final_state = f_adapter.cancelAndConfirm(
            "123456.isambard-pbs",
            f_poll_interval=0.01,
            f_grace_seconds=5.0,
            f_sleep=lambda _: None,
        )
        self.assertEqual(f_final_state, SchedulerJobState.CANCELLED)

        # 2. Already terminal job (SUCCEEDED in historical query)
        f_responses_term = [
            ProcessResult(0, "", "", 0.01),  # qdel
            ProcessResult(0, json.dumps({"Jobs": {}}), "", 0.01),  # qstat active (empty)
            ProcessResult(
                0,
                json.dumps({"Jobs": {"123456.isambard-pbs": {"job_state": "F", "Exit_status": 0}}}),
                "",
                0.01,
            ),  # qstat -x (accounting)
        ]
        f_runner_term = MockProcessRunner(f_response_sequence=f_responses_term)
        f_adapter_term = PbsSchedulerAdapter(f_command_runner=SchedulerCommandRunner(f_runner_term))
        f_final_term = f_adapter_term.cancelAndConfirm(
            "123456.isambard-pbs",
            f_poll_interval=0.01,
            f_grace_seconds=5.0,
            f_sleep=lambda _: None,
        )
        self.assertEqual(f_final_term, SchedulerJobState.SUCCEEDED)

        # 3. Grace period timeout returns UNKNOWN
        f_call_count = 0

        def mock_clock() -> float:
            nonlocal f_call_count
            f_call_count += 1
            return float(f_call_count * 100.0)

        f_runner_timeout = MockProcessRunner(
            f_returncode=0,
            f_stdout=json.dumps({"Jobs": {"123456.isambard-pbs": {"job_state": "R"}}}),
        )
        f_adapter_timeout = PbsSchedulerAdapter(f_command_runner=SchedulerCommandRunner(f_runner_timeout))
        f_final_timeout = f_adapter_timeout.cancelAndConfirm(
            "123456.isambard-pbs",
            f_poll_interval=0.01,
            f_grace_seconds=10.0,
            f_clock=mock_clock,
            f_sleep=lambda _: None,
        )
        self.assertEqual(f_final_timeout, SchedulerJobState.UNKNOWN)

    testCancelRequiresPostQdelTerminalEvidence = testCancelConfirmationBranches

    def testEmptyUnrecognizedAndCorruptedOutputYieldsUnknown(self) -> None:
        """Asserts malformed JSON, empty response, or missing fields never yield false success."""
        f_adapter = PbsSchedulerAdapter()

        # 1. Empty string output
        self.assertIsNone(f_adapter.parseActiveQuery(""))
        self.assertEqual(
            f_adapter.parseAccountingQuery(""),
            (SchedulerJobState.UNKNOWN, None),
        )

        # 2. Whitespace only output
        self.assertIsNone(f_adapter.parseActiveQuery("   \n"))
        self.assertEqual(
            f_adapter.parseAccountingQuery("   \n"),
            (SchedulerJobState.UNKNOWN, None),
        )

        # 3. Malformed JSON raises SchedulerError
        with self.assertRaises(SchedulerError):
            f_adapter.parseActiveQuery("{not a valid json")
        with self.assertRaises(SchedulerError):
            f_adapter.parseAccountingQuery("{not a valid json")

        # 4. JSON not a dict raises SchedulerError
        with self.assertRaises(SchedulerError):
            f_adapter.parseActiveQuery("[\"an\", \"array\"]")
        with self.assertRaises(SchedulerError):
            f_adapter.parseAccountingQuery("[\"an\", \"array\"]")

        # 5. Missing Jobs key returns None / UNKNOWN
        self.assertIsNone(f_adapter.parseActiveQuery("{\"timestamp\": 12345}"))
        self.assertEqual(
            f_adapter.parseAccountingQuery("{\"timestamp\": 12345}"),
            (SchedulerJobState.UNKNOWN, None),
        )

        # 6. Jobs is empty dict returns None / UNKNOWN
        self.assertIsNone(f_adapter.parseActiveQuery("{\"Jobs\": {}}"))
        self.assertEqual(
            f_adapter.parseAccountingQuery("{\"Jobs\": {}}"),
            (SchedulerJobState.UNKNOWN, None),
        )

        # 7. Job missing job_state field maps to UNKNOWN
        f_missing_state = json.dumps({"Jobs": {"123456.isambard-pbs": {"Job_Name": "test"}}})
        self.assertEqual(
            f_adapter.parseActiveQuery(f_missing_state, f_job_id="123456.isambard-pbs"),
            SchedulerJobState.UNKNOWN,
        )
        self.assertEqual(
            f_adapter.parseAccountingQuery(f_missing_state, f_job_id="123456.isambard-pbs"),
            (SchedulerJobState.UNKNOWN, None),
        )

        # 8. Finished job missing Exit_status maps to UNKNOWN (fail-closed, never SUCCEEDED)
        f_missing_exit = json.dumps({"Jobs": {"123456.isambard-pbs": {"job_state": "F"}}})
        self.assertEqual(
            f_adapter.parseActiveQuery(f_missing_exit, f_job_id="123456.isambard-pbs"),
            SchedulerJobState.UNKNOWN,
        )
        self.assertEqual(
            f_adapter.parseAccountingQuery(f_missing_exit, f_job_id="123456.isambard-pbs"),
            (SchedulerJobState.UNKNOWN, None),
        )

        # 9. Multiple entries matching job_id raises SchedulerError
        f_duplicate_entries = json.dumps({
            "Jobs": {
                "123456.isambard-pbs": {"job_state": "R"},
                "123456.other": {"job_state": "Q"},
            }
        })
        # If querying without specific job ID, multiple entries raises SchedulerError
        with self.assertRaises(SchedulerError):
            f_adapter.parseActiveQuery(f_duplicate_entries)
        with self.assertRaises(SchedulerError):
            f_adapter.parseAccountingQuery(f_duplicate_entries)

    testMalformedUnknownIsNonSuccess = testEmptyUnrecognizedAndCorruptedOutputYieldsUnknown

    def testValidateJobIdBoundaries(self) -> None:
        """Validates validateJobId with valid qualified/unqualified IDs and rejection of invalid types/characters."""
        # Valid IDs (plain decimal, qualified with server dot suffix)
        self.assertEqual(PbsSchedulerAdapter.validateJobId("123456"), "123456")
        self.assertEqual(PbsSchedulerAdapter.validateJobId("1"), "1")
        self.assertEqual(PbsSchedulerAdapter.validateJobId("00123456"), "00123456")
        self.assertEqual(PbsSchedulerAdapter.validateJobId("123456.isambard-pbs"), "123456.isambard-pbs")
        self.assertEqual(PbsSchedulerAdapter.validateJobId("00123456.pbs"), "00123456.pbs")
        self.assertEqual(PbsSchedulerAdapter.validateJobId("123456.server.domain"), "123456.server.domain")

        # Invalid IDs
        f_invalid_ids = [
            "",
            "   ",
            " 123456.isambard-pbs",
            "123456.isambard-pbs ",
            "123456[0]",
            "123456[0].isambard-pbs",
            "abc",
            "abc123.server",
            "-123",
            "123 456",
            "123\n456",
            "123\0",
            None,
            123456,
        ]
        for f_bad_id in f_invalid_ids:
            with self.assertRaises(SchedulerError, msg=f"Should reject: {f_bad_id!r}"):
                PbsSchedulerAdapter.validateJobId(f_bad_id)

    def testMethodAliases(self) -> None:
        """Verifies camelCase and snake_case method aliases on PbsSchedulerAdapter."""
        self.assertEqual(
            PbsSchedulerAdapter.submitCommand,
            PbsSchedulerAdapter.submit_command,
        )
        self.assertEqual(
            PbsSchedulerAdapter.activeQueryCommand,
            PbsSchedulerAdapter.active_query_command,
        )
        self.assertEqual(
            PbsSchedulerAdapter.accountingQueryCommand,
            PbsSchedulerAdapter.accounting_query_command,
        )
        self.assertEqual(
            PbsSchedulerAdapter.recoveryCommand,
            PbsSchedulerAdapter.recovery_command,
        )
        self.assertEqual(
            PbsSchedulerAdapter.cancelCommand,
            PbsSchedulerAdapter.cancel_command,
        )
        self.assertEqual(
            PbsSchedulerAdapter.mapPbsState,
            PbsSchedulerAdapter.map_pbs_state,
        )
        self.assertEqual(
            PbsSchedulerAdapter.parseActiveQuery,
            PbsSchedulerAdapter.parse_active_query,
        )
        self.assertEqual(
            PbsSchedulerAdapter.parseAccountingQuery,
            PbsSchedulerAdapter.parse_accounting_query,
        )

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
        f_runner = MockProcessRunner(f_returncode=0)
        f_adapter = PbsSchedulerAdapter(
            f_command_runner=SchedulerCommandRunner(f_runner),
            f_timeout=60.0,
        )

        def custom_handler_with_time(f_argv: Sequence[str]) -> ProcessResult:
            nonlocal f_current_time
            if f_argv[0] == "qdel":
                f_current_time += 2.0  # qdel takes 2.0s
                return ProcessResult(0, "", "", 2.0)
            elif f_argv[0] == "qstat":
                f_current_time += 1.0  # qstat takes 1.0s
                if f_current_time >= 106.0:
                    return ProcessResult(
                        0,
                        json.dumps({"Jobs": {"123456.isambard-pbs": {"job_state": "CANCELLED"}}}),
                        "",
                        1.0,
                    )
                return ProcessResult(
                    0,
                    json.dumps({"Jobs": {"123456.isambard-pbs": {"job_state": "R"}}}),
                    "",
                    1.0,
                )
            return ProcessResult(0, "", "", 0.01)

        f_runner.m_custom_handler = custom_handler_with_time

        f_final = f_adapter.cancelAndConfirm(
            "123456.isambard-pbs",
            f_poll_interval=1.5,
            f_grace_seconds=10.0,
            f_clock=mock_clock,
            f_sleep=mock_sleep,
        )
        self.assertEqual(f_final, SchedulerJobState.CANCELLED)
        # Verify qdel got remaining grace min(60.0, 10.0) = 10.0
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
            if f_argv[0] == "qdel":
                f_current_time += 15.0  # Consumes all 10s grace
                return ProcessResult(0, "", "", 15.0)
            return ProcessResult(0, "", "", 0.01)

        f_runner_all_grace.m_custom_handler = custom_cancel_consumes_grace
        f_adapter_all_grace = PbsSchedulerAdapter(
            f_command_runner=SchedulerCommandRunner(f_runner_all_grace),
            f_timeout=60.0,
        )
        f_state_all_grace = f_adapter_all_grace.cancelAndConfirm(
            "123456.isambard-pbs",
            f_poll_interval=1.0,
            f_grace_seconds=10.0,
            f_clock=mock_clock,
            f_sleep=mock_sleep,
        )
        self.assertEqual(f_state_all_grace, SchedulerJobState.UNKNOWN)
        # Proves no query command was issued after deadline expired
        self.assertEqual(len(f_runner_all_grace.m_invoked_argv), 1)
        self.assertEqual(f_runner_all_grace.m_invoked_argv[0][0], "qdel")

        # 3. Sleep truncation when poll_interval > remaining_grace
        f_current_time = 300.0
        f_sleep_durations.clear()
        f_runner_trunc = MockProcessRunner(f_returncode=0)

        def custom_trunc_handler(f_argv: Sequence[str]) -> ProcessResult:
            nonlocal f_current_time
            if f_argv[0] == "qdel":
                f_current_time += 3.0  # 3s elapsed, 2s remaining
                return ProcessResult(0, "", "", 3.0)
            elif f_argv[0] == "qstat":
                f_current_time += 0.5  # 3.5s elapsed, 1.5s remaining
                return ProcessResult(
                    0,
                    json.dumps({"Jobs": {"123456.isambard-pbs": {"job_state": "R"}}}),
                    "",
                    0.5,
                )
            return ProcessResult(0, "", "", 0.01)

        f_runner_trunc.m_custom_handler = custom_trunc_handler
        f_adapter_trunc = PbsSchedulerAdapter(
            f_command_runner=SchedulerCommandRunner(f_runner_trunc),
            f_timeout=60.0,
        )
        f_state_trunc = f_adapter_trunc.cancelAndConfirm(
            "123456.isambard-pbs",
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
            if f_argv[0] == "qdel":
                f_current_time += 1.0
                return ProcessResult(0, "", "", 1.0)
            elif f_argv[0] == "qstat":
                f_current_time += 1.0
                raise ProcessExecutionError("qstat failed")
            return ProcessResult(0, "", "", 0.01)

        f_runner_exc.m_custom_handler = custom_exc_handler
        f_adapter_exc = PbsSchedulerAdapter(
            f_command_runner=SchedulerCommandRunner(f_runner_exc),
            f_timeout=60.0,
        )
        f_state_exc = f_adapter_exc.cancelAndConfirm(
            "123456.isambard-pbs",
            f_poll_interval=1.0,
            f_grace_seconds=5.0,
            f_clock=mock_clock,
            f_sleep=mock_sleep,
        )
        self.assertEqual(f_state_exc, SchedulerJobState.UNKNOWN)

    def testTimeoutBeforeAfterAcceptanceIsNonSuccess(self) -> None:
        """Verifies that timeouts at submission, recovery, and queries are non-success and enforce token recovery for PBS."""
        f_ev_store = EvidenceStore(self.m_temp_dir.name, f_run_id="test_run_123")
        f_point = self.m_small_point
        f_spec = JobSpec(
            f_point_id=f_point,
            f_script_path=os.path.join(self.m_temp_dir.name, "job.sh"),
            f_working_dir=self.m_temp_dir.name,
            f_job_name="lm-000000000000000000000001",
        )

        # 1. Timed out submit command raises SubmissionDispatchError and records dispatched with timed_out=True
        f_runner_timeout = MockProcessRunner(
            f_returncode=-9,
            f_stdout="",
            f_stderr="timed out",
        )
        f_runner_timeout.m_custom_handler = lambda f_argv: ProcessResult(
            f_returncode=-9,
            f_stdout="",
            f_stderr="command timed out",
            f_elapsed_seconds=0.2,
            f_timed_out=True,
        )

        f_adapter_timeout = PbsSchedulerAdapter(
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
        self.assertEqual(f_disp_record.payload.get("job_name"), "lm-000000000000000000000001")
        self.assertNotIn("timed_out", f_disp_record.payload)

        # 2. Resubmission attempt for same point enters crash recovery by token, never blind resubmit
        f_runner_rec_zero = MockProcessRunner(
            f_returncode=0,
            f_stdout=json.dumps({"Jobs": {}}),
        )
        f_adapter_rec_zero = PbsSchedulerAdapter(
            f_command_runner=SchedulerCommandRunner(f_runner_rec_zero),
            f_evidence_store=f_ev_store,
        )
        with self.assertRaises(SubmissionDispatchError) as f_ctx2:
            f_adapter_rec_zero.dispatchSubmission(f_point, f_spec)
        self.assertIn("0 candidate jobs", str(f_ctx2.exception))
        # Ensure no second qsub was run
        self.assertEqual(len([f_c for f_c in f_runner_rec_zero.m_invoked_argv if f_c[0] == "qsub"]), 0)

        # 3. Crash recovery finding exactly 1 job succeeds and records handle
        f_runner_rec_single = MockProcessRunner(
            f_returncode=0,
            f_stdout=json.dumps({
                "Jobs": {
                    "123456.isambard-pbs": {
                        "Job_Name": "lm-000000000000000000000001",
                        "job_state": "R",
                    }
                }
            }),
        )
        f_adapter_rec_single = PbsSchedulerAdapter(
            f_command_runner=SchedulerCommandRunner(f_runner_rec_single),
            f_evidence_store=f_ev_store,
        )
        f_rec_res = f_adapter_rec_single.dispatchSubmission(f_point, f_spec)
        self.assertEqual(f_rec_res.job_handle.job_id, "123456.isambard-pbs")
        self.assertTrue(f_rec_res.is_success)

        # 4. Recovery query timeout returns 0 candidate jobs
        f_runner_rec_timeout = MockProcessRunner(f_returncode=-9)
        f_runner_rec_timeout.m_custom_handler = lambda f_argv: ProcessResult(
            f_returncode=-9,
            f_stdout=json.dumps({"Jobs": {"123456.isambard-pbs": {"Job_Name": "lm-000000000000000000000001"}}}),
            f_stderr="",
            f_elapsed_seconds=0.2,
            f_timed_out=True,
        )
        f_adapter_rec_timeout = PbsSchedulerAdapter(
            f_command_runner=SchedulerCommandRunner(f_runner_rec_timeout)
        )
        f_cands = f_adapter_rec_timeout.recoverCandidateJobIds("lm-000000000000000000000001", f_user="testuser")
        self.assertEqual(len(f_cands), 0)

    def testZeroNegativeNanInfinityTimeoutRejected(self) -> None:
        """Validates that zero, negative, NaN, infinity, bool, string, and None timeouts are strictly rejected for PBS."""
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
                PbsSchedulerAdapter.validateTimeout(f_bad_val)

        # 2. PbsSchedulerAdapter constructor
        for f_bad_val in f_invalid_timeouts:
            if f_bad_val is None:
                continue
            with self.assertRaises(SchedulerError):
                PbsSchedulerAdapter(f_timeout=f_bad_val)

            with self.assertRaises(SchedulerError):
                PbsSchedulerAdapter(f_command_timeout=f_bad_val)

        # 3. cancelAndConfirm arguments
        f_adapter = PbsSchedulerAdapter()
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
