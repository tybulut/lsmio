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

import os
import shutil
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union


class ArchiveError(Exception):
    """Base exception for archival errors and state hygiene failures."""

    pass


class ArchiveRequest:
    """Immutable parsed and validated archive request value object."""

    __slots__ = ("m_target", "m_scale", "m_variant", "m_dest", "_frozen")

    def __init__(
        self,
        f_target: str,
        f_scale: str,
        f_variant: Optional[str] = None,
        f_dest: Optional[str] = None,
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

        super().__setattr__("m_target", f_target.strip().lower())
        super().__setattr__("m_scale", f_scale.strip().lower())
        super().__setattr__(
            "m_variant", f_variant.strip().lower() if f_variant else None
        )
        super().__setattr__("m_dest", f_dest.strip() if f_dest else None)
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

    def toDict(self) -> Dict[str, Any]:
        """Convert ArchiveRequest to dictionary representation."""
        return {
            "target": self.m_target,
            "scale": self.m_scale,
            "variant": self.m_variant,
            "dest": self.m_dest,
        }

    def __repr__(self) -> str:
        return (
            f"ArchiveRequest(target={self.m_target!r}, "
            f"scale={self.m_scale!r}, "
            f"variant={self.m_variant!r}, "
            f"dest={self.m_dest!r})"
        )

    def __eq__(self, f_other: Any) -> bool:
        if isinstance(f_other, ArchiveRequest):
            return (
                self.m_target == f_other.m_target
                and self.m_scale == f_other.m_scale
                and self.m_variant == f_other.m_variant
                and self.m_dest == f_other.m_dest
            )
        return False

    def __hash__(self) -> int:
        return hash((self.m_target, self.m_scale, self.m_variant, self.m_dest))


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
    ) -> str:
        """Atomically moves f_source_dir to collision-free target, returning str (INV-PAIR-8)."""
        if not f_source_dir or not str(f_source_dir).strip():
            raise ArchiveError(
                f"source_dir must be a non-empty path, got: {f_source_dir!r}"
            )
        abs_source = Path(os.path.abspath(str(f_source_dir)))
        if not abs_source.exists():
            raise ArchiveError(f"Active output directory does not exist: {abs_source}")
        if not abs_source.is_dir():
            raise ArchiveError(f"Active output path is not a directory: {abs_source}")

        target_path = (
            Path(os.path.abspath(str(f_target_path)))
            if f_target_path is not None
            else Path(cls.resolveTargetDirectory(f_dest_root, f_arm_id, f_role))
        )

        # Ensure aggregated reports exist prior to moving into archive
        report_file = abs_source / "lsm-report.csv"
        if not report_file.is_file():
            try:
                if any(abs_source.glob("*/*/out-*.txt*")):
                    from lsmiotool.lib.output import LsmioAggOutput

                    agg = LsmioAggOutput(str(abs_source), f_scale="variants")
                    agg.generateReports(f_out_dir=str(abs_source))
            except Exception:
                pass

        target_path.parent.mkdir(parents=True, exist_ok=True)
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
        report_file = abs_source / "lsm-report.csv"
        if not report_file.is_file():
            try:
                if any(abs_source.glob("*/*/out-*.txt*")):
                    from lsmiotool.lib.output import LsmioAggOutput

                    agg = LsmioAggOutput(str(abs_source), f_scale="variants")
                    agg.generateReports(f_out_dir=str(abs_source))
            except Exception:
                pass

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
