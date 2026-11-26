import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { day } from '../api'
import { METRICS } from '../metrics'
import { axis } from '../ui'

function Tip({ active, payload, fmt, hasPrev }) {
  if (!active || !payload || !payload.length) return null
  const p = payload[0].payload
  return (
    <div className="tip">
      <div className="tip-row"><span>{day(p.date)}</span><b>{fmt(p.cur)}</b></div>
      {hasPrev && p.prevDate && <div className="tip-row" style={{ color: 'var(--text-muted)' }}><span>{day(p.prevDate)}</span><span>{fmt(p.prev)}</span></div>}
    </div>
  )
}

const readType = () => { try { return localStorage.getItem('chart-type') === 'line' ? 'line' : 'bar' } catch { return 'bar' } }

/** Selected metric over the period. Bars (default) or a line; the previous period is drawn alongside, day by day.
 *  The choice is remembered for every chart. */
export default function MetricChart({ ts, metric, compare = true, height = 260, ranges, note }) {
  const [type, setType] = useState(readType)
  const choose = (t) => { setType(t); try { localStorage.setItem('chart-type', t) } catch { /* ignore */ } }
  const m = METRICS[metric]
  const cur = ts.current[m.series]
  const prev = compare && ts.previous ? ts.previous[m.series] : null
  const data = ts.dates.map((date, i) => ({ date, cur: cur[i], prev: prev ? prev[i] : null, prevDate: prev ? ts.prev_dates[i] : null }))
  const dots = data.length <= 45
  const bars = type === 'bar'
  const common = { data, margin: { left: 0, right: 12, top: 8, bottom: 0 } }
  const axes = (
    <>
      <CartesianGrid stroke="var(--grid)" vertical={false} />
      <XAxis dataKey="date" tickFormatter={day} {...axis} minTickGap={32} />
      <YAxis {...axis} width={m.kind === 'rate' ? 48 : 56} tickFormatter={m.fmt} allowDecimals={m.kind === 'rate'} />
    </>
  )
  return (
    <div>
      <div className="chart-legend">
        <span><i className={bars ? 'sq' : ''} /> This period{ranges?.cur ? ` (${ranges.cur})` : ''}</span>
        {prev && <span><i className={bars ? 'sq prev' : 'dashed'} /> Previous period{ranges?.prev ? ` (${ranges.prev})` : ''}</span>}
        {note && <span style={{ color: 'var(--text-muted)' }}>{note}</span>}
        <span className="seg" role="group" aria-label="Chart type" style={{ marginLeft: 'auto' }}>
          <button type="button" className={bars ? 'on' : ''} aria-pressed={bars} onClick={() => choose('bar')}>Bars</button>
          <button type="button" className={!bars ? 'on' : ''} aria-pressed={!bars} onClick={() => choose('line')}>Line</button>
        </span>
      </div>
      <ResponsiveContainer width="100%" height={height}>
        {bars ? (
          <BarChart {...common} barGap={1} barCategoryGap="22%">
            {axes}
            <Tooltip content={<Tip fmt={m.fmt} hasPrev={!!prev} />} cursor={{ fill: 'var(--surface-2)', opacity: 0.7 }} />
            {prev && <Bar dataKey="prev" fill="var(--text-muted)" fillOpacity={0.45} radius={[2, 2, 0, 0]} maxBarSize={18} isAnimationActive={false} />}
            <Bar dataKey="cur" fill="var(--series-1)" radius={[3, 3, 0, 0]} maxBarSize={22} isAnimationActive={false} />
          </BarChart>
        ) : (
          <LineChart {...common}>
            {axes}
            <Tooltip content={<Tip fmt={m.fmt} hasPrev={!!prev} />} cursor={{ stroke: 'var(--border)' }} />
            {prev && <Line type="monotone" dataKey="prev" stroke="var(--text-muted)" strokeWidth={1.6} strokeDasharray="5 4" dot={false} activeDot={false} isAnimationActive={false} />}
            <Line type="monotone" dataKey="cur" stroke="var(--series-1)" strokeWidth={2.2} dot={dots ? { r: 2.5, fill: 'var(--series-1)', strokeWidth: 0 } : false} activeDot={{ r: 4.5 }} isAnimationActive={false} />
          </LineChart>
        )}
      </ResponsiveContainer>
    </div>
  )
}
