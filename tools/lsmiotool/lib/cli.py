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
  cancel <run root | run id>  stop a running 'run' (its job is cancelled)
  compare <nodes|variants> <folder> ... [--output-dir <dir>] [--all]
  load-modules  load needed HPC modules
  parse <target> [--output-dir <dir>] [--format <csv|json>]
  parse ior <local|bake|small|large> [--output-dir <dir>]
  parseLegacy <ior|lsmio|lmp> <local|bake|small|large|variants> [<path>]
  parseLegacy lsmio backends <local|bake|small|large> [<path>]
  run <ior|lsmio|lmp> <local|bake|small|large|variants> [<variants>] [--ssd] [--setup <name>] [--archive|--no-archive] [--resume] [--out-dir <dir>] [--versioned] [--fast] [--foreground]
  run lsmio backends <local|bake|small|large> [<backends>] [--ssd] [--archive|--no-archive] [--resume] [--out-dir <dir>] [--time <hours>] [--nodes <list>] [--fast] [--foreground]
  run ior <local|bake|small|large> [<ior setups>] [--ssd] [--setup <IOR setup>] [--archive|--no-archive] [--resume] [--out-dir <dir>] [--time <hours>] [--nodes <list>] [--fast] [--foreground]
  run epocpp backends <local|bake|small|large> [<backends>] [--ssd] [--archive|--no-archive] [--resume] [--out-dir <dir>] [--time <hours>] [--repeats <n>] [--nodes <list>] [--fast] [--foreground]

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
  <benchmark>   Supported benchmarks: lsmio, ior
  <scale>       Supported scales: local, bake, small, large, variants
                ('baseline' is accepted as the deprecated spelling of 'variants');
                ior: local, bake, small, large. An ior run is archived as
                outputs-ior[-<setup>] in <benchmark_root>/lsmio-archive/ior/<scale>.
  <variant>     Optional variant configuration for 'lsmio variants'
                (e.g. btree, mmap-btree, wbuf-512m). Only supported for 'lsmio variants'.

Options:
  --dest <path> Archive destination directory (default: <benchmark_root>/lsmio-archive/{variants|baseline};
                ior/<scale> for ior, epocpp/<scale> for epocpp).
                Relative paths resolve against <benchmark_root>. BM_ARCHIVE_DEST is ignored, as in bmtool.
                Note: '--dest=value' syntax is strictly rejected; use '--dest <path>'.
  --setup <name>
                LSMIO setup naming the arm, outputs-<arm> (default: $BM_SETUP, else NATIVE;
                for an lsmiotool run, the run's own setup). For ior: the IOR setup of the
                run to archive (BASE, COLLECTIVE, HDF5, HDF5-C, FSYNC, REVERSE).
  --source <path>
                What to archive: an lsmiotool run root, or bmtool's live outputs directory
                <benchmark_root>/lsmio/outputs (the only bmtool directory moved, as in bmtool).
                The run root of any arm of a variants, --versioned or backends run archives that
                whole run: each finished point (every combination and rank succeeded) not
                archived yet, as :run/:base pairs or outputs-<backend>/<nodes>, in the run's own
                destination unless --dest is given (<variant> is not used). An existing
                <nodes> dir of another run is never replaced. This picks up what 'run' left,
                e.g. after --no-archive or when its process ended before its jobs did; a run
                still running is refused.

Source (default): <benchmark_root> is the site profile's benchmark root.
  - <benchmark_root>/lsmio/outputs, when it holds bmtool outputs: moved to
    <dest>/outputs-<arm> and recreated empty, like bmtool archive.
  - otherwise the latest lsmiotool run of 'lsmio <scale>' (and <variant>) under
    <benchmark_root>/runs: its succeeded points are copied into <dest>/outputs-<arm>
    in bmtool's layout with reports; the run root is left in place.
  Both present is an error: pick one with --source.
  For ior, only lsmiotool runs: the latest standalone run of 'ior <scale>' (made before
  'run ior' ran its setups as arms); its points go to <dest>/outputs-ior[-<setup>]/<nodes>
  with ior-report.csv. A 'run ior' run archives itself, or with --source <one of its
  run roots>.
"""

RUN_HELP_TEXT = """Usage:
  lsmiotool run <benchmark> <scale> [<variants>] [--ssd] [--setup <name>] [--archive|--no-archive] [--resume] [--out-dir <path>] [--versioned] [--fast] [--foreground]
  lsmiotool run lsmio backends <scale> [<backends>] [--ssd] [--archive|--no-archive] [--resume] [--out-dir <path>] [--time <hours>] [--nodes <list>] [--fast] [--foreground]
  lsmiotool run ior <local|bake|small|large> [<ior setups>] [--ssd] [--setup <IOR setup>] [--archive|--no-archive] [--resume] [--out-dir <path>] [--time <hours>] [--nodes <list>] [--fast] [--foreground]
  lsmiotool run epocpp backends <local|bake|small|large> [<backends>] [--ssd] [--archive|--no-archive] [--resume] [--out-dir <path>] [--time <hours>] [--repeats <n>] [--nodes <list>] [--fast] [--foreground]

Arguments:
  <benchmark>   Supported benchmarks: ior, lsmio, lmp, epocpp ('run epocpp backends')
  <scale>       Supported scales: local, bake, small, large, variants
                (Note: 'lmp large' is strictly unsupported and rejected)
  <backends>    Optional comma-separated list of backends (default: adios2,native,plugin,rocksdb;
                also leveldb). Each backend has a -sync arm (adios2-sync, native-sync,
                plugin-sync, rocksdb-sync, leveldb-sync): the same benchmark with
                --lsmio-always-flush (sync puts; for ADIOS2, Put with adios2::Mode::Sync).
                Each scale point is one job running the backends one after another.
                Only supported for 'lsmiotool run lsmio backends'.
  <ior setups>  Optional comma-separated list of IOR setups for an ior scaling run
                (default: base,collective,hdf5,hdf5-collective; also fsync, reverse).
                Each scale point is one job running the setups one after another, and
                each is archived like a backend, as outputs-ior[-<setup>]/<nodes> in
                <benchmark_root>/lsmio-archive/ior/<scale> ('parse ior <scale>' regenerates
                its reports). '--setup <IOR setup>' runs that setup alone.
  <backends> (epocpp)
                Optional comma-separated list of EPOCpp backends (default:
                posix,adios2,plugin,native). Each scale point is one job running, one
                after another, the no-output baseline (epocpp-baseline), each backend's
                wall-time arm (epocpp-<backend>) and its bandwidth arm
                (epocpp-<backend>-bw, epocpp --io-benchmark -m), each over the 6 Lustre
                combinations with --repeats runs. The scales run the recommended 2D
                two-stream decks: small (128x128) for local, bake and small (2-48
                nodes),
                large (1024x1024) for large (8-64 nodes). Archived to
                <benchmark_root>/lsmio-archive/epocpp/<scale>/outputs-<arm>/<nodes>.
  <variants>    Optional single variant, comma-separated list of variants
                (e.g. btree,no-manoff,autotune), or 'most' or 'all'
                for the baseline and all 25 variants.
                Only supported for 'lsmio variants'.

Options:
  --ssd         Use SSD storage class (default: HDD).
  --setup <name>
                Explicit benchmark setup profile (e.g. BASE, HDF5, NATIVE, ROCKSDB, LSMIO).
                Note: '--setup=value' syntax is strictly rejected; use '--setup <name>'.
  --archive     Archive each scale point when its job ends. On by default for 'backends' and
                ior scaling runs, for 'variants' with one or more variants and for
                --versioned; a 'variants' run of the baseline alone is archived only with
                --archive.
  --no-archive  Do not archive (not allowed with --versioned).
  --resume      Skip a variant whose outputs-<arm>:run archive exists, or a backend's (IOR
                setup's) scale point whose outputs-<backend>/<nodes> archive exists. A
                baseline-alone or a --versioned run without variants always runs again.
  --out-dir <path>
                Explicit archive destination directory (default: <benchmark_root>/lsmio-archive/{backends/<scale>|ior/<scale>|epocpp/<scale>|variants|variants-versioned}).
                Aliases: --output-dir <path>, --dest <path>.
                Note: '--out-dir=value' syntax is strictly rejected; use separated arguments.
  --time <hours>
                Explicit job walltime limit in hours (aliases: --walltime, --wallhour, clamped to [1, 48]).
                Overrides the default dynamic scaling: 2 + total_runs * 2 hours for 'variants'
                (120 minutes per matrix run + 2 hours safety headroom), and
                2 + arms * max(1, nodes // 3) hours for 'lsmio backends' and 'ior' scaling runs
                (arms: backends or IOR setups). Ignored on a site with a fixed walltime (PBS
                job templates, e.g. isambard), which gives each job that walltime once per arm,
                capped at 48 hours.
                An epocpp point gets 12 hours on the small deck, and on the large deck
                12 hours at 8 and 16 nodes, 16 at 32, 20 at 48 and 36 at 64 (over 24
                hours: QoS 'long' on ARCHER2), for the default 10 repeats.
  --repeats <n> Runs of each epocpp arm per combination (default 10); the reports take
                the Max() of bandwidth and the Min() of EPOCpp's Runtime over them.
  --nodes <list> Only these node counts of the scale, comma-separated (e.g. 32 or
                24,32,40), run in the scale's order; each must be one of the scale's
                ('lsmio backends', 'ior <scale>' and 'epocpp backends'). E.g.
                'run epocpp backends small adios2 --nodes 32' runs the baseline and
                the ADIOS2 arms at 32 nodes alone. Each point keeps its own walltime
                and is archived like a full run's: without --resume its <nodes>
                archive is replaced.
  --versioned   Execute versioned comparison run against reference baseline.
  --fast        Halve calculated walltime and cap at 23 hours to stay within qos=standard (<= 24h) on ARCHER2.
  --foreground  Stay attached to the terminal. By default a run started from a terminal
                detaches once its run roots exist: it goes on in the background with its
                output in <run root>/control/console.log, which is followed on screen until
                it ends. Ctrl-C then only stops the following; 'lsmiotool cancel <run root>'
                stops the run (and cancels its job).

Global Options (preserved for legacy compatibility):
  --ssd, -s     Accepted before or after command.
"""

PARSE_HELP_TEXT = """Usage:
  lsmiotool parse <target> [--output-dir <dir>] [--format <csv|json>]
  lsmiotool parse lsmio backends <scale> [--output-dir <dir>] [--format <csv|json>]
  lsmiotool parse ior <scale> [--output-dir <dir>]

Arguments:
  <target>      Target run root path, manifest file path, or benchmark name (ior, lsmio, lmp).
  <scale>       Supported scales for backends mode: local, bake, small, large.
                'parse ior <scale>' regenerates ior-report.csv in every outputs-* of
                <benchmark_root>/lsmio-archive/ior/<scale> (or --output-dir), where
                'run ior <scale>' archives its IOR setups.

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
      Compares performance across node counts for a benchmark folder (or several:
      nodes <folder> <folder> ... [read|write] ...).
      Arguments:
          <folder>: Archive folder with one outputs-<backend> directory per backend (e.g. <archive>/backends/<scale>).
                    Further folders are charted with it, e.g. the IOR setups 'run ior' archived:
                    compare nodes <archive>/backends/small <archive>/ior/small --all
                    (plots are named by the first folder's scale and every folder's
                    parent, e.g. compare-small-backends+ior-write-4-1M.png; an arm in
                    several folders is labelled '<arm> (<parent>/<folder>)'). A folder of
                    IOR setups alone gives compare-<scale>-ior-*.png, apart from its
                    scale's backends charts.
          <read|write>: Operation to compare ('read' or 'write'); optional with --all.
                    An epocpp archive (<benchmark_root>/lsmio-archive/epocpp/<scale>)
                    charts its bandwidth arms for read/write (Max() of MiB/s), and its
                    wall-time arms for 'runtime' (Min() of EPOCpp's Runtime) or 'cost'
                    (that minus the no-output baseline's, epocpp-cost.csv); its plots
                    are
                    named compare-<scale>-epocpp-*.png.
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
        --setup <name>: Explicit environment / benchmark profile (e.g. BASE, NATIVE, LSMIO).
            Note: '--setup=value' is strictly rejected; use '--setup <name>'.

    Global Options:
        --ssd / -s: Accepted before or after commands for backwards compatibility.
    """

    VALID_BENCHMARKS = frozenset({"ior", "lsmio", "lmp", "epocpp"})
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
            f_benchmark == "epocpp"
            and f_post_run_tokens[1].strip().lower() != "backends"
        ):
            raise RunCliParseError(
                "epocpp runs as "
                "'run epocpp backends <local|bake|small|large> [<backends>]'"
            )
        if (
            f_benchmark in ("lsmio", "epocpp")
            and f_post_run_tokens[1].strip().lower() == "backends"
        ):
            f_mode = "backends"
            if len(f_post_run_tokens) < 3:
                raise RunCliParseError(
                    "Missing required positional argument: <scale> for "
                    f"'run {f_benchmark} backends'"
                )
            f_scale_tok = f_post_run_tokens[2]
            if f_scale_tok.startswith("-"):
                raise RunCliParseError(
                    f"Unexpected option {f_scale_tok!r} placed before scale in "
                    f"'run {f_benchmark} backends'."
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
                if f_benchmark == "epocpp":
                    from lsmiotool.lib.arms import ArmError, epocppArms

                    try:
                        epocppArms(f_backends)
                    except ArmError as f_err:
                        raise RunCliParseError(str(f_err)) from f_err
            elif f_benchmark == "epocpp":
                from lsmiotool.lib.arms import DEFAULT_EPOCPP_BACKENDS

                f_backends = DEFAULT_EPOCPP_BACKENDS
            else:
                from lsmiotool.lib.arms import DEFAULT_LSMIO_BACKENDS

                f_backends = DEFAULT_LSMIO_BACKENDS
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
        elif f_benchmark == "ior" and f_mode == "standard":
            # IOR scaling runs: one arm per IOR setup in each job, archived like backends
            from lsmiotool.lib.arms import IOR_ARMS

            f_mode = "backends"
            if f_trailing_tokens and not f_trailing_tokens[0].startswith("-"):
                f_setups_raw = f_trailing_tokens[0].strip()
                f_trailing_tokens = f_trailing_tokens[1:]
                f_parsed_setups = [
                    f_s.strip().lower()
                    for f_s in f_setups_raw.split(",")
                    if f_s.strip()
                ]
                if not f_parsed_setups:
                    raise RunCliParseError("IOR setup specification cannot be empty.")
                f_seen_arms: Dict[str, str] = {}
                for f_s in f_parsed_setups:
                    if f_s not in IOR_ARMS:
                        raise RunCliParseError(
                            f"Invalid IOR setup: {f_s!r}. Must be one of: {sorted(IOR_ARMS)}"
                        )
                    if IOR_ARMS[f_s][1] in f_seen_arms:
                        raise RunCliParseError(
                            f"IOR setup listed twice: {f_seen_arms[IOR_ARMS[f_s][1]]!r} "
                            f"and {f_s!r}"
                        )
                    f_seen_arms[IOR_ARMS[f_s][1]] = f_s
                f_backends = tuple(f_parsed_setups)

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
        f_repeats: Optional[int] = None
        f_nodes: Optional[List[int]] = None

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
            elif f_tok == "--repeats":
                if f_repeats is not None:
                    raise RunCliParseError("Duplicate '--repeats' option specified.")
                if f_idx + 1 >= len(f_trailing_tokens):
                    raise RunCliParseError("Missing value after '--repeats' option.")
                f_val = f_trailing_tokens[f_idx + 1].strip()
                if not f_val.isascii() or not f_val.isdigit() or int(f_val) < 1:
                    raise RunCliParseError(
                        f"--repeats must be a positive integer, got: {f_val!r}"
                    )
                f_repeats = int(f_val)
                f_idx += 2
            elif f_tok == "--nodes":
                if f_nodes is not None:
                    raise RunCliParseError("Duplicate '--nodes' option specified.")
                if f_idx + 1 >= len(f_trailing_tokens):
                    raise RunCliParseError("Missing value after '--nodes' option.")
                f_val = f_trailing_tokens[f_idx + 1].strip()
                f_items = [f_n.strip() for f_n in f_val.split(",")]
                if (
                    not all(
                        f_n.isascii()
                        and f_n.isdigit()
                        and len(f_n) <= 9
                        and int(f_n) >= 1
                        for f_n in f_items
                    )
                    or len(set(f_items)) != len(f_items)
                    or len({int(f_n) for f_n in f_items}) != len(f_items)
                ):
                    raise RunCliParseError(
                        "--nodes must be a comma-separated list of distinct positive "
                        f"integers, got: {f_val!r}"
                    )
                f_nodes = [int(f_n) for f_n in f_items]
                f_idx += 2
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
                    "--repeats=",
                    "--nodes=",
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
                    "only 'variants', 'lsmio backends' and ior scaling runs are archived "
                    "or resumed "
                    "(set BM_WALLHOUR to change the walltime)."
                )

        # --repeats is the runs of each epocpp arm per combination; an epocpp run's
        # arms come from its backend list, not --setup
        if f_repeats is not None and f_benchmark != "epocpp":
            raise RunCliParseError("--repeats is supported only for 'epocpp backends'.")
        # --nodes picks points of a backends run's scale: lsmio backends, the ior
        # scaling runs (parsed as backends) and epocpp backends
        if f_nodes is not None and (f_mode != "backends" or f_scale == "variants"):
            raise RunCliParseError(
                "--nodes is supported only for 'lsmio backends', 'ior <scale>' and "
                "'epocpp backends'."
            )
        if f_benchmark == "epocpp" and f_setup_name is not None:
            raise RunCliParseError(
                "--setup is not supported for 'epocpp backends': "
                "list the backends instead."
            )

        # An ior scaling run's --setup names its one arm (the IOR setup list's form)
        if f_benchmark == "ior" and f_mode == "backends" and f_setup_name is not None:
            from lsmiotool.lib.arms import IOR_ARMS, ArmError, iorArmToken

            if f_backends is not None:
                raise RunCliParseError(
                    "Cannot specify both an IOR setup list and '--setup'."
                )
            try:
                f_backends = (iorArmToken(f_setup_name),)
            except ArmError as f_err:
                raise RunCliParseError(str(f_err)) from f_err
            # The IOR setup name (HDF5-C), also for a token (--setup hdf5-collective)
            f_setup_name = IOR_ARMS[f_backends[0]][0]

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
        if f_benchmark == "lsmio" and f_setup_name is not None:
            from lsmiotool.lib.benchmarks import LsmioAdapter

            if f_setup_name in LsmioAdapter.ARM_ONLY_SETUPS:
                raise RunCliParseError(
                    f"Setup {f_setup_name!r} is a backends arm: list its backend (e.g. "
                    "'adios2-sync') in 'run lsmio backends <scale> <backends>'."
                )
            if f_setup_name not in LsmioAdapter.RUN_SETUPS:
                raise RunCliParseError(
                    f"Invalid setup: {f_setup_name!r}. Must be one of: "
                    f"{list(LsmioAdapter.RUN_SETUPS)}"
                )
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
            f_repeats=f_repeats,
            f_nodes=f_nodes,
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
        lsmiotool parse ior <local|bake|small|large> [options]

    Arguments:
        <target>: Run root path (also an archived one), manifest file path, bmtool-layout
            outputs directory, or benchmark name ('ior', 'lsmio', 'lmp'). A benchmark
            name selects the latest run of that benchmark under the site profile's
            benchmark root.
        <scale>: With 'lsmio', restricts the latest-run search to that scale.
            'parse lsmio variants' and 'parse lsmio backends <scale>' instead
            regenerate the reports of every outputs-* directory in the archive
            destination, like bmtool. 'parse ior <scale>' regenerates the
            ior-report.csv of every IOR setup 'run ior <scale>' archived
            (<root>/lsmio-archive/ior/<scale>/outputs-*).

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

        if f_target.lower() == "epocpp" and not (
            f_remaining_tokens and f_remaining_tokens[0].lower() == "backends"
        ):
            raise ParseCliParseError(
                "epocpp is parsed as 'parse epocpp backends <scale>' (its archive) or "
                "'parse <run root>'"
            )
        if (
            f_target.lower() in ("lsmio", "epocpp")
            and f_remaining_tokens
            and f_remaining_tokens[0].lower() == "backends"
        ):
            f_mode = "backends"
            f_remaining_tokens.pop(0)
            if not f_remaining_tokens or f_remaining_tokens[0].startswith("-"):
                raise ParseCliParseError(
                    "Missing required positional argument: <scale> for "
                    f"'parse {f_target.lower()} backends'"
                )
            f_scale_tok = f_remaining_tokens.pop(0).strip().lower()
            valid_scales = frozenset({"local", "bake", "small", "large"})
            if f_scale_tok not in valid_scales:
                raise ParseCliParseError(
                    f"Invalid scale for backends parse: {f_scale_tok!r}. Must be one of: {sorted(valid_scales)}"
                )
            f_scale = f_scale_tok
        elif (
            f_target.lower() == "ior"
            and f_remaining_tokens
            and not f_remaining_tokens[0].startswith("-")
        ):
            # The archive of 'run ior <scale>' (lsmio-archive/ior/<scale>)
            f_mode = "backends"
            f_scale_tok = f_remaining_tokens.pop(0).strip().lower()
            valid_scales = frozenset({"local", "bake", "small", "large"})
            if f_scale_tok not in valid_scales:
                raise ParseCliParseError(
                    f"Invalid scale for ior parse: {f_scale_tok!r}. Must be one of: {sorted(valid_scales)}"
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

        if f_target.lower() == "ior" and f_mode == "backends" and f_format != "csv":
            raise ParseCliParseError(
                "'parse ior <scale>' writes ior-report.csv only (bmtool ior-parse.sh); "
                "--format json is not supported"
            )
        if f_target.lower() == "epocpp" and f_format != "csv":
            raise ParseCliParseError(
                "'parse epocpp backends <scale>' writes epocpp-report.csv and "
                "epocpp-cost.csv only; --format json is not supported"
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
        <benchmark>: Required. 'lsmio', 'ior' or 'epocpp' (epocpp: --source <the run
            root of one of its arms>, whose whole run is archived).
        <scale>: Required. One of: local, bake, small, large, variants
            ('baseline' is the deprecated spelling of 'variants'); not variants for ior.
        <variant>: Optional. Supported exclusively for 'lsmio variants'.

    Options:
        --dest <path>: Archive destination directory (default: <benchmark_root>/lsmio-archive/{variants|baseline};
            ior/<scale> for ior, epocpp/<scale> for epocpp).
            Note: '--dest=value' syntax is strictly rejected; use '--dest <path>'.
        --setup <name>: LSMIO setup naming the arm (default: $BM_SETUP, else NATIVE;
            for an lsmiotool run, the run's own setup); for ior, the IOR setup of the
            run to archive.
        --source <path>: What to archive: an lsmiotool run root or a bmtool outputs
            directory (default: resolved from the benchmark root, see ArchiveMain).
    """

    VALID_BENCHMARKS = frozenset({"lsmio", "ior", "epocpp"})
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
        if f_benchmark in ("ior", "epocpp") and f_scale == "variants":
            raise ArchiveCliParseError(
                f"Invalid scale for {f_benchmark}: 'variants'. Only {f_benchmark} "
                "scaling runs (local, bake, small, large) are archived."
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
                    f_setup = cls.validateSetup(f_val, f_benchmark)
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
    def validateSetup(cls, f_setup: str, f_benchmark: str = "lsmio") -> str:
        """Canonical (upper-case) setup name of f_benchmark, as 'run --setup' accepts it.

        Raises:
            ArchiveCliParseError: For an unknown setup.
        """
        from lsmiotool.lib.arms import IOR_ARMS
        from lsmiotool.lib.benchmarks import EpocppAdapter, IorAdapter, LsmioAdapter

        f_allowed = {
            "ior": IorAdapter.ALLOWED_SETUPS,
            "epocpp": EpocppAdapter.ALLOWED_SETUPS,
        }.get(f_benchmark, LsmioAdapter.RUN_SETUPS)
        f_norm = f_setup.strip().upper()
        if f_benchmark == "ior" and f_setup.strip().lower() in IOR_ARMS:
            # An IOR setup token, as 'run ior <scale> <ior setups>' takes it
            f_norm = IOR_ARMS[f_setup.strip().lower()][0]
        if f_benchmark == "lsmio" and f_norm in LsmioAdapter.ARM_ONLY_SETUPS:
            raise ArchiveCliParseError(
                f"Setup {f_setup!r} is a backends arm: it is archived with its backends run."
            )
        if f_norm not in f_allowed:
            raise ArchiveCliParseError(
                f"Invalid setup: {f_setup!r}. Must be one of: {list(f_allowed)}"
            )
        return f_norm


def parseArchiveArguments(f_argv: Sequence[str]) -> ArchiveRequest:
    """Convenience function wrapping ArchiveCliParser.parse."""
    return ArchiveCliParser.parse(f_argv=f_argv)


class CompareNodesRequest:
    """Immutable parsed and validated request value object for 'compare nodes'."""

    __slots__ = (
        "m_folder",
        "m_extra_folders",
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
        f_extra_folders: Sequence[str] = (),
    ) -> None:
        if not isinstance(f_folder, str) or not f_folder.strip():
            raise ValueError(f"folder must be a non-empty string, got: {f_folder!r}")
        if isinstance(f_extra_folders, str) or any(
            not isinstance(f_f, str) or not f_f.strip() for f_f in f_extra_folders
        ):
            raise ValueError(
                f"extra folders must be non-empty strings, got: {f_extra_folders!r}"
            )
        if not isinstance(f_all, bool):
            raise ValueError(f"all must be a boolean, got: {f_all!r}")
        # With --all the operation is optional: 'both' charts read and write
        if f_op is None and f_all:
            f_op = "both"
        if not isinstance(f_op, str) or not f_op.strip():
            raise ValueError(f"op must be a non-empty string, got: {f_op!r}")
        f_norm_op = f_op.strip().lower()
        # runtime and cost chart an epocpp archive's wall-time arms
        f_valid_ops = ("read", "write", "runtime", "cost") + (
            ("both",) if f_all else ()
        )
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
        super().__setattr__(
            "m_extra_folders", tuple(f_f.strip() for f_f in f_extra_folders)
        )
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
    def folders(self) -> Tuple[str, ...]:
        """Every folder charted: the first (it names the plots), then the others."""
        return (self.m_folder,) + self.m_extra_folders

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
            **(
                {"extra_folders": list(self.m_extra_folders)}
                if self.m_extra_folders
                else {}
            ),
            "op": self.m_op,
            "stripes": self.m_stripes,
            "blocksize": self.m_blocksize,
            "output_dir": self.m_output_dir,
            "all": self.m_all,
        }

    def __repr__(self) -> str:
        return (
            f"CompareNodesRequest(folder={self.m_folder!r}, "
            f"extra_folders={self.m_extra_folders!r}, "
            f"op={self.m_op!r}, stripes={self.m_stripes!r}, "
            f"blocksize={self.m_blocksize!r}, "
            f"output_dir={self.m_output_dir!r}, all={self.m_all!r})"
        )

    def __eq__(self, f_other: Any) -> bool:
        if isinstance(f_other, CompareNodesRequest):
            return (
                self.m_folder == f_other.m_folder
                and self.m_extra_folders == f_other.m_extra_folders
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
                self.m_extra_folders,
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
        lsmiotool compare nodes <folder> [<folder> ...] <read|write> [<stripes>] [<blocksize>] [--output-dir <dir>]
        lsmiotool compare nodes <folder> [<folder> ...] [read|write] --all [--output-dir <dir>]
        lsmiotool compare variants <archive_folder> [read|write|both] [<stripes>] [<blocksize>] [--all] [--output-dir <dir>]
    """

    VALID_SUBMODES: Tuple[str, ...] = ("nodes", "variants")
    # runtime and cost: an epocpp archive's wall-time arms (epocpp-report.csv,
    # epocpp-cost.csv)
    VALID_OPERATIONS_NODES: Tuple[str, ...] = ("read", "write", "runtime", "cost")
    VALID_OPERATIONS_VARIANTS: Tuple[str, ...] = ("read", "write", "both")
    VALID_OPERATIONS: Tuple[str, ...] = (
        "read",
        "write",
        "both",
        "runtime",
        "cost",
    )
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
        # Further folders, charted with the first: tokens before <read|write> that name a
        # path (with a '/') or an existing directory; any other word is a bad operation
        f_extra_folders: List[str] = []

        while f_rem_idx < len(f_remaining_tokens):
            f_tok = f_remaining_tokens[f_rem_idx]
            if f_tok.startswith("-"):
                break

            if (
                f_pos_idx == 0
                and f_tok.strip()
                and f_tok.strip().lower() not in cls.VALID_OPERATIONS
                and (
                    os.sep in f_tok
                    or (
                        # A stripe count or block size is never a folder ('./4' is)
                        not f_tok.strip().isdigit()
                        and f_tok.strip().upper() not in cls.VALID_BLOCKSIZES
                        and os.path.isdir(os.path.expanduser(f_tok.strip()))
                    )
                )
            ):
                f_extra_folders.append(f_tok.strip())
                f_rem_idx += 1
            elif f_pos_idx == 0:
                f_op_norm = f_tok.strip().lower()
                if f_op_norm not in cls.VALID_OPERATIONS_NODES:
                    raise CompareCliParseError(
                        f"Invalid operation: {f_tok!r}. Must be 'read', 'write', "
                        "'runtime' or 'cost' (a further folder is a path with '/' or "
                        "an existing directory)"
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
            f_extra_folders=f_extra_folders,
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
