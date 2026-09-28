# run_tee LOG_FILE CMD [ARGS...]
# Run CMD with stdout+stderr copied to LOG_FILE (like `CMD 2>&1 | tee LOG_FILE`), but return
# CMD's exit status instead of tee's. A plain pipeline reports tee's status (0), so a failed
# benchmark rank would look successful and srun --kill-on-bad-exit would never end the step:
# the surviving ranks then block in MPI until the job's time limit. POSIX sh; no pipefail needed.
run_tee() {
  _rt_log="$1"
  shift
  # Hidden, so a file left behind by a killed rank never matches the parsers' out-*.txt* globs
  _rt_rc_file="$(dirname "$_rt_log")/.$(basename "$_rt_log").rc"
  rm -f "$_rt_rc_file"
  # 2>&1 on CMD only: the shell's own -x trace keeps going to the job's stderr, not LOG_FILE
  { "$@" 2>&1; echo $? > "$_rt_rc_file"; } | tee "$_rt_log"
  # No status file means the command never finished writing one: treat as failure
  _rt_rc=$(cat "$_rt_rc_file" 2>/dev/null)
  rm -f "$_rt_rc_file"
  return "${_rt_rc:-1}"
}
