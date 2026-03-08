#!/bin/sh

RSIZE="$1"
RSEQ="$2"

if [ -z "$1" ]; then
  RSIZE="small"
fi
if [ -z "$2" ]; then
  RSEQ="01"
fi

NTASKS=4
TASKPERNODE=1
if [ "$RSIZE" = "large" ]; then
  NTASKS=64
  TASKPERNODE=8
fi

# Modules: viking2
module purge
module load GCCcore/12.3.0
module load CMake/3.26.3-GCCcore-12.3.0
module load Automake/1.16.5-GCCcore-12.3.0
module load Autoconf/2.71-GCCcore-12.3.0
module load libtool/2.4.7-GCCcore-12.3.0
module load OpenMPI/4.1.5-GCC-12.3.0
module load zlib/1.2.13-GCCcore-12.3.0
module load lz4/1.9.4-GCCcore-12.3.0
module load libunwind/1.6.2-GCCcore-12.3.0
module load OpenJPEG/2.5.0-GCCcore-12.3.0
module load FFTW/3.3.10-GCC-12.3.0
module load gflags/2.2.2-GCCcore-12.3.0
module load bzip2/1.0.8-GCCcore-12.3.0
module load HDF5/1.14.0-gompi-2023a
module load SciPy-bundle/2023.07-gfbf-2023a
module load matplotlib/3.7.2-gfbf-2023a
module load Perl/5.36.1-GCCcore-12.3.0
module load Perl-bundle-CPAN/5.36.1-GCCcore-12.3.0
module load gnuplot/5.4.8-GCCcore-12.3.0
module load texlive/20230313-GCC-12.3.0

set -x
module list

# Clean-up
/usr/bin/rm -rf logs
/usr/bin/rm -rf output
mkdir -p logs
mkdir -p output
/usr/bin/cp -f ~/src/decks/input-posix-$RSIZE.deck output/input.deck

# Command to run
export DARSHAN_LOGPATH=$HOME/scratch/darshan
LD_PRELOAD=$HOME/src/usr/lib/libdarshan.so \
sbatch \
  --export=ALL \
  --ntasks=$NTASKS \
  --ntasks-per-node=$TASKPERNODE \
  --cpus-per-task=1 \
  --job-name=SERDAR-EPOC2D-4 \
  --time=4:00:00 \
  --mail-user="sb2984@york.ac.uk" \
  benchmark.sbatch

#  --account="cs-cshpc-2019" \
set +x

sleep 1
while [ 1 ];
do
  squeue -u $USER --format="%.15i %.9P %.20j %.8u %.8T %.10M %.9l %.6D %R"
  JOB_RUNNING=`squeue -u $USER | grep -v JOBID`
  if [ -z "$JOB_RUNNING" ]; then
    break
  fi

  sleep 8
done

OUTDIR="$DARSHAN_LOGPATH/epoch2d-$RSIZE-$RSEQ"

mkdir -p $OUTDIR
sync;sync;sleep 1

ls -la output/ > $OUTDIR/files.txt
/usr/bin/cp -f output/epoch2d.dat $OUTDIR/
/usr/bin/cp -f output/input.deck $OUTDIR/
/usr/bin/cp -f logs/sbatch-*.log $OUTDIR/
/usr/bin/mv  $DARSHAN_LOGPATH/sb2984_epoch2d_*.darshan $OUTDIR/


