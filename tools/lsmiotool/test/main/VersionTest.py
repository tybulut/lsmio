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

import os
import pathlib
import shutil
import tempfile
import unittest
from unittest.mock import patch

import lsmiotool.lib
from lsmiotool.lib.version import VersionError, getVersion


class VersionTest(unittest.TestCase):
    """Unit tests verifying single version authority, consumer validation, and no fallback."""

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.mkdtemp(prefix="lsmiotool-ver-test-")
        self.m_original_cwd = os.getcwd()

    def tearDown(self) -> None:
        os.chdir(self.m_original_cwd)
        shutil.rmtree(self.m_temp_dir, ignore_errors=True)

    def testAuthorityIs020(self) -> None:
        """Asserts tools/lsmiotool/VERSION contains exactly '0.2.0\\n'."""
        f_version_file = (
            pathlib.Path(__file__).resolve().parent.parent.parent / "VERSION"
        )
        self.assertTrue(
            f_version_file.is_file(),
            f"Authority file not found: {f_version_file}",
        )
        with open(f_version_file, "r", encoding="utf-8") as f_f:
            f_content = f_f.read()
        self.assertEqual(f_content, "0.2.0\n")

    def testCmakeProjectVersionMatchesAuthority(self) -> None:
        """Asserts CMake project version matches authority file."""
        f_repo_root = (
            pathlib.Path(__file__).resolve().parent.parent.parent.parent.parent
        )
        f_cmake_file = f_repo_root / "CMakeLists.txt"
        self.assertTrue(
            f_cmake_file.is_file(),
            f"CMakeLists.txt not found at {f_cmake_file}",
        )
        with open(f_cmake_file, "r", encoding="utf-8") as f_f:
            f_cmake_content = f_f.read()

        self.assertIn("tools/lsmiotool/VERSION", f_cmake_content)
        self.assertIn("project(lsmio VERSION ${LSMIO_VERSION}", f_cmake_content)

        # Authority version
        f_version = getVersion()
        self.assertEqual(f_version, "0.2.0")

    def testPackageValueFromFile(self) -> None:
        """Asserts lsmiotool.lib.__version__ and VERSION match 0.2.0."""
        self.assertEqual(lsmiotool.lib.__version__, "0.2.0")
        self.assertEqual(lsmiotool.lib.VERSION, "0.2.0")

    def testConsumerRejectsMalformedMissingSymlinkNonRegularUnreadable(self) -> None:
        """Asserts rejection of symlinks, directories, missing files, multiline content, and malformed strings."""
        # 1. Missing file
        f_missing_path = os.path.join(self.m_temp_dir, "NON_EXISTENT_VERSION")
        with self.assertRaises(VersionError):
            getVersion(f_missing_path)

        # 2. Directory instead of regular file
        f_dir_path = os.path.join(self.m_temp_dir, "version_dir")
        os.makedirs(f_dir_path, exist_ok=True)
        with self.assertRaises(VersionError):
            getVersion(f_dir_path)

        # 3. Symlink
        f_real_version = os.path.join(self.m_temp_dir, "REAL_VERSION")
        with open(f_real_version, "w", encoding="utf-8") as f_f:
            f_f.write("0.2.0\n")
        f_symlink_path = os.path.join(self.m_temp_dir, "SYMLINK_VERSION")
        os.symlink(f_real_version, f_symlink_path)
        with self.assertRaises(VersionError):
            getVersion(f_symlink_path)

        # 4. Empty file
        f_empty_path = os.path.join(self.m_temp_dir, "EMPTY_VERSION")
        with open(f_empty_path, "w", encoding="utf-8") as f_f:
            f_f.write("")
        with self.assertRaises(VersionError):
            getVersion(f_empty_path)

        # 5. Empty lines only
        f_newlines_path = os.path.join(self.m_temp_dir, "NEWLINES_VERSION")
        with open(f_newlines_path, "w", encoding="utf-8") as f_f:
            f_f.write("\n\n")
        with self.assertRaises(VersionError):
            getVersion(f_newlines_path)

        # 6. Multiline content
        f_multiline_path = os.path.join(self.m_temp_dir, "MULTILINE_VERSION")
        with open(f_multiline_path, "w", encoding="utf-8") as f_f:
            f_f.write("0.2.0\n0.2.1\n")
        with self.assertRaises(VersionError):
            getVersion(f_multiline_path)

        # 7. Malformed semver strings
        f_malformed_cases = [
            "0.2",
            "v0.2.0",
            "0.2.0-beta",
            "abc",
            "0.2.0.1",
            "0.2.0 extra",
            "0. 2. 0",
        ]
        for f_idx, f_bad_ver in enumerate(f_malformed_cases):
            f_bad_path = os.path.join(self.m_temp_dir, f"BAD_VERSION_{f_idx}")
            with open(f_bad_path, "w", encoding="utf-8") as f_f:
                f_f.write(f"{f_bad_ver}\n")
            with self.assertRaises(VersionError, msg=f"Failed to reject: {f_bad_ver}"):
                getVersion(f_bad_path)

        # 8. Unreadable file (using mock to test permission failure cross-platform)
        f_unreadable_path = os.path.join(self.m_temp_dir, "UNREADABLE_VERSION")
        with open(f_unreadable_path, "w", encoding="utf-8") as f_f:
            f_f.write("0.2.0\n")
        with patch("os.access", return_value=False):
            with self.assertRaises(VersionError):
                getVersion(f_unreadable_path)

        # 9. Invalid argument type
        with self.assertRaises(VersionError):
            getVersion(12345)  # type: ignore

    def testNoLookupFallback(self) -> None:
        """Proves getVersion does not fall back to other locations."""
        # Create a decoy VERSION file in a temporary current working directory
        f_decoy_cwd = os.path.join(self.m_temp_dir, "decoy_cwd")
        os.makedirs(f_decoy_cwd, exist_ok=True)
        f_decoy_file = os.path.join(f_decoy_cwd, "VERSION")
        with open(f_decoy_file, "w", encoding="utf-8") as f_f:
            f_f.write("9.9.9\n")

        os.chdir(f_decoy_cwd)

        # Asking for a non-existent explicit path must fail immediately, never reading cwd/VERSION
        f_non_existent = os.path.join(self.m_temp_dir, "NON_EXISTENT")
        with self.assertRaises(VersionError):
            getVersion(f_non_existent)

        # Calling getVersion() with no argument must read package VERSION (0.2.0), not cwd VERSION (9.9.9)
        f_default_version = getVersion()
        self.assertEqual(f_default_version, "0.2.0")

    def testSingleAuthoredVersionLiteral(self) -> None:
        """Asserts no hardcoded version literals exist in CMakeLists.txt or lib/__init__.py."""
        f_repo_root = (
            pathlib.Path(__file__).resolve().parent.parent.parent.parent.parent
        )
        f_cmake_file = f_repo_root / "CMakeLists.txt"
        with open(f_cmake_file, "r", encoding="utf-8") as f_f:
            f_cmake_content = f_f.read()

        # CMakeLists.txt should not have literal "project(lsmio VERSION 0.2"
        self.assertNotIn("project(lsmio VERSION 0.2", f_cmake_content)

        # lib/__init__.py should not have literal VERSION = "0.2"
        f_init_file = (
            pathlib.Path(__file__).resolve().parent.parent.parent
            / "lib"
            / "__init__.py"
        )
        with open(f_init_file, "r", encoding="utf-8") as f_f:
            f_init_content = f_f.read()

        self.assertNotIn('VERSION = "0.2"', f_init_content)
        self.assertNotIn('__version__ = "0.2"', f_init_content)
        self.assertIn("getVersion()", f_init_content)
