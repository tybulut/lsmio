#!/bin/sh -x

mkdir -p $HOME/src/packages/22-leveldb
cd $HOME/src/packages/22-leveldb

git clone https://github.com/google/leveldb.git

cd leveldb
git submodule update --init
cd ..

rm -rf leveldb-build
mkdir leveldb-build
cd leveldb-build

cmake \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=On \
  -DCMAKE_INSTALL_PREFIX:PATH=$HOME/src/usr \
  -DCMAKE_INSTALL_LIBDIR=lib \
  ../leveldb

make -j16 \
&& make all install

