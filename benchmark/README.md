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
| `-e, --sync` | None | `false` | Sets `useSync`. Only the LevelDB and RocksDB stores read it: it becomes `WriteOptions.sync` on their writes (RocksDB applies it only together with `--lsmio-wal`, and ignores it with a warning otherwise). It does not force `O_SYNC` or `fsync` for the other engines. See [Section 6](#6-durability-and-the-page-cache-mode). |
| `-l, --loop-all` | None | `false` | Iterate across all built-in configuration option variations. |
| `-m, --mpi-barrier` | None | `false` | Synchronize ranks via `MPI_Barrier` around every phase of an iteration: before and after the open, after the close and after the delete, on the write side and on the read side (see [Section 5.1](#51-phase-timeline)). |
| `-c, --collective-io` | None | `false` | Enable MPI collective I/O operations across ranks. |
| `-w, --mpi-io-world` | None | `false` | Use global `MPI_COMM_WORLD` for collective I/O rather than host-level rank groupings. |
| `--per-rank-path` | None | `false` | Gives every MPI world rank its own store path: the `-o`/`-d` path with the suffix `.mpirank<w>` (`<w>` is the world rank). Refused without `-m`, and refused with `-c`. Needed by `--read-shift`, which wants one store per rank. |
| `--read-shift` | None | `false` | Each rank reads the data of a peer rank on another node instead of its own (see [Section 7](#7-read-shift)). Needs `-m`, is refused with `-c`, and the executable must support it: `bm_native`, `bm_rocksdb`, `bm_leveldb` and `bm_adios` do, `bm_manager` does not (it refuses the run). |
| `--read-shift-nodes` | `<n>` | unset | Test seam: pretend the world has `<n>` nodes (rank `r` is on node `r mod n`) when `--read-shift` maps peers. Needs `--read-shift`, `<n>` must be at least 1 and at most the MPI world size. `lsmiotool` never passes it. |
| `--lsmio-durability` | `engine\|page-cache` | `engine` | Durability mode of the RocksDB and LevelDB stores (see [Section 6](#6-durability-and-the-page-cache-mode)). `page-cache` is refused with `-e/--sync` and on every library build that is not verified. |

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

> [!NOTE]
> **RocksDB and `--lsmio-mmap`.** With `bm_rocksdb`, `--lsmio-mmap` turns on RocksDB's `allow_mmap_reads` and `allow_mmap_writes`. RocksDB's mmap writer extends a file only through `fallocate`, so without it the first table file ends the process with `SIGBUS`. The store therefore sets `allow_fallocate` whenever `--lsmio-mmap` is given, as `--lsmio-prealloc` does, and logs one warning each time a RocksDB store is constructed while `--lsmio-prealloc` is not set (so for the writer and again for the reader of every iteration; the message reads "mmap writes need fallocate; enabling allow_fallocate (preAllocate not set)."). The benchmarks hide warnings unless `-v` is given, so the warning shows only in verbose runs. RocksDB keeps mmap writes only on a short list of filesystems (ext2/3/4, XFS and tmpfs, read from RocksDB's source and not run here) and switches them off elsewhere, for example on NFS, Lustre, GPFS and btrfs; there `--lsmio-mmap` still turns `allow_fallocate` on, so such a run behaves like `--lsmio-mmap --lsmio-prealloc` for ordinary writes, and the warning's wording does not fit. LevelDB has no mmap-writes option and ignores `--lsmio-mmap` for writes.

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
| `--lsmio-autotune` | None | `false` | Enables automatic parameter tuning based on filesystem block and stripe sizes. |
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

The `Duration`, `Throughput` and `IOPS` rows above (and the `iwrite,` / `iread,` rows of each iteration) are the *legacy window*: from the moment the store is open (after the barrier that follows the open) until the exit of the barrier that follows the close. They are unchanged by the phase timeline below, so older archives stay comparable.

### 5.1 Phase timeline

Every iteration has a write side and a read side, and each side records five boundaries, in this order:

| Boundary | Captured | Barrier before it (with `-m`) |
| :--- | :--- | :--- |
| `beforeOpen` | right after the barrier that precedes the store open | yes |
| `afterOpen` | after the store is open (the legacy timer starts here) | yes |
| `beforeClose` | after the last put or get, before the engine's finalize step (`doWriteFinalize` / `doReadFinalize`; for RocksDB the flush and the close) | no |
| `afterClose` | after the finalize step (the legacy timer stops here) | yes |
| `afterDelete` | after the engine's cleanup hook (`writeCleanup` / `readCleanup`) | yes |

Without `-m` no barrier runs, and without MPI (as in `micro.sh`) nothing is reduced over ranks either (with `-c` and no `-m` the offsets are still reduced, without barriers); the rows are printed in every case. The `beforeClose` boundary has no barrier on purpose, so the close of the slowest rank is not hidden inside the window before it. LSM engines delete the previous iteration's store when the writer opens, so the `open` window of a write side includes that delete; ADIOS2 truncates instead (inferred, not read from the ADIOS2 sources).

Each boundary is stored as an offset in microseconds from the writer's `beforeOpen` barrier exit of the same iteration (that offset is `0`), on a monotonic clock. Under MPI the offsets are reduced with `MAX` over all ranks once per iteration, after every capture of both sides, so every rank that prints results prints the same values, and the reduction sits inside no timed window.

The results carry one `Phases:` block per benchmark suite (one per `-l` variation, named with the same prefix as its `Bench-WRITE:` and `Bench-READ:` blocks). The blocks come after all `Bench-READ:` blocks, are printed by the same ranks as the legacy results, and look like this (illustrative values):

```text
Phases: native
phase,write,0,134217728,0,2210,81432,95310,97105
phase,read,0,134217728,99020,99804,131550,133900,134020
```

The columns are `phase,<write|read>,<iteration>,<bytes>,<beforeOpen>,<afterOpen>,<beforeClose>,<afterClose>,<afterDelete>`. `<bytes>` is the world-total payload of one side (`keyCount x valueSize x` MPI world size) as an integer. A side that failed on any rank has no row, as it has no `iwrite,` or `iread,` row; a failed write skips the read side of that iteration, and the suite stops at its first failed iteration. A suite always prints its `Phases:` line, even with no rows.

`lsmiotool` turns these rows into `lsm-phase-report.csv`; see the [Tools & Orchestration Guide](../tools/README.md#lsm-phase-reportcsv).

### 5.2 Header lines

The `BENCHMARK PARAMETERS:` block gained these lines:

| Line | Printed | Meaning |
| :--- | :--- | :--- |
| `perRankPath` | always | `1` with `--per-rank-path`, else `0`. |
| `durability` | always | `engine` or `page-cache`. |
| `rankShift` | always | `1` with `--read-shift`, else `0`. |
| `rankShiftNodes` | with `--read-shift` | `shared` (the real node split of the MPI job) or `simulated:<n>` (`--read-shift-nodes`). |
| `rankShiftSource` | with `--read-shift` | The world rank whose store the printing rank reads. |
| `rankShiftSelfRanks` | with `--read-shift` | How many world ranks read their own store (1-node runs, and see [Section 7](#7-read-shift)). |
| `rankShiftSameHostRanks` | with `--read-shift` | How many world ranks read a store written on a host with the same processor name as theirs (a diagnostic; it is the world size when the nodes are simulated on one host). |
| `rocksdbVersion` | `bm_rocksdb` | RocksDB `major.minor.patch` the benchmark was compiled against. |
| `leveldbVersion` | `bm_leveldb` | LevelDB `major.minor` (its header has no patch level). |

---

## 6. Durability and the page-cache mode

`--lsmio-durability` selects how the RocksDB and LevelDB stores treat durability. Native and ADIOS2 BP5 write without any sync call, so the engines are not on equal footing by default.

- **`engine` (default).** The engine keeps its own behaviour, including the syncs it issues on flush, on WAL rotation, for its manifest and on close. All archived and future default runs use it, so they stay comparable.
- **`page-cache`.** Every sync of the engine is removed: a wrapper file system (RocksDB) or wrapper `Env` (LevelDB) turns the file `Sync` and `Fsync` calls into plain flushes, and RocksDB's `RangeSync` and directory fsyncs into no-ops. Data reaches the operating system's page cache and is never forced to storage, as for native and BP5. It is refused together with `-e/--sync` (the benchmark refuses at argument parsing, and the store refuses too, so no other caller can combine them).

Native and BP5 have no such mode: `--lsmio-durability page-cache` has no effect on them beyond the header line.

> [!IMPORTANT]
> **LevelDB's `page-cache` arm leaves part of the last memtable in the log.** LevelDB's close is unchanged: it does not flush the final memtable to a table file. Between none and all of the last memtable stays only in the write-ahead log, depending on which background table builds finished before the close. The reader's open builds the rest from the log, so a LevelDB `page-cache` read includes that recovery work in the read side's `open` window; the benchmark neither hides it nor times it separately. This follows from the human decision on LevelDB's close (option 1: leave it unchanged, with no flush at reopen).

### 6.1 Verified-build gate

`page-cache` runs only on library builds whose sync removal was verified:

- A store asks the gate once, in its constructor, before it touches any file. An unverified build logs an `ERROR` that names the engine, the mode and the build, and throws `std::invalid_argument`. A refused store has deleted and created nothing. The benchmarks open their stores without a surrounding `try`, so the run ends at its first open on every rank (an uncaught exception).
- A build is identified by engine, version and platform: RocksDB by `major.minor.patch`, LevelDB by `major.minor`, each with the platform the library was compiled for (for example `linux-x86_64`). When the library reports its version at run time (RocksDB does, LevelDB does not) and it differs from the compile-time version, the store refuses.
- The RocksDB wrapper is compiled in only for RocksDB 9.11.2 and 10.6.2, the two versions whose headers were read against its interface. On every other RocksDB version the RocksDB store refuses `page-cache` whatever the table says. The wrapper was developed and tested against the packaged 9.11.2; 10.6.2 (the version the build fetches when no package is found) has been checked from its headers only, so its first build needs the site gate below before any campaign.
- macOS has no entries, so macOS builds refuse `page-cache`.
- The test suite runs `page-cache` stores on every build that has the wrapper through an admission seam that lives in a header under `lib/` and is reachable only from `test/`. No flag, environment variable, configuration field or CMake option opens it for a benchmark.
- A distribution that patches a library without changing its number is not told apart by the gate. The site gate below covers it.

A build enters the table (`verifiedBuildTable()` in `lib/manager/store/PageCacheGate.cpp`) only on recorded evidence and a human-approved code change. The evidence for an entry is: the `RocksDBPageCache` or `LevelDBPageCache` tests pass; a `strace` of those tests shows no `fsync`, `fdatasync` or `msync`, and `sync_file_range` only with flags 0; and a `strace` of the benchmark in page-cache mode (single process and three ranks, with `--lsmio-wal` and with `--lsmio-mmap`) shows the same while every iteration keeps its `iwrite,` and `iread,` rows.

#### Verified page-cache builds

| Engine | Library build | Platform | Evidence |
| :--- | :--- | :--- | :--- |
| RocksDB | 9.11.2 (`librocksdb9.11 9.11.2-1`) | linux-x86_64 | E2 test form 2026-11-12, branch `tybulut/benchmarkpp`, base `ae90360` (no lsmio commit hash yet): `strace -f -e trace=fsync,fdatasync,msync,sync_file_range` of `test_rocksdb --gtest_filter='RocksDBPageCache.*'`: `[  PASSED  ] 3 tests.`; 0 `fsync`, 0 `fdatasync`, 0 `msync`; 63 `sync_file_range`, all `(fd, 0, 0, 0)` (flags 0). E2b (benchmark form) 2026-11-13, same branch and base: `strace -f -e trace=fsync,fdatasync,msync,sync_file_range` of `bm_rocksdb -i 2 -k 4096 --lsmio-bs 1048576 --lsmio-ts 1048576 --lsmio-durability page-cache`, plain, with `--lsmio-wal`, with `--lsmio-mmap`, and a 3-rank `mpirun -np 3 --oversubscribe` run with `-m --per-rank-path --read-shift --read-shift-nodes 3`: every run exit 0 with its `iwrite` and `iread` rows for both iterations; 0 `fsync`, 0 `fdatasync`, 0 `msync`; 142 `sync_file_range` (24 plain, 28 WAL, 18 mmap, 72 three-rank), all flags 0 |
| LevelDB | 1.23 (`libleveldb1d 1.23-6`) | linux-x86_64 | E2 test form 2026-11-12, branch `tybulut/benchmarkpp`, base `ae90360` (no lsmio commit hash yet): same `strace -f` of `test_leveldb --gtest_filter='LevelDBPageCache.*'`: `[  PASSED  ] 3 tests.`; 0 `fsync`, 0 `fdatasync`, 0 `msync`, 0 `sync_file_range`. E2b (benchmark form) 2026-11-13, same branch and base: the same `strace -f` of `bm_leveldb` with the same flags, plain, with `--lsmio-wal`, with `--lsmio-mmap` (accepted), and the 3-rank `mpirun` run: every run exit 0 with its `iwrite` and `iread` rows for both iterations; 0 `fsync`, 0 `fdatasync`, 0 `msync`, 0 `sync_file_range` |

Each row records the date, the lsmio commit, the test names and their result lines, and the benchmark run's result (E2b, added after it passes).

### 6.2 Site gate

Before the first `page-cache` campaign on a site, check the site's library build:

- If its version and platform are not in the table, the store refuses on that site, loudly, at the first open. Follow the admission order there: run the site's tests (`./build.sh xtest`), run the `strace` check of the `RocksDBPageCache` / `LevelDBPageCache` tests, add the entry (a human-approved change), then run the benchmark check.
- If they are listed, run the benchmark check once on the site's build before the campaign. It is the only check of a patched build with a listed number.

Shifted reads in `page-cache` mode on Lustre may include the writer node's write-back (inferred, not measured); say so wherever such results are reported.

---

## 7. Read shift

Without `--read-shift`, every rank reads back the store it wrote, so a read can be served from the page cache of the node that wrote it. With `--read-shift` each rank reads the data of a peer on another node.

- **The rule.** Ranks are grouped by node (the real node split, or `--read-shift-nodes`). A rank's node-local index is its position among the ranks of its node, in world-rank order. The ranks that share a node-local index form a ring ordered by node id; a rank reads the store written by its successor in that ring, the rank with the same node-local index on the next node, and the last node wraps to the first. Which rank reads which store does not depend on how the launcher placed ranks, only on the node ids.
- **Own-store reads.** A node-local index held by one node only reads its own store. With one node, every rank does, and `rankShiftSelfRanks` equals the world size. With unequal numbers of ranks per node, the extra ranks on the fullest node read their own store too, even where a mapping with no own-store read might exist; the header counts them in `rankShiftSelfRanks`. Check that line before calling an arm a cross-node read.
- **One store per rank.** `--read-shift` needs `--per-rank-path` (or any other way to give each rank a distinct store). Before the first iteration the ranks exchange store paths and processor names over MPI, and every rank refuses with exit status 1 when two ranks have the same store path, when the executable does not support the shift, or when `--read-shift-nodes` exceeds the world size.
- **What a reader reads.** The key order of a reader is the key order of its source writer, so a reader looks up exactly what its source wrote. The write and read sides are ordered by barriers: every rank passes the `afterDelete` barrier of its write side before any rank opens a store to read.
- **Directory side effects.** RocksDB readers open read-only (`--lsmio-read-only`, on by default) and write nothing into the peer's directory. LevelDB has no read-only open, so its reader may write bookkeeping files into the peer's directory; each store has exactly one reader per iteration, so no reader changes what another reader sees.
- **Lustre.** With `page-cache` durability, a shifted read on Lustre may include the writer node's write-back (see Section 6.2).
- **`bm_manager`** does not support the shift and refuses the run.

---

## 8. Reading arm names

- A `-sync` arm of `lsmiotool run lsmio backends` (`rocksdb-sync`, `leveldb-sync`, `native-sync`, `adios-sync`, `plugin-sync`) runs its benchmark with `--lsmio-always-flush`. It is not `-e/--sync`, and it has nothing to do with `fsync`: it disables write batching so each record is accessible at once.
- Which setups the durability variants are for: `page-cache` and `page-cache-shift` change behaviour only for the `ROCKSDB` and `LEVELDB` setups, and for `PLUGIN` and `MANAGER` when they run over RocksDB or LevelDB. On `NATIVE`, `ADIOS` and the plugin over native, `page-cache` repeats the base arm's I/O and `page-cache-shift` equals `shift`; `lsmiotool` still accepts them there, and the header records the mode. `shift` and `page-cache-shift` need an executable that supports `--read-shift`: not `MANAGER`.

---

## 9. Installation and compatibility

The installed `LSMIOConfig` gained a `durability` field, and the installed `store_rdb.hpp` changed: `LSMIOStoreRDB`'s constructor gained a read-only parameter and the class gained a member, so the old two-argument constructor symbol is gone. Programs and libraries built against an earlier install must be rebuilt against the new headers.
