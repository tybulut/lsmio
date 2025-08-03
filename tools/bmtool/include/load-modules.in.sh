#

# Helper
load_modules() {
  IFS="
"
  for module in $1
  do
    echo "Loading module: $module"
    module load $module
  done
}

#  module load data/HDF5/1.12.2-gompi-2022a
load_modules_viking() {
  MODULES="
data/HDF5/1.10.7-gompi-2020b
compiler/GCC/11.3.0
devel/CMake/3.24.3-GCCcore-11.3.0
mpi/OpenMPI/4.1.4-GCC-11.3.0
lib/zlib/1.2.12-GCCcore-11.3.0
lib/lz4/1.9.3-GCCcore-11.3.0
lib/libunwind/1.6.2-GCCcore-11.3.0
lib/OpenJPEG/2.5.0-GCCcore-11.3.0
numlib/FFTW/3.3.10-GCC-11.3.0
"
  load_modules "$MODULES"
}

load_modules_viking2() {
  MODULES="
GCCcore/12.3.0
Clang/16.0.6-GCCcore-12.3.0
CMake/3.26.3-GCCcore-12.3.0
Automake/1.16.5-GCCcore-12.3.0
Autoconf/2.71-GCCcore-12.3.0
libtool/2.4.7-GCCcore-12.3.0
OpenMPI/4.1.5-GCC-12.3.0
zlib/1.2.13-GCCcore-12.3.0
lz4/1.9.4-GCCcore-12.3.0
libunwind/1.6.2-GCCcore-12.3.0
OpenJPEG/2.5.0-GCCcore-12.3.0
FFTW/3.3.10-GCC-12.3.0
gflags/2.2.2-GCCcore-12.3.0
bzip2/1.0.8-GCCcore-12.3.0
HDF5/1.14.0-gompi-2023a
SciPy-bundle/2023.07-gfbf-2023a
matplotlib/3.7.2-gfbf-2023a
Perl/5.36.1-GCCcore-12.3.0
Perl-bundle-CPAN/5.36.1-GCCcore-12.3.0
gnuplot/5.4.8-GCCcore-12.3.0
texlive/20230313-GCC-12.3.0
"
  load_modules "$MODULES"
}

load_modules_isambard() {
  MODULES="
modules/3.2.11.4
system-config/3.6.3070-7.0.2.1_7.3__g40f385a9.ari
craype-network-aries
Base-opts/2.4.142-7.0.2.1_2.69__g8f27585.ari
alps/6.6.59-7.0.2.1_3.62__g872a8d62.ari
nodestat/2.3.89-7.0.2.1_2.53__g8645157.ari
craype/2.6.2
sdb/3.3.812-7.0.2.1_2.74__gd6c4e58.ari
cray-libsci/20.09.1
udreg/2.3.2-7.0.2.1_2.24__g8175d3d.ari
pmi/5.0.17
ugni/6.0.14.0-7.0.2.1_3.24__ge78e5b0.ari
atp/3.11.7
gni-headers/5.0.12.0-7.0.2.1_2.27__g3b1768f.ari
rca/2.2.20-7.0.2.1_2.76__g8e3fb5b.ari
dmapp/7.1.1-7.0.2.1_2.75__g38cf134.ari
perftools-base/21.05.0
xpmem/2.2.20-7.0.2.1_2.61__g87eb960.ari
llm/21.4.629-7.0.2.1_2.53__g8cae6ef.ari
cray-mpich/7.7.17
gcc/10.3.0
tools/cmake/3.24.2
PrgEnv-gnu/6.0.9
cray-mpich-abi/7.7.17
cray-hdf5-parallel/1.12.0.4
cray-fftw/3.3.8.10
gdb4hpc/4.10.6
"
  load_modules "$MODULES"
}

list_modules() {
  module list
}

purge_modules() {
  module purge
}


echo "Loading modules for: $HPC_ENV"
purge_modules

if [ "$HPC_ENV" = "isambard" ]; then
  load_modules_isambard
elif [ "$HPC_ENV" = "viking" ]; then
  load_modules_viking
elif [ "$HPC_ENV" = "viking2" ]; then
  load_modules_viking2
else
  unknown_hpc_environment
fi

