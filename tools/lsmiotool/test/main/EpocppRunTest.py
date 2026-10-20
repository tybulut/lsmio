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

"""The epocpp workload's command line, arms, plan, manifest, site and preflight
(`run epocpp backends`), and its orchestration with the fake scheduler."""

import json
import os
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Tuple
import unittest

from lsmiotool.lib.archive import resolveArchiveDest
from lsmiotool.lib.arms import (
    ArmError,
    epocppArms,
    isEpocppArmId,
    resolveArmGroup,
)
from lsmiotool.lib.benchmarks import EpocppAdapter
from lsmiotool.lib.cli import RunCliParseError, parseRunArguments
from lsmiotool.lib.profile import ProfileLoader, ProfileSchemaError
from lsmiotool.lib.resources import ExecutionMode, RuntimeLayout
from lsmiotool.lib.run import (
    ManifestSerializer,
    ManifestValidationError,
    PlanValidationError,
    PreflightError,
    RunOrchestrator,
    RunPlanner,
    RunRequest,
    groupRunCount,
)
from lsmiotool.lib.site import (
    EnvironmentResolver,
    ExecutableRegistry,
    SiteProfile,
    SiteResolutionError,
)
from lsmiotool.lib.worker import ProcessResult
from lsmiotool.test.main import RunOrchestratorTest as _orchestrator

_SHARE_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "share")
)
_PROFILE_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "etc", "environments.json")
)
_ALL_ARMS = [
    ("baseline", "NONE", "epocpp-baseline"),
    ("posix", "POSIX", "epocpp-posix"),
    ("adios2", "ADIOS2", "epocpp-adios2"),
    ("plugin", "PLUGIN", "epocpp-plugin"),
    ("native", "NATIVE", "epocpp-native"),
    ("posix-bw", "POSIX-BW", "epocpp-posix-bw"),
    ("adios2-bw", "ADIOS2-BW", "epocpp-adios2-bw"),
    ("plugin-bw", "PLUGIN-BW", "epocpp-plugin-bw"),
    ("native-bw", "NATIVE-BW", "epocpp-native-bw"),
]


class EpocppCliTest(unittest.TestCase):
    """`run epocpp backends <scale> [<backends>] [--repeats <n>]`."""

    def testDefaultsAndOptions(self) -> None:
        f_req = parseRunArguments(["run", "epocpp", "backends", "small"], f_environ={})
        self.assertEqual(f_req.target, "epocpp")
        self.assertEqual(f_req.mode, "backends")
        self.assertEqual(f_req.backends, ("posix", "adios2", "plugin", "native"))
        self.assertIsNone(f_req.repeats)
        f_req = parseRunArguments(
            [
                "run",
                "epocpp",
                "backends",
                "large",
                "Native,posix",
                "--repeats",
                "1",
                "--time",
                "5",
                "--ssd",
                "--no-archive",
                "--resume",
            ],
            f_environ={},
        )
        self.assertEqual(f_req.backends, ("native", "posix"))
        self.assertEqual(f_req.repeats, 1)
        self.assertEqual(f_req.wallhour, 5)
        self.assertTrue(f_req.ssd)
        self.assertIs(f_req.archive, False)
        self.assertTrue(f_req.resume)

    def testNodesOption(self) -> None:
        f_req = parseRunArguments(
            ["run", "epocpp", "backends", "small", "adios2", "--nodes", "32"],
            f_environ={},
        )
        self.assertEqual(f_req.nodes, (32,))
        self.assertEqual(f_req.backends, ("adios2",))
        f_req = parseRunArguments(
            ["run", "epocpp", "backends", "small", "--nodes", "40, 24,32"],
            f_environ={},
        )
        self.assertEqual(f_req.nodes, (40, 24, 32))
        for f_argv in (
            ["run", "lsmio", "backends", "small", "adios2", "--nodes", "8,2"],
            ["run", "ior", "small", "--nodes", "8,2"],
            ["run", "ior", "small", "base,hdf5", "--nodes", "2"],
        ):
            with self.subTest(f_argv=f_argv):
                self.assertIsNotNone(parseRunArguments(f_argv, f_environ={}).nodes)
        self.assertIsNone(
            parseRunArguments(
                ["run", "epocpp", "backends", "small"], f_environ={}
            ).nodes
        )
        for f_argv in (
            ["run", "epocpp", "backends", "small", "--nodes"],
            ["run", "epocpp", "backends", "small", "--nodes", ""],
            ["run", "epocpp", "backends", "small", "--nodes", "0"],
            ["run", "epocpp", "backends", "small", "--nodes", "x"],
            ["run", "epocpp", "backends", "small", "--nodes", "\u00b2"],
            ["run", "epocpp", "backends", "small", "--nodes", "8,"],
            ["run", "epocpp", "backends", "small", "--nodes", "8,8"],
            ["run", "epocpp", "backends", "small", "--nodes", "8,08"],
            ["run", "epocpp", "backends", "small", "--nodes", "1" * 10],
            ["run", "epocpp", "backends", "small", "--nodes", "9" * 5000],
            ["run", "epocpp", "backends", "small", "--nodes=8"],
            ["run", "epocpp", "backends", "small", "--nodes", "8", "--nodes", "16"],
            # Only backends runs take it: not plain scaling, variants or lmp runs
            ["run", "lsmio", "small", "--nodes", "8"],
            ["run", "lsmio", "variants", "legacy", "--nodes", "8"],
            ["run", "lmp", "small", "--nodes", "8"],
        ):
            with self.subTest(f_argv=f_argv), self.assertRaises(RunCliParseError):
                parseRunArguments(f_argv, f_environ={})

    def testRefusals(self) -> None:
        with self.assertRaisesRegex(RunCliParseError, "'run epocpp backends'"):
            parseRunArguments(["run", "epocpp", "backends"], f_environ={})
        with self.assertRaisesRegex(RunCliParseError, "'run epocpp backends'"):
            parseRunArguments(
                ["run", "epocpp", "backends", "--repeats", "2"], f_environ={}
            )
        for f_argv in (
            ["run", "epocpp", "small"],
            ["run", "epocpp", "backends", "variants"],
            ["run", "epocpp", "backends", "small", "hdf5"],
            ["run", "epocpp", "backends", "small", "posix,posix"],
            ["run", "epocpp", "backends", "small", "--setup", "POSIX"],
            ["run", "epocpp", "backends", "small", "--repeats", "0"],
            ["run", "epocpp", "backends", "small", "--repeats", "x"],
            ["run", "epocpp", "backends", "small", "--repeats", "\u00b2"],
            ["run", "epocpp", "backends", "small", "--repeats"],
            ["run", "epocpp", "backends", "small", "--repeats=2"],
            ["run", "epocpp", "backends", "small", "--repeats", "2", "--repeats", "3"],
            ["run", "lsmio", "backends", "small", "--repeats", "2"],
            ["run", "ior", "small", "--repeats", "2"],
        ):
            with self.subTest(f_argv=f_argv), self.assertRaises(RunCliParseError):
                parseRunArguments(f_argv, f_environ={})


class EpocppArmsTest(unittest.TestCase):
    """The 9 arms: the baseline, then each backend's wall-time and bandwidth arm."""

    def testAllArmsInRunOrder(self) -> None:
        f_req = parseRunArguments(["run", "epocpp", "backends", "small"], f_environ={})
        f_group = resolveArmGroup(f_req, "POSIX", "/prefix")
        self.assertEqual(f_group.kind, "backends")
        self.assertTrue(f_group.archive)
        self.assertEqual(
            [(f_a.label, f_a.setup, f_a.arm_id) for f_a in f_group.arms], _ALL_ARMS
        )
        for f_arm in f_group.arms:
            self.assertIn(f_arm.setup, EpocppAdapter.ALLOWED_SETUPS)
            self.assertTrue(isEpocppArmId(f_arm.arm_id))

    def testSubsetAndNoArchive(self) -> None:
        f_req = parseRunArguments(
            ["run", "epocpp", "backends", "bake", "plugin", "--no-archive"],
            f_environ={},
        )
        f_group = resolveArmGroup(f_req, "POSIX", "/prefix")
        self.assertEqual(
            [f_a.arm_id for f_a in f_group.arms],
            ["epocpp-baseline", "epocpp-plugin", "epocpp-plugin-bw"],
        )
        self.assertFalse(f_group.archive)
        with self.assertRaises(ArmError):
            epocppArms([])
        self.assertFalse(isEpocppArmId("ior"))
        self.assertFalse(isEpocppArmId(None))


class EpocppPlanTest(unittest.TestCase):
    """Scale points, walltimes, repeats and the manifest."""

    def setUp(self) -> None:
        f_doc = ProfileLoader.load(_PROFILE_PATH)
        f_registry = EnvironmentResolver.resolveRegistry(
            f_doc, f_user="alice", f_home="/home/alice"
        )
        self.m_registry = f_registry
        self.m_viking2 = f_registry.getProfile("VIKING2")
        self.m_isambard = f_registry.getProfile("ISAMBARD")

    def _plan(
        self,
        f_scale: str,
        f_setup: str = "POSIX",
        f_profile: Optional[SiteProfile] = None,
        **f_kw: Any,
    ):
        return RunPlanner.createPlan(
            f_request=RunRequest("epocpp", f_scale, f_setup=f_setup, **f_kw),
            f_profile=f_profile or self.m_viking2,
            f_run_id_source=lambda: "run-20261018T000000Z-0123456789ab",
            f_clock=lambda: "2026-10-18T00:00:00Z",
        )

    def testScalePoints(self) -> None:
        f_expected = {
            "local": [(1, 1, 1)],
            "bake": [(1, 1, 1), (2, 1, 2), (4, 1, 4), (8, 1, 8)],
            "small": [(f_n, 1, f_n) for f_n in (2, 4, 8, 16, 24, 32, 40, 48)],
            "large": [(4 * f_n, 4, f_n) for f_n in (8, 16, 32, 48, 64)],
        }
        for f_scale, f_points in f_expected.items():
            with self.subTest(f_scale=f_scale):
                self.assertEqual(
                    [
                        (f_sp.tasks, f_sp.ppn, f_sp.nodes)
                        for f_sp in self._plan(f_scale).scale_points
                    ],
                    f_points,
                )
        with self.assertRaises(PlanValidationError):
            self._plan("variants")
        # Other targets keep the shared matrices
        self.assertEqual(RunPlanner.scalePoints("lsmio", "small")[0].nodes, 1)

    def testWalltimes(self) -> None:
        def _hours(f_plan) -> List[str]:
            return [f_p.walltime for f_p in f_plan.scheduled_points]

        self.assertEqual(_hours(self._plan("small")), ["12:00:00"] * 8)
        self.assertEqual(_hours(self._plan("bake")), ["12:00:00"] * 4)
        self.assertEqual(
            _hours(self._plan("large")),
            ["12:00:00", "12:00:00", "16:00:00", "20:00:00", "36:00:00"],
        )
        # --fast halves them
        self.assertEqual(_hours(self._plan("small", f_fast=True)), ["06:00:00"] * 8)
        self.assertEqual(
            _hours(self._plan("large", f_fast=True)),
            ["06:00:00", "06:00:00", "08:00:00", "10:00:00", "18:00:00"],
        )
        self.assertEqual(_hours(self._plan("large", f_wallhour=3)), ["03:00:00"] * 5)

    def testArcher2QosFollowsTheWalltime(self) -> None:
        # Over 24 hours ARCHER2's 'standard' QoS becomes 'long': only the large 64-node
        # point, and not with --fast
        f_archer2 = self.m_registry.getProfile("ARCHER2")

        def _qos(f_scale: str, **f_kw: Any) -> List[Tuple[int, str, str]]:
            f_plan = self._plan(f_scale, f_profile=f_archer2, **f_kw)
            return [
                (f_plan.scale_points[f_i].nodes, f_p.walltime, f_p.qos)
                for f_i, f_p in enumerate(f_plan.scheduled_points)
            ]

        self.assertEqual(
            _qos("large"),
            [
                (8, "12:00:00", "standard"),
                (16, "12:00:00", "standard"),
                (32, "16:00:00", "standard"),
                (48, "20:00:00", "standard"),
                (64, "36:00:00", "long"),
            ],
        )
        # The job script asks for it: 36 hours in the long QoS
        f_plan = self._plan("large", f_profile=f_archer2)
        f_directives, _ = RunOrchestrator._renderPointDirectives(
            f_archer2,
            f_plan.scale_points[-1],
            f_plan.scheduled_points[-1],
            "lm-0123456789abcdef01234567",
            "/tmp/out",
            "/tmp/err",
            "e281",
            None,
        )
        self.assertIn("#SBATCH --qos=long", f_directives)
        self.assertIn("#SBATCH --time=36:00:00", f_directives)
        self.assertEqual(
            {f_q for _, _, f_q in _qos("large", f_fast=True)}, {"standard"}
        )
        self.assertEqual({f_q for _, _, f_q in _qos("small")}, {"standard"})

    def testFixedWalltimeSite(self) -> None:
        # ISAMBARD's PBS template walltime is per arm: 9 arms x 6 h, capped at 48 h
        f_plan = RunPlanner.createPlan(
            f_request=parseRunArguments(
                ["run", "epocpp", "backends", "small"], f_environ={}
            ),
            f_profile=self.m_isambard,
            f_run_id_source=lambda: "run-20261018T000000Z-0123456789ab",
            f_clock=lambda: "2026-10-18T00:00:00Z",
        )
        self.assertEqual(
            {f_p.walltime for f_p in f_plan.scheduled_points}, {"48:00:00"}
        )

    def testProfileEpocppKeyIsOptional(self) -> None:
        with open(_PROFILE_PATH) as f_f:
            f_doc = json.load(f_f)
        f_dir = tempfile.mkdtemp(prefix="lsmiotool-epocpp-profile-")
        try:
            f_path = os.path.join(f_dir, "environments.json")
            for f_profile in f_doc["RUN_PROFILES"]["profiles"].values():
                del f_profile["executables"]["epocpp"]
            with open(f_path, "w") as f_f:
                json.dump(f_doc, f_f)
            ProfileLoader.load(f_path)
            for f_profile in f_doc["RUN_PROFILES"]["profiles"].values():
                f_profile["executables"]["epocpp2"] = "epocpp2"
            with open(f_path, "w") as f_f:
                json.dump(f_doc, f_f)
            with self.assertRaises(ProfileSchemaError):
                ProfileLoader.load(f_path)
        finally:
            shutil.rmtree(f_dir, ignore_errors=True)

    def testRepeatsAreRecorded(self) -> None:
        self.assertEqual(self._plan("small").request.repeats, 10)
        self.assertEqual(self._plan("small", f_repeats=1).request.repeats, 1)
        with self.assertRaises(PlanValidationError):
            RunRequest("epocpp", "small", f_repeats=0)
        with self.assertRaises(PlanValidationError):
            RunRequest("epocpp", "small", f_repeats=True)

    def testNodesPickScalePoints(self) -> None:
        def _nodes(f_plan: Any) -> List[int]:
            return [f_sp.nodes for f_sp in f_plan.scale_points]

        self.assertEqual(_nodes(self._plan("small", f_nodes=[32])), [32])
        # In the scale's order, with each point's own walltime
        f_plan = self._plan("large", f_nodes=[64, 8])
        self.assertEqual(_nodes(f_plan), [8, 64])
        self.assertEqual(
            [f_p.walltime for f_p in f_plan.scheduled_points], ["12:00:00", "36:00:00"]
        )
        # Recorded in the scale's order, not the order given
        self.assertEqual(f_plan.request.nodes, (8, 64))
        self.assertIsNone(self._plan("small").request.nodes)
        self.assertEqual(
            _nodes(self._plan("small", f_nodes=[48, 40, 32, 24, 16, 8, 4, 2])),
            _nodes(self._plan("small")),
        )
        # Nodes the scale does not run, and bad values
        with self.assertRaisesRegex(
            PlanValidationError, r"\[1\] are not in the 'small'"
        ):
            self._plan("small", f_nodes=[1])
        with self.assertRaisesRegex(
            PlanValidationError, r"\[12\] are not in the 'large'"
        ):
            self._plan("large", f_nodes=[8, 12])
        for f_bad in ([], [0], [True], [8, 8], "8", [8.0]):
            with self.subTest(f_bad=f_bad), self.assertRaises(PlanValidationError):
                RunRequest("epocpp", "small", f_nodes=f_bad)
        # lsmio and ior runs take it too, not lmp or variants runs
        for f_request in (
            RunRequest("lsmio", "small", f_mode="backends", f_nodes=[8, 2]),
            RunRequest("ior", "small", f_mode="backends", f_nodes=[8, 2]),
        ):
            self.assertEqual(
                _nodes(RunPlanner.createPlan(f_request, self.m_viking2)), [2, 8]
            )
        for f_request in (
            RunRequest("lmp", "small", f_nodes=[8]),
            RunRequest("lsmio", "variants", f_variants=["legacy"], f_nodes=[1]),
        ):
            with (
                self.subTest(f_request=f_request),
                self.assertRaisesRegex(
                    PlanValidationError, "only for 'lsmio backends'"
                ),
            ):
                RunPlanner.createPlan(f_request, self.m_viking2)

    def testEveryArmSetupPlans(self) -> None:
        for _, f_setup, _ in _ALL_ARMS:
            self.assertEqual(self._plan("bake", f_setup).request.setup, f_setup)
        with self.assertRaises(PlanValidationError):
            self._plan("bake", "HDF5")

    def testManifestRoundTripKeepsNodes(self) -> None:
        f_plan = self._plan("small", "ADIOS2-BW", f_nodes=[40, 32])
        f_text = ManifestSerializer.serialize(f_plan)
        self.assertEqual(json.loads(f_text)["request"]["nodes"], [32, 40])
        f_doc = ManifestSerializer.deserialize(f_text)
        self.assertEqual(f_doc.request, f_plan.request)
        self.assertEqual(f_doc.request.nodes, (32, 40))
        self.assertEqual(ManifestSerializer.serialize(f_doc.toRunPlan()), f_text)
        # A run without --nodes records none, and a bad record is refused
        self.assertNotIn(
            "nodes",
            json.loads(ManifestSerializer.serialize(self._plan("small")))["request"],
        )
        f_bad = json.loads(f_text)
        for f_value in ("32", [32, "8"], [True]):
            f_bad["request"]["nodes"] = f_value
            with (
                self.subTest(f_value=f_value),
                self.assertRaises(ManifestValidationError),
            ):
                ManifestSerializer.deserialize(json.dumps(f_bad))

    def testManifestRoundTripKeepsRepeats(self) -> None:
        f_plan = self._plan("large", "PLUGIN-BW", f_repeats=3)
        f_text = ManifestSerializer.serialize(f_plan)
        self.assertEqual(json.loads(f_text)["request"]["repeats"], 3)
        self.assertEqual(
            json.loads(f_text)["site"]["executables"]["epocpp"],
            "/home/alice/src/usr/bin/epocpp",
        )
        f_doc = ManifestSerializer.deserialize(f_text)
        self.assertEqual(f_doc.request, f_plan.request)
        self.assertEqual(ManifestSerializer.serialize(f_doc.toRunPlan()), f_text)

    def testManifestWithoutEpocppStillLoads(self) -> None:
        # A run made before epocpp was a site executable
        f_plan = RunPlanner.createPlan(
            f_request=RunRequest("ior", "bake", f_setup="BASE"),
            f_profile=self.m_viking2,
            f_run_id_source=lambda: "run-20261018T000000Z-0123456789ab",
            f_clock=lambda: "2026-10-18T00:00:00Z",
        )
        f_dict = json.loads(ManifestSerializer.serialize(f_plan))
        del f_dict["site"]["executables"]["epocpp"]
        self.assertNotIn(
            "epocpp", ManifestSerializer.deserialize(f_dict).site.executables.toDict()
        )
        f_dict["site"]["executables"]["epocpp2"] = "/x/bin/epocpp2"
        with self.assertRaises(ManifestValidationError):
            ManifestSerializer.deserialize(f_dict)

    def testGroupRunCountAndArchiveDest(self) -> None:
        self.assertEqual(
            groupRunCount(
                parseRunArguments(["run", "epocpp", "backends", "small"], f_environ={})
            ),
            9,
        )
        self.assertEqual(
            groupRunCount(
                parseRunArguments(
                    ["run", "epocpp", "backends", "small", "posix"], f_environ={}
                )
            ),
            3,
        )
        self.assertEqual(
            resolveArchiveDest("/bench", "backends", "large", f_target="epocpp"),
            "/bench/lsmio-archive/epocpp/large",
        )
        self.assertEqual(
            resolveArchiveDest(
                "/bench", "backends", "large", "/elsewhere", f_target="epocpp"
            ),
            "/elsewhere",
        )

    def testRegistryEpocppIsOptional(self) -> None:
        f_base = {
            f_k: f"/p/bin/{f_k}" for f_k in ExecutableRegistry.REQUIRED_EXECUTABLES
        }
        with self.assertRaises(SiteResolutionError):
            _ = ExecutableRegistry(f_base).epocpp
        self.assertEqual(
            ExecutableRegistry({**f_base, "epocpp": "/p/bin/epocpp"}).epocpp,
            "/p/bin/epocpp",
        )
        with self.assertRaises(SiteResolutionError):
            ExecutableRegistry({**f_base, "epocpp2": "/p/bin/epocpp2"})
        self.assertEqual(self.m_isambard.executables.epocpp.split("/")[-1], "epocpp")


class _EpocppFakeRunner(_orchestrator.FakeSchedulerCommandRunner):
    """The fake scheduler, also answering `epocpp --help`."""

    def __init__(self, f_help: str = "  --io-benchmark   Time every dump\n") -> None:
        super().__init__()
        self.m_help = f_help

    def run(
        self,
        f_argv: Sequence[str],
        f_cwd: Optional[str] = None,
        f_environment: Optional[Dict[str, str]] = None,
        f_log_path: Optional[str] = None,
    ) -> ProcessResult:
        if os.path.basename(f_argv[0]) == "epocpp":
            self.m_calls.append(list(f_argv))
            return ProcessResult(0, self.m_help, "", 0.01)
        return super().run(f_argv, f_cwd, f_environment, f_log_path)


class EpocppOrchestrationTest(unittest.TestCase):
    """`run epocpp backends` through the orchestrator with the fake scheduler."""

    setUp_ = _orchestrator.RunOrchestratorTest.setUp
    tearDown = _orchestrator.RunOrchestratorTest.tearDown
    _groupOnSubmit = _orchestrator.RunOrchestratorTest._groupOnSubmit
    _mockWritePointResults = _orchestrator.RunOrchestratorTest._mockWritePointResults
    _submittedScripts = staticmethod(
        _orchestrator.RunOrchestratorTest._submittedScripts
    )

    def setUp(self) -> None:
        self.setUp_()
        # An epocpp and the deck template under the install prefix, and the plugin
        self.m_epocpp = os.path.join(self.m_temp_dir, "bin", "epocpp")
        with open(self.m_epocpp, "w") as f_f:
            f_f.write("#!/bin/sh\nexit 0\n")
        os.chmod(self.m_epocpp, 0o755)
        f_template_dir = os.path.join(self.m_temp_dir, "share", "lsmio", "epocpp")
        os.makedirs(f_template_dir, exist_ok=True)
        shutil.copy(EpocppAdapter.templatePath(_SHARE_ROOT), f_template_dir)
        self.m_plugin = os.path.join(self.m_temp_dir, "lib", "liblsmio_adios.so")
        os.makedirs(os.path.dirname(self.m_plugin), exist_ok=True)
        open(self.m_plugin, "w").close()
        self.m_profile = self._profile(
            {**self.m_executables.toDict(), "epocpp": self.m_epocpp}
        )

    def _profile(self, f_executables: Dict[str, str]) -> SiteProfile:
        f_p = self.m_viking_profile
        return SiteProfile(
            f_name=f_p.name,
            f_scheduler=f_p.scheduler,
            f_launcher=f_p.launcher,
            f_certification=f_p.certification,
            f_test_only=True,
            f_benchmark_roots={
                f_k.value: f_v for f_k, f_v in f_p.benchmark_roots.items()
            }
            if hasattr(next(iter(f_p.benchmark_roots)), "value")
            else dict(f_p.benchmark_roots),
            f_install_prefix=f_p.install_prefix,
            f_executables=ExecutableRegistry(f_executables),
            f_modules=f_p.modules,
            f_resources=f_p.resources,
            f_rank_identity=f_p.rank_identity,
            f_cancellation=f_p.cancellation,
            f_lustre_pools=f_p.lustre_pools,
        )

    def _execute(
        self, f_argv: List[str], f_runner: Optional[Any] = None, f_profile=None
    ) -> RunOrchestrator:
        f_runner = f_runner or _EpocppFakeRunner()
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_runner,
            f_poll_interval=0.01,
        )
        f_runner.m_on_submit_callback = self._groupOnSubmit(f_orch)
        self.m_runner = f_runner
        f_orch.execute(
            parseRunArguments(f_argv, f_environ={}),
            f_site=f_profile or self.m_profile,
            f_worker_executable=self.m_worker_path,
        )
        return f_orch

    def testNodesRunOnlyThosePoints(self) -> None:
        f_orch = self._execute(
            [
                "run",
                "epocpp",
                "backends",
                "bake",
                "posix",
                "--repeats",
                "1",
                "--nodes",
                "4,2",
                "--no-archive",
            ]
        )
        for f_r in f_orch.groupRuns:
            self.assertEqual([f_sp.nodes for f_sp in f_r["plan"].scale_points], [2, 4])
            with open(f_r["store"].layout.manifestPath) as f_f:
                self.assertEqual(json.load(f_f)["request"]["nodes"], [2, 4])
        self.assertEqual(len(self._submittedScripts(self.m_runner)), 2)

    def testOneJobPerPointRunsEveryArm(self) -> None:
        f_orch = self._execute(
            ["run", "epocpp", "backends", "bake", "--repeats", "2", "--no-archive"]
        )
        f_runs = f_orch.groupRuns
        self.assertEqual(
            [
                (f_r["arm"].label, f_r["plan"].request.setup, f_r["arm"].arm_id)
                for f_r in f_runs
            ],
            _ALL_ARMS,
        )
        for f_r in f_runs:
            self.assertEqual(f_r["plan"].request.target, "epocpp")
            self.assertEqual(f_r["plan"].request.repeats, 2)
            with open(f_r["store"].layout.manifestPath) as f_f:
                self.assertEqual(json.load(f_f)["request"]["repeats"], 2)
        f_points = f_runs[0]["plan"].scale_points
        self.assertEqual(len(f_points), 4)
        f_scripts = self._submittedScripts(self.m_runner)
        self.assertEqual(len(f_scripts), len(f_points))
        for f_script in f_scripts:
            self.assertIn("#SBATCH --time=12:00:00", f_script)
            f_tail = f_script.strip().splitlines()[-1]
            self.assertIn(" allocation-group ", f_tail)
            self.assertIn(" continue ", f_tail)
            # Every arm's manifest, in run order
            f_positions = [
                f_tail.index(f_r["store"].layout.manifestPath) for f_r in f_runs
            ]
            self.assertEqual(f_positions, sorted(f_positions))
        # The probe ran epocpp --help
        self.assertIn([self.m_epocpp, "--help"], self.m_runner.m_calls)
        self.assertEqual(f_orch.exitCode, 0)

    def _writeRunOutputs(self, f_orch: RunOrchestrator, f_repeats: int) -> Any:
        """A submit callback doing what the worker does: every arm's run logs, decks and
        controller results for the points of the job."""
        from lsmiotool.lib.worker import AllocationController

        f_template = EpocppAdapter().readTemplate(
            EpocppAdapter.templatePath(_SHARE_ROOT)
        )

        def _onSubmit(f_jid: str, f_cwd: Optional[str]) -> None:
            for f_run in f_orch.groupRuns:
                f_ev, f_layout, f_plan = (
                    f_run["evidence"],
                    f_run["store"].layout,
                    f_run["plan"],
                )
                f_setup = f_plan.request.setup
                for f_idx, f_sp in enumerate(f_plan.scale_points):
                    if not os.path.isdir(f_layout.pointDir(f_sp, f_idx)):
                        continue
                    for f_combo in f_plan.combinations:
                        if f_ev.readControllerResult(f_sp, f_combo, f_ordinal=f_idx):
                            continue
                        f_name = f_layout.combinationName(f_combo)
                        f_work = f_layout.pointCombinationWorkDir(f_sp, f_name, f_idx)
                        os.makedirs(f_work, exist_ok=True)
                        EpocppAdapter().writeDeck(
                            EpocppAdapter().renderDeck(f_template, f_setup, "small"),
                            f_work,
                        )
                        f_logs = f_layout.pointLogsDir(f_sp, f_idx)
                        os.makedirs(f_logs, exist_ok=True)
                        for f_rep in range(1, f_repeats + 1):
                            f_text = f"Runtime = {f_sp.nodes + f_rep:.1f}\n"
                            if f_setup.endswith("-BW"):
                                f_text = (
                                    "BENCHMARK RESULTS: \n"
                                    f"write,{10.0 * f_rep:.2f},1.00,5.00,3.00,3,3\n"
                                    "read,20.00,2.00,9.00,3.00,3,3\n" + f_text
                                )
                            f_text += EpocppAdapter.dataBytesLine(0, 0, 0)
                            with open(
                                AllocationController.epocppLogPath(
                                    f_logs, f_name, f_rep
                                ),
                                "w",
                            ) as f_f:
                                f_f.write(f_text)
                        f_ev.recordControllerResult(
                            f_point=f_sp,
                            f_combination=f_combo,
                            f_payload={
                                "status": "success",
                                "exit_code": 0,
                                "stage": "execution",
                                "host": "node001",
                            },
                            f_ordinal=f_idx,
                        )

        return _onSubmit

    def testEveryArmPointIsArchivedWithItsReports(self) -> None:
        f_runner = _EpocppFakeRunner()
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_runner,
            f_poll_interval=0.01,
        )
        f_runner.m_on_submit_callback = self._writeRunOutputs(f_orch, 2)
        f_orch.execute(
            parseRunArguments(
                ["run", "epocpp", "backends", "bake", "posix", "--repeats", "2"],
                f_environ={},
            ),
            f_site=self.m_profile,
            f_worker_executable=self.m_worker_path,
        )
        self.assertEqual(f_orch.exitCode, 0)
        f_dest = os.path.join(self.m_viking_root_hdd, "lsmio-archive", "epocpp", "bake")
        self.assertEqual(
            sorted(os.listdir(f_dest)),
            [
                "epocpp-cost.csv",
                "outputs-epocpp-baseline",
                "outputs-epocpp-posix",
                "outputs-epocpp-posix-bw",
            ],
        )
        for f_arm in ("epocpp-baseline", "epocpp-posix", "epocpp-posix-bw"):
            f_arm_dir = os.path.join(f_dest, f"outputs-{f_arm}")
            self.assertEqual(
                sorted(f_e for f_e in os.listdir(f_arm_dir) if f_e.isdigit()),
                ["1", "2", "4", "8"],
            )
            (f_date,) = [
                f_d
                for f_d in os.listdir(os.path.join(f_arm_dir, "8"))
                if f_d != "input.deck"
            ]
            self.assertEqual(len(os.listdir(os.path.join(f_arm_dir, "8", f_date))), 12)
            self.assertTrue(os.path.isfile(os.path.join(f_arm_dir, "8", "input.deck")))
            self.assertTrue(
                os.path.isfile(os.path.join(f_arm_dir, "epocpp-report.csv"))
            )
            self.assertTrue(
                os.path.isfile(os.path.join(f_arm_dir, ".lsmiotool-run.json"))
            )
        with open(os.path.join(f_dest, "epocpp-cost.csv")) as f_f:
            f_cost = [f_l.strip().split(",") for f_l in f_f][1:]
        # Same fake Runtime for the baseline and posix: no I/O cost
        self.assertEqual(len(f_cost), 4 * 6)
        self.assertTrue(
            all(f_r[3] == "posix" and f_r[6] == "0.000000" for f_r in f_cost)
        )

    def testArchiveFromAnArmRunRoot(self) -> None:
        import io
        from unittest.mock import patch

        from lsmiotool.lib import main
        from lsmiotool.lib.cli import parseArchiveArguments

        f_runner = _EpocppFakeRunner()
        f_orch = RunOrchestrator(
            f_profile_resolver=self.m_registry,
            f_command_runner=f_runner,
            f_poll_interval=0.01,
        )
        f_runner.m_on_submit_callback = self._writeRunOutputs(f_orch, 1)
        f_orch.execute(
            parseRunArguments(
                [
                    "run",
                    "epocpp",
                    "backends",
                    "local",
                    "native",
                    "--repeats",
                    "1",
                    "--no-archive",
                ],
                f_environ={},
            ),
            f_site=self.m_profile,
            f_worker_executable=self.m_worker_path,
        )
        f_dest = os.path.join(
            self.m_viking_root_hdd, "lsmio-archive", "epocpp", "local"
        )
        self.assertFalse(os.path.exists(f_dest))
        f_arm_root = f_orch.groupRuns[1]["store"].layout.runRoot
        f_req = parseArchiveArguments(
            ["archive", "epocpp", "local", "--source", f_arm_root]
        )
        for f_round in (1, 2):
            f_out = io.StringIO()
            with patch("sys.stdout", f_out), patch("sys.stderr", io.StringIO()):
                self.assertEqual(main.ArchiveMain(f_request=f_req).run(), 0)
            if f_round == 2:
                # Every point is archived already
                self.assertIn("Nothing to archive", f_out.getvalue())
        self.assertEqual(
            sorted(os.listdir(f_dest)),
            [
                "epocpp-cost.csv",
                "outputs-epocpp-baseline",
                "outputs-epocpp-native",
                "outputs-epocpp-native-bw",
            ],
        )
        self.assertTrue(
            os.path.isfile(
                os.path.join(f_dest, "outputs-epocpp-native", "1", "input.deck")
            )
        )

    def testTemplateFromTheRuntimeLayout(self) -> None:
        # The template next to the runtime layout's LMP assets, not the install prefix's
        f_share = os.path.join(self.m_temp_dir, "elsewhere", "share")
        os.makedirs(os.path.join(f_share, "lmp-reaxff"))
        os.makedirs(os.path.join(f_share, "epocpp"))
        os.remove(
            EpocppAdapter.templatePath(os.path.join(self.m_temp_dir, "share", "lsmio"))
        )
        f_layout = RuntimeLayout(
            f_execution_mode=ExecutionMode.SOURCE,
            f_package_root=os.path.dirname(_SHARE_ROOT),
            f_profile_file=_PROFILE_PATH,
            f_asset_root=os.path.join(f_share, "lmp-reaxff"),
            f_worker_executable=self.m_worker_path,
            f_version_file=os.path.join(os.path.dirname(_SHARE_ROOT), "VERSION"),
        )

        def _execute() -> None:
            f_runner = _EpocppFakeRunner()
            f_orch = RunOrchestrator(
                f_profile_resolver=self.m_registry,
                f_command_runner=f_runner,
                f_poll_interval=0.01,
            )
            f_runner.m_on_submit_callback = self._groupOnSubmit(f_orch)
            f_orch.execute(
                parseRunArguments(
                    ["run", "epocpp", "backends", "local", "posix", "--no-archive"],
                    f_environ={},
                ),
                f_site=self.m_profile,
                f_runtime_layout=f_layout,
            )

        with self.assertRaisesRegex(PreflightError, "template"):
            _execute()
        shutil.copy(
            EpocppAdapter.templatePath(_SHARE_ROOT), os.path.join(f_share, "epocpp")
        )
        _execute()

    def testPreflightRefusals(self) -> None:
        # No epocpp in the site profile
        with self.assertRaisesRegex(PreflightError, "epocpp"):
            self._execute(
                ["run", "epocpp", "backends", "local", "--no-archive"],
                f_profile=self._profile(self.m_executables.toDict()),
            )
        # An epocpp without LSMIO (no --io-benchmark)
        with self.assertRaisesRegex(PreflightError, "io-benchmark"):
            self._execute(
                ["run", "epocpp", "backends", "local", "--no-archive"],
                f_runner=_EpocppFakeRunner("  -i,--input\n"),
            )
        # No plugin library: refused with a plugin arm, fine without
        os.remove(self.m_plugin)
        with self.assertRaisesRegex(PreflightError, "liblsmio_adios"):
            self._execute(["run", "epocpp", "backends", "local", "--no-archive"])
        self._execute(["run", "epocpp", "backends", "local", "posix", "--no-archive"])
        # No deck template
        os.remove(
            EpocppAdapter.templatePath(os.path.join(self.m_temp_dir, "share", "lsmio"))
        )
        with self.assertRaisesRegex(PreflightError, "template"):
            self._execute(
                ["run", "epocpp", "backends", "local", "posix", "--no-archive"]
            )


if __name__ == "__main__":
    unittest.main()
