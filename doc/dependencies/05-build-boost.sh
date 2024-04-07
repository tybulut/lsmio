#!/bin/sh -x

mkdir -p $HOME/src/packages/05-boost
cd $HOME/src/packages/05-boost

wget https://boostorg.jfrog.io/artifactory/main/release/1.84.0/source/boost_1_84_0.tar.bz2
tar jxf boost_1_84_0.tar.bz2

rm -rf boost_1_84_0
cd boost_1_84_0

./bootstrap.sh \
  --prefix=$HOME/src/usr \
  --with-libraries=filesystem,program_options

./b2 install


