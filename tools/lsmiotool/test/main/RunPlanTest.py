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
import io
import json
import os
import unittest
from unittest.mock import patch

from lsmiotool.lib.arms import DEFAULT_LSMIO_BACKENDS
from lsmiotool.lib.profile import ProfileLoader
from lsmiotool.lib.run import (
    Combination,
    LaunchMode,
    LaunchSpec,
    ManifestSerializer,
    PlanValidationError,
    RankIdentity,
    RunPlan,
    RunPlanner,
    RunReporter,
    RunRequest,
    ScalePoint,
    ScheduledPointResources,
)
from lsmiotool.lib.site import (
    EnvironmentResolver,
    SchedulerKind,
    SiteProfile,
    StorageClass,
)


class RunPlanTest(unittest.TestCase):
    """Unit tests for immutable run domain classes and pure RunPlanner."""

    def setUp(self) -> None:
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
        self.m_dev_profile = self.m_registry.getProfile("DEV")
        self.m_viking_profile = self.m_registry.getProfile("VIKING")
        self.m_viking2_profile = self.m_registry.getProfile("VIKING2")
        self.m_isambard_profile = self.m_registry.getProfile("ISAMBARD")
        self.m_archer2_profile = self.m_registry.getProfile("ARCHER2")

    def testAllValidCombinationsAndScalePoints(self) -> None:
        """Assert the exact 6 combinations in bmtool order (rf 4 16; bs 1M 64K 8M) and 4 scale matrices."""
        f_expected_combos = (
            (4, "1M", 4, 1048576, 4096, 1024),
            (4, "64K", 4, 65536, 32768, 16384),
            (4, "8M", 4, 8388608, 1024, 128),
            (16, "1M", 16, 1048576, 4096, 1024),
            (16, "64K", 16, 65536, 32768, 16384),
            (16, "8M", 16, 8388608, 1024, 128),
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
            tuple(
                ScalePoint(f_tasks=f_t, f_ppn=1, f_nodes=f_t)
                for f_t in f_expected_small_tasks
            ),
        )

        # Scale matrix for large
        f_expected_large_tasks = [4, 8, 16, 32, 64, 128, 192, 256]
        self.assertEqual(
            RunPlanner.SCALE_MATRICES["large"],
            tuple(
                ScalePoint(f_tasks=f_t, f_ppn=4, f_nodes=f_t // 4)
                for f_t in f_expected_large_tasks
            ),
        )

    def testIorLsmioLmpSetups(self) -> None:
        """Assert default and explicit valid setups across IOR, LSMIO, and LMP."""
        # Default setups
        f_ior_req = RunRequest(f_target="ior", f_scale="small")
        f_ior_plan = RunPlanner.createPlan(f_ior_req, self.m_viking_profile)
        self.assertEqual(f_ior_plan.request.setup, "BASE")

        f_lsmio_req = RunRequest(f_target="lsmio", f_scale="small")
        f_lsmio_plan = RunPlanner.createPlan(f_lsmio_req, self.m_viking_profile)
        self.assertEqual(f_lsmio_plan.request.setup, "NATIVE")

        f_lmp_req = RunRequest(f_target="lmp", f_scale="small")
        f_lmp_plan = RunPlanner.createPlan(f_lmp_req, self.m_viking_profile)
        self.assertEqual(f_lmp_plan.request.setup, "LSMIO")

        # Explicit IOR setups
        for f_setup in ["BASE", "HDF5", "HDF5-C", "COLLECTIVE", "FSYNC", "REVERSE"]:
            f_req = RunRequest(f_target="ior", f_scale="local", f_setup=f_setup.lower())
            f_plan = RunPlanner.createPlan(f_req, self.m_viking_profile)
            self.assertEqual(f_plan.request.setup, f_setup)

        # Explicit LSMIO setups
        for f_setup in ["NATIVE", "ADIOS", "PLUGIN", "ROCKSDB", "LEVELDB", "MANAGER"]:
            f_req = RunRequest(
                f_target="lsmio", f_scale="local", f_setup=f_setup.lower()
            )
            f_plan = RunPlanner.createPlan(f_req, self.m_viking_profile)
            self.assertEqual(f_plan.request.setup, f_setup)

        # The removed '-M' setup names are rejected
        for f_setup in ["NATIVE-M", "adios-m", "ROCKSDB-M", "ENV"]:
            with self.subTest(setup=f_setup):
                f_req = RunRequest(f_target="lsmio", f_scale="local", f_setup=f_setup)
                with self.assertRaises(PlanValidationError):
                    RunPlanner.createPlan(f_req, self.m_viking_profile)

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

    testLmpLargeFailsClosedWithoutIdentityOrSideEffects = (
        testLmpLargeRejectsBeforeSources
    )

    def testImmutabilityAndToDict(self) -> None:
        """Assert immutability of all records and canonical JSON schema-1 toDict serialization."""
        f_req = RunRequest(f_target="ior", f_scale="local", f_ssd=True, f_setup="BASE")
        with self.assertRaises(AttributeError):
            f_req.target = "lsmio"  # type: ignore
        with self.assertRaises(AttributeError):
            f_req.variant = "footer"  # type: ignore

        with self.assertRaises(PlanValidationError):
            RunRequest("lsmio", "baseline", f_variant="")
        with self.assertRaises(PlanValidationError):
            RunRequest("lsmio", "baseline", f_variant="   ")
        with self.assertRaises(PlanValidationError):
            RunRequest("lsmio", "baseline", f_variant=123)  # type: ignore

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
        self.assertEqual(f_plan_viking_local.scheduled_points[0].mem, "16gb")
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

        # Slurm (Archer2): dynamic long QoS when walltime exceeds 24 hours
        f_req_archer2_backends = RunRequest("lsmio", "small", f_mode="backends")
        f_plan_archer2_backends = RunPlanner.createPlan(
            f_req_archer2_backends, self.m_archer2_profile
        )
        self.assertEqual(f_plan_archer2_backends.scheduled_points[0].qos, "standard")
        self.assertEqual(
            f_plan_archer2_backends.scheduled_points[-1].walltime, "48:00:00"
        )
        self.assertEqual(f_plan_archer2_backends.scheduled_points[-1].qos, "long")

        # PBS (Isambard): small shape -> fixed "06:00:00", queue arm, pmem 8G, pvmem 8G, chunks=nodes, ncpus=1
        f_plan_isambard_small = RunPlanner.createPlan(
            f_req_local, self.m_isambard_profile
        )
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
        f_plan_isambard_large = RunPlanner.createPlan(
            f_req_large, self.m_isambard_profile
        )
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
            RunPlanner.createPlan(
                RunRequest("lsmio", "local", f_setup="ENV"), self.m_viking_profile
            )
        self.assertIn("ENV", str(f_ctx.exception))

        # Setup invalid for IOR
        with self.assertRaises(PlanValidationError):
            RunPlanner.createPlan(
                RunRequest("ior", "local", f_setup="NATIVE"), self.m_viking_profile
            )

        # Setup invalid for LSMIO
        with self.assertRaises(PlanValidationError):
            RunPlanner.createPlan(
                RunRequest("lsmio", "local", f_setup="COLLECTIVE"),
                self.m_viking_profile,
            )

        # Setup invalid for LMP
        with self.assertRaises(PlanValidationError):
            RunPlanner.createPlan(
                RunRequest("lmp", "local", f_setup="HDF5"), self.m_viking_profile
            )

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
        f_plan_local = RunPlanner.createPlan(
            RunRequest("lmp", "local"), self.m_viking_profile
        )
        self.assertEqual(f_plan_local.lmp_task_tuning, f_expected_local)

        # 2. Bake scale plan has exact 4-task tuning
        f_plan_bake = RunPlanner.createPlan(
            RunRequest("lmp", "bake"), self.m_viking_profile
        )
        self.assertEqual(f_plan_bake.lmp_task_tuning, f_expected_bake)

        # 3. Small scale plan has exact 9-task tuning
        f_plan_small = RunPlanner.createPlan(
            RunRequest("lmp", "small"), self.m_viking_profile
        )
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
        f_rank_with_local = RankIdentity(
            f_global_rank=5, f_node_rank="node-2", f_local_rank=1
        )
        self.assertEqual(f_rank_with_local.global_rank, 5)
        self.assertEqual(f_rank_with_local.node_rank, "node-2")
        self.assertEqual(f_rank_with_local.local_rank, 1)

        f_rank_no_local = RankIdentity(
            f_global_rank=5, f_node_rank="node-2", f_local_rank=None
        )
        self.assertEqual(f_rank_no_local.global_rank, 5)
        self.assertEqual(f_rank_no_local.node_rank, "node-2")
        self.assertIsNone(f_rank_no_local.local_rank)

    def testBaselineScalePointTopology(self) -> None:
        """Tasks 2.4.1 (INV-ARCH-1): Asserts baseline scale matrix has single point ScalePoint(8, 1, 8)."""
        self.assertIn("variants", RunPlanner.SCALE_MATRICES)
        self.assertEqual(RunPlanner.SCALE_ALIASES.get("baseline"), "variants")
        f_baseline_points = RunPlanner.SCALE_MATRICES["variants"]
        self.assertEqual(len(f_baseline_points), 1)
        self.assertEqual(
            f_baseline_points, (ScalePoint(f_tasks=8, f_ppn=1, f_nodes=8),)
        )
        self.assertEqual(f_baseline_points[0].tasks, 8)
        self.assertEqual(f_baseline_points[0].ppn, 1)
        self.assertEqual(f_baseline_points[0].nodes, 8)

    def testBaselinePlanShapeIsSmall(self) -> None:
        """Tasks 2.4.1 (INV-ARCH-1): Asserts baseline scale resolves to resource shape 'small'."""
        f_req = RunRequest("lsmio", "baseline", False, "NATIVE")
        f_plan = RunPlanner.createPlan(f_req, self.m_viking_profile)
        self.assertEqual(len(f_plan.scale_points), 1)
        self.assertEqual(f_plan.scale_points[0], ScalePoint(8, 1, 8))
        self.assertEqual(len(f_plan.scheduled_points), 1)
        # Viking slurm_nodes walltime policy for 8 nodes: 2 + (8 // 3) = 4 hours -> '04:00:00'
        self.assertEqual(f_plan.scheduled_points[0].walltime, "04:00:00")
        self.assertEqual(f_plan.scheduled_points[0].mem, "16gb")

        # Also verify under PBS scheduler profile (Isambard small shape: fixed 06:00:00, ncpus=1, pmem=8G)
        f_plan_isambard = RunPlanner.createPlan(f_req, self.m_isambard_profile)
        self.assertEqual(f_plan_isambard.scheduled_points[0].walltime, "06:00:00")
        self.assertEqual(f_plan_isambard.scheduled_points[0].select_chunks, 8)
        self.assertEqual(f_plan_isambard.scheduled_points[0].ncpus, 1)
        self.assertEqual(f_plan_isambard.scheduled_points[0].mpiprocs, 1)
        self.assertEqual(f_plan_isambard.scheduled_points[0].pmem, "8G")

    def testManifestRoundtripWithVariant(self) -> None:
        """Tasks 2.4.2 (INV-ARCH-9): Asserts manifest serialization and deserialization preserves variant."""
        f_req = RunRequest(
            f_target="lsmio",
            f_scale="baseline",
            f_ssd=False,
            f_setup="NATIVE",
            f_variant="footer-btree",
        )
        self.assertEqual(f_req.variant, "footer-btree")
        f_plan = RunPlanner.createPlan(f_req, self.m_viking_profile)
        f_json_str = ManifestSerializer.serialize(f_plan)
        self.assertIn('"variant": "footer-btree"', f_json_str)

        f_doc = ManifestSerializer.deserialize(f_json_str)
        self.assertEqual(f_doc.request.variant, "footer-btree")
        self.assertEqual(f_doc.request, f_plan.request)
        self.assertEqual(f_doc.toRunPlan(), f_plan)

    def testManifestDeserializationLegacyWithoutVariant(self) -> None:
        """Tasks 2.4.2 (INV-ARCH-9): Asserts manifest deserialization succeeds when variant is omitted."""
        f_plan = RunPlanner.createPlan(
            RunRequest("lsmio", "local"), self.m_viking_profile
        )
        f_json_str = ManifestSerializer.serialize(f_plan)
        self.assertNotIn('"variant"', f_json_str)

        f_doc = ManifestSerializer.deserialize(f_json_str)
        self.assertIsNone(f_doc.request.variant)

        # Explicitly verify deserializing a dict where request has no variant key
        f_dict = json.loads(f_json_str)
        self.assertNotIn("variant", f_dict["request"])
        f_doc_from_dict = ManifestSerializer.deserialize(f_dict)
        self.assertIsNone(f_doc_from_dict.request.variant)
        self.assertEqual(f_doc_from_dict.request, f_plan.request)

    def testWalltimeScalingAndOverride(self) -> None:
        """Asserts walltime scales at 120 min/run + 2h headroom, and explicit overrides are respected."""
        # 1. Single variant: total_runs = 2 -> 2 + 2*2 = 6 hours (06:00:00)
        f_req_1 = RunRequest(
            f_target="lsmio", f_scale="baseline", f_variants=("footer",)
        )
        f_plan_1 = RunPlanner.createPlan(f_req_1, self.m_viking_profile)
        self.assertEqual(f_plan_1.scheduled_points[0].walltime, "06:00:00")

        # 2. Three variants: total_runs = 4 -> 2 + 4*2 = 10 hours (10:00:00)
        f_req_3 = RunRequest(
            f_target="lsmio", f_scale="baseline", f_variants=("footer", "btree", "mmap")
        )
        f_plan_3 = RunPlanner.createPlan(f_req_3, self.m_viking_profile)
        self.assertEqual(f_plan_3.scheduled_points[0].walltime, "10:00:00")

        # 3. Five variants: total_runs = 6 -> 2 + 6*2 = 14 hours (14:00:00)
        f_req_5 = RunRequest(
            f_target="lsmio",
            f_scale="baseline",
            f_variants=("footer", "btree", "mmap", "autotune", "manoff"),
        )
        f_plan_5 = RunPlanner.createPlan(f_req_5, self.m_viking_profile)
        self.assertEqual(f_plan_5.scheduled_points[0].walltime, "14:00:00")

        # 4. Large variant count clamped to 48 hours ceiling: 24 variants -> total_runs = 25 -> 2 + 25*2 = 52 -> 48h (48:00:00)
        f_vars_24 = tuple(f"var_{i}" for i in range(24))
        f_req_24 = RunRequest(
            f_target="lsmio", f_scale="baseline", f_variants=f_vars_24
        )
        f_plan_24 = RunPlanner.createPlan(f_req_24, self.m_viking_profile)
        self.assertEqual(f_plan_24.scheduled_points[0].walltime, "48:00:00")

        # 5. Explicit wallhour override
        f_req_override = RunRequest(
            f_target="lsmio", f_scale="baseline", f_variants=("footer",), f_wallhour=12
        )
        f_plan_override = RunPlanner.createPlan(f_req_override, self.m_viking_profile)
        self.assertEqual(f_plan_override.scheduled_points[0].walltime, "12:00:00")

        # 6. Explicit wallhour override clamped to 48 hours
        f_req_override_clamp = RunRequest(
            f_target="lsmio", f_scale="baseline", f_variants=("footer",), f_wallhour=60
        )
        f_plan_override_clamp = RunPlanner.createPlan(
            f_req_override_clamp, self.m_viking_profile
        )
        self.assertEqual(f_plan_override_clamp.scheduled_points[0].walltime, "48:00:00")

        # 7. Explicit walltime string override
        f_req_hms = RunRequest(
            f_target="lsmio", f_scale="baseline", f_walltime="05:30:00"
        )
        f_plan_hms = RunPlanner.createPlan(f_req_hms, self.m_viking_profile)
        self.assertEqual(f_plan_hms.scheduled_points[0].walltime, "05:30:00")

    def testBackendsModeWalltimeScalingAndOverride(self) -> None:
        """Asserts backends mode walltime formula (INV-BACKEND-2) scales deterministically and respects overrides."""
        # 1. Scale 'bake' (nodes: 1, 2, 4, 8) with 3 explicit backends:
        # nodes 1, 2, 4: max(1, nodes//3) = 1 -> 2 + 3*1 = 5 hours ('05:00:00')
        # node 8: max(1, 8//3) = 2 -> 2 + 3*2 = 8 hours ('08:00:00')
        f_req_bake = RunRequest(
            f_target="lsmio",
            f_scale="bake",
            f_mode="backends",
            f_backends=("adios2", "native", "rocksdb"),
        )
        f_plan_bake = RunPlanner.createPlan(f_req_bake, self.m_viking_profile)
        self.assertEqual(f_plan_bake.scheduled_points[0].walltime, "05:00:00")  # node 1
        self.assertEqual(f_plan_bake.scheduled_points[1].walltime, "05:00:00")  # node 2
        self.assertEqual(f_plan_bake.scheduled_points[2].walltime, "05:00:00")  # node 4
        self.assertEqual(f_plan_bake.scheduled_points[3].walltime, "08:00:00")  # node 8

        # 2. Custom 2 backends on bake:
        # node 8: max(1, 8//3) = 2 -> 2 + 2*2 = 6 hours ('06:00:00')
        f_req_2b = RunRequest(
            f_target="lsmio",
            f_scale="bake",
            f_mode="backends",
            f_backends=("adios2", "native"),
        )
        f_plan_2b = RunPlanner.createPlan(f_req_2b, self.m_viking_profile)
        self.assertEqual(f_plan_2b.scheduled_points[3].walltime, "06:00:00")

        # 2b. Default backends (adios2, native, plugin, rocksdb) on bake:
        # node 1: 2 + 4*1 = 6 hours; node 8: max(1, 8//3) = 2 -> 2 + 4*2 = 10 hours
        f_req_default = RunRequest(f_target="lsmio", f_scale="bake", f_mode="backends")
        f_plan_default = RunPlanner.createPlan(f_req_default, self.m_viking_profile)
        self.assertEqual(f_plan_default.scheduled_points[0].walltime, "06:00:00")
        self.assertEqual(f_plan_default.scheduled_points[3].walltime, "10:00:00")

        # 3. High node count clamping to 48 hours: node 48 -> 2 + 4*16 = 66 -> clamped to 48 ('48:00:00')
        f_req_small = RunRequest(
            f_target="lsmio",
            f_scale="small",
            f_mode="backends",
        )
        f_plan_small = RunPlanner.createPlan(f_req_small, self.m_viking_profile)
        # Point index 8 is 48 nodes in small scale
        self.assertEqual(f_plan_small.scale_points[8].nodes, 48)
        self.assertEqual(f_plan_small.scheduled_points[8].walltime, "48:00:00")

        # 4. Explicit user override takes precedence
        f_req_override = RunRequest(
            f_target="lsmio",
            f_scale="bake",
            f_mode="backends",
            f_wallhour=15,
        )
        f_plan_override = RunPlanner.createPlan(f_req_override, self.m_viking_profile)
        for sp in f_plan_override.scheduled_points:
            self.assertEqual(sp.walltime, "15:00:00")

    def testPbsFixedWalltimeIgnoresTimeOverride(self) -> None:
        """A PBS site's fixed walltime wins over --time, as in bmtool, so the job script
        still renders instead of failing on another walltime. It is per run: a job running
        several arms gets it once per arm, up to 48 hours."""
        from lsmiotool.lib.scheduler import PbsScriptRenderer

        for f_req, f_walltime in (
            (
                RunRequest("lsmio", "variants", f_variants=["footer"], f_wallhour=10),
                "12:00:00",
            ),
            (RunRequest("lsmio", "small", f_walltime="12:00:00"), "06:00:00"),
            (RunRequest("lsmio", "small", f_mode="backends"), "24:00:00"),
            (RunRequest("ior", "small", f_mode="backends"), "24:00:00"),
            (
                RunRequest("ior", "small", f_mode="backends", f_backends=["hdf5"]),
                "06:00:00",
            ),
            (RunRequest("lsmio", "variants", f_versioned=True), "12:00:00"),
            (
                RunRequest(
                    "lsmio", "variants", f_variants=[f"v{f_i}" for f_i in range(9)]
                ),
                "48:00:00",
            ),
        ):
            f_plan = RunPlanner.createPlan(f_req, self.m_isambard_profile)
            for f_idx, f_sp in enumerate(f_plan.scale_points):
                f_res = f_plan.scheduled_points[f_idx]
                self.assertEqual(f_res.walltime, f_walltime, f_req)
                PbsScriptRenderer.renderDirectives(
                    f_point=f_sp,
                    f_profile=self.m_isambard_profile,
                    f_job_name=f_plan.tokens[f_idx],
                    f_output_path="/tmp/out",
                    f_error_path="/tmp/err",
                    f_walltime=f_res.walltime,
                )

    def testFixedWalltimeRunCountAndOtherFixedValues(self) -> None:
        """The arms a job runs, as resolveArmGroup resolves them; another fixed value scales
        by whole multiples within 48 hours, and the PBS renderer accepts exactly those."""
        from lsmiotool.lib.run import (
            PlanValidationError,
            groupRunCount,
            scaleFixedWalltime,
        )
        from lsmiotool.lib.scheduler import PbsScriptRenderer, SchedulerScriptError

        self.assertEqual(
            groupRunCount(RunRequest("lsmio", "baseline", f_variants=["a"])), 2
        )
        self.assertEqual(
            groupRunCount(RunRequest("lsmio", "baseline", f_versioned=True)), 2
        )
        self.assertEqual(
            groupRunCount(RunRequest("lmp", "small", f_mode="backends")), 1
        )
        self.assertEqual(
            groupRunCount(RunRequest("ior", "small", f_mode="backends")), 4
        )
        self.assertEqual(scaleFixedWalltime("07:00:00", 9), "42:00:00")
        self.assertEqual(scaleFixedWalltime("08:00:00", 3), "24:00:00")
        self.assertEqual(
            PbsScriptRenderer.fixedWalltimes("08:00:00"),
            ("08:00:00", "16:00:00", "24:00:00", "32:00:00", "40:00:00", "48:00:00"),
        )

        f_profile = copy.deepcopy(self.m_isambard_profile)
        f_small = (
            f_profile.resources["small"]
            if isinstance(f_profile.resources, dict)
            else f_profile.resources.small
        )
        object.__setattr__(f_small, "m_walltime_policy", "fixed_08:00:00")
        for f_req, f_walltime in (
            (RunRequest("lsmio", "small"), "08:00:00"),
            (RunRequest("ior", "small", f_mode="backends"), "32:00:00"),
            (RunRequest("lsmio", "variants", f_variants=["a", "b"]), "24:00:00"),
        ):
            f_plan = RunPlanner.createPlan(f_req, f_profile)
            f_sp = f_plan.scale_points[0]
            self.assertEqual(f_plan.scheduled_points[0].walltime, f_walltime)
            self.assertIn(
                f"#PBS -l walltime={f_walltime}",
                PbsScriptRenderer.renderDirectives(
                    f_point=f_sp,
                    f_profile=f_profile,
                    f_job_name=f_plan.tokens[0],
                    f_output_path="/tmp/out",
                    f_error_path="/tmp/err",
                    f_walltime=f_walltime,
                ),
            )
        with self.assertRaises(SchedulerScriptError):
            PbsScriptRenderer.renderDirectives(
                f_point=f_sp,
                f_profile=f_profile,
                f_job_name=f_plan.tokens[0],
                f_output_path="/tmp/out",
                f_error_path="/tmp/err",
                f_walltime="06:00:00",
            )
        object.__setattr__(f_small, "m_walltime_policy", "fixed_6h")
        with self.assertRaises(PlanValidationError):
            RunPlanner.createPlan(RunRequest("lsmio", "small"), f_profile)

    def testSlurmQosPromotionBoundariesAndLimits(self) -> None:
        """Verify exact QoS promotion boundaries, Slurm time format handling, and limit enforcement (T1, S4, S5)."""
        # 1. Exact boundary 24:00:00 -> standard
        f_req_24h = RunRequest("lsmio", "local", f_walltime="24:00:00")
        f_plan_24h = RunPlanner.createPlan(f_req_24h, self.m_archer2_profile)
        self.assertEqual(f_plan_24h.scheduled_points[0].qos, "standard")

        # 2. Boundary 24:30:00 -> long (would be rejected by standard QoS)
        f_req_24_5h = RunRequest("lsmio", "local", f_walltime="24:30:00")
        f_plan_24_5h = RunPlanner.createPlan(f_req_24_5h, self.m_archer2_profile)
        self.assertEqual(f_plan_24_5h.scheduled_points[0].qos, "long")

        # 3. Boundary 25:00:00 -> long
        f_req_25h = RunRequest("lsmio", "local", f_walltime="25:00:00")
        f_plan_25h = RunPlanner.createPlan(f_req_25h, self.m_archer2_profile)
        self.assertEqual(f_plan_25h.scheduled_points[0].qos, "long")

        # 4. Slurm day format: 1-00:00:00 (24h) -> standard
        f_req_day_24h = RunRequest("lsmio", "local", f_walltime="1-00:00:00")
        f_plan_day_24h = RunPlanner.createPlan(f_req_day_24h, self.m_archer2_profile)
        self.assertEqual(f_plan_day_24h.scheduled_points[0].qos, "standard")

        # 5. Slurm day format: 1-01:00:00 (25h) -> long
        f_req_day_25h = RunRequest("lsmio", "local", f_walltime="1-01:00:00")
        f_plan_day_25h = RunPlanner.createPlan(f_req_day_25h, self.m_archer2_profile)
        self.assertEqual(f_plan_day_25h.scheduled_points[0].qos, "long")

        # 6. Slurm day format: D-HH:MM (e.g. 1-00:30 = 24.5h) -> long
        f_req_day_dhm = RunRequest("lsmio", "local", f_walltime="1-00:30")
        f_plan_day_dhm = RunPlanner.createPlan(f_req_day_dhm, self.m_archer2_profile)
        self.assertEqual(f_plan_day_dhm.scheduled_points[0].qos, "long")

        # 7/8. Requested walltimes are clamped to 48h like --time, so
        # 96h, 4 days and anything beyond become 48:00:00 on the long QoS
        for f_long in ("96:00:00", "4-00:00:00", "97:00:00", "4-01:00:00"):
            f_plan_long = RunPlanner.createPlan(
                RunRequest("lsmio", "local", f_walltime=f_long), self.m_archer2_profile
            )
            self.assertEqual(f_plan_long.scheduled_points[0].walltime, "48:00:00")
            self.assertEqual(f_plan_long.scheduled_points[0].qos, "long")
        f_plan_fast = RunPlanner.createPlan(
            RunRequest("lsmio", "local", f_walltime="30:00:00", f_fast=True),
            self.m_archer2_profile,
        )
        self.assertEqual(f_plan_fast.scheduled_points[0].walltime, "23:00:00")
        self.assertEqual(f_plan_fast.scheduled_points[0].qos, "standard")

        # 9. Invalid/unparseable walltime inputs -> PlanValidationError
        for bad_walltime in ("invalid", "24:60:00", "1-25:00:00", "-1:00:00", ""):
            with self.assertRaises(PlanValidationError):
                RunPlanner.createPlan(
                    RunRequest("lsmio", "local", f_walltime=bad_walltime),
                    self.m_archer2_profile,
                )

        # 10. Long QoS node count limit: nodes > 64 raises PlanValidationError (S5)
        f_point_65 = ScalePoint(f_tasks=65, f_ppn=1, f_nodes=65)
        with patch.dict(RunPlanner.SCALE_MATRICES, {"custom": (f_point_65,)}):
            with self.assertRaises(PlanValidationError) as ctx:
                RunPlanner.createPlan(
                    RunRequest("lsmio", "custom", f_walltime="25:00:00"),
                    self.m_archer2_profile,
                )
            self.assertIn(
                "exceeds maximum allowed 64 nodes for long QoS", str(ctx.exception)
            )

    def testNonArcher2ProfileKeepsConfiguredQosAt48h(self) -> None:
        """Verify non-ARCHER2 Slurm profile (Viking) with 48h walltime keeps its configured QoS (T2)."""
        # Viking has qos: null in environments.json
        f_req_viking_48h = RunRequest("lsmio", "local", f_walltime="48:00:00")
        f_plan_viking_48h = RunPlanner.createPlan(
            f_req_viking_48h, self.m_viking_profile
        )
        self.assertEqual(f_plan_viking_48h.scheduled_points[0].walltime, "48:00:00")
        self.assertIsNone(f_plan_viking_48h.scheduled_points[0].qos)

        # Viking with wallhour=48
        f_req_viking_wh48 = RunRequest("lsmio", "small", f_wallhour=48)
        f_plan_viking_wh48 = RunPlanner.createPlan(
            f_req_viking_wh48, self.m_viking_profile
        )
        for sp in f_plan_viking_wh48.scheduled_points:
            self.assertEqual(sp.walltime, "48:00:00")
            self.assertIsNone(sp.qos)

    def testBackendsModeFastWalltimeScaling(self) -> None:
        """Asserts backends mode walltime formula with --fast halves walltime, caps at 23h, and stays in standard QoS."""
        f_req_small_fast = RunRequest(
            f_target="lsmio",
            f_scale="small",
            f_mode="backends",
            f_fast=True,
        )
        f_plan_viking = RunPlanner.createPlan(f_req_small_fast, self.m_viking_profile)
        # Small scale has 9 points: 1, 2, 4, 8, 16, 24, 32, 40, 48
        # Formula: (2 + 4 * max(1, nodes // 3)) // 2, clamped to [1, 23]
        f_expected_walltimes = [
            "03:00:00",  # node 1: (2 + 4*1)//2 = 3
            "03:00:00",  # node 2: (2 + 4*1)//2 = 3
            "03:00:00",  # node 4: (2 + 4*1)//2 = 3
            "05:00:00",  # node 8: (2 + 4*2)//2 = 5
            "11:00:00",  # node 16: (2 + 4*5)//2 = 11
            "17:00:00",  # node 24: (2 + 4*8)//2 = 17
            "21:00:00",  # node 32: (2 + 4*10)//2 = 21
            "23:00:00",  # node 40: (2 + 4*13)//2 = 27 -> min(23, 27) = 23
            "23:00:00",  # node 48: (2 + 4*16)//2 = 33 -> min(23, 33) = 23
        ]
        self.assertEqual(len(f_plan_viking.scheduled_points), len(f_expected_walltimes))
        for idx, exp_wt in enumerate(f_expected_walltimes):
            self.assertEqual(
                f_plan_viking.scheduled_points[idx].walltime,
                exp_wt,
                f"Mismatch at point {idx} (nodes={f_plan_viking.scale_points[idx].nodes})",
            )

        # On ARCHER2, verify all 9 points stay in standard QoS under --fast
        f_plan_archer2 = RunPlanner.createPlan(f_req_small_fast, self.m_archer2_profile)
        for idx, sp in enumerate(f_plan_archer2.scheduled_points):
            self.assertEqual(
                sp.qos,
                "standard",
                f"Point {idx} (walltime={sp.walltime}) promoted to non-standard QoS",
            )

    def testVariantsModeFastWalltimeScaling(self) -> None:
        """Asserts variants mode walltime formula with --fast halves walltime and caps at 23h."""
        # 3 variants: total_runs = 4 -> (2 + 4*2)//2 = 5h
        f_req_3 = RunRequest(
            f_target="lsmio",
            f_scale="variants",
            f_variants=("footer", "btree", "mmap"),
            f_fast=True,
        )
        f_plan_3 = RunPlanner.createPlan(f_req_3, self.m_viking_profile)
        self.assertEqual(f_plan_3.scheduled_points[0].walltime, "05:00:00")

        # 24 variants: total_runs = 25 -> (2 + 25*2)//2 = 26 -> clamped to 23h
        f_vars_24 = tuple(f"var_{i}" for i in range(24))
        f_req_24 = RunRequest(
            f_target="lsmio",
            f_scale="variants",
            f_variants=f_vars_24,
            f_fast=True,
        )
        f_plan_24 = RunPlanner.createPlan(f_req_24, self.m_viking_profile)
        self.assertEqual(f_plan_24.scheduled_points[0].walltime, "23:00:00")

        # On ARCHER2, verify qos is standard
        f_plan_archer2 = RunPlanner.createPlan(f_req_24, self.m_archer2_profile)
        self.assertEqual(f_plan_archer2.scheduled_points[0].qos, "standard")

        # Versioned variants mode with --fast
        f_req_ver = RunRequest(
            f_target="lsmio",
            f_scale="variants",
            f_variants=("footer",),
            f_versioned=True,
            f_fast=True,
        )
        f_plan_ver = RunPlanner.createPlan(f_req_ver, self.m_viking_profile)
        # var_cnt = 1 -> total_runs = 2 -> (2 + 2*2)//2 = 3h
        self.assertEqual(f_plan_ver.scheduled_points[0].walltime, "03:00:00")

    def testStandardModeFastWalltimeScaling(self) -> None:
        """Asserts standard scaling mode with --fast halves raw walltime and caps at 23h."""
        # Bake: nodes 1, 2, 4, 8
        f_req_bake = RunRequest(f_target="lsmio", f_scale="bake", f_fast=True)
        f_plan_bake = RunPlanner.createPlan(f_req_bake, self.m_viking_profile)
        # raw_hours:
        # node 1: 2 + 0 = 2 -> 2 // 2 = 1
        # node 2: 2 + 0 = 2 -> 2 // 2 = 1
        # node 4: 2 + 1 = 3 -> 3 // 2 = 1
        # node 8: 2 + 2 = 4 -> 4 // 2 = 2
        self.assertEqual(f_plan_bake.scheduled_points[0].walltime, "01:00:00")
        self.assertEqual(f_plan_bake.scheduled_points[1].walltime, "01:00:00")
        self.assertEqual(f_plan_bake.scheduled_points[2].walltime, "01:00:00")
        self.assertEqual(f_plan_bake.scheduled_points[3].walltime, "02:00:00")

        # Large scale: point 7 has 256 tasks / 4 ppn = 64 nodes -> raw_hours = 2 + 64//3 = 23 -> 23 // 2 = 11
        f_req_large = RunRequest(f_target="lsmio", f_scale="large", f_fast=True)
        f_plan_large = RunPlanner.createPlan(f_req_large, self.m_viking_profile)
        self.assertEqual(f_plan_large.scheduled_points[7].walltime, "11:00:00")

        # High node count ceiling cap: 200 nodes -> raw_hours = 2 + 200//3 = 68 -> 68 // 2 = 34 -> capped at 23
        f_point_200 = ScalePoint(f_tasks=200, f_ppn=1, f_nodes=200)
        with patch.dict(RunPlanner.SCALE_MATRICES, {"custom": (f_point_200,)}):
            f_req_custom = RunRequest(f_target="lsmio", f_scale="custom", f_fast=True)
            f_plan_custom = RunPlanner.createPlan(f_req_custom, self.m_viking_profile)
            self.assertEqual(f_plan_custom.scheduled_points[0].walltime, "23:00:00")

    def testExplicitOverrideWithFastPrecedence(self) -> None:
        """Asserts user walltime override takes precedence over formula but is capped at 23h under --fast."""
        # 1. wallhour <= 23 honored as-is
        f_req_15 = RunRequest(
            f_target="lsmio",
            f_scale="small",
            f_mode="backends",
            f_wallhour=15,
            f_fast=True,
        )
        f_plan_15 = RunPlanner.createPlan(f_req_15, self.m_viking_profile)
        for sp in f_plan_15.scheduled_points:
            self.assertEqual(sp.walltime, "15:00:00")

        # 2. wallhour > 23 capped at 23h
        f_req_30 = RunRequest(
            f_target="lsmio",
            f_scale="small",
            f_mode="backends",
            f_wallhour=30,
            f_fast=True,
        )
        f_plan_30 = RunPlanner.createPlan(f_req_30, self.m_viking_profile)
        for sp in f_plan_30.scheduled_points:
            self.assertEqual(sp.walltime, "23:00:00")

        # 3. walltime string > 23h capped at 23:00:00
        f_req_str = RunRequest(
            f_target="lsmio",
            f_scale="baseline",
            f_walltime="36:00:00",
            f_fast=True,
        )
        f_plan_str = RunPlanner.createPlan(f_req_str, self.m_viking_profile)
        self.assertEqual(f_plan_str.scheduled_points[0].walltime, "23:00:00")

        # 4. walltime string < 1h clamped up to 01:00:00
        f_req_sub1h = RunRequest(
            f_target="lsmio",
            f_scale="baseline",
            f_walltime="00:20:00",
            f_fast=True,
        )
        f_plan_sub1h = RunPlanner.createPlan(f_req_sub1h, self.m_viking_profile)
        self.assertEqual(f_plan_sub1h.scheduled_points[0].walltime, "01:00:00")


# =============================================================================
# Chunk C08 Contract Tests: RunReporter, LaunchSpec, RankIdentity, RunRequest
# =============================================================================


class RunReporterContractTest(unittest.TestCase):
    """Exhaustive contract tests for RunReporter emission, streams, and callback handling."""

    def testEmitCallbackExceptionAndStreamWithoutFlush(self) -> None:
        """Validates callback exception suppression and streams without flush support."""

        def f_failing_callback(f_msg: str) -> None:
            raise RuntimeError("Callback failure")

        class DummyNoFlushStream:
            def __init__(self) -> None:
                self.m_written = []

            def write(self, f_s: str) -> None:
                self.m_written.append(f_s)

        f_stream = DummyNoFlushStream()
        f_reporter = RunReporter(f_stream=f_stream, f_callback=f_failing_callback)
        # Lines 126, 127: callback exception caught; Arc [131, -119]: stream has no flush
        f_reporter.emit("line 1")
        self.assertEqual(f_reporter.lines, ["line 1"])
        self.assertEqual(f_reporter.output, "line 1\n")
        self.assertEqual(f_stream.m_written, ["line 1\n"])

    def testReportCompletionStateVariations(self) -> None:
        """Validates reportCompletion string branches and non-string/non-enum fallback."""
        # 1. String state (lines 172, 173; arcs [170, 172], [172, 173])
        f_rep_str = RunReporter(f_stream=io.StringIO())
        f_rep_str.reportCompletion("completed", 0)
        self.assertIn("Final State: COMPLETED", f_rep_str.output)
        self.assertIn("Exit Code: 0", f_rep_str.output)

        # 2. Non-string, non-enum fallback (line 175; arc [172, 175])
        f_rep_other = RunReporter(f_stream=io.StringIO())
        f_rep_other.reportCompletion(404, 1)
        self.assertIn("Final State: 404", f_rep_other.output)
        self.assertIn("Exit Code: 1", f_rep_other.output)

    def testCallableInterfaceSingleStringArg(self) -> None:
        """Validates __call__ with a single positional string argument."""
        f_rep = RunReporter(f_stream=io.StringIO())
        # Lines 182, 183; arc [182, 183]
        f_rep("Progress update message")
        self.assertEqual(f_rep.lines, ["Progress update message"])

    def testCallableInterfaceRunIdentityKwargs(self) -> None:
        """Validates __call__ run identity keyword arguments dispatch."""
        # Lines 184-187; arcs [182, 184], [184, 185]
        f_rep = RunReporter(f_stream=io.StringIO())
        f_rep(f_run_id="run-c08-001", f_run_root="/tmp/test_root")
        self.assertIn("Run ID: run-c08-001", f_rep.output)
        self.assertIn("Run Root: /tmp/test_root", f_rep.output)

        # Alternative kwargs without f_ prefix
        f_rep2 = RunReporter(f_stream=io.StringIO())
        f_rep2(run_id="run-c08-002", run_root="/tmp/test_root2")
        self.assertIn("Run ID: run-c08-002", f_rep2.output)

    def testCallableInterfacePointSubmissionKwargs(self) -> None:
        """Validates __call__ scale point submission keyword arguments dispatch."""
        # Lines 188-192; arcs [184, 188], [188, 189]
        f_rep = RunReporter(f_stream=io.StringIO())
        f_rep(f_point_id="p1", f_token="tok-abc", f_job_id="job-12345")
        self.assertIn("Point p1 Correlation Token: tok-abc", f_rep.output)
        self.assertIn("Point p1 Job ID: job-12345", f_rep.output)

        # Alternative kwargs without f_ prefix
        f_rep2 = RunReporter(f_stream=io.StringIO())
        f_rep2(point_id="p2", token="tok-xyz", job_id="job-67890")
        self.assertIn("Point p2 Correlation Token: tok-xyz", f_rep2.output)

    def testCallableInterfaceCompletionKwargsAndFallthrough(self) -> None:
        """Validates __call__ completion kwargs and unmatched arguments fallthrough."""
        # Lines 193-196; arcs [188, 193], [193, 194]
        f_rep = RunReporter(f_stream=io.StringIO())
        f_rep(f_final_state="failed", f_exit_code=2)
        self.assertIn("Final State: FAILED", f_rep.output)
        self.assertIn("Exit Code: 2", f_rep.output)

        # Fallthrough on unmatched call: arc [193, -181]
        f_rep2 = RunReporter(f_stream=io.StringIO())
        f_rep2(unrecognized_arg=True)
        self.assertEqual(f_rep2.lines, [])


class LaunchSpecContractTest(unittest.TestCase):
    """Exhaustive contract tests for LaunchSpec validation, immutability, and serialization."""

    def testLaunchSpecModeValidation(self) -> None:
        """Validates string mode normalization and error guards for mode and executable."""
        # 1. Valid string mode (lines 239, 240; arc [238, 239])
        f_spec = LaunchSpec("direct", "lsmiotool-worker")
        self.assertEqual(f_spec.mode, LaunchMode.DIRECT)

        # 2. Invalid string mode (lines 241, 242)
        with self.assertRaises(PlanValidationError) as f_ctx:
            LaunchSpec("invalid_mode", "worker")
        self.assertIn("Invalid LaunchMode string: 'invalid_mode'", str(f_ctx.exception))

        # 3. Invalid non-string non-LaunchMode type (line 246; arc [243, 246])
        for f_bad_mode in (123, None, [LaunchMode.DIRECT]):
            with self.subTest(bad_mode=f_bad_mode):
                with self.assertRaises(PlanValidationError) as f_ctx2:
                    LaunchSpec(f_bad_mode, "worker")
                self.assertIn(
                    "LaunchMode must be LaunchMode or str", str(f_ctx2.exception)
                )

        # 4. Empty or invalid executable_or_worker (line 251; arc [250, 251])
        for f_bad_exec in ("", None, 12345):
            with self.subTest(bad_exec=f_bad_exec):
                with self.assertRaises(PlanValidationError) as f_ctx3:
                    LaunchSpec("direct", f_bad_exec)
                self.assertIn(
                    "executable_or_worker must be a non-empty string",
                    str(f_ctx3.exception),
                )

    def testLaunchSpecImmutabilityAndSlotMutation(self) -> None:
        """Validates frozen immutability and unfrozen slot mutation/deletion via __new__."""
        f_spec = LaunchSpec("direct", "worker")

        # Frozen modification and deletion (lines 269, 270; arc [269, 270])
        with self.assertRaises(AttributeError):
            f_spec.m_mode = LaunchMode.SLURM
        with self.assertRaises(AttributeError):
            del f_spec.m_mode

        # Unfrozen mutation via __new__ (line 266; arc [264, 266])
        # Note: Must use an existing __slots__ attribute (e.g. m_mode) because arbitrary attributes are disallowed
        f_unfrozen = LaunchSpec.__new__(LaunchSpec)
        f_unfrozen.m_mode = LaunchMode.DIRECT
        self.assertEqual(f_unfrozen.m_mode, LaunchMode.DIRECT)

        # Unfrozen deletion via __new__ (line 273; arc [269, 273])
        del f_unfrozen.m_mode
        self.assertFalse(hasattr(f_unfrozen, "m_mode"))

    def testLaunchSpecSerializationAndEquality(self) -> None:
        """Validates toDict, __repr__, and __eq__ comparisons."""
        f_spec = LaunchSpec("direct", "worker", ["--flag", "val"], ["res.csv"])

        # toDict serialization (line 292)
        f_dict = f_spec.toDict()
        self.assertEqual(
            f_dict,
            {
                "mode": "direct",
                "executable_or_worker": "worker",
                "arguments": ["--flag", "val"],
                "expected_results": ["res.csv"],
            },
        )

        # __repr__ string formatting (line 300)
        self.assertIn("LaunchSpec(mode=<LaunchMode.DIRECT: 'direct'>", repr(f_spec))

        # __eq__ identical LaunchSpec (lines 308, 309; arc [308, 309])
        f_spec_same = LaunchSpec(
            LaunchMode.DIRECT, "worker", ["--flag", "val"], ["res.csv"]
        )
        self.assertEqual(f_spec, f_spec_same)

        # __eq__ different LaunchSpec
        f_spec_diff = LaunchSpec("direct", "other_worker")
        self.assertNotEqual(f_spec, f_spec_diff)

        # __eq__ non-LaunchSpec object (line 315; arc [308, 315])
        self.assertFalse(f_spec == "not_a_launch_spec")
        self.assertFalse(f_spec == 42)


class RankIdentityContractTest(unittest.TestCase):
    """Exhaustive contract tests for RankIdentity validation, immutability, and properties."""

    def testRankIdentityValidation(self) -> None:
        """Validates input guards for node_rank and local_rank."""
        # 1. Invalid node_rank (line 336; arc [333, 336])
        for f_bad_node in ("", None, 1.5):
            with self.subTest(bad_node=f_bad_node):
                with self.assertRaises(PlanValidationError) as f_ctx:
                    RankIdentity(0, f_bad_node)
                self.assertIn(
                    "node_rank must be a non-empty string or integer",
                    str(f_ctx.exception),
                )

        # 2. Invalid local_rank (line 341; arc [340, 341])
        for f_bad_local in (-1, 1.5, "0"):
            with self.subTest(bad_local=f_bad_local):
                with self.assertRaises(PlanValidationError) as f_ctx:
                    RankIdentity(0, "node0", f_bad_local)
                self.assertIn(
                    "local_rank must be a non-negative integer or None",
                    str(f_ctx.exception),
                )

    def testRankIdentityImmutabilityAndSlotMutation(self) -> None:
        """Validates frozen immutability and unfrozen slot mutation/deletion via __new__."""
        f_id = RankIdentity(0, "node0", 0)

        # Frozen modification and deletion (lines 356, 357; arc [356, 357])
        with self.assertRaises(AttributeError):
            f_id.m_global_rank = 1
        with self.assertRaises(AttributeError):
            del f_id.m_global_rank

        # Unfrozen mutation via __new__ (line 353; arc [351, 353])
        # Note: Must use an existing __slots__ attribute (e.g. m_global_rank)
        f_unfrozen = RankIdentity.__new__(RankIdentity)
        f_unfrozen.m_global_rank = 0
        self.assertEqual(f_unfrozen.m_global_rank, 0)

        # Unfrozen deletion via __new__ (line 360; arc [356, 360])
        del f_unfrozen.m_global_rank
        self.assertFalse(hasattr(f_unfrozen, "m_global_rank"))

    def testRankIdentityPropertiesSerializationAndEquality(self) -> None:
        """Validates property accessors, node alias, toDict, __repr__, and __eq__."""
        f_id = RankIdentity(0, "node42", 1)

        # Property accessors and node alias (line 372)
        self.assertEqual(f_id.global_rank, 0)
        self.assertEqual(f_id.node_rank, "node42")
        self.assertEqual(f_id.node, "node42")
        self.assertEqual(f_id.local_rank, 1)

        # toDict serialization
        self.assertEqual(
            f_id.toDict(),
            {"global_rank": 0, "node_rank": "node42", "local_rank": 1},
        )

        # __repr__ formatting (line 386)
        self.assertEqual(
            repr(f_id),
            "RankIdentity(global_rank=0, node_rank='node42', local_rank=1)",
        )

        # __eq__ matching and non-matching objects (line 399; arc [393, 399])
        f_id_same = RankIdentity(0, "node42", 1)
        self.assertEqual(f_id, f_id_same)
        self.assertNotEqual(f_id, RankIdentity(1, "node42", 1))
        self.assertFalse(f_id == "not_a_rank_identity")
        self.assertFalse(f_id == 0)


class RunRequestContractTest(unittest.TestCase):
    """Exhaustive contract tests for RunRequest validation guards, immutability, and serialization."""

    def testRunRequestValidationTargetScaleMode(self) -> None:
        """Validates non-empty string guards for target, scale, and mode."""
        # 1. Target invalid (line 452; arc [451, 452])
        for f_bad_target in ("", "   ", None, 123):
            with self.subTest(bad_target=f_bad_target):
                with self.assertRaises(PlanValidationError) as f_ctx:
                    RunRequest(f_bad_target, "small")
                self.assertIn("target must be a non-empty string", str(f_ctx.exception))

        # 2. Scale invalid (line 456; arc [455, 456])
        for f_bad_scale in ("", "   ", None, 123):
            with self.subTest(bad_scale=f_bad_scale):
                with self.assertRaises(PlanValidationError) as f_ctx:
                    RunRequest("lsmio", f_bad_scale)
                self.assertIn("scale must be a non-empty string", str(f_ctx.exception))

        # 3. Mode invalid (line 460; arc [459, 460])
        for f_bad_mode in ("", "   ", 123):
            with self.subTest(bad_mode=f_bad_mode):
                with self.assertRaises(PlanValidationError) as f_ctx:
                    RunRequest("lsmio", "small", f_mode=f_bad_mode)
                self.assertIn("mode must be a non-empty string", str(f_ctx.exception))

    def testRunRequestValidationBackendsAndDefault(self) -> None:
        """Validates backends sequence type guard and empty sequence fallback in backends mode."""
        # 1. Non-sequence backends (line 479; arc [478, 479])
        for f_bad_backends in ("native", 123, {"native": 1}):
            with self.subTest(bad_backends=f_bad_backends):
                with self.assertRaises(PlanValidationError) as f_ctx:
                    RunRequest("lsmio", "small", f_backends=f_bad_backends)
                self.assertIn(
                    "backends must be a sequence of strings", str(f_ctx.exception)
                )

        # 2. Empty backends sequence with mode="backends" defaults to target defaults (line 486; arc [485, 486])
        f_req = RunRequest("lsmio", "small", f_mode="backends", f_backends=[])
        self.assertEqual(f_req.backends, DEFAULT_LSMIO_BACKENDS)

    def testRunRequestValidationFlagsAndSetup(self) -> None:
        """Validates ssd, setup, variants, archive, resume, out_dir, wallhour, and fast."""
        # 1. ssd boolean guard (line 493; arc [492, 493])
        with self.assertRaises(PlanValidationError) as f_ctx:
            RunRequest("lsmio", "small", f_ssd="true")
        self.assertIn("ssd must be a boolean", str(f_ctx.exception))

        # 2. setup non-empty string guard (line 497; arc [494, 497])
        for f_bad_setup in ("", "   ", 123):
            with self.subTest(bad_setup=f_bad_setup):
                with self.assertRaises(PlanValidationError) as f_ctx:
                    RunRequest("lsmio", "small", f_setup=f_bad_setup)
                self.assertIn(
                    "setup must be a non-empty string or None", str(f_ctx.exception)
                )

        # 3. variants sequence guard (line 502; arc [501, 502])
        with self.assertRaises(PlanValidationError) as f_ctx:
            RunRequest("lsmio", "small", f_variants="var1")
        self.assertIn(
            "variants must be a sequence of variant strings or None",
            str(f_ctx.exception),
        )

        # 4. empty variants sequence fallback (line 512; arc [511, 512])
        f_req_empty_var = RunRequest("lsmio", "small", f_variants=[])
        self.assertEqual(f_req_empty_var.variants, (None,))
        self.assertIsNone(f_req_empty_var.variant)

        # 5. archive boolean guard (line 523; arc [522, 523])
        with self.assertRaises(PlanValidationError) as f_ctx:
            RunRequest("lsmio", "small", f_archive="yes")
        self.assertIn("archive must be a boolean or None", str(f_ctx.exception))

        # 6. resume boolean guard (line 527; arc [526, 527])
        with self.assertRaises(PlanValidationError) as f_ctx:
            RunRequest("lsmio", "small", f_resume="true")
        self.assertIn("resume must be a boolean", str(f_ctx.exception))

        # 7. out_dir string or Path guard (line 530; arc [529, 530])
        for f_bad_out in ("", "   ", 12345):
            with self.subTest(bad_out=f_bad_out):
                with self.assertRaises(PlanValidationError) as f_ctx:
                    RunRequest("lsmio", "small", f_out_dir=f_bad_out)
                self.assertIn(
                    "out_dir must be a non-empty string or Path", str(f_ctx.exception)
                )

        # 8. wallhour positive integer guard (line 539; arc [538, 539])
        for f_bad_wh in (0, -3, "5", 1.5):
            with self.subTest(bad_wh=f_bad_wh):
                with self.assertRaises(PlanValidationError) as f_ctx:
                    RunRequest("lsmio", "small", f_wallhour=f_bad_wh)
                self.assertIn(
                    "wallhour must be a positive integer", str(f_ctx.exception)
                )

        # 9. fast boolean guard (line 548; arc [547, 548])
        with self.assertRaises(PlanValidationError) as f_ctx:
            RunRequest("lsmio", "small", f_fast=1)
        self.assertIn("fast must be a boolean", str(f_ctx.exception))

    def testRunRequestImmutabilityAndSlotMutation(self) -> None:
        """Validates frozen immutability and unfrozen slot mutation/deletion via __new__."""
        f_req = RunRequest("lsmio", "small")

        # Frozen modification and deletion (lines 598, 599; arc [598, 599])
        with self.assertRaises(AttributeError):
            f_req.m_target = "ior"
        with self.assertRaises(AttributeError):
            del f_req.m_target

        # Unfrozen mutation via __new__ (line 595; arc [593, 595])
        # Note: Must use an existing __slots__ attribute (e.g. m_target)
        f_unfrozen = RunRequest.__new__(RunRequest)
        f_unfrozen.m_target = "lsmio"
        self.assertEqual(f_unfrozen.m_target, "lsmio")

        # Unfrozen deletion via __new__ (line 602; arc [598, 602])
        del f_unfrozen.m_target
        self.assertFalse(hasattr(f_unfrozen, "m_target"))

    def testRunRequestEffectiveArchive(self) -> None:
        """Validates effective_archive resolution when explicit archive is None with non-standard and standard variants."""
        # 1. Non-standard variant triggers any() true branch (line 654)
        f_req = RunRequest("lsmio", "small", f_variant="experimental_engine")
        self.assertIsNone(f_req.archive)
        self.assertTrue(f_req.effective_archive)

        # 2. Standard variants trigger any() false branch falling through to line 655 (line 655; arc [651, 655])
        f_req_std = RunRequest("lsmio", "small", f_variants=["default"])
        self.assertFalse(f_req_std.effective_archive)
        f_req_multi_std = RunRequest("lsmio", "small", f_variants=["default", "base"])
        self.assertTrue(f_req_multi_std.effective_archive)

    def testRunRequestToDictReprAndEquality(self) -> None:
        """Validates toDict serialization options, __repr__, and __eq__ non-RunRequest comparison."""
        f_req = RunRequest(
            f_target="lsmio",
            f_scale="small",
            f_variants=("var1", "var2"),
            f_archive=True,
            f_resume=True,
            f_out_dir="/tmp/custom_out",
            f_versioned=True,
            f_fast=True,
        )

        # toDict serialization (lines 723, 725, 727, 729, 735; arcs [720, 723], [724, 725], [726, 727], [728, 729], [734, 735])
        f_dict = f_req.toDict()
        self.assertEqual(f_dict["variants"], ["var1", "var2"])
        self.assertTrue(f_dict["archive"])
        self.assertTrue(f_dict["resume"])
        self.assertEqual(f_dict["out_dir"], "/tmp/custom_out")
        self.assertTrue(f_dict["versioned"])
        self.assertTrue(f_dict["fast"])

        # __repr__ formatting (line 745)
        f_repr = repr(f_req)
        self.assertIn("RunRequest(target='lsmio'", f_repr)
        self.assertIn("variants=('var1', 'var2')", f_repr)

        # __eq__ comparisons (line 785; arc [766, 785])
        f_req_same = RunRequest(
            f_target="lsmio",
            f_scale="small",
            f_variants=("var1", "var2"),
            f_archive=True,
            f_resume=True,
            f_out_dir="/tmp/custom_out",
            f_versioned=True,
            f_fast=True,
        )
        self.assertEqual(f_req, f_req_same)
        self.assertFalse(f_req == "not_a_run_request")
        self.assertFalse(f_req == 42)


class CombinationContractTest(unittest.TestCase):
    """Exhaustive contract tests for Combination validation, immutability, properties, and equality."""

    def testCombinationArgumentValidation(self) -> None:
        """Validates processes, block_size, stripe_count, block_bytes, key_count, segment_count validation guards."""
        # 1. processes positive integer validation (line 811; arc [810, 811])
        with self.assertRaises(PlanValidationError):
            Combination(0, "4M", 1, 4194304, 1000, 1)
        with self.assertRaises(PlanValidationError):
            Combination(-1, "4M", 1, 4194304, 1000, 1)
        with self.assertRaises(PlanValidationError):
            Combination("1", "4M", 1, 4194304, 1000, 1)  # type: ignore

        # 2. block_size non-empty string validation (line 815; arc [814, 815])
        with self.assertRaises(PlanValidationError):
            Combination(1, "", 1, 4194304, 1000, 1)
        with self.assertRaises(PlanValidationError):
            Combination(1, "   ", 1, 4194304, 1000, 1)
        with self.assertRaises(PlanValidationError):
            Combination(1, 4096, 1, 4194304, 1000, 1)  # type: ignore

        # 3. stripe_count positive integer validation (line 819; arc [818, 819])
        with self.assertRaises(PlanValidationError):
            Combination(1, "4M", 0, 4194304, 1000, 1)
        with self.assertRaises(PlanValidationError):
            Combination(1, "4M", -2, 4194304, 1000, 1)

        # 4. block_bytes positive integer validation (line 823; arc [822, 823])
        with self.assertRaises(PlanValidationError):
            Combination(1, "4M", 1, 0, 1000, 1)
        with self.assertRaises(PlanValidationError):
            Combination(1, "4M", 1, -1024, 1000, 1)

        # 5. key_count positive integer validation (line 827; arc [826, 827])
        with self.assertRaises(PlanValidationError):
            Combination(1, "4M", 1, 4194304, 0, 1)
        with self.assertRaises(PlanValidationError):
            Combination(1, "4M", 1, 4194304, -5, 1)

        # 6. segment_count positive integer validation (line 831; arc [830, 831])
        with self.assertRaises(PlanValidationError):
            Combination(1, "4M", 1, 4194304, 1000, 0)
        with self.assertRaises(PlanValidationError):
            Combination(1, "4M", 1, 4194304, 1000, -1)

    def testCombinationImmutabilityAndUnfrozenMutation(self) -> None:
        """Validates frozen immutability on modify/delete and unfrozen mutation/deletion via __new__."""
        f_comb = Combination(1, "4M", 1, 4194304, 1000, 1)

        # Frozen modify raises AttributeError (line 845)
        with self.assertRaises(AttributeError) as f_ctx:
            f_comb.m_processes = 2
        self.assertIn("Cannot modify immutable Combination", str(f_ctx.exception))

        # Frozen delete raises AttributeError (lines 849, 850; arc [849, 850])
        with self.assertRaises(AttributeError) as f_ctx_del:
            del f_comb.m_processes
        self.assertIn(
            "Cannot delete attribute from immutable Combination",
            str(f_ctx_del.exception),
        )

        # Unfrozen mutation via __new__ (line 846; arc [844, 846])
        f_unfrozen = Combination.__new__(Combination)
        f_unfrozen.m_processes = 8
        self.assertEqual(f_unfrozen.m_processes, 8)

        # Unfrozen deletion via __new__ (line 853; arc [849, 853])
        del f_unfrozen.m_processes
        self.assertFalse(hasattr(f_unfrozen, "m_processes"))

    def testCombinationEqualityAndSerialization(self) -> None:
        """Validates toDict, __repr__, and __eq__ non-Combination comparison branch."""
        f_comb = Combination(1, "4M", 2, 4194304, 1000, 1)
        self.assertEqual(f_comb.name, "c2_b4M")
        self.assertEqual(f_comb.processes, 1)
        self.assertEqual(f_comb.block_size, "4M")
        self.assertEqual(f_comb.stripe_count, 2)
        self.assertEqual(f_comb.block_bytes, 4194304)
        self.assertEqual(f_comb.key_count, 1000)
        self.assertEqual(f_comb.segment_count, 1)

        f_dict = f_comb.toDict()
        self.assertEqual(
            f_dict,
            {
                "processes": 1,
                "block_size": "4M",
                "stripe_count": 2,
                "block_bytes": 4194304,
                "key_count": 1000,
                "segment_count": 1,
            },
        )
        self.assertIn("Combination(processes=1, block_size='4M'", repr(f_comb))

        # __eq__ branch to False against non-Combination (line 913; arc [904, 913])
        self.assertFalse(f_comb == "not_a_combination")
        self.assertFalse(f_comb == 42)
        self.assertFalse(f_comb is None)
        self.assertFalse(f_comb == {"processes": 1})
        self.assertEqual(f_comb, Combination(1, "4M", 2, 4194304, 1000, 1))


class ScalePointContractTest(unittest.TestCase):
    """Exhaustive contract tests for ScalePoint immutability, property aliases, and equality."""

    def testScalePointImmutabilityAndUnfrozenMutation(self) -> None:
        """Validates frozen immutability and unfrozen mutation/deletion via __new__."""
        f_sp = ScalePoint(4, 4, 1)

        # Frozen modify raises AttributeError (line 944)
        with self.assertRaises(AttributeError) as f_ctx:
            f_sp.m_tasks = 8
        self.assertIn("Cannot modify immutable ScalePoint", str(f_ctx.exception))

        # Frozen delete raises AttributeError (lines 948, 949; arc [948, 949])
        with self.assertRaises(AttributeError) as f_ctx_del:
            del f_sp.m_tasks
        self.assertIn(
            "Cannot delete attribute from immutable ScalePoint",
            str(f_ctx_del.exception),
        )

        # Unfrozen mutation via __new__ (line 945; arc [943, 945])
        f_unfrozen = ScalePoint.__new__(ScalePoint)
        f_unfrozen.m_tasks = 16
        self.assertEqual(f_unfrozen.m_tasks, 16)

        # Unfrozen deletion via __new__ (line 952; arc [948, 952])
        del f_unfrozen.m_tasks
        self.assertFalse(hasattr(f_unfrozen, "m_tasks"))

    def testScalePointPropertyAliases(self) -> None:
        """Validates task_count, tasks_per_node, and node_count property aliases."""
        f_sp = ScalePoint(f_tasks=16, f_ppn=4, f_nodes=4)
        # Property aliases (lines 968, 972, 976)
        self.assertEqual(f_sp.task_count, 16)
        self.assertEqual(f_sp.tasks_per_node, 4)
        self.assertEqual(f_sp.node_count, 4)

    def testScalePointEqualityAgainstNonScalePoint(self) -> None:
        """Validates __eq__ returns False for non-ScalePoint comparisons."""
        f_sp = ScalePoint(1, 1, 1)
        self.assertFalse(f_sp == "not_a_scale_point")
        self.assertFalse(f_sp == 100)
        self.assertFalse(f_sp is None)
        self.assertFalse(f_sp == (1, 1, 1))
        self.assertEqual(f_sp, ScalePoint(1, 1, 1))


class ScheduledPointResourcesContractTest(unittest.TestCase):
    """Exhaustive contract tests for ScheduledPointResources validation, immutability, repr, and equality."""

    def testScheduledPointResourcesArgumentValidation(self) -> None:
        """Validates walltime, select_chunks, ncpus, and mpiprocs validation guards."""
        # 1. walltime non-empty string validation (line 1033; arc [1032, 1033])
        with self.assertRaises(PlanValidationError):
            ScheduledPointResources("")
        with self.assertRaises(PlanValidationError):
            ScheduledPointResources("   ")
        with self.assertRaises(PlanValidationError):
            ScheduledPointResources(120)  # type: ignore

        # 2. select_chunks positive integer validation (line 1039; arc [1036, 1039])
        with self.assertRaises(PlanValidationError):
            ScheduledPointResources("01:00:00", f_select_chunks=0)
        with self.assertRaises(PlanValidationError):
            ScheduledPointResources("01:00:00", f_select_chunks=-1)
        with self.assertRaises(PlanValidationError):
            ScheduledPointResources("01:00:00", f_select_chunks="2")  # type: ignore

        # 3. ncpus positive integer validation (line 1043; arc [1042, 1043])
        with self.assertRaises(PlanValidationError):
            ScheduledPointResources("01:00:00", f_ncpus=0)
        with self.assertRaises(PlanValidationError):
            ScheduledPointResources("01:00:00", f_ncpus=-16)
        with self.assertRaises(PlanValidationError):
            ScheduledPointResources("01:00:00", f_ncpus="16")  # type: ignore

        # 4. mpiprocs positive integer validation (line 1049; arc [1046, 1049])
        with self.assertRaises(PlanValidationError):
            ScheduledPointResources("01:00:00", f_mpiprocs=0)
        with self.assertRaises(PlanValidationError):
            ScheduledPointResources("01:00:00", f_mpiprocs=-4)
        with self.assertRaises(PlanValidationError):
            ScheduledPointResources("01:00:00", f_mpiprocs="4")  # type: ignore

    def testScheduledPointResourcesImmutabilityAndUnfrozenMutation(self) -> None:
        """Validates frozen immutability and unfrozen mutation/deletion via __new__."""
        f_res = ScheduledPointResources(
            "01:00:00", f_select_chunks=2, f_ncpus=16, f_mpiprocs=4
        )

        # Frozen modify raises AttributeError (line 1068)
        with self.assertRaises(AttributeError) as f_ctx:
            f_res.m_walltime = "02:00:00"
        self.assertIn(
            "Cannot modify immutable ScheduledPointResources", str(f_ctx.exception)
        )

        # Frozen delete raises AttributeError (lines 1072, 1073; arc [1072, 1073])
        with self.assertRaises(AttributeError) as f_ctx_del:
            del f_res.m_walltime
        self.assertIn(
            "Cannot delete attribute from immutable ScheduledPointResources",
            str(f_ctx_del.exception),
        )

        # Unfrozen mutation via __new__ (line 1069; arc [1067, 1069])
        f_unfrozen = ScheduledPointResources.__new__(ScheduledPointResources)
        f_unfrozen.m_walltime = "00:30:00"
        self.assertEqual(f_unfrozen.m_walltime, "00:30:00")

        # Unfrozen deletion via __new__ (line 1076; arc [1072, 1076])
        del f_unfrozen.m_walltime
        self.assertFalse(hasattr(f_unfrozen, "m_walltime"))

    def testScheduledPointResourcesReprAndEquality(self) -> None:
        """Validates __repr__ formatting and __eq__ non-ScheduledPointResources comparison branch."""
        f_res = ScheduledPointResources(
            "01:00:00", f_select_chunks=2, f_ncpus=16, f_mpiprocs=4
        )

        # __repr__ formatting (line 1138)
        f_repr = repr(f_res)
        self.assertIn("ScheduledPointResources(walltime='01:00:00'", f_repr)
        self.assertIn("select_chunks=2", f_repr)
        self.assertIn("ncpus=16", f_repr)
        self.assertIn("mpiprocs=4", f_repr)

        # __eq__ branch to False against non-ScheduledPointResources (line 1162; arc [1148, 1162])
        self.assertFalse(f_res == "not_resources")
        self.assertFalse(f_res == 42)
        self.assertFalse(f_res is None)
        self.assertFalse(f_res == {"walltime": "01:00:00"})

        f_res_same = ScheduledPointResources(
            "01:00:00", f_select_chunks=2, f_ncpus=16, f_mpiprocs=4
        )
        self.assertEqual(f_res, f_res_same)


class RunPlanContractTest(unittest.TestCase):
    """Exhaustive contract tests for RunPlan validation guards, LMP tuning, immutability, repr, and equality."""

    def setUp(self) -> None:
        f_env_path = os.path.normpath(
            os.path.join(
                os.path.dirname(__file__), "..", "..", "etc", "environments.json"
            )
        )
        f_doc = ProfileLoader.load(f_env_path)
        f_reg = EnvironmentResolver.resolveRegistry(
            f_doc, f_user="alice", f_home="/home/alice"
        )
        self.m_profile = f_reg.getProfile("viking")
        self.m_req = RunRequest("lsmio", "small")
        self.m_sp = ScalePoint(1, 1, 1)
        self.m_comb = Combination(1, "4M", 1, 4194304, 1000, 1)
        self.m_sched = ScheduledPointResources("01:00:00")
        self.m_token = "tok_test_01"
        self.m_ts = "2026-11-07T12:00:00Z"

    def testRunPlanBasicArgumentValidation(self) -> None:
        """Validates run_id, request, profile, scale_points, combinations, scheduled_points, tokens, timestamp guards."""
        # 1. run_id non-empty string validation (line 1194; arc [1193, 1194])
        with self.assertRaises(PlanValidationError):
            RunPlan(
                "",
                self.m_req,
                self.m_profile,
                [self.m_sp],
                [self.m_comb],
                [self.m_sched],
                [self.m_token],
                self.m_ts,
            )
        with self.assertRaises(PlanValidationError):
            RunPlan(
                "   ",
                self.m_req,
                self.m_profile,
                [self.m_sp],
                [self.m_comb],
                [self.m_sched],
                [self.m_token],
                self.m_ts,
            )
        with self.assertRaises(PlanValidationError):
            RunPlan(
                123,
                self.m_req,
                self.m_profile,
                [self.m_sp],
                [self.m_comb],
                [self.m_sched],
                [self.m_token],
                self.m_ts,
            )  # type: ignore

        # 2. request RunRequest type validation (line 1198; arc [1197, 1198])
        with self.assertRaises(PlanValidationError):
            RunPlan(
                "r1",
                "not_a_request",
                self.m_profile,
                [self.m_sp],
                [self.m_comb],
                [self.m_sched],
                [self.m_token],
                self.m_ts,
            )  # type: ignore

        # 3. profile SiteProfile type validation (line 1202; arc [1201, 1202])
        with self.assertRaises(PlanValidationError):
            RunPlan(
                "r1",
                self.m_req,
                "not_a_profile",
                [self.m_sp],
                [self.m_comb],
                [self.m_sched],
                [self.m_token],
                self.m_ts,
            )  # type: ignore

        # 4. scale_points non-empty sequence validation (line 1206; arc [1205, 1206])
        with self.assertRaises(PlanValidationError):
            RunPlan(
                "r1",
                self.m_req,
                self.m_profile,
                [],
                [self.m_comb],
                [self.m_sched],
                [self.m_token],
                self.m_ts,
            )

        # 5. combinations non-empty sequence validation (line 1208; arc [1207, 1208])
        with self.assertRaises(PlanValidationError):
            RunPlan(
                "r1",
                self.m_req,
                self.m_profile,
                [self.m_sp],
                [],
                [self.m_sched],
                [self.m_token],
                self.m_ts,
            )

        # 6. scheduled_points count equal scale_points count (line 1210; arc [1209, 1210])
        with self.assertRaises(PlanValidationError):
            RunPlan(
                "r1",
                self.m_req,
                self.m_profile,
                [self.m_sp],
                [self.m_comb],
                [],
                [self.m_token],
                self.m_ts,
            )
        with self.assertRaises(PlanValidationError):
            RunPlan(
                "r1",
                self.m_req,
                self.m_profile,
                [self.m_sp],
                [self.m_comb],
                [self.m_sched, self.m_sched],
                [self.m_token],
                self.m_ts,
            )

        # 7. tokens count equal scale_points count (line 1214; arc [1213, 1214])
        with self.assertRaises(PlanValidationError):
            RunPlan(
                "r1",
                self.m_req,
                self.m_profile,
                [self.m_sp],
                [self.m_comb],
                [self.m_sched],
                [],
                self.m_ts,
            )
        with self.assertRaises(PlanValidationError):
            RunPlan(
                "r1",
                self.m_req,
                self.m_profile,
                [self.m_sp],
                [self.m_comb],
                [self.m_sched],
                [self.m_token, "tok_02"],
                self.m_ts,
            )

        # 8. manifest_timestamp non-empty string validation (line 1221; arc [1217, 1221])
        with self.assertRaises(PlanValidationError):
            RunPlan(
                "r1",
                self.m_req,
                self.m_profile,
                [self.m_sp],
                [self.m_comb],
                [self.m_sched],
                [self.m_token],
                "",
            )
        with self.assertRaises(PlanValidationError):
            RunPlan(
                "r1",
                self.m_req,
                self.m_profile,
                [self.m_sp],
                [self.m_comb],
                [self.m_sched],
                [self.m_token],
                "   ",
            )
        with self.assertRaises(PlanValidationError):
            RunPlan(
                "r1",
                self.m_req,
                self.m_profile,
                [self.m_sp],
                [self.m_comb],
                [self.m_sched],
                [self.m_token],
                12345,
            )  # type: ignore

    def testRunPlanLmpDefaultTuningWhenNone(self) -> None:
        """Validates auto-populating lmp_task_tuning when f_lmp_task_tuning is None for LMP target."""
        f_req_lmp = RunRequest("lmp", "small")
        f_plan_lmp = RunPlan(
            "r_lmp",
            f_req_lmp,
            self.m_profile,
            [self.m_sp],
            [self.m_comb],
            [self.m_sched],
            [self.m_token],
            self.m_ts,
            f_lmp_task_tuning=None,
        )
        # Line 1229; Arc [1228, 1229]
        self.assertEqual(
            f_plan_lmp.lmp_task_tuning,
            {"1": {"replication": 4, "buffer_size_mb": 32}},
        )

    def testRunPlanLmpTuningValidationErrors(self) -> None:
        """Validates all LMP tuning validation failure modes."""
        f_req_lmp = RunRequest("lmp", "small")

        # 1. f_lmp_task_tuning not a mapping (line 1235; arc [1234, 1235])
        with self.assertRaises(PlanValidationError) as f_ctx:
            RunPlan(
                "r_lmp",
                f_req_lmp,
                self.m_profile,
                [self.m_sp],
                [self.m_comb],
                [self.m_sched],
                [self.m_token],
                self.m_ts,
                f_lmp_task_tuning=[1, 2],
            )  # type: ignore
        self.assertIn("lmp_task_tuning must be a mapping", str(f_ctx.exception))

        # 2. Key format invalid (leading zeroes, non-digits, <= 0) (line 1247; arc [1241, 1247])
        with self.assertRaises(PlanValidationError):
            RunPlan(
                "r_lmp",
                f_req_lmp,
                self.m_profile,
                [self.m_sp],
                [self.m_comb],
                [self.m_sched],
                [self.m_token],
                self.m_ts,
                f_lmp_task_tuning={"01": {"replication": 4, "buffer_size_mb": 32}},
            )
        with self.assertRaises(PlanValidationError):
            RunPlan(
                "r_lmp",
                f_req_lmp,
                self.m_profile,
                [self.m_sp],
                [self.m_comb],
                [self.m_sched],
                [self.m_token],
                self.m_ts,
                f_lmp_task_tuning={"abc": {"replication": 4, "buffer_size_mb": 32}},
            )
        with self.assertRaises(PlanValidationError):
            RunPlan(
                "r_lmp",
                f_req_lmp,
                self.m_profile,
                [self.m_sp],
                [self.m_comb],
                [self.m_sched],
                [self.m_token],
                self.m_ts,
                f_lmp_task_tuning={"-1": {"replication": 4, "buffer_size_mb": 32}},
            )

        # 3. Task int not in RunPlanner.LMP_TASK_TUNING (line 1253; arc [1252, 1253])
        # Scale point tasks=999 matches key, but 999 is undefined in LMP_TASK_TUNING
        f_sp_999 = ScalePoint(999, 1, 999)
        with self.assertRaises(PlanValidationError) as f_ctx_undef:
            RunPlan(
                "r_lmp",
                f_req_lmp,
                self.m_profile,
                [f_sp_999],
                [self.m_comb],
                [self.m_sched],
                [self.m_token],
                self.m_ts,
                f_lmp_task_tuning={"999": {"replication": 4, "buffer_size_mb": 32}},
            )
        self.assertIn(
            "LMP tuning is undefined for task count 999", str(f_ctx_undef.exception)
        )

        # 4. Tuning value not a mapping (line 1257; arc [1256, 1257])
        with self.assertRaises(PlanValidationError):
            RunPlan(
                "r_lmp",
                f_req_lmp,
                self.m_profile,
                [self.m_sp],
                [self.m_comb],
                [self.m_sched],
                [self.m_token],
                self.m_ts,
                f_lmp_task_tuning={"1": "not_a_mapping"},
            )  # type: ignore

        # 5. Dict keys not exactly {"replication", "buffer_size_mb"} (line 1261; arc [1260, 1261])
        with self.assertRaises(PlanValidationError):
            RunPlan(
                "r_lmp",
                f_req_lmp,
                self.m_profile,
                [self.m_sp],
                [self.m_comb],
                [self.m_sched],
                [self.m_token],
                self.m_ts,
                f_lmp_task_tuning={"1": {"replication": 4}},
            )
        with self.assertRaises(PlanValidationError):
            RunPlan(
                "r_lmp",
                f_req_lmp,
                self.m_profile,
                [self.m_sp],
                [self.m_comb],
                [self.m_sched],
                [self.m_token],
                self.m_ts,
                f_lmp_task_tuning={
                    "1": {"replication": 4, "buffer_size_mb": 32, "extra": 1}
                },
            )

        # 6. Field value not a positive integer or is a bool (line 1271; arc [1266, 1271])
        with self.assertRaises(PlanValidationError):
            RunPlan(
                "r_lmp",
                f_req_lmp,
                self.m_profile,
                [self.m_sp],
                [self.m_comb],
                [self.m_sched],
                [self.m_token],
                self.m_ts,
                f_lmp_task_tuning={"1": {"replication": 0, "buffer_size_mb": 32}},
            )
        with self.assertRaises(PlanValidationError):
            RunPlan(
                "r_lmp",
                f_req_lmp,
                self.m_profile,
                [self.m_sp],
                [self.m_comb],
                [self.m_sched],
                [self.m_token],
                self.m_ts,
                f_lmp_task_tuning={"1": {"replication": True, "buffer_size_mb": 32}},
            )
        with self.assertRaises(PlanValidationError):
            RunPlan(
                "r_lmp",
                f_req_lmp,
                self.m_profile,
                [self.m_sp],
                [self.m_comb],
                [self.m_sched],
                [self.m_token],
                self.m_ts,
                f_lmp_task_tuning={"1": {"replication": 4, "buffer_size_mb": -1}},
            )

        # 7. Values do not match approved authority (line 1279; arc [1275, 1279])
        with self.assertRaises(PlanValidationError) as f_ctx_auth:
            RunPlan(
                "r_lmp",
                f_req_lmp,
                self.m_profile,
                [self.m_sp],
                [self.m_comb],
                [self.m_sched],
                [self.m_token],
                self.m_ts,
                f_lmp_task_tuning={"1": {"replication": 999, "buffer_size_mb": 32}},
            )
        self.assertIn(
            "values do not match approved LMP tuning authority",
            str(f_ctx_auth.exception),
        )

        # 8. Tuning tasks do not match scale points tasks (line 1287; arc [1286, 1287])
        # Scale point has tasks=1, but tuning provided for tasks=2
        with self.assertRaises(PlanValidationError) as f_ctx_mismatch:
            RunPlan(
                "r_lmp",
                f_req_lmp,
                self.m_profile,
                [self.m_sp],
                [self.m_comb],
                [self.m_sched],
                [self.m_token],
                self.m_ts,
                f_lmp_task_tuning={"2": {"replication": 5, "buffer_size_mb": 32}},
            )
        self.assertIn("do not match scale points tasks", str(f_ctx_mismatch.exception))

    def testRunPlanNonLmpTuningMustBeEmpty(self) -> None:
        """Validates that non-LMP target rejects non-empty lmp_task_tuning."""
        f_req_ior = RunRequest("ior", "small")
        # Line 1292; Arc [1291, 1292]
        with self.assertRaises(PlanValidationError) as f_ctx:
            RunPlan(
                "r_ior",
                f_req_ior,
                self.m_profile,
                [self.m_sp],
                [self.m_comb],
                [self.m_sched],
                [self.m_token],
                self.m_ts,
                f_lmp_task_tuning={"1": {"replication": 4, "buffer_size_mb": 32}},
            )
        self.assertIn(
            "lmp_task_tuning must be empty for non-LMP target", str(f_ctx.exception)
        )

    def testRunPlanImmutabilityReprAndEquality(self) -> None:
        """Validates frozen immutability, unfrozen mutation/deletion, repr, and equality against non-RunPlan."""
        f_plan = RunPlan(
            "r1",
            self.m_req,
            self.m_profile,
            [self.m_sp],
            [self.m_comb],
            [self.m_sched],
            [self.m_token],
            self.m_ts,
        )

        # Frozen modify raises AttributeError (line 1310)
        with self.assertRaises(AttributeError) as f_ctx:
            f_plan.m_run_id = "r2"
        self.assertIn("Cannot modify immutable RunPlan", str(f_ctx.exception))

        # Frozen delete raises AttributeError (lines 1314, 1315; arc [1314, 1315])
        with self.assertRaises(AttributeError) as f_ctx_del:
            del f_plan.m_run_id
        self.assertIn(
            "Cannot delete attribute from immutable RunPlan", str(f_ctx_del.exception)
        )

        # Unfrozen mutation via __new__ (line 1311; arc [1309, 1311])
        f_unfrozen = RunPlan.__new__(RunPlan)
        f_unfrozen.m_run_id = "unfrozen_r1"
        self.assertEqual(f_unfrozen.m_run_id, "unfrozen_r1")

        # Unfrozen deletion via __new__ (line 1318; arc [1314, 1318])
        del f_unfrozen.m_run_id
        self.assertFalse(hasattr(f_unfrozen, "m_run_id"))

        # __repr__ formatting (line 1371)
        f_repr = repr(f_plan)
        self.assertIn("RunPlan(run_id='r1'", f_repr)
        self.assertIn("request=RunRequest(target='lsmio'", f_repr)

        # __eq__ branch to False against non-RunPlan (line 1396; arc [1384, 1396])
        self.assertFalse(f_plan == "not_a_plan")
        self.assertFalse(f_plan == 42)
        self.assertFalse(f_plan is None)
        self.assertFalse(f_plan == {"run_id": "r1"})

        f_plan_same = RunPlan(
            "r1",
            self.m_req,
            self.m_profile,
            [self.m_sp],
            [self.m_comb],
            [self.m_sched],
            [self.m_token],
            self.m_ts,
        )
        self.assertEqual(f_plan, f_plan_same)
