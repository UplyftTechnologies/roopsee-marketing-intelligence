import { inr, num } from '../api'
import { useFilters } from '../api'

/** How much of the revenue is actually paid: confirmed, cash on delivery still to be collected, and sales with no confirmed payment. */
export function RevenueSplit({ kpis }) {
  const f = useFilters()
  if (!kpis || kpis.revenue_confirmed === undefined || !kpis.revenue) return null
  const parts = [['paid (confirmed)', kpis.revenue_confirmed, 'good'], ['cash on delivery, not collected yet', kpis.revenue_cod_pending, ''], ['no confirmed payment', kpis.revenue_unconfirmed, 'warn']]
  return (
    <div className="banner" role="note" style={{ gap: 14 }}>
      <div>
        <b>Of {inr(kpis.revenue)} revenue:</b>{' '}
        {parts.filter(([, v]) => v > 0).map(([label, v], i) => <span key={label}>{i > 0 ? ' · ' : ''}<b>{inr(v)}</b> <span className="muted">{label}</span></span>)}
        <div className="muted" style={{ fontSize: 12 }}>Every valid sale counts as revenue when it is placed. Use <b>Sales counted</b> at the top to see only paid sales.</div>
      </div>
      <div className="spacer" />
      <button type="button" className="btn small" onClick={() => f.go('orders')}>Open Orders →</button>
    </div>
  )
}

/** Sales by customers that have no person in the lists below (orders before tracking began, or never linked to a visit). */
export function UntrackedNote({ untracked }) {
  const f = useFilters()
  if (!untracked || (!untracked.orders && !untracked.hidden_orders)) return null
  const total = untracked.revenue + (untracked.hidden_revenue || 0)
  return (
    <div className="banner" role="note">
      <div>
        <b>{inr(total)} of revenue is not in the revenue of this list.</b>{' '}
        <span className="muted">
          {untracked.orders > 0 && <>{inr(untracked.revenue)} from {num(untracked.customers)} customer{untracked.customers === 1 ? '' : 's'} ({num(untracked.orders)} order{untracked.orders === 1 ? '' : 's'}) with no tracked visit
            {untracked.before_tracking ? ` (${num(untracked.before_tracking)} placed before tracking began)` : ''}, so they cannot appear as a person. </>}
          {untracked.hidden_orders > 0 && <>{inr(untracked.hidden_revenue)} from {num(untracked.hidden_orders)} order{untracked.hidden_orders === 1 ? '' : 's'} by people whose visits are hidden (a foreign address or a browser shared with staff): the sale counts, the person is hidden. </>}
          All of it is in Orders, Overview and Retention &amp; LTV (all time).
        </span>
      </div>
      <div className="spacer" />
      <button type="button" className="btn small" onClick={() => f.go('orders')}>Open Orders →</button>
    </div>
  )
}
