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
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from lsmiotool.lib.archive import ArchiveError, ArchiveRequest
from lsmiotool.lib.run import RunRequest


LSMIOTOOL_HELP = """How to run
-----------------------------------------------------------------------
./lsmiotool [options] <cmd> <cmd-arguments>

common cmds:
  archive <benchmark> <scale> [<variant>] [--dest <path>] [--setup <name>] [--source <path>]
  compare <nodes|variants> <folder> ... [--output-dir <dir>] [--all]
  load-modules  load needed HPC modules
  parse <target> [--output-dir <dir>] [--format <csv|json>]
  parseLegacy <ior|lsmio|lmp> <local|bake|small|large|variants> [<path>]
  parseLegacy lsmio backends <local|bake|small|large> [<path>]
  run <ior|lsmio|lmp> <local|bake|small|large|variants> [<variants>] [--ssd] [--setup <name>] [--archive|--no-archive] [--resume] [--out-dir <dir>] [--versioned] [--fast]
  run lsmio backends <local|bake|small|large> [<backends>] [--ssd] [--archive|--no-archive] [--resume] [--out-dir <dir>] [--time <hours>] [--fast]

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

ARCHIVE_HELP_TEXT = """Usage:
  lsmiotool archive <benchmark> <scale> [<variant>] [--dest <path>] [--setup <name>] [--source <path>]

Arguments:
  <benchmark>   Supported benchmarks: lsmio
  <scale>       Supported scales: local, bake, small, large, variants
                ('baseline' is accepted as the deprecated spelling of 'variants')
  <variant>     Optional variant configuration for 'lsmio variants'
                (e.g. footer, footer-btree, wbuf-512m). Only supported for 'lsmio variants'.

Options:
  --dest <path> Archive destination directory (default: <benchmark_root>/lsmio-archive/{variants|baseline}).
                Relative paths resolve against <benchmark_root>. BM_ARCHIVE_DEST is ignored, as in bmtool.
                Note: '--dest=value' syntax is strictly rejected; use '--dest <path>'.
  --setup <name>
                LSMIO setup naming the arm, outputs-<arm> (default: $BM_SETUP, else NATIVE-M;
                for an lsmiotool run, the run's own setup).
  --source <path>
                What to archive: an lsmiotool run root or a bmtool outputs directory.

Source (default): <benchmark_root> is the site profile's benchmark root.
  - <benchmark_root>/lsmio/outputs, when it holds bmtool outputs: moved to
    <dest>/outputs-<arm> and recreated empty, like bmtool archive.
  - otherwise the latest lsmiotool run of 'lsmio <scale>' (and <variant>) under
    <benchmark_root>/runs: its succeeded points are copied into <dest>/outputs-<arm>
    in bmtool's layout with reports; the run root is left in place.
  Both present is an error: pick one with --source.
"""

RUN_HELP_TEXT = """Usage:
  lsmiotool run <benchmark> <scale> [<variants>] [--ssd] [--setup <name>] [--archive|--no-archive] [--resume] [--out-dir <path>] [--versioned] [--fast]
  lsmiotool run lsmio backends <scale> [<backends>] [--ssd] [--archive|--no-archive] [--resume] [--out-dir <path>] [--time <hours>] [--fast]

Arguments:
  <benchmark>   Supported benchmarks: ior, lsmio, lmp
  <scale>       Supported scales: local, bake, small, large, variants
                (Note: 'lmp large' is strictly unsupported and rejected)
  <backends>    Optional comma-separated list of backends (default: adios2,native,plugin,rocksdb).
                Each scale point is one job running the backends one after another.
                Only supported for 'lsmiotool run lsmio backends'.
  <variants>    Optional single variant, comma-separated list of variants
                (e.g. footer,manoff,autotune), 'most' for 26 canonical variants,
                or 'all' for all registered matrix variants.
                Only supported for 'lsmio variants'.

Options:
  --ssd         Use SSD storage class (default: HDD).
  --setup <name>
                Explicit benchmark setup profile (e.g. BASE, HDF5, NATIVE-M, ROCKSDB-M, LSMIO).
                Note: '--setup=value' syntax is strictly rejected; use '--setup <name>'.
  --archive     Archive each scale point when its job ends. On by default for 'backends', for
                'variants' with one or more variants and for --versioned; a 'variants' run of
                the baseline alone is archived only with --archive.
  --no-archive  Do not archive (not allowed with --versioned).
  --resume      Skip a variant whose outputs-<arm>:run archive exists, or a backend's scale point
                whose outputs-<backend>/<nodes> archive exists. A baseline-alone or a --versioned run
                without variants always runs again.
  --out-dir <path>
                Explicit archive destination directory (default: <benchmark_root>/lsmio-archive/{backends/<scale>|variants|variants-versioned}).
                Aliases: --output-dir <path>, --dest <path>.
                Note: '--out-dir=value' syntax is strictly rejected; use separated arguments.
  --time <hours>
                Explicit job walltime limit in hours (aliases: --walltime, --wallhour, clamped to [1, 48]).
                Overrides default dynamic scaling (2 + total_runs * 2 hours, granting 120 minutes per matrix run + 2 hours safety headroom).
  --versioned   Execute versioned comparison run against reference baseline.
  --fast        Halve calculated walltime and cap at 23 hours to stay within qos=standard (<= 24h) on ARCHER2.

Global Options (preserved for legacy compatibility):
  --ssd, -s     Accepted before or after command.
"""

PARSE_HELP_TEXT = """Usage:
  lsmiotool parse <target> [--output-dir <dir>] [--format <csv|json>]
  lsmiotool parse lsmio backends <scale> [--output-dir <dir>] [--format <csv|json>]

Arguments:
  <target>      Target run root path, manifest file path, or benchmark name (ior, lsmio, lmp).
  <scale>       Supported scales for backends mode: local, bake, small, large.

Options:
  --output-dir <dir>
                Destination directory for reports (default: current working directory).
  --format <format>
                Report format: 'csv' or 'json' (default: csv).
"""

COMPARE_HELP_TEXT = """Usage:
  lsmiotool compare <nodes|variants> <folder> ... [--output-dir <dir>] [--all]

Submodes:
  nodes <folder> <read|write> [<stripes>] [<blocksize>] [--output-dir <dir>]
  nodes <folder> [read|write] --all [--output-dir <dir>]
      Compares performance across node counts for a benchmark folder.
      Arguments:
          <folder>: Archive folder with one outputs-<backend> directory per backend (e.g. <archive>/backends/<scale>).
          <read|write>: Operation to compare ('read' or 'write'); optional with --all.
          [stripes]: Stripe count: 4 or 16 (default: 4).
          [blocksize]: Block size: '64K', '1M', or '8M' (default: '1M').
      Options:
          --all: Generate charts for all 6 (stripes, blocksize) permutations, for the given
                 operation or, without one, for both read and write (12 charts). Not combinable
                 with <stripes>/<blocksize>.
          --output-dir <dir>: Destination directory for generated PNG plots (default: current working directory).

  variants <archive_folder> [read|write|both] [<stripes>] [<blocksize>] [--all] [--output-dir <dir>]
      Compares performance across benchmark/storage variants on fixed 8-node baseline runs.
      Arguments:
          <archive_folder>: Archive folder containing outputs-* run subdirectories.
          [operation]: Operation to compare: 'read', 'write', or 'both' (default: 'both').
          [stripes]: Stripe count: 4 or 16 (default: 4).
          [blocksize]: Block size: '64K', '1M', or '8M' (default: '1M').
      Options:
          --all: Generate comparison charts across all 6 (stripes, blocksize) permutations, per
                 operation (12 with the default 'both'). Not combinable with <stripes>/<blocksize>.
          --output-dir <dir>: Destination directory for generated PNG plots (default: current working directory).
"""

# Backward compatibility alias
COMPARE_ARCHIVE_HELP_TEXT = COMPARE_HELP_TEXT


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


class ArchiveCliParseError(CliParseError):
    """Exception raised when CLI arguments for the 'archive' command are invalid."""

    pass


class CompareCliParseError(CliParseError):
    """Exception raised when CLI arguments for the 'compare' command are invalid."""

    pass


# Backward compatibility alias for existing test imports and external callers
CompareArchiveCliParseError = CompareCliParseError


class RunCliParser:
    """Pure standard-library parser for 'lsmiotool run' CLI arguments.

    Grammar:
        lsmiotool run <benchmark> <scale> [<variant>] [--ssd] [--setup <name>]

    Positional Arguments:
        <benchmark>: Required. One of: ior, lsmio, lmp.
        <scale>: Required. One of: local, bake, small, large, variants
            ('baseline' is the deprecated spelling of 'variants').
        <variant>: Optional. Supported exclusively for 'lsmio variants'.

    Options:
        --ssd: Storage class SSD (default HDD)
        --setup <name>: Explicit environment / benchmark profile (e.g. BASE, NATIVE-M, LSMIO).
            Note: '--setup=value' is strictly rejected; use '--setup <name>'.

    Global Options:
        --ssd / -s: Accepted before or after commands for backwards compatibility.
    """

    VALID_BENCHMARKS = frozenset({"ior", "lsmio", "lmp"})
    VALID_SCALES = frozenset({"local", "bake", "small", "large", "variants"})
    # Deprecated spelling retained so existing scripts keep working
    SCALE_ALIASES = {"baseline": "variants"}

    @classmethod
    def parse(
        cls,
        f_argv: Sequence[str],
        f_global_ssd: bool = False,
        f_environ: Optional[Dict[str, str]] = None,
    ) -> RunRequest:
        """Parses argument sequence into an immutable canonical RunRequest.

        Args:
            f_argv: Sequence of argument strings (either including or excluding leading 'run').
            f_global_ssd: Whether global '--ssd' was supplied before the command.
            f_environ: Environment for bmtool's BM_SETUP / BM_WALLHOUR defaults
                (default: os.environ).

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
            raise RunCliParseError("Missing required positional argument: <scale>")

        # Check for 'backends' mode syntax: lsmiotool run lsmio backends <scale> [<backends>]
        f_mode: str = "standard"
        f_backends: Optional[Tuple[str, ...]] = None
        f_variants: Tuple[Optional[str], ...] = (None,)
        f_variant_name: Optional[str] = None

        if (
            f_benchmark == "lsmio"
            and f_post_run_tokens[1].strip().lower() == "backends"
        ):
            f_mode = "backends"
            if len(f_post_run_tokens) < 3:
                raise RunCliParseError(
                    "Missing required positional argument: <scale> for 'run lsmio backends'"
                )
            f_scale_tok = f_post_run_tokens[2]
            if f_scale_tok.startswith("-"):
                raise RunCliParseError(
                    f"Unexpected option {f_scale_tok!r} placed before scale in 'run lsmio backends'."
                )
            f_scale = f_scale_tok.strip().lower()
            valid_backend_scales = frozenset({"local", "bake", "small", "large"})
            if f_scale not in valid_backend_scales:
                raise RunCliParseError(
                    f"Invalid scale for backends mode: {f_scale_tok!r}. Must be one of: {sorted(valid_backend_scales)}"
                )

            f_trailing_tokens = f_post_run_tokens[3:]
            if f_trailing_tokens and not f_trailing_tokens[0].startswith("-"):
                f_backends_raw = f_trailing_tokens[0].strip()
                f_trailing_tokens = f_trailing_tokens[1:]
                parsed_b = [
                    b.strip().lower() for b in f_backends_raw.split(",") if b.strip()
                ]
                if not parsed_b:
                    raise RunCliParseError("Backends specification cannot be empty.")
                f_backends = tuple(parsed_b)
            else:
                f_backends = ("adios2", "native", "plugin", "rocksdb")
        else:
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
            f_scale = cls.SCALE_ALIASES.get(f_scale, f_scale)
            if f_scale not in cls.VALID_SCALES:
                raise RunCliParseError(
                    f"Invalid scale: {f_scale_tok!r}. Must be one of: {sorted(cls.VALID_SCALES)}"
                )

            f_trailing_tokens = f_post_run_tokens[2:]

        # Parse trailing options and optional positional variant
        from lsmiotool.lib.variants import VariantCatalogue

        if f_scale == "variants":
            if f_benchmark == "lsmio":
                if f_trailing_tokens and not f_trailing_tokens[0].startswith("-"):
                    f_variant_tok = f_trailing_tokens[0]
                    f_trailing_tokens = f_trailing_tokens[1:]
                    raw_tokens = [
                        t.strip() for t in f_variant_tok.split(",") if t.strip()
                    ]
                    if not raw_tokens:
                        raise RunCliParseError("Variant specification cannot be empty.")

                    expanded_tokens: List[str] = []
                    for t in raw_tokens:
                        if t.lower() == "most":
                            expanded_tokens.extend(VariantCatalogue.mostVariants())
                        elif t.lower() == "all":
                            expanded_tokens.extend(VariantCatalogue.allVariants())
                        else:
                            expanded_tokens.append(t)

                    resolved_variants: List[Optional[str]] = []
                    for t in expanded_tokens:
                        f_rec = VariantCatalogue.resolve(t)
                        resolved_variants.append(f_rec.tokens if f_rec.tokens else None)
                    f_variants = tuple(resolved_variants)
                    f_variant_name = f_variants[0] if f_variants else None
            else:
                if f_trailing_tokens and not f_trailing_tokens[0].startswith("-"):
                    raise RunCliParseError(
                        f"Benchmark {f_benchmark!r} does not support variant configurations; "
                        f"variants are supported exclusively for 'lsmio'."
                    )

        f_is_ssd: bool = f_effective_global_ssd
        f_trailing_ssd_seen: bool = False
        f_setup_name: Optional[str] = None
        f_archive: Optional[bool] = None
        f_resume: bool = False
        f_out_dir: Optional[str] = None
        f_wallhour: Optional[int] = None
        f_walltime: Optional[str] = None
        f_versioned: bool = False
        f_fast: bool = False

        f_idx = 0
        while f_idx < len(f_trailing_tokens):
            f_tok = f_trailing_tokens[f_idx]
            if f_tok == "--ssd":
                if f_trailing_ssd_seen or f_effective_global_ssd:
                    raise RunCliParseError("Duplicate '--ssd' option specified.")
                f_is_ssd = True
                f_trailing_ssd_seen = True
                f_idx += 1
            elif f_tok == "--versioned":
                if f_versioned:
                    raise RunCliParseError("Duplicate '--versioned' option specified.")
                f_versioned = True
                f_idx += 1
            elif f_tok == "--fast":
                if f_fast:
                    raise RunCliParseError("Duplicate '--fast' option specified.")
                f_fast = True
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
            elif f_tok == "--archive":
                if f_archive is False:
                    raise RunCliParseError(
                        "Cannot specify both '--archive' and '--no-archive'."
                    )
                f_archive = True
                f_idx += 1
            elif f_tok == "--no-archive":
                if f_archive is True:
                    raise RunCliParseError(
                        "Cannot specify both '--archive' and '--no-archive'."
                    )
                f_archive = False
                f_idx += 1
            elif f_tok == "--resume":
                # Repeating a flag is harmless, as in bmtool
                f_resume = True
                f_idx += 1
            elif f_tok in ("--out-dir", "--output-dir", "--dest"):
                if f_out_dir is not None:
                    raise RunCliParseError(
                        f"Duplicate destination option specified: {f_tok!r}."
                    )
                if f_idx + 1 >= len(f_trailing_tokens):
                    raise RunCliParseError(f"Missing value after {f_tok!r} option.")
                f_val = f_trailing_tokens[f_idx + 1]
                if f_val.startswith("-"):
                    raise RunCliParseError(
                        f"Missing valid value after {f_tok!r} option, got option-like token: {f_val!r}"
                    )
                if not f_val.strip():
                    raise RunCliParseError(
                        f"Destination path after {f_tok!r} cannot be empty."
                    )
                # Absolute paths are normalised here; relative paths stay verbatim and
                # are resolved against the benchmark root by archive.resolveArchiveDest,
                # matching bmtool/include/archive-dest.in.sh.
                f_dest_val = f_val.strip()
                f_out_dir = (
                    str(Path(f_dest_val).resolve())
                    if os.path.isabs(f_dest_val)
                    else f_dest_val
                )
                f_idx += 2
            elif f_tok in ("--time", "--walltime", "--wallhour"):
                if f_wallhour is not None or f_walltime is not None:
                    raise RunCliParseError(
                        f"Duplicate walltime option specified: {f_tok!r}."
                    )
                if f_idx + 1 >= len(f_trailing_tokens):
                    raise RunCliParseError(f"Missing value after {f_tok!r} option.")
                f_val = f_trailing_tokens[f_idx + 1]
                if f_val.startswith("-"):
                    raise RunCliParseError(
                        f"Missing valid value after {f_tok!r} option, got option-like token: {f_val!r}"
                    )
                if not f_val.strip():
                    raise RunCliParseError(
                        f"Walltime value after {f_tok!r} cannot be empty."
                    )
                f_val_str = f_val.strip()
                import re

                if re.match(r"^\d+$", f_val_str):
                    f_h = int(f_val_str)
                    if f_h <= 0:
                        raise RunCliParseError(
                            f"--time value must be greater than 0, got: {f_h}"
                        )
                    f_wallhour = max(1, min(48, f_h))
                elif re.match(r"^\d+:\d{2}:\d{2}$", f_val_str):
                    f_walltime = f_val_str
                else:
                    raise RunCliParseError(
                        f"Invalid --time/--wallhour value: {f_val!r} (must be positive integer hours or HH:MM:SS format)"
                    )
                f_idx += 2
            elif any(
                f_tok.startswith(p)
                for p in (
                    "--out-dir=",
                    "--output-dir=",
                    "--dest=",
                    "--archive=",
                    "--no-archive=",
                    "--resume=",
                    "--time=",
                    "--walltime=",
                    "--wallhour=",
                    "--versioned=",
                    "--fast=",
                )
            ):
                flag_name = f_tok.split("=")[0]
                raise RunCliParseError(
                    f"Option syntax {f_tok!r} is not supported; use '{flag_name} <value>' with separated arguments."
                )
            elif f_tok.startswith("-"):
                raise RunCliParseError(f"Unknown option: {f_tok!r}")
            else:
                raise RunCliParseError(
                    f"Unexpected extra positional argument: {f_tok!r}"
                )

        if f_versioned:
            if f_scale != "variants" or f_benchmark != "lsmio":
                raise RunCliParseError(
                    "--versioned is supported exclusively for 'lsmio variants'."
                )
            if f_archive is False:
                raise RunCliParseError(
                    "Cannot specify '--no-archive' with '--versioned'."
                )
            f_archive = True

        # bmtool accepts archive/resume/destination/walltime options only for 'variants'
        # and backends runs; plain scaling runs take just --ssd and --fast
        if f_mode != "backends" and f_scale != "variants":
            f_unsupported = [
                f_opt
                for f_opt, f_used in (
                    ("--archive/--no-archive", f_archive is not None),
                    ("--resume", f_resume),
                    ("--dest/--out-dir", f_out_dir is not None),
                    ("--time", f_wallhour is not None or f_walltime is not None),
                )
                if f_used
            ]
            if f_unsupported:
                raise RunCliParseError(
                    f"{', '.join(f_unsupported)} not supported for '{f_benchmark} {f_scale}': "
                    "only 'variants' and 'backends' runs are archived or resumed "
                    "(set BM_WALLHOUR to change the walltime)."
                )

        # bmtool environment defaults: BM_SETUP picks the lsmio setup when --setup is not
        # given (ior/lmp hard-set theirs in bmtool); BM_WALLHOUR sets the walltime of any
        # run when --time is not given
        f_env = os.environ if f_environ is None else f_environ
        if (
            f_benchmark == "lsmio"
            and f_setup_name is None
            and f_env.get("BM_SETUP", "").strip()
        ):
            f_setup_name = f_env["BM_SETUP"].strip().upper()
        if (
            f_wallhour is None
            and f_walltime is None
            and f_env.get("BM_WALLHOUR", "").strip()
        ):
            f_raw_hours = f_env["BM_WALLHOUR"].strip()
            if not f_raw_hours.isdigit() or int(f_raw_hours) <= 0:
                raise RunCliParseError(
                    f"Invalid BM_WALLHOUR value: {f_raw_hours!r} (must be a positive integer)"
                )
            f_wallhour = max(1, min(48, int(f_raw_hours)))

        return RunRequest(
            f_target=f_benchmark,
            f_scale=f_scale,
            f_mode=f_mode,
            f_backends=f_backends,
            f_ssd=f_is_ssd,
            f_setup=f_setup_name,
            f_variant=f_variant_name,
            f_variants=f_variants,
            f_archive=f_archive,
            f_resume=f_resume,
            f_out_dir=f_out_dir,
            f_wallhour=f_wallhour,
            f_walltime=f_walltime,
            f_versioned=f_versioned,
            f_fast=f_fast,
        )


def parseRunArguments(
    f_argv: Sequence[str],
    f_global_ssd: bool = False,
    f_environ: Optional[Dict[str, str]] = None,
) -> RunRequest:
    """Convenience function wrapping RunCliParser.parse."""
    return RunCliParser.parse(
        f_argv=f_argv, f_global_ssd=f_global_ssd, f_environ=f_environ
    )


class ParseRequest:
    """Immutable parsed and validated parse request."""

    __slots__ = ("m_target", "m_mode", "m_scale", "m_output_dir", "m_format", "_frozen")

    def __init__(
        self,
        f_target: str,
        f_output_dir: Optional[str] = None,
        f_format: str = "csv",
        f_mode: str = "standard",
        f_scale: Optional[str] = None,
    ) -> None:
        if f_output_dir in ("standard", "backends") and f_scale is None:
            f_mode = f_output_dir
            f_scale = f_format if f_format not in ("csv", "json") else None
            f_output_dir = None
            f_format = "csv"
        if not isinstance(f_target, str) or not f_target.strip():
            raise ValueError(f"target must be a non-empty string, got: {f_target!r}")
        if not isinstance(f_mode, str) or not f_mode.strip():
            raise ValueError(f"mode must be a non-empty string, got: {f_mode!r}")
        if f_scale is not None and (
            not isinstance(f_scale, str) or not f_scale.strip()
        ):
            raise ValueError(
                f"scale must be a non-empty string or None, got: {f_scale!r}"
            )
        if f_output_dir is not None and (
            not isinstance(f_output_dir, str) or not f_output_dir.strip()
        ):
            raise ValueError(
                f"output_dir must be a non-empty string or None, got: {f_output_dir!r}"
            )
        if not isinstance(f_format, str) or not f_format.strip():
            raise ValueError(f"format must be a non-empty string, got: {f_format!r}")
        f_norm_format = f_format.strip().lower()
        if f_norm_format not in {"csv", "json"}:
            raise ValueError(f"format must be 'csv' or 'json', got: {f_format!r}")

        super().__setattr__("m_target", f_target.strip())
        super().__setattr__("m_mode", f_mode.strip().lower())
        super().__setattr__(
            "m_scale",
            f_scale.strip().lower() if f_scale is not None else None,
        )
        super().__setattr__(
            "m_output_dir",
            f_output_dir.strip() if f_output_dir is not None else None,
        )
        super().__setattr__("m_format", f_norm_format)
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
    def mode(self) -> str:
        return self.m_mode

    @property
    def scale(self) -> Optional[str]:
        return self.m_scale

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
        f_dict: Dict[str, Any] = {
            "target": self.m_target,
            "output_dir": self.m_output_dir,
            "format": self.m_format,
        }
        if self.m_mode != "standard":
            f_dict["mode"] = self.m_mode
        if self.m_scale is not None:
            f_dict["scale"] = self.m_scale
        return f_dict

    def __repr__(self) -> str:
        return (
            f"ParseRequest(target={self.m_target!r}, "
            f"mode={self.m_mode!r}, "
            f"scale={self.m_scale!r}, "
            f"output_dir={self.m_output_dir!r}, "
            f"format={self.m_format!r})"
        )

    def __eq__(self, f_other: Any) -> bool:
        if isinstance(f_other, ParseRequest):
            return (
                self.m_target == f_other.m_target
                and self.m_mode == f_other.m_mode
                and self.m_scale == f_other.m_scale
                and self.m_output_dir == f_other.m_output_dir
                and self.m_format == f_other.m_format
            )
        return False


class ParseCliParser:
    """Pure standard-library parser for 'lsmiotool parse' CLI arguments.

    Usage:
        lsmiotool parse <target> [--output-dir <dir>] [--format <csv|json>]
        lsmiotool parse lsmio <local|bake|small|large|variants> [options]
        lsmiotool parse lsmio backends <local|bake|small|large> [options]

    Arguments:
        <target>: Run root path (also an archived one), manifest file path, bmtool-layout
            outputs directory, or benchmark name ('ior', 'lsmio', 'lmp'). A benchmark
            name selects the latest run of that benchmark under the site profile's
            benchmark root.
        <scale>: With 'lsmio', restricts the latest-run search to that scale.
            'parse lsmio variants' and 'parse lsmio backends <scale>' instead
            regenerate the reports of every outputs-* directory in the archive
            destination, like bmtool.

    Options:
        --output-dir <dir>: Destination directory for reports (default: current working
            directory; for a bmtool-layout directory, the directory itself; for the
            archive forms, the archive destination to regenerate).
        --format <format>: Report format ('csv' or 'json', default: 'csv').
    """

    VALID_FORMATS = frozenset({"csv", "json"})
    VALID_SCALES = frozenset(
        {"local", "bake", "small", "large", "variants", "baseline"}
    )

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
            raise ParseCliParseError("Missing required positional argument: <target>")

        f_target_tok = f_tokens_copy[0]
        if f_target_tok.startswith("-"):
            raise ParseCliParseError(
                f"Unexpected option {f_target_tok!r} placed before positional argument <target>."
            )

        f_target = f_target_tok.strip()
        if not f_target:
            raise ParseCliParseError("Target cannot be empty.")

        f_remaining_tokens = f_tokens_copy[1:]
        f_mode: str = "standard"
        f_scale: Optional[str] = None

        if (
            f_target.lower() == "lsmio"
            and f_remaining_tokens
            and f_remaining_tokens[0].lower() == "backends"
        ):
            f_mode = "backends"
            f_remaining_tokens.pop(0)
            if not f_remaining_tokens or f_remaining_tokens[0].startswith("-"):
                raise ParseCliParseError(
                    "Missing required positional argument: <scale> for 'parse lsmio backends'"
                )
            f_scale_tok = f_remaining_tokens.pop(0).strip().lower()
            valid_scales = frozenset({"local", "bake", "small", "large"})
            if f_scale_tok not in valid_scales:
                raise ParseCliParseError(
                    f"Invalid scale for backends parse: {f_scale_tok!r}. Must be one of: {sorted(valid_scales)}"
                )
            f_scale = f_scale_tok
        elif (
            f_target.lower() == "lsmio"
            and f_remaining_tokens
            and f_remaining_tokens[0].strip().lower() in cls.VALID_SCALES
        ):
            # bmtool form: parse lsmio <local|bake|small|large|variants>
            f_scale = f_remaining_tokens.pop(0).strip().lower()
            if f_scale == "baseline":
                f_scale = "variants"

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
                    raise ParseCliParseError("Duplicate '--format' option specified.")
                if f_idx + 1 >= len(f_remaining_tokens):
                    raise ParseCliParseError("Missing value after '--format' option.")
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
            f_mode=f_mode,
            f_scale=f_scale,
            f_output_dir=f_output_dir,
            f_format=f_format,
        )


def parseParseArguments(f_argv: Sequence[str]) -> ParseRequest:
    """Convenience function wrapping ParseCliParser.parse."""
    return ParseCliParser.parse(f_argv=f_argv)


class ArchiveCliParser:
    """Pure standard-library parser for 'lsmiotool archive' CLI arguments.

    Grammar:
        lsmiotool archive <benchmark> <scale> [<variant>] [--dest <path>] [--setup <name>] [--source <path>]

    Positional Arguments:
        <benchmark>: Required. Must be 'lsmio'.
        <scale>: Required. One of: local, bake, small, large, variants
            ('baseline' is the deprecated spelling of 'variants').
        <variant>: Optional. Supported exclusively for 'lsmio variants'.

    Options:
        --dest <path>: Archive destination directory (default: <benchmark_root>/lsmio-archive/{variants|baseline}).
            Note: '--dest=value' syntax is strictly rejected; use '--dest <path>'.
        --setup <name>: LSMIO setup naming the arm (default: $BM_SETUP, else NATIVE-M;
            for an lsmiotool run, the run's own setup).
        --source <path>: What to archive: an lsmiotool run root or a bmtool outputs
            directory (default: resolved from the benchmark root, see ArchiveMain).
    """

    VALID_BENCHMARKS = frozenset({"lsmio"})
    VALID_SCALES = frozenset({"local", "bake", "small", "large", "variants"})
    # Deprecated spelling retained so existing scripts keep working
    SCALE_ALIASES = {"baseline": "variants"}

    @classmethod
    def parse(
        cls,
        f_argv: Sequence[str],
    ) -> ArchiveRequest:
        """Parses argument sequence into an immutable canonical ArchiveRequest.

        Args:
            f_argv: Sequence of argument strings (either including or excluding leading 'archive').

        Returns:
            Canonical ArchiveRequest instance.

        Raises:
            ArchiveCliParseError: If syntax, arity, flags, or values are invalid.
            UnknownVariantError: If variant is invalid for variants scale.
        """
        if f_argv is None or isinstance(f_argv, (str, bytes)):
            raise ArchiveCliParseError(
                f"f_argv must be a sequence of argument strings, got: {type(f_argv).__name__}"
            )
        try:
            f_tokens: List[str] = list(f_argv)
        except TypeError:
            raise ArchiveCliParseError(
                f"f_argv must be iterable, got: {type(f_argv).__name__}"
            )

        for f_idx, f_elem in enumerate(f_tokens):
            if not isinstance(f_elem, str):
                raise ArchiveCliParseError(
                    f"All argv elements must be strings, got {type(f_elem).__name__} at index {f_idx}"
                )

        # Strictly reject --dest=value anywhere in tokens
        for f_tok in f_tokens:
            if f_tok.startswith("--dest="):
                raise ArchiveCliParseError(
                    f"Prohibit '--dest=value' syntax ({f_tok!r}); use '--dest <path>' with explicit separate argument."
                )

        # Separate pre-'archive' and post-'archive' tokens if 'archive' is present
        f_archive_indices: List[int] = [
            f_idx for f_idx, f_tok in enumerate(f_tokens) if f_tok.lower() == "archive"
        ]

        if f_archive_indices:
            f_archive_idx = f_archive_indices[0]
            f_pre_archive_tokens = f_tokens[:f_archive_idx]
            f_post_archive_tokens = f_tokens[f_archive_idx + 1 :]

            for f_pre_tok in f_pre_archive_tokens:
                raise ArchiveCliParseError(
                    f"Unexpected token before 'archive': {f_pre_tok!r}"
                )
        else:
            f_post_archive_tokens = f_tokens[:]

        # Validate required positional arguments
        if not f_post_archive_tokens:
            raise ArchiveCliParseError(
                "Missing required positional arguments: <benchmark> <scale>"
            )

        # Validate benchmark (positional 0)
        f_benchmark_tok = f_post_archive_tokens[0]
        if f_benchmark_tok.startswith("-"):
            raise ArchiveCliParseError(
                f"Unexpected option {f_benchmark_tok!r} placed before positional arguments."
            )

        f_benchmark = f_benchmark_tok.strip().lower()
        if f_benchmark not in cls.VALID_BENCHMARKS:
            raise ArchiveCliParseError(
                f"Invalid benchmark: {f_benchmark_tok!r}. Must be one of: {sorted(cls.VALID_BENCHMARKS)}"
            )

        if len(f_post_archive_tokens) < 2:
            raise ArchiveCliParseError("Missing required positional argument: <scale>")

        # Validate scale (positional 1)
        f_scale_tok = f_post_archive_tokens[1]
        if f_scale_tok.startswith("-"):
            raise ArchiveCliParseError(
                f"Unexpected option {f_scale_tok!r} placed between positional arguments."
            )

        f_scale = f_scale_tok.strip().lower()
        f_scale = cls.SCALE_ALIASES.get(f_scale, f_scale)
        if f_scale not in cls.VALID_SCALES:
            raise ArchiveCliParseError(
                f"Invalid scale: {f_scale_tok!r}. Must be one of: {sorted(cls.VALID_SCALES)}"
            )

        # Parse trailing options and optional positional variant
        from lsmiotool.lib.variants import VariantCatalogue

        f_trailing_tokens = f_post_archive_tokens[2:]
        f_variant_name: Optional[str] = None

        if f_scale == "variants":
            if f_trailing_tokens and not f_trailing_tokens[0].startswith("-"):
                f_variant_tok = f_trailing_tokens[0]
                f_trailing_tokens = f_trailing_tokens[1:]
                f_rec = VariantCatalogue.resolve(f_variant_tok)
                f_variant_name = f_rec.tokens if f_rec.tokens else None
        else:
            if f_trailing_tokens and not f_trailing_tokens[0].startswith("-"):
                raise ArchiveCliParseError(
                    f"Unexpected extra positional argument: {f_trailing_tokens[0]!r}"
                )

        f_dest_path: Optional[str] = None
        f_dest_seen: bool = False
        f_setup: Optional[str] = None
        f_source: Optional[str] = None

        f_idx = 0
        while f_idx < len(f_trailing_tokens):
            f_tok = f_trailing_tokens[f_idx]
            if f_tok in ("--setup", "--source"):
                f_opt_seen = f_setup if f_tok == "--setup" else f_source
                if f_opt_seen is not None:
                    raise ArchiveCliParseError(f"Duplicate '{f_tok}' option specified.")
                if f_idx + 1 >= len(f_trailing_tokens):
                    raise ArchiveCliParseError(f"Missing value after '{f_tok}' option.")
                f_val = f_trailing_tokens[f_idx + 1].strip()
                if not f_val or f_val.startswith("-"):
                    raise ArchiveCliParseError(
                        f"Missing valid value after '{f_tok}' option, got: {f_trailing_tokens[f_idx + 1]!r}"
                    )
                if f_tok == "--setup":
                    f_setup = cls.validateSetup(f_val)
                else:
                    f_source = f_val
                f_idx += 2
            elif f_tok == "--dest":
                if f_dest_seen:
                    raise ArchiveCliParseError("Duplicate '--dest' option specified.")
                if f_idx + 1 >= len(f_trailing_tokens):
                    raise ArchiveCliParseError("Missing value after '--dest' option.")
                f_val = f_trailing_tokens[f_idx + 1]
                if f_val.startswith("-"):
                    raise ArchiveCliParseError(
                        f"Missing valid value after '--dest' option, got option-like token: {f_val!r}"
                    )
                if not f_val.strip():
                    raise ArchiveCliParseError("Destination path cannot be empty.")
                f_dest_path = f_val.strip()
                f_dest_seen = True
                f_idx += 2
            elif f_tok.startswith("-"):
                raise ArchiveCliParseError(f"Unknown option: {f_tok!r}")
            else:
                raise ArchiveCliParseError(
                    f"Unexpected extra positional argument: {f_tok!r}"
                )

        return ArchiveRequest(
            f_target=f_benchmark,
            f_scale=f_scale,
            f_variant=f_variant_name,
            f_dest=f_dest_path,
            f_setup=f_setup,
            f_source=f_source,
        )

    @classmethod
    def validateSetup(cls, f_setup: str) -> str:
        """Canonical (upper-case) LSMIO setup name, as 'run --setup' accepts it.

        Raises:
            ArchiveCliParseError: For an unknown setup.
        """
        from lsmiotool.lib.benchmarks import LsmioAdapter

        f_norm = f_setup.strip().upper()
        if f_norm not in LsmioAdapter.ALLOWED_SETUPS:
            raise ArchiveCliParseError(
                f"Invalid setup: {f_setup!r}. Must be one of: {list(LsmioAdapter.ALLOWED_SETUPS)}"
            )
        return f_norm


def parseArchiveArguments(f_argv: Sequence[str]) -> ArchiveRequest:
    """Convenience function wrapping ArchiveCliParser.parse."""
    return ArchiveCliParser.parse(f_argv=f_argv)


class CompareNodesRequest:
    """Immutable parsed and validated request value object for 'compare nodes'."""

    __slots__ = (
        "m_folder",
        "m_op",
        "m_stripes",
        "m_blocksize",
        "m_output_dir",
        "m_all",
        "_frozen",
    )

    def __init__(
        self,
        f_folder: str,
        f_op: Optional[str] = None,
        f_stripes: int = 4,
        f_blocksize: str = "1M",
        f_output_dir: Optional[str] = None,
        f_all: bool = False,
    ) -> None:
        if not isinstance(f_folder, str) or not f_folder.strip():
            raise ValueError(f"folder must be a non-empty string, got: {f_folder!r}")
        if not isinstance(f_all, bool):
            raise ValueError(f"all must be a boolean, got: {f_all!r}")
        # With --all the operation is optional: 'both' charts read and write
        if f_op is None and f_all:
            f_op = "both"
        if not isinstance(f_op, str) or not f_op.strip():
            raise ValueError(f"op must be a non-empty string, got: {f_op!r}")
        f_norm_op = f_op.strip().lower()
        f_valid_ops = ("read", "write", "both") if f_all else ("read", "write")
        if f_norm_op not in f_valid_ops:
            raise ValueError(f"op must be one of {f_valid_ops}, got: {f_op!r}")
        if (
            isinstance(f_stripes, bool)
            or not isinstance(f_stripes, int)
            or f_stripes <= 0
        ):
            raise ValueError(f"stripes must be a positive integer, got: {f_stripes!r}")
        if not isinstance(f_blocksize, str) or not f_blocksize.strip():
            raise ValueError(
                f"blocksize must be a non-empty string, got: {f_blocksize!r}"
            )
        f_norm_bs = f_blocksize.strip().upper()
        if f_norm_bs not in ("64K", "1M", "8M"):
            raise ValueError(
                f"blocksize must be one of ('64K', '1M', '8M'), got: {f_blocksize!r}"
            )
        if f_output_dir is not None and (
            not isinstance(f_output_dir, str) or not f_output_dir.strip()
        ):
            raise ValueError(
                f"output_dir must be a non-empty string or None, got: {f_output_dir!r}"
            )

        super().__setattr__("m_folder", f_folder.strip())
        super().__setattr__("m_op", f_norm_op)
        super().__setattr__("m_stripes", f_stripes)
        super().__setattr__("m_blocksize", f_norm_bs)
        super().__setattr__(
            "m_output_dir",
            f_output_dir.strip() if f_output_dir is not None else None,
        )
        super().__setattr__("m_all", f_all)
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
    def submode(self) -> str:
        return "nodes"

    @property
    def all(self) -> bool:
        return self.m_all

    @property
    def folder(self) -> str:
        return self.m_folder

    @property
    def op(self) -> str:
        return self.m_op

    @property
    def stripes(self) -> int:
        return self.m_stripes

    @property
    def blocksize(self) -> str:
        return self.m_blocksize

    @property
    def output_dir(self) -> Optional[str]:
        return self.m_output_dir

    @property
    def outputDir(self) -> Optional[str]:
        return self.m_output_dir

    def toDict(self) -> Dict[str, Any]:
        return {
            "submode": "nodes",
            "folder": self.m_folder,
            "op": self.m_op,
            "stripes": self.m_stripes,
            "blocksize": self.m_blocksize,
            "output_dir": self.m_output_dir,
            "all": self.m_all,
        }

    def __repr__(self) -> str:
        return (
            f"CompareNodesRequest(folder={self.m_folder!r}, "
            f"op={self.m_op!r}, stripes={self.m_stripes!r}, "
            f"blocksize={self.m_blocksize!r}, "
            f"output_dir={self.m_output_dir!r}, all={self.m_all!r})"
        )

    def __eq__(self, f_other: Any) -> bool:
        if isinstance(f_other, CompareNodesRequest):
            return (
                self.m_folder == f_other.m_folder
                and self.m_op == f_other.m_op
                and self.m_stripes == f_other.m_stripes
                and self.m_blocksize == f_other.m_blocksize
                and self.m_output_dir == f_other.m_output_dir
                and self.m_all == f_other.m_all
            )
        return False

    def __hash__(self) -> int:
        return hash(
            (
                self.m_folder,
                self.m_op,
                self.m_stripes,
                self.m_blocksize,
                self.m_output_dir,
                self.m_all,
            )
        )


class CompareVariantsRequest:
    """Immutable parsed and validated request value object for 'compare variants'."""

    __slots__ = (
        "m_archive_folder",
        "m_op",
        "m_stripes",
        "m_blocksize",
        "m_all",
        "m_output_dir",
        "_frozen",
    )

    def __init__(
        self,
        f_archive_folder: str,
        f_op: str = "both",
        f_stripes: int = 4,
        f_blocksize: str = "1M",
        f_all: bool = False,
        f_output_dir: Optional[str] = None,
    ) -> None:
        if not isinstance(f_archive_folder, str) or not f_archive_folder.strip():
            raise ValueError(
                f"archive_folder must be a non-empty string, got: {f_archive_folder!r}"
            )
        if not isinstance(f_op, str) or not f_op.strip():
            raise ValueError(f"op must be a non-empty string, got: {f_op!r}")
        f_norm_op = f_op.strip().lower()
        if f_norm_op not in ("read", "write", "both"):
            raise ValueError(
                f"op must be one of ('read', 'write', 'both'), got: {f_op!r}"
            )
        if (
            isinstance(f_stripes, bool)
            or not isinstance(f_stripes, int)
            or f_stripes not in (4, 16)
        ):
            raise ValueError(f"stripes must be 4 or 16, got: {f_stripes!r}")
        if not isinstance(f_blocksize, str) or not f_blocksize.strip():
            raise ValueError(
                f"blocksize must be a non-empty string, got: {f_blocksize!r}"
            )
        f_norm_bs = f_blocksize.strip().upper()
        if f_norm_bs not in ("64K", "1M", "8M"):
            raise ValueError(
                f"blocksize must be one of ('64K', '1M', '8M'), got: {f_blocksize!r}"
            )
        if not isinstance(f_all, bool):
            raise ValueError(f"all must be a boolean, got: {f_all!r}")
        if f_output_dir is not None and (
            not isinstance(f_output_dir, str) or not f_output_dir.strip()
        ):
            raise ValueError(
                f"output_dir must be a non-empty string or None, got: {f_output_dir!r}"
            )

        super().__setattr__("m_archive_folder", f_archive_folder.strip())
        super().__setattr__("m_op", f_norm_op)
        super().__setattr__("m_stripes", f_stripes)
        super().__setattr__("m_blocksize", f_norm_bs)
        super().__setattr__("m_all", f_all)
        super().__setattr__(
            "m_output_dir",
            f_output_dir.strip() if f_output_dir is not None else None,
        )
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
    def submode(self) -> str:
        return "variants"

    @property
    def archive_folder(self) -> str:
        return self.m_archive_folder

    @property
    def archiveFolder(self) -> str:
        return self.m_archive_folder

    @property
    def folder(self) -> str:
        return self.m_archive_folder

    @property
    def op(self) -> str:
        return self.m_op

    @property
    def stripes(self) -> int:
        return self.m_stripes

    @property
    def blocksize(self) -> str:
        return self.m_blocksize

    @property
    def all(self) -> bool:
        return self.m_all

    @property
    def output_dir(self) -> Optional[str]:
        return self.m_output_dir

    @property
    def outputDir(self) -> Optional[str]:
        return self.m_output_dir

    def toDict(self) -> Dict[str, Any]:
        return {
            "submode": "variants",
            "archive_folder": self.m_archive_folder,
            "folder": self.m_archive_folder,
            "op": self.m_op,
            "stripes": self.m_stripes,
            "blocksize": self.m_blocksize,
            "all": self.m_all,
            "output_dir": self.m_output_dir,
        }

    def __repr__(self) -> str:
        return (
            f"CompareVariantsRequest(archive_folder={self.m_archive_folder!r}, "
            f"op={self.m_op!r}, stripes={self.m_stripes!r}, "
            f"blocksize={self.m_blocksize!r}, all={self.m_all!r}, "
            f"output_dir={self.m_output_dir!r})"
        )

    def __eq__(self, f_other: Any) -> bool:
        if isinstance(f_other, CompareVariantsRequest):
            return (
                self.m_archive_folder == f_other.m_archive_folder
                and self.m_op == f_other.m_op
                and self.m_stripes == f_other.m_stripes
                and self.m_blocksize == f_other.m_blocksize
                and self.m_all == f_other.m_all
                and self.m_output_dir == f_other.m_output_dir
            )
        return False

    def __hash__(self) -> int:
        return hash(
            (
                self.m_archive_folder,
                self.m_op,
                self.m_stripes,
                self.m_blocksize,
                self.m_all,
                self.m_output_dir,
            )
        )


# Backward compatibility alias for existing test imports and internal callers
CompareArchiveRequest = CompareVariantsRequest


class CompareCliParser:
    """Pure standard-library two-tier parser for 'lsmiotool compare' CLI arguments.

    Grammar:
        lsmiotool compare nodes <folder> <read|write> [<stripes>] [<blocksize>] [--output-dir <dir>]
        lsmiotool compare nodes <folder> [read|write] --all [--output-dir <dir>]
        lsmiotool compare variants <archive_folder> [read|write|both] [<stripes>] [<blocksize>] [--all] [--output-dir <dir>]
    """

    VALID_SUBMODES: Tuple[str, ...] = ("nodes", "variants")
    VALID_OPERATIONS_NODES: Tuple[str, ...] = ("read", "write")
    VALID_OPERATIONS_VARIANTS: Tuple[str, ...] = ("read", "write", "both")
    VALID_OPERATIONS: Tuple[str, ...] = ("read", "write", "both")
    VALID_STRIPES: Tuple[int, ...] = (4, 16)
    VALID_BLOCKSIZES: Tuple[str, ...] = ("64K", "1M", "8M")
    WORKLOAD_PERMUTATIONS: Tuple[Tuple[int, str], ...] = (
        (4, "64K"),
        (16, "64K"),
        (4, "1M"),
        (16, "1M"),
        (4, "8M"),
        (16, "8M"),
    )

    @classmethod
    def parse(
        cls,
        f_argv: Sequence[str],
    ) -> Union[CompareNodesRequest, CompareVariantsRequest]:
        """Parses argument sequence into an immutable canonical CompareNodesRequest or CompareVariantsRequest.

        Args:
            f_argv: Sequence of argument strings (either including or excluding leading 'compare').

        Returns:
            Canonical CompareNodesRequest or CompareVariantsRequest instance.

        Raises:
            CompareCliParseError: If syntax, arity, flags, or values are invalid.
        """
        if f_argv is None or isinstance(f_argv, (str, bytes)):
            raise CompareCliParseError(
                f"f_argv must be a sequence of argument strings, got: {type(f_argv).__name__}"
            )
        try:
            f_tokens: List[str] = list(f_argv)
        except TypeError:
            raise CompareCliParseError(
                f"f_argv must be iterable, got: {type(f_argv).__name__}"
            )

        for f_idx, f_elem in enumerate(f_tokens):
            if not isinstance(f_elem, str):
                raise CompareCliParseError(
                    f"All argv elements must be strings, got {type(f_elem).__name__} at index {f_idx}"
                )

        for f_tok in f_tokens:
            if f_tok.startswith("--all="):
                raise CompareCliParseError(
                    f"Prohibit '--all=value' syntax ({f_tok!r}); '--all' takes no value."
                )
            if f_tok.startswith("--output-dir="):
                raise CompareCliParseError(
                    f"Prohibit '--output-dir=value' syntax ({f_tok!r}); use '--output-dir <dir>' with explicit separate argument."
                )

        f_cmd_indices: List[int] = [
            f_idx
            for f_idx, f_tok in enumerate(f_tokens)
            if f_tok.lower() in ("compare", "compare-archive")
        ]

        if f_cmd_indices:
            f_cmd_idx = f_cmd_indices[0]
            f_pre_tokens = f_tokens[:f_cmd_idx]
            f_post_tokens = f_tokens[f_cmd_idx + 1 :]

            for f_pre_tok in f_pre_tokens:
                raise CompareCliParseError(
                    f"Unexpected token before {f_tokens[f_cmd_idx]!r}: {f_pre_tok!r}"
                )
        else:
            f_post_tokens = f_tokens[:]

        if not f_post_tokens:
            raise CompareCliParseError(
                "Missing required submode: 'nodes' or 'variants'"
            )

        f_submode_tok = f_post_tokens[0]
        f_submode_norm = f_submode_tok.strip().lower()

        if f_submode_norm == "nodes":
            return cls._parseNodes(f_post_tokens[1:])
        elif f_submode_norm == "variants":
            return cls._parseVariants(f_post_tokens[1:])
        else:
            raise CompareCliParseError(
                f"Invalid submode {f_submode_tok!r}. Must be 'nodes' or 'variants'"
            )

    @classmethod
    def _parseNodes(
        cls,
        f_tokens: Sequence[str],
    ) -> CompareNodesRequest:
        if not f_tokens:
            raise CompareCliParseError("Missing required positional argument: <folder>")

        f_folder_tok = f_tokens[0]
        if f_folder_tok.startswith("-"):
            raise CompareCliParseError(
                f"Unexpected option {f_folder_tok!r} placed before positional argument <folder>."
            )

        f_folder = f_folder_tok.strip()
        if not f_folder:
            raise CompareCliParseError("Folder path cannot be empty.")

        f_op: Optional[str] = None
        f_stripes: int = 4
        f_blocksize: str = "1M"
        f_output_dir: Optional[str] = None
        f_all = f_tokens.count("--all") > 0
        if f_tokens.count("--all") > 1:
            raise CompareCliParseError("Duplicate '--all' option specified.")

        f_remaining_tokens = f_tokens[1:]
        f_pos_idx = 0
        f_rem_idx = 0

        while f_rem_idx < len(f_remaining_tokens):
            f_tok = f_remaining_tokens[f_rem_idx]
            if f_tok.startswith("-"):
                break

            if f_pos_idx == 0:
                f_op_norm = f_tok.strip().lower()
                if f_op_norm not in cls.VALID_OPERATIONS_NODES:
                    raise CompareCliParseError(
                        f"Invalid operation: {f_tok!r}. Must be 'read' or 'write'"
                    )
                f_op = f_op_norm
                f_pos_idx += 1
                f_rem_idx += 1
            elif f_pos_idx == 1:
                try:
                    f_stripes_val = int(f_tok)
                except ValueError:
                    raise CompareCliParseError(
                        f"Invalid stripes: {f_tok!r}. Must be one of: {cls.VALID_STRIPES}"
                    )
                if f_stripes_val not in cls.VALID_STRIPES:
                    raise CompareCliParseError(
                        f"Invalid stripes: {f_tok!r}. Must be one of: {cls.VALID_STRIPES}"
                    )
                f_stripes = f_stripes_val
                f_pos_idx += 1
                f_rem_idx += 1
            elif f_pos_idx == 2:
                f_bs_norm = f_tok.strip().upper()
                if f_bs_norm not in cls.VALID_BLOCKSIZES:
                    raise CompareCliParseError(
                        f"Invalid blocksize: {f_tok!r}. Must be one of: {cls.VALID_BLOCKSIZES}"
                    )
                f_blocksize = f_bs_norm
                f_pos_idx += 1
                f_rem_idx += 1
            else:
                raise CompareCliParseError(
                    f"Unexpected extra positional argument: {f_tok!r}"
                )

        if f_op is None and not f_all:
            raise CompareCliParseError(
                "Missing required positional argument: <read|write>"
            )
        if f_all and f_pos_idx > 1:
            raise CompareCliParseError(
                "'--all' charts every <stripes> and <blocksize>; do not give them"
            )

        f_output_dir_seen = False

        while f_rem_idx < len(f_remaining_tokens):
            f_tok = f_remaining_tokens[f_rem_idx]
            if f_tok == "--output-dir":
                if f_output_dir_seen:
                    raise CompareCliParseError(
                        "Duplicate '--output-dir' option specified."
                    )
                if f_rem_idx + 1 >= len(f_remaining_tokens):
                    raise CompareCliParseError(
                        "Missing value after '--output-dir' option."
                    )
                f_val = f_remaining_tokens[f_rem_idx + 1]
                if f_val.startswith("-"):
                    raise CompareCliParseError(
                        f"Missing valid value after '--output-dir' option, got option-like token: {f_val!r}"
                    )
                if not f_val.strip():
                    raise CompareCliParseError("Output directory path cannot be empty.")
                f_output_dir = f_val.strip()
                f_output_dir_seen = True
                f_rem_idx += 2
            elif f_tok == "--all":
                f_rem_idx += 1
            elif f_tok.startswith("-"):
                raise CompareCliParseError(f"Unknown option: {f_tok!r}")
            else:
                raise CompareCliParseError(
                    f"Unexpected extra positional argument: {f_tok!r}"
                )

        return CompareNodesRequest(
            f_folder=f_folder,
            f_op=f_op,
            f_stripes=f_stripes,
            f_blocksize=f_blocksize,
            f_output_dir=f_output_dir,
            f_all=f_all,
        )

    @classmethod
    def _parseVariants(
        cls,
        f_tokens: Sequence[str],
    ) -> CompareVariantsRequest:
        if not f_tokens:
            raise CompareCliParseError(
                "Missing required positional argument: <archive_folder>"
            )

        f_archive_folder_tok = f_tokens[0]
        if f_archive_folder_tok.startswith("-"):
            raise CompareCliParseError(
                f"Unexpected option {f_archive_folder_tok!r} placed before positional argument <archive_folder>."
            )

        f_archive_folder = f_archive_folder_tok.strip()
        if not f_archive_folder:
            raise CompareCliParseError("Archive folder path cannot be empty.")

        f_op: str = "both"
        f_stripes: int = 4
        f_blocksize: str = "1M"
        f_all: bool = False
        f_output_dir: Optional[str] = None

        f_remaining_tokens = f_tokens[1:]
        f_pos_idx = 0
        f_rem_idx = 0

        while f_rem_idx < len(f_remaining_tokens):
            f_tok = f_remaining_tokens[f_rem_idx]
            if f_tok.startswith("-"):
                break

            if f_pos_idx == 0:
                f_op_norm = f_tok.strip().lower()
                if f_op_norm not in cls.VALID_OPERATIONS_VARIANTS:
                    raise CompareCliParseError(
                        f"Invalid operation: {f_tok!r}. Must be one of: {cls.VALID_OPERATIONS_VARIANTS}"
                    )
                f_op = f_op_norm
                f_pos_idx += 1
                f_rem_idx += 1
            elif f_pos_idx == 1:
                try:
                    f_stripes_val = int(f_tok)
                except ValueError:
                    raise CompareCliParseError(
                        f"Invalid stripes: {f_tok!r}. Must be one of: {cls.VALID_STRIPES}"
                    )
                if f_stripes_val not in cls.VALID_STRIPES:
                    raise CompareCliParseError(
                        f"Invalid stripes: {f_tok!r}. Must be one of: {cls.VALID_STRIPES}"
                    )
                f_stripes = f_stripes_val
                f_pos_idx += 1
                f_rem_idx += 1
            elif f_pos_idx == 2:
                f_bs_norm = f_tok.strip().upper()
                if f_bs_norm not in cls.VALID_BLOCKSIZES:
                    raise CompareCliParseError(
                        f"Invalid blocksize: {f_tok!r}. Must be one of: {cls.VALID_BLOCKSIZES}"
                    )
                f_blocksize = f_bs_norm
                f_pos_idx += 1
                f_rem_idx += 1
            else:
                raise CompareCliParseError(
                    f"Unexpected extra positional argument: {f_tok!r}"
                )

        f_all_seen = False
        f_output_dir_seen = False

        while f_rem_idx < len(f_remaining_tokens):
            f_tok = f_remaining_tokens[f_rem_idx]
            if f_tok == "--all":
                if f_all_seen:
                    raise CompareCliParseError("Duplicate '--all' option specified.")
                f_all = True
                f_all_seen = True
                f_rem_idx += 1
            elif f_tok == "--output-dir":
                if f_output_dir_seen:
                    raise CompareCliParseError(
                        "Duplicate '--output-dir' option specified."
                    )
                if f_rem_idx + 1 >= len(f_remaining_tokens):
                    raise CompareCliParseError(
                        "Missing value after '--output-dir' option."
                    )
                f_val = f_remaining_tokens[f_rem_idx + 1]
                if f_val.startswith("-"):
                    raise CompareCliParseError(
                        f"Missing valid value after '--output-dir' option, got option-like token: {f_val!r}"
                    )
                if not f_val.strip():
                    raise CompareCliParseError("Output directory path cannot be empty.")
                f_output_dir = f_val.strip()
                f_output_dir_seen = True
                f_rem_idx += 2
            elif f_tok.startswith("-"):
                raise CompareCliParseError(f"Unknown option: {f_tok!r}")
            else:
                raise CompareCliParseError(
                    f"Unexpected extra positional argument: {f_tok!r}"
                )
        if f_all and f_pos_idx > 1:
            raise CompareCliParseError(
                "'--all' charts every <stripes> and <blocksize>; do not give them"
            )

        return CompareVariantsRequest(
            f_archive_folder=f_archive_folder,
            f_op=f_op,
            f_stripes=f_stripes,
            f_blocksize=f_blocksize,
            f_all=f_all,
            f_output_dir=f_output_dir,
        )


def parseCompareArguments(
    f_argv: Sequence[str],
) -> Union[CompareNodesRequest, CompareVariantsRequest]:
    """Convenience function wrapping CompareCliParser.parse."""
    return CompareCliParser.parse(f_argv=f_argv)


def parseCompareArchiveArguments(
    f_argv: Sequence[str],
) -> CompareVariantsRequest:
    """Compatibility wrapper delegating to CompareCliParser.parse in variants mode."""
    if f_argv is None or isinstance(f_argv, (str, bytes)):
        raise CompareCliParseError(
            f"f_argv must be a sequence of argument strings, got: {type(f_argv).__name__}"
        )
    try:
        tokens = list(f_argv)
    except TypeError:
        raise CompareCliParseError(
            f"f_argv must be iterable, got: {type(f_argv).__name__}"
        )
    for f_idx, f_elem in enumerate(tokens):
        if not isinstance(f_elem, str):
            raise CompareCliParseError(
                f"All argv elements must be strings, got {type(f_elem).__name__} at index {f_idx}"
            )
    if not tokens or (tokens[0] != "variants" and tokens[0] != "compare-archive"):
        tokens.insert(0, "variants")
    elif tokens and tokens[0] == "compare-archive":
        tokens[0] = "variants"
    req = CompareCliParser.parse(tokens)
    if isinstance(req, CompareVariantsRequest):
        return req
    raise CompareCliParseError("Expected variants request")


# Backward compatibility alias
CompareArchiveCliParser = CompareCliParser


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
