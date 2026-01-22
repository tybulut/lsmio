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
