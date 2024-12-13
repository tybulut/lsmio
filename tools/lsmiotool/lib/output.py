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

import os, re, pprint
from lsmiotool.lib.debuggable import DebuggableObject
from lsmiotool.lib.log import Console


class TraverseDir(DebuggableObject):
  def __init__(self, target_dir):
    self.root_dir = target_dir
    self.dir_recursive = self._gather(target_dir)

  #ior-outputs/4/2023-07-21/
  #  out-collective-16-1M-2023-07-21-node109-0.txt.2
  #  out-collective-16-1M-2023-07-21-node110-0.txt.2
  #  out-collective-16-1M-2023-07-21-node116-0.txt.2
  #  out-collective-16-1M-2023-07-21-node120-0.txt.2
  #  out-collective-16-64K-2023-07-21-node109-0.txt.2
  #  out-collective-16-64K-2023-07-21-node110-0.txt.2
  #  out-collective-16-64K-2023-07-21-node116-0.txt.2
  #  out-collective-16-64K-2023-07-21-node120-0.txt.2
  def _gather(self, gather_dir):
    folder_dict = {}
    for root, dirs, files in os.walk(gather_dir):
        for file in files:
            file_path = os.path.join(root, file)
            folder_dict[file] = os.path.getsize(file_path)
        for odir in dirs:
            folder_dict[odir] = self._gather(os.path.join(root, odir))
        break
    return folder_dict


  def getMap(self):
    #Console.debug("self.dir_recursive: " + pprint.pformat(self.dir_recursive))
    return self.dir_recursive


#{'1': {'2023-07-21':
#                               {'out-collective-16-1M-2023-07-21-node169-0.txt.2': 6952,
#                                'out-collective-16-64K-2023-07-21-node169-0.txt.2': 6969,
#                                'out-collective-16-8M-2023-07-21-node169-0.txt.2': 6949,
#                                'out-collective-4-1M-2023-07-21-node169-0.txt.2': 6949,
#                                'out-collective-4-64K-2023-07-21-node169-0.txt.2': 6966,
#                                'out-collective-4-8M-2023-07-21-node169-0.txt.2': 6947},
# ...
class IorOutputDir(TraverseDir):

  def getMetaMap(self):
    meta_dict = {}
    for field_size in self.dir_recursive:
        value_size = self.dir_recursive[field_size]
        if not isinstance(value_size, dict):
            Console.debug("Unexpeted field_size: " + field_size)
            Console.debug("Unexpeted value_size: " + str(value_size))
            continue
        if field_size not in meta_dict:
            meta_dict[field_size] = {}
        for date_dir in value_size:
            value_date = value_size[date_dir]
            if not isinstance(value_date, dict):
                continue # date: '2023-07-21'
            for key in value_date:
                val = value_date[key]
                if isinstance(val, dict):
                    continue # something else...
                pattern = r"out-[a-zA-Z\d-]*-(\d+)-(\d+[KMGTB])-\d+-\d+-\d+-[a-zA-Z\d]+-\d+\.\w+\.\d+"
                match = re.match(pattern, key)
                if not match:
                    Console.debug("Unexpected file pattern: " + key)
                    continue
                stripe_count = str(match.group(1))
                stripe_size = str(match.group(2))
                if stripe_count not in meta_dict[field_size]:
                    meta_dict[field_size][stripe_count] = {}
                if stripe_size not in meta_dict[field_size][stripe_count]:
                    meta_dict[field_size][stripe_count][stripe_size] = {}
                meta_dict[field_size][stripe_count][stripe_size][key] = val
    #Console.debug("meta_dict: " + pprint.pformat(meta_dict))
    return meta_dict


class LsmioOutputDir(IorOutputDir):
    pass

