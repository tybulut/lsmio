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
