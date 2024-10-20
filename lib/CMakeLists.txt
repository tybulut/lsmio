# Print debug
message(STATUS "Lib module: LSMIO_SOURCE_DIR=${LSMIO_SOURCE_DIR}")
message(STATUS "Lib module: LSMIO_INCLUDE_DIR=${LSMIO_INCLUDE_DIR}")

# Packages
find_package(MPI REQUIRED)
include_directories(${MPI_INCLUDE_DIR})
find_package(Threads REQUIRED)
# continues
include(PackageAdios)
include(PackageGoogleLog)
include(PackageLevelDB)
include(PackageRocksDB)

# Headers
set(LIB_SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")

# Include files
set(INC_ADIOS_HPP_FILES
  ${LIB_SOURCE_DIR}/adios-plugin/lsmio_plugin.hpp
  ${LIB_SOURCE_DIR}/adios-plugin/lsmio_plugin.tcc
)
# Source files
set(LIB_BASE_HPP_FILES
  ${INC_BASE_HPP_FILES}
)
set(LIB_STORE_HPP_FILES
  ${INC_BASE_HPP_FILES}
  ${INC_STORE_HPP_FILES}
)
set(LIB_ADIOS_HPP_FILES
  ${INC_BASE_HPP_FILES}
  ${INC_STORE_HPP_FILES}
  ${INC_ADIOS_HPP_FILES}
)
set(LIB_POSIX_HPP_FILES
  ${INC_BASE_HPP_FILES}
  ${INC_STORE_HPP_FILES}
  ${INC_POSIX_HPP_FILES}
)
set(LIB_BASE_CPP_FILES
  ${LIB_SOURCE_DIR}/lsmio.cpp
  ${LIB_SOURCE_DIR}/benchmark.cpp
)
set(LIB_STORE_CPP_FILES
  ${LIB_BASE_CPP_FILES}
  ${LIB_SOURCE_DIR}/manager/manager.cpp
  ${LIB_SOURCE_DIR}/manager/client/client.cpp
  ${LIB_SOURCE_DIR}/manager/client/client_mpi.cpp
  ${LIB_SOURCE_DIR}/manager/client/client_adios.cpp
  ${LIB_SOURCE_DIR}/manager/store/store.cpp
  ${LIB_SOURCE_DIR}/manager/store/store_ldb.cpp
  ${LIB_SOURCE_DIR}/manager/store/store_rdb.cpp
)
set(LIB_ADIOS_CPP_FILES
  ${LIB_STORE_CPP_FILES}
  ${LIB_SOURCE_DIR}/adios-plugin/lsmio_plugin.cpp
)
set(LIB_POSIX_CPP_FILES
  ${LIB_SOURCE_DIR}/posix/posix.cpp
)
set(LIB_BASE_SOURCE_FILES ${LIB_BASE_HPP_FILES} ${LIB_BASE_CPP_FILES})
set(LIB_STORE_SOURCE_FILES ${LIB_STORE_HPP_FILES} ${LIB_STORE_CPP_FILES})
set(LIB_ADIOS_SOURCE_FILES ${LIB_ADIOS_HPP_FILES} ${LIB_ADIOS_CPP_FILES})
set(LIB_POSIX_SOURCE_FILES ${LIB_POSIX_HPP_FILES} ${LIB_POSIX_CPP_FILES})

# Add library and binary: BASE
add_library(lsmio_base ${LIB_BASE_SOURCE_FILES})
#set_property(TARGET lsmio PROPERTY POSITION_INDEPENDENT_CODE ON)
add_library(lsmio::base ALIAS lsmio_base)
target_include_directories(lsmio_base PRIVATE ${LSMIO_INCLUDE_DIR})
target_link_libraries(lsmio_base PUBLIC
  fmt glog::glog
)
target_compile_definitions(lsmio_base PRIVATE LSMIO_VERSION=0.1.0)

# Add library and binary: STORE
add_library(lsmio_store ${LIB_STORE_SOURCE_FILES})
add_library(lsmio::store ALIAS lsmio_store)
target_include_directories(lsmio_store PRIVATE ${LSMIO_INCLUDE_DIR})
target_link_libraries(lsmio_store PUBLIC
  fmt glog::glog
  leveldb rocksdb
  MPI::MPI_CXX Threads::Threads
  adios2::cxx11_mpi adios2::core_mpi
)
target_compile_definitions(lsmio_store PRIVATE LSMIO_VERSION=0.1.0)

# Add library and binary: ADIOS
add_library(lsmio_adios ${LIB_ADIOS_SOURCE_FILES})
add_library(lsmio::adios ALIAS lsmio_adios)
target_include_directories(lsmio_adios PRIVATE ${LSMIO_INCLUDE_DIR})
target_link_libraries(lsmio_adios PUBLIC
  fmt glog::glog
  leveldb rocksdb
  MPI::MPI_CXX Threads::Threads
  adios2::cxx11_mpi adios2::core_mpi
)
target_compile_definitions(lsmio_adios PRIVATE LSMIO_VERSION=0.1.0)

# Add library and binary: POSIX
add_library(lsmio_posix ${LIB_POSIX_SOURCE_FILES})
add_library(lsmio::posix ALIAS lsmio_posix)
target_include_directories(lsmio_posix PRIVATE ${LSMIO_INCLUDE_DIR})
target_link_libraries(lsmio_posix PUBLIC
  fmt glog::glog
  leveldb rocksdb
  lsmio_store
  MPI::MPI_CXX Threads::Threads
  adios2::cxx11_mpi adios2::core_mpi
)
target_compile_definitions(lsmio_posix PRIVATE LSMIO_VERSION=0.1.0)

# Install: BASE
install(TARGETS lsmio_base
  EXPORT lsmio-base-targets
  COMPONENT ${PROJECT_NAME}
  INCLUDES DESTINATION include
)
install(FILES
  ${INC_BASE_HPP_FILES}
  DESTINATION include/lsmio
  COMPONENT ${PROJECT_NAME}_dev
)

# Install: STORE
install(TARGETS lsmio_store
  EXPORT lsmio-store-targets
  COMPONENT ${PROJECT_NAME}
  INCLUDES DESTINATION include
)
#install(FILES ${INC_STORE_HPP_FILES} DESTINATION include/lsmio/manager)
install(DIRECTORY
  ${LSMIO_INCLUDE_DIR}/lsmio/manager
  DESTINATION include/lsmio
  COMPONENT ${PROJECT_NAME}_dev
  FILES_MATCHING PATTERN "*.hpp"
)

# Install: ADIOS
install(TARGETS lsmio_adios
  DESTINATION lib
  COMPONENT ${PROJECT_NAME}
)

# Install: POSIX
install(TARGETS lsmio_posix
  EXPORT lsmio-posix-targets
  COMPONENT ${PROJECT_NAME}
  INCLUDES DESTINATION include
)
install(FILES
  ${INC_POSIX_HPP_FILES}
  DESTINATION include/lsmio/posix
  COMPONENT ${PROJECT_NAME}_dev
)

# CMake: BASE
install(EXPORT lsmio-base-targets
  FILE lsmio-base-targets.cmake
#    NAMESPACE lsmio::
  DESTINATION lib/cmake/lsmio
  COMPONENT ${PROJECT_NAME}_dev
)

# CMake: STORE
install(EXPORT lsmio-store-targets
  FILE lsmio-store-targets.cmake
#    NAMESPACE lsmio::
  DESTINATION lib/cmake/lsmio
  COMPONENT ${PROJECT_NAME}_dev
)

# CMake: POSIX
install(EXPORT lsmio-posix-targets
  FILE lsmio-posix-targets.cmake
#    NAMESPACE lsmio::
  DESTINATION lib/cmake/lsmio
  COMPONENT ${PROJECT_NAME}_dev
)

include(CMakePackageConfigHelpers)
write_basic_package_version_file(
  "lsmio-config-version.cmake"
  VERSION ${lsmio_VERSION}
  COMPATIBILITY AnyNewerVersion
)

install(FILES
  "${LSMIO_SOURCE_DIR}/cmake/lsmio-config.cmake"
  "${CMAKE_CURRENT_BINARY_DIR}/lsmio-config-version.cmake"
  DESTINATION lib/cmake/lsmio
  COMPONENT ${PROJECT_NAME}_dev
)

