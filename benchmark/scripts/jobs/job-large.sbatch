#!/bin/sh -x
#SBATCH --mail-type=END,FAIL
#SBATCH --job-name=LSMIO-LG
#SBATCH --time=24:00:00
#SBATCH --mem=8gb
#SBATCH --ntasks-per-node=4
#SBATCH --ntasks-per-socket=2
#SBATCH --ntasks-per-core=1
#SBATCH --distribution=cyclic:cyclic
#SBATCH --output=logs/sbatch-lsmio-%j.log
#SBATCH --error=logs/sbatch-lsmio-%j.err

. $BM_DIRNAME/jobs/batch.in.sh

