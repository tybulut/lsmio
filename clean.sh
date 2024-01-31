#!/bin/sh -x

cd $HOME/src/usr

rm -rf $HOME/src/usr/include/lsmio/
rm -rf $HOME/src/usr/lib/cmake/lsmio*
rm -f $HOME/src/usr/lib/liblsmio*
rm -f $HOME/src/usr/bin/bm_*

# Validate
find . -name "*lsmio*"

