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

import os, sys
from . import hpcvars
from . import dev
from . import isambard
from . import viking
from . import viking2


ERROR_UNKNOWN_HPC = \
'''############################################
# ERROR: Unknown HPC Environment            #
############################################
'''

# Determine HPC cluster
if hpcvars.HOSTNAME.startswith('xci') or hpcvars.HOSTNAME.startswith('nid'):
  hpcvars.HPC_ENV = 'ISAMBARD'
elif 'viking2' in hpcvars.HOSTNAME:
  hpcvars.HPC_ENV = 'VIKING2'
elif 'viking' in hpcvars.HOSTNAME:
  hpcvars.HPC_ENV = 'VIKING'
elif 'hp15' in hpcvars.HOSTNAME or 'mba-sbulut' in hpcvars.HOSTNAME:
  hpcvars.HPC_ENV = 'DEV'
else:
  print(ERROR_UNKNOWN_HPC)
  exit(1)

USE_SSD = False
if USE_SSD:
  LUSTRE_PATH = hpcvars.LUSTRE_SSD_PATH[hpcvars.HPC_ENV]
else:
  LUSTRE_PATH = hpcvars.LUSTRE_HDD_PATH[hpcvars.HPC_ENV]

BM_DIR = os.path.join(LUSTRE_PATH, 'users', hpcvars.USER, 'benchmark')

os.environ['PATH'] += ':' + hpcvars.BIN_DIR
if 'LD_LIBRARY_PATH' in os.environ:
  os.environ['LD_LIBRARY_PATH'] += ':' + hpcvars.LIB_DIR
else:
  os.environ['LD_LIBRARY_PATH'] = hpcvars.LIB_DIR
os.environ['ADIOS2_PLUGIN_PATH'] = hpcvars.LIB_DIR


