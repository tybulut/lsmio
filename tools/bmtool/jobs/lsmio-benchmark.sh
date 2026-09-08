#!/bin/sh -x

# No spaces allowed in BM_SETUP
: "${BM_SETUP:=NATIVE-M}"
#BM_SETUP="ADIOS-M"
#BM_SETUP="PLUGIN-M"
#BM_SETUP="ROCKSDB-M"
#BM_SETUP="LEVELDB-M"
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
. $BM_DIRNAME/jobs/lsmio-variants.in.sh

resolve_variant "$BM_VARIANT" || exit 1

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

case "$BM_SETUP" in
  *-M)
    MPI_FLAGS="-m -g"
    BASE_BACKEND="${BM_SETUP%-M}"
    BACKEND_TOKEN=$(echo "$BASE_BACKEND" | tr '[:upper:]' '[:lower:]')
    ;;
  MANAGER)
    MPI_FLAGS=""
    BASE_BACKEND="MANAGER"
    BACKEND_TOKEN="manager"
    ;;
  *)
    MPI_FLAGS=""
    BASE_BACKEND="$BM_SETUP"
    BACKEND_TOKEN="$(echo "$BASE_BACKEND" | tr '[:upper:]' '[:lower:]')-nompi"
    ;;
esac

if [ -n "$BM_VARIANT_TOKENS" ]; then
  INFIX="${BACKEND_TOKEN}-${BM_VARIANT_TOKENS}"
else
  INFIX="${BACKEND_TOKEN}"
fi

OUT_FILE="$DIRS_BM_BASE/c$rf/b$bs/lsmio-${BM_UNIQUE_UID}-${INFIX}.db"
LOG_FILE="$LSM_DIR_OUTPUT/out-${INFIX}-$rf-$bs-${DS}-${BM_UNIQUE_UID}.txt"

case "$BASE_BACKEND" in
  ADIOS)
    BIN_NAME="bm_adios"
    ;;
  PLUGIN)
    BIN_NAME="bm_adios"
    ;;
  NATIVE)
    BIN_NAME="bm_native"
    ;;
  ROCKSDB)
    BIN_NAME="bm_rocksdb"
    ;;
  LEVELDB)
    BIN_NAME="bm_leveldb"
    ;;
  MANAGER)
    BIN_NAME="bm_manager"
    ;;
  ENV)
    env | egrep 'SLURM|PBS|CRAY|AP' > "$LOG_FILE"
    exit 0
    ;;
  *)
    echo "Unknown backend in BM_SETUP: $BM_SETUP" >&2
    exit 1
    ;;
esac

if [ "$BASE_BACKEND" = "PLUGIN" ]; then
  PLUGIN_FLAG="--lsmio-plugin"
else
  PLUGIN_FLAG=""
fi

$SB_BIN/$BIN_NAME \
  $MPI_FLAGS \
  $PLUGIN_FLAG \
  $BM_VARIANT_FLAGS \
  -i 10 -o "$OUT_FILE" \
  --lsmio-ts "$bsb" --lsmio-bs "$bsb" --key-count "$sg" \
  2>&1 | tee "$LOG_FILE"

