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

"""Scheduler observations are written only when they change (ObservationThrottle).

Every scenario runs twice: once writing every poll (a zero heartbeat, the behaviour
before the throttle) and once throttled. Reconciling both must give the same run and
point states, and the throttled run must keep its observation sequences gapless.
"""

from datetime import datetime, timedelta, timezone
import os
import re
import signal
from typing import Any, Dict, List, Optional, Sequence, Tuple
import unittest
from unittest.mock import patch

from lsmiotool.lib.run import ObservationThrottle, RunOrchestrator, RunRequest
from lsmiotool.lib.run import SignalCoordinator
from lsmiotool.lib.state import StateReconciler
from lsmiotool.lib.worker import ProcessResult
from lsmiotool.test.main import InterruptionTest as _interruption

# One poll's scheduler answer:
#   PD: pending, R: running, U: both queries fail (UNKNOWN),
#   SR: squeue fails and sacct reports RUNNING (an exit code appears),
#   DONE, FAILED, TIMEOUT: the job left squeue and sacct reports that state
_SACCT_TERMINAL = {
    "DONE": "COMPLETED|0:0",
    "FAILED": "FAILED|1:0",
    "TIMEOUT": "TIMEOUT|0:0",
}


class ScriptedSchedulerCommandRunner(
    _interruption.FakeInterruptionSchedulerCommandRunner
):
    """Answers each job-state poll from a script; cancellation is the parent's."""

    def __init__(self, f_script: Sequence[str]) -> None:
        super().__init__()
        self.m_script = list(f_script)
        self.m_poll = 0
        self.m_current = "PD"
        self.m_on_poll = None

    def run(
        self,
        f_argv: Sequence[str],
        f_cwd: Optional[str] = None,
        f_environment: Optional[Dict[str, str]] = None,
        f_log_path: Optional[str] = None,
    ) -> ProcessResult:
        f_cmd = list(f_argv)
        f_exe = os.path.basename(f_cmd[0])
        f_jobs = [f_a.split("=", 1)[1] for f_a in f_cmd if f_a.startswith("--jobs=")]
        f_jid = f_jobs[0] if f_jobs else "1000"
        f_recovery = any(f_a.startswith("--name=") for f_a in f_cmd)
        if f_recovery or f_jid in self.m_cancelled_jobs or self.m_query_fail:
            return super().run(f_argv, f_cwd, f_environment, f_log_path)
        if f_exe == "squeue":
            self.m_calls.append(f_cmd)
            # The script's last answer repeats once it runs out
            self.m_current = self.m_script[min(self.m_poll, len(self.m_script) - 1)]
            self.m_poll += 1
            if self.m_on_poll is not None:
                self.m_on_poll(self.m_poll)
            if self.m_current in ("U", "SR"):
                return ProcessResult(
                    1, "", "squeue: error: Slurm controller down\n", 0.01
                )
            if self.m_current == "PD":
                return ProcessResult(0, f"{f_jid}|PENDING\n", "", 0.01)
            if self.m_current == "R":
                return ProcessResult(0, f"{f_jid}|RUNNING\n", "", 0.01)
            return ProcessResult(0, "", "", 0.01)
        if f_exe == "sacct":
            self.m_calls.append(f_cmd)
            if self.m_current == "U":
                return ProcessResult(1, "", "sacct: error: Slurmdbd down\n", 0.01)
            if self.m_current == "SR":
                return ProcessResult(0, f"{f_jid}|RUNNING|0:0\n", "", 0.01)
            f_line = _SACCT_TERMINAL.get(self.m_current)
            if f_line is not None:
                return ProcessResult(0, f"{f_jid}|{f_line}\n", "", 0.01)
            return ProcessResult(0, "", "", 0.01)
        return super().run(f_argv, f_cwd, f_environment, f_log_path)


class ObservationThrottleUnitTest(unittest.TestCase):
    """The write decision itself."""

    def testFirstPollIsWritten(self) -> None:
        self.assertTrue(ObservationThrottle().shouldWrite({"state": "active"}, 0.0))

    def testRepeatIsSkippedAndChangeIsWritten(self) -> None:
        f_t = ObservationThrottle(f_heartbeat_seconds=100.0)
        f_t.noteWritten({"state": "active", "exit_code": None}, 0.0)
        self.assertFalse(f_t.shouldWrite({"state": "active", "exit_code": None}, 8.0))
        self.assertTrue(f_t.shouldWrite({"state": "active", "exit_code": 0}, 8.0))
        self.assertTrue(f_t.shouldWrite({"state": "succeeded", "exit_code": None}, 8.0))

    def testHeartbeatWritesARepeat(self) -> None:
        f_t = ObservationThrottle(f_heartbeat_seconds=100.0)
        f_t.noteWritten({"state": "active"}, 0.0)
        self.assertFalse(f_t.shouldWrite({"state": "active"}, 99.0))
        self.assertTrue(f_t.shouldWrite({"state": "active"}, 100.0))

    def testDefaultHeartbeatIsHalfAnHour(self) -> None:
        self.assertEqual(ObservationThrottle().m_heartbeat_seconds, 1800.0)

    def testNotedPayloadIsACopy(self) -> None:
        f_t = ObservationThrottle()
        f_payload: Dict[str, Any] = {"state": "active", "handle": {"job_id": "1"}}
        f_t.noteWritten(f_payload, 0.0)
        f_payload["handle"]["job_id"] = "2"
        self.assertTrue(f_t.shouldWrite(f_payload, 1.0))


_RUN_ID = re.compile(r"run-\d{8}T\d{6}Z-[0-9a-f]+")
_TOKEN = re.compile(r"lm-[0-9a-f]+")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z?")


def _normalise(f_text: str) -> str:
    return _TIMESTAMP.sub("TIME", _TOKEN.sub("TOKEN", _RUN_ID.sub("RUN", f_text)))


def _viewKey(f_view: Any) -> Tuple[Any, ...]:
    """What reconcile decided, free of run ids and timestamps; diagnostics as a set
    (StateReconciler adds some once per observation file)."""
    return (
        str(f_view.state),
        f_view.has_interruption,
        f_view.has_success_marker,
        f_view.active_point_ordinal,
        frozenset(_normalise(str(f_d)) for f_d in f_view.diagnostics),
        tuple(
            (
                f_p.point_id,
                str(f_p.state),
                str(f_p.scheduler_state),
                _normalise(repr(f_p.handle)),
                tuple(f_p.combinations_completed),
                tuple(f_p.combinations_failed),
                tuple(f_p.combinations_missing),
                frozenset(_normalise(str(f_d)) for f_d in f_p.diagnostics),
            )
            for f_p in f_view.point_states
        ),
    )


class ObservationWritingTest(unittest.TestCase):
    """Throttled and unthrottled runs reconcile alike, for both polling loops."""

    setUp = _interruption.InterruptionTest.setUp
    tearDown = _interruption.InterruptionTest.tearDown

    def _run(
        self,
        f_script: Sequence[str],
        f_group: bool,
        f_heartbeat: Optional[float],
        f_signal_at_poll: Optional[int] = None,
        f_signal_in_sleep: bool = False,
        f_cancel_state: str = "CANCELLED",
        f_cancel_query_fails: bool = False,
        f_completed_labels: Sequence[str] = (),
    ) -> Tuple[List[Tuple[Any, ...]], List[List[List[int]]]]:
        """Run the script once; return each arm's reconciled view key and, per arm and
        point, the sequence numbers of its observation files."""
        f_runner = ScriptedSchedulerCommandRunner(f_script)
        f_runner.m_cancel_confirmed_state = f_cancel_state
        f_sig = SignalCoordinator()
        # Simulated time moves only when the orchestrator sleeps: 8 s between polls
        f_clock = [0.0]

        def _onPoll(f_poll: int) -> None:
            if f_poll == f_signal_at_poll and not f_signal_in_sleep:
                f_sig.trigger(signal.SIGINT)
                if f_cancel_query_fails:
                    f_runner.m_query_fail = True

        def _sleep(f_seconds: float) -> None:
            f_clock[0] += f_seconds
            if f_signal_in_sleep and f_runner.m_poll == f_signal_at_poll:
                f_sig.trigger(signal.SIGINT)
                if f_cancel_query_fails:
                    f_runner.m_query_fail = True

        f_runner.m_on_poll = _onPoll

        def _clockFn() -> float:
            return f_clock[0]

        class _SimulatedDatetime(datetime):
            """Evidence timestamps on the simulated clock. On the wall clock they are
            per second, so a cancel request and the failure after it could share a
            second in one run and not in the other, and reconcile apart (FAILED vs
            CANCELLED)."""

            @classmethod
            def now(cls, tz: Any = None) -> datetime:
                return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(
                    seconds=f_clock[0]
                )

        f_orch = RunOrchestrator(
            f_worker_validator=self.m_worker_validator,
            f_command_runner=f_runner,
            f_signal_coordinator=f_sig,
            f_poll_interval=8.0,
            f_clock_float=_clockFn,
            f_sleep=_sleep,
        )
        if f_completed_labels:

            def _onSubmit(f_jid: str, f_cwd: Optional[str]) -> None:
                for f_run in f_orch.groupRuns:
                    if f_run["arm"].label not in f_completed_labels:
                        continue
                    for f_idx, f_sp in enumerate(f_run["plan"].scale_points):
                        if not os.path.isdir(
                            f_run["store"].layout.pointDir(f_sp, f_idx)
                        ):
                            continue
                        for f_combo in f_run["plan"].combinations:
                            if (
                                f_run["evidence"].readControllerResult(
                                    f_sp, f_combo, f_ordinal=f_idx
                                )
                                is None
                            ):
                                f_run["evidence"].recordControllerResult(
                                    f_point=f_sp,
                                    f_combination=f_combo,
                                    f_payload={"returncode": 0, "status": "completed"},
                                    f_ordinal=f_idx,
                                )

            f_runner.m_on_submit_callback = _onSubmit

        if f_group:
            f_req = RunRequest(
                "ior",
                "local",
                f_mode="backends",
                f_backends=["base", "collective"],
                f_archive=False,
            )
        else:
            f_req = RunRequest("ior", "local")
        with (
            patch.object(
                ObservationThrottle,
                "HEARTBEAT_SECONDS",
                ObservationThrottle.HEARTBEAT_SECONDS
                if f_heartbeat is None
                else f_heartbeat,
            ),
            patch("lsmiotool.lib.evidence.datetime", _SimulatedDatetime),
        ):
            f_orch.execute(
                f_request=f_req,
                f_site=self.m_viking_profile,
                f_worker_executable=self.m_fake_worker,
            )

        if f_group:
            f_arms = [
                (f_r["plan"], f_r["evidence"], f_r["store"]) for f_r in f_orch.groupRuns
            ]
        else:
            f_store = f_orch.last_evidence_store
            f_arms = [(f_orch.last_plan, f_store, None)]
        f_keys: List[Tuple[Any, ...]] = []
        f_seqs: List[List[List[int]]] = []
        for f_plan, f_ev, f_art in f_arms:
            f_keys.append(_viewKey(StateReconciler().reconcile(f_plan, f_ev)))
            f_layout = f_ev.layout if f_art is None else f_art.layout
            f_points: List[List[int]] = []
            for f_idx, f_sp in enumerate(f_plan.scale_points):
                f_dir = f_layout.pointSchedulerObservationsDir(
                    f_sp, f_writer="control", f_ordinal=f_idx
                )
                f_points.append(
                    sorted(
                        int(f_n[:-5])
                        for f_n in os.listdir(f_dir)
                        if f_n.endswith(".json")
                    )
                    if os.path.isdir(f_dir)
                    else []
                )
            f_seqs.append(f_points)
        return f_keys, f_seqs

    def _assertEquivalent(self, f_group: bool, **f_kw: Any) -> List[List[List[int]]]:
        """Reconcile the scenario written in full and throttled; return the throttled
        runs' sequence numbers, checked gapless and no more than the full run's."""
        f_full_keys, f_full_seqs = self._run(f_group=f_group, f_heartbeat=0.0, **f_kw)
        f_keys, f_seqs = self._run(f_group=f_group, f_heartbeat=None, **f_kw)
        self.assertEqual(f_keys, f_full_keys)
        for f_arm, f_full_arm in zip(f_seqs, f_full_seqs, strict=True):
            for f_point, f_full_point in zip(f_arm, f_full_arm, strict=True):
                self.assertEqual(f_point, list(range(1, len(f_point) + 1)))
                self.assertLessEqual(len(f_point), len(f_full_point))
        return f_seqs

    # -- the single-run loop -------------------------------------------------

    def testSteadyJobWritesOnlyChanges(self) -> None:
        f_seqs = self._assertEquivalent(
            f_group=False, f_script=["PD"] * 3 + ["R"] * 20 + ["DONE"]
        )
        # queued, active, succeeded
        self.assertEqual(f_seqs, [[[1, 2, 3]]])

    def testUnknownFlapIsKept(self) -> None:
        f_seqs = self._assertEquivalent(
            f_group=False, f_script=["R"] * 5 + ["U"] + ["R"] * 5 + ["DONE"]
        )
        self.assertEqual(f_seqs, [[[1, 2, 3, 4]]])

    def testUnknownLimitStillStopsPolling(self) -> None:
        f_seqs = self._assertEquivalent(
            f_group=False, f_script=["U"] * (RunOrchestrator.UNKNOWN_POLL_LIMIT + 5)
        )
        self.assertEqual(f_seqs, [[[1]]])

    def testExitCodeFlipIsWritten(self) -> None:
        f_seqs = self._assertEquivalent(
            f_group=False, f_script=["R", "SR", "R", "SR", "DONE"]
        )
        self.assertEqual(f_seqs, [[[1, 2, 3, 4, 5]]])

    def testFailedAndTimedOutJobs(self) -> None:
        for f_end in ("FAILED", "TIMEOUT"):
            with self.subTest(f_end=f_end):
                f_seqs = self._assertEquivalent(
                    f_group=False, f_script=["R"] * 10 + [f_end]
                )
                self.assertEqual(f_seqs, [[[1, 2]]])

    def testHeartbeatWritesLongRepeats(self) -> None:
        # 1800 s at 8 s per poll: a repeat is written every 225 polls
        f_seqs = self._assertEquivalent(f_group=False, f_script=["R"] * 500 + ["DONE"])
        self.assertEqual(f_seqs, [[[1, 2, 3, 4]]])

    def testInterruptAfterSkippedPollsKeepsTheCancelObservation(self) -> None:
        # Both interrupt branches: noticed after a poll, and before the next one
        for f_in_sleep in (False, True):
            for f_cancel in ("CANCELLED", "COMPLETED", "FAILED"):
                with self.subTest(f_in_sleep=f_in_sleep, f_cancel=f_cancel):
                    f_seqs = self._assertEquivalent(
                        f_group=False,
                        f_script=["R"] * 30 + ["DONE"],
                        f_signal_at_poll=8,
                        f_signal_in_sleep=f_in_sleep,
                        f_cancel_state=f_cancel,
                    )
                    # active, then the cancel outcome at the next free number
                    self.assertEqual(f_seqs, [[[1, 2]]])

    def testCancelUnconfirmedWritesNoObservation(self) -> None:
        f_seqs = self._assertEquivalent(
            f_group=False,
            f_script=["R"] * 30 + ["DONE"],
            f_signal_at_poll=8,
            f_cancel_query_fails=True,
        )
        self.assertEqual(f_seqs, [[[1]]])

    # -- the arm-group loop --------------------------------------------------

    def testGroupSteadyJobWritesOnlyChanges(self) -> None:
        f_seqs = self._assertEquivalent(
            f_group=True, f_script=["PD"] * 3 + ["R"] * 20 + ["DONE"]
        )
        self.assertEqual(f_seqs, [[[1, 2, 3]], [[1, 2, 3]]])

    def testGroupJobEndWithACompletedArm(self) -> None:
        # The first arm finished before the shared job failed: its last observation
        # differs from the second arm's (arm_completed_before_job_end)
        for f_end in ("FAILED", "TIMEOUT"):
            with self.subTest(f_end=f_end):
                f_seqs = self._assertEquivalent(
                    f_group=True,
                    f_script=["R"] * 10 + [f_end],
                    f_completed_labels=("base",),
                )
                self.assertEqual(f_seqs, [[[1, 2]], [[1, 2]]])

    def testGroupInterruptAfterSkippedPollsMirrorsTheCancel(self) -> None:
        for f_cancel in ("CANCELLED", "COMPLETED"):
            with self.subTest(f_cancel=f_cancel):
                f_seqs = self._assertEquivalent(
                    f_group=True,
                    f_script=["R"] * 30 + ["DONE"],
                    f_signal_at_poll=8,
                    f_cancel_state=f_cancel,
                )
                # Every arm: active, then the (mirrored) cancel outcome
                self.assertEqual(f_seqs, [[[1, 2]], [[1, 2]]])

    def testGroupUnknownLimitStillStopsPolling(self) -> None:
        f_seqs = self._assertEquivalent(
            f_group=True, f_script=["U"] * (RunOrchestrator.UNKNOWN_POLL_LIMIT + 5)
        )
        # Every poll is the same UNKNOWN: one observation per arm
        self.assertEqual(f_seqs, [[[1]], [[1]]])

    def testGroupHeartbeatWritesLongRepeats(self) -> None:
        f_seqs = self._assertEquivalent(f_group=True, f_script=["R"] * 500 + ["DONE"])
        self.assertEqual(f_seqs, [[[1, 2, 3, 4]], [[1, 2, 3, 4]]])

    def testGroupInterruptBetweenPolls(self) -> None:
        f_seqs = self._assertEquivalent(
            f_group=True,
            f_script=["R"] * 30 + ["DONE"],
            f_signal_at_poll=8,
            f_signal_in_sleep=True,
        )
        self.assertEqual(f_seqs, [[[1, 2]], [[1, 2]]])

    def testGroupCancelUnconfirmedWritesNoObservation(self) -> None:
        f_seqs = self._assertEquivalent(
            f_group=True,
            f_script=["R"] * 30 + ["DONE"],
            f_signal_at_poll=8,
            f_cancel_query_fails=True,
        )
        self.assertEqual(f_seqs, [[[1]], [[1]]])

    def testGroupUnknownFlapAndExitCodeFlip(self) -> None:
        f_seqs = self._assertEquivalent(
            f_group=True, f_script=["R", "U", "R", "SR", "R", "DONE"]
        )
        self.assertEqual(f_seqs, [[[1, 2, 3, 4, 5, 6]], [[1, 2, 3, 4, 5, 6]]])


if __name__ == "__main__":
    unittest.main()
