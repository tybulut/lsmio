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

from concurrent.futures import ThreadPoolExecutor
import json
import os
import shutil
import socket
import tempfile
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple
import unittest
from unittest.mock import MagicMock, patch

from lsmiotool.lib.artifacts import ArtifactLayout, ArtifactStore, STANDARD_COMBINATION_TUPLES
from lsmiotool.lib.benchmarks import LsmioAdapter
from lsmiotool.lib.evidence import EvidenceKind, EvidenceRecord, EvidenceStore, WriterKind
from lsmiotool.lib.profile import ProfileLoader
from lsmiotool.lib.run import (
    Combination,
    ManifestDocument,
    ManifestSerializer,
    RankIdentity,
    RunPlan,
    RunPlanner,
    RunRequest,
    ScalePoint,
)
from lsmiotool.lib.site import EnvironmentResolver, SchedulerKind, SiteProfile
from lsmiotool.lib.worker import (
    ProcessResult,
    ProcessRunner,
    RankClaimError,
    RankClaimStore,
    RankIdentityError,
    RankIdentityResolver,
    RankWorker,
    RankWorkerError,
)


class MockProcessRunner:
    """Mock process runner recording executed commands and providing configurable results."""

    def __init__(
        self,
        f_default_returncode: int = 0,
        f_stdout: str = "",
        f_stderr: str = "",
        f_side_effect: Optional[Callable[[Sequence[str], Dict[str, Any]], ProcessResult]] = None,
    ) -> None:
        self.m_default_returncode = f_default_returncode
        self.m_stdout = f_stdout
        self.m_stderr = f_stderr
        self.m_side_effect = f_side_effect
        self.m_invocations: List[Tuple[List[str], Dict[str, Any]]] = []

    def run(
        self,
        f_argv: Sequence[str],
        **f_kwargs: Any,
    ) -> ProcessResult:
        f_argv_list = list(f_argv)
        self.m_invocations.append((f_argv_list, dict(f_kwargs)))

        if self.m_side_effect is not None:
            return self.m_side_effect(f_argv_list, f_kwargs)

        # Mirror output to log file if requested
        f_log_path = f_kwargs.get("f_log_path") or f_kwargs.get("log_path") or f_kwargs.get("log")
        if f_log_path:
            os.makedirs(os.path.dirname(f_log_path), exist_ok=True)
            with open(f_log_path, "a", encoding="utf-8") as f_f:
                f_f.write(self.m_stdout or "mock process output\n")

        return ProcessResult(
            f_returncode=self.m_default_returncode,
            f_stdout=self.m_stdout,
            f_stderr=self.m_stderr,
            f_elapsed_seconds=0.02,
        )


class RankWorkerTest(unittest.TestCase):
    """Comprehensive test suite for exclusive rank claims and launched LSMIO rank workers."""

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.TemporaryDirectory()
        self.m_real_temp = os.path.realpath(self.m_temp_dir.name)
        self.m_etc_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "etc", "environments.json")
        )
        self.m_profile_doc = ProfileLoader.load(self.m_etc_path)
        self.m_dev_profile = EnvironmentResolver.resolveProfile(
            "DEV", f_user="testuser", f_home=self.m_real_temp
        )
        self.m_viking_profile = EnvironmentResolver.resolveProfile(
            "VIKING", f_user="testuser", f_home=self.m_real_temp
        )
        self.m_isambard_profile = EnvironmentResolver.resolveProfile(
            "ISAMBARD", f_user="testuser", f_home=self.m_real_temp
        )
        self.m_benchmark_root = self.m_dev_profile.getBenchmarkRoot("hdd")
        os.makedirs(self.m_benchmark_root, exist_ok=True)
        self.m_run_counter = 0

    def tearDown(self) -> None:
        self.m_temp_dir.cleanup()

    def _createManifest(
        self,
        f_target: str = "lsmio",
        f_scale: str = "local",
        f_setup: Optional[str] = None,
        f_ssd: bool = False,
        f_run_id: Optional[str] = None,
        f_profile: Optional[SiteProfile] = None,
    ) -> Tuple[ManifestDocument, str, ArtifactLayout]:
        """Helper to create a valid RunPlan, write manifest.json to disk, and return layout."""
        self.m_run_counter += 1
        f_eff_run_id = f_run_id if f_run_id is not None else f"test-run-rank-{self.m_run_counter:04d}"
        f_prof = f_profile or self.m_dev_profile
        f_req = RunRequest(
            f_target=f_target,
            f_scale=f_scale,
            f_ssd=f_ssd,
            f_setup=f_setup,
        )

        f_tokens = [f"lm-{f_i:024x}" for f_i in range(len(RunPlanner.SCALE_MATRICES[f_scale]))]
        f_tok_idx = 0

        def token_gen() -> str:
            nonlocal f_tok_idx
            f_tok = f_tokens[f_tok_idx]
            f_tok_idx += 1
            return f_tok

        f_plan = RunPlanner.createPlan(
            f_request=f_req,
            f_profile=f_prof,
            f_run_id_source=lambda: f_eff_run_id,
            f_clock=lambda: "2026-08-20T12:00:00Z",
            f_token_source=token_gen,
        )

        f_layout = ArtifactLayout(f_prof.getBenchmarkRoot("ssd" if f_ssd else "hdd"), f_eff_run_id)
        f_store = ArtifactStore(f_layout)
        f_store.allocateRun(f_plan)

        f_manifest_path = f_layout.manifestPath
        with open(f_manifest_path, "rb") as f_f:
            f_doc = ManifestSerializer.deserialize(f_f.read())

        return f_doc, f_manifest_path, f_layout

    def testSlurmLateIdentity(self) -> None:
        """Validate Slurm environment identity resolution from SLURM_PROCID, SLURM_NODEID, SLURM_LOCALID."""
        # 1. Full Slurm environment
        f_env_full = {
            "SLURM_PROCID": "3",
            "SLURM_NODEID": "1",
            "SLURM_LOCALID": "0",
        }
        f_id1 = RankIdentityResolver.resolve(
            f_scheduler_kind=SchedulerKind.SLURM,
            f_env=f_env_full,
            f_tasks=4,
            f_ppn=1,
        )
        self.assertEqual(f_id1.global_rank, 3)
        self.assertEqual(f_id1.node_rank, "1")
        self.assertEqual(f_id1.local_rank, 0)

        # 2. Slurm with SLURMD_NODENAME fallback when SLURM_NODEID is absent
        f_env_nodename = {
            "SLURM_PROCID": "0",
            "SLURMD_NODENAME": "viking-node-042",
        }
        f_id2 = RankIdentityResolver.resolve(
            f_scheduler_kind="slurm",
            f_env=f_env_nodename,
            f_tasks=8,
            f_ppn=1,
        )
        self.assertEqual(f_id2.global_rank, 0)
        self.assertEqual(f_id2.node_rank, "viking-node-042")
        self.assertIsNone(f_id2.local_rank)

        # 3. Slurm passed as SiteProfile object
        f_id3 = RankIdentityResolver.resolve(
            f_scheduler_kind=self.m_viking_profile,
            f_env={"SLURM_PROCID": "2", "SLURM_NODEID": "2", "SLURM_LOCALID": "1"},
            f_tasks=4,
            f_ppn=2,
        )
        self.assertEqual(f_id3.global_rank, 2)
        self.assertEqual(f_id3.node_rank, "2")
        self.assertEqual(f_id3.local_rank, 1)

    def testPbsHostnameGlobalAndNoneLocal(self) -> None:
        """Validate PBS environment resolution from ALPS_APP_PE, HOSTNAME, and local_rank=None."""
        # 1. Standard PBS environment
        f_env_pbs = {
            "ALPS_APP_PE": "5",
            "HOSTNAME": "nid00128",
        }
        f_id1 = RankIdentityResolver.resolve(
            f_scheduler_kind=SchedulerKind.PBS,
            f_env=f_env_pbs,
            f_tasks=8,
            f_ppn=1,
        )
        self.assertEqual(f_id1.global_rank, 5)
        self.assertEqual(f_id1.node_rank, "nid00128")
        self.assertIsNone(f_id1.local_rank)

        # 2. PBS fallback hostname via socket.gethostname() when HOSTNAME is missing
        f_env_pe_only = {
            "ALPS_APP_PE": "0",
        }
        f_id2 = RankIdentityResolver.resolve(
            f_scheduler_kind="pbs",
            f_env=f_env_pe_only,
            f_tasks=2,
            f_ppn=1,
        )
        self.assertEqual(f_id2.global_rank, 0)
        self.assertTrue(len(f_id2.node_rank) > 0)
        self.assertIsNone(f_id2.local_rank)

        # 3. PBS with PBS_VNODENUM fallback
        f_env_vnodenum = {
            "PBS_VNODENUM": "1",
            "HOSTNAME": "isambard-node-01",
        }
        f_id3 = RankIdentityResolver.resolve(
            f_scheduler_kind=self.m_isambard_profile,
            f_env=f_env_vnodenum,
            f_tasks=4,
            f_ppn=1,
        )
        self.assertEqual(f_id3.global_rank, 1)
        self.assertEqual(f_id3.node_rank, "isambard-node-01")
        self.assertIsNone(f_id3.local_rank)

    def testOptionalCertifiedPbsLocalField(self) -> None:
        """Test PBS rank resolution when certified local rank configuration is supplied."""
        # When explicit certified variable is passed
        f_env = {
            "ALPS_APP_PE": "2",
            "HOSTNAME": "nid00042",
            "PBS_LOCALID": "1",
        }
        f_id = RankIdentityResolver.resolve(
            f_scheduler_kind=SchedulerKind.PBS,
            f_env=f_env,
            f_tasks=4,
            f_ppn=2,
            f_certified_local_var="PBS_LOCALID",
        )
        self.assertEqual(f_id.global_rank, 2)
        self.assertEqual(f_id.local_rank, 1)

        # When certified variable is non-integer, raises RankIdentityError
        f_bad_env = {
            "ALPS_APP_PE": "2",
            "HOSTNAME": "nid00042",
            "PBS_LOCALID": "not_an_int",
        }
        with self.assertRaises(RankIdentityError):
            RankIdentityResolver.resolve(
                f_scheduler_kind=SchedulerKind.PBS,
                f_env=f_bad_env,
                f_tasks=4,
                f_certified_local_var="PBS_LOCALID",
            )

        # When certified variable is negative, raises RankIdentityError
        f_neg_env = {
            "ALPS_APP_PE": "2",
            "HOSTNAME": "nid00042",
            "PBS_LOCALID": "-1",
        }
        with self.assertRaises(RankIdentityError):
            RankIdentityResolver.resolve(
                f_scheduler_kind=SchedulerKind.PBS,
                f_env=f_neg_env,
                f_tasks=4,
                f_certified_local_var="PBS_LOCALID",
            )

    def testDirectFakeEnvironmentResolution(self) -> None:
        """Validate direct and fake environment identity resolution."""
        # 1. LSMIO_RANK / LSMIO_NODE / LSMIO_LOCAL_RANK
        f_env = {
            "LSMIO_RANK": "1",
            "LSMIO_NODE": "host0",
            "LSMIO_LOCAL_RANK": "1",
        }
        f_id = RankIdentityResolver.resolve(
            f_scheduler_kind=SchedulerKind.FAKE,
            f_env=f_env,
            f_tasks=2,
        )
        self.assertEqual(f_id.global_rank, 1)
        self.assertEqual(f_id.node_rank, "host0")
        self.assertEqual(f_id.local_rank, 1)

        # 2. Generic RANK / NODEID
        f_id2 = RankIdentityResolver.resolve(
            f_scheduler_kind="direct",
            f_env={"RANK": "0", "NODEID": "dev-01"},
            f_tasks=1,
        )
        self.assertEqual(f_id2.global_rank, 0)
        self.assertEqual(f_id2.node_rank, "dev-01")
        self.assertIsNone(f_id2.local_rank)

    def testDuplicateClaimRaceOneWinner(self) -> None:
        """Test concurrent rank claim race condition where exactly one caller wins and subsequent callers receive RankClaimError."""
        f_rank_dir = os.path.join(self.m_real_temp, "ranks", "0", "c16_b8M")

        # 1. First claim succeeds
        f_lock_path = RankClaimStore.claim(f_rank_dir, 0, f_combination="c16_b8M")
        self.assertTrue(os.path.exists(f_lock_path))
        self.assertTrue(RankClaimStore.isClaimed(f_rank_dir))

        f_claim_data = RankClaimStore.getClaim(f_rank_dir)
        self.assertIsNotNone(f_claim_data)
        self.assertEqual(f_claim_data["global_rank"], 0)
        self.assertEqual(f_claim_data["combination"], "c16_b8M")
        self.assertEqual(f_claim_data["pid"], os.getpid())

        # 2. Second claim for same rank and same combination fails with RankClaimError
        with self.assertRaises(RankClaimError) as f_ctx:
            RankClaimStore.claim(f_rank_dir, 0, f_combination="c16_b8M")
        self.assertIn("already been claimed", str(f_ctx.exception))

        # 3. Same rank in DIFFERENT combination succeeds!
        f_diff_combo_dir = os.path.join(self.m_real_temp, "ranks", "0", "c16_b1M")
        f_diff_lock_path = RankClaimStore.claim(f_diff_combo_dir, 0, f_combination="c16_b1M")
        self.assertTrue(os.path.exists(f_diff_lock_path))
        self.assertTrue(RankClaimStore.isClaimed(f_diff_combo_dir))

        # 4. Multithreaded concurrent race test: 10 threads trying to claim rank 1 in c16_b8M simultaneously
        f_race_rank_dir = os.path.join(self.m_real_temp, "ranks", "1", "c16_b8M")
        f_success_count = 0
        f_error_count = 0

        def try_claim() -> bool:
            try:
                RankClaimStore.claim(f_race_rank_dir, 1, f_combination="c16_b8M")
                return True
            except RankClaimError:
                return False

        with ThreadPoolExecutor(max_workers=8) as f_executor:
            f_futures = [f_executor.submit(try_claim) for _ in range(10)]
            for f_fut in f_futures:
                if f_fut.result():
                    f_success_count += 1
                else:
                    f_error_count += 1

        self.assertEqual(f_success_count, 1)
        self.assertEqual(f_error_count, 9)

    def testSameRankAcrossAllSixCombinations(self) -> None:
        """F-04a: Prove rank 0 executes sequentially across all six combinations without claim collisions."""
        _, f_manifest_path, f_layout = self._createManifest(
            f_target="lsmio", f_scale="local", f_setup="NATIVE-M"
        )
        f_mock_runner = MockProcessRunner(
            f_default_returncode=0,
            f_stdout="LSMIO combination executed successfully\n",
        )
        f_env = {
            "LSMIO_RANK": "0",
            "LSMIO_NODE": "node0",
        }

        f_claim_paths: List[str] = []
        f_result_paths: List[str] = []
        f_log_paths: List[str] = []
        f_output_paths: List[str] = []

        # Execute RankWorker sequentially across all 6 standard combinations
        for f_stripe, f_block in STANDARD_COMBINATION_TUPLES:
            f_combo_name = f"c{f_stripe}_b{f_block}"
            f_exit = RankWorker.run(
                f_manifest_path=f_manifest_path,
                f_point_id="00-tasks-1",
                f_combination_desc=f_combo_name,
                f_env=f_env,
                f_runner=f_mock_runner,
                f_layout=f_layout,
            )
            self.assertEqual(
                f_exit, 0, f"RankWorker failed on combination '{f_combo_name}' with exit {f_exit}"
            )

            # Record paths for validation
            f_claim_path = f_layout.pointRankClaimPath("00-tasks-1", 0, f_combo_name)
            f_result_path = f_layout.pointRankResultPath("00-tasks-1", 0, f_combo_name)
            f_log_path = f_layout.pointRankLogPath("00-tasks-1", 0, f_combo_name)
            f_out_path = os.path.join(
                f_layout.pointDataSubdir("00-tasks-1", f_stripe, f_block),
                "lsmio-rank-0-native-m.db",
            )

            f_claim_paths.append(f_claim_path)
            f_result_paths.append(f_result_path)
            f_log_paths.append(f_log_path)
            f_output_paths.append(f_out_path)

            # Check individual combination claim lock
            self.assertTrue(os.path.exists(f_claim_path))
            with open(f_claim_path, "r", encoding="utf-8") as f_f:
                f_claim_meta = json.load(f_f)
            self.assertEqual(f_claim_meta["global_rank"], 0)
            self.assertEqual(f_claim_meta["combination"], f_combo_name)
            self.assertEqual(f_claim_meta["point_id"], "00-tasks-1")
            self.assertEqual(f_claim_meta["run_id"], f_layout.runId)
            self.assertEqual(f_claim_meta["pid"], os.getpid())
            self.assertTrue(len(f_claim_meta["claimed_at_utc"]) > 0)

            # Check individual combination result record
            self.assertTrue(os.path.exists(f_result_path))
            with open(f_result_path, "r", encoding="utf-8") as f_f:
                f_res_data = json.load(f_f)
            self.assertEqual(f_res_data["payload"]["status"], "success")
            self.assertEqual(f_res_data["payload"]["exit_code"], 0)
            self.assertEqual(f_res_data["payload"]["global_rank"], 0)
            self.assertEqual(f_res_data["payload"]["log_path"], f_log_path)
            self.assertEqual(f_res_data["payload"]["result_path"], f_result_path)

            # Check log file existence
            self.assertTrue(os.path.exists(f_log_path))

        # Assert all 6 claims, results, logs, and outputs are strictly unique
        self.assertEqual(len(set(f_claim_paths)), 6)
        self.assertEqual(len(set(f_result_paths)), 6)
        self.assertEqual(len(set(f_log_paths)), 6)
        self.assertEqual(len(set(f_output_paths)), 6)

        # Assert all 6 claims persist permanently
        for f_cp in f_claim_paths:
            self.assertTrue(os.path.exists(f_cp), f"Claim lock {f_cp} was unexpectedly removed")

    def testDuplicateSameRankCombinationRaceOneWinner(self) -> None:
        """F-04a: Prove duplicate rank worker for identical rank and combination has exactly one winner."""
        _, f_manifest_path, f_layout = self._createManifest(
            f_target="lsmio", f_scale="local", f_setup="NATIVE-M"
        )
        f_mock_runner = MockProcessRunner(f_default_returncode=0)
        f_env = {"LSMIO_RANK": "0", "LSMIO_NODE": "node0"}

        # First run succeeds
        f_exit1 = RankWorker.run(
            f_manifest_path=f_manifest_path,
            f_point_id="00-tasks-1",
            f_combination_desc="c16_b8M",
            f_env=f_env,
            f_runner=f_mock_runner,
            f_layout=f_layout,
        )
        self.assertEqual(f_exit1, 0)

        # Second run for same rank 0 and same combination c16_b8M fails closed with RankWorkerError / RankClaimError
        with self.assertRaises(RankWorkerError) as f_ctx:
            RankWorker.run(
                f_manifest_path=f_manifest_path,
                f_point_id="00-tasks-1",
                f_combination_desc="c16_b8M",
                f_env=f_env,
                f_runner=f_mock_runner,
                f_layout=f_layout,
            )
        self.assertTrue(
            "already been claimed" in str(f_ctx.exception)
            or "already exists" in str(f_ctx.exception)
        )

    def testCombinationValidatedBeforeClaim(self) -> None:
        """F-04a: Prove combination descriptor is strictly validated against planned matrix before any claim lock is created."""
        _, f_manifest_path, f_layout = self._createManifest(
            f_target="lsmio", f_scale="local", f_setup="NATIVE-M"
        )
        f_mock_runner = MockProcessRunner(f_default_returncode=0)
        f_env = {"LSMIO_RANK": "0", "LSMIO_NODE": "node0"}

        # 1. Invalid combination string
        with self.assertRaises(RankWorkerError):
            RankWorker.run(
                f_manifest_path=f_manifest_path,
                f_point_id="00-tasks-1",
                f_combination_desc="c99_b99M",
                f_env=f_env,
                f_runner=f_mock_runner,
                f_layout=f_layout,
            )
        # Verify no claim lock was created for c99_b99M
        f_bad_dir = os.path.join(f_layout.runRoot, "points", "00-tasks-1", "ranks", "0", "c99_b99M")
        self.assertFalse(os.path.exists(f_bad_dir))

        # 2. Unplanned foreign combination
        with self.assertRaises(RankWorkerError):
            RankWorker.run(
                f_manifest_path=f_manifest_path,
                f_point_id="00-tasks-1",
                f_combination_desc="c32_b16M",
                f_env=f_env,
                f_runner=f_mock_runner,
                f_layout=f_layout,
            )
        f_foreign_dir = os.path.join(f_layout.runRoot, "points", "00-tasks-1", "ranks", "0", "c32_b16M")
        self.assertFalse(os.path.exists(f_foreign_dir))

        # 3. Malformed descriptor
        with self.assertRaises(RankWorkerError):
            RankWorker.run(
                f_manifest_path=f_manifest_path,
                f_point_id="00-tasks-1",
                f_combination_desc="invalid-descriptor",
                f_env=f_env,
                f_runner=f_mock_runner,
                f_layout=f_layout,
            )

    def testClaimLogOutputResultAllCombinationPrivate(self) -> None:
        """F-04a: Prove all claim locks, logs, outputs, and results are combination-private and rank-private."""
        _, f_manifest_path, f_layout = self._createManifest(
            f_target="lsmio", f_scale="bake", f_setup="NATIVE-M"
        )
        f_adapter = LsmioAdapter()
        f_point = ScalePoint(f_tasks=4, f_ppn=1, f_nodes=4)

        f_combos = [
            Combination(16, "8M", 16, 8388608, 1024, 128),
            Combination(4, "1M", 4, 1048576, 4096, 128),
        ]

        f_all_claims = set()
        f_all_results = set()
        f_all_logs = set()
        f_all_outputs = set()

        for f_c in f_combos:
            f_spec = f_adapter.createLaunchSpec(
                f_request=RunRequest("lsmio", "bake", f_setup="NATIVE-M"),
                f_combination=f_c,
                f_point=f_point,
                f_executable="bm_native",
            )
            for f_rank in range(f_point.tasks):
                f_id = RankIdentity(f_global_rank=f_rank, f_node_rank=f"node-{f_rank}")
                f_bound = f_adapter.bindRank(f_spec, f_id, f_layout, f_ordinal=0)
                f_claim = f_layout.pointRankClaimPath(f_point, f_rank, f_c, f_ordinal=0)

                f_all_claims.add(f_claim)
                f_all_results.add(f_bound.result_path)
                f_all_logs.add(f_bound.stdout_path)
                f_all_outputs.add(f_bound.output_path)

                # Validate exact path format and containment
                self.assertTrue(f_claim.endswith(f"ranks/{f_rank}/{f_c.name}/claim.lock"))
                self.assertTrue(f_bound.result_path.endswith(f"ranks/{f_rank}/{f_c.name}/result.json"))
                self.assertTrue(f_bound.stdout_path.endswith(f"logs/{f_c.name}/rank_{f_rank}.log"))
                self.assertTrue(f_bound.output_path.endswith(f"data/c{f_c.stripe_count}/b{f_c.block_size}/lsmio-rank-{f_rank}-native-m.db"))

        # 4 ranks x 2 combinations = 8 distinct paths each
        self.assertEqual(len(f_all_claims), 8)
        self.assertEqual(len(f_all_results), 8)
        self.assertEqual(len(f_all_logs), 8)
        self.assertEqual(len(f_all_outputs), 8)

    def testClaimParentSymlinkRejection(self) -> None:
        """Prove claim lock creation rejects symbolic links in the claim path or parent directory."""
        f_outside_dir = tempfile.mkdtemp(prefix="outside-rank-claim-")
        try:
            f_symlink_dir = os.path.join(self.m_real_temp, "ranks", "symlink_rank")
            os.makedirs(os.path.dirname(f_symlink_dir), exist_ok=True)
            os.symlink(f_outside_dir, f_symlink_dir)

            with self.assertRaises(RankClaimError):
                RankClaimStore.claim(f_symlink_dir, 0, f_combination="c16_b8M")
        finally:
            shutil.rmtree(f_outside_dir, ignore_errors=True)

    def testRankIdentityMissingOrOutOfBoundsValidatedBeforeClaim(self) -> None:
        """Prove rank identity is validated before any claim lock is created."""
        _, f_manifest_path, f_layout = self._createManifest(
            f_target="lsmio", f_scale="local", f_setup="NATIVE-M"
        )
        f_mock_runner = MockProcessRunner(f_default_returncode=0)

        # Missing identity
        with self.assertRaises(RankWorkerError):
            RankWorker.run(
                f_manifest_path=f_manifest_path,
                f_point_id="00-tasks-1",
                f_combination_desc="c16_b8M",
                f_env={},  # empty env
                f_runner=f_mock_runner,
                f_layout=f_layout,
            )

        # Out-of-bounds rank (rank 10 for point with tasks 1)
        with self.assertRaises(RankWorkerError):
            RankWorker.run(
                f_manifest_path=f_manifest_path,
                f_point_id="00-tasks-1",
                f_combination_desc="c16_b8M",
                f_env={"LSMIO_RANK": "10"},
                f_runner=f_mock_runner,
                f_layout=f_layout,
            )

    def testNoClaimRelease(self) -> None:
        """Prove RankClaimStore exposes no release/unlock methods and claims are strictly permanent."""
        self.assertFalse(hasattr(RankClaimStore, "release"))
        self.assertFalse(hasattr(RankClaimStore, "unlock"))
        self.assertFalse(hasattr(RankClaimStore, "delete"))
        self.assertFalse(hasattr(RankClaimStore, "remove"))

    def testEveryGlobalUniquePaths(self) -> None:
        """Validate distinct non-colliding paths for every global rank 0..tasks-1."""
        _, _, f_layout = self._createManifest(f_target="lsmio", f_scale="bake")
        f_point = ScalePoint(f_tasks=4, f_ppn=1, f_nodes=4)
        f_adapter = LsmioAdapter()
        f_launch_spec = f_adapter.createLaunchSpec(
            f_request=RunRequest("lsmio", "bake", f_setup="NATIVE-M"),
            f_combination=Combination(16, "8M", 16, 8388608, 1024, 128),
            f_point=f_point,
            f_executable="bm_native",
        )

        f_output_paths = set()
        f_log_paths = set()
        f_result_paths = set()
        f_rank_dirs = set()

        for f_rank in range(f_point.tasks):
            f_id = RankIdentity(f_global_rank=f_rank, f_node_rank=f"node-{f_rank}")
            f_bound = f_adapter.bindRank(f_launch_spec, f_id, f_layout, f_ordinal=2)
            f_rank_dir = f_layout.pointRankDir(f_point, f_rank, f_ordinal=2)

            f_output_paths.add(f_bound.output_path)
            f_log_paths.add(f_bound.stdout_path)
            f_result_paths.add(f_bound.result_path)
            f_rank_dirs.add(f_rank_dir)

        # Assert all paths across all 4 ranks are strictly distinct
        self.assertEqual(len(f_output_paths), 4)
        self.assertEqual(len(f_log_paths), 4)
        self.assertEqual(len(f_result_paths), 4)
        self.assertEqual(len(f_rank_dirs), 4)

    def testIdentityFailures(self) -> None:
        """Test missing, non-numeric, negative, or out-of-bounds rank values."""
        # 1. Slurm missing SLURM_PROCID
        with self.assertRaises(RankIdentityError):
            RankIdentityResolver.resolve(SchedulerKind.SLURM, {}, f_tasks=4)

        # 2. Slurm non-integer SLURM_PROCID
        with self.assertRaises(RankIdentityError):
            RankIdentityResolver.resolve(
                SchedulerKind.SLURM, {"SLURM_PROCID": "invalid"}, f_tasks=4
            )

        # 3. Slurm negative SLURM_PROCID
        with self.assertRaises(RankIdentityError):
            RankIdentityResolver.resolve(
                SchedulerKind.SLURM, {"SLURM_PROCID": "-1"}, f_tasks=4
            )

        # 4. Slurm out-of-bounds SLURM_PROCID (equal to tasks)
        with self.assertRaises(RankIdentityError):
            RankIdentityResolver.resolve(
                SchedulerKind.SLURM, {"SLURM_PROCID": "4"}, f_tasks=4
            )

        # 5. Slurm out-of-bounds SLURM_PROCID (greater than tasks)
        with self.assertRaises(RankIdentityError):
            RankIdentityResolver.resolve(
                SchedulerKind.SLURM, {"SLURM_PROCID": "10"}, f_tasks=4
            )

        # 6. PBS missing ALPS_APP_PE
        with self.assertRaises(RankIdentityError):
            RankIdentityResolver.resolve(SchedulerKind.PBS, {}, f_tasks=4)

        # 7. PBS non-integer ALPS_APP_PE
        with self.assertRaises(RankIdentityError):
            RankIdentityResolver.resolve(
                SchedulerKind.PBS, {"ALPS_APP_PE": "foo"}, f_tasks=4
            )

        # 8. PBS negative ALPS_APP_PE
        with self.assertRaises(RankIdentityError):
            RankIdentityResolver.resolve(
                SchedulerKind.PBS, {"ALPS_APP_PE": "-3"}, f_tasks=4
            )

        # 9. PBS out-of-bounds ALPS_APP_PE
        with self.assertRaises(RankIdentityError):
            RankIdentityResolver.resolve(
                SchedulerKind.PBS, {"ALPS_APP_PE": "8"}, f_tasks=8
            )

        # 10. Direct/Fake missing rank variables
        with self.assertRaises(RankIdentityError):
            RankIdentityResolver.resolve(SchedulerKind.FAKE, {}, f_tasks=4)

        # 11. Invalid task count (zero or negative)
        with self.assertRaises(RankIdentityError):
            RankIdentityResolver.resolve(
                SchedulerKind.SLURM, {"SLURM_PROCID": "0"}, f_tasks=0
            )
        with self.assertRaises(RankIdentityError):
            RankIdentityResolver.resolve(
                SchedulerKind.SLURM, {"SLURM_PROCID": "0"}, f_tasks=-5
            )

    def testChildLogResultOrderAndStatus(self) -> None:
        """Test child process execution, output log capture, and rank result record creation."""
        _, f_manifest_path, f_layout = self._createManifest(
            f_target="lsmio", f_scale="local", f_setup="NATIVE-M"
        )
        f_mock_runner = MockProcessRunner(
            f_default_returncode=0,
            f_stdout="LSMIO benchmark completed successfully\nTotal iterations: 10\n",
        )

        f_env = {
            "LSMIO_RANK": "0",
            "LSMIO_NODE": "testnode0",
        }

        # 1. Execute RankWorker
        f_exit = RankWorker.run(
            f_manifest_path=f_manifest_path,
            f_point_id="00-tasks-1",
            f_combination_desc="c16_b8M",
            f_env=f_env,
            f_runner=f_mock_runner,
            f_layout=f_layout,
        )
        self.assertEqual(f_exit, 0)

        # 2. Check claim lock exists
        f_rank_combo_dir = os.path.join(f_layout.runRoot, "points", "00-tasks-1", "ranks", "0", "c16_b8M")
        self.assertTrue(RankClaimStore.isClaimed(f_rank_combo_dir))
        self.assertTrue(os.path.exists(os.path.join(f_rank_combo_dir, "claim.lock")))

        # 3. Check rank result was recorded
        f_result_path = os.path.join(
            f_rank_combo_dir, "result.json"
        )
        self.assertTrue(os.path.exists(f_result_path))

        with open(f_result_path, "r", encoding="utf-8") as f_f:
            f_data = json.load(f_f)

        self.assertEqual(f_data["writer_kind"], "rank")
        self.assertEqual(f_data["writer_id"], "0")
        self.assertEqual(f_data["evidence_kind"], "rank_result")
        self.assertEqual(f_data["payload"]["status"], "success")
        self.assertEqual(f_data["payload"]["exit_code"], 0)
        self.assertEqual(f_data["payload"]["global_rank"], 0)

        # 4. Check log file was written under combination logs dir
        f_log_path = f_data["payload"]["log_path"]
        self.assertTrue(os.path.exists(f_log_path))
        self.assertTrue(f_log_path.endswith("logs/c16_b8M/rank_0.log"))
        with open(f_log_path, "r", encoding="utf-8") as f_f:
            f_log_content = f_f.read()
        self.assertIn("LSMIO benchmark completed successfully", f_log_content)

        # 5. Overwrite rejection: executing again must raise RankClaimError / RankWorkerError
        with self.assertRaises(RankWorkerError) as f_ctx:
            RankWorker.run(
                f_manifest_path=f_manifest_path,
                f_point_id="00-tasks-1",
                f_combination_desc="c16_b8M",
                f_env=f_env,
                f_runner=f_mock_runner,
                f_layout=f_layout,
            )
        self.assertTrue(
            "already exists" in str(f_ctx.exception)
            or "already been claimed" in str(f_ctx.exception)
        )

        # 6. Explicit result file collision when claim is bypassed
        f_mock_claimer = MagicMock()
        with self.assertRaises(RankWorkerError) as f_ctx2:
            RankWorker.run(
                f_manifest_path=f_manifest_path,
                f_point_id="00-tasks-1",
                f_combination_desc="c16_b8M",
                f_env=f_env,
                f_runner=f_mock_runner,
                f_layout=f_layout,
                f_claim_store=f_mock_claimer,
            )
        self.assertIn("already exists", str(f_ctx2.exception))

    def testSharedRejected(self) -> None:
        """Assert RankWorker rejects shared benchmarks (ior, lmp) with RankWorkerError."""
        # 1. IOR manifest
        _, f_ior_manifest, _ = self._createManifest(f_target="ior", f_scale="local")
        with self.assertRaises(RankWorkerError) as f_ctx:
            RankWorker.run(
                f_manifest_path=f_ior_manifest,
                f_point_id="00-tasks-1",
                f_combination_desc="c16_b8M",
                f_env={"LSMIO_RANK": "0"},
            )
        self.assertIn("only supports 'lsmio'", str(f_ctx.exception))

        # 2. LMP manifest
        _, f_lmp_manifest, _ = self._createManifest(f_target="lmp", f_scale="local")
        with self.assertRaises(RankWorkerError) as f_ctx2:
            RankWorker.run(
                f_manifest_path=f_lmp_manifest,
                f_point_id="00-tasks-1",
                f_combination_desc="c16_b8M",
                f_env={"LSMIO_RANK": "0"},
            )
        self.assertIn("only supports 'lsmio'", str(f_ctx2.exception))

    def testOneRankFailurePropagation(self) -> None:
        """Test non-zero returncode and signal propagation from child process to rank result."""
        # 1. Child process exits with returncode 42
        _, f_manifest_path, f_layout = self._createManifest(
            f_target="lsmio", f_scale="local", f_setup="ROCKSDB", f_run_id="test-run-fail-42"
        )
        f_mock_runner = MockProcessRunner(
            f_default_returncode=42,
            f_stderr="RocksDB corruption error\n",
        )

        f_exit = RankWorker.run(
            f_manifest_path=f_manifest_path,
            f_point_id="00-tasks-1",
            f_combination_desc="c16_b1M",
            f_env={"LSMIO_RANK": "0", "LSMIO_NODE": "node0"},
            f_runner=f_mock_runner,
            f_layout=f_layout,
        )
        self.assertEqual(f_exit, 42)

        # Verify evidence record reflects failure
        f_store = EvidenceStore(f_layout)
        f_rec = f_store.readRankResult(ScalePoint(1, 1, 1), 0, "c16_b1M", f_ordinal=0)
        self.assertIsNotNone(f_rec)
        self.assertEqual(f_rec.payload["status"], "failed")
        self.assertEqual(f_rec.payload["exit_code"], 42)
        self.assertIn("RocksDB corruption error", f_rec.payload["error"])

        # 2. Child process killed by signal (e.g. SIGKILL -9)
        _, f_sig_manifest, f_sig_layout = self._createManifest(
            f_target="lsmio", f_scale="local", f_setup="ADIOS", f_run_id="test-run-sig-9"
        )
        f_sig_runner = MockProcessRunner(
            f_default_returncode=-9,
            f_stderr="Killed\n",
        )

        f_sig_exit = RankWorker.run(
            f_manifest_path=f_sig_manifest,
            f_point_id="00-tasks-1",
            f_combination_desc="c4_b64K",
            f_env={"LSMIO_RANK": "0", "LSMIO_NODE": "node0"},
            f_runner=f_sig_runner,
            f_layout=f_sig_layout,
        )
        self.assertEqual(f_sig_exit, -9)

        f_sig_store = EvidenceStore(f_sig_layout)
        f_sig_rec = f_sig_store.readRankResult(ScalePoint(1, 1, 1), 0, "c4_b64K", f_ordinal=0)
        self.assertIsNotNone(f_sig_rec)
        self.assertEqual(f_sig_rec.payload["status"], "failed")
        self.assertEqual(f_sig_rec.payload["exit_code"], -9)
        self.assertEqual(f_sig_rec.payload["signal_number"], 9)

    def testRankWorkerInstanceExecution(self) -> None:
        """Test instantiation and execute() method of RankWorker."""
        _, f_manifest_path, f_layout = self._createManifest(
            f_target="lsmio", f_scale="local", f_setup="PLUGIN-M", f_run_id="test-run-inst"
        )
        f_mock_runner = MockProcessRunner(f_default_returncode=0)

        f_worker = RankWorker(
            f_runner=f_mock_runner,
            f_layout=f_layout,
        )

        f_status = f_worker.execute(
            f_manifest_path=f_manifest_path,
            f_point_id="00-tasks-1",
            f_combination_desc="c4_b8M",
            f_env={"LSMIO_RANK": "0", "LSMIO_NODE": "instnode"},
        )
        self.assertEqual(f_status, 0)


if __name__ == "__main__":
    unittest.main()
