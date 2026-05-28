#!/bin/sh -x

mkdir -p $HOME/src/packages/21-adios2
cd $HOME/src/packages/21-adios2

git clone https://github.com/ornladios/ADIOS2.git

cd ADIOS2
git checkout release_29
cd ..

rm -rf ADIOS2-BUILD
mkdir ADIOS2-BUILD

cd ADIOS2-BUILD
cmake \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=On \
  -DADIOS2_USE_MPI=ON \
  -DADIOS2_USE_HDF5=ON \
  -DCMAKE_INSTALL_PREFIX:PATH=$HOME/src/usr \
  -DBUILD_TESTING=OFF \
  -DADIOS2_BUILD_EXAMPLES=OFF \
  -DCMAKE_INSTALL_LIBDIR=lib \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
  ../ADIOS2

make -j16 \
&& make all install

