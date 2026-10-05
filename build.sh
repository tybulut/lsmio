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
DO_CLEAN_COV=false
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
DO_RESULTS_FAIL=false
DO_COV_SHOW=false
COV_FILE=""
DO_FAST_COV=false
BUILD_ONE_BIN=""
TEST_ONE_BIN=""
TEST_ONE_SRC=""
TEST_ONE_DIR=""

detect_num_cores() {
  # 1. macOS physical cores
  if command -v sysctl >/dev/null 2>&1; then
    local phys_cpu
    phys_cpu=$(sysctl -n hw.physicalcpu 2>/dev/null)
    if [ -n "$phys_cpu" ] && [ "$phys_cpu" -gt 0 ] 2>/dev/null; then
      echo "$phys_cpu"
      return
    fi
  fi

  # 2. Linux physical cores (excluding hyper-threads)
  if command -v lscpu >/dev/null 2>&1; then
    local phys_cores
    phys_cores=$(lscpu -p=Core,Socket 2>/dev/null | grep -v '^#' | sort -u | wc -l)
    if [ -n "$phys_cores" ] && [ "$phys_cores" -gt 0 ] 2>/dev/null; then
      echo "$phys_cores"
      return
    fi
  fi

  # 3. Fallback to logical processors
  if command -v nproc >/dev/null 2>&1; then
    nproc 2>/dev/null || echo 4
  elif command -v getconf >/dev/null 2>&1; then
    getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4
  else
    echo 4
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
    ram_jobs=$(( (total_ram_gb - 4) * 4 / 5 ))
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
    clean-cov)
      DO_CLEAN_COV=true
      ;;
    make)
      DO_MAKE=true
      ;;
    test)
      DO_MAKE=true
      DO_TEST=true
      ;;
    itest)
      # itest <TestRegex> [make_target]: build make_target (default: all),
      # then run the tests matching TestRegex.
      DO_MAKE=true
      DO_ITEST=true
      ITEST_REGEX=$2
      if [ -z "$ITEST_REGEX" ]; then
        log_err "ERROR: usage: ./build.sh itest <TestRegex> [make_target]"
        exit 1
      fi
      shift
      case "$2" in
        ""|-*|debug|clean|clean-cov|make|test|itest|xtest|ptest|install|install:*|coverage|results|results-fail|cov-show|fast-cov|help|--help|-h) ;;
        *)
          ITEST_TARGET=$2
          shift
          ;;
      esac
      ;;
    xtest)
      DO_MAKE=true
      DO_XTEST=true
      if [ -n "$2" ] && [[ "$2" != -* && "$2" != "clean" && "$2" != "clean-cov" && "$2" != "make" && "$2" != "test" && "$2" != "itest" && "$2" != "xtest" && "$2" != "ptest" && "$2" != "install" && "$2" != "install:"* && "$2" != "coverage" && "$2" != "results" && "$2" != "results-fail" && "$2" != "cov-show" && "$2" != "fast-cov" && "$2" != "help" && "$2" != "--help" && "$2" != "-h" ]]; then
        TEST_ONE_BIN=$2
        shift
      fi
      ;;
    ptest)
      DO_PTEST=true
      ;;
    install)
      DO_MAKE=true
      DO_INSTALL=true
      ;;
    install:*)
      DO_MAKE=true
      DO_INSTALL=true
      INSTALL_TAG="${1#install:}"
      if [ -z "$INSTALL_TAG" ]; then
        log_err "ERROR: install tag cannot be empty (e.g. ./build.sh install:main)"
        exit 1
      fi
      ;;
    coverage)
      DO_MAKE=true
      DO_COVERAGE=true
      DO_TEST=true
      BUILD_TYPE="DEBUG"
      ;;
    results)
      DO_COVERAGE=true
      ;;
    results-fail)
      DO_COVERAGE=true
      DO_RESULTS_FAIL=true
      ;;
    cov-show)
      DO_COV_SHOW=true
      DO_COVERAGE=true
      COV_FILE=$2
      if [ -z "$COV_FILE" ]; then
        log_err "ERROR: usage: ./build.sh cov-show <file>"
        exit 1
      fi
      shift
      ;;
    fast-cov)
      DO_MAKE=true
      DO_COVERAGE=true
      DO_FAST_COV=true
      BUILD_TYPE="DEBUG"
      BUILD_ONE_BIN=$2
      TEST_ONE_BIN=$2
      TEST_ONE_SRC=$3
      TEST_ONE_DIR=$4
      if [ -z "$BUILD_ONE_BIN" ] || [ -z "$TEST_ONE_SRC" ]; then
        log_err "ERROR: usage: ./build.sh fast-cov <bin> <src> [dir]"
        exit 1
      fi
      shift 3
      ;;
    help|--help|-h)
      echo "Usage: ./build.sh [options]"
      echo "Options:"
      echo "  make                       Compile the project"
      echo "  clean                      Clean the build directory"
      echo "  clean-cov                  Clean coverage profile files (.profraw, .profdata, .gcda)"
      echo "  debug                      Reconfigure the build tree as DEBUG"
      echo "  test                       Run the test suite"
      echo "  xtest [regex]              Run the CTest suite quietly; failing output goes to a log (Agents)"
      echo "  ptest                      Run lsmiotool Python tests"
      echo "  itest <regex> [target]     Build target, run ctest -R <regex> quietly (failing output goes to a log)"
      echo "  coverage                   Run tests and generate coverage report"
      echo "  results                    Display coverage report using existing profile data"
      echo "  results-fail               Display coverage report, filtering out files with >=95% coverage (BLUE)"
      echo "  cov-show <file>            Display line-by-line coverage for a specific source file"
      echo "  fast-cov <bin> <src> [dir] Run fast targeted coverage for a binary and source file"
      echo "  install [tag]              Install the project (or with tag e.g. install:main)"
      echo "  -j, --jobs <n>             Number of parallel jobs for build/test (default: auto, max 24)"
      echo "  help                       Display this help message"
      exit 0
      ;;
    *)
      log_err "Unknown argument: $1 (see ./build.sh help)"
      exit 1
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
PROF_DIR=""
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
  if mkdir -p "$_scratch_dir/build" "$_scratch_dir/prof" 2>/dev/null && [ -w "$_scratch_dir" ]; then
    SCRATCH_DIR="$_scratch_dir"
    PROF_DIR="$_scratch_dir/prof"
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

# Prints the command for an LLVM coverage tool (llvm-profdata, llvm-cov). The
# .profraw format is version-specific, so the tool must come from the same LLVM
# as the compiler that built the tree. macOS goes through xcrun. Elsewhere the
# tool next to the configured compiler is preferred; clang++ on PATH stands in
# when no build is configured; PATH is the last resort.
resolve_llvm_tool() {
  local tool=$1 cxx dir cache maj min pat
  local -a cmake_files
  if command -v xcrun >/dev/null 2>&1; then
    echo "xcrun $tool"
    return
  fi
  cache="$ROOT_DIR/$BUILD_DIR/CMakeCache.txt"
  maj=$(sed -n 's/^CMAKE_CACHE_MAJOR_VERSION:INTERNAL=//p' "$cache" 2>/dev/null)
  min=$(sed -n 's/^CMAKE_CACHE_MINOR_VERSION:INTERNAL=//p' "$cache" 2>/dev/null)
  pat=$(sed -n 's/^CMAKE_CACHE_PATCH_VERSION:INTERNAL=//p' "$cache" 2>/dev/null)
  cmake_files=("$ROOT_DIR/$BUILD_DIR/CMakeFiles/$maj.$min.$pat/CMakeCXXCompiler.cmake")
  if [ -z "$maj" ] || [ ! -f "${cmake_files[0]}" ]; then
    cmake_files=("$ROOT_DIR/$BUILD_DIR"/CMakeFiles/*/CMakeCXXCompiler.cmake)
  fi
  cxx=$(sed -nE 's/^set\(CMAKE_CXX_COMPILER "(.*)"\)$/\1/p' \
          "${cmake_files[@]}" 2>/dev/null | head -n 1)
  [ -z "$cxx" ] && cxx=$(command -v clang++ 2>/dev/null)
  if [ -n "$cxx" ]; then
    dir=$(dirname "$(readlink -f "$cxx")")
    if [ -x "$dir/$tool" ]; then
      echo "$dir/$tool"
      return
    fi
  fi
  command -v "$tool" 2>/dev/null
}

# Written only after a complete, passing full-suite coverage run. The report
# targets (results, results-fail, cov-show) refuse to read the profile when a
# test binary or a source file is newer than this file, since the profile then
# no longer matches the code.
COVERAGE_STAMP="$ROOT_DIR/$BUILD_DIR/.coverage-stamp"

if [ "$DO_CLEAN_COV" = true ]; then
  log "Cleaning coverage profile files"
  find . \( -name "*.profraw" -o -name "*.gcda" \) -delete
  if [ -e "$BUILD_DIR" ]; then
    find "$BUILD_DIR/" \( -name "*.profraw" -o -name "*.gcda" \) -delete
  fi
  if [ -n "$PROF_DIR" ]; then
    find "$PROF_DIR" \( -name "*.profraw" -o -name "*.gcda" \) -delete
  fi
  rm -f coverage.profdata default.profdata "$BUILD_DIR/coverage.profdata" "$BUILD_DIR/default.profdata" "$COVERAGE_STAMP"
  exit 0
fi

log "lsmio: ${ORIG_ARGS:-(no command)} (-j$JOBS)"
if [ -L "$BUILD_DIR" ]; then
  log "Build directory: $BUILD_DIR/ -> $(readlink "$BUILD_DIR")"
else
  log "Build directory: $ROOT_DIR/$BUILD_DIR (in-tree)"
fi

INSTALL_PREFIX="${PREFIX:-${PROJECT_DIR:-$HOME/src/usr}}"

EXTRA_CMAKE_ARGS=()
if [ "$DO_COVERAGE" = true ]; then
  PY_COV=""
  if command -v python3 >/dev/null 2>&1 && python3 -c "import coverage, matplotlib" >/dev/null 2>&1; then
    PY_COV=$(command -v python3)
  elif [ -f "$ROOT_DIR/venv/bin/python3" ] && "$ROOT_DIR/venv/bin/python3" -c "import coverage, matplotlib" >/dev/null 2>&1; then
    PY_COV="$ROOT_DIR/venv/bin/python3"
  elif command -v python3 >/dev/null 2>&1 && python3 -c "import coverage" >/dev/null 2>&1; then
    PY_COV=$(command -v python3)
  elif [ -f "$ROOT_DIR/venv/bin/python3" ] && "$ROOT_DIR/venv/bin/python3" -c "import coverage" >/dev/null 2>&1; then
    PY_COV="$ROOT_DIR/venv/bin/python3"
  else
    log "Python virtual environment with coverage module not found; setting up venv"
    if python3 -m venv --system-site-packages venv 2>/dev/null; then
      ./venv/bin/pip install coverage matplotlib 2>/dev/null || ./venv/bin/pip install coverage 2>/dev/null || true
      if [ -f "$ROOT_DIR/venv/bin/python3" ]; then
        PY_COV="$ROOT_DIR/venv/bin/python3"
      fi
    fi
  fi
  if [ -n "$PY_COV" ]; then
    EXTRA_CMAKE_ARGS+=("-DPython3_EXECUTABLE=$PY_COV")
  fi
fi

log "Configuring a $BUILD_TYPE build (cmake, coverage: $DO_COVERAGE)"
cmake -B "$BUILD_DIR" \
  -DCMAKE_BUILD_TYPE=$BUILD_TYPE \
  -DBUILD_SHARED_LIBS=On \
  -DCMAKE_INSTALL_PREFIX:PATH="$INSTALL_PREFIX" \
  -DLSMIO_ENABLE_COVERAGE=$DO_COVERAGE \
  "${EXTRA_CMAKE_ARGS[@]}"

pushd "$BUILD_DIR" > /dev/null || exit 1

if [ "$DO_FAST_COV" = true ]; then
  log "Running fast targeted coverage for $TEST_ONE_BIN ($TEST_ONE_SRC)"
  make -j$JOBS ${TEST_ONE_BIN} || exit 1
  rm -f ${TEST_ONE_BIN}*.profraw ${TEST_ONE_BIN}.profdata "$COVERAGE_STAMP"
  find . -name "*$(basename ${TEST_ONE_SRC}).gcda" -delete 2>/dev/null
  LLVM_PROFILE_FILE="${TEST_ONE_BIN}-%p.profraw" ./${TEST_ONE_DIR:-test}/${TEST_ONE_BIN} || exit 1
  LLVM_PROFDATA=$(resolve_llvm_tool llvm-profdata)
  LLVM_COV=$(resolve_llvm_tool llvm-cov)
  if [ -n "$LLVM_PROFDATA" ] && [ -n "$LLVM_COV" ] && compgen -G "${TEST_ONE_BIN}-*.profraw" >/dev/null; then
    $LLVM_PROFDATA merge -sparse ${TEST_ONE_BIN}-*.profraw -o ${TEST_ONE_BIN}.profdata
    $LLVM_COV report -instr-profile=${TEST_ONE_BIN}.profdata -object ${TEST_ONE_DIR:-test}/${TEST_ONE_BIN} | grep "${TEST_ONE_SRC}"
  elif command -v gcov >/dev/null 2>&1; then
    GCDA_FILE=$(find . -name "*$(basename ${TEST_ONE_SRC}).gcda" -size +0c 2>/dev/null | head -n 1)
    [ -z "$GCDA_FILE" ] && GCDA_FILE=$(find . -name "*$(basename ${TEST_ONE_SRC}).gcda" 2>/dev/null | head -n 1)
    TMP_FAST_GCOV=$(mktemp -d)
    if [ -n "$GCDA_FILE" ]; then
      GCDA_PATH=$(readlink -f "$GCDA_FILE")
      (cd "$TMP_FAST_GCOV" && gcov -b -c -o "$GCDA_PATH" "$ROOT_DIR/$TEST_ONE_SRC") | grep -A 3 -B 1 "File '.*$(basename ${TEST_ONE_SRC})'"
    else
      GCNO_FILE=$(find . -name "*$(basename ${TEST_ONE_SRC}).gcno" 2>/dev/null | head -n 1)
      if [ -n "$GCNO_FILE" ]; then
        GCNO_PATH=$(readlink -f "$GCNO_FILE")
        (cd "$TMP_FAST_GCOV" && gcov -b -c "$GCNO_PATH") | grep -A 3 -B 1 "File '.*$(basename ${TEST_ONE_SRC})'"
      fi
    fi
    rm -rf "$TMP_FAST_GCOV"
  fi
  exit 0
fi

# make is implied if test or install are requested
if [ "$DO_MAKE" = true ]; then
  if [ -n "$BUILD_ONE_BIN" ]; then
    log "Building $BUILD_ONE_BIN (make -j$JOBS)"
    make -j$JOBS $BUILD_ONE_BIN || exit 1
  else
    log "Building all targets (make -j$JOBS)"
    make -j$JOBS || exit 1
  fi
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
    find . \( -name "*.profraw" -o -name "*.gcda" \) -delete
    if [ -n "$PROF_DIR" ]; then
      find "$PROF_DIR" \( -name "*.profraw" -o -name "*.gcda" \) -delete
    fi
    rm -f coverage.profdata default.profdata "$COVERAGE_STAMP"
    export LLVM_PROFILE_FILE="${PROF_DIR:-.}/test-%4m.profraw"
  fi

  if [ -n "$TEST_ONE_BIN" ]; then
    run_ctest_quiet -R "$TEST_ONE_BIN" || exit 1
  elif [ "$DO_COVERAGE" = true ]; then
    # Full coverage run: quiet
    run_ctest_quiet || exit 1
    cmake --build . --target lsmiotool_python_coverage_report || exit 1
    touch "$COVERAGE_STAMP"
  else
    log "Running all tests (ctest -j$JOBS)"
    ctest -j$JOBS || CTEST_FAILED=1
  fi
fi

if [ "$DO_XTEST" = true ]; then
  if [ -n "$TEST_ONE_BIN" ]; then
    run_ctest_quiet -R "$TEST_ONE_BIN" || exit 1
  else
    run_ctest_quiet || exit 1
  fi
fi

if [ "$DO_PTEST" = true ]; then
  log "Running lsmiotool Python tests"
  pushd "$BS_DIRNAME/tools/lsmiotool" > /dev/null && ./lsmiotool test || exit 1
  popd > /dev/null
fi

if [ "$DO_INSTALL" = true ]; then
  log "Installing to ${INSTALL_PREFIX} (make install)"
  make install || exit 1
  if [ -n "$INSTALL_TAG" ]; then
    INSTALL_BIN_DIR="${INSTALL_PREFIX}/bin"
    for bm in bm_native bm_rocksdb bm_leveldb bm_manager bm_adios; do
      if [ -f "${INSTALL_BIN_DIR}/${bm}" ]; then
        cp -f "${INSTALL_BIN_DIR}/${bm}" "${INSTALL_BIN_DIR}/${bm}:${INSTALL_TAG}"
      fi
    done
  fi
fi

if [ "$DO_COVERAGE" = true ]; then
  if [ "$DO_TEST" != true ]; then
    # results / results-fail / cov-show read a profile from an earlier run.
    if [ ! -f "$COVERAGE_STAMP" ]; then
      log_err "ERROR: No complete full-suite coverage run is recorded for this build."
      log_err "       Run: ./build.sh coverage"
      exit 1
    fi
    STALE_FILE=$(find "$ROOT_DIR/$BUILD_DIR/test" "$ROOT_DIR/$BUILD_DIR/benchmark" -type f -perm -u+x -newer "$COVERAGE_STAMP" 2>/dev/null | head -n 1)
    if [ -z "$STALE_FILE" ]; then
      STALE_FILE=$(find "$ROOT_DIR/lib" "$ROOT_DIR/include" "$ROOT_DIR/test" "$ROOT_DIR/benchmark" "$ROOT_DIR/tools" "$ROOT_DIR/cmake" \
        -type f \( -name "*.cpp" -o -name "*.hpp" -o -name "*.h" -o -name "*.tcc" -o -name "*.py" -o -name "CMakeLists.txt" \) \
        -newer "$COVERAGE_STAMP" 2>/dev/null | head -n 1)
    fi
    if [ -z "$STALE_FILE" ] && [ -f "$ROOT_DIR/CMakeLists.txt" ] && [ "$ROOT_DIR/CMakeLists.txt" -nt "$COVERAGE_STAMP" ]; then
      STALE_FILE="$ROOT_DIR/CMakeLists.txt"
    fi
    if [ -n "$STALE_FILE" ]; then
      log_err "ERROR: Coverage data is stale: $STALE_FILE changed after the last full coverage run."
      log_err "       Run: ./build.sh coverage"
      exit 1
    fi
  fi

  PROFRAW_FILES=$(find "${PROF_DIR:-.}" -name "test-*.profraw" 2>/dev/null)
  LLVM_PROFDATA=$(resolve_llvm_tool llvm-profdata)
  LLVM_COV=$(resolve_llvm_tool llvm-cov)

  if [ -n "$PROFRAW_FILES" ] && [ -n "$LLVM_PROFDATA" ] && [ -n "$LLVM_COV" ]; then
    log "Generating LLVM coverage report"
    $LLVM_PROFDATA merge -sparse $PROFRAW_FILES -o default.profdata || exit 1

    cd "$ROOT_DIR"
    BINARIES=$(find "$BUILD_DIR/test" -name "test_*" -type f -perm -u+x)
    MAIN_BIN=$(echo $BINARIES | awk '{print $1}')
    OTHER_BINS=$(echo $BINARIES | cut -d' ' -f2-)
    OBJ_ARGS=""
    for bin in $OTHER_BINS; do
      OBJ_ARGS="$OBJ_ARGS -object $bin"
    done

    if [ "$DO_COV_SHOW" = true ]; then
      log "Displaying line-by-line coverage for: $COV_FILE"
      $LLVM_COV show -instr-profile="$BUILD_DIR/default.profdata" \
        -format=text -show-branches=count \
        $MAIN_BIN $OBJ_ARGS \
        $COV_FILE
    else
      $LLVM_COV report -instr-profile="$BUILD_DIR/default.profdata" \
        -ignore-filename-regex="(test/.*|benchmark/.*|.*\.hpp)" \
        $MAIN_BIN $OBJ_ARGS \
        lib | awk -v fail_only="${DO_RESULTS_FAIL:-false}" '
        BEGIN {
          MAGENTA = "\033[35m"; RED = "\033[31m"; YELLOW = "\033[33m";
          GREEN = "\033[32m"; BLUE = "\033[34m"; RESET = "\033[0m";
        }
        {
          if ($0 ~ /^-+$/ || $1 == "Filename") {
            print $0;
          } else {
            pct_line_field = $10;
            pct_branch_field = $13;
            if (pct_line_field ~ /^[0-9.]+%$/) {
              line_val = substr(pct_line_field, 1, length(pct_line_field)-1) + 0;
              if (pct_branch_field ~ /^[0-9.]+%$/) {
                branch_val = substr(pct_branch_field, 1, length(pct_branch_field)-1) + 0;
              } else {
                branch_val = 100.0;
              }
              min_val = (line_val < branch_val) ? line_val : branch_val;
              if (min_val < 50) color = RED;
              else if (min_val < 80) color = YELLOW;
              else if (min_val < 95) color = GREEN;
              else color = BLUE;
              if (fail_only != "true" || color != BLUE) {
                print color $0 RESET;
              }
            } else {
              print $0;
            }
          }
        }'
    fi
    cd "$BUILD_DIR"
  elif command -v gcov >/dev/null 2>&1; then
    cd "$ROOT_DIR"
    if [ "$DO_COV_SHOW" = true ]; then
      log "Displaying line-by-line coverage for: $COV_FILE"
      GCDA_FILE=$(find "$BUILD_DIR/lib" -name "*$(basename "$COV_FILE").gcda" 2>/dev/null | while read -r g; do
        if [[ "$g" == *"$(basename "$(dirname "$COV_FILE")")"*"$(basename "$COV_FILE")"* ]] || [[ "$g" == *"$COV_FILE"* ]]; then
          echo "$g"
          break
        fi
      done)
      [ -z "$GCDA_FILE" ] && GCDA_FILE=$(find "$BUILD_DIR/lib" -name "*$(basename "$COV_FILE").gcda" 2>/dev/null | head -n 1)
      if [ -z "$GCDA_FILE" ]; then
        log_err "ERROR: No .gcda coverage data found for $COV_FILE."
        exit 1
      fi
      TMP_GCOV_DIR=$(mktemp -d)
      (
        cd "$TMP_GCOV_DIR" && gcov -b -c -o "$ROOT_DIR/$GCDA_FILE" "$ROOT_DIR/$COV_FILE" >/dev/null 2>&1
      )
      GCOV_OUT="$TMP_GCOV_DIR/$(basename $COV_FILE).gcov"
      if [ -f "$GCOV_OUT" ]; then
        python3 -c '
import sys, re
gcov_path = sys.argv[1]
with open(gcov_path) as f:
    for line in f:
        if line.startswith("branch"):
            m = re.search(r"taken\s+(\d+)", line)
            if m:
                taken = int(m.group(1))
                print(f"  |  Branch: [True: {taken}]")
            elif "never executed" in line:
                print("  |  Branch: [True: 0]")
        elif ":" in line:
            parts = line.split(":", 2)
            if len(parts) >= 3:
                hits, lineno, code = parts[0].strip(), parts[1].strip(), parts[2]
                if lineno.isdigit():
                    l_num = int(lineno)
                    if hits == "-":
                        print(f"{l_num:5d}|       |{code}", end="")
                    elif hits == "#####":
                        print(f"{l_num:5d}|      0|{code}", end="")
                    elif hits.isdigit():
                        print(f"{l_num:5d}|{int(hits):7d}|{code}", end="")
' "$GCOV_OUT"
        rm -rf "$TMP_GCOV_DIR"
      else
        log_err "ERROR: Failed to generate gcov report for $COV_FILE"
        rm -rf "$TMP_GCOV_DIR"
        exit 1
      fi
    else
      log "Generating gcov coverage report"
      python3 -c '
import subprocess, glob, os, re, sys, tempfile

fail_only = (sys.argv[1] == "true") if len(sys.argv) > 1 else False
gcda_files = glob.glob("build/lib/**/*.gcda", recursive=True)
files_data = {}

with tempfile.TemporaryDirectory() as tmp_dir:
    for gcda in gcda_files:
        res = subprocess.run(["gcov", "-b", "-c", "-o", os.path.abspath(gcda), os.path.abspath(gcda)], cwd=tmp_dir, capture_output=True, text=True)
        current_file = None
        for line in res.stdout.splitlines():
            m_file = re.search(r"^File .*(lib/.*)\x27", line)
            if m_file:
                current_file = m_file.group(1)
                if current_file not in files_data:
                    files_data[current_file] = {"lines_exec": 0, "lines_total": 0, "branches_exec": 0, "branches_total": 0}
            elif current_file:
                m_lines = re.search(r"Lines executed:([0-9.]+)% of (\d+)", line)
                if m_lines:
                    pct = float(m_lines.group(1))
                    tot = int(m_lines.group(2))
                    exc = int(round(pct * tot / 100.0))
                    files_data[current_file]["lines_exec"] = max(files_data[current_file]["lines_exec"], exc)
                    files_data[current_file]["lines_total"] = max(files_data[current_file]["lines_total"], tot)
                m_branches = re.search(r"Taken at least once:([0-9.]+)% of (\d+)", line)
                if m_branches:
                    pct = float(m_branches.group(1))
                    tot = int(m_branches.group(2))
                    exc = int(round(pct * tot / 100.0))
                    files_data[current_file]["branches_exec"] = max(files_data[current_file]["branches_exec"], exc)
                    files_data[current_file]["branches_total"] = max(files_data[current_file]["branches_total"], tot)

RED = "\033[31m"; YELLOW = "\033[33m"; GREEN = "\033[32m"; BLUE = "\033[34m"; RESET = "\033[0m"
header = f"%-50s %10s %10s %10s %10s %10s %10s" % ("Filename", "Lines", "Missed", "Cover", "Branches", "Missed", "Cover")
sep = "-" * len(header)
print(header)
print(sep)

for f in sorted(files_data.keys()):
    d = files_data[f]
    ltot = d["lines_total"]
    lexec = d["lines_exec"]
    lmiss = ltot - lexec
    lpct = (lexec * 100.0 / ltot) if ltot > 0 else 100.0
    btot = d["branches_total"]
    bexec = d["branches_exec"]
    bmiss = btot - bexec
    bpct = (bexec * 100.0 / btot) if btot > 0 else 100.0
    min_val = min(lpct, bpct)
    if min_val < 50:
        color = RED
    elif min_val < 80:
        color = YELLOW
    elif min_val < 95:
        color = GREEN
    else:
        color = BLUE
    if not fail_only or color != BLUE:
        row = f"%-50s %10d %10d %9.2f%% %10d %10d %9.2f%%" % (f, ltot, lmiss, lpct, btot, bmiss, bpct)
        print(f"{color}{row}{RESET}")
' "${DO_RESULTS_FAIL:-false}"
    fi
    cd "$BUILD_DIR"
  else
    log_err "ERROR: Neither LLVM coverage tools nor gcov found."
    exit 1
  fi
fi

if [ "$CTEST_FAILED" -ne 0 ]; then
  exit 1
fi

popd > /dev/null

