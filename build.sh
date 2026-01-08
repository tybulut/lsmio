#!/bin/bash -x

export BS_SCRIPT=`realpath $0`
export BS_DIRNAME=`dirname $BS_SCRIPT`

# Default values
BUILD_TYPE="RELEASE"
DO_CLEAN=false
DO_MAKE=false
DO_TEST=false
DO_INSTALL=false

# Parse arguments
for arg in "$@"; do
  case $arg in
    debug)
      BUILD_TYPE="DEBUG"
      ;;
    clean)
      DO_CLEAN=true
      ;;
    make)
      DO_MAKE=true
      ;;
    test)
      DO_TEST=true
      ;;
    install)
      DO_INSTALL=true
      ;;
  esac
done

if [ "$DO_CLEAN" = true ]; then
  rm -rf build \
  && mkdir -p build
fi

cmake -B build \
  -DCMAKE_BUILD_TYPE=$BUILD_TYPE \
  -DBUILD_SHARED_LIBS=On \
  -DCMAKE_INSTALL_PREFIX:PATH=$HOME/src/usr

pushd build

# make is implied if test or install are requested
if [ "$DO_MAKE" = true ] || [ "$DO_TEST" = true ] || [ "$DO_INSTALL" = true ]; then
  make -j8 || exit 1
fi

if [ "$DO_TEST" = true ]; then
  ctest -j8 || exit 1
fi

if [ "$DO_INSTALL" = true ]; then
  make install || exit 1
fi

popd

