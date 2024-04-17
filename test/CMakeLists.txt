# Print debug
message(STATUS "Test module: LSMIO_INCLUDE_DIR=${LSMIO_INCLUDE_DIR}")
message(STATUS "Test module: CMAKE_BINARY_DIR=${CMAKE_BINARY_DIR}")
message(STATUS "Test module: Checking CMAKE_BUILD_PARALLEL_LEVEL: ${CMAKE_BUILD_PARALLEL_LEVEL}")

# Find packages
find_package(MPI REQUIRED)
find_package(ADIOS2 REQUIRED)
find_package(glog REQUIRED)
find_package(GTest REQUIRED)

list(INSERT CMAKE_MODULE_PATH 0 "${PROJECT_SOURCE_DIR}/cmake/upstream")
include(GoogleTest)

# MPI settings
set (mpi_processes 4)
find_program (mpi_cmd mpirun)

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

# GTest: Benchmark
add_executable(test_benchmark test_benchmark.cpp)
target_include_directories(test_benchmark PRIVATE ${LSMIO_INCLUDE_DIR})
target_link_libraries(test_benchmark PUBLIC GTest::GTest GTest::Main PRIVATE lsmio::base)
gtest_add_tests(TARGET test_benchmark)

# GTest: Manager, LevelDB and RocksDB
add_executable(test_manager
  test_leveldb.cpp
  test_rocksdb.cpp
  test_manager.cpp
  test_posix.cpp
)
target_include_directories(test_manager PRIVATE ${LSMIO_INCLUDE_DIR})
target_link_libraries(test_manager
  PUBLIC GTest::GTest GTest::Main
  PRIVATE lsmio::store
  PRIVATE lsmio::posix
)
gtest_add_tests(TARGET test_manager)

# GTest: MPI: Base and Manager
add_executable(test_mpi
  test_mpi_base.cpp
  test_mpi_manager.cpp
  test_mpi_utils.cpp
)
target_include_directories(test_mpi PRIVATE ${LSMIO_INCLUDE_DIR})
target_link_libraries(test_mpi
  PUBLIC GTest::GTest GTest::Main adios2::cxx11_mpi MPI::MPI_CXX
  PRIVATE lsmio_base
  PRIVATE lsmio_store
)
gtest_discover_tests(
  test_mpi
  CMD_WRAPPER ${mpi_cmd} ${test_parameters}
)

# GTest: Adios and Plugin
add_executable(test_adios test_adios.cpp test_plugin.cpp)
target_include_directories(test_adios PRIVATE ${LSMIO_INCLUDE_DIR})
target_link_libraries(test_adios
  PUBLIC GTest::GTest GTest::Main adios2::cxx11 adios2::core
  PRIVATE lsmio_base
)
gtest_add_tests(TARGET test_adios)
set_tests_properties(${all_tests} PROPERTIES
  ENVIRONMENT ADIOS2_PLUGIN_PATH=${CMAKE_BINARY_DIR}/lib
)

# GTest: MPI: Adios and Plugin
add_executable(test_mpi_adios test_mpi_adios.cpp test_mpi_utils.cpp)
target_include_directories(test_mpi_adios PRIVATE ${LSMIO_INCLUDE_DIR})
target_link_libraries(test_mpi_adios
  PUBLIC GTest::GTest GTest::Main adios2::cxx11_mpi MPI::MPI_CXX
  PRIVATE lsmio_base
)
gtest_discover_tests(
  test_mpi_adios
  CMD_WRAPPER ${mpi_cmd} ${test_parameters}
)
set_tests_properties(${all_tests} PROPERTIES
  ENVIRONMENT ADIOS2_PLUGIN_PATH=${CMAKE_BINARY_DIR}/lib
)

