# Print debug
message(STATUS "Benchmark module: LSMIO_INCLUDE_DIR=${LSMIO_INCLUDE_DIR}")
message(STATUS "Benchmark module: CMAKE_BINARY_DIR=${CMAKE_BINARY_DIR}")

# Find packages
find_package(MPI REQUIRED)
find_package(ADIOS2 REQUIRED)
find_package(glog REQUIRED)
find_package(fmt REQUIRED)
find_package(Boost COMPONENTS program_options REQUIRED)

set(BASE_SOURCE_FILES
  bm_base.cpp
  bm_base.hpp
)

# Set up such that XCode organizes the files correctly
source_group(TREE ${CMAKE_CURRENT_SOURCE_DIR} FILES
  ${BASE_SOURCE_FILES}
)

# Benchmark: LevelDB
add_executable(bm_leveldb ${BASE_SOURCE_FILES} bm_leveldb.cpp)
#set_target_properties(bm_leveldb PROPERTIES LINK_FLAGS "-static")
target_include_directories(bm_leveldb PRIVATE ${LSMIO_INCLUDE_DIR})
target_link_libraries(bm_leveldb
  PRIVATE lsmio::store
  PUBLIC fmt Boost::program_options MPI::MPI_CXX)
install(TARGETS bm_leveldb DESTINATION bin)

# Benchmark: RocksDB
add_executable(bm_rocksdb ${BASE_SOURCE_FILES} bm_rocksdb.cpp)
target_include_directories(bm_rocksdb PRIVATE ${LSMIO_INCLUDE_DIR})
target_link_libraries(bm_rocksdb
  PRIVATE lsmio::store
  PUBLIC fmt Boost::program_options MPI::MPI_CXX)
install(TARGETS bm_rocksdb DESTINATION bin)

# Benchmark: Manager
add_executable(bm_manager ${BASE_SOURCE_FILES} bm_manager.cpp)
target_include_directories(bm_manager PRIVATE ${LSMIO_INCLUDE_DIR})
target_link_libraries(bm_manager
  PRIVATE lsmio::store
  PUBLIC fmt Boost::program_options MPI::MPI_CXX)
install(TARGETS bm_manager DESTINATION bin)

# Benchmark: Plugin
add_executable(bm_adios ${BASE_SOURCE_FILES} bm_adios.cpp)
target_include_directories(bm_adios PRIVATE ${LSMIO_INCLUDE_DIR})
target_link_libraries(bm_adios
  PRIVATE lsmio_base
  PUBLIC glog::glog adios2::cxx11 adios2::cxx11_mpi fmt Boost::program_options MPI::MPI_CXX
)
install(TARGETS bm_adios DESTINATION bin)
set_property(TARGET bm_adios
  PROPERTY ENVIRONMENT “ADIOS2_PLUGIN_PATH=${CMAKE_BINARY_DIR}/lib”
)


