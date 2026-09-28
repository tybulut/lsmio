#
IOR_DIR=$BM_PATH/ior
IOR_DIR_OBASE=$IOR_DIR/outputs
# Run index: the node count inside a Slurm allocation, as in lsmio-vars.in.sh
IOR_DIR_IDX=${SLURM_JOB_NUM_NODES:-$BM_NUM_TASKS}
IOR_DIR_OUTPUT=$IOR_DIR_OBASE/${IOR_DIR_IDX}/$DS
#
