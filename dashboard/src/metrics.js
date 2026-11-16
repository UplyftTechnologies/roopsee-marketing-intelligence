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
  bounce_rate: { label: 'Bounce rate', help: 'bounce', fmt: (v) => pct(v, 1), kpi: 'bounce_rate', series: 'bounce_rate', kind: 'rate', goodWhen: 'down' },
}
