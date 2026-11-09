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

"""Detached runs (lib/detach.py), the orchestrator pid file, and 'lsmiotool cancel'."""

import builtins
import io
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import call, patch

from lsmiotool.lib import detach
from lsmiotool.lib.detach import (
    FOLLOW_INTERVAL_SECONDS,
    consoleLogFor,
    consoleLogPath,
    detachAndFollow,
)
from lsmiotool.lib.main import CancelMain
from lsmiotool.lib.run import (
    liveOrchestratorMessage,
    orchestratorRunning,
    readOrchestratorPid,
    removeOrchestratorPid,
    writeOrchestratorPid,
)

TOOLS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

# A stand-in for 'lsmiotool run': prints, detaches, then runs as the detached child.
# Its file name puts "lsmiotool" in the command line, as for the real tool.
PROBE = """
import os, sys, time
sys.path.insert(0, sys.argv[1])
from lsmiotool.lib.detach import detachAndFollow
root, mode = sys.argv[2], sys.argv[3]
os.makedirs(os.path.join(root, "control"), exist_ok=True)
print("before detaching", flush=True)
detachAndFollow([root])
print("child session leader:", os.getsid(0) == os.getpid(), flush=True)
if mode == "exit":
    sys.exit(3)
while True:
    time.sleep(0.2)
"""


class DetachTest(unittest.TestCase):
    def setUp(self) -> None:
        self.m_tmp = tempfile.TemporaryDirectory()
        self.m_root = os.path.join(self.m_tmp.name, "runs", "run-x")
        os.makedirs(os.path.join(self.m_root, "control"))
        with open(os.path.join(self.m_root, "manifest.json"), "w") as f_f:
            f_f.write("{}")
        self.m_probe = os.path.join(self.m_tmp.name, "lsmiotool_detach_probe.py")
        with open(self.m_probe, "w") as f_f:
            f_f.write(PROBE)

    def tearDown(self) -> None:
        f_doc = readOrchestratorPid(self.m_root)
        if f_doc and orchestratorRunning(f_doc):
            os.kill(int(f_doc["pid"]), signal.SIGKILL)
        self.m_tmp.cleanup()

    def _start(self, f_mode: str) -> subprocess.Popen:
        return subprocess.Popen(
            [sys.executable, self.m_probe, TOOLS_DIR, self.m_root, f_mode],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

    def _childPid(self, f_timeout: float = 20.0) -> Optional[int]:
        f_deadline = time.monotonic() + f_timeout
        while time.monotonic() < f_deadline:
            f_doc = readOrchestratorPid(self.m_root)
            if f_doc:
                return int(f_doc["pid"])
            time.sleep(0.1)
        return None

    def testFollowerShowsTheDetachedRunAndExitsWithItsStatus(self) -> None:
        """The run goes on in its own session with its output in control/console.log; the
        terminal side follows that log and exits with the run's status."""
        f_proc = self._start("exit")
        f_out, _ = f_proc.communicate(timeout=60)
        f_text = f_out.decode()
        self.assertEqual(f_proc.returncode, 3, f_text)
        self.assertIn("before detaching", f_text)
        self.assertIn("Run detached (PID", f_text)
        self.assertIn(f"stop it with: lsmiotool cancel {self.m_root}", f_text)
        self.assertIn("child session leader: True", f_text)
        with open(consoleLogPath(self.m_root)) as f_f:
            f_log = f_f.read()
        self.assertIn("detached from the terminal", f_log)
        self.assertIn(f"  run root: {self.m_root}", f_log)
        self.assertIn(f"  stop it:  lsmiotool cancel {self.m_root}", f_log)
        self.assertIn("child session leader: True", f_log)
        self.assertNotIn("before detaching", f_log)

    def testCtrlCStopsFollowingAndCancelStopsTheRun(self) -> None:
        """Ctrl-C ends only the follower; 'lsmiotool cancel' then stops the run."""
        f_proc = self._start("wait")
        f_pid = self._childPid()
        self.assertIsNotNone(f_pid)
        time.sleep(0.5)
        f_proc.send_signal(signal.SIGINT)
        f_out, _ = f_proc.communicate(timeout=30)
        self.assertEqual(f_proc.returncode, 0)
        self.assertIn("Stopped following; the run goes on", f_out.decode())
        self.assertIn(f"lsmiotool cancel {self.m_root}", f_out.decode())
        self.assertTrue(orchestratorRunning(readOrchestratorPid(self.m_root)))

        with patch("sys.stdout", new_callable=io.StringIO) as f_msg:
            self.assertEqual(CancelMain(self.m_root, f_wait=20).run(), 0)
        self.assertIn("Stopped.", f_msg.getvalue())
        self.assertFalse(orchestratorRunning(readOrchestratorPid(self.m_root)))


class RunMainDetachTest(unittest.TestCase):
    """Detaching is opt-in: only the launchers ask for it, so tests and other callers of
    RunMain never fork, even with a terminal stdout."""

    def _kwargs(self, **f_main_kwargs: Any) -> Dict[str, Any]:
        from lsmiotool.lib.main import RunMain
        from lsmiotool.lib.run import RunRequest

        f_seen: Dict[str, Any] = {}

        class FakeOrchestrator:
            exitCode = 0

            def execute(self, **f_kw: Any) -> None:
                f_seen.update(f_kw)

        with patch("lsmiotool.lib.main._stdoutIsTerminal", return_value=True):
            f_rc = RunMain(
                f_request=RunRequest("lsmio", "local"),
                f_orchestrator_factory=lambda **f_kw: FakeOrchestrator(),
                **f_main_kwargs,
            ).run()
        self.assertEqual(f_rc, 0)
        return f_seen

    def testNoDetachUnlessAsked(self) -> None:
        self.assertNotIn("f_on_ready", self._kwargs())

    def testDetachWhenAskedFromATerminal(self) -> None:
        from lsmiotool.lib.detach import detachAndFollow

        self.assertIs(self._kwargs(f_detach=True)["f_on_ready"], detachAndFollow)


class OrchestratorPidTest(unittest.TestCase):
    def setUp(self) -> None:
        self.m_tmp = tempfile.TemporaryDirectory()
        self.m_roots: List[str] = []
        for f_name in ("run-a", "run-b"):
            f_root = os.path.join(self.m_tmp.name, f_name)
            os.makedirs(os.path.join(f_root, "control"))
            self.m_roots.append(f_root)

    def tearDown(self) -> None:
        self.m_tmp.cleanup()

    def testWriteReadRemove(self) -> None:
        writeOrchestratorPid(self.m_roots)
        for f_root in self.m_roots:
            f_doc = readOrchestratorPid(f_root)
            self.assertEqual(f_doc["pid"], os.getpid())
            self.assertEqual(f_doc["host"], socket.gethostname())
        # Only this process's own record is removed
        removeOrchestratorPid(self.m_roots, f_pid=os.getpid() + 1)
        self.assertIsNotNone(readOrchestratorPid(self.m_roots[0]))
        removeOrchestratorPid(self.m_roots)
        self.assertIsNone(readOrchestratorPid(self.m_roots[0]))

    def testRunningStates(self) -> None:
        f_dead = subprocess.Popen([sys.executable, "-c", "pass"])
        f_dead.wait()
        self.assertFalse(orchestratorRunning(None))
        self.assertFalse(
            orchestratorRunning({"pid": f_dead.pid, "host": socket.gethostname()})
        )
        self.assertIsNone(orchestratorRunning({"pid": 1, "host": "elsewhere.invalid"}))
        # This test process runs lsmiotool's tests, so its command line names lsmiotool
        f_me = {"pid": os.getpid(), "host": socket.gethostname()}
        self.assertTrue(orchestratorRunning(f_me))
        f_now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.assertTrue(orchestratorRunning(dict(f_me, started_at_utc=f_now)))
        # A pid file written before this process started names an earlier process
        self.assertFalse(
            orchestratorRunning(dict(f_me, started_at_utc="2020-01-01T00:00:00Z"))
        )

    def testAnotherUsersProcessIsNotTheRun(self) -> None:
        """A pid reused by another user's process (EPERM) is not this user's run."""
        f_doc = {"pid": 12345, "host": socket.gethostname()}
        with patch("lsmiotool.lib.run.os.kill", side_effect=PermissionError):
            self.assertFalse(orchestratorRunning(f_doc))

    def testPsFallbackStillChecksTheCommandWhenTheDateCannotBeRead(self) -> None:
        """Without /proc (macOS) ps gives the command and start time separately: a start
        time that cannot be parsed still leaves the "lsmiotool" check in force."""
        import builtins

        from lsmiotool.lib import run as run_mod

        f_open = builtins.open

        def no_proc(f_path: Any, *f_args: Any, **f_kwargs: Any) -> Any:
            if str(f_path).startswith("/proc"):
                raise OSError("no /proc")
            return f_open(f_path, *f_args, **f_kwargs)

        f_other = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"]
        )
        try:
            with (
                patch("builtins.open", no_proc),
                patch("time.strptime", side_effect=ValueError),
            ):
                f_cmd, f_start = run_mod._processInfo(f_other.pid)
                self.assertIn("time.sleep", f_cmd)
                self.assertIsNone(f_start)
                self.assertFalse(
                    orchestratorRunning(
                        {"pid": f_other.pid, "host": socket.gethostname()}
                    )
                )
        finally:
            f_other.kill()
            f_other.wait()

    def testArchiveRefusesALiveRun(self) -> None:
        """A run whose orchestrator is alive, or on another host, is not archived."""
        self.assertIsNone(liveOrchestratorMessage(self.m_roots))
        writeOrchestratorPid(self.m_roots[1:])
        self.assertIn("still running", liveOrchestratorMessage(self.m_roots))
        f_path = os.path.join(self.m_roots[1], "control", "orchestrator.pid")
        with open(f_path, "w") as f_f:
            f_f.write('{"pid": 1, "host": "elsewhere.invalid"}')
        self.assertIn(
            "may still be running on host", liveOrchestratorMessage(self.m_roots)
        )

    def testCancelWithoutARunningOrchestrator(self) -> None:
        f_root = self.m_roots[0]
        with open(os.path.join(f_root, "manifest.json"), "w") as f_f:
            f_f.write("{}")
        with patch("sys.stderr", new_callable=io.StringIO) as f_err:
            self.assertEqual(CancelMain(f_root).run(), 1)
        self.assertIn("no lsmiotool run is running", f_err.getvalue())


def _fdIds() -> List[Optional[Tuple[int, int, int]]]:
    """Identify the runner's fds 0, 1 and 2 (None for a closed one)."""
    f_ids: List[Optional[Tuple[int, int, int]]] = []
    for f_fd in (0, 1, 2):
        try:
            f_st = os.fstat(f_fd)
            f_ids.append((f_st.st_dev, f_st.st_ino, f_st.st_mode))
        except OSError:
            f_ids.append(None)
    return f_ids


class _BrokenFlush(io.StringIO):
    """A text stream whose flush counts its calls and fails like a closed pipe."""

    def __init__(self) -> None:
        super().__init__()
        self.m_flushes = 0

    def flush(self) -> None:
        self.m_flushes += 1
        raise OSError(32, "Broken pipe")


class ConsoleLogForTest(unittest.TestCase):
    """consoleLogFor follows the first run of an arm marker's group."""

    def testConsoleLogForFollowsTheFirstArm(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lsmiotool-detach-") as f_tmp:
            f_root = os.path.join(f_tmp, "runs", "run-b")
            os.makedirs(f_root)
            f_own = os.path.join(f_root, "control", "console.log")
            f_marker = os.path.join(f_root, ".lsmiotool-arm.json")
            self.assertEqual(consoleLogFor(f_root), f_own)
            f_rows = [
                (
                    json.dumps({"group_run_ids": ["run-a", "run-b"]}),
                    os.path.join(f_tmp, "runs", "run-a", "control", "console.log"),
                ),
                (
                    json.dumps({"group_run_ids": [7]}),
                    os.path.join(f_tmp, "runs", "7", "control", "console.log"),
                ),
                (json.dumps({"group_run_ids": []}), f_own),
                (json.dumps({"group_run_ids": None}), f_own),
                (json.dumps({}), f_own),
                (json.dumps(["run-a"]), f_own),
                ("{broken", f_own),
                ("", f_own),
            ]
            for f_text, f_expected in f_rows:
                with self.subTest(f_marker=f_text):
                    with open(f_marker, "w", encoding="utf-8") as f_f:
                        f_f.write(f_text)
                    self.assertEqual(consoleLogFor(f_root), f_expected)
            self.assertFalse(os.path.exists(os.path.join(f_root, "control")))


class DetachInProcessTest(unittest.TestCase):
    """In-process tests of detachAndFollow with fork, sessions, fds and exits mocked.

    Deliberately not a DetachTest subclass: DetachTest.tearDown kills the pid in
    control/orchestrator.pid, and the in-process child path records this runner's pid there.
    """

    _SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)

    def setUp(self) -> None:
        self.m_fd_ids = _fdIds()
        f_tmp = tempfile.TemporaryDirectory(prefix="lsmiotool-detach-")
        self.addCleanup(f_tmp.cleanup)
        self.m_runs = os.path.join(f_tmp.name, "runs")
        self.m_root = os.path.join(self.m_runs, "run-a")
        self.m_root2 = os.path.join(self.m_runs, "run-b")
        os.makedirs(self.m_root)
        os.makedirs(os.path.join(self.m_root2, "control"))
        self.m_log = consoleLogPath(self.m_root)

        # Process state detach.py really changes: restored after every patch is stopped.
        self.m_handlers = {f_s: signal.getsignal(f_s) for f_s in self._SIGNALS}
        self.m_mask = signal.pthread_sigmask(signal.SIG_BLOCK, ())

        def restore() -> None:
            signal.pthread_sigmask(signal.SIG_SETMASK, self.m_mask)
            for f_s, f_h in self.m_handlers.items():
                signal.signal(f_s, f_h)

        self.addCleanup(restore)

        # Never fork, leave the session, redirect fds, wait or exit for real.
        self.m_fork = self._patch(
            "os.fork", side_effect=AssertionError("unscripted fork")
        )
        self.m_setsid = self._patch("os.setsid")
        self.m_dup2 = self._patch("os.dup2")
        self.m_exit = self._patch("os._exit")
        self.m_waitpid = self._patch(
            "os.waitpid", side_effect=AssertionError("unscripted waitpid")
        )
        self.m_sleep = self._patch("time.sleep")

        # The follower's writes to fd 1 go to a buffer; any other fd is written for real.
        self.m_out = bytearray()
        self.m_write_error: Optional[BaseException] = None
        f_real_write = os.write

        def write(f_fd: int, f_data: bytes) -> int:
            if f_fd != 1:
                return f_real_write(f_fd, f_data)
            if self.m_write_error is not None:
                raise self.m_write_error
            self.m_out.extend(f_data)
            return len(f_data)

        self._patch("os.write", side_effect=write)

        # Record the fds detach.py opens, to prove they are closed.
        self.m_opened_fds: List[int] = []
        f_real_open = os.open

        def osopen(*f_args: Any, **f_kwargs: Any) -> int:
            f_fd = f_real_open(*f_args, **f_kwargs)
            self.m_opened_fds.append(f_fd)
            return f_fd

        self._patch("os.open", side_effect=osopen)

        # The log file _follow opens and never closes (observation O8): close it here.
        self.m_files: List[Any] = []

        def fopen(*f_args: Any, **f_kwargs: Any) -> Any:
            f_file = builtins.open(*f_args, **f_kwargs)
            self.m_files.append(f_file)
            return f_file

        f_open_patch = patch.object(detach, "open", create=True, side_effect=fopen)
        f_open_patch.start()
        self.addCleanup(f_open_patch.stop)
        self.addCleanup(lambda: [f_f.close() for f_f in self.m_files])

        # Python-level streams only; the runner's own stream objects and fds stay untouched.
        self.m_stdout = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        self.m_stderr = io.StringIO()
        self._patch("sys.stdout", new=self.m_stdout)
        self._patch("sys.stderr", new=self.m_stderr)

    def _patch(self, f_target: str, **f_kwargs: Any) -> Any:
        f_patch = patch(f_target, **f_kwargs)
        f_mock = f_patch.start()
        self.addCleanup(f_patch.stop)
        return f_mock

    def _assertRunnerFdsUntouched(self) -> None:
        self.assertEqual(_fdIds(), self.m_fd_ids)

    def _assertOpenedFdsClosed(self) -> None:
        for f_fd in self.m_opened_fds:
            with self.assertRaises(OSError):
                os.fstat(f_fd)

    def _mask(self) -> Any:
        return signal.pthread_sigmask(signal.SIG_BLOCK, ())

    def _header(self, f_pid: int = 4242) -> bytes:
        return (
            f"Run detached (PID {f_pid}); its output is in {self.m_log}.\n"
            f"Ctrl-C stops following, the run goes on; stop it with: "
            f"lsmiotool cancel {self.m_root}\n"
        ).encode()

    def _script(self, *f_steps: Any) -> None:
        f_iter = iter(f_steps)

        def waitpid(f_pid: int, f_options: int) -> Any:
            f_step = next(f_iter)
            return f_step() if callable(f_step) else f_step

        self.m_waitpid.side_effect = waitpid

    def _writeLog(self, f_data: bytes, f_mode: str = "wb") -> None:
        os.makedirs(os.path.dirname(self.m_log), exist_ok=True)
        with builtins.open(self.m_log, f_mode) as f_f:
            f_f.write(f_data)

    def _forkReturns(self, f_pid: int) -> None:
        self.m_fork.side_effect = None
        self.m_fork.return_value = f_pid

    def testEmptyRunRootsReturnAtOnce(self) -> None:
        for f_roots in ([], ()):
            with self.subTest(f_roots=f_roots):
                self.assertIsNone(detachAndFollow(f_roots))
        self.m_fork.assert_not_called()
        self.assertEqual(self.m_opened_fds, [])
        self.assertFalse(os.path.exists(os.path.join(self.m_root, "control")))

    def testForkFailureRestoresMaskAndClosesLog(self) -> None:
        f_broken = _BrokenFlush()
        with patch("sys.stdout", new=f_broken):
            for f_exc in (
                OSError(11, "Resource temporarily unavailable"),
                KeyboardInterrupt(),
            ):
                with self.subTest(f_exc=type(f_exc).__name__):
                    self.m_fork.side_effect = f_exc
                    self.m_opened_fds.clear()
                    with self.assertRaises(type(f_exc)) as f_cm:
                        detachAndFollow([self.m_root])
                    self.assertIs(f_cm.exception, f_exc)
                    self.assertEqual(self._mask(), self.m_mask)
                    self.assertEqual(len(self.m_opened_fds), 1)
                    self._assertOpenedFdsClosed()
                    self.assertTrue(os.path.isfile(self.m_log))
                    self.assertEqual(os.path.getsize(self.m_log), 0)
                    self.assertIsNone(readOrchestratorPid(self.m_root))
        self.assertEqual(f_broken.m_flushes, 2)
        self.m_setsid.assert_not_called()
        self.m_dup2.assert_not_called()
        self._assertRunnerFdsUntouched()

    def testChildLeavesSessionAndWritesBanner(self) -> None:
        self._forkReturns(0)
        self.assertFalse(hasattr(self.m_stderr, "reconfigure"))
        self.assertIsNone(detachAndFollow([self.m_root, self.m_root2]))
        self.m_setsid.assert_called_once_with()
        f_log_fd, f_null_fd = self.m_opened_fds
        self.assertEqual(
            self.m_dup2.call_args_list,
            [call(f_null_fd, 0), call(f_log_fd, 1), call(f_log_fd, 2)],
        )
        self._assertOpenedFdsClosed()
        self.assertEqual(
            {f_s: signal.getsignal(f_s) for f_s in self._SIGNALS}, self.m_handlers
        )
        self.assertEqual(self._mask(), self.m_mask)
        self.assertTrue(self.m_stdout.line_buffering)
        for f_root in (self.m_root, self.m_root2):
            self.assertEqual(readOrchestratorPid(f_root)["pid"], os.getpid())
        self.m_stdout.flush()
        f_text = self.m_stdout.buffer.getvalue().decode()
        self.assertRegex(f_text, r"^\[\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\] ")
        self.assertEqual(
            f_text.split("] ", 1)[1],
            f"lsmiotool run detached from the terminal (PID {os.getpid()})\n"
            f"  run root: {self.m_root}\n  run root: {self.m_root2}\n"
            f"  stop it:  lsmiotool cancel {self.m_root}\n",
        )
        self.assertEqual(os.path.getsize(self.m_log), 0)
        self.m_exit.assert_not_called()
        self.m_waitpid.assert_not_called()
        self._assertRunnerFdsUntouched()

    def testParentRecordsChildAndExitsWithFollowStatus(self) -> None:
        self._forkReturns(4242)
        with patch("lsmiotool.lib.detach._follow", return_value=7) as f_follow:
            self.assertIsNone(detachAndFollow([self.m_root, self.m_root2]))
        f_follow.assert_called_once_with(4242, self.m_log, self.m_root, self.m_mask)
        self.m_exit.assert_called_once_with(7)
        for f_root in (self.m_root, self.m_root2):
            self.assertEqual(readOrchestratorPid(f_root)["pid"], 4242)
        self._assertOpenedFdsClosed()
        self.assertTrue({signal.SIGINT, signal.SIGHUP} <= self._mask())
        self.m_setsid.assert_not_called()
        self.m_dup2.assert_not_called()
        self._assertRunnerFdsUntouched()

    def testParentExitsZeroWhenFollowRaises(self) -> None:
        self._forkReturns(4242)
        f_err = RuntimeError("follower broke")
        with patch("lsmiotool.lib.detach._follow", side_effect=f_err):
            with self.assertRaises(RuntimeError) as f_cm:
                detachAndFollow([self.m_root])
        self.assertIs(f_cm.exception, f_err)
        self.m_exit.assert_called_once_with(0)
        self.assertEqual(readOrchestratorPid(self.m_root)["pid"], 4242)

    def testFollowCopiesTheGrowingLogAndReturnsTheExitStatus(self) -> None:
        self._writeLog(b"A\n")

        def done() -> Tuple[int, int]:
            self._writeLog(b"B\n", "ab")
            return (4242, 3 << 8)

        self._script((0, 0), done)
        self.assertEqual(detach._follow(4242, self.m_log, self.m_root, set()), 3)
        self.assertEqual(bytes(self.m_out), self._header() + b"A\nB\n")
        self.m_sleep.assert_called_once_with(FOLLOW_INTERVAL_SECONDS)
        self.assertEqual(self.m_waitpid.call_args_list, [call(4242, os.WNOHANG)] * 2)
        self.assertIs(signal.getsignal(signal.SIGTERM), signal.SIG_DFL)
        self.assertIs(signal.getsignal(signal.SIGHUP), signal.SIG_DFL)
        self.assertTrue(callable(signal.getsignal(signal.SIGINT)))
        self.assertIsNot(
            signal.getsignal(signal.SIGINT), self.m_handlers[signal.SIGINT]
        )
        self.assertEqual(self._mask(), set())
        self.assertEqual([f_f.mode for f_f in self.m_files], ["rb"])

    def testFollowWithoutLogWaitsAndMapsASignalDeath(self) -> None:
        self._script((0, 0), (4242, signal.SIGKILL))
        self.assertEqual(
            detach._follow(4242, self.m_log, self.m_root, None), 128 + signal.SIGKILL
        )
        f_err = f"[Errno 2] No such file or directory: '{self.m_log}'"
        self.assertEqual(
            bytes(self.m_out),
            self._header()
            + f"Cannot follow {self.m_log} ({f_err}); waiting for the run to end.\n".encode(),
        )
        self.assertEqual(self.m_files, [])
        self.assertEqual(self._mask(), set())

    def testFollowEmptyLogOfAFinishedRun(self) -> None:
        self._writeLog(b"")
        self._script((4242, 0))
        self.assertEqual(detach._follow(4242, self.m_log, self.m_root, set()), 0)
        self.assertEqual(bytes(self.m_out), self._header())
        self.m_sleep.assert_not_called()

    def testCtrlCStopsFollowingOnly(self) -> None:
        self._writeLog(b"")

        def ctrlc() -> Tuple[int, int]:
            signal.getsignal(signal.SIGINT)(signal.SIGINT, None)
            return (0, 0)

        self._script(ctrlc)
        self.assertEqual(detach._follow(4242, self.m_log, self.m_root, set()), 0)
        self.assertEqual(
            bytes(self.m_out),
            self._header()
            + (
                f"\nStopped following; the run goes on (PID 4242).\n"
                f"  Follow it:  tail -f {self.m_log}\n"
                f"  Stop it:    lsmiotool cancel {self.m_root}\n"
            ).encode(),
        )
        self.m_sleep.assert_not_called()
        self.m_exit.assert_not_called()

    def testFollowerEndsQuietlyWhenTheTerminalIsGone(self) -> None:
        self._writeLog(b"x\n")
        self.m_write_error = OSError(5, "Input/output error")
        self.assertEqual(detach._follow(4242, self.m_log, self.m_root, set()), 0)
        self.m_waitpid.assert_not_called()

    def testParentFollowsTheRunAndExitsWithItsStatus(self) -> None:
        self._forkReturns(4242)
        self._script((4242, 5 << 8))
        self.assertIsNone(detachAndFollow([self.m_root]))
        self.m_exit.assert_called_once_with(5)
        self.assertEqual(bytes(self.m_out), self._header())
        self.assertEqual(self._mask(), self.m_mask)
        self._assertRunnerFdsUntouched()


if __name__ == "__main__":
    unittest.main()
