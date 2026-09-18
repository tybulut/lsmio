include(CMakeDependentOption)
include(CheckCXXCompilerFlag)

# Compiler options
option(BUILD_SHARED_LIBS "Build shared libraries" ON)
# To enable: -rdynamic
#set_property(TARGET compiler PROPERTY ENABLE_EXPORTS ON)
# To enable: -fPIC
#set(CMAKE_POSITION_INDEPENDENT_CODE ON)

function(add_LSMIO_option name description default)
  set(LSMIO_USE_${name} ${default} CACHE STRING "${description}")
  set(LSMIO_HAVE_${name} OFF CACHE INTERNAL "(Internal) ${description}")
  set_property(CACHE LSMIO_USE_${name} PROPERTY
    STRINGS "ON;TRUE;AUTO;OFF;FALSE"
  )
endfunction()

function(set_LSMIO_option name value)
  set(LSMIO_HAVE_${name} ${value} CACHE INTERNAL "${name}")
endfunction()


macro(lsmio_setup_options)
  option(LSMIO_BUILD_BENCHMARKS "Build LSMIO benchmarks" ON)
  option(LSMIO_BUILD_TESTS "Compile LSMIO tests" ON)
  option(LSMIO_ENABLE_COVERAGE "Enable code coverage reporting" OFF)
  option(LSMIO_USE_LLD "Link with lld when available" ON)

  if(NOT PROJECT_IS_TOP_LEVEL)
    mark_as_advanced(
      LSMIO_BUILD_BENCHMARKS
      LSMIO_BUILD_TESTS
      LSMIO_ENABLE_COVERAGE
      LSMIO_USE_LLD
    )
  endif()

  lsmio_setup_linker()
endmacro()


# Prefer lld when the toolchain supports it: it is multi-threaded and links much
# faster than GNU ld. Skipped on Apple, whose default linker is already fast,
# and on CMake < 3.18, which lacks check_linker_flag. A macro, so
# add_link_options applies to the calling directory.
macro(lsmio_setup_linker)
  set(LSMIO_LINKER "default")
  if(LSMIO_USE_LLD AND NOT APPLE AND CMAKE_VERSION VERSION_GREATER_EQUAL 3.18)
    include(CheckLinkerFlag)
    check_linker_flag(CXX "-fuse-ld=lld" LSMIO_HAS_LLD)
    if(LSMIO_HAS_LLD)
      add_link_options(-fuse-ld=lld)
      set(LSMIO_LINKER "lld")
    endif()
  endif()
endmacro()


macro(lsmio_print_build_config)
  message("")
  message("LSMIO build configuration:")
  message("  Version: ${LSMIO_VERSION}")
  message("  C++ Compiler: ${CMAKE_CXX_COMPILER_ID} "
                        "${CMAKE_CXX_COMPILER_VERSION} "
                        "${CMAKE_CXX_COMPILER_WRAPPER}")
  message("    ${CMAKE_CXX_COMPILER}")
  message("")
  message("  Installation prefix: ${CMAKE_INSTALL_PREFIX}")
  message("  Build options:")

  set(LIB_TYPE "")
  if(BUILD_SHARED_LIBS)
    set(LIB_TYPE " (shared)")
  else()
    set(LIB_TYPE " (static)")
  endif()
  message("    Library Type: ${LIB_TYPE}")
  message("    Build LSMIO benchmarks: ${LSMIO_BUILD_BENCHMARKS}")
  message("    Compile LSMIO tests: ${LSMIO_BUILD_TESTS}")
  message("    Enable coverage: ${LSMIO_ENABLE_COVERAGE}")
  message("    Linker: ${LSMIO_LINKER}")
  message("  --")
  message("")
  message("")
endmacro()
