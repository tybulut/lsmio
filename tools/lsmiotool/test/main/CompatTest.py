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

import importlib.util
import sys
import types
import typing
import unittest
from unittest.mock import patch

import lsmiotool.lib.compat as f_real_compat


class CompatFallbackTest(unittest.TestCase):
    def _loadFallbackCompat(self) -> types.ModuleType:
        """Execute compat.py privately with a typing module lacking TypedDict/Final."""
        f_spec = importlib.util.spec_from_file_location(
            "lsmiotool_compat_fallback_probe", f_real_compat.__file__
        )
        f_module = importlib.util.module_from_spec(f_spec)
        with patch.dict(sys.modules, {"typing": types.ModuleType("typing")}):
            f_spec.loader.exec_module(f_module)
        return f_module

    def testFallbackTypedDictIsDictSubclass(self) -> None:
        """The Python < 3.8 TypedDict stand-in is a plain dict subclass."""
        f_mod = self._loadFallbackCompat()

        class Point(f_mod.TypedDict):
            pass

        f_p = Point(x=1)
        self.assertTrue(issubclass(f_mod.TypedDict, dict))
        self.assertIsNot(f_mod.TypedDict, typing.TypedDict)
        self.assertEqual(f_p["x"], 1)
        self.assertIsInstance(f_p, dict)
        self.assertEqual(Point(x="a")["x"], "a")

    def testFallbackFinalSubscriptReturnsItem(self) -> None:
        """Subscripting the Final stand-in returns the subscript unchanged."""
        f_mod = self._loadFallbackCompat()
        for f_item in (int, str, "x", "", None):
            with self.subTest(item=f_item):
                self.assertIs(f_mod.Final[f_item], f_item)
        self.assertEqual(f_mod.Final["x"], "x")
        self.assertEqual(f_mod.Final[""], "")
        self.assertEqual(type(f_mod.Final).__name__, "_FinalMeta")
        self.assertIsNot(f_mod.Final, typing.Final)

    def testFallbackLoadLeavesRealModulesIntact(self) -> None:
        """The private fallback load does not disturb sys.modules or the real module."""
        f_typing_before = sys.modules["typing"]
        self._loadFallbackCompat()
        self.assertIs(sys.modules["typing"], f_typing_before)
        self.assertNotIn("lsmiotool_compat_fallback_probe", sys.modules)
        self.assertIs(f_real_compat.TypedDict, typing.TypedDict)
        self.assertIs(f_real_compat.Final, typing.Final)
