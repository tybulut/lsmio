#
. vars.in.sh

get_info_lustre() {
  if [ "$1" = "-v" ]; then
    LFS_OPT="-y"
  else
    LFS_OPT="-d"
  fi
  lfs getstripe "$LFS_OPT" $BM_PATH
}

configure_lustre() {
  if [ -n "$1"]; then
    STRIPE_SIZE="$1"
  else
    STRIPE_SIZE="64K"
  fi
  lfs setstripe -S "$STRIPE_SIZE" -c 4 $BM_PATH
}

