cmake_minimum_required(VERSION 3.12)
project(lsmio VERSION 0.1.6)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(CMAKE_FIND_PACKAGE_TARGETS_GLOBAL ON)

if(CMAKE_SIZEOF_VOID_P EQUAL 8)
  message(STATUS "Main: 64-bit compiler detected")
else(CMAKE_SIZEOF_VOID_P EQUAL 8)
  message(FATAL_ERROR "Main: 32-bit compiler detected")
endif(CMAKE_SIZEOF_VOID_P EQUAL 8)

include(ProcessorCount)
ProcessorCount(N)
if (N GREATER_EQUAL 2)
  math(EXPR M "${N} / 2" OUTPUT_FORMAT DECIMAL)
  message(STATUS "Main: Recommended minimum CMAKE_BUILD_PARALLEL_LEVEL: ${M}")
endif()

list(PREPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")
set(LSMIO_SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")

# Compiler options
option(BUILD_SHARED_LIBS "Build shared libraries" ON)
#set_property(TARGET compiler PROPERTY ENABLE_EXPORTS ON) # -rdynamic
#set(CMAKE_POSITION_INDEPENDENT_CODE ON) # -fPIC
# Other options
option(LSMIO_BUILD_BENCHMARKS "Build LSMIO benchmarks" ON)
option(LSMIO_BUILD_TESTS "Build the testing tree." ON)

# Other options

# Custom package directory
set(CUSTOM_PACKAGE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")

# Defines
add_subdirectory(include)

# Sub directories
add_subdirectory(lib)

# enable benchmark functionality
if(LSMIO_BUILD_BENCHMARKS)
  add_subdirectory(benchmark)
endif()

# Last step
include(DebianPkg)

# enable testing functionality
if(LSMIO_BUILD_TESTS)
  # Include dependencies
  include(CTest)

  enable_testing()
  add_subdirectory(test)
endif()

