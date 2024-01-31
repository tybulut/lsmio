#!/bin/sh -x

BM_SETUP="ADIOS-M"
#BM_SETUP="ROCKSDB-M"
#BM_SETUP="PLUGIN-M"
#BM_SETUP="ADIOS"
#BM_SETUP="ROCKSDB"
#BM_SETUP="PLUGIN"
#BM_SETUP="LEVELDB"
#BM_SETUP="ENV"
#BM_SETUP="MANAGER"

. $BM_DIRNAME/include/vars.in.sh
. $BM_DIRNAME/include/dirs-vars.in.sh
. $BM_DIRNAME/include/dirs-setup.in.sh
. $BM_DIRNAME/include/dirs-config.in.sh

. $BM_DIRNAME/jobs/lsmio-vars.in.sh
. $BM_DIRNAME/jobs/lsmio-setup.in.sh

. $BM_DIRNAME/include/load-modules.in.sh > $DIRS_LOG/load-modules-$SLURMD_NODENAME-$DS-$(( ctr+=1 )).log 2>&1

rf="$1"
bs="$2"

if [ "$bs" = "64K" ]; then
  bsb="65536"
  sg="16384"
elif [ "$bs" = "1M" ]; then
  bsb="1048576"
  sg="16384"
else
  bsb="8388608"
  sg="16384"
fi

if [ "$BM_SETUP" = "ROCKSDB" ]; then
  $SB_BIN/bm_rocksdb -i 10 \
    -o $DIRS_BM_BASE/c$rf/b$bs/lsmio-${BM_SLURM_UID}-rocks.db \
    --lsmio-ts $bsb --lsmio-bs $bsb --key-count $sg \
    2>&1 | tee $LSM_DIR_OUTPUT/out-rocksdb-$rf-$bs-${DS}-${BM_SLURM_UID}.txt.$(( ctr+=1 ))
elif [ "$BM_SETUP" = "ROCKSDB-M" ]; then
  $SB_BIN/bm_rocksdb -i 10 \
    -o $DIRS_BM_BASE/c$rf/b$bs/lsmio-${BM_SLURM_UID}-rocks.db -m \
    --lsmio-ts $bsb --lsmio-bs $bsb --key-count $sg \
    2>&1 | tee $LSM_DIR_OUTPUT/out-rocksdb-$rf-$bs-${DS}-${BM_SLURM_UID}.txt.$(( ctr+=1 ))
elif [ "$BM_SETUP" = "LEVELDB" ]; then
  $SB_BIN/bm_leveldb -v -i 10 \
    -o $DIRS_BM_BASE/c$rf/b$bs/lsmio-${BM_SLURM_UID}-level.db \
    --lsmio-ts $bsb --lsmio-bs $bsb --key-count $sg \
    2>&1 | tee $LSM_DIR_OUTPUT/out-rocksdb-$rf-$bs-${DS}-${BM_SLURM_UID}.txt.$(( ctr+=1 ))
elif [ "$BM_SETUP" = "MANAGER" ]; then
  $SB_BIN/bm_manager -v -i 10 \
    -o $DIRS_BM_BASE/c$rf/b$bs/lsmio-${BM_SLURM_UID}-manager.db \
    --lsmio-ts $bsb --lsmio-bs $bsb --key-count $sg \
    2>&1 | tee $LSM_DIR_OUTPUT/out-rocksdb-$rf-$bs-${DS}-${BM_SLURM_UID}.txt.$(( ctr+=1 ))
elif [ "$BM_SETUP" = "ADIOS" ]; then
  $SB_BIN/bm_adios -i 10 \
    -o $DIRS_BM_BASE/c$rf/b$bs/lsmio-${BM_SLURM_UID}-adios.bp \
    --lsmio-ts $bsb --lsmio-bs $bsb --key-count $sg \
    2>&1 | tee $LSM_DIR_OUTPUT/out-adios-$rf-$bs-${DS}-${BM_SLURM_UID}.txt.$(( ctr+=1 ))
elif [ "$BM_SETUP" = "ADIOS-M" ]; then
  $SB_BIN/bm_adios -i 10 \
    -o $DIRS_BM_BASE/c$rf/b$bs/lsmio-${BM_SLURM_UID}-adios.bp -m \
    --lsmio-ts $bsb --lsmio-bs $bsb --key-count $sg \
    2>&1 | tee $LSM_DIR_OUTPUT/out-adios-$rf-$bs-${DS}-${BM_SLURM_UID}.txt.$(( ctr+=1 ))
elif [ "$BM_SETUP" = "PLUGIN" ]; then
  $SB_BIN/bm_adios -i 10 \
    --lsmio-plugin \
    -o $DIRS_BM_BASE/c$rf/b$bs/lsmio-${BM_SLURM_UID}-plugin.db \
    --lsmio-ts $bsb --lsmio-bs $bsb --key-count $sg \
    2>&1 | tee $LSM_DIR_OUTPUT/out-plugin-$rf-$bs-${DS}-${BM_SLURM_UID}.txt.$(( ctr+=1 ))
elif [ "$BM_SETUP" = "PLUGIN-M" ]; then
  $SB_BIN/bm_adios -i 10 \
    --lsmio-plugin \
    -o $DIRS_BM_BASE/c$rf/b$bs/lsmio-${BM_SLURM_UID}-plugin.db -m \
    --lsmio-ts $bsb --lsmio-bs $bsb --key-count $sg \
    2>&1 | tee $LSM_DIR_OUTPUT/out-plugin-$rf-$bs-${DS}-${BM_SLURM_UID}.txt.$(( ctr+=1 ))
else
  env | grep SLURM > $LSM_DIR_OUTPUT/env-${DS}-${BM_SLURM_UID}.txt
fi

