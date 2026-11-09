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
import shutil
import tempfile
import types
import unittest
from typing import Any, List, Mapping, Optional, Sequence
from unittest.mock import patch

from lsmiotool.lib.profile import ProfileLoader
from lsmiotool.lib.run import Combination
from lsmiotool.lib.site import EnvironmentResolver, SiteProfile, StorageClass
from lsmiotool.lib.worker import (
    LustreConfigurationError,
    LustreConfigurator,
    ProcessExecutionError,
    ProcessLoggingError,
    ProcessResult,
    ProcessRunner,
    ProcessSpawnError,
)


class MockProcessRunner:
    """Mock process runner for simulating subprocess outcomes."""

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

    def run(
        self,
        f_argv: Sequence[str],
        **f_kwargs: Any,
    ) -> ProcessResult:
        self.m_invoked_argv.append(list(f_argv))
        if self.m_exception_to_raise is not None:
            raise self.m_exception_to_raise
        return ProcessResult(
            f_returncode=self.m_returncode,
            f_stdout=self.m_stdout,
            f_stderr=self.m_stderr,
            f_elapsed_seconds=0.01,
        )


class LustreConfiguratorTest(unittest.TestCase):
    """Test suite for LustreConfigurator verifying argv construction, pool selection, containment, and errors."""

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.mkdtemp(prefix="lustre_cfg_test_")
        self.m_etc_path = os.path.normpath(
            os.path.join(
                os.path.dirname(__file__), "..", "..", "etc", "environments.json"
            )
        )
        self.m_profile_doc = ProfileLoader.load(self.m_etc_path)
        self.m_viking2_profile = EnvironmentResolver.resolveProfile(
            "VIKING2", f_user="testuser", f_home="/tmp"
        )
        self.m_viking_profile = EnvironmentResolver.resolveProfile(
            "VIKING", f_user="testuser", f_home="/tmp"
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

        # Standard combinations
        self.m_combinations = (
            Combination(
                f_processes=1,
                f_block_size="8M",
                f_stripe_count=16,
                f_block_bytes=8388608,
                f_key_count=1024,
                f_segment_count=128,
            ),
            Combination(
                f_processes=1,
                f_block_size="1M",
                f_stripe_count=16,
                f_block_bytes=1048576,
                f_key_count=4096,
                f_segment_count=1024,
            ),
            Combination(
                f_processes=1,
                f_block_size="64K",
                f_stripe_count=16,
                f_block_bytes=65536,
                f_key_count=32768,
                f_segment_count=16384,
            ),
            Combination(
                f_processes=1,
                f_block_size="8M",
                f_stripe_count=4,
                f_block_bytes=8388608,
                f_key_count=1024,
                f_segment_count=128,
            ),
            Combination(
                f_processes=1,
                f_block_size="1M",
                f_stripe_count=4,
                f_block_bytes=1048576,
                f_key_count=4096,
                f_segment_count=1024,
            ),
            Combination(
                f_processes=1,
                f_block_size="64K",
                f_stripe_count=4,
                f_block_bytes=65536,
                f_key_count=32768,
                f_segment_count=16384,
            ),
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.m_temp_dir, ignore_errors=True)

    def testExactArgvAllCombinations(self) -> None:
        """Validates exact lfs setstripe argv across all 6 combinations."""
        for f_combo in self.m_combinations:
            f_stripe = f_combo.stripe_count
            f_block = f_combo.block_size
            f_target = f"/mnt/lustre/users/user/benchmark/runs/r1/points/00-tasks-1/data/c{f_stripe}/b{f_block}"

            # Using SiteProfile without pool (VIKING)
            f_argv_viking = LustreConfigurator.buildArgv(
                self.m_viking_profile, f_combo, f_target
            )
            self.assertEqual(
                f_argv_viking,
                ["lfs", "setstripe", "-S", f_block, "-c", str(f_stripe), f_target],
            )

            # Using raw tuple (stripe, block)
            f_argv_tuple = LustreConfigurator.argv(None, (f_stripe, f_block), f_target)
            self.assertEqual(
                f_argv_tuple,
                ["lfs", "setstripe", "-S", f_block, "-c", str(f_stripe), f_target],
            )

            # Using string combination descriptor "c<stripe>_b<block>"
            f_argv_str = LustreConfigurator.build_argv(
                None, f"c{f_stripe}_b{f_block}", f_target
            )
            self.assertEqual(
                f_argv_str,
                ["lfs", "setstripe", "-S", f_block, "-c", str(f_stripe), f_target],
            )

    def testViking2PoolSelection(self) -> None:
        """Validates correct -p <pool> selection for Viking2 SSD and HDD storage classes."""
        f_combo = self.m_combinations[0]  # (16, "8M")
        f_target = (
            "/mnt/scratch/users/user/benchmark/runs/r1/points/00-tasks-1/data/c16/b8M"
        )

        # 1. HDD StorageClass (explicit)
        f_argv_hdd = LustreConfigurator.buildArgv(
            self.m_viking2_profile,
            f_combo,
            f_target,
            f_storage_class=StorageClass.HDD,
        )
        self.assertEqual(
            f_argv_hdd,
            [
                "lfs",
                "setstripe",
                "-S",
                "8M",
                "-c",
                "16",
                "-p",
                "scratch.disk",
                f_target,
            ],
        )

        # 2. HDD string (lowercase)
        f_argv_hdd_str = LustreConfigurator.buildArgv(
            self.m_viking2_profile,
            f_combo,
            f_target,
            f_storage_class="hdd",
        )
        self.assertEqual(
            f_argv_hdd_str,
            [
                "lfs",
                "setstripe",
                "-S",
                "8M",
                "-c",
                "16",
                "-p",
                "scratch.disk",
                f_target,
            ],
        )

        # 3. Default storage class (None defaults to HDD)
        f_argv_default = LustreConfigurator.buildArgv(
            self.m_viking2_profile,
            f_combo,
            f_target,
        )
        self.assertEqual(
            f_argv_default,
            [
                "lfs",
                "setstripe",
                "-S",
                "8M",
                "-c",
                "16",
                "-p",
                "scratch.disk",
                f_target,
            ],
        )

        # 4. SSD StorageClass (explicit)
        f_argv_ssd = LustreConfigurator.buildArgv(
            self.m_viking2_profile,
            f_combo,
            f_target,
            f_storage_class=StorageClass.SSD,
        )
        self.assertEqual(
            f_argv_ssd,
            [
                "lfs",
                "setstripe",
                "-S",
                "8M",
                "-c",
                "16",
                "-p",
                "scratch.flash",
                f_target,
            ],
        )

        # 5. SSD string (lowercase and uppercase)
        f_argv_ssd_str = LustreConfigurator.buildArgv(
            self.m_viking2_profile,
            f_combo,
            f_target,
            f_storage_class="SSD",
        )
        self.assertEqual(
            f_argv_ssd_str,
            [
                "lfs",
                "setstripe",
                "-S",
                "8M",
                "-c",
                "16",
                "-p",
                "scratch.flash",
                f_target,
            ],
        )

        # 6. Resolving from site string "VIKING2"
        f_argv_site_str = LustreConfigurator.buildArgv(
            "VIKING2",
            f_combo,
            f_target,
            f_storage_class=StorageClass.SSD,
        )
        self.assertEqual(
            f_argv_site_str,
            [
                "lfs",
                "setstripe",
                "-S",
                "8M",
                "-c",
                "16",
                "-p",
                "scratch.flash",
                f_target,
            ],
        )

        # 7. Resolving from ProfileRecord
        f_viking2_record = self.m_profile_doc.getProfile("VIKING2")
        f_argv_record = LustreConfigurator.buildArgv(
            f_viking2_record,
            f_combo,
            f_target,
            f_storage_class=StorageClass.SSD,
        )
        self.assertEqual(
            f_argv_record,
            [
                "lfs",
                "setstripe",
                "-S",
                "8M",
                "-c",
                "16",
                "-p",
                "scratch.flash",
                f_target,
            ],
        )

    def testOtherSitesOmitPool(self) -> None:
        """Validates that VIKING, ISAMBARD, ARCHER2, and DEV omit the -p pool flag."""
        f_combo = self.m_combinations[0]  # (16, "8M")
        f_target = (
            "/mnt/lustre/users/user/benchmark/runs/r1/points/00-tasks-1/data/c16/b8M"
        )

        f_non_pool_sites = [
            ("VIKING", self.m_viking_profile),
            ("ARCHER2", self.m_archer2_profile),
            ("ISAMBARD", self.m_isambard_profile),
            ("DEV", self.m_dev_profile),
        ]

        for f_site_name, f_profile in f_non_pool_sites:
            for f_sc in (StorageClass.HDD, StorageClass.SSD, None):
                # Using SiteProfile
                f_argv = LustreConfigurator.buildArgv(
                    f_profile, f_combo, f_target, f_storage_class=f_sc
                )
                self.assertNotIn("-p", f_argv, f"Site {f_site_name} must omit -p flag")
                self.assertEqual(
                    f_argv,
                    ["lfs", "setstripe", "-S", "8M", "-c", "16", f_target],
                )

                # Using site string name
                f_argv_str = LustreConfigurator.buildArgv(
                    f_site_name, f_combo, f_target, f_storage_class=f_sc
                )
                self.assertNotIn(
                    "-p", f_argv_str, f"Site string {f_site_name} must omit -p flag"
                )
                self.assertEqual(
                    f_argv_str,
                    ["lfs", "setstripe", "-S", "8M", "-c", "16", f_target],
                )

                # Pool resolution directly returns None
                f_pool = LustreConfigurator.resolvePool(f_profile, f_storage_class=f_sc)
                self.assertIsNone(
                    f_pool, f"Site {f_site_name} pool must resolve to None"
                )

    def testContainmentRejectsEscapes(self) -> None:
        """Asserts rejection of path escapes (..), symlinks, and paths outside data directories."""
        f_combo = self.m_combinations[0]  # (16, "8M")

        # 1. Path traversal via '..'
        with self.assertRaises(LustreConfigurationError):
            LustreConfigurator.buildArgv(
                self.m_viking_profile,
                f_combo,
                "/mnt/lustre/runs/r1/points/00/data/c16/b8M/../../../escaped",
            )

        with self.assertRaises(LustreConfigurationError):
            LustreConfigurator.validateTargetDir("../points/00/data/c16/b8M", f_combo)

        # 2. Relative paths (not absolute)
        with self.assertRaises(LustreConfigurationError):
            LustreConfigurator.validateTargetDir("data/c16/b8M", f_combo)

        # 3. Root filesystem escapes
        with self.assertRaises(LustreConfigurationError):
            LustreConfigurator.validateTargetDir("/", f_combo)

        with self.assertRaises(LustreConfigurationError):
            LustreConfigurator.validateTargetDir("/etc", f_combo)

        with self.assertRaises(LustreConfigurationError):
            LustreConfigurator.validateTargetDir("/tmp/outside", f_combo)

        # 4. Outside data directory (e.g. work directory or logs directory)
        with self.assertRaises(LustreConfigurationError):
            LustreConfigurator.validateTargetDir(
                "/mnt/lustre/runs/r1/points/00-tasks-1/work/c16_b8M", f_combo
            )

        with self.assertRaises(LustreConfigurationError):
            LustreConfigurator.validateTargetDir(
                "/mnt/lustre/runs/r1/points/00-tasks-1/logs", f_combo
            )

        # 5. Combination mismatch in data path
        with self.assertRaises(LustreConfigurationError):
            LustreConfigurator.validateTargetDir(
                "/mnt/lustre/runs/r1/points/00-tasks-1/data/c4/b1M", f_combo
            )

        # 6. NUL byte injection
        with self.assertRaises(LustreConfigurationError):
            LustreConfigurator.validateTargetDir(
                "/mnt/lustre/runs/r1/points/00-tasks-1/data/c16/b8M\0injection", f_combo
            )

        # 7. Symlink target rejection
        f_real_data_dir = os.path.join(
            self.m_temp_dir, "real_point", "data", "c16", "b8M"
        )
        os.makedirs(f_real_data_dir, exist_ok=True)
        f_symlink_dir = os.path.join(self.m_temp_dir, "symlink_point")
        os.symlink(os.path.join(self.m_temp_dir, "real_point"), f_symlink_dir)

        f_symlink_target = os.path.join(f_symlink_dir, "data", "c16", "b8M")
        with self.assertRaises(LustreConfigurationError):
            LustreConfigurator.validateTargetDir(f_symlink_target, f_combo)

        # Direct symlink file/dir
        f_symlink_direct = os.path.join(self.m_temp_dir, "direct_symlink_data_c16_b8M")
        os.symlink(f_real_data_dir, f_symlink_direct)
        f_symlink_with_name = os.path.join(self.m_temp_dir, "data", "c16", "b8M")
        os.makedirs(os.path.dirname(f_symlink_with_name), exist_ok=True)
        os.symlink(f_real_data_dir, f_symlink_with_name)

        with self.assertRaises(LustreConfigurationError):
            LustreConfigurator.validateTargetDir(f_symlink_with_name, f_combo)

    def testSiteSymlinkAboveRunRootAccepted(self) -> None:
        """Asserts that site symlinks above the run root are accepted and those from it down are rejected."""
        f_combo = self.m_combinations[0]  # (16, "8M")
        f_lustre = os.path.join(self.m_temp_dir, "lustre", "work", "e281")
        f_point = os.path.join("benchmark", "runs", "r1", "points", "00-tasks-1")
        os.makedirs(os.path.join(f_lustre, f_point, "data", "c16", "b8M"))
        f_work = os.path.join(self.m_temp_dir, "work")
        os.makedirs(f_work)
        os.symlink(f_lustre, os.path.join(f_work, "e281"))

        f_target = os.path.join(f_work, "e281", f_point, "data", "c16", "b8M")
        self.assertEqual(
            LustreConfigurator.validateTargetDir(f_target, f_combo), f_target
        )
        self.assertEqual(LustreConfigurator.validateTargetDir(f_target), f_target)

        # A symlinked data/ inside the point directory
        f_real_data = os.path.join(self.m_temp_dir, "elsewhere")
        os.makedirs(os.path.join(f_real_data, "c16", "b8M"))
        f_linked_point = os.path.join(
            f_lustre, "benchmark", "runs", "r1", "points", "01"
        )
        os.makedirs(f_linked_point)
        os.symlink(f_real_data, os.path.join(f_linked_point, "data"))
        with self.assertRaisesRegex(LustreConfigurationError, "symlink"):
            LustreConfigurator.validateTargetDir(
                os.path.join(f_linked_point, "data", "c16", "b8M"), f_combo
            )

        # A symlinked point directory under the site symlink
        f_runs = os.path.join(f_lustre, "benchmark", "runs")
        f_points = os.path.join(f_runs, "r1", "points")
        os.symlink(os.path.join(f_points, "00-tasks-1"), os.path.join(f_points, "02"))
        with self.assertRaisesRegex(LustreConfigurationError, "symlink"):
            LustreConfigurator.validateTargetDir(
                os.path.join(
                    f_work,
                    "e281",
                    "benchmark",
                    "runs",
                    "r1",
                    "points",
                    "02",
                    "data",
                    "c16",
                    "b8M",
                ),
                f_combo,
            )

        # A symlinked stripe directory, points/ directory and run root
        f_stripe_point = os.path.join(f_points, "03")
        os.makedirs(os.path.join(f_stripe_point, "data"))
        os.symlink(
            os.path.join(f_real_data, "c16"),
            os.path.join(f_stripe_point, "data", "c16"),
        )
        os.symlink(os.path.join(f_runs, "r1"), os.path.join(f_runs, "r2"))
        os.makedirs(os.path.join(f_runs, "r3"))
        os.symlink(f_points, os.path.join(f_runs, "r3", "points"))
        for f_linked in (
            os.path.join(f_stripe_point, "data", "c16", "b8M"),
            os.path.join(f_runs, "r2", "points", "00-tasks-1", "data", "c16", "b8M"),
            os.path.join(f_runs, "r3", "points", "00-tasks-1", "data", "c16", "b8M"),
        ):
            with self.assertRaisesRegex(
                LustreConfigurationError, "symlink", msg=f_linked
            ):
                LustreConfigurator.validateTargetDir(f_linked, f_combo)

        # A symlinked runs/ directory, just above the run root, is the site's
        f_other_root = os.path.join(f_lustre, "other-benchmark")
        os.makedirs(f_other_root)
        os.symlink(f_runs, os.path.join(f_other_root, "runs"))
        f_via_runs = os.path.join(
            f_other_root, "runs", "r1", "points", "00-tasks-1", "data", "c16", "b8M"
        )
        self.assertEqual(
            LustreConfigurator.validateTargetDir(f_via_runs, f_combo), f_via_runs
        )

        # A point directory at the root, and a leading '//' (kept by normpath), return
        self.assertEqual(
            LustreConfigurator.validateTargetDir("/data/c16/b8M", f_combo),
            "/data/c16/b8M",
        )
        self.assertEqual(
            LustreConfigurator.validateTargetDir("//data/c16/b8M", f_combo),
            "//data/c16/b8M",
        )

    def testMissingCommandFatal(self) -> None:
        """Asserts that missing lfs binary or nonzero exit code raises LustreConfigurationError."""
        f_combo = self.m_combinations[0]
        f_target = (
            "/mnt/scratch/users/user/benchmark/runs/r1/points/00-tasks-1/data/c16/b8M"
        )

        # 1. Nonzero exit code from runner
        f_mock_failing_runner = MockProcessRunner(
            f_returncode=1,
            f_stderr="lfs setstripe: error setting stripe size",
        )
        with self.assertRaises(LustreConfigurationError) as f_ctx:
            LustreConfigurator.configure(
                self.m_viking2_profile,
                f_combo,
                f_target,
                f_runner=f_mock_failing_runner,
            )
        self.assertIn("failed", str(f_ctx.exception).lower())
        self.assertIn("1", str(f_ctx.exception))

        # 2. ProcessSpawnError (e.g. binary not found)
        f_spawn_error = ProcessSpawnError("Binary 'lfs' not found in PATH")
        f_mock_spawn_failing = MockProcessRunner(f_exception_to_raise=f_spawn_error)
        with self.assertRaises(LustreConfigurationError) as f_ctx:
            LustreConfigurator.configure(
                self.m_viking2_profile,
                f_combo,
                f_target,
                f_runner=f_mock_spawn_failing,
            )
        self.assertIn("spawn", str(f_ctx.exception).lower())

        # 3. Missing lfs binary on native system with default ProcessRunner
        with self.assertRaises(LustreConfigurationError):
            LustreConfigurator.configure(
                self.m_viking_profile,
                f_combo,
                f_target,
                f_runner=ProcessRunner(),
            )

    def testConfigureSuccessWithInjectedRunner(self) -> None:
        """Verifies configure() returns successful ProcessResult when runner succeeds."""
        f_combo = self.m_combinations[1]  # (16, "1M")
        f_target = (
            "/mnt/scratch/users/user/benchmark/runs/r1/points/00-tasks-1/data/c16/b1M"
        )

        f_mock_success_runner = MockProcessRunner(f_returncode=0, f_stdout="stripe set")
        f_result = LustreConfigurator.configure(
            self.m_viking2_profile,
            f_combo,
            f_target,
            f_runner=f_mock_success_runner,
            f_storage_class=StorageClass.SSD,
        )

        self.assertIsInstance(f_result, ProcessResult)
        self.assertEqual(f_result.returncode, 0)
        self.assertTrue(f_result.is_success)
        self.assertEqual(
            f_mock_success_runner.m_invoked_argv,
            [
                [
                    "lfs",
                    "setstripe",
                    "-S",
                    "1M",
                    "-c",
                    "16",
                    "-p",
                    "scratch.flash",
                    f_target,
                ]
            ],
        )

    def testInvalidCombinationDescriptors(self) -> None:
        """Verifies validation failure on invalid combination descriptors."""
        f_target = "/mnt/scratch/runs/r1/points/00/data/c16/b8M"

        # None combination
        with self.assertRaises(LustreConfigurationError):
            LustreConfigurator.buildArgv(self.m_viking_profile, None, f_target)

        # Zero or negative stripe count
        with self.assertRaises(LustreConfigurationError):
            LustreConfigurator.buildArgv(self.m_viking_profile, (0, "8M"), f_target)

        with self.assertRaises(LustreConfigurationError):
            LustreConfigurator.buildArgv(self.m_viking_profile, (-4, "8M"), f_target)

        # Invalid block size format
        with self.assertRaises(LustreConfigurationError):
            LustreConfigurator.buildArgv(
                self.m_viking_profile, (16, "8M; rm -rf /"), f_target
            )

        with self.assertRaises(LustreConfigurationError):
            LustreConfigurator.buildArgv(self.m_viking_profile, (16, ""), f_target)

    def testInvalidPoolToken(self) -> None:
        """Verifies validation failure on invalid pool names containing metacharacters."""
        with self.assertRaises(LustreConfigurationError):
            LustreConfigurator.resolvePool("scratch.pool; rm -rf /")

        with self.assertRaises(LustreConfigurationError):
            LustreConfigurator.resolvePool("pool\0with_nul")

        with self.assertRaises(LustreConfigurationError):
            LustreConfigurator.resolvePool("pool with spaces")

    def testAliasesAndClassInstantiations(self) -> None:
        """Verifies camelCase and snake_case method aliases on class and instance."""
        f_combo = self.m_combinations[0]
        f_target = "/mnt/lustre/runs/r1/points/00/data/c16/b8M"

        f_inst = LustreConfigurator()
        f_argv1 = LustreConfigurator.buildArgv(self.m_viking_profile, f_combo, f_target)
        f_argv2 = LustreConfigurator.build_argv(
            self.m_viking_profile, f_combo, f_target
        )
        f_argv3 = LustreConfigurator.argv(self.m_viking_profile, f_combo, f_target)
        f_argv4 = f_inst.buildArgv(self.m_viking_profile, f_combo, f_target)
        f_argv5 = f_inst.argv(self.m_viking_profile, f_combo, f_target)

        self.assertEqual(f_argv1, f_argv2)
        self.assertEqual(f_argv1, f_argv3)
        self.assertEqual(f_argv1, f_argv4)
        self.assertEqual(f_argv1, f_argv5)


class LustreConfiguratorContractTest(unittest.TestCase):
    """Contract tests for LustreConfigurator combination parsing, pool resolution, containment, and execution error handling."""

    def setUp(self) -> None:
        self.m_combo_valid = (16, "8M")
        self.m_target_valid = (
            "/mnt/scratch/benchmark/runs/r1/points/00-tasks-1/data/c16/b8M"
        )

    def testExtractCombinationStripeBlockAttributes(self) -> None:
        """Validates combination descriptor with stripe and block attributes."""
        f_combo = types.SimpleNamespace(stripe=8, block="2M")
        f_stripe, f_block = LustreConfigurator._extractCombination(f_combo)
        self.assertEqual(f_stripe, 8)
        self.assertEqual(f_block, "2M")

    def testExtractCombinationDictVariants(self) -> None:
        """Validates dictionary combination descriptors with stripe_count/block_size and stripe/block keys."""
        f_cases = [
            ({"stripe_count": 8, "block_size": "2M"}, (8, "2M")),
            ({"stripe": 4, "block": "1M"}, (4, "1M")),
        ]
        for f_dict, f_expected in f_cases:
            with self.subTest(combo_dict=f_dict):
                self.assertEqual(
                    LustreConfigurator._extractCombination(f_dict), f_expected
                )

    def testExtractCombinationUnsupportedType(self) -> None:
        """Validates rejection of unsupported combination descriptor types."""
        f_unsupported = [12345, 3.14, {1, 2}, [1, "2M", 3], object()]
        for f_bad in f_unsupported:
            with self.subTest(bad_type=type(f_bad).__name__):
                with self.assertRaisesRegex(
                    LustreConfigurationError, "Unsupported combination descriptor type"
                ):
                    LustreConfigurator._extractCombination(f_bad)

    def testExtractCombinationStringStripeValidation(self) -> None:
        """Validates parsing of numeric string stripe counts and rejection of non-numeric string stripe counts."""
        # 1. Valid string stripe count
        f_stripe, f_block = LustreConfigurator._extractCombination(("8", "2M"))
        self.assertEqual(f_stripe, 8)
        self.assertEqual(f_block, "2M")

        # 2. Non-numeric string stripe count
        with self.assertRaisesRegex(
            LustreConfigurationError,
            r"Stripe count must be a positive integer, got string: 'invalid_count'",
        ):
            LustreConfigurator._extractCombination(("invalid_count", "2M"))

    def testResolvePoolInvalidStorageClass(self) -> None:
        """Validates rejection of invalid storage class specifiers during pool resolution."""
        f_bad_classes = [
            "nvram",
            "archive",
            types.SimpleNamespace(value="tape"),
            123,
        ]
        for f_sc in f_bad_classes:
            with self.subTest(storage_class=f_sc):
                with self.assertRaisesRegex(
                    LustreConfigurationError,
                    "Invalid storage class for pool resolution",
                ):
                    LustreConfigurator.resolvePool("VIKING2", f_storage_class=f_sc)

    def testResolvePoolGetLustrePoolExceptionFallback(self) -> None:
        """Validates fallback to string storage key when getLustrePool(enum) raises an exception."""

        class _StringOnlyProfile:
            def getLustrePool(self, sc: Any) -> Optional[str]:
                if not isinstance(sc, str):
                    raise TypeError("Expected string storage key")
                return f"fallback_pool_{sc}"

        f_prof = _StringOnlyProfile()
        f_res = LustreConfigurator.resolvePool(f_prof, f_storage_class=StorageClass.SSD)
        self.assertEqual(f_res, "fallback_pool_ssd")

    def testResolvePoolLustrePoolsAttributeVariants(self) -> None:
        """Validates pool resolution from lustre_pools attribute with dict, non-dict, and enum keys."""
        # 1. lustre_pools is not a dict -> returns None
        f_prof_none = types.SimpleNamespace(lustre_pools=None)
        self.assertIsNone(LustreConfigurator.resolvePool(f_prof_none))

        # 2. lustre_pools dict with StorageClass enum keys
        f_prof_enum = types.SimpleNamespace(
            lustre_pools={
                StorageClass.HDD: "enum_hdd_pool",
                StorageClass.SSD: "enum_ssd_pool",
            }
        )
        self.assertEqual(
            LustreConfigurator.resolvePool(f_prof_enum, f_storage_class="hdd"),
            "enum_hdd_pool",
        )
        self.assertEqual(
            LustreConfigurator.resolvePool(f_prof_enum, f_storage_class="ssd"),
            "enum_ssd_pool",
        )

        # 3. Custom mapping where get(enum) raises an exception
        class _EnumRejectingMapping(dict):
            def get(self, key: Any, default: Any = None) -> Any:
                if not isinstance(key, str):
                    raise TypeError("Enum lookup rejected")
                return super().get(key, default)

        f_prof_reject = types.SimpleNamespace(
            lustre_pools=_EnumRejectingMapping({"other": "val"})
        )
        self.assertIsNone(
            LustreConfigurator.resolvePool(f_prof_reject, f_storage_class="hdd")
        )

    def testResolvePoolPoolsAttributeVariants(self) -> None:
        """Validates pool resolution from pools attribute with dict and non-dict."""
        # 1. pools is a dict
        f_prof_dict = types.SimpleNamespace(
            pools={"hdd": "custom_hdd_pool", "SSD": "custom_ssd_pool"}
        )
        self.assertEqual(
            LustreConfigurator.resolvePool(f_prof_dict, f_storage_class="hdd"),
            "custom_hdd_pool",
        )
        self.assertEqual(
            LustreConfigurator.resolvePool(f_prof_dict, f_storage_class="ssd"),
            "custom_ssd_pool",
        )

        # 2. pools is not a dict -> returns None
        f_prof_not_dict = types.SimpleNamespace(pools=None)
        self.assertIsNone(
            LustreConfigurator.resolvePool(f_prof_not_dict, f_storage_class="hdd")
        )

    def testResolvePoolDirectPoolStringName(self) -> None:
        """Validates resolving direct pool name token from string when not a known site name."""
        f_pool = LustreConfigurator.resolvePool("scratch.direct_nvme")
        self.assertEqual(f_pool, "scratch.direct_nvme")

    def testResolvePoolDictProfileVariants(self) -> None:
        """Validates pool resolution from dictionary profile containers."""
        # 1. lustre_pools in dict
        f_dict_lustre = {"lustre_pools": {"hdd": "dict_hdd_pool"}}
        self.assertEqual(
            LustreConfigurator.resolvePool(f_dict_lustre, f_storage_class="hdd"),
            "dict_hdd_pool",
        )

        # 2. pools in dict
        f_dict_pools = {"pools": {"hdd": "dict_pools_hdd"}}
        self.assertEqual(
            LustreConfigurator.resolvePool(f_dict_pools, f_storage_class="hdd"),
            "dict_pools_hdd",
        )

        # 3. Non-dict or empty
        self.assertIsNone(LustreConfigurator.resolvePool({"lustre_pools": None}))
        self.assertIsNone(LustreConfigurator.resolvePool({}))

    def testResolvePoolUnsupportedContainerType(self) -> None:
        """Validates rejection of unsupported container types during pool resolution."""
        f_unsupported = [12345, [1, 2], object()]
        for f_bad in f_unsupported:
            with self.subTest(bad_container=type(f_bad).__name__):
                with self.assertRaisesRegex(
                    LustreConfigurationError,
                    "Unsupported profile container type for pool resolution",
                ):
                    LustreConfigurator.resolvePool(f_bad)

    def testResolvePoolBlankStringReturnsNone(self) -> None:
        """Validates that whitespace or blank resolved pool string returns None."""
        f_cases = [{"pools": {"hdd": ""}}, {"pools": {"hdd": "   "}}]
        for f_prof in f_cases:
            with self.subTest(prof=f_prof):
                self.assertIsNone(LustreConfigurator.resolvePool(f_prof))

    def testResolvePoolInvalidPoolCharacters(self) -> None:
        """Validates rejection of pool name tokens containing spaces, semicolons, or NUL bytes."""
        f_invalid = [
            {"pools": {"hdd": "pool with spaces"}},
            {"pools": {"hdd": "pool;injection"}},
            {"pools": {"hdd": "pool\0nul"}},
        ]
        for f_prof in f_invalid:
            with self.subTest(prof=f_prof):
                with self.assertRaisesRegex(
                    LustreConfigurationError,
                    r"Lustre pool name '.*' contains invalid characters",
                ):
                    LustreConfigurator.resolvePool(f_prof)

    def testValidateTargetDirBlankOrNonString(self) -> None:
        """Validates rejection of empty string, whitespace, None, or non-string target directories."""
        f_invalid = ["", "   ", None, 12345, []]
        for f_bad in f_invalid:
            with self.subTest(bad_target=f_bad):
                with self.assertRaisesRegex(
                    LustreConfigurationError,
                    "Target directory must be a non-empty string",
                ):
                    LustreConfigurator.validateTargetDir(f_bad)

    def testValidateTargetDirGeneralPatternMismatchWhenCombinationNone(self) -> None:
        """Validates target directory containment check under general pattern when combination is None."""
        f_outside_path = (
            "/mnt/lustre/users/user/benchmark/runs/r1/points/00-tasks-1/work/c16_b8M"
        )
        with self.assertRaisesRegex(
            LustreConfigurationError,
            r"Target directory '.*' is not contained under a point data directory",
        ):
            LustreConfigurator.validateTargetDir(f_outside_path, f_combination=None)

    def testConfigureRunnerFromKwargs(self) -> None:
        """Validates runner injection via kwargs when f_runner parameter is omitted."""
        f_mock_runner = MockProcessRunner(f_returncode=0)
        f_res = LustreConfigurator.configure(
            None,
            self.m_combo_valid,
            self.m_target_valid,
            runner=f_mock_runner,
        )
        self.assertTrue(f_res.is_success)
        self.assertEqual(len(f_mock_runner.m_invoked_argv), 1)

    def testConfigureDefaultProcessRunner(self) -> None:
        """Validates configure default instantiation of ProcessRunner when runner is omitted."""
        with patch.object(
            ProcessRunner, "run", return_value=ProcessResult(0)
        ) as f_mock_run:
            f_res = LustreConfigurator.configure(
                None,
                self.m_combo_valid,
                self.m_target_valid,
            )
            self.assertTrue(f_res.is_success)
            f_mock_run.assert_called_once()

    def testConfigureProcessExecutionError(self) -> None:
        """Validates translation of ProcessExecutionError into LustreConfigurationError."""
        f_mock_runner = MockProcessRunner(
            f_exception_to_raise=ProcessExecutionError("I/O error during execution")
        )
        with self.assertRaises(LustreConfigurationError) as f_ctx:
            LustreConfigurator.configure(
                None,
                self.m_combo_valid,
                self.m_target_valid,
                f_runner=f_mock_runner,
            )
        self.assertIn("execution error", str(f_ctx.exception).lower())
        self.assertIsInstance(f_ctx.exception.__cause__, ProcessExecutionError)

    def testConfigureUnexpectedException(self) -> None:
        """Validates translation of unexpected runner exceptions into LustreConfigurationError."""
        f_mock_runner = MockProcessRunner(
            f_exception_to_raise=RuntimeError("Unexpected subprocess crash")
        )
        with self.assertRaises(LustreConfigurationError) as f_ctx:
            LustreConfigurator.configure(
                None,
                self.m_combo_valid,
                self.m_target_valid,
                f_runner=f_mock_runner,
            )
        self.assertIn("unexpected error", str(f_ctx.exception).lower())
        self.assertIsInstance(f_ctx.exception.__cause__, RuntimeError)


if __name__ == "__main__":
    unittest.main()
