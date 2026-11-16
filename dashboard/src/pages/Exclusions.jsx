import { useEffect, useState } from 'react'
import { api, dt, num, useApi, useFilters } from '../api'
import { Badge, Card, Loading, Table } from '../ui'
import { Inventory, ShareBar } from '../components/ExclusionTools'

/** Manual, editable exclusion list. Every change re-applies automatically (a few seconds) and all tabs reload. */
function AddForm({ kinds, onDone }) {
  const [kind, setKind] = useState('name')
  const [value, setValue] = useState('')
  const [note, setNote] = useState('')
  const [preview, setPreview] = useState(null)
  const [err, setErr] = useState('')
  const f = useFilters()

  const first = value.split(/[\n,]/).map((v) => v.trim()).find(Boolean)
  const doPreview = async () => {
    setErr(''); setPreview(null)
    try { setPreview(await api('/exclusions/preview', { params: { kind, value: first } })) } catch (e) { setErr(e.message) }
  }
  const add = async () => {
    setErr('')
    try {
      await api('/exclusions', { method: 'POST', body: { kind, value, note } })
      setValue(''); setNote(''); setPreview(null); f.reloadMeta(); onDone()
    } catch (e) { setErr(e.message) }
  }
  return (
    <Card title="Add an exclusion" sub="Excluded traffic is flagged, not deleted – you can switch it back on any time with “Include excluded traffic” in the header.">
      <div className="form-grid">
        <label>What to exclude
          <select className="field" style={{ width: '100%' }} value={kind} onChange={(e) => { setKind(e.target.value); setPreview(null) }}>
            {Object.entries(kinds).map(([k, d]) => <option key={k} value={k}>{k}</option>)}
          </select>
        </label>
        <div className="muted" style={{ alignSelf: 'end' }}>{kinds[kind]}</div>
        <label style={{ gridColumn: '1 / -1' }}>Value(s) – one per line, or comma separated
          <textarea className="field" value={value} onChange={(e) => { setValue(e.target.value); setPreview(null) }} placeholder={kind === 'ip' ? '45.119.30.192\n103.21.*' : kind === 'email' ? '@agency.com\nsomeone@gmail.com' : ''} />
        </label>
        <label style={{ gridColumn: '1 / -1' }}>Note (optional)
          <input className="field" style={{ width: '100%' }} value={note} onChange={(e) => setNote(e.target.value)} placeholder="why – e.g. “Raja's phone”, “founder testing”" />
        </label>
      </div>
      <div className="chip-row" style={{ marginTop: 12 }}>
        <button className="btn" disabled={!first} onClick={doPreview}>Preview impact</button>
        <button className="btn primary" disabled={!first} onClick={add}>Add &amp; apply</button>
        {preview && <span className="badge warn">{first}: would remove {num(preview.events)} events · {num(preview.sessions)} sessions{preview.people != null ? ` · ${num(preview.people)} people` : ''}</span>}
        {err && <span className="badge bad">{err}</span>}
      </div>
    </Card>
  )
}

function Finder({ onAdded }) {
  const [q, setQ] = useState('')
  const [res, setRes] = useState(null)
  const f = useFilters()
  useEffect(() => {
    if (q.trim().length < 2) { setRes(null); return }
    const t = setTimeout(() => api('/lookup', { params: { q: q.trim() } }).then(setRes).catch(() => setRes([])), 350)
    return () => clearTimeout(t)
  }, [q])
  const add = async (kind, value) => { await api('/exclusions', { method: 'POST', body: { kind, value, note: 'from finder' } }); f.reloadMeta(); onAdded() }
  return (
    <Card title="Find a name, IP, phone, session or browser id" sub="Type part of anything you know about a person – then exclude the exact identifier with one click.">
      <input className="field" style={{ width: '100%', maxWidth: 480 }} value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. raja, 9967, 45.119, a815962…" />
      {res && (
        <div style={{ marginTop: 10 }}>
          <Table empty="Nothing matches" cols={[
            { label: 'Type', render: (r) => <Badge>{r.kind}</Badge> },
            { label: 'Value', cls: 'mono', render: (r) => <span className="trunc" style={{ display: 'block' }} title={r.value}>{r.value}</span> },
            { label: 'Events', num: true, render: (r) => num(r.events) }, { label: 'Sessions', num: true, render: (r) => num(r.sessions) },
            { label: 'Last seen', render: (r) => dt(r.last_seen) },
            { label: '', render: (r) => (r.excluded ? <Badge tone="bad">already excluded</Badge> : <button className="btn small danger" onClick={() => add(r.kind, r.value)}>Exclude</button>) },
          ]} rows={res} />
        </div>
      )}
    </Card>
  )
}

function Row({ r, onChange }) {
  const [edit, setEdit] = useState(false)
  const [v, setV] = useState(r.value)
  const [n, setN] = useState(r.note || '')
  const f = useFilters()
  const patch = async (body) => { await api(`/exclusions/${r.id}`, { method: 'PUT', body }); f.reloadMeta(); onChange() }
  const del = async () => { if (confirm(`Remove ${r.kind}: ${r.value}?`)) { await api(`/exclusions/${r.id}`, { method: 'DELETE' }); f.reloadMeta(); onChange() } }
  return (
    <tr style={{ opacity: r.active ? 1 : 0.55 }}>
      <td><input type="checkbox" checked={r.active} onChange={(e) => patch({ active: e.target.checked })} title="Active" /></td>
      <td><Badge>{r.kind}</Badge></td>
      <td className="mono">{edit ? <input className="field" value={v} onChange={(e) => setV(e.target.value)} /> : r.value}</td>
      <td>{edit ? <input className="field" style={{ width: '100%' }} value={n} onChange={(e) => setN(e.target.value)} /> : r.note || <span className="muted">–</span>}</td>
      <td className="muted">{r.source === 'default' ? 'built-in' : 'manual'} · {dt(r.updated_at)}</td>
      <td style={{ whiteSpace: 'nowrap' }}>
        {edit
          ? <><button className="btn small primary" onClick={async () => { await patch({ value: v, note: n }); setEdit(false) }}>Save</button>{' '}<button className="btn small" onClick={() => { setEdit(false); setV(r.value); setN(r.note || '') }}>Cancel</button></>
          : <><button className="btn small" onClick={() => setEdit(true)}>Edit</button>{' '}<button className="btn small danger" onClick={del}>Delete</button></>}
      </td>
    </tr>
  )
}

const SORTERS = {
  new: (a, b) => b.id - a.id, old: (a, b) => a.id - b.id,
  az: (a, b) => a.value.localeCompare(b.value, 'en', { numeric: true, sensitivity: 'base' }), za: (a, b) => b.value.localeCompare(a.value, 'en', { numeric: true, sensitivity: 'base' }),
  kind: (a, b) => a.kind.localeCompare(b.kind) || a.value.localeCompare(b.value), active: (a, b) => Number(b.active) - Number(a.active) || b.id - a.id,
}
const sortRules = (rows, how) => [...rows].sort(SORTERS[how] || SORTERS.new)

export default function Exclusions() {
  const f = useFilters()
  const list = useApi('/exclusions', {}, { scoped: false })
  const impact = useApi('/meta', {}, { scoped: false })
  const [kindFilter, setKindFilter] = useState('')
  const [listSort, setListSort] = useState('new')
  const reload = () => f.bump()
  const c = impact.data?.counts
  const job = impact.data?.job
  return (
    <>
      <div className="banner ok">
        <div>
          Excluded right now: <b>{num(c?.sessions_excluded)}</b> of {num(c?.sessions)} sessions · <b>{num(c?.events_excluded)}</b> of {num(c?.events)} events · <b>{num(c?.people_excluded)}</b> people · <b>{num(c?.orders_excluded)}</b> orders.
          {job?.running && <span className="badge warn" style={{ marginLeft: 8 }}>applying changes…</span>}
        </div>
        <div className="spacer" />
        <button className="btn" disabled={job?.running} onClick={async () => { await api('/exclusions/apply', { method: 'POST' }); f.reloadMeta() }}>Re-apply all rules</button>
      </div>
      <ShareBar />
      {list.data && <AddForm kinds={list.data.kinds} onDone={reload} />}
      <Finder onAdded={reload} />
      <Inventory />
      <Loading state={list}>
        {({ rows, kinds }) => (
          <Card title={`Exclusion list (${rows.length})`} sub="tick/untick to enable or disable a rule · edit or delete · every change re-applies automatically"
            right={<span className="chip-row"><select className="field" value={listSort} onChange={(e) => setListSort(e.target.value)} aria-label="Sort rules"><option value="new">Newest first</option><option value="old">Oldest first</option><option value="az">Value A → Z</option><option value="za">Value Z → A</option><option value="kind">Type A → Z</option><option value="active">Active first</option></select><select className="field" value={kindFilter} onChange={(e) => setKindFilter(e.target.value)}><option value="">All types</option>{Object.keys(kinds).map((k) => <option key={k}>{k}</option>)}</select></span>}>
            <div className="table-wrap">
              <table>
                <thead><tr><th>On</th><th>Type</th><th>Value</th><th>Note</th><th>Source · updated</th><th /></tr></thead>
                <tbody>{sortRules(rows.filter((r) => !kindFilter || r.kind === kindFilter), listSort).map((r) => <Row key={`${r.id}-${r.updated_at}`} r={r} onChange={reload} />)}</tbody>
              </table>
            </div>
          </Card>
        )}
      </Loading>
    </>
  )
}
