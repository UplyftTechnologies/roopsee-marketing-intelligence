import { useState } from 'react'

/* ---------- metric glossary: shown as hover/focus help next to labels ---------- */
export const GLOSSARY = {
  sessions: 'One visit to the site or app (a unique session id). One person can have several sessions.',
  browsers: 'Distinct devices/browsers (visitor ids). Someone using phone and laptop counts twice here.',
  people: 'Distinct accounts, or anonymous browsers that never logged in. Browsers are merged into an account once the person logs in.',
  orders: 'Valid orders only: not cancelled / payment pending, not a ₹1 test order, and not excluded.',
  revenue: 'Order totals of valid, non-excluded orders (after discounts, before refunds).',
  aov: 'Average order value = revenue ÷ orders.',
  cart: 'Sessions where something was added to the cart.',
  cartRate: 'Share of sessions that added something to the cart.',
  checkout: 'Sessions that opened the checkout page.',
  quiz: 'Sessions that finished the skin quiz. Older tracking logged completions without a start event, so completions can exceed starts.',
  bounce: 'Sessions with at most one page view and no clicks, scrolls, searches or other actions: the visitor landed and left.',
  avgSession: 'Average length of sessions that lasted more than 0 seconds.',
  firstTouch: 'Credits an order to the very first visit of the buyer (the campaign that brought them), not just the session where they paid.',
  engaged: 'Sessions with 5+ events or a product view.',
  segment: 'Where a person is in the journey: Buyer, Abandoned checkout, Cart no checkout, Quiz done, Engaged browser or Visitor.',
}

export const Help = ({ id, text }) => (
  <span className="help" tabIndex={0} data-tip={text || GLOSSARY[id]} aria-label={text || GLOSSARY[id]}>ⓘ</span>
)

export const Card = ({ title, sub, right, children, style, help }) => (
  <section className="card" style={style}>
    {(title || right) && (
      <div className="card-head">
        <div>
          <h3>{title}{help && <> <Help id={help} /></>}</h3>
          {sub && <div className="sub">{sub}</div>}
        </div>
        {right}
      </div>
    )}
    {children}
  </section>
)

/** Change vs the previous period. kind 'count' → relative %, 'rate' → percentage-point difference. */
export function delta(cur, prev, kind = 'count') {
  if (prev === null || prev === undefined || cur === null || cur === undefined) return null
  if (kind === 'rate') {
    const d = (cur - prev) * 100
    if (Math.abs(d) < 0.05) return { dir: 0, text: 'no change' }
    return { dir: d > 0 ? 1 : -1, text: `${d > 0 ? '+' : ''}${d.toFixed(1)} pts` }
  }
  if (!prev) return cur ? { dir: 1, text: 'new' } : null
  const c = ((cur - prev) / prev) * 100
  if (Math.abs(c) < 0.5) return { dir: 0, text: 'no change' }
  return { dir: c > 0 ? 1 : -1, text: `${c > 0 ? '+' : ''}${Math.abs(c) >= 100 ? c.toFixed(0) : c.toFixed(1)}%` }
}

export const Delta = ({ d, goodWhen = 'up' }) => {
  if (!d) return null
  const good = d.dir === 0 ? null : (d.dir > 0) === (goodWhen === 'up')
  const arrow = d.dir > 0 ? '▲' : d.dir < 0 ? '▼' : '■'
  return (
    <span className="delta" title="Compared with the previous period of the same length">
      <span className={good === null ? '' : good ? 'ok' : 'bad'}>{arrow}</span> {d.text}
    </span>
  )
}

export const Kpi = ({ label, value, note, help, d, goodWhen, big }) => (
  <div className={`kpi ${big ? 'big' : ''}`}>
    <div className="label">{label}{help && <> <Help id={help} /></>}</div>
    <div className="value">{value}</div>
    <div className="note">{d ? <><Delta d={d} goodWhen={goodWhen} /> <span className="muted">vs previous</span></> : null}{d && note ? ' · ' : ''}{note}</div>
  </div>
)

export const Skeleton = () => (
  <div className="skeleton-wrap" aria-busy="true" aria-label="Loading">
    <div className="skeleton-row">{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton" style={{ height: 84 }} />)}</div>
    <div className="skeleton" style={{ height: 260 }} />
    <div className="skeleton" style={{ height: 180 }} />
  </div>
)

export const Loading = ({ state, children }) => {
  if (state.error) return <div className="banner err">Could not load: {state.error}</div>
  if (!state.data) return <Skeleton />
  return children(state.data)
}

export const Badge = ({ tone, children }) => <span className={`badge ${tone || ''}`}>{children}</span>

export const verdictTone = { Winning: 'good', Converting: 'good', Promising: 'warn', 'No carts - review': 'bad', 'Too early': '' }

export function Table({ cols, rows, onRow, empty = 'Nothing here for this selection. Try a wider date range or turn off “Hide internal & bot traffic”.', rowClass }) {
  if (!rows || !rows.length) return <div className="empty">{empty}</div>
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>{cols.map((c) => <th key={c.key || c.label} className={c.num ? 'num' : ''}>{c.label}{c.help && <> <Help id={c.help} /></>}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={`${onRow ? 'click' : ''} ${rowClass ? rowClass(r) : ''}`} onClick={onRow ? () => onRow(r) : undefined}>
              {cols.map((c) => (
                <td key={c.key || c.label} className={`${c.num ? 'num' : ''} ${c.cls || ''}`}>
                  {c.render ? c.render(r) : r[c.key] ?? '–'}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Download the rows as CSV. fields = [[header, key | fn(row)], ...] */
export function ExportBtn({ rows, fields, name }) {
  if (!rows || !rows.length) return null
  const go = () => {
    const esc = (v) => (v === null || v === undefined ? '' : `"${String(v).replace(/"/g, '""')}"`)
    const lines = [fields.map(([h]) => esc(h)).join(',')]
    rows.forEach((r) => lines.push(fields.map(([, k]) => esc(typeof k === 'function' ? k(r) : r[k])).join(',')))
    const url = URL.createObjectURL(new Blob(['﻿' + lines.join('\n')], { type: 'text/csv;charset=utf-8' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `${name}-${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }
  return <button className="btn small" onClick={go} title="Download these rows as a CSV file">Export CSV</button>
}

/** Horizontal rate bar used inside table cells (single hue, thin, anchored left). */
export const RateBar = ({ v, max = 1, text }) => (
  <span>
    <span className="inline-bar" style={{ width: Math.max(1, Math.min(1, v / (max || 1)) * 70) }} />
    {text}
  </span>
)

export function Pager({ total, limit, offset, setOffset }) {
  if (!total) return null
  return (
    <div className="pager">
      <span>{offset + 1}–{Math.min(offset + limit, total)} of {total.toLocaleString('en-IN')}</span>
      <button className="btn small" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>Prev</button>
      <button className="btn small" disabled={offset + limit >= total} onClick={() => setOffset(offset + limit)}>Next</button>
    </div>
  )
}

export function Chips({ options, value, onChange }) {
  return (
    <div className="chip-row">
      {options.map((o) => {
        const v = typeof o === 'string' ? o : o.value
        const l = typeof o === 'string' ? o : o.label
        return <button key={v} className={`chip ${value === v ? 'on' : ''}`} onClick={() => onChange(v)}>{l}</button>
      })}
    </div>
  )
}

/** Debounced search box. */
export function Search({ value, onChange, placeholder }) {
  const [v, setV] = useState(value || '')
  return (
    <input className="field" style={{ minWidth: 260 }} placeholder={placeholder} value={v}
      onChange={(e) => { setV(e.target.value); clearTimeout(Search.t); Search.t = setTimeout(() => onChange(e.target.value), 350) }} />
  )
}

export const chartTip = {
  contentStyle: { background: 'var(--surface-1)', border: '1px solid var(--border)', borderRadius: 8, color: 'var(--text-primary)', fontSize: 12 },
  labelStyle: { color: 'var(--text-secondary)' },
  itemStyle: { color: 'var(--text-primary)' },
  cursor: { fill: 'var(--surface-2)', opacity: 0.6 },
}
export const axis = { stroke: 'var(--grid)', tick: { fill: 'var(--text-muted)', fontSize: 11 }, tickLine: false }
export const SERIES = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)', 'var(--series-4)', 'var(--series-5)', 'var(--series-6)', 'var(--series-7)', 'var(--series-8)']
export const Legend = ({ items }) => (
  <div className="legend">{items.map(([label, color]) => <span key={label}><i style={{ background: color }} />{label}</span>)}</div>
)
