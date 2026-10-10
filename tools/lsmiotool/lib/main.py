#
# Copyright 2023 Serdar Bulut
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

import argparse
import importlib
import json
import os
import signal
import subprocess
import sys
from typing import (
    Any,
    Callable,
    Dict,
    FrozenSet,
    List,
    Mapping,
    NamedTuple,
    Optional,
    Sequence,
    Tuple,
    Union,
    TYPE_CHECKING,
)

if TYPE_CHECKING:
    from lsmiotool.lib.cli import (
        CompareArchiveRequest,
        CompareNodesRequest,
        CompareVariantsRequest,
    )

from lsmiotool.lib import debuggable, log

# Catch CTRL-C
signal.signal(signal.SIGINT, signal.SIG_DFL)


class BaseMain(debuggable.DebuggableObject):
    """Base class for all main execution modes."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize base main execution mode."""
        super().__init__()


class TestMain(BaseMain):
    """Test execution mode for running unit tests."""

    def __init__(self, *f_args: str) -> None:
        super().__init__()
        self.m_test_args = f_args

    def run(self) -> int:
        """Execute test suite and report results."""
        from lsmiotool import test

        return test.run_and_report(*self.m_test_args)


def siteBenchmarkRoots(f_storages: Sequence[str] = ("hdd", "ssd")) -> List[str]:
    """Benchmark roots ($BM_PATH) of the detected site profile for f_storages, in order
    and deduplicated. Empty when the site or its profile cannot be resolved."""
    try:
        import getpass

        from lsmiotool.lib.site import EnvironmentResolver

        f_dev = os.environ.get("LSMIO_ENV", "").strip().upper() == "DEV"
        f_site = EnvironmentResolver.detect(f_test_mode=f_dev)
        f_profile = EnvironmentResolver.resolveProfile(
            f_site,
            f_user=os.environ.get("USER") or getpass.getuser(),
            f_home=os.path.expanduser("~"),
        )
    except Exception as f_err:
        log.Console.debug(f"Cannot resolve site benchmark root: {f_err}")
        return []
    f_roots: List[str] = []
    for f_storage in f_storages:
        try:
            f_root = f_profile.getBenchmarkRoot(f_storage)
        except Exception:
            continue
        if f_root and f_root not in f_roots:
            f_roots.append(f_root)
    return f_roots


class ParseLegacyMain(BaseMain):
    """parseLegacy: bmtool's 'parse' command on a bmtool-layout outputs directory.

    Command:
        parseLegacy <ior|lsmio|lmp> <local|bake|small|large|variants> [<path>] [--ssd]
        parseLegacy lsmio backends <local|bake|small|large> [<path>] [--ssd]

    Like tools/bmtool/parse/*-parse.sh, the outputs directory defaults to
    $BM_PATH/<benchmark>/outputs (jobs/<benchmark>-vars.in.sh), where $BM_PATH is the
    site profile's benchmark root (its ssd root with --ssd), and the reports are
    written into it. 'lsmio backends <scale>' regenerates every outputs-* arm of the
    archive destination <BM_PATH>/lsmio-archive/backends/<scale> (bmtool's archive
    mode). <path> overrides the outputs directory (archive destination for backends).
    """

    VALID_MODES: FrozenSet[str] = frozenset(
        {"local", "bake", "small", "large", "variants", "baseline"}
    )
    BACKENDS_SCALES: FrozenSet[str] = frozenset({"local", "bake", "small", "large"})

    m_command: str
    m_mode: str
    m_is_ssd: bool
    m_backends: bool
    m_path: Optional[str]
    m_benchmark_root: Optional[str]

    def __init__(self, *f_args: Any, **f_kwargs: Any) -> None:
        """Initialize ParseLegacyMain.

        Args:
            *f_args: <ior|lsmio|lmp> <scale> [<path>], or lsmio backends <scale> [<path>]
            **f_kwargs: ssd=True/False; f_benchmark_root overrides the site profile's
                benchmark root.
        """
        super().__init__()
        f_usage = (
            "ParseLegacy: Needs <ior|lsmio|lmp> <local|bake|small|large|variants> "
            "[<path>] or lsmio backends <local|bake|small|large> [<path>]"
        )
        if len(f_args) < 2:
            log.Console.error(f_usage)
            sys.exit(1)
        f_tokens = [str(f_a) for f_a in f_args]
        self.m_command = f_tokens[0]
        self.m_is_ssd = bool(f_kwargs.get("ssd", False))
        self.m_benchmark_root = f_kwargs.get("f_benchmark_root")
        self.m_backends = False

        allowed_commands = ["ior", "lsmio", "lmp"]
        if self.m_command not in allowed_commands:
            log.Console.error(
                "Command to execute has to be in: " + str(allowed_commands)
            )
            sys.exit(1)

        f_rest = f_tokens[1:]
        if self.m_command == "lsmio" and f_rest[0] == "backends":
            self.m_backends = True
            f_rest = f_rest[1:]
            if not f_rest or f_rest[0] not in self.BACKENDS_SCALES:
                log.Console.error(
                    "Backends scale has to be in: " + str(sorted(self.BACKENDS_SCALES))
                )
                sys.exit(1)
        allowed_modes = ["local", "bake", "small", "large", "variants", "baseline"]
        if f_rest[0] not in self.VALID_MODES:
            log.Console.error("Command mode has to be in: " + str(allowed_modes))
            sys.exit(1)
        self.m_mode = f_rest[0]
        if len(f_rest) > 2:
            log.Console.error(f_usage)
            sys.exit(1)
        self.m_path = (
            os.path.abspath(os.path.expanduser(f_rest[1])) if len(f_rest) > 1 else None
        )

    def _benchmarkRoot(self) -> Optional[str]:
        """$BM_PATH: the explicit root, else the site profile's (ssd with --ssd)."""
        if self.m_benchmark_root:
            return os.path.abspath(os.path.expanduser(self.m_benchmark_root))
        f_roots = siteBenchmarkRoots(("ssd",) if self.m_is_ssd else ("hdd",))
        return f_roots[0] if f_roots else None

    def _getTargetDir(self, f_bench_type: str, f_mode: str, f_is_ssd: bool) -> str:
        """Outputs directory bmtool parses: <path>, else $BM_PATH/<benchmark>/outputs.

        Raises:
            ValueError: When no path was given and the benchmark root is unknown.
        """
        if self.m_path:
            return self.m_path
        f_root = self._benchmarkRoot()
        if not f_root:
            raise ValueError(
                "cannot resolve the benchmark root from the site profile; "
                "pass the outputs directory as <path>"
            )
        return os.path.join(f_root, f_bench_type, "outputs")

    def _checkTargetDir(self, f_bench_type: str, f_mode: str, f_is_ssd: bool) -> str:
        f_dir = self._getTargetDir(f_bench_type, f_mode, f_is_ssd)
        if not os.path.isdir(f_dir):
            raise ValueError(f"outputs directory not found: {f_dir}")
        return f_dir

    def parseIor(self, f_mode: str, f_is_ssd: bool) -> None:
        """Parse IOR outputs into ior-report.csv (bmtool parse/ior-parse.sh)."""
        from lsmiotool.lib import output

        target_dir = self._checkTargetDir("ior", f_mode, f_is_ssd)
        log.Console.debug(f"Parsing IOR logs from: {target_dir}")
        agg = output.IorAggOutput(target_dir)
        agg.generateReports(target_dir)

    def parseLsmio(self, f_mode: str, f_is_ssd: bool) -> None:
        """Parse LSMIO outputs into agg files and lsm-report.csv (lsmio-parse.sh)."""
        from lsmiotool.lib import output

        target_dir = self._checkTargetDir("lsmio", f_mode, f_is_ssd)
        log.Console.debug(f"Parsing LSMIO logs from: {target_dir}")
        agg = output.LsmioAggOutput(target_dir, f_scale=f_mode)
        agg.generateReports(target_dir)

    def parseLmp(self, f_mode: str, f_is_ssd: bool) -> None:
        """Parse LMP outputs into lmp-report.csv (bmtool parse/lmp-parse.sh)."""
        from lsmiotool.lib import output

        target_dir = self._checkTargetDir("lmp", f_mode, f_is_ssd)
        log.Console.debug(f"Parsing LMP logs from: {target_dir}")
        agg = output.LmpAggOutput(target_dir)
        agg.generateReports(target_dir)

    def parseLsmioBackends(self, f_scale: str) -> int:
        """lsmio-parse.sh archive mode, through 'parse lsmio backends <scale>'."""
        from lsmiotool.lib.cli import ParseRequest

        f_root = self._benchmarkRoot()
        if not self.m_path and not f_root:
            sys.stderr.write(
                "Error: cannot resolve the benchmark root from the site profile; "
                "pass the archive destination as <path>\n"
            )
            return 3
        f_request = ParseRequest(
            f_target="lsmio",
            f_mode="backends",
            f_scale=f_scale,
            f_output_dir=self.m_path,
        )
        return ParseMain(f_request=f_request, f_benchmark_root=f_root).run()

    def run(self) -> int:
        """Execute parsing dispatch.

        Returns:
            0 when the report was written, 1 when the outputs directory is missing or
            holds no results; backends mode returns 'parse lsmio backends' codes.
        """
        if self.m_backends:
            return self.parseLsmioBackends(self.m_mode)

        f_report_names = {
            "ior": "ior-report.csv",
            "lsmio": "lsm-report.csv",
            "lmp": "lmp-report.csv",
        }
        try:
            if self.m_command == "ior":
                self.parseIor(self.m_mode, self.m_is_ssd)
            elif self.m_command == "lsmio":
                self.parseLsmio(self.m_mode, self.m_is_ssd)
            elif self.m_command == "lmp":
                self.parseLmp(self.m_mode, self.m_is_ssd)
            f_report = os.path.join(
                self._getTargetDir(self.m_command, self.m_mode, self.m_is_ssd),
                f_report_names[self.m_command],
            )
        except ValueError as f_err:
            sys.stderr.write(f"Error: {f_err}\n")
            return 1

        from lsmiotool.lib.data import isUsableReport

        if not isUsableReport(f_report):
            sys.stderr.write(f"Warning: no {self.m_command} results; {f_report} not written\n")
            return 1
        sys.stdout.write(f"{f_report}\n")
        return 0


class ParseMain(BaseMain):
    """Parse command execution mode for modern benchmark run artifacts."""

    m_request: Optional[Any]
    m_init_error: Optional[Exception]
    m_benchmark_root: Optional[str]

    def __init__(
        self,
        *f_args: Any,
        f_request: Optional[Any] = None,
        **f_kwargs: Any,
    ) -> None:
        """Initialize ParseMain.

        Command: parse <target> [--output-dir <dir>] [--format <csv|json>]

        Args:
            *f_args: Variable positional arguments (e.g. target, or list of CLI tokens, or ParseRequest).
            f_request: Optional canonical ParseRequest.
            **f_kwargs: Keyword arguments (e.g. target, output_dir, format).
        """
        super().__init__()
        from lsmiotool.lib.cli import (
            ParseCliParseError,
            ParseRequest,
            parseParseArguments,
        )

        self.m_request = None
        self.m_init_error = None
        self.m_benchmark_root = f_kwargs.pop("f_benchmark_root", None)

        if f_request is not None:
            if not isinstance(f_request, ParseRequest):
                raise ValueError(
                    f"f_request must be ParseRequest, got: {type(f_request).__name__}"
                )
            self.m_request = f_request
        elif len(f_args) == 1 and isinstance(f_args[0], ParseRequest):
            self.m_request = f_args[0]
        elif len(f_args) == 1 and isinstance(f_args[0], (list, tuple)):
            try:
                self.m_request = parseParseArguments(list(f_args[0]))
            except ParseCliParseError as f_err:
                self.m_init_error = f_err
        elif len(f_args) >= 1:
            f_argv: List[str] = [str(a) for a in f_args]
            try:
                self.m_request = parseParseArguments(f_argv)
            except ParseCliParseError as f_err:
                self.m_init_error = f_err
        elif "target" in f_kwargs or "f_target" in f_kwargs:
            try:
                f_target = f_kwargs.get("f_target", f_kwargs.get("target"))
                f_output_dir = f_kwargs.get(
                    "f_output_dir",
                    f_kwargs.get("output_dir", f_kwargs.get("outputDir")),
                )
                f_format = f_kwargs.get("f_format", f_kwargs.get("format", "csv"))
                self.m_request = ParseRequest(
                    f_target=f_target,
                    f_output_dir=f_output_dir,
                    f_format=f_format,
                )
            except (ValueError, TypeError) as f_err:
                self.m_init_error = ParseCliParseError(str(f_err))
            except ParseCliParseError as f_err:
                self.m_init_error = f_err
        else:
            try:
                self.m_request = parseParseArguments([])
            except ParseCliParseError as f_err:
                self.m_init_error = f_err

    @property
    def request(self) -> Optional[Any]:
        return self.m_request

    @property
    def target(self) -> str:
        return self.m_request.target if self.m_request is not None else ""

    @property
    def output_dir(self) -> str:
        if self.m_request is not None and self.m_request.output_dir is not None:
            return self.m_request.output_dir
        return os.getcwd()

    @property
    def outputDir(self) -> str:
        return self.output_dir

    @property
    def format(self) -> str:
        return self.m_request.format if self.m_request is not None else "csv"

    def _classifyResolutionError(self, f_err: Exception) -> int:
        """Classify RunRootResolutionError into exit code 3 or 4.

        Exit codes:
            3: Missing or unreadable run artifacts (manifest.json missing or inaccessible,
               unreadable run root directory, symlink violations).
            4: Corrupted or incomplete run state (state reconciliation fails, run did not succeed,
               missing whole_run_succeeded marker, missing controller/rank results).
        """
        from lsmiotool.lib.evidence import EvidenceError
        from lsmiotool.lib.state import StateError

        f_msg = str(f_err).lower()
        f_state_indicators = (
            "did not succeed",
            "state reconciliation failed",
            "whole_run_succeeded",
            "missing controller result",
            "missing rank result",
            "does not match manifest run_id",
        )
        for f_ind in f_state_indicators:
            if f_ind in f_msg:
                return 4

        if isinstance(getattr(f_err, "__cause__", None), (StateError, EvidenceError)):
            return 4

        return 3

    def _benchmarkRoots(self) -> List[str]:
        """Benchmark roots of the site profile (hdd first, then ssd), deduplicated.

        Returns an empty list when the site or its profile cannot be resolved.
        """
        if self.m_benchmark_root:
            return [os.path.abspath(os.path.expanduser(self.m_benchmark_root))]
        return siteBenchmarkRoots(("hdd", "ssd"))

    def _resolveRun(self) -> Any:
        """Resolve the request target to a run (in any state; see run()), inferring
        benchmark names from the profile."""
        from lsmiotool.lib.runparse import RunRootResolutionError, RunRootResolver

        f_target = self.m_request.target
        f_scale = self.m_request.scale
        if f_target.strip().lower() not in ("ior", "lsmio", "lmp", "lammps"):
            return RunRootResolver.resolveTarget(
                f_target, f_scale=f_scale, f_allow_partial=True
            )

        # Runs live in <benchmark_root>/runs; fall back to the legacy search paths
        f_errors: List[str] = []
        for f_root in self._benchmarkRoots():
            try:
                return RunRootResolver.resolveTarget(
                    f_target,
                    f_benchmark_root=f_root,
                    f_scale=f_scale,
                    f_allow_partial=True,
                )
            except RunRootResolutionError as f_err:
                if "Cannot infer latest run" not in str(f_err):
                    raise
                f_errors.append(str(f_err))
        try:
            return RunRootResolver.resolveTarget(
                f_target, f_scale=f_scale, f_allow_partial=True
            )
        except RunRootResolutionError as f_err:
            if f_errors and "Cannot infer latest run" in str(f_err):
                raise RunRootResolutionError("; ".join(f_errors + [str(f_err)]))
            raise

    def _regenerateOutputDirs(
        self, f_dirs: Sequence[Tuple[str, str]], f_scale: Optional[str]
    ) -> int:
        """Regenerate bmtool-identical reports for (source dir, label) pairs.

        Returns:
            0 when at least one lsm-report.csv was produced, 5 otherwise.
        """
        from lsmiotool.lib.output import regenerateLsmioReports

        f_written = 0
        for f_dir, f_label in f_dirs:
            sys.stdout.write(
                f"=== Generating aggregates and report for {f_label} ===\n"
            )
            try:
                f_report = regenerateLsmioReports(f_dir, f_scale=f_scale)
            except Exception as f_err:
                sys.stderr.write(f"Error: failed to parse {f_dir}: {f_err}\n")
                continue
            if f_report is None:
                sys.stderr.write(f"Warning: no LSMIO results found in {f_dir}\n")
                continue
            f_written += 1
            sys.stdout.write(f"{f_report}\n")
        sys.stdout.flush()
        return 0 if f_written else 5

    def _parseArchive(self) -> int:
        """bmtool lsmio-parse.sh archive mode: regenerate per-arm reports in the archive.

        'parse lsmio backends <scale>' covers <dest>=<root>/lsmio-archive/backends/<scale>;
        every outputs-* directory there gets its agg-*-report.csv files and lsm-report.csv
        rebuilt.
        """
        from lsmiotool.lib.archive import resolveArchiveDest

        f_mode = self.m_request.mode
        f_scale = self.m_request.scale
        if self.m_request.output_dir:
            f_dests = [os.path.abspath(os.path.expanduser(self.m_request.output_dir))]
        else:
            f_dests = [
                resolveArchiveDest(f_root, f_mode=f_mode, f_scale=f_scale)
                for f_root in self._benchmarkRoots()
            ]
            if not f_dests:
                sys.stderr.write(
                    "Error: cannot resolve the benchmark root from the site profile; "
                    "pass --output-dir <archive destination>\n"
                )
                return 3

        f_dest = next((f_d for f_d in f_dests if os.path.isdir(f_d)), None)
        if f_dest is None:
            sys.stderr.write(
                f"Error: archive destination not found: {', '.join(f_dests)}\n"
            )
            return 3

        f_arms = sorted(
            f_entry
            for f_entry in os.listdir(f_dest)
            if f_entry.startswith("outputs-")
            and os.path.isdir(os.path.join(f_dest, f_entry))
        )
        if not f_arms:
            sys.stderr.write(f"Error: no outputs-* directories in {f_dest}\n")
            return 3

        f_node_scale = f_scale
        return self._regenerateOutputDirs(
            [
                (os.path.join(f_dest, f_arm), f"{f_arm[len('outputs-'):]} ({f_scale})")
                for f_arm in f_arms
            ],
            f_node_scale,
        )

    def _parseBmtoolLayout(self, f_dir: str) -> int:
        """Regenerate reports for a bmtool-layout outputs dir or an archive of them."""
        from lsmiotool.lib.output import isBmtoolOutputDir

        f_scale = self.m_request.scale
        if isBmtoolOutputDir(f_dir):
            if self.m_request.output_dir:
                # Aggregate into the requested directory, leaving the source untouched
                from lsmiotool.lib.output import LsmioAggOutput
                from lsmiotool.lib.data import LSM_REPORT_FILE, isUsableReport

                f_out = os.path.abspath(self.m_request.output_dir)
                LsmioAggOutput(f_dir, f_scale=f_scale).generateReports(f_out_dir=f_out)
                f_report = os.path.join(f_out, LSM_REPORT_FILE)
                if not isUsableReport(f_report):
                    sys.stderr.write(f"Warning: no LSMIO results found in {f_dir}\n")
                    return 5
                sys.stdout.write(f"{f_report}\n")
                return 0
            return self._regenerateOutputDirs(
                [(f_dir, os.path.basename(f_dir.rstrip(os.sep)))], f_scale
            )

        f_children = [
            os.path.join(f_dir, f_entry)
            for f_entry in sorted(os.listdir(f_dir))
            if f_entry.startswith("outputs-")
            and os.path.isdir(os.path.join(f_dir, f_entry))
        ]
        return self._regenerateOutputDirs(
            [(f_child, os.path.basename(f_child)) for f_child in f_children], f_scale
        )

    def _isOutputsTarget(self, f_target: str) -> bool:
        """True for a directory without manifest.json that holds bmtool-layout outputs
        directly or in outputs-* children (an archive destination)."""
        from lsmiotool.lib.output import isBmtoolOutputDir

        if not os.path.isdir(f_target) or os.path.exists(
            os.path.join(f_target, "manifest.json")
        ):
            return False
        if isBmtoolOutputDir(f_target):
            return True
        try:
            f_entries = os.listdir(f_target)
        except OSError:
            return False
        return any(
            f_entry.startswith("outputs-")
            and os.path.isdir(os.path.join(f_target, f_entry))
            for f_entry in f_entries
        )

    def run(self) -> int:
        """Execute benchmark run parsing, metric extraction, and report generation.

        Every point/combination with complete output is reported, also for a run
        that did not succeed (like bmtool, which reports whatever output exists);
        the others are skipped with a warning on stderr.

        Returns:
            0: Success (reports generated, summary printed to stdout).
            1: General runtime / configuration error.
            2: ParseCliParseError (invalid CLI syntax/arguments).
            3: RunRootResolutionError (missing manifest.json or unreadable run directory).
            4: Failed state reconciliation, or the run did not succeed (reports cover the
               points/combinations that completed, if any).
            5: Malformed or missing log files in a succeeded run (reports cover the
               other points/combinations, if any).
        """
        from lsmiotool.lib.cli import ParseCliParseError
        from lsmiotool.lib.evidence import EvidenceError
        from lsmiotool.lib.runparse import (
            ConsoleSummaryFormatter,
            ExtractionError,
            RunRootResolutionError,
            countExtracted,
            extractRun,
            generateReports,
        )
        from lsmiotool.lib.state import OverallRunState, StateError

        if self.m_init_error is not None:
            sys.stderr.write(f"Error: {self.m_init_error}\n")
            if isinstance(
                self.m_init_error, (ParseCliParseError, ValueError, TypeError)
            ):
                return 2
            return 1

        if self.m_request is None:
            sys.stderr.write("Error: No valid parse request configured.\n")
            return 1

        try:
            # bmtool lsmio-parse.sh archive mode is for backends only; every other
            # scale (variants included) parses the latest run, like bmtool's live outputs
            f_target_name = self.m_request.target.strip().lower()
            if f_target_name == "lsmio" and self.m_request.mode == "backends":
                return self._parseArchive()

            # bmtool-layout outputs directory (or an archive destination of them). A bare
            # benchmark name is always the benchmark, never a same-named dir in the cwd
            # (use ./lsmio for that)
            f_target_dir = os.path.abspath(os.path.expanduser(self.m_request.target))
            if f_target_name not in (
                "ior",
                "lsmio",
                "lmp",
                "lammps",
            ) and self._isOutputsTarget(f_target_dir):
                return self._parseBmtoolLayout(f_target_dir)

            # 1. Target resolution (a partially failed run resolves too)
            f_resolved_run = self._resolveRun()

            # 2. Metric extraction: every point/combination with complete output;
            # the rest are skipped with a warning, as bmtool's parsers do
            f_warnings: List[str] = []
            f_extracted_data = extractRun(
                f_resolved_run, f_skip_incomplete=True, f_warnings=f_warnings
            )
            f_run_state = f_resolved_run.runState
            f_run_ok = (
                f_run_state.is_success
                and f_run_state.state == OverallRunState.SUCCEEDED
                and f_run_state.has_success_marker
            )
            f_state_msg = ""
            if not f_run_ok:
                f_state_msg = (
                    f"Run '{f_resolved_run.runId}' did not succeed (state: "
                    f"{f_run_state.state.value}, diagnostics: {f_run_state.diagnostics})"
                )
                if f_run_state.is_success and not f_run_state.has_success_marker:
                    f_state_msg += ": missing whole_run_succeeded control event marker"
            for f_warning in f_warnings:
                sys.stderr.write(f"Warning: {f_warning}\n")

            if countExtracted(f_extracted_data) == 0:
                if not f_run_ok:
                    sys.stderr.write(
                        f"Error: {f_state_msg}; no point/combination has complete output\n"
                    )
                    return 4
                sys.stderr.write(
                    f"Error: no results could be extracted from run "
                    f"'{f_resolved_run.runId}'\n"
                )
                return 5
            if not f_run_ok:
                sys.stderr.write(
                    f"Warning: {f_state_msg}; reporting the points/combinations "
                    f"with complete output only\n"
                )

            # 3. Report generation
            f_effective_out_dir = self.output_dir
            generateReports(
                f_resolved_run=f_resolved_run,
                f_extracted_data=f_extracted_data,
                f_out_dir=f_effective_out_dir,
                f_format=self.format,
            )

            # 4. Formatting and writing console summary table to sys.stdout
            f_summary_table = ConsoleSummaryFormatter.formatSummaryTable(
                f_resolved_run=f_resolved_run,
                f_extracted_data=f_extracted_data,
            )
            sys.stdout.write(f"{f_summary_table}\n")
            sys.stdout.flush()

            # Partial reports keep the documented codes: 4 = the run did not succeed,
            # 5 = some logs could not be extracted
            if not f_run_ok:
                return 4
            return 5 if f_warnings else 0
        except ParseCliParseError as f_err:
            sys.stderr.write(f"Error: {f_err}\n")
            return 2
        except RunRootResolutionError as f_err:
            sys.stderr.write(f"Error: {f_err}\n")
            return self._classifyResolutionError(f_err)
        except (StateError, EvidenceError) as f_err:
            sys.stderr.write(f"Error: {f_err}\n")
            return 4
        except ExtractionError as f_err:
            sys.stderr.write(f"Error: {f_err}\n")
            return 5
        except Exception as f_err:
            sys.stderr.write(f"Error: {f_err}\n")
            return 1


class CompareNodesMain(BaseMain):
    """Submode orchestrator for 'compare nodes' (multi-node scaling curve comparison)."""

    m_request: "CompareNodesRequest"
    m_folder: str
    m_op: str
    m_stripes: int
    m_bs: str
    m_output_dir: Optional[str]
    m_all: bool

    def __init__(
        self,
        *f_args: Any,
        f_request: Optional[Any] = None,
        f_folder: Optional[str] = None,
        f_op: Optional[str] = None,
        f_stripes: int = 4,
        f_blocksize: str = "1M",
        f_output_dir: Optional[str] = None,
        f_all: bool = False,
        **f_kwargs: Any,
    ) -> None:
        """Initialize CompareNodesMain.

        Command: compare nodes <folder> <read|write> [<stripes>] [<blocksize>] [--output-dir <dir>]

        Args:
            *f_args: Variable length argument list (folder, op, [stripes], [blocksize], [output_dir]).
            f_request: Optional pre-constructed CompareNodesRequest.
            f_folder: Optional target benchmark folder.
            f_op: Optional operation ('read' or 'write').
            f_stripes: Optional stripe count (default: 4).
            f_blocksize: Optional block size ('64K', '1M', '8M', default: '1M').
            f_output_dir: Optional output directory for generated plots.
            f_all: Chart every (stripes, blocksize) permutation, for f_op or both operations.
            **f_kwargs: Arbitrary keyword arguments.
        """
        super().__init__()
        from lsmiotool.lib.cli import CompareNodesRequest

        if f_request is not None:
            req = f_request
        elif len(f_args) == 1 and isinstance(f_args[0], CompareNodesRequest):
            req = f_args[0]
        else:
            folder = f_folder
            op = f_op
            stripes = f_stripes
            bs = f_blocksize
            out_dir = (
                f_output_dir
                or f_kwargs.get("f_output_dir")
                or f_kwargs.get("output_dir")
            )

            if f_args:
                if len(f_args) < 2:
                    log.Console.error(
                        "Compare nodes: Needs at least two arguments: <folder> <read|write> [<stripes>] [<blocksize>]"
                    )
                    sys.exit(1)
                folder = str(f_args[0])
                op = str(f_args[1])
                if (
                    len(f_args) >= 3
                    and f_args[2] is not None
                    and str(f_args[2]).strip() != ""
                ):
                    try:
                        stripes = int(f_args[2])
                    except ValueError:
                        log.Console.error(f"Invalid stripes value: {f_args[2]}")
                        sys.exit(1)
                if (
                    len(f_args) >= 4
                    and f_args[3] is not None
                    and str(f_args[3]).strip() != ""
                ):
                    bs = str(f_args[3])
                if (
                    len(f_args) >= 5
                    and f_args[4] is not None
                    and str(f_args[4]).strip() != ""
                ):
                    out_dir = str(f_args[4])

            if folder is None or (op is None and not f_all):
                log.Console.error(
                    "Compare nodes: Missing required folder or operation."
                )
                sys.exit(1)

            try:
                req = CompareNodesRequest(
                    f_folder=folder,
                    f_op=op,
                    f_stripes=stripes,
                    f_blocksize=bs,
                    f_output_dir=out_dir,
                    f_all=f_all,
                )
            except ValueError as err:
                log.Console.error(f"Compare nodes validation error: {err}")
                sys.exit(1)

        self.m_request = req
        self.m_folder = req.folder
        self.m_op = req.op
        self.m_stripes = req.stripes
        self.m_bs = req.blocksize
        self.m_output_dir = req.output_dir
        self.m_all = req.all

    @property
    def request(self) -> "CompareNodesRequest":
        return self.m_request

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
        return self.m_bs

    @property
    def bs(self) -> str:
        return self.m_bs

    @property
    def output_dir(self) -> Optional[str]:
        return self.m_output_dir

    @property
    def outputDir(self) -> Optional[str]:
        return self.m_output_dir

    def resolveDirectory(self, f_path: str) -> str:
        """Resolve path handling user home (~), relative, and absolute paths."""
        expanded = os.path.expanduser(f_path)
        return os.path.abspath(expanded)

    def run(self) -> int:
        """Scan benchmark subdirectories, extract data series, and generate comparison
        plots: one, or with --all one per (operation, stripes, blocksize)."""
        from lsmiotool.lib.cli import CompareCliParser

        target_dir = self.resolveDirectory(self.m_folder)
        if not os.path.isdir(target_dir):
            log.Console.error(f"Directory not found: {target_dir}")
            sys.exit(1)

        if not self.m_all:
            self._plotOne(target_dir, self.m_op, self.m_stripes, self.m_bs)
            return 0
        f_ops = ["write", "read"] if self.m_op == "both" else [self.m_op]
        for f_op in f_ops:
            for f_stripes, f_bs in CompareCliParser.WORKLOAD_PERMUTATIONS:
                self._plotOne(target_dir, f_op, f_stripes, f_bs)
        return 0

    def _plotOne(self, target_dir: str, f_op: str, f_stripes: int, f_bs: str) -> None:
        """Generate the comparison plot of one (operation, stripes, blocksize)."""
        from lsmiotool.lib import data, output, plot

        canonical_backend_labels: Dict[str, str] = {
            "outputs-adios": "adios2",
            "outputs-adios2": "adios2",
            "adios": "adios2",
            "adios2": "adios2",
            "outputs-native": "native",
            "native": "native",
            "outputs-plugin": "plugin",
            "plugin": "plugin",
            "outputs-rocksdb": "rocksdb",
            "rocksdb": "rocksdb",
            "outputs-leveldb": "leveldb",
            "leveldb": "leveldb",
        }
        canonical_order: Dict[str, int] = {
            "adios2": 0,
            "native": 1,
            "plugin": 2,
            "rocksdb": 3,
            "leveldb": 4,
        }

        entries = sorted(os.listdir(target_dir))
        plot_data_list: List[plot.PlotData] = []
        is_read = f_op == "read"

        for entry in entries:
            child_path = os.path.join(target_dir, entry)
            if os.path.isdir(child_path):
                report_file = os.path.join(child_path, "lsm-report.csv")
                if output.ensureLsmioReports(child_path):
                    summary_data = data.LsmioSummaryData(report_file)
                    x_series, y_series = summary_data.timeSeries(
                        is_read, f_stripes, f_bs
                    )
                    if x_series and y_series:
                        legend_label = canonical_backend_labels.get(entry)
                        if legend_label is None:
                            entry_lower = entry.lower()
                            # "plugin" first: plugin runs are ADIOS2 too (e.g. "adios2-plugin")
                            if "plugin" in entry_lower:
                                legend_label = "plugin"
                            elif "adios" in entry_lower:
                                legend_label = "adios2"
                            elif entry_lower in ("outputs-native", "native"):
                                legend_label = "native"
                            elif "rocksdb" in entry_lower:
                                legend_label = "rocksdb"
                            elif "leveldb" in entry_lower:
                                legend_label = "leveldb"
                            else:
                                legend_label = entry
                        plot_data_list.append(
                            plot.PlotData(legend_label, x_series, y_series)
                        )

        if not plot_data_list:
            log.Console.warning(
                f"No benchmark data found in subdirectories of {target_dir} for {f_op}, stripes={f_stripes}, bs={f_bs}"
            )
            return

        # Sort plot series by canonical precedence: [adios2, native, plugin, rocksdb, leveldb] (INV-BACKEND-5)
        plot_data_list.sort(
            key=lambda p: (canonical_order.get(p.legend, 999), p.legend)
        )

        base_name = os.path.basename(target_dir.rstrip(os.sep))

        # Plots go straight into --output-dir (default: cwd), as 'compare variants' does;
        # the scale names them: backends/<scale> -> <scale>, a variants archive -> variants
        norm_target = os.path.normpath(target_dir)
        path_parts = norm_target.split(os.sep)

        out_dir = (
            self.resolveDirectory(self.m_output_dir)
            if self.m_output_dir
            else os.getcwd()
        )
        b_indices = [i for i, part in enumerate(path_parts) if part == "backends"]
        v_indices = [i for i, part in enumerate(path_parts) if part == "variants"]

        if b_indices:
            b_idx = b_indices[-1]
            scale_name = (
                path_parts[b_idx + 1] if b_idx + 1 < len(path_parts) else base_name
            )
        elif v_indices:
            scale_name = "variants"
        else:
            scale_name = base_name

        os.makedirs(out_dir, exist_ok=True)
        title = f"Comparison: {scale_name} ({f_op.upper()} - {f_stripes} stripes - {f_bs})"
        meta_data = plot.PlotMetaData(title, "# of Nodes", "Max BW in MB")

        output_filename = os.path.join(
            out_dir,
            f"compare-{scale_name}-{f_op}-{f_stripes}-{f_bs}.png",
        )
        bar_plot = plot.MultiBarPlot(meta_data, *plot_data_list)
        bar_plot.plot(output_filename)
        log.Console.info(f"Comparison plot saved to {output_filename}")


class PairedVariantRun(NamedTuple):
    """Encapsulates a verified paired variant run directory and its control baseline directory."""

    backend: str
    variant: str
    collision: Optional[int]
    display_label: str
    run_dir: str
    base_dir: str
    run_metadata: Dict[str, Any]
    base_metadata: Dict[str, Any]

    def toDict(self) -> Dict[str, Any]:
        return {
            "backend": self.backend,
            "variant": self.variant,
            "collision": self.collision,
            "display_label": self.display_label,
            "run_dir": self.run_dir,
            "base_dir": self.base_dir,
            "run_metadata": dict(self.run_metadata),
            "base_metadata": dict(self.base_metadata),
        }

    @classmethod
    def fromDict(cls, f_data: Dict[str, Any]) -> "PairedVariantRun":
        return cls(
            backend=str(f_data["backend"]),
            variant=str(f_data["variant"]),
            collision=int(f_data["collision"])
            if f_data.get("collision") is not None
            else None,
            display_label=str(f_data["display_label"]),
            run_dir=str(f_data["run_dir"]),
            base_dir=str(f_data["base_dir"]),
            run_metadata=dict(f_data["run_metadata"]),
            base_metadata=dict(f_data["base_metadata"]),
        )


class CompareVariantsMain(BaseMain):
    """Submode orchestrator for 'compare variants' (8-node baseline variant comparison).

    Scans benchmark run archives, executes fault-tolerant parse-on-demand aggregation,
    extracts 8-node baseline metrics across variants, sorts variants alphabetically,
    and renders publication-ready comparison bar charts.
    """

    __slots__ = (
        "m_request",
        "m_archive_folder",
        "m_op",
        "m_stripes",
        "m_blocksize",
        "m_all",
        "m_output_dir",
    )

    m_request: "CompareVariantsRequest"
    m_archive_folder: str
    m_op: str
    m_stripes: int
    m_blocksize: str
    m_all: bool
    m_output_dir: Optional[str]

    def __init__(
        self,
        *f_args: Any,
        f_request: Optional[Any] = None,
        f_archive_folder: Optional[str] = None,
        f_op: str = "both",
        f_stripes: int = 4,
        f_blocksize: str = "1M",
        f_all: bool = False,
        f_output_dir: Optional[str] = None,
        **f_kwargs: Any,
    ) -> None:
        """Initialize CompareVariantsMain.

        Command: compare variants <archive_folder> [read|write|both] [<stripes>] [<blocksize>] [--all] [--output-dir <dir>]

        Args:
            *f_args: Variable length argument list (e.g. folder, op, stripes, bs, or CLI argv).
            f_request: Optional pre-constructed CompareVariantsRequest.
            f_archive_folder: Optional path to archive folder.
            f_op: Optional operation ('read', 'write', 'both').
            f_stripes: Optional stripe count (4, 16).
            f_blocksize: Optional block size ('64K', '1M', '8M').
            f_all: Optional flag to run all 6 permutations.
            f_output_dir: Optional output directory for generated plots.
            **f_kwargs: Arbitrary keyword arguments.
        """
        super().__init__()
        from lsmiotool.lib.cli import (
            CompareVariantsRequest,
            parseCompareArchiveArguments,
            parseCompareArguments,
        )

        if f_request is not None:
            req = f_request
        elif len(f_args) == 1 and isinstance(f_args[0], CompareVariantsRequest):
            req = f_args[0]
        elif f_args and any(
            isinstance(a, str)
            and (a.startswith("-") or a in ("compare-archive", "compare", "variants"))
            for a in f_args
        ):
            tokens = [str(a) for a in f_args]
            if tokens and tokens[0] == "variants":
                req = parseCompareArguments(tokens)
            else:
                req = parseCompareArchiveArguments(tokens)
        else:
            folder = f_archive_folder
            op = f_op
            stripes = f_stripes
            blocksize = f_blocksize
            all_val = f_all
            out_dir = (
                f_output_dir
                or f_kwargs.get("f_output_dir")
                or f_kwargs.get("output_dir")
            )

            if f_args:
                folder = str(f_args[0])
                if len(f_args) >= 2 and f_args[1] is not None:
                    op = str(f_args[1])
                if len(f_args) >= 3 and f_args[2] is not None:
                    stripes = int(f_args[2])
                if len(f_args) >= 4 and f_args[3] is not None:
                    blocksize = str(f_args[3])
                if len(f_args) >= 5 and f_args[4] is not None:
                    all_val = bool(f_args[4])
                if len(f_args) >= 6 and f_args[5] is not None:
                    out_dir = str(f_args[5])

            if folder is None:
                req = parseCompareArchiveArguments([])
            else:
                req = CompareVariantsRequest(
                    f_archive_folder=folder,
                    f_op=op,
                    f_stripes=stripes,
                    f_blocksize=blocksize,
                    f_all=all_val,
                    f_output_dir=out_dir,
                )

        self.m_request = req
        self.m_archive_folder = req.archive_folder
        self.m_op = req.op
        self.m_stripes = req.stripes
        self.m_blocksize = req.blocksize
        self.m_all = req.all
        self.m_output_dir = req.output_dir

    @property
    def request(self) -> "CompareVariantsRequest":
        return self.m_request

    @property
    def archive_folder(self) -> str:
        return self.m_archive_folder

    @property
    def folder(self) -> str:
        return self.m_archive_folder

    @property
    def m_folder(self) -> str:
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
    def bs(self) -> str:
        return self.m_blocksize

    @property
    def m_bs(self) -> str:
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

    def resolveDirectory(self, f_path: str) -> str:
        """Resolves path string expanding user home (~) and normalizing to absolute path."""
        expanded = os.path.expanduser(f_path)
        return os.path.abspath(expanded)

    def _ensureReportExists(self, f_child_path: str) -> bool:
        """Check if lsm-report.csv exists in child directory, triggering parse-on-demand if missing.

        A zero-byte lsm-report.csv counts as missing, and a regeneration that yields
        no rows writes nothing into the archive.

        Args:
            f_child_path: Path to variant directory (bmtool layout or lsmiotool run root).

        Returns:
            True if a non-empty lsm-report.csv exists or was successfully generated.
        """
        from lsmiotool.lib.output import ensureLsmioReports

        return ensureLsmioReports(
            f_child_path, f_scale="variants", f_require_logs=False
        )

    def _extractMetrics(
        self, f_child_path: str, f_op: str, f_stripes: int, f_blocksize: str
    ) -> Optional[float]:
        """Extract 8-node baseline maxMB bandwidth metric from lsm-report.csv.

        Args:
            f_child_path: Path to variant directory or csv file.
            f_op: Operation ('read' or 'write').
            f_stripes: Stripe count (4 or 16).
            f_blocksize: Block size ('64K', '1M', '8M').

        Returns:
            Bandwidth in MB/s as float, or None on error or missing metric.
        """
        csv_path = (
            os.path.join(f_child_path, "lsm-report.csv")
            if os.path.isdir(f_child_path)
            else f_child_path
        )
        if not os.path.isfile(csv_path):
            return None

        try:
            from lsmiotool.lib.data import LsmioSummaryData

            summary_data = LsmioSummaryData(csv_path)
            op_key = f_op.lower()
            stripes_key = int(f_stripes)
            bs_key = f_blocksize.upper()
            bw = summary_data.m_csv_data[op_key][stripes_key][bs_key][8]["maxMB"]
            return float(bw)
        except (KeyError, IndexError, ValueError, TypeError):
            return None

    _extractBaselineMetric = _extractMetrics

    def _generateChart(
        self,
        f_arg1: Any,
        f_arg2: Any,
        f_arg3: Any,
        f_arg4: Any,
        f_arg5: Optional[Any] = None,
        f_arg6: Optional[Any] = None,
    ) -> str:
        """Render single-series grouped bar chart using MultiBarPlot.

        Supports both:
          _generateChart(op, stripes, blocksize, variant_data)
          _generateChart(base_name, op, stripes, bs, variant_data, output_dir)

        Returns:
            Absolute path to generated PNG chart.
        """
        from lsmiotool.lib import plot

        if f_arg5 is not None and f_arg6 is not None:
            archive_basename = str(f_arg1)
            op = str(f_arg2)
            stripes = int(f_arg3)
            blocksize = str(f_arg4)
            variant_data = list(f_arg5)
            out_dir = str(f_arg6)
        else:
            op = str(f_arg1)
            stripes = int(f_arg2)
            blocksize = str(f_arg3)
            variant_data = list(f_arg4)
            archive_basename = os.path.basename(
                self.resolveDirectory(self.m_archive_folder).rstrip(os.sep)
            )
            out_dir = (
                self.resolveDirectory(self.m_output_dir)
                if self.m_output_dir
                else os.getcwd()
            )

        sorted_data = sorted(variant_data, key=lambda x: x[0])
        sorted_variants = [x[0] for x in sorted_data]
        sorted_bws = [x[1] for x in sorted_data]

        series = [plot.PlotData(op.capitalize(), sorted_variants, sorted_bws)]
        filename = f"compare-variants-{archive_basename}-{op.lower()}-{stripes}-{blocksize.upper()}.png"
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, filename)

        title = f"LSMIO Variant Comparison ({op.capitalize()}, Stripes={stripes}, BS={blocksize.upper()})"
        meta_data = plot.PlotMetaData(title, "Variant", "Max Bandwidth (MB/s)")

        bar_plot = plot.MultiBarPlot(meta_data, *series)
        bar_plot.plot(out_path)
        log.Console.info(f"Comparison plot saved to {out_path}")
        return out_path

    def _pairDirectories(
        self,
        valid_runs: List[Tuple[Any, str]],
    ) -> List[PairedVariantRun]:
        variant_runs: List[Tuple[Any, str]] = []
        twin_bases: Dict[Tuple[str, str, Optional[int]], Tuple[Any, str]] = {}
        standalone_bases: Dict[Tuple[str, Optional[int]], Tuple[Any, str]] = {}

        for res, path in valid_runs:
            coll_int = int(res.collision) if res.collision is not None else None
            if res.role == "run":
                variant_runs.append((res, path))
            elif res.role == "base":
                twin_bases[(res.backend, res.variant, coll_int)] = (res, path)
            elif res.role is None and res.variant == "default":
                standalone_bases[(res.backend, coll_int)] = (res, path)

        paired_results: List[PairedVariantRun] = []
        for meta_run, path_run in variant_runs:
            coll_int = (
                int(meta_run.collision) if meta_run.collision is not None else None
            )
            base_match = twin_bases.get((meta_run.backend, meta_run.variant, coll_int))
            if base_match is None:
                base_match = standalone_bases.get(
                    (meta_run.backend, coll_int)
                ) or standalone_bases.get((meta_run.backend, None))
            if base_match is not None:
                meta_base, path_base = base_match
                paired_results.append(
                    PairedVariantRun(
                        backend=meta_run.backend,
                        variant=meta_run.variant,
                        collision=coll_int,
                        display_label=meta_run.display_label,
                        run_dir=path_run,
                        base_dir=path_base,
                        run_metadata=meta_run._asdict(),
                        base_metadata=meta_base._asdict(),
                    )
                )
            else:
                log.Console.warning(
                    f"Orphaned variant run omitted (no matching baseline): {meta_run.raw_directory}"
                )

        return sorted(paired_results, key=lambda x: x.display_label)

    def _computeDelta(
        self,
        f_run_bw: float,
        f_base_bw: float,
        f_metric: str = "percent",
    ) -> float:
        if f_metric == "percent":
            return (
                ((f_run_bw - f_base_bw) / f_base_bw) * 100.0 if f_base_bw > 0.0 else 0.0
            )
        return f_run_bw - f_base_bw

    def _generateDeltaChart(
        self,
        op: str,
        stripes: int,
        blocksize: str,
        delta_data: List[Tuple[str, float]],
        metric: str = "percent",
        out_dir: Optional[str] = None,
    ) -> str:
        from lsmiotool.lib import plot

        sorted_data = sorted(delta_data, key=lambda x: x[0])
        variants = [x[0] for x in sorted_data]
        deltas = [x[1] for x in sorted_data]

        series = plot.PlotData(op.capitalize(), variants, deltas)
        archive_basename = (
            os.path.basename(
                self.resolveDirectory(self.m_archive_folder).rstrip(os.sep)
            )
            if self.m_archive_folder
            else "archive"
        )
        out_dir_path = (
            self.resolveDirectory(out_dir)
            if out_dir
            else (
                self.resolveDirectory(self.m_output_dir)
                if self.m_output_dir
                else os.getcwd()
            )
        )
        filename = f"compare-variants-delta-{archive_basename}-{op.lower()}-{stripes}-{blocksize.upper()}.png"
        os.makedirs(out_dir_path, exist_ok=True)
        out_path = os.path.join(out_dir_path, filename)

        unit = "%" if metric == "percent" else "MB/s"
        title = f"LSMIO Variant Delta vs Paired Baseline ({op.capitalize()}, Stripes={stripes}, BS={blocksize.upper()})"
        meta_data = plot.PlotMetaData(title, "Variant", f"Delta Bandwidth ({unit})")

        chart = plot.DeltaBarPlot(
            meta_data, series, f_is_percentage=(metric == "percent")
        )
        chart.plot(out_path)
        log.Console.info(f"Comparison delta plot saved to {out_path}")
        return out_path

    def run(self) -> int:
        """Scan benchmark archive folder, extract variant metrics, and generate comparison plots.

        Returns:
            0 on success, 1 on no valid runs, 3 if archive folder does not exist.
        """
        target_dir = self.resolveDirectory(self.m_archive_folder)
        if not os.path.isdir(target_dir):
            sys.stderr.write(f"Archive folder not found: {self.m_archive_folder}\n")
            return 3

        from lsmiotool.lib.variants import VariantReverseResolver

        entries = sorted(os.listdir(target_dir))
        valid_runs: List[Tuple[Any, str]] = []
        for entry in entries:
            child_path = os.path.join(target_dir, entry)
            if not os.path.isdir(child_path):
                continue
            res = VariantReverseResolver.resolve(entry)
            if res is None:
                continue
            if self._ensureReportExists(child_path):
                valid_runs.append((res, child_path))

        if not valid_runs:
            log.Console.warning("No valid benchmark runs found in archive folder")
            return 1

        ops = ["read", "write"] if self.m_op.lower() == "both" else [self.m_op.lower()]
        from lsmiotool.lib.cli import CompareCliParser

        perms = (
            CompareCliParser.WORKLOAD_PERMUTATIONS
            if self.m_all
            else [(self.m_stripes, self.m_blocksize)]
        )

        # Determine if paired variant runs are present
        has_paired_runs = any(res.role == "run" for res, _ in valid_runs)

        if has_paired_runs:
            paired_runs = self._pairDirectories(valid_runs)
            if not paired_runs:
                log.Console.warning("No matched paired runs found for delta comparison")
                return 1

            for op in ops:
                for stripes, bs in perms:
                    delta_data: List[Tuple[str, float]] = []
                    for pair in paired_runs:
                        bw_run = self._extractMetrics(pair.run_dir, op, stripes, bs)
                        bw_base = self._extractMetrics(pair.base_dir, op, stripes, bs)
                        if bw_run is not None and bw_base is not None:
                            delta = self._computeDelta(bw_run, bw_base, "percent")
                            delta_data.append((pair.display_label, delta))
                    if delta_data:
                        self._generateDeltaChart(
                            op, stripes, bs, delta_data, metric="percent"
                        )
                    else:
                        log.Console.warning(
                            f"No paired benchmark data found for {op}, stripes={stripes}, bs={bs}"
                        )
        else:
            for op in ops:
                for stripes, bs in perms:
                    variant_data: List[Tuple[str, float]] = []
                    for res, child_path in valid_runs:
                        bw = self._extractMetrics(child_path, op, stripes, bs)
                        if bw is not None:
                            variant_data.append((res.display_label, bw))
                    if variant_data:
                        self._generateChart(op, stripes, bs, variant_data)
                    else:
                        log.Console.warning(
                            f"No benchmark data found in subdirectories for {op}, stripes={stripes}, bs={bs}"
                        )

        return 0


# Backward compatibility alias for existing test imports and external callers
CompareArchiveMain = CompareVariantsMain


class CompareMain(BaseMain):
    """Unified entry point and polymorphic dispatcher for 'compare' subcommand.

    Supports initialization via:
    1. Typed request object: CompareNodesRequest or CompareVariantsRequest
    2. CLI token sequences starting with 'nodes' or 'variants'
    3. Positional Python arguments (folder, op, stripes, bs) for test backward compatibility
       (safeguarding ProfileSchemaTest.py:606 and TestCompareMain.py)
    """

    m_request: Optional[Union["CompareNodesRequest", "CompareVariantsRequest"]]
    m_submode: str
    m_delegate: Union[CompareNodesMain, CompareVariantsMain]

    def __init__(
        self,
        *f_args: Any,
        f_request: Optional[
            Union["CompareNodesRequest", "CompareVariantsRequest"]
        ] = None,
        **f_kwargs: Any,
    ) -> None:
        super().__init__()
        from lsmiotool.lib.cli import (
            CompareNodesRequest,
            CompareVariantsRequest,
            parseCompareArguments,
        )

        if f_request is not None:
            req = f_request
            if getattr(req, "submode", "") == "variants" or isinstance(
                req, CompareVariantsRequest
            ):
                self.m_submode = "variants"
                self.m_delegate = CompareVariantsMain(f_request=req)
            else:
                self.m_submode = "nodes"
                self.m_delegate = CompareNodesMain(f_request=req)
            self.m_request = req
        elif len(f_args) == 1 and isinstance(
            f_args[0], (CompareNodesRequest, CompareVariantsRequest)
        ):
            req = f_args[0]
            if getattr(req, "submode", "") == "variants" or isinstance(
                req, CompareVariantsRequest
            ):
                self.m_submode = "variants"
                self.m_delegate = CompareVariantsMain(f_request=req)
            else:
                self.m_submode = "nodes"
                self.m_delegate = CompareNodesMain(f_request=req)
            self.m_request = req
        elif (
            len(f_args) == 1
            and isinstance(f_args[0], (list, tuple))
            and f_args[0]
            and str(f_args[0][0]).lower() in ("nodes", "variants", "compare")
        ):
            req = parseCompareArguments(f_args[0])
            if getattr(req, "submode", "") == "variants" or isinstance(
                req, CompareVariantsRequest
            ):
                self.m_submode = "variants"
                self.m_delegate = CompareVariantsMain(f_request=req)
            else:
                self.m_submode = "nodes"
                self.m_delegate = CompareNodesMain(f_request=req)
            self.m_request = req
        elif f_args and str(f_args[0]).lower() in ("nodes", "variants", "compare"):
            tokens = [str(a) for a in f_args]
            req = parseCompareArguments(tokens)
            if getattr(req, "submode", "") == "variants" or isinstance(
                req, CompareVariantsRequest
            ):
                self.m_submode = "variants"
                self.m_delegate = CompareVariantsMain(f_request=req)
            else:
                self.m_submode = "nodes"
                self.m_delegate = CompareNodesMain(f_request=req)
            self.m_request = req
        else:
            # Legacy Python caller fallback (ProfileSchemaTest.py:606, TestCompareMain.py)
            self.m_submode = "nodes"
            self.m_delegate = CompareNodesMain(*f_args, **f_kwargs)
            self.m_request = getattr(self.m_delegate, "m_request", None)

    @property
    def request(
        self,
    ) -> Optional[Union["CompareNodesRequest", "CompareVariantsRequest"]]:
        return self.m_request

    @property
    def submode(self) -> str:
        return self.m_submode

    @property
    def delegate(self) -> Union[CompareNodesMain, CompareVariantsMain]:
        return self.m_delegate

    @property
    def m_folder(self) -> str:
        return getattr(
            self.m_delegate,
            "m_folder",
            getattr(self.m_delegate, "m_archive_folder", ""),
        )

    @property
    def folder(self) -> str:
        return self.m_folder

    @property
    def archive_folder(self) -> str:
        return getattr(self.m_delegate, "m_archive_folder", "")

    @property
    def m_op(self) -> str:
        return self.m_delegate.m_op

    @property
    def op(self) -> str:
        return self.m_delegate.m_op

    @property
    def m_stripes(self) -> int:
        return self.m_delegate.m_stripes

    @property
    def stripes(self) -> int:
        return self.m_delegate.m_stripes

    @property
    def m_bs(self) -> str:
        return getattr(
            self.m_delegate,
            "m_bs",
            getattr(self.m_delegate, "m_blocksize", "1M"),
        )

    @property
    def blocksize(self) -> str:
        return self.m_bs

    @property
    def all(self) -> bool:
        return getattr(self.m_delegate, "m_all", False)

    @property
    def m_output_dir(self) -> Optional[str]:
        return self.m_delegate.m_output_dir

    @property
    def output_dir(self) -> Optional[str]:
        return self.m_output_dir

    @property
    def outputDir(self) -> Optional[str]:
        return self.m_output_dir

    def resolveDirectory(self, f_path: str) -> str:
        return self.m_delegate.resolveDirectory(f_path)

    def run(self) -> int:
        return self.m_delegate.run()


class RunMain(BaseMain):
    """Run command for executing benchmarks via RunOrchestrator."""

    m_request: Any
    m_orchestrator_factory: Optional[Callable[..., Any]]
    m_worker_validator: Optional[Any]
    m_site: Optional[Union[str, Any]]
    m_runtime_layout: Optional[Any]
    m_reporter: Optional[Any]

    def __init__(
        self,
        *f_args: Any,
        f_request: Optional[Any] = None,
        f_orchestrator_factory: Optional[Callable[..., Any]] = None,
        f_worker_validator: Optional[Any] = None,
        f_site: Optional[Union[str, Any]] = None,
        f_runtime_layout: Optional[Any] = None,
        f_reporter: Optional[Any] = None,
        **f_kwargs: Any,
    ) -> None:
        """Initialize RunMain.

        Command: run <ior|lsmio|lmp> <local|bake|small|large> [--ssd] [--setup <name>]

        Args:
            *f_args: Positional argument list (can be [target, scale] or [RunRequest]).
            f_request: Optional parsed canonical RunRequest.
            f_orchestrator_factory: Optional injected factory callable returning a RunOrchestrator.
            f_worker_validator: Optional injected worker validator for preflight checks.
            f_site: Optional explicit site or profile.
            f_runtime_layout: Optional runtime layout.
            f_reporter: Optional injected reporter or stream.
            **f_kwargs: Additional keyword arguments (e.g. ssd=True, setup="...").
        """
        super().__init__()
        from lsmiotool.lib.cli import parseRunArguments
        from lsmiotool.lib.run import RunRequest

        if f_request is not None:
            if not isinstance(f_request, RunRequest):
                raise ValueError(
                    f"f_request must be RunRequest, got: {type(f_request).__name__}"
                )
            self.m_request = f_request
        elif len(f_args) == 1 and isinstance(f_args[0], RunRequest):
            self.m_request = f_args[0]
        elif len(f_args) >= 2:
            f_argv: List[str] = [str(a) for a in f_args]
            if (
                "setup" in f_kwargs
                and f_kwargs["setup"] is not None
                and "--setup" not in f_argv
            ):
                f_argv.extend(["--setup", str(f_kwargs["setup"])])
            self.m_request = parseRunArguments(
                f_argv, f_global_ssd=bool(f_kwargs.get("ssd", False))
            )
        elif len(f_args) == 1 and isinstance(f_args[0], (list, tuple)):
            self.m_request = parseRunArguments(
                list(f_args[0]), f_global_ssd=bool(f_kwargs.get("ssd", False))
            )
        else:
            raise ValueError(
                "RunMain requires either a RunRequest or positional benchmark and scale arguments."
            )

        self.m_orchestrator_factory = f_orchestrator_factory
        self.m_worker_validator = f_worker_validator
        self.m_site = f_site
        self.m_runtime_layout = f_runtime_layout
        self.m_reporter = (
            f_reporter
            if f_reporter is not None
            else f_kwargs.get("f_reporter", f_kwargs.get("reporter"))
        )

    @property
    def request(self) -> Any:
        return self.m_request

    @property
    def orchestratorFactory(self) -> Optional[Callable[..., Any]]:
        return self.m_orchestrator_factory

    @property
    def orchestrator_factory(self) -> Optional[Callable[..., Any]]:
        return self.m_orchestrator_factory

    @property
    def workerValidator(self) -> Optional[Any]:
        return self.m_worker_validator

    @property
    def worker_validator(self) -> Optional[Any]:
        return self.m_worker_validator

    @property
    def site(self) -> Optional[Union[str, Any]]:
        return self.m_site

    @property
    def runtimeLayout(self) -> Optional[Any]:
        return self.m_runtime_layout

    @property
    def runtime_layout(self) -> Optional[Any]:
        return self.m_runtime_layout

    @property
    def reporter(self) -> Optional[Any]:
        return self.m_reporter

    @property
    def f_reporter(self) -> Optional[Any]:
        return self.m_reporter

    def run(self) -> int:
        """Execute benchmark run orchestration and return integer exit status."""
        from lsmiotool.lib.cli import WorkerExecutableValidator
        from lsmiotool.lib.run import (
            OrchestrationError,
            PreflightError,
            RunOrchestrator,
            RunReporter,
        )

        f_validator = (
            self.m_worker_validator
            if self.m_worker_validator is not None
            else WorkerExecutableValidator
        )

        f_reporter = self.m_reporter
        if f_reporter is None:
            f_reporter = RunReporter(sys.stdout)
        elif not isinstance(f_reporter, RunReporter) and callable(f_reporter):
            f_reporter = RunReporter(f_callback=f_reporter)

        if self.m_orchestrator_factory is not None:
            try:
                f_orch = self.m_orchestrator_factory(
                    f_worker_validator=f_validator,
                    f_reporter=f_reporter,
                )
            except TypeError:
                try:
                    f_orch = self.m_orchestrator_factory(f_worker_validator=f_validator)
                except TypeError:
                    f_orch = self.m_orchestrator_factory()
        else:
            f_orch = RunOrchestrator(
                f_worker_validator=f_validator,
                f_reporter=f_reporter,
            )

        if (
            hasattr(f_orch, "m_reporter")
            and getattr(f_orch, "m_reporter", None) is None
        ):
            try:
                object.__setattr__(f_orch, "m_reporter", f_reporter)
            except Exception:
                pass

        try:
            f_view = f_orch.execute(
                f_request=self.m_request,
                f_site=self.m_site,
                f_runtime_layout=self.m_runtime_layout,
            )
            return f_orch.exitCode
        except (PreflightError, OrchestrationError) as f_err:
            sys.stderr.write(f"Error: {f_err}\n")
            return 1
        except Exception as f_err:
            sys.stderr.write(f"Unexpected error: {f_err}\n")
            return 1


class ArchiveMain(BaseMain):
    """'lsmiotool archive': bmtool's archive command (include/archive.in.sh).

    Benchmark root: f_benchmark_root, else the site profile's benchmark root (hdd,
    as bmtool's archive has no --ssd) - never the working directory.
    Destination: --dest (resolved like bmtool's include/archive-dest.in.sh), else
    <root>/lsmio-archive/{variants|baseline}. An inherited BM_ARCHIVE_DEST is ignored:
    bmtool clears it before resolving the archive command's destination.
    Arm: outputs-<arm>, arm = resolveArmId(setup, variant) with setup from --setup,
    else $BM_SETUP, else NATIVE-M (an lsmiotool run root: the run's own setup).
    Source (--source, else resolved from the root):
      - <root>/lsmio/outputs ($LSM_DIR_OBASE) holding bmtool outputs is moved like
        bmtool does (reports generated first, an empty directory recreated);
      - otherwise the latest lsmiotool run of 'lsmio <scale>' [variant] under
        <root>/runs is exported in bmtool's layout (lib/export.py) for its succeeded
        points; the run root stays where it is (no empty runs/run-* left behind) and
        a run already exported to the destination is not archived again.
    """

    m_request: Any
    m_runtime_layout: Optional[Any]
    m_source_dir: Optional[str]
    m_dest_dir: Optional[str]
    m_benchmark_root: Optional[str]
    m_environ: Mapping[str, str]

    def __init__(
        self,
        *f_args: Any,
        f_request: Optional[Any] = None,
        f_runtime_layout: Optional[Any] = None,
        f_source_dir: Optional[str] = None,
        f_dest_dir: Optional[str] = None,
        **f_kwargs: Any,
    ) -> None:
        """Initialize ArchiveMain.

        Command: archive <benchmark> <scale> [<variant>] [--dest <path>]

        Args:
            *f_args: Variable positional arguments (e.g. tokens, or [ArchiveRequest]).
            f_request: Optional canonical ArchiveRequest.
            f_runtime_layout: Optional runtime layout.
            f_source_dir: Optional explicit source directory override.
            f_dest_dir: Optional explicit destination directory override.
            **f_kwargs: Additional keyword arguments (e.g. dest="...", source="...").
        """
        super().__init__()
        from lsmiotool.lib.archive import ArchiveRequest
        from lsmiotool.lib.cli import parseArchiveArguments

        if f_request is not None:
            if not isinstance(f_request, ArchiveRequest):
                raise ValueError(
                    f"f_request must be ArchiveRequest, got: {type(f_request).__name__}"
                )
            self.m_request = f_request
        elif len(f_args) == 1 and isinstance(f_args[0], ArchiveRequest):
            self.m_request = f_args[0]
        elif len(f_args) == 1 and isinstance(f_args[0], (list, tuple)):
            self.m_request = parseArchiveArguments(list(f_args[0]))
        elif len(f_args) >= 2:
            f_argv: List[str] = [str(a) for a in f_args]
            if (
                "dest" in f_kwargs
                and f_kwargs["dest"] is not None
                and "--dest" not in f_argv
            ):
                f_argv.extend(["--dest", str(f_kwargs["dest"])])
            self.m_request = parseArchiveArguments(f_argv)
        else:
            raise ValueError(
                "ArchiveMain requires either an ArchiveRequest or positional benchmark and scale arguments."
            )

        self.m_runtime_layout = f_runtime_layout
        self.m_benchmark_root = f_kwargs.get("f_benchmark_root")
        self.m_environ = f_kwargs.get("f_environ") or os.environ
        self.m_source_dir = (
            f_source_dir
            if f_source_dir is not None
            else f_kwargs.get(
                "f_source_dir",
                f_kwargs.get("source_dir", f_kwargs.get("source")),
            )
        )
        self.m_dest_dir = (
            f_dest_dir
            if f_dest_dir is not None
            else f_kwargs.get(
                "f_dest_dir",
                f_kwargs.get("dest_dir", f_kwargs.get("dest")),
            )
        )

    @property
    def request(self) -> Any:
        return self.m_request

    @property
    def runtimeLayout(self) -> Optional[Any]:
        return self.m_runtime_layout

    @property
    def runtime_layout(self) -> Optional[Any]:
        return self.m_runtime_layout

    @property
    def sourceDir(self) -> Optional[str]:
        return self.m_source_dir

    @property
    def source_dir(self) -> Optional[str]:
        return self.m_source_dir

    @property
    def destDir(self) -> Optional[str]:
        return self.m_dest_dir

    @property
    def dest_dir(self) -> Optional[str]:
        return self.m_dest_dir

    def _benchmarkRoot(self) -> Optional[str]:
        """$BM_PATH: explicit root, runtime layout's, else the site profile's (hdd)."""
        f_root = self.m_benchmark_root
        if not f_root and self.m_runtime_layout is not None:
            f_root = getattr(self.m_runtime_layout, "benchmark_root", None) or getattr(
                self.m_runtime_layout, "benchmarkRoot", None
            )
        if not f_root:
            f_roots = siteBenchmarkRoots(("hdd",))
            f_root = f_roots[0] if f_roots else None
        return os.path.abspath(os.path.expanduser(f_root)) if f_root else None

    def _explicitSetup(self) -> Optional[str]:
        """--setup, else $BM_SETUP (validated like --setup), else None."""
        from lsmiotool.lib.archive import ArchiveError
        from lsmiotool.lib.cli import ArchiveCliParseError, ArchiveCliParser

        f_setup = getattr(self.m_request, "setup", None)
        if f_setup:
            return f_setup
        f_env = str(self.m_environ.get("BM_SETUP", "") or "").strip()
        if not f_env:
            return None
        try:
            return ArchiveCliParser.validateSetup(f_env)
        except ArchiveCliParseError as f_err:
            raise ArchiveError(f"BM_SETUP: {f_err}") from f_err

    @staticmethod
    def _manifestRequest(f_run_root: str) -> Dict[str, Any]:
        try:
            with open(
                os.path.join(f_run_root, "manifest.json"), "r", encoding="utf-8"
            ) as f_f:
                f_doc = json.load(f_f)
        except (OSError, ValueError):
            return {}
        f_req = f_doc.get("request") if isinstance(f_doc, dict) else None
        return f_req if isinstance(f_req, dict) else {}

    def _runArmId(
        self, f_run_root: str, f_setup: Optional[str], f_strict: bool
    ) -> Optional[str]:
        """Arm id of a run root matching the request (lsmio, scale, variant, setup).

        Returns None for a run that does not match, or raises ArchiveError when
        f_strict (an explicit --source)."""
        from lsmiotool.lib.archive import ArchiveEngine, ArchiveError

        f_req = self._manifestRequest(f_run_root)

        def mismatch(f_what: str) -> None:
            if f_strict:
                raise ArchiveError(
                    f"Run root {f_run_root} does not match the request: {f_what}"
                )

        f_target = str(f_req.get("target") or "").strip().lower()
        if f_target != "lsmio":
            mismatch(f"target {f_target!r}")
            return None
        f_scale = str(f_req.get("scale") or "").strip().lower()
        if f_scale == "baseline":
            f_scale = "variants"
        if f_scale != self.m_request.scale:
            mismatch(f"scale {f_scale!r}, not {self.m_request.scale!r}")
            return None
        f_run_setup = str(f_req.get("setup") or "NATIVE-M").strip().upper()
        if f_setup and f_setup != f_run_setup:
            mismatch(f"setup {f_run_setup!r}, not {f_setup!r}")
            return None
        try:
            f_arm = ArchiveEngine.resolveArmId(f_run_setup, f_req.get("variant"))
            f_req_arm = ArchiveEngine.resolveArmId(f_run_setup, self.m_request.variant)
        except Exception as f_err:
            mismatch(f"unknown variant ({f_err})")
            return None
        if f_arm != f_req_arm:
            mismatch(
                f"variant {f_req.get('variant')!r}, not {self.m_request.variant!r}"
            )
            return None
        return f_arm

    def _latestRunRoot(self, f_root: str, f_setup: Optional[str]) -> Optional[str]:
        """Latest standalone run under <f_root>/runs matching the request (see
        _runArmId). Arms of a multi-arm run are archived by 'lsmiotool run' itself."""
        from lsmiotool.lib.archive import ArchiveEngine

        f_runs = os.path.join(f_root, "runs")
        try:
            f_entries = sorted(os.listdir(f_runs), reverse=True)
        except OSError:
            return None
        for f_entry in f_entries:
            f_run_root = os.path.join(f_runs, f_entry)
            if os.path.islink(f_run_root) or not os.path.isfile(
                os.path.join(f_run_root, "manifest.json")
            ):
                continue
            if ArchiveEngine.readArmMarker(f_run_root) is not None:
                continue
            if self._runArmId(f_run_root, f_setup, False) is not None:
                return f_run_root
        return None

    @staticmethod
    def _holdsOutputs(f_dir: str) -> bool:
        """True for a directory with entries other than bmtool's .bm-job-ok marker."""
        try:
            return any(f_entry != ".bm-job-ok" for f_entry in os.listdir(f_dir))
        except OSError:
            return False

    def run(self) -> int:
        """Archive the resolved source into the destination; 0 on success, 1 on error."""
        from lsmiotool.lib.archive import (
            ArchiveEngine,
            ArchiveError,
            resolveArchiveDest,
        )

        try:
            f_setup = self._explicitSetup()
            f_scale = self.m_request.scale
            f_root = self._benchmarkRoot()
            f_explicit_dest = self.m_request.dest or self.m_dest_dir
            if f_root is None and not (
                f_explicit_dest and os.path.isabs(f_explicit_dest)
            ):
                raise ArchiveError(
                    "cannot resolve the benchmark root from the site profile; "
                    "pass an absolute --dest (and --source)"
                )
            f_dest_root = resolveArchiveDest(
                f_root or "",
                f_mode=None,
                f_scale=f_scale,
                f_explicit=f_explicit_dest,
            )

            # Source: explicit, else bmtool's $LSM_DIR_OBASE or the latest lsmiotool run
            f_source = self.m_source_dir or getattr(self.m_request, "source", None)
            f_run_root: Optional[str] = None
            if f_source:
                f_source = os.path.abspath(os.path.expanduser(f_source))
                if os.path.isfile(os.path.join(f_source, "manifest.json")):
                    f_arm = ArchiveEngine.readArmMarker(f_source)
                    if f_arm is not None:
                        raise ArchiveError(
                            f"{f_source} is the '{f_arm.get('label')}' arm of a "
                            f"{f_arm.get('group_kind')} run, which 'lsmiotool run' archives "
                            "itself (as :run/:base pairs or per backend)"
                        )
                    f_run_root, f_source = f_source, None
                else:
                    # Only bmtool outputs are moved (include/archive.in.sh moves
                    # $LSM_DIR_OBASE): never an arbitrary directory
                    from lsmiotool.lib.output import isBmtoolOutputDir

                    f_bm_outputs = (
                        os.path.realpath(os.path.join(f_root, "lsmio", "outputs"))
                        if f_root
                        else None
                    )
                    if not isBmtoolOutputDir(f_source) and (
                        os.path.realpath(f_source) != f_bm_outputs
                    ):
                        raise ArchiveError(
                            f"--source {f_source} is neither an lsmiotool run root "
                            "(manifest.json) nor a bmtool outputs directory "
                            "(<nodes>/<date>/out-*.txt); refusing to move it"
                        )
            else:
                if f_root is None:
                    raise ArchiveError(
                        "cannot resolve the benchmark root from the site profile; "
                        "pass --source"
                    )
                f_outputs = os.path.join(f_root, "lsmio", "outputs")
                f_latest = self._latestRunRoot(f_root, f_setup)
                f_has_outputs = self._holdsOutputs(f_outputs)
                if f_has_outputs and f_latest is not None:
                    raise ArchiveError(
                        f"Both bmtool outputs ({f_outputs}) and an lsmiotool run "
                        f"({f_latest}) could be archived; pick one with --source"
                    )
                if f_latest is not None:
                    f_run_root = f_latest
                elif f_has_outputs:
                    f_source = f_outputs
                else:
                    raise ArchiveError(
                        f"Nothing to archive: {f_outputs} is missing or empty and no "
                        f"lsmiotool run of 'lsmio {f_scale}'"
                        + (f" ({self.m_request.variant})" if self.m_request.variant else "")
                        + f" was found under {os.path.join(f_root, 'runs')}"
                        " (a failed bmtool job leaves its outputs in "
                        f"{os.path.join(f_root, 'lsmio', 'outputs-failed')})"
                    )

            if f_run_root is not None:
                f_arm_id = self._runArmId(f_run_root, f_setup, True)
                if f_arm_id is None:
                    raise ArchiveError(f"Cannot derive the arm of {f_run_root}")
                f_run_id = os.path.basename(f_run_root.rstrip(os.sep))
                f_manifest_id = self._manifestRunId(f_run_root) or f_run_id
                f_done = ArchiveEngine.findArchivedRun(f_dest_root, f_manifest_id)
                if f_done is not None:
                    raise ArchiveError(
                        f"Run '{f_manifest_id}' is already archived in {f_done}"
                    )
                f_target_dir, f_exported, f_skipped = ArchiveEngine.exportRunRoot(
                    f_run_root, f_dest_root, f_arm_id
                )
                for f_point in f_skipped:
                    sys.stderr.write(
                        f"Warning: point '{f_point}' did not succeed; not archived\n"
                    )
                sys.stdout.write(f"Archived {f_run_root} -> {f_target_dir}\n")
                log.Console.info(f"Archived {f_run_root} -> {f_target_dir}")
                return 0

            # bmtool outputs directory: include/archive.in.sh move-on-archive
            f_arm_id = ArchiveEngine.resolveArmId(
                f_setup=f_setup or "NATIVE-M",
                f_variant=self.m_request.variant,
            )
            f_target_dir = ArchiveEngine.executeArchive(
                f_source_dir=f_source,
                f_dest_root=f_dest_root,
                f_arm_id=f_arm_id,
                f_scale=f_scale,
            )
            sys.stdout.write(f"Archived {f_source} -> {f_target_dir}\n")
            log.Console.info(f"Archived {f_source} -> {f_target_dir}")
            return 0
        except ArchiveError as f_err:
            sys.stderr.write(f"Archive error: {f_err}\n")
            log.Console.error(f"Archive error: {f_err}")
            return 1
        except Exception as f_err:
            sys.stderr.write(f"Unexpected archive error: {f_err}\n")
            log.Console.error(f"Unexpected archive error: {f_err}")
            return 1

    def _manifestRunId(self, f_run_root: str) -> Optional[str]:
        try:
            with open(
                os.path.join(f_run_root, "manifest.json"), "r", encoding="utf-8"
            ) as f_f:
                f_doc = json.load(f_f)
        except (OSError, ValueError):
            return None
        f_id = f_doc.get("run_id") if isinstance(f_doc, dict) else None
        return str(f_id) if f_id else None


class ShellMain(BaseMain):
    """Interactive shell execution mode."""

    def run(self) -> None:
        """Start an interactive Python shell with local context."""
        import code

        code.interact(local=dict(globals(), **locals()))


class HpcEnvMain(BaseMain):
    """Output HPC Modules shell commands."""

    def run(self) -> None:
        """Print module shell commands to stdout."""
        from lsmiotool.lib import env, hpc

        hpc_modules = hpc.HpcModules()
        print(hpc_modules.shell_output(env.HPC_ENV))


class NotImplemented(BaseMain):
    """Placeholder for unimplemented execution modes."""

    def run(self) -> None:
        """Exit with error for unimplemented modes."""
        log.Console.error("Not Implemented")
        sys.exit(1)


class DemoMain(BaseMain):
    """Demo execution mode for example plots."""

    def __init__(self) -> None:
        super().__init__()

    def demoRunDummy(self) -> None:
        """Generate a dummy plot with sample data."""
        from lsmiotool.lib import plot

        fn = "demo.png"
        md = plot.PlotMetaData("Sports Watch Data", "Average Pulse", "Calorie Burnage")
        pd = plot.PlotData(
            "Sample Data",
            [80, 85, 90, 95, 100, 105, 110, 115, 120, 125],
            [240, 250, 260, 270, 280, 290, 300, 310, 320, 330],
        )
        p = plot.Plot(md, pd)
        p.plot(fn)
        log.Console.debug(f"Image generated: {fn}.")

    def demoRunSingle(self) -> None:
        """Generate a single IOR benchmark plot."""
        from lsmiotool.lib import data, plot

        ior_run = data.IorSummaryData(
            "/home/sbulut/src/archive.ISAMBARD/ior-base/outputs/ior-report.csv"
        )
        x_series, y_series = ior_run.time_series(False, 4, "64K")
        fn = "ior-write-4-64k.png"
        md = plot.PlotMetaData("IOR Data", "# of Nodes", "Max BW in MB")
        pd = plot.PlotData("ior-base-4-64k", x_series, y_series)
        p = plot.Plot(md, pd)
        p.plot(fn)
        log.Console.debug(f"Image generated: {fn}.")

    def demoRunMulti(self) -> None:
        """Generate multiple IOR benchmark plots."""
        from lsmiotool.lib import data, plot

        ior_run = data.IorSummaryData(
            "/home/sbulut/src/archive.ISAMBARD/ior-base/outputs/ior-report.csv"
        )
        fn = "ior-write-64k.png"
        md = plot.PlotMetaData("IOR Data", "# of Nodes", "Max BW in MB")

        x_series, y_series = ior_run.time_series(False, 4, "64K")
        pda = plot.PlotData("ior-base-4-64k", x_series, y_series)
        x_series, y_series = ior_run.time_series(False, 16, "64K")
        pdb = plot.PlotData("ior-base-16-64k", x_series, y_series)

        p = plot.MultiPlot(md, pda, pdb)
        p.plot(fn)
        log.Console.debug(f"Image generated: {fn}.")

    def run(self) -> None:
        """Execute demo mode with multiple plots."""
        return self.demoRunMulti()


class LatexMain(BaseMain):
    """LaTeX document generation mode for paper plots."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize with HPC environment selection.

        Args:
            *args: Variable length argument list
            **kwargs: Arbitrary keyword arguments
        """
        super().__init__()
        self.hpc: str = args[0]
        if self.hpc == "viking2":
            self._results_from_viking2()
        elif self.hpc == "isambard":
            self._results_from_isambard()
        else:  # "viking":
            self._results_from_viking()

    def _results_from_viking(self) -> None:
        """Set up paths for Viking HPC environment."""
        from lsmiotool.lib import env

        self.ior_data: str = env.ior_data
        self.lsmio_dir: str = env.lsmio_dir
        self.lsmio_data: str = env.lsmio_data
        self.plots_dir: str = env.plots_dir

    def _results_from_viking2(self) -> None:
        """Set up paths for Viking2 HPC environment."""
        from lsmiotool.lib import env

        self.ior_data: str = env.ior_data
        self.lsmio_dir: str = env.lsmio_dir
        self.lsmio_data: str = env.lsmio_data
        self.plots_dir: str = env.plots_dir

    def _results_from_isambard(self) -> None:
        """Set up paths for Isambard HPC environment."""
        from lsmiotool.lib import env

        self.ior_data: str = env.ior_data
        self.lsmio_dir: str = env.lsmio_dir
        self.lsmio_data: str = env.lsmio_data
        self.plots_dir: str = env.plots_dir

    def _gen_png_name(
        self, title: str, is_read: bool, num_stripes: int, stripe_size: str
    ) -> str:
        """
        Generate PNG filename from plot parameters.

        Args:
            title: Plot title
            is_read: Whether plot is for read operation
            num_stripes: Number of stripes
            stripe_size: Size of stripes

        Returns:
            Generated filename
        """
        operation = "read" if is_read else "write"
        return f"{title}-{operation}-{num_stripes}-{stripe_size}.pdf"

    def _gen_png_path(self, file_name: str) -> str:
        """
        Generate full path for PNG file.

        Args:
            file_name: Name of the file

        Returns:
            Full path to the file
        """
        return os.path.join(self.plots_dir, file_name)

    def run_step_paper41(self) -> None:
        """Generate write performance plot for paper section 4.1."""
        from lsmiotool.lib import data, plot

        ior_run = data.IorSummaryData(os.path.join(self.ior_dir, "ior-report.csv"))
        fn = self._gen_png_name("ior", False, 4, "64K")
        md = plot.PlotMetaData("IOR Data", "# of Nodes", "Max BW in MB")

        x_series, y_series = ior_run.time_series(False, 4, "64K")
        pda = plot.PlotData("ior-base-4-64k", x_series, y_series)

        p = plot.Plot(md, pda)
        p.plot(self._gen_png_path(fn))
        log.Console.debug(f"Image generated: {fn}.")

    def run_step_paper42(self) -> None:
        """Generate read performance plot for paper section 4.2."""
        from lsmiotool.lib import data, plot

        hdf5_run = data.IorSummaryData(
            os.path.join(self.ior_dir, "hdf5", "ior-report.csv")
        )
        adios_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "adios", "lsm-report.csv")
        )
        lsmio_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "lsmio", "lsm-report.csv")
        )
        fn = self._gen_png_name("lsmio", True, 4, "64K")
        md = plot.PlotMetaData("HDF5 vs. ADIOS vs. LSMIO", "# of Nodes", "Max BW in MB")

        x_series, y_series = hdf5_run.time_series(True, 4, "64K")
        pda = plot.PlotData("hdf5-4-64k", x_series, y_series)
        x_series, y_series = adios_run.time_series(True, 4, "64K")
        pdb = plot.PlotData("adios-4-64k", x_series, y_series)
        x_series, y_series = lsmio_run.time_series(True, 4, "64K")
        pdc = plot.PlotData("lsmio-4-64k", x_series, y_series)

        p = plot.MultiPlot(md, pda, pdb, pdc)
        p.plot(self._gen_png_path(fn))
        log.Console.debug(f"Image generated: {fn}.")

    def run_step_paper43(self) -> None:
        """Generate write performance plot for paper section 4.3."""
        from lsmiotool.lib import data, plot

        adios_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "adios", "lsm-report.csv")
        )
        lsmio_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "lsmio", "lsm-report.csv")
        )
        plugin_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "plugin", "lsm-report.csv")
        )
        fn = self._gen_png_name("lsmio", False, 4, "64K")
        md = plot.PlotMetaData(
            "ADIOS vs. LSMIO vs. PLUGIN", "# of Nodes", "Max BW in MB"
        )

        x_series, y_series = adios_run.time_series(False, 4, "64K")
        pda = plot.PlotData("adios-4-64k", x_series, y_series)
        x_series, y_series = lsmio_run.time_series(False, 4, "64K")
        pdb = plot.PlotData("lsmio-4-64k", x_series, y_series)
        x_series, y_series = plugin_run.time_series(False, 4, "64K")
        pdc = plot.PlotData("plugin-4-64k", x_series, y_series)

        p = plot.MultiPlot(md, pda, pdb, pdc)
        p.plot(self._gen_png_path(fn))
        log.Console.debug(f"Image generated: {fn}.")

    def run_step_paper44(self) -> None:
        """Generate read performance plot for paper section 4.4."""
        from lsmiotool.lib import data, plot

        adios_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "adios", "lsm-report.csv")
        )
        lsmio_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "lsmio", "lsm-report.csv")
        )
        plugin_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "plugin", "lsm-report.csv")
        )
        fn = self._gen_png_name("lsmio", True, 16, "64K")
        md = plot.PlotMetaData(
            "ADIOS vs. LSMIO vs. PLUGIN", "# of Nodes", "Max BW in MB"
        )

        x_series, y_series = adios_run.time_series(True, 16, "64K")
        pda = plot.PlotData("adios-16-64k", x_series, y_series)
        x_series, y_series = lsmio_run.time_series(True, 16, "64K")
        pdb = plot.PlotData("lsmio-16-64k", x_series, y_series)
        x_series, y_series = plugin_run.time_series(True, 16, "64K")
        pdc = plot.PlotData("plugin-16-64k", x_series, y_series)

        p = plot.MultiPlot(md, pda, pdb, pdc)
        p.plot(self._gen_png_path(fn))
        log.Console.debug(f"Image generated: {fn}.")

    def run_step_paper45(self) -> None:
        """Generate write performance plot for paper section 4.5."""
        from lsmiotool.lib import data, plot

        adios_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "adios", "lsm-report.csv")
        )
        lsmio_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "lsmio", "lsm-report.csv")
        )
        plugin_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "plugin", "lsm-report.csv")
        )
        fn = self._gen_png_name("lsmio", False, 16, "64K")
        md = plot.PlotMetaData(
            "ADIOS vs. LSMIO vs. PLUGIN", "# of Nodes", "Max BW in MB"
        )

        x_series, y_series = adios_run.time_series(False, 16, "64K")
        pda = plot.PlotData("adios-16-64k", x_series, y_series)
        x_series, y_series = lsmio_run.time_series(False, 16, "64K")
        pdb = plot.PlotData("lsmio-16-64k", x_series, y_series)
        x_series, y_series = plugin_run.time_series(False, 16, "64K")
        pdc = plot.PlotData("plugin-16-64k", x_series, y_series)

        p = plot.MultiPlot(md, pda, pdb, pdc)
        p.plot(self._gen_png_path(fn))
        log.Console.debug(f"Image generated: {fn}.")

    def run_step_paper46(self) -> None:
        """Generate read performance plot for paper section 4.6."""
        from lsmiotool.lib import data, plot

        adios_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "adios", "lsm-report.csv")
        )
        lsmio_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "lsmio", "lsm-report.csv")
        )
        plugin_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "plugin", "lsm-report.csv")
        )
        fn = self._gen_png_name("lsmio", True, 4, "1M")
        md = plot.PlotMetaData(
            "ADIOS vs. LSMIO vs. PLUGIN", "# of Nodes", "Max BW in MB"
        )

        x_series, y_series = adios_run.time_series(True, 4, "1M")
        pda = plot.PlotData("adios-4-1m", x_series, y_series)
        x_series, y_series = lsmio_run.time_series(True, 4, "1M")
        pdb = plot.PlotData("lsmio-4-1m", x_series, y_series)
        x_series, y_series = plugin_run.time_series(True, 4, "1M")
        pdc = plot.PlotData("plugin-4-1m", x_series, y_series)

        p = plot.MultiPlot(md, pda, pdb, pdc)
        p.plot(self._gen_png_path(fn))
        log.Console.debug(f"Image generated: {fn}.")

    def run_step_paper91(self) -> None:
        """Generate write performance plot for paper section 9.1."""
        from lsmiotool.lib import data, plot

        adios_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "adios", "lsm-report.csv")
        )
        lsmio_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "lsmio", "lsm-report.csv")
        )
        plugin_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "plugin", "lsm-report.csv")
        )
        fn = self._gen_png_name("lsmio", False, 4, "1M")
        md = plot.PlotMetaData(
            "ADIOS vs. LSMIO vs. PLUGIN", "# of Nodes", "Max BW in MB"
        )

        x_series, y_series = adios_run.time_series(False, 4, "1M")
        pda = plot.PlotData("adios-4-1m", x_series, y_series)
        x_series, y_series = lsmio_run.time_series(False, 4, "1M")
        pdb = plot.PlotData("lsmio-4-1m", x_series, y_series)
        x_series, y_series = plugin_run.time_series(False, 4, "1M")
        pdc = plot.PlotData("plugin-4-1m", x_series, y_series)

        p = plot.MultiPlot(md, pda, pdb, pdc)
        p.plot(self._gen_png_path(fn))
        log.Console.debug(f"Image generated: {fn}.")

    def run_step_paper92(self) -> None:
        """Generate read performance plot for paper section 9.2."""
        from lsmiotool.lib import data, plot

        adios_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "adios", "lsm-report.csv")
        )
        lsmio_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "lsmio", "lsm-report.csv")
        )
        plugin_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "plugin", "lsm-report.csv")
        )
        fn = self._gen_png_name("lsmio", True, 16, "1M")
        md = plot.PlotMetaData(
            "ADIOS vs. LSMIO vs. PLUGIN", "# of Nodes", "Max BW in MB"
        )

        x_series, y_series = adios_run.time_series(True, 16, "1M")
        pda = plot.PlotData("adios-16-1m", x_series, y_series)
        x_series, y_series = lsmio_run.time_series(True, 16, "1M")
        pdb = plot.PlotData("lsmio-16-1m", x_series, y_series)
        x_series, y_series = plugin_run.time_series(True, 16, "1M")
        pdc = plot.PlotData("plugin-16-1m", x_series, y_series)

        p = plot.MultiPlot(md, pda, pdb, pdc)
        p.plot(self._gen_png_path(fn))
        log.Console.debug(f"Image generated: {fn}.")

    def run_step_paper93(self) -> None:
        """Generate write performance plot for paper section 9.3."""
        from lsmiotool.lib import data, plot

        adios_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "adios", "lsm-report.csv")
        )
        lsmio_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "lsmio", "lsm-report.csv")
        )
        plugin_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "plugin", "lsm-report.csv")
        )
        fn = self._gen_png_name("lsmio", False, 16, "1M")
        md = plot.PlotMetaData(
            "ADIOS vs. LSMIO vs. PLUGIN", "# of Nodes", "Max BW in MB"
        )

        x_series, y_series = adios_run.time_series(False, 16, "1M")
        pda = plot.PlotData("adios-16-1m", x_series, y_series)
        x_series, y_series = lsmio_run.time_series(False, 16, "1M")
        pdb = plot.PlotData("lsmio-16-1m", x_series, y_series)
        x_series, y_series = plugin_run.time_series(False, 16, "1M")
        pdc = plot.PlotData("plugin-16-1m", x_series, y_series)

        p = plot.MultiPlot(md, pda, pdb, pdc)
        p.plot(self._gen_png_path(fn))
        log.Console.debug(f"Image generated: {fn}.")

    def run_step_paper95(self) -> None:
        """Generate read performance plot for paper section 9.5."""
        from lsmiotool.lib import data, plot

        adios_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "adios", "lsm-report.csv")
        )
        lsmio_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "lsmio", "lsm-report.csv")
        )
        plugin_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "plugin", "lsm-report.csv")
        )
        fn = self._gen_png_name("lsmio", True, 4, "4M")
        md = plot.PlotMetaData(
            "ADIOS vs. LSMIO vs. PLUGIN", "# of Nodes", "Max BW in MB"
        )

        x_series, y_series = adios_run.time_series(True, 4, "4M")
        pda = plot.PlotData("adios-4-4m", x_series, y_series)
        x_series, y_series = lsmio_run.time_series(True, 4, "4M")
        pdb = plot.PlotData("lsmio-4-4m", x_series, y_series)
        x_series, y_series = plugin_run.time_series(True, 4, "4M")
        pdc = plot.PlotData("plugin-4-4m", x_series, y_series)

        p = plot.MultiPlot(md, pda, pdb, pdc)
        p.plot(self._gen_png_path(fn))
        log.Console.debug(f"Image generated: {fn}.")

    def run(self) -> None:
        """Execute LaTeX document generation with all paper plots."""
        self.run_step_paper41()
        self.run_step_paper42()
        self.run_step_paper43()
        self.run_step_paper44()
        self.run_step_paper45()
        self.run_step_paper46()
        self.run_step_paper91()
        self.run_step_paper92()
        self.run_step_paper93()
        self.run_step_paper95()
