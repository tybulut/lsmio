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
import math
import os
import shutil
import tempfile
import unittest
from types import MappingProxyType

from lsmiotool.lib.artifacts import (
    ArtifactError,
    ArtifactLayout,
    ArtifactStore,
    ContainmentError,
)
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
    ResultPayloadValidator,
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
            os.path.join(
                os.path.dirname(__file__), "..", "..", "etc", "environments.json"
            )
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
        f_req = RunRequest(
            f_target="lsmio", f_scale="bake", f_ssd=False, f_setup="NATIVE"
        )
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

    def testIntegerPointNamedFromMatchedPlanPoint(self) -> None:
        """An int point is an index or a task count; the directory is the matched point's NN-tasks-T."""
        f_points = self.m_plan.scale_points
        self.assertEqual([f_p.tasks for f_p in f_points[:4]], [1, 2, 4, 8])
        # (int, expected plan index): 0 and 3 are indexes (no point has 0 or 3 tasks), 4 is a task count.
        for f_int, f_idx in ((0, 0), (3, 3), (4, 2)):
            with self.subTest(f_int=f_int):
                f_sp = f_points[f_idx]
                f_name = f"{f_idx:02d}-tasks-{f_sp.tasks}"
                self.m_artifact_store.preparePoint(f_sp, f_ordinal=f_idx)
                f_rec = self.m_evidence_store.recordSubmissionRequested(
                    f_int, "client"
                )
                f_path = os.path.join(
                    self.m_layout.pointsDir,
                    f_name,
                    "scheduler",
                    "submission_requested.json",
                )
                self.assertTrue(os.path.isfile(f_path))
                self.assertEqual(f_rec.point_id, f_name)
                self.assertEqual(
                    self.m_evidence_store.readSubmissionRecords(f_int)[
                        "submission_requested"
                    ].point_id,
                    f_name,
                )

    def testIntegerPointFirstMatchInPlanOrder(self) -> None:
        """An int that is one point's index and another's task count resolves to the first in plan order."""
        f_points = self.m_plan.scale_points
        # 2 is the index of tasks=4 (idx 2) and the task count of idx 1; idx 1 comes first.
        self.assertEqual(f_points[1].tasks, 2)
        self.assertEqual(f_points[2].tasks, 4)
        self.m_artifact_store.preparePoint(f_points[1], f_ordinal=1)
        self.m_artifact_store.preparePoint(f_points[2], f_ordinal=2)
        f_rec = self.m_evidence_store.recordSubmissionRequested(2, "client")
        self.assertEqual(f_rec.point_id, "01-tasks-2")
        self.assertFalse(
            os.path.exists(
                os.path.join(
                    self.m_layout.pointsDir,
                    "02-tasks-4",
                    "scheduler",
                    "submission_requested.json",
                )
            )
        )

    def testIntegerPointRejections(self) -> None:
        """Outside-plan ints, bool points and contradictory ordinals raise EvidencePlanError; no plan raises ArtifactError."""
        f_run = self.m_run_id
        f_out = f"Point '99999' is not part of plan for run '{f_run}'"
        with self.assertRaises(EvidencePlanError) as f_cm:
            self.m_evidence_store.recordSubmissionRequested(99999, "client")
        self.assertEqual(str(f_cm.exception), f_out)
        with self.assertRaises(EvidencePlanError) as f_cm:
            self.m_evidence_store.readSubmissionRecords(99999)
        self.assertEqual(str(f_cm.exception), f_out)
        with self.assertRaises(EvidencePlanError) as f_cm:
            self.m_evidence_store.readWorkerEvents(99999)
        self.assertEqual(str(f_cm.exception), f_out)
        # bool is an int subclass but never a point.
        for f_b in (True, False):
            with self.subTest(f_b=f_b):
                with self.assertRaises(EvidencePlanError) as f_cm:
                    self.m_evidence_store.recordSubmissionRequested(f_b, "client")
                self.assertEqual(
                    str(f_cm.exception),
                    f"Point '{f_b}' is not part of plan for run '{f_run}'",
                )
        # Task count 4 matches plan index 2; an explicit ordinal must agree.
        with self.assertRaises(EvidencePlanError) as f_cm:
            self.m_evidence_store.recordSubmissionRequested(
                4, "client", f_ordinal=3
            )
        self.assertEqual(
            str(f_cm.exception),
            f"Ordinal 3 contradicts point '4' matched at plan index 2 for run '{f_run}'",
        )
        self.m_artifact_store.preparePoint(self.m_plan.scale_points[2], f_ordinal=2)
        f_rec = self.m_evidence_store.recordSubmissionRequested(
            4, "client", f_ordinal=2
        )
        self.assertEqual(f_rec.point_id, "02-tasks-4")
        # Without a plan the layout rejects the int.
        f_planless = EvidenceStore(self.m_layout)
        with self.assertRaises(ArtifactError) as f_cm:
            f_planless.recordSubmissionRequested(1, "client")
        self.assertIn("Integer point needs a plan", str(f_cm.exception))
        with self.assertRaises(ArtifactError):
            f_planless.readSubmissionRecords(1)

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
        self.assertIsNone(
            f_rank1_res
        )  # Absence is preserved, not synthesized as success

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
        f_all_records = self.m_evidence_store.readSubmissionRecords(
            f_point, f_ordinal=0
        )
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
        f_unplanned_rec = f_store1.recordControlEvent(
            "client", 1, EvidenceKind.OBSERVATION
        )
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
            EvidenceSerializer.deserialize(
                {"schema_version": 1}
            )  # missing required fields

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

    def testTerminalPayloadExactSchemasAndMetadataMatch(self) -> None:
        """Chunk 017: Verifies exact schemas, allowed/forbidden keys, type constraints, and output validation."""
        # 1. Base / Shared Payload Tests
        # Valid shared success
        f_s1 = ResultPayloadValidator.validateSharedPayload(
            {"status": "success", "exit_code": 0}
        )
        self.assertEqual(f_s1["status"], "success")
        self.assertEqual(f_s1["exit_code"], 0)

        # Aliases for status and returncode
        f_s2 = ResultPayloadValidator.validateSharedPayload(
            {"status": "completed", "returncode": 0}
        )
        self.assertEqual(f_s2["exit_code"], 0)
        f_s3 = ResultPayloadValidator.validateSharedPayload(
            {"status": "SUCCEEDED", "exit_code": 0}
        )
        self.assertEqual(f_s3["status"], "SUCCEEDED")
        f_s4 = ResultPayloadValidator.validateSharedPayload(
            {"status": "FAILED", "exit_code": 1}
        )
        self.assertEqual(f_s4["status"], "FAILED")

        # Negative: Non-dict, empty dict, missing keys
        for f_invalid in (None, [], "", 123, {}, {"elapsed_seconds": 1.0}):
            with self.assertRaises(EvidenceSchemaError):
                ResultPayloadValidator.validateSharedPayload(f_invalid)

        with self.assertRaises(EvidenceSchemaError):
            ResultPayloadValidator.validateSharedPayload(
                {"exit_code": 0}
            )  # missing status

        with self.assertRaises(EvidenceSchemaError):
            ResultPayloadValidator.validateSharedPayload(
                {"status": "success"}
            )  # missing exit_code

        # Negative: Type mismatch (bool, string)
        with self.assertRaises(EvidenceSchemaError):
            ResultPayloadValidator.validateSharedPayload(
                {"status": "success", "exit_code": True}
            )
        with self.assertRaises(EvidenceSchemaError):
            ResultPayloadValidator.validateSharedPayload(
                {"status": "failed", "exit_code": False}
            )
        with self.assertRaises(EvidenceSchemaError):
            ResultPayloadValidator.validateSharedPayload(
                {"status": "success", "exit_code": "0"}
            )

        # Negative: Contradictions
        with self.assertRaises(EvidenceSchemaError):
            ResultPayloadValidator.validateSharedPayload(
                {"status": "success", "exit_code": 1}
            )
        with self.assertRaises(EvidenceSchemaError):
            ResultPayloadValidator.validateSharedPayload(
                {"status": "success", "exit_code": 0, "error": "unexpected"}
            )
        with self.assertRaises(EvidenceSchemaError):
            ResultPayloadValidator.validateSharedPayload(
                {"status": "success", "exit_code": 0, "timed_out": True}
            )
        with self.assertRaises(EvidenceSchemaError):
            ResultPayloadValidator.validateSharedPayload(
                {"status": "failed", "exit_code": 0}
            )

        # Negative: Invalid optional field types
        with self.assertRaises(EvidenceSchemaError):
            ResultPayloadValidator.validateSharedPayload(
                {"status": "success", "exit_code": 0, "elapsed_seconds": True}
            )
        with self.assertRaises(EvidenceSchemaError):
            ResultPayloadValidator.validateSharedPayload(
                {"status": "success", "exit_code": 0, "elapsed_seconds": -5.0}
            )
        with self.assertRaises(EvidenceSchemaError):
            ResultPayloadValidator.validateSharedPayload(
                {"status": "failed", "exit_code": 143, "signal_number": True}
            )
        with self.assertRaises(EvidenceSchemaError):
            ResultPayloadValidator.validateSharedPayload(
                {"status": "success", "exit_code": 0, "exit_status": 2}
            )

        # 2. Rank Payload Validation Tests
        f_rank_log = self.m_layout.pointRankLogPath(
            self.m_point, 0, "c16_b8M", f_ordinal=0
        )
        f_rank_res = os.path.join(
            self.m_layout.pointRankCombinationDir(self.m_point, 0, "c16_b8M", 0),
            "rank_0.db",
        )
        os.makedirs(os.path.dirname(f_rank_log), exist_ok=True)
        os.makedirs(os.path.dirname(f_rank_res), exist_ok=True)
        with open(f_rank_log, "w", encoding="utf-8") as f_f:
            f_f.write("rank log\n")
        with open(f_rank_res, "w", encoding="utf-8") as f_f:
            f_f.write("rank db\n")

        f_valid_rank_payload = {
            "status": "success",
            "exit_code": 0,
            "exit_status": 0,
            "global_rank": 0,
            "rank": 0,
            "combination": "c16_b8M",
            "argv": ["lsmioworker", "rank", "c16_b8M"],
            "log_path": f_rank_log,
            "result_path": f_rank_res,
            "timed_out": False,
        }
        f_clean_rank = ResultPayloadValidator.validateRankPayload(
            f_valid_rank_payload,
            f_expected_rank=0,
            f_expected_combination="c16_b8M",
            f_validate_files=True,
            f_layout=self.m_layout,
        )
        self.assertEqual(f_clean_rank["rank"], 0)

        # Rank identity contradictions
        with self.assertRaises(EvidenceSchemaError):
            ResultPayloadValidator.validateRankPayload(
                {**f_valid_rank_payload, "global_rank": 1, "rank": 0}
            )
        with self.assertRaises(EvidenceSchemaError):
            ResultPayloadValidator.validateRankPayload(
                f_valid_rank_payload, f_expected_rank=2
            )
        with self.assertRaises(EvidenceSchemaError):
            ResultPayloadValidator.validateRankPayload(
                f_valid_rank_payload, f_expected_combination="c4_b64K"
            )

        # Forbidden extra fields
        with self.assertRaises(EvidenceSchemaError):
            ResultPayloadValidator.validateRankPayload(
                {**f_valid_rank_payload, "arbitrary_extra_field": "disallowed"}
            )

        # Missing required success fields
        for f_missing_key in (
            "exit_status",
            "argv",
            "log_path",
            "result_path",
            "timed_out",
        ):
            f_bad = dict(f_valid_rank_payload)
            del f_bad[f_missing_key]
            with self.assertRaises(EvidenceSchemaError):
                ResultPayloadValidator.validateRankPayload(f_bad, f_strict=True)

        # Rank file validation errors
        f_sym_res = os.path.join(
            self.m_layout.pointRankCombinationDir(self.m_point, 0, "c16_b8M", 0),
            "sym_rank_0.db",
        )
        if os.path.exists(f_sym_res):
            os.remove(f_sym_res)
        os.symlink(f_rank_res, f_sym_res)
        with self.assertRaises(EvidenceSchemaError):
            ResultPayloadValidator.validateRankPayload(
                {**f_valid_rank_payload, "result_path": f_sym_res},
                f_validate_files=True,
                f_layout=self.m_layout,
            )

        f_nonexistent_res = os.path.join(
            self.m_layout.pointRankCombinationDir(self.m_point, 0, "c16_b8M", 0),
            "nonexistent.db",
        )
        with self.assertRaises(EvidenceSchemaError):
            ResultPayloadValidator.validateRankPayload(
                {**f_valid_rank_payload, "result_path": f_nonexistent_res},
                f_validate_files=True,
                f_layout=self.m_layout,
            )

        with self.assertRaises(ContainmentError):
            ResultPayloadValidator.validateRankPayload(
                {**f_valid_rank_payload, "result_path": "/escape/path/db.db"},
                f_validate_files=True,
                f_layout=self.m_layout,
            )

        # 3. Controller Payload Validation Tests
        f_valid_ctrl_ior = {
            "status": "success",
            "exit_code": 0,
            "stage": "execution",
            "combination": "c16_b8M",
        }
        f_clean_ctrl = ResultPayloadValidator.validateControllerPayload(
            f_valid_ctrl_ior, f_target="ior", f_expected_combination="c16_b8M"
        )
        self.assertEqual(f_clean_ctrl["status"], "success")

        # LSMIO requires tasks_validated
        with self.assertRaises(EvidenceSchemaError):
            ResultPayloadValidator.validateControllerPayload(
                f_valid_ctrl_ior, f_target="lsmio", f_strict=True
            )

        f_valid_ctrl_lsmio = {
            "status": "success",
            "exit_code": 0,
            "stage": "rank_evidence",
            "tasks_validated": 1,
            "combination": "c16_b8M",
        }
        ResultPayloadValidator.validateControllerPayload(
            f_valid_ctrl_lsmio, f_target="lsmio", f_expected_tasks=1
        )

        # tasks_validated mismatch or invalid
        with self.assertRaises(EvidenceSchemaError):
            ResultPayloadValidator.validateControllerPayload(
                f_valid_ctrl_lsmio, f_target="lsmio", f_expected_tasks=4
            )
        with self.assertRaises(EvidenceSchemaError):
            ResultPayloadValidator.validateControllerPayload(
                {**f_valid_ctrl_lsmio, "tasks_validated": True}, f_target="lsmio"
            )
        with self.assertRaises(EvidenceSchemaError):
            ResultPayloadValidator.validateControllerPayload(
                {**f_valid_ctrl_lsmio, "tasks_validated": 0}, f_target="lsmio"
            )

        # Controller output_path file validation
        f_ctrl_out = os.path.join(
            self.m_layout.pointLogsDir(self.m_point, 0), "ior.stdout"
        )
        with open(f_ctrl_out, "w", encoding="utf-8") as f_f:
            f_f.write("ior output\n")
        f_ctrl_with_out = {**f_valid_ctrl_ior, "output_path": f_ctrl_out}
        ResultPayloadValidator.validateControllerPayload(
            f_ctrl_with_out, f_validate_files=True, f_layout=self.m_layout
        )

        f_sym_out = os.path.join(
            self.m_layout.pointLogsDir(self.m_point, 0), "sym_ior.stdout"
        )
        if os.path.exists(f_sym_out):
            os.remove(f_sym_out)
        os.symlink(f_ctrl_out, f_sym_out)
        with self.assertRaises(EvidenceSchemaError):
            ResultPayloadValidator.validateControllerPayload(
                {**f_valid_ctrl_ior, "output_path": f_sym_out},
                f_validate_files=True,
                f_layout=self.m_layout,
            )

        # 4. isSuccessPayload & isFailurePayload helpers
        self.assertTrue(
            ResultPayloadValidator.isSuccessPayload(
                f_valid_ctrl_lsmio,
                EvidenceKind.CONTROLLER_RESULT,
                f_target="lsmio",
                f_expected_tasks=1,
            )
        )
        self.assertFalse(
            ResultPayloadValidator.isFailurePayload(
                f_valid_ctrl_lsmio, EvidenceKind.CONTROLLER_RESULT
            )
        )
        self.assertTrue(
            ResultPayloadValidator.isFailurePayload(
                {"status": "failed", "exit_code": 1, "stage": "execution"},
                EvidenceKind.CONTROLLER_RESULT,
            )
        )
        self.assertFalse(
            ResultPayloadValidator.isSuccessPayload(
                {"status": "failed", "exit_code": 1, "stage": "execution"},
                EvidenceKind.CONTROLLER_RESULT,
            )
        )
        self.assertFalse(
            ResultPayloadValidator.isSuccessPayload({}, EvidenceKind.CONTROLLER_RESULT)
        )
        self.assertFalse(
            ResultPayloadValidator.isFailurePayload({}, EvidenceKind.CONTROLLER_RESULT)
        )


class ResultPayloadValidatorTest(unittest.TestCase):
    """Pure validator calls: exact messages, copies returned, inputs untouched."""

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.mkdtemp(prefix="lsmiotool-payload-test-")
        self.m_log = os.path.join(self.m_temp_dir, "rank_0.log")
        self.m_res = os.path.join(self.m_temp_dir, "rank_0.db")
        for f_path in (self.m_log, self.m_res):
            with open(f_path, "w", encoding="utf-8") as f_file:
                f_file.write("x\n")
        self.m_dir = os.path.join(self.m_temp_dir, "adir")
        os.mkdir(self.m_dir)
        self.m_missing = os.path.join(self.m_temp_dir, "missing.db")
        self.m_rank_ok = {
            "status": "success",
            "exit_code": 0,
            "exit_status": 0,
            "global_rank": 0,
            "rank": 0,
            "combination": "c16_b8M",
            "argv": ["lsmioworker", "rank"],
            "log_path": self.m_log,
            "result_path": self.m_res,
            "timed_out": False,
        }
        self.m_ctrl_ok = {
            "status": "success",
            "exit_code": 0,
            "stage": "execution",
            "combination": "c16_b8M",
        }
        self.m_ctrl_fail = {"status": "failed", "exit_code": 1, "stage": "execution"}

    def tearDown(self) -> None:
        shutil.rmtree(self.m_temp_dir, ignore_errors=True)

    def _assertNoNewFiles(self) -> None:
        self.assertEqual(
            sorted(os.listdir(self.m_temp_dir)), ["adir", "rank_0.db", "rank_0.log"]
        )

    def _assertRejects(self, f_call, f_payload, f_message, f_prefix=False):
        f_before = copy.deepcopy(f_payload)
        with self.assertRaises(EvidenceSchemaError) as f_cm:
            f_call(f_payload)
        if f_prefix:
            self.assertTrue(
                str(f_cm.exception).startswith(f_message), str(f_cm.exception)
            )
        else:
            self.assertEqual(str(f_cm.exception), f_message)
        self.assertEqual(f_payload, f_before)
        return f_cm.exception

    def _assertAccepts(self, f_call, f_payload):
        f_before = copy.deepcopy(f_payload)
        f_clean = f_call(f_payload)
        self.assertEqual(f_clean, f_payload)
        self.assertIsNot(f_clean, f_payload)
        self.assertEqual(f_payload, f_before)
        return f_clean

    def testSharedStatusMustBeNonBlankString(self) -> None:
        """A missing, blank or non-string status is rejected with the value."""
        for f_v in (None, 5, "", "   ", ["success"]):
            with self.subTest(f_v=f_v):
                self._assertRejects(
                    ResultPayloadValidator.validateSharedPayload,
                    {"status": f_v, "exit_code": 0},
                    "Result payload 'status' must be a non-empty string, got: "
                    + repr(f_v),
                )
        self._assertNoNewFiles()

    def testSharedStatusMustBeCanonical(self) -> None:
        """A non-canonical status is rejected with the raw padded value."""
        for f_v in ("ok", "SUCCESSFUL", "pass", " done "):
            with self.subTest(f_v=f_v):
                self._assertRejects(
                    ResultPayloadValidator.validateSharedPayload,
                    {"status": f_v, "exit_code": 0},
                    f"Invalid result payload status: {f_v!r} (must be one of "
                    "['complete', 'completed', 'failed', 'failure', 'succeeded', "
                    "'success'])",
                )
        self._assertNoNewFiles()

    def testSharedTimedOutMustBeBool(self) -> None:
        """timed_out must be a real bool; False is accepted."""
        for f_v in ("false", 0, None, 1):
            with self.subTest(f_v=f_v):
                self._assertRejects(
                    ResultPayloadValidator.validateSharedPayload,
                    {"status": "success", "exit_code": 0, "timed_out": f_v},
                    f"timed_out must be a boolean, got: {f_v!r}",
                )
        f_clean = self._assertAccepts(
            ResultPayloadValidator.validateSharedPayload,
            {"status": "success", "exit_code": 0, "timed_out": False},
        )
        self.assertIs(f_clean["timed_out"], False)
        self._assertNoNewFiles()

    def testSharedExitStatusMustBeInteger(self) -> None:
        """exit_status rejects bools and non-integers."""
        for f_v in (True, False, "0", 0.0, None):
            with self.subTest(f_v=f_v):
                self._assertRejects(
                    ResultPayloadValidator.validateSharedPayload,
                    {"status": "failed", "exit_code": 1, "exit_status": f_v},
                    f"exit_status must be an integer, got: {f_v!r}",
                )
        self._assertNoNewFiles()

    def testSharedSignalNumberAcceptedOnFailure(self) -> None:
        """signal_number is kept when an int, rejected otherwise; mappings become dicts."""
        f_a = {"status": "failed", "exit_code": 143, "signal_number": 15}
        self._assertAccepts(ResultPayloadValidator.validateSharedPayload, f_a)
        f_proxy = MappingProxyType(
            {
                "status": " Failure ",
                "exit_code": -9,
                "signal_number": 9,
                "elapsed_seconds": 0,
            }
        )
        f_clean = ResultPayloadValidator.validateSharedPayload(f_proxy)
        self.assertIs(type(f_clean), dict)
        self.assertEqual(f_clean, dict(f_proxy))
        self.assertEqual(f_clean["status"], " Failure ")
        self._assertRejects(
            ResultPayloadValidator.validateSharedPayload,
            {"status": "failed", "exit_code": 1, "signal_number": "15"},
            "signal_number must be an integer, got: '15'",
        )
        self._assertNoNewFiles()

    def testSharedElapsedSecondsRejectsNonFinite(self) -> None:
        """elapsed_seconds NaN and infinity are rejected, as are negative numbers."""
        # 10**400 is an int too large for float: isfinite would raise OverflowError.
        for f_bad in (float("nan"), float("inf"), float("-inf"), 10**400):
            with self.subTest(f_bad=repr(f_bad)):
                self._assertRejects(
                    ResultPayloadValidator.validateSharedPayload,
                    {"status": "success", "exit_code": 0, "elapsed_seconds": f_bad},
                    f"elapsed_seconds must be a non-negative float/int, got: {f_bad!r}",
                )
        f_json = json.loads(
            '{"status": "success", "exit_code": 0, "elapsed_seconds": NaN}'
        )
        self._assertRejects(
            ResultPayloadValidator.validateSharedPayload,
            f_json,
            "elapsed_seconds must be a non-negative float/int, got: nan",
        )
        self._assertRejects(
            ResultPayloadValidator.validateSharedPayload,
            {"status": "success", "exit_code": 0, "elapsed_seconds": -5.0},
            "elapsed_seconds must be a non-negative float/int, got: -5.0",
        )
        self._assertNoNewFiles()

    def testRankIdentityFieldTypes(self) -> None:
        """global_rank, rank and combination are type checked on a failure payload."""
        f_rows = (
            ("global_rank", (-1, True, "0", 1.0, None), "a non-negative integer"),
            ("rank", (-1, True, "0", 1.5), "a non-negative integer"),
            ("combination", ("", "   ", 5, None), "a non-empty string"),
        )
        for f_field, f_values, f_what in f_rows:
            for f_v in f_values:
                with self.subTest(f_field=f_field, f_v=f_v):
                    self._assertRejects(
                        ResultPayloadValidator.validateRankPayload,
                        {"status": "failed", "exit_code": 1, f_field: f_v},
                        f"{f_field} must be {f_what}, got: {f_v!r}",
                    )
        self._assertNoNewFiles()

    def testRankStrictSuccessRequiresRankAndCombination(self) -> None:
        """Strict success needs a rank and a combination; non-strict does not."""
        f_validate = ResultPayloadValidator.validateRankPayload
        f_no_rank = {
            f_k: f_v
            for f_k, f_v in self.m_rank_ok.items()
            if f_k not in ("global_rank", "rank")
        }
        self._assertRejects(
            f_validate,
            f_no_rank,
            "Rank success payload requires 'global_rank' or 'rank'",
        )
        f_clean = self._assertAccepts(
            lambda f_p: f_validate(f_p, f_strict=False), f_no_rank
        )
        self.assertNotIn("rank", f_clean)
        self.assertNotIn("global_rank", f_clean)
        f_no_comb = {
            f_k: f_v for f_k, f_v in self.m_rank_ok.items() if f_k != "combination"
        }
        self._assertRejects(
            f_validate, f_no_comb, "Rank success payload requires 'combination'"
        )
        self._assertNoNewFiles()

    def testRankStrictSuccessArgvShape(self) -> None:
        """argv must be a non-empty list of strings (strict success)."""
        for f_v in ([], (), ["a", 1], "lsmioworker", None):
            with self.subTest(f_v=f_v):
                self._assertRejects(
                    ResultPayloadValidator.validateRankPayload,
                    {**self.m_rank_ok, "argv": f_v},
                    f"Rank success argv must be a non-empty list of strings, got: {f_v!r}",
                )
        f_clean = ResultPayloadValidator.validateRankPayload(
            {**self.m_rank_ok, "argv": ("a", "b")}
        )
        self.assertEqual(f_clean["argv"], ("a", "b"))
        self._assertNoNewFiles()

    def testRankFileChecksWithoutLayout(self) -> None:
        """File checks run on plain paths when no layout is given."""
        f_clean = ResultPayloadValidator.validateRankPayload(
            self.m_rank_ok,
            f_expected_rank=0,
            f_expected_combination=" c16_b8M ",
            f_validate_files=True,
        )
        self.assertEqual(f_clean, self.m_rank_ok)

        def f_call(f_p):
            return ResultPayloadValidator.validateRankPayload(
                f_p, f_validate_files=True
            )

        self._assertRejects(
            f_call,
            {**self.m_rank_ok, "result_path": self.m_dir},
            f"Rank success result_path '{self.m_dir}' is not a regular file",
        )
        self._assertRejects(
            f_call,
            {**self.m_rank_ok, "log_path": self.m_dir},
            f"Rank success log_path '{self.m_dir}' is not a regular file",
        )
        f_exc = self._assertRejects(
            f_call,
            {**self.m_rank_ok, "result_path": self.m_missing},
            f"Rank success result_path '{self.m_missing}' does not exist: ",
            f_prefix=True,
        )
        self.assertIsInstance(f_exc.__cause__, FileNotFoundError)
        self.assertFalse(os.path.exists(self.m_missing))
        self.assertTrue(os.path.isdir(self.m_dir))
        self._assertNoNewFiles()

    def testRankFailureRejectsExtraFields(self) -> None:
        """A failure payload may only carry the allowed fields."""
        self._assertRejects(
            ResultPayloadValidator.validateRankPayload,
            {
                "status": "failed",
                "exit_code": 2,
                "zeta": 1,
                "alpha": 2,
                "error": "boom",
            },
            "Rank failure payload contains forbidden extra fields: ['alpha', 'zeta']",
        )
        self._assertAccepts(
            ResultPayloadValidator.validateRankPayload,
            {
                "status": "failed",
                "exit_code": 2,
                "error": "boom",
                "signal_number": 9,
                "spawn_error": "x",
                "stage": "exec",
            },
        )
        self._assertNoNewFiles()

    def testRankRedundantGuardsFireEarlier(self) -> None:
        """The shared checks fire before the rank-specific duplicates."""
        self._assertRejects(
            ResultPayloadValidator.validateRankPayload,
            {**self.m_rank_ok, "exit_status": 3},
            "Success payload cannot have non-zero exit_status: 3",
        )
        self._assertRejects(
            ResultPayloadValidator.validateRankPayload,
            {**self.m_rank_ok, "timed_out": None},
            "timed_out must be a boolean, got: None",
        )
        self._assertNoNewFiles()

    def testControllerCombinationMismatchAndExtraFields(self) -> None:
        """Controller payloads check the combination and forbid rank fields."""
        f_validate = ResultPayloadValidator.validateControllerPayload
        self._assertRejects(
            lambda f_p: f_validate(f_p, f_expected_combination="c4_b64K"),
            self.m_ctrl_ok,
            "Controller combination mismatch: expected 'c4_b64K', got 'c16_b8M'",
        )
        # Observation: the controller combination is compared through str().
        f_clean = f_validate(
            {**self.m_ctrl_ok, "combination": 5}, f_expected_combination=" 5 "
        )
        self.assertEqual(f_clean["combination"], 5)
        self._assertRejects(
            f_validate,
            {**self.m_ctrl_ok, "rank": 0, "argv": ["x"]},
            "Controller success payload contains forbidden extra fields: ['argv', 'rank']",
        )
        self._assertRejects(
            f_validate,
            {**self.m_ctrl_fail, "rank": 0, "argv": []},
            "Controller failure payload contains forbidden extra fields: ['argv', 'rank']",
        )
        self._assertNoNewFiles()

    def testControllerStageRequiredWhenStrict(self) -> None:
        """A strict controller payload needs a non-empty stage."""
        f_validate = ResultPayloadValidator.validateControllerPayload
        f_absent = object()
        for f_v in (f_absent, "", "  ", 3):
            for f_base, f_word in (
                (self.m_ctrl_ok, "success"),
                (self.m_ctrl_fail, "failure"),
            ):
                with self.subTest(f_v=f_v, f_word=f_word):
                    f_payload = {f_k: f_x for f_k, f_x in f_base.items() if f_k != "stage"}
                    if f_v is not f_absent:
                        f_payload["stage"] = f_v
                    self._assertRejects(
                        f_validate,
                        f_payload,
                        f"Controller {f_word} payload requires non-empty 'stage'",
                    )
                    self._assertAccepts(
                        lambda f_p: f_validate(f_p, f_strict=False), f_payload
                    )
        self._assertNoNewFiles()

    def testControllerOutputFileChecks(self) -> None:
        """output_path is checked as a file only when file validation is on."""

        def f_call(f_p):
            return ResultPayloadValidator.validateControllerPayload(
                f_p, f_validate_files=True
            )

        for f_v in ("", "   ", 7):
            with self.subTest(f_v=f_v):
                self._assertRejects(
                    f_call,
                    {**self.m_ctrl_ok, "output_path": f_v},
                    "output_path must be a non-empty string",
                )
        f_exc = self._assertRejects(
            f_call,
            {**self.m_ctrl_ok, "output_path": self.m_missing},
            f"Controller output artifact '{self.m_missing}' does not exist: ",
            f_prefix=True,
        )
        self.assertIsInstance(f_exc.__cause__, FileNotFoundError)
        self._assertRejects(
            f_call,
            {**self.m_ctrl_ok, "output_path": self.m_dir},
            f"Controller output artifact '{self.m_dir}' is not a regular file",
        )
        self._assertAccepts(f_call, {**self.m_ctrl_ok, "output_path": self.m_log})
        self._assertAccepts(
            ResultPayloadValidator.validateControllerPayload,
            {**self.m_ctrl_ok, "output_path": ""},
        )
        self.assertFalse(os.path.exists(self.m_missing))
        self._assertNoNewFiles()

    def testPayloadPredicatesOnNonMappings(self) -> None:
        """The predicates return False for non-mappings and route by kind."""
        for f_v in (None, [], "success", 5):
            with self.subTest(f_v=f_v):
                self.assertIs(ResultPayloadValidator.isSuccessPayload(f_v), False)
                self.assertIs(ResultPayloadValidator.isFailurePayload(f_v), False)
        self.assertIs(
            ResultPayloadValidator.isSuccessPayload(MappingProxyType(self.m_ctrl_ok)),
            True,
        )
        self.assertIs(
            ResultPayloadValidator.isFailurePayload(MappingProxyType(self.m_ctrl_fail)),
            True,
        )
        self.assertIs(
            ResultPayloadValidator.isSuccessPayload(self.m_rank_ok, "rank_result"), True
        )
        self.assertIs(
            ResultPayloadValidator.isSuccessPayload(
                {**self.m_rank_ok, "argv": []}, "rank_result", f_strict=True
            ),
            False,
        )
        self._assertNoNewFiles()
