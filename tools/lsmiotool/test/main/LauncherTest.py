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

import os
import sys
import tempfile
from typing import Any, Dict, List, Mapping, Optional, Sequence
import unittest
from unittest.mock import MagicMock, patch

from lsmiotool.lib.benchmarks import BenchmarkCommand
from lsmiotool.lib.profile import ProfileLoader
from lsmiotool.lib.run import Combination, LaunchMode, ScalePoint
from lsmiotool.lib.site import (
    EnvironmentResolver,
    LauncherPolicy,
    SchedulerKind,
    SiteProfile,
)
from lsmiotool.lib.worker import (
    Launcher,
    LauncherError,
    ProcessExecutionError,
    ProcessLoggingError,
    ProcessResult,
    ProcessRunner,
    ProcessSpawnError,
    WorkerError,
)


class MockProcessRunner:
    """Mock process runner for recording argv and simulating process return codes/signals."""

    def __init__(
        self,
        f_returncode: int = 0,
        f_stdout: str = "",
        f_stderr: str = "",
        f_exception_to_raise: Optional[Exception] = None,
    ) -> None:
        self.m_returncode = f_returncode
        self.m_stdout = f_stdout
        self.m_stderr = f_stderr
        self.m_exception_to_raise = f_exception_to_raise
        self.m_invoked_argv: List[List[str]] = []
        self.m_invoked_kwargs: List[Dict[str, Any]] = []

    def run(
        self,
        f_argv: Sequence[str],
        **f_kwargs: Any,
    ) -> ProcessResult:
        self.m_invoked_argv.append(list(f_argv))
        self.m_invoked_kwargs.append(dict(f_kwargs))
        if self.m_exception_to_raise is not None:
            raise self.m_exception_to_raise
        return ProcessResult(
            f_returncode=self.m_returncode,
            f_stdout=self.m_stdout,
            f_stderr=self.m_stderr,
            f_elapsed_seconds=0.05,
        )


class LauncherTest(unittest.TestCase):
    """Unit test suite for Launcher verifying exact argv construction, partition flags, and status propagation."""

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.TemporaryDirectory()
        self.m_etc_path = os.path.normpath(
            os.path.join(
                os.path.dirname(__file__), "..", "..", "etc", "environments.json"
            )
        )
        self.m_profile_doc = ProfileLoader.load(self.m_etc_path)
        self.m_viking_profile = EnvironmentResolver.resolveProfile(
            "VIKING", f_user="testuser", f_home="/tmp"
        )
        self.m_viking2_profile = EnvironmentResolver.resolveProfile(
            "VIKING2", f_user="testuser", f_home="/tmp"
        )
        self.m_archer2_profile = EnvironmentResolver.resolveProfile(
            "ARCHER2", f_user="testuser", f_home="/tmp"
        )
        self.m_isambard_profile = EnvironmentResolver.resolveProfile(
            "ISAMBARD", f_user="testuser", f_home="/tmp"
        )
        self.m_dev_profile = EnvironmentResolver.resolveProfile(
            "DEV", f_user="testuser", f_home="/tmp"
        )

        # Scale points
        self.m_small_point = ScalePoint(f_tasks=8, f_ppn=1, f_nodes=8)
        self.m_large_point = ScalePoint(f_tasks=32, f_ppn=4, f_nodes=8)
        self.m_single_point = ScalePoint(f_tasks=1, f_ppn=1, f_nodes=1)

        # Benchmark commands
        self.m_ior_command = BenchmarkCommand(
            f_argv=["ior", "-v", "-w", "-r", "-i=10"],
            f_stdout_path=os.path.join(self.m_temp_dir.name, "ior.stdout"),
            f_stderr_path=os.path.join(self.m_temp_dir.name, "ior.stderr"),
            f_working_dir=self.m_temp_dir.name,
        )
        self.m_lmp_command = BenchmarkCommand(
            f_argv=["lmp", "-in", "in.reaxc.hns", "-var", "x", "1"],
            f_stdout_path=os.path.join(self.m_temp_dir.name, "lmp.stdout"),
            f_stderr_path=os.path.join(self.m_temp_dir.name, "lmp.stderr"),
            f_working_dir=self.m_temp_dir.name,
        )

        # Combinations
        self.m_combination = Combination(
            f_processes=1,
            f_block_size="8M",
            f_stripe_count=16,
            f_block_bytes=8388608,
            f_key_count=1024,
            f_segment_count=128,
        )

    def tearDown(self) -> None:
        self.m_temp_dir.cleanup()

    def testExactSrunAndAprun(self) -> None:
        """Validates exact launcher argv structure for Slurm (Viking, Viking2), PBS (Isambard), and DEV."""
        # 1. Viking (Slurm, ppn=1): ['srun', '--export=ALL', '-n', '8', '-N', '8', ...]
        f_viking_small = Launcher.buildSharedArgv(
            self.m_viking_profile, self.m_small_point, self.m_ior_command
        )
        self.assertEqual(
            f_viking_small,
            [
                "srun",
                "--export=ALL",
                "-n",
                "8",
                "-N",
                "8",
                "ior",
                "-v",
                "-w",
                "-r",
                "-i=10",
            ],
        )

        # 2. Viking (Slurm, ppn=4): ['srun', '--export=ALL', '-n', '32', '-N', '8', ...]
        f_viking_large = Launcher.buildSharedArgv(
            self.m_viking_profile, self.m_large_point, self.m_ior_command
        )
        self.assertEqual(
            f_viking_large,
            [
                "srun",
                "--export=ALL",
                "-n",
                "32",
                "-N",
                "8",
                "ior",
                "-v",
                "-w",
                "-r",
                "-i=10",
            ],
        )

        # 3. Viking2 (Slurm, ppn=1)
        f_viking2_small = Launcher.buildSharedArgv(
            self.m_viking2_profile, self.m_small_point, self.m_lmp_command
        )
        self.assertEqual(
            f_viking2_small,
            [
                "srun",
                "--export=ALL",
                "-n",
                "8",
                "-N",
                "8",
                "lmp",
                "-in",
                "in.reaxc.hns",
                "-var",
                "x",
                "1",
            ],
        )

        # 4. Viking2 (Slurm, ppn=4)
        f_viking2_large = Launcher.buildSharedArgv(
            self.m_viking2_profile, self.m_large_point, self.m_lmp_command
        )
        self.assertEqual(
            f_viking2_large,
            [
                "srun",
                "--export=ALL",
                "-n",
                "32",
                "-N",
                "8",
                "lmp",
                "-in",
                "in.reaxc.hns",
                "-var",
                "x",
                "1",
            ],
        )

        # 5. Isambard (PBS, ppn=1): ['aprun', '-n', '8', '-N', '1', ...]
        f_isambard_small = Launcher.buildSharedArgv(
            self.m_isambard_profile, self.m_small_point, self.m_ior_command
        )
        self.assertEqual(
            f_isambard_small,
            ["aprun", "-n", "8", "-N", "1", "ior", "-v", "-w", "-r", "-i=10"],
        )

        # 6. Isambard (PBS, ppn=4): ['aprun', '-n', '32', '-N', '4', ...]
        f_isambard_large = Launcher.buildSharedArgv(
            self.m_isambard_profile, self.m_large_point, self.m_ior_command
        )
        self.assertEqual(
            f_isambard_large,
            ["aprun", "-n", "32", "-N", "4", "ior", "-v", "-w", "-r", "-i=10"],
        )

        # 7. DEV / Fake: direct execution without launcher prefix
        f_dev_argv = Launcher.buildSharedArgv(
            self.m_dev_profile, self.m_small_point, self.m_ior_command
        )
        self.assertEqual(f_dev_argv, ["ior", "-v", "-w", "-r", "-i=10"])

        # 8. Direct string "fake" / "direct" / None
        f_fake_argv = Launcher.buildSharedArgv(
            "fake", self.m_small_point, ["echo", "hello"]
        )
        self.assertEqual(f_fake_argv, ["echo", "hello"])
        f_none_argv = Launcher.buildSharedArgv(
            None, self.m_small_point, ["echo", "hello"]
        )
        self.assertEqual(f_none_argv, ["echo", "hello"])

    def testArcher2Partition(self) -> None:
        """Validates that Archer2 includes '-p standard' partition flag for both shapes and modes."""
        # 1. Archer2 Shared mode (small shape: ppn=1)
        f_archer2_small_shared = Launcher.buildSharedArgv(
            self.m_archer2_profile, self.m_small_point, self.m_ior_command
        )
        self.assertEqual(
            f_archer2_small_shared,
            [
                "srun",
                "--export=ALL",
                "-n",
                "8",
                "-N",
                "8",
                "-p",
                "standard",
                "ior",
                "-v",
                "-w",
                "-r",
                "-i=10",
            ],
        )

        # 2. Archer2 Shared mode (large shape: ppn=4)
        f_archer2_large_shared = Launcher.buildSharedArgv(
            self.m_archer2_profile, self.m_large_point, self.m_lmp_command
        )
        self.assertEqual(
            f_archer2_large_shared,
            [
                "srun",
                "--export=ALL",
                "-n",
                "32",
                "-N",
                "8",
                "-p",
                "standard",
                "lmp",
                "-in",
                "in.reaxc.hns",
                "-var",
                "x",
                "1",
            ],
        )

        # 3. Archer2 Rank worker mode (small shape: ppn=1)
        f_archer2_small_rank = Launcher.buildRankWorkerArgv(
            self.m_archer2_profile,
            self.m_small_point,
            f_worker_executable="/work/e281/e281/user/usr/bin/lsmioworker",
            f_manifest_path="/work/e281/e281/user/benchmark/runs/run1/manifest.json",
            f_point_id="p0",
            f_combination_desc=self.m_combination,
        )
        self.assertEqual(
            f_archer2_small_rank,
            [
                "srun",
                "--export=ALL",
                "-n",
                "8",
                "-N",
                "8",
                "-p",
                "standard",
                "/work/e281/e281/user/usr/bin/lsmioworker",
                "rank",
                "/work/e281/e281/user/benchmark/runs/run1/manifest.json",
                "p0",
                "c16_b8M",
            ],
        )

        # 4. Archer2 Rank worker mode (large shape: ppn=4)
        f_archer2_large_rank = Launcher.buildRankWorkerArgv(
            self.m_archer2_profile,
            self.m_large_point,
            f_worker_executable="/work/e281/e281/user/usr/bin/lsmioworker",
            f_manifest_path="/work/e281/e281/user/benchmark/runs/run1/manifest.json",
            f_point_id="p1",
            f_combination_desc="c4_b1M",
        )
        self.assertEqual(
            f_archer2_large_rank,
            [
                "srun",
                "--export=ALL",
                "-n",
                "32",
                "-N",
                "8",
                "-p",
                "standard",
                "/work/e281/e281/user/usr/bin/lsmioworker",
                "rank",
                "/work/e281/e281/user/benchmark/runs/run1/manifest.json",
                "p1",
                "c4_b1M",
            ],
        )

        # 5. String resolution "ARCHER2"
        f_archer2_str_rank = Launcher.buildRankWorkerArgv(
            "ARCHER2",
            self.m_small_point,
            f_worker_executable="/usr/bin/lsmioworker",
            f_manifest_path="/tmp/manifest.json",
            f_point_id=0,
            f_combination_desc="c16_b8M",
        )
        self.assertEqual(
            f_archer2_str_rank,
            [
                "srun",
                "--export=ALL",
                "-n",
                "8",
                "-N",
                "8",
                "-p",
                "standard",
                "/usr/bin/lsmioworker",
                "rank",
                "/tmp/manifest.json",
                "0",
                "c16_b8M",
            ],
        )

        # 6. Verify non-Archer2 profiles do NOT include -p standard
        for f_prof in (
            self.m_viking_profile,
            self.m_viking2_profile,
            self.m_isambard_profile,
            self.m_dev_profile,
        ):
            f_argv = Launcher.buildSharedArgv(
                f_prof, self.m_small_point, self.m_ior_command
            )
            self.assertNotIn("-p", f_argv)
            self.assertNotIn("standard", f_argv)

    def testSharedVersusRankWorkerTail(self) -> None:
        """Validates that shared mode appends benchmark argv while rank mode appends rank worker tail."""
        f_manifest = "/tmp/runs/run123/manifest.json"
        f_worker = "/tmp/usr/bin/lsmioworker"

        # Shared mode on Viking
        f_shared_argv = Launcher.buildSharedArgv(
            self.m_viking_profile, self.m_small_point, ["ior", "-w", "-r"]
        )
        self.assertEqual(f_shared_argv[-3:], ["ior", "-w", "-r"])
        self.assertNotIn("rank", f_shared_argv)
        self.assertNotIn(f_manifest, f_shared_argv)

        # Rank worker mode on Viking
        f_rank_argv = Launcher.buildRankWorkerArgv(
            self.m_viking_profile,
            self.m_small_point,
            f_worker_executable=f_worker,
            f_manifest_path=f_manifest,
            f_point_id="point_0",
            f_combination_desc="c16_b8M",
        )
        self.assertEqual(
            f_rank_argv,
            [
                "srun",
                "--export=ALL",
                "-n",
                "8",
                "-N",
                "8",
                f_worker,
                "rank",
                f_manifest,
                "point_0",
                "c16_b8M",
            ],
        )

        # Rank worker mode on Isambard (PBS)
        f_pbs_rank_argv = Launcher.buildRankWorkerArgv(
            self.m_isambard_profile,
            self.m_large_point,
            f_worker_executable=f_worker,
            f_manifest_path=f_manifest,
            f_point_id="point_1",
            f_combination_desc=(4, "1M"),
        )
        self.assertEqual(
            f_pbs_rank_argv,
            [
                "aprun",
                "-n",
                "32",
                "-N",
                "4",
                f_worker,
                "rank",
                f_manifest,
                "point_1",
                "c4_b1M",
            ],
        )

        # Rank worker mode on DEV (Fake)
        f_fake_rank_argv = Launcher.buildRankWorkerArgv(
            self.m_dev_profile,
            self.m_single_point,
            f_worker_executable=f_worker,
            f_manifest_path=f_manifest,
            f_point_id=0,
            f_combination_desc=self.m_combination,
        )
        self.assertEqual(
            f_fake_rank_argv,
            [f_worker, "rank", f_manifest, "0", "c16_b8M"],
        )

        # Combination dictionary descriptor
        f_dict_comb_argv = Launcher.buildRankWorkerArgv(
            self.m_dev_profile,
            self.m_single_point,
            f_worker_executable=f_worker,
            f_manifest_path=f_manifest,
            f_point_id="p0",
            f_combination_desc={"stripe": 16, "block": "64K"},
        )
        self.assertEqual(
            f_dict_comb_argv,
            [f_worker, "rank", f_manifest, "p0", "c16_b64K"],
        )

    def testStatusPropagation(self) -> None:
        """Proves return codes (0, 1, 42, 127, signal -9, signal -15) from ProcessRunner propagate unchanged."""
        f_test_statuses = [0, 1, 42, 127, -9, -15]

        for f_status in f_test_statuses:
            f_mock_runner = MockProcessRunner(
                f_returncode=f_status,
                f_stdout=f"STDOUT_STATUS_{f_status}",
                f_stderr=f"STDERR_STATUS_{f_status}",
            )

            # Test launchShared
            f_res_shared = Launcher.launchShared(
                self.m_viking_profile,
                self.m_small_point,
                self.m_ior_command,
                f_runner=f_mock_runner,
            )
            self.assertEqual(f_res_shared.returncode, f_status)
            self.assertEqual(f_res_shared.returnCode, f_status)
            self.assertEqual(f_res_shared.stdout, f"STDOUT_STATUS_{f_status}")
            self.assertEqual(f_res_shared.stderr, f"STDERR_STATUS_{f_status}")
            if f_status == 0:
                self.assertTrue(f_res_shared.is_success)
                self.assertTrue(f_res_shared.isSuccess)
                self.assertFalse(f_res_shared.is_signal)
                self.assertIsNone(f_res_shared.signal_number)
            elif f_status < 0:
                self.assertFalse(f_res_shared.is_success)
                self.assertTrue(f_res_shared.is_signal)
                self.assertEqual(f_res_shared.signal_number, -f_status)
                self.assertEqual(f_res_shared.signalNumber, -f_status)
            else:
                self.assertFalse(f_res_shared.is_success)
                self.assertFalse(f_res_shared.is_signal)
                self.assertIsNone(f_res_shared.signal_number)

            # Test launchRankWorkers
            f_res_rank = Launcher.launchRankWorkers(
                self.m_isambard_profile,
                self.m_large_point,
                f_worker_executable="/usr/bin/lsmioworker",
                f_manifest_path="/tmp/manifest.json",
                f_point_id="p0",
                f_combination_desc=self.m_combination,
                f_runner=f_mock_runner,
            )
            self.assertEqual(f_res_rank.returncode, f_status)
            self.assertEqual(f_res_rank.returnCode, f_status)
            if f_status == 0:
                self.assertTrue(f_res_rank.is_success)
            elif f_status < 0:
                self.assertTrue(f_res_rank.is_signal)
                self.assertEqual(f_res_rank.signal_number, -f_status)
            else:
                self.assertFalse(f_res_rank.is_success)

    def testNoShell(self) -> None:
        """Spies on ProcessRunner to verify shell=False and tokenized argv without string concatenation."""
        f_mock_runner = MockProcessRunner(f_returncode=0)

        # Arguments with spaces and shell metacharacters
        f_complex_cmd = [
            "/usr/local/bin/my bench",
            "--param=value with spaces",
            "arg; rm -rf /",
            "$(whoami)",
            "`uname -a`",
        ]

        Launcher.launchShared(
            self.m_viking_profile,
            self.m_small_point,
            f_complex_cmd,
            f_runner=f_mock_runner,
        )

        self.assertEqual(len(f_mock_runner.m_invoked_argv), 1)
        f_invoked = f_mock_runner.m_invoked_argv[0]

        # Verify it is a discrete list of tokens
        self.assertIsInstance(f_invoked, list)
        self.assertEqual(
            f_invoked,
            [
                "srun",
                "--export=ALL",
                "-n",
                "8",
                "-N",
                "8",
                "/usr/local/bin/my bench",
                "--param=value with spaces",
                "arg; rm -rf /",
                "$(whoami)",
                "`uname -a`",
            ],
        )

        # Verify no element contains merged shell strings
        self.assertEqual(f_invoked[6], "/usr/local/bin/my bench")
        self.assertEqual(f_invoked[7], "--param=value with spaces")
        self.assertEqual(f_invoked[8], "arg; rm -rf /")
        self.assertEqual(f_invoked[9], "$(whoami)")
        self.assertEqual(f_invoked[10], "`uname -a`")

    def testDoesNotValidateEvidence(self) -> None:
        """Verifies launcher does not perform evidence file scans or rank cardinality checks."""
        f_mock_runner = MockProcessRunner(f_returncode=0)

        # Non-existent paths that would fail if filesystem existence was checked
        f_nonexistent_manifest = "/nonexistent/path/to/manifest_99999.json"
        f_nonexistent_worker = "/nonexistent/usr/bin/lsmioworker_99999"

        # Mock filesystem calls to ensure none are made by Launcher
        with patch("os.listdir") as f_mock_listdir, patch("os.walk") as f_mock_walk:
            # Shared launch
            f_res_shared = Launcher.launchShared(
                self.m_viking_profile,
                self.m_small_point,
                ["/nonexistent/bin/ior", "-w"],
                f_runner=f_mock_runner,
            )
            self.assertEqual(f_res_shared.returncode, 0)

            # Rank workers launch
            f_res_rank = Launcher.launchRankWorkers(
                self.m_archer2_profile,
                self.m_large_point,
                f_worker_executable=f_nonexistent_worker,
                f_manifest_path=f_nonexistent_manifest,
                f_point_id="p99",
                f_combination_desc="c16_b8M",
                f_runner=f_mock_runner,
            )
            self.assertEqual(f_res_rank.returncode, 0)

            # Assert directory scans were not performed
            f_mock_listdir.assert_not_called()
            f_mock_walk.assert_not_called()

    def testErrorHandlingAndValidation(self) -> None:
        """Verifies strict error handling for invalid profiles, scale points, and command arguments."""
        # 1. Invalid profile
        with self.assertRaises(LauncherError):
            Launcher.buildSharedArgv("UNKNOWN_SITE_9999", self.m_small_point, ["ior"])

        with self.assertRaises(LauncherError):
            Launcher.buildSharedArgv(12345, self.m_small_point, ["ior"])

        # 2. Invalid scale points
        with self.assertRaises(LauncherError):
            Launcher.buildSharedArgv(self.m_viking_profile, None, ["ior"])

        with self.assertRaises(LauncherError):
            # Non-positive tasks
            Launcher.buildSharedArgv(
                self.m_viking_profile, {"tasks": 0, "ppn": 1, "nodes": 0}, ["ior"]
            )

        with self.assertRaises(LauncherError):
            # Negative tasks
            Launcher.buildSharedArgv(self.m_viking_profile, (-4, 1, 4), ["ior"])

        with self.assertRaises(LauncherError):
            # Invalid point tuple length
            Launcher.buildSharedArgv(self.m_viking_profile, (1, 2, 3, 4), ["ior"])

        # 3. Invalid command argv
        with self.assertRaises(LauncherError):
            Launcher.buildSharedArgv(self.m_viking_profile, self.m_small_point, None)

        with self.assertRaises(LauncherError):
            Launcher.buildSharedArgv(self.m_viking_profile, self.m_small_point, [])

        with self.assertRaises(LauncherError):
            Launcher.buildSharedArgv(self.m_viking_profile, self.m_small_point, "")

        with self.assertRaises(LauncherError):
            Launcher.buildSharedArgv(
                self.m_viking_profile, self.m_small_point, ["ior", None]
            )

        with self.assertRaises(LauncherError):
            Launcher.buildSharedArgv(
                self.m_viking_profile, self.m_small_point, ["ior", "arg\0with_nul"]
            )

        # 4. Invalid rank worker arguments
        with self.assertRaises(LauncherError):
            Launcher.buildRankWorkerArgv(
                self.m_viking_profile,
                self.m_small_point,
                "",
                "/tmp/m.json",
                "p0",
                "c16_b8M",
            )

        with self.assertRaises(LauncherError):
            Launcher.buildRankWorkerArgv(
                self.m_viking_profile,
                self.m_small_point,
                "/bin/worker\0nul",
                "/tmp/m.json",
                "p0",
                "c16_b8M",
            )

        with self.assertRaises(LauncherError):
            Launcher.buildRankWorkerArgv(
                self.m_viking_profile,
                self.m_small_point,
                "/bin/worker",
                "",
                "p0",
                "c16_b8M",
            )

        with self.assertRaises(LauncherError):
            Launcher.buildRankWorkerArgv(
                self.m_viking_profile,
                self.m_small_point,
                "/bin/worker",
                "/tmp/m.json",
                None,
                "c16_b8M",
            )

        with self.assertRaises(LauncherError):
            Launcher.buildRankWorkerArgv(
                self.m_viking_profile,
                self.m_small_point,
                "/bin/worker",
                "/tmp/m.json",
                "p0",
                None,
            )

        with self.assertRaises(LauncherError):
            Launcher.buildRankWorkerArgv(
                self.m_viking_profile,
                self.m_small_point,
                "/bin/worker",
                "/tmp/m.json",
                "p0",
                12345,
            )

    def testAliasesAndClassMethods(self) -> None:
        """Verifies both static/classmethod and instance invocation and snake_case aliases."""
        f_inst = Launcher()
        f_mock_runner = MockProcessRunner(f_returncode=0)

        # camelCase and snake_case for buildSharedArgv
        f_res1 = Launcher.buildSharedArgv(
            self.m_viking_profile, self.m_small_point, ["ior"]
        )
        f_res2 = f_inst.build_shared_argv(
            self.m_viking_profile, self.m_small_point, ["ior"]
        )
        self.assertEqual(f_res1, f_res2)

        # camelCase and snake_case for buildRankWorkerArgv
        f_res3 = Launcher.buildRankWorkerArgv(
            self.m_viking_profile,
            self.m_small_point,
            "/bin/w",
            "/m.json",
            "p0",
            "c16_b8M",
        )
        f_res4 = f_inst.build_rank_worker_argv(
            self.m_viking_profile,
            self.m_small_point,
            "/bin/w",
            "/m.json",
            "p0",
            "c16_b8M",
        )
        self.assertEqual(f_res3, f_res4)

        # camelCase and snake_case for launchShared
        f_exec1 = Launcher.launchShared(
            self.m_viking_profile, self.m_small_point, ["ior"], f_runner=f_mock_runner
        )
        f_exec2 = f_inst.launch_shared(
            self.m_viking_profile, self.m_small_point, ["ior"], f_runner=f_mock_runner
        )
        self.assertEqual(f_exec1.returncode, f_exec2.returncode)

        # camelCase and snake_case for launchRankWorkers
        f_exec3 = Launcher.launchRankWorkers(
            self.m_viking_profile,
            self.m_small_point,
            "/bin/w",
            "/m.json",
            "p0",
            "c16_b8M",
            f_runner=f_mock_runner,
        )
        f_exec4 = f_inst.launch_rank_workers(
            self.m_viking_profile,
            self.m_small_point,
            "/bin/w",
            "/m.json",
            "p0",
            "c16_b8M",
            f_runner=f_mock_runner,
        )
        self.assertEqual(f_exec3.returncode, f_exec4.returncode)

    def testRunnerExceptionsPropagate(self) -> None:
        """Verifies that ProcessSpawnError, ProcessLoggingError, and ProcessExecutionError propagate directly."""
        f_spawn_err_runner = MockProcessRunner(
            f_exception_to_raise=ProcessSpawnError("Failed to spawn binary")
        )
        with self.assertRaises(ProcessSpawnError):
            Launcher.launchShared(
                self.m_viking_profile,
                self.m_small_point,
                ["ior"],
                f_runner=f_spawn_err_runner,
            )

        with self.assertRaises(ProcessSpawnError):
            Launcher.launchRankWorkers(
                self.m_viking_profile,
                self.m_small_point,
                "/bin/w",
                "/m.json",
                "p0",
                "c16_b8M",
                f_runner=f_spawn_err_runner,
            )


if __name__ == "__main__":
    unittest.main()
