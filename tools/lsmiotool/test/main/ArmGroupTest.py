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
    DEFAULT_LSMIO_BACKENDS,
    ArmError,
    RunArm,
    iorArmToken,
    isIorArmId,
    resolveArmGroup,
    sanitizeBranch,
)
from lsmiotool.lib.export import (
    IOR_UNKNOWN_HOST,
    ExportError,
    exportIorPoint,
    exportPoint,
    generateIorReports,
)
from lsmiotool.lib.run import RunOrchestrator, RunRequest
from lsmiotool.lib.worker import AllocationControllerError, AllocationGroupRunner


class ArmResolutionTest(unittest.TestCase):
    def _group(self, f_request: RunRequest, f_setup: str = "NATIVE") -> Any:
        return resolveArmGroup(
            f_request, f_setup, "/opt/usr", f_version_tag="br-1a2b3c4"
        )

    def testStandardScaleIsSingleUnarchivedArm(self) -> None:
        f_group = self._group(RunRequest("lsmio", "small"))
        self.assertEqual(f_group.kind, "single")
        self.assertEqual(len(f_group.arms), 1)
        self.assertFalse(f_group.archive)

    def testRemovedSetupNamesAreRejected(self) -> None:
        for f_setup in ("NATIVE-M", "rocksdb-m", "ENV"):
            with self.subTest(setup=f_setup):
                with self.assertRaises(ArmError):
                    self._group(RunRequest("lsmio", "small"), f_setup)

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
            RunRequest(
                "lsmio", "variants", f_variants=["default", "no-footer", "no-manoff"]
            )
        )
        self.assertEqual(f_group.kind, "paired")
        self.assertTrue(f_group.archive)
        self.assertEqual(
            [(f_a.label, f_a.variant, f_a.arm_id, f_a.role) for f_a in f_group.arms],
            [
                ("baseline", None, None, "base"),
                ("no-footer", "no-footer", "native-no-footer", "run"),
                ("no-manoff", "no-manoff", "native-no-manoff", "run"),
            ],
        )
        self.assertFalse(
            self._group(
                RunRequest(
                    "lsmio", "variants", f_variants=["no-footer"], f_archive=False
                )
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
            RunRequest(
                "lsmio", "small", f_mode="backends", f_backends=["adios2", "leveldb"]
            )
        )
        self.assertEqual(f_group.kind, "backends")
        self.assertTrue(f_group.archive)
        self.assertEqual(
            [(f_a.setup, f_a.arm_id) for f_a in f_group.arms],
            [("ADIOS", "adios"), ("LEVELDB", "leveldb")],
        )
        with self.assertRaises(ArmError):
            self._group(
                RunRequest("lsmio", "small", f_mode="backends", f_backends=["bogus"])
            )

    def testSyncBackends(self) -> None:
        """Each backend has a -sync arm (--lsmio-always-flush); they run only when listed,
        and their setups are refused as a run's own setup."""
        f_backends = [
            "adios2",
            "adios2-sync",
            "native-sync",
            "plugin-sync",
            "rocksdb-sync",
            "leveldb-sync",
        ]
        f_group = self._group(
            RunRequest("lsmio", "small", f_mode="backends", f_backends=f_backends)
        )
        self.assertEqual(
            [(f_a.label, f_a.setup, f_a.arm_id) for f_a in f_group.arms],
            [
                ("adios2", "ADIOS", "adios"),
                ("adios2-sync", "ADIOS-SYNC", "adios-sync"),
                ("native-sync", "NATIVE-SYNC", "native-sync"),
                ("plugin-sync", "PLUGIN-SYNC", "plugin-sync"),
                ("rocksdb-sync", "ROCKSDB-SYNC", "rocksdb-sync"),
                ("leveldb-sync", "LEVELDB-SYNC", "leveldb-sync"),
            ],
        )
        self.assertEqual(
            [
                f_a.arm_id
                for f_a in self._group(
                    RunRequest(
                        "lsmio", "small", f_mode="backends", f_backends=["adios-sync"]
                    )
                ).arms
            ],
            ["adios-sync"],
        )
        self.assertEqual(
            DEFAULT_LSMIO_BACKENDS, ("adios2", "native", "plugin", "rocksdb")
        )
        for f_setup in ("ADIOS-SYNC", "NATIVE-SYNC"):
            with self.assertRaises(ArmError):
                self._group(
                    RunRequest("lsmio", "variants", f_variants=["btree"]), f_setup
                )
            with self.assertRaises(ArmError):
                self._group(RunRequest("lsmio", "small"), f_setup)

    def testIorSetupsAreBackendsArms(self) -> None:
        """An ior scaling run: one archived arm per IOR setup, outputs-ior[-<setup>]."""
        f_group = self._group(RunRequest("ior", "small", f_mode="backends"), "BASE")
        self.assertEqual(f_group.kind, "backends")
        self.assertTrue(f_group.archive)
        self.assertEqual(
            [(f_a.label, f_a.setup, f_a.arm_id) for f_a in f_group.arms],
            [
                ("base", "BASE", "ior"),
                ("collective", "COLLECTIVE", "ior-collective"),
                ("hdf5", "HDF5", "ior-hdf5"),
                ("hdf5-collective", "HDF5-C", "ior-hdf5-collective"),
            ],
        )
        self.assertFalse(
            self._group(
                RunRequest("ior", "small", f_mode="backends", f_archive=False), "BASE"
            ).archive
        )
        for f_backends in (["bogus"], ["hdf5-c", "hdf5-collective"], ["native"]):
            with self.subTest(backends=f_backends):
                with self.assertRaises(ArmError):
                    self._group(
                        RunRequest(
                            "ior", "small", f_mode="backends", f_backends=f_backends
                        ),
                        "BASE",
                    )

    def testIorArmHelpers(self) -> None:
        self.assertEqual(iorArmToken("hdf5-c"), "hdf5-collective")
        self.assertEqual(iorArmToken("BASE"), "base")
        with self.assertRaises(ArmError):
            iorArmToken("NATIVE")
        for f_id in ("ior", "ior-collective", "ior-hdf5-collective"):
            self.assertTrue(isIorArmId(f_id))
        for f_id in (None, "native", "adios", "iorx", "native-ior"):
            self.assertFalse(isIorArmId(f_id))

    def testSanitizeBranchMatchesBmtool(self) -> None:
        self.assertEqual(sanitizeBranch("tybulut/str-overhead"), "tybulut-str-overhead")
        self.assertEqual(sanitizeBranch("a.b c_d"), "a-b-c_d")


class _Layout:
    def __init__(self, f_root: str) -> None:
        self.m_root = f_root

    def combinationName(self, f_combo: Any) -> str:
        return f"c{f_combo.stripe_count}_b{f_combo.block_size}"

    def pointRankLogPath(
        self, f_sp: Any, f_rank: int, f_combo: str, f_ordinal: int = 0
    ) -> str:
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
        self.m_payload = f_payload or (
            lambda f_r: {"node_rank": str(f_r), "local_rank": 0}
        )

    def readRankResult(
        self, f_sp: Any, f_rank: int, f_combo: Any, f_ordinal: int = 0
    ) -> Any:
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
        f_node_dir = os.path.join(
            self.m_tmp, "archive", "outputs-native-no-footer:run", "2"
        )
        os.makedirs(os.path.join(f_node_dir, "stale"))
        f_n = exportPoint(
            self.m_layout,
            _Evidence(self.m_layout),
            self.m_sp,
            0,
            self.m_combos,
            "native-no-footer",
            f_node_dir,
        )
        self.assertEqual(f_n, 4)
        self.assertEqual(os.listdir(f_node_dir), ["2026-10-10"])
        self.assertEqual(
            sorted(os.listdir(os.path.join(f_node_dir, "2026-10-10"))),
            sorted(
                f"out-native-no-footer-{f_s}-{f_b}-2026-10-10-node{f_r}-0.txt"
                for f_s, f_b in ((16, "8M"), (4, "64K"))
                for f_r in range(2)
            ),
        )
        with open(
            os.path.join(
                f_node_dir,
                "2026-10-10",
                "out-native-no-footer-16-8M-2026-10-10-node1-0.txt",
            )
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
                lambda f_r: {
                    "node_rank": str(f_r),
                    "local_rank": 0,
                    "host": f"node{97 + f_r:03d}",
                }
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
            self._exportNames(
                lambda f_r: {"node_rank": "nid001234", "local_rank": None}
            ),
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


IOR_SUMMARY = (
    "Summary of all tests:\n"
    "Operation   Max(MiB)   Min(MiB)  Mean(MiB)     StdDev   Max(OPs)\n"
    "write        1650.38    1434.73    1573.37      62.47    1650.38    1434.73    1573.37"
    "      62.47    1.30379         NA            NA     0      2   1   10   0     0"
    "        1         0    0   1024  1048576  1048576    2048.0 POSIX      0\n"
    "read        12824.95    8741.74   10846.96    1061.25   12824.95    8741.74   10846.96"
    "    1061.25    0.19070         NA            NA     0      2   1   10   0     0"
    "        1         0    0   1024  1048576  1048576    2048.0 POSIX      0\n"
)


class _IorLayout(_Layout):
    def pointLogsDir(self, f_sp: Any, f_ordinal: int = 0) -> str:
        return os.path.join(self.m_root, "logs")


class _IorEvidence:
    def __init__(self, f_payload: Any) -> None:
        self.m_payload = f_payload

    def readControllerResult(self, f_sp: Any, f_combo: Any, f_ordinal: int = 0) -> Any:
        return SimpleNamespace(
            created_at_utc="2026-10-14T21:51:53Z", payload=dict(self.m_payload)
        )


class ExportIorPointTest(unittest.TestCase):
    """IOR points: one shared output per combination, in bmtool's IOR layout."""

    def setUp(self) -> None:
        self.m_tmp = tempfile.mkdtemp()
        self.m_layout = _IorLayout(os.path.join(self.m_tmp, "run"))
        self.m_combos = [
            SimpleNamespace(stripe_count=4, block_size="1M"),
            SimpleNamespace(stripe_count=16, block_size="64K"),
        ]
        self.m_sp = SimpleNamespace(tasks=2, nodes=2)
        os.makedirs(self.m_layout.pointLogsDir(self.m_sp))
        for f_c in self.m_combos:
            with open(
                os.path.join(
                    self.m_layout.pointLogsDir(self.m_sp),
                    f"ior_{self.m_layout.combinationName(f_c)}.stdout",
                ),
                "w",
            ) as f_f:
                f_f.write(IOR_SUMMARY)

    def tearDown(self) -> None:
        shutil.rmtree(self.m_tmp, ignore_errors=True)

    def _export(self, f_payload: Any, f_infix: str = "hdf5-c") -> str:
        f_arm_dir = os.path.join(self.m_tmp, "archive", "outputs-ior-hdf5-collective")
        f_n = exportIorPoint(
            self.m_layout,
            _IorEvidence(f_payload),
            self.m_sp,
            0,
            self.m_combos,
            f_infix,
            os.path.join(f_arm_dir, "2"),
        )
        self.assertEqual(f_n, 2)
        return f_arm_dir

    def testWritesBmtoolIorLayoutAndReport(self) -> None:
        f_arm_dir = self._export({"status": "success", "host": "node097"})
        self.assertEqual(
            sorted(os.listdir(os.path.join(f_arm_dir, "2", "2026-10-14"))),
            [
                "out-hdf5-c-16-64K-2026-10-14-node097-0.txt",
                "out-hdf5-c-4-1M-2026-10-14-node097-0.txt",
            ],
        )
        self.assertTrue(generateIorReports(f_arm_dir))
        with open(os.path.join(f_arm_dir, "ior-report.csv")) as f_f:
            f_rows = sorted(f_line.split(",")[:5] for f_line in f_f.read().split())
        # ior-parse.sh: node count, stripes and block size from the path, then the line
        self.assertEqual(
            f_rows,
            [
                ["2", "16", "64K", "read", "12824.95"],
                ["2", "16", "64K", "write", "1650.38"],
                ["2", "4", "1M", "read", "12824.95"],
                ["2", "4", "1M", "write", "1650.38"],
            ],
        )

    def testHostlessResultsKeepTheReportParseable(self) -> None:
        """A controller result written before 'host' was recorded still gives
        ior-parse.sh's node... host token."""
        f_arm_dir = self._export({"status": "success"}, "base")
        self.assertIn(
            f"out-base-4-1M-2026-10-14-{IOR_UNKNOWN_HOST}-0.txt",
            os.listdir(os.path.join(f_arm_dir, "2", "2026-10-14")),
        )
        self.assertTrue(generateIorReports(f_arm_dir))
        with open(os.path.join(f_arm_dir, "ior-report.csv")) as f_f:
            self.assertTrue(all(f_l.startswith("2,") for f_l in f_f.read().split()))

    def testUnparseableHostIsReplaced(self) -> None:
        """A host ior-parse.sh cannot strip (ARCHER2's nid + 6 digits) would leave the date
        and host in ior-report.csv's block size column: the file gets the fallback host."""
        from unittest.mock import patch

        from lsmiotool.lib import export

        export._IOR_WARNED_HOSTS.discard("nid001234")
        with patch("lsmiotool.lib.log.Console.warning") as f_warn:
            f_arm_dir = self._export({"status": "success", "host": "nid001234"}, "base")
        # Once per host, not once per output
        self.assertEqual(f_warn.call_count, 1)
        self.assertIn(
            f"out-base-4-1M-2026-10-14-{IOR_UNKNOWN_HOST}-0.txt",
            os.listdir(os.path.join(f_arm_dir, "2", "2026-10-14")),
        )
        self.assertTrue(generateIorReports(f_arm_dir))
        with open(os.path.join(f_arm_dir, "ior-report.csv")) as f_f:
            self.assertEqual(
                sorted({tuple(f_l.split(",")[:3]) for f_l in f_f.read().split()}),
                [("2", "16", "64K"), ("2", "4", "1M")],
            )
        # A PBS nid with five digits is kept, as ior-parse.sh strips it
        f_arm_dir = self._export({"status": "success", "host": "nid00123"}, "fsync")
        self.assertIn(
            "out-fsync-4-1M-2026-10-14-nid00123-0.txt",
            os.listdir(os.path.join(f_arm_dir, "2", "2026-10-14")),
        )

    def testMissingOutputLeavesTargetUntouched(self) -> None:
        os.unlink(
            os.path.join(self.m_layout.pointLogsDir(self.m_sp), "ior_c16_b64K.stdout")
        )
        f_node_dir = os.path.join(self.m_tmp, "archive", "outputs-ior", "2")
        os.makedirs(os.path.join(f_node_dir, "keep"))
        with self.assertRaises(ExportError):
            exportIorPoint(
                self.m_layout,
                _IorEvidence({"status": "success"}),
                self.m_sp,
                0,
                self.m_combos,
                "base",
                f_node_dir,
            )
        self.assertEqual(os.listdir(f_node_dir), ["keep"])
        self.assertFalse(os.path.exists(f_node_dir + ".partial"))

    def testIorPointSucceedsWithoutRankResults(self) -> None:
        """A shared IOR launch records no rank results: its controller results decide."""
        f_ctx = {
            "arm": RunArm("base", "BASE", None, "ior", None),
            "plan": SimpleNamespace(
                scale_points=[self.m_sp], combinations=self.m_combos
            ),
            "evidence": SimpleNamespace(
                readControllerResult=lambda *f_a, **f_k: SimpleNamespace(
                    payload={"status": "success"}
                ),
                readRankResult=lambda *f_a, **f_k: None,
            ),
        }
        self.assertTrue(RunOrchestrator._armPointSucceeded(f_ctx, 0))
        f_ctx["arm"] = RunArm("native", "NATIVE", None, "native", None)
        self.assertFalse(RunOrchestrator._armPointSucceeded(f_ctx, 0))


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
            self._run(AllocationGroupRunner.POLICY_CONTINUE, [1, 0, 2]),
            ["m0", "m1", "m2"],
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
