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
import fcntl
import json
import os
import shutil
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from lsmiotool.lib.run import (
    Combination,
    ManifestDocument,
    ManifestSerializer,
    ManifestValidationError,
    RunPlan,
    ScalePoint,
    ScheduledPointResources,
)


class ArtifactError(Exception):
    """Base exception for all artifact store and layout operations."""

    pass


class RunCollisionError(ArtifactError):
    """Raised when attempting to allocate a run directory that already exists."""

    pass


class ContainmentError(ArtifactError):
    """Raised when a path violates containment rules (traversal, escaping symlinks, etc.)."""

    pass


class LockContentionError(ArtifactError):
    """Raised when process exclusive control lock cannot be acquired due to contention."""

    pass


class ManifestWriteError(ArtifactError):
    """Raised when manifest writing, fsync, or byte verification fails."""

    pass


class CleanupForbiddenError(ArtifactError):
    """Raised when attempting to clean up a forbidden directory or completed results/logs."""

    pass


STANDARD_STRIPES: Tuple[int, ...] = (16, 4)
STANDARD_BLOCK_SIZES: Tuple[str, ...] = ("8M", "1M", "64K")
STANDARD_COMBINATION_TUPLES: Tuple[Tuple[int, str], ...] = (
    (16, "8M"),
    (16, "1M"),
    (16, "64K"),
    (4, "8M"),
    (4, "1M"),
    (4, "64K"),
)


def validatePathContainment(f_path: str, f_base: str) -> str:
    """Validate that f_path is strictly contained within f_base without traversal or escaping symlinks."""
    if not isinstance(f_path, str) or not f_path.strip():
        raise ContainmentError(f"Path must be a non-empty string, got: {f_path!r}")
    if "\0" in f_path:
        raise ContainmentError(f"Path contains NUL byte: {f_path!r}")
    if not isinstance(f_base, str) or not f_base.strip():
        raise ContainmentError(f"Base path must be a non-empty string, got: {f_base!r}")

    # Check for raw .. in path components
    f_parts = os.path.normpath(f_path).split(os.sep)
    if ".." in f_parts:
        raise ContainmentError(f"Path traversal '..' detected in path: {f_path!r}")

    f_abs_base = os.path.abspath(f_base)
    f_abs_path = os.path.abspath(f_path)

    # Prefix boundary check
    if f_abs_path != f_abs_base and not f_abs_path.startswith(f_abs_base + os.sep):
        raise ContainmentError(
            f"Path '{f_abs_path}' is not contained within base '{f_abs_base}'"
        )

    # Symlink escape check: if exists or is link
    if os.path.exists(f_abs_path) or os.path.islink(f_abs_path):
        f_real_path = os.path.realpath(f_abs_path)
        f_real_base = os.path.realpath(f_abs_base)
        if f_real_path != f_real_base and not f_real_path.startswith(f_real_base + os.sep):
            raise ContainmentError(
                f"Symlink target '{f_real_path}' escapes base directory '{f_real_base}'"
            )

    # Check intermediate path components for escaping symlinks
    f_curr = f_abs_path
    while f_curr and f_curr != f_abs_base and len(f_curr) > len(f_abs_base):
        if os.path.islink(f_curr):
            f_target = os.path.realpath(f_curr)
            f_real_base = os.path.realpath(f_abs_base)
            if f_target != f_real_base and not f_target.startswith(f_real_base + os.sep):
                raise ContainmentError(
                    f"Symlink component '{f_curr}' pointing to '{f_target}' escapes base '{f_real_base}'"
                )
        f_curr = os.path.dirname(f_curr)

    return f_abs_path


class ArtifactLayout:
    """Immutable directory and file path layout under <benchmark_root>/runs/<run_id>."""

    __slots__ = ("m_benchmark_root", "m_run_id", "_frozen")

    def __init__(self, f_benchmark_root: str, f_run_id: str) -> None:
        if not isinstance(f_benchmark_root, str) or not f_benchmark_root.strip():
            raise ArtifactError(
                f"benchmark_root must be a non-empty string, got: {f_benchmark_root!r}"
            )
        if not isinstance(f_run_id, str) or not f_run_id.strip():
            raise ArtifactError(f"run_id must be a non-empty string, got: {f_run_id!r}")
        if "/" in f_run_id or "\\" in f_run_id or ".." in f_run_id or "\0" in f_run_id:
            raise ContainmentError(f"Invalid run_id containing path separators or traversal: {f_run_id!r}")

        f_norm_root = os.path.abspath(f_benchmark_root)
        if "\0" in f_norm_root:
            raise ContainmentError(f"benchmark_root contains NUL byte: {f_benchmark_root!r}")

        super().__setattr__("m_benchmark_root", f_norm_root)
        super().__setattr__("m_run_id", f_run_id.strip())
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
    def benchmarkRoot(self) -> str:
        return self.m_benchmark_root

    @property
    def benchmark_root(self) -> str:
        return self.m_benchmark_root

    @property
    def runId(self) -> str:
        return self.m_run_id

    @property
    def run_id(self) -> str:
        return self.m_run_id

    @property
    def runsDir(self) -> str:
        return os.path.join(self.m_benchmark_root, "runs")

    @property
    def runs_dir(self) -> str:
        return self.runsDir

    @property
    def runRoot(self) -> str:
        return os.path.join(self.runsDir, self.m_run_id)

    @property
    def run_root(self) -> str:
        return self.runRoot

    @property
    def manifestPath(self) -> str:
        return os.path.join(self.runRoot, "manifest.json")

    @property
    def manifest_path(self) -> str:
        return self.manifestPath

    @property
    def controlDir(self) -> str:
        return os.path.join(self.runRoot, "control")

    @property
    def control_dir(self) -> str:
        return self.controlDir

    @property
    def controlLockPath(self) -> str:
        return os.path.join(self.controlDir, "lock")

    @property
    def control_lock_path(self) -> str:
        return self.controlLockPath

    @property
    def controlEventsDir(self) -> str:
        return os.path.join(self.controlDir, "events")

    @property
    def control_events_dir(self) -> str:
        return self.controlEventsDir

    def controlEventPath(self, f_writer: str, f_sequence: Union[int, str]) -> str:
        if not isinstance(f_writer, str) or not f_writer.strip():
            raise ArtifactError(f"writer must be a non-empty string, got: {f_writer!r}")
        if "/" in f_writer or "\\" in f_writer or ".." in f_writer or "\0" in f_writer:
            raise ContainmentError(f"Invalid writer name: {f_writer!r}")
        return os.path.join(self.controlEventsDir, f_writer.strip(), f"{f_sequence}.json")

    @property
    def pointsDir(self) -> str:
        return os.path.join(self.runRoot, "points")

    @property
    def points_dir(self) -> str:
        return self.pointsDir

    def pointDirName(
        self,
        f_point: Union[ScalePoint, str, int],
        f_ordinal: Optional[int] = None,
    ) -> str:
        if isinstance(f_point, str):
            f_name = f_point.strip()
            if "/" in f_name or "\\" in f_name or ".." in f_name or "\0" in f_name:
                raise ContainmentError(f"Invalid point directory name: {f_point!r}")
            return f_name
        if isinstance(f_point, int):
            if f_point < 0:
                raise ArtifactError(f"ordinal/point integer must be non-negative, got: {f_point}")
            return f"{f_point:02d}-tasks-1"
        if isinstance(f_point, ScalePoint):
            if f_ordinal is not None:
                return f"{f_ordinal:02d}-tasks-{f_point.tasks}"
            return f"tasks-{f_point.tasks}"
        if isinstance(f_point, ScheduledPointResources):
            if f_ordinal is not None:
                return f"point-{f_ordinal:02d}"
            return "point"
        raise ArtifactError(f"Unsupported point descriptor: {type(f_point).__name__}")

    def pointDir(
        self,
        f_point: Union[ScalePoint, str, int],
        f_ordinal: Optional[int] = None,
    ) -> str:
        return os.path.join(self.pointsDir, self.pointDirName(f_point, f_ordinal))

    def pointSchedulerDir(
        self,
        f_point: Union[ScalePoint, str, int],
        f_ordinal: Optional[int] = None,
    ) -> str:
        return os.path.join(self.pointDir(f_point, f_ordinal), "scheduler")

    def pointSchedulerObservationsDir(
        self,
        f_point: Union[ScalePoint, str, int],
        f_writer: Optional[str] = None,
        f_ordinal: Optional[int] = None,
    ) -> str:
        f_obs = os.path.join(self.pointSchedulerDir(f_point, f_ordinal), "observations")
        if f_writer is not None:
            if not isinstance(f_writer, str) or not f_writer.strip():
                raise ArtifactError(f"writer must be a non-empty string, got: {f_writer!r}")
            if "/" in f_writer or "\\" in f_writer or ".." in f_writer or "\0" in f_writer:
                raise ContainmentError(f"Invalid writer name: {f_writer!r}")
            return os.path.join(f_obs, f_writer.strip())
        return f_obs

    def pointSchedulerObservationPath(
        self,
        f_point: Union[ScalePoint, str, int],
        f_writer: str,
        f_sequence: Union[int, str],
        f_ordinal: Optional[int] = None,
    ) -> str:
        return os.path.join(
            self.pointSchedulerObservationsDir(f_point, f_writer, f_ordinal),
            f"{f_sequence}.json",
        )

    def pointWorkerEventsDir(
        self,
        f_point: Union[ScalePoint, str, int],
        f_ordinal: Optional[int] = None,
    ) -> str:
        return os.path.join(self.pointDir(f_point, f_ordinal), "worker", "events")

    def pointWorkerEventPath(
        self,
        f_point: Union[ScalePoint, str, int],
        f_sequence: Union[int, str],
        f_ordinal: Optional[int] = None,
    ) -> str:
        return os.path.join(
            self.pointWorkerEventsDir(f_point, f_ordinal),
            f"{f_sequence}.json",
        )

    def pointCombinationsDir(
        self,
        f_point: Union[ScalePoint, str, int],
        f_ordinal: Optional[int] = None,
    ) -> str:
        return os.path.join(self.pointDir(f_point, f_ordinal), "combinations")

    def combinationName(self, f_combination: Union[Combination, str]) -> str:
        if isinstance(f_combination, str):
            f_name = f_combination.strip()
            if "/" in f_name or "\\" in f_name or ".." in f_name or "\0" in f_name:
                raise ContainmentError(f"Invalid combination name: {f_combination!r}")
            return f_name
        if isinstance(f_combination, Combination):
            return f_combination.name
        raise ArtifactError(f"Unsupported combination type: {type(f_combination).__name__}")

    def pointCombinationDir(
        self,
        f_point: Union[ScalePoint, str, int],
        f_combination: Union[Combination, str],
        f_ordinal: Optional[int] = None,
    ) -> str:
        return os.path.join(
            self.pointCombinationsDir(f_point, f_ordinal),
            self.combinationName(f_combination),
        )

    def pointControllerResultPath(
        self,
        f_point: Union[ScalePoint, str, int],
        f_combination: Union[Combination, str],
        f_ordinal: Optional[int] = None,
    ) -> str:
        return os.path.join(
            self.pointCombinationDir(f_point, f_combination, f_ordinal),
            "controller-result.json",
        )

    def pointRanksDir(
        self,
        f_point: Union[ScalePoint, str, int],
        f_ordinal: Optional[int] = None,
    ) -> str:
        return os.path.join(self.pointDir(f_point, f_ordinal), "ranks")

    def pointRankDir(
        self,
        f_point: Union[ScalePoint, str, int],
        f_global_rank: Union[int, str],
        f_ordinal: Optional[int] = None,
    ) -> str:
        return os.path.join(self.pointRanksDir(f_point, f_ordinal), str(f_global_rank))

    def pointRankCombinationDir(
        self,
        f_point: Union[ScalePoint, str, int],
        f_global_rank: Union[int, str],
        f_combination: Union[Combination, str],
        f_ordinal: Optional[int] = None,
    ) -> str:
        return os.path.join(
            self.pointRankDir(f_point, f_global_rank, f_ordinal),
            self.combinationName(f_combination),
        )

    def pointRankClaimPath(
        self,
        f_point: Union[ScalePoint, str, int],
        f_global_rank: Union[int, str],
        f_combination: Union[Combination, str],
        f_ordinal: Optional[int] = None,
    ) -> str:
        return os.path.join(
            self.pointRankCombinationDir(f_point, f_global_rank, f_combination, f_ordinal),
            "claim.lock",
        )

    def pointRankResultPath(
        self,
        f_point: Union[ScalePoint, str, int],
        f_global_rank: Union[int, str],
        f_combination: Union[Combination, str],
        f_ordinal: Optional[int] = None,
    ) -> str:
        return os.path.join(
            self.pointRankCombinationDir(f_point, f_global_rank, f_combination, f_ordinal),
            "result.json",
        )

    def pointLogsDir(
        self,
        f_point: Union[ScalePoint, str, int],
        f_ordinal: Optional[int] = None,
    ) -> str:
        return os.path.join(self.pointDir(f_point, f_ordinal), "logs")

    def pointCombinationLogsDir(
        self,
        f_point: Union[ScalePoint, str, int],
        f_combination: Union[Combination, str],
        f_ordinal: Optional[int] = None,
    ) -> str:
        return os.path.join(
            self.pointLogsDir(f_point, f_ordinal),
            self.combinationName(f_combination),
        )

    def pointRankLogPath(
        self,
        f_point: Union[ScalePoint, str, int],
        f_global_rank: Union[int, str],
        f_combination: Union[Combination, str],
        f_ordinal: Optional[int] = None,
    ) -> str:
        return os.path.join(
            self.pointCombinationLogsDir(f_point, f_combination, f_ordinal),
            f"rank_{f_global_rank}.log",
        )

    def pointDataDir(
        self,
        f_point: Union[ScalePoint, str, int],
        f_ordinal: Optional[int] = None,
    ) -> str:
        return os.path.join(self.pointDir(f_point, f_ordinal), "data")

    def pointDataSubdir(
        self,
        f_point: Union[ScalePoint, str, int],
        f_stripe: Union[int, str],
        f_block: str,
        f_ordinal: Optional[int] = None,
    ) -> str:
        return os.path.join(
            self.pointDataDir(f_point, f_ordinal),
            f"c{f_stripe}",
            f"b{f_block}",
        )

    def pointAllDataSubdirs(
        self,
        f_point: Union[ScalePoint, str, int],
        f_ordinal: Optional[int] = None,
    ) -> Tuple[str, ...]:
        return tuple(
            self.pointDataSubdir(f_point, f_stripe, f_block, f_ordinal)
            for f_stripe, f_block in STANDARD_COMBINATION_TUPLES
        )

    def pointWorkDir(
        self,
        f_point: Union[ScalePoint, str, int],
        f_ordinal: Optional[int] = None,
    ) -> str:
        return os.path.join(self.pointDir(f_point, f_ordinal), "work")

    def pointCombinationWorkDir(
        self,
        f_point: Union[ScalePoint, str, int],
        f_combination: Union[Combination, str],
        f_ordinal: Optional[int] = None,
    ) -> str:
        return os.path.join(
            self.pointWorkDir(f_point, f_ordinal),
            self.combinationName(f_combination),
        )

    def __repr__(self) -> str:
        return f"ArtifactLayout(benchmark_root={self.m_benchmark_root!r}, run_id={self.m_run_id!r})"

    def __eq__(self, f_other: Any) -> bool:
        if isinstance(f_other, ArtifactLayout):
            return (
                self.m_benchmark_root == f_other.m_benchmark_root
                and self.m_run_id == f_other.m_run_id
            )
        return False


class ControlLock:
    """Process-level exclusive control lock for a run using fcntl.flock on control/lock."""

    __slots__ = ("m_lock_path", "m_fd", "m_is_locked", "_frozen")

    def __init__(self, f_lock_path: str) -> None:
        if not isinstance(f_lock_path, str) or not f_lock_path.strip():
            raise ArtifactError(f"lock_path must be a non-empty string, got: {f_lock_path!r}")
        super().__setattr__("m_lock_path", os.path.abspath(f_lock_path))
        super().__setattr__("m_fd", None)
        super().__setattr__("m_is_locked", False)
        super().__setattr__("_frozen", True)

    def __setattr__(self, f_key: str, f_value: Any) -> None:
        if getattr(self, "_frozen", False):
            if f_key in ("m_fd", "m_is_locked"):
                super().__setattr__(f_key, f_value)
                return
            raise AttributeError(f"Cannot modify immutable {self.__class__.__name__}")
        super().__setattr__(f_key, f_value)

    def __delattr__(self, f_key: str) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"Cannot delete attribute from immutable {self.__class__.__name__}")
        super().__delattr__(f_key)

    @property
    def lock_path(self) -> str:
        return self.m_lock_path

    @property
    def lockPath(self) -> str:
        return self.m_lock_path

    @property
    def is_locked(self) -> bool:
        return self.m_is_locked

    @property
    def isLocked(self) -> bool:
        return self.m_is_locked

    def acquire(self, f_blocking: bool = False) -> bool:
        """Acquire process-level exclusive flock on the lock file.

        If non-blocking (default) and lock is held, raises LockContentionError.
        """
        if self.m_is_locked:
            return True

        f_parent = os.path.dirname(self.m_lock_path)
        os.makedirs(f_parent, exist_ok=True)

        try:
            f_fd = os.open(self.m_lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        except OSError as f_err:
            raise ArtifactError(f"Failed to open lock file '{self.m_lock_path}': {f_err}")

        f_flags = fcntl.LOCK_EX
        if not f_blocking:
            f_flags |= fcntl.LOCK_NB

        try:
            fcntl.flock(f_fd, f_flags)
        except (BlockingIOError, IOError, OSError) as f_err:
            os.close(f_fd)
            raise LockContentionError(
                f"Failed to acquire control lock on '{self.m_lock_path}': contention detected ({f_err})"
            )

        try:
            os.ftruncate(f_fd, 0)
            os.lseek(f_fd, 0, os.SEEK_SET)
            f_info = (
                f"pid={os.getpid()}\n"
                f"locked_at_utc={datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
            )
            os.write(f_fd, f_info.encode("utf-8"))
            os.fsync(f_fd)
        except OSError:
            pass

        self.m_fd = f_fd
        self.m_is_locked = True
        return True

    def release(self) -> None:
        """Release the flock and close the lock file descriptor."""
        if not self.m_is_locked or self.m_fd is None:
            return

        try:
            fcntl.flock(self.m_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            try:
                os.close(self.m_fd)
            except OSError:
                pass
            self.m_fd = None
            self.m_is_locked = False

    def __enter__(self) -> "ControlLock":
        self.acquire(f_blocking=False)
        return self

    def __exit__(self, f_exc_type: Any, f_exc_val: Any, f_exc_tb: Any) -> None:
        self.release()

    def __del__(self) -> None:
        try:
            self.release()
        except Exception:
            pass


class ArtifactStore:
    """Exclusive artifact store for managing run directory creation, manifest writes, point preparation, and cleanup."""

    __slots__ = ("m_layout", "_frozen")

    def __init__(
        self,
        f_benchmark_root_or_layout: Union[ArtifactLayout, str],
        f_run_id: Optional[str] = None,
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

    def validateContainment(self, f_path: str) -> str:
        """Validate that f_path is contained within this store's runRoot."""
        return validatePathContainment(f_path, self.m_layout.runRoot)

    def allocateRun(
        self, f_plan: Optional[Union[RunPlan, ManifestDocument]] = None
    ) -> str:
        """Atomically and exclusively allocate the run root directory structure.

        Fails with RunCollisionError if run directory already exists.
        """
        f_run_root = self.m_layout.runRoot
        f_runs_dir = self.m_layout.runsDir

        validatePathContainment(f_run_root, self.m_layout.benchmarkRoot)

        os.makedirs(f_runs_dir, exist_ok=True)

        try:
            os.mkdir(f_run_root)
        except FileExistsError as f_err:
            raise RunCollisionError(
                f"Run directory already exists at '{f_run_root}': collision rejected"
            )
        except OSError as f_err:
            raise ArtifactError(f"Failed to create run directory '{f_run_root}': {f_err}")

        try:
            os.makedirs(self.m_layout.controlDir, exist_ok=True)
            os.makedirs(self.m_layout.controlEventsDir, exist_ok=True)
            os.makedirs(self.m_layout.pointsDir, exist_ok=True)
        except OSError as f_err:
            raise ArtifactError(
                f"Failed to initialize run directory layout under '{f_run_root}': {f_err}"
            )

        if f_plan is not None:
            self.writeManifest(f_plan)

        return f_run_root

    def writeManifest(self, f_manifest_doc: Union[RunPlan, ManifestDocument]) -> str:
        """Write manifest.json once exclusively, fsync, and verify byte stability."""
        f_manifest_path = self.m_layout.manifestPath
        self.validateContainment(f_manifest_path)

        f_serialized_text = ManifestSerializer.serialize(f_manifest_doc)
        f_serialized_bytes = f_serialized_text.encode("utf-8")

        try:
            f_fd = os.open(
                f_manifest_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o644,
            )
        except FileExistsError as f_err:
            raise ManifestWriteError(
                f"Manifest file already exists at '{f_manifest_path}': {f_err}"
            )
        except OSError as f_err:
            raise ManifestWriteError(
                f"Failed to open manifest file at '{f_manifest_path}': {f_err}"
            )

        try:
            f_written = 0
            while f_written < len(f_serialized_bytes):
                f_n = os.write(f_fd, f_serialized_bytes[f_written:])
                if f_n == 0:
                    raise ManifestWriteError(f"Zero bytes written to manifest at '{f_manifest_path}'")
                f_written += f_n

            os.fsync(f_fd)
        except Exception as f_err:
            raise ManifestWriteError(
                f"Error writing or fsyncing manifest to '{f_manifest_path}': {f_err}"
            )
        finally:
            os.close(f_fd)

        try:
            with open(f_manifest_path, "rb") as f_f:
                f_read_bytes = f_f.read()
        except OSError as f_err:
            raise ManifestWriteError(
                f"Failed to read back manifest from '{f_manifest_path}' for verification: {f_err}"
            )

        if f_read_bytes != f_serialized_bytes:
            raise ManifestWriteError(
                f"Manifest byte stability verification failed: read {len(f_read_bytes)} bytes != written {len(f_serialized_bytes)} bytes"
            )

        f_parsed_doc = ManifestSerializer.deserialize(f_read_bytes)
        if f_parsed_doc.run_id != self.m_layout.runId:
            raise ManifestWriteError(
                f"Manifest run_id '{f_parsed_doc.run_id}' does not match layout run_id '{self.m_layout.runId}'"
            )

        return f_manifest_path

    def preparePoint(
        self,
        f_point: Union[ScalePoint, str, int],
        f_combinations: Optional[Sequence[Union[Combination, str]]] = None,
        f_ordinal: Optional[int] = None,
    ) -> str:
        """Create point-specific directory structure."""
        f_point_dir = self.m_layout.pointDir(f_point, f_ordinal)
        self.validateContainment(f_point_dir)

        # 1. Base point directories
        os.makedirs(f_point_dir, exist_ok=True)
        os.makedirs(self.m_layout.pointSchedulerDir(f_point, f_ordinal), exist_ok=True)
        os.makedirs(
            self.m_layout.pointSchedulerObservationsDir(f_point, f_ordinal=f_ordinal),
            exist_ok=True,
        )
        os.makedirs(self.m_layout.pointWorkerEventsDir(f_point, f_ordinal), exist_ok=True)
        os.makedirs(self.m_layout.pointCombinationsDir(f_point, f_ordinal), exist_ok=True)
        os.makedirs(self.m_layout.pointRanksDir(f_point, f_ordinal), exist_ok=True)
        os.makedirs(self.m_layout.pointLogsDir(f_point, f_ordinal), exist_ok=True)
        os.makedirs(self.m_layout.pointWorkDir(f_point, f_ordinal), exist_ok=True)

        # 2. Six standard data directories
        for f_data_dir in self.m_layout.pointAllDataSubdirs(f_point, f_ordinal):
            os.makedirs(f_data_dir, exist_ok=True)

        # 3. Combinations and combination work and log directories
        if f_combinations:
            for f_combo in f_combinations:
                os.makedirs(
                    self.m_layout.pointCombinationDir(f_point, f_combo, f_ordinal),
                    exist_ok=True,
                )
                os.makedirs(
                    self.m_layout.pointCombinationWorkDir(f_point, f_combo, f_ordinal),
                    exist_ok=True,
                )
                os.makedirs(
                    self.m_layout.pointCombinationLogsDir(f_point, f_combo, f_ordinal),
                    exist_ok=True,
                )
        else:
            for f_stripe, f_block in STANDARD_COMBINATION_TUPLES:
                f_cname = f"c{f_stripe}_b{f_block}"
                os.makedirs(
                    self.m_layout.pointCombinationDir(f_point, f_cname, f_ordinal),
                    exist_ok=True,
                )
                os.makedirs(
                    self.m_layout.pointCombinationWorkDir(f_point, f_cname, f_ordinal),
                    exist_ok=True,
                )
                os.makedirs(
                    self.m_layout.pointCombinationLogsDir(f_point, f_cname, f_ordinal),
                    exist_ok=True,
                )

        # Write point preparation metadata
        f_point_id = self.m_layout.pointDirName(f_point, f_ordinal)
        f_meta_path = os.path.join(f_point_dir, ".point_metadata.json")
        f_meta = {
            "run_id": self.m_layout.runId,
            "point_id": f_point_id,
            "prepared_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "prepared",
        }
        with open(f_meta_path, "w", encoding="utf-8") as f_f:
            json.dump(f_meta, f_f, indent=2)
            f_f.write("\n")

        return f_point_dir

    def cleanupIncompletePreparation(
        self,
        f_point: Union[ScalePoint, str, int],
        f_ordinal: Optional[int] = None,
    ) -> None:
        """Safely clean up incomplete point preparation without touching run root, logs, or results."""
        if isinstance(f_point, str) and (f_point.startswith("/") or "/" in f_point or "\\" in f_point):
            f_point_dir = os.path.abspath(f_point)
        else:
            f_point_dir = self.m_layout.pointDir(f_point, f_ordinal)

        # 1. Forbidden roots check
        f_norm_benchmark_root = os.path.abspath(self.m_layout.benchmarkRoot)
        f_norm_runs_dir = os.path.abspath(self.m_layout.runsDir)
        f_norm_run_root = os.path.abspath(self.m_layout.runRoot)
        f_norm_points_dir = os.path.abspath(self.m_layout.pointsDir)

        if f_point_dir in (
            f_norm_benchmark_root,
            f_norm_runs_dir,
            f_norm_run_root,
            f_norm_points_dir,
        ):
            raise CleanupForbiddenError(
                f"Cannot clean forbidden root directory: '{f_point_dir}'"
            )

        # 2. Containment and point hierarchy check
        self.validateContainment(f_point_dir)
        if not f_point_dir.startswith(f_norm_points_dir + os.sep):
            raise CleanupForbiddenError(
                f"Cannot clean directory '{f_point_dir}': not strictly beneath points directory '{f_norm_points_dir}'"
            )

        if not os.path.exists(f_point_dir):
            return

        # 3. Check for existing results or log contents
        # Check combinations results
        f_combos_dir = os.path.join(f_point_dir, "combinations")
        if os.path.exists(f_combos_dir):
            for f_root, _, f_files in os.walk(f_combos_dir):
                for f_file in f_files:
                    if f_file == "controller-result.json":
                        raise CleanupForbiddenError(
                            f"Cannot clean point '{f_point_dir}': controller result exists at '{os.path.join(f_root, f_file)}'"
                        )

        # Check ranks results and claims
        f_ranks_dir = os.path.join(f_point_dir, "ranks")
        if os.path.exists(f_ranks_dir):
            for f_root, _, f_files in os.walk(f_ranks_dir):
                for f_file in f_files:
                    if f_file in ("result.json", "claim.lock"):
                        raise CleanupForbiddenError(
                            f"Cannot clean point '{f_point_dir}': rank artifact exists at '{os.path.join(f_root, f_file)}'"
                        )

        # 4. Safe removal of incomplete preparation:
        # Clean work/ and data/ directories
        f_work_dir = self.m_layout.pointWorkDir(f_point, f_ordinal)
        if os.path.exists(f_work_dir):
            shutil.rmtree(f_work_dir, ignore_errors=False)

        f_data_dir = self.m_layout.pointDataDir(f_point, f_ordinal)
        if os.path.exists(f_data_dir):
            shutil.rmtree(f_data_dir, ignore_errors=False)

        # Remove incomplete metadata
        f_meta_path = os.path.join(f_point_dir, ".point_metadata.json")
        if os.path.exists(f_meta_path):
            try:
                os.remove(f_meta_path)
            except OSError:
                pass

        # Re-create empty work and data directories
        os.makedirs(f_work_dir, exist_ok=True)
        os.makedirs(f_data_dir, exist_ok=True)
        for f_subdir in self.m_layout.pointAllDataSubdirs(f_point, f_ordinal):
            os.makedirs(f_subdir, exist_ok=True)

    def getControlLock(self) -> ControlLock:
        """Create and return a ControlLock instance for this run."""
        return ControlLock(self.m_layout.controlLockPath)
