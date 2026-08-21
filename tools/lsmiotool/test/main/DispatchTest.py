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
import unittest
from unittest.mock import MagicMock, patch

from lsmiotool.lib.cli import (
    LSMIOTOOL_HELP,
    RUN_HELP_TEXT,
    PackageValidationError,
    RunCliParseError,
    RunCliParser,
    SourcePackageValidator,
    parseRunArguments,
)
from lsmiotool.lib.main import (
    CompareMain,
    HpcEnvMain,
    LatexMain,
    ParseMain,
    RunMain,
    ShellMain,
    TestMain,
)
from lsmiotool.lib.run import RunRequest
from lsmiotool.lib.version import getVersion


class DispatchTest(unittest.TestCase):
    """Unit tests for lazy legacy dispatch, entry point, SourcePackageValidator, and RunMain."""

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.mkdtemp(prefix="lsmiotool-dispatch-test-")
        self.m_executable = (
            Path(__file__).resolve().parents[2] / "lsmiotool"
        )
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
            with open(os.path.join(f_real_dir, "lib", f_name), "w", encoding="utf-8") as f_f:
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
        with open(os.path.join(f_incomplete_pkg, "lib", "cli.py"), "w", encoding="utf-8") as f_f:
            f_f.write("# dummy\n")
        # Missing main.py, version.py, __init__.py
        with self.assertRaises(PackageValidationError):
            SourcePackageValidator.validate(f_incomplete_pkg)

        # 6. Symlink required core file
        f_symlink_file_pkg = os.path.join(self.m_temp_dir, "symfile_pkg")
        os.makedirs(os.path.join(f_symlink_file_pkg, "lib"), exist_ok=True)
        for f_name in ("__init__.py", "cli.py", "version.py"):
            with open(os.path.join(f_symlink_file_pkg, "lib", f_name), "w", encoding="utf-8") as f_f:
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
            with open(os.path.join(f_dir_file_pkg, "lib", f_name), "w", encoding="utf-8") as f_f:
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
            with open(os.path.join(f_decoy_cwd, "lib", f_name), "w", encoding="utf-8") as f_f:
                f_f.write("# dummy\n")
        os.chdir(f_decoy_cwd)

        # Explicit nonexistent path must fail immediately without falling back to cwd
        with self.assertRaises(PackageValidationError):
            SourcePackageValidator.validate(os.path.join(self.m_temp_dir, "nonexistent"))

    def testEveryLegacyCommandAndGlobalSsdCompatibility(self) -> None:
        """Asserts all legacy commands maintain argument compatibility with and without global SSD."""
        f_exec_str = str(self.m_executable)

        # 1. compare command
        with patch.object(sys, "argv", [f_exec_str, "compare", "bench_folder", "read"]):
            with patch.object(CompareMain, "run", return_value=0) as mock_run:
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 0)
                mock_run.assert_called_once()

        # compare command with global --ssd
        with patch.object(sys, "argv", [f_exec_str, "--ssd", "compare", "bench_folder", "write", "8", "8M"]):
            with patch.object(CompareMain, "run", return_value=0) as mock_run:
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 0)
                mock_run.assert_called_once()

        # compare command with global -s
        with patch.object(sys, "argv", [f_exec_str, "-s", "compare", "bench_folder", "read"]):
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
        # compare with insufficient arguments
        with patch.object(sys, "argv", [f_exec_str, "compare", "bench_folder"]):
            with self.assertRaises(SystemExit) as ctx:
                runpy.run_path(f_exec_str, run_name="__main__")
            self.assertEqual(ctx.exception.code, 1)

        # latex with no arguments
        with patch.object(sys, "argv", [f_exec_str, "latex"]):
            with self.assertRaises(SystemExit) as ctx:
                runpy.run_path(f_exec_str, run_name="__main__")
            self.assertEqual(ctx.exception.code, 1)

        # parse with insufficient arguments
        with patch.object(sys, "argv", [f_exec_str, "parse", "ior"]):
            with self.assertRaises(SystemExit) as ctx:
                runpy.run_path(f_exec_str, run_name="__main__")
            self.assertEqual(ctx.exception.code, 1)

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

    def testParseStillReceivesSsd(self) -> None:
        """Asserts parse command receives the SSD boolean flag."""
        f_exec_str = str(self.m_executable)

        # 1. parse without SSD
        with patch.object(sys, "argv", [f_exec_str, "parse", "ior", "local"]):
            with patch("lsmiotool.lib.main.ParseMain") as mock_parse_cls:
                mock_inst = MagicMock()
                mock_inst.run.return_value = 0
                mock_parse_cls.return_value = mock_inst
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 0)
                mock_parse_cls.assert_called_once_with("ior", "local", ssd=False)

        # 2. parse with global --ssd
        with patch.object(sys, "argv", [f_exec_str, "--ssd", "parse", "lsmio", "small"]):
            with patch("lsmiotool.lib.main.ParseMain") as mock_parse_cls:
                mock_inst = MagicMock()
                mock_inst.run.return_value = 0
                mock_parse_cls.return_value = mock_inst
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 0)
                mock_parse_cls.assert_called_once_with("lsmio", "small", ssd=True)

        # 3. parse with global -s
        with patch.object(sys, "argv", [f_exec_str, "-s", "parse", "lmp", "bake"]):
            with patch("lsmiotool.lib.main.ParseMain") as mock_parse_cls:
                mock_inst = MagicMock()
                mock_inst.run.return_value = 0
                mock_parse_cls.return_value = mock_inst
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 0)
                mock_parse_cls.assert_called_once_with("lmp", "bake", ssd=True)

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
        self.assertEqual(
            f_factory_calls[0].get("f_worker_validator"), f_mock_validator
        )
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
        with patch.object(sys, "argv", [f_exec_str, "run", "ior", "local", "--setup=BASE"]):
            with patch("sys.stderr", new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_exec_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 1)

        # 3. Run command syntax error: unknown option
        with patch.object(sys, "argv", [f_exec_str, "run", "ior", "local", "--unknown"]):
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
        self.assertIn("lsmiotool parse", f_readme)

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

