#

. $BM_DIRNAME/include/vars.in.sh
. $BM_DIRNAME/include/dirs-vars.in.sh
. $BM_DIRNAME/include/dirs-cleanup.in.sh

. $BM_DIRNAME/include/dirs-setup.in.sh
. $BM_DIRNAME/include/dirs-config.in.sh 

if [ "$BM_TYPE" = "ior" ]; then
  JOB_BIN="$BM_DIRNAME/jobs/ior-benchmark.sh"
  . $BM_DIRNAME/jobs/ior-vars.in.sh
  . $BM_DIRNAME/jobs/ior-setup.in.sh
elif [ "$BM_TYPE" = "lsmio" ]; then
  JOB_BIN="$BM_DIRNAME/jobs/lsmio-benchmark.sh"
  . $BM_DIRNAME/jobs/lsmio-vars.in.sh
  rm -rf "$LSM_DIR_OBASE" && mkdir -p "$LSM_DIR_OBASE"
  . $BM_DIRNAME/jobs/lsmio-setup.in.sh
  . $BM_DIRNAME/jobs/lsmio-variants.in.sh
elif [ "$BM_TYPE" = "lmp" ]; then
  JOB_BIN="$BM_DIRNAME/jobs/lmp-benchmark.sh"
  . $BM_DIRNAME/jobs/lmp-vars.in.sh
  . $BM_DIRNAME/jobs/lmp-setup.in.sh
else
  echo "Please pass either ior, lmp or lsmio as argument."
  exit
fi

# Ensure fatal_error fallback is defined (INV-PAIR-6)
if ! command -v fatal_error >/dev/null 2>&1; then
  fatal_error() {
    echo "ERROR: $1" >&2
    exit 1
  }
fi

# Scope prerequisites: load variant resolver if lsmio benchmark
if [ "$BM_TYPE" = "lsmio" ]; then
  . $BM_DIRNAME/jobs/lsmio-variants.in.sh
fi

run_matrix_workload() {
  for rf in 4 16; do
    for bs in 1M 64K 8M; do
      if [ "$BM_TYPE" = "lmp" ]; then
        rm ~/scratch/benchmark/lmp/outputs/*
        cp -r lmp-reaxff $DIRS_BM_BASE/c$rf/b$bs/
      fi

      if [ "$HPC_MANAGER" = "slurm" ]; then
        if [ "$HPC_ENV" = "archer2" ]; then
          srun -p standard --export=ALL ${JOB_BIN} $rf $bs
        else
          srun --export=ALL ${JOB_BIN} $rf $bs
        fi
      elif [ "$HPC_MANAGER" = "pbs" ]; then
        aprun -n $BM_NUM_TASKS -N $BM_NUM_CORES ${JOB_BIN} $rf $bs
      else
        unknown_hpc_environment
      fi

      sleep 3
    done
  done
}

if [ "$BM_VERSIONED" = "yes" ] && [ "$BM_TYPE" = "lsmio" ]; then
  # -------------------------------------------------------------------------
  # Phase 1: Golden Reference Baseline (bm_native:main -> role :base)
  # -------------------------------------------------------------------------
  if [ ! -x "$SB_BIN/bm_native:main" ]; then
    fatal_error "Reference binary $SB_BIN/bm_native:main not found. Build and install reference baseline via: ./build.sh install:main"
  fi

  echo "=== [Intra-Allocation] Step 1: Running Reference Main Baseline (bm_native:main) ==="
  BM_BIN_NAME="bm_native:main"
  export BM_BIN_NAME
  BM_VARIANT=""
  export BM_VARIANT
  . $BM_DIRNAME/include/dirs-cleanup.in.sh
  rm -rf "$LSM_DIR_OBASE" && mkdir -p "$LSM_DIR_OBASE"
  . $BM_DIRNAME/jobs/lsmio-setup.in.sh
  run_matrix_workload

  if [ -f "$BM_DIRNAME/parse/lsmio-parse.sh" ]; then
    . $BM_DIRNAME/parse/lsmio-parse.sh
  fi

  STAGING_BASE="$BM_PATH/lsmio/outputs-baseline-staged"
  rm -rf "$STAGING_BASE"
  mv "$LSM_DIR_OBASE" "$STAGING_BASE"
  mkdir -p "$LSM_DIR_OBASE"

  # -------------------------------------------------------------------------
  # Phase 2: Active Target Baseline (bm_native -> role :run)
  # -------------------------------------------------------------------------
  if [ ! -x "$SB_BIN/bm_native" ]; then
    fatal_error "Active target binary $SB_BIN/bm_native not found. Build and install via: ./build.sh install"
  fi

  GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
  GIT_HASH=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
  SANITIZED_BRANCH=$(echo "$GIT_BRANCH" | sed -E 's/[^a-zA-Z0-9_-]/-/g')

  if [ -n "$EXPANDED_VARIANTS" ] && [ "$EXPANDED_VARIANTS" != "default" ] && [ "$EXPANDED_VARIANTS" != "base" ]; then
    _rem="$EXPANDED_VARIANTS"
    while [ -n "$_rem" ]; do
      case "$_rem" in
        *,*) _v="${_rem%%,*}"; _rem="${_rem#*,}" ;;
        *) _v="$_rem"; _rem="" ;;
      esac
      [ "$_v" != "default" ] && [ "$_v" != "base" ] || continue
      VERSION_VARIANT="version-${SANITIZED_BRANCH}-${GIT_HASH}-${_v}"
      ARM_ID="$(bm_resolve_arm_id "$BM_SETUP" "$VERSION_VARIANT")" || ARM_ID="native-${VERSION_VARIANT}"
      TARGET_RUN="${BM_ARCHIVE_DEST}/outputs-${ARM_ID}:run"
      if [ "$BM_RESUME" = "yes" ] && [ -d "$TARGET_RUN" ]; then
        echo "[RESUME] Skipping versioned variant '${_v}'"
        continue
      fi
      echo "=== [Intra-Allocation] Step 2: Running Active Target Versioned Variant '${_v}' (ARM_ID: ${ARM_ID}) ==="
      BM_BIN_NAME="bm_native"
      export BM_BIN_NAME
      BM_VARIANT="$_v"
      export BM_VARIANT
      . $BM_DIRNAME/include/dirs-cleanup.in.sh
      . $BM_DIRNAME/jobs/lsmio-setup.in.sh
      run_matrix_workload

      if [ -f "$BM_DIRNAME/parse/lsmio-parse.sh" ]; then
        . $BM_DIRNAME/parse/lsmio-parse.sh
      fi

      PAIR_SUFFIX=""
      BASE_RUN="${BM_ARCHIVE_DEST}/outputs-${ARM_ID}:run"
      BASE_BASE="${BM_ARCHIVE_DEST}/outputs-${ARM_ID}:base"
      if [ -e "$BASE_RUN" ] || [ -e "$BASE_BASE" ]; then
        k=1
        while [ -e "${BASE_RUN}-${k}" ] || [ -e "${BASE_BASE}-${k}" ]; do
          k=$(( k + 1 ))
        done
        PAIR_SUFFIX="-$k"
      fi

      BM_ROLE="run" ARM_ID="$ARM_ID" BM_PAIR_SUFFIX="$PAIR_SUFFIX" . $BM_DIRNAME/include/archive.in.sh

      echo "=== [Intra-Allocation] Step 3: Archiving Reference Baseline for '${_v}' (Role: base) ==="
      rm -rf "$LSM_DIR_OBASE"
      cp -Rp "$STAGING_BASE" "$LSM_DIR_OBASE"
      BM_ROLE="base" ARM_ID="$ARM_ID" BM_PAIR_SUFFIX="$PAIR_SUFFIX" . $BM_DIRNAME/include/archive.in.sh

      . $BM_DIRNAME/include/dirs-cleanup.in.sh
    done
    rm -rf "$STAGING_BASE"
  else
    VERSION_VARIANT="version-${SANITIZED_BRANCH}-${GIT_HASH}"
    ARM_ID="$(bm_resolve_arm_id "$BM_SETUP" "$VERSION_VARIANT")" || ARM_ID="native-${VERSION_VARIANT}"

    echo "=== [Intra-Allocation] Step 2: Running Active Target Baseline (bm_native) (ARM_ID: ${ARM_ID}) ==="
    BM_BIN_NAME="bm_native"
    export BM_BIN_NAME
    BM_VARIANT="$VERSION_VARIANT"
    export BM_VARIANT
    . $BM_DIRNAME/include/dirs-cleanup.in.sh
    . $BM_DIRNAME/jobs/lsmio-setup.in.sh
    run_matrix_workload

    if [ -f "$BM_DIRNAME/parse/lsmio-parse.sh" ]; then
      . $BM_DIRNAME/parse/lsmio-parse.sh
    fi

    PAIR_SUFFIX=""
    BASE_RUN="${BM_ARCHIVE_DEST}/outputs-${ARM_ID}:run"
    BASE_BASE="${BM_ARCHIVE_DEST}/outputs-${ARM_ID}:base"
    if [ -e "$BASE_RUN" ] || [ -e "$BASE_BASE" ]; then
      k=1
      while [ -e "${BASE_RUN}-${k}" ] || [ -e "${BASE_BASE}-${k}" ]; do
        k=$(( k + 1 ))
      done
      PAIR_SUFFIX="-$k"
    fi

    BM_ROLE="run" ARM_ID="$ARM_ID" BM_PAIR_SUFFIX="$PAIR_SUFFIX" . $BM_DIRNAME/include/archive.in.sh

    # -------------------------------------------------------------------------
    # Phase 3: Restore & Archive Golden Reference (Role :base)
    # -------------------------------------------------------------------------
    echo "=== [Intra-Allocation] Step 3: Archiving Reference Baseline (Role: base) ==="
    rm -rf "$LSM_DIR_OBASE"
    cp -Rp "$STAGING_BASE" "$LSM_DIR_OBASE"
    BM_ROLE="base" ARM_ID="$ARM_ID" BM_PAIR_SUFFIX="$PAIR_SUFFIX" . $BM_DIRNAME/include/archive.in.sh

    rm -rf "$STAGING_BASE"
    . $BM_DIRNAME/include/dirs-cleanup.in.sh
  fi

elif [ "$BM_PAIRED_RUN" = "yes" ] && [ "$BM_TYPE" = "lsmio" ]; then
  echo "=== [Intra-Allocation] Step 1: Running Shared Pre-Baseline ==="
  BM_VARIANT=""
  export BM_VARIANT
  . $BM_DIRNAME/include/dirs-cleanup.in.sh
  rm -rf "$LSM_DIR_OBASE" && mkdir -p "$LSM_DIR_OBASE"
  . $BM_DIRNAME/jobs/lsmio-setup.in.sh
  run_matrix_workload

  # Aggregate metrics and generate lsm-report.csv prior to staging
  if [ -f "$BM_DIRNAME/parse/lsmio-parse.sh" ]; then
    . $BM_DIRNAME/parse/lsmio-parse.sh
  fi

  STAGING_BASE="$BM_PATH/lsmio/outputs-baseline-staged"
  rm -rf "$STAGING_BASE"
  mv "$LSM_DIR_OBASE" "$STAGING_BASE"
  mkdir -p "$LSM_DIR_OBASE"

  _rem="$EXPANDED_VARIANTS"
  while [ -n "$_rem" ]; do
    case "$_rem" in
      *,*) _v="${_rem%%,*}"; _rem="${_rem#*,}" ;;
      *) _v="$_rem"; _rem="" ;;
    esac
    [ "$_v" != "default" ] && [ "$_v" != "base" ] || continue
    ARM_ID="$(bm_resolve_arm_id "$BM_SETUP" "$_v")" || fatal_error "Failed to derive Arm ID for [$_v]"
    TARGET_RUN="${BM_ARCHIVE_DEST}/outputs-${ARM_ID}:run"
    if [ "$BM_RESUME" = "yes" ] && [ -d "$TARGET_RUN" ]; then
      echo "[RESUME] Skipping variant '${_v}'"
      continue
    fi
    echo "=== [Intra-Allocation] Running variant '${_v}' (ARM_ID: ${ARM_ID}) ==="
    . $BM_DIRNAME/include/dirs-cleanup.in.sh
    BM_VARIANT="$_v"
    export BM_VARIANT
    . $BM_DIRNAME/jobs/lsmio-setup.in.sh
    run_matrix_workload

    # Aggregate metrics and generate lsm-report.csv prior to archiving variant run
    if [ -f "$BM_DIRNAME/parse/lsmio-parse.sh" ]; then
      . $BM_DIRNAME/parse/lsmio-parse.sh
    fi

    PAIR_SUFFIX=""
    BASE_RUN="${BM_ARCHIVE_DEST}/outputs-${ARM_ID}:run"
    BASE_BASE="${BM_ARCHIVE_DEST}/outputs-${ARM_ID}:base"
    if [ -e "$BASE_RUN" ] || [ -e "$BASE_BASE" ]; then
      k=1
      while [ -e "${BASE_RUN}-${k}" ] || [ -e "${BASE_BASE}-${k}" ]; do
        k=$(( k + 1 ))
      done
      PAIR_SUFFIX="-$k"
    fi

    BM_ROLE="run" BM_PAIR_SUFFIX="$PAIR_SUFFIX" . $BM_DIRNAME/include/archive.in.sh
    rm -rf "$LSM_DIR_OBASE"
    cp -Rp "$STAGING_BASE" "$LSM_DIR_OBASE"
    BM_ROLE="base" BM_PAIR_SUFFIX="$PAIR_SUFFIX" . $BM_DIRNAME/include/archive.in.sh
  done

  rm -rf "$STAGING_BASE"
  . $BM_DIRNAME/include/dirs-cleanup.in.sh
else
  run_matrix_workload
  if [ "$BM_TYPE" = "lsmio" ] && [ -f "$BM_DIRNAME/parse/lsmio-parse.sh" ]; then
    . $BM_DIRNAME/parse/lsmio-parse.sh
  fi
fi


