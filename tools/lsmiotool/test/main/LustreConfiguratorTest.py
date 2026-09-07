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
import unittest
from typing import Any, List, Mapping, Optional, Sequence

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
                f_key_count=65536,
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
                f_key_count=65536,
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


if __name__ == "__main__":
    unittest.main()
