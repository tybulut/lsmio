#

. $BM_DIRNAME/jobs/ior-vars.in.sh

REPORT_FILE=${IOR_DIR_OBASE}/ior-report.csv

cp /dev/null "$REPORT_FILE"
for file in ${IOR_DIR_OBASE}/*/*/*
do
  echo "$file"
  if [ ! -s "$file" ]; then
    continue
  fi

  egrep -H '^write|^read' "$file" | tail -2 \
    | sed "s/:/  /" \
    | sed "s|$IOR_DIR_OBASE/||" \
    | sed "s|/20..-..-..||" \
    | sed "s|-20..-..-..-node...-0.txt.2||" \
    | perl -e 's/^(.|..)\/out-[a-z]+-(\d+)-(\d+[MK])/$1  $2  $3/' -p \
    | perl -e 's/ +/,/g' -p \
    >> "$REPORT_FILE"
done


