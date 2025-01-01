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

import os, lsmiotool

VERSION = "0.2"
PROGRAM = "lsmiotool"
LSMIOTOOL_DIR = os.path.dirname(os.path.abspath(lsmiotool.__file__))

# Enum definition
def enum(*args, **kwargs):
  """
  a = enum('ERROR', 'WARNING', 'DEBUG', 'INFO')
  assert(a.ERROR == 0)
  """
  enums = dict(zip(args, range(len(args))), **kwargs)
  return type('Enum', (), enums)


class StringEnum(set):
  """
  a = StringEnum(['ERROR', 'WARNING', 'DEBUG', 'INFO'])
  assert(a.ERROR == 'ERROR')
  """
  def __getattr__(self, f_name):
    if f_name in self:
        return f_name
    raise AttributeError(f_name)


class LsmioToolException(Exception):

  def __init__(self, value):
    self.value = value


  def __str__(self):
    return str(self.value)


