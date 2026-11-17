#
# Copyright 2026 Serdar Bulut
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived from
#    this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#

# BenchmarkMPITest.cmake
# Runs one benchmark executable under the MPI launcher in its own work directory and checks the
# outcome. Used by the benchmarkMPI/* ctest entries (cmake -P).
#
# Inputs (-D). Lists are semicolon separated; quote them in add_test so ctest does not split them.
#   command    required  the whole command: launcher, its parameters, the executable, its argv
#   work_dir   required  removed and recreated first; the command runs in it; the combined
#                        stdout+stderr is saved there as output.log
#   expect     required  zero | nonzero (the exit status of the command)
#   timeout    optional  seconds before the command is killed (default 100)
#   match      optional  regexes that must match the combined output (not anchored at line start:
#                        Open MPI's -tag-output prefixes every line)
#   not_match  optional  regexes that must not match the combined output
#   counts     optional  "<regex>=<n>" items: the regex must match exactly n times
#   exist      optional  glob patterns (relative to work_dir) that must match at least one path
#   absent     optional  glob patterns (relative to work_dir) that must match no path
#   list_dirs  optional  glob patterns (relative to work_dir) of directories whose file names and
#                        sizes are printed afterwards (the E7 listing)
# Regexes and patterns must not contain a semicolon, a square bracket or a backslash: they travel
# through a CMake list and the generated CTestTestfile.

foreach(required_variable command work_dir expect)
  if(NOT DEFINED ${required_variable} OR "${${required_variable}}" STREQUAL "")
    message(FATAL_ERROR "BenchmarkMPITest: '${required_variable}' must be defined and non-empty.")
  endif()
endforeach()
if(NOT expect STREQUAL "zero" AND NOT expect STREQUAL "nonzero")
  message(FATAL_ERROR "BenchmarkMPITest: 'expect' must be zero or nonzero, not '${expect}'.")
endif()
if(NOT DEFINED timeout OR "${timeout}" STREQUAL "")
  set(timeout 100)
endif()

get_filename_component(abs_work_dir "${work_dir}" ABSOLUTE)
file(REMOVE_RECURSE "${abs_work_dir}")
file(MAKE_DIRECTORY "${abs_work_dir}")

execute_process(
  COMMAND ${command}
  WORKING_DIRECTORY "${abs_work_dir}"
  RESULT_VARIABLE run_result
  OUTPUT_VARIABLE run_output
  ERROR_VARIABLE run_output
  TIMEOUT ${timeout}
)
file(WRITE "${abs_work_dir}/output.log" "${run_output}")

function(failCheck f_message)
  message("---- output of the command (${abs_work_dir}/output.log) ----\n${run_output}\n----")
  message(FATAL_ERROR "BenchmarkMPITest: ${f_message}")
endfunction()

# execute_process sets the result to a text such as "Process terminated due to timeout" when it
# kills the command, and to the exit status otherwise.
if(NOT run_result MATCHES "^-?[0-9]+$")
  failCheck("the command did not finish: ${run_result}")
endif()
if(expect STREQUAL "zero" AND NOT run_result EQUAL 0)
  failCheck("expected exit status 0, got ${run_result}")
endif()
if(expect STREQUAL "nonzero" AND run_result EQUAL 0)
  failCheck("expected a non-zero exit status, got 0")
endif()

foreach(pattern IN LISTS match)
  if(NOT run_output MATCHES "${pattern}")
    failCheck("the output does not match '${pattern}'")
  endif()
endforeach()

foreach(pattern IN LISTS not_match)
  if(run_output MATCHES "${pattern}")
    failCheck("the output matches '${pattern}', which it must not")
  endif()
endforeach()

foreach(item IN LISTS counts)
  if(NOT item MATCHES "^(.+)=([0-9]+)$")
    message(FATAL_ERROR "BenchmarkMPITest: bad counts item '${item}', expected <regex>=<n>.")
  endif()
  set(count_pattern "${CMAKE_MATCH_1}")
  set(count_wanted "${CMAKE_MATCH_2}")
  string(REGEX MATCHALL "${count_pattern}" count_found "${run_output}")
  list(LENGTH count_found count_found_size)
  if(NOT count_found_size EQUAL count_wanted)
    failCheck("'${count_pattern}' matches ${count_found_size} times, expected ${count_wanted}")
  endif()
endforeach()

foreach(pattern IN LISTS exist)
  file(GLOB found_paths "${abs_work_dir}/${pattern}")
  if(NOT found_paths)
    failCheck("no path matches '${pattern}' under ${abs_work_dir}")
  endif()
endforeach()

foreach(pattern IN LISTS absent)
  file(GLOB found_paths "${abs_work_dir}/${pattern}")
  if(found_paths)
    failCheck("path(s) match '${pattern}' under ${abs_work_dir}, which must not exist: ${found_paths}")
  endif()
endforeach()

set(all_listings "")
foreach(pattern IN LISTS list_dirs)
  file(GLOB listed_dirs "${abs_work_dir}/${pattern}")
  if(NOT listed_dirs)
    failCheck("no directory matches '${pattern}' under ${abs_work_dir} to list")
  endif()
  foreach(listed_dir IN LISTS listed_dirs)
    file(GLOB listed_files RELATIVE "${listed_dir}" "${listed_dir}/*")
    list(SORT listed_files)
    set(listing "")
    foreach(listed_file IN LISTS listed_files)
      file(SIZE "${listed_dir}/${listed_file}" listed_size)
      string(APPEND listing "  ${listed_file} ${listed_size}\n")
    endforeach()
    file(RELATIVE_PATH listed_name "${abs_work_dir}" "${listed_dir}")
    message("listing ${listed_name}:\n${listing}")
    string(APPEND all_listings "listing ${listed_name}:\n${listing}")
  endforeach()
endforeach()
if(NOT all_listings STREQUAL "")
  # A passing ctest entry prints nothing, so the listing is also kept in a file next to output.log.
  file(WRITE "${abs_work_dir}/listing.log" "${all_listings}")
endif()
