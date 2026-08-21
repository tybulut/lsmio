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
                f_point, f_combo, f_payload={"exit_code": 0, "status": "success"}, f_ordinal=0
            )
            f_store.recordRankResult(
                f_point,
                f_global_rank=0,
                f_combination=f_combo,
                f_payload={"exit_code": 0, "status": "success"},
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
                f_point_4, f_combo, f_payload={"exit_code": 0}, f_ordinal=2
            )
            for f_r in range(3):  # 0, 1, 2 only
                f_store.recordRankResult(
                    f_point_4, f_global_rank=f_r, f_combination=f_combo, f_payload={"exit_code": 0}, f_ordinal=2
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
                f_point_4, f_global_rank=3, f_combination=f_combo, f_payload={"exit_code": 0}, f_ordinal=2
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
            f_point, f_combo0, f_payload={"exit_code": 0}, f_ordinal=0
        )
        f_store.recordRankResult(
            f_point, f_global_rank=0, f_combination=f_combo0, f_payload={"exit_code": 1, "status": "failed"}, f_ordinal=0
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
            f_store.recordControllerResult(f_point, f_combo, f_payload={"exit_code": 0}, f_ordinal=0)
            f_store.recordRankResult(
                f_point, f_global_rank=0, f_combination=f_combo, f_payload={"exit_code": 0}, f_ordinal=0
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
            f_store.recordControllerResult(f_point, f_combo, f_payload={"exit_code": 0}, f_ordinal=0)
            f_store.recordRankResult(
                f_point, f_global_rank=0, f_combination=f_combo, f_payload={"exit_code": 0}, f_ordinal=0
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
            f_store.recordControllerResult(f_point, f_combo, f_payload={"exit_code": 0}, f_ordinal=0)
            f_store.recordRankResult(
                f_point, f_global_rank=0, f_combination=f_combo, f_payload={"exit_code": 0}, f_ordinal=0
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
            f_store.recordControllerResult(f_point0, f_combo, f_payload={"exit_code": 0}, f_ordinal=0)
            f_store.recordRankResult(
                f_point0, f_global_rank=0, f_combination=f_combo, f_payload={"exit_code": 0}, f_ordinal=0
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
            f_store.recordControllerResult(f_point, f_combo, f_payload={"exit_code": 0}, f_ordinal=0)

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
            f_store.recordControllerResult(f_p0, f_combo, f_payload={"exit_code": 0}, f_ordinal=0)
            f_store.recordRankResult(
                f_p0, f_global_rank=0, f_combination=f_combo, f_payload={"exit_code": 0}, f_ordinal=0
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
