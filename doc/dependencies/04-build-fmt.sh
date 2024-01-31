#!/bin/sh -x

mkdir -p $HOME/src/packages/04-fmt
cd $HOME/src/packages/04-fmt

git clone https://github.com/fmtlib/fmt.git

rm -rf fmt-build
mkdir fmt-build

cd fmt-build
cmake \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=On \
  -DCMAKE_INSTALL_PREFIX:PATH=$HOME/src/usr \
  -DCMAKE_INSTALL_LIBDIR=lib \
  ../fmt

make -j16 \
&& make all install

