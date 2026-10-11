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

import csv
import json
import math
import os
import re
import stat
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple, Union

from lsmiotool.lib import data
from lsmiotool.lib.log import Console
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


class ExtractionError(RunParseError):
    """Raised when log files are missing, malformed, or metric extraction fails."""

    pass


def parseFloat(f_val: Any, f_fallback: float = 0.0) -> float:
    """Robustly parse float with sentinel fallback.

    Args:
        f_val: Value to convert to float.
        f_fallback: Fallback value if conversion fails (default 0.0).

    Returns:
        Converted float value or fallback.
    """
    if f_val is None:
        return f_fallback
    try:
        f_val_str = str(f_val).strip()
        if not f_val_str or f_val_str.upper() in ["NA", "NAN", "N/A", "NULL", "NONE"]:
            return f_fallback
        return float(f_val_str)
    except (ValueError, TypeError):
        return f_fallback


def parseInt(f_val: Any, f_fallback: int = 0) -> int:
    """Robustly parse integer with sentinel fallback.

    Args:
        f_val: Value to convert to integer.
        f_fallback: Fallback value if conversion fails (default 0).

    Returns:
        Converted int value or fallback.
    """
    if f_val is None:
        return f_fallback
    try:
        f_val_str = str(f_val).strip()
        if not f_val_str or f_val_str.upper() in ["NA", "NAN", "N/A", "NULL", "NONE"]:
            return f_fallback
        return int(float(f_val_str))
    except (ValueError, TypeError):
        return f_fallback


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
            raise RunParseError(
                f"point_id must be a non-empty string, got: {f_point_id!r}"
            )
        if not isinstance(f_scale_point, ScalePoint):
            raise RunParseError(
                f"scale_point must be a ScalePoint, got: {f_scale_point!r}"
            )
        if not isinstance(f_ordinal, int) or f_ordinal < 0:
            raise RunParseError(
                f"ordinal must be non-negative integer, got: {f_ordinal!r}"
            )
        if not isinstance(f_point_dir, str) or not f_point_dir.strip():
            raise RunParseError(
                f"point_dir must be a non-empty string, got: {f_point_dir!r}"
            )
        if not isinstance(f_state_view, PointStateView):
            raise RunParseError(
                f"state_view must be a PointStateView, got: {f_state_view!r}"
            )

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
            raise AttributeError(
                f"Cannot delete attribute from immutable {self.__class__.__name__}"
            )
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
        self,
        f_global_rank: int,
        f_combination: Union[Combination, str, Tuple[int, str]],
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
        "m_variant",
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
            raise RunParseError(
                f"run_root must be a non-empty string, got: {f_run_root!r}"
            )
        if not isinstance(f_manifest, ManifestDocument):
            raise RunParseError(
                f"manifest must be a ManifestDocument, got: {f_manifest!r}"
            )
        if not isinstance(f_plan, RunPlan):
            raise RunParseError(f"plan must be a RunPlan, got: {f_plan!r}")
        if not isinstance(f_run_state, RunStateView):
            raise RunParseError(
                f"run_state must be a RunStateView, got: {f_run_state!r}"
            )
        if not isinstance(f_evidence_store, EvidenceStore):
            raise RunParseError(
                f"evidence_store must be an EvidenceStore, got: {f_evidence_store!r}"
            )

        f_variant = None
        if hasattr(f_manifest, "toDict"):
            f_manifest_dict = f_manifest.toDict()
            if isinstance(f_manifest_dict, dict):
                f_req_dict = f_manifest_dict.get("request", {})
                if isinstance(f_req_dict, dict):
                    f_variant = f_req_dict.get("variant")
        if f_variant is None and hasattr(f_manifest, "request"):
            f_variant = getattr(f_manifest.request, "variant", None)
        if f_variant is not None:
            if not isinstance(f_variant, str) or not f_variant.strip():
                raise RunParseError(
                    f"variant must be a non-empty string or None, got: {f_variant!r}"
                )
            f_variant = f_variant.strip().lower()

        super().__setattr__("m_run_root", f_run_root)
        super().__setattr__("m_manifest", f_manifest)
        super().__setattr__("m_plan", f_plan)
        super().__setattr__("m_run_state", f_run_state)
        super().__setattr__("m_points", tuple(f_points))
        super().__setattr__("m_evidence_store", f_evidence_store)
        super().__setattr__("m_variant", f_variant)
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

    @property
    def variant(self) -> Optional[str]:
        return self.m_variant

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
        raise RunParseError(
            f"Scale point '{f_point_id}' not found in resolved run '{self.run_id}'"
        )

    def toDict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_root": self.m_run_root,
            "target": self.target,
            "scale": self.scale,
            "setup": self.setup,
            "variant": self.m_variant,
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
            f"variant={self.m_variant!r}, "
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
                and self.m_variant == f_other.m_variant
            )
        return False


class ArchivedArtifactLayout(ArtifactLayout):
    """ArtifactLayout of a run root moved out of '<benchmark_root>/runs/<run_id>'.

    The archive step moves (and may rename) a run root, e.g. to
    '<benchmark_root>/lsmio-archive/variants/outputs-native-legacy:run'. Every path
    of the layout derives from runRoot, so pinning it to the archived directory
    makes the manifest, control and point paths resolve inside the archive.
    """

    __slots__ = ("m_archived_root",)

    def __init__(self, f_archived_root: str, f_run_id: str) -> None:
        f_abs_root = os.path.abspath(f_archived_root)
        object.__setattr__(self, "m_archived_root", f_abs_root)
        super().__init__(os.path.dirname(f_abs_root), f_run_id)

    @property
    def runRoot(self) -> str:
        return self.m_archived_root

    @property
    def run_root(self) -> str:
        return self.m_archived_root

    @property
    def runsDir(self) -> str:
        return os.path.dirname(self.m_archived_root)

    @property
    def runs_dir(self) -> str:
        return self.runsDir


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
            raise RunRootResolutionError(
                f"explicit_root contains NUL byte: {f_explicit_root!r}"
            )

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
    def _createArtifactLayout(
        cls, f_abs_root: str, f_manifest: ManifestDocument
    ) -> ArtifactLayout:
        """Create and containment-validate the ArtifactLayout for a run root.

        A pristine run root is '<benchmark_root>/runs/<run_id>'. A root that was moved
        or renamed by the archive step (e.g. '<dest>/outputs-native-legacy:run') keeps
        its manifest.json and point layout and is resolved in place.
        """
        f_root_basename = os.path.basename(f_abs_root)
        f_parent = os.path.dirname(f_abs_root)
        f_is_pristine = (
            f_root_basename == f_manifest.run_id
            and os.path.basename(f_parent) == "runs"
        )

        try:
            if f_is_pristine:
                f_layout: ArtifactLayout = ArtifactLayout(
                    os.path.dirname(f_parent), f_manifest.run_id
                )
                validatePathContainment(f_layout.runRoot, f_layout.benchmarkRoot)
            else:
                f_layout = ArchivedArtifactLayout(f_abs_root, f_manifest.run_id)
                validatePathContainment(f_layout.runRoot, f_parent)
        except Exception as f_err:
            raise RunRootResolutionError(
                f"Layout containment validation failed for '{f_abs_root}': {f_err}"
            ) from f_err

        return f_layout

    @classmethod
    def resolve(
        cls, f_explicit_root: str, f_allow_partial: bool = False
    ) -> ResolvedRun:
        """Resolve and validate an explicit run root.

        By default the whole run must have succeeded. With f_allow_partial a run in
        any reconciled state resolves: every scale point is returned with whatever
        controller/rank results exist (None for missing ones), so callers can report
        the points and combinations that completed (bmtool reports whatever output
        exists). Check ResolvedRun.isSuccess / ResolvedPoint.isSuccess.
        """
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

        f_strict = not f_allow_partial
        if f_strict and (
            not f_run_state.is_success or f_run_state.state != OverallRunState.SUCCEEDED
        ):
            raise RunRootResolutionError(
                f"Run '{f_manifest.run_id}' did not succeed (state: {f_run_state.state.value}, diagnostics: {f_run_state.diagnostics})"
            )

        if f_strict and not f_run_state.has_success_marker:
            raise RunRootResolutionError(
                f"Run '{f_manifest.run_id}' is missing whole_run_succeeded control event marker"
            )

        # Build resolved points and verify evidence
        f_is_lsmio = f_manifest.request.target.lower() == "lsmio"
        f_resolved_points: List[ResolvedPoint] = []

        for f_idx, f_sp in enumerate(f_plan.scale_points):
            f_pt_view = f_run_state.point_states[f_idx]
            if f_strict and (
                not f_pt_view.is_success or f_pt_view.state != PointRunState.SUCCEEDED
            ):
                raise RunRootResolutionError(
                    f"Scale point {f_idx} (tasks={f_sp.tasks}) did not succeed: state={f_pt_view.state.value}"
                )

            f_pt_name = f_layout.pointDirName(f_sp, f_idx)
            f_pt_dir = f_layout.pointDir(f_sp, f_idx)

            f_ctrl_results: Dict[str, Optional[EvidenceRecord]] = {}
            f_rank_results: Dict[Tuple[int, str], Optional[EvidenceRecord]] = {}

            for f_combo in f_plan.combinations:
                f_c_res = f_evidence_store.readControllerResult(
                    f_sp, f_combo, f_ordinal=f_idx
                )
                if f_c_res is None and f_strict:
                    raise RunRootResolutionError(
                        f"Missing controller result for point {f_idx} combination {f_combo.name}"
                    )
                f_ctrl_results[f_combo.name] = f_c_res

                if f_is_lsmio:
                    for f_rank in range(f_sp.tasks):
                        f_r_res = f_evidence_store.readRankResult(
                            f_sp, f_rank, f_combo, f_ordinal=f_idx
                        )
                        if f_r_res is None and f_strict:
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
                if (
                    f_norm == f_dir_name
                    or f_norm == f"tasks-{f_sp.tasks}"
                    or f_norm == f"point-{f_i:02d}"
                ):
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
            f_avail = [
                f_layout.pointDirName(f_sp, f_i)
                for f_i, f_sp in enumerate(f_plan.scale_points)
            ]
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

        f_is_lsmio = f_manifest.request.target.lower() == "lsmio"
        f_ctrl_results: Dict[str, Optional[EvidenceRecord]] = {}
        f_rank_results: Dict[Tuple[int, str], Optional[EvidenceRecord]] = {}

        for f_combo in f_plan.combinations:
            f_c_res = f_evidence_store.readControllerResult(
                f_matched_sp, f_combo, f_ordinal=f_matched_idx
            )
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

    @classmethod
    def _manifestMatches(
        cls,
        f_manifest_path: str,
        f_target: Optional[str],
        f_scale: Optional[str],
    ) -> bool:
        """Return True when the manifest's request target/scale match the filters."""
        if f_target is None and f_scale is None:
            return True
        try:
            with open(f_manifest_path, "r", encoding="utf-8") as f_f:
                f_doc = json.load(f_f)
        except (OSError, ValueError):
            return False
        if not isinstance(f_doc, dict):
            return False
        f_req = f_doc.get("request") if isinstance(f_doc.get("request"), dict) else {}
        f_plan = f_doc.get("plan") if isinstance(f_doc.get("plan"), dict) else {}

        def norm(f_val: Any) -> str:
            f_txt = str(f_val or "").strip().lower()
            if f_txt == "lammps":
                return "lmp"
            if f_txt == "baseline":
                return "variants"
            return f_txt

        if f_target is not None:
            f_doc_target = norm(f_req.get("target") or f_plan.get("target"))
            if f_doc_target != norm(f_target):
                return False
        if f_scale is not None:
            f_doc_scale = norm(f_req.get("scale") or f_plan.get("scale"))
            if f_doc_scale != norm(f_scale):
                return False
        return True

    @classmethod
    def inferLatestRun(
        cls,
        f_benchmark_name_or_dir: str,
        f_target: Optional[str] = None,
        f_scale: Optional[str] = None,
    ) -> str:
        """Infer and locate the latest run directory from a benchmark name or root path.

        Args:
            f_benchmark_name_or_dir: Benchmark name ('lsmio', ...) or a benchmark root,
                runs/ directory or run root.
            f_target: Only consider runs whose manifest targets this benchmark. A
                benchmark name implies its own target.
            f_scale: Only consider runs of this scale.
        """
        if (
            not isinstance(f_benchmark_name_or_dir, str)
            or not f_benchmark_name_or_dir.strip()
        ):
            raise RunRootResolutionError(
                f"benchmark_name_or_dir must be a non-empty string, got: {f_benchmark_name_or_dir!r}"
            )
        if "\0" in f_benchmark_name_or_dir:
            raise RunRootResolutionError(
                f"benchmark_name_or_dir contains NUL byte: {f_benchmark_name_or_dir!r}"
            )

        f_raw = f_benchmark_name_or_dir.strip()
        f_name_lower = f_raw.lower()

        # Candidate roots
        f_candidates: List[str] = []

        if f_name_lower in ("ior", "lsmio", "lmp", "lammps"):
            if f_target is None:
                f_target = f_name_lower
            # Known benchmark names
            f_candidates.extend(
                [
                    os.path.expanduser(f"~/scratch/benchmark/{f_name_lower}"),
                    os.path.expanduser(f"~/scratch/{f_name_lower}"),
                    os.path.join(os.getcwd(), "benchmarks", f_name_lower),
                    os.path.join(os.getcwd(), "benchmark", f_name_lower),
                    os.path.join(os.getcwd(), f_name_lower),
                    os.path.expanduser(f"~/{f_name_lower}"),
                ]
            )
        else:
            # Explicit path passed
            f_abs = os.path.abspath(f_raw)
            f_candidates.append(f_abs)
            if os.path.basename(f_abs) == "runs":
                f_candidates.append(os.path.dirname(f_abs))

        f_valid_runs: List[str] = []

        for f_cand in f_candidates:
            if not os.path.exists(f_cand):
                continue

            # Check if f_cand itself is a run root directory with manifest.json
            f_direct_man = os.path.join(f_cand, "manifest.json")
            if os.path.exists(f_direct_man):
                try:
                    f_st = os.lstat(f_cand)
                    f_mst = os.lstat(f_direct_man)
                    if (
                        not stat.S_ISLNK(f_st.st_mode)
                        and stat.S_ISDIR(f_st.st_mode)
                        and not stat.S_ISLNK(f_mst.st_mode)
                        and stat.S_ISREG(f_mst.st_mode)
                    ):
                        if cls._manifestMatches(f_direct_man, f_target, f_scale):
                            f_valid_runs.append(f_cand)
                except OSError:
                    pass

            # Check if f_cand has a runs/ subdirectory or is a runs/ directory
            f_runs_dir = (
                f_cand
                if os.path.basename(f_cand) == "runs"
                else os.path.join(f_cand, "runs")
            )
            if os.path.isdir(f_runs_dir):
                try:
                    for f_entry in os.listdir(f_runs_dir):
                        f_run_path = os.path.join(f_runs_dir, f_entry)
                        f_man_path = os.path.join(f_run_path, "manifest.json")
                        try:
                            f_st = os.lstat(f_run_path)
                            if stat.S_ISLNK(f_st.st_mode) or not stat.S_ISDIR(
                                f_st.st_mode
                            ):
                                continue
                            if not os.path.exists(f_man_path):
                                continue
                            f_mst = os.lstat(f_man_path)
                            if stat.S_ISLNK(f_mst.st_mode) or not stat.S_ISREG(
                                f_mst.st_mode
                            ):
                                continue
                            if not cls._manifestMatches(f_man_path, f_target, f_scale):
                                continue
                            f_valid_runs.append(f_run_path)
                        except OSError:
                            continue
                except OSError:
                    pass

        if not f_valid_runs:
            f_filters = ""
            if f_target is not None or f_scale is not None:
                f_filters = f" (target={f_target!r}, scale={f_scale!r})"
            raise RunRootResolutionError(
                f"Cannot infer latest run for '{f_benchmark_name_or_dir}'{f_filters}: no valid run directories containing manifest.json found in {f_candidates}"
            )

        # Sort descending by run directory basename / name
        f_valid_runs.sort(key=lambda f_p: os.path.basename(f_p), reverse=True)
        return f_valid_runs[0]

    @classmethod
    def resolveTarget(
        cls,
        f_target: str,
        f_benchmark_root: Optional[str] = None,
        f_scale: Optional[str] = None,
        f_allow_partial: bool = False,
    ) -> ResolvedRun:
        """Resolve a target string (manifest path, run root directory, or benchmark name) into a ResolvedRun.

        A benchmark name selects the latest run of that benchmark (and of f_scale,
        when given) under '<f_benchmark_root>/runs' when a benchmark root is given.
        """
        if not isinstance(f_target, str) or not f_target.strip():
            raise RunRootResolutionError(
                f"Target must be a non-empty string, got: {f_target!r}"
            )
        if "\0" in f_target:
            raise RunRootResolutionError(f"Target contains NUL byte: {f_target!r}")

        f_raw = f_target.strip()
        f_norm_target = f_raw.lower()

        if f_norm_target in ("ior", "lsmio", "lmp", "lammps"):
            if f_benchmark_root is not None and f_benchmark_root.strip():
                f_bm_root = f_benchmark_root.strip()
                f_candidate_dir = os.path.join(f_bm_root, f_raw)
                if not os.path.isdir(os.path.join(f_candidate_dir, "runs")):
                    f_candidate_dir = f_bm_root
                f_run_root = cls.inferLatestRun(
                    f_candidate_dir, f_target=f_norm_target, f_scale=f_scale
                )
            else:
                f_run_root = cls.inferLatestRun(f_raw, f_scale=f_scale)
        elif f_raw.endswith("manifest.json"):
            f_abs_man = os.path.abspath(f_raw)
            f_run_root = os.path.dirname(f_abs_man)
        elif os.path.isdir(f_raw):
            f_abs_dir = os.path.abspath(f_raw)
            if os.path.exists(os.path.join(f_abs_dir, "manifest.json")):
                f_run_root = f_abs_dir
            else:
                f_run_root = cls.inferLatestRun(f_abs_dir)
        else:
            if f_benchmark_root is not None and f_benchmark_root.strip():
                f_run_root = cls.inferLatestRun(f_benchmark_root.strip())
            else:
                f_run_root = os.path.abspath(f_raw)

        return cls.resolve(f_run_root, f_allow_partial=f_allow_partial)


# Standard 26 metrics extracted from IOR summary tables
IOR_SUMMARY_COLUMNS: Tuple[str, ...] = (
    "Max(MiB)",
    "Min(MiB)",
    "Mean(MiB)",
    "StdDev",
    "Max(OPs)",
    "Min(OPs)",
    "Mean(OPs)",
    "StdDev",
    "Mean(s)",
    "Stonewall(s)",
    "Stonewall(MiB)",
    "Test#",
    "#Tasks",
    "tPN",
    "reps",
    "fPP",
    "reord",
    "reordoff",
    "reordrand",
    "seed",
    "segcnt",
    "blksiz",
    "xsize",
    "aggs(MiB)",
    "API",
    "RefNum",
)


class IorLogExtractor:
    """Extractor for IOR benchmark output logs and metrics."""

    @classmethod
    def findLogPath(cls, f_point: ResolvedPoint, f_combo: Combination) -> str:
        """Find and validate the IOR stdout/log file path for a point and combination."""
        f_logs_dir = os.path.join(f_point.pointDir, "logs")
        f_candidates = [
            os.path.join(f_logs_dir, f"ior_{f_combo.name}.stdout"),
            os.path.join(f_logs_dir, f"ior_{f_combo.name}.log"),
            os.path.join(f_logs_dir, f"{f_combo.name}.stdout"),
            os.path.join(f_logs_dir, f"{f_combo.name}.log"),
            os.path.join(f_point.pointDir, "output.log"),
            os.path.join(f_logs_dir, "output.log"),
        ]

        f_ctrl_rec = f_point.getControllerResult(f_combo)
        if f_ctrl_rec and f_ctrl_rec.payload and "stdout_path" in f_ctrl_rec.payload:
            f_candidates.insert(0, str(f_ctrl_rec.payload["stdout_path"]))
        if f_ctrl_rec and f_ctrl_rec.payload and "output_path" in f_ctrl_rec.payload:
            f_candidates.insert(0, str(f_ctrl_rec.payload["output_path"]))

        f_found: Optional[str] = None
        for f_cand in f_candidates:
            if os.path.exists(f_cand):
                f_found = f_cand
                break

        if f_found is None:
            raise ExtractionError(
                f"Log file does not exist for point '{f_point.pointId}' combination '{f_combo.name}': "
                f"searched {f_candidates}"
            )

        f_abs_path = os.path.abspath(f_found)
        try:
            f_stat = os.lstat(f_abs_path)
        except OSError as f_err:
            raise ExtractionError(
                f"Failed to access log file '{f_abs_path}': {f_err}"
            ) from f_err

        if stat.S_ISLNK(f_stat.st_mode):
            raise ExtractionError(f"Log file must not be a symlink: '{f_abs_path}'")
        if not stat.S_ISREG(f_stat.st_mode):
            raise ExtractionError(f"Log file must be a regular file: '{f_abs_path}'")

        return f_abs_path

    @classmethod
    def extractPointCombo(
        cls, f_point: ResolvedPoint, f_combo: Combination
    ) -> Dict[str, Any]:
        """Extract write and read metrics from IOR output log.

        'bmtool_lines' holds the summary lines ior-parse.sh would report verbatim.
        """
        f_log_path = cls.findLogPath(f_point, f_combo)

        try:
            with open(f_log_path, "r", encoding="utf-8", errors="replace") as f_f:
                f_lines = f_f.readlines()
        except OSError as f_err:
            raise ExtractionError(
                f"Failed to read log file '{f_log_path}': {f_err}"
            ) from f_err

        if not f_lines:
            raise ExtractionError(f"Log file is empty: '{f_log_path}'")

        f_head_line: Optional[str] = None
        f_read_line: Optional[str] = None
        f_write_line: Optional[str] = None
        f_found_summary = False

        for f_line in f_lines:
            f_stripped = f_line.strip()
            if not f_found_summary:
                if f_stripped.startswith("Summary of all tests"):
                    f_found_summary = True
                continue
            if f_stripped.startswith("Operation") and (
                "Max(MiB)" in f_stripped or "Max" in f_stripped
            ):
                f_head_line = f_stripped
                continue
            if f_stripped.startswith("write"):
                f_write_line = f_stripped
                continue
            if f_stripped.startswith("read"):
                f_read_line = f_stripped
                continue
            if f_head_line and f_read_line and f_write_line:
                break

        if (
            not f_found_summary
            or not f_head_line
            or not f_write_line
            or not f_read_line
        ):
            raise ExtractionError(
                f"Malformed IOR output log '{f_log_path}': missing 'Summary of all tests' section or operation rows"
            )

        f_heads = f_head_line.split()[1:]
        f_reads = f_read_line.split()[1:]
        f_writes = f_write_line.split()[1:]

        if (
            len(f_heads) < 20
            or len(f_reads) < len(f_heads)
            or len(f_writes) < len(f_heads)
        ):
            raise ExtractionError(
                f"Malformed IOR summary in log '{f_log_path}': expected >= 20 columns, got heads={len(f_heads)}, writes={len(f_writes)}, reads={len(f_reads)}"
            )

        f_res: Dict[str, Any] = {"write": {}, "read": {}}

        # The second 'StdDev' (OPs) gets its own key instead of overwriting the first
        f_col_keys = data.iorSummaryKeys(IOR_SUMMARY_COLUMNS)
        for f_i in range(len(IOR_SUMMARY_COLUMNS)):
            f_col_name = f_col_keys[f_i]
            f_w_raw = f_writes[f_i] if f_i < len(f_writes) else ""
            f_r_raw = f_reads[f_i] if f_i < len(f_reads) else ""

            if f_col_name in (
                "Max(MiB)",
                "Min(MiB)",
                "Mean(MiB)",
                "StdDev",
                "Max(OPs)",
                "Min(OPs)",
                "Mean(OPs)",
                data.IOR_OPS_STDDEV_KEY,
                "Mean(s)",
                "aggs(MiB)",
            ):
                f_res["write"][f_col_name] = parseFloat(f_w_raw)
                f_res["read"][f_col_name] = parseFloat(f_r_raw)
            elif f_col_name in (
                "Test#",
                "#Tasks",
                "tPN",
                "reps",
                "fPP",
                "reord",
                "reordoff",
                "reordrand",
                "seed",
                "segcnt",
                "blksiz",
                "xsize",
                "RefNum",
            ):
                f_res["write"][f_col_name] = (
                    parseInt(f_w_raw) if f_w_raw.isdigit() else f_w_raw
                )
                f_res["read"][f_col_name] = (
                    parseInt(f_r_raw) if f_r_raw.isdigit() else f_r_raw
                )
            else:
                f_res["write"][f_col_name] = f_w_raw
                f_res["read"][f_col_name] = f_r_raw

        f_res["write"]["_raw_values"] = [
            f_writes[i] if i < len(f_writes) else "" for i in range(26)
        ]
        f_res["read"]["_raw_values"] = [
            f_reads[i] if i < len(f_reads) else "" for i in range(26)
        ]

        # The lines bmtool ior-parse.sh copies into ior-report.csv
        try:
            f_res["bmtool_lines"] = data.iorSummaryLines(
                data.readBmtoolLines(f_log_path)
            )
        except OSError as f_err:
            raise ExtractionError(
                f"Failed to read log file '{f_log_path}': {f_err}"
            ) from f_err

        return f_res


class LsmioLogExtractor:
    """Extractor for LSMIO benchmark per-rank logs and iteration metrics."""

    @classmethod
    def extractPointCombo(
        cls, f_point: ResolvedPoint, f_combo: Combination
    ) -> Dict[str, Any]:
        """Extract iteration and summary metrics across all rank logs for a scale point."""
        f_tasks = f_point.scalePoint.tasks
        f_w_iters: List[float] = []
        f_r_iters: List[float] = []

        f_first_w_line = ""
        f_first_r_line = ""

        f_logs_dir = os.path.join(f_point.pointDir, "logs")
        # bmtool lsmio-parse.sh aggregate: summed 'write,'/'read,' lines across ranks
        f_bm_agg = data.LsmioBmtoolAggregate()

        for f_rank in range(f_tasks):
            f_candidates = [
                os.path.join(f_logs_dir, f_combo.name, f"rank_{f_rank}.log"),
                os.path.join(f_logs_dir, f"{f_combo.name}_rank_{f_rank}.log"),
                os.path.join(
                    f_point.pointDir, "ranks", str(f_rank), f_combo.name, "output.log"
                ),
                os.path.join(f_logs_dir, f"rank_{f_rank}.log"),
            ]

            f_rank_rec = f_point.getRankResult(f_rank, f_combo)
            if (
                f_rank_rec
                and f_rank_rec.payload
                and "stdout_path" in f_rank_rec.payload
            ):
                f_candidates.insert(0, str(f_rank_rec.payload["stdout_path"]))
            if f_rank_rec and f_rank_rec.payload and "log_path" in f_rank_rec.payload:
                f_candidates.insert(0, str(f_rank_rec.payload["log_path"]))

            f_log_path: Optional[str] = None
            for f_cand in f_candidates:
                if os.path.exists(f_cand):
                    f_log_path = f_cand
                    break

            if f_log_path is None:
                raise ExtractionError(
                    f"Rank log file does not exist for point '{f_point.pointId}' combo '{f_combo.name}' rank {f_rank}: "
                    f"searched {f_candidates}"
                )

            f_abs_path = os.path.abspath(f_log_path)
            try:
                f_stat = os.lstat(f_abs_path)
            except OSError as f_err:
                raise ExtractionError(
                    f"Failed to access rank log '{f_abs_path}': {f_err}"
                ) from f_err

            if stat.S_ISLNK(f_stat.st_mode):
                raise ExtractionError(f"Rank log must not be a symlink: '{f_abs_path}'")
            if not stat.S_ISREG(f_stat.st_mode):
                raise ExtractionError(
                    f"Rank log must be a regular file: '{f_abs_path}'"
                )

            try:
                with open(f_abs_path, "r", encoding="utf-8", errors="replace") as f_f:
                    f_lines = f_f.readlines()
            except OSError as f_err:
                raise ExtractionError(
                    f"Failed to read rank log '{f_abs_path}': {f_err}"
                ) from f_err

            if not f_lines:
                raise ExtractionError(f"Rank log is empty: '{f_abs_path}'")

            try:
                f_bm_agg.addLines(data.readBmtoolLines(f_abs_path))
            except OSError as f_err:
                raise ExtractionError(
                    f"Failed to read rank log '{f_abs_path}': {f_err}"
                ) from f_err

            f_found_w_summary = False
            f_found_r_summary = False

            for f_line in f_lines:
                f_stripped = f_line.strip()
                if f_stripped.startswith("iwrite,"):
                    f_parts = f_stripped.split(",")
                    if len(f_parts) > 1:
                        f_w_iters.append(parseFloat(f_parts[1]))
                elif f_stripped.startswith("iread,"):
                    f_parts = f_stripped.split(",")
                    if len(f_parts) > 1:
                        f_r_iters.append(parseFloat(f_parts[1]))

                if not f_found_w_summary and not f_first_w_line:
                    if f_stripped.startswith("Bench-WRITE:"):
                        f_found_w_summary = True
                        continue
                if f_found_w_summary and not f_first_w_line:
                    if f_stripped.startswith("write,") or f_stripped.startswith(
                        "write"
                    ):
                        f_first_w_line = f_stripped
                        f_found_w_summary = False
                        continue

                if not f_found_r_summary and not f_first_r_line:
                    if f_stripped.startswith("Bench-READ:"):
                        f_found_r_summary = True
                        continue
                if f_found_r_summary and not f_first_r_line:
                    if f_stripped.startswith("read,") or f_stripped.startswith("read"):
                        f_first_r_line = f_stripped
                        f_found_r_summary = False
                        continue

                if not f_first_w_line and f_stripped.startswith("write,"):
                    f_first_w_line = f_stripped
                if not f_first_r_line and f_stripped.startswith("read,"):
                    f_first_r_line = f_stripped

        if not f_first_w_line:
            f_first_w_line = "write,0.0,0.0,0,0,0"
        if not f_first_r_line:
            f_first_r_line = "read,0.0,0.0,0,0,0"

        f_max_w = max(f_w_iters) if f_w_iters else 0.0
        f_min_w = min(f_w_iters) if f_w_iters else 0.0
        f_mean_w = (math.fsum(f_w_iters) / len(f_w_iters)) if f_w_iters else 0.0

        f_max_r = max(f_r_iters) if f_r_iters else 0.0
        f_min_r = min(f_r_iters) if f_r_iters else 0.0
        f_mean_r = (math.fsum(f_r_iters) / len(f_r_iters)) if f_r_iters else 0.0

        f_w_parts = f_first_w_line.split(",")
        f_w_bw = parseFloat(f_w_parts[1]) if len(f_w_parts) > 1 else 0.0
        f_w_lat = parseFloat(f_w_parts[2]) if len(f_w_parts) > 2 else 0.0
        f_w_blk = parseInt(f_w_parts[3]) if len(f_w_parts) > 3 else 0
        f_w_xfer = parseInt(f_w_parts[4]) if len(f_w_parts) > 4 else 0
        f_w_iter = parseInt(f_w_parts[5]) if len(f_w_parts) > 5 else len(f_w_iters)

        f_r_parts = f_first_r_line.split(",")
        f_r_bw = parseFloat(f_r_parts[1]) if len(f_r_parts) > 1 else 0.0
        f_r_lat = parseFloat(f_r_parts[2]) if len(f_r_parts) > 2 else 0.0
        f_r_blk = parseInt(f_r_parts[3]) if len(f_r_parts) > 3 else 0
        f_r_xfer = parseInt(f_r_parts[4]) if len(f_r_parts) > 4 else 0
        f_r_iter = parseInt(f_r_parts[5]) if len(f_r_parts) > 5 else len(f_r_iters)

        return {
            "bmtool_agg": {
                "lines": f_bm_agg.aggLines(),
                "ranks": f_bm_agg.fileCount,
            },
            "write": {
                "bmtool_row": f_bm_agg.row("write"),
                "first_line": f_first_w_line,
                "bw": f_w_bw,
                "latency": f_w_lat,
                "block_kib": f_w_blk,
                "xfer_kib": f_w_xfer,
                "iter": f_w_iter,
                "max": f_max_w,
                "min": f_min_w,
                "mean": f_mean_w,
                "iterations": f_w_iters,
            },
            "read": {
                "bmtool_row": f_bm_agg.row("read"),
                "first_line": f_first_r_line,
                "bw": f_r_bw,
                "latency": f_r_lat,
                "block_kib": f_r_blk,
                "xfer_kib": f_r_xfer,
                "iter": f_r_iter,
                "max": f_max_r,
                "min": f_min_r,
                "mean": f_mean_r,
                "iterations": f_r_iters,
            },
        }


class LmpLogExtractor:
    """Extractor for LAMMPS benchmark output logs and throughput metrics."""

    @classmethod
    def findLogPath(cls, f_point: ResolvedPoint, f_combo: Combination) -> str:
        """Find and validate the LMP stdout/log file path for a point and combination."""
        f_logs_dir = os.path.join(f_point.pointDir, "logs")
        f_candidates = [
            os.path.join(f_logs_dir, f"lmp_{f_combo.name}.stdout"),
            os.path.join(f_logs_dir, f"lmp_{f_combo.name}.log"),
            os.path.join(f_logs_dir, f"{f_combo.name}.stdout"),
            os.path.join(f_logs_dir, f"{f_combo.name}.log"),
            os.path.join(f_point.pointDir, "output.log"),
            os.path.join(f_logs_dir, "output.log"),
        ]

        f_ctrl_rec = f_point.getControllerResult(f_combo)
        if f_ctrl_rec and f_ctrl_rec.payload and "stdout_path" in f_ctrl_rec.payload:
            f_candidates.insert(0, str(f_ctrl_rec.payload["stdout_path"]))
        if f_ctrl_rec and f_ctrl_rec.payload and "output_path" in f_ctrl_rec.payload:
            f_candidates.insert(0, str(f_ctrl_rec.payload["output_path"]))

        f_found: Optional[str] = None
        for f_cand in f_candidates:
            if os.path.exists(f_cand):
                f_found = f_cand
                break

        if f_found is None:
            raise ExtractionError(
                f"Log file does not exist for point '{f_point.pointId}' combination '{f_combo.name}': "
                f"searched {f_candidates}"
            )

        f_abs_path = os.path.abspath(f_found)
        try:
            f_stat = os.lstat(f_abs_path)
        except OSError as f_err:
            raise ExtractionError(
                f"Failed to access log file '{f_abs_path}': {f_err}"
            ) from f_err

        if stat.S_ISLNK(f_stat.st_mode):
            raise ExtractionError(f"Log file must not be a symlink: '{f_abs_path}'")
        if not stat.S_ISREG(f_stat.st_mode):
            raise ExtractionError(f"Log file must be a regular file: '{f_abs_path}'")

        return f_abs_path

    @classmethod
    def extractPointCombo(
        cls, f_point: ResolvedPoint, f_combo: Combination
    ) -> Dict[str, Any]:
        """Extract write throughput from LMP output log.

        Like tools/bmtool/parse/lmp-parse.sh, the last line matching '^.write,' (the
        LSMIO 'iwrite,<MiB/s>,...' lines of an LSMIO-enabled LAMMPS) is the result:
        'bmtool_field' is what lmp-report.csv shows after 'n,rf,bs,' (the line up to
        its first colon) and its second comma field the throughput. A log without
        such a line falls back to the last 'write,'/'write:' line (lsmiotool only;
        bmtool reports nothing for it).
        """
        f_log_path = cls.findLogPath(f_point, f_combo)

        try:
            f_lines = data.readBmtoolLines(f_log_path)
        except OSError as f_err:
            raise ExtractionError(
                f"Failed to read log file '{f_log_path}': {f_err}"
            ) from f_err

        if not f_lines:
            raise ExtractionError(f"Log file is empty: '{f_log_path}'")

        f_bmtool_line: Optional[str] = None
        f_fallback_line: Optional[str] = None
        f_throughput: Optional[float] = None

        for f_line in f_lines:
            if data.isLmpResultLine(f_line):
                f_bmtool_line = f_line
                continue
            f_stripped = f_line.strip()
            if (
                f_stripped.startswith(".write,")
                or f_stripped.startswith("write,")
                or f_stripped.startswith("write:")
                or f_stripped.startswith(".write:")
            ):
                if ":" in f_stripped:
                    f_parts = [f_p.strip() for f_p in f_stripped.split(":")]
                else:
                    f_parts = [f_p.strip() for f_p in f_stripped.split(",")]

                if len(f_parts) >= 3:
                    f_val = parseFloat(f_parts[2])
                elif len(f_parts) >= 2:
                    f_val = parseFloat(f_parts[1])
                else:
                    continue
                if f_val > 0.0 or f_throughput is None:
                    f_throughput = f_val
                    f_fallback_line = f_stripped

        if f_bmtool_line is not None:
            f_throughput = data.lmpLineThroughput(f_bmtool_line)
            f_report_line = f_bmtool_line
        elif f_throughput is not None and f_fallback_line is not None:
            f_report_line = f_fallback_line
        else:
            raise ExtractionError(
                f"Malformed LMP output log '{f_log_path}': could not extract write throughput metric"
            )

        return {
            "bmtool_field": f_report_line.split(":")[0],
            "write": {
                "throughput": f_throughput,
                "bw(MiB/s)": f_throughput,
            },
        }


def _bmtoolComboOrder(f_combo: Combination) -> Tuple[int, int]:
    """Sort key for bmtool's combination loop order: rf 4, 16; bs 64K, 1M, 8M."""
    f_rf = str(f_combo.stripe_count)
    f_bs = str(f_combo.block_size)
    return (
        data.BMTOOL_STRIPE_COUNTS.index(f_rf)
        if f_rf in data.BMTOOL_STRIPE_COUNTS
        else len(data.BMTOOL_STRIPE_COUNTS),
        data.BMTOOL_BLOCK_SIZES.index(f_bs)
        if f_bs in data.BMTOOL_BLOCK_SIZES
        else len(data.BMTOOL_BLOCK_SIZES),
    )


class ConsoleSummaryFormatter:
    """Formats benchmark results into a clean, aligned ASCII summary table."""

    HEADERS: List[str] = [
        "Benchmark",
        "Variant",
        "Point ID",
        "Tasks/Cores",
        "Combination",
        "Operation",
        "Throughput MB/s",
        "IOPS",
        "Duration",
    ]
    TABLE_HEADERS: Tuple[str, ...] = tuple(HEADERS)

    @classmethod
    def formatSummaryTable(
        cls, f_resolved_run: ResolvedRun, f_extracted_data: Mapping[str, Any]
    ) -> str:
        """Format an ASCII summary table for the parsed benchmark run.

        Columns:
        Benchmark | Variant | Point ID | Tasks/Cores | Combination | Operation | Throughput MB/s | IOPS | Duration
        """
        f_headers = list(cls.HEADERS)

        f_rows: List[List[str]] = []
        f_bm = f_resolved_run.target.upper()
        f_variant = f_resolved_run.variant or "-"

        for f_pt in f_resolved_run.points:
            f_pt_id = f_pt.pointId
            f_tasks_cores = (
                f"{f_pt.scalePoint.tasks}/{f_pt.scalePoint.nodes * f_pt.scalePoint.ppn}"
            )

            for f_combo in f_resolved_run.plan.combinations:
                if f_combo.name not in f_extracted_data.get(f_pt_id, {}):
                    continue  # skipped as incomplete (partial run)
                f_combo_data = f_extracted_data.get(f_pt_id, {}).get(f_combo.name, {})

                if f_bm == "IOR":
                    for f_op in ("write", "read"):
                        f_op_data = f_combo_data.get(f_op, {})
                        f_tp = f_op_data.get(
                            "Mean(MiB)", f_op_data.get("Max(MiB)", "N/A")
                        )
                        f_tp_str = (
                            f"{f_tp:.2f}"
                            if isinstance(f_tp, (int, float))
                            else str(f_tp)
                        )

                        f_iops = f_op_data.get(
                            "Mean(OPs)", f_op_data.get("Max(OPs)", "N/A")
                        )
                        f_iops_str = (
                            f"{f_iops:.2f}"
                            if isinstance(f_iops, (int, float))
                            else str(f_iops)
                        )

                        f_dur = f_op_data.get("Mean(s)", "N/A")
                        f_dur_str = (
                            f"{f_dur:.2f}s"
                            if isinstance(f_dur, (int, float))
                            else str(f_dur)
                        )

                        f_rows.append(
                            [
                                f_bm,
                                f_variant,
                                f_pt_id,
                                f_tasks_cores,
                                f_combo.name,
                                f_op,
                                f_tp_str,
                                f_iops_str,
                                f_dur_str,
                            ]
                        )

                elif f_bm == "LSMIO":
                    for f_op in ("write", "read"):
                        f_op_data = f_combo_data.get(f_op, {})
                        f_tp = f_op_data.get("mean", f_op_data.get("bw", "N/A"))
                        f_tp_str = (
                            f"{f_tp:.2f}"
                            if isinstance(f_tp, (int, float))
                            else str(f_tp)
                        )

                        f_lat = f_op_data.get("latency", "N/A")
                        f_lat_str = (
                            f"{f_lat:.3f}ms"
                            if isinstance(f_lat, (int, float))
                            else "N/A"
                        )

                        f_rows.append(
                            [
                                f_bm,
                                f_variant,
                                f_pt_id,
                                f_tasks_cores,
                                f_combo.name,
                                f_op,
                                f_tp_str,
                                "N/A",
                                f_lat_str,
                            ]
                        )

                elif f_bm in ("LMP", "LAMMPS"):
                    f_op_data = f_combo_data.get("write", {})
                    f_tp = f_op_data.get("throughput", "N/A")
                    f_tp_str = (
                        f"{f_tp:.2f}" if isinstance(f_tp, (int, float)) else str(f_tp)
                    )

                    f_rows.append(
                        [
                            f_bm,
                            f_variant,
                            f_pt_id,
                            f_tasks_cores,
                            f_combo.name,
                            "write",
                            f_tp_str,
                            "N/A",
                            "N/A",
                        ]
                    )

        f_col_widths = [len(h) for h in f_headers]
        for f_row in f_rows:
            for f_i, f_val in enumerate(f_row):
                f_col_widths[f_i] = max(f_col_widths[f_i], len(f_val))

        f_border = "+" + "+".join("-" * (w + 2) for w in f_col_widths) + "+"
        f_header_line = (
            "| "
            + " | ".join(f_h.ljust(f_col_widths[i]) for i, f_h in enumerate(f_headers))
            + " |"
        )

        f_output_lines = [f_border, f_header_line, f_border]
        for f_row in f_rows:
            f_row_line = (
                "| "
                + " | ".join(f_v.ljust(f_col_widths[i]) for i, f_v in enumerate(f_row))
                + " |"
            )
            f_output_lines.append(f_row_line)
        f_output_lines.append(f_border)

        return "\n".join(f_output_lines)


class ReportGenerator:
    """Base class for benchmark report generators."""

    @classmethod
    def exportCsv(
        cls, f_rows: Sequence[Union[str, Sequence[Any]]], f_out_file: str
    ) -> None:
        """Export rows to CSV file."""
        f_out_dir = os.path.dirname(os.path.abspath(f_out_file))
        os.makedirs(f_out_dir, exist_ok=True)
        with open(f_out_file, "w", newline="", encoding="utf-8") as f_f:
            f_writer = csv.writer(f_f)
            for f_row in f_rows:
                if isinstance(f_row, str):
                    f_f.write(f_row.rstrip() + "\n")
                elif isinstance(f_row, (list, tuple)):
                    f_writer.writerow([str(f_v) for f_v in f_row])

    @classmethod
    def exportJson(cls, f_data: Any, f_out_file: str) -> None:
        """Export structured dictionary or list to JSON file."""
        f_out_dir = os.path.dirname(os.path.abspath(f_out_file))
        os.makedirs(f_out_dir, exist_ok=True)
        with open(f_out_file, "w", encoding="utf-8") as f_f:
            json.dump(f_data, f_f, indent=2)

    @classmethod
    def generate(
        cls,
        f_resolved_run: ResolvedRun,
        f_extracted_data: Mapping[str, Any],
        f_out_dir: str,
        f_format: str = "csv",
    ) -> Dict[str, str]:
        """Generate benchmark reports. Subclasses override this."""
        raise NotImplementedError


class IorReportGenerator(ReportGenerator):
    """Generates IOR master CSV and JSON reports."""

    @classmethod
    def generate(
        cls,
        f_resolved_run: ResolvedRun,
        f_extracted_data: Mapping[str, Any],
        f_out_dir: str,
        f_format: str = "csv",
    ) -> Dict[str, str]:
        f_res: Dict[str, str] = {}
        f_master_file = os.path.join(f_out_dir, "ior-report.csv")
        # Rows per (point, combination), emitted in the shell glob order ior-parse.sh
        # visits '<n>/<date>/out-<infix>-<rf>-<bs>-...' files in
        f_groups: List[Tuple[Tuple[str, str, str], List[str]]] = []
        for f_pt in f_resolved_run.points:
            # bmtool takes the node count from the outputs dir name: no padding
            f_node_str = str(f_pt.scalePoint.nodes)

            for f_combo in f_resolved_run.plan.combinations:
                f_group_rows: List[str] = []
                f_groups.append(
                    (
                        data.bmtoolCollationKey(
                            f"{f_node_str}/2000-01-01/out-x-{f_combo.stripe_count}"
                            f"-{f_combo.block_size}-2000-01-01-node000-0.txt"
                        ),
                        f_group_rows,
                    )
                )
                f_s_count = str(f_combo.stripe_count)
                f_s_size = str(f_combo.block_size)
                f_combo_data = f_extracted_data.get(f_pt.pointId, {}).get(
                    f_combo.name, {}
                )

                # ior-parse.sh: the log's summary lines, spaces runs turned into commas
                f_bm_lines = f_combo_data.get("bmtool_lines")
                if f_bm_lines:
                    f_group_rows.extend(
                        data.bmtoolIorRow(f_node_str, f_s_count, f_s_size, f_line)
                        for f_line in f_bm_lines
                    )
                    continue

                for f_op in ("write", "read"):
                    f_op_data = f_combo_data.get(f_op, {})
                    if not f_op_data:
                        continue
                    if "_raw_values" in f_op_data:
                        f_vals = [str(f_v) for f_v in f_op_data["_raw_values"]]
                    else:
                        f_vals = [
                            str(f_op_data.get(k, ""))
                            for k in data.iorSummaryKeys(IOR_SUMMARY_COLUMNS)
                        ]

                    f_row_str = (
                        f"{f_node_str},{f_s_count},{f_s_size},{f_op},"
                        + ",".join(f_vals)
                    )
                    f_group_rows.append(f_row_str)

        f_rows = [
            f_row
            for _f_key, f_group in sorted(f_groups, key=lambda f_g: f_g[0])
            for f_row in f_group
        ]
        if not f_rows:
            Console.warning(
                f"No IOR report rows for run '{f_resolved_run.runId}'; "
                f"not writing {f_master_file}"
            )
            return f_res
        data.writeBmtoolLines(f_master_file, f_rows)
        f_res["ior-report.csv"] = f_master_file
        f_res["master_csv"] = f_master_file

        if f_format.lower() == "json":
            f_json_file = os.path.join(f_out_dir, "ior-report.json")
            f_json_data = {
                "run_id": f_resolved_run.runId,
                "target": f_resolved_run.target,
                "scale": f_resolved_run.scale,
                "points": [
                    {
                        "point_id": f_pt.pointId,
                        "nodes": f_pt.scalePoint.nodes,
                        "tasks": f_pt.scalePoint.tasks,
                        "combinations": f_extracted_data.get(f_pt.pointId, {}),
                    }
                    for f_pt in f_resolved_run.points
                ],
            }
            cls.exportJson(f_json_data, f_json_file)
            f_res["ior-report.json"] = f_json_file
            f_res["json"] = f_json_file

        return f_res


class LsmioReportGenerator(ReportGenerator):
    """Generates bmtool-identical LSMIO agg-<rf>-<bs>-report.csv / lsm-report.csv and JSON reports."""

    @classmethod
    def generate(
        cls,
        f_resolved_run: ResolvedRun,
        f_extracted_data: Mapping[str, Any],
        f_out_dir: str,
        f_format: str = "csv",
    ) -> Dict[str, str]:
        """Write <nodes>/agg-<rf>-<bs>-report.csv per point/combination and lsm-report.csv.

        The content matches tools/bmtool/parse/lsmio-parse.sh for the same rank logs:
        each agg file holds the first rank's header plus the 'write'/'read' lines
        summed across ranks, and lsm-report.csv lists their rows in bmtool's order.
        lsm-report.csv is not written when there are no rows.
        """
        f_res: Dict[str, str] = {}
        f_agg_files: Dict[str, List[str]] = {}

        # Stage 1: <nodes>/agg-<stripe_count>-<stripe_size>-report.csv for each point
        for f_pt in f_resolved_run.points:
            f_n_part = str(f_pt.scalePoint.nodes)

            for f_combo in f_resolved_run.plan.combinations:
                f_s_count = str(f_combo.stripe_count)
                f_s_size = str(f_combo.block_size)
                f_combo_data = f_extracted_data.get(f_pt.pointId, {}).get(f_combo.name)
                if f_combo_data is None:
                    continue  # skipped (and warned about) by extractRun
                f_agg_lines = f_combo_data.get("bmtool_agg", {}).get("lines")
                if not f_agg_lines:
                    Console.warning(
                        f"No rank aggregate for point '{f_pt.pointId}' combination "
                        f"'{f_combo.name}'; skipping its agg report"
                    )
                    continue

                f_agg_name = data.aggReportFileName(f_s_count, f_s_size)
                f_agg_file_path = os.path.join(f_out_dir, f_n_part, f_agg_name)
                data.writeBmtoolLines(f_agg_file_path, f_agg_lines)
                f_agg_files[f"{f_n_part}/{f_agg_name}"] = list(f_agg_lines)
                f_res[f"agg-{f_n_part}-{f_s_count}-{f_s_size}"] = f_agg_file_path

        # Stage 2: master lsm-report.csv in bmtool's (shell glob) order
        f_master_rows: List[str] = []
        for f_rel in sorted(f_agg_files, key=data.bmtoolCollationKey):
            f_master_rows.extend(data.bmtoolReportRows(f_rel, f_agg_files[f_rel]))

        f_master_file = os.path.join(f_out_dir, data.LSM_REPORT_FILE)
        if f_master_rows:
            data.writeBmtoolLines(f_master_file, f_master_rows)
            f_res["lsm-report.csv"] = f_master_file
            f_res["master_csv"] = f_master_file
        else:
            Console.warning(
                f"No LSMIO report rows for run '{f_resolved_run.runId}'; "
                f"not writing {f_master_file}"
            )

        if f_format.lower() == "json":
            f_json_file = os.path.join(f_out_dir, "lsm-report.json")
            f_json_data = {
                "run_id": f_resolved_run.runId,
                "target": f_resolved_run.target,
                "scale": f_resolved_run.scale,
                "points": [
                    {
                        "point_id": f_pt.pointId,
                        "nodes": f_pt.scalePoint.nodes,
                        "tasks": f_pt.scalePoint.tasks,
                        "combinations": f_extracted_data.get(f_pt.pointId, {}),
                    }
                    for f_pt in f_resolved_run.points
                ],
            }
            cls.exportJson(f_json_data, f_json_file)
            f_res["lsm-report.json"] = f_json_file
            f_res["json"] = f_json_file

        return f_res


class LmpReportGenerator(ReportGenerator):
    """Generates LAMMPS master CSV and JSON reports."""

    @classmethod
    def generate(
        cls,
        f_resolved_run: ResolvedRun,
        f_extracted_data: Mapping[str, Any],
        f_out_dir: str,
        f_format: str = "csv",
    ) -> Dict[str, str]:
        f_res: Dict[str, str] = {}
        f_master_file = os.path.join(f_out_dir, "lmp-report.csv")
        f_master_rows: List[str] = []

        for f_pt in f_resolved_run.points:
            f_n_part = str(f_pt.scalePoint.nodes)

            # lmp-parse.sh row order: rf 4 16, bs 64K 1M 8M
            for f_combo in sorted(
                f_resolved_run.plan.combinations, key=_bmtoolComboOrder
            ):
                f_s_count = str(f_combo.stripe_count)
                f_s_size = str(f_combo.block_size)
                f_combo_data = f_extracted_data.get(f_pt.pointId, {}).get(f_combo.name)
                if not f_combo_data:
                    continue

                # bmtool: 'n,rf,bs,' + the matched log line up to its first colon
                f_field = f_combo_data.get("bmtool_field")
                if f_field is None:
                    f_field = str(f_combo_data.get("write", {}).get("throughput", ""))
                f_master_rows.append(f"{f_n_part},{f_s_count},{f_s_size},{f_field}")

        if not f_master_rows:
            Console.warning(
                f"No LMP report rows for run '{f_resolved_run.runId}'; "
                f"not writing {f_master_file}"
            )
            return f_res
        data.writeBmtoolLines(f_master_file, f_master_rows)
        f_res["lmp-report.csv"] = f_master_file
        f_res["master_csv"] = f_master_file

        if f_format.lower() == "json":
            f_json_file = os.path.join(f_out_dir, "lmp-report.json")
            f_json_data = {
                "run_id": f_resolved_run.runId,
                "target": f_resolved_run.target,
                "scale": f_resolved_run.scale,
                "points": [
                    {
                        "point_id": f_pt.pointId,
                        "nodes": f_pt.scalePoint.nodes,
                        "tasks": f_pt.scalePoint.tasks,
                        "combinations": f_extracted_data.get(f_pt.pointId, {}),
                    }
                    for f_pt in f_resolved_run.points
                ],
            }
            cls.exportJson(f_json_data, f_json_file)
            f_res["lmp-report.json"] = f_json_file
            f_res["json"] = f_json_file

        return f_res


def _recordSucceeded(f_rec: Optional[EvidenceRecord]) -> bool:
    """True when a controller/rank result record reports success (exit code 0)."""
    if f_rec is None:
        return False
    f_payload = f_rec.payload or {}
    for f_key in ("exit_code", "exit_status"):
        if f_payload.get(f_key) is not None:
            try:
                return int(f_payload[f_key]) == 0
            except (TypeError, ValueError):
                return False
    return str(f_payload.get("status", "")).strip().lower() in (
        "success",
        "succeeded",
        "ok",
    )


def incompleteReason(
    f_target: str, f_point: ResolvedPoint, f_combo: Combination
) -> Optional[str]:
    """Why a combination of a point that did not succeed has no complete output, or None.

    A succeeded point was verified by state reconciliation. Otherwise an LSMIO
    combination needs a successful result from every rank, and an IOR/LMP one a
    successful controller result.
    """
    if f_point.state == PointRunState.SUCCEEDED:
        return None
    if f_target == "lsmio":
        for f_rank in range(f_point.scalePoint.tasks):
            if not _recordSucceeded(f_point.getRankResult(f_rank, f_combo)):
                return f"rank {f_rank} has no successful result"
        return None
    if not _recordSucceeded(f_point.getControllerResult(f_combo)):
        return "no successful controller result"
    return None


def extractRun(
    f_resolved_run: ResolvedRun,
    f_skip_incomplete: bool = False,
    f_warnings: Optional[List[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Extract metrics for all points and combinations in a resolved run.

    Args:
        f_resolved_run: The run (resolved with f_allow_partial for a partial run).
        f_skip_incomplete: Skip, with a warning, every combination without complete
            output (see incompleteReason) or whose logs cannot be extracted, instead
            of raising; skipped combinations are absent from the result. bmtool's
            parsers likewise report whatever output exists.
        f_warnings: Collects the warnings; when None they are logged.

    Raises:
        ExtractionError: Without f_skip_incomplete, on the first unusable log.
    """
    f_target = f_resolved_run.target.lower()
    if f_target not in ("ior", "lsmio", "lmp", "lammps"):
        raise ExtractionError(
            f"Unsupported benchmark target '{f_target}' for extraction"
        )
    f_data: Dict[str, Dict[str, Any]] = {}

    def warn(f_msg: str) -> None:
        if f_warnings is None:
            Console.warning(f_msg)
        else:
            f_warnings.append(f_msg)

    for f_pt in f_resolved_run.points:
        f_data[f_pt.pointId] = {}
        for f_combo in f_resolved_run.plan.combinations:
            if f_skip_incomplete:
                f_reason = incompleteReason(f_target, f_pt, f_combo)
                if f_reason is not None:
                    warn(
                        f"Skipping point '{f_pt.pointId}' combination '{f_combo.name}' "
                        f"(point state: {f_pt.state.value}): {f_reason}"
                    )
                    continue
            try:
                if f_target == "ior":
                    f_res = IorLogExtractor.extractPointCombo(f_pt, f_combo)
                elif f_target == "lsmio":
                    f_res = LsmioLogExtractor.extractPointCombo(f_pt, f_combo)
                else:
                    f_res = LmpLogExtractor.extractPointCombo(f_pt, f_combo)
            except ExtractionError as f_err:
                if not f_skip_incomplete:
                    raise
                warn(
                    f"Skipping point '{f_pt.pointId}' combination '{f_combo.name}': {f_err}"
                )
                continue
            f_data[f_pt.pointId][f_combo.name] = f_res

    return f_data


def countExtracted(f_extracted_data: Mapping[str, Mapping[str, Any]]) -> int:
    """Number of (point, combination) entries extractRun produced."""
    return sum(len(f_combos) for f_combos in f_extracted_data.values())


def generateReports(
    f_resolved_run: ResolvedRun,
    f_extracted_data: Mapping[str, Any],
    f_out_dir: str,
    f_format: str = "csv",
) -> Dict[str, str]:
    """Dispatch report generation to the appropriate ReportGenerator."""
    f_target = f_resolved_run.target.lower()
    if f_target == "ior":
        return IorReportGenerator.generate(
            f_resolved_run, f_extracted_data, f_out_dir, f_format
        )
    elif f_target == "lsmio":
        return LsmioReportGenerator.generate(
            f_resolved_run, f_extracted_data, f_out_dir, f_format
        )
    elif f_target in ("lmp", "lammps"):
        return LmpReportGenerator.generate(
            f_resolved_run, f_extracted_data, f_out_dir, f_format
        )
    else:
        raise RunParseError(
            f"Unsupported benchmark target '{f_target}' for report generation"
        )
