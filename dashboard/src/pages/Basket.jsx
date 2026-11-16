import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { inr, num, pct, useApi } from '../api'
import { Card, Chips, ExportBtn, Kpi, Loading, Table, axis, chartTip } from '../ui'

export default function Basket() {
  const [threshold, setThreshold] = useState(499)
  const s = useApi('/basket', { threshold })
  return (
    <Loading state={s}>
      {(d) => {
        const k = d.kpis
        const uplift = k.aov_single ? k.aov_multi / k.aov_single - 1 : null
        const t = d.threshold
        const o = t.orders
        return (
          <>
            <div className="kpis">
              <Kpi label="Orders" help="orders" value={num(k.orders)} note={`${inr(k.revenue)} revenue`} />
              <Kpi label="Average order value" help="aov" value={inr(k.aov)} note={`median ${inr(k.median_aov)}`} />
              <Kpi label="Items per order" value={k.items_per_order.toFixed(2)} note={`${num(k.single_item_orders)} orders (${pct(k.single_item_orders / (k.orders || 1), 0)}) have just one item`} />
              <Kpi label="2+ items vs 1 item" value={uplift === null ? '–' : `${uplift >= 0 ? '+' : ''}${(uplift * 100).toFixed(0)}%`} note={`${inr(k.aov_multi)} vs ${inr(k.aov_single)} per order`} />
            </div>

            <div className="grid g2">
              <Card title="Order value by basket size" sub="average order value for orders with 1, 2, 3 or 4+ items">
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={d.by_size} margin={{ left: -4, right: 8 }}>
                    <CartesianGrid stroke="var(--grid)" vertical={false} />
                    <XAxis dataKey="items" {...axis} tickFormatter={(v) => `${v} item${v === '1' ? '' : 's'}`} />
                    <YAxis {...axis} width={54} tickFormatter={inr} />
                    <Tooltip {...chartTip} formatter={(v, n, p) => [`${inr(v)} (${p.payload.orders} orders)`, 'Average order']} labelFormatter={(l) => `${l} item${l === '1' ? '' : 's'}`} />
                    <Bar dataKey="aov" fill="var(--series-1)" radius={[4, 4, 0, 0]} maxBarSize={44} isAnimationActive={false} />
                  </BarChart>
                </ResponsiveContainer>
              </Card>
              <Card title="Orders by basket value" sub="value of products before delivery and discounts">
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={d.bands.map((b) => ({ ...b, label: b.band.slice(3) }))} margin={{ left: -10, right: 8 }}>
                    <CartesianGrid stroke="var(--grid)" vertical={false} />
                    <XAxis dataKey="label" {...axis} />
                    <YAxis {...axis} width={40} allowDecimals={false} />
                    <Tooltip {...chartTip} formatter={(v, n, p) => [`${v} orders, ${inr(p.payload.revenue)}`, 'Orders']} />
                    <Bar dataKey="orders" fill="var(--series-1)" radius={[4, 4, 0, 0]} maxBarSize={44} isAnimationActive={false} />
                  </BarChart>
                </ResponsiveContainer>
              </Card>
            </div>

            <Card title="Offer / free-delivery threshold lab" sub="Pick a basket value and see how many orders and abandoned carts sit just below it. This is a what-if on basket value, not your actual delivery rule."
              right={<Chips value={threshold} onChange={setThreshold} options={[399, 499, 699, 999].map((v) => ({ value: v, label: `₹${v}` }))} />}>
              <div className="kpis" style={{ marginBottom: 10 }}>
                <Kpi label={`Orders already ₹${threshold}+`} value={pct(o.at_or_above / (o.orders || 1), 0)} note={`${num(o.at_or_above)} of ${num(o.orders)} orders`} />
                <Kpi label="In the nudge zone" help="nudge" value={num(o.near)} note={`orders at 70–99% of ₹${threshold}`} />
                <Kpi label="Revenue if nudged up" value={inr(o.gap_value)} note="if those orders reached the threshold" />
                <Kpi label="Abandoned carts in the zone" value={num(t.abandoned.near)} note={`${num(t.abandoned.at_or_above)} were ₹${threshold}+ · ${num(t.abandoned.unknown)} value unknown`} />
              </div>
              <div className="muted">The “nudge zone” is where an add-on suggestion, a progress bar (“add ₹X for free delivery”) or a bundle offer is most likely to lift the order. Small sample, so treat as directional.</div>
            </Card>

            <div className="grid g2">
              <Card title="Often bought together" sub="product types that appear together in 2+ orders (inferred from names where the catalog has no match)">
                <Table cols={[{ label: 'Type A', key: 'a' }, { label: 'Type B', key: 'b' }, { label: 'Orders', sortBy: 'orders', num: true, render: (r) => num(r.orders) }]} rows={d.pairs} empty="No pair of product types has appeared together in 2+ orders in this range yet" />
              </Card>
              <Card title="Coupon impact" sub="average order value by coupon used">
                <Table cols={[
                  { label: 'Coupon', key: 'coupon' }, { label: 'Orders', sortBy: 'orders', num: true, render: (r) => num(r.orders) },
                  { label: 'Avg order', sortBy: 'aov', num: true, render: (r) => inr(r.aov) }, { label: 'Avg basket', sortBy: 'avg_basket', num: true, render: (r) => inr(r.avg_basket) },
                  { label: 'Avg discount', sortBy: 'avg_discount', num: true, render: (r) => (r.avg_discount ? inr(r.avg_discount) : '–') },
                ]} rows={d.coupons} />
              </Card>
            </div>

            <div className="grid g2">
              <Card title="Top products" sub="by revenue" right={<ExportBtn name="top-products" rows={d.products} fields={[['Product', 'product_name'], ['Brand', 'brand'], ['Type', 'product_type'], ['Units', 'units'], ['Orders', 'orders'], ['Revenue', 'revenue']]} />}>
                <Table cols={[
                  { label: 'Product', sortBy: 'product_name', render: (r) => <span className="trunc" style={{ display: 'block', maxWidth: 200 }} title={r.product_name}>{r.product_name}</span> },
                  { label: 'Type', key: 'product_type' }, { label: 'Units', sortBy: 'units', num: true, render: (r) => num(r.units) },
                  { label: 'Revenue', sortBy: 'revenue', num: true, render: (r) => inr(r.revenue) },
                ]} rows={d.products} />
              </Card>
              <div className="grid" style={{ gap: 14 }}>
                <Card title="Brands" sub="by revenue">
                  <Table cols={[{ label: 'Brand', key: 'brand' }, { label: 'Units', sortBy: 'units', num: true, render: (r) => num(r.units) }, { label: 'Orders', sortBy: 'orders', num: true, render: (r) => num(r.orders) }, { label: 'Revenue', sortBy: 'revenue', num: true, render: (r) => inr(r.revenue) }]} rows={d.brands} />
                </Card>
                <Card title="Product types">
                  <Table cols={[{ label: 'Type', key: 'product_type' }, { label: 'Units', sortBy: 'units', num: true, render: (r) => num(r.units) }, { label: 'Revenue', sortBy: 'revenue', num: true, render: (r) => inr(r.revenue) }]} rows={d.types} />
                </Card>
              </div>
            </div>
            <div className="muted">
              Data coverage: brand is known for {d.coverage.brand_known_pct.toFixed(0)}% of revenue (generic names like “Niacinamide Face Serum” carry no brand in the orders);
              only {d.coverage.catalog_type_pct.toFixed(0)}% of revenue matches your product catalogs exactly, so product types are inferred from names for the rest.
            </div>
          </>
        )
      }}
    </Loading>
  )
}
