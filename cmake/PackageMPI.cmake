#
# This module provides a way to find MPI that is compatible with both
# standard distributions (like OpenMPI, MPICH) and Cray-MPICH on Cray systems.
#

if (NOT TARGET MPI::MPI_CXX)
  # On Cray systems, the compiler wrappers (CC, cc, ftn) handle MPI automatically.
  # We check if MPI is already available via the compiler.
  include(CheckCXXSourceCompiles)
  set(CMAKE_REQUIRED_FLAGS_SAVE ${CMAKE_REQUIRED_FLAGS})
  set(CMAKE_REQUIRED_LIBRARIES_SAVE ${CMAKE_REQUIRED_LIBRARIES})

  # Try to compile a simple MPI program without any extra flags
  check_cxx_source_compiles("
    #include <mpi.h>
    int main(int argc, char **argv) {
      MPI_Init(&argc, &argv);
      MPI_Finalize();
      return 0;
    }
  " MPI_COMPILER_WORKS)

  if (MPI_COMPILER_WORKS)
    message(STATUS "MPI is supported by the compiler wrappers (Cray-style).")
    add_library(MPI::MPI_CXX INTERFACE IMPORTED)
    # No extra flags or libraries needed as they are handled by the wrapper
  else()
    message(STATUS "MPI not supported by compiler wrappers. Falling back to find_package(MPI).")
    find_package(MPI REQUIRED)
  endif()

  set(CMAKE_REQUIRED_FLAGS ${CMAKE_REQUIRED_FLAGS_SAVE})
  set(CMAKE_REQUIRED_LIBRARIES ${CMAKE_REQUIRED_LIBRARIES_SAVE})
endif()
