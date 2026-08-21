#!/bin/bash -x

export BS_SCRIPT=`realpath $0`
export BS_DIRNAME=`dirname $BS_SCRIPT`

# Default values
BUILD_TYPE="RELEASE"
DO_CLEAN=false
DO_MAKE=false
DO_TEST=false
DO_XTEST=false
DO_PTEST=false
DO_INSTALL=false
DO_COVERAGE=false

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
    xtest)
      DO_XTEST=true
      ;;
    ptest)
      DO_PTEST=true
      ;;
    install)
      DO_INSTALL=true
      ;;
    coverage)
      DO_COVERAGE=true
      DO_TEST=true
      BUILD_TYPE="DEBUG"
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
  -DCMAKE_INSTALL_PREFIX:PATH=$HOME/src/usr \
  -DLSMIO_ENABLE_COVERAGE=$DO_COVERAGE

pushd build

# make is implied if test or install are requested
if [ "$DO_MAKE" = true ] || [ "$DO_TEST" = true ] || [ "$DO_INSTALL" = true ]; then
  make -j8 || exit 1
fi

CTEST_FAILED=0
if [ "$DO_TEST" = true ]; then
  if [ "$DO_COVERAGE" = true ]; then
    export LLVM_PROFILE_FILE="coverage-%p.profraw"
  fi
  ctest -j8 || CTEST_FAILED=1
fi

if [ "$DO_XTEST" = true ]; then
  ctest -j8 --output-on-failure -Q --timeout 120 || exit 1
fi

if [ "$DO_PTEST" = true ]; then
  pushd "$BS_DIRNAME/tools/lsmiotool" && ./lsmiotool test || exit 1
  popd
fi

if [ "$DO_INSTALL" = true ]; then
  make install || exit 1
fi

if [ "$DO_COVERAGE" = true ]; then
  echo "Generating lsmiotool Python coverage report..."
  cmake --build . --target lsmiotool_python_coverage_report || exit 1

  echo "Generating coverage report..."
  
  if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS: Use llvm-profdata and llvm-cov
    xcrun llvm-profdata merge -sparse $(find . -name "coverage-*.profraw") -o coverage.profdata
    
    # We need to target the shared library or executable that has the coverage mapping.
    # Note: llvm-cov requires the exact binary that produced the profile.
    
    # Terminal Summary
    echo ""
    echo "Coverage Summary:"
    echo "-----------------"
    xcrun llvm-cov report -instr-profile=coverage.profdata \
      -ignore-filename-regex="(test|benchmark|/usr/|/opt/|/Applications/)" \
      $(find lib -name "*.dylib")
    echo "-----------------"
    echo ""

    xcrun llvm-cov show -instr-profile=coverage.profdata \
      -format=html -output-dir=coverage_report \
      -ignore-filename-regex="(test|benchmark|/usr/|/opt/|/Applications/)" \
      $(find lib -name "*.dylib")
      
    echo "Coverage report generated at build/coverage_report/index.html"
  else
    # Linux/GCC: Use lcov
    # Capture coverage data
    lcov --capture --directory . --output-file coverage.info
    # Filter out unwanted files (system headers, tests, etc.)
    lcov --remove coverage.info '/usr/*' '*/test/*' '*/benchmark/*' --output-file coverage.filtered.info
    
    # Terminal Summary
    lcov --list coverage.filtered.info
    
    # Generate HTML report
    genhtml coverage.filtered.info --output-directory coverage_report
    echo "Coverage report generated at build/coverage_report/index.html"
  fi
fi

if [ "$CTEST_FAILED" -ne 0 ]; then
  exit 1
fi

popd

