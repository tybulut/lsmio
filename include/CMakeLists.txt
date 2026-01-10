# Print debug
message(STATUS "Include module: CMAKE_CURRENT_SOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}")

# Headers
set(LSMIO_INCLUDE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
set(LSMIO_INCLUDE_DIR "${CMAKE_CURRENT_SOURCE_DIR}" PARENT_SCOPE)

message(STATUS "Include module: LSMIO_INCLUDE_DIR=${LSMIO_INCLUDE_DIR}")

# Include files
set(INC_BASE_HPP_FILES
  ${LSMIO_INCLUDE_DIR}/lsmio/lsmio.hpp
  ${LSMIO_INCLUDE_DIR}/lsmio/benchmark.hpp
  PARENT_SCOPE
)

set(INC_STORE_HPP_FILES
  ${LSMIO_INCLUDE_DIR}/lsmio/manager/manager.hpp
  ${LSMIO_INCLUDE_DIR}/lsmio/manager/store/store.hpp
  ${LSMIO_INCLUDE_DIR}/lsmio/manager/store/store_ldb.hpp
  ${LSMIO_INCLUDE_DIR}/lsmio/manager/store/store_rdb.hpp
  ${LSMIO_INCLUDE_DIR}/lsmio/manager/store/native/store_native.hpp
  ${LSMIO_INCLUDE_DIR}/lsmio/manager/store/native/memtable.hpp
  ${LSMIO_INCLUDE_DIR}/lsmio/manager/store/native/sstable_manager.hpp
  ${LSMIO_INCLUDE_DIR}/lsmio/manager/client/client.hpp
  ${LSMIO_INCLUDE_DIR}/lsmio/manager/client/client_mpi.hpp
  ${LSMIO_INCLUDE_DIR}/lsmio/manager/client/client_adios.hpp
  PARENT_SCOPE
)

set(INC_POSIX_HPP_FILES
  ${LSMIO_INCLUDE_DIR}/lsmio/posix/posix.hpp
  PARENT_SCOPE
)

