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

class TestIorAggOutput(output.IorAggOutput):
  _node_counts= ['1', '2']


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
    self.assertTrue('1' in dir_map)
    self.assertEqual(len(dir_map), 2)
    self.assertTrue('2023-07-21' in dir_map['1'])
    self.assertEqual(len(dir_map['1']['2023-07-21']), 6)
    self.assertEqual(dir_map['1']['2023-07-21']['out-collective-16-1M-2023-07-21-node169-0.txt.2'], 6952)


  #{'1': {'16': {'1M': {'out-collective-16-1M-2023-07-21-node169-0.txt.2': 6952},
  #              '64K': {'out-collective-16-64K-2023-07-21-node169-0.txt.2': 6969},
  #              '8M': {'out-collective-16-8M-2023-07-21-node169-0.txt.2': 6949}},
  #       '4': {'1M': {'out-collective-4-1M-2023-07-21-node169-0.txt.2': 6949},
  #             '64K': {'out-collective-4-64K-2023-07-21-node169-0.txt.2': 6966},
  #             '8M': {'out-collective-4-8M-2023-07-21-node169-0.txt.2': 6947}}},
  # '2': {'16': {'1M': {'out-collective-16-1M-2023-07-21-node154-0.txt.2': 0},
  #              '64K': {'out-collective-16-64K-2023-07-21-node154-0.txt.2': 0},
  #              '8M': {'out-collective-16-8M-2023-07-21-node150-0.txt.2': 6950}},
  #       '4': {'1M': {'out-collective-4-1M-2023-07-21-node150-0.txt.2': 6946},
  #             '64K': {'out-collective-4-64K-2023-07-21-node154-0.txt.2': 0},
  #             '8M': {'out-collective-4-8M-2023-07-21-node154-0.txt.2': 0}}}}
  def test_ior_out_dir(self):
    root_dir_list = ['example', 'ior-outputs']
    root_dir = os.path.join(MY_DIR, *root_dir_list)
    Console.debug('Reading example ior directory to traverse: ' + root_dir + '.')
    ior_dir = output.IorOutputDir(root_dir)
    dir_map = ior_dir.getMap()
    #Console.debug("test_ior_out_dir map: " + pprint.pformat(dir_map))
    self.assertTrue('1' in dir_map)
    self.assertEqual(len(dir_map), 2)
    self.assertTrue('4' in dir_map['1'])
    self.assertEqual(len(dir_map['1']), 2)
    self.assertTrue('1M' in dir_map['1']['4'])
    self.assertEqual(len(dir_map['1']['4']), 3)
    self.assertEqual(dir_map['1']['4']['64K']['out-collective-4-64K-2023-07-21-node169-0.txt.2']["size"], 6966)


  def test_lsm_out_dir(self):
    root_dir_list = ['example', 'lsmio-outputs']
    root_dir = os.path.join(MY_DIR, *root_dir_list)
    Console.debug('Reading example ior directory to traverse: ' + root_dir + '.')
    lsm_dir = output.LsmioOutputDir(root_dir)
    dir_map = lsm_dir.getMap()
    #Console.debug("test_ior_out_dir map: " + pprint.pformat(dir_map))
    self.assertTrue('4' in dir_map)
    self.assertEqual(len(dir_map), 2)
    self.assertTrue('16' in dir_map['4'])
    self.assertEqual(len(dir_map['4']), 2)
    self.assertTrue('8M' in dir_map['4']['16'])
    self.assertEqual(len(dir_map['4']['16']), 3)
    self.assertEqual(dir_map['4']['16']['64K']['out-rocksdb-16-64K-2023-07-02-node103-0.txt.2']["size"], 2190)
    self.assertEqual(dir_map['4']['16']['64K']['out-rocksdb-16-64K-2023-07-02-node105-0.txt.2']["size"], 2190)
    self.assertEqual(dir_map['4']['16']['64K']['out-rocksdb-16-64K-2023-07-02-node108-0.txt.2']["size"], 2190)
    self.assertEqual(dir_map['4']['16']['64K']['out-rocksdb-16-64K-2023-07-02-node113-0.txt.2']["size"], 2190)


  #{'1': {'16': {'1M': [{'read': {'#Tasks': '1',
  #                             'API': 'MPIIO',
  #                             'Max(MiB)': 4152.58,
  #                             'Max(OPs)': 4152.58,
  #                             'Mean(MiB)': 3734.04,
  #                             'Mean(OPs)': 3734.04,
  #                             'Mean(s)': '0.13826',
  #                             ...
  #                    'write': {'#Tasks': '1',
  #                              'API': 'MPIIO',
  #                              'Max(MiB)': 1154.86,
  #                              'Max(OPs)': 1154.86,
  #                              'Mean(MiB)': 1022.76,
  def test_ior_agg_out(self):
    root_dir_list = ['example', 'ior-outputs']
    root_dir = os.path.join(MY_DIR, *root_dir_list)
    Console.debug('Reading example ior agg directory: ' + root_dir + '.')
    ior_agg = TestIorAggOutput(root_dir)
    agg_map = ior_agg.getMap()
    #Console.debug("test_ior_agg_out map: " + pprint.pformat(agg_map))
    self.assertTrue('1' in agg_map)
    self.assertEqual(len(agg_map), 2)
    self.assertTrue('4' in agg_map['1'])
    self.assertEqual(len(agg_map['1']), 2)
    self.assertTrue('1M' in agg_map['1']['4'])
    self.assertEqual(len(agg_map['1']['4']), 3)
    self.assertEqual(agg_map['1']['16']['1M']['read']["Max(MiB)"], 4152.58)
    self.assertEqual(agg_map['1']['16']['1M']['write']["Max(OPs)"], 1154.86)


