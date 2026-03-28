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
if hostname | egrep '^xci|^nid'; then
  HPC_ENV="isambard"
  HPC_MANAGER="pbs"
elif hostname | grep -w viking; then
  HPC_ENV="viking"
  HPC_MANAGER="slurm"
elif hostname | grep -w viking2; then
  HPC_ENV="viking2"
  HPC_MANAGER="slurm"
elif groups | grep -w archer2; then
  HPC_ENV="archer2"
  HPC_MANAGER="slurm"
else
  unknown_hpc_environment
fi

### LUSTRE
if [ "$HPC_ENV" = "isambard" ]; then
  export LUSTRE_HDD_PATH=/projects/external/$USER
  export LUSTRE_SSD_PATH=/scratch/$USER
elif [ "$HPC_ENV" = "viking" ]; then
  export LUSTRE_HDD_PATH=/mnt/lustre/users/$USER
  export LUSTRE_SSD_PATH=/mnt/bb/tmp/users/$USER
elif [ "$HPC_ENV" = "viking2" ]; then
  export LUSTRE_HDD_PATH=/mnt/scratch/users/$USER
  export LUSTRE_SSD_PATH=/mnt/scratch/users/$USER
elif [ "$HPC_ENV" = "archer2" ]; then
  export LUSTRE_HDD_PATH=/work/e281/e281/$USER
  export LUSTRE_SSD_PATH=/scratch-nvme/e281/e281/$USER
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
export BM_PATH=$LUSTRE_PATH/benchmark

