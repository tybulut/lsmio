cmake_minimum_required(VERSION 3.12)
project(lsmio VERSION 0.1.0)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

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

set(DEV_PACKAGE_DIR "$ENV{HOME}/src/usr")
list(PREPEND CMAKE_PREFIX_PATH "${DEV_PACKAGE_DIR}")
list(PREPEND CMAKE_INCLUDE_PATH "${DEV_PACKAGE_DIR}/include")
list(PREPEND CMAKE_LIBRARY_PATH "${DEV_PACKAGE_DIR}/lib")
list(PREPEND CMAKE_LIBRARY_PATH "${DEV_PACKAGE_DIR}/lib64")
list(PREPEND CMAKE_MODULE_PATH "${DEV_PACKAGE_DIR}/lib")
list(PREPEND CMAKE_MODULE_PATH "${DEV_PACKAGE_DIR}/lib64")

set(LSMIO_SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")

link_directories(${DEV_PACKAGE_DIR}/lib)
link_directories(${DEV_PACKAGE_DIR}/lib64)

# Compiler options
option(BUILD_SHARED_LIBS "Build shared libraries" ON)
#set_property(TARGET compiler PROPERTY ENABLE_EXPORTS ON) # -rdynamic
#set(CMAKE_POSITION_INDEPENDENT_CODE ON) # -fPIC

include(CTest)

# Custom package directory
set(CUSTOM_PACKAGE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")

# Defines
add_subdirectory(include)

# Sub directories
add_subdirectory(lib)
add_subdirectory(benchmark)

# enable testing functionality
enable_testing()
add_subdirectory(test)

