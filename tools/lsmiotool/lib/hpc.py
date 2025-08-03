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


import subprocess
import sys
from typing import List, Any

from lsmiotool.lib import env, debuggable
from lsmiotool.lib.env import HpcEnv
from lsmiotool.lib.log import Console


class HpcModules(debuggable.DebuggableObject):
    """A class to manage HPC environment."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the HpcModules class.

        Args:
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.
        """
        super().__init__(*args, **kwargs)

    def _get_modules(self, hpc_env: HpcEnv) -> List[str]:
        """Get the list of modules for a given HPC environment.

        Args:
            hpc_env: The HPC environment to get modules for.

        Returns:
            List of module names to load.
        """
        modules: List[str] = []
        if hpc_env == HpcEnv.VIKING:
            modules = [
                "data/HDF5/1.10.7-gompi-2020b",
                "compiler/GCC/11.3.0",
                "devel/CMake/3.24.3-GCCcore-11.3.0",
                "mpi/OpenMPI/4.1.4-GCC-11.3.0",
                "lib/zlib/1.2.12-GCCcore-11.3.0",
                "lib/lz4/1.9.3-GCCcore-11.3.0",
                "lib/libunwind/1.6.2-GCCcore-11.3.0",
                "lib/OpenJPEG/2.5.0-GCCcore-11.3.0",
                "numlib/FFTW/3.3.10-GCC-11.3.0",
            ]
        elif hpc_env == HpcEnv.VIKING2:
            modules = [
                "GCCcore/13.2.0",
                "CMake/3.27.6-GCCcore-13.2.0",
                "OpenMPI/4.1.6-GCC-13.2.0",
                "zlib/1.2.13-GCCcore-13.2.0",
                "lz4/1.9.4-GCCcore-13.2.0",
                "libunwind/1.6.2-GCCcore-13.2.0",
                "OpenJPEG/2.5.0-GCCcore-13.2.0",
                "FFTW/3.3.10-GCC-13.2.0",
                "gflags/2.2.2-GCCcore-12.3.0",
                "bzip2/1.0.8-GCCcore-13.2.0",
                "HDF5/1.14.3-gompi-2023b",
                "SciPy-bundle/2023.11-gfbf-2023b",
                "matplotlib/3.8.2-gfbf-2023b",
            ]
        elif hpc_env == HpcEnv.ISAMBARD:
            modules = [
                "modules/3.2.11.4",
                "system-config/3.6.3070-7.0.2.1_7.3__g40f385a9.ari",
                "craype-network-aries",
                "Base-opts/2.4.142-7.0.2.1_2.69__g8f27585.ari",
                "alps/6.6.59-7.0.2.1_3.62__g872a8d62.ari",
                "nodestat/2.3.89-7.0.2.1_2.53__g8645157.ari",
                "craype/2.6.2",
                "sdb/3.3.812-7.0.2.1_2.74__gd6c4e58.ari",
                "cray-libsci/20.09.1",
                "udreg/2.3.2-7.0.2.1_2.24__g8175d3d.ari",
                "pmi/5.0.17",
                "ugni/6.0.14.0-7.0.2.1_3.24__ge78e5b0.ari",
                "atp/3.11.7",
                "gni-headers/5.0.12.0-7.0.2.1_2.27__g3b1768f.ari",
                "rca/2.2.20-7.0.2.1_2.76__g8e3fb5b.ari",
                "dmapp/7.1.1-7.0.2.1_2.75__g38cf134.ari",
                "perftools-base/21.05.0",
                "xpmem/2.2.20-7.0.2.1_2.61__g87eb960.ari",
                "llm/21.4.629-7.0.2.1_2.53__g8cae6ef.ari",
                "cray-mpich/7.7.17",
                "gcc/10.3.0",
                "tools/cmake/3.24.2",
                "PrgEnv-gnu/6.0.9",
                "cray-mpich-abi/7.7.17",
                "cray-hdf5-parallel/1.12.0.4",
                "cray-fftw/3.3.8.10",
                "gdb4hpc/4.10.6",
            ]
        return modules

    def shell_commands(self, hpc_env: HpcEnv) -> List[str]:
        """Get the list of shell commands for a given HPC environment.

        Args:
            hpc_env: The HPC environment to get commands for.

        Returns:
            List of shell commands to execute.
        """
        Console.debug('shell_commands: ' + hpc_env.value)
        if hpc_env == HpcEnv.ISAMBARD:
            commands: List[str] = ["module purge"]
            modules = self._get_modules(HpcEnv.ISAMBARD)
        elif hpc_env == HpcEnv.VIKING:
            commands = ["module purge"]
            modules = self._get_modules(HpcEnv.VIKING)
        elif hpc_env == HpcEnv.VIKING2:
            commands = ["module purge"]
            modules = self._get_modules(HpcEnv.VIKING2)
        elif hpc_env == HpcEnv.DEV:
            commands = []
            modules = []
        else:
            Console.error(env.UNKNOWN_HPC_ENVIRONMENT)
            sys.exit(1)
        commands += [f"module load {mod}" for mod in modules]
        return commands

    def shell_output(self, hpc_env: HpcEnv) -> str:
        """Print all module commands (purge and loads) for the current HPC environment.

        Args:
            hpc_env: The HPC environment to get commands for.

        Returns:
            String containing all module commands.
        """
        commands = self.shell_commands(hpc_env)
        script = "\n".join(commands)
        return script

    def load(self, hpc_env: HpcEnv) -> None:
        """Execute all module commands (purge and loads) for the current HPC environment.

        Args:
            hpc_env: The HPC environment to load modules for.
        """
        commands = self.shell_commands(hpc_env)
        script = "\n".join(commands)
        result = subprocess.run(script, shell=True, executable="/bin/bash", \
                        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        print("Loading modules: stdout:", result.stdout)
        print("Loading modules: stderr:", result.stderr)
