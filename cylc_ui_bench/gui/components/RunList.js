import { fmtDate } from '../api.js'

export default {
  name: 'RunList',
  props: {
    runs: { type: Array, required: true },
    selected: { type: String, default: null },
  },
  emits: ['select'],
  setup () {
    return { fmtDate }
  },
  template: `
    <ul class="runs">
      <li v-for="run in runs" :key="run.id" :class="{ selected: run.id === selected }" @click="$emit('select', run.id)">
        <div>
          <b>{{ fmtDate(run.created) || run.id }}</b>
          <span :class="['state', run.state]">{{ run.state }}</span>
        </div>
        <div class="refs">{{ run.refs.join(' vs ') }}</div>
        <div class="muted" v-if="run.total && !run.legacy">{{ run.done }}/{{ run.total }} runs<span v-if="run.failed">, {{ run.failed }} failed</span></div>
      </li>
      <li v-if="!runs.length" class="muted">No runs yet</li>
    </ul>
  `,
}
