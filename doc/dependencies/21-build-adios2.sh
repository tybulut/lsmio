#!/bin/sh -x

mkdir -p $HOME/src/packages/21-adios2
cd $HOME/src/packages/21-adios2

git clone https://github.com/ornladios/ADIOS2.git

cd ADIOS2
# v2.11.0: release_29 (2.9.2) segfaults in BP5 reads once a step holds ~2 GiB
# of string values (bm_adios 64K point); fetch so an existing clone sees the tag
git fetch --tags
git checkout v2.11.0
cd ..

rm -rf ADIOS2-BUILD
mkdir ADIOS2-BUILD

cd ADIOS2-BUILD
# OpenSSL=OFF: lsmio needs no HTTPS/remote transport, and with an NSS module
# loaded FindOpenSSL can pair OpenSSL's libcrypto with NSS's libssl.a, leaving
# libadios2_core with undefined SSL_* symbols
cmake \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=On \
  -DADIOS2_USE_MPI=ON \
  -DADIOS2_USE_HDF5=ON \
  -DADIOS2_USE_OpenSSL=OFF \
  -DCMAKE_INSTALL_PREFIX:PATH=$HOME/src/usr \
  -DBUILD_TESTING=OFF \
  -DADIOS2_BUILD_EXAMPLES=OFF \
  -DCMAKE_INSTALL_LIBDIR=lib \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
  ../ADIOS2

make -j16 \
&& make all install

