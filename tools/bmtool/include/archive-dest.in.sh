# Archive destination resolver for LSMIO benchmark outputs
# Pure POSIX /bin/sh (dash-compatible, no bashisms per INV-4)
#
# Single source of truth for BM_ARCHIVE_DEST. Sourced by bmtool (before the job
# is submitted), by jobs/batch.in.sh (inside the allocation) and by
# include/archive.in.sh (archive cmd), so every context resolves identically.
#
# Layout (three destinations under $BM_PATH/lsmio-archive):
#   backends/<scale>  multi-backend intra-allocation runs (BM_MODE=backends)
#   variants          variant matrix runs (BM_SCALE=variants)
#   baseline          plain scaling runs (local, bake, small, large)

# Note: bmtool clears BM_ARCHIVE_DEST at startup, so an inherited environment value
# only takes effect inside an allocation (batch.in.sh), where the submitting bmtool
# exported the value it resolved. Pass --dest to override.

bm_resolve_archive_dest() {
  # Normalise the mode/scale tokens the same way the Python resolver does
  # (lsmiotool.lib.archive.resolveArchiveDest): case-insensitive, with
  # 'baseline' accepted as the deprecated spelling of 'variants'.
  _bm_mode=$(printf '%s' "${BM_MODE:-standard}" | tr 'A-Z' 'a-z')
  _bm_scale=$(printf '%s' "$BM_SCALE" | tr 'A-Z' 'a-z')
  [ "$_bm_scale" = "baseline" ] && _bm_scale="variants"

  # Trim surrounding whitespace; a whitespace-only value counts as unset
  # (matches the Python resolver in lsmiotool.lib.archive)
  case "$BM_ARCHIVE_DEST" in
    *[![:space:]]*)
      BM_ARCHIVE_DEST=$(printf '%s' "$BM_ARCHIVE_DEST" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')
      ;;
    *) BM_ARCHIVE_DEST="" ;;
  esac

  if [ -n "$BM_ARCHIVE_DEST" ]; then
    case "$BM_ARCHIVE_DEST" in
      # Root-relative shorthand: --dest=/lsmio-archive/... means $BM_PATH-relative
      /lsmio-archive|/lsmio-archive/*) BM_ARCHIVE_DEST="${BM_PATH}${BM_ARCHIVE_DEST}" ;;
      /*) ;;
      *) BM_ARCHIVE_DEST="${BM_PATH}/${BM_ARCHIVE_DEST}" ;;
    esac
  elif [ "$_bm_mode" = "backends" ]; then
    BM_ARCHIVE_DEST="$BM_PATH/lsmio-archive/backends/$_bm_scale"
  elif [ "$_bm_scale" = "variants" ]; then
    BM_ARCHIVE_DEST="$BM_PATH/lsmio-archive/variants"
  else
    BM_ARCHIVE_DEST="$BM_PATH/lsmio-archive/baseline"
  fi

  unset _bm_mode _bm_scale
  export BM_ARCHIVE_DEST
}
