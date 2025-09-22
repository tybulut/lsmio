#!/bin/sh -x

mkdir -p $HOME/src/packages/24-epoch
cd $HOME/src/packages/24-epoch

git clone --recursive https://github.com/Warwick-Plasma/epoch.git

cd epoch

for v in epoch1d epoch2d epoch3d
do
  pushd $v
  make COMPILER=gfortran -j8
  popd
done

