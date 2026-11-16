import { useRef, useState } from 'react'
import { api, dt, num, useApi, useFilters } from '../api'
import { Badge, Card, Chips, ExportBtn, Loading, Search, Table } from '../ui'

/** Tiny RFC-4180 CSV reader (quoted fields, embedded commas / quotes / newlines). */
function parseCsv(text) {
  const rows = []
  let row = []
  let cell = ''
  let q = false
  const t = text.replace(/^﻿/, '')
  for (let i = 0; i < t.length; i++) {
    const ch = t[i]
    if (q) {
      if (ch === '"') { if (t[i + 1] === '"') { cell += '"'; i++ } else q = false } else cell += ch
    } else if (ch === '"') q = true
    else if (ch === ',') { row.push(cell); cell = '' }
    else if (ch === '\n' || ch === '\r') { if (ch === '\r' && t[i + 1] === '\n') i++; row.push(cell); rows.push(row); row = []; cell = '' }
    else cell += ch
  }
  if (cell !== '' || row.length) { row.push(cell); rows.push(row) }
  return rows.filter((r) => r.some((c) => c.trim() !== ''))
}

/** Read an exported exclusion file (our JSON, or a CSV with kind,value[,note,active]) into a list of items. */
export async function readExclusionFile(file) {
  const text = await file.text()
  if (file.name.toLowerCase().endsWith('.csv')) {
    const [head, ...body] = parseCsv(text)
    const idx = (n) => head.map((h) => h.trim().toLowerCase()).indexOf(n)
    if (idx('kind') < 0 || idx('value') < 0) throw new Error('CSV needs “kind” and “value” columns')
    return body.map((r) => ({ kind: (r[idx('kind')] || '').trim(), value: (r[idx('value')] || '').trim(), note: idx('note') >= 0 ? r[idx('note')] || null : null, active: idx('active') >= 0 ? (r[idx('active')] || 'true').trim().toLowerCase() !== 'false' : true }))
  }
  const j = JSON.parse(text)
  const list = Array.isArray(j) ? j : j.exclusions
  if (!Array.isArray(list)) throw new Error('This file does not look like an exclusion list')
  return list.map((e) => ({ kind: String(e.kind || '').trim(), value: String(e.value || '').trim(), note: e.note ?? null, active: e.active !== false }))
}

/** Download the exclusion list, or import one a teammate sent. Nothing is overwritten: only new entries are added. */
export function ShareBar() {
  const f = useFilters()
  const fileRef = useRef(null)
  const [builtin, setBuiltin] = useState(false)
  const [pending, setPending] = useState(null)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')

  const pick = async (file) => {
    setErr(''); setMsg('')
    if (!file) return
    try {
      const items = await readExclusionFile(file)
      const r = await api('/exclusions/import', { method: 'POST', body: { exclusions: items, dry_run: true } })
      setPending({ items, name: file.name, ...r })
    } catch (e) { setErr(e.message) }
    if (fileRef.current) fileRef.current.value = ''
  }
  const confirm = async () => {
    try {
      const r = await api('/exclusions/import', { method: 'POST', body: { exclusions: pending.items, dry_run: false } })
      setMsg(`Imported ${r.new} new exclusion${r.new === 1 ? '' : 's'} (${r.duplicates} were already in your list). Rebuilding…`)
      setPending(null); f.reloadMeta(); f.bump()
    } catch (e) { setErr(e.message) }
  }
  return (
    <Card title="Share your exclusion list" sub="Download the list and send it to a teammate; they import it into their dashboard and get the same exclusions. Importing only adds what's missing.">
      <div className="chip-row">
        <a className="btn primary" href={`/api/exclusions/export?format=json&include_builtin=${builtin}`} download>Download list (.json)</a>
        <a className="btn" href={`/api/exclusions/export?format=csv&include_builtin=${builtin}`} download>Download as CSV</a>
        <label className="toggle"><input type="checkbox" checked={builtin} onChange={(e) => setBuiltin(e.target.checked)} /> include built-in rules</label>
        <span style={{ flex: 1 }} />
        <button type="button" className="btn" onClick={() => fileRef.current?.click()}>Import a list…</button>
        <input ref={fileRef} type="file" accept=".json,.csv,application/json,text/csv" style={{ display: 'none' }} onChange={(e) => pick(e.target.files?.[0])} aria-label="Choose an exclusion file" />
      </div>
      <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>The file contains staff phone numbers, emails and IP addresses. Send it only through a private channel.</div>
      {err && <div className="banner err" style={{ marginTop: 10 }}>{err}</div>}
      {msg && <div className="banner ok" style={{ marginTop: 10 }}>{msg}</div>}
      {pending && (
        <div className="banner" style={{ marginTop: 10, display: 'block' }}>
          <b>{pending.name}</b>: {num(pending.new)} new, {num(pending.duplicates)} already in your list{pending.invalid_count ? `, ${num(pending.invalid_count)} invalid (skipped)` : ''}.
          {pending.preview.length > 0 && <div className="muted mono" style={{ margin: '6px 0', fontSize: 12 }}>{pending.preview.slice(0, 6).map((p) => `${p.kind}: ${p.value}`).join('  ·  ')}{pending.new > 6 ? '  …' : ''}</div>}
          <div className="chip-row" style={{ marginTop: 6 }}>
            <button className="btn primary" disabled={!pending.new} onClick={confirm}>Import {num(pending.new)} new</button>
            <button className="btn" onClick={() => setPending(null)}>Cancel</button>
          </div>
        </div>
      )}
    </Card>
  )
}

const KIND_FILTERS = ['all', 'ip', 'phone', 'email', 'user_id', 'visitor_id', 'name']

/** Everything we have reason to think is internal or automated, how much of it still counts, and a way to add it to the list. */
export function Inventory() {
  const f = useFilters()
  const s = useApi('/exclusions/inventory', {}, { scoped: false })
  const [kind, setKind] = useState('all')
  const [view, setView] = useState('open')
  const [q, setQ] = useState('')
  const [sel, setSel] = useState(new Set())
  const [msg, setMsg] = useState('')
  const id = (r) => `${r.kind}\u0000${r.value}`

  return (
    <Loading state={s}>
      {(d) => {
        const rows = d.rows.filter((r) => (kind === 'all' || r.kind === kind)
          && (view === 'all' || (view === 'open' && !r.in_list) || (view === 'leaks' && !r.in_list && r.counted > 0))
          && (!q || `${r.value} ${r.label || ''} ${r.reason}`.toLowerCase().includes(q.toLowerCase())))
        const chosen = d.rows.filter((r) => sel.has(id(r)))
        const safe = rows.filter((r) => !r.in_list && !r.risky)
        const add = async () => {
          const items = chosen.map((r) => ({ kind: r.kind, value: r.value, note: `${r.label ? r.label + ': ' : ''}${r.reason}`.slice(0, 200) }))
          const r = await api('/exclusions/bulk', { method: 'POST', body: { items } })
          setMsg(`Added ${r.added} to your exclusion list (${r.skipped} were already there). Rebuilding…`)
          setSel(new Set()); f.reloadMeta(); f.bump()
        }
        const toggle = (i) => setSel((p) => { const n = new Set(p); if (n.has(i)) n.delete(i); else n.add(i); return n })
        const toggleAll = (ids, on) => setSel((p) => { const n = new Set(p); ids.forEach((i) => (on ? n.add(i) : n.delete(i))); return n })
        return (
          <Card title="Internal identifiers we found" sub={`${num(d.summary.total)} identifiers (IPs, phones, emails, accounts, browsers) look internal or automated · ${num(d.summary.in_list)} already in your list · ${num(d.summary.still_counted)} not listed and still affecting your numbers`}
            right={<ExportBtn name="internal-identifiers" rows={d.rows} fields={[['Type', 'kind'], ['Value', 'value'], ['Name', 'label'], ['Why', 'reason'], ['Sessions', 'sessions'], ['Still counted', 'counted'], ['In list', (r) => (r.in_list ? 'yes' : 'no')], ['Shared by browsers', 'shared']]} />}>
            <div className="chip-row" style={{ marginBottom: 10 }}>
              <Chips value={kind} onChange={setKind} options={KIND_FILTERS.map((k) => ({ value: k, label: k === 'all' ? 'All types' : k }))} />
              <Chips value={view} onChange={setView} options={[{ value: 'leaks', label: 'Still counted' }, { value: 'open', label: 'Not in my list' }, { value: 'all', label: 'Everything' }]} />
              <Search value={q} onChange={setQ} placeholder="Search value, name, reason…" />
            </div>
            <div className="bulkbar">
              <span>{chosen.length ? <b>{chosen.length} selected</b> : 'Tick the rows to add, or use “Select all safe”.'}</span>
              <button type="button" className="btn small" onClick={() => toggleAll(safe.map(id), true)} disabled={!safe.length}>Select all safe ({safe.length})</button>
              {chosen.length > 0 && <button type="button" className="btn small" onClick={() => setSel(new Set())}>Clear</button>}
              <span className="spacer" />
              <button type="button" className="btn primary small" disabled={!chosen.length} onClick={add}>Add {chosen.length || ''} to exclusion list</button>
            </div>
            {msg && <div className="banner ok" style={{ marginBottom: 10 }}>{msg}</div>}
            <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>“Safe” leaves out IP addresses shared by 4+ browsers (mobile carriers and offices): excluding one of those would also remove real customers.</div>
            <Table selectable selected={sel} onToggle={toggle} onToggleAll={toggleAll} rowId={id} rows={rows} empty="Nothing matches. Try “Everything”." cols={[
              { label: 'Type', key: 'kind', render: (r) => <Badge>{r.kind}</Badge> },
              { label: 'Value', key: 'value', cls: 'mono', render: (r) => <span className="trunc" style={{ display: 'block', maxWidth: 230 }} title={r.value}>{r.value}</span> },
              { label: 'Name', key: 'label', cls: 'nw', render: (r) => r.label || <span className="muted">–</span> },
              { label: 'Why it looks internal', key: 'reason', render: (r) => <span className="trunc" style={{ display: 'block', maxWidth: 240 }} title={r.reason}>{r.reason}</span> },
              { label: 'Sessions', num: true, sortBy: 'sessions', render: (r) => num(r.sessions) },
              { label: 'Still counted', num: true, sortBy: 'counted', render: (r) => (r.counted ? <b>{num(r.counted)}</b> : '0') },
              { label: 'Last seen', cls: 'nw', sortBy: 'last_seen', render: (r) => dt(r.last_seen) },
              { label: 'Status', cls: 'nw', sortBy: (r) => (r.in_list ? 2 : r.risky ? 1 : 0), render: (r) => (r.in_list ? <Badge tone="good">In list</Badge> : r.risky ? <span title={`This IP was used by ${r.shared} different browsers, so excluding it would remove real customers too`}><Badge tone="warn">Shared ×{r.shared}</Badge></span> : <Badge>Not listed</Badge>) },
            ]} />
          </Card>
        )
      }}
    </Loading>
  )
}
