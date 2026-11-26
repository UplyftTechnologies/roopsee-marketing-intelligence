import { useCallback, useEffect, useMemo, useState } from 'react'
import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, dt, inr, num, pct, useApi, useFilters, usePersisted } from '../api'
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

const STATE_TEXT = { priced: 'Priced', review: 'To review', not_available: 'Not available', unchecked: 'Not checked' }

/** One competitor's price in a table cell: price, MRP, discount, Nykaa's offer price as a note, and a link to the page. Without a price: why. */
function SiteCell({ v, ours }) {
  if (v?.state === 'review') return <Badge tone="warn" title="A possible match is waiting for you in Review matches">To review</Badge>
  if (v?.state === 'not_available') return <span className="muted" title="Not found on this site, marked as not sold there, or no price shown">Not available</span>
  if (v?.state !== 'priced') return <span className="muted" title="Not looked for or not read yet: press Refresh prices">Not checked</span>
  return (
    <div style={{ lineHeight: 1.3, minWidth: 92 }}>
      <b style={{ color: ours && v.price ? (ours > v.price * 1.01 ? 'var(--critical)' : ours < v.price * 0.99 ? 'var(--good)' : undefined) : undefined }}>{inr(v.price)}</b>
      {v.mrp && v.price && v.mrp > v.price && <span className="muted" style={{ fontSize: 11 }}> <s>{inr(v.mrp)}</s> {pct(v.discount, 0)} off</span>}
      {v.offer_price && <div className="muted" style={{ fontSize: 11 }} title="Nykaa's price for some customers only (e.g. a first order); not used in the comparison">offer {inr(v.offer_price)}</div>}
      <div style={{ fontSize: 11 }}><a href={v.url} target="_blank" rel="noreferrer noopener" onClick={(e) => e.stopPropagation()}>open ↗</a>{' '}
        <span className="muted" title={v.earlier ? 'The latest read gave no price, so this is the last one we saw' : undefined}>{v.earlier ? `price from ${dt(v.checked)}` : age(v.checked)}</span></div>
    </div>
  )
}

/** With sharing on: who this computer is, when it last synced, who else is refreshing, and the first upload. */
function Sharing({ st, onChange }) {
  const sh = st.sharing || {}
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState('')
  const call = async (what, path, text) => {
    setBusy(what); setMsg('')
    try { const r = await api(path, { method: 'POST' }); if (text) setMsg(text(r)) } catch (e) { setMsg(e.message) }
    setBusy(''); onChange()
  }
  if (!sh.enabled) return <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>Prices are kept on this computer only. To share them between computers, see docs/price-sync.md.</div>
  const upload = () => {
    if (!window.confirm(`Send this computer’s earlier price history to Supabase (${num(sh.history)} readings and ${num(sh.history_matches)} matches)? Everyone with the shared key will see it. The key cannot delete it afterwards.`)) return
    call('upload', '/prices/upload', (r) => `Uploaded ${num(r.readings)} readings and ${num(r.matches)} matches${r.kept_theirs ? ` (${num(r.kept_theirs)} matches already had a newer or personal decision there)` : ''}.`)
  }
  const others = sh.holder && !st.job.running
  return (
    <div style={{ marginTop: 10, display: 'grid', gap: 6 }}>
      <div className="chip-row" style={{ gap: 10, flexWrap: 'wrap' }}>
        <Badge tone={sh.error ? 'warn' : 'good'}>shared through Supabase</Badge>
        <span className="muted" style={{ fontSize: 12 }}>this computer is “{sh.me}” · {sh.last_sync ? `last synced ${dt(sh.last_sync)}` : 'not synced yet'}{sh.waiting ? ` · ${num(sh.waiting)} waiting to be sent` : ''}</span>
        <button type="button" className="btn small" disabled={!!busy} onClick={() => call('sync', '/prices/sync', (r) => (r.ok === false ? r.error : ''))}>{busy === 'sync' ? 'Syncing…' : 'Sync now'}</button>
        {(sh.history > 0 || sh.history_matches > 0) && <button type="button" className="btn small" disabled={!!busy || st.job.running} onClick={upload}>{busy === 'upload' ? 'Uploading…' : `Upload this computer’s history (${num(sh.history)} readings)`}</button>}
      </div>
      {others && <div className="banner" style={{ margin: 0 }}><b>{sh.holder}</b>&nbsp;is refreshing prices{sh.holder_since ? ` since ${dt(sh.holder_since)}` : ''}. Press Sync now to see their results.</div>}
      {sh.error && <div className="banner err" style={{ margin: 0 }}>{sh.error}</div>}
      {msg && <div className="muted" style={{ fontSize: 12 }}>{msg}</div>}
    </div>
  )
}

function RefreshBar({ st, onChange }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const job = st.job
  const go = async (path, params) => { setBusy(true); setErr(''); try { await api(path, { method: 'POST', params }); onChange() } catch (e) { setErr(e.message) } setBusy(false) }
  const last = st.last_run
  const refresh = (params) => {  // shared: ask before repeating a refresh someone finished a short while ago
    const hours = last?.finished_at ? (Date.now() - new Date(last.finished_at).getTime()) / 36e5 : null
    if (st.sharing?.enabled && last?.status?.startsWith('done') && hours != null && hours < 6 && !window.confirm(`Prices were refreshed ${age(last.finished_at)}${last.host ? ` by ${last.host}` : ''}. Refresh again?`)) return
    go('/prices/refresh', params)
  }
  return (
    <Card title="Competitor prices" sub="Nykaa, Tira and Purplle product pages, read one page at a time per site with a pause in between (a refresh takes about 15–20 minutes; the first one takes longer, because it also finds every product on each site)"
      right={job.running
        ? <button type="button" className="btn danger" onClick={() => go('/prices/stop')} disabled={busy || job.stop}>{job.stop ? 'Stopping…' : 'Stop'}</button>
        : <span className="chip-row">
          <button type="button" className="btn" onClick={() => refresh({ recheck: true })} disabled={busy || st.needs_pull} title="Refresh prices, and also search again for everything not available or waiting for review (your own decisions are kept)">Search again + refresh</button>
          <button type="button" className="btn primary" onClick={() => refresh()} disabled={busy || st.needs_pull}>↻ Refresh prices</button>
        </span>}>
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
                {p ? `${num(p.done)} / ${num(p.total)} · ${num(p.ok)} read${p.failed ? ` · ${num(p.failed)} failed` : ''}` : `${num(s.matched)} matched · ${num(s.review)} to review · ${num(s.not_found)} not available`}
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
      <Sharing st={st} onChange={onChange} />
    </Card>
  )
}

function Comparison({ rows, f }) {
  const [search, setSearch] = usePersisted('prices.search', '')
  const [brand, setBrand] = usePersisted('prices.brand', '')
  const [pos, setPos] = usePersisted('prices.pos', '')
  const [active, setActive] = usePersisted('prices.active', false)
  const [hist, setHist] = useState(null)
  const closeHist = useCallback(() => setHist(null), [])
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
      <Card title={`${num(shown.length)} products`} sub="the latest regular price on each site (red = cheaper than us, green = dearer) · our gap = our price against the cheapest competitor price · views and orders are ours, in the dates at the top · click a product to see its price history graph"
        right={<ExportBtn name="price-comparison" rows={shown} fields={[['Product id', 'product_id'], ['Product', 'name'], ['Brand', 'brand'], ['Size', 'size'], ['Our price', 'our_price'], ['Our MRP', 'our_mrp'],
          ...SITES.flatMap(([k, l]) => [[`${l} price`, (r) => r.sites[k]?.price ?? ''], [`${l} MRP`, (r) => r.sites[k]?.mrp ?? ''], [`${l} status`, (r) => STATE_TEXT[r.sites[k]?.state] || ''], [`${l} link`, (r) => r.sites[k]?.url ?? '']]),
          ['Cheapest site', 'cheapest_site'], ['Cheapest price', 'cheapest_price'], ['Our gap', 'gap'], ['Views', 'views'], ['Orders', 'orders'], ['Revenue', 'revenue']]} />}>
        <Table id="prices-compare" scroll rows={shown} cols={cols} onRow={(r) => setHist(r)} empty="No product matches these filters." />
      </Card>
      {hist && <History product={hist} onClose={closeHist} />}
    </>
  )
}

/** The pop-up of one product: what each shop asks now, and the graph of every price read, one step per refresh. */
function History({ product, onClose }) {
  const s = useApi('/prices/history', { product_id: product.product_id }, { scoped: false })
  useEffect(() => {
    const key = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', key)
    const was = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.removeEventListener('keydown', key); document.body.style.overflow = was }
  }, [onClose])
  const name = (k) => (k === 'ours' ? 'Roopsee' : SITES.find(([x]) => x === k)?.[1] || k)
  return (
    <div className="modal-back" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="card modal" role="dialog" aria-modal="true" aria-label={`Price history of ${product.name}`}>
        <div className="row-between" style={{ alignItems: 'flex-start', gap: 12, padding: 0 }}>
          <div style={{ minWidth: 0 }}>
            <h3 style={{ margin: 0, fontSize: 15 }}>{product.name}</h3>
            <div className="muted" style={{ fontSize: 12 }}>{product.brand}{product.size ? ` · ${product.size}` : ''}</div>
          </div>
          <button type="button" className="btn small" onClick={onClose} autoFocus>Close ✕</button>
        </div>
        <div className="chip-row" style={{ margin: '12px 0', gap: 8, flexWrap: 'wrap' }}>
          <span className="price-now"><i style={{ background: 'var(--text-primary)' }} /> Roopsee <b>{inr(product.our_price)}</b></span>
          {SITES.map(([k, label]) => {
            const v = product.sites[k]
            return (
              <span key={k} className="price-now"><i style={{ background: COLOR[k] }} /> {label}{' '}
                {v?.state === 'priced' ? <><b>{inr(v.price)}</b> <Badge tone={gapTone(v.gap)}>{gapText(v.gap)}</Badge> <a href={v.url} target="_blank" rel="noreferrer noopener">open ↗</a></> : <span className="muted">{STATE_TEXT[v?.state] || 'Not checked'}</span>}
              </span>
            )
          })}
        </div>
        <Loading state={s}>
          {(d) => {
            const steps = new Map()  // one row of the graph per refresh: our price and each shop's
            const step = (p) => {
              const key = p.run ?? p.day
              if (!steps.has(key)) steps.set(key, { at: p.run_at || p.at || p.day })
              return steps.get(key)
            }
            for (const p of d.points) step(p)[p.site] = p.price
            for (const p of d.own || []) step(p).ours = p.price
            const data = [...steps.values()].sort((a, b) => String(a.at).localeCompare(String(b.at)))
            if (!data.length) return <div className="empty">No price has been read for this product yet. Press <b>Refresh prices</b>.</div>
            const hasOwn = data.some((x) => x.ours != null)
            const all = [...data.flatMap((x) => [x.ours, ...SITES.map(([k]) => x[k])]), product.our_price].filter((v) => v != null)
            const pad = Math.max(5, (Math.max(...all) - Math.min(...all)) * 0.15)
            return (
              <>
                <div style={{ height: 320 }}>
                  <ResponsiveContainer>
                    <LineChart data={data} margin={{ left: 0, right: 20, top: 10, bottom: 0 }}>
                      <CartesianGrid stroke="var(--grid)" vertical={false} />
                      <XAxis dataKey="at" tickFormatter={dt} {...axis} padding={{ left: 16, right: 16 }} />
                      <YAxis {...axis} width={60} tickFormatter={(v) => `₹${num(v)}`} domain={[Math.max(0, Math.floor(Math.min(...all) - pad)), Math.ceil(Math.max(...all) + pad)]} />
                      <Tooltip {...chartTip} labelFormatter={dt} formatter={(v, n) => [inr(v), name(n)]} />
                      <Legend formatter={name} />
                      {!hasOwn && product.our_price != null && <ReferenceLine y={product.our_price} stroke="var(--text-primary)" strokeDasharray="5 4" label={{ value: 'our price today', position: 'insideTopLeft', fontSize: 11, fill: 'var(--text-muted)' }} />}
                      {hasOwn && <Line dataKey="ours" stroke="var(--text-primary)" strokeWidth={2.5} strokeDasharray="5 4" dot={{ r: 3 }} connectNulls isAnimationActive={false} />}
                      {SITES.map(([k]) => <Line key={k} dataKey={k} stroke={COLOR[k]} strokeWidth={2} dot={{ r: 3.5 }} connectNulls isAnimationActive={false} />)}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
                <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
                  One point per price refresh ({num(data.length)} so far). Shop prices are their regular prices.
                  {data.length < 2 ? ' The lines appear after the next refresh.' : ''}{!hasOwn ? ' Our own price is recorded from the next refresh on; until then the dashed line is today’s.' : ''}
                </div>
              </>
            )
          }}
        </Loading>
      </div>
    </div>
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
              <Kpi label="Typical gap" value={gapText(k.median_gap)} note="our price against the cheapest competitor (median)" />
            </div>
            <Card title="Against each site" sub="products priced on each site · gap = our price against that site's (median) · discount = (MRP − price) / MRP on the same products">
              <Table id="prices-sites" rows={d.sites} cols={[
                { label: 'Site', key: 'label' }, { label: 'Priced', num: true, render: (r) => num(r.priced) }, { label: 'To review', num: true, render: (r) => num(r.review) },
                { label: 'Not available', num: true, render: (r) => num(r.not_available) }, { label: 'Not checked', num: true, hidden: true, render: (r) => num(r.unchecked) }, { label: 'Our typical gap', num: true, render: (r) => <Badge tone={gapTone(r.median_gap)}>{gapText(r.median_gap)}</Badge> },
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
            <div>
              <Card title="What changed since the previous reading" sub="price changes between the last two prices read for a product on a site, biggest first">
                <Table id="prices-changes" scroll rows={d.changes} empty="No change yet (it needs two refreshes)." cols={[
                  { label: 'Product', render: (r) => <div className="trunc" style={{ maxWidth: 260 }} title={r.name}>{r.name}</div> }, { label: 'Site', key: 'site_label' },
                  { label: 'Before', num: true, render: (r) => inr(r.before_price) }, { label: 'Now', num: true, render: (r) => inr(r.now_price) },
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
    try { await api('/prices/match', { method: 'POST', body: { product_id: r.product_id, site: r.site, action, url, version: r.version } }) } catch (e) { setErr(e.message) }
    setRev((x) => x + 1); onChange()  // also after a refusal: the list then shows what the others decided
  }
  const sure = (r) => { const c = r.candidates?.[0]; return c && !c.note && c.page_name && c.score >= 0.85 && (c.page_size || c.size) === 'same' }
  const confirmAll = async (list) => {
    if (!window.confirm(`Confirm the first suggestion of ${list.length} products (same size, name match 85% or more)? Check a few of them first: confirmed matches are not guessed again.`)) return
    setErr('')
    try { for (const r of list) await api('/prices/match', { method: 'POST', body: { product_id: r.product_id, site: r.site, action: 'confirm', url: r.candidates[0].url, version: r.version } }) } catch (e) { setErr(e.message) }
    setRev((x) => x + 1); onChange()
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
          <Card right={status === 'review' && d.rows.some(sure) ? <button type="button" className="btn small" onClick={() => confirmAll(d.rows.filter(sure))}>Confirm {num(d.rows.filter(sure).length)} strong matches</button> : null}
            title={`${num(d.rows.length)} ${status === 'review' ? 'matches to check' : status === 'none' ? 'products not found' : status === 'rejected' ? 'rejected' : 'matched'}`}
            sub={status === 'review' ? 'we are not sure these are the same product (name or size do not fully agree): confirm the right one, reject it, or paste the right link. Your decision is kept and never guessed again.'
              : status === 'none' ? 'no page with the same brand, name and size was found; paste the link if the site sells it (it is looked for again after a week)'
                : status === 'matched' ? 'how each match was made: link in the sheet, barcode (Purplle), name and size, or you' : 'pages you said are not our product; clear one to let it be found again'}>
            {d.rows.length === 0 ? <div className="empty">Nothing here.</div> : (
              <div className="review-list">
                {d.rows.map((r) => {
                  const key = `${r.product_id}|${r.site}`
                  return (
                    <div key={key} className="review-row">
                      <div className="review-ours"><Badge>{r.site_label}</Badge> <b>{r.name}</b><div className="muted" style={{ fontSize: 12 }}>{r.brand}{r.size ? ` · ${r.size}` : ''} · ours {inr(r.our_price)}{r.updated_by ? ` · last changed by ${r.updated_by}` : ''}</div></div>
                      <div className="review-cands">
                        {status === 'matched' ? (
                          <div className="review-cand"><a href={r.url} target="_blank" rel="noreferrer noopener">{r.matched_name || r.url}</a> <span className="muted">· {r.method === 'sheet' ? 'link in the sheet' : r.method === 'you' ? 'set by you' : r.method === 'barcode' ? 'same barcode' : `name and size (${pct(r.confidence, 0)})`}</span>
                            <button type="button" className="btn small" onClick={() => act(r, 'reject', r.url)}>Not this product</button></div>
                        ) : (r.candidates || []).filter((c) => c.page_name || status === 'review').slice(0, 3).map((c) => (
                          <div key={c.url} className="review-cand">
                            <a href={c.url} target="_blank" rel="noreferrer noopener">{c.page_name || c.url.replace(/^https:\/\/[^/]+/, '')}</a>
                            <span className="muted"> · {pct(c.score, 0)} name match · size {c.page_size || c.size}{c.price ? ` · ${inr(c.price)}` : ''}</span>
                            {c.note && <Badge tone="warn" title="This page does not sell our size, so its price is not compared until you decide">{c.note}</Badge>}
                            {status !== 'rejected' && <><button type="button" className="btn small primary" onClick={() => act(r, 'confirm', c.url)}>Same product</button>
                              <button type="button" className="btn small" onClick={() => act(r, 'reject', c.url)}>Not it</button></>}
                          </div>
                        ))}
                        {status !== 'matched' && (
                          <form className="chip-row" onSubmit={(e) => { e.preventDefault(); act(r, 'link', paste[key]) }}>
                            <input className="field" style={{ flex: 1, minWidth: 260 }} placeholder={`Paste the ${r.site_label} product link…`} value={paste[key] || ''} onChange={(e) => setPaste({ ...paste, [key]: e.target.value })} />
                            <button type="submit" className="btn small" disabled={!paste[key]}>Use this link</button>
                            {status !== 'rejected' && <button type="button" className="btn small" onClick={() => act(r, 'notsold')} title="Shows “Not available” and stops looking for it on this site">Not sold here</button>}
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
              { label: 'Started', cls: 'nw', render: (r) => dt(r.started_at) }, { label: 'Computer', cls: 'nw', render: (r) => r.host || 'this one' }, { label: 'Finished', cls: 'nw', render: (r) => (r.finished_at ? dt(r.finished_at) : '–') },
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
  const shared = !!st.data?.sharing?.enabled
  useEffect(() => {  // opening the tab: fetch what other computers added
    if (shared) api('/prices/sync', { method: 'POST' }).catch(() => {}).then(() => setRev((x) => x + 1))
  }, [shared])
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
