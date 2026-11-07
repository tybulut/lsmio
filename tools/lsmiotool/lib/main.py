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
import glob
import importlib
import json
import math
import os
import signal
import subprocess
import sys
import types
import time
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
    TYPE_CHECKING,
)

if TYPE_CHECKING:
    from lsmiotool.lib.cli import CompareRequest

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
        rebuilt. 'parse ior <scale>' covers <root>/lsmio-archive/ior/<scale>, where 'run
        ior' archives its IOR setups: each outputs-* gets its ior-report.csv (ior-parse.sh).
        'parse epocpp backends <scale>' covers <root>/lsmio-archive/epocpp/<scale>: each
        outputs-epocpp-* gets its epocpp-report.csv, and the scale its epocpp-cost.csv.
        """
        from lsmiotool.lib.archive import resolveArchiveDest

        f_mode = self.m_request.mode
        f_scale = self.m_request.scale
        f_target = self.m_request.target.strip().lower()
        if self.m_request.output_dir:
            f_dests = [os.path.abspath(os.path.expanduser(self.m_request.output_dir))]
        else:
            f_dests = [
                resolveArchiveDest(
                    f_root, f_mode=f_mode, f_scale=f_scale, f_target=f_target
                )
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

        from lsmiotool.lib.arms import isEpocppArmId, isIorArmId

        def _armKind(f_arm: str) -> str:
            if isIorArmId(f_arm):
                return "ior"
            return "epocpp" if isEpocppArmId(f_arm) else "lsmio"

        # 'parse lsmio backends' reads only LSMIO outputs, 'parse ior' only IOR ones and
        # 'parse epocpp backends' only EPOCpp ones
        f_arms = sorted(
            f_entry
            for f_entry in os.listdir(f_dest)
            if f_entry.startswith("outputs-")
            and os.path.isdir(os.path.join(f_dest, f_entry))
            and _armKind(f_entry[len("outputs-") :]) == f_target
        )
        if not f_arms:
            sys.stderr.write(f"Error: no outputs-* directories in {f_dest}\n")
            return 3

        if f_target == "epocpp":
            return self._regenerateEpocppDirs(
                [os.path.join(f_dest, f_arm) for f_arm in f_arms]
            )
        if f_target == "ior":
            return self._regenerateIorDirs(
                [os.path.join(f_dest, f_arm) for f_arm in f_arms]
            )
        f_node_scale = f_scale
        return self._regenerateOutputDirs(
            [
                (os.path.join(f_dest, f_arm), f"{f_arm[len('outputs-') :]} ({f_scale})")
                for f_arm in f_arms
            ],
            f_node_scale,
        )

    @staticmethod
    def _regenerateEpocppDirs(f_dirs: Sequence[str]) -> int:
        """Regenerate each epocpp arm's epocpp-report.csv, and the scale's
        epocpp-cost.csv.

        Returns:
            0 when at least one epocpp-report.csv was produced, 5 otherwise.
        """
        from lsmiotool.lib.epocppreport import (
            ARM_REPORT_FILE,
            writeArmReport,
            writeCostReport,
        )

        f_written = 0
        for f_dir in f_dirs:
            f_arm = os.path.basename(f_dir)[len("outputs-") :]
            sys.stdout.write(f"=== Generating report for {f_arm} ===\n")
            try:
                if writeArmReport(f_dir) is None:
                    sys.stderr.write(f"Warning: no EPOCpp results found in {f_dir}\n")
                    continue
            except Exception as f_err:
                sys.stderr.write(f"Error: failed to parse {f_dir}: {f_err}\n")
                continue
            f_written += 1
            sys.stdout.write(f"{os.path.join(f_dir, ARM_REPORT_FILE)}\n")
        if f_dirs:
            try:
                f_cost = writeCostReport(os.path.dirname(os.path.normpath(f_dirs[0])))
            except Exception as f_err:
                f_cost = None
                sys.stderr.write(
                    f"Error: failed to write the I/O cost report: {f_err}\n"
                )
            if f_cost is not None:
                sys.stdout.write(f"{f_cost}\n")
        sys.stdout.flush()
        return 0 if f_written else 5

    def _parseEpocppRunRoot(self, f_resolved_run: Any) -> int:
        """'parse <run root>' of an epocpp arm: its succeeded points exported, as the
        archive holds them, to <output dir>/outputs-<arm>/<nodes> (default: the cwd),
        and their reports written there.

        Returns:
            0 when every point was reported, 4 when the run did not succeed (the points
            that did are reported, if any), 5 when nothing could be reported otherwise,
            2 for --format json.
        """
        from lsmiotool.lib.archive import ArchiveEngine
        from lsmiotool.lib.export import exportEpocppPoint
        from lsmiotool.lib.run import RunOrchestrator, RunPlanner

        if self.format != "csv":
            sys.stderr.write(
                "Error: an epocpp run is reported as epocpp-report.csv only; "
                "--format json is not supported\n"
            )
            return 2
        f_plan = f_resolved_run.plan
        f_evidence = f_resolved_run.evidenceStore
        f_marker = ArchiveEngine.readArmMarker(f_resolved_run.runRoot) or {}
        f_arm_id = f_marker.get("arm_id")
        if not isinstance(f_arm_id, str) or not f_arm_id.startswith("epocpp-"):
            # The arm of a run root without its marker: its setup
            f_setup = (f_plan.request.setup or "POSIX").lower()
            f_arm_id = "epocpp-baseline" if f_setup == "none" else f"epocpp-{f_setup}"
        f_out = os.path.join(
            os.path.abspath(os.path.expanduser(self.output_dir or os.getcwd())),
            f"outputs-{f_arm_id}",
        )
        # What RunOrchestrator._armPointSucceeded reads of an arm group's run
        f_ctx = {
            "evidence": f_evidence,
            "plan": f_plan,
            "arm": types.SimpleNamespace(arm_id=f_arm_id),
        }
        f_done = 0
        f_kept = 0
        f_failed = 0
        for f_idx, f_sp in enumerate(f_plan.scale_points):
            if not RunOrchestrator._armPointSucceeded(f_ctx, f_idx):
                f_failed += 1
                sys.stderr.write(
                    f"Warning: point {f_evidence.layout.pointDirName(f_sp, f_idx)} did "
                    "not succeed; not reported\n"
                )
                continue
            f_node_dir = os.path.join(f_out, str(f_sp.nodes))
            # Like archiving, never replace a <nodes> directory already there (it may
            # hold another run's results)
            if os.path.lexists(f_node_dir):
                f_kept += 1
                sys.stderr.write(
                    f"Warning: '{f_node_dir}' exists; not replaced (move it away to "
                    "export this run's point)\n"
                )
                continue
            try:
                exportEpocppPoint(
                    f_layout=f_evidence.layout,
                    f_evidence_store=f_evidence,
                    f_scale_point=f_sp,
                    f_ordinal=f_idx,
                    f_combinations=f_plan.combinations,
                    f_arm_id=f_arm_id,
                    f_repeats=f_plan.request.repeats
                    or RunPlanner.EPOCPP_DEFAULT_REPEATS,
                    f_node_dir=f_node_dir,
                )
            except Exception as f_err:
                sys.stderr.write(f"Error: exporting point {f_idx} failed: {f_err}\n")
                continue
            f_done += 1
        if f_done + f_kept == 0:
            sys.stderr.write(
                f"Error: no point of run '{f_resolved_run.runId}' could be reported\n"
            )
            # As for the other benchmarks: 4 when the run did not succeed
            return 4 if f_failed else 5
        f_status = self._regenerateEpocppDirs([f_out])
        if f_status != 0:
            return f_status
        return 0 if f_done + f_kept == len(f_plan.scale_points) else 4

    @staticmethod
    def _regenerateIorDirs(f_dirs: Sequence[str]) -> int:
        """Regenerate ior-report.csv in each IOR outputs dir, through IorAggOutput.

        Returns:
            0 when at least one ior-report.csv was produced, 5 otherwise.
        """
        from lsmiotool.lib.data import IOR_REPORT_FILE
        from lsmiotool.lib.output import IorAggOutput

        f_written = 0
        for f_dir in f_dirs:
            f_base = os.path.basename(os.path.normpath(f_dir))
            f_label = f_base[len("outputs-") :] if f_base.startswith("outputs-") else f_base
            sys.stdout.write(f"=== Generating report for {f_label} ===\n")
            try:
                # None (no summary rows) is the failure; an old report may exist
                if IorAggOutput(f_dir).generateReports() is None:
                    sys.stderr.write(f"Warning: no IOR results found in {f_dir}\n")
                    continue
            except Exception as f_err:
                sys.stderr.write(f"Error: failed to parse {f_dir}: {f_err}\n")
                continue
            f_written += 1
            sys.stdout.write(f"{os.path.join(f_dir, IOR_REPORT_FILE)}\n")
        sys.stdout.flush()
        return 0 if f_written else 5

    @staticmethod
    def _isIorArmDir(f_dir: str) -> bool:
        """True for the archive dir of an IOR arm, outputs-ior[-<setup>]."""
        from lsmiotool.lib.arms import isIorArmId

        f_name = os.path.basename(f_dir.rstrip(os.sep))
        return f_name.startswith("outputs-") and isIorArmId(f_name[len("outputs-") :])

    @staticmethod
    def _hasIorBanner(f_dir: str) -> bool:
        """True when a rank log <dir>/<nodes>/<date>/out-* starts with the IOR banner.

        Only the first line of each regular, non-empty log is read, in sorted path
        order, until the first banner. Some IOR logs have no banner (they start with
        an HDF5 or MPI error), so one banner anywhere is enough.
        """
        f_paths = sorted(
            glob.iglob(os.path.join(glob.escape(f_dir), "*", "*", "out-*"))
        )
        for f_path in f_paths:
            if not os.path.relpath(f_path, f_dir).split(os.sep)[0].isdigit():
                continue
            try:
                if not os.path.isfile(f_path) or os.path.getsize(f_path) == 0:
                    continue
                with open(f_path, errors="replace") as f_file:
                    f_first = f_file.readline()
            except OSError:
                continue
            if f_first.startswith("IOR-") and (
                "MPI Coordinated Test of Parallel I/O" in f_first
            ):
                return True
        return False

    def _isIorOutputsDir(self, f_dir: str) -> bool:
        """An IOR outputs dir: outputs-ior[-<setup>] by name, else by the IOR banner in
        its rank logs. An EPOCpp arm (by name) is never IOR."""
        if self._isEpocppArmDir(f_dir):
            return False
        return self._isIorArmDir(f_dir) or self._hasIorBanner(f_dir)

    def _parseBmtoolLayout(self, f_dir: str) -> int:
        """Regenerate reports for a bmtool-layout outputs dir or an archive of them; an
        IOR dir (outputs-ior[-<setup>] or any dir whose rank logs carry the IOR banner)
        gets its ior-report.csv and an epocpp arm (outputs-epocpp-*) its
        epocpp-report.csv, never LSMIO reports."""
        from lsmiotool.lib.output import IorAggOutput, isBmtoolOutputDir

        f_scale = self.m_request.scale
        f_epocpp_dirs = (
            [f_dir]
            if self._isEpocppArmDir(f_dir)
            else [
                os.path.join(f_dir, f_entry)
                for f_entry in sorted(os.listdir(f_dir))
                if self._isEpocppArmDir(os.path.join(f_dir, f_entry))
                and os.path.isdir(os.path.join(f_dir, f_entry))
            ]
        )
        if f_epocpp_dirs and self.m_request.format != "csv":
            sys.stderr.write(
                f"Error: {f_dir} holds EPOCpp outputs, reported as epocpp-report.csv "
                "only; --format json is not supported\n"
            )
            return 2
        if self._isEpocppArmDir(f_dir):
            if self.m_request.output_dir:
                sys.stderr.write(
                    f"Error: an EPOCpp arm's reports are written in its archive "
                    f"({f_dir}); --output-dir is not supported for it\n"
                )
                return 2
            return self._regenerateEpocppDirs([f_dir])
        if self.m_request.format != "csv" and (
            self._isIorOutputsDir(f_dir)
            or any(
                f_entry.startswith("outputs-")
                and os.path.isdir(os.path.join(f_dir, f_entry))
                and self._isIorOutputsDir(os.path.join(f_dir, f_entry))
                for f_entry in os.listdir(f_dir)
            )
        ):
            # As 'parse ior <scale>' rejects it: IOR outputs give ior-report.csv only
            sys.stderr.write(
                f"Error: {f_dir} holds IOR outputs, reported as ior-report.csv only; "
                "--format json is not supported\n"
            )
            return 2
        if self._isIorOutputsDir(f_dir):
            if self.m_request.output_dir:
                f_report = IorAggOutput(f_dir).generateReports(
                    os.path.abspath(self.m_request.output_dir)
                )
                if f_report is None:
                    sys.stderr.write(f"Warning: no IOR results found in {f_dir}\n")
                    return 5
                sys.stdout.write(f"{f_report}\n")
                return 0
            return self._regenerateIorDirs([f_dir])
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
        f_ior = [f_c for f_c in f_children if self._isIorOutputsDir(f_c)]
        f_lsmio = [
            f_c for f_c in f_children if f_c not in f_ior and f_c not in f_epocpp_dirs
        ]
        f_codes = []
        if f_epocpp_dirs:
            # In the archive, as 'parse epocpp backends' writes them
            f_codes.append(self._regenerateEpocppDirs(f_epocpp_dirs))
        if f_lsmio:
            f_codes.append(
                self._regenerateOutputDirs(
                    [(f_child, os.path.basename(f_child)) for f_child in f_lsmio],
                    f_scale,
                )
            )
        if f_ior:
            f_codes.append(self._regenerateIorDirs(f_ior))
        # 0 when either kind produced a report, as each does for its own dirs
        return 0 if 0 in f_codes else 5

    @staticmethod
    def _isEpocppArmDir(f_dir: str) -> bool:
        """f_dir is an epocpp arm's archive (outputs-epocpp-<kind>)."""
        from lsmiotool.lib.arms import isEpocppArmId

        f_name = os.path.basename(os.path.normpath(f_dir))
        return f_name.startswith("outputs-") and isEpocppArmId(
            f_name[len("outputs-") :]
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
            # scale (variants included) parses the latest run, like bmtool's live outputs.
            # 'parse ior <scale>' is the archive mode of 'run ior' (lsmio-archive/ior)
            f_target_name = self.m_request.target.strip().lower()
            if (
                f_target_name in ("lsmio", "ior", "epocpp")
                and self.m_request.mode == "backends"
            ):
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
            if f_resolved_run.target.lower() == "epocpp":
                return self._parseEpocppRunRoot(f_resolved_run)

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





class CompareMain(BaseMain):
    """Subcommand orchestrator for 'compare': runs the dataset builder and the panel plot."""

    m_request: "CompareRequest"

    def __init__(self, f_request: "CompareRequest") -> None:
        super().__init__()
        from lsmiotool.lib import cli

        if not isinstance(f_request, cli.CompareRequest):
            raise TypeError(
                f"f_request must be an instance of CompareRequest, got {type(f_request).__name__}"
            )
        self.m_request = f_request

    @property
    def request(self) -> "CompareRequest":
        return self.m_request

    def run(self) -> int:
        from lsmiotool.lib import compare, plot

        try:
            f_dataset = compare.CompareDatasetBuilder(self.m_request).build()
        except compare.CompareFolderError as f_err:
            log.Console.error(str(f_err))
            return 3
        except (
            compare.CompareKindError,
            compare.CompareSelectionError,
            compare.CompareNoDataError,
        ) as f_err:
            log.Console.error(str(f_err))
            return 1

        try:
            os.makedirs(f_dataset.output_dir, exist_ok=True)
        except OSError as f_err:
            log.Console.error(
                f"Cannot create the output directory {f_dataset.output_dir}: {f_err}"
            )
            return 1

        for f_png in f_dataset.pngs:
            try:
                plot.ComparePanelPlot(f_png.figure, self.m_request.style).plot(
                    f_png.path
                )
            except OSError as f_err:
                log.Console.error(f"Cannot write {f_png.path}: {f_err}")
                return 1
            log.Console.info(f"Comparison plot saved to {f_png.path}")

        return 0


def _stdoutIsTerminal() -> bool:
    try:
        return os.isatty(sys.stdout.fileno())
    except (AttributeError, OSError, ValueError):
        return False


class RunMain(BaseMain):
    """Run command for executing benchmarks via RunOrchestrator."""

    m_request: Any
    m_orchestrator_factory: Optional[Callable[..., Any]]
    m_worker_validator: Optional[Any]
    m_site: Optional[Union[str, Any]]
    m_runtime_layout: Optional[Any]
    m_reporter: Optional[Any]
    m_detach: bool

    def __init__(
        self,
        *f_args: Any,
        f_request: Optional[Any] = None,
        f_orchestrator_factory: Optional[Callable[..., Any]] = None,
        f_worker_validator: Optional[Any] = None,
        f_site: Optional[Union[str, Any]] = None,
        f_runtime_layout: Optional[Any] = None,
        f_reporter: Optional[Any] = None,
        f_detach: bool = False,
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
            f_detach: Detach the run from a terminal stdout once its run roots exist
                (lib/detach.py); the launchers set it unless --foreground is given.
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
        self.m_detach = bool(f_detach)
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

        # From a terminal the run detaches once its run roots exist (lib/detach.py), so a
        # dropped login session does not stop it; scripts and pipes keep it attached
        f_extra: Dict[str, Any] = {}
        if self.m_detach and hasattr(os, "fork") and _stdoutIsTerminal():
            from lsmiotool.lib.detach import detachAndFollow

            f_extra["f_on_ready"] = detachAndFollow
        try:
            f_view = f_orch.execute(
                f_request=self.m_request,
                f_site=self.m_site,
                f_runtime_layout=self.m_runtime_layout,
                **f_extra,
            )
            return f_orch.exitCode
        except (PreflightError, OrchestrationError) as f_err:
            sys.stderr.write(f"Error: {f_err}\n")
            return 1
        except Exception as f_err:
            sys.stderr.write(f"Unexpected error: {f_err}\n")
            return 1


class ArchiveMain(BaseMain):
    """'lsmiotool archive': export a finished lsmiotool run into the archive.

    Benchmark root: f_benchmark_root, else the site profile's benchmark root (hdd,
    no --ssd) - never the working directory.
    Destination: --dest, else <root>/lsmio-archive/{variants|baseline}; for ior,
    <root>/lsmio-archive/ior/<scale>, where 'run ior' archives (an epocpp run archives
    to <root>/lsmio-archive/epocpp/<scale> from --source). An inherited BM_ARCHIVE_DEST
    is ignored.
    Arm: outputs-<arm>, arm = resolveArmId(setup, variant) with setup from --setup,
    else $BM_SETUP, else NATIVE (an lsmiotool run root: the run's own setup).
    Source: --source takes an lsmiotool run root (manifest.json) only; any other
    directory is refused and left untouched. Without --source, the latest standalone
    lsmiotool run of 'lsmio <scale>' [variant] under <root>/runs is exported in the
    archive layout (lib/export.py) for its succeeded points; the run root stays where
    it is (no empty runs/run-* left behind) and a run already exported to the
    destination is not archived again. Arms of a multi-arm run are archived with
    --source <one of its run roots>.
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
        if self.m_request.target != "lsmio":
            # BM_SETUP is bmtool's LSMIO setup
            return None
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
        if f_target != self.m_request.target:
            mismatch(f"target {f_target!r}")
            return None
        f_scale = str(f_req.get("scale") or "").strip().lower()
        if f_scale == "baseline":
            f_scale = "variants"
        if f_scale != self.m_request.scale:
            mismatch(f"scale {f_scale!r}, not {self.m_request.scale!r}")
            return None
        if f_target == "ior":
            from lsmiotool.lib.arms import IOR_ARMS, ArmError, iorArmToken

            f_ior_setup = str(f_req.get("setup") or "BASE").strip().upper()
            if f_setup and f_setup != f_ior_setup:
                mismatch(f"setup {f_ior_setup!r}, not {f_setup!r}")
                return None
            try:
                return IOR_ARMS[iorArmToken(f_ior_setup)][1]
            except ArmError as f_err:
                mismatch(str(f_err))
                return None
        from lsmiotool.lib.benchmarks import LsmioAdapter

        f_run_setup = str(f_req.get("setup") or "NATIVE").strip().upper()
        if f_run_setup in LsmioAdapter.ARM_ONLY_SETUPS:
            # A -sync arm of a backends run: archived by its arm marker, never as a run of its
            # own (outputs-<setup> would take the 'sync' variant's name)
            mismatch(
                f"setup {f_run_setup!r} is a backends arm, archived with its backends run"
            )
            return None
        if f_run_setup not in LsmioAdapter.RUN_SETUPS:
            mismatch(f"setup {f_run_setup!r} is no longer supported")
            return None
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
        _runArmId). Arms of a multi-arm run are archived by 'lsmiotool run' itself, or
        with an explicit --source naming one of their run roots."""
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

    def _groupArmRunRoots(self, f_root: str, f_setup: Optional[str]) -> List[str]:
        """Names of the runs under <f_root>/runs that match the request but were
        skipped by _latestRunRoot as arms of a multi-arm run (readArmMarker)."""
        from lsmiotool.lib.archive import ArchiveEngine

        f_runs = os.path.join(f_root, "runs")
        try:
            f_entries = sorted(os.listdir(f_runs), reverse=True)
        except OSError:
            return []
        f_names: List[str] = []
        for f_entry in f_entries:
            f_run_root = os.path.join(f_runs, f_entry)
            if os.path.islink(f_run_root) or not os.path.isfile(
                os.path.join(f_run_root, "manifest.json")
            ):
                continue
            if ArchiveEngine.readArmMarker(
                f_run_root
            ) is not None and self._runArmId(f_run_root, f_setup, False):
                f_names.append(f_entry)
        return f_names

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
            f_source = self.m_source_dir or getattr(self.m_request, "source", None)
            if f_source:
                f_source = os.path.abspath(os.path.expanduser(f_source))
                # A group run archives to the destination it recorded: no root needed
                if (
                    os.path.isfile(os.path.join(f_source, "manifest.json"))
                    and ArchiveEngine.readArmMarker(f_source) is not None
                ):
                    return self._archiveGroupRun(
                        f_source, f_explicit_dest, f_root, f_scale
                    )
            if self.m_request.target == "epocpp":
                # 'run epocpp backends' archives itself; what it left is archived from
                # one of its arms' run roots
                raise ArchiveError(
                    "an epocpp run is archived with --source <run root of one of its "
                    "arms> (runs/<run id> with .lsmiotool-arm.json)"
                )
            if f_root is None and not (
                f_explicit_dest and os.path.isabs(f_explicit_dest)
            ):
                raise ArchiveError(
                    "cannot resolve the benchmark root from the site profile; "
                    "pass an absolute --dest (and --source)"
                )
            f_ior = self.m_request.target == "ior"
            f_dest_root = resolveArchiveDest(
                f_root or "",
                # Where 'run ior' archives: lsmio-archive/ior/<scale>
                f_mode="backends" if f_ior else None,
                f_scale=f_scale,
                f_explicit=f_explicit_dest,
                f_target=self.m_request.target,
            )

            # Source: an explicit run root, else the latest standalone lsmiotool run
            f_run_root: Optional[str] = None
            if f_source:
                if os.path.isfile(os.path.join(f_source, "manifest.json")):
                    f_run_root, f_source = f_source, None
                elif f_ior:
                    # bmtool never archived IOR: only lsmiotool runs are archived
                    raise ArchiveError(
                        f"--source {f_source} is not an lsmiotool run root "
                        "(manifest.json); an ior archive takes only an ior run root"
                    )
                else:
                    # Only an lsmiotool run root is archived: never an archive, a copy
                    # or any other directory, which moving would break or misfile
                    raise ArchiveError(
                        f"--source {f_source} is not an lsmiotool run root "
                        "(manifest.json); refusing to archive it (--source takes the "
                        "run root of an lsmiotool run)"
                    )
            else:
                if f_root is None:
                    raise ArchiveError(
                        "cannot resolve the benchmark root from the site profile; "
                        "pass --source"
                    )
                f_runs_root = os.path.join(f_root, "runs")
                f_latest = self._latestRunRoot(f_root, f_setup)
                if f_latest is not None:
                    f_run_root = f_latest
                else:
                    f_skipped = self._groupArmRunRoots(f_root, f_setup)
                    f_hint = (
                        f"; {len(f_skipped)} matching run(s) belong to a multi-arm "
                        f"run and are not taken ({', '.join(f_skipped)}): archive one "
                        "with --source <its run root>"
                        if f_skipped
                        else ""
                    )
                    if f_ior:
                        raise ArchiveError(
                            f"Nothing to archive: no lsmiotool run of 'ior {f_scale}'"
                            + (f" ({f_setup})" if f_setup else "")
                            + f" was found under {f_runs_root} (a multi-setup "
                            "ior run is archived with --source <one of its run roots>)"
                            + f_hint
                        )
                    raise ArchiveError(
                        f"Nothing to archive: no lsmiotool run of 'lsmio {f_scale}'"
                        + (
                            f" ({self.m_request.variant})"
                            if self.m_request.variant
                            else ""
                        )
                        + f" was found under {f_runs_root} (a variants, --versioned "
                        "or backends run is archived with --source <one of its run "
                        "roots>)"
                        + f_hint
                    )

            if f_run_root is not None:
                f_arm_id = self._runArmId(f_run_root, f_setup, True)
                if f_arm_id is None:
                    raise ArchiveError(f"Cannot derive the arm of {f_run_root}")
                from lsmiotool.lib.run import liveOrchestratorMessage

                f_live = liveOrchestratorMessage([f_run_root])
                if f_live:
                    raise ArchiveError(f_live)
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

            raise ArchiveError("Nothing to archive")
        except ArchiveError as f_err:
            sys.stderr.write(f"Archive error: {f_err}\n")
            log.Console.error(f"Archive error: {f_err}")
            return 1
        except Exception as f_err:
            sys.stderr.write(f"Unexpected archive error: {f_err}\n")
            log.Console.error(f"Unexpected archive error: {f_err}")
            return 1

    def _archiveGroupRun(
        self,
        f_arm_root: str,
        f_explicit_dest: Optional[str],
        f_root: Optional[str],
        f_scale: str,
    ) -> int:
        """Archive what 'run' left unarchived of the multi-arm run f_arm_root belongs to:
        its finished points, as :run/:base pairs or per backend, in the run's own archive
        destination unless --dest is given. The variant argument is not used: every arm
        of the run is considered."""
        from lsmiotool.lib.archive import ArchiveError, resolveArchiveDest
        from lsmiotool.lib.run import RunOrchestrator

        f_req = self._manifestRequest(f_arm_root)
        f_target = str(f_req.get("target") or "").strip().lower()
        f_run_scale = str(f_req.get("scale") or "").strip().lower()
        if f_run_scale == "baseline":
            f_run_scale = "variants"
        if f_target != self.m_request.target or f_run_scale != f_scale:
            raise ArchiveError(
                f"Run root {f_arm_root} does not match the request: "
                f"{f_target} {f_run_scale}, not {self.m_request.target} {f_scale}"
            )
        if f_explicit_dest and f_root is None and not os.path.isabs(f_explicit_dest):
            raise ArchiveError(
                "cannot resolve the benchmark root from the site profile; pass an "
                "absolute --dest"
            )
        f_dest = (
            resolveArchiveDest(
                f_root or "", f_scale=f_scale, f_explicit=f_explicit_dest
            )
            if f_explicit_dest
            else None
        )
        f_ok, f_archived = RunOrchestrator().archiveGroupRun(
            f_arm_root,
            f_dest_root=f_dest,
            f_reporter=lambda f_line: sys.stdout.write(f"{f_line}\n"),
        )
        if not f_ok:
            raise ArchiveError(f"archiving the run of {f_arm_root} failed (see above)")
        if not f_archived:
            sys.stdout.write(
                f"Nothing to archive for the run of {f_arm_root}: every finished point "
                "is archived already, or no arm finished a point with its baseline\n"
            )
        return 0

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


class CancelMain(BaseMain):
    """'lsmiotool cancel <run root | run id>': stop a running 'lsmiotool run'.

    Sends SIGTERM to the orchestrator recorded in the run root's control/orchestrator.pid,
    which interrupts the run as Ctrl-C does in the foreground: its job is cancelled and
    the interruption recorded. Any arm's run root of a multi-arm run will do."""

    WAIT_SECONDS = 300.0
    POLL_SECONDS = 2.0

    def __init__(self, f_target: str, f_wait: Optional[float] = None) -> None:
        super().__init__()
        self.m_target = f_target
        self.m_wait = self.WAIT_SECONDS if f_wait is None else f_wait

    def _runRoot(self) -> Optional[str]:
        f_path = os.path.abspath(os.path.expanduser(self.m_target))
        if os.path.isfile(os.path.join(f_path, "manifest.json")):
            return f_path
        if os.sep not in self.m_target:
            for f_root in siteBenchmarkRoots(("hdd", "ssd")):
                f_run = os.path.join(f_root, "runs", self.m_target)
                if os.path.isfile(os.path.join(f_run, "manifest.json")):
                    return f_run
        return None

    def run(self) -> int:
        from lsmiotool.lib.run import (
            orchestratorPidPath,
            orchestratorRunning,
            readOrchestratorPid,
        )

        f_root = self._runRoot()
        if f_root is None:
            sys.stderr.write(f"Cancel: no run root or run id {self.m_target!r}\n")
            return 1
        f_doc = readOrchestratorPid(f_root)
        f_running = orchestratorRunning(f_doc)
        if f_running is False:
            sys.stderr.write(
                f"Cancel: no lsmiotool run is running for {f_root} (it has finished or "
                "was stopped)\n"
            )
            return 1
        f_pid = int((f_doc or {}).get("pid", 0))
        if f_running is None:
            sys.stderr.write(
                f"Cancel: the run is on host {f_doc.get('host')!r} (PID {f_pid}); run "
                f"'lsmiotool cancel' there, or remove {orchestratorPidPath(f_root)} if "
                "that process is gone\n"
            )
            return 1
        try:
            os.kill(f_pid, signal.SIGTERM)
        except OSError as f_err:
            sys.stderr.write(f"Cancel: cannot signal PID {f_pid}: {f_err}\n")
            return 1
        sys.stdout.write(
            f"Sent SIGTERM to the run (PID {f_pid}); it cancels its job and stops.\n"
        )
        from lsmiotool.lib.detach import consoleLogFor

        f_deadline = time.monotonic() + self.m_wait
        while orchestratorRunning(readOrchestratorPid(f_root)):
            if time.monotonic() >= f_deadline:
                f_log = consoleLogFor(f_root)
                sys.stdout.write(
                    "Still stopping (it waits for the scheduler to confirm the "
                    "cancellation); "
                    + (
                        f"see {f_log}\n"
                        if os.path.isfile(f_log)
                        else "its output is in the terminal it runs in (--foreground)\n"
                    )
                )
                return 0
            time.sleep(self.POLL_SECONDS)
        sys.stdout.write("Stopped.\n")
        return 0


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


class LatexDataMain(BaseMain):
    """latex data: rebuild a paper's chart data (TSV files) from the benchmark reports.

    Command:
        latex data <sources.yaml> --data-dir <dir> --output-dir <dir>

    The sources.yaml names, for every TSV, the report it is built from (see
    lsmiotool.lib.paperdata). Nothing is written when any TSV cannot be built.
    """

    def __init__(self, f_request: Any) -> None:
        """Initialize with a parsed latex request (lsmiotool.lib.cli.LatexRequest)."""
        super().__init__()
        self.m_request = f_request

    def run(self) -> int:
        """Rebuild the TSVs and print each written file with the sources of its rows;
        returns 0, or 1 when sources.yaml or a report is unusable."""
        from lsmiotool.lib import paperdata

        f_request = self.m_request
        f_output_dir = os.path.expanduser(f_request.output_dir)
        try:
            f_sources = paperdata.loadSources(os.path.expanduser(f_request.sources_path))
            f_results = paperdata.generate(
                f_sources, os.path.expanduser(f_request.data_dir), f_output_dir
            )
        except paperdata.PaperDataError as f_err:
            log.Console.error(str(f_err))
            return 1
        for f_result in f_results:
            sys.stdout.write(f"Wrote {os.path.join(f_output_dir, f_result.spec.output)}\n")
            for f_line in f_result.provenance:
                sys.stdout.write(f"  {f_line}\n")
        return 0


class LatexMain(BaseMain):
    """latex plots: draw preview PDFs of a paper's figures from its chart data.

    Command:
        latex plots <sources.yaml> --tsv-dir <dir> [--output-dir <dir>]

    The figures are the sources.yaml's; each series is read from a TSV that
    'latex data' wrote under <dir>. The PDFs go to --output-dir (default: the current
    working directory).
    """

    def __init__(self, f_request: Any) -> None:
        """Initialize with a parsed latex request (lsmiotool.lib.cli.LatexRequest)."""
        super().__init__()
        self.m_request = f_request

    def run(self) -> int:
        """Draw every figure; returns 0, or 1 when sources.yaml or a TSV is unusable."""
        from lsmiotool.lib import paperdata, plot

        f_request = self.m_request
        f_tsv_dir = os.path.expanduser(f_request.tsv_dir)
        f_output_dir = os.path.expanduser(f_request.output_dir or os.getcwd())
        try:
            f_sources = paperdata.loadSources(os.path.expanduser(f_request.sources_path))
            if not f_sources.figures:
                raise paperdata.PaperDataError(
                    f"{f_request.sources_path} defines no figures"
                )
            for f_figure in f_sources.figures:
                f_plots = []
                for f_series in f_figure.series:
                    f_x, f_y = paperdata.readSeries(
                        os.path.join(f_tsv_dir, f_series.dataset), f_series
                    )
                    # a series of nan points only (runs without data) would draw nothing
                    if all(math.isnan(f_v) for f_v in f_y):
                        raise paperdata.PaperDataError(
                            f"{f_figure.file}: series '{f_series.label}' has no data in "
                            f"{f_series.dataset}"
                        )
                    f_plots.append(
                        plot.PlotData(
                            f_series.label, f_x, [f_v / f_figure.y_divisor for f_v in f_y]
                        )
                    )
                f_meta = plot.PlotMetaData(f_figure.title, "# of Nodes", f_figure.y_label)
                f_path = os.path.join(f_output_dir, f_figure.file)
                os.makedirs(os.path.dirname(f_path), exist_ok=True)
                plot.MultiPlot(f_meta, *f_plots).plot(f_path)
                sys.stdout.write(f"Image generated: {f_path}\n")
        except (paperdata.PaperDataError, OSError, ValueError) as f_err:
            log.Console.error(str(f_err))
            return 1
        return 0
