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
      BM_VARIANT_FLAGS="--lsmio-footer-index"
      ;;
    btree)
      BM_VARIANT_TOKENS="btree"
      BM_VARIANT_FLAGS="--lsmio-memtable btree"
      ;;
    footer-btree)
      BM_VARIANT_TOKENS="footer-btree"
      BM_VARIANT_FLAGS="--lsmio-footer-index --lsmio-memtable btree"
      ;;
    map)
      BM_VARIANT_TOKENS="map"
      BM_VARIANT_FLAGS="--lsmio-memtable map"
      ;;
    vsort)
      BM_VARIANT_TOKENS="vsort"
      BM_VARIANT_FLAGS="--lsmio-memtable vector-sort"
      ;;
    prealloc)
      BM_VARIANT_TOKENS="prealloc"
      BM_VARIANT_FLAGS="--lsmio-prealloc"
      ;;
    footer-prealloc)
      BM_VARIANT_TOKENS="footer-prealloc"
      BM_VARIANT_FLAGS="--lsmio-footer-index --lsmio-prealloc"
      ;;
    manoff)
      BM_VARIANT_TOKENS="manoff"
      BM_VARIANT_FLAGS="--lsmio-manual-offset"
      ;;
    footer-manoff)
      BM_VARIANT_TOKENS="footer-manoff"
      BM_VARIANT_FLAGS="--lsmio-footer-index --lsmio-manual-offset"
      ;;
    wbuf-512m)
      BM_VARIANT_TOKENS="wbuf-512m"
      BM_VARIANT_FLAGS="--lsmio-wbuffer 536870912"
      ;;
    wbuf-32m)
      BM_VARIANT_TOKENS="wbuf-32m"
      BM_VARIANT_FLAGS="--lsmio-wbuffer 33554432"
      ;;
    footer-wbuf-512m)
      BM_VARIANT_TOKENS="footer-wbuf-512m"
      BM_VARIANT_FLAGS="--lsmio-footer-index --lsmio-wbuffer 536870912"
      ;;
    footer-btree-prealloc)
      BM_VARIANT_TOKENS="footer-btree-prealloc"
      BM_VARIANT_FLAGS="--lsmio-footer-index --lsmio-memtable btree --lsmio-prealloc"
      ;;
    bfilter)
      BM_VARIANT_TOKENS="bfilter"
      BM_VARIANT_FLAGS="--lsmio-bfilter"
      ;;
    wal)
      BM_VARIANT_TOKENS="wal"
      BM_VARIANT_FLAGS="--lsmio-wal"
      ;;
    mmap)
      BM_VARIANT_TOKENS="mmap"
      BM_VARIANT_FLAGS="--lsmio-mmap"
      ;;
    pread)
      BM_VARIANT_TOKENS="pread"
      BM_VARIANT_FLAGS="--lsmio-pread"
      ;;
    footer-mmap)
      BM_VARIANT_TOKENS="footer-mmap"
      BM_VARIANT_FLAGS="--lsmio-footer-index --lsmio-mmap"
      ;;
    footer-pread)
      BM_VARIANT_TOKENS="footer-pread"
      BM_VARIANT_FLAGS="--lsmio-footer-index --lsmio-pread"
      ;;
    compress)
      BM_VARIANT_TOKENS="compress"
      BM_VARIANT_FLAGS="--lsmio-compress"
      ;;
    sync)
      BM_VARIANT_TOKENS="sync"
      BM_VARIANT_FLAGS="--sync"
      ;;
    pool-8)
      BM_VARIANT_TOKENS="pool-8"
      BM_VARIANT_FLAGS="--lsmio-pool 8"
      ;;
    flush)
      BM_VARIANT_TOKENS="flush"
      BM_VARIANT_FLAGS="--lsmo-always-flush"
      ;;
    batch-2048)
      BM_VARIANT_TOKENS="batch-2048"
      BM_VARIANT_FLAGS="--lsmio-batch-size 2048"
      ;;
    manoff-prealloc)
      BM_VARIANT_TOKENS="manoff-prealloc"
      BM_VARIANT_FLAGS="--lsmio-manual-offset --lsmio-prealloc"
      ;;
    wbuf-512m-manoff-prealloc)
      BM_VARIANT_TOKENS="wbuf-512m-manoff-prealloc"
      BM_VARIANT_FLAGS="--lsmio-wbuffer 536870912 --lsmio-manual-offset --lsmio-prealloc"
      ;;
    footer-wbuf-32m)
      BM_VARIANT_TOKENS="footer-wbuf-32m"
      BM_VARIANT_FLAGS="--lsmio-footer-index --lsmio-wbuffer 33554432"
      ;;
    footer-pool-8)
      BM_VARIANT_TOKENS="footer-pool-8"
      BM_VARIANT_FLAGS="--lsmio-footer-index --lsmio-pool 8"
      ;;
    footer-wbuf-512m-manoff-prealloc)
      BM_VARIANT_TOKENS="footer-wbuf-512m-manoff-prealloc"
      BM_VARIANT_FLAGS="--lsmio-footer-index --lsmio-wbuffer 536870912 --lsmio-manual-offset --lsmio-prealloc"
      ;;
    footer-vsort-manoff-prealloc)
      BM_VARIANT_TOKENS="footer-vsort-manoff-prealloc"
      BM_VARIANT_FLAGS="--lsmio-footer-index --lsmio-memtable vector-sort --lsmio-manual-offset --lsmio-prealloc"
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
      return 1
      ;;
  esac
  export BM_VARIANT_TOKENS BM_VARIANT_FLAGS
  return 0
}
