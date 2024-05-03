#!/bin/sh
#
# Copyright 2023 Serdar Bulut
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

BM_USAGE="Usage:
$0 <cmd> <cmd-arguments> [<cmd-optional-arguments>]

cmds:
  run <ior|lsmio|lmp> <local|bake|small|large> [<--ssd>]
  parse <ior|lsmio|lmp> <local|bake|small|large> [<--ssd>]
  load-modules
"

export BM_SCRIPT=`realpath $0`
export BM_DIRNAME=`dirname $BM_SCRIPT`

fatal_error() {
  echo "ERROR: $1"
  echo "$BM_USAGE"
  exit 1
}

# Sanity checks
if [ -z "$BM_SCRIPT" -o -z "$BM_DIRNAME" ]; then
  fatal_error "Failed to determine the script environment"
fi

# SBatch settings
if [ -z "$SB_EMAIL" ]; then
  fatal_error "Email for SBATCH is not set using SB_EMAIL: $SB_EMAIL"
fi
if [ -z "$SB_ACCOUNT" ]; then
  fatal_error "Account for SBATCH is not set using SB_ACCOUNT: $SB_ACCOUNT"
fi

# Parse arguments
if [ "$1" = "parse" ]; then
  PASS_CMD="parse"
elif [ "$1" = "run" ]; then
  PASS_CMD="run"
elif [ "$1" = "load-modules" ]; then
  PASS_CMD="load-modules"
elif [ -z "$1" ]; then
  fatal_error "Please pass a non-empty cmd."
else
  fatal_error "Invalid cmd: [$1]. Please pass a valid cmd."
fi

if [ "$2" = "ior" ]; then
  JOB_TOOL="ior"
elif [ "$2" = "lsmio" ]; then
  JOB_TOOL="lsmio"
elif [ "$2" = "lmp" ]; then
  JOB_TOOL="lmp"
elif [ "$PASS_CMD" != "load-modules" ]; then
  fatal_error "Please pass either ior, lsmio, or lmp as a first cmd argument."
fi

if [ "$PASS_CMD" = "run" ]; then
  SSD_ARG="$4"
elif [ "$PASS_CMD" = "parse" ]; then
  SSD_ARG="$4"
fi

if [ -n "$SSD_ARG" ]; then
  if [ "$SSD_ARG" = "--ssd" ]; then
    # Set before including vars.in.sh
    LUSTRE_SSD=on
  else
    fatal_error "Unknown argument for $PASS_CMD cmd: [$SSD_ARG]"
  fi
fi


if [ "$PASS_CMD" = "run" ] || [ "$PASS_CMD" = "parse" ]; then
  JOB_SCALE="$3"

  if [ "$JOB_SCALE" != "local" -a "$JOB_SCALE" != "bake" -a "$JOB_SCALE" != "small" -a "$JOB_SCALE" != "large" ]; then
    fatal_error "Unknown second argument for $PASS_CMD cmd: [$JOB_SCALE]"
  fi
fi

echo "Entered cmd summary:
- Passed cmd: $PASS_CMD
- Cmd param-1: $JOB_TOOL
- Cmd param-2: $JOB_SCALE
- Cmd optional param: SSD=$LUSTRE_SSD

Environment settings:
- Email: $SB_EMAIL
- Account: $SB_ACCOUNT

Executing...
"

# Execute
# Export: BM_CMD,BM_TYPE,BM_SCALE,BM_SSD
export BM_CMD="$PASS_CMD"
export BM_TYPE="$JOB_TOOL"
export BM_SCALE="$JOB_SCALE"
export BM_SSD="$LUSTRE_SSD"

. $BM_DIRNAME/include/vars.in.sh

# example: CMD:run TYPE:ior ARGS:local
if [ "$BM_CMD" = "run" ]; then
  . $BM_DIRNAME/jobs/submission.in.sh

  case $BM_TYPE in
    ior)
      ;;
    lsmio)
      ;;
    lmp)
      ;;
    *)
      fatal_error "Uknown $BM_CMD parameter: $BM_TYPE."
      ;;
  esac

  if [ "$BM_SCALE" = "local" ]; then
    run_local_job $BM_TYPE
  elif [ "$BM_SCALE" = "bake" ]; then
    run_bake_job $BM_TYPE
  elif [ "$BM_SCALE" = "small" ]; then
    run_small_job $BM_TYPE
  elif [ "$BM_SCALE" = "large" ]; then
    run_large_job $BM_TYPE
  else
    fatal_error "Uknown $BM_CMD parameter: $BM_SCALE."
  fi
# example: CMD:parse TYPE:ior ARGS:local
elif [ "$BM_CMD" = "parse" ]; then
  . $BM_DIRNAME/include/dirs-vars.in.sh

  if [ "$BM_TYPE" = "ior" ]; then
    . $BM_DIRNAME/parse/ior-parse.sh
  elif [ "$BM_TYPE" = "lsmio" ]; then
    . $BM_DIRNAME/parse/lsmio-parse.sh
  elif [ "$BM_TYPE" = "lmp" ]; then
    . $BM_DIRNAME/parse/lmp-parse.sh
  else
    fatal_error "Uknown $BM_CMD parameter: $BM_TYPE."
  fi
elif [ "$BM_CMD" = "load-modules" ]; then
  . $BM_DIRNAME/include/load-modules.in.sh
  list_modules
else
  fatal_error "Unknown error at cmd execution."
fi


