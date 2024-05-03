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

import sys, unittest
import lsmiotool
try:
	import coverage
	_HAS_COVERAGE = True
except ImportError:
	_HAS_COVERAGE = False


_LSMIOTOOL_TEST_MODULES = [ 'lsmiotool.test.parse' ]

# The modules needs to be loaded to be queried
for _n in _LSMIOTOOL_TEST_MODULES:
	exec("from %s import *" % _n)
modules = list(globals().keys())
lsmiotool_tests = []
for m in modules:
	if m.startswith('_'): continue
	module = globals()[m]
	if not module.__name__.startswith('lsmiotool.test.'): continue
	if module.__name__ in _LSMIOTOOL_TEST_MODULES: continue
	print(module.__name__)
	lsmiotool_tests.append(module)


def suite():
	suite = unittest.TestSuite()
	tests = []
	for test in lsmiotool_tests:
		tl = unittest.TestLoader().loadTestsFromModule(test)
		tests += tl._tests
	suite._tests = tests
	return suite


def run_and_report():
	if _HAS_COVERAGE:
		cov = coverage.Coverage()
		cov.erase()
		cov.start()
	tr = unittest.TextTestRunner(verbosity=2)
	tr.run(suite())
	if _HAS_COVERAGE:
		cov.stop()
		cov.analysis(lsmiotool.lib)

	mc = []
	for m in sys.modules.values():
		if m and m.__name__.startswith('lsmiotool.lib'):
			mc.append(m)
	if _HAS_COVERAGE:
		cov.report(mc, ignore_errors=1, show_missing=0)

