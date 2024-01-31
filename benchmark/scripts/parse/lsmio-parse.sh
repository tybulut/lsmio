#

. $BM_DIRNAME/jobs/lsmio-vars.in.sh

#LSM_DIR_OBASE=/.../benchmark/lsmio-archive/lsmio-large-rocksdb/outputs

generate_aggregates() {
  if [ "$1" = "small" ]; then
    NODES="1 2 4 8 16 24 32 40 48"
  elif [ "$1" = "large" ]; then
    NODES="1 2 4 8 16 32 48 64"
  fi

  for n in $NODES
  do
    #out-rocksdb-16-1M-2023-04-05-node074-0.txt.2
    for rf in 4 16
    do
      for bs in 64K 1M 8M
      do
        AGG_FILE=${LSM_DIR_OBASE}/$n/agg-$rf-$bs-report.csv

        for file in ${LSM_DIR_OBASE}/$n/*/out-*-$rf-$bs-*.txt.2
        do
          echo "$file"
          HEADER=`grep '^access,' $file | head -1`
          WRITE_ROW=`grep '^write,' $file | head -1`
          READ_ROW=`grep '^read,' $file | head -1`
          break
        done

        OUT_WRITES=`grep '^write,' ${LSM_DIR_OBASE}/$n/*/out-*-$rf-$bs-*.txt.2 | awk -F, -v OFS=, 'BEGIN {it = 0;}  {sumMX += $2; sumMN += $3; sumME += $4; sumMB += $5; sumIO += $6; if ($7>0+it) it=$7;} END {print "write", sumMX, sumMN, sumME, sumMB, sumIO, it;}'`
        OUT_READS=`grep '^read,' ${LSM_DIR_OBASE}/$n/*/out-*-$rf-$bs-*.txt.2 | awk -F, -v OFS=, 'BEGIN {it = 0;}  {sumMX += $2; sumMN += $3; sumME += $4; sumMB += $5; sumIO += $6; if ($7>0+it) it=$7;} END {print "read", sumMX, sumMN, sumME, sumMB, sumIO, it;}'`

        cp /dev/null "$AGG_FILE"
        echo "$HEADER" >> "$AGG_FILE"
        echo "$OUT_WRITES" >> "$AGG_FILE"
        echo "$OUT_READS" >> "$AGG_FILE"

      done
    done
  done
}


generate_report() {
  REPORT_FILE=${LSM_DIR_OBASE}/lsm-report.csv
  cp /dev/null "$REPORT_FILE"

  #Example: /.../benchmark/lsmio/outputs/8/agg-4-8M-report.csv
  for file in ${LSM_DIR_OBASE}/*/agg-*-report.csv
  do
    echo "$file"

    egrep -H '^write|^read' "$file" | tail -2 \
      | sed "s/:/  /" \
      | sed "s|$LSM_DIR_OBASE/||" \
      | sed "s|agg-||" \
      | sed "s|-report.csv||" \
      | perl -e 's/^(.|..)\/(\d+)-(\d+[MK])/$1  $2  $3/' -p \
      | perl -e 's/ +/,/g' -p \
      >> "$REPORT_FILE"
  done
}

if [ "$BM_SCALE" = "small" ]; then
  generate_aggregates $BM_SCALE
  generate_report
elif [ "$BM_SCALE" = "large" ]; then
  generate_aggregates $BM_SCALE
  generate_report
else
  fatal_error "Please pass either small or large for lsmio parsing."
fi


