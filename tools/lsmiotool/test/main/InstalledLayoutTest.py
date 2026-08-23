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

"""Comprehensive unit and layout contract tests for installed packages, wrappers, and InstalledPackageValidator."""

import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
from typing import Dict, List, Optional
import unittest
from unittest.mock import MagicMock, patch

from lsmiotool.lib.cli import (
    InstalledPackageValidator,
    PackageValidationError,
)
from lsmiotool.lib.resources import (
    ExecutionMode,
    InstallRelativeLayout,
    LayoutConfigurationError,
    ResourceLocator,
    RuntimeLayout,
)


class InstalledLayoutTest(unittest.TestCase):
    """Test suite for InstalledPackageValidator, relative layouts, and installed wrapper contracts."""

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.mkdtemp(prefix="lsmiotool-inst-layout-test-")
        self.m_original_cwd = os.getcwd()

    def tearDown(self) -> None:
        os.chdir(self.m_original_cwd)
        shutil.rmtree(self.m_temp_dir, ignore_errors=True)

    def _createValidInstalledPackage(self, f_root_dir: Optional[str] = None) -> str:
        """Create a mock installed package directory matching the full installed file set."""
        f_pkg_dir = f_root_dir if f_root_dir is not None else os.path.join(self.m_temp_dir, "share", "lsmio", "python", "lsmiotool")
        f_lib_dir = os.path.join(f_pkg_dir, "lib")
        os.makedirs(f_lib_dir, exist_ok=True)

        # Create package root files
        with open(os.path.join(f_pkg_dir, "__init__.py"), "w", encoding="utf-8") as f_f:
            f_f.write('"""lsmiotool package."""\n')

        # Create core required lib module files
        for f_mod in ("__init__.py", "cli.py", "main.py", "run.py", "worker.py", "version.py", "resources.py"):
            with open(os.path.join(f_lib_dir, f_mod), "w", encoding="utf-8") as f_f:
                f_f.write(f'"""Mock {f_mod}."""\n')

        return f_pkg_dir

    def testInstalledPackageValidatorAcceptsValidLayout(self) -> None:
        """Validates that a correctly populated installed package directory passes validation."""
        f_pkg_dir = self._createValidInstalledPackage()
        f_validated = InstalledPackageValidator.validate(f_pkg_dir)
        self.assertEqual(f_validated, os.path.normpath(f_pkg_dir))

        # Test instance __call__ interface
        f_inst = InstalledPackageValidator()
        self.assertEqual(f_inst(f_pkg_dir), os.path.normpath(f_pkg_dir))

        # Test Path object input
        self.assertEqual(InstalledPackageValidator.validate(Path(f_pkg_dir)), os.path.normpath(f_pkg_dir))

    def testInstalledPackageValidatorRejectsMissingRoot(self) -> None:
        """Validates that a nonexistent package root raises PackageValidationError."""
        f_nonexistent = os.path.join(self.m_temp_dir, "nonexistent", "lsmiotool")
        with self.assertRaises(PackageValidationError) as f_ctx:
            InstalledPackageValidator.validate(f_nonexistent)
        self.assertIn("does not exist", str(f_ctx.exception))

    def testInstalledPackageValidatorRejectsSymlinkRoot(self) -> None:
        """Validates that a symlinked package root directory is strictly rejected."""
        f_real_dir = self._createValidInstalledPackage(os.path.join(self.m_temp_dir, "real_pkg"))
        f_symlink_dir = os.path.join(self.m_temp_dir, "symlink_pkg")
        os.symlink(f_real_dir, f_symlink_dir)

        with self.assertRaises(PackageValidationError) as f_ctx:
            InstalledPackageValidator.validate(f_symlink_dir)
        self.assertIn("must not be a symlink", str(f_ctx.exception))

    def testInstalledPackageValidatorRejectsFileAsRoot(self) -> None:
        """Validates that a file (not a directory) passed as package root is rejected."""
        f_file_path = os.path.join(self.m_temp_dir, "fake_file.py")
        with open(f_file_path, "w", encoding="utf-8") as f_f:
            f_f.write("# not a directory\n")

        with self.assertRaises(PackageValidationError) as f_ctx:
            InstalledPackageValidator.validate(f_file_path)
        self.assertIn("must be a directory", str(f_ctx.exception))

    def testInstalledPackageValidatorRejectsMissingRequiredFiles(self) -> None:
        """Validates that missing any required module file raises PackageValidationError."""
        for f_required_file in InstalledPackageValidator.DEFAULT_REQUIRED_FILES:
            f_pkg_dir = os.path.join(self.m_temp_dir, f"test_missing_{f_required_file.replace('/', '_')}")
            self._createValidInstalledPackage(f_pkg_dir)

            # Remove the specific required file
            f_target_file = os.path.join(f_pkg_dir, f_required_file)
            os.remove(f_target_file)

            with self.assertRaises(PackageValidationError) as f_ctx:
                InstalledPackageValidator.validate(f_pkg_dir)
            self.assertIn("does not exist", str(f_ctx.exception))

    def testInstalledPackageValidatorRejectsSymlinkRequiredFile(self) -> None:
        """Validates that a symlinked module file inside the package is strictly rejected."""
        f_pkg_dir = self._createValidInstalledPackage()
        f_target_file = os.path.join(f_pkg_dir, "lib", "cli.py")
        os.remove(f_target_file)

        # Create external decoy and symlink
        f_decoy = os.path.join(self.m_temp_dir, "decoy_cli.py")
        with open(f_decoy, "w", encoding="utf-8") as f_f:
            f_f.write("# decoy\n")
        os.symlink(f_decoy, f_target_file)

        with self.assertRaises(PackageValidationError) as f_ctx:
            InstalledPackageValidator.validate(f_pkg_dir)
        self.assertIn("must not be a symlink", str(f_ctx.exception))

    def testInstalledPackageValidatorRejectsDirectoryAsRequiredFile(self) -> None:
        """Validates that a directory occupying a required file path is rejected."""
        f_pkg_dir = self._createValidInstalledPackage()
        f_target_file = os.path.join(f_pkg_dir, "lib", "main.py")
        os.remove(f_target_file)
        os.makedirs(f_target_file, exist_ok=True)

        with self.assertRaises(PackageValidationError) as f_ctx:
            InstalledPackageValidator.validate(f_pkg_dir)
        self.assertIn("must be a regular file", str(f_ctx.exception))

    def testInstalledPackageValidatorRejectsUnreadableRequiredFile(self) -> None:
        """Validates that an unreadable required file raises PackageValidationError."""
        f_pkg_dir = self._createValidInstalledPackage()
        f_target_file = os.path.join(f_pkg_dir, "lib", "run.py")

        try:
            os.chmod(f_target_file, 0)
            with self.assertRaises(PackageValidationError) as f_ctx:
                InstalledPackageValidator.validate(f_pkg_dir)
            self.assertIn("not readable", str(f_ctx.exception))
        finally:
            os.chmod(f_target_file, 0o644)

    def testInstalledPackageValidatorRejectsInvalidArguments(self) -> None:
        """Validates error handling on invalid parameter types and characters."""
        # None
        with self.assertRaises(PackageValidationError):
            InstalledPackageValidator.validate(None)  # type: ignore

        # Wrong type
        with self.assertRaises(PackageValidationError):
            InstalledPackageValidator.validate(12345)  # type: ignore

        # Empty string
        with self.assertRaises(PackageValidationError):
            InstalledPackageValidator.validate("")

        with self.assertRaises(PackageValidationError):
            InstalledPackageValidator.validate("   ")

        # NUL byte
        with self.assertRaises(PackageValidationError):
            InstalledPackageValidator.validate(f"{self.m_temp_dir}\0invalid")

        # Invalid required_files sequence type
        f_pkg_dir = self._createValidInstalledPackage()
        with self.assertRaises(PackageValidationError):
            InstalledPackageValidator.validate(f_pkg_dir, f_required_files="invalid_str")  # type: ignore

        # Empty entry in required_files
        with self.assertRaises(PackageValidationError):
            InstalledPackageValidator.validate(f_pkg_dir, f_required_files=[""])

        # NUL byte in required_files entry
        with self.assertRaises(PackageValidationError):
            InstalledPackageValidator.validate(f_pkg_dir, f_required_files=["lib/cli.py\0"])

    def testInstalledPackageValidatorNoFallbackToCwdOrHome(self) -> None:
        """Validates that validation never searches CWD, HOME, or PATH when a file is absent."""
        f_pkg_dir = self._createValidInstalledPackage()
        f_target_file = os.path.join(f_pkg_dir, "lib", "worker.py")
        os.remove(f_target_file)

        # Place decoy file in CWD
        f_cwd_decoy_dir = os.path.join(self.m_temp_dir, "cwd_work")
        os.makedirs(os.path.join(f_cwd_decoy_dir, "lib"), exist_ok=True)
        with open(os.path.join(f_cwd_decoy_dir, "lib", "worker.py"), "w", encoding="utf-8") as f_f:
            f_f.write("# decoy worker in cwd\n")

        os.chdir(f_cwd_decoy_dir)

        # Must fail without falling back to CWD
        with self.assertRaises(PackageValidationError) as f_ctx:
            InstalledPackageValidator.validate(f_pkg_dir)
        self.assertIn("worker.py", str(f_ctx.exception))

    def testConfiguredWrappersSelectInstalledOnly(self) -> None:
        """Asserts that installed wrapper templates strictly use installed mode and relative constants."""
        f_source_dir = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )

        f_public_tmpl_path = os.path.join(f_source_dir, "lsmiotool-installed.in")
        f_worker_tmpl_path = os.path.join(f_source_dir, "lsmiotool-worker-installed.in")

        self.assertTrue(os.path.isfile(f_public_tmpl_path), f"Missing public wrapper template: {f_public_tmpl_path}")
        self.assertTrue(os.path.isfile(f_worker_tmpl_path), f"Missing worker wrapper template: {f_worker_tmpl_path}")

        with open(f_public_tmpl_path, "r", encoding="utf-8") as f_f:
            f_public_content = f_f.read()

        with open(f_worker_tmpl_path, "r", encoding="utf-8") as f_f:
            f_worker_content = f_f.read()

        # Both templates must use ResourceLocator.forInstalled and InstalledPackageValidator
        self.assertIn("ResourceLocator.forInstalled", f_public_content)
        self.assertIn("InstalledPackageValidator", f_public_content)
        self.assertNotIn("ResourceLocator.forSource", f_public_content)
        self.assertNotIn("SourcePackageValidator", f_public_content)

        self.assertIn("ResourceLocator.forInstalled", f_worker_content)
        self.assertIn("InstalledPackageValidator", f_worker_content)
        self.assertNotIn("ResourceLocator.forSource", f_worker_content)
        self.assertNotIn("SourcePackageValidator", f_worker_content)

        # Assert presence of configured CMake variable placeholders
        self.assertIn("@REL_BIN_TO_PYTHON@", f_public_content)
        self.assertIn("@REL_BIN_TO_LIBEXEC_WORKER@", f_public_content)
        self.assertIn("@REL_BIN_TO_PROFILE@", f_public_content)
        self.assertIn("@REL_BIN_TO_ASSETS@", f_public_content)
        self.assertIn("@REL_BIN_TO_VERSION@", f_public_content)

        self.assertIn("@REL_LIBEXEC_TO_PYTHON@", f_worker_content)
        self.assertIn("@REL_LIBEXEC_TO_PROFILE@", f_worker_content)
        self.assertIn("@REL_LIBEXEC_TO_ASSETS@", f_worker_content)
        self.assertIn("@REL_LIBEXEC_TO_WORKER@", f_worker_content)
        self.assertIn("@REL_LIBEXEC_TO_VERSION@", f_worker_content)

    def testRelativePathResolutionForStandardAndCustomLayouts(self) -> None:
        """Validates relative path layout calculations for standard and non-standard install prefixes."""
        # Standard layout: /usr/local
        f_std_wrapper = "/usr/local/bin/lsmiotool"
        f_std_rel = InstallRelativeLayout(
            f_package_root="../share/lsmio/python",
            f_profile_file="../share/lsmio/etc/environments.json",
            f_asset_root="../share/lsmio/lmp-reaxff",
            f_worker_executable="../libexec/lsmio/lsmiotool-worker",
            f_version_file="../share/lsmio/python/lsmiotool/VERSION",
        )
        f_std_layout = ResourceLocator.forInstalled(f_std_wrapper, f_std_rel)

        self.assertEqual(f_std_layout.execution_mode, ExecutionMode.INSTALLED)
        self.assertTrue(f_std_layout.is_installed)
        self.assertFalse(f_std_layout.is_source)
        self.assertEqual(f_std_layout.package_root, "/usr/local/share/lsmio/python")
        self.assertEqual(f_std_layout.profile_file, "/usr/local/share/lsmio/etc/environments.json")
        self.assertEqual(f_std_layout.asset_root, "/usr/local/share/lsmio/lmp-reaxff")
        self.assertEqual(f_std_layout.worker_executable, "/usr/local/libexec/lsmio/lsmiotool-worker")
        self.assertEqual(f_std_layout.version_file, "/usr/local/share/lsmio/python/lsmiotool/VERSION")

        # Custom user prefix layout: /home/user/src/usr
        f_custom_wrapper = "/home/user/src/usr/bin/lsmiotool"
        f_custom_layout = ResourceLocator.forInstalled(f_custom_wrapper, f_std_rel)
        self.assertEqual(f_custom_layout.package_root, "/home/user/src/usr/share/lsmio/python")
        self.assertEqual(f_custom_layout.worker_executable, "/home/user/src/usr/libexec/lsmio/lsmiotool-worker")
        self.assertEqual(f_custom_layout.asset_root, "/home/user/src/usr/share/lsmio/lmp-reaxff")

        # Worker relative layout: /usr/local/libexec/lsmio/lsmiotool-worker
        f_worker_wrapper = "/usr/local/libexec/lsmio/lsmiotool-worker"
        f_worker_rel = InstallRelativeLayout(
            f_package_root="../../share/lsmio/python",
            f_profile_file="../../share/lsmio/etc/environments.json",
            f_asset_root="../../share/lsmio/lmp-reaxff",
            f_worker_executable="lsmiotool-worker",
            f_version_file="../../share/lsmio/python/lsmiotool/VERSION",
        )
        f_worker_layout = ResourceLocator.forInstalled(f_worker_wrapper, f_worker_rel)
        self.assertEqual(f_worker_layout.execution_mode, ExecutionMode.INSTALLED)
        self.assertEqual(f_worker_layout.package_root, "/usr/local/share/lsmio/python")
        self.assertEqual(f_worker_layout.worker_executable, "/usr/local/libexec/lsmio/lsmiotool-worker")
        self.assertEqual(f_worker_layout.asset_root, "/usr/local/share/lsmio/lmp-reaxff")
        self.assertEqual(f_worker_layout.profile_file, "/usr/local/share/lsmio/etc/environments.json")
        self.assertEqual(f_worker_layout.version_file, "/usr/local/share/lsmio/python/lsmiotool/VERSION")

    def testInstalledPublicWrapperExecutionContract(self) -> None:
        """Tests that public installed wrapper code structure dispatches correctly in installed mode."""
        f_staged_prefix = os.path.join(self.m_temp_dir, "opt", "lsmio")
        f_bin_dir = os.path.join(f_staged_prefix, "bin")
        f_share_dir = os.path.join(f_staged_prefix, "share", "lsmio")
        f_pkg_dir = self._createValidInstalledPackage(os.path.join(f_share_dir, "python", "lsmiotool"))
        os.makedirs(f_bin_dir, exist_ok=True)
        os.makedirs(os.path.join(f_share_dir, "etc"), exist_ok=True)

        # Create dummy environments.json and VERSION
        with open(os.path.join(f_pkg_dir, "VERSION"), "w", encoding="utf-8") as f_f:
            f_f.write("1.0.0\n")

        # Validate package
        f_res = InstalledPackageValidator.validate(f_pkg_dir)
        self.assertEqual(f_res, f_pkg_dir)

        # Verify layout construction
        f_wrapper_path = os.path.join(f_bin_dir, "lsmiotool")
        f_rel = InstallRelativeLayout(
            f_package_root="../share/lsmio/python",
            f_profile_file="../share/lsmio/etc/environments.json",
            f_asset_root="../share/lsmio/lmp-reaxff",
            f_worker_executable="../libexec/lsmio/lsmiotool-worker",
            f_version_file="../share/lsmio/python/lsmiotool/VERSION",
        )
        f_layout = ResourceLocator.forInstalled(f_wrapper_path, f_rel)
        self.assertTrue(f_layout.is_installed)
        self.assertEqual(f_layout.package_root, os.path.join(f_share_dir, "python"))

    def testInstalledLmpAssetsExactFilenamesAndNoAliases(self) -> None:
        """Asserts that LMP assets in source and installed layouts use exact upstream names with no renamed aliases."""
        f_source_dir = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "tools", "bmtool", "lmp-reaxff")
        )
        if os.path.isdir(f_source_dir):
            f_assets = sorted(os.listdir(f_source_dir))
            self.assertEqual(
                f_assets,
                ["data.hns-equil", "ffield.reax.hns", "in.reaxc.hns"],
                "Source LMP assets must match exact upstream filenames",
            )
            self.assertNotIn("in.reaxff.hns", f_assets)
            self.assertNotIn("data.hns", f_assets)

    def testRuntimeLayoutHasNoArtifactRole(self) -> None:
        """Asserts that RuntimeLayout has no artifact roles and ArtifactLayout has no resource roles (F-02)."""
        from lsmiotool.lib.artifacts import ArtifactLayout, ArtifactStore, validatePathContainment
        from lsmiotool.lib.evidence import EvidenceStore
        from lsmiotool.lib.worker import AllocationController, AllocationControllerError

        # 1. Create installed RuntimeLayout
        f_rel = InstallRelativeLayout(
            f_package_root="../share/lsmio/python",
            f_profile_file="../share/lsmio/etc/environments.json",
            f_asset_root="../share/lsmio/lmp-reaxff",
            f_worker_executable="../libexec/lsmio/lsmiotool-worker",
            f_version_file="../share/lsmio/python/lsmiotool/VERSION",
        )
        f_inst_layout = ResourceLocator.forInstalled("/opt/lsmio/bin/lsmiotool", f_rel)

        # 2. Create source RuntimeLayout
        f_src_worker = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "lsmiotool-worker")
        )
        f_src_layout = ResourceLocator.forSource(f_src_worker)

        # 3. Assert RuntimeLayout has no artifact attributes or methods
        f_artifact_attrs = (
            "runRoot",
            "benchmarkRoot",
            "manifestPath",
            "pointDir",
            "pointDataDir",
            "pointLogsDir",
            "pointCombinationsDir",
            "pointResultsDir",
            "pointWorkDir",
            "pointClaimsDir",
            "pointWorkerEventsDir",
            "rankDir",
            "rankCombinationDir",
            "rankResultPath",
            "rankLogPath",
            "rankClaimPath",
            "controllerResultPath",
            "outputArtifactPath",
        )
        for f_layout in (f_inst_layout, f_src_layout):
            for f_attr in f_artifact_attrs:
                self.assertFalse(
                    hasattr(f_layout, f_attr),
                    f"RuntimeLayout must NOT have artifact attribute '{f_attr}'",
                )
                with self.assertRaises(AttributeError):
                    getattr(f_layout, f_attr)

        # 4. Assert ArtifactLayout has no resource attributes or methods
        f_art_layout = ArtifactLayout("/tmp/benchmarks", "run-001")
        f_resource_attrs = (
            "package_root",
            "profile_file",
            "asset_root",
            "worker_executable",
            "version_file",
            "execution_mode",
            "is_source",
            "is_installed",
        )
        for f_attr in f_resource_attrs:
            self.assertFalse(
                hasattr(f_art_layout, f_attr),
                f"ArtifactLayout must NOT have resource attribute '{f_attr}'",
            )
            with self.assertRaises(AttributeError):
                getattr(f_art_layout, f_attr)

        # 5. Using RuntimeLayout with ArtifactStore / EvidenceStore fails closed
        from lsmiotool.lib.artifacts import ArtifactError
        with self.assertRaises((ArtifactError, AttributeError, TypeError)):
            ArtifactStore(f_inst_layout)  # type: ignore

        with self.assertRaises((ArtifactError, AttributeError, TypeError)):
            EvidenceStore(f_inst_layout)  # type: ignore

        # 6. AllocationController rejects RuntimeLayout passed as f_layout during execution
        f_controller = AllocationController(
            f_worker_executable=f_inst_layout.worker_executable,
            f_asset_source=f_inst_layout.asset_root,
            f_layout=f_inst_layout,  # Invalid layout
        )
        with self.assertRaises((AllocationControllerError, AttributeError)):
            f_controller.run(
                f_manifest_path="/nonexistent/manifest.json",
                f_point_id="00-tasks-1",
            )


if __name__ == "__main__":
    unittest.main()
