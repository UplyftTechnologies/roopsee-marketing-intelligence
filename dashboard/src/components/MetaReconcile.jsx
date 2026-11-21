import { inr, num, useApi } from '../api'
import { Card, Table } from '../ui'

/** Meta's own purchase numbers next to what your site recorded for Paid Meta traffic, with the likely reasons for any gap. */
export default function MetaReconcile() {
  const s = useApi('/meta/reconcile')
  const d = s.data
  if (s.error || !d || !d.connected) return null
  const t = d.totals
  return (
    <Card title="Meta says vs your site says" sub="the same period, counted two ways. Differences are normal, but a big gap means one of the two is losing orders">
      <div className="grid g2">
        <div className="sc static" style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12 }}>
          <span className="sc-label">Meta reports</span>
          <div style={{ fontSize: 13, marginTop: 4 }}>
            <b>{num(t.meta_purchases)}</b> purchases · <b>{inr(t.meta_value)}</b> value<br />
            <b>{num(t.meta_clicks)}</b> link clicks · <b>{inr(t.spend)}</b> spent
          </div>
        </div>
        <div className="sc static" style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12 }}>
          <span className="sc-label">Your site recorded</span>
          <div style={{ fontSize: 13, marginTop: 4 }}>
            <b>{num(t.site_orders)}</b> orders credited to Paid Meta · <b>{inr(t.site_revenue)}</b><br />
            <b>{num(t.site_visits)}</b> visits from Paid Meta
          </div>
        </div>
      </div>
      {d.notes.map((n) => <div key={n.slice(0, 40)} className="muted" style={{ fontSize: 13, marginTop: 8 }}>{n}</div>)}
      <details style={{ marginTop: 10 }}>
        <summary className="muted" style={{ cursor: 'pointer', fontSize: 12 }}>Day by day</summary>
        <Table rows={[...d.rows].reverse()} cols={[
          { label: 'Day', cls: 'nw', render: (r) => r.date },
          { label: 'Spend', num: true, render: (r) => inr(r.spend) },
          { label: 'Meta clicks', num: true, render: (r) => num(r.meta_clicks) },
          { label: 'Site visits', num: true, render: (r) => num(r.site_visits) },
          { label: 'Meta purchases', num: true, render: (r) => num(r.meta_purchases) },
          { label: 'Site orders', num: true, render: (r) => num(r.site_orders) },
        ]} />
      </details>
    </Card>
  )
}
