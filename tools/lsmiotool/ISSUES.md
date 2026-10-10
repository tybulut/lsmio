# lsmiotool ↔ bmtool parity issues

Audit of `tools/lsmiotool` against `tools/bmtool` (the reference implementation), 2026-10-10,
at `tybulut/str-overhead` 6eccef7. Paths are relative to `tools/`. Line numbers are as of the audit.

Verified to match bmtool: all 61 variant flag mappings and the `most`/`all` lists; scale
matrices; LSMIO block size / key count map; IOR/LMP argv; Lustre `-S/-c/-p` striping; Slurm
walltime/qos/memory per site; srun/aprun launch flags; module lists; arm-ID derivation
(incl. `version-` IDs); archive destination rules; `compare` on bmtool-produced archives.

Root causes behind most entries:

1. `RunOrchestrator.execute()` is a single generic path (one stripped-down plan per variant, then
   one `executeArchive`). bmtool's backends / versioned / paired branches of `jobs/batch.in.sh`
   were never ported; the building blocks exist and are unit-tested but are not wired.
2. Fail-fast everywhere, where bmtool records the failure and continues.
3. bmtool's environment setup (`include/vars.in.sh`, `qsub -v`, ARCHER2 relocation, env-var
   overrides) was dropped.
4. The parser requires a pristine artifact-store run layout, which the archive step breaks.

Status: `[ ]` open, `[x]` fixed.

---

## High — wrong or missing results, hangs, site breakage

### [x] H1. `lsm-report.csv` holds rank 0's numbers instead of the sum across ranks
- bmtool `bmtool/parse/lsmio-parse.sh:39-40` sums columns 2–6 of every rank's `write,`/`read,`
  line and takes the max of `iter`; 10-column rows.
- lsmiotool `lsmiotool/lib/output.py:676-737` (`LsmioAggOutput.generateReports`) copies the first
  file's line verbatim; same in `lib/runparse.py:1320-1338` (`LsmioLogExtractor`) and
  `:1788-1814` (`LsmioReportGenerator`). Header and column count (13) also differ.
- Reproduced: variants-0.3.0 autotune:run 8 nodes 4/1M write — bmtool 4169.77, lsmiotool 521.21;
  backends/small native 16 nodes — 5461.88 vs 341.37.
- Reaches `parse`, `parseLegacy`, parse-on-demand in `compare variants`, and the pre-archive
  report in `archive.py`.

### [x] H2. Run modes: versioned, paired-baseline, backends and single-allocation are not implemented
- **H2a** Per-variant sub-`RunRequest` in `lib/run.py` `RunOrchestrator.execute` (~4365) drops
  `f_versioned`, `f_mode`, `f_backends`, `f_archive`, `f_resume`, `f_out_dir`.
- **H2b** No versioned flow (bmtool `jobs/batch.in.sh:257-415`): no `bm_native:main` reference
  baseline, no `version-<branch>-<hash>-<variant>` arm ID, no `:base` archive.
- **H2c** No paired pre-baseline for non-versioned variants (bmtool `batch.in.sh:415-470`); only
  `:run` is archived; `ArchiveEngine.executePairedArchive` is never called. `compare variants`
  drops every lsmiotool run as "orphaned".
- **H2d** Backends mode (bmtool `batch.in.sh:125-250`) never runs the backend list; only
  `bm_native` runs, walltime formula is not applied, and nothing is archived by default.
- **H2e** Each variant is its own plan + scheduler submission; bmtool runs baseline + all variants
  in one allocation on the same nodes (INV-PAIR-1).
- **H2f** The archive moves the artifact-store run root (`manifest.json`, `control/`, `points/`)
  instead of bmtool's `<nodes>/…/out-*.txt` + `lsm-report.csv` layout.

### [x] H3. LAMMPS runs in an unstriped directory
- bmtool `batch.in.sh:91-93` copies `lmp-reaxff` into the striped `$DIRS_BM_BASE/c$rf/b$bs/` and
  `lmp-benchmark.sh` `cd`s there (checkpoints are written to cwd).
- lsmiotool `lib/worker.py` (~2300-2380, ~2530-2565) stages assets into and launches from
  `pointCombinationWorkDir` (`work/c16_b8M`); only `data/c16/b8M` is striped. All six LMP
  combinations run with default striping.

### [x] H4. Benchmark data is never deleted
- bmtool `batch.in.sh:118-119` empties `c$rf/b$bs` after every combination (peak quota = one
  combination) and `dirs-cleanup.in.sh` runs around every run.
- lsmiotool `lib/worker.py` `AllocationController.run` never removes `points/*/data`; it accumulates
  forever (>1 TiB per large-scale point).

### [x] H5. Fail-fast at combination, point and variant level
- bmtool records the failed step and continues (`batch.in.sh:87-122`, `:441-446`;
  `submission.in.sh:220-227`); only a failed baseline aborts.
- lsmiotool returns on the first failed combination (`worker.py:2412/2598/2712`), stops at the first
  non-succeeded point (`run.py:5156-5168`) and the first failed variant (`run.py:4442-4454`).

### [x] H6. One `UNKNOWN` scheduler poll ends monitoring and orphans the job
- bmtool `submission.in.sh:181-200` keeps polling.
- lsmiotool `scheduler.py:2511-2560` returns `UNKNOWN` when squeue and sacct both fail/are empty
  (e.g. sacct lag after submit); `run.py:~5118` treats it as terminal, the run breaks, no scancel.

### [x] H7. lsmiotool-produced archives cannot be parsed; `compare` writes an empty report into them
- `runparse.py:645-648` rejects an archived root (basename ≠ `run_id`, not under `runs/`): exit 4.
- `compare variants` (`main.py:915-940`) falls back to the legacy parser, finds no node dirs and
  writes a zero-byte `lsm-report.csv` into the archive; later runs accept it via `isfile`.
- `executeArchive` recreates the moved source, leaving empty `runs/run-*` directories.

### [x] H8. `parse lsmio [backends] <scale>` cannot find runs
- `cli.py:827-845` parses mode/scale but `main.py:399` calls only `RunRootResolver.resolveTarget`.
- `runparse.py:898-907` `inferLatestRun` searches `~/scratch/benchmark/lsmio/runs`; runs live in
  `<benchmark_root>/runs`. Exit 3. It also does not filter by target.
- bmtool `lsmio-parse.sh:77-98` regenerates per-backend reports in the archive.

### [x] H9. `LD_LIBRARY_PATH` / `ADIOS2_PLUGIN_PATH` never set; no plugin preflight
- bmtool `include/vars.in.sh:38-43,181-186` exports both from `$PROJECT_DIR`; `bmtool:548-553` and
  `batch.in.sh:164` check `liblsmio_adios.so` exists.
- lsmiotool sets them only in `lib/env.py:201-206`, which the run path never imports
  (`scheduler.py:845-927` script, `worker.py:1680-1694` launch env).

### [x] H10. PBS submission propagates no environment
- bmtool `submission.in.sh:172-173` `qsub -v BM_SCRIPT,…`.
- lsmiotool `scheduler.py:2867-2875` `["qsub", script]`.

### [x] H11. ARCHER2: no relocation off `/home`
- bmtool `bmtool:112-142` rsyncs the tools to `$ARCHER2_WORK_ROOT/tools` and re-execs (compute
  nodes cannot read `/home`).
- lsmiotool `run.py:4145-4153` puts the source-tree `lsmiotool-worker` into `job.sh`.

### [x] H12. ARCHER2 site detection
- `site.py:959-977` checks all rules and raises "Ambiguous site detection" on `nid*` hosts with the
  `archer2` group; bmtool `vars.in.sh:164-178` is first-match in order viking, viking2, archer2,
  isambard.
- `env.py:116-125` matches only `"archer2" in HOSTNAME`: `ln01` → DEV, `nid*` → ISAMBARD.

### [x] H13. A scheduler-level job failure marks every arm FAILED, including finished ones
- `lib/run.py` `_executeArmGroup` mirrors every observation to all arms; `lib/state.py`
  `_derivePointState` turns a FAILED/TIMEOUT job state into a point failure.
- The group job exits 0 on worker failures, but TIMEOUT / OOM / node failure still reach every
  arm. A backends point whose last backend hits walltime leaves all backends TIMED_OUT: nothing
  archived, `--resume` reruns all. bmtool has already archived the finished backends.

### [x] H14. Mirrored arms get no cancel records on interruption
- `_cancelActiveJob` writes `cancel_requested` / `cancel_recorded` / the final observation only to
  the dispatching arm. Other arms reconcile INDETERMINATE ("cancelled without a requested
  cancellation record"), so `recoverRun` on them cannot settle.

---

## Medium

- [x] **M1.** `--time` on a PBS site crashes rendering: the override (`run.py:1550-1561`) is not gated
  on `walltime_policy`; `scheduler.py:1958-1962` requires `06:00:00`. bmtool PBS ignores it.
- [x] **M2.** PBS large: `select={nodes}:ncpus={ppn}:mpiprocs={ppn}:mem=32GB` (`scheduler.py:2014`)
  gives 32GB per 4 ranks; bmtool `select=$concurrency:mem=32GB` (`submission.in.sh:174`).
- [x] **M3.** Module loads run under `set -euo pipefail` (`scheduler.py:902-915`); one failing
  `module load` kills the job. bmtool tolerates and logs (`load-modules.in.sh:125-142`).
- [x] **M4.** `--archive/--resume/--dest/--time` accepted for scaling scales and ior/lmp
  (`cli.py:448-588`); ior/lmp runs get archived as `outputs-native`; `--resume` can skip a whole run
  and return synthetic success. bmtool rejects (`bmtool:474-489`) / forces no archive (`:407-417`).
- [x] **M5.** `--resume` skips the default/baseline when `outputs-native` exists (`run.py:4342`);
  bmtool only resumes paired/backends `:run` arms.
  *(Second pass: resume now skips only variant `:run` arms and backends `<nodes>` dirs, as
  bmtool; standalone runs and the versioned run without variants rerun.)*
- [x] **M6.** `BM_SETUP` and `BM_WALLHOUR` env vars are ignored (bmtool `bmtool:516`,
  `submission.in.sh:23-24`).
- [x] **M7.** An exported `LSM_DIR_OBASE` is purged on the login node and used as the archive source
  (`run.py:4317-4329`, `:4458`).
- [x] **M8.** `lsmiotool archive` resolves source/dest from cwd and inherited env, hardcodes
  `NATIVE-M` (`main.py:1694-1729`).
- [x] **M9.** A partially failed run produces no report (`runparse.py:684-731`; `output.py:523-527`
  `MissingDataError`, swallowed in `archive.py:256`). bmtool skips missing nodes.
- [x] **M10.** An archive error aborts remaining variants and exits 1 after a successful run
  (`run.py:4477`).
- [x] **M11.** `--time HH:MM:SS` not clamped to 48h (23h with `--fast`) (`cli.py:563`,
  `run.py:1554-1561`); can auto-promote to ARCHER2 `qos=long`. Repeated `--archive`/`--resume` is a
  hard error (`cli.py:494`).
- [x] **M12.** Combination order reversed: lsmiotool c16/8M→c4/64K (`artifacts.py:87-94`,
  `run.py:1342`); bmtool `for rf in 4 16; for bs in 1M 64K 8M`.
- [x] **M13.** Logs are buffered until exit, stdout then stderr (`worker.py:414-485`); a step killed at
  walltime leaves no log; no `sleep 3` between steps.
- [x] **M14.** Legacy IOR report: second `StdDev` overwrites the first (`data.py:142-160`,
  `output.py:449-456`): 466.80 → 7468.8.
- [x] **M15.** `parseLegacy lsmio` reads `<BM_DIR>/logs/jobs` instead of `$BM_PATH/lsmio/outputs`,
  no path argument, no backends (`main.py:126-184`).
- [x] **M16.** LMP report shape differs (one row per file, throughput only, `output.py:883-889`);
  `LmpSummaryData` reads bmtool rows' `row[3]` as 0 (`data.py:551-557`). *(plausible — no real LMP
  outputs to confirm)*
- [x] **M17.** `parse lsmio <scale>` treats a bare benchmark name as a path when the cwd has a
  `lsmio/` (or `ior/`, `lmp/`) dir with an `outputs-*` child (`main.py` `_isOutputsTarget` check
  runs first): from `~/scratch/benchmark` it parses `lsmio/outputs-failed`.
- [x] **M18.** `run` honours an inherited `BM_ARCHIVE_DEST` (`run.py` archive dest resolution);
  bmtool clears it at startup and lsmiotool `archive`/`parse` ignore it, so `run` archives/resumes
  where `parse`/`compare` do not look.
- [x] **M19.** An exported `BM_SETUP` is applied to every target (`cli.py`); bmtool hard-sets
  `BASE`/`LSMIO` for ior/lmp, so `BM_SETUP=NATIVE-M lsmiotool run ior local` fails preflight.
- [x] **M20.** `archive --source <dir>` moves any directory without `manifest.json`
  (`main.py` → `ArchiveEngine.executeArchive`); bmtool only ever moves `$LSM_DIR_OBASE`.
- [x] **M21.** The archived-run marker (`.lsmiotool-run.json`) is written only by
  `lsmiotool archive`, not by `run`'s own archiving, and arm manifests do not record the arm's
  kind/role: `archive` can re-export a group arm (baseline, `bm_native:main` reference, a backend)
  as a standalone `outputs-native`.
- [ ] **M22.** A group arm can never be archived by hand: `archive` (`main.py` source check and
  `_latestRunRoot`) refuses/skips every run root with `.lsmiotool-arm.json`, saying `run`
  archives it, which is false after `--no-archive`, a failed archive step ("ERROR: archiving
  arm … failed") or an interrupt (L15). The arm marker does not record whether the arm was
  archived; refuse only when `findArchivedRun` finds the run.
- [ ] **M23.** `archive --source` accepts an existing archive dir (it satisfies
  `isBmtoolOutputDir`) and moves it: `--source <dest>/outputs-native-footer:run` renames it to
  `outputs-native-footer` and leaves an empty `:run` next to `:base` (compare sees an empty arm,
  `--resume` skips footer). `lsmio/outputs-failed/<x>` is accepted too. Refuse sources holding
  `.lsmiotool-run.json` or under an archive dest / `outputs-failed`.
- [x] **M24.** Archiving only happens at the end of `execute`, never after an interrupt. bmtool
  archives each backend's `<nodes>` dir inside each job. lsmiotool archives after all points, and
  not at all when interrupted, so per-(arm, point) resume only helps after failed points: an
  interrupted `backends large` after 5/8 points reruns all 8.
- [x] **M25.** `parse lsmio variants` always reads the archive. `lib/main.py` routes
  `variants`/`baseline` to the archive dest; bmtool `lsmio-parse.sh` uses the archive dest only
  for backends mode and parses the live outputs otherwise. After an unarchived `run lsmio
  variants`, `parse lsmio variants` exits 3 or silently re-parses an old archive.
- [x] **M26.** Archived rank files are not named by host. bmtool names them
  `out-…-${SLURMD_NODENAME}-${SLURM_LOCALID}.txt` (`hostname`-`ALPS_APP_PE` on PBS).
  `lib/export.py` used `node<node_rank>`, and `node_rank` is `SLURM_NODEID`. The 2026-10-10
  versioned run (job 37416785) archived `node0-0` … `node7-0` where bmtool had `node097-0` …,
  and the real host was recorded nowhere. On PBS, where `node_rank` is the hostname, names became
  `nodenid001234-0` and every rank on a node collided on suffix 0, falling back to `-r<rank>`.

## Low

- [ ] **L1.** `--opt=value` forms rejected (`cli.py:571-588`); bmtool documents `--dest=`, `--time=`.
- [ ] **L2.** Backend list not validated (unknown, duplicate, `adios`+`adios2`, empty) (`cli.py:371-379`
  vs `bmtool:245-266`).
- [ ] **L3.** `NATIVE` (non-MPI) and `ENV` setups rejected (`benchmarks.py:982-993`,
  `run.py:1435-1446`).
- [ ] **L4.** Default variant omits `--lsmio-no-autotune` (`variants.py:647-661`); no effect today
  (binary default is false).
- [ ] **L5.** `.db` naming `lsmio-rank-N-native-m…` vs bmtool `lsmio-<node>-<local>-native…`.
- [x] **L6.** sbatch lacks `--export=ALL` (`scheduler.py:2188`).
- [ ] **L7.** Submit-ID parsing requires `^[0-9]+$` (`scheduler.py:1229`); `id;cluster` reports
  failure while the job is queued.
- [ ] **L8.** `ARCHER2_WORK_ROOT` override ignored (`etc/environments.json`).
- [ ] **L9.** Job names / log paths differ (`lm-<hex>` vs `LSMIO-SM-…`).
- [ ] **L10.** `:run`/`:base` collision suffixes checked independently (`resolveTargetDirectory`);
  `_pairDirectories` fallback (`main.py:1062-1065`) can mispair.
- [ ] **L11.** `parse` output: min MiB/s printed as "Duration" (`runparse.py:1588`); JSON `iter` /
  `block_kib` misnamed; report written to cwd.
- [ ] **L12.** `compare nodes` labels collision dirs by raw name; `compare variants` drops standalone
  variant dirs when any `:run` exists (`main.py:1049-1052`).
- [ ] **L13.** MPI child spawned with `close_fds=True` (`worker.py:415`); breaks PMI2 fd handoff on
  sites using `--mpi=pmi2` (not Viking2).
- [ ] **L14.** `lib/jobs.py` is dead code that has drifted from bmtool.
- [ ] **L15.** On interruption, arms that already finished in the interrupted point become
  CANCELLED (H13's completion override is not applied on the cancel path) and are not archived.
- [ ] **L16.** `parse … --ssd` is rejected though bmtool documents it; the global `--ssd` does
  not reach `ParseMain`, which searches the hdd root first.
- [ ] **L17.** `parse lsmio <scale>` picks an effectively random arm of a multi-arm run (arms share
  the creation second; "latest" is decided by random hex).
- [ ] **L18.** `ProcessRunner` timeout can block on a grandchild holding the pipes (only the
  direct child is killed). Pre-existing; no production caller passes a timeout.
- [ ] **L19.** `recoverRun` does not call `relocateForSite` (ARCHER2 /home worker path).
- [ ] **L20.** Stale docstring: `cli.py` parse help says `parse lsmio variants` uses the archive.
- [ ] **L21.** A symlink `--source` passes the M20 realpath check but `shutil.move` moves the link
  itself: the archive becomes a symlink to the live outputs.
- [ ] **L22.** Resume: `--resume` is silently dropped with `--no-archive` for paired/backends runs
  (bmtool's paired/backends branches always archive and honour `BM_RESUME`); when every variant is
  resumed lsmiotool skips the baseline job and reports success, while bmtool still runs the
  baseline (undocumented difference).
- [ ] **L23.** Resumed (skipped) points leave that arm's run IN_PROGRESS forever (point
  NOT_STARTED, no `whole_run_succeeded`): the run exits 0 but `parse <arm root>` exits 4.
- [ ] **L24.** `archive` says "no lsmiotool run … was found" when matching runs exist but were
  skipped as group arms.
- [ ] **L25.** `parse ./lsmio` (a dir holding `outputs/` and `outputs-failed/`) treats
  `outputs-failed` as an archive arm and ignores `outputs` (exit 5); exclude `outputs-failed` and
  `outputs-baseline-staged`.
- [ ] **L26.** The run marker merges points only for the same run id: a backends `outputs-<arm>`
  dir topped up by a later `--resume` run names only the new run. No functional impact today
  (`findArchivedRun` is only used for standalone runs).
- [ ] **L27.** ISSUES.md contradictions: the H7 note says M8 is still open; the H8 note says
  `parse lsmio variants` reads the archive (contradicts M25); the H-pass M4 note says the CLI still
  accepts the options (contradicts the medium-pass M4 note).
- [ ] **L28.** Test hygiene: `ArchiveTest._lsmiotoolRun` calls `RunParseTest.setUp()` without
  `tearDown`, leaving 4 empty `/tmp/lsmiotool-runparse-test-*` dirs per suite run.
- [ ] **L29.** Crash right after dispatch leaves companion arms without submission records.
  Mirrored records are written after `dispatchSubmission` returns; `recoverRun` on a companion arm
  could submit a second job that races the shared one.
- [ ] **L30.** Some interrupts in the group loop record no INTERRUPTED control event. Interrupt
  between points, or as the job turns terminal, hits a plain `break`.
- [ ] **L31.** An externally cancelled job does not stop a multi-arm run. The group loop stops
  only on UNKNOWN; the single-arm loop stops on INDETERMINATE.
- [ ] **L32.** Final state / exit code lines. Multi-arm runs never call `reportCompletion`;
  single-arm runs report the exit code before archiving, so an archive failure prints "Exit Code:
  0" while exiting 1.
- [ ] **L33.** Stale help text. `lib/cli.py` run help still says the backends "are not yet run one
  after another".
- [x] **L34.** Arm manifests record the arm's own walltime, not the shared job's. In job
  37416785 the job asked for `08:00:00` (bmtool's versioned rule, 2 + 3 runs × 2h), but the
  reference manifest said `04:00:00` and the variant manifests `06:00:00`. Each arm's plan was made
  from its own sub-request.

---

## Resolution notes (high-priority pass)

- **H1** `data.py` reproduces `lsmio-parse.sh` exactly (awk `%.6g`, sums of columns 2–6, max
  of `iter`, en_US glob order); `output.py` `LsmioAggOutput` and `runparse.py` use it.
  `test/parse/BmtoolParityTest.py` runs bmtool's own shell functions and compares bytes.
  Deliberate difference: a combination with no rank logs is skipped with a warning instead of
  writing bmtool's junk `write,,,,,,0` agg file.
- **H2** `lib/arms.py` resolves a request into arms (single / paired / versioned / backends).
  Each arm is its own run root; multi-arm requests submit one job per scale point whose tail is
  `exec lsmiotool-worker allocation-group <point> <policy> <manifests…>`
  (`AllocationGroupRunner` in `worker.py`). The first arm dispatches; the others get the same
  submission and scheduler observations in their own evidence. The group job always exits 0 so
  the scheduler does not mark successful arms FAILED; each arm's outcome is its own controller
  evidence. A failed baseline stops a paired job (bmtool). Walltime comes from the whole request.
  Results are archived in bmtool's layout by `lib/export.py`. The reference baseline arm's
  manifest names `bm_native:main`; it is preflighted (hint: `./build.sh install:main`).
- **H3/H4** LMP runs from `<data>/c<rf>/b<bs>/lmp-reaxff`; each combination's data dir is
  emptied after it completes (directory and striping kept).
- **H5** The worker records a failed combination and continues; a failed point no longer stops
  later points. An INDETERMINATE point (job lost track of) still stops them, so jobs never overlap.
- **H6** UNKNOWN polls are retried up to `RunOrchestrator.UNKNOWN_POLL_LIMIT` (75, ~10 min).
- **H7** Zero-byte reports count as missing and an empty report is never written; archived
  (moved/renamed) run roots parse via `ArchivedArtifactLayout`. Still open: the standalone
  `lsmiotool archive` command (M8) recreates the moved source, leaving empty `runs/run-*` dirs.
- **H8** `parse lsmio [backends|variants] <scale>` uses the site profile's benchmark root,
  filters by target/scale, and regenerates per-arm reports in the archive dest.
- **H9–H12** Job script exports `LD_LIBRARY_PATH`/`ADIOS2_PLUGIN_PATH`; `qsub -V` and
  `sbatch --export=ALL`; first-match site detection in bmtool's order; `lib/relocate.py` rsyncs
  the tools to `$ARCHER2_WORK_ROOT/tools` when they live under /home. `-V` was not verified
  against Isambard's PBS.
- Fixed along the way: **M5** (resume only applies to archived arms), **M7** (no
  `LSM_DIR_OBASE` purge/source), **M10** (archive errors are per arm and reported), **L6**.
  **M4** is partly addressed: ior/lmp and plain scaling runs are never archived or resumed, but
  the CLI still accepts the options.

## Resolution notes (H13, H14, M24, M25)

- **H13** When the shared job ends FAILED / TIMEOUT / CANCELLED, an arm whose worker recorded a
  result for every combination gets its own completion as the terminal observation
  (`state: succeeded`, with the raw `job_state` and `arm_completed_before_job_end` kept in the
  payload); unfinished arms keep the job's state.
- **H14** After cancelling, the dispatching arm's `cancel_requested` / `cancel_recorded` /
  `cancel_unconfirmed` records (same timestamps) and final observation are copied to every arm
  sharing the job.
- **M24** Multi-arm requests always use the group loop, which archives each scale point right
  after its job ends; paired :run/:base dirs are resolved once per arm and reused.
- **M25** Only `parse lsmio backends <scale>` reads the archive dest; `parse lsmio variants`
  parses the latest run. An archive dir can still be parsed with `parse <dir>`.

## Resolution notes (medium pass)

- **M1** A site whose walltime policy is fixed (PBS templates) ignores `--time`/`--walltime`, as
  bmtool's PBS jobs do; the plan keeps `06:00:00` and the script renders.
- **M2** PBS keeps one chunk per node (`select=<nodes>:ncpus=<ppn>:mpiprocs=<ppn>`, which
  `aprun -N <ppn>` needs) but asks for the policy memory per rank: `mem=<ppn x 32GB>`, matching
  bmtool's 32GB per task. (bmtool's literal `select=<tasks>:mem=32GB` leaves node packing to PBS.)
- **M3** Module commands run under `set +eu`, each as `module … || echo "WARNING: … failed" >&2`,
  then `set -eu` before the library exports and the worker.
- **M4** Plain scaling runs (`local/bake/small/large`, any target) reject
  `--archive/--no-archive/--resume/--dest/--time` like bmtool; ior/lmp are never archived.
- **M6** `BM_SETUP` (when `--setup` is absent) and `BM_WALLHOUR` (when `--time` is absent, any
  scale, clamped to [1, 48]) are honoured.
- **M11** `--time HH:MM:SS` is clamped to [1h, 48h] ([1h, 23h] with `--fast`) like integer hours;
  repeated `--archive`/`--no-archive`/`--resume` are accepted.
- **M12** Combinations run in bmtool's order: `for rf in 4 16; for bs in 1M 64K 8M`.
- **M13** `ProcessRunner` writes output to the log as it arrives (stdout and stderr interleaved,
  like `2>&1 | tee`), still capturing both; the worker pauses 3 s between steps
  (`LSMIO_STEP_SETTLE_SECONDS` overrides; the test package sets 0).
- **M8** `lsmiotool archive` uses the site profile's (hdd) benchmark root, ignores inherited
  `BM_ARCHIVE_DEST` (bmtool clears it; `--dest` overrides), takes `--setup` / `$BM_SETUP` /
  NATIVE-M and an optional `--source`. A bmtool outputs dir is moved like bmtool; otherwise the
  latest matching run root's succeeded points are exported in bmtool layout (run root left in
  place, no empty `runs/run-*`), marked with `.lsmiotool-run.json` so a run is not archived twice.
- **M9** `parse` reports every complete point/combination of a partial run and warns about the
  rest. Exit codes keep the existing scheme (4 run not succeeded, 5 extraction gaps) even when a
  partial report was written.
- **M14** The second IOR `StdDev` column is `StdDev(OPs)`; the legacy IOR report reproduces
  `ior-parse.sh` byte for byte (tested against the real script).
- **M15** `parseLegacy` reads `$BM_PATH/<benchmark>/outputs` from the site profile (ssd root with
  `--ssd`), takes an optional path, and supports `parseLegacy lsmio backends <scale>`.
- **M16** LMP reports match `lmp-parse.sh` (`n,rf,bs,<last ^.write, line up to ':'>`) and
  `LmpSummaryData` reads the throughput after the `…write`/`…read` label. Verified against a
  constructed fixture only (no real LMP outputs available).

## Resolution notes (second review pass)

- **M5** Resume skips only variant `:run` arms and backends `<nodes>` dirs; standalone runs and
  the versioned run without variants rerun (bmtool archives them to a `-N` suffix).
- **M17** A bare `ior`/`lsmio`/`lmp`/`lammps` parse target is always the benchmark; a same-named
  directory in the cwd is parsed only when given as a path (`./lsmio`).
- **M18** `run` archives only to `--dest` or the default destination; an inherited
  `BM_ARCHIVE_DEST` is ignored, as in bmtool and lsmiotool's `parse`/`archive`.
- **M19** `BM_SETUP` applies to lsmio only.
- **M20** `archive --source` refuses anything that is neither a run root nor a bmtool outputs dir
  (`<nodes>/<date>/out-*.txt*`) other than `<root>/lsmio/outputs`.
- **M21** Every arm of a multi-arm run gets `.lsmiotool-arm.json` (group kind, label, role, arm
  ID, sibling run IDs) next to its manifest; `run`'s archiving writes `.lsmiotool-run.json` in each
  archive dir it fills (points merged for backends). `archive` skips group arms when picking the
  latest run and refuses one given as `--source`.

## Resolution notes (2026-10-10 run check)

- **M26** Rank results record `host` (`SLURMD_NODENAME`, else `socket.gethostname()`, as
  `job-all.in.sh`). The export names files `<host>-<local>`, where the local part is the local
  rank or, when there is none (PBS), the global rank, as bmtool's `ALPS_APP_PE`. Rank results
  without `host` keep `node<index>` for a numeric `node_rank` and use any other `node_rank` as is.
  The run-root evidence of the 2026-10-10 run has no `host`, so re-exporting it still gives
  `node0` … `node7`.
- **L34** Arms of a multi-arm run (paired, versioned, backends) take the scheduled resources of
  the whole-request plan, the one the shared job is rendered from, so `manifest.json` `points`
  match the job script.
