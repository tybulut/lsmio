# Print debug
message(STATUS "Test module: LSMIO_INCLUDE_DIR=${LSMIO_INCLUDE_DIR}")
message(STATUS "Test module: CMAKE_BINARY_DIR=${CMAKE_BINARY_DIR}")
message(STATUS "Test module: Checking CMAKE_BUILD_PARALLEL_LEVEL: ${CMAKE_BUILD_PARALLEL_LEVEL}")

# Find packages
find_package(MPI REQUIRED)
find_package(HDF5 REQUIRED)
# continues
include(PackageAdios)
include(PackageGoogleLog)
include(PackageGoogleTest)

# MPI settings
set (mpi_processes 2)
find_program (mpi_cmd mpirun)

if(NOT mpi_cmd)
  find_program (mpi_cmd aprun)
endif()

if(NOT mpi_cmd)
  message(FATAL_ERROR "MPI command not found!")
else()
  message(STATUS "Test module: MPI command found=${mpi_cmd}")

  if(mpi_cmd MATCHES "aprun")
    set (test_parameters -n ${mpi_processes})
  else()
    set (test_parameters -tag-output -np ${mpi_processes})
  endif()
endif()

# Disable RTTI
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -fno-rtti")

include(CMakeParseArguments)

function(add_lsmio_base_test x)
  message("Adding LSMIO base testing for ${x}.cpp")
  add_executable(${x} "${x}.cpp")
  target_include_directories(${x} PRIVATE ${LSMIO_INCLUDE_DIR})
  target_link_libraries(${x}
    PUBLIC GTest::GTest GTest::Main
    PRIVATE lsmio::base
  )
  gtest_add_tests(TARGET ${x})
endfunction()

function(add_lsmio_store_test x)
  message("Adding LSMIO store testing for ${x}.cpp")
  add_executable(${x} "${x}.cpp")
  target_include_directories(${x} PRIVATE ${LSMIO_INCLUDE_DIR})
  target_link_libraries(${x}
    PUBLIC GTest::GTest GTest::Main
    PRIVATE lsmio::store
    PRIVATE lsmio::posix
  )
  gtest_add_tests(TARGET ${x})
endfunction()

function(add_lsmio_mpi_test x)
  message("Adding LSMIO MPI testing for ${x}.cpp")
  add_executable(${x}
    "${x}.cpp"
    test_mpi_utils.cpp
  )
  target_include_directories(${x} PRIVATE ${LSMIO_INCLUDE_DIR})
  target_link_libraries(${x}
    PUBLIC GTest::GTest GTest::Main adios2::cxx11_mpi MPI::MPI_CXX
    PRIVATE lsmio_base
    PRIVATE lsmio::store
  )
  gtest_discover_tests(
    ${x}
    CMD_WRAPPER ${mpi_cmd} ${test_parameters}
  )
endfunction()

# GTest: Benchmark
add_lsmio_base_test(test_benchmark)

# GTest: Manager, LevelDB and RocksDB
add_lsmio_store_test(test_leveldb)
add_lsmio_store_test(test_rocksdb)
add_lsmio_store_test(test_manager)
add_lsmio_store_test(test_posix)

# GTest: MPI: Base and Manager
add_lsmio_mpi_test(test_mpi_base)
add_lsmio_mpi_test(test_mpi_manager)

# GTest: Adios and Plugin
add_executable(test_adios test_adios.cpp test_plugin.cpp)
target_include_directories(test_adios PRIVATE ${LSMIO_INCLUDE_DIR})
target_link_libraries(test_adios
  PUBLIC GTest::GTest GTest::Main adios2::cxx11 adios2::core
  PRIVATE lsmio_base
)
gtest_discover_tests(
  test_adios
  PROPERTIES ENVIRONMENT ADIOS2_PLUGIN_PATH=${CMAKE_BINARY_DIR}/lib
)

# GTest: MPI: Adios and Plugin
add_executable(test_mpi_adios test_mpi_adios.cpp test_mpi_utils.cpp)
target_include_directories(test_mpi_adios PRIVATE ${LSMIO_INCLUDE_DIR})
target_link_libraries(test_mpi_adios
  PUBLIC GTest::GTest GTest::Main adios2::cxx11_mpi MPI::MPI_CXX
  PUBLIC HDF5::HDF5
  PRIVATE lsmio_base
)
gtest_discover_tests(
  test_mpi_adios
  CMD_WRAPPER ${mpi_cmd} ${test_parameters}
  PROPERTIES ENVIRONMENT ADIOS2_PLUGIN_PATH=${CMAKE_BINARY_DIR}/lib
)

# GTest: MPI: Adios and Plugin
add_executable(test_mpi_hdf5 test_mpi_hdf5.cpp test_mpi_utils.cpp)
target_include_directories(test_mpi_hdf5 PRIVATE ${LSMIO_INCLUDE_DIR})
target_link_libraries(test_mpi_hdf5
  PUBLIC GTest::GTest GTest::Main adios2::cxx11_mpi MPI::MPI_CXX
  PUBLIC HDF5::HDF5
  PRIVATE lsmio_base
)
gtest_discover_tests(
  test_mpi_hdf5
  CMD_WRAPPER ${mpi_cmd} ${test_parameters}
  PROPERTIES ENVIRONMENT ADIOS2_PLUGIN_PATH=${CMAKE_BINARY_DIR}/lib
)
