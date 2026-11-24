// Graph view layout against a synthetic workflow with edges: the view's own
// dot code and layout methods, with Graphviz (WebAssembly), but no rendering.
import { defineBench, tryImport, workflowParams } from '../_common/harness.js'
import { loadRenderer } from '../_common/render.js'
import { makeWorkflow } from '../_common/workflow.js'

// happy-dom can't measure rendered SVG, so give every node a typical size
const NODE_SIZE = Object.freeze({ width: 300, height: 60 })

defineBench('graph', async () => {
  const params = workflowParams()
  const wf = makeWorkflow({ ...params, user: 'owner', workflow: 'wf' })
  const [renderer, Graph, graphviz] = await Promise.all([
    loadRenderer(),
    tryImport(() => import('@/views/Graph.vue')),
    tryImport(() => import('@hpcc-js/wasm/graphviz')),
  ])
  const methods = Graph?.default?.methods ?? {}
  const needed = ['getGraphNodes', 'getGraphEdges', 'getCycles', 'getDotCode', 'layout']
  const missing = needed.filter((name) => typeof methods[name] !== 'function')
  if (!renderer || !graphviz || missing.length) {
    const reason = missing.length ? `Graph view lacks ${missing.join(', ')}` : 'cannot load the Graph view'
    return { params, counts: wf.counts, scenarios: { all: { skip: reason } } }
  }

  // the nodes and edges as the view takes them from the store
  const store = renderer.newStore()
  const delta = wf.added()
  delta.edges = wf.edges()
  store.commit('workflows/UPDATE_DELTAS', delta)
  const workflows = store.getters['workflows/getNodes']('workflow', [wf.workflowID])
  const nodes = methods.getGraphNodes.call({ workflows })
  const edges = methods.getGraphEdges.call({ workflows })
  const nodeDimensions = Object.fromEntries(nodes.map((node) => [node.id, NODE_SIZE]))
  const loaded = graphviz.Graphviz.load()
  await loaded

  // a stand-in for the view's `this`, with its default options
  const view = (options) => ({
    ...methods,
    spacing: 1.5,
    transpose: false,
    groupCycle: false,
    ...options,
    graphviz: loaded,
    nodeTransformations: {},
    subgraphs: {},
    graphEdges: [],
    panZoomWidget: {}, // so layout() doesn't try to set up pan/zoom
  })
  const layout = (options) => ({
    async fn () {
      const v = view(options)
      await v.layout(nodes, edges, nodeDimensions, v.getCycles(nodes))
    },
  })

  const scenarios = {
    'dot code': {
      fn () {
        const v = view()
        v.getDotCode(nodeDimensions, nodes, edges, v.getCycles(nodes))
      },
    },
    layout: layout(),
    'layout (transposed)': layout({ transpose: true }),
    'layout (grouped by cycle)': layout({ groupCycle: true }),
  }

  // check the layout really places everything, for the run log
  const v = view()
  await v.layout(nodes, edges, nodeDimensions, v.getCycles(nodes))
  console.log(
    `${nodes.length} nodes, ${edges.length} edges; laid out`,
    `${Object.keys(v.nodeTransformations).length} nodes, ${v.graphEdges.length} edges`,
  )

  return {
    params,
    counts: { ...wf.counts, edges: edges.length },
    info: { nodeSize: NODE_SIZE },
    scenarios,
  }
})
