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
from typing import Dict, List
from lsmiotool.lib.log import Console


def get_base_dir(bm_path: str) -> Dict[str, str]:
    """
    Return the base directory path as a dict
    """
    return {
        'BASE': os.path.join(bm_path, 'data'),
    }


def get_data_dirs(bm_path: str) -> Dict[str, str]:
    """
    Return dictionary of data directory paths.
    """
    return {
        'DATA': {
            '4': {
                '64K': os.path.join(bm_path, 'data', '4', '64K'),
                '1M': os.path.join(bm_path, 'data', '4', '1M'),
                '8M': os.path.join(bm_path, 'data', '4', '8M'),
            },
            '16': {
                '64K': os.path.join(bm_path, 'data', '16', '64K'),
                '1M': os.path.join(bm_path, 'data', '16', '1M'),
                '8M': os.path.join(bm_path, 'data', '16', '8M'),
            }
        }
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
    return {
        **get_base_dir(bm_path),
        **get_data_dirs(bm_path),
        **get_log_dir(bm_path)
    }


def setup_data_dirs(bm_path: str) -> None:
    """
    Create all required benchmark and log directories (mkdir -p equivalent).
    Args:
        bm_path: Base path for benchmark directories.
    """
    dirs = get_data_dirs(bm_path)['DATA']
    for core_dict in dirs.values():
        for d in core_dict.values():
            os.makedirs(d, exist_ok=True)
    # Ensure log dir exists
    log_dir = get_log_dir(bm_path)['LOG']
    os.makedirs(log_dir, exist_ok=True)


def cleanup_data_dirs(bm_path: str) -> None:
    """
    Remove all files and subdirectories inside the benchmark and log directories.
    Args:
        bm_path: Base path for benchmark directories.
    """
    dirs = get_data_dirs(bm_path)['DATA']
    # Flatten all paths from nested dict
    all_paths = []
    for core_dict in dirs.values():
        for d in core_dict.values():
            all_paths.append(d)
    # Sort directories by descending path length (deepest first)
    dir_list = sorted(all_paths, key=lambda x: -len(x))
    for d in dir_list:
        if os.path.isdir(d):
            for entry in os.listdir(d):
                entry_path = os.path.join(d, entry)
                Console.debug(f"entry_path: {entry_path}")
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
        bm_path: Base path for benchmark directories.
    """
    dirs = get_data_dirs(bm_path)
    lfs_path = shutil.which('lfs')
    if not lfs_path:
        print('Warning: lfs not found, skipping setstripe configuration.')
        return
    setstripe_cmds: List[List[str]] = [
        ['lfs', 'setstripe', '-S', '64K', '-c', '4', dirs['4']['64K']],
        ['lfs', 'setstripe', '-S', '64K', '-c', '16', dirs['16']['64K']],
        ['lfs', 'setstripe', '-S', '1M', '-c', '4', dirs['4']['1M']],
        ['lfs', 'setstripe', '-S', '1M', '-c', '16', dirs['16']['1M']],
        ['lfs', 'setstripe', '-S', '8M', '-c', '4', dirs['4']['8M']],
        ['lfs', 'setstripe', '-S', '8M', '-c', '16', dirs['16']['8M']],
    ]
    for cmd in setstripe_cmds:
        try:
            subprocess.run(cmd, check=True)
        except Exception as e:
            print(f'Warning: Failed to run {" ".join(cmd)}: {e}')

