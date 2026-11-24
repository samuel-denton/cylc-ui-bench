# cylc-ui-bench

Benchmark parts of the [cylc-ui](https://github.com/cylc/cylc-ui) across git
refs, e.g. a PR branch against master.

Suites:

| Suite | What it measures |
|---|---|
| `store` | workflows Vuex store mutations (initial load, spawning/pruning a cycle, updating every node, removing a workflow) and the memory a loaded store retains |
| `tree` | Tree view rendering in happy-dom: mounting (every cycle, family and task), expanding tasks to show jobs, updating every node, filtering by ID; and the memory a mounted view uses and any retained after unmounting |
| `graph` | Graph view layout, using the view's own methods: generating the Graphviz dot code, and laying out (dot code, Graphviz and processing the result) top-bottom, left-right and grouped by cycle. Not rendering: nodes are given a fixed size, as happy-dom can't measure SVG |

The synthetic workflow's graph (used by `graph`) is layered within each cycle,
about sqrt(tasks) wide, with ~1.3 edges per task and an edge between
consecutive cycles.

Render suites (e.g. `tree`) mount the real views with Vuetify, the Vuex store
and the `WorkflowService`'s subscription handling (with no network), in
[happy-dom](https://github.com/capricorn86/happy-dom). Their timings cover Vue,
Vuetify and DOM work but not browser layout or paint, and their memory figures
are inflated by happy-dom's DOM, so they are for comparing refs rather than
absolute numbers.

Suites marked as scaled run against a synthetic workflow of configurable size
(`CYCLESxTASKSxJOBS`, e.g. `10x500x2`).

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

# or do it all from a web GUI
cylc-ui-bench gui -C ~/cylc-ui
```

Run `cylc-ui-bench run -h` for all options. With no refs, `master HEAD` is
compared.

## GUI

`cylc-ui-bench gui` serves a web page for starting runs and browsing results,
and opens it in your browser:

- **New run**: choose refs (with autocomplete from the cylc-ui checkout),
  suites, scales, rounds, iterations, sessions and delay, then start the run.
- **Runs**: every run in the results directory, including ones started from
  the command line, with live progress, the log, the summary and the report.
  A run in progress can be stopped.

Runs are started as separate processes, so they carry on if the GUI is closed
or stopped. Only one run can be in progress at a time, as concurrent runs
would skew each other's timings.

The server listens on 127.0.0.1 only, and every request needs the access token
in the printed URL (kept in a cookie after the first visit), so other users of
a shared machine can't use it. Use `-p PORT` for a fixed port.

## Options

The main options of `cylc-ui-bench run`:

| Option | Default | Meaning |
|---|---|---|
| `REF...` | `master HEAD` | git refs to compare, the first is the baseline |
| `-C DIR` | see below | cylc-ui checkout |
| `-s SUITE` | all | suite to run (repeatable) |
| `--scale SCALE` | suite's default | workload size (repeatable), e.g. `10x500x2` for `store` |
| `-r N` | 3 | rounds per session, per scale |
| `-i N` | per suite (`run -h`) | timed iterations per scenario, per round |
| `-n N` | 1 | sessions |
| `-d MINUTES` | 30 | wait between sessions |
| `--only REGEX` | | only run scenarios matching REGEX |

Environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `CYLC_UI` | the current directory or `../cylc-ui` next to this tool, if either is cylc-ui | cylc-ui checkout (`-C` takes precedence) |
| `BENCH_RESULTS` | `results/` in this tool | where run directories are created (`-o` takes precedence) |
| `BENCH_TMP` | `~/.cache/cylc-ui-bench` | where temporary worktrees are created |
| `BENCH_FAMILY_DEPTH` | 2 | synthetic workflow: levels of families below root |
| `BENCH_FAMILY_BREADTH` | 5 | synthetic workflow: child families per family |

## How it works

1. Each ref is resolved to a commit and checked out into a temporary git
   worktree (detached, so your checkout is untouched), with `node_modules`
   symlinked from the main checkout. These are reused for the whole run.
   Note that every ref runs with the main checkout's dependencies; a warning
   is logged if a ref's `yarn.lock` differs, and refs whose test setup needs
   other dependencies (e.g. year-old ones expecting jsdom) fail to run.
2. `suites/_common/` and each suite's files are copied into
   `tests/unit/_bench/` of each worktree. Vitest suites are run with vitest,
   using a production Vue build and `--expose-gc`; command suites run their
   own command.
3. For each session, suite, scale and round, every ref is run in turn,
   alternating the order (ABBA...) so machine noise is spread evenly. Suites
   that aren't scaled run once per round.
4. Every suite run appends one line to `results.jsonl`:
   `{"meta": {...}, "results": [...]}`, where `meta` records the suite, ref
   label, session, round, date, node/vue versions and scale, and each result
   holds a scenario's `state` (`completed`, `skipped` or `errored`), `unit`
   (`ms`, `s` or `bytes`; lower is always better) and statistics over its
   iterations (`p50`, `mean`, `min`, `max`...).
5. At the end, the results are summarised, comparing each ref to the first as
   baseline / value, so higher is better.

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

Create a subpackage of `cylc_ui_bench/suites/` (it is found automatically)
with an `__init__.py` defining a `Suite` subclass, e.g.

```python
from .. import Suite

class TreeSuite(Suite):
    name = 'tree'
    description = 'Tree view rendering'
```

Optional attributes: `scaled = False` for suites that don't use the workflow
scale, `default_iterations` (20 by default; lower for slow suites), and
`vitest_args`, e.g. `('--pool=forks',)` for suites that render (a separate
process, which also reports running out of memory clearly).

For a **vitest suite** (the default), add `*.bench.spec.js` files alongside it.
They are copied into `tests/unit/_bench/<name>/` and can import from
`../_common/`: `harness.js` (defining benchmarks), `workflow.js` (synthetic
workflow deltas) and `render.js` (mounting views, and standard memory
scenarios; see `suites/tree/tree.bench.spec.js`). For example (see also
`suites/store/store.bench.spec.js`):

```js
import { defineBench, tryImport, workflowParams } from '../_common/harness.js'
import { makeWorkflow } from '../_common/workflow.js'

defineBench('tree', async () => {
  const params = workflowParams()
  const wf = makeWorkflow(params)
  // import cylc-ui code dynamically so refs without it skip, not fail
  const mod = await tryImport(() => import('@/some/module'))
  return {
    params,
    counts: wf.counts,
    scenarios: {
      'timed thing': mod ? { fn: () => mod.thing(), beforeEach () { /* untimed setup */ } }
                         : { skip: 'no @/some/module' },
      'memory thing': { unit: 'bytes', measure: () => 123 },
      // ratio: false where ratios between refs would be noise (e.g. values ~0)
    },
  }
})
```

Mounting views in tests: don't use sinon stubs for services the views call
(e.g. `$workflowService`). Sinon keeps every stub and its calls in a global
sandbox, so each mounted view stays in memory and large benchmarks run out of
it. `render.js` provides suitable fakes.

For a **command suite**, override `command()` to return the command to run in
the worktree and `collect(worktree, output, elapsed)` to return its results,
as a list of `{"name", "unit", "state", "p50", ...}` dicts.

## Layout

```
bin/cylc-ui-bench   run without installing
cylc_ui_bench/
  cli.py            command line interface
  runner.py         worktrees, sessions and rounds
  summarise.py      summary tables
  report.py         writes summaries and report.html
  viewer.html       the HTML report viewer
  server.py         the GUI's web server and API
  gui/              the GUI (Vue 3, no build step; Vue is vendored in gui/vendor/, MIT licence)
  suites/           benchmark suites copied into cylc-ui worktrees
    _common/        harness.js, workflow.js and render.js, shared by the suites
results/            output (not tracked)
```
