#!/bin/bash
# Progress is reported with [build.sh] messages; run `bash -x ./build.sh ...`
# to trace every command when debugging this script.

export BS_SCRIPT=`realpath $0`
export BS_DIRNAME=`dirname $BS_SCRIPT`

# Work from the repository root regardless of the caller's directory.
cd "$BS_DIRNAME" || exit 1

# Repository root, and the build tree relative to it. BUILD_DIR may be a
# symlink to an out-of-tree build (see "Optional out-of-tree builds" below);
# every path in this script goes through it.
ROOT_DIR="$(pwd)"
BUILD_DIR="build"
ORIG_ARGS="$*"

log() { echo "[build.sh] $*"; }
log_err() { echo "[build.sh] $*" >&2; }

# Default values
BUILD_TYPE="RELEASE"
DO_CLEAN=false
DO_MAKE=false
DO_TEST=false
DO_ITEST=false
ITEST_REGEX=""
ITEST_TARGET=""
DO_XTEST=false
DO_PTEST=false
DO_INSTALL=false
INSTALL_TAG=""
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
    itest)
      # itest <TestRegex> [make_target]: build make_target (default: all),
      # then run the tests matching TestRegex.
      DO_ITEST=true
      ITEST_REGEX=$2
      if [ -z "$ITEST_REGEX" ]; then
        log_err "ERROR: usage: ./build.sh itest <TestRegex> [make_target]"
        exit 1
      fi
      shift
      case "$2" in
        ""|-*|debug|clean|make|test|itest|xtest|ptest|install|install:*|coverage) ;;
        *)
          ITEST_TARGET=$2
          shift
          ;;
      esac
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
    install:*)
      DO_INSTALL=true
      INSTALL_TAG="${1#install:}"
      if [ -z "$INSTALL_TAG" ]; then
        log_err "ERROR: install tag cannot be empty (e.g. ./build.sh install:main)"
        exit 1
      fi
      ;;
    coverage)
      DO_COVERAGE=true
      DO_TEST=true
      BUILD_TYPE="DEBUG"
      ;;
  esac
  shift
done

# Optional out-of-tree builds. If $HOME/scratch/builds exists, the build tree
# lives in $HOME/scratch/builds/lsmio-<name>/build and ./build is a symlink to
# it. <name> is the checked-out branch, detached-<path hash>, or
# nogit-<path hash>, so each branch keeps its own tree. Otherwise ./build is a
# normal in-tree directory.
SCRATCH_ROOT="$HOME/scratch/builds"
SCRATCH_DIR=""
if [ -d "$SCRATCH_ROOT" ]; then
  _path_hash=$(printf '%s' "$(pwd -P)" | shasum | cut -c1-8)
  # Use git only if this directory is itself the repo root; a non-git copy
  # nested inside another repo would otherwise inherit that repo's branch.
  if [ "$(git rev-parse --show-toplevel 2>/dev/null)" != "$(pwd -P)" ]; then
    _name="nogit-$_path_hash"
  elif _branch=$(git symbolic-ref --short -q HEAD); then
    # A branch is checked out in at most one worktree, so this is unique.
    _name="$_branch"
  else
    _name="detached-$_path_hash"
  fi
  _scratch_dir="$SCRATCH_ROOT/lsmio-$(printf '%s' "$_name" | tr -c 'A-Za-z0-9._-' '-')"
  if mkdir -p "$_scratch_dir/build" 2>/dev/null && [ -w "$_scratch_dir" ]; then
    SCRATCH_DIR="$_scratch_dir"
  else
    log_err "WARNING: $SCRATCH_ROOT is not writable; using the in-tree build directory."
  fi
fi

if [ -n "$SCRATCH_DIR" ]; then
  if [ "$DO_CLEAN" = true ]; then
    log "Cleaning the build directory"
    # Empty the out-of-tree build but keep ./build a symlink. A plain
    # `rm -rf build` on a symlink removes only the link.
    find "$SCRATCH_DIR/build" -mindepth 1 -delete || exit 1
    rm -rf "$BUILD_DIR" || exit 1
  fi
  if [ -L "$BUILD_DIR" ]; then
    # Repoint after a branch switch; each branch keeps its own tree.
    if [ "$(readlink "$BUILD_DIR")" != "$SCRATCH_DIR/build" ]; then
      ln -sfn "$SCRATCH_DIR/build" "$BUILD_DIR" || exit 1
    fi
  elif [ -e "$BUILD_DIR" ]; then
    # Replace an in-tree build with the out-of-tree one. A CMake tree records
    # its absolute path and can't be moved, so it is removed and reconfigured.
    # Anything that doesn't look like a CMake tree is left alone.
    if [ -f "$BUILD_DIR/CMakeCache.txt" ] || [ -d "$BUILD_DIR/CMakeFiles" ] \
       || [ -z "$(ls -A "$BUILD_DIR")" ]; then
      log_err "NOTICE: replacing the in-tree $BUILD_DIR/ with a symlink to $SCRATCH_DIR/build; a full rebuild follows."
      rm -rf "$BUILD_DIR" && ln -s "$SCRATCH_DIR/build" "$BUILD_DIR" || exit 1
    else
      log_err "WARNING: $ROOT_DIR/$BUILD_DIR is not a CMake build tree; left in place and used as is."
    fi
  else
    ln -s "$SCRATCH_DIR/build" "$BUILD_DIR" || exit 1
  fi
else
  if [ "$DO_CLEAN" = true ]; then
    log "Cleaning the build directory"
    rm -rf "$BUILD_DIR" \
    && mkdir -p "$BUILD_DIR"
  fi
  if [ -L "$BUILD_DIR" ] && [ ! -e "$BUILD_DIR" ]; then
    log_err "ERROR: $BUILD_DIR is a symlink to $(readlink "$BUILD_DIR"), which does not exist."
    log_err "       Restore it, or run './build.sh clean' to use an in-tree build directory."
    exit 1
  fi
fi

log "lsmio: ${ORIG_ARGS:-(no command)} (-j$JOBS)"
if [ -L "$BUILD_DIR" ]; then
  log "Build directory: $BUILD_DIR/ -> $(readlink "$BUILD_DIR")"
else
  log "Build directory: $ROOT_DIR/$BUILD_DIR (in-tree)"
fi

log "Configuring a $BUILD_TYPE build (cmake, coverage: $DO_COVERAGE)"
cmake -B "$BUILD_DIR" \
  -DCMAKE_BUILD_TYPE=$BUILD_TYPE \
  -DBUILD_SHARED_LIBS=On \
  -DCMAKE_INSTALL_PREFIX:PATH="${PREFIX:-$HOME/src/usr}" \
  -DLSMIO_ENABLE_COVERAGE=$DO_COVERAGE

pushd "$BUILD_DIR" > /dev/null || exit 1

# make is implied if test or install are requested
if [ "$DO_MAKE" = true ] || [ "$DO_TEST" = true ] || [ "$DO_INSTALL" = true ]; then
  log "Building all targets (make -j$JOBS)"
  make -j$JOBS || exit 1
elif [ "$DO_ITEST" = true ]; then
  log "Building ${ITEST_TARGET:-all targets} (make -j$JOBS)"
  make -j$JOBS $ITEST_TARGET || exit 1
fi

# Runs ctest without printing any test output (for agents: long, streamed test
# output is costly for tools that capture it). ctest -Q silences the console and
# -O writes what the console would have shown to FAILURES_LOG: one result line
# per test, the output of failing tests only, and ctest's summary. On failure,
# lists the failed tests and points to that log. Extra arguments go to ctest.
run_ctest_quiet() {
  local failures_log="Testing/Temporary/LastTestFailures.log"
  local failed_list="Testing/Temporary/LastTestsFailed.log"
  local summary total
  mkdir -p Testing/Temporary
  rm -f "$failed_list"
  log "Running tests${*:+ ($*)} quietly; output of failing tests: $ROOT_DIR/$BUILD_DIR/$failures_log"
  if ctest -j"$JOBS" -Q --output-on-failure --timeout 120 --no-tests=error -O "$failures_log" "$@"; then
    summary=$(grep -E 'tests passed, [0-9]+ tests? failed out of [0-9]+' "$failures_log" | tail -n 1)
    log "${summary:-All tests passed.}"
    return 0
  fi
  summary=$(grep -E 'tests passed, [0-9]+ tests? failed out of [0-9]+' "$failures_log" | tail -n 1)
  if [ -s "$failed_list" ]; then
    total=$(wc -l < "$failed_list")
    log_err "Tests FAILED: ${summary:-$total test(s) failed}"
    log_err "Failed tests (full list: $ROOT_DIR/$BUILD_DIR/$failed_list):"
    head -n 50 "$failed_list" | sed 's/^/  /' >&2
    if [ "$total" -gt 50 ]; then
      log_err "  ... first 50 of $total shown"
    fi
  else
    log_err "ctest failed without a list of failed tests; last lines of its log:"
    tail -n 3 "$failures_log" | sed 's/^/  /' >&2
  fi
  log_err "Output of the failed tests: $ROOT_DIR/$BUILD_DIR/$failures_log ($(du -h "$failures_log" | cut -f1))"
  return 1
}

if [ "$DO_ITEST" = true ]; then
  run_ctest_quiet -R "$ITEST_REGEX" || exit 1
fi

CTEST_FAILED=0
if [ "$DO_TEST" = true ]; then
  if [ "$DO_COVERAGE" = true ]; then
    export LLVM_PROFILE_FILE="coverage-%p.profraw"
  fi
  log "Running all tests (ctest -j$JOBS)"
  ctest -j$JOBS || CTEST_FAILED=1
fi

if [ "$DO_XTEST" = true ]; then
  run_ctest_quiet || exit 1
fi

if [ "$DO_PTEST" = true ]; then
  log "Running lsmiotool Python tests"
  pushd "$BS_DIRNAME/tools/lsmiotool" > /dev/null && ./lsmiotool test || exit 1
  popd > /dev/null
fi

if [ "$DO_INSTALL" = true ]; then
  log "Installing to ${PREFIX:-$HOME/src/usr} (make install)"
  make install || exit 1
  if [ -n "$INSTALL_TAG" ]; then
    INSTALL_PREFIX="${PREFIX:-$HOME/src/usr}"
    INSTALL_BIN_DIR="${INSTALL_PREFIX}/bin"
    for bm in bm_native bm_rocksdb bm_leveldb bm_manager bm_adios; do
      if [ -f "${INSTALL_BIN_DIR}/${bm}" ]; then
        cp -f "${INSTALL_BIN_DIR}/${bm}" "${INSTALL_BIN_DIR}/${bm}:${INSTALL_TAG}"
      fi
    done
  fi
fi

if [ "$DO_COVERAGE" = true ]; then
  log "Generating lsmiotool Python coverage report"
  cmake --build . --target lsmiotool_python_coverage_report || exit 1

  log "Generating coverage report"
  
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
      
    log "Coverage report generated at $BUILD_DIR/coverage_report/index.html"
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
    log "Coverage report generated at $BUILD_DIR/coverage_report/index.html"
  fi
fi

if [ "$CTEST_FAILED" -ne 0 ]; then
  exit 1
fi

popd > /dev/null

