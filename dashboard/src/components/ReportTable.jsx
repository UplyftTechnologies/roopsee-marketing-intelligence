import { useEffect, useState } from 'react'
import { dur, inr, num, pct, useApi, useFilters } from '../api'
import { Card, ExportBtn, GLOSSARY, Search } from '../ui'
import Icon from './Icon'

const DIMENSIONS = [['channel', 'Channel'], ['source_medium', 'Source / medium'], ['campaign', 'Campaign'], ['device', 'Device'],
  ['landing', 'Landing page'], ['state', 'State'], ['city', 'City']]
// Clicking a row opens the Sessions tab filtered to it (only where Sessions can filter on that dimension)
const DRILL = { channel: (v) => ({ channel: v }), campaign: (v) => ({ search: v === '(not set)' ? '' : v }), city: (v) => ({ search: v }), state: (v) => ({ search: v }) }

const COLS = [
  ['sessions', 'Sessions', 'sessions', (r, max) => (
    <><span className="rt-bar" style={{ width: Math.max(1, (r.sessions / (max || 1)) * 64) }} />{num(r.sessions)}</>)],
  ['people', 'People', 'people', (r) => num(r.people)],
  ['cart_rate', 'Add-to-cart rate', 'cartRate', (r) => pct(r.cart_rate, 1)],
  ['checkouts', 'Checkouts', 'checkout', (r) => num(r.checkouts)],
  ['orders', 'Orders', 'orders', (r) => num(r.orders)],
  ['revenue', 'Revenue', 'revenue', (r) => inr(r.revenue)],
  ['bounce_rate', 'Bounce rate', 'bounce', (r) => pct(r.bounce_rate, 1)],
  ['avg_duration', 'Avg. time', 'avgSession', (r) => dur(r.avg_duration)],
]

/** Google-Analytics-style report: dimension picker, search, sortable columns, totals row, pagination. */
export default function ReportTable({ title = 'Traffic', sub, defaultDimension = 'channel', dimensions = DIMENSIONS }) {
  const f = useFilters()
  const [dimension, setDimension] = useState(defaultDimension)
  const [sort, setSort] = useState('sessions')
  const [direction, setDirection] = useState('desc')
  const [search, setSearch] = useState('')
  const [limit, setLimit] = useState(10)
  const [offset, setOffset] = useState(0)
  const [minSessions, setMinSessions] = useState(1)
  useEffect(() => setOffset(0), [dimension, sort, direction, search, limit, minSessions])
  const s = useApi('/report', { dimension, sort, direction, search: search || undefined, limit, offset, min_sessions: minSessions })
  const d = s.data
  const dimLabel = dimensions.find((x) => x[0] === dimension)?.[1] || ''
  const onHead = (key) => { if (sort === key) setDirection(direction === 'desc' ? 'asc' : 'desc'); else { setSort(key); setDirection(key === 'dim' ? 'asc' : 'desc') } }
  const arrow = (key) => (sort === key ? <span className="arrow">{direction === 'desc' ? '▼' : '▲'}</span> : null)
  const drill = DRILL[dimension]
  const max = d ? Math.max(1, ...d.rows.map((r) => r.sessions)) : 1
  const exportFields = [[dimLabel, 'dim'], ...COLS.map(([k, label]) => [label, k])]

  return (
    <Card title={title} sub={sub} right={d ? <ExportBtn name={`report-${dimension}`} rows={d.rows} fields={exportFields} /> : null}>
      <div className="rt-toolbar">
        <label className="muted" style={{ fontSize: 12 }}>Group by{' '}
          <select className="field" value={dimension} onChange={(e) => setDimension(e.target.value)}>{dimensions.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
        </label>
        <span className="spacer" />
        <label className="muted" style={{ fontSize: 12 }} title="Hide rows with very few sessions, so rates are not dominated by tiny samples">Min. sessions{' '}
          <select className="field" value={minSessions} onChange={(e) => setMinSessions(+e.target.value)}>{[1, 10, 50, 100].map((n) => <option key={n} value={n}>{n}</option>)}</select>
        </label>
        <Search value={search} onChange={setSearch} placeholder={`Search ${dimLabel.toLowerCase()}…`} />
      </div>
      {s.error && <div className="banner err">Could not load: {s.error}</div>}
      {!d && !s.error && <div className="skeleton" style={{ height: 260 }} />}
      {d && (
        <>
          <div className="table-wrap">
            <table className="rt">
              <thead>
                <tr>
                  <th className={`sortable ${sort === 'dim' ? 'sorted' : ''}`} onClick={() => onHead('dim')}>{dimLabel}{arrow('dim')}</th>
                  {COLS.map(([k, label, help]) => (
                    <th key={k} className={`num sortable ${sort === k ? 'sorted' : ''}`} onClick={() => onHead(k)} title={GLOSSARY[help]}>{label}{arrow(k)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {d.totals && (
                  <tr className="total">
                    <td>Total</td>{COLS.map(([k, , , cell]) => <td key={k} className="num">{k === 'sessions' ? num(d.totals.sessions) : cell(d.totals, max)}</td>)}
                  </tr>
                )}
                {d.rows.length === 0 && <tr><td colSpan={COLS.length + 1}><div className="empty">No rows match. Try a wider date range, a lower minimum, or clear the search.</div></td></tr>}
                {d.rows.map((r) => (
                  <tr key={r.dim} className={drill ? 'click' : ''} onClick={drill ? () => f.go('sessions', drill(r.dim)) : undefined} title={drill ? 'Open these sessions' : undefined}>
                    <td className="dimcell" title={r.dim}>{r.dim}</td>
                    {COLS.map(([k, , , cell]) => <td key={k} className="num">{cell(r, max)}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="rt-foot">
            <span>Rows per page{' '}<select className="field" value={limit} onChange={(e) => setLimit(+e.target.value)}>{[10, 25, 50, 100, 5000].map((n) => <option key={n} value={n}>{n === 5000 ? 'All' : n}</option>)}</select></span>
            <span>{d.groups ? `${offset + 1}–${Math.min(offset + limit, d.groups)} of ${num(d.groups)}` : '0 of 0'}</span>
            <span>
              <button className="icon-btn" aria-label="Previous page" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}><Icon name="left" size={18} /></button>
              <button className="icon-btn" aria-label="Next page" disabled={offset + limit >= d.groups} onClick={() => setOffset(offset + limit)}><Icon name="right" size={18} /></button>
            </span>
          </div>
        </>
      )}
    </Card>
  )
}
