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
import shlex
import sys
import tempfile
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Union
import unittest
from unittest.mock import MagicMock, patch

from lsmiotool.lib.artifacts import ArtifactLayout
from lsmiotool.lib.evidence import (
    EvidenceCollisionError,
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
    LaunchMode,
    LaunchSpec,
    RankIdentity,
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
    SlurmSchedulerAdapter,
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
    ProcessSpawnError,
)


class MockProcessRunner:
    """Mock process runner for recording argv and simulating process results."""

    def __init__(
        self,
        f_returncode: int = 0,
        f_stdout: str = "",
        f_stderr: str = "",
        f_exception_to_raise: Optional[Exception] = None,
        f_custom_handler: Optional[Callable[[Sequence[str]], ProcessResult]] = None,
    ) -> None:
        self.m_returncode = f_returncode
        self.m_stdout = f_stdout
        self.m_stderr = f_stderr
        self.m_exception_to_raise = f_exception_to_raise
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
        if self.m_exception_to_raise is not None:
            raise self.m_exception_to_raise
        return ProcessResult(
            f_returncode=self.m_returncode,
            f_stdout=self.m_stdout,
            f_stderr=self.m_stderr,
            f_elapsed_seconds=0.05,
        )


class FakeRecoverableAdapter(SchedulerAdapter):
    """Test scheduler adapter subclass providing mock candidate discovery for recovery."""

    def __init__(
        self,
        f_backend: SchedulerKind,
        f_command_runner: Optional[SchedulerCommandRunner] = None,
        f_evidence_store: Optional[EvidenceStore] = None,
        f_worker_validator: Optional[Union[WorkerExecutableValidator, Callable[[str], str]]] = None,
        f_mock_candidates: Optional[List[str]] = None,
    ) -> None:
        super().__init__(
            f_backend=f_backend,
            f_command_runner=f_command_runner,
            f_evidence_store=f_evidence_store,
            f_worker_validator=f_worker_validator,
        )
        self.m_mock_candidates = f_mock_candidates if f_mock_candidates is not None else []

    def recoverCandidateJobIds(self, f_job_name: str, f_user: Optional[str] = None) -> List[str]:
        return list(self.m_mock_candidates)


class SchedulerRendererTest(unittest.TestCase):
    """Unit test suite verifying scheduler-neutral script rendering, token safety, and dispatch evidence orchestration."""

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
        self.m_isambard_profile = EnvironmentResolver.resolveProfile(
            "ISAMBARD", f_user="testuser", f_home="/tmp"
        )
        self.m_dev_profile = EnvironmentResolver.resolveProfile(
            "DEV", f_user="testuser", f_home="/tmp"
        )

        # Scale point & Plan
        self.m_point = ScalePoint(f_tasks=8, f_ppn=1, f_nodes=8)
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
            f_run_id_source=lambda: "run_test_001",
            f_clock=lambda: "2026-08-20T12:00:00Z",
            f_token_source=token_gen,
        )

        # Artifact Layout & Evidence Store
        self.m_layout = ArtifactLayout(self.m_temp_dir.name, "run_test_001")
        self.m_evidence_store = EvidenceStore(self.m_layout, f_plan=self.m_plan)
        self.m_point = self.m_plan.scale_points[0]

        # Standard test parameters
        self.m_worker_path = "/opt/lsmio/bin/lsmiotool-worker"
        self.m_manifest_path = os.path.join(self.m_layout.runRoot, "manifest.json")
        self.m_point_id = "0-tasks-1"
        self.m_token = "lm-abcdef0123456789abcdef01"

    def tearDown(self) -> None:
        self.m_temp_dir.cleanup()

    def testExactScriptSections(self) -> None:
        """Validates bash header, fail-fast options, directives, module preamble, and POSIX-quoted worker exec tail."""
        f_slurm_directives = [
            "#SBATCH --job-name=lm-abcdef0123456789abcdef01",
            "#SBATCH --ntasks=8",
            "#SBATCH --nodes=8",
            "#SBATCH --mail-type=END,FAIL",
            "#SBATCH --mail-user=user@example.com",
            "#SBATCH --account=myaccount",
            "#SBATCH --output=/tmp/output.log",
            "#SBATCH --error=/tmp/error.log",
        ]

        # 1. Slurm script with modules (Viking2)
        f_script_viking2 = SchedulerScriptRenderer.renderScript(
            f_backend=SchedulerKind.SLURM,
            f_directives=f_slurm_directives,
            f_profile=self.m_viking2_profile,
            f_worker_executable=self.m_worker_path,
            f_manifest_path=self.m_manifest_path,
            f_point_id=self.m_point_id,
        )

        # Verify sections in strict order:
        # Line 0: #!/bin/bash
        # Lines 1-8: Directives
        # Line 9: set -euo pipefail
        # Line 10: module purge
        # Line 11+: module load ...
        # Final line: exec <worker> allocation <manifest> <point>
        f_lines = [f_l.strip() for f_l in f_script_viking2.strip().splitlines() if f_l.strip()]
        self.assertEqual(f_lines[0], "#!/bin/bash")
        self.assertEqual(f_lines[1:9], f_slurm_directives)
        self.assertEqual(f_lines[9], "set -euo pipefail")
        self.assertEqual(f_lines[10], "module purge")
        self.assertTrue(any("module load" in f_l for f_l in f_lines[11:-1]))
        self.assertEqual(
            f_lines[-1],
            f"exec {self.m_worker_path} allocation {self.m_manifest_path} {self.m_point_id}",
        )

        # 2. PBS script with modules (Isambard)
        f_pbs_directives = [
            "#PBS -q arm",
            "#PBS -m abe",
            "#PBS -N lm-abcdef0123456789abcdef01",
            "#PBS -l select=8:ncpus=1:mpiprocs=1:mem=32GB",
            "#PBS -l walltime=06:00:00",
            "#PBS -o /tmp/output.log",
            "#PBS -e /tmp/error.log",
        ]
        f_script_isambard = SchedulerScriptRenderer.renderScript(
            f_backend=SchedulerKind.PBS,
            f_directives=f_pbs_directives,
            f_profile=self.m_isambard_profile,
            f_worker_executable=self.m_worker_path,
            f_manifest_path=self.m_manifest_path,
            f_point_id=self.m_point_id,
        )
        f_pbs_lines = [f_l.strip() for f_l in f_script_isambard.strip().splitlines() if f_l.strip()]
        self.assertEqual(f_pbs_lines[0], "#!/bin/bash")
        self.assertEqual(f_pbs_lines[1:8], f_pbs_directives)
        self.assertEqual(f_pbs_lines[8], "set -euo pipefail")
        self.assertEqual(f_pbs_lines[9], "module purge")
        self.assertEqual(
            f_pbs_lines[-1],
            f"exec {self.m_worker_path} allocation {self.m_manifest_path} {self.m_point_id}",
        )

        # 3. DEV profile with empty modules: no module commands rendered
        f_script_dev = SchedulerScriptRenderer.renderScript(
            f_backend=SchedulerKind.FAKE,
            f_directives=[],
            f_profile=self.m_dev_profile,
            f_worker_executable=self.m_worker_path,
            f_manifest_path=self.m_manifest_path,
            f_point_id=self.m_point_id,
        )
        f_dev_lines = [f_l.strip() for f_l in f_script_dev.strip().splitlines() if f_l.strip()]
        self.assertEqual(f_dev_lines[0], "#!/bin/bash")
        self.assertEqual(f_dev_lines[1], "set -euo pipefail")
        self.assertNotIn("module", f_script_dev)
        self.assertEqual(
            f_dev_lines[-1],
            f"exec {self.m_worker_path} allocation {self.m_manifest_path} {self.m_point_id}",
        )

    def testDispatchEvidenceOrder(self) -> None:
        """Validates strict order of SUBMISSION_REQUESTED -> SUBMISSION_DISPATCHED -> submit -> SUBMISSION_RECORDED."""
        f_mock_runner = MockProcessRunner(f_returncode=0, f_stdout="123456\n")
        f_cmd_runner = SchedulerCommandRunner(f_process_runner=f_mock_runner)
        f_adapter = SchedulerAdapter(
            f_backend=SchedulerKind.SLURM,
            f_command_runner=f_cmd_runner,
            f_evidence_store=self.m_evidence_store,
        )

        f_script_path = os.path.join(self.m_temp_dir.name, "job.sh")
        with open(f_script_path, "w") as f_f:
            f_f.write("#!/bin/bash\n")

        f_spec = JobSpec(
            f_point_id=self.m_point,
            f_script_path=f_script_path,
            f_working_dir=self.m_temp_dir.name,
            f_job_name=self.m_token,
            f_account="myaccount",
            f_mail_user="user@example.com",
            f_mail_mode=SlurmMailMode.END_FAIL,
        )

        # Dispatch submission
        f_result = f_adapter.dispatchSubmission(
            f_point=self.m_point,
            f_spec=f_spec,
            f_writer_id="control",
            f_ordinal=0,
        )

        # Verify JobResult
        self.assertEqual(f_result.job_handle.backend, "slurm")
        self.assertEqual(f_result.job_handle.job_id, "123456")
        self.assertEqual(f_result.exit_code, 0)
        self.assertTrue(f_result.is_success)

        # Verify submission records on disk
        f_records = self.m_evidence_store.readSubmissionRecords(self.m_point, f_ordinal=0)
        self.assertIsNotNone(f_records.get("submission_requested"))
        self.assertIsNotNone(f_records.get("submission_dispatched"))
        self.assertIsNotNone(f_records.get("submission_recorded"))

        f_req = f_records["submission_requested"]
        f_disp = f_records["submission_dispatched"]
        f_rec = f_records["submission_recorded"]

        # Verify exact sequence numbers (1 -> 2 -> 3)
        self.assertEqual(f_req.sequence_number, 1)
        self.assertEqual(f_disp.sequence_number, 2)
        self.assertEqual(f_rec.sequence_number, 3)

        # Verify evidence kinds
        self.assertEqual(f_req.evidence_kind, EvidenceKind.SUBMISSION_REQUESTED)
        self.assertEqual(f_disp.evidence_kind, EvidenceKind.SUBMISSION_DISPATCHED)
        self.assertEqual(f_rec.evidence_kind, EvidenceKind.SUBMISSION_RECORDED)

        # Verify dispatched payload: contains pre-spawn metadata only (NO post-return result)
        self.assertEqual(f_disp.payload["argv"], ["sbatch", "--parsable", f_script_path])
        self.assertEqual(f_disp.payload["job_name"], self.m_token)
        self.assertEqual(f_disp.payload["correlation_token"], self.m_token)
        self.assertEqual(f_disp.payload["script_path"], f_script_path)
        self.assertEqual(f_disp.payload["working_dir"], self.m_temp_dir.name)
        self.assertNotIn("returncode", f_disp.payload)
        self.assertNotIn("stdout", f_disp.payload)
        self.assertNotIn("stderr", f_disp.payload)
        self.assertNotIn("timed_out", f_disp.payload)

        # Verify recorded payload
        self.assertEqual(f_rec.payload["handle"]["backend"], "slurm")
        self.assertEqual(f_rec.payload["handle"]["job_id"], "123456")
        self.assertEqual(f_rec.payload["job_name"], self.m_token)
        self.assertEqual(f_rec.payload["raw_output"], "123456")

        # Verify runner was invoked with exact submit command
        self.assertEqual(len(f_mock_runner.m_invoked_argv), 1)
        self.assertEqual(f_mock_runner.m_invoked_argv[0], ["sbatch", "--parsable", f_script_path])

    def testDispatchEvidenceExistsAtRunnerEntry(self) -> None:
        """Validates that submission_dispatched exists in evidence store at the exact instant the process runner is entered."""
        f_evidence_at_entry: Dict[str, Any] = {}

        def entry_handler(f_argv: Sequence[str]) -> ProcessResult:
            # Inspect evidence store at runner entry
            f_recs = self.m_evidence_store.readSubmissionRecords(self.m_point, f_ordinal=0)
            f_evidence_at_entry["requested"] = f_recs.get("submission_requested")
            f_evidence_at_entry["dispatched"] = f_recs.get("submission_dispatched")
            f_evidence_at_entry["recorded"] = f_recs.get("submission_recorded")
            return ProcessResult(f_returncode=0, f_stdout="998877\n", f_stderr="", f_elapsed_seconds=0.01)

        f_mock_runner = MockProcessRunner(f_custom_handler=entry_handler)
        f_adapter = SchedulerAdapter(
            f_backend=SchedulerKind.SLURM,
            f_command_runner=SchedulerCommandRunner(f_process_runner=f_mock_runner),
            f_evidence_store=self.m_evidence_store,
        )

        f_script_path = os.path.join(self.m_temp_dir.name, "job.sh")
        with open(f_script_path, "w") as f_f:
            f_f.write("#!/bin/bash\n")

        f_spec = JobSpec(
            f_point_id=self.m_point,
            f_script_path=f_script_path,
            f_working_dir=self.m_temp_dir.name,
            f_job_name=self.m_token,
        )

        f_res = f_adapter.dispatchSubmission(
            f_point=self.m_point,
            f_spec=f_spec,
            f_writer_id="control",
            f_ordinal=0,
        )

        # Assert evidence state at the exact moment runner was called:
        self.assertIsNotNone(f_evidence_at_entry.get("requested"), "submission_requested must exist at runner entry")
        self.assertIsNotNone(f_evidence_at_entry.get("dispatched"), "submission_dispatched must exist at runner entry")
        self.assertIsNone(f_evidence_at_entry.get("recorded"), "submission_recorded must NOT exist before runner completes")

        f_disp_entry = f_evidence_at_entry["dispatched"]
        self.assertEqual(f_disp_entry.sequence_number, 2)
        self.assertEqual(f_disp_entry.payload["argv"], ["sbatch", "--parsable", f_script_path])
        self.assertEqual(f_disp_entry.payload["job_name"], self.m_token)
        self.assertEqual(f_disp_entry.payload["correlation_token"], self.m_token)
        self.assertNotIn("returncode", f_disp_entry.payload)
        self.assertNotIn("stdout", f_disp_entry.payload)

        # Assert post-run evidence state:
        f_post_recs = self.m_evidence_store.readSubmissionRecords(self.m_point, f_ordinal=0)
        self.assertIsNotNone(f_post_recs.get("submission_recorded"))
        self.assertEqual(f_post_recs["submission_recorded"].sequence_number, 3)
        self.assertEqual(f_post_recs["submission_recorded"].payload["handle"]["job_id"], "998877")
        self.assertEqual(f_res.job_handle.job_id, "998877")

    def testCrashBeforeRequestBeforeDispatchAfterDispatchAfterAcceptanceAfterHandle(self) -> None:
        """Verifies submit counts and recovery behavior across all 5 lifecycle crash points."""
        f_scale_points = self.m_plan.scale_points

        # Crash Point 1: Before Request (empty state) -> submits once
        f_point_1 = f_scale_points[0]
        f_runner_1 = MockProcessRunner(f_returncode=0, f_stdout="100001\n")
        f_adapter_1 = SchedulerAdapter(
            f_backend=SchedulerKind.SLURM,
            f_command_runner=SchedulerCommandRunner(f_runner_1),
            f_evidence_store=self.m_evidence_store,
        )
        f_spec_1 = JobSpec(f_point_id=f_point_1, f_script_path="/tmp/job1.sh", f_working_dir=self.m_temp_dir.name, f_job_name="lm-000000000000000000000001")
        f_res_1 = f_adapter_1.dispatchSubmission(f_point_1, f_spec_1, f_ordinal=0)
        self.assertEqual(f_res_1.job_handle.job_id, "100001")
        self.assertEqual(len(f_runner_1.m_invoked_argv), 1, "Crash point 1: expected exactly 1 submit invocation")
        f_recs_1 = self.m_evidence_store.readSubmissionRecords(f_point_1, f_ordinal=0)
        self.assertIsNotNone(f_recs_1["submission_requested"])
        self.assertIsNotNone(f_recs_1["submission_dispatched"])
        self.assertIsNotNone(f_recs_1["submission_recorded"])

        # Crash Point 2: After Request, Before Dispatch (only requested exists) -> submits once
        f_point_2 = f_scale_points[1]
        self.m_evidence_store.recordSubmissionRequested(
            f_point=f_point_2,
            f_writer_id="control",
            f_payload={"script_path": "/tmp/job2.sh", "job_name": "lm-000000000000000000000002"},
            f_ordinal=1,
        )
        f_runner_2 = MockProcessRunner(f_returncode=0, f_stdout="100002\n")
        f_adapter_2 = SchedulerAdapter(
            f_backend=SchedulerKind.SLURM,
            f_command_runner=SchedulerCommandRunner(f_runner_2),
            f_evidence_store=self.m_evidence_store,
        )
        f_spec_2 = JobSpec(f_point_id=f_point_2, f_script_path="/tmp/job2.sh", f_working_dir=self.m_temp_dir.name, f_job_name="lm-000000000000000000000002")
        f_res_2 = f_adapter_2.dispatchSubmission(f_point_2, f_spec_2, f_ordinal=1)
        self.assertEqual(f_res_2.job_handle.job_id, "100002")
        self.assertEqual(len(f_runner_2.m_invoked_argv), 1, "Crash point 2: expected exactly 1 submit invocation")
        f_recs_2 = self.m_evidence_store.readSubmissionRecords(f_point_2, f_ordinal=1)
        self.assertIsNotNone(f_recs_2["submission_dispatched"])
        self.assertIsNotNone(f_recs_2["submission_recorded"])

        # Crash Point 3: After Dispatch, Before Acceptance (dispatched exists, scheduler has 0 jobs) -> fails closed, 0 submits
        f_point_3 = f_scale_points[2]
        self.m_evidence_store.recordSubmissionRequested(
            f_point=f_point_3,
            f_writer_id="control",
            f_payload={"script_path": "/tmp/job3.sh", "job_name": "lm-000000000000000000000003"},
            f_ordinal=2,
        )
        self.m_evidence_store.recordSubmissionDispatched(
            f_point=f_point_3,
            f_writer_id="control",
            f_payload={"argv": ["sbatch", "--parsable", "/tmp/job3.sh"], "job_name": "lm-000000000000000000000003"},
            f_ordinal=2,
        )
        f_runner_3 = MockProcessRunner(f_returncode=0, f_stdout="NEVER_CALLED")
        f_adapter_3 = FakeRecoverableAdapter(
            f_backend=SchedulerKind.SLURM,
            f_command_runner=SchedulerCommandRunner(f_runner_3),
            f_evidence_store=self.m_evidence_store,
            f_mock_candidates=[],  # 0 jobs in scheduler
        )
        f_spec_3 = JobSpec(f_point_id=f_point_3, f_script_path="/tmp/job3.sh", f_working_dir=self.m_temp_dir.name, f_job_name="lm-000000000000000000000003")
        with self.assertRaises(SubmissionDispatchError):
            f_adapter_3.dispatchSubmission(f_point_3, f_spec_3, f_ordinal=2)
        self.assertEqual(len(f_runner_3.m_invoked_argv), 0, "Crash point 3: expected 0 submit invocations")

        # Crash Point 4: After Dispatch, After Acceptance, Before Recorded Handle (dispatched exists, scheduler has 1 job) -> adopts handle, 0 submits
        f_point_4 = f_scale_points[3]
        self.m_evidence_store.recordSubmissionRequested(
            f_point=f_point_4,
            f_writer_id="control",
            f_payload={"script_path": "/tmp/job4.sh", "job_name": "lm-000000000000000000000004"},
            f_ordinal=3,
        )
        self.m_evidence_store.recordSubmissionDispatched(
            f_point=f_point_4,
            f_writer_id="control",
            f_payload={"argv": ["sbatch", "--parsable", "/tmp/job4.sh"], "job_name": "lm-000000000000000000000004"},
            f_ordinal=3,
        )
        f_runner_4 = MockProcessRunner(f_returncode=0, f_stdout="NEVER_CALLED")
        f_adapter_4 = FakeRecoverableAdapter(
            f_backend=SchedulerKind.SLURM,
            f_command_runner=SchedulerCommandRunner(f_runner_4),
            f_evidence_store=self.m_evidence_store,
            f_mock_candidates=["100004"],  # 1 job accepted by scheduler
        )
        f_spec_4 = JobSpec(f_point_id=f_point_4, f_script_path="/tmp/job4.sh", f_working_dir=self.m_temp_dir.name, f_job_name="lm-000000000000000000000004")
        f_res_4 = f_adapter_4.dispatchSubmission(f_point_4, f_spec_4, f_ordinal=3)
        self.assertEqual(f_res_4.job_handle.job_id, "100004")
        self.assertEqual(len(f_runner_4.m_invoked_argv), 0, "Crash point 4: expected 0 submit invocations")
        f_recs_4 = self.m_evidence_store.readSubmissionRecords(f_point_4, f_ordinal=3)
        self.assertIsNotNone(f_recs_4["submission_recorded"])
        self.assertEqual(f_recs_4["submission_recorded"].payload["handle"]["job_id"], "100004")

        # Crash Point 5: After Recorded Handle (recorded exists) -> returns handle directly, 0 submits
        f_point_5 = f_scale_points[4]
        self.m_evidence_store.recordSubmissionRequested(
            f_point=f_point_5,
            f_writer_id="control",
            f_payload={"script_path": "/tmp/job5.sh", "job_name": "lm-000000000000000000000005"},
            f_ordinal=4,
        )
        self.m_evidence_store.recordSubmissionDispatched(
            f_point=f_point_5,
            f_writer_id="control",
            f_payload={"argv": ["sbatch", "--parsable", "/tmp/job5.sh"], "job_name": "lm-000000000000000000000005"},
            f_ordinal=4,
        )
        self.m_evidence_store.recordSubmissionRecorded(
            f_point=f_point_5,
            f_writer_id="control",
            f_handle=JobHandle("slurm", "100005"),
            f_payload={"raw_output": "100005", "job_name": "lm-000000000000000000000005"},
            f_ordinal=4,
        )
        f_runner_5 = MockProcessRunner(f_returncode=0, f_stdout="NEVER_CALLED")
        f_adapter_5 = SchedulerAdapter(
            f_backend=SchedulerKind.SLURM,
            f_command_runner=SchedulerCommandRunner(f_runner_5),
            f_evidence_store=self.m_evidence_store,
        )
        f_spec_5 = JobSpec(f_point_id=f_point_5, f_script_path="/tmp/job5.sh", f_working_dir=self.m_temp_dir.name, f_job_name="lm-000000000000000000000005")
        f_res_5 = f_adapter_5.dispatchSubmission(f_point_5, f_spec_5, f_ordinal=4)
        self.assertEqual(f_res_5.job_handle.job_id, "100005")
        self.assertEqual(len(f_runner_5.m_invoked_argv), 0, "Crash point 5: expected 0 submit invocations")

    def testRequestedOnlyMaySubmitOnce(self) -> None:
        """Verifies that pre-existing submission_requested without submission_dispatched submits exactly once."""
        f_point = self.m_plan.scale_points[0]
        self.m_evidence_store.recordSubmissionRequested(
            f_point=f_point,
            f_writer_id="control",
            f_payload={"script_path": "/tmp/job.sh", "job_name": self.m_token},
            f_ordinal=0,
        )

        f_runner = MockProcessRunner(f_returncode=0, f_stdout="543210\n")
        f_adapter = SchedulerAdapter(
            f_backend=SchedulerKind.SLURM,
            f_command_runner=SchedulerCommandRunner(f_runner),
            f_evidence_store=self.m_evidence_store,
        )
        f_spec = JobSpec(
            f_point_id=f_point,
            f_script_path="/tmp/job.sh",
            f_working_dir=self.m_temp_dir.name,
            f_job_name=self.m_token,
        )

        f_res = f_adapter.dispatchSubmission(f_point, f_spec, f_ordinal=0)
        self.assertEqual(f_res.job_handle.job_id, "543210")
        self.assertEqual(len(f_runner.m_invoked_argv), 1)

        # Second dispatch attempt returns recorded handle without submitting again
        f_res_2 = f_adapter.dispatchSubmission(f_point, f_spec, f_ordinal=0)
        self.assertEqual(f_res_2.job_handle.job_id, "543210")
        self.assertEqual(len(f_runner.m_invoked_argv), 1)

    def testDispatchedZeroOneManyNeverResubmits(self) -> None:
        """Verifies that submission_dispatched without recorded handle never resubmits across 0, 1, and >1 recovery candidates."""
        f_scale_points = self.m_plan.scale_points

        # 1. Zero candidate jobs -> INDETERMINATE error, 0 submit calls
        f_p0 = f_scale_points[0]
        self.m_evidence_store.recordSubmissionRequested(f_point=f_p0, f_writer_id="control", f_payload={"job_name": "lm-001"}, f_ordinal=0)
        self.m_evidence_store.recordSubmissionDispatched(f_point=f_p0, f_writer_id="control", f_payload={"argv": ["sbatch", "--parsable", "/tmp/job.sh"], "job_name": "lm-001"}, f_ordinal=0)

        f_runner_zero = MockProcessRunner(f_returncode=0, f_stdout="")
        f_adapter_zero = FakeRecoverableAdapter(
            f_backend=SchedulerKind.SLURM,
            f_command_runner=SchedulerCommandRunner(f_runner_zero),
            f_evidence_store=self.m_evidence_store,
            f_mock_candidates=[],
        )
        f_spec_0 = JobSpec(f_point_id=f_p0, f_script_path="/tmp/job.sh", f_working_dir=self.m_temp_dir.name, f_job_name="lm-001")
        with self.assertRaises(SubmissionDispatchError) as f_ctx0:
            f_adapter_zero.dispatchSubmission(f_p0, f_spec_0, f_ordinal=0)
        self.assertIn("0 candidate jobs", str(f_ctx0.exception))
        self.assertEqual(len(f_runner_zero.m_invoked_argv), 0)

        # 2. Exactly One candidate job -> Adopts handle, records submission_recorded, 0 submit calls
        f_p1 = f_scale_points[1]
        self.m_evidence_store.recordSubmissionRequested(f_point=f_p1, f_writer_id="control", f_payload={"job_name": "lm-002"}, f_ordinal=1)
        self.m_evidence_store.recordSubmissionDispatched(f_point=f_p1, f_writer_id="control", f_payload={"argv": ["sbatch", "--parsable", "/tmp/job.sh"], "job_name": "lm-002"}, f_ordinal=1)

        f_runner_one = MockProcessRunner(f_returncode=0, f_stdout="")
        f_adapter_one = FakeRecoverableAdapter(
            f_backend=SchedulerKind.SLURM,
            f_command_runner=SchedulerCommandRunner(f_runner_one),
            f_evidence_store=self.m_evidence_store,
            f_mock_candidates=["445566"],
        )
        f_spec_1 = JobSpec(f_point_id=f_p1, f_script_path="/tmp/job.sh", f_working_dir=self.m_temp_dir.name, f_job_name="lm-002")
        f_res_one = f_adapter_one.dispatchSubmission(f_p1, f_spec_1, f_ordinal=1)
        self.assertEqual(f_res_one.job_handle.job_id, "445566")
        self.assertEqual(len(f_runner_one.m_invoked_argv), 0)
        f_recs_1 = self.m_evidence_store.readSubmissionRecords(f_p1, f_ordinal=1)
        self.assertIsNotNone(f_recs_1["submission_recorded"])
        self.assertEqual(f_recs_1["submission_recorded"].payload["handle"]["job_id"], "445566")

        # 3. Many candidate jobs (>1 distinct IDs) -> INDETERMINATE error, 0 submit calls
        f_p2 = f_scale_points[2]
        self.m_evidence_store.recordSubmissionRequested(f_point=f_p2, f_writer_id="control", f_payload={"job_name": "lm-003"}, f_ordinal=2)
        self.m_evidence_store.recordSubmissionDispatched(f_point=f_p2, f_writer_id="control", f_payload={"argv": ["sbatch", "--parsable", "/tmp/job.sh"], "job_name": "lm-003"}, f_ordinal=2)

        f_runner_many = MockProcessRunner(f_returncode=0, f_stdout="")
        f_adapter_many = FakeRecoverableAdapter(
            f_backend=SchedulerKind.SLURM,
            f_command_runner=SchedulerCommandRunner(f_runner_many),
            f_evidence_store=self.m_evidence_store,
            f_mock_candidates=["888001", "888002"],
        )
        f_spec_2 = JobSpec(f_point_id=f_p2, f_script_path="/tmp/job.sh", f_working_dir=self.m_temp_dir.name, f_job_name="lm-003")
        with self.assertRaises(SubmissionDispatchError) as f_ctx2:
            f_adapter_many.dispatchSubmission(f_p2, f_spec_2, f_ordinal=2)
        self.assertIn("multiple distinct candidate jobs", str(f_ctx2.exception))
        self.assertEqual(len(f_runner_many.m_invoked_argv), 0)

    def testCreateCollisionAndEvidenceWriteFailure(self) -> None:
        """Verifies that evidence creation collision or write failure halts submission and fails closed."""
        f_point = self.m_plan.scale_points[0]
        f_spec = JobSpec(
            f_point_id=f_point,
            f_script_path="/tmp/job.sh",
            f_working_dir=self.m_temp_dir.name,
            f_job_name=self.m_token,
        )

        # Create a pre-existing dummy file where submission_dispatched.json would be written
        f_disp_path = os.path.join(
            self.m_evidence_store.layout.pointSchedulerDir(f_point, 0),
            "submission_dispatched.json",
        )
        os.makedirs(os.path.dirname(f_disp_path), exist_ok=True)
        with open(f_disp_path, "w") as f_f:
            f_f.write("corrupt non-json\n")

        f_runner = MockProcessRunner(f_returncode=0, f_stdout="123456\n")
        f_adapter = SchedulerAdapter(
            f_backend=SchedulerKind.SLURM,
            f_command_runner=SchedulerCommandRunner(f_runner),
            f_evidence_store=self.m_evidence_store,
        )

        # dispatchSubmission should fail with EvidenceError (e.g. EvidenceCollisionError or EvidenceCorruptionError)
        with self.assertRaises(EvidenceError):
            f_adapter.dispatchSubmission(f_point, f_spec, f_ordinal=0)

        # Submit process was NEVER spawned
        self.assertEqual(len(f_runner.m_invoked_argv), 0)

    def testRequestWithoutDispatchMaySubmit(self) -> None:
        """Verifies recovery when submission was requested but not dispatched."""
        # Pre-seed submission_requested on disk
        self.m_evidence_store.recordSubmissionRequested(
            f_point=self.m_point,
            f_writer_id="control",
            f_payload={"script_path": "/tmp/job.sh", "job_name": self.m_token},
            f_ordinal=0,
        )

        # Verify requested exists and dispatched does not
        f_pre_records = self.m_evidence_store.readSubmissionRecords(self.m_point, f_ordinal=0)
        self.assertIsNotNone(f_pre_records.get("submission_requested"))
        self.assertIsNone(f_pre_records.get("submission_dispatched"))
        self.assertIsNone(f_pre_records.get("submission_recorded"))

        f_mock_runner = MockProcessRunner(f_returncode=0, f_stdout="987654\n")
        f_cmd_runner = SchedulerCommandRunner(f_process_runner=f_mock_runner)
        f_adapter = SchedulerAdapter(
            f_backend=SchedulerKind.SLURM,
            f_command_runner=f_cmd_runner,
            f_evidence_store=self.m_evidence_store,
        )

        f_spec = JobSpec(
            f_point_id=self.m_point,
            f_script_path="/tmp/job.sh",
            f_working_dir=self.m_temp_dir.name,
            f_job_name=self.m_token,
        )

        # Dispatch should proceed to submit
        f_result = f_adapter.dispatchSubmission(
            f_point=self.m_point,
            f_spec=f_spec,
            f_writer_id="control",
            f_ordinal=0,
        )

        self.assertEqual(f_result.job_handle.job_id, "987654")
        self.assertEqual(len(f_mock_runner.m_invoked_argv), 1)

        # Dispatched and recorded should now exist
        f_post_records = self.m_evidence_store.readSubmissionRecords(self.m_point, f_ordinal=0)
        self.assertIsNotNone(f_post_records.get("submission_dispatched"))
        self.assertIsNotNone(f_post_records.get("submission_recorded"))
        self.assertEqual(f_post_records["submission_recorded"].payload["handle"]["job_id"], "987654")

    def testDispatchWithoutHandleMustRecover(self) -> None:
        """Verifies recovery when dispatched output exists without recorded handle."""
        # Pre-seed submission_requested and submission_dispatched
        self.m_evidence_store.recordSubmissionRequested(
            f_point=self.m_point,
            f_writer_id="control",
            f_payload={"script_path": "/tmp/job.sh", "job_name": self.m_token},
            f_ordinal=0,
        )
        self.m_evidence_store.recordSubmissionDispatched(
            f_point=self.m_point,
            f_writer_id="control",
            f_payload={"argv": ["sbatch", "--parsable", "/tmp/job.sh"], "job_name": self.m_token},
            f_ordinal=0,
        )

        f_mock_runner = MockProcessRunner(f_returncode=0, f_stdout="NEVER_REACHED")
        f_cmd_runner = SchedulerCommandRunner(f_process_runner=f_mock_runner)

        # 1. Recovery with exactly 1 candidate: persists handle without calling submit
        f_rec_adapter = FakeRecoverableAdapter(
            f_backend=SchedulerKind.SLURM,
            f_command_runner=f_cmd_runner,
            f_evidence_store=self.m_evidence_store,
            f_mock_candidates=["777888"],
        )

        f_spec = JobSpec(
            f_point_id=self.m_point,
            f_script_path="/tmp/job.sh",
            f_working_dir=self.m_temp_dir.name,
            f_job_name=self.m_token,
        )

        f_res = f_rec_adapter.dispatchSubmission(
            f_point=self.m_point,
            f_spec=f_spec,
            f_writer_id="control",
            f_ordinal=0,
        )

        self.assertEqual(f_res.job_handle.job_id, "777888")
        # Submit command was NEVER executed
        self.assertEqual(len(f_mock_runner.m_invoked_argv), 0)

        # Recorded handle should be saved
        f_records = self.m_evidence_store.readSubmissionRecords(self.m_point, f_ordinal=0)
        self.assertIsNotNone(f_records.get("submission_recorded"))
        self.assertEqual(f_records["submission_recorded"].payload["handle"]["job_id"], "777888")

        # 2. Recovery with 0 candidates: raises SubmissionDispatchError without calling submit
        f_point_2 = self.m_plan.scale_points[1]
        self.m_evidence_store.recordSubmissionRequested(
            f_point=f_point_2,
            f_writer_id="control",
            f_payload={"script_path": "/tmp/job2.sh", "job_name": "lm-000000000000000000000002"},
            f_ordinal=1,
        )
        self.m_evidence_store.recordSubmissionDispatched(
            f_point=f_point_2,
            f_writer_id="control",
            f_payload={"argv": ["sbatch", "--parsable", "/tmp/job2.sh"], "job_name": "lm-000000000000000000000002"},
            f_ordinal=1,
        )

        f_zero_adapter = FakeRecoverableAdapter(
            f_backend=SchedulerKind.SLURM,
            f_command_runner=f_cmd_runner,
            f_evidence_store=self.m_evidence_store,
            f_mock_candidates=[],
        )
        f_spec_2 = JobSpec(
            f_point_id=f_point_2,
            f_script_path="/tmp/job2.sh",
            f_working_dir=self.m_temp_dir.name,
            f_job_name="lm-000000000000000000000002",
        )
        with self.assertRaises(SubmissionDispatchError):
            f_zero_adapter.dispatchSubmission(
                f_point=f_point_2,
                f_spec=f_spec_2,
                f_writer_id="control",
                f_ordinal=1,
            )
        self.assertEqual(len(f_mock_runner.m_invoked_argv), 0)

        # 3. Recovery with multiple distinct candidate root jobs: raises SubmissionDispatchError (indeterminate)
        f_point_3 = self.m_plan.scale_points[2]
        self.m_evidence_store.recordSubmissionRequested(
            f_point=f_point_3,
            f_writer_id="control",
            f_payload={"script_path": "/tmp/job3.sh", "job_name": "lm-000000000000000000000003"},
            f_ordinal=2,
        )
        self.m_evidence_store.recordSubmissionDispatched(
            f_point=f_point_3,
            f_writer_id="control",
            f_payload={"argv": ["sbatch", "--parsable", "/tmp/job3.sh"], "job_name": "lm-000000000000000000000003"},
            f_ordinal=2,
        )

        f_multi_adapter = FakeRecoverableAdapter(
            f_backend=SchedulerKind.SLURM,
            f_command_runner=f_cmd_runner,
            f_evidence_store=self.m_evidence_store,
            f_mock_candidates=["1001", "1002"],
        )
        f_spec_3 = JobSpec(
            f_point_id=f_point_3,
            f_script_path="/tmp/job3.sh",
            f_working_dir=self.m_temp_dir.name,
            f_job_name="lm-000000000000000000000003",
        )
        with self.assertRaises(SubmissionDispatchError):
            f_multi_adapter.dispatchSubmission(
                f_point=f_point_3,
                f_spec=f_spec_3,
                f_writer_id="control",
                f_ordinal=2,
            )
        self.assertEqual(len(f_mock_runner.m_invoked_argv), 0)

    def testUsesValidatedWorkerWithoutFilesystemCalls(self) -> None:
        """Proves renderer calls injected validator without filesystem stat/exists calls (spy verified)."""
        f_validator_mock = MagicMock(return_value="/approved/bin/worker")

        with patch("os.stat") as f_mock_stat, patch("os.lstat") as f_mock_lstat, patch(
            "os.path.exists"
        ) as f_mock_exists, patch("os.path.isfile") as f_mock_isfile, patch("os.access") as f_mock_access:

            f_script = SchedulerScriptRenderer.renderScript(
                f_backend=SchedulerKind.SLURM,
                f_directives=["#SBATCH --job-name=lm-abcdef0123456789abcdef01"],
                f_profile=self.m_viking_profile,
                f_worker_executable="/input/bin/worker",
                f_manifest_path="/tmp/manifest.json",
                f_point_id="p0",
                f_worker_validator=f_validator_mock,
            )

            # Injected validator was called with input worker path
            f_validator_mock.validate.assert_not_called() if not hasattr(f_validator_mock, "validate") else None
            f_validator_mock.assert_called_once_with("/input/bin/worker")

            # Resulting script uses approved worker path
            self.assertIn("/approved/bin/worker", f_script)

            # ZERO filesystem inspection calls made by renderer
            f_mock_stat.assert_not_called()
            f_mock_lstat.assert_not_called()
            f_mock_exists.assert_not_called()
            f_mock_isfile.assert_not_called()
            f_mock_access.assert_not_called()

    def testBackendTypedMailPositiveAndCrossBackendInjectionNegative(self) -> None:
        """Verifies acceptance of matching typed mail enum and rejection of raw/cross-backend values."""
        # 1. Slurm accepts SlurmMailMode.END_FAIL -> 'END,FAIL'
        f_slurm_mail = SchedulerScriptRenderer.validateMailMode(
            SchedulerKind.SLURM, SlurmMailMode.END_FAIL
        )
        self.assertEqual(f_slurm_mail, "END,FAIL")

        # 2. PBS accepts PbsMailMode.ABE -> 'abe'
        f_pbs_mail = SchedulerScriptRenderer.validateMailMode(
            SchedulerKind.PBS, PbsMailMode.ABE
        )
        self.assertEqual(f_pbs_mail, "abe")

        # 3. Slurm rejects PbsMailMode.ABE
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validateMailMode(SchedulerKind.SLURM, PbsMailMode.ABE)

        # 4. PBS rejects SlurmMailMode.END_FAIL
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validateMailMode(SchedulerKind.PBS, SlurmMailMode.END_FAIL)

        # 5. Raw string 'END,FAIL' rejected
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validateMailMode(SchedulerKind.SLURM, "END,FAIL")

        # 6. Raw string 'abe' rejected
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validateMailMode(SchedulerKind.PBS, "abe")

        # 7. Raw string 'ALL', 'NONE', 'BEGIN' rejected
        for f_raw in ("ALL", "NONE", "BEGIN", "FAIL", "END"):
            with self.assertRaises(SchedulerScriptError):
                SchedulerScriptRenderer.validateMailMode(SchedulerKind.SLURM, f_raw)
            with self.assertRaises(SchedulerScriptError):
                SchedulerScriptRenderer.validateMailMode(SchedulerKind.PBS, f_raw)

        # 8. Injected control text / newlines rejected
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validateMailMode(SchedulerKind.SLURM, "END,FAIL\n#SBATCH --account=evil")

    def testShlexQuoteLiteralRoundTrip(self) -> None:
        """Tests adversarial worker/manifest paths with spaces, quotes, and metacharacters."""
        f_adversarial_workers = [
            "/opt/path with spaces/bin/lsmioworker",
            "/opt/path'with'single_quotes/bin/worker",
            '/opt/path"with"double_quotes/bin/worker',
            "/opt/path;rm -rf /bin/worker",
            "/opt/path$(whoami)/bin/worker",
            "/opt/path`uname -a`/bin/worker",
            "/opt/path$VAR/bin/worker",
        ]

        f_adversarial_manifests = [
            "/tmp/benchmark root/runs/run#1/manifest.json",
            "/tmp/run's/manifest.json",
            '/tmp/run"s/manifest.json',
            "/tmp/run; rm -rf /manifest.json",
            "/tmp/run$(date)/manifest.json",
        ]

        for f_worker in f_adversarial_workers:
            for f_manifest in f_adversarial_manifests:
                f_tail = SchedulerScriptRenderer.renderExecutionTail(
                    f_worker_executable=f_worker,
                    f_manifest_path=f_manifest,
                    f_point_id="p 0; evil",
                )
                self.assertTrue(f_tail.startswith("exec "))

                # Parse tail line using shlex.split to verify exact round-trip tokens
                f_tokens = shlex.split(f_tail[len("exec ") :])
                self.assertEqual(len(f_tokens), 4)
                self.assertEqual(f_tokens[0], f_worker)
                self.assertEqual(f_tokens[1], "allocation")
                self.assertEqual(f_tokens[2], f_manifest)
                self.assertEqual(f_tokens[3], "p 0; evil")

    def testNewlineCrNulAndDirectiveInjectionRejected(self) -> None:
        """Asserts rejection of newlines, \\r, NUL, and #SBATCH / #PBS directive injection attempts."""
        # 1. Job name adversaries
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validateJobName("lm-001\n#SBATCH --mail-type=ALL")
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validateJobName("lm-001\r#SBATCH --mail-type=ALL")
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validateJobName("lm-001\0nul")
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validateJobName("lm-001#SBATCH injection")

        # 2. Account adversaries
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validateAccount("myacct\n#SBATCH --account=evil")
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validateAccount("myacct\r#PBS -q evil")
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validateAccount("myacct\0nul")
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validateAccount("myacct#SBATCH")

        # 3. Mail user adversaries
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validateMailUser("user@example.com\n#SBATCH")
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validateMailUser("user@example.com\r#PBS")
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validateMailUser("user@example.com\0")

        # 4. Path adversaries
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validatePath("/tmp/out.log\n#SBATCH")
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validatePath("/tmp/out.log\r#PBS")
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validatePath("/tmp/out.log\0")

        # 5. JobSpec validation rejects injection
        with self.assertRaises(SchedulerScriptError):
            JobSpec(
                f_point_id=self.m_point,
                f_script_path="/tmp/job.sh\n#SBATCH",
                f_working_dir="/tmp",
            )
        with self.assertRaises(SchedulerScriptError):
            JobSpec(
                f_point_id=self.m_point,
                f_script_path="/tmp/job.sh",
                f_working_dir="/tmp",
                f_account="acct\n#SBATCH",
            )
        with self.assertRaises(SchedulerScriptError):
            JobSpec(
                f_point_id=self.m_point,
                f_script_path="/tmp/job.sh",
                f_working_dir="/tmp",
                f_mail_user="u@e.com\0nul",
            )

    def testAccountMailModulePathTokenAdversaries(self) -> None:
        """Tests validation of account, mail, module, and path tokens."""
        # 1. Valid tokens
        self.assertEqual(SchedulerScriptRenderer.validateAccount("e281"), "e281")
        self.assertEqual(SchedulerScriptRenderer.validateAccount("proj_123.sub-1"), "proj_123.sub-1")
        self.assertEqual(SchedulerScriptRenderer.validateQueueOrPartition("standard"), "standard")
        self.assertEqual(SchedulerScriptRenderer.validateQueueOrPartition("arm-gpu_01"), "arm-gpu_01")
        self.assertEqual(SchedulerScriptRenderer.validateMailUser("alice.bob+test@dept.univ.ac.uk"), "alice.bob+test@dept.univ.ac.uk")
        self.assertEqual(SchedulerScriptRenderer.validatePath("/mnt/lustre/users/test/output.log"), "/mnt/lustre/users/test/output.log")
        self.assertEqual(SchedulerScriptRenderer.validatePath("/tmp/out%j.log"), "/tmp/out%j.log")

        # 2. Invalid account tokens
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validateAccount("-leadingdash")
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validateAccount("space in acct")
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validateAccount("acct;evil")
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validateAccount("acct$VAR")

        # 3. Invalid mail user tokens
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validateMailUser("no_at_sign")
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validateMailUser("@nohost.com")
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validateMailUser("user@")
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validateMailUser("user @domain.com")

        # 4. Invalid path tokens
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validatePath("relative/path/out.log")
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validatePath("")
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validatePath("/path/with space/out.log")
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validatePath("/path;rm -rf /")

    def testNoForeignOrLateDirective(self) -> None:
        """Proves all directives appear strictly before preamble and execution tail."""
        # 1. Foreign #PBS directive in Slurm script
        f_foreign_pbs = (
            "#!/bin/bash\n"
            "#SBATCH --job-name=lm-abcdef0123456789abcdef01\n"
            "#PBS -q arm\n"
            "set -euo pipefail\n"
            f"exec {self.m_worker_path} allocation {self.m_manifest_path} p0\n"
        )
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validateScript(f_foreign_pbs, f_backend=SchedulerKind.SLURM)

        # 2. Foreign #SBATCH directive in PBS script
        f_foreign_sbatch = (
            "#!/bin/bash\n"
            "#PBS -q arm\n"
            "#SBATCH --account=myaccount\n"
            "set -euo pipefail\n"
            f"exec {self.m_worker_path} allocation {self.m_manifest_path} p0\n"
        )
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validateScript(f_foreign_sbatch, f_backend=SchedulerKind.PBS)

        # 3. Late directive after 'set -euo pipefail'
        f_late_directive_1 = (
            "#!/bin/bash\n"
            "#SBATCH --job-name=lm-abcdef0123456789abcdef01\n"
            "set -euo pipefail\n"
            "#SBATCH --mail-type=END,FAIL\n"
            f"exec {self.m_worker_path} allocation {self.m_manifest_path} p0\n"
        )
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validateScript(f_late_directive_1, f_backend=SchedulerKind.SLURM)

        # 4. Late directive after module preamble
        f_late_directive_2 = (
            "#!/bin/bash\n"
            "#SBATCH --job-name=lm-abcdef0123456789abcdef01\n"
            "set -euo pipefail\n"
            "module purge\n"
            "module load OpenMPI/4.1.5\n"
            "#SBATCH --account=late_acct\n"
            f"exec {self.m_worker_path} allocation {self.m_manifest_path} p0\n"
        )
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validateScript(f_late_directive_2, f_backend=SchedulerKind.SLURM)

        # 5. Late directive after exec tail
        f_late_directive_3 = (
            "#!/bin/bash\n"
            "#SBATCH --job-name=lm-abcdef0123456789abcdef01\n"
            "set -euo pipefail\n"
            f"exec {self.m_worker_path} allocation {self.m_manifest_path} p0\n"
            "#SBATCH --output=/tmp/out.log\n"
        )
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validateScript(f_late_directive_3, f_backend=SchedulerKind.SLURM)

        # 6. Missing fail-fast 'set -euo pipefail' or 'set -e'
        f_missing_set_e = (
            "#!/bin/bash\n"
            "#SBATCH --job-name=lm-abcdef0123456789abcdef01\n"
            f"exec {self.m_worker_path} allocation {self.m_manifest_path} p0\n"
        )
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validateScript(f_missing_set_e, f_backend=SchedulerKind.SLURM)

        # 7. Missing exec tail
        f_missing_exec = (
            "#!/bin/bash\n"
            "#SBATCH --job-name=lm-abcdef0123456789abcdef01\n"
            "set -euo pipefail\n"
            "echo done\n"
        )
        with self.assertRaises(SchedulerScriptError):
            SchedulerScriptRenderer.validateScript(f_missing_exec, f_backend=SchedulerKind.SLURM)

    def testJobSpecAndResultDomainModels(self) -> None:
        """Verifies immutability, properties, and dictionary serialization for JobSpec and JobResult."""
        f_handle = JobHandle("slurm", "5551234")
        self.assertEqual(f_handle.backend, "slurm")
        self.assertEqual(f_handle.job_id, "5551234")
        self.assertEqual(f_handle.jobId, "5551234")

        # JobSpec immutability
        f_spec = JobSpec(
            f_point_id=self.m_point,
            f_script_path="/tmp/job.sh",
            f_working_dir="/tmp/work",
            f_job_name=self.m_token,
            f_account="myaccount",
            f_mail_user="user@example.com",
            f_mail_mode=SlurmMailMode.END_FAIL,
            f_output_path="/tmp/out.log",
            f_error_path="/tmp/err.log",
        )
        self.assertEqual(f_spec.script_path, "/tmp/job.sh")
        self.assertEqual(f_spec.scriptPath, "/tmp/job.sh")
        self.assertEqual(f_spec.working_dir, "/tmp/work")
        self.assertEqual(f_spec.workingDir, "/tmp/work")
        self.assertEqual(f_spec.job_name, self.m_token)
        self.assertEqual(f_spec.account, "myaccount")
        self.assertEqual(f_spec.mail_user, "user@example.com")
        self.assertEqual(f_spec.mail_mode, SlurmMailMode.END_FAIL)

        with self.assertRaises(AttributeError):
            f_spec.script_path = "/mutated/job.sh"  # type: ignore

        f_spec_dict = f_spec.toDict()
        self.assertEqual(f_spec_dict["script_path"], "/tmp/job.sh")
        self.assertEqual(f_spec_dict["mail_mode"], "END,FAIL")

        # JobResult immutability and success checks
        f_res = JobResult(
            f_job_handle=f_handle,
            f_raw_output="5551234\n",
            f_exit_code=0,
            f_status=SchedulerJobState.QUEUED,
            f_diagnostics=["submitted successfully"],
        )
        self.assertEqual(f_res.job_handle, f_handle)
        self.assertEqual(f_res.jobHandle, f_handle)
        self.assertEqual(f_res.raw_output, "5551234\n")
        self.assertEqual(f_res.rawOutput, "5551234\n")
        self.assertEqual(f_res.exit_code, 0)
        self.assertEqual(f_res.exitCode, 0)
        self.assertEqual(f_res.status, SchedulerJobState.QUEUED)
        self.assertTrue(f_res.is_success)
        self.assertTrue(f_res.isSuccess)

        with self.assertRaises(AttributeError):
            f_res.exit_code = 1  # type: ignore

        f_res_dict = f_res.toDict()
        self.assertEqual(f_res_dict["exit_code"], 0)
        self.assertEqual(f_res_dict["status"], "queued")
        self.assertTrue(f_res_dict["is_success"])

    def testEverySchedulerCallCarriesExactGraceTimeout(self) -> None:
        """Verifies that every scheduler adapter call derives and carries the exact grace_seconds timeout."""
        # 1. Profile derivation
        f_profile = EnvironmentResolver.resolveProfile("VIKING", f_user="testuser", f_home="/tmp")
        self.assertEqual(f_profile.cancellation.grace_seconds, 120)

        f_runner = MockProcessRunner(f_returncode=0, f_stdout="123456\n")
        f_adapter = SchedulerAdapter(
            f_backend=SchedulerKind.SLURM,
            f_command_runner=SchedulerCommandRunner(f_runner),
            f_profile=f_profile,
        )
        self.assertEqual(f_adapter.command_timeout, 120.0)
        self.assertEqual(f_adapter.commandTimeout, 120.0)
        self.assertEqual(f_adapter.timeout, 120.0)

        # 2. Dispatch submission passes exact timeout
        f_spec = JobSpec(
            f_point_id=self.m_point,
            f_script_path="/tmp/job.sh",
            f_working_dir=self.m_temp_dir.name,
            f_job_name=self.m_token,
        )
        f_res = f_adapter.dispatchSubmission(self.m_point, f_spec)
        self.assertEqual(f_res.job_handle.job_id, "123456")
        self.assertEqual(len(f_runner.m_invoked_kwargs), 1)
        self.assertEqual(f_runner.m_invoked_kwargs[0].get("f_timeout"), 120.0)

        # 3. Explicit timeout constructor override
        f_runner_custom = MockProcessRunner(f_returncode=0, f_stdout="789012\n")
        f_adapter_custom = SchedulerAdapter(
            f_backend=SchedulerKind.SLURM,
            f_command_runner=SchedulerCommandRunner(f_runner_custom),
            f_timeout=45.5,
        )
        self.assertEqual(f_adapter_custom.command_timeout, 45.5)
        f_adapter_custom.dispatchSubmission(self.m_point, f_spec)
        self.assertEqual(len(f_runner_custom.m_invoked_kwargs), 1)
        self.assertEqual(f_runner_custom.m_invoked_kwargs[0].get("f_timeout"), 45.5)

        # 4. SlurmSchedulerAdapter derives and passes exact timeout
        f_slurm_runner = MockProcessRunner(f_returncode=0, f_stdout="999888\n")
        f_slurm_adapter = SlurmSchedulerAdapter(
            f_command_runner=SchedulerCommandRunner(f_slurm_runner),
            f_profile=f_profile,
        )
        self.assertEqual(f_slurm_adapter.command_timeout, 120.0)
        f_slurm_adapter.dispatchSubmission(self.m_point, f_spec)
        self.assertEqual(f_slurm_runner.m_invoked_kwargs[0].get("f_timeout"), 120.0)

        # Recovery queries on Slurm also carry exact timeout
        f_slurm_runner.m_invoked_kwargs.clear()
        f_slurm_adapter.recoverCandidateJobIds("lm-000000000000000000000001")
        self.assertGreaterEqual(len(f_slurm_runner.m_invoked_kwargs), 2)
        for f_kw in f_slurm_runner.m_invoked_kwargs:
            self.assertEqual(f_kw.get("f_timeout"), 120.0)

        # 5. PbsSchedulerAdapter derives and passes exact timeout
        f_isambard_profile = EnvironmentResolver.resolveProfile("ISAMBARD", f_user="testuser", f_home="/tmp")
        f_pbs_runner = MockProcessRunner(f_returncode=0, f_stdout="555444.isambard-pbs\n")
        f_pbs_adapter = PbsSchedulerAdapter(
            f_command_runner=SchedulerCommandRunner(f_pbs_runner),
            f_profile=f_isambard_profile,
        )
        self.assertEqual(f_pbs_adapter.command_timeout, 120.0)
        f_pbs_adapter.dispatchSubmission(self.m_point, f_spec)
        self.assertEqual(f_pbs_runner.m_invoked_kwargs[0].get("f_timeout"), 120.0)

        # Recovery query on PBS carries exact timeout
        f_pbs_runner.m_invoked_kwargs.clear()
        f_pbs_runner.m_stdout = json.dumps({"Jobs": {}})
        f_pbs_adapter.recoverCandidateJobIds("lm-000000000000000000000001", f_user="testuser")
        self.assertEqual(len(f_pbs_runner.m_invoked_kwargs), 1)
        self.assertEqual(f_pbs_runner.m_invoked_kwargs[0].get("f_timeout"), 120.0)


if __name__ == "__main__":
    unittest.main()
