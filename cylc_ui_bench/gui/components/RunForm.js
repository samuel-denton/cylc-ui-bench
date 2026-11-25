import { computed, reactive, ref, watch } from 'vue'
import { post } from '../api.js'

export default {
  name: 'RunForm',
  props: {
    options: { type: Object, default: null },
    activeRun: { type: String, default: null },
  },
  emits: ['started'],
  setup (props, { emit }) {
    const form = reactive({
      refs: [],
      suites: [],
      scales: '',
      rounds: 3,
      iterations: null,
      sessions: 1,
      delay: 30,
      only: '',
      fetch: false,
      install: 'auto',
    })
    const error = ref(null)
    const submitting = ref(false)

    // fill in defaults once the server's options arrive
    watch(() => props.options, (options) => {
      if (!options || form.refs.length) return
      const d = options.defaults
      Object.assign(form, {
        refs: [...d.refs],
        suites: options.suites.map((s) => s.name),
        rounds: d.rounds,
        iterations: d.iterations,
        sessions: d.sessions,
        delay: d.delay,
        install: d.install,
      })
    }, { immediate: true })

    const scales = computed(() => form.scales.split(/[\s,]+/).filter(Boolean))
    const refs = computed(() => form.refs.map((r) => r.trim()).filter(Boolean))

    const runCount = computed(() => {
      if (!props.options) return 0
      const perSuite = form.suites.map((name) => {
        const suite = props.options.suites.find((s) => s.name === name)
        if (!suite?.scaled) return 1
        return scales.value.length || suite.default_scales.length
      })
      const scaleRuns = perSuite.reduce((a, b) => a + b, 0)
      return form.sessions * form.rounds * refs.value.length * scaleRuns
    })

    function move (i, by) {
      const [r] = form.refs.splice(i, 1)
      form.refs.splice(i + by, 0, r)
    }

    async function submit () {
      error.value = null
      submitting.value = true
      try {
        const { id } = await post('/api/runs', {
          refs: refs.value,
          suites: form.suites,
          scales: scales.value,
          rounds: form.rounds,
          iterations: form.iterations || null,
          sessions: form.sessions,
          delay: form.delay,
          only: form.only || null,
          fetch: form.fetch,
          install: form.install,
        })
        emit('started', id)
      } catch (err) {
        error.value = err.message
      } finally {
        submitting.value = false
      }
    }

    const iterationsHelp = computed(() => 'Default per suite: ' +
      (props.options?.suites ?? []).map((s) => `${s.name} ${s.default_iterations}`).join(', '))

    return { form, error, submitting, runCount, refs, iterationsHelp, move, submit }
  },
  template: `
    <form @submit.prevent="submit">
      <h2>New run</h2>
      <p v-if="!options" class="muted">Loading…</p>
      <template v-else>
        <div class="field">
          <label class="title">Git refs</label>
          <div v-for="(r, i) in form.refs" :key="i" class="ref-row">
            <input v-model="form.refs[i]" list="git-refs" placeholder="branch, tag or commit">
            <button type="button" class="small" :disabled="i === 0" @click="move(i, -1)" title="move up">↑</button>
            <button type="button" class="small" :disabled="i === form.refs.length - 1" @click="move(i, 1)" title="move down">↓</button>
            <button type="button" class="small" :disabled="form.refs.length === 1" @click="form.refs.splice(i, 1)" title="remove">✕</button>
            <span v-if="i === 0" class="tag">baseline</span>
          </div>
          <button type="button" @click="form.refs.push('')">+ add ref</button>
          <datalist id="git-refs">
            <option v-for="r in options.refs" :key="r" :value="r"></option>
          </datalist>
          <div class="help">Each ref is compared with the first. Refs are resolved in {{ options.cylc_ui }}.</div>
        </div>

        <div class="field">
          <label class="title">Suites</label>
          <div v-for="s in options.suites" :key="s.name">
            <label><input type="checkbox" v-model="form.suites" :value="s.name"> <b>{{ s.name }}</b>: {{ s.description }}</label>
          </div>
        </div>

        <div class="field">
          <label class="title">Scales</label>
          <input v-model="form.scales" placeholder="default 10x500x2" size="40">
          <div class="help">
            Synthetic workflow sizes, {{ options.suites.find((s) => s.scaled)?.scale_help }}. Separate several with spaces.
            Applies to {{ options.suites.filter((s) => s.scaled).map((s) => s.name).join(', ') || 'no suites' }};
            other suites run once per round.
          </div>
        </div>

        <div class="field numbers">
          <label>Rounds<br><input type="number" min="1" v-model.number="form.rounds"></label>
          <label>Iterations<br><input type="number" min="1" v-model.number="form.iterations" placeholder="default" :title="iterationsHelp"></label>
          <label>Sessions<br><input type="number" min="1" v-model.number="form.sessions"></label>
          <label>Delay (min)<br><input type="number" min="0" v-model.number="form.delay" :disabled="form.sessions < 2"></label>
          <label>Only scenarios (regex)<br><input v-model="form.only" placeholder="all" style="width: 12em"></label>
        </div>

        <div class="field">
          <label><input type="checkbox" v-model="form.fetch"> git fetch --all first</label>
        </div>

        <div class="field">
          <label class="title">Dependencies</label>
          <select v-model="form.install">
            <option value="auto">auto: yarn install for refs whose dependencies differ from the checkout's</option>
            <option value="always">always: yarn install for every ref</option>
            <option value="never">never: use the checkout's node_modules for every ref</option>
          </select>
          <div class="help">Installs are temporary (~0.8 GB each, shared by refs with the same yarn.lock) and can take a few minutes.</div>
        </div>

        <p class="muted">{{ runCount }} suite runs in total.</p>
        <p v-if="activeRun" class="error">Run {{ activeRun }} is in progress; wait for it to finish or stop it before starting another.</p>
        <p v-if="error" class="error">{{ error }}</p>
        <button type="submit" class="primary" :disabled="submitting || !!activeRun || !refs.length || !form.suites.length">
          {{ submitting ? 'Starting…' : 'Start run' }}
        </button>
      </template>
    </form>
  `,
}
