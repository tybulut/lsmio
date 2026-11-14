#!/bin/sh -x

mkdir -p $HOME/src/packages/22-leveldb
cd $HOME/src/packages/22-leveldb

git clone https://github.com/google/snappy.git

cd snappy
git checkout 1.3.1 || exit 1
cd ..

rm -rf snappy-build
mkdir snappy-build
cd snappy-build

cmake \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CXX_FLAGS_RELEASE="-O3 -DNDEBUG -frtti" \
  -DBUILD_SHARED_LIBS=ON \
  -DCMAKE_INSTALL_PREFIX:PATH=$HOME/src/usr \
  -DCMAKE_INSTALL_LIBDIR=lib \
  -DSNAPPY_BUILD_TESTS=OFF \
  -DSNAPPY_BUILD_BENCHMARKS=OFF \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
  ../snappy

make -j16 \
&& make all install


cd $HOME/src/packages/22-leveldb

git clone https://github.com/google/leveldb.git

cd leveldb
git checkout 1.23 || exit 1
git submodule update
cd ..

rm -rf leveldb-build
mkdir leveldb-build
cd leveldb-build

# LevelDB's CMakeLists.txt strips -frtti from CMAKE_CXX_FLAGS and appends -fno-rtti; the
# per-config flags come after it on the compile line, so -frtti there wins (lsmio's no-sync
# Env derives from LevelDB classes). Snappy lives in $HOME/src/usr: its include and library
# paths let LevelDB's check_library_exists(snappy ...) find it and link it in.
cmake \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CXX_FLAGS="-I$HOME/src/usr/include" \
  -DCMAKE_CXX_FLAGS_RELEASE="-O3 -DNDEBUG -frtti" \
  -DCMAKE_REQUIRED_LINK_OPTIONS="-L$HOME/src/usr/lib" \
  -DCMAKE_SHARED_LINKER_FLAGS="-L$HOME/src/usr/lib -Wl,-rpath,$HOME/src/usr/lib" \
  -DCMAKE_EXE_LINKER_FLAGS="-L$HOME/src/usr/lib -Wl,-rpath,$HOME/src/usr/lib" \
  -DBUILD_SHARED_LIBS=On \
  -DCMAKE_INSTALL_PREFIX:PATH=$HOME/src/usr \
  -DCMAKE_INSTALL_LIBDIR=lib \
  -DLEVELDB_BUILD_TESTS=OFF \
  -DLEVELDB_BUILD_BENCHMARKS=OFF \
  -DCMAKE_CXX_STANDARD=17 \
  ../leveldb

make -j16 \
&& make all install

