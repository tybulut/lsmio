#!/bin/sh -x

mkdir -p $HOME/src/packages/22-leveldb
cd $HOME/src/packages/22-leveldb

git clone https://github.com/google/snappy.git

rm -rf snappy-build
mkdir snappy-build
cd snappy-build

cmake \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=ON \
  -DCMAKE_INSTALL_PREFIX:PATH=$HOME/src/usr \
  -DCMAKE_INSTALL_LIBDIR=lib \
  -DSNAPPY_BUILD_TESTS=OFF \
  -DSNAPPY_BUILD_BENCHMARKS=OFF \
  ../snappy

make -j16 \
&& make all install


cd $HOME/src/packages/22-leveldb

git clone https://github.com/google/leveldb.git

cd leveldb
git submodule update
cd ..

rm -rf leveldb-build
mkdir leveldb-build
cd leveldb-build

cmake \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=On \
  -DCMAKE_INSTALL_PREFIX:PATH=$HOME/src/usr \
  -DCMAKE_INSTALL_LIBDIR=lib \
  -DLEVELDB_BUILD_TESTS=OFF \
  -DLEVELDB_BUILD_BENCHMARKS=OFF \
  -DCMAKE_CXX_STANDARD=17 \
  ../leveldb

make -j16 \
&& make all install

