#!/bin/sh -x

export BS_SCRIPT=`realpath $0`
export BS_DIRNAME=`dirname $BS_SCRIPT`

$BS_DIRNAME/clean.sh

rm -rf build \
&& mkdir -p build \
&& cd build

#  -DCMAKE_BUILD_TYPE=Release \
cmake .. \
  -DBUILD_SHARED_LIBS=On \
  -DCMAKE_INSTALL_PREFIX:PATH=$HOME/src/usr \
  -DCMAKE_INSTALL_LIBDIR=lib

make -j8

#&& make -j4 \
#&& ctest .. -j4
#&& ctest .. -j4 --rerun-failed --output-on-failure
#&& ctest .. --verbose


