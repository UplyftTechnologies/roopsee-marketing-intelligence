import { useEffect, useState } from 'react'
import { KEY_LABEL, api, dt, dur, num, useApi, useFilters } from '../api'
import { Badge, Card, Chips, Loading, Pager, Search, Table } from '../ui'

const STAGE = ['Browsed', 'Viewed product', 'Added to cart', 'Reached checkout', 'Started payment', 'Ordered']
const STAGE_TONE = ['', '', 'warn', 'warn', 'serious', 'good']

/** Adds one exclusion and reloads; the API re-applies it in the background. */
export function useQuickExclude() {
  const f = useFilters()
  const [msg, setMsg] = useState('')
  const exclude = async (kind, value, note) => {
    if (!value) return
    try {
      const r = await api('/exclusions', { method: 'POST', body: { kind, value, note } })
      setMsg(r.added ? `Excluded ${kind} “${value}” – rebuilding…` : `${kind} “${value}” is already in the exclusion list`)
      f.reloadMeta()
    } catch (e) { setMsg(`Failed: ${e.message}`) }
  }
  return { exclude, msg }
}

export function SessionDrawer({ id, onClose }) {
  const [d, setD] = useState(null)
  const { exclude, msg } = useQuickExclude()
  useEffect(() => { api(`/sessions/${encodeURIComponent(id)}`).then(setD).catch(() => setD({ error: true })) }, [id])
  const s = d?.session
  return (
    <>
      <div className="drawer-bg" onClick={onClose} />
      <aside className="drawer">
        <div className="card-head"><h3>Session {id.slice(0, 18)}…</h3><button className="btn small" onClick={onClose}>Close</button></div>
        {!d && <div className="empty">Loading…</div>}
        {d?.error && <div className="banner err">Session not found</div>}
        {s && (
          <>
            <dl className="kv">
              <dt>Started</dt><dd>{dt(s.started_at)} · {dur(s.duration_s)} · {s.events} events</dd>
              <dt>Source</dt><dd>{s.channel} — {s.source} / {s.medium} / {s.campaign}</dd>
              <dt>Landing</dt><dd className="mono">{s.landing_path}</dd>
              <dt>Place / device</dt><dd>{[s.city, s.region, s.country].filter(Boolean).join(', ') || '–'} · {s.is_app ? 'Android app' : s.device} · {s.platform}</dd>
              <dt>IP</dt><dd className="mono">{s.ip || '–'}</dd>
              <dt>Browser id</dt><dd className="mono">{s.visitor_key}</dd>
              <dt>User id</dt><dd className="mono">{s.user_id || '–'}</dd>
              <dt>Phone</dt><dd className="mono">{s.phone10 || '–'}</dd>
              <dt>Journey</dt><dd>{s.key_events || '–'}</dd>
              <dt>Status</dt><dd>{s.is_excluded ? <Badge tone="bad">Excluded: {s.excl_reason}</Badge> : <Badge tone="good">Counted</Badge>}</dd>
            </dl>
            <Card title="Exclude from analytics" sub="adds a rule on the Exclusions tab (editable there). Browser/user/phone rules also remove every other session of that person." style={{ marginTop: 14 }}>
              <div className="chip-row">
                <button className="btn small" onClick={() => exclude('session_id', s.session_id, 'from session drawer')}>This session</button>
                <button className="btn small" disabled={!s.visitor_key} onClick={() => exclude('visitor_id', s.visitor_key, 'from session drawer')}>This browser</button>
                <button className="btn small" disabled={!s.ip} onClick={() => exclude('ip', s.ip, 'from session drawer')}>This IP</button>
                <button className="btn small" disabled={!s.user_id} onClick={() => exclude('user_id', s.user_id, 'from session drawer')}>This user</button>
                <button className="btn small" disabled={!s.phone10} onClick={() => exclude('phone', s.phone10, 'from session drawer')}>This phone</button>
              </div>
              {msg && <div className="muted" style={{ marginTop: 8 }}>{msg}</div>}
            </Card>
            <h3 style={{ margin: '16px 0 8px' }}>Timeline</h3>
            <div className="timeline">
              {d.events.map((e, i) => (
                <div key={i} className={`tl-item ${e.event_key ? 'key' : ''}`}>
                  <span className="muted">{new Date(e.at).toLocaleTimeString('en-IN')}</span>{' '}
                  <b>{e.event_key ? KEY_LABEL[e.event_key] || e.event_key : e.event_name}</b>{' '}
                  <span className="muted">{e.event_key ? `(${e.event_name}) ` : ''}{e.path}{e.product_name ? ` · ${e.product_name}` : ''}{e.amount ? ` · ₹${e.amount}` : ''}{e.search_term ? ` · “${e.search_term}”` : ''}</span>
                </div>
              ))}
            </div>
          </>
        )}
      </aside>
    </>
  )
}

export default function Sessions() {
  const [search, setSearch] = useState('')
  const [stage, setStage] = useState(0)
  const [only, setOnly] = useState('counted')
  const [offset, setOffset] = useState(0)
  const [open, setOpen] = useState(null)
  const limit = 50
  const s = useApi('/sessions', { search, min_stage: stage || undefined, only_excluded: only === 'excluded' || undefined, limit, offset })
  useEffect(() => setOffset(0), [search, stage, only])
  return (
    <>
      <div className="chip-row">
        <Search value={search} onChange={setSearch} placeholder="Search session id, IP, phone, name, city, campaign…" />
        <Chips value={stage} onChange={setStage} options={[{ value: 0, label: 'All sessions' }, { value: 2, label: 'Added to cart+' }, { value: 3, label: 'Reached checkout+' }, { value: 5, label: 'Ordered' }]} />
        <Chips value={only} onChange={setOnly} options={[{ value: 'counted', label: 'Per global filter' }, { value: 'excluded', label: 'Only excluded' }]} />
      </div>
      <Loading state={s}>
        {({ rows, total }) => (
          <Card title={`${num(total)} sessions`} sub="click a row for the full event timeline and one-click exclusion">
            <Table onRow={(r) => setOpen(r.session_id)} rowClass={(r) => (r.is_excluded ? 'excluded' : '')} cols={[
              { label: 'Started', render: (r) => dt(r.started_at) },
              { label: 'Who', render: (r) => r.name || (r.phone10 ? <span className="mono">{r.phone10}</span> : <span className="muted">anonymous</span>) },
              { label: 'Journey', render: (r) => <span title={r.key_events}>{r.key_events ? r.key_events.split(' > ').map((k) => KEY_LABEL[k] || k).join(' → ') : <span className="muted">{r.events} events, no key action</span>}</span> },
              { label: 'Stage', render: (r) => <Badge tone={STAGE_TONE[r.stage]}>{STAGE[r.stage]}</Badge> },
              { label: 'Channel', render: (r) => <span title={`${r.source} / ${r.medium} / ${r.campaign}`}>{r.channel}</span> },
              { label: 'Place', render: (r) => r.city || r.region || '–' },
              { label: 'Device', render: (r) => (r.is_app ? 'App' : r.device || '–') },
              { label: 'Events', num: true, render: (r) => r.events }, { label: 'Time', num: true, render: (r) => dur(r.duration_s) },
              { label: '', render: (r) => (r.is_excluded ? <Badge tone="bad">excluded</Badge> : null) },
            ]} rows={rows} />
            <Pager total={total} limit={limit} offset={offset} setOffset={setOffset} />
          </Card>
        )}
      </Loading>
      {open && <SessionDrawer id={open} onClose={() => setOpen(null)} />}
    </>
  )
}
