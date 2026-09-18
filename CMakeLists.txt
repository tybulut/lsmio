cmake_minimum_required(VERSION 3.12)

file(READ "${CMAKE_CURRENT_SOURCE_DIR}/tools/lsmiotool/VERSION" LSMIO_VERSION)
string(STRIP "${LSMIO_VERSION}" LSMIO_VERSION)

project(lsmio VERSION ${LSMIO_VERSION} LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(CMAKE_FIND_PACKAGE_TARGETS_GLOBAL ON)

# RPATH settings
set(CMAKE_MACOSX_RPATH 1)
set(CMAKE_INSTALL_RPATH "${CMAKE_INSTALL_PREFIX}/lib")
set(CMAKE_INSTALL_RPATH_USE_LINK_PATH TRUE)

if(CMAKE_SIZEOF_VOID_P EQUAL 8)
  message(STATUS "Main: 64-bit compiler detected")
else(CMAKE_SIZEOF_VOID_P EQUAL 8)
  message(FATAL_ERROR "Main: 32-bit compiler detected")
endif(CMAKE_SIZEOF_VOID_P EQUAL 8)

# MacOS
if(APPLE)
    add_compile_options(-Wno-vla-cxx-extension)
endif()

include(ProcessorCount)
ProcessorCount(N)
if (N GREATER_EQUAL 2)
  math(EXPR M "${N} / 2" OUTPUT_FORMAT DECIMAL)
  message(STATUS "Main: Recommended minimum CMAKE_BUILD_PARALLEL_LEVEL: ${M}")
endif()

set(LSMIO_SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
set(CUSTOM_PACKAGE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")

list(PREPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")
include(cmake/ProjectOptions.cmake)
lsmio_setup_options()

execute_process(
  COMMAND git rev-parse --abbrev-ref HEAD
  WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
  OUTPUT_VARIABLE LSMIO_GIT_BRANCH
  OUTPUT_STRIP_TRAILING_WHITESPACE
  ERROR_QUIET
)
execute_process(
  COMMAND git rev-parse --short HEAD
  WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
  OUTPUT_VARIABLE LSMIO_GIT_COMMIT_HASH
  OUTPUT_STRIP_TRAILING_WHITESPACE
  ERROR_QUIET
)

if(NOT LSMIO_GIT_BRANCH)
  set(LSMIO_GIT_BRANCH "unknown")
endif()

if(NOT LSMIO_GIT_COMMIT_HASH)
  set(LSMIO_GIT_COMMIT_HASH "unknown")
endif()

add_compile_definitions(
  LSMIO_VERSION_STR="${LSMIO_VERSION}"
  LSMIO_GIT_BRANCH="${LSMIO_GIT_BRANCH}"
  LSMIO_GIT_COMMIT_HASH="${LSMIO_GIT_COMMIT_HASH}"
)

# Linker: prefer lld when the toolchain supports it; it is multi-threaded and
# links much faster than GNU ld. Opt out with -DLSMIO_USE_LLD=OFF. Skipped on
# Apple, whose default linker is already fast, and on CMake < 3.18, which lacks
# check_linker_flag.
option(LSMIO_USE_LLD "Link with lld when available" ON)
if(LSMIO_USE_LLD AND NOT APPLE AND CMAKE_VERSION VERSION_GREATER_EQUAL 3.18)
  include(CheckLinkerFlag)
  check_linker_flag(CXX "-fuse-ld=lld" LSMIO_HAS_LLD)
  if(LSMIO_HAS_LLD)
    add_link_options(-fuse-ld=lld)
  endif()
endif()

# Defines
add_subdirectory(include)
include(PackageTLX)

# Sub directories
add_subdirectory(lib)

# enable benchmark functionality
if(LSMIO_BUILD_BENCHMARKS)
  add_subdirectory(benchmark)
endif()

# tools
add_subdirectory(tools/lsmiotool)

# Last step
include(DebianPkg)

# enable testing functionality
if(LSMIO_BUILD_TESTS)
  # Include dependencies
  include(CTest)
  find_package(Python3 REQUIRED COMPONENTS Interpreter)

  if(LSMIO_ENABLE_COVERAGE)
    execute_process(
      COMMAND "${Python3_EXECUTABLE}" -c "import coverage"
      RESULT_VARIABLE _coverage_status
      OUTPUT_QUIET
      ERROR_QUIET
    )
    if(NOT _coverage_status EQUAL 0)
      message(FATAL_ERROR "LSMIO_ENABLE_COVERAGE is ON, but Python 'coverage' module is not available on '${Python3_EXECUTABLE}'. Please install coverage (e.g. '${Python3_EXECUTABLE} -m pip install coverage') and re-run CMake.")
    endif()
  endif()

  enable_testing()
  add_subdirectory(test)
endif()

lsmio_print_build_config()
