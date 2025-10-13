#
if [ "$HPC_ENV" = "viking" ]; then
  lfs setstripe -S 64K -c 4 $DIRS_BM_C4_B64
  lfs setstripe -S 64K -c 16 $DIRS_BM_c16_B64
  lfs setstripe -S 1M -c 4 $DIRS_BM_C4_B1M
  lfs setstripe -S 1M -c 16 $DIRS_BM_c16_B1M
  lfs setstripe -S 8M -c 4 $DIRS_BM_C4_B8M
  lfs setstripe -S 8M -c 16 $DIRS_BM_c16_B8M
elif [ "$BM_SSD" = "on" ]; then
  lfs setstripe -S 64K -c 4 $DIRS_BM_C4_B64 -p scratch.flash
  lfs setstripe -S 64K -c 16 $DIRS_BM_c16_B64 -p scratch.flash
  lfs setstripe -S 1M -c 4 $DIRS_BM_C4_B1M -p scratch.flash
  lfs setstripe -S 1M -c 16 $DIRS_BM_c16_B1M -p scratch.flash
  lfs setstripe -S 8M -c 4 $DIRS_BM_C4_B8M -p scratch.flash
  lfs setstripe -S 8M -c 16 $DIRS_BM_c16_B8M -p scratch.flash
else
  lfs setstripe -S 64K -c 4 $DIRS_BM_C4_B64 -p scratch.disk
  lfs setstripe -S 64K -c 16 $DIRS_BM_c16_B64 -p scratch.disk
  lfs setstripe -S 1M -c 4 $DIRS_BM_C4_B1M -p scratch.disk
  lfs setstripe -S 1M -c 16 $DIRS_BM_c16_B1M -p scratch.disk
  lfs setstripe -S 8M -c 4 $DIRS_BM_C4_B8M -p scratch.disk
  lfs setstripe -S 8M -c 16 $DIRS_BM_c16_B8M -p scratch.disk
fi
#
