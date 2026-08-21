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
        f_active_argv = PbsSchedulerAdapter.activeQueryCommand("123456")
        self.assertEqual(f_active_argv, ["qstat", "-f", "-F", "json", "123456"])

        # 3. Historical query (accounting): ['qstat', '-x', '-f', '-F', 'json', <job_id>]
        f_acct_argv = PbsSchedulerAdapter.accountingQueryCommand("123456")
        self.assertEqual(f_acct_argv, ["qstat", "-x", "-f", "-F", "json", "123456"])

        # 4. Recovery query: ['qstat', '-x', '-f', '-F', 'json', '-u', <user>]
        f_recovery_argv = PbsSchedulerAdapter.recoveryCommand("testuser")
        self.assertEqual(f_recovery_argv, ["qstat", "-x", "-f", "-F", "json", "-u", "testuser"])

        # 5. Cancel command: ['qdel', <job_id>]
        f_cancel_argv = PbsSchedulerAdapter.cancelCommand("123456")
        self.assertEqual(f_cancel_argv, ["qdel", "123456"])

    def testIdAndJsonSchema(self) -> None:
        """Validates parsing of PBS JSON output, handling server suffixes, and extracting exact decimal ID."""
        f_adapter = PbsSchedulerAdapter()

        # 1. Submit output parsing with server suffixes and plain decimal IDs
        self.assertEqual(f_adapter.parseSubmitOutput("123456.isambard-pbs\n"), "123456")
        self.assertEqual(f_adapter.parseSubmitOutput("123456.isambard-pbs\r\n"), "123456")
        self.assertEqual(f_adapter.parseSubmitOutput("123456.server.domain\n"), "123456")
        self.assertEqual(f_adapter.parseSubmitOutput("99999999\n"), "99999999")
        self.assertEqual(f_adapter.parseSubmitOutput("123456"), "123456")
        self.assertEqual(f_adapter.parseSubmitOutput("00123456.pbs\n"), "00123456")

        # 2. Rejected invalid submit outputs (whitespace, multiline, non-numeric)
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

        # 3. JSON schema parsing: job with server suffix in Jobs dictionary
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
        f_state = PbsSchedulerAdapter.parseActiveQuery(f_json_with_suffix, f_job_id="123456")
        self.assertEqual(f_state, SchedulerJobState.ACTIVE)

        # 4. JSON schema parsing: job without server suffix
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

        # 5. Exact numeric handle persistence in dispatch submission
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

        self.assertEqual(f_result.job_handle.job_id, "00123456")
        self.assertEqual(f_result.job_handle.backend, "pbs")

        # Verify evidence store recorded handle
        f_sub_records = self.m_evidence_store.readSubmissionRecords(f_point)
        f_recorded = f_sub_records["submission_recorded"]
        self.assertEqual(f_recorded.payload["handle"]["job_id"], "00123456")
        self.assertEqual(f_recorded.payload["handle"]["backend"], "pbs")

    def testStateExitTable(self) -> None:
        """Tests full state and exit code mapping matrix (Q, W, H, T, R, E, B, F with 0, nonzero, missing Exit_status)."""
        # Active query tests (qstat -f -F json)
        f_test_cases = [
            ("Q", None, SchedulerJobState.QUEUED),
            ("W", None, SchedulerJobState.QUEUED),
            ("H", None, SchedulerJobState.QUEUED),
            ("T", None, SchedulerJobState.QUEUED),
            ("R", None, SchedulerJobState.ACTIVE),
            ("E", None, SchedulerJobState.ACTIVE),
            ("B", None, SchedulerJobState.ACTIVE),
            ("S", None, SchedulerJobState.ACTIVE),
            ("F", 0, SchedulerJobState.SUCCEEDED),
            ("F", 1, SchedulerJobState.FAILED),
            ("F", 2, SchedulerJobState.FAILED),
            ("F", 143, SchedulerJobState.FAILED),
            ("F", -1, SchedulerJobState.FAILED),
            ("F", None, SchedulerJobState.UNKNOWN),  # missing Exit_status fail-closed
            ("F", "corrupted", SchedulerJobState.UNKNOWN),
            ("C", 0, SchedulerJobState.SUCCEEDED),
            ("C", 1, SchedulerJobState.FAILED),
            ("C", None, SchedulerJobState.UNKNOWN),
            ("CANCELLED", None, SchedulerJobState.CANCELLED),
            ("TIMEOUT", None, SchedulerJobState.TIMEOUT),
            ("UNKNOWN_XYZ", None, SchedulerJobState.UNKNOWN),
        ]

        for f_st_str, f_exit_val, f_exp_state in f_test_cases:
            f_job_dict: Dict[str, Any] = {"job_state": f_st_str}
            if f_exit_val is not None:
                f_job_dict["Exit_status"] = f_exit_val

            f_json_str = json.dumps({"Jobs": {"123456.isambard-pbs": f_job_dict}})

            # Test active query parser
            f_parsed_act = PbsSchedulerAdapter.parseActiveQuery(f_json_str, f_job_id="123456")
            self.assertEqual(
                f_parsed_act,
                f_exp_state,
                msg=f"Active query failed for state '{f_st_str}' and exit '{f_exit_val}'",
            )

            # Test accounting query parser
            f_parsed_acct, f_parsed_exit = PbsSchedulerAdapter.parseAccountingQuery(f_json_str, f_job_id="123456")
            self.assertEqual(
                f_parsed_acct,
                f_exp_state,
                msg=f"Accounting query failed for state '{f_st_str}' and exit '{f_exit_val}'",
            )
            if f_exit_val is not None and isinstance(f_exit_val, int):
                self.assertEqual(f_parsed_exit, f_exit_val)

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
        f_act_argv = f_adapter.activeQueryCommand("123456")
        self.assertNotIn("-u", f_act_argv)
        self.assertIn("123456", f_act_argv)
        f_res_act = f_adapter.commandRunner.run(f_act_argv)
        f_state_act = f_adapter.parseActiveQuery(f_res_act.stdout, f_job_id="123456")
        self.assertEqual(f_state_act, SchedulerJobState.ACTIVE)

        # 2. Build and execute accounting query
        f_acct_argv = f_adapter.accountingQueryCommand("123456")
        self.assertNotIn("-u", f_acct_argv)
        self.assertIn("123456", f_acct_argv)
        f_res_acct = f_adapter.commandRunner.run(f_acct_argv)
        f_state_acct, f_exit_acct = f_adapter.parseAccountingQuery(f_res_acct.stdout, f_job_id="123456")
        self.assertEqual(f_state_acct, SchedulerJobState.SUCCEEDED)
        self.assertEqual(f_exit_acct, 0)

        # 3. Cancellation polling queries ONLY exact job ID
        f_recorded_argvs.clear()
        f_final_cancel = f_adapter.cancelAndConfirm(
            "123456",
            f_poll_interval=0.01,
            f_grace_seconds=5.0,
            f_sleep=lambda _: None,
        )
        for f_argv in f_recorded_argvs:
            self.assertNotIn("-u", f_argv, msg=f"Unexpected whole-user flag in argv: {f_argv}")
            self.assertIn("123456", f_argv, msg=f"Missing exact job ID in argv: {f_argv}")

    def testRecoveryUserQueryOnlyInCrashWindowAndExactName(self) -> None:
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

        # Recovery query uses exact user query
        f_candidates = f_adapter.recoverCandidateJobIds(self.m_job_name, f_user="testuser")
        self.assertEqual(f_candidates, ["123456"])

        # Recovery command argv uses -u testuser
        f_rec_argv = f_runner.m_invoked_argv[0]
        self.assertEqual(f_rec_argv, ["qstat", "-x", "-f", "-F", "json", "-u", "testuser"])

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
        self.assertEqual(f_rec_single.job_id, "123456")

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

        # Single candidate recovered and recorded
        f_adapter_dispatch = PbsSchedulerAdapter(
            f_command_runner=SchedulerCommandRunner(f_runner_single),
            f_evidence_store=self.m_evidence_store,
        )
        f_res = f_adapter_dispatch.dispatchSubmission(f_point=f_point, f_spec=f_spec)
        self.assertEqual(f_res.job_handle.job_id, "123456")
        self.assertTrue(
            self.m_evidence_store.readSubmissionRecords(f_point)["submission_recorded"].payload.get("recovered")
        )

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
            "123456",
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
            "123456",
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
            "123456",
            f_poll_interval=0.01,
            f_grace_seconds=10.0,
            f_clock=mock_clock,
            f_sleep=lambda _: None,
        )
        self.assertEqual(f_final_timeout, SchedulerJobState.UNKNOWN)

    def testMalformedUnknownIsNonSuccess(self) -> None:
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
        self.assertEqual(f_adapter.parseActiveQuery(f_missing_state, f_job_id="123456"), SchedulerJobState.UNKNOWN)
        self.assertEqual(
            f_adapter.parseAccountingQuery(f_missing_state, f_job_id="123456"),
            (SchedulerJobState.UNKNOWN, None),
        )

        # 8. Finished job missing Exit_status maps to UNKNOWN (fail-closed, never SUCCEEDED)
        f_missing_exit = json.dumps({"Jobs": {"123456.isambard-pbs": {"job_state": "F"}}})
        self.assertEqual(f_adapter.parseActiveQuery(f_missing_exit, f_job_id="123456"), SchedulerJobState.UNKNOWN)
        self.assertEqual(
            f_adapter.parseAccountingQuery(f_missing_exit, f_job_id="123456"),
            (SchedulerJobState.UNKNOWN, None),
        )

        # 9. Multiple entries matching job_id raises SchedulerError
        f_duplicate_entries = json.dumps({
            "Jobs": {
                "123456.server1": {"job_state": "R"},
                "123456.server2": {"job_state": "Q"},
            }
        })
        with self.assertRaises(SchedulerError):
            f_adapter.parseActiveQuery(f_duplicate_entries, f_job_id="123456")
        with self.assertRaises(SchedulerError):
            f_adapter.parseAccountingQuery(f_duplicate_entries, f_job_id="123456")

    def testValidateJobIdBoundaries(self) -> None:
        """Validates validateJobId with valid decimal IDs and rejection of invalid types/characters."""
        # Valid decimal IDs
        self.assertEqual(PbsSchedulerAdapter.validateJobId("123456"), "123456")
        self.assertEqual(PbsSchedulerAdapter.validateJobId("1"), "1")
        self.assertEqual(PbsSchedulerAdapter.validateJobId("00123456"), "00123456")

        # Invalid IDs
        f_invalid_ids = [
            "",
            "   ",
            "123456.isambard-pbs",  # validated job ID must be the extracted decimal string
            "abc",
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


if __name__ == "__main__":
    unittest.main()
