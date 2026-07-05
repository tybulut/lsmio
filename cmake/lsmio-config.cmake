include(CMakeFindDependencyMacro)
#
include(${CMAKE_CURRENT_LIST_DIR}/lsmio-base-targets.cmake)
include(${CMAKE_CURRENT_LIST_DIR}/lsmio-store-targets.cmake)
include(${CMAKE_CURRENT_LIST_DIR}/lsmio-posix-targets.cmake)
#
find_dependency(Threads)
find_dependency(fmt)
find_dependency(glog)
find_dependency(cli11)
# Resolve MPI in this config's own scope so find_dependency's REQUIRED/QUIET
# propagation and its early-return-on-not-found behave correctly (a return()
# from an include()'d helper would not abort this config). Skip when the
# consumer already provides an MPI::MPI_CXX target, e.g. Cray compiler wrappers.
if(NOT TARGET MPI::MPI_CXX)
  find_dependency(MPI)
endif()
find_dependency(ADIOS2)
find_dependency(leveldb)
find_dependency(RocksDB)
