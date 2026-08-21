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
                    f_cmd.split("module load ", 1)[1]
                    for f_cmd in f_commands[1:]
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

        # Representative modules from each site that must NOT appear as literals in hpc.py
        f_forbidden_literals = (
            "GCCcore/12.3.0",
            "GCCcore/13.2.0",
            "Clang/16.0.6",
            "CMake/3.26.3",
            "OpenMPI/4.1.5",
            "OpenMPI/4.1.6",
            "data/HDF5/1.10.7",
            "HDF5/1.14.0",
            "HDF5/1.14.3",
            "modules/3.2.11.4",
            "system-config/3.6.3070",
            "craype-network-aries",
            "cray-mpich/7.7.17",
            "cray-mpich/8.1.27",
            "PrgEnv-gnu",
            "load-epcc-module",
            "extra-compilers",
            "SciPy-bundle",
            "matplotlib/3.7.2",
            "matplotlib/3.8.2",
        )

        for f_forbidden in f_forbidden_literals:
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
            with patch("sys.stdout", new=io.StringIO()) as f_fake_out, patch.object(
                env, "HPC_ENV", f_target_env
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

    def testAllFourExactModuleInventoriesMatchDesignAndBmtool(self) -> None:
        """Assert exact module counts and ordering match normative specifications."""
        # Viking (9 modules)
        f_viking_mods = self.m_hpc_modules.getModules("VIKING")
        self.assertEqual(len(f_viking_mods), 9)
        self.assertEqual(f_viking_mods[0], "data/HDF5/1.10.7-gompi-2020b")
        self.assertEqual(f_viking_mods[-1], "numlib/FFTW/3.3.10-GCC-11.3.0")

        # Viking2 (22 modules, GCCcore 12.3.0 / OpenMPI 4.1.5-GCC-12.3.0)
        f_viking2_mods = self.m_hpc_modules.getModules("VIKING2")
        self.assertEqual(len(f_viking2_mods), 22)
        self.assertEqual(f_viking2_mods[0], "GCCcore/12.3.0")
        self.assertEqual(f_viking2_mods[7], "OpenMPI/4.1.5-GCC-12.3.0")
        self.assertEqual(f_viking2_mods[-1], "texlive/20230313-GCC-12.3.0")

        # Isambard (27 modules)
        f_isambard_mods = self.m_hpc_modules.getModules("ISAMBARD")
        self.assertEqual(len(f_isambard_mods), 27)
        self.assertEqual(f_isambard_mods[0], "modules/3.2.11.4")
        self.assertEqual(f_isambard_mods[-1], "gdb4hpc/4.10.6")

        # Archer2 (16 modules)
        f_archer2_mods = self.m_hpc_modules.getModules("ARCHER2")
        self.assertEqual(len(f_archer2_mods), 16)
        self.assertEqual(f_archer2_mods[0], "PrgEnv-gnu")
        self.assertEqual(f_archer2_mods[-1], "cray-fftw/3.3.10.5")

        # DEV (0 modules)
        f_dev_mods = self.m_hpc_modules.getModules("DEV")
        self.assertEqual(len(f_dev_mods), 0)
        self.assertEqual(f_dev_mods, ())
