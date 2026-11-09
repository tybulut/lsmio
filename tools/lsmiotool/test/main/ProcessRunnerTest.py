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

    def testLogIsWrittenWhileProcessRuns(self) -> None:
        """Output reaches the log as it is produced (like 'CMD 2>&1 | tee LOG'), so a
        step killed at its time limit still leaves what it printed; both streams are kept."""
        import threading

        f_log_path = os.path.join(self.m_temp_dir.name, "live.log")
        f_argv = [
            sys.executable,
            "-c",
            "import sys, time; print('first', flush=True); "
            "sys.stderr.write('warn\\n'); sys.stderr.flush(); time.sleep(30)",
        ]
        f_result: Dict[str, Any] = {}
        f_thread = threading.Thread(
            target=lambda: f_result.update(
                res=self.m_runner.run(f_argv, f_log_path=f_log_path, f_timeout=3)
            )
        )
        f_thread.start()
        f_deadline = time.monotonic() + 2.5
        f_content = ""
        while time.monotonic() < f_deadline:
            if os.path.exists(f_log_path):
                with open(f_log_path) as f_f:
                    f_content = f_f.read()
                if "first" in f_content and "warn" in f_content:
                    break
            time.sleep(0.05)
        self.assertTrue(f_thread.is_alive(), "process should still be running")
        self.assertIn("first\n", f_content)
        self.assertIn("warn\n", f_content)
        f_thread.join()
        f_res = f_result["res"]
        self.assertTrue(f_res.timed_out)
        self.assertEqual(f_res.stdout, "first\n")
        self.assertEqual(f_res.stderr, "warn\n")
        with open(f_log_path) as f_f:
            self.assertEqual(sorted(f_f.read().splitlines()), ["first", "warn"])

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

        # Long enough for the child to start and print under a loaded parallel ctest run
        f_start = time.monotonic()
        f_result = self.m_runner.run(f_argv, f_timeout=0.5)
        f_wall_elapsed = time.monotonic() - f_start

        self.assertTrue(f_result.timed_out)
        self.assertTrue(f_result.timedOut)
        self.assertFalse(f_result.is_success)
        self.assertFalse(f_result.isSuccess)
        self.assertTrue(f_result.is_signal)
        # Bounded in wall elapsed time (significantly less than the 60-second sleep)
        self.assertLess(f_wall_elapsed, 5.0)
        self.assertLess(f_result.elapsed_seconds, 5.0)
        self.assertGreaterEqual(f_result.elapsed_seconds, 0.45)
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

    def testProcessRunnerArgvNotIterable(self) -> None:
        """Validates that non-iterable argv raises ProcessSpawnError."""
        for f_bad in [12345, object()]:
            with self.subTest(bad=f_bad):
                with self.assertRaises(ProcessSpawnError) as f_cm:
                    self.m_runner.run(f_bad)  # type: ignore
                self.assertIn(
                    "Process argv must be an iterable sequence of arguments",
                    str(f_cm.exception),
                )

    def testProcessRunnerUnexpectedPopenException(self) -> None:
        """Validates unexpected (non-OSError) exception in subprocess.Popen raises ProcessSpawnError with cause."""
        with patch(
            "subprocess.Popen", side_effect=RuntimeError("Subprocess memory error")
        ):
            with self.assertRaises(ProcessSpawnError) as f_cm:
                self.m_runner.run(["/bin/echo", "test"])
            self.assertIn(
                "Unexpected error spawning process '/bin/echo': Subprocess memory error",
                str(f_cm.exception),
            )
            self.assertIsInstance(f_cm.exception.__cause__, RuntimeError)

    def testProcessRunnerTimeoutKillRaisesOSError(self) -> None:
        """Validates that OSError raised by kill() during communicate timeout is swallowed."""
        f_mock_proc = MagicMock()
        f_mock_proc.communicate.side_effect = [
            subprocess.TimeoutExpired(cmd="sleep", timeout=0.1),
            (b"post-timeout", b""),
        ]
        f_mock_proc.kill.side_effect = ProcessLookupError("No such process")
        f_mock_proc.returncode = -9
        with patch("subprocess.Popen", return_value=f_mock_proc):
            f_res = self.m_runner.run(["sleep", "10"], f_timeout=0.1)
            self.assertTrue(f_res.timed_out)
            self.assertEqual(f_res.stdout, "post-timeout")
            self.assertEqual(f_res.returncode, -9)
            self.assertTrue(f_mock_proc.kill.called)

    def testProcessRunnerCommunicateUnexpectedException(self) -> None:
        """Validates unexpected exception in communicate kills process and raises ProcessExecutionError with cause."""
        f_mock_proc = MagicMock()
        f_mock_proc.communicate.side_effect = RuntimeError("Pipe error")
        f_mock_proc.kill.side_effect = ProcessLookupError("gone")
        f_mock_proc.wait.return_value = 1
        with patch("subprocess.Popen", return_value=f_mock_proc):
            with self.assertRaises(ProcessExecutionError) as f_cm:
                self.m_runner.run(["/bin/test_cmd"])
            self.assertIn(
                "Communication error during process execution '/bin/test_cmd': Pipe error",
                str(f_cm.exception),
            )
            self.assertIsInstance(f_cm.exception.__cause__, RuntimeError)
            self.assertTrue(f_mock_proc.kill.called)
            self.assertTrue(f_mock_proc.wait.called)

    def testProcessRunnerLogFileCloseRaisesOSError(self) -> None:
        """Validates that OSError on log file close in finally block is swallowed without masking result."""
        f_log_path = os.path.join(self.m_temp_dir.name, "test_close_err.log")
        f_real_open = open

        class _MockFileWrapper:
            def __init__(self, f):
                self._f = f

            def write(self, b):
                return self._f.write(b)

            def flush(self):
                return self._f.flush()

            def fileno(self):
                return self._f.fileno()

            def close(self):
                self._f.close()
                raise OSError("NFS flush error")

        def _custom_open(path, mode="r", *args, **kwargs):
            f = f_real_open(path, mode, *args, **kwargs)
            if "test_close_err.log" in str(path):
                return _MockFileWrapper(f)
            return f

        with patch("builtins.open", side_effect=_custom_open):
            f_res = self.m_runner.run(
                [sys.executable, "-c", "print('hello')"],
                f_log_path=f_log_path,
            )
            self.assertEqual(f_res.returncode, 0)
            self.assertEqual(f_res.stdout, "hello\n")

    def testProcessRunnerMirrorStdoutEmptyStreams(self) -> None:
        """Validates branches 518->521 (empty stdout) and 521->528 (empty stderr) during console mirroring."""
        with self.subTest(stream="stderr_only"):
            with (
                patch("sys.stdout", new_callable=io.StringIO) as f_mock_stdout,
                patch("sys.stderr", new_callable=io.StringIO) as f_mock_stderr,
            ):
                f_res = self.m_runner.run(
                    [sys.executable, "-c", "import sys; sys.stderr.write('err\\n')"],
                    f_mirror_stdout=True,
                )
                self.assertEqual(f_res.stdout, "")
                self.assertEqual(f_res.stderr, "err\n")
                self.assertEqual(f_mock_stdout.getvalue(), "")
                self.assertEqual(f_mock_stderr.getvalue(), "err\n")

        with self.subTest(stream="stdout_only"):
            with (
                patch("sys.stdout", new_callable=io.StringIO) as f_mock_stdout,
                patch("sys.stderr", new_callable=io.StringIO) as f_mock_stderr,
            ):
                f_res = self.m_runner.run(
                    [sys.executable, "-c", "import sys; sys.stdout.write('out\\n')"],
                    f_mirror_stdout=True,
                )
                self.assertEqual(f_res.stdout, "out\n")
                self.assertEqual(f_res.stderr, "")
                self.assertEqual(f_mock_stdout.getvalue(), "out\n")
                self.assertEqual(f_mock_stderr.getvalue(), "")

    def testProcessRunnerMirrorStdoutWriteException(self) -> None:
        """Validates that sys.stdout.write exception during mirroring is swallowed without masking outcome."""
        with patch("sys.stdout.write", side_effect=IOError("Broken pipe")):
            f_res = self.m_runner.run(
                [sys.executable, "-c", "print('out')"],
                f_mirror_stdout=True,
            )
            self.assertEqual(f_res.returncode, 0)
            self.assertEqual(f_res.stdout, "out\n")

    def testProcessRunnerStreamToLogWriteErrorAndDrain(self) -> None:
        """Validates _streamToLog multi-chunk write error, error collection, drain continuation, and fsync skip."""

        class _MockPipe:
            def __init__(self, chunks):
                self._chunks = list(chunks)

            def read1(self, size: int) -> bytes:
                if self._chunks:
                    return self._chunks.pop(0)
                return b""

            def close(self) -> None:
                pass

        class _MockLogFile:
            def __init__(self):
                self.writes = 0

            def fileno(self) -> int:
                return 1

            def write(self, chunk: bytes) -> int:
                self.writes += 1
                if self.writes == 1:
                    raise OSError("Disk write failure")
                return len(chunk)

            def flush(self) -> None:
                pass

        f_mock_proc = MagicMock()
        f_mock_proc.stdout = _MockPipe([b"chunk1", b"chunk2"])
        f_mock_proc.stderr = _MockPipe([])
        f_mock_proc.wait.return_value = 0

        f_mock_log = _MockLogFile()
        f_out, f_err, f_timed_out, f_err_res = ProcessRunner._streamToLog(
            f_mock_proc, f_mock_log, None
        )
        self.assertEqual(f_out, b"chunk1chunk2")
        self.assertEqual(f_err, b"")
        self.assertFalse(f_timed_out)
        self.assertIsInstance(f_err_res, OSError)
        self.assertIn("Disk write failure", str(f_err_res))

    def testProcessRunnerStreamToLogTimeoutKillRaisesOSError(self) -> None:
        """Validates that _streamToLog swallows OSError raised by f_proc.kill() on timeout."""

        class _MockPipe:
            def read1(self, size: int) -> bytes:
                return b""

            def close(self) -> None:
                pass

        class _MockLogFile:
            def fileno(self) -> int:
                return 1

            def flush(self) -> None:
                pass

        f_mock_proc = MagicMock()
        f_mock_proc.stdout = _MockPipe()
        f_mock_proc.stderr = _MockPipe()
        f_mock_proc.wait.side_effect = [
            subprocess.TimeoutExpired(cmd="sleep", timeout=0.1),
            0,
        ]
        f_mock_proc.kill.side_effect = ProcessLookupError("gone")

        f_mock_log = _MockLogFile()
        with patch("os.fsync"):
            f_out, f_err, f_timed_out, f_err_res = ProcessRunner._streamToLog(
                f_mock_proc, f_mock_log, 0.1
            )
            self.assertEqual(f_out, b"")
            self.assertEqual(f_err, b"")
            self.assertTrue(f_timed_out)
            self.assertIsNone(f_err_res)
            self.assertTrue(f_mock_proc.kill.called)


class ProcessResultContractTest(unittest.TestCase):
    """Contract tests for ProcessResult unfrozen mutations, scalar properties, and equality."""

    def testProcessResultUnfrozenSetattr(self) -> None:
        """Validates that unfrozen ProcessResult allows setting attributes via super().__setattr__."""
        f_res = ProcessResult.__new__(ProcessResult)
        f_res.m_returncode = 42
        self.assertEqual(f_res.m_returncode, 42)

        f_res2 = ProcessResult(0)
        object.__setattr__(f_res2, "_frozen", False)
        f_res2.m_returncode = 99
        self.assertEqual(f_res2.m_returncode, 99)

    def testProcessResultUnfrozenDelattr(self) -> None:
        """Validates that unfrozen ProcessResult allows deleting attributes via super().__delattr__."""
        f_res = ProcessResult.__new__(ProcessResult)
        f_res.m_returncode = 42
        self.assertTrue(hasattr(f_res, "m_returncode"))
        del f_res.m_returncode
        self.assertFalse(hasattr(f_res, "m_returncode"))

        f_res2 = ProcessResult(0)
        object.__setattr__(f_res2, "_frozen", False)
        self.assertTrue(hasattr(f_res2, "m_returncode"))
        del f_res2.m_returncode
        self.assertFalse(hasattr(f_res2, "m_returncode"))

    def testProcessResultAliasProperties(self) -> None:
        """Validates alias properties: elapsedSeconds, spawn_error, spawnError."""
        f_res = ProcessResult(
            f_returncode=127,
            f_elapsed_seconds=2.718,
            f_spawn_error="binary not found",
        )
        self.assertEqual(f_res.elapsedSeconds, 2.718)
        self.assertEqual(f_res.spawn_error, "binary not found")
        self.assertEqual(f_res.spawnError, "binary not found")

    def testProcessResultEqualityNonProcessResult(self) -> None:
        """Validates equality comparisons between ProcessResult and non-ProcessResult objects return False."""
        f_res = ProcessResult(f_returncode=0)
        for f_other in [None, 0, "ProcessResult", {}, object()]:
            with self.subTest(other=f_other):
                self.assertFalse(f_res == f_other)
                self.assertTrue(f_res != f_other)


if __name__ == "__main__":
    unittest.main()
