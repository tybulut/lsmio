include_guard(GLOBAL)

# Packages
find_package(MPI REQUIRED GLOBAL)
find_package(Threads REQUIRED GLOBAL)

# ADIOS2
find_package(ADIOS2 QUIET GLOBAL)
if (ADIOS2_FOUND)
  if (TARGET adios2::cxx11 AND NOT TARGET adios2::cxx)
    add_library(adios2::cxx ALIAS adios2::cxx11)
  endif()
  if (TARGET adios2::cxx11_mpi AND NOT TARGET adios2::cxx_mpi)
    add_library(adios2::cxx_mpi ALIAS adios2::cxx11_mpi)
  endif()
endif()

if (NOT ADIOS2_FOUND AND NOT TARGET ADIOS2)
  include(FetchContent)
  set(FETCHCONTENT_QUIET FALSE)

  # Features
  set(ADIOS2_USE_MPI        ON  CACHE BOOL   "Turn on MPI" FORCE)
  set(ADIOS2_USE_Fortran    OFF CACHE STRING "Turn off Fortran" FORCE)
  set(ADIOS2_USE_ZeroMQ     OFF CACHE BOOL   "Turn off ZeroMQ" FORCE)
  # Testing and Examples
  set(BUILD_TESTING         OFF CACHE INTERNAL "Turn off Testing" FORCE)
  set(ADIOS2_BUILD_EXAMPLES OFF CACHE BOOL "Turn off Examples" FORCE)
  set(ADIOS2_BUILD_EXAMPLES_EXPERIMENTAL  OFF CACHE BOOL "Turn off Testing" FORCE)

  # Include ADIOS2
  FetchContent_Declare(
    ADIOS2
    GIT_REPOSITORY https://github.com/ornladios/ADIOS2.git
    GIT_TAG        v2.9.2
    GIT_PROGRESS   TRUE
  )

  # ADIOS2 v2.9.2 declares a cmake_minimum_required below 3.5, which CMake 4+
  # refuses to configure. Relax the policy floor via a persisted cache entry so
  # its add_subdirectory (inside FetchContent_MakeAvailable) configures anyway.
  # A normal variable does not reliably reach the FetchContent subdirectory
  # scope; older CMake ignores this. Mirrors cmake/PackageTLX.cmake and the
  # -DCMAKE_POLICY_VERSION_MINIMUM=3.5 in doc/dependencies/21-build-adios2.sh.
  set(CMAKE_POLICY_VERSION_MINIMUM 3.5 CACHE STRING
      "Minimum CMake policy version for third-party deps with old cmake_minimum_required")
  FetchContent_MakeAvailable(ADIOS2)

  add_library(adios2::core ALIAS adios2_core)
  add_library(adios2::core_mpi ALIAS adios2_core_mpi)
  if(TARGET adios2_cxx11 AND NOT TARGET adios2::cxx)
    add_library(adios2::cxx ALIAS adios2_cxx11)
  endif()
  if(TARGET adios2_cxx11_mpi AND NOT TARGET adios2::cxx_mpi)
    add_library(adios2::cxx_mpi ALIAS adios2_cxx11_mpi)
  endif()
endif()
