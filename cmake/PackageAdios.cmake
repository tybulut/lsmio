# Packages
find_package(MPI REQUIRED GLOBAL)
find_package(Threads REQUIRED GLOBAL)

# ADIOS2
find_package(ADIOS2 QUIET GLOBAL)
if (NOT ADIOS2_FOUND)
  include(FetchContent)
  set(FETCHCONTENT_QUIET FALSE)

  block()
    # Features
    set(ADIOS2_USE_MPI        ON  CACHE BOOL "Turn on MPI")
    set(ADIOS2_USE_Fortran    OFF CACHE BOOL "Turn off Fortran")
    set(ADIOS2_USE_ZeroMQ     OFF CACHE BOOL "Turn off ZeroMQ")
    # Testing and Examples
    set(ADIOS2_BUILD_TESTING  OFF CACHE BOOL "Turn off Testing")
    set(ADIOS2_BUILD_EXAMPLES OFF CACHE BOOL "Turn off Examples")
    set(BUILD_TESTING         OFF CACHE BOOL "Turn off Testing")

    # Include ADIOS2
    FetchContent_Declare(
      ADIOS2
      GIT_REPOSITORY https://github.com/ornladios/ADIOS2.git
      GIT_TAG        v2.9.2
    )

    FetchContent_MakeAvailable(ADIOS2)
  endblock()

  add_library(adios2::core ALIAS adios2_core)
  add_library(adios2::core_mpi ALIAS adios2_core_mpi)
endif()

