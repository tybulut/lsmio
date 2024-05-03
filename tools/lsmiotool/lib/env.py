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

import os, sys, platform
from datetime import datetime

# Relative paths stored as a list to be concentenated later
_REL_PROJECT_DIR = ['src', 'usr', 'bin']
_REL_BIN_DIR = ['src', 'usr', 'bin']
_REL_LIB_DIR = ['src', 'usr', 'lib']

# OS Environment
USER = os.environ['USER']
HOME = os.environ['HOME']
LD_LIBRARY_PATH = os.environ['HOME']

# Data Environment
_LSMIO_DATA_DIR = ['src', 'lsmio-data']

_VIKING_IOR_DIR = _LSMIO_DATA_DIR + ['synthetic', 'viking', 'ior-small-hdd']
_VIKING_LSMIO_DIR = _LSMIO_DATA_DIR + ['synthetic', 'viking', 'lsmio-small-hdd']
VIKING_IOR_DIR = os.path.join(HOME, *_VIKING_IOR_DIR)
VIKING_IOR_DATA = {
  'base': 'ior-base',
  'collective': 'ior-collective',
  'hdf5': 'ior-hdf5',
  'hdf5-collective': 'ior-hdf5-c'
}
VIKING_LSMIO_DIR = os.path.join(HOME, *_VIKING_LSMIO_DIR)
VIKING_LSMIO_DATA = {
  'adios': 'lsmio-adios-m-yes',
  'plugin': 'lsmio-plugin-m-yes',
  'lsmio': 'lsmio-rocksdb-m-yes'
}
_VIKING_PLOTS_DIR = _LSMIO_DATA_DIR + ['synthetic', 'viking', 'plots']
VIKING_PLOTS_DIR = os.path.join(HOME, *_VIKING_PLOTS_DIR)

_VIKING2_IOR_DIR = _LSMIO_DATA_DIR + ['synthetic', 'viking2', 'ior-small-hdd']
_VIKING2_LSMIO_DIR = _LSMIO_DATA_DIR + ['synthetic', 'viking2', 'lsmio-small-hdd']
VIKING2_IOR_DIR = os.path.join(HOME, *_VIKING2_IOR_DIR)
VIKING2_IOR_DATA = {
  'base': 'ior-base',
  'collective': 'ior-collective',
  'hdf5': 'ior-hdf5',
  'hdf5-collective': 'ior-hdf5-c'
}
VIKING2_LSMIO_DIR = os.path.join(HOME, *_VIKING2_LSMIO_DIR)
VIKING2_LSMIO_DATA = {
  'adios': 'lsmio-adios-m',
  'plugin': 'lsmio-plugin-m',
  'lsmio': 'lsmio-rocksdb-m'
}
_VIKING2_PLOTS_DIR = _LSMIO_DATA_DIR + ['synthetic', 'viking2', 'plots']
VIKING2_PLOTS_DIR = os.path.join(HOME, *_VIKING2_PLOTS_DIR)

_ISAMBARD_XCI_IOR_DIR = _LSMIO_DATA_DIR + ['synthetic', 'isambard.xci', 'ior-small-hdd']
_ISAMBARD_XCI_LSMIO_DIR = _LSMIO_DATA_DIR + ['synthetic', 'isambard.xci', 'lsmio-small-hdd']
ISAMBARD_XCI_IOR_DIR = os.path.join(HOME, *_ISAMBARD_XCI_IOR_DIR)
ISAMBARD_XCI_IOR_DATA = {
  'base': 'ior-base',
  'collective': 'ior-collective',
  'hdf5': 'ior-hdf5',
  'hdf5-collective': 'ior-hdf5-c'
}
ISAMBARD_XCI_LSMIO_DIR = os.path.join(HOME, *_ISAMBARD_XCI_LSMIO_DIR)
ISAMBARD_XCI_LSMIO_DATA = {
  'adios': 'lsmio-adios-m',
  'plugin': 'lsmio-plugin-m',
  'lsmio': 'lsmio-rocksdb-m'
}
_ISAMBARD_XCI_PLOTS_DIR = _LSMIO_DATA_DIR + ['synthetic', 'isambard.xci', 'plots']
ISAMBARD_XCI_PLOTS_DIR = os.path.join(HOME, *_ISAMBARD_XCI_PLOTS_DIR)

# Determine HPC cluster
UNKNOWN_HPC_ENVIRONMENT = \
'''############################################
# ERROR: Uknown HPC Environment            #
############################################
'''
HOSTNAME = platform.node()
if HOSTNAME.startswith('xci') or HOSTNAME.startswith('nid'):
  HPC_ENV = 'ISAMBARD'
  HPC_MANAGER = 'PBS'

  LUSTRE_HDD_PATH = '/projects/external/ri-sbulut'
  LUSTRE_SSD_PATH = '/scratch'
elif 'viking2' in HOSTNAME:
  HPC_ENV = 'VIKING2'
  HPC_MANAGER = 'SLURM'

  LUSTRE_HDD_PATH = '/mnt/scratch'
  LUSTRE_SSD_PATH = '/mnt/scratch'
elif 'viking' in HOSTNAME:
  HPC_ENV = 'VIKING'
  HPC_MANAGER = 'SLURM'

  LUSTRE_HDD_PATH = '/mnt/lustre'
  LUSTRE_SSD_PATH = '/mnt/bb/tmp'
elif 'hp15' in HOSTNAME:
  HPC_ENV = 'DEV'
  HPC_MANAGER = 'DEV'

  LUSTRE_HDD_PATH = os.path.join(HOME, 'scratch')
  LUSTRE_SSD_PATH = os.path.join(HOME, 'scratch')
else:
  print(UNKNOWN_HPC_ENVIRONMENT)
  exit(1)

# Benchmark Environment
DS = datetime.today().strftime('%Y-%m-%d')
PROJECT_DIR = os.path.join(HOME, *_REL_PROJECT_DIR)
BIN_DIR = os.path.join(HOME, *_REL_BIN_DIR)
LIB_DIR = os.path.join(HOME, *_REL_LIB_DIR)

if False:
  LUSTRE_PATH = LUSTRE_SSD_PATH
else:
  LUSTRE_PATH = LUSTRE_HDD_PATH

BM_DIR = os.path.join(LUSTRE_PATH, 'users', USER, 'benchmark')

os.environ['PATH'] += ':' + BIN_DIR
os.environ['LD_LIBRARY_PATH'] += ':' + LIB_DIR
os.environ['ADIOS2_PLUGIN_PATH'] = LIB_DIR


