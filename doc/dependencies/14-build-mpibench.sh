#!/bin/sh -x

mkdir -p $HOME/src/packages/14-mpiBench
cd $HOME/src/packages/14-mpiBench

git clone https://github.com/LLNL/mpiBench.git
cd mpiBench

make \
&& cp -p -i crunch_mpiBench mpiBench $HOME/src/usr/bin

