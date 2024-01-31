#!/bin/sh -x

# Dependencies:
# mpi, openmp, cuda, boost
# debian: libfftw3-dev libblas64-dev libopenblas-openmp-dev collectd-core 


mkdir -p $HOME/src/packages/91-amrex
cd $HOME/src/packages/91-amrex

git clone ssh://git@git.jetbrains.space/lsmio/main/amrex-lsmio.git

cd amrex-lsmio
git checkout lsmio
cd ..

rm -rf amrex-build
mkdir amrex-build
cd amrex-build

# DEV: Start 
rm -rf build
mkdir build
cd build

cmake \
  -DCMAKE_INSTALL_PREFIX:PATH=$HOME/src/usr \
  -DCMAKE_CXX_STANDARD_INCLUDE_DIRECTORIES=$HOME/src/usr/include \
  -DCMAKE_CXX_STANDARD_LINK_DIRECTORIES=$HOME/src/usr/lib \
  -DAMReX_OMP=ON \
  -DAMReX_PARTICLES=ON \
  -DAMReX_MPI_THREAD_MULTIPLE=ON \
  ..
# DEV: End
#  ../amrex-lsmio

make -j 8 
#ctest
#make all install
