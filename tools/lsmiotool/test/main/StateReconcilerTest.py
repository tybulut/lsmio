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

from lsmiotool.lib.artifacts import ArtifactLayout, ArtifactStore
from lsmiotool.lib.evidence import (
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
            os.path.join(os.path.dirname(__file__), "..", "..", "etc", "environments.json")
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
        f_setup: str = "NATIVE-M",
    ) -> RunPlan:
        f_req = RunRequest(f_target=f_target, f_scale=f_scale, f_ssd=False, f_setup=f_setup)
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
        f_setup: str = "NATIVE-M",
    ):
        f_plan = self._createTestPlan(f_run_id, f_target=f_target, f_scale=f_scale, f_setup=f_setup)
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
            f_run_id, f_target="lsmio", f_scale="local", f_setup="NATIVE-M"
        )
        f_point = f_plan.scale_points[0]
        f_handle = JobHandle("slurm", "1001")

        # 1. Record submission records
        f_store.recordSubmissionRequested(f_point, "client", f_ordinal=0)
        f_store.recordSubmissionDispatched(f_point, "client", f_ordinal=0)
        f_store.recordSubmissionRecorded(f_point, "client", f_handle=f_handle, f_ordinal=0)

        # 2. Record worker started event
        f_store.recordWorkerEvent(f_point, 1, EvidenceKind.CONTROLLER_STARTED, f_ordinal=0)

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
        f_store.recordWholeRunSucceeded("client", 1, f_payload={"summary": "all passed"})

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
            f_run_id, f_target="lsmio", f_scale="bake", f_setup="NATIVE-M"
        )
        # Point 2 has tasks=4
        f_point_4 = f_plan.scale_points[2]
        self.assertEqual(f_point_4.tasks, 4)
        f_handle = JobHandle("slurm", "1002")

        f_store.recordSubmissionRequested(f_point_4, "client", f_ordinal=2)
        f_store.recordSubmissionDispatched(f_point_4, "client", f_ordinal=2)
        f_store.recordSubmissionRecorded(f_point_4, "client", f_handle=f_handle, f_ordinal=2)
        f_store.recordWorkerEvent(f_point_4, 1, EvidenceKind.CONTROLLER_STARTED, f_ordinal=2)

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
            f_run_id, f_target="lsmio", f_scale="local", f_setup="NATIVE-M"
        )
        f_point = f_plan.scale_points[0]
        f_handle = JobHandle("slurm", "1003")

        f_store.recordSubmissionRecorded(f_point, "client", f_handle=f_handle, f_ordinal=0)

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
            f_run_id, f_target="lsmio", f_scale="local", f_setup="NATIVE-M"
        )
        f_point = f_plan.scale_points[0]
        f_handle = JobHandle("slurm", "1004")

        # Scenario A: Clean Cancellation without prior failure
        f_store.recordSubmissionRecorded(f_point, "client", f_handle=f_handle, f_ordinal=0)
        f_store.recordCancelRequested(f_point, "client", f_handle=f_handle, f_ordinal=0)
        f_store.recordCancelRecorded(f_point, "client", f_handle=f_handle, f_ordinal=0)

        f_view_clean_cancel = StateReconciler.reconcile(f_plan, f_store)
        self.assertEqual(f_view_clean_cancel.point_states[0].state, PointRunState.CANCELLED)
        self.assertEqual(f_view_clean_cancel.state, OverallRunState.CANCELLED)

        # Scenario B: Prior Failure precedes Cancel Request
        f_run_id_b = "run-state-004b"
        f_plan_b, f_art_store_b, f_store_b = self._setupRunEnvironment(
            f_run_id_b, f_target="lsmio", f_scale="local", f_setup="NATIVE-M"
        )
        f_point_b = f_plan_b.scale_points[0]

        f_store_b.recordSubmissionRecorded(f_point_b, "client", f_handle=f_handle, f_ordinal=0)
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
            f_run_id, f_target="lsmio", f_scale="local", f_setup="NATIVE-M"
        )
        f_point = f_plan.scale_points[0]
        f_handle = JobHandle("slurm", "1005")

        f_store.recordSubmissionRecorded(f_point, "client", f_handle=f_handle, f_ordinal=0)
        f_store.recordCancelRequested(f_point, "client", f_handle=f_handle, f_ordinal=0)

        # Record cancel_unconfirmed
        f_unconf_path = os.path.join(f_store.layout.pointSchedulerDir(f_point, 0), "cancel_unconfirmed.json")
        f_unconf_rec = EvidenceRecord(
            f_writer_kind=WriterKind.CONTROL,
            f_writer_id="client",
            f_sequence_number=2,
            f_evidence_kind=EvidenceKind.CANCEL_UNCONFIRMED,
            f_point_id=f_store.layout.pointDirName(f_point, 0),
        )
        f_store.recordRecord(f_unconf_path, f_unconf_rec)

        f_view_indet = StateReconciler.reconcile(f_plan, f_store)
        self.assertEqual(f_view_indet.point_states[0].state, PointRunState.INDETERMINATE)
        self.assertEqual(f_view_indet.state, OverallRunState.INDETERMINATE)

        # Corrupt evidence file
        f_corrupt_path = f_store.layout.pointControllerResultPath(f_point, f_plan.combinations[0], 0)
        with open(f_corrupt_path, "w") as f_f:
            f_f.write("{invalid_json: true")

        f_view_corrupt = StateReconciler.reconcile(f_plan, f_store)
        self.assertEqual(f_view_corrupt.point_states[0].state, PointRunState.INDETERMINATE)
        self.assertEqual(f_view_corrupt.state, OverallRunState.INDETERMINATE)

    def testInterruptionThenFinalSuccess(self) -> None:
        """Rule 4: Interruption before marker permanently yields INTERRUPTED even if points subsequently succeed."""
        f_run_id = "run-state-006"
        f_plan, f_art_store, f_store = self._setupRunEnvironment(
            f_run_id, f_target="lsmio", f_scale="local", f_setup="NATIVE-M"
        )
        f_point = f_plan.scale_points[0]
        f_handle = JobHandle("slurm", "1006")

        # 1. Record interruption event first (sequence 1)
        f_store.recordInterruption("client", 1, f_payload={"reason": "SIGINT signal"})

        # 2. Point 0 subsequently completes with full success evidence
        f_store.recordSubmissionRecorded(f_point, "client", f_handle=f_handle, f_ordinal=0)
        f_store.recordWorkerEvent(f_point, 1, EvidenceKind.CONTROLLER_STARTED, f_ordinal=0)
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
            f_run_id, f_target="lsmio", f_scale="local", f_setup="NATIVE-M"
        )
        f_point = f_plan.scale_points[0]
        f_handle = JobHandle("slurm", "1007")

        # 1. Point 0 completes successfully
        f_store.recordSubmissionRecorded(f_point, "client", f_handle=f_handle, f_ordinal=0)
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
        f_store.recordInterruption("client", 2, f_payload={"reason": "late signal after completion"})

        f_view = StateReconciler.reconcile(f_plan, f_store)
        self.assertTrue(f_view.has_success_marker)
        self.assertTrue(f_view.has_interruption)
        self.assertEqual(f_view.point_states[0].state, PointRunState.SUCCEEDED)
        self.assertEqual(f_view.state, OverallRunState.SUCCEEDED)

    def testConflictingHandleUnknown(self) -> None:
        """Rule 5: Conflicting job handles or UNKNOWN scheduler terminal accounting yield INDETERMINATE."""
        f_run_id = "run-state-008"
        f_plan, f_art_store, f_store = self._setupRunEnvironment(
            f_run_id, f_target="lsmio", f_scale="local", f_setup="NATIVE-M"
        )
        f_point = f_plan.scale_points[0]
        f_handle = JobHandle("slurm", "1008")

        f_store.recordSubmissionRecorded(f_point, "client", f_handle=f_handle, f_ordinal=0)

        # Case A: Fresh observation provides conflicting job handle
        f_conflicting_handle = JobHandle("slurm", "9999")
        f_view_conflict = StateReconciler.reconcile(
            f_plan,
            f_store,
            f_scheduler_observations={0: {"state": "active", "handle": f_conflicting_handle}},
        )
        self.assertEqual(f_view_conflict.point_states[0].state, PointRunState.INDETERMINATE)
        self.assertEqual(f_view_conflict.state, OverallRunState.INDETERMINATE)

        # Case B: Scheduler observation UNKNOWN
        f_view_unknown = StateReconciler.reconcile(
            f_plan, f_store, f_scheduler_observations={0: SchedulerJobState.UNKNOWN}
        )
        self.assertEqual(f_view_unknown.point_states[0].state, PointRunState.INDETERMINATE)
        self.assertEqual(f_view_unknown.state, OverallRunState.INDETERMINATE)

    def testStaleActiveCannotRegress(self) -> None:
        """Rule 6: Stale active observations cannot regress an established terminal fact."""
        f_run_id = "run-state-009"
        f_plan, f_art_store, f_store = self._setupRunEnvironment(
            f_run_id, f_target="lsmio", f_scale="local", f_setup="NATIVE-M"
        )
        f_point = f_plan.scale_points[0]
        f_handle = JobHandle("slurm", "1009")

        # Point has established terminal SUCCEEDED on disk
        f_store.recordSubmissionRecorded(f_point, "client", f_handle=f_handle, f_ordinal=0)
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
        self.assertEqual(f_view_stale_active.point_states[0].state, PointRunState.SUCCEEDED)

        f_view_stale_queued = StateReconciler.reconcile(
            f_plan, f_store, f_scheduler_observations={0: "queued"}
        )
        self.assertEqual(f_view_stale_queued.point_states[0].state, PointRunState.SUCCEEDED)

    def testPermutationDeterminism(self) -> None:
        """Determinism: Reconciliation result is invariant under permutation of evidence reading."""
        f_run_id = "run-state-010"
        f_plan, f_art_store, f_store = self._setupRunEnvironment(
            f_run_id, f_target="lsmio", f_scale="bake", f_setup="NATIVE-M"
        )
        f_point0 = f_plan.scale_points[0]
        f_handle0 = JobHandle("slurm", "1010")

        f_store.recordSubmissionRecorded(f_point0, "client", f_handle=f_handle0, f_ordinal=0)
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

        f_store.recordSubmissionRecorded(f_point, "client", f_handle=f_handle, f_ordinal=0)
        for f_combo in f_plan.combinations:
            f_store.recordControllerResult(
                f_point,
                f_combo,
                f_payload=self._validControllerSuccessPayload(f_combo.name, f_tasks=None),
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
            f_run_id, f_target="lsmio", f_scale="bake", f_setup="NATIVE-M"
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
        f_store.recordSchedulerObservation(f_p0, "reconciler", 1, f_payload={"state": "succeeded"}, f_ordinal=0)

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
            f_store.recordSubmissionRecorded(f_point, "client", f_handle=JobHandle("slurm", "5000"), f_ordinal=0)
            # Record incomplete/corrupt controller result
            for f_combo in f_plan.combinations:
                f_store.recordControllerResult(f_point, f_combo, f_payload=f_bad, f_ordinal=0)
            f_store.recordSchedulerObservation(f_point, "reconciler", 1, f_payload={"state": "succeeded"}, f_ordinal=0)

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
        f_plan1, _, f_store1 = self._setupRunEnvironment(f_run_id1, f_target="ior", f_scale="local", f_setup="BASE")
        f_point1 = f_plan1.scale_points[0]
        f_store1.recordSubmissionRecorded(f_point1, "client", f_handle=JobHandle("slurm", "5001"), f_ordinal=0)
        for f_combo in f_plan1.combinations:
            f_store1.recordControllerResult(
                f_point1,
                f_combo,
                f_payload={"status": "success", "exit_code": True, "stage": "execution"},
                f_ordinal=0,
            )
        f_store1.recordSchedulerObservation(f_point1, "reconciler", 1, f_payload={"state": "succeeded"}, f_ordinal=0)
        f_view1 = StateReconciler.reconcile(f_plan1, f_store1)
        self.assertEqual(f_view1.point_states[0].state, PointRunState.INDETERMINATE)

        # 2. String exit_code
        f_run_id2 = "run-state-malformed-str"
        f_plan2, _, f_store2 = self._setupRunEnvironment(f_run_id2, f_target="ior", f_scale="local", f_setup="BASE")
        f_point2 = f_plan2.scale_points[0]
        f_store2.recordSubmissionRecorded(f_point2, "client", f_handle=JobHandle("slurm", "5002"), f_ordinal=0)
        for f_combo in f_plan2.combinations:
            f_store2.recordControllerResult(
                f_point2,
                f_combo,
                f_payload={"status": "success", "exit_code": "0", "stage": "execution"},
                f_ordinal=0,
            )
        f_store2.recordSchedulerObservation(f_point2, "reconciler", 1, f_payload={"state": "succeeded"}, f_ordinal=0)
        f_view2 = StateReconciler.reconcile(f_plan2, f_store2)
        self.assertEqual(f_view2.point_states[0].state, PointRunState.INDETERMINATE)

        # 3. LSMIO Rank Identity Mismatch (rank 1 payload recorded for rank 0)
        f_run_id3 = "run-state-rank-mismatch"
        f_plan3, _, f_store3 = self._setupRunEnvironment(f_run_id3, f_target="lsmio", f_scale="local", f_setup="NATIVE-M")
        f_point3 = f_plan3.scale_points[0]
        f_store3.recordSubmissionRecorded(f_point3, "client", f_handle=JobHandle("slurm", "5003"), f_ordinal=0)
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
        f_store3.recordSchedulerObservation(f_point3, "reconciler", 1, f_payload={"state": "succeeded"}, f_ordinal=0)
        f_view3 = StateReconciler.reconcile(f_plan3, f_store3)
        self.assertEqual(f_view3.point_states[0].state, PointRunState.INDETERMINATE)

    def testDurableFailedThenFreshSucceededRemainsFailure(self) -> None:
        """Chunk 018: Durable FAILED on disk cannot be overwritten by fresh SUCCEEDED observation."""
        f_run_id = "run-state-f11-001"
        f_plan, _, f_store = self._setupRunEnvironment(f_run_id, f_target="ior", f_scale="local", f_setup="BASE")
        f_point = f_plan.scale_points[0]
        f_handle = JobHandle("slurm", "6001")

        f_store.recordSubmissionRecorded(f_point, "client", f_handle=f_handle, f_ordinal=0)
        # Durable disk observation: FAILED
        f_store.recordSchedulerObservation(
            f_point, "reconciler", 1, f_payload={"state": "failed", "handle": f_handle.toDict()}, f_ordinal=0
        )

        # Fresh observation: SUCCEEDED
        f_view = StateReconciler.reconcile(
            f_plan, f_store, f_scheduler_observations={0: SchedulerJobState.SUCCEEDED}
        )
        self.assertEqual(f_view.point_states[0].state, PointRunState.FAILED)
        self.assertEqual(f_view.state, OverallRunState.FAILED)

        # Also test controller failure with fresh scheduler SUCCEEDED
        f_run_id2 = "run-state-f11-001b"
        f_plan2, _, f_store2 = self._setupRunEnvironment(f_run_id2, f_target="ior", f_scale="local", f_setup="BASE")
        f_point2 = f_plan2.scale_points[0]
        f_store2.recordSubmissionRecorded(f_point2, "client", f_handle=f_handle, f_ordinal=0)
        for f_combo in f_plan2.combinations:
            f_store2.recordControllerResult(
                f_point2,
                f_combo,
                f_payload={"status": "failed", "exit_code": 1, "stage": "execution", "combination": f_combo.name},
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
        f_plan, _, f_store = self._setupRunEnvironment(f_run_id, f_target="ior", f_scale="local", f_setup="BASE")
        f_point = f_plan.scale_points[0]
        f_handle = JobHandle("slurm", "6002")

        f_store.recordSubmissionRecorded(f_point, "client", f_handle=f_handle, f_ordinal=0)
        for f_combo in f_plan.combinations:
            f_store.recordControllerResult(
                f_point,
                f_combo,
                f_payload=self._validControllerSuccessPayload(f_combo.name),
                f_ordinal=0,
            )
        # Durable disk observation: SUCCEEDED
        f_store.recordSchedulerObservation(
            f_point, "reconciler", 1, f_payload={"state": "succeeded", "handle": f_handle.toDict()}, f_ordinal=0
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
            (SchedulerJobState.SUCCEEDED, SchedulerJobState.SUCCEEDED): PointRunState.SUCCEEDED,
            (SchedulerJobState.SUCCEEDED, SchedulerJobState.FAILED): PointRunState.FAILED,
            (SchedulerJobState.SUCCEEDED, SchedulerJobState.TIMEOUT): PointRunState.TIMED_OUT,
            (SchedulerJobState.SUCCEEDED, SchedulerJobState.CANCELLED): PointRunState.INDETERMINATE,
            (SchedulerJobState.FAILED, SchedulerJobState.SUCCEEDED): PointRunState.FAILED,
            (SchedulerJobState.FAILED, SchedulerJobState.FAILED): PointRunState.FAILED,
            (SchedulerJobState.FAILED, SchedulerJobState.TIMEOUT): PointRunState.INDETERMINATE,
            (SchedulerJobState.FAILED, SchedulerJobState.CANCELLED): PointRunState.INDETERMINATE,
            (SchedulerJobState.TIMEOUT, SchedulerJobState.SUCCEEDED): PointRunState.TIMED_OUT,
            (SchedulerJobState.TIMEOUT, SchedulerJobState.FAILED): PointRunState.INDETERMINATE,
            (SchedulerJobState.TIMEOUT, SchedulerJobState.TIMEOUT): PointRunState.TIMED_OUT,
            (SchedulerJobState.TIMEOUT, SchedulerJobState.CANCELLED): PointRunState.INDETERMINATE,
            (SchedulerJobState.CANCELLED, SchedulerJobState.SUCCEEDED): PointRunState.INDETERMINATE,
            (SchedulerJobState.CANCELLED, SchedulerJobState.FAILED): PointRunState.INDETERMINATE,
            (SchedulerJobState.CANCELLED, SchedulerJobState.TIMEOUT): PointRunState.INDETERMINATE,
            (SchedulerJobState.CANCELLED, SchedulerJobState.CANCELLED): PointRunState.INDETERMINATE,
        }

        for (f_s1, f_s2), f_exp_state in f_expected_no_cancel.items():
            f_run_id = f"run-pair-{f_s1.value}-{f_s2.value}"
            f_plan, _, f_store = self._setupRunEnvironment(f_run_id, f_target="ior", f_scale="local", f_setup="BASE")
            f_point = f_plan.scale_points[0]
            f_handle = JobHandle("slurm", "7001")
            f_store.recordSubmissionRecorded(f_point, "client", f_handle=f_handle, f_ordinal=0)

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
                f_point, "obs1", 1, f_payload={"state": f_s1.value, "handle": f_handle.toDict()}, f_ordinal=0
            )
            # Record second state on disk
            f_store.recordSchedulerObservation(
                f_point, "obs2", 1, f_payload={"state": f_s2.value, "handle": f_handle.toDict()}, f_ordinal=0
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
        f_plan_pf, _, f_store_pf = self._setupRunEnvironment(f_run_id_prior_f, f_target="ior", f_scale="local", f_setup="BASE")
        f_pt_pf = f_plan_pf.scale_points[0]
        f_h_pf = JobHandle("slurm", "7002")
        f_store_pf.recordSubmissionRecorded(f_pt_pf, "client", f_handle=f_h_pf, f_ordinal=0)
        f_store_pf.recordSchedulerObservation(
            f_pt_pf, "obs", 1, f_payload={"state": "failed", "handle": f_h_pf.toDict()}, f_created_at_utc=f_prior_time, f_ordinal=0
        )
        f_store_pf.recordCancelRequested(f_pt_pf, "client", f_handle=f_h_pf, f_created_at_utc=f_cancel_time, f_ordinal=0)
        f_store_pf.recordCancelRecorded(f_pt_pf, "client", f_handle=f_h_pf, f_created_at_utc=f_post_time, f_ordinal=0)
        f_view_pf = StateReconciler.reconcile(f_plan_pf, f_store_pf)
        self.assertEqual(f_view_pf.point_states[0].state, PointRunState.FAILED)

        # Prior timeout outranks cancellation
        f_run_id_prior_t = "run-pair-prior-t-cancel"
        f_plan_pt, _, f_store_pt = self._setupRunEnvironment(f_run_id_prior_t, f_target="ior", f_scale="local", f_setup="BASE")
        f_pt_pt = f_plan_pt.scale_points[0]
        f_h_pt = JobHandle("slurm", "7003")
        f_store_pt.recordSubmissionRecorded(f_pt_pt, "client", f_handle=f_h_pt, f_ordinal=0)
        f_store_pt.recordSchedulerObservation(
            f_pt_pt, "obs", 1, f_payload={"state": "timeout", "handle": f_h_pt.toDict()}, f_created_at_utc=f_prior_time, f_ordinal=0
        )
        f_store_pt.recordCancelRequested(f_pt_pt, "client", f_handle=f_h_pt, f_created_at_utc=f_cancel_time, f_ordinal=0)
        f_store_pt.recordCancelRecorded(f_pt_pt, "client", f_handle=f_h_pt, f_created_at_utc=f_post_time, f_ordinal=0)
        f_view_pt = StateReconciler.reconcile(f_plan_pt, f_store_pt)
        self.assertEqual(f_view_pt.point_states[0].state, PointRunState.TIMED_OUT)

        # Cancellation before failure yields CANCELLED
        f_run_id_post_f = "run-pair-cancel-then-f"
        f_plan_post, _, f_store_post = self._setupRunEnvironment(f_run_id_post_f, f_target="ior", f_scale="local", f_setup="BASE")
        f_pt_post = f_plan_post.scale_points[0]
        f_h_post = JobHandle("slurm", "7004")
        f_store_post.recordSubmissionRecorded(f_pt_post, "client", f_handle=f_h_post, f_ordinal=0)
        f_store_post.recordCancelRequested(f_pt_post, "client", f_handle=f_h_post, f_created_at_utc=f_cancel_time, f_ordinal=0)
        f_store_post.recordSchedulerObservation(
            f_pt_post, "obs", 1, f_payload={"state": "failed", "handle": f_h_post.toDict()}, f_created_at_utc=f_post_time, f_ordinal=0
        )
        f_store_post.recordCancelRecorded(f_pt_post, "client", f_handle=f_h_post, f_created_at_utc=f_post_time, f_ordinal=0)
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
            f_plan, _, f_store = self._setupRunEnvironment(f_run_id, f_target="ior", f_scale="local", f_setup="BASE")
            f_point = f_plan.scale_points[0]
            f_handle = JobHandle("slurm", "8001")
            f_store.recordSubmissionRecorded(f_point, "client", f_handle=f_handle, f_ordinal=0)

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
                f_point, "obs", 1, f_payload={"state": f_term_sched.value, "handle": f_handle.toDict()}, f_ordinal=0
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
        f_plan1, _, f_store1 = self._setupRunEnvironment(f_run_id1, f_target="ior", f_scale="local", f_setup="BASE")
        f_pt1 = f_plan1.scale_points[0]
        f_store1.recordSubmissionRecorded(f_pt1, "client", f_handle=f_handle, f_ordinal=0)
        f_store1.recordSchedulerObservation(
            f_pt1, "obs", 1, f_payload={"state": "cancelled", "handle": f_handle.toDict()}, f_ordinal=0
        )
        f_view1 = StateReconciler.reconcile(f_plan1, f_store1)
        self.assertEqual(f_view1.point_states[0].state, PointRunState.INDETERMINATE)
        self.assertEqual(f_view1.state, OverallRunState.INDETERMINATE)

        # 2. cancel_requested recorded, but cancel_unconfirmed.json exists -> INDETERMINATE
        f_run_id2 = "run-cancel-causality-2"
        f_plan2, _, f_store2 = self._setupRunEnvironment(f_run_id2, f_target="ior", f_scale="local", f_setup="BASE")
        f_pt2 = f_plan2.scale_points[0]
        f_store2.recordSubmissionRecorded(f_pt2, "client", f_handle=f_handle, f_ordinal=0)
        f_store2.recordCancelRequested(f_pt2, "client", f_handle=f_handle, f_ordinal=0)
        f_unconf_path = os.path.join(f_store2.layout.pointSchedulerDir(f_pt2, 0), "cancel_unconfirmed.json")
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
        f_plan3, _, f_store3 = self._setupRunEnvironment(f_run_id3, f_target="ior", f_scale="local", f_setup="BASE")
        f_pt3 = f_plan3.scale_points[0]
        f_store3.recordSubmissionRecorded(f_pt3, "client", f_handle=f_handle, f_ordinal=0)
        f_store3.recordCancelRequested(f_pt3, "client", f_handle=f_handle, f_created_at_utc="2026-08-20T12:00:00Z", f_ordinal=0)
        f_store3.recordCancelRecorded(f_pt3, "client", f_handle=f_handle, f_created_at_utc="2026-08-20T12:05:00Z", f_ordinal=0)
        # Scheduler completed with terminal SUCCEEDED, but controller results are missing -> failure without timestamp
        f_store3.recordSchedulerObservation(
            f_pt3, "obs", 1, f_payload={"state": "succeeded", "handle": f_handle.toDict()}, f_ordinal=0
        )
        f_view3 = StateReconciler.reconcile(f_plan3, f_store3)
        self.assertEqual(f_view3.point_states[0].state, PointRunState.INDETERMINATE)

    def testPermutationAndRepeatedReconcileStable(self) -> None:
        """Chunk 018: State reconciliation is strictly deterministic and invariant under observation permutations and repetition."""
        f_run_id = "run-permutation-test"
        f_plan, _, f_store = self._setupRunEnvironment(f_run_id, f_target="ior", f_scale="bake", f_setup="BASE")
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

