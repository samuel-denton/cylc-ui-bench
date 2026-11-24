import { computed, createApp, onMounted, onUnmounted, ref } from 'vue'
import { ACTIVE, get } from './api.js'
import RunDetail from './components/RunDetail.js'
import RunForm from './components/RunForm.js'
import RunList from './components/RunList.js'

// the selected run is kept in the URL hash (#run=<id>) so reloads keep it
const fromHash = () => new URLSearchParams(location.hash.slice(1)).get('run')

const App = {
  components: { RunDetail, RunForm, RunList },
  setup () {
    const options = ref(null)
    const runs = ref([])
    const selected = ref(fromHash())
    const error = ref(null)
    let timer = null

    const activeRun = computed(() => runs.value.find((r) => ACTIVE.includes(r.state))?.id ?? null)

    async function refresh () {
      try {
        runs.value = await get('/api/runs')
        error.value = null
      } catch (err) {
        error.value = err.message
      }
    }

    function select (id) {
      selected.value = id
      location.hash = id ? `run=${encodeURIComponent(id)}` : ''
    }

    async function onStarted (id) {
      await refresh()
      select(id)
    }

    const onHash = () => { selected.value = fromHash() }
    onMounted(async () => {
      window.addEventListener('hashchange', onHash)
      try {
        options.value = await get('/api/options')
      } catch (err) {
        error.value = err.message
      }
      await refresh()
      timer = setInterval(refresh, 3000)
    })
    onUnmounted(() => {
      clearInterval(timer)
      window.removeEventListener('hashchange', onHash)
    })

    return { options, runs, selected, error, activeRun, refresh, select, onStarted }
  },
  template: `
    <header>
      <h1>cylc-ui-bench</h1>
      <span class="muted" v-if="options">{{ options.cylc_ui }} · results in {{ options.results_dir }}</span>
    </header>
    <div class="layout">
      <aside>
        <button class="new-run primary" @click="select(null)">+ New run</button>
        <run-list :runs="runs" :selected="selected" @select="select"></run-list>
      </aside>
      <main>
        <p v-if="error" class="error">{{ error }}</p>
        <run-detail v-if="selected" :key="selected" :run-id="selected" @changed="refresh"></run-detail>
        <run-form v-else :options="options" :active-run="activeRun" @started="onStarted"></run-form>
      </main>
    </div>
  `,
}

createApp(App).mount('#app')
