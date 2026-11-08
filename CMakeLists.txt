cmake_minimum_required(VERSION 3.12)

# Clang by default, as in loreos: when no compiler is set (CMAKE_C_COMPILER,
# CMAKE_CXX_COMPILER, CC, CXX), choose clang++ >= 19 and the clang in the same
# directory. A set compiler, e.g. CI's -DCMAKE_CXX_COMPILER=g++ or a parent
# project's, skips all of this. If Clang cannot compile and link a program that
# includes <string> (no libstdc++ where it looks), look for a GCC installation
# with libstdc++ that Clang builds with and add --gcc-install-dir=<dir> to the C,
# C++ and linker flags, keeping the caller's flags. The chosen compilers are
# cached, so this runs once per build tree and later configures change nothing.
if(NOT DEFINED CMAKE_C_COMPILER AND NOT DEFINED CMAKE_CXX_COMPILER
   AND NOT DEFINED ENV{CC} AND NOT DEFINED ENV{CXX})
  # Compiles and links a program that includes <string> with clang++ $cxx, the
  # caller's flags and any extra arguments. Sets $result to 0 on success.
  function(lsmio_clang_builds result cxx)
    set(_dir "${CMAKE_BINARY_DIR}/CMakeFiles/lsmio-probe")
    file(WRITE "${_dir}/probe.cpp" "#include <string>\nint main() { std::string s; return static_cast<int>(s.size()); }\n")
    separate_arguments(_cxxflags UNIX_COMMAND "$ENV{CXXFLAGS} ${CMAKE_CXX_FLAGS}")
    separate_arguments(_ldflags UNIX_COMMAND "$ENV{LDFLAGS} ${CMAKE_EXE_LINKER_FLAGS}")
    execute_process(
      COMMAND "${cxx}" ${_cxxflags} ${_ldflags} ${ARGN} "${_dir}/probe.cpp" -o "${_dir}/probe.out"
      RESULT_VARIABLE _rc
      OUTPUT_QUIET
      ERROR_QUIET
    )
    set(${result} ${_rc} PARENT_SCOPE)
  endfunction()

  # Candidates: clang++ first, then clang++-NN from the highest. The version
  # must be 19 or more, and the C compiler is the clang (clang-NN) next to it.
  set(_lsmio_names clang++)
  foreach(_v RANGE 19 40)
    list(INSERT _lsmio_names 1 clang++-${_v})
  endforeach()
  set(_lsmio_cxx "")
  set(_lsmio_cc "")
  foreach(_name IN LISTS _lsmio_names)
    find_program(_lsmio_found_cxx NAMES ${_name})
    if(_lsmio_found_cxx)
      execute_process(
        COMMAND "${_lsmio_found_cxx}" -dumpversion
        OUTPUT_VARIABLE _raw
        OUTPUT_STRIP_TRAILING_WHITESPACE
        ERROR_QUIET
        RESULT_VARIABLE _rc
      )
      string(REGEX MATCH "^[0-9]+" _major "${_raw}")
      if(_rc EQUAL 0 AND _major AND NOT _major LESS 19)
        if(_name STREQUAL "clang++")
          set(_cname clang)
        else()
          string(REPLACE "clang++-" "clang-" _cname "${_name}")
        endif()
        get_filename_component(_dir "${_lsmio_found_cxx}" DIRECTORY)
        find_program(_lsmio_found_cc NAMES ${_cname} PATHS "${_dir}" NO_DEFAULT_PATH)
        if(_lsmio_found_cc)
          set(_lsmio_cxx "${_lsmio_found_cxx}")
          set(_lsmio_cc "${_lsmio_found_cc}")
        else()
          message(STATUS "Skipping ${_lsmio_found_cxx}: no ${_cname} in ${_dir}")
        endif()
      endif()
    endif()
    unset(_lsmio_found_cxx CACHE)
    unset(_lsmio_found_cc CACHE)
    if(_lsmio_cxx)
      break()
    endif()
  endforeach()

  if(_lsmio_cxx)
    lsmio_clang_builds(_rc "${_lsmio_cxx}")
    set(_lsmio_use_clang TRUE)
    if(NOT _rc EQUAL 0)
      set(_lsmio_use_clang FALSE)
      file(GLOB _lsmio_gcc_dirs "/usr/lib/gcc/*/*")
      # Try the highest version first (numeric comparison), as Clang itself does.
      while(_lsmio_gcc_dirs)
        set(_best "")
        set(_best_ver "")
        foreach(_gdir IN LISTS _lsmio_gcc_dirs)
          get_filename_component(_ver "${_gdir}" NAME)
          if(NOT _best OR _ver VERSION_GREATER _best_ver)
            set(_best "${_gdir}")
            set(_best_ver "${_ver}")
          endif()
        endforeach()
        list(REMOVE_ITEM _lsmio_gcc_dirs "${_best}")
        if(EXISTS "${_best}/libstdc++.so" OR EXISTS "${_best}/libstdc++.a")
          lsmio_clang_builds(_rc "${_lsmio_cxx}" "--gcc-install-dir=${_best}")
          if(_rc EQUAL 0)
            message(STATUS "Found a GCC installation with libstdc++ for Clang: ${_best}")
            set(_lsmio_use_clang TRUE)
            # Append to the caller's flags. A flag passed with -D is a cache entry
            # already; the others are appended through CMake's *_INIT variables,
            # which keep the environment's CFLAGS, CXXFLAGS and LDFLAGS.
            foreach(_var CMAKE_C_FLAGS CMAKE_CXX_FLAGS CMAKE_EXE_LINKER_FLAGS
                         CMAKE_SHARED_LINKER_FLAGS CMAKE_MODULE_LINKER_FLAGS)
              if(DEFINED ${_var})
                set(${_var} "${${_var}} --gcc-install-dir=${_best}" CACHE STRING "" FORCE)
              else()
                set(${_var}_INIT "${${_var}_INIT} --gcc-install-dir=${_best}")
              endif()
            endforeach()
            break()
          endif()
        endif()
      endwhile()
      if(NOT _lsmio_use_clang)
        message(STATUS "Clang ${_lsmio_cxx} cannot build with libstdc++ and no GCC installation helps; using the default compilers")
      endif()
    endif()
    if(_lsmio_use_clang)
      set(CMAKE_CXX_COMPILER "${_lsmio_cxx}" CACHE FILEPATH "C++ compiler" FORCE)
      set(CMAKE_C_COMPILER "${_lsmio_cc}" CACHE FILEPATH "C compiler" FORCE)
    endif()
  else()
    message(STATUS "No Clang >= 19 with a matching clang found; using the default compilers")
  endif()
endif()

if(APPLE AND NOT DEFINED CMAKE_OSX_DEPLOYMENT_TARGET AND NOT DEFINED ENV{MACOSX_DEPLOYMENT_TARGET})
  if(EXISTS "/opt/homebrew/opt/fmt/lib/libfmt.dylib")
    execute_process(
      COMMAND otool -l /opt/homebrew/opt/fmt/lib/libfmt.dylib
      OUTPUT_VARIABLE _fmt_otool
      ERROR_QUIET
    )
    if(_fmt_otool MATCHES "minos ([0-9]+\\.[0-9]+)")
      set(CMAKE_OSX_DEPLOYMENT_TARGET "${CMAKE_MATCH_1}" CACHE STRING "macOS deployment target aligned with Homebrew dylibs" FORCE)
    endif()
  endif()
endif()

file(READ "${CMAKE_CURRENT_SOURCE_DIR}/tools/lsmiotool/VERSION" LSMIO_VERSION)
string(STRIP "${LSMIO_VERSION}" LSMIO_VERSION)

project(lsmio VERSION ${LSMIO_VERSION} LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(CMAKE_FIND_PACKAGE_TARGETS_GLOBAL ON)

# RPATH settings
set(CMAKE_MACOSX_RPATH 1)
set(CMAKE_INSTALL_RPATH "${CMAKE_INSTALL_PREFIX}/lib")
set(CMAKE_INSTALL_RPATH_USE_LINK_PATH TRUE)

if(CMAKE_SIZEOF_VOID_P EQUAL 8)
  message(STATUS "Main: 64-bit compiler detected")
else(CMAKE_SIZEOF_VOID_P EQUAL 8)
  message(FATAL_ERROR "Main: 32-bit compiler detected")
endif(CMAKE_SIZEOF_VOID_P EQUAL 8)

# MacOS
if(APPLE)
    add_compile_options(-Wno-vla-cxx-extension)
endif()

include(ProcessorCount)
ProcessorCount(N)
if (N GREATER_EQUAL 2)
  math(EXPR M "${N} / 2" OUTPUT_FORMAT DECIMAL)
  message(STATUS "Main: Recommended minimum CMAKE_BUILD_PARALLEL_LEVEL: ${M}")
endif()

set(LSMIO_SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
set(CUSTOM_PACKAGE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")

list(PREPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")
include(cmake/ProjectOptions.cmake)
lsmio_setup_options()

if(LSMIO_ENABLE_COVERAGE AND NOT CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  message(FATAL_ERROR "LSMIO_ENABLE_COVERAGE is ON, but the C++ compiler is ${CMAKE_CXX_COMPILER_ID} (${CMAKE_CXX_COMPILER}). C++ coverage uses llvm-cov and needs Clang: run './build.sh clean coverage' with CC and CXX unset.")
endif()

execute_process(
  COMMAND git rev-parse --abbrev-ref HEAD
  WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
  OUTPUT_VARIABLE LSMIO_GIT_BRANCH
  OUTPUT_STRIP_TRAILING_WHITESPACE
  ERROR_QUIET
)
execute_process(
  COMMAND git rev-parse --short HEAD
  WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
  OUTPUT_VARIABLE LSMIO_GIT_COMMIT_HASH
  OUTPUT_STRIP_TRAILING_WHITESPACE
  ERROR_QUIET
)

if(NOT LSMIO_GIT_BRANCH)
  set(LSMIO_GIT_BRANCH "unknown")
endif()

if(NOT LSMIO_GIT_COMMIT_HASH)
  set(LSMIO_GIT_COMMIT_HASH "unknown")
endif()

# Defines
add_subdirectory(include)
include(PackageTLX)

# Sub directories
add_subdirectory(lib)

# enable benchmark functionality
if(LSMIO_BUILD_BENCHMARKS)
  add_subdirectory(benchmark)
endif()

# tools
add_subdirectory(tools/lsmiotool)

# Last step
include(DebianPkg)

# enable testing functionality
if(LSMIO_BUILD_TESTS)
  # Include dependencies
  include(CTest)
  find_package(Python3 REQUIRED COMPONENTS Interpreter)

  if(LSMIO_ENABLE_COVERAGE)
    execute_process(
      COMMAND "${Python3_EXECUTABLE}" -c "import coverage"
      RESULT_VARIABLE _coverage_status
      OUTPUT_QUIET
      ERROR_QUIET
    )
    if(NOT _coverage_status EQUAL 0)
      message(FATAL_ERROR "LSMIO_ENABLE_COVERAGE is ON, but Python 'coverage' module is not available on '${Python3_EXECUTABLE}'. Please install coverage (e.g. '${Python3_EXECUTABLE} -m pip install coverage') and re-run CMake.")
    endif()
  endif()

  enable_testing()
  add_subdirectory(test)
endif()

lsmio_print_build_config()
