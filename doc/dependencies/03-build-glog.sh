#!/bin/sh -x

mkdir -p $HOME/src/packages/03-glog
cd $HOME/src/packages/03-glog

git clone https://github.com/google/glog.git

rm -rf glog-build
mkdir glog-build

cd glog-build
cmake \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=On \
  -DCMAKE_INSTALL_PREFIX:PATH=$HOME/src/usr \
  -DCMAKE_INSTALL_LIBDIR=lib \
  ../glog

make -j16 \
&& make all install

