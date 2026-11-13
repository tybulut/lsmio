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
include(PackageCLI11)
include(PackageFMT)

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


include(CMakeParseArguments)

function(add_lsmio_base_test x)
  message("Adding LSMIO base testing for ${x}.cpp")

  add_executable(${x} "${x}.cpp")
  target_include_directories(${x} PRIVATE ${LSMIO_INCLUDE_DIR})
  target_link_libraries(${x}
    PUBLIC GTest::GTest GTest::Main
    PRIVATE lsmio::base_static
  )

  gtest_discover_tests(${x}
    NO_PRETTY_VALUES
    PROPERTIES
      TIMEOUT 30
      ENVIRONMENT "LD_LIBRARY_PATH=${CMAKE_BINARY_DIR}/lib:$ENV{LD_LIBRARY_PATH}"
    DISCOVERY_TIMEOUT 30
  )
endfunction()

function(add_lsmio_store_test x)
  message("Adding LSMIO store testing for ${x}.cpp")

  add_executable(${x} "${x}.cpp")
  target_include_directories(${x} PRIVATE ${LSMIO_INCLUDE_DIR})
  target_link_libraries(${x}
    PUBLIC GTest::GTest GTest::Main
    PRIVATE lsmio::store_static
  )

  gtest_discover_tests(${x}
    NO_PRETTY_VALUES
    PROPERTIES
      TIMEOUT 30
      ENVIRONMENT "LD_LIBRARY_PATH=${CMAKE_BINARY_DIR}/lib:$ENV{LD_LIBRARY_PATH}"
    DISCOVERY_TIMEOUT 30
  )
endfunction()

function(add_lsmio_posix_test x)
  message("Adding LSMIO POSIX testing for ${x}.cpp")

  add_executable(${x} "${x}.cpp")
  target_include_directories(${x} PRIVATE ${LSMIO_INCLUDE_DIR})
  target_link_libraries(${x}
    PUBLIC GTest::GTest GTest::Main
    PRIVATE lsmio::posix_static
  )

  gtest_discover_tests(${x}
    NO_PRETTY_VALUES
    PROPERTIES
      TIMEOUT 30
      ENVIRONMENT "LD_LIBRARY_PATH=${CMAKE_BINARY_DIR}/lib:$ENV{LD_LIBRARY_PATH}"
    DISCOVERY_TIMEOUT 30
  )
endfunction()

function(add_lsmio_mpi_test x lib)
  message("Adding LSMIO MPI testing for ${x}.cpp")

  add_executable(${x}
    "${x}.cpp"
    test_mpi_utils.cpp
  )
  target_include_directories(${x} PRIVATE ${LSMIO_INCLUDE_DIR})
  target_link_libraries(${x}
    PUBLIC GTest::GTest GTest::Main adios2::cxx_mpi MPI::MPI_CXX
    PRIVATE ${lib}
  )

  gtest_discover_tests(
    ${x}
    NO_PRETTY_VALUES
    CMD_WRAPPER ${mpi_cmd} ${test_parameters}
    PROPERTIES
      TIMEOUT 30
      # Each test runs ${mpi_processes} ranks: count them against ctest -j
      PROCESSORS ${mpi_processes}
      ENVIRONMENT "LD_LIBRARY_PATH=${CMAKE_BINARY_DIR}/lib:$ENV{LD_LIBRARY_PATH}"
    DISCOVERY_TIMEOUT 30
  )
endfunction()

# GTest: Benchmark
add_lsmio_base_test(test_benchmark)

# GTest: Version
add_lsmio_base_test(test_version)

# GTest: lsmio.cpp (logging setup, helper flags, enum strings and stream operators)
add_lsmio_base_test(test_lsmio)

# GTest: BMBase Regression Harness
add_executable(test_bm_base test_bm_base.cpp
  "${CMAKE_SOURCE_DIR}/benchmark/bm_base.cpp"
  "${CMAKE_SOURCE_DIR}/benchmark/PhaseTimeline.cpp"
  "${CMAKE_SOURCE_DIR}/benchmark/KeyPermutation.cpp"
  "${CMAKE_SOURCE_DIR}/benchmark/ReadShift.cpp")
target_include_directories(test_bm_base PRIVATE ${LSMIO_INCLUDE_DIR} "${CMAKE_SOURCE_DIR}/benchmark")
target_link_libraries(test_bm_base
  PUBLIC GTest::GTest GTest::Main
  PRIVATE lsmio::base_static fmt::fmt MPI::MPI_CXX CLI11::CLI11
)
gtest_discover_tests(test_bm_base
  NO_PRETTY_VALUES
  PROPERTIES
    TIMEOUT 30
    ENVIRONMENT "LD_LIBRARY_PATH=${CMAKE_BINARY_DIR}/lib:$ENV{LD_LIBRARY_PATH}"
  DISCOVERY_TIMEOUT 30
)

# GTest: Manager, LevelDB and RocksDB
add_lsmio_store_test(test_leveldb)
add_lsmio_store_test(test_rocksdb)
# The page-cache gate and its test seam are internal headers under lib/ (INV-20b): only these two
# tests reach them, by the "manager/store/..." path below lib/.
foreach(gate_test test_leveldb test_rocksdb)
  target_include_directories(${gate_test} PRIVATE ${LSMIO_SOURCE_DIR}/lib)
endforeach()
add_lsmio_store_test(test_native)
add_lsmio_store_test(test_native_extended)
add_lsmio_store_test(test_memtable)
add_lsmio_store_test(test_sstable_manager)
add_lsmio_store_test(test_file_pool)
add_lsmio_store_test(test_file_closer)
add_lsmio_store_test(test_manager)
add_lsmio_store_test(test_copy_once)
add_lsmio_store_test(test_store)
add_lsmio_posix_test(test_posix)

# GTest: MPI: Base and Manager
add_lsmio_mpi_test(test_mpi_base lsmio::base_static)
add_lsmio_mpi_test(test_mpi_manager lsmio::store_static)

# GTest: MPI: BMBase iteration orchestration and the read-source exchange (T4)
add_executable(test_mpi_bm_base test_mpi_bm_base.cpp test_mpi_utils.cpp
  "${CMAKE_SOURCE_DIR}/benchmark/bm_base.cpp"
  "${CMAKE_SOURCE_DIR}/benchmark/PhaseTimeline.cpp"
  "${CMAKE_SOURCE_DIR}/benchmark/KeyPermutation.cpp"
  "${CMAKE_SOURCE_DIR}/benchmark/ReadShift.cpp")
target_include_directories(test_mpi_bm_base PRIVATE ${LSMIO_INCLUDE_DIR} "${CMAKE_SOURCE_DIR}/benchmark")
target_link_libraries(test_mpi_bm_base
  PUBLIC GTest::GTest GTest::Main adios2::cxx_mpi MPI::MPI_CXX
  PRIVATE lsmio::base_static fmt::fmt CLI11::CLI11
)
gtest_discover_tests(test_mpi_bm_base
  NO_PRETTY_VALUES
  CMD_WRAPPER ${mpi_cmd} ${test_parameters}
  PROPERTIES
    TIMEOUT 30
    # Each test runs ${mpi_processes} ranks: count them against ctest -j
    PROCESSORS ${mpi_processes}
    ENVIRONMENT "LD_LIBRARY_PATH=${CMAKE_BINARY_DIR}/lib:$ENV{LD_LIBRARY_PATH}"
  DISCOVERY_TIMEOUT 30
)

# Below MPI_THREAD_MULTIPLE aggregation must be refused on every rank, not hang
add_test(
  NAME lsmioTest/managerMPIThreadTests.ThreadSerialized
  COMMAND ${mpi_cmd} ${test_parameters} $<TARGET_FILE:test_mpi_manager>
    --mpi-thread-serialized --gtest_filter=managerMPIThreadTests.*
  WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
)
set_tests_properties(lsmioTest/managerMPIThreadTests.ThreadSerialized PROPERTIES
  SKIP_REGULAR_EXPRESSION "\\[  SKIPPED \\]"
  ENVIRONMENT "LD_LIBRARY_PATH=${CMAKE_BINARY_DIR}/lib:$ENV{LD_LIBRARY_PATH}"
  TIMEOUT 30
  PROCESSORS ${mpi_processes}
)

# GTest: Adios and Plugin
add_executable(test_adios test_adios.cpp test_plugin.cpp)
target_include_directories(test_adios PRIVATE ${LSMIO_INCLUDE_DIR})
target_link_libraries(test_adios
  PUBLIC GTest::GTest GTest::Main adios2::cxx adios2::core
  PRIVATE lsmio::base_static
)
gtest_discover_tests(
  test_adios
  NO_PRETTY_VALUES
  PROPERTIES
    TIMEOUT 30
    # One value per property: a ; inside a PROPERTIES value splits it, dropping the second variable
    ENVIRONMENT "ADIOS2_PLUGIN_PATH=${CMAKE_BINARY_DIR}/lib"
    ENVIRONMENT_MODIFICATION "LD_LIBRARY_PATH=path_list_prepend:${CMAKE_BINARY_DIR}/lib"
  DISCOVERY_TIMEOUT 30
)

# GTest: MPI: Adios and Plugin
add_executable(test_mpi_adios test_mpi_adios.cpp test_mpi_utils.cpp)
target_include_directories(test_mpi_adios PRIVATE ${LSMIO_INCLUDE_DIR})
target_link_libraries(test_mpi_adios
  PUBLIC GTest::GTest GTest::Main adios2::cxx_mpi MPI::MPI_CXX
  PRIVATE lsmio::base_static
)
gtest_discover_tests(
  test_mpi_adios
  NO_PRETTY_VALUES
  CMD_WRAPPER ${mpi_cmd} ${test_parameters}
  PROPERTIES
    ENVIRONMENT "ADIOS2_PLUGIN_PATH=${CMAKE_BINARY_DIR}/lib"
    ENVIRONMENT_MODIFICATION "LD_LIBRARY_PATH=path_list_prepend:${CMAKE_BINARY_DIR}/lib"
    TIMEOUT 30
    PROCESSORS ${mpi_processes}
  DISCOVERY_TIMEOUT 30
)

# The plugin's MPI tests again with 3 ranks: with 2 there is a single client, so ranks never
# send different numbers of commands, and Split and Shared form the same group as Entire.
# Open MPI's mpirun counts one slot per physical core, so a host with fewer than 3 (such as a
# GitHub hosted runner) refuses to start 3 ranks. So this test always passes --oversubscribe
# when the launcher is named mpirun and the MPI is Open MPI, whatever the host size.
# Open MPI is detected first from the library version string FindMPI read from the MPI
# library (MPI_C_/MPI_CXX_LIBRARY_VERSION_STRING, saved by cmake/PackageAdios.cmake),
# because `mpirun --version` takes its text from help files that some packages leave out
# (Ubuntu 26.04's PMIx and PRRTE 3 ship none, so the output lacks "Open MPI"). The
# `mpirun --version` match is the fallback, for when that step was skipped (cross-compiling
# without an emulator) or failed, or the string does not say Open MPI.
# No other launcher gets it: MPICH's mpirun and aprun reject it, and srun's --oversubscribe
# means something else.
set(test_parameters_3 ${test_parameters})
list(POP_BACK test_parameters_3)
list(APPEND test_parameters_3 3)
set(mpi_oversubscribe OFF)
set(mpi_oversubscribe_check "none")
get_filename_component(mpi_cmd_name "${mpi_cmd}" NAME)
if(mpi_cmd_name STREQUAL "mpirun")
  get_property(mpi_library_version GLOBAL PROPERTY LSMIO_MPI_LIBRARY_VERSION_STRING)
  if(mpi_library_version MATCHES "Open MPI")
    set(mpi_oversubscribe ON)
    set(mpi_oversubscribe_check "library version string")
  else()
    execute_process(
      COMMAND ${mpi_cmd} --version
      OUTPUT_VARIABLE mpi_cmd_version
      ERROR_VARIABLE mpi_cmd_version
      RESULT_VARIABLE mpi_cmd_version_result
      TIMEOUT 30
    )
    if(mpi_cmd_version_result EQUAL 0 AND mpi_cmd_version MATCHES "Open MPI|OpenRTE")
      set(mpi_oversubscribe ON)
      set(mpi_oversubscribe_check "mpirun --version")
    endif()
  endif()
  if(mpi_oversubscribe)
    list(INSERT test_parameters_3 0 --oversubscribe)
  endif()
endif()
message(STATUS "Test module: ThreeRanks oversubscribe (Open MPI mpirun)=${mpi_oversubscribe} (matched: ${mpi_oversubscribe_check})")
add_test(
  NAME lsmioTest/pluginMPITests.ThreeRanks
  COMMAND ${mpi_cmd} ${test_parameters_3} $<TARGET_FILE:test_mpi_adios>
    --gtest_filter=lsmioTest/pluginMPITests.*
  WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
)
set_tests_properties(lsmioTest/pluginMPITests.ThreeRanks PROPERTIES
  ENVIRONMENT "ADIOS2_PLUGIN_PATH=${CMAKE_BINARY_DIR}/lib;LD_LIBRARY_PATH=${CMAKE_BINARY_DIR}/lib:$ENV{LD_LIBRARY_PATH}"
  TIMEOUT 120
  PROCESSORS 3
)

# Benchmark ctest entries (T5, T7): the benchmark executables on 3 ranks of one host, driven by
# cmake/BenchmarkMPITest.cmake. Every rank gets the same argv, so --per-rank-path is what gives
# each rank its own store. Every entry has its own work directory and its own -o (so parallel
# entries never share a store), and PROCESSORS 3 keeps ctest from overcommitting the host.
if(LSMIO_BUILD_BENCHMARKS AND TARGET bm_native)
  # add_benchmark_mpi_test(<ctest name> TARGET <bm target> EXPECT zero|nonzero
  #   ARGS <benchmark argv...> [MATCH ...] [NOT_MATCH ...] [COUNTS ...] [EXIST ...] [ABSENT ...]
  #   [LIST_DIRS ...])
  # The work directory is <build>/test/benchmark-mpi/<ctest name with / and . replaced by ->.
  # The semicolon lists are quoted, or add_test would split them before cmake -P sees them.
  function(add_benchmark_mpi_test x)
    cmake_parse_arguments(BMT "" "TARGET;EXPECT" "ARGS;MATCH;NOT_MATCH;COUNTS;EXIST;ABSENT;LIST_DIRS" ${ARGN})
    string(REGEX REPLACE "[/.]" "-" bmt_dir_name "${x}")
    set(bmt_work_dir "${CMAKE_CURRENT_BINARY_DIR}/benchmark-mpi/${bmt_dir_name}")
    set(bmt_command ${mpi_cmd} ${test_parameters_3} $<TARGET_FILE:${BMT_TARGET}> ${BMT_ARGS}
        -d ${bmt_work_dir} -o store)
    list(JOIN bmt_command ";" bmt_command_text)
    add_test(
      NAME ${x}
      COMMAND ${CMAKE_COMMAND}
        "-Dcommand=${bmt_command_text}"
        "-Dwork_dir=${bmt_work_dir}"
        "-Dexpect=${BMT_EXPECT}"
        "-Dtimeout=100"
        "-Dmatch=${BMT_MATCH}"
        "-Dnot_match=${BMT_NOT_MATCH}"
        "-Dcounts=${BMT_COUNTS}"
        "-Dexist=${BMT_EXIST}"
        "-Dabsent=${BMT_ABSENT}"
        "-Dlist_dirs=${BMT_LIST_DIRS}"
        -P ${CMAKE_SOURCE_DIR}/cmake/BenchmarkMPITest.cmake
    )
    set_tests_properties(${x} PROPERTIES
      ENVIRONMENT "ADIOS2_PLUGIN_PATH=${CMAKE_BINARY_DIR}/lib;LD_LIBRARY_PATH=${CMAKE_BINARY_DIR}/lib:$ENV{LD_LIBRARY_PATH}"
      TIMEOUT 120
      PROCESSORS 3
    )
  endfunction()

  # engine, benchmark target, extra argv, store option suffix (genDBPath), version header line
  set(bm_engines
    "native|bm_native||:0:0|"
    "rocksdb|bm_rocksdb||:0:0| rocksdbVersion: "
    "leveldb|bm_leveldb||:0:0| leveldbVersion: "
    "adios|bm_adios||:0:0|"
    "adiosplugin|bm_adios|--lsmio-plugin|:1:0|"
  )
  foreach(bm_engine IN LISTS bm_engines)
    # Fields can be empty, so read them by position.
    string(REGEX MATCH "^([^|]*)[|]([^|]*)[|]([^|]*)[|]([^|]*)[|](.*)$" bm_unused "${bm_engine}")
    set(bm_name "${CMAKE_MATCH_1}")
    set(bm_target "${CMAKE_MATCH_2}")
    set(bm_extra "${CMAKE_MATCH_3}")
    set(bm_suffix "${CMAKE_MATCH_4}")
    set(bm_version_line "${CMAKE_MATCH_5}")

    set(bm_store_paths "")
    foreach(bm_world_rank RANGE 0 2)
      list(APPEND bm_store_paths "store.mpirank${bm_world_rank}${bm_suffix}")
    endforeach()
    set(bm_common_match "durability: engine" "perRankPath: 1" "Phases:" "phase,write,1," "phase,read,1,")
    if(NOT bm_version_line STREQUAL "")
      list(APPEND bm_common_match "${bm_version_line}")
    endif()
    set(bm_list_dirs "")
    if(bm_name STREQUAL "adiosplugin" OR bm_name STREQUAL "rocksdb")
      # E7: the file names in each rank's store after the shifted run, and after the unshifted
      # run (each reader on its own store) to compare with; listing.log in the work directory
      set(bm_list_dirs "store.mpirank*${bm_suffix}")
    endif()

    # T5, simulated: 3 nodes on one host, so every rank reads a peer's store
    add_benchmark_mpi_test(benchmarkMPI/${bm_name}.ReadShiftSimulated
      TARGET ${bm_target}
      EXPECT zero
      ARGS -m --per-rank-path --read-shift --read-shift-nodes 3 -i 2 -k 64 -z 1024 ${bm_extra}
      MATCH ${bm_common_match} "rankShiftNodes: simulated:3" "rankShiftSelfRanks: 0" "rankShiftSource: 1"
      COUNTS "iread,=2" "iwrite,=2"
      EXIST ${bm_store_paths}
      LIST_DIRS ${bm_list_dirs}
    )

    # T5, unsimulated: one host, so all 3 ranks share the node and each reads its own store
    add_benchmark_mpi_test(benchmarkMPI/${bm_name}.ReadShiftUnsimulated
      TARGET ${bm_target}
      EXPECT zero
      ARGS -m --per-rank-path --read-shift -i 2 -k 64 -z 1024 ${bm_extra}
      MATCH ${bm_common_match} "rankShiftNodes: shared" "rankShiftSelfRanks: 3"
      COUNTS "iread,=2" "iwrite,=2"
      EXIST ${bm_store_paths}
      LIST_DIRS ${bm_list_dirs}
    )
  endforeach()

  # T7: refusals, on every rank, before any store is opened
  add_benchmark_mpi_test(benchmarkMPI/native.ReadShiftSharedPathRefused
    TARGET bm_native
    EXPECT nonzero
    ARGS -m --read-shift --read-shift-nodes 3 -i 2 -k 64 -z 1024
    MATCH "same store path" "--per-rank-path"
    ABSENT "store*"
  )
  add_benchmark_mpi_test(benchmarkMPI/native.ReadShiftNodesAboveWorldRefused
    TARGET bm_native
    EXPECT nonzero
    ARGS -m --per-rank-path --read-shift --read-shift-nodes 4 -i 2 -k 64 -z 1024
    MATCH "is larger than the MPI world size 3"
    ABSENT "store*"
  )
  add_benchmark_mpi_test(benchmarkMPI/manager.ReadShiftNotSupportedRefused
    TARGET bm_manager
    EXPECT nonzero
    ARGS -m --per-rank-path --read-shift --read-shift-nodes 3 -i 2 -k 64 -z 1024
    MATCH "is not supported by this benchmark executable"
    ABSENT "store*"
  )
endif()

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

