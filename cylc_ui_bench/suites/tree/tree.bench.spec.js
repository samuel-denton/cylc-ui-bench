// Tree view rendering against a synthetic workflow, in happy-dom.
import { mockRoute } from '$tests/util'
import { defineBench, tryImport, workflowParams } from '../_common/harness.js'
import { flushPromises, loadRenderer, memoryScenarios } from '../_common/render.js'
import { makeWorkflow } from '../_common/workflow.js'

// views show ~<owner>/<workflowName>, owner being "owner" in tests/unit/setup.js
mockRoute({ params: { workflowName: 'wf' } })

defineBench('tree', async () => {
  const params = workflowParams()
  const wf = makeWorkflow({ ...params, user: 'owner', workflow: 'wf' })
  const [renderer, Tree] = await Promise.all([
    loadRenderer(),
    tryImport(() => import('@/views/Tree.vue')),
  ])
  if (!renderer || !Tree) {
    return { params, counts: wf.counts, scenarios: { all: { skip: 'cannot load the Tree view' } } }
  }
  const { newStore, mountView, info } = renderer

  const populated = () => {
    const store = newStore()
    store.commit('workflows/UPDATE_DELTAS', wf.added())
    return store
  }
  const mountTree = async (store) => {
    const wrapper = mountView(Tree.default, store)
    await flushPromises()
    return wrapper
  }

  let store, wrapper, delta
  let flip = false
  const unmount = () => { wrapper?.unmount(); wrapper = null }
  const mounted = async () => {
    unmount()
    store = populated()
    wrapper = await mountTree(store)
  }
  // cycles and families are expanded by default, so this adds tasks, showing their jobs
  const expandJobs = async () => {
    wrapper.vm.expandAll = ['workflow', 'cycle', 'family', 'task']
    await flushPromises()
  }

  const scenarios = {
    // renders every cycle, family and task
    mount: {
      async fn () { wrapper = await mountTree(store) },
      beforeEach () { unmount(); store = populated() },
      afterEach: unmount,
    },
    'expand jobs': {
      fn: expandJobs,
      beforeEach: mounted,
      afterEach: unmount,
    },
    'update all (expanded)': {
      async fn () {
        store.commit('workflows/UPDATE_DELTAS', delta)
        await flushPromises()
      },
      async beforeAll () {
        await mounted()
        await expandJobs()
      },
      // alternate states so every assignment is a real change
      beforeEach () { flip = !flip; delta = wf.updated(undefined, flip ? 'running' : 'succeeded') },
      afterAll: unmount,
    },
    // matches 1 in 10 tasks (task_1, task_10-19, task_100-199...)
    'filter by id': {
      async fn () {
        wrapper.vm.tasksFilter = { id: 'task_1*', states: null }
        await flushPromises()
      },
      beforeEach: mounted,
      afterEach: unmount,
    },
    ...memoryScenarios({ newStore: populated, mountIt: mountTree }),
  }

  // check the tree really renders, for the run log
  await mounted()
  const size = () => `${wrapper.findAll('.c-treeitem').length} tree items, ${wrapper.element.querySelectorAll('*').length} elements`
  console.log(`rendered on mount: ${size()}`)
  await expandJobs()
  console.log(`rendered with jobs: ${size()}`)
  unmount()

  return { params, counts: wf.counts, info, scenarios }
})
