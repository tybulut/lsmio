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

  # Dynamic Walltime Scaling & Explicit Override (INV-PAIR-1)
  if [ -n "$BM_WALLHOUR_OVERRIDE" ] || [ -n "$BM_WALLHOUR" ]; then
    _user_hours="${BM_WALLHOUR_OVERRIDE:-$BM_WALLHOUR}"
    if [ "$_user_hours" -lt 1 ]; then
      wallhour=1
    elif [ "$_user_hours" -gt 48 ]; then
      wallhour=48
    else
      wallhour=$_user_hours
    fi
  elif [ "$BM_SCALE" = "baseline" ] && [ "$BM_TYPE" = "lsmio" ] && [ "$BM_VERSIONED" = "yes" ]; then
    if [ -n "$EXPANDED_VARIANTS" ] && [ "$EXPANDED_VARIANTS" != "default" ] && [ "$EXPANDED_VARIANTS" != "base" ]; then
      if [ -z "$VAR_COUNT" ] || [ "$VAR_COUNT" -le 0 ]; then
        _cnt=0
        _r="$EXPANDED_VARIANTS"
        while [ -n "$_r" ]; do
          case "$_r" in
            *,*) _cnt=$(( _cnt + 1 )); _r="${_r#*,}" ;;
            *) _cnt=$(( _cnt + 1 )); _r="" ;;
          esac
        done
        total_runs=$(( 1 + _cnt ))
      else
        total_runs=$(( 1 + VAR_COUNT ))
      fi
    else
      total_runs=2
    fi
    # 120 min per baseline run (maximum safety margin for 64K workloads) + 2 hours base headroom
    calculated_hours=$(( 2 + total_runs * 2 ))
    if [ "$calculated_hours" -lt 4 ]; then
      wallhour=4
    elif [ "$calculated_hours" -gt 48 ]; then
      wallhour=48
    else
      wallhour=$calculated_hours
    fi
  elif [ "$BM_SCALE" = "baseline" ] && [ "$BM_TYPE" = "lsmio" ] && [ -n "$EXPANDED_VARIANTS" ] && [ "$EXPANDED_VARIANTS" != "default" ]; then
    if [ -z "$VAR_COUNT" ] || [ "$VAR_COUNT" -le 0 ]; then
      _cnt=0
      _r="$EXPANDED_VARIANTS"
      while [ -n "$_r" ]; do
        case "$_r" in
          *,*) _cnt=$(( _cnt + 1 )); _r="${_r#*,}" ;;
          *) _cnt=$(( _cnt + 1 )); _r="" ;;
        esac
      done
      total_runs=$(( 1 + _cnt ))
    else
      total_runs=$(( 1 + VAR_COUNT ))
    fi
    # 120 min per run (maximum safety margin for 64K workloads) + 2 hours base headroom
    calculated_hours=$(( 2 + total_runs * 2 ))
    if [ "$calculated_hours" -lt 4 ]; then
      wallhour=4
    elif [ "$calculated_hours" -gt 48 ]; then
      wallhour=48
    else
      wallhour=$calculated_hours
    fi
  else
    wallhour=`echo "2 + ($nodes / 3)" | bc`
  fi

  if [ "$QSUBMIT" = "sbatch" ]; then
    # ARCHER2's standard partition allocates whole nodes and rejects --mem;
    # other Slurm sites need an explicit per-job memory request.
    if [ "$HPC_ENV" = "archer2" ]; then
      SBATCH_EXTRA="--partition=standard --qos=standard"
    else
      SBATCH_EXTRA="--mem=8gb"
    fi
    sbatch \
      $SBATCH_EXTRA \
      --export=ALL \
      --ntasks=$concurrency \
      --nodes=$nodes \
      --job-name=LSMIO-SM-$BM_TYPE-$concurrency \
      --time=$wallhour:00:00 \
      --account="$SB_ACCOUNT" \
      --mail-user="$SB_EMAIL" \
      ${job_script}.sbatch
  else
    export BM_NUM_TASKS=$concurrency
    export BM_NUM_CORES=$pernode

    cd $BM_DIRNAME
    qsub \
      -v BM_SCRIPT,BM_DIRNAME,BM_CMD,BM_TYPE,BM_SCALE,BM_SSD,BM_NUM_TASKS,BM_NUM_CORES,BM_VARIANT,BM_SETUP,BM_PAIRED_RUN,EXPANDED_VARIANTS,DO_ARCHIVE,BM_RESUME,BM_ARCHIVE_DEST,VAR_COUNT,BM_WALLHOUR_OVERRIDE,BM_VERSIONED \
      -l select=$concurrency:mem=32GB \
      ${job_script}.pbs
  fi
}

wait_for_completion() {
  set +x
  while [ 1 ];
  do
    if [ "$QMANAGER" = "squeue" ]; then
      $QMANAGER -u $USER --format="%.15i %.9P %.20j %.8u %.8T %.10M %.9l %.6D %R"
    else
      $QMANAGER -u $USER
    fi

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
  for concurrency in 1 2 4 8
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

run_baseline_job() {
  concurrency=8
  pernode=1
  batch_run $concurrency $pernode $BM_DIRNAME/jobs/job-small
  wait_for_completion
}


