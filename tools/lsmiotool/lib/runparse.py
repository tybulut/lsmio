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
import stat
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple, Union

from lsmiotool.lib.artifacts import (
    ArtifactError,
    ArtifactLayout,
    ContainmentError,
    validatePathContainment,
)
from lsmiotool.lib.evidence import (
    EvidenceCorruptionError,
    EvidenceError,
    EvidenceKind,
    EvidenceRecord,
    EvidenceSchemaError,
    EvidenceSequenceError,
    EvidenceStore,
)
from lsmiotool.lib.run import (
    Combination,
    ManifestDocument,
    ManifestSerializer,
    ManifestValidationError,
    RunPlan,
    RunRequest,
    ScalePoint,
    ScheduledPointResources,
)
from lsmiotool.lib.state import (
    OverallRunState,
    PointRunState,
    PointStateView,
    RunStateView,
    StateError,
    StateReconciler,
)


class RunParseError(Exception):
    """Base exception for all run parse domain operations."""

    pass


class RunRootResolutionError(RunParseError):
    """Raised when an explicit run root cannot be resolved, validated, or verified as succeeded."""

    pass


class ResolvedPoint:
    """Immutable representation of an inspected scale point in a benchmark run."""

    __slots__ = (
        "m_point_id",
        "m_scale_point",
        "m_ordinal",
        "m_point_dir",
        "m_state_view",
        "m_controller_results",
        "m_rank_results",
        "_frozen",
    )

    def __init__(
        self,
        f_point_id: str,
        f_scale_point: ScalePoint,
        f_ordinal: int,
        f_point_dir: str,
        f_state_view: PointStateView,
        f_controller_results: Mapping[str, Optional[EvidenceRecord]],
        f_rank_results: Mapping[Tuple[int, str], Optional[EvidenceRecord]],
    ) -> None:
        if not isinstance(f_point_id, str) or not f_point_id.strip():
            raise RunParseError(f"point_id must be a non-empty string, got: {f_point_id!r}")
        if not isinstance(f_scale_point, ScalePoint):
            raise RunParseError(f"scale_point must be a ScalePoint, got: {f_scale_point!r}")
        if not isinstance(f_ordinal, int) or f_ordinal < 0:
            raise RunParseError(f"ordinal must be non-negative integer, got: {f_ordinal!r}")
        if not isinstance(f_point_dir, str) or not f_point_dir.strip():
            raise RunParseError(f"point_dir must be a non-empty string, got: {f_point_dir!r}")
        if not isinstance(f_state_view, PointStateView):
            raise RunParseError(f"state_view must be a PointStateView, got: {f_state_view!r}")

        super().__setattr__("m_point_id", f_point_id.strip())
        super().__setattr__("m_scale_point", f_scale_point)
        super().__setattr__("m_ordinal", f_ordinal)
        super().__setattr__("m_point_dir", f_point_dir)
        super().__setattr__("m_state_view", f_state_view)
        super().__setattr__("m_controller_results", dict(f_controller_results))
        super().__setattr__("m_rank_results", dict(f_rank_results))
        super().__setattr__("_frozen", True)

    def __setattr__(self, f_key: str, f_value: Any) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"Cannot modify immutable {self.__class__.__name__}")
        super().__setattr__(f_key, f_value)

    def __delattr__(self, f_key: str) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"Cannot delete attribute from immutable {self.__class__.__name__}")
        super().__delattr__(f_key)

    @staticmethod
    def _comboKey(f_combo: Union[Combination, str, Tuple[int, str]]) -> str:
        if isinstance(f_combo, Combination):
            return f_combo.name
        if isinstance(f_combo, str):
            return f_combo.strip()
        if isinstance(f_combo, (tuple, list)) and len(f_combo) == 2:
            return f"c{f_combo[0]}_b{f_combo[1]}"
        raise RunParseError(f"Invalid combination descriptor: {f_combo!r}")

    @property
    def pointId(self) -> str:
        return self.m_point_id

    @property
    def point_id(self) -> str:
        return self.m_point_id

    @property
    def scalePoint(self) -> ScalePoint:
        return self.m_scale_point

    @property
    def scale_point(self) -> ScalePoint:
        return self.m_scale_point

    @property
    def ordinal(self) -> int:
        return self.m_ordinal

    @property
    def pointDir(self) -> str:
        return self.m_point_dir

    @property
    def point_dir(self) -> str:
        return self.m_point_dir

    @property
    def stateView(self) -> PointStateView:
        return self.m_state_view

    @property
    def state_view(self) -> PointStateView:
        return self.m_state_view

    @property
    def state(self) -> PointRunState:
        return self.m_state_view.state

    @property
    def isSuccess(self) -> bool:
        return self.m_state_view.is_success

    @property
    def is_success(self) -> bool:
        return self.m_state_view.is_success

    @property
    def isTerminal(self) -> bool:
        return self.m_state_view.is_terminal

    @property
    def is_terminal(self) -> bool:
        return self.m_state_view.is_terminal

    @property
    def controllerResults(self) -> Dict[str, Optional[EvidenceRecord]]:
        return dict(self.m_controller_results)

    @property
    def controller_results(self) -> Dict[str, Optional[EvidenceRecord]]:
        return dict(self.m_controller_results)

    @property
    def rankResults(self) -> Dict[Tuple[int, str], Optional[EvidenceRecord]]:
        return dict(self.m_rank_results)

    @property
    def rank_results(self) -> Dict[Tuple[int, str], Optional[EvidenceRecord]]:
        return dict(self.m_rank_results)

    def getControllerResult(
        self, f_combination: Union[Combination, str, Tuple[int, str]]
    ) -> Optional[EvidenceRecord]:
        f_key = self._comboKey(f_combination)
        return self.m_controller_results.get(f_key)

    def getRankResult(
        self, f_global_rank: int, f_combination: Union[Combination, str, Tuple[int, str]]
    ) -> Optional[EvidenceRecord]:
        f_key = self._comboKey(f_combination)
        return self.m_rank_results.get((f_global_rank, f_key))

    def toDict(self) -> Dict[str, Any]:
        return {
            "point_id": self.m_point_id,
            "ordinal": self.m_ordinal,
            "scale_point": self.m_scale_point.toDict(),
            "point_dir": self.m_point_dir,
            "state": self.m_state_view.state.value,
            "is_success": self.is_success,
            "combinations_completed": list(self.m_state_view.combinations_completed),
            "combinations_failed": list(self.m_state_view.combinations_failed),
            "combinations_missing": list(self.m_state_view.combinations_missing),
            "diagnostics": list(self.m_state_view.diagnostics),
        }

    def __repr__(self) -> str:
        return (
            f"ResolvedPoint(point_id={self.m_point_id!r}, "
            f"ordinal={self.m_ordinal}, "
            f"tasks={self.m_scale_point.tasks}, "
            f"state={self.m_state_view.state.value!r})"
        )

    def __eq__(self, f_other: Any) -> bool:
        if isinstance(f_other, ResolvedPoint):
            return (
                self.m_point_id == f_other.m_point_id
                and self.m_scale_point == f_other.m_scale_point
                and self.m_ordinal == f_other.m_ordinal
                and self.m_point_dir == f_other.m_point_dir
                and self.m_state_view == f_other.m_state_view
                and self.m_controller_results == f_other.m_controller_results
                and self.m_rank_results == f_other.m_rank_results
            )
        return False


class ResolvedRun:
    """Immutable representation of a validated, succeeded benchmark run."""

    __slots__ = (
        "m_run_root",
        "m_manifest",
        "m_plan",
        "m_run_state",
        "m_points",
        "m_evidence_store",
        "_frozen",
    )

    def __init__(
        self,
        f_run_root: str,
        f_manifest: ManifestDocument,
        f_plan: RunPlan,
        f_run_state: RunStateView,
        f_points: Sequence[ResolvedPoint],
        f_evidence_store: EvidenceStore,
    ) -> None:
        if not isinstance(f_run_root, str) or not f_run_root.strip():
            raise RunParseError(f"run_root must be a non-empty string, got: {f_run_root!r}")
        if not isinstance(f_manifest, ManifestDocument):
            raise RunParseError(f"manifest must be a ManifestDocument, got: {f_manifest!r}")
        if not isinstance(f_plan, RunPlan):
            raise RunParseError(f"plan must be a RunPlan, got: {f_plan!r}")
        if not isinstance(f_run_state, RunStateView):
            raise RunParseError(f"run_state must be a RunStateView, got: {f_run_state!r}")
        if not isinstance(f_evidence_store, EvidenceStore):
            raise RunParseError(f"evidence_store must be an EvidenceStore, got: {f_evidence_store!r}")

        super().__setattr__("m_run_root", f_run_root)
        super().__setattr__("m_manifest", f_manifest)
        super().__setattr__("m_plan", f_plan)
        super().__setattr__("m_run_state", f_run_state)
        super().__setattr__("m_points", tuple(f_points))
        super().__setattr__("m_evidence_store", f_evidence_store)
        super().__setattr__("_frozen", True)

    def __setattr__(self, f_key: str, f_value: Any) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"Cannot modify immutable {self.__class__.__name__}")
        super().__setattr__(f_key, f_value)

    def __delattr__(self, f_key: str) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"Cannot delete attribute from immutable {self.__class__.__name__}")
        super().__delattr__(f_key)

    @property
    def runRoot(self) -> str:
        return self.m_run_root

    @property
    def run_root(self) -> str:
        return self.m_run_root

    @property
    def manifest(self) -> ManifestDocument:
        return self.m_manifest

    @property
    def plan(self) -> RunPlan:
        return self.m_plan

    @property
    def runState(self) -> RunStateView:
        return self.m_run_state

    @property
    def run_state(self) -> RunStateView:
        return self.m_run_state

    @property
    def points(self) -> Tuple[ResolvedPoint, ...]:
        return self.m_points

    @property
    def pointStates(self) -> Tuple[PointStateView, ...]:
        return self.m_run_state.point_states

    @property
    def evidenceStore(self) -> EvidenceStore:
        return self.m_evidence_store

    @property
    def evidence_store(self) -> EvidenceStore:
        return self.m_evidence_store

    @property
    def isSuccess(self) -> bool:
        return self.m_run_state.is_success

    @property
    def is_success(self) -> bool:
        return self.m_run_state.is_success

    @property
    def runId(self) -> str:
        return self.m_manifest.run_id

    @property
    def run_id(self) -> str:
        return self.m_manifest.run_id

    @property
    def target(self) -> str:
        return self.m_manifest.request.target

    @property
    def scale(self) -> str:
        return self.m_manifest.request.scale

    @property
    def setup(self) -> str:
        return self.m_manifest.request.setup

    @property
    def isSsd(self) -> bool:
        return self.m_manifest.request.is_ssd

    @property
    def is_ssd(self) -> bool:
        return self.m_manifest.request.is_ssd

    def getPoint(self, f_point_id: Union[int, str, ScalePoint]) -> ResolvedPoint:
        """Lookup a resolved point by ordinal, task count, directory name, or ScalePoint."""
        if isinstance(f_point_id, int):
            if 0 <= f_point_id < len(self.m_points):
                return self.m_points[f_point_id]
            for f_pt in self.m_points:
                if f_pt.scale_point.tasks == f_point_id:
                    return f_pt
        elif isinstance(f_point_id, str):
            f_norm = f_point_id.strip()
            for f_pt in self.m_points:
                if f_pt.point_id == f_norm:
                    return f_pt
            if f_norm.isdigit():
                f_val = int(f_norm)
                if 0 <= f_val < len(self.m_points):
                    return self.m_points[f_val]
                for f_pt in self.m_points:
                    if f_pt.scale_point.tasks == f_val:
                        return f_pt
        elif isinstance(f_point_id, ScalePoint):
            for f_pt in self.m_points:
                if (
                    f_pt.scale_point.tasks == f_point_id.tasks
                    and f_pt.scale_point.ppn == f_point_id.ppn
                    and f_pt.scale_point.nodes == f_point_id.nodes
                ):
                    return f_pt
        raise RunParseError(f"Scale point '{f_point_id}' not found in resolved run '{self.run_id}'")

    def toDict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_root": self.m_run_root,
            "target": self.target,
            "scale": self.scale,
            "setup": self.setup,
            "is_ssd": self.is_ssd,
            "state": self.m_run_state.state.value,
            "is_success": self.is_success,
            "points": [f_pt.toDict() for f_pt in self.m_points],
        }

    def __repr__(self) -> str:
        return (
            f"ResolvedRun(run_id={self.run_id!r}, "
            f"target={self.target!r}, "
            f"scale={self.scale!r}, "
            f"points_count={len(self.m_points)})"
        )

    def __eq__(self, f_other: Any) -> bool:
        if isinstance(f_other, ResolvedRun):
            return (
                self.m_run_root == f_other.m_run_root
                and self.m_manifest == f_other.m_manifest
                and self.m_plan == f_other.m_plan
                and self.m_run_state == f_other.m_run_state
                and self.m_points == f_other.m_points
            )
        return False


class RunRootResolver:
    """Explicit, manifest-aware run root resolver with strict boundary validation."""

    @classmethod
    def _validateRootDirectory(cls, f_explicit_root: str) -> str:
        """Validate consumer boundary on explicit root directory via os.lstat."""
        if not isinstance(f_explicit_root, str) or not f_explicit_root.strip():
            raise RunRootResolutionError(
                f"explicit_root must be a non-empty string, got: {f_explicit_root!r}"
            )
        if "\0" in f_explicit_root:
            raise RunRootResolutionError(f"explicit_root contains NUL byte: {f_explicit_root!r}")

        f_abs_root = os.path.abspath(f_explicit_root)

        try:
            f_stat = os.lstat(f_abs_root)
        except FileNotFoundError as f_err:
            raise RunRootResolutionError(
                f"Run root directory does not exist: '{f_abs_root}'"
            ) from f_err
        except OSError as f_err:
            raise RunRootResolutionError(
                f"Failed to access run root directory '{f_abs_root}': {f_err}"
            ) from f_err

        if stat.S_ISLNK(f_stat.st_mode):
            raise RunRootResolutionError(
                f"Run root must not be a symlink: '{f_abs_root}'"
            )
        if not stat.S_ISDIR(f_stat.st_mode):
            raise RunRootResolutionError(
                f"Run root must be a directory: '{f_abs_root}'"
            )

        return f_abs_root

    @classmethod
    def _loadAndValidateManifest(cls, f_abs_root: str) -> ManifestDocument:
        """Read, stat-validate, and deserialize manifest.json from run root."""
        f_manifest_path = os.path.join(f_abs_root, "manifest.json")

        try:
            f_mstat = os.lstat(f_manifest_path)
        except FileNotFoundError as f_err:
            raise RunRootResolutionError(
                f"Missing manifest.json in run root: '{f_manifest_path}'"
            ) from f_err
        except OSError as f_err:
            raise RunRootResolutionError(
                f"Failed to access manifest.json '{f_manifest_path}': {f_err}"
            ) from f_err

        if stat.S_ISLNK(f_mstat.st_mode):
            raise RunRootResolutionError(
                f"manifest.json must not be a symlink: '{f_manifest_path}'"
            )
        if not stat.S_ISREG(f_mstat.st_mode):
            raise RunRootResolutionError(
                f"manifest.json must be a regular file: '{f_manifest_path}'"
            )

        try:
            with open(f_manifest_path, "r", encoding="utf-8") as f_f:
                f_content = f_f.read()
        except OSError as f_err:
            raise RunRootResolutionError(
                f"Failed to read manifest.json '{f_manifest_path}': {f_err}"
            ) from f_err

        try:
            f_manifest = ManifestSerializer.deserialize(f_content)
        except Exception as f_err:
            raise RunRootResolutionError(
                f"Failed to deserialize manifest.json '{f_manifest_path}': {f_err}"
            ) from f_err

        return f_manifest

    @classmethod
    def _createArtifactLayout(cls, f_abs_root: str, f_manifest: ManifestDocument) -> ArtifactLayout:
        """Create and containment-validate ArtifactLayout from run root and manifest."""
        f_root_basename = os.path.basename(f_abs_root)
        if f_root_basename != f_manifest.run_id:
            raise RunRootResolutionError(
                f"Run root directory basename '{f_root_basename}' does not match manifest run_id '{f_manifest.run_id}'"
            )

        f_parent = os.path.dirname(f_abs_root)
        if os.path.basename(f_parent) != "runs":
            raise RunRootResolutionError(
                f"Run root directory '{f_abs_root}' is not located in a 'runs' directory: parent is '{f_parent}'"
            )

        f_bm_root = os.path.dirname(f_parent)
        try:
            f_layout = ArtifactLayout(f_bm_root, f_manifest.run_id)
            validatePathContainment(f_layout.runRoot, f_layout.benchmarkRoot)
        except Exception as f_err:
            raise RunRootResolutionError(
                f"Layout containment validation failed for '{f_abs_root}': {f_err}"
            ) from f_err

        return f_layout

    @classmethod
    def resolve(cls, f_explicit_root: str) -> ResolvedRun:
        """Resolve and validate an explicit run root, verifying that the whole run succeeded."""
        f_abs_root = cls._validateRootDirectory(f_explicit_root)
        f_manifest = cls._loadAndValidateManifest(f_abs_root)
        f_layout = cls._createArtifactLayout(f_abs_root, f_manifest)

        f_plan = f_manifest.toRunPlan()
        f_evidence_store = EvidenceStore(f_layout, f_plan=f_plan)

        try:
            f_run_state = StateReconciler.reconcile(f_plan, f_evidence_store)
        except Exception as f_err:
            raise RunRootResolutionError(
                f"State reconciliation failed for run '{f_manifest.run_id}': {f_err}"
            ) from f_err

        if not f_run_state.is_success or f_run_state.state != OverallRunState.SUCCEEDED:
            raise RunRootResolutionError(
                f"Run '{f_manifest.run_id}' did not succeed (state: {f_run_state.state.value}, diagnostics: {f_run_state.diagnostics})"
            )

        if not f_run_state.has_success_marker:
            raise RunRootResolutionError(
                f"Run '{f_manifest.run_id}' is missing whole_run_succeeded control event marker"
            )

        # Build resolved points and verify evidence
        f_is_lsmio = (f_manifest.request.target.lower() == "lsmio")
        f_resolved_points: List[ResolvedPoint] = []

        for f_idx, f_sp in enumerate(f_plan.scale_points):
            f_pt_view = f_run_state.point_states[f_idx]
            if not f_pt_view.is_success or f_pt_view.state != PointRunState.SUCCEEDED:
                raise RunRootResolutionError(
                    f"Scale point {f_idx} (tasks={f_sp.tasks}) did not succeed: state={f_pt_view.state.value}"
                )

            f_pt_name = f_layout.pointDirName(f_sp, f_idx)
            f_pt_dir = f_layout.pointDir(f_sp, f_idx)

            f_ctrl_results: Dict[str, Optional[EvidenceRecord]] = {}
            f_rank_results: Dict[Tuple[int, str], Optional[EvidenceRecord]] = {}

            for f_combo in f_plan.combinations:
                f_c_res = f_evidence_store.readControllerResult(f_sp, f_combo, f_ordinal=f_idx)
                if f_c_res is None:
                    raise RunRootResolutionError(
                        f"Missing controller result for point {f_idx} combination {f_combo.name}"
                    )
                f_ctrl_results[f_combo.name] = f_c_res

                if f_is_lsmio:
                    for f_rank in range(f_sp.tasks):
                        f_r_res = f_evidence_store.readRankResult(f_sp, f_rank, f_combo, f_ordinal=f_idx)
                        if f_r_res is None:
                            raise RunRootResolutionError(
                                f"Missing rank result for point {f_idx} rank {f_rank} combination {f_combo.name}"
                            )
                        f_rank_results[(f_rank, f_combo.name)] = f_r_res

            f_resolved_points.append(
                ResolvedPoint(
                    f_point_id=f_pt_name,
                    f_scale_point=f_sp,
                    f_ordinal=f_idx,
                    f_point_dir=f_pt_dir,
                    f_state_view=f_pt_view,
                    f_controller_results=f_ctrl_results,
                    f_rank_results=f_rank_results,
                )
            )

        return ResolvedRun(
            f_run_root=f_abs_root,
            f_manifest=f_manifest,
            f_plan=f_plan,
            f_run_state=f_run_state,
            f_points=f_resolved_points,
            f_evidence_store=f_evidence_store,
        )

    @classmethod
    def select(cls, f_explicit_root: str) -> ResolvedRun:
        """Alias for resolve(). Selects a validated succeeded run."""
        return cls.resolve(f_explicit_root)

    @classmethod
    def resolvePoint(
        cls,
        f_explicit_root: str,
        f_point_id: Union[int, str, ScalePoint],
    ) -> ResolvedPoint:
        """Explicitly inspect a single scale point from a run root, even if the overall run was interrupted."""
        f_abs_root = cls._validateRootDirectory(f_explicit_root)
        f_manifest = cls._loadAndValidateManifest(f_abs_root)
        f_layout = cls._createArtifactLayout(f_abs_root, f_manifest)

        f_plan = f_manifest.toRunPlan()
        f_evidence_store = EvidenceStore(f_layout, f_plan=f_plan)

        # Match point
        f_matched_idx: Optional[int] = None
        f_matched_sp: Optional[ScalePoint] = None

        if isinstance(f_point_id, int):
            if 0 <= f_point_id < len(f_plan.scale_points):
                f_matched_idx = f_point_id
                f_matched_sp = f_plan.scale_points[f_point_id]
            else:
                for f_i, f_sp in enumerate(f_plan.scale_points):
                    if f_sp.tasks == f_point_id:
                        f_matched_idx = f_i
                        f_matched_sp = f_sp
                        break
        elif isinstance(f_point_id, str):
            f_norm = f_point_id.strip()
            for f_i, f_sp in enumerate(f_plan.scale_points):
                f_dir_name = f_layout.pointDirName(f_sp, f_i)
                if f_norm == f_dir_name or f_norm == f"tasks-{f_sp.tasks}" or f_norm == f"point-{f_i:02d}":
                    f_matched_idx = f_i
                    f_matched_sp = f_sp
                    break
            if f_matched_idx is None and f_norm.isdigit():
                f_val = int(f_norm)
                if 0 <= f_val < len(f_plan.scale_points):
                    f_matched_idx = f_val
                    f_matched_sp = f_plan.scale_points[f_val]
                else:
                    for f_i, f_sp in enumerate(f_plan.scale_points):
                        if f_sp.tasks == f_val:
                            f_matched_idx = f_i
                            f_matched_sp = f_sp
                            break
        elif isinstance(f_point_id, ScalePoint):
            for f_i, f_sp in enumerate(f_plan.scale_points):
                if (
                    f_sp.tasks == f_point_id.tasks
                    and f_sp.ppn == f_point_id.ppn
                    and f_sp.nodes == f_point_id.nodes
                ):
                    f_matched_idx = f_i
                    f_matched_sp = f_sp
                    break

        if f_matched_idx is None or f_matched_sp is None:
            f_avail = [f_layout.pointDirName(f_sp, f_i) for f_i, f_sp in enumerate(f_plan.scale_points)]
            raise RunRootResolutionError(
                f"Point identifier '{f_point_id}' not found in manifest scale points: {f_avail}"
            )

        try:
            f_run_state = StateReconciler.reconcile(f_plan, f_evidence_store)
        except Exception as f_err:
            raise RunRootResolutionError(
                f"State reconciliation failed for run '{f_manifest.run_id}': {f_err}"
            ) from f_err

        f_pt_view = f_run_state.point_states[f_matched_idx]
        f_pt_name = f_layout.pointDirName(f_matched_sp, f_matched_idx)
        f_pt_dir = f_layout.pointDir(f_matched_sp, f_matched_idx)

        f_is_lsmio = (f_manifest.request.target.lower() == "lsmio")
        f_ctrl_results: Dict[str, Optional[EvidenceRecord]] = {}
        f_rank_results: Dict[Tuple[int, str], Optional[EvidenceRecord]] = {}

        for f_combo in f_plan.combinations:
            f_c_res = f_evidence_store.readControllerResult(f_matched_sp, f_combo, f_ordinal=f_matched_idx)
            f_ctrl_results[f_combo.name] = f_c_res

            if f_is_lsmio:
                for f_rank in range(f_matched_sp.tasks):
                    f_r_res = f_evidence_store.readRankResult(
                        f_matched_sp, f_rank, f_combo, f_ordinal=f_matched_idx
                    )
                    f_rank_results[(f_rank, f_combo.name)] = f_r_res

        return ResolvedPoint(
            f_point_id=f_pt_name,
            f_scale_point=f_matched_sp,
            f_ordinal=f_matched_idx,
            f_point_dir=f_pt_dir,
            f_state_view=f_pt_view,
            f_controller_results=f_ctrl_results,
            f_rank_results=f_rank_results,
        )

    @classmethod
    def selectPoint(
        cls,
        f_explicit_root: str,
        f_point_id: Union[int, str, ScalePoint],
    ) -> ResolvedPoint:
        """Alias for resolvePoint()."""
        return cls.resolvePoint(f_explicit_root, f_point_id)
