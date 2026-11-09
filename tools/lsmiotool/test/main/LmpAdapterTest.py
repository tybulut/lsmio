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


class MockProcessResult(NamedTuple):
    returncode: int
    stdout: str
    stderr: str


class LmpAdapterTest(unittest.TestCase):
    """Comprehensive test suite for LmpAdapter contract, upstream golden argv, and invariants."""

    def setUp(self) -> None:
        self.m_adapter = LmpAdapter()
        self.m_executable = "/opt/lammps/bin/lmp"
        self.m_work_dir = "/benchmark/runs/run-123/points/00-tasks-1/work/c16_b8M"

    def testUpstreamGoldenArgvEverySupportedTaskSetup(self) -> None:
        """Validate all 27 exact upstream-golden argv tuples (3 setups x 9 task tuning points).

        Exact shared LMP argv contract:
        - Base: lmp -in in.reaxc.hns -v x REP -v y REP -v z REP
        - LSMIO: -lsmio-buf-size-mb BUF
        - LSMIO-MMAP: -lsmio-mmap -lsmio-buf-size-mb BUF
        - FS: -lsmio-fallback
        """
        f_setups = ["LSMIO", "LSMIO-MMAP", "FS"]
        # Literal upstream tuning values (the LMP benchmark's per-node buffer sizes)
        f_upstream_tuning: Dict[int, Tuple[int, int]] = {
            1: (4, 32),
            2: (5, 32),
            4: (6, 64),
            8: (8, 128),
            16: (10, 256),
            24: (12, 512),
            32: (14, 1024),
            40: (15, 1024),
            48: (16, 1024),
        }

        f_tested_count = 0
        for f_setup in f_setups:
            for f_tasks, (f_rep, f_buf) in f_upstream_tuning.items():
                f_cmd = self.m_adapter.buildCommand(
                    f_executable=self.m_executable,
                    f_setup=f_setup,
                    f_replication=f_rep,
                    f_buffer_size_mb=f_buf,
                    f_working_dir=self.m_work_dir,
                )

                if f_setup == "LSMIO":
                    f_expected_argv = (
                        self.m_executable,
                        "-in",
                        "in.reaxc.hns",
                        "-v",
                        "x",
                        str(f_rep),
                        "-v",
                        "y",
                        str(f_rep),
                        "-v",
                        "z",
                        str(f_rep),
                        "-lsmio-buf-size-mb",
                        str(f_buf),
                    )
                    self.assertEqual(len(f_cmd.argv), 14)
                elif f_setup == "LSMIO-MMAP":
                    f_expected_argv = (
                        self.m_executable,
                        "-in",
                        "in.reaxc.hns",
                        "-v",
                        "x",
                        str(f_rep),
                        "-v",
                        "y",
                        str(f_rep),
                        "-v",
                        "z",
                        str(f_rep),
                        "-lsmio-mmap",
                        "-lsmio-buf-size-mb",
                        str(f_buf),
                    )
                    self.assertEqual(len(f_cmd.argv), 15)
                elif f_setup == "FS":
                    f_expected_argv = (
                        self.m_executable,
                        "-in",
                        "in.reaxc.hns",
                        "-v",
                        "x",
                        str(f_rep),
                        "-v",
                        "y",
                        str(f_rep),
                        "-v",
                        "z",
                        str(f_rep),
                        "-lsmio-fallback",
                    )
                    self.assertEqual(len(f_cmd.argv), 13)

                self.assertEqual(
                    f_cmd.argv,
                    f_expected_argv,
                    f"Argv mismatch for setup={f_setup} tasks={f_tasks}",
                )
                self.assertEqual(f_cmd.is_rank_local, False)
                self.assertEqual(f_cmd.isRankLocal, False)
                self.assertEqual(f_cmd.working_dir, self.m_work_dir)
                f_tested_count += 1

        self.assertEqual(f_tested_count, 27)

    def testExactUpstreamAssetsHashAndStage(self) -> None:
        """Validate exact upstream asset names (in.reaxc.hns, data.hns-equil, ffield.reax.hns), hashing, and staging."""
        self.assertEqual(
            self.m_adapter.REQUIRED_ASSETS,
            ("in.reaxc.hns", "data.hns-equil", "ffield.reax.hns"),
        )

        with tempfile.TemporaryDirectory() as f_temp_base:
            f_asset_dir = os.path.join(f_temp_base, "lmp-reaxff")
            os.makedirs(f_asset_dir, exist_ok=True)

            f_content_in = (
                b"# LAMMPS input file for ReaxFF HNS benchmark\nvariable rep index 4\n"
            )
            f_content_data = (
                b"# LAMMPS data file for HNS equilibrium structure\n1000 atoms\n"
            )
            f_content_ffield = (
                b"# ReaxFF force field parameters for HNS\nReaxFF parameters\n"
            )

            with open(os.path.join(f_asset_dir, "in.reaxc.hns"), "wb") as f_f:
                f_f.write(f_content_in)
            with open(os.path.join(f_asset_dir, "data.hns-equil"), "wb") as f_f:
                f_f.write(f_content_data)
            with open(os.path.join(f_asset_dir, "ffield.reax.hns"), "wb") as f_f:
                f_f.write(f_content_ffield)

            f_expected_hashes = {
                "in.reaxc.hns": hashlib.sha256(f_content_in).hexdigest(),
                "data.hns-equil": hashlib.sha256(f_content_data).hexdigest(),
                "ffield.reax.hns": hashlib.sha256(f_content_ffield).hexdigest(),
            }

            # 1. Test validateAssets directly
            f_validated_hashes = self.m_adapter.validateAssets(f_asset_dir)
            self.assertEqual(f_validated_hashes, f_expected_hashes)

            # 2. Test stageAssets for combination 1
            f_work_dir_combo1 = os.path.join(
                f_temp_base, "runs", "run-1", "points", "p0", "work", "c16_b8M"
            )
            f_hashes_combo1 = self.m_adapter.stageAssets(f_asset_dir, f_work_dir_combo1)
            self.assertEqual(f_hashes_combo1, f_expected_hashes)

            for f_name, f_exp_content in (
                ("in.reaxc.hns", f_content_in),
                ("data.hns-equil", f_content_data),
                ("ffield.reax.hns", f_content_ffield),
            ):
                f_staged_path = os.path.join(f_work_dir_combo1, f_name)
                self.assertTrue(os.path.isfile(f_staged_path))
                with open(f_staged_path, "rb") as f_f:
                    self.assertEqual(f_f.read(), f_exp_content)

            # 3. Test stageAssets for combination 2
            f_work_dir_combo2 = os.path.join(
                f_temp_base, "runs", "run-1", "points", "p0", "work", "c16_b1M"
            )
            f_hashes_combo2 = self.m_adapter.stageAssets(f_asset_dir, f_work_dir_combo2)
            self.assertEqual(f_hashes_combo2, f_expected_hashes)

            # Verify independence: mutating combo1 work dir does not alter combo2
            with open(os.path.join(f_work_dir_combo1, "in.reaxc.hns"), "wb") as f_f:
                f_f.write(b"mutated")

            with open(os.path.join(f_work_dir_combo2, "in.reaxc.hns"), "rb") as f_f:
                self.assertEqual(f_f.read(), f_content_in)

    def testNoInventedKokkosDumpRenameOrFallback(self) -> None:
        """Assert no invented Kokkos flags, dump flags, renamed aliases, or fallback tables exist."""
        # 1. buildCommand must reject calls without replication (no hidden fallback table)
        with self.assertRaises(BenchmarkConfigurationError) as f_cm:
            self.m_adapter.buildCommand(
                f_executable=self.m_executable,
                f_setup="LSMIO",
                f_working_dir=self.m_work_dir,
            )
        self.assertIn("replication", str(f_cm.exception).lower())

        # Passing tasks without tuning or replication must also fail
        with self.assertRaises(BenchmarkConfigurationError):
            self.m_adapter.buildCommand(
                f_executable=self.m_executable,
                f_setup="LSMIO",
                f_working_dir=self.m_work_dir,
                f_tasks=8,
            )

        # 2. Verify no Kokkos, dump, or renamed alias tokens appear in valid commands
        f_cmd = self.m_adapter.buildCommand(
            f_executable=self.m_executable,
            f_setup="LSMIO",
            f_replication=4,
            f_buffer_size_mb=32,
            f_working_dir=self.m_work_dir,
        )

        f_forbidden_tokens = [
            "-k",
            "-sf",
            "-pk",
            "kk",
            "-nocite",
            "dump",
            "-v dump",
            "in.reaxff.hns",
            "data.hns",
        ]
        for f_tok in f_forbidden_tokens:
            self.assertNotIn(f_tok, f_cmd.argv)

        # 3. Verify adapter does not have TASK_TUNING_MAP or SETUP_DUMP_MAP attributes
        self.assertFalse(hasattr(self.m_adapter, "TASK_TUNING_MAP"))
        self.assertFalse(hasattr(self.m_adapter, "SETUP_DUMP_MAP"))
        self.assertFalse(hasattr(LmpAdapter, "TASK_TUNING_MAP"))
        self.assertFalse(hasattr(LmpAdapter, "SETUP_DUMP_MAP"))

        # 4. Tuning mapping can be passed directly as f_tuning
        f_cmd_tuning = self.m_adapter.buildCommand(
            f_executable=self.m_executable,
            f_setup="LSMIO-MMAP",
            f_tuning={"replication": 6, "buffer_size_mb": 64},
            f_working_dir=self.m_work_dir,
        )
        self.assertEqual(
            f_cmd_tuning.argv,
            (
                self.m_executable,
                "-in",
                "in.reaxc.hns",
                "-v",
                "x",
                "6",
                "-v",
                "y",
                "6",
                "-v",
                "z",
                "6",
                "-lsmio-mmap",
                "-lsmio-buf-size-mb",
                "64",
            ),
        )

    def testMissingSymlinkDirectoryUnreadableChangedAssetFails(self) -> None:
        """Assert os.lstat strictly rejects missing assets, directories, unreadable files, and symlinks."""
        with tempfile.TemporaryDirectory() as f_temp_base:
            f_asset_dir = os.path.join(f_temp_base, "assets")
            os.makedirs(f_asset_dir, exist_ok=True)

            f_content = b"valid content"
            with open(os.path.join(f_asset_dir, "in.reaxc.hns"), "wb") as f_f:
                f_f.write(f_content)
            with open(os.path.join(f_asset_dir, "data.hns-equil"), "wb") as f_f:
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

            with patch(
                "builtins.open", side_effect=PermissionError("Permission denied")
            ):
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
            f_replication=4,
            f_buffer_size_mb=32,
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
                    f_replication=4,
                    f_buffer_size_mb=32,
                    f_working_dir=f"/tmp/work_{f_token}",
                )
            with self.assertRaises(BenchmarkConfigurationError):
                self.m_adapter.buildCommand(
                    f_executable=f"/bin/lmp_{f_token}",
                    f_setup="LSMIO",
                    f_replication=4,
                    f_buffer_size_mb=32,
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

            # Create decoy files in decoy_dir
            with open(os.path.join(f_decoy_dir, "in.reaxc.hns"), "wb") as f_f:
                f_f.write(b"DECOY IN")
            with open(os.path.join(f_decoy_dir, "data.hns-equil"), "wb") as f_f:
                f_f.write(b"DECOY DATA")
            with open(os.path.join(f_decoy_dir, "ffield.reax.hns"), "wb") as f_f:
                f_f.write(b"DECOY FFIELD")

            # Create genuine files in real_assets
            f_real_in = b"GENUINE IN CONTENT"
            f_real_data = b"GENUINE DATA CONTENT"
            f_real_ffield = b"GENUINE FFIELD CONTENT"
            with open(os.path.join(f_asset_dir, "in.reaxc.hns"), "wb") as f_f:
                f_f.write(f_real_in)
            with open(os.path.join(f_asset_dir, "data.hns-equil"), "wb") as f_f:
                f_f.write(f_real_data)
            with open(os.path.join(f_asset_dir, "ffield.reax.hns"), "wb") as f_f:
                f_f.write(f_real_ffield)

            try:
                os.chdir(f_decoy_dir)

                # Staging uses explicit asset directory
                f_hashes = self.m_adapter.stageAssets(f_asset_dir, f_work_dir)
                self.assertEqual(
                    f_hashes["in.reaxc.hns"], hashlib.sha256(f_real_in).hexdigest()
                )

                # Verify staged files contain genuine content, NOT decoy content
                with open(os.path.join(f_work_dir, "in.reaxc.hns"), "rb") as f_f:
                    self.assertEqual(f_f.read(), f_real_in)
                with open(os.path.join(f_work_dir, "data.hns-equil"), "rb") as f_f:
                    self.assertEqual(f_f.read(), f_real_data)
                with open(os.path.join(f_work_dir, "ffield.reax.hns"), "rb") as f_f:
                    self.assertEqual(f_f.read(), f_real_ffield)

                # buildCommand paths are under real_work, not decoy_dir
                f_cmd = self.m_adapter.buildCommand(
                    f_executable=self.m_executable,
                    f_setup="LSMIO",
                    f_replication=8,
                    f_buffer_size_mb=128,
                    f_working_dir=f_work_dir,
                )
                self.assertEqual(f_cmd.working_dir, f_work_dir)
                self.assertTrue(f_cmd.stdout_path.startswith(f_work_dir))
                self.assertFalse(f_cmd.stdout_path.startswith(f_decoy_dir))

            finally:
                os.chdir(f_orig_cwd)

    def testProbeFailures(self) -> None:
        """Verify fail-closed handling for missing or unsupported LMP binaries and flag mismatches."""

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
            return MockProcessResult(
                returncode=127, stdout="", stderr="lmp: command not found"
            )

        with self.assertRaises(BenchmarkProbeError):
            self.m_adapter.probeCapability(
                f_executable=self.m_executable,
                f_runner=mockFailingRunner,
            )

        # 3. Runner output indicates unsupported capability
        def mockUnsupportedRunner(f_argv: Sequence[str]) -> MockProcessResult:
            return MockProcessResult(
                returncode=0, stdout="lmp: unsupported option -h", stderr=""
            )

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

        # 6. Setup flag mismatches:
        # 6a. LSMIO requires 'buf'
        with self.assertRaises(BenchmarkProbeError):
            self.m_adapter.probeCapability(
                f_executable=self.m_executable,
                f_runner=lambda argv: MockProcessResult(
                    0, "LAMMPS (2 Aug 2023)\n-lsmio-fallback", ""
                ),
                f_setup="LSMIO",
            )

        # 6b. LSMIO-MMAP requires 'buf' and 'mmap'
        with self.assertRaises(BenchmarkProbeError):
            self.m_adapter.probeCapability(
                f_executable=self.m_executable,
                f_runner=lambda argv: MockProcessResult(
                    0, "LAMMPS (2 Aug 2023)\n-lsmio-buf-size-mb", ""
                ),
                f_setup="LSMIO-MMAP",
            )

        # 6c. FS requires 'fallback'
        with self.assertRaises(BenchmarkProbeError):
            self.m_adapter.probeCapability(
                f_executable=self.m_executable,
                f_runner=lambda argv: MockProcessResult(
                    0, "LAMMPS (2 Aug 2023)\n-lsmio-buf-size-mb", ""
                ),
                f_setup="FS",
            )

    def testUnverifiedNoVersionClaim(self) -> None:
        """Prove unprobeable binaries remain recorded as configured/unverified, and verified when flags present."""
        f_state = self.m_adapter.probeCapability(
            f_executable=self.m_executable, f_runner=None
        )
        self.assertEqual(f_state, CapabilityState.CONFIGURED)
        self.assertEqual(f_state, ProbeState.CONFIGURED)
        self.assertTrue(f_state.is_configured)
        self.assertFalse(f_state.is_verified)
        self.assertFalse(f_state.is_unsupported)

        # When runner successfully returns valid LMP output exposing setup flags:
        # Setup LSMIO
        f_verified_lsmio = self.m_adapter.probeCapability(
            f_executable=self.m_executable,
            f_runner=lambda argv: MockProcessResult(
                0, "LAMMPS\n-lsmio-buf-size-mb\n", ""
            ),
            f_setup="LSMIO",
        )
        self.assertEqual(f_verified_lsmio, CapabilityState.VERIFIED)

        # Setup LSMIO-MMAP
        f_verified_mmap = self.m_adapter.probeCapability(
            f_executable=self.m_executable,
            f_runner=lambda argv: MockProcessResult(
                0, "LAMMPS\n-lsmio-buf-size-mb\n-lsmio-mmap\n", ""
            ),
            f_setup="LSMIO-MMAP",
        )
        self.assertEqual(f_verified_mmap, CapabilityState.VERIFIED)

        # Setup FS
        f_verified_fs = self.m_adapter.probeCapability(
            f_executable=self.m_executable,
            f_runner=lambda argv: MockProcessResult(0, "LAMMPS\n-lsmio-fallback\n", ""),
            f_setup="FS",
        )
        self.assertEqual(f_verified_fs, CapabilityState.VERIFIED)

    def testCommandImmutability(self) -> None:
        """Verify that BenchmarkCommand returned by LmpAdapter is immutable."""
        f_cmd = self.m_adapter.buildCommand(
            f_executable=self.m_executable,
            f_setup="LSMIO",
            f_replication=4,
            f_buffer_size_mb=32,
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
            f_replication=4,
            f_buffer_size_mb=32,
            f_working_dir=f_work_dir_with_spaces,
        )

        self.assertEqual(f_cmd.argv[0], f_exe_with_spaces)
        self.assertEqual(f_cmd.working_dir, f_work_dir_with_spaces)
        self.assertEqual(len(f_cmd.argv), 14)

    def testNulByteRejection(self) -> None:
        """Verify that NUL bytes in arguments or paths raise BenchmarkConfigurationError."""
        with self.assertRaises(BenchmarkConfigurationError):
            self.m_adapter.buildCommand(
                f_executable="/bin/lmp\0",
                f_setup="LSMIO",
                f_replication=4,
                f_buffer_size_mb=32,
                f_working_dir=self.m_work_dir,
            )

        with self.assertRaises(BenchmarkConfigurationError):
            self.m_adapter.buildCommand(
                f_executable=self.m_executable,
                f_setup="LSMIO",
                f_replication=4,
                f_buffer_size_mb=32,
                f_working_dir="/work\0dir",
            )

    def testAdapterProperties(self) -> None:
        """Verify adapter metadata properties."""
        self.assertEqual(self.m_adapter.target, "lmp")
        self.assertEqual(self.m_adapter.defaultSetup, "LSMIO")
        self.assertEqual(
            set(self.m_adapter.allowedSetups),
            {"LSMIO", "LSMIO-MMAP", "FS"},
        )

    def testRuntimeLayoutObjectSupport(self) -> None:
        """Verify passing RuntimeLayout object to stageAssets."""
        with tempfile.TemporaryDirectory() as f_temp_base:
            f_asset_dir = os.path.join(f_temp_base, "assets")
            os.makedirs(f_asset_dir, exist_ok=True)
            for f_name in ("in.reaxc.hns", "data.hns-equil", "ffield.reax.hns"):
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
            self.assertTrue(os.path.isfile(os.path.join(f_staged_work, "in.reaxc.hns")))
            self.assertTrue(
                os.path.isfile(os.path.join(f_staged_work, "data.hns-equil"))
            )
            self.assertTrue(
                os.path.isfile(os.path.join(f_staged_work, "ffield.reax.hns"))
            )

    def testValidateAssetsArgumentValidation(self) -> None:
        """Verify validateAssets argument validation (cases 033-A1, 033-A2)."""
        # 033-A1: non-string / empty asset_root raises BenchmarkConfigurationError
        for f_bad in (123, None, "", "   ", "\t"):
            with self.subTest(asset_root=f_bad):
                with self.assertRaises(BenchmarkConfigurationError) as f_cm:
                    self.m_adapter.validateAssets(f_bad)  # type: ignore[arg-type]
                self.assertIn(
                    "Asset root must be a non-empty string", str(f_cm.exception)
                )

        # 033-A2: NUL byte in asset_root
        with self.assertRaises(BenchmarkConfigurationError) as f_cm:
            self.m_adapter.validateAssets("/tmp/assets\0dir")
        self.assertIn("Asset root contains NUL byte:", str(f_cm.exception))

    def testStageAssetsSourceAndDirectoryValidation(self) -> None:
        """Verify stageAssets source and directory validation (cases 033-B1 to 033-B4)."""
        # 033-B1: layout object with camelCase assetRoot
        with tempfile.TemporaryDirectory() as f_temp_base:
            f_asset_dir = os.path.join(f_temp_base, "assets")
            os.makedirs(f_asset_dir, exist_ok=True)
            for f_name in ("in.reaxc.hns", "data.hns-equil", "ffield.reax.hns"):
                with open(os.path.join(f_asset_dir, f_name), "wb") as f_f:
                    f_f.write(b"content")

            class LayoutWithCamelCase:
                assetRoot = f_asset_dir

            f_staged_work = os.path.join(f_temp_base, "work")
            f_hashes = self.m_adapter.stageAssets(LayoutWithCamelCase(), f_staged_work)
            self.assertEqual(len(f_hashes), 3)
            self.assertTrue(os.path.isfile(os.path.join(f_staged_work, "in.reaxc.hns")))

        # 033-B2: invalid asset_source type raises BenchmarkConfigurationError
        for f_bad in (123, None, [], {"root": "/tmp"}):
            with self.subTest(asset_source=f_bad):
                with self.assertRaises(BenchmarkConfigurationError) as f_cm:
                    self.m_adapter.stageAssets(f_bad, "/tmp/work")  # type: ignore[arg-type]
                self.assertIn(
                    "Asset source must be a string path or RuntimeLayout object",
                    str(f_cm.exception),
                )

        # 033-B3: working_dir non-string / empty
        for f_bad in (123, None, "", "   "):
            with self.subTest(work_dir=f_bad):
                with self.assertRaises(BenchmarkConfigurationError) as f_cm:
                    self.m_adapter.stageAssets("/tmp/assets", f_bad)  # type: ignore[arg-type]
                self.assertIn(
                    "Working directory must be a non-empty string", str(f_cm.exception)
                )

        # 033-B4: working_dir contains NUL byte
        with self.assertRaises(BenchmarkConfigurationError) as f_cm:
            self.m_adapter.stageAssets("/tmp/assets", "/tmp/work\0dir")
        self.assertIn("Working directory contains NUL byte:", str(f_cm.exception))

    def testStageAssetsFileSystemFailures(self) -> None:
        """Verify stageAssets handles filesystem errors when creating directories or staging files (cases 033-C1, 033-C2)."""
        with tempfile.TemporaryDirectory() as f_temp_base:
            f_asset_dir = os.path.join(f_temp_base, "assets")
            os.makedirs(f_asset_dir, exist_ok=True)
            for f_name in ("in.reaxc.hns", "data.hns-equil", "ffield.reax.hns"):
                with open(os.path.join(f_asset_dir, f_name), "wb") as f_f:
                    f_f.write(b"content")

            # 033-C1: os.makedirs failure
            with patch(
                "os.makedirs", side_effect=OSError("Makedirs permission denied")
            ):
                with self.assertRaises(BenchmarkConfigurationError) as f_cm_mkdir:
                    self.m_adapter.stageAssets(f_asset_dir, "/tmp/fail_work")
                self.assertIn(
                    "Failed to create LMP working directory", str(f_cm_mkdir.exception)
                )
                self.assertIsInstance(f_cm_mkdir.exception.__cause__, OSError)

            # 033-C2: file write failure
            f_real_open = open

            def _failing_open(
                f_path: Any, f_mode: str = "r", *f_args: Any, **f_kwargs: Any
            ) -> Any:
                if "wb" in f_mode and "fail_stage" in str(f_path):
                    raise OSError("Disk write error")
                return f_real_open(f_path, f_mode, *f_args, **f_kwargs)

            with patch("builtins.open", side_effect=_failing_open):
                with self.assertRaises(BenchmarkConfigurationError) as f_cm_write:
                    self.m_adapter.stageAssets(
                        f_asset_dir, os.path.join(f_temp_base, "fail_stage")
                    )
                self.assertIn("Failed to stage LMP asset", str(f_cm_write.exception))
                self.assertIsInstance(f_cm_write.exception.__cause__, OSError)

    def testBuildCommandArgumentValidation(self) -> None:
        """Verify buildCommand argument validation for executable, setup, replication, buffer, working_dir (cases 033-D1 to 033-D7)."""
        # 033-D1: executable invalid / empty
        for f_bad in (123, None, "", "   "):
            with self.subTest(executable=f_bad):
                with self.assertRaises(BenchmarkConfigurationError) as f_cm:
                    self.m_adapter.buildCommand(
                        f_bad,  # type: ignore[arg-type]
                        f_setup="LSMIO",
                        f_replication=4,
                        f_buffer_size_mb=32,
                    )
                self.assertIn(
                    "Executable must be a non-empty string", str(f_cm.exception)
                )

        # 033-D2: setup invalid / empty
        for f_bad in (123, None, "", "   "):
            with self.subTest(setup=f_bad):
                with self.assertRaises(BenchmarkConfigurationError) as f_cm:
                    self.m_adapter.buildCommand(
                        self.m_executable,
                        f_setup=f_bad,  # type: ignore[arg-type]
                        f_replication=4,
                        f_buffer_size_mb=32,
                    )
                self.assertIn("Setup must be a non-empty string", str(f_cm.exception))

        # 033-D3: unknown setup
        for f_bad in ("UNKNOWN", "INVALID", "MPIIO"):
            with self.subTest(setup=f_bad):
                with self.assertRaises(BenchmarkConfigurationError) as f_cm:
                    self.m_adapter.buildCommand(
                        self.m_executable,
                        f_setup=f_bad,
                        f_replication=4,
                        f_buffer_size_mb=32,
                    )
                self.assertIn("Unknown LMP setup:", str(f_cm.exception))

        # 033-D4: replication non-positive or non-int
        for f_bad in (0, -1, -10, True, False, "4", 4.5):
            with self.subTest(replication=f_bad):
                with self.assertRaises(BenchmarkConfigurationError) as f_cm:
                    self.m_adapter.buildCommand(
                        self.m_executable,
                        f_setup="LSMIO",
                        f_replication=f_bad,  # type: ignore[arg-type]
                        f_buffer_size_mb=32,
                    )
                self.assertIn(
                    "LMP replication must be a positive integer", str(f_cm.exception)
                )

        # 033-D5: buffer_size_mb required for LSMIO and LSMIO-MMAP
        for f_setup in ("LSMIO", "LSMIO-MMAP"):
            with self.subTest(setup=f_setup):
                with self.assertRaises(BenchmarkConfigurationError) as f_cm:
                    self.m_adapter.buildCommand(
                        self.m_executable,
                        f_setup=f_setup,
                        f_replication=4,
                        f_buffer_size_mb=None,
                    )
                self.assertIn(
                    "LMP buffer_size_mb is required for setup", str(f_cm.exception)
                )

        # 033-D6: buffer_size_mb non-positive or non-int
        for f_bad in (0, -1, -32, True, False, "32", 32.0):
            with self.subTest(buffer_size_mb=f_bad):
                with self.assertRaises(BenchmarkConfigurationError) as f_cm:
                    self.m_adapter.buildCommand(
                        self.m_executable,
                        f_setup="LSMIO",
                        f_replication=4,
                        f_buffer_size_mb=f_bad,  # type: ignore[arg-type]
                    )
                self.assertIn(
                    "LMP buffer_size_mb must be a positive integer", str(f_cm.exception)
                )

        # 033-D7: working_dir invalid / empty
        for f_bad in (123, None, "", "   "):
            with self.subTest(working_dir=f_bad):
                with self.assertRaises(BenchmarkConfigurationError) as f_cm:
                    self.m_adapter.buildCommand(
                        self.m_executable,
                        f_setup="LSMIO",
                        f_replication=4,
                        f_buffer_size_mb=32,
                        f_working_dir=f_bad,  # type: ignore[arg-type]
                    )
                self.assertIn(
                    "Working directory must be a non-empty string", str(f_cm.exception)
                )

    def testBuildCommandPathValidation(self) -> None:
        """Verify stdout_path and stderr_path validation in buildCommand (cases 033-E1 to 033-E4)."""
        # 033-E1: stdout_path non-string / empty
        for f_bad in (123, "", "   ", "\t"):
            with self.subTest(stdout_path=f_bad):
                with self.assertRaises(BenchmarkConfigurationError) as f_cm:
                    self.m_adapter.buildCommand(
                        self.m_executable,
                        f_setup="LSMIO",
                        f_replication=4,
                        f_buffer_size_mb=32,
                        f_stdout_path=f_bad,  # type: ignore[arg-type]
                    )
                self.assertIn(
                    "Stdout path must be a non-empty string", str(f_cm.exception)
                )

        # 033-E2: stdout_path contains NUL byte
        with self.assertRaises(BenchmarkConfigurationError) as f_cm:
            self.m_adapter.buildCommand(
                self.m_executable,
                f_setup="LSMIO",
                f_replication=4,
                f_buffer_size_mb=32,
                f_stdout_path="/tmp/stdout\0.log",
            )
        self.assertIn("Stdout path contains NUL byte:", str(f_cm.exception))

        # 033-E3: stderr_path non-string / empty
        for f_bad in (123, "", "   ", "\n"):
            with self.subTest(stderr_path=f_bad):
                with self.assertRaises(BenchmarkConfigurationError) as f_cm:
                    self.m_adapter.buildCommand(
                        self.m_executable,
                        f_setup="LSMIO",
                        f_replication=4,
                        f_buffer_size_mb=32,
                        f_stderr_path=f_bad,  # type: ignore[arg-type]
                    )
                self.assertIn(
                    "Stderr path must be a non-empty string", str(f_cm.exception)
                )

        # 033-E4: stderr_path contains NUL byte
        with self.assertRaises(BenchmarkConfigurationError) as f_cm:
            self.m_adapter.buildCommand(
                self.m_executable,
                f_setup="LSMIO",
                f_replication=4,
                f_buffer_size_mb=32,
                f_stderr_path="/tmp/stderr\0.log",
            )
        self.assertIn("Stderr path contains NUL byte:", str(f_cm.exception))

    def testBuildCommandCustomSetupFallthrough(self) -> None:
        """Verify buildCommand custom setup fall-through without backend flags (case 033-F1)."""
        f_custom_adapter = LmpAdapter()
        f_custom_adapter.ALLOWED_SETUPS = ("LSMIO", "LSMIO-MMAP", "FS", "CUSTOM")  # type: ignore[assignment]
        f_cmd = f_custom_adapter.buildCommand(
            self.m_executable,
            f_setup="CUSTOM",
            f_replication=4,
            f_working_dir=self.m_work_dir,
        )
        f_expected_argv = (
            self.m_executable,
            "-in",
            "in.reaxc.hns",
            "-v",
            "x",
            "4",
            "-v",
            "y",
            "4",
            "-v",
            "z",
            "4",
        )
        self.assertEqual(f_cmd.argv, f_expected_argv)

    def testBuildCommandConvenienceAliases(self) -> None:
        """Verify convenience aliases buildBenchmarkCommand, createCommand, and build_command (case 033-G1)."""
        f_kwargs = {
            "f_executable": self.m_executable,
            "f_setup": "LSMIO",
            "f_replication": 4,
            "f_buffer_size_mb": 32,
            "f_working_dir": self.m_work_dir,
        }
        f_golden = self.m_adapter.buildCommand(**f_kwargs)
        self.assertEqual(self.m_adapter.buildBenchmarkCommand(**f_kwargs), f_golden)
        self.assertEqual(self.m_adapter.createCommand(**f_kwargs), f_golden)
        self.assertEqual(self.m_adapter.build_command(**f_kwargs), f_golden)

    def testProbeCapabilityValidation(self) -> None:
        """Verify probeCapability executable validation (cases 033-H1, 033-H2)."""
        # 033-H1: non-string / empty executable
        for f_bad in (123, None, "", "   "):
            with self.subTest(executable=f_bad):
                with self.assertRaises(BenchmarkConfigurationError) as f_cm:
                    self.m_adapter.probeCapability(f_executable=f_bad)  # type: ignore[arg-type]
                self.assertIn(
                    "Executable must be a non-empty string", str(f_cm.exception)
                )

        # 033-H2: NUL byte in executable
        with self.assertRaises(BenchmarkConfigurationError) as f_cm:
            self.m_adapter.probeCapability(f_executable="/bin/lmp\0")
        self.assertIn("Executable contains NUL byte:", str(f_cm.exception))

    def testProbeCapabilityUnexpectedException(self) -> None:
        """Verify unexpected runner exceptions are wrapped in BenchmarkProbeError (case 033-I1)."""

        def _failingRunner(_argv: Sequence[str]) -> Any:
            raise RuntimeError("Unexpected LMP probe crash")

        with self.assertRaises(BenchmarkProbeError) as f_cm:
            self.m_adapter.probeCapability(
                self.m_executable,
                f_runner=_failingRunner,
                f_setup="LSMIO",
            )
        self.assertIn(
            "LMP probe runner raised unexpected error for",
            str(f_cm.exception),
        )
        self.assertIsInstance(f_cm.exception.__cause__, RuntimeError)

    def testProbeCapabilityRunnerResultTypes(self) -> None:
        """Verify probeCapability handling across runner result types (cases 033-J1 to 033-J6)."""

        # 033-J1: result with exit_code attribute (no returncode)
        class ExitCodeResult:
            exit_code = 0
            stdout = "LAMMPS buf"
            stderr = ""

        f_res_exit = self.m_adapter.probeCapability(
            self.m_executable,
            f_runner=lambda a: ExitCodeResult(),
            f_setup="LSMIO",
        )
        self.assertEqual(f_res_exit, CapabilityState.VERIFIED)

        # 033-J2: 3-tuple result (exit_code, stdout, stderr)
        f_res_tuple3 = self.m_adapter.probeCapability(
            self.m_executable,
            f_runner=lambda a: (0, "LAMMPS buf", "stderr output"),
            f_setup="LSMIO",
        )
        self.assertEqual(f_res_tuple3, CapabilityState.VERIFIED)

        # 033-J3: 2-tuple result (exit_code, stdout)
        f_res_tuple2 = self.m_adapter.probeCapability(
            self.m_executable,
            f_runner=lambda a: (0, "LAMMPS buf"),
            f_setup="LSMIO",
        )
        self.assertEqual(f_res_tuple2, CapabilityState.VERIFIED)

        # 033-J4: int result (non-zero and zero)
        with self.assertRaises(BenchmarkProbeError) as f_cm_fail:
            self.m_adapter.probeCapability(
                self.m_executable,
                f_runner=lambda a: 1,
                f_setup="LSMIO",
            )
        self.assertIn("probe failed with exit code 1", str(f_cm_fail.exception))

        with self.assertRaises(BenchmarkProbeError) as f_cm_empty:
            self.m_adapter.probeCapability(
                self.m_executable,
                f_runner=lambda a: 0,
                f_setup="LSMIO",
            )
        self.assertIn("produced empty probe output", str(f_cm_empty.exception))

        # 033-J5: str result
        f_res_str = self.m_adapter.probeCapability(
            self.m_executable,
            f_runner=lambda a: "LAMMPS -lsmio-buf-size-mb",
            f_setup="LSMIO",
        )
        self.assertEqual(f_res_str, CapabilityState.VERIFIED)

        # 033-J6: custom object with __str__ returning banner text
        class CustomStrResult:
            def __str__(self) -> str:
                return "LAMMPS -lsmio-buf-size-mb"

        f_res_custom = self.m_adapter.probeCapability(
            self.m_executable,
            f_runner=lambda a: CustomStrResult(),
            f_setup="LSMIO",
        )
        self.assertEqual(f_res_custom, CapabilityState.VERIFIED)

    def testProbeCapabilityFallbackSetupAndUnrecognizedOutput(self) -> None:
        """Verify fallback setup probing and unrecognized help output (cases 033-K1, 033-K2)."""
        f_custom_adapter = LmpAdapter()
        f_custom_adapter.ALLOWED_SETUPS = ("LSMIO", "LSMIO-MMAP", "FS", "BASE")  # type: ignore[assignment]

        # 033-K1: fallback setup with recognized lammps banner
        f_res = f_custom_adapter.probeCapability(
            self.m_executable,
            f_runner=lambda a: (0, "LAMMPS 2023 version", ""),
            f_setup="BASE",
        )
        self.assertEqual(f_res, CapabilityState.VERIFIED)

        # 033-K2: fallback setup with unrecognized output
        with self.assertRaises(BenchmarkProbeError) as f_cm:
            f_custom_adapter.probeCapability(
                self.m_executable,
                f_runner=lambda a: (
                    0,
                    "unrecognized banner text with neither keyword",
                    "",
                ),
                f_setup="BASE",
            )
        self.assertIn("produced unrecognized help output:", str(f_cm.exception))

    def testProbeCapabilityNoneSetupDefaultsToLsmio(self) -> None:
        """Verify that when f_setup is None, probeCapability defaults to LSMIO and returns VERIFIED."""
        # Setup None defaults to LSMIO; when output exposes required 'buf' flag, capability is verified
        f_res = self.m_adapter.probeCapability(
            self.m_executable,
            f_runner=lambda a: (0, "LAMMPS (2 Aug 2023) -lsmio-buf-size-mb", ""),
            f_setup=None,
        )
        self.assertEqual(f_res, CapabilityState.VERIFIED)

        # Confirm it defaulted to LSMIO by checking that missing 'buf' raises BenchmarkProbeError for setup 'LSMIO'
        with self.assertRaises(BenchmarkProbeError) as f_cm:
            self.m_adapter.probeCapability(
                self.m_executable,
                f_runner=lambda a: (0, "LAMMPS (2 Aug 2023) without required flag", ""),
                f_setup=None,
            )
        self.assertIn(
            "required buffer flag ('buf') for setup 'LSMIO'", str(f_cm.exception)
        )


if __name__ == "__main__":
    unittest.main()
