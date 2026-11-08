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

import unittest

from lsmiotool.lib import cli, main
from lsmiotool.lib.cli import (
    COMPARE_HELP_TEXT,
    LSMIOTOOL_HELP,
    CompareCliParseError,
    CompareCliParser,
    CompareRequest,
    parseCompareArguments,
)
from lsmiotool.lib.variants import (
    VariantReverseResolver,
)


class CompareCliParserTest(unittest.TestCase):
    """Unit tests for CompareRequest and CompareCliParser."""

    def testParseAcceptsEveryBenchmarkAndInterleavedOptions(self) -> None:
        """Exercises T1 and G1: parses all 4 benchmarks with and without interleaved options."""
        # lsmio minimal
        req = parseCompareArguments(["lsmio", "/path1"])
        self.assertEqual(req.benchmark, "lsmio")
        self.assertEqual(req.folders, ("/path1",))
        self.assertEqual(req.by, "nodes")
        self.assertEqual(req.style, "bars")
        self.assertIsNone(req.metrics)
        self.assertIsNone(req.nodes)
        self.assertIsNone(req.stripes)
        self.assertIsNone(req.blocks)
        self.assertIsNone(req.output_dir)

        # ior with leading compare, multiple folders, interleaved --by, --style
        req = parseCompareArguments(
            [
                "compare",
                "ior",
                "/path1",
                "--by",
                "combinations",
                "/path2",
                "--style",
                "lines",
            ]
        )
        self.assertEqual(req.benchmark, "ior")
        self.assertEqual(req.folders, ("/path1", "/path2"))
        self.assertEqual(req.by, "combinations")
        self.assertEqual(req.style, "lines")

        # epocpp with --metrics, --nodes, --output-dir interleaved
        req = parseCompareArguments(
            [
                "epocpp",
                "--metrics",
                "runtime,cost",
                "/path1",
                "--nodes",
                "16,8",
                "--output-dir",
                "/out",
            ]
        )
        self.assertEqual(req.benchmark, "epocpp")
        self.assertEqual(req.folders, ("/path1",))
        self.assertEqual(req.metrics, ("runtime", "cost"))
        self.assertEqual(req.nodes, (8, 16))
        self.assertEqual(req.output_dir, "/out")

        # variants with --stripes, --block interleaved between folders
        req = parseCompareArguments(
            [
                "variants",
                "/path1",
                "--stripes",
                "16,4",
                "--block",
                "8M,64K",
                "/path2",
            ]
        )
        self.assertEqual(req.benchmark, "variants")
        self.assertEqual(req.folders, ("/path1", "/path2"))
        self.assertEqual(req.stripes, (4, 16))
        self.assertEqual(req.blocks, ("64K", "8M"))

    def testParseListsAndCaseNormalisation(self) -> None:
        """Exercises G2, G5, G6, G7: comma-separated lists, case-folding, and canonical ordering."""
        req = parseCompareArguments(
            [
                "EPOCPP",
                "/folder",
                "--by",
                "COMBINATIONS",
                "--style",
                "LINES",
                "--metrics",
                "RUNTIME,write,READ",
                "--nodes",
                "16,8",
                "--stripes",
                "16,4",
                "--block",
                "8m,64k",
            ]
        )
        self.assertEqual(req.benchmark, "epocpp")
        self.assertEqual(req.by, "combinations")
        self.assertEqual(req.style, "lines")
        self.assertEqual(req.metrics, ("runtime", "write", "read"))
        self.assertEqual(req.nodes, (8, 16))
        self.assertEqual(req.stripes, (4, 16))
        self.assertEqual(req.blocks, ("64K", "8M"))

    def testParseOnlyALeadingCompareIsTheCommandWord(self) -> None:
        """Section 4.1 rule: only leading compare is command word; compare after benchmark is a folder."""
        req1 = parseCompareArguments(["compare", "lsmio", "compare"])
        self.assertEqual(req1.benchmark, "lsmio")
        self.assertEqual(req1.folders, ("compare",))

        req2 = parseCompareArguments(["lsmio", "/a"])
        self.assertEqual(req2.benchmark, "lsmio")
        self.assertEqual(req2.folders, ("/a",))

    def testParseRefusals(self) -> None:
        """T2, G3-G8: table of parse refusals."""
        cases = [
            ([], "Missing benchmark"),
            (["nodes", "/a", "read"], "'compare nodes' was removed"),
            (["scaling", "/a"], "Invalid benchmark"),
            (["lsmio"], "Missing <folder>"),
            (["lsmio", "/a", "--all"], "'--all' was removed"),
            (["lsmio", "/a", "--foo"], "Unknown option"),
            (["lsmio", "/a", "--nodes=8"], "Prohibit '--nodes=value'"),
            (["lsmio", "/a", "--foo=1"], "Unknown option"),
            (["lsmio", "/a", "--nodes", "8", "--nodes", "16"], "Duplicate '--nodes'"),
            (["lsmio", "/a", "--nodes"], "Missing value after '--nodes'"),
            (["lsmio", "/a", "--output-dir", "-x"], "option-like token"),
            (["lsmio", "/a", "--output-dir", " "], "cannot be empty"),
            (["lsmio", "/a", "--nodes", "8,,16"], "empty item"),
            (["lsmio", "/a", "--nodes", "8,8"], "repeated item"),
            (["lsmio", "/a", "--nodes", "0"], "invalid node count"),
            (["lsmio", "/a", "--nodes", "x"], "invalid node count"),
            (["lsmio", "/a", "--nodes", "²"], "invalid node count"),
            (["lsmio", "/a", "--nodes", "８"], "invalid node count"),
            (["lsmio", "/a", "--stripes", "8"], "invalid stripe count"),
            (["lsmio", "/a", "--stripes", "٤"], "invalid stripe count"),
            (["lsmio", "/a", "--block", "2M"], "invalid block size"),
            (["lsmio", "/a", "--by", "x"], "Invalid --by value"),
            (["lsmio", "/a", "--style", "x"], "Invalid --style value"),
            (["lsmio", "/a", "--metrics", "cost"], "invalid metric 'cost'"),
            (["ior", "/a", "--metrics", "cost"], "invalid metric 'cost'"),
            (["variants", "/a", "--metrics", "cost"], "invalid metric 'cost'"),
            (["lsmio", "/a", "read"], "is not a folder"),
            (["lsmio", "/a", "16"], "is not a folder"),
            (["lsmio", "/a", "1m"], "is not a folder"),
            (["lsmio", "/a", "runtime"], "is not a folder"),
            (["compare-archive", "/a"], "'compare-archive' was removed"),
            (["lsmio", ""], "Folder path cannot be empty"),
        ]
        for argv, substr in cases:
            with (
                self.subTest(argv=argv, substr=substr),
                self.assertRaises(CompareCliParseError) as ctx,
            ):
                parseCompareArguments(argv)
            self.assertIn(substr, str(ctx.exception))

    def testParseRefusesNonStringArgv(self) -> None:
        """Non-iterable, string, bytes, or iterable containing non-strings raises CompareCliParseError."""
        for bad_argv in (None, "string", b"bytes", ["lsmio", "/a", 123]):
            with (
                self.subTest(bad_argv=bad_argv),
                self.assertRaises(CompareCliParseError),
            ):
                parseCompareArguments(bad_argv)  # type: ignore

    def testCompareHelpTextContract(self) -> None:
        """T3: Verifies COMPARE_HELP_TEXT and LSMIOTOOL_HELP contracts."""
        norm_help = " ".join(COMPARE_HELP_TEXT.split())
        self.assertIn(
            "Usage: lsmiotool compare <lsmio|ior|epocpp|variants> <folder>",
            norm_help,
        )
        self.assertIn("lsmio a backends archive", norm_help)
        self.assertIn("ior an IOR archive", norm_help)
        self.assertIn("epocpp an epocpp archive", norm_help)
        self.assertIn("variants a variants archive", norm_help)
        self.assertIn("--by nodes|combinations", norm_help)
        self.assertIn("--style bars|lines", norm_help)
        self.assertIn("--metrics <list>", norm_help)
        self.assertIn("--nodes <list>", norm_help)
        self.assertIn("--stripes <list>", norm_help)
        self.assertIn("--block <list>", norm_help)
        self.assertIn("--output-dir <dir>", norm_help)
        self.assertIn("variants: x is the variants", norm_help)
        self.assertIn("drawn as a gap and named in a warning", norm_help)
        self.assertIn("compare-<scale>-<benchmark>[-<names>]-by-nodes.png", norm_help)
        self.assertIn(
            "compare-<scale>-<benchmark>[-<names>]-by-combinations-<nodes>.png",
            norm_help,
        )
        self.assertIn("Exit status:", norm_help)

        self.assertIn(
            "compare <lsmio|ior|epocpp|variants> <folder> ... [options]",
            LSMIOTOOL_HELP,
        )
        self.assertFalse(hasattr(cli, "COMPARE_ARCHIVE_HELP_TEXT"))

    def testRemovedInterfacesAreGone(self) -> None:
        """T18: Asserts that legacy compare interfaces and submodes are gone."""
        removed_cli = (
            "CompareNodesRequest",
            "CompareVariantsRequest",
            "CompareArchiveRequest",
            "CompareArchiveCliParser",
            "CompareArchiveCliParseError",
            "parseCompareArchiveArguments",
            "COMPARE_ARCHIVE_HELP_TEXT",
            "_parseNodes",
            "_parseVariants",
        )
        for name in removed_cli:
            self.assertFalse(
                hasattr(cli, name),
                f"lsmiotool.lib.cli.{name} should have been removed",
            )

        removed_parser_consts = (
            "WORKLOAD_PERMUTATIONS",
            "VALID_SUBMODES",
            "VALID_OPERATIONS",
            "VALID_OPERATIONS_EXPANDED",
        )
        for name in removed_parser_consts:
            self.assertFalse(
                hasattr(CompareCliParser, name),
                f"CompareCliParser.{name} should have been removed",
            )

        removed_main = (
            "CompareNodesMain",
            "CompareVariantsMain",
            "CompareArchiveMain",
            "PairedVariantRun",
        )
        for name in removed_main:
            self.assertFalse(
                hasattr(main, name),
                f"lsmiotool.lib.main.{name} should have been removed",
            )

    def testVariantReverseResolutionTruthTable(self) -> None:
        """Exhaustively validates all 10 canonical rows of the Reverse-Resolution Truth Table."""
        # Row 1: outputs-native -> backend 'native', variant 'default', collision None, display 'default'
        r1 = VariantReverseResolver.resolve("outputs-native")
        self.assertIsNotNone(r1)
        self.assertEqual(r1.backend, "native")
        self.assertEqual(r1.variant, "default")
        self.assertIsNone(r1.collision)
        self.assertEqual(r1.display_label, "default")
        self.assertEqual(r1.raw_directory, "outputs-native")

        # Row 2: outputs-native-1 -> backend 'native', variant 'default', collision '1', display 'default-1'
        r2 = VariantReverseResolver.resolve("outputs-native-1")
        self.assertIsNotNone(r2)
        self.assertEqual(r2.backend, "native")
        self.assertEqual(r2.variant, "default")
        self.assertEqual(r2.collision, "1")
        self.assertEqual(r2.display_label, "default-1")

        # Row 3: outputs-native-footer -> backend 'native', variant 'footer', collision None, display 'footer'
        r3 = VariantReverseResolver.resolve("outputs-native-footer")
        self.assertIsNotNone(r3)
        self.assertEqual(r3.backend, "native")
        self.assertEqual(r3.variant, "footer")
        self.assertIsNone(r3.collision)
        self.assertEqual(r3.display_label, "footer")

        # Row 4: outputs-native-footer-2 -> backend 'native', variant 'footer', collision '2', display 'footer-2'
        r4 = VariantReverseResolver.resolve("outputs-native-footer-2")
        self.assertIsNotNone(r4)
        self.assertEqual(r4.backend, "native")
        self.assertEqual(r4.variant, "footer")
        self.assertEqual(r4.collision, "2")
        self.assertEqual(r4.display_label, "footer-2")

        # Row 5: outputs-native-footer-btree -> backend 'native', variant 'footer-btree', collision None, display 'footer-btree'
        r5 = VariantReverseResolver.resolve("outputs-native-footer-btree")
        self.assertIsNotNone(r5)
        self.assertEqual(r5.backend, "native")
        self.assertEqual(r5.variant, "footer-btree")
        self.assertIsNone(r5.collision)
        self.assertEqual(r5.display_label, "footer-btree")

        # Row 6: outputs-native-pool-8 -> backend 'native', variant 'pool-8', collision None, display 'pool-8'
        r6 = VariantReverseResolver.resolve("outputs-native-pool-8")
        self.assertIsNotNone(r6)
        self.assertEqual(r6.backend, "native")
        self.assertEqual(r6.variant, "pool-8")
        self.assertIsNone(r6.collision)
        self.assertEqual(r6.display_label, "pool-8")

        # Row 7: outputs-native-pool-8-3 -> backend 'native', variant 'pool-8', collision '3', display 'pool-8-3'
        r7 = VariantReverseResolver.resolve("outputs-native-pool-8-3")
        self.assertIsNotNone(r7)
        self.assertEqual(r7.backend, "native")
        self.assertEqual(r7.variant, "pool-8")
        self.assertEqual(r7.collision, "3")
        self.assertEqual(r7.display_label, "pool-8-3")

        # Row 8: outputs-adios -> backend 'adios', variant 'default', collision None, display 'adios'
        r8 = VariantReverseResolver.resolve("outputs-adios")
        self.assertIsNotNone(r8)
        self.assertEqual(r8.backend, "adios")
        self.assertEqual(r8.variant, "default")
        self.assertIsNone(r8.collision)
        self.assertEqual(r8.display_label, "adios")

        # Row 9: outputs-adios-2 -> backend 'adios', variant 'default', collision '2', display 'adios-2'
        r9 = VariantReverseResolver.resolve("outputs-adios-2")
        self.assertIsNotNone(r9)
        self.assertEqual(r9.backend, "adios")
        self.assertEqual(r9.variant, "default")
        self.assertEqual(r9.collision, "2")
        self.assertEqual(r9.display_label, "adios-2")

        # Row 10: outputs-adios-footer-1 -> backend 'adios', variant 'footer', collision '1', display 'adios-footer-1'
        r10 = VariantReverseResolver.resolve("outputs-adios-footer-1")
        self.assertIsNotNone(r10)
        self.assertEqual(r10.backend, "adios")
        self.assertEqual(r10.variant, "footer")
        self.assertEqual(r10.collision, "1")
        self.assertEqual(r10.display_label, "adios-footer-1")

    def testNonMatchingDirectoryIgnored(self) -> None:
        """Asserts that directories not matching 'outputs-*' return None."""
        self.assertIsNone(VariantReverseResolver.resolve("some-random-folder"))
        self.assertIsNone(VariantReverseResolver.resolve("inputs-native"))
        self.assertIsNone(VariantReverseResolver.resolve("outputs"))
        self.assertIsNone(VariantReverseResolver.resolve("output-native"))
        self.assertIsNone(VariantReverseResolver.resolve("outputs_native"))
        self.assertIsNone(VariantReverseResolver.resolve("archive"))

    def testCompareParserConstants(self) -> None:
        """Asserts the exact tuples and dicts of the new constants in CompareCliParser."""
        self.assertEqual(
            CompareCliParser.VALID_BENCHMARKS,
            ("lsmio", "ior", "epocpp", "variants"),
        )
        self.assertEqual(
            CompareCliParser.BENCHMARK_METRICS,
            {
                "lsmio": ("write", "read"),
                "ior": ("write", "read"),
                "variants": ("write", "read"),
                "epocpp": ("runtime", "cost", "write", "read"),
            },
        )
        self.assertEqual(
            CompareCliParser.DEFAULT_METRICS,
            {
                "lsmio": ("write", "read"),
                "ior": ("write", "read"),
                "variants": ("write", "read"),
                "epocpp": ("runtime", "write", "read"),
            },
        )
        self.assertEqual(
            CompareCliParser.COMBINATIONS,
            (
                (4, "64K"),
                (4, "1M"),
                (4, "8M"),
                (16, "64K"),
                (16, "1M"),
                (16, "8M"),
            ),
        )
        self.assertEqual(CompareCliParser.VALID_BY, ("nodes", "combinations"))
        self.assertEqual(CompareCliParser.VALID_STYLES, ("bars", "lines"))
        self.assertEqual(CompareCliParser.VALID_STRIPES, (4, 16))
        self.assertEqual(CompareCliParser.VALID_BLOCKSIZES, ("64K", "1M", "8M"))

    def testCompareRequestDefaultsAndToDict(self) -> None:
        """CompareRequest('lsmio', ['/a']) defaults and toDict structure."""
        req = CompareRequest("lsmio", ["/a"])
        self.assertEqual(req.benchmark, "lsmio")
        self.assertEqual(req.folders, ("/a",))
        self.assertEqual(req.by, "nodes")
        self.assertEqual(req.style, "bars")
        self.assertIsNone(req.metrics)
        self.assertIsNone(req.nodes)
        self.assertIsNone(req.stripes)
        self.assertIsNone(req.blocks)
        self.assertIsNone(req.output_dir)

        expected_dict = {
            "benchmark": "lsmio",
            "folders": ["/a"],
            "by": "nodes",
            "style": "bars",
            "metrics": None,
            "nodes": None,
            "stripes": None,
            "blocks": None,
            "output_dir": None,
        }
        self.assertEqual(req.toDict(), expected_dict)
        self.assertTrue(repr(req).startswith("CompareRequest("))

    def testCompareRequestNormalisesAndStoresSetsCanonically(self) -> None:
        """Case normalisation and canonical ordering of sets in CompareRequest."""
        req = CompareRequest(
            f_benchmark=" EPOCPP ",
            f_folders=[" /b ", "/a", "/b"],
            f_by="Combinations",
            f_style="LINES",
            f_metrics=("Read", "write"),
            f_nodes=(16, 8),
            f_stripes=(16, 4),
            f_blocks=("8m", "64k"),
            f_output_dir=" out ",
        )
        self.assertEqual(req.benchmark, "epocpp")
        self.assertEqual(req.folders, ("/b", "/a", "/b"))
        self.assertEqual(req.by, "combinations")
        self.assertEqual(req.style, "lines")
        self.assertEqual(req.metrics, ("read", "write"))
        self.assertEqual(req.nodes, (8, 16))
        self.assertEqual(req.stripes, (4, 16))
        self.assertEqual(req.blocks, ("64K", "8M"))
        self.assertEqual(req.output_dir, "out")

    def testCompareRequestEqualityAndHash(self) -> None:
        """Equality and hashing across permutations, metrics, folders, and types."""
        req1 = CompareRequest(
            "lsmio",
            ["/a"],
            f_nodes=(8, 16),
            f_stripes=(4, 16),
            f_blocks=("64K", "8M"),
        )
        req2 = CompareRequest(
            "lsmio",
            ["/a"],
            f_nodes=(16, 8),
            f_stripes=(16, 4),
            f_blocks=("8M", "64K"),
        )
        self.assertEqual(req1, req2)
        self.assertEqual(hash(req1), hash(req2))

        req3 = CompareRequest("lsmio", ["/a"], f_metrics=("write", "read"))
        self.assertNotEqual(req1, req3)

        req4 = CompareRequest("lsmio", ["/a", "/b"])
        req5 = CompareRequest("lsmio", ["/b", "/a"])
        self.assertNotEqual(req4, req5)

        self.assertNotEqual(req1, "lsmio")
        self.assertNotEqual(req1, 42)
        self.assertNotEqual(req1, None)

    def testCompareRequestIsImmutable(self) -> None:
        """Setting or deleting attributes on CompareRequest raises AttributeError."""
        req = CompareRequest("lsmio", ["/a"])
        with self.assertRaises(AttributeError):
            req.benchmark = "ior"
        with self.assertRaises(AttributeError):
            req.m_benchmark = "ior"
        with self.assertRaises(AttributeError):
            del req.benchmark
        with self.assertRaises(AttributeError):
            del req.m_benchmark
        with self.assertRaises(AttributeError):
            req.unknown_attribute = "test"

        unfrozen = object.__new__(CompareRequest)
        unfrozen.m_benchmark = "ior"
        self.assertEqual(unfrozen.m_benchmark, "ior")
        del unfrozen.m_benchmark

    def testCompareRequestRejectsInvalidValues(self) -> None:
        """Asserts that invalid inputs raise ValueError with appropriate subTests."""
        # benchmark "nodes", "", None
        for val in ("nodes", "", None):
            with self.subTest(case="benchmark", val=val), self.assertRaises(ValueError):
                CompareRequest(val, ["/a"])

        # folders "abc", (), ("",), (" ",), (1,)
        for val in ("abc", (), ("",), (" ",), (1,)):
            with self.subTest(case="folders", val=val), self.assertRaises(ValueError):
                CompareRequest("lsmio", val)

        # by "x"
        with self.subTest(case="by", val="x"), self.assertRaises(ValueError):
            CompareRequest("lsmio", ["/a"], f_by="x")

        # style "x"
        with self.subTest(case="style", val="x"), self.assertRaises(ValueError):
            CompareRequest("lsmio", ["/a"], f_style="x")

        # metrics (), ("cost",) for lsmio, ior and variants, ("write", "WRITE"), ("speed",)
        for bm in ("lsmio", "ior", "variants"):
            with (
                self.subTest(case="metrics_cost", benchmark=bm),
                self.assertRaises(ValueError),
            ):
                CompareRequest(bm, ["/a"], f_metrics=("cost",))

        for val in ((), ("write", "WRITE"), ("speed",)):
            with self.subTest(case="metrics", val=val), self.assertRaises(ValueError):
                CompareRequest("lsmio", ["/a"], f_metrics=val)

        # nodes (), (0,), (-1,), (True,), ("8",), (8, 8)
        for val in ((), (0,), (-1,), (True,), ("8",), (8, 8)):
            with self.subTest(case="nodes", val=val), self.assertRaises(ValueError):
                CompareRequest("lsmio", ["/a"], f_nodes=val)

        # stripes (8,), (4, 4), ()
        for val in ((8,), (4, 4), ()):
            with self.subTest(case="stripes", val=val), self.assertRaises(ValueError):
                CompareRequest("lsmio", ["/a"], f_stripes=val)

        # blocks ("2M",), ("1M", "1m"), ()
        for val in (("2M",), ("1M", "1m"), ()):
            with self.subTest(case="blocks", val=val), self.assertRaises(ValueError):
                CompareRequest("lsmio", ["/a"], f_blocks=val)

        # output_dir "", " ", 5
        for val in ("", " ", 5):
            with (
                self.subTest(case="output_dir", val=val),
                self.assertRaises(ValueError),
            ):
                CompareRequest("lsmio", ["/a"], f_output_dir=val)


if __name__ == "__main__":
    unittest.main()
