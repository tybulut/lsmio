# TLX
list(APPEND CMAKE_MODULE_PATH "/usr/share/cmake")
find_package(tlx QUIET)
if (NOT tlx_FOUND AND NOT TARGET tlx)
  include(FetchContent)
  set(FETCHCONTENT_QUIET FALSE)

  option(tlx_BUILD_TESTS "Build tests" OFF)
  FetchContent_Declare(
    tlx
    GIT_REPOSITORY https://github.com/tlx/tlx.git
    GIT_TAG v0.6.1
    GIT_SUBMODULES ""
    GIT_PROGRESS   TRUE
  )

  FetchContent_MakeAvailable(tlx)
  include_directories(${tlx_SOURCE_DIR})
endif()


