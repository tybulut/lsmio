#!/bin/sh -x

#export DARSHAN_LOGPATH=$HOME/scratch/darshan
#LD_PRELOAD=$HOME/src/usr/lib/libdarshan.so \
srun ./bin/epoch2d -i input.deck << EOFF
output
EOFF

