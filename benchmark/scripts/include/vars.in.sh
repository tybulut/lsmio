### BASE
export DS=`date +"%F"`
#
export SB_BIN=$HOME/src/usr/bin
#
export PROJECT_DIR=$HOME/src
if [ -z `echo $LD_LIBRARY_PATH | grep $PROJECT_DIR` ]; then
  export LD_LIBRARY_PATH=$PROJECT_DIR/usr/lib:$PROJECT_DIR/usr/lib64:$LD_LIBRARY_PATH
fi
export ADIOS2_PLUGIN_PATH=$PROJECT_DIR/usr/lib

unknown_hpc_environment() {
  echo "############################################"
  echo "# ERROR: Uknown HPC Environment            #"
  echo "############################################"
}

### HPC ENV
if [ -e /etc/issue.gw4 ] && grep -wq isambard /etc/issue.gw4; then
  HPC_ENV="isambard"
elif [ `hostname | grep -w viking` ]; then
  HPC_ENV="viking"
elif [ `hostname | grep -w viking2` ]; then
  HPC_ENV="viking2"
else
  unknown_hpc_environment
fi

### LUSTRE
if [ "$HPC_ENV" = "isambard" ]; then
  export LUSTRE_HDD_PATH=/projects/external/ri-sbulut
  export LUSTRE_SSD_PATH=/scratch
elif [ "$HPC_ENV" = "viking" ]; then
  export LUSTRE_HDD_PATH=/mnt/lustre
  export LUSTRE_SSD_PATH=/mnt/bb/tmp
elif [ "$HPC_ENV" = "viking2" ]; then
  export LUSTRE_HDD_PATH=/mnt/scratch
  export LUSTRE_SSD_PATH=/mnt/scratch
else
  unknown_hpc_environment
fi

#
if [ "$BM_SSD" = "on" ]; then
  export LUSTRE_PATH=$LUSTRE_SSD_PATH
else
  export LUSTRE_PATH=$LUSTRE_HDD_PATH
fi

#
export BM_PATH=$LUSTRE_PATH/users/$USER/benchmark

### SLURM
#export BM_SLURM_UID=${SLURM_JOB_NUM_NODES}-${SLURMD_NODENAME}-${SLURM_LOCALID}
export BM_SLURM_UID=${SLURMD_NODENAME}-${SLURM_LOCALID}
