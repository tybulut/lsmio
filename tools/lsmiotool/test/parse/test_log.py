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
from unittest import TestCase
from unittest.mock import patch
from io import StringIO
from typing import Dict, Any, Optional
from lsmiotool.lib.log import Log, Console, LogLevel, LogOutput
from lsmiotool.lib.debuggable import DebuggableObject


class MyTestObject(DebuggableObject):
    def methodDebugs(self, f_args: Dict[str, Any]) -> None:
        self._logDebug(f_args)

    def methodWarns(self, f_args: Dict[str, Any]) -> None:
        self._logWarning(f_args)

    def methodErrors(self, f_args: Dict[str, Any]) -> None:
        self._logError(f_args)


class LogUnitTestCase(TestCase):
    def test_traceable(self) -> None:
        swap_output = Log().output
        Log().output = StringIO()

        to = MyTestObject()

        Log().output.seek(0)
        Log().output.truncate()
        to.methodWarns({"b": 2})
        output = Log().output.getvalue()
        self.assertEqual(
            output, "lsmiotool: WARNING: MyTestObject::methodWarns(): b=2\n", output
        )

        Log().output.seek(0)
        Log().output.truncate()
        to.methodErrors({"c": 3})
        output = Log().output.getvalue()
        self.assertEqual(
            output, "lsmiotool: ERROR: MyTestObject::methodErrors(): c=3\n", output
        )

        Log().output = swap_output


class LogApiTest(TestCase):
    def setUp(self) -> None:
        self.m_saved_level = Log.getLevel()

    def tearDown(self) -> None:
        Log.setLevel(self.m_saved_level)

    def testLogOutputReportsPatchedFile(self) -> None:
        """LogOutput writes to, and reports, the module LOG_FILE read at construction."""
        f_dir = tempfile.TemporaryDirectory()
        self.addCleanup(f_dir.cleanup)
        f_path = os.path.join(f_dir.name, "probe.log")
        with patch("lsmiotool.lib.log.LOG_FILE", f_path):
            f_out = LogOutput("LogApiTest")
        self.addCleanup(f_out._handler.close)
        self.addCleanup(f_out._logger.removeHandler, f_out._handler)
        f_out.write("hello\n")
        f_out._handler.flush()
        self.assertEqual(f_out.output(), f_path)
        self.assertEqual(f_out.log_file, f_path)
        self.assertTrue(os.path.exists(f_path))
        with open(f_path) as f_file:
            self.assertTrue(f_file.read().endswith(" - hello\n"))

    def testSetLevelStoresEveryValidLevel(self) -> None:
        """setLevel stores each LogLevel, shared with Console."""
        for f_level in (LogLevel.ERROR, LogLevel.WARNING, LogLevel.DEBUG, LogLevel.INFO):
            with self.subTest(level=f_level):
                Log.setLevel(f_level)
                self.assertIs(Log.getLevel(), f_level)
                self.assertIs(Log._debug_level, f_level)
                self.assertIs(Console.getLevel(), f_level)

    def testSetLevelRejectsNonLogLevel(self) -> None:
        """setLevel rejects anything that is not a LogLevel and keeps the old level."""
        Log.setLevel(LogLevel.DEBUG)
        for f_bad in (2, -1, 4, "DEBUG", "", None, 2.0):
            with self.subTest(value=f_bad):
                with self.assertRaises(ValueError) as f_ctx:
                    Log.setLevel(f_bad)
                self.assertEqual(str(f_ctx.exception), "Log level must be a LogLevel enum")
                self.assertIs(Log.getLevel(), LogLevel.DEBUG)

    def testFixPermissionsChownsLogFile(self) -> None:
        """Log.fixPermissions creates the missing log file and chowns it."""
        with tempfile.TemporaryDirectory() as f_dir:
            f_path = os.path.join(f_dir, "x.log")
            with patch("lsmiotool.lib.log.LOG_FILE", f_path), patch(
                "lsmiotool.lib.log.os.chown"
            ) as f_chown:
                Log.fixPermissions(12, 34)
                self.assertTrue(os.path.exists(f_path))
                f_chown.assert_called_once_with(f_path, 12, 34)
                f_chown.reset_mock()
                with open(f_path, "w") as f_f:
                    f_f.write("keep")
                Log.fixPermissions(5, 6)
                f_chown.assert_called_once_with(f_path, 5, 6)
                with open(f_path) as f_f:
                    self.assertEqual(f_f.read(), "keep")

    def testConsoleFixPermissionsIsNoOp(self) -> None:
        """Console.fixPermissions does nothing."""
        with patch("lsmiotool.lib.log.os.chown") as f_chown:
            f_result = Console.fixPermissions(os.getuid(), os.getgid())
            self.assertIsNone(f_result)
            f_chown.assert_not_called()

    def testConsoleDumpWritesProgramPrefixedLine(self) -> None:
        """Console.dump writes 'lsmiotool: <msg>' to stderr."""
        for f_msg in ("hello", "", "a\nb"):
            with self.subTest(msg=f_msg):
                with patch("sys.stderr", new_callable=StringIO) as f_err:
                    Console.dump(f_msg)
                self.assertEqual(f_err.getvalue(), f"lsmiotool: {f_msg}\n")
        self.assertIs(Console(), Console())
        self.assertIsNot(Console(), Log())


def _raiseBoom() -> None:
    raise ValueError("boom")


class Probe(DebuggableObject):
    def debugs(self, f_args: Optional[Dict[str, Any]]) -> None:
        self._logDebug(f_args)

    def warns(self, f_args: Optional[Dict[str, Any]]) -> None:
        self._logWarning(f_args)

    def errors(self, f_args: Optional[Dict[str, Any]]) -> None:
        self._logError(f_args)

    def dumps(self, f_args: Optional[Dict[str, Any]]) -> None:
        self._dumpConsole(f_args)


class DebuggableObjectTest(TestCase):
    def setUp(self) -> None:
        f_saved_output = Log().output
        f_saved_level = Log.getLevel()

        def f_restore() -> None:
            Log().output = f_saved_output
            Log.setLevel(f_saved_level)

        self.addCleanup(f_restore)
        Log().output = StringIO()
        Log.setLevel(LogLevel.WARNING)

    def _logged(self) -> str:
        return Log().output.getvalue()

    def testComposeLogTraceback(self) -> None:
        """A _trace_back entry is rendered after the parts, caller dict intact."""
        try:
            raise ValueError("boom")
        except ValueError as f_err:
            f_tb = f_err.__traceback__
        f_file = f_tb.tb_frame.f_code.co_filename
        f_dict = {"a": 1, "_trace_back": f_tb, "b": 2}
        f_before = dict(f_dict)
        with self.subTest(row="A1 one frame"):
            Log().output = StringIO()
            Probe().warns(f_dict)
            self.assertEqual(
                self._logged(),
                "lsmiotool: WARNING: Probe::warns(): a=1, b=2\n"
                f'  File  "{f_file}", line {f_tb.tb_lineno}\n'
                '  raise ValueError("boom")\n',
            )
            self.assertEqual(f_dict, f_before)
            self.assertIs(f_dict["_trace_back"], f_tb)

        try:
            _raiseBoom()
        except ValueError as f_err:
            f_tb = f_err.__traceback__
        f_inner = f_tb.tb_next
        with self.subTest(row="A2 two frames"):
            Log().output = StringIO()
            f_dict = {"_trace_back": f_tb}
            Probe().warns(f_dict)
            self.assertEqual(
                self._logged(),
                "lsmiotool: WARNING: Probe::warns(): \n"
                f'  File  "{f_tb.tb_frame.f_code.co_filename}", '
                f"line {f_tb.tb_lineno}\n"
                "  _raiseBoom()\n"
                f'  File  "{f_inner.tb_frame.f_code.co_filename}", '
                f"line {f_inner.tb_lineno}\n"
                '  raise ValueError("boom")\n',
            )
            self.assertEqual(f_dict, {"_trace_back": f_tb})

    def testComposeLogEdgeParts(self) -> None:
        """A falsy _trace_back is an ordinary part; empty keys and values work."""
        f_rows = (
            (
                "A3 falsy trace",
                {"_trace_back": None, "x": ""},
                "lsmiotool: WARNING: Probe::warns(): _trace_back=None, x=\n",
            ),
            (
                "A4 empty key/value",
                {"": ""},
                "lsmiotool: WARNING: Probe::warns(): =\n",
            ),
        )
        for f_name, f_dict, f_expected in f_rows:
            with self.subTest(row=f_name):
                Log().output = StringIO()
                Probe().warns(f_dict)
                self.assertEqual(self._logged(), f_expected)

    def testLevelGating(self) -> None:
        """Each _log* method emits only at or above its own level."""
        f_dbg = "lsmiotool: DEBUG: Probe::debugs(): "
        f_wrn = "lsmiotool: WARNING: Probe::warns(): "
        f_err = "lsmiotool: ERROR: Probe::errors(): "
        f_rows = (
            ("B1", LogLevel.DEBUG, "debugs", None, f_dbg + "\n"),
            ("B2", LogLevel.DEBUG, "debugs", {"a": 1}, f_dbg + "a=1\n"),
            ("B3", LogLevel.DEBUG, "debugs", {}, f_dbg + "\n"),
            ("B4", LogLevel.INFO, "debugs", {"a": 1}, f_dbg + "a=1\n"),
            ("B5", LogLevel.WARNING, "debugs", {"a": 1}, ""),
            ("B6", LogLevel.WARNING, "warns", None, f_wrn + "\n"),
            ("B7", LogLevel.ERROR, "warns", {"b": 2}, ""),
            ("B8", LogLevel.ERROR, "errors", None, f_err + "\n"),
            ("B9", LogLevel.INFO, "errors", {"c": 3}, f_err + "c=3\n"),
        )
        for f_name, f_level, f_method, f_args, f_expected in f_rows:
            with self.subTest(row=f_name):
                Log().output = StringIO()
                Log.setLevel(f_level)
                getattr(Probe(), f_method)(f_args)
                self.assertEqual(self._logged(), f_expected)
                self.assertEqual(Log.getLevel(), f_level)

    def testDumpConsole(self) -> None:
        """_dumpConsole writes to stderr only and is not level-gated."""
        f_rows = (
            ("D1", LogLevel.WARNING, None, "lsmiotool: Probe::dumps(): \n"),
            (
                "D2",
                LogLevel.WARNING,
                {"a": 1, "b": ""},
                "lsmiotool: Probe::dumps(): a=1, b=\n",
            ),
            ("D3", LogLevel.ERROR, {"a": 1}, "lsmiotool: Probe::dumps(): a=1\n"),
        )
        for f_name, f_level, f_args, f_expected in f_rows:
            with self.subTest(row=f_name):
                Log().output = StringIO()
                Log.setLevel(f_level)
                with patch("sys.stderr", new_callable=StringIO) as f_stderr:
                    Probe().dumps(f_args)
                self.assertEqual(f_stderr.getvalue(), f_expected)
                self.assertEqual(self._logged(), "")
                self.assertEqual(Log.getLevel(), f_level)

    def testStrReturnsClassName(self) -> None:
        """__str__ returns the class name."""
        self.assertEqual(str(Probe()), "Probe")
        self.assertEqual(Probe.__str__(), "Probe")
