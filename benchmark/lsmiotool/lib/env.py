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


