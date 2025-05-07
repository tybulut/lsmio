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

import os
import shutil
import subprocess
import pprint
from typing import Dict
from lsmiotool.lib.log import Console


def get_base_dir(bm_path: str) -> Dict[str, str]:
    """
    Return the base directory path as a dict
    """
    return {
        'BM_BASE': os.path.join(bm_path, 'data'),
    }


def get_data_dirs(bm_path: str) -> Dict[str, str]:
    return {
        'BM_C4_B64': os.path.join(bm_path, 'data', 'c4', 'b64K'),
        'BM_c16_B64': os.path.join(bm_path, 'data', 'c16', 'b64K'),
        'BM_C4_B1M': os.path.join(bm_path, 'data', 'c4', 'b1M'),
        'BM_c16_B1M': os.path.join(bm_path, 'data', 'c16', 'b1M'),
        'BM_C4_B8M': os.path.join(bm_path, 'data', 'c4', 'b8M'),
        'BM_c16_B8M': os.path.join(bm_path, 'data', 'c16', 'b8M'),
    }


def get_log_dir(bm_path: str) -> Dict[str, str]:
    """
    Return the log directory path as a dict
    """
    return {
        'LOG':  os.path.join(bm_path, 'logs', 'jobs')
    }


def get_dirs(bm_path: str) -> Dict[str, str]:
    """
    Return a dictionary of all managed directories (base, data, log).
    """
    return {**get_base_dir(bm_path), **get_data_dirs(bm_path), **get_log_dir(bm_path)}


def setup_data_dirs(bm_path: str) -> None:
    """
    Create all required benchmark and log directories (mkdir -p equivalent).
    Args:
        bm_path (str): Base path for benchmark directories.
    """
    dirs = get_data_dirs(bm_path)
    for d in dirs.values():
        os.makedirs(d, exist_ok=True)


def cleanup_data_dirs(bm_path: str) -> None:
    """
    Remove all files and subdirectories inside the benchmark and log directories.
    Args:
        bm_path (str): Base path for benchmark directories.
    """
    dirs = get_data_dirs(bm_path)
    # Sort directories by descending path length (deepest first)
    dir_list = sorted(dirs.values(), key=lambda x: -len(x))
    for d in dir_list:
        if os.path.isdir(d):
            for entry in os.listdir(d):
                entry_path = os.path.join(d, entry)
                Console.debug("entry_path: " + entry_path)
                if os.path.isdir(entry_path):
                    shutil.rmtree(entry_path)
                else:
                    os.unlink(entry_path)
        else:
            os.makedirs(d, exist_ok=True)



def config_data_dirs(bm_path: str) -> None:
    """
    Configure Lustre striping for benchmark directories if the 'lfs' command is available.
    Args:
        bm_path (str): Base path for benchmark directories.
    """
    dirs = get_data_dirs(bm_path)
    lfs_path = shutil.which('lfs')
    if not lfs_path:
        print('Warning: lfs not found, skipping setstripe configuration.')
        return
    setstripe_cmds = [
        ['lfs', 'setstripe', '-S', '64K', '-c', '4', dirs['BM_C4_B64']],
        ['lfs', 'setstripe', '-S', '64K', '-c', '16', dirs['BM_c16_B64']],
        ['lfs', 'setstripe', '-S', '1M', '-c', '4', dirs['BM_C4_B1M']],
        ['lfs', 'setstripe', '-S', '1M', '-c', '16', dirs['BM_c16_B1M']],
        ['lfs', 'setstripe', '-S', '8M', '-c', '4', dirs['BM_C4_B8M']],
        ['lfs', 'setstripe', '-S', '8M', '-c', '16', dirs['BM_c16_B8M']],
    ]
    for cmd in setstripe_cmds:
        try:
            subprocess.run(cmd, check=True)
        except Exception as e:
            print(f'Warning: Failed to run {" ".join(cmd)}: {e}')

