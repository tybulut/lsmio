# LSMIO ADIOS2 Plugin Improvements

Status (2026-10-11): steps 1–7 of "Proposed order" are implemented and staged, not committed, with the fixes from two separate reviews ("Review fixes"). Aggregated mode needs `MPI_THREAD_MULTIPLE`: LSMIO now refuses to start it below that level, and EPOCpp requests it ("Thread support"). Step 8, the end-to-end check, runs with EPOCpp's `adios_engine` key (`../EPOCpp/BENCHMARKS.md`, step 2). See "Results" at the end.

Goal: make the LSMIO ADIOS2 engine plugin (`lib/adios-plugin/`) a full ADIOS2 backend for the EPOCpp benchmarks (`../EPOCpp/BENCHMARKS.md`). EPOCpp must be able to write a dump through it and read the dump back through its restart path, per rank and with `--aggregated` (MPI aggregation).

Sources:
- reading the code;
- a standalone attribute round-trip program (`scratchpad/attr/attr.cpp`);
- a separate review of the staged binary-storage change, which ran single-rank and 2–3-rank MPI scratch programs.

## Done (staged, not committed)
- **Binary values:** numeric variables are stored as the raw bytes of the selection (`SelectionSize() * sizeof(T)`) instead of comma-separated text at about 6 significant digits. Reads check the size and `memcpy`.
- **Per-type parsers removed:** the char/short/long double text parsers and the throwing `std::complex` specializations are gone, so complex variables now work.
- **Failed put/get throws** instead of being ignored. With MPI aggregation a client's failed put is reported at close instead ("Aggregated I/O").
- **New test:** `ADIOS.PluginArrays` round-trips double, float, int64, char, complex<double> and a scalar. It fails on the old plugin.
- **Release note:** none. `Release.latest.md` stays as released for 0.3.1 (2026-10-11).
- **`bm_adios --lsmio-plugin` is unaffected:** it writes only `std::string` variables, which the plugin always stored as raw bytes.

## Findings
Line numbers refer to the code before these changes.

### Blockers for EPOCpp

**P1. Attributes are never stored or restored.**
- **Evidence:** a writer defined two attributes and one variable. A fresh reader saw 0 attributes and the variable.
- **Root cause:** ADIOS2 keeps attributes only in the IO's in-memory map (`core::IO::m_Attributes`, `GetAttributes()`). `PluginEngineInterface` has no attribute callbacks, so the engine must persist them itself. BP5 does this in `BP5Writer.cpp:131-135` (marshal on write) and `BP5Deserializer.cpp:1153-1298` (`m_IO.DefineAttribute` on read).
- **Write side:** `LsmioPlugin::WriteVarsFromIO` (`lsmio_plugin.cpp:229-253`) only loops over `m_IO.GetVariables()`.
- **Read side:** `LsmioPlugin::Init()` (`lsmio_plugin.cpp:122-159`) treats every metadata record as a variable and only calls `DefineVariable`.
- ADIOS2's example plugins (`examples/plugins/engine/`) don't handle attributes either; the LSMIO plugin probably copied that gap.
- **Impact:** EPOCpp's restart path starts with `IOPathAdios::readHeader`, which reads the attributes `io_id`, `io_version`, `rank`, `file_per_process`, `job_time`, `basePath`, `iteration`, `meshesPath` and `particlesPath`. So plugin dumps can't be read back.

**P2. Reader `Open` crashes on local values, joined arrays and dimensions above `INT_MAX`.**
- **Cause:** `convertStrToDims` (`lsmio_plugin.cpp:58-71`) uses `std::stoi`, but `WriteVariableInfo` stores `LocalValueDim` as `{18446744073709551613}`. EPOCpp's `writeRank<T>` defines `{adios2::LocalValueDim}` scalars (`IOPathAdios.cpp:664`).
- **Reproduced:** every rank threw `stoi` at reader Open. The exception leaves the constructor after `_lm` (`lsmio_plugin.cpp:117-119`), and with it the MPI collective-I/O server thread, was created. The processes then segfaulted at exit.

**P3. In MPI aggregation modes, failures on non-aggregator ranks are silent.** (Fixed by the asynchronous error status in "Aggregated I/O" below. Accepting values larger than the write buffer, D2, is deferred to a later stage.)
- **Where:**
  - On a non-aggregator rank, `LSMIOManager::put` returns `sendCommand`'s result, which is always true (`manager.cpp:291-293`, `:315-318`).
  - The aggregator's `callbackForCollectiveIO` (`manager.cpp:516`) ignores the store's result.
  - A remote `get` of a missing key returns true with an empty value (`manager.cpp:257-266`).
- **Reproduced (2 ranks, EveryoneWrites, rank 1 writes 136 MB, over the ~126.75 MiB `getMaxValueLen()`):**
  - Every rank's write "succeeded" and nothing was stored.
  - Rank 1's read failed only because of the new size check: "holds 0 bytes, the selection needs 136000000".
  - When rank 0 (the aggregator) wrote the oversized value instead, rank 0 threw and rank 1 hung.
- **Impact:** a write-only run reports success for lost data, and whether a run fails or hangs depends on which rank hits the error.

### Risks

**P4. The reader's offset and the writer's memory selection are ignored.**
- **Reader offset:** `ReadVariable` checks only the size, not `m_Start`. A same-size selection at a different offset silently returns the rank's own stored block. Example: an EPOCpp restart with the same `nproc` but a different `nprocx`/`nprocy` split, read through `readCollective`'s `SetSelection` (`IOPathAdios.cpp:1248`).
- **Writer memory selection:** `WriteVariable` ignores `m_MemoryStart`/`m_MemoryCount` (`SetMemorySelection`), so it would store the wrong bytes. EPOCpp doesn't use this today.
- **Earlier behaviour:**
  - Sub-block selections and multi-step selections now throw a clean size error.
  - The old text reader wrote every stored value whatever the selection, so a smaller selection overflowed the heap.
  - `SetBlockSelection` happens to work, because the plugin never sets `variable.m_Engine`.

**P5. One missing variable stops all later metadata.**
- In `WriteVarsFromIO` (`lsmio_plugin.cpp:244-245`), `if (!v) { return; }` inside the type-dispatch macro exits the whole loop.
- One null `InquireVariable` therefore skips the metadata of every later variable. It should be `continue`.

**P6. `metaPut` failures are ignored.**
- `WriteVarsFromIO` (`lsmio_plugin.cpp:248`) ignores `metaPut`'s result, which is inconsistent with put/get now throwing.
- The failures surface in `DoClose`/`EndStep`.

**P7. Old plugin DBs aren't rejected cleanly** (no longer a concern: old DBs need not be readable, see D5).
- Text-format values mostly fail the size check on read.
- But one whose text length happens to equal `SelectionSize() * sizeof(T)` returns garbage. Example: an 8-character integer read as int64.
- There's no format marker to tell the old and new layouts apart.

**P8. The metadata record is a `;`-separated text line** (`name;type;shape;start;count`, `WriteVariableInfo`, parsed in `Init`).
- It is fine for EPOCpp's variable names.
- It can't hold attribute values (strings such as `basePath` = `/data/%T/` may contain `;`) or binary numbers, which matters for P1.

**P9. Reading a plugin DB writes to it.**
- `DoClose` always calls `PerformPuts` → `WriteVarsFromIO`, even in read mode. `Init()` has defined every variable on the reader's IO, so their metadata is put again and flushed as a new SST at close.
- **Measured:** the baseline read created `L0-000007.sst` (5,133 bytes, one `openat` and one `write`).
- **Fix:** D1 writes metadata only in write mode.

### Nits
- **N1. Zero-count blocks:** `memcpy(values, ..., 0)` with a null `values` is undefined behaviour (UBSan flags it). ADIOS allows null data for zero-count blocks. Guard it with `if (size)`.
- **N2. `long double` padding:** on x86-64 each value carries 6 uninitialised padding bytes. Values round-trip, but the stored bytes are non-deterministic (valgrind warns) and not portable across ABIs.
- **N3. Formatting:** `lsmio_plugin.tcc` isn't clang-format clean (ColumnLimit 100): five wrapped `throw` lines and the `std::string bytes(...)` line fit on one line. CI's clang-format action skips `.tcc`, so it won't catch this. The include order also differs from `lsmio_plugin.cpp`.
- **N4. Release note overstates things:**
  - "A failed put or get now throws" isn't true on non-aggregator ranks (P3).
  - "Cannot be read back" should be "must not be read" (P7).
- **N5. Unused member:** `_variableStoreKey` (`lsmio_plugin.hpp:92`) is used only in a log line. Now `_metadataKey`, the key of the metadata record.

### Tests
- **T1. `ADIOS.Plugin` checks nothing.** `testPluginReader` takes `messages` by value (`test_plugin.cpp:73`), so the caller's vector stays empty and the `EXPECT_EQ` loop (`:111`) runs zero times. This predates the change.
- **T2. `ADIOS.PluginArrays` gaps:**
  - It compares with `EXPECT_EQ`, which treats `-0.0f == 0.0f`, so a lost sign bit would pass. Use `memcmp`.
  - It has no deferred numeric Put.
  - It has no failure-path test: an oversized value, a missing key, a selection mismatch.
  - Its helpers sit in the global namespace of a binary shared with `test_adios.cpp`.
- **T3. No MPI plugin test covers numeric arrays, attributes or aggregation failures.** `test_mpi_adios.cpp` only round-trips one string.

## Constraint: no extra I/O requests (2026-10-11)
None of the changes may add I/O requests on the write or read path. Extra work must stay in CPU and RAM, and a dump must still reach storage as the same writes as before.

How the plugin reaches storage today:
- **A put is a RAM operation in every store.**
  - The native store ignores the per-put `flush` flag and adds the value to the active memtable (`StoreNative.cpp:266-303`).
  - RocksDB batches it ("flush (not-applicable)", `store_rdb.cpp:189`).
  - Disk writes happen only when a memtable fills up (`m_memtable_max_size_bytes`) and is written out as an SSTable, or when the DB is closed. So the `Mode::Sync` puts EPOCpp makes by default (`gConfigAdios.alwaysFlush = true`) don't each become a write.
- **Metadata is put about 3 times per variable.** `WriteVarsFromIO` runs on `PerformPuts`, `EndStep` and `DoClose`, and EPOCpp calls all three (`IOPathAdios.cpp:628`, `EndStep`, `Close`).
  - The sorted memtables overwrite the repeats in RAM (`MemtableVectorSort.cpp:53-57`).
  - `MemtableVectorNoSort` appends every repeat (`MemtableVectorNoSort.cpp:40-43`), so the duplicates are written to disk.
  - In aggregated mode every metadata put from a non-aggregator rank is also an MPI message.
- **Reading:** `Init` does one prefix scan over the metadata (`metaGetAll` → `getPrefix`), and then each variable is read with one `get`.
- **Not changed by this work:** a rank whose dump is larger than the memtable is written as several SSTables. EPOCpp's planned ~240 MB per rank is more than the 128 MiB write buffer.
  - Decision (2026-10-11): the LSM-tree is not changed. `writeBufferSize` stays a tunable with its 128 MiB default (`include/lsmio/lsmio.hpp:144`), the same size `bm_adios` gives ADIOS2 as `BufferChunkSize`.
  - Decision (2026-10-11): a single metadata record written only at `Close` is acceptable. A writer that never closes leaves no readable metadata, as with a BP5 file without its index.

Rules that follow for every change below:
- **Data:** exactly one put per variable per write, and one get per variable per read, as now. The staged binary change already meets this: it builds one `std::string` per variable in RAM, as the text encoder did.
- **Metadata:**
  - **Write:** one record per DB, holding every variable and attribute. It is built in RAM and put once, in `DoClose`; `PerformPuts` and `EndStep` no longer write metadata. This is fewer puts and fewer MPI messages than today.
  - **Read:** `Init` reads the record with one `get`, replacing the prefix scan, and builds the variables and attributes in RAM.
- **Checks:** size, selection and dimension parsing work on values already in RAM and add no requests or messages.
- **Exception, Append mode (accepted 2026-10-11):** opening an existing DB in Append mode reads its metadata record once (one get), to keep its entries in the record written at Close. The old plugin read nothing there. EPOCpp never opens in Append mode.
- **No status round trips:** no change may add an acknowledgement or status message per put or get. D2 Option C is rejected.

Baseline (2026-10-11, the staged plugin, `scratchpad/iocheck`): an EPOCpp-shaped dump with 14 × 16.8 MB particle arrays, 10 field arrays, 20 scalars and 16 attributes, about 238 MB in total, written with `Mode::Sync` puts and read back bit-exact.
- **Write:** 24 `writev` and 2 `write` calls, forming 2 SSTables (120,586,788 and 117,446,183 bytes). The metadata is in the second.
- **Read:** 112 `pread64` and 6 `read` calls, plus 1 `write` of 5,133 bytes into a new SST (P9).

Proposed check: run an EPOCpp-shaped plugin write and read before and after the changes, and compare the write and read system calls on the DB files (`strace -f -c -e trace=write,pwrite64,writev,read,pread64`) and the number of SSTables created. Both must be the same or lower.

## Design questions

**D1. Metadata and attribute layout (P1, P8).** There is no backward compatibility to keep (2026-10-11), so the layout can change freely.
- **One metadata record per DB:** a single key, `__adios_metadata`, written once at `DoClose`. It holds every variable that was put (as in BP5, a variable defined but never put is not listed) and every attribute.
- **Binary, length-prefixed encoding:** a record count, then for each entry:
  - kind (variable or attribute) and name;
  - for a variable: type, shape, start and count as `uint64`;
  - for an attribute: type, element count, whether it is a single value, then raw bytes, or length-prefixed strings for string attributes.
- **No separators:** nothing is `;`-separated, so names and string values may contain any byte, and there is no text parsing (this also fixes P2's `stoi`). In aggregated mode a variable name still must not contain `;` or a NUL byte: the client command format splits on the first `;` with `strchr` (`deSerializeCmd`, unchanged).
- **Variable data keys stay as the variable name:** one put and one get per variable.
- **Aggregated mode:** each rank's record gets the rank suffix (`_rankedKey`), as data keys do. That is still one put per rank per DB and adds no messages.
- Open question: anything EPOCpp or tools read from the metadata by key that must stay readable? I know of none; `bm_adios` only reads its own string variables.

**D2. Values larger than the write buffer (P3): RocksDB's model, deferred to a later stage (2026-10-11, `BACKLOG.md`).** Not needed for the EPOCpp benchmark.
- **Largest value at the planned deck size** (32³ cells and 64 particles per cell per rank): one particle component is about 2.1M doubles, about 16.8 MB. That is roughly 7.5 times below `getMaxValueLen()` (about 126.75 MiB).
- **Until then, values over the limit fail loudly:** the plugin throws on a failed put, and EPOCpp's `IOPathLsmio::putBytes` will throw too (`../EPOCpp/BENCHMARKS.md`, step 2).
- The design is under "Later stage" below.

**D3. Errors.** Throw on the rank where the error happens, as BP5 does: its transport throws `ios_base::failure` on the writing rank (`FilePOSIX.cpp:315`). In aggregated mode, errors recorded on an aggregator are also reported to every rank of its aggregation group at close ("Aggregated I/O").

**D4. Selection semantics (P4).**
- **Reader:** `m_Start`/`m_Count` must equal the stored block's, otherwise throw. This is a CPU comparison against the metadata already in RAM from D1.
- **Memory selection:** throw if `m_MemoryCount` is set (`SetMemorySelection`), on both write and read.
- Reads spanning several ranks' blocks (as BP5 supports) are deferred to a later stage (`BACKLOG.md`). In aggregated mode they are possible, since every rank's data is in one DB under `<rank>::<key>`, at one get per overlapping block (slower aggregation is acceptable). The EPOCpp benchmark doesn't need them: it reads back with the decomposition it wrote. Per-rank mode would need other ranks' DBs.

**D5. Format marker (P7).** Dropped. Old plugin DBs need not be readable. The new layout has a single metadata record, so a DB from the old plugin has none and fails at `Init` with "no LSMIO plugin metadata".

**D6. `long double` (N2).** Dropped. The 6 padding bytes are part of the x86-64 type (an 80-bit value in a 16-byte slot), not something the plugin adds. BP5 copies `sizeof(T)` per element too (`BP5Serializer.cpp:878`). A one-line comment is enough.

## Aggregated I/O: asynchronous error status
Aggregated I/O is in scope. It may be somewhat slower than per-rank mode, which is acceptable (2026-10-11), but it must report errors.
- **How it worked before:**
  - Non-aggregator ranks send puts with a blocking `MPI_Send` and get no reply.
  - The aggregator's server thread takes one command per rank per round (`client.cpp:200-260`). It replies only to GET, META_GET, META_GET_ALL and the barriers.
  - Close sends an EOL command, then an `MPI_Barrier`. The aggregator's last memtable flush runs after that, in `_lcStore->close()` (`manager.cpp:199-216`).
- **Sticky errors:** the aggregator keeps one flag (`_collectiveFailed`, atomic, since the server thread sets it). A failed put, delete, metadata put or write barrier sets it, whether it was a client's command (`callbackForCollectiveIO`) or the aggregator's own write. Nothing is sent; puts stay fire-and-forget.
- **Unequal command counts:** ranks may send different numbers of commands (one rank puts a variable more). A server round now takes a command only from ranks that haven't sent EOL, so a rank that closes early no longer makes the aggregator wait for a command that never comes (a hang, or a mismatched reply, with 3 or more ranks). CPU only, no extra messages.
  - **Limit (unchanged):** until a rank sends EOL, each round still waits for one command from it, and the server posts a rank's receive only inside a round. So any command that blocks counts: a get, metaGet, metaGetAll or barrier waiting for its reply, and a put larger than MPI's eager limit (between 8 and 70 KB here). Such a command deadlocks against a rank that has moved on to an application collective. Reproduced with 3 ranks: rank 2 puts one extra 70 KB value, then all ranks join `MPI_Barrier`; rank 2 never returns from `Put` (with 8 KB or less it completes). Safe as long as every rank sends the same number of commands between application collectives.
- **Final flush before reporting:** at close, the aggregator finishes its last flush (`writeBarrier`) before reporting, so a flush failure is included. Other ranks then wait at close for the aggregator's flush, in aggregated mode only. `bm_*` with `-m` already includes this flush through its barrier after close.
- **Report at close:** the close `MPI_Barrier` becomes an `MPI_Allreduce` of an error flag, which costs the same as a barrier. Every rank of the aggregation group then fails at the same point, which removes the hang where one rank throws and the others wait. The allreduce runs on the group's communicator: under Split, or Shared across nodes, other groups close normally, so an application that needs every rank to agree must check that itself (EPOCpp uses Entire, a single group).
- **Read failures:** a failed GET answers `getFail` instead of `getBack` in the reply that already exists.
- **Known limits (unchanged by this work):**
  - If `Init` fails on some ranks only, a failing client waits in its destructor until the aggregator closes, as it did at the old barrier.
  - Aggregated clients now return from close only after the aggregator's final flush, so per-rank close times are longer. No I/O is added.
- **EPOCpp (`../EPOCpp/BENCHMARKS.md`, step 2):** `IOPathLsmio::pathClose` now throws when `LSMIOManager::close()` fails.
- **Related EPOCpp fix (`../EPOCpp/BENCHMARKS.md`, step 2):** `IOPathLsmio::readHeader` must set `prs.collectiveMode`, so that aggregated native LSMIO dumps can be read back.

## Later stage

**D2. Values larger than the write buffer (P3): RocksDB's model (decided 2026-10-11, deferred).**
- **The limits today:**
  - BP5 has no per-value limit; a block larger than `BufferChunkSize` gets a chunk of its own size (`ChunkV.cpp:139-141`).
  - RocksDB (v10.6.2) accepts any value up to 4 GiB − 1 (`db/write_batch.cc:857-858`). A value larger than `write_buffer_size` makes the memtable go over its target size; `MemTable::ShouldFlushNow` (`db/memtable.cc:200-240`) then reports it full. The value stays whole in one oversized data block, written in one piece and read with one block read. BlobDB is optional and off.
  - LSMIO's native store rejects values over `getMaxValueLen()` (about 126.75 MiB, `StoreNative.cpp:272`), although its on-disk format holds values up to 2 GiB − 1 (`READ_MAX_VAL_LEN`, `SSTableManager.cpp:55`).
  - Every LSMIO user is affected, including EPOCpp's `IOPathLsmio::putBytes`, which ignores the failed put (Blocker 3 in `../EPOCpp/BENCHMARKS.md`).
- **Decision: the native store accepts values up to the format limit, 2 GiB − 1,** as RocksDB accepts values larger than its write buffer.
  - The existing rotation (`StoreNative.cpp:278`) moves the current memtable aside first, so an oversized value lands alone in a fresh memtable.
  - That memtable is moved aside right after the add, so its flush starts at once, as RocksDB's `ShouldFlushNow` does.
  - It becomes one oversized SST. In the flush (`SSTableManager.cpp:299-333`), libstdc++ writes the record straight to the file with one `writev`, so the 128 MiB `m_flush_buffer` doesn't grow. Preallocated space is trimmed to the end of the data as now.
  - **I/O:** one contiguous write per oversized value. Reading takes the existing two-`pread` path for large records, or one `mmap` copy.
  - **RAM:** the value is held in the memtable, plus the record copy made during the flush (`record_buf`), as for any value today.
  - **Key length and the write-buffer tunable are unchanged.** Values within the buffer behave exactly as now.
- **`getMaxValueLen()`:**
  - It becomes the format limit: 2 GiB − 1 minus the record framing.
  - The check that the buffer is too small for any value moves to its own function, which `bm_base.cpp:442` and `StoreNative.cpp:87` use.
  - `test_native_extended.cpp:464-467`, which expects a value just over the buffer to be rejected, changes to expect it to round-trip. A new test checks rejection above the format limit (`m_max_value_len` lowered through a test hook, to avoid allocating 2 GiB).
- **Aggregated mode:** `LSMIOManager::put` rejects a value whose serialized command exceeds `INT_MAX`, `MPI_Send`'s count limit, before sending. This is a CPU check.
- **No change needed in the RocksDB and LevelDB stores,** which already accept such values.
- **Rejected:** splitting in the plugin or in the manager, and a status reply per put. The asynchronous status in "Aggregated I/O" replaces the reply.

## Proposed order
1. **Init fixes:**
   - P2: delete `_lm` if `Init` throws. The `stoi` crash goes away with D1's binary dims.
   - P5: `continue` instead of `return`; this code is replaced by D1 anyway.
   - P6: throw if the single metadata put fails at `DoClose`.
2. **Metadata record (D1):** the single binary record, written once at `DoClose` and read with one `get` in `Init`, including attributes (P1).
3. **Selection checks (P4):** per D4.
4. **Aggregated error status:** sticky errors, the final flush before reporting, an `MPI_Allreduce` at close, and `getFail`.
5. **Tests:**
   - fix T1;
   - harden `PluginArrays` (T2);
   - add an attribute round-trip, including a string containing `;` and a NUL byte;
   - add a `LocalValueDim` scalar;
   - add a value over `getMaxValueLen()`, which must make the plugin's put throw;
   - add a start-offset mismatch;
   - MPI aggregated tests (T3): a round-trip of arrays and attributes, and a failed aggregator put that every rank of the group reports at close.
6. **I/O-count check:** compare `strace` and SSTable counts before and after, as described under the constraint above.
7. **Nits:** N1, N3, N4 and N5 (`Release.latest.md` is left as released).
8. **End-to-end check:** write with EPOCpp's variable and attribute layout and read it back through the restart path.

## Review fixes (2026-10-11)
A separate review of the staged change found the following; all are fixed and staged.
- **A second `Close` after a failed one segfaulted:** ADIOS keeps an engine open when its `Close` throws, and `DoClose` then used the closed manager. `DoClose` now deletes the manager before throwing.
- **A reader's `SetMemorySelection` was ignored** (only the writer rejected it): now rejected on read too.
- **The aggregator's own failed write wasn't reported to the other ranks** at close: it now sets the shared flag (`LSMIOManager::_noteLocalWrite`).
- **Unequal command counts hung the aggregator** with 3 or more ranks (existing behaviour): see "Unequal command counts".
- **Variables defined but never put were listed** to readers: entries are now recorded at put time, after a successful put.
- **Nits:**
  - the record reader's dimension count can't overflow its bounds check;
  - the close error names the file;
  - `close()` logs again;
  - the server loop frees its buffers with `delete[]`.
- **Build:** LSMIO's include directory is now public in a build tree (`lib/CMakeLists.txt`). EPOCpp builds LSMIO from source but compiled against an older installed copy of the headers (`/users/sb2984/src/usr/include/lsmio`, which shares a prefix with ADIOS2), so it could allocate an `LSMIOManager` with a stale layout.

Second review (all fixed and staged):
- **Scope of the close result:** docs and comments said every rank gets the same result; it is every rank of the aggregation group.
- **Command-count limit** documented ("Unequal command counts"), and the Append-mode read recorded as an accepted exception to the I/O constraint.
- **Corrupt records:** an unknown type, an unknown kind, a single-value attribute without exactly one element and an attribute element count that would overflow are reported as a corrupt record. Struct attributes are skipped when writing.
- **Tests:** a corrupt-record test, a joined-array round-trip, and a ctest entry running the plugin MPI tests with 3 ranks (it needs 3 MPI slots: an allocation of exactly 2 fails that one test).
- **Checked, no change:** the RocksDB store's extra flush at close (`writeBarrier` before the store's own close) does no I/O: 13 `write`, 7 `fdatasync` and 6 `fsync` before and after (`scratchpad/rdbcheck`).
- **Not covered by tests:** `LSMIOClientAdios` (the aggregation client over an ADIOS communicator) is compiled but unused, so its EOL change is untested.

## Thread support (decided 2026-10-11)
- The aggregator runs a server thread that makes MPI calls (`MPI_Probe`, `MPI_Irecv`, `MPI_Send`) while the main thread makes its own (the startup barrier, the application's calls). MPI allows that only when it was started with `MPI_THREAD_MULTIPLE`.
- `LSMIOClient::checkThreadSupport` logged the level but its result was ignored (and it returned true when the level was *not* `MPI_THREAD_MULTIPLE`).
- LSMIO's benchmarks and tests start MPI with `MPI_THREAD_MULTIPLE`. EPOCpp called plain `MPI_Init` (`src/parallel.cpp:602`), which gives `MPI_THREAD_SINGLE`, until the decision below.
- The second review reproduced segfaults in aggregated mode under plain `MPI_Init` (3 of 22 runs, none in 50 with `MPI_THREAD_MULTIPLE`).
- **Decision:** EPOCpp starts MPI with `MPI_Init_thread(MPI_THREAD_MULTIPLE)` (`src/parallel.cpp`), so every backend runs at the same level, and rank 0 warns when MPI provides less. Checked with a PMPI shim: EPOCpp requests and gets `MPI_THREAD_MULTIPLE`. Aggregation without a server thread is in `BACKLOG.md`.
- **Decision, for now:** LSMIO refuses aggregation below `MPI_THREAD_MULTIPLE`. `LSMIOManager` throws `std::runtime_error` at open when the communicator has more than one rank and MPI provides less, on every rank, so no rank waits on one that gave up. A single rank (`MPI_COMM_SELF`, or no communicator) is unaffected. A rank alone in its Split or Shared group is refused too, although it starts no server thread: refusing only some ranks would leave the others waiting. `checkThreadSupport` is now static, returns the right answer, and runs before any directory, store or aggregation communicator is created (the duplicate of an ADIOS communicator is freed); `LSMIOManager::initialize` and `LSMIOStream::initialize` used to leave their "initialising" flag set when the manager's constructor threw, so every later call was refused with "already initialiazing", a warning hidden at the default log level. Their three flags (initialised, initialising, cleaning), checked and set in separate steps, are now one `LifecycleState` (None, Initializing, Ready, Cleaning) changed by compare-exchange: a failed initialize goes back to None and logs the cause at `ERROR` (a retry on the same path can still fail if the manager failed after opening its store, which then leaks), two threads can no longer both initialize, and refusals name the state. Each `LSMIOStream` read and write still does one atomic load, so I/O is unchanged. Not addressed: `cleanup` can delete the manager while another thread still uses it. Tests: `lsmioPosix.StreamInitializeFailure`, `StreamConcurrentInitialize`, `lsmioManager.InitializeLifecycle`, `ConcurrentInitialize`; the concurrent test fails 24 of 30 runs with the old check-then-set. Applications that start MPI with plain `MPI_Init` and give LSMIO a multi-rank communicator now fail at open instead of risking a crash; LSMIO's own tools already request `MPI_THREAD_MULTIPLE`. The one possible casualty is the LAMMPS workload (`lsmiotool` target `lmp`), a patched LAMMPS that calls LSMIO directly (`-lsmio-buf-size-mb`): if it starts MPI with plain `MPI_Init` (not checked) and gives `LSMIOManager` a multi-rank communicator, it now fails at open; through `LSMIOStream` (no communicator) it is unaffected. Without a code change, `OMPI_MPI_THREAD_LEVEL=3` (Open MPI; checked with 5.0.3: plain `MPI_Init` then provides `MPI_THREAD_MULTIPLE`) or `MPIR_CVAR_DEFAULT_THREAD_LEVEL=MPI_THREAD_MULTIPLE` (MPICH, not checked) raises the level plain `MPI_Init` asks for. Test: `managerMPIThreadTests.AggregationNeedsThreadMultiple`, run as usual and again below the level (`managerMPIThreadTests.ThreadSerialized`, `--mpi-thread-serialized`); it fails when the check is disabled.
- **Related:** EPOCpp's `IOPathLsmio` passes its own communicator to `LSMIOManager`, which uses it as is (the plugin passes a duplicate). The server's `MPI_Probe(ANY_TAG)` could then take EPOCpp's own point-to-point messages.

## Results (2026-10-11)
- **Tests:** the full LSMIO suite passes, 223/223. New:
  - `ADIOS.PluginAttributes`, `PluginLocalValue`, `PluginJoinedArray`, `PluginSelectionMismatch`, `PluginOversizedValue`, `PluginUnputVariable`, `PluginAppend`, `PluginCorruptMetadata` and `PluginMissingMetadata`;
  - `pluginMPITests.ArraysAndAttributes` and `FailedPutReportedAtClose`, each under all five aggregation layouts, with 2 ranks and again with 3 (`pluginMPITests.ThreeRanks`); they also pass with 4, 5 and 7. `FailedPutReportedAtClose` fails a client's put, then an aggregator's, and closes again after the failure.
  - EPOCpp's suite gives the same result as before the change: 78/86, with the same 8 failures, all from the PMIx singleton environment (`OMPI_MCA_orte_precondition_transports`).
  - `ADIOS.Plugin` now checks its strings, and `PluginArrays` compares bytes and includes a deferred Put.
- **I/O check, per rank** (`scratchpad/iocheck`, 238 MB EPOCpp-shaped dump):

  | | Before | After |
  |---|---|---|
  | Write | 24 `writev` + 2 `write` | 24 `writev` + 2 `write` (less metadata) |
  | SSTables | 2, plus 1 written by the reader | 2 |
  | Read | 112 `pread64` + 6 `read` + 1 `write` | 69 `pread64` + 6 `read` |
  | Attributes seen by the reader | 0 | 16 |

- **I/O check, aggregated** (2 ranks, `EveryoneWrites`, 124 MB):

  | | Before | After |
  |---|---|---|
  | Write | 50 `writev` + 2 `write` | 49 `writev` + 1 `write` |
  | SSTables | 1, plus 1 written by the readers | 1 |
  | Read | 268 `pread64` | 138 `pread64` |

- **Data:** every run read back bit-exact. The review fixes leave every count above unchanged (re-measured).
