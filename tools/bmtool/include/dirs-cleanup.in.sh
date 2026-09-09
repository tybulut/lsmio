#
for target in \
  "${DIRS_BM_C4_B64:?DIRS_BM_C4_B64 is unset or empty}" \
  "${DIRS_BM_c16_B64:?DIRS_BM_c16_B64 is unset or empty}" \
  "${DIRS_BM_C4_B1M:?DIRS_BM_C4_B1M is unset or empty}" \
  "${DIRS_BM_c16_B1M:?DIRS_BM_c16_B1M is unset or empty}" \
  "${DIRS_BM_C4_B8M:?DIRS_BM_C4_B8M is unset or empty}" \
  "${DIRS_BM_c16_B8M:?DIRS_BM_c16_B8M is unset or empty}" \
  "${DIRS_LOG:?DIRS_LOG is unset or empty}"
do
  if [ -d "$target" ]; then
    rm -rf -- "$target"/*
  fi
done
#

