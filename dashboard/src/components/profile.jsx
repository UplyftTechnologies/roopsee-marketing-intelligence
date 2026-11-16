import { useState } from 'react'
import { KEY_LABEL, tod } from '../api'
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
export function SessionTimeline({ events, max = 400 }) {
  const [keyOnly, setKeyOnly] = useState(false)
  if (!events || !events.length) return <div className="empty">No events recorded</div>
  const t0 = new Date(events[0].at).getTime()
  const rows = []
  for (const e of events) {
    if (keyOnly && !e.event_key) continue
    const last = rows[rows.length - 1]
    if (last && !e.event_key && last.e.event_name === e.event_name && last.e.path === e.path) last.n += 1
    else rows.push({ e, n: 1 })
  }
  return (
    <div>
      <div className="tl-tools">
        <label className="toggle"><input type="checkbox" checked={keyOnly} onChange={(e) => setKeyOnly(e.target.checked)} /> Key actions only</label>
        <span className="muted">{events.length} events{rows.length !== events.length && !keyOnly ? ` · ${rows.length} steps (repeats grouped)` : ''}</span>
      </div>
      <div className="timeline">
        {rows.slice(0, max).map(({ e, n }, i) => {
          const detail = [pretty(e.path), e.product_name && `· ${e.product_name}`, e.amount ? `· ₹${e.amount}` : null, e.search_term && `· “${e.search_term}”`].filter(Boolean).join(' ')
          return (
            <div key={i} className={`tl-item ${e.event_key ? 'key' : ''}`}>
              <span className="tl-time">{tod(e.at)} <small>{offset(Math.max(0, Math.round((new Date(e.at).getTime() - t0) / 1000)))}</small></span>
              <b>{label(e)}</b>{n > 1 && <span className="muted"> ×{n}</span>} <span className="muted">{detail}</span>
            </div>
          )
        })}
      </div>
      {rows.length > max && <div className="muted" style={{ marginTop: 6 }}>Showing the first {max} of {rows.length} steps.</div>}
    </div>
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
