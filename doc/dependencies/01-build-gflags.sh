#!/bin/sh -x

mkdir -p $HOME/src/packages/01-gflags
cd $HOME/src/packages/01-gflags

git clone https://github.com/gflags/gflags.git

rm -rf gflags-build
mkdir gflags-build

cd gflags-build
cmake \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=On \
  -DBUILD_STATIC_LIBS=On \
  -DBUILD_gflags_LIBS=On \
  -DCMAKE_INSTALL_PREFIX:PATH=$HOME/src/usr \
  -DCMAKE_INSTALL_LIBDIR=lib \
  ../gflags

make -j16 \
&& make all install

