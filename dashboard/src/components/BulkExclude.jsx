import { useState } from 'react'
import { api, num, useFilters } from '../api'

/** Shown above a table when rows are ticked: exclude the selected rows' browsers / users / phones / IPs in one go (one rebuild). */
export default function BulkExclude({ rows, fields, onClear, noun }) {
  const f = useFilters()
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  if (!rows.length) return null
  const options = fields.map((fl) => ({ ...fl, values: [...new Set(rows.map(fl.get).filter(Boolean).map(String))] })).filter((o) => o.values.length)

  const run = async (o) => {
    const risk = o.kind === 'ip' ? '\n\nCareful: an IP address can be shared by many different visitors (mobile carriers, offices), so this may remove real customers too.' : ''
    if (!window.confirm(`Exclude ${o.values.length} ${o.label}${o.values.length === 1 ? '' : 's'} from the analytics?\n\nEvery other session from ${o.values.length === 1 ? 'it' : 'them'} will be hidden too. You can undo this on the Exclusions tab.${risk}`)) return
    setBusy(true)
    try {
      const r = await api('/exclusions/bulk', { method: 'POST', body: { items: o.values.map((v) => ({ kind: o.kind, value: v, note: `bulk from ${noun}` })) } })
      setMsg(`Added ${num(r.added)} to the exclusion list (${num(r.skipped)} already there). Rebuilding…`)
      f.reloadMeta(); f.bump(); onClear()
    } catch (e) { setMsg(`Failed: ${e.message}`) }
    setBusy(false)
  }
  return (
    <div className="bulkbar" role="region" aria-label="Bulk actions">
      <b>{rows.length} selected</b>
      <span className="muted">Exclude their:</span>
      {options.map((o) => <button key={o.kind} type="button" className="btn small" disabled={busy} onClick={() => run(o)}>{o.label} ({o.values.length})</button>)}
      {options.length === 0 && <span className="muted">nothing to exclude on these rows</span>}
      <span className="spacer" />
      {msg && <span className="muted">{msg}</span>}
      <button type="button" className="btn small" onClick={onClear}>Clear selection</button>
    </div>
  )
}
