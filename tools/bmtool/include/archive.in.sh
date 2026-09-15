# Archive & Move Engine for LSMIO benchmark outputs
# Pure POSIX /bin/sh (dash-compatible, no bashisms per INV-4)

# Fallback definition of fatal_error if not already defined
if ! command -v fatal_error >/dev/null 2>&1; then
  fatal_error() {
    echo "ERROR: $1" >&2
    exit 1
  }
fi

# Task 4.2.1: Scope prerequisites
# Bring $LSM_DIR_OBASE into scope (Constraint C15) and load variant catalogue
. $BM_DIRNAME/jobs/lsmio-vars.in.sh
. $BM_DIRNAME/jobs/lsmio-variants.in.sh

# Task 4.2.2: Destination resolution (default to $BM_PATH/lsmio-archive if omitted)
: "${BM_ARCHIVE_DEST:=$BM_PATH/lsmio-archive}"

# Task 4.2.3: Active output directory check
[ -d "$LSM_DIR_OBASE" ] || fatal_error "Active output directory does not exist: $LSM_DIR_OBASE"

# Task 4.2.3b: Ensure output directory has aggregated reports before archiving
if [ "${BM_TYPE:-lsmio}" = "lsmio" ] && [ ! -f "${LSM_DIR_OBASE}/lsm-report.csv" ] && [ -f "$BM_DIRNAME/parse/lsmio-parse.sh" ]; then
  _have_logs=0
  for _f in "${LSM_DIR_OBASE}"/*/*/out-*.txt*; do
    if [ -f "$_f" ]; then
      _have_logs=1
      break
    fi
  done
  if [ "$_have_logs" -eq 1 ]; then
    : "${BM_SCALE:=baseline}"
    . $BM_DIRNAME/parse/lsmio-parse.sh
  fi
fi

# Task 4.2.4: Mechanical Arm Identifier Derivation
: "${BM_SETUP:=NATIVE-M}"
if [ -z "$ARM_ID" ]; then
  ARM_ID="$(bm_resolve_arm_id "$BM_SETUP" "$BM_VARIANT")" || fatal_error "Invalid variant: [$BM_VARIANT]"
fi
# Task 4.2.5: Symmetrical Paired & Standalone Collision Resolution Engine
if [ -n "$BM_ROLE" ]; then
  # Symmetrical Paired Archiving (INV-PAIR-2)
  if [ -z "${BM_PAIR_SUFFIX+x}" ]; then
    BASE_RUN="${BM_ARCHIVE_DEST}/outputs-${ARM_ID}:run"
    BASE_BASE="${BM_ARCHIVE_DEST}/outputs-${ARM_ID}:base"
    if [ -e "$BASE_RUN" ] || [ -e "$BASE_BASE" ]; then
      k=1
      while [ -e "${BASE_RUN}-${k}" ] || [ -e "${BASE_BASE}-${k}" ]; do
        k=$(( k + 1 ))
      done
      BM_PAIR_SUFFIX="-$k"
    else
      BM_PAIR_SUFFIX=""
    fi
  fi
  ARCHIVE_TARGET="${BM_ARCHIVE_DEST}/outputs-${ARM_ID}:${BM_ROLE}${BM_PAIR_SUFFIX}"
else
  # Standalone Unadorned Baseline / Legacy Collision Resolution (INV-PAIR-3)
  ARCHIVE_TARGET="${BM_ARCHIVE_DEST}/outputs-${ARM_ID}"
  if [ -e "$ARCHIVE_TARGET" ]; then
    suffix=1
    while [ -e "${ARCHIVE_TARGET}-${suffix}" ]; do
      suffix=$(( suffix + 1 ))
    done
    ARCHIVE_TARGET="${ARCHIVE_TARGET}-${suffix}"
  fi
fi

# Task 4.2.6: Move-on-archive execution (INV-5, Constraints C7, C9)
mkdir -p "$BM_ARCHIVE_DEST" || fatal_error "Failed to create archive destination directory: $BM_ARCHIVE_DEST"
mv -- "$LSM_DIR_OBASE" "$ARCHIVE_TARGET"
[ ! -e "$LSM_DIR_OBASE" ] || fatal_error "Failed to move $LSM_DIR_OBASE"
mkdir -p "$LSM_DIR_OBASE" || fatal_error "Failed to recreate active output directory: $LSM_DIR_OBASE"
echo "Archived $LSM_DIR_OBASE -> $ARCHIVE_TARGET"
