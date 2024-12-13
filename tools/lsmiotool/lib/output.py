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

import os
from lsmiotool.lib.debuggable import DebuggableObject


class TraverseDir(DebuggableObject):
  def __init__(self, target_dir):
    self.root_dir = target_dir
    self.dir_recursive = { os.path.basename(target_dir) : self._gather(target_dir) }

  #outputs/4/2023-07-21/
  #  out-collective-16-1M-2023-07-21-node109-0.txt.2
  #  out-collective-16-1M-2023-07-21-node110-0.txt.2
  #  out-collective-16-1M-2023-07-21-node116-0.txt.2
  #  out-collective-16-1M-2023-07-21-node120-0.txt.2
  #  out-collective-16-64K-2023-07-21-node109-0.txt.2
  #  out-collective-16-64K-2023-07-21-node110-0.txt.2
  #  out-collective-16-64K-2023-07-21-node116-0.txt.2
  #  out-collective-16-64K-2023-07-21-node120-0.txt.2
  def _gather(self, target_dir):
    folder_dict = {}
    for root, dirs, files in os.walk(target_dir):
        for file in files:
            file_path = os.path.join(root, file)
            folder_dict[file] = os.path.getsize(file_path)
        for odir in dirs:
            folder_dict[odir] = self._gather(os.path.join(root, odir))
    return folder_dict


  def getMap(self):
    return self.dir_recursive


