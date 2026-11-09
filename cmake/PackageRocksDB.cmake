# RocksDB Dependency: GFlags
find_package(gflags 2.2 QUIET)
if (NOT gflags_FOUND AND NOT TARGET gflags)
  include(FetchContent)
  set(FETCHCONTENT_QUIET FALSE)

  option(GFLAGS_BUILD_TESTS "Build tests" OFF)
  FetchContent_Declare(
    gflags
    GIT_REPOSITORY https://github.com/gflags/gflags.git
    GIT_TAG        v2.2.2
    GIT_SUBMODULES ""
    GIT_PROGRESS   TRUE
  )

  FetchContent_MakeAvailable(gflags)
endif()

# RocksDB
foreach(VERSION 10 9 8 7)
    find_package(RocksDB ${VERSION} QUIET)
    if(RocksDB_FOUND)
        break()
    endif()
endforeach()

if (NOT RocksDB_FOUND AND NOT TARGET RocksDB)
  message(STATUS "RocksDB: Could not find rocksdb version 8 <-> 10.")
  include(FetchContent)
  set(FETCHCONTENT_QUIET FALSE)

  #include(CMakePrintHelpers)
  #cmake_print_variables(RocksDB_FOUND)
  #cmake_print_variables(CMAKE_MODULE_PATH)

  # rocksdb
  block()
    # Compression codecs: mirror doc/dependencies/23-build-rocksdb.sh so source builds have a
    # supported codec (Snappy, LZ4, Zstd). Include $HOME/src/usr and (on macOS) the Homebrew prefix
    # in CMAKE_PREFIX_PATH so find_package locates codecs installed there.
    if(DEFINED ENV{HOME} AND EXISTS "$ENV{HOME}/src/usr")
      list(PREPEND CMAKE_PREFIX_PATH "$ENV{HOME}/src/usr")
    endif()
    if(APPLE)
      find_program(_BREW_EXECUTABLE brew)
      if(_BREW_EXECUTABLE)
        execute_process(
          COMMAND "${_BREW_EXECUTABLE}" --prefix
          OUTPUT_VARIABLE _BREW_PREFIX
          OUTPUT_STRIP_TRAILING_WHITESPACE
          ERROR_QUIET
        )
        if(_BREW_PREFIX)
          list(PREPEND CMAKE_PREFIX_PATH "${_BREW_PREFIX}")
        endif()
      endif()
    endif()

    # Snappy is guaranteed by PackageLevelDB.cmake (system package or FetchContent target `snappy`).
    # When Snappy came from FetchContent rather than a system install, pre-populate the variables
    # RocksDB's FindSnappy.cmake checks and add `snappy` to RocksDBTargets so RocksDB's
    # install(EXPORT RocksDBTargets) succeeds.
    if(TARGET snappy AND NOT Snappy_FOUND)
      set(Snappy_INCLUDE_DIR "${snappy_SOURCE_DIR}" CACHE PATH "Snappy include dir")
      set(Snappy_LIBRARIES snappy CACHE STRING "Snappy libraries")
      install(TARGETS snappy EXPORT RocksDBTargets)
    endif()
    set(WITH_SNAPPY YES CACHE BOOL "with snappy")

    # Enable LZ4 and Zstd when their headers and libraries are available on the host (RocksDB's
    # CMakeLists.txt calls find_package(lz4 REQUIRED) and find_package(zstd REQUIRED)).
    find_path(lz4_INCLUDE_DIRS NAMES lz4.h)
    find_library(lz4_LIBRARIES NAMES lz4)
    if(lz4_INCLUDE_DIRS AND lz4_LIBRARIES)
      set(WITH_LZ4 YES CACHE BOOL "with lz4")
    else()
      set(WITH_LZ4 NO CACHE BOOL "with lz4")
    endif()

    find_path(ZSTD_INCLUDE_DIRS NAMES zstd.h)
    find_library(ZSTD_LIBRARIES NAMES zstd)
    if(ZSTD_INCLUDE_DIRS AND ZSTD_LIBRARIES)
      set(WITH_ZSTD YES CACHE BOOL "with zstd")
    else()
      set(WITH_ZSTD NO CACHE BOOL "with zstd")
    endif()

    set(FAIL_ON_WARNINGS NO CACHE BOOL "fail on warnings")
    set(CMAKE_POSITION_INDEPENDENT_CODE ON CACHE BOOL "-fPIC")
    # Features
    set(JNI NO CACHE BOOL "with jni")
    set(USE_RTTI YES CACHE BOOL "with RTTI")
    set(WITH_JNI NO CACHE BOOL "with jni")
    set(WITH_GFLAGS NO CACHE BOOL "with gflags")
    # Tests
    set(BENCHMARK_ENABLE_GTEST_TESTS NO CACHE BOOL "with gtest")
    set(WITH_ALL_TESTS NO CACHE BOOL "with all tests")
    set(WITH_TESTS NO CACHE BOOL "with tests")
    # Tools
    set(WITH_BENCHMARK NO CACHE BOOL "with benchmark")
    set(WITH_BENCHMARK_TOOLS NO CACHE BOOL "with benchmark tools")
    set(WITH_CORE_TOOLS NO CACHE BOOL "with core tools")
    set(WITH_EXAMPLES NO CACHE BOOL "with examples")
    set(WITH_TOOLS NO CACHE BOOL " with tools")
    set(WITH_TRACE_TOOLS NO CACHE BOOL "with trace tools")

    FetchContent_Declare(
      rocksdb
      GIT_REPOSITORY https://github.com/facebook/rocksdb.git
      GIT_TAG        v8.11.4
      GIT_SUBMODULES ""
      GIT_PROGRESS   TRUE
    )

    FetchContent_MakeAvailable(rocksdb)

    add_library(RocksDB::rocksdb-shared ALIAS rocksdb)
  endblock()
else()
  message(STATUS "RocksDB: Found rocksdb version ${RocksDB_VERSION}.")
endif()

