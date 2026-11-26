import { num, pct, useApi, useFilters } from '../api'
import { Badge, Card, Table } from '../ui'

const sec = (ms) => (ms == null ? '–' : `${(ms / 1000).toFixed(1)}s`)
const tone = (ms) => (ms == null ? '' : ms > 4000 ? 'bad' : ms > 2500 ? 'warn' : 'good')

/** Page load speed, from the load time the tracker reports on every page load. */
export default function PageSpeed({ linked = true }) {
  const f = useFilters()
  const s = useApi('/performance')
  const d = s.data
  const cols = (first, key) => [
    { label: first, key },
    { label: 'Loads', num: true, sortBy: 'samples', render: (r) => num(r.samples) },
    { label: 'Typical', num: true, sortBy: 'p50', render: (r) => <Badge tone={tone(r.p50)}>{sec(r.p50)}</Badge> },
    { label: 'Slowest 10%', num: true, sortBy: 'p90', render: (r) => <Badge tone={tone(r.p90)}>{sec(r.p90)}</Badge> },
    { label: 'Over 3s', num: true, sortBy: 'slow_share', render: (r) => pct(r.slow_share, 0) },
  ]
  return (
    <Card title="Page speed" sub="how long pages take to load for visitors. Typical = half of loads are faster. Slow pages lose shoppers before they see a product."
      right={linked ? <button type="button" className="btn small" onClick={() => f.go('speed')}>See affected visits →</button> : null}>
      {s.error && <div className="muted">Could not load: {s.error}</div>}
      {!d && !s.error && <div className="skeleton" style={{ height: 160 }} />}
      {d && !d.overall?.samples && <div className="empty">No load-time samples in this date range.</div>}
      {d && d.overall?.samples > 0 && (
        <>
          <div className="chip-row" style={{ marginBottom: 10 }}>
            <Badge tone={tone(d.overall.p50)}>Typical {sec(d.overall.p50)}</Badge>
            <Badge tone={tone(d.overall.p90)}>Slowest 10%: {sec(d.overall.p90)}</Badge>
            <span className="muted">{pct(d.overall.slow_share, 0)} of {num(d.overall.samples)} loads took over 3 seconds</span>
          </div>
          <div className="grid g2">
            <Table rows={d.by_page} cols={cols('Page', 'page')} />
            <Table rows={d.by_device} cols={cols('Device', 'device')} />
          </div>
        </>
      )}
    </Card>
  )
}
