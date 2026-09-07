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

from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple
import unittest

from lsmiotool.lib.benchmarks import (
    BenchmarkCommand,
    BenchmarkConfigurationError,
    BenchmarkProbeError,
    CapabilityState,
    IorAdapter,
    ProbeState,
)
from lsmiotool.lib.run import Combination


class MockProcessResult(NamedTuple):
    returncode: int
    stdout: str
    stderr: str


class IorAdapterTest(unittest.TestCase):
    """Comprehensive test suite for IorAdapter contract and invariants."""

    def setUp(self) -> None:
        self.m_adapter = IorAdapter()
        self.m_executable = "/opt/ior/bin/ior"
        self.m_work_dir = "/benchmark/runs/run-123/points/00-tasks-1/work/c16_b8M"
        self.m_out_path = (
            "/benchmark/runs/run-123/points/00-tasks-1/data/c16/b8M/ior.base"
        )

    def testUpstreamLiteralParityEveryMode(self) -> None:
        """Validate exact upstream-golden argv for all 6 setups across all 3 block sizes (18 combinations total)."""
        f_setups = ["BASE", "HDF5", "HDF5-C", "COLLECTIVE", "FSYNC", "REVERSE"]
        f_block_sizes = ["64K", "1M", "8M"]
        f_segments = {
            "64K": "16384",
            "1M": "1024",
            "8M": "128",
        }
        f_extra_flags = {
            "BASE": (),
            "HDF5": ("-a", "HDF5"),
            "HDF5-C": ("-c", "-a", "HDF5"),
            "COLLECTIVE": ("-c", "-a", "MPIIO"),
            "FSYNC": ("-e",),
            "REVERSE": ("-C",),
        }

        f_tested_count = 0
        for f_setup in f_setups:
            for f_bs in f_block_sizes:
                f_out_path = f"/benchmark/runs/run-123/points/00-tasks-1/data/c16/b{f_bs}/ior.{f_setup.lower()}"
                f_cmd = self.m_adapter.buildCommand(
                    f_executable=self.m_executable,
                    f_setup=f_setup,
                    f_block_size=f_bs,
                    f_working_dir=self.m_work_dir,
                    f_output_path=f_out_path,
                )

                f_expected_argv = (
                    self.m_executable,
                    "-v",
                    "-w",
                    "-r",
                    "-i=10",
                    *f_extra_flags[f_setup],
                    "-o",
                    f_out_path,
                    f"-t={f_bs}",
                    f"-b={f_bs}",
                    f"-s={f_segments[f_bs]}",
                )

                self.assertEqual(
                    f_cmd.argv,
                    f_expected_argv,
                    f"Argv mismatch for setup={f_setup} block_size={f_bs}",
                )
                self.assertEqual(f_cmd.is_rank_local, False)
                self.assertEqual(f_cmd.isRankLocal, False)
                f_tested_count += 1

        self.assertEqual(f_tested_count, 18)

    def testSharedPrivatePathsNoRank(self) -> None:
        """Validate that IOR output and log paths are shared across the point and contain no rank placeholders."""
        f_cmd = self.m_adapter.buildCommand(
            f_executable=self.m_executable,
            f_setup="BASE",
            f_block_size="8M",
            f_working_dir=self.m_work_dir,
        )

        self.assertFalse(f_cmd.is_rank_local)
        self.assertFalse(f_cmd.isRankLocal)

        # Ensure no rank tokens appear anywhere in argv or paths
        f_rank_tokens = ["{rank}", "{global_rank}", "{local_rank}", "%r", "@RANK@"]
        for f_token in f_rank_tokens:
            for f_arg in f_cmd.argv:
                self.assertNotIn(f_token, f_arg)
            self.assertNotIn(f_token, f_cmd.stdout_path)
            self.assertNotIn(f_token, f_cmd.stderr_path)
            self.assertNotIn(f_token, f_cmd.working_dir)

        # Output and logs are beneath work dir
        self.assertTrue(f_cmd.stdout_path.startswith(self.m_work_dir))
        self.assertTrue(f_cmd.stderr_path.startswith(self.m_work_dir))

        # Explicit rank placeholders passed to buildCommand must be rejected
        for f_token in f_rank_tokens:
            with self.assertRaises(BenchmarkConfigurationError):
                self.m_adapter.buildCommand(
                    f_executable=self.m_executable,
                    f_setup="BASE",
                    f_block_size="8M",
                    f_working_dir=f"/tmp/work_{f_token}",
                )
            with self.assertRaises(BenchmarkConfigurationError):
                self.m_adapter.buildCommand(
                    f_executable=self.m_executable,
                    f_setup="BASE",
                    f_block_size="8M",
                    f_working_dir=self.m_work_dir,
                    f_output_path=f"/tmp/out_{f_token}.dat",
                )

    def testProbeFailures(self) -> None:
        """Verify fail-closed handling for missing or unsupported IOR binaries."""

        # 1. Runner raises FileNotFoundError
        def mockMissingBinary(f_argv: Sequence[str]) -> MockProcessResult:
            raise FileNotFoundError("Executable not found: /path/to/missing_ior")

        with self.assertRaises(BenchmarkProbeError):
            self.m_adapter.probeCapability(
                f_executable="/path/to/missing_ior",
                f_runner=mockMissingBinary,
            )

        # 2. Runner returns non-zero exit code
        def mockFailingRunner(f_argv: Sequence[str]) -> MockProcessResult:
            return MockProcessResult(
                returncode=127, stdout="", stderr="ior: command not found"
            )

        with self.assertRaises(BenchmarkProbeError):
            self.m_adapter.probeCapability(
                f_executable=self.m_executable,
                f_runner=mockFailingRunner,
            )

        # 3. Runner output indicates unsupported capability / error
        def mockUnsupportedRunner(f_argv: Sequence[str]) -> MockProcessResult:
            return MockProcessResult(
                returncode=0, stdout="IOR: unsupported option -v", stderr=""
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

        # 5. Probing with invalid setup requested
        with self.assertRaises(BenchmarkProbeError):
            self.m_adapter.probeCapability(
                f_executable=self.m_executable,
                f_runner=lambda argv: MockProcessResult(0, "IOR-3.3.0", ""),
                f_setup="NON_EXISTENT_SETUP",
            )

    def testUnverifiedNoVersionClaim(self) -> None:
        """Prove unprobeable binaries remain recorded as configured/unverified."""
        # When runner is None, returns CapabilityState.CONFIGURED without claiming version
        f_state = self.m_adapter.probeCapability(
            f_executable=self.m_executable, f_runner=None
        )
        self.assertEqual(f_state, CapabilityState.CONFIGURED)
        self.assertEqual(f_state, ProbeState.CONFIGURED)
        self.assertTrue(f_state.is_configured)
        self.assertFalse(f_state.is_verified)
        self.assertFalse(f_state.is_unsupported)

        # When runner successfully returns valid IOR output, returns CapabilityState.VERIFIED
        def mockSuccessRunner(f_argv: Sequence[str]) -> MockProcessResult:
            self.assertEqual(f_argv, [self.m_executable, "-v"])
            return MockProcessResult(
                returncode=0, stdout="IOR-3.3.0: Parallel IO Benchmark", stderr=""
            )

        f_verified_state = self.m_adapter.probeCapability(
            f_executable=self.m_executable,
            f_runner=mockSuccessRunner,
        )
        self.assertEqual(f_verified_state, CapabilityState.VERIFIED)
        self.assertTrue(f_verified_state.is_verified)
        self.assertFalse(f_verified_state.is_configured)

    def testSpacesRemainArgv(self) -> None:
        """Verify argv tokens with spaces remain discrete arguments and are not word-split."""
        f_exe_with_spaces = "/opt/my tools/bin/ior executable"
        f_work_dir_with_spaces = "/scratch/user run/points/00 tasks/work dir"
        f_out_path_with_spaces = (
            "/scratch/user run/points/00 tasks/data/ior output file.dat"
        )

        f_cmd = self.m_adapter.buildCommand(
            f_executable=f_exe_with_spaces,
            f_setup="BASE",
            f_block_size="8M",
            f_working_dir=f_work_dir_with_spaces,
            f_output_path=f_out_path_with_spaces,
        )

        self.assertEqual(f_cmd.argv[0], f_exe_with_spaces)
        self.assertEqual(f_cmd.argv[1], "-v")
        self.assertEqual(f_cmd.argv[2], "-w")
        self.assertEqual(f_cmd.argv[3], "-r")
        self.assertEqual(f_cmd.argv[4], "-i=10")
        self.assertEqual(f_cmd.argv[5], "-o")
        self.assertEqual(f_cmd.argv[6], f_out_path_with_spaces)
        self.assertEqual(f_cmd.argv[7], "-t=8M")
        self.assertEqual(f_cmd.argv[8], "-b=8M")
        self.assertEqual(f_cmd.argv[9], "-s=128")
        self.assertEqual(len(f_cmd.argv), 10)

    def testCommandImmutability(self) -> None:
        """Verify that BenchmarkCommand is immutable."""
        f_cmd = self.m_adapter.buildCommand(
            f_executable=self.m_executable,
            f_setup="BASE",
            f_block_size="1M",
            f_working_dir=self.m_work_dir,
        )
        with self.assertRaises(AttributeError):
            f_cmd.m_argv = ("new", "argv")
        with self.assertRaises(AttributeError):
            f_cmd.m_stdout_path = "/new/path"
        with self.assertRaises(AttributeError):
            del f_cmd.m_argv

    def testInvalidSetupsAndBlockSizes(self) -> None:
        """Verify that invalid setup names or unsupported block sizes raise errors."""
        with self.assertRaises(BenchmarkConfigurationError):
            self.m_adapter.buildCommand(
                f_executable=self.m_executable,
                f_setup="INVALID_SETUP",
                f_block_size="8M",
                f_working_dir=self.m_work_dir,
            )

        with self.assertRaises(BenchmarkConfigurationError):
            self.m_adapter.buildCommand(
                f_executable=self.m_executable,
                f_setup="BASE",
                f_block_size="2M",  # unsupported block size
                f_working_dir=self.m_work_dir,
            )

        with self.assertRaises(BenchmarkConfigurationError):
            self.m_adapter.buildCommand(
                f_executable=self.m_executable,
                f_setup="BASE",
                f_block_size=None,
                f_combination=None,
                f_working_dir=self.m_work_dir,
            )

    def testCombinationObjectSupport(self) -> None:
        """Verify that passing Combination objects from lib.run works seamlessly."""
        f_combo = Combination(
            f_processes=16,
            f_block_size="1M",
            f_stripe_count=16,
            f_block_bytes=1048576,
            f_key_count=4096,
            f_segment_count=1024,
        )

        f_cmd = self.m_adapter.buildCommand(
            f_executable=self.m_executable,
            f_setup="COLLECTIVE",
            f_combination=f_combo,
            f_working_dir=self.m_work_dir,
        )

        self.assertIn("-b=1M", f_cmd.argv)
        self.assertIn("-t=1M", f_cmd.argv)
        self.assertIn("-s=1024", f_cmd.argv)
        self.assertIn("-c", f_cmd.argv)
        self.assertIn("-a", f_cmd.argv)
        self.assertIn("MPIIO", f_cmd.argv)

    def testNulByteRejection(self) -> None:
        """Verify that NUL bytes in arguments or paths raise BenchmarkConfigurationError."""
        with self.assertRaises(BenchmarkConfigurationError):
            self.m_adapter.buildCommand(
                f_executable="/bin/ior\0",
                f_setup="BASE",
                f_block_size="8M",
                f_working_dir=self.m_work_dir,
            )

        with self.assertRaises(BenchmarkConfigurationError):
            self.m_adapter.buildCommand(
                f_executable=self.m_executable,
                f_setup="BASE",
                f_block_size="8M",
                f_working_dir="/work\0dir",
            )

    def testAdapterProperties(self) -> None:
        """Verify adapter metadata properties."""
        self.assertEqual(self.m_adapter.target, "ior")
        self.assertEqual(self.m_adapter.defaultSetup, "BASE")
        self.assertEqual(
            set(self.m_adapter.allowedSetups),
            {"BASE", "HDF5", "HDF5-C", "COLLECTIVE", "FSYNC", "REVERSE"},
        )
        self.assertEqual(IorAdapter.getSegments("64K"), 16384)
        self.assertEqual(IorAdapter.getSegments("1M"), 1024)
        self.assertEqual(IorAdapter.getSegments("8M"), 128)

    def testEqualityHashAndDict(self) -> None:
        """Verify equality, hashing, and dict conversion of BenchmarkCommand."""
        f_cmd1 = self.m_adapter.buildCommand(
            f_executable=self.m_executable,
            f_setup="BASE",
            f_block_size="8M",
            f_working_dir=self.m_work_dir,
        )
        f_cmd2 = self.m_adapter.buildCommand(
            f_executable=self.m_executable,
            f_setup="BASE",
            f_block_size="8M",
            f_working_dir=self.m_work_dir,
        )
        f_cmd3 = self.m_adapter.buildCommand(
            f_executable=self.m_executable,
            f_setup="HDF5",
            f_block_size="8M",
            f_working_dir=self.m_work_dir,
        )

        self.assertEqual(f_cmd1, f_cmd2)
        self.assertEqual(hash(f_cmd1), hash(f_cmd2))
        self.assertNotEqual(f_cmd1, f_cmd3)

        f_dict = f_cmd1.toDict()
        self.assertEqual(f_dict["argv"], list(f_cmd1.argv))
        self.assertEqual(f_dict["stdout_path"], f_cmd1.stdout_path)
        self.assertEqual(f_dict["stderr_path"], f_cmd1.stderr_path)
        self.assertEqual(f_dict["working_dir"], f_cmd1.working_dir)
        self.assertEqual(f_dict["is_rank_local"], False)


if __name__ == "__main__":
    unittest.main()
