#!/bin/sh -x

. ~/src/lsmio/tools/bmtool/include/vars.in.sh

mkdir -p $HOME/src/packages/11-darshan
cd $HOME/src/packages/11-darshan

git clone https://github.com/darshan-hpc/darshan.git
cd darshan

#  --with-log-path=/$BM_PATH/darshan \
./prepare.sh
./configure \
  --with-log-path=$HOME/scratch/darshan \
  --with-jobid-env=SLURM_JOB_ID \
  --prefix=$HOME/src/usr
#  --enable-static --disable-shared \

make -j16 \
&& make install

