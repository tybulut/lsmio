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

# StageLsmiotoolTest.cmake
# Performs isolated staged installation of lsmiotool into a build-private prefix
# and prepares clean smoke working directory and fake HOME.

if(NOT DEFINED build_dir OR "${build_dir}" STREQUAL "")
  message(FATAL_ERROR "StageLsmiotoolTest: 'build_dir' variable must be defined and non-empty.")
endif()

if(NOT DEFINED stage_dir OR "${stage_dir}" STREQUAL "")
  message(FATAL_ERROR "StageLsmiotoolTest: 'stage_dir' variable must be defined and non-empty.")
endif()

get_filename_component(abs_build_dir "${build_dir}" ABSOLUTE)
get_filename_component(abs_stage_dir "${stage_dir}" ABSOLUTE)

# Verify that build_dir exists and is a directory
if(NOT IS_DIRECTORY "${abs_build_dir}")
  message(FATAL_ERROR "StageLsmiotoolTest: build_dir '${abs_build_dir}' does not exist or is not a directory.")
endif()

# Verify that stage_dir resides strictly inside build_dir
file(RELATIVE_PATH rel_stage "${abs_build_dir}" "${abs_stage_dir}")
if(rel_stage MATCHES "^\\.\\." OR IS_ABSOLUTE "${rel_stage}" OR "${rel_stage}" STREQUAL "" OR "${rel_stage}" STREQUAL ".")
  message(FATAL_ERROR "StageLsmiotoolTest: stage_dir '${abs_stage_dir}' must reside strictly inside build_dir '${abs_build_dir}'.")
endif()

set(smoke_cwd "${abs_build_dir}/lsmiotool-smoke-cwd")
set(smoke_home "${abs_build_dir}/lsmiotool-smoke-home")

# Safely remove and recreate stage_dir, smoke_cwd, and smoke_home
file(REMOVE_RECURSE "${abs_stage_dir}" "${smoke_cwd}" "${smoke_home}")
file(MAKE_DIRECTORY "${abs_stage_dir}" "${smoke_cwd}" "${smoke_home}")

# Execute cmake --install
execute_process(
  COMMAND "${CMAKE_COMMAND}" --install "${abs_build_dir}" --prefix "${abs_stage_dir}"
  RESULT_VARIABLE install_res
  OUTPUT_VARIABLE install_out
  ERROR_VARIABLE install_err
)

if(NOT install_res EQUAL 0)
  message(FATAL_ERROR "StageLsmiotoolTest: Staged install failed with exit code ${install_res}:\n${install_out}\n${install_err}")
endif()

message(STATUS "StageLsmiotoolTest: Successfully staged installation to ${abs_stage_dir}")
