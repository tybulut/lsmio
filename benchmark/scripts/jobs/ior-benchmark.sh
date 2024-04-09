#!/bin/sh -x

BM_SETUP="BASE"
#BM_SETUP="COLLECTIVE"
#BM_SETUP="HDF5"
#BM_SETUP="HDF5-C"
#BM_SETUP="REVERSE"
#BM_SETUP="FSYNC"

. $BM_DIRNAME/include/vars.in.sh
. $BM_DIRNAME/jobs/all-vars.in.sh

. $BM_DIRNAME/include/dirs-vars.in.sh
. $BM_DIRNAME/include/dirs-setup.in.sh
. $BM_DIRNAME/include/dirs-config.in.sh

. $BM_DIRNAME/jobs/ior-vars.in.sh
. $BM_DIRNAME/jobs/ior-setup.in.sh

. $BM_DIRNAME/include/load-modules.in.sh > $DIRS_LOG/load-modules-$BM_NODENAME-$DS-$(( ctr+=1 )).log 2>&1

rf="$1"
bs="$2"

if [ "$bs" = "64K" ]; then
  sg="16384"
elif [ "$bs" = "1M" ]; then
  sg="1024"
else
  sg="128"
fi

INFIX=`echo "$BM_SETUP" | tr '[:upper:]' '[:lower:]'`
OUT_FILE="$DIRS_BM_BASE/c$rf/b$bs/ior.$INFIX"
LOG_FILE="$IOR_DIR_OUTPUT/out-${INFIX}-$rf-$bs-${DS}-${BM_UNIQUE_UID}.txt"

if [ "$BM_SETUP" = "HDF5" ]; then
  $SB_BIN/ior -v -w -r -i=10 \
    -a HDF5 -o $OUT_FILE \
    -t=$bs -b=$bs -s=$sg \
    2>&1 | tee $LOG_FILE
elif [ "$BM_SETUP" = "HDF5-C" ]; then
  $SB_BIN/ior -v -w -r -i=10 \
    -c -a HDF5 -o $OUT_FILE \
    -t=$bs -b=$bs -s=$sg \
    2>&1 | tee $LOG_FILE
elif [ "$BM_SETUP" = "COLLECTIVE" ]; then
  $SB_BIN/ior -v -w -r -i=10 \
    -c -a MPIIO -o $OUT_FILE \
    -t=$bs -b=$bs -s=$sg \
    2>&1 | tee $LOG_FILE
elif [ "$BM_SETUP" = "FSYNC" ]; then
  $SB_BIN/ior -v -w -r -i=10 \
    -e -o $OUT_FILE \
    -t=$bs -b=$bs -s=$sg \
    2>&1 | tee $LOG_FILE
elif [ "$BM_SETUP" = "REVERSE" ]; then
  $SB_BIN/ior -v -w -r -i=10 \
    -C -o $OUT_FILE \
    -t=$bs -b=$bs -s=$sg \
    2>&1 | tee $LOG_FILE
else
  $SB_BIN/ior -v -w -r -i=10 \
    -o $OUT_FILE \
    -t=$bs -b=$bs -s=$sg \
    2>&1 | tee $LOG_FILE
fi

