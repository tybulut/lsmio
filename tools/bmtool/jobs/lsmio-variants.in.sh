# Declarative variant catalogue & resolver for LSMIO benchmarks
# Pure POSIX /bin/sh (dash-compatible, no bashisms per INV-4)

resolve_variant() {
  var="$1"

  # Task 2.2.1: Strip optional backend prefix if present (e.g. native-btree -> btree)
  case "$var" in
    native-*|NATIVE-*|rocksdb-*|ROCKSDB-*|leveldb-*|LEVELDB-*|adios-*|ADIOS-*|plugin-*|PLUGIN-*|manager-*|MANAGER-*)
      var="${var#*-}"
      ;;
  esac

  # Task 2.2.2: Map variant key to tokens and flags
  case "$var" in
    ""|base|default)
      BM_VARIANT_TOKENS=""
      BM_VARIANT_FLAGS="--lsmio-no-autotune"
      ;;
    version-*)
      # version-<branch>-<hash>-<retired variant> is rejected like the bare key (no-pread,
      # no-footer and no-manoff end in a retired key but are valid, so they match first)
      case "$var" in
        version-*-*-no-pread|version-*-*-no-footer|version-*-*-no-manoff) ;;
        version-*-*-footer-wbuf-512m-manoff-prealloc \
        | version-*-*-footer-vsort-manoff-prealloc \
        | version-*-*-footer-pread-manoff-pool-8 \
        | version-*-*-wbuf-512m-manoff-prealloc \
        | version-*-*-footer-manoff-pool-8-mmap \
        | version-*-*-footer-btree-manoff-pread \
        | version-*-*-footer-vsort-manoff-mmap \
        | version-*-*-footer-btree-manoff-mmap \
        | version-*-*-footer-map-manoff-pread \
        | version-*-*-footer-map-manoff-mmap \
        | version-*-*-footer-btree-prealloc \
        | version-*-*-footer-manoff-pool-8 \
        | version-*-*-footer-vsort-manoff \
        | version-*-*-footer-pread-pool-8 \
        | version-*-*-footer-pread-manoff \
        | version-*-*-footer-pool-8-mmap \
        | version-*-*-footer-btree-pread \
        | version-*-*-footer-vsort-pread \
        | version-*-*-footer-map-manoff \
        | version-*-*-footer-wbuf-512m \
        | version-*-*-footer-map-pread \
        | version-*-*-footer-prealloc \
        | version-*-*-manoff-prealloc \
        | version-*-*-footer-wbuf-32m \
        | version-*-*-footer-manoff \
        | version-*-*-footer-pool-8 \
        | version-*-*-manoff-pool-8 \
        | version-*-*-footer-btree \
        | version-*-*-footer-pread \
        | version-*-*-footer-mmap \
        | version-*-*-footer-map \
        | version-*-*-footer \
        | version-*-*-manoff \
        | version-*-*-pread \
        | version-*-*-map)
          echo "Error: Unknown variant '$1' (retired variant)." >&2
          return 1
          ;;
      esac
      BM_VARIANT_TOKENS="$var"
      BM_VARIANT_FLAGS="--lsmio-no-autotune"
      ;;
    btree)
      BM_VARIANT_TOKENS="btree"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-memtable btree"
      ;;
    vsort)
      BM_VARIANT_TOKENS="vsort"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-memtable vector-sort"
      ;;
    prealloc)
      BM_VARIANT_TOKENS="prealloc"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-prealloc"
      ;;
    wbuf-512m)
      BM_VARIANT_TOKENS="wbuf-512m"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-wbuffer 536870912"
      ;;
    wbuf-32m)
      BM_VARIANT_TOKENS="wbuf-32m"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-wbuffer 33554432"
      ;;
    bfilter)
      BM_VARIANT_TOKENS="bfilter"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-bfilter"
      ;;
    wal)
      BM_VARIANT_TOKENS="wal"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-wal"
      ;;
    mmap)
      BM_VARIANT_TOKENS="mmap"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-mmap --lsmio-no-pread"
      ;;
    compress)
      BM_VARIANT_TOKENS="compress"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-compress"
      ;;
    sync)
      BM_VARIANT_TOKENS="sync"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --sync"
      ;;
    pool-8)
      BM_VARIANT_TOKENS="pool-8"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-pool 8"
      ;;
    flush)
      BM_VARIANT_TOKENS="flush"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-always-flush"
      ;;
    batch-2048)
      BM_VARIANT_TOKENS="batch-2048"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-batch-size 2048"
      ;;
    vnosort)
      BM_VARIANT_TOKENS="vnosort"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-memtable vector-no-sort"
      ;;
    no-pread)
      BM_VARIANT_TOKENS="no-pread"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-no-pread"
      ;;
    no-footer)
      BM_VARIANT_TOKENS="no-footer"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-no-footer-index"
      ;;
    no-manoff)
      BM_VARIANT_TOKENS="no-manoff"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-no-manual-offset"
      ;;
    legacy)
      BM_VARIANT_TOKENS="legacy"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-no-footer-index --lsmio-no-manual-offset --lsmio-no-pread --lsmio-memtable vector-no-sort"
      ;;
    prealloc-vsort)
      BM_VARIANT_TOKENS="prealloc-vsort"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-memtable vector-sort --lsmio-prealloc"
      ;;
    prealloc-btree)
      BM_VARIANT_TOKENS="prealloc-btree"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-memtable btree --lsmio-prealloc"
      ;;
    prealloc-wbuf-512m)
      BM_VARIANT_TOKENS="prealloc-wbuf-512m"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-wbuffer 536870912 --lsmio-prealloc"
      ;;
    mmap-vsort)
      BM_VARIANT_TOKENS="mmap-vsort"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-memtable vector-sort --lsmio-mmap --lsmio-no-pread"
      ;;
    mmap-btree)
      BM_VARIANT_TOKENS="mmap-btree"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-memtable btree --lsmio-mmap --lsmio-no-pread"
      ;;
    pool-8-mmap)
      BM_VARIANT_TOKENS="pool-8-mmap"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-pool 8 --lsmio-mmap --lsmio-no-pread"
      ;;
    autotune)
      BM_VARIANT_TOKENS="autotune"
      BM_VARIANT_FLAGS="--lsmio-autotune"
      ;;
    *)
      echo "Error: Unknown variant '$1'." >&2
      echo "Supported canonical variants are:" >&2
      echo "  default (or empty)" >&2
      echo "  vsort, btree, vnosort, mmap, no-pread, no-footer, no-manoff, legacy" >&2
      echo "  prealloc, wbuf-512m, wbuf-32m, pool-8" >&2
      echo "  prealloc-vsort, prealloc-btree, prealloc-wbuf-512m" >&2
      echo "  mmap-vsort, mmap-btree, pool-8-mmap" >&2
      echo "  flush, batch-2048, bfilter, wal, compress, sync, autotune" >&2
      return 1
      ;;
  esac
  export BM_VARIANT_TOKENS BM_VARIANT_FLAGS
  return 0
}

# Streamlined canonical sequence of 26 matrix variants (base default + 25 non-empty keys)
LSMIO_MOST_VARIANTS="default,vsort,btree,vnosort,mmap,no-pread,no-footer,no-manoff,legacy,prealloc,wbuf-512m,wbuf-32m,pool-8,prealloc-vsort,prealloc-btree,prealloc-wbuf-512m,mmap-vsort,mmap-btree,pool-8-mmap,flush,batch-2048,bfilter,wal,compress,sync,autotune"
export LSMIO_MOST_VARIANTS

# Every registered variant: the same 26 as LSMIO_MOST_VARIANTS ('most' and 'all' are synonyms)
LSMIO_ALL_VARIANTS="$LSMIO_MOST_VARIANTS"
export LSMIO_ALL_VARIANTS

# Expands and validates a raw variant argument into a canonical comma-separated list.
# Handles: omitted/empty, 'default', 'base', single variant, comma list, 'most', or 'all'.
# Returns 0 on success (printing comma-separated tokens), 1 on validation error.
bm_expand_variants() {
  _raw="$1"
  if [ -z "$_raw" ] || [ "$_raw" = "default" ] || [ "$_raw" = "base" ]; then
    echo "default"
    return 0
  fi
  if [ "$_raw" = "most" ]; then
    echo "$LSMIO_MOST_VARIANTS"
    return 0
  fi
  if [ "$_raw" = "all" ]; then
    echo "$LSMIO_ALL_VARIANTS"
    return 0
  fi

  _out=""
  _rem="$_raw"
  while [ -n "$_rem" ]; do
    case "$_rem" in
      *,*)
        _item="${_rem%%,*}"
        _rem="${_rem#*,}"
        ;;
      *)
        _item="$_rem"
        _rem=""
        ;;
    esac

    # Normalize token
    case "$_item" in
      ""|default|base)
        _norm="default"
        ;;
      most)
        _norm="$LSMIO_MOST_VARIANTS"
        ;;
      all)
        _norm="$LSMIO_ALL_VARIANTS"
        ;;
      *)
        if ! resolve_variant "$_item" >/dev/null 2>&1; then
          echo "Error: Unknown variant '$_item' in variant list." >&2
          return 1
        fi
        _norm="$_item"
        ;;
    esac

    if [ -z "$_out" ]; then
      _out="$_norm"
    else
      _out="${_out},${_norm}"
    fi
  done

  [ -n "$_out" ] || _out="default"
  echo "$_out"
  return 0
}

# Derives mechanical arm identifier matching lsmiotool and archive.in.sh
bm_resolve_arm_id() {
  if [ $# -ge 2 ]; then
    _setup="${1:-NATIVE}"
    _var="$2"
  else
    _setup="${BM_SETUP:-NATIVE}"
    _var="$1"
  fi

  _backend=$(echo "$_setup" | tr '[:upper:]' '[:lower:]')

  resolve_variant "$_var" >/dev/null 2>&1 || return 1

  if [ -n "$BM_VARIANT_TOKENS" ]; then
    echo "${_backend}-${BM_VARIANT_TOKENS}"
  else
    echo "${_backend}"
  fi
  return 0
}
