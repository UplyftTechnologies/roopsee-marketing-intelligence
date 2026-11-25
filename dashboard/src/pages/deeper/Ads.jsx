import { inr, num, pct, useApi, useFilters } from '../../api'
import { Badge, Loading } from '../../ui'
import { NotBuilt, secs } from './common'

const VERDICT_TONE = { Ordering: 'good', Promising: 'warn', 'No carts': 'bad', 'High bounce': 'bad', 'Too early': '' }

function Funnel({ r }) {
  const steps = [['Visits', r.sessions], ['Looked at a product', r.product], ['Added to cart', r.carts], ['Reached checkout', r.checkouts], ['Ordered', r.orders]]
  const max = Math.max(r.sessions, 1)
  return (
    <div style={{ display: 'grid', gap: 3 }}>
      {steps.map(([n, v]) => (
        <div key={n} style={{ display: 'grid', gridTemplateColumns: '120px 1fr 52px', alignItems: 'center', gap: 6, fontSize: 12 }}>
          <span className="muted">{n}</span>
          <span className="mini-bar" style={{ margin: 0 }}><i style={{ width: `${Math.max(1, (v / max) * 100)}%` }} /></span>
          <span style={{ textAlign: 'right' }}>{num(v)}</span>
        </div>
      ))}
    </div>
  )
}

/** A postmortem card: the picture first, then what happened to the visits it brought. */
function PostCard({ r, kind, f }) {
  const title = kind === 'ad' ? (r.name || `Ad ${r.ad_id}`) : r.name
  return (
    <article className="card" style={{ display: 'grid', gap: 10, alignContent: 'start' }}>
      <div style={{ display: 'grid', gridTemplateColumns: '92px 1fr', gap: 10 }}>
        <div style={{ width: 92, height: 92, borderRadius: 8, background: 'var(--surface-2)', display: 'grid', placeItems: 'center', overflow: 'hidden' }}>
          {r.image
            ? <img src={r.image} alt={title} loading="lazy" style={{ width: '100%', height: '100%', objectFit: 'cover' }} onError={(e) => { e.currentTarget.style.display = 'none' }} />
            : <span className="muted" style={{ fontSize: 11, textAlign: 'center', padding: 4 }}>{kind === 'ad' ? (r.in_meta ? 'no picture saved yet' : 'ad not in the synced account') : 'no picture'}</span>}
        </div>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 600, overflowWrap: 'anywhere' }}>{title}</div>
          <div className="muted" style={{ fontSize: 12 }}>
            {kind === 'ad' ? <>ad <span className="mono">{r.ad_id}</span>{r.status ? ` · ${r.status.toLowerCase()}` : ''}</> : r.brand}
          </div>
          <div style={{ marginTop: 4 }}><Badge tone={VERDICT_TONE[r.verdict]}>{r.verdict}</Badge></div>
        </div>
      </div>
      <Funnel r={r} />
      <div className="muted" style={{ fontSize: 12 }}>
        bounce {pct(r.bounce_rate, 0)} · cart {pct(r.cart_rate, 1)} · avg {secs(r.avg_duration)}{r.roop_opened > 0 ? ` · opened Roop ${num(r.roop_opened)} (${pct(r.roop_rate, 1)})` : ''}{r.pain_rate >= 0.1 ? ` · ${pct(r.pain_rate, 0)} hit a problem` : ''}
        {kind === 'ad' && r.spend > 0 ? ` · spent ${inr(r.spend)}${r.cost_per_order ? ` (${inr(r.cost_per_order)} per order)` : ''}` : ''}
        {kind === 'ad' && r.landing?.length ? <><br />landed on: {r.landing.map((l) => `${l.name} ${Math.round((l.count / r.sessions) * 100)}%`).join(', ')}</> : null}
      </div>
      {r.notes.length > 0 && <ul style={{ margin: 0, paddingLeft: 16, fontSize: 13, display: 'grid', gap: 2 }}>{r.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
      <div>
        <button type="button" className="btn small" onClick={() => f.go('sessions', kind === 'ad' ? { ad: r.ad_id } : { landing_product: r.product_id })}>See the visits →</button>
        {r.roop_opened > 0 && <> <button type="button" className="btn small" onClick={() => f.go('sessions', kind === 'ad' ? { ad: r.ad_id, has: ['roop'] } : { landing_product: r.product_id, has: ['roop'] })}>Visits that opened Roop ({num(r.roop_opened)}) →</button></>}
      </div>
    </article>
  )
}

export default function Ads() {
  const f = useFilters()
  const s = useApi('/deeper/ads')
  return (
    <Loading state={s}>
      {(d) => {
        if (!d.ready) return <NotBuilt />
        return (
          <>
            <h3 style={{ margin: 0 }}>Which ad they saw <span className="muted" style={{ fontWeight: 400, fontSize: 13 }}>· Paid Meta visits by ad, compared with all Paid Meta visits ({num(d.meta_baseline.sessions)} visits, {pct(d.meta_baseline.bounce_rate, 0)} bounce, {pct(d.meta_baseline.cart_rate, 1)} add to cart)</span></h3>
            {!d.meta_connected && <div className="banner">Meta Ads is not synced yet, so ads show only their id. Add the Meta token (see the Meta Ads page) and press Refresh to see the pictures and names.</div>}
            {d.ads_without_image > 0 && d.meta_connected && <div className="muted" style={{ fontSize: 12 }}>{d.ads_without_image} of {d.ads.length} ads have no picture: they are not in the synced ad accounts, or the picture has not been saved yet (it is saved at the next Refresh).</div>}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 14 }}>
              {d.ads.map((r) => <PostCard key={r.ad_id} r={r} kind="ad" f={f} />)}
            </div>
            {!d.ads.length && <div className="muted">No Paid Meta visits with an ad id in these dates.</div>}

            <h3 style={{ margin: '8px 0 0' }}>Which product they landed on <span className="muted" style={{ fontWeight: 400, fontSize: 13 }}>· product pages that visits started on ({num(d.product_baseline.sessions)} visits, {pct(d.product_baseline.bounce_rate, 0)} bounce, {pct(d.product_baseline.cart_rate, 1)} add to cart)</span></h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 14 }}>
              {d.products.map((r) => <PostCard key={r.product_id} r={r} kind="product" f={f} />)}
            </div>
            {!d.products.length && <div className="muted">No product pages with 10 or more landing visits in these dates.</div>}
          </>
        )
      }}
    </Loading>
  )
}
