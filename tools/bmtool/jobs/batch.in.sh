#

. $BM_DIRNAME/include/vars.in.sh
. $BM_DIRNAME/include/dirs-vars.in.sh
. $BM_DIRNAME/include/dirs-cleanup.in.sh

. $BM_DIRNAME/include/dirs-setup.in.sh
. $BM_DIRNAME/include/dirs-config.in.sh 

if [ "$BM_TYPE" = "ior" ]; then
  JOB_BIN="$BM_DIRNAME/jobs/ior-benchmark.sh"
  . $BM_DIRNAME/jobs/ior-vars.in.sh
  . $BM_DIRNAME/jobs/ior-setup.in.sh
elif [ "$BM_TYPE" = "lsmio" ]; then
  JOB_BIN="$BM_DIRNAME/jobs/lsmio-benchmark.sh"
  . $BM_DIRNAME/jobs/lsmio-vars.in.sh
  . $BM_DIRNAME/jobs/lsmio-setup.in.sh
elif [ "$BM_TYPE" = "lmp" ]; then
  JOB_BIN="$BM_DIRNAME/jobs/lmp-benchmark.sh"
  . $BM_DIRNAME/jobs/lmp-vars.in.sh
  . $BM_DIRNAME/jobs/lmp-setup.in.sh
else
  echo "Please pass either ior, lmp or lsmio as argument."
  exit
fi

for rf in 16 4
do
  for bs in 8M 1M 64K
  do

    if [ "$BM_TYPE" = "lmp" ]; then
      rm ~/scratch/benchmark/lmp/outputs/*
      cp -r lmp-reaxff $DIRS_BM_BASE/c$rf/b$bs/
    fi

    if [ "$HPC_MANAGER" = "slurm" ]; then
      srun ${JOB_BIN} $rf $bs --export=ALL
    elif [ "$HPC_MANAGER" = "pbs" ]; then
      aprun -n $BM_NUM_TASKS -N $BM_NUM_CORES ${JOB_BIN} $rf $bs
    else
      unknown_hpc_environment
    fi

    sleep 3

  done
done


