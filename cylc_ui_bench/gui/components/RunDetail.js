import { computed, onUnmounted, ref, watch } from 'vue'
import { ACTIVE, fmtDate, get, post } from '../api.js'

export default {
  name: 'RunDetail',
  props: {
    runId: { type: String, required: true },
  },
  emits: ['changed'],
  setup (props, { emit }) {
    const run = ref(null)
    const error = ref(null)
    const stopping = ref(false)
    let timer = null

    const active = computed(() => ACTIVE.includes(run.value?.state))
    // reload the report whenever another suite run finishes
    const reportURL = computed(() => `/api/runs/${encodeURIComponent(props.runId)}/report?v=${run.value?.done ?? 0}`)

    async function load () {
      try {
        run.value = await get(`/api/runs/${encodeURIComponent(props.runId)}`)
        error.value = null
      } catch (err) {
        error.value = err.message
      }
      clearTimeout(timer)
      if (!run.value || active.value) timer = setTimeout(load, 3000)
    }

    async function stop () {
      if (!confirm(`Stop run ${props.runId}?`)) return
      stopping.value = true
      try {
        await post(`/api/runs/${encodeURIComponent(props.runId)}/stop`)
        await load()
      } catch (err) {
        error.value = err.message
      } finally {
        stopping.value = false
      }
    }

    watch(() => run.value?.state, (state, old) => { if (old && state !== old) emit('changed') })
    load()
    onUnmounted(() => clearTimeout(timer))

    return { run, error, stopping, active, reportURL, stop, fmtDate }
  },
  template: `
    <div>
      <p v-if="error" class="error">{{ error }}</p>
      <template v-if="run">
        <h2>{{ run.id }} <span :class="['state', run.state]">{{ run.state }}</span></h2>
        <dl class="props">
          <dt>Refs</dt><dd>{{ run.refs.join(', ') }}</dd>
          <dt>Suites</dt><dd>{{ run.suites.join(', ') }}</dd>
          <template v-if="!run.legacy">
            <dt>Scales</dt><dd>{{ Object.entries(run.scales).map(([s, x]) => s + ': ' + x.join(' ')).join('; ') }}</dd>
            <dt>Settings</dt>
            <dd>{{ run.rounds }} rounds × {{ run.sessions }} sessions<span v-if="run.sessions > 1">, {{ run.delay }} min apart</span>, {{ run.iterations ?? 'default' }} iterations<span v-if="run.only">, only /{{ run.only }}/</span></dd>
          </template>
          <dt>Started</dt><dd>{{ fmtDate(run.started) }}</dd>
          <dt v-if="run.finished">Finished</dt><dd v-if="run.finished">{{ fmtDate(run.finished) }}</dd>
          <dt>Directory</dt><dd><code>{{ run.path }}</code></dd>
        </dl>

        <p v-if="active">
          <progress :max="run.total || 1" :value="run.done"></progress>
          {{ run.done }}/{{ run.total ?? '?' }}<span v-if="run.current"> · {{ run.current }}</span>
          <button class="danger" :disabled="stopping" @click="stop" style="margin-left: 1em">Stop</button>
        </p>
        <p v-if="run.failed" class="error">{{ run.failed }} suite run(s) failed, see the log below.</p>
        <p v-if="run.state === 'died'" class="error">The run's process is no longer running, but it didn't record finishing.</p>
        <div v-if="run.stderr"><h3>Errors</h3><pre class="log">{{ run.stderr }}</pre></div>

        <h3>Report</h3>
        <iframe v-if="run.done" class="report" :src="reportURL"></iframe>
        <p v-else class="muted">No results yet.</p>

        <details v-if="run.summary">
          <summary>Summary (text)</summary>
          <pre>{{ run.summary }}</pre>
        </details>
        <details :open="active">
          <summary>Log (last 200 lines)</summary>
          <pre class="log">{{ run.log || '(empty)' }}</pre>
        </details>
      </template>
      <p v-else-if="!error" class="muted">Loading…</p>
    </div>
  `,
}
