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

import io
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from lsmiotool.lib.detach import consoleLogPath
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


if __name__ == "__main__":
    unittest.main()
