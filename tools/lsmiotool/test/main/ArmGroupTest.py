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

"""Tests for arm groups: resolution, bmtool-layout export, and the shared-job tail."""

import io
import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from typing import Any, List

from lsmiotool.lib.arms import (
    ArmError,
    RunArm,
    resolveArmGroup,
    sanitizeBranch,
)
from lsmiotool.lib.export import ExportError, exportPoint
from lsmiotool.lib.run import RunOrchestrator, RunRequest
from lsmiotool.lib.worker import AllocationControllerError, AllocationGroupRunner


class ArmResolutionTest(unittest.TestCase):
    def _group(self, f_request: RunRequest, f_setup: str = "NATIVE-M") -> Any:
        return resolveArmGroup(f_request, f_setup, "/opt/usr", f_version_tag="br-1a2b3c4")

    def testStandardScaleIsSingleUnarchivedArm(self) -> None:
        f_group = self._group(RunRequest("lsmio", "small"))
        self.assertEqual(f_group.kind, "single")
        self.assertEqual(len(f_group.arms), 1)
        self.assertFalse(f_group.archive)

    def testIorNeverArchives(self) -> None:
        f_group = self._group(RunRequest("ior", "local", f_archive=True), "BASE")
        self.assertFalse(f_group.archive)
        self.assertIsNone(f_group.arms[0].arm_id)

    def testDefaultVariantsArchiveOnlyOnRequest(self) -> None:
        self.assertFalse(self._group(RunRequest("lsmio", "variants")).archive)
        f_group = self._group(RunRequest("lsmio", "variants", f_archive=True))
        self.assertTrue(f_group.archive)
        self.assertEqual(f_group.arms[0].arm_id, "native")

    def testPairedVariants(self) -> None:
        f_group = self._group(
            RunRequest("lsmio", "variants", f_variants=["default", "footer", "manoff"])
        )
        self.assertEqual(f_group.kind, "paired")
        self.assertTrue(f_group.archive)
        self.assertEqual(
            [(f_a.label, f_a.variant, f_a.arm_id, f_a.role) for f_a in f_group.arms],
            [
                ("baseline", None, None, "base"),
                ("footer", "footer", "native-footer", "run"),
                ("manoff", "manoff", "native-manoff", "run"),
            ],
        )
        self.assertFalse(
            self._group(
                RunRequest("lsmio", "variants", f_variants=["footer"], f_archive=False)
            ).archive
        )

    def testVersionedWithVariants(self) -> None:
        f_group = self._group(
            RunRequest("lsmio", "variants", f_variants=["autotune"], f_versioned=True)
        )
        f_ref, f_run = f_group.arms
        self.assertEqual(f_ref.role, "base")
        self.assertEqual(
            f_ref.executable_overrides, {"bm_native": "/opt/usr/bin/bm_native:main"}
        )
        self.assertEqual(f_run.variant, "autotune")
        self.assertEqual(f_run.arm_id, "native-version-br-1a2b3c4-autotune")
        self.assertEqual(f_run.executable_overrides, {})

    def testVersionedWithoutVariants(self) -> None:
        f_group = self._group(RunRequest("lsmio", "variants", f_versioned=True))
        self.assertEqual(
            [(f_a.variant, f_a.arm_id) for f_a in f_group.arms],
            [(None, None), (None, "native-version-br-1a2b3c4")],
        )

    def testBackends(self) -> None:
        f_group = self._group(
            RunRequest("lsmio", "small", f_mode="backends", f_backends=["adios2", "leveldb"])
        )
        self.assertEqual(f_group.kind, "backends")
        self.assertTrue(f_group.archive)
        self.assertEqual(
            [(f_a.setup, f_a.arm_id) for f_a in f_group.arms],
            [("ADIOS-M", "adios"), ("LEVELDB-M", "leveldb")],
        )
        with self.assertRaises(ArmError):
            self._group(
                RunRequest("lsmio", "small", f_mode="backends", f_backends=["bogus"])
            )

    def testSanitizeBranchMatchesBmtool(self) -> None:
        self.assertEqual(sanitizeBranch("tybulut/str-overhead"), "tybulut-str-overhead")
        self.assertEqual(sanitizeBranch("a.b c_d"), "a-b-c_d")


class _Layout:
    def __init__(self, f_root: str) -> None:
        self.m_root = f_root

    def combinationName(self, f_combo: Any) -> str:
        return f"c{f_combo.stripe_count}_b{f_combo.block_size}"

    def pointRankLogPath(self, f_sp: Any, f_rank: int, f_combo: str, f_ordinal: int = 0) -> str:
        return os.path.join(self.m_root, "logs", f_combo, f"rank_{f_rank}.log")


class _Evidence:
    def __init__(
        self,
        f_layout: _Layout,
        f_with_records: bool = True,
        f_payload: Any = None,
    ) -> None:
        self.m_layout = f_layout
        self.m_with = f_with_records
        # Older rank results: a Slurm node index and no host
        self.m_payload = f_payload or (lambda f_r: {"node_rank": str(f_r), "local_rank": 0})

    def readRankResult(self, f_sp: Any, f_rank: int, f_combo: Any, f_ordinal: int = 0) -> Any:
        if not self.m_with:
            return None
        return SimpleNamespace(
            created_at_utc="2026-10-10T03:33:12Z",
            payload=self.m_payload(f_rank),
        )


class ExportPointTest(unittest.TestCase):
    def setUp(self) -> None:
        self.m_tmp = tempfile.mkdtemp()
        self.m_layout = _Layout(os.path.join(self.m_tmp, "run"))
        self.m_combos = [
            SimpleNamespace(stripe_count=16, block_size="8M"),
            SimpleNamespace(stripe_count=4, block_size="64K"),
        ]
        self.m_sp = SimpleNamespace(tasks=2, nodes=2)
        for f_c in self.m_combos:
            for f_r in range(2):
                f_p = self.m_layout.pointRankLogPath(
                    self.m_sp, f_r, self.m_layout.combinationName(f_c)
                )
                os.makedirs(os.path.dirname(f_p), exist_ok=True)
                with open(f_p, "w") as f_f:
                    f_f.write(f"write,{f_r + 1},1,1,1,1,10\n")

    def tearDown(self) -> None:
        shutil.rmtree(self.m_tmp, ignore_errors=True)

    def testWritesBmtoolLayoutAndReplacesNodeDir(self) -> None:
        f_node_dir = os.path.join(self.m_tmp, "archive", "outputs-native-footer:run", "2")
        os.makedirs(os.path.join(f_node_dir, "stale"))
        f_n = exportPoint(
            self.m_layout,
            _Evidence(self.m_layout),
            self.m_sp,
            0,
            self.m_combos,
            "native-footer",
            f_node_dir,
        )
        self.assertEqual(f_n, 4)
        self.assertEqual(os.listdir(f_node_dir), ["2026-10-10"])
        self.assertEqual(
            sorted(os.listdir(os.path.join(f_node_dir, "2026-10-10"))),
            sorted(
                f"out-native-footer-{f_s}-{f_b}-2026-10-10-node{f_r}-0.txt"
                for f_s, f_b in ((16, "8M"), (4, "64K"))
                for f_r in range(2)
            ),
        )
        with open(
            os.path.join(f_node_dir, "2026-10-10", "out-native-footer-16-8M-2026-10-10-node1-0.txt")
        ) as f_f:
            self.assertEqual(f_f.read(), "write,2,1,1,1,1,10\n")
        self.assertFalse(os.path.exists(f_node_dir + ".partial"))

    def _exportNames(self, f_payload: Any) -> List[str]:
        f_node_dir = os.path.join(self.m_tmp, "archive", "outputs-native", "2")
        exportPoint(
            self.m_layout,
            _Evidence(self.m_layout, f_payload=f_payload),
            self.m_sp,
            0,
            self.m_combos[:1],
            "native",
            f_node_dir,
        )
        return sorted(os.listdir(os.path.join(f_node_dir, "2026-10-10")))

    def testNamesFilesByRecordedHost(self) -> None:
        """Files carry the node's hostname, as bmtool's ${SLURMD_NODENAME}-${SLURM_LOCALID}."""
        self.assertEqual(
            self._exportNames(
                lambda f_r: {"node_rank": str(f_r), "local_rank": 0, "host": f"node{97 + f_r:03d}"}
            ),
            [
                "out-native-16-8M-2026-10-10-node097-0.txt",
                "out-native-16-8M-2026-10-10-node098-0.txt",
            ],
        )

    def testPbsNamesUseHostnameAndGlobalRank(self) -> None:
        """Without a local rank (PBS) the suffix is the global rank, bmtool's ALPS_APP_PE,
        and a hostname node_rank is used as is."""
        self.assertEqual(
            self._exportNames(lambda f_r: {"node_rank": "nid001234", "local_rank": None}),
            [
                "out-native-16-8M-2026-10-10-nid001234-0.txt",
                "out-native-16-8M-2026-10-10-nid001234-1.txt",
            ],
        )

    def testMissingLogLeavesTargetUntouched(self) -> None:
        os.unlink(self.m_layout.pointRankLogPath(self.m_sp, 1, "c4_b64K"))
        f_node_dir = os.path.join(self.m_tmp, "archive", "outputs-native", "2")
        os.makedirs(os.path.join(f_node_dir, "keep"))
        with self.assertRaises(ExportError):
            exportPoint(
                self.m_layout,
                _Evidence(self.m_layout),
                self.m_sp,
                0,
                self.m_combos,
                "native",
                f_node_dir,
            )
        self.assertEqual(os.listdir(f_node_dir), ["keep"])
        self.assertFalse(os.path.exists(f_node_dir + ".partial"))


class AllocationGroupRunnerTest(unittest.TestCase):
    def _run(self, f_policy: str, f_rcs: List[int]) -> List[str]:
        f_calls: List[str] = []

        def run_allocation(f_manifest: str, f_point: str) -> int:
            f_calls.append(f_manifest)
            self.assertEqual(f_point, "00-tasks-8")
            return f_rcs[len(f_calls) - 1]

        f_rc = AllocationGroupRunner.run(
            "00-tasks-8",
            f_policy,
            [f"m{f_i}" for f_i in range(len(f_rcs))],
            run_allocation,
            f_stderr=io.StringIO(),
        )
        self.assertEqual(f_rc, 0)
        return f_calls

    def testContinueRunsEveryArm(self) -> None:
        self.assertEqual(
            self._run(AllocationGroupRunner.POLICY_CONTINUE, [1, 0, 2]), ["m0", "m1", "m2"]
        )

    def testStopAfterFailedBaseline(self) -> None:
        self.assertEqual(
            self._run(AllocationGroupRunner.POLICY_STOP_AFTER_FIRST_FAILURE, [1, 0, 0]),
            ["m0"],
        )
        # A failed variant does not stop the others
        self.assertEqual(
            self._run(AllocationGroupRunner.POLICY_STOP_AFTER_FIRST_FAILURE, [0, 3, 0]),
            ["m0", "m1", "m2"],
        )

    def testRejectsUnknownPolicy(self) -> None:
        with self.assertRaises(AllocationControllerError):
            AllocationGroupRunner.run("p", "bogus", ["m"], lambda f_m, f_p: 0)


class GroupScriptTest(unittest.TestCase):
    def testReplacesExecTail(self) -> None:
        f_script = (
            "#!/bin/bash\n#SBATCH --nodes=8\nset -euo pipefail\nmodule purge\n"
            "export ADIOS2_PLUGIN_PATH=/opt/usr/lib\n"
            "exec /w/lsmiotool-worker allocation /r/a/manifest.json 00-tasks-8\n"
        )
        f_out = RunOrchestrator._groupScript(
            f_script,
            "/w/lsmiotool-worker",
            "00-tasks-8",
            "continue",
            ["/r/a/manifest.json", "/r/b c/manifest.json"],
        )
        f_lines = f_out.strip().splitlines()
        self.assertEqual(f_lines[:-1], f_script.strip().splitlines()[:-1])
        self.assertEqual(
            f_lines[-1],
            "exec /w/lsmiotool-worker allocation-group 00-tasks-8 continue "
            "/r/a/manifest.json '/r/b c/manifest.json'",
        )


if __name__ == "__main__":
    unittest.main()
