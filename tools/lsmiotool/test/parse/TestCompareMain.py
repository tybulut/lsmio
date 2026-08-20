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
import tempfile
import unittest
from unittest import TestCase
from unittest.mock import patch, MagicMock

from lsmiotool.lib import main, plot


class TestCompareMain(TestCase):
    """Unit and functional tests for CompareMain command."""

    m_temp_dir: tempfile.TemporaryDirectory
    m_created_files: list

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.TemporaryDirectory()
        self.m_created_files = []

    def tearDown(self) -> None:
        self.m_temp_dir.cleanup()
        for f in self.m_created_files:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except OSError:
                    pass

    def testInitValidArguments(self) -> None:
        """Test initialization with explicit arguments."""
        cm = main.CompareMain("/tmp/bench", "read", "16", "8M")
        self.assertEqual(cm.m_folder, "/tmp/bench")
        self.assertEqual(cm.m_op, "read")
        self.assertEqual(cm.m_stripes, 16)
        self.assertEqual(cm.m_bs, "8M")

    def testInitDefaultFallback(self) -> None:
        """Test default fallbacks for optional arguments."""
        cm = main.CompareMain("/tmp/bench", "WRITE")
        self.assertEqual(cm.m_folder, "/tmp/bench")
        self.assertEqual(cm.m_op, "write")
        self.assertEqual(cm.m_stripes, 4)
        self.assertEqual(cm.m_bs, "1M")

    def testInitMissingArguments(self) -> None:
        """Test exit when missing required arguments."""
        with self.assertRaises(SystemExit):
            main.CompareMain("only_one_arg")

    def testInitInvalidOperation(self) -> None:
        """Test exit when operation is neither read nor write."""
        with self.assertRaises(SystemExit):
            main.CompareMain("/tmp/bench", "invalid_op")

    def testInitInvalidStripes(self) -> None:
        """Test exit when stripes cannot be converted to integer."""
        with self.assertRaises(SystemExit):
            main.CompareMain("/tmp/bench", "read", "invalid_stripes")

    def testResolveDirectory(self) -> None:
        """Test path resolution for absolute, relative, and home-based paths."""
        cm = main.CompareMain("/tmp/bench", "read")
        # Absolute path
        self.assertEqual(cm.resolveDirectory("/var/log"), "/var/log")
        # Relative path
        self.assertEqual(
            cm.resolveDirectory("./foo"),
            os.path.abspath(os.path.join(os.getcwd(), "foo")),
        )
        # Home expansion
        home_path = os.path.expanduser("~/benchmark_test")
        self.assertEqual(cm.resolveDirectory("~/benchmark_test"), home_path)

    def testMissingDirectoryHandling(self) -> None:
        """Test handling of non-existent target directory."""
        non_existent_dir = os.path.join(
            self.m_temp_dir.name, "does_not_exist_987654321"
        )
        cm = main.CompareMain(non_existent_dir, "read")
        with self.assertRaises(SystemExit):
            cm.run()

    def testRunNoDataWarning(self) -> None:
        """Test graceful warning when subdirectories contain no valid report data."""
        empty_subdir = os.path.join(self.m_temp_dir.name, "sub_empty")
        os.makedirs(empty_subdir, exist_ok=True)
        cm = main.CompareMain(self.m_temp_dir.name, "read", "4", "1M")

        with patch("lsmiotool.lib.log.Console.warning") as mock_warn:
            cm.run()
            mock_warn.assert_called_once()

    def testEndToEndCompareExecution(self) -> None:
        """Functional end-to-end test against synthetic viking2 dataset."""
        candidate_paths = [
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "..",
                "..",
                "..",
                "lsmio-data",
                "synthetic",
                "viking2",
                "lsmio-2026-08-04",
            ),
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "..",
                "..",
                "lsmio-data",
                "synthetic",
                "viking2",
                "lsmio-2026-08-04",
            ),
            "/Users/sbulut/src/bulut/lsmio-data/synthetic/viking2/lsmio-2026-08-04",
            os.path.expanduser("~/src/lsmio-data/synthetic/viking2/lsmio-2026-08-04"),
        ]
        target_dir = ""
        for p in candidate_paths:
            p_abs = os.path.abspath(p)
            if os.path.exists(p_abs):
                target_dir = p_abs
                break

        if not target_dir:
            self.skipTest("Synthetic viking2 dataset not found at expected locations")

        with patch("os.getcwd", return_value=self.m_temp_dir.name):
            # 1. Test Read comparison
            cm_read = main.CompareMain(target_dir, "read", "4", "1M")
            cm_read.run()

            expected_read_png = os.path.join(
                self.m_temp_dir.name, "compare-lsmio-2026-08-04-read-4-1M.png"
            )
            self.assertTrue(
                os.path.exists(expected_read_png),
                f"Generated comparison plot {expected_read_png} must exist",
            )
            self.assertGreater(
                os.path.getsize(expected_read_png),
                0,
                "Generated comparison plot must not be empty",
            )

            # 2. Test Write comparison
            cm_write = main.CompareMain(target_dir, "write", "4", "1M")
            cm_write.run()

            expected_write_png = os.path.join(
                self.m_temp_dir.name, "compare-lsmio-2026-08-04-write-4-1M.png"
            )
            self.assertTrue(
                os.path.exists(expected_write_png),
                f"Generated comparison plot {expected_write_png} must exist",
            )
            self.assertGreater(
                os.path.getsize(expected_write_png),
                0,
                "Generated comparison plot must not be empty",
            )
