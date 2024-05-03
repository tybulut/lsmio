#
. vars.in.sh

run_mpi_bench() {
  srun -n 16 ./mpiBench -b 0 -e 1K -i 1000 -m 1G > output.txt
  crunch_mpiBench output.txt
}

