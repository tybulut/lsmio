#
# Copyright 2023 Serdar Bulut
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

from lsmiotool.lib import enum, StringEnum, LsmioToolException


class LibPackageTest(unittest.TestCase):
    def testEnumAssignsIndexesAndKeywordValues(self) -> None:
        """enum() numbers positional names and lets keywords add or override."""
        f_rows = (
            (enum("ERROR", "WARNING", "DEBUG", "INFO"), {"ERROR": 0, "WARNING": 1, "DEBUG": 2, "INFO": 3}),
            (enum("A", B=5), {"A": 0, "B": 5}),
            (enum("A", A=9), {"A": 9}),
        )
        for f_index, (f_e, f_expected) in enumerate(f_rows):
            with self.subTest(row=f_index):
                for f_name, f_value in f_expected.items():
                    self.assertEqual(getattr(f_e, f_name), f_value)
                self.assertIsInstance(f_e, type)
                self.assertEqual(f_e.__name__, "Enum")
        with self.subTest(row="empty"):
            f_empty = enum()
            self.assertFalse(hasattr(f_empty, "A"))
            self.assertEqual(f_empty.__name__, "Enum")
        with self.subTest(row="distinct"):
            self.assertIsNot(enum("A"), enum("A"))

    def testStringEnumReturnsMemberName(self) -> None:
        """Attribute lookup of a member returns the member's own name."""
        f_se = StringEnum(["ERROR", "WARNING", ""])
        for f_name in ("ERROR", "WARNING", ""):
            with self.subTest(name=f_name):
                self.assertEqual(getattr(f_se, f_name), f_name)
        self.assertEqual(f_se, {"ERROR", "WARNING", ""})

    def testStringEnumUnknownNameRaises(self) -> None:
        """Attribute lookup of a non-member raises AttributeError carrying the name."""
        f_rows = ((["ERROR"], "MISSING"), (["ERROR"], "error"), ([], ""))
        for f_members, f_name in f_rows:
            with self.subTest(name=f_name):
                f_se = StringEnum(f_members)
                with self.assertRaises(AttributeError) as f_ctx:
                    getattr(f_se, f_name)
                self.assertEqual(f_ctx.exception.args, (f_name,))
                self.assertEqual(len(f_se), len(f_members))

    def testLsmioToolExceptionKeepsValue(self) -> None:
        """LsmioToolException stores its value and stringifies it."""
        for f_value in ("boom", "", 42, {"k": 1}):
            with self.subTest(value=f_value):
                f_exc = LsmioToolException(f_value)
                self.assertEqual(str(f_exc), str(f_value))
                self.assertIs(f_exc.value, f_value)
                self.assertIsInstance(f_exc, Exception)
                with self.assertRaises(LsmioToolException) as f_ctx:
                    raise LsmioToolException(f_value)
                self.assertIs(f_ctx.exception.value, f_value)
