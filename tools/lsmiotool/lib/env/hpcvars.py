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

import os, platform
from datetime import datetime

HOSTNAME = platform.node()
HPC_ENV = 'DEV'

USER = os.environ['USER']
HOME = os.environ['HOME']
LD_LIBRARY_PATH = os.environ['HOME']

REL_PROJECT_DIR = ['src', 'usr', 'bin']
REL_BIN_DIR = ['src', 'usr', 'bin']
REL_LIB_DIR = ['src', 'usr', 'lib']

DS = datetime.today().strftime('%Y-%m-%d')
PROJECT_DIR = os.path.join(HOME, *REL_PROJECT_DIR)
BIN_DIR = os.path.join(HOME, *REL_BIN_DIR)
LIB_DIR = os.path.join(HOME, *REL_LIB_DIR)

IOR_DATA_DIR = ['src', 'ior-data']
LSMIO_DATA_DIR = ['src', 'lsmio-data']

HPC_MANAGER = {}
LUSTRE_HDD_PATH = {}
LUSTRE_SSD_PATH = {}
IOR_DIR = {}
IOR_DATA = {}
LSMIO_DIR = {}
LSMIO_DATA = {}
PLOTS_DIR = {}

