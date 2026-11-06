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

import concurrent.futures
import json
import os
import shutil
import tempfile
import unittest

from lsmiotool.lib.artifacts import (
    ArtifactError,
    ArtifactLayout,
    ArtifactStore,
    CleanupForbiddenError,
    ContainmentError,
    ControlLock,
    LockContentionError,
    ManifestWriteError,
    RunCollisionError,
    STANDARD_COMBINATION_TUPLES,
    validatePathContainment,
)
from lsmiotool.lib.profile import ProfileLoader
from lsmiotool.lib.run import (
    Combination,
    ManifestSerializer,
    RunOrchestrator,
    RunPlan,
    RunPlanner,
    RunRequest,
    ScalePoint,
    ScheduledPointResources,
)
from lsmiotool.lib.site import EnvironmentResolver


class ArtifactStoreTest(unittest.TestCase):
    """Unit tests for ArtifactLayout, ControlLock, and ArtifactStore."""

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.mkdtemp(prefix="lsmiotool-artifact-test-")
        self.m_default_profile_path = os.path.normpath(
            os.path.join(
                os.path.dirname(__file__), "..", "..", "etc", "environments.json"
            )
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

    def _createTestPlan(self, f_run_id: str = "run-test-001") -> RunPlan:
        f_req = RunRequest(f_target="ior", f_scale="local", f_ssd=False, f_setup="BASE")
        f_tokens = ["lm-000000000000000000000001"]
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
            f_clock=lambda: "2026-08-20T12:00:00Z",
            f_token_source=token_gen,
        )

    def testExclusiveCollisionPreservesBytes(self) -> None:
        """Fails on existing run-id directory collision without overwriting existing data."""
        f_run_id = "run-collision-test"
        f_store1 = ArtifactStore(self.m_temp_dir, f_run_id)
        f_run_root = f_store1.allocateRun()
        self.assertTrue(os.path.isdir(f_run_root))

        # Write sentinel file with known bytes
        f_sentinel_path = os.path.join(f_run_root, "sentinel.dat")
        f_expected_bytes = b"exclusive-collision-preserved-bytes-12345"
        with open(f_sentinel_path, "wb") as f_f:
            f_f.write(f_expected_bytes)

        # Attempt to allocate same run_id again
        f_store2 = ArtifactStore(self.m_temp_dir, f_run_id)
        with self.assertRaises(RunCollisionError):
            f_store2.allocateRun()

        # Verify sentinel file still exists and contains unchanged bytes
        self.assertTrue(os.path.isfile(f_sentinel_path))
        with open(f_sentinel_path, "rb") as f_f:
            self.assertEqual(f_f.read(), f_expected_bytes)

    def testConcurrentRootsDisjoint(self) -> None:
        """Validates independent runs in different root locations remain disjoint."""
        f_root_a = os.path.join(self.m_temp_dir, "benchmark_a")
        f_root_b = os.path.join(self.m_temp_dir, "benchmark_b")
        f_run_id = "shared-run-id"

        f_store_a = ArtifactStore(f_root_a, f_run_id)
        f_store_b = ArtifactStore(f_root_b, f_run_id)

        f_root_a_allocated = f_store_a.allocateRun()
        f_root_b_allocated = f_store_b.allocateRun()

        self.assertNotEqual(f_root_a_allocated, f_root_b_allocated)
        self.assertTrue(os.path.isdir(f_root_a_allocated))
        self.assertTrue(os.path.isdir(f_root_b_allocated))

        # Prepare point on store A
        f_point_dir_a = f_store_a.preparePoint("00-tasks-1")
        f_file_a = os.path.join(
            f_store_a.layout.pointWorkDir("00-tasks-1"), "data_a.txt"
        )
        with open(f_file_a, "w") as f_f:
            f_f.write("content_a")

        # Point dir in store B should not exist until prepared
        self.assertFalse(os.path.exists(f_store_b.layout.pointDir("00-tasks-1")))

        # Prepare point on store B
        f_point_dir_b = f_store_b.preparePoint("00-tasks-1")
        f_file_b = os.path.join(
            f_store_b.layout.pointWorkDir("00-tasks-1"), "data_b.txt"
        )
        with open(f_file_b, "w") as f_f:
            f_f.write("content_b")

        # Verify disjoint contents
        self.assertTrue(os.path.exists(f_file_a))
        self.assertTrue(os.path.exists(f_file_b))
        self.assertFalse(
            os.path.exists(
                os.path.join(f_store_b.layout.pointWorkDir("00-tasks-1"), "data_a.txt")
            )
        )
        self.assertFalse(
            os.path.exists(
                os.path.join(f_store_a.layout.pointWorkDir("00-tasks-1"), "data_b.txt")
            )
        )

    def testManifestByteStableNoStateOrJob(self) -> None:
        """Proves manifest creation is create-once, byte-stable, and free of mutable state or job IDs."""
        f_run_id = "run-manifest-byte-stable"
        f_plan = self._createTestPlan(f_run_id)
        f_store = ArtifactStore(self.m_temp_dir, f_run_id)
        f_store.allocateRun()

        f_manifest_path = f_store.writeManifest(f_plan)
        self.assertEqual(f_manifest_path, f_store.layout.manifestPath)
        self.assertTrue(os.path.isfile(f_manifest_path))

        # Read back bytes
        with open(f_manifest_path, "rb") as f_f:
            f_disk_bytes = f_f.read()

        f_expected_text = ManifestSerializer.serialize(f_plan)
        self.assertEqual(f_disk_bytes, f_expected_text.encode("utf-8"))

        # Verify deserialization
        f_doc = ManifestSerializer.deserialize(f_disk_bytes)
        self.assertEqual(f_doc.run_id, f_run_id)

        # Inspect raw JSON: assert no mutable job/state fields exist
        f_raw_json = json.loads(f_disk_bytes.decode("utf-8"))
        f_forbidden_keys = {
            "job_id",
            "job_ids",
            "state",
            "status",
            "exit_code",
            "exit_status",
            "jobs",
        }
        self.assertTrue(f_forbidden_keys.isdisjoint(set(f_raw_json.keys())))
        for f_sp in f_raw_json.get("points", []):
            self.assertTrue(f_forbidden_keys.isdisjoint(set(f_sp.keys())))

        # Writing again must fail with ManifestWriteError
        with self.assertRaises(ManifestWriteError):
            f_store.writeManifest(f_plan)

    def testContainmentAttacks(self) -> None:
        """Proves rejection of .. traversal, symlink escapes, prefix collisions, and invalid names."""
        f_run_id = "run-containment"
        f_store = ArtifactStore(self.m_temp_dir, f_run_id)
        f_run_root = f_store.allocateRun()

        # 1. Path traversal attacks
        f_traversal_paths = [
            os.path.join(f_run_root, "..", "escaped"),
            os.path.join(f_run_root, "points", "..", "..", "escaped"),
            os.path.join(f_run_root, "points", "p1", "..", "..", "..", "etc", "passwd"),
            "/etc/passwd",
            "/tmp/arbitrary_file",
        ]
        for f_path in f_traversal_paths:
            with self.assertRaises(
                ContainmentError, msg=f"Failed to reject traversal path: {f_path}"
            ):
                f_store.validateContainment(f_path)

        # 2. Prefix collision attack (e.g. /runs/run-containment_decoy)
        f_prefix_attack = f_run_root + "_decoy"
        with self.assertRaises(ContainmentError):
            f_store.validateContainment(f_prefix_attack)

        # 3. Symlink escape attack
        f_outside_dir = tempfile.mkdtemp(prefix="outside-escape-")
        try:
            f_symlink_path = os.path.join(f_run_root, "symlink_escape")
            os.symlink(f_outside_dir, f_symlink_path)
            f_file_in_symlink = os.path.join(f_symlink_path, "target.txt")

            with self.assertRaises(ContainmentError):
                f_store.validateContainment(f_symlink_path)
            with self.assertRaises(ContainmentError):
                f_store.validateContainment(f_file_in_symlink)
        finally:
            shutil.rmtree(f_outside_dir, ignore_errors=True)

        # 4. Invalid run_id or component names
        with self.assertRaises(ContainmentError):
            ArtifactLayout(self.m_temp_dir, "run/with/slashes")
        with self.assertRaises(ContainmentError):
            ArtifactLayout(self.m_temp_dir, "run..traversal")
        with self.assertRaises(ContainmentError):
            f_store.layout.pointDirName("../escaped")
        with self.assertRaises(ContainmentError):
            f_store.layout.pointDirName("point/with/slash")
        with self.assertRaises(ContainmentError):
            f_store.layout.controlEventPath("../escaped", 1)
        with self.assertRaises(ContainmentError):
            f_store.layout.controlEventPath("writer/slash", 1)
        with self.assertRaises(ContainmentError):
            f_store.layout.combinationName("../escaped")

        # 5. NUL byte attack
        with self.assertRaises(ContainmentError):
            f_store.validateContainment(f_run_root + "/file\0null")

    def testCleanupOnlyMatchingIncompletePreparation(self) -> None:
        """Tests point cleanup removes only prepared point work without touching run root, logs, or results."""
        f_run_id = "run-cleanup-test"
        f_store = ArtifactStore(self.m_temp_dir, f_run_id)
        f_store.allocateRun()

        f_p1 = "00-tasks-1"
        f_p2 = "01-tasks-2"

        f_dir1 = f_store.preparePoint(f_p1)
        f_dir2 = f_store.preparePoint(f_p2)

        # Populate work and data in p1
        f_work1_file = os.path.join(f_store.layout.pointWorkDir(f_p1), "scratch.dat")
        f_data1_file = os.path.join(
            f_store.layout.pointDataSubdir(f_p1, 16, "8M"), "dataset1.bin"
        )
        with open(f_work1_file, "w") as f_f:
            f_f.write("temporary_work_1")
        with open(f_data1_file, "w") as f_f:
            f_f.write("data_1")

        # Populate work and data in p2
        f_work2_file = os.path.join(f_store.layout.pointWorkDir(f_p2), "scratch2.dat")
        f_data2_file = os.path.join(
            f_store.layout.pointDataSubdir(f_p2, 16, "8M"), "dataset2.bin"
        )
        with open(f_work2_file, "w") as f_f:
            f_f.write("temporary_work_2")
        with open(f_data2_file, "w") as f_f:
            f_f.write("data_2")

        # Add root marker
        f_root_marker = os.path.join(f_store.layout.runRoot, "root_marker.txt")
        with open(f_root_marker, "w") as f_f:
            f_f.write("root_preserved")

        # Cleanup incomplete preparation on p1
        f_store.cleanupIncompletePreparation(f_p1)

        # Assert p1 work and data files were removed
        self.assertFalse(os.path.exists(f_work1_file))
        self.assertFalse(os.path.exists(f_data1_file))

        # Assert p1 work and data directories still exist in clean state
        self.assertTrue(os.path.isdir(f_store.layout.pointWorkDir(f_p1)))
        self.assertTrue(os.path.isdir(f_store.layout.pointDataSubdir(f_p1, 16, "8M")))

        # Assert p2 was untouched
        self.assertTrue(os.path.exists(f_work2_file))
        self.assertTrue(os.path.exists(f_data2_file))

        # Assert root marker and run root were untouched
        self.assertTrue(os.path.exists(f_root_marker))
        self.assertTrue(os.path.isdir(f_store.layout.controlDir))
        self.assertTrue(os.path.isdir(f_store.layout.pointsDir))

    def testForbiddenCleanup(self) -> None:
        """Tests rejection of attempts to delete forbidden roots or result directories."""
        f_run_id = "run-forbidden-cleanup"
        f_store = ArtifactStore(self.m_temp_dir, f_run_id)
        f_store.allocateRun()

        # 1. Attempting to clean root directories fails closed
        with self.assertRaises(CleanupForbiddenError):
            f_store.cleanupIncompletePreparation(f_store.layout.benchmarkRoot)
        with self.assertRaises(CleanupForbiddenError):
            f_store.cleanupIncompletePreparation(f_store.layout.runsDir)
        with self.assertRaises(CleanupForbiddenError):
            f_store.cleanupIncompletePreparation(f_store.layout.runRoot)
        with self.assertRaises(CleanupForbiddenError):
            f_store.cleanupIncompletePreparation(f_store.layout.pointsDir)

        # 2. Attempting to clean point with existing controller-result.json
        f_point = "00-tasks-1"
        f_store.preparePoint(f_point)
        f_ctrl_result = f_store.layout.pointControllerResultPath(f_point, "c16_b8M")
        with open(f_ctrl_result, "w") as f_f:
            f_f.write('{"status": "completed"}')

        with self.assertRaises(CleanupForbiddenError):
            f_store.cleanupIncompletePreparation(f_point)

        # Remove controller result and write rank result.json
        os.remove(f_ctrl_result)
        f_rank_dir = f_store.layout.pointRankDir(f_point, 0)
        os.makedirs(os.path.join(f_rank_dir, "c16_b8M"), exist_ok=True)
        f_rank_result = f_store.layout.pointRankResultPath(f_point, 0, "c16_b8M")
        with open(f_rank_result, "w") as f_f:
            f_f.write('{"status": "completed"}')

        with self.assertRaises(CleanupForbiddenError):
            f_store.cleanupIncompletePreparation(f_point)

        # Remove rank result and write claim.lock
        os.remove(f_rank_result)
        f_claim_path = f_store.layout.pointRankClaimPath(f_point, 0, "c16_b8M")
        with open(f_claim_path, "w") as f_f:
            f_f.write('{"claimed_at": "2026-08-20T12:00:00Z"}')

        with self.assertRaises(CleanupForbiddenError):
            f_store.cleanupIncompletePreparation(f_point)

    def testCombinationScopedRankAndLogPathsAndContainment(self) -> None:
        """Tests that combination-scoped rank claim, result, and log paths are exact and contained."""
        f_run_id = "run-combo-scoped-paths"
        f_store = ArtifactStore(self.m_temp_dir, f_run_id)
        f_store.allocateRun()

        f_point = "00-tasks-1"
        f_store.preparePoint(f_point)

        f_rank_combo_dir = f_store.layout.pointRankCombinationDir(f_point, 0, "c16_b8M")
        self.assertEqual(
            f_rank_combo_dir,
            os.path.join(
                f_store.layout.runRoot, "points", f_point, "ranks", "0", "c16_b8M"
            ),
        )
        f_store.validateContainment(f_rank_combo_dir)

        f_claim_path = f_store.layout.pointRankClaimPath(f_point, 0, "c16_b8M")
        self.assertEqual(
            f_claim_path,
            os.path.join(f_rank_combo_dir, "claim.lock"),
        )
        f_store.validateContainment(f_claim_path)

        f_result_path = f_store.layout.pointRankResultPath(f_point, 0, "c16_b8M")
        self.assertEqual(
            f_result_path,
            os.path.join(f_rank_combo_dir, "result.json"),
        )
        f_store.validateContainment(f_result_path)

        f_combo_logs_dir = f_store.layout.pointCombinationLogsDir(f_point, "c16_b8M")
        self.assertEqual(
            f_combo_logs_dir,
            os.path.join(f_store.layout.runRoot, "points", f_point, "logs", "c16_b8M"),
        )
        f_store.validateContainment(f_combo_logs_dir)

        f_rank_log_path = f_store.layout.pointRankLogPath(f_point, 0, "c16_b8M")
        self.assertEqual(
            f_rank_log_path,
            os.path.join(f_combo_logs_dir, "rank_0.log"),
        )
        f_store.validateContainment(f_rank_log_path)

    def testLockExclusionAndRelease(self) -> None:
        """Tests ControlLock exclusion, non-blocking contention, and release on exit."""
        f_run_id = "run-lock-test"
        f_store = ArtifactStore(self.m_temp_dir, f_run_id)
        f_store.allocateRun()

        f_lock1 = f_store.getControlLock()
        f_lock2 = f_store.getControlLock()

        self.assertFalse(f_lock1.is_locked)
        self.assertFalse(f_lock2.is_locked)

        # Acquire lock1
        self.assertTrue(f_lock1.acquire(f_blocking=False))
        self.assertTrue(f_lock1.is_locked)
        self.assertTrue(os.path.isfile(f_lock1.lock_path))

        # lock2 non-blocking acquisition must raise LockContentionError
        with self.assertRaises(LockContentionError):
            f_lock2.acquire(f_blocking=False)
        self.assertFalse(f_lock2.is_locked)

        # Release lock1
        f_lock1.release()
        self.assertFalse(f_lock1.is_locked)

        # Now lock2 can acquire
        self.assertTrue(f_lock2.acquire(f_blocking=False))
        self.assertTrue(f_lock2.is_locked)
        f_lock2.release()
        self.assertFalse(f_lock2.is_locked)

        # Context manager test
        with f_lock1:
            self.assertTrue(f_lock1.is_locked)
            with self.assertRaises(LockContentionError):
                f_lock2.acquire(f_blocking=False)

        self.assertFalse(f_lock1.is_locked)

        # Lock can be re-acquired after context manager exit
        with f_lock2:
            self.assertTrue(f_lock2.is_locked)
        self.assertFalse(f_lock2.is_locked)

    def testArtifactLayoutPropertiesAndDataDirectories(self) -> None:
        """Validates all ArtifactLayout properties, standard data directories, and immutability."""
        f_layout = ArtifactLayout(self.m_temp_dir, "run-layout-001")
        self.assertEqual(f_layout.benchmarkRoot, os.path.abspath(self.m_temp_dir))
        self.assertEqual(f_layout.runId, "run-layout-001")
        self.assertEqual(
            f_layout.runsDir, os.path.join(os.path.abspath(self.m_temp_dir), "runs")
        )
        self.assertEqual(
            f_layout.runRoot,
            os.path.join(os.path.abspath(self.m_temp_dir), "runs", "run-layout-001"),
        )
        self.assertEqual(
            f_layout.manifestPath, os.path.join(f_layout.runRoot, "manifest.json")
        )
        self.assertEqual(
            f_layout.controlLockPath, os.path.join(f_layout.runRoot, "control", "lock")
        )

        # Check the 6 standard data directories
        f_sp = ScalePoint(f_tasks=16, f_ppn=4, f_nodes=4)
        f_data_dirs = f_layout.pointAllDataSubdirs(f_sp, f_ordinal=0)
        self.assertEqual(len(f_data_dirs), 6)

        f_expected_subdirs = [
            os.path.join(
                f_layout.runRoot, "points", "00-tasks-16", "data", f"c{f_s}", f"b{f_b}"
            )
            for f_s in (4, 16)
            for f_b in ("1M", "64K", "8M")
        ]
        self.assertEqual(list(f_data_dirs), f_expected_subdirs)

        # Immutability
        with self.assertRaises(AttributeError):
            f_layout.run_id = "modified"  # type: ignore
        with self.assertRaises(AttributeError):
            del f_layout.run_id  # type: ignore

        f_store = ArtifactStore(f_layout)
        with self.assertRaises(AttributeError):
            f_store.layout = f_layout  # type: ignore

    def testConcurrentSameIdExactlyOneWinnerAndLoserPreservesBytes(self) -> None:
        """Proves concurrent allocation race on the same run ID yields exactly one winner and losers preserve winner bytes."""
        f_run_id = "concurrent-race-run-id"
        f_num_threads = 10
        f_plan = self._createTestPlan(f_run_id)

        f_success_count = 0
        f_collision_count = 0
        f_other_errors = []

        def worker_allocate(thread_idx: int) -> str:
            f_s = ArtifactStore(self.m_temp_dir, f_run_id)
            return f_s.allocateRun(f_plan)

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=f_num_threads
        ) as executor:
            f_futures = [
                executor.submit(worker_allocate, i) for i in range(f_num_threads)
            ]
            for f in concurrent.futures.as_completed(f_futures):
                try:
                    f_res = f.result()
                    f_success_count += 1
                except RunCollisionError:
                    f_collision_count += 1
                except Exception as e:
                    f_other_errors.append(e)

        self.assertEqual(f_other_errors, [])
        self.assertEqual(
            f_success_count, 1, "Exactly one thread must win the allocation race"
        )
        self.assertEqual(
            f_collision_count,
            f_num_threads - 1,
            f"Remaining {f_num_threads - 1} threads must get RunCollisionError",
        )

        # Winner's directory exists and contains manifest.json
        f_winner_store = ArtifactStore(self.m_temp_dir, f_run_id)
        f_run_root = f_winner_store.layout.runRoot
        self.assertTrue(os.path.isdir(f_run_root))
        self.assertTrue(os.path.isfile(f_winner_store.layout.manifestPath))

        # Write sentinel data into winner root
        f_sentinel_path = os.path.join(f_run_root, "race_sentinel.bin")
        f_sentinel_bytes = b"exclusive-race-winner-data-987654321"
        with open(f_sentinel_path, "wb") as f_f:
            f_f.write(f_sentinel_bytes)

        # Record tree before loser attempt
        f_files_before = sorted(os.listdir(f_run_root))

        # Additional loser allocation attempt
        f_loser_store = ArtifactStore(self.m_temp_dir, f_run_id)
        with self.assertRaises(RunCollisionError):
            f_loser_store.allocateRun(f_plan)

        # Assert tree and bytes are 100% unchanged
        f_files_after = sorted(os.listdir(f_run_root))
        self.assertEqual(f_files_before, f_files_after)
        with open(f_sentinel_path, "rb") as f_f:
            self.assertEqual(f_f.read(), f_sentinel_bytes)

    def testExistingRootFileSymlinkWrongTypeCollisionRejection(self) -> None:
        """Tests that allocateRun rejects existing regular file or symlink at run root location."""
        # 1. Existing regular file at run root
        f_run_id_file = "run-file-collision"
        f_store_file = ArtifactStore(self.m_temp_dir, f_run_id_file)
        os.makedirs(f_store_file.layout.runsDir, exist_ok=True)
        with open(f_store_file.layout.runRoot, "w") as f_f:
            f_f.write("I am a file, not a directory")

        with self.assertRaises(RunCollisionError):
            f_store_file.allocateRun()

        # 2. Existing symlink at run root
        f_target_outside = tempfile.mkdtemp(prefix="symlink-target-")
        try:
            f_run_id_symlink = "run-symlink-collision"
            f_store_symlink = ArtifactStore(self.m_temp_dir, f_run_id_symlink)
            os.makedirs(f_store_symlink.layout.runsDir, exist_ok=True)
            os.symlink(f_target_outside, f_store_symlink.layout.runRoot)

            with self.assertRaises(ArtifactError):
                f_store_symlink.allocateRun()
        finally:
            shutil.rmtree(f_target_outside, ignore_errors=True)

    def _assertRaisesMessage(self, f_exc_type, f_message, f_call) -> None:
        with self.assertRaises(f_exc_type) as f_cm:
            f_call()
        self.assertIs(type(f_cm.exception), f_exc_type)
        self.assertEqual(str(f_cm.exception), f_message)

    def testValidatePathContainmentArgumentChecks(self) -> None:
        """Path and base argument checks, relative '..' and absolute '..' collapse."""
        f_root = os.path.abspath(self.m_temp_dir)
        for f_p in (None, 5, "", "   "):
            with self.subTest(f_p=f_p):
                self._assertRaisesMessage(
                    ContainmentError,
                    f"Path must be a non-empty string, got: {f_p!r}",
                    lambda: validatePathContainment(f_p, f_root),
                )
        for f_b in (None, 5, "", "  "):
            with self.subTest(f_b=f_b):
                self._assertRaisesMessage(
                    ContainmentError,
                    f"Base path must be a non-empty string, got: {f_b!r}",
                    lambda: validatePathContainment(f_root + "/x", f_b),
                )
        for f_p in ("../x", "a/../../x", ".."):
            with self.subTest(f_p=f_p):
                self._assertRaisesMessage(
                    ContainmentError,
                    f"Path traversal '..' detected in path: {f_p!r}",
                    lambda: validatePathContainment(f_p, f_root),
                )
        self.assertEqual(
            validatePathContainment(f_root + "/a/../b", f_root), f_root + "/b"
        )
        self.assertEqual(os.listdir(self.m_temp_dir), [])

    def testArtifactLayoutConstructorChecks(self) -> None:
        """Constructor argument checks, NUL bytes and run id stripping."""
        for f_r in (None, 5, "", "   "):
            with self.subTest(f_r=f_r):
                self._assertRaisesMessage(
                    ArtifactError,
                    f"benchmark_root must be a non-empty string, got: {f_r!r}",
                    lambda: ArtifactLayout(f_r, "run-1"),
                )
        for f_v in (None, 5, "", "   "):
            with self.subTest(f_v=f_v):
                self._assertRaisesMessage(
                    ArtifactError,
                    f"run_id must be a non-empty string, got: {f_v!r}",
                    lambda: ArtifactLayout(self.m_temp_dir, f_v),
                )
        for f_r, f_text in (
            ("/tmp/a\0b", "benchmark_root contains NUL byte: '/tmp/a\\x00b'"),
            ("a\0b", "benchmark_root contains NUL byte: 'a\\x00b'"),
        ):
            with self.subTest(f_r=f_r):
                self._assertRaisesMessage(
                    ContainmentError, f_text, lambda: ArtifactLayout(f_r, "run-1")
                )
        self.assertEqual(ArtifactLayout(self.m_temp_dir, " run-1 ").runId, "run-1")
        self.assertEqual(os.listdir(self.m_temp_dir), [])

    def testArtifactLayoutUnfrozenSlotWrites(self) -> None:
        """An unfrozen instance allows slot set and delete; a frozen one refuses."""
        f_raw = ArtifactLayout.__new__(ArtifactLayout)
        setattr(f_raw, "m_run_id", "r")
        self.assertEqual(f_raw.m_run_id, "r")
        delattr(f_raw, "m_run_id")
        with self.assertRaises(AttributeError):
            getattr(f_raw, "m_run_id")
        f_layout = ArtifactLayout(self.m_temp_dir, "run-1")
        self._assertRaisesMessage(
            AttributeError,
            "Cannot modify immutable ArtifactLayout",
            lambda: setattr(f_layout, "m_run_id", "x"),
        )
        self.assertEqual(f_layout.runId, "run-1")

    def testArtifactLayoutSnakeCaseAliases(self) -> None:
        """Each snake_case property equals its camelCase twin and the expected path."""
        f_layout = ArtifactLayout(self.m_temp_dir, "run-1")
        f_root = os.path.abspath(self.m_temp_dir)
        f_run = f_root + "/runs/run-1"
        f_rows = (
            ("benchmark_root", "benchmarkRoot", f_root),
            ("run_id", "runId", "run-1"),
            ("runs_dir", "runsDir", f_root + "/runs"),
            ("run_root", "runRoot", f_run),
            ("manifest_path", "manifestPath", f_run + "/manifest.json"),
            ("control_dir", "controlDir", f_run + "/control"),
            ("control_lock_path", "controlLockPath", f_run + "/control/lock"),
            ("control_events_dir", "controlEventsDir", f_run + "/control/events"),
            ("points_dir", "pointsDir", f_run + "/points"),
        )
        for f_snake, f_camel, f_expected in f_rows:
            with self.subTest(f_snake=f_snake):
                self.assertEqual(getattr(f_layout, f_snake), f_expected)
                self.assertEqual(getattr(f_layout, f_camel), f_expected)
        self.assertEqual(os.listdir(self.m_temp_dir), [])

    def testWriterNameValidation(self) -> None:
        """Writer names must be non-blank and free of separators and '..'."""
        f_layout = ArtifactLayout(self.m_temp_dir, "run-1")
        f_run = os.path.abspath(self.m_temp_dir) + "/runs/run-1"
        for f_w in (None, 5, "", "   "):
            with self.subTest(f_w=f_w):
                self._assertRaisesMessage(
                    ArtifactError,
                    f"writer must be a non-empty string, got: {f_w!r}",
                    lambda: f_layout.controlEventPath(f_w, "7"),
                )
        self.assertEqual(
            f_layout.controlEventPath(" control ", "7"),
            f_run + "/control/events/control/7.json",
        )
        for f_w in ("", "   ", 5):
            with self.subTest(f_w=f_w):
                self._assertRaisesMessage(
                    ArtifactError,
                    f"writer must be a non-empty string, got: {f_w!r}",
                    lambda: f_layout.pointSchedulerObservationsDir("00-tasks-1", f_w),
                )
        for f_w in ("a/b", "a\\b", "..", "x..y", "a\0b"):
            with self.subTest(f_w=f_w):
                self._assertRaisesMessage(
                    ContainmentError,
                    f"Invalid writer name: {f_w!r}",
                    lambda: f_layout.pointSchedulerObservationsDir("00-tasks-1", f_w),
                )
        f_obs = f_run + "/points/00-tasks-1/scheduler/observations"
        self.assertEqual(
            f_layout.pointSchedulerObservationsDir("00-tasks-1", " slurm "),
            f_obs + "/slurm",
        )
        self.assertEqual(f_layout.pointSchedulerObservationsDir("00-tasks-1"), f_obs)
        self._assertRaisesMessage(
            ContainmentError,
            "Invalid writer name: 'a/b'",
            lambda: f_layout.pointSchedulerObservationPath("00-tasks-1", "a/b", 1),
        )
        self.assertEqual(os.listdir(self.m_temp_dir), [])

    def testPointDirNameIntegerAndResourceDescriptors(self) -> None:
        """Integer and ScheduledPointResources descriptors map to directory names."""
        f_layout = ArtifactLayout(self.m_temp_dir, "run-1")
        f_points = os.path.abspath(self.m_temp_dir) + "/runs/run-1/points"
        self._assertRaisesMessage(
            ArtifactError,
            "Integer point needs a plan to be named; resolve it to a ScalePoint and ordinal first",
            lambda: f_layout.pointDirName(-1),
        )
        f_spr = ScheduledPointResources("01:00:00")
        self.assertEqual(f_layout.pointDirName(f_spr), "point")
        self.assertEqual(f_layout.pointDirName(f_spr, 3), "point-03")
        self.assertEqual(f_layout.pointDirName(f_spr, 0), "point-00")
        self.assertEqual(f_layout.pointDir(f_spr, 4), f_points + "/point-04")
        self.assertEqual(os.listdir(self.m_temp_dir), [])

    def testPointDirNameRejectsBareInteger(self) -> None:
        """A bare integer has no plan to name it from; the layout rejects it (EvidenceStore resolves ints)."""
        f_layout = ArtifactLayout(self.m_temp_dir, "run-1")
        f_sp = ScalePoint(f_tasks=4, f_ppn=1, f_nodes=4)
        for f_args in ((2,), (2, 5), (0,), (True,)):
            with self.subTest(f_args=f_args):
                self._assertRaisesMessage(
                    ArtifactError,
                    "Integer point needs a plan to be named; resolve it to a ScalePoint and ordinal first",
                    lambda: f_layout.pointDirName(*f_args),
                )
        self.assertEqual(f_layout.pointDirName(f_sp, 2), "02-tasks-4")
        self.assertEqual(os.listdir(self.m_temp_dir), [])

    def testUnsupportedPointAndCombinationTypes(self) -> None:
        """Unsupported point and combination descriptors are rejected by type name."""
        f_layout = ArtifactLayout(self.m_temp_dir, "run-1")
        for f_v in (None, 1.0, ("a",), b"x"):
            with self.subTest(f_v=f_v):
                self._assertRaisesMessage(
                    ArtifactError,
                    f"Unsupported point descriptor: {type(f_v).__name__}",
                    lambda: f_layout.pointDirName(f_v),
                )
        for f_c in (None, 5, ("c16", "8M"), {"name": "c16_b8M"}):
            with self.subTest(f_c=f_c):
                self._assertRaisesMessage(
                    ArtifactError,
                    f"Unsupported combination type: {type(f_c).__name__}",
                    lambda: f_layout.combinationName(f_c),
                )
        self._assertRaisesMessage(
            ArtifactError,
            "Unsupported combination type: int",
            lambda: f_layout.pointCombinationDir("00-tasks-1", 7),
        )
        self.assertEqual(os.listdir(self.m_temp_dir), [])

    def testArtifactLayoutReprAndEquality(self) -> None:
        """repr, equality (abspath based) and the missing __hash__."""
        f_layout = ArtifactLayout(self.m_temp_dir, "run-1")
        f_root = os.path.abspath(self.m_temp_dir)
        self.assertEqual(
            repr(f_layout), f"ArtifactLayout(benchmark_root={f_root!r}, run_id='run-1')"
        )
        self.assertTrue(f_layout == ArtifactLayout(self.m_temp_dir, "run-1"))
        self.assertTrue(f_layout == ArtifactLayout(self.m_temp_dir + "/", "run-1"))
        self.assertFalse(f_layout == ArtifactLayout(self.m_temp_dir, "run-2"))
        self.assertFalse(f_layout == ArtifactLayout(self.m_temp_dir + "/x", "run-1"))
        self.assertFalse(f_layout == f_layout.runRoot)
        self.assertIs(f_layout.__eq__(None), False)
        self.assertTrue(f_layout != "x")
        # Observation O-A1: __eq__ without __hash__ makes layouts unhashable.
        with self.assertRaises(TypeError):
            hash(f_layout)
        self.assertEqual(os.listdir(self.m_temp_dir), [])


if __name__ == "__main__":
    unittest.main()
