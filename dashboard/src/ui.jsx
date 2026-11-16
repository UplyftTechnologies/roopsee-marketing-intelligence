import { useState } from 'react'

export const Card = ({ title, sub, right, children, style }) => (
  <section className="card" style={style}>
    {(title || right) && (
      <div className="card-head">
        <div>
          <h3>{title}</h3>
          {sub && <div className="sub">{sub}</div>}
        </div>
        {right}
      </div>
    )}
    {children}
  </section>
)

export const Kpi = ({ label, value, note }) => (
  <div className="kpi">
    <div className="label">{label}</div>
    <div className="value">{value}</div>
    {note && <div className="note">{note}</div>}
  </div>
)

export const Loading = ({ state, children }) => {
  if (state.error) return <div className="banner err">Could not load: {state.error}</div>
  if (!state.data) return <div className="empty">Loading…</div>
  return children(state.data)
}

export const Badge = ({ tone, children }) => <span className={`badge ${tone || ''}`}>{children}</span>

export const verdictTone = { Winning: 'good', Converting: 'good', Promising: 'warn', 'No carts - review': 'bad', 'Too early': '' }

export function Table({ cols, rows, onRow, empty = 'No data for this selection', rowClass }) {
  if (!rows || !rows.length) return <div className="empty">{empty}</div>
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>{cols.map((c) => <th key={c.key || c.label} className={c.num ? 'num' : ''}>{c.label}</th>)}</tr>
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
