import { useMemo } from 'react'
import { num, pct, useApi, usePersisted } from '../api'
import { Card, ExportBtn, Loading, Table } from '../ui'
import './Products.css'

const EMPTY_FILTERS = { search: '', brand: '', category: '', type: '', minPrice: '', maxPrice: '', minDiscount: '', eligibility: '' }
const rupees = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 0, maximumFractionDigits: 2 })
const ruleDate = new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
const money = (value) => value == null ? '–' : rupees.format(value)
const productName = (row) => row.name || row.product_id
const new15Price = (row) => row.new15_eligible === false ? 'Not eligible' : row.new15_price
const couponDiscount = (row, code) => row.coupon_discounts?.[code] ?? null
const couponLabel = (code) => `${code} Discount`

const COLUMNS = [
  { key: 'image', render: (r) => r.image && <img className="products-thumb" src={r.image} alt="" loading="lazy" /> },
  { label: 'Product', key: 'name', sortBy: productName, render: (r) => <strong>{productName(r)}</strong> },
  { label: 'Brand', key: 'brand' },
  { label: 'Category', key: 'category' },
  { label: 'Type', key: 'type' },
  { label: 'Size', key: 'size' },
  { label: 'MRP', key: 'mrp', num: true, cls: 'nw', render: (r) => money(r.mrp) },
  {
    label: 'Selling Price', key: 'selling_price', num: true, cls: 'nw',
    render: (r) => (
      <>
        <strong>{money(r.selling_price)}</strong>
        {r.off_mrp != null && <div className="muted products-discount">{pct(Math.abs(r.off_mrp))} {r.off_mrp < 0 ? 'above MRP' : 'off MRP'}</div>}
      </>
    ),
  },
  {
    label: 'NEW15 Price', key: 'new15_price', num: true, cls: 'nw',
    render: (r) => r.new15_eligible === false ? <span className="muted">Not eligible</span> : money(r.new15_price),
  },
  { label: 'Pay Online Price', key: 'pay_online_price', num: true, cls: 'nw', render: (r) => money(r.pay_online_price) },
  { label: 'App Price', key: 'app_price', num: true, cls: 'nw', render: (r) => money(r.app_price) },
  { label: 'Product ID', key: 'product_id', cls: 'mono nw', hidden: true },
]
const EXPORT_FIELDS = [
  ['Product', productName], ['Brand', 'brand'], ['Category', 'category'], ['Type', 'type'], ['Size', 'size'],
  ['MRP', 'mrp'], ['Selling Price', 'selling_price'], ['% off MRP', (r) => r.off_mrp == null ? null : pct(r.off_mrp)],
  ['NEW15 Price', new15Price], ['Pay Online Price', 'pay_online_price'], ['App Price', 'app_price'],
  ['Product ID', 'product_id'], ['Image', 'image'],
]
const NO_COUPONS = []

function CouponEligibility({ coupons }) {
  if (!coupons.length) return null
  return (
    <details className="products-note">
      <summary>Coupon eligibility</summary>
      <ul>
        {coupons.map(({ code, audience, brand, minimum, maximum, percent, flat }) => (
          <li key={code}>
            <strong>{code}</strong> · {flat == null ? `${percent}% off` : `${money(flat)} off`} · {brand || audience}
            {minimum != null && ` · ${brand ? 'Brand subtotal' : 'Order subtotal'} ${money(minimum)} or more`}
            {maximum != null && `, below ${money(maximum)}`}
          </li>
        ))}
      </ul>
    </details>
  )
}

function ProductList({ rows, rules }) {
  const coupons = rules.coupons ?? NO_COUPONS
  const columns = useMemo(() => [
    ...COLUMNS,
    ...coupons.map(({ code }) => ({
      label: couponLabel(code), key: code, num: true, cls: 'nw', sortBy: (row) => couponDiscount(row, code),
      render: (row) => {
        const discount = couponDiscount(row, code)
        return discount == null && row.selling_price != null ? <span className="muted">Not eligible</span> : money(discount)
      },
    })),
  ], [coupons])
  const exportFields = useMemo(() => [
    ...EXPORT_FIELDS,
    ...coupons.map(({ code }) => [
      couponLabel(code), (row) => couponDiscount(row, code) ?? (row.selling_price == null ? null : 'Not eligible'),
    ]),
  ], [coupons])

  const [filters, setFilters] = usePersisted('products.filters', EMPTY_FILTERS)
  const update = (key) => (event) => {
    const { value } = event.target
    setFilters((current) => ({ ...current, [key]: value }))
  }
  const facets = useMemo(() => Object.fromEntries(['brand', 'category', 'type'].map((key) => [
    key, [...new Set(rows.map((row) => row[key]).filter(Boolean))].sort((a, b) => a.localeCompare(b)),
  ])), [rows])

  const shown = useMemo(() => {
    const search = filters.search.trim().toLowerCase()
    const minPrice = filters.minPrice === '' ? null : Number(filters.minPrice)
    const maxPrice = filters.maxPrice === '' ? null : Number(filters.maxPrice)
    const minDiscount = filters.minDiscount === '' ? null : Number(filters.minDiscount) / 100
    return rows.filter((r) => (
      (!search || [r.name, r.brand, r.product_id].some((v) => v?.toLowerCase().includes(search))) &&
      (!filters.brand || r.brand === filters.brand) &&
      (!filters.category || r.category === filters.category) &&
      (!filters.type || r.type === filters.type) &&
      (minPrice == null || (r.selling_price != null && r.selling_price >= minPrice)) &&
      (maxPrice == null || (r.selling_price != null && r.selling_price <= maxPrice)) &&
      (minDiscount == null || (r.off_mrp != null && r.off_mrp >= minDiscount)) &&
      (!filters.eligibility || r.new15_eligible === (filters.eligibility === 'eligible'))
    ))
  }, [rows, filters])

  const discounts = shown.map((r) => r.off_mrp).filter((v) => v != null)
  const average = discounts.length ? discounts.reduce((sum, value) => sum + value, 0) / discounts.length : null
  const eligible = shown.filter((r) => r.new15_eligible).length
  const priceRangeInvalid = filters.minPrice !== '' && filters.maxPrice !== '' && Number(filters.minPrice) > Number(filters.maxPrice)

  return (
    <>
      <div className="products-filters">
        <label className="products-search">Search
          <input className="field" type="search" value={filters.search} onChange={update('search')} placeholder="Product name, brand, or ID" />
        </label>
        {[['brand', 'Brand'], ['category', 'Category'], ['type', 'Type']].map(([key, label]) => (
          <label key={key}>{label}
            <select className="field" value={filters[key]} onChange={update(key)}>
              <option value="">All</option>
              {filters[key] && !facets[key].includes(filters[key]) && <option value={filters[key]}>{filters[key]}</option>}
              {facets[key].map((value) => <option key={value}>{value}</option>)}
            </select>
          </label>
        ))}
        <label>Min selling price (₹)
          <input className="field products-number" type="number" inputMode="decimal" min="0" step="0.01" value={filters.minPrice} onChange={update('minPrice')} aria-invalid={priceRangeInvalid} />
        </label>
        <label>Max selling price (₹)
          <input className="field products-number" type="number" inputMode="decimal" min="0" step="0.01" value={filters.maxPrice} onChange={update('maxPrice')} aria-invalid={priceRangeInvalid} />
        </label>
        <label>Min % off MRP
          <input className="field products-number" type="number" inputMode="decimal" max="100" step="0.1" value={filters.minDiscount} onChange={update('minDiscount')} />
        </label>
        <label>NEW15 eligibility
          <select className="field" value={filters.eligibility} onChange={update('eligibility')}>
            <option value="">All</option>
            <option value="eligible">Eligible</option>
            <option value="ineligible">Not eligible</option>
          </select>
        </label>
        <button type="button" className="btn" disabled={!Object.values(filters).some(Boolean)} onClick={() => setFilters(EMPTY_FILTERS)}>Clear filters</button>
      </div>

      <p className="muted products-note">
        Offer rules as of <time dateTime={rules.effective_date}>{ruleDate.format(new Date(rules.effective_date))}</time>.
        {' '}NEW15 is {rules.new15_percent}% off for eligible new customers on orders of {money(rules.new15_min_subtotal)} or more.
        {' '}Pay Online adds {rules.online_percent}% off, and App Price applies the {rules.app_percent}% first-app-order discount before Pay Online.
        {' '}Price estimates are for one unit and exclude delivery fees, platform fees, and brand coupons.
        {' '}Discount columns show savings for each coupon based on one unit. Apply one cart coupon per order.
        {' '}The APP10 column shows the discount used in App Price.
      </p>
      <CouponEligibility coupons={coupons} />

      <Card title={`${num(shown.length)} of ${num(rows.length)} products`}
        sub={`Average % off MRP ${pct(average)} · ${num(eligible)} eligible for NEW15`}
        right={<ExportBtn name="products" preferenceKey="mi.products.exportShown" rows={shown} fields={exportFields} />}>
        <Table id="products-catalogue" scroll rows={shown} cols={columns} empty={
          rows.length === 0 ? 'No catalog data yet. Press Refresh to load products.'
            : priceRangeInvalid ? 'The minimum selling price must be at or below the maximum.'
              : 'No products match these filters.'
        } />
      </Card>
    </>
  )
}

export default function Products() {
  const state = useApi('/products', {}, { scoped: false })
  return <Loading state={state}>{({ rows, rules }) => <ProductList rows={rows} rules={rules} />}</Loading>
}
