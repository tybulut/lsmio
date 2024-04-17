
### HPC Manager
if [ "$HPC_MANAGER" = "slurm" ]; then
  export BM_NUM_CORES=1
  export BM_NUM_TASKS=${SLURM_JOB_NUM_NODES}
  export BM_NODENAME=${SLURMD_NODENAME}
  export BM_UNIQUE_UID=${SLURMD_NODENAME}-${SLURM_LOCALID}
elif [ "$HPC_MANAGER" = "pbs" ]; then
  # Will be filled before QSUB
  #export BM_NUM_CORES=
  #export BM_NUM_TASKS=
  export BM_NODENAME=`hostname`
  export BM_UNIQUE_UID=${BM_NODENAME}-${ALPS_APP_PE}
else
  unknown_hpc_environment
fi

