# CLI11
list(APPEND CMAKE_MODULE_PATH "/usr/share/cmake")
find_package(CLI11 2 QUIET)
if (NOT CLI11_FOUND AND NOT TARGET CLI11)
  include(FetchContent)
  set(FETCHCONTENT_QUIET FALSE)

  option(CLI11_BUILD_TESTS "Build tests" OFF)
  FetchContent_Declare(
    cli11
    GIT_REPOSITORY https://github.com/CLIUtils/CLI11.git
    GIT_TAG v2.4.2
    GIT_SUBMODULES ""
    GIT_PROGRESS   TRUE
  )

  FetchContent_MakeAvailable(cli11)
  include_directories(${cli11_SOURCE_DIR}/include)
endif()


