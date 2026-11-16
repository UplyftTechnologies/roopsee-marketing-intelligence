import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
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

/** Selected metric over the period: solid line = this period, dashed = previous period aligned day by day. */
export default function MetricChart({ ts, metric, compare = true, height = 260, ranges, note }) {
  const m = METRICS[metric]
  const cur = ts.current[m.series]
  const prev = compare && ts.previous ? ts.previous[m.series] : null
  const data = ts.dates.map((date, i) => ({ date, cur: cur[i], prev: prev ? prev[i] : null, prevDate: prev ? ts.prev_dates[i] : null }))
  const dots = data.length <= 45
  return (
    <div>
      <div className="chart-legend">
        <span><i /> This period{ranges?.cur ? ` (${ranges.cur})` : ''}</span>
        {prev && <span><i className="dashed" /> Previous period{ranges?.prev ? ` (${ranges.prev})` : ''}</span>}
        {note && <span style={{ color: 'var(--text-muted)' }}>{note}</span>}
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ left: 0, right: 12, top: 8, bottom: 0 }}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis dataKey="date" tickFormatter={day} {...axis} minTickGap={32} />
          <YAxis {...axis} width={m.kind === 'rate' ? 48 : 56} tickFormatter={m.fmt} allowDecimals={false} />
          <Tooltip content={<Tip fmt={m.fmt} hasPrev={!!prev} />} cursor={{ stroke: 'var(--border)' }} />
          {prev && <Line type="monotone" dataKey="prev" stroke="var(--text-muted)" strokeWidth={1.6} strokeDasharray="5 4" dot={false} activeDot={false} isAnimationActive={false} />}
          <Line type="monotone" dataKey="cur" stroke="var(--series-1)" strokeWidth={2.2} dot={dots ? { r: 2.5, fill: 'var(--series-1)', strokeWidth: 0 } : false} activeDot={{ r: 4.5 }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
