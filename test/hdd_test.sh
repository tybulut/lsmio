#!/bin/sh -x

HDD_DRIVE=/dev/sda2
HDD_MOUNT=/media/400GB

tune_defaults() {
  echo 3000 > /proc/sys/vm/dirty_expire_centisecs
  echo 500 > /proc/sys/vm/dirty_writeback_centisecs
}


tune_benchmarks() {
  echo 0 > /proc/sys/vm/dirty_expire_centisecs
  echo 0 > /proc/sys/vm/dirty_writeback_centisecs
  echo 200 > /proc/sys/vm/vfs_cache_pressure
  echo 1 > /proc/sys/vm/drop_caches
  echo 2 > /proc/sys/vm/drop_caches
  echo 3 > /proc/sys/vm/drop_caches
}

show_tuning() {
  cat /proc/sys/vm/dirty_expire_centisecs
  cat /proc/sys/vm/dirty_writeback_centisecs
}

mount -o sync,noatime,nodiratime $HDD_DRIVE $HDD_MOUNT


