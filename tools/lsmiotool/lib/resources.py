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
import os
from typing import Any, Dict, Optional, Tuple, Union


class LayoutConfigurationError(Exception):
    """Raised when runtime layout or resource configuration is invalid."""

    pass


class ExecutionMode(Enum):
    """Execution mode distinguishing source tree from installed installation."""

    SOURCE = "source"
    INSTALLED = "installed"

    @property
    def isSource(self) -> bool:
        return self == ExecutionMode.SOURCE

    @property
    def is_source(self) -> bool:
        return self.isSource

    @property
    def isInstalled(self) -> bool:
        return self == ExecutionMode.INSTALLED

    @property
    def is_installed(self) -> bool:
        return self.isInstalled


class InstallRelativeLayout:
    """Immutable relative path specification for installed assets anchored to an entry point."""

    __slots__ = (
        "m_package_root",
        "m_profile_file",
        "m_asset_root",
        "m_worker_executable",
        "m_version_file",
        "_frozen",
    )

    def __init__(
        self,
        f_package_root: str,
        f_profile_file: str,
        f_asset_root: str,
        f_worker_executable: str,
        f_version_file: str,
    ) -> None:
        self._validateRelativeConstant("package_root", f_package_root)
        self._validateRelativeConstant("profile_file", f_profile_file)
        self._validateRelativeConstant("asset_root", f_asset_root)
        self._validateRelativeConstant("worker_executable", f_worker_executable)
        self._validateRelativeConstant("version_file", f_version_file)

        object.__setattr__(self, "m_package_root", str(f_package_root).strip())
        object.__setattr__(self, "m_profile_file", str(f_profile_file).strip())
        object.__setattr__(self, "m_asset_root", str(f_asset_root).strip())
        object.__setattr__(self, "m_worker_executable", str(f_worker_executable).strip())
        object.__setattr__(self, "m_version_file", str(f_version_file).strip())
        object.__setattr__(self, "_frozen", True)

    @staticmethod
    def _validateRelativeConstant(f_name: str, f_value: Any) -> None:
        if not isinstance(f_value, str) or not f_value.strip():
            raise LayoutConfigurationError(
                f"Install relative layout field '{f_name}' must be a non-empty string, got: {f_value!r}"
            )
        if "\0" in f_value:
            raise LayoutConfigurationError(
                f"Install relative layout field '{f_name}' contains NUL byte: {f_value!r}"
            )
        f_stripped = f_value.strip()
        if os.path.isabs(f_stripped) or f_stripped.startswith("/") or f_stripped.startswith("\\"):
            raise LayoutConfigurationError(
                f"Install relative layout field '{f_name}' must be a relative path, got absolute path: {f_value!r}"
            )

    def __setattr__(self, f_name: str, f_value: Any) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"InstallRelativeLayout is immutable; cannot set attribute '{f_name}'")
        super().__setattr__(f_name, f_value)

    def __delattr__(self, f_name: str) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"InstallRelativeLayout is immutable; cannot delete attribute '{f_name}'")
        super().__delattr__(f_name)

    @property
    def package_root(self) -> str:
        return self.m_package_root

    @property
    def packageRoot(self) -> str:
        return self.m_package_root

    @property
    def profile_file(self) -> str:
        return self.m_profile_file

    @property
    def profileFile(self) -> str:
        return self.m_profile_file

    @property
    def asset_root(self) -> str:
        return self.m_asset_root

    @property
    def assetRoot(self) -> str:
        return self.m_asset_root

    @property
    def worker_executable(self) -> str:
        return self.m_worker_executable

    @property
    def workerExecutable(self) -> str:
        return self.m_worker_executable

    @property
    def version_file(self) -> str:
        return self.m_version_file

    @property
    def versionFile(self) -> str:
        return self.m_version_file

    def toDict(self) -> Dict[str, str]:
        return {
            "package_root": self.m_package_root,
            "profile_file": self.m_profile_file,
            "asset_root": self.m_asset_root,
            "worker_executable": self.m_worker_executable,
            "version_file": self.m_version_file,
        }

    def __eq__(self, f_other: Any) -> bool:
        if not isinstance(f_other, InstallRelativeLayout):
            return False
        return (
            self.m_package_root == f_other.m_package_root
            and self.m_profile_file == f_other.m_profile_file
            and self.m_asset_root == f_other.m_asset_root
            and self.m_worker_executable == f_other.m_worker_executable
            and self.m_version_file == f_other.m_version_file
        )

    def __repr__(self) -> str:
        return (
            f"InstallRelativeLayout("
            f"package_root={self.m_package_root!r}, "
            f"profile_file={self.m_profile_file!r}, "
            f"asset_root={self.m_asset_root!r}, "
            f"worker_executable={self.m_worker_executable!r}, "
            f"version_file={self.m_version_file!r})"
        )

    def __hash__(self) -> int:
        return hash((
            self.m_package_root,
            self.m_profile_file,
            self.m_asset_root,
            self.m_worker_executable,
            self.m_version_file,
        ))


class RuntimeLayout:
    """Immutable runtime layout specifying canonical absolute paths for all system assets."""

    __slots__ = (
        "m_execution_mode",
        "m_package_root",
        "m_profile_file",
        "m_asset_root",
        "m_worker_executable",
        "m_version_file",
        "_frozen",
    )

    def __init__(
        self,
        f_execution_mode: ExecutionMode,
        f_package_root: str,
        f_profile_file: str,
        f_asset_root: str,
        f_worker_executable: str,
        f_version_file: str,
    ) -> None:
        if not isinstance(f_execution_mode, ExecutionMode):
            raise LayoutConfigurationError(
                f"Execution mode must be an ExecutionMode enum, got: {f_execution_mode!r}"
            )
        self._validateAbsolutePath("package_root", f_package_root)
        self._validateAbsolutePath("profile_file", f_profile_file)
        self._validateAbsolutePath("asset_root", f_asset_root)
        self._validateAbsolutePath("worker_executable", f_worker_executable)
        self._validateAbsolutePath("version_file", f_version_file)

        object.__setattr__(self, "m_execution_mode", f_execution_mode)
        object.__setattr__(self, "m_package_root", os.path.normpath(str(f_package_root).strip()))
        object.__setattr__(self, "m_profile_file", os.path.normpath(str(f_profile_file).strip()))
        object.__setattr__(self, "m_asset_root", os.path.normpath(str(f_asset_root).strip()))
        object.__setattr__(self, "m_worker_executable", os.path.normpath(str(f_worker_executable).strip()))
        object.__setattr__(self, "m_version_file", os.path.normpath(str(f_version_file).strip()))
        object.__setattr__(self, "_frozen", True)

    @staticmethod
    def _validateAbsolutePath(f_name: str, f_value: Any) -> None:
        if not isinstance(f_value, str) or not f_value.strip():
            raise LayoutConfigurationError(
                f"Runtime layout field '{f_name}' must be a non-empty string, got: {f_value!r}"
            )
        if "\0" in f_value:
            raise LayoutConfigurationError(
                f"Runtime layout field '{f_name}' contains NUL byte: {f_value!r}"
            )
        f_stripped = f_value.strip()
        if not os.path.isabs(f_stripped):
            raise LayoutConfigurationError(
                f"Runtime layout field '{f_name}' must be an absolute path, got: {f_value!r}"
            )

    def __setattr__(self, f_name: str, f_value: Any) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"RuntimeLayout is immutable; cannot set attribute '{f_name}'")
        super().__setattr__(f_name, f_value)

    def __delattr__(self, f_name: str) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"RuntimeLayout is immutable; cannot delete attribute '{f_name}'")
        super().__delattr__(f_name)

    @property
    def execution_mode(self) -> ExecutionMode:
        return self.m_execution_mode

    @property
    def executionMode(self) -> ExecutionMode:
        return self.m_execution_mode

    @property
    def is_source(self) -> bool:
        return self.m_execution_mode == ExecutionMode.SOURCE

    @property
    def isSource(self) -> bool:
        return self.is_source

    @property
    def is_installed(self) -> bool:
        return self.m_execution_mode == ExecutionMode.INSTALLED

    @property
    def isInstalled(self) -> bool:
        return self.is_installed

    @property
    def package_root(self) -> str:
        return self.m_package_root

    @property
    def packageRoot(self) -> str:
        return self.m_package_root

    @property
    def profile_file(self) -> str:
        return self.m_profile_file

    @property
    def profileFile(self) -> str:
        return self.m_profile_file

    @property
    def asset_root(self) -> str:
        return self.m_asset_root

    @property
    def assetRoot(self) -> str:
        return self.m_asset_root

    @property
    def worker_executable(self) -> str:
        return self.m_worker_executable

    @property
    def workerExecutable(self) -> str:
        return self.m_worker_executable

    @property
    def version_file(self) -> str:
        return self.m_version_file

    @property
    def versionFile(self) -> str:
        return self.m_version_file

    def toDict(self) -> Dict[str, Any]:
        return {
            "execution_mode": self.m_execution_mode.value,
            "package_root": self.m_package_root,
            "profile_file": self.m_profile_file,
            "asset_root": self.m_asset_root,
            "worker_executable": self.m_worker_executable,
            "version_file": self.m_version_file,
        }

    def __eq__(self, f_other: Any) -> bool:
        if not isinstance(f_other, RuntimeLayout):
            return False
        return (
            self.m_execution_mode == f_other.m_execution_mode
            and self.m_package_root == f_other.m_package_root
            and self.m_profile_file == f_other.m_profile_file
            and self.m_asset_root == f_other.m_asset_root
            and self.m_worker_executable == f_other.m_worker_executable
            and self.m_version_file == f_other.m_version_file
        )

    def __repr__(self) -> str:
        return (
            f"RuntimeLayout("
            f"execution_mode={self.m_execution_mode!r}, "
            f"package_root={self.m_package_root!r}, "
            f"profile_file={self.m_profile_file!r}, "
            f"asset_root={self.m_asset_root!r}, "
            f"worker_executable={self.m_worker_executable!r}, "
            f"version_file={self.m_version_file!r})"
        )

    def __hash__(self) -> int:
        return hash((
            self.m_execution_mode,
            self.m_package_root,
            self.m_profile_file,
            self.m_asset_root,
            self.m_worker_executable,
            self.m_version_file,
        ))


class ResourceLocator:
    """Pure lexical path constructor for source and installed runtime layouts.

    CRITICAL INVARIANT:
    Never performs filesystem calls (exists, stat, lstat, is_file, is_dir, is_symlink, access, open, resolve).
    Constructs normalized absolute paths and validates lexical containment without searching cwd/HOME/PATH
    or falling back between modes.
    """

    @classmethod
    def forSource(cls, f_source_entry: str) -> RuntimeLayout:
        """Derive RuntimeLayout anchored to a source entry path."""
        if not isinstance(f_source_entry, str) or not f_source_entry.strip():
            raise LayoutConfigurationError(
                f"Source entry must be a non-empty string, got: {f_source_entry!r}"
            )
        if "\0" in f_source_entry:
            raise LayoutConfigurationError(
                f"Source entry contains NUL byte: {f_source_entry!r}"
            )

        f_entry_str = f_source_entry.strip()
        f_norm_entry = os.path.normpath(
            f_entry_str if os.path.isabs(f_entry_str) else os.path.abspath(f_entry_str)
        )

        # Lexically determine repo_root and package_root
        f_parts = [p for p in f_norm_entry.split(os.sep) if p]

        # Check if 'tools' and 'lsmiotool' are contiguous parts
        f_tools_idx = -1
        for f_i in range(len(f_parts) - 1):
            if f_parts[f_i] == "tools" and f_parts[f_i + 1] == "lsmiotool":
                f_tools_idx = f_i
                break

        if f_tools_idx >= 0:
            # Everything before 'tools' is repo_root
            f_repo_parts = f_parts[:f_tools_idx]
            f_repo_root = "/" + "/".join(f_repo_parts) if f_repo_parts else "/"
            f_package_root = os.path.normpath(os.path.join(f_repo_root, "tools", "lsmiotool"))
        else:
            # If not explicitly in tools/lsmiotool, derive from entry path
            if len(f_parts) >= 2 and f_parts[-2] == "lib":
                f_package_root = "/" + "/".join(f_parts[:-2])
            elif len(f_parts) >= 1 and (f_parts[-1] in ("lsmiotool", "lsmiotool-worker") or "." in f_parts[-1]):
                f_package_root = "/" + "/".join(f_parts[:-1]) if len(f_parts) > 1 else "/"
            else:
                f_package_root = f_norm_entry

            f_pkg_parts = [p for p in f_package_root.split(os.sep) if p]
            if len(f_pkg_parts) >= 2 and f_pkg_parts[-2] == "tools" and f_pkg_parts[-1] == "lsmiotool":
                f_repo_root = "/" + "/".join(f_pkg_parts[:-2]) if len(f_pkg_parts) > 2 else "/"
            else:
                f_repo_root = "/" + "/".join(f_pkg_parts[:-1]) if len(f_pkg_parts) > 1 else "/"

        f_profile_file = os.path.normpath(os.path.join(f_package_root, "etc", "environments.json"))
        f_asset_root = os.path.normpath(os.path.join(f_repo_root, "tools", "bmtool", "lmp-reaxff"))
        f_worker_executable = os.path.normpath(os.path.join(f_package_root, "lsmiotool-worker"))
        f_version_file = os.path.normpath(os.path.join(f_repo_root, "VERSION"))

        return RuntimeLayout(
            f_execution_mode=ExecutionMode.SOURCE,
            f_package_root=f_package_root,
            f_profile_file=f_profile_file,
            f_asset_root=f_asset_root,
            f_worker_executable=f_worker_executable,
            f_version_file=f_version_file,
        )

    @classmethod
    def forInstalled(
        cls,
        f_installed_entry: str,
        f_relative_layout: InstallRelativeLayout,
    ) -> RuntimeLayout:
        """Derive RuntimeLayout anchored to an installed wrapper executable and relative layout."""
        if not isinstance(f_installed_entry, str) or not f_installed_entry.strip():
            raise LayoutConfigurationError(
                f"Installed entry must be a non-empty string, got: {f_installed_entry!r}"
            )
        if "\0" in f_installed_entry:
            raise LayoutConfigurationError(
                f"Installed entry contains NUL byte: {f_installed_entry!r}"
            )
        if not isinstance(f_relative_layout, InstallRelativeLayout):
            raise LayoutConfigurationError(
                f"Relative layout must be an InstallRelativeLayout instance, got: {f_relative_layout!r}"
            )

        f_entry_str = f_installed_entry.strip()
        f_norm_entry = os.path.normpath(
            f_entry_str if os.path.isabs(f_entry_str) else os.path.abspath(f_entry_str)
        )
        f_anchor_dir = os.path.dirname(f_norm_entry)

        f_package_root = cls._resolveRelativePath(f_anchor_dir, f_relative_layout.package_root, "package_root")
        f_profile_file = cls._resolveRelativePath(f_anchor_dir, f_relative_layout.profile_file, "profile_file")
        f_asset_root = cls._resolveRelativePath(f_anchor_dir, f_relative_layout.asset_root, "asset_root")
        f_worker_executable = cls._resolveRelativePath(
            f_anchor_dir, f_relative_layout.worker_executable, "worker_executable"
        )
        f_version_file = cls._resolveRelativePath(f_anchor_dir, f_relative_layout.version_file, "version_file")

        return RuntimeLayout(
            f_execution_mode=ExecutionMode.INSTALLED,
            f_package_root=f_package_root,
            f_profile_file=f_profile_file,
            f_asset_root=f_asset_root,
            f_worker_executable=f_worker_executable,
            f_version_file=f_version_file,
        )

    @classmethod
    def _resolveRelativePath(cls, f_anchor_dir: str, f_rel_path: str, f_field_name: str) -> str:
        """Resolve and lexically validate that a relative path does not escape the filesystem root."""
        if not isinstance(f_rel_path, str) or not f_rel_path.strip():
            raise LayoutConfigurationError(
                f"Relative path for '{f_field_name}' must be a non-empty string, got: {f_rel_path!r}"
            )
        if "\0" in f_rel_path:
            raise LayoutConfigurationError(
                f"Relative path for '{f_field_name}' contains NUL byte: {f_rel_path!r}"
            )

        f_stripped = f_rel_path.strip()
        if os.path.isabs(f_stripped) or f_stripped.startswith("/") or f_stripped.startswith("\\"):
            raise LayoutConfigurationError(
                f"Relative path for '{f_field_name}' must not be absolute: {f_rel_path!r}"
            )

        f_anchor_parts = [p for p in f_anchor_dir.split(os.sep) if p]
        f_cur_parts = list(f_anchor_parts)

        # Normalize forward/backward slashes
        f_tokens = f_stripped.replace("\\", "/").split("/")
        for f_token in f_tokens:
            if not f_token or f_token == ".":
                continue
            elif f_token == "..":
                if not f_cur_parts:
                    raise LayoutConfigurationError(
                        f"Relative path '{f_rel_path}' for '{f_field_name}' escapes filesystem root from anchor '{f_anchor_dir}'"
                    )
                f_cur_parts.pop()
            else:
                f_cur_parts.append(f_token)

        f_resolved = "/" + "/".join(f_cur_parts) if f_cur_parts else "/"
        return os.path.normpath(f_resolved)
