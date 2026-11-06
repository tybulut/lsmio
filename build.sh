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
PY_ACTIONS=()
PY_FILTER=""
PY_SRC=""
PY_FAST_MODULE=""
DO_INSTALL=false
INSTALL_TAG=""
DO_COVERAGE=false
DO_RESULTS_FAIL=false
DO_COV_SHOW=false
COV_FILE=""
DO_FAST_COV=false
# Coverage target (Code Coverage Invariant): a file passes when both its line and
# its branch coverage reach this percentage. results-fail hides passing files.
COV_THRESHOLD=95
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
        ""|-*|debug|clean|clean-cov|make|test|itest|xtest|py-*|install|install:*|coverage|results|results-fail|cov-show|fast-cov|help|--help|-h) ;;
        *)
          ITEST_TARGET=$2
          shift
          ;;
      esac
      ;;
    xtest)
      DO_MAKE=true
      DO_XTEST=true
      if [ -n "$2" ] && [[ "$2" != -* && "$2" != "clean" && "$2" != "clean-cov" && "$2" != "make" && "$2" != "test" && "$2" != "itest" && "$2" != "xtest" && "$2" != py-* && "$2" != "install" && "$2" != "install:"* && "$2" != "coverage" && "$2" != "results" && "$2" != "results-fail" && "$2" != "cov-show" && "$2" != "fast-cov" && "$2" != "help" && "$2" != "--help" && "$2" != "-h" ]]; then
        TEST_ONE_BIN=$2
        shift
      fi
      ;;
    py-xtest|py-coverage|py-results|py-results-fail)
      PY_ACTIONS+=("$1")
      ;;
    py-itest)
      # py-itest <filter>: a dotted test name as `lsmiotool test` takes it.
      PY_FILTER=$2
      case "$PY_FILTER" in
        ""|-*|debug|clean|clean-cov|make|test|itest|xtest|py-*|install|install:*|coverage|results|results-fail|cov-show|fast-cov|help|--help|-h)
          log_err "ERROR: usage: ./build.sh py-itest <test name> (a dotted name as 'lsmiotool test' takes it, e.g. lsmiotool.test.main.VersionTest)"
          exit 2
          ;;
      esac
      PY_ACTIONS+=("$1")
      shift
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
      if [[ "$2" == *.py ]]; then
        # A .py source selects the Python form, chosen before the C++ state is set
        # (as loreos does for .rs): it reads the last py-coverage run.
        PY_SRC=${2#./}
        PY_ACTIONS+=("cov-show-py")
      else
        DO_COV_SHOW=true
        DO_COVERAGE=true
        COV_FILE=$2
        if [ -z "$COV_FILE" ]; then
          log_err "ERROR: usage: ./build.sh cov-show <file>"
          exit 1
        fi
      fi
      shift
      ;;
    fast-cov)
      if [[ "$3" == *.py ]]; then
        # Python form: ./build.sh fast-cov <test_module> <src.py>. No C++ state is
        # touched (no DO_MAKE, DO_COVERAGE or BUILD_TYPE).
        if [ -z "$2" ]; then
          log_err "ERROR: usage: ./build.sh fast-cov <test_module> <tools/lsmiotool/...py>"
          exit 1
        fi
        PY_FAST_MODULE=$2
        PY_SRC=${3#./}
        PY_ACTIONS+=("fast-cov-py")
        shift 2
      else
        DO_MAKE=true
        DO_COVERAGE=true
        DO_FAST_COV=true
        BUILD_TYPE="DEBUG"
        BUILD_ONE_BIN=$2
        TEST_ONE_BIN=$2
        TEST_ONE_SRC=$3
        TEST_ONE_DIR=$4
        if [ -z "$BUILD_ONE_BIN" ] || [ -z "$TEST_ONE_SRC" ]; then
          log_err "ERROR: usage: ./build.sh fast-cov <bin> <src> [dir]  or  fast-cov <test_module> <src.py>"
          exit 1
        fi
        shift 3
      fi
      ;;
    help|--help|-h)
      echo "Usage: ./build.sh [options]"
      echo "Options:"
      echo "  make                       Compile the project"
      echo "  clean                      Clean the build directory"
      echo "  clean-cov                  Clean coverage data: C++ (.profraw, .profdata, stamp) and Python (data, JSON, stamp)"
      echo "  debug                      Reconfigure the build tree as DEBUG"
      echo "  test                       Run the test suite"
      echo "  xtest [regex]              Run the CTest suite quietly; failing output goes to a log (Agents)"
      echo "  itest <regex> [target]     Build target, run ctest -R <regex> quietly (failing output goes to a log)"
      echo "  coverage                   Run the C++ tests and generate the C++ coverage report"
      echo "  results                    Display the C++ coverage report using existing profile data"
      echo "  results-fail               Display the C++ coverage report, filtering out files with >=${COV_THRESHOLD}% line and branch coverage (BLUE)"
      echo "  py-xtest                   Run the lsmiotool Python tests quietly; failing output goes to a log (no C++ build)"
      echo "  py-itest <test name>       Like py-xtest for one dotted test name (module, class or method)"
      echo "  py-coverage                Run the lsmiotool Python tests under coverage.py (branch mode) and print the Python report"
      echo "  py-results                 Display the Python coverage report of the last py-coverage run"
      echo "  py-results-fail            Like py-results, filtering out files with >=${COV_THRESHOLD}% line and branch coverage (BLUE)"
      echo "  cov-show <file>            Line-by-line coverage of a lib/...cpp file (last coverage run) or of a"
      echo "                             tools/lsmiotool/...py file (last py-coverage run)"
      echo "  fast-cov <bin> <src> [dir] C++: run one test binary and report one source file (invalidates the last"
      echo "                             coverage run)"
      echo "  fast-cov <test_module> <src.py>"
      echo "                             Python: run one test module under coverage.py and report one source file"
      echo "                             (leaves the py-coverage data alone)"
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

# Optional out-of-tree builds. If $HOME/builds exists, the build tree
# lives in $HOME/builds/lsmio-<name>/build and ./build is a symlink to
# it. <name> is the checked-out branch, detached-<path hash>, or
# nogit-<path hash>, so each branch keeps its own tree. Otherwise ./build is a
# normal in-tree directory.
SCRATCH_ROOT="$HOME/builds"
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

# llvm-cov prints "warning: N functions have mismatched data" when it drops the
# profile records of functions whose objects disagree. This is the one place that
# names its text; adjust it here if a later LLVM rewords the warning.
LLVM_MISMATCH_TEXT="functions have mismatched data"

# Shows llvm-cov's captured stderr ($1) and fails on a mismatched-data warning:
# such a run gives no C++ verdict for any file. Removes the file.
llvm_check_warnings() {
  local status=0
  cat "$1" >&2
  if grep -q "$LLVM_MISMATCH_TEXT" "$1"; then
    log_err "ERROR: llvm-cov reports mismatched function data: those functions' records were not loaded, so no file's figures can be trusted. This run gives no C++ verdict."
    status=1
  fi
  rm -f "$1"
  return $status
}

# Prints the command for an LLVM coverage tool (llvm-profdata, llvm-cov). The
# .profraw format is version-specific, so the tool must come from the same LLVM
# as the compiler that built the tree. macOS goes through xcrun. Elsewhere the
# tool next to the configured compiler is preferred; clang++ on PATH stands in
# when no build is configured; PATH is the last resort.
# The printed command runs with DEBUGINFOD_URLS unset: with it set, every llvm-cov
# call looks up debug info over the network and takes tens of seconds.
resolve_llvm_tool() {
  local tool
  tool=$(resolve_llvm_tool_path "$1")
  [ -n "$tool" ] && echo "env -u DEBUGINFOD_URLS $tool"
  return 0
}

resolve_llvm_tool_path() {
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

# Prints CMAKE_CXX_COMPILER_ID (e.g. Clang, AppleClang, GNU) of the configured
# build tree, read from the CMake file the configure wrote, never judged by the
# compiler's path; prints nothing when no tree is configured.
configured_cxx_id() {
  local cache="$ROOT_DIR/$BUILD_DIR/CMakeCache.txt" maj min pat
  local -a cmake_files
  maj=$(sed -n 's/^CMAKE_CACHE_MAJOR_VERSION:INTERNAL=//p' "$cache" 2>/dev/null)
  min=$(sed -n 's/^CMAKE_CACHE_MINOR_VERSION:INTERNAL=//p' "$cache" 2>/dev/null)
  pat=$(sed -n 's/^CMAKE_CACHE_PATCH_VERSION:INTERNAL=//p' "$cache" 2>/dev/null)
  cmake_files=("$ROOT_DIR/$BUILD_DIR/CMakeFiles/$maj.$min.$pat/CMakeCXXCompiler.cmake")
  if [ -z "$maj" ] || [ ! -f "${cmake_files[0]}" ]; then
    cmake_files=("$ROOT_DIR/$BUILD_DIR"/CMakeFiles/*/CMakeCXXCompiler.cmake)
  fi
  sed -nE 's/^set\(CMAKE_CXX_COMPILER_ID "(.*)"\)$/\1/p' "${cmake_files[@]}" 2>/dev/null | head -n 1
}

# Written only after a complete, passing full-suite coverage run. The report
# targets (results, results-fail, cov-show) refuse to read the profile when a
# test binary or a source file is newer than this file, since the profile then
# no longer matches the code.
COVERAGE_STAMP="$ROOT_DIR/$BUILD_DIR/.coverage-stamp"

if [ "$DO_CLEAN_COV" = true ]; then
  log "Cleaning coverage profile files"
  find . -name "*.profraw" -delete
  if [ -e "$BUILD_DIR" ]; then
    find "$BUILD_DIR/" -name "*.profraw" -delete
  fi
  if [ -n "$PROF_DIR" ]; then
    find "$PROF_DIR" -name "*.profraw" -delete
  fi
  rm -f coverage.profdata default.profdata "$BUILD_DIR/coverage.profdata" "$BUILD_DIR/default.profdata" "$COVERAGE_STAMP"
  # Python full-run data, marker, JSON, stamp and Python fast-cov data.
  rm -f "$BUILD_DIR/.coverage.lsmiotool" "$BUILD_DIR/.coverage.lsmiotool.sha256" \
        "$BUILD_DIR/lsmiotool-python-coverage.json" "$BUILD_DIR/.py-coverage-stamp" \
        "$BUILD_DIR"/.coverage.lsmiotool.fast*
  exit 0
fi

# C++ coverage is llvm-cov only, so a coverage run or a C++ fast-cov needs a Clang
# tree. This reads the cache after the clean block above: with no configured tree
# (e.g. after `clean`) the run proceeds and CMake picks the compiler.
if { [ "$DO_COVERAGE" = true ] && [ "$DO_TEST" = true ]; } || [ "$DO_FAST_COV" = true ]; then
  CONFIGURED_ID=$(configured_cxx_id)
  case "$CONFIGURED_ID" in
    ""|*Clang*) ;;
    *)
      log_err "ERROR: C++ coverage needs a Clang build, but this tree's C++ compiler is $CONFIGURED_ID."
      log_err "       Run: ./build.sh clean coverage   (with CC and CXX unset)"
      exit 1
      ;;
  esac
fi

log "lsmio: ${ORIG_ARGS:-(no command)} (-j$JOBS)"
if [ -L "$BUILD_DIR" ]; then
  log "Build directory: $BUILD_DIR/ -> $(readlink "$BUILD_DIR")"
else
  log "Build directory: $ROOT_DIR/$BUILD_DIR (in-tree)"
fi

INSTALL_PREFIX="${PREFIX:-${PROJECT_DIR:-$HOME/src/usr}}"

# Sets PY_COV to a Python that can import coverage (the one the coverage-enabled
# configure hands to CMake), creating lsmio/venv when none is found.
select_coverage_python() {
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
}

configure_tree() {
  log "Configuring a $BUILD_TYPE build (cmake, coverage: $DO_COVERAGE)"
  # Every library goes to $INSTALL_PREFIX/lib, where lsmio_adios is installed and the
  # install RPATH points (GNUInstallDirs would pick lib64 on 64-bit Red Hat systems).
  cmake -B "$BUILD_DIR" \
    -DCMAKE_BUILD_TYPE=$BUILD_TYPE \
    -DBUILD_SHARED_LIBS=On \
    -DCMAKE_INSTALL_PREFIX:PATH="$INSTALL_PREFIX" \
    -DCMAKE_INSTALL_LIBDIR:PATH=lib \
    -DLSMIO_ENABLE_COVERAGE=$DO_COVERAGE \
    "${EXTRA_CMAKE_ARGS[@]}" || { log_err "ERROR: the CMake configure failed"; return 1; }
}

# ---------------------------------------------------------------------------
# Python (lsmiotool) commands: py-xtest, py-itest, py-coverage, py-results,
# py-results-fail. They build no C++ and write no C++ state (profiles,
# .coverage-stamp). Python has its own data, JSON and stamp.
# ---------------------------------------------------------------------------
PY_BUILD="$ROOT_DIR/$BUILD_DIR"
PY_DATA="$PY_BUILD/.coverage.lsmiotool"
PY_MARKER="$PY_BUILD/.coverage.lsmiotool.sha256"
PY_JSON="$PY_BUILD/lsmiotool-python-coverage.json"
PY_STAMP="$PY_BUILD/.py-coverage-stamp"

# Python source shared by the Python report and Python cov-show: resolves a key of
# the coverage.py JSON to a path relative to the lsmio root. A key is absolute, or
# relative to the lsmio root or to build/test (the suite's working directory).
read -r -d '' PY_KEYS_SRC <<'PYEOF'
import os


def resolve_key(path, root, build):
    if not os.path.isabs(path):
        in_root = os.path.join(root, path)
        path = in_root if os.path.exists(in_root) else os.path.join(build, "test", path)
    return os.path.relpath(os.path.realpath(path), os.path.realpath(root))
PYEOF

# Sets PY_EXE to the Python the build tree's CMake cache records (the running
# Python must equal it, BaselineGateTest). $1=true also requires it to import
# coverage. A tree that is not configured is configured as `./build.sh make`
# would; a configured tree only gets its Python (and the generated baseline
# file) refreshed, so no other cache value changes.
py_prepare() {
  local cache="$PY_BUILD/CMakeCache.txt" baseline="$PY_BUILD/test/CTestTestfile.baseline.cmake"
  local reason=""
  PY_EXE=$(sed -n 's/^_Python3_EXECUTABLE:INTERNAL=//p' "$cache" 2>/dev/null)
  if [ ! -f "$cache" ]; then
    reason="no configured build tree"
  elif [ -z "$PY_EXE" ] || [ ! -x "$PY_EXE" ] || [ ! -f "$baseline" ]; then
    reason="the cached Python or the baseline registration is missing"
  elif [ "$1" = true ] && ! "$PY_EXE" -c "import coverage" >/dev/null 2>&1; then
    reason="the cached Python cannot import coverage"
  fi
  if [ -n "$reason" ]; then
    log "Python commands: $reason; configuring"
    select_coverage_python
    EXTRA_CMAKE_ARGS=()
    [ -n "$PY_COV" ] && EXTRA_CMAKE_ARGS+=("-DPython3_EXECUTABLE=$PY_COV")
    if [ ! -f "$cache" ]; then
      configure_tree || return 1
    else
      cmake -S "$ROOT_DIR" -B "$PY_BUILD" "${EXTRA_CMAKE_ARGS[@]}" \
        || { log_err "ERROR: the CMake configure failed"; return 1; }
    fi
    PY_EXE=$(sed -n 's/^_Python3_EXECUTABLE:INTERNAL=//p' "$cache" 2>/dev/null)
    if [ -z "$PY_EXE" ] || { [ "$1" = true ] && ! "$PY_EXE" -c "import coverage" >/dev/null 2>&1; }; then
      log_err "ERROR: no usable Python${1:+ with coverage} recorded in $cache"
      return 1
    fi
  fi
  return 0
}

# Runs a command from build/test with exactly the ENVIRONMENT of the ctest test
# lsmiotool_python_suite. $1=true adds the coverage-mode variable.
py_env_run() {
  local cov=$1
  shift
  local -a extra=()
  [ "$cov" = true ] && extra=(LSMIO_ENABLE_COVERAGE=ON)
  (
    cd "$PY_BUILD/test" || exit 1
    env "PYTHONPATH=$ROOT_DIR/tools:$PYTHONPATH" LSMIO_ENV=DEV MPLBACKEND=Agg \
      "MPLCONFIGDIR=$PY_BUILD/matplotlib" \
      "LSMIO_CTEST_REGISTRATION=$PY_BUILD/test/CTestTestfile.baseline.cmake" \
      "LSMIO_CTEST_PYTHON=$PY_EXE" \
      "LSMIO_CTEST_ENTRY=$ROOT_DIR/tools/lsmiotool/lsmiotool" \
      "${extra[@]}" "$@"
  )
}

# py-xtest / py-itest: $1 is an optional dotted test name.
py_test_quiet() {
  local test_log="$PY_BUILD/py-test.log" summary
  py_prepare false || return 1
  log "Running lsmiotool Python tests${1:+ ($1)} quietly; full output: $test_log"
  if py_env_run false "$PY_EXE" "$ROOT_DIR/tools/lsmiotool/lsmiotool" test ${1:+"$1"} > "$test_log" 2>&1; then
    summary=$(grep -E '^Ran [0-9]+ tests? in' "$test_log" | tail -n 1)
    log "Python tests passed: ${summary:-no summary line}"
    return 0
  fi
  summary=$(grep -E '^Ran [0-9]+ tests? in' "$test_log" | tail -n 1)
  log_err "Python tests FAILED: ${summary:-the suite did not finish}"
  grep -E '^(FAIL|ERROR):' "$test_log" | head -n 50 | sed 's/^/  /' >&2
  log_err "Output of the failed tests: $test_log"
  return 1
}

# Refuses to read Python coverage that is missing or older than its inputs.
py_check_fresh() {
  local stale
  if [ ! -f "$PY_STAMP" ]; then
    log_err "ERROR: No complete Python coverage run is recorded for this build."
    log_err "       Run: ./build.sh py-coverage"
    return 1
  fi
  stale=$(find "$ROOT_DIR/tools/lsmiotool" -type f \( -name '*.py' -o -name lsmiotool -o -name lsmiotool-worker \) \
            -not -path '*/__pycache__/*' -newer "$PY_STAMP" 2>/dev/null | head -n 1)
  if [ -z "$stale" ]; then
    for f in "$PY_DATA" "$PY_MARKER" "$PY_JSON"; do
      if [ -e "$f" ] && [ "$f" -nt "$PY_STAMP" ]; then stale=$f; break; fi
    done
  fi
  if [ -n "$stale" ]; then
    log_err "ERROR: Python coverage data is stale: $stale changed after the last py-coverage run."
    log_err "       Run: ./build.sh py-coverage"
    return 1
  fi
  return 0
}

# Prints the Python table from the last run's coverage.py JSON: in-scope files
# only (tools/lsmiotool/**/*.py minus test/ and ctest/).
py_table() {
  python3 -c "$PY_KEYS_SRC"'
import json, os, sys

root, build, json_path, threshold, fail_only, only = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4]), sys.argv[5] == "true", sys.argv[6]
try:
    with open(json_path) as fh:
        files = json.load(fh)["files"]
except (OSError, ValueError, KeyError, TypeError) as err:
    print(f"[build.sh] ERROR: cannot read {json_path} ({err}). Run: ./build.sh py-coverage", file=sys.stderr)
    sys.exit(1)

rows = []
for path, data in files.items():
    rel = resolve_key(path, root, build)
    if not (rel.startswith("tools/lsmiotool/") and rel.endswith(".py")):
        continue
    if rel.startswith(("tools/lsmiotool/test/", "tools/lsmiotool/ctest/", "tools/lsmiotool/venv/")) or "/__pycache__/" in rel:
        continue
    s = data["summary"]
    rows.append((rel, s["num_statements"], s["covered_lines"], s.get("num_branches", 0), s.get("covered_branches", 0)))

if only:
    rows = [r for r in rows if r[0] == only]
    if not rows:
        print(f"[build.sh] ERROR: {only} was not measured (in scope: tools/lsmiotool/**/*.py without test/ and ctest/).", file=sys.stderr)
        sys.exit(3)

RED = "\033[31m"; YELLOW = "\033[33m"; BLUE = "\033[34m"; RESET = "\033[0m"
header = "%-50s %10s %10s %10s %10s %10s %10s" % ("Filename", "Stmts", "Missed", "Cover", "Branches", "Missed", "Cover")
print(header)
print("-" * len(header))
for rel, nstmt, cstmt, nbr, cbr in sorted(rows):
    lpct = (cstmt * 100.0 / nstmt) if nstmt > 0 else 100.0
    bpct = (cbr * 100.0 / nbr) if nbr > 0 else 100.0
    min_val = min(lpct, bpct)
    color = RED if min_val < 50 else (YELLOW if min_val < threshold else BLUE)
    if fail_only and color == BLUE:
        continue
    row = "%-50s %10d %10d %9.2f%% %10d %10d %9.2f%%" % (rel, nstmt, nstmt - cstmt, lpct, nbr, nbr - cbr, bpct)
    print(f"{color}{row}{RESET}")
' "$ROOT_DIR" "$PY_BUILD" "${2:-$PY_JSON}" "$COV_THRESHOLD" "$1" "${3:-}"
}

# $1: a tools/lsmiotool/...py path relative to the lsmio root. Fails unless it is a file.
py_check_source() {
  case "$1" in
    tools/lsmiotool/*.py) ;;
    *)
      log_err "ERROR: $1 is not a tools/lsmiotool/...py source file"
      return 1
      ;;
  esac
  if [ ! -f "$ROOT_DIR/$1" ]; then
    log_err "ERROR: source file does not exist: $1"
    return 1
  fi
}

# fast-cov <test_module> <src.py>: one test module under coverage.py (branch mode,
# the full run's --source and --omit), into a data file of its own. A lower bound
# only. Never touches the py-coverage data, JSON, marker or stamp, nor the C++ state.
py_fast_cov() {
  local fast_data="$PY_BUILD/.coverage.lsmiotool.fast"
  local fast_json="$PY_BUILD/.coverage.lsmiotool.fast.json"
  local fast_log="$PY_BUILD/py-fast-cov.log"
  py_check_source "$PY_SRC" || return 1
  py_prepare true || return 1
  rm -f "$fast_data" "$fast_json"
  log "Running $PY_FAST_MODULE under coverage (branch mode); output: $fast_log"
  if ! py_env_run true "$PY_EXE" -m coverage run "--data-file=$fast_data" --branch \
         "--source=$ROOT_DIR/tools/lsmiotool" '--omit=*/test/*,*/ctest/*,*/__pycache__/*' \
         "$ROOT_DIR/tools/lsmiotool/lsmiotool" test "$PY_FAST_MODULE" > "$fast_log" 2>&1; then
    log_err "ERROR: the tests failed under coverage; last lines of $fast_log:"
    tail -n 15 "$fast_log" | sed 's/^/  /' >&2
    return 1
  fi
  if ! py_env_run true "$PY_EXE" -m coverage json "--data-file=$fast_data" -o "$fast_json" >> "$fast_log" 2>&1; then
    log_err "ERROR: no coverage data was produced; see $fast_log"
    return 1
  fi
  py_table false "$fast_json" "$PY_SRC"
}

# cov-show <src.py>: the file annotated from the last py-coverage run, in the C++
# cov-show line format (<line>|<hits>|<code>): hits 0 for a missed statement, 1 for
# an executed one (coverage.py records no counts), blank for a non-executable line.
# Each line that starts at least one missed branch is followed by one annotation.
py_cov_show() {
  py_check_source "$PY_SRC" || return 1
  py_check_fresh || return 1
  python3 -c "$PY_KEYS_SRC"'
import json, os, sys

root, json_path, src, build = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
try:
    with open(json_path) as fh:
        files = json.load(fh)["files"]
except (OSError, ValueError, KeyError, TypeError) as err:
    print(f"[build.sh] ERROR: cannot read {json_path} ({err}). Run: ./build.sh py-coverage", file=sys.stderr)
    sys.exit(1)

real_root = os.path.realpath(root)
entry = None
for path, data in files.items():
    if resolve_key(path, root, build) == src:
        entry = data
        break
if entry is None:
    print(f"[build.sh] ERROR: No Python coverage data for {src} (in scope: tools/lsmiotool/**/*.py without test/ and ctest/).", file=sys.stderr)
    sys.exit(1)

missing = set(entry.get("missing_lines", []))
executable = set(entry.get("executed_lines", [])) | missing
missed_branches = {}
for frm, to in entry.get("missing_branches", []):
    missed_branches.setdefault(frm, []).append(to)
with open(os.path.join(real_root, src), errors="replace") as fh:
    code_lines = fh.read().splitlines()
for i, code in enumerate(code_lines, 1):
    if i in missing:
        print(f"{i:5d}|{0:7d}|{code}")
    elif i in executable:
        print(f"{i:5d}|{1:7d}|{code}")
    else:
        print(f"{i:5d}|       |{code}")
    if i in missed_branches:
        dests = ", ".join("exit" if t < 0 else str(t) for t in sorted(missed_branches[i]))
        print(f"  |  Branch: [True: 0, False: 0] missed: to {dests}")
' "$ROOT_DIR" "$PY_JSON" "$PY_SRC" "$PY_BUILD"
}

py_coverage() {
  local py_log="$PY_BUILD/py-coverage.log"
  py_prepare true || return 1
  rm -f "$PY_STAMP"
  log "Running lsmiotool Python tests under coverage (branch mode); output: $py_log"
  py_env_run true cmake -Dmode=run "-Dpython=$PY_EXE" "-Ddata=$PY_DATA" "-Djson=$PY_JSON" "-Dmarker=$PY_MARKER" \
      "-Dsource=$ROOT_DIR/tools/lsmiotool" "-Dentry=$ROOT_DIR/tools/lsmiotool/lsmiotool" \
      -P "$ROOT_DIR/cmake/LsmiotoolPythonCoverage.cmake" > "$py_log" 2>&1 \
  && py_env_run true cmake -Dmode=report "-Dpython=$PY_EXE" "-Ddata=$PY_DATA" "-Djson=$PY_JSON" "-Dmarker=$PY_MARKER" \
      -P "$ROOT_DIR/cmake/LsmiotoolPythonCoverage.cmake" >> "$py_log" 2>&1
  if [ $? -ne 0 ]; then
    log_err "ERROR: the Python coverage run failed; last lines of $py_log:"
    tail -n 15 "$py_log" | sed 's/^/  /' >&2
    return 1
  fi
  log "Python coverage (lsmiotool, coverage.py branch mode)"
  py_table false || return 1
  touch "$PY_STAMP"
}

py_run_actions() {
  local action
  for action in "${PY_ACTIONS[@]}"; do
    case "$action" in
      py-xtest)         py_test_quiet "" || return 1 ;;
      py-itest)         py_test_quiet "$PY_FILTER" || return 1 ;;
      py-coverage)      py_coverage || return 1 ;;
      fast-cov-py)      py_fast_cov || return 1 ;;
      cov-show-py)      py_cov_show || return 1 ;;
      py-results)       py_check_fresh && { log "Python coverage (lsmiotool, coverage.py branch mode)"; py_table false; } || return 1 ;;
      py-results-fail)  py_check_fresh && { log "Python coverage (lsmiotool, coverage.py branch mode)"; py_table true; } || return 1 ;;
    esac
  done
}

# An invocation with only py- commands does nothing else.
if [ ${#PY_ACTIONS[@]} -gt 0 ] && [ "$DO_CLEAN" != true ] && [ "$DO_MAKE" != true ] && [ "$DO_TEST" != true ] \
   && [ "$DO_ITEST" != true ] && [ "$DO_XTEST" != true ] && [ "$DO_INSTALL" != true ] && [ "$DO_COVERAGE" != true ]; then
  py_run_actions || exit 1
  exit 0
fi

EXTRA_CMAKE_ARGS=()
if [ "$DO_COVERAGE" = true ]; then
  select_coverage_python
  if [ -n "$PY_COV" ]; then
    EXTRA_CMAKE_ARGS+=("-DPython3_EXECUTABLE=$PY_COV")
  fi
fi

configure_tree || exit 1

pushd "$BUILD_DIR" > /dev/null || exit 1

if [ "$DO_FAST_COV" = true ]; then
  log "Running fast targeted coverage for $TEST_ONE_BIN ($TEST_ONE_SRC)"
  make -j$JOBS ${TEST_ONE_BIN} || exit 1
  rm -f ${TEST_ONE_BIN}*.profraw ${TEST_ONE_BIN}.profdata "$COVERAGE_STAMP"
  LLVM_PROFILE_FILE="${TEST_ONE_BIN}-%p.profraw" ./${TEST_ONE_DIR:-test}/${TEST_ONE_BIN} || exit 1
  LLVM_PROFDATA=$(resolve_llvm_tool llvm-profdata)
  LLVM_COV=$(resolve_llvm_tool llvm-cov)
  if [ -n "$LLVM_PROFDATA" ] && [ -n "$LLVM_COV" ] && compgen -G "${TEST_ONE_BIN}-*.profraw" >/dev/null; then
    $LLVM_PROFDATA merge -sparse ${TEST_ONE_BIN}-*.profraw -o ${TEST_ONE_BIN}.profdata
    $LLVM_COV report -instr-profile=${TEST_ONE_BIN}.profdata -object ${TEST_ONE_DIR:-test}/${TEST_ONE_BIN} | grep "${TEST_ONE_SRC}"
  else
    log_err "ERROR: no profile was written, or llvm-profdata and llvm-cov were not found next to the configured compiler."
    exit 1
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
    find . -name "*.profraw" -delete
    if [ -n "$PROF_DIR" ]; then
      find "$PROF_DIR" -name "*.profraw" -delete
    fi
    rm -f coverage.profdata default.profdata "$COVERAGE_STAMP"
    # One profile per process (%p). A pooled name (%Nm) loses the profiles of
    # concurrent processes of one binary under ctest -j.
    export LLVM_PROFILE_FILE="${PROF_DIR:-.}/test-%p.profraw"
  fi

  if [ -n "$TEST_ONE_BIN" ]; then
    run_ctest_quiet -R "$TEST_ONE_BIN" || exit 1
  elif [ "$DO_COVERAGE" = true ]; then
    # Full C++ coverage run: quiet. The lsmiotool Python suite is measured by
    # py-coverage alone (one writer of the Python data), not here.
    run_ctest_quiet -E '^lsmiotool_python_suite$' || exit 1
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
        -type f \( -name "*.cpp" -o -name "*.hpp" -o -name "*.h" -o -name "*.tcc" -o -name "CMakeLists.txt" \) \
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
  # In-scope C++ files of the Code Coverage Invariant: the library implementation.
  SCOPE_CPP=$(cd "$ROOT_DIR" && find lib -type f -name '*.cpp' | LC_ALL=C sort)

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
    # The instrumented shared libraries are objects too: lsmio_plugin.cpp is built
    # only into liblsmio_adios, which ADIOS2 loads at run time, so no test binary
    # holds its coverage mapping.
    for lib in $(find "$BUILD_DIR/lib" -type f \( -name '*.so' -o -name '*.so.*' -o -name '*.dylib' \) | LC_ALL=C sort); do
      OBJ_ARGS="$OBJ_ARGS -object $lib"
    done

    LLVM_ERR=$(mktemp)
    if [ "$DO_COV_SHOW" = true ]; then
      log "Displaying line-by-line coverage for: $COV_FILE"
      $LLVM_COV show -instr-profile="$BUILD_DIR/default.profdata" \
        -format=text -show-branches=count \
        $MAIN_BIN $OBJ_ARGS \
        $COV_FILE 2> "$LLVM_ERR"
      SHOW_STATUS=$?
      llvm_check_warnings "$LLVM_ERR" || exit 1
      [ "$SHOW_STATUS" -eq 0 ] || exit "$SHOW_STATUS"
    else
      log "C++ coverage backend: llvm-cov"
      # Only the in-scope sources (lib/**/*.cpp) are reported. llvm-cov strips the
      # common path prefix from the row names; the awk below matches each row to
      # exactly one in-scope file by path suffix and prints the lib/... name. The
      # scope list reaches awk through the environment, space-joined (no newline
      # in an awk -v value).
      $LLVM_COV report -instr-profile="$BUILD_DIR/default.profdata" \
        $MAIN_BIN $OBJ_ARGS \
        $SCOPE_CPP 2> "$LLVM_ERR" | COV_SCOPE_WORDS=$(echo $SCOPE_CPP) awk -v fail_only="${DO_RESULTS_FAIL:-false}" -v thr="$COV_THRESHOLD" '
        BEGIN {
          RED = "\033[31m"; YELLOW = "\033[33m"; BLUE = "\033[34m"; RESET = "\033[0m";
          n_scope = split(ENVIRON["COV_SCOPE_WORDS"], scope_list, " ");
        }
        {
          if ($0 ~ /^-+$/ || $1 == "Filename" || $1 == "TOTAL") {
            print $0;
          } else {
            name = $1;
            full = ""; matches = 0;
            for (i = 1; i <= n_scope; i++) {
              f = scope_list[i];
              if (f == name || (length(f) > length(name) && substr(f, length(f) - length(name)) == "/" name)) {
                full = f; matches++;
              }
            }
            if (matches != 1) {
              print "[build.sh] ERROR: llvm-cov row \"" name "\" matches " matches " in-scope files" > "/dev/stderr";
              bad = 1; next;
            }
            seen[full] = 1;
            pos = index($0, name);
            if (pos > 0) $0 = substr($0, 1, pos - 1) full substr($0, pos + length(name));
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
              else if (min_val < thr) color = YELLOW;
              else color = BLUE;
              if (fail_only != "true" || color != BLUE) {
                print color $0 RESET;
              }
            } else {
              print $0;
            }
          }
        }
        END {
          # Every in-scope file must have a row; one without a row has no verdict.
          for (i = 1; i <= n_scope; i++) {
            if (!(scope_list[i] in seen)) {
              print "[build.sh] ERROR: no llvm-cov row for in-scope file " scope_list[i] > "/dev/stderr";
              bad = 1;
            }
          }
          exit bad
        }'
      REPORT_STATUS=("${PIPESTATUS[@]}")
      # The table is printed first; then llvm-cov's warnings are shown and a
      # mismatched-data warning fails the run.
      llvm_check_warnings "$LLVM_ERR"
      WARN_STATUS=$?
      if [ "${REPORT_STATUS[0]}" -ne 0 ] || [ "${REPORT_STATUS[1]}" -ne 0 ]; then
        log_err "ERROR: llvm-cov report failed (llvm-cov exit ${REPORT_STATUS[0]}, row check exit ${REPORT_STATUS[1]}: a row matched no in-scope file or an in-scope file has no row)"
        exit 1
      fi
      [ "$WARN_STATUS" -eq 0 ] || exit 1
    fi
    cd "$BUILD_DIR"
  elif [ -z "$LLVM_PROFDATA" ] || [ -z "$LLVM_COV" ]; then
    log_err "ERROR: llvm-profdata and llvm-cov were not found next to the configured compiler (they come with Clang)."
    exit 1
  else
    log_err "ERROR: No test-*.profraw files found: no C++ coverage run is recorded for this build."
    log_err "       Run: ./build.sh coverage"
    exit 1
  fi

fi

# py- commands given together with C++ commands run after them.
if [ ${#PY_ACTIONS[@]} -gt 0 ]; then
  py_run_actions || exit 1
fi

if [ "$CTEST_FAILED" -ne 0 ]; then
  exit 1
fi

popd > /dev/null

