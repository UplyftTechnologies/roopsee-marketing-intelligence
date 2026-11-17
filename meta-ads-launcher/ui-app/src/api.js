// Every call carries a header another website's page cannot send, so only this app can change anything.
export async function api(path, { method = 'GET', body } = {}) {
  const init = { method, headers: { 'X-Launcher': '1' } }
  if (body instanceof FormData) init.body = body
  else if (body !== undefined) { init.body = JSON.stringify(body); init.headers['Content-Type'] = 'application/json' }
  const r = await fetch(path, init)
  const data = await r.json().catch(() => ({}))
  if (!r.ok) {
    const d = data.detail
    const err = new Error(typeof d === 'string' ? d : d && d.errors ? d.errors.join(' ') : JSON.stringify(d || data))
    err.errors = d && d.errors
    throw err
  }
  return data
}

/** Polls a background job until it finishes; `onUpdate` receives the job every time. */
export async function followJob(id, onUpdate) {
  for (;;) {
    const j = await api('/api/jobs/' + id)
    onUpdate && onUpdate(j)
    if (j.status === 'done') return j
    await new Promise((r) => setTimeout(r, 700))
  }
}

export async function runCommand(body, onUpdate) {
  const { job } = await api('/api/run', { method: 'POST', body })
  return followJob(job, onUpdate)
}

export const inr = (v) => (v == null ? '–' : '₹' + Number(v).toLocaleString('en-IN', { maximumFractionDigits: 2 }))
export const num = (v) => (v == null ? '–' : Number(v).toLocaleString('en-IN'))
