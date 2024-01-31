#!/bin/sh -x

# Dependencies:
# mpi, openmp, cuda, boost
# debian: libfftw3-dev libblas64-dev libopenblas-openmp-dev collectd-core 

mkdir -p $HOME/src/packages/92-warpx
cd $HOME/src/packages/92-warpx

git clone ssh://git@git.jetbrains.space/lsmio/main/warpx-lsmio.git

cd warpx-lsmio
git checkout lsmio
cd ..

rm -rf warpx-build
mkdir warpx-build
cd warpx-build

# DEV: Start 
rm -rf build
mkdir build
cd build

# Fresh checkout
#  -DWarpX_amrex_repo="ssh://git@git.jetbrains.space/lsmio/main/amrex-lsmio.git" \
#  -DWarpX_amrex_repo=lsmio \

DIMS=2
cmake \
  -DWarpX_DIMS=$DIMS \
  -DCMAKE_INSTALL_PREFIX:PATH=$HOME/src/usr \
  -DCMAKE_CXX_STANDARD_INCLUDE_DIRECTORIES=$HOME/src/usr/include \
  -DCMAKE_CXX_STANDARD_LINK_DIRECTORIES=$HOME/src/usr/lib \
  -DWarpX_amrex_src=$HOME/src/packages/91-amrex/amrex-lsmio \
  ..
# DEV: End
  #-DWarpX_LSMIO=OFF \
  #-DWarpX_amrex_src=$HOME/src/packages/91-amrex/amrex-lsmio \
  #../warpx-lsmio


make -j 8 
#ctest
#make all install
