import { Fragment, useState } from 'react'
import { inr, num, useApi, useFilters } from '../api'
import { Card, Loading } from '../ui'
import { METRICS } from '../metrics'
import { Scorecard, ScorecardStrip } from '../components/Scorecard'
import MetricChart from '../components/LazyMetricChart'
import ReportTable from '../components/ReportTable'
import PageSpeed from '../components/PageSpeed'
import { RevenueSplit } from '../components/RevenueNotes'

const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const RAMP = ['var(--seq-100)', 'var(--seq-200)', 'var(--seq-300)', 'var(--seq-400)', 'var(--seq-500)', 'var(--seq-600)']
const CARDS = ['sessions', 'people', 'cart_rate', 'orders', 'revenue', 'aov']

export function Heatmap({ hours, unit = 'sessions' }) {
  const m = {}
  let max = 0
  hours.forEach((h) => { m[`${h.dow}-${h.hour}`] = h.sessions; max = Math.max(max, h.sessions) })
  return (
    <div>
      <div className="heat">
        <span />
        {Array.from({ length: 24 }, (_, h) => <span key={h} style={{ textAlign: 'center' }}>{h % 3 === 0 ? h : ''}</span>)}
        {DOW.map((d, di) => (
          <Fragment key={d}>
            <span className="lab">{d}</span>
            {Array.from({ length: 24 }, (_, h) => {
              const v = m[`${di}-${h}`] || 0
              const step = v ? Math.min(5, Math.floor((v / max) * 5.999)) : -1
              return <span key={h} className="cell" title={`${d} ${h}:00 – ${num(v)} ${unit}`} style={step >= 0 ? { background: RAMP[step] } : undefined} />
            })}
          </Fragment>
        ))}
      </div>
      <div className="legend">{unit === 'orders' ? 'Orders' : 'Sessions'} by hour of day (IST) · lighter = fewer, darker = more · peak {num(max)} in one hour</div>
    </div>
  )
}

export default function Overview() {
  const f = useFilters()
  const ov = useApi('/overview')
  const ts = useApi('/timeseries')
  const [metric, setMetric] = useState('sessions')
  return (
    <Loading state={ov}>
      {({ kpis, prev, hours, staff_orders: so }) => (
        <>
          {so.orders > 0 && (
            <div className={`banner ${so.excluded ? '' : 'ok'}`}>
              <div>
                <b>{num(so.orders)} orders ({inr(so.revenue)}) came from admin / staff accounts</b> in this range.{' '}
                {so.excluded ? 'They are excluded from every number here as team / test orders.' : 'They are counted as real customer orders.'}
                <div className="muted">Team keying in real customer orders? Turn off the <span className="mono">staff_orders</span> rule in Exclusions to count them.</div>
              </div>
            </div>
          )}
          <ScorecardStrip>
            {CARDS.map((k) => (
              <Scorecard key={k} metric={k} kpis={kpis} prev={prev} compare={f.compare} spark={ts.data?.current[METRICS[k].series]} active={metric === k} onClick={() => setMetric(k)} />
            ))}
          </ScorecardStrip>
          <RevenueSplit kpis={kpis} />
          <Card title={METRICS[metric].label} sub="Click a tile above to change the chart">
            {ts.data ? <MetricChart ts={ts.data} metric={metric} compare={f.compare} ranges={{ cur: f.rangeText, prev: f.prevText }} note={(!f.to || f.to === f.meta?.range?.last) ? 'The latest day may be incomplete' : undefined} /> : <div className="skeleton" style={{ height: 280 }} />}
          </Card>
          <ReportTable title="Where traffic comes from" sub="Group by channel, campaign, device, place… Click a row to see its sessions." />
          <Card title="When people visit"><Heatmap hours={hours} /></Card>
          <PageSpeed />
          <div className="muted" style={{ fontSize: 12 }}>
            Scorecards and the chart use the order date; the table credits an order to the session it was placed in, so the two can differ slightly.
          </div>
        </>
      )}
    </Loading>
  )
}
