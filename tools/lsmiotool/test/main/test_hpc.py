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
#

import subprocess
import unittest
from unittest.mock import patch, MagicMock

from lsmiotool.lib import env, hpc


class TestHpcModules(unittest.TestCase):
    def setUp(self) -> None:
        self.m_hpc_modules = hpc.HpcModules()
        self.hpc_modules = self.m_hpc_modules

    def _assertShellCommands(self, f_hpc_env: env.HpcEnv) -> None:
        """Assert the commands are a purge followed by one load per profile module.

        The modules come from environments.json, so site re-tooling needs no test change.
        """
        f_cmds = self.m_hpc_modules.shell_commands(f_hpc_env)
        f_profile_modules = self.m_hpc_modules.getModules(f_hpc_env)
        self.assertTrue(f_profile_modules)
        self.assertEqual(f_cmds[0], "module purge")
        self.assertEqual(
            f_cmds,
            ["module purge"] + [f"module load {f_m}" for f_m in f_profile_modules],
        )

    def testshell_commands_viking(self) -> None:
        self._assertShellCommands(env.HpcEnv.VIKING)

    def testshell_commands_viking2(self) -> None:
        self._assertShellCommands(env.HpcEnv.VIKING2)

    def testshell_commands_isambard(self) -> None:
        self._assertShellCommands(env.HpcEnv.ISAMBARD)

    @patch("builtins.print")
    def test_shell_output(self, f_mock_print) -> None:
        f_script = self.m_hpc_modules.shell_output(env.HpcEnv.VIKING)
        f_first_module = self.m_hpc_modules.getModules(env.HpcEnv.VIKING)[0]
        self.assertIn("module purge", f_script)
        self.assertIn(f"module load {f_first_module}", f_script)
        self.assertEqual(
            f_script,
            "\n".join(self.m_hpc_modules.shell_commands(env.HpcEnv.VIKING)),
        )

    @patch("subprocess.run")
    def test_load(self, f_mock_run) -> None:
        f_script = self.m_hpc_modules.shell_output(env.HpcEnv.VIKING)
        f_expected_script = "set -e\n" + f_script
        self.m_hpc_modules.load(env.HpcEnv.VIKING)
        f_mock_run.assert_called_once_with(
            f_expected_script,
            shell=True,
            executable="/bin/bash",
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )

    @patch("subprocess.run")
    def test_load_propagates_failure(self, f_mock_run) -> None:
        f_mock_run.side_effect = subprocess.CalledProcessError(9, "module purge")

        with self.assertRaises(subprocess.CalledProcessError) as f_context:
            self.m_hpc_modules.load(env.HpcEnv.VIKING)

        self.assertEqual(f_context.exception.returncode, 9)
