#
LSM_DIR=$BM_PATH/lsmio
LSM_DIR_OBASE=$LSM_DIR/outputs
# Index n of one run's outputs, $LSM_DIR_OBASE/<n>. Inside a Slurm allocation it is the node
# count, which is also the ranks' BM_NUM_TASKS (job-all.in.sh); batch.in.sh's own BM_NUM_TASKS
# is the task count, which differs at more than one task per node
LSM_DIR_IDX=${SLURM_JOB_NUM_NODES:-$BM_NUM_TASKS}
LSM_DIR_OUTPUT=$LSM_DIR_OBASE/${LSM_DIR_IDX}/$DS
#
