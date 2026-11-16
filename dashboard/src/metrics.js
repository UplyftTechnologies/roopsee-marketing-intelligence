import { inr, num, pct } from './api'

/** One definition per headline metric, shared by scorecards, the chart and the tables.
 *  kpi    = key in /api/overview and /api/insights `kpis`
 *  series = key in /api/timeseries arrays
 *  kind   = 'count' (relative % change) | 'rate' (percentage-point change) */
export const METRICS = {
  sessions: { label: 'Sessions', help: 'sessions', fmt: num, kpi: 'sessions', series: 'sessions', kind: 'count', goodWhen: 'up' },
  people: { label: 'People', help: 'people', fmt: num, kpi: 'people', series: 'people', kind: 'count', goodWhen: 'up' },
  cart_rate: { label: 'Add-to-cart rate', help: 'cartRate', fmt: (v) => pct(v, 1), kpi: 'cart_rate', series: 'cart_rate', kind: 'rate', goodWhen: 'up' },
  orders: { label: 'Orders', help: 'orders', fmt: num, kpi: 'orders', series: 'orders', kind: 'count', goodWhen: 'up' },
  revenue: { label: 'Revenue', help: 'revenue', fmt: inr, kpi: 'revenue', series: 'revenue', kind: 'count', goodWhen: 'up' },
  aov: { label: 'Avg. order value', help: 'aov', fmt: inr, kpi: 'aov', series: 'aov', kind: 'count', goodWhen: 'up' },
  o_orders: { label: 'Orders', help: 'orders', fmt: num, kpi: 'orders', series: 'orders', kind: 'count', goodWhen: 'up' },
  gmv: { label: 'Order value (GMV)', help: 'revenue', fmt: inr, kpi: 'gmv', series: 'gmv', kind: 'count', goodWhen: 'up' },
  o_aov: { label: 'Avg. order value', help: 'aov', fmt: inr, kpi: 'aov', series: 'aov', kind: 'count', goodWhen: 'up' },
  cancelled: { label: 'Payments cancelled', fmt: num, kpi: 'cancelled', series: 'cancelled', kind: 'count', goodWhen: 'down' },
  cod_share: { label: 'Cash on delivery', fmt: (v) => pct(v, 0), kpi: 'cod_share', series: null, kind: 'rate', goodWhen: null },
  repeat_share: { label: 'Repeat-customer orders', fmt: (v) => pct(v, 0), kpi: 'repeat_share', series: null, kind: 'rate', goodWhen: 'up' },
  m_spend: { label: 'Meta spend', fmt: inr, kpi: 'spend', series: 'spend', kind: 'count', goodWhen: null },
  m_clicks: { label: 'Link clicks', fmt: num, kpi: 'link_clicks', series: 'link_clicks', kind: 'count', goodWhen: 'up' },
  m_ctr: { label: 'Click-through rate', fmt: (v) => pct(v, 2), kpi: 'ctr', series: null, kind: 'rate', goodWhen: 'up' },
  m_cpc: { label: 'Cost per click', fmt: (v) => (v == null ? '–' : '₹' + Number(v).toFixed(2)), kpi: 'cpc', series: null, kind: 'count', goodWhen: 'down' },
  m_sessions: { label: 'Tracked sessions', fmt: num, kpi: 'sessions', series: 'sessions', kind: 'count', goodWhen: 'up' },
  m_carts: { label: 'Add-to-carts', fmt: num, kpi: 'carts', series: 'carts', kind: 'count', goodWhen: 'up' },
  bounce_rate: { label: 'Bounce rate', help: 'bounce', fmt: (v) => pct(v, 1), kpi: 'bounce_rate', series: 'bounce_rate', kind: 'rate', goodWhen: 'down' },
}
