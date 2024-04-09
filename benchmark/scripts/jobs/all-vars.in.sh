
### HPC Manager
if [ "$HPC_MANAGER" = "slurm" ]; then
  export BM_UNIQUE_UID=${SLURMD_NODENAME}-${SLURM_LOCALID}
  export BM_NUM_TASKS=${SLURM_JOB_NUM_NODES}
  export BM_NODENAME=${SLURMD_NODENAME}
elif [ "$HPC_MANAGER" = "pbs" ]; then
  export BM_UNIQUE_UID=${PBS_O_HOST}-${PBS_NODENUM}
  #export BM_NUM_TASKS=$(cat $PBS_NODEFILE | wc -l)
  export BM_NODENAME=${PBS_O_HOST}
else
  unknown_hpc_environment
fi

