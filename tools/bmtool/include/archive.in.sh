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

# Task 4.2.4: Mechanical Arm Identifier Derivation
: "${BM_SETUP:=NATIVE-M}"
ARM_ID="$(bm_resolve_arm_id "$BM_SETUP" "$BM_VARIANT")" || fatal_error "Invalid variant: [$BM_VARIANT]"
ARCHIVE_TARGET="${BM_ARCHIVE_DEST}/outputs-${ARM_ID}"

# Task 4.2.5: Target collision guard with auto-increment suffix (INV-5)
if [ -e "$ARCHIVE_TARGET" ]; then
  suffix=1
  while [ -e "${ARCHIVE_TARGET}-${suffix}" ]; do
    suffix=$(( suffix + 1 ))
  done
  ARCHIVE_TARGET="${ARCHIVE_TARGET}-${suffix}"
fi

# Task 4.2.6: Move-on-archive execution (INV-5, Constraints C7, C9)
mkdir -p "$BM_ARCHIVE_DEST" || fatal_error "Failed to create archive destination directory: $BM_ARCHIVE_DEST"
mv -- "$LSM_DIR_OBASE" "$ARCHIVE_TARGET"
[ ! -e "$LSM_DIR_OBASE" ] || fatal_error "Failed to move $LSM_DIR_OBASE"
mkdir -p "$LSM_DIR_OBASE" || fatal_error "Failed to recreate active output directory: $LSM_DIR_OBASE"
echo "Archived $LSM_DIR_OBASE -> $ARCHIVE_TARGET"
