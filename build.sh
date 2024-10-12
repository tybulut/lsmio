#!/bin/bash -x

export BS_SCRIPT=`realpath $0`
export BS_DIRNAME=`dirname $BS_SCRIPT`

if [ "$1" = "clean" ]; then
  rm -rf build \
  && mkdir -p build
fi

if [ "$2" = "debug" ]; then
  cmake -B build \
    -DCMAKE_BUILD_TYPE=DEBUG \
    -DBUILD_SHARED_LIBS=On \
    -DCMAKE_INSTALL_PREFIX:PATH=$HOME/src/usr
else
  cmake -B build \
    -DCMAKE_BUILD_TYPE=RELEASE \
    -DBUILD_SHARED_LIBS=On \
    -DCMAKE_INSTALL_PREFIX:PATH=$HOME/src/usr
fi
pushd build

if [ "$1" = "test" ]; then
  make -j8 \
  && ctest -j8 \
  && popd
  #ctest .. -j8 --rerun-failed --output-on-failure
elif [ "$1" = "install" ]; then
  make -j8 \
  && make install \
  && popd
elif [ "$1" = "make" ]; then
  make -j8 \
  && popd
fi

