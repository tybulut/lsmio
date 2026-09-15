# Print debug
message(STATUS "Lib module: LSMIO_SOURCE_DIR=${LSMIO_SOURCE_DIR}")
message(STATUS "Lib module: LSMIO_INCLUDE_DIR=${LSMIO_INCLUDE_DIR}")

# Packages
include(PackageMPI)
find_package(Threads REQUIRED)
# continues
include(PackageAdios)
include(PackageFMT)
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
  ${LIB_SOURCE_DIR}/manager/manager.cpp
  ${LIB_SOURCE_DIR}/manager/client/client.cpp
  ${LIB_SOURCE_DIR}/manager/client/client_mpi.cpp
  ${LIB_SOURCE_DIR}/manager/client/client_adios.cpp
  ${LIB_SOURCE_DIR}/manager/store/store.cpp
  ${LIB_SOURCE_DIR}/manager/store/store_ldb.cpp
  ${LIB_SOURCE_DIR}/manager/store/store_rdb.cpp
  ${LIB_SOURCE_DIR}/manager/store/native/StoreNative.cpp
  ${LIB_SOURCE_DIR}/manager/store/native/MemtableVectorNoSort.cpp
  ${LIB_SOURCE_DIR}/manager/store/native/MemtableVectorSort.cpp
  ${LIB_SOURCE_DIR}/manager/store/native/SSTableManager.cpp
  ${LIB_SOURCE_DIR}/manager/store/native/FilePool.cpp
  ${LIB_SOURCE_DIR}/manager/store/native/FileCloser.cpp
)
set(LIB_ADIOS_CPP_FILES
  ${LIB_SOURCE_DIR}/adios-plugin/lsmio_plugin.cpp
)
set(LIB_POSIX_CPP_FILES
  ${LIB_SOURCE_DIR}/posix/posix.cpp
)
set(LIB_BASE_SOURCE_FILES ${LIB_BASE_HPP_FILES} ${LIB_BASE_CPP_FILES})
set(LIB_STORE_SOURCE_FILES ${LIB_STORE_HPP_FILES} ${LIB_STORE_CPP_FILES})
set(LIB_ADIOS_SOURCE_FILES ${LIB_ADIOS_HPP_FILES} ${LIB_ADIOS_CPP_FILES})
set(LIB_POSIX_SOURCE_FILES ${LIB_POSIX_HPP_FILES} ${LIB_POSIX_CPP_FILES})

macro(lsmio_add_props MY_TARGET)
  set_property(TARGET ${MY_TARGET} PROPERTY POSITION_INDEPENDENT_CODE ON)
  target_include_directories(${MY_TARGET} PRIVATE ${LSMIO_INCLUDE_DIR})
  target_compile_definitions(${MY_TARGET} PRIVATE LSMIO_VERSION="${PROJECT_VERSION}")
  if(LSMIO_ENABLE_COVERAGE)
    if(CMAKE_CXX_COMPILER_ID MATCHES "Clang")
      target_compile_options(${MY_TARGET} PRIVATE -fprofile-instr-generate -fcoverage-mapping)
      target_link_libraries(${MY_TARGET} PUBLIC -fprofile-instr-generate)
    else()
      target_compile_options(${MY_TARGET} PRIVATE -fprofile-arcs -ftest-coverage)
      target_link_libraries(${MY_TARGET} PUBLIC --coverage)
    endif()
  endif()
endmacro()


function(add_lsmio_dual_library NAME)
  cmake_parse_arguments(ARG "" "" "SOURCES;INTERNAL_DEPS;PUBLIC_LIBS" ${ARGN})

  # Shared library
  add_library(lsmio_${NAME} ${ARG_SOURCES})
  add_library(lsmio::${NAME} ALIAS lsmio_${NAME})
  target_link_libraries(lsmio_${NAME} PUBLIC ${ARG_PUBLIC_LIBS})
  foreach(dep ${ARG_INTERNAL_DEPS})
    target_link_libraries(lsmio_${NAME} PUBLIC lsmio_${dep})
  endforeach()
  lsmio_add_props(lsmio_${NAME})

  # Static library
  add_library(lsmio_${NAME}_static STATIC ${ARG_SOURCES})
  add_library(lsmio::${NAME}_static ALIAS lsmio_${NAME}_static)
  target_link_libraries(lsmio_${NAME}_static PUBLIC ${ARG_PUBLIC_LIBS})
  foreach(dep ${ARG_INTERNAL_DEPS})
    target_link_libraries(lsmio_${NAME}_static PUBLIC lsmio_${dep}_static)
  endforeach()
  lsmio_add_props(lsmio_${NAME}_static)
endfunction()


# Add library: BASE (Shared and Static)
add_lsmio_dual_library(base
  SOURCES ${LIB_BASE_SOURCE_FILES}
  PUBLIC_LIBS fmt::fmt glog::glog
)

# Add library: STORE (Shared and Static)
add_lsmio_dual_library(store
  SOURCES ${LIB_STORE_SOURCE_FILES}
  INTERNAL_DEPS base
  PUBLIC_LIBS fmt::fmt glog::glog
    Snappy::snappy leveldb::leveldb RocksDB::rocksdb-shared
    MPI::MPI_CXX Threads::Threads
    adios2::cxx_mpi adios2::core_mpi
    tlx
)

# Add library and binary: ADIOS
add_library(lsmio_adios ${LIB_ADIOS_SOURCE_FILES})
add_library(lsmio::adios ALIAS lsmio_adios)
target_link_libraries(lsmio_adios
  PUBLIC fmt::fmt glog::glog lsmio_store
    Snappy::snappy leveldb::leveldb RocksDB::rocksdb-shared
    MPI::MPI_CXX Threads::Threads
    adios2::cxx_mpi adios2::core_mpi
)
lsmio_add_props(lsmio_adios)

# Add library: POSIX (Shared and Static)
add_lsmio_dual_library(posix
  SOURCES ${LIB_POSIX_SOURCE_FILES}
  INTERNAL_DEPS store
  PUBLIC_LIBS fmt::fmt glog::glog
    Snappy::snappy leveldb::leveldb RocksDB::rocksdb-shared
    MPI::MPI_CXX Threads::Threads
    adios2::cxx_mpi adios2::core_mpi
)

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

