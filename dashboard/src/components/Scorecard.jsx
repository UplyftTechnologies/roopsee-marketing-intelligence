import { Delta, GLOSSARY, delta } from '../ui'
import { METRICS } from '../metrics'

/** Tiny trend line: no axes, just shape. Draws the last point as a dot. */
export function Sparkline({ values, w = 84, h = 28 }) {
  if (!values || values.length < 2) return <span style={{ width: w, height: h }} />
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const pts = values.map((v, i) => [(i / (values.length - 1)) * (w - 4) + 2, h - 3 - ((v - min) / span) * (h - 6)])
  const last = pts[pts.length - 1]
  return (
    <svg className="spark" width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Trend over the selected period">
      <polyline points={pts.map((p) => p.join(',')).join(' ')} fill="none" stroke="var(--series-1)" strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={last[0]} cy={last[1]} r="2.2" fill="var(--series-1)" />
    </svg>
  )
}

/** One tile of the strip. Clicking selects the metric shown in the chart below. */
export function Scorecard({ metric, kpis, prev, spark, active, onClick, compare = true, note }) {
  const m = METRICS[metric]
  const d = compare && prev ? delta(kpis[m.kpi], prev[m.kpi], m.kind) : null
  return (
    <button type="button" className={`sc ${active ? 'active' : ''}`} onClick={onClick} aria-pressed={active}>
      <span className="sc-label" title={GLOSSARY[m.help]}>{m.label}</span>
      <span className="sc-value">{m.fmt(kpis[m.kpi])}</span>
      <span className="sc-foot">
        <span>{d ? <Delta d={d} goodWhen={m.goodWhen} /> : <span className="sc-note">{note || ' '}</span>}</span>
        <Sparkline values={spark} />
      </span>
    </button>
  )
}

export const ScorecardStrip = ({ children }) => <div className="scorecards" role="group" aria-label="Key metrics">{children}</div>
