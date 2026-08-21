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

import fnmatch
import importlib
import pkgutil
import unittest


_TEST_FILENAME_PATTERNS = ("test*.py", "*Test.py", "Test*.py")
_EXCLUDED_PATH_COMPONENTS = frozenset(("example", "fixtures"))


def _matchingTestPatterns(f_module_name):
    filename = f_module_name.rsplit(".", 1)[-1] + ".py"
    return tuple(
        pattern
        for pattern in _TEST_FILENAME_PATTERNS
        if fnmatch.fnmatchcase(filename, pattern)
    )


def _isDiscoverableTestModule(f_module_name, f_is_package):
    components = f_module_name.split(".")
    if f_is_package or components[-1] == "__init__":
        return False
    if _EXCLUDED_PATH_COMPONENTS.intersection(components):
        return False
    return bool(_matchingTestPatterns(f_module_name))


def _discoverTestModuleNames(
    f_paths=None,
    f_prefix=None,
    f_walk_packages=pkgutil.walk_packages,
):
    paths = __path__ if f_paths is None else f_paths
    prefix = __name__ + "." if f_prefix is None else f_prefix
    module_names = {
        module_info.name
        for module_info in f_walk_packages(paths, prefix)
        if _isDiscoverableTestModule(module_info.name, module_info.ispkg)
    }
    if not module_names:
        raise RuntimeError("No lsmiotool test modules were discovered")
    return tuple(sorted(module_names))


def _importTestModules(f_module_names, f_import_module=importlib.import_module):
    return tuple(f_import_module(module_name) for module_name in f_module_names)


def _buildTestSuite(f_modules):
    if not f_modules:
        raise RuntimeError("No lsmiotool test modules were imported")

    test_suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    for module in f_modules:
        test_suite.addTests(loader.loadTestsFromModule(module))
    if test_suite.countTestCases() == 0:
        raise RuntimeError("No lsmiotool tests were loaded")
    return test_suite


lsmiotool_test_module_names = _discoverTestModuleNames()
lsmiotool_tests = _importTestModules(lsmiotool_test_module_names)


def suite():
    return _buildTestSuite(lsmiotool_tests)


def run_and_report() -> int:
    tr = unittest.TextTestRunner(verbosity=2)
    result = tr.run(suite())
    return 0 if result.wasSuccessful() else 1
