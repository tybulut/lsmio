# LSMIO: High-Performance LSM-Tree Scientific Storage Engine

[![Build & Test](https://img.shields.io/badge/build-passing-brightgreen.svg)](build.sh)
[![License](https://img.shields.io/badge/license-BSD--3--Clause-blue.svg)](LICENSE)
[![SC'23 Workshop Paper](https://img.shields.io/badge/DOI-10.1145%2F3624062.3624118-darkred.svg)](https://doi.org/10.1145/3624062.3624118)

LSMIO is an asynchronous, high-throughput storage engine and parallel I/O middleware library based on Log-Structured Merge-trees (LSM-trees). Engineered specifically to optimize checkpointing and scientific data access on High-Performance Computing (HPC) parallel filesystems (e.g., Lustre), LSMIO minimizes metadata synchronization bottlenecks, eliminates shared-file lock contention, and provides high-performance read pathways via memory mapping and atomic persistent descriptor I/O.

---

## Central Subsystem Guides

To navigate the detailed architectural, testing, and operational guides across the LSMIO codebase:

- [**Benchmark Subsystem Guide**](benchmark/README.md): Comprehensive reference for synthetic benchmark targets (`bm_native`, `bm_adios`, `bm_rocksdb`, `bm_leveldb`, `bm_manager`), CLI flag catalog, high-performance read flags (`--lsmio-mmap`, `--lsmio-pread`), scaling models, and the `micro.sh` runner.
- [**Testing & Verification Guide**](test/README.md): Exhaustive documentation covering CTest orchestration, GoogleTest suites, MPI multi-rank integration fixtures, execution protocols (`test`, `xtest`, `ptest`), and debugging workflows (`gdb`, `lldb`, AddressSanitizer).
- [**Tools & Orchestration Guide**](tools/README.md): User and architectural manual for the `lsmiotool` framework, HPC batch scheduler orchestration (Slurm & PBS), report parsing (`lsmiotool parse`), scaling and variant comparison (`lsmiotool compare`), and the canonical 30-variant catalog.

---

## Getting Started

### Clone Repository

```bash
# Via SSH:
git clone git@github.com:tybulut/lsmio.git

# Via HTTPS:
git clone https://github.com/tybulut/lsmio.git
```

---

## Prerequisites

### Debian / Ubuntu Linux

Install required compilation toolchain, libraries, and dependencies:

```bash
sudo apt-get update && sudo apt-get install -y \
  build-essential cmake autoconf automake gdb git \
  cpplint libbz2-dev libpython3-dev \
  libkyotocabinet-dev kyotocabinet-utils \
  libsnappy-dev sqlite3 libsqlite3-dev \
  texlive-latex-base texlive-font-utils \
  texlive-latex-extra texlive-science \
  libchart-gnuplot-perl libpng-dev \
  libpod-parser-perl libpod-latex-perl \
  libhdf5-dev libhdf5-mpi-dev libhdf5-mpich-dev libhdf5-openmpi-dev \
  openmpi-bin libopenmpi-dev \
  libgtest-dev googletest-tools googletest \
  libgoogle-glog-dev libfmt-dev \
  libgflags-dev libleveldb-dev librocksdb-dev \
  libadios2-mpi-c++11-dev libcli11-dev
```

#### Optional Packages:
```bash
sudo apt-get install -y screen vim wget curl rdate rsync
```

#### Other Dependencies:
Darshan should be installed manually if not already present on the system:
```bash
# Build script located at:
doc/dependencies/11-darshan
```
The remaining dependencies are automatically managed via CMake.

### HPC Cluster Environment (Rocky Linux / RedHat)

On HPC systems such as Viking, ARCHER2, or Isambard:
- **Operating System**: Rocky Linux release 8 / RedHat Enterprise Linux 8.
- **HPC Modules**: Automatically load required compiler and MPI modules:
  ```bash
  ./tools/bmtool/bmtool load-modules
  # Or via modern lsmiotool:
  ./tools/lsmiotool/lsmiotool load-modules
  ```
- **Custom Dependencies**: Packages listed under `doc/dependencies/` provide standalone installation scripts targeting `$HOME/src` as the default prefix. Dependencies with filenames starting with `9` are optional.

---

## Building and Installation

LSMIO provides a centralized build script `build.sh`:

```bash
# Build release version (default build directory: ./build)
./build.sh release make

# Build debug version with full symbols (-g)
./build.sh debug make

# Build and execute the test suite
./build.sh release test

# Build and install to $HOME/src/usr
./build.sh release install

# Clean existing build directory and perform fresh installation
./build.sh clean install
```

---

## Testing

```bash
# Run standard unit tests in parallel (8 threads)
./build.sh test

# Run extended test suite (all 134+ tests including MPI and Python)
./build.sh xtest

# Run Python toolchain tests
./build.sh ptest
```

> [!TIP]
> When executing intensive regression tests on a local HDD, mount the volume with `noatime,nodiratime` to prevent metadata update bottlenecks:
> ```bash
> mount -o noatime,nodiratime /dev/sda2 /media/400GB
> ```

For detailed test suite breakdowns, regex filtering, and LLDB/ASan debugging instructions, refer to the [Testing Guide](test/README.md).

---

## Library Integration

### CMake Project Integration

To incorporate LSMIO into an external CMake project:

```cmake
find_package(lsmio REQUIRED)

add_executable(my_application main.cpp)
target_include_directories(my_application PUBLIC ${LSMIO_INCLUDE_DIRS})
target_link_libraries(my_application PUBLIC lsmio_store)
```

### C++ API Minimal Example

```cpp
#include <iostream>
#include <string>
#include <lsmio/lsmio.hpp>
#include <lsmio/manager/manager.hpp>

int main(int argc, char** argv) {
    // Initialize LSMIO runtime configuration
    initLSMIORelease(argv[0]);

    // Instantiate LSMIOManager with target database name and storage directory
    lsmio::LSMIOManager lm("simulation_checkpoint", "/tmp/lsmio_run");

    std::string key = "rank_0_step_1000";
    std::string payload = "checkpoint_binary_blob_data";

    // Synchronous write
    bool write_ok = lm.put(key, payload, true);
    if (!write_ok) {
        std::cerr << "Failed to write key: " << key << std::endl;
        return 1;
    }

    // Direct key lookup
    std::string retrieved_val;
    bool read_ok = lm.get(key, &retrieved_val);
    if (read_ok) {
        std::cout << "Successfully retrieved value of size: " << retrieved_val.size() << " bytes\n";
    }

    return 0;
}
```

---

## Resources & Community

- [Developer Guidelines](DEVELOPERS.md)
- [Contribution Guidelines](CONTRIBUTING.md)
- [Issue & Bug Tracker](https://github.com/tybulut/lsmio/issues)

---

## Academic Reference & Citation

If you use LSMIO in your research, please cite our SC '23 workshop paper:

**ACM Format:**
```text
Serdar Bulut and Steven A. Wright. 2023. Optimizing Write Performance for Checkpointing to Parallel File Systems Using LSM-Trees. In Proceedings of the SC '23 Workshops of The International Conference on High Performance Computing, Network, Storage, and Analysis (SC-W '23). Association for Computing Machinery, New York, NY, USA, 492–501. https://doi.org/10.1145/3624062.3624118
```

**BibTeX Format:**
```bibtex
@inproceedings{10.1145/3624062.3624118,
  author = {Bulut, Serdar and Wright, Steven A.},
  title = {Optimizing Write Performance for Checkpointing to Parallel File Systems Using LSM-Trees},
  year = {2023},
  isbn = {9798400707858},
  publisher = {Association for Computing Machinery},
  address = {New York, NY, USA},
  url = {https://doi.org/10.1145/3624062.3624118},
  doi = {10.1145/3624062.3624118},
  abstract = {The widening gap between compute performance and I/O performance on modern HPC systems means that writing checkpoints to a parallel file system for fault tolerance is fast becoming a bottleneck to high-performance. It is therefore vital that software is engineered such that it can achieve the highest proportion of available performance on the underlying hardware; and this is a burden often carried by I/O middleware libraries. In this paper, we outline such an I/O library based on a Log-structured Merge Tree (LSM-Tree), not just for metadata, but also scientific data. We benchmark its performance using the IOR benchmark, demonstrating 2.4 to 76.7 x better performance than alternative file formats, such as ADIOS2, HDF5, and IOR baseline when running on a Lustre Parallel File System. We further demonstrate that when our LSM-Tree I/O library is used as a storage layer for ADIOS2, the resulting I/O library still outperforms the default ADIOS2 implementation by 1.5 x.},
  booktitle = {Proceedings of the SC '23 Workshops of The International Conference on High Performance Computing, Network, Storage, and Analysis},
  pages = {492–501},
  numpages = {10},
  keywords = {MPI, checkpointing, distributed storage, high performance computing, input/output},
  location = {Denver, CO, USA},
  series = {SC-W '23}
}
```
