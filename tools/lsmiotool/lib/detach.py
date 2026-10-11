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

"""Detaching 'lsmiotool run' from the terminal, like running it under nohup and tailing
its output.

Once its run roots exist, the run forks: the child carries on in a new session (no
controlling terminal, so neither a dropped login session nor Ctrl-C reaches it) with its
output in <first run root>/control/console.log; the parent follows that log until the
child exits and exits with its status. Ctrl-C only stops the following;
'lsmiotool cancel <run root>' stops the run itself (SIGTERM: its job is cancelled).
"""

import os
import signal
import sys
import time
from datetime import datetime, timezone
from typing import List, NoReturn, Optional, Sequence

CONSOLE_LOG = "console.log"
FOLLOW_INTERVAL_SECONDS = 0.5

# Delivered to the terminal's process group: blocked across fork() and setsid(), so a
# Ctrl-C or hangup in that window cannot reach the run before it leaves the session
_SESSION_SIGNALS = {signal.SIGINT, signal.SIGHUP}


def consoleLogPath(f_run_root: str) -> str:
    return os.path.join(f_run_root, "control", CONSOLE_LOG)


def consoleLogFor(f_run_root: str) -> str:
    """The console log of the run f_run_root belongs to: a multi-arm run keeps it in its
    first arm's run root (.lsmiotool-arm.json group_run_ids)."""
    from lsmiotool.lib.archive import ArchiveEngine

    f_marker = ArchiveEngine.readArmMarker(f_run_root) or {}
    f_ids = f_marker.get("group_run_ids") or []
    if f_ids:
        return consoleLogPath(os.path.join(os.path.dirname(f_run_root), str(f_ids[0])))
    return consoleLogPath(f_run_root)


def detachAndFollow(f_run_roots: Sequence[str]) -> None:
    """Fork the run off the terminal. Returns in the child, which continues the run;
    never returns in the parent, which follows the console log and exits."""
    from lsmiotool.lib.run import writeOrchestratorPid

    f_roots: List[str] = list(f_run_roots)
    if not f_roots:
        return
    f_log = consoleLogPath(f_roots[0])
    os.makedirs(os.path.dirname(f_log), exist_ok=True)
    f_fd = os.open(f_log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    for f_stream in (sys.stdout, sys.stderr):
        try:
            f_stream.flush()
        except Exception:
            pass

    f_old_mask = signal.pthread_sigmask(signal.SIG_BLOCK, _SESSION_SIGNALS)
    try:
        f_pid = os.fork()
    except BaseException:
        signal.pthread_sigmask(signal.SIG_SETMASK, f_old_mask)
        os.close(f_fd)
        raise
    if f_pid == 0:
        os.setsid()
        # Drop a Ctrl-C or hangup that arrived before setsid (ignoring discards it)
        f_handlers = {
            f_sig: signal.signal(f_sig, signal.SIG_IGN) for f_sig in _SESSION_SIGNALS
        }
        signal.pthread_sigmask(signal.SIG_SETMASK, f_old_mask)
        for f_sig, f_handler in f_handlers.items():
            signal.signal(f_sig, f_handler)
        f_null = os.open(os.devnull, os.O_RDONLY)
        os.dup2(f_null, 0)
        os.close(f_null)
        os.dup2(f_fd, 1)
        os.dup2(f_fd, 2)
        os.close(f_fd)
        for f_stream in (sys.stdout, sys.stderr):
            try:
                f_stream.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
            except Exception:
                pass
        writeOrchestratorPid(f_roots)
        f_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        sys.stdout.write(
            f"[{f_now}] lsmiotool run detached from the terminal (PID {os.getpid()})\n"
            + "".join(f"  run root: {f_r}\n" for f_r in f_roots)
            + f"  stop it:  lsmiotool cancel {f_roots[0]}\n"
        )
        return

    # The parent never returns into the run: returning would unwind it and release the
    # control locks it shares with the child (flock on the same open file)
    f_code = 0
    try:
        os.close(f_fd)
        # Name the run, not this follower, before anyone could read the pid file
        writeOrchestratorPid(f_roots, f_pid=f_pid)
        f_code = _follow(f_pid, f_log, f_roots[0], f_old_mask)
    finally:
        os._exit(f_code)


def _follow(f_pid: int, f_log: str, f_root: str, f_old_mask: Optional[set]) -> int:
    """Copy the console log to stdout until the run (f_pid) exits, and return its exit
    status; Ctrl-C stops following (0)."""
    f_stop: List[int] = []
    signal.signal(signal.SIGINT, lambda f_sig, f_frame: f_stop.append(f_sig))
    # Killing the follower must not take the run with it: no cancellation here
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGHUP, signal.SIG_DFL)
    signal.pthread_sigmask(signal.SIG_SETMASK, f_old_mask or set())

    def out(f_text: str) -> None:
        os.write(1, f_text.encode())

    def status(f_raw: int) -> int:
        f_code = os.waitstatus_to_exitcode(f_raw)
        return 128 - f_code if f_code < 0 else f_code

    try:
        out(
            f"Run detached (PID {f_pid}); its output is in {f_log}.\n"
            f"Ctrl-C stops following, the run goes on; stop it with: "
            f"lsmiotool cancel {f_root}\n"
        )
        try:
            f_f = open(f_log, "rb")
        except OSError as f_err:
            out(f"Cannot follow {f_log} ({f_err}); waiting for the run to end.\n")
            f_f = None
        while True:
            if f_f is not None:
                f_chunk = f_f.read()
                if f_chunk:
                    os.write(1, f_chunk)
            f_done, f_raw = os.waitpid(f_pid, os.WNOHANG)
            if f_done:
                if f_f is not None:
                    f_rest = f_f.read()
                    if f_rest:
                        os.write(1, f_rest)
                return status(f_raw)
            if f_stop:
                out(
                    f"\nStopped following; the run goes on (PID {f_pid}).\n"
                    f"  Follow it:  tail -f {f_log}\n"
                    f"  Stop it:    lsmiotool cancel {f_root}\n"
                )
                return 0
            time.sleep(FOLLOW_INTERVAL_SECONDS)
    except OSError:
        # The terminal is gone: the run goes on without a follower
        return 0
