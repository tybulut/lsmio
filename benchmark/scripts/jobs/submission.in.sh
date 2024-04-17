#

if [ "$HPC_MANAGER" = "slurm" ]; then
  QMANAGER=squeue
  QSUBMIT=sbatch
elif [ "$HPC_MANAGER" = "pbs" ]; then
  QMANAGER=qstat
  QSUBMIT=qsub
else
  unknown_hpc_environment
fi

batch_run() {
  concurrency="$1"
  pernode="$2"
  job_script="$3"

  nodes=`echo "$concurrency / $pernode" | bc`
  export BM_NUM_TASKS=$concurrency

  if [ "$QSUBMIT" = "sbatch" ]; then
    sbatch \
      --export=ALL \
      --ntasks=$concurrency \
      --nodes=$nodes \
      --account="$SB_ACCOUNT" \
      --mail-user="$SB_EMAIL" \
      ${job_script}.sbatch
  else
    export BM_NUM_TASKS=$concurrency
    export BM_NUM_CORES=$pernode

    cd $BM_DIRNAME
    qsub \
      -v BM_SCRIPT,BM_DIRNAME,BM_CMD,BM_TYPE,BM_SCALE,BM_SSD,BM_NUM_TASKS,BM_NUM_CORES \
      -l select=$concurrency:mem=8GB \
      ${job_script}.pbs
  fi
}

wait_for_completion() {
  set +x
  while [ 1 ];
  do
    $QMANAGER -u $USER

    JOB_RUNNING=`$QMANAGER -u $USER | grep -v JOBID`
    if [ -z "$JOB_RUNNING" ]; then
      break
    fi

    sleep 8
  done

  sleep 1
}

run_local_job() {
  for concurrency in 1
  do
    pernode=1
    batch_run $concurrency $pernode $BM_DIRNAME/jobs/job-small
    wait_for_completion
  done
}

run_bake_job() {
  for concurrency in 4
  do
    pernode=1
    batch_run $concurrency $pernode $BM_DIRNAME/jobs/job-small
    wait_for_completion
  done
}

run_small_job() {
  for concurrency in 1 2 4 8 16 24 32 40 48
  do
    pernode=1
    batch_run $concurrency $pernode $BM_DIRNAME/jobs/job-small
    wait_for_completion
  done
}

run_large_job() {
  for concurrency in 4 8 16 32 64 128 192 256
  do
    pernode=4
    batch_run $concurrency $pernode $BM_DIRNAME/jobs/job-large
    wait_for_completion
  done
}

