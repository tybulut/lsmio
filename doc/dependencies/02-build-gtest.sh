#!/bin/sh -x

mkdir -p $HOME/src/packages/02-gtest
cd $HOME/src/packages/02-gtest

git clone https://github.com/google/googletest.git

cd googletest
git checkout v1.14.x
cd ..

rm -rf googletest-build
mkdir googletest-build

cd googletest-build
cmake \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=On \
  -DCMAKE_INSTALL_PREFIX:PATH=$HOME/src/usr \
  -DCMAKE_INSTALL_LIBDIR=lib \
  ../googletest

make -j16 \
&& make all install

