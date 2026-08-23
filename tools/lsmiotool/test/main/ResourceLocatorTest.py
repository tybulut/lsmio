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

import builtins
import os
import pathlib
import shutil
import tempfile
import unittest
from unittest.mock import patch

from lsmiotool.lib.resources import (
    ExecutionMode,
    InstallRelativeLayout,
    LayoutConfigurationError,
    ResourceLocator,
    RuntimeLayout,
)


class ResourceLocatorTest(unittest.TestCase):
    """Unit tests verifying RuntimeLayout, InstallRelativeLayout, and ResourceLocator contracts."""

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.mkdtemp(prefix="lsmiotool-res-test-")
        self.m_original_cwd = os.getcwd()

    def tearDown(self) -> None:
        os.chdir(self.m_original_cwd)
        shutil.rmtree(self.m_temp_dir, ignore_errors=True)

    def _createSampleInstalledLayout(self) -> InstallRelativeLayout:
        return InstallRelativeLayout(
            f_package_root="../share/lsmio/python",
            f_profile_file="../share/lsmio/python/lsmiotool/etc/environments.json",
            f_asset_root="../share/lsmio/lmp-reaxff",
            f_worker_executable="../libexec/lsmio/lsmiotool-worker",
            f_version_file="../share/lsmio/python/VERSION",
        )

    def testSourceLayoutExactCheckedInPaths(self) -> None:
        """Validates exact five-path source layout across public, private worker, spaces, and relative entries."""
        # Public source entry
        f_public_entry = "/mock/repo/tools/lsmiotool/lsmiotool"
        f_layout1 = ResourceLocator.forSource(f_public_entry)

        self.assertEqual(f_layout1.execution_mode, ExecutionMode.SOURCE)
        self.assertEqual(f_layout1.executionMode, ExecutionMode.SOURCE)
        self.assertTrue(f_layout1.is_source)
        self.assertTrue(f_layout1.isSource)
        self.assertFalse(f_layout1.is_installed)
        self.assertFalse(f_layout1.isInstalled)
        self.assertEqual(f_layout1.package_root, "/mock/repo/tools/lsmiotool")
        self.assertEqual(f_layout1.packageRoot, "/mock/repo/tools/lsmiotool")
        self.assertEqual(f_layout1.profile_file, "/mock/repo/tools/lsmiotool/etc/environments.json")
        self.assertEqual(f_layout1.profileFile, "/mock/repo/tools/lsmiotool/etc/environments.json")
        self.assertEqual(f_layout1.asset_root, "/mock/repo/tools/bmtool/lmp-reaxff")
        self.assertEqual(f_layout1.assetRoot, "/mock/repo/tools/bmtool/lmp-reaxff")
        self.assertEqual(f_layout1.worker_executable, "/mock/repo/tools/lsmiotool/lsmiotool-worker")
        self.assertEqual(f_layout1.workerExecutable, "/mock/repo/tools/lsmiotool/lsmiotool-worker")
        self.assertEqual(f_layout1.version_file, "/mock/repo/VERSION")
        self.assertEqual(f_layout1.versionFile, "/mock/repo/VERSION")

        # Private source worker entry
        f_private_entry = "/mock/repo/tools/lsmiotool/lsmiotool-worker"
        f_layout2 = ResourceLocator.forSource(f_private_entry)
        self.assertEqual(f_layout1, f_layout2)

        # Package directory entry
        f_pkg_entry = "/mock/repo/tools/lsmiotool"
        f_layout3 = ResourceLocator.forSource(f_pkg_entry)
        self.assertEqual(f_layout1, f_layout3)

        # Path with spaces
        f_spaces_entry = "/mock path/with spaces/repo/tools/lsmiotool/lsmiotool"
        f_layout_spaces = ResourceLocator.forSource(f_spaces_entry)
        self.assertEqual(f_layout_spaces.package_root, "/mock path/with spaces/repo/tools/lsmiotool")
        self.assertEqual(f_layout_spaces.profile_file, "/mock path/with spaces/repo/tools/lsmiotool/etc/environments.json")
        self.assertEqual(f_layout_spaces.asset_root, "/mock path/with spaces/repo/tools/bmtool/lmp-reaxff")
        self.assertEqual(f_layout_spaces.worker_executable, "/mock path/with spaces/repo/tools/lsmiotool/lsmiotool-worker")
        self.assertEqual(f_layout_spaces.version_file, "/mock path/with spaces/repo/VERSION")

        # Relative invocation path
        f_orig_cwd = os.getcwd()
        try:
            os.chdir(self.m_temp_dir)
            f_cur_cwd = os.getcwd()
            f_rel_entry = "./tools/lsmiotool/lsmiotool"
            f_layout_rel = ResourceLocator.forSource(f_rel_entry)
            self.assertEqual(f_layout_rel.package_root, os.path.normpath(os.path.join(f_cur_cwd, "tools/lsmiotool")))
            self.assertEqual(f_layout_rel.worker_executable, os.path.normpath(os.path.join(f_cur_cwd, "tools/lsmiotool/lsmiotool-worker")))
        finally:
            os.chdir(f_orig_cwd)

    def testExactSourceLayout(self) -> None:
        """Alias preserving testExactSourceLayout naming from initial plan."""
        self.testSourceLayoutExactCheckedInPaths()

    def testInstalledUsesOnlyAnchorAndConstants(self) -> None:
        """Validates exact constructed paths for installed layout using anchor and relative layout."""
        # Standard GNUInstallDirs public wrapper
        f_public_wrapper = "/usr/local/bin/lsmiotool"
        f_rel_layout = self._createSampleInstalledLayout()
        f_layout = ResourceLocator.forInstalled(f_public_wrapper, f_rel_layout)

        self.assertEqual(f_layout.execution_mode, ExecutionMode.INSTALLED)
        self.assertTrue(f_layout.is_installed)
        self.assertTrue(f_layout.isInstalled)
        self.assertFalse(f_layout.is_source)
        self.assertFalse(f_layout.isSource)
        self.assertEqual(f_layout.package_root, "/usr/local/share/lsmio/python")
        self.assertEqual(f_layout.profile_file, "/usr/local/share/lsmio/python/lsmiotool/etc/environments.json")
        self.assertEqual(f_layout.asset_root, "/usr/local/share/lsmio/lmp-reaxff")
        self.assertEqual(f_layout.worker_executable, "/usr/local/libexec/lsmio/lsmiotool-worker")
        self.assertEqual(f_layout.version_file, "/usr/local/share/lsmio/python/VERSION")

        # Private wrapper with deeper anchor
        f_private_wrapper = "/opt/lsmio/libexec/lsmio/lsmiotool-worker"
        f_private_rel_layout = InstallRelativeLayout(
            f_package_root="../../share/lsmio/python",
            f_profile_file="../../share/lsmio/python/lsmiotool/etc/environments.json",
            f_asset_root="../../share/lsmio/lmp-reaxff",
            f_worker_executable="lsmiotool-worker",
            f_version_file="../../share/lsmio/python/VERSION",
        )
        f_layout_private = ResourceLocator.forInstalled(f_private_wrapper, f_private_rel_layout)
        self.assertEqual(f_layout_private.execution_mode, ExecutionMode.INSTALLED)
        self.assertEqual(f_layout_private.package_root, "/opt/lsmio/share/lsmio/python")
        self.assertEqual(f_layout_private.profile_file, "/opt/lsmio/share/lsmio/python/lsmiotool/etc/environments.json")
        self.assertEqual(f_layout_private.asset_root, "/opt/lsmio/share/lsmio/lmp-reaxff")
        self.assertEqual(f_layout_private.worker_executable, "/opt/lsmio/libexec/lsmio/lsmiotool-worker")
        self.assertEqual(f_layout_private.version_file, "/opt/lsmio/share/lsmio/python/VERSION")

        # Non-default GNUInstallDirs
        f_custom_wrapper = "/custom/prefix/custom_bin/lsmiotool"
        f_custom_rel = InstallRelativeLayout(
            f_package_root="../custom_data/python",
            f_profile_file="../custom_data/python/lsmiotool/etc/environments.json",
            f_asset_root="../custom_data/lmp-reaxff",
            f_worker_executable="../custom_exec/lsmiotool-worker",
            f_version_file="../custom_data/python/VERSION",
        )
        f_layout_custom = ResourceLocator.forInstalled(f_custom_wrapper, f_custom_rel)
        self.assertEqual(f_layout_custom.package_root, "/custom/prefix/custom_data/python")
        self.assertEqual(f_layout_custom.worker_executable, "/custom/prefix/custom_exec/lsmiotool-worker")

    def testSourceInstalledNeverCrossFallback(self) -> None:
        """Proves zero fallback between source and installed modes."""
        # Create a real directory that looks like a source checkout in temp_dir
        f_fake_repo = os.path.join(self.m_temp_dir, "fake_repo")
        f_fake_source_pkg = os.path.join(f_fake_repo, "tools", "lsmiotool")
        os.makedirs(f_fake_source_pkg, exist_ok=True)

        # Call forInstalled on an anchor that does NOT exist on disk
        f_installed_entry = "/opt/never_installed/bin/lsmiotool"
        f_rel_layout = self._createSampleInstalledLayout()
        f_installed_layout = ResourceLocator.forInstalled(f_installed_entry, f_rel_layout)

        # Asserts it stays strictly in installed mode and does NOT fall back to fake_repo
        self.assertEqual(f_installed_layout.execution_mode, ExecutionMode.INSTALLED)
        self.assertTrue(f_installed_layout.package_root.startswith("/opt/never_installed"))
        self.assertNotIn("fake_repo", f_installed_layout.package_root)

        # Call forSource on a non-existent source entry while an installed tree exists
        f_nonexistent_source = "/opt/nonexistent_src/tools/lsmiotool/lsmiotool"
        f_source_layout = ResourceLocator.forSource(f_nonexistent_source)
        self.assertEqual(f_source_layout.execution_mode, ExecutionMode.SOURCE)
        self.assertTrue(f_source_layout.package_root.startswith("/opt/nonexistent_src"))
        self.assertNotIn("never_installed", f_source_layout.package_root)

    def testSourceConstructionAllowsNotYetExistingConsumerPath(self) -> None:
        """Verifies path construction succeeds on non-existent paths without disk dependencies."""
        f_nonexistent_source = "/does/not/exist/anywhere/tools/lsmiotool/lsmiotool"
        f_source_layout = ResourceLocator.forSource(f_nonexistent_source)
        self.assertEqual(f_source_layout.package_root, "/does/not/exist/anywhere/tools/lsmiotool")
        self.assertEqual(f_source_layout.profile_file, "/does/not/exist/anywhere/tools/lsmiotool/etc/environments.json")
        self.assertEqual(f_source_layout.asset_root, "/does/not/exist/anywhere/tools/bmtool/lmp-reaxff")
        self.assertEqual(f_source_layout.worker_executable, "/does/not/exist/anywhere/tools/lsmiotool/lsmiotool-worker")
        self.assertEqual(f_source_layout.version_file, "/does/not/exist/anywhere/VERSION")

    def testReturnsNonexistentConstructedPathsWithoutFallback(self) -> None:
        """Verifies path construction succeeds on non-existent paths without disk dependencies."""
        self.testSourceConstructionAllowsNotYetExistingConsumerPath()

        f_nonexistent_installed = "/completely/fake/install/bin/lsmiotool"
        f_installed_layout = ResourceLocator.forInstalled(
            f_nonexistent_installed,
            self._createSampleInstalledLayout(),
        )
        self.assertEqual(f_installed_layout.package_root, "/completely/fake/install/share/lsmio/python")
        self.assertEqual(f_installed_layout.worker_executable, "/completely/fake/install/libexec/lsmio/lsmiotool-worker")

    def testNoFilesystemValidationCallsIncludingResolveStatExistsOrSymlink(self) -> None:
        """Spies on all filesystem introspection functions to prove ZERO calls occur during layout derivation."""
        with patch("os.stat") as f_mock_stat, patch("os.lstat") as f_mock_lstat, patch(
            "os.path.exists"
        ) as f_mock_exists, patch("os.path.isfile") as f_mock_isfile, patch(
            "os.path.isdir"
        ) as f_mock_isdir, patch(
            "os.path.islink"
        ) as f_mock_islink, patch(
            "os.access"
        ) as f_mock_access, patch(
            "builtins.open"
        ) as f_mock_open, patch.object(
            pathlib.Path, "stat"
        ) as f_mock_path_stat, patch.object(
            pathlib.Path, "lstat"
        ) as f_mock_path_lstat, patch.object(
            pathlib.Path, "exists"
        ) as f_mock_path_exists, patch.object(
            pathlib.Path, "is_file"
        ) as f_mock_path_isfile, patch.object(
            pathlib.Path, "is_dir"
        ) as f_mock_path_isdir, patch.object(
            pathlib.Path, "is_symlink"
        ) as f_mock_path_issymlink, patch.object(
            pathlib.Path, "resolve"
        ) as f_mock_path_resolve:

            # Execute forSource
            f_source_layout = ResourceLocator.forSource("/mock/repo/tools/lsmiotool/lsmiotool")
            self.assertIsNotNone(f_source_layout)

            # Execute forInstalled
            f_rel_layout = self._createSampleInstalledLayout()
            f_installed_layout = ResourceLocator.forInstalled("/usr/local/bin/lsmiotool", f_rel_layout)
            self.assertIsNotNone(f_installed_layout)

            # Assert ZERO calls to all filesystem introspection functions
            f_mock_stat.assert_not_called()
            f_mock_lstat.assert_not_called()
            f_mock_exists.assert_not_called()
            f_mock_isfile.assert_not_called()
            f_mock_isdir.assert_not_called()
            f_mock_islink.assert_not_called()
            f_mock_access.assert_not_called()
            f_mock_open.assert_not_called()
            f_mock_path_stat.assert_not_called()
            f_mock_path_lstat.assert_not_called()
            f_mock_path_exists.assert_not_called()
            f_mock_path_isfile.assert_not_called()
            f_mock_path_isdir.assert_not_called()
            f_mock_path_issymlink.assert_not_called()
            f_mock_path_resolve.assert_not_called()

    def testSourceLayoutIgnoresCwdHomeAndDecoys(self) -> None:
        """Verifies source layout construction is completely isolated from cwd, HOME, and decoy files."""
        f_decoy_cwd = os.path.join(self.m_temp_dir, "decoy_cwd")
        f_decoy_home = os.path.join(self.m_temp_dir, "decoy_home")
        os.makedirs(os.path.join(f_decoy_cwd, "tools", "lsmiotool"), exist_ok=True)
        os.makedirs(f_decoy_home, exist_ok=True)

        # Place decoy files in cwd and home
        with open(os.path.join(f_decoy_cwd, "VERSION"), "w", encoding="utf-8") as f_f:
            f_f.write("decoy_cwd_version\n")
        with open(os.path.join(f_decoy_home, "VERSION"), "w", encoding="utf-8") as f_f:
            f_f.write("decoy_home_version\n")

        f_orig_env_home = os.environ.get("HOME")
        f_orig_cwd = os.getcwd()
        try:
            os.environ["HOME"] = f_decoy_home
            os.chdir(f_decoy_cwd)

            # Call forSource on an explicit path
            f_layout = ResourceLocator.forSource("/real/repo/tools/lsmiotool/lsmiotool")
            self.assertEqual(f_layout.package_root, "/real/repo/tools/lsmiotool")
            self.assertEqual(f_layout.profile_file, "/real/repo/tools/lsmiotool/etc/environments.json")
            self.assertEqual(f_layout.asset_root, "/real/repo/tools/bmtool/lmp-reaxff")
            self.assertEqual(f_layout.worker_executable, "/real/repo/tools/lsmiotool/lsmiotool-worker")
            self.assertEqual(f_layout.version_file, "/real/repo/VERSION")
            self.assertNotIn("decoy", f_layout.package_root)
            self.assertNotIn("decoy", f_layout.worker_executable)
            self.assertNotIn("decoy", f_layout.version_file)
        finally:
            os.chdir(f_orig_cwd)
            if f_orig_env_home is not None:
                os.environ["HOME"] = f_orig_env_home
            else:
                os.environ.pop("HOME", None)

    def testIndependentOfCwd(self) -> None:
        """Asserts output is invariant across arbitrary cwd changes."""
        f_source_entry = "/var/custom/repo/tools/lsmiotool/lsmiotool"
        f_installed_entry = "/usr/local/bin/lsmiotool"
        f_rel_layout = self._createSampleInstalledLayout()

        # Call in original cwd
        f_src_layout1 = ResourceLocator.forSource(f_source_entry)
        f_inst_layout1 = ResourceLocator.forInstalled(f_installed_entry, f_rel_layout)

        # Change cwd to temporary directory
        os.chdir(self.m_temp_dir)
        f_src_layout2 = ResourceLocator.forSource(f_source_entry)
        f_inst_layout2 = ResourceLocator.forInstalled(f_installed_entry, f_rel_layout)

        # Change cwd to /tmp or /var
        if os.path.exists("/tmp"):
            os.chdir("/tmp")
            f_src_layout3 = ResourceLocator.forSource(f_source_entry)
            f_inst_layout3 = ResourceLocator.forInstalled(f_installed_entry, f_rel_layout)
            self.assertEqual(f_src_layout1, f_src_layout3)
            self.assertEqual(f_inst_layout1, f_inst_layout3)

        self.assertEqual(f_src_layout1, f_src_layout2)
        self.assertEqual(f_inst_layout1, f_inst_layout2)

    def testLexicalContainmentRejectsAbsoluteAndDotDotConstants(self) -> None:
        """Asserts rejection of absolute constants and .. escape attempts."""
        # Absolute path in InstallRelativeLayout
        with self.assertRaises(LayoutConfigurationError):
            InstallRelativeLayout(
                f_package_root="/usr/share/lsmio/python",
                f_profile_file="../share/lsmio/python/lsmiotool/etc/environments.json",
                f_asset_root="../share/lsmio/lmp-reaxff",
                f_worker_executable="../libexec/lsmio/lsmiotool-worker",
                f_version_file="../share/lsmio/python/VERSION",
            )

        with self.assertRaises(LayoutConfigurationError):
            InstallRelativeLayout(
                f_package_root="../share/lsmio/python",
                f_profile_file="/etc/environments.json",
                f_asset_root="../share/lsmio/lmp-reaxff",
                f_worker_executable="../libexec/lsmio/lsmiotool-worker",
                f_version_file="../share/lsmio/python/VERSION",
            )

        # Empty string or whitespace in InstallRelativeLayout
        with self.assertRaises(LayoutConfigurationError):
            InstallRelativeLayout(
                f_package_root="",
                f_profile_file="etc/environments.json",
                f_asset_root="lmp-reaxff",
                f_worker_executable="lsmiotool-worker",
                f_version_file="VERSION",
            )

        with self.assertRaises(LayoutConfigurationError):
            InstallRelativeLayout(
                f_package_root="   ",
                f_profile_file="etc/environments.json",
                f_asset_root="lmp-reaxff",
                f_worker_executable="lsmiotool-worker",
                f_version_file="VERSION",
            )

        # NUL byte in InstallRelativeLayout
        with self.assertRaises(LayoutConfigurationError):
            InstallRelativeLayout(
                f_package_root="share/lsmio\0/python",
                f_profile_file="etc/environments.json",
                f_asset_root="lmp-reaxff",
                f_worker_executable="lsmiotool-worker",
                f_version_file="VERSION",
            )

        # Traversal escape above root via .. in forInstalled
        f_escaping_rel = InstallRelativeLayout(
            f_package_root="../../../../../../../../../../etc/shadow",
            f_profile_file="../share/lsmio/python/lsmiotool/etc/environments.json",
            f_asset_root="../share/lsmio/lmp-reaxff",
            f_worker_executable="../libexec/lsmio/lsmiotool-worker",
            f_version_file="../share/lsmio/python/VERSION",
        )
        with self.assertRaises(LayoutConfigurationError):
            ResourceLocator.forInstalled("/usr/bin/lsmiotool", f_escaping_rel)

        # Traversal escape from a shallow anchor
        f_shallow_escape = InstallRelativeLayout(
            f_package_root="../../escape",
            f_profile_file="etc/environments.json",
            f_asset_root="lmp-reaxff",
            f_worker_executable="lsmiotool-worker",
            f_version_file="VERSION",
        )
        with self.assertRaises(LayoutConfigurationError):
            ResourceLocator.forInstalled("/bin/lsmiotool", f_shallow_escape)

    def testLayoutImmutability(self) -> None:
        """Asserts RuntimeLayout and InstallRelativeLayout are immutable."""
        f_rel = self._createSampleInstalledLayout()
        with self.assertRaises((AttributeError, TypeError)):
            f_rel.m_package_root = "/new/path"  # type: ignore
        with self.assertRaises((AttributeError, TypeError)):
            f_rel.package_root = "/new/path"  # type: ignore
        with self.assertRaises((AttributeError, TypeError)):
            del f_rel.m_package_root  # type: ignore

        f_layout = ResourceLocator.forSource("/mock/repo/tools/lsmiotool/lsmiotool")
        with self.assertRaises((AttributeError, TypeError)):
            f_layout.m_package_root = "/new/path"  # type: ignore
        with self.assertRaises((AttributeError, TypeError)):
            f_layout.package_root = "/new/path"  # type: ignore
        with self.assertRaises((AttributeError, TypeError)):
            del f_layout.m_package_root  # type: ignore

    def testLayoutEqualityAndRepr(self) -> None:
        """Asserts __eq__, __repr__, __hash__, and toDict() for layouts."""
        f_rel1 = self._createSampleInstalledLayout()
        f_rel2 = self._createSampleInstalledLayout()
        f_rel3 = InstallRelativeLayout(
            f_package_root="../other/python",
            f_profile_file="../share/lsmio/python/lsmiotool/etc/environments.json",
            f_asset_root="../share/lsmio/lmp-reaxff",
            f_worker_executable="../libexec/lsmio/lsmiotool-worker",
            f_version_file="../share/lsmio/python/VERSION",
        )

        self.assertEqual(f_rel1, f_rel2)
        self.assertNotEqual(f_rel1, f_rel3)
        self.assertNotEqual(f_rel1, "not_a_layout")
        self.assertEqual(hash(f_rel1), hash(f_rel2))
        self.assertIn("InstallRelativeLayout", repr(f_rel1))
        self.assertEqual(f_rel1.toDict()["package_root"], "../share/lsmio/python")

        f_layout1 = ResourceLocator.forSource("/mock/repo/tools/lsmiotool/lsmiotool")
        f_layout2 = ResourceLocator.forSource("/mock/repo/tools/lsmiotool/lsmiotool")
        f_layout3 = ResourceLocator.forSource("/other/repo/tools/lsmiotool/lsmiotool")

        self.assertEqual(f_layout1, f_layout2)
        self.assertNotEqual(f_layout1, f_layout3)
        self.assertNotEqual(f_layout1, 42)
        self.assertEqual(hash(f_layout1), hash(f_layout2))
        self.assertIn("RuntimeLayout", repr(f_layout1))

        f_dict = f_layout1.toDict()
        self.assertEqual(f_dict["execution_mode"], "source")
        self.assertEqual(f_dict["package_root"], "/mock/repo/tools/lsmiotool")

    def testInvalidArguments(self) -> None:
        """Asserts invalid arguments to ResourceLocator and RuntimeLayout raise LayoutConfigurationError."""
        # Non-string or empty source entry
        with self.assertRaises(LayoutConfigurationError):
            ResourceLocator.forSource("")  # type: ignore
        with self.assertRaises(LayoutConfigurationError):
            ResourceLocator.forSource(None)  # type: ignore
        with self.assertRaises(LayoutConfigurationError):
            ResourceLocator.forSource(123)  # type: ignore
        with self.assertRaises(LayoutConfigurationError):
            ResourceLocator.forSource("/repo/tools/lsmiotool\0/lsmiotool")

        # Invalid installed entry or layout
        with self.assertRaises(LayoutConfigurationError):
            ResourceLocator.forInstalled("", self._createSampleInstalledLayout())
        with self.assertRaises(LayoutConfigurationError):
            ResourceLocator.forInstalled(None, self._createSampleInstalledLayout())  # type: ignore
        with self.assertRaises(LayoutConfigurationError):
            ResourceLocator.forInstalled("/usr/bin/lsmiotool", None)  # type: ignore
        with self.assertRaises(LayoutConfigurationError):
            ResourceLocator.forInstalled("/usr/bin/lsmiotool\0", self._createSampleInstalledLayout())

        # RuntimeLayout with non-absolute path
        with self.assertRaises(LayoutConfigurationError):
            RuntimeLayout(
                f_execution_mode=ExecutionMode.SOURCE,
                f_package_root="relative/path",
                f_profile_file="/etc/environments.json",
                f_asset_root="/lmp-reaxff",
                f_worker_executable="/worker",
                f_version_file="/VERSION",
            )

        # RuntimeLayout with invalid ExecutionMode
        with self.assertRaises(LayoutConfigurationError):
            RuntimeLayout(
                f_execution_mode="invalid_mode",  # type: ignore
                f_package_root="/package",
                f_profile_file="/etc/environments.json",
                f_asset_root="/lmp-reaxff",
                f_worker_executable="/worker",
                f_version_file="/VERSION",
            )
