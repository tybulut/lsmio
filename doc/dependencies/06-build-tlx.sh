#!/bin/sh -x

PREFIX="${PREFIX:-${PROJECT_DIR:-$HOME/src/usr}}"

mkdir -p $HOME/src/packages/06-tlx
cd $HOME/src/packages/06-tlx

git clone https://github.com/tlx/tlx.git

cd tlx
git checkout v0.6.1
cd ..

rm -rf tlx-build
mkdir tlx-build

cd tlx-build
cmake \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=On \
  -DTLX_BUILD_TESTS=OFF \
  -DCMAKE_INSTALL_PREFIX:PATH=$PREFIX \
  -DCMAKE_INSTALL_LIBDIR=lib \
  ../tlx

make -j16 \
&& make all install
