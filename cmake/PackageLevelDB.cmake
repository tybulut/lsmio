# LevelDB Dependency: Snappy
find_package(Snappy 1.1 QUIET)
if (NOT Snappy_FOUND AND NOT TARGET snappy)
  include(FetchContent)
  set(FETCHCONTENT_QUIET FALSE)

  option(SNAPPY_BUILD_TESTS "Build tests" OFF)
  option(SNAPPY_BUILD_BENCHMARKS "Build benchmarks" OFF)
  FetchContent_Declare(
    snappy
    GIT_REPOSITORY https://github.com/google/snappy.git
    GIT_TAG        1.3.1
    GIT_SUBMODULES ""
    GIT_PROGRESS   TRUE
  )

  set(CMAKE_POLICY_VERSION_MINIMUM 3.5 CACHE STRING
      "Minimum CMake policy version for third-party deps with old cmake_minimum_required")
  FetchContent_MakeAvailable(snappy)
  unset(CMAKE_POLICY_VERSION_MINIMUM CACHE)
  if (NOT MSVC)
    target_compile_options(snappy PRIVATE -frtti)
  endif()
  add_library(Snappy::snappy ALIAS snappy)
endif()
# An installed LevelDB built with Snappy exports the bare name `snappy` in its link interface,
# which CMake would pass as -lsnappy with no search path. A global `snappy` target that stands
# for the found Snappy package makes that name resolve to the library's full path in every
# directory that links LevelDB (lib, test, benchmark).
if (Snappy_FOUND AND NOT TARGET snappy)
  set_target_properties(Snappy::snappy PROPERTIES IMPORTED_GLOBAL TRUE)
  add_library(snappy INTERFACE IMPORTED GLOBAL)
  target_link_libraries(snappy INTERFACE Snappy::snappy)
endif()

# LevelDB
find_package(leveldb 1.23 QUIET)
if (NOT leveldb_FOUND AND NOT TARGET leveldb)
  include(FetchContent)
  set(FETCHCONTENT_QUIET FALSE)


  # leveldb
  # Pre-set HAVE_SNAPPY so LevelDB's check_library_exists(snappy snappy_compress "" HAVE_SNAPPY)
  # does not disable Snappy when `snappy` comes from FetchContent and is not yet compiled at
  # configure time.
  set(HAVE_SNAPPY ON CACHE BOOL "Build LevelDB with Snappy")
  option(LEVELDB_BUILD_TESTS "Build tests" OFF)
  option(LEVELDB_BUILD_BENCHMARKS "Build benchmarks" OFF)
  FetchContent_Declare(
    leveldb
    GIT_REPOSITORY https://github.com/google/leveldb.git
    GIT_TAG        1.23
    GIT_SUBMODULES ""
    GIT_PROGRESS   TRUE
  )

  FetchContent_MakeAvailable(leveldb)
  # LevelDB appends -fno-rtti to CMAKE_CXX_FLAGS; target options come later on the compile
  # line, so -frtti wins (lsmio's no-sync Env derives from LevelDB classes)
  if (NOT MSVC)
    target_compile_options(leveldb PRIVATE -frtti)
  endif()
  add_library(leveldb::leveldb ALIAS leveldb)
endif()

