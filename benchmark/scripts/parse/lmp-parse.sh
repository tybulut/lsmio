#

. $BM_DIRNAME/jobs/lmp-vars.in.sh

generate_report() {
  REPORT_FILE=${LMP_DIR_OBASE}/lmp-report.csv
  cp /dev/null "$REPORT_FILE"

  for n in 1 2 4 8 16 24 32 40 48
  do
    #out-lmp-fs-16-8M-2023-06-20-node090-0.txt.2
    for rf in 4 16
    do
      for bs in 64K 1M 8M
      do
        grep -Hn '^.write,' ${LMP_DIR_OBASE}/$n/*/out-*-$rf-$bs-*.txt.2 \
          | tail -1 \
          | awk -F: "{ print \"$n,$rf,$bs,\"\$3 }" \
          >> "$REPORT_FILE"
      done
    done
  done
}



generate_report

