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

class TestHpcEnvMain(unittest.TestCase):
    def setUp(self) -> None:
        self.hpc_env_main = hpc.HpcEnvMain()

    @patch('lsmiotool.lib.env.HPC_ENV', env.HpcEnv.VIKING)
    def test_get_all_module_commands_viking(self) -> None:
        cmds = self.hpc_env_main._get_all_module_commands()
        self.assertIn('module purge', cmds)
        self.assertIn('module load data/HDF5/1.10.7-gompi-2020b', cmds)
        self.assertTrue(any(cmd.startswith('module load') for cmd in cmds))

    @patch('lsmiotool.lib.env.HPC_ENV', env.HpcEnv.VIKING2)
    def test_get_all_module_commands_viking2(self) -> None:
        cmds = self.hpc_env_main._get_all_module_commands()
        self.assertIn('module purge', cmds)
        self.assertIn('module load GCCcore/13.2.0', cmds)

    @patch('lsmiotool.lib.env.HPC_ENV', env.HpcEnv.ISAMBARD)
    def test_get_all_module_commands_isambard(self) -> None:
        cmds = self.hpc_env_main._get_all_module_commands()
        self.assertIn('module purge', cmds)
        self.assertIn('module load modules/3.2.11.4', cmds)

    @patch('lsmiotool.lib.env.HPC_ENV', env.HpcEnv.VIKING)
    @patch('builtins.print')
    def test_run_prints_commands(self, mock_print) -> None:
        self.hpc_env_main.run()
        mock_print.assert_any_call('module purge')
        mock_print.assert_any_call('module load data/HDF5/1.10.7-gompi-2020b')

    @patch('lsmiotool.lib.env.HPC_ENV', env.HpcEnv.VIKING)
    @patch('subprocess.run')
    def test_execute_runs_commands(self, mock_run) -> None:
        self.hpc_env_main.execute()
        script = '\n'.join(self.hpc_env_main._get_all_module_commands())
        mock_run.assert_called_once_with(script, shell=True, executable='/bin/bash', check=True)

    @patch('lsmiotool.lib.env.HPC_ENV', 'UNKNOWN_ENV')
    @patch('lsmiotool.lib.hpc.Console')
    def test_get_all_module_commands_unknown_env(self, mock_console) -> None:
        with self.assertRaises(SystemExit):
            self.hpc_env_main._get_all_module_commands()
        mock_console.error.assert_called_once_with('Unknown HPC Environment')

