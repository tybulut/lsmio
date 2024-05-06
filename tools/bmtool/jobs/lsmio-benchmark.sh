#!/bin/sh -x

# No spaces allowed in BM_SETUP
BM_SETUP="ADIOS-M"
#BM_SETUP="PLUGIN-M"
#BM_SETUP="ROCKSDB-M"
#BM_SETUP="ADIOS"
#BM_SETUP="PLUGIN"
#BM_SETUP="ROCKSDB"
#BM_SETUP="LEVELDB"
#BM_SETUP="ENV"
#BM_SETUP="MANAGER"

. $BM_DIRNAME/include/vars.in.sh
. $BM_DIRNAME/jobs/job-all.in.sh

. $BM_DIRNAME/include/dirs-vars.in.sh
. $BM_DIRNAME/include/dirs-setup.in.sh
. $BM_DIRNAME/include/dirs-config.in.sh

. $BM_DIRNAME/jobs/lsmio-vars.in.sh
. $BM_DIRNAME/jobs/lsmio-setup.in.sh

. $BM_DIRNAME/include/load-modules.in.sh > $DIRS_LOG/load-modules-$BM_NODENAME-$DS-$(( ctr+=1 )).log 2>&1

rf="$1"
bs="$2"

if [ "$bs" = "64K" ]; then
  bsb="65536"
  #sg="4096"
  sg="65536"
elif [ "$bs" = "1M" ]; then
  bsb="1048576"
  sg="4096"
else
  bsb="8388608"
  sg="1024"
fi

INFIX=`echo "$BM_SETUP" | tr '[:upper:]' '[:lower:]'`
OUT_FILE="$DIRS_BM_BASE/c$rf/b$bs/lsmio-${BM_UNIQUE_UID}-${INFIX}.db"
LOG_FILE="$LSM_DIR_OUTPUT/out-${INFIX}-$rf-$bs-${DS}-${BM_UNIQUE_UID}.txt"

if [ "$BM_SETUP" = "ADIOS-M" ]; then
  $SB_BIN/bm_adios -m -g \
    -i 10 -o $OUT_FILE \
    --lsmio-ts $bsb --lsmio-bs $bsb --key-count $sg \
    2>&1 | tee $LOG_FILE
elif [ "$BM_SETUP" = "PLUGIN-M" ]; then
  $SB_BIN/bm_adios -m -g \
    --lsmio-plugin \
    -i 10 -o $OUT_FILE \
    --lsmio-ts $bsb --lsmio-bs $bsb --key-count $sg \
    2>&1 | tee $LOG_FILE
elif [ "$BM_SETUP" = "ROCKSDB-M" ]; then
  $SB_BIN/bm_rocksdb -m -g \
    -i 10 -o $OUT_FILE \
    --lsmio-ts $bsb --lsmio-bs $bsb --key-count $sg \
    2>&1 | tee $LOG_FILE
elif [ "$BM_SETUP" = "ADIOS" ]; then
  $SB_BIN/bm_adios -i 10 -o $OUT_FILE \
    --lsmio-ts $bsb --lsmio-bs $bsb --key-count $sg \
    2>&1 | tee $LOG_FILE
elif [ "$BM_SETUP" = "PLUGIN" ]; then
  $SB_BIN/bm_adios -i 10 -o $OUT_FILE \
    --lsmio-plugin \
    --lsmio-ts $bsb --lsmio-bs $bsb --key-count $sg \
    2>&1 | tee $LOG_FILE
elif [ "$BM_SETUP" = "ROCKSDB" ]; then
  $SB_BIN/bm_rocksdb -i 10 -o $OUT_FILE \
    --lsmio-ts $bsb --lsmio-bs $bsb --key-count $sg \
    2>&1 | tee $LOG_FILE
elif [ "$BM_SETUP" = "LEVELDB" ]; then
  $SB_BIN/bm_leveldb -i 10 -o $OUT_FILE \
    --lsmio-ts $bsb --lsmio-bs $bsb --key-count $sg \
    2>&1 | tee $LOG_FILE
elif [ "$BM_SETUP" = "MANAGER" ]; then
  $SB_BIN/bm_manager -i 10 -o $OUT_FILE \
    --lsmio-ts $bsb --lsmio-bs $bsb --key-count $sg \
    2>&1 | tee $LOG_FILE
else
  env | egrep 'SLURM|PBS|CRAY|AP' > $LOG_FILE
fi

