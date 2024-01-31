#!/bin/sh -x

mkdir -p $HOME/src/packages/12-ior
cd $HOME/src/packages/12-ior

git clone https://github.com/hpc/ior.git
cd ior

./bootstrap
./configure \
  --with-hdf5 \
  --prefix=$HOME/src/usr
#  --enable-static --disable-shared \

make -j16 \
&& make install

