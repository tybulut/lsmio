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

import errno
import json
import os
import re
import shlex
import signal
import socket
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from lsmiotool.lib.cli import (
    WorkerExecutableValidationError,
    WorkerExecutableValidator,
)
from lsmiotool.lib.run import Combination



class WorkerError(Exception):
    """Base exception for all worker and process operations."""

    pass


class ModuleRenderError(WorkerError):
    """Raised when module rendering or module token validation fails."""

    pass


class LustreConfigurationError(WorkerError):
    """Raised when Lustre stripe configuration or target validation fails."""

    pass


class LauncherError(WorkerError):
    """Raised when launcher argument construction or execution validation fails."""

    pass


class AllocationControllerError(WorkerError):
    """Raised when allocation controller preflight, execution, or validation fails."""

    pass


class RankWorkerError(WorkerError):
    """Base exception for all rank worker and rank identity operations."""

    pass


class RankClaimError(RankWorkerError):
    """Raised when an exclusive rank claim fails or another worker won the claim race."""

    pass


class RankIdentityError(RankWorkerError):
    """Raised when rank identity resolution fails, environment variables are missing/malformed/out-of-range."""

    pass



class ProcessExecutionError(WorkerError):
    """Raised when a process fails to execute, spawns with error, or encounters infrastructure failures."""

    def __init__(
        self,
        f_message: str,
        f_result: Optional["ProcessResult"] = None,
    ) -> None:
        super().__init__(f_message)
        self.m_result = f_result

    @property
    def result(self) -> Optional["ProcessResult"]:
        return self.m_result


class ProcessSpawnError(ProcessExecutionError):
    """Raised when process invocation fails to spawn (e.g. FileNotFoundError, PermissionError)."""

    pass


class ProcessLoggingError(ProcessExecutionError):
    """Raised when mirroring/logging process output fails during write/flush/fsync."""

    pass


class ProcessTimeoutError(ProcessExecutionError):
    """Raised when process execution exceeds the configured timeout duration."""

    pass


class ProcessResult:
    """Immutable result of a subprocess execution."""

    __slots__ = (
        "m_returncode",
        "m_stdout",
        "m_stderr",
        "m_elapsed_seconds",
        "m_timed_out",
        "m_spawn_error",
        "_frozen",
    )

    def __init__(
        self,
        f_returncode: int,
        f_stdout: str = "",
        f_stderr: str = "",
        f_elapsed_seconds: float = 0.0,
        f_timed_out: bool = False,
        f_spawn_error: Optional[str] = None,
    ) -> None:
        object.__setattr__(self, "m_returncode", int(f_returncode))
        object.__setattr__(self, "m_stdout", str(f_stdout) if f_stdout is not None else "")
        object.__setattr__(self, "m_stderr", str(f_stderr) if f_stderr is not None else "")
        object.__setattr__(self, "m_elapsed_seconds", float(f_elapsed_seconds))
        object.__setattr__(self, "m_timed_out", bool(f_timed_out))
        object.__setattr__(
            self,
            "m_spawn_error",
            str(f_spawn_error) if f_spawn_error is not None else None,
        )
        object.__setattr__(self, "_frozen", True)

    def __setattr__(self, f_name: str, f_value: Any) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"ProcessResult is immutable; cannot set attribute '{f_name}'")
        super().__setattr__(f_name, f_value)

    def __delattr__(self, f_name: str) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"ProcessResult is immutable; cannot delete attribute '{f_name}'")
        super().__delattr__(f_name)

    @property
    def returncode(self) -> int:
        return self.m_returncode

    @property
    def returnCode(self) -> int:
        return self.m_returncode

    @property
    def stdout(self) -> str:
        return self.m_stdout

    @property
    def stderr(self) -> str:
        return self.m_stderr

    @property
    def elapsed_seconds(self) -> float:
        return self.m_elapsed_seconds

    @property
    def elapsedSeconds(self) -> float:
        return self.m_elapsed_seconds

    @property
    def timed_out(self) -> bool:
        return self.m_timed_out

    @property
    def timedOut(self) -> bool:
        return self.m_timed_out

    @property
    def spawn_error(self) -> Optional[str]:
        return self.m_spawn_error

    @property
    def spawnError(self) -> Optional[str]:
        return self.m_spawn_error

    @property
    def is_success(self) -> bool:
        return self.m_returncode == 0 and not self.m_timed_out and self.m_spawn_error is None

    @property
    def isSuccess(self) -> bool:
        return self.is_success

    @property
    def is_signal(self) -> bool:
        return self.m_returncode < 0

    @property
    def isSignal(self) -> bool:
        return self.is_signal

    @property
    def signal_number(self) -> Optional[int]:
        return -self.m_returncode if self.m_returncode < 0 else None

    @property
    def signalNumber(self) -> Optional[int]:
        return self.signal_number

    def toDict(self) -> Dict[str, Any]:
        return {
            "returncode": self.m_returncode,
            "stdout": self.m_stdout,
            "stderr": self.m_stderr,
            "elapsed_seconds": self.m_elapsed_seconds,
            "timed_out": self.m_timed_out,
            "spawn_error": self.m_spawn_error,
            "is_success": self.is_success,
            "is_signal": self.is_signal,
            "signal_number": self.signal_number,
        }

    def __repr__(self) -> str:
        return (
            f"ProcessResult(returncode={self.m_returncode}, "
            f"stdout={self.m_stdout!r}, stderr={self.m_stderr!r}, "
            f"elapsed_seconds={self.m_elapsed_seconds:.4f}, "
            f"timed_out={self.m_timed_out}, spawn_error={self.m_spawn_error!r})"
        )

    def __eq__(self, f_other: Any) -> bool:
        if not isinstance(f_other, ProcessResult):
            return False
        return (
            self.m_returncode == f_other.m_returncode
            and self.m_stdout == f_other.m_stdout
            and self.m_stderr == f_other.m_stderr
            and abs(self.m_elapsed_seconds - f_other.m_elapsed_seconds) < 1e-6
            and self.m_timed_out == f_other.m_timed_out
            and self.m_spawn_error == f_other.m_spawn_error
        )


class ProcessRunner:
    """Failure-preserving process runner using direct subprocess execution.

    Invariants:
    - NEVER uses shell=True or shell pipelines.
    - Preserves exact exit codes (0, positive, and negative signals e.g. -9, -15).
    - Converts spawn and logging failures into explicit exceptions.
    - Flushes and fsyncs log files to guarantee durability.
    """

    def __init__(self) -> None:
        pass

    def run(
        self,
        f_argv: Sequence[str],
        f_cwd: Optional[str] = None,
        f_env: Optional[Mapping[str, str]] = None,
        f_log_path: Optional[str] = None,
        f_mirror_stdout: bool = False,
        f_timeout: Optional[float] = None,
        **f_kwargs: Any,
    ) -> ProcessResult:
        """Execute a command directly without shell interpolation and preserve outcome facts.

        Args:
            f_argv: Sequence of discrete argument strings. Must not be empty or a string.
            f_cwd: Optional working directory path.
            f_env: Optional environment mapping.
            f_log_path: Optional path to log file for mirrored output.
            f_mirror_stdout: If True, mirrors stdout/stderr to standard streams.
            f_timeout: Optional execution timeout in seconds.

        Returns:
            ProcessResult containing returncode, stdout, stderr, elapsed time, timeout state.

        Raises:
            ProcessSpawnError: When binary cannot be spawned (e.g. not found, permissions, invalid argv).
            ProcessLoggingError: When log file cannot be opened, written, flushed, or fsynced.
        """
        # Resolve any kwargs aliases
        if f_cwd is None:
            f_cwd = f_kwargs.get("f_working_dir") or f_kwargs.get("cwd") or f_kwargs.get("working_dir")
        if f_env is None:
            f_env = f_kwargs.get("f_environment") or f_kwargs.get("env") or f_kwargs.get("environment")
        if f_log_path is None:
            f_log_path = f_kwargs.get("f_log") or f_kwargs.get("log_path") or f_kwargs.get("log")
        if not f_mirror_stdout:
            f_mirror_stdout = bool(f_kwargs.get("mirror_stdout", False))
        if f_timeout is None:
            f_timeout = f_kwargs.get("timeout")

        # Validate argv
        if isinstance(f_argv, (str, bytes)):
            raise ProcessSpawnError(
                f"Process argv must be a sequence of arguments, not a string or bytes: {f_argv!r}"
            )
        if not hasattr(f_argv, "__iter__"):
            raise ProcessSpawnError(
                f"Process argv must be an iterable sequence of arguments, got: {type(f_argv).__name__}"
            )

        f_argv_list: List[str] = []
        for f_index, f_arg in enumerate(f_argv):
            if f_arg is None:
                raise ProcessSpawnError(f"Process argv contains None at index {f_index}")
            f_str_arg = str(f_arg)
            if "\0" in f_str_arg:
                raise ProcessSpawnError(
                    f"Process argv element at index {f_index} contains NUL byte: {f_str_arg!r}"
                )
            f_argv_list.append(f_str_arg)

        if not f_argv_list:
            raise ProcessSpawnError("Process argv must be a non-empty sequence of strings")

        # Validate log path if specified
        if f_log_path is not None:
            if not isinstance(f_log_path, str) or not f_log_path.strip():
                raise ProcessLoggingError("Log path must be a non-empty string when specified")
            if "\0" in f_log_path:
                raise ProcessLoggingError("Log path contains NUL byte")

        # Environment preparation
        f_process_env: Optional[Dict[str, str]] = None
        if f_env is not None:
            f_process_env = {str(f_k): str(f_v) for f_k, f_v in f_env.items()}

        # Cwd preparation
        f_process_cwd = str(f_cwd) if f_cwd is not None else None

        f_start_time = time.monotonic()
        f_timed_out = False
        f_stdout_bytes = b""
        f_stderr_bytes = b""
        f_proc: Optional[subprocess.Popen] = None

        try:
            f_proc = subprocess.Popen(
                f_argv_list,
                cwd=f_process_cwd,
                env=f_process_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
            )
        except (FileNotFoundError, PermissionError, NotADirectoryError, OSError) as f_spawn_err:
            raise ProcessSpawnError(
                f"Failed to spawn process '{f_argv_list[0]}': {f_spawn_err}"
            ) from f_spawn_err
        except Exception as f_unexpected_err:
            raise ProcessSpawnError(
                f"Unexpected error spawning process '{f_argv_list[0]}': {f_unexpected_err}"
            ) from f_unexpected_err

        try:
            f_stdout_bytes, f_stderr_bytes = f_proc.communicate(timeout=f_timeout)
        except subprocess.TimeoutExpired:
            f_timed_out = True
            try:
                f_proc.kill()
            except OSError:
                pass
            f_stdout_bytes, f_stderr_bytes = f_proc.communicate()
        except Exception as f_comm_err:
            try:
                f_proc.kill()
            except OSError:
                pass
            f_proc.wait()
            raise ProcessExecutionError(
                f"Communication error during process execution '{f_argv_list[0]}': {f_comm_err}"
            ) from f_comm_err

        f_elapsed_seconds = time.monotonic() - f_start_time
        f_returncode = f_proc.returncode if f_proc.returncode is not None else -1

        f_stdout_str = f_stdout_bytes.decode("utf-8", errors="replace")
        f_stderr_str = f_stderr_bytes.decode("utf-8", errors="replace")

        # Mirror output to standard streams if requested
        if f_mirror_stdout:
            try:
                if f_stdout_str:
                    sys.stdout.write(f_stdout_str)
                    sys.stdout.flush()
                if f_stderr_str:
                    sys.stderr.write(f_stderr_str)
                    sys.stderr.flush()
            except Exception:
                # Do not mask process status on stdout/stderr console mirroring issues
                pass

        # Write output to log file if requested
        if f_log_path is not None:
            try:
                with open(f_log_path, "a", encoding="utf-8", errors="replace") as f_log_file:
                    if f_stdout_str:
                        f_log_file.write(f_stdout_str)
                    if f_stderr_str:
                        f_log_file.write(f_stderr_str)
                    f_log_file.flush()
                    os.fsync(f_log_file.fileno())
            except OSError as f_log_err:
                f_partial_result = ProcessResult(
                    f_returncode=f_returncode,
                    f_stdout=f_stdout_str,
                    f_stderr=f_stderr_str,
                    f_elapsed_seconds=f_elapsed_seconds,
                    f_timed_out=f_timed_out,
                )
                raise ProcessLoggingError(
                    f"Failed to write or flush log file '{f_log_path}': {f_log_err}",
                    f_result=f_partial_result,
                ) from f_log_err

        return ProcessResult(
            f_returncode=f_returncode,
            f_stdout=f_stdout_str,
            f_stderr=f_stderr_str,
            f_elapsed_seconds=f_elapsed_seconds,
            f_timed_out=f_timed_out,
            f_spawn_error=None,
        )


class ModuleSetup:
    """Safe one-time shell renderer and validator for HPC environment modules.

    Invariants:
    - Strictly validates module tokens against '^[A-Za-z0-9][A-Za-z0-9_./+:@-]*$'.
    - Rejects NUL bytes, unprintable control characters, newlines, embedded shell injections, and leading dashes.
    - Employs shlex.quote on every module token.
    - Emits 'module purge' followed by 'module load <quoted_module>' per ordered module if modules present.
    - Emits empty string / empty command list if module inventory is empty (e.g. DEV) without inventing modules.
    - Provides a self-contained one-time preamble suitable for the top-level job script before controller execution.
    - Maintains 100% parity with HpcModules and authoritative site profiles.
    """

    MODULE_SPECIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./+:@-]*$")

    __slots__ = ()

    def __init__(self) -> None:
        pass

    @classmethod
    def validateModule(cls, f_module: Any) -> str:
        """Validate a single module token.

        Args:
            f_module: Module token to validate.

        Returns:
            Validated module string.

        Raises:
            ModuleRenderError: If module token is not a string, contains control characters,
                              NUL bytes, newlines, leading dashes, or invalid characters.
        """
        if not isinstance(f_module, str):
            raise ModuleRenderError(
                f"Module specifier must be a string, got: {type(f_module).__name__}"
            )
        if "\0" in f_module:
            raise ModuleRenderError(f"Module specifier contains NUL byte: {f_module!r}")
        if any(ord(f_c) < 32 or ord(f_c) == 127 for f_c in f_module):
            raise ModuleRenderError(
                f"Module specifier contains control or unprintable characters: {f_module!r}"
            )
        if not cls.MODULE_SPECIFIER_PATTERN.match(f_module):
            raise ModuleRenderError(
                f"Module specifier does not match valid pattern '^[A-Za-z0-9][A-Za-z0-9_./+:@-]*$': {f_module!r}"
            )
        return f_module

    validate_module = validateModule

    @classmethod
    def validateModules(cls, f_modules: Iterable[Any]) -> Tuple[str, ...]:
        """Validate a collection of module tokens.

        Args:
            f_modules: Iterable of module tokens.

        Returns:
            Tuple of validated module strings.

        Raises:
            ModuleRenderError: If collection is invalid or any module token fails validation.
        """
        if f_modules is None:
            raise ModuleRenderError("Module sequence cannot be None")
        if isinstance(f_modules, (str, bytes)):
            raise ModuleRenderError(
                f"Module sequence must be an iterable collection, not {type(f_modules).__name__}"
            )
        if not hasattr(f_modules, "__iter__"):
            raise ModuleRenderError(
                f"Module sequence must be an iterable collection, got {type(f_modules).__name__}"
            )
        f_validated: List[str] = []
        for f_mod in f_modules:
            f_val = cls.validateModule(f_mod)
            f_validated.append(f_val)
        return tuple(f_validated)

    validate_modules = validateModules

    @classmethod
    def _extractModules(cls, f_profile: Any) -> Sequence[str]:
        """Extract sequence of module strings from profile, environment, or sequence."""
        if f_profile is None:
            raise ModuleRenderError("Profile or module sequence cannot be None")

        # 1. SiteProfile or ProfileRecord (has .modules attribute)
        if hasattr(f_profile, "modules") and not isinstance(f_profile, type):
            f_mods = f_profile.modules
            if f_mods is None:
                return ()
            if isinstance(f_mods, (str, bytes)):
                raise ModuleRenderError(
                    f"Profile modules must be a sequence of strings, got {type(f_mods).__name__}"
                )
            return f_mods

        # 2. HpcEnv enum or named object
        if hasattr(f_profile, "name") and isinstance(f_profile.name, str):
            try:
                from lsmiotool.lib.site import EnvironmentResolver
                f_user = os.environ.get("USER") or "user"
                f_home = os.environ.get("HOME") or "/tmp"
                f_resolved = EnvironmentResolver.resolveProfile(
                    f_profile.name, f_user=f_user, f_home=f_home
                )
                return f_resolved.modules
            except Exception as f_err:
                raise ModuleRenderError(
                    f"Failed to resolve site profile for {f_profile!r}: {f_err}"
                ) from f_err

        # 3. String site name
        if isinstance(f_profile, str):
            try:
                from lsmiotool.lib.site import EnvironmentResolver
                f_user = os.environ.get("USER") or "user"
                f_home = os.environ.get("HOME") or "/tmp"
                f_resolved = EnvironmentResolver.resolveProfile(
                    f_profile, f_user=f_user, f_home=f_home
                )
                return f_resolved.modules
            except Exception:
                raise ModuleRenderError(
                    f"Cannot resolve string {f_profile!r} as a site profile and string is not a module sequence"
                )

        # 4. Sequence of strings
        if isinstance(f_profile, (list, tuple)) or (
            isinstance(f_profile, Sequence) and not isinstance(f_profile, (str, bytes))
        ):
            return f_profile

        raise ModuleRenderError(
            f"Unsupported profile or module container type: {type(f_profile).__name__}"
        )

    @classmethod
    def renderCommands(
        cls,
        f_profile: Union[Any, Sequence[str]],
    ) -> List[str]:
        """Render ordered list of shell commands for module environment setup.

        Args:
            f_profile: SiteProfile, ProfileRecord, HpcEnv, site name str, or sequence of module names.

        Returns:
            List of shell command strings (['module purge', 'module load ...'] or []).

        Raises:
            ModuleRenderError: If any module specifier is invalid or profile resolution fails.
        """
        f_raw_modules = cls._extractModules(f_profile)
        if not f_raw_modules:
            return []

        f_validated = cls.validateModules(f_raw_modules)
        if not f_validated:
            return []

        f_commands: List[str] = ["module purge"]
        for f_mod in f_validated:
            f_quoted = shlex.quote(f_mod)
            f_commands.append(f"module load {f_quoted}")
        return f_commands

    render_commands = renderCommands

    @classmethod
    def renderScript(
        cls,
        f_profile: Union[Any, Sequence[str]],
    ) -> str:
        """Render self-contained shell snippet for module environment setup.

        Args:
            f_profile: SiteProfile, ProfileRecord, HpcEnv, site name str, or sequence of module names.

        Returns:
            Multiline shell script snippet (or empty string if no modules).

        Raises:
            ModuleRenderError: If any module specifier is invalid or profile resolution fails.
        """
        f_commands = cls.renderCommands(f_profile)
        if not f_commands:
            return ""
        return "\n".join(f_commands)

    render_script = renderScript

    @classmethod
    def render(
        cls,
        f_profile: Union[Any, Sequence[str]],
    ) -> str:
        """Render self-contained shell snippet for module environment setup.

        Alias for renderScript.

        Args:
            f_profile: SiteProfile, ProfileRecord, HpcEnv, site name str, or sequence of module names.

        Returns:
            Multiline shell script snippet (or empty string if no modules).
        """
        return cls.renderScript(f_profile)


class LustreConfigurator:
    """Contained Lustre file system stripe configurator and validator.

    Invariants:
    - Generates direct 'lfs setstripe -S <block_size> -c <stripe_count> [ -p <pool> ] <target_dir>' argv.
    - Validates target directory containment under point private data directory (data/c<stripe>/b<block>).
    - Strictly rejects path traversal ('..'), symlinks, root escapes, and non-contained paths.
    - Resolves site-specific Lustre pools (e.g. Viking2 scratch.disk / scratch.flash per storage class),
      omitting -p flag for sites without pool configuration (Viking, Isambard, Archer2, Dev).
    - Treats runner nonzero exit codes and missing binaries as fatal infrastructure errors,
      raising LustreConfigurationError.
    """

    POOL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
    BLOCK_SIZE_PATTERN = re.compile(r"^[0-9]+[KMGkmg]?$")

    __slots__ = ()

    def __init__(self) -> None:
        pass

    @classmethod
    def _extractCombination(cls, f_combination: Any) -> Tuple[int, str]:
        """Extract validated (stripe_count, block_size) tuple from various combination descriptors.

        Args:
            f_combination: Combination instance, tuple/list, mapping, or string descriptor.

        Returns:
            Tuple of (stripe_count: int, block_size: str).

        Raises:
            LustreConfigurationError: If combination descriptor is invalid or cannot be parsed.
        """
        if f_combination is None:
            raise LustreConfigurationError("Combination descriptor cannot be None")

        f_stripe: Any = None
        f_block: Any = None

        if hasattr(f_combination, "stripe_count") and hasattr(f_combination, "block_size"):
            f_stripe = f_combination.stripe_count
            f_block = f_combination.block_size
        elif hasattr(f_combination, "stripe") and hasattr(f_combination, "block"):
            f_stripe = f_combination.stripe
            f_block = f_combination.block
        elif isinstance(f_combination, (tuple, list)) and len(f_combination) == 2:
            f_stripe = f_combination[0]
            f_block = f_combination[1]
        elif isinstance(f_combination, dict):
            f_stripe = f_combination.get("stripe_count") or f_combination.get("stripe")
            f_block = f_combination.get("block_size") or f_combination.get("block")
        elif isinstance(f_combination, str):
            f_match = re.match(r"^c?(\d+)[_/b-]b?([0-9]+[KMGkmg]?)$", f_combination.strip())
            if f_match:
                f_stripe = int(f_match.group(1))
                f_block = f_match.group(2)
            else:
                raise LustreConfigurationError(
                    f"Cannot parse combination string descriptor: {f_combination!r}"
                )
        else:
            raise LustreConfigurationError(
                f"Unsupported combination descriptor type: {type(f_combination).__name__}"
            )

        # Validate stripe count
        if isinstance(f_stripe, str):
            try:
                f_stripe = int(f_stripe)
            except ValueError:
                raise LustreConfigurationError(
                    f"Stripe count must be a positive integer, got string: {f_stripe!r}"
                )
        if isinstance(f_stripe, bool) or not isinstance(f_stripe, int) or f_stripe <= 0:
            raise LustreConfigurationError(
                f"Stripe count must be a positive integer, got: {f_stripe!r}"
            )

        # Validate block size
        if not isinstance(f_block, str) or not f_block.strip():
            raise LustreConfigurationError(
                f"Block size must be a non-empty string, got: {f_block!r}"
            )
        f_block_str = f_block.strip()
        if "\0" in f_block_str or not cls.BLOCK_SIZE_PATTERN.match(f_block_str):
            raise LustreConfigurationError(
                f"Block size '{f_block_str}' does not match pattern '^[0-9]+[KMGkmg]?$'"
            )

        return f_stripe, f_block_str

    @classmethod
    def resolvePool(
        cls,
        f_profile: Any,
        f_storage_class: Optional[Any] = None,
        **f_kwargs: Any,
    ) -> Optional[str]:
        """Resolve Lustre storage pool name from site profile and storage class.

        Args:
            f_profile: SiteProfile, ProfileRecord, dict, site name str, or pool name str.
            f_storage_class: StorageClass enum, 'hdd', 'ssd', or None (defaults to HDD).

        Returns:
            Pool name string (e.g. 'scratch.disk', 'scratch.flash') or None if site has no pools.

        Raises:
            LustreConfigurationError: If pool token or storage class is invalid.
        """
        if f_profile is None:
            return None

        # Resolve storage class
        if f_storage_class is None:
            f_storage_class = f_kwargs.get("storage_class") or f_kwargs.get("storage")

        f_storage_key = "hdd"
        if f_storage_class is not None:
            if hasattr(f_storage_class, "value"):
                f_storage_key = str(f_storage_class.value).lower().strip()
            else:
                f_storage_key = str(f_storage_class).lower().strip()

        if f_storage_key not in ("hdd", "ssd"):
            raise LustreConfigurationError(
                f"Invalid storage class for pool resolution: {f_storage_class!r}"
            )

        f_pool_val: Optional[str] = None

        # 1. SiteProfile or object with getLustrePool method
        if hasattr(f_profile, "getLustrePool") and callable(f_profile.getLustrePool):
            try:
                from lsmiotool.lib.site import StorageClass
                f_sc_enum = StorageClass.SSD if f_storage_key == "ssd" else StorageClass.HDD
                f_pool_val = f_profile.getLustrePool(f_sc_enum)
            except Exception:
                f_pool_val = f_profile.getLustrePool(f_storage_key)

        # 2. Object with lustre_pools property / attribute
        elif hasattr(f_profile, "lustre_pools"):
            f_pools = f_profile.lustre_pools
            if isinstance(f_pools, dict):
                f_pool_val = (
                    f_pools.get(f_storage_key)
                    or f_pools.get(f_storage_key.upper())
                )
                if f_pool_val is None:
                    try:
                        from lsmiotool.lib.site import StorageClass
                        f_sc_enum = StorageClass.SSD if f_storage_key == "ssd" else StorageClass.HDD
                        f_pool_val = f_pools.get(f_sc_enum)
                    except Exception:
                        pass

        # 3. Object with pools property / attribute
        elif hasattr(f_profile, "pools"):
            f_pools = f_profile.pools
            if isinstance(f_pools, dict):
                f_pool_val = (
                    f_pools.get(f_storage_key)
                    or f_pools.get(f_storage_key.upper())
                )

        # 4. String site name or pool name
        elif isinstance(f_profile, str):
            try:
                from lsmiotool.lib.site import EnvironmentResolver, StorageClass
                f_user = os.environ.get("USER") or "user"
                f_home = os.environ.get("HOME") or "/tmp"
                f_resolved = EnvironmentResolver.resolveProfile(
                    f_profile, f_user=f_user, f_home=f_home
                )
                f_sc_enum = StorageClass.SSD if f_storage_key == "ssd" else StorageClass.HDD
                f_pool_val = f_resolved.getLustrePool(f_sc_enum)
            except Exception:
                # If string is not a recognized site name, check if it's a direct pool name
                if cls.POOL_NAME_PATTERN.match(f_profile):
                    f_pool_val = f_profile
                else:
                    raise LustreConfigurationError(
                        f"Cannot resolve site profile or pool name from string: {f_profile!r}"
                    )

        # 5. Dict with lustre_pools or pools
        elif isinstance(f_profile, dict):
            f_pools = f_profile.get("lustre_pools") or f_profile.get("pools")
            if isinstance(f_pools, dict):
                f_pool_val = (
                    f_pools.get(f_storage_key)
                    or f_pools.get(f_storage_key.upper())
                )

        else:
            raise LustreConfigurationError(
                f"Unsupported profile container type for pool resolution: {type(f_profile).__name__}"
            )

        if f_pool_val is None:
            return None

        f_pool_str = str(f_pool_val).strip()
        if not f_pool_str:
            return None

        if "\0" in f_pool_str or not cls.POOL_NAME_PATTERN.match(f_pool_str):
            raise LustreConfigurationError(
                f"Lustre pool name '{f_pool_str}' contains invalid characters (must match '^[A-Za-z0-9_.-]+$')"
            )

        return f_pool_str

    resolve_pool = resolvePool

    @classmethod
    def validateTargetDir(
        cls,
        f_target_dir: Any,
        f_combination: Optional[Any] = None,
    ) -> str:
        """Validate target directory containment and path safety.

        Invariants:
        - Must be a non-empty string and absolute path.
        - Must not contain NUL bytes or path traversal ('..').
        - Must not be root filesystem ('/').
        - Must not be a symlink or contain symlink components.
        - Must be contained under point data directory ('data/c<stripe>/b<block>').

        Args:
            f_target_dir: Target directory path.
            f_combination: Optional combination descriptor to verify stripe/block subpath match.

        Returns:
            Normalized absolute path string.

        Raises:
            LustreConfigurationError: If any validation rule is violated.
        """
        if not isinstance(f_target_dir, str) or not f_target_dir.strip():
            raise LustreConfigurationError("Target directory must be a non-empty string")
        if "\0" in f_target_dir:
            raise LustreConfigurationError("Target directory path contains NUL byte")

        # Path traversal checks
        f_raw_parts = f_target_dir.replace("\\", "/").split("/")
        f_norm_parts = os.path.normpath(f_target_dir).split(os.sep)
        if ".." in f_raw_parts or ".." in f_norm_parts:
            raise LustreConfigurationError(
                f"Path traversal '..' detected in target directory: {f_target_dir!r}"
            )

        if not os.path.isabs(f_target_dir) and not f_target_dir.startswith("/"):
            raise LustreConfigurationError(
                f"Target directory must be an absolute path, got: {f_target_dir!r}"
            )

        f_abs_path = os.path.abspath(os.path.normpath(f_target_dir))
        if f_abs_path in ("/", ""):
            raise LustreConfigurationError("Target directory cannot be root filesystem")

        # Symlink detection
        if os.path.islink(f_abs_path):
            raise LustreConfigurationError(
                f"Target directory is a symlink: '{f_abs_path}'"
            )

        f_curr = f_abs_path
        while f_curr and f_curr != "/":
            if os.path.islink(f_curr):
                raise LustreConfigurationError(
                    f"Target directory path contains symlink component: '{f_curr}'"
                )
            f_parent = os.path.dirname(f_curr)
            if f_parent == f_curr:
                break
            f_curr = f_parent

        # Point data directory containment
        if f_combination is not None:
            f_stripe, f_block = cls._extractCombination(f_combination)
            f_expected_pattern = rf"(?:^|/)data/c{f_stripe}/b{f_block}(?:/.*)?$"
            if not re.search(f_expected_pattern, f_abs_path):
                raise LustreConfigurationError(
                    f"Target directory '{f_abs_path}' is not contained under expected point data directory 'data/c{f_stripe}/b{f_block}'"
                )
        else:
            f_general_pattern = r"(?:^|/)data/c\d+/b[0-9]+[KMGkmg]?(?:/.*)?$"
            if not re.search(f_general_pattern, f_abs_path):
                raise LustreConfigurationError(
                    f"Target directory '{f_abs_path}' is not contained under a point data directory ('data/c<stripe>/b<block>')"
                )

        return f_abs_path

    validate_target_dir = validateTargetDir

    @classmethod
    def buildArgv(
        cls,
        f_profile: Any,
        f_combination: Any,
        f_target_dir: str,
        f_storage_class: Optional[Any] = None,
        **f_kwargs: Any,
    ) -> List[str]:
        """Construct the direct 'lfs setstripe' argv sequence.

        Args:
            f_profile: SiteProfile, ProfileRecord, HpcEnv, site name str, or None.
            f_combination: Combination instance, (stripe, block) tuple, or combination descriptor.
            f_target_dir: Validated target data directory.
            f_storage_class: Optional storage class (HDD default or SSD).

        Returns:
            List of argument strings: ['lfs', 'setstripe', '-S', '<block>', '-c', '<stripe>', (optional '-p', '<pool>'), '<target_dir>']

        Raises:
            LustreConfigurationError: If any argument validation fails.
        """
        f_stripe, f_block = cls._extractCombination(f_combination)
        f_valid_target = cls.validateTargetDir(f_target_dir, f_combination=f_combination)
        f_pool = cls.resolvePool(
            f_profile, f_storage_class=f_storage_class, **f_kwargs
        )

        f_argv: List[str] = [
            "lfs",
            "setstripe",
            "-S",
            f_block,
            "-c",
            str(f_stripe),
        ]
        if f_pool:
            f_argv.extend(["-p", f_pool])
        f_argv.append(f_valid_target)

        return f_argv

    build_argv = buildArgv
    argv = buildArgv

    @classmethod
    def configure(
        cls,
        f_profile: Any,
        f_combination: Any,
        f_target_dir: str,
        f_runner: Optional[ProcessRunner] = None,
        f_storage_class: Optional[Any] = None,
        **f_kwargs: Any,
    ) -> ProcessResult:
        """Execute 'lfs setstripe' via ProcessRunner with fail-fast fatal semantics.

        Args:
            f_profile: SiteProfile, ProfileRecord, HpcEnv, site name str, or None.
            f_combination: Combination instance, (stripe, block) tuple, or combination descriptor.
            f_target_dir: Validated target data directory.
            f_runner: Optional ProcessRunner instance (creates new instance if None).
            f_storage_class: Optional storage class (HDD default or SSD).

        Returns:
            ProcessResult on successful zero-exit execution.

        Raises:
            LustreConfigurationError: If command fails, exits non-zero, or cannot be spawned.
        """
        if f_runner is None:
            f_runner = f_kwargs.get("runner")
        if f_runner is None:
            f_runner = ProcessRunner()

        f_argv = cls.buildArgv(
            f_profile,
            f_combination,
            f_target_dir,
            f_storage_class=f_storage_class,
            **f_kwargs,
        )

        try:
            f_result = f_runner.run(f_argv)
        except ProcessSpawnError as f_spawn_err:
            raise LustreConfigurationError(
                f"Failed to spawn Lustre stripe configuration command '{f_argv[0]}': {f_spawn_err}"
            ) from f_spawn_err
        except ProcessExecutionError as f_exec_err:
            raise LustreConfigurationError(
                f"Lustre stripe configuration execution error: {f_exec_err}"
            ) from f_exec_err
        except Exception as f_unexpected_err:
            raise LustreConfigurationError(
                f"Unexpected error executing Lustre stripe configuration: {f_unexpected_err}"
            ) from f_unexpected_err

        if not f_result.is_success:
            f_err_msg = (
                f_result.stderr.strip()
                or f_result.stdout.strip()
                or f"process exited with return code {f_result.returncode}"
            )
            raise LustreConfigurationError(
                f"Lustre stripe configuration command failed ({f_err_msg}) with exit code {f_result.returncode}"
            )

        return f_result


class Launcher:
    """Scheduler-specific MPI job launcher and command builder.

    Invariants:
    - Builds direct execution argv for shared benchmark workloads and rank workers.
    - Slurm (SchedulerKind.SLURM):
        ['srun', '--export=ALL', '-n', str(point.tasks), '-N', str(point.nodes)]
        Appends ['-p', partition] if site profile defines a partition (e.g. Archer2 '-p standard').
    - PBS (SchedulerKind.PBS):
        ['aprun', '-n', str(point.tasks), '-N', str(point.ppn)]
    - Direct / Fake (SchedulerKind.FAKE / SchedulerKind.DIRECT):
        Direct execution without launcher prefix.
    - Shared mode appends benchmark argv tokens verbatim.
    - Rank worker mode appends:
        [worker_executable, 'rank', manifest_path, point_id, combination_desc]
    - Executes via ProcessRunner directly (shell=False) and preserves exact return codes / signals.
    - Launcher does NOT validate evidence files, check cardinality, or parse rank results (controller-owned).
    """

    __slots__ = ()

    def __init__(self) -> None:
        pass

    @classmethod
    def _extractPoint(cls, f_point: Any) -> Tuple[int, int, int]:
        """Extract validated (tasks: int, ppn: int, nodes: int) from scale point.

        Args:
            f_point: ScalePoint instance, dict, tuple/list, or object with tasks/ppn/nodes.

        Returns:
            Tuple of (tasks: int, ppn: int, nodes: int).

        Raises:
            LauncherError: If point is invalid, non-positive, or tasks/ppn/nodes cannot be determined.
        """
        if f_point is None:
            raise LauncherError("Scale point cannot be None")

        f_tasks: Any = None
        f_ppn: Any = None
        f_nodes: Any = None

        if hasattr(f_point, "tasks") and hasattr(f_point, "ppn") and hasattr(f_point, "nodes"):
            f_tasks = f_point.tasks
            f_ppn = f_point.ppn
            f_nodes = f_point.nodes
        elif hasattr(f_point, "task_count") and hasattr(f_point, "tasks_per_node"):
            f_tasks = f_point.task_count
            f_ppn = f_point.tasks_per_node
            f_nodes = getattr(f_point, "node_count", None)
        elif isinstance(f_point, dict):
            f_tasks = f_point.get("tasks") or f_point.get("task_count")
            f_ppn = f_point.get("ppn") or f_point.get("tasks_per_node") or 1
            f_nodes = f_point.get("nodes") or f_point.get("node_count")
        elif isinstance(f_point, (tuple, list)):
            if len(f_point) == 3:
                f_tasks, f_ppn, f_nodes = f_point
            elif len(f_point) == 2:
                f_tasks, f_ppn = f_point
            elif len(f_point) == 1:
                f_tasks = f_point[0]
                f_ppn = 1
            else:
                raise LauncherError(
                    f"Scale point tuple/list must have 1, 2, or 3 elements, got {len(f_point)}"
                )
        elif isinstance(f_point, int):
            f_tasks = f_point
            f_ppn = 1
        else:
            raise LauncherError(
                f"Unsupported scale point type: {type(f_point).__name__}"
            )

        if isinstance(f_tasks, bool) or not isinstance(f_tasks, int) or f_tasks <= 0:
            raise LauncherError(f"Scale point tasks must be a positive integer, got: {f_tasks!r}")
        if isinstance(f_ppn, bool) or not isinstance(f_ppn, int) or f_ppn <= 0:
            raise LauncherError(f"Scale point ppn must be a positive integer, got: {f_ppn!r}")

        if f_nodes is None:
            f_nodes = max(1, f_tasks // f_ppn)

        if isinstance(f_nodes, bool) or not isinstance(f_nodes, int) or f_nodes <= 0:
            raise LauncherError(f"Scale point nodes must be a positive integer, got: {f_nodes!r}")

        return f_tasks, f_ppn, f_nodes

    @classmethod
    def _resolveSchedulerAndPartition(
        cls,
        f_profile: Any,
        f_point: Optional[Any] = None,
    ) -> Tuple[Any, Optional[str]]:
        """Resolve (SchedulerKind, partition: Optional[str]) from profile and optional point.

        Args:
            f_profile: SiteProfile, ProfileRecord, SchedulerKind, LauncherPolicy, dict, str, or None.
            f_point: Optional scale point for shape-specific resource lookup.

        Returns:
            Tuple of (SchedulerKind, Optional[str] partition name).

        Raises:
            LauncherError: If profile or scheduler cannot be resolved.
        """
        from lsmiotool.lib.site import SchedulerKind, LauncherPolicy, SiteProfile, EnvironmentResolver

        if f_profile is None:
            return SchedulerKind.FAKE, None

        if isinstance(f_profile, SchedulerKind):
            return f_profile, None

        if isinstance(f_profile, LauncherPolicy):
            f_kind_str = f_profile.kind.lower().strip()
            if f_kind_str in ("srun", "slurm"):
                return SchedulerKind.SLURM, None
            elif f_kind_str in ("aprun", "pbs"):
                return SchedulerKind.PBS, None
            elif f_kind_str in ("fake", "direct"):
                return SchedulerKind.FAKE, None
            else:
                raise LauncherError(f"Unknown launcher policy kind: {f_profile.kind!r}")

        # Check LaunchMode enum if passed
        if hasattr(f_profile, "value") and hasattr(f_profile, "name"):
            f_enum_val = str(f_profile.value).lower().strip()
            if f_enum_val in ("slurm", "srun"):
                return SchedulerKind.SLURM, None
            elif f_enum_val in ("pbs", "aprun"):
                return SchedulerKind.PBS, None
            elif f_enum_val in ("fake", "direct"):
                return SchedulerKind.FAKE, None

        f_resolved_profile: Any = f_profile

        # If profile is string site name or scheduler name
        if isinstance(f_profile, str):
            f_norm_str = f_profile.strip().lower()
            if f_norm_str in ("slurm", "srun"):
                return SchedulerKind.SLURM, None
            elif f_norm_str in ("pbs", "aprun"):
                return SchedulerKind.PBS, None
            elif f_norm_str in ("fake", "direct"):
                return SchedulerKind.FAKE, None
            else:
                try:
                    f_user = os.environ.get("USER") or "user"
                    f_home = os.environ.get("HOME") or "/tmp"
                    f_resolved_profile = EnvironmentResolver.resolveProfile(
                        f_profile, f_user=f_user, f_home=f_home
                    )
                except Exception as f_err:
                    raise LauncherError(
                        f"Failed to resolve site profile '{f_profile}': {f_err}"
                    ) from f_err

        # Extract scheduler
        f_scheduler: Optional[SchedulerKind] = None
        if hasattr(f_resolved_profile, "scheduler"):
            f_raw_sched = f_resolved_profile.scheduler
            if isinstance(f_raw_sched, SchedulerKind):
                f_scheduler = f_raw_sched
            elif isinstance(f_raw_sched, str):
                f_raw_sched_lower = f_raw_sched.lower().strip()
                if f_raw_sched_lower in ("slurm", "srun"):
                    f_scheduler = SchedulerKind.SLURM
                elif f_raw_sched_lower in ("pbs", "aprun"):
                    f_scheduler = SchedulerKind.PBS
                elif f_raw_sched_lower in ("fake", "direct"):
                    f_scheduler = SchedulerKind.FAKE
        elif isinstance(f_resolved_profile, dict):
            f_raw_sched = f_resolved_profile.get("scheduler") or f_resolved_profile.get("launcher")
            if isinstance(f_raw_sched, str):
                f_raw_sched_lower = f_raw_sched.lower().strip()
                if f_raw_sched_lower in ("slurm", "srun"):
                    f_scheduler = SchedulerKind.SLURM
                elif f_raw_sched_lower in ("pbs", "aprun"):
                    f_scheduler = SchedulerKind.PBS
                elif f_raw_sched_lower in ("fake", "direct"):
                    f_scheduler = SchedulerKind.FAKE
            elif isinstance(f_raw_sched, SchedulerKind):
                f_scheduler = f_raw_sched

        if f_scheduler is None:
            raise LauncherError(
                f"Cannot determine scheduler from profile: {f_profile!r}"
            )

        # Extract partition if Slurm
        f_partition: Optional[str] = None
        if f_scheduler == SchedulerKind.SLURM:
            # Check shape from f_point
            f_shape = "small"
            if f_point is not None:
                try:
                    _, f_ppn, _ = cls._extractPoint(f_point)
                    if f_ppn == 4:
                        f_shape = "large"
                except Exception:
                    pass

            if hasattr(f_resolved_profile, "resources") and isinstance(f_resolved_profile.resources, dict):
                f_res_obj = f_resolved_profile.resources.get(f_shape) or f_resolved_profile.resources.get("small")
                if f_res_obj is not None:
                    if hasattr(f_res_obj, "partition") and f_res_obj.partition:
                        f_partition = str(f_res_obj.partition).strip()
                    elif isinstance(f_res_obj, dict) and f_res_obj.get("partition"):
                        f_partition = str(f_res_obj["partition"]).strip()
            elif isinstance(f_resolved_profile, dict):
                f_res_dict = f_resolved_profile.get("resources", {})
                if isinstance(f_res_dict, dict):
                    f_shp_dict = f_res_dict.get(f_shape) or f_res_dict.get("small") or {}
                    if isinstance(f_shp_dict, dict) and f_shp_dict.get("partition"):
                        f_partition = str(f_shp_dict["partition"]).strip()

            if not f_partition and hasattr(f_resolved_profile, "partition") and f_resolved_profile.partition:
                f_partition = str(f_resolved_profile.partition).strip()
            if not f_partition and isinstance(f_resolved_profile, dict) and f_resolved_profile.get("partition"):
                f_partition = str(f_resolved_profile["partition"]).strip()

            # Profile name check fallback
            if not f_partition and hasattr(f_resolved_profile, "name"):
                if str(f_resolved_profile.name).upper() == "ARCHER2":
                    f_partition = "standard"

        return f_scheduler, f_partition

    @classmethod
    def _extractCommandArgv(cls, f_command: Any) -> List[str]:
        """Extract validated argv tokens list from benchmark command or sequence.

        Args:
            f_command: BenchmarkCommand instance, sequence of strings, or non-empty string.

        Returns:
            List of discrete string argument tokens.

        Raises:
            LauncherError: If command argv is empty, invalid, or contains NUL bytes.
        """
        if f_command is None:
            raise LauncherError("Command cannot be None")

        f_raw_argv: Any = None
        if hasattr(f_command, "argv"):
            f_raw_argv = f_command.argv
        elif hasattr(f_command, "arguments"):
            f_raw_argv = f_command.arguments
        elif isinstance(f_command, (list, tuple)):
            f_raw_argv = f_command
        elif isinstance(f_command, str):
            if not f_command.strip():
                raise LauncherError("Command string cannot be empty")
            f_raw_argv = [f_command]
        else:
            raise LauncherError(
                f"Unsupported command container type: {type(f_command).__name__}"
            )

        if not f_raw_argv:
            raise LauncherError("Command argv cannot be empty")

        f_argv_list: List[str] = []
        for f_idx, f_arg in enumerate(f_raw_argv):
            if f_arg is None:
                raise LauncherError(f"Command argv contains None at index {f_idx}")
            f_str_arg = str(f_arg)
            if "\0" in f_str_arg:
                raise LauncherError(
                    f"Command argv element at index {f_idx} contains NUL byte: {f_str_arg!r}"
                )
            f_argv_list.append(f_str_arg)

        if not f_argv_list:
            raise LauncherError("Command argv cannot be empty")

        return f_argv_list

    @classmethod
    def _validateWorkerExecutable(cls, f_worker_executable: Any) -> str:
        """Validate worker executable path string."""
        if not isinstance(f_worker_executable, str) or not f_worker_executable.strip():
            raise LauncherError(
                f"Worker executable must be a non-empty string, got: {f_worker_executable!r}"
            )
        f_worker_str = f_worker_executable.strip()
        if "\0" in f_worker_str:
            raise LauncherError("Worker executable path contains NUL byte")
        return f_worker_str

    @classmethod
    def _validateManifestPath(cls, f_manifest_path: Any) -> str:
        """Validate manifest path string."""
        if not isinstance(f_manifest_path, str) or not f_manifest_path.strip():
            raise LauncherError(
                f"Manifest path must be a non-empty string, got: {f_manifest_path!r}"
            )
        f_manifest_str = f_manifest_path.strip()
        if "\0" in f_manifest_str:
            raise LauncherError("Manifest path contains NUL byte")
        return f_manifest_str

    @classmethod
    def _validatePointId(cls, f_point_id: Any) -> str:
        """Validate scale point identifier string."""
        if f_point_id is None:
            raise LauncherError("Point ID cannot be None")
        f_pt_str = str(f_point_id).strip()
        if not f_pt_str:
            raise LauncherError("Point ID cannot be empty")
        if "\0" in f_pt_str:
            raise LauncherError("Point ID contains NUL byte")
        return f_pt_str

    @classmethod
    def _validateCombinationDesc(cls, f_combination_desc: Any) -> str:
        """Validate combination descriptor string."""
        if f_combination_desc is None:
            raise LauncherError("Combination descriptor cannot be None")

        if hasattr(f_combination_desc, "name"):
            f_comb_str = str(f_combination_desc.name).strip()
        elif isinstance(f_combination_desc, (tuple, list)) and len(f_combination_desc) == 2:
            f_comb_str = f"c{f_combination_desc[0]}_b{f_combination_desc[1]}"
        elif isinstance(f_combination_desc, dict):
            f_stripe = f_combination_desc.get("stripe") or f_combination_desc.get("stripe_count")
            f_block = f_combination_desc.get("block") or f_combination_desc.get("block_size")
            f_comb_str = f"c{f_stripe}_b{f_block}"
        elif isinstance(f_combination_desc, str):
            f_comb_str = f_combination_desc.strip()
        else:
            raise LauncherError(
                f"Unsupported combination descriptor type: {type(f_combination_desc).__name__}"
            )

        if not f_comb_str:
            raise LauncherError("Combination descriptor cannot be empty")
        if "\0" in f_comb_str:
            raise LauncherError("Combination descriptor contains NUL byte")
        return f_comb_str

    @classmethod
    def buildSharedArgv(
        cls,
        f_profile: Any,
        f_point: Any,
        f_command: Any,
    ) -> List[str]:
        """Construct discrete argv for launching shared benchmark MPI commands.

        Args:
            f_profile: SiteProfile, ProfileRecord, SchedulerKind, LauncherPolicy, or str.
            f_point: ScalePoint, dict, or tuple/list defining (tasks, ppn, nodes).
            f_command: BenchmarkCommand, sequence of tokens, or non-empty string.

        Returns:
            List of argument strings (e.g. ['srun', '--export=ALL', '-n', '8', '-N', '8', 'ior', ...]).

        Raises:
            LauncherError: If argument construction or validation fails.
        """
        from lsmiotool.lib.site import SchedulerKind

        f_scheduler, f_partition = cls._resolveSchedulerAndPartition(f_profile, f_point)
        f_tasks, f_ppn, f_nodes = cls._extractPoint(f_point)
        f_cmd_argv = cls._extractCommandArgv(f_command)

        if f_scheduler == SchedulerKind.SLURM:
            f_argv: List[str] = [
                "srun",
                "--export=ALL",
                "-n",
                str(f_tasks),
                "-N",
                str(f_nodes),
            ]
            if f_partition:
                f_argv.extend(["-p", f_partition])
            f_argv.extend(f_cmd_argv)
            return f_argv

        elif f_scheduler == SchedulerKind.PBS:
            f_argv = [
                "aprun",
                "-n",
                str(f_tasks),
                "-N",
                str(f_ppn),
            ]
            f_argv.extend(f_cmd_argv)
            return f_argv

        elif f_scheduler == SchedulerKind.FAKE:
            return list(f_cmd_argv)

        else:
            raise LauncherError(f"Unsupported scheduler kind: {f_scheduler}")

    build_shared_argv = buildSharedArgv

    @classmethod
    def buildRankWorkerArgv(
        cls,
        f_profile: Any,
        f_point: Any,
        f_worker_executable: str,
        f_manifest_path: str,
        f_point_id: Any,
        f_combination_desc: Any,
    ) -> List[str]:
        """Construct discrete argv for launching distributed rank worker processes.

        Args:
            f_profile: SiteProfile, ProfileRecord, SchedulerKind, LauncherPolicy, or str.
            f_point: ScalePoint, dict, or tuple/list defining (tasks, ppn, nodes).
            f_worker_executable: Path to worker binary (e.g. lsmioworker).
            f_manifest_path: Path to immutable manifest.json.
            f_point_id: Point identifier string or index.
            f_combination_desc: Combination descriptor (e.g. 'c16_b8M' or Combination instance).

        Returns:
            List of argument strings (e.g. ['srun', ..., worker, 'rank', manifest, point_id, combination]).

        Raises:
            LauncherError: If argument construction or validation fails.
        """
        from lsmiotool.lib.site import SchedulerKind

        f_scheduler, f_partition = cls._resolveSchedulerAndPartition(f_profile, f_point)
        f_tasks, f_ppn, f_nodes = cls._extractPoint(f_point)
        f_worker = cls._validateWorkerExecutable(f_worker_executable)
        f_manifest = cls._validateManifestPath(f_manifest_path)
        f_point_str = cls._validatePointId(f_point_id)
        f_comb_str = cls._validateCombinationDesc(f_combination_desc)

        f_tail: List[str] = [
            f_worker,
            "rank",
            f_manifest,
            f_point_str,
            f_comb_str,
        ]

        if f_scheduler == SchedulerKind.SLURM:
            f_argv: List[str] = [
                "srun",
                "--export=ALL",
                "-n",
                str(f_tasks),
                "-N",
                str(f_nodes),
            ]
            if f_partition:
                f_argv.extend(["-p", f_partition])
            f_argv.extend(f_tail)
            return f_argv

        elif f_scheduler == SchedulerKind.PBS:
            f_argv = [
                "aprun",
                "-n",
                str(f_tasks),
                "-N",
                str(f_ppn),
            ]
            f_argv.extend(f_tail)
            return f_argv

        elif f_scheduler == SchedulerKind.FAKE:
            return list(f_tail)

        else:
            raise LauncherError(f"Unsupported scheduler kind: {f_scheduler}")

    build_rank_worker_argv = buildRankWorkerArgv

    @classmethod
    def launchShared(
        cls,
        f_profile: Any,
        f_point: Any,
        f_command: Any,
        f_runner: Optional[ProcessRunner] = None,
        f_cwd: Optional[str] = None,
        f_env: Optional[Mapping[str, str]] = None,
        f_log_path: Optional[str] = None,
        f_mirror_stdout: bool = False,
        f_timeout: Optional[float] = None,
        **f_kwargs: Any,
    ) -> ProcessResult:
        """Execute shared benchmark MPI command via ProcessRunner and preserve exact return status.

        Args:
            f_profile: SiteProfile, ProfileRecord, SchedulerKind, LauncherPolicy, or str.
            f_point: ScalePoint, dict, or tuple/list defining (tasks, ppn, nodes).
            f_command: BenchmarkCommand, sequence of tokens, or non-empty string.
            f_runner: Optional ProcessRunner instance (defaults to new ProcessRunner()).
            f_cwd: Optional working directory path.
            f_env: Optional environment mapping.
            f_log_path: Optional log file path.
            f_mirror_stdout: If True, mirror output to console streams.
            f_timeout: Optional execution timeout in seconds.

        Returns:
            ProcessResult containing returncode, stdout, stderr, timing.

        Raises:
            LauncherError: If argument construction fails or unexpected error occurs.
            ProcessExecutionError: If runner encounters spawn or logging errors.
        """
        if f_runner is None:
            f_runner = f_kwargs.get("runner")
        if f_runner is None:
            f_runner = ProcessRunner()

        f_argv = cls.buildSharedArgv(f_profile, f_point, f_command)

        if f_cwd is None:
            f_cwd = f_kwargs.get("cwd") or f_kwargs.get("working_dir") or f_kwargs.get("f_working_dir")
        if f_cwd is None and hasattr(f_command, "working_dir"):
            f_cwd = getattr(f_command, "working_dir")

        if f_env is None:
            f_env = f_kwargs.get("env") or f_kwargs.get("environment") or f_kwargs.get("f_environment")

        if f_log_path is None:
            f_log_path = f_kwargs.get("log_path") or f_kwargs.get("log") or f_kwargs.get("f_log")
        if f_log_path is None and hasattr(f_command, "stdout_path"):
            f_log_path = getattr(f_command, "stdout_path")

        try:
            return f_runner.run(
                f_argv,
                f_cwd=f_cwd,
                f_env=f_env,
                f_log_path=f_log_path,
                f_mirror_stdout=f_mirror_stdout,
                f_timeout=f_timeout,
                **f_kwargs,
            )
        except (ProcessSpawnError, ProcessLoggingError, ProcessExecutionError):
            raise
        except Exception as f_err:
            raise LauncherError(f"Unexpected error executing shared launch: {f_err}") from f_err

    launch_shared = launchShared

    @classmethod
    def launchRankWorkers(
        cls,
        f_profile: Any,
        f_point: Any,
        f_worker_executable: str,
        f_manifest_path: str,
        f_point_id: Any,
        f_combination_desc: Any,
        f_runner: Optional[ProcessRunner] = None,
        f_cwd: Optional[str] = None,
        f_env: Optional[Mapping[str, str]] = None,
        f_log_path: Optional[str] = None,
        f_mirror_stdout: bool = False,
        f_timeout: Optional[float] = None,
        **f_kwargs: Any,
    ) -> ProcessResult:
        """Execute distributed rank worker processes via ProcessRunner and preserve exact return status.

        Args:
            f_profile: SiteProfile, ProfileRecord, SchedulerKind, LauncherPolicy, or str.
            f_point: ScalePoint, dict, or tuple/list defining (tasks, ppn, nodes).
            f_worker_executable: Path to worker binary (e.g. lsmioworker).
            f_manifest_path: Path to immutable manifest.json.
            f_point_id: Point identifier string or index.
            f_combination_desc: Combination descriptor (e.g. 'c16_b8M' or Combination instance).
            f_runner: Optional ProcessRunner instance (defaults to new ProcessRunner()).
            f_cwd: Optional working directory path.
            f_env: Optional environment mapping.
            f_log_path: Optional log file path.
            f_mirror_stdout: If True, mirror output to console streams.
            f_timeout: Optional execution timeout in seconds.

        Returns:
            ProcessResult containing returncode, stdout, stderr, timing.

        Raises:
            LauncherError: If argument construction fails or unexpected error occurs.
            ProcessExecutionError: If runner encounters spawn or logging errors.
        """
        if f_runner is None:
            f_runner = f_kwargs.get("runner")
        if f_runner is None:
            f_runner = ProcessRunner()

        f_argv = cls.buildRankWorkerArgv(
            f_profile,
            f_point,
            f_worker_executable,
            f_manifest_path,
            f_point_id,
            f_combination_desc,
        )

        if f_cwd is None:
            f_cwd = f_kwargs.get("cwd") or f_kwargs.get("working_dir") or f_kwargs.get("f_working_dir")
        if f_env is None:
            f_env = f_kwargs.get("env") or f_kwargs.get("environment") or f_kwargs.get("f_environment")
        if f_log_path is None:
            f_log_path = f_kwargs.get("log_path") or f_kwargs.get("log") or f_kwargs.get("f_log")

        try:
            return f_runner.run(
                f_argv,
                f_cwd=f_cwd,
                f_env=f_env,
                f_log_path=f_log_path,
                f_mirror_stdout=f_mirror_stdout,
                f_timeout=f_timeout,
                **f_kwargs,
            )
        except (ProcessSpawnError, ProcessLoggingError, ProcessExecutionError):
            raise
        except Exception as f_err:
            raise LauncherError(f"Unexpected error executing rank worker launch: {f_err}") from f_err

    launch_rank_workers = launchRankWorkers


class AllocationController:
    """Ordered matrix allocation controller and execution supervisor.

    Invariants:
    - Assumes module environment has already been established once by the outer scheduler job shell.
    - Preflight validation:
        - Deserializes and validates manifest via ManifestSerializer.deserialize().
        - Validates f_point_id matches a scale point in the manifest.
        - Validates benchmark root and run directory containment.
        - Rejects manifest mismatch before any mutation.
    - Matrix execution:
        - Iterates over all 6 combinations in strict ordered sequence:
          (16, 8M), (16, 1M), (16, 64K), (4, 8M), (4, 1M), (4, 64K)
        - For each combination:
          1. Prepares point private data directory data/c<stripe>/b<block>.
          2. Configures Lustre stripe via LustreConfigurator.configure().
          3. For LMP: stages and validates assets (in.reaxc.hns, data.hns-equil, ffield.reax.hns) into point work directory.
          4. Resolves benchmark adapter (IOR, LSMIO, LMP):
             - Shared mode (is_rank_local=False, e.g. IOR, LMP):
               - Launches benchmark via Launcher.launchShared().
               - Records controller result in combinations/<combination>/controller-result.json via EvidenceStore.
               - If launcher returns nonzero or failure, stops immediately without advancing to subsequent combinations, and returns failure status.
             - Rank-local mode (is_rank_local=True, e.g. LSMIO):
               - Launches rank workers via Launcher.launchRankWorkers().
               - If launcher returns nonzero, stops immediately.
               - Scans and validates rank evidence: requires all exact tasks ranks (0..tasks-1) to have produced successful result records in ranks/<global_rank>/<combination>/result.json.
               - If any rank is missing, duplicate, corrupt, or failed, records combination failure and stops immediately.
               - Records controller result in combinations/<combination>/controller-result.json.
        - Fails closed on any error at any stage, never overwrites existing result files, and returns exact integer exit status (0 on complete success, or the failure code).
    """

    __slots__ = (
        "m_runner",
        "m_worker_executable",
        "m_asset_source",
        "m_layout",
        "m_evidence_store",
        "_frozen",
    )

    def __init__(
        self,
        f_runner: Optional[ProcessRunner] = None,
        f_worker_executable: Optional[str] = None,
        f_asset_source: Optional[Union[str, Any]] = None,
        f_layout: Optional[Any] = None,
        f_evidence_store: Optional[Any] = None,
    ) -> None:
        object.__setattr__(self, "m_runner", f_runner)
        object.__setattr__(
            self,
            "m_worker_executable",
            str(f_worker_executable).strip() if f_worker_executable is not None else None,
        )
        object.__setattr__(self, "m_asset_source", f_asset_source)
        object.__setattr__(self, "m_layout", f_layout)
        object.__setattr__(self, "m_evidence_store", f_evidence_store)
        object.__setattr__(self, "_frozen", True)

    def __setattr__(self, f_name: str, f_value: Any) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"AllocationController is immutable; cannot set attribute '{f_name}'")
        super().__setattr__(f_name, f_value)

    def __delattr__(self, f_name: str) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"AllocationController is immutable; cannot delete attribute '{f_name}'")
        super().__delattr__(f_name)

    @classmethod
    def _extractManifest(
        cls,
        f_manifest_source: Any,
    ) -> Tuple[Any, Optional[str]]:
        """Extract and validate ManifestDocument from path, bytes, string, or ManifestDocument.

        Returns (ManifestDocument, Optional[str] manifest_file_path).
        """
        from lsmiotool.lib.run import ManifestDocument, ManifestSerializer

        if f_manifest_source is None:
            raise AllocationControllerError("Manifest source cannot be None")

        if isinstance(f_manifest_source, ManifestDocument):
            return f_manifest_source, None

        if isinstance(f_manifest_source, (str, bytes)):
            if isinstance(f_manifest_source, str):
                f_str_path = f_manifest_source.strip()
                if "\0" in f_str_path:
                    raise AllocationControllerError(
                        f"Manifest path contains NUL byte: {f_manifest_source!r}"
                    )
                if os.path.exists(f_str_path):
                    if os.path.islink(f_str_path):
                        raise AllocationControllerError(
                            f"Manifest path is a symlink: '{f_str_path}'"
                        )
                    try:
                        with open(f_str_path, "rb") as f_f:
                            f_bytes = f_f.read()
                    except OSError as f_err:
                        raise AllocationControllerError(
                            f"Failed to read manifest file '{f_str_path}': {f_err}"
                        ) from f_err
                    try:
                        f_doc = ManifestSerializer.deserialize(f_bytes)
                        return f_doc, os.path.abspath(f_str_path)
                    except Exception as f_err:
                        raise AllocationControllerError(
                            f"Manifest validation failed for '{f_str_path}': {f_err}"
                        ) from f_err
                elif f_str_path.startswith("{") or "schema_version" in f_str_path:
                    try:
                        f_doc = ManifestSerializer.deserialize(f_str_path)
                        return f_doc, None
                    except Exception as f_err:
                        raise AllocationControllerError(
                            f"Manifest JSON string validation failed: {f_err}"
                        ) from f_err
                else:
                    raise AllocationControllerError(
                        f"Manifest file not found: '{f_manifest_source}'"
                    )
            else:
                try:
                    f_doc = ManifestSerializer.deserialize(f_manifest_source)
                    return f_doc, None
                except Exception as f_err:
                    raise AllocationControllerError(
                        f"Manifest JSON bytes validation failed: {f_err}"
                    ) from f_err

        if isinstance(f_manifest_source, dict):
            try:
                f_doc = ManifestSerializer.deserialize(f_manifest_source)
                return f_doc, None
            except Exception as f_err:
                raise AllocationControllerError(
                    f"Manifest dict validation failed: {f_err}"
                ) from f_err

        raise AllocationControllerError(
            f"Unsupported manifest parameter type: {type(f_manifest_source).__name__}"
        )

    @classmethod
    def _matchScalePoint(
        cls,
        f_manifest: Any,
        f_point_id: Any,
    ) -> Tuple[Any, int, str]:
        """Match point identifier against scale points in manifest.

        Returns (matched_scale_point: ScalePoint, matched_ordinal: int, point_dir_name: str).
        """
        if f_point_id is None:
            raise AllocationControllerError("Scale point ID cannot be None")

        f_matched_sp = None
        f_matched_ord = None

        f_scale_points = getattr(f_manifest, "scale_points", ())
        if not f_scale_points:
            raise AllocationControllerError("Manifest scale_points list is empty")

        for f_idx, f_sp in enumerate(f_scale_points):
            if isinstance(f_point_id, bool):
                break
            if isinstance(f_point_id, int):
                if f_point_id < len(f_scale_points):
                    if f_point_id == f_idx:
                        f_matched_sp = f_sp
                        f_matched_ord = f_idx
                        break
                elif f_point_id == f_sp.tasks:
                    f_matched_sp = f_sp
                    f_matched_ord = f_idx
                    break
            elif hasattr(f_point_id, "tasks") and hasattr(f_point_id, "ppn") and hasattr(f_point_id, "nodes"):
                if (
                    f_sp.tasks == f_point_id.tasks
                    and f_sp.ppn == f_point_id.ppn
                    and f_sp.nodes == f_point_id.nodes
                ):
                    f_matched_sp = f_sp
                    f_matched_ord = f_idx
                    break
            elif isinstance(f_point_id, str):
                f_pt_str = f_point_id.strip()
                f_candidates = {
                    f"{f_idx:02d}-tasks-{f_sp.tasks}",
                    f"tasks-{f_sp.tasks}",
                    f"point-{f_idx:02d}",
                    f"point-{f_idx}",
                    f"{f_idx:02d}",
                    str(f_idx),
                    str(f_sp.tasks),
                }
                if f_pt_str in f_candidates:
                    f_matched_sp = f_sp
                    f_matched_ord = f_idx
                    break

        if f_matched_sp is None:
            f_available_tasks = [f_sp.tasks for f_sp in f_scale_points]
            raise AllocationControllerError(
                f"Scale point identifier '{f_point_id}' does not match any scale point in manifest: tasks={f_available_tasks}"
            )

        f_point_dir_name = f"{f_matched_ord:02d}-tasks-{f_matched_sp.tasks}"
        return f_matched_sp, f_matched_ord, f_point_dir_name

    @classmethod
    def run(
        cls,
        f_manifest_path: Union[str, Any],
        f_point_id: Union[str, int, Any],
        f_runner: Optional[ProcessRunner] = None,
        f_worker_executable: Optional[str] = None,
        f_asset_source: Optional[Union[str, Any]] = None,
        f_layout: Optional[Any] = None,
        f_evidence_store: Optional[Any] = None,
        **f_kwargs: Any,
    ) -> int:
        """Execute ordered benchmark matrix across all 6 combinations for the given point.

        Args:
            f_manifest_path: Path to manifest.json, manifest JSON string/bytes, or ManifestDocument.
            f_point_id: Scale point identifier (e.g. '00-tasks-1', 'tasks-1', index 0, or ScalePoint).
            f_runner: Optional ProcessRunner instance.
            f_worker_executable: Optional path to worker executable for LSMIO rank workers.
            f_asset_source: Optional LMP asset root directory or RuntimeLayout.
            f_layout: Optional ArtifactLayout override.
            f_evidence_store: Optional EvidenceStore override.

        Returns:
            0 on complete success, or the non-zero integer failure status code.

        Raises:
            AllocationControllerError: On preflight validation failures, manifest mismatch, or existing results.
        """
        # Resolve defaults if invoked on instance
        if not isinstance(cls, type):
            if f_runner is None:
                f_runner = cls.m_runner
            if f_worker_executable is None:
                f_worker_executable = cls.m_worker_executable
            if f_asset_source is None:
                f_asset_source = cls.m_asset_source
            if f_layout is None:
                f_layout = cls.m_layout
            if f_evidence_store is None:
                f_evidence_store = cls.m_evidence_store

        # 1. Preflight Manifest Validation
        f_manifest, f_manifest_file_path = cls._extractManifest(f_manifest_path)

        # 2. Match Scale Point
        f_matched_sp, f_matched_ord, f_point_dir_name = cls._matchScalePoint(
            f_manifest, f_point_id
        )

        # 3. Storage class & benchmark root resolution
        f_storage_str = "hdd"
        if hasattr(f_manifest, "plan") and isinstance(f_manifest.plan, dict):
            f_storage_str = f_manifest.plan.get("storage", "hdd")
        elif hasattr(f_manifest, "request") and getattr(f_manifest.request, "ssd", False):
            f_storage_str = "ssd"

        try:
            f_benchmark_root = f_manifest.site.getBenchmarkRoot(f_storage_str)
        except Exception as f_err:
            raise AllocationControllerError(
                f"Failed to resolve benchmark root for storage '{f_storage_str}': {f_err}"
            ) from f_err

        from lsmiotool.lib.artifacts import (
            ArtifactLayout,
            STANDARD_COMBINATION_TUPLES,
            validatePathContainment,
        )

        if f_layout is not None:
            f_layout_obj = f_layout
        else:
            f_layout_obj = ArtifactLayout(f_benchmark_root, f_manifest.run_id)

        try:
            validatePathContainment(f_layout_obj.runRoot, f_layout_obj.benchmarkRoot)
            f_point_dir = f_layout_obj.pointDir(f_matched_sp, f_matched_ord)
            validatePathContainment(f_point_dir, f_layout_obj.runRoot)
            if f_manifest_file_path is not None:
                validatePathContainment(f_manifest_file_path, f_layout_obj.runRoot)
        except Exception as f_err:
            raise AllocationControllerError(
                f"Path containment validation failed: {f_err}"
            ) from f_err

        # 4. Evidence Store Resolution
        if f_evidence_store is not None:
            f_store = f_evidence_store
        else:
            from lsmiotool.lib.evidence import EvidenceStore
            f_plan = f_manifest.toRunPlan() if hasattr(f_manifest, "toRunPlan") else None
            f_store = EvidenceStore(f_layout_obj, f_plan=f_plan)

        # 5. Process Runner
        if f_runner is None:
            f_runner = ProcessRunner()

        # 6. Record Controller Started Event
        from lsmiotool.lib.evidence import EvidenceCollisionError, EvidenceKind

        f_worker_events_dir = f_layout_obj.pointWorkerEventsDir(f_matched_sp, f_matched_ord)
        os.makedirs(f_worker_events_dir, exist_ok=True)

        try:
            f_store.recordWorkerEvent(
                f_point=f_matched_sp,
                f_sequence=1,
                f_evidence_kind=EvidenceKind.CONTROLLER_STARTED,
                f_payload={
                    "target": f_manifest.request.target,
                    "point_id": f_point_dir_name,
                    "tasks": f_matched_sp.tasks,
                    "ppn": f_matched_sp.ppn,
                    "nodes": f_matched_sp.nodes,
                },
                f_ordinal=f_matched_ord,
            )
        except EvidenceCollisionError as f_err:
            raise AllocationControllerError(
                f"Controller event sequence 1 already exists for point '{f_point_dir_name}'; restart rejected"
            ) from f_err

        # 7. Ordered Matrix Execution
        f_target = f_manifest.request.target.lower().strip()
        if f_target not in ("ior", "lsmio", "lmp"):
            raise AllocationControllerError(
                f"Unsupported benchmark target: {f_manifest.request.target!r}"
            )

        for f_combo_idx, (f_stripe, f_block) in enumerate(STANDARD_COMBINATION_TUPLES):
            f_combo_name = f"c{f_stripe}_b{f_block}"

            # Prepare directories
            f_data_dir = f_layout_obj.pointDataSubdir(
                f_matched_sp, f_stripe, f_block, f_matched_ord
            )
            f_combo_dir = f_layout_obj.pointCombinationDir(
                f_matched_sp, f_combo_name, f_matched_ord
            )
            f_combo_work_dir = f_layout_obj.pointCombinationWorkDir(
                f_matched_sp, f_combo_name, f_matched_ord
            )
            f_logs_dir = f_layout_obj.pointLogsDir(f_matched_sp, f_matched_ord)
            f_ranks_dir = f_layout_obj.pointRanksDir(f_matched_sp, f_matched_ord)

            os.makedirs(f_data_dir, exist_ok=True)
            os.makedirs(f_combo_dir, exist_ok=True)
            os.makedirs(f_combo_work_dir, exist_ok=True)
            os.makedirs(f_logs_dir, exist_ok=True)
            os.makedirs(f_ranks_dir, exist_ok=True)

            # Never overwrite check
            f_ctrl_result_path = f_layout_obj.pointControllerResultPath(
                f_matched_sp, f_combo_name, f_matched_ord
            )
            if os.path.exists(f_ctrl_result_path):
                raise AllocationControllerError(
                    f"Controller result for combination '{f_combo_name}' already exists at '{f_ctrl_result_path}'; replacement rejected"
                )

            # Stripe configuration
            try:
                LustreConfigurator.configure(
                    f_profile=f_manifest.site,
                    f_combination=(f_stripe, f_block),
                    f_target_dir=f_data_dir,
                    f_runner=f_runner,
                    f_storage_class=f_storage_str,
                )
            except Exception as f_stripe_err:
                try:
                    f_store.recordControllerResult(
                        f_point=f_matched_sp,
                        f_combination=f_combo_name,
                        f_payload={
                            "status": "failed",
                            "exit_code": 1,
                            "stage": "stripe",
                            "error": str(f_stripe_err),
                        },
                        f_ordinal=f_matched_ord,
                    )
                except Exception:
                    pass
                return 1

            # LMP Asset Staging
            if f_target == "lmp":
                from lsmiotool.lib.benchmarks import LmpAdapter

                f_lmp_adapter = LmpAdapter()
                f_resolved_assets = f_asset_source
                if f_resolved_assets is None:
                    try:
                        from lsmiotool.lib.resources import ResourceLocator

                        f_resolved_assets = ResourceLocator.forSource(sys.argv[0]).asset_root
                    except Exception:
                        f_resolved_assets = os.path.join(
                            f_manifest.site.install_prefix, "share", "lmp-reaxff"
                        )

                try:
                    f_lmp_adapter.stageAssets(
                        f_asset_source=f_resolved_assets,
                        f_work_dir=f_combo_work_dir,
                    )
                except Exception as f_stage_err:
                    try:
                        f_store.recordControllerResult(
                            f_point=f_matched_sp,
                            f_combination=f_combo_name,
                            f_payload={
                                "status": "failed",
                                "exit_code": 1,
                                "stage": "stage_assets",
                                "error": str(f_stage_err),
                            },
                            f_ordinal=f_matched_ord,
                        )
                    except Exception:
                        pass
                    return 1

            # Shared Launch (IOR or LMP)
            if f_target == "ior":
                from lsmiotool.lib.benchmarks import IorAdapter

                f_ior_adapter = IorAdapter()
                f_ior_exe = f_manifest.site.executables["ior"]
                f_setup = (
                    f_manifest.plan.get("setup", "BASE")
                    if hasattr(f_manifest, "plan") and isinstance(f_manifest.plan, dict)
                    else (f_manifest.request.setup or "BASE")
                )
                f_out_file = os.path.join(f_data_dir, f"ior.{f_setup.lower()}")
                f_stdout_file = os.path.join(f_logs_dir, f"ior_{f_combo_name}.stdout")
                f_stderr_file = os.path.join(f_logs_dir, f"ior_{f_combo_name}.stderr")

                try:
                    f_cmd = f_ior_adapter.buildCommand(
                        f_executable=f_ior_exe,
                        f_setup=f_setup,
                        f_block_size=f_block,
                        f_working_dir=f_combo_work_dir,
                        f_output_path=f_out_file,
                        f_stdout_path=f_stdout_file,
                        f_stderr_path=f_stderr_file,
                        f_stripe_count=f_stripe,
                    )
                except Exception as f_spec_err:
                    try:
                        f_store.recordControllerResult(
                            f_point=f_matched_sp,
                            f_combination=f_combo_name,
                            f_payload={
                                "status": "failed",
                                "exit_code": 1,
                                "stage": "spec",
                                "error": str(f_spec_err),
                            },
                            f_ordinal=f_matched_ord,
                        )
                    except Exception:
                        pass
                    return 1

                try:
                    f_proc_res = Launcher.launchShared(
                        f_profile=f_manifest.site,
                        f_point=f_matched_sp,
                        f_command=f_cmd,
                        f_runner=f_runner,
                        f_cwd=f_combo_work_dir,
                        f_log_path=f_cmd.stdout_path,
                    )
                except Exception as f_launch_err:
                    try:
                        f_store.recordControllerResult(
                            f_point=f_matched_sp,
                            f_combination=f_combo_name,
                            f_payload={
                                "status": "failed",
                                "exit_code": 1,
                                "stage": "launch",
                                "error": str(f_launch_err),
                            },
                            f_ordinal=f_matched_ord,
                        )
                    except Exception:
                        pass
                    return 1

                f_is_ok = f_proc_res.is_success
                f_ret = f_proc_res.returncode
                if not f_is_ok or f_ret != 0:
                    f_store.recordControllerResult(
                        f_point=f_matched_sp,
                        f_combination=f_combo_name,
                        f_payload={
                            "status": "failed",
                            "exit_code": f_ret if f_ret != 0 else 1,
                            "stage": "execution",
                            "error": f"IOR process failed with code {f_ret}",
                        },
                        f_ordinal=f_matched_ord,
                    )
                    return f_ret if f_ret != 0 else 1

                # Validate expected benchmark output artifact
                f_out_path = f_stdout_file
                f_out_valid = False
                f_out_err = None
                try:
                    from lsmiotool.lib.artifacts import validatePathContainment
                    validatePathContainment(f_out_path, f_layout_obj.runRoot)
                    f_st = os.lstat(f_out_path)
                    if stat.S_ISLNK(f_st.st_mode):
                        f_out_err = f"Expected IOR output artifact '{f_out_path}' is a symlink"
                    elif not stat.S_ISREG(f_st.st_mode):
                        f_out_err = f"Expected IOR output artifact '{f_out_path}' is not a regular file"
                    else:
                        f_out_valid = True
                except Exception as f_stat_err:
                    f_out_err = f"Expected IOR output artifact '{f_out_path}' could not be validated: {f_stat_err}"

                if not f_out_valid:
                    f_store.recordControllerResult(
                        f_point=f_matched_sp,
                        f_combination=f_combo_name,
                        f_payload={
                            "status": "failed",
                            "exit_code": 1,
                            "stage": "output_validation",
                            "error": f_out_err,
                            "output_path": f_out_path,
                        },
                        f_ordinal=f_matched_ord,
                    )
                    return 1

                f_store.recordControllerResult(
                    f_point=f_matched_sp,
                    f_combination=f_combo_name,
                    f_payload={
                        "status": "success",
                        "exit_code": 0,
                        "elapsed_seconds": f_proc_res.elapsed_seconds,
                        "stage": "execution",
                        "output_path": f_out_path,
                    },
                    f_ordinal=f_matched_ord,
                )

            elif f_target == "lmp":
                from lsmiotool.lib.benchmarks import LmpAdapter

                f_lmp_adapter = LmpAdapter()
                f_lmp_exe = f_manifest.site.executables["lmp"]
                f_setup = (
                    f_manifest.plan.get("setup", "LSMIO")
                    if hasattr(f_manifest, "plan") and isinstance(f_manifest.plan, dict)
                    else (f_manifest.request.setup or "LSMIO")
                )
                f_stdout_file = os.path.join(f_logs_dir, f"lmp_{f_combo_name}.stdout")
                f_stderr_file = os.path.join(f_logs_dir, f"lmp_{f_combo_name}.stderr")

                # Read tuning exclusively from manifest plan for the exact task count
                f_tasks_str = str(f_matched_sp.tasks)
                f_tuning_map = None
                if isinstance(f_manifest.plan, dict) and "lmp_task_tuning" in f_manifest.plan:
                    f_tuning_map = f_manifest.plan["lmp_task_tuning"]
                elif hasattr(f_manifest.plan, "lmp_task_tuning"):
                    f_tuning_map = f_manifest.plan.lmp_task_tuning

                if not isinstance(f_tuning_map, (dict, Mapping)) or f_tasks_str not in f_tuning_map:
                    f_err_msg = f"Missing LMP tuning in manifest for task count {f_tasks_str}"
                    try:
                        f_store.recordControllerResult(
                            f_point=f_matched_sp,
                            f_combination=f_combo_name,
                            f_payload={
                                "status": "failed",
                                "exit_code": 1,
                                "stage": "spec",
                                "error": f_err_msg,
                            },
                            f_ordinal=f_matched_ord,
                        )
                    except Exception:
                        pass
                    return 1

                f_point_tuning = f_tuning_map[f_tasks_str]
                if not isinstance(f_point_tuning, (dict, Mapping)):
                    f_err_msg = f"Malformed LMP tuning in manifest for task count {f_tasks_str}: {f_point_tuning!r}"
                    try:
                        f_store.recordControllerResult(
                            f_point=f_matched_sp,
                            f_combination=f_combo_name,
                            f_payload={
                                "status": "failed",
                                "exit_code": 1,
                                "stage": "spec",
                                "error": f_err_msg,
                            },
                            f_ordinal=f_matched_ord,
                        )
                    except Exception:
                        pass
                    return 1

                f_rep = f_point_tuning.get("replication")
                f_buf = f_point_tuning.get("buffer_size_mb")

                try:
                    f_cmd = f_lmp_adapter.buildCommand(
                        f_executable=f_lmp_exe,
                        f_setup=f_setup,
                        f_replication=f_rep,
                        f_buffer_size_mb=f_buf,
                        f_working_dir=f_combo_work_dir,
                        f_stdout_path=f_stdout_file,
                        f_stderr_path=f_stderr_file,
                    )
                except Exception as f_spec_err:
                    try:
                        f_store.recordControllerResult(
                            f_point=f_matched_sp,
                            f_combination=f_combo_name,
                            f_payload={
                                "status": "failed",
                                "exit_code": 1,
                                "stage": "spec",
                                "error": str(f_spec_err),
                            },
                            f_ordinal=f_matched_ord,
                        )
                    except Exception:
                        pass
                    return 1

                try:
                    f_proc_res = Launcher.launchShared(
                        f_profile=f_manifest.site,
                        f_point=f_matched_sp,
                        f_command=f_cmd,
                        f_runner=f_runner,
                        f_cwd=f_combo_work_dir,
                        f_log_path=f_cmd.stdout_path,
                    )
                except Exception as f_launch_err:
                    try:
                        f_store.recordControllerResult(
                            f_point=f_matched_sp,
                            f_combination=f_combo_name,
                            f_payload={
                                "status": "failed",
                                "exit_code": 1,
                                "stage": "launch",
                                "error": str(f_launch_err),
                            },
                            f_ordinal=f_matched_ord,
                        )
                    except Exception:
                        pass
                    return 1

                f_is_ok = f_proc_res.is_success
                f_ret = f_proc_res.returncode
                if not f_is_ok or f_ret != 0:
                    f_store.recordControllerResult(
                        f_point=f_matched_sp,
                        f_combination=f_combo_name,
                        f_payload={
                            "status": "failed",
                            "exit_code": f_ret if f_ret != 0 else 1,
                            "stage": "execution",
                            "error": f"LMP process failed with code {f_ret}",
                        },
                        f_ordinal=f_matched_ord,
                    )
                    return f_ret if f_ret != 0 else 1

                # Validate expected benchmark output artifact
                f_out_path = f_stdout_file
                f_out_valid = False
                f_out_err = None
                try:
                    from lsmiotool.lib.artifacts import validatePathContainment
                    validatePathContainment(f_out_path, f_layout_obj.runRoot)
                    f_st = os.lstat(f_out_path)
                    if stat.S_ISLNK(f_st.st_mode):
                        f_out_err = f"Expected LMP output artifact '{f_out_path}' is a symlink"
                    elif not stat.S_ISREG(f_st.st_mode):
                        f_out_err = f"Expected LMP output artifact '{f_out_path}' is not a regular file"
                    else:
                        f_out_valid = True
                except Exception as f_stat_err:
                    f_out_err = f"Expected LMP output artifact '{f_out_path}' could not be validated: {f_stat_err}"

                if not f_out_valid:
                    f_store.recordControllerResult(
                        f_point=f_matched_sp,
                        f_combination=f_combo_name,
                        f_payload={
                            "status": "failed",
                            "exit_code": 1,
                            "stage": "output_validation",
                            "error": f_out_err,
                            "output_path": f_out_path,
                        },
                        f_ordinal=f_matched_ord,
                    )
                    return 1

                f_store.recordControllerResult(
                    f_point=f_matched_sp,
                    f_combination=f_combo_name,
                    f_payload={
                        "status": "success",
                        "exit_code": 0,
                        "elapsed_seconds": f_proc_res.elapsed_seconds,
                        "stage": "execution",
                        "output_path": f_out_path,
                    },
                    f_ordinal=f_matched_ord,
                )

            elif f_target == "lsmio":
                # Rank-local mode
                f_worker_exe = f_worker_executable
                if f_worker_exe is None:
                    try:
                        from lsmiotool.lib.resources import ResourceLocator

                        f_worker_exe = ResourceLocator.forSource(sys.argv[0]).worker_executable
                    except Exception:
                        f_worker_exe = sys.argv[0]

                f_manifest_param = (
                    f_manifest_file_path
                    if f_manifest_file_path is not None
                    else f_layout_obj.manifestPath
                )
                f_stdout_file = os.path.join(
                    f_logs_dir, f"lsmio_launcher_{f_combo_name}.stdout"
                )

                try:
                    f_proc_res = Launcher.launchRankWorkers(
                        f_profile=f_manifest.site,
                        f_point=f_matched_sp,
                        f_worker_executable=f_worker_exe,
                        f_manifest_path=f_manifest_param,
                        f_point_id=f_point_dir_name,
                        f_combination_desc=f_combo_name,
                        f_runner=f_runner,
                        f_cwd=f_combo_work_dir,
                        f_log_path=f_stdout_file,
                    )
                except Exception as f_launch_err:
                    try:
                        f_store.recordControllerResult(
                            f_point=f_matched_sp,
                            f_combination=f_combo_name,
                            f_payload={
                                "status": "failed",
                                "exit_code": 1,
                                "stage": "launch",
                                "error": str(f_launch_err),
                            },
                            f_ordinal=f_matched_ord,
                        )
                    except Exception:
                        pass
                    return 1

                if not f_proc_res.is_success or f_proc_res.returncode != 0:
                    f_ret = f_proc_res.returncode
                    f_store.recordControllerResult(
                        f_point=f_matched_sp,
                        f_combination=f_combo_name,
                        f_payload={
                            "status": "failed",
                            "exit_code": f_ret,
                            "stage": "launcher",
                            "error": f"Launcher exited with return code {f_ret}",
                        },
                        f_ordinal=f_matched_ord,
                    )
                    return f_ret if f_ret != 0 else 1

                # Scan and validate rank evidence
                f_ranks_failed = False
                f_failure_reason = None
                from lsmiotool.lib.evidence import ResultPayloadValidator
                for f_rank_idx in range(f_matched_sp.tasks):
                    f_rank_result_path = f_layout_obj.pointRankResultPath(
                        f_matched_sp, f_rank_idx, f_combo_name, f_matched_ord
                    )
                    if not os.path.exists(f_rank_result_path):
                        f_ranks_failed = True
                        f_failure_reason = (
                            f"Missing rank result for rank {f_rank_idx} in combination {f_combo_name}"
                        )
                        break

                    try:
                        f_st = os.lstat(f_rank_result_path)
                        if stat.S_ISLNK(f_st.st_mode):
                            f_ranks_failed = True
                            f_failure_reason = f"Rank result for rank {f_rank_idx} is a symlink: '{f_rank_result_path}'"
                            break
                        if not stat.S_ISREG(f_st.st_mode):
                            f_ranks_failed = True
                            f_failure_reason = f"Rank result for rank {f_rank_idx} is not a regular file: '{f_rank_result_path}'"
                            break
                    except OSError as f_st_err:
                        f_ranks_failed = True
                        f_failure_reason = f"Cannot lstat rank result for rank {f_rank_idx}: {f_st_err}"
                        break

                    try:
                        f_rank_rec = f_store.readRankResult(
                            f_matched_sp, f_rank_idx, f_combo_name, f_ordinal=f_matched_ord
                        )
                    except Exception as f_read_err:
                        f_ranks_failed = True
                        f_failure_reason = (
                            f"Corrupt rank result for rank {f_rank_idx} in combination {f_combo_name}: {f_read_err}"
                        )
                        break

                    if f_rank_rec is None:
                        f_ranks_failed = True
                        f_failure_reason = (
                            f"Missing rank result for rank {f_rank_idx} in combination {f_combo_name}"
                        )
                        break

                    try:
                        ResultPayloadValidator.validateRankPayload(
                            f_rank_rec.payload,
                            f_expected_rank=f_rank_idx,
                            f_expected_combination=f_combo_name,
                            f_validate_files=True,
                            f_layout=f_layout_obj,
                        )
                    except Exception as f_val_err:
                        f_ranks_failed = True
                        f_failure_reason = f"Rank {f_rank_idx} failed payload validation: {f_val_err}"
                        break

                    f_payload = f_rank_rec.payload or {}
                    if f_payload.get("status") != "success" or int(f_payload.get("exit_code", -1)) != 0:
                        f_ranks_failed = True
                        f_failure_reason = f"Rank {f_rank_idx} reported non-success: {f_payload}"
                        break

                if f_ranks_failed:
                    f_store.recordControllerResult(
                        f_point=f_matched_sp,
                        f_combination=f_combo_name,
                        f_payload={
                            "status": "failed",
                            "exit_code": 1,
                            "stage": "rank_evidence",
                            "error": f_failure_reason,
                        },
                        f_ordinal=f_matched_ord,
                    )
                    return 1

                f_store.recordControllerResult(
                    f_point=f_matched_sp,
                    f_combination=f_combo_name,
                    f_payload={
                        "status": "success",
                        "exit_code": 0,
                        "stage": "rank_evidence",
                        "tasks_validated": f_matched_sp.tasks,
                        "elapsed_seconds": f_proc_res.elapsed_seconds,
                    },
                    f_ordinal=f_matched_ord,
                )

        return 0

    execute = run


class RankIdentityResolver:
    """Resolver for late-bound task rank identity from scheduler runtime environments.

    Invariants:
    - Slurm (SchedulerKind.SLURM):
        - global_rank: from SLURM_PROCID (must parse to integer, 0 <= global_rank < tasks)
        - node_rank: from SLURM_NODEID (str/int) or fallback to SLURMD_NODENAME or socket.gethostname()
        - local_rank: from SLURM_LOCALID (int if present and non-empty, else None)
    - PBS (SchedulerKind.PBS):
        - global_rank: from ALPS_APP_PE (or PBS_VNODENUM / PBS_NODENUM, int, 0 <= global_rank < tasks)
        - node_rank: from HOSTNAME in environment or socket.gethostname() (str)
        - local_rank: strictly None unless profile/certified config explicitly supplies a certified local_rank variable name
    - Direct / Fake (SchedulerKind.FAKE / SchedulerKind.DIRECT):
        - global_rank: from LSMIO_RANK / RANK / PROCID / SLURM_PROCID / ALPS_APP_PE
        - node_rank: from LSMIO_NODE / NODEID / SLURM_NODEID / HOSTNAME / socket.gethostname()
        - local_rank: from LSMIO_LOCAL_RANK / LOCAL_RANK / SLURM_LOCALID (or None)
    - Validation:
        - tasks must be a positive integer.
        - global_rank must satisfy 0 <= global_rank < tasks.
        - Rejects missing, non-integer, negative, or out-of-range values with RankIdentityError.
    """

    __slots__ = ()

    def __init__(self) -> None:
        pass

    @classmethod
    def resolve(
        cls,
        f_scheduler_kind: Any,
        f_env: Optional[Mapping[str, str]] = None,
        f_tasks: int = 1,
        f_ppn: int = 1,
        f_profile: Optional[Any] = None,
        **f_kwargs: Any,
    ) -> Any:
        """Resolve RankIdentity from runtime environment variables.

        Args:
            f_scheduler_kind: SchedulerKind enum, string (e.g. 'slurm', 'pbs', 'fake'), SiteProfile, or object.
            f_env: Mapping of environment variables (defaults to os.environ if None).
            f_tasks: Planned total task count for the scale point.
            f_ppn: Planned tasks per node (defaults to 1).
            f_profile: Optional SiteProfile / ProfileRecord.

        Returns:
            RankIdentity instance.

        Raises:
            RankIdentityError: If rank identity variables are missing, malformed, or out of range.
        """
        from lsmiotool.lib.run import RankIdentity
        from lsmiotool.lib.site import SchedulerKind

        # Validate tasks
        if isinstance(f_tasks, bool) or not isinstance(f_tasks, int) or f_tasks <= 0:
            raise RankIdentityError(
                f"Task count must be a positive integer, got: {f_tasks!r}"
            )

        if isinstance(f_ppn, bool) or not isinstance(f_ppn, int) or f_ppn <= 0:
            raise RankIdentityError(
                f"PPN must be a positive integer, got: {f_ppn!r}"
            )

        f_effective_env: Mapping[str, str] = f_env if f_env is not None else os.environ

        # Resolve scheduler kind
        f_kind: Optional[SchedulerKind] = None
        if isinstance(f_scheduler_kind, SchedulerKind):
            f_kind = f_scheduler_kind
        elif isinstance(f_scheduler_kind, str):
            f_kind_str = f_scheduler_kind.lower().strip()
            if f_kind_str in ("slurm", "srun"):
                f_kind = SchedulerKind.SLURM
            elif f_kind_str in ("pbs", "aprun"):
                f_kind = SchedulerKind.PBS
            elif f_kind_str in ("fake", "direct"):
                f_kind = SchedulerKind.FAKE
            else:
                raise RankIdentityError(f"Unknown scheduler kind string: {f_scheduler_kind!r}")
        elif hasattr(f_scheduler_kind, "scheduler"):
            f_raw = getattr(f_scheduler_kind, "scheduler")
            if isinstance(f_raw, SchedulerKind):
                f_kind = f_raw
            elif isinstance(f_raw, str):
                f_raw_str = f_raw.lower().strip()
                if f_raw_str in ("slurm", "srun"):
                    f_kind = SchedulerKind.SLURM
                elif f_raw_str in ("pbs", "aprun"):
                    f_kind = SchedulerKind.PBS
                elif f_raw_str in ("fake", "direct"):
                    f_kind = SchedulerKind.FAKE
        elif f_profile is not None and hasattr(f_profile, "scheduler"):
            f_raw = getattr(f_profile, "scheduler")
            if isinstance(f_raw, SchedulerKind):
                f_kind = f_raw
            elif isinstance(f_raw, str):
                f_raw_str = f_raw.lower().strip()
                if f_raw_str in ("slurm", "srun"):
                    f_kind = SchedulerKind.SLURM
                elif f_raw_str in ("pbs", "aprun"):
                    f_kind = SchedulerKind.PBS
                elif f_raw_str in ("fake", "direct"):
                    f_kind = SchedulerKind.FAKE

        if f_kind is None:
            f_kind = SchedulerKind.FAKE

        f_global_rank: Optional[int] = None
        f_node_rank: Optional[Union[str, int]] = None
        f_local_rank: Optional[int] = None

        if f_kind == SchedulerKind.SLURM:
            # 1. Global rank from SLURM_PROCID
            if "SLURM_PROCID" not in f_effective_env:
                raise RankIdentityError("SLURM environment missing required SLURM_PROCID variable")
            f_procid_raw = f_effective_env["SLURM_PROCID"]
            if f_procid_raw is None or not str(f_procid_raw).strip():
                raise RankIdentityError("SLURM_PROCID variable is empty")
            try:
                f_global_rank = int(str(f_procid_raw).strip())
            except ValueError as f_err:
                raise RankIdentityError(
                    f"SLURM_PROCID must be an integer, got: {f_procid_raw!r}"
                ) from f_err

            # 2. Node rank from SLURM_NODEID or SLURMD_NODENAME
            if "SLURM_NODEID" in f_effective_env and str(f_effective_env["SLURM_NODEID"]).strip():
                f_node_rank = str(f_effective_env["SLURM_NODEID"]).strip()
            elif "SLURMD_NODENAME" in f_effective_env and str(f_effective_env["SLURMD_NODENAME"]).strip():
                f_node_rank = str(f_effective_env["SLURMD_NODENAME"]).strip()
            elif "HOSTNAME" in f_effective_env and str(f_effective_env["HOSTNAME"]).strip():
                f_node_rank = str(f_effective_env["HOSTNAME"]).strip()
            else:
                f_node_rank = socket.gethostname()

            # 3. Local rank from SLURM_LOCALID (optional)
            if "SLURM_LOCALID" in f_effective_env and str(f_effective_env["SLURM_LOCALID"]).strip():
                f_localid_raw = f_effective_env["SLURM_LOCALID"]
                try:
                    f_local_rank = int(str(f_localid_raw).strip())
                except ValueError as f_err:
                    raise RankIdentityError(
                        f"SLURM_LOCALID must be an integer, got: {f_localid_raw!r}"
                    ) from f_err
                if f_local_rank < 0:
                    raise RankIdentityError(
                        f"SLURM_LOCALID cannot be negative: {f_local_rank}"
                    )

        elif f_kind == SchedulerKind.PBS:
            # 1. Global rank from ALPS_APP_PE (or PBS_VNODENUM / PBS_NODENUM)
            f_pe_raw = (
                f_effective_env.get("ALPS_APP_PE")
                or f_effective_env.get("PBS_VNODENUM")
                or f_effective_env.get("PBS_NODENUM")
            )
            if f_pe_raw is None or not str(f_pe_raw).strip():
                raise RankIdentityError("PBS environment missing required ALPS_APP_PE variable")
            try:
                f_global_rank = int(str(f_pe_raw).strip())
            except ValueError as f_err:
                raise RankIdentityError(
                    f"PBS rank must be an integer, got: {f_pe_raw!r}"
                ) from f_err

            # 2. Node rank from HOSTNAME or socket.gethostname()
            if "HOSTNAME" in f_effective_env and str(f_effective_env["HOSTNAME"]).strip():
                f_node_rank = str(f_effective_env["HOSTNAME"]).strip()
            else:
                f_node_rank = socket.gethostname()

            # 3. Local rank: strictly None unless profile / certified config explicitly supplies it
            f_certified_local_var = None
            if f_profile is not None and hasattr(f_profile, "rank_identity"):
                f_ri = getattr(f_profile, "rank_identity")
                if hasattr(f_ri, "local_rank") and f_ri.local_rank:
                    f_certified_local_var = f_ri.local_rank
            if f_certified_local_var is None:
                f_certified_local_var = f_kwargs.get("f_certified_local_var") or f_kwargs.get("certified_local_var")

            if f_certified_local_var and f_certified_local_var in f_effective_env:
                f_loc_raw = f_effective_env[f_certified_local_var]
                if f_loc_raw is not None and str(f_loc_raw).strip():
                    try:
                        f_local_rank = int(str(f_loc_raw).strip())
                    except ValueError as f_err:
                        raise RankIdentityError(
                            f"Certified local rank variable {f_certified_local_var!r} must be an integer, got: {f_loc_raw!r}"
                        ) from f_err
                    if f_local_rank < 0:
                        raise RankIdentityError(
                            f"Certified local rank cannot be negative: {f_local_rank}"
                        )
            else:
                f_local_rank = None

        elif f_kind == SchedulerKind.FAKE:
            # 1. Global rank from LSMIO_RANK / RANK / PROCID / SLURM_PROCID / ALPS_APP_PE
            f_rank_raw = (
                f_effective_env.get("LSMIO_RANK")
                or f_effective_env.get("RANK")
                or f_effective_env.get("PROCID")
                or f_effective_env.get("SLURM_PROCID")
                or f_effective_env.get("ALPS_APP_PE")
            )
            if f_rank_raw is None or not str(f_rank_raw).strip():
                raise RankIdentityError(
                    "Direct/Fake environment missing rank variable (LSMIO_RANK / RANK / PROCID)"
                )
            try:
                f_global_rank = int(str(f_rank_raw).strip())
            except ValueError as f_err:
                raise RankIdentityError(
                    f"Direct/Fake rank must be an integer, got: {f_rank_raw!r}"
                ) from f_err

            # 2. Node rank from LSMIO_NODE / NODEID / SLURM_NODEID / HOSTNAME / socket.gethostname()
            f_node_raw = (
                f_effective_env.get("LSMIO_NODE")
                or f_effective_env.get("NODEID")
                or f_effective_env.get("SLURM_NODEID")
                or f_effective_env.get("SLURMD_NODENAME")
                or f_effective_env.get("HOSTNAME")
            )
            if f_node_raw and str(f_node_raw).strip():
                f_node_rank = str(f_node_raw).strip()
            else:
                f_node_rank = socket.gethostname()

            # 3. Local rank from LSMIO_LOCAL_RANK / LOCAL_RANK / SLURM_LOCALID
            f_loc_raw = (
                f_effective_env.get("LSMIO_LOCAL_RANK")
                or f_effective_env.get("LOCAL_RANK")
                or f_effective_env.get("SLURM_LOCALID")
            )
            if f_loc_raw is not None and str(f_loc_raw).strip():
                try:
                    f_local_rank = int(str(f_loc_raw).strip())
                except ValueError as f_err:
                    raise RankIdentityError(
                        f"Local rank must be an integer, got: {f_loc_raw!r}"
                    ) from f_err
                if f_local_rank < 0:
                    raise RankIdentityError(
                        f"Local rank cannot be negative: {f_local_rank}"
                    )
            else:
                f_local_rank = None

        # Validate global rank range
        if f_global_rank is None or f_global_rank < 0:
            raise RankIdentityError(
                f"Global rank cannot be negative or None, got: {f_global_rank!r}"
            )
        if f_global_rank >= f_tasks:
            raise RankIdentityError(
                f"Global rank ({f_global_rank}) is out of range for task count ({f_tasks})"
            )

        if not f_node_rank:
            raise RankIdentityError("Node rank could not be resolved")

        return RankIdentity(
            f_global_rank=f_global_rank,
            f_node_rank=f_node_rank,
            f_local_rank=f_local_rank,
        )

    resolveIdentity = resolve
    resolve_identity = resolve


class RankClaimStore:
    """Store and manager for exclusive rank claim locks scoped by rank and combination.

    Invariants:
    - Claim lockfile 'claim.lock' is created inside the rank combination directory
      (ranks/<global_rank>/<combination>/claim.lock).
    - Uses atomic exclusive create (os.O_CREAT | os.O_EXCL | os.O_WRONLY).
    - If the lockfile already exists (race condition), exactly one caller wins and subsequent callers
      receive RankClaimError.
    - Writes claim metadata (run, point, rank, combination, pid, timestamp) and ensures durability
      with os.fsync before closing.
    - Claims are permanent and never released or deleted.
    - Rejects symbolic links in claim path or parent directory to ensure strict containment.
    """

    __slots__ = ()

    def __init__(self) -> None:
        pass

    @classmethod
    def claim(
        cls,
        f_rank_dir: str,
        f_global_rank: Union[int, str],
        f_combination: Optional[Union[Combination, str, Any]] = None,
        f_run_id: Optional[str] = None,
        f_point_id: Optional[str] = None,
        **f_kwargs: Any,
    ) -> str:
        """Exclusively claim a rank for a combination by creating claim.lock.

        Args:
            f_rank_dir: Path to rank combination directory (ranks/<global_rank>/<combination>)
                        or base rank directory (ranks/<global_rank>).
            f_global_rank: Global rank index.
            f_combination: Optional combination descriptor or name.
            f_run_id: Optional run ID.
            f_point_id: Optional point ID.

        Returns:
            Absolute path to the created claim.lock file.

        Raises:
            RankClaimError: If rank is already claimed (file exists) or claim creation fails.
        """
        if not isinstance(f_rank_dir, str) or not f_rank_dir.strip():
            raise RankClaimError(f"Rank directory must be a non-empty string, got: {f_rank_dir!r}")
        if "\0" in f_rank_dir:
            raise RankClaimError("Rank directory path contains NUL byte")

        f_raw_dir = f_rank_dir.strip()
        f_combo_str: Optional[str] = None
        if f_combination is not None:
            if hasattr(f_combination, "name"):
                f_combo_str = f_combination.name
            else:
                f_combo_str = str(f_combination).strip()

        f_abs_dir = os.path.abspath(os.path.normpath(f_raw_dir))

        if f_combo_str is not None:
            if os.path.basename(f_abs_dir) != f_combo_str:
                f_abs_dir = os.path.join(f_abs_dir, f_combo_str)
        else:
            f_combo_str = os.path.basename(f_abs_dir)

        # Check for symbolic links in the claim directory path or parent directory
        if os.path.islink(f_abs_dir) or os.path.islink(os.path.dirname(f_abs_dir)):
            raise RankClaimError(f"Rank claim directory cannot be a symlink: {f_abs_dir}")

        os.makedirs(f_abs_dir, exist_ok=True)

        f_lock_path = os.path.join(f_abs_dir, "claim.lock")

        if os.path.islink(f_lock_path):
            raise RankClaimError(f"Rank claim lock cannot be a symlink: {f_lock_path}")

        f_now_utc = datetime.now(timezone.utc).isoformat()
        f_pid = os.getpid()

        f_payload = {
            "run": str(f_run_id) if f_run_id is not None else "",
            "run_id": str(f_run_id) if f_run_id is not None else "",
            "point": str(f_point_id) if f_point_id is not None else "",
            "point_id": str(f_point_id) if f_point_id is not None else "",
            "rank": int(f_global_rank),
            "global_rank": int(f_global_rank),
            "combination": f_combo_str,
            "pid": f_pid,
            "claimed_at_utc": f_now_utc,
        }
        f_content = (json.dumps(f_payload, indent=2, sort_keys=True) + "\n").encode("utf-8")

        try:
            f_fd = os.open(
                f_lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except (FileExistsError, OSError) as f_err:
            if getattr(f_err, "errno", None) == errno.EEXIST or isinstance(f_err, FileExistsError):
                raise RankClaimError(
                    f"Rank {f_global_rank} for combination '{f_combo_str}' has already been claimed: '{f_lock_path}'"
                ) from f_err
            raise RankClaimError(
                f"Failed to create rank claim lock '{f_lock_path}': {f_err}"
            ) from f_err

        try:
            os.write(f_fd, f_content)
            os.fsync(f_fd)
        except OSError as f_write_err:
            raise RankClaimError(
                f"Failed to write/fsync rank claim lock '{f_lock_path}': {f_write_err}"
            ) from f_write_err
        finally:
            os.close(f_fd)

        return f_lock_path

    claimRank = claim
    claim_rank = claim

    @classmethod
    def isClaimed(
        cls,
        f_rank_dir: str,
        f_combination: Optional[Union[Combination, str, Any]] = None,
    ) -> bool:
        """Check if a rank combination directory has an existing claim.lock file."""
        if not isinstance(f_rank_dir, str) or not f_rank_dir.strip():
            return False
        f_dir = os.path.abspath(os.path.normpath(f_rank_dir.strip()))
        if f_combination is not None:
            f_cname = f_combination.name if hasattr(f_combination, "name") else str(f_combination).strip()
            if os.path.basename(f_dir) != f_cname:
                f_dir = os.path.join(f_dir, f_cname)
        f_lock_path = os.path.join(f_dir, "claim.lock")
        return os.path.exists(f_lock_path)

    is_claimed = isClaimed

    @classmethod
    def getClaim(
        cls,
        f_rank_dir: str,
        f_combination: Optional[Union[Combination, str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Read claim payload from claim.lock if present, else return None."""
        if not isinstance(f_rank_dir, str) or not f_rank_dir.strip():
            return None
        f_dir = os.path.abspath(os.path.normpath(f_rank_dir.strip()))
        if f_combination is not None:
            f_cname = f_combination.name if hasattr(f_combination, "name") else str(f_combination).strip()
            if os.path.basename(f_dir) != f_cname:
                f_dir = os.path.join(f_dir, f_cname)
        f_lock_path = os.path.join(f_dir, "claim.lock")
        if not os.path.exists(f_lock_path):
            return None
        try:
            with open(f_lock_path, "r", encoding="utf-8") as f_f:
                return json.load(f_f)
        except Exception:
            return None

    get_claim = getClaim


class _RankWorkerDispatcher:
    """Descriptor that dispatches run/execute calls to class-level or instance-level execution."""

    def __init__(self, f_func: Any) -> None:
        self.m_func = f_func

    def __get__(self, f_instance: Any, f_owner: Any) -> Any:
        f_raw_func = getattr(self.m_func, "__func__", self.m_func)
        if f_instance is None:
            def _class_call(
                f_manifest_path: Union[str, Any],
                f_point_id: Union[str, int, Any],
                f_combination_desc: Union[str, Any],
                f_env: Optional[Mapping[str, str]] = None,
                f_runner: Optional[ProcessRunner] = None,
                f_layout: Optional[Any] = None,
                f_evidence_store: Optional[Any] = None,
                f_identity_resolver: Optional[Any] = None,
                f_claim_store: Optional[Any] = None,
                **f_kwargs: Any,
            ) -> int:
                return f_raw_func(
                    f_manifest_path=f_manifest_path,
                    f_point_id=f_point_id,
                    f_combination_desc=f_combination_desc,
                    f_env=f_env,
                    f_runner=f_runner,
                    f_layout=f_layout,
                    f_evidence_store=f_evidence_store,
                    f_identity_resolver=f_identity_resolver,
                    f_claim_store=f_claim_store,
                    **f_kwargs,
                )

            return _class_call
        else:
            def _instance_call(
                f_manifest_path: Union[str, Any],
                f_point_id: Union[str, int, Any],
                f_combination_desc: Union[str, Any],
                f_env: Optional[Mapping[str, str]] = None,
                f_runner: Optional[ProcessRunner] = None,
                f_layout: Optional[Any] = None,
                f_evidence_store: Optional[Any] = None,
                f_identity_resolver: Optional[Any] = None,
                f_claim_store: Optional[Any] = None,
                **f_kwargs: Any,
            ) -> int:
                return f_raw_func(
                    f_manifest_path=f_manifest_path,
                    f_point_id=f_point_id,
                    f_combination_desc=f_combination_desc,
                    f_env=f_env,
                    f_runner=f_runner if f_runner is not None else f_instance.m_runner,
                    f_layout=f_layout if f_layout is not None else f_instance.m_layout,
                    f_evidence_store=f_evidence_store if f_evidence_store is not None else f_instance.m_evidence_store,
                    f_identity_resolver=f_identity_resolver if f_identity_resolver is not None else f_instance.m_identity_resolver,
                    f_claim_store=f_claim_store if f_claim_store is not None else f_instance.m_claim_store,
                    **f_kwargs,
                )

            return _instance_call


class RankWorker:
    """Launched LSMIO task worker executing rank-bound benchmark commands.

    Invariants:
    - Deserializes and validates manifest; verifies f_point_id matches a scale point and target is 'lsmio'.
    - Rejects non-LSMIO shared targets (ior, lmp) with RankWorkerError.
    - Validates combination descriptor and planned matrix before resolving identity or making claims.
    - Resolves RankIdentity via RankIdentityResolver.resolve().
    - Exclusively claims the rank combination via RankClaimStore.claim().
    - Prepares rank combination private output and log directories (ranks/<global_rank>/<combination>/).
    - Instantiates LsmioAdapter and generates launch spec via createLaunchSpec().
    - Binds launch spec for this rank via LsmioAdapter.bindRank(f_launch_spec, f_rank_identity).
    - Executes the bound command via ProcessRunner.run(), mirroring output to combination rank log file.
    - Records rank result record in ranks/<global_rank>/<combination>/result.json via EvidenceStore.
    - Returns exact process exit status (0 on success, or non-zero child returncode / signal).
    - Never overwrites existing rank result files.
    """

    __slots__ = (
        "m_runner",
        "m_layout",
        "m_evidence_store",
        "m_identity_resolver",
        "m_claim_store",
        "_frozen",
    )

    def __init__(
        self,
        f_runner: Optional[ProcessRunner] = None,
        f_layout: Optional[Any] = None,
        f_evidence_store: Optional[Any] = None,
        f_identity_resolver: Optional[Any] = None,
        f_claim_store: Optional[Any] = None,
    ) -> None:
        object.__setattr__(self, "m_runner", f_runner)
        object.__setattr__(self, "m_layout", f_layout)
        object.__setattr__(self, "m_evidence_store", f_evidence_store)
        object.__setattr__(self, "m_identity_resolver", f_identity_resolver)
        object.__setattr__(self, "m_claim_store", f_claim_store)
        object.__setattr__(self, "_frozen", True)

    def __setattr__(self, f_name: str, f_value: Any) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"RankWorker is immutable; cannot set attribute '{f_name}'")
        super().__setattr__(f_name, f_value)

    def __delattr__(self, f_name: str) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"RankWorker is immutable; cannot delete attribute '{f_name}'")
        super().__delattr__(f_name)

    @staticmethod
    def _executeImpl(
        f_manifest_path: Union[str, Any],
        f_point_id: Union[str, int, Any],
        f_combination_desc: Union[str, Any],
        f_env: Optional[Mapping[str, str]] = None,
        f_runner: Optional[ProcessRunner] = None,
        f_layout: Optional[Any] = None,
        f_evidence_store: Optional[Any] = None,
        f_identity_resolver: Optional[Any] = None,
        f_claim_store: Optional[Any] = None,
        **f_kwargs: Any,
    ) -> int:
        """Execute rank-bound benchmark for the resolved task identity."""
        # 1. Preflight Manifest Validation
        try:
            f_manifest, f_manifest_file_path = AllocationController._extractManifest(f_manifest_path)
        except Exception as f_err:
            raise RankWorkerError(f"Failed to load or validate manifest: {f_err}") from f_err

        # 2. Validate Benchmark Target is LSMIO
        f_target = f_manifest.request.target.lower().strip()
        if f_target != "lsmio":
            raise RankWorkerError(
                f"RankWorker only supports 'lsmio' benchmark target, got {f_manifest.request.target!r}"
            )

        # 3. Match Scale Point
        try:
            f_matched_sp, f_matched_ord, f_point_dir_name = AllocationController._matchScalePoint(
                f_manifest, f_point_id
            )
        except Exception as f_err:
            raise RankWorkerError(f"Failed to match scale point: {f_err}") from f_err

        # 4. Validate Combination Descriptor & Planned Matrix BEFORE Claiming (F-04)
        try:
            f_stripe, f_block = LustreConfigurator._extractCombination(f_combination_desc)
        except Exception as f_err:
            raise RankWorkerError(f"Invalid combination descriptor {f_combination_desc!r}: {f_err}") from f_err

        f_combo_name = f"c{f_stripe}_b{f_block}"

        f_planned_combos: List[str] = []
        if hasattr(f_manifest, "combinations") and f_manifest.combinations:
            for f_c in f_manifest.combinations:
                f_c_name = f_c.name if hasattr(f_c, "name") else (
                    f"c{getattr(f_c, 'stripe_count', f_stripe)}_b{getattr(f_c, 'block_size', f_block)}"
                )
                f_planned_combos.append(f_c_name)
        else:
            f_planned_combos = [f"c{f_s}_b{f_b}" for f_s, f_b in STANDARD_COMBINATION_TUPLES]

        if f_combo_name not in f_planned_combos:
            raise RankWorkerError(
                f"Combination '{f_combo_name}' is not among planned combinations {f_planned_combos} for scale point '{f_point_dir_name}'"
            )

        # 5. Storage Class & Benchmark Root & Layout
        f_storage_str = "hdd"
        if hasattr(f_manifest, "plan") and isinstance(f_manifest.plan, dict):
            f_storage_str = f_manifest.plan.get("storage", "hdd")
        elif hasattr(f_manifest, "request") and getattr(f_manifest.request, "ssd", False):
            f_storage_str = "ssd"

        try:
            f_benchmark_root = f_manifest.site.getBenchmarkRoot(f_storage_str)
        except Exception as f_err:
            raise RankWorkerError(
                f"Failed to resolve benchmark root for storage '{f_storage_str}': {f_err}"
            ) from f_err

        from lsmiotool.lib.artifacts import ArtifactLayout, validatePathContainment

        if f_layout is not None:
            f_layout_obj = f_layout
        else:
            f_layout_obj = ArtifactLayout(f_benchmark_root, f_manifest.run_id)

        try:
            validatePathContainment(f_layout_obj.runRoot, f_layout_obj.benchmarkRoot)
            f_point_dir = f_layout_obj.pointDir(f_matched_sp, f_matched_ord)
            validatePathContainment(f_point_dir, f_layout_obj.runRoot)
            if f_manifest_file_path is not None:
                validatePathContainment(f_manifest_file_path, f_layout_obj.runRoot)
        except Exception as f_err:
            raise RankWorkerError(f"Path containment validation failed: {f_err}") from f_err

        # 6. Resolve Rank Identity BEFORE Claiming
        f_resolver = f_identity_resolver or RankIdentityResolver
        f_effective_env = f_env if f_env is not None else os.environ

        try:
            f_rank_identity = f_resolver.resolve(
                f_scheduler_kind=f_manifest.site.scheduler,
                f_env=f_effective_env,
                f_tasks=f_matched_sp.tasks,
                f_ppn=f_matched_sp.ppn,
                f_profile=f_manifest.site,
                **f_kwargs,
            )
        except Exception as f_err:
            raise RankWorkerError(f"Rank identity resolution failed: {f_err}") from f_err

        f_global_rank = f_rank_identity.global_rank

        # 7. Exclusive Rank Claim (Scoped by rank and combination)
        f_rank_combo_dir = f_layout_obj.pointRankCombinationDir(
            f_matched_sp, f_global_rank, f_combo_name, f_matched_ord
        )
        if os.path.islink(f_rank_combo_dir) or os.path.islink(os.path.dirname(f_rank_combo_dir)):
            raise RankClaimError(f"Rank claim directory cannot be a symlink: {f_rank_combo_dir}")

        f_claimer = f_claim_store or RankClaimStore
        f_claimer.claim(
            f_rank_combo_dir,
            f_global_rank,
            f_combination=f_combo_name,
            f_run_id=f_manifest.run_id,
            f_point_id=f_point_dir_name,
        )

        # 8. Guard Against Result Replacement
        f_result_path = f_layout_obj.pointRankResultPath(
            f_matched_sp, f_global_rank, f_combo_name, f_matched_ord
        )
        if os.path.exists(f_result_path):
            raise RankWorkerError(
                f"Rank result for rank {f_global_rank} and combination '{f_combo_name}' already exists at '{f_result_path}'; replacement rejected"
            )

        # 9. Directory Preparation
        f_logs_combo_dir = f_layout_obj.pointCombinationLogsDir(
            f_matched_sp, f_combo_name, f_matched_ord
        )
        f_work_dir = f_layout_obj.pointCombinationWorkDir(
            f_matched_sp, f_combo_name, f_matched_ord
        )
        f_data_dir = f_layout_obj.pointDataSubdir(
            f_matched_sp, f_stripe, f_block, f_matched_ord
        )

        os.makedirs(f_rank_combo_dir, exist_ok=True)
        os.makedirs(f_logs_combo_dir, exist_ok=True)
        os.makedirs(f_work_dir, exist_ok=True)
        os.makedirs(f_data_dir, exist_ok=True)

        # 10. Instantiate LsmioAdapter, Create LaunchSpec, and Pure Bind
        from lsmiotool.lib.benchmarks import LsmioAdapter
        from lsmiotool.lib.run import Combination

        f_lsmio_adapter = LsmioAdapter()
        f_setup = (
            f_manifest.plan.get("setup", "NATIVE-M")
            if hasattr(f_manifest, "plan") and isinstance(f_manifest.plan, dict)
            else (f_manifest.request.setup or "NATIVE-M")
        )
        f_exe_name = f_lsmio_adapter.getExecutableName(f_setup)
        if hasattr(f_manifest.site.executables, "getExecutable"):
            f_exe_path = f_manifest.site.executables.getExecutable(f_exe_name)
        elif hasattr(f_manifest.site.executables, "get"):
            f_exe_path = f_manifest.site.executables.get(f_exe_name, f_exe_name)
        elif hasattr(f_manifest.site.executables, "__getitem__"):
            try:
                f_exe_path = f_manifest.site.executables[f_exe_name]
            except Exception:
                f_exe_path = f_exe_name
        else:
            f_exe_path = f_exe_name

        f_combo_obj = None
        if hasattr(f_manifest, "combinations") and f_manifest.combinations:
            for f_c in f_manifest.combinations:
                if (
                    getattr(f_c, "stripe_count", None) == f_stripe
                    and getattr(f_c, "block_size", None) == f_block
                ):
                    f_combo_obj = f_c
                    break
        if f_combo_obj is None:
            f_block_bytes, f_key_count = f_lsmio_adapter.getBlockParameters(f_block)
            f_combo_obj = Combination(
                f_processes=16,
                f_block_size=f_block,
                f_stripe_count=f_stripe,
                f_block_bytes=f_block_bytes,
                f_key_count=f_key_count,
                f_segment_count=128,
            )

        f_launch_spec = f_lsmio_adapter.createLaunchSpec(
            f_request=f_manifest.request,
            f_combination=f_combo_obj,
            f_point=f_matched_sp,
            f_executable=f_exe_path,
        )

        f_bound_cmd = f_lsmio_adapter.bindRank(
            f_spec=f_launch_spec,
            f_identity=f_rank_identity,
            f_layout=f_layout_obj,
            f_ordinal=f_matched_ord,
        )

        # 11. Process Runner Execution
        if f_runner is None:
            f_runner = ProcessRunner()

        f_log_path = f_bound_cmd.stdout_path
        os.makedirs(os.path.dirname(f_log_path), exist_ok=True)

        try:
            f_proc_res = f_runner.run(
                f_bound_cmd.argv,
                f_cwd=f_bound_cmd.working_dir,
                f_log_path=f_log_path,
                f_mirror_stdout=False,
            )
        except (ProcessSpawnError, ProcessLoggingError, ProcessExecutionError) as f_exec_err:
            f_proc_res = getattr(
                f_exec_err,
                "result",
                ProcessResult(
                    f_returncode=1,
                    f_stdout="",
                    f_stderr=str(f_exec_err),
                    f_elapsed_seconds=0.0,
                    f_spawn_error=str(f_exec_err),
                ),
            )
            if f_proc_res is None:
                f_proc_res = ProcessResult(
                    f_returncode=1,
                    f_stdout="",
                    f_stderr=str(f_exec_err),
                    f_elapsed_seconds=0.0,
                    f_spawn_error=str(f_exec_err),
                )

        # 12. Record Rank Evidence
        from lsmiotool.lib.evidence import EvidenceStore

        if f_evidence_store is not None:
            f_store = f_evidence_store
        else:
            f_plan = f_manifest.toRunPlan() if hasattr(f_manifest, "toRunPlan") else None
            f_store = EvidenceStore(f_layout_obj, f_plan=f_plan)

        f_is_ok = f_proc_res.is_success
        f_ret = f_proc_res.returncode
        f_exit_val = 0 if f_is_ok else (f_ret if f_ret != 0 else 1)
        f_payload: Dict[str, Any] = {
            "status": "success" if f_is_ok else "failed",
            "exit_code": f_exit_val,
            "exit_status": f_exit_val,
            "global_rank": f_global_rank,
            "rank": f_global_rank,
            "combination": f_combo_name,
            "node_rank": f_rank_identity.node_rank,
            "local_rank": f_rank_identity.local_rank,
            "elapsed_seconds": f_proc_res.elapsed_seconds,
            "timed_out": f_proc_res.timed_out,
            "argv": list(f_bound_cmd.argv),
            "log_path": f_log_path,
            "result_path": f_result_path,
        }
        if not f_is_ok:
            f_err_msg = (
                f_proc_res.stderr.strip()
                or f_proc_res.stdout.strip()
                or f_proc_res.spawn_error
                or f"Process exited with code {f_exit_val}"
            )
            f_payload["error"] = f_err_msg
        if f_proc_res.is_signal:
            f_payload["signal_number"] = f_proc_res.signal_number

        f_store.recordRankResult(
            f_point=f_matched_sp,
            f_global_rank=f_global_rank,
            f_combination=f_combo_name,
            f_payload=f_payload,
            f_ordinal=f_matched_ord,
        )

        return f_ret

    run = _RankWorkerDispatcher(_executeImpl)
    execute = _RankWorkerDispatcher(_executeImpl)
