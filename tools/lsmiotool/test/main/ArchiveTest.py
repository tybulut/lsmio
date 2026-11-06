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

"""Unit tests for ArchiveRequest, ArchiveCliParser, ArchiveEngine, and ArchiveMain."""

import io
import os
import shutil
import tempfile
import unittest
from typing import Dict, List, Optional, Tuple
from unittest.mock import patch

from lsmiotool.lib.archive import (
    ArchiveEngine,
    ArchiveError,
    ArchiveRequest,
)
from lsmiotool.lib.cli import (
    ArchiveCliParseError,
    ArchiveCliParser,
    parseArchiveArguments,
)
from lsmiotool.lib.main import ArchiveMain
from lsmiotool.lib.variants import UnknownSetupError, UnknownVariantError


class ArchiveTest(unittest.TestCase):
    """Unit test suite asserting move-on-archive semantics, parser contracts, and collision handling."""

    def testArchiveRequestImmutability(self) -> None:
        """Tasks 4.5.1: Asserts ArchiveRequest fields, properties, immutability, and validation."""
        req = ArchiveRequest(
            f_target="lsmio",
            f_scale="variants",
            f_variant="no-footer",
            f_dest="/tmp/archive",
        )

        self.assertEqual(req.target, "lsmio")
        self.assertEqual(req.scale, "variants")
        self.assertEqual(req.variant, "no-footer")
        self.assertEqual(req.dest, "/tmp/archive")

        # Immutability enforcement
        with self.assertRaises(AttributeError):
            req.target = "ior"  # type: ignore

        with self.assertRaises(AttributeError):
            req.m_target = "ior"  # type: ignore

        with self.assertRaises(AttributeError):
            req.variant = "btree"  # type: ignore

        with self.assertRaises(AttributeError):
            req.dest = "/other"  # type: ignore

        with self.assertRaises(AttributeError):
            del req.target

        # Dictionary serialization
        d = req.toDict()
        self.assertEqual(
            d,
            {
                "target": "lsmio",
                "scale": "variants",
                "variant": "no-footer",
                "dest": "/tmp/archive",
            },
        )

        # Repr and value equality
        self.assertIn("ArchiveRequest", repr(req))
        req2 = ArchiveRequest(
            f_target="lsmio",
            f_scale="variants",
            f_variant="no-footer",
            f_dest="/tmp/archive",
        )
        self.assertEqual(req, req2)
        self.assertEqual(hash(req), hash(req2))

        # Rejection of invalid inputs
        with self.assertRaises(ArchiveError):
            ArchiveRequest("", "baseline")

        with self.assertRaises(ArchiveError):
            ArchiveRequest("lsmio", "")

        with self.assertRaises(ArchiveError):
            ArchiveRequest("lsmio", "baseline", f_variant="")

        with self.assertRaises(ArchiveError):
            ArchiveRequest("lsmio", "baseline", f_dest="")

        with self.assertRaises(ArchiveError):
            ArchiveRequest(123, "baseline")  # type: ignore

        with self.assertRaises(ArchiveError):
            ArchiveRequest("lsmio", None)  # type: ignore

    def testArchiveCliParserContracts(self) -> None:
        """Tasks 4.5.2: Asserts valid argument sequences parsed into canonical ArchiveRequest."""
        # 1. Leading 'archive' command with all arguments
        req1 = parseArchiveArguments(
            ["archive", "lsmio", "baseline", "no-footer", "--dest", "/tmp/archive"]
        )
        self.assertEqual(req1.target, "lsmio")
        self.assertEqual(req1.scale, "variants")
        self.assertEqual(req1.variant, "no-footer")
        self.assertEqual(req1.dest, "/tmp/archive")

        # 2. Without leading 'archive'
        req2 = parseArchiveArguments(["lsmio", "baseline", "mmap-btree"])
        self.assertEqual(req2.target, "lsmio")
        self.assertEqual(req2.scale, "variants")
        self.assertEqual(req2.variant, "mmap-btree")
        self.assertIsNone(req2.dest)

        # 3. Baseline scale with base/default normalizes to None
        req3 = parseArchiveArguments(["lsmio", "baseline", "default"])
        self.assertIsNone(req3.variant)

        req4 = parseArchiveArguments(["lsmio", "baseline", "base"])
        self.assertIsNone(req4.variant)

        # 4. Baseline scale without variant
        req5 = parseArchiveArguments(["lsmio", "baseline"])
        self.assertEqual(req5.scale, "variants")
        self.assertIsNone(req5.variant)

        # 5. Legacy scales without variant
        for sc in ("local", "bake", "small", "large"):
            req_sc = parseArchiveArguments(["lsmio", sc])
            self.assertEqual(req_sc.scale, sc)
            self.assertIsNone(req_sc.variant)

        # 6. Legacy scale with --dest
        req6 = parseArchiveArguments(["lsmio", "small", "--dest", "/data/arc"])
        self.assertEqual(req6.scale, "small")
        self.assertEqual(req6.dest, "/data/arc")

        # 7. Case insensitivity
        req7 = parseArchiveArguments(["LSMIO", "BASELINE", "MMAP-BTREE"])
        self.assertEqual(req7.target, "lsmio")
        self.assertEqual(req7.scale, "variants")
        self.assertEqual(req7.variant, "mmap-btree")

    def testArchiveCliParserRejections(self) -> None:
        """Tasks 4.5.3: Asserts invalid CLI sequences, unsupported benchmarks, and legacy positional rejection."""
        # Input type validation
        with self.assertRaises(ArchiveCliParseError):
            parseArchiveArguments(None)  # type: ignore

        with self.assertRaises(ArchiveCliParseError):
            parseArchiveArguments("lsmio baseline")  # type: ignore

        with self.assertRaises(ArchiveCliParseError):
            parseArchiveArguments(["lsmio", 123])  # type: ignore

        # Missing positionals
        with self.assertRaises(ArchiveCliParseError):
            parseArchiveArguments([])

        with self.assertRaises(ArchiveCliParseError):
            parseArchiveArguments(["archive"])

        with self.assertRaises(ArchiveCliParseError):
            parseArchiveArguments(["lsmio"])

        # Benchmark validation: lsmio, and ior scaling runs (not 'ior variants')
        with self.assertRaises(ArchiveCliParseError):
            parseArchiveArguments(["ior", "baseline"])

        with self.assertRaises(ArchiveCliParseError):
            parseArchiveArguments(["lmp", "local"])

        with self.assertRaises(ArchiveCliParseError):
            parseArchiveArguments(["unknown", "baseline"])

        # Scale validation
        with self.assertRaises(ArchiveCliParseError):
            parseArchiveArguments(["lsmio", "invalid_scale"])

        # Legacy scales reject extra positional arguments
        for sc in ("local", "bake", "small", "large"):
            with self.assertRaises(ArchiveCliParseError) as ctx:
                parseArchiveArguments(["lsmio", sc, "no-footer"])
            self.assertIn("Unexpected extra positional argument", str(ctx.exception))

        # Baseline scale with unknown variant fails fast
        with self.assertRaises(UnknownVariantError) as ctx_u:
            parseArchiveArguments(["lsmio", "baseline", "nonexistent_variant"])
        self.assertIn("Invalid variant", str(ctx_u.exception))

        # Retired variants and two-segment '<backend>-m-' prefixes are rejected too
        for f_variant in ("footer", "footer-btree", "native-m-btree"):
            with self.assertRaises(UnknownVariantError):
                parseArchiveArguments(["lsmio", "baseline", f_variant])

        # Baseline scale rejects extra positional arguments after variant
        with self.assertRaises(ArchiveCliParseError):
            parseArchiveArguments(["lsmio", "baseline", "no-footer", "unexpected"])

        # Prohibit --dest=value syntax
        with self.assertRaises(ArchiveCliParseError) as ctx_eq:
            parseArchiveArguments(["lsmio", "baseline", "--dest=/tmp/archive"])
        self.assertIn("Prohibit '--dest=value' syntax", str(ctx_eq.exception))

        # Duplicate --dest
        with self.assertRaises(ArchiveCliParseError):
            parseArchiveArguments(
                ["lsmio", "baseline", "--dest", "/p1", "--dest", "/p2"]
            )

        # Missing value after --dest
        with self.assertRaises(ArchiveCliParseError):
            parseArchiveArguments(["lsmio", "baseline", "--dest"])

        with self.assertRaises(ArchiveCliParseError):
            parseArchiveArguments(["lsmio", "baseline", "--dest", "--other"])

        # Unknown option
        with self.assertRaises(ArchiveCliParseError):
            parseArchiveArguments(["lsmio", "baseline", "--unknown"])

        # Options placed before positionals
        with self.assertRaises(ArchiveCliParseError):
            parseArchiveArguments(["--dest", "/tmp", "lsmio", "baseline"])

        with self.assertRaises(ArchiveCliParseError):
            parseArchiveArguments(["lsmio", "--dest", "/tmp", "baseline"])

    def testArchiveEngineArmIdResolution(self) -> None:
        """Tasks 4.5.4: Asserts mechanical ARM_ID derivation per INV-ARCH-8."""
        # NATIVE with variant
        self.assertEqual(
            ArchiveEngine.resolveArmId("NATIVE", "mmap-btree"),
            "native-mmap-btree",
        )
        self.assertEqual(
            ArchiveEngine.resolveArmId("NATIVE", "no-footer"),
            "native-no-footer",
        )
        self.assertEqual(
            ArchiveEngine.resolveArmId("NATIVE", None),
            "native",
        )
        self.assertEqual(
            ArchiveEngine.resolveArmId("NATIVE", "default"),
            "native",
        )

        # Only LSMIO setups name an arm: 'lsmio' and the removed '-M' names are rejected,
        # so an old run root is never archived under a 'native-m' arm
        for f_setup in ("lsmio", "NATIVE-M", "native-m", "ROCKSDB-M"):
            with self.subTest(setup=f_setup):
                with self.assertRaises(UnknownSetupError):
                    ArchiveEngine.resolveArmId(f_setup, "mmap-btree")
                with self.assertRaises(UnknownSetupError):
                    ArchiveEngine.resolveArmId(f_setup, None)

        # Composite setups
        self.assertEqual(
            ArchiveEngine.resolveArmId("ROCKSDB", "wbuf-512m"),
            "rocksdb-wbuf-512m",
        )
        self.assertEqual(
            ArchiveEngine.resolveArmId("MANAGER", "btree"),
            "manager-btree",
        )

        # Default resolution
        self.assertEqual(ArchiveEngine.resolveArmId(), "native")

    def testArchiveEngineCollisionAvoidance(self) -> None:
        """Tasks 4.5.5: Asserts auto-increment suffix collision resolution per INV-ARCH-7."""
        with tempfile.TemporaryDirectory() as temp_dir:
            arm_id = "native-mmap-btree"

            # Case 1: Target does not exist
            t0 = ArchiveEngine.resolveTargetDirectory(temp_dir, arm_id)
            self.assertEqual(t0, os.path.join(temp_dir, "outputs-native-mmap-btree"))

            # Case 2: Base target exists -> suffix -1
            os.makedirs(t0)
            t1 = ArchiveEngine.resolveTargetDirectory(temp_dir, arm_id)
            self.assertEqual(
                t1, os.path.join(temp_dir, "outputs-native-mmap-btree-1")
            )

            # Case 3: -1 also exists -> suffix -2
            os.makedirs(t1)
            t2 = ArchiveEngine.resolveTargetDirectory(temp_dir, arm_id)
            self.assertEqual(
                t2, os.path.join(temp_dir, "outputs-native-mmap-btree-2")
            )

            # Case 4: -2 also exists -> suffix -3
            os.makedirs(t2)
            t3 = ArchiveEngine.resolveTargetDirectory(temp_dir, arm_id)
            self.assertEqual(
                t3, os.path.join(temp_dir, "outputs-native-mmap-btree-3")
            )

    def testArchiveEngineAtomicMoveAndRecreation(self) -> None:
        """Tasks 4.5.6: Asserts atomic move-on-archive and clean active directory recreation."""
        with tempfile.TemporaryDirectory() as temp_root:
            source_dir = os.path.join(temp_root, "outputs")
            dest_root = os.path.join(temp_root, "lsmio-archive")
            os.makedirs(source_dir)

            # Create test payload inside source directory
            test_file = os.path.join(source_dir, "rank-0.db")
            with open(test_file, "w") as f:
                f.write("benchmark payload data")

            # First archive run
            target_1 = ArchiveEngine.executeArchive(
                f_source_dir=source_dir,
                f_dest_root=dest_root,
                f_arm_id="native-no-footer",
            )
            expected_target_1 = os.path.join(dest_root, "outputs-native-no-footer")
            self.assertEqual(target_1, expected_target_1)

            # Verify files moved to target
            self.assertTrue(os.path.exists(target_1))
            self.assertTrue(os.path.isfile(os.path.join(target_1, "rank-0.db")))

            # Verify clean directory recreation (INV-ARCH-7)
            self.assertTrue(os.path.exists(source_dir))
            self.assertTrue(os.path.isdir(source_dir))
            self.assertEqual(os.listdir(source_dir), [])

            # Second archive run: populate and move again (should resolve collision to -1)
            test_file_2 = os.path.join(source_dir, "rank-1.db")
            with open(test_file_2, "w") as f:
                f.write("second payload")
            # bmtool's clean-finish marker is dropped, not archived
            open(os.path.join(source_dir, ".bm-job-ok"), "w").close()

            target_2 = ArchiveEngine.executeArchive(
                f_source_dir=source_dir,
                f_dest_root=dest_root,
                f_arm_id="native-no-footer",
            )
            expected_target_2 = os.path.join(dest_root, "outputs-native-no-footer-1")
            self.assertEqual(target_2, expected_target_2)
            self.assertTrue(os.path.isfile(os.path.join(target_2, "rank-1.db")))
            self.assertEqual(os.listdir(target_2), ["rank-1.db"])
            self.assertEqual(os.listdir(source_dir), [])

            # Failure modes: non-existent source directory raises ArchiveError
            with self.assertRaises(ArchiveError) as f_raised:
                ArchiveEngine.executeArchive(
                    f_source_dir=os.path.join(temp_root, "nonexistent"),
                    f_dest_root=dest_root,
                    f_arm_id="native",
                )
            self.assertNotIn("outputs-failed", str(f_raised.exception))

            # A failed bmtool job moved its outputs to a sibling outputs-failed: say so
            f_failed_root = os.path.join(temp_root, "failed-job")
            os.makedirs(os.path.join(f_failed_root, "outputs-failed"))
            with self.assertRaisesRegex(
                ArchiveError,
                r"failed benchmark job leaves its outputs in .*outputs-failed",
            ):
                ArchiveEngine.executeArchive(
                    f_source_dir=os.path.join(f_failed_root, "outputs"),
                    f_dest_root=dest_root,
                    f_arm_id="native",
                )

            # Failure mode: source path is not a directory
            fake_file = os.path.join(temp_root, "fake.txt")
            with open(fake_file, "w") as f:
                f.write("text")
            with self.assertRaises(ArchiveError):
                ArchiveEngine.executeArchive(
                    f_source_dir=fake_file,
                    f_dest_root=dest_root,
                    f_arm_id="native",
                )

    def testArchiveMainRunSuccess(self) -> None:
        """Tasks 4.5.7: Asserts ArchiveMain dispatching and successful execution."""
        with (
            tempfile.TemporaryDirectory() as temp_root,
            patch.object(ArchiveMain, "_benchmarkRoot", return_value=temp_root),
        ):
            # bmtool's live outputs dir, the only bmtool directory archive moves (L48)
            source_dir = os.path.join(temp_root, "lsmio", "outputs")
            dest_root = os.path.join(temp_root, "lsmio-archive")
            # bmtool outputs layout: <nodes>/<date>/out-*.txt
            payload_rel = os.path.join(
                "8", "2026-10-10", "out-native-no-footer-4-1M-2026-10-10-node1-0.txt"
            )
            payload_file = os.path.join(source_dir, payload_rel)
            os.makedirs(os.path.dirname(payload_file))
            with open(payload_file, "w") as f:
                f.write("write,1,1,1,1,1,10\nread,2,2,2,2,2,10\n")

            # M20: an arbitrary directory is never moved
            stray_dir = os.path.join(temp_root, "not-outputs")
            os.makedirs(stray_dir)
            open(os.path.join(stray_dir, "notes.txt"), "w").close()
            stray_req = ArchiveRequest(
                f_target="lsmio", f_scale="baseline", f_dest=dest_root
            )
            with patch("sys.stderr", new_callable=io.StringIO):
                self.assertEqual(
                    ArchiveMain(f_request=stray_req, f_source_dir=stray_dir).run(), 1
                )
            self.assertTrue(os.path.isfile(os.path.join(stray_dir, "notes.txt")))

            # L48: bmtool-format outputs anywhere else (a copy, an old archive) are not moved
            copy_dir = os.path.join(temp_root, "outputs-copy")
            shutil.copytree(source_dir, copy_dir)
            with patch("sys.stderr", new_callable=io.StringIO) as f_err:
                self.assertEqual(
                    ArchiveMain(f_request=stray_req, f_source_dir=copy_dir).run(), 1
                )
            self.assertIn("bmtool's live outputs directory", f_err.getvalue())
            self.assertTrue(os.path.isfile(os.path.join(copy_dir, payload_rel)))

            # Initialize ArchiveMain with direct request
            req = ArchiveRequest(
                f_target="lsmio",
                f_scale="baseline",
                f_variant="no-footer",
                f_dest=dest_root,
            )
            main_inst = ArchiveMain(
                f_request=req,
                f_source_dir=source_dir,
            )

            self.assertEqual(main_inst.request, req)
            self.assertEqual(main_inst.sourceDir, source_dir)
            self.assertIsNone(main_inst.runtimeLayout)

            # Run archive execution
            ret_code = main_inst.run()
            self.assertEqual(ret_code, 0)

            # Verify target directory created with payload
            expected_target = os.path.join(dest_root, "outputs-native-no-footer")
            self.assertTrue(os.path.isdir(expected_target))
            self.assertTrue(os.path.isfile(os.path.join(expected_target, payload_rel)))

            # Verify source directory cleanly recreated
            self.assertTrue(os.path.isdir(source_dir))
            self.assertEqual(os.listdir(source_dir), [])

            # Test initializing ArchiveMain with argv sequence
            os.makedirs(os.path.dirname(payload_file))
            with open(payload_file, "w") as f:
                f.write("write,3,3,3,3,3,10\n")

            main_inst2 = ArchiveMain(
                ["lsmio", "baseline", "no-footer", "--dest", dest_root],
                f_source_dir=source_dir,
            )
            ret_code2 = main_inst2.run()
            self.assertEqual(ret_code2, 0)
            expected_target2 = os.path.join(dest_root, "outputs-native-no-footer-1")
            self.assertTrue(os.path.isdir(expected_target2))
            self.assertEqual(os.listdir(source_dir), [])

    def testArchiveMainRunError(self) -> None:
        """Tasks 4.5.7: Asserts ArchiveMain error handling returns non-zero on failure."""
        req = ArchiveRequest(
            f_target="lsmio",
            f_scale="baseline",
            f_dest="/tmp/does_not_matter",
        )
        # Point to non-existent source directory
        main_inst = ArchiveMain(
            f_request=req,
            f_source_dir="/tmp/path_that_does_not_exist_for_archive_test_xyz",
        )
        ret_code = main_inst.run()
        self.assertEqual(ret_code, 1)


class ArchiveDestResolverTest(unittest.TestCase):
    """Asserts resolveArchiveDest mirrors bmtool/include/archive-dest.in.sh."""

    def testDefaultPartitioning(self) -> None:
        from lsmiotool.lib.archive import resolveArchiveDest

        self.assertEqual(
            resolveArchiveDest("/bm", f_mode="backends", f_scale="small"),
            "/bm/lsmio-archive/backends/small",
        )
        self.assertEqual(
            resolveArchiveDest("/bm", f_mode="standard", f_scale="variants"),
            "/bm/lsmio-archive/variants",
        )
        for f_scale in ("local", "bake", "small", "large"):
            self.assertEqual(
                resolveArchiveDest("/bm", f_mode="standard", f_scale=f_scale),
                "/bm/lsmio-archive/baseline",
            )
        # ior scaling runs archive apart from the LSMIO backends
        self.assertEqual(
            resolveArchiveDest(
                "/bm", f_mode="backends", f_scale="small", f_target="ior"
            ),
            "/bm/lsmio-archive/ior/small",
        )
        self.assertEqual(
            resolveArchiveDest(
                "/bm", f_mode="backends", f_scale="small", f_target="lsmio"
            ),
            "/bm/lsmio-archive/backends/small",
        )

    def testVersionedVariantsGetTheirOwnDestination(self) -> None:
        """--versioned runs default to variants-versioned, so 'compare variants' on the
        variant matrix archive does not mix them in; an explicit destination still wins."""
        from lsmiotool.lib.archive import resolveArchiveDest

        self.assertEqual(
            resolveArchiveDest("/bm", f_scale="variants", f_versioned=True),
            "/bm/lsmio-archive/variants-versioned",
        )
        self.assertEqual(
            resolveArchiveDest("/bm", f_scale="baseline", f_versioned=True),
            "/bm/lsmio-archive/variants-versioned",
        )
        self.assertEqual(
            resolveArchiveDest(
                "/bm", f_scale="variants", f_explicit="/abs/v", f_versioned=True
            ),
            "/abs/v",
        )

    def testDeprecatedBaselineScaleMapsToVariants(self) -> None:
        from lsmiotool.lib.archive import resolveArchiveDest

        self.assertEqual(
            resolveArchiveDest("/bm", f_mode="standard", f_scale="baseline"),
            "/bm/lsmio-archive/variants",
        )

    def testExplicitDestForms(self) -> None:
        from lsmiotool.lib.archive import resolveArchiveDest

        # Absolute paths are used as given
        self.assertEqual(
            resolveArchiveDest("/bm", f_scale="small", f_explicit="/abs/path"),
            "/abs/path",
        )
        # Root-relative shorthand resolves against the benchmark root
        self.assertEqual(
            resolveArchiveDest(
                "/bm", f_scale="small", f_explicit="/lsmio-archive/custom"
            ),
            "/bm/lsmio-archive/custom",
        )
        # A similarly-named absolute path is NOT relocated (path-component match)
        self.assertEqual(
            resolveArchiveDest(
                "/bm", f_scale="small", f_explicit="/lsmio-archive-other"
            ),
            "/lsmio-archive-other",
        )
        # Relative paths resolve against the benchmark root, as bmtool does
        self.assertEqual(
            resolveArchiveDest("/bm", f_scale="small", f_explicit="rel/path"),
            "/bm/rel/path",
        )
        # Whitespace-only values count as unset and fall through to the default
        self.assertEqual(
            resolveArchiveDest("/bm", f_scale="small", f_explicit="   "),
            "/bm/lsmio-archive/baseline",
        )

    def testTokenNormalisation(self) -> None:
        """Mixed-case mode/scale tokens normalise, matching the shell resolver."""
        from lsmiotool.lib.archive import resolveArchiveDest

        self.assertEqual(
            resolveArchiveDest("/bm", f_mode="BACKENDS", f_scale="Small"),
            "/bm/lsmio-archive/backends/small",
        )
        self.assertEqual(
            resolveArchiveDest("/bm", f_mode="standard", f_scale="Variants"),
            "/bm/lsmio-archive/variants",
        )


class ArchiveCommandBmtoolParityTest(unittest.TestCase):
    """M8: 'lsmiotool archive' resolves like bmtool's archive command
    (bmtool archive dispatch, include/archive.in.sh, include/archive-dest.in.sh)."""

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.mkdtemp(prefix="lsmiotool-archivecmd-")
        self.m_root = os.path.join(self.m_temp_dir, "benchmark")
        os.makedirs(self.m_root)
        self.m_cwd = os.getcwd()

    def tearDown(self) -> None:
        os.chdir(self.m_cwd)
        shutil.rmtree(self.m_temp_dir, ignore_errors=True)

    def _archive(
        self, f_argv: List[str], f_environ: Optional[Dict[str, str]] = None
    ) -> Tuple[int, str]:
        f_inst = ArchiveMain(
            f_request=parseArchiveArguments(f_argv),
            f_benchmark_root=self.m_root,
            f_environ=f_environ if f_environ is not None else {},
        )
        f_stderr = io.StringIO()
        with (
            patch("sys.stdout", io.StringIO()),
            patch("sys.stderr", f_stderr),
            patch("lsmiotool.lib.log.Console.error"),
            patch("lsmiotool.lib.log.Console.info"),
            patch("lsmiotool.lib.log.Console.warning"),
        ):
            return f_inst.run(), f_stderr.getvalue()

    def _bmtoolOutputs(self) -> str:
        from lsmiotool.test.parse.BmtoolParityTest import writeBmtoolLayout

        f_outputs = os.path.join(self.m_root, "lsmio", "outputs")
        writeBmtoolLayout(f_outputs, ["8"])
        open(os.path.join(f_outputs, ".bm-job-ok"), "w").close()
        return f_outputs

    def _lsmiotoolRun(
        self, f_run_id: str, f_variant: Optional[str] = "autotune"
    ) -> str:
        """A succeeded 'lsmio variants <variant>' run root under <root>/runs."""
        from lsmiotool.test.parse.BmtoolParityTest import rankLog, rankValues
        from lsmiotool.test.parse.RunParseTest import RunParseTest

        f_helper = RunParseTest("testExplicitSucceededPaths")
        f_helper.setUp()
        try:
            f_helper.m_temp_dir = self.m_root
            f_run_root, f_plan, _ = f_helper._setupSucceededRun(
                f_run_id, "lsmio", "variants", f_variant=f_variant
            )
        finally:
            f_helper.m_temp_dir = self.m_temp_dir
        f_store_root = os.path.join(f_run_root, "points")
        for f_idx, f_sp in enumerate(f_plan.scale_points):
            f_pt = os.path.join(f_store_root, f"{f_idx:02d}-tasks-{f_sp.tasks}")
            for f_salt, f_combo in enumerate(f_plan.combinations):
                f_dir = os.path.join(f_pt, "logs", f_combo.name)
                os.makedirs(f_dir, exist_ok=True)
                for f_rank in range(f_sp.tasks):
                    f_vals = rankValues(f_rank, f_salt)
                    with open(os.path.join(f_dir, f"rank_{f_rank}.log"), "w") as f_f:
                        f_f.write(rankLog(f_vals["write"], f_vals["read"]))
        return f_run_root

    def testBmtoolOutputsFromBenchmarkRootNotCwd(self) -> None:
        f_outputs = self._bmtoolOutputs()
        f_cwd = os.path.join(self.m_temp_dir, "cwd")
        os.makedirs(os.path.join(f_cwd, "outputs"))
        open(os.path.join(f_cwd, "outputs", "decoy"), "w").close()
        os.chdir(f_cwd)

        with patch.dict(os.environ, {"BM_ARCHIVE_DEST": "/inherited/dest"}):
            f_code, f_err = self._archive(["lsmio", "variants"])
        self.assertEqual(f_code, 0, f_err)
        f_target = os.path.join(
            self.m_root, "lsmio-archive", "variants", "outputs-native"
        )
        self.assertTrue(os.path.isfile(os.path.join(f_target, "lsm-report.csv")))
        self.assertTrue(os.path.isdir(os.path.join(f_target, "8", "2026-10-07")))
        self.assertFalse(os.path.exists(os.path.join(f_target, ".bm-job-ok")))
        # bmtool recreates $LSM_DIR_OBASE empty; the cwd is untouched
        self.assertEqual(os.listdir(f_outputs), [])
        self.assertEqual(os.listdir(os.path.join(f_cwd, "outputs")), ["decoy"])
        self.assertFalse(os.path.exists("/inherited/dest"))

    def testSetupFromOptionThenBmSetup(self) -> None:
        self._bmtoolOutputs()
        f_code, f_err = self._archive(
            ["lsmio", "small"], f_environ={"BM_SETUP": "ROCKSDB"}
        )
        self.assertEqual(f_code, 0, f_err)
        f_base = os.path.join(self.m_root, "lsmio-archive", "baseline")
        self.assertTrue(os.path.isdir(os.path.join(f_base, "outputs-rocksdb")))

        self._bmtoolOutputs()
        f_code, f_err = self._archive(
            ["lsmio", "small", "--setup", "adios"], f_environ={"BM_SETUP": "ROCKSDB"}
        )
        self.assertEqual(f_code, 0, f_err)
        self.assertTrue(os.path.isdir(os.path.join(f_base, "outputs-adios")))

        self._bmtoolOutputs()
        f_code, f_err = self._archive(
            ["lsmio", "small"], f_environ={"BM_SETUP": "BOGUS"}
        )
        self.assertEqual(f_code, 1)
        self.assertIn("BM_SETUP", f_err)

    def testRunRootExportedNotMoved(self) -> None:
        f_run_root = self._lsmiotoolRun("run-20261010T000000Z-aaaa")
        f_code, f_err = self._archive(["lsmio", "variants", "autotune"])
        self.assertEqual(f_code, 0, f_err)

        f_target = os.path.join(
            self.m_root, "lsmio-archive", "variants", "outputs-native-autotune"
        )
        self.assertTrue(os.path.isfile(os.path.join(f_target, "lsm-report.csv")))
        f_days = [
            f_n
            for f_n in os.listdir(os.path.join(f_target, "8"))
            if os.path.isdir(os.path.join(f_target, "8", f_n))
        ]
        self.assertEqual(len(f_days), 1)
        f_logs = os.listdir(os.path.join(f_target, "8", f_days[0]))
        self.assertEqual(len(f_logs), 48)
        self.assertTrue(all(f_n.startswith("out-native-autotune-") for f_n in f_logs))
        # The run root stays (evidence); nothing empty is left in runs/
        self.assertTrue(os.path.isfile(os.path.join(f_run_root, "manifest.json")))
        self.assertEqual(
            os.listdir(os.path.join(self.m_root, "runs")), ["run-20261010T000000Z-aaaa"]
        )
        self.assertFalse(os.path.exists(os.path.join(self.m_root, "lsmio", "outputs")))

        # The report equals bmtool's for the same rank logs
        from lsmiotool.lib import data, output

        f_bm = os.path.join(self.m_temp_dir, "bm")
        shutil.copytree(os.path.join(f_target, "8"), os.path.join(f_bm, "8"))
        for f_name in os.listdir(os.path.join(f_bm, "8")):
            if f_name.startswith("agg-"):
                os.remove(os.path.join(f_bm, "8", f_name))
        output.LsmioAggOutput(f_bm, f_scale="variants").generateReports()
        with (
            open(os.path.join(f_bm, data.LSM_REPORT_FILE)) as f_a,
            open(os.path.join(f_target, data.LSM_REPORT_FILE)) as f_b,
        ):
            self.assertEqual(f_a.read(), f_b.read())

        # Archiving the same run again is refused; another variant finds nothing
        f_code, f_err = self._archive(["lsmio", "variants", "autotune"])
        self.assertEqual(f_code, 1)
        self.assertIn("already archived", f_err)
        f_code, f_err = self._archive(["lsmio", "variants", "no-footer"])
        self.assertEqual(f_code, 1)
        self.assertIn("Nothing to archive", f_err)

    def testSyncArmRunRootIsNotArchivedAlone(self) -> None:
        """A -sync arm's run root without its arm marker is not archived as a run of its own
        (outputs-adios-sync is the 'sync' variant's name)."""
        import json

        f_run_root = self._lsmiotoolRun("run-20261010T000000Z-eeee", f_variant=None)
        f_manifest = os.path.join(f_run_root, "manifest.json")
        with open(f_manifest, "r", encoding="utf-8") as f_f:
            f_doc = json.load(f_f)
        f_doc["request"]["setup"] = "ADIOS-SYNC"
        with open(f_manifest, "w", encoding="utf-8") as f_f:
            json.dump(f_doc, f_f)

        f_code, f_err = self._archive(["lsmio", "variants", "--source", f_run_root])
        self.assertEqual(f_code, 1)
        self.assertIn("'ADIOS-SYNC' is a backends arm", f_err)
        # archive --setup refuses the -SYNC setups too
        from lsmiotool.lib.cli import ArchiveCliParseError, parseArchiveArguments

        with self.assertRaisesRegex(ArchiveCliParseError, "is a backends arm"):
            parseArchiveArguments(["lsmio", "variants", "--setup", "ADIOS-SYNC"])

    def testRunRootWithRemovedSetupIsRefused(self) -> None:
        """A run made before the '-M' setups were removed is not archived as 'native-m'."""
        import json

        f_run_root = self._lsmiotoolRun("run-20261010T000000Z-dddd", f_variant=None)
        f_manifest = os.path.join(f_run_root, "manifest.json")
        with open(f_manifest, "r", encoding="utf-8") as f_f:
            f_doc = json.load(f_f)
        f_doc["request"]["setup"] = "NATIVE-M"
        with open(f_manifest, "w", encoding="utf-8") as f_f:
            json.dump(f_doc, f_f)

        f_code, f_err = self._archive(["lsmio", "variants", "--source", f_run_root])
        self.assertEqual(f_code, 1)
        self.assertIn("'NATIVE-M' is no longer supported", f_err)
        # Without --source the run is not found, rather than archived under a new name
        f_code, f_err = self._archive(["lsmio", "variants"])
        self.assertEqual(f_code, 1)
        f_dest = os.path.join(self.m_root, "lsmio-archive", "variants")
        self.assertFalse(
            os.path.exists(os.path.join(f_dest, "outputs-native-m"))
        )
        self.assertFalse(os.path.exists(os.path.join(f_dest, "outputs-native")))

    def _iorRun(self, f_run_id: str, f_setup: str) -> str:
        """A succeeded single-setup 'ior local' run root under <root>/runs, with each
        combination's shared IOR output."""
        from lsmiotool.test.main.ArmGroupTest import IOR_SUMMARY
        from lsmiotool.test.parse.RunParseTest import RunParseTest

        f_helper = RunParseTest("testExplicitSucceededPaths")
        f_helper.setUp()
        try:
            f_helper.m_temp_dir = self.m_root
            f_run_root, f_plan, _ = f_helper._setupSucceededRun(
                f_run_id, "ior", "local", f_setup=f_setup
            )
        finally:
            f_helper.m_temp_dir = self.m_temp_dir
        for f_idx, f_sp in enumerate(f_plan.scale_points):
            f_logs = os.path.join(
                f_run_root, "points", f"{f_idx:02d}-tasks-{f_sp.tasks}", "logs"
            )
            os.makedirs(f_logs, exist_ok=True)
            for f_combo in f_plan.combinations:
                with open(
                    os.path.join(f_logs, f"ior_{f_combo.name}.stdout"), "w"
                ) as f_f:
                    f_f.write(IOR_SUMMARY)
        return f_run_root

    def testIorRunArchivedToIorFolder(self) -> None:
        """'archive ior <scale>': a single-setup ior run goes to ior/<scale> as
        outputs-ior[-<setup>], in bmtool's IOR layout with ior-report.csv."""
        f_run_root = self._iorRun("run-20261014T000000Z-ior1", "HDF5-C")
        # bmtool's LSMIO outputs and BM_SETUP play no part in an ior archive
        self._bmtoolOutputs()
        f_code, f_err = self._archive(
            ["ior", "local"], f_environ={"BM_SETUP": "ROCKSDB"}
        )
        self.assertEqual(f_code, 0, f_err)
        f_target = os.path.join(
            self.m_root, "lsmio-archive", "ior", "local", "outputs-ior-hdf5-collective"
        )
        with open(os.path.join(f_target, "ior-report.csv")) as f_f:
            f_rows = f_f.read().split()
        self.assertEqual(len(f_rows), 12)
        self.assertTrue(all(f_r.startswith("1,") for f_r in f_rows))
        f_days = [
            f_n
            for f_n in os.listdir(os.path.join(f_target, "1"))
            if os.path.isdir(os.path.join(f_target, "1", f_n))
        ]
        self.assertEqual(len(f_days), 1)
        f_logs = os.listdir(os.path.join(f_target, "1", f_days[0]))
        self.assertEqual(len(f_logs), 6)
        self.assertTrue(all(f_n.startswith("out-hdf5-c-") for f_n in f_logs))
        self.assertFalse(os.path.exists(os.path.join(f_target, "lsm-report.csv")))
        self.assertTrue(os.path.isfile(os.path.join(f_run_root, "manifest.json")))

        f_code, f_err = self._archive(["ior", "local"])
        self.assertEqual(f_code, 1)
        self.assertIn("already archived", f_err)
        f_code, f_err = self._archive(["ior", "local", "--setup", "base"])
        self.assertEqual(f_code, 1)
        self.assertIn("Nothing to archive", f_err)
        f_code, f_err = self._archive(
            ["ior", "local", "--source", f_run_root, "--setup", "BASE"]
        )
        self.assertEqual(f_code, 1)
        self.assertIn("does not match", f_err)

    def testIorArchiveTakesOnlyRunRoots(self) -> None:
        """bmtool never archived IOR: its live LSMIO outputs are never an ior --source."""
        f_outputs = self._bmtoolOutputs()
        f_before = sorted(os.listdir(f_outputs))
        for f_extra in ([], ["--setup", "HDF5"]):
            f_code, f_err = self._archive(
                ["ior", "local", "--source", f_outputs] + f_extra
            )
            self.assertEqual(f_code, 1)
            self.assertIn("an ior archive takes only an ior run root", f_err)
        self.assertEqual(sorted(os.listdir(f_outputs)), f_before)
        self.assertFalse(os.path.exists(os.path.join(self.m_root, "lsmio-archive")))

    def testIorArchiveCli(self) -> None:
        f_req = parseArchiveArguments(["ior", "small", "--setup", "hdf5-c"])
        self.assertEqual((f_req.target, f_req.setup), ("ior", "HDF5-C"))
        # The IOR setup tokens of 'run ior <scale> <ior setups>' name setups too
        for f_tok, f_setup in (("hdf5-collective", "HDF5-C"), ("ior", "BASE")):
            self.assertEqual(
                parseArchiveArguments(["ior", "small", "--setup", f_tok]).setup, f_setup
            )
        for f_argv in (
            ["ior", "variants"],
            ["ior", "small", "--setup", "NATIVE"],
            ["lsmio", "small", "--setup", "HDF5"],
        ):
            with self.subTest(argv=f_argv):
                with self.assertRaises(ArchiveCliParseError):
                    parseArchiveArguments(f_argv)

    def testAmbiguousSourceNeedsExplicitSource(self) -> None:
        f_run_root = self._lsmiotoolRun("run-20261010T000000Z-bbbb", f_variant=None)
        f_outputs = self._bmtoolOutputs()
        f_code, f_err = self._archive(["lsmio", "variants"])
        self.assertEqual(f_code, 1)
        self.assertIn("--source", f_err)

        f_code, f_err = self._archive(["lsmio", "variants", "--source", f_run_root])
        self.assertEqual(f_code, 0, f_err)
        self.assertTrue(
            os.path.isdir(
                os.path.join(self.m_root, "lsmio-archive", "variants", "outputs-native")
            )
        )
        f_code, f_err = self._archive(["lsmio", "variants", "--source", f_outputs])
        self.assertEqual(f_code, 0, f_err)
        self.assertTrue(
            os.path.isdir(
                os.path.join(
                    self.m_root, "lsmio-archive", "variants", "outputs-native-1"
                )
            )
        )
        # An explicit run root must match the request
        f_code, f_err = self._archive(
            ["lsmio", "variants", "--source", f_run_root, "--setup", "ROCKSDB"]
        )
        self.assertEqual(f_code, 1)
        self.assertIn("does not match", f_err)

    def testCliSetupAndSource(self) -> None:
        f_req = parseArchiveArguments(
            ["archive", "lsmio", "small", "--setup", "rocksdb", "--source", "/x/y"]
        )
        self.assertEqual((f_req.setup, f_req.source), ("ROCKSDB", "/x/y"))
        self.assertEqual(f_req.toDict()["setup"], "ROCKSDB")
        self.assertNotIn("setup", parseArchiveArguments(["lsmio", "small"]).toDict())
        for f_argv in (
            ["lsmio", "small", "--setup", "nope"],
            ["lsmio", "small", "--setup", "rocksdb-m"],
            ["lsmio", "small", "--setup", "NATIVE-M"],
            ["lsmio", "small", "--setup"],
            ["lsmio", "small", "--setup", "ADIOS", "--setup", "ADIOS"],
            ["lsmio", "small", "--source", "--setup"],
        ):
            with self.assertRaises(ArchiveCliParseError):
                parseArchiveArguments(f_argv)


if __name__ == "__main__":
    unittest.main()
