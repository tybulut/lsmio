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

### Build Script (`build.sh`)
Usage: `./build.sh [args...]`
* `debug`: Sets `CMAKE_BUILD_TYPE` to `DEBUG`.
* `clean`: Removes and recreates the `build/` directory.
* `make`: Compiles the project using `make -j8`.
* `test`: Runs tests using `ctest -j8`.
* `install`: Installs the project to `$HOME/src/usr`.
* `coverage`: Enables code coverage, runs tests, and generates an HTML report in `build/coverage_report/`.

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
