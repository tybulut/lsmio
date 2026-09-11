# LSMIO Benchmark Subsystem Guide

The LSMIO benchmark subsystem provides high-precision synthetic benchmarking harnesses, micro-benchmarking drivers, and workload scaling tools designed to evaluate I/O performance on local storage and distributed parallel filesystems (e.g., Lustre).

For top-level architecture and subsystem navigation, refer to the [LSMIO Architecture Guide](../README.md).  
For test verification, see the [Testing Guide](../test/README.md).  
For cluster-wide orchestration and batch scheduler integration, see the [Tools & Orchestration Guide](../tools/README.md).

---

## 1. Benchmark Executables

All benchmark binaries are compiled into `build/benchmark/` (and installed to `${CMAKE_INSTALL_PREFIX}/bin` or `~/src/usr/bin/` by default).

| Executable | Storage Engine / Target | Key Architectural Role |
| :--- | :--- | :--- |
| `bm_native` | `LSMIOStoreNative` | Evaluates LSMIO's native LSM-tree storage engine, including memtable variants, dense index footers, file pooling, and the high-performance read path (`mmap` / `pread`). |
| `bm_adios` | ADIOS2 / LSMIO Plugin | Evaluates ADIOS2 BP file engine, and optionally the LSMIO ADIOS plugin (`--lsmio-plugin`) where LSMIO acts as the storage backend beneath ADIOS2. |
| `bm_rocksdb` | `LSMIOStoreRocksDB` | Benchmarks Facebook's RocksDB embedded key-value engine under identical synthetic workloads for direct comparative baseline analysis. |
| `bm_leveldb` | `LSMIOStoreLevelDB` | Benchmarks Google's LevelDB embedded key-value engine under identical synthetic workloads for baseline comparison. |
| `bm_manager` | `LSMIOManager` | Benchmarks the high-level LSMIO manager abstraction layer interfacing multiple storage ranks and directory partitions. |

---

## 2. Command-Line Flags Reference

Benchmark executables share a common CLI foundation based on `CLI11` via `BMBase`.

### 2.1 General Benchmark Execution Flags

| Flag | Argument | Default | Description |
| :--- | :--- | :--- | :--- |
| `-o, --output-file` | `<path>` | *Required* | Output file path for database storage and benchmark files. |
| `-d, --output-dir` | `<path>` | `""` | Base directory for storing benchmark artifacts and SSTables. |
| `-i, --iterations` | `<int>` | `1` | Number of write and read iterations to execute. |
| `-k, --key-count` | `<int>` | `1024` | Total number of keys per benchmark iteration. |
| `-z, --value-size` | `<int>` | `64K` (65536) | Size in bytes for each key's payload value. |
| `-s, --segment-count` | `<int>` | `1024` | Segment count for key partitioning. |
| `-v, --verbose` | None | `false` | Enable verbose informational logging to standard output. |
| `-g, --debug` | None | `false` | Enable verbose debugging diagnostics. |
| `-e, --sync` | None | `false` | Enforce synchronous I/O operations (`O_SYNC` / `fsync`) after writes. |
| `-l, --loop-all` | None | `false` | Iterate across all built-in configuration option variations. |
| `-m, --mpi-barrier` | None | `false` | Synchronize ranks via `MPI_Barrier` before starting and stopping benchmarks. |
| `-c, --collective-io` | None | `false` | Enable MPI collective I/O operations across ranks. |
| `-w, --mpi-io-world` | None | `false` | Use global `MPI_COMM_WORLD` for collective I/O rather than host-level rank groupings. |

### 2.2 Storage Backend Selection Flags

| Flag | Target Backend | Description |
| :--- | :--- | :--- |
| *(default)* | NativeDB | Uses `LSMIOStoreNative`, LSMIO's native high-performance LSM-tree engine. |
| `--lsmio-use-rocksdb` | RocksDB | Switches the storage backend to embedded RocksDB (`lsmio::StorageType::RocksDB`). |
| `--lsmio-use-leveldb` | LevelDB | Switches the storage backend to embedded LevelDB (`lsmio::StorageType::LevelDB`). |
| `--lsmio-plugin` | ADIOS2 Plugin | Used with `bm_adios` to direct ADIOS2 I/O operations through the LSMIO storage engine plugin. |

### 2.3 High-Performance Read Path Flags

| Flag | Read Mechanism | Description | System Overhead |
| :--- | :--- | :--- | :--- |
| *(default)* | Stream Fallback | Reads SSTable entries using POSIX stream I/O (`std::ifstream`), reopening descriptors and seeking. | 7 syscalls, 2 MDS RPCs per read |
| `--lsmio-mmap` | Memory-Mapped I/O | Memory-maps SSTable files upon ingestion (`mmap` with `PROT_READ \| MAP_SHARED`) and triggers Lustre bulk OST read-ahead with `posix_madvise(WILLNEED)`. Lookups extract key-value records zero-copy directly from page cache. | **0 syscalls, 0 MDS RPCs** |
| `--lsmio-pread` | Persistent `pread()` | Retains open read file descriptors (`read_fd`) in `IndexNode` and issues speculative `pread()` into a 64 KiB stack buffer. Payloads $\le 64\text{ KiB}$ complete in a single atomic syscall; larger payloads require a second atomic tail read. | **1 syscall (or 2 if >64KB), 0 MDS RPCs** |

> [!TIP]
> Combining `--lsmio-footer-index` with either `--lsmio-mmap` or `--lsmio-pread` provides maximum read throughput on Lustre filesystems by bypassing file open/close metadata operations and stream positioning entirely.

### 2.4 NativeStore Engine Tuning Parameters

| Flag | Argument | Default | Description |
| :--- | :--- | :--- | :--- |
| `--lsmio-footer-index` | None | `false` | Appends a Dense Index Footer to SSTables during memtable flush, enabling $O(\log N)$ binary search key lookups. |
| `--lsmio-manual-offset` | None | `false` | Manually tracks SSTable write offsets, bypassing redundant `tellp()` system calls. |
| `--lsmio-memtable` | `<type>` | `vector-no-sort` | Selects memtable in-memory write buffer data structure: `vector-no-sort`, `vector-sort`, `map`, or `btree`. |
| `--lsmio-wbuffer` | `<bytes>` | `128M` (134217728) | Memtable write buffer threshold before triggering asynchronous flush to SSTable. |
| `--lsmio-wbuffer-num` | `<int>` | `4` | Number of concurrent write buffers maintained by the store. |
| `--lsmio-fsize` | `<bytes>` | `8x wbuffer` | Target SSTable file size on disk before rotating files. |
| `--lsmio-prealloc` | None | `false` | Pre-allocates SSTable files on disk using `posix_fallocate()` to avoid fragmentation and metadata lock contention. |
| `--lsmio-pool` | `<int>` | `4` | Number of pre-allocated file descriptors maintained in the background `FilePool`. |
| `--lsmio-always-flush` | None | `false` | Disables write batching and flushes data immediately so records are accessible immediately. |
| `--lsmio-batch-size` | `<int>` | `512` | Batch threshold for asynchronous batched write operations. |
| `--lsmio-batch-bytes` | `<bytes>` | `32M` (33554432) | Maximum deferred batch byte capacity. |
| `--lsmio-cache` | `<bytes>` | `0` | Capacity of LRU block/record cache in bytes (`0` disables cache). |
| `--lsmio-bs` | `<bytes>` | `64K` (65536) | Block size for storage operations. |
| `--lsmio-ts` | `<bytes>` | `64K` (65536) | Transfer chunk size for write/read routines. |
| `--lsmio-bfilter` | None | `false` | Enables Bloom filter generation to filter out SSTables that do not contain a queried key. |
| `--lsmio-wal` | None | `false` | Enables Write-Ahead Logging (WAL) for durability against process crash. |
| `--lsmio-compress` | None | `false` | Enables data compression for stored records. |
| `--lsmio-autotune` | None | `true` | Enables automatic parameter tuning based on filesystem block and stripe sizes. |
| `--lsmio-disable-agg-dir-structure` | None | `false` | Disables per-rank aggregation directory structure, placing SSTables in a shared directory. |
| `--lsmio-max-key` | `<bytes>` | `256K` (262144) | Maximum allowable key length in bytes. |

---

## 3. Workload Scaling Models

### 3.1 Weak Scaling vs. Strong Scaling

- **Weak Scaling**:
  - The workload per process/rank remains constant (e.g., $N$ keys per process), while total ranks scale from 1 to 256.
  - Total data size increases linearly with the rank count:
    $$\text{Data}_{\text{total}} = N_{\text{ranks}} \times N_{\text{keys}} \times \text{Size}_{\text{value}}$$
  - Weak scaling evaluates how effectively the parallel filesystem (e.g., Lustre Object Storage Targets / OSTs) and LSMIO's per-rank aggregation directory structures accommodate aggregate I/O bandwidth without metadata bottlenecks.
- **Strong Scaling**:
  - The total dataset size is fixed (e.g., 100 GiB total across all ranks), and the rank count increases.
  - The per-rank workload shrinks proportionally:
    $$\text{Keys}_{\text{rank}} = \frac{N_{\text{total\_keys}}}{N_{\text{ranks}}}$$
  - Strong scaling evaluates parallel coordination efficiency, MPI barrier latency, and lock contention under decreasing granularities.

### 3.2 Lustre File Striping Interactions

LSMIO workloads are tuned for Lustre parallel filesystems:
- **Stripe Count (`-c`)**: Defines how many OSTs an SSTable or directory is striped across (e.g., 4 or 16 stripes).
- **Stripe Size (`-S`)**: Defines the contiguous chunk size written to an OST before advancing to the next stripe (e.g., 64 KiB, 1 MiB, or 8 MiB).
- **Isolated Directory Layout**: Directing each rank to an isolated combination path (`data/c<stripe>/b<block>/`) eliminates shared-file lock conflicts across Lustre OSTs.

---

## 4. Micro-benchmarking Automation (`micro.sh`)

The `micro.sh` shell script automates compilation, installation, and sequential execution of local micro-benchmarks across selected storage engines.

### 4.1 Usage Syntax

```bash
./micro.sh [adios] [plugin] [rocksdb] [leveldb] [native] [-i iterations]
```

### 4.2 Target Selectors & Options

- `adios`: Runs `bm_adios` using ADIOS2's default BP engine.
- `plugin`: Runs `bm_adios` with `--lsmio-plugin` enabled.
- `rocksdb`: Runs `bm_rocksdb`.
- `leveldb`: Runs `bm_leveldb`.
- `native`: Runs `bm_native` using LSMIO's native storage engine.
- `-i, --iterations <n>`: Specifies iteration count (defaults to `5`).

### 4.3 Environment Variables

- `BM_DIR`: Base directory where benchmark databases and output files are created (default: `$HOME/benchmark`).
- `ITER`: Default iteration count if `-i` is omitted (default: `5`).

### 4.4 Execution Workflow

1. Validates that at least one benchmark target is selected.
2. Creates destination directory `${BM_DIR}`.
3. Enters `${BUILD_DIR}` and executes `make -j8 install` to ensure binaries in `~/src/usr/bin/` are current.
4. Executes each selected target with standardized parameters:
   - Block size: `1024 KiB` (`--lsmio-bs 1024`)
   - Transfer size: `1024 KiB` (`--lsmio-ts 1024`)
   - Key count: `2048` (`--key-count 2048`)
   - Verbose and debug flags enabled (`-v -g`)
   - Outputs saved to `${BM_DIR}/lsmio-<target>.db`

---

## 5. Metrics & Output Interpretation

At completion, benchmark executables print structured performance metrics to stdout:

```text
BENCHMARK PARAMETERS:
  fileName: /tmp/lsmio-native.db
  iterations: 5
  keyCount: 2048
  valueSize: 65536
  enableMMAP: true
  enablePread: false
  footerIndex: true

BENCHMARK RESULTS:
Bench-WRITE: native
  Duration: 0.1082 s
  Throughput: 1210.72 MB/s
  IOPS: 18927.91 ops/s

Bench-READ: native
  Duration: 0.0415 s
  Throughput: 3156.62 MB/s
  IOPS: 49349.39 ops/s
```

### Calculation Formulas
- **Data Transferred (Bytes)**:
  $$\text{Bytes} = N_{\text{keys}} \times \text{Size}_{\text{value}} \times (\text{MPI Size if enabled})$$
- **Throughput (MB/s)**:
  $$\text{Throughput} = \frac{\text{Bytes}}{\text{Duration (seconds)} \times 10^6}$$
- **IOPS (Operations/sec)**:
  $$\text{IOPS} = \frac{N_{\text{keys}}}{\text{Duration (seconds)}}$$
- **Statistical Summaries**:
  When running multiple iterations (`-i > 1`), `BMBase` outputs minimum, maximum, and mean throughput across all iterations for write and read phases.
