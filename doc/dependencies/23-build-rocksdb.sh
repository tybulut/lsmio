#!/bin/sh -x

mkdir -p $HOME/src/packages/23-rocksdb
cd $HOME/src/packages/23-rocksdb

git clone https://github.com/facebook/rocksdb.git

cd rocksdb
git checkout 8.1.fb
git submodule update --init
cd ..

rm -rf rocksdb-build
mkdir rocksdb-build
cd rocksdb-build

cmake \
  -DCMAKE_BUILD_TYPE=Release \
  -DROCKSDB_BUILD_SHARED=On \
  -DWITH_TOOLS=On \
  -DUSE_RTTI=On \
  -DWITH_BENCHMARK_TOOLS=Off \
  -DWITH_TESTS=Off \
  -DWITH_JNI=Off \
  -DJNI=Off \
  -DCMAKE_INSTALL_PREFIX:PATH=$HOME/src/usr \
  -DCMAKE_INSTALL_LIBDIR=lib \
  ../rocksdb

make -j16 \
&& make install

#DEBUG_LEVEL=0 make -j8 shared_lib
#DEBUG_LEVEL=0 make install-shared

#DEBUG_LEVEL=0 make -j8 static_lib
#DEBUG_LEVEL=0 make install-shared

#make -j8 all

