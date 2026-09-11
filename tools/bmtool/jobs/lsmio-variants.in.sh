# Declarative variant catalogue & resolver for LSMIO benchmarks
# Pure POSIX /bin/sh (dash-compatible, no bashisms per INV-4)

resolve_variant() {
  var="$1"

  # Task 2.2.1: Strip optional backend prefix if present (e.g. native-footer -> footer)
  case "$var" in
    native-m-*|NATIVE-M-*|rocksdb-m-*|ROCKSDB-M-*|leveldb-m-*|LEVELDB-M-*|adios-m-*|ADIOS-M-*|plugin-m-*|PLUGIN-M-*)
      var="${var#*-}"
      var="${var#*-}"
      ;;
    native-*|NATIVE-*|rocksdb-*|ROCKSDB-*|leveldb-*|LEVELDB-*|adios-*|ADIOS-*|plugin-*|PLUGIN-*|manager-*|MANAGER-*)
      var="${var#*-}"
      ;;
  esac

  # Task 2.2.2: Map variant key to tokens and flags
  case "$var" in
    ""|base|default)
      BM_VARIANT_TOKENS=""
      BM_VARIANT_FLAGS=""
      ;;
    footer)
      BM_VARIANT_TOKENS="footer"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-footer-index"
      ;;
    btree)
      BM_VARIANT_TOKENS="btree"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-memtable btree"
      ;;
    footer-btree)
      BM_VARIANT_TOKENS="footer-btree"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-footer-index --lsmio-memtable btree"
      ;;
    map)
      BM_VARIANT_TOKENS="map"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-memtable map"
      ;;
    vsort)
      BM_VARIANT_TOKENS="vsort"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-memtable vector-sort"
      ;;
    prealloc)
      BM_VARIANT_TOKENS="prealloc"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-prealloc"
      ;;
    footer-prealloc)
      BM_VARIANT_TOKENS="footer-prealloc"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-footer-index --lsmio-prealloc"
      ;;
    manoff)
      BM_VARIANT_TOKENS="manoff"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-manual-offset"
      ;;
    footer-manoff)
      BM_VARIANT_TOKENS="footer-manoff"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-footer-index --lsmio-manual-offset"
      ;;
    wbuf-512m)
      BM_VARIANT_TOKENS="wbuf-512m"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-wbuffer 536870912"
      ;;
    wbuf-32m)
      BM_VARIANT_TOKENS="wbuf-32m"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-wbuffer 33554432"
      ;;
    footer-wbuf-512m)
      BM_VARIANT_TOKENS="footer-wbuf-512m"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-footer-index --lsmio-wbuffer 536870912"
      ;;
    footer-btree-prealloc)
      BM_VARIANT_TOKENS="footer-btree-prealloc"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-footer-index --lsmio-memtable btree --lsmio-prealloc"
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
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-mmap"
      ;;
    pread)
      BM_VARIANT_TOKENS="pread"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-pread"
      ;;
    footer-mmap)
      BM_VARIANT_TOKENS="footer-mmap"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-footer-index --lsmio-mmap"
      ;;
    footer-pread)
      BM_VARIANT_TOKENS="footer-pread"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-footer-index --lsmio-pread"
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
    manoff-prealloc)
      BM_VARIANT_TOKENS="manoff-prealloc"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-manual-offset --lsmio-prealloc"
      ;;
    wbuf-512m-manoff-prealloc)
      BM_VARIANT_TOKENS="wbuf-512m-manoff-prealloc"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-wbuffer 536870912 --lsmio-manual-offset --lsmio-prealloc"
      ;;
    footer-wbuf-32m)
      BM_VARIANT_TOKENS="footer-wbuf-32m"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-footer-index --lsmio-wbuffer 33554432"
      ;;
    footer-pool-8)
      BM_VARIANT_TOKENS="footer-pool-8"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-footer-index --lsmio-pool 8"
      ;;
    footer-wbuf-512m-manoff-prealloc)
      BM_VARIANT_TOKENS="footer-wbuf-512m-manoff-prealloc"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-footer-index --lsmio-wbuffer 536870912 --lsmio-manual-offset --lsmio-prealloc"
      ;;
    footer-vsort-manoff-prealloc)
      BM_VARIANT_TOKENS="footer-vsort-manoff-prealloc"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-footer-index --lsmio-memtable vector-sort --lsmio-manual-offset --lsmio-prealloc"
      ;;
    footer-vsort-manoff-mmap)
      BM_VARIANT_TOKENS="footer-vsort-manoff-mmap"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-footer-index --lsmio-memtable vector-sort --lsmio-manual-offset --lsmio-mmap"
      ;;
    footer-vsort-manoff)
      BM_VARIANT_TOKENS="footer-vsort-manoff"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-footer-index --lsmio-memtable vector-sort --lsmio-manual-offset"
      ;;
    footer-pool-8-mmap)
      BM_VARIANT_TOKENS="footer-pool-8-mmap"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-footer-index --lsmio-pool 8 --lsmio-mmap"
      ;;
    footer-manoff-pool-8-mmap)
      BM_VARIANT_TOKENS="footer-manoff-pool-8-mmap"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-footer-index --lsmio-manual-offset --lsmio-pool 8 --lsmio-mmap"
      ;;
    footer-btree-manoff-mmap)
      BM_VARIANT_TOKENS="footer-btree-manoff-mmap"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-footer-index --lsmio-memtable btree --lsmio-manual-offset --lsmio-mmap"
      ;;
    footer-manoff-pool-8)
      BM_VARIANT_TOKENS="footer-manoff-pool-8"
      BM_VARIANT_FLAGS="--lsmio-no-autotune --lsmio-footer-index --lsmio-manual-offset --lsmio-pool 8"
      ;;
    autotune)
      BM_VARIANT_TOKENS="autotune"
      BM_VARIANT_FLAGS="--lsmio-autotune"
      ;;
    *)
      echo "Error: Unknown variant '$1'." >&2
      echo "Supported variants are:" >&2
      echo "  base, default (or empty)" >&2
      echo "  footer, btree, footer-btree, map, vsort" >&2
      echo "  prealloc, footer-prealloc, manoff, footer-manoff" >&2
      echo "  wbuf-512m, wbuf-32m, footer-wbuf-512m, footer-btree-prealloc" >&2
      echo "  bfilter, wal, mmap, pread, compress, sync" >&2
      echo "  pool-8, flush, batch-2048, manoff-prealloc" >&2
      echo "  footer-mmap, footer-pread" >&2
      echo "  wbuf-512m-manoff-prealloc, footer-wbuf-32m, footer-pool-8" >&2
      echo "  footer-wbuf-512m-manoff-prealloc, footer-vsort-manoff-prealloc" >&2
      echo "  footer-vsort-manoff-mmap, footer-vsort-manoff, footer-pool-8-mmap" >&2
      echo "  footer-manoff-pool-8-mmap, footer-btree-manoff-mmap, footer-manoff-pool-8" >&2
      echo "  autotune" >&2
      return 1
      ;;
  esac
  export BM_VARIANT_TOKENS BM_VARIANT_FLAGS
  return 0
}

# Canonical sequence of all 38 matrix variants (base run + 37 non-empty keys)
LSMIO_ALL_VARIANTS="default,footer,btree,footer-btree,map,vsort,prealloc,footer-prealloc,manoff,footer-manoff,wbuf-512m,wbuf-32m,footer-wbuf-512m,footer-btree-prealloc,bfilter,wal,mmap,pread,footer-mmap,footer-pread,compress,sync,pool-8,flush,batch-2048,manoff-prealloc,wbuf-512m-manoff-prealloc,footer-wbuf-32m,footer-pool-8,footer-wbuf-512m-manoff-prealloc,footer-vsort-manoff-prealloc,footer-vsort-manoff-mmap,footer-vsort-manoff,footer-pool-8-mmap,footer-manoff-pool-8-mmap,footer-btree-manoff-mmap,footer-manoff-pool-8,autotune"
export LSMIO_ALL_VARIANTS

# Expands and validates a raw variant argument into a canonical comma-separated list.
# Handles: omitted/empty, 'default', 'base', single variant, comma list, or 'all'.
# Returns 0 on success (printing comma-separated tokens), 1 on validation error.
bm_expand_variants() {
  _raw="$1"
  if [ -z "$_raw" ] || [ "$_raw" = "default" ] || [ "$_raw" = "base" ]; then
    echo "default"
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
    _setup="${1:-NATIVE-M}"
    _var="$2"
  else
    _setup="${BM_SETUP:-NATIVE-M}"
    _var="$1"
  fi

  case "$_setup" in
    *-M)
      _base="${_setup%-M}"
      _backend=$(echo "$_base" | tr '[:upper:]' '[:lower:]')
      ;;
    MANAGER)
      _backend="manager"
      ;;
    *)
      _backend="$(echo "$_setup" | tr '[:upper:]' '[:lower:]')-nompi"
      ;;
  esac

  resolve_variant "$_var" >/dev/null 2>&1 || return 1

  if [ -n "$BM_VARIANT_TOKENS" ]; then
    echo "${_backend}-${BM_VARIANT_TOKENS}"
  else
    echo "${_backend}"
  fi
  return 0
}
