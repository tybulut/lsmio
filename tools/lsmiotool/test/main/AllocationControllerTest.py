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

import json
import os
import tempfile
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple
import unittest
from unittest.mock import MagicMock, patch

from lsmiotool.lib.artifacts import (
    ArtifactLayout,
    ArtifactStore,
    STANDARD_COMBINATION_TUPLES,
)
from lsmiotool.lib.benchmarks import LmpAdapter
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
from lsmiotool.lib.site import EnvironmentResolver, SiteProfile
from lsmiotool.lib.worker import (
    AllocationController,
    AllocationControllerError,
    ModuleSetup,
    ProcessResult,
    ProcessRunner,
)


class MockProcessRunner:
    """Mock process runner recording executed commands and providing configurable results."""

    def __init__(
        self,
        f_default_returncode: int = 0,
        f_side_effect: Optional[
            Callable[[Sequence[str], Dict[str, Any]], ProcessResult]
        ] = None,
    ) -> None:
        self.m_default_returncode = f_default_returncode
        self.m_side_effect = f_side_effect
        self.m_invocations: List[Tuple[List[str], Dict[str, Any]]] = []

    def run(
        self,
        f_argv: Sequence[str],
        **f_kwargs: Any,
    ) -> ProcessResult:
        f_argv_list = list(f_argv)
        self.m_invocations.append((f_argv_list, dict(f_kwargs)))

        f_log = f_kwargs.get("f_log_path") or f_kwargs.get("log_path")
        if f_log and self.m_default_returncode == 0:
            os.makedirs(os.path.dirname(os.path.abspath(f_log)), exist_ok=True)
            if not os.path.exists(f_log):
                with open(f_log, "w", encoding="utf-8") as f_f:
                    f_f.write("mock log output\n")

        if self.m_side_effect is not None:
            return self.m_side_effect(f_argv_list, f_kwargs)

        return ProcessResult(
            f_returncode=self.m_default_returncode,
            f_stdout="",
            f_stderr="",
            f_elapsed_seconds=0.01,
        )


class AllocationControllerTest(unittest.TestCase):
    """Unit test suite for AllocationController verifying matrix order, failure stops, and invariants."""

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.TemporaryDirectory()
        self.m_real_temp = os.path.realpath(self.m_temp_dir.name)
        self.m_etc_path = os.path.normpath(
            os.path.join(
                os.path.dirname(__file__), "..", "..", "etc", "environments.json"
            )
        )
        self.m_profile_doc = ProfileLoader.load(self.m_etc_path)
        self.m_dev_profile = EnvironmentResolver.resolveProfile(
            "DEV", f_user="testuser", f_home=self.m_real_temp
        )
        self.m_benchmark_root = self.m_dev_profile.getBenchmarkRoot("hdd")
        os.makedirs(self.m_benchmark_root, exist_ok=True)

        # Create sample LMP assets in a dedicated directory
        self.m_lmp_assets_dir = os.path.join(self.m_real_temp, "lmp_assets")
        os.makedirs(self.m_lmp_assets_dir, exist_ok=True)
        for f_asset in ("in.reaxc.hns", "data.hns-equil", "ffield.reax.hns"):
            with open(
                os.path.join(self.m_lmp_assets_dir, f_asset), "w", encoding="utf-8"
            ) as f_f:
                f_f.write(f"# mock content for {f_asset}\n")

    def tearDown(self) -> None:
        self.m_temp_dir.cleanup()

    def _createManifest(
        self,
        f_target: str = "ior",
        f_scale: str = "local",
        f_setup: Optional[str] = None,
        f_ssd: bool = False,
        f_run_id: str = "test-run-001",
    ) -> Tuple[ManifestDocument, str, ArtifactLayout]:
        """Helper to create a valid RunPlan, write manifest.json to disk, and return layout."""
        f_req = RunRequest(
            f_target=f_target,
            f_scale=f_scale,
            f_ssd=f_ssd,
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
            f_profile=self.m_dev_profile,
            f_run_id_source=lambda: f_run_id,
            f_clock=lambda: "2026-08-20T12:00:00Z",
            f_token_source=token_gen,
        )

        f_layout = ArtifactLayout(self.m_benchmark_root, f_run_id)
        f_store = ArtifactStore(f_layout)
        f_store.allocateRun(f_plan)

        f_manifest_path = f_layout.manifestPath
        with open(f_manifest_path, "rb") as f_f:
            f_doc = ManifestSerializer.deserialize(f_f.read())

        return f_doc, f_manifest_path, f_layout

    def testExactOrder(self) -> None:
        """Validates strict execution order of all 6 combinations: (16,8M), (16,1M), (16,64K), (4,8M), (4,1M), (4,64K)."""
        f_doc, f_manifest_path, f_layout = self._createManifest(
            f_target="ior", f_scale="local"
        )
        f_point_id = "00-tasks-1"

        f_executed_stripes: List[Tuple[int, str]] = []

        def side_effect(
            f_argv: Sequence[str], f_kwargs: Dict[str, Any]
        ) -> ProcessResult:
            if len(f_argv) >= 2 and f_argv[0] == "lfs" and f_argv[1] == "setstripe":
                # Extract stripe parameters: -S <block> -c <stripe>
                f_s_idx = f_argv.index("-S")
                f_c_idx = f_argv.index("-c")
                f_block = f_argv[f_s_idx + 1]
                f_stripe = int(f_argv[f_c_idx + 1])
                f_executed_stripes.append((f_stripe, f_block))
            return ProcessResult(f_returncode=0, f_elapsed_seconds=0.01)

        f_runner = MockProcessRunner(f_side_effect=side_effect)

        f_status = AllocationController.run(
            f_manifest_path=f_manifest_path,
            f_point_id=f_point_id,
            f_runner=f_runner,
            f_layout=f_layout,
        )

        self.assertEqual(f_status, 0)
        self.assertEqual(tuple(f_executed_stripes), STANDARD_COMBINATION_TUPLES)

        # Assert all 6 controller results exist on disk with success status
        f_evidence_store = EvidenceStore(f_layout, f_plan=f_doc.toRunPlan())
        for f_sp in f_doc.scale_points:
            for f_stripe, f_block in STANDARD_COMBINATION_TUPLES:
                f_combo = f"c{f_stripe}_b{f_block}"
                f_res = f_evidence_store.readControllerResult(
                    f_sp, f_combo, f_ordinal=0
                )
                self.assertIsNotNone(f_res)
                self.assertEqual(f_res.payload["status"], "success")
                self.assertEqual(f_res.payload["exit_code"], 0)

    def testEveryStageAndPositionStops(self) -> None:
        """Tests failure at each stage (stripe, stage assets, launch, rank evidence) immediately stops execution."""
        # 1. Failure at Lustre stripe on combination index 2 (c16_b64K)
        f_doc, f_manifest_path, f_layout = self._createManifest(
            f_target="ior", f_scale="local", f_run_id="run-stripe-fail"
        )
        f_stripe_call_count = 0

        def stripe_fail_side_effect(
            f_argv: Sequence[str], f_kwargs: Dict[str, Any]
        ) -> ProcessResult:
            nonlocal f_stripe_call_count
            if len(f_argv) >= 2 and f_argv[0] == "lfs" and f_argv[1] == "setstripe":
                f_stripe_call_count += 1
                if f_stripe_call_count == 3:  # 3rd combination: c16_b64K
                    return ProcessResult(f_returncode=1, f_stderr="stripe config error")
            return ProcessResult(f_returncode=0)

        f_runner = MockProcessRunner(f_side_effect=stripe_fail_side_effect)
        f_status = AllocationController.run(
            f_manifest_path=f_manifest_path,
            f_point_id=0,
            f_runner=f_runner,
            f_layout=f_layout,
        )

        self.assertEqual(f_status, 1)
        self.assertEqual(f_stripe_call_count, 3)

        f_store = EvidenceStore(f_layout, f_plan=f_doc.toRunPlan())
        f_sp = f_doc.scale_points[0]
        # Combos 0 and 1 succeeded
        self.assertEqual(
            f_store.readControllerResult(f_sp, "c16_b8M", f_ordinal=0).payload[
                "status"
            ],
            "success",
        )
        self.assertEqual(
            f_store.readControllerResult(f_sp, "c16_b1M", f_ordinal=0).payload[
                "status"
            ],
            "success",
        )
        # Combo 2 recorded failure
        f_res_failed = f_store.readControllerResult(f_sp, "c16_b64K", f_ordinal=0)
        self.assertEqual(f_res_failed.payload["status"], "failed")
        self.assertEqual(f_res_failed.payload["stage"], "stripe")
        # Combos 3, 4, 5 were never attempted
        self.assertIsNone(f_store.readControllerResult(f_sp, "c4_b8M", f_ordinal=0))
        self.assertIsNone(f_store.readControllerResult(f_sp, "c4_b1M", f_ordinal=0))
        self.assertIsNone(f_store.readControllerResult(f_sp, "c4_b64K", f_ordinal=0))

        # 2. Failure at Shared Launch on combination index 1 (c16_b1M) with specific exit code 42
        f_doc2, f_manifest_path2, f_layout2 = self._createManifest(
            f_target="ior", f_scale="local", f_run_id="run-launch-fail"
        )
        f_launch_count = 0

        def launch_fail_side_effect(
            f_argv: Sequence[str], f_kwargs: Dict[str, Any]
        ) -> ProcessResult:
            nonlocal f_launch_count
            if len(f_argv) >= 1 and f_argv[0] == self.m_dev_profile.executables["ior"]:
                f_launch_count += 1
                if f_launch_count == 2:
                    return ProcessResult(
                        f_returncode=42, f_stderr="IOR benchmark crashed"
                    )
            return ProcessResult(f_returncode=0)

        f_runner2 = MockProcessRunner(f_side_effect=launch_fail_side_effect)
        f_status2 = AllocationController.run(
            f_manifest_path=f_manifest_path2,
            f_point_id=0,
            f_runner=f_runner2,
            f_layout=f_layout2,
        )

        self.assertEqual(f_status2, 42)
        self.assertEqual(f_launch_count, 2)
        f_store2 = EvidenceStore(f_layout2, f_plan=f_doc2.toRunPlan())
        self.assertEqual(
            f_store2.readControllerResult(f_sp, "c16_b8M", f_ordinal=0).payload[
                "status"
            ],
            "success",
        )
        f_fail_res2 = f_store2.readControllerResult(f_sp, "c16_b1M", f_ordinal=0)
        self.assertEqual(f_fail_res2.payload["status"], "failed")
        self.assertEqual(f_fail_res2.payload["exit_code"], 42)
        self.assertIsNone(f_store2.readControllerResult(f_sp, "c16_b64K", f_ordinal=0))

        # 3. Failure at LMP Asset Staging (corrupt/missing asset source)
        f_doc3, f_manifest_path3, f_layout3 = self._createManifest(
            f_target="lmp", f_scale="local", f_run_id="run-lmp-stage-fail"
        )
        f_empty_asset_dir = os.path.join(self.m_real_temp, "empty_assets")
        os.makedirs(f_empty_asset_dir, exist_ok=True)

        f_runner3 = MockProcessRunner()
        f_status3 = AllocationController.run(
            f_manifest_path=f_manifest_path3,
            f_point_id=0,
            f_runner=f_runner3,
            f_asset_source=f_empty_asset_dir,
            f_layout=f_layout3,
        )

        self.assertEqual(f_status3, 1)
        f_store3 = EvidenceStore(f_layout3, f_plan=f_doc3.toRunPlan())
        f_fail_res3 = f_store3.readControllerResult(f_sp, "c16_b8M", f_ordinal=0)
        self.assertEqual(f_fail_res3.payload["status"], "failed")
        self.assertEqual(f_fail_res3.payload["stage"], "stage_assets")

    def testSharedOneResult(self) -> None:
        """Tests IOR and LMP shared execution producing exactly 1 controller combination result per combination."""
        # 1. IOR shared run
        f_doc_ior, f_path_ior, f_layout_ior = self._createManifest(
            f_target="ior", f_scale="local", f_run_id="run-ior-shared"
        )
        f_runner = MockProcessRunner()
        f_status = AllocationController.run(
            f_manifest_path=f_path_ior,
            f_point_id="tasks-1",
            f_runner=f_runner,
            f_layout=f_layout_ior,
        )
        self.assertEqual(f_status, 0)

        # Assert exactly 6 controller-result.json files and zero rank result files
        f_store_ior = EvidenceStore(f_layout_ior, f_plan=f_doc_ior.toRunPlan())
        f_sp = f_doc_ior.scale_points[0]
        for f_stripe, f_block in STANDARD_COMBINATION_TUPLES:
            f_combo = f"c{f_stripe}_b{f_block}"
            f_res = f_store_ior.readControllerResult(f_sp, f_combo, f_ordinal=0)
            self.assertIsNotNone(f_res)
            # Ranks directory should have no result files
            self.assertIsNone(f_store_ior.readRankResult(f_sp, 0, f_combo, f_ordinal=0))

        # 2. LMP shared run
        f_doc_lmp, f_path_lmp, f_layout_lmp = self._createManifest(
            f_target="lmp", f_scale="local", f_run_id="run-lmp-shared"
        )
        f_status_lmp = AllocationController.run(
            f_manifest_path=f_path_lmp,
            f_point_id="00-tasks-1",
            f_runner=f_runner,
            f_asset_source=self.m_lmp_assets_dir,
            f_layout=f_layout_lmp,
        )
        self.assertEqual(f_status_lmp, 0)
        f_store_lmp = EvidenceStore(f_layout_lmp, f_plan=f_doc_lmp.toRunPlan())
        for f_stripe, f_block in STANDARD_COMBINATION_TUPLES:
            f_combo = f"c{f_stripe}_b{f_block}"
            f_res = f_store_lmp.readControllerResult(f_sp, f_combo, f_ordinal=0)
            self.assertIsNotNone(f_res)
            self.assertEqual(f_res.payload["status"], "success")

    def _recordMockRankResult(
        self,
        f_store: EvidenceStore,
        f_layout: ArtifactLayout,
        f_point: ScalePoint,
        f_rank_idx: int,
        f_combo: str,
        f_ordinal: int = 0,
        f_status: str = "success",
        f_exit_code: int = 0,
        f_error: Optional[str] = None,
    ) -> None:
        f_log = f_layout.pointRankLogPath(
            f_point, f_rank_idx, f_combo, f_ordinal=f_ordinal
        )
        f_res = os.path.join(
            f_layout.pointRankCombinationDir(f_point, f_rank_idx, f_combo, f_ordinal),
            f"rank_{f_rank_idx}.db",
        )
        os.makedirs(os.path.dirname(f_log), exist_ok=True)
        os.makedirs(os.path.dirname(f_res), exist_ok=True)
        if not os.path.exists(f_log):
            with open(f_log, "w", encoding="utf-8") as f_f:
                f_f.write("mock rank log\n")
        if not os.path.exists(f_res):
            with open(f_res, "w", encoding="utf-8") as f_f:
                f_f.write("mock rank db\n")
        f_payload: Dict[str, Any] = {
            "status": f_status,
            "exit_code": f_exit_code,
            "exit_status": f_exit_code,
            "global_rank": f_rank_idx,
            "rank": f_rank_idx,
            "combination": f_combo,
            "argv": ["lsmioworker", "rank", f_combo],
            "log_path": f_log,
            "result_path": f_res,
            "timed_out": False,
        }
        if f_error is not None:
            f_payload["error"] = f_error
        f_store.recordRankResult(
            f_point=f_point,
            f_global_rank=f_rank_idx,
            f_combination=f_combo,
            f_payload=f_payload,
            f_ordinal=f_ordinal,
        )

    def testLsmioExactRanks(self) -> None:
        """Tests LSMIO requiring launcher success + exact rank evidence for all tasks ranks."""
        # Scale point with 4 tasks
        f_doc, f_manifest_path, f_layout = self._createManifest(
            f_target="lsmio", f_scale="bake", f_run_id="run-lsmio-exact-ranks"
        )
        f_store = EvidenceStore(f_layout, f_plan=f_doc.toRunPlan())
        f_point = f_doc.scale_points[2]  # bake: [1, 2, 4, 8] -> index 2 is tasks=4
        f_point_id = "02-tasks-4"

        def lsmio_launcher_side_effect(
            f_argv: Sequence[str], f_kwargs: Dict[str, Any]
        ) -> ProcessResult:
            # When launcher runs for rank workers, simulate all 4 ranks writing result.json
            if "rank" in f_argv:
                f_combo = f_argv[-1]  # combination is always the last argument
                for f_rank_idx in range(4):
                    self._recordMockRankResult(
                        f_store, f_layout, f_point, f_rank_idx, f_combo, f_ordinal=2
                    )
            return ProcessResult(f_returncode=0)

        f_runner = MockProcessRunner(f_side_effect=lsmio_launcher_side_effect)
        f_status = AllocationController.run(
            f_manifest_path=f_manifest_path,
            f_point_id=f_point_id,
            f_runner=f_runner,
            f_worker_executable="/mock/bin/lsmioworker",
            f_layout=f_layout,
            f_evidence_store=f_store,
        )

        self.assertEqual(f_status, 0)

        # Assert each combination validated 4 ranks and recorded controller success
        for f_stripe, f_block in STANDARD_COMBINATION_TUPLES:
            f_combo = f"c{f_stripe}_b{f_block}"
            f_ctrl_res = f_store.readControllerResult(f_point, f_combo, f_ordinal=2)
            self.assertIsNotNone(f_ctrl_res)
            self.assertEqual(f_ctrl_res.payload["status"], "success")
            self.assertEqual(f_ctrl_res.payload["tasks_validated"], 4)

    def testRankEvidenceFailures(self) -> None:
        """Tests missing rank, failed rank, or corrupt rank evidence causes immediate combination failure."""
        # 1. Missing Rank Evidence (only 3 of 4 ranks write evidence)
        f_doc1, f_path1, f_layout1 = self._createManifest(
            f_target="lsmio", f_scale="bake", f_run_id="run-lsmio-missing-rank"
        )
        f_store1 = EvidenceStore(f_layout1, f_plan=f_doc1.toRunPlan())
        f_point1 = f_doc1.scale_points[2]  # tasks=4

        def missing_rank_side_effect(
            f_argv: Sequence[str], f_kwargs: Dict[str, Any]
        ) -> ProcessResult:
            if "rank" in f_argv:
                f_combo = f_argv[-1]
                # Write results only for ranks 0, 1, 2 (missing rank 3)
                for f_rank_idx in range(3):
                    self._recordMockRankResult(
                        f_store1, f_layout1, f_point1, f_rank_idx, f_combo, f_ordinal=2
                    )
            return ProcessResult(f_returncode=0)

        f_runner1 = MockProcessRunner(f_side_effect=missing_rank_side_effect)
        f_status1 = AllocationController.run(
            f_manifest_path=f_path1,
            f_point_id=2,
            f_runner=f_runner1,
            f_worker_executable="/mock/bin/lsmioworker",
            f_layout=f_layout1,
            f_evidence_store=f_store1,
        )

        self.assertEqual(f_status1, 1)
        f_ctrl_res1 = f_store1.readControllerResult(f_point1, "c16_b8M", f_ordinal=2)
        self.assertEqual(f_ctrl_res1.payload["status"], "failed")
        self.assertEqual(f_ctrl_res1.payload["stage"], "rank_evidence")
        self.assertIn("Missing rank result for rank 3", f_ctrl_res1.payload["error"])

        # 2. Failed Rank Evidence (rank 2 reports non-zero exit_code)
        f_doc2, f_path2, f_layout2 = self._createManifest(
            f_target="lsmio", f_scale="bake", f_run_id="run-lsmio-failed-rank"
        )
        f_store2 = EvidenceStore(f_layout2, f_plan=f_doc2.toRunPlan())

        def failed_rank_side_effect(
            f_argv: Sequence[str], f_kwargs: Dict[str, Any]
        ) -> ProcessResult:
            if "rank" in f_argv:
                f_combo = f_argv[-1]
                for f_rank_idx in range(4):
                    f_exit = 137 if f_rank_idx == 2 else 0
                    f_st = "failed" if f_rank_idx == 2 else "success"
                    f_err = "killed with 137" if f_rank_idx == 2 else None
                    self._recordMockRankResult(
                        f_store2,
                        f_layout2,
                        f_point1,
                        f_rank_idx,
                        f_combo,
                        f_ordinal=2,
                        f_status=f_st,
                        f_exit_code=f_exit,
                        f_error=f_err,
                    )
            return ProcessResult(f_returncode=0)

        f_runner2 = MockProcessRunner(f_side_effect=failed_rank_side_effect)
        f_status2 = AllocationController.run(
            f_manifest_path=f_path2,
            f_point_id=2,
            f_runner=f_runner2,
            f_worker_executable="/mock/bin/lsmioworker",
            f_layout=f_layout2,
            f_evidence_store=f_store2,
        )

        self.assertEqual(f_status2, 1)
        f_ctrl_res2 = f_store2.readControllerResult(f_point1, "c16_b8M", f_ordinal=2)
        self.assertEqual(f_ctrl_res2.payload["status"], "failed")
        self.assertIn("Rank 2", f_ctrl_res2.payload["error"])

        # 3. Corrupted Rank Evidence (corrupted JSON written to disk)
        f_doc3, f_path3, f_layout3 = self._createManifest(
            f_target="lsmio", f_scale="bake", f_run_id="run-lsmio-corrupt-rank"
        )
        f_store3 = EvidenceStore(f_layout3, f_plan=f_doc3.toRunPlan())

        def corrupt_rank_side_effect(
            f_argv: Sequence[str], f_kwargs: Dict[str, Any]
        ) -> ProcessResult:
            if "rank" in f_argv:
                f_combo = f_argv[-1]
                for f_rank_idx in range(4):
                    if f_rank_idx == 1:
                        # Write corrupted raw JSON directly
                        f_rank_path = f_layout3.pointRankResultPath(
                            f_point1, 1, f_combo, f_ordinal=2
                        )
                        os.makedirs(os.path.dirname(f_rank_path), exist_ok=True)
                        with open(f_rank_path, "wb") as f_f:
                            f_f.write(b"NOT_VALID_JSON{:::}")
                    else:
                        self._recordMockRankResult(
                            f_store3,
                            f_layout3,
                            f_point1,
                            f_rank_idx,
                            f_combo,
                            f_ordinal=2,
                        )
            return ProcessResult(f_returncode=0)

        f_runner3 = MockProcessRunner(f_side_effect=corrupt_rank_side_effect)
        f_status3 = AllocationController.run(
            f_manifest_path=f_path3,
            f_point_id=2,
            f_runner=f_runner3,
            f_worker_executable="/mock/bin/lsmioworker",
            f_layout=f_layout3,
            f_evidence_store=f_store3,
        )

        self.assertEqual(f_status3, 1)
        f_ctrl_res3 = f_store3.readControllerResult(f_point1, "c16_b8M", f_ordinal=2)
        self.assertEqual(f_ctrl_res3.payload["status"], "failed")
        self.assertIn("Corrupt rank result for rank 1", f_ctrl_res3.payload["error"])

    def testMismatchBeforeMutation(self) -> None:
        """Tests invalid point ID or corrupted manifest aborts before creating any directories or files."""
        f_doc, f_manifest_path, f_layout = self._createManifest(
            f_target="ior", f_scale="local"
        )

        # 1. Invalid point ID (nonexistent scale point)
        f_point_dir_before = f_layout.pointDir("99-tasks-99")
        self.assertFalse(os.path.exists(f_point_dir_before))

        with self.assertRaises(AllocationControllerError):
            AllocationController.run(
                f_manifest_path=f_manifest_path,
                f_point_id="99-tasks-99",
                f_layout=f_layout,
            )

        # Assert no point directory or worker events directory was created
        self.assertFalse(os.path.exists(f_point_dir_before))

        # 2. Corrupted manifest file
        f_corrupt_manifest_path = os.path.join(
            self.m_real_temp, "corrupt_manifest.json"
        )
        with open(f_corrupt_manifest_path, "w", encoding="utf-8") as f_f:
            f_f.write('{"schema_version": 1, "incomplete": true}')

        with self.assertRaises(AllocationControllerError):
            AllocationController.run(
                f_manifest_path=f_corrupt_manifest_path,
                f_point_id=0,
                f_layout=f_layout,
            )

    def testNeverOverwrite(self) -> None:
        """Asserts existing result files are never overwritten."""
        f_doc, f_manifest_path, f_layout = self._createManifest(
            f_target="ior", f_scale="local"
        )
        f_store = EvidenceStore(f_layout, f_plan=f_doc.toRunPlan())
        f_sp = f_doc.scale_points[0]

        # Pre-create combination 0 controller-result.json
        f_store.recordControllerResult(
            f_point=f_sp,
            f_combination="c16_b8M",
            f_payload={"status": "success", "exit_code": 0, "original": True},
            f_ordinal=0,
        )

        f_runner = MockProcessRunner()

        # Run allocation controller; must fail before overwriting c16_b8M result
        with self.assertRaises(AllocationControllerError) as f_cm:
            AllocationController.run(
                f_manifest_path=f_manifest_path,
                f_point_id=0,
                f_runner=f_runner,
                f_layout=f_layout,
                f_evidence_store=f_store,
            )

        self.assertIn("already exists", str(f_cm.exception))

        # Assert original result is preserved exactly
        f_res = f_store.readControllerResult(f_sp, "c16_b8M", f_ordinal=0)
        self.assertTrue(f_res.payload.get("original"))

    def testModulesAlreadyEstablishedOnce(self) -> None:
        """Asserts allocation controller does not re-invoke module load per combination or per rank."""
        f_doc, f_manifest_path, f_layout = self._createManifest(
            f_target="ior", f_scale="local"
        )
        f_runner = MockProcessRunner()

        with patch.object(
            ModuleSetup, "renderCommands", wraps=ModuleSetup.renderCommands
        ) as f_mock_render:
            f_status = AllocationController.run(
                f_manifest_path=f_manifest_path,
                f_point_id=0,
                f_runner=f_runner,
                f_layout=f_layout,
            )

            self.assertEqual(f_status, 0)
            # ModuleSetup.renderCommands must NEVER be called by allocation controller
            self.assertEqual(f_mock_render.call_count, 0)

        # Assert no 'module' command was passed to runner
        for f_argv, _ in f_runner.m_invocations:
            self.assertFalse(any("module" in f_arg for f_arg in f_argv))

    def testLmpConsumesManifestTuningOnly(self) -> None:
        """Asserts AllocationController consumes LMP tuning exclusively from manifest plan for exact tasks."""
        # 1. Valid LMP run consumes tuning from manifest
        f_doc, f_manifest_path, f_layout = self._createManifest(
            f_target="lmp", f_scale="local", f_run_id="run-lmp-tuning-valid"
        )
        f_runner = MockProcessRunner()
        f_status = AllocationController.run(
            f_manifest_path=f_manifest_path,
            f_point_id="00-tasks-1",
            f_runner=f_runner,
            f_asset_source=self.m_lmp_assets_dir,
            f_layout=f_layout,
        )
        self.assertEqual(f_status, 0)
        # Check first LMP benchmark command
        f_lmp_cmds = [
            inv[0] for inv in f_runner.m_invocations if "in.reaxc.hns" in inv[0]
        ]
        self.assertTrue(len(f_lmp_cmds) > 0)
        f_first_cmd = f_lmp_cmds[0]
        self.assertIn("in.reaxc.hns", f_first_cmd)
        self.assertIn("-v", f_first_cmd)
        self.assertIn("x", f_first_cmd)
        self.assertIn("4", f_first_cmd)  # tasks=1 -> rep=4
        self.assertIn("-lsmio-buf-size-mb", f_first_cmd)
        self.assertIn("32", f_first_cmd)  # tasks=1 -> buf=32

        # 2. Mismatched point task tuning in manifest fails closed during manifest validation
        f_doc_no_task_tuning, f_path_no_task_tuning, f_layout_no_task_tuning = (
            self._createManifest(
                f_target="lmp", f_scale="local", f_run_id="run-lmp-no-task-tuning"
            )
        )
        f_json_no_task_tuning = json.loads(f_doc_no_task_tuning.toJson())
        # Provide tuning for task count 2, but scale point is task count 1
        f_json_no_task_tuning["plan"]["lmp_task_tuning"] = {
            "2": {"replication": 5, "buffer_size_mb": 32}
        }
        with open(f_path_no_task_tuning, "w", encoding="utf-8") as f_f:
            json.dump(f_json_no_task_tuning, f_f, indent=2)

        with self.assertRaises(AllocationControllerError):
            AllocationController.run(
                f_manifest_path=f_path_no_task_tuning,
                f_point_id="00-tasks-1",
                f_runner=MockProcessRunner(),
                f_asset_source=self.m_lmp_assets_dir,
                f_layout=f_layout_no_task_tuning,
            )

        # 3. Missing lmp_task_tuning key entirely fails closed during manifest validation
        f_doc_missing_plan, f_path_missing_plan, f_layout_missing_plan = (
            self._createManifest(
                f_target="lmp", f_scale="local", f_run_id="run-lmp-missing-key"
            )
        )
        f_json_missing_key = json.loads(f_doc_missing_plan.toJson())
        del f_json_missing_key["plan"]["lmp_task_tuning"]
        with open(f_path_missing_plan, "w", encoding="utf-8") as f_f:
            json.dump(f_json_missing_key, f_f, indent=2)

        with self.assertRaises(AllocationControllerError):
            AllocationController.run(
                f_manifest_path=f_path_missing_plan,
                f_point_id="00-tasks-1",
                f_runner=MockProcessRunner(),
                f_asset_source=self.m_lmp_assets_dir,
                f_layout=f_layout_missing_plan,
            )

    def testEmptyPartialContradictoryRankPayloadFails(self) -> None:
        """Tests empty, partial, or contradictory rank payload causes combination failure in stage rank_evidence."""
        f_doc, f_path, f_layout = self._createManifest(
            f_target="lsmio", f_scale="local", f_run_id="run-lsmio-bad-payloads"
        )
        f_store = EvidenceStore(f_layout, f_plan=f_doc.toRunPlan())
        f_point = f_doc.scale_points[0]  # tasks=1

        # Case 1: Empty dict payload
        def empty_payload_runner(
            f_argv: Sequence[str], f_kwargs: Dict[str, Any]
        ) -> ProcessResult:
            if "rank" in f_argv:
                f_combo = f_argv[-1]
                f_store.recordRankResult(
                    f_point=f_point,
                    f_global_rank=0,
                    f_combination=f_combo,
                    f_payload={},
                    f_ordinal=0,
                )
            return ProcessResult(f_returncode=0)

        f_status1 = AllocationController.run(
            f_manifest_path=f_path,
            f_point_id=0,
            f_runner=MockProcessRunner(f_side_effect=empty_payload_runner),
            f_worker_executable="/mock/bin/lsmioworker",
            f_layout=f_layout,
            f_evidence_store=f_store,
        )
        self.assertEqual(f_status1, 1)
        f_ctrl1 = f_store.readControllerResult(f_point, "c16_b8M", f_ordinal=0)
        self.assertEqual(f_ctrl1.payload["status"], "failed")
        self.assertEqual(f_ctrl1.payload["stage"], "rank_evidence")

        # Case 2: Contradictory success+nonzero
        f_doc2, f_path2, f_layout2 = self._createManifest(
            f_target="lsmio",
            f_scale="local",
            f_run_id="run-lsmio-contradictory-payload",
        )
        f_store2 = EvidenceStore(f_layout2, f_plan=f_doc2.toRunPlan())

        def contradictory_payload_runner(
            f_argv: Sequence[str], f_kwargs: Dict[str, Any]
        ) -> ProcessResult:
            if "rank" in f_argv:
                f_combo = f_argv[-1]
                f_log = f_layout2.pointRankLogPath(f_point, 0, f_combo, f_ordinal=0)
                f_res = os.path.join(
                    f_layout2.pointRankCombinationDir(f_point, 0, f_combo, 0),
                    "rank_0.db",
                )
                os.makedirs(os.path.dirname(f_log), exist_ok=True)
                os.makedirs(os.path.dirname(f_res), exist_ok=True)
                with open(f_log, "w", encoding="utf-8") as f_f:
                    f_f.write("log\n")
                with open(f_res, "w", encoding="utf-8") as f_f:
                    f_f.write("db\n")
                f_store2.recordRankResult(
                    f_point=f_point,
                    f_global_rank=0,
                    f_combination=f_combo,
                    f_payload={
                        "status": "success",
                        "exit_code": 1,  # contradictory!
                        "exit_status": 0,
                        "global_rank": 0,
                        "rank": 0,
                        "combination": f_combo,
                        "argv": ["lsmioworker", "rank", f_combo],
                        "log_path": f_log,
                        "result_path": f_res,
                        "timed_out": False,
                    },
                    f_ordinal=0,
                )
            return ProcessResult(f_returncode=0)

        f_status2 = AllocationController.run(
            f_manifest_path=f_path2,
            f_point_id=0,
            f_runner=MockProcessRunner(f_side_effect=contradictory_payload_runner),
            f_worker_executable="/mock/bin/lsmioworker",
            f_layout=f_layout2,
            f_evidence_store=f_store2,
        )
        self.assertEqual(f_status2, 1)
        f_ctrl2 = f_store2.readControllerResult(f_point, "c16_b8M", f_ordinal=0)
        self.assertEqual(f_ctrl2.payload["status"], "failed")
        self.assertEqual(f_ctrl2.payload["stage"], "rank_evidence")

    def testExpectedOutputPropagationAndStrictValidationBeforeSuccess(self) -> None:
        """Tests that missing, symlinked, or non-regular output artifacts fail validation before recording success."""
        # 1. IOR output artifact deleted/missing before validation
        f_doc_ior, f_path_ior, f_layout_ior = self._createManifest(
            f_target="ior", f_scale="local", f_run_id="run-ior-output-missing"
        )
        f_store_ior = EvidenceStore(f_layout_ior, f_plan=f_doc_ior.toRunPlan())

        def ior_missing_output_runner(
            f_argv: Sequence[str], f_kwargs: Dict[str, Any]
        ) -> ProcessResult:
            # Delete stdout file if created
            f_log = f_kwargs.get("f_log_path") or f_kwargs.get("log_path")
            if f_log and os.path.exists(f_log):
                os.remove(f_log)
            return ProcessResult(f_returncode=0)

        f_status_ior = AllocationController.run(
            f_manifest_path=f_path_ior,
            f_point_id=0,
            f_runner=MockProcessRunner(f_side_effect=ior_missing_output_runner),
            f_layout=f_layout_ior,
            f_evidence_store=f_store_ior,
        )
        self.assertEqual(f_status_ior, 1)
        f_res_ior = f_store_ior.readControllerResult(
            f_doc_ior.scale_points[0], "c16_b8M", f_ordinal=0
        )
        self.assertEqual(f_res_ior.payload["status"], "failed")
        self.assertEqual(f_res_ior.payload["stage"], "output_validation")

        # 2. IOR output artifact is a symlink
        f_doc_sym, f_path_sym, f_layout_sym = self._createManifest(
            f_target="ior", f_scale="local", f_run_id="run-ior-symlink-output"
        )
        f_store_sym = EvidenceStore(f_layout_sym, f_plan=f_doc_sym.toRunPlan())

        def ior_symlink_output_runner(
            f_argv: Sequence[str], f_kwargs: Dict[str, Any]
        ) -> ProcessResult:
            f_log = f_kwargs.get("f_log_path") or f_kwargs.get("log_path")
            if f_log:
                os.makedirs(os.path.dirname(f_log), exist_ok=True)
                if os.path.exists(f_log):
                    os.remove(f_log)
                f_target_file = os.path.join(os.path.dirname(f_log), "real_output.txt")
                with open(f_target_file, "w", encoding="utf-8") as f_f:
                    f_f.write("real content\n")
                os.symlink(f_target_file, f_log)
            return ProcessResult(f_returncode=0)

        f_status_sym = AllocationController.run(
            f_manifest_path=f_path_sym,
            f_point_id=0,
            f_runner=MockProcessRunner(f_side_effect=ior_symlink_output_runner),
            f_layout=f_layout_sym,
            f_evidence_store=f_store_sym,
        )
        self.assertEqual(f_status_sym, 1)
        f_res_sym = f_store_sym.readControllerResult(
            f_doc_sym.scale_points[0], "c16_b8M", f_ordinal=0
        )
        self.assertEqual(f_res_sym.payload["status"], "failed")
        self.assertEqual(f_res_sym.payload["stage"], "output_validation")
        self.assertIn("symlink", f_res_sym.payload["error"])


if __name__ == "__main__":
    unittest.main()
