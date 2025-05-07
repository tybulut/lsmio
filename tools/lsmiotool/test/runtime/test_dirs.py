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
import pprint
import tempfile
import shutil
import unittest
from unittest.mock import patch
from lsmiotool.lib import dirs
from lsmiotool.lib.log import Console

class TestDirs(unittest.TestCase):
    def test_get_dirs_structure(self):
        bm_path = '/tmp/fakebm'
        result = dirs.get_dirs(bm_path)
        self.assertIsInstance(result, dict)
        self.assertTrue(all(isinstance(v, str) for v in result.values()))
        self.assertIn('BM_C4_B64', result)
        self.assertTrue(result['LOG'].startswith(bm_path))

    def test_setup_and_cleanup_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Setup
            dirs.setup_data_dirs(tmpdir)
            paths = dirs.get_data_dirs(tmpdir)
            Console.debug("paths: " + pprint.pformat(paths))
            for path in paths.values():
                Console.debug("setup-path: " + path)
                self.assertTrue(os.path.isdir(path))
                # Create a file and a subdirectory for cleanup test
                file_path = os.path.join(path, 'testfile.txt')
                subdir_path = os.path.join(path, 'subdir')
                with open(file_path, 'w'):
                    pass
                os.makedirs(subdir_path, exist_ok=True)
                self.assertTrue(os.path.isfile(file_path))
                self.assertTrue(os.path.isdir(subdir_path))
            # Cleanup
            dirs.cleanup_data_dirs(tmpdir)
            for path in paths.values():
                Console.debug("cleanup-path: " + path)
                self.assertTrue(os.path.isdir(path))
                self.assertEqual(os.listdir(path), [])

    def test_get_log_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = dirs.get_log_dir(tmpdir)
            Console.debug("result-log: " + pprint.pformat(result))
            self.assertIsInstance(result['LOG'], str)
            self.assertTrue(result['LOG'].endswith('logs/jobs'))

    @patch('shutil.which', return_value=None)
    def test_config_dirs_no_lfs(self, mock_which):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Should not raise
            dirs.config_data_dirs(tmpdir)

