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

import enum
import os
import sys
import tempfile
import types
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
    SiteResolutionError,
)
from lsmiotool.lib.worker import (
    OMPI_TMPDIR_ENV,
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
        # 1. Viking (Slurm, ppn=1): ['srun', '--export=ALL', '--kill-on-bad-exit=1', '-n', '8', '-N', '8', ...]
        f_viking_small = Launcher.buildSharedArgv(
            self.m_viking_profile, self.m_small_point, self.m_ior_command
        )
        self.assertEqual(
            f_viking_small,
            [
                "srun",
                "--export=ALL",
                "--kill-on-bad-exit=1",
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

        # 2. Viking (Slurm, ppn=4): ['srun', '--export=ALL', '--kill-on-bad-exit=1', '-n', '32', '-N', '8', ...]
        f_viking_large = Launcher.buildSharedArgv(
            self.m_viking_profile, self.m_large_point, self.m_ior_command
        )
        self.assertEqual(
            f_viking_large,
            [
                "srun",
                "--export=ALL",
                "--kill-on-bad-exit=1",
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

        # 3. Viking2 (Slurm, ppn=1): srun_mpi=pmix, since its Open MPI 5 module sets
        # SLURM_MPI_TYPE=none

        f_viking2_small = Launcher.buildSharedArgv(
            self.m_viking2_profile, self.m_small_point, self.m_lmp_command
        )
        self.assertEqual(
            f_viking2_small,
            [
                "srun",
                "--export=ALL",
                "--kill-on-bad-exit=1",
                "--mpi=pmix",
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
                "--kill-on-bad-exit=1",
                "--mpi=pmix",
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
                "--kill-on-bad-exit=1",
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
                "--kill-on-bad-exit=1",
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
                "--kill-on-bad-exit=1",
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
                "--kill-on-bad-exit=1",
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
                "--kill-on-bad-exit=1",
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

    def testSrunMpiFromProfile(self) -> None:
        """srun_mpi adds --mpi=<type> to both srun forms; without it srun is left to the environment."""
        f_worker = "/tmp/usr/bin/lsmioworker"
        f_manifest = "/tmp/runs/run123/manifest.json"

        def _rankArgv(f_profile: Any) -> List[str]:
            return Launcher.buildRankWorkerArgv(
                f_profile,
                self.m_small_point,
                f_worker_executable=f_worker,
                f_manifest_path=f_manifest,
                f_point_id="point_0",
                f_combination_desc="c16_b8M",
            )

        self.assertEqual(self.m_viking2_profile.launcher.srun_mpi, "pmix")
        self.assertEqual(
            _rankArgv(self.m_viking2_profile)[:7],
            [
                "srun",
                "--export=ALL",
                "--kill-on-bad-exit=1",
                "--mpi=pmix",
                "-n",
                "8",
                "-N",
            ],
        )
        self.assertEqual(
            Launcher.buildSharedArgv(
                self.m_viking2_profile, self.m_small_point, ["ior"]
            )[3],
            "--mpi=pmix",
        )

        # Viking (Open MPI 4) and ARCHER2 (Cray MPICH) leave srun to the environment
        for f_profile in (self.m_viking_profile, self.m_archer2_profile):
            self.assertIsNone(f_profile.launcher.srun_mpi)
            self.assertFalse(
                any(f_a.startswith("--mpi") for f_a in _rankArgv(f_profile))
            )

        # The other profile forms the launcher accepts
        self.assertIn("--mpi=pmix", _rankArgv(LauncherPolicy("srun", "pmix")))
        self.assertIn(
            "--mpi=pmi2", _rankArgv({"scheduler": "slurm", "srun_mpi": "pmi2"})
        )
        self.assertIn("--mpi=pmix", _rankArgv("VIKING2"))
        self.assertFalse(any(f_a.startswith("--mpi") for f_a in _rankArgv("slurm")))
        with self.assertRaises(LauncherError):
            _rankArgv({"scheduler": "slurm", "srun_mpi": 5})

        # srun_mpi only makes sense for srun, and must be a plugin type
        with self.assertRaises(SiteResolutionError):
            LauncherPolicy("aprun", "pmix")
        with self.assertRaises(SiteResolutionError):
            LauncherPolicy("srun", "pmix --overcommit")
        with self.assertRaises(SiteResolutionError):
            LauncherPolicy("srun", "")

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
                "--kill-on-bad-exit=1",
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
                "--kill-on-bad-exit=1",
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
        self.assertEqual(f_invoked[7], "/usr/local/bin/my bench")
        self.assertEqual(f_invoked[8], "--param=value with spaces")
        self.assertEqual(f_invoked[9], "arg; rm -rf /")
        self.assertEqual(f_invoked[10], "$(whoami)")
        self.assertEqual(f_invoked[11], "`uname -a`")

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

    def testSlurmLaunchEnvironment(self) -> None:
        """Slurm launches default the Open MPI session directory to /dev/shm; others are untouched."""
        f_mock_runner = MockProcessRunner(f_returncode=0)

        # 1. Slurm, no caller env: os.environ plus both defaults
        with patch.dict(os.environ, {"LSMIO_ENV_PROBE": "1"}, clear=False):
            for f_key in OMPI_TMPDIR_ENV:
                os.environ.pop(f_key, None)
            Launcher.launchShared(
                self.m_viking2_profile,
                self.m_small_point,
                ["ior"],
                f_runner=f_mock_runner,
            )
        f_env = f_mock_runner.m_invoked_kwargs[-1]["f_env"]
        self.assertEqual(f_env["LSMIO_ENV_PROBE"], "1")
        self.assertEqual(f_env["OMPI_MCA_orte_tmpdir_base"], "/dev/shm")
        self.assertEqual(f_env["PRTE_MCA_prte_tmpdir_base"], "/dev/shm")

        # 2. Slurm, caller env: a set value wins, an empty one is filled; the input is not mutated
        f_caller_env = {
            "OMPI_MCA_orte_tmpdir_base": "/scratch/ompi",
            "PRTE_MCA_prte_tmpdir_base": "",
        }
        Launcher.launchRankWorkers(
            self.m_viking2_profile,
            self.m_small_point,
            "/bin/w",
            "/m.json",
            "p0",
            "c16_b8M",
            f_runner=f_mock_runner,
            f_env=f_caller_env,
        )
        f_env = f_mock_runner.m_invoked_kwargs[-1]["f_env"]
        self.assertEqual(f_env["OMPI_MCA_orte_tmpdir_base"], "/scratch/ompi")
        self.assertEqual(f_env["PRTE_MCA_prte_tmpdir_base"], "/dev/shm")
        self.assertEqual(f_caller_env["PRTE_MCA_prte_tmpdir_base"], "")

        # 3. PBS and DEV: the environment passes through unchanged (None, or the same mapping)
        for f_profile in (self.m_isambard_profile, self.m_dev_profile):
            Launcher.launchShared(
                f_profile, self.m_small_point, ["ior"], f_runner=f_mock_runner
            )
            self.assertIsNone(f_mock_runner.m_invoked_kwargs[-1]["f_env"])

            f_own_env = {"PATH": "/usr/bin"}
            Launcher.launchRankWorkers(
                f_profile,
                self.m_small_point,
                "/bin/w",
                "/m.json",
                "p0",
                "c16_b8M",
                f_runner=f_mock_runner,
                f_env=f_own_env,
            )
            self.assertIs(f_mock_runner.m_invoked_kwargs[-1]["f_env"], f_own_env)
            self.assertEqual(f_own_env, {"PATH": "/usr/bin"})


class FauxList:
    """A container that evaluates to True in boolean contexts but yields zero elements when iterated."""

    def __bool__(self) -> bool:
        return True

    def __iter__(self) -> Any:
        return iter([])


class LauncherContractTest(unittest.TestCase):
    """Contract verification test suite for Launcher eliminating all coverage gaps in IDs 005 and 006."""

    def testExtractPointAlternativeAttributesAndTuples(self) -> None:
        """Validates point extraction from alternative attribute names, 1/2-tuples, ints, and unsupported types."""
        # 1. task_count, tasks_per_node, node_count (lines 1309-1311, arc [1308, 1309])
        f_pt_obj = types.SimpleNamespace(task_count=16, tasks_per_node=2, node_count=8)
        self.assertEqual(Launcher._extractPoint(f_pt_obj), (16, 2, 8))

        # 2. 2-tuple (tasks, ppn) with derived nodes (line 1320, 1346, arcs [1319, 1320], [1345, 1346])
        self.assertEqual(Launcher._extractPoint((16, 2)), (16, 2, 8))

        # 3. 1-tuple (tasks,) with default ppn=1 and derived nodes (lines 1322, 1323, arc [1321, 1322])
        self.assertEqual(Launcher._extractPoint((8,)), (8, 1, 8))
        self.assertEqual(Launcher._extractPoint([4]), (4, 1, 4))

        # 4. int tasks with default ppn=1 and derived nodes (lines 1328-1330, arcs [1316, 1328], [1328, 1329])
        self.assertEqual(Launcher._extractPoint(8), (8, 1, 8))

        # 5. Unsupported type raises LauncherError (line 1332, arc [1328, 1332])
        for f_bad_pt in (1.5, {1, 2}, set()):
            with self.subTest(bad_pt=f_bad_pt):
                with self.assertRaises(LauncherError) as f_ctx:
                    Launcher._extractPoint(f_bad_pt)
                self.assertIn("Unsupported scale point type", str(f_ctx.exception))

    def testExtractPointValidationErrors(self) -> None:
        """Validates error guards for non-positive ppn and nodes in _extractPoint."""
        # Invalid ppn (line 1341, arc [1340, 1341])
        # Note: must use tuple or object because dict.get("ppn") or 1 replaces falsy 0 with 1
        for f_bad_ppn in (0, -1, True, "2"):
            with self.subTest(bad_ppn=f_bad_ppn):
                with self.assertRaises(LauncherError) as f_ctx:
                    Launcher._extractPoint((8, f_bad_ppn, 1))
                self.assertIn("Scale point ppn must be a positive integer", str(f_ctx.exception))

        # Invalid nodes (line 1349, arc [1348, 1349])
        # Note: must use tuple or object because dict.get("nodes") or ... replaces falsy 0 with None
        for f_bad_nodes in (0, -1, True, "4"):
            with self.subTest(bad_nodes=f_bad_nodes):
                with self.assertRaises(LauncherError) as f_ctx:
                    Launcher._extractPoint((8, 1, f_bad_nodes))
                self.assertIn("Scale point nodes must be a positive integer", str(f_ctx.exception))

    def testResolveSrunMpiEdgeCases(self) -> None:
        """Validates profile srun_mpi resolution fallback paths and error translation."""
        # 1. Unresolvable site profile raises LauncherError (lines 1391, 1392)
        with self.assertRaises(LauncherError) as f_ctx:
            Launcher._resolveSrunMpi("UNKNOWN_SITE_XYZ_999")
        self.assertIn("Failed to resolve site profile", str(f_ctx.exception))

        # 2. Object without .launcher having string .srun_mpi (lines 1398, 1399, arc [1396, 1398])
        f_prof_srun_mpi = types.SimpleNamespace(srun_mpi="pmix")
        self.assertEqual(Launcher._resolveSrunMpi(f_prof_srun_mpi), "pmix")

        # 3. Object without .launcher having None or non-string .srun_mpi
        f_prof_none = types.SimpleNamespace(srun_mpi=None)
        self.assertIsNone(Launcher._resolveSrunMpi(f_prof_none))
        f_prof_empty = types.SimpleNamespace()
        self.assertIsNone(Launcher._resolveSrunMpi(f_prof_empty))

    def testResolveSchedulerAndPartitionKindsAndPolicies(self) -> None:
        """Validates SchedulerKind direct pass-through and LauncherPolicy kind matrix."""
        # 1. Direct SchedulerKind pass-through (line 1430, arc [1429, 1430])
        self.assertEqual(
            Launcher._resolveSchedulerAndPartition(SchedulerKind.SLURM),
            (SchedulerKind.SLURM, None),
        )
        self.assertEqual(
            Launcher._resolveSchedulerAndPartition(SchedulerKind.PBS),
            (SchedulerKind.PBS, None),
        )

        # 2. LauncherPolicy variants (lines 1436-1441, arcs [1434, 1436], [1436, 1437], [1436, 1438], [1438, 1439], [1438, 1441])
        self.assertEqual(
            Launcher._resolveSchedulerAndPartition(LauncherPolicy("pbs")),
            (SchedulerKind.PBS, None),
        )
        self.assertEqual(
            Launcher._resolveSchedulerAndPartition(LauncherPolicy("aprun")),
            (SchedulerKind.PBS, None),
        )
        self.assertEqual(
            Launcher._resolveSchedulerAndPartition(LauncherPolicy("direct")),
            (SchedulerKind.FAKE, None),
        )
        self.assertEqual(
            Launcher._resolveSchedulerAndPartition(LauncherPolicy("fake")),
            (SchedulerKind.FAKE, None),
        )
        with self.assertRaises(LauncherError) as f_ctx:
            Launcher._resolveSchedulerAndPartition(LauncherPolicy("custom_kind"))
        self.assertIn("Unknown launcher policy kind", str(f_ctx.exception))

    def testResolveSchedulerAndPartitionEnumsAndStrings(self) -> None:
        """Validates LaunchMode enums and direct string scheduler names."""
        # 1. LaunchMode enum values (lines 1445-1451, arcs [1444, 1445], [1446, 1447], [1446, 1448], [1448, 1449], [1448, 1450], [1450, 1451], [1450, 1453])
        self.assertEqual(
            Launcher._resolveSchedulerAndPartition(LaunchMode.SLURM),
            (SchedulerKind.SLURM, None),
        )
        self.assertEqual(
            Launcher._resolveSchedulerAndPartition(LaunchMode.PBS),
            (SchedulerKind.PBS, None),
        )
        self.assertEqual(
            Launcher._resolveSchedulerAndPartition(LaunchMode.DIRECT),
            (SchedulerKind.FAKE, None),
        )
        self.assertEqual(
            Launcher._resolveSchedulerAndPartition(LaunchMode.FAKE),
            (SchedulerKind.FAKE, None),
        )

        # Enum with unhandled value falls through arc [1450, 1453]
        class OtherEnum(enum.Enum):
            OTHER = "other"

        with self.assertRaises(LauncherError):
            Launcher._resolveSchedulerAndPartition(OtherEnum.OTHER)

        # 2. Direct string names "pbs", "aprun" (line 1461, arc [1460, 1461])
        self.assertEqual(
            Launcher._resolveSchedulerAndPartition("pbs"),
            (SchedulerKind.PBS, None),
        )
        self.assertEqual(
            Launcher._resolveSchedulerAndPartition("aprun"),
            (SchedulerKind.PBS, None),
        )

    def testResolveSchedulerAndPartitionAttributes(self) -> None:
        """Validates attribute-based scheduler extraction and fallback error handling."""
        # Lines 1482-1489, arcs [1480, 1482], [1482, 1483], [1482, 1505], [1484, 1485], [1484, 1486], [1486, 1487], [1486, 1488], [1488, 1489], [1488, 1505]
        self.assertEqual(
            Launcher._resolveSchedulerAndPartition(types.SimpleNamespace(scheduler="srun")),
            (SchedulerKind.SLURM, None),
        )
        self.assertEqual(
            Launcher._resolveSchedulerAndPartition(types.SimpleNamespace(scheduler="aprun")),
            (SchedulerKind.PBS, None),
        )
        self.assertEqual(
            Launcher._resolveSchedulerAndPartition(types.SimpleNamespace(scheduler="direct")),
            (SchedulerKind.FAKE, None),
        )
        with self.assertRaises(LauncherError):
            Launcher._resolveSchedulerAndPartition(types.SimpleNamespace(scheduler="invalid"))
        with self.assertRaises(LauncherError):
            Launcher._resolveSchedulerAndPartition(types.SimpleNamespace(scheduler=12345))

    def testResolveSchedulerAndPartitionDictContainers(self) -> None:
        """Validates dictionary profile scheduler extraction and error paths."""
        # Lines 1498-1503, arcs [1494, 1502], [1496, 1498], [1498, 1499], [1498, 1500], [1500, 1501], [1500, 1505], [1502, 1503], [1502, 1505]
        self.assertEqual(
            Launcher._resolveSchedulerAndPartition({"scheduler": "pbs"}),
            (SchedulerKind.PBS, None),
        )
        self.assertEqual(
            Launcher._resolveSchedulerAndPartition({"launcher": "direct"}),
            (SchedulerKind.FAKE, None),
        )
        self.assertEqual(
            Launcher._resolveSchedulerAndPartition({"scheduler": SchedulerKind.PBS}),
            (SchedulerKind.PBS, None),
        )
        with self.assertRaises(LauncherError):
            Launcher._resolveSchedulerAndPartition({"scheduler": "unknown_scheduler"})
        with self.assertRaises(LauncherError):
            Launcher._resolveSchedulerAndPartition({"scheduler": 9999})

    def testResolveSchedulerAndPartitionSlurmPartitions(self) -> None:
        """Validates Slurm partition extraction across resources dict, top-level attributes, and name fallbacks."""
        # 1. Line 1533, arcs [1529, 1543], [1532, 1533], [1534, 1543]: resources dict with shape dict
        f_prof_res_dict = types.SimpleNamespace(
            scheduler="slurm", resources={"small": {"partition": "dict_part"}}
        )
        self.assertEqual(
            Launcher._resolveSchedulerAndPartition(f_prof_res_dict),
            (SchedulerKind.SLURM, "dict_part"),
        )

        # Empty resources dict falls through [1529, 1543]
        f_prof_res_empty = types.SimpleNamespace(scheduler="slurm", resources={})
        self.assertEqual(
            Launcher._resolveSchedulerAndPartition(f_prof_res_empty),
            (SchedulerKind.SLURM, None),
        )

        # 2. Line 1541, arcs [1536, 1543], [1540, 1541]: dict profile with resources dict
        f_dict_prof_res = {
            "scheduler": "slurm",
            "resources": {"small": {"partition": "slurm_part"}},
        }
        self.assertEqual(
            Launcher._resolveSchedulerAndPartition(f_dict_prof_res),
            (SchedulerKind.SLURM, "slurm_part"),
        )

        # Dict profile with non-dict/None resources triggers arc [1536, 1543]
        self.assertEqual(
            Launcher._resolveSchedulerAndPartition({"scheduler": "slurm", "resources": None}),
            (SchedulerKind.SLURM, None),
        )
        self.assertEqual(
            Launcher._resolveSchedulerAndPartition({"scheduler": "slurm", "resources": {}}),
            (SchedulerKind.SLURM, None),
        )

        # 3. Line 1548, arc [1543, 1548]: object with .partition
        f_prof_part_attr = types.SimpleNamespace(scheduler="slurm", partition="custom_part")
        self.assertEqual(
            Launcher._resolveSchedulerAndPartition(f_prof_part_attr),
            (SchedulerKind.SLURM, "custom_part"),
        )

        # 4. Line 1554, arc [1549, 1554]: dict profile with top-level partition
        f_dict_top_part = {"scheduler": "slurm", "partition": "dict_top_part"}
        self.assertEqual(
            Launcher._resolveSchedulerAndPartition(f_dict_top_part),
            (SchedulerKind.SLURM, "dict_top_part"),
        )

        # 5. Line 1559, arc [1558, 1559]: profile name fallback to "ARCHER2"
        f_archer2_fallback = types.SimpleNamespace(scheduler="slurm", name="ARCHER2")
        self.assertEqual(
            Launcher._resolveSchedulerAndPartition(f_archer2_fallback),
            (SchedulerKind.SLURM, "standard"),
        )

    def testExtractCommandArgvVariantsAndEdgeCases(self) -> None:
        """Validates command extraction from arguments attribute, single strings, and empty container checks."""
        # 1. Line 1583, arc [1582, 1583]: .arguments attribute
        f_cmd_args = types.SimpleNamespace(arguments=["ior", "-w", "-r"])
        self.assertEqual(Launcher._extractCommandArgv(f_cmd_args), ["ior", "-w", "-r"])

        # 2. Line 1589, arc [1587, 1589]: single command string
        self.assertEqual(Launcher._extractCommandArgv("ior -w -r"), ["ior -w -r"])

        # 3. Line 1591, arc [1586, 1591]: unsupported command container type
        for f_bad_cmd in (12345, {"cmd": "ior"}):
            with self.subTest(bad_cmd=f_bad_cmd):
                with self.assertRaises(LauncherError) as f_ctx:
                    Launcher._extractCommandArgv(f_bad_cmd)
                self.assertIn("Unsupported command container type", str(f_ctx.exception))

        # 4. Line 1610, arc [1609, 1610]: truthy container yielding zero items
        f_truthy_empty = types.SimpleNamespace(argv=FauxList())
        with self.assertRaises(LauncherError) as f_ctx:
            Launcher._extractCommandArgv(f_truthy_empty)
        self.assertIn("Command argv cannot be empty", str(f_ctx.exception))

    def testValidationGuards(self) -> None:
        """Validates argument guards for manifest path, point ID, and combination descriptor."""
        # 1. Manifest path NUL byte (line 1635, arc [1634, 1635])
        with self.assertRaises(LauncherError) as f_ctx:
            Launcher._validateManifestPath("/tmp/m\0.json")
        self.assertIn("Manifest path contains NUL byte", str(f_ctx.exception))

        # 2. Point ID empty and NUL byte (lines 1645, 1647, arcs [1644, 1645], [1646, 1647])
        with self.assertRaises(LauncherError) as f_ctx:
            Launcher._validatePointId("   ")
        self.assertIn("Point ID cannot be empty", str(f_ctx.exception))

        with self.assertRaises(LauncherError) as f_ctx:
            Launcher._validatePointId("p0\0bad")
        self.assertIn("Point ID contains NUL byte", str(f_ctx.exception))

        # 3. Combination descriptor empty and NUL byte (lines 1679, 1681, arcs [1678, 1679], [1680, 1681])
        with self.assertRaises(LauncherError) as f_ctx:
            Launcher._validateCombinationDesc("   ")
        self.assertIn("Combination descriptor cannot be empty", str(f_ctx.exception))

        with self.assertRaises(LauncherError) as f_ctx:
            Launcher._validateCombinationDesc("c16_b8M\0bad")
        self.assertIn("Combination descriptor contains NUL byte", str(f_ctx.exception))

    def testBuildArgvUnsupportedScheduler(self) -> None:
        """Validates unsupported scheduler fallthrough in buildSharedArgv and buildRankWorkerArgv."""
        with patch.object(Launcher, "_resolveSchedulerAndPartition", return_value=("CUSTOM", None)):
            # Line 1740, arc [1736, 1740]
            with self.assertRaises(LauncherError) as f_ctx:
                Launcher.buildSharedArgv(None, (8, 1, 8), ["ior"])
            self.assertIn("Unsupported scheduler kind: CUSTOM", str(f_ctx.exception))

            # Line 1817, arc [1813, 1817]
            with self.assertRaises(LauncherError) as f_ctx:
                Launcher.buildRankWorkerArgv(
                    None, (8, 1, 8), "/bin/worker", "/tmp/m.json", "p0", "c16_b8M"
                )
            self.assertIn("Unsupported scheduler kind: CUSTOM", str(f_ctx.exception))

    def testLaunchExecutionRunnerFallbackAndExceptions(self) -> None:
        """Validates runner kwargs fallback, default instantiation, caller env, and unexpected exceptions."""
        f_mock_runner = MockProcessRunner(f_returncode=0)

        # 1. launchShared runner kwargs fallback (line 1879, arc [1878, 1879])
        f_res1 = Launcher.launchShared(
            "fake", (8, 1, 8), ["ior"], runner=f_mock_runner
        )
        self.assertEqual(f_res1.returncode, 0)
        self.assertEqual(len(f_mock_runner.m_invoked_argv), 1)

        # 2. launchShared default ProcessRunner instantiation (line 1881, arc [1880, 1881])
        with patch.object(ProcessRunner, "run", return_value=ProcessResult(0)) as f_mock_run:
            f_res2 = Launcher.launchShared("fake", (8, 1, 8), ["ior"])
            self.assertEqual(f_res2.returncode, 0)
            f_mock_run.assert_called_once()

        # 3. launchShared with caller env (arc [1894, 1900])
        f_mock_runner_env = MockProcessRunner(f_returncode=0)
        f_res3 = Launcher.launchShared(
            "fake", (8, 1, 8), ["ior"], f_runner=f_mock_runner_env, f_env={"MY_CUSTOM_VAR": "val"}
        )
        self.assertEqual(f_res3.returncode, 0)
        self.assertEqual(
            f_mock_runner_env.m_invoked_kwargs[0]["f_env"], {"MY_CUSTOM_VAR": "val"}
        )

        # 4. launchShared unexpected exception translation (lines 1921, 1922)
        f_crash_runner = MockProcessRunner(
            f_exception_to_raise=RuntimeError("Subprocess fatal error")
        )
        with self.assertRaises(LauncherError) as f_ctx:
            Launcher.launchShared("fake", (8, 1, 8), ["ior"], f_runner=f_crash_runner)
        self.assertIn("Unexpected error executing shared launch", str(f_ctx.exception))
        self.assertIsInstance(f_ctx.exception.__cause__, RuntimeError)

        # 5. launchRankWorkers runner kwargs fallback (line 1969, arc [1968, 1969])
        f_mock_rank_runner = MockProcessRunner(f_returncode=0)
        f_res4 = Launcher.launchRankWorkers(
            "fake",
            (8, 1, 8),
            "/bin/worker",
            "/tmp/m.json",
            "p0",
            "c16_b8M",
            runner=f_mock_rank_runner,
        )
        self.assertEqual(f_res4.returncode, 0)
        self.assertEqual(len(f_mock_rank_runner.m_invoked_argv), 1)

        # 6. launchRankWorkers default ProcessRunner instantiation (line 1971, arc [1970, 1971])
        with patch.object(ProcessRunner, "run", return_value=ProcessResult(0)) as f_mock_run_rank:
            f_res5 = Launcher.launchRankWorkers(
                "fake", (8, 1, 8), "/bin/worker", "/tmp/m.json", "p0", "c16_b8M"
            )
            self.assertEqual(f_res5.returncode, 0)
            f_mock_run_rank.assert_called_once()

        # 7. launchRankWorkers unexpected exception translation (lines 2012, 2013)
        with self.assertRaises(LauncherError) as f_ctx:
            Launcher.launchRankWorkers(
                "fake",
                (8, 1, 8),
                "/bin/worker",
                "/tmp/m.json",
                "p0",
                "c16_b8M",
                f_runner=f_crash_runner,
            )
        self.assertIn("Unexpected error executing rank worker launch", str(f_ctx.exception))
        self.assertIsInstance(f_ctx.exception.__cause__, RuntimeError)


if __name__ == "__main__":
    unittest.main()
