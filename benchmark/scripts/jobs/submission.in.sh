#

wait_for_completion() {
  set +x
  while [ 1 ];
  do
    squeue -u $USER

    JOB_RUNNING=`squeue -u $USER | grep -v JOBID`
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
    nodes=$concurrency
    sbatch --ntasks=$concurrency --nodes=$nodes \
      --account="$SB_ACCOUNT" --mail-user="$SB_EMAIL" \
      $BM_DIRNAME/jobs/job-small.sbatch --export=ALL
    wait_for_completion
  done
}

run_bake_job() {
  for concurrency in 4
  do
    nodes=$concurrency
    sbatch --ntasks=$concurrency --nodes=$nodes \
      --account="$SB_ACCOUNT" --mail-user="$SB_EMAIL" \
      $BM_DIRNAME/jobs/job-small.sbatch --export=ALL
    wait_for_completion
  done
}

run_small_job() {
  for concurrency in 1 2 4 8 16 24 32 40 48
  do
    nodes=$concurrency
    sbatch --ntasks=$concurrency --nodes=$nodes \
      --account="$SB_ACCOUNT" --mail-user="$SB_EMAIL" \
      $BM_DIRNAME/jobs/job-small.sbatch --export=ALL
    wait_for_completion
  done
}

run_large_job() {
  for concurrency in 4 8 16 32 64 128 192 256
  do
    nodes=`echo "$concurrency / 4" | bc`
    sbatch --ntasks=$concurrency --nodes=$nodes \
      --account="$SB_ACCOUNT" --mail-user="$SB_EMAIL" \
      $BM_DIRNAME/jobs/job-large.sbatch --export=ALL
    wait_for_completion
  done
}

