# Google-Test
include(FetchContent)
# NOT TARGET gtest
if (NOT gtest_FOUND)
  include(FetchContent)
  set(FETCHCONTENT_QUIET FALSE)

  block()
    set(INSTALL_GTEST OFF CACHE BOOL "Install")
    FetchContent_Declare(
      gtest
      GIT_REPOSITORY https://github.com/google/googletest.git
      GIT_TAG        v1.14.0
    )

    FetchContent_MakeAvailable(gtest)
    include_directories(${googletest_SOURCE_DIR}/googletest/include)
  endblock()

  add_library(GTest::GTest ALIAS gtest)
  add_library(GTest::Main ALIAS gtest_main)
endif()

list(INSERT CMAKE_MODULE_PATH 0 "${PROJECT_SOURCE_DIR}/cmake/upstream")
include(GoogleTest)


