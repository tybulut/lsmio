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



