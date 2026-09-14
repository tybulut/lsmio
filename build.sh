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

detect_num_cores() {
  if command -v nproc >/dev/null 2>&1; then
    nproc 2>/dev/null || echo 0
  elif command -v sysctl >/dev/null 2>&1; then
    sysctl -n hw.logicalcpu 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 0
  elif command -v getconf >/dev/null 2>&1; then
    getconf _NPROCESSORS_ONLN 2>/dev/null || echo 0
  else
    echo 0
  fi
}

detect_total_ram_gb() {
  if [ -f /proc/meminfo ]; then
    local ram_kb
    ram_kb=$(awk '/MemTotal/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)
    echo $((ram_kb / 1024 / 1024))
  elif command -v sysctl >/dev/null 2>&1; then
    local ram_bytes
    ram_bytes=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
    echo $((ram_bytes / 1024 / 1024 / 1024))
  else
    echo 0
  fi
}

detect_optimal_jobs() {
  local num_cores
  local total_ram_gb
  local core_jobs
  local ram_jobs
  local jobs

  num_cores=$(detect_num_cores)
  total_ram_gb=$(detect_total_ram_gb)

  # 1. Core budget: leave 1-2 cores for OS/IDE responsiveness
  if [ "$num_cores" -gt 16 ]; then
    core_jobs=$((num_cores - 2))
  elif [ "$num_cores" -gt 4 ]; then
    core_jobs=$((num_cores - 1))
  elif [ "$num_cores" -gt 0 ]; then
    core_jobs=$num_cores
  else
    core_jobs=4
  fi

  # 2. Memory budget: reserve 4 GiB floor for OS/services, allocate ~1.5 GiB per compiler/linker job
  if [ "$total_ram_gb" -gt 4 ]; then
    ram_jobs=$(( (total_ram_gb - 4) * 2 / 3 ))
    [ "$ram_jobs" -lt 1 ] && ram_jobs=1
  elif [ "$total_ram_gb" -gt 0 ]; then
    ram_jobs=1
  else
    ram_jobs=$core_jobs
  fi

  # 3. Take minimum of core and memory budgets
  if [ "$ram_jobs" -lt "$core_jobs" ]; then
    jobs=$ram_jobs
  else
    jobs=$core_jobs
  fi

  # 4. Enforce lower bound of 1 and hard cap of 24
  [ "$jobs" -lt 1 ] && jobs=1
  if [ "$jobs" -gt 24 ]; then
    jobs=24
  fi

  echo "$jobs"
}

# Automatic JOBS detection bounded by CPU cores, physical RAM, and a hard cap of 24
JOBS=$(detect_optimal_jobs)

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    -j|--jobs)
      JOBS=$2
      shift
      ;;
    -j*)
      JOBS="${1#-j}"
      ;;
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
  shift
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
  make -j$JOBS || exit 1
fi

CTEST_FAILED=0
if [ "$DO_TEST" = true ]; then
  if [ "$DO_COVERAGE" = true ]; then
    export LLVM_PROFILE_FILE="coverage-%p.profraw"
  fi
  ctest -j$JOBS || CTEST_FAILED=1
fi

if [ "$DO_XTEST" = true ]; then
  ctest -j$JOBS --output-on-failure -Q --timeout 120 || exit 1
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

