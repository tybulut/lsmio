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

import pkgutil
import unittest
from types import ModuleType
from unittest.mock import Mock

import lsmiotool.test as test_package


_PREEXISTING_MODULE_NAMES = (
    "lsmiotool.test.main.BaselineGateTest",
    "lsmiotool.test.main.test_dirs",
    "lsmiotool.test.main.test_hpc",
    "lsmiotool.test.main.test_jobs",
    "lsmiotool.test.parse.TestCompareMain",
    "lsmiotool.test.parse.TestEndToEndParse",
    "lsmiotool.test.parse.TestLmpData",
    "lsmiotool.test.parse.TestMultiBarPlot",
    "lsmiotool.test.parse.TestOutputAggregation",
    "lsmiotool.test.parse.TestParseMain",
    "lsmiotool.test.parse.test_data",
    "lsmiotool.test.parse.test_log",
    "lsmiotool.test.parse.test_output",
)

_LEGACY_PREFIX_MODULE_NAMES = (
    "lsmiotool.test.parse.TestCompareMain",
    "lsmiotool.test.parse.TestEndToEndParse",
    "lsmiotool.test.parse.TestLmpData",
    "lsmiotool.test.parse.TestMultiBarPlot",
    "lsmiotool.test.parse.TestOutputAggregation",
    "lsmiotool.test.parse.TestParseMain",
)


def _moduleInfo(f_name, f_is_package=False):
    return pkgutil.ModuleInfo(None, f_name, f_is_package)


def _walkFrom(f_module_infos):
    return lambda f_paths, f_prefix: iter(f_module_infos)


def _testIds(f_suite):
    test_ids = []
    for test in f_suite:
        if isinstance(test, unittest.TestSuite):
            test_ids.extend(_testIds(test))
        else:
            test_ids.append(test.id())
    return test_ids


class LoaderTest(unittest.TestCase):
    def testDiscoversLowercasePrefixPreferredSuffixAndLegacyPrefixExactlyOnce(
        self,
    ) -> None:
        module_infos = (
            _moduleInfo("synthetic.tests.test_lowercase"),
            _moduleInfo("synthetic.tests.PreferredTest"),
            _moduleInfo("synthetic.tests.TestLegacy"),
            _moduleInfo("synthetic.tests.helper"),
        )

        discovered = test_package._discoverTestModuleNames(
            f_paths=(),
            f_prefix="synthetic.tests.",
            f_walk_packages=_walkFrom(module_infos),
        )

        self.assertEqual(
            discovered,
            (
                "synthetic.tests.PreferredTest",
                "synthetic.tests.TestLegacy",
                "synthetic.tests.test_lowercase",
            ),
        )

    def testLegacyPrefixInventoryHasSixModulesAndThirtyThreeTestsExactlyOnce(
        self,
    ) -> None:
        modules_by_name = {
            module.__name__: module for module in test_package.lsmiotool_tests
        }
        legacy_modules = tuple(
            modules_by_name[module_name]
            for module_name in _LEGACY_PREFIX_MODULE_NAMES
        )
        test_ids = _testIds(test_package._buildTestSuite(legacy_modules))

        self.assertEqual(
            tuple(module.__name__ for module in legacy_modules),
            _LEGACY_PREFIX_MODULE_NAMES,
        )
        self.assertEqual(len(test_ids), 33)
        self.assertEqual(len(test_ids), len(set(test_ids)))

    def testLexicalOrderIndependentOfWalkOrder(self) -> None:
        module_infos = (
            _moduleInfo("synthetic.tests.test_zulu"),
            _moduleInfo("synthetic.tests.AlphaTest"),
            _moduleInfo("synthetic.tests.TestMiddle"),
        )
        forward = test_package._discoverTestModuleNames(
            f_paths=(),
            f_prefix="synthetic.tests.",
            f_walk_packages=_walkFrom(module_infos),
        )
        reversed_order = test_package._discoverTestModuleNames(
            f_paths=(),
            f_prefix="synthetic.tests.",
            f_walk_packages=_walkFrom(tuple(reversed(module_infos))),
        )

        self.assertEqual(forward, tuple(sorted(forward)))
        self.assertEqual(reversed_order, forward)

    def testOverlappingPatternAndAliasSightingsDeduplicateBeforeImport(
        self,
    ) -> None:
        module_name = "synthetic.tests.TestBridgeTest"
        module_infos = (
            _moduleInfo(module_name),
            _moduleInfo(module_name),
            _moduleInfo(module_name),
        )
        discovered = test_package._discoverTestModuleNames(
            f_paths=(),
            f_prefix="synthetic.tests.",
            f_walk_packages=_walkFrom(module_infos),
        )
        imported_module = ModuleType(module_name)
        import_module = Mock(return_value=imported_module)

        imported = test_package._importTestModules(discovered, import_module)

        self.assertEqual(
            test_package._matchingTestPatterns(module_name),
            ("*Test.py", "Test*.py"),
        )
        self.assertEqual(discovered, (module_name,))
        self.assertEqual(imported, (imported_module,))
        import_module.assert_called_once_with(module_name)

    def testExcludesPackagesInitializersFixturesExamplesDataAndNonmatchingHelpers(
        self,
    ) -> None:
        module_infos = (
            _moduleInfo("synthetic.tests.TestPackage", f_is_package=True),
            _moduleInfo("synthetic.tests.__init__"),
            _moduleInfo("synthetic.tests.fixtures.TestFixture"),
            _moduleInfo("synthetic.tests.parse.example.TestExample"),
            _moduleInfo("synthetic.tests.parse.example.data.test_resource"),
            _moduleInfo("synthetic.tests.parse.helper"),
            _moduleInfo("synthetic.tests.parse.test_data"),
        )

        discovered = test_package._discoverTestModuleNames(
            f_paths=(),
            f_prefix="synthetic.tests.",
            f_walk_packages=_walkFrom(module_infos),
        )

        self.assertEqual(discovered, ("synthetic.tests.parse.test_data",))

    def testImportAndEmptyDiscoveryFail(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "No lsmiotool test modules"):
            test_package._discoverTestModuleNames(
                f_paths=(),
                f_prefix="synthetic.tests.",
                f_walk_packages=_walkFrom(()),
            )

        import_error = ModuleNotFoundError("broken test module")
        import_module = Mock(side_effect=import_error)
        with self.assertRaises(ModuleNotFoundError) as raised:
            test_package._importTestModules(
                ("synthetic.tests.BrokenTest",),
                import_module,
            )
        self.assertIs(raised.exception, import_error)
        import_module.assert_called_once_with("synthetic.tests.BrokenTest")

    def testAllPreexistingModulesAndTestsRemainPresentExactlyOnce(self) -> None:
        current_modules = tuple(
            module
            for module in test_package.lsmiotool_tests
            if module.__name__ != "lsmiotool.test.main.LoaderTest"
        )
        preexisting_test_ids = _testIds(
            test_package._buildTestSuite(current_modules)
        )
        all_test_ids = _testIds(test_package.suite())

        self.assertEqual(
            tuple(module.__name__ for module in current_modules),
            _PREEXISTING_MODULE_NAMES,
        )
        self.assertIn("lsmiotool.test.parse.test_data", _PREEXISTING_MODULE_NAMES)
        self.assertEqual(len(preexisting_test_ids), 77)
        self.assertEqual(len(preexisting_test_ids), len(set(preexisting_test_ids)))
        self.assertEqual(len(all_test_ids), 85)
        self.assertEqual(len(all_test_ids), len(set(all_test_ids)))
        self.assertEqual(
            set(preexisting_test_ids),
            set(all_test_ids) - {
                test_id
                for test_id in all_test_ids
                if ".LoaderTest." in test_id
            },
        )

    def testOrdinaryDiscoveryExcludesCtestInstalledSmoke(self) -> None:
        self.assertNotIn(
            "lsmiotool.ctest.installed_smoke",
            test_package.lsmiotool_test_module_names,
        )
        self.assertFalse(
            any(
                "installed_smoke" in name
                for name in test_package.lsmiotool_test_module_names
            )
        )
        self.assertEqual(
            test_package._matchingTestPatterns("installed_smoke"),
            (),
        )
        self.assertEqual(
            test_package._matchingTestPatterns("installed_smoke.py"),
            (),
        )
        self.assertFalse(
            test_package._isDiscoverableTestModule(
                "lsmiotool.ctest.installed_smoke",
                False,
            )
        )
        self.assertFalse(
            test_package._isDiscoverableTestModule(
                "installed_smoke",
                False,
            )
        )
        all_test_ids = _testIds(test_package.suite())
        self.assertFalse(
            any(
                "installed_smoke" in test_id.split(".")[:-1]
                or "InstalledSmoke" in test_id.split(".")[:-1]
                or test_id.startswith("lsmiotool.ctest")
                for test_id in all_test_ids
            )
        )
