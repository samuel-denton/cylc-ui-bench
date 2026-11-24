// Synthetic workflow deltas shaped like the cylc-ui Tree view subscription results,
// shared by the benchmark suites.
// Dependency-free so it can be copied into any cylc-ui checkout.

const FLAGS = Object.freeze({
  isHeld: false,
  isQueued: false,
  isRunahead: false,
  isRetry: false,
  isWallclock: false,
  isXtriggered: false,
})

const TIME = '2026-01-01T00:00:00Z'

/**
 * Describe a synthetic workflow and return generators for its deltas.
 *
 * Each cycle has the same family hierarchy: root -> `familyBreadth` families per
 * level, `familyDepth` levels deep, with tasks spread round-robin over the leaf
 * families. Every call returns fresh objects, as the store keeps and mutates them.
 */
export function makeWorkflow ({
  user = 'bench',
  workflow = 'wf',
  cycles = 10,
  tasksPerCycle = 500,
  jobsPerTask = 2,
  familyDepth = 2,
  familyBreadth = 5,
} = {}) {
  const workflowID = `~${user}/${workflow}`
  const cyclePoints = Array.from({ length: cycles }, (_, i) => String(i + 1))

  // ancestors use cylc's order: first parent ... root
  const families = [{ name: 'root', ancestors: [] }]
  let level = families.slice()
  for (let d = 0; d < familyDepth; d++) {
    const next = []
    for (const parent of level) {
      for (let b = 0; b < familyBreadth; b++) {
        next.push({
          name: parent.name === 'root' ? `FAM_${b}` : `${parent.name}_${b}`,
          ancestors: [parent.name, ...parent.ancestors],
        })
      }
    }
    families.push(...next)
    level = next
  }

  const tasks = []
  const childTasks = {}
  for (let i = 0; i < tasksPerCycle; i++) {
    const firstParent = level[i % level.length].name
    tasks.push({ name: `task_${i}`, firstParent })
    ;(childTasks[firstParent] ??= []).push(`task_${i}`)
  }

  const id = (cycle, name) => `${workflowID}//${cycle}/${name}`
  const jobID = (taskID, submitNum) => `${taskID}/${String(submitNum).padStart(2, '0')}`

  // `full` = added delta; otherwise mimic a stripNull updated delta, where
  // node-type fields (firstParent, ancestors, childTasks...) still resolve in full
  function familyProxy (cycle, fam, state, full) {
    return {
      __typename: 'FamilyProxy',
      id: id(cycle, fam.name),
      state,
      ancestors: fam.ancestors.map((name) => ({ name })),
      childTasks: (childTasks[fam.name] ?? []).map((t) => ({ id: id(cycle, t) })),
      ...(full && { ...FLAGS, graphDepth: 0 }),
    }
  }

  function taskProxy (cycle, task, state, full) {
    return {
      __typename: 'TaskProxy',
      id: id(cycle, task.name),
      state,
      firstParent: { id: id(cycle, task.firstParent) },
      task: { meanElapsedTime: 60 },
      ...(full && { ...FLAGS, runtime: { runMode: 'Live' }, flowNums: '[1]', graphDepth: 0 }),
    }
  }

  function job (taskID, submitNum, state, full) {
    return {
      __typename: 'Job',
      id: jobID(taskID, submitNum),
      state,
      taskProxy: { outputs: [] },
      ...(full && {
        submitNum,
        jobRunnerName: 'background',
        jobId: String(10000 + submitNum),
        platform: 'localhost',
        submittedTime: TIME,
        startedTime: TIME,
        finishedTime: TIME,
        estimatedFinishTime: TIME,
        messages: [],
      }),
    }
  }

  /** Initial burst: everything in the given cycles. */
  function added (cycles = cyclePoints) {
    const delta = {
      workflow: { __typename: 'Workflow', id: workflowID, reloaded: true },
      familyProxies: [],
      taskProxies: [],
      jobs: [],
    }
    for (const cycle of cycles) {
      for (const fam of families) delta.familyProxies.push(familyProxy(cycle, fam, 'waiting', true))
      for (const task of tasks) {
        delta.taskProxies.push(taskProxy(cycle, task, 'succeeded', true))
        for (let n = 1; n <= jobsPerTask; n++) {
          delta.jobs.push(job(id(cycle, task.name), n, 'succeeded', true))
        }
      }
    }
    return delta
  }

  /** State change for every task, family and latest job in the given cycles. */
  function updated (cycles = cyclePoints, state = 'running') {
    const delta = { familyProxies: [], taskProxies: [], jobs: [] }
    for (const cycle of cycles) {
      for (const fam of families) delta.familyProxies.push(familyProxy(cycle, fam, state, false))
      for (const task of tasks) {
        delta.taskProxies.push(taskProxy(cycle, task, state, false))
        if (jobsPerTask) delta.jobs.push(job(id(cycle, task.name), jobsPerTask, state, false))
      }
    }
    return delta
  }

  /** Everything in one cycle, pruned in a single batch (as cylc-flow does). */
  function pruned (cycle = cyclePoints[0]) {
    const delta = { familyProxies: [], taskProxies: [], jobs: [] }
    for (const fam of families) delta.familyProxies.push(id(cycle, fam.name))
    for (const task of tasks) {
      const taskID = id(cycle, task.name)
      delta.taskProxies.push(taskID)
      for (let n = 1; n <= jobsPerTask; n++) delta.jobs.push(jobID(taskID, n))
    }
    return delta
  }

  // Graph edges (only included in deltas on request, so as not to change the
  // workload of suites that don't use them). In each cycle the tasks form
  // layers about sqrt(tasks) wide: each task depends on one in the previous
  // layer and every third on a second, and task_0 depends on task_0 in the
  // previous cycle.
  const width = Math.max(1, Math.round(Math.sqrt(tasksPerCycle)))
  const edge = (sourceCycle, source, targetCycle, target) => ({
    __typename: 'Edge',
    id: `${workflowID}//$edge|${sourceCycle}/task_${source}|${targetCycle}/task_${target}`,
    source: id(sourceCycle, `task_${source}`),
    target: id(targetCycle, `task_${target}`),
  })

  /** Edges within, and between, the given cycles. */
  function edges (cycles = cyclePoints) {
    const ret = []
    cycles.forEach((cycle, c) => {
      if (c > 0 && tasksPerCycle) ret.push(edge(cycles[c - 1], 0, cycle, 0))
      for (let i = width; i < tasksPerCycle; i++) {
        const previousLayer = i - (i % width) - width
        ret.push(edge(cycle, previousLayer + (i % width), cycle, i))
        if (width > 1 && i % 3 === 0) ret.push(edge(cycle, previousLayer + ((i + 1) % width), cycle, i))
      }
    })
    return ret
  }

  return {
    workflowID,
    cyclePoints,
    counts: {
      cycles,
      families: families.length * cycles,
      tasks: tasksPerCycle * cycles,
      jobs: tasksPerCycle * jobsPerTask * cycles,
    },
    added,
    updated,
    pruned,
    edges,
  }
}
