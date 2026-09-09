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

from enum import Enum
import json
import os
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple, Union

from lsmiotool.lib.evidence import (
    EvidenceCorruptionError,
    EvidenceError,
    EvidenceKind,
    EvidenceRecord,
    EvidenceSchemaError,
    EvidenceSequenceError,
    EvidenceStore,
    JobHandle,
    ResultPayloadValidator,
    WriterKind,
)
from lsmiotool.lib.run import (
    Combination,
    RunPlan,
    ScalePoint,
    ScheduledPointResources,
)


class StateError(Exception):
    """Base exception for state reconciliation errors."""

    pass


class SchedulerJobState(Enum):
    """Normalized external scheduler job states."""

    QUEUED = "queued"
    ACTIVE = "active"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"

    @property
    def isTerminal(self) -> bool:
        return self in (
            SchedulerJobState.SUCCEEDED,
            SchedulerJobState.FAILED,
            SchedulerJobState.CANCELLED,
            SchedulerJobState.TIMEOUT,
        )

    @property
    def is_terminal(self) -> bool:
        return self.isTerminal

    @property
    def isSuccess(self) -> bool:
        return self == SchedulerJobState.SUCCEEDED

    @property
    def is_success(self) -> bool:
        return self.isSuccess


class PointRunState(Enum):
    """Authoritative execution states for an individual scale point."""

    NOT_STARTED = "not_started"
    SUBMITTED = "submitted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    INTERRUPTED = "interrupted"
    INDETERMINATE = "indeterminate"

    @property
    def isTerminal(self) -> bool:
        return self in (
            PointRunState.SUCCEEDED,
            PointRunState.FAILED,
            PointRunState.CANCELLED,
            PointRunState.TIMED_OUT,
            PointRunState.INTERRUPTED,
            PointRunState.INDETERMINATE,
        )

    @property
    def is_terminal(self) -> bool:
        return self.isTerminal

    @property
    def isSuccess(self) -> bool:
        return self == PointRunState.SUCCEEDED

    @property
    def is_success(self) -> bool:
        return self.isSuccess


class OverallRunState(Enum):
    """Authoritative execution states for an entire benchmark run."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    INTERRUPTED = "interrupted"
    INDETERMINATE = "indeterminate"

    @property
    def isTerminal(self) -> bool:
        return self in (
            OverallRunState.SUCCEEDED,
            OverallRunState.FAILED,
            OverallRunState.CANCELLED,
            OverallRunState.TIMED_OUT,
            OverallRunState.INTERRUPTED,
            OverallRunState.INDETERMINATE,
        )

    @property
    def is_terminal(self) -> bool:
        return self.isTerminal

    @property
    def isSuccess(self) -> bool:
        return self == OverallRunState.SUCCEEDED

    @property
    def is_success(self) -> bool:
        return self.isSuccess


class PointStateView:
    """Immutable view of a scale point's authoritative execution state."""

    __slots__ = (
        "m_point_id",
        "m_ordinal",
        "m_scale_point",
        "m_state",
        "m_handle",
        "m_scheduler_state",
        "m_combinations_completed",
        "m_combinations_failed",
        "m_combinations_missing",
        "m_diagnostics",
        "_frozen",
    )

    def __init__(
        self,
        f_point_id: str,
        f_ordinal: int,
        f_scale_point: ScalePoint,
        f_state: PointRunState,
        f_handle: Optional[JobHandle] = None,
        f_scheduler_state: Optional[SchedulerJobState] = None,
        f_combinations_completed: Sequence[str] = (),
        f_combinations_failed: Sequence[str] = (),
        f_combinations_missing: Sequence[str] = (),
        f_diagnostics: Sequence[str] = (),
    ) -> None:
        if not isinstance(f_point_id, str) or not f_point_id.strip():
            raise StateError(
                f"point_id must be a non-empty string, got: {f_point_id!r}"
            )
        if not isinstance(f_ordinal, int) or f_ordinal < 0:
            raise StateError(
                f"ordinal must be a non-negative integer, got: {f_ordinal!r}"
            )
        if not isinstance(f_scale_point, ScalePoint):
            raise StateError(
                f"scale_point must be ScalePoint, got: {type(f_scale_point).__name__}"
            )
        if not isinstance(f_state, PointRunState):
            raise StateError(
                f"state must be PointRunState, got: {type(f_state).__name__}"
            )
        if f_handle is not None and not isinstance(f_handle, JobHandle):
            raise StateError(
                f"handle must be JobHandle or None, got: {type(f_handle).__name__}"
            )
        if f_scheduler_state is not None and not isinstance(
            f_scheduler_state, SchedulerJobState
        ):
            raise StateError(
                f"scheduler_state must be SchedulerJobState or None, got: {type(f_scheduler_state).__name__}"
            )

        super().__setattr__("m_point_id", f_point_id.strip())
        super().__setattr__("m_ordinal", f_ordinal)
        super().__setattr__("m_scale_point", f_scale_point)
        super().__setattr__("m_state", f_state)
        super().__setattr__("m_handle", f_handle)
        super().__setattr__("m_scheduler_state", f_scheduler_state)
        super().__setattr__(
            "m_combinations_completed",
            tuple(str(f_c) for f_c in f_combinations_completed),
        )
        super().__setattr__(
            "m_combinations_failed", tuple(str(f_c) for f_c in f_combinations_failed)
        )
        super().__setattr__(
            "m_combinations_missing", tuple(str(f_c) for f_c in f_combinations_missing)
        )
        super().__setattr__("m_diagnostics", tuple(str(f_d) for f_d in f_diagnostics))
        super().__setattr__("_frozen", True)

    def __setattr__(self, f_key: str, f_value: Any) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"Cannot modify immutable {self.__class__.__name__}")
        super().__setattr__(f_key, f_value)

    def __delattr__(self, f_key: str) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(
                f"Cannot delete attribute from immutable {self.__class__.__name__}"
            )
        super().__delattr__(f_key)

    @property
    def pointId(self) -> str:
        return self.m_point_id

    @property
    def point_id(self) -> str:
        return self.m_point_id

    @property
    def ordinal(self) -> int:
        return self.m_ordinal

    @property
    def scalePoint(self) -> ScalePoint:
        return self.m_scale_point

    @property
    def scale_point(self) -> ScalePoint:
        return self.m_scale_point

    @property
    def state(self) -> PointRunState:
        return self.m_state

    @property
    def handle(self) -> Optional[JobHandle]:
        return self.m_handle

    @property
    def schedulerState(self) -> Optional[SchedulerJobState]:
        return self.m_scheduler_state

    @property
    def scheduler_state(self) -> Optional[SchedulerJobState]:
        return self.m_scheduler_state

    @property
    def combinationsCompleted(self) -> Tuple[str, ...]:
        return self.m_combinations_completed

    @property
    def combinations_completed(self) -> Tuple[str, ...]:
        return self.m_combinations_completed

    @property
    def combinationsFailed(self) -> Tuple[str, ...]:
        return self.m_combinations_failed

    @property
    def combinations_failed(self) -> Tuple[str, ...]:
        return self.m_combinations_failed

    @property
    def combinationsMissing(self) -> Tuple[str, ...]:
        return self.m_combinations_missing

    @property
    def combinations_missing(self) -> Tuple[str, ...]:
        return self.m_combinations_missing

    @property
    def diagnostics(self) -> Tuple[str, ...]:
        return self.m_diagnostics

    @property
    def isTerminal(self) -> bool:
        return self.m_state.isTerminal

    @property
    def is_terminal(self) -> bool:
        return self.m_state.isTerminal

    @property
    def isSuccess(self) -> bool:
        return self.m_state.isSuccess

    @property
    def is_success(self) -> bool:
        return self.m_state.isSuccess

    def toDict(self) -> Dict[str, Any]:
        return {
            "point_id": self.m_point_id,
            "ordinal": self.m_ordinal,
            "scale_point": self.m_scale_point.toDict(),
            "state": self.m_state.value,
            "handle": self.m_handle.toDict() if self.m_handle else None,
            "scheduler_state": self.m_scheduler_state.value
            if self.m_scheduler_state
            else None,
            "combinations_completed": list(self.m_combinations_completed),
            "combinations_failed": list(self.m_combinations_failed),
            "combinations_missing": list(self.m_combinations_missing),
            "diagnostics": list(self.m_diagnostics),
        }

    def __repr__(self) -> str:
        return (
            f"PointStateView(point_id={self.m_point_id!r}, "
            f"ordinal={self.m_ordinal}, "
            f"state={self.m_state.value!r}, "
            f"handle={self.m_handle!r}, "
            f"scheduler_state={self.m_scheduler_state.value if self.m_scheduler_state else None!r})"
        )

    def __eq__(self, f_other: Any) -> bool:
        if isinstance(f_other, PointStateView):
            return (
                self.m_point_id == f_other.m_point_id
                and self.m_ordinal == f_other.m_ordinal
                and self.m_scale_point == f_other.m_scale_point
                and self.m_state == f_other.m_state
                and self.m_handle == f_other.m_handle
                and self.m_scheduler_state == f_other.m_scheduler_state
                and self.m_combinations_completed == f_other.m_combinations_completed
                and self.m_combinations_failed == f_other.m_combinations_failed
                and self.m_combinations_missing == f_other.m_combinations_missing
                and self.m_diagnostics == f_other.m_diagnostics
            )
        return False


class RunStateView:
    """Immutable view of an overall benchmark run's authoritative execution state."""

    __slots__ = (
        "m_run_id",
        "m_state",
        "m_point_states",
        "m_active_point_ordinal",
        "m_diagnostics",
        "m_has_interruption",
        "m_has_success_marker",
        "_frozen",
    )

    def __init__(
        self,
        f_run_id: str,
        f_state: OverallRunState,
        f_point_states: Sequence[PointStateView] = (),
        f_active_point_ordinal: Optional[int] = None,
        f_diagnostics: Sequence[str] = (),
        f_has_interruption: bool = False,
        f_has_success_marker: bool = False,
    ) -> None:
        if not isinstance(f_run_id, str) or not f_run_id.strip():
            raise StateError(f"run_id must be a non-empty string, got: {f_run_id!r}")
        if not isinstance(f_state, OverallRunState):
            raise StateError(
                f"state must be OverallRunState, got: {type(f_state).__name__}"
            )
        if f_active_point_ordinal is not None and (
            not isinstance(f_active_point_ordinal, int) or f_active_point_ordinal < 0
        ):
            raise StateError(
                f"active_point_ordinal must be non-negative integer or None, got: {f_active_point_ordinal!r}"
            )

        super().__setattr__("m_run_id", f_run_id.strip())
        super().__setattr__("m_state", f_state)
        super().__setattr__("m_point_states", tuple(f_point_states))
        super().__setattr__("m_active_point_ordinal", f_active_point_ordinal)
        super().__setattr__("m_diagnostics", tuple(str(f_d) for f_d in f_diagnostics))
        super().__setattr__("m_has_interruption", bool(f_has_interruption))
        super().__setattr__("m_has_success_marker", bool(f_has_success_marker))
        super().__setattr__("_frozen", True)

    def __setattr__(self, f_key: str, f_value: Any) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"Cannot modify immutable {self.__class__.__name__}")
        super().__setattr__(f_key, f_value)

    def __delattr__(self, f_key: str) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(
                f"Cannot delete attribute from immutable {self.__class__.__name__}"
            )
        super().__delattr__(f_key)

    @property
    def runId(self) -> str:
        return self.m_run_id

    @property
    def run_id(self) -> str:
        return self.m_run_id

    @property
    def state(self) -> OverallRunState:
        return self.m_state

    @property
    def pointStates(self) -> Tuple[PointStateView, ...]:
        return self.m_point_states

    @property
    def point_states(self) -> Tuple[PointStateView, ...]:
        return self.m_point_states

    @property
    def activePointOrdinal(self) -> Optional[int]:
        return self.m_active_point_ordinal

    @property
    def active_point_ordinal(self) -> Optional[int]:
        return self.m_active_point_ordinal

    @property
    def diagnostics(self) -> Tuple[str, ...]:
        return self.m_diagnostics

    @property
    def hasInterruption(self) -> bool:
        return self.m_has_interruption

    @property
    def has_interruption(self) -> bool:
        return self.m_has_interruption

    @property
    def hasSuccessMarker(self) -> bool:
        return self.m_has_success_marker

    @property
    def has_success_marker(self) -> bool:
        return self.m_has_success_marker

    @property
    def isTerminal(self) -> bool:
        return self.m_state.isTerminal

    @property
    def is_terminal(self) -> bool:
        return self.m_state.isTerminal

    @property
    def isSuccess(self) -> bool:
        return self.m_state.isSuccess

    @property
    def is_success(self) -> bool:
        return self.m_state.isSuccess

    def toDict(self) -> Dict[str, Any]:
        return {
            "run_id": self.m_run_id,
            "state": self.m_state.value,
            "active_point_ordinal": self.m_active_point_ordinal,
            "has_interruption": self.m_has_interruption,
            "has_success_marker": self.m_has_success_marker,
            "diagnostics": list(self.m_diagnostics),
            "point_states": [f_ps.toDict() for f_ps in self.m_point_states],
        }

    def __repr__(self) -> str:
        return (
            f"RunStateView(run_id={self.m_run_id!r}, "
            f"state={self.m_state.value!r}, "
            f"active_point_ordinal={self.m_active_point_ordinal}, "
            f"points_count={len(self.m_point_states)})"
        )

    def __eq__(self, f_other: Any) -> bool:
        if isinstance(f_other, RunStateView):
            return (
                self.m_run_id == f_other.m_run_id
                and self.m_state == f_other.m_state
                and self.m_point_states == f_other.m_point_states
                and self.m_active_point_ordinal == f_other.m_active_point_ordinal
                and self.m_diagnostics == f_other.m_diagnostics
                and self.m_has_interruption == f_other.m_has_interruption
                and self.m_has_success_marker == f_other.m_has_success_marker
            )
        return False


class StateReconciler:
    """Authoritative state reconciler enforcing the 6 approved architecture precedence rules."""

    @staticmethod
    def reconcile(
        f_plan: RunPlan,
        f_evidence_store: EvidenceStore,
        f_scheduler_observations: Optional[Mapping[Any, Any]] = None,
    ) -> RunStateView:
        """Deterministically derives authoritative run and point state from plan, evidence, and scheduler observations."""
        if not isinstance(f_plan, RunPlan):
            raise StateError(f"f_plan must be a RunPlan, got: {type(f_plan).__name__}")
        if not isinstance(f_evidence_store, EvidenceStore):
            raise StateError(
                f"f_evidence_store must be EvidenceStore, got: {type(f_evidence_store).__name__}"
            )

        f_run_diagnostics: List[str] = []
        f_layout = f_evidence_store.layout

        # -------------------------------------------------------------------------
        # 1. Read Control Stream Events
        # -------------------------------------------------------------------------
        f_control_corrupt = False
        f_whole_run_succeeded_events: List[EvidenceRecord] = []
        f_interrupted_events: List[EvidenceRecord] = []

        f_ctrl_events_dir = f_layout.controlEventsDir
        if os.path.exists(f_ctrl_events_dir):
            f_writer_dirs = [
                f_d
                for f_d in os.listdir(f_ctrl_events_dir)
                if os.path.isdir(os.path.join(f_ctrl_events_dir, f_d))
            ]
            # Lexical sort for permutation-independent determinism
            f_writer_dirs.sort()

            for f_writer in f_writer_dirs:
                try:
                    f_records = f_evidence_store.readControlEvents(f_writer)
                    for f_rec in f_records:
                        if f_rec.evidence_kind == EvidenceKind.WHOLE_RUN_SUCCEEDED:
                            f_whole_run_succeeded_events.append(f_rec)
                        elif f_rec.evidence_kind == EvidenceKind.INTERRUPTED:
                            f_interrupted_events.append(f_rec)
                except (
                    EvidenceSequenceError,
                    EvidenceCorruptionError,
                    EvidenceSchemaError,
                ) as f_err:
                    f_control_corrupt = True
                    f_run_diagnostics.append(
                        f"Control stream error for writer '{f_writer}': {f_err}"
                    )

        # Deterministic sorting across all writers
        f_whole_run_succeeded_events.sort(
            key=lambda r: (r.created_at_utc, r.writer_id, r.sequence_number)
        )
        f_interrupted_events.sort(
            key=lambda r: (r.created_at_utc, r.writer_id, r.sequence_number)
        )

        # Determine Temporal Precedence between WHOLE_RUN_SUCCEEDED and INTERRUPTED (Rule 1 & 4)
        f_has_interruption = len(f_interrupted_events) > 0
        f_has_success_marker = len(f_whole_run_succeeded_events) > 0
        f_interrupted_first = False

        if f_has_interruption:
            if not f_has_success_marker:
                f_interrupted_first = True
            else:
                # Both exist: check ordering
                # Find earliest whole_run_succeeded and earliest interrupted
                f_marker = f_whole_run_succeeded_events[0]
                f_interrupt = f_interrupted_events[0]

                if f_marker.writer_id == f_interrupt.writer_id:
                    # Same writer stream: monotonic sequence number is exact causal order
                    if f_interrupt.sequence_number < f_marker.sequence_number:
                        f_interrupted_first = True
                    else:
                        f_interrupted_first = False
                else:
                    # Cross-writer: compare ISO UTC timestamp string
                    if f_interrupt.created_at_utc < f_marker.created_at_utc:
                        f_interrupted_first = True
                    else:
                        f_interrupted_first = False

        # -------------------------------------------------------------------------
        # 2. Reconcile Each Scale Point
        # -------------------------------------------------------------------------
        f_point_views: List[PointStateView] = []
        f_is_lsmio = f_plan.request.target.lower() == "lsmio"

        for f_idx, f_scale_point in enumerate(f_plan.scale_points):
            f_point_name = f_layout.pointDirName(f_scale_point, f_idx)
            f_point_diagnostics: List[str] = []
            f_conflicting_handles = False
            f_corrupt_evidence = False

            # a) Read submission records
            f_sub_records: Dict[str, Optional[EvidenceRecord]] = {}
            try:
                f_sub_records = f_evidence_store.readSubmissionRecords(
                    f_scale_point, f_ordinal=f_idx
                )
            except (EvidenceError, OSError) as f_err:
                f_corrupt_evidence = True
                f_point_diagnostics.append(f"Submission records read error: {f_err}")

            f_sub_req = f_sub_records.get("submission_requested")
            f_sub_disp = f_sub_records.get("submission_dispatched")
            f_sub_rec = f_sub_records.get("submission_recorded")
            f_cancel_req = f_sub_records.get("cancel_requested")
            f_cancel_rec = f_sub_records.get("cancel_recorded")

            # Check for cancel_unconfirmed.json in point scheduler directory
            f_cancel_unconf_path = os.path.join(
                f_layout.pointSchedulerDir(f_scale_point, f_idx),
                "cancel_unconfirmed.json",
            )
            f_cancel_unconf = f_evidence_store.readRecordIfExists(f_cancel_unconf_path)

            # Extract persisted handle
            f_handle: Optional[JobHandle] = None
            if f_sub_rec is not None:
                try:
                    f_handle_data = f_sub_rec.payload.get("handle")
                    if isinstance(f_handle_data, dict):
                        f_handle = JobHandle.fromDict(f_handle_data)
                except Exception as f_err:
                    f_corrupt_evidence = True
                    f_point_diagnostics.append(
                        f"Corrupt JobHandle in submission_recorded: {f_err}"
                    )

            # b) Read scheduler observations from disk
            f_disk_observations: List[EvidenceRecord] = []
            f_obs_base_dir = os.path.join(
                f_layout.pointSchedulerDir(f_scale_point, f_idx), "observations"
            )
            if os.path.exists(f_obs_base_dir):
                f_obs_writers = [
                    f_d
                    for f_d in os.listdir(f_obs_base_dir)
                    if os.path.isdir(os.path.join(f_obs_base_dir, f_d))
                ]
                f_obs_writers.sort()
                for f_obs_w in f_obs_writers:
                    try:
                        f_recs = f_evidence_store.readSchedulerObservations(
                            f_scale_point, f_obs_w, f_ordinal=f_idx
                        )
                        f_disk_observations.extend(f_recs)
                    except (
                        EvidenceSequenceError,
                        EvidenceCorruptionError,
                        EvidenceSchemaError,
                    ) as f_err:
                        f_corrupt_evidence = True
                        f_point_diagnostics.append(
                            f"Observation read error for writer '{f_obs_w}': {f_err}"
                        )

            # Sort disk observations deterministically
            f_disk_observations.sort(
                key=lambda r: (r.created_at_utc, r.writer_id, r.sequence_number)
            )

            # Check handle consistency and payload validity across disk observations
            for f_obs in f_disk_observations:
                if not isinstance(f_obs.payload, dict):
                    f_corrupt_evidence = True
                    f_point_diagnostics.append(
                        f"Corrupt observation payload: {f_obs.payload!r}"
                    )
                    continue
                f_obs_h = f_obs.payload.get("handle")
                if isinstance(f_obs_h, dict) and f_handle is not None:
                    try:
                        f_parsed_h = JobHandle.fromDict(f_obs_h)
                        if f_parsed_h != f_handle:
                            f_conflicting_handles = True
                            f_point_diagnostics.append(
                                f"Conflicting handle on disk: {f_parsed_h} != {f_handle}"
                            )
                    except Exception:
                        f_corrupt_evidence = True

            # Lookup fresh scheduler observation from argument
            f_fresh_obs = StateReconciler._lookupSchedulerObservation(
                f_scale_point=f_scale_point,
                f_ordinal=f_idx,
                f_point_id=f_point_name,
                f_handle=f_handle,
                f_scheduler_observations=f_scheduler_observations,
            )

            # Check for conflicting handle in fresh observation
            if f_fresh_obs and f_fresh_obs.get("handle") and f_handle:
                try:
                    f_fresh_h = f_fresh_obs["handle"]
                    if isinstance(f_fresh_h, dict):
                        f_fresh_h = JobHandle.fromDict(f_fresh_h)
                    if isinstance(f_fresh_h, JobHandle) and f_fresh_h != f_handle:
                        f_conflicting_handles = True
                        f_point_diagnostics.append(
                            f"Conflicting handle in fresh observation: {f_fresh_h} != {f_handle}"
                        )
                except Exception:
                    f_corrupt_evidence = True

            # c) Read Controller events and results
            f_worker_events: List[EvidenceRecord] = []
            try:
                f_worker_events = f_evidence_store.readWorkerEvents(
                    f_scale_point, f_ordinal=f_idx
                )
            except (
                EvidenceSequenceError,
                EvidenceCorruptionError,
                EvidenceSchemaError,
            ) as f_err:
                f_corrupt_evidence = True
                f_point_diagnostics.append(f"Worker events read error: {f_err}")

            f_combinations_completed: List[str] = []
            f_combinations_failed: List[str] = []
            f_combinations_missing: List[str] = []
            f_controller_failure = False
            f_failure_timestamp: Optional[str] = None

            for f_combo in f_plan.combinations:
                f_combo_name = f_combo.name
                try:
                    f_ctrl_res = f_evidence_store.readControllerResult(
                        f_scale_point, f_combo, f_ordinal=f_idx
                    )
                except (EvidenceCorruptionError, EvidenceSchemaError) as f_err:
                    f_corrupt_evidence = True
                    f_point_diagnostics.append(
                        f"Corrupt controller result for {f_combo_name}: {f_err}"
                    )
                    f_ctrl_res = None

                if f_ctrl_res is None:
                    f_combinations_missing.append(f_combo_name)
                else:
                    f_target_str = (
                        f_plan.request.target
                        if hasattr(f_plan, "request")
                        and hasattr(f_plan.request, "target")
                        else getattr(f_plan, "target", None)
                    )
                    f_is_succ = ResultPayloadValidator.isSuccessPayload(
                        f_ctrl_res.payload,
                        EvidenceKind.CONTROLLER_RESULT,
                        f_target=f_target_str,
                        f_expected_tasks=(f_scale_point.tasks if f_is_lsmio else None),
                        f_expected_combination=f_combo_name,
                    )
                    f_is_fail = ResultPayloadValidator.isFailurePayload(
                        f_ctrl_res.payload,
                        EvidenceKind.CONTROLLER_RESULT,
                        f_expected_combination=f_combo_name,
                    )
                    if f_is_succ:
                        f_combinations_completed.append(f_combo_name)
                    elif f_is_fail:
                        f_combinations_failed.append(f_combo_name)
                        f_controller_failure = True
                        if (
                            f_failure_timestamp is None
                            or f_ctrl_res.created_at_utc < f_failure_timestamp
                        ):
                            f_failure_timestamp = f_ctrl_res.created_at_utc
                    else:
                        f_corrupt_evidence = True
                        f_point_diagnostics.append(
                            f"Corrupt or invalid controller result payload for {f_combo_name}: {f_ctrl_res.payload!r}"
                        )

            # d) Read LSMIO Task Rank Results (if applicable)
            f_rank_failure = False
            f_rank_missing = False
            if f_is_lsmio:
                for f_combo in f_plan.combinations:
                    for f_rank_idx in range(f_scale_point.tasks):
                        try:
                            f_rank_res = f_evidence_store.readRankResult(
                                f_scale_point, f_rank_idx, f_combo, f_ordinal=f_idx
                            )
                        except (EvidenceCorruptionError, EvidenceSchemaError) as f_err:
                            f_corrupt_evidence = True
                            f_point_diagnostics.append(
                                f"Corrupt rank result for rank {f_rank_idx}, {f_combo.name}: {f_err}"
                            )
                            f_rank_res = None

                        if f_rank_res is None:
                            f_rank_missing = True
                        else:
                            f_r_succ = ResultPayloadValidator.isSuccessPayload(
                                f_rank_res.payload,
                                EvidenceKind.RANK_RESULT,
                                f_expected_rank=f_rank_idx,
                                f_expected_combination=f_combo.name,
                            )
                            f_r_fail = ResultPayloadValidator.isFailurePayload(
                                f_rank_res.payload,
                                EvidenceKind.RANK_RESULT,
                                f_expected_rank=f_rank_idx,
                                f_expected_combination=f_combo.name,
                            )
                            if f_r_fail:
                                f_rank_failure = True
                                if (
                                    f_failure_timestamp is None
                                    or f_rank_res.created_at_utc < f_failure_timestamp
                                ):
                                    f_failure_timestamp = f_rank_res.created_at_utc
                            elif not f_r_succ:
                                f_corrupt_evidence = True
                                f_point_diagnostics.append(
                                    f"Corrupt or invalid rank result payload for rank {f_rank_idx}, {f_combo.name}: {f_rank_res.payload!r}"
                                )

            # Check scheduler observation failures for failure timestamp
            for f_obs in f_disk_observations:
                f_p = f_obs.payload
                if isinstance(f_p, dict):
                    f_raw_st = (
                        f_p.get("state")
                        or f_p.get("scheduler_state")
                        or f_p.get("job_state")
                    )
                    f_parsed_st = None
                    if isinstance(f_raw_st, SchedulerJobState):
                        f_parsed_st = f_raw_st
                    elif isinstance(f_raw_st, str):
                        try:
                            f_parsed_st = SchedulerJobState(f_raw_st.strip().lower())
                        except ValueError:
                            pass
                    if f_parsed_st in (
                        SchedulerJobState.FAILED,
                        SchedulerJobState.TIMEOUT,
                    ):
                        if (
                            f_failure_timestamp is None
                            or f_obs.created_at_utc < f_failure_timestamp
                        ):
                            f_failure_timestamp = f_obs.created_at_utc

            # Resolve SchedulerJobState (Enforcing Reduction & Terminal Non-Regression)
            f_sched_state = StateReconciler._resolveSchedulerState(
                f_disk_observations=f_disk_observations,
                f_fresh_observation=f_fresh_obs,
                f_submission_dispatched=(f_sub_disp is not None),
                f_submission_recorded=(f_sub_rec is not None),
                f_point_diagnostics=f_point_diagnostics,
                f_cancel_requested=(f_cancel_req is not None),
                f_cancel_recorded=(f_cancel_rec is not None),
                f_cancel_req_record=f_cancel_req,
                f_failure_timestamp=f_failure_timestamp,
            )

            # e) Derive PointRunState under the 6 Precedence Rules
            f_point_state = StateReconciler._derivePointState(
                f_sub_requested=(f_sub_req is not None),
                f_sub_dispatched=(f_sub_disp is not None),
                f_sub_recorded=(f_sub_rec is not None),
                f_sched_state=f_sched_state,
                f_has_worker_events=(len(f_worker_events) > 0),
                f_combinations_completed=f_combinations_completed,
                f_combinations_failed=f_combinations_failed,
                f_combinations_missing=f_combinations_missing,
                f_plan_combinations_count=len(f_plan.combinations),
                f_is_lsmio=f_is_lsmio,
                f_rank_failure=f_rank_failure,
                f_rank_missing=f_rank_missing,
                f_cancel_requested=(f_cancel_req is not None),
                f_cancel_recorded=(f_cancel_rec is not None),
                f_cancel_unconfirmed=(f_cancel_unconf is not None),
                f_cancel_req_record=f_cancel_req,
                f_failure_timestamp=f_failure_timestamp,
                f_conflicting_handles=f_conflicting_handles,
                f_corrupt_evidence=f_corrupt_evidence,
                f_point_diagnostics=f_point_diagnostics,
            )

            f_point_view = PointStateView(
                f_point_id=f_point_name,
                f_ordinal=f_idx,
                f_scale_point=f_scale_point,
                f_state=f_point_state,
                f_handle=f_handle,
                f_scheduler_state=f_sched_state,
                f_combinations_completed=f_combinations_completed,
                f_combinations_failed=f_combinations_failed,
                f_combinations_missing=f_combinations_missing,
                f_diagnostics=f_point_diagnostics,
            )
            f_point_views.append(f_point_view)

        # -------------------------------------------------------------------------
        # 3. Synthesize OverallRunState Precedence
        # -------------------------------------------------------------------------
        f_active_ordinal: Optional[int] = None
        for f_idx, f_pv in enumerate(f_point_views):
            if f_pv.state in (PointRunState.RUNNING, PointRunState.SUBMITTED):
                f_active_ordinal = f_idx
                break

        f_overall_state = StateReconciler._deriveOverallState(
            f_point_views=f_point_views,
            f_control_corrupt=f_control_corrupt,
            f_has_interruption=f_has_interruption,
            f_has_success_marker=f_has_success_marker,
            f_interrupted_first=f_interrupted_first,
            f_run_diagnostics=f_run_diagnostics,
        )

        return RunStateView(
            f_run_id=f_plan.run_id,
            f_state=f_overall_state,
            f_point_states=f_point_views,
            f_active_point_ordinal=f_active_ordinal,
            f_diagnostics=f_run_diagnostics,
            f_has_interruption=f_has_interruption,
            f_has_success_marker=f_has_success_marker,
        )

    # ---------------------------------------------------------------------------
    # Private Helper Methods
    # ---------------------------------------------------------------------------

    @staticmethod
    def _isResultFailure(f_payload: Mapping[str, Any]) -> bool:
        """Determines if a controller or rank result payload indicates failure."""
        return ResultPayloadValidator.isFailurePayload(f_payload)

    @staticmethod
    def _lookupSchedulerObservation(
        f_scale_point: ScalePoint,
        f_ordinal: int,
        f_point_id: str,
        f_handle: Optional[JobHandle],
        f_scheduler_observations: Optional[Mapping[Any, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Extracts and normalizes scheduler observation for a point from caller argument."""
        if not f_scheduler_observations:
            return None

        f_matched_val: Any = None
        for f_k, f_v in f_scheduler_observations.items():
            if (
                f_k == f_scale_point
                or f_k == f_ordinal
                or f_k == f_point_id
                or str(f_k) == str(f_ordinal)
            ):
                f_matched_val = f_v
                break
            if f_handle is not None:
                if (
                    f_k == f_handle
                    or f_k == f_handle.job_id
                    or f_k == f_handle.jobId
                    or str(f_k) == f_handle.job_id
                ):
                    f_matched_val = f_v
                    break

        if f_matched_val is None:
            return None

        if isinstance(f_matched_val, SchedulerJobState):
            return {"state": f_matched_val}
        elif isinstance(f_matched_val, str):
            try:
                return {"state": SchedulerJobState(f_matched_val.strip().lower())}
            except ValueError:
                return {"state": SchedulerJobState.UNKNOWN, "raw": f_matched_val}
        elif isinstance(f_matched_val, dict):
            f_res = dict(f_matched_val)
            if "state" in f_res:
                if isinstance(f_res["state"], str):
                    try:
                        f_res["state"] = SchedulerJobState(
                            f_res["state"].strip().lower()
                        )
                    except ValueError:
                        f_res["state"] = SchedulerJobState.UNKNOWN
            return f_res
        elif hasattr(f_matched_val, "state"):
            f_st = getattr(f_matched_val, "state")
            if isinstance(f_st, SchedulerJobState):
                f_res_st = f_st
            elif isinstance(f_st, str):
                try:
                    f_res_st = SchedulerJobState(f_st.strip().lower())
                except ValueError:
                    f_res_st = SchedulerJobState.UNKNOWN
            else:
                f_res_st = SchedulerJobState.UNKNOWN
            f_h = getattr(f_matched_val, "handle", None)
            return {"state": f_res_st, "handle": f_h}

        return {"state": SchedulerJobState.UNKNOWN}

    @staticmethod
    def _resolveSchedulerState(
        f_disk_observations: List[EvidenceRecord],
        f_fresh_observation: Optional[Dict[str, Any]],
        f_submission_dispatched: bool,
        f_submission_recorded: bool,
        f_point_diagnostics: Optional[List[str]] = None,
        f_cancel_requested: bool = False,
        f_cancel_recorded: bool = False,
        f_cancel_req_record: Optional[EvidenceRecord] = None,
        f_failure_timestamp: Optional[str] = None,
    ) -> Optional[SchedulerJobState]:
        """Resolves authoritative scheduler job state by deterministically reducing observation history + fresh observation."""
        f_all_states: List[SchedulerJobState] = []

        # Parse disk observations
        for f_obs in f_disk_observations:
            f_p = f_obs.payload
            if not isinstance(f_p, dict):
                f_all_states.append(SchedulerJobState.UNKNOWN)
                continue
            f_raw_st = (
                f_p.get("state") or f_p.get("scheduler_state") or f_p.get("job_state")
            )
            if isinstance(f_raw_st, SchedulerJobState):
                f_all_states.append(f_raw_st)
            elif isinstance(f_raw_st, str):
                try:
                    f_all_states.append(SchedulerJobState(f_raw_st.strip().lower()))
                except ValueError:
                    f_all_states.append(SchedulerJobState.UNKNOWN)
            else:
                f_all_states.append(SchedulerJobState.UNKNOWN)

        # Parse fresh observation
        if f_fresh_observation and "state" in f_fresh_observation:
            f_raw_fresh = f_fresh_observation["state"]
            if isinstance(f_raw_fresh, SchedulerJobState):
                f_all_states.append(f_raw_fresh)
            elif isinstance(f_raw_fresh, str):
                try:
                    f_all_states.append(SchedulerJobState(f_raw_fresh.strip().lower()))
                except ValueError:
                    f_all_states.append(SchedulerJobState.UNKNOWN)
            else:
                f_all_states.append(SchedulerJobState.UNKNOWN)

        # If no observations at all
        if not f_all_states:
            if f_submission_recorded or f_submission_dispatched:
                return SchedulerJobState.QUEUED
            return None

        # Separate terminal vs non-terminal
        f_terminal_states = {f_st for f_st in f_all_states if f_st.isTerminal}

        # Case 1: No terminal observations
        if not f_terminal_states:
            if SchedulerJobState.UNKNOWN in f_all_states:
                return SchedulerJobState.UNKNOWN
            if SchedulerJobState.ACTIVE in f_all_states:
                return SchedulerJobState.ACTIVE
            if SchedulerJobState.QUEUED in f_all_states:
                return SchedulerJobState.QUEUED
            if f_submission_recorded or f_submission_dispatched:
                return SchedulerJobState.QUEUED
            return None

        # Case 2: Terminal observations exist (active/queued cannot regress established terminal facts)
        if len(f_terminal_states) == 1:
            return next(iter(f_terminal_states))

        # Case 3: Multiple distinct terminal states exist (evaluate precedence and conflict)
        # 3a. SUCCEEDED vs FAILED (Rule 2: Specific failure outranks generic scheduler success)
        if f_terminal_states == {SchedulerJobState.SUCCEEDED, SchedulerJobState.FAILED}:
            if f_point_diagnostics is not None:
                f_point_diagnostics.append(
                    "Resolved scheduler state FAILED (specific failure outranks generic scheduler success)"
                )
            return SchedulerJobState.FAILED

        # 3b. SUCCEEDED vs TIMEOUT (Rule 2: Specific timeout outranks generic scheduler success)
        if f_terminal_states == {
            SchedulerJobState.SUCCEEDED,
            SchedulerJobState.TIMEOUT,
        }:
            if f_point_diagnostics is not None:
                f_point_diagnostics.append(
                    "Resolved scheduler state TIMEOUT (specific timeout outranks generic scheduler success)"
                )
            return SchedulerJobState.TIMEOUT

        # 3c. SUCCEEDED vs CANCELLED
        if f_terminal_states == {
            SchedulerJobState.SUCCEEDED,
            SchedulerJobState.CANCELLED,
        }:
            if f_cancel_requested:
                return SchedulerJobState.CANCELLED
            else:
                if f_point_diagnostics is not None:
                    f_point_diagnostics.append(
                        "Indeterminate: Conflicting terminal scheduler observations: succeeded vs cancelled without requested cancellation"
                    )
                return SchedulerJobState.UNKNOWN

        # 3d. FAILED vs CANCELLED
        if f_terminal_states == {SchedulerJobState.FAILED, SchedulerJobState.CANCELLED}:
            if f_cancel_requested:
                if f_failure_timestamp and f_cancel_req_record:
                    if f_failure_timestamp <= f_cancel_req_record.created_at_utc:
                        return SchedulerJobState.FAILED
                    else:
                        return SchedulerJobState.CANCELLED
                else:
                    if f_point_diagnostics is not None:
                        f_point_diagnostics.append(
                            "Indeterminate: Ambiguous causal order between failure and cancellation"
                        )
                    return SchedulerJobState.UNKNOWN
            else:
                if f_point_diagnostics is not None:
                    f_point_diagnostics.append(
                        "Indeterminate: Conflicting terminal scheduler observations: failed vs cancelled without requested cancellation"
                    )
                return SchedulerJobState.UNKNOWN

        # 3e. TIMEOUT vs CANCELLED
        if f_terminal_states == {
            SchedulerJobState.TIMEOUT,
            SchedulerJobState.CANCELLED,
        }:
            if f_cancel_requested:
                if f_failure_timestamp and f_cancel_req_record:
                    if f_failure_timestamp <= f_cancel_req_record.created_at_utc:
                        return SchedulerJobState.TIMEOUT
                    else:
                        return SchedulerJobState.CANCELLED
                else:
                    if f_point_diagnostics is not None:
                        f_point_diagnostics.append(
                            "Indeterminate: Ambiguous causal order between timeout and cancellation"
                        )
                    return SchedulerJobState.UNKNOWN
            else:
                if f_point_diagnostics is not None:
                    f_point_diagnostics.append(
                        "Indeterminate: Conflicting terminal scheduler observations: timeout vs cancelled without requested cancellation"
                    )
                return SchedulerJobState.UNKNOWN

        # 3f. FAILED vs TIMEOUT (Conflicting failure modes without causal precedence)
        if f_terminal_states == {SchedulerJobState.FAILED, SchedulerJobState.TIMEOUT}:
            if f_point_diagnostics is not None:
                f_point_diagnostics.append(
                    "Indeterminate: Conflicting terminal scheduler observations: failed vs timeout"
                )
            return SchedulerJobState.UNKNOWN

        # 3g. Multi-way terminal state combinations:
        # If both FAILED and TIMEOUT are in the set -> conflict between failure modes
        if (
            SchedulerJobState.FAILED in f_terminal_states
            and SchedulerJobState.TIMEOUT in f_terminal_states
        ):
            if f_point_diagnostics is not None:
                f_point_diagnostics.append(
                    "Indeterminate: Conflicting terminal scheduler observations: failed vs timeout"
                )
            return SchedulerJobState.UNKNOWN

        # If SUCCEEDED + FAILED + CANCELLED:
        if f_terminal_states == {
            SchedulerJobState.SUCCEEDED,
            SchedulerJobState.FAILED,
            SchedulerJobState.CANCELLED,
        }:
            if f_cancel_requested:
                if f_failure_timestamp and f_cancel_req_record:
                    if f_failure_timestamp <= f_cancel_req_record.created_at_utc:
                        return SchedulerJobState.FAILED
                    else:
                        return SchedulerJobState.CANCELLED
                else:
                    if f_point_diagnostics is not None:
                        f_point_diagnostics.append(
                            "Indeterminate: Ambiguous causal order between failure and cancellation"
                        )
                    return SchedulerJobState.UNKNOWN
            else:
                if f_point_diagnostics is not None:
                    f_point_diagnostics.append(
                        "Indeterminate: Conflicting terminal scheduler observations without requested cancellation"
                    )
                return SchedulerJobState.UNKNOWN

        # If SUCCEEDED + TIMEOUT + CANCELLED:
        if f_terminal_states == {
            SchedulerJobState.SUCCEEDED,
            SchedulerJobState.TIMEOUT,
            SchedulerJobState.CANCELLED,
        }:
            if f_cancel_requested:
                if f_failure_timestamp and f_cancel_req_record:
                    if f_failure_timestamp <= f_cancel_req_record.created_at_utc:
                        return SchedulerJobState.TIMEOUT
                    else:
                        return SchedulerJobState.CANCELLED
                else:
                    if f_point_diagnostics is not None:
                        f_point_diagnostics.append(
                            "Indeterminate: Ambiguous causal order between timeout and cancellation"
                        )
                    return SchedulerJobState.UNKNOWN
            else:
                if f_point_diagnostics is not None:
                    f_point_diagnostics.append(
                        "Indeterminate: Conflicting terminal scheduler observations without requested cancellation"
                    )
                return SchedulerJobState.UNKNOWN

        # All other unresolvable terminal conflicts
        if f_point_diagnostics is not None:
            f_point_diagnostics.append(
                f"Indeterminate: Conflicting terminal scheduler observations: {sorted(s.value for s in f_terminal_states)}"
            )
        return SchedulerJobState.UNKNOWN

    @staticmethod
    def _derivePointState(
        f_sub_requested: bool,
        f_sub_dispatched: bool,
        f_sub_recorded: bool,
        f_sched_state: Optional[SchedulerJobState],
        f_has_worker_events: bool,
        f_combinations_completed: List[str],
        f_combinations_failed: List[str],
        f_combinations_missing: List[str],
        f_plan_combinations_count: int,
        f_is_lsmio: bool,
        f_rank_failure: bool,
        f_rank_missing: bool,
        f_cancel_requested: bool,
        f_cancel_recorded: bool,
        f_cancel_unconfirmed: bool,
        f_cancel_req_record: Optional[EvidenceRecord],
        f_failure_timestamp: Optional[str],
        f_conflicting_handles: bool,
        f_corrupt_evidence: bool,
        f_point_diagnostics: List[str],
    ) -> PointRunState:
        """Derives single scale point state strictly adhering to the 6 precedence rules."""
        # 1. Not Started
        if not f_sub_requested and not f_sub_dispatched and not f_sub_recorded:
            return PointRunState.NOT_STARTED

        # 2. Rule 5: Indeterminate Refinement
        if f_conflicting_handles:
            f_point_diagnostics.append(
                "Indeterminate: Conflicting scheduler job handles detected"
            )
            return PointRunState.INDETERMINATE

        if f_corrupt_evidence:
            f_point_diagnostics.append("Indeterminate: Corrupted evidence encountered")
            return PointRunState.INDETERMINATE

        if f_cancel_unconfirmed:
            f_point_diagnostics.append("Indeterminate: Unconfirmed cancellation")
            return PointRunState.INDETERMINATE

        if f_sched_state == SchedulerJobState.UNKNOWN:
            f_point_diagnostics.append("Indeterminate: Scheduler job state is UNKNOWN")
            return PointRunState.INDETERMINATE

        # 3. Rule 2: Failure Precedence (Evidenced failure outranks generic scheduler success)
        f_has_specific_failure = False
        if len(f_combinations_failed) > 0 or f_rank_failure:
            f_has_specific_failure = True
        elif f_sched_state in (SchedulerJobState.FAILED, SchedulerJobState.TIMEOUT):
            f_has_specific_failure = True
        elif f_sched_state == SchedulerJobState.SUCCEEDED:
            # If scheduler terminal completion occurred, but combination/rank evidence is incomplete:
            # Missing evidence after terminal completion is an execution contract failure!
            if len(f_combinations_missing) > 0 or (f_is_lsmio and f_rank_missing):
                f_has_specific_failure = True
                f_point_diagnostics.append(
                    "Execution failure: Scheduler completed but required evidence is missing"
                )

        # 4. Rule 3: Cancellation Causality
        if f_cancel_requested:
            # Check if independent failure occurred before cancel request
            if f_has_specific_failure:
                if f_failure_timestamp and f_cancel_req_record:
                    if f_failure_timestamp <= f_cancel_req_record.created_at_utc:
                        if f_sched_state == SchedulerJobState.TIMEOUT:
                            return PointRunState.TIMED_OUT
                        return PointRunState.FAILED
                    else:
                        # Cancel request preceded failure -> cancel takes precedence if confirmed
                        if (
                            f_cancel_recorded
                            or f_sched_state == SchedulerJobState.CANCELLED
                        ):
                            return PointRunState.CANCELLED
                        elif f_sched_state and f_sched_state.isTerminal:
                            return PointRunState.FAILED
                        else:
                            return (
                                PointRunState.RUNNING
                                if f_sched_state == SchedulerJobState.ACTIVE
                                else PointRunState.SUBMITTED
                            )
                else:
                    # Ambiguous causal order between failure and cancellation request
                    f_point_diagnostics.append(
                        "Indeterminate: Ambiguous causal order between failure and cancellation"
                    )
                    return PointRunState.INDETERMINATE

            if f_cancel_recorded or f_sched_state == SchedulerJobState.CANCELLED:
                return PointRunState.CANCELLED
            elif f_sched_state and f_sched_state.isTerminal:
                # Terminal but not cancelled when cancel was requested
                if f_has_specific_failure:
                    return PointRunState.FAILED
                f_point_diagnostics.append(
                    "Indeterminate: Terminal completion while cancellation was requested"
                )
                return PointRunState.INDETERMINATE
            else:
                # Cancel requested, but still active/waiting confirmation
                return (
                    PointRunState.RUNNING
                    if f_sched_state == SchedulerJobState.ACTIVE
                    else PointRunState.SUBMITTED
                )

        # 5. Cancellation without cancel requested -> not approved cancellation -> INDETERMINATE
        if f_sched_state == SchedulerJobState.CANCELLED and not f_cancel_requested:
            f_point_diagnostics.append(
                "Indeterminate: Scheduler job was cancelled without a requested cancellation record"
            )
            return PointRunState.INDETERMINATE

        # 6. Rule 2: Failure Precedence without cancellation
        if f_has_specific_failure:
            if f_sched_state == SchedulerJobState.TIMEOUT:
                return PointRunState.TIMED_OUT
            return PointRunState.FAILED

        # 7. Rule 1: Point Success Invariant
        if f_sched_state == SchedulerJobState.SUCCEEDED:
            f_all_combos = (
                len(f_combinations_completed) == f_plan_combinations_count
                and len(f_combinations_missing) == 0
                and len(f_combinations_failed) == 0
            )
            f_all_ranks = (not f_is_lsmio) or (
                not f_rank_missing and not f_rank_failure
            )
            if f_all_combos and f_all_ranks:
                return PointRunState.SUCCEEDED

        # 8. Active / Running / Submitted
        if (
            f_sched_state == SchedulerJobState.ACTIVE
            or f_has_worker_events
            or len(f_combinations_completed) > 0
        ):
            return PointRunState.RUNNING

        if (
            f_sched_state == SchedulerJobState.QUEUED
            or f_sub_recorded
            or f_sub_dispatched
            or f_sub_requested
        ):
            return PointRunState.SUBMITTED

        return PointRunState.NOT_STARTED

    @staticmethod
    def _deriveOverallState(
        f_point_views: List[PointStateView],
        f_control_corrupt: bool,
        f_has_interruption: bool,
        f_has_success_marker: bool,
        f_interrupted_first: bool,
        f_run_diagnostics: List[str],
    ) -> OverallRunState:
        """Derives authoritative overall run state enforcing precedence across points and control events."""
        # 1. Control stream corruption -> INDETERMINATE
        if f_control_corrupt:
            f_run_diagnostics.append(
                "Overall INDETERMINATE due to corrupt control stream"
            )
            return OverallRunState.INDETERMINATE

        # 2. Any point INDETERMINATE -> Overall INDETERMINATE
        if any(f_pv.state == PointRunState.INDETERMINATE for f_pv in f_point_views):
            return OverallRunState.INDETERMINATE

        # 3. Rule 2: Failure Precedence (Any point failure outranks success/cancellation)
        if any(f_pv.state == PointRunState.FAILED for f_pv in f_point_views):
            return OverallRunState.FAILED

        if any(f_pv.state == PointRunState.TIMED_OUT for f_pv in f_point_views):
            return OverallRunState.TIMED_OUT

        # 4. Rule 3: Cancellation (Any point cancelled without prior failure)
        if any(f_pv.state == PointRunState.CANCELLED for f_pv in f_point_views):
            return OverallRunState.CANCELLED

        # 5. Rule 4: Interruption Permanence
        # If interruption occurred before whole_run_succeeded marker, overall is permanently INTERRUPTED
        if f_interrupted_first:
            return OverallRunState.INTERRUPTED

        # 6. Rule 1: Complete Overall Success Invariant
        # Overall SUCCEEDED requires all points SUCCEEDED + WHOLE_RUN_SUCCEEDED marker recorded before interruption
        f_all_points_succeeded = len(f_point_views) > 0 and all(
            f_pv.state == PointRunState.SUCCEEDED for f_pv in f_point_views
        )

        if f_all_points_succeeded:
            if f_has_success_marker and not f_interrupted_first:
                return OverallRunState.SUCCEEDED
            else:
                # All points succeeded, but whole_run_succeeded marker not yet persisted
                return OverallRunState.IN_PROGRESS

        # 7. Not Started
        if (
            all(f_pv.state == PointRunState.NOT_STARTED for f_pv in f_point_views)
            and not f_has_interruption
        ):
            return OverallRunState.NOT_STARTED

        # 8. In Progress
        return OverallRunState.IN_PROGRESS
