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


class ParseLegacyMain(BaseMain):
    """ParseLegacy command for processing benchmark output logs."""

    VALID_MODES: FrozenSet[str] = frozenset(
        {"local", "bake", "small", "large", "baseline"}
    )

    m_command: str
    m_mode: str
    m_is_ssd: bool

    def __init__(self, *f_args: Any, **f_kwargs: Any) -> None:
        """Initialize ParseLegacyMain.

        Command: parseLegacy <ior|lsmio|lmp> <local|bake|small|large|baseline> [--ssd]

        Args:
            *f_args: Variable length argument list (command, mode)
            **f_kwargs: Keyword arguments (ssd=True/False)
        """
        super().__init__()
        if len(f_args) < 2:
            log.Console.error(
                "ParseLegacy: Needs two arguments: <ior|lsmio|lmp> <local|bake|small|large|baseline>"
            )
            sys.exit(1)
        self.m_command = f_args[0]
        self.m_mode = f_args[1]
        self.m_is_ssd = f_kwargs.get("ssd", False)

        allowed_commands = ["ior", "lsmio", "lmp"]
        if self.m_command not in allowed_commands:
            log.Console.error(
                "Command to execute has to be in: " + str(allowed_commands)
            )
            sys.exit(1)
        allowed_modes = ["local", "bake", "small", "large", "baseline"]
        if self.m_mode not in self.VALID_MODES:
            log.Console.error("Command mode has to be in: " + str(allowed_modes))
            sys.exit(1)

    def _getTargetDir(self, f_bench_type: str, f_mode: str, f_is_ssd: bool) -> str:
        """Resolve root log/output directory for parsing based on environment and options.

        Args:
            f_bench_type: Benchmark type ('ior', 'lsmio', 'lmp').
            f_mode: Execution mode ('local', 'bake', 'small', 'large').
            f_is_ssd: Whether SSD storage path is used.

        Returns:
            Absolute path to directory to parse.
        """
        from lsmiotool.lib import dirs, env

        if f_bench_type == "ior":
            if f_mode == "small":
                dir_path = os.path.expanduser(
                    os.path.join(
                        env.base_path,
                        *env._env.get("ior_dirs", []),
                        env.ior_data.get("base", "ior-base"),
                    )
                )
                if os.path.exists(dir_path):
                    return dir_path
            return os.path.expanduser(dirs.get_log_dir(env.BM_DIR)["LOG"])
        elif f_bench_type == "lsmio":
            if f_mode == "small":
                dir_path = os.path.expanduser(
                    os.path.join(
                        env.base_path, *env._env.get("lsmio_dirs", []), "lsmio-adios"
                    )
                )
                if os.path.exists(dir_path):
                    return dir_path
                dir_path_alt = os.path.expanduser(
                    os.path.join(
                        env.base_path,
                        *env._env.get("lsmio_dirs", []),
                        env.lsmio_data.get("adios", "lsmio-adios-m"),
                    )
                )
                if os.path.exists(dir_path_alt):
                    return dir_path_alt
            return os.path.expanduser(dirs.get_log_dir(env.BM_DIR)["LOG"])
        elif f_bench_type == "lmp":
            if f_mode == "small":
                dir_path = os.path.expanduser(
                    os.path.join(
                        env.base_path,
                        "synthetic",
                        "viking",
                        "lmp-small-hdd",
                        "lmp-reaxff",
                    )
                )
                if os.path.exists(dir_path):
                    return dir_path
            return os.path.expanduser(dirs.get_log_dir(env.BM_DIR)["LOG"])
        return os.path.expanduser(env.BM_DIR)

    def parseIor(self, f_mode: str, f_is_ssd: bool) -> None:
        """Parse IOR benchmark outputs and generate reports.

        Args:
            f_mode: Execution mode scale.
            f_is_ssd: Whether SSD storage path is used.
        """
        from lsmiotool.lib import output

        target_dir = self._getTargetDir("ior", f_mode, f_is_ssd)
        log.Console.debug(f"Parsing IOR logs from: {target_dir}")
        agg = output.IorAggOutput(target_dir)
        agg.generateReports(target_dir)

    def parseLsmio(self, f_mode: str, f_is_ssd: bool) -> None:
        """Parse LSMIO benchmark outputs and generate reports.

        Args:
            f_mode: Execution mode scale.
            f_is_ssd: Whether SSD storage path is used.
        """
        from lsmiotool.lib import output

        target_dir = self._getTargetDir("lsmio", f_mode, f_is_ssd)
        log.Console.debug(f"Parsing LSMIO logs from: {target_dir}")
        agg = output.LsmioAggOutput(target_dir, f_scale=f_mode)
        agg.generateReports(target_dir)

    def parseLmp(self, f_mode: str, f_is_ssd: bool) -> None:
        """Parse LMP benchmark outputs and generate reports.

        Args:
            f_mode: Execution mode scale.
            f_is_ssd: Whether SSD storage path is used.
        """
        from lsmiotool.lib import output

        target_dir = self._getTargetDir("lmp", f_mode, f_is_ssd)
        log.Console.debug(f"Parsing LMP logs from: {target_dir}")
        agg = output.LmpAggOutput(target_dir)
        agg.generateReports(target_dir)

    def run(self) -> None:
        """Execute parsing dispatch."""
        if self.m_command == "ior":
            self.parseIor(self.m_mode, self.m_is_ssd)
        elif self.m_command == "lsmio":
            self.parseLsmio(self.m_mode, self.m_is_ssd)
        elif self.m_command == "lmp":
            self.parseLmp(self.m_mode, self.m_is_ssd)


class ParseMain(BaseMain):
    """Parse command execution mode for modern benchmark run artifacts."""

    m_request: Optional[Any]
    m_init_error: Optional[Exception]

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

    def run(self) -> int:
        """Execute benchmark run parsing, metric extraction, and report generation.

        Returns:
            0: Success (reports generated, summary printed to stdout).
            1: General runtime / configuration error.
            2: ParseCliParseError (invalid CLI syntax/arguments).
            3: RunRootResolutionError (missing manifest.json or unreadable run directory).
            4: RunRootResolutionError (failed state reconciliation or non-SUCCEEDED overall state).
            5: ExtractionError (malformed log files or missing required metrics).
        """
        from lsmiotool.lib.cli import ParseCliParseError
        from lsmiotool.lib.evidence import EvidenceError
        from lsmiotool.lib.runparse import (
            ConsoleSummaryFormatter,
            ExtractionError,
            RunRootResolutionError,
            RunRootResolver,
            extractRun,
            generateReports,
        )
        from lsmiotool.lib.state import StateError

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
            # 1. Target resolution
            f_resolved_run = RunRootResolver.resolveTarget(self.m_request.target)

            # 2. Metric extraction
            f_extracted_data = extractRun(f_resolved_run)

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

            return 0
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

    def __init__(
        self,
        *f_args: Any,
        f_request: Optional[Any] = None,
        f_folder: Optional[str] = None,
        f_op: Optional[str] = None,
        f_stripes: int = 4,
        f_blocksize: str = "1M",
        f_output_dir: Optional[str] = None,
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

            if folder is None or op is None:
                log.Console.error("Compare nodes: Missing required folder or operation.")
                sys.exit(1)

            try:
                req = CompareNodesRequest(
                    f_folder=folder,
                    f_op=op,
                    f_stripes=stripes,
                    f_blocksize=bs,
                    f_output_dir=out_dir,
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
        """Scan benchmark subdirectories, extract data series, and generate comparison plot."""
        from lsmiotool.lib import data, plot

        target_dir = self.resolveDirectory(self.m_folder)
        if not os.path.isdir(target_dir):
            log.Console.error(f"Directory not found: {target_dir}")
            sys.exit(1)

        entries = sorted(os.listdir(target_dir))
        plot_data_list: List[plot.PlotData] = []
        is_read = self.m_op == "read"

        for entry in entries:
            child_path = os.path.join(target_dir, entry)
            if os.path.isdir(child_path):
                report_file = os.path.join(child_path, "lsm-report.csv")
                if os.path.isfile(report_file):
                    summary_data = data.LsmioSummaryData(report_file)
                    x_series, y_series = summary_data.timeSeries(
                        is_read, self.m_stripes, self.m_bs
                    )
                    if x_series and y_series:
                        plot_data_list.append(plot.PlotData(entry, x_series, y_series))

        if not plot_data_list:
            log.Console.warning(
                f"No benchmark data found in subdirectories of {target_dir} for {self.m_op}, stripes={self.m_stripes}, bs={self.m_bs}"
            )
            return 0

        base_name = os.path.basename(target_dir.rstrip(os.sep))
        title = f"Comparison: {base_name} ({self.m_op.upper()} - {self.m_stripes} stripes - {self.m_bs})"
        meta_data = plot.PlotMetaData(title, "# of Nodes", "Max BW in MB")

        # Output directory resolution (INV-ARCH-9: fixes legacy hardcoded os.getcwd())
        out_dir = (
            self.resolveDirectory(self.m_output_dir)
            if self.m_output_dir
            else os.getcwd()
        )
        os.makedirs(out_dir, exist_ok=True)
        output_filename = os.path.join(
            out_dir,
            f"compare-{base_name}-{self.m_op}-{self.m_stripes}-{self.m_bs}.png",
        )
        bar_plot = plot.MultiBarPlot(meta_data, *plot_data_list)
        bar_plot.plot(output_filename)
        log.Console.info(f"Comparison plot saved to {output_filename}")
        return 0


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

        Args:
            f_child_path: Path to variant directory.

        Returns:
            True if lsm-report.csv exists or was successfully generated, False otherwise.
        """
        report_file = os.path.join(f_child_path, "lsm-report.csv")
        if os.path.isfile(report_file):
            return True

        try:
            from lsmiotool.lib.output import LsmioAggOutput, MissingDataError

            try:
                agg = LsmioAggOutput(f_child_path, f_scale="baseline")
            except TypeError:
                agg = LsmioAggOutput(f_input=f_child_path, f_scale="baseline")
            try:
                agg.generateReports(f_out_dir=f_child_path)
            except TypeError:
                agg.generateReports(f_child_path)
            return os.path.isfile(report_file)
        except (MissingDataError, OSError, IOError, ValueError, KeyError) as err:
            log.Console.warning(f"Failed to generate report for {f_child_path}: {err}")
            return False

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
        filename = f"compare-archive-{archive_basename}-{op.lower()}-{stripes}-{blocksize.upper()}.png"
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, filename)

        title = f"LSMIO Variant Comparison ({op.capitalize()}, Stripes={stripes}, BS={blocksize.upper()})"
        meta_data = plot.PlotMetaData(title, "Variant", "Max Bandwidth (MB/s)")

        bar_plot = plot.MultiBarPlot(meta_data, *series)
        bar_plot.plot(out_path)
        log.Console.info(f"Comparison plot saved to {out_path}")
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
    """Archive command dispatcher executing move-on-archive for benchmark outputs."""

    m_request: Any
    m_runtime_layout: Optional[Any]
    m_source_dir: Optional[str]
    m_dest_dir: Optional[str]

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

    def run(self) -> int:
        """Dispatches archive operation, resolves source and destination, and logs result."""
        from lsmiotool.lib.archive import ArchiveEngine, ArchiveError

        try:
            # 1. Derive arm_id matching bmtool archive semantics
            f_arm_id = ArchiveEngine.resolveArmId(
                f_setup="NATIVE-M",
                f_variant=self.m_request.variant,
            )

            # 2. Resolve source directory
            f_source_dir = self.m_source_dir
            if f_source_dir is None:
                if "LSM_DIR_OBASE" in os.environ and os.path.exists(
                    os.environ["LSM_DIR_OBASE"]
                ):
                    f_source_dir = os.environ["LSM_DIR_OBASE"]
                elif os.path.isdir(os.path.join(os.getcwd(), "outputs")):
                    f_source_dir = os.path.join(os.getcwd(), "outputs")
                else:
                    f_bm_root = None
                    if self.m_runtime_layout is not None:
                        f_bm_root = getattr(
                            self.m_runtime_layout, "benchmark_root", None
                        ) or getattr(
                            self.m_runtime_layout, "benchmarkRoot", None
                        )
                    if f_bm_root and os.path.isdir(
                        os.path.join(f_bm_root, "outputs")
                    ):
                        f_source_dir = os.path.join(f_bm_root, "outputs")
                    else:
                        f_source_dir = os.path.join(os.getcwd(), "outputs")

            # 3. Resolve destination root
            f_dest_root = self.m_request.dest or self.m_dest_dir
            if f_dest_root is None:
                if "BM_ARCHIVE_DEST" in os.environ:
                    f_dest_root = os.environ["BM_ARCHIVE_DEST"]
                else:
                    f_bm_root = None
                    if self.m_runtime_layout is not None:
                        f_bm_root = getattr(
                            self.m_runtime_layout, "benchmark_root", None
                        ) or getattr(
                            self.m_runtime_layout, "benchmarkRoot", None
                        )
                    if f_bm_root:
                        f_dest_root = os.path.join(f_bm_root, "lsmio-archive")
                    else:
                        f_dest_root = os.path.join(os.getcwd(), "lsmio-archive")

            # 4. Perform atomic move-on-archive and clean recreation
            f_target_dir = ArchiveEngine.executeArchive(
                f_source_dir=f_source_dir,
                f_dest_root=f_dest_root,
                f_arm_id=f_arm_id,
            )
            log.Console.info(f"Archived {f_source_dir} -> {f_target_dir}")
            return 0
        except ArchiveError as f_err:
            sys.stderr.write(f"Archive error: {f_err}\n")
            log.Console.error(f"Archive error: {f_err}")
            return 1
        except Exception as f_err:
            sys.stderr.write(f"Unexpected archive error: {f_err}\n")
            log.Console.error(f"Unexpected archive error: {f_err}")
            return 1


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
