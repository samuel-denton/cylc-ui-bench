// Helpers for suites that render cylc-ui views in happy-dom with @vue/test-utils.
//
// Timings cover Vue, Vuetify and DOM work, not browser layout or paint.
import { flushPromises, mount } from '@vue/test-utils'
import { createStore } from 'vuex'
import { createVuetify } from 'vuetify'
import { gc, tryImport } from './harness.js'

export { flushPromises }

/**
 * The real WorkflowService's subscription bookkeeping (subscribe, unsubscribe,
 * recompute, stopping subscriptions), with no network.
 *
 * Falls back to a no-op service if this ref's WorkflowService differs. Not a
 * sinon stub: those record their calls, including the component, keeping
 * every mounted view alive.
 */
function offlineWorkflowService (WorkflowService) {
  const noop = { mode: 'no-op', service: new Proxy({}, { get: () => () => {} }) }
  const proto = WorkflowService?.prototype
  if (typeof proto?.subscribe !== 'function' || typeof proto?.unsubscribe !== 'function') return noop
  const service = Object.create(proto)
  service.subscriptions = {}
  service.startSubscriptions = function () {
    for (const subscription of Object.values(this.subscriptions)) {
      subscription.observable ??= { unsubscribe () {} }
    }
  }
  return { mode: 'offline', service }
}

/**
 * Load what's needed to mount views, or return null if this ref lacks it.
 *
 * Returns { newStore, mountView, info }: newStore() creates a Vuex store,
 * mountView(View, store, props) mounts a view with the store, Vuetify and a
 * WorkflowService shared by all mounts (as in the app), and info records how.
 */
export async function loadRenderer () {
  const [storeOptions, vuetifyPlugin, WorkflowService] = await Promise.all([
    tryImport(() => import('@/store/options')),
    tryImport(() => import('@/plugins/vuetify')),
    tryImport(() => import('@/services/workflow.service')),
  ])
  if (!storeOptions || !vuetifyPlugin) return null
  const vuetify = createVuetify(vuetifyPlugin.vuetifyOptions)
  const { mode, service } = offlineWorkflowService(WorkflowService?.default)
  return {
    info: { workflowService: mode },
    newStore: () => createStore({ ...storeOptions.default, devtools: false }),
    mountView: (View, store, props = {}) => mount(View, {
      props,
      global: { plugins: [store, vuetify], mocks: { $workflowService: service } },
    }),
  }
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

/**
 * Heap used once things have settled: an unmounted view can stay reachable
 * for a short while (e.g. via pending timers), so wait before collecting.
 */
async function settledHeapUsed () {
  await flushPromises()
  await sleep(1500)
  gc()
  return process.memoryUsage().heapUsed
}

/**
 * Standard memory scenarios for a view (need node --expose-gc):
 *
 * - "memory: mounted view": heap used by one mounted view, beyond its store.
 * - "memory: retained after N mounts": heap still used after mounting and
 *   unmounting the view N times, which should be ~0 unless something leaks.
 *
 * newStore() returns a populated store; mountIt(store) mounts the view and
 * resolves to the wrapper once rendered.
 */
export function memoryScenarios ({ newStore, mountIt, cycles = 3, iterations = 3 }) {
  if (!globalThis.gc) {
    const skip = { skip: 'needs node --expose-gc' }
    return { 'memory: mounted view': skip, [`memory: retained after ${cycles} mounts`]: skip }
  }
  const cycle = async () => {
    let wrapper = await mountIt(newStore())
    wrapper.unmount()
    wrapper = null
    await flushPromises()
  }
  return {
    'memory: mounted view': {
      unit: 'bytes',
      iterations,
      async measure () {
        const store = newStore()
        const before = await settledHeapUsed()
        let wrapper = await mountIt(store)
        const mounted = await settledHeapUsed()
        wrapper.unmount()
        wrapper = null
        return mounted - before
      },
    },
    [`memory: retained after ${cycles} mounts`]: {
      unit: 'bytes',
      iterations,
      // ~0 normally, so ratios between refs would just be noise
      ratio: false,
      async measure () {
        await cycle()  // so one-off module/cache allocations aren't counted
        const before = await settledHeapUsed()
        for (let i = 0; i < cycles; i++) await cycle()
        return await settledHeapUsed() - before
      },
    },
  }
}
