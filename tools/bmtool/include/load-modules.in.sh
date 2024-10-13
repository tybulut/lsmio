#

#  module load data/HDF5/1.12.2-gompi-2022a
load_modules_viking() {
  module load data/HDF5/1.10.7-gompi-2020b
  module load compiler/GCC/11.3.0
  module load devel/CMake/3.24.3-GCCcore-11.3.0
  module load mpi/OpenMPI/4.1.4-GCC-11.3.0
  module load lib/zlib/1.2.12-GCCcore-11.3.0
  module load lib/lz4/1.9.3-GCCcore-11.3.0
  module load lib/libunwind/1.6.2-GCCcore-11.3.0
  module load lib/OpenJPEG/2.5.0-GCCcore-11.3.0
  module load numlib/FFTW/3.3.10-GCC-11.3.0
}

load_modules_viking2() {
  module load HDF5/1.14.0-gompi-2023a
  module load GCCcore/12.3.0
  module load CMake/3.26.3-GCCcore-12.3.0
  module load OpenMPI/4.1.5-GCC-12.3.0
  module load zlib/1.2.13-GCCcore-12.3.0
  module load lz4/1.9.4-GCCcore-12.3.0
  module load libunwind/1.6.2-GCCcore-12.3.0
  module load OpenJPEG/2.5.0-GCCcore-12.3.0
  module load FFTW/3.3.10-GCC-12.3.0
}

load_modules_isambard() {
  module load modules/3.2.11.4
  module load system-config/3.6.3070-7.0.2.1_7.3__g40f385a9.ari
  module load craype-network-aries
  module load Base-opts/2.4.142-7.0.2.1_2.69__g8f27585.ari
  module load alps/6.6.59-7.0.2.1_3.62__g872a8d62.ari
  # module load cce/11.0.4
  module load nodestat/2.3.89-7.0.2.1_2.53__g8645157.ari
  module load craype/2.6.2
  module load sdb/3.3.812-7.0.2.1_2.74__gd6c4e58.ari
  module load cray-libsci/20.09.1
  module load udreg/2.3.2-7.0.2.1_2.24__g8175d3d.ari
  module load pmi/5.0.17
  module load ugni/6.0.14.0-7.0.2.1_3.24__ge78e5b0.ari
  module load atp/3.11.7
  module load gni-headers/5.0.12.0-7.0.2.1_2.27__g3b1768f.ari
  module load rca/2.2.20-7.0.2.1_2.76__g8e3fb5b.ari
  module load dmapp/7.1.1-7.0.2.1_2.75__g38cf134.ari
  module load perftools-base/21.05.0
  module load xpmem/2.2.20-7.0.2.1_2.61__g87eb960.ari
  #module load PrgEnv-cray/6.0.9
  module load llm/21.4.629-7.0.2.1_2.53__g8cae6ef.ari
  module load cray-mpich/7.7.17
  #  Additions
  module load gcc/10.3.0
  module load tools/cmake/3.24.2
  module load PrgEnv-gnu/6.0.9
  #module load cray-mpich/7.7.17
  module load cray-mpich-abi/7.7.17
  module load cray-hdf5-parallel/1.12.0.4
  module load cray-fftw/3.3.8.10
  #  Additions
  module load gdb4hpc/4.10.6
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




