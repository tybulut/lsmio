# LevelDB
find_package(rocksdb 8.9 QUIET)
if (NOT rocksdb_FOUND)
  include(FetchContent)
  set(FETCHCONTENT_QUIET FALSE)

  # rocksdb
  block()
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

    add_library(rocksdb::rocksdb ALIAS rocksdb)
  endblock()
endif()

