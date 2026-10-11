# lsmiotool open issues

Paths are relative to `tools/`; line numbers are may have drifted.

Status: `[ ]` open.

---

## High — wrong or missing results, hangs, site breakage
- 


## Medium
-


## Low

- [ ] **L1.** `--opt=value` forms rejected (`cli.py:571-588`); bmtool documents `--dest=`, `--time=`.
- [ ] **L2.** Backend list not validated (unknown, duplicate, `adios`+`adios2`, empty) (`cli.py:371-379`
  vs `bmtool:245-266`).
- [ ] **L3.** `NATIVE` (non-MPI) and `ENV` setups rejected (`benchmarks.py:982-993`,
  `run.py:1435-1446`).
- [ ] **L4.** Default variant omits `--lsmio-no-autotune` (`variants.py:647-661`); no effect today
  (binary default is false).
- [ ] **L5.** `.db` naming `lsmio-rank-N-native-m…` vs bmtool `lsmio-<node>-<local>-native…`.
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
- [ ] **L35.** A `backends` rerun to the same destination replaces earlier results silently.
  `lib/export.py` removes and renames each `outputs-<backend>/<nodes>` it archives, while variant
  pairs get `-N` suffixes. Matches bmtool (`rm -rf` + `cp`), but an earlier campaign at that
  `<nodes>` is lost without notice; documented in tools/README.md (use `--out-dir` per campaign).
- [ ] **L36.** `--resume` never skips a `variants` run of the baseline alone or a `--versioned` run
  without variants (`lib/run.py` resume set: only paired arms with a variant and backend points).
  Matches bmtool, where those archive to a new `-N` suffix; documented in tools/README.md and the
  run help. A rerun after an interruption therefore repeats the whole job.
- [ ] **L37.** Versioned pairs archived to `lsmio-archive/variants` (by bmtool, or by lsmiotool before
  `--versioned` defaulted to `variants-versioned`) are invisible to `--resume` of a new versioned
  run, which reruns them into `variants-versioned/`, and they stay in `variants/` charts.
  Documented (move the `outputs-*-version-*` dirs, or `--out-dir lsmio-archive/variants`); a
  one-off migration helper or a resume check of both folders would remove the trap.
- [ ] **L38.** `tools/bmtool/DEPRECATED.md` maps bmtool's `--dest=<path>` to `--out-dir` for every
  command, but `lsmiotool archive` accepts only `--dest <path>` (`--out-dir` is "Unknown option").
  Split the row into `run` and `archive`.
- [ ] **L39.** `tools/bmtool/DEPRECATED.md` says the `Bmtool*Test.py` files require byte-identical
  reports; only `test/parse/BmtoolParityTest.py` does. The other three test bmtool's own behaviour
  (backend list check, ARCHER2 relocation, run_tee).
- [ ] **L40.** tools/README.md's ARCHER2 paragraph (Slurm directives section) describes only bmtool's
  relocation (rsync of all of `tools/`, `--chdir`). lsmiotool's own (`lib/relocate.py`: mirror
  `tools/lsmiotool`, assets included, and run the relocated worker) is not described.
- [ ] **L41.** The first `run` line of `lsmiotool --help` (`lib/cli.py` LSMIOTOOL_HELP / RUN_HELP_TEXT)
  omits `--time`, which `variants` runs accept (plain scaling runs reject it).
- [ ] **L42.** Stale asset paths: `lib/worker.py` falls back to `<install_prefix>/share/lmp-reaxff`
  (the installed layout is `share/lsmio/lmp-reaxff`; reached only if `ResourceLocator.forSource`
  raises), and `lib/jobs.py` `batch_job_orchestration` copies `<bm_path>/lmp-reaxff` (dead code,
  only called from `test/main/test_jobs.py`).
- [ ] **L43.** On ARCHER2 a source-mode relocation (lsmiotool, or bmtool's rsync of `tools/`) runs
  `rsync --delete` over `<work>/tools/lsmiotool`, which removes an installed-mode mirror kept under
  it; a queued installed-mode job could lose its worker. Predates the bmtool deprecation.
- [ ] **L45.** A pair half-written by `_archiveGroup` (the `:base` export fails, or the process is
  killed between export and `_mark`) leaves a `:run` without a run marker: the next
  `archive --source` archives a duplicate `:run-1`/`:base-1` pair, and `run --resume` treats the
  variant as done. Write the markers as soon as the pair dirs exist, or export into temporary
  dirs and rename at the end.
- [ ] **L46.** With `--foreground`, a hangup also reaches `sbatch`/`squeue` children (bash forwards
  SIGHUP to its jobs): a killed `squeue` costs one UNKNOWN poll, a killed `sbatch` after the
  controller accepted the job can leave an orphan job. Detached runs are not affected. Fix:
  start scheduler commands with `start_new_session=True`.
- [ ] **L49.** `recoverRun` never installs the signal coordinator (no SIGINT/SIGTERM handling there);
  only relevant if it is reached from the CLI.
- [ ] **L50.** `orchestratorRunning` compares the process start (btime-based on Linux, `ps lstart`
  elsewhere) with the pid file's wall-clock `started_at_utc` within 5 s: a forward wall-clock
  step of more than 5 s after the pid file is written makes a live run look dead (`cancel` and
  the archive guard then miss it). Record the process's own start ticks instead of wall time.
