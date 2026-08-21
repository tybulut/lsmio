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
import tempfile
import unittest

from lsmiotool.lib.artifacts import ArtifactLayout, ArtifactStore, ContainmentError
from lsmiotool.lib.evidence import (
    EvidenceCollisionError,
    EvidenceCorruptionError,
    EvidenceError,
    EvidenceKind,
    EvidenceOwnershipError,
    EvidencePlanError,
    EvidenceRecord,
    EvidenceSchemaError,
    EvidenceSequenceError,
    EvidenceSerializer,
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
)
from lsmiotool.lib.site import EnvironmentResolver


class EvidenceStoreTest(unittest.TestCase):
    """Comprehensive unit tests for EvidenceStore, EvidenceRecord, and JobHandle."""

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.mkdtemp(prefix="lsmiotool-evidence-test-")
        self.m_default_profile_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "etc", "environments.json")
        )
        self.m_profile_doc = ProfileLoader.load(self.m_default_profile_path)
        self.m_test_user = "alice"
        self.m_test_home = "/home/alice"
        self.m_registry = EnvironmentResolver.resolveRegistry(
            self.m_profile_doc, f_user=self.m_test_user, f_home=self.m_test_home
        )
        self.m_viking_profile = self.m_registry.getProfile("VIKING")

        # Create base test plan
        self.m_run_id = "run-evidence-001"
        self.m_plan = self._createTestPlan(self.m_run_id)

        # Initialize ArtifactStore and allocate run
        self.m_artifact_store = ArtifactStore(self.m_temp_dir, self.m_run_id)
        self.m_run_root = self.m_artifact_store.allocateRun(self.m_plan)
        self.m_layout = self.m_artifact_store.layout

        # Prepare first point (tasks=1)
        self.m_point = self.m_plan.scale_points[0]
        self.m_artifact_store.preparePoint(self.m_point, f_ordinal=0)

        # Initialize EvidenceStore
        self.m_evidence_store = EvidenceStore(self.m_layout, f_plan=self.m_plan)

    def tearDown(self) -> None:
        shutil.rmtree(self.m_temp_dir, ignore_errors=True)

    def _createTestPlan(self, f_run_id: str) -> RunPlan:
        f_req = RunRequest(f_target="lsmio", f_scale="bake", f_ssd=False, f_setup="NATIVE-M")
        f_tokens = [f"lm-{f_i:024d}" for f_i in range(1, 10)]
        f_tok_idx = 0

        def token_gen() -> str:
            nonlocal f_tok_idx
            f_tok = f_tokens[f_tok_idx]
            f_tok_idx += 1
            return f_tok

        return RunPlanner.createPlan(
            f_request=f_req,
            f_profile=self.m_viking_profile,
            f_run_id_source=lambda: f_run_id,
            f_clock=lambda: "2026-08-20T12:00:00Z",
            f_token_source=token_gen,
        )

    def testOwnershipMatrix(self) -> None:
        """Control, Controller, and Rank create only owned evidence in their respective directories."""
        f_point = self.m_point
        f_combo = "c16_b8M"

        # 1. CONTROL Writer: Authorized in control/events and points/<p>/scheduler
        f_ctrl_rec = self.m_evidence_store.recordControlEvent(
            f_writer_id="client",
            f_sequence=1,
            f_evidence_kind=EvidenceKind.OBSERVATION,
            f_payload={"status": "init"},
        )
        self.assertEqual(f_ctrl_rec.writer_kind, WriterKind.CONTROL)
        self.assertEqual(f_ctrl_rec.sequence_number, 1)

        f_sub_req = self.m_evidence_store.recordSubmissionRequested(
            f_point=f_point,
            f_writer_id="client",
            f_payload={"token": "lm-000000000000000000000001"},
            f_ordinal=0,
        )
        self.assertEqual(f_sub_req.evidence_kind, EvidenceKind.SUBMISSION_REQUESTED)

        # CONTROL Writer: Unauthorized in worker/events or combinations or ranks
        f_unauth_worker_path = self.m_layout.pointWorkerEventPath(
            f_point, f_sequence=1, f_ordinal=0
        )
        f_bad_ctrl_rec = EvidenceRecord(
            f_writer_kind=WriterKind.CONTROL,
            f_writer_id="client",
            f_sequence_number=1,
            f_evidence_kind=EvidenceKind.CONTROLLER_STARTED,
        )
        with self.assertRaises(EvidenceOwnershipError):
            self.m_evidence_store.recordRecord(f_unauth_worker_path, f_bad_ctrl_rec)

        # 2. CONTROLLER Writer: Authorized in worker/events and combinations/<combo>/controller-result.json
        f_worker_rec = self.m_evidence_store.recordWorkerEvent(
            f_point=f_point,
            f_sequence=1,
            f_evidence_kind=EvidenceKind.CONTROLLER_STARTED,
            f_payload={"stage": "start"},
            f_ordinal=0,
        )
        self.assertEqual(f_worker_rec.writer_kind, WriterKind.CONTROLLER)

        f_ctrl_res = self.m_evidence_store.recordControllerResult(
            f_point=f_point,
            f_combination=f_combo,
            f_payload={"status": "success", "exit_code": 0},
            f_ordinal=0,
        )
        self.assertEqual(f_ctrl_res.evidence_kind, EvidenceKind.CONTROLLER_RESULT)

        # CONTROLLER Writer: Unauthorized in control/events or ranks
        f_unauth_control_path = self.m_layout.controlEventPath("client", 2)
        f_bad_worker_rec = EvidenceRecord(
            f_writer_kind=WriterKind.CONTROLLER,
            f_writer_id="controller",
            f_sequence_number=2,
            f_evidence_kind=EvidenceKind.INTERRUPTED,
        )
        with self.assertRaises(EvidenceOwnershipError):
            self.m_evidence_store.recordRecord(f_unauth_control_path, f_bad_worker_rec)

        # 3. RANK Writer: Authorized only in ranks/<global_rank>/<combo>/result.json
        f_rank_res = self.m_evidence_store.recordRankResult(
            f_point=f_point,
            f_global_rank=0,
            f_combination=f_combo,
            f_payload={"status": "success", "iterations": 10},
            f_ordinal=0,
        )
        self.assertEqual(f_rank_res.writer_kind, WriterKind.RANK)
        self.assertEqual(f_rank_res.global_rank, 0)

        # RANK Writer: Unauthorized in other rank's directory or combinations or control
        f_other_rank_path = self.m_layout.pointRankResultPath(
            f_point, f_global_rank=1, f_combination=f_combo, f_ordinal=0
        )
        f_bad_rank_rec = EvidenceRecord(
            f_writer_kind=WriterKind.RANK,
            f_writer_id="0",  # writer_id 0 attempting to write rank 1 path
            f_sequence_number=1,
            f_evidence_kind=EvidenceKind.RANK_RESULT,
            f_global_rank=0,
        )
        with self.assertRaises(EvidenceOwnershipError):
            self.m_evidence_store.recordRecord(f_other_rank_path, f_bad_rank_rec)

        # RANK Writer: Unauthorized in combinations controller-result.json
        f_combo_path = self.m_layout.pointControllerResultPath(
            f_point, f_combo, f_ordinal=0
        )
        with self.assertRaises(EvidenceOwnershipError):
            self.m_evidence_store.recordRecord(f_combo_path, f_rank_res)

    def testConcurrentWritersRetainAll(self) -> None:
        """Validates concurrent disjoint writers in separate namespaces retain all evidence intact."""
        # Prepare 4-task point (scale_points[2] has tasks=4)
        f_point_4 = self.m_plan.scale_points[2]
        self.m_artifact_store.preparePoint(f_point_4, f_ordinal=2)
        f_combo = "c16_b8M"

        # Separate writers writing to disjoint directories
        # 1. Control writer
        f_ctrl_rec = self.m_evidence_store.recordControlEvent(
            f_writer_id="control-agent",
            f_sequence=1,
            f_evidence_kind=EvidenceKind.OBSERVATION,
            f_payload={"obs": "running"},
        )

        # 2. Worker/Controller writer
        f_worker_rec = self.m_evidence_store.recordWorkerEvent(
            f_point=f_point_4,
            f_sequence=1,
            f_evidence_kind=EvidenceKind.CONTROLLER_STARTED,
            f_payload={"stage": "benchmarking"},
            f_ordinal=2,
        )
        f_ctrl_result = self.m_evidence_store.recordControllerResult(
            f_point=f_point_4,
            f_combination=f_combo,
            f_payload={"combo": f_combo, "exit": 0},
            f_ordinal=2,
        )

        # 3. Four rank writers writing in parallel namespaces
        f_rank_records = []
        for f_r in range(4):
            f_rec = self.m_evidence_store.recordRankResult(
                f_point=f_point_4,
                f_global_rank=f_r,
                f_combination=f_combo,
                f_payload={"rank": f_r, "written_bytes": 1048576},
                f_ordinal=2,
            )
            f_rank_records.append(f_rec)

        # Verify all evidence files are retained completely and read back byte-exact
        f_read_ctrl = self.m_evidence_store.readControlEvents("control-agent")
        self.assertEqual(len(f_read_ctrl), 1)
        self.assertEqual(f_read_ctrl[0], f_ctrl_rec)

        f_read_worker = self.m_evidence_store.readWorkerEvents(f_point_4, f_ordinal=2)
        self.assertEqual(len(f_read_worker), 1)
        self.assertEqual(f_read_worker[0], f_worker_rec)

        f_read_ctrl_res = self.m_evidence_store.readControllerResult(
            f_point_4, f_combo, f_ordinal=2
        )
        self.assertEqual(f_read_ctrl_res, f_ctrl_result)

        for f_r in range(4):
            f_read_rank = self.m_evidence_store.readRankResult(
                f_point_4, f_global_rank=f_r, f_combination=f_combo, f_ordinal=2
            )
            self.assertEqual(f_read_rank, f_rank_records[f_r])

    def testNoReplacement(self) -> None:
        """Rejects duplicate sequence creation or replacing an existing evidence file."""
        f_point = self.m_point
        f_combo = "c16_b8M"

        # Record initial rank result
        self.m_evidence_store.recordRankResult(
            f_point=f_point,
            f_global_rank=0,
            f_combination=f_combo,
            f_payload={"run": 1},
            f_ordinal=0,
        )

        # Attempt to record again for same rank and combination -> must raise EvidenceCollisionError
        with self.assertRaises(EvidenceCollisionError):
            self.m_evidence_store.recordRankResult(
                f_point=f_point,
                f_global_rank=0,
                f_combination=f_combo,
                f_payload={"run": 2},
                f_ordinal=0,
            )

        # Verify original content is completely intact
        f_res = self.m_evidence_store.readRankResult(
            f_point, f_global_rank=0, f_combination=f_combo, f_ordinal=0
        )
        self.assertIsNotNone(f_res)
        self.assertEqual(f_res.payload, {"run": 1})

    def testSequenceAndCausality(self) -> None:
        """Validates monotonic sequence order and causal predecessor tracking."""
        f_writer = "seq-tester"

        # Sequence 1: Initial event
        f_ev1 = self.m_evidence_store.recordControlEvent(
            f_writer_id=f_writer,
            f_sequence=1,
            f_evidence_kind=EvidenceKind.OBSERVATION,
            f_payload={"step": 1},
        )
        self.assertIsNone(f_ev1.causal_predecessor)

        # Sequence 2: Next event with predecessor
        f_ev2 = self.m_evidence_store.recordControlEvent(
            f_writer_id=f_writer,
            f_sequence=2,
            f_evidence_kind=EvidenceKind.CANCEL_REQUESTED,
            f_payload={"step": 2},
            f_causal_predecessor="event-1",
        )
        self.assertEqual(f_ev2.causal_predecessor, "event-1")

        # Sequence 3: Cancel recorded referencing cancel_requested
        f_ev3 = self.m_evidence_store.recordControlEvent(
            f_writer_id=f_writer,
            f_sequence=3,
            f_evidence_kind=EvidenceKind.CANCEL_RECORDED,
            f_payload={"step": 3},
            f_causal_predecessor="cancel_requested",
        )
        self.assertEqual(f_ev3.causal_predecessor, "cancel_requested")

        # Read back sequence and verify monotonic order
        f_events = self.m_evidence_store.readControlEvents(f_writer)
        self.assertEqual(len(f_events), 3)
        self.assertEqual([f_e.sequence_number for f_e in f_events], [1, 2, 3])

        # Attempting sequence 5 (gap skipping 4) -> EvidenceSequenceError
        with self.assertRaises(EvidenceSequenceError):
            self.m_evidence_store.recordControlEvent(
                f_writer_id=f_writer,
                f_sequence=5,
                f_evidence_kind=EvidenceKind.OBSERVATION,
            )

        # Attempting sequence 2 (duplicate/regression) -> EvidenceSequenceError
        with self.assertRaises(EvidenceSequenceError):
            self.m_evidence_store.recordControlEvent(
                f_writer_id=f_writer,
                f_sequence=2,
                f_evidence_kind=EvidenceKind.OBSERVATION,
            )

        # Read gap detection: simulate artificial sequence gap on filesystem
        f_stream_dir = os.path.join(self.m_layout.controlEventsDir, f_writer)
        os.remove(os.path.join(f_stream_dir, "2.json"))
        with self.assertRaises(EvidenceSequenceError):
            self.m_evidence_store.readControlEvents(f_writer)

    def testExactSchedulerHandleRoundTripsUnchanged(self) -> None:
        """Confirms decimal string job_id is preserved byte-for-byte without integer conversion."""
        # Decimal job ID with leading zeroes or large precision
        f_job_id = "00012345678901234567890"
        f_handle = JobHandle(f_backend="slurm", f_job_id=f_job_id)
        self.assertEqual(f_handle.backend, "slurm")
        self.assertEqual(f_handle.job_id, f_job_id)

        # Record submission_recorded with this handle
        f_point = self.m_point
        f_sub_rec = self.m_evidence_store.recordSubmissionRecorded(
            f_point=f_point,
            f_writer_id="client",
            f_handle=f_handle,
            f_payload={"comment": "preserved decimal string"},
            f_ordinal=0,
        )

        self.assertEqual(f_sub_rec.payload["handle"]["job_id"], f_job_id)

        # Read back submission record from disk and verify byte stability
        f_sub_records = self.m_evidence_store.readSubmissionRecords(
            f_point, f_ordinal=0
        )
        f_read_sub_rec = f_sub_records["submission_recorded"]
        self.assertIsNotNone(f_read_sub_rec)
        self.assertIsInstance(f_read_sub_rec.payload["handle"]["job_id"], str)
        self.assertEqual(f_read_sub_rec.payload["handle"]["job_id"], f_job_id)

        # Deserialized JobHandle
        f_deserialized_handle = JobHandle.fromDict(f_read_sub_rec.payload["handle"])
        self.assertEqual(f_deserialized_handle, f_handle)
        self.assertEqual(f_deserialized_handle.job_id, f_job_id)

    def testOutOfPlanRejected(self) -> None:
        """Rejects evidence for combinations, ranks, or points not in the plan."""
        # 1. Out-of-plan point
        with self.assertRaises(EvidencePlanError):
            self.m_evidence_store.recordSubmissionRequested(
                f_point="99-tasks-999",
                f_writer_id="client",
            )

        # 2. Out-of-plan combination
        with self.assertRaises(EvidencePlanError):
            self.m_evidence_store.recordControllerResult(
                f_point=self.m_point,
                f_combination="c99_b99M",
                f_ordinal=0,
            )

        # 3. Out-of-plan rank (rank 99 on a 1-task point)
        with self.assertRaises(EvidencePlanError):
            self.m_evidence_store.recordRankResult(
                f_point=self.m_point,
                f_global_rank=99,
                f_combination="c16_b8M",
                f_ordinal=0,
            )

        # 4. Negative rank
        with self.assertRaises(EvidencePlanError):
            self.m_evidence_store.recordRankResult(
                f_point=self.m_point,
                f_global_rank=-1,
                f_combination="c16_b8M",
                f_ordinal=0,
            )

    def testCorruptUnknownSymlinkFail(self) -> None:
        """Rejects corrupt JSON, unknown schema versions, and symlinks."""
        f_point = self.m_point
        f_combo = "c16_b8M"
        f_path = self.m_layout.pointRankResultPath(
            f_point, f_global_rank=0, f_combination=f_combo, f_ordinal=0
        )
        os.makedirs(os.path.dirname(f_path), exist_ok=True)

        # 1. Corrupt JSON syntax
        with open(f_path, "w", encoding="utf-8") as f_f:
            f_f.write("{corrupt_json: invalid syntax")

        with self.assertRaises(EvidenceCorruptionError):
            self.m_evidence_store.readRecord(f_path)

        os.remove(f_path)

        # 2. Unknown schema version (schema_version: 99)
        f_invalid_schema = {
            "schema_version": 99,
            "writer_kind": "rank",
            "writer_id": "0",
            "sequence_number": 1,
            "created_at_utc": "2026-08-20T12:00:00Z",
            "evidence_kind": "rank_result",
            "payload": {},
        }
        with open(f_path, "w", encoding="utf-8") as f_f:
            json.dump(f_invalid_schema, f_f)

        with self.assertRaises(EvidenceSchemaError):
            self.m_evidence_store.readRecord(f_path)

        os.remove(f_path)

        # 3. Symlink failure
        f_decoy_path = os.path.join(self.m_temp_dir, "decoy_target.json")
        f_valid_rec = EvidenceRecord(
            f_writer_kind=WriterKind.RANK,
            f_writer_id="0",
            f_sequence_number=1,
            f_evidence_kind=EvidenceKind.RANK_RESULT,
        )
        with open(f_decoy_path, "w", encoding="utf-8") as f_f:
            f_f.write(EvidenceSerializer.serialize(f_valid_rec))

        os.symlink(f_decoy_path, f_path)
        with self.assertRaises((EvidenceCorruptionError, ContainmentError)):
            self.m_evidence_store.readRecord(f_path)

        with self.assertRaises((EvidenceCorruptionError, ContainmentError)):
            self.m_evidence_store.recordRankResult(
                f_point=f_point,
                f_global_rank=0,
                f_combination=f_combo,
                f_ordinal=0,
            )

    def testCrashGapAbsent(self) -> None:
        """Verifies unrecorded evidence after a crash is treated as incomplete without synthesizing success."""
        # scale_points[1] has tasks=2
        f_point_2 = self.m_plan.scale_points[1]
        self.m_artifact_store.preparePoint(f_point_2, f_ordinal=1)
        f_combo = "c16_b8M"

        # Rank 0 records result successfully
        self.m_evidence_store.recordRankResult(
            f_point=f_point_2,
            f_global_rank=0,
            f_combination=f_combo,
            f_payload={"status": "success"},
            f_ordinal=1,
        )

        # Rank 1 crashes before recording result
        f_rank0_res = self.m_evidence_store.readRankResult(
            f_point_2, f_global_rank=0, f_combination=f_combo, f_ordinal=1
        )
        f_rank1_res = self.m_evidence_store.readRankResult(
            f_point_2, f_global_rank=1, f_combination=f_combo, f_ordinal=1
        )

        self.assertIsNotNone(f_rank0_res)
        self.assertIsNone(f_rank1_res)  # Absence is preserved, not synthesized as success

        # Controller started event 1 recorded, but crashed before controller result
        self.m_evidence_store.recordWorkerEvent(
            f_point=f_point_2,
            f_sequence=1,
            f_evidence_kind=EvidenceKind.CONTROLLER_STARTED,
            f_ordinal=1,
        )
        f_ctrl_res = self.m_evidence_store.readControllerResult(
            f_point_2, f_combo, f_ordinal=1
        )
        self.assertIsNone(f_ctrl_res)

    def testControlOrdersSuccessAndInterruption(self) -> None:
        """Asserts whole-run success and interruption event ordering in the control stream."""
        f_writer = "control-orchestrator"

        # Scenario A: Whole run succeeds first, then late interrupt
        f_rec1 = self.m_evidence_store.recordWholeRunSucceeded(
            f_writer_id=f_writer,
            f_sequence=1,
            f_payload={"total_points": 4},
        )
        f_rec2 = self.m_evidence_store.recordInterruption(
            f_writer_id=f_writer,
            f_sequence=2,
            f_payload={"reason": "late SIGINT"},
            f_causal_predecessor="sigint_signal",
        )

        f_events = self.m_evidence_store.readControlEvents(f_writer)
        self.assertEqual(len(f_events), 2)
        self.assertEqual(f_events[0].evidence_kind, EvidenceKind.WHOLE_RUN_SUCCEEDED)
        self.assertEqual(f_events[1].evidence_kind, EvidenceKind.INTERRUPTED)

        # Scenario B: Interrupted first, whole run cannot erase interruption order
        f_writer_b = "control-orchestrator-b"
        f_b1 = self.m_evidence_store.recordInterruption(
            f_writer_id=f_writer_b,
            f_sequence=1,
            f_payload={"reason": "SIGTERM"},
        )
        f_b2 = self.m_evidence_store.recordWholeRunSucceeded(
            f_writer_id=f_writer_b,
            f_sequence=2,
            f_payload={"total_points": 4},
        )

        f_events_b = self.m_evidence_store.readControlEvents(f_writer_b)
        self.assertEqual(len(f_events_b), 2)
        self.assertEqual(f_events_b[0].evidence_kind, EvidenceKind.INTERRUPTED)
        self.assertEqual(f_events_b[1].evidence_kind, EvidenceKind.WHOLE_RUN_SUCCEEDED)

    def testJobHandleValidationAndEquality(self) -> None:
        """Validates JobHandle edge cases, equality, hashing, and invalid values."""
        f_h1 = JobHandle("slurm", "12345")
        f_h2 = JobHandle("SLURM", "12345")
        self.assertEqual(f_h1, f_h2)
        self.assertEqual(hash(f_h1), hash(f_h2))

        with self.assertRaises(EvidenceSchemaError):
            JobHandle("", "12345")
        with self.assertRaises(EvidenceSchemaError):
            JobHandle("slurm", "")
        with self.assertRaises(EvidenceSchemaError):
            JobHandle("slurm\n", "12345")
        with self.assertRaises(EvidenceSchemaError):
            JobHandle("slurm", "12345\0")

    def testEvidenceRecordImmutabilityAndSerialization(self) -> None:
        """Validates EvidenceRecord immutability and schema 1 serialization."""
        f_rec = EvidenceRecord(
            f_writer_kind=WriterKind.CONTROL,
            f_writer_id="ctrl",
            f_sequence_number=1,
            f_evidence_kind=EvidenceKind.OBSERVATION,
            f_payload={"key": "val"},
        )

        with self.assertRaises(AttributeError):
            f_rec.sequence_number = 2  # type: ignore

        f_json = f_rec.toJson()
        f_deserialized = EvidenceRecord.fromJson(f_json)
        self.assertEqual(f_rec, f_deserialized)
        self.assertEqual(f_deserialized.schema_version, 1)

    def testSubmissionLifecycleRecords(self) -> None:
        """Tests complete submission lifecycle evidence recording and query."""
        f_point = self.m_point
        f_handle = JobHandle("pbs", "987654.isambard-pbs")

        # 1. Submission requested
        f_req = self.m_evidence_store.recordSubmissionRequested(
            f_point=f_point,
            f_writer_id="client",
            f_payload={"stage": "request"},
            f_ordinal=0,
        )
        self.assertEqual(f_req.evidence_kind, EvidenceKind.SUBMISSION_REQUESTED)

        # 2. Submission dispatched
        f_disp = self.m_evidence_store.recordSubmissionDispatched(
            f_point=f_point,
            f_writer_id="client",
            f_payload={"stage": "dispatched"},
            f_ordinal=0,
        )
        self.assertEqual(f_disp.evidence_kind, EvidenceKind.SUBMISSION_DISPATCHED)

        # 3. Submission recorded
        f_rec = self.m_evidence_store.recordSubmissionRecorded(
            f_point=f_point,
            f_writer_id="client",
            f_handle=f_handle,
            f_payload={"stage": "recorded"},
            f_ordinal=0,
        )
        self.assertEqual(f_rec.evidence_kind, EvidenceKind.SUBMISSION_RECORDED)
        self.assertEqual(f_rec.payload["handle"]["backend"], "pbs")
        self.assertEqual(f_rec.payload["handle"]["job_id"], "987654.isambard-pbs")

        # 4. Cancel requested
        f_creq = self.m_evidence_store.recordCancelRequested(
            f_point=f_point,
            f_writer_id="client",
            f_handle=f_handle,
            f_ordinal=0,
        )
        self.assertEqual(f_creq.evidence_kind, EvidenceKind.CANCEL_REQUESTED)

        # 5. Cancel recorded
        f_crec = self.m_evidence_store.recordCancelRecorded(
            f_point=f_point,
            f_writer_id="client",
            f_handle=f_handle,
            f_ordinal=0,
        )
        self.assertEqual(f_crec.evidence_kind, EvidenceKind.CANCEL_RECORDED)

        # Query all submission records
        f_all_records = self.m_evidence_store.readSubmissionRecords(f_point, f_ordinal=0)
        self.assertEqual(f_all_records["submission_requested"], f_req)
        self.assertEqual(f_all_records["submission_dispatched"], f_disp)
        self.assertEqual(f_all_records["submission_recorded"], f_rec)
        self.assertEqual(f_all_records["cancel_requested"], f_creq)
        self.assertEqual(f_all_records["cancel_recorded"], f_crec)

    def testEvidenceStoreConstructorAndImmutability(self) -> None:
        """Tests EvidenceStore construction variations and immutability."""
        f_store1 = EvidenceStore(self.m_layout)
        self.assertEqual(f_store1.layout, self.m_layout)
        self.assertIsNone(f_store1.plan)

        f_store2 = EvidenceStore(self.m_temp_dir, f_run_id=self.m_run_id)
        self.assertEqual(f_store2.layout.runId, self.m_run_id)

        with self.assertRaises(AttributeError):
            f_store1.layout = self.m_layout  # type: ignore

        # When plan is None, plan validation is skipped
        f_unplanned_rec = f_store1.recordControlEvent("client", 1, EvidenceKind.OBSERVATION)
        self.assertEqual(f_unplanned_rec.sequence_number, 1)

    def testEvidenceSerializerEdgeCases(self) -> None:
        """Tests EvidenceSerializer with bytes, malformed JSON, and missing fields."""
        f_rec = EvidenceRecord(
            f_writer_kind="control",
            f_writer_id="client",
            f_sequence_number=1,
            f_evidence_kind="observation",
            f_payload={"test": 123},
        )
        f_bytes = f_rec.toJson().encode("utf-8")
        f_deserialized = EvidenceSerializer.deserialize(f_bytes)
        self.assertEqual(f_deserialized, f_rec)

        with self.assertRaises(EvidenceCorruptionError):
            EvidenceSerializer.deserialize(b"not json")

        with self.assertRaises(EvidenceCorruptionError):
            EvidenceSerializer.deserialize("[1, 2, 3]")

        with self.assertRaises(EvidenceSchemaError):
            EvidenceSerializer.deserialize(12345)  # type: ignore

        with self.assertRaises(EvidenceSchemaError):
            EvidenceSerializer.deserialize({"schema_version": 1})  # missing required fields

    def testEvidenceRecordValidation(self) -> None:
        """Tests EvidenceRecord input validation errors."""
        with self.assertRaises(EvidenceSchemaError):
            EvidenceRecord(
                f_writer_kind="invalid_kind",
                f_writer_id="client",
                f_sequence_number=1,
                f_evidence_kind=EvidenceKind.OBSERVATION,
            )

        with self.assertRaises(EvidenceSchemaError):
            EvidenceRecord(
                f_writer_kind=WriterKind.CONTROL,
                f_writer_id="client",
                f_sequence_number=1,
                f_evidence_kind="invalid_kind",
            )

        with self.assertRaises(EvidenceSchemaError):
            EvidenceRecord(
                f_writer_kind=WriterKind.CONTROL,
                f_writer_id="",
                f_sequence_number=1,
                f_evidence_kind=EvidenceKind.OBSERVATION,
            )

        with self.assertRaises(ContainmentError):
            EvidenceRecord(
                f_writer_kind=WriterKind.CONTROL,
                f_writer_id="../escape",
                f_sequence_number=1,
                f_evidence_kind=EvidenceKind.OBSERVATION,
            )

        with self.assertRaises(EvidenceSequenceError):
            EvidenceRecord(
                f_writer_kind=WriterKind.CONTROL,
                f_writer_id="client",
                f_sequence_number=0,
                f_evidence_kind=EvidenceKind.OBSERVATION,
            )

        with self.assertRaises(EvidenceSchemaError):
            EvidenceRecord(
                f_writer_kind=WriterKind.CONTROL,
                f_writer_id="client",
                f_sequence_number=1,
                f_evidence_kind=EvidenceKind.OBSERVATION,
                f_payload="not a dict",  # type: ignore
            )

        with self.assertRaises(EvidenceSchemaError):
            EvidenceRecord(
                f_writer_kind=WriterKind.CONTROL,
                f_writer_id="client",
                f_sequence_number=1,
                f_evidence_kind=EvidenceKind.OBSERVATION,
                f_schema_version=2,
            )

    def testMonotonicStreamStartingNonOne(self) -> None:
        """Tests that starting a new stream with sequence > 1 raises EvidenceSequenceError."""
        with self.assertRaises(EvidenceSequenceError):
            self.m_evidence_store.recordControlEvent(
                f_writer_id="brand-new-stream",
                f_sequence=2,
                f_evidence_kind=EvidenceKind.OBSERVATION,
            )
