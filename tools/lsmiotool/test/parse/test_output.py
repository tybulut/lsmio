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
from lsmiotool.lib.log import Console
from lsmiotool.lib import output

import os
from pathlib import Path
import pprint

MY_DIR = Path(__file__).parent.resolve()

class OutputUnitTestCase(TestCase):

  #ior-output
  #ior-output/1
  #ior-output/1/2023-07-21
  #ior-output/1/2023-07-21/out-collective-4-1M-2023-07-21-node169-0.txt.2
  #ior-output/1/2023-07-21/out-collective-16-8M-2023-07-21-node169-0.txt.2
  #ior-output/1/2023-07-21/out-collective-4-64K-2023-07-21-node169-0.txt.2
  #ior-output/1/2023-07-21/out-collective-16-1M-2023-07-21-node169-0.txt.2
  #ior-output/1/2023-07-21/out-collective-16-64K-2023-07-21-node169-0.txt.2
  #ior-output/1/2023-07-21/out-collective-4-8M-2023-07-21-node169-0.txt.2
  #
  #{'ior-outputs': {'1': {'2023-07-21':
  #                               {'out-collective-16-1M-2023-07-21-node169-0.txt.2': 6952,
  #                                'out-collective-16-64K-2023-07-21-node169-0.txt.2': 6969,
  #                                'out-collective-16-8M-2023-07-21-node169-0.txt.2': 6949,
  #                                'out-collective-4-1M-2023-07-21-node169-0.txt.2': 6949,
  #                                'out-collective-4-64K-2023-07-21-node169-0.txt.2': 6966,
  #                                'out-collective-4-8M-2023-07-21-node169-0.txt.2': 6947},
  # ...
  def test_traverse_dir(self):
    root_dir_list = ['example', 'ior-outputs']
    root_dir = os.path.join(MY_DIR, *root_dir_list)
    Console.debug('Reading example directory to traverse: ' + root_dir + '.')
    traversed = output.TraverseDir(root_dir)
    dir_map = traversed.getMap()
    #Console.debug("test_traverse_dir map: " + pprint.pformat(dir_map))
    self.assertTrue('ior-outputs' in dir_map)
    self.assertTrue('1' in dir_map['ior-outputs'])
    self.assertTrue('2023-07-21' in dir_map['ior-outputs']['1'])
    self.assertEqual(len(dir_map['ior-outputs']['1']['2023-07-21']), 6)
    self.assertEqual(dir_map['ior-outputs']['1']['2023-07-21']['out-collective-16-1M-2023-07-21-node169-0.txt.2'], 6952)

