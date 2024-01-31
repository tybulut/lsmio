#!/bin/sh -x

# Dependencies:
# mpi, openmp, cuda, boost
# debian: libfftw3-dev libblas64-dev libopenblas-openmp-dev collectd-core 


mkdir -p $HOME/src/packages/95-cp2k
cd $HOME/src/packages/95-cp2k

git clone https://github.com/cp2k/cp2k.git

rm -rf cp2k-build
mkdir cp2k-build
cd cp2k-build

# DEV: Start 
rm -rf build
mkdir build
cd build

cmake \
  -DCMAKE_INSTALL_PREFIX:PATH=$HOME/src/usr \
  -DCMAKE_CXX_STANDARD_INCLUDE_DIRECTORIES=$HOME/src/usr/include \
  -DCMAKE_CXX_STANDARD_LINK_DIRECTORIES=$HOME/src/usr/lib \
  -DCP2K_USE_MPI=ON \
  ..
# DEV: End

make -j 8 
#ctest
#make all install
