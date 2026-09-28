#

# One date for the whole job: vars.in.sh takes DS from BM_JOB_DS, and srun --export=ALL
# passes it to every rank. Unset first, so a value from the submitting shell is not reused
unset BM_JOB_DS
. $BM_DIRNAME/include/vars.in.sh
BM_JOB_DS="$DS"
export BM_JOB_DS
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
  if [ -n "$LSM_DIR_IDX" ] && [ "$BM_SCALE" != "variants" ]; then
    rm -rf "${LSM_DIR_OBASE}/${LSM_DIR_IDX}" && mkdir -p "$LSM_DIR_OBASE"
  else
    rm -rf "$LSM_DIR_OBASE" && mkdir -p "$LSM_DIR_OBASE"
  fi
  # Written only when this job finishes cleanly (plain branch below); bmtool's --archive
  # step checks it, since it cannot see whether the job failed, timed out or was cancelled
  BM_JOB_OK_MARKER="$LSM_DIR_OBASE/.bm-job-ok"
  rm -f "$BM_JOB_OK_MARKER"
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

# Failed steps: BM_MATRIX_FAILED counts them in the last run_matrix_workload call;
# BM_JOB_FAILED stays 1 once any step failed, and the job then exits 1 at the end
BM_JOB_FAILED=0

# Move a failed run's live outputs (SRC) out of the archive and the parsers' reach to
# $BM_PATH/<ior|lmp|lsmio>/outputs-failed/NAME[-k]: --resume then reruns it, and the
# partial logs stay available for troubleshooting
bm_keep_failed_outputs() {
  _kf_src="$1"
  _kf_dest="$BM_PATH/$BM_TYPE/outputs-failed/$2"
  # An empty run index would name the whole outputs tree, other runs included
  case "$_kf_src" in
    */) fatal_error "Cannot locate the failed run's outputs (empty run index): $_kf_src" ;;
  esac
  if [ -e "$_kf_dest" ]; then
    _kf_k=1
    while [ -e "${_kf_dest}-${_kf_k}" ]; do
      _kf_k=$(( _kf_k + 1 ))
    done
    _kf_dest="${_kf_dest}-${_kf_k}"
  fi
  echo "WARNING: $BM_MATRIX_FAILED benchmark step(s) failed; keeping this run out of the reports and archive" >&2
  if [ -d "$_kf_src" ]; then
    # Left in place, the failed logs would be parsed or archived with the next successful run
    mkdir -p "$(dirname "$_kf_dest")" && mv -- "$_kf_src" "$_kf_dest" \
      || fatal_error "Cannot move failed outputs $_kf_src to $_kf_dest"
    echo "WARNING: failed outputs kept in $_kf_dest" >&2
  else
    echo "WARNING: no outputs found at $_kf_src" >&2
  fi
}

run_matrix_workload() {
  BM_MATRIX_FAILED=0
  for rf in 4 16; do
    for bs in 1M 64K 8M; do
      if [ "$BM_TYPE" = "lmp" ]; then
        rm ~/scratch/benchmark/lmp/outputs/*
        cp -r lmp-reaxff $DIRS_BM_BASE/c$rf/b$bs/
      fi

      # --kill-on-bad-exit: one failed rank ends the step; otherwise the
      # surviving ranks block in MPI until the job hits its time limit
      if [ "$HPC_MANAGER" = "slurm" ]; then
        if [ "$HPC_ENV" = "archer2" ]; then
          srun -p standard --kill-on-bad-exit=1 --export=ALL ${JOB_BIN} $rf $bs
        else
          srun --kill-on-bad-exit=1 --export=ALL ${JOB_BIN} $rf $bs
        fi
      elif [ "$HPC_MANAGER" = "pbs" ]; then
        aprun -n $BM_NUM_TASKS -N $BM_NUM_CORES ${JOB_BIN} $rf $bs
      else
        unknown_hpc_environment
      fi
      _rmw_rc=$?
      if [ "$_rmw_rc" -ne 0 ]; then
        echo "WARNING: benchmark step c$rf/b$bs failed with exit code $_rmw_rc" >&2
        BM_MATRIX_FAILED=$(( BM_MATRIX_FAILED + 1 ))
        BM_JOB_FAILED=1
      fi

      sleep 3

      # Free this point's data now so peak quota usage is one point, not six
      rm -rf -- "${DIRS_BM_BASE:?DIRS_BM_BASE is unset or empty}/c$rf/b$bs"/*
    done
  done
  [ "$BM_MATRIX_FAILED" -eq 0 ]
}

if [ "$BM_MODE" = "backends" ] && [ "$BM_TYPE" = "lsmio" ]; then
  # -------------------------------------------------------------------------
  # Multi-Backend Intra-Allocation Scaling Execution Loop (INV-BACKEND-1)
  # -------------------------------------------------------------------------
  if [ -n "$BM_NUM_NODES" ] && [ "$BM_NUM_NODES" -gt 0 ]; then
    _node_idx="$BM_NUM_NODES"
  elif [ -n "$BM_NUM_CORES" ] && [ "$BM_NUM_CORES" -gt 0 ]; then
    _node_idx=$(( BM_NUM_TASKS / BM_NUM_CORES ))
  elif [ "$BM_SCALE" = "large" ]; then
    _node_idx=$(( BM_NUM_TASKS / 4 ))
  else
    _node_idx="$BM_NUM_TASKS"
  fi

  # Resolve BM_ARCHIVE_DEST inside the allocation (same rules as bmtool)
  . $BM_DIRNAME/include/archive-dest.in.sh
  bm_resolve_archive_dest

  # Check every backend's binary, and the LSMIO plugin library, before running
  # any backend, so a missing one fails fast instead of after hours of runs
  _backend_tokens="$BM_BACKENDS"
  while [ -n "$_backend_tokens" ]; do
    _b="${_backend_tokens%%,*}"
    case "$_backend_tokens" in
      *,*) _backend_tokens="${_backend_tokens#*,}" ;;
      *) _backend_tokens="" ;;
    esac
    case "$_b" in
      adios2|adios|plugin) BM_BIN_NAME="bm_adios" ;;
      native) BM_BIN_NAME="bm_native" ;;
      rocksdb) BM_BIN_NAME="bm_rocksdb" ;;
      leveldb) BM_BIN_NAME="bm_leveldb" ;;
      "") continue ;;
      *) fatal_error "Unsupported backend for backends scaling: [$_b]" ;;
    esac
    if [ ! -x "$SB_BIN/$BM_BIN_NAME" ]; then
      fatal_error "Backend binary $SB_BIN/$BM_BIN_NAME not found or not executable. Please verify build and install."
    fi
    # bm_adios --lsmio-plugin loads liblsmio_adios from ADIOS2_PLUGIN_PATH (include/vars.in.sh)
    if [ "$_b" = "plugin" ] && [ ! -e "$ADIOS2_PLUGIN_PATH/liblsmio_adios.so" ] \
      && [ ! -e "$ADIOS2_PLUGIN_PATH/liblsmio_adios.dylib" ]; then
      fatal_error "LSMIO ADIOS2 plugin liblsmio_adios not found in ADIOS2_PLUGIN_PATH=$ADIOS2_PLUGIN_PATH. Please verify build and install."
    fi
  done

  _backend_tokens="$BM_BACKENDS"
  while [ -n "$_backend_tokens" ]; do
    case "$_backend_tokens" in
      *,*)
        _b="${_backend_tokens%%,*}"
        _backend_tokens="${_backend_tokens#*,}"
        ;;
      *)
        _b="$_backend_tokens"
        _backend_tokens=""
        ;;
    esac
    [ -n "$_b" ] || continue

    case "$_b" in
      adios2|adios)
        BM_SETUP="ADIOS-M"
        BM_BIN_NAME="bm_adios"
        ARM_ID="adios"
        ;;
      native)
        BM_SETUP="NATIVE-M"
        BM_BIN_NAME="bm_native"
        ARM_ID="native"
        ;;
      plugin)
        # ADIOS2 with the LSMIO engine plugin (bm_adios --lsmio-plugin)
        BM_SETUP="PLUGIN-M"
        BM_BIN_NAME="bm_adios"
        ARM_ID="plugin"
        ;;
      rocksdb)
        BM_SETUP="ROCKSDB-M"
        BM_BIN_NAME="bm_rocksdb"
        ARM_ID="rocksdb"
        ;;
      leveldb)
        BM_SETUP="LEVELDB-M"
        BM_BIN_NAME="bm_leveldb"
        ARM_ID="leveldb"
        ;;
      *)
        fatal_error "Unsupported backend for backends scaling: [$_b]"
        ;;
    esac

    TARGET_NODE_DIR="${BM_ARCHIVE_DEST}/outputs-${ARM_ID}/${_node_idx}"
    if [ "$BM_RESUME" = "yes" ] && [ -d "$TARGET_NODE_DIR" ]; then
      echo "[RESUME] Skipping backend '${_b}' on node ${_node_idx} (target directory exists: $TARGET_NODE_DIR)"
      continue
    fi

    echo "=== [Intra-Allocation] Running backend '${_b}' (ARM_ID: ${ARM_ID}) on node ${_node_idx} ==="
    # 1. Pre-execution Lustre OST Sanitization
    . $BM_DIRNAME/include/dirs-cleanup.in.sh

    export BM_BIN_NAME
    export BM_SETUP
    export ARM_ID
    BM_VARIANT=""
    export BM_VARIANT

    . $BM_DIRNAME/jobs/lsmio-setup.in.sh

    # 2. Execute Workload Matrix (rf in 4,16; bs in 1M,64K,8M)
    run_matrix_workload

    # 3. Stage Completed Task Outputs into Approach 2 Partitioned Archive
    #    (a backend with any failed step stays out of it, so --resume reruns it)
    if [ "$BM_MATRIX_FAILED" -ne 0 ]; then
      bm_keep_failed_outputs "${LSM_DIR_OBASE}/${LSM_DIR_IDX}" "outputs-${ARM_ID}/${_node_idx}"
    else
      mkdir -p "${BM_ARCHIVE_DEST}/outputs-${ARM_ID}"
      rm -rf "$TARGET_NODE_DIR"
      if [ -d "${LSM_DIR_OBASE}/${LSM_DIR_IDX}" ]; then
        if cp -Rp "${LSM_DIR_OBASE}/${LSM_DIR_IDX}" "$TARGET_NODE_DIR"; then
          rm -rf "${LSM_DIR_OBASE}/${LSM_DIR_IDX}"
        else
          echo "WARNING: Failed to copy ${LSM_DIR_OBASE}/${LSM_DIR_IDX} to $TARGET_NODE_DIR; preserving live directory" >&2
        fi
      fi
    fi

    # 4. Post-execution Lustre OST Sanitization
    . $BM_DIRNAME/include/dirs-cleanup.in.sh
  done

elif [ "$BM_VERSIONED" = "yes" ] && [ "$BM_TYPE" = "lsmio" ]; then
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
  if ! run_matrix_workload; then
    # Every variant is compared against this baseline: stop rather than archive bad pairs
    bm_keep_failed_outputs "$LSM_DIR_OBASE" "outputs-baseline-$DS"
    fatal_error "Baseline run failed; nothing archived"
  fi

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
      if ! run_matrix_workload; then
        # Neither role is archived, so --resume reruns this variant
        bm_keep_failed_outputs "$LSM_DIR_OBASE" "outputs-${ARM_ID}:run"
        mkdir -p "$LSM_DIR_OBASE"
        . $BM_DIRNAME/include/dirs-cleanup.in.sh
        continue
      fi

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
    if ! run_matrix_workload; then
      # Neither role is archived, so a rerun repeats this pair
      bm_keep_failed_outputs "$LSM_DIR_OBASE" "outputs-${ARM_ID}:run"
      mkdir -p "$LSM_DIR_OBASE"
    else
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

      # -----------------------------------------------------------------------
      # Phase 3: Restore & Archive Golden Reference (Role :base)
      # -----------------------------------------------------------------------
      echo "=== [Intra-Allocation] Step 3: Archiving Reference Baseline (Role: base) ==="
      rm -rf "$LSM_DIR_OBASE"
      cp -Rp "$STAGING_BASE" "$LSM_DIR_OBASE"
      BM_ROLE="base" ARM_ID="$ARM_ID" BM_PAIR_SUFFIX="$PAIR_SUFFIX" . $BM_DIRNAME/include/archive.in.sh
    fi

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
  if ! run_matrix_workload; then
    # Every variant is compared against this baseline: stop rather than archive bad pairs
    bm_keep_failed_outputs "$LSM_DIR_OBASE" "outputs-baseline-$DS"
    fatal_error "Baseline run failed; nothing archived"
  fi

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
    if ! run_matrix_workload; then
      # Neither role is archived, so --resume reruns this variant
      bm_keep_failed_outputs "$LSM_DIR_OBASE" "outputs-${ARM_ID}:run"
      mkdir -p "$LSM_DIR_OBASE"
      continue
    fi

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
  if run_matrix_workload; then
    if [ "$BM_TYPE" = "lsmio" ]; then
      if [ -f "$BM_DIRNAME/parse/lsmio-parse.sh" ]; then
        . $BM_DIRNAME/parse/lsmio-parse.sh
      fi
      # Only bmtool's standalone variants --archive step reads it
      if [ "$BM_SCALE" = "variants" ]; then
        : > "$BM_JOB_OK_MARKER"
      fi
    fi
  elif [ "$BM_TYPE" = "lsmio" ]; then
    # bmtool may archive $LSM_DIR_OBASE after this job (--archive) without seeing its exit
    # status, so move the failed run out first
    if [ "$BM_SCALE" = "variants" ]; then
      # $LSM_DIR_OBASE holds only this run, so there is no report to make. Not recreated,
      # so archive.in.sh stops on it
      bm_keep_failed_outputs "$LSM_DIR_OBASE" "outputs-variants-$DS"
    else
      # Scaling runs share $LSM_DIR_OBASE across concurrencies: move this one only, then
      # rebuild the report so it no longer lists the moved run
      bm_keep_failed_outputs "${LSM_DIR_OBASE}/${LSM_DIR_IDX}" "outputs-${LSM_DIR_IDX}-$DS"
      if [ -f "$BM_DIRNAME/parse/lsmio-parse.sh" ]; then
        . $BM_DIRNAME/parse/lsmio-parse.sh
      fi
    fi
  elif [ "$BM_TYPE" = "ior" ]; then
    # Keep the failed run out of ior-parse.sh's reach. Only this run's date directory:
    # the index directory also holds earlier runs
    bm_keep_failed_outputs "$IOR_DIR_OUTPUT" "outputs-${IOR_DIR_IDX}-$DS"
  elif [ "$BM_TYPE" = "lmp" ]; then
    bm_keep_failed_outputs "$LMP_DIR_OUTPUT" "outputs-${LMP_DIR_IDX}-$DS"
  fi
fi

# Report failed steps to Slurm/PBS (job state FAILED, failure mail) instead of a clean exit
if [ "$BM_JOB_FAILED" -ne 0 ]; then
  echo "ERROR: one or more benchmark steps failed; see the WARNING lines above" >&2
  exit 1
fi


