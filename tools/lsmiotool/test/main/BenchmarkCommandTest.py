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

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
import unittest

from lsmiotool.lib.benchmarks import (
    BenchmarkAdapter,
    BenchmarkCommand,
    BenchmarkConfigurationError,
    BenchmarkError,
    BenchmarkProbeError,
    CapabilityState,
    LsmioBoundCommand,
    LsmioLaunchSpec,
    ProbeState,
)
from lsmiotool.lib.run import Combination, RankIdentity, ScalePoint


class BenchmarkCapabilityAndErrorTest(unittest.TestCase):
    """Tests for CapabilityState enum, compatibility aliases, and benchmark error hierarchy."""

    def testCapabilityStateEnumAndProperties(self) -> None:
        """Verify CapabilityState member values, boolean query properties, and ProbeState alias."""
        self.assertEqual(CapabilityState.CONFIGURED.value, "configured")
        self.assertEqual(CapabilityState.VERIFIED.value, "verified")
        self.assertEqual(CapabilityState.UNSUPPORTED.value, "unsupported")

        self.assertTrue(CapabilityState.VERIFIED.is_verified)
        self.assertFalse(CapabilityState.VERIFIED.is_configured)
        self.assertFalse(CapabilityState.VERIFIED.is_unsupported)

        self.assertFalse(CapabilityState.CONFIGURED.is_verified)
        self.assertTrue(CapabilityState.CONFIGURED.is_configured)
        self.assertFalse(CapabilityState.CONFIGURED.is_unsupported)

        self.assertFalse(CapabilityState.UNSUPPORTED.is_verified)
        self.assertFalse(CapabilityState.UNSUPPORTED.is_configured)
        self.assertTrue(CapabilityState.UNSUPPORTED.is_unsupported)

        self.assertIs(ProbeState, CapabilityState)

    def testBenchmarkErrorHierarchy(self) -> None:
        """Verify benchmark exception class inheritance and string representation."""
        self.assertTrue(issubclass(BenchmarkError, Exception))
        self.assertTrue(issubclass(BenchmarkConfigurationError, BenchmarkError))
        self.assertTrue(issubclass(BenchmarkProbeError, BenchmarkError))

        f_base = BenchmarkError("base error")
        f_cfg = BenchmarkConfigurationError("cfg err")
        f_probe = BenchmarkProbeError("probe err")

        self.assertEqual(str(f_base), "base error")
        self.assertEqual(str(f_cfg), "cfg err")
        self.assertEqual(str(f_probe), "probe err")


class BenchmarkCommandContractTest(unittest.TestCase):
    """Tests for BenchmarkCommand validation, immutability, serialization, and equality contracts."""

    def testBenchmarkCommandRejectsEmptyArgv(self) -> None:
        """Verify BenchmarkCommand rejects empty argv sequence."""
        for f_bad_argv in ([], ()):
            with self.subTest(argv=f_bad_argv):
                with self.assertRaises(BenchmarkConfigurationError) as f_ctx:
                    BenchmarkCommand(
                        f_argv=f_bad_argv,
                        f_stdout_path="/out",
                        f_stderr_path="/err",
                        f_working_dir="/work",
                    )
                self.assertIn(
                    "BenchmarkCommand argv sequence must not be empty",
                    str(f_ctx.exception),
                )

    def testBenchmarkCommandRejectsNonStringArgvElements(self) -> None:
        """Verify BenchmarkCommand rejects non-string argv elements."""
        for f_bad_argv in (["valid", 123], [None, "valid"], [1.5]):
            with self.subTest(argv=f_bad_argv):
                with self.assertRaises(BenchmarkConfigurationError) as f_ctx:
                    BenchmarkCommand(
                        f_argv=f_bad_argv,  # type: ignore[arg-type]
                        f_stdout_path="/out",
                        f_stderr_path="/err",
                        f_working_dir="/work",
                    )
                self.assertIn("must be a string, got:", str(f_ctx.exception))

    def testBenchmarkCommandRejectsNulInArgvElements(self) -> None:
        """Verify BenchmarkCommand rejects argv elements containing NUL bytes."""
        for f_bad_argv in (["cmd\0"], ["cmd", "arg\0nul"]):
            with self.subTest(argv=f_bad_argv):
                with self.assertRaises(BenchmarkConfigurationError) as f_ctx:
                    BenchmarkCommand(
                        f_argv=f_bad_argv,
                        f_stdout_path="/out",
                        f_stderr_path="/err",
                        f_working_dir="/work",
                    )
                self.assertIn("contains NUL byte:", str(f_ctx.exception))

    def testBenchmarkCommandRejectsInvalidStdoutPath(self) -> None:
        """Verify BenchmarkCommand rejects non-string or whitespace-only stdout_path."""
        for f_bad in (123, None, "", "   ", "\t\n"):
            with self.subTest(stdout_path=f_bad):
                with self.assertRaises(BenchmarkConfigurationError) as f_ctx:
                    BenchmarkCommand(
                        f_argv=["cmd"],
                        f_stdout_path=f_bad,  # type: ignore[arg-type]
                        f_stderr_path="/err",
                        f_working_dir="/work",
                    )
                self.assertIn(
                    "stdout_path must be a non-empty string", str(f_ctx.exception)
                )

    def testBenchmarkCommandRejectsNulInStdoutPath(self) -> None:
        """Verify BenchmarkCommand rejects stdout_path containing NUL bytes."""
        with self.assertRaises(BenchmarkConfigurationError) as f_ctx:
            BenchmarkCommand(
                f_argv=["cmd"],
                f_stdout_path="/out/file\0.log",
                f_stderr_path="/err",
                f_working_dir="/work",
            )
        self.assertIn("stdout_path contains NUL byte:", str(f_ctx.exception))

    def testBenchmarkCommandRejectsInvalidStderrPath(self) -> None:
        """Verify BenchmarkCommand rejects non-string or whitespace-only stderr_path."""
        for f_bad in (123, None, "", "   ", "\t"):
            with self.subTest(stderr_path=f_bad):
                with self.assertRaises(BenchmarkConfigurationError) as f_ctx:
                    BenchmarkCommand(
                        f_argv=["cmd"],
                        f_stdout_path="/out",
                        f_stderr_path=f_bad,  # type: ignore[arg-type]
                        f_working_dir="/work",
                    )
                self.assertIn(
                    "stderr_path must be a non-empty string", str(f_ctx.exception)
                )

    def testBenchmarkCommandRejectsNulInStderrPath(self) -> None:
        """Verify BenchmarkCommand rejects stderr_path containing NUL bytes."""
        with self.assertRaises(BenchmarkConfigurationError) as f_ctx:
            BenchmarkCommand(
                f_argv=["cmd"],
                f_stdout_path="/out",
                f_stderr_path="/err/file\0.log",
                f_working_dir="/work",
            )
        self.assertIn("stderr_path contains NUL byte:", str(f_ctx.exception))

    def testBenchmarkCommandRejectsInvalidWorkingDir(self) -> None:
        """Verify BenchmarkCommand rejects non-string or whitespace-only working_dir."""
        for f_bad in (123, None, "", "   ", "\n"):
            with self.subTest(working_dir=f_bad):
                with self.assertRaises(BenchmarkConfigurationError) as f_ctx:
                    BenchmarkCommand(
                        f_argv=["cmd"],
                        f_stdout_path="/out",
                        f_stderr_path="/err",
                        f_working_dir=f_bad,  # type: ignore[arg-type]
                    )
                self.assertIn(
                    "working_dir must be a non-empty string", str(f_ctx.exception)
                )

    def testBenchmarkCommandRejectsNulInWorkingDir(self) -> None:
        """Verify BenchmarkCommand rejects working_dir containing NUL bytes."""
        with self.assertRaises(BenchmarkConfigurationError) as f_ctx:
            BenchmarkCommand(
                f_argv=["cmd"],
                f_stdout_path="/out",
                f_stderr_path="/err",
                f_working_dir="/work/dir\0",
            )
        self.assertIn("working_dir contains NUL byte:", str(f_ctx.exception))

    def testBenchmarkCommandRejectsNonBoolIsRankLocal(self) -> None:
        """Verify BenchmarkCommand rejects non-boolean is_rank_local values."""
        for f_bad in (1, 0, "true", None, []):
            with self.subTest(is_rank_local=f_bad):
                with self.assertRaises(BenchmarkConfigurationError) as f_ctx:
                    BenchmarkCommand(
                        f_argv=["cmd"],
                        f_stdout_path="/out",
                        f_stderr_path="/err",
                        f_working_dir="/work",
                        f_is_rank_local=f_bad,  # type: ignore[arg-type]
                    )
                self.assertIn(
                    "is_rank_local must be a boolean", str(f_ctx.exception)
                )

    def testBenchmarkCommandImmutabilityFrozenRaise(self) -> None:
        """Verify frozen BenchmarkCommand instance raises AttributeError upon attribute mutation or deletion."""
        f_cmd = BenchmarkCommand(
            ["cmd"], "/out", "/err", "/work", f_is_rank_local=True
        )
        with self.assertRaises(AttributeError) as f_ctx:
            f_cmd.m_argv = ("new",)  # type: ignore[misc]
        self.assertIn(
            "Cannot modify immutable BenchmarkCommand", str(f_ctx.exception)
        )

        with self.assertRaises(AttributeError) as f_ctx:
            del f_cmd.m_argv  # type: ignore[misc]
        self.assertIn(
            "Cannot delete attribute from immutable BenchmarkCommand",
            str(f_ctx.exception),
        )

        self.assertEqual(f_cmd.argv, ("cmd",))

    def testBenchmarkCommandImmutabilityUnfrozenSetattr(self) -> None:
        """Verify unfrozen BenchmarkCommand instance allows attribute assignment via super().__setattr__."""
        f_cmd = BenchmarkCommand.__new__(BenchmarkCommand)
        setattr(f_cmd, "m_argv", ("unfrozen", "arg"))
        self.assertEqual(getattr(f_cmd, "m_argv"), ("unfrozen", "arg"))

    def testBenchmarkCommandImmutabilityUnfrozenDelattr(self) -> None:
        """Verify unfrozen BenchmarkCommand instance allows attribute deletion via super().__delattr__."""
        f_cmd = BenchmarkCommand.__new__(BenchmarkCommand)
        setattr(f_cmd, "m_argv", ("to_del",))
        self.assertTrue(hasattr(f_cmd, "m_argv"))
        delattr(f_cmd, "m_argv")
        self.assertFalse(hasattr(f_cmd, "m_argv"))

    def testBenchmarkCommandPropertiesAndAliases(self) -> None:
        """Verify BenchmarkCommand properties and compatibility aliases return normalized attributes."""
        f_cmd = BenchmarkCommand(
            ["cmd", "run"],
            " /var/log/stdout.log ",
            " /var/log/stderr.log ",
            " /tmp/work/dir/ ",
            f_is_rank_local=True,
        )
        self.assertEqual(f_cmd.argv, ("cmd", "run"))
        self.assertEqual(f_cmd.arguments, f_cmd.argv)
        self.assertEqual(f_cmd.stdout_path, "/var/log/stdout.log")
        self.assertEqual(f_cmd.stdoutPath, f_cmd.stdout_path)
        self.assertEqual(f_cmd.stderr_path, "/var/log/stderr.log")
        self.assertEqual(f_cmd.stderrPath, f_cmd.stderr_path)
        self.assertEqual(f_cmd.working_dir, "/tmp/work/dir")
        self.assertEqual(f_cmd.workingDir, f_cmd.working_dir)
        self.assertTrue(f_cmd.is_rank_local)
        self.assertTrue(f_cmd.isRankLocal)

    def testBenchmarkCommandToDict(self) -> None:
        """Verify BenchmarkCommand serialization to dictionary format."""
        f_cmd = BenchmarkCommand(
            ["cmd", "-v"],
            "/out.log",
            "/err.log",
            "/work",
            f_is_rank_local=False,
        )
        f_expected = {
            "argv": ["cmd", "-v"],
            "stdout_path": "/out.log",
            "stderr_path": "/err.log",
            "working_dir": "/work",
            "is_rank_local": False,
        }
        self.assertEqual(f_cmd.toDict(), f_expected)

    def testBenchmarkCommandRepr(self) -> None:
        """Verify BenchmarkCommand representation string contents."""
        f_cmd = BenchmarkCommand(
            ["cmd"], "/out", "/err", "/work", f_is_rank_local=True
        )
        f_repr = repr(f_cmd)
        self.assertTrue(f_repr.startswith("BenchmarkCommand("))
        self.assertIn("argv=('cmd',)", f_repr)
        self.assertIn("is_rank_local=True", f_repr)

    def testBenchmarkCommandHash(self) -> None:
        """Verify BenchmarkCommand hash stability and equality in sets."""
        f_cmd1 = BenchmarkCommand(
            ["cmd"], "/out", "/err", "/work", f_is_rank_local=False
        )
        f_cmd2 = BenchmarkCommand(
            ["cmd"], "/out", "/err", "/work", f_is_rank_local=False
        )
        self.assertEqual(hash(f_cmd1), hash(f_cmd2))
        self.assertEqual(len({f_cmd1, f_cmd2}), 1)

    def testBenchmarkCommandEqualityNonBenchmarkCommand(self) -> None:
        """Verify BenchmarkCommand returns False when compared against non-BenchmarkCommand objects."""
        f_cmd = BenchmarkCommand(
            ["cmd"], "/out", "/err", "/work", f_is_rank_local=False
        )
        for f_other in ("string", 42, None, object(), []):
            with self.subTest(other=f_other):
                self.assertFalse(f_cmd == f_other)
                self.assertTrue(f_cmd != f_other)

    def testBenchmarkCommandEqualityPermutations(self) -> None:
        """Verify BenchmarkCommand equality checks all attributes across variations."""
        f_base = BenchmarkCommand(
            ["cmd", "1"], "/out", "/err", "/work", f_is_rank_local=False
        )
        f_same = BenchmarkCommand(
            ["cmd", "1"], "/out", "/err", "/work", f_is_rank_local=False
        )
        self.assertEqual(f_base, f_same)

        f_diff_argv = BenchmarkCommand(
            ["cmd", "2"], "/out", "/err", "/work", f_is_rank_local=False
        )
        f_diff_stdout = BenchmarkCommand(
            ["cmd", "1"], "/out2", "/err", "/work", f_is_rank_local=False
        )
        f_diff_stderr = BenchmarkCommand(
            ["cmd", "1"], "/out", "/err2", "/work", f_is_rank_local=False
        )
        f_diff_work = BenchmarkCommand(
            ["cmd", "1"], "/out", "/err", "/work2", f_is_rank_local=False
        )
        f_diff_rank = BenchmarkCommand(
            ["cmd", "1"], "/out", "/err", "/work", f_is_rank_local=True
        )

        for f_variant in (
            f_diff_argv,
            f_diff_stdout,
            f_diff_stderr,
            f_diff_work,
            f_diff_rank,
        ):
            with self.subTest(variant=f_variant):
                self.assertNotEqual(f_base, f_variant)


class BenchmarkAdapterContractTest(unittest.TestCase):
    """Tests for BenchmarkAdapter abstract base class contract."""

    def testBenchmarkAdapterAbstractClassCannotBeInstantiatedDirectly(self) -> None:
        """Verify BenchmarkAdapter cannot be instantiated directly and incomplete subclasses raise TypeError."""
        with self.assertRaises(TypeError) as f_cm:
            BenchmarkAdapter()  # type: ignore[abstract]
        self.assertIn("Can't instantiate abstract class BenchmarkAdapter", str(f_cm.exception))

        class IncompleteAdapter(BenchmarkAdapter):
            """Subclass missing defaultSetup, allowedSetups, and probeCapability."""

            @property
            def target(self) -> str:
                return "dummy"

        with self.assertRaises(TypeError) as f_cm_incomplete:
            IncompleteAdapter()  # type: ignore[abstract]
        self.assertIn("Can't instantiate abstract class IncompleteAdapter", str(f_cm_incomplete.exception))


class LsmioLaunchSpecContractTest(unittest.TestCase):
    """Tests for LsmioLaunchSpec validation, immutability, serialization, and equality contracts."""

    def testLsmioLaunchSpecRejectsInvalidSetup(self) -> None:
        """Verify LsmioLaunchSpec rejects non-string or whitespace-only setup."""
        for f_bad in (None, 123, "", "   ", "\t\n"):
            with self.subTest(setup=f_bad):
                with self.assertRaises(BenchmarkConfigurationError) as f_ctx:
                    LsmioLaunchSpec(
                        f_request="req",
                        f_combination="combo",
                        f_point="pt",
                        f_setup=f_bad,  # type: ignore[arg-type]
                        f_executable="/bin/exe",
                    )
                self.assertIn(
                    "LsmioLaunchSpec setup must be a non-empty string",
                    str(f_ctx.exception),
                )

    def testLsmioLaunchSpecRejectsNulInSetup(self) -> None:
        """Verify LsmioLaunchSpec rejects setup containing NUL bytes."""
        with self.assertRaises(BenchmarkConfigurationError) as f_ctx:
            LsmioLaunchSpec(
                f_request="req",
                f_combination="combo",
                f_point="pt",
                f_setup="NATIVE\0",
                f_executable="/bin/exe",
            )
        self.assertIn(
            "LsmioLaunchSpec setup contains NUL byte:", str(f_ctx.exception)
        )

    def testLsmioLaunchSpecRejectsInvalidExecutable(self) -> None:
        """Verify LsmioLaunchSpec rejects non-string or whitespace-only executable."""
        for f_bad in (None, 123, "", "   "):
            with self.subTest(executable=f_bad):
                with self.assertRaises(BenchmarkConfigurationError) as f_ctx:
                    LsmioLaunchSpec(
                        f_request="req",
                        f_combination="combo",
                        f_point="pt",
                        f_setup="NATIVE",
                        f_executable=f_bad,  # type: ignore[arg-type]
                    )
                self.assertIn(
                    "LsmioLaunchSpec executable must be a non-empty string",
                    str(f_ctx.exception),
                )

    def testLsmioLaunchSpecRejectsNulInExecutable(self) -> None:
        """Verify LsmioLaunchSpec rejects executable containing NUL bytes."""
        with self.assertRaises(BenchmarkConfigurationError) as f_ctx:
            LsmioLaunchSpec(
                f_request="req",
                f_combination="combo",
                f_point="pt",
                f_setup="NATIVE",
                f_executable="/bin/lsmio\0",
            )
        self.assertIn(
            "LsmioLaunchSpec executable contains NUL byte:", str(f_ctx.exception)
        )

    def testLsmioLaunchSpecRejectsInvalidVariant(self) -> None:
        """Verify LsmioLaunchSpec rejects invalid non-string or whitespace-only variant."""
        for f_bad in (123, "", "   "):
            with self.subTest(variant=f_bad):
                with self.assertRaises(BenchmarkConfigurationError) as f_ctx:
                    LsmioLaunchSpec(
                        f_request="req",
                        f_combination="combo",
                        f_point="pt",
                        f_setup="NATIVE",
                        f_executable="/bin/exe",
                        f_variant=f_bad,  # type: ignore[arg-type]
                    )
                self.assertIn(
                    "LsmioLaunchSpec variant must be a non-empty string or None",
                    str(f_ctx.exception),
                )

    def testLsmioLaunchSpecRejectsNulInVariant(self) -> None:
        """Verify LsmioLaunchSpec rejects variant containing NUL bytes."""
        with self.assertRaises(BenchmarkConfigurationError) as f_ctx:
            LsmioLaunchSpec(
                f_request="req",
                f_combination="combo",
                f_point="pt",
                f_setup="NATIVE",
                f_executable="/bin/exe",
                f_variant="sync\0",
            )
        self.assertIn(
            "LsmioLaunchSpec variant contains NUL byte:", str(f_ctx.exception)
        )

    def testLsmioLaunchSpecRejectsNonBoolIsRankLocal(self) -> None:
        """Verify LsmioLaunchSpec rejects non-boolean is_rank_local values."""
        for f_bad in (1, 0, "true", None):
            with self.subTest(is_rank_local=f_bad):
                with self.assertRaises(BenchmarkConfigurationError) as f_ctx:
                    LsmioLaunchSpec(
                        f_request="req",
                        f_combination="combo",
                        f_point="pt",
                        f_setup="NATIVE",
                        f_executable="/bin/exe",
                        f_is_rank_local=f_bad,  # type: ignore[arg-type]
                    )
                self.assertIn(
                    "LsmioLaunchSpec is_rank_local must be a boolean",
                    str(f_ctx.exception),
                )

    def testLsmioLaunchSpecRejectsNonBoolIsBound(self) -> None:
        """Verify LsmioLaunchSpec rejects non-boolean is_bound values."""
        for f_bad in (1, 0, "false", None):
            with self.subTest(is_bound=f_bad):
                with self.assertRaises(BenchmarkConfigurationError) as f_ctx:
                    LsmioLaunchSpec(
                        f_request="req",
                        f_combination="combo",
                        f_point="pt",
                        f_setup="NATIVE",
                        f_executable="/bin/exe",
                        f_is_bound=f_bad,  # type: ignore[arg-type]
                    )
                self.assertIn(
                    "LsmioLaunchSpec is_bound must be a boolean",
                    str(f_ctx.exception),
                )

    def testLsmioLaunchSpecImmutabilityFrozenRaise(self) -> None:
        """Verify frozen LsmioLaunchSpec instance raises AttributeError upon attribute mutation or deletion."""
        f_spec = LsmioLaunchSpec(
            f_request="req",
            f_combination="combo",
            f_point="pt",
            f_setup="NATIVE",
            f_executable="/bin/exe",
        )
        with self.assertRaises(AttributeError) as f_ctx:
            f_spec.m_setup = "NEW"  # type: ignore[misc]
        self.assertIn(
            "Cannot modify immutable LsmioLaunchSpec", str(f_ctx.exception)
        )

        with self.assertRaises(AttributeError) as f_ctx:
            del f_spec.m_setup  # type: ignore[misc]
        self.assertIn(
            "Cannot delete attribute from immutable LsmioLaunchSpec",
            str(f_ctx.exception),
        )

        self.assertEqual(f_spec.setup, "NATIVE")

    def testLsmioLaunchSpecImmutabilityUnfrozenSetattr(self) -> None:
        """Verify unfrozen LsmioLaunchSpec instance allows attribute assignment via super().__setattr__."""
        f_spec = LsmioLaunchSpec.__new__(LsmioLaunchSpec)
        setattr(f_spec, "m_setup", "UNFROZEN")
        self.assertEqual(getattr(f_spec, "m_setup"), "UNFROZEN")

    def testLsmioLaunchSpecImmutabilityUnfrozenDelattr(self) -> None:
        """Verify unfrozen LsmioLaunchSpec instance allows attribute deletion via super().__delattr__."""
        f_spec = LsmioLaunchSpec.__new__(LsmioLaunchSpec)
        setattr(f_spec, "m_setup", "UNFROZEN")
        self.assertTrue(hasattr(f_spec, "m_setup"))
        delattr(f_spec, "m_setup")
        self.assertFalse(hasattr(f_spec, "m_setup"))

    def testLsmioLaunchSpecPropertiesAndAliases(self) -> None:
        """Verify LsmioLaunchSpec properties, normalized values, and aliases."""
        f_spec = LsmioLaunchSpec(
            f_request="req1",
            f_combination="combo1",
            f_point="pt1",
            f_setup=" native ",
            f_executable=" /bin/lsmio/ ",
            f_variant=" SYNC ",
            f_is_rank_local=True,
            f_is_bound=False,
        )
        self.assertEqual(f_spec.request, "req1")
        self.assertEqual(f_spec.combination, "combo1")
        self.assertEqual(f_spec.point, "pt1")
        self.assertEqual(f_spec.setup, "NATIVE")
        self.assertEqual(f_spec.executable, "/bin/lsmio")
        self.assertEqual(f_spec.variant, "sync")
        self.assertTrue(f_spec.is_rank_local)
        self.assertTrue(f_spec.isRankLocal)
        self.assertFalse(f_spec.is_bound)
        self.assertFalse(f_spec.isBound)
        self.assertEqual(f_spec.expected_results, ())
        self.assertEqual(f_spec.mode, "direct")
        self.assertEqual(f_spec.executable_or_worker, "/bin/lsmio")
        self.assertEqual(f_spec.arguments, ())

    def testLsmioLaunchSpecToDict(self) -> None:
        """Verify LsmioLaunchSpec serialization with combination/point toDict() and plain strings."""
        f_combo = Combination(
            f_processes=1,
            f_block_size="1M",
            f_stripe_count=1,
            f_block_bytes=1048576,
            f_key_count=100,
            f_segment_count=10,
        )
        f_point = ScalePoint(f_tasks=1, f_ppn=1, f_nodes=1)

        with self.subTest(has_to_dict=True):
            f_spec = LsmioLaunchSpec(
                f_request="req",
                f_combination=f_combo,
                f_point=f_point,
                f_setup="NATIVE",
                f_executable="/bin/exe",
                f_variant="sync",
                f_is_rank_local=True,
                f_is_bound=False,
            )
            f_dict = f_spec.toDict()
            self.assertEqual(f_dict["target"], "lsmio")
            self.assertEqual(f_dict["setup"], "NATIVE")
            self.assertEqual(f_dict["executable"], "/bin/exe")
            self.assertEqual(f_dict["variant"], "sync")
            self.assertEqual(f_dict["combination"], f_combo.toDict())
            self.assertEqual(f_dict["point"], f_point.toDict())
            self.assertTrue(f_dict["is_rank_local"])
            self.assertFalse(f_dict["is_bound"])

        with self.subTest(has_to_dict=False):
            f_spec_plain = LsmioLaunchSpec(
                f_request="req",
                f_combination="plain_combo",
                f_point="plain_point",
                f_setup="NATIVE",
                f_executable="/bin/exe",
                f_variant=None,
                f_is_rank_local=False,
                f_is_bound=True,
            )
            f_dict_plain = f_spec_plain.toDict()
            self.assertNotIn("variant", f_dict_plain)
            self.assertEqual(f_dict_plain["combination"], "plain_combo")
            self.assertEqual(f_dict_plain["point"], "plain_point")
            self.assertFalse(f_dict_plain["is_rank_local"])
            self.assertTrue(f_dict_plain["is_bound"])

    def testLsmioLaunchSpecRepr(self) -> None:
        """Verify LsmioLaunchSpec representation string contents."""
        f_spec = LsmioLaunchSpec(
            f_request="req",
            f_combination="combo",
            f_point="pt",
            f_setup="NATIVE",
            f_executable="/bin/exe",
            f_variant="sync",
            f_is_rank_local=True,
            f_is_bound=False,
        )
        f_repr = repr(f_spec)
        self.assertTrue(f_repr.startswith("LsmioLaunchSpec("))
        self.assertIn("setup='NATIVE'", f_repr)
        self.assertIn("variant='sync'", f_repr)

    def testLsmioLaunchSpecHash(self) -> None:
        """Verify LsmioLaunchSpec hash stability across combination and point structural types."""
        f_combo = Combination(
            f_processes=1,
            f_block_size="1M",
            f_stripe_count=1,
            f_block_bytes=1048576,
            f_key_count=100,
            f_segment_count=10,
        )
        f_point = ScalePoint(f_tasks=1, f_ppn=1, f_nodes=1)

        with self.subTest(structural=True):
            f_spec1 = LsmioLaunchSpec(
                f_request="req",
                f_combination=f_combo,
                f_point=f_point,
                f_setup="NATIVE",
                f_executable="/bin/exe",
                f_variant="sync",
                f_is_rank_local=True,
                f_is_bound=False,
            )
            f_spec2 = LsmioLaunchSpec(
                f_request="req",
                f_combination=f_combo,
                f_point=f_point,
                f_setup="NATIVE",
                f_executable="/bin/exe",
                f_variant="sync",
                f_is_rank_local=True,
                f_is_bound=False,
            )
            self.assertEqual(hash(f_spec1), hash(f_spec2))
            self.assertEqual(len({f_spec1, f_spec2}), 1)

        with self.subTest(structural=False):
            f_spec3 = LsmioLaunchSpec(
                f_request="req",
                f_combination="str_c",
                f_point="str_p",
                f_setup="NATIVE",
                f_executable="/bin/exe",
                f_variant=None,
                f_is_rank_local=False,
                f_is_bound=True,
            )
            f_spec4 = LsmioLaunchSpec(
                f_request="req",
                f_combination="str_c",
                f_point="str_p",
                f_setup="NATIVE",
                f_executable="/bin/exe",
                f_variant=None,
                f_is_rank_local=False,
                f_is_bound=True,
            )
            self.assertEqual(hash(f_spec3), hash(f_spec4))
            self.assertEqual(len({f_spec3, f_spec4}), 1)

    def testLsmioLaunchSpecEqualityNonSpec(self) -> None:
        """Verify LsmioLaunchSpec returns False when compared against non-LsmioLaunchSpec objects."""
        f_spec = LsmioLaunchSpec(
            f_request="req",
            f_combination="c",
            f_point="p",
            f_setup="NATIVE",
            f_executable="/bin/exe",
        )
        for f_other in ("other", 42, None, []):
            with self.subTest(other=f_other):
                self.assertFalse(f_spec == f_other)
                self.assertTrue(f_spec != f_other)

    def testLsmioLaunchSpecEqualityPermutations(self) -> None:
        """Verify LsmioLaunchSpec equality checks all 7 comparison fields."""
        f_base = LsmioLaunchSpec(
            f_request="req",
            f_combination="c",
            f_point="p",
            f_setup="NATIVE",
            f_executable="/bin/exe",
            f_variant="var",
            f_is_rank_local=True,
            f_is_bound=False,
        )
        f_same = LsmioLaunchSpec(
            f_request="req",
            f_combination="c",
            f_point="p",
            f_setup="NATIVE",
            f_executable="/bin/exe",
            f_variant="var",
            f_is_rank_local=True,
            f_is_bound=False,
        )
        self.assertEqual(f_base, f_same)

        f_diff_setup = LsmioLaunchSpec(
            f_request="req",
            f_combination="c",
            f_point="p",
            f_setup="OTHER",
            f_executable="/bin/exe",
            f_variant="var",
            f_is_rank_local=True,
            f_is_bound=False,
        )
        f_diff_exe = LsmioLaunchSpec(
            f_request="req",
            f_combination="c",
            f_point="p",
            f_setup="NATIVE",
            f_executable="/bin/other",
            f_variant="var",
            f_is_rank_local=True,
            f_is_bound=False,
        )
        f_diff_combo = LsmioLaunchSpec(
            f_request="req",
            f_combination="c2",
            f_point="p",
            f_setup="NATIVE",
            f_executable="/bin/exe",
            f_variant="var",
            f_is_rank_local=True,
            f_is_bound=False,
        )
        f_diff_point = LsmioLaunchSpec(
            f_request="req",
            f_combination="c",
            f_point="p2",
            f_setup="NATIVE",
            f_executable="/bin/exe",
            f_variant="var",
            f_is_rank_local=True,
            f_is_bound=False,
        )
        f_diff_variant = LsmioLaunchSpec(
            f_request="req",
            f_combination="c",
            f_point="p",
            f_setup="NATIVE",
            f_executable="/bin/exe",
            f_variant="other_var",
            f_is_rank_local=True,
            f_is_bound=False,
        )
        f_diff_rank_local = LsmioLaunchSpec(
            f_request="req",
            f_combination="c",
            f_point="p",
            f_setup="NATIVE",
            f_executable="/bin/exe",
            f_variant="var",
            f_is_rank_local=False,
            f_is_bound=False,
        )
        f_diff_bound = LsmioLaunchSpec(
            f_request="req",
            f_combination="c",
            f_point="p",
            f_setup="NATIVE",
            f_executable="/bin/exe",
            f_variant="var",
            f_is_rank_local=True,
            f_is_bound=True,
        )

        for f_variant in (
            f_diff_setup,
            f_diff_exe,
            f_diff_combo,
            f_diff_point,
            f_diff_variant,
            f_diff_rank_local,
            f_diff_bound,
        ):
            with self.subTest(variant=f_variant):
                self.assertNotEqual(f_base, f_variant)


class LsmioBoundCommandContractTest(unittest.TestCase):
    """Tests for LsmioBoundCommand validation, defaults, serialization, and equality contracts."""

    def testLsmioBoundCommandRejectsInvalidResultPath(self) -> None:
        """Verify LsmioBoundCommand rejects invalid non-string or whitespace-only result_path."""
        for f_bad in (123, "", "   ", "\t"):
            with self.subTest(result_path=f_bad):
                with self.assertRaises(BenchmarkConfigurationError) as f_ctx:
                    LsmioBoundCommand(
                        f_argv=["cmd"],
                        f_stdout_path="/out",
                        f_stderr_path="/err",
                        f_working_dir="/work",
                        f_result_path=f_bad,  # type: ignore[arg-type]
                    )
                self.assertIn(
                    "result_path must be a non-empty string",
                    str(f_ctx.exception),
                )

    def testLsmioBoundCommandRejectsNulInResultPath(self) -> None:
        """Verify LsmioBoundCommand rejects result_path containing NUL bytes."""
        with self.assertRaises(BenchmarkConfigurationError) as f_ctx:
            LsmioBoundCommand(
                f_argv=["cmd"],
                f_stdout_path="/out",
                f_stderr_path="/err",
                f_working_dir="/work",
                f_result_path="/res/path\0.json",
            )
        self.assertIn(
            "result_path contains NUL byte:", str(f_ctx.exception)
        )

    def testLsmioBoundCommandRejectsInvalidOutputPath(self) -> None:
        """Verify LsmioBoundCommand rejects invalid non-string or whitespace-only output_path."""
        for f_bad in (123, "", "   ", "\t"):
            with self.subTest(output_path=f_bad):
                with self.assertRaises(BenchmarkConfigurationError) as f_ctx:
                    LsmioBoundCommand(
                        f_argv=["cmd"],
                        f_stdout_path="/out",
                        f_stderr_path="/err",
                        f_working_dir="/work",
                        f_output_path=f_bad,  # type: ignore[arg-type]
                    )
                self.assertIn(
                    "output_path must be a non-empty string",
                    str(f_ctx.exception),
                )

    def testLsmioBoundCommandRejectsNulInOutputPath(self) -> None:
        """Verify LsmioBoundCommand rejects output_path containing NUL bytes."""
        with self.assertRaises(BenchmarkConfigurationError) as f_ctx:
            LsmioBoundCommand(
                f_argv=["cmd"],
                f_stdout_path="/out",
                f_stderr_path="/err",
                f_working_dir="/work",
                f_output_path="/out/path\0.bin",
            )
        self.assertIn(
            "output_path contains NUL byte:", str(f_ctx.exception)
        )

    def testLsmioBoundCommandDefaultsWhenPathsNone(self) -> None:
        """Verify LsmioBoundCommand defaults result_path and output_path to empty strings when None."""
        f_bcmd = LsmioBoundCommand(
            f_argv=["cmd"],
            f_stdout_path="/out",
            f_stderr_path="/err",
            f_working_dir="/work",
            f_result_path=None,
            f_output_path=None,
        )
        self.assertEqual(f_bcmd.result_path, "")
        self.assertEqual(f_bcmd.output_path, "")

    def testLsmioBoundCommandPropertiesAndAliases(self) -> None:
        """Verify LsmioBoundCommand properties, aliases, identity, and spec."""
        f_ident = RankIdentity(f_global_rank=0, f_node_rank="node1", f_local_rank=0)
        f_spec = "mock_spec"
        f_bcmd = LsmioBoundCommand(
            f_argv=["cmd"],
            f_stdout_path="/out",
            f_stderr_path="/err",
            f_working_dir="/work",
            f_result_path=" /res/data.json ",
            f_output_path=" /out/data.bin ",
            f_identity=f_ident,
            f_spec=f_spec,
        )
        self.assertEqual(f_bcmd.result_path, "/res/data.json")
        self.assertEqual(f_bcmd.resultPath, f_bcmd.result_path)
        self.assertEqual(f_bcmd.output_path, "/out/data.bin")
        self.assertEqual(f_bcmd.outputPath, f_bcmd.output_path)
        self.assertIs(f_bcmd.identity, f_ident)
        self.assertIs(f_bcmd.spec, f_spec)

    def testLsmioBoundCommandToDict(self) -> None:
        """Verify LsmioBoundCommand serialization with None identity, RankIdentity, and plain string identity."""
        with self.subTest(identity_none=True):
            f_bcmd1 = LsmioBoundCommand(
                f_argv=["cmd"],
                f_stdout_path="/out",
                f_stderr_path="/err",
                f_working_dir="/work",
                f_result_path="/res",
                f_output_path="/outpath",
                f_identity=None,
            )
            f_d1 = f_bcmd1.toDict()
            self.assertEqual(f_d1["result_path"], "/res")
            self.assertEqual(f_d1["output_path"], "/outpath")
            self.assertNotIn("identity", f_d1)

        with self.subTest(identity_structured=True):
            f_ident = RankIdentity(f_global_rank=0, f_node_rank="node1", f_local_rank=0)
            f_bcmd2 = LsmioBoundCommand(
                f_argv=["cmd"],
                f_stdout_path="/out",
                f_stderr_path="/err",
                f_working_dir="/work",
                f_result_path="/res",
                f_output_path="/outpath",
                f_identity=f_ident,
            )
            f_d2 = f_bcmd2.toDict()
            self.assertEqual(f_d2["result_path"], "/res")
            self.assertEqual(f_d2["output_path"], "/outpath")
            self.assertEqual(f_d2["identity"], f_ident.toDict())

        with self.subTest(identity_plain_string=True):
            f_bcmd3 = LsmioBoundCommand(
                f_argv=["cmd"],
                f_stdout_path="/out",
                f_stderr_path="/err",
                f_working_dir="/work",
                f_result_path="/res",
                f_output_path="/outpath",
                f_identity="plain_identity",
            )
            f_d3 = f_bcmd3.toDict()
            self.assertEqual(f_d3["identity"], "plain_identity")

    def testLsmioBoundCommandRepr(self) -> None:
        """Verify LsmioBoundCommand representation string contents."""
        f_bcmd = LsmioBoundCommand(
            f_argv=["cmd"],
            f_stdout_path="/out",
            f_stderr_path="/err",
            f_working_dir="/work",
            f_result_path="/res",
            f_output_path="/outpath",
        )
        f_repr = repr(f_bcmd)
        self.assertTrue(f_repr.startswith("LsmioBoundCommand("))
        self.assertIn("result_path='/res'", f_repr)
        self.assertIn("output_path='/outpath'", f_repr)

    def testLsmioBoundCommandHash(self) -> None:
        """Verify LsmioBoundCommand hash stability and equality in sets."""
        f_bcmd1 = LsmioBoundCommand(
            f_argv=["cmd"],
            f_stdout_path="/out",
            f_stderr_path="/err",
            f_working_dir="/work",
            f_result_path="/res",
            f_output_path="/outpath",
        )
        f_bcmd2 = LsmioBoundCommand(
            f_argv=["cmd"],
            f_stdout_path="/out",
            f_stderr_path="/err",
            f_working_dir="/work",
            f_result_path="/res",
            f_output_path="/outpath",
        )
        self.assertEqual(hash(f_bcmd1), hash(f_bcmd2))
        self.assertEqual(len({f_bcmd1, f_bcmd2}), 1)

    def testLsmioBoundCommandEqualityNonBoundCommand(self) -> None:
        """Verify LsmioBoundCommand returns False when compared against non-LsmioBoundCommand objects."""
        f_bcmd = LsmioBoundCommand(
            f_argv=["cmd"],
            f_stdout_path="/out",
            f_stderr_path="/err",
            f_working_dir="/work",
            f_result_path="/res",
            f_output_path="/outpath",
        )
        f_base_cmd = BenchmarkCommand(
            f_argv=["cmd"],
            f_stdout_path="/out",
            f_stderr_path="/err",
            f_working_dir="/work",
        )
        for f_other in ("string", 42, None, f_base_cmd):
            with self.subTest(other=f_other):
                self.assertFalse(f_bcmd == f_other)
                self.assertTrue(f_bcmd != f_other)

    def testLsmioBoundCommandEqualityPermutations(self) -> None:
        """Verify LsmioBoundCommand equality checks both base and subclass attributes."""
        f_base = LsmioBoundCommand(
            f_argv=["cmd"],
            f_stdout_path="/out",
            f_stderr_path="/err",
            f_working_dir="/work",
            f_is_rank_local=True,
            f_result_path="/res",
            f_output_path="/outpath",
            f_identity="id1",
        )
        f_same = LsmioBoundCommand(
            f_argv=["cmd"],
            f_stdout_path="/out",
            f_stderr_path="/err",
            f_working_dir="/work",
            f_is_rank_local=True,
            f_result_path="/res",
            f_output_path="/outpath",
            f_identity="id1",
        )
        self.assertEqual(f_base, f_same)

        f_diff_argv = LsmioBoundCommand(
            f_argv=["cmd2"],
            f_stdout_path="/out",
            f_stderr_path="/err",
            f_working_dir="/work",
            f_is_rank_local=True,
            f_result_path="/res",
            f_output_path="/outpath",
            f_identity="id1",
        )
        f_diff_stdout = LsmioBoundCommand(
            f_argv=["cmd"],
            f_stdout_path="/out2",
            f_stderr_path="/err",
            f_working_dir="/work",
            f_is_rank_local=True,
            f_result_path="/res",
            f_output_path="/outpath",
            f_identity="id1",
        )
        f_diff_stderr = LsmioBoundCommand(
            f_argv=["cmd"],
            f_stdout_path="/out",
            f_stderr_path="/err2",
            f_working_dir="/work",
            f_is_rank_local=True,
            f_result_path="/res",
            f_output_path="/outpath",
            f_identity="id1",
        )
        f_diff_work = LsmioBoundCommand(
            f_argv=["cmd"],
            f_stdout_path="/out",
            f_stderr_path="/err",
            f_working_dir="/work2",
            f_is_rank_local=True,
            f_result_path="/res",
            f_output_path="/outpath",
            f_identity="id1",
        )
        f_diff_rank = LsmioBoundCommand(
            f_argv=["cmd"],
            f_stdout_path="/out",
            f_stderr_path="/err",
            f_working_dir="/work",
            f_is_rank_local=False,
            f_result_path="/res",
            f_output_path="/outpath",
            f_identity="id1",
        )
        f_diff_res = LsmioBoundCommand(
            f_argv=["cmd"],
            f_stdout_path="/out",
            f_stderr_path="/err",
            f_working_dir="/work",
            f_is_rank_local=True,
            f_result_path="/res2",
            f_output_path="/outpath",
            f_identity="id1",
        )
        f_diff_out = LsmioBoundCommand(
            f_argv=["cmd"],
            f_stdout_path="/out",
            f_stderr_path="/err",
            f_working_dir="/work",
            f_is_rank_local=True,
            f_result_path="/res",
            f_output_path="/outpath2",
            f_identity="id1",
        )
        f_diff_id = LsmioBoundCommand(
            f_argv=["cmd"],
            f_stdout_path="/out",
            f_stderr_path="/err",
            f_working_dir="/work",
            f_is_rank_local=True,
            f_result_path="/res",
            f_output_path="/outpath",
            f_identity="id2",
        )

        for f_variant in (
            f_diff_argv,
            f_diff_stdout,
            f_diff_stderr,
            f_diff_work,
            f_diff_rank,
            f_diff_res,
            f_diff_out,
            f_diff_id,
        ):
            with self.subTest(variant=f_variant):
                self.assertNotEqual(f_base, f_variant)
