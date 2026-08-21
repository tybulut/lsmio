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

import hashlib
import os
import tempfile
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple
import unittest
from unittest.mock import MagicMock, patch

from lsmiotool.lib.benchmarks import (
    BenchmarkCommand,
    BenchmarkConfigurationError,
    BenchmarkProbeError,
    CapabilityState,
    LmpAdapter,
    ProbeState,
)
from lsmiotool.lib.resources import ExecutionMode, RuntimeLayout
from lsmiotool.lib.run import Combination, RunRequest, ScalePoint


class MockProcessResult(NamedTuple):
    returncode: int
    stdout: str
    stderr: str


class LmpAdapterTest(unittest.TestCase):
    """Comprehensive test suite for LmpAdapter contract and invariants."""

    def setUp(self) -> None:
        self.m_adapter = LmpAdapter()
        self.m_executable = "/opt/lammps/bin/lmp"
        self.m_work_dir = "/benchmark/runs/run-123/points/00-tasks-1/work/c16_b8M"

    def testExactTwentySevenArgv(self) -> None:
        """Validate all 27 exact argv tuples (3 setups x 9 task tuning points)."""
        f_setups = ["LSMIO", "LSMIO-MMAP", "FS"]
        f_dumps = {
            "LSMIO": "1",
            "LSMIO-MMAP": "2",
            "FS": "0",
        }
        f_task_tuning = {
            1: ("10", "10", "10"),
            2: ("10", "10", "20"),
            4: ("10", "20", "20"),
            8: ("20", "20", "20"),
            16: ("20", "20", "40"),
            24: ("20", "30", "40"),
            32: ("20", "40", "40"),
            40: ("20", "40", "50"),
            48: ("20", "40", "60"),
        }

        f_tested_count = 0
        for f_setup in f_setups:
            for f_tasks, (f_tx, f_ty, f_tz) in f_task_tuning.items():
                f_cmd = self.m_adapter.buildCommand(
                    f_executable=self.m_executable,
                    f_setup=f_setup,
                    f_tasks=f_tasks,
                    f_threads=1,
                    f_working_dir=self.m_work_dir,
                )

                f_expected_argv = (
                    self.m_executable,
                    "-k",
                    "on",
                    "t",
                    "1",
                    "-sf",
                    "kk",
                    "-pk",
                    "kk",
                    "-in",
                    "in.reaxff.hns",
                    "-nocite",
                    "-v",
                    "x",
                    f_tx,
                    "-v",
                    "y",
                    f_ty,
                    "-v",
                    "z",
                    f_tz,
                    "-v",
                    "dump",
                    f_dumps[f_setup],
                )

                self.assertEqual(
                    f_cmd.argv,
                    f_expected_argv,
                    f"Argv mismatch for setup={f_setup} tasks={f_tasks}",
                )
                self.assertEqual(len(f_cmd.argv), 24)
                self.assertEqual(f_cmd.is_rank_local, False)
                self.assertEqual(f_cmd.isRankLocal, False)
                self.assertEqual(f_cmd.working_dir, self.m_work_dir)
                f_tested_count += 1

        self.assertEqual(f_tested_count, 27)

    def testLargeZeroLocatorProbeStage(self) -> None:
        """Prove rejection of large scale and unsupported tasks occurs before any locator, probe, or staging."""
        f_mock_locator = MagicMock()
        f_mock_probe_runner = MagicMock()
        f_mock_lstat = MagicMock()
        f_mock_open = MagicMock()

        with (
            patch("lsmiotool.lib.resources.ResourceLocator.forSource", f_mock_locator),
            patch("lsmiotool.lib.resources.ResourceLocator.forInstalled", f_mock_locator),
            patch("os.lstat", f_mock_lstat),
            patch("builtins.open", f_mock_open),
        ):
            # 1. Reject via scale='large' argument
            with self.assertRaises(BenchmarkConfigurationError):
                self.m_adapter.buildCommand(
                    f_executable=self.m_executable,
                    f_scale="large",
                    f_tasks=4,
                    f_working_dir=self.m_work_dir,
                )

            # 2. Reject via RunRequest with scale='large'
            f_large_req = RunRequest(f_target="lmp", f_scale="large", f_ssd=False, f_setup="LSMIO")
            with self.assertRaises(BenchmarkConfigurationError):
                self.m_adapter.buildCommand(
                    f_executable=self.m_executable,
                    f_request=f_large_req,
                    f_working_dir=self.m_work_dir,
                )

            # 3. Reject via unsupported task counts (e.g. 64, 128, 256)
            for f_bad_tasks in (64, 128, 192, 256):
                with self.assertRaises(BenchmarkConfigurationError):
                    self.m_adapter.buildCommand(
                        f_executable=self.m_executable,
                        f_tasks=f_bad_tasks,
                        f_working_dir=self.m_work_dir,
                    )

            # Assert zero calls were made to locator, filesystem, or probe
            f_mock_locator.assert_not_called()
            f_mock_probe_runner.assert_not_called()
            f_mock_lstat.assert_not_called()
            f_mock_open.assert_not_called()

    def testUnsupportedNoFallback(self) -> None:
        """Assert unsupported setups and tasks fail closed without fallback searches."""
        # 1. Invalid setup names fail closed
        for f_bad_setup in ("INVALID", "ENV", "BASE", "NATIVE-M", "HDF5"):
            with self.assertRaises(BenchmarkConfigurationError):
                self.m_adapter.buildCommand(
                    f_executable=self.m_executable,
                    f_setup=f_bad_setup,
                    f_tasks=1,
                    f_working_dir=self.m_work_dir,
                )

        # 2. Unsupported task counts fail closed
        for f_bad_tasks in (0, -1, 3, 5, 7, 9, 15, 50, 100):
            with self.assertRaises(BenchmarkConfigurationError):
                self.m_adapter.buildCommand(
                    f_executable=self.m_executable,
                    f_setup="LSMIO",
                    f_tasks=f_bad_tasks,
                    f_working_dir=self.m_work_dir,
                )

        # 3. getDumpValue with invalid setup
        with self.assertRaises(BenchmarkConfigurationError):
            LmpAdapter.getDumpValue("INVALID")

        # 4. getTuningParameters with invalid tasks
        with self.assertRaises(BenchmarkConfigurationError):
            LmpAdapter.getTuningParameters(99)

        # 5. Missing asset fails closed without falling back to search paths or cwd
        with tempfile.TemporaryDirectory() as f_temp_dir:
            # Empty directory with no assets
            with self.assertRaises(BenchmarkConfigurationError):
                self.m_adapter.validateAssets(f_temp_dir)

            with self.assertRaises(BenchmarkConfigurationError):
                self.m_adapter.stageAssets(f_temp_dir, os.path.join(f_temp_dir, "work"))

    def testExactAssetHashesPerCombination(self) -> None:
        """Validate asset hashing and staging into combination-private work directories."""
        with tempfile.TemporaryDirectory() as f_temp_base:
            f_asset_dir = os.path.join(f_temp_base, "lmp-reaxff")
            os.makedirs(f_asset_dir, exist_ok=True)

            f_content_in = b"# LAMMPS input file for ReaxFF HNS benchmark\nvariable dump index 1\n"
            f_content_data = b"# LAMMPS data file for HNS structure\n1000 atoms\n"
            f_content_ffield = b"# ReaxFF force field for HNS\nReaxFF parameters\n"

            with open(os.path.join(f_asset_dir, "in.reaxff.hns"), "wb") as f_f:
                f_f.write(f_content_in)
            with open(os.path.join(f_asset_dir, "data.hns"), "wb") as f_f:
                f_f.write(f_content_data)
            with open(os.path.join(f_asset_dir, "ffield.reax.hns"), "wb") as f_f:
                f_f.write(f_content_ffield)

            f_expected_hashes = {
                "in.reaxff.hns": hashlib.sha256(f_content_in).hexdigest(),
                "data.hns": hashlib.sha256(f_content_data).hexdigest(),
                "ffield.reax.hns": hashlib.sha256(f_content_ffield).hexdigest(),
            }

            # 1. Test validateAssets directly
            f_validated_hashes = self.m_adapter.validateAssets(f_asset_dir)
            self.assertEqual(f_validated_hashes, f_expected_hashes)

            # 2. Test stageAssets for combination 1
            f_work_dir_combo1 = os.path.join(f_temp_base, "runs", "run-1", "points", "p0", "work", "c16_b8M")
            f_hashes_combo1 = self.m_adapter.stageAssets(f_asset_dir, f_work_dir_combo1)
            self.assertEqual(f_hashes_combo1, f_expected_hashes)

            # Verify files exist in work_dir_combo1 with exact contents
            for f_name, f_exp_content in (
                ("in.reaxff.hns", f_content_in),
                ("data.hns", f_content_data),
                ("ffield.reax.hns", f_content_ffield),
            ):
                f_staged_path = os.path.join(f_work_dir_combo1, f_name)
                self.assertTrue(os.path.isfile(f_staged_path))
                with open(f_staged_path, "rb") as f_f:
                    self.assertEqual(f_f.read(), f_exp_content)

            # 3. Test stageAssets for combination 2
            f_work_dir_combo2 = os.path.join(f_temp_base, "runs", "run-1", "points", "p0", "work", "c16_b1M")
            f_hashes_combo2 = self.m_adapter.stageAssets(f_asset_dir, f_work_dir_combo2)
            self.assertEqual(f_hashes_combo2, f_expected_hashes)

            for f_name, f_exp_content in (
                ("in.reaxff.hns", f_content_in),
                ("data.hns", f_content_data),
                ("ffield.reax.hns", f_content_ffield),
            ):
                f_staged_path = os.path.join(f_work_dir_combo2, f_name)
                self.assertTrue(os.path.isfile(f_staged_path))
                with open(f_staged_path, "rb") as f_f:
                    self.assertEqual(f_f.read(), f_exp_content)

            # Verify independence: mutating combo1 work dir does not alter combo2
            with open(os.path.join(f_work_dir_combo1, "in.reaxff.hns"), "wb") as f_f:
                f_f.write(b"mutated")

            with open(os.path.join(f_work_dir_combo2, "in.reaxff.hns"), "rb") as f_f:
                self.assertEqual(f_f.read(), f_content_in)

    def testAssetFailures(self) -> None:
        """Assert os.lstat rejects missing assets, directories, unreadable files, and symlinks."""
        with tempfile.TemporaryDirectory() as f_temp_base:
            f_asset_dir = os.path.join(f_temp_base, "assets")
            os.makedirs(f_asset_dir, exist_ok=True)

            f_content = b"valid content"
            with open(os.path.join(f_asset_dir, "in.reaxff.hns"), "wb") as f_f:
                f_f.write(f_content)
            with open(os.path.join(f_asset_dir, "data.hns"), "wb") as f_f:
                f_f.write(f_content)

            # Case 1: Missing asset (ffield.reax.hns missing)
            with self.assertRaises(BenchmarkConfigurationError) as f_cm:
                self.m_adapter.validateAssets(f_asset_dir)
            self.assertIn("ffield.reax.hns", str(f_cm.exception))

            # Case 2: Directory instead of regular file
            os.makedirs(os.path.join(f_asset_dir, "ffield.reax.hns"), exist_ok=True)
            with self.assertRaises(BenchmarkConfigurationError) as f_cm:
                self.m_adapter.validateAssets(f_asset_dir)
            self.assertIn("not a regular file", str(f_cm.exception))
            os.rmdir(os.path.join(f_asset_dir, "ffield.reax.hns"))

            # Case 3: Symlinked asset is forbidden
            f_target_file = os.path.join(f_temp_base, "target_ffield.txt")
            with open(f_target_file, "wb") as f_f:
                f_f.write(f_content)
            os.symlink(f_target_file, os.path.join(f_asset_dir, "ffield.reax.hns"))

            with self.assertRaises(BenchmarkConfigurationError) as f_cm:
                self.m_adapter.validateAssets(f_asset_dir)
            self.assertIn("symlink", str(f_cm.exception))
            os.unlink(os.path.join(f_asset_dir, "ffield.reax.hns"))

            # Case 4: Unreadable asset file
            f_unreadable_path = os.path.join(f_asset_dir, "ffield.reax.hns")
            with open(f_unreadable_path, "wb") as f_f:
                f_f.write(f_content)

            with patch("builtins.open", side_effect=PermissionError("Permission denied")):
                with self.assertRaises(BenchmarkConfigurationError) as f_cm:
                    self.m_adapter.validateAssets(f_asset_dir)
                self.assertIn("cannot be read", str(f_cm.exception))

            # Case 5: Non-existent asset root
            with self.assertRaises(BenchmarkConfigurationError):
                self.m_adapter.validateAssets("/path/to/nonexistent/root")

    def testSharedNoRank(self) -> None:
        """Assert is_rank_local=False and paths contain no rank placeholders."""
        f_cmd = self.m_adapter.buildCommand(
            f_executable=self.m_executable,
            f_setup="LSMIO",
            f_tasks=4,
            f_working_dir=self.m_work_dir,
        )

        self.assertFalse(f_cmd.is_rank_local)
        self.assertFalse(f_cmd.isRankLocal)

        f_rank_tokens = ["{rank}", "{global_rank}", "{local_rank}", "%r", "@RANK@"]
        for f_token in f_rank_tokens:
            for f_arg in f_cmd.argv:
                self.assertNotIn(f_token, f_arg)
            self.assertNotIn(f_token, f_cmd.stdout_path)
            self.assertNotIn(f_token, f_cmd.stderr_path)
            self.assertNotIn(f_token, f_cmd.working_dir)

        self.assertTrue(f_cmd.stdout_path.startswith(self.m_work_dir))
        self.assertTrue(f_cmd.stderr_path.startswith(self.m_work_dir))

        # Explicit rank placeholders passed to buildCommand or stageAssets must be rejected
        for f_token in f_rank_tokens:
            with self.assertRaises(BenchmarkConfigurationError):
                self.m_adapter.buildCommand(
                    f_executable=self.m_executable,
                    f_setup="LSMIO",
                    f_tasks=1,
                    f_working_dir=f"/tmp/work_{f_token}",
                )
            with self.assertRaises(BenchmarkConfigurationError):
                self.m_adapter.buildCommand(
                    f_executable=f"/bin/lmp_{f_token}",
                    f_setup="LSMIO",
                    f_tasks=1,
                    f_working_dir=self.m_work_dir,
                )
            with self.assertRaises(BenchmarkConfigurationError):
                self.m_adapter.stageAssets(
                    f_asset_source="/path/to/assets",
                    f_work_dir=f"/tmp/work_{f_token}",
                )

    def testCwdIndependent(self) -> None:
        """Assert staging and path generation are completely independent of cwd."""
        f_orig_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as f_temp_base:
            f_decoy_dir = os.path.join(f_temp_base, "decoy_cwd")
            f_asset_dir = os.path.join(f_temp_base, "real_assets")
            f_work_dir = os.path.join(f_temp_base, "real_work")

            os.makedirs(f_decoy_dir, exist_ok=True)
            os.makedirs(f_asset_dir, exist_ok=True)
            os.makedirs(f_work_dir, exist_ok=True)

            # Create decoy files with different content in decoy_dir
            with open(os.path.join(f_decoy_dir, "in.reaxff.hns"), "wb") as f_f:
                f_f.write(b"DECOY IN")
            with open(os.path.join(f_decoy_dir, "data.hns"), "wb") as f_f:
                f_f.write(b"DECOY DATA")
            with open(os.path.join(f_decoy_dir, "ffield.reax.hns"), "wb") as f_f:
                f_f.write(b"DECOY FFIELD")

            # Create genuine files in real_assets
            f_real_in = b"GENUINE IN CONTENT"
            f_real_data = b"GENUINE DATA CONTENT"
            f_real_ffield = b"GENUINE FFIELD CONTENT"
            with open(os.path.join(f_asset_dir, "in.reaxff.hns"), "wb") as f_f:
                f_f.write(f_real_in)
            with open(os.path.join(f_asset_dir, "data.hns"), "wb") as f_f:
                f_f.write(f_real_data)
            with open(os.path.join(f_asset_dir, "ffield.reax.hns"), "wb") as f_f:
                f_f.write(f_real_ffield)

            try:
                os.chdir(f_decoy_dir)

                # Staging uses explicit asset directory
                f_hashes = self.m_adapter.stageAssets(f_asset_dir, f_work_dir)
                self.assertEqual(f_hashes["in.reaxff.hns"], hashlib.sha256(f_real_in).hexdigest())

                # Verify staged files contain genuine content, NOT decoy content
                with open(os.path.join(f_work_dir, "in.reaxff.hns"), "rb") as f_f:
                    self.assertEqual(f_f.read(), f_real_in)
                with open(os.path.join(f_work_dir, "data.hns"), "rb") as f_f:
                    self.assertEqual(f_f.read(), f_real_data)
                with open(os.path.join(f_work_dir, "ffield.reax.hns"), "rb") as f_f:
                    self.assertEqual(f_f.read(), f_real_ffield)

                # buildCommand paths are under real_work, not decoy_dir
                f_cmd = self.m_adapter.buildCommand(
                    f_executable=self.m_executable,
                    f_setup="LSMIO",
                    f_tasks=8,
                    f_working_dir=f_work_dir,
                )
                self.assertEqual(f_cmd.working_dir, f_work_dir)
                self.assertTrue(f_cmd.stdout_path.startswith(f_work_dir))
                self.assertFalse(f_cmd.stdout_path.startswith(f_decoy_dir))

            finally:
                os.chdir(f_orig_cwd)

    def testProbeFailures(self) -> None:
        """Verify fail-closed handling for missing or unsupported LMP binaries."""
        # 1. Runner raises FileNotFoundError
        def mockMissingBinary(f_argv: Sequence[str]) -> MockProcessResult:
            raise FileNotFoundError("Executable not found: /path/to/missing_lmp")

        with self.assertRaises(BenchmarkProbeError):
            self.m_adapter.probeCapability(
                f_executable="/path/to/missing_lmp",
                f_runner=mockMissingBinary,
            )

        # 2. Runner returns non-zero exit code
        def mockFailingRunner(f_argv: Sequence[str]) -> MockProcessResult:
            return MockProcessResult(returncode=127, stdout="", stderr="lmp: command not found")

        with self.assertRaises(BenchmarkProbeError):
            self.m_adapter.probeCapability(
                f_executable=self.m_executable,
                f_runner=mockFailingRunner,
            )

        # 3. Runner output indicates unsupported capability
        def mockUnsupportedRunner(f_argv: Sequence[str]) -> MockProcessResult:
            return MockProcessResult(returncode=0, stdout="lmp: unsupported option -h", stderr="")

        with self.assertRaises(BenchmarkProbeError):
            self.m_adapter.probeCapability(
                f_executable=self.m_executable,
                f_runner=mockUnsupportedRunner,
            )

        # 4. Runner returns empty output
        def mockEmptyRunner(f_argv: Sequence[str]) -> MockProcessResult:
            return MockProcessResult(returncode=0, stdout="", stderr="")

        with self.assertRaises(BenchmarkProbeError):
            self.m_adapter.probeCapability(
                f_executable=self.m_executable,
                f_runner=mockEmptyRunner,
            )

        # 5. Invalid setup during probe
        with self.assertRaises(BenchmarkProbeError):
            self.m_adapter.probeCapability(
                f_executable=self.m_executable,
                f_runner=lambda argv: MockProcessResult(0, "LAMMPS (2 Aug 2023)", ""),
                f_setup="INVALID_SETUP",
            )

    def testUnverifiedNoVersionClaim(self) -> None:
        """Prove unprobeable binaries remain recorded as configured/unverified."""
        f_state = self.m_adapter.probeCapability(f_executable=self.m_executable, f_runner=None)
        self.assertEqual(f_state, CapabilityState.CONFIGURED)
        self.assertEqual(f_state, ProbeState.CONFIGURED)
        self.assertTrue(f_state.is_configured)
        self.assertFalse(f_state.is_verified)
        self.assertFalse(f_state.is_unsupported)

        def mockSuccessRunner(f_argv: Sequence[str]) -> MockProcessResult:
            self.assertEqual(f_argv, [self.m_executable, "-h"])
            return MockProcessResult(returncode=0, stdout="LAMMPS (2 Aug 2023) - Large-scale Atomic/Molecular Massively Parallel Simulator", stderr="")

        f_verified = self.m_adapter.probeCapability(
            f_executable=self.m_executable,
            f_runner=mockSuccessRunner,
        )
        self.assertEqual(f_verified, CapabilityState.VERIFIED)
        self.assertTrue(f_verified.is_verified)
        self.assertFalse(f_verified.is_configured)

    def testCommandImmutability(self) -> None:
        """Verify that BenchmarkCommand returned by LmpAdapter is immutable."""
        f_cmd = self.m_adapter.buildCommand(
            f_executable=self.m_executable,
            f_setup="LSMIO",
            f_tasks=1,
            f_working_dir=self.m_work_dir,
        )
        with self.assertRaises(AttributeError):
            f_cmd.m_argv = ("new", "argv")
        with self.assertRaises(AttributeError):
            f_cmd.m_stdout_path = "/new/path"
        with self.assertRaises(AttributeError):
            del f_cmd.m_argv

    def testSpacesRemainArgv(self) -> None:
        """Verify argv tokens with spaces remain discrete arguments and are not word-split."""
        f_exe_with_spaces = "/opt/lammps tools/bin/lmp executable"
        f_work_dir_with_spaces = "/scratch/user run/points/00 tasks/work dir"

        f_cmd = self.m_adapter.buildCommand(
            f_executable=f_exe_with_spaces,
            f_setup="LSMIO",
            f_tasks=1,
            f_working_dir=f_work_dir_with_spaces,
        )

        self.assertEqual(f_cmd.argv[0], f_exe_with_spaces)
        self.assertEqual(f_cmd.working_dir, f_work_dir_with_spaces)
        self.assertEqual(len(f_cmd.argv), 24)

    def testNulByteRejection(self) -> None:
        """Verify that NUL bytes in arguments or paths raise BenchmarkConfigurationError."""
        with self.assertRaises(BenchmarkConfigurationError):
            self.m_adapter.buildCommand(
                f_executable="/bin/lmp\0",
                f_setup="LSMIO",
                f_tasks=1,
                f_working_dir=self.m_work_dir,
            )

        with self.assertRaises(BenchmarkConfigurationError):
            self.m_adapter.buildCommand(
                f_executable=self.m_executable,
                f_setup="LSMIO",
                f_tasks=1,
                f_working_dir="/work\0dir",
            )

    def testAdapterProperties(self) -> None:
        """Verify adapter metadata properties and helper methods."""
        self.assertEqual(self.m_adapter.target, "lmp")
        self.assertEqual(self.m_adapter.defaultSetup, "LSMIO")
        self.assertEqual(
            set(self.m_adapter.allowedSetups),
            {"LSMIO", "LSMIO-MMAP", "FS"},
        )
        self.assertEqual(LmpAdapter.getDumpValue("LSMIO"), 1)
        self.assertEqual(LmpAdapter.getDumpValue("LSMIO-MMAP"), 2)
        self.assertEqual(LmpAdapter.getDumpValue("FS"), 0)
        self.assertEqual(LmpAdapter.getTuningParameters(1), (10, 10, 10))
        self.assertEqual(LmpAdapter.getTuningParameters(48), (20, 40, 60))

    def testScalePointAndRuntimeLayoutObjectSupport(self) -> None:
        """Verify passing ScalePoint and RuntimeLayout objects to adapter methods."""
        f_sp = ScalePoint(f_tasks=16, f_ppn=1, f_nodes=16)
        f_cmd = self.m_adapter.buildCommand(
            f_executable=self.m_executable,
            f_setup="LSMIO-MMAP",
            f_point=f_sp,
            f_working_dir=self.m_work_dir,
        )

        self.assertIn("40", f_cmd.argv)
        self.assertIn("2", f_cmd.argv)

        with tempfile.TemporaryDirectory() as f_temp_base:
            f_asset_dir = os.path.join(f_temp_base, "assets")
            os.makedirs(f_asset_dir, exist_ok=True)
            for f_name in ("in.reaxff.hns", "data.hns", "ffield.reax.hns"):
                with open(os.path.join(f_asset_dir, f_name), "wb") as f_f:
                    f_f.write(b"content")

            f_layout = RuntimeLayout(
                f_execution_mode=ExecutionMode.SOURCE,
                f_package_root="/pkg",
                f_profile_file="/pkg/etc/environments.json",
                f_asset_root=f_asset_dir,
                f_worker_executable="/pkg/worker/lsmioworker",
                f_version_file="/VERSION",
            )

            f_staged_work = os.path.join(f_temp_base, "work")
            f_hashes = self.m_adapter.stageAssets(f_layout, f_staged_work)
            self.assertEqual(len(f_hashes), 3)
            self.assertTrue(os.path.isfile(os.path.join(f_staged_work, "in.reaxff.hns")))


if __name__ == "__main__":
    unittest.main()
