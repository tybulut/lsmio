#
# Copyright 2026 Serdar Bulut
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

import io
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional
import unittest
from unittest.mock import MagicMock, patch

from lsmiotool.lib.worker import (
    ProcessExecutionError,
    ProcessLoggingError,
    ProcessResult,
    ProcessRunner,
    ProcessSpawnError,
    ProcessTimeoutError,
    WorkerError,
)


class ProcessRunnerTest(unittest.TestCase):
    """Unit test suite for ProcessRunner and ProcessResult contract and invariants."""

    def setUp(self) -> None:
        self.m_runner = ProcessRunner()
        self.m_temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.m_temp_dir.cleanup()

    def testStatusSurvivesMirroring(self) -> None:
        """Confirms exit codes (0, 1, 42, 127) survive stdout/stderr mirroring and logging."""
        f_test_codes = [0, 1, 42, 127]
        for f_code in f_test_codes:
            f_log_path = os.path.join(self.m_temp_dir.name, f"test_status_{f_code}.log")
            f_script = (
                f"import sys; "
                f"sys.stdout.write('STDOUT_MSG_{f_code}\\n'); "
                f"sys.stderr.write('STDERR_MSG_{f_code}\\n'); "
                f"sys.exit({f_code})"
            )
            f_argv = [sys.executable, "-c", f_script]

            # Test without mirroring
            f_res_no_mirror = self.m_runner.run(f_argv, f_log_path=f_log_path)
            self.assertEqual(f_res_no_mirror.returncode, f_code)
            self.assertEqual(f_res_no_mirror.returnCode, f_code)
            self.assertIn(f"STDOUT_MSG_{f_code}", f_res_no_mirror.stdout)
            self.assertIn(f"STDERR_MSG_{f_code}", f_res_no_mirror.stderr)
            if f_code == 0:
                self.assertTrue(f_res_no_mirror.is_success)
                self.assertTrue(f_res_no_mirror.isSuccess)
            else:
                self.assertFalse(f_res_no_mirror.is_success)
                self.assertFalse(f_res_no_mirror.isSuccess)
            self.assertFalse(f_res_no_mirror.is_signal)
            self.assertFalse(f_res_no_mirror.isSignal)
            self.assertIsNone(f_res_no_mirror.signal_number)
            self.assertIsNone(f_res_no_mirror.signalNumber)

            # Check log file contains output
            self.assertTrue(os.path.exists(f_log_path))
            with open(f_log_path, "r", encoding="utf-8") as f_f:
                f_content = f_f.read()
            self.assertIn(f"STDOUT_MSG_{f_code}", f_content)
            self.assertIn(f"STDERR_MSG_{f_code}", f_content)

            # Test with mirroring enabled
            f_mirror_log_path = os.path.join(
                self.m_temp_dir.name, f"test_mirror_status_{f_code}.log"
            )
            f_stdout_capture = io.StringIO()
            f_stderr_capture = io.StringIO()
            with (
                patch("sys.stdout", f_stdout_capture),
                patch("sys.stderr", f_stderr_capture),
            ):
                f_res_mirror = self.m_runner.run(
                    f_argv,
                    f_log_path=f_mirror_log_path,
                    f_mirror_stdout=True,
                )

            self.assertEqual(f_res_mirror.returncode, f_code)
            self.assertEqual(f_res_mirror.returnCode, f_code)
            self.assertIn(f"STDOUT_MSG_{f_code}", f_res_mirror.stdout)
            self.assertIn(f"STDERR_MSG_{f_code}", f_res_mirror.stderr)
            self.assertIn(f"STDOUT_MSG_{f_code}", f_stdout_capture.getvalue())
            self.assertIn(f"STDERR_MSG_{f_code}", f_stderr_capture.getvalue())

    def testSignalAndSpawn(self) -> None:
        """Validates handling of negative signal return codes (-9, -15) and binary spawn failures."""
        # Test negative signal return codes (SIGKILL = 9, SIGTERM = 15)
        f_signals = [signal.SIGKILL, signal.SIGTERM]
        for f_sig in f_signals:
            f_script = f"import os, signal; os.kill(os.getpid(), signal.{f_sig.name})"
            f_argv = [sys.executable, "-c", f_script]
            f_result = self.m_runner.run(f_argv)

            self.assertEqual(f_result.returncode, -int(f_sig))
            self.assertTrue(f_result.is_signal)
            self.assertTrue(f_result.isSignal)
            self.assertEqual(f_result.signal_number, int(f_sig))
            self.assertEqual(f_result.signalNumber, int(f_sig))
            self.assertFalse(f_result.is_success)

        # Test spawn failure with non-existent executable
        f_non_existent = os.path.join(
            self.m_temp_dir.name, "non_existent_binary_xyz_123"
        )
        with self.assertRaises(ProcessSpawnError) as f_ctx:
            self.m_runner.run([f_non_existent, "arg1"])
        self.assertIn(f_non_existent, str(f_ctx.exception))

        # Test spawn failure with non-executable file (Permission denied)
        f_unexecutable = os.path.join(self.m_temp_dir.name, "unexecutable_file.bin")
        with open(f_unexecutable, "w") as f_f:
            f_f.write("#!/bin/sh\necho test\n")
        os.chmod(
            f_unexecutable, stat.S_IRUSR | stat.S_IWUSR
        )  # 0o600 no execute permission

        with self.assertRaises(ProcessSpawnError) as f_ctx2:
            self.m_runner.run([f_unexecutable])
        self.assertIn(f_unexecutable, str(f_ctx2.exception))

    def testLogFailures(self) -> None:
        """Verifies that file logging write/flush errors raise ProcessLoggingError or explicit infrastructure failure."""
        f_argv = [sys.executable, "-c", "import sys; sys.stdout.write('sample\\n')"]

        # Non-existent parent directory
        f_invalid_log_path = os.path.join(
            self.m_temp_dir.name, "non_existent_sub_dir_12345", "test.log"
        )
        with self.assertRaises(ProcessLoggingError) as f_ctx1:
            self.m_runner.run(f_argv, f_log_path=f_invalid_log_path)
        self.assertIn(f_invalid_log_path, str(f_ctx1.exception))
        # Ensure partial result is captured in exception
        self.assertIsNotNone(f_ctx1.exception.result)
        self.assertEqual(f_ctx1.exception.result.returncode, 0)
        self.assertEqual(f_ctx1.exception.result.stdout, "sample\n")

        # Mocked write/flush/fsync failure
        f_log_path = os.path.join(self.m_temp_dir.name, "valid.log")
        with patch("os.fsync", side_effect=OSError("Disk write error")):
            with self.assertRaises(ProcessLoggingError) as f_ctx2:
                self.m_runner.run(f_argv, f_log_path=f_log_path)
            self.assertIn("Disk write error", str(f_ctx2.exception))
            self.assertIsNotNone(f_ctx2.exception.result)

    def testLiteralAdversarialArgv(self) -> None:
        """Proves tokens with spaces, $VAR, ;, |, and newlines are executed literally and not interpreted by a shell."""
        f_adversarial_args = [
            "arg with spaces",
            "$HOME",
            "${USER}",
            "; echo injected",
            "&& rm -rf /",
            "| grep foo",
            "> /tmp/should_not_exist",
            "< /dev/null",
            "single'quote",
            'double"quote',
            "newline\nseparated\nline",
            "carriage\rreturn",
            "tab\tcharacter",
            "wildcard*.py",
            "tilde~",
            "--flag=value with spaces",
        ]

        f_script = "import sys, json; sys.stdout.write(json.dumps(sys.argv[1:]))"
        f_argv = [sys.executable, "-c", f_script] + f_adversarial_args

        f_result = self.m_runner.run(f_argv)
        self.assertEqual(f_result.returncode, 0)
        self.assertTrue(f_result.is_success)

        f_received_args = json.loads(f_result.stdout)
        self.assertEqual(len(f_received_args), len(f_adversarial_args))
        for f_expected, f_actual in zip(f_adversarial_args, f_received_args):
            self.assertEqual(f_expected, f_actual)

    def testNoShellOrPipeline(self) -> None:
        """Spies on subprocess.Popen to ensure shell=True is NEVER passed and argv is a sequence."""
        f_argv = [sys.executable, "-c", "import sys; print('no shell')"]

        with patch("subprocess.Popen", wraps=subprocess.Popen) as f_spy_popen:
            f_result = self.m_runner.run(f_argv)
            self.assertEqual(f_result.returncode, 0)

            self.assertEqual(f_spy_popen.call_count, 1)
            f_args, f_kwargs = f_spy_popen.call_args

            # Verify shell=False or not True
            self.assertFalse(f_kwargs.get("shell", False))
            self.assertIs(f_kwargs.get("shell"), False)

            # Verify argv passed to Popen is a list/sequence of discrete strings, not a single shell string
            f_called_argv = f_args[0] if f_args else f_kwargs.get("args")
            self.assertIsInstance(f_called_argv, list)
            self.assertEqual(f_called_argv, f_argv)
            for f_token in f_called_argv:
                self.assertIsInstance(f_token, str)

    def testTimeoutHandling(self) -> None:
        """Validates that a process exceeding timeout is terminated and flagged timed_out=True."""
        f_script = "import time; time.sleep(10)"
        f_argv = [sys.executable, "-c", f_script]

        f_result = self.m_runner.run(f_argv, f_timeout=0.1)
        self.assertTrue(f_result.timed_out)
        self.assertTrue(f_result.timedOut)
        self.assertFalse(f_result.is_success)
        self.assertGreater(f_result.elapsed_seconds, 0.0)

    def testRealHungChildKilledAndTimedOut(self) -> None:
        """Proves that a real hung child process ignoring SIGTERM is killed via SIGKILL and bounded in real elapsed time."""
        # A real hung script that would sleep 60s
        f_hung_script = (
            "import time, signal, sys\n"
            "try:\n"
            "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "except Exception:\n"
            "    pass\n"
            "sys.stdout.write('STARTED\\n')\n"
            "sys.stdout.flush()\n"
            "time.sleep(60)\n"
        )
        f_argv = [sys.executable, "-c", f_hung_script]

        f_start = time.monotonic()
        f_result = self.m_runner.run(f_argv, f_timeout=0.2)
        f_wall_elapsed = time.monotonic() - f_start

        self.assertTrue(f_result.timed_out)
        self.assertTrue(f_result.timedOut)
        self.assertFalse(f_result.is_success)
        self.assertFalse(f_result.isSuccess)
        self.assertTrue(f_result.is_signal)
        # Bounded in wall elapsed time (significantly less than the 60-second sleep)
        self.assertLess(f_wall_elapsed, 5.0)
        self.assertLess(f_result.elapsed_seconds, 5.0)
        self.assertGreaterEqual(f_result.elapsed_seconds, 0.15)
        self.assertIn("STARTED", f_result.stdout)

    def testCustomEnvironmentAndCwd(self) -> None:
        """Validates execution with custom environment variables and working directory."""
        f_script = (
            "import os, json, sys; "
            "sys.stdout.write(json.dumps({'cwd': os.getcwd(), 'env_val': os.environ.get('MY_CUSTOM_VAR')}))"
        )
        f_argv = [sys.executable, "-c", f_script]
        f_custom_cwd = self.m_temp_dir.name
        f_custom_env = dict(os.environ)
        f_custom_env["MY_CUSTOM_VAR"] = "test_custom_value_42"

        f_result = self.m_runner.run(
            f_argv,
            f_cwd=f_custom_cwd,
            f_env=f_custom_env,
        )

        self.assertEqual(f_result.returncode, 0)
        f_data = json.loads(f_result.stdout)
        self.assertEqual(
            os.path.realpath(f_data["cwd"]), os.path.realpath(f_custom_cwd)
        )
        self.assertEqual(f_data["env_val"], "test_custom_value_42")

    def testArgvValidation(self) -> None:
        """Validates rejection of invalid argv types, empty argv, and NUL bytes."""
        with self.assertRaises(ProcessSpawnError):
            self.m_runner.run("string_command_not_allowed")  # type: ignore

        with self.assertRaises(ProcessSpawnError):
            self.m_runner.run(b"bytes_not_allowed")  # type: ignore

        with self.assertRaises(ProcessSpawnError):
            self.m_runner.run([])

        with self.assertRaises(ProcessSpawnError):
            self.m_runner.run([sys.executable, "arg\0with_nul"])

        with self.assertRaises(ProcessSpawnError):
            self.m_runner.run([sys.executable, None])  # type: ignore

    def testLogPathValidation(self) -> None:
        """Validates rejection of empty or NUL-containing log path."""
        f_argv = [sys.executable, "-c", "print('hello')"]
        with self.assertRaises(ProcessLoggingError):
            self.m_runner.run(f_argv, f_log_path="")

        with self.assertRaises(ProcessLoggingError):
            self.m_runner.run(f_argv, f_log_path="path\0with_nul")

    def testKwargsAliases(self) -> None:
        """Validates support for keyword argument aliases."""
        f_script = "import os, sys; sys.stdout.write(os.environ.get('ALIAS_VAR', ''))"
        f_argv = [sys.executable, "-c", f_script]
        f_log_path = os.path.join(self.m_temp_dir.name, "alias.log")

        f_result = self.m_runner.run(
            f_argv,
            cwd=self.m_temp_dir.name,
            env={**os.environ, "ALIAS_VAR": "alias_value"},
            log_path=f_log_path,
            mirror_stdout=False,
            timeout=5.0,
        )

        self.assertEqual(f_result.returncode, 0)
        self.assertEqual(f_result.stdout, "alias_value")
        self.assertTrue(os.path.exists(f_log_path))

    def testProcessResultImmutability(self) -> None:
        """Validates that ProcessResult instances cannot be mutated or have attributes deleted."""
        f_res = ProcessResult(
            f_returncode=0,
            f_stdout="out",
            f_stderr="err",
            f_elapsed_seconds=1.23,
            f_timed_out=False,
            f_spawn_error=None,
        )

        with self.assertRaises(AttributeError):
            f_res.returncode = 1  # type: ignore

        with self.assertRaises(AttributeError):
            f_res.stdout = "new"  # type: ignore

        with self.assertRaises(AttributeError):
            del f_res.returncode  # type: ignore

        # Equality and repr tests
        f_res2 = ProcessResult(
            f_returncode=0,
            f_stdout="out",
            f_stderr="err",
            f_elapsed_seconds=1.23,
            f_timed_out=False,
            f_spawn_error=None,
        )
        self.assertEqual(f_res, f_res2)
        self.assertIn("ProcessResult", repr(f_res))
        self.assertIn("returncode=0", repr(f_res))

        f_dict = f_res.toDict()
        self.assertEqual(f_dict["returncode"], 0)
        self.assertEqual(f_dict["stdout"], "out")
        self.assertEqual(f_dict["stderr"], "err")
        self.assertTrue(f_dict["is_success"])
        self.assertFalse(f_dict["is_signal"])
        self.assertIsNone(f_dict["signal_number"])

    def testExceptionHierarchy(self) -> None:
        """Validates exception class hierarchy."""
        self.assertTrue(issubclass(ProcessExecutionError, WorkerError))
        self.assertTrue(issubclass(ProcessSpawnError, ProcessExecutionError))
        self.assertTrue(issubclass(ProcessLoggingError, ProcessExecutionError))
        self.assertTrue(issubclass(ProcessTimeoutError, ProcessExecutionError))
        self.assertTrue(issubclass(WorkerError, Exception))


if __name__ == "__main__":
    unittest.main()
