// @vitest-environment node
// Benchmarks for the workflows store mutations, run inside a cylc-ui checkout.
// Copied (with deltas.js) into tests/unit/_bench/ by run.sh; configured via env vars.
import { appendFileSync } from 'node:fs'
import { Bench } from 'tinybench'
import { createStore } from 'vuex'
import { reactive, version as vueVersion } from 'vue'
import { workflows } from '@/store/workflows.module'
import { makeWorkflow } from './deltas.js'

const env = (name, dflt) => Number(process.env[name] ?? dflt)

const SCALE = {
  cycles: env('BENCH_CYCLES', 10),
  tasksPerCycle: env('BENCH_TASKS', 500),
  jobsPerTask: env('BENCH_JOBS', 2),
  familyDepth: env('BENCH_FAMILY_DEPTH', 2),
  familyBreadth: env('BENCH_FAMILY_BREADTH', 5),
}
const ITERATIONS = env('BENCH_ITERATIONS', 20)
const ONLY = process.env.BENCH_ONLY ? new RegExp(process.env.BENCH_ONLY) : null

function vueBuild () {
  // the dev build warns about non-object values, the prod build doesn't
  const warn = console.warn
  let warned = false
  console.warn = () => { warned = true }
  reactive(1)
  console.warn = warn
  return warned ? 'dev' : 'prod'
}

it('store benchmarks', async () => {
  const wf = makeWorkflow(SCALE)
  const first = wf.cyclePoints[0]
  const last = wf.cyclePoints.at(-1)
  const newStore = () => createStore({ modules: { workflows } })
  const populated = () => {
    const s = newStore()
    s.commit('workflows/UPDATE_DELTAS', wf.added())
    return s
  }

  // fresh deltas every iteration, as the store keeps and mutates them
  let store, delta
  let flip = false
  const scenarios = {
    'initial load': [
      () => store.commit('workflows/UPDATE_DELTAS', delta),
      { beforeEach () { store = newStore(); delta = wf.added() } },
    ],
    'spawn cycle': [
      () => store.commit('workflows/UPDATE_DELTAS', delta),
      {
        beforeAll () { store = populated() },
        beforeEach () {
          store.commit('workflows/REMOVE_DELTAS', wf.pruned(last))
          delta = wf.added([last])
        },
      },
    ],
    'update all': [
      () => store.commit('workflows/UPDATE_DELTAS', delta),
      {
        beforeAll () { store = populated() },
        // alternate states so every assignment is a real change
        beforeEach () { flip = !flip; delta = wf.updated(undefined, flip ? 'running' : 'succeeded') },
      },
    ],
    'prune cycle': [
      () => store.commit('workflows/REMOVE_DELTAS', delta),
      {
        beforeAll () { store = populated() },
        beforeEach () {
          store.commit('workflows/UPDATE_DELTAS', wf.added([first]))
          delta = wf.pruned(first)
        },
      },
    ],
    'remove children': [
      () => store.commit('workflows/REMOVE_CHILDREN', wf.workflowID),
      { beforeEach () { store = populated() } },
    ],
  }

  const bench = new Bench({
    time: 0,
    iterations: ITERATIONS,
    warmupTime: 0,
    warmupIterations: Math.min(3, ITERATIONS),
    throws: true,
  })
  for (const [name, [fn, hooks]] of Object.entries(scenarios)) {
    if (ONLY && !ONLY.test(name)) continue
    bench.add(name, fn, {
      ...hooks,
      // collect setup garbage now rather than during the timed run
      beforeEach () { hooks.beforeEach?.(); globalThis.gc?.() },
    })
  }
  await bench.run()

  const results = bench.tasks.map(({ name, result }) => ({
    name,
    state: result.state,
    ...(result.latency && {
      samples: result.latency.samplesCount,
      mean: result.latency.mean,
      p50: result.latency.p50,
      p75: result.latency.p75,
      p99: result.latency.p99,
      min: result.latency.min,
      max: result.latency.max,
      rme: result.latency.rme,
    }),
  }))
  console.table(Object.fromEntries(results.map(({ name, samples, mean, p50, min, max, rme }) => [
    name,
    { samples, 'mean (ms)': +mean.toFixed(2), 'p50 (ms)': +p50.toFixed(2), 'min (ms)': +min.toFixed(2), 'max (ms)': +max.toFixed(2), 'rme (%)': +rme.toFixed(1) },
  ])))

  if (process.env.BENCH_OUT) {
    const meta = {
      label: process.env.BENCH_LABEL ?? null,
      round: process.env.BENCH_ROUND ? Number(process.env.BENCH_ROUND) : null,
      date: new Date().toISOString(),
      node: process.version,
      vue: vueVersion,
      vueBuild: vueBuild(),
      gc: typeof globalThis.gc === 'function',
      iterations: ITERATIONS,
      scale: SCALE,
      counts: wf.counts,
    }
    appendFileSync(process.env.BENCH_OUT, JSON.stringify({ meta, results }) + '\n')
  }
  expect(results.every((r) => r.state === 'completed')).toBe(true)
}, 24 * 60 * 60 * 1000)
