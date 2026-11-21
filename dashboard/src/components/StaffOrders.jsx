import { useState } from 'react'
import { api, dt, inr, num, useApi, useFilters } from '../api'
import { Badge, Card, Loading, Table } from '../ui'

/** Orders placed from accounts with a staff role (admin / rider / doctor): count them as real sales account by account. */
export default function StaffOrders({ exclusions }) {
  const f = useFilters()
  const s = useApi('/staff-orders', {}, { scoped: false })
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState('')
  const toggle = async (a) => {
    setBusy(a.user_id)
    setErr('')
    try {
      if (a.real_customer) {
        const row = (exclusions || []).find((r) => r.kind === 'real_customer' && String(r.value).toLowerCase() === String(a.user_id).toLowerCase())
        if (row) await api(`/exclusions/${row.id}`, { method: 'DELETE' })
      } else {
        await api('/exclusions', { method: 'POST', body: { kind: 'real_customer', value: a.user_id, note: `staff account, real customer orders (${a.name || a.phone10 || 'no name'})` } })
      }
      f.bump()
      f.reloadMeta()
    } catch (e) {
      setErr(e.message)
    }
    setBusy('')
  }
  return (
    <Loading state={s}>
      {(d) => {
        if (!d.accounts.length) return null
        const t = d.totals
        return (
          <Card title="Orders from staff accounts" sub={`${num(t.orders)} orders worth ${inr(t.revenue)} come from accounts with a staff role. ${d.rule_on ? `Counted as sales: ${num(t.counted_orders)} orders (${inr(t.counted_revenue)}). The rest are hidden as internal.` : 'The staff-orders rule is off, so all of them are counted.'}`}>
            <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
              Tick <b>Real customer</b> for an account whose orders are genuine sales (a customer using an admin login, an owner ordering for a customer). Its orders then count everywhere (revenue, Orders, Basket, Campaigns); its visits stay hidden.
              “Looks real” means most of its orders were shipped or delivered and at least one payment is confirmed.
            </div>
            {err && <div className="banner err">{err}</div>}
            <Table rows={d.accounts} empty="No staff-account orders." cols={[
              { label: 'Real customer', cls: 'nw', render: (a) => (
                <label className="toggle"><input type="checkbox" checked={a.real_customer || (!d.rule_on)} disabled={busy === a.user_id || !d.rule_on} onChange={() => toggle(a)} /> {a.counted ? 'counted' : 'hidden'}</label>
              ) },
              { label: 'Account', render: (a) => <span><b>{a.name || 'No name'}</b> <span className="muted">{a.role}</span>{a.phone10 ? <span className="mono muted"> · {a.phone10}</span> : null}</span> },
              { label: 'Orders', num: true, sortBy: 'orders', render: (a) => num(a.orders) },
              { label: 'Revenue', num: true, sortBy: 'revenue', render: (a) => inr(a.revenue) },
              { label: 'Shipped', num: true, render: (a) => `${a.shipped} of ${a.orders}` },
              { label: 'Paid', num: true, render: (a) => `${a.paid} of ${a.orders}` },
              { label: 'COD', num: true, render: (a) => num(a.cod) },
              { label: 'Last order', cls: 'nw', sortBy: 'last_order', render: (a) => dt(a.last_order) },
              { label: '', render: (a) => (a.looks_real ? <Badge tone="good">looks real</Badge> : null) },
            ]} />
          </Card>
        )
      }}
    </Loading>
  )
}
