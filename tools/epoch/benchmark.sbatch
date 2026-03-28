#!/bin/sh -x
#SBATCH --mail-type=END,FAIL
#SBATCH --mem=32gb
#SBATCH --distribution=cyclic:cyclic
#SBATCH --output=logs/sbatch-%j.log
#SBATCH --error=logs/sbatch-%j.err

./benchmark.sh
