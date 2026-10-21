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

from abc import ABC, abstractmethod
from enum import Enum
import errno
import hashlib
import os
import re
import stat
import string
import sys
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)

from lsmiotool.lib.variants import VariantCatalogue


class CapabilityState(Enum):
    """Capability verification state for a benchmark executable."""

    CONFIGURED = "configured"
    VERIFIED = "verified"
    UNSUPPORTED = "unsupported"

    @property
    def is_verified(self) -> bool:
        return self == CapabilityState.VERIFIED

    @property
    def is_configured(self) -> bool:
        return self == CapabilityState.CONFIGURED

    @property
    def is_unsupported(self) -> bool:
        return self == CapabilityState.UNSUPPORTED


# Alias ProbeState for compatibility
ProbeState = CapabilityState


class BenchmarkError(Exception):
    """Base exception for all benchmark adapter operations."""

    pass


class BenchmarkConfigurationError(BenchmarkError):
    """Raised when benchmark configuration, setup, or parameters are invalid."""

    pass


class BenchmarkProbeError(BenchmarkError):
    """Raised when capability probing encounters an error or unsupported capability."""

    pass


class BenchmarkCommand:
    """Immutable container representing a prepared benchmark execution command."""

    __slots__ = (
        "m_argv",
        "m_stdout_path",
        "m_stderr_path",
        "m_working_dir",
        "m_is_rank_local",
        "_frozen",
    )

    def __init__(
        self,
        f_argv: Sequence[str],
        f_stdout_path: str,
        f_stderr_path: str,
        f_working_dir: str,
        f_is_rank_local: bool = False,
    ) -> None:
        if not f_argv:
            raise BenchmarkConfigurationError(
                "BenchmarkCommand argv sequence must not be empty"
            )

        f_clean_argv: List[str] = []
        for f_idx, f_arg in enumerate(f_argv):
            if not isinstance(f_arg, str):
                raise BenchmarkConfigurationError(
                    f"BenchmarkCommand argv[{f_idx}] must be a string, got: {type(f_arg).__name__}"
                )
            if "\0" in f_arg:
                raise BenchmarkConfigurationError(
                    f"BenchmarkCommand argv[{f_idx}] contains NUL byte: {f_arg!r}"
                )
            f_clean_argv.append(f_arg)

        if not isinstance(f_stdout_path, str) or not f_stdout_path.strip():
            raise BenchmarkConfigurationError(
                f"BenchmarkCommand stdout_path must be a non-empty string, got: {f_stdout_path!r}"
            )
        if "\0" in f_stdout_path:
            raise BenchmarkConfigurationError(
                f"BenchmarkCommand stdout_path contains NUL byte: {f_stdout_path!r}"
            )

        if not isinstance(f_stderr_path, str) or not f_stderr_path.strip():
            raise BenchmarkConfigurationError(
                f"BenchmarkCommand stderr_path must be a non-empty string, got: {f_stderr_path!r}"
            )
        if "\0" in f_stderr_path:
            raise BenchmarkConfigurationError(
                f"BenchmarkCommand stderr_path contains NUL byte: {f_stderr_path!r}"
            )

        if not isinstance(f_working_dir, str) or not f_working_dir.strip():
            raise BenchmarkConfigurationError(
                f"BenchmarkCommand working_dir must be a non-empty string, got: {f_working_dir!r}"
            )
        if "\0" in f_working_dir:
            raise BenchmarkConfigurationError(
                f"BenchmarkCommand working_dir contains NUL byte: {f_working_dir!r}"
            )

        if not isinstance(f_is_rank_local, bool):
            raise BenchmarkConfigurationError(
                f"BenchmarkCommand is_rank_local must be a boolean, got: {f_is_rank_local!r}"
            )

        super().__setattr__("m_argv", tuple(f_clean_argv))
        super().__setattr__("m_stdout_path", os.path.normpath(f_stdout_path.strip()))
        super().__setattr__("m_stderr_path", os.path.normpath(f_stderr_path.strip()))
        super().__setattr__("m_working_dir", os.path.normpath(f_working_dir.strip()))
        super().__setattr__("m_is_rank_local", f_is_rank_local)
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
    def argv(self) -> Tuple[str, ...]:
        return self.m_argv

    @property
    def arguments(self) -> Tuple[str, ...]:
        return self.m_argv

    @property
    def stdout_path(self) -> str:
        return self.m_stdout_path

    @property
    def stdoutPath(self) -> str:
        return self.m_stdout_path

    @property
    def stderr_path(self) -> str:
        return self.m_stderr_path

    @property
    def stderrPath(self) -> str:
        return self.m_stderr_path

    @property
    def working_dir(self) -> str:
        return self.m_working_dir

    @property
    def workingDir(self) -> str:
        return self.m_working_dir

    @property
    def is_rank_local(self) -> bool:
        return self.m_is_rank_local

    @property
    def isRankLocal(self) -> bool:
        return self.m_is_rank_local

    def toDict(self) -> Dict[str, Any]:
        return {
            "argv": list(self.m_argv),
            "stdout_path": self.m_stdout_path,
            "stderr_path": self.m_stderr_path,
            "working_dir": self.m_working_dir,
            "is_rank_local": self.m_is_rank_local,
        }

    def __repr__(self) -> str:
        return (
            f"BenchmarkCommand("
            f"argv={self.m_argv!r}, "
            f"stdout_path={self.m_stdout_path!r}, "
            f"stderr_path={self.m_stderr_path!r}, "
            f"working_dir={self.m_working_dir!r}, "
            f"is_rank_local={self.m_is_rank_local!r})"
        )

    def __eq__(self, f_other: Any) -> bool:
        if not isinstance(f_other, BenchmarkCommand):
            return False
        return (
            self.m_argv == f_other.m_argv
            and self.m_stdout_path == f_other.m_stdout_path
            and self.m_stderr_path == f_other.m_stderr_path
            and self.m_working_dir == f_other.m_working_dir
            and self.m_is_rank_local == f_other.m_is_rank_local
        )

    def __hash__(self) -> int:
        return hash(
            (
                self.m_argv,
                self.m_stdout_path,
                self.m_stderr_path,
                self.m_working_dir,
                self.m_is_rank_local,
            )
        )


class BenchmarkAdapter(ABC):
    """Abstract base class for benchmark command generation and capability probing."""

    @property
    @abstractmethod
    def target(self) -> str:
        """Return canonical target name (e.g. 'ior', 'lsmio', 'lmp')."""
        pass

    @property
    @abstractmethod
    def defaultSetup(self) -> str:
        """Return default setup name for this benchmark."""
        pass

    @property
    @abstractmethod
    def allowedSetups(self) -> Tuple[str, ...]:
        """Return tuple of allowed setup names."""
        pass

    @abstractmethod
    def probeCapability(
        self,
        f_executable: str,
        f_runner: Optional[Callable[..., Any]] = None,
        f_setup: Optional[str] = None,
    ) -> CapabilityState:
        """Probe executable capability, returning CapabilityState or raising BenchmarkProbeError."""
        pass


class IorAdapter(BenchmarkAdapter):
    """Adapter for constructing exact IOR shared benchmark commands and probing IOR capabilities."""

    TARGET: str = "ior"
    DEFAULT_SETUP: str = "BASE"
    ALLOWED_SETUPS: Tuple[str, ...] = (
        "BASE",
        "HDF5",
        "HDF5-C",
        "COLLECTIVE",
        "FSYNC",
        "REVERSE",
    )

    SEGMENT_MAP: Dict[str, int] = {
        "64K": 16384,
        "1M": 1024,
        "8M": 128,
    }

    SETUP_EXTRA_FLAGS: Dict[str, Tuple[str, ...]] = {
        "BASE": (),
        "HDF5": ("-a", "HDF5"),
        "HDF5-C": ("-c", "-a", "HDF5"),
        "COLLECTIVE": ("-c", "-a", "MPIIO"),
        "FSYNC": ("-e",),
        "REVERSE": ("-C",),
    }

    BASE_FLAGS: Tuple[str, ...] = ("-v", "-w", "-r", "-i=10")

    RANK_PLACEHOLDERS: Tuple[str, ...] = (
        "{rank}",
        "{global_rank}",
        "{local_rank}",
        "%r",
        "@RANK@",
    )

    @property
    def target(self) -> str:
        return self.TARGET

    @property
    def defaultSetup(self) -> str:
        return self.DEFAULT_SETUP

    @property
    def allowedSetups(self) -> Tuple[str, ...]:
        return self.ALLOWED_SETUPS

    @classmethod
    def getSegments(cls, f_block_size: str) -> int:
        """Return segment count for a given block size."""
        if not isinstance(f_block_size, str):
            raise BenchmarkConfigurationError(
                f"Block size must be a string, got: {type(f_block_size).__name__}"
            )
        f_norm_size = f_block_size.strip().upper()
        if f_norm_size not in cls.SEGMENT_MAP:
            raise BenchmarkConfigurationError(
                f"Unsupported IOR block size: {f_block_size!r}. Allowed: {list(cls.SEGMENT_MAP.keys())}"
            )
        return cls.SEGMENT_MAP[f_norm_size]

    def buildCommand(
        self,
        f_executable: str,
        f_setup: str = "BASE",
        f_block_size: Optional[str] = None,
        f_working_dir: str = "/tmp",
        f_output_path: Optional[str] = None,
        f_stdout_path: Optional[str] = None,
        f_stderr_path: Optional[str] = None,
        f_combination: Optional[Any] = None,
        f_stripe_count: Optional[int] = None,
    ) -> BenchmarkCommand:
        """Construct exact BenchmarkCommand for an IOR run."""
        if not isinstance(f_executable, str) or not f_executable.strip():
            raise BenchmarkConfigurationError(
                f"Executable must be a non-empty string, got: {f_executable!r}"
            )
        if "\0" in f_executable:
            raise BenchmarkConfigurationError(
                f"Executable contains NUL byte: {f_executable!r}"
            )

        f_norm_executable = f_executable.strip()

        if not isinstance(f_setup, str) or not f_setup.strip():
            raise BenchmarkConfigurationError(
                f"Setup must be a non-empty string, got: {f_setup!r}"
            )
        f_norm_setup = f_setup.strip().upper()
        if f_norm_setup not in self.ALLOWED_SETUPS:
            raise BenchmarkConfigurationError(
                f"Unknown IOR setup: {f_setup!r}. Allowed setups: {self.ALLOWED_SETUPS}"
            )

        # Resolve block size
        f_resolved_block_size: Optional[str] = None
        if f_block_size is not None:
            if not isinstance(f_block_size, str) or not f_block_size.strip():
                raise BenchmarkConfigurationError(
                    f"Block size must be a non-empty string, got: {f_block_size!r}"
                )
            f_resolved_block_size = f_block_size.strip().upper()
        elif f_combination is not None:
            if hasattr(f_combination, "block_size"):
                f_resolved_block_size = str(f_combination.block_size).strip().upper()
            elif isinstance(f_combination, str):
                f_combo_str = f_combination.strip()
                if "_b" in f_combo_str:
                    f_resolved_block_size = (
                        f_combo_str.split("_b", 1)[1].strip().upper()
                    )
                else:
                    f_resolved_block_size = f_combo_str.upper()
            elif isinstance(f_combination, (tuple, list)) and len(f_combination) >= 2:
                f_resolved_block_size = str(f_combination[1]).strip().upper()

        if f_resolved_block_size is None:
            raise BenchmarkConfigurationError(
                "Block size must be specified directly or via combination"
            )

        if f_resolved_block_size not in self.SEGMENT_MAP:
            raise BenchmarkConfigurationError(
                f"Unsupported IOR block size: {f_resolved_block_size!r}. Allowed: {list(self.SEGMENT_MAP.keys())}"
            )

        f_segments = self.SEGMENT_MAP[f_resolved_block_size]

        if not isinstance(f_working_dir, str) or not f_working_dir.strip():
            raise BenchmarkConfigurationError(
                f"Working directory must be a non-empty string, got: {f_working_dir!r}"
            )
        if "\0" in f_working_dir:
            raise BenchmarkConfigurationError(
                f"Working directory contains NUL byte: {f_working_dir!r}"
            )
        f_norm_working_dir = os.path.normpath(f_working_dir.strip())

        # Resolve output path
        if f_output_path is not None:
            if not isinstance(f_output_path, str) or not f_output_path.strip():
                raise BenchmarkConfigurationError(
                    f"Output path must be a non-empty string, got: {f_output_path!r}"
                )
            if "\0" in f_output_path:
                raise BenchmarkConfigurationError(
                    f"Output path contains NUL byte: {f_output_path!r}"
                )
            f_outpath = os.path.normpath(f_output_path.strip())
        else:
            f_outpath = os.path.join(f_norm_working_dir, f"ior.{f_norm_setup.lower()}")

        # Resolve stdout and stderr paths
        if f_stdout_path is not None:
            if not isinstance(f_stdout_path, str) or not f_stdout_path.strip():
                raise BenchmarkConfigurationError(
                    f"Stdout path must be a non-empty string, got: {f_stdout_path!r}"
                )
            if "\0" in f_stdout_path:
                raise BenchmarkConfigurationError(
                    f"Stdout path contains NUL byte: {f_stdout_path!r}"
                )
            f_norm_stdout = os.path.normpath(f_stdout_path.strip())
        else:
            f_norm_stdout = os.path.join(
                f_norm_working_dir, f"ior.{f_norm_setup.lower()}.stdout.log"
            )

        if f_stderr_path is not None:
            if not isinstance(f_stderr_path, str) or not f_stderr_path.strip():
                raise BenchmarkConfigurationError(
                    f"Stderr path must be a non-empty string, got: {f_stderr_path!r}"
                )
            if "\0" in f_stderr_path:
                raise BenchmarkConfigurationError(
                    f"Stderr path contains NUL byte: {f_stderr_path!r}"
                )
            f_norm_stderr = os.path.normpath(f_stderr_path.strip())
        else:
            f_norm_stderr = os.path.join(
                f_norm_working_dir, f"ior.{f_norm_setup.lower()}.stderr.log"
            )

        # Validate that no rank placeholders are present in paths or executable
        for f_check_str, f_desc in (
            (f_norm_executable, "executable"),
            (f_outpath, "output path"),
            (f_norm_stdout, "stdout path"),
            (f_norm_stderr, "stderr path"),
            (f_norm_working_dir, "working directory"),
        ):
            for f_ph in self.RANK_PLACEHOLDERS:
                if f_ph in f_check_str:
                    raise BenchmarkConfigurationError(
                        f"IOR command {f_desc} contains rank placeholder {f_ph!r}: {f_check_str!r}"
                    )

        # Assemble argv sequence in exact upstream order:
        # ior -v -w -r -i=10 [extra_flags] -o <outpath> -t=<bs> -b=<bs> -s=<sg>
        f_extra_flags = self.SETUP_EXTRA_FLAGS[f_norm_setup]
        f_argv_list: List[str] = [
            f_norm_executable,
            *self.BASE_FLAGS,
            *f_extra_flags,
            "-o",
            f_outpath,
            f"-t={f_resolved_block_size}",
            f"-b={f_resolved_block_size}",
            f"-s={f_segments}",
        ]

        return BenchmarkCommand(
            f_argv=f_argv_list,
            f_stdout_path=f_norm_stdout,
            f_stderr_path=f_norm_stderr,
            f_working_dir=f_norm_working_dir,
            f_is_rank_local=False,
        )

    # Convenience aliases
    buildBenchmarkCommand = buildCommand
    createCommand = buildCommand
    build_command = buildCommand

    def probeCapability(
        self,
        f_executable: str,
        f_runner: Optional[Callable[..., Any]] = None,
        f_setup: Optional[str] = None,
    ) -> CapabilityState:
        """Probe IOR capability using an injected runner or report configured/unverified."""
        if not isinstance(f_executable, str) or not f_executable.strip():
            raise BenchmarkConfigurationError(
                f"Executable must be a non-empty string, got: {f_executable!r}"
            )
        if "\0" in f_executable:
            raise BenchmarkConfigurationError(
                f"Executable contains NUL byte: {f_executable!r}"
            )

        f_norm_executable = f_executable.strip()

        if f_setup is not None:
            f_norm_setup = f_setup.strip().upper()
            if f_norm_setup not in self.ALLOWED_SETUPS:
                raise BenchmarkProbeError(
                    f"Unsupported IOR setup requested: {f_setup!r}. Allowed: {self.ALLOWED_SETUPS}"
                )

        if f_runner is None:
            # When no live runner is injected, record target as configured/unverified without inventing version
            return CapabilityState.CONFIGURED

        f_probe_argv = [f_norm_executable, "-v"]

        try:
            if hasattr(f_runner, "run") and callable(getattr(f_runner, "run")):
                f_result = f_runner.run(f_probe_argv)
            else:
                f_result = f_runner(f_probe_argv)
        except (FileNotFoundError, PermissionError, OSError) as f_exc:
            raise BenchmarkProbeError(
                f"IOR executable probe failed for {f_norm_executable!r}: {f_exc}"
            ) from f_exc
        except Exception as f_exc:
            raise BenchmarkProbeError(
                f"IOR probe runner raised unexpected error for {f_norm_executable!r}: {f_exc}"
            ) from f_exc

        # Inspect runner result
        f_exit_code: int = 0
        f_output_text: str = ""

        if hasattr(f_result, "returncode"):
            f_exit_code = int(f_result.returncode)
            f_stdout = getattr(f_result, "stdout", "") or ""
            f_stderr = getattr(f_result, "stderr", "") or ""
            f_output_text = f"{f_stdout}\n{f_stderr}"
        elif hasattr(f_result, "exit_code"):
            f_exit_code = int(f_result.exit_code)
            f_stdout = getattr(f_result, "stdout", "") or ""
            f_stderr = getattr(f_result, "stderr", "") or ""
            f_output_text = f"{f_stdout}\n{f_stderr}"
        elif isinstance(f_result, tuple) and len(f_result) >= 2:
            f_exit_code = int(f_result[0])
            f_output_text = str(f_result[1])
            if len(f_result) >= 3:
                f_output_text += f"\n{f_result[2]}"
        elif isinstance(f_result, int):
            f_exit_code = f_result
            f_output_text = ""
        elif isinstance(f_result, str):
            f_exit_code = 0
            f_output_text = f_result
        else:
            f_output_text = str(f_result)

        if f_exit_code != 0:
            raise BenchmarkProbeError(
                f"IOR executable {f_norm_executable!r} probe failed with exit code {f_exit_code}: {f_output_text.strip()}"
            )

        f_lower_out = f_output_text.lower()
        if (
            "unsupported" in f_lower_out
            or "invalid option" in f_lower_out
            or "command not found" in f_lower_out
        ):
            raise BenchmarkProbeError(
                f"IOR executable {f_norm_executable!r} reported unsupported capability: {f_output_text.strip()}"
            )

        if not f_output_text.strip():
            raise BenchmarkProbeError(
                f"IOR executable {f_norm_executable!r} produced empty probe output"
            )

        # Check for IOR signature or version pattern
        f_ior_match = re.search(
            r"IOR[- ](\d+\.\d+(?:\.\d+)?(?:[a-zA-Z0-9_.-]*)?)",
            f_output_text,
            re.IGNORECASE,
        )
        if f_ior_match or "ior" in f_lower_out or "version" in f_lower_out:
            return CapabilityState.VERIFIED

        raise BenchmarkProbeError(
            f"IOR executable {f_norm_executable!r} produced unrecognized probe output: {f_output_text.strip()}"
        )


class LsmioLaunchSpec:
    """Immutable container representing an unbound launch template specification for LSMIO benchmark."""

    __slots__ = (
        "m_request",
        "m_combination",
        "m_point",
        "m_setup",
        "m_executable",
        "m_variant",
        "m_is_rank_local",
        "m_is_bound",
        "_frozen",
    )

    def __init__(
        self,
        f_request: Any,
        f_combination: Any,
        f_point: Any,
        f_setup: str,
        f_executable: str,
        f_variant: Optional[str] = None,
        f_is_rank_local: bool = True,
        f_is_bound: bool = False,
    ) -> None:
        if not isinstance(f_setup, str) or not f_setup.strip():
            raise BenchmarkConfigurationError(
                f"LsmioLaunchSpec setup must be a non-empty string, got: {f_setup!r}"
            )
        if "\0" in f_setup:
            raise BenchmarkConfigurationError(
                f"LsmioLaunchSpec setup contains NUL byte: {f_setup!r}"
            )
        if not isinstance(f_executable, str) or not f_executable.strip():
            raise BenchmarkConfigurationError(
                f"LsmioLaunchSpec executable must be a non-empty string, got: {f_executable!r}"
            )
        if "\0" in f_executable:
            raise BenchmarkConfigurationError(
                f"LsmioLaunchSpec executable contains NUL byte: {f_executable!r}"
            )
        if f_variant is not None and (
            not isinstance(f_variant, str) or not f_variant.strip()
        ):
            raise BenchmarkConfigurationError(
                f"LsmioLaunchSpec variant must be a non-empty string or None, got: {f_variant!r}"
            )
        if f_variant is not None and "\0" in f_variant:
            raise BenchmarkConfigurationError(
                f"LsmioLaunchSpec variant contains NUL byte: {f_variant!r}"
            )
        if not isinstance(f_is_rank_local, bool):
            raise BenchmarkConfigurationError(
                f"LsmioLaunchSpec is_rank_local must be a boolean, got: {f_is_rank_local!r}"
            )
        if not isinstance(f_is_bound, bool):
            raise BenchmarkConfigurationError(
                f"LsmioLaunchSpec is_bound must be a boolean, got: {f_is_bound!r}"
            )

        super().__setattr__("m_request", f_request)
        super().__setattr__("m_combination", f_combination)
        super().__setattr__("m_point", f_point)
        super().__setattr__("m_setup", f_setup.strip().upper())
        super().__setattr__("m_executable", os.path.normpath(f_executable.strip()))
        super().__setattr__(
            "m_variant", f_variant.strip().lower() if f_variant else None
        )
        super().__setattr__("m_is_rank_local", f_is_rank_local)
        super().__setattr__("m_is_bound", f_is_bound)
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
    def request(self) -> Any:
        return self.m_request

    @property
    def combination(self) -> Any:
        return self.m_combination

    @property
    def point(self) -> Any:
        return self.m_point

    @property
    def setup(self) -> str:
        return self.m_setup

    @property
    def executable(self) -> str:
        return self.m_executable

    @property
    def variant(self) -> Optional[str]:
        return self.m_variant

    @property
    def is_rank_local(self) -> bool:
        return self.m_is_rank_local

    @property
    def isRankLocal(self) -> bool:
        return self.m_is_rank_local

    @property
    def is_bound(self) -> bool:
        return self.m_is_bound

    @property
    def isBound(self) -> bool:
        return self.m_is_bound

    @property
    def expected_results(self) -> Tuple[str, ...]:
        return ()

    @property
    def mode(self) -> str:
        return "direct"

    @property
    def executable_or_worker(self) -> str:
        return self.m_executable

    @property
    def arguments(self) -> Tuple[str, ...]:
        return ()

    def toDict(self) -> Dict[str, Any]:
        f_dict: Dict[str, Any] = {
            "target": "lsmio",
            "setup": self.m_setup,
            "executable": self.m_executable,
            "combination": (
                self.m_combination.toDict()
                if hasattr(self.m_combination, "toDict")
                else str(self.m_combination)
            ),
            "point": (
                self.m_point.toDict()
                if hasattr(self.m_point, "toDict")
                else str(self.m_point)
            ),
            "is_rank_local": self.m_is_rank_local,
            "is_bound": self.m_is_bound,
        }
        if self.m_variant is not None:
            f_dict["variant"] = self.m_variant
        return f_dict

    def __repr__(self) -> str:
        return (
            f"LsmioLaunchSpec("
            f"setup={self.m_setup!r}, "
            f"executable={self.m_executable!r}, "
            f"combination={self.m_combination!r}, "
            f"point={self.m_point!r}, "
            f"variant={self.m_variant!r}, "
            f"is_rank_local={self.m_is_rank_local!r}, "
            f"is_bound={self.m_is_bound!r})"
        )

    def __eq__(self, f_other: Any) -> bool:
        if not isinstance(f_other, LsmioLaunchSpec):
            return False
        return (
            self.m_setup == f_other.m_setup
            and self.m_executable == f_other.m_executable
            and self.m_combination == f_other.m_combination
            and self.m_point == f_other.m_point
            and self.m_variant == f_other.m_variant
            and self.m_is_rank_local == f_other.m_is_rank_local
            and self.m_is_bound == f_other.m_is_bound
        )

    def __hash__(self) -> int:
        f_combo_key = (
            (self.m_combination.stripe_count, self.m_combination.block_size)
            if hasattr(self.m_combination, "stripe_count")
            and hasattr(self.m_combination, "block_size")
            else str(self.m_combination)
        )
        f_point_key = (
            (self.m_point.tasks, self.m_point.ppn, self.m_point.nodes)
            if hasattr(self.m_point, "tasks")
            and hasattr(self.m_point, "ppn")
            and hasattr(self.m_point, "nodes")
            else str(self.m_point)
        )
        return hash(
            (
                self.m_setup,
                self.m_executable,
                f_combo_key,
                f_point_key,
                self.m_variant,
                self.m_is_rank_local,
                self.m_is_bound,
            )
        )


class LsmioBoundCommand(BenchmarkCommand):
    """Immutable bound benchmark execution command for a specific rank."""

    __slots__ = (
        "m_result_path",
        "m_output_path",
        "m_identity",
        "m_spec",
    )

    def __init__(
        self,
        f_argv: Sequence[str],
        f_stdout_path: str,
        f_stderr_path: str,
        f_working_dir: str,
        f_is_rank_local: bool = True,
        f_result_path: Optional[str] = None,
        f_output_path: Optional[str] = None,
        f_identity: Optional[Any] = None,
        f_spec: Optional[Any] = None,
    ) -> None:
        super().__init__(
            f_argv=f_argv,
            f_stdout_path=f_stdout_path,
            f_stderr_path=f_stderr_path,
            f_working_dir=f_working_dir,
            f_is_rank_local=f_is_rank_local,
        )

        if f_result_path is not None:
            if not isinstance(f_result_path, str) or not f_result_path.strip():
                raise BenchmarkConfigurationError(
                    f"result_path must be a non-empty string, got: {f_result_path!r}"
                )
            if "\0" in f_result_path:
                raise BenchmarkConfigurationError(
                    f"result_path contains NUL byte: {f_result_path!r}"
                )
            f_norm_result = os.path.normpath(f_result_path.strip())
        else:
            f_norm_result = ""

        if f_output_path is not None:
            if not isinstance(f_output_path, str) or not f_output_path.strip():
                raise BenchmarkConfigurationError(
                    f"output_path must be a non-empty string, got: {f_output_path!r}"
                )
            if "\0" in f_output_path:
                raise BenchmarkConfigurationError(
                    f"output_path contains NUL byte: {f_output_path!r}"
                )
            f_norm_output = os.path.normpath(f_output_path.strip())
        else:
            f_norm_output = ""

        super(BenchmarkCommand, self).__setattr__("m_result_path", f_norm_result)
        super(BenchmarkCommand, self).__setattr__("m_output_path", f_norm_output)
        super(BenchmarkCommand, self).__setattr__("m_identity", f_identity)
        super(BenchmarkCommand, self).__setattr__("m_spec", f_spec)

    @property
    def result_path(self) -> str:
        return self.m_result_path

    @property
    def resultPath(self) -> str:
        return self.m_result_path

    @property
    def output_path(self) -> str:
        return self.m_output_path

    @property
    def outputPath(self) -> str:
        return self.m_output_path

    @property
    def identity(self) -> Optional[Any]:
        return self.m_identity

    @property
    def spec(self) -> Optional[Any]:
        return self.m_spec

    def toDict(self) -> Dict[str, Any]:
        f_base = super().toDict()
        f_base["result_path"] = self.m_result_path
        f_base["output_path"] = self.m_output_path
        if self.m_identity is not None:
            f_base["identity"] = (
                self.m_identity.toDict()
                if hasattr(self.m_identity, "toDict")
                else str(self.m_identity)
            )
        return f_base

    def __repr__(self) -> str:
        return (
            f"LsmioBoundCommand("
            f"argv={self.m_argv!r}, "
            f"stdout_path={self.m_stdout_path!r}, "
            f"stderr_path={self.m_stderr_path!r}, "
            f"working_dir={self.m_working_dir!r}, "
            f"is_rank_local={self.m_is_rank_local!r}, "
            f"result_path={self.m_result_path!r}, "
            f"output_path={self.m_output_path!r})"
        )

    def __eq__(self, f_other: Any) -> bool:
        if not isinstance(f_other, LsmioBoundCommand):
            return False
        return (
            super().__eq__(f_other)
            and self.m_result_path == f_other.m_result_path
            and self.m_output_path == f_other.m_output_path
            and self.m_identity == f_other.m_identity
        )

    def __hash__(self) -> int:
        return hash(
            (
                super().__hash__(),
                self.m_result_path,
                self.m_output_path,
            )
        )


class LsmioAdapter(BenchmarkAdapter):
    """Adapter for constructing pure exact LSMIO late-binding rank commands and probing LSMIO capabilities."""

    TARGET: str = "lsmio"
    DEFAULT_SETUP: str = "NATIVE"
    ALLOWED_SETUPS: Tuple[str, ...] = (
        "NATIVE",
        "ADIOS",
        "PLUGIN",
        "ROCKSDB",
        "LEVELDB",
        "MANAGER",
    )

    # Every setup runs under MPI with barriers around its timed phases
    MPI_FLAGS: Tuple[str, ...] = ("-m", "-g")

    EXECUTABLE_MAP: Dict[str, str] = {
        "NATIVE": "bm_native",
        "ADIOS": "bm_adios",
        "PLUGIN": "bm_adios",
        "ROCKSDB": "bm_rocksdb",
        "LEVELDB": "bm_leveldb",
        "MANAGER": "bm_manager",
    }

    BLOCK_SIZE_MAP: Dict[str, Tuple[int, int]] = {
        "64K": (65536, 32768),
        "1M": (1048576, 4096),
        "8M": (8388608, 1024),
    }

    RANK_PLACEHOLDERS: Tuple[str, ...] = (
        "{rank}",
        "{global_rank}",
        "{local_rank}",
        "%r",
        "@RANK@",
    )

    @property
    def target(self) -> str:
        return self.TARGET

    @property
    def defaultSetup(self) -> str:
        return self.DEFAULT_SETUP

    @property
    def allowedSetups(self) -> Tuple[str, ...]:
        return self.ALLOWED_SETUPS

    @classmethod
    def getExecutableName(cls, f_setup: str) -> str:
        """Return executable basename for the given setup."""
        if not isinstance(f_setup, str) or not f_setup.strip():
            raise BenchmarkConfigurationError(
                f"Setup must be a non-empty string, got: {f_setup!r}"
            )
        f_norm_setup = f_setup.strip().upper()
        if f_norm_setup == "ENV":
            raise BenchmarkConfigurationError(
                "LSMIO setup 'ENV' is a diagnostic mode and cannot be used as a run benchmark setup"
            )
        if f_norm_setup not in cls.EXECUTABLE_MAP:
            raise BenchmarkConfigurationError(
                f"Unknown LSMIO setup: {f_setup!r}. Allowed setups: {cls.ALLOWED_SETUPS}"
            )
        return cls.EXECUTABLE_MAP[f_norm_setup]

    @classmethod
    def getBlockParameters(cls, f_block_size: str) -> Tuple[int, int]:
        """Return (block_bytes, key_count) for the given block size."""
        if not isinstance(f_block_size, str) or not f_block_size.strip():
            raise BenchmarkConfigurationError(
                f"Block size must be a non-empty string, got: {f_block_size!r}"
            )
        f_norm_size = f_block_size.strip().upper()
        if f_norm_size not in cls.BLOCK_SIZE_MAP:
            raise BenchmarkConfigurationError(
                f"Unsupported LSMIO block size: {f_block_size!r}. Allowed: {list(cls.BLOCK_SIZE_MAP.keys())}"
            )
        return cls.BLOCK_SIZE_MAP[f_norm_size]

    def createLaunchSpec(
        self,
        f_request: Any,
        f_combination: Any,
        f_point: Any,
        f_executable: Optional[str] = None,
    ) -> LsmioLaunchSpec:
        """Create unbound launch template specification for LSMIO benchmark."""
        # 1. Resolve and validate setup
        f_setup_name: str
        if hasattr(f_request, "setup") and f_request.setup is not None:
            f_setup_name = str(f_request.setup)
        elif isinstance(f_request, str) and f_request.strip():
            f_setup_name = f_request.strip()
        else:
            f_setup_name = self.DEFAULT_SETUP

        f_norm_setup = f_setup_name.strip().upper()
        if f_norm_setup == "ENV":
            raise BenchmarkConfigurationError(
                "LSMIO setup 'ENV' is a diagnostic mode and cannot be used as a run benchmark setup"
            )
        if f_norm_setup not in self.ALLOWED_SETUPS:
            raise BenchmarkConfigurationError(
                f"Unknown LSMIO setup: {f_setup_name!r}. Allowed setups: {self.ALLOWED_SETUPS}"
            )

        # 2. Resolve block size & validate
        f_bs_str: str
        if hasattr(f_combination, "block_size"):
            f_bs_str = str(f_combination.block_size).strip().upper()
        elif isinstance(f_combination, str):
            f_combo_str = f_combination.strip()
            if "_b" in f_combo_str:
                f_bs_str = f_combo_str.split("_b", 1)[1].strip().upper()
            else:
                f_bs_str = f_combo_str.upper()
        elif isinstance(f_combination, (tuple, list)) and len(f_combination) >= 2:
            f_bs_str = str(f_combination[1]).strip().upper()
        else:
            raise BenchmarkConfigurationError(
                f"Cannot resolve block size from combination: {f_combination!r}"
            )

        if f_bs_str not in self.BLOCK_SIZE_MAP:
            raise BenchmarkConfigurationError(
                f"Unsupported LSMIO block size: {f_bs_str!r}. Allowed: {list(self.BLOCK_SIZE_MAP.keys())}"
            )

        # 3. Resolve executable
        f_eff_executable: str
        if f_executable is not None and str(f_executable).strip():
            if "\0" in f_executable:
                raise BenchmarkConfigurationError(
                    f"Executable contains NUL byte: {f_executable!r}"
                )
            f_eff_executable = str(f_executable).strip()
        else:
            f_eff_executable = self.getExecutableName(f_norm_setup)

        f_variant = getattr(f_request, "variant", None)
        return LsmioLaunchSpec(
            f_request=f_request,
            f_combination=f_combination,
            f_point=f_point,
            f_setup=f_norm_setup,
            f_executable=f_eff_executable,
            f_variant=f_variant,
            f_is_rank_local=True,
            f_is_bound=False,
        )

    def bindRank(
        self,
        f_spec: Any,
        f_identity: Any,
        f_layout: Any,
        f_ordinal: Optional[int] = None,
    ) -> LsmioBoundCommand:
        """Deterministically bind a rank identity to a launch spec using the artifact layout.

        CRITICAL INVARIANT: Performs ZERO filesystem writes, zero claims, zero locks,
        and zero duplicate detection.
        """
        # 1. Validate spec
        if (
            not hasattr(f_spec, "setup")
            or not hasattr(f_spec, "combination")
            or not hasattr(f_spec, "point")
        ):
            raise BenchmarkConfigurationError(
                f"f_spec must have setup, combination, and point attributes, got: {type(f_spec).__name__}"
            )

        f_setup = str(f_spec.setup).strip().upper()
        if f_setup == "ENV":
            raise BenchmarkConfigurationError(
                "LSMIO setup 'ENV' is a diagnostic mode and cannot be used as a run benchmark setup"
            )
        if f_setup not in self.ALLOWED_SETUPS:
            raise BenchmarkConfigurationError(
                f"Unknown LSMIO setup: {f_setup!r}. Allowed setups: {self.ALLOWED_SETUPS}"
            )

        # 2. Validate identity
        if not hasattr(f_identity, "global_rank"):
            raise BenchmarkConfigurationError(
                f"f_identity must have global_rank attribute, got: {type(f_identity).__name__}"
            )

        f_global_rank = getattr(f_identity, "global_rank")
        if not isinstance(f_global_rank, int) or f_global_rank < 0:
            raise BenchmarkConfigurationError(
                f"global_rank must be a non-negative integer, got: {f_global_rank!r}"
            )

        # Validate tasks range
        f_tasks: int
        if hasattr(f_spec.point, "tasks"):
            f_tasks = int(f_spec.point.tasks)
        elif isinstance(f_spec.point, int):
            f_tasks = f_spec.point
        else:
            raise BenchmarkConfigurationError(
                f"Cannot determine task count from point: {f_spec.point!r}"
            )

        if f_global_rank >= f_tasks:
            raise BenchmarkConfigurationError(
                f"global_rank ({f_global_rank}) is out of range for point tasks ({f_tasks})"
            )

        # Supports PBS where local_rank is None
        f_local_rank = getattr(f_identity, "local_rank", None)
        if f_local_rank is not None:
            if not isinstance(f_local_rank, int) or f_local_rank < 0:
                raise BenchmarkConfigurationError(
                    f"local_rank must be a non-negative integer or None, got: {f_local_rank!r}"
                )

        # 3. Validate layout
        if not hasattr(f_layout, "pointDir") or not hasattr(f_layout, "pointLogsDir"):
            raise BenchmarkConfigurationError(
                f"f_layout must be an ArtifactLayout instance, got: {type(f_layout).__name__}"
            )

        # 4. Pure path derivations (no filesystem writes or checks)
        f_point_desc = f_spec.point
        f_combo_desc = f_spec.combination

        if hasattr(f_layout, "pointRankLogPath"):
            f_log_path = f_layout.pointRankLogPath(
                f_point_desc, f_global_rank, f_combo_desc, f_ordinal
            )
        elif hasattr(f_layout, "pointCombinationLogsDir"):
            f_log_path = os.path.join(
                f_layout.pointCombinationLogsDir(f_point_desc, f_combo_desc, f_ordinal),
                f"rank_{f_global_rank}.log",
            )
        else:
            f_combo_name = (
                f_layout.combinationName(f_combo_desc)
                if hasattr(f_layout, "combinationName")
                else (
                    f_combo_desc.name
                    if hasattr(f_combo_desc, "name")
                    else str(f_combo_desc)
                )
            )
            f_logs_dir = f_layout.pointLogsDir(f_point_desc, f_ordinal)
            f_log_path = os.path.join(
                f_logs_dir, f_combo_name, f"rank_{f_global_rank}.log"
            )

        f_result_path = f_layout.pointRankResultPath(
            f_point_desc, f_global_rank, f_combo_desc, f_ordinal
        )

        f_work_dir = f_layout.pointCombinationWorkDir(
            f_point_desc, f_combo_desc, f_ordinal
        )

        f_stripe = (
            getattr(f_combo_desc, "stripe_count", 16)
            if hasattr(f_combo_desc, "stripe_count")
            else 16
        )
        f_bs_name = (
            getattr(f_combo_desc, "block_size", "8M")
            if hasattr(f_combo_desc, "block_size")
            else "8M"
        )

        f_variant = getattr(f_spec, "variant", None)
        f_variant_rec = VariantCatalogue.resolve(f_variant)

        f_data_dir = f_layout.pointDataSubdir(
            f_point_desc, f_stripe, f_bs_name, f_ordinal
        )
        if f_variant_rec.tokens:
            f_db_name = f"lsmio-rank-{f_global_rank}-{f_setup.lower()}-{f_variant_rec.tokens}.db"
        else:
            f_db_name = f"lsmio-rank-{f_global_rank}-{f_setup.lower()}.db"
        f_output_path = os.path.join(f_data_dir, f_db_name)

        # 5. Block sizing and key count
        f_block_bytes, f_key_count = self.getBlockParameters(str(f_bs_name))

        # 6. Build argv
        f_exe = str(f_spec.executable).strip()
        f_argv: List[str] = [f_exe]

        f_argv.extend(self.MPI_FLAGS)

        if f_setup == "PLUGIN":
            f_argv.append("--lsmio-plugin")

        if f_variant_rec.flags:
            f_argv.extend(f_variant_rec.flags)

        f_argv.extend(
            [
                "-i",
                "10",
                "-o",
                f_output_path,
                "--lsmio-ts",
                str(f_block_bytes),
                "--lsmio-bs",
                str(f_block_bytes),
                "--key-count",
                str(f_key_count),
            ]
        )

        return LsmioBoundCommand(
            f_argv=f_argv,
            f_stdout_path=f_log_path,
            f_stderr_path=f_log_path,
            f_working_dir=f_work_dir,
            f_is_rank_local=True,
            f_result_path=f_result_path,
            f_output_path=f_output_path,
            f_identity=f_identity,
            f_spec=f_spec,
        )

    def buildCommand(
        self,
        f_executable: str,
        f_setup: str = "NATIVE",
        f_block_size: Optional[str] = None,
        f_working_dir: str = "/tmp",
        f_output_path: Optional[str] = None,
        f_stdout_path: Optional[str] = None,
        f_stderr_path: Optional[str] = None,
        f_combination: Optional[Any] = None,
        f_stripe_count: Optional[int] = None,
        f_global_rank: int = 0,
        f_variant: Optional[str] = None,
    ) -> LsmioBoundCommand:
        """Construct a BenchmarkCommand / LsmioBoundCommand directly for an LSMIO run."""
        if not isinstance(f_executable, str) or not f_executable.strip():
            raise BenchmarkConfigurationError(
                f"Executable must be a non-empty string, got: {f_executable!r}"
            )
        if "\0" in f_executable:
            raise BenchmarkConfigurationError(
                f"Executable contains NUL byte: {f_executable!r}"
            )

        f_norm_executable = f_executable.strip()

        if not isinstance(f_setup, str) or not f_setup.strip():
            raise BenchmarkConfigurationError(
                f"Setup must be a non-empty string, got: {f_setup!r}"
            )
        f_norm_setup = f_setup.strip().upper()
        if f_norm_setup == "ENV":
            raise BenchmarkConfigurationError(
                "LSMIO setup 'ENV' is a diagnostic mode and cannot be used as a run benchmark setup"
            )
        if f_norm_setup not in self.ALLOWED_SETUPS:
            raise BenchmarkConfigurationError(
                f"Unknown LSMIO setup: {f_setup!r}. Allowed setups: {self.ALLOWED_SETUPS}"
            )

        # Resolve variant
        f_variant_rec = VariantCatalogue.resolve(f_variant)

        # Resolve block size
        f_resolved_block_size: Optional[str] = None
        if f_block_size is not None:
            if not isinstance(f_block_size, str) or not f_block_size.strip():
                raise BenchmarkConfigurationError(
                    f"Block size must be a non-empty string, got: {f_block_size!r}"
                )
            f_resolved_block_size = f_block_size.strip().upper()
        elif f_combination is not None:
            if hasattr(f_combination, "block_size"):
                f_resolved_block_size = str(f_combination.block_size).strip().upper()
            elif isinstance(f_combination, str):
                f_combo_str = f_combination.strip()
                if "_b" in f_combo_str:
                    f_resolved_block_size = (
                        f_combo_str.split("_b", 1)[1].strip().upper()
                    )
                else:
                    f_resolved_block_size = f_combo_str.upper()
            elif isinstance(f_combination, (tuple, list)) and len(f_combination) >= 2:
                f_resolved_block_size = str(f_combination[1]).strip().upper()

        if f_resolved_block_size is None:
            raise BenchmarkConfigurationError(
                "Block size must be specified directly or via combination"
            )

        if f_resolved_block_size not in self.BLOCK_SIZE_MAP:
            raise BenchmarkConfigurationError(
                f"Unsupported LSMIO block size: {f_resolved_block_size!r}. Allowed: {list(self.BLOCK_SIZE_MAP.keys())}"
            )

        f_block_bytes, f_key_count = self.BLOCK_SIZE_MAP[f_resolved_block_size]

        if not isinstance(f_working_dir, str) or not f_working_dir.strip():
            raise BenchmarkConfigurationError(
                f"Working directory must be a non-empty string, got: {f_working_dir!r}"
            )
        if "\0" in f_working_dir:
            raise BenchmarkConfigurationError(
                f"Working directory contains NUL byte: {f_working_dir!r}"
            )
        f_norm_working_dir = os.path.normpath(f_working_dir.strip())

        if f_output_path is not None:
            if not isinstance(f_output_path, str) or not f_output_path.strip():
                raise BenchmarkConfigurationError(
                    f"Output path must be a non-empty string, got: {f_output_path!r}"
                )
            if "\0" in f_output_path:
                raise BenchmarkConfigurationError(
                    f"Output path contains NUL byte: {f_output_path!r}"
                )
            f_outpath = os.path.normpath(f_output_path.strip())
        else:
            if f_variant_rec.tokens:
                f_db_name = f"lsmio-rank-{f_global_rank}-{f_norm_setup.lower()}-{f_variant_rec.tokens}.db"
            else:
                f_db_name = f"lsmio-rank-{f_global_rank}-{f_norm_setup.lower()}.db"
            f_outpath = os.path.join(
                f_norm_working_dir,
                f_db_name,
            )

        if f_stdout_path is not None:
            if not isinstance(f_stdout_path, str) or not f_stdout_path.strip():
                raise BenchmarkConfigurationError(
                    f"Stdout path must be a non-empty string, got: {f_stdout_path!r}"
                )
            if "\0" in f_stdout_path:
                raise BenchmarkConfigurationError(
                    f"Stdout path contains NUL byte: {f_stdout_path!r}"
                )
            f_norm_stdout = os.path.normpath(f_stdout_path.strip())
        else:
            f_norm_stdout = os.path.join(
                f_norm_working_dir, f"rank_{f_global_rank}.log"
            )

        if f_stderr_path is not None:
            if not isinstance(f_stderr_path, str) or not f_stderr_path.strip():
                raise BenchmarkConfigurationError(
                    f"Stderr path must be a non-empty string, got: {f_stderr_path!r}"
                )
            if "\0" in f_stderr_path:
                raise BenchmarkConfigurationError(
                    f"Stderr path contains NUL byte: {f_stderr_path!r}"
                )
            f_norm_stderr = os.path.normpath(f_stderr_path.strip())
        else:
            f_norm_stderr = f_norm_stdout

        f_argv: List[str] = [f_norm_executable]
        f_argv.extend(self.MPI_FLAGS)
        if f_norm_setup == "PLUGIN":
            f_argv.append("--lsmio-plugin")
        if f_variant_rec.flags:
            f_argv.extend(f_variant_rec.flags)
        f_argv.extend(
            [
                "-i",
                "10",
                "-o",
                f_outpath,
                "--lsmio-ts",
                str(f_block_bytes),
                "--lsmio-bs",
                str(f_block_bytes),
                "--key-count",
                str(f_key_count),
            ]
        )

        return LsmioBoundCommand(
            f_argv=f_argv,
            f_stdout_path=f_norm_stdout,
            f_stderr_path=f_norm_stderr,
            f_working_dir=f_norm_working_dir,
            f_is_rank_local=True,
            f_output_path=f_outpath,
        )

    # Convenience aliases
    buildBenchmarkCommand = buildCommand
    createCommand = buildCommand
    build_command = buildCommand

    def probeCapability(
        self,
        f_executable: str,
        f_runner: Optional[Callable[..., Any]] = None,
        f_setup: Optional[str] = None,
    ) -> CapabilityState:
        """Probe LSMIO capability or report configured/unverified."""
        if not isinstance(f_executable, str) or not f_executable.strip():
            raise BenchmarkConfigurationError(
                f"Executable must be a non-empty string, got: {f_executable!r}"
            )
        if "\0" in f_executable:
            raise BenchmarkConfigurationError(
                f"Executable contains NUL byte: {f_executable!r}"
            )

        f_norm_executable = f_executable.strip()

        if f_setup is not None:
            f_norm_setup = f_setup.strip().upper()
            if f_norm_setup == "ENV":
                raise BenchmarkProbeError(
                    "LSMIO setup 'ENV' is a diagnostic mode and cannot be probed as a run benchmark"
                )
            if f_norm_setup not in self.ALLOWED_SETUPS:
                raise BenchmarkProbeError(
                    f"Unsupported LSMIO setup requested: {f_setup!r}. Allowed: {self.ALLOWED_SETUPS}"
                )

        # Per Critic P-02 and Architecture §10: LSMIO executables do not expose a probe (bare -v fails).
        # They remain configured but unverified without invoking a probe command.
        return CapabilityState.CONFIGURED


class LmpAdapter(BenchmarkAdapter):
    """Adapter for constructing exact LMP shared-command benchmark specifications,
    probing LMP capabilities, and validating and staging immutable input assets.
    """

    TARGET: str = "lmp"
    DEFAULT_SETUP: str = "LSMIO"
    ALLOWED_SETUPS: Tuple[str, ...] = (
        "LSMIO",
        "LSMIO-MMAP",
        "FS",
    )

    REQUIRED_ASSETS: Tuple[str, ...] = (
        "in.reaxc.hns",
        "data.hns-equil",
        "ffield.reax.hns",
    )

    RANK_PLACEHOLDERS: Tuple[str, ...] = (
        "{rank}",
        "{global_rank}",
        "{local_rank}",
        "%r",
        "@RANK@",
    )

    @property
    def target(self) -> str:
        return self.TARGET

    @property
    def defaultSetup(self) -> str:
        return self.DEFAULT_SETUP

    @property
    def allowedSetups(self) -> Tuple[str, ...]:
        return self.ALLOWED_SETUPS

    def validateAssets(self, f_asset_root: str) -> Dict[str, str]:
        """Verify each required asset at the consumer boundary using os.lstat.

        Requires each asset to be a readable, non-symlink regular file.
        Returns a dictionary mapping asset filenames to SHA-256 hex digests.
        """
        if not isinstance(f_asset_root, str) or not f_asset_root.strip():
            raise BenchmarkConfigurationError(
                f"Asset root must be a non-empty string, got: {f_asset_root!r}"
            )
        if "\0" in f_asset_root:
            raise BenchmarkConfigurationError(
                f"Asset root contains NUL byte: {f_asset_root!r}"
            )

        f_norm_root = os.path.normpath(f_asset_root.strip())
        f_hashes: Dict[str, str] = {}

        for f_asset_name in self.REQUIRED_ASSETS:
            f_asset_path = os.path.join(f_norm_root, f_asset_name)
            try:
                f_stat = os.lstat(f_asset_path)
            except (FileNotFoundError, OSError) as f_exc:
                raise BenchmarkConfigurationError(
                    f"Required LMP asset '{f_asset_name}' not found at '{f_asset_path}': {f_exc}"
                ) from f_exc

            if stat.S_ISLNK(f_stat.st_mode):
                raise BenchmarkConfigurationError(
                    f"Required LMP asset '{f_asset_name}' at '{f_asset_path}' is a symlink, which is forbidden"
                )

            if not stat.S_ISREG(f_stat.st_mode):
                raise BenchmarkConfigurationError(
                    f"Required LMP asset '{f_asset_name}' at '{f_asset_path}' is not a regular file"
                )

            f_hasher = hashlib.sha256()
            try:
                with open(f_asset_path, "rb") as f_f:
                    while True:
                        f_chunk = f_f.read(65536)
                        if not f_chunk:
                            break
                        f_hasher.update(f_chunk)
            except (PermissionError, OSError) as f_exc:
                raise BenchmarkConfigurationError(
                    f"Required LMP asset '{f_asset_name}' at '{f_asset_path}' cannot be read: {f_exc}"
                ) from f_exc

            f_hashes[f_asset_name] = f_hasher.hexdigest()

        return f_hashes

    def stageAssets(
        self,
        f_asset_source: Union[str, Any],
        f_work_dir: str,
    ) -> Dict[str, str]:
        """Validate assets at the source boundary and stage immutable copies into work_dir.

        Returns a dictionary mapping asset filenames to their SHA-256 hex digests.
        """
        # Resolve asset root from string or layout object
        if hasattr(f_asset_source, "asset_root"):
            f_asset_root = str(f_asset_source.asset_root)
        elif hasattr(f_asset_source, "assetRoot"):
            f_asset_root = str(f_asset_source.assetRoot)
        elif isinstance(f_asset_source, str):
            f_asset_root = f_asset_source
        else:
            raise BenchmarkConfigurationError(
                f"Asset source must be a string path or RuntimeLayout object, got: {type(f_asset_source).__name__}"
            )

        if not isinstance(f_work_dir, str) or not f_work_dir.strip():
            raise BenchmarkConfigurationError(
                f"Working directory must be a non-empty string, got: {f_work_dir!r}"
            )
        if "\0" in f_work_dir:
            raise BenchmarkConfigurationError(
                f"Working directory contains NUL byte: {f_work_dir!r}"
            )

        f_norm_work_dir = os.path.normpath(f_work_dir.strip())

        for f_ph in self.RANK_PLACEHOLDERS:
            if f_ph in f_norm_work_dir:
                raise BenchmarkConfigurationError(
                    f"LMP working directory contains rank placeholder {f_ph!r}: {f_norm_work_dir!r}"
                )

        # Validate source assets and compute their hashes
        f_hashes = self.validateAssets(f_asset_root)
        f_norm_source_root = os.path.normpath(f_asset_root.strip())

        # Ensure destination directory exists
        try:
            os.makedirs(f_norm_work_dir, exist_ok=True)
        except OSError as f_exc:
            raise BenchmarkConfigurationError(
                f"Failed to create LMP working directory '{f_norm_work_dir}': {f_exc}"
            ) from f_exc

        # Stage immutable copies
        for f_asset_name in self.REQUIRED_ASSETS:
            f_src_path = os.path.join(f_norm_source_root, f_asset_name)
            f_dst_path = os.path.join(f_norm_work_dir, f_asset_name)
            try:
                with open(f_src_path, "rb") as f_src_file:
                    f_content = f_src_file.read()
                with open(f_dst_path, "wb") as f_dst_file:
                    f_dst_file.write(f_content)
            except OSError as f_exc:
                raise BenchmarkConfigurationError(
                    f"Failed to stage LMP asset '{f_asset_name}' from '{f_src_path}' to '{f_dst_path}': {f_exc}"
                ) from f_exc

        return f_hashes

    def buildCommand(
        self,
        f_executable: str,
        f_setup: str = "LSMIO",
        f_replication: Optional[int] = None,
        f_buffer_size_mb: Optional[int] = None,
        f_working_dir: str = "/tmp",
        f_stdout_path: Optional[str] = None,
        f_stderr_path: Optional[str] = None,
        f_tuning: Optional[Mapping[str, Any]] = None,
        **f_kwargs: Any,
    ) -> BenchmarkCommand:
        """Construct exact BenchmarkCommand for a shared LMP run.

        Consumes replication and buffer size exclusively from manifest tuning.
        Adapter is table-free and performs zero fallback searches.
        """
        # Validate executable
        if not isinstance(f_executable, str) or not f_executable.strip():
            raise BenchmarkConfigurationError(
                f"Executable must be a non-empty string, got: {f_executable!r}"
            )
        if "\0" in f_executable:
            raise BenchmarkConfigurationError(
                f"Executable contains NUL byte: {f_executable!r}"
            )
        f_norm_executable = f_executable.strip()

        # Validate setup
        if not isinstance(f_setup, str) or not f_setup.strip():
            raise BenchmarkConfigurationError(
                f"Setup must be a non-empty string, got: {f_setup!r}"
            )
        f_norm_setup = f_setup.strip().upper()
        if f_norm_setup not in self.ALLOWED_SETUPS:
            raise BenchmarkConfigurationError(
                f"Unknown LMP setup: {f_setup!r}. Allowed setups: {self.ALLOWED_SETUPS}"
            )

        # Resolve replication (REP)
        f_rep = f_replication
        if f_rep is None:
            f_rep = f_kwargs.get("f_rep") or f_kwargs.get("rep")
        if f_rep is None and f_tuning is not None and isinstance(f_tuning, Mapping):
            f_rep = f_tuning.get("replication", f_tuning.get("rep"))

        if f_rep is None:
            raise BenchmarkConfigurationError(
                "LMP replication (REP) is required; adapter is table-free and consumes manifest tuning"
            )
        if isinstance(f_rep, bool) or not isinstance(f_rep, int) or f_rep <= 0:
            raise BenchmarkConfigurationError(
                f"LMP replication must be a positive integer, got: {f_rep!r}"
            )

        # Resolve buffer size (BUF)
        f_buf = f_buffer_size_mb
        if f_buf is None:
            f_buf = (
                f_kwargs.get("f_buf")
                or f_kwargs.get("f_buffer")
                or f_kwargs.get("buffer_size_mb")
                or f_kwargs.get("buffer")
            )
        if f_buf is None and f_tuning is not None and isinstance(f_tuning, Mapping):
            f_buf = f_tuning.get(
                "buffer_size_mb", f_tuning.get("buf", f_tuning.get("buffer"))
            )

        if f_norm_setup in ("LSMIO", "LSMIO-MMAP"):
            if f_buf is None:
                raise BenchmarkConfigurationError(
                    f"LMP buffer_size_mb is required for setup '{f_norm_setup}'"
                )
            if isinstance(f_buf, bool) or not isinstance(f_buf, int) or f_buf <= 0:
                raise BenchmarkConfigurationError(
                    f"LMP buffer_size_mb must be a positive integer, got: {f_buf!r}"
                )

        # Validate working dir
        if not isinstance(f_working_dir, str) or not f_working_dir.strip():
            raise BenchmarkConfigurationError(
                f"Working directory must be a non-empty string, got: {f_working_dir!r}"
            )
        if "\0" in f_working_dir:
            raise BenchmarkConfigurationError(
                f"Working directory contains NUL byte: {f_working_dir!r}"
            )
        f_norm_working_dir = os.path.normpath(f_working_dir.strip())

        # Resolve stdout and stderr paths
        if f_stdout_path is not None:
            if not isinstance(f_stdout_path, str) or not f_stdout_path.strip():
                raise BenchmarkConfigurationError(
                    f"Stdout path must be a non-empty string, got: {f_stdout_path!r}"
                )
            if "\0" in f_stdout_path:
                raise BenchmarkConfigurationError(
                    f"Stdout path contains NUL byte: {f_stdout_path!r}"
                )
            f_norm_stdout = os.path.normpath(f_stdout_path.strip())
        else:
            f_norm_stdout = os.path.join(
                f_norm_working_dir, f"lmp.{f_norm_setup.lower()}.stdout.log"
            )

        if f_stderr_path is not None:
            if not isinstance(f_stderr_path, str) or not f_stderr_path.strip():
                raise BenchmarkConfigurationError(
                    f"Stderr path must be a non-empty string, got: {f_stderr_path!r}"
                )
            if "\0" in f_stderr_path:
                raise BenchmarkConfigurationError(
                    f"Stderr path contains NUL byte: {f_stderr_path!r}"
                )
            f_norm_stderr = os.path.normpath(f_stderr_path.strip())
        else:
            f_norm_stderr = os.path.join(
                f_norm_working_dir, f"lmp.{f_norm_setup.lower()}.stderr.log"
            )

        # Validate that no rank placeholders are present in paths or executable
        for f_check_str, f_desc in (
            (f_norm_executable, "executable"),
            (f_norm_stdout, "stdout path"),
            (f_norm_stderr, "stderr path"),
            (f_norm_working_dir, "working directory"),
        ):
            for f_ph in self.RANK_PLACEHOLDERS:
                if f_ph in f_check_str:
                    raise BenchmarkConfigurationError(
                        f"LMP command {f_desc} contains rank placeholder {f_ph!r}: {f_check_str!r}"
                    )

        # Assemble exact upstream argv:
        # lmp -in in.reaxc.hns -v x REP -v y REP -v z REP [setup_flags]
        f_argv_list: List[str] = [
            f_norm_executable,
            "-in",
            "in.reaxc.hns",
            "-v",
            "x",
            str(f_rep),
            "-v",
            "y",
            str(f_rep),
            "-v",
            "z",
            str(f_rep),
        ]
        if f_norm_setup == "LSMIO":
            f_argv_list.extend(["-lsmio-buf-size-mb", str(f_buf)])
        elif f_norm_setup == "LSMIO-MMAP":
            f_argv_list.extend(["-lsmio-mmap", "-lsmio-buf-size-mb", str(f_buf)])
        elif f_norm_setup == "FS":
            f_argv_list.extend(["-lsmio-fallback"])

        return BenchmarkCommand(
            f_argv=f_argv_list,
            f_stdout_path=f_norm_stdout,
            f_stderr_path=f_norm_stderr,
            f_working_dir=f_norm_working_dir,
            f_is_rank_local=False,
        )

    # Convenience aliases
    buildBenchmarkCommand = buildCommand
    createCommand = buildCommand
    build_command = buildCommand

    def probeCapability(
        self,
        f_executable: str,
        f_runner: Optional[Callable[..., Any]] = None,
        f_setup: Optional[str] = None,
    ) -> CapabilityState:
        """Probe LMP capability using an injected runner or report configured/unverified."""
        if not isinstance(f_executable, str) or not f_executable.strip():
            raise BenchmarkConfigurationError(
                f"Executable must be a non-empty string, got: {f_executable!r}"
            )
        if "\0" in f_executable:
            raise BenchmarkConfigurationError(
                f"Executable contains NUL byte: {f_executable!r}"
            )

        f_norm_executable = f_executable.strip()

        if f_setup is not None:
            f_norm_setup = f_setup.strip().upper()
            if f_norm_setup not in self.ALLOWED_SETUPS:
                raise BenchmarkProbeError(
                    f"Unsupported LMP setup requested: {f_setup!r}. Allowed: {self.ALLOWED_SETUPS}"
                )

        if f_runner is None:
            return CapabilityState.CONFIGURED

        f_probe_argv = [f_norm_executable, "-h"]

        try:
            if hasattr(f_runner, "run") and callable(getattr(f_runner, "run")):
                f_result = f_runner.run(f_probe_argv)
            else:
                f_result = f_runner(f_probe_argv)
        except (FileNotFoundError, PermissionError, OSError) as f_exc:
            raise BenchmarkProbeError(
                f"LMP executable probe failed for {f_norm_executable!r}: {f_exc}"
            ) from f_exc
        except Exception as f_exc:
            raise BenchmarkProbeError(
                f"LMP probe runner raised unexpected error for {f_norm_executable!r}: {f_exc}"
            ) from f_exc

        # Inspect runner result
        f_exit_code: int = 0
        f_output_text: str = ""

        if hasattr(f_result, "returncode"):
            f_exit_code = int(f_result.returncode)
            f_stdout = getattr(f_result, "stdout", "") or ""
            f_stderr = getattr(f_result, "stderr", "") or ""
            f_output_text = f"{f_stdout}\n{f_stderr}"
        elif hasattr(f_result, "exit_code"):
            f_exit_code = int(f_result.exit_code)
            f_stdout = getattr(f_result, "stdout", "") or ""
            f_stderr = getattr(f_result, "stderr", "") or ""
            f_output_text = f"{f_stdout}\n{f_stderr}"
        elif isinstance(f_result, tuple) and len(f_result) >= 2:
            f_exit_code = int(f_result[0])
            f_output_text = str(f_result[1])
            if len(f_result) >= 3:
                f_output_text += f"\n{f_result[2]}"
        elif isinstance(f_result, int):
            f_exit_code = f_result
            f_output_text = ""
        elif isinstance(f_result, str):
            f_exit_code = 0
            f_output_text = f_result
        else:
            f_output_text = str(f_result)

        if f_exit_code != 0:
            raise BenchmarkProbeError(
                f"LMP executable {f_norm_executable!r} probe failed with exit code {f_exit_code}: {f_output_text.strip()}"
            )

        if not f_output_text.strip():
            raise BenchmarkProbeError(
                f"LMP executable {f_norm_executable!r} produced empty probe output"
            )

        f_lower_out = f_output_text.lower()
        if (
            "unsupported" in f_lower_out
            or "invalid option" in f_lower_out
            or "command not found" in f_lower_out
        ):
            raise BenchmarkProbeError(
                f"LMP executable {f_norm_executable!r} reported unsupported capability: {f_output_text.strip()}"
            )

        # Check setup-specific flags in help text
        if f_norm_setup == "LSMIO":
            if "buf" not in f_lower_out:
                raise BenchmarkProbeError(
                    f"LMP executable {f_norm_executable!r} help output does not expose required buffer flag ('buf') for setup 'LSMIO'"
                )
        elif f_norm_setup == "LSMIO-MMAP":
            if "buf" not in f_lower_out or "mmap" not in f_lower_out:
                raise BenchmarkProbeError(
                    f"LMP executable {f_norm_executable!r} help output does not expose required flags ('buf' and 'mmap') for setup 'LSMIO-MMAP'"
                )
        elif f_norm_setup == "FS":
            if "fallback" not in f_lower_out:
                raise BenchmarkProbeError(
                    f"LMP executable {f_norm_executable!r} help output does not expose required fallback flag ('fallback') for setup 'FS'"
                )
        else:
            if not ("lammps" in f_lower_out or "lmp" in f_lower_out):
                raise BenchmarkProbeError(
                    f"LMP executable {f_norm_executable!r} produced unrecognized help output: {f_output_text.strip()}"
                )

        return CapabilityState.VERIFIED


class EpocppAdapter(BenchmarkAdapter):
    """Adapter for EPOCpp, an application run with one shared srun per repeat.

    It fills the deck template (share/epocpp/two_stream.deck.in) for an arm and a scale
    and builds the epocpp command. An arm's setup names its backend (or NONE, the
    no-output baseline) and its kind: <BACKEND> is a wall-time run, timed by EPOCpp's
    own Runtime; <BACKEND>-BW is a bandwidth run, which adds --io-benchmark -m
    (lsmio::Benchmark's iwrite/iread results).
    """

    TARGET: str = "epocpp"
    DEFAULT_SETUP: str = "POSIX"
    BACKENDS: Tuple[str, ...] = ("NONE", "POSIX", "ADIOS2", "PLUGIN", "NATIVE")
    BANDWIDTH_SUFFIX: str = "-BW"
    ALLOWED_SETUPS: Tuple[str, ...] = (
        "NONE",
        "POSIX",
        "ADIOS2",
        "PLUGIN",
        "NATIVE",
        "POSIX-BW",
        "ADIOS2-BW",
        "PLUGIN-BW",
        "NATIVE-BW",
    )

    KIND_WALLTIME: str = "walltime"
    KIND_BANDWIDTH: str = "bandwidth"
    KINDS: Tuple[str, ...] = (KIND_WALLTIME, KIND_BANDWIDTH)
    BANDWIDTH_FLAGS: Tuple[str, ...] = ("--io-benchmark", "-m")

    # Output-block keys that pick each backend (EPOCpp's output block keys)
    BACKEND_KEYS: Dict[str, Tuple[str, ...]] = {
        "POSIX": ("filetype = posix",),
        "ADIOS2": ("filetype = adios",),
        "PLUGIN": ("filetype = adios", "adios_engine = plugin"),
        "NATIVE": ("filetype = lsmio",),
    }
    # The dump extension each backend writes (data<step>_<rank>.<ext>)
    OUTPUT_EXTENSIONS: Dict[str, str] = {
        "POSIX": "epc",
        "ADIOS2": "bp5",
        "PLUGIN": "lsp",
        "NATIVE": "ldb",
    }

    # The two deck sizes of the recommended decks: grid cells per side and particles
    # per cell; every scale but large runs the small deck
    DECK_SIZES: Dict[str, Tuple[int, int]] = {
        "small": (128, 64),
        "large": (1024, 128),
    }
    SCALE_DECKS: Dict[str, str] = {
        "local": "small",
        "bake": "small",
        "small": "small",
        "large": "large",
    }

    TEMPLATE_DIR: str = "epocpp"
    TEMPLATE_NAME: str = "two_stream.deck.in"
    TEMPLATE_PLACEHOLDERS: Tuple[str, ...] = ("nppc", "nx", "output")
    DECK_NAME: str = "input.deck"

    # The colleagues' output block: data named "data", particle positions and the
    # px/py momenta; a no-output run never dumps, a dump run dumps every step as a
    # full restart dump (restartable = T keeps the restart variables those
    # particle lines would otherwise clear) with a file per process
    _OUTPUT_COMMON: Tuple[str, ...] = (
        "particles = always",
        "px = always",
        "py = always",
    )
    _OUTPUT_NONE: Tuple[str, ...] = (
        "dump_first = F",
        "dump_last = F",
        "nstep_snapshot = 0",
    )
    _OUTPUT_DUMP: Tuple[str, ...] = (
        "dump_first = T",
        "dump_last = T",
        "nstep_snapshot = 1",
        "restartable = T",
    )

    _PLACEHOLDER_RE = re.compile(r"\$(?:\{(?P<braced>[^}]*)\}|(?P<other>.?))")

    @property
    def target(self) -> str:
        return self.TARGET

    @property
    def defaultSetup(self) -> str:
        return self.DEFAULT_SETUP

    @property
    def allowedSetups(self) -> Tuple[str, ...]:
        return self.ALLOWED_SETUPS

    @classmethod
    def normalizeSetup(cls, f_setup: str) -> str:
        """Return the canonical setup name, or raise BenchmarkConfigurationError."""
        if not isinstance(f_setup, str) or not f_setup.strip():
            raise BenchmarkConfigurationError(
                f"Setup must be a non-empty string, got: {f_setup!r}"
            )
        f_norm = f_setup.strip().upper()
        if f_norm not in cls.ALLOWED_SETUPS:
            raise BenchmarkConfigurationError(
                f"Unknown EPOCpp setup: {f_setup!r}. "
                f"Allowed setups: {cls.ALLOWED_SETUPS}"
            )
        return f_norm

    @classmethod
    def splitSetup(cls, f_setup: str) -> Tuple[str, str]:
        """Return an arm setup's (backend, kind): POSIX -> (POSIX, walltime),
        POSIX-BW -> (POSIX, bandwidth), NONE -> (NONE, walltime)."""
        f_norm = cls.normalizeSetup(f_setup)
        if f_norm.endswith(cls.BANDWIDTH_SUFFIX):
            return f_norm[: -len(cls.BANDWIDTH_SUFFIX)], cls.KIND_BANDWIDTH
        return f_norm, cls.KIND_WALLTIME

    @classmethod
    def deckForScale(cls, f_scale: str) -> str:
        """Return the deck size ('small' or 'large') a scale runs."""
        f_norm = f_scale.strip().lower() if isinstance(f_scale, str) else ""
        if f_norm not in cls.SCALE_DECKS:
            raise BenchmarkConfigurationError(
                f"Unsupported EPOCpp scale: {f_scale!r}. "
                f"Allowed: {list(cls.SCALE_DECKS)}"
            )
        return cls.SCALE_DECKS[f_norm]

    @classmethod
    def outputBlock(cls, f_setup: str) -> str:
        """Return the deck's output block for f_setup (both kinds share it)."""
        f_norm = cls.splitSetup(f_setup)[0]
        f_keys: List[str] = ["name = data"]
        if f_norm == "NONE":
            f_keys += [*cls._OUTPUT_NONE, *cls._OUTPUT_COMMON]
        else:
            f_keys += [
                *cls._OUTPUT_DUMP,
                *cls._OUTPUT_COMMON,
                "file_per_process = T",
                *cls.BACKEND_KEYS[f_norm],
            ]
        return "\n".join(
            ["begin:output", *(f"  {f_key}" for f_key in f_keys), "end:output"]
        )

    @classmethod
    def templatePath(cls, f_share_root: str) -> str:
        """Return the template's path under a share root (source share/ or installed
        share/lsmio/)."""
        return os.path.join(f_share_root, cls.TEMPLATE_DIR, cls.TEMPLATE_NAME)

    def readTemplate(self, f_template_path: str) -> str:
        """Read the deck template: a readable, non-symlink regular file whose only
        placeholders are exactly TEMPLATE_PLACEHOLDERS."""
        if not isinstance(f_template_path, str) or not f_template_path.strip():
            raise BenchmarkConfigurationError(
                f"Template path must be a non-empty string, got: {f_template_path!r}"
            )
        if "\0" in f_template_path:
            raise BenchmarkConfigurationError(
                f"Template path contains NUL byte: {f_template_path!r}"
            )
        try:
            f_stat = os.lstat(f_template_path)
        except OSError as f_exc:
            raise BenchmarkConfigurationError(
                f"EPOCpp deck template not found at '{f_template_path}': {f_exc}"
            ) from f_exc
        if stat.S_ISLNK(f_stat.st_mode):
            raise BenchmarkConfigurationError(
                f"EPOCpp deck template '{f_template_path}' is a symlink, "
                "which is forbidden"
            )
        if not stat.S_ISREG(f_stat.st_mode):
            raise BenchmarkConfigurationError(
                f"EPOCpp deck template '{f_template_path}' is not a regular file"
            )
        try:
            with open(f_template_path, encoding="utf-8") as f_f:
                f_text = f_f.read()
        except (OSError, UnicodeDecodeError) as f_exc:
            raise BenchmarkConfigurationError(
                f"EPOCpp deck template '{f_template_path}' is not readable: {f_exc}"
            ) from f_exc

        f_found: Set[str] = set()
        for f_match in self._PLACEHOLDER_RE.finditer(f_text):
            f_name = f_match.group("braced")
            if f_name is None:
                raise BenchmarkConfigurationError(
                    f"EPOCpp deck template '{f_template_path}' has a '$' that is not a "
                    f"${{name}} placeholder: {f_match.group(0)!r}"
                )
            f_found.add(f_name)
        if f_found != set(self.TEMPLATE_PLACEHOLDERS):
            raise BenchmarkConfigurationError(
                f"EPOCpp deck template '{f_template_path}' has placeholders "
                f"{sorted(f_found)}, expected {sorted(self.TEMPLATE_PLACEHOLDERS)}"
            )
        return f_text

    def renderDeck(
        self,
        f_template_text: str,
        f_setup: str,
        f_deck: str = "small",
        f_nx: Optional[int] = None,
        f_nppc: Optional[int] = None,
    ) -> str:
        """Fill the template for f_setup and the f_deck size; f_nx/f_nppc replace the
        size's values (tests shrink the grid)."""
        f_deck = f_deck.strip().lower() if isinstance(f_deck, str) else ""
        if f_deck not in self.DECK_SIZES:
            raise BenchmarkConfigurationError(
                f"Unknown EPOCpp deck size: {f_deck!r}. "
                f"Allowed: {list(self.DECK_SIZES)}"
            )
        f_size_nx, f_size_nppc = self.DECK_SIZES[f_deck]
        f_values = {
            "nx": f_size_nx if f_nx is None else f_nx,
            "nppc": f_size_nppc if f_nppc is None else f_nppc,
        }
        for f_key, f_value in f_values.items():
            if isinstance(f_value, bool) or not isinstance(f_value, int) or f_value < 1:
                raise BenchmarkConfigurationError(
                    f"EPOCpp deck {f_key} must be a positive integer, got: {f_value!r}"
                )
        try:
            return string.Template(f_template_text).substitute(
                nx=f_values["nx"],
                nppc=f_values["nppc"],
                output=self.outputBlock(f_setup),
            )
        except (KeyError, ValueError) as f_exc:
            raise BenchmarkConfigurationError(
                f"EPOCpp deck template could not be filled: {f_exc!r}"
            ) from f_exc

    def writeDeck(self, f_deck_text: str, f_deck_dir: str) -> str:
        """Write f_deck_text as <f_deck_dir>/input.deck (a new file; an existing deck
        or a symlink is refused) and return its path. A failed write leaves no deck."""
        if not isinstance(f_deck_text, str):
            raise BenchmarkConfigurationError(
                f"EPOCpp deck text must be a string, got: {type(f_deck_text).__name__}"
            )
        try:
            f_bytes = f_deck_text.encode("utf-8")
        except UnicodeEncodeError as f_exc:
            raise BenchmarkConfigurationError(
                f"EPOCpp deck text cannot be encoded as UTF-8: {f_exc}"
            ) from f_exc
        if not os.path.isdir(f_deck_dir) or os.path.islink(f_deck_dir):
            raise BenchmarkConfigurationError(
                f"EPOCpp deck directory '{f_deck_dir}' is not a directory"
            )
        f_path = os.path.join(f_deck_dir, self.DECK_NAME)
        try:
            f_fd = os.open(f_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except OSError as f_exc:
            raise BenchmarkConfigurationError(
                f"EPOCpp deck '{f_path}' could not be created: {f_exc}"
            ) from f_exc
        try:
            with os.fdopen(f_fd, "wb") as f_f:
                f_f.write(f_bytes)
                f_f.flush()
                os.fsync(f_f.fileno())
            f_dir_fd = os.open(f_deck_dir, os.O_RDONLY)
            try:
                os.fsync(f_dir_fd)
            finally:
                os.close(f_dir_fd)
        except OSError as f_exc:
            try:
                os.unlink(f_path)
            except OSError:
                pass
            raise BenchmarkConfigurationError(
                f"EPOCpp deck '{f_path}' could not be written: {f_exc}"
            ) from f_exc
        return f_path

    @staticmethod
    def logFileName(f_combo_name: str, f_repeat: int) -> str:
        """The log of one run (1-based repeat) in a point's logs dir."""
        return f"epocpp_{f_combo_name}_r{f_repeat:02d}.stdout"

    # The line the worker appends to a run's log once the run has exited
    DATA_BYTES_PREFIX: str = "lsmiotool: data bytes = "
    _RUNTIME_RE = re.compile(
        r"^Runtime = ([0-9]+(?:\.[0-9]*)?(?:[eE][-+]?[0-9]+)?)\s*$", re.M
    )
    _SUMMARY_RE = re.compile(r"^(write|read),([0-9][^,]*),", re.M)

    @classmethod
    def runtimeOf(cls, f_text: str) -> Optional[float]:
        """EPOCpp's `Runtime = <seconds>` from a run's output, or None."""
        f_matches = cls._RUNTIME_RE.findall(f_text)
        return float(f_matches[-1]) if f_matches else None

    @classmethod
    def checkOutput(cls, f_setup: str, f_text: str) -> Optional[str]:
        """Why a run's output is not a complete run of f_setup's kind, or None:
        every run prints Runtime; a bandwidth run also prints BENCHMARK RESULTS with
        numeric write and read summaries."""
        if cls.runtimeOf(f_text) is None:
            return "no 'Runtime = <seconds>' line"
        if cls.splitSetup(f_setup)[1] != cls.KIND_BANDWIDTH:
            return None
        if "BENCHMARK RESULTS:" not in f_text:
            return "no 'BENCHMARK RESULTS:' block"
        f_ops = {f_m.group(1) for f_m in cls._SUMMARY_RE.finditer(f_text)}
        for f_op in ("write", "read"):
            if f_op not in f_ops:
                return f"no numeric '{f_op},' summary (FAILED or missing)"
        return None

    # Threads that size and remove a run's dumps: each file costs Lustre metadata
    # round trips, so overlapping them is what shortens the pass, not CPU
    CLEANUP_THREADS = 32

    @staticmethod
    def _countAndRemoveEntry(f_path: str) -> Tuple[int, int, int]:
        """Size, then remove, one top-level entry of a data dir: a file, a symlink
        (never followed) or a directory, deepest first. Directories are walked by
        file descriptor, so a symlink swapped in cannot lead the removal elsewhere.
        What cannot be removed is left, with the first error on stderr."""
        f_size = f_alloc = f_files = 0
        f_error: Optional[OSError] = None

        def _note(f_err: OSError) -> None:
            nonlocal f_error
            # Gone already is what removing wants
            if f_error is None and f_err.errno != errno.ENOENT:
                f_error = f_err

        def _remove(f_name: str, f_dir_fd: Optional[int]) -> None:
            nonlocal f_size, f_alloc, f_files
            try:
                f_st = os.stat(f_name, dir_fd=f_dir_fd, follow_symlinks=False)
                if stat.S_ISDIR(f_st.st_mode):
                    os.rmdir(f_name, dir_fd=f_dir_fd)
                    return
                os.unlink(f_name, dir_fd=f_dir_fd)
                # Counted once removed, so a pass over what is left counts it once
                if stat.S_ISREG(f_st.st_mode):
                    f_size += f_st.st_size
                    f_alloc += getattr(f_st, "st_blocks", 0) * 512
                    f_files += 1
            except OSError as f_err:
                _note(f_err)

        try:
            f_is_dir = stat.S_ISDIR(os.lstat(f_path).st_mode)
        except OSError as f_err:
            _note(f_err)
            f_is_dir = False
        if f_is_dir:
            # fwalk raises, rather than calls onerror, when it cannot open f_path
            try:
                for _, f_dirs, f_names, f_fd in os.fwalk(
                    f_path, topdown=False, onerror=_note, follow_symlinks=False
                ):
                    for f_name in f_names + f_dirs:
                        _remove(f_name, f_fd)
            except OSError as f_err:
                _note(f_err)
        if f_error is None or f_is_dir:
            _remove(f_path, None)
        if f_error is not None:
            sys.stderr.write(f"WARNING: failed to remove under '{f_path}': {f_error}\n")
        return f_size, f_alloc, f_files

    @classmethod
    def countAndRemove(
        cls, f_data_dir: str, f_threads: Optional[int] = None
    ) -> Tuple[int, int, int]:
        """(file bytes, allocated bytes, files) a run left under f_data_dir, in the same
        pass that empties it; read once the run has exited, so nothing observes it
        while running. Each top-level entry (one rank's dump: data<step>_<rank>.<ext>)
        is sized and removed by one of f_threads threads. Symlinks are removed, never
        followed; f_data_dir itself (and its striping) is kept. What cannot be removed
        is left; the caller checks the dir ends up empty."""
        from concurrent.futures import ThreadPoolExecutor

        try:
            f_entries = [
                os.path.join(f_data_dir, f_e) for f_e in os.listdir(f_data_dir)
            ]
        except OSError:
            return 0, 0, 0
        if not f_entries:
            return 0, 0, 0
        f_workers = max(1, min(f_threads or cls.CLEANUP_THREADS, len(f_entries)))
        with ThreadPoolExecutor(max_workers=f_workers) as f_pool:
            f_parts = list(f_pool.map(cls._countAndRemoveEntry, f_entries))
        return (
            sum(f_p[0] for f_p in f_parts),
            sum(f_p[1] for f_p in f_parts),
            sum(f_p[2] for f_p in f_parts),
        )

    @classmethod
    def dataBytesLine(cls, f_size: int, f_alloc: int, f_files: int) -> str:
        return (
            f"{cls.DATA_BYTES_PREFIX}{f_size} allocated = {f_alloc} files = {f_files}\n"
        )

    def buildCommand(
        self,
        f_executable: str,
        f_setup: str,
        f_deck_dir: str,
        f_data_dir: str,
        f_working_dir: str,
        f_stdout_path: str,
        f_stderr_path: Optional[str] = None,
    ) -> BenchmarkCommand:
        """Construct the shared epocpp command: epocpp [--io-benchmark -m] -i <deck
        dir> -o <data dir>."""
        f_norm_kind = self.splitSetup(f_setup)[1]
        f_checked: Dict[str, str] = {}
        for f_desc, f_value in (
            ("Executable", f_executable),
            ("Deck directory", f_deck_dir),
            ("Data directory", f_data_dir),
            ("Working directory", f_working_dir),
            ("Stdout path", f_stdout_path),
            (
                "Stderr path",
                f_stdout_path if f_stderr_path is None else f_stderr_path,
            ),
        ):
            if not isinstance(f_value, str) or not f_value.strip():
                raise BenchmarkConfigurationError(
                    f"{f_desc} must be a non-empty string, got: {f_value!r}"
                )
            if "\0" in f_value:
                raise BenchmarkConfigurationError(
                    f"{f_desc} contains NUL byte: {f_value!r}"
                )
            for f_ph in IorAdapter.RANK_PLACEHOLDERS:
                if f_ph in f_value:
                    raise BenchmarkConfigurationError(
                        f"EPOCpp command {f_desc.lower()} contains rank placeholder "
                        f"{f_ph!r}: {f_value!r}"
                    )
            f_checked[f_desc] = (
                f_value.strip()
                if f_desc == "Executable"
                else os.path.normpath(f_value.strip())
            )

        f_argv: List[str] = [f_checked["Executable"]]
        if f_norm_kind == self.KIND_BANDWIDTH:
            f_argv += self.BANDWIDTH_FLAGS
        f_argv += ["-i", f_checked["Deck directory"], "-o", f_checked["Data directory"]]
        return BenchmarkCommand(
            f_argv=f_argv,
            f_stdout_path=f_checked["Stdout path"],
            f_stderr_path=f_checked["Stderr path"],
            f_working_dir=f_checked["Working directory"],
            f_is_rank_local=False,
        )

    def probeCapability(
        self,
        f_executable: str,
        f_runner: Optional[Callable[..., Any]] = None,
        f_setup: Optional[str] = None,
    ) -> CapabilityState:
        """CONFIGURED without a runner; with one, VERIFIED when `epocpp --help` exits 0
        and offers --io-benchmark (an EPOCpp built with LSMIO), else
        BenchmarkProbeError. The runner must start epocpp bare: --help exits before
        MPI_Finalize, which mpirun and srun report as a failure."""
        if not isinstance(f_executable, str) or not f_executable.strip():
            raise BenchmarkConfigurationError(
                f"Executable must be a non-empty string, got: {f_executable!r}"
            )
        if "\0" in f_executable:
            raise BenchmarkConfigurationError(
                f"Executable contains NUL byte: {f_executable!r}"
            )
        if f_setup is not None:
            try:
                self.normalizeSetup(f_setup)
            except BenchmarkConfigurationError as f_exc:
                raise BenchmarkProbeError(str(f_exc)) from f_exc
        if f_runner is None:
            return CapabilityState.CONFIGURED

        f_norm_executable = f_executable.strip()
        f_argv = [f_norm_executable, "--help"]
        try:
            if hasattr(f_runner, "run") and callable(f_runner.run):
                f_result = f_runner.run(f_argv)
            else:
                f_result = f_runner(f_argv)
        except Exception as f_exc:
            raise BenchmarkProbeError(
                f"EPOCpp executable {f_norm_executable!r} probe could not run: {f_exc}"
            ) from f_exc

        # The runner's result, read as LmpAdapter.probeCapability does
        f_code: Optional[int] = None
        f_text = ""
        if hasattr(f_result, "returncode") or hasattr(f_result, "exit_code"):
            f_raw = getattr(
                f_result, "returncode", getattr(f_result, "exit_code", None)
            )
            f_code = f_raw if type(f_raw) is int else None
            f_text = (
                f"{getattr(f_result, 'stdout', '') or ''}\n"
                f"{getattr(f_result, 'stderr', '') or ''}"
            )
        elif isinstance(f_result, tuple) and len(f_result) >= 2:
            f_code = f_result[0] if type(f_result[0]) is int else None
            f_text = "\n".join(str(f_part) for f_part in f_result[1:])
        elif isinstance(f_result, str):
            f_code, f_text = 0, f_result
        if f_code != 0:
            raise BenchmarkProbeError(
                f"EPOCpp executable {f_norm_executable!r} probe failed with exit code "
                f"{f_code}: {f_text.strip()}"
            )
        if "--io-benchmark" not in f_text:
            raise BenchmarkProbeError(
                f"EPOCpp executable {f_norm_executable!r} has no --io-benchmark option "
                "(it must be built with LSMIO)"
            )
        return CapabilityState.VERIFIED
