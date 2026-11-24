// Small wrappers around fetch for the cylc-ui-bench server API.

async function handle (response) {
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.error || `${response.status} ${response.statusText}`)
  return data
}

export async function get (path) {
  return handle(await fetch(path, { headers: { Accept: 'application/json' } }))
}

export async function post (path, body = {}) {
  return handle(await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'cylc-ui-bench' },
    body: JSON.stringify(body),
  }))
}

export const ACTIVE = ['starting', 'running']

export function fmtDate (iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleString([], {
    year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}
