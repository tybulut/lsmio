# Google-Test
include(FetchContent)
# NOT TARGET gtest
if (NOT gtest_FOUND)
  include(FetchContent)
  FetchContent_Declare(
    gtest
    GIT_REPOSITORY https://github.com/google/googletest.git
    GIT_TAG        v1.14.0
  )

  FetchContent_MakeAvailable(gtest)
  include_directories(${googletest_SOURCE_DIR}/googletest/include)
  add_library(GTest::GTest ALIAS gtest)
  add_library(GTest::Main ALIAS gtest_main)
endif()

list(INSERT CMAKE_MODULE_PATH 0 "${PROJECT_SOURCE_DIR}/cmake/upstream")
include(GoogleTest)


