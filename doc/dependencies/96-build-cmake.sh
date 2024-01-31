#!/bin/sh -x

mkdir -p $HOME/src/packages/96-cmake
cd $HOME/src/packages/96-cmake

git clone https://github.com/Kitware/CMake.git

cd CMake
rm -rf build
mkdir build

cd build
../bootstrap --prefix=$HOME/src/usr --parallel=16

make -j16 \
&& make all install

