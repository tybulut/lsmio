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
    UnknownSetupError,
    UnknownVariantError,
    VariantCatalogue,
    VariantRecord,
)


class VariantCatalogueTest(unittest.TestCase):
    """Unit test suite verifying declarative variant catalog, mappings, and immutability."""

    EXPECTED_25_VARIANTS = {
        "vsort": ("vsort", ("--lsmio-no-autotune", "--lsmio-memtable", "vector-sort")),
        "btree": ("btree", ("--lsmio-no-autotune", "--lsmio-memtable", "btree")),
        "vnosort": (
            "vnosort",
            ("--lsmio-no-autotune", "--lsmio-memtable", "vector-no-sort"),
        ),
        "mmap": ("mmap", ("--lsmio-no-autotune", "--lsmio-mmap", "--lsmio-no-pread")),
        "no-pread": ("no-pread", ("--lsmio-no-autotune", "--lsmio-no-pread")),
        "no-footer": ("no-footer", ("--lsmio-no-autotune", "--lsmio-no-footer-index")),
        "no-manoff": ("no-manoff", ("--lsmio-no-autotune", "--lsmio-no-manual-offset")),
        "legacy": (
            "legacy",
            (
                "--lsmio-no-autotune",
                "--lsmio-no-footer-index",
                "--lsmio-no-manual-offset",
                "--lsmio-no-pread",
                "--lsmio-memtable",
                "vector-no-sort",
            ),
        ),
        "prealloc": ("prealloc", ("--lsmio-no-autotune", "--lsmio-prealloc")),
        "wbuf-512m": (
            "wbuf-512m",
            ("--lsmio-no-autotune", "--lsmio-wbuffer", "536870912"),
        ),
        "wbuf-32m": (
            "wbuf-32m",
            ("--lsmio-no-autotune", "--lsmio-wbuffer", "33554432"),
        ),
        "pool-8": ("pool-8", ("--lsmio-no-autotune", "--lsmio-pool", "8")),
        "prealloc-vsort": (
            "prealloc-vsort",
            (
                "--lsmio-no-autotune",
                "--lsmio-memtable",
                "vector-sort",
                "--lsmio-prealloc",
            ),
        ),
        "prealloc-btree": (
            "prealloc-btree",
            ("--lsmio-no-autotune", "--lsmio-memtable", "btree", "--lsmio-prealloc"),
        ),
        "prealloc-wbuf-512m": (
            "prealloc-wbuf-512m",
            ("--lsmio-no-autotune", "--lsmio-wbuffer", "536870912", "--lsmio-prealloc"),
        ),
        "mmap-vsort": (
            "mmap-vsort",
            (
                "--lsmio-no-autotune",
                "--lsmio-memtable",
                "vector-sort",
                "--lsmio-mmap",
                "--lsmio-no-pread",
            ),
        ),
        "mmap-btree": (
            "mmap-btree",
            (
                "--lsmio-no-autotune",
                "--lsmio-memtable",
                "btree",
                "--lsmio-mmap",
                "--lsmio-no-pread",
            ),
        ),
        "pool-8-mmap": (
            "pool-8-mmap",
            (
                "--lsmio-no-autotune",
                "--lsmio-pool",
                "8",
                "--lsmio-mmap",
                "--lsmio-no-pread",
            ),
        ),
        "flush": ("flush", ("--lsmio-no-autotune", "--lsmio-always-flush")),
        "batch-2048": (
            "batch-2048",
            ("--lsmio-no-autotune", "--lsmio-batch-size", "2048"),
        ),
        "bfilter": ("bfilter", ("--lsmio-no-autotune", "--lsmio-bfilter")),
        "wal": ("wal", ("--lsmio-no-autotune", "--lsmio-wal")),
        "compress": ("compress", ("--lsmio-no-autotune", "--lsmio-compress")),
        "sync": ("sync", ("--lsmio-no-autotune", "--sync")),
        "autotune": ("autotune", ("--lsmio-autotune",)),
    }

    RETIRED_35_VARIANTS = (
        "footer",
        "footer-btree",
        "map",
        "footer-prealloc",
        "manoff",
        "footer-manoff",
        "footer-wbuf-512m",
        "footer-btree-prealloc",
        "pread",
        "footer-mmap",
        "footer-pread",
        "manoff-prealloc",
        "wbuf-512m-manoff-prealloc",
        "footer-wbuf-32m",
        "footer-pool-8",
        "footer-wbuf-512m-manoff-prealloc",
        "footer-vsort-manoff-prealloc",
        "footer-vsort-manoff-mmap",
        "footer-vsort-manoff",
        "footer-pool-8-mmap",
        "footer-manoff-pool-8-mmap",
        "footer-btree-manoff-mmap",
        "footer-manoff-pool-8",
        "footer-pread-pool-8",
        "footer-pread-manoff",
        "footer-pread-manoff-pool-8",
        "footer-map-pread",
        "footer-btree-pread",
        "footer-vsort-pread",
        "footer-btree-manoff-pread",
        "footer-map-manoff-pread",
        "footer-map-manoff-mmap",
        "footer-map",
        "footer-map-manoff",
        "manoff-pool-8",
    )

    EXPECTED_CANONICAL_25_VARIANTS = (
        "vsort",
        "btree",
        "vnosort",
        "mmap",
        "no-pread",
        "no-footer",
        "no-manoff",
        "legacy",
        "prealloc",
        "wbuf-512m",
        "wbuf-32m",
        "pool-8",
        "prealloc-vsort",
        "prealloc-btree",
        "prealloc-wbuf-512m",
        "mmap-vsort",
        "mmap-btree",
        "pool-8-mmap",
        "flush",
        "batch-2048",
        "bfilter",
        "wal",
        "compress",
        "sync",
        "autotune",
    )

    def testDefaultAndBaseKeysResolveToNoAutotune(self) -> None:
        """Assert None, empty strings, 'base', and 'default' resolve to the default VariantRecord."""
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
            self.assertEqual(rec.flags, ("--lsmio-no-autotune",))
            self.assertEqual(rec.flagsString, "--lsmio-no-autotune")
            self.assertEqual(rec, VariantRecord("", "", ("--lsmio-no-autotune",)))
            self.assertTrue(VariantCatalogue.isValid(key))

    def testCanonicalVariants(self) -> None:
        """Assert canonical matrix contains 'default' followed by 25 streamlined variants."""
        canonical = VariantCatalogue.canonicalVariants()
        self.assertEqual(len(canonical), 26)
        self.assertEqual(canonical[0], "default")
        self.assertEqual(canonical[1:], self.EXPECTED_CANONICAL_25_VARIANTS)

    def testMostVariants(self) -> None:
        """Assert 'mostVariants' returns the 26 canonical matrix variants and aliases canonicalVariants."""
        most = VariantCatalogue.mostVariants()
        self.assertEqual(len(most), 26)
        self.assertEqual(most, VariantCatalogue.canonicalVariants())
        self.assertEqual(most[0], "default")
        self.assertEqual(most[1:], self.EXPECTED_CANONICAL_25_VARIANTS)
        for var in most:
            self.assertTrue(VariantCatalogue.isValid(var))
            rec = VariantCatalogue.resolve(var)
            self.assertIsInstance(rec, VariantRecord)

    def testAllVariants(self) -> None:
        """Assert 'allVariants' returns 'default' followed by all supported variants and equals mostVariants."""
        all_vars = VariantCatalogue.allVariants()
        supported = VariantCatalogue.supportedVariants()
        self.assertEqual(len(all_vars), len(supported) + 1)
        self.assertEqual(len(all_vars), 26)
        self.assertEqual(all_vars, VariantCatalogue.mostVariants())
        self.assertEqual(all_vars[0], "default")
        self.assertEqual(all_vars[1:], supported)
        for var in all_vars:
            self.assertTrue(VariantCatalogue.isValid(var))
            rec = VariantCatalogue.resolve(var)
            self.assertIsInstance(rec, VariantRecord)
        for retired in self.RETIRED_35_VARIANTS:
            self.assertNotIn(retired, all_vars)

    def testAll25NonEmptyVariants(self) -> None:
        """Assert all 25 non-empty keys match tokens and engine CLI flags and the 35 retired keys are rejected."""
        supported = VariantCatalogue.supportedVariants()
        all_keys = VariantCatalogue.getAllVariantKeys()
        self.assertEqual(len(supported), 25)
        self.assertEqual(len(self.EXPECTED_25_VARIANTS), 25)
        self.assertEqual(supported, all_keys)
        self.assertEqual(supported, tuple(self.EXPECTED_25_VARIANTS.keys()))
        self.assertEqual(supported, self.EXPECTED_CANONICAL_25_VARIANTS)

        for key, (expected_tokens, expected_flags) in self.EXPECTED_25_VARIANTS.items():
            rec = VariantCatalogue.resolve(key)
            self.assertEqual(rec.key, key)
            self.assertEqual(rec.tokens, expected_tokens)
            self.assertEqual(rec.flags, expected_flags)
            self.assertEqual(rec.flagsString, " ".join(expected_flags))
            self.assertTrue(VariantCatalogue.isValid(key))

        # Retired keys can no longer be run but still name archive directories
        archived = VariantCatalogue.archivedVariantNames()
        self.assertEqual(len(self.RETIRED_35_VARIANTS), 35)
        self.assertEqual(archived, supported + self.RETIRED_35_VARIANTS)
        for key in self.RETIRED_35_VARIANTS:
            self.assertNotIn(key, supported)
            self.assertIn(key, archived)
            self.assertFalse(VariantCatalogue.isValid(key))
            with self.assertRaises(UnknownVariantError) as ctx:
                VariantCatalogue.resolve(key)
            self.assertEqual(ctx.exception.variant, key)
            self.assertFalse(VariantCatalogue.isValid(f"native-{key}"))

    def testMmapVariantsExcludePread(self) -> None:
        """Assert all mmap variants strictly include '--lsmio-no-pread' to avoid dual-handle contention."""
        mmap_keys = (
            "mmap",
            "mmap-vsort",
            "mmap-btree",
            "pool-8-mmap",
        )
        self.assertEqual(
            tuple(
                key
                for key in VariantCatalogue.supportedVariants()
                if "--lsmio-mmap" in VariantCatalogue.resolve(key).flags
            ),
            mmap_keys,
        )
        for key in mmap_keys:
            rec = VariantCatalogue.resolve(key)
            self.assertIn(
                "--lsmio-no-pread",
                rec.flags,
                f"Variant '{key}' must include '--lsmio-no-pread'",
            )
            self.assertIn(
                "--lsmio-mmap",
                rec.flags,
                f"Variant '{key}' must include '--lsmio-mmap'",
            )

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
        """Assert stripBackendPrefix strips one-segment prefixes and two-segment '<backend>-m-' prefixes are rejected."""
        two_segment_cases = [
            ("native-m-no-footer", "m-no-footer"),
            ("NATIVE-M-NO-FOOTER", "m-no-footer"),
            ("rocksdb-m-btree", "m-btree"),
            ("leveldb-m-vnosort", "m-vnosort"),
            ("adios-m-wal", "m-wal"),
            ("plugin-m-sync", "m-sync"),
            ("native-m-mmap-btree", "m-mmap-btree"),
            ("rocksdb-m-prealloc-wbuf-512m", "m-prealloc-wbuf-512m"),
        ]
        for prefixed, expected in two_segment_cases:
            stripped = VariantCatalogue.stripBackendPrefix(prefixed)
            self.assertEqual(stripped, expected)
            self.assertFalse(VariantCatalogue.isValid(prefixed))
            with self.assertRaises(UnknownVariantError) as ctx:
                VariantCatalogue.resolve(prefixed)
            self.assertEqual(ctx.exception.variant, prefixed)

        one_segment_cases = [
            ("native-no-footer", "no-footer"),
            ("NATIVE-NO-FOOTER", "no-footer"),
            ("rocksdb-btree", "btree"),
            ("ROCKSDB-btree", "btree"),
            ("leveldb-vnosort", "vnosort"),
            ("adios-wal", "wal"),
            ("plugin-sync", "sync"),
            ("native-mmap-btree", "mmap-btree"),
            ("manager-wbuf-512m", "wbuf-512m"),
            ("MANAGER-BATCH-2048", "batch-2048"),
        ]
        for prefixed, expected in one_segment_cases:
            stripped = VariantCatalogue.stripBackendPrefix(prefixed)
            self.assertEqual(stripped, expected)
            rec = VariantCatalogue.resolve(prefixed)
            self.assertEqual(rec.key, expected)

        # Base and default with prefix
        self.assertEqual(VariantCatalogue.stripBackendPrefix("native-base"), "base")
        self.assertEqual(
            VariantCatalogue.stripBackendPrefix("manager-default"), "default"
        )
        rec_base = VariantCatalogue.resolve("native-base")
        self.assertEqual(rec_base.key, "")
        self.assertEqual(rec_base.tokens, "")
        self.assertEqual(rec_base.flags, ("--lsmio-no-autotune",))
        rec_default = VariantCatalogue.resolve("manager-default")
        self.assertEqual(rec_default.key, "")
        self.assertEqual(rec_default.tokens, "")
        self.assertEqual(rec_default.flags, ("--lsmio-no-autotune",))
        self.assertEqual(VariantCatalogue.stripBackendPrefix("native-m-base"), "m-base")
        with self.assertRaises(UnknownVariantError):
            VariantCatalogue.resolve("native-m-base")

    def testUnknownVariantRaises(self) -> None:
        """Assert unrecognized variant keys raise UnknownVariantError with details."""
        for invalid_key in (
            "unknown",
            "footer-foo",
            "footer",
            "manoff-pool-8",
            "rocksdb-m-btree",
            "invalid",
            "wbuf-128m",
            "native-m-unknown",
            "12345",
            # version-<branch>-<hash>-<retired variant> is rejected like the bare key
            "version-main-abc123-footer",
            "version-main-abc123-pread",
            "version-feature-x-abc123-footer-btree",
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
        # Only LSMIO setups are accepted; the removed '-M' names raise
        for f_setup in ("NATIVE-M", "rocksdb-m", "lsmio", "BASE"):
            with self.assertRaises(UnknownSetupError):
                VariantCatalogue.getInfix(f_setup, "btree")
        # A version key ending in a supported variant that ends in a retired key resolves
        self.assertEqual(
            VariantCatalogue.resolve("version-main-abc123-no-pread").flags,
            ("--lsmio-no-autotune", "--lsmio-no-pread"),
        )
        self.assertEqual(
            VariantCatalogue.getInfix("NATIVE", "mmap-btree"),
            "native-mmap-btree",
        )
        self.assertEqual(
            VariantCatalogue.getInfix("ROCKSDB", "sync"),
            "rocksdb-sync",
        )
        self.assertEqual(
            VariantCatalogue.getInfix("MANAGER", None),
            "manager",
        )
        self.assertEqual(
            VariantCatalogue.getInfix("native", "base"),
            "native",
        )
        self.assertEqual(
            VariantCatalogue.getInfix("leveldb", "flush"),
            "leveldb-flush",
        )
        self.assertEqual(
            VariantCatalogue.getInfix("ADIOS", "default"),
            "adios",
        )
        self.assertEqual(
            VariantCatalogue.getInfix("PLUGIN", ""),
            "plugin",
        )
        self.assertEqual(
            VariantCatalogue.getInfix("", None),
            "native",
        )
        # Keyword arguments
        self.assertEqual(
            VariantCatalogue.getInfix(f_backend="NATIVE", f_key="no-footer"),
            "native-no-footer",
        )
        self.assertEqual(
            VariantCatalogue.getInfix(f_setup="ROCKSDB", f_variant="btree"),
            "rocksdb-btree",
        )
        # Retired variants cannot name a new arm
        with self.assertRaises(UnknownVariantError):
            VariantCatalogue.getInfix("NATIVE", "footer-btree")

    def testVariantRecordImmutability(self) -> None:
        """Assert INV-ARCH-6: VariantRecord instances are strictly immutable."""
        rec = VariantCatalogue.resolve("no-footer")

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
