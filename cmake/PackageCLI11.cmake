# CLI11
find_package(cli11 2.4 QUIET)
if (NOT cli11_FOUND)
  include(FetchContent)

  # LevelDB Dependency: Snappy
  option(CLI11_BUILD_TESTS "Build tests" OFF)
  FetchContent_Declare(
    cli11
    GIT_REPOSITORY https://github.com/CLIUtils/CLI11.git
    GIT_TAG v2.4.2
    GIT_SUBMODULES ""
  )

  FetchContent_MakeAvailable(cli11)
  include_directories(${cli11_SOURCE_DIR}/include)
endif()

