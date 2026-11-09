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

    def testSegmentsValidation(self) -> None:
        """Verify getSegments argument type and value validation (cases 030-A1, 030-A2)."""
        # 030-A1: non-string block size raises BenchmarkConfigurationError
        for f_bad in (123, None, [], {"bs": "1M"}):
            with self.subTest(block_size=f_bad):
                with self.assertRaises(BenchmarkConfigurationError) as f_cm:
                    IorAdapter.getSegments(f_bad)  # type: ignore[arg-type]
                self.assertIn("Block size must be a string, got:", str(f_cm.exception))

        # 030-A2: unsupported block size string raises BenchmarkConfigurationError
        for f_unsupported in ("2M", "16M", "32K", "INVALID"):
            with self.subTest(block_size=f_unsupported):
                with self.assertRaises(BenchmarkConfigurationError) as f_cm:
                    IorAdapter.getSegments(f_unsupported)
                self.assertIn("Unsupported IOR block size:", str(f_cm.exception))
                self.assertIn("Allowed: ['64K', '1M', '8M']", str(f_cm.exception))

    def testBuildCommandArgumentValidation(self) -> None:
        """Verify buildCommand input argument validation for executable, setup, block_size, and working_dir (cases 030-B1 to 030-B4)."""
        # 030-B1: executable invalid / empty
        for f_bad_exe in (123, None, "", "   ", "\t"):
            with self.subTest(executable=f_bad_exe):
                with self.assertRaises(BenchmarkConfigurationError) as f_cm:
                    self.m_adapter.buildCommand(
                        f_executable=f_bad_exe,  # type: ignore[arg-type]
                        f_block_size="1M",
                    )
                self.assertIn(
                    "Executable must be a non-empty string", str(f_cm.exception)
                )

        # 030-B2: setup invalid / empty
        for f_bad_setup in (123, None, "", "   "):
            with self.subTest(setup=f_bad_setup):
                with self.assertRaises(BenchmarkConfigurationError) as f_cm:
                    self.m_adapter.buildCommand(
                        self.m_executable,
                        f_setup=f_bad_setup,  # type: ignore[arg-type]
                        f_block_size="1M",
                    )
                self.assertIn("Setup must be a non-empty string", str(f_cm.exception))

        # 030-B3: block_size invalid / empty string
        for f_bad_bs in (123, "", "   ", "\n"):
            with self.subTest(block_size=f_bad_bs):
                with self.assertRaises(BenchmarkConfigurationError) as f_cm:
                    self.m_adapter.buildCommand(
                        self.m_executable,
                        f_block_size=f_bad_bs,  # type: ignore[arg-type]
                    )
                self.assertIn(
                    "Block size must be a non-empty string", str(f_cm.exception)
                )

        # 030-B4: working_dir invalid / empty
        for f_bad_dir in (123, None, "", "   "):
            with self.subTest(working_dir=f_bad_dir):
                with self.assertRaises(BenchmarkConfigurationError) as f_cm:
                    self.m_adapter.buildCommand(
                        self.m_executable,
                        f_block_size="1M",
                        f_working_dir=f_bad_dir,  # type: ignore[arg-type]
                    )
                self.assertIn(
                    "Working directory must be a non-empty string", str(f_cm.exception)
                )

    def testBuildCommandPathValidation(self) -> None:
        """Verify output_path, stdout_path, and stderr_path validation in buildCommand (cases 030-C1 to 030-C6)."""
        # 030-C1: output_path non-string / empty
        for f_bad in (123, "", "   ", "\t"):
            with self.subTest(output_path=f_bad):
                with self.assertRaises(BenchmarkConfigurationError) as f_cm:
                    self.m_adapter.buildCommand(
                        self.m_executable,
                        f_block_size="1M",
                        f_output_path=f_bad,  # type: ignore[arg-type]
                    )
                self.assertIn(
                    "Output path must be a non-empty string", str(f_cm.exception)
                )

        # 030-C2: output_path contains NUL byte
        with self.assertRaises(BenchmarkConfigurationError) as f_cm:
            self.m_adapter.buildCommand(
                self.m_executable,
                f_block_size="1M",
                f_output_path="/tmp/out\0file.dat",
            )
        self.assertIn("Output path contains NUL byte:", str(f_cm.exception))

        # 030-C3: stdout_path non-string / empty
        for f_bad in (123, "", "   ", "\n"):
            with self.subTest(stdout_path=f_bad):
                with self.assertRaises(BenchmarkConfigurationError) as f_cm:
                    self.m_adapter.buildCommand(
                        self.m_executable,
                        f_block_size="1M",
                        f_stdout_path=f_bad,  # type: ignore[arg-type]
                    )
                self.assertIn(
                    "Stdout path must be a non-empty string", str(f_cm.exception)
                )

        # 030-C4: stdout_path contains NUL byte
        with self.assertRaises(BenchmarkConfigurationError) as f_cm:
            self.m_adapter.buildCommand(
                self.m_executable,
                f_block_size="1M",
                f_stdout_path="/tmp/stdout\0.log",
            )
        self.assertIn("Stdout path contains NUL byte:", str(f_cm.exception))

        # 030-C5: stderr_path non-string / empty
        for f_bad in (123, "", "   ", "\t"):
            with self.subTest(stderr_path=f_bad):
                with self.assertRaises(BenchmarkConfigurationError) as f_cm:
                    self.m_adapter.buildCommand(
                        self.m_executable,
                        f_block_size="1M",
                        f_stderr_path=f_bad,  # type: ignore[arg-type]
                    )
                self.assertIn(
                    "Stderr path must be a non-empty string", str(f_cm.exception)
                )

        # 030-C6: stderr_path contains NUL byte
        with self.assertRaises(BenchmarkConfigurationError) as f_cm:
            self.m_adapter.buildCommand(
                self.m_executable,
                f_block_size="1M",
                f_stderr_path="/tmp/stderr\0.log",
            )
        self.assertIn("Stderr path contains NUL byte:", str(f_cm.exception))

    def testBuildCommandCombinationBlockSizeVariations(self) -> None:
        """Verify combination-based block size resolution variants and errors (cases 030-D1 to 030-D4)."""
        # 030-D1: string with '_b'
        f_cmd1 = self.m_adapter.buildCommand(
            self.m_executable,
            f_combination="c16_b1M",
            f_working_dir=self.m_work_dir,
        )
        self.assertIn("-b=1M", f_cmd1.argv)
        self.assertIn("-t=1M", f_cmd1.argv)
        self.assertIn("-s=1024", f_cmd1.argv)

        # 030-D2: plain block size string without '_b'
        f_cmd2 = self.m_adapter.buildCommand(
            self.m_executable,
            f_combination="8M",
            f_working_dir=self.m_work_dir,
        )
        self.assertIn("-b=8M", f_cmd2.argv)
        self.assertIn("-t=8M", f_cmd2.argv)
        self.assertIn("-s=128", f_cmd2.argv)

        # 030-D3: tuple or list with length >= 2
        for f_combo, f_exp_bs, f_exp_seg in (
            ([16, "64K"], "64K", "16384"),
            ((16, "64K"), "64K", "16384"),
            (["c1", "1M", "extra"], "1M", "1024"),
        ):
            with self.subTest(combo=f_combo):
                f_cmd = self.m_adapter.buildCommand(
                    self.m_executable,
                    f_combination=f_combo,
                    f_working_dir=self.m_work_dir,
                )
                self.assertIn(f"-b={f_exp_bs}", f_cmd.argv)
                self.assertIn(f"-t={f_exp_bs}", f_cmd.argv)
                self.assertIn(f"-s={f_exp_seg}", f_cmd.argv)

        # 030-D4: invalid combination type or insufficient length raises BenchmarkConfigurationError
        for f_bad_combo in (123, (), [16], object()):
            with self.subTest(bad_combo=f_bad_combo):
                with self.assertRaises(BenchmarkConfigurationError) as f_cm:
                    self.m_adapter.buildCommand(
                        self.m_executable,
                        f_combination=f_bad_combo,
                        f_working_dir=self.m_work_dir,
                    )
                self.assertIn(
                    "Block size must be specified directly or via combination",
                    str(f_cm.exception),
                )

    def testBuildCommandConvenienceAliases(self) -> None:
        """Verify convenience aliases buildBenchmarkCommand, createCommand, and build_command (case 030-E1)."""
        f_kwargs = {
            "f_executable": self.m_executable,
            "f_setup": "BASE",
            "f_block_size": "1M",
            "f_working_dir": self.m_work_dir,
        }
        f_golden = self.m_adapter.buildCommand(**f_kwargs)
        self.assertEqual(self.m_adapter.buildBenchmarkCommand(**f_kwargs), f_golden)
        self.assertEqual(self.m_adapter.createCommand(**f_kwargs), f_golden)
        self.assertEqual(self.m_adapter.build_command(**f_kwargs), f_golden)

    def testProbeCapabilityValidation(self) -> None:
        """Verify probeCapability executable validation (cases 030-F1, 030-F2)."""
        # 030-F1: non-string / empty executable
        for f_bad in (123, None, "", "   ", "\t"):
            with self.subTest(executable=f_bad):
                with self.assertRaises(BenchmarkConfigurationError) as f_cm:
                    self.m_adapter.probeCapability(f_executable=f_bad)  # type: ignore[arg-type]
                self.assertIn(
                    "Executable must be a non-empty string", str(f_cm.exception)
                )

        # 030-F2: NUL byte in executable
        with self.assertRaises(BenchmarkConfigurationError) as f_cm:
            self.m_adapter.probeCapability(f_executable="/bin/ior\0")
        self.assertIn("Executable contains NUL byte:", str(f_cm.exception))

    def testProbeCapabilityUnexpectedException(self) -> None:
        """Verify unexpected runner exceptions are wrapped in BenchmarkProbeError (case 030-G1)."""

        def _failingRunner(_argv: Sequence[str]) -> Any:
            raise RuntimeError("Unexpected probe runner crash")

        with self.assertRaises(BenchmarkProbeError) as f_cm:
            self.m_adapter.probeCapability(self.m_executable, f_runner=_failingRunner)
        self.assertIn(
            "IOR probe runner raised unexpected error for",
            str(f_cm.exception),
        )
        self.assertIsInstance(f_cm.exception.__cause__, RuntimeError)

    def testProbeCapabilityRunnerResultTypes(self) -> None:
        """Verify probeCapability handling across runner result types (cases 030-H1 to 030-H6)."""

        # 030-H1: result with exit_code attribute (no returncode)
        class ExitCodeResult:
            exit_code = 0
            stdout = "IOR-3.3.0"
            stderr = ""

        f_res_exit = self.m_adapter.probeCapability(
            self.m_executable, f_runner=lambda a: ExitCodeResult()
        )
        self.assertEqual(f_res_exit, CapabilityState.VERIFIED)

        # 030-H2: 3-tuple result (exit_code, stdout, stderr)
        f_res_tuple3 = self.m_adapter.probeCapability(
            self.m_executable,
            f_runner=lambda a: (0, "IOR-3.3.0", "stderr debug output"),
        )
        self.assertEqual(f_res_tuple3, CapabilityState.VERIFIED)

        # 030-H3: 2-tuple result (exit_code, stdout)
        f_res_tuple2 = self.m_adapter.probeCapability(
            self.m_executable,
            f_runner=lambda a: (0, "IOR-3.3.0"),
        )
        self.assertEqual(f_res_tuple2, CapabilityState.VERIFIED)

        # 030-H4: int result (non-zero and zero)
        with self.assertRaises(BenchmarkProbeError) as f_cm_fail:
            self.m_adapter.probeCapability(self.m_executable, f_runner=lambda a: 1)
        self.assertIn("probe failed with exit code 1", str(f_cm_fail.exception))

        with self.assertRaises(BenchmarkProbeError) as f_cm_empty:
            self.m_adapter.probeCapability(self.m_executable, f_runner=lambda a: 0)
        self.assertIn("produced empty probe output", str(f_cm_empty.exception))

        # 030-H5: str result
        f_res_str = self.m_adapter.probeCapability(
            self.m_executable,
            f_runner=lambda a: "IOR-3.3.0: Parallel IO Benchmark",
        )
        self.assertEqual(f_res_str, CapabilityState.VERIFIED)

        # 030-H6: custom object with __str__ returning banner text
        class CustomStrResult:
            def __str__(self) -> str:
                return "IOR-3.3.0"

        f_res_custom = self.m_adapter.probeCapability(
            self.m_executable,
            f_runner=lambda a: CustomStrResult(),
        )
        self.assertEqual(f_res_custom, CapabilityState.VERIFIED)

    def testProbeCapabilityUnrecognizedOutput(self) -> None:
        """Verify probeCapability raises BenchmarkProbeError when output has exit code 0 but no recognizable signature (case 030-I1)."""
        with self.assertRaises(BenchmarkProbeError) as f_cm:
            self.m_adapter.probeCapability(
                self.m_executable,
                f_runner=lambda a: (
                    0,
                    "unrecognized banner text with zero matching keywords",
                    "",
                ),
            )
        self.assertIn("produced unrecognized probe output:", str(f_cm.exception))


if __name__ == "__main__":
    unittest.main()
