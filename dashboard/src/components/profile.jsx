import { useState } from 'react'
import { KEY_LABEL, dt, tod } from '../api'
import { Badge, Card, Table } from '../ui'
import { useQuickExclude } from '../shared'
import Icon from './Icon'
import Popover from './Popover'

export const pretty = (p) => { try { return decodeURIComponent(p || '') } catch { return p || '' } }
const label = (e) => (e.event_key ? KEY_LABEL[e.event_key] || e.event_key : e.event_name.replace(/_/g, ' '))
const offset = (s) => {
  if (s < 3600) return `+${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
  return `+${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}m`
}

/** Ordered activity inside one session: clock time, time since the session began, key actions highlighted, repeats grouped. */
const norm = (x) => String(x ?? '').toLowerCase().replace(/[_\-\s]+/g, ' ').trim()
/** Does an event match the search words? Every word must appear in the event name, its label, product, page or search term. */
const matches = (e, words) => {
  const hay = norm([e.event_name, label(e), e.product_name, e.brand, e.path, e.search_term, ...(e.details || []).map((d) => d.v)].join(' '))
  return words.every((w) => hay.includes(w))
}

/** Pass `query` + `onQuery` to control the search box from outside (for example from a click on an event type). */
export function SessionTimeline({ events, max = 400, query, onQuery }) {
  const [keyOnly, setKeyOnly] = useState(false)
  const [own, setOwn] = useState('')
  const [open, setOpen] = useState(new Set())
  const q = query ?? own
  const setQ = onQuery ?? setOwn
  if (!events || !events.length) return <div className="empty">No events recorded</div>
  const t0 = new Date(events[0].at).getTime()
  const words = norm(q).split(' ').filter(Boolean)
  const rows = []
  let hits = 0
  for (const e of events) {
    if (keyOnly && !e.event_key) continue
    if (words.length) { if (!matches(e, words)) continue; hits += 1 }
    const last = rows[rows.length - 1]
    if (last && !e.event_key && last.e.event_name === e.event_name && last.e.path === e.path) last.n += 1
    else rows.push({ e, n: 1 })
  }
  return (
    <div>
      <div className="tl-tools">
        <input className="field" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search events, e.g. address, add to cart…" aria-label="Search events by name" style={{ minWidth: 220 }} />
        <label className="toggle"><input type="checkbox" checked={keyOnly} onChange={(e) => setKeyOnly(e.target.checked)} /> Key actions only</label>
        <span className="muted">{words.length ? `${hits} of ${events.length} events match` : `${events.length} events`}{!words.length && rows.length !== events.length && !keyOnly ? ` · ${rows.length} steps (repeats grouped)` : ''}</span>
        {words.length > 0 && <button type="button" className="btn small" onClick={() => setQ('')}>Clear search</button>}
      </div>
      <div className="timeline">
        {rows.slice(0, max).map(({ e, n }, i) => {
          const detail = [pretty(e.path), e.product_name && `· ${e.product_name}`, e.amount ? `· ₹${e.amount}` : null, e.search_term && `· “${e.search_term}”`].filter(Boolean).join(' ')
          const det = e.details || []
          const isOpen = open.has(e.at + e.event_name)
          const toggleOpen = () => setOpen((p) => { const nx = new Set(p); const k = e.at + e.event_name; if (nx.has(k)) nx.delete(k); else nx.add(k); return nx })
          return (
            <div key={i} className={`tl-item ${e.event_key ? 'key' : ''}`}>
              <span className="tl-time">{tod(e.at)} <small>{offset(Math.max(0, Math.round((new Date(e.at).getTime() - t0) / 1000)))}</small></span>
              <b>{label(e)}</b>{n > 1 && <span className="muted"> ×{n}</span>} <span className="muted">{detail}</span>
              {det.length > 0 && <button type="button" className="tl-more" onClick={toggleOpen} aria-expanded={isOpen} title={isOpen ? 'Hide the data of this event' : 'Show all data recorded for this event'}>{isOpen ? 'Hide data' : 'Data'}</button>}
              {isOpen && <dl className="tl-all">{det.map((d) => <div key={d.k}><dt>{d.k}</dt><dd>{d.v}</dd></div>)}</dl>}
            </div>
          )
        })}
      </div>
      {words.length > 0 && rows.length === 0 && <div className="empty">No event matches “{q}”.</div>}
      {rows.length > max && <div className="muted" style={{ marginTop: 6 }}>Showing the first {max} of {rows.length} steps.</div>}
    </div>
  )
}

const CATS = [
  { id: 'visits', label: 'Visits & pages' }, { id: 'browsing', label: 'Browsing' }, { id: 'cart', label: 'Cart & orders' }, { id: 'clicks', label: 'Other clicks' },
  { id: 'login', label: 'Login & account' }, { id: 'roop', label: 'Roop chat' }, { id: 'errors', label: 'Errors & slow pages' },
]
const CART_KEYS = new Set(['add_to_cart', 'view_cart', 'checkout_view', 'pay_started', 'order_placed'])
/** Which group an event belongs to in the session table. */
export function eventCategory(e) {
  const n = e.event_name || ''
  if (n === 'assistant_chat') return 'roop'
  if (/error|fail|slow|timeout|exception|page_load_sample|web_vital/i.test(n)) return 'errors'
  if (/login|logout|signup|sign_up|register|otp|password|account|verify|verified/i.test(n)) return 'login'
  if (CART_KEYS.has(e.event_key) || /cart|checkout|order|payment|pay_|coupon/i.test(n)) return 'cart'
  if (/^(page_viewed|page_view|web_opened|app_opened|session_started|screen_viewed)/i.test(n)) return 'visits'
  if (/click|tap|toggle|ui_/i.test(n)) return 'clicks'
  return 'browsing'
}
const gapText = (s) => (s < 1 ? '–' : s < 60 ? `+${s} sec` : s < 3600 ? `+${Math.floor(s / 60)} min ${s % 60 ? `${s % 60} s` : ''}`.trim() : `+${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`)
const cap = (s) => (s ? String(s).replace(/[_-]+/g, ' ').replace(/^./, (c) => c.toUpperCase()) : '')

/** An event's stored record as JSON (what the tracker sent), with the readable view one click away. */
function RawData({ e }) {
  const [view, setView] = useState(e.raw ? 'json' : 'plain')
  const text = e.raw ? JSON.stringify(e.raw, null, 2) : ''
  const det = e.details || []
  return (
    <div className="tl-all" style={{ display: 'block' }}>
      <div className="chip-row" style={{ marginBottom: 6 }}>
        {e.raw && <button type="button" className={`chip ${view === 'json' ? 'on' : ''}`} onClick={() => setView('json')}>JSON</button>}
        <button type="button" className={`chip ${view === 'plain' ? 'on' : ''}`} onClick={() => setView('plain')}>Readable</button>
        {e.raw && <CopyBtn text={text} title="Copy this event's JSON" />}
      </div>
      {view === 'json'
        ? <pre className="mono" style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: 12, maxHeight: 360, overflow: 'auto' }}>{text}</pre>
        : det.length ? <dl style={{ margin: 0, display: 'grid', gap: 3 }}>{det.map((d) => <div key={d.k}><dt>{d.k}</dt><dd>{d.v}</dd></div>)}</dl> : <span className="muted">Nothing else was recorded.</span>}
    </div>
  )
}

/** The session's events as a table, the way the roopsee.com admin analytics shows them: # · Time · Gap · Page · What happened · Detail, with group chips and counts. */
export function SessionEventsTable({ events, query, onQuery }) {
  const [cat, setCat] = useState('all')
  const [tech, setTech] = useState(true)
  const [own, setOwn] = useState('')
  const [open, setOpen] = useState(new Set())
  const q = query ?? own
  const setQ = onQuery ?? setOwn
  if (!events || !events.length) return <div className="empty">No events recorded</div>
  let prev = null
  const all = events.map((e, i) => {
    const t = new Date(e.at).getTime()
    const gap = prev == null ? 0 : Math.max(0, Math.round((t - prev) / 1000))
    prev = t
    return { e, n: i + 1, gap, cat: eventCategory(e) }
  })
  const counts = {}
  for (const r of all) counts[r.cat] = (counts[r.cat] || 0) + 1
  const words = norm(q).split(' ').filter(Boolean)
  const rows = all.filter((r) => (cat === 'all' || r.cat === cat) && (!words.length || matches(r.e, words)))
  const toggle = (n) => setOpen((p) => { const nx = new Set(p); if (nx.has(n)) nx.delete(n); else nx.add(n); return nx })
  const summary = (e) => {
    if (e.search_term) return `“${e.search_term}”`
    if (e.product_name) return `${e.product_name}${e.amount ? ` · ₹${e.amount}` : ''}`
    const d = (e.details || [])[0]
    if (d) return String(d.v).length > 70 ? `${String(d.v).slice(0, 67)}…` : d.v
    return e.amount ? `₹${e.amount}` : '—'
  }
  return (
    <div>
      <div className="tl-tools">
        {[{ id: 'all', label: 'All', n: all.length }, ...CATS.filter((c) => counts[c.id]).map((c) => ({ ...c, n: counts[c.id] }))].map((c) => (
          <button key={c.id} type="button" className={`chip ${cat === c.id ? 'on' : ''}`} onClick={() => setCat(c.id)}>{c.label} <b>{c.n}</b></button>
        ))}
      </div>
      <div className="tl-tools">
        <input className="field" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search events, e.g. address, add to cart…" aria-label="Search events" style={{ minWidth: 220 }} />
        <label className="toggle"><input type="checkbox" checked={tech} onChange={(e) => setTech(e.target.checked)} /> Show technical names</label>
        <span className="muted">{rows.length === all.length ? `${all.length} events` : `${rows.length} of ${all.length} events`}</span>
        {(words.length > 0 || cat !== 'all') && <button type="button" className="btn small" onClick={() => { setQ(''); setCat('all') }}>Clear</button>}
      </div>
      <Table scroll rows={rows} empty="No event matches." rowClass={(r) => (r.e.event_key ? 'key-row' : '')} cols={[
        { label: '#', cls: 'muted', render: (r) => r.n },
        { label: 'Time', cls: 'nw', render: (r) => tod(r.e.at) },
        { label: 'Gap', cls: 'nw muted', render: (r) => gapText(r.gap) },
        { label: 'Page', cls: 'nw', render: (r) => (r.e.page_type ? cap(r.e.page_type) : r.e.path ? <span className="mono">{pretty(r.e.path).slice(0, 24)}</span> : '–') },
        { label: 'What happened', render: (r) => (r.cat === 'roop' ? <span>💬 {tech ? <span className="mono"><b>{r.e.event_name}</b></span> : <b>Message to Roop</b>}</span>
          : tech ? <span className="mono"><b>{r.e.event_name}</b></span> : <b>{label(r.e)}</b>) },
        { label: 'Score', num: true, render: (r) => (r.e.score != null ? <b title="Product match score">{r.e.score}</b> : r.e.score_note ? <span className="muted">{r.e.score_note}</span> : <span className="muted">–</span>) },
        { label: 'Detail', render: (r) => {
          const det = r.e.details || []
          const ps = r.e.params || []
          return (
            <div>
              {ps.length ? <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 4 }}>{ps.slice(0, 4).map((p) => <span key={p.k} className="chip" style={{ cursor: 'default', maxWidth: 220 }} title={`${p.k}: ${p.v}`}><span className="muted">{p.k}:</span> <span className="trunc" style={{ display: 'inline-block', maxWidth: 130, verticalAlign: 'bottom' }}>{p.v}</span></span>)}{ps.length > 4 && <span className="muted">+{ps.length - 4} more</span>}</span> : <span>{summary(r.e)}</span>}
              {(det.length > 0 || r.e.raw) && <> <button type="button" className="link-btn" onClick={() => toggle(r.n)} aria-expanded={open.has(r.n)} style={{ background: 'none', border: 0, color: 'var(--accent)', cursor: 'pointer', padding: 0, font: 'inherit' }}>{open.has(r.n) ? 'hide data' : 'raw data'}</button></>}
              {open.has(r.n) && <RawData e={r.e} />}
            </div>
          )
        } },
      ]} />
    </div>
  )
}

/** Saved addresses on the account, plus the pincodes / places typed or picked during one session. */
export function AddressCard({ data, title = 'Address' }) {
  const saved = data?.saved || []
  const entered = data?.entered || []
  if (!saved.length && !entered.length) return <Card title={title}><div className="muted">No saved address, and none entered in this session.</div></Card>
  const savedPins = new Set(saved.map((a) => a.pincode))
  return (
    <Card title={title}>
      {saved.length > 0 && <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>Saved on the account ({saved.length})</div>}
      {saved.map((a) => {
        const line = [a.delivery_address, a.nearby_landmark && `Near ${a.nearby_landmark}`, [a.city, a.state].filter(Boolean).join(', '), a.pincode].filter(Boolean).join(', ')
        const extra = a.formatted_address && !line.toLowerCase().includes(a.formatted_address.toLowerCase()) ? a.formatted_address : null
        return (
          <div key={a.id} style={{ marginBottom: 10 }}>
            <div>{a.is_default && <Badge tone="good">default</Badge>} <b>{a.full_name || 'No name given'}</b>{a.phone ? <span className="muted mono"> · {a.phone}</span> : null}</div>
            <div style={{ marginTop: 2 }}>{line || '–'}</div>
            {extra && <div className="muted" style={{ fontSize: 12 }}>Map location: {extra}</div>}
            {a.email && <div className="muted" style={{ fontSize: 12 }}>{a.email}</div>}
            <div className="muted" style={{ fontSize: 12 }}>saved {dt(a.created_at)}{a.updated_at && a.updated_at !== a.created_at ? ` · edited ${dt(a.updated_at)}` : ''}{a.location_source ? ` · via ${a.location_source.replace(/_/g, ' ')}` : ''}{a.latitude != null && a.longitude != null ? ` · ${a.latitude.toFixed(4)}, ${a.longitude.toFixed(4)}` : ''}</div>
          </div>
        )
      })}
      {entered.length > 0 && <div className="muted" style={{ fontSize: 12, margin: '6px 0 4px' }}>Pincodes entered in this session</div>}
      {[...new Set(entered.map((e) => e.pincode))].map((pin) => {
        const evs = entered.filter((e) => e.pincode === pin)
        return (
          <div key={pin} style={{ marginBottom: 6 }}>
            <span className="mono"><b>{pin}</b></span> {savedPins.has(pin) ? <Badge tone="good">matches saved</Badge> : null}
            <div className="muted" style={{ fontSize: 12 }}>{evs.map((e) => `${e.event_name.replace(/_/g, ' ')}${e.n > 1 ? ` ×${e.n}` : ''} (${tod(e.first_at)})`).join(' → ')}</div>
          </div>
        )
      })}
    </Card>
  )
}

/** Journey as small chips: "Product view → Add to cart → Checkout". */
export function Journey({ keyEvents }) {
  if (!keyEvents) return <span className="muted">no key action</span>
  const hot = new Set(['add_to_cart', 'checkout_view', 'pay_started', 'order_placed'])
  return (
    <span className="jchips">
      {keyEvents.split(' > ').map((k) => <span key={k} className={`jchip ${hot.has(k) ? 'hot' : ''}`}>{KEY_LABEL[k] || k}</span>)}
    </span>
  )
}

export function Facts({ rows }) {
  return (
    <dl className="facts">
      {rows.filter(([, v]) => v !== null && v !== undefined && v !== '').map(([k, v]) => <><dt key={`k-${k}`}>{k}</dt><dd key={`v-${k}`}>{v}</dd></>)}
    </dl>
  )
}

export function CopyBtn({ text, title = 'Copy' }) {
  const [done, setDone] = useState(false)
  return (
    <button type="button" className="icon-btn" title={title} aria-label={title}
      onClick={() => { navigator.clipboard?.writeText(text).then(() => { setDone(true); setTimeout(() => setDone(false), 1200) }).catch(() => {}) }}>
      <Icon name={done ? 'check' : 'copy'} size={16} />
    </button>
  )
}

/** Remove this person / browser / IP / phone from the analytics (adds a rule on the Exclusions tab). */
export function ExcludeMenu({ items }) {
  const { exclude, msg } = useQuickExclude()
  const usable = items.filter((i) => i.value)
  return (
    <Popover align="right" width={320} trigger={({ open, toggle }) => (
      <button type="button" className="pill-btn" aria-expanded={open} onClick={toggle}><Icon name="ban" size={18} />Exclude…</button>
    )}>
      <div className="pop-title">Remove from analytics</div>
      {usable.map((i) => (
        <button key={i.label} type="button" className="pop-item" onClick={() => exclude(i.kind, i.value, i.note || 'from profile page')}>
          <span>{i.label}</span><small className="muted mono">{String(i.value).slice(0, 16)}</small>
        </button>
      ))}
      {msg && <div className="muted" style={{ padding: '6px 10px', fontSize: 12 }}>{msg}</div>}
      <div className="pop-sep" />
      <div className="muted" style={{ padding: '2px 10px 6px', fontSize: 12 }}>Editable any time on the Exclusions tab.</div>
    </Popover>
  )
}
