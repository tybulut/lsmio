#!/bin/sh -x

mkdir -p $HOME/src/packages/23-rocksdb
cd $HOME/src/packages/23-rocksdb

git clone https://github.com/facebook/rocksdb.git

cd rocksdb
git checkout v10.6.2
git submodule update --init
cd ..

rm -rf rocksdb-build
mkdir rocksdb-build
cd rocksdb-build

# Compression codecs: RocksDB builds none of them unless asked, and then the store has nothing to
# compress with. On macOS the codec libraries come from Homebrew (brew install snappy lz4 zstd),
# which CMake finds through the Homebrew prefix. Codecs built from source reside in $HOME/src/usr.
PREFIX_PATH="$HOME/src/usr"
if [ "$(uname -s)" = "Darwin" ]; then
  PREFIX_PATH="$(brew --prefix);$PREFIX_PATH"
fi

cmake \
  -DCMAKE_PREFIX_PATH="$PREFIX_PATH" \
  -DWITH_SNAPPY=ON \
  -DWITH_LZ4=ON \
  -DWITH_ZSTD=ON \
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
  -DFAIL_ON_WARNINGS=OFF \
  ../rocksdb

make -j16 \
&& make install

#DEBUG_LEVEL=0 make -j8 shared_lib
#DEBUG_LEVEL=0 make install-shared

#DEBUG_LEVEL=0 make -j8 static_lib
#DEBUG_LEVEL=0 make install-shared

