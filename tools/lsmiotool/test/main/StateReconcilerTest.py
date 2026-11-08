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
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple, Union
import unittest
from unittest.mock import patch

from lsmiotool.lib.artifacts import ArtifactLayout, ArtifactStore
from lsmiotool.lib.evidence import (
    EvidenceCorruptionError,
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
)
from lsmiotool.lib.site import EnvironmentResolver
from lsmiotool.lib.state import (
    OverallRunState,
    PointRunState,
    PointStateView,
    RunStateView,
    SchedulerJobState,
    StateError,
    StateReconciler,
)


class StateReconcilerTest(unittest.TestCase):
    """Unit tests covering all state reconciliation rules, views, and edge cases."""

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.mkdtemp(prefix="lsmiotool-state-test-")
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

    def tearDown(self) -> None:
        shutil.rmtree(self.m_temp_dir, ignore_errors=True)

    def _createTestPlan(
        self,
        f_run_id: str,
        f_target: str = "lsmio",
        f_scale: str = "local",
        f_setup: str = "NATIVE",
    ) -> RunPlan:
        f_req = RunRequest(
            f_target=f_target, f_scale=f_scale, f_ssd=False, f_setup=f_setup
        )
        f_tokens = [f"lm-{f_i:024d}" for f_i in range(1, 20)]
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

    def _setupRunEnvironment(
        self,
        f_run_id: str,
        f_target: str = "lsmio",
        f_scale: str = "local",
        f_setup: str = "NATIVE",
    ):
        f_plan = self._createTestPlan(
            f_run_id, f_target=f_target, f_scale=f_scale, f_setup=f_setup
        )
        f_art_store = ArtifactStore(self.m_temp_dir, f_run_id)
        f_art_store.allocateRun(f_plan)
        for f_idx, f_sp in enumerate(f_plan.scale_points):
            f_art_store.preparePoint(f_sp, f_ordinal=f_idx)
        f_evidence_store = EvidenceStore(f_art_store.layout, f_plan=f_plan)
        return f_plan, f_art_store, f_evidence_store

    def _validControllerSuccessPayload(
        self,
        f_combo: str = "c16_b8M",
        f_tasks: Optional[int] = None,
        f_stage: str = "execution",
    ) -> Dict[str, Any]:
        f_payload: Dict[str, Any] = {
            "status": "success",
            "exit_code": 0,
            "stage": f_stage,
            "combination": f_combo,
        }
        if f_tasks is not None:
            f_payload["tasks_validated"] = f_tasks
        return f_payload

    def _validRankSuccessPayload(
        self,
        f_rank: int = 0,
        f_combo: str = "c16_b8M",
    ) -> Dict[str, Any]:
        return {
            "status": "success",
            "exit_code": 0,
            "exit_status": 0,
            "global_rank": f_rank,
            "rank": f_rank,
            "combination": f_combo,
            "argv": ["lsmioworker", "rank", f_combo],
            "log_path": f"/tmp/log_{f_rank}.log",
            "result_path": f"/tmp/res_{f_rank}.db",
            "timed_out": False,
        }

    def testSuccessRequiresCompleteEvidenceAndMarker(self) -> None:
        """Rule 1: Overall success requires terminal scheduler success, complete evidence, and success marker."""
        f_run_id = "run-state-001"
        f_plan, f_art_store, f_store = self._setupRunEnvironment(
            f_run_id, f_target="lsmio", f_scale="local", f_setup="NATIVE"
        )
        f_point = f_plan.scale_points[0]
        f_handle = JobHandle("slurm", "1001")

        # 1. Record submission records
        f_store.recordSubmissionRequested(f_point, "client", f_ordinal=0)
        f_store.recordSubmissionDispatched(f_point, "client", f_ordinal=0)
        f_store.recordSubmissionRecorded(
            f_point, "client", f_handle=f_handle, f_ordinal=0
        )

        # 2. Record worker started event
        f_store.recordWorkerEvent(
            f_point, 1, EvidenceKind.CONTROLLER_STARTED, f_ordinal=0
        )

        # 3. Record all 6 combinations controller results and rank results
        for f_combo in f_plan.combinations:
            f_store.recordControllerResult(
                f_point,
                f_combo,
                f_payload=self._validControllerSuccessPayload(f_combo.name, f_tasks=1),
                f_ordinal=0,
            )
            f_store.recordRankResult(
                f_point,
                f_global_rank=0,
                f_combination=f_combo,
                f_payload=self._validRankSuccessPayload(0, f_combo.name),
                f_ordinal=0,
            )

        # 4. Record terminal scheduler success observation on disk
        f_store.recordSchedulerObservation(
            f_point,
            "reconciler",
            1,
            f_payload={"state": "succeeded", "handle": f_handle.toDict()},
            f_ordinal=0,
        )

        # Reconcile BEFORE whole_run_succeeded marker
        f_view_before = StateReconciler.reconcile(f_plan, f_store)
        self.assertEqual(f_view_before.point_states[0].state, PointRunState.SUCCEEDED)
        self.assertFalse(f_view_before.has_success_marker)
        self.assertFalse(f_view_before.is_success)
        self.assertEqual(f_view_before.state, OverallRunState.IN_PROGRESS)

        # 5. Record whole_run_succeeded marker in control stream
        f_store.recordWholeRunSucceeded(
            "client", 1, f_payload={"summary": "all passed"}
        )

        # Reconcile AFTER whole_run_succeeded marker
        f_view_after = StateReconciler.reconcile(f_plan, f_store)
        self.assertEqual(f_view_after.point_states[0].state, PointRunState.SUCCEEDED)
        self.assertTrue(f_view_after.has_success_marker)
        self.assertTrue(f_view_after.is_success)
        self.assertTrue(f_view_after.is_terminal)
        self.assertEqual(f_view_after.state, OverallRunState.SUCCEEDED)

    def testExactLsmioRanks(self) -> None:
        """Rule 1: Asserts rank evidence completeness for all planned tasks in LSMIO setups."""
        f_run_id = "run-state-002"
        f_plan, f_art_store, f_store = self._setupRunEnvironment(
            f_run_id, f_target="lsmio", f_scale="bake", f_setup="NATIVE"
        )
        # Point 2 has tasks=4
        f_point_4 = f_plan.scale_points[2]
        self.assertEqual(f_point_4.tasks, 4)
        f_handle = JobHandle("slurm", "1002")

        f_store.recordSubmissionRequested(f_point_4, "client", f_ordinal=2)
        f_store.recordSubmissionDispatched(f_point_4, "client", f_ordinal=2)
        f_store.recordSubmissionRecorded(
            f_point_4, "client", f_handle=f_handle, f_ordinal=2
        )
        f_store.recordWorkerEvent(
            f_point_4, 1, EvidenceKind.CONTROLLER_STARTED, f_ordinal=2
        )

        # Record controller results for all 6 combinations, but only ranks 0, 1, 2 (missing rank 3)
        for f_combo in f_plan.combinations:
            f_store.recordControllerResult(
                f_point_4,
                f_combo,
                f_payload=self._validControllerSuccessPayload(f_combo.name, f_tasks=4),
                f_ordinal=2,
            )
            for f_r in range(3):  # 0, 1, 2 only
                f_store.recordRankResult(
                    f_point_4,
                    f_global_rank=f_r,
                    f_combination=f_combo,
                    f_payload=self._validRankSuccessPayload(f_r, f_combo.name),
                    f_ordinal=2,
                )

        f_store.recordSchedulerObservation(
            f_point_4, "reconciler", 1, f_payload={"state": "succeeded"}, f_ordinal=2
        )

        # Missing rank 3 after scheduler completion -> Point and Overall FAILED
        f_view_incomplete = StateReconciler.reconcile(f_plan, f_store)
        self.assertEqual(f_view_incomplete.point_states[2].state, PointRunState.FAILED)
        self.assertEqual(f_view_incomplete.state, OverallRunState.FAILED)

        # Now complete rank 3 for all combinations
        for f_combo in f_plan.combinations:
            f_store.recordRankResult(
                f_point_4,
                f_global_rank=3,
                f_combination=f_combo,
                f_payload=self._validRankSuccessPayload(3, f_combo.name),
                f_ordinal=2,
            )

        f_view_complete = StateReconciler.reconcile(f_plan, f_store)
        self.assertEqual(f_view_complete.point_states[2].state, PointRunState.SUCCEEDED)

    def testSpecificFailureAndMissingEvidence(self) -> None:
        """Rule 2: Specific failure outranks scheduler success; missing evidence after terminal is incomplete."""
        f_run_id = "run-state-003"
        f_plan, f_art_store, f_store = self._setupRunEnvironment(
            f_run_id, f_target="lsmio", f_scale="local", f_setup="NATIVE"
        )
        f_point = f_plan.scale_points[0]
        f_handle = JobHandle("slurm", "1003")

        f_store.recordSubmissionRecorded(
            f_point, "client", f_handle=f_handle, f_ordinal=0
        )

        # Case A: Controller result succeeded, but rank 0 failed with exit_code 1
        f_combo0 = f_plan.combinations[0]
        f_store.recordControllerResult(
            f_point,
            f_combo0,
            f_payload=self._validControllerSuccessPayload(f_combo0.name, f_tasks=1),
            f_ordinal=0,
        )
        f_store.recordRankResult(
            f_point,
            f_global_rank=0,
            f_combination=f_combo0,
            f_payload={
                "exit_code": 1,
                "status": "failed",
                "global_rank": 0,
                "rank": 0,
                "combination": f_combo0.name,
            },
            f_ordinal=0,
        )
        f_store.recordSchedulerObservation(
            f_point, "reconciler", 1, f_payload={"state": "succeeded"}, f_ordinal=0
        )

        f_view_fail = StateReconciler.reconcile(f_plan, f_store)
        self.assertEqual(f_view_fail.point_states[0].state, PointRunState.FAILED)
        self.assertEqual(f_view_fail.state, OverallRunState.FAILED)

        # Case B: Scheduler state is TIMEOUT
        f_view_timeout = StateReconciler.reconcile(
            f_plan, f_store, f_scheduler_observations={0: SchedulerJobState.TIMEOUT}
        )
        self.assertEqual(f_view_timeout.point_states[0].state, PointRunState.TIMED_OUT)
        self.assertEqual(f_view_timeout.state, OverallRunState.TIMED_OUT)

    def testConfirmedCancellationAndPriorFailure(self) -> None:
        """Rule 3: Confirmed cancellation applies unless an earlier independent failure exists."""
        f_run_id = "run-state-004"
        f_plan, f_art_store, f_store = self._setupRunEnvironment(
            f_run_id, f_target="lsmio", f_scale="local", f_setup="NATIVE"
        )
        f_point = f_plan.scale_points[0]
        f_handle = JobHandle("slurm", "1004")

        # Scenario A: Clean Cancellation without prior failure
        f_store.recordSubmissionRecorded(
            f_point, "client", f_handle=f_handle, f_ordinal=0
        )
        f_store.recordCancelRequested(f_point, "client", f_handle=f_handle, f_ordinal=0)
        f_store.recordCancelRecorded(f_point, "client", f_handle=f_handle, f_ordinal=0)

        f_view_clean_cancel = StateReconciler.reconcile(f_plan, f_store)
        self.assertEqual(
            f_view_clean_cancel.point_states[0].state, PointRunState.CANCELLED
        )
        self.assertEqual(f_view_clean_cancel.state, OverallRunState.CANCELLED)

        # Scenario B: Prior Failure precedes Cancel Request
        f_run_id_b = "run-state-004b"
        f_plan_b, f_art_store_b, f_store_b = self._setupRunEnvironment(
            f_run_id_b, f_target="lsmio", f_scale="local", f_setup="NATIVE"
        )
        f_point_b = f_plan_b.scale_points[0]

        f_store_b.recordSubmissionRecorded(
            f_point_b, "client", f_handle=f_handle, f_ordinal=0
        )
        # Record failure at T=10:00:00Z
        f_store_b.recordRankResult(
            f_point_b,
            f_global_rank=0,
            f_combination=f_plan_b.combinations[0],
            f_payload={"exit_code": 2, "status": "failed"},
            f_created_at_utc="2026-08-20T10:00:00Z",
            f_ordinal=0,
        )
        # Record cancel request at T=10:05:00Z
        f_store_b.recordCancelRequested(
            f_point_b,
            "client",
            f_handle=f_handle,
            f_created_at_utc="2026-08-20T10:05:00Z",
            f_ordinal=0,
        )
        # Record cancel confirmation at T=10:06:00Z
        f_store_b.recordCancelRecorded(
            f_point_b,
            "client",
            f_handle=f_handle,
            f_created_at_utc="2026-08-20T10:06:00Z",
            f_ordinal=0,
        )

        f_view_prior_fail = StateReconciler.reconcile(f_plan_b, f_store_b)
        self.assertEqual(f_view_prior_fail.point_states[0].state, PointRunState.FAILED)
        self.assertEqual(f_view_prior_fail.state, OverallRunState.FAILED)

    def testAmbiguousCausality(self) -> None:
        """Rule 5: Unconfirmed cancellation, corrupt evidence, or ambiguous causality resolves to INDETERMINATE."""
        f_run_id = "run-state-005"
        f_plan, f_art_store, f_store = self._setupRunEnvironment(
            f_run_id, f_target="lsmio", f_scale="local", f_setup="NATIVE"
        )
        f_point = f_plan.scale_points[0]
        f_handle = JobHandle("slurm", "1005")

        f_store.recordSubmissionRecorded(
            f_point, "client", f_handle=f_handle, f_ordinal=0
        )
        f_store.recordCancelRequested(f_point, "client", f_handle=f_handle, f_ordinal=0)

        # Record cancel_unconfirmed
        f_unconf_path = os.path.join(
            f_store.layout.pointSchedulerDir(f_point, 0), "cancel_unconfirmed.json"
        )
        f_unconf_rec = EvidenceRecord(
            f_writer_kind=WriterKind.CONTROL,
            f_writer_id="client",
            f_sequence_number=2,
            f_evidence_kind=EvidenceKind.CANCEL_UNCONFIRMED,
            f_point_id=f_store.layout.pointDirName(f_point, 0),
        )
        f_store.recordRecord(f_unconf_path, f_unconf_rec)

        f_view_indet = StateReconciler.reconcile(f_plan, f_store)
        self.assertEqual(
            f_view_indet.point_states[0].state, PointRunState.INDETERMINATE
        )
        self.assertEqual(f_view_indet.state, OverallRunState.INDETERMINATE)

        # Corrupt evidence file
        f_corrupt_path = f_store.layout.pointControllerResultPath(
            f_point, f_plan.combinations[0], 0
        )
        with open(f_corrupt_path, "w") as f_f:
            f_f.write("{invalid_json: true")

        f_view_corrupt = StateReconciler.reconcile(f_plan, f_store)
        self.assertEqual(
            f_view_corrupt.point_states[0].state, PointRunState.INDETERMINATE
        )
        self.assertEqual(f_view_corrupt.state, OverallRunState.INDETERMINATE)

    def testInterruptionThenFinalSuccess(self) -> None:
        """Rule 4: Interruption before marker permanently yields INTERRUPTED even if points subsequently succeed."""
        f_run_id = "run-state-006"
        f_plan, f_art_store, f_store = self._setupRunEnvironment(
            f_run_id, f_target="lsmio", f_scale="local", f_setup="NATIVE"
        )
        f_point = f_plan.scale_points[0]
        f_handle = JobHandle("slurm", "1006")

        # 1. Record interruption event first (sequence 1)
        f_store.recordInterruption("client", 1, f_payload={"reason": "SIGINT signal"})

        # 2. Point 0 subsequently completes with full success evidence
        f_store.recordSubmissionRecorded(
            f_point, "client", f_handle=f_handle, f_ordinal=0
        )
        f_store.recordWorkerEvent(
            f_point, 1, EvidenceKind.CONTROLLER_STARTED, f_ordinal=0
        )
        for f_combo in f_plan.combinations:
            f_store.recordControllerResult(
                f_point,
                f_combo,
                f_payload=self._validControllerSuccessPayload(f_combo.name, f_tasks=1),
                f_ordinal=0,
            )
            f_store.recordRankResult(
                f_point,
                f_global_rank=0,
                f_combination=f_combo,
                f_payload=self._validRankSuccessPayload(0, f_combo.name),
                f_ordinal=0,
            )
        f_store.recordSchedulerObservation(
            f_point, "reconciler", 1, f_payload={"state": "succeeded"}, f_ordinal=0
        )

        f_view = StateReconciler.reconcile(f_plan, f_store)
        # Point itself is successfully evidenced
        self.assertEqual(f_view.point_states[0].state, PointRunState.SUCCEEDED)
        # But overall run state permanently remains INTERRUPTED
        self.assertTrue(f_view.has_interruption)
        self.assertFalse(f_view.has_success_marker)
        self.assertEqual(f_view.state, OverallRunState.INTERRUPTED)

    def testMarkerThenInterruption(self) -> None:
        """Rule 4: Success marker recorded before interruption retains overall SUCCEEDED."""
        f_run_id = "run-state-007"
        f_plan, f_art_store, f_store = self._setupRunEnvironment(
            f_run_id, f_target="lsmio", f_scale="local", f_setup="NATIVE"
        )
        f_point = f_plan.scale_points[0]
        f_handle = JobHandle("slurm", "1007")

        # 1. Point 0 completes successfully
        f_store.recordSubmissionRecorded(
            f_point, "client", f_handle=f_handle, f_ordinal=0
        )
        for f_combo in f_plan.combinations:
            f_store.recordControllerResult(
                f_point,
                f_combo,
                f_payload=self._validControllerSuccessPayload(f_combo.name, f_tasks=1),
                f_ordinal=0,
            )
            f_store.recordRankResult(
                f_point,
                f_global_rank=0,
                f_combination=f_combo,
                f_payload=self._validRankSuccessPayload(0, f_combo.name),
                f_ordinal=0,
            )
        f_store.recordSchedulerObservation(
            f_point, "reconciler", 1, f_payload={"state": "succeeded"}, f_ordinal=0
        )

        # 2. Whole run succeeded recorded at sequence 1
        f_store.recordWholeRunSucceeded("client", 1, f_payload={"summary": "all done"})

        # 3. Late interruption event recorded at sequence 2
        f_store.recordInterruption(
            "client", 2, f_payload={"reason": "late signal after completion"}
        )

        f_view = StateReconciler.reconcile(f_plan, f_store)
        self.assertTrue(f_view.has_success_marker)
        self.assertTrue(f_view.has_interruption)
        self.assertEqual(f_view.point_states[0].state, PointRunState.SUCCEEDED)
        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)

    def testConflictingHandleUnknown(self) -> None:
        """Rule 5: Conflicting job handles or UNKNOWN scheduler terminal accounting yield INDETERMINATE."""
        f_run_id = "run-state-008"
        f_plan, f_art_store, f_store = self._setupRunEnvironment(
            f_run_id, f_target="lsmio", f_scale="local", f_setup="NATIVE"
        )
        f_point = f_plan.scale_points[0]
        f_handle = JobHandle("slurm", "1008")

        f_store.recordSubmissionRecorded(
            f_point, "client", f_handle=f_handle, f_ordinal=0
        )

        # Case A: Fresh observation provides conflicting job handle
        f_conflicting_handle = JobHandle("slurm", "9999")
        f_view_conflict = StateReconciler.reconcile(
            f_plan,
            f_store,
            f_scheduler_observations={
                0: {"state": "active", "handle": f_conflicting_handle}
            },
        )
        self.assertEqual(
            f_view_conflict.point_states[0].state, PointRunState.INDETERMINATE
        )
        self.assertEqual(f_view_conflict.state, OverallRunState.INDETERMINATE)

        # Case B: Scheduler observation UNKNOWN
        f_view_unknown = StateReconciler.reconcile(
            f_plan, f_store, f_scheduler_observations={0: SchedulerJobState.UNKNOWN}
        )
        self.assertEqual(
            f_view_unknown.point_states[0].state, PointRunState.INDETERMINATE
        )
        self.assertEqual(f_view_unknown.state, OverallRunState.INDETERMINATE)

    def testStaleActiveCannotRegress(self) -> None:
        """Rule 6: Stale active observations cannot regress an established terminal fact."""
        f_run_id = "run-state-009"
        f_plan, f_art_store, f_store = self._setupRunEnvironment(
            f_run_id, f_target="lsmio", f_scale="local", f_setup="NATIVE"
        )
        f_point = f_plan.scale_points[0]
        f_handle = JobHandle("slurm", "1009")

        # Point has established terminal SUCCEEDED on disk
        f_store.recordSubmissionRecorded(
            f_point, "client", f_handle=f_handle, f_ordinal=0
        )
        for f_combo in f_plan.combinations:
            f_store.recordControllerResult(
                f_point,
                f_combo,
                f_payload=self._validControllerSuccessPayload(f_combo.name, f_tasks=1),
                f_ordinal=0,
            )
            f_store.recordRankResult(
                f_point,
                f_global_rank=0,
                f_combination=f_combo,
                f_payload=self._validRankSuccessPayload(0, f_combo.name),
                f_ordinal=0,
            )
        f_store.recordSchedulerObservation(
            f_point, "reconciler", 1, f_payload={"state": "succeeded"}, f_ordinal=0
        )

        # Pass stale fresh observation saying QUEUED or ACTIVE
        f_view_stale_active = StateReconciler.reconcile(
            f_plan, f_store, f_scheduler_observations={0: SchedulerJobState.ACTIVE}
        )
        self.assertEqual(
            f_view_stale_active.point_states[0].state, PointRunState.SUCCEEDED
        )

        f_view_stale_queued = StateReconciler.reconcile(
            f_plan, f_store, f_scheduler_observations={0: "queued"}
        )
        self.assertEqual(
            f_view_stale_queued.point_states[0].state, PointRunState.SUCCEEDED
        )

    def testPermutationDeterminism(self) -> None:
        """Determinism: Reconciliation result is invariant under permutation of evidence reading."""
        f_run_id = "run-state-010"
        f_plan, f_art_store, f_store = self._setupRunEnvironment(
            f_run_id, f_target="lsmio", f_scale="bake", f_setup="NATIVE"
        )
        f_point0 = f_plan.scale_points[0]
        f_handle0 = JobHandle("slurm", "1010")

        f_store.recordSubmissionRecorded(
            f_point0, "client", f_handle=f_handle0, f_ordinal=0
        )
        for f_combo in f_plan.combinations:
            f_store.recordControllerResult(
                f_point0,
                f_combo,
                f_payload=self._validControllerSuccessPayload(f_combo.name, f_tasks=1),
                f_ordinal=0,
            )
            f_store.recordRankResult(
                f_point0,
                f_global_rank=0,
                f_combination=f_combo,
                f_payload=self._validRankSuccessPayload(0, f_combo.name),
                f_ordinal=0,
            )
        f_store.recordSchedulerObservation(
            f_point0, "reconciler", 1, f_payload={"state": "succeeded"}, f_ordinal=0
        )

        f_view1 = StateReconciler.reconcile(f_plan, f_store)
        f_view2 = StateReconciler.reconcile(f_plan, f_store)
        self.assertEqual(f_view1, f_view2)
        self.assertEqual(f_view1.toDict(), f_view2.toDict())

    def testIorSharedSuccessWithoutRankResults(self) -> None:
        """IOR benchmark uses shared MPI launch contract and requires no rank results."""
        f_run_id = "run-state-011"
        f_plan, f_art_store, f_store = self._setupRunEnvironment(
            f_run_id, f_target="ior", f_scale="local", f_setup="BASE"
        )
        f_point = f_plan.scale_points[0]
        f_handle = JobHandle("slurm", "1011")

        f_store.recordSubmissionRecorded(
            f_point, "client", f_handle=f_handle, f_ordinal=0
        )
        for f_combo in f_plan.combinations:
            f_store.recordControllerResult(
                f_point,
                f_combo,
                f_payload=self._validControllerSuccessPayload(
                    f_combo.name, f_tasks=None
                ),
                f_ordinal=0,
            )

        f_store.recordSchedulerObservation(
            f_point, "reconciler", 1, f_payload={"state": "succeeded"}, f_ordinal=0
        )
        f_store.recordWholeRunSucceeded("client", 1)

        f_view = StateReconciler.reconcile(f_plan, f_store)
        self.assertEqual(f_view.point_states[0].state, PointRunState.SUCCEEDED)
        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)

    def testMultiPointInProgressLifecycle(self) -> None:
        """Tests multi-point sequential execution lifecycle and active point tracking."""
        f_run_id = "run-state-012"
        f_plan, f_art_store, f_store = self._setupRunEnvironment(
            f_run_id, f_target="lsmio", f_scale="bake", f_setup="NATIVE"
        )
        # Point 0: SUCCEEDED
        f_p0 = f_plan.scale_points[0]
        f_h0 = JobHandle("slurm", "2000")
        f_store.recordSubmissionRecorded(f_p0, "client", f_handle=f_h0, f_ordinal=0)
        for f_combo in f_plan.combinations:
            f_store.recordControllerResult(
                f_p0,
                f_combo,
                f_payload=self._validControllerSuccessPayload(f_combo.name, f_tasks=1),
                f_ordinal=0,
            )
            f_store.recordRankResult(
                f_p0,
                f_global_rank=0,
                f_combination=f_combo,
                f_payload=self._validRankSuccessPayload(0, f_combo.name),
                f_ordinal=0,
            )
        f_store.recordSchedulerObservation(
            f_p0, "reconciler", 1, f_payload={"state": "succeeded"}, f_ordinal=0
        )

        # Point 1: RUNNING (submitted + active observation)
        f_p1 = f_plan.scale_points[1]
        f_h1 = JobHandle("slurm", "2001")
        f_store.recordSubmissionRecorded(f_p1, "client", f_handle=f_h1, f_ordinal=1)
        f_store.recordWorkerEvent(f_p1, 1, EvidenceKind.CONTROLLER_STARTED, f_ordinal=1)

        # Points 2 and 3: NOT_STARTED

        f_view = StateReconciler.reconcile(
            f_plan, f_store, f_scheduler_observations={1: SchedulerJobState.ACTIVE}
        )
        self.assertEqual(f_view.point_states[0].state, PointRunState.SUCCEEDED)
        self.assertEqual(f_view.point_states[1].state, PointRunState.RUNNING)
        self.assertEqual(f_view.point_states[2].state, PointRunState.NOT_STARTED)
        self.assertEqual(f_view.point_states[3].state, PointRunState.NOT_STARTED)
        self.assertEqual(f_view.state, OverallRunState.IN_PROGRESS)
        self.assertEqual(f_view.active_point_ordinal, 1)

    def testEmptyElapsedOnlyStatusOnlyExitOnlyNeverSucceeds(self) -> None:
        """Chunk 017: Empty, elapsed-only, status-only, and exit-only payloads are rejected as INDETERMINATE."""
        f_bad_payloads = [
            {},
            {"elapsed_seconds": 10.5},
            {"status": "success"},
            {"exit_code": 0},
            {"returncode": 0},
        ]
        for f_idx, f_bad in enumerate(f_bad_payloads):
            f_run_id = f"run-state-bad-{f_idx}"
            f_plan, f_art_store, f_store = self._setupRunEnvironment(
                f_run_id, f_target="ior", f_scale="local", f_setup="BASE"
            )
            f_point = f_plan.scale_points[0]
            f_store.recordSubmissionRecorded(
                f_point, "client", f_handle=JobHandle("slurm", "5000"), f_ordinal=0
            )
            # Record incomplete/corrupt controller result
            for f_combo in f_plan.combinations:
                f_store.recordControllerResult(
                    f_point, f_combo, f_payload=f_bad, f_ordinal=0
                )
            f_store.recordSchedulerObservation(
                f_point, "reconciler", 1, f_payload={"state": "succeeded"}, f_ordinal=0
            )

            f_view = StateReconciler.reconcile(f_plan, f_store)
            self.assertEqual(
                f_view.point_states[0].state,
                PointRunState.INDETERMINATE,
                f"Payload {f_bad!r} should resolve to INDETERMINATE, got {f_view.point_states[0].state}",
            )

    def testMalformedBoolStringMismatchAndPathIdentityIndeterminate(self) -> None:
        """Chunk 017: Bool exit code, numeric string exit code, rank/combination mismatch resolve to INDETERMINATE."""
        # 1. Boolean exit_code
        f_run_id1 = "run-state-malformed-bool"
        f_plan1, _, f_store1 = self._setupRunEnvironment(
            f_run_id1, f_target="ior", f_scale="local", f_setup="BASE"
        )
        f_point1 = f_plan1.scale_points[0]
        f_store1.recordSubmissionRecorded(
            f_point1, "client", f_handle=JobHandle("slurm", "5001"), f_ordinal=0
        )
        for f_combo in f_plan1.combinations:
            f_store1.recordControllerResult(
                f_point1,
                f_combo,
                f_payload={
                    "status": "success",
                    "exit_code": True,
                    "stage": "execution",
                },
                f_ordinal=0,
            )
        f_store1.recordSchedulerObservation(
            f_point1, "reconciler", 1, f_payload={"state": "succeeded"}, f_ordinal=0
        )
        f_view1 = StateReconciler.reconcile(f_plan1, f_store1)
        self.assertEqual(f_view1.point_states[0].state, PointRunState.INDETERMINATE)

        # 2. String exit_code
        f_run_id2 = "run-state-malformed-str"
        f_plan2, _, f_store2 = self._setupRunEnvironment(
            f_run_id2, f_target="ior", f_scale="local", f_setup="BASE"
        )
        f_point2 = f_plan2.scale_points[0]
        f_store2.recordSubmissionRecorded(
            f_point2, "client", f_handle=JobHandle("slurm", "5002"), f_ordinal=0
        )
        for f_combo in f_plan2.combinations:
            f_store2.recordControllerResult(
                f_point2,
                f_combo,
                f_payload={"status": "success", "exit_code": "0", "stage": "execution"},
                f_ordinal=0,
            )
        f_store2.recordSchedulerObservation(
            f_point2, "reconciler", 1, f_payload={"state": "succeeded"}, f_ordinal=0
        )
        f_view2 = StateReconciler.reconcile(f_plan2, f_store2)
        self.assertEqual(f_view2.point_states[0].state, PointRunState.INDETERMINATE)

        # 3. LSMIO Rank Identity Mismatch (rank 1 payload recorded for rank 0)
        f_run_id3 = "run-state-rank-mismatch"
        f_plan3, _, f_store3 = self._setupRunEnvironment(
            f_run_id3, f_target="lsmio", f_scale="local", f_setup="NATIVE"
        )
        f_point3 = f_plan3.scale_points[0]
        f_store3.recordSubmissionRecorded(
            f_point3, "client", f_handle=JobHandle("slurm", "5003"), f_ordinal=0
        )
        for f_combo in f_plan3.combinations:
            f_store3.recordControllerResult(
                f_point3,
                f_combo,
                f_payload=self._validControllerSuccessPayload(f_combo.name, f_tasks=1),
                f_ordinal=0,
            )
            # Rank mismatch: expected rank 0, payload has rank 1
            f_store3.recordRankResult(
                f_point3,
                f_global_rank=0,
                f_combination=f_combo,
                f_payload=self._validRankSuccessPayload(1, f_combo.name),
                f_ordinal=0,
            )
        f_store3.recordSchedulerObservation(
            f_point3, "reconciler", 1, f_payload={"state": "succeeded"}, f_ordinal=0
        )
        f_view3 = StateReconciler.reconcile(f_plan3, f_store3)
        self.assertEqual(f_view3.point_states[0].state, PointRunState.INDETERMINATE)

    def testDurableFailedThenFreshSucceededRemainsFailure(self) -> None:
        """Chunk 018: Durable FAILED on disk cannot be overwritten by fresh SUCCEEDED observation."""
        f_run_id = "run-state-f11-001"
        f_plan, _, f_store = self._setupRunEnvironment(
            f_run_id, f_target="ior", f_scale="local", f_setup="BASE"
        )
        f_point = f_plan.scale_points[0]
        f_handle = JobHandle("slurm", "6001")

        f_store.recordSubmissionRecorded(
            f_point, "client", f_handle=f_handle, f_ordinal=0
        )
        # Durable disk observation: FAILED
        f_store.recordSchedulerObservation(
            f_point,
            "reconciler",
            1,
            f_payload={"state": "failed", "handle": f_handle.toDict()},
            f_ordinal=0,
        )

        # Fresh observation: SUCCEEDED
        f_view = StateReconciler.reconcile(
            f_plan, f_store, f_scheduler_observations={0: SchedulerJobState.SUCCEEDED}
        )
        self.assertEqual(f_view.point_states[0].state, PointRunState.FAILED)
        self.assertEqual(f_view.state, OverallRunState.FAILED)

        # Also test controller failure with fresh scheduler SUCCEEDED
        f_run_id2 = "run-state-f11-001b"
        f_plan2, _, f_store2 = self._setupRunEnvironment(
            f_run_id2, f_target="ior", f_scale="local", f_setup="BASE"
        )
        f_point2 = f_plan2.scale_points[0]
        f_store2.recordSubmissionRecorded(
            f_point2, "client", f_handle=f_handle, f_ordinal=0
        )
        for f_combo in f_plan2.combinations:
            f_store2.recordControllerResult(
                f_point2,
                f_combo,
                f_payload={
                    "status": "failed",
                    "exit_code": 1,
                    "stage": "execution",
                    "combination": f_combo.name,
                },
                f_ordinal=0,
            )
        f_view2 = StateReconciler.reconcile(
            f_plan2, f_store2, f_scheduler_observations={0: SchedulerJobState.SUCCEEDED}
        )
        self.assertEqual(f_view2.point_states[0].state, PointRunState.FAILED)
        self.assertEqual(f_view2.state, OverallRunState.FAILED)

    def testDurableSuccessThenFreshFailureIsFailure(self) -> None:
        """Chunk 018: Durable SUCCEEDED on disk is outranked by fresh FAILED observation."""
        f_run_id = "run-state-f11-002"
        f_plan, _, f_store = self._setupRunEnvironment(
            f_run_id, f_target="ior", f_scale="local", f_setup="BASE"
        )
        f_point = f_plan.scale_points[0]
        f_handle = JobHandle("slurm", "6002")

        f_store.recordSubmissionRecorded(
            f_point, "client", f_handle=f_handle, f_ordinal=0
        )
        for f_combo in f_plan.combinations:
            f_store.recordControllerResult(
                f_point,
                f_combo,
                f_payload=self._validControllerSuccessPayload(f_combo.name),
                f_ordinal=0,
            )
        # Durable disk observation: SUCCEEDED
        f_store.recordSchedulerObservation(
            f_point,
            "reconciler",
            1,
            f_payload={"state": "succeeded", "handle": f_handle.toDict()},
            f_ordinal=0,
        )

        # Fresh observation: FAILED
        f_view = StateReconciler.reconcile(
            f_plan, f_store, f_scheduler_observations={0: SchedulerJobState.FAILED}
        )
        self.assertEqual(f_view.point_states[0].state, PointRunState.FAILED)
        self.assertEqual(f_view.state, OverallRunState.FAILED)

    def testEveryTerminalPairConflictTable(self) -> None:
        """Chunk 018: Comprehensive validation of the 4x4 terminal-pair precedence and conflict resolution matrix."""
        f_terminal_states = [
            SchedulerJobState.SUCCEEDED,
            SchedulerJobState.FAILED,
            SchedulerJobState.TIMEOUT,
            SchedulerJobState.CANCELLED,
        ]

        # Case A: Without user cancellation request
        f_expected_no_cancel = {
            (
                SchedulerJobState.SUCCEEDED,
                SchedulerJobState.SUCCEEDED,
            ): PointRunState.SUCCEEDED,
            (
                SchedulerJobState.SUCCEEDED,
                SchedulerJobState.FAILED,
            ): PointRunState.FAILED,
            (
                SchedulerJobState.SUCCEEDED,
                SchedulerJobState.TIMEOUT,
            ): PointRunState.TIMED_OUT,
            (
                SchedulerJobState.SUCCEEDED,
                SchedulerJobState.CANCELLED,
            ): PointRunState.INDETERMINATE,
            (
                SchedulerJobState.FAILED,
                SchedulerJobState.SUCCEEDED,
            ): PointRunState.FAILED,
            (SchedulerJobState.FAILED, SchedulerJobState.FAILED): PointRunState.FAILED,
            (
                SchedulerJobState.FAILED,
                SchedulerJobState.TIMEOUT,
            ): PointRunState.INDETERMINATE,
            (
                SchedulerJobState.FAILED,
                SchedulerJobState.CANCELLED,
            ): PointRunState.INDETERMINATE,
            (
                SchedulerJobState.TIMEOUT,
                SchedulerJobState.SUCCEEDED,
            ): PointRunState.TIMED_OUT,
            (
                SchedulerJobState.TIMEOUT,
                SchedulerJobState.FAILED,
            ): PointRunState.INDETERMINATE,
            (
                SchedulerJobState.TIMEOUT,
                SchedulerJobState.TIMEOUT,
            ): PointRunState.TIMED_OUT,
            (
                SchedulerJobState.TIMEOUT,
                SchedulerJobState.CANCELLED,
            ): PointRunState.INDETERMINATE,
            (
                SchedulerJobState.CANCELLED,
                SchedulerJobState.SUCCEEDED,
            ): PointRunState.INDETERMINATE,
            (
                SchedulerJobState.CANCELLED,
                SchedulerJobState.FAILED,
            ): PointRunState.INDETERMINATE,
            (
                SchedulerJobState.CANCELLED,
                SchedulerJobState.TIMEOUT,
            ): PointRunState.INDETERMINATE,
            (
                SchedulerJobState.CANCELLED,
                SchedulerJobState.CANCELLED,
            ): PointRunState.INDETERMINATE,
        }

        for (f_s1, f_s2), f_exp_state in f_expected_no_cancel.items():
            f_run_id = f"run-pair-{f_s1.value}-{f_s2.value}"
            f_plan, _, f_store = self._setupRunEnvironment(
                f_run_id, f_target="ior", f_scale="local", f_setup="BASE"
            )
            f_point = f_plan.scale_points[0]
            f_handle = JobHandle("slurm", "7001")
            f_store.recordSubmissionRecorded(
                f_point, "client", f_handle=f_handle, f_ordinal=0
            )

            # Record full controller success results so missing evidence does not mask scheduler resolution
            for f_combo in f_plan.combinations:
                f_store.recordControllerResult(
                    f_point,
                    f_combo,
                    f_payload=self._validControllerSuccessPayload(f_combo.name),
                    f_ordinal=0,
                )

            # Record first state on disk
            f_store.recordSchedulerObservation(
                f_point,
                "obs1",
                1,
                f_payload={"state": f_s1.value, "handle": f_handle.toDict()},
                f_ordinal=0,
            )
            # Record second state on disk
            f_store.recordSchedulerObservation(
                f_point,
                "obs2",
                1,
                f_payload={"state": f_s2.value, "handle": f_handle.toDict()},
                f_ordinal=0,
            )

            f_view = StateReconciler.reconcile(f_plan, f_store)
            self.assertEqual(
                f_view.point_states[0].state,
                f_exp_state,
                f"Pair ({f_s1.value}, {f_s2.value}) expected {f_exp_state}, got {f_view.point_states[0].state}",
            )

        # Case B: With confirmed user cancellation request (cancel requested at T=12:00:00Z)
        f_cancel_time = "2026-08-20T12:00:00Z"
        f_prior_time = "2026-08-20T11:00:00Z"
        f_post_time = "2026-08-20T13:00:00Z"

        # Prior failure outranks cancellation
        f_run_id_prior_f = "run-pair-prior-f-cancel"
        f_plan_pf, _, f_store_pf = self._setupRunEnvironment(
            f_run_id_prior_f, f_target="ior", f_scale="local", f_setup="BASE"
        )
        f_pt_pf = f_plan_pf.scale_points[0]
        f_h_pf = JobHandle("slurm", "7002")
        f_store_pf.recordSubmissionRecorded(
            f_pt_pf, "client", f_handle=f_h_pf, f_ordinal=0
        )
        f_store_pf.recordSchedulerObservation(
            f_pt_pf,
            "obs",
            1,
            f_payload={"state": "failed", "handle": f_h_pf.toDict()},
            f_created_at_utc=f_prior_time,
            f_ordinal=0,
        )
        f_store_pf.recordCancelRequested(
            f_pt_pf,
            "client",
            f_handle=f_h_pf,
            f_created_at_utc=f_cancel_time,
            f_ordinal=0,
        )
        f_store_pf.recordCancelRecorded(
            f_pt_pf,
            "client",
            f_handle=f_h_pf,
            f_created_at_utc=f_post_time,
            f_ordinal=0,
        )
        f_view_pf = StateReconciler.reconcile(f_plan_pf, f_store_pf)
        self.assertEqual(f_view_pf.point_states[0].state, PointRunState.FAILED)

        # Prior timeout outranks cancellation
        f_run_id_prior_t = "run-pair-prior-t-cancel"
        f_plan_pt, _, f_store_pt = self._setupRunEnvironment(
            f_run_id_prior_t, f_target="ior", f_scale="local", f_setup="BASE"
        )
        f_pt_pt = f_plan_pt.scale_points[0]
        f_h_pt = JobHandle("slurm", "7003")
        f_store_pt.recordSubmissionRecorded(
            f_pt_pt, "client", f_handle=f_h_pt, f_ordinal=0
        )
        f_store_pt.recordSchedulerObservation(
            f_pt_pt,
            "obs",
            1,
            f_payload={"state": "timeout", "handle": f_h_pt.toDict()},
            f_created_at_utc=f_prior_time,
            f_ordinal=0,
        )
        f_store_pt.recordCancelRequested(
            f_pt_pt,
            "client",
            f_handle=f_h_pt,
            f_created_at_utc=f_cancel_time,
            f_ordinal=0,
        )
        f_store_pt.recordCancelRecorded(
            f_pt_pt,
            "client",
            f_handle=f_h_pt,
            f_created_at_utc=f_post_time,
            f_ordinal=0,
        )
        f_view_pt = StateReconciler.reconcile(f_plan_pt, f_store_pt)
        self.assertEqual(f_view_pt.point_states[0].state, PointRunState.TIMED_OUT)

        # Cancellation before failure yields CANCELLED
        f_run_id_post_f = "run-pair-cancel-then-f"
        f_plan_post, _, f_store_post = self._setupRunEnvironment(
            f_run_id_post_f, f_target="ior", f_scale="local", f_setup="BASE"
        )
        f_pt_post = f_plan_post.scale_points[0]
        f_h_post = JobHandle("slurm", "7004")
        f_store_post.recordSubmissionRecorded(
            f_pt_post, "client", f_handle=f_h_post, f_ordinal=0
        )
        f_store_post.recordCancelRequested(
            f_pt_post,
            "client",
            f_handle=f_h_post,
            f_created_at_utc=f_cancel_time,
            f_ordinal=0,
        )
        f_store_post.recordSchedulerObservation(
            f_pt_post,
            "obs",
            1,
            f_payload={"state": "failed", "handle": f_h_post.toDict()},
            f_created_at_utc=f_post_time,
            f_ordinal=0,
        )
        f_store_post.recordCancelRecorded(
            f_pt_post,
            "client",
            f_handle=f_h_post,
            f_created_at_utc=f_post_time,
            f_ordinal=0,
        )
        f_view_post = StateReconciler.reconcile(f_plan_post, f_store_post)
        self.assertEqual(f_view_post.point_states[0].state, PointRunState.CANCELLED)

    def testStaleActiveQueuedNeverRegressTerminal(self) -> None:
        """Chunk 018: Stale active or queued observations cannot regress any established terminal fact."""
        f_terminals = [
            (SchedulerJobState.SUCCEEDED, PointRunState.SUCCEEDED),
            (SchedulerJobState.FAILED, PointRunState.FAILED),
            (SchedulerJobState.TIMEOUT, PointRunState.TIMED_OUT),
        ]
        for f_term_sched, f_exp_point in f_terminals:
            f_run_id = f"run-stale-{f_term_sched.value}"
            f_plan, _, f_store = self._setupRunEnvironment(
                f_run_id, f_target="ior", f_scale="local", f_setup="BASE"
            )
            f_point = f_plan.scale_points[0]
            f_handle = JobHandle("slurm", "8001")
            f_store.recordSubmissionRecorded(
                f_point, "client", f_handle=f_handle, f_ordinal=0
            )

            if f_term_sched == SchedulerJobState.SUCCEEDED:
                for f_combo in f_plan.combinations:
                    f_store.recordControllerResult(
                        f_point,
                        f_combo,
                        f_payload=self._validControllerSuccessPayload(f_combo.name),
                        f_ordinal=0,
                    )

            # Establish terminal state on disk
            f_store.recordSchedulerObservation(
                f_point,
                "obs",
                1,
                f_payload={"state": f_term_sched.value, "handle": f_handle.toDict()},
                f_ordinal=0,
            )

            # Stale fresh ACTIVE
            f_view_active = StateReconciler.reconcile(
                f_plan, f_store, f_scheduler_observations={0: SchedulerJobState.ACTIVE}
            )
            self.assertEqual(f_view_active.point_states[0].state, f_exp_point)

            # Stale fresh QUEUED
            f_view_queued = StateReconciler.reconcile(
                f_plan, f_store, f_scheduler_observations={0: "queued"}
            )
            self.assertEqual(f_view_queued.point_states[0].state, f_exp_point)

            # Stale fresh UNKNOWN (does not regress established terminal fact)
            f_view_unk = StateReconciler.reconcile(
                f_plan, f_store, f_scheduler_observations={0: SchedulerJobState.UNKNOWN}
            )
            self.assertEqual(f_view_unk.point_states[0].state, f_exp_point)

    def testCancellationRequiresCausality(self) -> None:
        """Chunk 018: Confirmed requested cancellation is applied only with its cancel evidence; causality is strictly validated."""
        f_handle = JobHandle("slurm", "9001")

        # 1. CANCELLED scheduler state without cancel_requested record -> INDETERMINATE
        f_run_id1 = "run-cancel-causality-1"
        f_plan1, _, f_store1 = self._setupRunEnvironment(
            f_run_id1, f_target="ior", f_scale="local", f_setup="BASE"
        )
        f_pt1 = f_plan1.scale_points[0]
        f_store1.recordSubmissionRecorded(
            f_pt1, "client", f_handle=f_handle, f_ordinal=0
        )
        f_store1.recordSchedulerObservation(
            f_pt1,
            "obs",
            1,
            f_payload={"state": "cancelled", "handle": f_handle.toDict()},
            f_ordinal=0,
        )
        f_view1 = StateReconciler.reconcile(f_plan1, f_store1)
        self.assertEqual(f_view1.point_states[0].state, PointRunState.INDETERMINATE)
        self.assertEqual(f_view1.state, OverallRunState.INDETERMINATE)

        # 2. cancel_requested recorded, but cancel_unconfirmed.json exists -> INDETERMINATE
        f_run_id2 = "run-cancel-causality-2"
        f_plan2, _, f_store2 = self._setupRunEnvironment(
            f_run_id2, f_target="ior", f_scale="local", f_setup="BASE"
        )
        f_pt2 = f_plan2.scale_points[0]
        f_store2.recordSubmissionRecorded(
            f_pt2, "client", f_handle=f_handle, f_ordinal=0
        )
        f_store2.recordCancelRequested(f_pt2, "client", f_handle=f_handle, f_ordinal=0)
        f_unconf_path = os.path.join(
            f_store2.layout.pointSchedulerDir(f_pt2, 0), "cancel_unconfirmed.json"
        )
        f_store2.recordRecord(
            f_unconf_path,
            EvidenceRecord(
                f_writer_kind=WriterKind.CONTROL,
                f_writer_id="client",
                f_sequence_number=2,
                f_evidence_kind=EvidenceKind.CANCEL_UNCONFIRMED,
                f_point_id=f_store2.layout.pointDirName(f_pt2, 0),
            ),
        )
        f_view2 = StateReconciler.reconcile(f_plan2, f_store2)
        self.assertEqual(f_view2.point_states[0].state, PointRunState.INDETERMINATE)

        # 3. cancel_requested recorded, but failure timestamp missing (e.g. missing evidence failure -> ambiguous causality) -> INDETERMINATE
        f_run_id3 = "run-cancel-causality-3"
        f_plan3, _, f_store3 = self._setupRunEnvironment(
            f_run_id3, f_target="ior", f_scale="local", f_setup="BASE"
        )
        f_pt3 = f_plan3.scale_points[0]
        f_store3.recordSubmissionRecorded(
            f_pt3, "client", f_handle=f_handle, f_ordinal=0
        )
        f_store3.recordCancelRequested(
            f_pt3,
            "client",
            f_handle=f_handle,
            f_created_at_utc="2026-08-20T12:00:00Z",
            f_ordinal=0,
        )
        f_store3.recordCancelRecorded(
            f_pt3,
            "client",
            f_handle=f_handle,
            f_created_at_utc="2026-08-20T12:05:00Z",
            f_ordinal=0,
        )
        # Scheduler completed with terminal SUCCEEDED, but controller results are missing -> failure without timestamp
        f_store3.recordSchedulerObservation(
            f_pt3,
            "obs",
            1,
            f_payload={"state": "succeeded", "handle": f_handle.toDict()},
            f_ordinal=0,
        )
        f_view3 = StateReconciler.reconcile(f_plan3, f_store3)
        self.assertEqual(f_view3.point_states[0].state, PointRunState.INDETERMINATE)

    def testPermutationAndRepeatedReconcileStable(self) -> None:
        """Chunk 018: State reconciliation is strictly deterministic and invariant under observation permutations and repetition."""
        f_run_id = "run-permutation-test"
        f_plan, _, f_store = self._setupRunEnvironment(
            f_run_id, f_target="ior", f_scale="bake", f_setup="BASE"
        )
        f_pt0 = f_plan.scale_points[0]
        f_h0 = JobHandle("slurm", "9010")

        f_store.recordSubmissionRecorded(f_pt0, "client", f_handle=f_h0, f_ordinal=0)
        for f_combo in f_plan.combinations:
            f_store.recordControllerResult(
                f_pt0,
                f_combo,
                f_payload=self._validControllerSuccessPayload(f_combo.name),
                f_ordinal=0,
            )

        # Write 5 duplicate identical observations across multiple writers
        for f_w_idx in range(5):
            f_store.recordSchedulerObservation(
                f_pt0,
                f"reconciler_{f_w_idx}",
                1,
                f_payload={"state": "succeeded", "handle": f_h0.toDict()},
                f_ordinal=0,
            )

        f_store.recordWholeRunSucceeded("client", 1)

        # Reconcile multiple times
        f_view_base = StateReconciler.reconcile(f_plan, f_store)
        for _ in range(5):
            f_view_repeat = StateReconciler.reconcile(f_plan, f_store)
            self.assertEqual(f_view_base, f_view_repeat)
            self.assertEqual(f_view_base.toDict(), f_view_repeat.toDict())

    def testEnumsAndViewsImmutability(self) -> None:
        """Tests enum helper properties and immutable view class properties and error paths."""
        self.assertTrue(SchedulerJobState.SUCCEEDED.isTerminal)
        self.assertTrue(SchedulerJobState.SUCCEEDED.isSuccess)
        self.assertFalse(SchedulerJobState.ACTIVE.isTerminal)
        self.assertFalse(SchedulerJobState.UNKNOWN.isTerminal)

        self.assertTrue(PointRunState.SUCCEEDED.isTerminal)
        self.assertTrue(PointRunState.SUCCEEDED.isSuccess)
        self.assertFalse(PointRunState.NOT_STARTED.isTerminal)
        self.assertFalse(PointRunState.RUNNING.isTerminal)

        self.assertTrue(OverallRunState.SUCCEEDED.isTerminal)
        self.assertTrue(OverallRunState.SUCCEEDED.isSuccess)
        self.assertFalse(OverallRunState.IN_PROGRESS.isTerminal)
        self.assertFalse(OverallRunState.NOT_STARTED.isTerminal)

        f_sp = ScalePoint(1, 1, 1)
        f_pv = PointStateView(
            f_point_id="0-tasks-1",
            f_ordinal=0,
            f_scale_point=f_sp,
            f_state=PointRunState.RUNNING,
        )
        with self.assertRaises(AttributeError):
            f_pv.state = PointRunState.SUCCEEDED  # type: ignore

        f_rv = RunStateView(
            f_run_id="run-view-test",
            f_state=OverallRunState.IN_PROGRESS,
            f_point_states=[f_pv],
        )
        with self.assertRaises(AttributeError):
            f_rv.state = OverallRunState.SUCCEEDED  # type: ignore

        self.assertIn("0-tasks-1", str(f_pv))
        self.assertIn("run-view-test", str(f_rv))

        with self.assertRaises(StateError):
            PointStateView("", 0, f_sp, PointRunState.RUNNING)
        with self.assertRaises(StateError):
            RunStateView("", OverallRunState.NOT_STARTED)


class StateEnumAndErrorContractTest(unittest.TestCase):
    """Unit tests for StateError hierarchy and state enum properties (ID 035)."""

    def testStateErrorHierarchy(self) -> None:
        """Tests that StateError subclasses Exception, retains messages, and is catchable."""
        self.assertTrue(issubclass(StateError, Exception))
        f_err = StateError("state reconciliation failed")
        self.assertIsInstance(f_err, Exception)
        self.assertEqual(str(f_err), "state reconciliation failed")
        try:
            raise f_err
        except StateError as f_caught:
            self.assertIs(f_caught, f_err)

    def testSchedulerJobStateEnumAndProperties(self) -> None:
        """Tests SchedulerJobState enum values, terminal statuses, and success properties."""
        f_expected_values = {
            SchedulerJobState.QUEUED: "queued",
            SchedulerJobState.ACTIVE: "active",
            SchedulerJobState.SUCCEEDED: "succeeded",
            SchedulerJobState.FAILED: "failed",
            SchedulerJobState.CANCELLED: "cancelled",
            SchedulerJobState.TIMEOUT: "timeout",
            SchedulerJobState.UNKNOWN: "unknown",
        }
        f_terminal_members = {
            SchedulerJobState.SUCCEEDED,
            SchedulerJobState.FAILED,
            SchedulerJobState.CANCELLED,
            SchedulerJobState.TIMEOUT,
        }
        for f_member, f_val in f_expected_values.items():
            with self.subTest(member=f_member.name):
                self.assertEqual(f_member.value, f_val)
                f_is_term = f_member in f_terminal_members
                self.assertEqual(f_member.isTerminal, f_is_term)
                self.assertEqual(f_member.is_terminal, f_is_term)
                f_is_succ = f_member is SchedulerJobState.SUCCEEDED
                self.assertEqual(f_member.isSuccess, f_is_succ)
                self.assertEqual(f_member.is_success, f_is_succ)

    def testPointRunStateEnumAndProperties(self) -> None:
        """Tests PointRunState enum values, terminal statuses, and success properties."""
        f_expected_values = {
            PointRunState.NOT_STARTED: "not_started",
            PointRunState.SUBMITTED: "submitted",
            PointRunState.RUNNING: "running",
            PointRunState.SUCCEEDED: "succeeded",
            PointRunState.FAILED: "failed",
            PointRunState.CANCELLED: "cancelled",
            PointRunState.TIMED_OUT: "timed_out",
            PointRunState.INTERRUPTED: "interrupted",
            PointRunState.INDETERMINATE: "indeterminate",
        }
        f_terminal_members = {
            PointRunState.SUCCEEDED,
            PointRunState.FAILED,
            PointRunState.CANCELLED,
            PointRunState.TIMED_OUT,
            PointRunState.INTERRUPTED,
            PointRunState.INDETERMINATE,
        }
        for f_member, f_val in f_expected_values.items():
            with self.subTest(member=f_member.name):
                self.assertEqual(f_member.value, f_val)
                f_is_term = f_member in f_terminal_members
                self.assertEqual(f_member.isTerminal, f_is_term)
                self.assertEqual(f_member.is_terminal, f_is_term)
                f_is_succ = f_member is PointRunState.SUCCEEDED
                self.assertEqual(f_member.isSuccess, f_is_succ)
                self.assertEqual(f_member.is_success, f_is_succ)

    def testOverallRunStateEnumAndProperties(self) -> None:
        """Tests OverallRunState enum values, terminal statuses, and success properties."""
        f_expected_values = {
            OverallRunState.NOT_STARTED: "not_started",
            OverallRunState.IN_PROGRESS: "in_progress",
            OverallRunState.SUCCEEDED: "succeeded",
            OverallRunState.FAILED: "failed",
            OverallRunState.CANCELLED: "cancelled",
            OverallRunState.TIMED_OUT: "timed_out",
            OverallRunState.INTERRUPTED: "interrupted",
            OverallRunState.INDETERMINATE: "indeterminate",
        }
        f_terminal_members = {
            OverallRunState.SUCCEEDED,
            OverallRunState.FAILED,
            OverallRunState.CANCELLED,
            OverallRunState.TIMED_OUT,
            OverallRunState.INTERRUPTED,
            OverallRunState.INDETERMINATE,
        }
        for f_member, f_val in f_expected_values.items():
            with self.subTest(member=f_member.name):
                self.assertEqual(f_member.value, f_val)
                f_is_term = f_member in f_terminal_members
                self.assertEqual(f_member.isTerminal, f_is_term)
                self.assertEqual(f_member.is_terminal, f_is_term)
                f_is_succ = f_member is OverallRunState.SUCCEEDED
                self.assertEqual(f_member.isSuccess, f_is_succ)
                self.assertEqual(f_member.is_success, f_is_succ)


class PointStateViewContractTest(unittest.TestCase):
    """Unit tests covering PointStateView argument validation, immutability, properties, serialization, and equality (ID 036)."""

    def testPointStateViewRejectsInvalidPointId(self) -> None:
        """Tests that PointStateView constructor rejects non-string or whitespace-only point_id."""
        f_sp = ScalePoint(1, 1, 1)
        for f_bad_id in (None, 123, "", "   ", "\t\n", []):
            with self.subTest(bad_id=f_bad_id):
                with self.assertRaises(StateError) as f_cm:
                    PointStateView(
                        f_point_id=f_bad_id,  # type: ignore
                        f_ordinal=0,
                        f_scale_point=f_sp,
                        f_state=PointRunState.NOT_STARTED,
                    )
                self.assertIn("point_id must be a non-empty string, got:", str(f_cm.exception))

    def testPointStateViewRejectsInvalidOrdinal(self) -> None:
        """Tests that PointStateView constructor rejects non-integer or negative ordinal."""
        f_sp = ScalePoint(1, 1, 1)
        for f_bad_ord in (None, "0", -1, -42, 1.5, []):
            with self.subTest(bad_ord=f_bad_ord):
                with self.assertRaises(StateError) as f_cm:
                    PointStateView(
                        f_point_id="pt-1",
                        f_ordinal=f_bad_ord,  # type: ignore
                        f_scale_point=f_sp,
                        f_state=PointRunState.NOT_STARTED,
                    )
                self.assertIn("ordinal must be a non-negative integer, got:", str(f_cm.exception))

    def testPointStateViewRejectsInvalidScalePoint(self) -> None:
        """Tests that PointStateView constructor rejects non-ScalePoint instances."""
        for f_bad_sp in (None, "not_scale_point", 123, object(), []):
            with self.subTest(bad_sp=f_bad_sp):
                with self.assertRaises(StateError) as f_cm:
                    PointStateView(
                        f_point_id="pt-1",
                        f_ordinal=0,
                        f_scale_point=f_bad_sp,  # type: ignore
                        f_state=PointRunState.NOT_STARTED,
                    )
                self.assertIn("scale_point must be ScalePoint, got:", str(f_cm.exception))

    def testPointStateViewRejectsInvalidState(self) -> None:
        """Tests that PointStateView constructor rejects non-PointRunState instances."""
        f_sp = ScalePoint(1, 1, 1)
        for f_bad_st in (None, "running", 123, SchedulerJobState.SUCCEEDED, OverallRunState.SUCCEEDED):
            with self.subTest(bad_st=f_bad_st):
                with self.assertRaises(StateError) as f_cm:
                    PointStateView(
                        f_point_id="pt-1",
                        f_ordinal=0,
                        f_scale_point=f_sp,
                        f_state=f_bad_st,  # type: ignore
                    )
                self.assertIn("state must be PointRunState, got:", str(f_cm.exception))

    def testPointStateViewRejectsInvalidHandle(self) -> None:
        """Tests that PointStateView constructor rejects non-JobHandle when handle is provided."""
        f_sp = ScalePoint(1, 1, 1)
        for f_bad_h in ("handle", 123, object(), SchedulerJobState.ACTIVE):
            with self.subTest(bad_h=f_bad_h):
                with self.assertRaises(StateError) as f_cm:
                    PointStateView(
                        f_point_id="pt-1",
                        f_ordinal=0,
                        f_scale_point=f_sp,
                        f_state=PointRunState.NOT_STARTED,
                        f_handle=f_bad_h,  # type: ignore
                    )
                self.assertIn("handle must be JobHandle or None, got:", str(f_cm.exception))

    def testPointStateViewRejectsInvalidSchedulerState(self) -> None:
        """Tests that PointStateView constructor rejects non-SchedulerJobState when scheduler state is provided."""
        f_sp = ScalePoint(1, 1, 1)
        for f_bad_sched in ("queued", 123, PointRunState.SUCCEEDED, OverallRunState.SUCCEEDED):
            with self.subTest(bad_sched=f_bad_sched):
                with self.assertRaises(StateError) as f_cm:
                    PointStateView(
                        f_point_id="pt-1",
                        f_ordinal=0,
                        f_scale_point=f_sp,
                        f_state=PointRunState.NOT_STARTED,
                        f_scheduler_state=f_bad_sched,  # type: ignore
                    )
                self.assertIn("scheduler_state must be SchedulerJobState or None, got:", str(f_cm.exception))

    def testPointStateViewImmutabilityFrozenRaise(self) -> None:
        """Tests that initialized PointStateView rejects attribute mutations and deletions."""
        f_pv = PointStateView("pt-1", 0, ScalePoint(1, 1, 1), PointRunState.RUNNING)
        with self.assertRaises(AttributeError) as f_cm_set1:
            f_pv.m_point_id = "pt-2"  # type: ignore
        self.assertIn("Cannot modify immutable PointStateView", str(f_cm_set1.exception))

        with self.assertRaises(AttributeError) as f_cm_set2:
            f_pv.point_id = "pt-2"  # type: ignore
        self.assertIn("Cannot modify immutable PointStateView", str(f_cm_set2.exception))

        with self.assertRaises(AttributeError) as f_cm_del1:
            del f_pv.m_point_id
        self.assertIn("Cannot delete attribute from immutable PointStateView", str(f_cm_del1.exception))

        with self.assertRaises(AttributeError) as f_cm_del2:
            del f_pv.m_ordinal
        self.assertIn("Cannot delete attribute from immutable PointStateView", str(f_cm_del2.exception))

        self.assertEqual(f_pv.point_id, "pt-1")
        self.assertEqual(f_pv.ordinal, 0)

    def testPointStateViewImmutabilityUnfrozenSetattr(self) -> None:
        """Tests that unfrozen PointStateView allows slot attribute assignment via super().__setattr__."""
        f_pv = PointStateView.__new__(PointStateView)
        setattr(f_pv, "m_point_id", "unfrozen-pt")
        setattr(f_pv, "m_ordinal", 5)
        self.assertEqual(f_pv.m_point_id, "unfrozen-pt")
        self.assertEqual(f_pv.m_ordinal, 5)

    def testPointStateViewImmutabilityUnfrozenDelattr(self) -> None:
        """Tests that unfrozen PointStateView allows slot attribute deletion via super().__delattr__."""
        f_pv = PointStateView.__new__(PointStateView)
        setattr(f_pv, "m_point_id", "to_delete")
        self.assertTrue(hasattr(f_pv, "m_point_id"))
        delattr(f_pv, "m_point_id")
        self.assertFalse(hasattr(f_pv, "m_point_id"))

    def testPointStateViewPropertiesAndAliases(self) -> None:
        """Tests PointStateView properties, camelCase aliases, collections conversion, and terminal/success flags."""
        f_sp = ScalePoint(4, 1, 4)
        f_h = JobHandle("slurm", "job-12345")
        f_pv = PointStateView(
            "  pt-test-alias  ",
            3,
            f_sp,
            PointRunState.SUCCEEDED,
            f_handle=f_h,
            f_scheduler_state=SchedulerJobState.SUCCEEDED,
            f_combinations_completed=["c1", "c2"],
            f_combinations_failed=["c3"],
            f_combinations_missing=["c4"],
            f_diagnostics=["diag-warn"],
        )
        self.assertEqual(f_pv.point_id, "pt-test-alias")
        self.assertEqual(f_pv.pointId, f_pv.point_id)
        self.assertEqual(f_pv.ordinal, 3)
        self.assertEqual(f_pv.scale_point, f_sp)
        self.assertEqual(f_pv.scalePoint, f_pv.scale_point)
        self.assertEqual(f_pv.state, PointRunState.SUCCEEDED)
        self.assertEqual(f_pv.handle, f_h)
        self.assertEqual(f_pv.scheduler_state, SchedulerJobState.SUCCEEDED)
        self.assertEqual(f_pv.schedulerState, f_pv.scheduler_state)
        self.assertEqual(f_pv.combinations_completed, ("c1", "c2"))
        self.assertEqual(f_pv.combinationsCompleted, f_pv.combinations_completed)
        self.assertEqual(f_pv.combinations_failed, ("c3",))
        self.assertEqual(f_pv.combinationsFailed, f_pv.combinations_failed)
        self.assertEqual(f_pv.combinations_missing, ("c4",))
        self.assertEqual(f_pv.combinationsMissing, f_pv.combinations_missing)
        self.assertEqual(f_pv.diagnostics, ("diag-warn",))
        self.assertTrue(f_pv.is_terminal)
        self.assertTrue(f_pv.isTerminal)
        self.assertTrue(f_pv.is_success)
        self.assertTrue(f_pv.isSuccess)

    def testPointStateViewPropertiesNonTerminalAndNoneOptionals(self) -> None:
        """Tests PointStateView non-terminal properties and None optional fields."""
        f_sp = ScalePoint(1, 1, 1)
        f_pv = PointStateView("pt-running", 0, f_sp, PointRunState.RUNNING, f_handle=None, f_scheduler_state=None)
        self.assertFalse(f_pv.isTerminal)
        self.assertFalse(f_pv.is_terminal)
        self.assertFalse(f_pv.isSuccess)
        self.assertFalse(f_pv.is_success)
        self.assertIsNone(f_pv.handle)
        self.assertIsNone(f_pv.schedulerState)
        self.assertIsNone(f_pv.scheduler_state)

    def testPointStateViewToDictAndRepr(self) -> None:
        """Tests PointStateView dictionary serialization and string representation."""
        f_sp = ScalePoint(1, 1, 1)
        f_h = JobHandle("slurm", "job-999")
        f_pv_full = PointStateView(
            "pt-full",
            0,
            f_sp,
            PointRunState.SUCCEEDED,
            f_handle=f_h,
            f_scheduler_state=SchedulerJobState.SUCCEEDED,
            f_combinations_completed=["c1"],
            f_diagnostics=["d1"],
        )
        f_pv_none = PointStateView("pt-none", 1, f_sp, PointRunState.RUNNING)

        f_d_full = f_pv_full.toDict()
        self.assertEqual(f_d_full["point_id"], "pt-full")
        self.assertEqual(f_d_full["ordinal"], 0)
        self.assertEqual(f_d_full["scale_point"], f_sp.toDict())
        self.assertEqual(f_d_full["state"], "succeeded")
        self.assertEqual(f_d_full["handle"], f_h.toDict())
        self.assertEqual(f_d_full["scheduler_state"], "succeeded")
        self.assertEqual(f_d_full["combinations_completed"], ["c1"])
        self.assertEqual(f_d_full["combinations_failed"], [])
        self.assertEqual(f_d_full["combinations_missing"], [])
        self.assertEqual(f_d_full["diagnostics"], ["d1"])

        f_d_none = f_pv_none.toDict()
        self.assertEqual(f_d_none["point_id"], "pt-none")
        self.assertIsNone(f_d_none["handle"])
        self.assertIsNone(f_d_none["scheduler_state"])

        self.assertIn("PointStateView", repr(f_pv_full))
        self.assertIn("pt-full", repr(f_pv_full))
        self.assertIn("succeeded", repr(f_pv_full))
        self.assertIn("PointStateView", repr(f_pv_none))

    def testPointStateViewEqualityNonPointStateView(self) -> None:
        """Tests that PointStateView returns False when compared to objects of other types."""
        f_pv = PointStateView("pt-1", 0, ScalePoint(1, 1, 1), PointRunState.RUNNING)
        for f_other in ("string", 123, None, object(), [], RunStateView("run-1", OverallRunState.NOT_STARTED)):
            with self.subTest(other=f_other):
                self.assertFalse(f_pv == f_other)
                self.assertTrue(f_pv != f_other)

    def testPointStateViewEqualityPermutations(self) -> None:
        """Tests PointStateView equality comparison across all 10 member fields."""
        f_sp = ScalePoint(1, 1, 1)
        f_h = JobHandle("slurm", "101")
        f_base = PointStateView(
            "pt-1",
            0,
            f_sp,
            PointRunState.SUCCEEDED,
            f_h,
            SchedulerJobState.SUCCEEDED,
            ["c1"],
            ["c2"],
            ["c3"],
            ["d1"],
        )
        f_identical = PointStateView(
            "pt-1",
            0,
            f_sp,
            PointRunState.SUCCEEDED,
            f_h,
            SchedulerJobState.SUCCEEDED,
            ["c1"],
            ["c2"],
            ["c3"],
            ["d1"],
        )
        self.assertEqual(f_base, f_identical)

        f_diff_point_id = PointStateView("pt-2", 0, f_sp, PointRunState.SUCCEEDED, f_h, SchedulerJobState.SUCCEEDED, ["c1"], ["c2"], ["c3"], ["d1"])
        f_diff_ordinal = PointStateView("pt-1", 1, f_sp, PointRunState.SUCCEEDED, f_h, SchedulerJobState.SUCCEEDED, ["c1"], ["c2"], ["c3"], ["d1"])
        f_diff_sp = PointStateView("pt-1", 0, ScalePoint(4, 1, 4), PointRunState.SUCCEEDED, f_h, SchedulerJobState.SUCCEEDED, ["c1"], ["c2"], ["c3"], ["d1"])
        f_diff_state = PointStateView("pt-1", 0, f_sp, PointRunState.FAILED, f_h, SchedulerJobState.SUCCEEDED, ["c1"], ["c2"], ["c3"], ["d1"])
        f_diff_handle = PointStateView("pt-1", 0, f_sp, PointRunState.SUCCEEDED, JobHandle("slurm", "999"), SchedulerJobState.SUCCEEDED, ["c1"], ["c2"], ["c3"], ["d1"])
        f_diff_scheduler = PointStateView("pt-1", 0, f_sp, PointRunState.SUCCEEDED, f_h, SchedulerJobState.FAILED, ["c1"], ["c2"], ["c3"], ["d1"])
        f_diff_completed = PointStateView("pt-1", 0, f_sp, PointRunState.SUCCEEDED, f_h, SchedulerJobState.SUCCEEDED, ["c1_diff"], ["c2"], ["c3"], ["d1"])
        f_diff_failed = PointStateView("pt-1", 0, f_sp, PointRunState.SUCCEEDED, f_h, SchedulerJobState.SUCCEEDED, ["c1"], ["c2_diff"], ["c3"], ["d1"])
        f_diff_missing = PointStateView("pt-1", 0, f_sp, PointRunState.SUCCEEDED, f_h, SchedulerJobState.SUCCEEDED, ["c1"], ["c2"], ["c3_diff"], ["d1"])
        f_diff_diagnostics = PointStateView("pt-1", 0, f_sp, PointRunState.SUCCEEDED, f_h, SchedulerJobState.SUCCEEDED, ["c1"], ["c2"], ["c3"], ["d1_diff"])

        for f_label, f_variant in (
            ("point_id", f_diff_point_id),
            ("ordinal", f_diff_ordinal),
            ("scale_point", f_diff_sp),
            ("state", f_diff_state),
            ("handle", f_diff_handle),
            ("scheduler_state", f_diff_scheduler),
            ("combinations_completed", f_diff_completed),
            ("combinations_failed", f_diff_failed),
            ("combinations_missing", f_diff_missing),
            ("diagnostics", f_diff_diagnostics),
        ):
            with self.subTest(variant=f_label):
                self.assertNotEqual(f_base, f_variant)
                self.assertFalse(f_base == f_variant)


class RunStateViewContractTest(unittest.TestCase):
    """Unit tests covering RunStateView argument validation, immutability, properties, serialization, and equality (ID 037)."""

    def testRunStateViewRejectsInvalidRunId(self) -> None:
        """Tests that RunStateView constructor rejects non-string or whitespace-only run_id."""
        for f_bad_id in (None, 123, "", "   ", "\t\n", []):
            with self.subTest(bad_id=f_bad_id):
                with self.assertRaises(StateError) as f_cm:
                    RunStateView(f_run_id=f_bad_id, f_state=OverallRunState.NOT_STARTED)  # type: ignore
                self.assertIn("run_id must be a non-empty string, got:", str(f_cm.exception))

    def testRunStateViewRejectsInvalidState(self) -> None:
        """Tests that RunStateView constructor rejects non-OverallRunState instances."""
        for f_bad_st in (None, "not_started", 123, PointRunState.SUCCEEDED, SchedulerJobState.SUCCEEDED):
            with self.subTest(bad_st=f_bad_st):
                with self.assertRaises(StateError) as f_cm:
                    RunStateView("run-1", f_bad_st)  # type: ignore
                self.assertIn("state must be OverallRunState, got:", str(f_cm.exception))

    def testRunStateViewRejectsInvalidActivePointOrdinal(self) -> None:
        """Tests that RunStateView constructor rejects negative or non-integer active_point_ordinal."""
        for f_bad_ord in (-1, -99, "0", 1.5, []):
            with self.subTest(bad_ord=f_bad_ord):
                with self.assertRaises(StateError) as f_cm:
                    RunStateView("run-1", OverallRunState.IN_PROGRESS, f_active_point_ordinal=f_bad_ord)  # type: ignore
                self.assertIn("active_point_ordinal must be non-negative integer or None, got:", str(f_cm.exception))

    def testRunStateViewImmutabilityFrozenRaise(self) -> None:
        """Tests that initialized RunStateView rejects attribute modifications and deletions."""
        f_rv = RunStateView("run-1", OverallRunState.IN_PROGRESS)
        with self.assertRaises(AttributeError) as f_cm_set1:
            f_rv.m_run_id = "run-2"  # type: ignore
        self.assertIn("Cannot modify immutable RunStateView", str(f_cm_set1.exception))

        with self.assertRaises(AttributeError) as f_cm_set2:
            f_rv.run_id = "run-2"  # type: ignore
        self.assertIn("Cannot modify immutable RunStateView", str(f_cm_set2.exception))

        with self.assertRaises(AttributeError) as f_cm_del1:
            del f_rv.m_run_id
        self.assertIn("Cannot delete attribute from immutable RunStateView", str(f_cm_del1.exception))

        with self.assertRaises(AttributeError) as f_cm_del2:
            del f_rv.m_state
        self.assertIn("Cannot delete attribute from immutable RunStateView", str(f_cm_del2.exception))

        self.assertEqual(f_rv.run_id, "run-1")
        self.assertEqual(f_rv.state, OverallRunState.IN_PROGRESS)

    def testRunStateViewImmutabilityUnfrozenSetattr(self) -> None:
        """Tests that unfrozen RunStateView allows slot attribute assignment via super().__setattr__."""
        f_rv = RunStateView.__new__(RunStateView)
        setattr(f_rv, "m_run_id", "unfrozen-run")
        setattr(f_rv, "m_active_point_ordinal", 2)
        self.assertEqual(f_rv.m_run_id, "unfrozen-run")
        self.assertEqual(f_rv.m_active_point_ordinal, 2)

    def testRunStateViewImmutabilityUnfrozenDelattr(self) -> None:
        """Tests that unfrozen RunStateView allows slot attribute deletion via super().__delattr__."""
        f_rv = RunStateView.__new__(RunStateView)
        setattr(f_rv, "m_run_id", "to_delete")
        self.assertTrue(hasattr(f_rv, "m_run_id"))
        delattr(f_rv, "m_run_id")
        self.assertFalse(hasattr(f_rv, "m_run_id"))

    def testRunStateViewPropertiesAndAliases(self) -> None:
        """Tests RunStateView properties, camelCase aliases, collections conversion, and terminal/success flags."""
        f_pv = PointStateView("pt-0", 0, ScalePoint(1, 1, 1), PointRunState.SUCCEEDED)
        f_rv = RunStateView(
            "  run-test-alias  ",
            OverallRunState.SUCCEEDED,
            [f_pv],
            f_active_point_ordinal=0,
            f_diagnostics=["diag-all-good"],
            f_has_interruption=True,
            f_has_success_marker=True,
        )
        self.assertEqual(f_rv.run_id, "run-test-alias")
        self.assertEqual(f_rv.runId, f_rv.run_id)
        self.assertEqual(f_rv.state, OverallRunState.SUCCEEDED)
        self.assertEqual(f_rv.point_states, (f_pv,))
        self.assertEqual(f_rv.pointStates, f_rv.point_states)
        self.assertEqual(f_rv.active_point_ordinal, 0)
        self.assertEqual(f_rv.activePointOrdinal, f_rv.active_point_ordinal)
        self.assertEqual(f_rv.diagnostics, ("diag-all-good",))
        self.assertTrue(f_rv.has_interruption)
        self.assertTrue(f_rv.hasInterruption)
        self.assertTrue(f_rv.has_success_marker)
        self.assertTrue(f_rv.hasSuccessMarker)
        self.assertTrue(f_rv.is_terminal)
        self.assertTrue(f_rv.isTerminal)
        self.assertTrue(f_rv.is_success)
        self.assertTrue(f_rv.isSuccess)

    def testRunStateViewPropertiesNonTerminalAndDefaults(self) -> None:
        """Tests RunStateView default values for collections and optional properties."""
        f_rv = RunStateView("run-active", OverallRunState.IN_PROGRESS)
        self.assertEqual(f_rv.point_states, ())
        self.assertEqual(f_rv.pointStates, ())
        self.assertIsNone(f_rv.active_point_ordinal)
        self.assertIsNone(f_rv.activePointOrdinal)
        self.assertEqual(f_rv.diagnostics, ())
        self.assertFalse(f_rv.has_interruption)
        self.assertFalse(f_rv.hasInterruption)
        self.assertFalse(f_rv.has_success_marker)
        self.assertFalse(f_rv.hasSuccessMarker)
        self.assertFalse(f_rv.isTerminal)
        self.assertFalse(f_rv.is_terminal)
        self.assertFalse(f_rv.isSuccess)
        self.assertFalse(f_rv.is_success)

    def testRunStateViewToDictAndRepr(self) -> None:
        """Tests RunStateView dictionary serialization and string representation."""
        f_pv = PointStateView("pt-0", 0, ScalePoint(1, 1, 1), PointRunState.SUCCEEDED)
        f_rv = RunStateView(
            "run-42",
            OverallRunState.SUCCEEDED,
            [f_pv],
            f_active_point_ordinal=0,
            f_diagnostics=["done"],
            f_has_interruption=False,
            f_has_success_marker=True,
        )
        f_expected_dict = {
            "run_id": "run-42",
            "state": "succeeded",
            "active_point_ordinal": 0,
            "has_interruption": False,
            "has_success_marker": True,
            "diagnostics": ["done"],
            "point_states": [f_pv.toDict()],
        }
        self.assertEqual(f_rv.toDict(), f_expected_dict)
        self.assertEqual(
            repr(f_rv),
            "RunStateView(run_id='run-42', state='succeeded', active_point_ordinal=0, points_count=1)",
        )

    def testRunStateViewEqualityNonRunStateView(self) -> None:
        """Tests that RunStateView returns False when compared to objects of other types."""
        f_rv = RunStateView("run-1", OverallRunState.NOT_STARTED)
        for f_other in ("string", 123, None, object(), [], PointStateView("pt-1", 0, ScalePoint(1, 1, 1), PointRunState.NOT_STARTED)):
            with self.subTest(other=f_other):
                self.assertFalse(f_rv == f_other)
                self.assertTrue(f_rv != f_other)

    def testRunStateViewEqualityPermutations(self) -> None:
        """Tests RunStateView equality comparison across all 7 member fields."""
        f_pv1 = PointStateView("pt-0", 0, ScalePoint(1, 1, 1), PointRunState.SUCCEEDED)
        f_pv2 = PointStateView("pt-1", 1, ScalePoint(4, 1, 4), PointRunState.SUCCEEDED)
        f_base = RunStateView("run-1", OverallRunState.SUCCEEDED, [f_pv1], 0, ["d1"], False, True)
        f_identical = RunStateView("run-1", OverallRunState.SUCCEEDED, [f_pv1], 0, ["d1"], False, True)
        self.assertEqual(f_base, f_identical)

        f_diff_run_id = RunStateView("run-2", OverallRunState.SUCCEEDED, [f_pv1], 0, ["d1"], False, True)
        f_diff_state = RunStateView("run-1", OverallRunState.FAILED, [f_pv1], 0, ["d1"], False, True)
        f_diff_points = RunStateView("run-1", OverallRunState.SUCCEEDED, [f_pv2], 0, ["d1"], False, True)
        f_diff_active = RunStateView("run-1", OverallRunState.SUCCEEDED, [f_pv1], 1, ["d1"], False, True)
        f_diff_diag = RunStateView("run-1", OverallRunState.SUCCEEDED, [f_pv1], 0, ["d2"], False, True)
        f_diff_interruption = RunStateView("run-1", OverallRunState.SUCCEEDED, [f_pv1], 0, ["d1"], True, True)
        f_diff_marker = RunStateView("run-1", OverallRunState.SUCCEEDED, [f_pv1], 0, ["d1"], False, False)

        for f_label, f_variant in (
            ("run_id", f_diff_run_id),
            ("state", f_diff_state),
            ("point_states", f_diff_points),
            ("active_point_ordinal", f_diff_active),
            ("diagnostics", f_diff_diag),
            ("has_interruption", f_diff_interruption),
            ("has_success_marker", f_diff_marker),
        ):
            with self.subTest(variant=f_label):
                self.assertNotEqual(f_base, f_variant)
                self.assertFalse(f_base == f_variant)


class StateReconcilerExecutionContractTest(unittest.TestCase):
    """Integration and edge contract tests for StateReconciler.reconcile execution lifecycle."""

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.mkdtemp(prefix="lsmiotool-reconcile-test-")
        self.m_default_profile_path = os.path.normpath(
            os.path.join(
                os.path.dirname(__file__), "..", "..", "etc", "environments.json"
            )
        )
        self.m_profile_doc = ProfileLoader.load(self.m_default_profile_path)
        self.m_registry = EnvironmentResolver.resolveRegistry(
            self.m_profile_doc, f_user="alice", f_home="/home/alice"
        )
        self.m_viking_profile = self.m_registry.getProfile("VIKING")

    def tearDown(self) -> None:
        shutil.rmtree(self.m_temp_dir, ignore_errors=True)

    def _createTestPlan(
        self,
        f_run_id: str,
        f_target: str = "lsmio",
        f_scale: str = "local",
        f_setup: str = "NATIVE",
    ) -> RunPlan:
        f_req = RunRequest(f_target=f_target, f_scale=f_scale, f_ssd=False, f_setup=f_setup)
        f_tokens = [f"lm-{i:024d}" for i in range(1, 20)]
        f_tok_idx = 0

        def token_gen() -> str:
            nonlocal f_tok_idx
            tok = f_tokens[f_tok_idx]
            f_tok_idx += 1
            return tok

        return RunPlanner.createPlan(
            f_request=f_req,
            f_profile=self.m_viking_profile,
            f_run_id_source=lambda: f_run_id,
            f_clock=lambda: "2026-08-20T12:00:00Z",
            f_token_source=token_gen,
        )

    def _setupRunEnvironment(
        self,
        f_run_id: str,
        f_target: str = "lsmio",
        f_scale: str = "local",
        f_setup: str = "NATIVE",
    ) -> Tuple[RunPlan, ArtifactStore, EvidenceStore]:
        f_plan = self._createTestPlan(f_run_id, f_target=f_target, f_scale=f_scale, f_setup=f_setup)
        f_art_store = ArtifactStore(self.m_temp_dir, f_run_id)
        f_art_store.allocateRun(f_plan)
        for f_idx, f_sp in enumerate(f_plan.scale_points):
            f_art_store.preparePoint(f_sp, f_ordinal=f_idx)
        f_evidence_store = EvidenceStore(f_art_store.layout, f_plan=f_plan)
        return f_plan, f_art_store, f_evidence_store

    def testReconcileRejectsInvalidPlan(self) -> None:
        """Verifies StateReconciler.reconcile rejects invalid plan arguments with StateError."""
        f_plan, f_art_store, f_store = self._setupRunEnvironment("run-a1")
        for f_bad_plan in (None, "plan", 123, object(), []):
            with self.subTest(bad_plan=f_bad_plan):
                with self.assertRaises(StateError) as ctx:
                    StateReconciler.reconcile(f_bad_plan, f_store)
                self.assertIn("f_plan must be a RunPlan, got:", str(ctx.exception))

    def testReconcileRejectsInvalidEvidenceStore(self) -> None:
        """Verifies StateReconciler.reconcile rejects invalid evidence store arguments with StateError."""
        f_plan, f_art_store, f_store = self._setupRunEnvironment("run-a2")
        for f_bad_store in (None, "store", 123, {}, []):
            with self.subTest(bad_store=f_bad_store):
                with self.assertRaises(StateError) as ctx:
                    StateReconciler.reconcile(f_plan, f_bad_store)
                self.assertIn("f_evidence_store must be EvidenceStore, got:", str(ctx.exception))

    def testReconcileControlStreamIgnoredKind(self) -> None:
        """Verifies that non-interruption and non-marker control events are skipped in reconcile."""
        f_plan, f_art_store, f_store = self._setupRunEnvironment("run-b1")
        f_ctrl_dir = os.path.join(f_art_store.layout.controlEventsDir, "w1")
        os.makedirs(f_ctrl_dir, exist_ok=True)
        with open(os.path.join(f_ctrl_dir, "1.json"), "w") as f_f:
            json.dump(
                {
                    "schema_version": 1,
                    "writer_kind": "control",
                    "writer_id": "w1",
                    "sequence_number": 1,
                    "evidence_kind": "controller_started",
                    "created_at_utc": "2026-08-20T12:00:00Z",
                    "payload": {},
                },
                f_f,
            )
        f_rv = StateReconciler.reconcile(f_plan, f_store)
        self.assertFalse(f_rv.has_interruption)
        self.assertFalse(f_rv.has_success_marker)
        self.assertEqual(f_rv.state, OverallRunState.NOT_STARTED)

    def testReconcileControlStreamCorruptionError(self) -> None:
        """Verifies corrupt control stream triggers INDETERMINATE with appropriate diagnostics."""
        f_plan, f_art_store, f_store = self._setupRunEnvironment("run-b2")
        f_ctrl_dir = os.path.join(f_art_store.layout.controlEventsDir, "w1")
        os.makedirs(f_ctrl_dir, exist_ok=True)
        with open(os.path.join(f_ctrl_dir, "1.json"), "w") as f_f:
            f_f.write("{corrupt_json")
        f_rv = StateReconciler.reconcile(f_plan, f_store)
        self.assertEqual(f_rv.state, OverallRunState.INDETERMINATE)
        self.assertTrue(any("Control stream error for writer 'w1'" in d for d in f_rv.diagnostics))
        self.assertTrue(any("Overall INDETERMINATE due to corrupt control stream" in d for d in f_rv.diagnostics))

    def testReconcileInterruptedPrecedesMarkerSameWriter(self) -> None:
        """Verifies monotonic sequence ordering sets interrupted first when seq(interrupted) < seq(marker)."""
        f_plan, f_art_store, f_store = self._setupRunEnvironment("run-c1")
        f_ctrl_dir = os.path.join(f_art_store.layout.controlEventsDir, "w1")
        os.makedirs(f_ctrl_dir, exist_ok=True)
        with open(os.path.join(f_ctrl_dir, "1.json"), "w") as f_f:
            json.dump(
                {
                    "schema_version": 1,
                    "writer_kind": "control",
                    "writer_id": "w1",
                    "sequence_number": 1,
                    "evidence_kind": "interrupted",
                    "created_at_utc": "2026-08-20T12:00:00Z",
                    "payload": {},
                },
                f_f,
            )
        with open(os.path.join(f_ctrl_dir, "2.json"), "w") as f_f:
            json.dump(
                {
                    "schema_version": 1,
                    "writer_kind": "control",
                    "writer_id": "w1",
                    "sequence_number": 2,
                    "evidence_kind": "whole_run_succeeded",
                    "created_at_utc": "2026-08-20T12:05:00Z",
                    "payload": {},
                },
                f_f,
            )
        f_rv = StateReconciler.reconcile(f_plan, f_store)
        self.assertTrue(f_rv.has_interruption)
        self.assertTrue(f_rv.has_success_marker)
        self.assertEqual(f_rv.state, OverallRunState.INTERRUPTED)

    def testReconcileInterruptedCrossWriterOrdering(self) -> None:
        """Verifies cross-writer timestamp ordering between interruption and success marker."""
        # Subtest 1: interrupted earlier than success
        with self.subTest(case="interrupted_earlier"):
            f_plan, f_art_store, f_store = self._setupRunEnvironment("run-c2-1")
            f_w1_dir = os.path.join(f_art_store.layout.controlEventsDir, "w1")
            f_w2_dir = os.path.join(f_art_store.layout.controlEventsDir, "w2")
            os.makedirs(f_w1_dir, exist_ok=True)
            os.makedirs(f_w2_dir, exist_ok=True)
            with open(os.path.join(f_w1_dir, "1.json"), "w") as f_f:
                json.dump(
                    {
                        "schema_version": 1,
                        "writer_kind": "control",
                        "writer_id": "w1",
                        "sequence_number": 1,
                        "evidence_kind": "interrupted",
                        "created_at_utc": "2026-08-20T12:00:00Z",
                        "payload": {},
                    },
                    f_f,
                )
            with open(os.path.join(f_w2_dir, "1.json"), "w") as f_f:
                json.dump(
                    {
                        "schema_version": 1,
                        "writer_kind": "control",
                        "writer_id": "w2",
                        "sequence_number": 1,
                        "evidence_kind": "whole_run_succeeded",
                        "created_at_utc": "2026-08-20T12:05:00Z",
                        "payload": {},
                    },
                    f_f,
                )
            f_rv = StateReconciler.reconcile(f_plan, f_store)
            self.assertEqual(f_rv.state, OverallRunState.INTERRUPTED)

        # Subtest 2: interrupted later than success
        with self.subTest(case="interrupted_later"):
            f_plan, f_art_store, f_store = self._setupRunEnvironment("run-c2-2")
            f_w1_dir = os.path.join(f_art_store.layout.controlEventsDir, "w1")
            f_w2_dir = os.path.join(f_art_store.layout.controlEventsDir, "w2")
            os.makedirs(f_w1_dir, exist_ok=True)
            os.makedirs(f_w2_dir, exist_ok=True)
            with open(os.path.join(f_w1_dir, "1.json"), "w") as f_f:
                json.dump(
                    {
                        "schema_version": 1,
                        "writer_kind": "control",
                        "writer_id": "w1",
                        "sequence_number": 1,
                        "evidence_kind": "interrupted",
                        "created_at_utc": "2026-08-20T12:10:00Z",
                        "payload": {},
                    },
                    f_f,
                )
            with open(os.path.join(f_w2_dir, "1.json"), "w") as f_f:
                json.dump(
                    {
                        "schema_version": 1,
                        "writer_kind": "control",
                        "writer_id": "w2",
                        "sequence_number": 1,
                        "evidence_kind": "whole_run_succeeded",
                        "created_at_utc": "2026-08-20T12:05:00Z",
                        "payload": {},
                    },
                    f_f,
                )
            f_rv = StateReconciler.reconcile(f_plan, f_store)
            self.assertEqual(f_rv.state, OverallRunState.IN_PROGRESS)

    def testReconcileSubmissionRecordsReadError(self) -> None:
        """Verifies that an error reading submission records is diagnosed and leaves state NOT_STARTED."""
        f_plan, f_art_store, f_store = self._setupRunEnvironment("run-d1")
        with patch.object(
            EvidenceStore,
            "readSubmissionRecords",
            side_effect=EvidenceCorruptionError("Corrupted submission stream"),
        ):
            f_rv = StateReconciler.reconcile(f_plan, f_store)
            self.assertEqual(f_rv.point_states[0].state, PointRunState.NOT_STARTED)
            self.assertTrue(
                any(
                    "Submission records read error: Corrupted submission stream" in d
                    for d in f_rv.point_states[0].diagnostics
                )
            )

    def testReconcileSubmissionRecordedNonDictHandle(self) -> None:
        """Verifies submission recorded with non-dict handle is tolerated and falls through to SUBMITTED."""
        f_plan, f_art_store, f_store = self._setupRunEnvironment("run-d2")
        f_sp = f_plan.scale_points[0]
        os.makedirs(f_art_store.layout.pointSchedulerDir(f_sp, 0), exist_ok=True)
        f_sub_rec_path = os.path.join(
            f_art_store.layout.pointSchedulerDir(f_sp, 0), "submission_recorded.json"
        )
        with open(f_sub_rec_path, "w") as f_f:
            json.dump(
                {
                    "schema_version": 1,
                    "writer_kind": "control",
                    "writer_id": "client",
                    "sequence_number": 1,
                    "evidence_kind": "submission_recorded",
                    "created_at_utc": "2026-08-20T12:00:00Z",
                    "payload": {"handle": "not_a_dict"},
                },
                f_f,
            )
        f_rv = StateReconciler.reconcile(f_plan, f_store)
        self.assertIsNone(f_rv.point_states[0].handle)
        self.assertEqual(f_rv.point_states[0].state, PointRunState.SUBMITTED)

    def testReconcileSubmissionRecordedCorruptHandleDict(self) -> None:
        """Verifies submission recorded with malformed handle dict causes INDETERMINATE."""
        f_plan, f_art_store, f_store = self._setupRunEnvironment("run-d3")
        f_sp = f_plan.scale_points[0]
        os.makedirs(f_art_store.layout.pointSchedulerDir(f_sp, 0), exist_ok=True)
        f_sub_rec_path = os.path.join(
            f_art_store.layout.pointSchedulerDir(f_sp, 0), "submission_recorded.json"
        )
        with open(f_sub_rec_path, "w") as f_f:
            json.dump(
                {
                    "schema_version": 1,
                    "writer_kind": "control",
                    "writer_id": "client",
                    "sequence_number": 1,
                    "evidence_kind": "submission_recorded",
                    "created_at_utc": "2026-08-20T12:00:00Z",
                    "payload": {"handle": {"invalid": 123}},
                },
                f_f,
            )
        f_rv = StateReconciler.reconcile(f_plan, f_store)
        self.assertEqual(f_rv.point_states[0].state, PointRunState.INDETERMINATE)
        self.assertTrue(
            any(
                "Corrupt JobHandle in submission_recorded:" in d
                for d in f_rv.point_states[0].diagnostics
            )
        )

    def testReconcileDiskObservationsMalformedPayload(self) -> None:
        """Verifies non-dict observation payload triggers INDETERMINATE and records diagnostic."""
        f_plan, f_art_store, f_store = self._setupRunEnvironment("run-e1")
        f_sp = f_plan.scale_points[0]
        f_store.recordSubmissionRequested(f_sp, "client", f_ordinal=0)
        f_fake_obs = SimpleNamespace(
            payload="not_a_dict",
            created_at_utc="2026-08-20T12:00:00Z",
            writer_id="w1",
            sequence_number=1,
        )
        with patch.object(
            EvidenceStore, "readSchedulerObservations", return_value=[f_fake_obs]
        ):
            f_obs_dir = os.path.join(
                f_art_store.layout.pointSchedulerDir(f_sp, 0), "observations", "w1"
            )
            os.makedirs(f_obs_dir, exist_ok=True)
            f_rv = StateReconciler.reconcile(f_plan, f_store)
            self.assertEqual(f_rv.point_states[0].state, PointRunState.INDETERMINATE)
            self.assertTrue(
                any(
                    "Corrupt observation payload: 'not_a_dict'" in d
                    for d in f_rv.point_states[0].diagnostics
                )
            )

    def testReconcileDiskObservationsCorruptHandle(self) -> None:
        """Verifies corrupt JobHandle dictionary in disk observation payload causes INDETERMINATE."""
        f_plan, f_art_store, f_store = self._setupRunEnvironment("run-e2")
        f_sp = f_plan.scale_points[0]
        f_valid_handle = JobHandle("slurm", "job-100")
        f_store.recordSubmissionRecorded(f_sp, "client", f_handle=f_valid_handle, f_ordinal=0)
        f_fake_obs = SimpleNamespace(
            payload={"handle": {"invalid": 123}},
            created_at_utc="2026-08-20T12:00:00Z",
            writer_id="w1",
            sequence_number=1,
        )
        with patch.object(
            EvidenceStore, "readSchedulerObservations", return_value=[f_fake_obs]
        ):
            f_obs_dir = os.path.join(
                f_art_store.layout.pointSchedulerDir(f_sp, 0), "observations", "w1"
            )
            os.makedirs(f_obs_dir, exist_ok=True)
            f_rv = StateReconciler.reconcile(f_plan, f_store)
            self.assertEqual(f_rv.point_states[0].state, PointRunState.INDETERMINATE)
            self.assertTrue(
                any(
                    "Indeterminate: Corrupted evidence encountered" in d
                    for d in f_rv.point_states[0].diagnostics
                )
            )

    def testReconcileDiskObservationsStateParsingVariations(self) -> None:
        """Verifies disk observation state extraction across enum, invalid string, and non-string types."""
        f_plan, f_art_store, f_store = self._setupRunEnvironment("run-e3")
        f_sp = f_plan.scale_points[0]
        f_store.recordSubmissionRequested(f_sp, "client", f_ordinal=0)
        f_obs_list = [
            SimpleNamespace(
                payload={"state": SchedulerJobState.FAILED},
                created_at_utc="2026-08-20T12:02:00Z",
                writer_id="w1",
                sequence_number=1,
            ),
            SimpleNamespace(
                payload={"state": "invalid_enum_val"},
                created_at_utc="2026-08-20T12:03:00Z",
                writer_id="w1",
                sequence_number=2,
            ),
            SimpleNamespace(
                payload={"state": 99999},
                created_at_utc="2026-08-20T12:04:00Z",
                writer_id="w1",
                sequence_number=3,
            ),
        ]
        with patch.object(
            EvidenceStore, "readSchedulerObservations", return_value=f_obs_list
        ):
            f_obs_dir = os.path.join(
                f_art_store.layout.pointSchedulerDir(f_sp, 0), "observations", "w1"
            )
            os.makedirs(f_obs_dir, exist_ok=True)
            f_rv = StateReconciler.reconcile(f_plan, f_store)
            self.assertEqual(f_rv.point_states[0].state, PointRunState.FAILED)

    def testReconcileFreshObservationDictHandle(self) -> None:
        """Verifies fresh observation handle parsing with matching dict handle and malformed dict handle."""
        # Subtest 1: matching dict handle
        with self.subTest(case="matching_handle"):
            f_plan, f_art_store, f_store = self._setupRunEnvironment("run-f1-1")
            f_sp = f_plan.scale_points[0]
            f_valid_h = JobHandle("slurm", "job-200")
            f_store.recordSubmissionRecorded(f_sp, "client", f_handle=f_valid_h, f_ordinal=0)
            f_fresh = {
                "job-200": {
                    "handle": {"backend": "slurm", "job_id": "job-200"},
                    "state": "active",
                }
            }
            f_rv = StateReconciler.reconcile(f_plan, f_store, f_scheduler_observations=f_fresh)
            self.assertEqual(f_rv.point_states[0].state, PointRunState.RUNNING)

        # Subtest 2: corrupt dict handle
        with self.subTest(case="corrupt_handle"):
            f_plan, f_art_store, f_store = self._setupRunEnvironment("run-f1-2")
            f_sp = f_plan.scale_points[0]
            f_valid_h = JobHandle("slurm", "job-200")
            f_store.recordSubmissionRecorded(f_sp, "client", f_handle=f_valid_h, f_ordinal=0)
            f_fresh = {
                "job-200": {
                    "handle": {"invalid": 123},
                    "state": "active",
                }
            }
            f_rv = StateReconciler.reconcile(f_plan, f_store, f_scheduler_observations=f_fresh)
            self.assertEqual(f_rv.point_states[0].state, PointRunState.INDETERMINATE)

    def testReconcileWorkerEventsCorruptionError(self) -> None:
        """Verifies readWorkerEvents corruption sets point INDETERMINATE with diagnostics."""
        f_plan, f_art_store, f_store = self._setupRunEnvironment("run-g1")
        f_sp = f_plan.scale_points[0]
        f_store.recordSubmissionRequested(f_sp, "client", f_ordinal=0)
        with patch.object(
            EvidenceStore,
            "readWorkerEvents",
            side_effect=EvidenceCorruptionError("Worker stream corrupt"),
        ):
            f_rv = StateReconciler.reconcile(f_plan, f_store)
            self.assertEqual(f_rv.point_states[0].state, PointRunState.INDETERMINATE)
            self.assertTrue(
                any(
                    "Worker events read error: Worker stream corrupt" in d
                    for d in f_rv.point_states[0].diagnostics
                )
            )

    def testReconcileRankResultCorruptionError(self) -> None:
        """Verifies readRankResult corruption in LSMIO mode sets INDETERMINATE with diagnostics."""
        f_plan, f_art_store, f_store = self._setupRunEnvironment("run-h1", f_target="lsmio")
        f_sp = f_plan.scale_points[0]
        f_store.recordSubmissionRequested(f_sp, "client", f_ordinal=0)
        with patch.object(
            EvidenceStore,
            "readRankResult",
            side_effect=EvidenceCorruptionError("Rank result corrupt"),
        ):
            f_rv = StateReconciler.reconcile(f_plan, f_store)
            self.assertEqual(f_rv.point_states[0].state, PointRunState.INDETERMINATE)
            self.assertTrue(
                any(
                    "Corrupt rank result for rank 0" in d
                    for d in f_rv.point_states[0].diagnostics
                )
            )


class StateReconcilerDerivationContractTest(unittest.TestCase):
    """Pure in-memory unit tests covering StateReconciler derivation helper methods."""

    def testIsResultFailure(self) -> None:
        """Verifies _isResultFailure identifies failure payloads accurately."""
        self.assertTrue(StateReconciler._isResultFailure({"status": "failed", "exit_code": 1}))
        self.assertFalse(StateReconciler._isResultFailure({"status": "success", "exit_code": 0}))

    def testLookupSchedulerObservationByHandleOrJobId(self) -> None:
        """Verifies _lookupSchedulerObservation matches by JobHandle object or job_id string."""
        f_sp = ScalePoint(1, 1, 1)
        f_h = JobHandle("slurm", "job-100")
        f_res1 = StateReconciler._lookupSchedulerObservation(f_sp, 0, "pt-0", f_h, {f_h: "succeeded"})
        self.assertEqual(f_res1, {"state": SchedulerJobState.SUCCEEDED})
        f_res2 = StateReconciler._lookupSchedulerObservation(f_sp, 0, "pt-0", f_h, {"job-100": "succeeded"})
        self.assertEqual(f_res2, {"state": SchedulerJobState.SUCCEEDED})

    def testLookupSchedulerObservationStringInvalidEnum(self) -> None:
        """Verifies string observation with invalid enum value returns UNKNOWN with raw field."""
        f_sp = ScalePoint(1, 1, 1)
        f_h = JobHandle("slurm", "job-100")
        f_res = StateReconciler._lookupSchedulerObservation(f_sp, 0, "pt-0", f_h, {"pt-0": "bogus_state"})
        self.assertEqual(f_res, {"state": SchedulerJobState.UNKNOWN, "raw": "bogus_state"})

    def testLookupSchedulerObservationDictVariations(self) -> None:
        """Verifies dictionary observations handling missing state, enum state, and invalid str state."""
        f_sp = ScalePoint(1, 1, 1)
        f_h = JobHandle("slurm", "job-100")

        # Missing state key
        f_d1 = StateReconciler._lookupSchedulerObservation(f_sp, 0, "pt-0", f_h, {"pt-0": {"foo": "bar"}})
        self.assertEqual(f_d1, {"foo": "bar"})

        # Enum state
        f_d2 = StateReconciler._lookupSchedulerObservation(
            f_sp, 0, "pt-0", f_h, {"pt-0": {"state": SchedulerJobState.ACTIVE}}
        )
        self.assertEqual(f_d2, {"state": SchedulerJobState.ACTIVE})

        # Invalid str state
        f_d3 = StateReconciler._lookupSchedulerObservation(
            f_sp, 0, "pt-0", f_h, {"pt-0": {"state": "bogus"}}
        )
        self.assertEqual(f_d3, {"state": SchedulerJobState.UNKNOWN})

    def testLookupSchedulerObservationObjectWithStateAttribute(self) -> None:
        """Verifies object observations with .state and .handle attributes across type variations."""
        f_sp = ScalePoint(1, 1, 1)
        f_h = JobHandle("slurm", "job-100")

        # Object with enum state and handle
        f_o1 = StateReconciler._lookupSchedulerObservation(
            f_sp, 0, "pt-0", f_h, {"pt-0": SimpleNamespace(state=SchedulerJobState.ACTIVE, handle=f_h)}
        )
        self.assertEqual(f_o1, {"state": SchedulerJobState.ACTIVE, "handle": f_h})

        # Object with valid str state
        f_o2 = StateReconciler._lookupSchedulerObservation(
            f_sp, 0, "pt-0", f_h, {"pt-0": SimpleNamespace(state="queued")}
        )
        self.assertEqual(f_o2, {"state": SchedulerJobState.QUEUED, "handle": None})

        # Object with invalid str state
        f_o3 = StateReconciler._lookupSchedulerObservation(
            f_sp, 0, "pt-0", f_h, {"pt-0": SimpleNamespace(state="invalid_str")}
        )
        self.assertEqual(f_o3, {"state": SchedulerJobState.UNKNOWN, "handle": None})

        # Object with non-str / non-enum state (e.g. integer)
        f_o4 = StateReconciler._lookupSchedulerObservation(
            f_sp, 0, "pt-0", f_h, {"pt-0": SimpleNamespace(state=12345)}
        )
        self.assertEqual(f_o4, {"state": SchedulerJobState.UNKNOWN, "handle": None})

    def testLookupSchedulerObservationFallback(self) -> None:
        """Verifies fallback when observation is neither dict nor has .state attribute."""
        f_sp = ScalePoint(1, 1, 1)
        f_h = JobHandle("slurm", "job-100")
        f_res = StateReconciler._lookupSchedulerObservation(f_sp, 0, "pt-0", f_h, {"pt-0": 99999})
        self.assertEqual(f_res, {"state": SchedulerJobState.UNKNOWN})

    def testDerivePointStateCancellationFollowedByTerminalFailure(self) -> None:
        """Verifies Rule 3: failure after cancel request with terminal scheduler state returns FAILED."""
        f_cancel_rec = EvidenceRecord(
            WriterKind.CONTROL,
            "c1",
            1,
            EvidenceKind.CANCEL_REQUESTED,
            {},
            f_created_at_utc="2026-08-20T12:00:00Z",
        )
        f_diag: List[str] = []
        f_st = StateReconciler._derivePointState(
            f_sub_requested=True,
            f_sub_dispatched=True,
            f_sub_recorded=True,
            f_sched_state=SchedulerJobState.FAILED,
            f_is_lsmio=True,
            f_plan_combinations_count=1,
            f_combinations_completed=[],
            f_combinations_failed=["c1"],
            f_combinations_missing=[],
            f_rank_failure=False,
            f_rank_missing=False,
            f_has_worker_events=True,
            f_cancel_requested=True,
            f_cancel_recorded=False,
            f_cancel_unconfirmed=False,
            f_cancel_req_record=f_cancel_rec,
            f_failure_timestamp="2026-08-20T12:05:00Z",
            f_conflicting_handles=False,
            f_corrupt_evidence=False,
            f_point_diagnostics=f_diag,
        )
        self.assertEqual(f_st, PointRunState.FAILED)

    def testDerivePointStateCancellationFollowedByActiveFailure(self) -> None:
        """Verifies Rule 3: failure after cancel request with active scheduler state returns RUNNING."""
        f_cancel_rec = EvidenceRecord(
            WriterKind.CONTROL,
            "c1",
            1,
            EvidenceKind.CANCEL_REQUESTED,
            {},
            f_created_at_utc="2026-08-20T12:00:00Z",
        )
        f_diag: List[str] = []
        f_st = StateReconciler._derivePointState(
            f_sub_requested=True,
            f_sub_dispatched=True,
            f_sub_recorded=True,
            f_sched_state=SchedulerJobState.ACTIVE,
            f_is_lsmio=True,
            f_plan_combinations_count=1,
            f_combinations_completed=[],
            f_combinations_failed=["c1"],
            f_combinations_missing=[],
            f_rank_failure=False,
            f_rank_missing=False,
            f_has_worker_events=True,
            f_cancel_requested=True,
            f_cancel_recorded=False,
            f_cancel_unconfirmed=False,
            f_cancel_req_record=f_cancel_rec,
            f_failure_timestamp="2026-08-20T12:05:00Z",
            f_conflicting_handles=False,
            f_corrupt_evidence=False,
            f_point_diagnostics=f_diag,
        )
        self.assertEqual(f_st, PointRunState.RUNNING)

    def testDerivePointStateCancelRequestedTerminalCompletionIndeterminate(self) -> None:
        """Verifies Rule 3: terminal scheduler completion with cancel requested and no failure is INDETERMINATE."""
        f_cancel_rec = EvidenceRecord(
            WriterKind.CONTROL,
            "c1",
            1,
            EvidenceKind.CANCEL_REQUESTED,
            {},
            f_created_at_utc="2026-08-20T12:00:00Z",
        )
        f_diag: List[str] = []
        f_st = StateReconciler._derivePointState(
            f_sub_requested=True,
            f_sub_dispatched=True,
            f_sub_recorded=True,
            f_sched_state=SchedulerJobState.SUCCEEDED,
            f_is_lsmio=False,
            f_plan_combinations_count=1,
            f_combinations_completed=["c1"],
            f_combinations_failed=[],
            f_combinations_missing=[],
            f_rank_failure=False,
            f_rank_missing=False,
            f_has_worker_events=True,
            f_cancel_requested=True,
            f_cancel_recorded=False,
            f_cancel_unconfirmed=False,
            f_cancel_req_record=f_cancel_rec,
            f_failure_timestamp=None,
            f_conflicting_handles=False,
            f_corrupt_evidence=False,
            f_point_diagnostics=f_diag,
        )
        self.assertEqual(f_st, PointRunState.INDETERMINATE)
        self.assertTrue(
            any("Terminal completion while cancellation was requested" in d for d in f_diag)
        )

    def testDerivePointStateCancelRequestedActiveRunning(self) -> None:
        """Verifies Rule 3: active scheduler state with cancel requested and no failure returns RUNNING."""
        f_cancel_rec = EvidenceRecord(
            WriterKind.CONTROL,
            "c1",
            1,
            EvidenceKind.CANCEL_REQUESTED,
            {},
            f_created_at_utc="2026-08-20T12:00:00Z",
        )
        f_diag: List[str] = []
        f_st = StateReconciler._derivePointState(
            f_sub_requested=True,
            f_sub_dispatched=True,
            f_sub_recorded=True,
            f_sched_state=SchedulerJobState.ACTIVE,
            f_is_lsmio=False,
            f_plan_combinations_count=1,
            f_combinations_completed=[],
            f_combinations_failed=[],
            f_combinations_missing=[],
            f_rank_failure=False,
            f_rank_missing=False,
            f_has_worker_events=False,
            f_cancel_requested=True,
            f_cancel_recorded=False,
            f_cancel_unconfirmed=False,
            f_cancel_req_record=f_cancel_rec,
            f_failure_timestamp=None,
            f_conflicting_handles=False,
            f_corrupt_evidence=False,
            f_point_diagnostics=f_diag,
        )
        self.assertEqual(f_st, PointRunState.RUNNING)

    def testDerivePointStateSchedulerSucceededIncompleteCombinations(self) -> None:
        """Verifies Rule 1: scheduler SUCCEEDED but combinations completed < planned count returns RUNNING."""
        f_diag: List[str] = []
        f_st = StateReconciler._derivePointState(
            f_sub_requested=True,
            f_sub_dispatched=True,
            f_sub_recorded=True,
            f_sched_state=SchedulerJobState.SUCCEEDED,
            f_is_lsmio=False,
            f_plan_combinations_count=2,
            f_combinations_completed=["c1"],
            f_combinations_failed=[],
            f_combinations_missing=[],
            f_rank_failure=False,
            f_rank_missing=False,
            f_has_worker_events=False,
            f_cancel_requested=False,
            f_cancel_recorded=False,
            f_cancel_unconfirmed=False,
            f_cancel_req_record=None,
            f_failure_timestamp=None,
            f_conflicting_handles=False,
            f_corrupt_evidence=False,
            f_point_diagnostics=f_diag,
        )
        self.assertEqual(f_st, PointRunState.RUNNING)

    def testDerivePointStateDeadCodeAudit(self) -> None:
        """Verify deterministic PointRunState derivation for post-cancellation failure and unsubmitted points.

        1. When cancellation is requested but a specific combination/scheduler failure occurs,
           _derivePointState deterministically derives PointRunState.FAILED.
        2. When all submission flags are False, _derivePointState returns PointRunState.NOT_STARTED.
        """
        # Prove condition 1: if f_has_specific_failure is True, it returns before line 1368
        f_cancel_rec = EvidenceRecord(
            WriterKind.CONTROL,
            "c1",
            1,
            EvidenceKind.CANCEL_REQUESTED,
            {},
            f_created_at_utc="2026-08-20T12:00:00Z",
        )
        f_st_fail = StateReconciler._derivePointState(
            f_sub_requested=True,
            f_sub_dispatched=True,
            f_sub_recorded=True,
            f_sched_state=SchedulerJobState.FAILED,
            f_is_lsmio=False,
            f_plan_combinations_count=1,
            f_combinations_completed=[],
            f_combinations_failed=["c1"],
            f_combinations_missing=[],
            f_rank_failure=False,
            f_rank_missing=False,
            f_has_worker_events=True,
            f_cancel_requested=True,
            f_cancel_recorded=False,
            f_cancel_unconfirmed=False,
            f_cancel_req_record=f_cancel_rec,
            f_failure_timestamp="2026-08-20T12:05:00Z",
            f_conflicting_handles=False,
            f_corrupt_evidence=False,
            f_point_diagnostics=[],
        )
        self.assertEqual(f_st_fail, PointRunState.FAILED)

        # Prove condition 2: line 1300 returns NOT_STARTED if all submission flags are False
        f_st_not_started = StateReconciler._derivePointState(
            f_sub_requested=False,
            f_sub_dispatched=False,
            f_sub_recorded=False,
            f_sched_state=None,
            f_is_lsmio=False,
            f_plan_combinations_count=1,
            f_combinations_completed=[],
            f_combinations_failed=[],
            f_combinations_missing=[],
            f_rank_failure=False,
            f_rank_missing=False,
            f_has_worker_events=False,
            f_cancel_requested=False,
            f_cancel_recorded=False,
            f_cancel_unconfirmed=False,
            f_cancel_req_record=None,
            f_failure_timestamp=None,
            f_conflicting_handles=False,
            f_corrupt_evidence=False,
            f_point_diagnostics=[],
        )
        self.assertEqual(f_st_not_started, PointRunState.NOT_STARTED)

    def testDeriveOverallStateControlCorrupt(self) -> None:
        """Verifies _deriveOverallState returns INDETERMINATE with diagnostics when f_control_corrupt is True."""
        f_diag: List[str] = []
        f_st = StateReconciler._deriveOverallState(
            f_point_views=[],
            f_control_corrupt=True,
            f_has_interruption=False,
            f_has_success_marker=False,
            f_interrupted_first=False,
            f_run_diagnostics=f_diag,
        )
        self.assertEqual(f_st, OverallRunState.INDETERMINATE)
        self.assertTrue(
            any("Overall INDETERMINATE due to corrupt control stream" in d for d in f_diag)
        )


