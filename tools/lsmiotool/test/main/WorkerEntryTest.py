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
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from lsmiotool.lib.cli import (
    WorkerExecutableValidationError,
    WorkerExecutableValidator,
)
from lsmiotool.lib.main import RunMain
from lsmiotool.lib.resources import (
    ExecutionMode,
    InstallRelativeLayout,
    ResourceLocator,
    RuntimeLayout,
)
from lsmiotool.lib.run import (
    PreflightError,
    RunOrchestrator,
    RunPlan,
    RunRequest,
)
from lsmiotool.lib.site import (
    EnvironmentResolver,
    SiteProfile,
    SiteProfileRegistry,
)
from lsmiotool.lib.worker import (
    AllocationController,
    AllocationControllerError,
    RankWorker,
    RankWorkerError,
)


class WorkerEntryTest(unittest.TestCase):
    """Unit tests for WorkerExecutableValidator, lsmiotool-worker entry script, and preflight integration."""

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.mkdtemp(prefix="lsmiotool-worker-entry-test-")
        self.m_worker_executable = (
            Path(__file__).resolve().parents[2] / "lsmiotool-worker"
        )
        self.m_original_cwd = os.getcwd()

        # Ensure lsmiotool-worker has executable permissions
        if self.m_worker_executable.exists():
            os.chmod(str(self.m_worker_executable), 0o755)

        # Create a test profile for preflight testing
        self.m_bench_root = os.path.join(self.m_temp_dir, "benchmark")
        os.makedirs(self.m_bench_root, exist_ok=True)
        self.m_registry = EnvironmentResolver.resolveRegistry(
            f_user="testuser", f_home=self.m_temp_dir
        )
        self.m_dev_profile = self.m_registry.getProfile("dev")

    def tearDown(self) -> None:
        os.chdir(self.m_original_cwd)
        shutil.rmtree(self.m_temp_dir, ignore_errors=True)

    def testWorkerValidatorAcceptsCreatedExecutable(self) -> None:
        """Validates that WorkerExecutableValidator accepts the real lsmiotool-worker executable in source tree."""
        self.assertTrue(
            self.m_worker_executable.exists(),
            f"Expected lsmiotool-worker at {self.m_worker_executable}",
        )

        # 1. String path validation
        f_norm_path = WorkerExecutableValidator.validate(str(self.m_worker_executable))
        self.assertEqual(f_norm_path, os.path.normpath(str(self.m_worker_executable)))

        # 2. Path object validation
        f_norm_path_obj = WorkerExecutableValidator.validate(self.m_worker_executable)
        self.assertEqual(f_norm_path_obj, os.path.normpath(str(self.m_worker_executable)))

        # 3. Instance method and callable validation
        f_validator = WorkerExecutableValidator()
        self.assertEqual(
            f_validator.validate(str(self.m_worker_executable)),
            os.path.normpath(str(self.m_worker_executable)),
        )
        self.assertEqual(
            f_validator(str(self.m_worker_executable)),
            os.path.normpath(str(self.m_worker_executable)),
        )

    def testWorkerValidatorRejectsMissingSymlinkWrongTypeAndNonExecutableWithoutFallback(self) -> None:
        """Asserts rejection of symlinks, directories, missing files, non-executable files, and unreadable files without search/fallback."""
        # 1. Missing executable
        f_missing_path = os.path.join(self.m_temp_dir, "nonexistent-worker")
        with self.assertRaises(WorkerExecutableValidationError):
            WorkerExecutableValidator.validate(f_missing_path)

        # 2. Symlink to real executable
        f_real_exe = os.path.join(self.m_temp_dir, "real_worker")
        with open(f_real_exe, "w", encoding="utf-8") as f_f:
            f_f.write("#!/bin/sh\nexit 0\n")
        os.chmod(f_real_exe, 0o755)

        f_symlink_exe = os.path.join(self.m_temp_dir, "symlink_worker")
        os.symlink(f_real_exe, f_symlink_exe)

        with self.assertRaises(WorkerExecutableValidationError):
            WorkerExecutableValidator.validate(f_symlink_exe)

        # 3. Directory instead of regular file
        f_dir_path = os.path.join(self.m_temp_dir, "dir_worker")
        os.makedirs(f_dir_path, exist_ok=True)
        os.chmod(f_dir_path, 0o755)

        with self.assertRaises(WorkerExecutableValidationError):
            WorkerExecutableValidator.validate(f_dir_path)

        # 4. Non-executable regular file
        f_non_exec_file = os.path.join(self.m_temp_dir, "non_exec_worker")
        with open(f_non_exec_file, "w", encoding="utf-8") as f_f:
            f_f.write("#!/bin/sh\nexit 0\n")
        os.chmod(f_non_exec_file, 0o644)

        with self.assertRaises(WorkerExecutableValidationError):
            WorkerExecutableValidator.validate(f_non_exec_file)

        # 5. Unreadable file
        with patch("os.access", side_effect=lambda f_path, f_mode: False if f_mode == os.R_OK else True):
            with self.assertRaises(WorkerExecutableValidationError):
                WorkerExecutableValidator.validate(f_real_exe)

        # 6. Invalid arguments (None, empty, whitespace, wrong types, NUL byte)
        with self.assertRaises(WorkerExecutableValidationError):
            WorkerExecutableValidator.validate(None)  # type: ignore
        with self.assertRaises(WorkerExecutableValidationError):
            WorkerExecutableValidator.validate("")
        with self.assertRaises(WorkerExecutableValidationError):
            WorkerExecutableValidator.validate("   ")
        with self.assertRaises(WorkerExecutableValidationError):
            WorkerExecutableValidator.validate(12345)  # type: ignore
        with self.assertRaises(WorkerExecutableValidationError):
            WorkerExecutableValidator.validate(f"/path/with/\0/null")

        # 7. No fallback to cwd, HOME, or PATH
        f_decoy_dir = os.path.join(self.m_temp_dir, "decoy_cwd")
        os.makedirs(f_decoy_dir, exist_ok=True)
        f_decoy_worker = os.path.join(f_decoy_dir, "lsmiotool-worker")
        with open(f_decoy_worker, "w", encoding="utf-8") as f_f:
            f_f.write("#!/bin/sh\nexit 0\n")
        os.chmod(f_decoy_worker, 0o755)

        os.chdir(f_decoy_dir)
        # Passing an explicit non-existent path must fail without falling back to cwd
        with self.assertRaises(WorkerExecutableValidationError):
            WorkerExecutableValidator.validate(os.path.join(self.m_temp_dir, "nonexistent"))

    def testRunPreflightUsesRealWorkerValidatorBeforeMutation(self) -> None:
        """Asserts RunMain / RunOrchestrator preflight executes WorkerExecutableValidator before making any mutations."""
        f_req = RunRequest(f_target="ior", f_scale="local", f_ssd=False, f_setup="BASE")
        f_invalid_worker = os.path.join(self.m_temp_dir, "missing_worker_exe")

        # 1. RunOrchestrator preflight with invalid worker executable raises PreflightError
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_worker_validator=WorkerExecutableValidator,
        )

        with self.assertRaises(PreflightError):
            f_orch.execute(
                f_request=f_req,
                f_site=self.m_dev_profile,
                f_worker_executable=f_invalid_worker,
            )

        # Assert no run directory or lock file or mutation occurred
        f_runs_dir = os.path.join(self.m_dev_profile.benchmark_roots["hdd"], "runs")
        self.assertFalse(
            os.path.exists(f_runs_dir),
            "Runs directory must NOT be created when worker validation fails during preflight",
        )

        # 2. RunMain delegating to RunOrchestrator with default WorkerExecutableValidator
        f_run_main = RunMain(
            f_request=f_req,
            f_site=self.m_dev_profile,
        )
        # Set an invalid worker executable via mocked runtime layout
        f_mock_layout = MagicMock()
        f_mock_layout.worker_executable = f_invalid_worker
        f_run_main.m_runtime_layout = f_mock_layout

        with patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
            f_status = f_run_main.run()
            self.assertEqual(f_status, 1)
            self.assertIn("Worker executable validation failed", mock_stderr.getvalue())

        self.assertFalse(
            os.path.exists(f_runs_dir),
            "Runs directory must NOT exist after RunMain preflight failure",
        )

    def testExactModesAndArity(self) -> None:
        """Validates lsmiotool-worker accepting exact allocation (2 args) and rank (3 args) commands, and rejecting invalid arity or unknown commands."""
        f_worker_str = str(self.m_worker_executable)

        # 1. Valid allocation mode (2 args after 'allocation')
        with patch("lsmiotool.lib.worker.AllocationController.run", return_value=0) as mock_alloc_run:
            with patch.object(
                sys,
                "argv",
                [f_worker_str, "allocation", "/path/to/manifest.json", "00-tasks-1"],
            ):
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_worker_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 0)
                mock_alloc_run.assert_called_once()

        # 2. Valid rank mode (3 args after 'rank')
        with patch("lsmiotool.lib.worker.RankWorker.run", return_value=0) as mock_rank_run:
            with patch.object(
                sys,
                "argv",
                [f_worker_str, "rank", "/path/to/manifest.json", "00-tasks-1", "c16_b8M"],
            ):
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_worker_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 0)
                mock_rank_run.assert_called_once()

        # 3. Invalid arity for allocation (too few args)
        for f_bad_argv in (
            [f_worker_str, "allocation"],
            [f_worker_str, "allocation", "/path/to/manifest.json"],
        ):
            with patch.object(sys, "argv", f_bad_argv):
                with patch("sys.stderr", new_callable=io.StringIO):
                    with self.assertRaises(SystemExit) as ctx:
                        runpy.run_path(f_worker_str, run_name="__main__")
                    self.assertEqual(ctx.exception.code, 2)

        # 4. Invalid arity for allocation (too many args)
        with patch.object(
            sys,
            "argv",
            [f_worker_str, "allocation", "/path/to/manifest.json", "point-0", "extra_arg"],
        ):
            with patch("sys.stderr", new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_worker_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 2)

        # 5. Invalid arity for rank (too few args)
        for f_bad_argv in (
            [f_worker_str, "rank"],
            [f_worker_str, "rank", "/path/to/manifest.json"],
            [f_worker_str, "rank", "/path/to/manifest.json", "point-0"],
        ):
            with patch.object(sys, "argv", f_bad_argv):
                with patch("sys.stderr", new_callable=io.StringIO):
                    with self.assertRaises(SystemExit) as ctx:
                        runpy.run_path(f_worker_str, run_name="__main__")
                    self.assertEqual(ctx.exception.code, 2)

        # 6. Invalid arity for rank (too many args)
        with patch.object(
            sys,
            "argv",
            [f_worker_str, "rank", "/path/to/manifest.json", "point-0", "c16_b8M", "extra"],
        ):
            with patch("sys.stderr", new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_worker_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 2)

        # 7. No arguments
        with patch.object(sys, "argv", [f_worker_str]):
            with patch("sys.stderr", new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_worker_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 1)

        # 8. Unknown mode
        with patch.object(sys, "argv", [f_worker_str, "unknown_mode", "foo"]):
            with patch("sys.stderr", new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_worker_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 1)

    def testStatusesReachSystemExit(self) -> None:
        """Validates that returned statuses from AllocationController and RankWorker propagate to sys.exit."""
        f_worker_str = str(self.m_worker_executable)

        # 1. AllocationController return codes: 0, 1, 7, 130, 143
        for f_expected_code in (0, 1, 7, 130, 143):
            with patch(
                "lsmiotool.lib.worker.AllocationController.run",
                return_value=f_expected_code,
            ):
                with patch.object(
                    sys,
                    "argv",
                    [f_worker_str, "allocation", "/path/manifest.json", "point-0"],
                ):
                    with self.assertRaises(SystemExit) as ctx:
                        runpy.run_path(f_worker_str, run_name="__main__")
                    self.assertEqual(ctx.exception.code, f_expected_code)

        # 2. RankWorker return codes: 0, 1, 7, 130, 143
        for f_expected_code in (0, 1, 7, 130, 143):
            with patch(
                "lsmiotool.lib.worker.RankWorker.run",
                return_value=f_expected_code,
            ):
                with patch.object(
                    sys,
                    "argv",
                    [f_worker_str, "rank", "/path/manifest.json", "point-0", "c16_b8M"],
                ):
                    with self.assertRaises(SystemExit) as ctx:
                        runpy.run_path(f_worker_str, run_name="__main__")
                    self.assertEqual(ctx.exception.code, f_expected_code)

        # 3. AllocationControllerError raises and maps to exit code 1
        with patch(
            "lsmiotool.lib.worker.AllocationController.run",
            side_effect=AllocationControllerError("Controller failed"),
        ):
            with patch.object(
                sys,
                "argv",
                [f_worker_str, "allocation", "/path/manifest.json", "point-0"],
            ):
                with patch("sys.stderr", new_callable=io.StringIO):
                    with self.assertRaises(SystemExit) as ctx:
                        runpy.run_path(f_worker_str, run_name="__main__")
                    self.assertEqual(ctx.exception.code, 1)

        # 4. RankWorkerError raises and maps to exit code 1
        with patch(
            "lsmiotool.lib.worker.RankWorker.run",
            side_effect=RankWorkerError("Rank execution failed"),
        ):
            with patch.object(
                sys,
                "argv",
                [f_worker_str, "rank", "/path/manifest.json", "point-0", "c16_b8M"],
            ):
                with patch("sys.stderr", new_callable=io.StringIO):
                    with self.assertRaises(SystemExit) as ctx:
                        runpy.run_path(f_worker_str, run_name="__main__")
                    self.assertEqual(ctx.exception.code, 1)

    def testSourceLayoutExplicit(self) -> None:
        """Asserts explicit layout construction in lsmiotool-worker."""
        f_worker_str = str(self.m_worker_executable)
        f_layout = ResourceLocator.forSource(f_worker_str)

        self.assertEqual(
            f_layout.package_root,
            os.path.normpath(str(self.m_worker_executable.parent)),
        )

        f_captured_init_kwargs = []

        class MockAllocationController:
            def __init__(self, *f_args, **f_kwargs):
                f_captured_init_kwargs.append(f_kwargs)

            def run(self, *f_args, **f_kwargs):
                return 0

        with patch("lsmiotool.lib.worker.AllocationController", MockAllocationController):
            with patch.object(
                sys,
                "argv",
                [f_worker_str, "allocation", "/path/manifest.json", "point-0"],
            ):
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_worker_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 0)
                self.assertEqual(len(f_captured_init_kwargs), 1)
                f_kw = f_captured_init_kwargs[0]
                self.assertEqual(f_kw.get("f_worker_executable"), f_worker_str)
                self.assertEqual(f_kw.get("f_asset_source"), f_layout.asset_root)

    def testUnrelatedCwd(self) -> None:
        """Asserts lsmiotool-worker functions identically regardless of the current working directory."""
        f_worker_str = str(self.m_worker_executable)
        f_unrelated_dir = os.path.join(self.m_temp_dir, "unrelated_cwd")
        os.makedirs(f_unrelated_dir, exist_ok=True)
        os.chdir(f_unrelated_dir)

        # Execute allocation mode from unrelated cwd
        with patch("lsmiotool.lib.worker.AllocationController.run", return_value=0) as mock_alloc:
            with patch.object(
                sys,
                "argv",
                [f_worker_str, "allocation", "/path/manifest.json", "00-tasks-1"],
            ):
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_worker_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 0)
                mock_alloc.assert_called_once()

        # Execute rank mode from unrelated cwd
        with patch("lsmiotool.lib.worker.RankWorker.run", return_value=0) as mock_rank:
            with patch.object(
                sys,
                "argv",
                [f_worker_str, "rank", "/path/manifest.json", "00-tasks-1", "c16_b8M"],
            ):
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_worker_str, run_name="__main__")
                self.assertEqual(ctx.exception.code, 0)
                mock_rank.assert_called_once()

    def testNoSchedulerOrFallbackLookup(self) -> None:
        """Asserts zero scheduler command calls or fallback directory searches."""
        f_worker_str = str(self.m_worker_executable)

        # Assert no scheduler commands (srun, aprun, sbatch, qsub) are invoked during worker execution
        with patch("subprocess.run") as mock_subproc, patch("subprocess.Popen") as mock_popen:
            with patch("lsmiotool.lib.worker.AllocationController.run", return_value=0):
                with patch.object(
                    sys,
                    "argv",
                    [f_worker_str, "allocation", "/path/manifest.json", "00-tasks-1"],
                ):
                    with self.assertRaises(SystemExit) as ctx:
                        runpy.run_path(f_worker_str, run_name="__main__")
                    self.assertEqual(ctx.exception.code, 0)
                    mock_subproc.assert_not_called()
                    mock_popen.assert_not_called()

    def testInstalledAllocationKeepsRuntimeAndArtifactLayoutsSeparate(self) -> None:
        """Asserts installed worker passes RuntimeLayout.asset_root only as resource input and no resource layout as f_layout (F-02)."""
        f_stage_dir = os.path.join(self.m_temp_dir, "stage")
        f_pkg_dir = os.path.join(f_stage_dir, "share", "lsmio", "python", "lsmiotool")
        f_lib_dir = os.path.join(f_pkg_dir, "lib")
        os.makedirs(f_lib_dir, exist_ok=True)

        # Copy actual lsmiotool python files to satisfy InstalledPackageValidator
        f_src_tool_dir = Path(__file__).resolve().parents[2]
        shutil.copyfile(str(f_src_tool_dir / "__init__.py"), os.path.join(f_pkg_dir, "__init__.py"))
        for f_file in (f_src_tool_dir / "lib").glob("*.py"):
            shutil.copyfile(str(f_file), os.path.join(f_lib_dir, f_file.name))

        # Create VERSION file
        with open(os.path.join(f_pkg_dir, "VERSION"), "w", encoding="utf-8") as f_f:
            f_f.write("0.2.0\n")

        # Create etc directory with environments.json
        f_etc_dir = os.path.join(f_stage_dir, "share", "lsmio", "etc")
        os.makedirs(f_etc_dir, exist_ok=True)
        shutil.copyfile(str(f_src_tool_dir / "etc" / "environments.json"), os.path.join(f_etc_dir, "environments.json"))

        # Create lmp-reaxff assets directory
        f_assets_dir = os.path.join(f_stage_dir, "share", "lsmio", "lmp-reaxff")
        os.makedirs(f_assets_dir, exist_ok=True)
        for f_asset in ("in.reaxc.hns", "data.hns-equil", "ffield.reax.hns"):
            with open(os.path.join(f_assets_dir, f_asset), "w", encoding="utf-8") as f_f:
                f_f.write(f"# asset {f_asset}\n")

        # Create staged worker binary from template
        f_libexec_dir = os.path.join(f_stage_dir, "libexec", "lsmio")
        os.makedirs(f_libexec_dir, exist_ok=True)
        f_inst_worker = os.path.join(f_libexec_dir, "lsmiotool-worker")

        f_tmpl_path = str(f_src_tool_dir / "lsmiotool-worker-installed.in")
        with open(f_tmpl_path, "r", encoding="utf-8") as f_f:
            f_tmpl = f_f.read()

        f_configured_worker = (
            f_tmpl
            .replace("@REL_LIBEXEC_TO_PYTHON@", "../../share/lsmio/python")
            .replace("@REL_LIBEXEC_TO_PROFILE@", "../../share/lsmio/etc/environments.json")
            .replace("@REL_LIBEXEC_TO_ETC@", "../../share/lsmio/etc")
            .replace("@REL_LIBEXEC_TO_ASSETS@", "../../share/lsmio/lmp-reaxff")
            .replace("@REL_LIBEXEC_TO_WORKER@", "lsmiotool-worker")
            .replace("@REL_LIBEXEC_TO_VERSION@", "../../share/lsmio/python/lsmiotool/VERSION")
        )
        with open(f_inst_worker, "w", encoding="utf-8") as f_f:
            f_f.write(f_configured_worker)
        os.chmod(f_inst_worker, 0o755)

        # 1. Assert runtime layout properties
        f_rel_layout = InstallRelativeLayout(
            f_package_root="../../share/lsmio/python",
            f_profile_file="../../share/lsmio/etc/environments.json",
            f_asset_root="../../share/lsmio/lmp-reaxff",
            f_worker_executable="lsmiotool-worker",
            f_version_file="../../share/lsmio/python/lsmiotool/VERSION",
        )
        f_runtime_layout = ResourceLocator.forInstalled(f_inst_worker, f_rel_layout)
        self.assertTrue(f_runtime_layout.is_installed)
        self.assertEqual(f_runtime_layout.execution_mode, ExecutionMode.INSTALLED)
        self.assertEqual(f_runtime_layout.asset_root, os.path.normpath(f_assets_dir))
        self.assertEqual(f_runtime_layout.worker_executable, os.path.normpath(f_inst_worker))
        self.assertFalse(hasattr(f_runtime_layout, "runRoot"))
        self.assertFalse(hasattr(f_runtime_layout, "benchmarkRoot"))

        # 2. Run allocation mode with mock AllocationController and verify kwargs
        f_captured_alloc_kwargs = []

        class MockAllocationController:
            def __init__(self, *f_args, **f_kwargs):
                f_captured_alloc_kwargs.append(f_kwargs)

            def run(self, *f_args, **f_kwargs):
                return 0

        with patch("lsmiotool.lib.worker.AllocationController", MockAllocationController):
            with patch.object(
                sys,
                "argv",
                [f_inst_worker, "allocation", "/path/to/manifest.json", "00-tasks-1"],
            ):
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_inst_worker, run_name="__main__")
                self.assertEqual(ctx.exception.code, 0)
                self.assertEqual(len(f_captured_alloc_kwargs), 1)
                f_kw = f_captured_alloc_kwargs[0]
                self.assertEqual(f_kw.get("f_worker_executable"), os.path.abspath(f_inst_worker))
                self.assertEqual(f_kw.get("f_asset_source"), os.path.normpath(f_assets_dir))
                self.assertIsNone(
                    f_kw.get("f_layout"),
                    "AllocationController must receive f_layout=None from installed worker (F-02)",
                )

        # 3. Run rank mode with mock RankWorker and verify initialization
        f_captured_rank_instances = []

        class MockRankWorker:
            def __init__(self, *f_args, **f_kwargs):
                f_captured_rank_instances.append((f_args, f_kwargs))

            def run(self, *f_args, **f_kwargs):
                return 0

        with patch("lsmiotool.lib.worker.RankWorker", MockRankWorker):
            with patch.object(
                sys,
                "argv",
                [f_inst_worker, "rank", "/path/to/manifest.json", "00-tasks-1", "c16_b8M"],
            ):
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(f_inst_worker, run_name="__main__")
                self.assertEqual(ctx.exception.code, 0)
                self.assertEqual(len(f_captured_rank_instances), 1)
                f_r_args, f_r_kwargs = f_captured_rank_instances[0]
                self.assertEqual(len(f_r_args), 0)
                self.assertEqual(len(f_r_kwargs), 0)

        # 4. Prove no duck-typing / cross-fallback between RuntimeLayout and ArtifactLayout
        from lsmiotool.lib.artifacts import ArtifactLayout
        with self.assertRaises(AttributeError):
            _ = f_runtime_layout.runRoot  # type: ignore
        with self.assertRaises(AttributeError):
            _ = f_runtime_layout.benchmarkRoot  # type: ignore

        f_bench_root = os.path.join(self.m_temp_dir, "benchmarks")
        f_art_layout = ArtifactLayout(f_bench_root, "test-run-123")
        self.assertFalse(hasattr(f_art_layout, "asset_root"))
        self.assertFalse(hasattr(f_art_layout, "package_root"))
        self.assertFalse(hasattr(f_art_layout, "profile_file"))
        self.assertFalse(hasattr(f_art_layout, "worker_executable"))

    def testRealSourceWorkerSubprocessFromUnrelatedCwdHomeWithDecoys(self) -> None:
        """Chunk 020: Invokes the real source lsmiotool-worker script as a subprocess from an unrelated CWD/HOME with decoys, verifying arity and failure handling."""
        f_worker_str = str(self.m_worker_executable)
        f_unrelated_cwd = os.path.join(self.m_temp_dir, "real_worker_cwd")
        f_unrelated_home = os.path.join(self.m_temp_dir, "real_worker_home")
        os.makedirs(f_unrelated_cwd, exist_ok=True)
        os.makedirs(f_unrelated_home, exist_ok=True)

        # Plant decoy files
        for f_dir in (f_unrelated_cwd, f_unrelated_home):
            with open(os.path.join(f_dir, "manifest.json"), "w", encoding="utf-8") as f_f:
                f_f.write("decoy\n")

        f_env = dict(os.environ)
        f_env["HOME"] = f_unrelated_home

        # 1. Zero arguments -> exit 1
        f_p1 = subprocess.run([sys.executable, f_worker_str], cwd=f_unrelated_cwd, env=f_env, capture_output=True, text=True)
        self.assertEqual(f_p1.returncode, 1)

        # 2. Allocation with insufficient arguments -> exit 2
        f_p2 = subprocess.run([sys.executable, f_worker_str, "allocation"], cwd=f_unrelated_cwd, env=f_env, capture_output=True, text=True)
        self.assertEqual(f_p2.returncode, 2)

        # 3. Rank with insufficient arguments -> exit 2
        f_p3 = subprocess.run([sys.executable, f_worker_str, "rank"], cwd=f_unrelated_cwd, env=f_env, capture_output=True, text=True)
        self.assertEqual(f_p3.returncode, 2)

        # 4. Unknown mode -> exit 1
        f_p4 = subprocess.run([sys.executable, f_worker_str, "invalid_mode"], cwd=f_unrelated_cwd, env=f_env, capture_output=True, text=True)
        self.assertEqual(f_p4.returncode, 1)

        # 5. Non-existent manifest -> exit 1
        f_p5 = subprocess.run(
            [sys.executable, f_worker_str, "allocation", "/nonexistent/manifest.json", "00-tasks-1"],
            cwd=f_unrelated_cwd,
            env=f_env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(f_p5.returncode, 1)

        # Assert no mutations occurred in decoy cwd/home
        self.assertEqual(os.listdir(f_unrelated_cwd), ["manifest.json"])
        self.assertEqual(os.listdir(f_unrelated_home), ["manifest.json"])

