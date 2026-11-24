# cylc-ui-bench

Benchmark parts of the [cylc-ui](https://github.com/cylc/cylc-ui) across git
refs, e.g. a PR branch against master.

Currently one suite is available, `store`, which times the workflows Vuex store
mutations (initial load, spawning/pruning a cycle, updating every node and
removing a workflow) against a synthetic workflow of configurable size.

## Requirements

- git, bash and python3 (standard library only)
- node/npx on `PATH`
- a cylc-ui checkout with dependencies installed (`yarn install`)

## Quick start

```bash
# compare two refs (the first is the baseline), 3 rounds each
bin/run.sh -C ~/cylc-ui upstream/master my-branch

# several sessions spread over time, at multiple workflow scales
nohup bin/overnight.sh -C ~/cylc-ui -n 4 -s '10x500x2 2x2500x2' upstream/master my-branch \
  > overnight.out 2>&1 &
```

Run `bin/run.sh -h` or `bin/overnight.sh -h` for all options. With no refs,
`master HEAD` is compared.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `CYLC_UI` | `../cylc-ui` next to this repo | cylc-ui checkout (or use `-C DIR`) |
| `BENCH_RESULTS` | `results/` in this repo | where results are written |
| `BENCH_TMP` | `~/.cache/cylc-ui-bench` | where temporary worktrees are created |

The `store` suite is configured with:

| Variable | Default | Meaning |
|---|---|---|
| `BENCH_CYCLES` | 10 | cycle points |
| `BENCH_TASKS` | 500 | tasks per cycle |
| `BENCH_JOBS` | 2 | jobs per task |
| `BENCH_FAMILY_DEPTH` | 2 | levels of families below root |
| `BENCH_FAMILY_BREADTH` | 5 | child families per family |
| `BENCH_ITERATIONS` | 20 | timed iterations per scenario per run |
| `BENCH_ONLY` | | regex selecting scenarios to run |

## How it works

1. Each ref is checked out into a temporary git worktree (detached, so your
   checkout is untouched), with `node_modules` symlinked from the main checkout.
2. The suite's spec files are copied into `tests/unit/_bench/` of each worktree
   and run with vitest, using a production Vue build and `--expose-gc`.
3. Rounds alternate the ref order (ABBA...) so machine noise is spread evenly.
4. Every run appends one line to a JSONL file: `{"meta": {...}, "results": [...]}`,
   where `meta` records the ref label, round, date, node/vue versions and scale,
   and each result holds a scenario's latency statistics in ms.
5. The results are summarised at the end, comparing each ref to the first.

## Viewing results

```bash
report/summarise.py [--markdown] [--stat p50|mean] results/*.jsonl
report/report.py results/*.jsonl > report.html   # self-contained HTML report
```

Alternatively, open `report/viewer.html` in a browser and drop `.jsonl` files on it.

## Layout

```
bin/        runners (run.sh, overnight.sh)
suites/     benchmark suites copied into cylc-ui worktrees
report/     summaries and the HTML viewer
legacy/     older scripts, to be turned into suites
results/    output (not tracked)
```
