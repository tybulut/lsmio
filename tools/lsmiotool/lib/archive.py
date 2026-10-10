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

"""Atomic move-on-archive semantics and collision-guarded archive engine for LSMIO."""

import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


class ArchiveError(Exception):
    """Base exception for archival errors and state hygiene failures."""

    pass


class ArchiveRequest:
    """Immutable parsed and validated archive request value object.

    setup: LSMIO setup naming the arm (bmtool BM_SETUP); None means BM_SETUP from
    the environment, else NATIVE-M (or, for an lsmiotool run root, the run's own).
    source: explicit source (an lsmiotool run root or a bmtool outputs directory);
    None means resolve it from the benchmark root.
    """

    __slots__ = (
        "m_target",
        "m_scale",
        "m_variant",
        "m_dest",
        "m_setup",
        "m_source",
        "_frozen",
    )

    def __init__(
        self,
        f_target: str,
        f_scale: str,
        f_variant: Optional[str] = None,
        f_dest: Optional[str] = None,
        f_setup: Optional[str] = None,
        f_source: Optional[str] = None,
    ) -> None:
        if not isinstance(f_target, str) or not f_target.strip():
            raise ArchiveError(f"target must be a non-empty string, got: {f_target!r}")
        if not isinstance(f_scale, str) or not f_scale.strip():
            raise ArchiveError(f"scale must be a non-empty string, got: {f_scale!r}")
        if f_variant is not None and (
            not isinstance(f_variant, str) or not f_variant.strip()
        ):
            raise ArchiveError(
                f"variant must be a non-empty string or None, got: {f_variant!r}"
            )
        if f_dest is not None and (not isinstance(f_dest, str) or not f_dest.strip()):
            raise ArchiveError(
                f"dest must be a non-empty string or None, got: {f_dest!r}"
            )
        if f_setup is not None and (
            not isinstance(f_setup, str) or not f_setup.strip()
        ):
            raise ArchiveError(
                f"setup must be a non-empty string or None, got: {f_setup!r}"
            )
        if f_source is not None and (
            not isinstance(f_source, str) or not f_source.strip()
        ):
            raise ArchiveError(
                f"source must be a non-empty string or None, got: {f_source!r}"
            )

        super().__setattr__("m_target", f_target.strip().lower())
        super().__setattr__("m_scale", f_scale.strip().lower())
        super().__setattr__(
            "m_variant", f_variant.strip().lower() if f_variant else None
        )
        super().__setattr__("m_dest", f_dest.strip() if f_dest else None)
        super().__setattr__("m_setup", f_setup.strip().upper() if f_setup else None)
        super().__setattr__("m_source", f_source.strip() if f_source else None)
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
    def target(self) -> str:
        return self.m_target

    @property
    def scale(self) -> str:
        return self.m_scale

    @property
    def variant(self) -> Optional[str]:
        return self.m_variant

    @property
    def dest(self) -> Optional[str]:
        return self.m_dest

    @property
    def setup(self) -> Optional[str]:
        return self.m_setup

    @property
    def source(self) -> Optional[str]:
        return self.m_source

    def toDict(self) -> Dict[str, Any]:
        """Convert ArchiveRequest to dictionary representation."""
        f_dict: Dict[str, Any] = {
            "target": self.m_target,
            "scale": self.m_scale,
            "variant": self.m_variant,
            "dest": self.m_dest,
        }
        if self.m_setup is not None:
            f_dict["setup"] = self.m_setup
        if self.m_source is not None:
            f_dict["source"] = self.m_source
        return f_dict

    def __repr__(self) -> str:
        return (
            f"ArchiveRequest(target={self.m_target!r}, "
            f"scale={self.m_scale!r}, "
            f"variant={self.m_variant!r}, "
            f"dest={self.m_dest!r}, "
            f"setup={self.m_setup!r}, "
            f"source={self.m_source!r})"
        )

    def __eq__(self, f_other: Any) -> bool:
        if isinstance(f_other, ArchiveRequest):
            return (
                self.m_target == f_other.m_target
                and self.m_scale == f_other.m_scale
                and self.m_variant == f_other.m_variant
                and self.m_dest == f_other.m_dest
                and self.m_setup == f_other.m_setup
                and self.m_source == f_other.m_source
            )
        return False

    def __hash__(self) -> int:
        return hash(
            (
                self.m_target,
                self.m_scale,
                self.m_variant,
                self.m_dest,
                self.m_setup,
                self.m_source,
            )
        )


def resolveArchiveDest(
    f_benchmark_root: str,
    f_mode: Optional[str] = None,
    f_scale: Optional[str] = None,
    f_explicit: Optional[str] = None,
) -> str:
    """Resolve the archive destination root, mirroring bmtool/include/archive-dest.in.sh.

    Layout (three destinations under <benchmark_root>/lsmio-archive):
        backends/<scale>  multi-backend intra-allocation runs (mode 'backends')
        variants          variant matrix runs (scale 'variants')
        baseline          plain scaling runs (local, bake, small, large)

    Args:
        f_benchmark_root: Benchmark root ($BM_PATH equivalent).
        f_mode: Launch mode ('backends' or 'standard'); None means standard.
        f_scale: Scale token ('variants' or a plain scale); 'baseline' is the
            deprecated spelling of 'variants'.
        f_explicit: Explicit destination from --dest / --out-dir or BM_ARCHIVE_DEST.
            Absolute paths are used as given, except a path starting with
            '/lsmio-archive' which is treated as benchmark-root relative;
            relative paths resolve against the benchmark root.

    Returns:
        Absolute archive destination root.
    """
    f_root = os.path.join(f_benchmark_root, "lsmio-archive")

    f_val = str(f_explicit).strip() if f_explicit else ""
    if f_val:
        if f_val == "/lsmio-archive" or f_val.startswith("/lsmio-archive/"):
            return os.path.join(f_benchmark_root, f_val.lstrip("/"))
        if os.path.isabs(f_val):
            return f_val
        return os.path.join(f_benchmark_root, f_val)

    f_norm_mode = (f_mode or "standard").strip().lower()
    f_norm_scale = (f_scale or "").strip().lower()
    if f_norm_scale == "baseline":
        f_norm_scale = "variants"

    if f_norm_mode == "backends":
        return (
            os.path.join(f_root, "backends", f_norm_scale)
            if f_norm_scale
            else os.path.join(f_root, "backends")
        )
    if f_norm_scale == "variants":
        return os.path.join(f_root, "variants")
    return os.path.join(f_root, "baseline")


class ArchiveEngine:
    """Core engine executing move-on-archive semantics with collision avoidance."""

    # Written into an archive exported from an lsmiotool run root (exportRunRoot), so
    # the same run is not archived twice; not part of bmtool's layout
    RUN_MARKER_FILE = ".lsmiotool-run.json"

    # Written next to a multi-arm run's manifest by 'lsmiotool run': the arm belongs to a
    # paired/versioned/backends group and is archived by the run itself
    ARM_MARKER_FILE = ".lsmiotool-arm.json"

    @classmethod
    def writeRunMarker(
        cls,
        f_target: Union[str, Path],
        f_run_id: str,
        f_run_root: Union[str, Path],
        f_points: List[str],
    ) -> None:
        """Record in an archive dir which run (and points) it was exported from, so the
        same run is not archived twice. Points of an existing marker for the same run are
        kept (a backends arm is archived one point at a time)."""
        from lsmiotool.lib.log import Console

        f_path = os.path.join(str(f_target), cls.RUN_MARKER_FILE)
        f_all_points = list(f_points)
        try:
            with open(f_path, "r", encoding="utf-8") as f_f:
                f_old = json.load(f_f)
            if isinstance(f_old, dict) and f_old.get("run_id") == f_run_id:
                f_all_points = sorted(set(f_old.get("points") or []) | set(f_points))
        except (OSError, ValueError):
            pass
        try:
            with open(f_path, "w", encoding="utf-8") as f_f:
                json.dump(
                    {
                        "run_id": f_run_id,
                        "run_root": os.path.abspath(str(f_run_root)),
                        "points": f_all_points,
                    },
                    f_f,
                    indent=2,
                )
        except OSError as f_err:
            Console.warning(f"Cannot write {cls.RUN_MARKER_FILE} in {f_target}: {f_err}")

    @classmethod
    def readArmMarker(cls, f_run_root: Union[str, Path]) -> Optional[Dict[str, Any]]:
        """The arm marker of a run root written by a multi-arm 'lsmiotool run', or None."""
        try:
            with open(
                os.path.join(str(f_run_root), cls.ARM_MARKER_FILE), "r", encoding="utf-8"
            ) as f_f:
                f_doc = json.load(f_f)
        except (OSError, ValueError):
            return None
        return f_doc if isinstance(f_doc, dict) else None

    @classmethod
    def findArchivedRun(
        cls, f_dest_root: Union[str, Path], f_run_id: str
    ) -> Optional[str]:
        """The outputs-* dir under f_dest_root exported from run f_run_id, or None."""
        f_dest = str(f_dest_root)
        try:
            f_entries = sorted(os.listdir(f_dest))
        except OSError:
            return None
        for f_entry in f_entries:
            if not f_entry.startswith("outputs-"):
                continue
            f_marker = os.path.join(f_dest, f_entry, cls.RUN_MARKER_FILE)
            try:
                with open(f_marker, "r", encoding="utf-8") as f_f:
                    f_doc = json.load(f_f)
            except (OSError, ValueError):
                continue
            if isinstance(f_doc, dict) and f_doc.get("run_id") == f_run_id:
                return os.path.join(f_dest, f_entry)
        return None

    @classmethod
    def exportRunRoot(
        cls,
        f_run_root: Union[str, Path],
        f_dest_root: Union[str, Path],
        f_arm_id: str,
        f_target_path: Optional[Union[str, Path]] = None,
    ) -> Tuple[str, List[str], List[str]]:
        """Archive an lsmiotool run root in bmtool's layout, as 'lsmiotool run' does.

        The rank logs of every succeeded scale point are copied (lib/export.py) to
        <target>/<nodes>/<date>/out-<arm>-<rf>-<bs>-...txt and the agg files and
        lsm-report.csv generated; the run root itself is left untouched (it is the
        run's evidence), so nothing is recreated in its place.

        Returns:
            (target directory, exported point ids, skipped point ids)

        Raises:
            ArchiveError: When the run root cannot be read or no point could be
                exported (nothing is left behind in the destination then).
        """
        from lsmiotool.lib.export import exportPoint, generateReports
        from lsmiotool.lib.log import Console
        from lsmiotool.lib.runparse import RunParseError, RunRootResolver
        from lsmiotool.lib.state import PointRunState

        try:
            f_resolved = RunRootResolver.resolve(str(f_run_root), f_allow_partial=True)
        except RunParseError as f_err:
            raise ArchiveError(f"Cannot read run root {f_run_root}: {f_err}") from f_err

        f_store = f_resolved.evidenceStore
        f_skipped = [
            f_pt.pointId
            for f_pt in f_resolved.points
            if f_pt.state != PointRunState.SUCCEEDED
        ]
        f_points = [
            f_pt for f_pt in f_resolved.points if f_pt.state == PointRunState.SUCCEEDED
        ]
        if not f_points:
            raise ArchiveError(
                f"Run '{f_resolved.runId}' ({f_run_root}) has no succeeded scale point "
                f"to archive"
            )

        f_target = (
            os.path.abspath(str(f_target_path))
            if f_target_path is not None
            else cls.resolveTargetDirectory(f_dest_root, f_arm_id)
        )
        f_created = not os.path.exists(f_target)
        f_exported: List[str] = []
        for f_pt in f_points:
            try:
                exportPoint(
                    f_layout=f_store.layout,
                    f_evidence_store=f_store,
                    f_scale_point=f_pt.scalePoint,
                    f_ordinal=f_pt.ordinal,
                    f_combinations=f_resolved.plan.combinations,
                    f_infix=f_arm_id,
                    f_node_dir=os.path.join(f_target, str(f_pt.scalePoint.nodes)),
                )
            except Exception as f_err:
                Console.warning(f"Not archiving point '{f_pt.pointId}': {f_err}")
                f_skipped.append(f_pt.pointId)
                continue
            f_exported.append(f_pt.pointId)

        if not f_exported:
            if f_created:
                shutil.rmtree(f_target, ignore_errors=True)
            raise ArchiveError(
                f"No point of run '{f_resolved.runId}' could be exported from {f_run_root}"
            )

        if not generateReports(f_target):
            Console.warning(f"No lsm-report.csv rows for {f_target}")
        cls.writeRunMarker(f_target, f_resolved.runId, f_run_root, f_exported)
        return f_target, f_exported, f_skipped

    @classmethod
    def resolveArmId(
        cls,
        f_setup: str = "NATIVE-M",
        f_variant: Optional[str] = None,
    ) -> str:
        """Derives mechanical arm identifier string matching bmtool archive.in.sh.

        Arm ID = VariantCatalogue.getInfix(f_setup, f_variant)
        """
        from lsmiotool.lib.variants import VariantCatalogue

        if not isinstance(f_setup, str) or not f_setup.strip():
            f_setup = "NATIVE-M"
        clean_setup = f_setup.strip()
        if clean_setup.lower() == "lsmio":
            clean_setup = "LSMIO-M"
        return VariantCatalogue.getInfix(clean_setup, f_variant)

    @classmethod
    def resolvePairTargetDirectories(
        cls,
        f_dest_dir: Union[str, Path],
        f_arm_id: str,
    ) -> Tuple[str, str]:
        """Atomically resolves synchronized target paths for paired (:run, :base) archives."""
        if not f_dest_dir or not str(f_dest_dir).strip():
            raise ArchiveError(
                f"dest_dir must be a non-empty path, got: {f_dest_dir!r}"
            )
        if not isinstance(f_arm_id, str) or not f_arm_id.strip():
            raise ArchiveError(f"arm_id must be a non-empty string, got: {f_arm_id!r}")

        dest_root = Path(os.path.abspath(str(f_dest_dir)))
        run_base = dest_root / f"outputs-{f_arm_id}:run"
        base_base = dest_root / f"outputs-{f_arm_id}:base"

        if not run_base.exists() and not base_base.exists():
            return (str(run_base), str(base_base))

        suffix = 1
        while (dest_root / f"outputs-{f_arm_id}:run-{suffix}").exists() or (
            dest_root / f"outputs-{f_arm_id}:base-{suffix}"
        ).exists():
            suffix += 1

        return (
            str(dest_root / f"outputs-{f_arm_id}:run-{suffix}"),
            str(dest_root / f"outputs-{f_arm_id}:base-{suffix}"),
        )

    @classmethod
    def resolveTargetDirectory(
        cls,
        f_dest_dir: Union[str, Path],
        f_arm_id: str,
        f_role: Optional[str] = None,
    ) -> str:
        """Calculates collision-free archive destination path, returning str (INV-PAIR-8)."""
        if not f_dest_dir or not str(f_dest_dir).strip():
            raise ArchiveError(
                f"dest_dir must be a non-empty path, got: {f_dest_dir!r}"
            )
        dest_root = Path(os.path.abspath(str(f_dest_dir)))
        if f_role:
            base_name = f"outputs-{f_arm_id}:{f_role}"
        else:
            base_name = f"outputs-{f_arm_id}" if f_arm_id else "outputs"
        base_path = dest_root / base_name
        if not base_path.exists():
            return str(base_path)
        suffix = 1
        while (dest_root / f"{base_name}-{suffix}").exists():
            suffix += 1
        return str(dest_root / f"{base_name}-{suffix}")

    @classmethod
    def executeArchive(
        cls,
        f_source_dir: Union[str, Path],
        f_dest_root: Union[str, Path],
        f_arm_id: str,
        f_role: Optional[str] = None,
        f_target_path: Optional[Union[str, Path]] = None,
        f_scale: Optional[str] = None,
    ) -> str:
        """Atomically moves f_source_dir to collision-free target, returning str (INV-PAIR-8).

        bmtool include/archive.in.sh semantics for a bmtool outputs directory: reports
        are generated first when missing (for f_scale's node counts; every node dir
        when None), the directory is moved and an empty one recreated in its place.
        """
        if not f_source_dir or not str(f_source_dir).strip():
            raise ArchiveError(
                f"source_dir must be a non-empty path, got: {f_source_dir!r}"
            )
        abs_source = Path(os.path.abspath(str(f_source_dir)))
        if not abs_source.exists():
            f_msg = f"Active output directory does not exist: {abs_source}"
            # bmtool's batch job moves a failed run's outputs there instead of leaving them
            f_failed_dir = abs_source.parent / "outputs-failed"
            if f_failed_dir.is_dir():
                f_msg += f" (a failed benchmark job leaves its outputs in {f_failed_dir})"
            raise ArchiveError(f_msg)
        if not abs_source.is_dir():
            raise ArchiveError(f"Active output path is not a directory: {abs_source}")

        target_path = (
            Path(os.path.abspath(str(f_target_path)))
            if f_target_path is not None
            else Path(cls.resolveTargetDirectory(f_dest_root, f_arm_id, f_role))
        )

        # Ensure aggregated reports exist prior to moving into archive
        from lsmiotool.lib.output import ensureLsmioReports

        ensureLsmioReports(str(abs_source), f_scale=f_scale)

        target_path.parent.mkdir(parents=True, exist_ok=True)
        # bmtool's clean-finish marker (jobs/batch.in.sh) is job bookkeeping, not results
        try:
            (abs_source / ".bm-job-ok").unlink()
        except FileNotFoundError:
            pass
        try:
            shutil.move(str(abs_source), str(target_path))
        except Exception as err:
            raise ArchiveError(
                f"Failed to move {abs_source} to {target_path}: {err}"
            ) from err

        try:
            abs_source.mkdir(parents=True, exist_ok=True)
        except Exception as err:
            raise ArchiveError(
                f"Failed to recreate active output directory {abs_source}: {err}"
            ) from err

        return str(target_path)

    @classmethod
    def replicateArchive(
        cls,
        f_source_dir: Union[str, Path],
        f_dest_root: Union[str, Path],
        f_arm_id: str,
        f_role: str = "base",
        f_target_path: Optional[Union[str, Path]] = None,
    ) -> str:
        """Copies staged baseline output to destination archive, returning str path (INV-PAIR-8)."""
        if not f_source_dir or not str(f_source_dir).strip():
            raise ArchiveError(
                f"source_dir must be a non-empty path, got: {f_source_dir!r}"
            )
        abs_source = Path(os.path.abspath(str(f_source_dir)))
        if not abs_source.exists():
            raise ArchiveError(
                f"Staged baseline directory does not exist: {abs_source}"
            )
        if not abs_source.is_dir():
            raise ArchiveError(f"Staged baseline path is not a directory: {abs_source}")

        target_path = (
            Path(os.path.abspath(str(f_target_path)))
            if f_target_path is not None
            else Path(cls.resolveTargetDirectory(f_dest_root, f_arm_id, f_role))
        )

        # Ensure aggregated reports exist prior to replicating staged baseline
        from lsmiotool.lib.output import ensureLsmioReports

        ensureLsmioReports(str(abs_source))

        target_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copytree(str(abs_source), str(target_path))
        except Exception as err:
            raise ArchiveError(
                f"Failed to replicate {abs_source} to {target_path}: {err}"
            ) from err
        return str(target_path)

    @classmethod
    def executePairedArchive(
        cls,
        f_run_source_dir: Union[str, Path],
        f_base_source_dir: Union[str, Path],
        f_dest_root: Union[str, Path],
        f_arm_id: str,
    ) -> Tuple[str, str]:
        """Atomically archives paired variant run (:run) and staged baseline (:base)."""
        target_run, target_base = cls.resolvePairTargetDirectories(
            f_dest_root, f_arm_id
        )
        cls.executeArchive(
            f_source_dir=f_run_source_dir,
            f_dest_root=f_dest_root,
            f_arm_id=f_arm_id,
            f_role="run",
            f_target_path=target_run,
        )
        cls.replicateArchive(
            f_source_dir=f_base_source_dir,
            f_dest_root=f_dest_root,
            f_arm_id=f_arm_id,
            f_role="base",
            f_target_path=target_base,
        )
        return (target_run, target_base)
