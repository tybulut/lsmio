#!/bin/sh -x

mkdir -p $HOME/src/packages/05-CLI11
cd $HOME/src/packages/05-CLI11

git clone https://github.com/CLIUtils/CLI11.git

cd CLI11
git checkout v2.4.2
cd ..

rm -rf CLI11-build
mkdir CLI11-build

cd CLI11-build
cmake \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=On \
  -DCLI11_BUILD_TESTS=Off \
  -DCMAKE_INSTALL_PREFIX:PATH=$HOME/src/usr \
  ../CLI11

make -j16 \
&& make all install

