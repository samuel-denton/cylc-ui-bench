// Shared harness for benchmark suites run with vitest inside a cylc-ui worktree.
//
// A suite's spec calls defineBench() with a setup function returning its
// scenarios. Each scenario is one of:
//   { fn, beforeAll?, beforeEach?, afterEach?, afterAll? }  timed with tinybench (ms)
//   { measure: async () => number, unit, iterations? }      a measured value, e.g. bytes,
//                                                           repeated at most `iterations` times
//   { skip: 'reason' }                                      not applicable to this ref
// Add `ratio: false` to a scenario whose values aren't meaningful as ratios
// between refs (e.g. ones that are normally ~0).
// Setup should import cylc-ui code dynamically (see tryImport), so a ref that
// lacks it skips the affected scenarios rather than failing the whole suite.
//
// Configured by the runner via env vars; results are appended to $BENCH_OUT as
// one JSON line: {"meta": {...}, "results": [...]}.
import { appendFileSync } from 'node:fs'
import { Bench } from 'tinybench'
import { reactive, version as vueVersion } from 'vue'

export const envNumber = (name, dflt) => Number(process.env[name] ?? dflt)

export const ITERATIONS = envNumber('BENCH_ITERATIONS', 20)
const ONLY = process.env.BENCH_ONLY ? new RegExp(process.env.BENCH_ONLY) : null

/** Synthetic workflow size, from the run's scale (see workflow.js). */
export function workflowParams () {
  return {
    cycles: envNumber('BENCH_CYCLES', 10),
    tasksPerCycle: envNumber('BENCH_TASKS', 500),
    jobsPerTask: envNumber('BENCH_JOBS', 2),
    familyDepth: envNumber('BENCH_FAMILY_DEPTH', 2),
    familyBreadth: envNumber('BENCH_FAMILY_BREADTH', 5),
  }
}

/** Import a module, or return null if it doesn't exist in this ref. */
export async function tryImport (load) {
  try {
    return await load()
  } catch {
    return null
  }
}

/** Collect garbage now (if node has --expose-gc) so it doesn't land in a timed run. */
export function gc () {
  globalThis.gc?.()
}

function vueBuild () {
  // the dev build warns about non-object values, the prod build doesn't
  const warn = console.warn
  let warned = false
  console.warn = () => { warned = true }
  reactive(1)
  console.warn = warn
  return warned ? 'dev' : 'prod'
}

function stats (values) {
  const sorted = [...values].sort((a, b) => a - b)
  const n = sorted.length
  const at = (q) => sorted[Math.min(n - 1, Math.ceil(q * n) - 1)]
  const mean = sorted.reduce((a, b) => a + b, 0) / n
  const sd = n > 1 ? Math.sqrt(sorted.reduce((a, b) => a + (b - mean) ** 2, 0) / (n - 1)) : 0
  const p50 = n % 2 ? sorted[n >> 1] : (sorted[n / 2 - 1] + sorted[n / 2]) / 2
  return {
    samples: n,
    mean,
    p50,
    p75: at(0.75),
    p99: at(0.99),
    min: sorted[0],
    max: sorted[n - 1],
    rme: mean ? (1.96 * sd / Math.sqrt(n) / Math.abs(mean)) * 100 : 0,
  }
}

async function timed (name, scenario) {
  const bench = new Bench({
    time: 0,
    iterations: ITERATIONS,
    warmupTime: 0,
    warmupIterations: Math.min(3, ITERATIONS),
    throws: false,
  })
  bench.add(name, scenario.fn, {
    beforeAll: scenario.beforeAll,
    afterAll: scenario.afterAll,
    afterEach: scenario.afterEach,
    // collect setup garbage now rather than during the timed run
    async beforeEach () { await scenario.beforeEach?.(); gc() },
  })
  await bench.run()
  const { result } = bench.tasks[0]
  if (result.state !== 'completed') {
    return { state: result.state, error: String(result.error?.stack ?? result.error ?? '') }
  }
  const l = result.latency
  return {
    state: 'completed',
    samples: l.samplesCount,
    mean: l.mean,
    p50: l.p50,
    p75: l.p75,
    p99: l.p99,
    min: l.min,
    max: l.max,
    rme: l.rme,
  }
}

async function measured (scenario) {
  try {
    const values = []
    const iterations = Math.min(scenario.iterations ?? ITERATIONS, ITERATIONS)
    for (let i = 0; i < iterations; i++) values.push(await scenario.measure())
    return { state: 'completed', ...stats(values) }
  } catch (err) {
    return { state: 'errored', error: String(err?.stack ?? err) }
  }
}

function fmt (value, unit) {
  if (value === undefined) return ''
  if (unit === 'bytes') return `${(value / 1024 / 1024).toFixed(2)} MiB`
  return `${value.toFixed(2)} ${unit}`
}

/**
 * Register a vitest test that runs a suite's scenarios and records the results.
 *
 * setup() returns { scenarios, params?, counts?, info? }: params and counts
 * describe the workload, and info anything else worth recording; all go in
 * the results' meta.
 */
export function defineBench (suite, setup) {
  it(`${suite} benchmarks`, async () => {
    const { scenarios, params = null, counts = null, info = null } = await setup()
    const results = []
    for (const [name, scenario] of Object.entries(scenarios)) {
      if (ONLY && !ONLY.test(name)) continue
      const unit = scenario.measure ? scenario.unit : 'ms'
      let result
      if (scenario.skip) {
        result = { state: 'skipped', reason: scenario.skip }
      } else if (scenario.measure) {
        result = await measured(scenario)
      } else {
        result = await timed(name, scenario)
      }
      results.push({ name, unit, ...(scenario.ratio === false && { ratio: false }), ...result })
    }

    console.table(Object.fromEntries(results.map((r) => [r.name, {
      state: r.state,
      samples: r.samples,
      mean: fmt(r.mean, r.unit),
      p50: fmt(r.p50, r.unit),
      min: fmt(r.min, r.unit),
      max: fmt(r.max, r.unit),
      'rme (%)': r.rme === undefined ? '' : +r.rme.toFixed(1),
    }])))
    for (const r of results) {
      if (r.error) console.error(`${r.name}: ${r.error}`)
      if (r.reason) console.log(`${r.name}: skipped (${r.reason})`)
    }

    if (process.env.BENCH_OUT) {
      const meta = {
        suite,
        label: process.env.BENCH_LABEL ?? null,
        session: process.env.BENCH_SESSION ? Number(process.env.BENCH_SESSION) : null,
        round: process.env.BENCH_ROUND ? Number(process.env.BENCH_ROUND) : null,
        date: new Date().toISOString(),
        node: process.version,
        vue: vueVersion,
        vueBuild: vueBuild(),
        gc: typeof globalThis.gc === 'function',
        iterations: ITERATIONS,
        scaleName: process.env.BENCH_SCALE ?? null,
        scale: params,
        counts,
        info,
      }
      appendFileSync(process.env.BENCH_OUT, JSON.stringify({ meta, results }) + '\n')
    }
    expect(results.filter((r) => !['completed', 'skipped'].includes(r.state))).toEqual([])
  }, 24 * 60 * 60 * 1000)
}
