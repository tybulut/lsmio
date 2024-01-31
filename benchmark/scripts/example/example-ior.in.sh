
. vars.in.sh

run_ior() {
  if [ ! -d $BM_PATH/ior ]; then
    mkdir $BM_PATH/ior
  fi
  $SB_BIN/ior -F -w -r \
    -b=64k -t=64k -s=1024 -i=10 \
    -o $BM_PATH/ior/ior.dat
}

