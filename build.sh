#!/bin/bash -x

export BS_SCRIPT=`realpath $0`
export BS_DIRNAME=`dirname $BS_SCRIPT`

if [ "$1" = "clean" ]; then
  $BS_DIRNAME/clean.sh
fi

rm -rf build \
&& mkdir -p build

if [ "$1" = "debug" ]; then
  cmake -B build \
    -DCMAKE_BUILD_TYPE=DEBUG \
    -DBUILD_SHARED_LIBS=On \
    -DCMAKE_INSTALL_PREFIX:PATH=$HOME/src/usr \
    -DCMAKE_INSTALL_LIBDIR=lib
else
  cmake -B build \
    -DCMAKE_BUILD_TYPE=RELEASE \
    -DBUILD_SHARED_LIBS=On \
    -DCMAKE_INSTALL_PREFIX:PATH=$HOME/src/usr \
    -DCMAKE_INSTALL_LIBDIR=lib
fi
pushd build

if [ "$2" = "test" ]; then
  make -j8 \
  && ctest -j8 \
  && popd
  #ctest .. -j8 --rerun-failed --output-on-failure
elif [ "$2" = "install" ]; then
  make -j8 \
  && make install \
  && popd
else
  make -j8 \
  && popd
fi

