#!/bin/sh -x

BM_SETUP="BASE"
#BM_SETUP="COLLECTIVE"
#BM_SETUP="HDF5"
#BM_SETUP="HDF5-C"
#BM_SETUP="REVERSE"
#BM_SETUP="FSYNC"

. $BM_DIRNAME/include/vars.in.sh
. $BM_DIRNAME/include/dirs-vars.in.sh
. $BM_DIRNAME/include/dirs-setup.in.sh
. $BM_DIRNAME/include/dirs-config.in.sh

. $BM_DIRNAME/jobs/ior-vars.in.sh
. $BM_DIRNAME/jobs/ior-setup.in.sh

. $BM_DIRNAME/include/load-modules.in.sh > $DIRS_LOG/load-modules-$SLURMD_NODENAME-$DS-$(( ctr+=1 )).log 2>&1

rf="$1"
bs="$2"

if [ "$bs" = "64K" ]; then
  sg="16384"
elif [ "$bs" = "1M" ]; then
  sg="1024"
else
  sg="128"
fi

if [ "$BM_SETUP" = "HDF5" ]; then
  $SB_BIN/ior -v -w -r -i=10 \
    -a HDF5 \
    -o $DIRS_BM_BASE/c$rf/b$bs/ior.hdf5 \
    -t=$bs -b=$bs -s=$sg \
    2>&1 | tee $IOR_DIR_OUTPUT/out-hdf5-$rf-$bs-${DS}-${BM_SLURM_UID}.txt.$(( ctr+=1 ))
elif [ "$BM_SETUP" = "HDF5-C" ]; then
  $SB_BIN/ior -v -w -r -i=10 \
    -c -a HDF5 \
    -o $DIRS_BM_BASE/c$rf/b$bs/ior-c.hdf5 \
    -t=$bs -b=$bs -s=$sg \
    2>&1 | tee $IOR_DIR_OUTPUT/out-hdf5c-$rf-$bs-${DS}-${BM_SLURM_UID}.txt.$(( ctr+=1 ))
elif [ "$BM_SETUP" = "COLLECTIVE" ]; then
  $SB_BIN/ior -v -w -r -i=10 \
    -c -a MPIIO \
    -o $DIRS_BM_BASE/c$rf/b$bs/ior-c.data \
    -t=$bs -b=$bs -s=$sg \
    2>&1 | tee $IOR_DIR_OUTPUT/out-collective-$rf-$bs-${DS}-${BM_SLURM_UID}.txt.$(( ctr+=1 ))
elif [ "$BM_SETUP" = "FSYNC" ]; then
  $SB_BIN/ior -v -w -r -i=10 \
    -e \
    -o $DIRS_BM_BASE/c$rf/b$bs/ior-fsync.data \
    -t=$bs -b=$bs -s=$sg \
    2>&1 | tee $IOR_DIR_OUTPUT/out-fsync-$rf-$bs-${DS}-${BM_SLURM_UID}.txt.$(( ctr+=1 ))
elif [ "$BM_SETUP" = "REVERSE" ]; then
  $SB_BIN/ior -v -w -r -i=10 \
    -C \
    -o $DIRS_BM_BASE/c$rf/b$bs/ior-reverse.data \
    -t=$bs -b=$bs -s=$sg \
    2>&1 | tee $IOR_DIR_OUTPUT/out-reverse-$rf-$bs-${DS}-${BM_SLURM_UID}.txt.$(( ctr+=1 ))
else
  $SB_BIN/ior -v -w -r -i=10 \
    -o $DIRS_BM_BASE/c$rf/b$bs/ior-base.data \
    -t=$bs -b=$bs -s=$sg \
    2>&1 | tee $IOR_DIR_OUTPUT/out-base-$rf-$bs-${DS}-${BM_SLURM_UID}.txt.$(( ctr+=1 ))
fi

