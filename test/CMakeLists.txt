# Print debug
message(STATUS "Test module: LSMIO_INCLUDE_DIR=${LSMIO_INCLUDE_DIR}")
message(STATUS "Test module: CMAKE_BINARY_DIR=${CMAKE_BINARY_DIR}")
message(STATUS "Test module: Checking CMAKE_BUILD_PARALLEL_LEVEL: ${CMAKE_BUILD_PARALLEL_LEVEL}")

# Find packages
include(PackageMPI)
# continues
include(PackageAdios)
include(PackageGoogleLog)
include(PackageGoogleTest)

# MPI settings
set (mpi_processes 2)
# Prefer mpirun; fall back through aprun/likwid-mpirun to srun (the launcher on
# Cray systems such as ARCHER2). find_program keeps the first name it resolves.
find_program (mpi_cmd NAMES mpirun aprun likwid-mpirun srun)

if(NOT mpi_cmd)
  message(FATAL_ERROR "MPI command (mpirun, aprun, likwid-mpirun, srun) not found!")
else()
  message(STATUS "Test module: MPI command found=${mpi_cmd}")

  # -tag-output is OpenMPI-specific; only pass it to (OpenMPI/MPICH) mpirun.
  if(mpi_cmd MATCHES "aprun" OR mpi_cmd MATCHES "srun")
    set (test_parameters -n ${mpi_processes})
  elseif(mpi_cmd MATCHES "likwid-mpirun")
    set (test_parameters -np ${mpi_processes})
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

  gtest_add_tests(TARGET ${x} TEST_LIST tests)
  set_tests_properties(${tests} PROPERTIES
    TIMEOUT 30
    ENVIRONMENT "LD_LIBRARY_PATH=${CMAKE_BINARY_DIR}/lib:$ENV{LD_LIBRARY_PATH}"
  )
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

  gtest_add_tests(TARGET ${x} TEST_LIST tests)
  set_tests_properties(${tests} PROPERTIES
    TIMEOUT 30
    ENVIRONMENT "LD_LIBRARY_PATH=${CMAKE_BINARY_DIR}/lib:$ENV{LD_LIBRARY_PATH}"
  )
endfunction()

function(add_lsmio_mpi_test x)
  message("Adding LSMIO MPI testing for ${x}.cpp")

  add_executable(${x}
    "${x}.cpp"
    test_mpi_utils.cpp
  )
  target_include_directories(${x} PRIVATE ${LSMIO_INCLUDE_DIR})
  target_link_libraries(${x}
    PUBLIC GTest::GTest GTest::Main adios2::cxx_mpi MPI::MPI_CXX
    PRIVATE lsmio_base
    PRIVATE lsmio::store
  )

  gtest_discover_tests(
    ${x}
    CMD_WRAPPER ${mpi_cmd} ${test_parameters}
    PROPERTIES
      TIMEOUT 30
      ENVIRONMENT "LD_LIBRARY_PATH=${CMAKE_BINARY_DIR}/lib:$ENV{LD_LIBRARY_PATH}"
  )
endfunction()

# GTest: Benchmark
add_lsmio_base_test(test_benchmark)

# GTest: Manager, LevelDB and RocksDB
add_lsmio_store_test(test_leveldb)
add_lsmio_store_test(test_rocksdb)
add_lsmio_store_test(test_native)
add_lsmio_store_test(test_native_extended)
add_lsmio_store_test(test_memtable)
add_lsmio_store_test(test_sstable_manager)
add_lsmio_store_test(test_file_pool)
add_lsmio_store_test(test_file_closer)
add_lsmio_store_test(test_manager)
add_lsmio_store_test(test_posix)

# GTest: MPI: Base and Manager
add_lsmio_mpi_test(test_mpi_base)
add_lsmio_mpi_test(test_mpi_manager)

# GTest: Adios and Plugin
add_executable(test_adios test_adios.cpp test_plugin.cpp)
target_include_directories(test_adios PRIVATE ${LSMIO_INCLUDE_DIR})
target_link_libraries(test_adios
  PUBLIC GTest::GTest GTest::Main adios2::cxx adios2::core
  PRIVATE lsmio_base
)
gtest_discover_tests(
  test_adios
  PROPERTIES
    TIMEOUT 30
    ENVIRONMENT "ADIOS2_PLUGIN_PATH=${CMAKE_BINARY_DIR}/lib;LD_LIBRARY_PATH=${CMAKE_BINARY_DIR}/lib:$ENV{LD_LIBRARY_PATH}"
)

# GTest: MPI: Adios and Plugin
add_executable(test_mpi_adios test_mpi_adios.cpp test_mpi_utils.cpp)
target_include_directories(test_mpi_adios PRIVATE ${LSMIO_INCLUDE_DIR})
target_link_libraries(test_mpi_adios
  PUBLIC GTest::GTest GTest::Main adios2::cxx_mpi MPI::MPI_CXX
  PRIVATE lsmio_base
)
gtest_discover_tests(
  test_mpi_adios
  CMD_WRAPPER ${mpi_cmd} ${test_parameters}
  PROPERTIES
    ENVIRONMENT "ADIOS2_PLUGIN_PATH=${CMAKE_BINARY_DIR}/lib;LD_LIBRARY_PATH=${CMAKE_BINARY_DIR}/lib:$ENV{LD_LIBRARY_PATH}"
    TIMEOUT 30
)

if(LSMIO_ENABLE_COVERAGE)
  file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/CTestTestfile.baseline.cmake"
    "add_test(lsmiotool_python_suite \"${Python3_EXECUTABLE}\" \"${LSMIO_SOURCE_DIR}/tools/lsmiotool/lsmiotool\" \"test\")\n"
  )

  add_test(
    NAME lsmiotool_python_suite
    COMMAND ${CMAKE_COMMAND}
            -Dmode=run
            -Dpython=${Python3_EXECUTABLE}
            -Ddata=${CMAKE_BINARY_DIR}/.coverage.lsmiotool
            -Djson=${CMAKE_BINARY_DIR}/lsmiotool-python-coverage.json
            -Dmarker=${CMAKE_BINARY_DIR}/.coverage.lsmiotool.sha256
            -Dsource=${LSMIO_SOURCE_DIR}/tools/lsmiotool
            -Dentry=${LSMIO_SOURCE_DIR}/tools/lsmiotool/lsmiotool
            -P ${CMAKE_SOURCE_DIR}/cmake/LsmiotoolPythonCoverage.cmake
  )
  set_tests_properties(lsmiotool_python_suite PROPERTIES
    TIMEOUT 120
    ENVIRONMENT
      "PYTHONPATH=${LSMIO_SOURCE_DIR}/tools:$ENV{PYTHONPATH};LSMIO_ENV=DEV;MPLBACKEND=Agg;MPLCONFIGDIR=${CMAKE_BINARY_DIR}/matplotlib;LSMIO_CTEST_REGISTRATION=${CMAKE_CURRENT_BINARY_DIR}/CTestTestfile.baseline.cmake;LSMIO_CTEST_PYTHON=${Python3_EXECUTABLE};LSMIO_CTEST_ENTRY=${LSMIO_SOURCE_DIR}/tools/lsmiotool/lsmiotool;LSMIO_ENABLE_COVERAGE=ON"
  )

  add_custom_target(
    lsmiotool_python_coverage_report
    COMMAND ${CMAKE_COMMAND}
            -Dmode=report
            -Dpython=${Python3_EXECUTABLE}
            -Ddata=${CMAKE_BINARY_DIR}/.coverage.lsmiotool
            -Djson=${CMAKE_BINARY_DIR}/lsmiotool-python-coverage.json
            -Dmarker=${CMAKE_BINARY_DIR}/.coverage.lsmiotool.sha256
            -P ${CMAKE_SOURCE_DIR}/cmake/LsmiotoolPythonCoverage.cmake
    COMMENT "Generating lsmiotool Python coverage report"
    VERBATIM
  )
else()
  file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/CTestTestfile.baseline.cmake"
    "add_test(lsmiotool_python_suite \"${Python3_EXECUTABLE}\" \"${LSMIO_SOURCE_DIR}/tools/lsmiotool/lsmiotool\" \"test\")\n"
  )

  file(GLOB_RECURSE _lsmiotool_test_files
    CONFIGURE_DEPENDS
    "${LSMIO_SOURCE_DIR}/tools/lsmiotool/test/*Test.py"
    "${LSMIO_SOURCE_DIR}/tools/lsmiotool/test/test_*.py"
    "${LSMIO_SOURCE_DIR}/tools/lsmiotool/test/Test*.py"
  )

  execute_process(
    COMMAND ${Python3_EXECUTABLE} -c
      "import sys; sys.path.insert(0, '${LSMIO_SOURCE_DIR}/tools'); from lsmiotool.test import _discoverTestModuleNames; print(';'.join(_discoverTestModuleNames()))"
    OUTPUT_VARIABLE LSMIOTOOL_TEST_MODULES
    OUTPUT_STRIP_TRAILING_WHITESPACE
    RESULT_VARIABLE _discovery_result
  )

  if(_discovery_result EQUAL 0 AND LSMIOTOOL_TEST_MODULES)
    foreach(_mod ${LSMIOTOOL_TEST_MODULES})
      string(REPLACE "lsmiotool.test." "lsmiotool." _test_name "${_mod}")
      add_test(
        NAME "${_test_name}"
        COMMAND Python3::Interpreter
                "${LSMIO_SOURCE_DIR}/tools/lsmiotool/lsmiotool"
                test
                "${_mod}"
      )
      set_tests_properties("${_test_name}" PROPERTIES
        TIMEOUT 60
        ENVIRONMENT
          "PYTHONPATH=${LSMIO_SOURCE_DIR}/tools:$ENV{PYTHONPATH};LSMIO_ENV=DEV;MPLBACKEND=Agg;MPLCONFIGDIR=${CMAKE_BINARY_DIR}/matplotlib;LSMIO_CTEST_REGISTRATION=${CMAKE_CURRENT_BINARY_DIR}/CTestTestfile.baseline.cmake;LSMIO_CTEST_PYTHON=${Python3_EXECUTABLE};LSMIO_CTEST_ENTRY=${LSMIO_SOURCE_DIR}/tools/lsmiotool/lsmiotool"
      )
    endforeach()
  else()
    add_test(
      NAME lsmiotool_python_suite
      COMMAND Python3::Interpreter
              "${LSMIO_SOURCE_DIR}/tools/lsmiotool/lsmiotool"
              test
    )
    set_tests_properties(lsmiotool_python_suite PROPERTIES
      TIMEOUT 120
      ENVIRONMENT
        "PYTHONPATH=${LSMIO_SOURCE_DIR}/tools:$ENV{PYTHONPATH};LSMIO_ENV=DEV;MPLBACKEND=Agg;MPLCONFIGDIR=${CMAKE_BINARY_DIR}/matplotlib;LSMIO_CTEST_REGISTRATION=${CMAKE_CURRENT_BINARY_DIR}/CTestTestfile.baseline.cmake;LSMIO_CTEST_PYTHON=${Python3_EXECUTABLE};LSMIO_CTEST_ENTRY=${LSMIO_SOURCE_DIR}/tools/lsmiotool/lsmiotool"
      )
  endif()
endif()

add_test(
  NAME lsmiotool_stage_install
  COMMAND ${CMAKE_COMMAND}
          -Dbuild_dir=${CMAKE_BINARY_DIR}
          -Dstage_dir=${CMAKE_BINARY_DIR}/lsmiotool-stage
          -P ${CMAKE_SOURCE_DIR}/cmake/StageLsmiotoolTest.cmake
)
set_tests_properties(lsmiotool_stage_install PROPERTIES
  FIXTURES_SETUP lsmiotool_staged_install
)

add_test(
  NAME lsmiotool_installed_smoke
  COMMAND ${Python3_EXECUTABLE}
          ${CMAKE_SOURCE_DIR}/tools/lsmiotool/ctest/installed_smoke.py
          --stage ${CMAKE_BINARY_DIR}/lsmiotool-stage
          --work ${CMAKE_BINARY_DIR}/lsmiotool-smoke-cwd
)
set_tests_properties(lsmiotool_installed_smoke PROPERTIES
  FIXTURES_REQUIRED lsmiotool_staged_install
  WORKING_DIRECTORY ${CMAKE_BINARY_DIR}/lsmiotool-smoke-cwd
  ENVIRONMENT "HOME=${CMAKE_BINARY_DIR}/lsmiotool-smoke-home"
)

