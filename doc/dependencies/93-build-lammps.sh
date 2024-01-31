#!/bin/sh -x

# Dependencies:
# mpi, adios2, openmp, cuda, boost, clang-format-13, libpng


mkdir -p $HOME/src/packages/93-lammps
cd $HOME/src/packages/93-lammps

git clone ssh://git@git.jetbrains.space/lsmio/main/lammps-lsmio.git

rm -rf lammps-build
mkdir lammps-build
cd lammps-build

# DEV: Start 
rm -rf build
mkdir build
cd build

#  -DCMAKE_BUILD_TYPE=Debug \
#  -DENABLE_COVERAGE=ON \
#  -DBUILD_SHARED_LIBS=On \
cmake \
  -DCMAKE_INSTALL_PREFIX:PATH=$HOME/src/usr \
  -DCMAKE_CXX_STANDARD_INCLUDE_DIRECTORIES=$HOME/src/usr/include \
  -DCMAKE_CXX_STANDARD_LINK_DIRECTORIES=$HOME/src/usr/lib \
  -DCMAKE_INSTALL_LIBDIR=lib \
  -DBUILD_MPI=ON \
  -DBUILD_OMP=ON \
  -DFFT=fftw3 \
  -DPKG_ADIOS=ON \
  -DPKG_COLVARS=ON \
  -DPKG_COMPRESS=ON \
  -DPKG_H5MD=ON \
  -DPKG_KSPACE=ON \
  -DPKG_LSMIO=ON \
  -DPKG_MPI=ON \
  -DPKG_MPIIO=ON \
  -DPKG_MOLECULE=ON \
  -DPKG_OPENMP=ON \
  -DPKG_REAXFF=ON \
  -DPKG_RIGID=ON \
  -DWITH_JPEG=ON \
  -DWITH_PNG=ON \
  -DWITH_GZIP=ON \
  ../cmake
# DEV: End
#  ../lammps-lsmio/cmake

make -j 16 \
&& make all install

#make -j 8
#ctest
