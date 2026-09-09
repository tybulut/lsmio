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

# LsmiotoolPythonCoverage.cmake
# Manages explicit, verified Python branch-coverage collection and reporting for lsmiotool.

if(NOT DEFINED mode OR "${mode}" STREQUAL "")
  message(FATAL_ERROR "LsmiotoolPythonCoverage: 'mode' variable must be defined ('run' or 'report').")
endif()

if(NOT DEFINED python OR "${python}" STREQUAL "")
  message(FATAL_ERROR "LsmiotoolPythonCoverage: 'python' variable must be defined.")
endif()

if(NOT DEFINED data OR "${data}" STREQUAL "")
  message(FATAL_ERROR "LsmiotoolPythonCoverage: 'data' variable must be defined.")
endif()

if(NOT DEFINED json OR "${json}" STREQUAL "")
  message(FATAL_ERROR "LsmiotoolPythonCoverage: 'json' variable must be defined.")
endif()

if(NOT DEFINED marker OR "${marker}" STREQUAL "")
  message(FATAL_ERROR "LsmiotoolPythonCoverage: 'marker' variable must be defined.")
endif()

# Validate absolute paths
if(NOT IS_ABSOLUTE "${data}")
  message(FATAL_ERROR "LsmiotoolPythonCoverage: data path must be absolute: '${data}'")
endif()

if(NOT IS_ABSOLUTE "${json}")
  message(FATAL_ERROR "LsmiotoolPythonCoverage: json path must be absolute: '${json}'")
endif()

if(NOT IS_ABSOLUTE "${marker}")
  message(FATAL_ERROR "LsmiotoolPythonCoverage: marker path must be absolute: '${marker}'")
endif()

# Validate that data, json, marker reside within build tree if build_dir is defined
if(DEFINED build_dir AND NOT "${build_dir}" STREQUAL "")
  get_filename_component(abs_build_dir "${build_dir}" ABSOLUTE)
  file(RELATIVE_PATH rel_data "${abs_build_dir}" "${data}")
  file(RELATIVE_PATH rel_json "${abs_build_dir}" "${json}")
  file(RELATIVE_PATH rel_marker "${abs_build_dir}" "${marker}")
  if(rel_data MATCHES "^\\.\\." OR IS_ABSOLUTE "${rel_data}" OR "${rel_data}" STREQUAL "")
    message(FATAL_ERROR "LsmiotoolPythonCoverage: data path '${data}' must reside inside build_dir '${abs_build_dir}'.")
  endif()
  if(rel_json MATCHES "^\\.\\." OR IS_ABSOLUTE "${rel_json}" OR "${rel_json}" STREQUAL "")
    message(FATAL_ERROR "LsmiotoolPythonCoverage: json path '${json}' must reside inside build_dir '${abs_build_dir}'.")
  endif()
  if(rel_marker MATCHES "^\\.\\." OR IS_ABSOLUTE "${rel_marker}" OR "${rel_marker}" STREQUAL "")
    message(FATAL_ERROR "LsmiotoolPythonCoverage: marker path '${marker}' must reside inside build_dir '${abs_build_dir}'.")
  endif()
endif()

if("${mode}" STREQUAL "run")
  if(NOT DEFINED source OR "${source}" STREQUAL "")
    message(FATAL_ERROR "LsmiotoolPythonCoverage (run): 'source' variable must be defined.")
  endif()
  if(NOT DEFINED entry OR "${entry}" STREQUAL "")
    message(FATAL_ERROR "LsmiotoolPythonCoverage (run): 'entry' variable must be defined.")
  endif()
  if(NOT IS_ABSOLUTE "${source}")
    message(FATAL_ERROR "LsmiotoolPythonCoverage (run): source path must be absolute: '${source}'")
  endif()
  if(NOT IS_ABSOLUTE "${entry}")
    message(FATAL_ERROR "LsmiotoolPythonCoverage (run): entry path must be absolute: '${entry}'")
  endif()

  # Remove only the three build-private files
  file(REMOVE "${data}" "${json}" "${marker}")

  # Execute python coverage run
  execute_process(
    COMMAND "${python}" -m coverage run
            "--data-file=${data}"
            --branch
            "--source=${source}"
            --omit=*/test/*,*/ctest/*,*/__pycache__/*
            "${entry}"
            test
    RESULT_VARIABLE run_res
  )

  # Check result and data file validity
  if(NOT run_res EQUAL 0)
    file(REMOVE "${data}" "${marker}")
    message(FATAL_ERROR "LsmiotoolPythonCoverage: Test suite execution under coverage failed with exit code ${run_res}.")
  endif()

  if(NOT EXISTS "${data}")
    file(REMOVE "${data}" "${marker}")
    message(FATAL_ERROR "LsmiotoolPythonCoverage: Expected coverage data file '${data}' was not created.")
  endif()

  file(SIZE "${data}" data_size)
  if(data_size EQUAL 0)
    file(REMOVE "${data}" "${marker}")
    message(FATAL_ERROR "LsmiotoolPythonCoverage: Coverage data file '${data}' is empty (0 bytes).")
  endif()

  # Calculate SHA256 and write to marker file
  file(SHA256 "${data}" data_sha256)
  file(WRITE "${marker}" "${data_sha256}\n")
  message(STATUS "LsmiotoolPythonCoverage: Coverage run succeeded; marker written to ${marker}")

elseif("${mode}" STREQUAL "report")
  # Validate that data and marker exist
  if(NOT EXISTS "${data}")
    message(FATAL_ERROR "LsmiotoolPythonCoverage: Coverage data file '${data}' does not exist.")
  endif()

  if(NOT EXISTS "${marker}")
    message(FATAL_ERROR "LsmiotoolPythonCoverage: Coverage marker file '${marker}' does not exist.")
  endif()

  file(SIZE "${data}" data_size)
  if(data_size EQUAL 0)
    message(FATAL_ERROR "LsmiotoolPythonCoverage: Coverage data file '${data}' is empty (0 bytes).")
  endif()

  # Read marker and verify hash
  file(READ "${marker}" expected_sha256)
  string(STRIP "${expected_sha256}" expected_sha256)
  if("${expected_sha256}" STREQUAL "")
    message(FATAL_ERROR "LsmiotoolPythonCoverage: Coverage marker file '${marker}' is empty.")
  endif()

  file(SHA256 "${data}" actual_sha256)
  if(NOT "${actual_sha256}" STREQUAL "${expected_sha256}")
    message(FATAL_ERROR "LsmiotoolPythonCoverage: Coverage data file '${data}' SHA256 '${actual_sha256}' does not match marker SHA256 '${expected_sha256}'.")
  endif()

  # Remove only the exact json path
  file(REMOVE "${json}")

  # Execute python coverage json
  execute_process(
    COMMAND "${python}" -m coverage json "--data-file=${data}" -o "${json}"
    RESULT_VARIABLE json_res
    OUTPUT_VARIABLE json_out
    ERROR_VARIABLE json_err
  )
  if(NOT json_res EQUAL 0)
    message(FATAL_ERROR "LsmiotoolPythonCoverage: 'coverage json' failed with exit code ${json_res}:\n${json_out}\n${json_err}")
  endif()

  # Execute python coverage report
  execute_process(
    COMMAND "${python}" -m coverage report "--data-file=${data}"
    RESULT_VARIABLE report_res
  )
  if(NOT report_res EQUAL 0)
    message(FATAL_ERROR "LsmiotoolPythonCoverage: 'coverage report' failed with exit code ${report_res}.")
  endif()

  # Verify json exists and is non-empty
  if(NOT EXISTS "${json}")
    message(FATAL_ERROR "LsmiotoolPythonCoverage: Coverage JSON report '${json}' was not created.")
  endif()

  file(SIZE "${json}" json_size)
  if(json_size EQUAL 0)
    message(FATAL_ERROR "LsmiotoolPythonCoverage: Coverage JSON report '${json}' is empty (0 bytes).")
  endif()

  message(STATUS "LsmiotoolPythonCoverage: Successfully generated coverage report at ${json}")

else()
  message(FATAL_ERROR "LsmiotoolPythonCoverage: Unknown mode '${mode}'. Supported modes are 'run' and 'report'.")
endif()
