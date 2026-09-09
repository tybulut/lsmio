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


import os
import subprocess
import sys
from typing import Any, List, Optional, Sequence, Tuple, Union

from lsmiotool.lib import debuggable, env
from lsmiotool.lib.env import HpcEnv
from lsmiotool.lib.log import Console
from lsmiotool.lib.profile import (
    ProfileDocument,
    ProfileLoader,
    ProfileRecord,
    ProfileSchemaError,
)
from lsmiotool.lib.site import EnvironmentResolver, SiteProfile, SiteResolutionError


class HpcModules(debuggable.DebuggableObject):
    """A class to manage HPC environment modules via authoritative site profile."""

    def __init__(
        self,
        *f_args: Any,
        f_profile_path: Optional[str] = None,
        **f_kwargs: Any,
    ) -> None:
        """Initialize the HpcModules class.

        Args:
            *f_args: Variable length argument list.
            f_profile_path: Optional path to environments.json configuration file.
            **f_kwargs: Arbitrary keyword arguments.
        """
        super().__init__(*f_args, **f_kwargs)
        self.m_profile_path = f_profile_path

    def _resolveSiteProfile(
        self, f_hpc_env: Union[HpcEnv, SiteProfile, ProfileRecord, str]
    ) -> SiteProfile:
        """Resolve any HPC environment identifier or record to a typed SiteProfile.

        Args:
            f_hpc_env: HpcEnv enum, SiteProfile, ProfileRecord, or site name string.

        Returns:
            Resolved SiteProfile instance.
        """
        if isinstance(f_hpc_env, SiteProfile):
            return f_hpc_env

        f_user = os.environ.get("USER") or "user"
        f_home = os.environ.get("HOME") or "/tmp"

        if isinstance(f_hpc_env, ProfileRecord):
            return EnvironmentResolver.resolveProfile(
                f_hpc_env, f_user=f_user, f_home=f_home
            )

        if isinstance(f_hpc_env, HpcEnv):
            f_site_name = f_hpc_env.name
        elif isinstance(f_hpc_env, str):
            f_site_name = f_hpc_env.strip().upper()
        elif hasattr(f_hpc_env, "name") and isinstance(f_hpc_env.name, str):
            f_site_name = f_hpc_env.name.strip().upper()
        else:
            raise SiteResolutionError(
                f"Unsupported HPC environment identifier: {f_hpc_env!r}"
            )

        f_profile_path = (
            self.m_profile_path or EnvironmentResolver.getDefaultProfilePath()
        )
        return EnvironmentResolver.resolveProfile(
            f_site_name,
            f_user=f_user,
            f_home=f_home,
            f_env_file=f_profile_path,
        )

    def getModules(
        self, f_hpc_env: Union[HpcEnv, SiteProfile, ProfileRecord, str]
    ) -> Tuple[str, ...]:
        """Get the authoritative tuple of modules for a given HPC environment.

        Args:
            f_hpc_env: The HPC environment to get modules for.

        Returns:
            Tuple of module names to load in declared order.
        """
        f_profile = self._resolveSiteProfile(f_hpc_env)
        return f_profile.modules

    _get_modules = getModules
    get_modules = getModules

    def shellCommands(
        self, f_hpc_env: Union[HpcEnv, SiteProfile, ProfileRecord, str]
    ) -> List[str]:
        """Get the list of shell commands for a given HPC environment.

        Args:
            f_hpc_env: The HPC environment to get commands for.

        Returns:
            List of shell commands to execute.
        """
        f_profile = self._resolveSiteProfile(f_hpc_env)
        Console.debug(f"shell_commands: {f_profile.name}")
        if not f_profile.modules:
            return []
        f_commands: List[str] = ["module purge"]
        f_commands.extend([f"module load {f_mod}" for f_mod in f_profile.modules])
        return f_commands

    shell_commands = shellCommands

    def shellOutput(
        self, f_hpc_env: Union[HpcEnv, SiteProfile, ProfileRecord, str]
    ) -> str:
        """Print all module commands (purge and loads) for the current HPC environment.

        Args:
            f_hpc_env: The HPC environment to get commands for.

        Returns:
            String containing all module commands separated by newlines.
        """
        f_commands = self.shellCommands(f_hpc_env)
        return "\n".join(f_commands)

    shell_output = shellOutput

    def load(self, f_hpc_env: Union[HpcEnv, SiteProfile, ProfileRecord, str]) -> None:
        """Execute all module commands for the requested HPC environment.

        Executes module purge and module loads in one checked Bash invocation,
        stopping at the first failure.

        Args:
            f_hpc_env: The HPC environment to load modules for.
        """
        f_commands = self.shellCommands(f_hpc_env)
        if not f_commands:
            return
        f_script = "\n".join(["set -e"] + f_commands)
        f_result = subprocess.run(
            f_script,
            shell=True,
            executable="/bin/bash",
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        print("Loading modules: stdout:", f_result.stdout)
        print("Loading modules: stderr:", f_result.stderr)
