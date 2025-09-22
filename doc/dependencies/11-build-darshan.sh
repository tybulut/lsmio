#!/bin/sh -x

. ../benchmark/scripts/vars.in.sh

mkdir -p $HOME/src/packages/11-darshan
cd $HOME/src/packages/11-darshan

git clone https://github.com/darshan-hpc/darshan.git
cd darshan

#  --with-log-path=/$BM_PATH/darshan \
./prepare.sh
./configure \
  --disable-heatmap-mod \
  --with-log-path=$HOME/scratch/darshan \
  --with-log-path-by-env=DARSHAN_LOGPATH \
  --with-jobid-env=SLURM_JOB_ID \
  --prefix=$HOME/src/usr
#  --enable-static --disable-shared \
#  --enable-heatmap-mod \

make -j16 \
&& make install

