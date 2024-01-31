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
  module load devel/Boost/1.79.0-GCC-11.3.0
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
  module load Boost/1.82.0-GCC-12.3.0
  module load OpenJPEG/2.5.0-GCCcore-12.3.0
  module load FFTW/3.3.10-GCC-12.3.0
}

load_modules_isambard() {
  module load hdf5/1.10.1
  module load gcc/9.2.0
  module load openmpi/gcc/64/1.10.7
  module load boost/1.71.0
  module load fftw3/openmpi/gcc/64/3.3.8
}


list_modules() {
  module list
}

purge_modules() {
  module purge
}

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




