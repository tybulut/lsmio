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

from lsmiotool.lib.cli import (
    COMPARE_ARCHIVE_HELP_TEXT,
    COMPARE_HELP_TEXT,
    LSMIOTOOL_HELP,
    CliParseError,
    CompareArchiveCliParseError,
    CompareArchiveCliParser,
    CompareArchiveRequest,
    CompareCliParseError,
    CompareCliParser,
    CompareNodesRequest,
    CompareVariantsRequest,
    parseCompareArchiveArguments,
    parseCompareArguments,
)
from lsmiotool.lib.variants import (
    VariantResolutionResult,
    VariantReverseResolver,
)


class CompareCliParserTest(unittest.TestCase):
    """Unit tests for CompareNodesRequest, CompareVariantsRequest, and CompareCliParser."""

    def testCompareNodesRequestValueObject(self) -> None:
        """Validates CompareNodesRequest construction, properties, immutability, toDict, repr, eq, and hash."""
        req = CompareNodesRequest(
            f_folder="/path/to/bench",
            f_op="read",
            f_stripes=16,
            f_blocksize="8M",
            f_output_dir="/tmp/plots",
        )

        # Properties
        self.assertEqual(req.submode, "nodes")
        self.assertEqual(req.folder, "/path/to/bench")
        self.assertEqual(req.op, "read")
        self.assertEqual(req.stripes, 16)
        self.assertEqual(req.blocksize, "8M")
        self.assertEqual(req.output_dir, "/tmp/plots")
        self.assertEqual(req.outputDir, "/tmp/plots")

        # Defaults
        req_def = CompareNodesRequest(
            f_folder="/path/to/bench",
            f_op="write",
        )
        self.assertEqual(req_def.submode, "nodes")
        self.assertEqual(req_def.folder, "/path/to/bench")
        self.assertEqual(req_def.op, "write")
        self.assertEqual(req_def.stripes, 4)
        self.assertEqual(req_def.blocksize, "1M")
        self.assertIsNone(req_def.output_dir)
        self.assertIsNone(req_def.outputDir)

        # Normalization
        req_norm = CompareNodesRequest(
            f_folder="  /path/to/bench  ",
            f_op="  READ  ",
            f_stripes=4,
            f_blocksize="  64k  ",
            f_output_dir="  /tmp/out  ",
        )
        self.assertEqual(req_norm.folder, "/path/to/bench")
        self.assertEqual(req_norm.op, "read")
        self.assertEqual(req_norm.blocksize, "64K")
        self.assertEqual(req_norm.output_dir, "/tmp/out")

        # Immutability guards
        with self.assertRaises(AttributeError):
            req.m_op = "write"  # type: ignore
        with self.assertRaises(AttributeError):
            req.op = "write"  # type: ignore
        with self.assertRaises(AttributeError):
            req.m_stripes = 4  # type: ignore
        with self.assertRaises(AttributeError):
            del req.m_stripes  # type: ignore
        with self.assertRaises(AttributeError):
            del req.stripes  # type: ignore

        # toDict serialization
        expected_dict = {
            "submode": "nodes",
            "folder": "/path/to/bench",
            "op": "read",
            "stripes": 16,
            "blocksize": "8M",
            "output_dir": "/tmp/plots",
        }
        self.assertEqual(req.toDict(), expected_dict)

        # __repr__
        self.assertIn("CompareNodesRequest(", repr(req))
        self.assertIn("folder='/path/to/bench'", repr(req))
        self.assertIn("op='read'", repr(req))
        self.assertIn("stripes=16", repr(req))
        self.assertIn("blocksize='8M'", repr(req))
        self.assertIn("output_dir='/tmp/plots'", repr(req))

        # __eq__ and __hash__
        req_same = CompareNodesRequest(
            f_folder="/path/to/bench",
            f_op="READ",
            f_stripes=16,
            f_blocksize="8m",
            f_output_dir="/tmp/plots",
        )
        self.assertEqual(req, req_same)
        self.assertEqual(hash(req), hash(req_same))
        self.assertNotEqual(req, req_def)
        self.assertFalse(req == "non_request_object")
        self.assertFalse(req == 123)

        req_set = {req, req_same, req_def}
        self.assertEqual(len(req_set), 2)

        # Constructor validation errors
        with self.assertRaises(ValueError):
            CompareNodesRequest(f_folder="", f_op="read")
        with self.assertRaises(ValueError):
            CompareNodesRequest(f_folder="   ", f_op="read")
        with self.assertRaises(ValueError):
            CompareNodesRequest(f_folder=None, f_op="read")  # type: ignore
        with self.assertRaises(ValueError):
            CompareNodesRequest(f_folder="/path", f_op="")
        with self.assertRaises(ValueError):
            CompareNodesRequest(f_folder="/path", f_op="both")
        with self.assertRaises(ValueError):
            CompareNodesRequest(f_folder="/path", f_op="delete")
        with self.assertRaises(ValueError):
            CompareNodesRequest(f_folder="/path", f_op="read", f_stripes=0)
        with self.assertRaises(ValueError):
            CompareNodesRequest(f_folder="/path", f_op="read", f_stripes=-1)
        with self.assertRaises(ValueError):
            CompareNodesRequest(f_folder="/path", f_op="read", f_stripes=True)  # type: ignore
        with self.assertRaises(ValueError):
            CompareNodesRequest(f_folder="/path", f_op="read", f_blocksize="2M")
        with self.assertRaises(ValueError):
            CompareNodesRequest(f_folder="/path", f_op="read", f_blocksize="")
        with self.assertRaises(ValueError):
            CompareNodesRequest(f_folder="/path", f_op="read", f_output_dir="")
        with self.assertRaises(ValueError):
            CompareNodesRequest(f_folder="/path", f_op="read", f_output_dir="   ")

    def testCompareVariantsRequestValueObject(self) -> None:
        """Validates CompareVariantsRequest construction, properties, immutability, toDict, repr, eq, and hash."""
        req = CompareVariantsRequest(
            f_archive_folder="/path/to/archive",
            f_op="read",
            f_stripes=16,
            f_blocksize="8M",
            f_all=True,
            f_output_dir="/tmp/charts",
        )

        # Properties
        self.assertEqual(req.submode, "variants")
        self.assertEqual(req.archive_folder, "/path/to/archive")
        self.assertEqual(req.archiveFolder, "/path/to/archive")
        self.assertEqual(req.folder, "/path/to/archive")
        self.assertEqual(req.op, "read")
        self.assertEqual(req.stripes, 16)
        self.assertEqual(req.blocksize, "8M")
        self.assertTrue(req.all)
        self.assertEqual(req.output_dir, "/tmp/charts")
        self.assertEqual(req.outputDir, "/tmp/charts")

        # Backward compatibility alias
        self.assertIs(CompareArchiveRequest, CompareVariantsRequest)
        req_alias = CompareArchiveRequest(f_archive_folder="/path/to/archive")
        self.assertIsInstance(req_alias, CompareVariantsRequest)

        # Defaults
        req_default = CompareVariantsRequest(f_archive_folder="/path/to/archive")
        self.assertEqual(req_default.submode, "variants")
        self.assertEqual(req_default.archive_folder, "/path/to/archive")
        self.assertEqual(req_default.folder, "/path/to/archive")
        self.assertEqual(req_default.op, "both")
        self.assertEqual(req_default.stripes, 4)
        self.assertEqual(req_default.blocksize, "1M")
        self.assertFalse(req_default.all)
        self.assertIsNone(req_default.output_dir)

        # Immutability guards
        with self.assertRaises(AttributeError):
            req.m_op = "write"  # type: ignore
        with self.assertRaises(AttributeError):
            req.op = "write"  # type: ignore
        with self.assertRaises(AttributeError):
            req.m_stripes = 4  # type: ignore
        with self.assertRaises(AttributeError):
            del req.m_stripes  # type: ignore
        with self.assertRaises(AttributeError):
            del req.stripes  # type: ignore

        # toDict serialization
        expected_dict = {
            "submode": "variants",
            "archive_folder": "/path/to/archive",
            "folder": "/path/to/archive",
            "op": "read",
            "stripes": 16,
            "blocksize": "8M",
            "all": True,
            "output_dir": "/tmp/charts",
        }
        self.assertEqual(req.toDict(), expected_dict)

        # __repr__
        self.assertIn("CompareVariantsRequest(", repr(req))
        self.assertIn("archive_folder='/path/to/archive'", repr(req))
        self.assertIn("op='read'", repr(req))
        self.assertIn("stripes=16", repr(req))
        self.assertIn("blocksize='8M'", repr(req))
        self.assertIn("all=True", repr(req))
        self.assertIn("output_dir='/tmp/charts'", repr(req))

        # __eq__ and __hash__
        req_same = CompareVariantsRequest(
            f_archive_folder="/path/to/archive",
            f_op="READ",
            f_stripes=16,
            f_blocksize="8m",
            f_all=True,
            f_output_dir="/tmp/charts",
        )
        self.assertEqual(req, req_same)
        self.assertEqual(hash(req), hash(req_same))
        self.assertNotEqual(req, req_default)
        self.assertFalse(req == "non_request_object")
        self.assertFalse(req == 123)

        req_set = {req, req_same, req_default}
        self.assertEqual(len(req_set), 2)

        # Constructor validation errors
        with self.assertRaises(ValueError):
            CompareVariantsRequest(f_archive_folder="")
        with self.assertRaises(ValueError):
            CompareVariantsRequest(f_archive_folder="   ")
        with self.assertRaises(ValueError):
            CompareVariantsRequest(f_archive_folder=None)  # type: ignore
        with self.assertRaises(ValueError):
            CompareVariantsRequest(f_archive_folder="/path", f_op="delete")
        with self.assertRaises(ValueError):
            CompareVariantsRequest(f_archive_folder="/path", f_op="")
        with self.assertRaises(ValueError):
            CompareVariantsRequest(f_archive_folder="/path", f_stripes=8)
        with self.assertRaises(ValueError):
            CompareVariantsRequest(f_archive_folder="/path", f_stripes=True)  # type: ignore
        with self.assertRaises(ValueError):
            CompareVariantsRequest(f_archive_folder="/path", f_blocksize="2M")
        with self.assertRaises(ValueError):
            CompareVariantsRequest(f_archive_folder="/path", f_blocksize="")
        with self.assertRaises(ValueError):
            CompareVariantsRequest(f_archive_folder="/path", f_all="yes")  # type: ignore
        with self.assertRaises(ValueError):
            CompareVariantsRequest(f_archive_folder="/path", f_output_dir="")
        with self.assertRaises(ValueError):
            CompareVariantsRequest(f_archive_folder="/path", f_output_dir="   ")

    def testParseCompareNodesValidArguments(self) -> None:
        """Validates parsing for 'compare nodes' grammar."""
        # Minimal positional: nodes <folder> <op>
        req1 = parseCompareArguments(["nodes", "/path/to/bench", "read"])
        self.assertIsInstance(req1, CompareNodesRequest)
        self.assertEqual(req1.submode, "nodes")
        self.assertEqual(req1.folder, "/path/to/bench")
        self.assertEqual(req1.op, "read")
        self.assertEqual(req1.stripes, 4)
        self.assertEqual(req1.blocksize, "1M")
        self.assertIsNone(req1.output_dir)

        # Direct parser invocation
        req1_direct = CompareCliParser.parse(["nodes", "/path/to/bench", "read"])
        self.assertEqual(req1_direct, req1)

        # Leading 'compare' token
        req1_cmd = parseCompareArguments(["compare", "nodes", "/path/to/bench", "read"])
        self.assertEqual(req1_cmd, req1)

        # Explicit stripes and blocksize
        req_stripes_bs = parseCompareArguments([
            "nodes",
            "/path/to/bench",
            "write",
            "16",
            "8M",
        ])
        self.assertEqual(req_stripes_bs.op, "write")
        self.assertEqual(req_stripes_bs.stripes, 16)
        self.assertEqual(req_stripes_bs.blocksize, "8M")

        # Case normalization for op and blocksize
        req_case = parseCompareArguments([
            "nodes",
            "/path/to/bench",
            "WRITE",
            "4",
            "64k",
        ])
        self.assertEqual(req_case.op, "write")
        self.assertEqual(req_case.blocksize, "64K")

        # With --output-dir
        req_out = parseCompareArguments([
            "nodes",
            "/path/to/bench",
            "read",
            "--output-dir",
            "/tmp/plots",
        ])
        self.assertEqual(req_out.output_dir, "/tmp/plots")
        self.assertEqual(req_out.outputDir, "/tmp/plots")

        # Full options permutation
        req_full = parseCompareArguments([
            "nodes",
            "/path/to/bench",
            "read",
            "16",
            "8M",
            "--output-dir",
            "/tmp/plots",
        ])
        self.assertEqual(req_full.folder, "/path/to/bench")
        self.assertEqual(req_full.op, "read")
        self.assertEqual(req_full.stripes, 16)
        self.assertEqual(req_full.blocksize, "8M")
        self.assertEqual(req_full.output_dir, "/tmp/plots")

    def testParseCompareVariantsValidArguments(self) -> None:
        """Validates parsing for 'compare variants' grammar."""
        # Minimal positional: variants <archive_folder>
        req1 = parseCompareArguments(["variants", "/path/to/archive"])
        self.assertIsInstance(req1, CompareVariantsRequest)
        self.assertEqual(req1.submode, "variants")
        self.assertEqual(req1.archive_folder, "/path/to/archive")
        self.assertEqual(req1.folder, "/path/to/archive")
        self.assertEqual(req1.op, "both")
        self.assertEqual(req1.stripes, 4)
        self.assertEqual(req1.blocksize, "1M")
        self.assertFalse(req1.all)
        self.assertIsNone(req1.output_dir)

        # Leading 'compare' token
        req1_cmd = parseCompareArguments(["compare", "variants", "/path/to/archive"])
        self.assertEqual(req1_cmd, req1)

        # Positional operations: read, write, both
        req_read = parseCompareArguments(["variants", "/path/to/archive", "read"])
        self.assertEqual(req_read.op, "read")
        req_write = parseCompareArguments(["variants", "/path/to/archive", "WRITE"])
        self.assertEqual(req_write.op, "write")
        req_both = parseCompareArguments(["variants", "/path/to/archive", "both"])
        self.assertEqual(req_both.op, "both")

        # Positional stripes and blocksize
        req_s_bs = parseCompareArguments([
            "variants",
            "/path/to/archive",
            "read",
            "16",
            "64K",
        ])
        self.assertEqual(req_s_bs.stripes, 16)
        self.assertEqual(req_s_bs.blocksize, "64K")

        # With --all and --output-dir
        req_all_out = parseCompareArguments([
            "variants",
            "/path/to/archive",
            "read",
            "16",
            "8M",
            "--all",
            "--output-dir",
            "/tmp/plots",
        ])
        self.assertTrue(req_all_out.all)
        self.assertEqual(req_all_out.output_dir, "/tmp/plots")

        # Compatibility function parseCompareArchiveArguments
        req_compat = parseCompareArchiveArguments([
            "/path/to/archive",
            "read",
            "16",
            "--all",
        ])
        self.assertIsInstance(req_compat, CompareVariantsRequest)
        self.assertEqual(req_compat.archive_folder, "/path/to/archive")
        self.assertEqual(req_compat.op, "read")
        self.assertEqual(req_compat.stripes, 16)
        self.assertTrue(req_compat.all)

    def testParseCompareErrorsZeroAliasAndFallback(self) -> None:
        """Validates strict rejection of missing submode, aliases, bare folder fallback (INV-ARCH-1, INV-ARCH-2)."""
        # Missing submode token
        with self.assertRaises(CompareCliParseError) as ctx_empty:
            parseCompareArguments([])
        self.assertIn("Missing required submode", str(ctx_empty.exception))

        with self.assertRaises(CompareCliParseError) as ctx_cmp_only:
            parseCompareArguments(["compare"])
        self.assertIn("Missing required submode", str(ctx_cmp_only.exception))

        # Bare folder fallback (legacy command syntax)
        with self.assertRaises(CompareCliParseError) as ctx_bare1:
            parseCompareArguments(["/path/to/bench", "read"])
        self.assertIn("Invalid submode '/path/to/bench'", str(ctx_bare1.exception))
        self.assertIn("Must be 'nodes' or 'variants'", str(ctx_bare1.exception))

        with self.assertRaises(CompareCliParseError) as ctx_bare2:
            parseCompareArguments(["compare", "viking2/", "read"])
        self.assertIn("Invalid submode 'viking2/'", str(ctx_bare2.exception))
        self.assertIn("Must be 'nodes' or 'variants'", str(ctx_bare2.exception))

        # Prohibited alias 'scaling'
        with self.assertRaises(CompareCliParseError) as ctx_scaling:
            parseCompareArguments(["scaling", "/path/to/bench", "read"])
        self.assertIn("Invalid submode 'scaling'", str(ctx_scaling.exception))
        self.assertIn("Must be 'nodes' or 'variants'", str(ctx_scaling.exception))

        with self.assertRaises(CompareCliParseError) as ctx_scaling_cmd:
            parseCompareArguments(["compare", "scaling", "/path/to/bench", "read"])
        self.assertIn("Invalid submode 'scaling'", str(ctx_scaling_cmd.exception))

        # Prohibited alias 'archive'
        with self.assertRaises(CompareCliParseError) as ctx_archive:
            parseCompareArguments(["archive", "/path/to/archive"])
        self.assertIn("Invalid submode 'archive'", str(ctx_archive.exception))

        with self.assertRaises(CompareCliParseError) as ctx_archive_cmd:
            parseCompareArguments(["compare", "archive", "/path/to/archive"])
        self.assertIn("Invalid submode 'archive'", str(ctx_archive_cmd.exception))

        # Option flag placed before submode
        with self.assertRaises(CompareCliParseError) as ctx_opt_sub:
            parseCompareArguments(["--output-dir", "/tmp", "nodes", "/path/to/bench", "read"])
        self.assertIn("Invalid submode '--output-dir'", str(ctx_opt_sub.exception))

        with self.assertRaises(CompareCliParseError) as ctx_all_first:
            parseCompareArguments(["--all"])
        self.assertIn("Invalid submode '--all'", str(ctx_all_first.exception))

    def testParseCompareNodesGrammarErrors(self) -> None:
        """Validates error cases specific to 'compare nodes' grammar."""
        # Missing folder
        with self.assertRaises(CompareCliParseError) as ctx:
            parseCompareArguments(["nodes"])
        self.assertIn("Missing required positional argument: <folder>", str(ctx.exception))

        # Option placed before folder
        with self.assertRaises(CompareCliParseError) as ctx:
            parseCompareArguments(["nodes", "--output-dir", "/tmp", "/path", "read"])
        self.assertIn("Unexpected option '--output-dir' placed before positional argument <folder>", str(ctx.exception))

        # Missing operation
        with self.assertRaises(CompareCliParseError) as ctx:
            parseCompareArguments(["nodes", "/path/to/bench"])
        self.assertIn("Missing required positional argument: <read|write>", str(ctx.exception))

        # Invalid operation (both is rejected in nodes mode)
        with self.assertRaises(CompareCliParseError) as ctx:
            parseCompareArguments(["nodes", "/path/to/bench", "both"])
        self.assertIn("Invalid operation: 'both'. Must be 'read' or 'write'", str(ctx.exception))

        with self.assertRaises(CompareCliParseError) as ctx:
            parseCompareArguments(["nodes", "/path/to/bench", "delete"])
        self.assertIn("Invalid operation: 'delete'. Must be 'read' or 'write'", str(ctx.exception))

        # Invalid stripes
        with self.assertRaises(CompareCliParseError) as ctx:
            parseCompareArguments(["nodes", "/path/to/bench", "read", "8"])
        self.assertIn("Invalid stripes: '8'", str(ctx.exception))

        with self.assertRaises(CompareCliParseError) as ctx:
            parseCompareArguments(["nodes", "/path/to/bench", "read", "abc"])
        self.assertIn("Invalid stripes: 'abc'", str(ctx.exception))

        # Invalid blocksize
        with self.assertRaises(CompareCliParseError) as ctx:
            parseCompareArguments(["nodes", "/path/to/bench", "read", "4", "2M"])
        self.assertIn("Invalid blocksize: '2M'", str(ctx.exception))

        # Rejection of --all option under nodes mode
        with self.assertRaises(CompareCliParseError) as ctx:
            parseCompareArguments(["nodes", "/path/to/bench", "read", "--all"])
        self.assertIn("Option '--all' is only valid for 'variants' submode", str(ctx.exception))

        # Prohibited --all=val and --output-dir=val syntax
        with self.assertRaises(CompareCliParseError) as ctx:
            parseCompareArguments(["nodes", "/path/to/bench", "read", "--all=true"])
        self.assertIn("Prohibit '--all=value' syntax", str(ctx.exception))

        with self.assertRaises(CompareCliParseError) as ctx:
            parseCompareArguments(["nodes", "/path/to/bench", "read", "--output-dir=/tmp/plots"])
        self.assertIn("Prohibit '--output-dir=value' syntax", str(ctx.exception))

        # Missing or option-like value after --output-dir
        with self.assertRaises(CompareCliParseError) as ctx:
            parseCompareArguments(["nodes", "/path/to/bench", "read", "--output-dir"])
        self.assertIn("Missing value after '--output-dir' option.", str(ctx.exception))

        with self.assertRaises(CompareCliParseError) as ctx:
            parseCompareArguments(["nodes", "/path/to/bench", "read", "--output-dir", "--other"])
        self.assertIn("Missing valid value after '--output-dir' option, got option-like token: '--other'", str(ctx.exception))

        with self.assertRaises(CompareCliParseError) as ctx:
            parseCompareArguments(["nodes", "/path/to/bench", "read", "--output-dir", ""])
        self.assertIn("Output directory path cannot be empty.", str(ctx.exception))

        # Duplicate options
        with self.assertRaises(CompareCliParseError) as ctx:
            parseCompareArguments([
                "nodes",
                "/path/to/bench",
                "read",
                "--output-dir",
                "/a",
                "--output-dir",
                "/b",
            ])
        self.assertIn("Duplicate '--output-dir' option specified.", str(ctx.exception))

        # Unknown options
        with self.assertRaises(CompareCliParseError) as ctx:
            parseCompareArguments(["nodes", "/path/to/bench", "read", "--unknown"])
        self.assertIn("Unknown option: '--unknown'", str(ctx.exception))

        # Unexpected extra positional arguments
        with self.assertRaises(CompareCliParseError) as ctx:
            parseCompareArguments([
                "nodes",
                "/path/to/bench",
                "read",
                "4",
                "1M",
                "extra",
            ])
        self.assertIn("Unexpected extra positional argument: 'extra'", str(ctx.exception))

        # Unexpected token before compare
        with self.assertRaises(CompareCliParseError) as ctx:
            parseCompareArguments([
                "unexpected",
                "compare",
                "nodes",
                "/path/to/bench",
                "read",
            ])
        self.assertIn("Unexpected token before 'compare': 'unexpected'", str(ctx.exception))

        # Invalid argv types
        with self.assertRaises(CompareCliParseError):
            parseCompareArguments(None)  # type: ignore
        with self.assertRaises(CompareCliParseError):
            parseCompareArguments("string")  # type: ignore
        with self.assertRaises(CompareCliParseError):
            parseCompareArguments(123)  # type: ignore
        with self.assertRaises(CompareCliParseError):
            parseCompareArguments(["nodes", "/path", 123])  # type: ignore

    def testParseCompareVariantsGrammarErrors(self) -> None:
        """Validates error cases specific to 'compare variants' grammar."""
        # Missing archive folder
        with self.assertRaises(CompareCliParseError) as ctx:
            parseCompareArguments(["variants"])
        self.assertIn("Missing required positional argument: <archive_folder>", str(ctx.exception))

        # Option placed before archive folder
        with self.assertRaises(CompareCliParseError) as ctx:
            parseCompareArguments(["variants", "--all", "/path/to/archive"])
        self.assertIn("Unexpected option '--all' placed before positional argument <archive_folder>", str(ctx.exception))

        # Invalid operation
        with self.assertRaises(CompareCliParseError) as ctx:
            parseCompareArguments(["variants", "/path/to/archive", "delete"])
        self.assertIn("Invalid operation: 'delete'", str(ctx.exception))

        # Invalid stripes
        with self.assertRaises(CompareCliParseError) as ctx:
            parseCompareArguments(["variants", "/path/to/archive", "read", "8"])
        self.assertIn("Invalid stripes: '8'", str(ctx.exception))

        # Invalid blocksize
        with self.assertRaises(CompareCliParseError) as ctx:
            parseCompareArguments(["variants", "/path/to/archive", "read", "4", "2M"])
        self.assertIn("Invalid blocksize: '2M'", str(ctx.exception))

        # Prohibited --all=val syntax
        with self.assertRaises(CompareCliParseError) as ctx:
            parseCompareArguments(["variants", "/path/to/archive", "--all=true"])
        self.assertIn("Prohibit '--all=value' syntax", str(ctx.exception))

        # Missing or option-like value after --output-dir
        with self.assertRaises(CompareCliParseError) as ctx:
            parseCompareArguments(["variants", "/path/to/archive", "--output-dir"])
        self.assertIn("Missing value after '--output-dir' option.", str(ctx.exception))

        with self.assertRaises(CompareCliParseError) as ctx:
            parseCompareArguments(["variants", "/path/to/archive", "--output-dir", "--all"])
        self.assertIn("Missing valid value after '--output-dir' option, got option-like token: '--all'", str(ctx.exception))

        # Duplicate options
        with self.assertRaises(CompareCliParseError) as ctx:
            parseCompareArguments(["variants", "/path/to/archive", "--all", "--all"])
        self.assertIn("Duplicate '--all' option specified.", str(ctx.exception))

        # Unknown option
        with self.assertRaises(CompareCliParseError) as ctx:
            parseCompareArguments(["variants", "/path/to/archive", "--foo"])
        self.assertIn("Unknown option: '--foo'", str(ctx.exception))

        # Unexpected extra positional arguments
        with self.assertRaises(CompareCliParseError) as ctx:
            parseCompareArguments([
                "variants",
                "/path/to/archive",
                "read",
                "4",
                "1M",
                "extra",
            ])
        self.assertIn("Unexpected extra positional argument: 'extra'", str(ctx.exception))

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

    def testCompareHelpTextSynchronization(self) -> None:
        """Asserts that COMPARE_HELP_TEXT and LSMIOTOOL_HELP are defined and synchronized."""
        self.assertIn("lsmiotool compare <nodes|variants> <folder> ...", COMPARE_HELP_TEXT)
        self.assertIn("nodes <folder> <read|write>", COMPARE_HELP_TEXT)
        self.assertIn("variants <archive_folder>", COMPARE_HELP_TEXT)
        self.assertIn("compare <nodes|variants> <folder> ...", LSMIOTOOL_HELP)
        self.assertEqual(COMPARE_ARCHIVE_HELP_TEXT, COMPARE_HELP_TEXT)
        self.assertIs(CompareArchiveCliParseError, CompareCliParseError)


if __name__ == "__main__":
    unittest.main()
