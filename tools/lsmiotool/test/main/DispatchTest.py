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

import io
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
from typing import Any
import unittest
from unittest.mock import MagicMock, patch

from lsmiotool.lib.cli import (
    LSMIOTOOL_HELP,
    RUN_HELP_TEXT,
    PackageValidationError,
    ParseRequest,
    RunCliParseError,
    RunCliParser,
    SourcePackageValidator,
    parseRunArguments,
)
from lsmiotool.lib.main import (
    CompareMain,
    HpcEnvMain,
    LatexMain,
    ParseLegacyMain,
    ParseMain,
    RunMain,
    ShellMain,
    TestMain,
)
from lsmiotool.lib.resources import (
    ExecutionMode,
    ResourceLocator,
    RuntimeLayout,
)
from lsmiotool.lib.run import (
    RunOrchestrator,
    RunPlan,
    RunPlanner,
    RunReporter,
    RunRequest,
    ScalePoint,
    ScheduledPointResources,
    SignalCoordinator,
)
from lsmiotool.lib.state import (
    OverallRunState,
    PointRunState,
    RunStateView,
)
from lsmiotool.lib.version import getVersion


class DispatchTest(unittest.TestCase):
    """Unit tests for lazy legacy dispatch, entry point, SourcePackageValidator, and RunMain."""

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.mkdtemp(prefix="lsmiotool-dispatch-test-")
        self.m_executable = Path(__file__).resolve().parents[2] / "lsmiotool"
        self.m_package_root = Path(__file__).resolve().parents[2]
        self.m_original_cwd = os.getcwd()

    def tearDown(self) -> None:
        os.chdir(self.m_original_cwd)
        shutil.rmtree(self.m_temp_dir, ignore_errors=True)

    def testSourcePackageConsumerValidationAndNoFallback(self) -> None:
        """Asserts SourcePackageValidator validates package root and files using lstat, rejecting symlinks and missing files without fallback."""
        # 1. Valid package root
        f_norm_root = SourcePackageValidator.validate(self.m_package_root)
        self.assertEqual(f_norm_root, os.path.normpath(str(self.m_package_root)))

        # 2. Non-existent package root
        f_missing_root = os.path.join(self.m_temp_dir, "nonexistent_pkg")
        with self.assertRaises(PackageValidationError):
            SourcePackageValidator.validate(f_missing_root)

        # 3. Symlink to package root
        f_real_dir = os.path.join(self.m_temp_dir, "real_pkg")
        os.makedirs(os.path.join(f_real_dir, "lib"), exist_ok=True)
        for f_name in ("__init__.py", "cli.py", "main.py", "version.py"):
            with open(
                os.path.join(f_real_dir, "lib", f_name), "w", encoding="utf-8"
            ) as f_f:
                f_f.write("# dummy\n")
        f_sym_root = os.path.join(self.m_temp_dir, "sym_pkg")
        os.symlink(f_real_dir, f_sym_root)
        with self.assertRaises(PackageValidationError):
            SourcePackageValidator.validate(f_sym_root)

        # 4. File instead of directory as package root
        f_file_root = os.path.join(self.m_temp_dir, "file_pkg")
        with open(f_file_root, "w", encoding="utf-8") as f_f:
            f_f.write("not a directory\n")
        with self.assertRaises(PackageValidationError):
            SourcePackageValidator.validate(f_file_root)

        # 5. Missing required core file
        f_incomplete_pkg = os.path.join(self.m_temp_dir, "incomplete_pkg")
        os.makedirs(os.path.join(f_incomplete_pkg, "lib"), exist_ok=True)
        with open(
            os.path.join(f_incomplete_pkg, "lib", "cli.py"), "w", encoding="utf-8"
        ) as f_f:
            f_f.write("# dummy\n")
        # Missing main.py, version.py, __init__.py
        with self.assertRaises(PackageValidationError):
            SourcePackageValidator.validate(f_incomplete_pkg)

        # 6. Symlink required core file
        f_symlink_file_pkg = os.path.join(self.m_temp_dir, "symfile_pkg")
        os.makedirs(os.path.join(f_symlink_file_pkg, "lib"), exist_ok=True)
        for f_name in ("__init__.py", "cli.py", "version.py"):
            with open(
                os.path.join(f_symlink_file_pkg, "lib", f_name), "w", encoding="utf-8"
            ) as f_f:
                f_f.write("# dummy\n")
        f_target_main = os.path.join(self.m_temp_dir, "real_main.py")
        with open(f_target_main, "w", encoding="utf-8") as f_f:
            f_f.write("# real main\n")
        os.symlink(f_target_main, os.path.join(f_symlink_file_pkg, "lib", "main.py"))
        with self.assertRaises(PackageValidationError):
            SourcePackageValidator.validate(f_symlink_file_pkg)

        # 7. Directory instead of regular file for a required file
        f_dir_file_pkg = os.path.join(self.m_temp_dir, "dirfile_pkg")
        os.makedirs(os.path.join(f_dir_file_pkg, "lib", "main.py"), exist_ok=True)
        for f_name in ("__init__.py", "cli.py", "version.py"):
            with open(
                os.path.join(f_dir_file_pkg, "lib", f_name), "w", encoding="utf-8"
            ) as f_f:
                f_f.write("# dummy\n")
        with self.assertRaises(PackageValidationError):
            SourcePackageValidator.validate(f_dir_file_pkg)

        # 8. Unreadable required file
        with patch("os.access", return_value=False):
            with self.assertRaises(PackageValidationError):
                SourcePackageValidator.validate(self.m_package_root)

        # 9. Invalid argument types
        with self.assertRaises(PackageValidationError):
            SourcePackageValidator.validate(None)  # type: ignore
        with self.assertRaises(PackageValidationError):
            SourcePackageValidator.validate(12345)  # type: ignore
        with self.assertRaises(PackageValidationError):
            SourcePackageValidator.validate("")

        # 10. Prohibits directory searching and no fallback to cwd
        f_decoy_cwd = os.path.join(self.m_temp_dir, "decoy_cwd")
        os.makedirs(os.path.join(f_decoy_cwd, "lib"), exist_ok=True)
        for f_name in ("__init__.py", "cli.py", "main.py", "version.py"):
            with open(
                os.path.join(f_decoy_cwd, "lib", f_name), "w", encoding="utf-8"
            ) as f_f:
                f_f.write("# dummy\n")
        os.chdir(f_decoy_cwd)

        # Explicit nonexistent path must fail immediately without falling back to cwd
        with self.assertRaises(PackageValidationError):
            SourcePackageValidator.validate(
                os.path.join(self.m_temp_dir, "nonexistent")
            )

    def testEveryLegacyCommandAndGlobalSsdCompatibility(self) -> None:
        """Asserts all legacy commands maintain argument compatibility with and without global SSD."""
        f_exec_str = str(self.m_executable)

        # 1. compare command
        with patch.object(
            sys, "argv", [f_exec_str, "compare", "nodes", "bench_folder", "read"]
        ):
            with patch.object(CompareMain, "run", return_value=0) as mock_run:
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 0)
                mock_run.assert_called_once()

        # compare variants command
        with patch.object(
            sys,
            "argv",
            [f_exec_str, "compare", "variants", "archive_folder", "both"],
        ):
            with patch.object(CompareMain, "run", return_value=0) as mock_run:
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 0)
                mock_run.assert_called_once()

        # compare command with global --ssd
        with patch.object(
            sys,
            "argv",
            [
                f_exec_str,
                "--ssd",
                "compare",
                "nodes",
                "bench_folder",
                "write",
                "16",
                "8M",
            ],
        ):
            with patch.object(CompareMain, "run", return_value=0) as mock_run:
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 0)
                mock_run.assert_called_once()

        # compare command with global -s
        with patch.object(
            sys, "argv", [f_exec_str, "-s", "compare", "nodes", "bench_folder", "read"]
        ):
            with patch.object(CompareMain, "run", return_value=0) as mock_run:
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 0)
                mock_run.assert_called_once()

        # 2. latex command
        with patch.object(sys, "argv", [f_exec_str, "latex", "viking"]):
            with patch.object(LatexMain, "run", return_value=0) as mock_run:
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 0)
                mock_run.assert_called_once()

        # latex with global --ssd
        with patch.object(sys, "argv", [f_exec_str, "--ssd", "latex", "viking2"]):
            with patch.object(LatexMain, "run", return_value=0) as mock_run:
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 0)
                mock_run.assert_called_once()

        # 3. load-modules command
        with patch.object(sys, "argv", [f_exec_str, "load-modules"]):
            with patch.object(HpcEnvMain, "run", return_value=0) as mock_run:
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 0)
                mock_run.assert_called_once()

        # load-modules with global --ssd
        with patch.object(sys, "argv", [f_exec_str, "--ssd", "load-modules"]):
            with patch.object(HpcEnvMain, "run", return_value=0) as mock_run:
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 0)
                mock_run.assert_called_once()

        # 4. shell command
        with patch.object(sys, "argv", [f_exec_str, "shell"]):
            with patch.object(ShellMain, "run", return_value=0) as mock_run:
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 0)
                mock_run.assert_called_once()

        # shell with global -s
        with patch.object(sys, "argv", [f_exec_str, "-s", "shell"]):
            with patch.object(ShellMain, "run", return_value=0) as mock_run:
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 0)
                mock_run.assert_called_once()

        # 5. test command
        with patch.object(sys, "argv", [f_exec_str, "test"]):
            with patch.object(TestMain, "run", return_value=0) as mock_run:
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 0)
                mock_run.assert_called_once()

        # 6. Arity and error checks
        # compare with missing submode
        with patch.object(sys, "argv", [f_exec_str, "compare"]):
            with patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 2)
                self.assertIn("Missing required submode", mock_stderr.getvalue())

        # compare with bare folder fallback prohibited
        with patch.object(sys, "argv", [f_exec_str, "compare", "bench_folder"]):
            with patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 2)
                self.assertIn("Invalid submode", mock_stderr.getvalue())

        # compare with prohibited scaling alias
        with patch.object(
            sys, "argv", [f_exec_str, "compare", "scaling", "bench_folder", "read"]
        ):
            with patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 2)
                self.assertIn("Invalid submode", mock_stderr.getvalue())

        # compare nodes with missing operation
        with patch.object(
            sys, "argv", [f_exec_str, "compare", "nodes", "bench_folder"]
        ):
            with patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 2)
                self.assertIn(
                    "Missing required positional argument: <read|write>",
                    mock_stderr.getvalue(),
                )

        # compare-archive is excised and falls through to unknown command (exit code 1)
        with patch.object(
            sys, "argv", [f_exec_str, "compare-archive", "archive_folder"]
        ):
            with patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 1)
                self.assertIn("Unknown command:", mock_stderr.getvalue())

        # compare with --help exits with code 0
        with patch.object(sys, "argv", [f_exec_str, "compare", "--help"]):
            with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 0)
                self.assertIn("Usage:", mock_stdout.getvalue())
                self.assertIn("compare <nodes|variants>", mock_stdout.getvalue())

        # latex with no arguments
        with patch.object(sys, "argv", [f_exec_str, "latex"]):
            with self.assertRaises(SystemExit) as ctx:
                runpy.run_path(f_exec_str, run_name="__main__")
            self.assertEqual(ctx.exception.code, 1)

        # parseLegacy with insufficient arguments
        with patch.object(sys, "argv", [f_exec_str, "parseLegacy", "ior"]):
            with patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 1)
                self.assertIn(
                    "ParseLegacy: Needs two arguments:", mock_stderr.getvalue()
                )

        # parse command with no additional arguments
        with patch.object(sys, "argv", [f_exec_str, "parse"]):
            with patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 2)
                self.assertIn(
                    "Missing required positional argument: <target>",
                    mock_stderr.getvalue(),
                )

        # parse command with unexpected extra positional argument
        with patch.object(sys, "argv", [f_exec_str, "parse", "ior", "local"]):
            with patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 2)
                self.assertIn(
                    "Unexpected extra positional argument: 'local'",
                    mock_stderr.getvalue(),
                )

        # empty command
        with patch.object(sys, "argv", [f_exec_str]):
            with self.assertRaises(SystemExit) as ctx:
                runpy.run_path(f_exec_str, run_name="__main__")
            self.assertEqual(ctx.exception.code, 1)

        # unknown command
        with patch.object(sys, "argv", [f_exec_str, "unknown_cmd"]):
            with self.assertRaises(SystemExit) as ctx:
                runpy.run_path(f_exec_str, run_name="__main__")
            self.assertEqual(ctx.exception.code, 1)

        # unknown option
        with patch.object(sys, "argv", [f_exec_str, "--invalid-flag", "shell"]):
            with self.assertRaises(SystemExit) as ctx:
                runpy.run_path(f_exec_str, run_name="__main__")
            self.assertEqual(ctx.exception.code, 1)

    def testParseLegacyReceivesSsd(self) -> None:
        """Asserts parseLegacy command receives the SSD boolean flag."""
        f_exec_str = str(self.m_executable)

        # 1. parseLegacy without SSD
        with patch.object(sys, "argv", [f_exec_str, "parseLegacy", "ior", "local"]):
            with patch("lsmiotool.lib.main.ParseLegacyMain") as mock_parse_cls:
                mock_inst = MagicMock()
                mock_inst.run.return_value = 0
                mock_parse_cls.return_value = mock_inst
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 0)
                mock_parse_cls.assert_called_once_with("ior", "local", ssd=False)

        # 2. parseLegacy with global --ssd
        with patch.object(
            sys, "argv", [f_exec_str, "--ssd", "parseLegacy", "lsmio", "small"]
        ):
            with patch("lsmiotool.lib.main.ParseLegacyMain") as mock_parse_cls:
                mock_inst = MagicMock()
                mock_inst.run.return_value = 0
                mock_parse_cls.return_value = mock_inst
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 0)
                mock_parse_cls.assert_called_once_with("lsmio", "small", ssd=True)

        # 3. parseLegacy with global -s
        with patch.object(
            sys, "argv", [f_exec_str, "-s", "parseLegacy", "lmp", "bake"]
        ):
            with patch("lsmiotool.lib.main.ParseLegacyMain") as mock_parse_cls:
                mock_inst = MagicMock()
                mock_inst.run.return_value = 0
                mock_parse_cls.return_value = mock_inst
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 0)
                mock_parse_cls.assert_called_once_with("lmp", "bake", ssd=True)

    def testParseCommandDispatch(self) -> None:
        """Asserts parse command dispatches to ParseMain with parsed ParseRequest."""
        f_exec_str = str(self.m_executable)

        # 1. parse command with target
        with patch.object(sys, "argv", [f_exec_str, "parse", "ior"]):
            with patch("lsmiotool.lib.main.ParseMain") as mock_parse_cls:
                mock_inst = MagicMock()
                mock_inst.run.return_value = 0
                mock_parse_cls.return_value = mock_inst
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 0)
                mock_parse_cls.assert_called_once()
                call_kwargs = mock_parse_cls.call_args[1]
                req = call_kwargs.get("f_request")
                self.assertIsInstance(req, ParseRequest)
                self.assertEqual(req.target, "ior")
                self.assertEqual(req.format, "csv")
                self.assertIsNone(req.output_dir)

        # 2. parse command with options
        with patch.object(
            sys,
            "argv",
            [
                f_exec_str,
                "parse",
                "/path/to/manifest.json",
                "--output-dir",
                "/tmp/out",
                "--format",
                "json",
            ],
        ):
            with patch("lsmiotool.lib.main.ParseMain") as mock_parse_cls:
                mock_inst = MagicMock()
                mock_inst.run.return_value = 0
                mock_parse_cls.return_value = mock_inst
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 0)
                mock_parse_cls.assert_called_once()
                call_kwargs = mock_parse_cls.call_args[1]
                req = call_kwargs.get("f_request")
                self.assertIsInstance(req, ParseRequest)
                self.assertEqual(req.target, "/path/to/manifest.json")
                self.assertEqual(req.format, "json")
                self.assertEqual(req.output_dir, "/tmp/out")

    def testRunLazyWithoutOptionalImportsOrOsGetlogin(self) -> None:
        """Asserts run command does not eagerly import heavy/optional modules (Matplotlib, NumPy) or call os.getlogin."""
        f_repo_tools = str(self.m_package_root.parent)
        f_script = """
import sys
import os
from unittest.mock import patch, MagicMock

# Patch os.getlogin to verify it is never called
with patch("os.getlogin", side_effect=AssertionError("os.getlogin was called")):
    from lsmiotool.lib.main import RunMain
    from lsmiotool.lib.run import RunRequest

    mock_orch = MagicMock()
    mock_orch.execute.return_value = MagicMock()
    mock_orch.exitCode = 0

    req = RunRequest(f_target="ior", f_scale="local", f_ssd=False, f_setup=None)
    run_main = RunMain(f_request=req, f_orchestrator_factory=lambda **kw: mock_orch)
    code = run_main.run()
    assert code == 0, f"Expected 0, got {code}"

    # Assert optional/heavy modules are NOT in sys.modules
    for mod_name in (
        "numpy",
        "matplotlib",
        "matplotlib.pyplot",
        "lsmiotool.lib.plot",
        "lsmiotool.lib.dirs",
        "lsmiotool.lib.jobs",
        "lsmiotool.lib.env",
    ):
        assert mod_name not in sys.modules, f"Module '{mod_name}' was eagerly imported into sys.modules"

print("LAZY_IMPORT_OK")
"""
        f_env = dict(os.environ)
        f_env["PYTHONPATH"] = f_repo_tools

        f_proc = subprocess.run(
            [sys.executable, "-c", f_script],
            capture_output=True,
            text=True,
            env=f_env,
        )
        self.assertEqual(
            f_proc.returncode,
            0,
            f"Process failed with stderr: {f_proc.stderr}\nstdout: {f_proc.stdout}",
        )
        self.assertIn("LAZY_IMPORT_OK", f_proc.stdout)

    def testRunMainRequestAndStatusWithInjectedWorkerValidator(self) -> None:
        """Tests RunMain delegating to RunOrchestrator with injected validator and returning exact exit status."""
        # 1. Test instantiation with RunRequest
        f_req = RunRequest(f_target="ior", f_scale="local", f_ssd=False, f_setup="BASE")
        f_mock_validator = MagicMock()
        f_mock_orch = MagicMock()
        f_mock_orch.execute.return_value = MagicMock()
        f_mock_orch.exitCode = 0

        f_factory_calls = []

        def mock_factory(**f_kwargs):
            f_factory_calls.append(f_kwargs)
            return f_mock_orch

        f_run_main = RunMain(
            f_request=f_req,
            f_orchestrator_factory=mock_factory,
            f_worker_validator=f_mock_validator,
        )
        self.assertEqual(f_run_main.request, f_req)
        self.assertEqual(f_run_main.workerValidator, f_mock_validator)

        f_status = f_run_main.run()
        self.assertEqual(f_status, 0)
        self.assertEqual(len(f_factory_calls), 1)
        self.assertEqual(f_factory_calls[0].get("f_worker_validator"), f_mock_validator)
        f_mock_orch.execute.assert_called_once_with(
            f_request=f_req, f_site=None, f_runtime_layout=None
        )

        # 2. Test instantiation with positional arguments
        f_run_main_pos = RunMain(
            "lsmio",
            "small",
            ssd=True,
            setup="NATIVE-M",
            f_orchestrator_factory=mock_factory,
            f_worker_validator=f_mock_validator,
        )
        self.assertEqual(f_run_main_pos.request.target, "lsmio")
        self.assertEqual(f_run_main_pos.request.scale, "small")
        self.assertTrue(f_run_main_pos.request.ssd)
        self.assertEqual(f_run_main_pos.request.setup, "NATIVE-M")

        # 3. Test non-zero, 130, and 143 statuses
        for f_expected_status in (1, 130, 143):
            f_mock_orch_status = MagicMock()
            f_mock_orch_status.execute.return_value = MagicMock()
            f_mock_orch_status.exitCode = f_expected_status

            f_main_status = RunMain(
                f_request=f_req,
                f_orchestrator_factory=lambda **kw: f_mock_orch_status,
                f_worker_validator=f_mock_validator,
            )
            f_actual_status = f_main_status.run()
            self.assertEqual(f_actual_status, f_expected_status)

    def testSourceRunPassesExplicitRuntimeLayout(self) -> None:
        """Asserts entry point 'run' command constructs and passes the explicit source RuntimeLayout with checked-in worker."""
        f_exec_str = str(self.m_executable)
        f_captured_init_kwargs = {}
        f_orig_run_main_init = RunMain.__init__

        def spy_run_main_init(self_obj, *args, **kwargs):
            f_captured_init_kwargs.update(kwargs)
            f_orig_run_main_init(self_obj, *args, **kwargs)

        # 1. Standard invocation
        with patch.object(sys, "argv", [f_exec_str, "run", "ior", "local"]):
            with patch.object(
                RunMain, "__init__", side_effect=spy_run_main_init, autospec=True
            ):
                with patch.object(RunMain, "run", return_value=0):
                    with self.assertRaises(SystemExit) as ctx:
                        runpy.run_path(f_exec_str, run_name="__main__")
                    self.assertEqual(ctx.exception.code, 0)

        f_layout = f_captured_init_kwargs.get("f_runtime_layout")
        self.assertIsNotNone(f_layout)
        self.assertIsInstance(f_layout, RuntimeLayout)
        self.assertEqual(f_layout.execution_mode, ExecutionMode.SOURCE)
        self.assertTrue(f_layout.is_source)
        self.assertFalse(f_layout.is_installed)
        self.assertEqual(f_layout.package_root, str(self.m_package_root))
        self.assertEqual(
            f_layout.profile_file,
            str(self.m_package_root / "etc" / "environments.json"),
        )
        self.assertEqual(
            f_layout.asset_root,
            str(self.m_package_root.parent / "bmtool" / "lmp-reaxff"),
        )
        self.assertEqual(
            f_layout.worker_executable, str(self.m_package_root / "lsmiotool-worker")
        )
        self.assertEqual(
            f_layout.version_file, str(self.m_package_root.parent.parent / "VERSION")
        )

        # 2. Invocation from unrelated cwd with decoy files
        f_decoy_dir = os.path.join(self.m_temp_dir, "decoy_run_cwd")
        os.makedirs(os.path.join(f_decoy_dir, "tools", "lsmiotool"), exist_ok=True)
        with open(os.path.join(f_decoy_dir, "VERSION"), "w", encoding="utf-8") as f_f:
            f_f.write("decoy\n")

        f_orig_cwd = os.getcwd()
        try:
            os.chdir(f_decoy_dir)
            f_captured_init_kwargs.clear()
            with patch.object(sys, "argv", [f_exec_str, "run", "lmp", "bake"]):
                with patch.object(
                    RunMain, "__init__", side_effect=spy_run_main_init, autospec=True
                ):
                    with patch.object(RunMain, "run", return_value=0):
                        with self.assertRaises(SystemExit) as ctx:
                            runpy.run_path(f_exec_str, run_name="__main__")
                        self.assertEqual(ctx.exception.code, 0)

            f_layout_decoy = f_captured_init_kwargs.get("f_runtime_layout")
            self.assertIsNotNone(f_layout_decoy)
            self.assertEqual(f_layout_decoy.package_root, str(self.m_package_root))
            self.assertEqual(
                f_layout_decoy.worker_executable,
                str(self.m_package_root / "lsmiotool-worker"),
            )
            self.assertNotIn("decoy", f_layout_decoy.package_root)
            self.assertNotIn("decoy", f_layout_decoy.worker_executable)
        finally:
            os.chdir(f_orig_cwd)

    def testHelpVersionZero(self) -> None:
        """Tests --help and --version return exit code 0 and output valid text / version from Chunk 026."""
        f_exec_str = str(self.m_executable)
        f_expected_version = getVersion()

        # 1. --help
        with patch.object(sys, "argv", [f_exec_str, "--help"]):
            with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 0)
                f_out = mock_stdout.getvalue()
                self.assertIn("How to run", f_out)
                self.assertIn("common cmds:", f_out)
                self.assertIn("run <ior|lsmio|lmp> <local|bake|small|large>", f_out)

        # 2. -h
        with patch.object(sys, "argv", [f_exec_str, "-h"]):
            with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 0)
                self.assertIn("How to run", mock_stdout.getvalue())

        # 3. --version
        with patch.object(sys, "argv", [f_exec_str, "--version"]):
            with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 0)
                f_out = mock_stdout.getvalue()
                self.assertIn(f_expected_version, f_out)
                self.assertIn("version:", f_out)

        # 4. -v
        with patch.object(sys, "argv", [f_exec_str, "-v"]):
            with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 0)
                self.assertIn(f_expected_version, mock_stdout.getvalue())

    def testValidationAndSignalStatusesAtExecutable(self) -> None:
        """Tests execution paths propagating return codes (0, 1, 130, 143) to sys.exit()."""
        f_exec_str = str(self.m_executable)

        # 1. Run command propagating 0, 1, 130, 143
        for f_code in (0, 1, 130, 143):
            with patch.object(sys, "argv", [f_exec_str, "run", "ior", "local"]):
                with patch.object(RunMain, "run", return_value=f_code) as mock_run:
                    with self.assertRaises(SystemExit) as ctx:
                        runpy.run_path(f_exec_str, run_name="__main__")
                    self.assertEqual(ctx.exception.code, f_code)
                    mock_run.assert_called_once()

        # 2. Run command syntax error: --setup=value rejected
        with patch.object(
            sys, "argv", [f_exec_str, "run", "ior", "local", "--setup=BASE"]
        ):
            with patch("sys.stderr", new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 1)

        # 3. Run command syntax error: unknown option
        with patch.object(
            sys, "argv", [f_exec_str, "run", "ior", "local", "--unknown"]
        ):
            with patch("sys.stderr", new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 1)

        # 4. Package validation failure triggers exit(1)
        with patch.object(
            SourcePackageValidator,
            "validate",
            side_effect=PackageValidationError("Corrupt package"),
        ):
            with patch.object(sys, "argv", [f_exec_str, "test"]):
                with patch("sys.stderr", new_callable=io.StringIO):
                    with self.assertRaises(SystemExit) as ctx:
                        runpy.run_path(f_exec_str, run_name="__main__")
                    self.assertEqual(ctx.exception.code, 1)

    def testSourceAndInstalledRunDoNotCallDetectWithUserHome(self) -> None:
        """Asserts source and installed RunMain dispatch does not pass user/home to EnvironmentResolver.detect()."""
        from lsmiotool.lib.site import EnvironmentResolver, SiteProfile

        f_exec_str = str(self.m_executable)

        mock_profile = MagicMock(spec=SiteProfile)

        f_detect_calls = []
        f_resolve_calls = []

        def spy_detect(*args: Any, **kwargs: Any) -> str:
            f_detect_calls.append((args, kwargs))
            return "VIKING"

        def spy_resolve(*args: Any, **kwargs: Any) -> SiteProfile:
            f_resolve_calls.append((args, kwargs))
            return mock_profile

        # 1. Source layout through RunMain
        source_layout = ResourceLocator.forSource(f_exec_str)
        run_main_src = RunMain(
            "ior",
            "local",
            f_runtime_layout=source_layout,
        )
        f_detect_calls.clear()
        f_resolve_calls.clear()

        with patch.object(EnvironmentResolver, "detect", side_effect=spy_detect):
            with patch.object(
                EnvironmentResolver, "resolveProfile", side_effect=spy_resolve
            ):
                with patch(
                    "lsmiotool.lib.run.RunPlanner.createPlan"
                ) as mock_create_plan:
                    mock_create_plan.side_effect = Exception(
                        "Stop after preflight profile resolution"
                    )
                    exit_code = run_main_src.run()
                    self.assertEqual(exit_code, 1)

        self.assertEqual(len(f_detect_calls), 1)
        _, det_kw = f_detect_calls[0]
        self.assertNotIn("f_user", det_kw)
        self.assertNotIn("f_home", det_kw)
        self.assertNotIn("user", det_kw)
        self.assertNotIn("home", det_kw)

        self.assertEqual(len(f_resolve_calls), 1)
        res_args, res_kw = f_resolve_calls[0]
        self.assertEqual(res_args[0], "VIKING")
        self.assertEqual(res_kw.get("f_env_file"), source_layout.profile_file)

        # 2. Installed layout through RunMain
        installed_layout = RuntimeLayout(
            f_execution_mode=ExecutionMode.INSTALLED,
            f_package_root="/usr/local/share/lsmio/python",
            f_profile_file="/usr/local/share/lsmio/etc/environments.json",
            f_asset_root="/usr/local/share/lsmio/lmp-reaxff",
            f_worker_executable="/usr/local/libexec/lsmio/lsmiotool-worker",
            f_version_file="/usr/local/share/lsmio/VERSION",
        )
        run_main_inst = RunMain(
            "ior",
            "local",
            f_runtime_layout=installed_layout,
        )
        f_detect_calls.clear()
        f_resolve_calls.clear()

        with patch.object(EnvironmentResolver, "detect", side_effect=spy_detect):
            with patch.object(
                EnvironmentResolver, "resolveProfile", side_effect=spy_resolve
            ):
                with patch(
                    "lsmiotool.lib.run.RunPlanner.createPlan"
                ) as mock_create_plan:
                    mock_create_plan.side_effect = Exception(
                        "Stop after preflight profile resolution"
                    )
                    exit_code = run_main_inst.run()
                    self.assertEqual(exit_code, 1)

        self.assertEqual(len(f_detect_calls), 1)
        _, det_kw = f_detect_calls[0]
        self.assertNotIn("f_user", det_kw)
        self.assertNotIn("f_home", det_kw)

        self.assertEqual(len(f_resolve_calls), 1)
        res_args, res_kw = f_resolve_calls[0]
        self.assertEqual(res_args[0], "VIKING")
        self.assertEqual(res_kw.get("f_env_file"), installed_layout.profile_file)

        # 3. Full entrypoint invocation with runpy to ensure no unexpected keyword argument exception
        f_detect_calls.clear()
        f_resolve_calls.clear()
        with patch.object(sys, "argv", [f_exec_str, "run", "ior", "local"]):
            with patch.object(EnvironmentResolver, "detect", side_effect=spy_detect):
                with patch.object(
                    EnvironmentResolver, "resolveProfile", side_effect=spy_resolve
                ):
                    with patch(
                        "lsmiotool.lib.run.RunPlanner.createPlan"
                    ) as mock_create_plan:
                        mock_create_plan.side_effect = Exception(
                            "Stop after profile resolution"
                        )
                        with patch(
                            "sys.stderr", new_callable=io.StringIO
                        ) as mock_stderr:
                            with self.assertRaises(SystemExit) as ctx:
                                runpy.run_path(f_exec_str, run_name="__main__")
                            self.assertEqual(ctx.exception.code, 1)
                            err_out = mock_stderr.getvalue()
                            self.assertNotIn("unexpected keyword argument", err_out)

        self.assertEqual(len(f_detect_calls), 1)
        _, det_kw = f_detect_calls[0]
        self.assertNotIn("f_user", det_kw)
        self.assertNotIn("f_home", det_kw)

    def _readReadmeContent(self) -> str:
        """Helper to read README.md content from repository root."""
        f_readme_path = Path(__file__).resolve().parents[4] / "README.md"
        self.assertTrue(
            f_readme_path.is_file(), f"README.md not found at {f_readme_path}"
        )
        with open(f_readme_path, "r", encoding="utf-8") as f_f:
            return f_f.read()

    def testReadmeRegistriesMatricesResourcesMailAndWalltimeMatchRuntime(self) -> None:
        """Asserts documented combinations, order, benchmarks, scales, and scheduler directives match runtime implementations."""
        f_readme = self._readReadmeContent()

        # 1. Benchmarks: ior, lsmio, lmp
        for f_bm in RunCliParser.VALID_BENCHMARKS:
            self.assertIn(f_bm, f_readme)

        # 2. Scales: local, bake, small, large
        for f_scale in RunCliParser.VALID_SCALES:
            self.assertIn(f_scale, f_readme)

        # 3. 6 combinations in fixed sequence
        f_expected_combinations = [
            "(16, 8M)",
            "(16, 1M)",
            "(16, 64K)",
            "(4, 8M)",
            "(4, 1M)",
            "(4, 64K)",
        ]
        f_last_pos = -1
        for f_combo in f_expected_combinations:
            f_pos = f_readme.find(f_combo)
            self.assertNotEqual(
                f_pos, -1, f"Expected combination {f_combo} in README.md"
            )
            self.assertGreater(
                f_pos, f_last_pos, f"Combination {f_combo} appears out of order"
            )
            f_last_pos = f_pos

        # 4. Default setups
        self.assertIn("BASE", f_readme)
        self.assertIn("NATIVE-M", f_readme)
        self.assertIn("LSMIO", f_readme)

        # 5. PBS directives: walltime=06:00:00, -m abe, -q arm, select=, pmem=8G, pvmem=8G
        self.assertIn("#PBS -l walltime=06:00:00", f_readme)
        self.assertIn("#PBS -m abe", f_readme)
        self.assertIn("#PBS -q arm", f_readme)
        self.assertIn("#PBS -l select=", f_readme)
        self.assertIn("#PBS -l pmem=8G", f_readme)
        self.assertIn("#PBS -l pvmem=8G", f_readme)

        # 6. Slurm directives: --mail-type=END,FAIL, cyclic:cyclic, mem=8gb
        self.assertIn("#SBATCH --mail-type=END,FAIL", f_readme)
        self.assertIn("#SBATCH --time=", f_readme)
        self.assertIn("#SBATCH --distribution=cyclic:cyclic", f_readme)
        self.assertIn("#SBATCH --mem=8gb", f_readme)

        # 7. Configured certification state
        self.assertIn("configured", f_readme)

    def testReadmeSlurmDecimalOnlyHandleAndClusterQualifiedRejection(self) -> None:
        """Asserts documentation of decimal-only Slurm job IDs and rejection of cluster-qualified strings."""
        f_readme = self._readReadmeContent()

        # Slurm decimal regex and single parsed line
        self.assertIn("^[0-9]+$", f_readme)
        self.assertIn("sbatch --parsable", f_readme)

        # Cluster-qualified output rejection (e.g. 123;cluster)
        self.assertIn("123;cluster", f_readme)

        # Correlation token regex and 4-step dispatch evidence sequence
        self.assertIn("^lm-[0-9a-f]{24}$", f_readme)
        self.assertIn("submission_requested", f_readme)
        self.assertIn("submission_dispatched", f_readme)

        # Crash recovery window without resubmission
        self.assertIn("without blind resubmission", f_readme)

    def testReadmeRejectsSetupEquals(self) -> None:
        """Asserts documentation records --setup=value rejection."""
        f_readme = self._readReadmeContent()

        # README documents rejection of --setup=value and usage of --setup <name>
        self.assertIn("--setup=value", f_readme)
        self.assertIn("--setup <name>", f_readme)

        # CLI help text also documents rejection of --setup=value
        self.assertIn("--setup=value", RUN_HELP_TEXT)
        self.assertIn("--setup <name>", RUN_HELP_TEXT)

    def testReadmeLegacySsdAndParseLimit(self) -> None:
        """Asserts documentation records legacy global SSD and parse boundaries."""
        f_readme = self._readReadmeContent()

        # Legacy global --ssd acceptance
        self.assertIn("--ssd", f_readme)
        self.assertIn("lsmiotool --ssd run", f_readme)

        # Parse limitations (no auto-discovery, RunRootResolver)
        self.assertIn("RunRootResolver", f_readme)
        self.assertIn("lsmiotool parseLegacy", f_readme)

    def testReadmeInstallAndStateConstants(self) -> None:
        """Asserts documentation records installed layout paths and state precedence rules."""
        f_readme = self._readReadmeContent()

        # Installed layout paths
        self.assertIn("bin/lsmiotool", f_readme)
        self.assertIn("libexec/lsmio/lsmiotool-worker", f_readme)
        self.assertIn("share/lsmio/python", f_readme)
        self.assertIn("share/lsmio/lmp-reaxff", f_readme)

        # Source layout paths
        self.assertIn("tools/lsmiotool/lsmiotool", f_readme)
        self.assertIn("tools/lsmiotool/lsmiotool-worker", f_readme)
        self.assertIn("tools/bmtool/lmp-reaxff", f_readme)

        # State precedence & markers
        self.assertIn("WHOLE_RUN_SUCCEEDED", f_readme)
        self.assertIn("SUCCEEDED", f_readme)
        self.assertIn("INTERRUPTED", f_readme)
        self.assertIn("FAILED", f_readme)
        self.assertIn("CANCELLED", f_readme)
        self.assertIn("INDETERMINATE", f_readme)

        # Signal coordination
        self.assertIn("130", f_readme)
        self.assertIn("143", f_readme)

        # Atomic lmp large rejection
        self.assertIn("lmp large", f_readme)

    def testReadmeHelpRuntimeConstantsAndPathsAgree(self) -> None:
        """Chunk 021: Asserts README.md, CLI help constants, and runtime layout paths agree on benchmarks, scales, setups, syntax, and paths."""
        f_readme = self._readReadmeContent()

        # 1. Benchmarks, scales, and setups agreement
        for f_bm in ("ior", "lsmio", "lmp"):
            self.assertIn(f_bm, f_readme)
            self.assertIn(f_bm, RUN_HELP_TEXT)
            self.assertIn(f_bm, LSMIOTOOL_HELP)

        for f_scale in ("local", "bake", "small", "large"):
            self.assertIn(f_scale, f_readme)
            self.assertIn(f_scale, RUN_HELP_TEXT)
            self.assertIn(f_scale, LSMIOTOOL_HELP)

        for f_setup in ("BASE", "NATIVE-M", "LSMIO"):
            self.assertIn(f_setup, f_readme)
            self.assertIn(f_setup, RUN_HELP_TEXT)

        # 2. Syntax rules: --setup <name> accepted, --setup=value strictly rejected
        self.assertIn("--setup <name>", f_readme)
        self.assertIn("--setup=value", f_readme)
        self.assertIn("--setup <name>", RUN_HELP_TEXT)
        self.assertIn("--setup=value", RUN_HELP_TEXT)

        # 3. Global legacy --ssd / -s option
        self.assertIn("--ssd", f_readme)
        self.assertIn("-s", f_readme)
        self.assertIn("--ssd", RUN_HELP_TEXT)
        self.assertIn("-s", RUN_HELP_TEXT)
        self.assertIn("--ssd", LSMIOTOOL_HELP)

        # 4. Installed and Source layout paths agree with runtime specifications
        # Installed layout paths
        self.assertIn("bin/lsmiotool", f_readme)
        self.assertIn("libexec/lsmio/lsmiotool-worker", f_readme)
        self.assertIn("share/lsmio/python", f_readme)
        self.assertIn("share/lsmio/etc/environments.json", f_readme)
        self.assertIn("share/lsmio/VERSION", f_readme)
        self.assertIn("share/lsmio/lmp-reaxff", f_readme)

        # Source layout paths
        self.assertIn("tools/lsmiotool/lsmiotool", f_readme)
        self.assertIn("tools/lsmiotool/lsmiotool-worker", f_readme)
        self.assertIn("tools/lsmiotool/etc/environments.json", f_readme)
        self.assertIn("tools/bmtool/lmp-reaxff", f_readme)

        # 5. Standardized printed identity lines
        self.assertIn("Run ID:", f_readme)
        self.assertIn("Run Root:", f_readme)
        self.assertIn("Point <point-id> Correlation Token:", f_readme)
        self.assertIn("Point <point-id> Job ID:", f_readme)
        self.assertIn("Final State:", f_readme)
        self.assertIn("Exit Code:", f_readme)

        # 6. Run collision refusal
        self.assertIn("allocateRun", f_readme)
        self.assertIn("Collision Refusal", f_readme)
        self.assertIn("control/lock", f_readme)

    def testReadmeDispatchSchedulerIdAndSignalContracts(self) -> None:
        """Chunk 021: Asserts README.md documents the pre-spawn dispatch protocol, exact scheduler ID and command contracts, timeouts, fail-closed handling, and signals."""
        f_readme = self._readReadmeContent()

        # 1. 4-step dispatch protocol with pre-spawn evidence
        self.assertIn("4-Step Dispatch Protocol", f_readme)
        self.assertIn("submission_requested", f_readme)
        self.assertIn("submission_dispatched", f_readme)
        self.assertIn("submission_recorded", f_readme)
        self.assertIn(
            "Written immediately before spawning the scheduler process", f_readme
        )

        # 2. Correlation token format and recovery
        self.assertIn("^lm-[0-9a-f]{24}$", f_readme)
        self.assertIn("without blind resubmission", f_readme)
        self.assertIn("INDETERMINATE", f_readme)

        # 3. Slurm handle contract and exact commands
        self.assertIn("^[0-9]+$", f_readme)
        self.assertIn("123;cluster", f_readme)
        self.assertIn("squeue --noheader --jobs=<id> --format=%i|%T", f_readme)
        self.assertIn(
            "sacct --noheader --parsable2 --jobs=<id> --format=JobIDRaw,JobName,State,ExitCode",
            f_readme,
        )
        self.assertIn("scancel <id>", f_readme)

        # 4. Slurm credentials
        self.assertIn("SB_ACCOUNT", f_readme)
        self.assertIn("SB_EMAIL", f_readme)

        # 5. PBS handle contract and exact commands
        self.assertIn(r"^[0-9]+(?:\.[A-Za-z0-9._-]+)?$", f_readme)
        self.assertIn("123456.isambard-pbs", f_readme)
        self.assertIn("qstat -F json <id>", f_readme)
        self.assertIn("qstat -F json -x <id>", f_readme)
        self.assertIn("qdel <id>", f_readme)

        # 6. Finite timeouts, polling interval, and fail-closed error handling
        self.assertIn("grace_seconds", f_readme)
        self.assertIn("120s", f_readme)
        self.assertIn("8-second", f_readme)
        self.assertIn("time.sleep", f_readme)
        self.assertIn("fail closed", f_readme)
        self.assertIn("no 3-unknown retry loop", f_readme)

        # 7. Signal coordination and interruption-first durability
        self.assertIn("130", f_readme)
        self.assertIn("143", f_readme)
        self.assertIn("Interruption-First Durability", f_readme)
        self.assertIn(
            "interruption event is durably appended to the control stream before any cancellation command",
            f_readme,
        )

        # 8. State precedence
        self.assertIn("WHOLE_RUN_SUCCEEDED", f_readme)
        self.assertIn("SUCCEEDED", f_readme)
        self.assertIn("FAILED", f_readme)
        self.assertIn("CANCELLED", f_readme)
        self.assertIn("INTERRUPTED", f_readme)

    def testReadmeLmpAssetsFlagsAndTuningMatchUpstream(self) -> None:
        """Chunk 021: Asserts README.md documents exact upstream LMP asset filenames, tuning parameters, shared invocation argv, and the atomic large gate."""
        f_readme = self._readReadmeContent()

        # 1. Exact upstream LMP asset filenames
        self.assertIn("in.reaxc.hns", f_readme)
        self.assertIn("data.hns-equil", f_readme)
        self.assertIn("ffield.reax.hns", f_readme)

        # 2. Exact shared invocation argv and setup flags
        self.assertIn("lmp -in in.reaxc.hns -v x <REP> -v y <REP> -v z <REP>", f_readme)
        self.assertIn("-lsmio-buf-size-mb <BUF>", f_readme)
        self.assertIn("-lsmio-mmap -lsmio-buf-size-mb <BUF>", f_readme)
        self.assertIn("-lsmio-fallback", f_readme)
        self.assertIn("No Kokkos or dump flags", f_readme)

        # 3. Upstream tuning table for all 9 supported task counts
        f_independent_approved_tuning = {
            1: (4, 32),
            2: (5, 32),
            4: (6, 64),
            8: (8, 128),
            16: (10, 256),
            24: (12, 512),
            32: (14, 1024),
            40: (15, 1024),
            48: (16, 1024),
        }

        for f_tasks, (f_rep, f_buf) in f_independent_approved_tuning.items():
            # Check against independent approved literals
            self.assertIn(f"| {f_tasks} | {f_rep} | {f_buf} |", f_readme)
            # Check agreement with RunPlanner.LMP_TASK_TUNING
            f_runtime_tuning = RunPlanner.LMP_TASK_TUNING.get(f_tasks)
            self.assertIsNotNone(
                f_runtime_tuning, f"Missing runtime tuning for {f_tasks} tasks"
            )
            self.assertEqual(f_runtime_tuning["replication"], f_rep)
            self.assertEqual(f_runtime_tuning["buffer_size_mb"], f_buf)

        # 4. Atomic lmp large gate
        self.assertIn("lmp large", f_readme)
        self.assertIn("rejected atomically before run ID allocation", f_readme)

    def testReadmeCoverageGateAndConfiguredLabels(self) -> None:
        """Chunk 021: Asserts README.md documents configured certification state, preflight checks, 6-combination matrix, combination-private ranks, and parse limits."""
        f_readme = self._readReadmeContent()

        # 1. Configured certification status for all production profiles
        self.assertIn("configured", f_readme)
        self.assertIn("pending opt-in live site certification", f_readme)
        for f_prof in ("viking", "viking2", "archer2", "isambard", "dev"):
            self.assertIn(f_prof, f_readme)

        # 2. Executable, worker, and capability preflight checks
        self.assertIn("Executable, Worker, and Capability Preflight Checks", f_readme)
        self.assertIn("regular readable/executable non-symlink files", f_readme)
        self.assertIn("SHA-256 integrity", f_readme)

        # 3. 6-combination execution matrix and fixed sequence
        f_expected_combinations = [
            "(16, 8M)",
            "(16, 1M)",
            "(16, 64K)",
            "(4, 8M)",
            "(4, 1M)",
            "(4, 64K)",
        ]
        f_last_pos = -1
        for f_combo in f_expected_combinations:
            f_pos = f_readme.find(f_combo)
            self.assertNotEqual(
                f_pos, -1, f"Expected combination {f_combo} in README.md"
            )
            self.assertGreater(
                f_pos, f_last_pos, f"Combination {f_combo} appears out of order"
            )
            f_last_pos = f_pos

        # 4. Combination-private rank claims, logs, and results
        self.assertIn("ranks/<global-rank>/<combination>/claim.lock", f_readme)
        self.assertIn("logs/<combination>/rank_<global-rank>.log", f_readme)
        self.assertIn("ranks/<global-rank>/<combination>/result.json", f_readme)
        self.assertIn("combinations/<combination>/controller-result.json", f_readme)
        self.assertIn("data/c<stripe>/b<block>/", f_readme)

        # 5. Parse command boundary and limitations
        self.assertIn("RunRootResolver", f_readme)
        self.assertIn("lsmiotool parseLegacy", f_readme)
        self.assertIn("does not perform automatic run-root discovery", f_readme)

    def testRunMainPrintsIdsTokensRootFinalStateAndExit(self) -> None:
        """Chunk 019: Asserts RunMain emits Run ID, Run Root, point tokens/job IDs, final state, and exit code to stdout without duplicates."""
        # 1. Successful execution scenario
        f_mock_view = MagicMock(spec=RunStateView)
        f_mock_view.state = OverallRunState.SUCCEEDED
        f_mock_view.run_id = "run-20260823-100000-abcd"

        class FakeSuccessOrchestrator:
            def __init__(self, **kwargs: Any) -> None:
                self.m_reporter = kwargs.get("f_reporter")
                self.exitCode = 0

            def execute(self, *args: Any, **kwargs: Any) -> RunStateView:
                if self.m_reporter:
                    self.m_reporter.reportRunIdentity(
                        "run-20260823-100000-abcd",
                        "/tmp/benchmarks/run-20260823-100000-abcd",
                    )
                    self.m_reporter.reportPointSubmission(
                        "00-tasks-1", "lm-111111111111111111111111", "1001"
                    )
                    self.m_reporter.reportCompletion(OverallRunState.SUCCEEDED, 0)
                return f_mock_view

        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            f_main_succ = RunMain(
                "ior",
                "local",
                f_orchestrator_factory=lambda **kw: FakeSuccessOrchestrator(**kw),
            )
            f_exit = f_main_succ.run()
            self.assertEqual(f_exit, 0)
            f_out = mock_stdout.getvalue()
            self.assertIn("Run ID: run-20260823-100000-abcd\n", f_out)
            self.assertIn("Run Root: /tmp/benchmarks/run-20260823-100000-abcd\n", f_out)
            self.assertIn(
                "Point 00-tasks-1 Correlation Token: lm-111111111111111111111111\n",
                f_out,
            )
            self.assertIn("Point 00-tasks-1 Job ID: 1001\n", f_out)
            self.assertIn("Final State: SUCCEEDED\n", f_out)
            self.assertIn("Exit Code: 0\n", f_out)

            # Assert order of output
            pos_id = f_out.index("Run ID: run-20260823-100000-abcd")
            pos_root = f_out.index("Run Root: /tmp/benchmarks/run-20260823-100000-abcd")
            pos_token = f_out.index("Point 00-tasks-1 Correlation Token:")
            pos_job = f_out.index("Point 00-tasks-1 Job ID: 1001")
            pos_final = f_out.index("Final State: SUCCEEDED")
            pos_exit = f_out.index("Exit Code: 0")
            self.assertTrue(
                pos_id < pos_root < pos_token < pos_job < pos_final < pos_exit
            )

        # 2. Failure execution scenario
        f_mock_view_fail = MagicMock(spec=RunStateView)
        f_mock_view_fail.state = OverallRunState.FAILED
        f_mock_view_fail.run_id = "run-20260823-100000-fail"

        class FakeFailureOrchestrator:
            def __init__(self, **kwargs: Any) -> None:
                self.m_reporter = kwargs.get("f_reporter")
                self.exitCode = 1

            def execute(self, *args: Any, **kwargs: Any) -> RunStateView:
                if self.m_reporter:
                    self.m_reporter.reportRunIdentity(
                        "run-20260823-100000-fail",
                        "/tmp/benchmarks/run-20260823-100000-fail",
                    )
                    self.m_reporter.reportPointSubmission(
                        "00-tasks-1", "lm-111111111111111111111111", "1002"
                    )
                    self.m_reporter.reportCompletion(OverallRunState.FAILED, 1)
                return f_mock_view_fail

        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            f_main_fail = RunMain(
                "ior",
                "local",
                f_orchestrator_factory=lambda **kw: FakeFailureOrchestrator(**kw),
            )
            f_exit = f_main_fail.run()
            self.assertEqual(f_exit, 1)
            f_out = mock_stdout.getvalue()
            self.assertIn("Run ID: run-20260823-100000-fail\n", f_out)
            self.assertIn("Run Root: /tmp/benchmarks/run-20260823-100000-fail\n", f_out)
            self.assertIn(
                "Point 00-tasks-1 Correlation Token: lm-111111111111111111111111\n",
                f_out,
            )
            self.assertIn("Point 00-tasks-1 Job ID: 1002\n", f_out)
            self.assertIn("Final State: FAILED\n", f_out)
            self.assertIn("Exit Code: 1\n", f_out)

        # 3. Multi-point scenario and no duplicate lines
        class FakeMultiPointOrchestrator:
            def __init__(self, **kwargs: Any) -> None:
                self.m_reporter = kwargs.get("f_reporter")
                self.exitCode = 0

            def execute(self, *args: Any, **kwargs: Any) -> RunStateView:
                if self.m_reporter:
                    self.m_reporter.reportRunIdentity(
                        "run-20260823-multi", "/tmp/benchmarks/run-20260823-multi"
                    )
                    # Try emitting run identity again to assert deduplication
                    self.m_reporter.reportRunIdentity(
                        "run-20260823-multi", "/tmp/benchmarks/run-20260823-multi"
                    )
                    self.m_reporter.reportPointSubmission(
                        "00-tasks-1", "lm-aaaaaaaaaaaaaaaaaaaaaaaa", "2001"
                    )
                    # Try duplicate point submission emission
                    self.m_reporter.reportPointSubmission(
                        "00-tasks-1", "lm-aaaaaaaaaaaaaaaaaaaaaaaa", "2001"
                    )
                    self.m_reporter.reportPointSubmission(
                        "01-tasks-2", "lm-bbbbbbbbbbbbbbbbbbbbbbbb", "2002"
                    )
                    self.m_reporter.reportCompletion(OverallRunState.SUCCEEDED, 0)
                    self.m_reporter.reportCompletion(OverallRunState.SUCCEEDED, 0)
                return f_mock_view

        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            f_main_multi = RunMain(
                "ior",
                "small",
                f_orchestrator_factory=lambda **kw: FakeMultiPointOrchestrator(**kw),
            )
            f_exit = f_main_multi.run()
            self.assertEqual(f_exit, 0)
            f_out = mock_stdout.getvalue()
            self.assertEqual(f_out.count("Run ID: run-20260823-multi"), 1)
            self.assertEqual(
                f_out.count("Run Root: /tmp/benchmarks/run-20260823-multi"), 1
            )
            self.assertEqual(f_out.count("Point 00-tasks-1 Job ID: 2001"), 1)
            self.assertEqual(f_out.count("Point 01-tasks-2 Job ID: 2002"), 1)
            self.assertEqual(f_out.count("Final State: SUCCEEDED"), 1)
            self.assertEqual(f_out.count("Exit Code: 0"), 1)

        # 4. Exact qualified PBS ID preservation
        class FakePbsOrchestrator:
            def __init__(self, **kwargs: Any) -> None:
                self.m_reporter = kwargs.get("f_reporter")
                self.exitCode = 0

            def execute(self, *args: Any, **kwargs: Any) -> RunStateView:
                if self.m_reporter:
                    self.m_reporter.reportRunIdentity(
                        "run-pbs-qualified", "/tmp/benchmarks/run-pbs-qualified"
                    )
                    self.m_reporter.reportPointSubmission(
                        "00-tasks-1",
                        "lm-cccccccccccccccccccccccc",
                        "123456.isambard-pbs.epcc.ed.ac.uk",
                    )
                    self.m_reporter.reportCompletion(OverallRunState.SUCCEEDED, 0)
                return f_mock_view

        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            f_main_pbs = RunMain(
                "ior",
                "local",
                f_orchestrator_factory=lambda **kw: FakePbsOrchestrator(**kw),
            )
            f_exit = f_main_pbs.run()
            self.assertEqual(f_exit, 0)
            f_out = mock_stdout.getvalue()
            self.assertIn(
                "Point 00-tasks-1 Job ID: 123456.isambard-pbs.epcc.ed.ac.uk\n", f_out
            )

    def testValidationBeforePlanPrintsNoFakeIdentity(self) -> None:
        """Chunk 019: Asserts pre-plan validation errors print only concise stderr with no fake run identity or Run ID on stdout."""
        f_exec_str = str(self.m_executable)

        # 1. Direct RunMain with LMP large scale (rejected during preflight before plan creation)
        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            with patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
                f_main_lmp = RunMain("lmp", "large")
                f_exit = f_main_lmp.run()
                self.assertEqual(f_exit, 1)
                self.assertEqual(
                    mock_stdout.getvalue(),
                    "",
                    "Stdout must be empty on preflight error",
                )
                self.assertIn("Error:", mock_stderr.getvalue())
                self.assertIn("LMP large scale is unsupported", mock_stderr.getvalue())
                self.assertNotIn("Run ID:", mock_stdout.getvalue())
                self.assertNotIn("Run Root:", mock_stdout.getvalue())
                self.assertNotIn("Run ID:", mock_stderr.getvalue())

        # 2. Direct RunMain with invalid benchmark target
        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            with patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
                with self.assertRaises(RunCliParseError):
                    RunMain("invalid_benchmark", "local")

        # 3. Executable invocation with unknown target via CLI parser
        with patch.object(sys, "argv", [f_exec_str, "run", "unknown_target", "local"]):
            with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                with patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
                    with self.assertRaises(SystemExit) as ctx:
                        runpy.run_path(f_exec_str, run_name="__main__")
                    self.assertEqual(ctx.exception.code, 1)
                    self.assertEqual(mock_stdout.getvalue(), "")
                    self.assertIn(
                        "Invalid benchmark: 'unknown_target'", mock_stderr.getvalue()
                    )
                    self.assertNotIn("Run ID:", mock_stdout.getvalue())

    def testSignalAndIndeterminateProminentlyReportHandleRoot(self) -> None:
        """Chunk 019: Asserts signal interruption, cancellation, and indeterminate states prominently retain exact job ID and run root in output."""
        # 1. SIGINT with confirmed cancellation (130)
        f_mock_view_cancel = MagicMock(spec=RunStateView)
        f_mock_view_cancel.state = OverallRunState.CANCELLED
        f_mock_view_cancel.run_id = "run-sigint-cancel"

        class FakeCancelOrchestrator:
            def __init__(self, **kwargs: Any) -> None:
                self.m_reporter = kwargs.get("f_reporter")
                self.exitCode = 130

            def execute(self, *args: Any, **kwargs: Any) -> RunStateView:
                if self.m_reporter:
                    self.m_reporter.reportRunIdentity(
                        "run-sigint-cancel", "/tmp/benchmarks/run-sigint-cancel"
                    )
                    self.m_reporter.reportPointSubmission(
                        "00-tasks-1", "lm-dddddddddddddddddddddddd", "55555"
                    )
                    self.m_reporter.reportCompletion(OverallRunState.CANCELLED, 130)
                return f_mock_view_cancel

        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            f_main_cancel = RunMain(
                "ior",
                "local",
                f_orchestrator_factory=lambda **kw: FakeCancelOrchestrator(**kw),
            )
            f_exit = f_main_cancel.run()
            self.assertEqual(f_exit, 130)
            f_out = mock_stdout.getvalue()
            self.assertIn("Run ID: run-sigint-cancel\n", f_out)
            self.assertIn("Run Root: /tmp/benchmarks/run-sigint-cancel\n", f_out)
            self.assertIn(
                "Point 00-tasks-1 Correlation Token: lm-dddddddddddddddddddddddd\n",
                f_out,
            )
            self.assertIn("Point 00-tasks-1 Job ID: 55555\n", f_out)
            self.assertIn("Final State: CANCELLED\n", f_out)
            self.assertIn("Exit Code: 130\n", f_out)

        # 2. Indeterminate execution with unconfirmed cancellation / query ambiguity
        f_mock_view_indet = MagicMock(spec=RunStateView)
        f_mock_view_indet.state = OverallRunState.INDETERMINATE
        f_mock_view_indet.run_id = "run-indet-unconfirmed"

        class FakeIndetOrchestrator:
            def __init__(self, **kwargs: Any) -> None:
                self.m_reporter = kwargs.get("f_reporter")
                self.exitCode = 1

            def execute(self, *args: Any, **kwargs: Any) -> RunStateView:
                if self.m_reporter:
                    self.m_reporter.reportRunIdentity(
                        "run-indet-unconfirmed", "/data/runs/run-indet-unconfirmed"
                    )
                    self.m_reporter.reportPointSubmission(
                        "00-tasks-1",
                        "lm-eeeeeeeeeeeeeeeeeeeeeeee",
                        "777777.pbs01.cluster",
                    )
                    self.m_reporter.reportCompletion(OverallRunState.INDETERMINATE, 1)
                return f_mock_view_indet

        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            f_main_indet = RunMain(
                "ior",
                "local",
                f_orchestrator_factory=lambda **kw: FakeIndetOrchestrator(**kw),
            )
            f_exit = f_main_indet.run()
            self.assertEqual(f_exit, 1)
            f_out = mock_stdout.getvalue()
            # Prominently retain exact job ID and root
            self.assertIn("Run Root: /data/runs/run-indet-unconfirmed\n", f_out)
            self.assertIn("Point 00-tasks-1 Job ID: 777777.pbs01.cluster\n", f_out)
            self.assertIn("Final State: INDETERMINATE\n", f_out)
            self.assertIn("Exit Code: 1\n", f_out)

        # 3. SIGTERM interruption before point execution (143)
        f_mock_view_interrupted = MagicMock(spec=RunStateView)
        f_mock_view_interrupted.state = OverallRunState.INTERRUPTED
        f_mock_view_interrupted.run_id = "run-sigterm-early"

        class FakeEarlySigtermOrchestrator:
            def __init__(self, **kwargs: Any) -> None:
                self.m_reporter = kwargs.get("f_reporter")
                self.exitCode = 143

            def execute(self, *args: Any, **kwargs: Any) -> RunStateView:
                if self.m_reporter:
                    self.m_reporter.reportRunIdentity(
                        "run-sigterm-early", "/tmp/benchmarks/run-sigterm-early"
                    )
                    self.m_reporter.reportCompletion(OverallRunState.INTERRUPTED, 143)
                return f_mock_view_interrupted

        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            f_main_sigterm = RunMain(
                "ior",
                "local",
                f_orchestrator_factory=lambda **kw: FakeEarlySigtermOrchestrator(**kw),
            )
            f_exit = f_main_sigterm.run()
            self.assertEqual(f_exit, 143)
            f_out = mock_stdout.getvalue()
            self.assertIn("Run ID: run-sigterm-early\n", f_out)
            self.assertIn("Run Root: /tmp/benchmarks/run-sigterm-early\n", f_out)
            self.assertIn("Final State: INTERRUPTED\n", f_out)
            self.assertIn("Exit Code: 143\n", f_out)

    def testRealSourceExecutableFromUnrelatedCwdHomeWithProductionProfile(self) -> None:
        """Chunk 020: Invokes the real source lsmiotool executable from an unrelated CWD/HOME with decoys and explicit credentials, asserting preflight failure without F-01 errors."""
        f_exec_str = str(self.m_executable)
        f_unrelated_cwd = os.path.join(self.m_temp_dir, "real_src_exec_cwd")
        f_unrelated_home = os.path.join(self.m_temp_dir, "real_src_exec_home")
        os.makedirs(f_unrelated_cwd, exist_ok=True)
        os.makedirs(f_unrelated_home, exist_ok=True)

        # Plant decoy files in CWD and HOME
        for f_dir in (f_unrelated_cwd, f_unrelated_home):
            with open(os.path.join(f_dir, "VERSION"), "w", encoding="utf-8") as f_f:
                f_f.write("decoy-version\n")
            with open(
                os.path.join(f_dir, "in.reaxc.hns"), "w", encoding="utf-8"
            ) as f_f:
                f_f.write("# decoy lmp asset\n")
            with open(
                os.path.join(f_dir, "lsmiotool-worker"), "w", encoding="utf-8"
            ) as f_f:
                f_f.write("#!/bin/sh\nexit 99\n")
            os.chmod(os.path.join(f_dir, "lsmiotool-worker"), 0o755)

        f_env = dict(os.environ)
        f_env["HOME"] = f_unrelated_home
        f_env["LSMIO_ENV"] = "VIKING"
        f_env["SB_ACCOUNT"] = "production_acct"
        f_env["SB_EMAIL"] = "prod@example.com"

        # 1. Run IOR local: passes package validation and profile resolution, fails at missing benchmark executable preflight
        f_proc = subprocess.run(
            [sys.executable, f_exec_str, "run", "ior", "local", "--setup", "BASE"],
            cwd=f_unrelated_cwd,
            env=f_env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(f_proc.returncode, 1)
        self.assertIn("Error: Benchmark executable does not exist", f_proc.stderr)
        self.assertNotIn("TypeError", f_proc.stderr)
        self.assertNotIn("unexpected keyword argument", f_proc.stderr)
        self.assertNotIn("Run ID:", f_proc.stdout)
        self.assertNotIn("Final State:", f_proc.stdout)

        # 2. Run LMP large: atomically rejected during preflight before any resource access
        f_proc_lmp = subprocess.run(
            [sys.executable, f_exec_str, "run", "lmp", "large"],
            cwd=f_unrelated_cwd,
            env=f_env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(f_proc_lmp.returncode, 1)
        self.assertIn("LMP large scale is unsupported", f_proc_lmp.stderr)
        self.assertNotIn("Run ID:", f_proc_lmp.stdout)
