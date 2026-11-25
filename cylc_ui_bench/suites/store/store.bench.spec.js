// Benchmarks for the workflows store mutations against a synthetic workflow.
// Runs in the ref's default test environment, as its test setup may need it.
import { createStore } from 'vuex'
import { defineBench, gc, tryImport, workflowParams } from '../_common/harness.js'
import { makeWorkflow } from '../_common/workflow.js'

defineBench('store', async () => {
  const params = workflowParams()
  const wf = makeWorkflow(params)
  const { workflows } = await tryImport(() => import('@/store/workflows.module')) ?? {}
  if (!workflows) {
    return { params, counts: wf.counts, scenarios: { all: { skip: 'no @/store/workflows.module' } } }
  }

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
    'initial load': {
      fn: () => store.commit('workflows/UPDATE_DELTAS', delta),
      beforeEach () { store = newStore(); delta = wf.added() },
    },
    'spawn cycle': {
      fn: () => store.commit('workflows/UPDATE_DELTAS', delta),
      beforeAll () { store = populated() },
      beforeEach () {
        store.commit('workflows/REMOVE_DELTAS', wf.pruned(last))
        delta = wf.added([last])
      },
    },
    'update all': {
      fn: () => store.commit('workflows/UPDATE_DELTAS', delta),
      beforeAll () { store = populated() },
      // alternate states so every assignment is a real change
      beforeEach () { flip = !flip; delta = wf.updated(undefined, flip ? 'running' : 'succeeded') },
    },
    'prune cycle': {
      fn: () => store.commit('workflows/REMOVE_DELTAS', delta),
      beforeAll () { store = populated() },
      beforeEach () {
        store.commit('workflows/UPDATE_DELTAS', wf.added([first]))
        delta = wf.pruned(first)
      },
    },
    'remove children': {
      fn: () => store.commit('workflows/REMOVE_CHILDREN', wf.workflowID),
      beforeEach () { store = populated() },
    },
    'memory: loaded store': globalThis.gc
      ? {
          unit: 'bytes',
          // heap retained by a populated store
          measure () {
            store = delta = null
            gc()
            const before = process.memoryUsage().heapUsed
            const s = populated()
            gc()
            const after = process.memoryUsage().heapUsed
            s.state.toString() // keep s alive until measured
            return after - before
          },
        }
      : { skip: 'needs node --expose-gc' },
  }
  return { params, counts: wf.counts, scenarios }
})
