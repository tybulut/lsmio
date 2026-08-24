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

"""Pure approved CLI argument parser and package validator for lsmiotool."""

import os
from pathlib import Path
import stat
from typing import Any, Dict, List, Optional, Sequence, Union

from lsmiotool.lib.run import RunRequest


LSMIOTOOL_HELP = """How to run
-----------------------------------------------------------------------
./lsmiotool [options] <cmd> <cmd-arguments>

common cmds:
  compare <benchmark_folder> <read|write> [<stripes>] [<blocksize>]
  load-modules  load needed HPC modules
  parse <target> [--output-dir <dir>] [--format <csv|json>]
  parseLegacy <ior|lsmio|lmp> <local|bake|small|large>
  run <ior|lsmio|lmp> <local|bake|small|large> [--ssd] [--setup <name>]

other cmds:
  latex <viking|viking2|isambard>
  shell       provide interactive access to the python tool
  test        run lsmiotool unit and functional tests

options:
  --debug     enable debug mode and run
  --help      print this help screen
  --ssd       use SSD storage instead
  --version   print version and exit
"""

RUN_HELP_TEXT = """Usage:
  lsmiotool run <benchmark> <scale> [--ssd] [--setup <name>]

Arguments:
  <benchmark>   Supported benchmarks: ior, lsmio, lmp
  <scale>       Supported scales: local, bake, small, large
                (Note: 'lmp large' is strictly unsupported and rejected)

Options:
  --ssd         Use SSD storage class (default: HDD).
  --setup <name>
                Explicit benchmark setup profile (e.g. BASE, HDF5, NATIVE-M, ROCKSDB-M, LSMIO).
                Note: '--setup=value' syntax is strictly rejected; use '--setup <name>'.

Global Options (preserved for legacy compatibility):
  --ssd, -s     Accepted before or after command.
"""

PARSE_HELP_TEXT = """Usage:
  lsmiotool parse <target> [--output-dir <dir>] [--format <csv|json>]

Arguments:
  <target>      Target run root path, manifest file path, or benchmark name (ior, lsmio, lmp).

Options:
  --output-dir <dir>
                Destination directory for reports (default: current working directory).
  --format <format>
                Report format: 'csv' or 'json' (default: csv).
"""


class PackageValidationError(Exception):
    """Raised when package root or required module files fail validation."""

    pass


class WorkerExecutableValidationError(Exception):
    """Raised when worker executable fails path, existence, permissions, or type validation."""

    pass


class CliParseError(Exception):
    """Base exception for CLI argument parsing errors."""

    pass


class RunCliParseError(CliParseError):
    """Exception raised when CLI arguments for the 'run' command are invalid."""

    pass


class ParseCliParseError(CliParseError):
    """Exception raised when CLI arguments for the 'parse' command are invalid."""

    pass


class RunCliParser:
    """Pure standard-library parser for 'lsmiotool run' CLI arguments.

    Usage:
        lsmiotool run <benchmark> <scale> [--ssd] [--setup <name>]

    Supported benchmarks:
        - ior   (default setup: BASE)
        - lsmio (default setup: NATIVE-M)
        - lmp   (default setup: LSMIO)

    Supported scales:
        - local (1 task, 1 task/node)
        - bake  (1, 2, 4, 8 tasks, 1 task/node)
        - small (1, 2, 4, 8, 16, 24, 32, 40, 48 tasks, 1 task/node)
        - large (4, 8, 16, 32, 64, 128, 192, 256 tasks, 4 tasks/node; lmp large is unsupported)

    Options:
        --ssd: Storage class SSD (default HDD)
        --setup <name>: Explicit environment / benchmark profile (e.g. BASE, NATIVE-M, LSMIO).
            Note: '--setup=value' is strictly rejected; use '--setup <name>'.

    Global Options:
        --ssd / -s: Accepted before or after commands for backwards compatibility.
    """

    VALID_BENCHMARKS = frozenset({"ior", "lsmio", "lmp"})
    VALID_SCALES = frozenset({"local", "bake", "small", "large"})

    @classmethod
    def parse(
        cls,
        f_argv: Sequence[str],
        f_global_ssd: bool = False,
    ) -> RunRequest:
        """Parses argument sequence into an immutable canonical RunRequest.

        Args:
            f_argv: Sequence of argument strings (either including or excluding leading 'run').
            f_global_ssd: Whether global '--ssd' was supplied before the command.

        Returns:
            Canonical RunRequest instance.

        Raises:
            RunCliParseError: If syntax, arity, flags, or values are invalid.
        """
        if f_argv is None or isinstance(f_argv, (str, bytes)):
            raise RunCliParseError(
                f"f_argv must be a sequence of argument strings, got: {type(f_argv).__name__}"
            )
        try:
            f_tokens: List[str] = list(f_argv)
        except TypeError:
            raise RunCliParseError(
                f"f_argv must be iterable, got: {type(f_argv).__name__}"
            )

        for f_idx, f_elem in enumerate(f_tokens):
            if not isinstance(f_elem, str):
                raise RunCliParseError(
                    f"All argv elements must be strings, got {type(f_elem).__name__} at index {f_idx}"
                )

        if not isinstance(f_global_ssd, bool):
            raise RunCliParseError(
                f"f_global_ssd must be a boolean, got: {type(f_global_ssd).__name__}"
            )

        # Strictly reject --setup=value anywhere in tokens
        for f_tok in f_tokens:
            if f_tok.startswith("--setup="):
                raise RunCliParseError(
                    f"Prohibit '--setup=value' syntax ({f_tok!r}); use '--setup <name>' with explicit separate argument."
                )

        f_effective_global_ssd: bool = f_global_ssd

        # Separate pre-'run' and post-'run' tokens if 'run' is present
        f_run_indices: List[int] = [
            f_idx for f_idx, f_tok in enumerate(f_tokens) if f_tok.lower() == "run"
        ]

        if f_run_indices:
            f_run_idx = f_run_indices[0]
            f_pre_run_tokens = f_tokens[:f_run_idx]
            f_post_run_tokens = f_tokens[f_run_idx + 1 :]

            for f_pre_tok in f_pre_run_tokens:
                if f_pre_tok == "--setup":
                    raise RunCliParseError(
                        "Prohibit '--setup' placed before 'run' command."
                    )
                elif f_pre_tok == "--ssd":
                    if f_effective_global_ssd:
                        raise RunCliParseError("Duplicate '--ssd' option specified.")
                    f_effective_global_ssd = True
                else:
                    raise RunCliParseError(
                        f"Unexpected token before 'run': {f_pre_tok!r}"
                    )
        else:
            f_post_run_tokens = f_tokens[:]

        # Validate required positional arguments
        if not f_post_run_tokens:
            raise RunCliParseError(
                "Missing required positional arguments: <benchmark> <scale>"
            )

        # Validate benchmark (positional 0)
        f_benchmark_tok = f_post_run_tokens[0]
        if f_benchmark_tok.startswith("-"):
            if f_benchmark_tok == "--setup":
                raise RunCliParseError(
                    "Prohibit '--setup' placed before positional arguments."
                )
            elif f_benchmark_tok == "--ssd":
                raise RunCliParseError(
                    "Prohibit '--ssd' placed before positional arguments."
                )
            else:
                raise RunCliParseError(
                    f"Unexpected option {f_benchmark_tok!r} placed before positional arguments."
                )

        f_benchmark = f_benchmark_tok.strip().lower()
        if f_benchmark not in cls.VALID_BENCHMARKS:
            raise RunCliParseError(
                f"Invalid benchmark: {f_benchmark_tok!r}. Must be one of: {sorted(cls.VALID_BENCHMARKS)}"
            )

        if len(f_post_run_tokens) < 2:
            raise RunCliParseError(
                "Missing required positional argument: <scale>"
            )

        # Validate scale (positional 1)
        f_scale_tok = f_post_run_tokens[1]
        if f_scale_tok.startswith("-"):
            if f_scale_tok == "--setup":
                raise RunCliParseError(
                    "Prohibit '--setup' placed between positional arguments."
                )
            elif f_scale_tok == "--ssd":
                raise RunCliParseError(
                    "Prohibit '--ssd' placed between positional arguments."
                )
            else:
                raise RunCliParseError(
                    f"Unexpected option {f_scale_tok!r} placed between positional arguments."
                )

        f_scale = f_scale_tok.strip().lower()
        if f_scale not in cls.VALID_SCALES:
            raise RunCliParseError(
                f"Invalid scale: {f_scale_tok!r}. Must be one of: {sorted(cls.VALID_SCALES)}"
            )

        # Parse trailing options
        f_trailing_tokens = f_post_run_tokens[2:]
        f_is_ssd: bool = f_effective_global_ssd
        f_trailing_ssd_seen: bool = False
        f_setup_name: Optional[str] = None

        f_idx = 0
        while f_idx < len(f_trailing_tokens):
            f_tok = f_trailing_tokens[f_idx]
            if f_tok == "--ssd":
                if f_trailing_ssd_seen or f_effective_global_ssd:
                    raise RunCliParseError("Duplicate '--ssd' option specified.")
                f_is_ssd = True
                f_trailing_ssd_seen = True
                f_idx += 1
            elif f_tok == "--setup":
                if f_setup_name is not None:
                    raise RunCliParseError("Duplicate '--setup' option specified.")
                if f_idx + 1 >= len(f_trailing_tokens):
                    raise RunCliParseError("Missing value after '--setup' option.")
                f_val = f_trailing_tokens[f_idx + 1]
                if f_val.startswith("-"):
                    raise RunCliParseError(
                        f"Missing valid value after '--setup' option, got option-like token: {f_val!r}"
                    )
                if not f_val.strip():
                    raise RunCliParseError("Setup name cannot be empty.")
                f_setup_name = f_val.strip().upper()
                f_idx += 2
            elif f_tok.startswith("-"):
                raise RunCliParseError(f"Unknown option: {f_tok!r}")
            else:
                raise RunCliParseError(
                    f"Unexpected extra positional argument: {f_tok!r}"
                )

        return RunRequest(
            f_target=f_benchmark,
            f_scale=f_scale,
            f_ssd=f_is_ssd,
            f_setup=f_setup_name,
        )


def parseRunArguments(
    f_argv: Sequence[str],
    f_global_ssd: bool = False,
) -> RunRequest:
    """Convenience function wrapping RunCliParser.parse."""
    return RunCliParser.parse(f_argv=f_argv, f_global_ssd=f_global_ssd)


class ParseRequest:
    """Immutable parsed and validated parse request."""

    __slots__ = ("m_target", "m_output_dir", "m_format", "_frozen")

    def __init__(
        self,
        f_target: str,
        f_output_dir: Optional[str] = None,
        f_format: str = "csv",
    ) -> None:
        if not isinstance(f_target, str) or not f_target.strip():
            raise ValueError(
                f"target must be a non-empty string, got: {f_target!r}"
            )
        if f_output_dir is not None and (
            not isinstance(f_output_dir, str) or not f_output_dir.strip()
        ):
            raise ValueError(
                f"output_dir must be a non-empty string or None, got: {f_output_dir!r}"
            )
        if not isinstance(f_format, str) or not f_format.strip():
            raise ValueError(
                f"format must be a non-empty string, got: {f_format!r}"
            )
        f_norm_format = f_format.strip().lower()
        if f_norm_format not in {"csv", "json"}:
            raise ValueError(
                f"format must be 'csv' or 'json', got: {f_format!r}"
            )

        super().__setattr__("m_target", f_target.strip())
        super().__setattr__(
            "m_output_dir",
            f_output_dir.strip() if f_output_dir is not None else None,
        )
        super().__setattr__("m_format", f_norm_format)
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
    def output_dir(self) -> Optional[str]:
        return self.m_output_dir

    @property
    def outputDir(self) -> Optional[str]:
        return self.m_output_dir

    @property
    def format(self) -> str:
        return self.m_format

    def toDict(self) -> Dict[str, Any]:
        return {
            "target": self.m_target,
            "output_dir": self.m_output_dir,
            "format": self.m_format,
        }

    def __repr__(self) -> str:
        return (
            f"ParseRequest(target={self.m_target!r}, "
            f"output_dir={self.m_output_dir!r}, "
            f"format={self.m_format!r})"
        )

    def __eq__(self, f_other: Any) -> bool:
        if isinstance(f_other, ParseRequest):
            return (
                self.m_target == f_other.m_target
                and self.m_output_dir == f_other.m_output_dir
                and self.m_format == f_other.m_format
            )
        return False


class ParseCliParser:
    """Pure standard-library parser for 'lsmiotool parse' CLI arguments.

    Usage:
        lsmiotool parse <target> [--output-dir <dir>] [--format <csv|json>]

    Arguments:
        <target>: Target run root path, manifest file path, or benchmark name ('ior', 'lsmio', 'lmp').

    Options:
        --output-dir <dir>: Destination directory for reports (default: current working directory).
        --format <format>: Report format ('csv' or 'json', default: 'csv').
    """

    VALID_FORMATS = frozenset({"csv", "json"})

    @classmethod
    def parse(
        cls,
        f_argv: Sequence[str],
    ) -> ParseRequest:
        """Parses argument sequence into an immutable canonical ParseRequest.

        Args:
            f_argv: Sequence of argument strings (either including or excluding leading 'parse').

        Returns:
            Canonical ParseRequest instance.

        Raises:
            ParseCliParseError: If syntax, arity, flags, or values are invalid.
        """
        if f_argv is None or isinstance(f_argv, (str, bytes)):
            raise ParseCliParseError(
                f"f_argv must be a sequence of argument strings, got: {type(f_argv).__name__}"
            )
        try:
            f_tokens: List[str] = list(f_argv)
        except TypeError:
            raise ParseCliParseError(
                f"f_argv must be iterable, got: {type(f_argv).__name__}"
            )

        for f_idx, f_elem in enumerate(f_tokens):
            if not isinstance(f_elem, str):
                raise ParseCliParseError(
                    f"All argv elements must be strings, got {type(f_elem).__name__} at index {f_idx}"
                )

        f_tokens_copy = list(f_tokens)
        if f_tokens_copy and f_tokens_copy[0].lower() == "parse":
            f_tokens_copy.pop(0)

        if not f_tokens_copy:
            raise ParseCliParseError(
                "Missing required positional argument: <target>"
            )

        f_target_tok = f_tokens_copy[0]
        if f_target_tok.startswith("-"):
            raise ParseCliParseError(
                f"Unexpected option {f_target_tok!r} placed before positional argument <target>."
            )

        f_target = f_target_tok.strip()
        if not f_target:
            raise ParseCliParseError("Target cannot be empty.")

        f_remaining_tokens = f_tokens_copy[1:]
        f_output_dir: Optional[str] = None
        f_format: str = "csv"
        f_format_seen: bool = False

        f_idx = 0
        while f_idx < len(f_remaining_tokens):
            f_tok = f_remaining_tokens[f_idx]
            if f_tok == "--output-dir":
                if f_output_dir is not None:
                    raise ParseCliParseError(
                        "Duplicate '--output-dir' option specified."
                    )
                if f_idx + 1 >= len(f_remaining_tokens):
                    raise ParseCliParseError(
                        "Missing value after '--output-dir' option."
                    )
                f_val = f_remaining_tokens[f_idx + 1]
                if f_val.startswith("-"):
                    raise ParseCliParseError(
                        f"Missing valid value after '--output-dir' option, got option-like token: {f_val!r}"
                    )
                if not f_val.strip():
                    raise ParseCliParseError("Output directory cannot be empty.")
                f_output_dir = f_val.strip()
                f_idx += 2
            elif f_tok == "--format":
                if f_format_seen:
                    raise ParseCliParseError(
                        "Duplicate '--format' option specified."
                    )
                if f_idx + 1 >= len(f_remaining_tokens):
                    raise ParseCliParseError(
                        "Missing value after '--format' option."
                    )
                f_val = f_remaining_tokens[f_idx + 1]
                if f_val.startswith("-"):
                    raise ParseCliParseError(
                        f"Missing valid value after '--format' option, got option-like token: {f_val!r}"
                    )
                f_norm_val = f_val.strip().lower()
                if f_norm_val not in cls.VALID_FORMATS:
                    raise ParseCliParseError(
                        f"Invalid format: {f_val!r}. Must be one of: {sorted(cls.VALID_FORMATS)}"
                    )
                f_format = f_norm_val
                f_format_seen = True
                f_idx += 2
            elif f_tok.startswith("-"):
                raise ParseCliParseError(f"Unknown option: {f_tok!r}")
            else:
                raise ParseCliParseError(
                    f"Unexpected extra positional argument: {f_tok!r}"
                )

        return ParseRequest(
            f_target=f_target,
            f_output_dir=f_output_dir,
            f_format=f_format,
        )


def parseParseArguments(f_argv: Sequence[str]) -> ParseRequest:
    """Convenience function wrapping ParseCliParser.parse."""
    return ParseCliParser.parse(f_argv=f_argv)


class SourcePackageValidator:
    """Validates source package root and required core module files at consumer boundary."""

    DEFAULT_REQUIRED_FILES = (
        "lib/__init__.py",
        "lib/cli.py",
        "lib/main.py",
        "lib/version.py",
    )

    @classmethod
    def validate(
        cls,
        f_package_root: Union[str, Path],
        f_required_files: Optional[Sequence[str]] = None,
    ) -> str:
        """Validates that package root is a non-symlink directory and required files exist as non-symlink regular readable files.

        Uses os.lstat strictly at the consumer boundary. Prohibits directory searching,
        cwd/HOME/PATH lookup, or fallback.

        Args:
            f_package_root: Path to package root directory.
            f_required_files: Optional sequence of relative paths to validate within package root.
                Defaults to DEFAULT_REQUIRED_FILES.

        Returns:
            Normalized path string to the package root.

        Raises:
            PackageValidationError: If package root or any required file is missing, symlinked,
                non-regular/wrong type, unreadable, or invalid.
        """
        if f_package_root is None:
            raise PackageValidationError("Package root cannot be None.")
        if not isinstance(f_package_root, (str, Path)):
            raise PackageValidationError(
                f"Package root must be a string or Path, got: {type(f_package_root).__name__}"
            )
        f_root_str = str(f_package_root).strip()
        if not f_root_str:
            raise PackageValidationError("Package root cannot be empty.")
        if "\0" in f_root_str:
            raise PackageValidationError("Package root contains NUL byte.")

        f_root_norm = os.path.normpath(f_root_str)

        # Validate package root using lstat
        try:
            f_st = os.lstat(f_root_norm)
        except (FileNotFoundError, OSError) as f_e:
            raise PackageValidationError(
                f"Package root directory does not exist or cannot be accessed: {f_root_norm}"
            ) from f_e

        if stat.S_ISLNK(f_st.st_mode) or os.path.islink(f_root_norm):
            raise PackageValidationError(
                f"Package root must not be a symlink: {f_root_norm}"
            )

        if not stat.S_ISDIR(f_st.st_mode):
            raise PackageValidationError(
                f"Package root must be a directory: {f_root_norm}"
            )

        # Validate required files
        f_req_list = (
            f_required_files
            if f_required_files is not None
            else cls.DEFAULT_REQUIRED_FILES
        )
        if not isinstance(f_req_list, (list, tuple, set, frozenset)):
            raise PackageValidationError(
                f"Required files must be a sequence of paths, got: {type(f_req_list).__name__}"
            )

        for f_rel_file in f_req_list:
            if not isinstance(f_rel_file, str) or not f_rel_file.strip():
                raise PackageValidationError(
                    f"Required file path must be a non-empty string, got: {f_rel_file!r}"
                )
            if "\0" in f_rel_file:
                raise PackageValidationError(
                    f"Required file path contains NUL byte: {f_rel_file!r}"
                )
            f_clean_rel = f_rel_file.strip()
            if os.path.isabs(f_clean_rel):
                f_file_path = os.path.normpath(f_clean_rel)
            else:
                f_file_path = os.path.normpath(os.path.join(f_root_norm, f_clean_rel))

            try:
                f_file_st = os.lstat(f_file_path)
            except (FileNotFoundError, OSError) as f_e:
                raise PackageValidationError(
                    f"Required package module file does not exist: {f_file_path}"
                ) from f_e

            if stat.S_ISLNK(f_file_st.st_mode) or os.path.islink(f_file_path):
                raise PackageValidationError(
                    f"Required package module file must not be a symlink: {f_file_path}"
                )

            if not stat.S_ISREG(f_file_st.st_mode):
                raise PackageValidationError(
                    f"Required package module file must be a regular file: {f_file_path}"
                )

            if not os.access(f_file_path, os.R_OK):
                raise PackageValidationError(
                    f"Required package module file is not readable: {f_file_path}"
                )

        return f_root_norm


class WorkerExecutableValidator:
    """Validates worker executable at consumer boundary using os.lstat."""

    @classmethod
    def validate(
        cls,
        f_worker_path: Union[str, Path],
    ) -> str:
        """Validates that worker executable exists, is an absolute regular file, not a symlink, and has execute and read permissions.

        Uses os.lstat directly at consumer boundary. Prohibits directory searching,
        cwd/HOME/PATH lookup, or fallback.

        Args:
            f_worker_path: Path to worker executable (str or Path).

        Returns:
            Normalized absolute path string to the worker executable.

        Raises:
            WorkerExecutableValidationError: If path is missing, symlinked, directory,
                non-regular, non-executable, unreadable, or invalid.
        """
        if f_worker_path is None:
            raise WorkerExecutableValidationError(
                "Worker executable path cannot be None."
            )
        if not isinstance(f_worker_path, (str, Path)):
            raise WorkerExecutableValidationError(
                f"Worker executable path must be a string or Path, got: {type(f_worker_path).__name__}"
            )
        f_path_str = str(f_worker_path).strip()
        if not f_path_str:
            raise WorkerExecutableValidationError(
                "Worker executable path cannot be empty."
            )
        if "\0" in f_path_str:
            raise WorkerExecutableValidationError(
                "Worker executable path contains NUL byte."
            )

        f_abs_path = os.path.normpath(
            f_path_str if os.path.isabs(f_path_str) else os.path.abspath(f_path_str)
        )

        try:
            f_st = os.lstat(f_abs_path)
        except (FileNotFoundError, OSError) as f_err:
            raise WorkerExecutableValidationError(
                f"Worker executable does not exist or cannot be accessed: {f_abs_path}"
            ) from f_err

        if stat.S_ISLNK(f_st.st_mode) or os.path.islink(f_abs_path):
            raise WorkerExecutableValidationError(
                f"Worker executable must not be a symlink: {f_abs_path}"
            )

        if not stat.S_ISREG(f_st.st_mode):
            raise WorkerExecutableValidationError(
                f"Worker executable must be a regular file: {f_abs_path}"
            )

        if not os.access(f_abs_path, os.X_OK):
            raise WorkerExecutableValidationError(
                f"Worker executable does not have execute permissions: {f_abs_path}"
            )

        if not os.access(f_abs_path, os.R_OK):
            raise WorkerExecutableValidationError(
                f"Worker executable is not readable: {f_abs_path}"
            )

        return f_abs_path

    def __call__(self, f_worker_path: Union[str, Path]) -> str:
        return self.validate(f_worker_path)


class InstalledPackageValidator:
    """Validates installed package root and required core module files at consumer boundary."""

    DEFAULT_REQUIRED_FILES = (
        "__init__.py",
        "lib/__init__.py",
        "lib/cli.py",
        "lib/main.py",
        "lib/run.py",
        "lib/worker.py",
        "lib/version.py",
        "lib/resources.py",
    )

    @classmethod
    def validate(
        cls,
        f_installed_pkg_root: Union[str, Path],
        f_required_files: Optional[Sequence[str]] = None,
    ) -> str:
        """Validates that installed package root is a non-symlink directory and required files exist as non-symlink regular readable files.

        Uses os.lstat strictly at the consumer boundary. Prohibits directory searching,
        cwd/HOME/PATH lookup, or fallback.

        Args:
            f_installed_pkg_root: Path to installed package root directory.
            f_required_files: Optional sequence of relative paths to validate within package root.
                Defaults to DEFAULT_REQUIRED_FILES.

        Returns:
            Normalized path string to the installed package root.

        Raises:
            PackageValidationError: If installed package root or any required file is missing, symlinked,
                non-regular/wrong type, unreadable, or invalid.
        """
        if f_installed_pkg_root is None:
            raise PackageValidationError("Installed package root cannot be None.")
        if not isinstance(f_installed_pkg_root, (str, Path)):
            raise PackageValidationError(
                f"Installed package root must be a string or Path, got: {type(f_installed_pkg_root).__name__}"
            )
        f_root_str = str(f_installed_pkg_root).strip()
        if not f_root_str:
            raise PackageValidationError("Installed package root cannot be empty.")
        if "\0" in f_root_str:
            raise PackageValidationError("Installed package root contains NUL byte.")

        f_root_norm = os.path.normpath(f_root_str)

        # Validate installed package root using lstat
        try:
            f_st = os.lstat(f_root_norm)
        except (FileNotFoundError, OSError) as f_e:
            raise PackageValidationError(
                f"Installed package root directory does not exist or cannot be accessed: {f_root_norm}"
            ) from f_e

        if stat.S_ISLNK(f_st.st_mode) or os.path.islink(f_root_norm):
            raise PackageValidationError(
                f"Installed package root must not be a symlink: {f_root_norm}"
            )

        if not stat.S_ISDIR(f_st.st_mode):
            raise PackageValidationError(
                f"Installed package root must be a directory: {f_root_norm}"
            )

        # Validate required files
        f_req_list = (
            f_required_files
            if f_required_files is not None
            else cls.DEFAULT_REQUIRED_FILES
        )
        if not isinstance(f_req_list, (list, tuple, set, frozenset)):
            raise PackageValidationError(
                f"Required files must be a sequence of paths, got: {type(f_req_list).__name__}"
            )

        for f_rel_file in f_req_list:
            if not isinstance(f_rel_file, str) or not f_rel_file.strip():
                raise PackageValidationError(
                    f"Required file path must be a non-empty string, got: {f_rel_file!r}"
                )
            if "\0" in f_rel_file:
                raise PackageValidationError(
                    f"Required file path contains NUL byte: {f_rel_file!r}"
                )
            f_clean_rel = f_rel_file.strip()
            if os.path.isabs(f_clean_rel):
                f_file_path = os.path.normpath(f_clean_rel)
            else:
                f_file_path = os.path.normpath(os.path.join(f_root_norm, f_clean_rel))

            try:
                f_file_st = os.lstat(f_file_path)
            except (FileNotFoundError, OSError) as f_e:
                raise PackageValidationError(
                    f"Required installed package module file does not exist: {f_file_path}"
                ) from f_e

            if stat.S_ISLNK(f_file_st.st_mode) or os.path.islink(f_file_path):
                raise PackageValidationError(
                    f"Required installed package module file must not be a symlink: {f_file_path}"
                )

            if not stat.S_ISREG(f_file_st.st_mode):
                raise PackageValidationError(
                    f"Required installed package module file must be a regular file: {f_file_path}"
                )

            if not os.access(f_file_path, os.R_OK):
                raise PackageValidationError(
                    f"Required installed package module file is not readable: {f_file_path}"
                )

        return f_root_norm

    def __call__(
        self,
        f_installed_pkg_root: Union[str, Path],
        f_required_files: Optional[Sequence[str]] = None,
    ) -> str:
        return self.validate(f_installed_pkg_root, f_required_files)
