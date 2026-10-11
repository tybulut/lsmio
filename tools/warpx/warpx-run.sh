#!/bin/sh

RUN_DIR=run-001
rm -rf $RUN_DIR
mkdir -p $RUN_DIR
cd $RUN_DIR


mpirun -np 2 \
  -x LD_PRELOAD=$HOME/src/usr/lib/libdarshan.so \
  ../warpx ../laser_ion_inputs 2>&1 | tee ./out.txt

