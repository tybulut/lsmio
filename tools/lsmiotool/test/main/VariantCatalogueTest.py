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

"""Unit tests for VariantRecord, VariantCatalogue, and UnknownVariantError."""

import unittest

from lsmiotool.lib.cli import CliParseError
from lsmiotool.lib.variants import (
    UnknownVariantError,
    VariantCatalogue,
    VariantRecord,
)


class VariantCatalogueTest(unittest.TestCase):
    """Unit test suite verifying declarative variant catalog, mappings, and immutability."""

    EXPECTED_37_VARIANTS = {
        "footer": ("footer", ("--lsmio-no-autotune", "--lsmio-footer-index")),
        "btree": ("btree", ("--lsmio-no-autotune", "--lsmio-memtable", "btree")),
        "footer-btree": (
            "footer-btree",
            ("--lsmio-no-autotune", "--lsmio-footer-index", "--lsmio-memtable", "btree"),
        ),
        "map": ("map", ("--lsmio-no-autotune", "--lsmio-memtable", "map")),
        "vsort": ("vsort", ("--lsmio-no-autotune", "--lsmio-memtable", "vector-sort")),
        "prealloc": ("prealloc", ("--lsmio-no-autotune", "--lsmio-prealloc")),
        "footer-prealloc": (
            "footer-prealloc",
            ("--lsmio-no-autotune", "--lsmio-footer-index", "--lsmio-prealloc"),
        ),
        "manoff": ("manoff", ("--lsmio-no-autotune", "--lsmio-manual-offset")),
        "footer-manoff": (
            "footer-manoff",
            ("--lsmio-no-autotune", "--lsmio-footer-index", "--lsmio-manual-offset"),
        ),
        "wbuf-512m": ("wbuf-512m", ("--lsmio-no-autotune", "--lsmio-wbuffer", "536870912")),
        "wbuf-32m": ("wbuf-32m", ("--lsmio-no-autotune", "--lsmio-wbuffer", "33554432")),
        "footer-wbuf-512m": (
            "footer-wbuf-512m",
            ("--lsmio-no-autotune", "--lsmio-footer-index", "--lsmio-wbuffer", "536870912"),
        ),
        "footer-btree-prealloc": (
            "footer-btree-prealloc",
            (
                "--lsmio-no-autotune",
                "--lsmio-footer-index",
                "--lsmio-memtable",
                "btree",
                "--lsmio-prealloc",
            ),
        ),
        "bfilter": ("bfilter", ("--lsmio-no-autotune", "--lsmio-bfilter")),
        "wal": ("wal", ("--lsmio-no-autotune", "--lsmio-wal")),
        "mmap": ("mmap", ("--lsmio-no-autotune", "--lsmio-mmap")),
        "pread": ("pread", ("--lsmio-no-autotune", "--lsmio-pread")),
        "footer-mmap": (
            "footer-mmap",
            ("--lsmio-no-autotune", "--lsmio-footer-index", "--lsmio-mmap"),
        ),
        "footer-pread": (
            "footer-pread",
            ("--lsmio-no-autotune", "--lsmio-footer-index", "--lsmio-pread"),
        ),
        "compress": ("compress", ("--lsmio-no-autotune", "--lsmio-compress")),
        "sync": ("sync", ("--lsmio-no-autotune", "--sync")),
        "pool-8": ("pool-8", ("--lsmio-no-autotune", "--lsmio-pool", "8")),
        "flush": ("flush", ("--lsmio-no-autotune", "--lsmio-always-flush")),
        "batch-2048": ("batch-2048", ("--lsmio-no-autotune", "--lsmio-batch-size", "2048")),
        "manoff-prealloc": (
            "manoff-prealloc",
            ("--lsmio-no-autotune", "--lsmio-manual-offset", "--lsmio-prealloc"),
        ),
        "wbuf-512m-manoff-prealloc": (
            "wbuf-512m-manoff-prealloc",
            (
                "--lsmio-no-autotune",
                "--lsmio-wbuffer",
                "536870912",
                "--lsmio-manual-offset",
                "--lsmio-prealloc",
            ),
        ),
        "footer-wbuf-32m": (
            "footer-wbuf-32m",
            ("--lsmio-no-autotune", "--lsmio-footer-index", "--lsmio-wbuffer", "33554432"),
        ),
        "footer-pool-8": (
            "footer-pool-8",
            ("--lsmio-no-autotune", "--lsmio-footer-index", "--lsmio-pool", "8"),
        ),
        "footer-wbuf-512m-manoff-prealloc": (
            "footer-wbuf-512m-manoff-prealloc",
            (
                "--lsmio-no-autotune",
                "--lsmio-footer-index",
                "--lsmio-wbuffer",
                "536870912",
                "--lsmio-manual-offset",
                "--lsmio-prealloc",
            ),
        ),
        "footer-vsort-manoff-prealloc": (
            "footer-vsort-manoff-prealloc",
            (
                "--lsmio-no-autotune",
                "--lsmio-footer-index",
                "--lsmio-memtable",
                "vector-sort",
                "--lsmio-manual-offset",
                "--lsmio-prealloc",
            ),
        ),
        "footer-vsort-manoff-mmap": (
            "footer-vsort-manoff-mmap",
            (
                "--lsmio-no-autotune",
                "--lsmio-footer-index",
                "--lsmio-memtable",
                "vector-sort",
                "--lsmio-manual-offset",
                "--lsmio-mmap",
            ),
        ),
        "footer-vsort-manoff": (
            "footer-vsort-manoff",
            (
                "--lsmio-no-autotune",
                "--lsmio-footer-index",
                "--lsmio-memtable",
                "vector-sort",
                "--lsmio-manual-offset",
            ),
        ),
        "footer-pool-8-mmap": (
            "footer-pool-8-mmap",
            (
                "--lsmio-no-autotune",
                "--lsmio-footer-index",
                "--lsmio-pool",
                "8",
                "--lsmio-mmap",
            ),
        ),
        "footer-manoff-pool-8-mmap": (
            "footer-manoff-pool-8-mmap",
            (
                "--lsmio-no-autotune",
                "--lsmio-footer-index",
                "--lsmio-manual-offset",
                "--lsmio-pool",
                "8",
                "--lsmio-mmap",
            ),
        ),
        "footer-btree-manoff-mmap": (
            "footer-btree-manoff-mmap",
            (
                "--lsmio-no-autotune",
                "--lsmio-footer-index",
                "--lsmio-memtable",
                "btree",
                "--lsmio-manual-offset",
                "--lsmio-mmap",
            ),
        ),
        "footer-manoff-pool-8": (
            "footer-manoff-pool-8",
            (
                "--lsmio-no-autotune",
                "--lsmio-footer-index",
                "--lsmio-manual-offset",
                "--lsmio-pool",
                "8",
            ),
        ),
        "autotune": (
            "autotune",
            ("--lsmio-autotune",),
        ),
    }

    def testDefaultAndBaseKeysReturnEmpty(self) -> None:
        """Assert None, empty strings, 'base', and 'default' resolve to empty VariantRecord."""
        for key in (
            None,
            "",
            "   ",
            "base",
            "default",
            "BASE",
            "DEFAULT",
            " Base ",
            " Default ",
        ):
            rec = VariantCatalogue.resolve(key)
            self.assertEqual(rec.key, "")
            self.assertEqual(rec.tokens, "")
            self.assertEqual(rec.flags, ())
            self.assertEqual(rec.flagsString, "")
            self.assertTrue(VariantCatalogue.isValid(key))

    def testAll37NonEmptyVariants(self) -> None:
        """Assert all 37 non-empty keys match tokens and engine CLI flags."""
        supported = VariantCatalogue.supportedVariants()
        all_keys = VariantCatalogue.getAllVariantKeys()
        self.assertEqual(len(supported), 37)
        self.assertEqual(len(self.EXPECTED_37_VARIANTS), 37)
        self.assertEqual(supported, all_keys)
        self.assertEqual(set(supported), set(self.EXPECTED_37_VARIANTS.keys()))

        for key, (expected_tokens, expected_flags) in self.EXPECTED_37_VARIANTS.items():
            rec = VariantCatalogue.resolve(key)
            self.assertEqual(rec.key, key)
            self.assertEqual(rec.tokens, expected_tokens)
            self.assertEqual(rec.flags, expected_flags)
            self.assertEqual(rec.flagsString, " ".join(expected_flags))
            self.assertTrue(VariantCatalogue.isValid(key))

    def testFlushVariantExactFlag(self) -> None:
        """Assert INV-ARCH-4: 'flush' maps strictly to '--lsmio-always-flush'."""
        rec = VariantCatalogue.resolve("flush")
        self.assertEqual(rec.flags, ("--lsmio-no-autotune", "--lsmio-always-flush"))
        self.assertEqual(rec.flagsString, "--lsmio-no-autotune --lsmio-always-flush")
        self.assertNotIn("--lsmo-always-flush", rec.flags)

    def testSyncVariantFlag(self) -> None:
        """Assert 'sync' maps strictly to ('--sync',)."""
        rec = VariantCatalogue.resolve("sync")
        self.assertEqual(rec.flags, ("--lsmio-no-autotune", "--sync"))
        self.assertEqual(rec.flagsString, "--lsmio-no-autotune --sync")

    def testPrefixStripping(self) -> None:
        """Assert stripBackendPrefix strips two-segment and one-segment prefixes."""
        two_segment_cases = [
            ("native-m-footer", "footer"),
            ("NATIVE-M-FOOTER", "footer"),
            ("rocksdb-m-btree", "btree"),
            ("ROCKSDB-M-btree", "btree"),
            ("leveldb-m-map", "map"),
            ("adios-m-wal", "wal"),
            ("plugin-m-sync", "sync"),
            ("native-m-footer-btree", "footer-btree"),
            ("rocksdb-m-wbuf-512m-manoff-prealloc", "wbuf-512m-manoff-prealloc"),
        ]
        for prefixed, expected in two_segment_cases:
            stripped = VariantCatalogue.stripBackendPrefix(prefixed)
            self.assertEqual(stripped, expected)
            rec = VariantCatalogue.resolve(prefixed)
            self.assertEqual(rec.key, expected)

        one_segment_cases = [
            ("native-footer", "footer"),
            ("rocksdb-btree", "btree"),
            ("leveldb-map", "map"),
            ("adios-wal", "wal"),
            ("plugin-sync", "sync"),
            ("manager-wbuf-512m", "wbuf-512m"),
            ("MANAGER-BATCH-2048", "batch-2048"),
        ]
        for prefixed, expected in one_segment_cases:
            stripped = VariantCatalogue.stripBackendPrefix(prefixed)
            self.assertEqual(stripped, expected)
            rec = VariantCatalogue.resolve(prefixed)
            self.assertEqual(rec.key, expected)

        # Base and default with prefix
        self.assertEqual(VariantCatalogue.stripBackendPrefix("native-m-base"), "base")
        self.assertEqual(
            VariantCatalogue.stripBackendPrefix("manager-default"), "default"
        )
        rec_base = VariantCatalogue.resolve("native-m-base")
        self.assertEqual(rec_base.key, "")
        self.assertEqual(rec_base.tokens, "")
        rec_default = VariantCatalogue.resolve("manager-default")
        self.assertEqual(rec_default.key, "")
        self.assertEqual(rec_default.tokens, "")

    def testUnknownVariantRaises(self) -> None:
        """Assert unrecognized variant keys raise UnknownVariantError with details."""
        for invalid_key in (
            "unknown",
            "footer-foo",
            "invalid",
            "wbuf-128m",
            "native-m-unknown",
            "12345",
        ):
            self.assertFalse(VariantCatalogue.isValid(invalid_key))
            with self.assertRaises(UnknownVariantError) as ctx:
                VariantCatalogue.resolve(invalid_key)

            err = ctx.exception
            self.assertIsInstance(err, CliParseError)
            self.assertEqual(err.m_variant, invalid_key)
            self.assertEqual(err.variant, invalid_key)
            self.assertEqual(err.m_supported, VariantCatalogue.supportedVariants())
            self.assertEqual(err.supported, VariantCatalogue.supportedVariants())
            self.assertIn(f"Invalid variant: {invalid_key!r}", str(err))

    def testGetInfixDerivation(self) -> None:
        """Assert INV-ARCH-8: getInfix generates correct backend-variant infixes."""
        self.assertEqual(
            VariantCatalogue.getInfix("NATIVE-M", "footer-btree"),
            "native-footer-btree",
        )
        self.assertEqual(
            VariantCatalogue.getInfix("ROCKSDB", "sync"),
            "rocksdb-nompi-sync",
        )
        self.assertEqual(
            VariantCatalogue.getInfix("MANAGER", None),
            "manager",
        )
        self.assertEqual(
            VariantCatalogue.getInfix("native-m", "base"),
            "native",
        )
        self.assertEqual(
            VariantCatalogue.getInfix("leveldb", "flush"),
            "leveldb-nompi-flush",
        )
        self.assertEqual(
            VariantCatalogue.getInfix("ADIOS-M", "default"),
            "adios",
        )
        self.assertEqual(
            VariantCatalogue.getInfix("PLUGIN-M", ""),
            "plugin",
        )
        # Keyword arguments
        self.assertEqual(
            VariantCatalogue.getInfix(f_backend="NATIVE-M", f_key="footer"),
            "native-footer",
        )
        self.assertEqual(
            VariantCatalogue.getInfix(f_setup="ROCKSDB-M", f_variant="btree"),
            "rocksdb-btree",
        )

    def testVariantRecordImmutability(self) -> None:
        """Assert INV-ARCH-6: VariantRecord instances are strictly immutable."""
        rec = VariantCatalogue.resolve("footer")

        with self.assertRaises(AttributeError):
            rec.key = "other"  # type: ignore[misc]

        with self.assertRaises(AttributeError):
            rec.tokens = "other"  # type: ignore[misc]

        with self.assertRaises(AttributeError):
            rec.flags = ()  # type: ignore[misc]

        with self.assertRaises(AttributeError):
            rec.m_key = "other"  # type: ignore[misc]

        with self.assertRaises(AttributeError):
            del rec.key  # type: ignore[misc]

        with self.assertRaises(AttributeError):
            del rec.m_key  # type: ignore[misc]

    def testVariantRecordValueSemantics(self) -> None:
        """Assert VariantRecord value semantics, string representation, and hashing."""
        rec1 = VariantRecord("footer", "footer", ("--lsmio-footer-index",))
        rec2 = VariantRecord("footer", "footer", ["--lsmio-footer-index"])
        rec3 = VariantRecord("btree", "btree", ("--lsmio-memtable", "btree"))

        self.assertEqual(rec1, rec2)
        self.assertNotEqual(rec1, rec3)
        self.assertNotEqual(rec1, "not-a-record")
        self.assertEqual(hash(rec1), hash(rec2))
        self.assertIn("footer", repr(rec1))
        self.assertIn("--lsmio-footer-index", repr(rec1))


if __name__ == "__main__":
    unittest.main()
