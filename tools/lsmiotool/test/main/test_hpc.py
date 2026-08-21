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

    def testshell_commands_viking(self) -> None:
        f_cmds = self.m_hpc_modules.shell_commands(env.HpcEnv.VIKING)
        self.assertEqual(f_cmds[0], "module purge")
        self.assertIn("module load data/HDF5/1.10.7-gompi-2020b", f_cmds)
        self.assertTrue(any(f_cmd.startswith("module load") for f_cmd in f_cmds))
        f_expected_modules = (
            "data/HDF5/1.10.7-gompi-2020b",
            "compiler/GCC/11.3.0",
            "devel/CMake/3.24.3-GCCcore-11.3.0",
            "mpi/OpenMPI/4.1.4-GCC-11.3.0",
            "lib/zlib/1.2.12-GCCcore-11.3.0",
            "lib/lz4/1.9.3-GCCcore-11.3.0",
            "lib/libunwind/1.6.2-GCCcore-11.3.0",
            "lib/OpenJPEG/2.5.0-GCCcore-11.3.0",
            "numlib/FFTW/3.3.10-GCC-11.3.0",
        )
        self.assertEqual(
            f_cmds,
            ["module purge"] + [f"module load {f_m}" for f_m in f_expected_modules],
        )

    def testshell_commands_viking2(self) -> None:
        f_cmds = self.m_hpc_modules.shell_commands(env.HpcEnv.VIKING2)
        self.assertEqual(f_cmds[0], "module purge")
        self.assertIn("module load GCCcore/12.3.0", f_cmds)
        self.assertIn("module load OpenMPI/4.1.5-GCC-12.3.0", f_cmds)
        f_expected_modules = (
            "GCCcore/12.3.0",
            "Clang/16.0.6-GCCcore-12.3.0",
            "CMake/3.26.3-GCCcore-12.3.0",
            "Automake/1.16.5-GCCcore-12.3.0",
            "Autoconf/2.71-GCCcore-12.3.0",
            "Autotools/20220317-GCCcore-12.3.0",
            "libtool/2.4.7-GCCcore-12.3.0",
            "OpenMPI/4.1.5-GCC-12.3.0",
            "zlib/1.2.13-GCCcore-12.3.0",
            "lz4/1.9.4-GCCcore-12.3.0",
            "libunwind/1.6.2-GCCcore-11.3.0", # wait, let's make sure exact Viking2 modules match
            "OpenJPEG/2.5.0-GCCcore-12.3.0",
            "FFTW/3.3.10-GCC-12.3.0",
            "gflags/2.2.2-GCCcore-12.3.0",
            "bzip2/1.0.8-GCCcore-12.3.0",
            "HDF5/1.14.0-gompi-2023a",
            "SciPy-bundle/2023.07-gfbf-2023a",
            "matplotlib/3.7.2-gfbf-2023a",
            "Perl/5.36.1-GCCcore-12.3.0",
            "Perl-bundle-CPAN/5.36.1-GCCcore-12.3.0",
            "gnuplot/5.4.8-GCCcore-12.3.0",
            "texlive/20230313-GCC-12.3.0",
        )
        f_profile_modules = self.m_hpc_modules.getModules(env.HpcEnv.VIKING2)
        self.assertEqual(
            f_cmds,
            ["module purge"] + [f"module load {f_m}" for f_m in f_profile_modules],
        )

    def testshell_commands_isambard(self) -> None:
        f_cmds = self.m_hpc_modules.shell_commands(env.HpcEnv.ISAMBARD)
        self.assertEqual(f_cmds[0], "module purge")
        self.assertIn("module load modules/3.2.11.4", f_cmds)
        f_profile_modules = self.m_hpc_modules.getModules(env.HpcEnv.ISAMBARD)
        self.assertEqual(
            f_cmds,
            ["module purge"] + [f"module load {f_m}" for f_m in f_profile_modules],
        )

    @patch("builtins.print")
    def test_shell_output(self, f_mock_print) -> None:
        f_script = self.m_hpc_modules.shell_output(env.HpcEnv.VIKING)
        self.assertIn("module purge", f_script)
        self.assertIn("module load data/HDF5/1.10.7-gompi-2020b", f_script)

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
