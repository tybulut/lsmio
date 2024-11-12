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
    GIT_TAG        1.2.1
    GIT_SUBMODULES ""
    GIT_PROGRESS   TRUE
  )

  FetchContent_MakeAvailable(snappy)
  add_library(Snappy::snappy ALIAS snappy)
endif()

# LevelDB
find_package(leveldb 1.23 QUIET)
if (NOT leveldb_FOUND AND NOT TARGET leveldb)
  include(FetchContent)
  set(FETCHCONTENT_QUIET FALSE)


  # leveldb
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
  add_library(leveldb::leveldb ALIAS leveldb)
endif()

