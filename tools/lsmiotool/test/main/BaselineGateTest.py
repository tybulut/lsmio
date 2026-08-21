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
from pathlib import Path
import re
import runpy
import sys
import unittest
from unittest.mock import MagicMock, patch

from lsmiotool import test as lsmiotool_test
from lsmiotool.lib import main


class BaselineGateTest(unittest.TestCase):
    def testRunnerReturnsZeroAndOne(self) -> None:
        successful = MagicMock()
        successful.wasSuccessful.return_value = True
        unsuccessful = MagicMock()
        unsuccessful.wasSuccessful.return_value = False

        with patch.object(
            lsmiotool_test.unittest.TextTestRunner, "run", side_effect=[successful, unsuccessful]
        ) as mock_run:
            statuses = [
                lsmiotool_test.run_and_report(),
                lsmiotool_test.run_and_report(),
            ]

        self.assertEqual(statuses, [0, 1])
        self.assertEqual(mock_run.call_count, 2)

    def testTestMainReturnsRunnerStatus(self) -> None:
        with patch.object(lsmiotool_test, "run_and_report", return_value=7) as mock_run:
            status = main.TestMain().run()

        self.assertEqual(status, 7)
        mock_run.assert_called_once_with()

    def testExecutableSystemExitUsesReturnedSeven(self) -> None:
        executable = Path(__file__).resolve().parents[2] / "lsmiotool"

        with patch.dict(os.environ, {"LSMIO_ENV": "DEV"}, clear=True):
            with patch.object(sys, "argv", [str(executable), "test"]):
                with patch.object(main.TestMain, "run", return_value=7):
                    with self.assertRaises(SystemExit) as context:
                        runpy.run_path(str(executable), run_name="__main__")

            self.assertEqual(os.environ.get("MPLBACKEND"), "Agg")

        self.assertEqual(context.exception.code, 7)

    def testExecutableNoneMapsZeroAndRetainsInterpreter(self) -> None:
        executable = Path(__file__).resolve().parents[2] / "lsmiotool"

        with patch.object(sys, "argv", [str(executable), "shell"]):
            with patch.object(main.ShellMain, "run", return_value=None):
                with patch("os.execvp") as mock_exec:
                    with self.assertRaises(SystemExit) as context:
                        runpy.run_path(str(executable), run_name="__main__")

        self.assertEqual(context.exception.code, 0)
        mock_exec.assert_not_called()

    def testNoLoginSession(self) -> None:
        log_path = Path(__file__).resolve().parents[2] / "lib" / "log.py"

        with patch("os.getlogin", side_effect=OSError("no login session")) as mock_login:
            with patch("getpass.getuser", return_value="service-user"):
                module_globals = runpy.run_path(str(log_path))

        self.assertEqual(
            module_globals["LOG_FILE"],
            "/tmp/lsmiotool-service-user-lsmiotool.log",
        )
        mock_login.assert_not_called()

    def testGeneratedCtestRegistrationExactlyOnceAndReadOnly(self) -> None:
        source_root = Path(__file__).resolve().parents[4]
        registration_path = Path(
            os.environ.get("LSMIO_CTEST_REGISTRATION")
            or source_root / "build" / "test" / "CTestTestfile.cmake"
        )
        cache_path = registration_path.parent.parent / "CMakeCache.txt"
        cache_before = cache_path.stat()
        cache = cache_path.read_text(encoding="utf-8")
        cache_after = cache_path.stat()
        cached_python = re.findall(
            r"^_Python3_EXECUTABLE:INTERNAL=(.+)$",
            cache,
            flags=re.MULTILINE,
        )
        self.assertEqual(len(cached_python), 1, cache)

        selected_python = os.environ.get("LSMIO_CTEST_PYTHON") or cached_python[0]
        selected_entry = os.environ.get("LSMIO_CTEST_ENTRY") or str(
            source_root / "tools" / "lsmiotool" / "lsmiotool"
        )

        before = registration_path.stat()
        registration = registration_path.read_text(encoding="utf-8")
        after = registration_path.stat()
        matches = re.findall(
            r'^add_test\(lsmiotool_python_suite "([^"]+)" "([^"]+)" "test"\)$',
            registration,
            flags=re.MULTILINE,
        )

        self.assertEqual(matches, [(selected_python, selected_entry)], registration)
        self.assertEqual(selected_python, cached_python[0])
        self.assertEqual(
            (cache_after.st_ino, cache_after.st_size, cache_after.st_mtime_ns),
            (cache_before.st_ino, cache_before.st_size, cache_before.st_mtime_ns),
        )
        self.assertEqual(
            (after.st_ino, after.st_size, after.st_mtime_ns),
            (before.st_ino, before.st_size, before.st_mtime_ns),
        )
