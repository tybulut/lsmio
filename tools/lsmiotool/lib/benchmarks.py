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
import hashlib
import os
import re
import stat
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
    DEFAULT_SETUP: str = "NATIVE-M"
    ALLOWED_SETUPS: Tuple[str, ...] = (
        "NATIVE-M",
        "ADIOS-M",
        "PLUGIN-M",
        "ROCKSDB-M",
        "LEVELDB-M",
        "ADIOS",
        "PLUGIN",
        "ROCKSDB",
        "LEVELDB",
        "MANAGER",
    )

    EXECUTABLE_MAP: Dict[str, str] = {
        "NATIVE": "bm_native",
        "NATIVE-M": "bm_native",
        "ADIOS": "bm_adios",
        "ADIOS-M": "bm_adios",
        "PLUGIN": "bm_adios",
        "PLUGIN-M": "bm_adios",
        "ROCKSDB": "bm_rocksdb",
        "ROCKSDB-M": "bm_rocksdb",
        "LEVELDB": "bm_leveldb",
        "LEVELDB-M": "bm_leveldb",
        "MANAGER": "bm_manager",
    }

    BLOCK_SIZE_MAP: Dict[str, Tuple[int, int]] = {
        "64K": (65536, 65536),
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

        if f_setup.endswith("-M"):
            f_argv.extend(["-m", "-g"])

        if f_setup in ("PLUGIN", "PLUGIN-M"):
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
        f_setup: str = "NATIVE-M",
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
        if f_norm_setup.endswith("-M"):
            f_argv.extend(["-m", "-g"])
        if f_norm_setup in ("PLUGIN", "PLUGIN-M"):
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
