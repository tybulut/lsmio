# main/lsmio



## Getting Started

Download links:
```
SSH clone URL: git@github.com:tybulut/lsmio.git
HTTPS clone URL: https://github.com/tybulut/lsmio.git
```

These instructions will get you a copy of the project.


## Prerequisites: Linux/Debian

What packages to install and how to install them.

### OS:
```
DEBIAN-x86-64/stable
```

### Packages:
```
build-essential
cmake autoconf automake gdb git
cpplint libbz2-dev libpython3-dev
libkyotocabinet-dev kyotocabinet-utils
libsnappy-dev sqlite3 libsqlite3-dev
texlive-latex-base texlive-font-utils
texlive-latex-base  texlive-latex-extra texlive-science
libchart-gnuplot-perl libpng-dev
libpod-parser-perl libpod-latex-perl
libhdf5-dev libhdf5-mpi-dev libhdf5-mpich-dev libhdf5-openmpi-dev
openmpi-bin libopenmpi-dev
libgtest-dev googletest-tools googletest
libgoogle-glog-dev libfmt-dev
libgflags-dev libleveldb-dev librocksdb-dev
libadios2-mpi-c++11-dev libcli11-dev
```

### Optional Packages:
```
screen vim wget curl rdate rsync
```

### Other Dependencies:
Darshan should be installed manually if it is not available already on the
system. The remaining dependencies are managed by CMake.
```
- doc/dependencies/11-darshan
```

## Prerequisites: HPC

### OS:
```
Rocky Linux release 8
```

### Modules:
```
./tools/bmtool/bmtool load-modules
```

### Other dependencies:
Not all dependencies are available as modules on Viking cluster. Hence we need
to manually maintain the following dependencies.
```
By default all the packages will be installed with the prefix: $HOME/src
The packages that are listed in doc/dependencies/ directory have the installation 
instructions listed in their respective shell scripts.
In the same directory the dependencies starting with 9 are optional.
```


## Building 

Run build sript:
```
./build.sh <debug|release> [<test|install>]
```

This will create a build in the directory below:
```
./build
```


### Testing

After building, to run the unit tests:
```
cd build
ctest -j8 ..  # to run 8 tests in parallel
```

Alternatively you can build and test together
```
./build.sh <debug|release> test
```

Recommended mount options for testing on a local HDD:
```
mount -o noatime,nodiratime /dev/sda2 /media/400GB
```

## Deployment

Build script makes assumptions on where to install. 
```
./build.sh <debug|release> install
```

If you want to remove the previous files and then install a release version of it
```
./build.sh clean install
```

These instructions will get your copy of the project up and ready to use on your local
machine in $HOME/src prefix directory for development and testing purposes.

## Benchmark Orchestration (`lsmiotool run`)

`lsmiotool run` provides declarative, resilient benchmark orchestration across HPC clusters with native support for Slurm and PBS schedulers.

### CLI Syntax and Usage

```bash
lsmiotool run <benchmark> <scale> [--ssd] [--setup <name>]
```

For legacy migration compatibility, global `--ssd` / `-s` is also accepted:
```bash
lsmiotool --ssd run <benchmark> <scale> [--setup <name>]
```

#### Arguments & Options:
- `<benchmark>`: Benchmark suite to run. Supported values:
  - `ior`: IOR parallel I/O benchmark (default setup: `BASE`).
  - `lsmio`: LSMIO storage engine benchmark (default setup: `NATIVE-M`).
  - `lmp`: LAMMPS ReaxFF molecular dynamics benchmark (default setup: `LSMIO`).
- `<scale>`: Execution scale. Supported values:
  - `local`: 1 task on 1 node (1 task/node).
  - `bake`: 1, 2, 4, 8 tasks on 1, 2, 4, 8 nodes (1 task/node).
  - `small`: 1, 2, 4, 8, 16, 24, 32, 40, 48 tasks on 1 task/node.
  - `large`: 4, 8, 16, 32, 64, 128, 192, 256 tasks on 4 tasks/node.
    *(Note: `lmp large` is unsupported and is rejected atomically before any mutation.)*
- `--ssd`: Selects SSD storage class root. Default storage class is HDD.
- `--setup <name>`: Explicitly overrides the benchmark setup profile.
  - **Syntax rule**: `--setup <name>` must be specified as two separate arguments. Syntax `--setup=value` is strictly rejected.
- Legacy `--ssd` / `-s`: Accepted globally before the subcommand for backwards compatibility.

#### Benchmark Setups:
- **IOR setups**: `BASE` (default), `HDF5`, `HDF5-C`, `COLLECTIVE`, `FSYNC`, `REVERSE`.
- **LSMIO setups**: `NATIVE-M` (default), `ADIOS-M`, `PLUGIN-M`, `ROCKSDB-M`, `LEVELDB-M`, `ADIOS`, `PLUGIN`, `ROCKSDB`, `LEVELDB`, `MANAGER`.
- **LMP setups**: `LSMIO` (default), `LSMIO-MMAP`, `FS`.

### 6-Combination Execution Matrix

Each submitted scheduler allocation executes exactly 6 stripe count and block size combinations in an immutable, fixed sequence:
1. `(16, 8M)` - 16 stripes, 8 MiB block size
2. `(16, 1M)` - 16 stripes, 1 MiB block size
3. `(16, 64K)` - 16 stripes, 64 KiB block size
4. `(4, 8M)` - 4 stripes, 8 MiB block size
5. `(4, 1M)` - 4 stripes, 1 MiB block size
6. `(4, 64K)` - 4 stripes, 64 KiB block size

On Lustre parallel filesystems, directories are explicitly configured using `lfs setstripe -c <stripes> -S <blocksize>` prior to executing each combination.

### Scale Points and Allocation Shapes

| Scale | Task Counts | Tasks Per Node (ppn) | Node Counts |
|---|---|---|---|
| `local` | `[1]` | 1 | 1 |
| `bake` | `[1, 2, 4, 8]` | 1 | 1, 2, 4, 8 |
| `small` | `[1, 2, 4, 8, 16, 24, 32, 40, 48]` | 1 | 1, 2, 4, 8, 16, 24, 32, 40, 48 |
| `large` | `[4, 8, 16, 32, 64, 128, 192, 256]` | 4 | 1, 2, 4, 8, 16, 32, 48, 64 |

### Environment Profiles: Configured vs Certified

Environment configurations are loaded from `RUN_PROFILES` in `etc/environments.json`.
- **Supported profiles**:
  - `viking`: Slurm scheduler (`srun` launcher, `END,FAIL` mail, computed walltime)
  - `viking2`: Slurm scheduler (`srun` launcher, `END,FAIL` mail, pool configuration)
  - `archer2`: Slurm scheduler (`srun` launcher, `standard` partition/QoS)
  - `isambard`: PBS scheduler (`aprun` launcher, `abe` mail, fixed 6-hour walltime)
  - `dev`: Fake scheduler & launcher (test-only profile)
- **Certification status**: All production profiles are in `configured` state pending opt-in site-specific live certification.

### Scheduler Resource Directives & Policies

#### PBS Directives (Isambard Profile):
- Fixed walltime directive: `#PBS -l walltime=06:00:00`
- Typed mail mode directive: `#PBS -m abe` (abort, begin, end)
- Queue directive: `#PBS -q arm`
- Small / Bake / Local scale chunk directive: `#PBS -l select=<nodes>:ncpus=1:mpiprocs=1:mem=32GB` plus memory limits `#PBS -l pmem=8G` and `#PBS -l pvmem=8G`
- Large scale chunk directive: `#PBS -l select=<nodes>:ncpus=4:mpiprocs=4:mem=32GB` (without `pmem`/`pvmem`)
- Directives use node count per select chunk.
- No Slurm `#SBATCH` directives, accounts, or email credentials are required or rendered for PBS jobs.

#### Slurm Directives (Viking, Viking2, Archer2 Profiles):
- Computed walltime directive: `#SBATCH --time=...` (scaled with task count)
- Typed mail mode directive: `#SBATCH --mail-type=END,FAIL`
- Task distribution directive: `#SBATCH --distribution=cyclic:cyclic`
- Viking / Viking2 memory directive: `#SBATCH --mem=8gb`
- Archer2 partition & QoS directives: `#SBATCH -p standard`, `#SBATCH --qos=standard` (no memory directive)
- Standard directives for job name, ntasks, nodes, ntasks-per-node, output, error, account, and mail-user.

### Decimal-Only Slurm Job IDs & Cluster-Qualified Output Rejection

- `sbatch --parsable` submit output is validated against regex `^[0-9]+$`. The single parsed decimal string is retained verbatim as `JobHandle.job_id`.
- Cluster-qualified output strings (e.g. `123;cluster`) are strictly rejected as unverified.
- PBS job IDs match regex `^[0-9]+(?:\.[A-Za-z0-9._-]+)?$`.
- The exact numeric handle is preserved across all active queries (`squeue`), accounting (`sacct`), cancellation (`scancel`), and evidence records without modification or integer truncation.

### Correlation Tokens, 4-Step Dispatch Sequence & Crash Recovery

- **Correlation Token**: A 27-character identifier matching `^lm-[0-9a-f]{24}$` (prefix `lm-` followed by 24 lowercase hexadecimal characters) generated per scale point plan and transported exclusively as the scheduler job name.
- **4-Step Dispatch Sequence**:
  1. `submission_requested`: Written to point evidence before scheduler command execution.
  2. `submission_dispatched`: Written immediately before spawning the scheduler process.
  3. `sbatch` / `qsub` process execution.
  4. `JobHandle` recorded upon verifying the returned job identifier.
- **Accepted-Submit Crash Recovery**: If orchestration is interrupted after `submission_dispatched` before the job handle is persisted, the orchestrator queries the scheduler using the correlation token (`squeue --name=<token>` / `sacct --name=<token>` or `qstat -u <user>` filtered by `Job_Name`).
  - Exactly 1 candidate job: Recovered and adopted without resubmission.
  - 0 or >1 candidate jobs: Marked `INDETERMINATE` without blind resubmission.

### Artifact Ownership, Control Lock & State Precedence

- **Run Root Directory**: `<benchmark-root>/runs/<run-id>`
- **Isolated Directory Layout**:
  - `manifest.json`: Canonical, immutable write-once run plan.
  - `control/lock`: Exclusive advisory lock (`fcntl.flock`) preventing concurrent orchestrators.
  - `control/events/<writer>/<sequence>.json`: High-level lifecycle events.
  - `scheduler/submission*.json` & `scheduler/observations/<writer>/<sequence>.json`: Point-private scheduler submissions and observations.
  - `worker/events/<sequence>.json`: Controller allocation execution records.
  - `combinations/<combination>/controller-result.json`: Combination execution results.
  - `ranks/<global-rank>/<combination>/result.json`: LSMIO rank worker results.
  - `logs/`: Isolated standard output and standard error logs.
  - `data/c<stripe>/b<block>/`: Stripe/block combination data directories.
- **Disjoint Writer Ownership**: CONTROL, CONTROLLER, and RANK writers create only their owned evidence. External schedulers never write to the filesystem directly.
- **Authoritative State Precedence**:
  1. Specific independent execution failure (`FAILED`) outranks generic success.
  2. Confirmed requested cancellation (`CANCELLED`).
  3. Whole run success requires complete evidence across all points and combinations AND a durable `WHOLE_RUN_SUCCEEDED` control event (`SUCCEEDED`).
  4. Interruption recorded before the success marker permanently holds overall state at `INTERRUPTED` even if the final point succeeded.
  5. Conflicting handles, corrupt/missing evidence, unconfirmed cancellation, or missing terminal accounting yields `INDETERMINATE`.
  6. Stale active observations cannot regress terminal facts.

### Signal Coordination & Bounded Cancellation

- SIGINT latches and exits with status code `130`.
- SIGTERM latches and exits with status code `143`.
- Upon receiving a signal, new submissions are prevented, an interruption event is appended to the control stream, the active job is cancelled via `scancel` / `qdel`, and cancellation is confirmed via bounded polling (poll interval: 8s, grace period: 120s).

### Printed Identifiers and Paths

At startup, `lsmiotool run` prints:
- `Run ID`: Unique run identifier (e.g. `run-20260821-120000-abcdef123456`)
- `Correlation Token`: Point token (e.g. `lm-abcdef0123456789abcdef01`)
- `Run Root`: Absolute path to the isolated run root directory
At completion, prints final reconciled state (`SUCCEEDED`, `FAILED`, `INTERRUPTED`, `CANCELLED`, `INDETERMINATE`) and exit code.

### Installed Layout vs Source Layout

The runtime paths are explicitly constructed without cross-fallback:
- **Installed Layout**:
  - Public CLI: `<prefix>/bin/lsmiotool`
  - Private Worker: `<prefix>/libexec/lsmio/lsmiotool-worker`
  - Python Package, Profiles & VERSION: `<prefix>/share/lsmio/python/`
  - LAMMPS ReaxFF Assets: `<prefix>/share/lsmio/lmp-reaxff/`
- **Source Layout**:
  - Public CLI: `tools/lsmiotool/lsmiotool`
  - Private Worker: `tools/lsmiotool/lsmiotool-worker`
  - Assets: `tools/bmtool/lmp-reaxff/`
  - Profiles: `tools/lsmiotool/etc/environments.json`
  - Version: `tools/lsmiotool/VERSION`

### Parse Command Boundary & Limitations

- `lsmiotool parse` operates on legacy outputs and does not perform automatic run-root discovery or date/benchmark guessing.
- Internal `RunRootResolver` requires an explicit path to a reconciled `manifest.json` and succeeded evidence.
- Legacy `parse` functionality remains backward-compatible and unchanged.

### Atomic `lmp large` Gate

- `lmp large` is unsupported and is rejected immediately before run ID generation, correlation token creation, capability probing, artifact directory creation, filesystem mutation, or scheduler interaction.

### Migration Incompatibilities from Legacy `bmtool`

| Legacy `bmtool` Behavior | Modern `lsmiotool run` Implementation |
|---|---|
| Invocation via `tools/bmtool/bmtool run` | Invocation via `lsmiotool run <benchmark> <scale>` |
| Shared mutable paths (`$HOME/scratch/benchmark/data/*`) | Isolated private run roots (`<root>/runs/<run-id>`) |
| Uncoordinated `dirs-cleanup.sh` wiping data | Isolated per-combination data directories (`data/c<stripe>/b<block>`) |
| Same-day run directory collisions and overwrites | Unique immutable run IDs with collision-proof directory creation |
| Whole-user queue polling (`squeue -u $USER` / `qstat -u $USER`) | Exact job ID tracking with correlation tokens (`lm-...`) |
| Status masking and hidden benchmark failures | Failure-preserving process runner and deterministic state reconciliation |
| Benchmark setups edited via shell variables | Explicit `--setup <name>` option |
| Unchecked CLI arguments silently ignored | Strict argument parsing; `--setup=val` and unknown options rejected |

## Using LSMIO in a Project

To include LSMIO in your package using a CMAKE project:
```
find_package(lsmio REQUIRED)
target_include_directories(... PUBLIC ${LSMIO_INCLUDE_DIRS})
target_link_libraries(... PUBLIC lsmio_store)
```
Substitute the ... with your target name.

A simple example is follows:
```
...
#include <lsmio/lsmio.hpp>
#include <lsmio/manager/manager.hpp>
...

...
  initLSMIORelease(argv[0]);

  lsmio::LSMIOManager lm("test_data", "/tmp/mydir");

  success = lm.put(key1, value1, true);
  success = lm.get(key1, &value);
...

```


## Resources

External resources for this project:
- [Developers Guide](DEVELOPERS.md)
- [Contribution Guide](CONTRIBUTING.md)
- Bug tracker: https://github.com/tybulut/lsmio/issues
- CI server: TBA

## How to reference

ACM format:
```
Serdar Bulut and Steven A. Wright. 2023. Optimizing Write Performance for Checkpointing to Parallel File Systems Using LSM-Trees. In Proceedings of the SC '23 Workshops of The International Conference on High Performance Computing, Network, Storage, and Analysis (SC-W '23). Association for Computing Machinery, New York, NY, USA, 492–501. https://doi.org/10.1145/3624062.3624118
```

BibTex format:
```
@inproceedings{10.1145/3624062.3624118,
author = {Bulut, Serdar and Wright, Steven A.},
title = {Optimizing Write Performance for Checkpointing to Parallel File Systems Using LSM-Trees},
year = {2023},
isbn = {9798400707858},
publisher = {Association for Computing Machinery},
address = {New York, NY, USA},
url = {https://doi.org/10.1145/3624062.3624118},
doi = {10.1145/3624062.3624118},
abstract = {The widening gap between compute performance and I/O performance on modern HPC systems means that writing checkpoints to a parallel file system for fault tolerance is fast becoming a bottleneck to high-performance. It is therefore vital that software is engineered such that it can achieve the highest proportion of available performance on the underlying hardware; and this is a burden often carried by I/O middleware libraries. In this paper, we outline such an I/O library based on a Log-structured Merge Tree (LSM-Tree), not just for metadata, but also scientific data. We benchmark its performance using the IOR benchmark, demonstrating 2.4 to 76.7 \texttimes{} better performance than alternative file formats, such as ADIOS2, HDF5, and IOR baseline when running on a Lustre Parallel File System. We further demonstrate that when our LSM-Tree I/O library is used as a storage layer for ADIOS2, the resulting I/O library still outperforms the default ADIOS2 implementation by 1.5 \texttimes{}.},
booktitle = {Proceedings of the SC '23 Workshops of The International Conference on High Performance Computing, Network, Storage, and Analysis},
pages = {492–501},
numpages = {10},
keywords = {MPI, checkpointing, distributed storage, high performance computing, input/output},
location = {<conf-loc>, <city>Denver</city>, <state>CO</state>, <country>USA</country>, </conf-loc>},
series = {SC-W '23}
}
```


