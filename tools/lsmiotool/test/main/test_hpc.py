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

import unittest
from unittest.mock import patch, MagicMock
from lsmiotool.lib import hpc, env

class TestHpcModules(unittest.TestCase):
    def setUp(self) -> None:
        self.hpc_modules = hpc.HpcModules()

    def test_get_all_module_commands_viking(self) -> None:
        cmds = self.hpc_modules._get_all_module_commands(env.HpcEnv.VIKING)
        self.assertIn('module purge', cmds)
        self.assertIn('module load data/HDF5/1.10.7-gompi-2020b', cmds)
        self.assertTrue(any(cmd.startswith('module load') for cmd in cmds))

    def test_get_all_module_commands_viking2(self) -> None:
        cmds = self.hpc_modules._get_all_module_commands(env.HpcEnv.VIKING2)
        self.assertIn('module purge', cmds)
        self.assertIn('module load GCCcore/13.2.0', cmds)

    def test_get_all_module_commands_isambard(self) -> None:
        cmds = self.hpc_modules._get_all_module_commands(env.HpcEnv.ISAMBARD)
        self.assertIn('module purge', cmds)
        self.assertIn('module load modules/3.2.11.4', cmds)

    @patch('builtins.print')
    def test_shell_output(self, mock_print) -> None:
        script = self.hpc_modules.shell_output(env.HpcEnv.VIKING)
        self.assertIn('module purge', script)
        self.assertIn('module load data/HDF5/1.10.7-gompi-2020b', script)

    @patch('subprocess.run')
    def test_load(self, mock_run) -> None:
        script = self.hpc_modules.shell_output(env.HpcEnv.VIKING)
        self.hpc_modules.load(env.HpcEnv.VIKING)
        mock_run.assert_called_once_with(script, shell=True, executable='/bin/bash', check=True)


