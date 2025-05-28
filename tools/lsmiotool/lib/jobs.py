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
import shlex
import shutil
import socket
import subprocess
import time
import getpass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

from lsmiotool.lib import debuggable, dirs, env, hpc, log
from lsmiotool.lib.env import HpcManager


class JobSize(Enum):
    SMALL = "SMALL"
    LARGE = "LARGE"

def setup_job_environment_and_dirs(bm_path: str) -> Dict[str, str]:
    """
    Set up environment variables and all required directories for the benchmark.
    This should be called before any job is run.

    Args:
        bm_path: Base path for benchmark directories

    Returns:
        Dictionary of directory paths
    """
    # Environment setup (calls env.py logic)
    # If env exposes a setup function, call it here (else rely on import side-effects)
    # Directory setup (calls dirs.py logic)
    dirs.setup_data_dirs(bm_path)
    all_dirs = dirs.get_dirs(bm_path)
    return all_dirs


def batch_job_orchestration(
    bm_type: str,
    bm_path: str,
    hpc_manager: HpcManager,
    ds: str
) -> None:
    """
    Orchestrate batch job submission as in batch.in.sh.
    For each rf/bs combination, runs the appropriate benchmark script
    with correct arguments.

    Args:
        bm_type: Type of benchmark to run
        bm_path: Base path for benchmark directories
        hpc_manager: HPC job manager to use (slurm/pbs)
        ds: Dataset size
    """
    # Ensure environment and directories are set up before running jobs
    all_dirs: Dict[str, str] = setup_job_environment_and_dirs(bm_path)
    rf_list: List[int] = [16, 4]
    bs_list: List[str] = ["8M", "1M", "64K"]
    for rf in rf_list:
        for bs in bs_list:
            if bm_type == "lmp":
                # Use managed output directory from dirs module
                lmp_outputs = all_dirs.get(
                    "LMP_DIR_OUTPUT",
                    os.path.expanduser("~/scratch/benchmark/lmp/outputs")
                )
                if os.path.isdir(lmp_outputs):
                    shutil.rmtree(lmp_outputs)
                lmp_reaxff = os.path.join(bm_path, "lmp-reaxff")
                shutil.copytree(lmp_reaxff, lmp_outputs)
            if hpc_manager == HpcManager.SLURM:
                subprocess.run([
                    "srun",
                    f"{bm_path}/jobs/{bm_type}-benchmark.sh",
                    str(rf),
                    bs,
                    "--export=ALL",
                ])
            elif hpc_manager == HpcManager.PBS:
                num_tasks = os.environ.get("BM_NUM_TASKS", "1")
                num_cores = os.environ.get("BM_NUM_CORES", "1")
                subprocess.run([
                    "aprun",
                    "-n",
                    str(num_tasks),
                    "-N",
                    str(num_cores),
                    f"{bm_path}/jobs/{bm_type}-benchmark.sh",
                    str(rf),
                    bs,
                ])
            elif hpc_manager == HpcManager.DEV:
                subprocess.run([
                    f"{bm_path}/jobs/{bm_type}-benchmark.sh",
                    str(rf),
                    bs,
                ])
            else:
                raise RuntimeError(f"Unknown HPC manager: {hpc_manager}")
            time.sleep(3)


class JobScriptGenerator(debuggable.DebuggableObject):
    """
    Generates job scripts for PBS and SBATCH schedulers.
    """
    @staticmethod
    def generate_pbs_script(
        queue: str = "arm",
        name: str = "LSMIO-LG",
        walltime: str = "6:00:00",
        output_dir: str = "logs",
        batch_in_sh: str = "$BM_DIRNAME/jobs/batch.in.sh"
    ) -> str:
        """
        Generate PBS job script.

        Args:
            queue: PBS queue name
            name: Job name
            walltime: Wall clock time limit
            output_dir: Directory for output files
            batch_in_sh: Path to batch input script

        Returns:
            Generated PBS script content
        """
        return f"""#!/bin/sh -x
#PBS -q {queue}
#PBS -m abe
#PBS -N {name}
#PBS -l walltime={walltime}
#PBS -o {output_dir}/
#PBS -e {output_dir}/

. {batch_in_sh}
"""

    @staticmethod
    def generate_sbatch_script(
        mail_type: str = "END,FAIL",
        mem: str = "8gb",
        ntasks_per_node: int = 4,
        ntasks_per_socket: int = 2,
        ntasks_per_core: int = 1,
        distribution: str = "cyclic:cyclic",
        output: str = "logs/sbatch-lsmio-%j.log",
        error: str = "logs/sbatch-lsmio-%j.err",
        batch_in_sh: str = "$BM_DIRNAME/jobs/batch.in.sh"
    ) -> str:
        """
        Generate SLURM job script.

        Args:
            mail_type: Mail notification type
            mem: Memory per node
            ntasks_per_node: Number of tasks per node
            ntasks_per_socket: Number of tasks per socket
            ntasks_per_core: Number of tasks per core
            distribution: Task distribution
            output: Output file path
            error: Error file path
            batch_in_sh: Path to batch input script

        Returns:
            Generated SLURM script content
        """
        return f"""#!/bin/sh -x
#SBATCH --mail-type={mail_type}
#SBATCH --mem={mem}
#SBATCH --ntasks-per-node={ntasks_per_node}
#SBATCH --ntasks-per-socket={ntasks_per_socket}
#SBATCH --ntasks-per-core={ntasks_per_core}
#SBATCH --distribution={distribution}
#SBATCH --output={output}
#SBATCH --error={error}

. {batch_in_sh}
"""

    @staticmethod
    def get_unique_uid() -> str:
        if hpc_manager == HpcManager.SLURM:
            return "${SLURMD_NODENAME}-${SLURM_LOCALID}"
        elif hpc_manager == HpcManager.PBS:
            return "${BM_NODENAME}-${ALPS_APP_PE}"
        elif hpc_manager == HpcManager.DEV:
            return "${BM_NODENAME}-DEV"
        else:
            raise RuntimeError(f"get_unique_uid: Unknown HPC manager: {hpc_manager}")



class IORBenchmark(debuggable.DebuggableObject):
    """
    Encapsulates logic for running IOR benchmarks (ported from ior-benchmark.sh).
    """
    bm_setup: str
    sb_bin: str
    dirs_bm_base: str
    ior_dir_output: str
    bm_unique_uid: str
    ds: str

    def __init__(
        self,
        bm_setup: str = "BASE",
        sb_bin: Optional[str] = None,
        dirs_bm_base: Optional[str] = None,
        ior_dir_output: Optional[str] = None
    ) -> None:
        """Initialize IORBenchmark with setup and environment variables."""
        self.bm_setup = bm_setup
        self.sb_bin = sb_bin or os.environ.get("SB_BIN", "")
        self.dirs_bm_base = dirs_bm_base or os.environ.get("DIRS_BM_BASE", "")
        self.ior_dir_output = ior_dir_output or os.environ.get("IOR_DIR_OUTPUT", "")
        self.bm_unique_uid = env.BM_UNIQUE_UID
        self.ds = env.DATE_STAMP


    def run(self, rf: str, bs: str) -> subprocess.CompletedProcess:
        """Run the IOR benchmark for the given rf and bs."""
        sg: str
        infix: str
        out_file: str
        log_file: str
        base_cmd: List[str]
        cmd: List[str]

        if bs == "64K":
            sg = "16384"
        elif bs == "1M":
            sg = "1024"
        else:
            sg = "128"
        infix = self.bm_setup.lower()
        out_file = f"{self.dirs_bm_base}/c{rf}/b{bs}/ior.{infix}"
        log_file = (
            f"{self.ior_dir_output}/out-{infix}-{rf}-{bs}-"
            f"{self.ds}-{self.bm_unique_uid}.txt"
        )
        log_file = os.path.expanduser(log_file)
        log_file = os.path.expandvars(log_file)
        sb_exe = os.path.expanduser(f"{self.sb_bin}/ior")
        base_cmd = [
            sb_exe,
            "-v",
            "-w",
            "-r",
            "-i=10",
            "-o",
            out_file,
            f"-t={bs}",
            f"-b={bs}",
            f"-s={sg}"
        ]
        if self.bm_setup == "HDF5":
            cmd = base_cmd + ["-a", "HDF5"]
        elif self.bm_setup == "HDF5-C":
            cmd = base_cmd + ["-c", "-a", "HDF5"]
        elif self.bm_setup == "COLLECTIVE":
            cmd = base_cmd + ["-c", "-a", "MPIIO"]
        elif self.bm_setup == "FSYNC":
            cmd = base_cmd + ["-e"]
        elif self.bm_setup == "REVERSE":
            cmd = base_cmd + ["-C"]
        else:
            cmd = base_cmd
        hpc_env = env.HPC_ENV
        command = " ".join(cmd)
        #command = " ".join(shlex.quote(os.path.expandvars(os.path.expanduser(arg))) for arg in cmd)
        commands = "#!/bin/bash -x\n" \
            + f"\n{command}"
        log.Console.debug(f"IORBenchmark cmd: {cmd}")
        log.Console.debug(f"IORBenchmark commands: \n{commands}")
        log.Console.debug(f"IORBenchmark log file: {log_file}")
        with open(log_file, "a+") as logf:
            result = subprocess.run(["/bin/bash", "-c", commands], stdout=logf, stderr=subprocess.STDOUT, text=True, check=True)
        return result


class LMPBenchmark(debuggable.DebuggableObject):
    """
    Encapsulates logic for running LMP benchmarks (ported from lmp-benchmark.sh).
    """
    bm_setup: str
    sb_bin: str
    dirs_bm_base: str
    lmp_dir_output: str
    bm_unique_uid: str
    ds: str
    bm_num_tasks: int

    def __init__(
        self,
        bm_setup: str = "LSMIO",
        sb_bin: Optional[str] = None,
        dirs_bm_base: Optional[str] = None,
        lmp_dir_output: Optional[str] = None,
        bm_num_tasks: Optional[int] = None
    ) -> None:
        """Initialize LMPBenchmark with setup and environment variables."""
        self.bm_setup = bm_setup
        self.sb_bin = sb_bin or os.environ.get("SB_BIN", "")
        self.dirs_bm_base = dirs_bm_base or os.environ.get("DIRS_BM_BASE", "")
        self.lmp_dir_output = lmp_dir_output or os.environ.get("LMP_DIR_OUTPUT", "")
        self.bm_unique_uid = os.environ.get("BM_UNIQUE_UID", "")
        self.ds = os.environ.get("DS", "")
        self.bm_num_tasks = int(bm_num_tasks or os.environ.get("BM_NUM_TASKS", "1"))

    def run(self, rf: str, bs: str) -> subprocess.CompletedProcess:
        """Run the LMP benchmark for the given rf and bs."""
        bsb: str
        sg: str
        rep_lut: Dict[int, Tuple[int, int]] = {
            1: (4, 32),
            2: (5, 32),
            4: (6, 64),
            8: (8, 128),
            16: (10, 256),
            24: (12, 512),
            32: (14, 1024),
            40: (15, 1024),
            48: (16, 1024)
        }
        REP: int
        LSMIO_BUF_MB: int
        infix: str
        log_file: str
        work_dir: str
        cmd: List[str]

        if bs == "64K":
            bsb = "65536"
            sg = "4096"
        elif bs == "1M":
            bsb = "1048576"
            sg = "4096"
        else:
            bsb = "8388608"
            sg = "4096"
        # Set REP and LSMIO_BUF_MB based on BM_NUM_TASKS
        REP, LSMIO_BUF_MB = rep_lut.get(self.bm_num_tasks, (4, 32))
        infix = self.bm_setup.lower()
        log_file = (
            f"{self.lmp_dir_output}/out-lmp-{infix}-{rf}-{bs}-"
            f"{self.ds}-{self.bm_unique_uid}.txt"
        )
        work_dir = os.path.join(self.dirs_bm_base, f"c{rf}/b{bs}/lmp-reaxff")
        os.makedirs(work_dir, exist_ok=True)
        cmd = [
            f"{self.sb_bin}/lmp",
            "-in",
            "in.reaxc.hns",
            "-v",
            "x",
            str(REP),
            "-v",
            "y",
            str(REP),
            "-v",
            "z",
            str(REP)
        ]
        if self.bm_setup == "LSMIO":
            cmd += ["-lsmio-buf-size-mb", str(LSMIO_BUF_MB)]
        elif self.bm_setup == "LSMIO-MMAP":
            cmd += ["-lsmio-mmap", "-lsmio-buf-size-mb", str(LSMIO_BUF_MB)]
        elif self.bm_setup == "FS":
            cmd += ["-lsmio-fallback"]
        with open(log_file, "w") as logf:
            result = subprocess.run(
                cmd,
                cwd=work_dir,
                stdout=logf,
                stderr=subprocess.STDOUT
            )
        return result


class LSMIOBenchmark(debuggable.DebuggableObject):
    """
    Encapsulates logic for running LSMIO benchmarks (ported from lsmio-benchmark.sh).
    """
    bm_setup: str
    sb_bin: str
    dirs_bm_base: str
    lsm_dir_output: str
    bm_unique_uid: str
    ds: str

    def __init__(
        self,
        bm_setup: str = "ADIOS-M",
        sb_bin: Optional[str] = None,
        dirs_bm_base: Optional[str] = None,
        lsm_dir_output: Optional[str] = None
    ) -> None:
        """Initialize LSMIOBenchmark with setup and environment variables."""
        self.bm_setup = bm_setup
        self.sb_bin = sb_bin or os.environ.get("SB_BIN", "")
        self.dirs_bm_base = dirs_bm_base or os.environ.get("DIRS_BM_BASE", "")
        self.lsm_dir_output = lsm_dir_output or os.environ.get("LSM_DIR_OUTPUT", "")
        self.bm_unique_uid = os.environ.get("BM_UNIQUE_UID", "")
        self.ds = os.environ.get("DS", "")

    def run(self, rf: str, bs: str) -> subprocess.CompletedProcess:
        """Run the LSMIO benchmark for the given rf and bs."""
        bsb: str
        sg: str
        infix: str
        out_file: str
        log_file: str
        cmd: List[str]

        # Map block size to numeric values as in the shell script
        if bs == "64K":
            bsb = "65536"
            sg = "65536"
        elif bs == "1M":
            bsb = "1048576"
            sg = "4096"
        else:
            bsb = "8388608"
            sg = "1024"
        infix = self.bm_setup.lower()
        out_file = f"{self.dirs_bm_base}/c{rf}/b{bs}/lsmio-{self.bm_unique_uid}-{infix}.db"
        log_file = (
            f"{self.lsm_dir_output}/out-{infix}-{rf}-{bs}-"
            f"{self.ds}-{self.bm_unique_uid}.txt"
        )

        if self.bm_setup == "ADIOS-M":
            cmd = [
                f"{self.sb_bin}/bm_adios",
                "-m",
                "-g",
                "-i",
                "10",
                "-o",
                out_file,
                "--lsmio-ts",
                bsb,
                "--lsmio-bs",
                bsb,
                "--key-count",
                sg
            ]
        elif self.bm_setup == "PLUGIN-M":
            cmd = [
                f"{self.sb_bin}/bm_adios",
                "-m",
                "-g",
                "-i",
                "10",
                "-o",
                out_file,
                "--lsmio-ts",
                bsb,
                "--lsmio-bs",
                bsb,
                "--key-count",
                sg
            ]
        else:
            raise NotImplementedError(
                f"Benchmark setup {self.bm_setup} not yet implemented."
            )
        with open(log_file, "w") as logf:
            result = subprocess.run(cmd, stdout=logf, stderr=subprocess.STDOUT)
        return result


class JobsRunner(debuggable.DebuggableObject):
    """Manages job submission and execution for different HPC managers."""

    def __init__(
        self,
        hpc_mgr: HpcManager,
        sb_account: Optional[str] = None,
        sb_email: Optional[str] = None,
        bm_type: Optional[str] = None,
        bm_scale: Optional[str] = None,
        bm_ssd: Optional[str] = None
    ) -> None:
        self.hpc_manager = hpc_mgr
        self.slurm_account = sb_account
        self.slurm_email = sb_email
        self.bench_type = bm_type
        self.bench_scale = bm_scale
        self.bench_ssd = bm_ssd

    def run(
        self,
        concurrency: int,
        pernode: int,
        job_size: JobSize
    ) -> None:
        """
        Submit a batch job using sbatch or qsub, ported from submission.in.sh.
        """
        nodes = int(concurrency) // int(pernode)
        wallhour = 2 + (nodes // 3)
        os.environ["BM_NUM_TASKS"] = str(concurrency)
        job_script = job_size.value
        os.chdir(".")
        if self.hpc_manager == HpcManager.SLURM:
            cmd = [
                "sbatch",
                "--export=ALL",
                f"--ntasks={concurrency}",
                f"--nodes={nodes}",
                f"--job-name=LSMIO-SM-{self.bench_scale}-{concurrency}",
                f"--time={wallhour}:00:00",
            ]
            if self.slurm_account:
                cmd.append(f"--account={self.slurm_account}")
            if self.slurm_email:
                cmd.append(f"--mail-user={self.slurm_email}")
            cmd.append(f"{job_script}.sbatch")
            subprocess.run(cmd)
        elif self.hpc_manager == HpcManager.PBS:
            os.environ["BM_NUM_TASKS"] = str(concurrency)
            os.environ["BM_NUM_CORES"] = str(pernode)
            cmd = [
                "qsub",
                "-v",
                "BM_SCRIPT,BM_DIRNAME,BM_CMD,BM_TYPE,BM_SCALE,BM_SSD,"
                "BM_NUM_TASKS,BM_NUM_CORES",
                f"-l select={concurrency}:mem=32GB",
                f"{job_script}.pbs"
            ]
            subprocess.run(cmd)
        elif self.hpc_manager == HpcManager.DEV:
            cmd = [ "echo Hello World" ]
            subprocess.run(cmd)
        else:
            raise RuntimeError(f"Unknown HPC manager: '{self.hpc_manager}'")

    def wait_for_completion(self) -> None:
        """
        Wait for all jobs to complete, ported from submission.in.sh.
        """
        user = getpass.getuser()
        while True:
            if self.hpc_manager == HpcManager.SLURM:
                cmd = [
                    "squeue",
                    "-u",
                    user,
                    "--format=%.15i %.9P %.20j %.8u %.8T %.10M %.9l %.6D %R"
                ]
            elif self.hpc_manager == HpcManager.PBS:
                cmd = ["qstat", "-u", user]
            elif self.hpc_manager == HpcManager.DEV:
                break
            else:
                raise RuntimeError(f"Unknown HPC manager: {self.hpc_manager}")
            proc = subprocess.run(cmd, capture_output=True, text=True)
            lines = [
                l for l in proc.stdout.splitlines()
                if "JOBID" not in l and l.strip()
            ]
            if not lines:
                break
            print(proc.stdout)
            time.sleep(8)
        time.sleep(1)

    def run_bake(self) -> None:
        """Run a bake job with moderate concurrency."""
        for concurrency in [4]:
            pernode = 1
            self.run(
                concurrency,
                pernode,
                JobSize.SMALL
            )
            self.wait_for_completion()

    def run_small(self) -> None:
        """Run small-scale jobs with varying concurrency."""
        for concurrency in [1, 2, 4, 8, 16, 24, 32, 40, 48]:
            pernode = 1
            self.run(
                concurrency,
                pernode,
                JobSize.SMALL
            )
            self.wait_for_completion()

    def run_large(self) -> None:
        """Run large-scale jobs with varying concurrency."""
        for concurrency in [4, 8, 16, 32, 64, 128, 192, 256]:
            pernode = 4
            self.run(
                concurrency,
                pernode,
                JobSize.LARGE
            )
            self.wait_for_completion()

