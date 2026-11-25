import { useEffect, useMemo, useState } from 'react'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, day, dt, inr, num, pct, useApi, useFilters, usePersisted } from '../api'
import { Badge, Card, Chips, ExportBtn, Kpi, Loading, Search, Table, axis, chartTip } from '../ui'

/** Price intelligence: our catalogue against the live regular prices on Nykaa, Tira and Purplle. Backend: mi/prices.py, mi/price_sites.py */

const SITES = [['nykaa', 'Nykaa'], ['tira', 'Tira'], ['purplle', 'Purplle']]
const COLOR = { nykaa: 'var(--series-1)', tira: 'var(--series-2)', purplle: 'var(--series-3)' }
const POS = { dearer: ['We are dearer', 'bad'], cheaper: ['We are cheapest', 'good'], same: ['Same price', ''], no_data: ['No competitor price', ''] }
const gapText = (g) => (g == null ? '–' : `${g > 0 ? '+' : ''}${(g * 100).toFixed(1)}%`)
const gapTone = (g) => (g == null ? '' : g > 0.01 ? 'bad' : g < -0.01 ? 'good' : '')
const age = (t) => {
  if (!t) return ''
  const h = (Date.now() - new Date(t).getTime()) / 36e5
  return h < 1 ? 'just now' : h < 48 ? `${Math.round(h)} h ago` : `${Math.round(h / 24)} days ago`
}
const thumb = (img) => { const s = String(img || '').split(/[,\s]+/).find((x) => x.startsWith('http')); return s || null }

/** One competitor's price in a table cell: price, MRP, discount, stock, Nykaa's offer price as a note, and a link to the page. */
function SiteCell({ v, ours }) {
  if (!v) return <span className="muted">not matched</span>
  if (v.price == null && v.in_stock !== false) return <span className="muted" title="matched, not read yet: press Refresh prices">–</span>
  return (
    <div style={{ lineHeight: 1.3, minWidth: 92 }}>
      {v.in_stock === false ? <Badge tone="warn">out of stock</Badge> : (
        <b style={{ color: ours && v.price ? (ours > v.price * 1.01 ? 'var(--critical)' : ours < v.price * 0.99 ? 'var(--good)' : undefined) : undefined }}>{inr(v.price)}</b>
      )}
      {v.mrp && v.price && v.mrp > v.price && <span className="muted" style={{ fontSize: 11 }}> <s>{inr(v.mrp)}</s> {pct(v.discount, 0)} off</span>}
      {v.offer_price && <div className="muted" style={{ fontSize: 11 }} title="Nykaa's price for some customers only (e.g. a first order); not used in the comparison">offer {inr(v.offer_price)}</div>}
      <div style={{ fontSize: 11 }}><a href={v.url} target="_blank" rel="noreferrer noopener" onClick={(e) => e.stopPropagation()}>open ↗</a> <span className="muted">{age(v.checked)}</span></div>
    </div>
  )
}

function RefreshBar({ st, onChange }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const job = st.job
  const go = async (path) => { setBusy(true); setErr(''); try { await api(path, { method: 'POST' }); onChange() } catch (e) { setErr(e.message) } setBusy(false) }
  const last = st.last_run
  return (
    <Card title="Competitor prices" sub="Nykaa, Tira and Purplle product pages, read one page at a time per site with a pause in between (a refresh takes about 15–20 minutes; the first one takes longer, because it also finds every product on each site)"
      right={job.running
        ? <button type="button" className="btn danger" onClick={() => go('/prices/stop')} disabled={busy || job.stop}>{job.stop ? 'Stopping…' : 'Stop'}</button>
        : <button type="button" className="btn primary" onClick={() => go('/prices/refresh')} disabled={busy || st.needs_pull}>↻ Refresh prices</button>}>
      {st.needs_pull && <div className="banner err" style={{ margin: 0 }}>The product sheet was pulled by an older version. Press <b>Refresh</b> (top right) once, then refresh prices.</div>}
      {err && <div className="banner err" style={{ margin: '0 0 8px' }}>{err}</div>}
      <div className="price-sites">
        {SITES.map(([k, label]) => {
          const s = st.sites[k] || {}
          const p = job.running ? job.sites?.[k] : null
          return (
            <div key={k} className="price-site">
              <div className="row-between" style={{ padding: 0 }}><b>{label}</b>{p ? <Badge tone="warn">{p.phase}</Badge> : null}</div>
              {p && p.total > 0 && (
                <div className="price-progress" title={`${p.done} of ${p.total}`}><i style={{ width: `${Math.round((p.done / p.total) * 100)}%` }} /></div>
              )}
              <div className="muted" style={{ fontSize: 12 }}>
                {p ? `${num(p.done)} / ${num(p.total)} · ${num(p.ok)} read${p.failed ? ` · ${num(p.failed)} failed` : ''}` : `${num(s.matched)} matched · ${num(s.review)} to review · ${num(s.not_found)} not found`}
              </div>
              {p?.error && <div style={{ fontSize: 12, color: 'var(--critical)' }}>{p.error}</div>}
            </div>
          )
        })}
      </div>
      <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
        {job.running ? `Running since ${dt(job.started)}. You can keep using the dashboard; prices appear as they are read.`
          : last ? `Last refresh ${dt(last.finished_at || last.started_at)} (${age(last.finished_at || last.started_at)}): ${last.status}${last.message ? ` · ${last.message}` : ''}` : 'Prices have never been refreshed. Press Refresh prices.'}
        {' '}Our prices are the Selling Price and MRP of the product sheet (master_products). Competitor prices are their regular prices.
      </div>
    </Card>
  )
}

function Comparison({ rows, f }) {
  const [search, setSearch] = usePersisted('prices.search', '')
  const [brand, setBrand] = usePersisted('prices.brand', '')
  const [pos, setPos] = usePersisted('prices.pos', '')
  const [active, setActive] = usePersisted('prices.active', false)
  const [hist, setHist] = useState(null)
  const brands = useMemo(() => [...new Set(rows.map((r) => r.brand).filter(Boolean))].sort((a, b) => a.localeCompare(b)), [rows])
  const shown = rows.filter((r) => (!brand || r.brand === brand) && (!pos || r.position === pos) && (!active || r.views || r.orders)
    && (!search || `${r.name} ${r.brand} ${r.product_id}`.toLowerCase().includes(search.toLowerCase())))
  const cols = [
    { label: 'Product', sortBy: 'name', render: (r) => (
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', minWidth: 230, maxWidth: 330 }}>
        {thumb(r.image) ? <img src={thumb(r.image)} alt="" loading="lazy" style={{ width: 34, height: 34, objectFit: 'cover', borderRadius: 6, flex: 'none', background: 'var(--surface-2)' }} /> : null}
        <div style={{ minWidth: 0 }}><div className="trunc" title={r.name}>{r.name}</div><div className="muted" style={{ fontSize: 11.5 }}>{r.brand}{r.size ? ` · ${r.size}` : ''}</div></div>
      </div>
    ) },
    { label: 'Our price', num: true, sortBy: 'our_price', render: (r) => <div style={{ lineHeight: 1.3 }}><b>{inr(r.our_price)}</b>{r.our_mrp > r.our_price ? <div className="muted" style={{ fontSize: 11 }}><s>{inr(r.our_mrp)}</s> {pct(r.our_discount, 0)} off</div> : null}</div> },
    ...SITES.map(([k, label]) => ({ label, sortBy: (r) => r.sites[k]?.price ?? null, render: (r) => <SiteCell v={r.sites[k]} ours={r.our_price} /> })),
    { label: 'Cheapest', cls: 'nw', sortBy: 'cheapest_price', render: (r) => (r.cheapest_site ? <span>{inr(r.cheapest_price)} <span className="muted">{SITES.find(([k]) => k === r.cheapest_site)?.[1]}</span></span> : <span className="muted">–</span>) },
    { label: 'Our gap', num: true, sortBy: (r) => r.gap ?? null, render: (r) => <Badge tone={gapTone(r.gap)}>{gapText(r.gap)}</Badge> },
    { label: 'Views', num: true, sortBy: 'views', render: (r) => num(r.views) },
    { label: 'Orders', num: true, sortBy: 'orders', render: (r) => num(r.orders) },
    { label: 'Revenue', num: true, hidden: true, sortBy: 'revenue', render: (r) => inr(r.revenue) },
    { label: 'Category', hidden: true, sortBy: 'category', render: (r) => [r.category, r.type].filter(Boolean).join(' · ') || '–' },
    { label: 'Product id', hidden: true, cls: 'mono nw', render: (r) => r.product_id },
  ]
  return (
    <>
      <div className="chip-row">
        <Search value={search} onChange={setSearch} placeholder="Search a product, brand or product id…" />
        <select className="field" value={brand} onChange={(e) => setBrand(e.target.value)} aria-label="Brand"><option value="">All brands</option>{brands.map((b) => <option key={b} value={b}>{b}</option>)}</select>
        <Chips value={pos} onChange={setPos} options={[{ value: '', label: 'All' }, { value: 'dearer', label: 'We are dearer' }, { value: 'cheaper', label: 'We are cheapest' }, { value: 'same', label: 'Same price' }, { value: 'no_data', label: 'No competitor price' }]} />
        <label className="muted" style={{ fontSize: 12 }}><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> Viewed or sold in these dates</label>
      </div>
      <Card title={`${num(shown.length)} products`} sub="the latest regular price on each site (red = cheaper than us, green = dearer) · our gap = our price against the cheapest in-stock competitor · views and orders are ours, in the dates at the top · click a row for its price history"
        right={<ExportBtn name="price-comparison" rows={shown} fields={[['Product id', 'product_id'], ['Product', 'name'], ['Brand', 'brand'], ['Size', 'size'], ['Our price', 'our_price'], ['Our MRP', 'our_mrp'],
          ...SITES.flatMap(([k, l]) => [[`${l} price`, (r) => r.sites[k]?.price ?? ''], [`${l} MRP`, (r) => r.sites[k]?.mrp ?? ''], [`${l} in stock`, (r) => (r.sites[k] ? (r.sites[k].in_stock ? 'yes' : 'no') : '')], [`${l} link`, (r) => r.sites[k]?.url ?? '']]),
          ['Cheapest site', 'cheapest_site'], ['Cheapest price', 'cheapest_price'], ['Our gap', 'gap'], ['Views', 'views'], ['Orders', 'orders'], ['Revenue', 'revenue']]} />}>
        <Table id="prices-compare" scroll rows={shown} cols={cols} onRow={(r) => setHist(r)} empty="No product matches these filters." />
      </Card>
      {hist && <History product={hist} onClose={() => setHist(null)} />}
    </>
  )
}

function History({ product, onClose }) {
  const s = useApi('/prices/history', { product_id: product.product_id }, { scoped: false })
  return (
    <Card title={`Price history: ${product.name}`} sub={`our price today ${inr(product.our_price)} · one point per day and site (the last reading of the day)`} right={<button type="button" className="btn small" onClick={onClose}>Close</button>}>
      <Loading state={s}>
        {(d) => {
          const days = [...new Set(d.points.map((p) => String(p.day)))].sort()
          const data = days.map((x) => ({ day: x, ours: product.our_price, ...Object.fromEntries(SITES.map(([k]) => [k, d.points.find((p) => p.site === k && String(p.day) === x)?.price ?? null])) }))
          if (!data.length) return <div className="muted">No readings yet. Press Refresh prices.</div>
          return (
            <div style={{ height: 240 }}>
              <ResponsiveContainer>
                <LineChart data={data} margin={{ left: 0, right: 16, top: 8, bottom: 0 }}>
                  <CartesianGrid stroke="var(--grid)" vertical={false} />
                  <XAxis dataKey="day" tickFormatter={day} {...axis} />
                  <YAxis {...axis} width={56} tickFormatter={(v) => `₹${num(v)}`} domain={['auto', 'auto']} />
                  <Tooltip {...chartTip} labelFormatter={day} formatter={(v, n) => [inr(v), n === 'ours' ? 'Roopsee (today)' : SITES.find(([k]) => k === n)?.[1] || n]} />
                  <Legend formatter={(n) => (n === 'ours' ? 'Roopsee (today)' : SITES.find(([k]) => k === n)?.[1] || n)} />
                  <Line dataKey="ours" stroke="var(--text-muted)" strokeDasharray="4 4" dot={false} isAnimationActive={false} />
                  {SITES.map(([k]) => <Line key={k} dataKey={k} stroke={COLOR[k]} connectNulls dot isAnimationActive={false} />)}
                </LineChart>
              </ResponsiveContainer>
            </div>
          )
        }}
      </Loading>
    </Card>
  )
}

const productCols = (extra = []) => [
  { label: 'Product', sortBy: 'name', render: (r) => <div style={{ maxWidth: 300 }}><div className="trunc" title={r.name}>{r.name}</div><div className="muted" style={{ fontSize: 11.5 }}>{r.brand}{r.size ? ` · ${r.size}` : ''}</div></div> },
  { label: 'Our price', num: true, sortBy: 'our_price', render: (r) => inr(r.our_price) },
  { label: 'Cheapest', cls: 'nw', sortBy: 'cheapest_price', render: (r) => (r.cheapest_site ? `${inr(r.cheapest_price)} · ${SITES.find(([k]) => k === r.cheapest_site)?.[1]}` : '–') },
  { label: 'Gap', num: true, sortBy: (r) => r.gap ?? null, render: (r) => <Badge tone={gapTone(r.gap)}>{gapText(r.gap)}</Badge> },
  ...extra,
]

function Analysis() {
  const s = useApi('/prices/analysis')
  return (
    <Loading state={s}>
      {(d) => {
        const k = d.kpis
        if (!k.compared) return <div className="empty">No competitor prices yet. Press <b>Refresh prices</b> above, then come back.</div>
        return (
          <>
            <div className="kpis">
              <Kpi label="Products compared" value={num(k.compared)} note={`of ${num(k.products)} in the product sheet`} />
              <Kpi label="We are cheapest (or equal)" value={pct(k.cheapest_share, 0)} note={`${num(k.cheaper)} cheaper · ${num(k.same)} same`} />
              <Kpi label="We are dearer" value={num(k.dearer)} note={`${num(k.dearer_10)} by more than 10%`} />
              <Kpi label="Typical gap" value={gapText(k.median_gap)} note="our price against the cheapest in-stock competitor (median)" />
            </div>
            <Card title="Against each site" sub="products matched and read on each site · gap = our price against that site's (median) · discount = (MRP − price) / MRP on the same products">
              <Table id="prices-sites" rows={d.sites} cols={[
                { label: 'Site', key: 'label' }, { label: 'Matched', num: true, render: (r) => num(r.matched) }, { label: 'In stock', num: true, render: (r) => num(r.in_stock) },
                { label: 'Out of stock', num: true, render: (r) => num(r.out_of_stock) }, { label: 'Our typical gap', num: true, render: (r) => <Badge tone={gapTone(r.median_gap)}>{gapText(r.median_gap)}</Badge> },
                { label: 'We are dearer', num: true, render: (r) => num(r.we_dearer) }, { label: 'We are cheaper', num: true, render: (r) => num(r.we_cheaper) },
                { label: 'Their discount', num: true, render: (r) => pct(r.their_discount, 0) }, { label: 'Our discount', num: true, render: (r) => pct(r.our_discount, 0) },
                { label: 'With an offer price', num: true, hidden: true, render: (r) => num(r.with_offer) }]} />
            </Card>
            <div className="grid g2">
              <Card title="Revenue at risk" sub="products where a competitor is cheaper, ranked by our own revenue and views in the dates at the top"
                right={<ExportBtn name="prices-at-risk" rows={d.at_risk} fields={[['Product', 'name'], ['Brand', 'brand'], ['Our price', 'our_price'], ['Cheapest', 'cheapest_price'], ['Site', 'cheapest_site'], ['Gap', 'gap'], ['Cut needed', 'saving_needed'], ['Revenue', 'revenue'], ['Views', 'views']]} />}>
                <Table id="prices-risk" scroll rows={d.at_risk} empty="No product that sells or gets views is dearer than a competitor." cols={productCols([
                  { label: 'Cut to match', num: true, sortBy: 'saving_needed', render: (r) => inr(r.saving_needed) }, { label: 'Revenue', num: true, sortBy: 'revenue', render: (r) => inr(r.revenue) },
                  { label: 'Views', num: true, sortBy: 'views', render: (r) => num(r.views) }])} />
              </Card>
              <Card title="Price-sensitive products" sub={`viewed 20+ times, added to cart less than our average (${pct(d.cart_rate, 1)}) and dearer than a competitor: the best repricing candidates`}>
                <Table id="prices-sensitive" scroll rows={d.price_sensitive} empty="None right now." cols={productCols([
                  { label: 'Views', num: true, sortBy: 'views', render: (r) => num(r.views) }, { label: 'Cart rate', num: true, sortBy: 'cart_rate', render: (r) => pct(r.cart_rate, 1) }])} />
              </Card>
            </div>
            <div className="grid g2">
              <Card title="By brand" sub="price index: 100 = same as the cheapest competitor, above 100 = we are dearer (median of the brand's products)">
                <Table id="prices-brand" scroll rows={d.by_brand} cols={[{ label: 'Brand', key: 'name' }, { label: 'Products', num: true, render: (r) => num(r.products) },
                  { label: 'Price index', num: true, sortBy: 'index', render: (r) => <Badge tone={r.index > 101 ? 'bad' : r.index < 99 ? 'good' : ''}>{r.index}</Badge> },
                  { label: 'We are dearer', num: true, render: (r) => num(r.dearer) }, { label: 'Our revenue', num: true, sortBy: 'revenue', render: (r) => inr(r.revenue) }]} />
              </Card>
              <Card title="By category">
                <Table id="prices-cat" rows={d.by_category} cols={[{ label: 'Category', key: 'name' }, { label: 'Products', num: true, render: (r) => num(r.products) },
                  { label: 'Price index', num: true, sortBy: 'index', render: (r) => <Badge tone={r.index > 101 ? 'bad' : r.index < 99 ? 'good' : ''}>{r.index}</Badge> },
                  { label: 'We are dearer', num: true, render: (r) => num(r.dearer) }]} />
              </Card>
            </div>
            <div className="grid g2">
              <Card title="Out of stock elsewhere" sub="a competitor has run out: a chance to promote these">
                <Table id="prices-oos" scroll rows={d.out_of_stock_elsewhere} empty="Every matched competitor page is in stock." cols={productCols([
                  { label: 'Out of stock at', render: (r) => r.out_of_stock_at.map((x) => SITES.find(([k]) => k === x)?.[1]).join(', ') }, { label: 'Views', num: true, sortBy: 'views', render: (r) => num(r.views) }])} />
              </Card>
              <Card title="What changed since the previous reading" sub="price or stock changes between the last two readings of a product on a site, biggest first">
                <Table id="prices-changes" scroll rows={d.changes} empty="No change yet (it needs two refreshes)." cols={[
                  { label: 'Product', render: (r) => <div className="trunc" style={{ maxWidth: 260 }} title={r.name}>{r.name}</div> }, { label: 'Site', key: 'site_label' },
                  { label: 'Before', num: true, render: (r) => (r.before_stock === false ? 'out of stock' : inr(r.before_price)) }, { label: 'Now', num: true, render: (r) => (r.now_stock === false ? 'out of stock' : inr(r.now_price)) },
                  { label: 'Change', num: true, sortBy: (r) => r.change ?? null, render: (r) => (r.change == null ? '–' : <Badge tone={r.change < 0 ? 'bad' : 'good'}>{gapText(r.change)}</Badge>) },
                  { label: 'Seen', cls: 'nw', render: (r) => dt(r.fetched_at) }]} />
              </Card>
            </div>
          </>
        )
      }}
    </Loading>
  )
}

function Review({ onChange }) {
  const [site, setSite] = usePersisted('prices.review.site', '')
  const [status, setStatus] = usePersisted('prices.review.status', 'review')
  const [rev, setRev] = useState(0)
  const [paste, setPaste] = useState({})
  const [err, setErr] = useState('')
  const s = useApi('/prices/review', { site: site || undefined, status, rev }, { scoped: false })
  const act = async (r, action, url) => {
    setErr('')
    try { await api('/prices/match', { method: 'POST', body: { product_id: r.product_id, site: r.site, action, url } }); setRev((x) => x + 1); onChange() } catch (e) { setErr(e.message) }
  }
  return (
    <>
      <div className="chip-row">
        <Chips value={status} onChange={setStatus} options={[{ value: 'review', label: 'To review' }, { value: 'none', label: 'Not found' }, { value: 'rejected', label: 'Rejected' }, { value: 'matched', label: 'Matched' }]} />
        <Chips value={site} onChange={setSite} options={[{ value: '', label: 'All sites' }, ...SITES.map(([value, label]) => ({ value, label }))]} />
      </div>
      {err && <div className="banner err">{err}</div>}
      <Loading state={s}>
        {(d) => (
          <Card title={`${num(d.rows.length)} ${status === 'review' ? 'matches to check' : status === 'none' ? 'products not found' : status === 'rejected' ? 'rejected' : 'matched'}`}
            sub={status === 'review' ? 'we are not sure these are the same product (name or size do not fully agree): confirm the right one, reject it, or paste the right link. Your decision is kept and never guessed again.'
              : status === 'none' ? 'no page with the same brand, name and size was found; paste the link if the site sells it (it is looked for again after a week)'
                : status === 'matched' ? 'how each match was made: link in the sheet, barcode (Purplle), name and size, or you' : 'pages you said are not our product; clear one to let it be found again'}>
            {d.rows.length === 0 ? <div className="empty">Nothing here.</div> : (
              <div className="review-list">
                {d.rows.map((r) => {
                  const key = `${r.product_id}|${r.site}`
                  return (
                    <div key={key} className="review-row">
                      <div className="review-ours"><Badge>{r.site_label}</Badge> <b>{r.name}</b><div className="muted" style={{ fontSize: 12 }}>{r.brand}{r.size ? ` · ${r.size}` : ''} · ours {inr(r.our_price)}</div></div>
                      <div className="review-cands">
                        {status === 'matched' ? (
                          <div className="review-cand"><a href={r.url} target="_blank" rel="noreferrer noopener">{r.matched_name || r.url}</a> <span className="muted">· {r.method === 'sheet' ? 'link in the sheet' : r.method === 'you' ? 'set by you' : r.method === 'barcode' ? 'same barcode' : `name and size (${pct(r.confidence, 0)})`}</span>
                            <button type="button" className="btn small" onClick={() => act(r, 'reject', r.url)}>Not this product</button></div>
                        ) : (r.candidates || []).filter((c) => c.page_name || status === 'review').slice(0, 3).map((c) => (
                          <div key={c.url} className="review-cand">
                            <a href={c.url} target="_blank" rel="noreferrer noopener">{c.page_name || c.url.replace(/^https:\/\/[^/]+/, '')}</a>
                            <span className="muted"> · {pct(c.score, 0)} name match · size {c.page_size || c.size}{c.price ? ` · ${inr(c.price)}` : ''}{c.in_stock === false ? ' · out of stock' : ''}</span>
                            {c.note && <Badge tone="warn" title="This page does not sell our size, so its price is not compared until you decide">{c.note}</Badge>}
                            {status !== 'rejected' && <><button type="button" className="btn small primary" onClick={() => act(r, 'confirm', c.url)}>Same product</button>
                              <button type="button" className="btn small" onClick={() => act(r, 'reject', c.url)}>Not it</button></>}
                          </div>
                        ))}
                        {status !== 'matched' && (
                          <form className="chip-row" onSubmit={(e) => { e.preventDefault(); act(r, 'link', paste[key]) }}>
                            <input className="field" style={{ flex: 1, minWidth: 260 }} placeholder={`Paste the ${r.site_label} product link…`} value={paste[key] || ''} onChange={(e) => setPaste({ ...paste, [key]: e.target.value })} />
                            <button type="submit" className="btn small" disabled={!paste[key]}>Use this link</button>
                            {status === 'rejected' && <button type="button" className="btn small" onClick={() => act(r, 'clear')}>Look again</button>}
                          </form>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </Card>
        )}
      </Loading>
    </>
  )
}

function Log() {
  const s = useApi('/prices/runs', {}, { scoped: false })
  return (
    <Loading state={s}>
      {(d) => (
        <>
          <Card title="Refresh runs" sub="every Refresh prices run, newest first">
            <Table id="prices-runs" rows={d.runs} empty="No run yet." cols={[
              { label: 'Started', cls: 'nw', render: (r) => dt(r.started_at) }, { label: 'Finished', cls: 'nw', render: (r) => (r.finished_at ? dt(r.finished_at) : '–') },
              { label: 'Status', render: (r) => <Badge tone={r.status === 'done' ? 'good' : r.status === 'running' ? 'warn' : 'bad'}>{r.status}</Badge> },
              { label: 'Pages read', num: true, render: (r) => num(r.summary?.ok) }, { label: 'Failed', num: true, render: (r) => num(r.summary?.failed) },
              { label: 'Note', render: (r) => <span className="muted">{r.message || ''}</span> }]} />
          </Card>
          <Card title="Why pages failed in the last run" sub="grouped by site and reason; a site that changed its pages shows here as 'layout not recognised'">
            <Table id="prices-errors" rows={d.last_errors} empty="No page failed in the last run." cols={[{ label: 'Site', key: 'site' }, { label: 'Reason', key: 'error' },
              { label: 'Pages', num: true, render: (r) => num(r.n) }, { label: 'Example', render: (r) => <a href={r.example} target="_blank" rel="noreferrer noopener" className="trunc" style={{ display: 'block', maxWidth: 360 }}>{r.example}</a> }]} />
          </Card>
        </>
      )}
    </Loading>
  )
}

export default function Prices() {
  const f = useFilters()
  const [tab, setTab] = usePersisted('prices.tab', 'compare')
  const [stRev, setStRev] = useState(0)   // the run's progress
  const [rev, setRev] = useState(0)       // the numbers (comparison, analysis, log)
  const st = useApi('/prices/status', { rev: stRev + rev }, { scoped: false })
  const cmp = useApi('/prices/compare', { rev })
  const running = !!st.data?.job?.running
  useEffect(() => {  // while a run is going: progress every 4 s, the numbers every 30 s as prices come in, and once more when it ends
    if (!running) return undefined
    const a = setInterval(() => setStRev((x) => x + 1), 4000)
    const b = setInterval(() => setRev((x) => x + 1), 30000)
    return () => { clearInterval(a); clearInterval(b); setRev((x) => x + 1) }
  }, [running])
  const review = st.data ? SITES.reduce((n, [k]) => n + (st.data.sites[k]?.review || 0), 0) : 0
  return (
    <>
      <Loading state={st}>{(d) => <RefreshBar st={d} onChange={() => setRev((x) => x + 1)} />}</Loading>
      <div className="chip-row" role="tablist" aria-label="Price intelligence">
        <Chips value={tab} onChange={setTab} options={[{ value: 'compare', label: 'Comparison' }, { value: 'analysis', label: 'Analysis' }, { value: 'review', label: `Review matches${review ? ` (${review})` : ''}` }, { value: 'log', label: 'Refresh log' }]} />
      </div>
      {tab === 'compare' && <Loading state={cmp}>{(d) => <Comparison rows={d.rows} f={f} />}</Loading>}
      {tab === 'analysis' && <Analysis key={rev} />}
      {tab === 'review' && <Review onChange={() => setRev((x) => x + 1)} />}
      {tab === 'log' && <Log key={rev} />}
    </>
  )
}
