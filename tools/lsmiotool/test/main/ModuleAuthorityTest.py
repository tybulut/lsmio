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

import hashlib
import io
import os
import re
import subprocess
import sys
import unittest
from unittest.mock import patch, MagicMock

from lsmiotool.lib import env, hpc
from lsmiotool.lib.env import HpcEnv
from lsmiotool.lib.main import HpcEnvMain
from lsmiotool.lib.profile import ProfileDocument, ProfileLoader, ProfileSchemaError
from lsmiotool.lib.site import EnvironmentResolver, SiteProfile, SiteResolutionError


class ModuleAuthorityTest(unittest.TestCase):
    """Unit tests ensuring HpcModules single inventory authority from SiteProfile."""

    def setUp(self) -> None:
        self.m_etc_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "etc")
        )
        self.m_env_json_path = os.path.join(self.m_etc_dir, "environments.json")
        self.m_hpc_py_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "lib", "hpc.py")
        )
        self.m_hpc_modules = hpc.HpcModules(f_profile_path=self.m_env_json_path)

    def testLegacyOutputAndRunProfileSameTuple(self) -> None:
        """Assert shell output and run profile modules are identical tuples across all sites."""
        f_sites = ("DEV", "VIKING", "VIKING2", "ARCHER2", "ISAMBARD")
        f_env_map = {
            "DEV": HpcEnv.DEV,
            "VIKING": HpcEnv.VIKING,
            "VIKING2": HpcEnv.VIKING2,
            "ARCHER2": HpcEnv.ARCHER2,
            "ISAMBARD": HpcEnv.ISAMBARD,
        }

        for f_site_name in f_sites:
            f_profile = EnvironmentResolver.resolveProfile(
                f_site_name,
                f_user="testuser",
                f_home="/tmp/testuser",
                f_env_file=self.m_env_json_path,
            )
            f_profile_modules = f_profile.modules

            # Via string site name
            f_mod_from_str = self.m_hpc_modules.getModules(f_site_name)
            self.assertEqual(f_mod_from_str, f_profile_modules)

            # Via HpcEnv enum
            f_hpc_env = f_env_map[f_site_name]
            f_mod_from_enum = self.m_hpc_modules.getModules(f_hpc_env)
            self.assertEqual(f_mod_from_enum, f_profile_modules)

            # Via SiteProfile instance
            f_mod_from_prof = self.m_hpc_modules.getModules(f_profile)
            self.assertEqual(f_mod_from_prof, f_profile_modules)

            # Check shell commands alignment
            f_commands = self.m_hpc_modules.shellCommands(f_site_name)
            if not f_profile_modules:
                self.assertEqual(f_commands, [])
            else:
                self.assertEqual(f_commands[0], "module purge")
                f_loaded_modules = tuple(
                    f_cmd.split("module load ", 1)[1] for f_cmd in f_commands[1:]
                )
                self.assertEqual(f_loaded_modules, f_profile_modules)

            # Check shell output alignment
            f_output = self.m_hpc_modules.shellOutput(f_site_name)
            if not f_profile_modules:
                self.assertEqual(f_output, "")
            else:
                self.assertEqual(f_output, "\n".join(f_commands))

            # Hash equivalence
            f_profile_hash = hashlib.sha256(
                repr(f_profile_modules).encode("utf-8")
            ).hexdigest()
            f_legacy_hash = hashlib.sha256(
                repr(f_mod_from_enum).encode("utf-8")
            ).hexdigest()
            self.assertEqual(f_profile_hash, f_legacy_hash)

    def testLoadCheckedFailure(self) -> None:
        """Assert checked failure when module load command fails."""
        # Simulated failure propagating CalledProcessError
        with patch("subprocess.run") as f_mock_run:
            f_mock_run.side_effect = subprocess.CalledProcessError(
                returncode=127,
                cmd="set -e\nmodule purge\nmodule load nonexistent/1.0",
                stderr="ModuleCmd_Load.c(244):ERROR:105: Unable to locate a modulefile",
            )
            with self.assertRaises(subprocess.CalledProcessError) as f_ctx:
                self.m_hpc_modules.load(HpcEnv.VIKING)
            self.assertEqual(f_ctx.exception.returncode, 127)

        # Verify load on DEV is a no-op that does not invoke subprocess
        with patch("subprocess.run") as f_mock_run_dev:
            self.m_hpc_modules.load(HpcEnv.DEV)
            f_mock_run_dev.assert_not_called()

    def testNoHardCodedSecondInventory(self) -> None:
        """Assert no separate hard-coded module lists exist in hpc.py."""
        with open(self.m_hpc_py_path, "r", encoding="utf-8") as f_file:
            f_source_code = f_file.read()

        # No module of any site profile may appear as a literal in hpc.py
        f_doc = ProfileLoader.load(self.m_env_json_path)
        f_forbidden_literals = {
            f_mod
            for f_site in f_doc.profiles
            for f_mod in f_doc.getProfile(f_site).modules
        }
        self.assertTrue(f_forbidden_literals)

        for f_forbidden in sorted(f_forbidden_literals):
            self.assertNotIn(
                f_forbidden,
                f_source_code,
                f"Forbidden hardcoded module literal '{f_forbidden}' found in {self.m_hpc_py_path}",
            )

        # Verify HpcModules instance has no dictionary of hardcoded module arrays
        self.assertFalse(hasattr(self.m_hpc_modules, "m_modules"))
        self.assertFalse(hasattr(self.m_hpc_modules, "_modules"))

    def testLegacyHpcEnvMainCommandDispatch(self) -> None:
        """Assert legacy load-modules command dispatch remains green across all sites."""
        f_sites = ("DEV", "VIKING", "VIKING2", "ARCHER2", "ISAMBARD")
        f_env_map = {
            "DEV": HpcEnv.DEV,
            "VIKING": HpcEnv.VIKING,
            "VIKING2": HpcEnv.VIKING2,
            "ARCHER2": HpcEnv.ARCHER2,
            "ISAMBARD": HpcEnv.ISAMBARD,
        }

        for f_site_name in f_sites:
            f_target_env = f_env_map[f_site_name]
            with (
                patch("sys.stdout", new=io.StringIO()) as f_fake_out,
                patch.object(env, "HPC_ENV", f_target_env),
            ):
                f_main = HpcEnvMain()
                f_main.run()
                f_printed = f_fake_out.getvalue().rstrip("\n")
                f_expected = self.m_hpc_modules.shellOutput(f_target_env)
                self.assertEqual(f_printed, f_expected)

    def testUnknownProfileRejection(self) -> None:
        """Assert unknown or invalid profile names fail closed."""
        with self.assertRaises((ProfileSchemaError, SiteResolutionError)):
            self.m_hpc_modules.getModules("NONEXISTENT_SITE_XYZ")

        with self.assertRaises((ProfileSchemaError, SiteResolutionError)):
            self.m_hpc_modules.shellCommands("NONEXISTENT_SITE_XYZ")

    def testAllFourModuleInventoriesMatchBmtool(self) -> None:
        """Assert every site's module inventory matches bmtool's load-modules.in.sh.

        Both inventories are read from their files, so a site re-tooling only has to
        keep the two in step; no module name is pinned here.
        """
        f_load_modules_path = os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "..",
                "bmtool",
                "include",
                "load-modules.in.sh",
            )
        )
        with open(f_load_modules_path, "r", encoding="utf-8") as f_file:
            f_shell_source = f_file.read()

        # load_modules_<site>() { MODULES="<one module per line>" ... }
        f_bmtool_inventories = {
            f_match.group(1).upper(): tuple(
                f_line for f_line in f_match.group(2).split("\n") if f_line
            )
            for f_match in re.finditer(
                r'^load_modules_(\w+)\(\) \{\n  MODULES="\n(.*?)"$',
                f_shell_source,
                re.MULTILINE | re.DOTALL,
            )
        }
        self.assertEqual(
            set(f_bmtool_inventories), {"VIKING", "VIKING2", "ISAMBARD", "ARCHER2"}
        )

        for f_site_name, f_bmtool_mods in f_bmtool_inventories.items():
            f_mods = self.m_hpc_modules.getModules(f_site_name)
            self.assertTrue(f_mods, f"{f_site_name} has no modules")
            self.assertEqual(len(set(f_mods)), len(f_mods), f"{f_site_name} duplicates")
            self.assertEqual(f_mods, f_bmtool_mods, f"{f_site_name} differs from bmtool")

        # DEV (0 modules)
        f_dev_mods = self.m_hpc_modules.getModules("DEV")
        self.assertEqual(len(f_dev_mods), 0)
        self.assertEqual(f_dev_mods, ())
