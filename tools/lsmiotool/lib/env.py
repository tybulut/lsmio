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

import copy
import json
import os
import platform
import socket
from datetime import datetime
from enum import Enum
from typing import Dict, List, Any, Optional
from lsmiotool.lib.compat import TypedDict, Final
from lsmiotool.lib.log import Console


class HpcEnv(Enum):
    """Enumeration of supported HPC environments."""
    ISAMBARD = "ISAMBARD"
    VIKING2 = "VIKING2"
    VIKING = "VIKING"
    DEV = "DEV"


class HpcManager(Enum):
    """Enumeration of supported HPC job management systems."""
    PBS = "PBS"
    SLURM = "SLURM"
    DEV = "DEV"


class IorData(TypedDict):
    """Type definition for IOR benchmark data paths."""
    base: str
    collective: str
    hdf5: str
    hdf5_collective: str


class LsmioData(TypedDict):
    """Type definition for LSMIO benchmark data paths."""
    adios: str
    plugin: str
    lsmio: str


# Relative paths stored as a list to be concatenated later
_REL_PROJECT_DIR: Final[List[str]] = ["src", "usr", "bin"]
_REL_BIN_DIR: Final[List[str]] = ["src", "usr", "bin"]
_REL_LIB_DIR: Final[List[str]] = ["src", "usr", "lib"]

# OS Environment
USER: Final[str] = os.environ["USER"]
HOME: Final[str] = os.environ["HOME"]
LD_LIBRARY_PATH: Final[str] = os.environ["HOME"]

# Error message for unknown environments
UNKNOWN_HPC_ENVIRONMENT: Final[str] = "Unknown HPC Environment"

# --- Environment Configuration via JSON ---
# Per-environment settings are loaded from ../etc/environments.json
# Edit that file to update IOR/LSMIO data, paths, etc. for each environment.

# Detect environment
lsmio_env: Optional[str] = os.environ.get("LSMIO_ENV", None)
if lsmio_env is not None:
    lsmio_env = lsmio_env.upper()
    if lsmio_env == "ISAMBARD":
        HPC_ENV: HpcEnv = HpcEnv.ISAMBARD
    elif lsmio_env == "VIKING2":
        HPC_ENV: HpcEnv = HpcEnv.VIKING2
    elif lsmio_env == "VIKING":
        HPC_ENV: HpcEnv = HpcEnv.VIKING
    elif lsmio_env == "DEV":
        HPC_ENV: HpcEnv = HpcEnv.DEV
    else:
        Console.error(f"Unknown LSMIO_ENV value: {lsmio_env}")
        Console.error(UNKNOWN_HPC_ENVIRONMENT)
        exit(1)
else:
    # Hostname-based detection (legacy)
    HOSTNAME: Final[str] = platform.node()
    if HOSTNAME.startswith("xci") or HOSTNAME.startswith("nid"):
        HPC_ENV: HpcEnv = HpcEnv.ISAMBARD
    elif "viking2" in HOSTNAME:
        HPC_ENV: HpcEnv = HpcEnv.VIKING2
    elif "viking" in HOSTNAME:
        HPC_ENV: HpcEnv = HpcEnv.VIKING
    else:
        Console.error(f"Unfamiliar host environment: {HOSTNAME}")
        Console.error(UNKNOWN_HPC_ENVIRONMENT)
        exit(1)


# Load JSON config
_json_path: str = os.path.join(os.path.dirname(__file__), "..", "etc", "environments.json")
with open(_json_path, "r") as _f:
    _env_configs: Dict[str, Any] = json.load(_f)

if "DEFAULT" not in _env_configs:
    Console.error("DEFAULT section missing in environments.json")
    exit(1)


def _deep_merge(dict1: Dict[str, Any], dict2: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge dict2 into dict1 recursively, returning a new dict.

    Args:
        dict1: Base dictionary to merge into
        dict2: Dictionary to merge from

    Returns:
        Merged dictionary
    """
    result = copy.deepcopy(dict1)
    for k, v in dict2.items():
        if (
            k in result
            and isinstance(result[k], dict)
            and isinstance(v, dict)
        ):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


_env: Dict[str, Any] = _deep_merge(_env_configs["DEFAULT"], _env_configs.get(HPC_ENV.value, {}))

hpc_manager: str = _env["hpc_manager"]
base_path: str = _env["base_path"]
ior_dir: str = os.path.join(base_path, *_env["ior_dirs"])
lsmio_dir: str = os.path.join(base_path, *_env["lsmio_dirs"])
plots_dir: str = os.path.join(base_path, *_env["plots_dirs"])
ior_data: IorData = _env["ior_data"]
lsmio_data: LsmioData = _env["lsmio_data"]
lustre_hdd_path: str = _env["lustre_hdd_path"]
lustre_ssd_path: str = _env["lustre_ssd_path"]

if HPC_ENV.value not in _env_configs:
    Console.error(f"Unknown _env_configs value: {HPC_ENV.value}")
    Console.error(UNKNOWN_HPC_ENVIRONMENT)
    exit(1)


# Benchmark Environment
DATE_STAMP: Final[str] = datetime.today().strftime("%Y-%m-%d")
PROJECT_DIR: Final[str] = os.path.join(HOME, *_REL_PROJECT_DIR)
BIN_DIR: Final[str] = os.path.join(HOME, *_REL_BIN_DIR)
LIB_DIR: Final[str] = os.path.join(HOME, *_REL_LIB_DIR)

# Use SSD path by default
lustre_path: str = lustre_ssd_path

BM_DIR: Final[str] = os.path.join(lustre_path, "users", USER, "benchmark")
BM_NUM_CORES: int = 1
BM_NUM_TASKS: int = int(os.environ.get("SLURM_JOB_NUM_NODES", 1))
BM_NODENAME: str = str(socket.gethostname())
BM_UNIQUE_UID: str = BM_NODENAME + "-" + datetime.today().strftime("%Y%m%d-%H%M")

if hpc_manager == HpcManager.SLURM:
    BM_NODENAME = os.environ.get("SLURMD_NODENAME")
    BM_UNIQUE_UID = os.path.expandvars("${SLURMD_NODENAME}-${SLURM_LOCALID}")
elif hpc_manager == HpcManager.PBS:
    BM_UNIQUE_UID = os.path.expandvars(BM_NODENAME + "-${ALPS_APP_PE}")

os.environ["PATH"] += ":" + BIN_DIR
if "LD_LIBRARY_PATH" in os.environ:
    os.environ["LD_LIBRARY_PATH"] += ":" + LIB_DIR
else:
    os.environ["LD_LIBRARY_PATH"] = LIB_DIR
os.environ["ADIOS2_PLUGIN_PATH"] = LIB_DIR
