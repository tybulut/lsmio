#!/bin/sh -x
#SBATCH --mail-type=END,FAIL
#SBATCH --job-name=LSMIO-SM
#SBATCH --mem=8gb
#SBATCH --ntasks-per-node=1
#SBATCH --ntasks-per-socket=1
#SBATCH --cpus-per-task=1
#SBATCH --distribution=cyclic:cyclic
#SBATCH --output=logs/sbatch-lsmio-%j.log
#SBATCH --error=logs/sbatch-lsmio-%j.err

. $BM_DIRNAME/jobs/batch.in.sh

