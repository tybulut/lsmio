## Coding style
* When applicable, separate the header and source files for CPP code
* Use camel-case method names
* Use pascal-case class names and file names
* Use pascal-case for test file names with Test as suffix (e.g. CharacterTest.cpp)
* Use snake-case for member variables and function arguments / variables
* For class member variables use  m_ prefix.
* For function and method argument variables use f_ prefix.

## Build System
The project uses CMake and provides a `build.sh` helper script for common tasks.

* **Compiler:** lsmio builds with Clang by default when Clang 19 or newer is installed; otherwise with the default compilers. When none of `CC`, `CXX`, `CMAKE_C_COMPILER` and `CMAKE_CXX_COMPILER` is set, CMake picks `clang++` and the `clang` next to it. If Clang cannot link out of the box (no libstdc++ where it looks), CMake looks for a GCC installation that has libstdc++ and that Clang builds with, and caches `--gcc-install-dir` for it (your own `CFLAGS`, `CXXFLAGS` and `LDFLAGS` are kept); no flag is needed on the command line. The compilers are cached, so this happens once per build tree.
* **Choosing GCC:** set the compilers on the call that cleans, because CMake keeps the compiler it cached: `env CC=gcc CXX=g++ ./build.sh clean test`. To return to Clang, `env -u CC -u CXX ./build.sh clean test`. Each switch costs a full rebuild. Ubuntu CI builds with GCC (macOS CI with AppleClang) and runs ctest without coverage, so both compilers stay tested.
* **Coverage requires Clang:** C++ coverage uses Clang's instrumentation and llvm-cov. `./build.sh coverage` and C++ `fast-cov` stop with a message on a tree built with another compiler, and CMake refuses `LSMIO_ENABLE_COVERAGE=ON` with one; start a Clang tree with `./build.sh clean coverage` with `CC` and `CXX` unset.
* **Profile data:** the coverage run writes one profile file per test process (`test-<pid>.profraw`) and merges them, so tests running in parallel do not overwrite each other's profiles. Only code defined in `.cpp` files is instrumented (`cmake/lsmio-profile-list.txt`), so header functions that several libraries hold cannot disagree in the profile.

### Build Script (`build.sh`)
Usage: `./build.sh [args...]`
* `debug`: Sets `CMAKE_BUILD_TYPE` to `DEBUG`.
* `clean`: Cleans the build directory (preserving out-of-tree scratch build symlinks).
* `clean-cov`: Cleans coverage data: C++ (`.profraw`, `.profdata`, `.coverage-stamp`) and Python (data file, marker, JSON, Python stamp, `fast-cov` data).
* `make`: Compiles the project using `make -j<jobs>`.
* `test`: Compiles and runs tests using `ctest -j<jobs>`.
* `xtest [regex]`: Compiles and runs CTest quietly; failing output goes to a log (supports optional regex filter).
* `itest <regex> [target]`: Compiles target and runs `ctest -R <regex>` quietly.
* `install [tag]`: Compiles and installs the project to `$HOME/src/usr` (or with tag e.g. `install:main`).
* `py-xtest`: Runs the lsmiotool Python suite quietly (one summary line; failing output goes to a log in the build tree). Builds no C++.
* `py-itest <test name>`: Like `py-xtest` for one dotted test name (module, class or method, e.g. `lsmiotool.test.main.VersionTest`).
* `coverage`: Builds with coverage (Clang), runs the C++ test suite and prints the C++ coverage report (llvm-cov). The run fails, after printing the table, when llvm-cov reports functions with mismatched data or an in-scope file has no row.
* `results`: Reprints the C++ report from the last `coverage` run (refuses when that run is missing or stale).
* `results-fail`: Like `results`, listing only files below 95% on line or branch.
* `py-coverage`: Runs the lsmiotool suite under coverage.py (branch mode) and prints the Python report. Builds no C++ and leaves the C++ coverage run alone.
* `py-results`: Reprints the Python report from the last `py-coverage` run (refuses when that run is missing or stale).
* `py-results-fail`: Like `py-results`, listing only files below 95% on line or branch.
* `fast-cov <bin> <src> [dir]`: Fast targeted C++ coverage for one test binary and one source file. It invalidates the last `coverage` run (`results` and `cov-show` refuse until the next `coverage`).
* `fast-cov <test_module> <src.py>`: Fast targeted Python coverage for one test module and one `tools/lsmiotool` source file. It leaves the `py-coverage` data alone.
* `cov-show <file>`: Displays line-by-line coverage for a `lib/...cpp` file (last `coverage` run) or a `tools/lsmiotool/...py` file (last `py-coverage` run), with branch decisions.

### CMake Options
* `BUILD_SHARED_LIBS`: Build shared libraries (default: `ON`).
* `LSMIO_BUILD_BENCHMARKS`: Build LSMIO benchmarks (default: `ON`).
* `LSMIO_BUILD_TESTS`: Compile LSMIO tests (default: `ON`).
* `LSMIO_ENABLE_COVERAGE`: Enable code coverage reporting (default: `OFF`).
* `CMAKE_BUILD_TYPE`: Standard CMake build type (`RELEASE`, `DEBUG`, etc.).
* `CMAKE_INSTALL_PREFIX`: Path where the project will be installed.

### Micro-benchmarks (`micro.sh`)
Usage: `./micro.sh [targets...] [-i iterations]`
* **Targets**: `adios`, `plugin`, `rocksdb`, `leveldb`, `native`.
* **Options**:
    * `-i`, `--iterations <N>`: Number of iterations to run (default: 5).
* **Notes**: 
    * At least one target must be selected.
    * The script automatically runs `make install` before benchmarks.
    * Benchmark results are stored in `~/benchmark`.

## Code Coverage Invariant
The dev workflow's Coverage Rules apply to lsmio with these values, which replace the defaults.

* **Floor:** each changed in-scope file reaches Line >= 95% AND Branch >= 95%. A file with no branches counts as 100% branch coverage, and a file with no statements as 100% line coverage. The Coverage Rules' tolerance of 0.5 percentage points applies.
* **C++ scope:** the library implementation, `lib/**/*.cpp`.
    * Out of scope: headers and inline templates (`include/**`, `lib/**/*.hpp`, `lib/**/*.tcc`), tests (`test/**`), benchmark programs (`benchmark/**`, including `benchmark/bm_base.cpp`, which `test_bm_base` compiles), and anything outside the lsmio tree. lsmio has no vendored or generated C++ sources.
* **Python scope:** lsmiotool's package code, `tools/lsmiotool/**/*.py`.
    * Out of scope: its tests and fixtures (`tools/lsmiotool/test/**`), the installed-layout smoke test (`tools/lsmiotool/ctest/**`), the entry scripts without a `.py` suffix (`tools/lsmiotool/lsmiotool`, `tools/lsmiotool/lsmiotool-worker`), configure templates (`*.in`) and `venv/**`.
    * Code that runs only in a child process is not measured; cover it with tests that call it in-process.
* **Authoritative runs:** one per language.
    * C++: llvm-cov is the only backend. `./build.sh coverage` builds with Clang (lsmio's default compiler), runs the C++ tests and prints the report; `./build.sh results` reprints it, `./build.sh results-fail` lists only the in-scope files below 95% on line or branch, and `./build.sh cov-show <file>` annotates one file. Coverage on a tree configured with another compiler fails with a message; start a Clang tree with `./build.sh clean coverage` with `CC`/`CXX` unset (an explicit `CXX=clang++` skips the probe that may be needed to find libstdc++). The report names its backend (llvm-cov) in a line before the table. Line and branch counts are llvm-cov's own.
    * If Clang cannot link out of the box, CMake looks for a GCC installation that has libstdc++ and that Clang links with, and caches `--gcc-install-dir` for it; no flag is needed on the command line. Flags a caller needs for one compiler go on the cleaning command only and are not exported.
    * Mismatched data: if llvm-cov warns that functions have mismatched data, it has not loaded those functions' records, so file figures can move either way. `coverage`, `results` and `results-fail` then print the table and fail with a message. Such a run gives no C++ verdict for any file, and the audit reports `STATUS: FAILED` with that reason. The same holds when an in-scope file has no row.
    * Python: `./build.sh py-coverage` runs the lsmiotool suite under coverage.py in branch mode and prints the report; `./build.sh py-results` reprints it from that run, and `./build.sh py-results-fail` lists only the in-scope files below 95% on line or branch. The `Cover` column of coverage.py's own `coverage report` combines statements and branches and is not the invariant's number.
* **Per-chunk check:** `./build.sh fast-cov <test_binary> <lib/...cpp> [dir]` for C++ (`dir` defaults to `test`), `./build.sh fast-cov <test_module> <tools/lsmiotool/...py>` for Python (`<test_module>` as `./lsmiotool test` takes it, e.g. `lsmiotool.test.main.VersionTest`). Both measure one test target, so a gap they show may be covered elsewhere. C++ `fast-cov` (Clang trees only) invalidates the last full run (it removes the coverage stamp), so `results` and `cov-show` refuse until the next `./build.sh coverage`; Python `fast-cov` leaves the `py-coverage` data alone.
* **Large chunk:** the Coverage Rules' 200-line count sums lines added to in-scope `.cpp` and `.py` files.
* **Line inspection:** `./build.sh cov-show <file>` annotates a `.cpp` file from the last `coverage` run, or an in-scope `.py` file from the last `py-coverage` run; `extract_gaps.py --submodule lsmio` reads it for both.
* **Run-to-run variation:** some in-scope C++ files (today `benchmark.cpp`, `manager/manager.cpp`, `manager/store/native/SSTableManager.cpp`, `manager/store/native/StoreNative.cpp` and `posix/posix.cpp`) are reached by tests whose paths depend on timing. Executed counts of such a file can differ by a few lines or branches between two runs, while its line and branch totals stay fixed. A changed file that sits close to 95% can pass in one run and fail in the next.

## Directory Structure
* `include/lsmio/`: Public header files.
* `lib/`: Core library implementation.
    * `adios-plugin/`: ADIOS2 engine plugin.
    * `manager/`: Internal management of clients and stores.
    * `posix/`: POSIX-like API layer.
* `test/`: Unit tests using GoogleTest.
* `benchmark/`: Performance benchmarking tools.
* `cmake/`: Custom CMake modules and package configurations.
* `doc/`: Documentation and dependency installation scripts.
* `tools/`: Python and shell-based utility tools.

## Testing & Debugging
* **Testing**: Use `ctest --output-on-failure` to see detailed output from failed tests.
* **Debugging**: 
    * On **Linux**, use `gdb` to debug segmentation faults or other crashes.
    * On **macOS**, use `lldb` for debugging.
