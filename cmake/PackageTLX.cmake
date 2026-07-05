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

  # tlx v0.6.1 declares a cmake_minimum_required below 3.5, which CMake 4+
  # refuses to configure. This override lets its configure proceed and is
  # ignored by older CMake versions.
  set(CMAKE_POLICY_VERSION_MINIMUM 3.5)
  FetchContent_MakeAvailable(tlx)
  unset(CMAKE_POLICY_VERSION_MINIMUM)
  include_directories(${tlx_SOURCE_DIR})
endif()


