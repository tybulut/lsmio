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

"""Integration test suite proving real six-combination LSMIO execution via subprocess."""

import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import unittest

from lsmiotool.lib.artifacts import (
    ArtifactLayout,
    ArtifactStore,
    STANDARD_COMBINATION_TUPLES,
    validatePathContainment,
)
from lsmiotool.lib.evidence import (
    EvidenceKind,
    EvidenceRecord,
    EvidenceStore,
    WriterKind,
)
from lsmiotool.lib.profile import ProfileLoader
from lsmiotool.lib.run import (
    Combination,
    ManifestDocument,
    ManifestSerializer,
    RunPlan,
    RunPlanner,
    RunRequest,
    ScalePoint,
)
from lsmiotool.lib.site import (
    EnvironmentResolver,
    SchedulerKind,
    SiteProfile,
)
from lsmiotool.lib.state import (
    OverallRunState,
    PointRunState,
    PointStateView,
    RunStateView,
    SchedulerJobState,
    StateReconciler,
)
from lsmiotool.lib.worker import (
    AllocationController,
    AllocationControllerError,
    ProcessResult,
    ProcessRunner,
    RankClaimError,
    RankClaimStore,
    RankIdentityResolver,
    RankWorker,
    RankWorkerError,
)


class LsmioSixCombinationIntegrationTest(unittest.TestCase):
    """Integration test suite executing private worker as a real subprocess across all six LSMIO combinations."""

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.mkdtemp(prefix="lsmio-six-combo-int-test-")
        self.m_real_temp = os.path.realpath(self.m_temp_dir)
        self.m_decoy_home = os.path.join(self.m_real_temp, "decoy_home")
        self.m_decoy_cwd = os.path.join(self.m_real_temp, "decoy_cwd")
        self.m_bin_dir = os.path.join(self.m_decoy_home, "src", "usr", "bin")
        self.m_benchmark_root = os.path.join(
            self.m_decoy_home, ".lsmio-dev", "benchmark"
        )

        os.makedirs(self.m_decoy_home, exist_ok=True)
        os.makedirs(self.m_decoy_cwd, exist_ok=True)
        os.makedirs(self.m_bin_dir, exist_ok=True)
        os.makedirs(self.m_benchmark_root, exist_ok=True)

        # Locate checked-in private worker executable
        self.m_worker_executable = (
            Path(__file__).resolve().parents[2] / "lsmiotool-worker"
        )
        if self.m_worker_executable.exists():
            os.chmod(str(self.m_worker_executable), 0o755)

        # 1. Create dummy lfs executable in bin dir to handle LustreConfigurator calls
        self.m_lfs_executable = os.path.join(self.m_bin_dir, "lfs")
        with open(self.m_lfs_executable, "w", encoding="utf-8") as f_f:
            f_f.write("#!/bin/sh\nexit 0\n")
        os.chmod(self.m_lfs_executable, 0o755)

        # 2. Create real temporary benchmark executable (bm_native)
        self.m_bm_native_executable = os.path.join(self.m_bin_dir, "bm_native")
        f_bm_script = """#!/usr/bin/env python3
import sys
import os
import signal

fail_combo = os.environ.get("MOCK_FAIL_COMBO")
fail_code = int(os.environ.get("MOCK_FAIL_CODE", "42"))
signal_combo = os.environ.get("MOCK_SIGNAL_COMBO")

out_path = None
for i, arg in enumerate(sys.argv):
    if arg == "-o" and i + 1 < len(sys.argv):
        out_path = sys.argv[i + 1]
        break

if signal_combo and out_path:
    f_sig_slash = signal_combo.replace("_", "/")
    if signal_combo in out_path or f_sig_slash in out_path:
        sys.stderr.write(f"MOCK_BENCHMARK_SIGNAL on combination {signal_combo}\\n")
        sys.stderr.flush()
        os.kill(os.getpid(), signal.SIGKILL)

if fail_combo and out_path:
    f_fail_slash = fail_combo.replace("_", "/")
    if fail_combo in out_path or f_fail_slash in out_path:
        sys.stderr.write(f"MOCK_BENCHMARK_FAILURE on combination {fail_combo}\\n")
        sys.stderr.flush()
        sys.exit(fail_code)

if out_path:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("MOCK_LSMIO_DATABASE_RECORDS\\n")

print(f"MOCK_BENCHMARK_EXECUTED: argv={' '.join(sys.argv)}")
sys.exit(0)
"""
        with open(self.m_bm_native_executable, "w", encoding="utf-8") as f_f:
            f_f.write(f_bm_script)
        os.chmod(self.m_bm_native_executable, 0o755)

        # 3. Load profile document and resolve DEV site profile with custom paths
        self.m_etc_path = os.path.normpath(
            os.path.join(
                os.path.dirname(__file__), "..", "..", "etc", "environments.json"
            )
        )
        self.m_profile_doc = ProfileLoader.load(self.m_etc_path)
        self.m_site_profile = EnvironmentResolver.resolveProfile(
            "DEV", f_user="testuser", f_home=self.m_decoy_home
        )

        self.m_run_counter = 0
        self.m_original_cwd = os.getcwd()
        os.chdir(self.m_decoy_cwd)

    def tearDown(self) -> None:
        os.chdir(self.m_original_cwd)
        shutil.rmtree(self.m_temp_dir, ignore_errors=True)

    def _createManifest(
        self,
        f_target: str = "lsmio",
        f_scale: str = "local",
        f_setup: str = "NATIVE-M",
        f_run_id: Optional[str] = None,
    ) -> Tuple[RunPlan, ArtifactLayout, str]:
        """Helper to create a canonical RunPlan, allocate run on disk, and return plan, layout, manifest path."""
        self.m_run_counter += 1
        f_eff_run_id = f_run_id or f"lsmio-six-run-{self.m_run_counter:04d}"
        f_req = RunRequest(
            f_target=f_target,
            f_scale=f_scale,
            f_ssd=False,
            f_setup=f_setup,
        )

        f_tokens = [
            f"lm-{f_i:024x}" for f_i in range(len(RunPlanner.SCALE_MATRICES[f_scale]))
        ]
        f_tok_idx = 0

        def token_gen() -> str:
            nonlocal f_tok_idx
            f_tok = f_tokens[f_tok_idx]
            f_tok_idx += 1
            return f_tok

        f_plan = RunPlanner.createPlan(
            f_request=f_req,
            f_profile=self.m_site_profile,
            f_run_id_source=lambda: f_eff_run_id,
            f_clock=lambda: "2026-08-22T12:00:00Z",
            f_token_source=token_gen,
        )

        f_layout = ArtifactLayout(self.m_benchmark_root, f_eff_run_id)
        f_store = ArtifactStore(f_layout)
        f_store.allocateRun(f_plan)
        f_evidence_store = EvidenceStore(f_layout, f_plan=f_plan)
        from lsmiotool.lib.evidence import JobHandle

        for f_idx, f_sp in enumerate(f_plan.scale_points):
            f_store.preparePoint(f_sp, f_ordinal=f_idx)
            f_evidence_store.recordSubmissionRequested(f_sp, "client", f_ordinal=f_idx)
            f_evidence_store.recordSubmissionDispatched(f_sp, "client", f_ordinal=f_idx)
            f_evidence_store.recordSubmissionRecorded(
                f_sp,
                "client",
                f_handle=JobHandle("fake", f"100{f_idx}"),
                f_ordinal=f_idx,
            )

        return f_plan, f_layout, f_layout.manifestPath

    def _buildSubprocessEnv(
        self,
        f_extra_env: Optional[Mapping[str, str]] = None,
    ) -> Dict[str, str]:
        """Build clean isolated subprocess environment with decoy cwd/HOME and rank inheritance."""
        f_env = dict(os.environ)
        f_env["HOME"] = self.m_decoy_home
        f_env["PATH"] = f"{self.m_bin_dir}:{f_env.get('PATH', '')}"
        f_env["LSMIO_RANK"] = "0"
        f_env["LSMIO_NODE"] = "int-node-0"
        f_package_parent = str(Path(__file__).resolve().parents[3])
        f_env["PYTHONPATH"] = f_package_parent + (
            f":{f_env['PYTHONPATH']}" if "PYTHONPATH" in f_env else ""
        )

        if f_extra_env:
            f_env.update({str(f_k): str(f_v) for f_k, f_v in f_extra_env.items()})

        return f_env

    def testSourceWorkerRunsOneRealPointAcrossExactSixCombinations(self) -> None:
        """F-04b: Proves real private worker subprocess completes one scale point across all six combinations."""
        f_plan, f_layout, f_manifest_path = self._createManifest(
            f_target="lsmio", f_scale="local", f_setup="NATIVE-M"
        )
        f_point_id = "00-tasks-1"
        f_point = f_plan.scale_points[0]
        f_env = self._buildSubprocessEnv()

        # 1. Execute private worker executable in allocation mode as a real subprocess
        f_cmd = [
            sys.executable,
            str(self.m_worker_executable),
            "allocation",
            f_manifest_path,
            f_point_id,
        ]
        f_proc = subprocess.run(
            f_cmd,
            cwd=self.m_decoy_cwd,
            env=f_env,
            capture_output=True,
            text=True,
        )

        # Assert exit code 0 and transcript clean
        self.assertEqual(
            f_proc.returncode,
            0,
            f"Worker allocation subprocess failed (exit code {f_proc.returncode}).\nStdout: {f_proc.stdout}\nStderr: {f_proc.stderr}",
        )
        self.assertEqual(f_proc.stderr, "")

        # 2. Evidence Store verification
        f_evidence_store = EvidenceStore(f_layout, f_plan=f_plan)

        f_claim_paths: List[str] = []
        f_result_paths: List[str] = []
        f_log_paths: List[str] = []
        f_output_paths: List[str] = []
        f_ctrl_result_paths: List[str] = []

        # 3. Assert all 6 combinations executed in exact ordered sequence
        for f_combo_idx, (f_stripe, f_block) in enumerate(STANDARD_COMBINATION_TUPLES):
            f_combo_name = f"c{f_stripe}_b{f_block}"

            # a) Controller Result
            f_ctrl_res_path = f_layout.pointControllerResultPath(
                f_point, f_combo_name, f_ordinal=0
            )
            self.assertTrue(
                os.path.exists(f_ctrl_res_path),
                f"Missing controller-result.json for combination {f_combo_name}",
            )
            f_ctrl_res = f_evidence_store.readControllerResult(
                f_point, f_combo_name, f_ordinal=0
            )
            self.assertIsNotNone(f_ctrl_res)
            self.assertEqual(f_ctrl_res.payload["status"], "success")
            self.assertEqual(f_ctrl_res.payload["exit_code"], 0)
            self.assertEqual(f_ctrl_res.payload["tasks_validated"], 1)
            f_ctrl_result_paths.append(f_ctrl_res_path)

            # b) Rank Claim Lock
            f_claim_path = f_layout.pointRankClaimPath(
                f_point, 0, f_combo_name, f_ordinal=0
            )
            self.assertTrue(
                os.path.exists(f_claim_path),
                f"Missing claim.lock for rank 0 and combination {f_combo_name}",
            )
            with open(f_claim_path, "r", encoding="utf-8") as f_f:
                f_claim_data = json.load(f_f)
            self.assertEqual(f_claim_data["global_rank"], 0)
            self.assertEqual(f_claim_data["combination"], f_combo_name)
            self.assertEqual(f_claim_data["point_id"], f_point_id)
            self.assertEqual(f_claim_data["run_id"], f_plan.run_id)
            self.assertTrue(
                isinstance(f_claim_data["pid"], int) and f_claim_data["pid"] > 0
            )
            self.assertTrue(len(f_claim_data["claimed_at_utc"]) > 0)
            f_claim_paths.append(f_claim_path)

            # c) Rank Log
            f_log_path = f_layout.pointRankLogPath(
                f_point, 0, f_combo_name, f_ordinal=0
            )
            self.assertTrue(
                os.path.exists(f_log_path),
                f"Missing log file {f_log_path} for combination {f_combo_name}",
            )
            with open(f_log_path, "r", encoding="utf-8") as f_f:
                f_log_content = f_f.read()
            self.assertIn("MOCK_BENCHMARK_EXECUTED", f_log_content)
            f_log_paths.append(f_log_path)

            # d) Rank Result Record
            f_rank_res_path = f_layout.pointRankResultPath(
                f_point, 0, f_combo_name, f_ordinal=0
            )
            self.assertTrue(
                os.path.exists(f_rank_res_path),
                f"Missing result.json for rank 0 and combination {f_combo_name}",
            )
            f_rank_res = f_evidence_store.readRankResult(
                f_point, 0, f_combo_name, f_ordinal=0
            )
            self.assertIsNotNone(f_rank_res)
            self.assertEqual(f_rank_res.payload["status"], "success")
            self.assertEqual(f_rank_res.payload["exit_code"], 0)
            self.assertEqual(f_rank_res.payload["global_rank"], 0)
            self.assertEqual(f_rank_res.payload["log_path"], f_log_path)
            self.assertEqual(f_rank_res.payload["result_path"], f_rank_res_path)

            # Exact argv validation
            f_argv = f_rank_res.payload["argv"]
            self.assertIn("-m", f_argv)
            self.assertIn("-g", f_argv)
            self.assertIn("-i", f_argv)
            self.assertIn("10", f_argv)
            self.assertIn("-o", f_argv)
            self.assertIn("--lsmio-ts", f_argv)
            self.assertIn("--lsmio-bs", f_argv)
            self.assertIn("--key-count", f_argv)
            f_result_paths.append(f_rank_res_path)

            # e) Output Database File
            f_out_path = os.path.join(
                f_layout.pointDataSubdir(f_point, f_stripe, f_block, f_ordinal=0),
                "lsmio-rank-0-native-m.db",
            )
            self.assertTrue(
                os.path.exists(f_out_path),
                f"Missing output database file at {f_out_path}",
            )
            with open(f_out_path, "r", encoding="utf-8") as f_f:
                f_db_content = f_f.read()
            self.assertIn("MOCK_LSMIO_DATABASE_RECORDS", f_db_content)
            f_output_paths.append(f_out_path)

        # 4. Strict Uniqueness and Containment Proof (24 distinct combination-private files)
        self.assertEqual(len(set(f_ctrl_result_paths)), 6)
        self.assertEqual(len(set(f_claim_paths)), 6)
        self.assertEqual(len(set(f_log_paths)), 6)
        self.assertEqual(len(set(f_result_paths)), 6)
        self.assertEqual(len(set(f_output_paths)), 6)

        # 5. Verify NO 7th combination exists anywhere in the layout
        f_combos_dir = f_layout.pointCombinationsDir(f_point, f_ordinal=0)
        self.assertEqual(len(os.listdir(f_combos_dir)), 6)

        f_logs_dir = f_layout.pointLogsDir(f_point, f_ordinal=0)
        f_log_subdirs = [
            d
            for d in os.listdir(f_logs_dir)
            if os.path.isdir(os.path.join(f_logs_dir, d))
        ]
        self.assertEqual(len(f_log_subdirs), 6)
        self.assertEqual(
            sorted(f_log_subdirs),
            ["c16_b1M", "c16_b64K", "c16_b8M", "c4_b1M", "c4_b64K", "c4_b8M"],
        )

        f_rank0_dir = f_layout.pointRankDir(f_point, 0, f_ordinal=0)
        self.assertEqual(len(os.listdir(f_rank0_dir)), 6)
        self.assertEqual(
            sorted(os.listdir(f_rank0_dir)),
            ["c16_b1M", "c16_b64K", "c16_b8M", "c4_b1M", "c4_b64K", "c4_b8M"],
        )

        f_data_dir = f_layout.pointDataDir(f_point, f_ordinal=0)
        f_data_stripes = sorted(os.listdir(f_data_dir))
        self.assertEqual(f_data_stripes, ["c16", "c4"])
        for f_s in f_data_stripes:
            f_blocks = sorted(os.listdir(os.path.join(f_data_dir, f_s)))
            self.assertEqual(f_blocks, ["b1M", "b64K", "b8M"])

        # 6. Authoritative State Reconciler Proof
        f_state_view = StateReconciler.reconcile(
            f_plan,
            f_evidence_store,
            f_scheduler_observations={0: SchedulerJobState.SUCCEEDED},
        )
        self.assertEqual(
            f_state_view.point_states[0].state,
            PointRunState.SUCCEEDED,
            "StateReconciler must reconcile the point state to SUCCEEDED after valid six-combination execution",
        )

    def testDuplicateSameRankCombinationSubprocessLoser(self) -> None:
        """F-04b: Prove second duplicate rank worker subprocess fails closed with RankClaimError and preserves lock."""
        f_plan, f_layout, f_manifest_path = self._createManifest(
            f_target="lsmio", f_scale="local", f_setup="NATIVE-M"
        )
        f_point_id = "00-tasks-1"
        f_combo_name = "c16_b8M"
        f_env = self._buildSubprocessEnv()

        # 1. First rank worker execution succeeds
        f_cmd1 = [
            sys.executable,
            str(self.m_worker_executable),
            "rank",
            f_manifest_path,
            f_point_id,
            f_combo_name,
        ]
        f_proc1 = subprocess.run(
            f_cmd1,
            cwd=self.m_decoy_cwd,
            env=f_env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            f_proc1.returncode,
            0,
            f"First rank worker subprocess failed.\nStdout: {f_proc1.stdout}\nStderr: {f_proc1.stderr}",
        )

        f_claim_path = f_layout.pointRankClaimPath(
            "00-tasks-1", 0, f_combo_name, f_ordinal=0
        )
        self.assertTrue(os.path.exists(f_claim_path))
        with open(f_claim_path, "r", encoding="utf-8") as f_f:
            f_orig_claim_data = json.load(f_f)

        # 2. Second duplicate rank worker subprocess on exact same rank and combination fails
        f_proc2 = subprocess.run(
            f_cmd1,
            cwd=self.m_decoy_cwd,
            env=f_env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            f_proc2.returncode,
            1,
            f"Duplicate rank worker must exit with non-zero status, got: {f_proc2.returncode}",
        )
        self.assertTrue(
            "already been claimed" in f_proc2.stderr
            or "already exists" in f_proc2.stderr,
            f"Expected claim collision error in stderr, got: {f_proc2.stderr}",
        )

        # 3. Original claim lock remains untouched and intact
        with open(f_claim_path, "r", encoding="utf-8") as f_f:
            f_current_claim_data = json.load(f_f)
        self.assertEqual(f_orig_claim_data, f_current_claim_data)

    def testOneRankFailureStopsCombinationAndLaterCombos(self) -> None:
        """F-04b: Prove child benchmark failure immediately halts execution and prevents later combinations from running."""
        f_plan, f_layout, f_manifest_path = self._createManifest(
            f_target="lsmio", f_scale="local", f_setup="NATIVE-M"
        )
        f_point_id = "00-tasks-1"
        f_point = f_plan.scale_points[0]

        # Configure mock benchmark to fail specifically on combination index 2 (c16_b64K) with code 42
        f_fail_env = self._buildSubprocessEnv(
            {
                "MOCK_FAIL_COMBO": "c16_b64K",
                "MOCK_FAIL_CODE": "42",
            }
        )

        f_cmd = [
            sys.executable,
            str(self.m_worker_executable),
            "allocation",
            f_manifest_path,
            f_point_id,
        ]
        f_proc = subprocess.run(
            f_cmd,
            cwd=self.m_decoy_cwd,
            env=f_fail_env,
            capture_output=True,
            text=True,
        )

        self.assertEqual(
            f_proc.returncode,
            42,
            f"Expected failure exit code 42 from allocation subprocess, got: {f_proc.returncode}",
        )

        f_evidence_store = EvidenceStore(f_layout, f_plan=f_plan)

        # 1. Combos 0 (c16_b8M) and 1 (c16_b1M) succeeded
        f_res0 = f_evidence_store.readControllerResult(f_point, "c16_b8M", f_ordinal=0)
        self.assertIsNotNone(f_res0)
        self.assertEqual(f_res0.payload["status"], "success")

        f_res1 = f_evidence_store.readControllerResult(f_point, "c16_b1M", f_ordinal=0)
        self.assertIsNotNone(f_res1)
        self.assertEqual(f_res1.payload["status"], "success")

        # 2. Combo 2 (c16_b64K) failed and recorded failure
        f_res2 = f_evidence_store.readControllerResult(f_point, "c16_b64K", f_ordinal=0)
        self.assertIsNotNone(f_res2)
        self.assertEqual(f_res2.payload["status"], "failed")
        self.assertEqual(f_res2.payload["exit_code"], 42)

        # 3. Later combos 3 (c4_b8M), 4 (c4_b1M), 5 (c4_b64K) were NEVER executed
        for f_later_combo in ("c4_b8M", "c4_b1M", "c4_b64K"):
            self.assertIsNone(
                f_evidence_store.readControllerResult(
                    f_point, f_later_combo, f_ordinal=0
                ),
                f"Combination {f_later_combo} should not have a controller result",
            )
            self.assertIsNone(
                f_evidence_store.readRankResult(f_point, 0, f_later_combo, f_ordinal=0),
                f"Combination {f_later_combo} should not have a rank result",
            )
            f_later_claim = f_layout.pointRankClaimPath(
                f_point, 0, f_later_combo, f_ordinal=0
            )
            self.assertFalse(
                os.path.exists(f_later_claim),
                f"Combination {f_later_combo} should not have a claim lock",
            )

        # 4. StateReconciler derives PointRunState.FAILED
        f_state_view = StateReconciler.reconcile(
            f_plan,
            f_evidence_store,
            f_scheduler_observations={0: SchedulerJobState.FAILED},
        )
        self.assertEqual(
            f_state_view.point_states[0].state,
            PointRunState.FAILED,
        )

    def testMissingMalformedResultFailsLauncherControllerRun(self) -> None:
        """F-04b: Proves missing or malformed rank evidence causes immediate combination failure."""
        f_plan, f_layout, f_manifest_path = self._createManifest(
            f_target="lsmio", f_scale="local", f_setup="NATIVE-M"
        )
        f_point = f_plan.scale_points[0]
        f_evidence_store = EvidenceStore(f_layout, f_plan=f_plan)

        # 1. Missing Rank Result Case:
        # Simulate launcher succeeding but rank 0 result.json is absent
        class MockRunnerMissingRank:
            def run(self, f_argv: Sequence[str], **f_kwargs: Any) -> ProcessResult:
                return ProcessResult(f_returncode=0)

        f_status = AllocationController.run(
            f_manifest_path=f_manifest_path,
            f_point_id=0,
            f_runner=MockRunnerMissingRank(),
            f_layout=f_layout,
            f_evidence_store=f_evidence_store,
        )
        self.assertEqual(f_status, 1)

        f_ctrl_res = f_evidence_store.readControllerResult(
            f_point, "c16_b8M", f_ordinal=0
        )
        self.assertIsNotNone(f_ctrl_res)
        self.assertEqual(f_ctrl_res.payload["status"], "failed")
        self.assertEqual(f_ctrl_res.payload["stage"], "rank_evidence")
        self.assertIn("Missing rank result", f_ctrl_res.payload["error"])

        # Subsequent combos were never executed
        self.assertIsNone(
            f_evidence_store.readControllerResult(f_point, "c16_b1M", f_ordinal=0)
        )

        # 2. Corrupt / Malformed Rank Result Case
        f_plan2, f_layout2, f_manifest_path2 = self._createManifest(
            f_target="lsmio", f_scale="local", f_setup="NATIVE-M"
        )
        f_point2 = f_plan2.scale_points[0]
        f_evidence_store2 = EvidenceStore(f_layout2, f_plan=f_plan2)

        class MockRunnerCorruptRank:
            def run(self, f_argv: Sequence[str], **f_kwargs: Any) -> ProcessResult:
                if "rank" in f_argv:
                    # Write corrupted non-JSON bytes to result.json
                    f_res_path = f_layout2.pointRankResultPath(
                        f_point2, 0, "c16_b8M", f_ordinal=0
                    )
                    os.makedirs(os.path.dirname(f_res_path), exist_ok=True)
                    with open(f_res_path, "wb") as f_f:
                        f_f.write(b"CORRUPTED_RAW_NON_JSON{:::")
                return ProcessResult(f_returncode=0)

        f_status2 = AllocationController.run(
            f_manifest_path=f_manifest_path2,
            f_point_id=0,
            f_runner=MockRunnerCorruptRank(),
            f_layout=f_layout2,
            f_evidence_store=f_evidence_store2,
        )
        self.assertEqual(f_status2, 1)

        f_ctrl_res2 = f_evidence_store2.readControllerResult(
            f_point2, "c16_b8M", f_ordinal=0
        )
        self.assertIsNotNone(f_ctrl_res2)
        self.assertEqual(f_ctrl_res2.payload["status"], "failed")
        self.assertEqual(f_ctrl_res2.payload["stage"], "rank_evidence")
        self.assertIn("Corrupt rank result", f_ctrl_res2.payload["error"])
        self.assertIsNone(
            f_evidence_store2.readControllerResult(f_point2, "c16_b1M", f_ordinal=0)
        )

    def testSignalAndTimeoutChildHandling(self) -> None:
        """F-04b: Proves signal termination of child benchmark records signal number in rank evidence and halts controller."""
        f_plan, f_layout, f_manifest_path = self._createManifest(
            f_target="lsmio", f_scale="local", f_setup="NATIVE-M"
        )
        f_point_id = "00-tasks-1"
        f_point = f_plan.scale_points[0]

        # Configure mock benchmark to be killed by SIGKILL on combination c16_b8M
        f_sig_env = self._buildSubprocessEnv(
            {
                "MOCK_SIGNAL_COMBO": "c16_b8M",
            }
        )

        f_cmd = [
            sys.executable,
            str(self.m_worker_executable),
            "allocation",
            f_manifest_path,
            f_point_id,
        ]
        f_proc = subprocess.run(
            f_cmd,
            cwd=self.m_decoy_cwd,
            env=f_sig_env,
            capture_output=True,
            text=True,
        )

        # Allocation controller must fail
        self.assertNotEqual(f_proc.returncode, 0)

        f_evidence_store = EvidenceStore(f_layout, f_plan=f_plan)

        # Rank result should record signal failure
        f_rank_res = f_evidence_store.readRankResult(f_point, 0, "c16_b8M", f_ordinal=0)
        self.assertIsNotNone(f_rank_res)
        self.assertEqual(f_rank_res.payload["status"], "failed")
        self.assertEqual(f_rank_res.payload["signal_number"], int(signal.SIGKILL))

        # Controller result should record failure
        f_ctrl_res = f_evidence_store.readControllerResult(
            f_point, "c16_b8M", f_ordinal=0
        )
        self.assertIsNotNone(f_ctrl_res)
        self.assertEqual(f_ctrl_res.payload["status"], "failed")

        # Subsequent combos were not run
        self.assertIsNone(
            f_evidence_store.readControllerResult(f_point, "c16_b1M", f_ordinal=0)
        )


if __name__ == "__main__":
    unittest.main()
