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

from datetime import datetime, timezone
from enum import Enum
import json
import os
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple, Union

from lsmiotool.lib.artifacts import (
    ArtifactError,
    ArtifactLayout,
    ContainmentError,
    STANDARD_COMBINATION_TUPLES,
    validatePathContainment,
)
from lsmiotool.lib.run import (
    Combination,
    RunPlan,
    ScalePoint,
    ScheduledPointResources,
)


class EvidenceError(ArtifactError):
    """Base exception for all evidence subsystem operations."""

    pass


class EvidenceSchemaError(EvidenceError):
    """Raised when evidence JSON schema version is unsupported or structure is invalid."""

    pass


class EvidenceSequenceError(EvidenceError):
    """Raised when per-writer monotonic sequence invariant is violated (gap, duplicate, regression)."""

    pass


class EvidenceOwnershipError(EvidenceError):
    """Raised when a writer attempts to create evidence outside its authorized namespace."""

    pass


class EvidenceCollisionError(EvidenceError):
    """Raised when attempting to overwrite or replace an existing create-only evidence file."""

    pass


class EvidenceCorruptionError(EvidenceError):
    """Raised when evidence file contains malformed JSON, corrupted data, or symlink."""

    pass


class EvidencePlanError(EvidenceError):
    """Raised when evidence refers to a point, combination, or rank not present in the run plan."""

    pass


class WriterKind(Enum):
    """Enumeration of authorized evidence writer kinds."""

    CONTROL = "control"
    CONTROLLER = "controller"
    RANK = "rank"


class EvidenceKind(Enum):
    """Enumeration of evidence record kinds across control, controller, and rank streams."""

    SUBMISSION_REQUESTED = "submission_requested"
    SUBMISSION_DISPATCHED = "submission_dispatched"
    SUBMISSION_RECORDED = "submission_recorded"
    OBSERVATION = "observation"
    CANCEL_REQUESTED = "cancel_requested"
    CANCEL_RECORDED = "cancel_recorded"
    CANCEL_UNCONFIRMED = "cancel_unconfirmed"
    CONTROLLER_STARTED = "controller_started"
    CONTROLLER_RESULT = "controller_result"
    RANK_RESULT = "rank_result"
    WHOLE_RUN_SUCCEEDED = "whole_run_succeeded"
    INTERRUPTED = "interrupted"


class JobHandle:
    """Immutable scheduler job handle preserving exact identifier string byte-for-byte."""

    __slots__ = ("m_backend", "m_job_id", "_frozen")

    def __init__(self, f_backend: str, f_job_id: str) -> None:
        if not isinstance(f_backend, str) or not f_backend.strip():
            raise EvidenceSchemaError(
                f"JobHandle backend must be a non-empty string, got: {f_backend!r}"
            )
        if not isinstance(f_job_id, str) or not f_job_id.strip():
            raise EvidenceSchemaError(
                f"JobHandle job_id must be a non-empty string, got: {f_job_id!r}"
            )
        if "\0" in f_backend or "\n" in f_backend or "\r" in f_backend:
            raise EvidenceSchemaError(f"JobHandle backend contains invalid control characters: {f_backend!r}")
        if "\0" in f_job_id or "\n" in f_job_id or "\r" in f_job_id:
            raise EvidenceSchemaError(f"JobHandle job_id contains invalid control characters: {f_job_id!r}")

        super().__setattr__("m_backend", f_backend.strip().lower())
        super().__setattr__("m_job_id", f_job_id.strip())
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
    def backend(self) -> str:
        return self.m_backend

    @property
    def jobId(self) -> str:
        return self.m_job_id

    @property
    def job_id(self) -> str:
        return self.m_job_id

    def toDict(self) -> Dict[str, str]:
        return {
            "backend": self.m_backend,
            "job_id": self.m_job_id,
        }

    @classmethod
    def fromDict(cls, f_data: Dict[str, Any]) -> "JobHandle":
        if not isinstance(f_data, dict):
            raise EvidenceSchemaError(f"Expected dict for JobHandle, got: {type(f_data).__name__}")
        if "backend" not in f_data or "job_id" not in f_data:
            raise EvidenceSchemaError(
                f"JobHandle requires 'backend' and 'job_id' keys, got: {list(f_data.keys())}"
            )
        return cls(f_backend=str(f_data["backend"]), f_job_id=str(f_data["job_id"]))

    def __repr__(self) -> str:
        return f"JobHandle(backend={self.m_backend!r}, job_id={self.m_job_id!r})"

    def __eq__(self, f_other: Any) -> bool:
        if isinstance(f_other, JobHandle):
            return self.m_backend == f_other.m_backend and self.m_job_id == f_other.m_job_id
        return False

    def __hash__(self) -> int:
        return hash((self.m_backend, self.m_job_id))


class EvidenceRecord:
    """Immutable canonical schema-version-1 evidence record."""

    SCHEMA_VERSION: int = 1

    __slots__ = (
        "m_schema_version",
        "m_writer_kind",
        "m_writer_id",
        "m_sequence_number",
        "m_created_at_utc",
        "m_evidence_kind",
        "m_payload",
        "m_causal_predecessor",
        "m_run_id",
        "m_point_id",
        "m_combination",
        "m_global_rank",
        "_frozen",
    )

    def __init__(
        self,
        f_writer_kind: Union[WriterKind, str],
        f_writer_id: str,
        f_sequence_number: int,
        f_evidence_kind: Union[EvidenceKind, str],
        f_payload: Optional[Mapping[str, Any]] = None,
        f_causal_predecessor: Optional[str] = None,
        f_created_at_utc: Optional[str] = None,
        f_run_id: Optional[str] = None,
        f_point_id: Optional[str] = None,
        f_combination: Optional[str] = None,
        f_global_rank: Optional[int] = None,
        f_schema_version: int = 1,
    ) -> None:
        if f_schema_version != self.SCHEMA_VERSION:
            raise EvidenceSchemaError(
                f"Unsupported schema_version: {f_schema_version} (expected {self.SCHEMA_VERSION})"
            )

        if isinstance(f_writer_kind, str):
            try:
                f_norm_writer_kind = WriterKind(f_writer_kind.lower())
            except ValueError:
                raise EvidenceSchemaError(f"Invalid WriterKind: {f_writer_kind!r}")
        elif isinstance(f_writer_kind, WriterKind):
            f_norm_writer_kind = f_writer_kind
        else:
            raise EvidenceSchemaError(
                f"writer_kind must be WriterKind or str, got: {type(f_writer_kind).__name__}"
            )

        if not isinstance(f_writer_id, str) or not f_writer_id.strip():
            raise EvidenceSchemaError(f"writer_id must be a non-empty string, got: {f_writer_id!r}")
        if "/" in f_writer_id or "\\" in f_writer_id or ".." in f_writer_id or "\0" in f_writer_id:
            raise ContainmentError(f"Invalid writer_id containing traversal or separator: {f_writer_id!r}")

        if not isinstance(f_sequence_number, int) or f_sequence_number < 1:
            raise EvidenceSequenceError(
                f"sequence_number must be a positive integer (>= 1), got: {f_sequence_number!r}"
            )

        if isinstance(f_evidence_kind, str):
            try:
                f_norm_evidence_kind = EvidenceKind(f_evidence_kind.lower())
            except ValueError:
                raise EvidenceSchemaError(f"Invalid EvidenceKind: {f_evidence_kind!r}")
        elif isinstance(f_evidence_kind, EvidenceKind):
            f_norm_evidence_kind = f_evidence_kind
        else:
            raise EvidenceSchemaError(
                f"evidence_kind must be EvidenceKind or str, got: {type(f_evidence_kind).__name__}"
            )

        if f_created_at_utc is None:
            f_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        elif isinstance(f_created_at_utc, str) and f_created_at_utc.strip():
            f_ts = f_created_at_utc.strip()
        else:
            raise EvidenceSchemaError(
                f"created_at_utc must be a non-empty string, got: {f_created_at_utc!r}"
            )

        if f_payload is None:
            f_norm_payload: Dict[str, Any] = {}
        elif isinstance(f_payload, (dict, Mapping)):
            f_norm_payload = dict(f_payload)
        else:
            raise EvidenceSchemaError(
                f"payload must be a dict/mapping, got: {type(f_payload).__name__}"
            )

        f_norm_causal = (
            str(f_causal_predecessor).strip()
            if f_causal_predecessor is not None and str(f_causal_predecessor).strip()
            else None
        )
        f_norm_run_id = (
            str(f_run_id).strip() if f_run_id is not None and str(f_run_id).strip() else None
        )
        f_norm_point_id = (
            str(f_point_id).strip() if f_point_id is not None and str(f_point_id).strip() else None
        )
        f_norm_combo = (
            str(f_combination).strip()
            if f_combination is not None and str(f_combination).strip()
            else None
        )
        f_norm_rank = int(f_global_rank) if f_global_rank is not None else None

        super().__setattr__("m_schema_version", self.SCHEMA_VERSION)
        super().__setattr__("m_writer_kind", f_norm_writer_kind)
        super().__setattr__("m_writer_id", f_writer_id.strip())
        super().__setattr__("m_sequence_number", f_sequence_number)
        super().__setattr__("m_created_at_utc", f_ts)
        super().__setattr__("m_evidence_kind", f_norm_evidence_kind)
        super().__setattr__("m_payload", f_norm_payload)
        super().__setattr__("m_causal_predecessor", f_norm_causal)
        super().__setattr__("m_run_id", f_norm_run_id)
        super().__setattr__("m_point_id", f_norm_point_id)
        super().__setattr__("m_combination", f_norm_combo)
        super().__setattr__("m_global_rank", f_norm_rank)
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
    def schemaVersion(self) -> int:
        return self.m_schema_version

    @property
    def schema_version(self) -> int:
        return self.m_schema_version

    @property
    def writerKind(self) -> WriterKind:
        return self.m_writer_kind

    @property
    def writer_kind(self) -> WriterKind:
        return self.m_writer_kind

    @property
    def writerId(self) -> str:
        return self.m_writer_id

    @property
    def writer_id(self) -> str:
        return self.m_writer_id

    @property
    def sequenceNumber(self) -> int:
        return self.m_sequence_number

    @property
    def sequence_number(self) -> int:
        return self.m_sequence_number

    @property
    def createdAtUtc(self) -> str:
        return self.m_created_at_utc

    @property
    def created_at_utc(self) -> str:
        return self.m_created_at_utc

    @property
    def evidenceKind(self) -> EvidenceKind:
        return self.m_evidence_kind

    @property
    def evidence_kind(self) -> EvidenceKind:
        return self.m_evidence_kind

    @property
    def payload(self) -> Dict[str, Any]:
        return dict(self.m_payload)

    @property
    def causalPredecessor(self) -> Optional[str]:
        return self.m_causal_predecessor

    @property
    def causal_predecessor(self) -> Optional[str]:
        return self.m_causal_predecessor

    @property
    def runId(self) -> Optional[str]:
        return self.m_run_id

    @property
    def run_id(self) -> Optional[str]:
        return self.m_run_id

    @property
    def pointId(self) -> Optional[str]:
        return self.m_point_id

    @property
    def point_id(self) -> Optional[str]:
        return self.m_point_id

    @property
    def combination(self) -> Optional[str]:
        return self.m_combination

    @property
    def globalRank(self) -> Optional[int]:
        return self.m_global_rank

    @property
    def global_rank(self) -> Optional[int]:
        return self.m_global_rank

    def toDict(self) -> Dict[str, Any]:
        f_doc: Dict[str, Any] = {
            "schema_version": self.m_schema_version,
            "writer_kind": self.m_writer_kind.value,
            "writer_id": self.m_writer_id,
            "sequence_number": self.m_sequence_number,
            "created_at_utc": self.m_created_at_utc,
            "evidence_kind": self.m_evidence_kind.value,
            "payload": self.m_payload,
            "causal_predecessor": self.m_causal_predecessor,
        }
        if self.m_run_id is not None:
            f_doc["run_id"] = self.m_run_id
        if self.m_point_id is not None:
            f_doc["point_id"] = self.m_point_id
        if self.m_combination is not None:
            f_doc["combination"] = self.m_combination
        if self.m_global_rank is not None:
            f_doc["global_rank"] = self.m_global_rank
        return f_doc

    @classmethod
    def fromDict(cls, f_data: Dict[str, Any]) -> "EvidenceRecord":
        if not isinstance(f_data, dict):
            raise EvidenceSchemaError(f"Expected dict for EvidenceRecord, got: {type(f_data).__name__}")

        f_schema = f_data.get("schema_version")
        if f_schema != cls.SCHEMA_VERSION:
            raise EvidenceSchemaError(
                f"Unsupported schema_version: {f_schema!r} (expected {cls.SCHEMA_VERSION})"
            )

        f_required = [
            "writer_kind",
            "writer_id",
            "sequence_number",
            "created_at_utc",
            "evidence_kind",
            "payload",
        ]
        for f_req in f_required:
            if f_req not in f_data:
                raise EvidenceSchemaError(f"Missing required field in EvidenceRecord: {f_req!r}")

        return cls(
            f_writer_kind=f_data["writer_kind"],
            f_writer_id=str(f_data["writer_id"]),
            f_sequence_number=int(f_data["sequence_number"]),
            f_evidence_kind=f_data["evidence_kind"],
            f_payload=f_data["payload"],
            f_causal_predecessor=f_data.get("causal_predecessor"),
            f_created_at_utc=f_data.get("created_at_utc"),
            f_run_id=f_data.get("run_id"),
            f_point_id=f_data.get("point_id"),
            f_combination=f_data.get("combination"),
            f_global_rank=f_data.get("global_rank"),
            f_schema_version=int(f_data["schema_version"]),
        )

    def toJson(self) -> str:
        return EvidenceSerializer.serialize(self)

    @classmethod
    def fromJson(cls, f_json_text: Union[str, bytes]) -> "EvidenceRecord":
        return EvidenceSerializer.deserialize(f_json_text)

    def __repr__(self) -> str:
        return (
            f"EvidenceRecord(writer_kind={self.m_writer_kind.value!r}, "
            f"writer_id={self.m_writer_id!r}, "
            f"sequence_number={self.m_sequence_number}, "
            f"evidence_kind={self.m_evidence_kind.value!r}, "
            f"causal_predecessor={self.m_causal_predecessor!r})"
        )

    def __eq__(self, f_other: Any) -> bool:
        if isinstance(f_other, EvidenceRecord):
            return self.toDict() == f_other.toDict()
        return False


class EvidenceSerializer:
    """Canonical schema-version-1 JSON serializer and deserializer for evidence records."""

    @staticmethod
    def serialize(f_record: Union[EvidenceRecord, Dict[str, Any]]) -> str:
        if isinstance(f_record, EvidenceRecord):
            f_doc = f_record.toDict()
        elif isinstance(f_record, dict):
            f_doc = f_record
        else:
            raise EvidenceSchemaError(
                f"Expected EvidenceRecord or dict, got: {type(f_record).__name__}"
            )

        return json.dumps(f_doc, indent=2, sort_keys=True) + "\n"

    @staticmethod
    def deserialize(f_data: Union[str, bytes, Dict[str, Any]]) -> EvidenceRecord:
        if isinstance(f_data, (str, bytes)):
            try:
                f_parsed = json.loads(f_data)
            except Exception as f_err:
                raise EvidenceCorruptionError(f"Failed to parse evidence JSON: {f_err}") from f_err
        elif isinstance(f_data, dict):
            f_parsed = f_data
        else:
            raise EvidenceSchemaError(
                f"Expected str, bytes, or dict for deserialization, got: {type(f_data).__name__}"
            )

        if not isinstance(f_parsed, dict):
            raise EvidenceCorruptionError(
                f"Evidence root must be a JSON object, got: {type(f_parsed).__name__}"
            )

        return EvidenceRecord.fromDict(f_parsed)


class EvidenceStore:
    """Disjoint, writer-owned, create-only evidence store enforcing monotonic sequences and containment."""

    __slots__ = ("m_layout", "m_plan", "_frozen")

    def __init__(
        self,
        f_benchmark_root_or_layout: Union[ArtifactLayout, str],
        f_run_id: Optional[str] = None,
        f_plan: Optional[RunPlan] = None,
    ) -> None:
        if isinstance(f_benchmark_root_or_layout, ArtifactLayout):
            f_layout = f_benchmark_root_or_layout
        elif isinstance(f_benchmark_root_or_layout, str):
            if f_run_id is None:
                raise ArtifactError("run_id must be provided when passing benchmark_root string")
            f_layout = ArtifactLayout(f_benchmark_root_or_layout, f_run_id)
        else:
            raise ArtifactError(
                f"Expected ArtifactLayout or str, got: {type(f_benchmark_root_or_layout).__name__}"
            )

        super().__setattr__("m_layout", f_layout)
        super().__setattr__("m_plan", f_plan)
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
    def layout(self) -> ArtifactLayout:
        return self.m_layout

    @property
    def plan(self) -> Optional[RunPlan]:
        return self.m_plan

    def _validatePlanMembership(
        self,
        f_point: Optional[Union[ScalePoint, str, int]] = None,
        f_combination: Optional[Union[Combination, str]] = None,
        f_global_rank: Optional[Union[int, str]] = None,
        f_ordinal: Optional[int] = None,
    ) -> None:
        """Validate that point, combination, and rank exist in the configured plan if present."""
        if self.m_plan is None:
            return

        # 1. Point membership
        f_point_tasks: Optional[int] = None
        if f_point is not None:
            f_found = False
            f_scale_points = getattr(self.m_plan, "scale_points", ())
            for f_idx, f_plan_point in enumerate(f_scale_points):
                # Check scale point equality or task match or ordinal match
                if isinstance(f_point, ScalePoint):
                    if (
                        f_plan_point.tasks == f_point.tasks
                        and f_plan_point.ppn == f_point.ppn
                        and f_plan_point.nodes == f_point.nodes
                    ):
                        if f_ordinal is None or f_ordinal == f_idx:
                            f_found = True
                            f_point_tasks = f_plan_point.tasks
                            break
                elif isinstance(f_point, int):
                    if f_idx == f_point or f_plan_point.tasks == f_point:
                        f_found = True
                        f_point_tasks = f_plan_point.tasks
                        break
                elif isinstance(f_point, str):
                    f_name = self.m_layout.pointDirName(f_point, f_ordinal)
                    f_plan_name_1 = self.m_layout.pointDirName(f_plan_point, f_idx)
                    f_plan_name_2 = self.m_layout.pointDirName(f_plan_point)
                    if f_name in (f_plan_name_1, f_plan_name_2):
                        f_found = True
                        f_point_tasks = f_plan_point.tasks
                        break
            if not f_found:
                raise EvidencePlanError(
                    f"Point '{f_point}' is not part of plan for run '{self.m_layout.runId}'"
                )

        # 2. Combination membership
        if f_combination is not None:
            f_combo_name = self.m_layout.combinationName(f_combination)
            f_valid_combos: Set[str] = set()
            f_plan_combos = getattr(self.m_plan, "combinations", ())
            if f_plan_combos:
                for f_combo in f_plan_combos:
                    f_valid_combos.add(f_combo.name)
            else:
                for f_stripe, f_block in STANDARD_COMBINATION_TUPLES:
                    f_valid_combos.add(f"c{f_stripe}_b{f_block}")

            if f_combo_name not in f_valid_combos:
                raise EvidencePlanError(
                    f"Combination '{f_combo_name}' is not in plan matrix (valid: {sorted(f_valid_combos)})"
                )

        # 3. Global rank range
        if f_global_rank is not None:
            try:
                f_rank_int = int(f_global_rank)
            except (ValueError, TypeError):
                raise EvidencePlanError(f"global_rank must be integer-convertible, got: {f_global_rank!r}")

            if f_rank_int < 0:
                raise EvidencePlanError(f"global_rank cannot be negative, got: {f_rank_int}")

            if f_point_tasks is not None:
                if f_rank_int >= f_point_tasks:
                    raise EvidencePlanError(
                        f"global_rank {f_rank_int} exceeds point task count {f_point_tasks}"
                    )
            else:
                # Check maximum task count in plan
                f_scale_points = getattr(self.m_plan, "scale_points", ())
                if f_scale_points:
                    f_max_tasks = max(f_p.tasks for f_p in f_scale_points)
                    if f_rank_int >= f_max_tasks:
                        raise EvidencePlanError(
                            f"global_rank {f_rank_int} exceeds maximum plan task count {f_max_tasks}"
                        )

    def _checkSymlinksAndContainment(self, f_path: str) -> str:
        """Validate lexical and physical containment and ensure no symlinks in path."""
        f_norm_path = validatePathContainment(f_path, self.m_layout.runRoot)

        # Explicit check for symlink at target or intermediate components
        f_curr = f_norm_path
        f_run_root = os.path.abspath(self.m_layout.runRoot)
        while f_curr and f_curr != f_run_root and len(f_curr) >= len(f_run_root):
            if os.path.islink(f_curr):
                raise EvidenceCorruptionError(
                    f"Symlinks are forbidden in evidence store path: '{f_curr}'"
                )
            f_parent = os.path.dirname(f_curr)
            if f_parent == f_curr:
                break
            f_curr = f_parent

        return f_norm_path

    def _enforceMonotonicSequence(self, f_dir: str, f_sequence: int) -> None:
        """Enforce strict monotonic sequence number N (N = highest + 1, starting at 1)."""
        if not os.path.exists(f_dir):
            if f_sequence != 1:
                raise EvidenceSequenceError(
                    f"Sequence gap detected: expected sequence 1 for new stream, got {f_sequence}"
                )
            return

        f_existing: List[int] = []
        for f_fname in os.listdir(f_dir):
            f_match = re.match(r"^([0-9]+)\.json$", f_fname)
            if f_match:
                f_existing.append(int(f_match.group(1)))

        if not f_existing:
            if f_sequence != 1:
                raise EvidenceSequenceError(
                    f"Sequence gap detected: expected sequence 1 for empty stream, got {f_sequence}"
                )
            return

        f_existing.sort()
        f_highest = f_existing[-1]

        if f_sequence <= f_highest:
            raise EvidenceSequenceError(
                f"Sequence number {f_sequence} violates monotonic ordering (highest existing is {f_highest})"
            )
        if f_sequence > f_highest + 1:
            raise EvidenceSequenceError(
                f"Sequence gap detected: expected sequence {f_highest + 1}, got {f_sequence}"
            )

    def _writeExclusiveRecord(self, f_path: str, f_record: EvidenceRecord) -> str:
        """Atomically write canonical evidence JSON using O_CREAT | O_EXCL and disk fsync."""
        f_norm_path = self._checkSymlinksAndContainment(f_path)
        f_parent = os.path.dirname(f_norm_path)
        os.makedirs(f_parent, exist_ok=True)

        f_text = EvidenceSerializer.serialize(f_record)
        f_bytes = f_text.encode("utf-8")

        try:
            f_fd = os.open(
                f_norm_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o644,
            )
        except FileExistsError as f_err:
            raise EvidenceCollisionError(
                f"Evidence file already exists at '{f_norm_path}': replacement rejected"
            ) from f_err
        except OSError as f_err:
            raise EvidenceError(f"Failed to open evidence file '{f_norm_path}': {f_err}") from f_err

        try:
            f_written = 0
            while f_written < len(f_bytes):
                f_n = os.write(f_fd, f_bytes[f_written:])
                if f_n == 0:
                    raise EvidenceCorruptionError(f"Zero bytes written to evidence at '{f_norm_path}'")
                f_written += f_n

            os.fsync(f_fd)
        except Exception as f_err:
            raise EvidenceCorruptionError(
                f"Error writing or fsyncing evidence to '{f_norm_path}': {f_err}"
            ) from f_err
        finally:
            os.close(f_fd)

        # Verification readback
        try:
            with open(f_norm_path, "rb") as f_f:
                f_read_back = f_f.read()
        except OSError as f_err:
            raise EvidenceCorruptionError(
                f"Failed to read back evidence from '{f_norm_path}' for verification: {f_err}"
            ) from f_err

        if f_read_back != f_bytes:
            raise EvidenceCorruptionError(
                f"Evidence verification mismatch at '{f_norm_path}': read {len(f_read_back)} bytes != written {len(f_bytes)} bytes"
            )

        return f_norm_path

    def recordRecord(self, f_path: str, f_record: EvidenceRecord) -> EvidenceRecord:
        """Write an evidence record after validating ownership matrix, sequence, and plan membership."""
        f_norm_path = os.path.abspath(f_path)
        self._checkSymlinksAndContainment(f_norm_path)

        f_control_events_prefix = os.path.abspath(self.m_layout.controlEventsDir)
        f_points_prefix = os.path.abspath(self.m_layout.pointsDir)

        # Ownership Matrix Validation
        if f_record.writer_kind == WriterKind.CONTROL:
            # Control writer can write to control/events or scheduler directories
            f_is_control_event = f_norm_path.startswith(f_control_events_prefix + os.sep)
            f_is_scheduler = (
                f_norm_path.startswith(f_points_prefix + os.sep)
                and os.sep + "scheduler" + os.sep in f_norm_path
            )
            if not (f_is_control_event or f_is_scheduler):
                raise EvidenceOwnershipError(
                    f"CONTROL writer '{f_record.writer_id}' is not authorized to write to '{f_norm_path}'"
                )

        elif f_record.writer_kind == WriterKind.CONTROLLER:
            # Controller writer can write to points/<p>/worker/events or points/<p>/combinations/<c>/controller-result.json
            f_is_worker = (
                f_norm_path.startswith(f_points_prefix + os.sep)
                and os.sep + "worker" + os.sep + "events" + os.sep in f_norm_path
            )
            f_is_controller_result = (
                f_norm_path.startswith(f_points_prefix + os.sep)
                and os.sep + "combinations" + os.sep in f_norm_path
                and os.path.basename(f_norm_path) == "controller-result.json"
            )
            if not (f_is_worker or f_is_controller_result):
                raise EvidenceOwnershipError(
                    f"CONTROLLER writer '{f_record.writer_id}' is not authorized to write to '{f_norm_path}'"
                )

        elif f_record.writer_kind == WriterKind.RANK:
            # Rank writer can write ONLY to points/<p>/ranks/<global_rank>/<c>/result.json
            f_is_rank_result = (
                f_norm_path.startswith(f_points_prefix + os.sep)
                and os.sep + "ranks" + os.sep in f_norm_path
                and os.path.basename(f_norm_path) == "result.json"
            )
            if not f_is_rank_result:
                raise EvidenceOwnershipError(
                    f"RANK writer '{f_record.writer_id}' is not authorized to write to '{f_norm_path}'"
                )

            # Validate that the rank path matches the writer_id and global_rank
            f_parts = f_norm_path.split(os.sep)
            try:
                f_ranks_idx = f_parts.index("ranks")
                f_path_rank = f_parts[f_ranks_idx + 1]
                if f_path_rank != f_record.writer_id:
                    raise EvidenceOwnershipError(
                        f"RANK writer '{f_record.writer_id}' cannot write to rank '{f_path_rank}' path"
                    )
            except (ValueError, IndexError):
                raise EvidenceOwnershipError(
                    f"Malformed rank path structure for RANK writer: '{f_norm_path}'"
                )
        else:
            raise EvidenceOwnershipError(f"Unknown writer kind: {f_record.writer_kind!r}")

        # Write record
        self._writeExclusiveRecord(f_norm_path, f_record)
        return f_record

    # --- Typed Control Writer Methods ---

    def recordControlEvent(
        self,
        f_writer_id: str,
        f_sequence: int,
        f_evidence_kind: Union[EvidenceKind, str],
        f_payload: Optional[Dict[str, Any]] = None,
        f_causal_predecessor: Optional[str] = None,
        f_created_at_utc: Optional[str] = None,
    ) -> EvidenceRecord:
        """Record an ordered control event under control/events/<writer_id>/<sequence>.json."""
        f_stream_dir = os.path.join(self.m_layout.controlEventsDir, f_writer_id.strip())
        self._enforceMonotonicSequence(f_stream_dir, f_sequence)

        f_path = self.m_layout.controlEventPath(f_writer_id, f_sequence)
        f_rec = EvidenceRecord(
            f_writer_kind=WriterKind.CONTROL,
            f_writer_id=f_writer_id,
            f_sequence_number=f_sequence,
            f_evidence_kind=f_evidence_kind,
            f_payload=f_payload,
            f_causal_predecessor=f_causal_predecessor,
            f_created_at_utc=f_created_at_utc,
            f_run_id=self.m_layout.runId,
        )
        return self.recordRecord(f_path, f_rec)

    def recordInterruption(
        self,
        f_writer_id: str,
        f_sequence: int,
        f_payload: Optional[Dict[str, Any]] = None,
        f_causal_predecessor: Optional[str] = None,
        f_created_at_utc: Optional[str] = None,
    ) -> EvidenceRecord:
        """Record an interruption event in the control stream."""
        return self.recordControlEvent(
            f_writer_id=f_writer_id,
            f_sequence=f_sequence,
            f_evidence_kind=EvidenceKind.INTERRUPTED,
            f_payload=f_payload,
            f_causal_predecessor=f_causal_predecessor,
            f_created_at_utc=f_created_at_utc,
        )

    def recordWholeRunSucceeded(
        self,
        f_writer_id: str,
        f_sequence: int,
        f_payload: Optional[Dict[str, Any]] = None,
        f_causal_predecessor: Optional[str] = None,
        f_created_at_utc: Optional[str] = None,
    ) -> EvidenceRecord:
        """Record a whole_run_succeeded marker in the control stream."""
        return self.recordControlEvent(
            f_writer_id=f_writer_id,
            f_sequence=f_sequence,
            f_evidence_kind=EvidenceKind.WHOLE_RUN_SUCCEEDED,
            f_payload=f_payload,
            f_causal_predecessor=f_causal_predecessor,
            f_created_at_utc=f_created_at_utc,
        )

    # --- Typed Scheduler Methods (CONTROL Owned) ---

    def recordSchedulerObservation(
        self,
        f_point: Union[ScalePoint, str, int],
        f_writer_id: str,
        f_sequence: int,
        f_payload: Optional[Dict[str, Any]] = None,
        f_causal_predecessor: Optional[str] = None,
        f_created_at_utc: Optional[str] = None,
        f_ordinal: Optional[int] = None,
    ) -> EvidenceRecord:
        """Record a scheduler observation event under points/<point>/scheduler/observations/<writer>/<seq>.json."""
        self._validatePlanMembership(f_point=f_point, f_ordinal=f_ordinal)

        f_obs_dir = self.m_layout.pointSchedulerObservationsDir(f_point, f_writer=f_writer_id, f_ordinal=f_ordinal)
        self._enforceMonotonicSequence(f_obs_dir, f_sequence)

        f_path = self.m_layout.pointSchedulerObservationPath(f_point, f_writer_id, f_sequence, f_ordinal)
        f_point_name = self.m_layout.pointDirName(f_point, f_ordinal)
        f_rec = EvidenceRecord(
            f_writer_kind=WriterKind.CONTROL,
            f_writer_id=f_writer_id,
            f_sequence_number=f_sequence,
            f_evidence_kind=EvidenceKind.OBSERVATION,
            f_payload=f_payload,
            f_causal_predecessor=f_causal_predecessor,
            f_created_at_utc=f_created_at_utc,
            f_run_id=self.m_layout.runId,
            f_point_id=f_point_name,
        )
        return self.recordRecord(f_path, f_rec)

    def recordSubmissionRequested(
        self,
        f_point: Union[ScalePoint, str, int],
        f_writer_id: str,
        f_payload: Optional[Dict[str, Any]] = None,
        f_causal_predecessor: Optional[str] = None,
        f_created_at_utc: Optional[str] = None,
        f_ordinal: Optional[int] = None,
    ) -> EvidenceRecord:
        """Record submission_requested before scheduler invocation."""
        self._validatePlanMembership(f_point=f_point, f_ordinal=f_ordinal)
        f_path = os.path.join(
            self.m_layout.pointSchedulerDir(f_point, f_ordinal),
            "submission_requested.json",
        )
        f_point_name = self.m_layout.pointDirName(f_point, f_ordinal)
        f_rec = EvidenceRecord(
            f_writer_kind=WriterKind.CONTROL,
            f_writer_id=f_writer_id,
            f_sequence_number=1,
            f_evidence_kind=EvidenceKind.SUBMISSION_REQUESTED,
            f_payload=f_payload,
            f_causal_predecessor=f_causal_predecessor,
            f_created_at_utc=f_created_at_utc,
            f_run_id=self.m_layout.runId,
            f_point_id=f_point_name,
        )
        return self.recordRecord(f_path, f_rec)

    def recordSubmissionDispatched(
        self,
        f_point: Union[ScalePoint, str, int],
        f_writer_id: str,
        f_payload: Optional[Dict[str, Any]] = None,
        f_causal_predecessor: Optional[str] = None,
        f_created_at_utc: Optional[str] = None,
        f_ordinal: Optional[int] = None,
    ) -> EvidenceRecord:
        """Record submission_dispatched immediately before the process call."""
        self._validatePlanMembership(f_point=f_point, f_ordinal=f_ordinal)
        f_path = os.path.join(
            self.m_layout.pointSchedulerDir(f_point, f_ordinal),
            "submission_dispatched.json",
        )
        f_point_name = self.m_layout.pointDirName(f_point, f_ordinal)
        f_rec = EvidenceRecord(
            f_writer_kind=WriterKind.CONTROL,
            f_writer_id=f_writer_id,
            f_sequence_number=2,
            f_evidence_kind=EvidenceKind.SUBMISSION_DISPATCHED,
            f_payload=f_payload,
            f_causal_predecessor=f_causal_predecessor,
            f_created_at_utc=f_created_at_utc,
            f_run_id=self.m_layout.runId,
            f_point_id=f_point_name,
        )
        return self.recordRecord(f_path, f_rec)

    def recordSubmissionRecorded(
        self,
        f_point: Union[ScalePoint, str, int],
        f_writer_id: str,
        f_handle: JobHandle,
        f_payload: Optional[Dict[str, Any]] = None,
        f_causal_predecessor: Optional[str] = None,
        f_created_at_utc: Optional[str] = None,
        f_ordinal: Optional[int] = None,
    ) -> EvidenceRecord:
        """Record submission_recorded persisting the returned JobHandle."""
        self._validatePlanMembership(f_point=f_point, f_ordinal=f_ordinal)
        if not isinstance(f_handle, JobHandle):
            raise EvidenceSchemaError(f"Expected JobHandle, got: {type(f_handle).__name__}")

        f_path = os.path.join(
            self.m_layout.pointSchedulerDir(f_point, f_ordinal),
            "submission_recorded.json",
        )
        f_full_payload = dict(f_payload or {})
        f_full_payload["handle"] = f_handle.toDict()

        f_point_name = self.m_layout.pointDirName(f_point, f_ordinal)
        f_rec = EvidenceRecord(
            f_writer_kind=WriterKind.CONTROL,
            f_writer_id=f_writer_id,
            f_sequence_number=3,
            f_evidence_kind=EvidenceKind.SUBMISSION_RECORDED,
            f_payload=f_full_payload,
            f_causal_predecessor=f_causal_predecessor,
            f_created_at_utc=f_created_at_utc,
            f_run_id=self.m_layout.runId,
            f_point_id=f_point_name,
        )
        return self.recordRecord(f_path, f_rec)

    def recordCancelRequested(
        self,
        f_point: Union[ScalePoint, str, int],
        f_writer_id: str,
        f_handle: Optional[JobHandle] = None,
        f_payload: Optional[Dict[str, Any]] = None,
        f_causal_predecessor: Optional[str] = None,
        f_created_at_utc: Optional[str] = None,
        f_ordinal: Optional[int] = None,
    ) -> EvidenceRecord:
        """Record cancel_requested event when cancellation is initiated."""
        self._validatePlanMembership(f_point=f_point, f_ordinal=f_ordinal)
        f_path = os.path.join(
            self.m_layout.pointSchedulerDir(f_point, f_ordinal),
            "cancel_requested.json",
        )
        f_full_payload = dict(f_payload or {})
        if f_handle is not None:
            f_full_payload["handle"] = f_handle.toDict()

        f_point_name = self.m_layout.pointDirName(f_point, f_ordinal)
        f_rec = EvidenceRecord(
            f_writer_kind=WriterKind.CONTROL,
            f_writer_id=f_writer_id,
            f_sequence_number=1,
            f_evidence_kind=EvidenceKind.CANCEL_REQUESTED,
            f_payload=f_full_payload,
            f_causal_predecessor=f_causal_predecessor,
            f_created_at_utc=f_created_at_utc,
            f_run_id=self.m_layout.runId,
            f_point_id=f_point_name,
        )
        return self.recordRecord(f_path, f_rec)

    def recordCancelRecorded(
        self,
        f_point: Union[ScalePoint, str, int],
        f_writer_id: str,
        f_handle: Optional[JobHandle] = None,
        f_payload: Optional[Dict[str, Any]] = None,
        f_causal_predecessor: Optional[str] = None,
        f_created_at_utc: Optional[str] = None,
        f_ordinal: Optional[int] = None,
    ) -> EvidenceRecord:
        """Record cancel_recorded event confirming cancellation."""
        self._validatePlanMembership(f_point=f_point, f_ordinal=f_ordinal)
        f_path = os.path.join(
            self.m_layout.pointSchedulerDir(f_point, f_ordinal),
            "cancel_recorded.json",
        )
        f_full_payload = dict(f_payload or {})
        if f_handle is not None:
            f_full_payload["handle"] = f_handle.toDict()

        f_point_name = self.m_layout.pointDirName(f_point, f_ordinal)
        f_rec = EvidenceRecord(
            f_writer_kind=WriterKind.CONTROL,
            f_writer_id=f_writer_id,
            f_sequence_number=2,
            f_evidence_kind=EvidenceKind.CANCEL_RECORDED,
            f_payload=f_full_payload,
            f_causal_predecessor=f_causal_predecessor,
            f_created_at_utc=f_created_at_utc,
            f_run_id=self.m_layout.runId,
            f_point_id=f_point_name,
        )
        return self.recordRecord(f_path, f_rec)

    # --- Typed Controller Writer Methods ---

    def recordWorkerEvent(
        self,
        f_point: Union[ScalePoint, str, int],
        f_sequence: int,
        f_evidence_kind: Union[EvidenceKind, str] = EvidenceKind.CONTROLLER_STARTED,
        f_payload: Optional[Dict[str, Any]] = None,
        f_causal_predecessor: Optional[str] = None,
        f_created_at_utc: Optional[str] = None,
        f_ordinal: Optional[int] = None,
    ) -> EvidenceRecord:
        """Record an allocation-controller event under points/<point>/worker/events/<seq>.json."""
        self._validatePlanMembership(f_point=f_point, f_ordinal=f_ordinal)

        f_worker_events_dir = self.m_layout.pointWorkerEventsDir(f_point, f_ordinal)
        self._enforceMonotonicSequence(f_worker_events_dir, f_sequence)

        f_path = self.m_layout.pointWorkerEventPath(f_point, f_sequence, f_ordinal)
        f_point_name = self.m_layout.pointDirName(f_point, f_ordinal)
        f_rec = EvidenceRecord(
            f_writer_kind=WriterKind.CONTROLLER,
            f_writer_id="controller",
            f_sequence_number=f_sequence,
            f_evidence_kind=f_evidence_kind,
            f_payload=f_payload,
            f_causal_predecessor=f_causal_predecessor,
            f_created_at_utc=f_created_at_utc,
            f_run_id=self.m_layout.runId,
            f_point_id=f_point_name,
        )
        return self.recordRecord(f_path, f_rec)

    def recordControllerResult(
        self,
        f_point: Union[ScalePoint, str, int],
        f_combination: Union[Combination, str],
        f_payload: Optional[Dict[str, Any]] = None,
        f_causal_predecessor: Optional[str] = None,
        f_created_at_utc: Optional[str] = None,
        f_ordinal: Optional[int] = None,
    ) -> EvidenceRecord:
        """Record combination controller result under points/<point>/combinations/<combo>/controller-result.json."""
        self._validatePlanMembership(
            f_point=f_point, f_combination=f_combination, f_ordinal=f_ordinal
        )

        f_path = self.m_layout.pointControllerResultPath(f_point, f_combination, f_ordinal)
        f_point_name = self.m_layout.pointDirName(f_point, f_ordinal)
        f_combo_name = self.m_layout.combinationName(f_combination)
        f_rec = EvidenceRecord(
            f_writer_kind=WriterKind.CONTROLLER,
            f_writer_id="controller",
            f_sequence_number=1,
            f_evidence_kind=EvidenceKind.CONTROLLER_RESULT,
            f_payload=f_payload,
            f_causal_predecessor=f_causal_predecessor,
            f_created_at_utc=f_created_at_utc,
            f_run_id=self.m_layout.runId,
            f_point_id=f_point_name,
            f_combination=f_combo_name,
        )
        return self.recordRecord(f_path, f_rec)

    # --- Typed Rank Writer Methods ---

    def recordRankResult(
        self,
        f_point: Union[ScalePoint, str, int],
        f_global_rank: Union[int, str],
        f_combination: Union[Combination, str],
        f_payload: Optional[Dict[str, Any]] = None,
        f_causal_predecessor: Optional[str] = None,
        f_created_at_utc: Optional[str] = None,
        f_ordinal: Optional[int] = None,
    ) -> EvidenceRecord:
        """Record task rank result under points/<point>/ranks/<global_rank>/<combo>/result.json."""
        self._validatePlanMembership(
            f_point=f_point,
            f_combination=f_combination,
            f_global_rank=f_global_rank,
            f_ordinal=f_ordinal,
        )

        f_path = self.m_layout.pointRankResultPath(
            f_point, f_global_rank, f_combination, f_ordinal
        )
        f_point_name = self.m_layout.pointDirName(f_point, f_ordinal)
        f_combo_name = self.m_layout.combinationName(f_combination)
        f_rank_str = str(f_global_rank)
        f_rank_int = int(f_global_rank)

        f_rec = EvidenceRecord(
            f_writer_kind=WriterKind.RANK,
            f_writer_id=f_rank_str,
            f_sequence_number=1,
            f_evidence_kind=EvidenceKind.RANK_RESULT,
            f_payload=f_payload,
            f_causal_predecessor=f_causal_predecessor,
            f_created_at_utc=f_created_at_utc,
            f_run_id=self.m_layout.runId,
            f_point_id=f_point_name,
            f_combination=f_combo_name,
            f_global_rank=f_rank_int,
        )
        return self.recordRecord(f_path, f_rec)

    # --- Read Semantics ---

    def readRecord(self, f_path: str) -> EvidenceRecord:
        """Read and validate an evidence record from file."""
        f_norm_path = self._checkSymlinksAndContainment(f_path)
        if not os.path.exists(f_norm_path):
            raise FileNotFoundError(f"Evidence record not found: '{f_norm_path}'")

        try:
            with open(f_norm_path, "rb") as f_f:
                f_bytes = f_f.read()
        except OSError as f_err:
            raise EvidenceCorruptionError(
                f"Failed to read evidence file '{f_norm_path}': {f_err}"
            ) from f_err

        return EvidenceSerializer.deserialize(f_bytes)

    def readRecordIfExists(self, f_path: str) -> Optional[EvidenceRecord]:
        """Read an evidence record if it exists, or return None."""
        f_norm_path = self._checkSymlinksAndContainment(f_path)
        if not os.path.exists(f_norm_path):
            return None
        return self.readRecord(f_norm_path)

    def readControlEvents(self, f_writer_id: str) -> List[EvidenceRecord]:
        """Read all control events for a given writer in strict monotonic sequence order."""
        f_dir = os.path.join(self.m_layout.controlEventsDir, f_writer_id.strip())
        if not os.path.exists(f_dir):
            return []

        f_files = [f_f for f_f in os.listdir(f_dir) if re.match(r"^[0-9]+\.json$", f_f)]
        if not f_files:
            return []

        f_files.sort(key=lambda f_f: int(f_f.split(".")[0]))
        f_records: List[EvidenceRecord] = []

        for f_idx, f_fname in enumerate(f_files, start=1):
            f_seq = int(f_fname.split(".")[0])
            if f_seq != f_idx:
                raise EvidenceSequenceError(
                    f"Gap detected in control events for writer '{f_writer_id}': expected sequence {f_idx}, found {f_seq}"
                )
            f_path = os.path.join(f_dir, f_fname)
            f_records.append(self.readRecord(f_path))

        return f_records

    def readSchedulerObservations(
        self,
        f_point: Union[ScalePoint, str, int],
        f_writer_id: str,
        f_ordinal: Optional[int] = None,
    ) -> List[EvidenceRecord]:
        """Read all scheduler observations for a writer at a point in monotonic sequence order."""
        f_dir = self.m_layout.pointSchedulerObservationsDir(f_point, f_writer=f_writer_id, f_ordinal=f_ordinal)
        if not os.path.exists(f_dir):
            return []

        f_files = [f_f for f_f in os.listdir(f_dir) if re.match(r"^[0-9]+\.json$", f_f)]
        if not f_files:
            return []

        f_files.sort(key=lambda f_f: int(f_f.split(".")[0]))
        f_records: List[EvidenceRecord] = []

        for f_idx, f_fname in enumerate(f_files, start=1):
            f_seq = int(f_fname.split(".")[0])
            if f_seq != f_idx:
                raise EvidenceSequenceError(
                    f"Gap detected in scheduler observations for writer '{f_writer_id}': expected sequence {f_idx}, found {f_seq}"
                )
            f_path = os.path.join(f_dir, f_fname)
            f_records.append(self.readRecord(f_path))

        return f_records

    def readWorkerEvents(
        self,
        f_point: Union[ScalePoint, str, int],
        f_ordinal: Optional[int] = None,
    ) -> List[EvidenceRecord]:
        """Read all worker events for a point in monotonic sequence order."""
        f_dir = self.m_layout.pointWorkerEventsDir(f_point, f_ordinal)
        if not os.path.exists(f_dir):
            return []

        f_files = [f_f for f_f in os.listdir(f_dir) if re.match(r"^[0-9]+\.json$", f_f)]
        if not f_files:
            return []

        f_files.sort(key=lambda f_f: int(f_f.split(".")[0]))
        f_records: List[EvidenceRecord] = []

        for f_idx, f_fname in enumerate(f_files, start=1):
            f_seq = int(f_fname.split(".")[0])
            if f_seq != f_idx:
                raise EvidenceSequenceError(
                    f"Gap detected in worker events: expected sequence {f_idx}, found {f_seq}"
                )
            f_path = os.path.join(f_dir, f_fname)
            f_records.append(self.readRecord(f_path))

        return f_records

    def readControllerResult(
        self,
        f_point: Union[ScalePoint, str, int],
        f_combination: Union[Combination, str],
        f_ordinal: Optional[int] = None,
    ) -> Optional[EvidenceRecord]:
        """Read controller result for a point and combination if present."""
        f_path = self.m_layout.pointControllerResultPath(f_point, f_combination, f_ordinal)
        return self.readRecordIfExists(f_path)

    def readRankResult(
        self,
        f_point: Union[ScalePoint, str, int],
        f_global_rank: Union[int, str],
        f_combination: Union[Combination, str],
        f_ordinal: Optional[int] = None,
    ) -> Optional[EvidenceRecord]:
        """Read task rank result for a point, rank, and combination if present."""
        f_path = self.m_layout.pointRankResultPath(f_point, f_global_rank, f_combination, f_ordinal)
        return self.readRecordIfExists(f_path)

    def readSubmissionRecords(
        self,
        f_point: Union[ScalePoint, str, int],
        f_ordinal: Optional[int] = None,
    ) -> Dict[str, Optional[EvidenceRecord]]:
        """Read standard submission records for a point (requested, dispatched, recorded, cancel_req, cancel_rec)."""
        f_sched_dir = self.m_layout.pointSchedulerDir(f_point, f_ordinal)
        f_names = [
            "submission_requested",
            "submission_dispatched",
            "submission_recorded",
            "cancel_requested",
            "cancel_recorded",
        ]
        f_results: Dict[str, Optional[EvidenceRecord]] = {}
        for f_name in f_names:
            f_path = os.path.join(f_sched_dir, f"{f_name}.json")
            f_results[f_name] = self.readRecordIfExists(f_path)
        return f_results
