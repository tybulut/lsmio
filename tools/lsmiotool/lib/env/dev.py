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
from . import hpcvars

hpcvars.HPC_MANAGER['DEV'] = 'DEV'
hpcvars.LUSTRE_HDD_PATH['DEV'] = os.path.join(hpcvars.HOME, 'scratch')
hpcvars.LUSTRE_SSD_PATH['DEV'] = { 'DEV' : os.path.join(hpcvars.HOME, 'scratch') }
hpcvars.IOR_DIR['DEV'] = { 'DEV' : os.path.join(hpcvars.HOME, 'synthetic', 'dev', 'ior-data') }
hpcvars.IOR_DATA['DEV'] = { 'DEV' : {
  'base': 'ior-base',
  'collective': 'ior-collective',
  'hdf5': 'ior-hdf5',
  'hdf5-collective': 'ior-hdf5-c'
}}
hpcvars.LSMIO_DIR['DEV'] = { 'DEV' : os.path.join(hpcvars.HOME, 'synthetic', 'dev', 'lsmio-data') }
hpcvars.LSMIO_DATA['DEV'] = { 'DEV' : {
  'adios': 'lsmio-adios',
  'plugin': 'lsmio-plugin',
  'lsmio': 'lsmio-rocksdb'
}}
hpcvars.PLOTS_DIR['DEV'] = { 'DEV' : os.path.join(hpcvars.HOME, 'synthetic', 'dev', 'plots') }

