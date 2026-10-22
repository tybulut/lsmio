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
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple
import unittest
from unittest.mock import MagicMock, patch

from lsmiotool.lib.artifacts import ArtifactLayout
from lsmiotool.lib.benchmarks import (
    BenchmarkCommand,
    BenchmarkConfigurationError,
    BenchmarkProbeError,
    CapabilityState,
    LsmioAdapter,
    LsmioBoundCommand,
    LsmioLaunchSpec,
    ProbeState,
)
from lsmiotool.lib.run import (
    Combination,
    PlanValidationError,
    RankIdentity,
    RunRequest,
    ScalePoint,
)


class MockProcessResult(NamedTuple):
    returncode: int
    stdout: str
    stderr: str


class LsmioAdapterTest(unittest.TestCase):
    """Comprehensive test suite for LsmioAdapter contract and invariants."""

    def setUp(self) -> None:
        self.m_adapter = LsmioAdapter()
        self.m_benchmark_root = "/benchmark"
        self.m_run_id = "run-20260820T120000Z-abcdef012345"
        self.m_layout = ArtifactLayout(
            f_benchmark_root=self.m_benchmark_root,
            f_run_id=self.m_run_id,
        )
        self.m_point = ScalePoint(f_tasks=4, f_ppn=1, f_nodes=4)
        self.m_combo_8m = Combination(
            f_processes=16,
            f_block_size="8M",
            f_stripe_count=16,
            f_block_bytes=8388608,
            f_key_count=1024,
            f_segment_count=128,
        )
        self.m_combo_1m = Combination(
            f_processes=16,
            f_block_size="1M",
            f_stripe_count=16,
            f_block_bytes=1048576,
            f_key_count=4096,
            f_segment_count=1024,
        )
        self.m_combo_64k = Combination(
            f_processes=16,
            f_block_size="64K",
            f_stripe_count=16,
            f_block_bytes=65536,
            f_key_count=32768,
            f_segment_count=16384,
        )

    def testExactSetupBlockMappings(self) -> None:
        """Validate all 33 exact setup/block permutations (11 setups x 3 block sizes)."""
        f_setups = [
            "NATIVE",
            "ADIOS",
            "PLUGIN",
            "ROCKSDB",
            "LEVELDB",
            "MANAGER",
            "ADIOS-SYNC",
            "NATIVE-SYNC",
            "PLUGIN-SYNC",
            "ROCKSDB-SYNC",
            "LEVELDB-SYNC",
        ]
        f_combos = [self.m_combo_64k, self.m_combo_1m, self.m_combo_8m]
        f_expected_executables = {
            "NATIVE": "bm_native",
            "ADIOS": "bm_adios",
            "PLUGIN": "bm_adios",
            "ROCKSDB": "bm_rocksdb",
            "LEVELDB": "bm_leveldb",
            "MANAGER": "bm_manager",
            "ADIOS-SYNC": "bm_adios",
            "NATIVE-SYNC": "bm_native",
            "PLUGIN-SYNC": "bm_adios",
            "ROCKSDB-SYNC": "bm_rocksdb",
            "LEVELDB-SYNC": "bm_leveldb",
        }
        f_setup_flags = {
            "PLUGIN": ["--lsmio-plugin"],
            "ADIOS-SYNC": ["--lsmio-always-flush"],
            "NATIVE-SYNC": ["--lsmio-always-flush"],
            "PLUGIN-SYNC": ["--lsmio-plugin", "--lsmio-always-flush"],
            "ROCKSDB-SYNC": ["--lsmio-always-flush"],
            "LEVELDB-SYNC": ["--lsmio-always-flush"],
        }
        f_block_params = {
            "64K": ("65536", "32768"),
            "1M": ("1048576", "4096"),
            "8M": ("8388608", "1024"),
        }

        f_tested_count = 0
        f_identity = RankIdentity(f_global_rank=0, f_node_rank="node01", f_local_rank=0)

        for f_setup in f_setups:
            for f_combo in f_combos:
                f_req = RunRequest(
                    f_target="lsmio", f_scale="small", f_ssd=False, f_setup=f_setup
                )
                f_spec = self.m_adapter.createLaunchSpec(
                    f_request=f_req,
                    f_combination=f_combo,
                    f_point=self.m_point,
                )
                f_bound = self.m_adapter.bindRank(
                    f_spec=f_spec,
                    f_identity=f_identity,
                    f_layout=self.m_layout,
                )

                f_expected_exe = f_expected_executables[f_setup]
                f_bsb, f_sg = f_block_params[f_combo.block_size]
                f_expected_out = os.path.join(
                    self.m_layout.pointDataSubdir(
                        self.m_point, f_combo.stripe_count, f_combo.block_size
                    ),
                    f"lsmio-rank-0-{f_setup.lower()}.db",
                )
                f_expected_log = os.path.join(
                    self.m_layout.pointLogsDir(self.m_point),
                    f_combo.name,
                    "rank_0.log",
                )
                f_expected_result = self.m_layout.pointRankResultPath(
                    self.m_point, 0, f_combo
                )

                # Assemble expected argv
                f_expected_argv_list: List[str] = [f_expected_exe, "-m", "-g"]
                f_expected_argv_list.extend(f_setup_flags.get(f_setup, []))
                f_expected_argv_list.extend(
                    [
                        "--lsmio-no-autotune",
                        "-i",
                        "10",
                        "-o",
                        f_expected_out,
                        "--lsmio-ts",
                        f_bsb,
                        "--lsmio-bs",
                        f_bsb,
                        "--key-count",
                        f_sg,
                    ]
                )

                self.assertEqual(
                    f_bound.argv,
                    tuple(f_expected_argv_list),
                    f"Argv mismatch for setup={f_setup} block_size={f_combo.block_size}",
                )
                self.assertEqual(f_bound.stdout_path, f_expected_log)
                self.assertEqual(f_bound.stderr_path, f_expected_log)
                self.assertEqual(f_bound.result_path, f_expected_result)
                self.assertEqual(f_bound.output_path, f_expected_out)
                self.assertTrue(f_bound.is_rank_local)
                self.assertTrue(f_bound.isRankLocal)
                f_tested_count += 1

        self.assertEqual(f_tested_count, 33)

    def testTemplateUnbound(self) -> None:
        """Confirm template from createLaunchSpec is unbound and rank-local."""
        f_req = RunRequest(
            f_target="lsmio", f_scale="small", f_ssd=False, f_setup="NATIVE"
        )
        f_spec = self.m_adapter.createLaunchSpec(
            f_request=f_req,
            f_combination=self.m_combo_8m,
            f_point=self.m_point,
        )

        self.assertTrue(f_spec.is_rank_local)
        self.assertTrue(f_spec.isRankLocal)
        self.assertFalse(f_spec.is_bound)
        self.assertFalse(f_spec.isBound)
        self.assertEqual(f_spec.setup, "NATIVE")
        self.assertEqual(f_spec.executable, "bm_native")
        self.assertEqual(f_spec.combination, self.m_combo_8m)
        self.assertEqual(f_spec.point, self.m_point)
        self.assertEqual(f_spec.arguments, ())
        self.assertEqual(f_spec.expected_results, ())
        self.assertEqual(f_spec.mode, "direct")

    def testPureBindDistinctGlobals(self) -> None:
        """Confirm distinct global ranks yield distinct rank-private paths."""
        f_req = RunRequest(
            f_target="lsmio", f_scale="small", f_ssd=False, f_setup="ROCKSDB"
        )
        f_spec = self.m_adapter.createLaunchSpec(
            f_request=f_req,
            f_combination=self.m_combo_1m,
            f_point=self.m_point,
        )

        f_ranks = [0, 1, 2, 3]
        f_bound_commands = []
        for f_r in f_ranks:
            f_id = RankIdentity(
                f_global_rank=f_r, f_node_rank=f"node0{f_r + 1}", f_local_rank=0
            )
            f_cmd = self.m_adapter.bindRank(
                f_spec=f_spec,
                f_identity=f_id,
                f_layout=self.m_layout,
            )
            f_bound_commands.append(f_cmd)

        f_output_paths = [f_cmd.output_path for f_cmd in f_bound_commands]
        f_log_paths = [f_cmd.stdout_path for f_cmd in f_bound_commands]
        f_result_paths = [f_cmd.result_path for f_cmd in f_bound_commands]

        # All 4 output paths must be distinct
        self.assertEqual(len(set(f_output_paths)), 4)
        for f_r, f_out in enumerate(f_output_paths):
            self.assertTrue(f_out.endswith(f"lsmio-rank-{f_r}-rocksdb.db"))

        # All 4 log paths must be distinct
        self.assertEqual(len(set(f_log_paths)), 4)
        for f_r, f_log in enumerate(f_log_paths):
            self.assertTrue(f_log.endswith(f"c16_b1M/rank_{f_r}.log"))

        # All 4 result paths must be distinct
        self.assertEqual(len(set(f_result_paths)), 4)
        for f_r, f_res in enumerate(f_result_paths):
            self.assertTrue(f_res.endswith(f"ranks/{f_r}/c16_b1M/result.json"))

    def testPbsNoneLocalAccepted(self) -> None:
        """Confirm PBS local_rank=None binds cleanly."""
        f_req = RunRequest(
            f_target="lsmio", f_scale="small", f_ssd=False, f_setup="LEVELDB"
        )
        f_spec = self.m_adapter.createLaunchSpec(
            f_request=f_req,
            f_combination=self.m_combo_64k,
            f_point=self.m_point,
        )

        f_pbs_identity = RankIdentity(
            f_global_rank=2,
            f_node_rank="isambard-nid00045",
            f_local_rank=None,
        )

        f_cmd = self.m_adapter.bindRank(
            f_spec=f_spec,
            f_identity=f_pbs_identity,
            f_layout=self.m_layout,
        )

        self.assertIsNotNone(f_cmd)
        self.assertEqual(f_cmd.identity.local_rank, None)
        self.assertEqual(f_cmd.identity.global_rank, 2)
        self.assertTrue(f_cmd.is_rank_local)
        self.assertTrue(f_cmd.output_path.endswith("lsmio-rank-2-leveldb.db"))
        self.assertTrue(f_cmd.stdout_path.endswith("c16_b64K/rank_2.log"))
        self.assertTrue(f_cmd.result_path.endswith("ranks/2/c16_b64K/result.json"))

    def testRangeAndContainment(self) -> None:
        """Assert negative or out-of-range global ranks fail with BenchmarkConfigurationError."""
        f_req = RunRequest(
            f_target="lsmio", f_scale="small", f_ssd=False, f_setup="NATIVE"
        )
        f_spec = self.m_adapter.createLaunchSpec(
            f_request=f_req,
            f_combination=self.m_combo_8m,
            f_point=self.m_point,  # tasks=4, valid ranks are 0, 1, 2, 3
        )

        # 1. Out of range: global_rank == tasks (4 >= 4)
        f_out_of_range_id = RankIdentity(
            f_global_rank=4, f_node_rank="node01", f_local_rank=0
        )
        with self.assertRaises(BenchmarkConfigurationError):
            self.m_adapter.bindRank(
                f_spec=f_spec,
                f_identity=f_out_of_range_id,
                f_layout=self.m_layout,
            )

        # 2. Large out of range: global_rank == 100
        f_large_id = RankIdentity(
            f_global_rank=100, f_node_rank="node01", f_local_rank=0
        )
        with self.assertRaises(BenchmarkConfigurationError):
            self.m_adapter.bindRank(
                f_spec=f_spec,
                f_identity=f_large_id,
                f_layout=self.m_layout,
            )

        # 3. Negative global rank in RankIdentity
        with self.assertRaises(PlanValidationError):
            RankIdentity(f_global_rank=-1, f_node_rank="node01", f_local_rank=0)

        # 4. Mock identity with negative global rank passed to bindRank
        f_mock_neg_id = MagicMock()
        f_mock_neg_id.global_rank = -1
        with self.assertRaises(BenchmarkConfigurationError):
            self.m_adapter.bindRank(
                f_spec=f_spec,
                f_identity=f_mock_neg_id,
                f_layout=self.m_layout,
            )

    def testNoClaimStoreOrFilesystemCalls(self) -> None:
        """Spy on filesystem and store to prove bindRank performs zero I/O or lock calls."""
        f_req = RunRequest(
            f_target="lsmio", f_scale="small", f_ssd=False, f_setup="MANAGER"
        )
        f_spec = self.m_adapter.createLaunchSpec(
            f_request=f_req,
            f_combination=self.m_combo_8m,
            f_point=self.m_point,
        )
        f_id = RankIdentity(f_global_rank=0, f_node_rank="node01", f_local_rank=0)

        with (
            patch("os.mkdir") as f_mock_mkdir,
            patch("os.makedirs") as f_mock_makedirs,
            patch("os.remove") as f_mock_remove,
            patch("os.unlink") as f_mock_unlink,
            patch("os.stat") as f_mock_stat,
            patch("os.lstat") as f_mock_lstat,
            patch("os.path.exists") as f_mock_exists,
            patch("builtins.open") as f_mock_open,
            patch("fcntl.flock") as f_mock_flock,
        ):
            f_bound = self.m_adapter.bindRank(
                f_spec=f_spec,
                f_identity=f_id,
                f_layout=self.m_layout,
            )

            self.assertIsNotNone(f_bound)
            f_mock_mkdir.assert_not_called()
            f_mock_makedirs.assert_not_called()
            f_mock_remove.assert_not_called()
            f_mock_unlink.assert_not_called()
            f_mock_stat.assert_not_called()
            f_mock_lstat.assert_not_called()
            f_mock_exists.assert_not_called()
            f_mock_open.assert_not_called()
            f_mock_flock.assert_not_called()

    def testEnvRejected(self) -> None:
        """Prove setup ENV is rejected cleanly."""
        # 1. createLaunchSpec with setup ENV
        with self.assertRaises(BenchmarkConfigurationError):
            self.m_adapter.createLaunchSpec(
                f_request=RunRequest(
                    f_target="lsmio", f_scale="small", f_ssd=False, f_setup="ENV"
                ),
                f_combination=self.m_combo_8m,
                f_point=self.m_point,
            )

        # 2. createLaunchSpec with lowercase setup 'env'
        with self.assertRaises(BenchmarkConfigurationError):
            self.m_adapter.createLaunchSpec(
                f_request=RunRequest(
                    f_target="lsmio", f_scale="small", f_ssd=False, f_setup="env"
                ),
                f_combination=self.m_combo_8m,
                f_point=self.m_point,
            )

        # 3. getExecutableName with ENV
        with self.assertRaises(BenchmarkConfigurationError):
            self.m_adapter.getExecutableName("ENV")

        # 4. probeCapability with ENV
        with self.assertRaises(BenchmarkProbeError):
            self.m_adapter.probeCapability(
                f_executable="bm_native",
                f_runner=lambda argv: MockProcessResult(0, "LSMIO", ""),
                f_setup="ENV",
            )

    def testProbeFailures(self) -> None:
        """Verify fail-closed handling for invalid arguments and diagnostic modes."""
        # 1. Invalid executable type or empty or whitespace
        with self.assertRaises(BenchmarkConfigurationError):
            self.m_adapter.probeCapability(f_executable="")
        with self.assertRaises(BenchmarkConfigurationError):
            self.m_adapter.probeCapability(f_executable="   ")
        with self.assertRaises(BenchmarkConfigurationError):
            self.m_adapter.probeCapability(f_executable=None)  # type: ignore

        # 2. Executable with NUL byte
        with self.assertRaises(BenchmarkConfigurationError):
            self.m_adapter.probeCapability(f_executable="/bin/bm_native\0")

        # 3. Diagnostic mode ENV requested for probe
        with self.assertRaises(BenchmarkProbeError):
            self.m_adapter.probeCapability(
                f_executable="/bin/bm_native",
                f_setup="ENV",
            )

        # 4. Invalid setup requested for probe
        with self.assertRaises(BenchmarkProbeError):
            self.m_adapter.probeCapability(
                f_executable="/bin/bm_native",
                f_setup="INVALID_SETUP",
            )

    def testUnverifiedNoVersionClaim(self) -> None:
        """Prove unprobeable LSMIO binaries remain recorded as configured/unverified (Critic P-02)."""
        # When runner is None, returns CapabilityState.CONFIGURED without claiming version
        f_state = self.m_adapter.probeCapability(
            f_executable="/bin/bm_native", f_runner=None
        )
        self.assertEqual(f_state, CapabilityState.CONFIGURED)
        self.assertEqual(f_state, ProbeState.CONFIGURED)
        self.assertTrue(f_state.is_configured)
        self.assertFalse(f_state.is_verified)
        self.assertFalse(f_state.is_unsupported)

        # When runner is provided, LSMIO binaries still remain configured/unverified because bare -v fails
        f_runner_called = False

        def mockRunner(f_argv: Sequence[str]) -> MockProcessResult:
            nonlocal f_runner_called
            f_runner_called = True
            return MockProcessResult(
                returncode=0, stdout="LSMIO Benchmark version 1.0", stderr=""
            )

        f_state_with_runner = self.m_adapter.probeCapability(
            f_executable="/bin/bm_native",
            f_runner=mockRunner,
            f_setup="NATIVE",
        )
        self.assertFalse(
            f_runner_called,
            "LSMIO probe should not invoke runner on probe-incapable binaries",
        )
        self.assertEqual(f_state_with_runner, CapabilityState.CONFIGURED)
        self.assertTrue(f_state_with_runner.is_configured)
        self.assertFalse(f_state_with_runner.is_verified)

    def testCommandImmutability(self) -> None:
        """Verify that LsmioLaunchSpec and LsmioBoundCommand are immutable."""
        f_req = RunRequest(
            f_target="lsmio", f_scale="small", f_ssd=False, f_setup="NATIVE"
        )
        f_spec = self.m_adapter.createLaunchSpec(
            f_request=f_req,
            f_combination=self.m_combo_8m,
            f_point=self.m_point,
        )
        with self.assertRaises(AttributeError):
            f_spec.m_setup = "ADIOS"
        with self.assertRaises(AttributeError):
            del f_spec.m_setup

        f_id = RankIdentity(f_global_rank=0, f_node_rank="node01", f_local_rank=0)
        f_bound = self.m_adapter.bindRank(
            f_spec=f_spec,
            f_identity=f_id,
            f_layout=self.m_layout,
        )
        with self.assertRaises(AttributeError):
            f_bound.m_argv = ("new", "argv")
        with self.assertRaises(AttributeError):
            f_bound.m_result_path = "/new/result.json"
        with self.assertRaises(AttributeError):
            del f_bound.m_argv

    def testSpacesRemainArgv(self) -> None:
        """Verify argv tokens with spaces remain discrete arguments and are not word-split."""
        f_exe_with_spaces = "/opt/lsmio tools/bin/bm native executable"
        f_req = RunRequest(
            f_target="lsmio", f_scale="small", f_ssd=False, f_setup="NATIVE"
        )
        f_spec = self.m_adapter.createLaunchSpec(
            f_request=f_req,
            f_combination=self.m_combo_8m,
            f_point=self.m_point,
            f_executable=f_exe_with_spaces,
        )
        f_id = RankIdentity(f_global_rank=0, f_node_rank="node 01", f_local_rank=0)
        f_bound = self.m_adapter.bindRank(
            f_spec=f_spec,
            f_identity=f_id,
            f_layout=self.m_layout,
        )

        self.assertEqual(f_bound.argv[0], f_exe_with_spaces)
        self.assertEqual(f_bound.argv[1], "-m")
        self.assertEqual(f_bound.argv[2], "-g")
        self.assertEqual(f_bound.argv[3], "--lsmio-no-autotune")
        self.assertEqual(f_bound.argv[4], "-i")
        self.assertEqual(f_bound.argv[5], "10")
        self.assertEqual(f_bound.argv[6], "-o")
        self.assertEqual(f_bound.argv[7], f_bound.output_path)

    def testNulByteRejection(self) -> None:
        """Verify that NUL bytes in arguments or paths raise BenchmarkConfigurationError."""
        f_req = RunRequest(
            f_target="lsmio", f_scale="small", f_ssd=False, f_setup="NATIVE"
        )
        with self.assertRaises(BenchmarkConfigurationError):
            self.m_adapter.createLaunchSpec(
                f_request=f_req,
                f_combination=self.m_combo_8m,
                f_point=self.m_point,
                f_executable="/bin/bm_native\0",
            )

        with self.assertRaises(BenchmarkConfigurationError):
            self.m_adapter.buildCommand(
                f_executable="/bin/bm_native\0",
                f_setup="NATIVE",
                f_block_size="8M",
            )

    def testAdapterProperties(self) -> None:
        """Verify adapter metadata properties and helper methods."""
        self.assertEqual(self.m_adapter.target, "lsmio")
        self.assertEqual(self.m_adapter.defaultSetup, "NATIVE")
        self.assertEqual(
            set(self.m_adapter.allowedSetups),
            {
                "NATIVE",
                "ADIOS",
                "PLUGIN",
                "ROCKSDB",
                "LEVELDB",
                "MANAGER",
                "ADIOS-SYNC",
                "NATIVE-SYNC",
                "PLUGIN-SYNC",
                "ROCKSDB-SYNC",
                "LEVELDB-SYNC",
            },
        )
        self.assertEqual(
            set(LsmioAdapter.ALLOWED_SETUPS) - set(LsmioAdapter.RUN_SETUPS),
            set(LsmioAdapter.ARM_ONLY_SETUPS),
        )
        # The planner plans each arm's sub-request: it accepts every setup the adapter runs
        from lsmiotool.lib.run import RunPlanner

        self.assertEqual(
            RunPlanner.ALLOWED_SETUPS["lsmio"], set(LsmioAdapter.ALLOWED_SETUPS)
        )
        self.assertEqual(LsmioAdapter.getBlockParameters("64K"), (65536, 32768))
        self.assertEqual(LsmioAdapter.getBlockParameters("1M"), (1048576, 4096))
        self.assertEqual(LsmioAdapter.getBlockParameters("8M"), (8388608, 1024))
        self.assertEqual(LsmioAdapter.getExecutableName("NATIVE"), "bm_native")
        self.assertEqual(LsmioAdapter.getExecutableName("ADIOS"), "bm_adios")
        self.assertEqual(LsmioAdapter.getExecutableName("PLUGIN"), "bm_adios")
        self.assertEqual(LsmioAdapter.getExecutableName("ROCKSDB"), "bm_rocksdb")
        self.assertEqual(LsmioAdapter.getExecutableName("LEVELDB"), "bm_leveldb")
        self.assertEqual(LsmioAdapter.getExecutableName("MANAGER"), "bm_manager")

    def testEqualityHashAndDict(self) -> None:
        """Verify equality, hashing, and dict conversion of LsmioLaunchSpec and LsmioBoundCommand."""
        f_req = RunRequest(
            f_target="lsmio", f_scale="small", f_ssd=False, f_setup="NATIVE"
        )
        f_spec1 = self.m_adapter.createLaunchSpec(
            f_request=f_req,
            f_combination=self.m_combo_8m,
            f_point=self.m_point,
        )
        f_spec2 = self.m_adapter.createLaunchSpec(
            f_request=f_req,
            f_combination=self.m_combo_8m,
            f_point=self.m_point,
        )
        f_spec3 = self.m_adapter.createLaunchSpec(
            f_request=f_req,
            f_combination=self.m_combo_1m,
            f_point=self.m_point,
        )

        self.assertEqual(f_spec1, f_spec2)
        self.assertEqual(hash(f_spec1), hash(f_spec2))
        self.assertNotEqual(f_spec1, f_spec3)

        f_dict = f_spec1.toDict()
        self.assertEqual(f_dict["target"], "lsmio")
        self.assertEqual(f_dict["setup"], "NATIVE")
        self.assertEqual(f_dict["executable"], "bm_native")
        self.assertEqual(f_dict["is_rank_local"], True)
        self.assertEqual(f_dict["is_bound"], False)

        f_id = RankIdentity(f_global_rank=0, f_node_rank="node01", f_local_rank=0)
        f_bound1 = self.m_adapter.bindRank(
            f_spec=f_spec1, f_identity=f_id, f_layout=self.m_layout
        )
        f_bound2 = self.m_adapter.bindRank(
            f_spec=f_spec1, f_identity=f_id, f_layout=self.m_layout
        )
        f_bound3 = self.m_adapter.bindRank(
            f_spec=f_spec3, f_identity=f_id, f_layout=self.m_layout
        )

        self.assertEqual(f_bound1, f_bound2)
        self.assertEqual(hash(f_bound1), hash(f_bound2))
        self.assertNotEqual(f_bound1, f_bound3)

        f_bound_dict = f_bound1.toDict()
        self.assertEqual(f_bound_dict["argv"], list(f_bound1.argv))
        self.assertEqual(f_bound_dict["stdout_path"], f_bound1.stdout_path)
        self.assertEqual(f_bound_dict["stderr_path"], f_bound1.stderr_path)
        self.assertEqual(f_bound_dict["working_dir"], f_bound1.working_dir)
        self.assertEqual(f_bound_dict["is_rank_local"], True)
        self.assertEqual(f_bound_dict["result_path"], f_bound1.result_path)
        self.assertEqual(f_bound_dict["output_path"], f_bound1.output_path)

    def testVariantLaunchSpecCreation(self) -> None:
        """Tasks 3.2.1: Verify launch spec captures variant property, enforces immutability and validation."""
        f_req = RunRequest(
            f_target="lsmio",
            f_scale="baseline",
            f_ssd=False,
            f_setup="NATIVE",
            f_variant="mmap-btree",
        )
        f_spec = self.m_adapter.createLaunchSpec(
            f_request=f_req,
            f_combination=self.m_combo_8m,
            f_point=self.m_point,
        )
        self.assertEqual(f_spec.variant, "mmap-btree")
        self.assertIn("variant='mmap-btree'", repr(f_spec))

        # Dict serialization with variant
        f_dict = f_spec.toDict()
        self.assertEqual(f_dict.get("variant"), "mmap-btree")

        # Immutability enforcement (INV-ARCH-6)
        with self.assertRaises(AttributeError):
            f_spec.variant = "wbuf-512m"
        with self.assertRaises(AttributeError):
            f_spec.m_variant = "wbuf-512m"
        with self.assertRaises(AttributeError):
            del f_spec.m_variant

        # Direct construction validations
        with self.assertRaises(BenchmarkConfigurationError):
            LsmioLaunchSpec(
                f_request=f_req,
                f_combination=self.m_combo_8m,
                f_point=self.m_point,
                f_setup="NATIVE",
                f_executable="bm_native",
                f_variant="",  # non-empty or None
            )
        with self.assertRaises(BenchmarkConfigurationError):
            LsmioLaunchSpec(
                f_request=f_req,
                f_combination=self.m_combo_8m,
                f_point=self.m_point,
                f_setup="NATIVE",
                f_executable="bm_native",
                f_variant="bad\0variant",
            )
        with self.assertRaises(BenchmarkConfigurationError):
            LsmioLaunchSpec(
                f_request=f_req,
                f_combination=self.m_combo_8m,
                f_point=self.m_point,
                f_setup="NATIVE",
                f_executable="bm_native",
                f_variant=12345,  # type: ignore
            )

        # Value equality and hashing with variant
        f_spec_same = self.m_adapter.createLaunchSpec(
            f_request=f_req,
            f_combination=self.m_combo_8m,
            f_point=self.m_point,
        )
        f_req_diff = RunRequest(
            f_target="lsmio",
            f_scale="baseline",
            f_ssd=False,
            f_setup="NATIVE",
            f_variant="wbuf-512m",
        )
        f_spec_diff = self.m_adapter.createLaunchSpec(
            f_request=f_req_diff,
            f_combination=self.m_combo_8m,
            f_point=self.m_point,
        )
        self.assertEqual(f_spec, f_spec_same)
        self.assertEqual(hash(f_spec), hash(f_spec_same))
        self.assertNotEqual(f_spec, f_spec_diff)

    def testBindRankWithVariantFlagInjection(self) -> None:
        """Tasks 3.2.2: Verify bindRank injects engine flags and derives deterministic infix DB name (INV-ARCH-4, INV-ARCH-8)."""
        f_req = RunRequest(
            f_target="lsmio",
            f_scale="baseline",
            f_ssd=False,
            f_setup="NATIVE",
            f_variant="mmap-btree",
        )
        f_spec = self.m_adapter.createLaunchSpec(
            f_request=f_req,
            f_combination=self.m_combo_8m,
            f_point=self.m_point,
        )
        f_id = RankIdentity(f_global_rank=0, f_node_rank="node01", f_local_rank=0)
        f_bound = self.m_adapter.bindRank(
            f_spec=f_spec,
            f_identity=f_id,
            f_layout=self.m_layout,
        )

        # Infix DB naming (INV-ARCH-8)
        self.assertTrue(
            f_bound.output_path.endswith("lsmio-rank-0-native-mmap-btree.db"),
            f"Expected output_path to end with lsmio-rank-0-native-mmap-btree.db, got: {f_bound.output_path}",
        )

        # Flag injection in argv (INV-ARCH-4)
        f_expected_flags = (
            "--lsmio-no-autotune",
            "--lsmio-memtable",
            "btree",
            "--lsmio-mmap",
            "--lsmio-no-pread",
        )
        for f_flag in f_expected_flags:
            self.assertIn(f_flag, f_bound.argv)

        # Flag ordering: -m, -g before variant flags, before -i 10 -o ...
        idx_m = f_bound.argv.index("-m")
        idx_mmap = f_bound.argv.index("--lsmio-mmap")
        idx_iter = f_bound.argv.index("-i")
        self.assertLess(idx_m, idx_mmap)
        self.assertLess(idx_mmap, idx_iter)
        self.assertEqual(
            f_bound.argv[1:8],
            (
                "-m",
                "-g",
                "--lsmio-no-autotune",
                "--lsmio-memtable",
                "btree",
                "--lsmio-mmap",
                "--lsmio-no-pread",
            ),
        )

        # Also test a complex variant with 3 flags after --lsmio-no-autotune
        f_req_complex = RunRequest(
            f_target="lsmio",
            f_scale="baseline",
            f_ssd=False,
            f_setup="NATIVE",
            f_variant="prealloc-wbuf-512m",
        )
        f_spec_complex = self.m_adapter.createLaunchSpec(
            f_request=f_req_complex,
            f_combination=self.m_combo_8m,
            f_point=self.m_point,
        )
        f_bound_complex = self.m_adapter.bindRank(
            f_spec=f_spec_complex,
            f_identity=f_id,
            f_layout=self.m_layout,
        )
        self.assertTrue(
            f_bound_complex.output_path.endswith(
                "lsmio-rank-0-native-prealloc-wbuf-512m.db"
            )
        )
        for f_flag in (
            "--lsmio-wbuffer",
            "536870912",
            "--lsmio-prealloc",
        ):
            self.assertIn(f_flag, f_bound_complex.argv)

        # Test PLUGIN setup ordering: --lsmio-plugin immediately followed by variant flags
        f_req_plugin = RunRequest(
            f_target="lsmio",
            f_scale="baseline",
            f_ssd=False,
            f_setup="PLUGIN",
            f_variant="no-footer",
        )
        f_spec_plugin = self.m_adapter.createLaunchSpec(
            f_request=f_req_plugin,
            f_combination=self.m_combo_8m,
            f_point=self.m_point,
        )
        f_bound_plugin = self.m_adapter.bindRank(
            f_spec=f_spec_plugin,
            f_identity=f_id,
            f_layout=self.m_layout,
        )
        self.assertTrue(
            f_bound_plugin.output_path.endswith("lsmio-rank-0-plugin-no-footer.db")
        )
        idx_plugin = f_bound_plugin.argv.index("--lsmio-plugin")
        idx_no_autotune = f_bound_plugin.argv.index("--lsmio-no-autotune")
        idx_footer_plugin = f_bound_plugin.argv.index("--lsmio-no-footer-index")
        self.assertEqual(idx_no_autotune, idx_plugin + 1)
        self.assertEqual(idx_footer_plugin, idx_plugin + 2)

    def testBindRankFlushVariantExactFlag(self) -> None:
        """Tasks 3.2.3: Verify flush variant injects exact --lsmio-always-flush flag (INV-ARCH-4)."""
        f_req = RunRequest(
            f_target="lsmio",
            f_scale="baseline",
            f_ssd=False,
            f_setup="NATIVE",
            f_variant="flush",
        )
        f_spec = self.m_adapter.createLaunchSpec(
            f_request=f_req,
            f_combination=self.m_combo_8m,
            f_point=self.m_point,
        )
        f_id = RankIdentity(f_global_rank=0, f_node_rank="node01", f_local_rank=0)
        f_bound = self.m_adapter.bindRank(
            f_spec=f_spec,
            f_identity=f_id,
            f_layout=self.m_layout,
        )
        # Critical assertion: --lsmio-always-flush, not --lsmo-
        self.assertIn("--lsmio-always-flush", f_bound.argv)
        self.assertNotIn("--lsmo-always-flush", f_bound.argv)
        self.assertTrue(f_bound.output_path.endswith("lsmio-rank-0-native-flush.db"))

    def testBuildCommandWithVariant(self) -> None:
        """Tasks 3.2.4: Verify buildCommand injects variant flags and generates infix DB name."""
        # 1. Default output path with variant
        f_cmd = self.m_adapter.buildCommand(
            f_executable="bm_native",
            f_setup="NATIVE",
            f_block_size="8M",
            f_variant="mmap-btree",
        )
        self.assertIn("--lsmio-mmap", f_cmd.argv)
        self.assertIn("--lsmio-no-pread", f_cmd.argv)
        self.assertIn("--lsmio-memtable", f_cmd.argv)
        self.assertIn("btree", f_cmd.argv)
        self.assertEqual(
            f_cmd.output_path, "/tmp/lsmio-rank-0-native-mmap-btree.db"
        )
        self.assertIn("/tmp/lsmio-rank-0-native-mmap-btree.db", f_cmd.argv)

        # 2. Flush variant with exact flag
        f_cmd_flush = self.m_adapter.buildCommand(
            f_executable="bm_native",
            f_setup="NATIVE",
            f_block_size="8M",
            f_variant="flush",
        )
        self.assertIn("--lsmio-always-flush", f_cmd_flush.argv)
        self.assertNotIn("--lsmo-always-flush", f_cmd_flush.argv)
        self.assertEqual(f_cmd_flush.output_path, "/tmp/lsmio-rank-0-native-flush.db")

        # 3. Explicit output path preserves custom path while injecting variant flags
        f_cmd_custom = self.m_adapter.buildCommand(
            f_executable="bm_native",
            f_setup="NATIVE",
            f_block_size="8M",
            f_output_path="/custom/dir/my-output.db",
            f_variant="wbuf-512m",
        )
        self.assertIn("--lsmio-wbuffer", f_cmd_custom.argv)
        self.assertIn("536870912", f_cmd_custom.argv)
        self.assertEqual(f_cmd_custom.output_path, "/custom/dir/my-output.db")
        self.assertIn("/custom/dir/my-output.db", f_cmd_custom.argv)

    def testBaseVariantHasOnlyNoAutotuneFlag(self) -> None:
        """Tasks 3.2.5: Verify default, base, and omitted variants add only --lsmio-no-autotune, matching bmtool."""
        f_id = RankIdentity(f_global_rank=0, f_node_rank="node01", f_local_rank=0)

        for f_variant_input in (None, "base", "default", ""):
            # Test via createLaunchSpec and bindRank
            f_spec = LsmioLaunchSpec(
                f_request=None,
                f_combination=self.m_combo_8m,
                f_point=self.m_point,
                f_setup="NATIVE",
                f_executable="bm_native",
                f_variant=f_variant_input if f_variant_input else None,
            )
            f_bound = self.m_adapter.bindRank(
                f_spec=f_spec,
                f_identity=f_id,
                f_layout=self.m_layout,
            )
            self.assertTrue(
                f_bound.output_path.endswith("lsmio-rank-0-native.db"),
                f"Expected clean DB path for variant={f_variant_input!r}, got: {f_bound.output_path}",
            )
            self.assertEqual(
                f_bound.argv,
                (
                    "bm_native",
                    "-m",
                    "-g",
                    "--lsmio-no-autotune",
                    "-i",
                    "10",
                    "-o",
                    f_bound.output_path,
                    "--lsmio-ts",
                    "8388608",
                    "--lsmio-bs",
                    "8388608",
                    "--key-count",
                    "1024",
                ),
            )

            # Test via buildCommand
            f_cmd = self.m_adapter.buildCommand(
                f_executable="bm_native",
                f_setup="NATIVE",
                f_block_size="8M",
                f_variant=f_variant_input,
            )
            self.assertEqual(f_cmd.output_path, "/tmp/lsmio-rank-0-native.db")
            self.assertEqual(
                f_cmd.argv,
                (
                    "bm_native",
                    "-m",
                    "-g",
                    "--lsmio-no-autotune",
                    "-i",
                    "10",
                    "-o",
                    "/tmp/lsmio-rank-0-native.db",
                    "--lsmio-ts",
                    "8388608",
                    "--lsmio-bs",
                    "8388608",
                    "--key-count",
                    "1024",
                ),
            )


if __name__ == "__main__":
    unittest.main()
