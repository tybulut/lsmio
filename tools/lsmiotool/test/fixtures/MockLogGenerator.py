#
# Copyright 2023 Serdar Bulut
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived from
#    this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#

import os
from typing import Dict, List, Optional, Any


class MockLogGenerator:
    """Fixture class to programmatically write fake IOR, LSMIO, and LMP logs."""

    m_base_dir: str

    def __init__(self, f_base_dir: str = "") -> None:
        """Initialize MockLogGenerator.

        Args:
            f_base_dir: Root base directory for generated mock files.
        """
        self.m_base_dir = f_base_dir

    def generateIorFile(
        self,
        f_file_path: str,
        f_node_count: int = 1,
        f_stripe_count: int = 4,
        f_stripe_size: str = "64K",
        f_write_max: float = 1200.5,
        f_read_max: float = 4500.2,
    ) -> str:
        """Generate a mock IOR output log file.

        Args:
            f_file_path: Destination path.
            f_node_count: Number of nodes.
            f_stripe_count: Stripe count.
            f_stripe_size: Stripe size.
            f_write_max: Max write MiB/s.
            f_read_max: Max read MiB/s.

        Returns:
            Absolute path to the created file.
        """
        os.makedirs(os.path.dirname(os.path.abspath(f_file_path)), exist_ok=True)
        content = f"""IOR-3.3.0: MPI Coordinated Test of Parallel I/O
Summary of all tests:
Operation   Max(MiB)   Min(MiB)  Mean(MiB)     StdDev   Max(OPs)   Min(OPs)  Mean(OPs)     StdDev    Mean(s) Stonewall(s) Stonewall(MiB) Test# #Tasks tPN reps fPP reord reordoff reordrand seed segcnt   blksiz    xsize aggs(MiB)   API RefNum
write        {f_write_max:.2f}     800.10    1000.25     120.30    {f_write_max:.2f}     800.10    1000.25     120.30    0.15000         NA            NA     0      {f_node_count}   1   10   0     0        1         0    0    128  1048576  1048576     512.0 POSIX      0
read        {f_read_max:.2f}    3200.40    3900.50     310.20   {f_read_max:.2f}    3200.40    3900.50     310.20    0.03500         NA            NA     0      {f_node_count}   1   10   0     0        1         0    0    128  1048576  1048576     512.0 POSIX      0
Finished
"""
        with open(f_file_path, "w") as f:
            f.write(content)
        return f_file_path

    def generateLsmioFile(
        self,
        f_file_path: str,
        f_node_count: int = 1,
        f_stripe_count: int = 4,
        f_stripe_size: str = "64K",
        f_write_bw: float = 167.46,
        f_read_bw: float = 320.78,
        f_write_iters: Optional[List[float]] = None,
        f_read_iters: Optional[List[float]] = None,
    ) -> str:
        """Generate a mock LSMIO output log file with iterations and summaries.

        Args:
            f_file_path: Destination path.
            f_node_count: Number of nodes.
            f_stripe_count: Stripe count.
            f_stripe_size: Stripe size.
            f_write_bw: Benchmark summary write bandwidth in MiB/s.
            f_read_bw: Benchmark summary read bandwidth in MiB/s.
            f_write_iters: List of iteration write bandwidths.
            f_read_iters: List of iteration read bandwidths.

        Returns:
            Absolute path to the created file.
        """
        os.makedirs(os.path.dirname(os.path.abspath(f_file_path)), exist_ok=True)
        w_iters = f_write_iters or [150.0 + i * 2.0 for i in range(10)]
        r_iters = f_read_iters or [300.0 + i * 3.0 for i in range(10)]

        w_iter_lines = "\n".join(
            [
                f"iwrite,{bw:.2f},1.500,1048576,1048576,{i}"
                for i, bw in enumerate(w_iters)
            ]
        )
        r_iter_lines = "\n".join(
            [
                f"iread,{bw:.2f},0.800,1048576,1048576,{i}"
                for i, bw in enumerate(r_iters)
            ]
        )

        content = f"""BENCHMARK PARAMETERS: 
 fileName: /tmp/mock.bp
 iterations: 10
BENCHMARK RESULTS: 

Iteration-WRITE: AdiosDB SYN: false Plg: false
access,bw(MiB/s),Latency(ms),block(KiB),xfer(KiB),iter
------,---------,----------,----------,---------,----
{w_iter_lines}

Bench-WRITE: AdiosDB SYN: false Plg: false
access,bw(MiB/s),Latency(ms),block(KiB),xfer(KiB),iter
------,---------,----------,----------,---------,----
write,{f_write_bw:.2f},1.529,1048576,1048576,10

Iteration-READ: AdiosDB SYN: false Plg: false
access,bw(MiB/s),Latency(ms),block(KiB),xfer(KiB),iter
------,---------,----------,----------,---------,----
{r_iter_lines}

Bench-READ: AdiosDB SYN: false Plg: false
access,bw(MiB/s),Latency(ms),block(KiB),xfer(KiB),iter
------,---------,----------,----------,---------,----
read,{f_read_bw:.2f},0.798,1048576,1048576,10
"""
        with open(f_file_path, "w") as f:
            f.write(content)
        return f_file_path

    def generateLmpFile(
        self,
        f_file_path: str,
        f_node_count: int = 1,
        f_stripe_count: int = 4,
        f_stripe_size: str = "64K",
        f_throughput: float = 123.45,
    ) -> str:
        """Generate a mock LMP output log file.

        Args:
            f_file_path: Destination path.
            f_node_count: Number of nodes.
            f_stripe_count: Stripe count.
            f_stripe_size: Stripe size.
            f_throughput: Throughput metric in MiB/s.

        Returns:
            Absolute path to the created file.
        """
        os.makedirs(os.path.dirname(os.path.abspath(f_file_path)), exist_ok=True)
        content = f""".write, bw: {f_throughput:.2f}, total: 1024MB
write,{f_stripe_size},{f_throughput:.2f}
"""
        with open(f_file_path, "w") as f:
            f.write(content)
        return f_file_path

    def generateMockDirectoryTree(
        self,
        f_base_dir: str,
        f_bench_type: str = "lsmio",
        f_nodes: Optional[List[str]] = None,
        f_stripes: Optional[List[str]] = None,
        f_sizes: Optional[List[str]] = None,
        f_date: str = "2023-07-01",
    ) -> str:
        """Generate a full directory structure with mock logs for testing.

        Args:
            f_base_dir: Root directory path.
            f_bench_type: Benchmark type ('ior', 'lsmio', 'lmp').
            f_nodes: List of node counts.
            f_stripes: List of stripe counts.
            f_sizes: List of stripe sizes.
            f_date: Date string for directory folder.

        Returns:
            Root directory path.
        """
        nodes = f_nodes or ["1", "2"]
        stripes = f_stripes or ["4", "16"]
        sizes = f_sizes or ["64K", "1M", "8M"]

        for n in nodes:
            n_int = int(n)
            for rf in stripes:
                for bs in sizes:
                    for task_id in range(n_int):
                        file_name = f"out-{f_bench_type}-{rf}-{bs}-{f_date}-node{task_id:03d}-0.txt.2"
                        file_path = os.path.join(f_base_dir, n, f_date, file_name)
                        if f_bench_type == "ior":
                            self.generateIorFile(file_path, n_int, int(rf), bs)
                        elif f_bench_type == "lsmio":
                            self.generateLsmioFile(file_path, n_int, int(rf), bs)
                        elif f_bench_type == "lmp":
                            self.generateLmpFile(file_path, n_int, int(rf), bs)
        return f_base_dir

    def generateMockFile(
        self, f_file_name: str, f_bench_type: str = "lsmio", **kwargs: Any
    ) -> str:
        """Generate a single mock file based on benchmark type.

        Args:
            f_file_name: Destination path.
            f_bench_type: Type of log file ('ior', 'lsmio', 'lmp').
            **kwargs: Additional parameters for the generator.

        Returns:
            Absolute path to created file.
        """
        if f_bench_type == "ior":
            return self.generateIorFile(f_file_name, **kwargs)
        elif f_bench_type == "lmp":
            return self.generateLmpFile(f_file_name, **kwargs)
        return self.generateLsmioFile(f_file_name, **kwargs)
