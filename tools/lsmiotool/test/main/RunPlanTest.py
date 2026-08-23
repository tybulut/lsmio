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

import copy
import json
import os
import unittest

from lsmiotool.lib.profile import ProfileLoader
from lsmiotool.lib.run import (
    Combination,
    LaunchMode,
    LaunchSpec,
    PlanValidationError,
    RankIdentity,
    RunPlan,
    RunPlanner,
    RunRequest,
    ScalePoint,
    ScheduledPointResources,
)
from lsmiotool.lib.site import EnvironmentResolver, SchedulerKind, SiteProfile, StorageClass


class RunPlanTest(unittest.TestCase):
    """Unit tests for immutable run domain classes and pure RunPlanner."""

    def setUp(self) -> None:
        self.m_default_profile_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "etc", "environments.json")
        )
        self.m_profile_doc = ProfileLoader.load(self.m_default_profile_path)
        self.m_test_user = "alice"
        self.m_test_home = "/home/alice"
        self.m_registry = EnvironmentResolver.resolveRegistry(
            self.m_profile_doc, f_user=self.m_test_user, f_home=self.m_test_home
        )
        self.m_dev_profile = self.m_registry.getProfile("DEV")
        self.m_viking_profile = self.m_registry.getProfile("VIKING")
        self.m_viking2_profile = self.m_registry.getProfile("VIKING2")
        self.m_isambard_profile = self.m_registry.getProfile("ISAMBARD")
        self.m_archer2_profile = self.m_registry.getProfile("ARCHER2")

    def testAllValidCombinationsAndScalePoints(self) -> None:
        """Assert the exact 6 ordered combinations and 4 scale matrices."""
        f_expected_combos = (
            (16, "8M", 16, 8388608, 1024, 128),
            (16, "1M", 16, 1048576, 4096, 1024),
            (16, "64K", 16, 65536, 65536, 16384),
            (4, "8M", 4, 8388608, 1024, 128),
            (4, "1M", 4, 1048576, 4096, 1024),
            (4, "64K", 4, 65536, 65536, 16384),
        )

        self.assertEqual(len(RunPlanner.ORDERED_COMBINATIONS), 6)
        for f_idx, f_expected in enumerate(f_expected_combos):
            f_c = RunPlanner.ORDERED_COMBINATIONS[f_idx]
            self.assertEqual(f_c.processes, f_expected[0])
            self.assertEqual(f_c.block_size, f_expected[1])
            self.assertEqual(f_c.stripe_count, f_expected[2])
            self.assertEqual(f_c.block_bytes, f_expected[3])
            self.assertEqual(f_c.key_count, f_expected[4])
            self.assertEqual(f_c.segment_count, f_expected[5])

        # Scale matrix for local
        self.assertEqual(
            RunPlanner.SCALE_MATRICES["local"],
            (ScalePoint(f_tasks=1, f_ppn=1, f_nodes=1),),
        )

        # Scale matrix for bake
        self.assertEqual(
            RunPlanner.SCALE_MATRICES["bake"],
            (
                ScalePoint(f_tasks=1, f_ppn=1, f_nodes=1),
                ScalePoint(f_tasks=2, f_ppn=1, f_nodes=2),
                ScalePoint(f_tasks=4, f_ppn=1, f_nodes=4),
                ScalePoint(f_tasks=8, f_ppn=1, f_nodes=8),
            ),
        )

        # Scale matrix for small
        f_expected_small_tasks = [1, 2, 4, 8, 16, 24, 32, 40, 48]
        self.assertEqual(
            RunPlanner.SCALE_MATRICES["small"],
            tuple(ScalePoint(f_tasks=f_t, f_ppn=1, f_nodes=f_t) for f_t in f_expected_small_tasks),
        )

        # Scale matrix for large
        f_expected_large_tasks = [4, 8, 16, 32, 64, 128, 192, 256]
        self.assertEqual(
            RunPlanner.SCALE_MATRICES["large"],
            tuple(ScalePoint(f_tasks=f_t, f_ppn=4, f_nodes=f_t // 4) for f_t in f_expected_large_tasks),
        )

    def testIorLsmioLmpSetups(self) -> None:
        """Assert default and explicit valid setups across IOR, LSMIO, and LMP."""
        # Default setups
        f_ior_req = RunRequest(f_target="ior", f_scale="small")
        f_ior_plan = RunPlanner.createPlan(f_ior_req, self.m_viking_profile)
        self.assertEqual(f_ior_plan.request.setup, "BASE")

        f_lsmio_req = RunRequest(f_target="lsmio", f_scale="small")
        f_lsmio_plan = RunPlanner.createPlan(f_lsmio_req, self.m_viking_profile)
        self.assertEqual(f_lsmio_plan.request.setup, "NATIVE-M")

        f_lmp_req = RunRequest(f_target="lmp", f_scale="small")
        f_lmp_plan = RunPlanner.createPlan(f_lmp_req, self.m_viking_profile)
        self.assertEqual(f_lmp_plan.request.setup, "LSMIO")

        # Explicit IOR setups
        for f_setup in ["BASE", "HDF5", "HDF5-C", "COLLECTIVE", "FSYNC", "REVERSE"]:
            f_req = RunRequest(f_target="ior", f_scale="local", f_setup=f_setup.lower())
            f_plan = RunPlanner.createPlan(f_req, self.m_viking_profile)
            self.assertEqual(f_plan.request.setup, f_setup)

        # Explicit LSMIO setups
        for f_setup in [
            "NATIVE-M",
            "ADIOS-M",
            "PLUGIN-M",
            "ROCKSDB-M",
            "LEVELDB-M",
            "ADIOS",
            "PLUGIN",
            "ROCKSDB",
            "LEVELDB",
            "MANAGER",
        ]:
            f_req = RunRequest(f_target="lsmio", f_scale="local", f_setup=f_setup.lower())
            f_plan = RunPlanner.createPlan(f_req, self.m_viking_profile)
            self.assertEqual(f_plan.request.setup, f_setup)

        # Explicit LMP setups
        for f_setup in ["LSMIO", "LSMIO-MMAP", "FS"]:
            f_req = RunRequest(f_target="lmp", f_scale="local", f_setup=f_setup.lower())
            f_plan = RunPlanner.createPlan(f_req, self.m_viking_profile)
            self.assertEqual(f_plan.request.setup, f_setup)

    def testLmpLargeRejectsBeforeSources(self) -> None:
        """Assert lmp large is rejected fail-closed before any ID, clock, or token invocation."""
        f_id_calls = 0
        f_clock_calls = 0
        f_token_calls = 0

        def spy_id_source() -> str:
            nonlocal f_id_calls
            f_id_calls += 1
            return "run-id-123"

        def spy_clock() -> str:
            nonlocal f_clock_calls
            f_clock_calls += 1
            return "2026-08-20T12:00:00Z"

        def spy_token_source() -> str:
            nonlocal f_token_calls
            f_token_calls += 1
            return "lm-0123456789abcdef01234567"

        f_req = RunRequest(f_target="lmp", f_scale="large")

        with self.assertRaises(PlanValidationError) as f_ctx:
            RunPlanner.createPlan(
                f_request=f_req,
                f_profile=self.m_viking_profile,
                f_run_id_source=spy_id_source,
                f_clock=spy_clock,
                f_token_source=spy_token_source,
            )

        self.assertIn("LMP", str(f_ctx.exception))
        self.assertIn("large", str(f_ctx.exception))
        self.assertEqual(f_id_calls, 0)
        self.assertEqual(f_clock_calls, 0)
        self.assertEqual(f_token_calls, 0)

    testLmpLargeFailsClosedWithoutIdentityOrSideEffects = testLmpLargeRejectsBeforeSources

    def testImmutabilityAndToDict(self) -> None:
        """Assert immutability of all records and canonical JSON schema-1 toDict serialization."""
        f_req = RunRequest(f_target="ior", f_scale="local", f_ssd=True, f_setup="BASE")
        with self.assertRaises(AttributeError):
            f_req.target = "lsmio"  # type: ignore

        f_sp = ScalePoint(f_tasks=4, f_ppn=4, f_nodes=1)
        with self.assertRaises(AttributeError):
            f_sp.tasks = 8  # type: ignore

        f_combo = Combination(
            f_processes=16,
            f_block_size="8M",
            f_stripe_count=16,
            f_block_bytes=8388608,
            f_key_count=1024,
            f_segment_count=128,
        )
        with self.assertRaises(AttributeError):
            f_combo.processes = 4  # type: ignore

        f_res = ScheduledPointResources(f_walltime="02:00:00", f_mem="8gb")
        with self.assertRaises(AttributeError):
            f_res.walltime = "06:00:00"  # type: ignore

        f_launch = LaunchSpec(
            f_mode=LaunchMode.SLURM,
            f_executable_or_worker="ior",
            f_arguments=["-v", "-w"],
            f_expected_results=["output.txt"],
        )
        with self.assertRaises(AttributeError):
            f_launch.executable_or_worker = "lmp"  # type: ignore

        f_rank = RankIdentity(f_global_rank=0, f_node_rank="node-1", f_local_rank=0)
        with self.assertRaises(AttributeError):
            f_rank.global_rank = 1  # type: ignore

        f_plan = RunPlanner.createPlan(
            f_request=f_req,
            f_profile=self.m_viking_profile,
            f_run_id_source=lambda: "run-test-123",
            f_clock=lambda: "2026-08-20T12:00:00Z",
            f_token_source=lambda: "lm-0123456789abcdef01234567",
        )
        with self.assertRaises(AttributeError):
            f_plan.run_id = "other-id"  # type: ignore

        # toDict serialization
        f_dict = f_plan.toDict()
        self.assertEqual(f_dict["schema_version"], 1)
        self.assertEqual(f_dict["run_id"], "run-test-123")
        self.assertEqual(f_dict["manifest_timestamp"], "2026-08-20T12:00:00Z")
        self.assertEqual(f_dict["request"]["target"], "ior")
        self.assertEqual(f_dict["request"]["scale"], "local")
        self.assertTrue(f_dict["request"]["ssd"])
        self.assertEqual(f_dict["request"]["setup"], "BASE")
        self.assertEqual(len(f_dict["scale_points"]), 1)
        self.assertEqual(len(f_dict["combinations"]), 6)
        self.assertEqual(len(f_dict["scheduled_points"]), 1)
        self.assertEqual(f_dict["tokens"], ["lm-0123456789abcdef01234567"])
        self.assertEqual(f_dict["lmp_task_tuning"], {})
        self.assertEqual(f_plan.lmp_task_tuning, {})

        # Mutating property copy does not mutate plan
        f_tuning_copy = f_plan.lmp_task_tuning
        f_tuning_copy["1"] = {"replication": 4, "buffer_size_mb": 32}
        self.assertEqual(f_plan.lmp_task_tuning, {})

        # JSON round-trip
        f_json_str = json.dumps(f_dict)
        f_loaded = json.loads(f_json_str)
        self.assertEqual(f_loaded["schema_version"], 1)

    def testScalePointTaskNodeDivisibility(self) -> None:
        """Assert ScalePoint enforces tasks > 0, ppn in {1, 4}, tasks % ppn == 0, nodes == tasks // ppn."""
        # Valid cases
        self.assertEqual(ScalePoint(1, 1, 1).nodes, 1)
        self.assertEqual(ScalePoint(256, 4, 64).nodes, 64)

        # tasks <= 0
        with self.assertRaises(PlanValidationError):
            ScalePoint(0, 1, 0)
        with self.assertRaises(PlanValidationError):
            ScalePoint(-4, 4, -1)

        # ppn not in {1, 4}
        with self.assertRaises(PlanValidationError):
            ScalePoint(8, 2, 4)
        with self.assertRaises(PlanValidationError):
            ScalePoint(16, 8, 2)

        # indivisible tasks
        with self.assertRaises(PlanValidationError):
            ScalePoint(7, 4, 1)

        # mismatched nodes
        with self.assertRaises(PlanValidationError):
            ScalePoint(16, 4, 8)

    def testSlurmAndPbsResourceCalculations(self) -> None:
        """Assert computed Slurm walltime and fixed PBS walltime and chunk mappings."""
        # Slurm (Viking): local (1 node) -> 2 + 0 = 2 hours -> "02:00:00"
        f_req_local = RunRequest("ior", "local")
        f_plan_viking_local = RunPlanner.createPlan(f_req_local, self.m_viking_profile)
        self.assertEqual(f_plan_viking_local.scheduled_points[0].walltime, "02:00:00")
        self.assertEqual(f_plan_viking_local.scheduled_points[0].mem, "8gb")
        self.assertEqual(f_plan_viking_local.scheduled_points[0].mail_mode, "END,FAIL")
        self.assertIsNone(f_plan_viking_local.scheduled_points[0].select_chunks)

        # Slurm (Viking): large (64 nodes max) -> 2 + 64 // 3 = 2 + 21 = 23 hours -> "23:00:00"
        f_req_large = RunRequest("ior", "large")
        f_plan_viking_large = RunPlanner.createPlan(f_req_large, self.m_viking_profile)
        self.assertEqual(f_plan_viking_large.scheduled_points[-1].walltime, "23:00:00")

        # Slurm (Archer2): partition/qos standard, mem None
        f_plan_archer2 = RunPlanner.createPlan(f_req_local, self.m_archer2_profile)
        self.assertEqual(f_plan_archer2.scheduled_points[0].partition, "standard")
        self.assertEqual(f_plan_archer2.scheduled_points[0].qos, "standard")
        self.assertIsNone(f_plan_archer2.scheduled_points[0].mem)

        # PBS (Isambard): small shape -> fixed "06:00:00", queue arm, pmem 8G, pvmem 8G, chunks=nodes, ncpus=1
        f_plan_isambard_small = RunPlanner.createPlan(f_req_local, self.m_isambard_profile)
        f_pt_small = f_plan_isambard_small.scheduled_points[0]
        self.assertEqual(f_pt_small.walltime, "06:00:00")
        self.assertEqual(f_pt_small.queue, "arm")
        self.assertEqual(f_pt_small.mail_mode, "abe")
        self.assertEqual(f_pt_small.mem, "32GB")
        self.assertEqual(f_pt_small.pmem, "8G")
        self.assertEqual(f_pt_small.pvmem, "8G")
        self.assertEqual(f_pt_small.select_chunks, 1)
        self.assertEqual(f_pt_small.ncpus, 1)
        self.assertEqual(f_pt_small.mpiprocs, 1)

        # PBS (Isambard): large shape -> fixed "06:00:00", queue arm, pmem None, pvmem None, chunks=nodes, ncpus=4
        f_plan_isambard_large = RunPlanner.createPlan(f_req_large, self.m_isambard_profile)
        f_pt_large = f_plan_isambard_large.scheduled_points[-1]
        self.assertEqual(f_pt_large.walltime, "06:00:00")
        self.assertEqual(f_pt_large.queue, "arm")
        self.assertEqual(f_pt_large.mail_mode, "abe")
        self.assertEqual(f_pt_large.mem, "32GB")
        self.assertIsNone(f_pt_large.pmem)
        self.assertIsNone(f_pt_large.pvmem)
        self.assertEqual(f_pt_large.select_chunks, 64)
        self.assertEqual(f_pt_large.ncpus, 4)
        self.assertEqual(f_pt_large.mpiprocs, 4)

    def testCorrelationTokenFormatAndUniqueness(self) -> None:
        """Assert correlation tokens must match ^lm-[0-9a-f]{24}$ and be unique per point."""
        f_tokens = [f"lm-{f_i:024x}" for f_i in range(9)]
        f_idx = 0

        def token_gen() -> str:
            nonlocal f_idx
            f_tok = f_tokens[f_idx]
            f_idx += 1
            return f_tok

        f_req = RunRequest("ior", "small")
        f_plan = RunPlanner.createPlan(
            f_request=f_req,
            f_profile=self.m_viking_profile,
            f_token_source=token_gen,
        )
        self.assertEqual(len(f_plan.tokens), 9)
        self.assertEqual(f_plan.tokens, tuple(f_tokens))

        # Duplicate token rejection
        with self.assertRaises(PlanValidationError) as f_ctx:
            RunPlanner.createPlan(
                f_request=f_req,
                f_profile=self.m_viking_profile,
                f_token_source=lambda: "lm-000000000000000000000001",
            )
        self.assertIn("Duplicate", str(f_ctx.exception))

        # Invalid token format rejection (wrong prefix, wrong length, uppercase)
        with self.assertRaises(PlanValidationError):
            RunPlanner.createPlan(
                f_request=f_req,
                f_profile=self.m_viking_profile,
                f_token_source=lambda: "bad-token-123",
            )

        with self.assertRaises(PlanValidationError):
            RunPlanner.createPlan(
                f_request=f_req,
                f_profile=self.m_viking_profile,
                f_token_source=lambda: "lm-0123456789ABCDEF01234567",
            )

        with self.assertRaises(PlanValidationError):
            RunPlanner.createPlan(
                f_request=f_req,
                f_profile=self.m_viking_profile,
                f_token_source=lambda: "lm-012345",
            )

    def testInvalidSetupAndTargetRejection(self) -> None:
        """Assert unknown targets, unknown scales, diagnostic ENV, and mismatched setups are rejected."""
        # Unknown target
        with self.assertRaises(PlanValidationError):
            RunPlanner.createPlan(RunRequest("unknown", "local"), self.m_viking_profile)

        # Unknown scale
        with self.assertRaises(PlanValidationError):
            RunPlanner.createPlan(RunRequest("ior", "giant"), self.m_viking_profile)

        # Diagnostic LSMIO setup ENV rejected
        with self.assertRaises(PlanValidationError) as f_ctx:
            RunPlanner.createPlan(RunRequest("lsmio", "local", f_setup="ENV"), self.m_viking_profile)
        self.assertIn("ENV", str(f_ctx.exception))

        # Setup invalid for IOR
        with self.assertRaises(PlanValidationError):
            RunPlanner.createPlan(RunRequest("ior", "local", f_setup="NATIVE-M"), self.m_viking_profile)

        # Setup invalid for LSMIO
        with self.assertRaises(PlanValidationError):
            RunPlanner.createPlan(RunRequest("lsmio", "local", f_setup="COLLECTIVE"), self.m_viking_profile)

        # Setup invalid for LMP
        with self.assertRaises(PlanValidationError):
            RunPlanner.createPlan(RunRequest("lmp", "local", f_setup="HDF5"), self.m_viking_profile)

    def testApprovedLmpTaskTuningForLocalBakeSmall(self) -> None:
        """Assert exact literal LMP task tuning objects in RunPlan for local, bake, and small scales."""
        f_expected_local = {
            "1": {"replication": 4, "buffer_size_mb": 32},
        }
        f_expected_bake = {
            "1": {"replication": 4, "buffer_size_mb": 32},
            "2": {"replication": 5, "buffer_size_mb": 32},
            "4": {"replication": 6, "buffer_size_mb": 64},
            "8": {"replication": 8, "buffer_size_mb": 128},
        }
        f_expected_small = {
            "1": {"replication": 4, "buffer_size_mb": 32},
            "2": {"replication": 5, "buffer_size_mb": 32},
            "4": {"replication": 6, "buffer_size_mb": 64},
            "8": {"replication": 8, "buffer_size_mb": 128},
            "16": {"replication": 10, "buffer_size_mb": 256},
            "24": {"replication": 12, "buffer_size_mb": 512},
            "32": {"replication": 14, "buffer_size_mb": 1024},
            "40": {"replication": 15, "buffer_size_mb": 1024},
            "48": {"replication": 16, "buffer_size_mb": 1024},
        }

        # 1. Local scale plan has exact 1-task tuning
        f_plan_local = RunPlanner.createPlan(RunRequest("lmp", "local"), self.m_viking_profile)
        self.assertEqual(f_plan_local.lmp_task_tuning, f_expected_local)

        # 2. Bake scale plan has exact 4-task tuning
        f_plan_bake = RunPlanner.createPlan(RunRequest("lmp", "bake"), self.m_viking_profile)
        self.assertEqual(f_plan_bake.lmp_task_tuning, f_expected_bake)

        # 3. Small scale plan has exact 9-task tuning
        f_plan_small = RunPlanner.createPlan(RunRequest("lmp", "small"), self.m_viking_profile)
        self.assertEqual(f_plan_small.lmp_task_tuning, f_expected_small)

        # 4. Direct authority query via getLmpTuning
        f_expected_task_map = {
            1: {"replication": 4, "buffer_size_mb": 32},
            2: {"replication": 5, "buffer_size_mb": 32},
            4: {"replication": 6, "buffer_size_mb": 64},
            8: {"replication": 8, "buffer_size_mb": 128},
            16: {"replication": 10, "buffer_size_mb": 256},
            24: {"replication": 12, "buffer_size_mb": 512},
            32: {"replication": 14, "buffer_size_mb": 1024},
            40: {"replication": 15, "buffer_size_mb": 1024},
            48: {"replication": 16, "buffer_size_mb": 1024},
        }
        for f_tasks, f_tuning in f_expected_task_map.items():
            self.assertEqual(RunPlanner.getLmpTuning(f_tasks), f_tuning)

        # 5. Undefined or non-positive task count raises PlanValidationError
        with self.assertRaises(PlanValidationError):
            RunPlanner.getLmpTuning(64)
        with self.assertRaises(PlanValidationError):
            RunPlanner.getLmpTuning(128)
        with self.assertRaises(PlanValidationError):
            RunPlanner.getLmpTuning(256)
        with self.assertRaises(PlanValidationError):
            RunPlanner.getLmpTuning(0)
        with self.assertRaises(PlanValidationError):
            RunPlanner.getLmpTuning(-1)

    def testLaunchModesAndCardinality(self) -> None:
        """Assert LaunchMode enum members, LaunchSpec, and RankIdentity behavior."""
        self.assertEqual(LaunchMode.DIRECT.value, "direct")
        self.assertEqual(LaunchMode.SLURM.value, "slurm")
        self.assertEqual(LaunchMode.PBS.value, "pbs")
        self.assertEqual(LaunchMode.FAKE.value, "fake")

        f_spec = LaunchSpec(
            f_mode=LaunchMode.SLURM,
            f_executable_or_worker="ior",
            f_arguments=["-v", "-w"],
            f_expected_results=["output.txt"],
        )
        self.assertEqual(f_spec.mode, LaunchMode.SLURM)
        self.assertEqual(f_spec.executable_or_worker, "ior")
        self.assertEqual(f_spec.arguments, ("-v", "-w"))
        self.assertEqual(f_spec.expected_results, ("output.txt",))

        # RankIdentity with and without local_rank
        f_rank_with_local = RankIdentity(f_global_rank=5, f_node_rank="node-2", f_local_rank=1)
        self.assertEqual(f_rank_with_local.global_rank, 5)
        self.assertEqual(f_rank_with_local.node_rank, "node-2")
        self.assertEqual(f_rank_with_local.local_rank, 1)

        f_rank_no_local = RankIdentity(f_global_rank=5, f_node_rank="node-2", f_local_rank=None)
        self.assertEqual(f_rank_no_local.global_rank, 5)
        self.assertEqual(f_rank_no_local.node_rank, "node-2")
        self.assertIsNone(f_rank_no_local.local_rank)
