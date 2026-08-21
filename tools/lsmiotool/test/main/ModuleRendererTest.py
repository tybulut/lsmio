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
import os
import re
import shlex
import subprocess
import unittest

from lsmiotool.lib import env, hpc
from lsmiotool.lib.env import HpcEnv
from lsmiotool.lib.profile import ProfileDocument, ProfileLoader, ProfileRecord
from lsmiotool.lib.site import EnvironmentResolver, SiteProfile
from lsmiotool.lib.worker import ModuleRenderError, ModuleSetup, ProcessRunner


class ModuleRendererTest(unittest.TestCase):
    """Unit tests for safe one-time module shell renderer and token validation."""

    def setUp(self) -> None:
        self.m_etc_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "etc")
        )
        self.m_env_json_path = os.path.join(self.m_etc_dir, "environments.json")
        self.m_hpc_modules = hpc.HpcModules(f_profile_path=self.m_env_json_path)
        self.m_runner = ProcessRunner()

    def testExactOrderEverySite(self) -> None:
        """Validates exact generated shell lines and module ordering across all sites."""
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

            # Test via SiteProfile instance
            f_cmds_prof = ModuleSetup.renderCommands(f_profile)
            f_script_prof = ModuleSetup.render(f_profile)

            # Test via HpcEnv enum
            f_cmds_enum = ModuleSetup.renderCommands(f_env_map[f_site_name])
            f_script_enum = ModuleSetup.render(f_env_map[f_site_name])

            # Test via string site name
            f_cmds_str = ModuleSetup.renderCommands(f_site_name)
            f_script_str = ModuleSetup.render(f_site_name)

            self.assertEqual(f_cmds_prof, f_cmds_enum)
            self.assertEqual(f_cmds_prof, f_cmds_str)
            self.assertEqual(f_script_prof, f_script_enum)
            self.assertEqual(f_script_prof, f_script_str)

            if not f_profile_modules:
                self.assertEqual(f_cmds_prof, [])
                self.assertEqual(f_script_prof, "")
            else:
                self.assertEqual(f_cmds_prof[0], "module purge")
                self.assertEqual(len(f_cmds_prof), len(f_profile_modules) + 1)
                for f_idx, f_mod in enumerate(f_profile_modules):
                    f_expected_cmd = f"module load {shlex.quote(f_mod)}"
                    self.assertEqual(f_cmds_prof[f_idx + 1], f_expected_cmd)
                self.assertEqual(f_script_prof, "\n".join(f_cmds_prof))

        # Site-specific golden checks
        # Viking (9 modules)
        f_viking_cmds = ModuleSetup.renderCommands("VIKING")
        self.assertEqual(len(f_viking_cmds), 10)
        self.assertEqual(f_viking_cmds[0], "module purge")
        self.assertEqual(f_viking_cmds[1], "module load data/HDF5/1.10.7-gompi-2020b")
        self.assertEqual(f_viking_cmds[-1], "module load numlib/FFTW/3.3.10-GCC-11.3.0")

        # Viking2 (22 modules)
        f_viking2_cmds = ModuleSetup.renderCommands("VIKING2")
        self.assertEqual(len(f_viking2_cmds), 23)
        self.assertEqual(f_viking2_cmds[0], "module purge")
        self.assertEqual(f_viking2_cmds[1], "module load GCCcore/12.3.0")
        self.assertEqual(f_viking2_cmds[8], "module load OpenMPI/4.1.5-GCC-12.3.0")
        self.assertEqual(f_viking2_cmds[-1], "module load texlive/20230313-GCC-12.3.0")

        # Archer2 (16 modules)
        f_archer2_cmds = ModuleSetup.renderCommands("ARCHER2")
        self.assertEqual(len(f_archer2_cmds), 17)
        self.assertEqual(f_archer2_cmds[0], "module purge")
        self.assertEqual(f_archer2_cmds[1], "module load PrgEnv-gnu")
        self.assertEqual(f_archer2_cmds[-1], "module load cray-fftw/3.3.10.5")

        # Isambard (27 modules)
        f_isambard_cmds = ModuleSetup.renderCommands("ISAMBARD")
        self.assertEqual(len(f_isambard_cmds), 28)
        self.assertEqual(f_isambard_cmds[0], "module purge")
        self.assertEqual(f_isambard_cmds[1], "module load modules/3.2.11.4")
        self.assertEqual(f_isambard_cmds[-1], "module load gdb4hpc/4.10.6")

        # DEV (0 modules)
        f_dev_cmds = ModuleSetup.renderCommands("DEV")
        self.assertEqual(f_dev_cmds, [])
        self.assertEqual(ModuleSetup.render("DEV"), "")

    def testRenderedOnce(self) -> None:
        """Asserts output structure is a self-contained one-time preamble."""
        for f_site_name in ("VIKING", "VIKING2", "ARCHER2", "ISAMBARD"):
            f_script = ModuleSetup.render(f_site_name)
            self.assertTrue(len(f_script) > 0)
            f_lines = f_script.split("\n")

            # Must start with exactly one module purge
            self.assertEqual(f_lines[0], "module purge")
            self.assertEqual(f_lines.count("module purge"), 1)

            # Every other line must be a single module load
            for f_line in f_lines[1:]:
                self.assertTrue(f_line.startswith("module load "))
                self.assertNotIn("\n", f_line)
                self.assertNotIn(";", f_line)

            # Check that no execution or rank wrapping is present
            self.assertNotIn("exec", f_script)
            self.assertNotIn("srun", f_script)
            self.assertNotIn("aprun", f_script)
            self.assertNotIn("mpirun", f_script)
            self.assertNotIn("for ", f_script)
            self.assertNotIn("while ", f_script)

        # DEV produces empty string (never empty module purge or invalid preamble)
        f_dev_script = ModuleSetup.render("DEV")
        self.assertEqual(f_dev_script, "")

    def testAdversarialModulesRejectedOrLiteral(self) -> None:
        """Asserts rejection of newlines, control chars, semicolons, shell subshells, NUL bytes, and leading dashes."""
        f_adversarial_tokens = (
            # Semicolons and command chaining
            "gcc/11.2.0; rm -rf /",
            "; reboot",
            "mod && evil",
            "mod || evil",
            "mod | bash",
            "mod & evil",
            # Subshell interpolation
            "$(whoami)",
            "gcc/`id`",
            "`cat /etc/passwd`",
            "${HOME}",
            "$VAR",
            # Newlines and carriage returns
            "gcc/11.2.0\nrm -rf /",
            "gcc/11.2.0\r\nrm -rf /",
            "gcc\n",
            "\n",
            "\r",
            # Control characters
            "gcc/\x01/1.0",
            "gcc/\x1b[31m",
            "\t",
            "gcc/\t/1.0",
            "\x7f",
            # NUL bytes
            "gcc/\x00/1.0",
            "\x00",
            # Leading dashes and options
            "-rf",
            "--help",
            "-m",
            "-v",
            "--option=val",
            # Leading non-alphanumeric characters
            "/usr/local",
            ".hidden",
            "+extra",
            ":colon",
            "@version",
            "-leading",
            # Redirections and pipes
            "gcc > /dev/null",
            "gcc < /etc/shadow",
            "gcc >> /tmp/log",
            # Quotes and escapes
            'gcc"evil',
            "gcc'evil",
            "gcc\\evil",
            # Spaces
            " gcc",
            "gcc 11.2.0",
            "gcc ",
            "   ",
            "",
        )

        for f_bad_token in f_adversarial_tokens:
            # Direct token validation
            with self.assertRaises(ModuleRenderError, msg=f"Should reject {f_bad_token!r}"):
                ModuleSetup.validateModule(f_bad_token)

            # In a list of modules
            with self.assertRaises(ModuleRenderError, msg=f"Should reject list with {f_bad_token!r}"):
                ModuleSetup.renderCommands([f_bad_token])

            with self.assertRaises(ModuleRenderError, msg=f"Should reject list with {f_bad_token!r}"):
                ModuleSetup.render([f_bad_token])

        # Non-string types
        f_bad_types = (None, 123, 45.67, b"gcc/11.2.0", ["nested"])
        for f_bad_type in f_bad_types:
            with self.assertRaises(ModuleRenderError):
                ModuleSetup.validateModule(f_bad_type)

        # Invalid containers
        with self.assertRaises(ModuleRenderError):
            ModuleSetup.renderCommands(None)

        with self.assertRaises(ModuleRenderError):
            ModuleSetup.render(None)

        with self.assertRaises(ModuleRenderError):
            ModuleSetup.renderCommands("NONEXISTENT_SITE_NAME_123")

        # Valid complex module specifiers must pass
        f_valid_tokens = (
            "GCCcore/12.3.0",
            "cray-mpich/8.1.27",
            "data/HDF5/1.10.7-gompi-2020b",
            "system-config/3.6.3070-7.0.2.1_7.3__g40f385a9.ari",
            "pkg@1.2.3+mpi:feature_1-a.b",
            "PrgEnv-gnu/6.0.9",
            "texlive/20230313-GCC-12.3.0",
        )
        for f_valid in f_valid_tokens:
            f_validated = ModuleSetup.validateModule(f_valid)
            self.assertEqual(f_validated, f_valid)

    def testFailurePreventsExec(self) -> None:
        """Validates shell fail-fast semantics (set -e stops execution before controller exec)."""
        # 1. Successful execution scenario: mock module load succeeds and reaches exec
        f_success_script = """#!/bin/bash
set -e
# Mock module function that succeeds
module() {
    return 0
}
""" + ModuleSetup.render("VIKING") + """
echo "CONTROLLER_EXECUTED_SUCCESSFULLY"
"""
        f_res_success = self.m_runner.run(["/bin/bash", "-c", f_success_script])
        self.assertTrue(f_res_success.is_success)
        self.assertEqual(f_res_success.returncode, 0)
        self.assertIn("CONTROLLER_EXECUTED_SUCCESSFULLY", f_res_success.stdout)

        # 2. Failing execution scenario: mock module load fails and halts script immediately
        f_failing_script = """#!/bin/bash
set -e
# Mock module function where purge succeeds but load fails
module() {
    if [ "$1" = "load" ]; then
        echo "Module load failed for $2" >&2
        return 1
    fi
    return 0
}
""" + ModuleSetup.render("VIKING") + """
echo "CONTROLLER_EXECUTED_UNEXPECTEDLY"
"""
        f_res_failing = self.m_runner.run(["/bin/bash", "-c", f_failing_script])
        self.assertFalse(f_res_failing.is_success)
        self.assertNotEqual(f_res_failing.returncode, 0)
        self.assertEqual(f_res_failing.returncode, 1)
        self.assertNotIn("CONTROLLER_EXECUTED_UNEXPECTEDLY", f_res_failing.stdout)
        self.assertIn("Module load failed", f_res_failing.stderr)

        # 3. Failing purge scenario: purge itself fails and halts script immediately
        f_failing_purge = """#!/bin/bash
set -e
# Mock module function where purge fails
module() {
    if [ "$1" = "purge" ]; then
        echo "Module purge failed" >&2
        return 2
    fi
    return 0
}
""" + ModuleSetup.render("VIKING") + """
echo "CONTROLLER_EXECUTED_UNEXPECTEDLY"
"""
        f_res_purge = self.m_runner.run(["/bin/bash", "-c", f_failing_purge])
        self.assertFalse(f_res_purge.is_success)
        self.assertEqual(f_res_purge.returncode, 2)
        self.assertNotIn("CONTROLLER_EXECUTED_UNEXPECTEDLY", f_res_purge.stdout)
        self.assertIn("Module purge failed", f_res_purge.stderr)

    def testMatchesLoadModulesAuthority(self) -> None:
        """Proves exact 1:1 parity with HpcModules.shell_commands() and shellOutput() from Chunk 005."""
        f_sites = ("DEV", "VIKING", "VIKING2", "ARCHER2", "ISAMBARD")
        f_env_map = {
            "DEV": HpcEnv.DEV,
            "VIKING": HpcEnv.VIKING,
            "VIKING2": HpcEnv.VIKING2,
            "ARCHER2": HpcEnv.ARCHER2,
            "ISAMBARD": HpcEnv.ISAMBARD,
        }

        for f_site_name in f_sites:
            f_hpc_env = f_env_map[f_site_name]
            f_profile = EnvironmentResolver.resolveProfile(
                f_site_name,
                f_user="testuser",
                f_home="/tmp/testuser",
                f_env_file=self.m_env_json_path,
            )

            # Commands list parity
            f_setup_cmds = ModuleSetup.renderCommands(f_profile)
            f_hpc_cmds = self.m_hpc_modules.shellCommands(f_hpc_env)
            f_hpc_cmds_alias = self.m_hpc_modules.shell_commands(f_site_name)

            self.assertEqual(f_setup_cmds, f_hpc_cmds)
            self.assertEqual(f_setup_cmds, f_hpc_cmds_alias)

            # Output script parity
            f_setup_script = ModuleSetup.render(f_profile)
            f_setup_script_alias = ModuleSetup.renderScript(f_profile)
            f_hpc_output = self.m_hpc_modules.shellOutput(f_hpc_env)

            self.assertEqual(f_setup_script, f_hpc_output)
            self.assertEqual(f_setup_script, f_setup_script_alias)

            # SHA-256 byte parity
            f_setup_hash = hashlib.sha256(f_setup_script.encode("utf-8")).hexdigest()
            f_hpc_hash = hashlib.sha256(f_hpc_output.encode("utf-8")).hexdigest()
            self.assertEqual(f_setup_hash, f_hpc_hash)

    def testModuleSetupClassAndInstanceParity(self) -> None:
        """Asserts ModuleSetup works identically when invoked on class or instance."""
        f_inst = ModuleSetup()
        f_profile = EnvironmentResolver.resolveProfile(
            "VIKING",
            f_user="testuser",
            f_home="/tmp/testuser",
            f_env_file=self.m_env_json_path,
        )

        self.assertEqual(f_inst.render(f_profile), ModuleSetup.render(f_profile))
        self.assertEqual(
            f_inst.renderCommands(f_profile), ModuleSetup.renderCommands(f_profile)
        )
        self.assertEqual(
            f_inst.renderScript(f_profile), ModuleSetup.renderScript(f_profile)
        )
        self.assertEqual(
            f_inst.validateModule("GCCcore/12.3.0"),
            ModuleSetup.validateModule("GCCcore/12.3.0"),
        )
        self.assertEqual(
            f_inst.validateModules(["GCCcore/12.3.0"]),
            ModuleSetup.validateModules(["GCCcore/12.3.0"]),
        )

    def testCustomModuleSequenceRendering(self) -> None:
        """Asserts arbitrary valid custom module sequences render properly."""
        f_custom = ["custom/1.0", "custom/2.0"]
        f_cmds = ModuleSetup.renderCommands(f_custom)
        self.assertEqual(
            f_cmds,
            ["module purge", "module load custom/1.0", "module load custom/2.0"],
        )
        self.assertEqual(
            ModuleSetup.render(f_custom),
            "module purge\nmodule load custom/1.0\nmodule load custom/2.0",
        )

        # Empty sequence returns empty
        self.assertEqual(ModuleSetup.renderCommands([]), [])
        self.assertEqual(ModuleSetup.render([]), "")
        self.assertEqual(ModuleSetup.renderCommands(()), [])
        self.assertEqual(ModuleSetup.render(()), "")
