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
  # refuses to configure ("Compatibility with CMake < 3.5 has been removed").
  # Relax the policy floor so its add_subdirectory (done inside
  # FetchContent_MakeAvailable) configures anyway. This must be a cache entry:
  # a normal variable does not reliably propagate into the FetchContent
  # subdirectory scope. Older CMake versions ignore it.
  set(CMAKE_POLICY_VERSION_MINIMUM 3.5 CACHE STRING
      "Minimum CMake policy version for third-party deps with old cmake_minimum_required")
  set(CMAKE_POLICY_DEFAULT_CMP0048 NEW CACHE STRING "Suppress CMP0048 warning")
  FetchContent_MakeAvailable(tlx)
  unset(CMAKE_POLICY_DEFAULT_CMP0048 CACHE)
  unset(CMAKE_POLICY_VERSION_MINIMUM CACHE)
  include_directories(${tlx_SOURCE_DIR})
endif()


