### BASE
export DS=`date +"%F"`

unknown_hpc_environment() {
  echo "############################################"
  echo "# ERROR: Unknown HPC Environment           #"
  echo "############################################"
  # Fail fast when run as a script (bmtool, batch jobs); only warn when these
  # fragments are sourced into an interactive shell, so we don't kill it.
  case $- in
    *i*) return 1 ;;
    *) exit 1 ;;
  esac
}

### HPC ENV
HPC_MANAGER="slurm"
export PROJECT_DIR=$HOME/src/usr
if hostname | grep -qw viking; then
  HPC_ENV="viking"
elif hostname | grep -qw viking2; then
  HPC_ENV="viking2"
elif groups | grep -qw archer2; then
  HPC_ENV="archer2"
  export PROJECT_DIR=/work/e281/e281/$USER/usr
elif hostname | grep -qE '^xci|^nid'; then
  HPC_ENV="isambard"
  HPC_MANAGER="pbs"
else
  unknown_hpc_environment
fi

#
export SB_BIN=$PROJECT_DIR/bin
case ":$LD_LIBRARY_PATH:" in
  *":$PROJECT_DIR/lib:"*) ;;
  *) export LD_LIBRARY_PATH=$PROJECT_DIR/lib:$PROJECT_DIR/lib64:$LD_LIBRARY_PATH ;;
esac
export ADIOS2_PLUGIN_PATH=$PROJECT_DIR/lib

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

