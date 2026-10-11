# bmtool is deprecated

`bmtool` is frozen. Use `tools/lsmiotool/lsmiotool` (or `<prefix>/bin/lsmiotool` when installed)
for all benchmark runs, parsing, archiving and comparisons. New benchmarks and features are added
to lsmiotool only.

## Policy

- **Frozen**: no new features or benchmarks. Only fixes for problems that stop it from working as
  the parity reference.
- **Still runnable**: every command prints a deprecation warning to stderr (except `help`), then
  behaves as before.
- **Why it stays**: lsmiotool's parity tests (`tools/lsmiotool/test/parse/BmtoolParityTest.py`
  and the `Bmtool*Test.py` files) run bmtool's own scripts and require lsmiotool's reports to be
  byte-identical. bmtool is the reference until those tests carry recorded expected outputs.
- **Removal**: after lsmiotool has been validated on every site it replaces bmtool on (Viking is
  done; ARCHER2/PBS still needs a real run) and the parity tests no longer need the live scripts.

## Command mapping

| bmtool | lsmiotool |
|:---|:---|
| `bmtool run <ior\|lsmio\|lmp> <scale> [<variants>] [options]` | `lsmiotool run <ior\|lsmio\|lmp> <scale> [<variants>] [options]` |
| `bmtool run lsmio variants <variants> --versioned` | `lsmiotool run lsmio variants <variants> --versioned` |
| `bmtool run lsmio backends <scale> [<backends>]` | `lsmiotool run lsmio backends <scale> [<backends>]` |
| `--dest=<path>` | `--out-dir <path>` (aliases `--output-dir`, `--dest`; no `=` form) |
| `--time=<hours>` | `--time <hours>` (aliases `--walltime`, `--wallhour`; no `=` form) |
| `bmtool parse lsmio backends <scale>` | not needed after `run`: reports are written on archive. To rebuild them: `lsmiotool parse lsmio backends <scale>` |
| `bmtool parse <ior\|lsmio\|lmp> <scale>` | `lsmiotool parse <ior\|lsmio\|lmp>` (latest run), or `lsmiotool parseLegacy ...` for bmtool output layouts |
| `bmtool archive lsmio <scale> [<variant>]` | `lsmiotool archive lsmio <scale> [<variant>]` |
| `bmtool dirs` | not needed: each run creates and stripes its own data directories in its run root |
| `bmtool load-modules` | `lsmiotool load-modules` |

One default differs: lsmiotool archives `--versioned` runs to `lsmio-archive/variants-versioned`
(bmtool: `lsmio-archive/variants`), so `compare variants` on the variant matrix does not mix them
in. Versioned pairs already in `variants/` are not seen there by `--resume`: move their
`outputs-*-version-*` directories to `variants-versioned/`, or pass `--out-dir lsmio-archive/variants`.

Archive layouts and report files (`outputs-<arm>[:run\|:base]/<nodes>/<date>/out-*.txt`,
`agg-*-report.csv`, `lsm-report.csv`) are the same, so archives from either tool can be compared
with `lsmiotool compare`.

## What moved out of `tools/bmtool`

- LAMMPS ReaxFF inputs: `tools/bmtool/lmp-reaxff/` is now `tools/lsmiotool/share/lmp-reaxff/`
  (bmtool's LMP jobs copy them from there).
- WarpX run scripts: `tools/bmtool/warpx/` is now `tools/warpx/`.
