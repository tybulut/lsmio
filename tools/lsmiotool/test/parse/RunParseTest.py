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
import shutil
import tempfile
from typing import Tuple
import unittest

from lsmiotool.lib.artifacts import ArtifactLayout, ArtifactStore
from lsmiotool.lib.evidence import (
    EvidenceKind,
    EvidenceRecord,
    EvidenceStore,
    JobHandle,
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
from lsmiotool.lib.runparse import (
    ResolvedPoint,
    ResolvedRun,
    RunParseError,
    RunRootResolutionError,
    RunRootResolver,
)
from lsmiotool.lib.site import EnvironmentResolver
from lsmiotool.lib.state import OverallRunState, PointRunState


class RunParseTest(unittest.TestCase):
    """Unit tests covering explicit manifest-aware run root parse boundary."""

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.mkdtemp(prefix="lsmiotool-runparse-test-")
        self.m_default_profile_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "etc", "environments.json")
        )
        self.m_profile_doc = ProfileLoader.load(self.m_default_profile_path)
        self.m_test_user = "alice"
        self.m_test_home = "/home/alice"
        self.m_registry = EnvironmentResolver.resolveRegistry(
            self.m_profile_doc, f_user=self.m_test_user, f_home=self.m_test_home
        )
        self.m_viking_profile = self.m_registry.getProfile("VIKING")

    def tearDown(self) -> None:
        shutil.rmtree(self.m_temp_dir, ignore_errors=True)

    def _createPlan(
        self,
        f_run_id: str,
        f_target: str = "lsmio",
        f_scale: str = "local",
        f_setup: str = "NATIVE-M",
        f_ssd: bool = False,
    ) -> RunPlan:
        f_req = RunRequest(
            f_target=f_target,
            f_scale=f_scale,
            f_ssd=f_ssd,
            f_setup=f_setup,
        )
        f_tokens = [f"lm-{f_i:024d}" for f_i in range(1, 20)]
        f_tok_idx = 0

        def token_gen() -> str:
            nonlocal f_tok_idx
            f_tok = f_tokens[f_tok_idx]
            f_tok_idx += 1
            return f_tok

        return RunPlanner.createPlan(
            f_request=f_req,
            f_profile=self.m_viking_profile,
            f_run_id_source=lambda: f_run_id,
            f_clock=lambda: "2026-08-21T12:00:00Z",
            f_token_source=token_gen,
        )

    def _setupSucceededRun(
        self,
        f_run_id: str,
        f_target: str = "lsmio",
        f_scale: str = "local",
        f_setup: str = "NATIVE-M",
        f_ssd: bool = False,
    ) -> Tuple[str, RunPlan, EvidenceStore]:
        f_plan = self._createPlan(f_run_id, f_target=f_target, f_scale=f_scale, f_setup=f_setup, f_ssd=f_ssd)
        f_art_store = ArtifactStore(self.m_temp_dir, f_run_id)
        f_art_store.allocateRun(f_plan)
        f_evidence_store = EvidenceStore(f_art_store.layout, f_plan=f_plan)

        f_is_lsmio = (f_target.lower() == "lsmio")

        for f_idx, f_sp in enumerate(f_plan.scale_points):
            f_art_store.preparePoint(f_sp, f_ordinal=f_idx)
            f_handle = JobHandle("slurm", f"100{f_idx + 1}")

            f_evidence_store.recordSubmissionRequested(f_sp, "client", f_ordinal=f_idx)
            f_evidence_store.recordSubmissionDispatched(f_sp, "client", f_ordinal=f_idx)
            f_evidence_store.recordSubmissionRecorded(f_sp, "client", f_handle=f_handle, f_ordinal=f_idx)
            f_evidence_store.recordWorkerEvent(f_sp, 1, EvidenceKind.CONTROLLER_STARTED, f_ordinal=f_idx)

            for f_combo in f_plan.combinations:
                f_evidence_store.recordControllerResult(
                    f_sp, f_combo, f_payload={"exit_code": 0, "status": "success"}, f_ordinal=f_idx
                )
                if f_is_lsmio:
                    for f_rank in range(f_sp.tasks):
                        f_evidence_store.recordRankResult(
                            f_sp,
                            f_global_rank=f_rank,
                            f_combination=f_combo,
                            f_payload={"exit_code": 0, "status": "success"},
                            f_ordinal=f_idx,
                        )

            f_evidence_store.recordSchedulerObservation(
                f_sp,
                "reconciler",
                1,
                f_payload={"state": "succeeded", "handle": f_handle.toDict()},
                f_ordinal=f_idx,
            )

        f_evidence_store.recordWholeRunSucceeded("client", 1, f_payload={"summary": "all passed"})
        return f_art_store.layout.runRoot, f_plan, f_evidence_store

    def testExplicitSucceededPaths(self) -> None:
        """Validates RunRootResolver.resolve() and select() on mock valid succeeded run roots."""
        # 1. Test LSMIO succeeded run
        f_run_root_lsmio, f_plan_lsmio, _ = self._setupSucceededRun("run-lsmio-success-001", "lsmio", "local")
        f_resolved = RunRootResolver.resolve(f_run_root_lsmio)

        self.assertIsInstance(f_resolved, ResolvedRun)
        self.assertEqual(f_resolved.run_root, f_run_root_lsmio)
        self.assertEqual(f_resolved.runRoot, f_run_root_lsmio)
        self.assertEqual(f_resolved.run_id, "run-lsmio-success-001")
        self.assertEqual(f_resolved.runId, "run-lsmio-success-001")
        self.assertEqual(f_resolved.target, "lsmio")
        self.assertEqual(f_resolved.scale, "local")
        self.assertEqual(f_resolved.setup, "NATIVE-M")
        self.assertFalse(f_resolved.is_ssd)
        self.assertFalse(f_resolved.isSsd)
        self.assertTrue(f_resolved.is_success)
        self.assertTrue(f_resolved.isSuccess)
        self.assertEqual(f_resolved.run_state.state, OverallRunState.SUCCEEDED)
        self.assertEqual(len(f_resolved.points), 1)

        f_pt = f_resolved.points[0]
        self.assertIsInstance(f_pt, ResolvedPoint)
        self.assertEqual(f_pt.ordinal, 0)
        self.assertEqual(f_pt.scale_point.tasks, 1)
        self.assertTrue(f_pt.is_success)
        self.assertTrue(f_pt.isSuccess)
        self.assertTrue(f_pt.is_terminal)
        self.assertEqual(f_pt.state, PointRunState.SUCCEEDED)
        self.assertEqual(len(f_pt.controller_results), 6)
        self.assertEqual(len(f_pt.rank_results), 6)

        # Test select() alias
        f_selected = RunRootResolver.select(f_run_root_lsmio)
        self.assertEqual(f_selected, f_resolved)

        # Test getPoint lookups
        self.assertEqual(f_resolved.getPoint(0), f_pt)
        self.assertEqual(f_resolved.getPoint(1), f_pt)
        self.assertEqual(f_resolved.getPoint("00-tasks-1"), f_pt)
        self.assertEqual(f_resolved.getPoint(f_plan_lsmio.scale_points[0]), f_pt)

        # Test getControllerResult and getRankResult
        f_first_combo = f_plan_lsmio.combinations[0]
        self.assertIsNotNone(f_pt.getControllerResult(f_first_combo))
        self.assertIsNotNone(f_pt.getControllerResult(f_first_combo.name))
        self.assertIsNotNone(f_pt.getRankResult(0, f_first_combo))
        self.assertIsNotNone(f_pt.getRankResult(0, f_first_combo.name))

        # 2. Test IOR succeeded run with bake (multiple points)
        f_run_root_ior, f_plan_ior, _ = self._setupSucceededRun("run-ior-success-002", "ior", "bake", "BASE")
        f_resolved_ior = RunRootResolver.resolve(f_run_root_ior)
        self.assertEqual(f_resolved_ior.target, "ior")
        self.assertEqual(f_resolved_ior.scale, "bake")
        self.assertEqual(len(f_resolved_ior.points), 4)
        for f_i, f_p in enumerate(f_resolved_ior.points):
            self.assertEqual(f_p.ordinal, f_i)
            self.assertTrue(f_p.is_success)
            self.assertEqual(len(f_p.controller_results), 6)
            self.assertEqual(len(f_p.rank_results), 0)  # IOR has no rank results

        # Test toDict representations
        f_dict = f_resolved_ior.toDict()
        self.assertEqual(f_dict["run_id"], "run-ior-success-002")
        self.assertEqual(f_dict["target"], "ior")
        self.assertTrue(f_dict["is_success"])
        self.assertEqual(len(f_dict["points"]), 4)

    def testNeverDiscovers(self) -> None:
        """Asserts RunRootResolver has no auto-discovery, scanning, or pattern searching logic."""
        # 1. Assert no auto-discovery methods exist on RunRootResolver
        f_forbidden_methods = [
            "findLatest",
            "find_latest",
            "discover",
            "discoverRuns",
            "scan",
            "scanDirectory",
            "search",
            "searchRuns",
            "autoDiscover",
        ]
        for f_method in f_forbidden_methods:
            self.assertFalse(
                hasattr(RunRootResolver, f_method),
                f"RunRootResolver must not expose discovery method '{f_method}'",
            )

        # 2. Assert resolver rejects empty, None, and non-explicit paths without searching
        with self.assertRaises(RunRootResolutionError) as f_ctx:
            RunRootResolver.resolve("")
        self.assertIn("explicit_root must be a non-empty string", str(f_ctx.exception))

        with self.assertRaises(RunRootResolutionError) as f_ctx:
            RunRootResolver.resolve(None)  # type: ignore
        self.assertIn("explicit_root must be a non-empty string", str(f_ctx.exception))

        # 3. Assert non-existent path fails immediately without searching cwd or filesystem
        f_non_existent = os.path.join(self.m_temp_dir, "runs", "non-existent-run-999")
        with self.assertRaises(RunRootResolutionError) as f_ctx:
            RunRootResolver.resolve(f_non_existent)
        self.assertIn("does not exist", str(f_ctx.exception))

    def testNonSuccessRejected(self) -> None:
        """Asserts failed, incomplete, unstarted, and missing-marker runs raise RunRootResolutionError."""
        # 1. Unstarted run (only allocated)
        f_plan_unstarted = self._createPlan("run-unstarted-001", "lsmio", "local")
        f_store_unstarted = ArtifactStore(self.m_temp_dir, "run-unstarted-001")
        f_store_unstarted.allocateRun(f_plan_unstarted)
        f_unstarted_root = f_store_unstarted.layout.runRoot

        with self.assertRaises(RunRootResolutionError) as f_ctx:
            RunRootResolver.resolve(f_unstarted_root)
        self.assertIn("did not succeed", str(f_ctx.exception))

        # 2. Incomplete run (missing controller results)
        f_plan_inc = self._createPlan("run-inc-002", "lsmio", "local")
        f_store_inc = ArtifactStore(self.m_temp_dir, "run-inc-002")
        f_store_inc.allocateRun(f_plan_inc)
        f_sp_inc = f_plan_inc.scale_points[0]
        f_store_inc.preparePoint(f_sp_inc, f_ordinal=0)
        f_ev_inc = EvidenceStore(f_store_inc.layout, f_plan=f_plan_inc)
        f_handle_inc = JobHandle("slurm", "2001")
        f_ev_inc.recordSubmissionRequested(f_sp_inc, "client", f_ordinal=0)
        f_ev_inc.recordSubmissionDispatched(f_sp_inc, "client", f_ordinal=0)
        f_ev_inc.recordSubmissionRecorded(f_sp_inc, "client", f_handle=f_handle_inc, f_ordinal=0)
        f_ev_inc.recordWorkerEvent(f_sp_inc, 1, EvidenceKind.CONTROLLER_STARTED, f_ordinal=0)
        # Record only 3 out of 6 combinations
        for f_c in f_plan_inc.combinations[:3]:
            f_ev_inc.recordControllerResult(f_sp_inc, f_c, f_payload={"exit_code": 0}, f_ordinal=0)
            f_ev_inc.recordRankResult(f_sp_inc, 0, f_c, f_payload={"exit_code": 0}, f_ordinal=0)

        with self.assertRaises(RunRootResolutionError) as f_ctx:
            RunRootResolver.resolve(f_store_inc.layout.runRoot)
        self.assertIn("did not succeed", str(f_ctx.exception))

        # 3. Failed run (combination failed)
        f_plan_fail = self._createPlan("run-fail-003", "lsmio", "local")
        f_store_fail = ArtifactStore(self.m_temp_dir, "run-fail-003")
        f_store_fail.allocateRun(f_plan_fail)
        f_sp_fail = f_plan_fail.scale_points[0]
        f_store_fail.preparePoint(f_sp_fail, f_ordinal=0)
        f_ev_fail = EvidenceStore(f_store_fail.layout, f_plan=f_plan_fail)
        f_handle_fail = JobHandle("slurm", "2002")
        f_ev_fail.recordSubmissionRequested(f_sp_fail, "client", f_ordinal=0)
        f_ev_fail.recordSubmissionDispatched(f_sp_fail, "client", f_ordinal=0)
        f_ev_fail.recordSubmissionRecorded(f_sp_fail, "client", f_handle=f_handle_fail, f_ordinal=0)
        f_ev_fail.recordWorkerEvent(f_sp_fail, 1, EvidenceKind.CONTROLLER_STARTED, f_ordinal=0)
        for f_idx, f_c in enumerate(f_plan_fail.combinations):
            f_exit = 1 if f_idx == 0 else 0
            f_ev_fail.recordControllerResult(f_sp_fail, f_c, f_payload={"exit_code": f_exit}, f_ordinal=0)
            f_ev_fail.recordRankResult(f_sp_fail, 0, f_c, f_payload={"exit_code": f_exit}, f_ordinal=0)
        f_ev_fail.recordSchedulerObservation(
            f_sp_fail, "reconciler", 1, f_payload={"state": "failed", "handle": f_handle_fail.toDict()}, f_ordinal=0
        )

        with self.assertRaises(RunRootResolutionError) as f_ctx:
            RunRootResolver.resolve(f_store_fail.layout.runRoot)
        self.assertIn("did not succeed", str(f_ctx.exception))

        # 4. Missing whole_run_succeeded marker (point succeeded, but whole run not marked)
        f_plan_nomark = self._createPlan("run-nomark-004", "lsmio", "local")
        f_store_nomark = ArtifactStore(self.m_temp_dir, "run-nomark-004")
        f_store_nomark.allocateRun(f_plan_nomark)
        f_sp_nm = f_plan_nomark.scale_points[0]
        f_store_nomark.preparePoint(f_sp_nm, f_ordinal=0)
        f_ev_nm = EvidenceStore(f_store_nomark.layout, f_plan=f_plan_nomark)
        f_handle_nm = JobHandle("slurm", "2003")
        f_ev_nm.recordSubmissionRequested(f_sp_nm, "client", f_ordinal=0)
        f_ev_nm.recordSubmissionDispatched(f_sp_nm, "client", f_ordinal=0)
        f_ev_nm.recordSubmissionRecorded(f_sp_nm, "client", f_handle=f_handle_nm, f_ordinal=0)
        f_ev_nm.recordWorkerEvent(f_sp_nm, 1, EvidenceKind.CONTROLLER_STARTED, f_ordinal=0)
        for f_c in f_plan_nomark.combinations:
            f_ev_nm.recordControllerResult(f_sp_nm, f_c, f_payload={"exit_code": 0}, f_ordinal=0)
            f_ev_nm.recordRankResult(f_sp_nm, 0, f_c, f_payload={"exit_code": 0}, f_ordinal=0)
        f_ev_nm.recordSchedulerObservation(
            f_sp_nm, "reconciler", 1, f_payload={"state": "succeeded", "handle": f_handle_nm.toDict()}, f_ordinal=0
        )

        with self.assertRaises(RunRootResolutionError) as f_ctx:
            RunRootResolver.resolve(f_store_nomark.layout.runRoot)
        self.assertIn("did not succeed", str(f_ctx.exception))

    def testInterruptedPointInspectableNotWholeSuccess(self) -> None:
        """Asserts interrupted run root is rejected for whole run, but individual completed point evidence can be queried."""
        f_run_id = "run-interrupted-001"
        f_plan = self._createPlan(f_run_id, "lsmio", "bake")
        f_art_store = ArtifactStore(self.m_temp_dir, f_run_id)
        f_art_store.allocateRun(f_plan)
        f_evidence_store = EvidenceStore(f_art_store.layout, f_plan=f_plan)

        # Complete Point 0 (tasks=1)
        f_sp0 = f_plan.scale_points[0]
        f_art_store.preparePoint(f_sp0, f_ordinal=0)
        f_handle0 = JobHandle("slurm", "3001")
        f_evidence_store.recordSubmissionRequested(f_sp0, "client", f_ordinal=0)
        f_evidence_store.recordSubmissionDispatched(f_sp0, "client", f_ordinal=0)
        f_evidence_store.recordSubmissionRecorded(f_sp0, "client", f_handle=f_handle0, f_ordinal=0)
        f_evidence_store.recordWorkerEvent(f_sp0, 1, EvidenceKind.CONTROLLER_STARTED, f_ordinal=0)
        for f_combo in f_plan.combinations:
            f_evidence_store.recordControllerResult(
                f_sp0, f_combo, f_payload={"exit_code": 0, "status": "success"}, f_ordinal=0
            )
            f_evidence_store.recordRankResult(
                f_sp0, 0, f_combo, f_payload={"exit_code": 0, "status": "success"}, f_ordinal=0
            )
        f_evidence_store.recordSchedulerObservation(
            f_sp0, "reconciler", 1, f_payload={"state": "succeeded", "handle": f_handle0.toDict()}, f_ordinal=0
        )

        # Point 1 (tasks=2) is prepared but interrupted
        f_sp1 = f_plan.scale_points[1]
        f_art_store.preparePoint(f_sp1, f_ordinal=1)
        f_handle1 = JobHandle("slurm", "3002")
        f_evidence_store.recordSubmissionRequested(f_sp1, "client", f_ordinal=1)
        f_evidence_store.recordSubmissionDispatched(f_sp1, "client", f_ordinal=1)
        f_evidence_store.recordSubmissionRecorded(f_sp1, "client", f_handle=f_handle1, f_ordinal=1)

        # Record interruption event in control stream
        f_evidence_store.recordInterruption("client", 1, f_payload={"reason": "SIGINT received"})

        f_run_root = f_art_store.layout.runRoot

        # 1. Whole-run resolve MUST fail with RunRootResolutionError
        with self.assertRaises(RunRootResolutionError) as f_ctx:
            RunRootResolver.resolve(f_run_root)
        self.assertIn("did not succeed", str(f_ctx.exception))

        # 2. Point 0 was completed and can be inspected via resolvePoint()
        f_pt0 = RunRootResolver.resolvePoint(f_run_root, 0)
        self.assertIsInstance(f_pt0, ResolvedPoint)
        self.assertEqual(f_pt0.ordinal, 0)
        self.assertEqual(f_pt0.scale_point.tasks, 1)
        self.assertTrue(f_pt0.is_success)
        self.assertEqual(f_pt0.state, PointRunState.SUCCEEDED)
        self.assertEqual(len(f_pt0.controller_results), 6)
        self.assertEqual(len(f_pt0.rank_results), 6)

        # Also inspectable via point identifier string
        f_pt0_by_str = RunRootResolver.resolvePoint(f_run_root, "00-tasks-1")
        self.assertEqual(f_pt0_by_str, f_pt0)

        # 3. Point 1 was interrupted / incomplete
        f_pt1 = RunRootResolver.resolvePoint(f_run_root, 1)
        self.assertIsInstance(f_pt1, ResolvedPoint)
        self.assertEqual(f_pt1.ordinal, 1)
        self.assertEqual(f_pt1.scale_point.tasks, 2)
        self.assertFalse(f_pt1.is_success)
        self.assertNotEqual(f_pt1.state, PointRunState.SUCCEEDED)

    def testMalformedForeignSymlink(self) -> None:
        """Asserts symlinked root, missing manifest, malformed JSON, and foreign schema raise RunRootResolutionError."""
        # 1. Setup valid run first
        f_real_root, f_plan, _ = self._setupSucceededRun("run-real-001", "lsmio", "local")

        # Symlink to run root directory
        f_symlink_root = os.path.join(self.m_temp_dir, "runs", "symlink-run-001")
        os.symlink(f_real_root, f_symlink_root)
        with self.assertRaises(RunRootResolutionError) as f_ctx:
            RunRootResolver.resolve(f_symlink_root)
        self.assertIn("must not be a symlink", str(f_ctx.exception))

        # Symlink point resolution also rejected
        with self.assertRaises(RunRootResolutionError) as f_ctx:
            RunRootResolver.resolvePoint(f_symlink_root, 0)
        self.assertIn("must not be a symlink", str(f_ctx.exception))

        # 2. Root is a regular file, not a directory
        f_file_root = os.path.join(self.m_temp_dir, "runs", "file-root-001")
        with open(f_file_root, "w") as f_f:
            f_f.write("not a directory")
        with self.assertRaises(RunRootResolutionError) as f_ctx:
            RunRootResolver.resolve(f_file_root)
        self.assertIn("must be a directory", str(f_ctx.exception))

        # 3. Missing manifest.json
        f_no_manifest_root = os.path.join(self.m_temp_dir, "runs", "no-manifest-001")
        os.makedirs(f_no_manifest_root, exist_ok=True)
        with self.assertRaises(RunRootResolutionError) as f_ctx:
            RunRootResolver.resolve(f_no_manifest_root)
        self.assertIn("Missing manifest.json", str(f_ctx.exception))

        # 4. Symlinked manifest.json
        f_sym_man_root = os.path.join(self.m_temp_dir, "runs", "sym-man-001")
        os.makedirs(f_sym_man_root, exist_ok=True)
        f_real_man = os.path.join(f_real_root, "manifest.json")
        os.symlink(f_real_man, os.path.join(f_sym_man_root, "manifest.json"))
        with self.assertRaises(RunRootResolutionError) as f_ctx:
            RunRootResolver.resolve(f_sym_man_root)
        self.assertIn("manifest.json must not be a symlink", str(f_ctx.exception))

        # 5. manifest.json is a directory
        f_dir_man_root = os.path.join(self.m_temp_dir, "runs", "dir-man-001")
        os.makedirs(os.path.join(f_dir_man_root, "manifest.json"), exist_ok=True)
        with self.assertRaises(RunRootResolutionError) as f_ctx:
            RunRootResolver.resolve(f_dir_man_root)
        self.assertIn("manifest.json must be a regular file", str(f_ctx.exception))

        # 6. Malformed JSON syntax in manifest.json
        f_corrupt_man_root = os.path.join(self.m_temp_dir, "runs", "corrupt-man-001")
        os.makedirs(f_corrupt_man_root, exist_ok=True)
        with open(os.path.join(f_corrupt_man_root, "manifest.json"), "w") as f_f:
            f_f.write("{this is not valid json")
        with self.assertRaises(RunRootResolutionError) as f_ctx:
            RunRootResolver.resolve(f_corrupt_man_root)
        self.assertIn("Failed to deserialize manifest.json", str(f_ctx.exception))

        # 7. Foreign schema version (schema_version: 999)
        f_foreign_root = os.path.join(self.m_temp_dir, "runs", "foreign-schema-001")
        os.makedirs(f_foreign_root, exist_ok=True)
        with open(os.path.join(f_real_root, "manifest.json"), "r") as f_f:
            f_valid_dict = json.load(f_f)
        f_valid_dict["schema_version"] = 999
        f_valid_dict["run_id"] = "foreign-schema-001"
        with open(os.path.join(f_foreign_root, "manifest.json"), "w") as f_f:
            json.dump(f_valid_dict, f_f)
        with self.assertRaises(RunRootResolutionError) as f_ctx:
            RunRootResolver.resolve(f_foreign_root)
        self.assertIn("schema_version must be integer 1", str(f_ctx.exception))

        # 8. Mismatched run_id in manifest vs folder name
        f_mismatched_root = os.path.join(self.m_temp_dir, "runs", "folder-name-different-001")
        os.makedirs(f_mismatched_root, exist_ok=True)
        with open(os.path.join(f_real_root, "manifest.json"), "r") as f_f:
            f_man_dict = json.load(f_f)
        # manifest has run-real-001, but folder is folder-name-different-001
        with open(os.path.join(f_mismatched_root, "manifest.json"), "w") as f_f:
            json.dump(f_man_dict, f_f)
        with self.assertRaises(RunRootResolutionError) as f_ctx:
            RunRootResolver.resolve(f_mismatched_root)
        self.assertIn("does not match manifest run_id", str(f_ctx.exception))

        # 9. Run root not under a 'runs' directory
        f_non_runs_root = os.path.join(self.m_temp_dir, "custom_folder", "run-real-001")
        os.makedirs(f_non_runs_root, exist_ok=True)
        with open(os.path.join(f_non_runs_root, "manifest.json"), "w") as f_f:
            json.dump(f_man_dict, f_f)
        with self.assertRaises(RunRootResolutionError) as f_ctx:
            RunRootResolver.resolve(f_non_runs_root)
        self.assertIn("not located in a 'runs' directory", str(f_ctx.exception))

        # 10. Path containing NUL byte
        with self.assertRaises(RunRootResolutionError) as f_ctx:
            RunRootResolver.resolve("/path/with/\0/null")
        self.assertIn("contains NUL byte", str(f_ctx.exception))

    def testLegacyParseUnchanged(self) -> None:
        """Asserts legacy parse routines and compatibility remain unchanged."""
        from lsmiotool.lib.main import ParseMain

        # Legacy ParseMain initialization for ior, lsmio, lmp
        inst_ior = ParseMain("ior", "local")
        self.assertEqual(inst_ior.m_command, "ior")
        self.assertEqual(inst_ior.m_mode, "local")
        self.assertFalse(inst_ior.m_is_ssd)

        inst_lsmio = ParseMain("lsmio", "small", ssd=True)
        self.assertEqual(inst_lsmio.m_command, "lsmio")
        self.assertEqual(inst_lsmio.m_mode, "small")
        self.assertTrue(inst_lsmio.m_is_ssd)

        inst_lmp = ParseMain("lmp", "bake")
        self.assertEqual(inst_lmp.m_command, "lmp")
        self.assertEqual(inst_lmp.m_mode, "bake")

        # Assert ParseMain does not import or call RunRootResolver
        self.assertFalse(hasattr(inst_ior, "resolve"))
        self.assertFalse(hasattr(inst_ior, "select"))

    def testResolvedRunAndPointImmutability(self) -> None:
        """Asserts ResolvedRun and ResolvedPoint instances are strictly immutable."""
        f_run_root, f_plan, _ = self._setupSucceededRun("run-immut-001", "lsmio", "local")
        f_resolved = RunRootResolver.resolve(f_run_root)
        f_pt = f_resolved.points[0]

        with self.assertRaises(AttributeError):
            f_resolved.m_run_root = "new_root"  # type: ignore

        with self.assertRaises(AttributeError):
            f_resolved.target = "ior"  # type: ignore

        with self.assertRaises(AttributeError):
            del f_resolved.m_manifest  # type: ignore

        with self.assertRaises(AttributeError):
            f_pt.m_ordinal = 99  # type: ignore

        with self.assertRaises(AttributeError):
            f_pt.state = PointRunState.FAILED  # type: ignore

        with self.assertRaises(AttributeError):
            del f_pt.m_point_id  # type: ignore

    def testPointIdentifierLookups(self) -> None:
        """Asserts point lookup helper methods handle various identifier representations and fail on invalid ones."""
        f_run_root, f_plan, _ = self._setupSucceededRun("run-lookup-001", "lsmio", "bake")
        f_resolved = RunRootResolver.resolve(f_run_root)

        # Lookup by ordinal int
        self.assertEqual(f_resolved.getPoint(0).scale_point.tasks, 1)
        self.assertEqual(f_resolved.getPoint(1).scale_point.tasks, 2)
        self.assertEqual(f_resolved.getPoint(2).scale_point.tasks, 4)
        self.assertEqual(f_resolved.getPoint(3).scale_point.tasks, 8)

        # Lookup by task count int
        self.assertEqual(f_resolved.getPoint(8).ordinal, 3)

        # Lookup by string directory name
        self.assertEqual(f_resolved.getPoint("00-tasks-1").ordinal, 0)
        self.assertEqual(f_resolved.getPoint("03-tasks-8").ordinal, 3)

        # Lookup by string task count
        self.assertEqual(f_resolved.getPoint("8").ordinal, 3)

        # Lookup by ScalePoint instance
        self.assertEqual(f_resolved.getPoint(f_plan.scale_points[2]).ordinal, 2)

        # Invalid identifier raises RunParseError
        with self.assertRaises(RunParseError) as f_ctx:
            f_resolved.getPoint(999)
        self.assertIn("not found in resolved run", str(f_ctx.exception))

        with self.assertRaises(RunParseError) as f_ctx:
            f_resolved.getPoint("non-existent-point")
        self.assertIn("not found in resolved run", str(f_ctx.exception))

        # resolvePoint with invalid identifier raises RunRootResolutionError
        with self.assertRaises(RunRootResolutionError) as f_ctx:
            RunRootResolver.resolvePoint(f_run_root, 999)
        self.assertIn("not found in manifest scale points", str(f_ctx.exception))


if __name__ == "__main__":
    unittest.main()
