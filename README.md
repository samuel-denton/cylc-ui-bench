# cylc-ui-bench

Benchmark parts of the [cylc-ui](https://github.com/cylc/cylc-ui) across git
refs, e.g. a PR branch against master.

Currently one suite is available, `store`, which times the workflows Vuex store
mutations (initial load, spawning/pruning a cycle, updating every node and
removing a workflow) against a synthetic workflow of configurable size.

## Requirements

- git and python >= 3.9 (standard library only)
- node/npx on `PATH`
- a cylc-ui checkout with dependencies installed (`yarn install`)

The `cylc-dev` conda environment used for cylc-ui development has all of these.

## Installation

Either run `bin/cylc-ui-bench` from this checkout, or install it to put
`cylc-ui-bench` on your `PATH`:

```bash
pip install -e .
```

## Quick start

```bash
# compare a branch with upstream master (the first ref is the baseline)
cylc-ui-bench run -C ~/cylc-ui upstream/master my-branch

# overnight: 4 sessions 30 minutes apart, at two workflow scales
nohup cylc-ui-bench run -C ~/cylc-ui -n 4 -d 30 --scale 10x500x2 --scale 2x2500x2 \
  upstream/master my-branch > overnight.out 2>&1 &

# re-summarise a run, or compare several
cylc-ui-bench report results/20261124-141500
```

Run `cylc-ui-bench run -h` for all options. With no refs, `master HEAD` is
compared.

## Options

The main options of `cylc-ui-bench run`:

| Option | Default | Meaning |
|---|---|---|
| `REF...` | `master HEAD` | git refs to compare, the first is the baseline |
| `-C DIR` | see below | cylc-ui checkout |
| `-s SUITE` | all | suite to run (repeatable) |
| `--scale SCALE` | suite's default | workload size (repeatable), e.g. `10x500x2` for `store` |
| `-r N` | 3 | rounds per session, per scale |
| `-i N` | 20 | timed iterations per scenario, per round |
| `-n N` | 1 | sessions |
| `-d MINUTES` | 30 | wait between sessions |
| `--only REGEX` | | only run scenarios matching REGEX |

Environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `CYLC_UI` | the current directory or `../cylc-ui` next to this tool, if either is cylc-ui | cylc-ui checkout (`-C` takes precedence) |
| `BENCH_RESULTS` | `results/` in this tool | where run directories are created (`-o` takes precedence) |
| `BENCH_TMP` | `~/.cache/cylc-ui-bench` | where temporary worktrees are created |
| `BENCH_FAMILY_DEPTH` | 2 | `store`: levels of families below root |
| `BENCH_FAMILY_BREADTH` | 5 | `store`: child families per family |

## How it works

1. Each ref is resolved to a commit and checked out into a temporary git
   worktree (detached, so your checkout is untouched), with `node_modules`
   symlinked from the main checkout. These are reused for the whole run.
2. Each suite's spec files are copied into `tests/unit/_bench/<suite>/` of each
   worktree and run with vitest, using a production Vue build and `--expose-gc`.
3. For each session, suite, scale and round, every ref is run in turn,
   alternating the order (ABBA...) so machine noise is spread evenly.
4. Every suite run appends one line to `results.jsonl`:
   `{"meta": {...}, "results": [...]}`, where `meta` records the suite, ref
   label, session, round, date, node/vue versions and scale, and each result
   holds a scenario's latency statistics in ms.
5. At the end, the results are summarised, comparing each ref to the first.

## Results

Each run creates a timestamped directory:

```
results/20261124-141500/
  config.json     settings and resolved refs
  status.json     state (running/done/failed/interrupted/error) and progress
  results.jsonl   one line per suite run
  run.log         output of every suite run
  summary.txt     summary tables
  summary.md      the same, in markdown
  report.html     self-contained report with charts
```

`report.html` can be opened directly or shared. Alternatively, open
`cylc_ui_bench/viewer.html` in a browser and drop `.jsonl` files on it.

## Adding a suite

Create a subpackage of `cylc_ui_bench/suites/` containing its vitest spec files
and a `Suite` subclass (see `suites/store/__init__.py`), and register it in
`SUITES` in `suites/__init__.py`. The spec should append a line to `$BENCH_OUT`
in the format above.

## Layout

```
bin/cylc-ui-bench   run without installing
cylc_ui_bench/
  cli.py            command line interface
  runner.py         worktrees, sessions and rounds
  summarise.py      summary tables
  report.py         writes summaries and report.html
  viewer.html       the HTML report viewer
  suites/           benchmark suites copied into cylc-ui worktrees
results/            output (not tracked)
```
