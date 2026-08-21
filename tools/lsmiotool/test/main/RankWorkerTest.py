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
        f_rank_dir = os.path.join(self.m_real_temp, "ranks", "0")

        # 1. First claim succeeds
        f_lock_path = RankClaimStore.claim(f_rank_dir, 0)
        self.assertTrue(os.path.exists(f_lock_path))
        self.assertTrue(RankClaimStore.isClaimed(f_rank_dir))

        f_claim_data = RankClaimStore.getClaim(f_rank_dir)
        self.assertIsNotNone(f_claim_data)
        self.assertEqual(f_claim_data["global_rank"], 0)
        self.assertEqual(f_claim_data["pid"], os.getpid())

        # 2. Second claim fails with RankClaimError
        with self.assertRaises(RankClaimError) as f_ctx:
            RankClaimStore.claim(f_rank_dir, 0)
        self.assertIn("already been claimed", str(f_ctx.exception))

        # 3. Multithreaded concurrent race test: 10 threads trying to claim rank 1 simultaneously
        f_race_rank_dir = os.path.join(self.m_real_temp, "ranks", "1")
        f_success_count = 0
        f_error_count = 0

        def try_claim() -> bool:
            try:
                RankClaimStore.claim(f_race_rank_dir, 1)
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
        f_rank_dir = os.path.join(f_layout.runRoot, "points", "00-tasks-1", "ranks", "0")
        self.assertTrue(RankClaimStore.isClaimed(f_rank_dir))

        # 3. Check rank result was recorded
        f_result_path = os.path.join(
            f_rank_dir, "c16_b8M", "result.json"
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

        # 4. Check log file was written
        f_log_path = f_data["payload"]["log_path"]
        self.assertTrue(os.path.exists(f_log_path))
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
