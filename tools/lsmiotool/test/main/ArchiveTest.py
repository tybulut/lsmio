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

import os
import tempfile
import unittest

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
from lsmiotool.lib.variants import UnknownVariantError


class ArchiveTest(unittest.TestCase):
    """Unit test suite asserting move-on-archive semantics, parser contracts, and collision handling."""

    def testArchiveRequestImmutability(self) -> None:
        """Tasks 4.5.1: Asserts ArchiveRequest fields, properties, immutability, and validation."""
        req = ArchiveRequest(
            f_target="lsmio",
            f_scale="baseline",
            f_variant="footer",
            f_dest="/tmp/archive",
        )

        self.assertEqual(req.target, "lsmio")
        self.assertEqual(req.scale, "baseline")
        self.assertEqual(req.variant, "footer")
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
                "scale": "baseline",
                "variant": "footer",
                "dest": "/tmp/archive",
            },
        )

        # Repr and value equality
        self.assertIn("ArchiveRequest", repr(req))
        req2 = ArchiveRequest(
            f_target="lsmio",
            f_scale="baseline",
            f_variant="footer",
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
            ["archive", "lsmio", "baseline", "footer", "--dest", "/tmp/archive"]
        )
        self.assertEqual(req1.target, "lsmio")
        self.assertEqual(req1.scale, "baseline")
        self.assertEqual(req1.variant, "footer")
        self.assertEqual(req1.dest, "/tmp/archive")

        # 2. Without leading 'archive'
        req2 = parseArchiveArguments(["lsmio", "baseline", "footer-btree"])
        self.assertEqual(req2.target, "lsmio")
        self.assertEqual(req2.scale, "baseline")
        self.assertEqual(req2.variant, "footer-btree")
        self.assertIsNone(req2.dest)

        # 3. Baseline scale with base/default normalizes to None
        req3 = parseArchiveArguments(["lsmio", "baseline", "default"])
        self.assertIsNone(req3.variant)

        req4 = parseArchiveArguments(["lsmio", "baseline", "base"])
        self.assertIsNone(req4.variant)

        # 4. Baseline scale without variant
        req5 = parseArchiveArguments(["lsmio", "baseline"])
        self.assertEqual(req5.scale, "baseline")
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
        req7 = parseArchiveArguments(["LSMIO", "BASELINE", "FOOTER-BTREE"])
        self.assertEqual(req7.target, "lsmio")
        self.assertEqual(req7.scale, "baseline")
        self.assertEqual(req7.variant, "footer-btree")

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

        # Benchmark validation: only lsmio is supported for archive
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
                parseArchiveArguments(["lsmio", sc, "footer"])
            self.assertIn("Unexpected extra positional argument", str(ctx.exception))

        # Baseline scale with unknown variant fails fast
        with self.assertRaises(UnknownVariantError) as ctx_u:
            parseArchiveArguments(["lsmio", "baseline", "nonexistent_variant"])
        self.assertIn("Invalid variant", str(ctx_u.exception))

        # Baseline scale rejects extra positional arguments after variant
        with self.assertRaises(ArchiveCliParseError):
            parseArchiveArguments(["lsmio", "baseline", "footer", "unexpected"])

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
        # NATIVE-M with variant
        self.assertEqual(
            ArchiveEngine.resolveArmId("NATIVE-M", "footer-btree"),
            "native-footer-btree",
        )
        self.assertEqual(
            ArchiveEngine.resolveArmId("NATIVE-M", "footer"),
            "native-footer",
        )
        self.assertEqual(
            ArchiveEngine.resolveArmId("NATIVE-M", None),
            "native",
        )
        self.assertEqual(
            ArchiveEngine.resolveArmId("NATIVE-M", "default"),
            "native",
        )

        # lsmio setup normalization
        self.assertEqual(
            ArchiveEngine.resolveArmId("lsmio", "footer-btree"),
            "lsmio-footer-btree",
        )
        self.assertEqual(
            ArchiveEngine.resolveArmId("lsmio", None),
            "lsmio",
        )

        # Composite setups
        self.assertEqual(
            ArchiveEngine.resolveArmId("ROCKSDB-M", "wbuf-512m"),
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
            arm_id = "native-footer-btree"

            # Case 1: Target does not exist
            t0 = ArchiveEngine.resolveTargetDirectory(temp_dir, arm_id)
            self.assertEqual(
                t0, os.path.join(temp_dir, "outputs-native-footer-btree")
            )

            # Case 2: Base target exists -> suffix -1
            os.makedirs(t0)
            t1 = ArchiveEngine.resolveTargetDirectory(temp_dir, arm_id)
            self.assertEqual(
                t1, os.path.join(temp_dir, "outputs-native-footer-btree-1")
            )

            # Case 3: -1 also exists -> suffix -2
            os.makedirs(t1)
            t2 = ArchiveEngine.resolveTargetDirectory(temp_dir, arm_id)
            self.assertEqual(
                t2, os.path.join(temp_dir, "outputs-native-footer-btree-2")
            )

            # Case 4: -2 also exists -> suffix -3
            os.makedirs(t2)
            t3 = ArchiveEngine.resolveTargetDirectory(temp_dir, arm_id)
            self.assertEqual(
                t3, os.path.join(temp_dir, "outputs-native-footer-btree-3")
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
                f_arm_id="native-footer",
            )
            expected_target_1 = os.path.join(dest_root, "outputs-native-footer")
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

            target_2 = ArchiveEngine.executeArchive(
                f_source_dir=source_dir,
                f_dest_root=dest_root,
                f_arm_id="native-footer",
            )
            expected_target_2 = os.path.join(
                dest_root, "outputs-native-footer-1"
            )
            self.assertEqual(target_2, expected_target_2)
            self.assertTrue(
                os.path.isfile(os.path.join(target_2, "rank-1.db"))
            )
            self.assertEqual(os.listdir(source_dir), [])

            # Failure modes: non-existent source directory raises ArchiveError
            with self.assertRaises(ArchiveError):
                ArchiveEngine.executeArchive(
                    f_source_dir=os.path.join(temp_root, "nonexistent"),
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
        with tempfile.TemporaryDirectory() as temp_root:
            source_dir = os.path.join(temp_root, "outputs")
            dest_root = os.path.join(temp_root, "lsmio-archive")
            os.makedirs(source_dir)

            payload_file = os.path.join(source_dir, "output.log")
            with open(payload_file, "w") as f:
                f.write("run output log")

            # Initialize ArchiveMain with direct request
            req = ArchiveRequest(
                f_target="lsmio",
                f_scale="baseline",
                f_variant="footer",
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
            expected_target = os.path.join(dest_root, "outputs-native-footer")
            self.assertTrue(os.path.isdir(expected_target))
            self.assertTrue(
                os.path.isfile(os.path.join(expected_target, "output.log"))
            )

            # Verify source directory cleanly recreated
            self.assertTrue(os.path.isdir(source_dir))
            self.assertEqual(os.listdir(source_dir), [])

            # Test initializing ArchiveMain with argv sequence
            with open(os.path.join(source_dir, "second.log"), "w") as f:
                f.write("second log")

            main_inst2 = ArchiveMain(
                ["lsmio", "baseline", "footer", "--dest", dest_root],
                f_source_dir=source_dir,
            )
            ret_code2 = main_inst2.run()
            self.assertEqual(ret_code2, 0)
            expected_target2 = os.path.join(
                dest_root, "outputs-native-footer-1"
            )
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


if __name__ == "__main__":
    unittest.main()
