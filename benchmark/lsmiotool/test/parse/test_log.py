from unittest import TestCase
from io import StringIO
from lsmiotool.lib.log import Log
from lsmiotool.lib.debuggable import DebuggableObject


class MyTestObject(DebuggableObject):

	def methodDebugs(self, f_args):
		self._logDebug(f_args)


	def methodWarns(self, f_args):
		self._logWarning(f_args)


	def methodErrors(self, f_args):
		self._logError(f_args)


class LogUnitTestCase(TestCase):

	def test_traceable(self):
		swap_output = Log().output
		Log().output = StringIO()

		to = MyTestObject()

		Log().output.seek(0)
		Log().output.truncate()
		to.methodWarns({'b': 2 })
		output = Log().output.getvalue()
		self.assertEqual(output, 'lsmiotool: WARNING: MyTestObject::methodWarns(): b=2\n', output)

		Log().output.seek(0)
		Log().output.truncate()
		to.methodErrors({'c': 3 })
		output = Log().output.getvalue()
		self.assertEqual(output, 'lsmiotool: ERROR: MyTestObject::methodErrors(): c=3\n', output)

		Log().output = swap_output



