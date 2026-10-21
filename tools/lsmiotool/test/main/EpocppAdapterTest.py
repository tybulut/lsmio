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

"""EpocppAdapter: the deck template, the filled decks, the epocpp command and the probe.

EpocppRealRunTest also runs a tiny deck of every arm through a real epocpp under
mpirun: LSMIOTOOL_TEST_EPOCPP names the executable, else <home>/src/usr/bin/epocpp or
an epocpp on PATH; without one (or without mpirun) it is skipped.
"""

import os
import re
import shutil
import subprocess
import tempfile
from typing import Dict, List, NamedTuple, Optional
import unittest
from unittest.mock import patch

from lsmiotool.lib.benchmarks import (
    BenchmarkConfigurationError,
    BenchmarkProbeError,
    CapabilityState,
    EpocppAdapter,
)

_SHARE_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "share")
)
_TEMPLATE = EpocppAdapter.templatePath(_SHARE_ROOT)
_OUTPUT_SETUPS = ("POSIX", "ADIOS2", "PLUGIN", "NATIVE")

# The recommended decks (~/src/decks/input-*-{small,large}.deck) up to their output
# block, with nppc and nx as placeholders: the template's physics, exactly
_PHYSICS = """begin:constant
  drift_p = 2.5e-24
  temp = 273
  dens = 10
  nppc = ${nppc}
end:constant

begin:control
   x_min = 0
   x_max = 5.0e5
   y_min = x_min
   y_max = x_max
   nx = ${nx}
   ny = nx
   nsteps = 10
end:control

begin:boundaries
   bc_x_min = periodic
   bc_x_max = periodic
   bc_y_min = periodic
   bc_y_max = periodic
end:boundaries

begin:species
   # Rightwards travelling electrons
   name = Right
   charge = -1
   mass = 1.0
   temperature = temp
   drift_x = drift_p
   number_density = dens
   npart_per_cell = nppc
end:species

begin:species
   # Leftwards travelling electrons
   name = Left
   charge = -1
   mass = 1.0
   temperature = temp
   drift_x = -drift_p
   number_density = dens
   npart_per_cell = nppc
end:species

"""


class _Result(NamedTuple):
    returncode: int
    stdout: str
    stderr: str


def _outputBlock(f_deck: str) -> List[str]:
    """The output block's key lines, stripped."""
    f_block = f_deck[f_deck.index("begin:output") : f_deck.index("end:output")]
    return [f_line.strip() for f_line in f_block.splitlines()[1:] if f_line.strip()]


def _outsideOutput(f_deck: str) -> str:
    return f_deck[: f_deck.index("begin:output")]


class EpocppTemplateTest(unittest.TestCase):
    """The shipped template, and what readTemplate refuses."""

    def setUp(self) -> None:
        self.m_adapter = EpocppAdapter()
        self.m_dir = tempfile.mkdtemp(prefix="lsmiotool-epocpp-template-")

    def tearDown(self) -> None:
        shutil.rmtree(self.m_dir, ignore_errors=True)

    def _write(self, f_name: str, f_text: str) -> str:
        f_path = os.path.join(self.m_dir, f_name)
        with open(f_path, "w") as f_f:
            f_f.write(f_text)
        return f_path

    def testShippedTemplateHasExactlyTheThreePlaceholders(self) -> None:
        f_text = self.m_adapter.readTemplate(_TEMPLATE)
        self.assertEqual(
            sorted(set(re.findall(r"\$\{(\w+)\}", f_text))), ["nppc", "nx", "output"]
        )

    def testTemplatePhysicsIsExactlyTheRecommendedDecks(self) -> None:
        f_text = self.m_adapter.readTemplate(_TEMPLATE)
        # Comment lines, then the physics, then the output block placeholder
        f_lines = f_text.splitlines(keepends=True)
        f_start = next(
            f_i
            for f_i, f_l in enumerate(f_lines)
            if f_l.strip() and not f_l.startswith("#")
        )
        self.assertTrue(
            all(f_l.startswith("#") or not f_l.strip() for f_l in f_lines[:f_start])
        )
        self.assertEqual("".join(f_lines[f_start:]), _PHYSICS + "${output}\n")

    def testSymlinkIsRefused(self) -> None:
        f_link = os.path.join(self.m_dir, "link.deck.in")
        os.symlink(_TEMPLATE, f_link)
        with self.assertRaisesRegex(BenchmarkConfigurationError, "symlink"):
            self.m_adapter.readTemplate(f_link)

    def testMissingOrNonRegularIsRefused(self) -> None:
        with self.assertRaisesRegex(BenchmarkConfigurationError, "not found"):
            self.m_adapter.readTemplate(os.path.join(self.m_dir, "absent"))
        with self.assertRaisesRegex(BenchmarkConfigurationError, "not a regular file"):
            self.m_adapter.readTemplate(self.m_dir)

    def testWrongPlaceholdersAreRefused(self) -> None:
        for f_text in (
            "nx = ${nx}\n${output}\n",
            "nx = ${nx}\nnppc = ${nppc}\n${output}\nny = ${ny}\n",
            "nx = ${nx}\nnppc = ${nppc}\n${output}\ncost = $5\n",
            "nx = $nx\nnppc = ${nppc}\n${output}\n",
        ):
            with (
                self.subTest(f_text=f_text),
                self.assertRaises(BenchmarkConfigurationError),
            ):
                self.m_adapter.readTemplate(self._write("bad.deck.in", f_text))


class EpocppDeckTest(unittest.TestCase):
    """The filled deck of every arm and deck size."""

    def setUp(self) -> None:
        self.m_adapter = EpocppAdapter()
        self.m_template = self.m_adapter.readTemplate(_TEMPLATE)

    def testSizesOfEveryScale(self) -> None:
        self.assertEqual(
            {
                f_scale: EpocppAdapter.deckForScale(f_scale)
                for f_scale in ("local", "bake", "small", "large")
            },
            {"local": "small", "bake": "small", "small": "small", "large": "large"},
        )
        with self.assertRaises(BenchmarkConfigurationError):
            EpocppAdapter.deckForScale("variants")
        for f_deck, (f_nx, f_nppc) in (("small", (128, 64)), ("large", (1024, 128))):
            f_text = self.m_adapter.renderDeck(self.m_template, "POSIX", f_deck)
            self.assertIn(f"\n   nx = {f_nx}\n", f_text)
            self.assertIn(f"\n  nppc = {f_nppc}\n", f_text)

    def testOnlyTheOutputBlockDiffersBetweenArms(self) -> None:
        for f_deck in ("small", "large"):
            f_bodies = {
                _outsideOutput(self.m_adapter.renderDeck(self.m_template, f_s, f_deck))
                for f_s in EpocppAdapter.ALLOWED_SETUPS
            }
            self.assertEqual(len(f_bodies), 1)

    def testNoPlaceholderSurvives(self) -> None:
        for f_setup in EpocppAdapter.ALLOWED_SETUPS:
            for f_deck in ("small", "large"):
                f_text = self.m_adapter.renderDeck(self.m_template, f_setup, f_deck)
                self.assertNotIn("$", f_text)
                self.assertEqual(f_text.count("begin:output"), 1)

    def testBaselineNeverDumps(self) -> None:
        f_keys = _outputBlock(self.m_adapter.renderDeck(self.m_template, "NONE"))
        self.assertEqual(
            f_keys,
            [
                "name = data",
                "dump_first = F",
                "dump_last = F",
                "nstep_snapshot = 0",
                "particles = always",
                "px = always",
                "py = always",
            ],
        )

    def testEveryBackendDumpsFullRestartDumpsPerProcess(self) -> None:
        f_backend_keys = {
            "POSIX": ["filetype = posix"],
            "ADIOS2": ["filetype = adios"],
            "PLUGIN": ["filetype = adios", "adios_engine = plugin"],
            "NATIVE": ["filetype = lsmio"],
        }
        for f_setup in _OUTPUT_SETUPS:
            with self.subTest(f_setup=f_setup):
                f_keys = _outputBlock(
                    self.m_adapter.renderDeck(self.m_template, f_setup, "large")
                )
                self.assertEqual(
                    f_keys,
                    [
                        "name = data",
                        "dump_first = T",
                        "dump_last = T",
                        "nstep_snapshot = 1",
                        "restartable = T",
                        "particles = always",
                        "px = always",
                        "py = always",
                        "file_per_process = T",
                        *f_backend_keys[f_setup],
                    ],
                )
                # Keys a backend must not get: another backend's, or shared output
                self.assertNotIn("file_per_process = F", f_keys)
                if f_setup != "PLUGIN":
                    self.assertFalse(
                        any(f_k.startswith("adios_engine") for f_k in f_keys)
                    )
                self.assertEqual(sum(f_k.startswith("filetype") for f_k in f_keys), 1)

    def testSizeOverridesAndBadValues(self) -> None:
        f_text = self.m_adapter.renderDeck(
            self.m_template, "NATIVE", "large", f_nx=16, f_nppc=4
        )
        self.assertIn("\n   nx = 16\n", f_text)
        self.assertIn("\n  nppc = 4\n", f_text)
        for f_kw in ({"f_nx": 0}, {"f_nppc": -1}, {"f_nx": True}, {"f_nppc": "8"}):
            with self.assertRaises(BenchmarkConfigurationError):
                self.m_adapter.renderDeck(self.m_template, "POSIX", **f_kw)
        with self.assertRaises(BenchmarkConfigurationError):
            self.m_adapter.renderDeck(self.m_template, "POSIX", "medium")
        with self.assertRaises(BenchmarkConfigurationError):
            self.m_adapter.renderDeck(self.m_template, "HDF5")

    def testWriteDeckCreatesInputDeckOnce(self) -> None:
        f_dir = tempfile.mkdtemp(prefix="lsmiotool-epocpp-deck-")
        try:
            f_path = self.m_adapter.writeDeck("deck text\n", f_dir)
            self.assertEqual(f_path, os.path.join(f_dir, "input.deck"))
            with open(f_path) as f_f:
                self.assertEqual(f_f.read(), "deck text\n")
            with self.assertRaises(BenchmarkConfigurationError):
                self.m_adapter.writeDeck("again\n", f_dir)
            with self.assertRaises(BenchmarkConfigurationError):
                self.m_adapter.writeDeck("x\n", os.path.join(f_dir, "absent"))
        finally:
            shutil.rmtree(f_dir, ignore_errors=True)

    def testFailedWriteLeavesNoDeck(self) -> None:
        f_dir = tempfile.mkdtemp(prefix="lsmiotool-epocpp-deck-")
        try:
            with self.assertRaises(BenchmarkConfigurationError):
                self.m_adapter.writeDeck(b"bytes", f_dir)
            with (
                patch("os.fsync", side_effect=OSError(5, "I/O error")),
                self.assertRaisesRegex(BenchmarkConfigurationError, "written"),
            ):
                self.m_adapter.writeDeck("deck\n", f_dir)
            self.assertEqual(os.listdir(f_dir), [])
            # The directory's fsync (the second) failing also removes the deck
            f_fsync = os.fsync
            f_calls = []

            def _secondFails(f_fd: int) -> None:
                f_calls.append(f_fd)
                if len(f_calls) == 2:
                    raise OSError(5, "I/O error")
                f_fsync(f_fd)

            with (
                patch("os.fsync", side_effect=_secondFails),
                self.assertRaisesRegex(BenchmarkConfigurationError, "written"),
            ):
                self.m_adapter.writeDeck("deck\n", f_dir)
            self.assertEqual(len(f_calls), 2)
            self.assertEqual(os.listdir(f_dir), [])
            with self.assertRaisesRegex(BenchmarkConfigurationError, "UTF-8"):
                self.m_adapter.writeDeck("bad \udc80\n", f_dir)
            self.assertEqual(os.listdir(f_dir), [])
            self.m_adapter.writeDeck("deck\n", f_dir)
            self.assertEqual(os.listdir(f_dir), ["input.deck"])
        finally:
            shutil.rmtree(f_dir, ignore_errors=True)

    def testDeckSizeNameIsNormalised(self) -> None:
        self.assertEqual(
            self.m_adapter.renderDeck(self.m_template, "POSIX", " Large "),
            self.m_adapter.renderDeck(self.m_template, "POSIX", "large"),
        )


class EpocppCommandTest(unittest.TestCase):
    """The epocpp argv for each kind, the refusals and the probe."""

    def setUp(self) -> None:
        self.m_adapter = EpocppAdapter()

    def _build(self, f_setup: str, **f_kw: str):
        f_args: Dict[str, str] = {
            "f_executable": "/prefix/bin/epocpp",
            "f_deck_dir": "/run/work/c4_b1M",
            "f_data_dir": "/run/data/c4/b1M",
            "f_working_dir": "/run/work/c4_b1M",
            "f_stdout_path": "/run/logs/epocpp_c4_b1M_r01.stdout",
        }
        f_args.update(f_kw)
        return self.m_adapter.buildCommand(f_setup=f_setup, **f_args)

    def testArmSetups(self) -> None:
        self.assertEqual(len(EpocppAdapter.ALLOWED_SETUPS), 9)
        self.assertEqual(EpocppAdapter.splitSetup("none"), ("NONE", "walltime"))
        self.assertEqual(EpocppAdapter.splitSetup("PLUGIN"), ("PLUGIN", "walltime"))
        self.assertEqual(EpocppAdapter.splitSetup("plugin-bw"), ("PLUGIN", "bandwidth"))
        for f_bad in ("NONE-BW", "HDF5", "-BW"):
            with self.assertRaises(BenchmarkConfigurationError):
                EpocppAdapter.splitSetup(f_bad)

    def testWallTimeAndBandwidthArgv(self) -> None:
        f_wall = self._build("POSIX")
        self.assertEqual(
            list(f_wall.argv),
            ["/prefix/bin/epocpp", "-i", "/run/work/c4_b1M", "-o", "/run/data/c4/b1M"],
        )
        self.assertFalse(f_wall.is_rank_local)
        self.assertEqual(f_wall.stdout_path, "/run/logs/epocpp_c4_b1M_r01.stdout")
        self.assertEqual(f_wall.working_dir, "/run/work/c4_b1M")
        f_bw = self._build("native-bw")
        self.assertEqual(
            list(f_bw.argv),
            [
                "/prefix/bin/epocpp",
                "--io-benchmark",
                "-m",
                "-i",
                "/run/work/c4_b1M",
                "-o",
                "/run/data/c4/b1M",
            ],
        )
        self.assertEqual(list(self._build("NONE").argv), list(f_wall.argv))

    def testRefusals(self) -> None:
        # The baseline has no bandwidth arm
        with self.assertRaisesRegex(
            BenchmarkConfigurationError, "Unknown EPOCpp setup"
        ):
            self._build("NONE-BW")
        for f_setup in ("HDF5", "POSIX-FAST", "", "BW"):
            with self.assertRaises(BenchmarkConfigurationError):
                self._build(f_setup)
        for f_kw in (
            {"f_data_dir": ""},
            {"f_data_dir": "/run/data/\0"},
            {"f_stdout_path": "/run/logs/rank_{rank}.log"},
            {"f_executable": "  "},
        ):
            with (
                self.subTest(f_kw=f_kw),
                self.assertRaises(BenchmarkConfigurationError),
            ):
                self._build("POSIX", **f_kw)

    def testProbe(self) -> None:
        self.assertEqual(
            self.m_adapter.probeCapability("/prefix/bin/epocpp"),
            CapabilityState.CONFIGURED,
        )
        f_help = "  --io-benchmark   Time every dump\n  -m,--mpi-barrier\n"
        self.assertEqual(
            self.m_adapter.probeCapability(
                "/prefix/bin/epocpp", lambda f_argv: _Result(0, f_help, "")
            ),
            CapabilityState.VERIFIED,
        )
        with self.assertRaisesRegex(BenchmarkProbeError, "LSMIO"):
            self.m_adapter.probeCapability(
                "/prefix/bin/epocpp", lambda f_argv: _Result(0, "  -i,--input\n", "")
            )
        with self.assertRaisesRegex(BenchmarkProbeError, "exit code 1"):
            self.m_adapter.probeCapability(
                "/prefix/bin/epocpp", lambda f_argv: _Result(1, "", "boom")
            )
        with self.assertRaises(BenchmarkProbeError):
            self.m_adapter.probeCapability("/prefix/bin/epocpp", f_setup="HDF5")

    def testProbeResultForms(self) -> None:
        f_help = "  --io-benchmark   Time every dump\n"

        def _raise(f_argv):
            raise FileNotFoundError("no such file")

        self.assertEqual(
            self.m_adapter.probeCapability("/e", lambda f_argv: (0, f_help)),
            CapabilityState.VERIFIED,
        )
        self.assertEqual(
            self.m_adapter.probeCapability("/e", lambda f_argv: f_help),
            CapabilityState.VERIFIED,
        )

        class _ExitCodeOnly:
            # Not a tuple: only the exit_code reading can accept it
            def __init__(self, f_code: int, f_stdout: str) -> None:
                self.exit_code = f_code
                self.stdout = f_stdout

        self.assertEqual(
            self.m_adapter.probeCapability(
                "/e", lambda f_argv: _ExitCodeOnly(0, f_help)
            ),
            CapabilityState.VERIFIED,
        )
        for f_runner in (
            _raise,
            lambda f_argv: _Result(None, f_help, ""),
            lambda f_argv: _Result(False, f_help, ""),
            lambda f_argv: _ExitCodeOnly(3, f_help),
            lambda f_argv: (2, f_help),
            lambda f_argv: (None, f_help),
            lambda f_argv: (False, f_help),
            lambda f_argv: 0,
        ):
            with self.assertRaises(BenchmarkProbeError):
                self.m_adapter.probeCapability("/e", f_runner)
        with self.assertRaises(BenchmarkConfigurationError):
            self.m_adapter.probeCapability("/prefix/bin/ep\0occ")


def _findEpocpp() -> Optional[str]:
    for f_path in (
        os.environ.get("LSMIOTOOL_TEST_EPOCPP"),
        os.path.join(os.path.expanduser("~"), "src", "usr", "bin", "epocpp"),
        shutil.which("epocpp"),
    ):
        if f_path and os.path.isfile(f_path) and os.access(f_path, os.X_OK):
            return f_path
    return None


_EPOCPP = _findEpocpp()
_MPIRUN = shutil.which("mpirun")


@unittest.skipUnless(
    _EPOCPP and _MPIRUN, "no epocpp (LSMIOTOOL_TEST_EPOCPP) or no mpirun found"
)
class EpocppRealRunTest(unittest.TestCase):
    """A tiny filled deck of every arm through the real epocpp on 2 ranks."""

    def setUp(self) -> None:
        self.m_adapter = EpocppAdapter()
        self.m_template = self.m_adapter.readTemplate(_TEMPLATE)
        self.m_dir = tempfile.mkdtemp(prefix="lsmiotool-epocpp-run-")

    def tearDown(self) -> None:
        shutil.rmtree(self.m_dir, ignore_errors=True)

    def _run(self, f_setup: str) -> tuple:
        f_root = os.path.join(self.m_dir, f_setup)
        f_work = os.path.join(f_root, "work")
        f_data = os.path.join(f_root, "data")
        os.makedirs(f_work)
        os.makedirs(f_data)
        self.m_adapter.writeDeck(
            self.m_adapter.renderDeck(self.m_template, f_setup, f_nx=16, f_nppc=4),
            f_work,
        )
        f_cmd = self.m_adapter.buildCommand(
            _EPOCPP, f_setup, f_work, f_data, f_work, f"{f_root}/out.log"
        )
        # ADIOS2 then finds the plugin on the library search path, as in the jobs
        f_env = {
            f_k: f_v for f_k, f_v in os.environ.items() if f_k != "ADIOS2_PLUGIN_PATH"
        }
        f_proc = subprocess.run(
            [_MPIRUN, "-np", "2", *f_cmd.argv],
            cwd=f_cmd.working_dir,
            env=f_env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return (
            f_proc.returncode,
            f_proc.stdout + f_proc.stderr,
            sorted(os.listdir(f_data)),
        )

    def testBaselineRunsAndWritesNothing(self) -> None:
        f_rc, f_out, f_files = self._run("NONE")
        self.assertEqual(f_rc, 0, f_out)
        self.assertRegex(f_out, r"Runtime = [0-9.]+")
        self.assertEqual(f_files, [])

    def testEveryBackendWritesItsOwnFileType(self) -> None:
        for f_setup in _OUTPUT_SETUPS:
            f_ext = EpocppAdapter.OUTPUT_EXTENSIONS[f_setup]
            # 11 dumps (dump_first, then every step of 10) on each of the 2 ranks
            f_expected = [
                f"data{f_step:05d}_{f_rank:03d}.{f_ext}"
                for f_step in range(11)
                for f_rank in range(2)
            ]
            for f_arm in (f_setup, f_setup + EpocppAdapter.BANDWIDTH_SUFFIX):
                f_kind = EpocppAdapter.splitSetup(f_arm)[1]
                with self.subTest(f_arm=f_arm):
                    f_rc, f_out, f_files = self._run(f_arm)
                    self.assertEqual(f_rc, 0, f_out)
                    self.assertRegex(f_out, r"Runtime = [0-9.]+")
                    self.assertEqual(f_files, f_expected)
                    if f_kind == EpocppAdapter.KIND_BANDWIDTH:
                        # --io-benchmark accepted the deck as a full restart dump
                        self.assertIn("BENCHMARK RESULTS:", f_out)
                        self.assertRegex(f_out, r"\nwrite,[0-9]")
                        self.assertRegex(f_out, r"\nread,[0-9]")
                        self.assertNotIn("FAILED", f_out)
                    else:
                        self.assertNotIn("BENCHMARK RESULTS:", f_out)


if __name__ == "__main__":
    unittest.main()
