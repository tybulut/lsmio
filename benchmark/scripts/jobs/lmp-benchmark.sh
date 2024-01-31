#!/bin/sh -x

BM_SETUP="LSMIO"
#BM_SETUP="LSMIO-MMAP"
#BM_SETUP="FS"

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
  bsb="65536"
  sg="4096"
elif [ "$bs" = "1M" ]; then
  bsb="1048576"
  sg="4096"
else
  bsb="8388608"
  sg="4096"
fi

# 1 2 4 8 16 24 32 40 48
if [ "$SLURM_JOB_NUM_NODES" == 1 ]; then
  REP=4 # 6 minutes
  LSMIO_BUF_MB=32 # 18 MB
elif [ "$SLURM_JOB_NUM_NODES" == 2 ]; then
  REP=5 # ? minutes [4 was 3 minutes]
  LSMIO_BUF_MB=32 # 35 MB
elif [ "$SLURM_JOB_NUM_NODES" == 4 ]; then
  REP=6 # 6 minutes
  LSMIO_BUF_MB=64 # 60 MB
elif [ "$SLURM_JOB_NUM_NODES" == 8 ]; then
  REP=8 # ? minutes [12 was 21 minutes]
  LSMIO_BUF_MB=128 # 143 MB
elif [ "$SLURM_JOB_NUM_NODES" == 16 ]; then
  REP=10 # ? minutes [24 was 28+ minutes]
  LSMIO_BUF_MB=256 # 278 MB
elif [ "$SLURM_JOB_NUM_NODES" == 24 ]; then
  REP=12 # 7 minutes 
  LSMIO_BUF_MB=512 # 481 MB
elif [ "$SLURM_JOB_NUM_NODES" == 32 ]; then
  REP=14 # 9 minutes
  LSMIO_BUF_MB=1024 # 764 MB
elif [ "$SLURM_JOB_NUM_NODES" == 40 ]; then
  REP=15 # ? minutes [16 was 11 minutes]
  LSMIO_BUF_MB=1024 # 939 MB
elif [ "$SLURM_JOB_NUM_NODES" == 48 ]; then
  REP=16 # 9 minutes
  LSMIO_BUF_MB=1024 # 1140 MB
else
  echo "Error: Unknown number of slurm jobs: $SLURM_JOB_NUM_NODES"
  exit 1
fi

# If needs to be set the same for all
#LSMIO_BUF_MB=512

cd $DIRS_BM_BASE/c$rf/b$bs/lmp-reaxff

if [ "$BM_SETUP" = "LSMIO" ]; then
  $SB_BIN/lmp  -in in.reaxc.hns \
    -v x $REP -v y $REP -v z $REP \
    -lsmio-buf-size-mb $LSMIO_BUF_MB \
    2>&1 | tee $LMP_DIR_OUTPUT/out-lmp-lsmio-$rf-$bs-${DS}-${BM_SLURM_UID}.txt.$(( ctr+=1 ))
elif [ "$BM_SETUP" = "LSMIO-MMAP" ]; then
  $SB_BIN/lmp  -in in.reaxc.hns \
    -v x $REP -v y $REP -v z $REP \
    -lsmio-mmap \
    -lsmio-buf-size-mb $LSMIO_BUF_MB \
    2>&1 | tee $LMP_DIR_OUTPUT/out-lmp-lsmio-$rf-$bs-${DS}-${BM_SLURM_UID}.txt.$(( ctr+=1 ))
elif [ "$BM_SETUP" = "FS" ]; then
  $SB_BIN/lmp  -in in.reaxc.hns \
    -v x $REP -v y $REP -v z $REP \
    -lsmio-fallback \
    2>&1 | tee $LMP_DIR_OUTPUT/out-lmp-fs-$rf-$bs-${DS}-${BM_SLURM_UID}.txt.$(( ctr+=1 ))
else
  env | grep SLURM > $LMP_DIR_OUTPUT/env-${DS}-${BM_SLURM_UID}.txt
fi

