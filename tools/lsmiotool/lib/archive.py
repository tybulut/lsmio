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
from typing import Any, Dict, Optional


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
            raise ArchiveError(
                f"target must be a non-empty string, got: {f_target!r}"
            )
        if not isinstance(f_scale, str) or not f_scale.strip():
            raise ArchiveError(
                f"scale must be a non-empty string, got: {f_scale!r}"
            )
        if f_variant is not None and (
            not isinstance(f_variant, str) or not f_variant.strip()
        ):
            raise ArchiveError(
                f"variant must be a non-empty string or None, got: {f_variant!r}"
            )
        if f_dest is not None and (
            not isinstance(f_dest, str) or not f_dest.strip()
        ):
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
            raise AttributeError(
                f"Cannot modify immutable {self.__class__.__name__}"
            )
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
    def resolveTargetDirectory(cls, f_dest_dir: str, f_arm_id: str) -> str:
        """Calculates collision-free archive destination path.

        Format:
            Base target: <f_dest_dir>/outputs-<f_arm_id>
            Collision suffix: <f_dest_dir>/outputs-<f_arm_id>-1, -2, ...
        """
        if not isinstance(f_dest_dir, str) or not f_dest_dir.strip():
            raise ArchiveError(
                f"dest_dir must be a non-empty string, got: {f_dest_dir!r}"
            )
        f_abs_dest = os.path.abspath(f_dest_dir)
        base_name = f"outputs-{f_arm_id}" if f_arm_id else "outputs"
        base_path = os.path.join(f_abs_dest, base_name)
        if not os.path.exists(base_path):
            return base_path
        f_suffix = 1
        while os.path.exists(f"{base_path}-{f_suffix}"):
            f_suffix += 1
        return f"{base_path}-{f_suffix}"

    @classmethod
    def executeArchive(
        cls,
        f_source_dir: str,
        f_dest_root: str,
        f_arm_id: str,
    ) -> str:
        """Atomically moves f_source_dir to collision-free target and recreates f_source_dir.

        Returns:
            Absolute path to archived target directory.

        Raises:
            ArchiveError: If source does not exist or move operation fails.
        """
        if not isinstance(f_source_dir, str) or not f_source_dir.strip():
            raise ArchiveError(
                f"source_dir must be a non-empty string, got: {f_source_dir!r}"
            )
        f_abs_source = os.path.abspath(f_source_dir)
        if not os.path.exists(f_abs_source):
            raise ArchiveError(
                f"Active output directory does not exist: {f_abs_source}"
            )
        if not os.path.isdir(f_abs_source):
            raise ArchiveError(
                f"Active output path is not a directory: {f_abs_source}"
            )

        f_target_dir = cls.resolveTargetDirectory(f_dest_root, f_arm_id)
        try:
            os.makedirs(os.path.abspath(f_dest_root), exist_ok=True)
        except Exception as f_err:
            raise ArchiveError(
                f"Failed to create destination directory {f_dest_root}: {f_err}"
            ) from f_err

        try:
            shutil.move(f_abs_source, f_target_dir)
        except Exception as f_err:
            raise ArchiveError(
                f"Failed to move {f_abs_source} to {f_target_dir}: {f_err}"
            ) from f_err

        try:
            os.makedirs(f_abs_source, exist_ok=True)
        except Exception as f_err:
            raise ArchiveError(
                f"Failed to recreate active output directory {f_abs_source}: {f_err}"
            ) from f_err

        return f_target_dir
