
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

### Open MPI session directory (Slurm only, as in lsmiotool's Launcher)
# MPI_Init creates a per-node session directory under /tmp by default; a full /tmp on one node
# fails MPI_Init there. Use RAM-backed /dev/shm instead. Its files are small, but they include
# the shared-memory backing files, so they count as RAM, and a killed rank's leftovers stay
# until the site cleans /dev/shm. Open MPI 4.x reads orte_tmpdir_base, also under direct srun
# launch. The prte_ name is for Open MPI 5.x, where it is likely a no-op under direct srun (the
# session directory then comes from Slurm's PMIx server). Other MPI libraries ignore both.
# A value already set in the environment wins.
if [ "$HPC_MANAGER" = "slurm" ]; then
  export OMPI_MCA_orte_tmpdir_base=${OMPI_MCA_orte_tmpdir_base:-/dev/shm}
  export PRTE_MCA_prte_tmpdir_base=${PRTE_MCA_prte_tmpdir_base:-/dev/shm}
fi

