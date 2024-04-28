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

