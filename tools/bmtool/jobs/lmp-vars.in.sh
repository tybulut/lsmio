#
LMP_DIR=$BM_PATH/lmp
LMP_DIR_OBASE=$LMP_DIR/outputs
# Run index: the node count inside a Slurm allocation, as in lsmio-vars.in.sh
LMP_DIR_IDX=${SLURM_JOB_NUM_NODES:-$BM_NUM_TASKS}
LMP_DIR_OUTPUT=$LMP_DIR_OBASE/${LMP_DIR_IDX}/$DS
#
