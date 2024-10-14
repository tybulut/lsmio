# Google-Test
find_package(GTest 1.12 QUIET)
# NOT TARGET gtest
if (NOT GTest_FOUND AND NOT TARGET GTest)
  include(FetchContent)
  set(FETCHCONTENT_QUIET FALSE)

  block()
    set(INSTALL_GTEST OFF CACHE BOOL "Install")
    FetchContent_Declare(
      gtest
      GIT_REPOSITORY https://github.com/google/googletest.git
      GIT_TAG        v1.14.0
      GIT_PROGRESS   TRUE
    )

    FetchContent_MakeAvailable(gtest)
    include_directories(${googletest_SOURCE_DIR}/googletest/include)

    add_library(GTest::GTest ALIAS gtest)
    add_library(GTest::Main ALIAS gtest_main)
  endblock()
endif()

list(INSERT CMAKE_MODULE_PATH 0 "${PROJECT_SOURCE_DIR}/cmake/upstream")
include(GoogleTest)


