#!/bin/sh -x

# Dependencies:
# mpi, openmp 
# debian: libfftw3-dev


mkdir -p $HOME/src/packages/94-gromacs
cd $HOME/src/packages/94-gromacs

git clone https://gitlab.com/gromacs/gromacs.git

rm -rf gromacs-build
mkdir gromacs-build
cd gromacs-build

# DEV: Start 
rm -rf build
mkdir build
cd build

cmake \
  -DCMAKE_INSTALL_PREFIX:PATH=$HOME/src/usr \
  -DCMAKE_CXX_STANDARD_INCLUDE_DIRECTORIES=$HOME/src/usr/include \
  -DCMAKE_CXX_STANDARD_LINK_DIRECTORIES=$HOME/src/usr/lib \
  -DGMX_FFT_LIBRARY=fftw3 \
  -DGMX_MPI=on \
  ..
# DEV: End

make -j 8 
#ctest
#make all install
