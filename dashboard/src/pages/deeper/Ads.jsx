import { inr, num, pct, useApi, useFilters } from '../../api'
import { Badge, Loading } from '../../ui'
import { NotBuilt, secs } from './common'

const VERDICT_TONE = { Ordering: 'good', Promising: 'warn', 'No carts': 'bad', 'High bounce': 'bad', 'Too early': '' }

function Funnel({ r }) {
  const steps = [['Visits', r.sessions], ['Product views', r.product], ['Added to cart', r.carts], ['Checkout', r.checkouts], ['Ordered', r.orders]]
  const max = Math.max(r.sessions, 1)
  return (
    <div className="post-funnel" aria-label="Visit funnel">
      {steps.map(([label, value]) => (
        <div className="post-funnel-row" key={label}>
          <span>{label}</span>
          <span className="post-funnel-bar"><i style={{ width: `${Math.max(1, (value / max) * 100)}%` }} /></span>
          <b>{num(value)}</b>
        </div>
      ))}
    </div>
  )
}

function Metric({ label, value }) {
  return <div className="post-metric"><span>{label}</span><b>{value}</b></div>
}

/** A concise performance card for an ad or a product landing page. */
function PostCard({ r, kind, f }) {
  const title = kind === 'ad' ? (r.name || `Ad ${r.ad_id}`) : r.name
  const isAd = kind === 'ad'
  const fallback = isAd ? (r.in_meta ? 'Creative unavailable' : 'Not in synced account') : 'Product image unavailable'
  return (
    <article className="post-card">
      <header className="post-card-head">
        <div className="post-thumb">
          {r.image
            ? <img src={r.image} alt={title} loading="lazy" onError={(e) => { e.currentTarget.style.display = 'none' }} />
            : <span><b>{isAd ? 'AD' : 'PRODUCT'}</b><small>{fallback}</small></span>}
        </div>
        <div className="post-title">
          <div className="post-kicker">{isAd ? 'Paid Meta ad' : (r.brand || 'Landing product')}</div>
          <h3 title={title}>{title}</h3>
          {isAd && <div className="post-id">ad {r.ad_id}{r.status ? ` | ${r.status.toLowerCase()}` : ''}</div>}
          <Badge tone={VERDICT_TONE[r.verdict]}>{r.verdict}</Badge>
        </div>
      </header>

      <div className="post-metrics">
        <Metric label="Bounce" value={pct(r.bounce_rate, 0)} />
        <Metric label="Cart rate" value={pct(r.cart_rate, 1)} />
        <Metric label="Avg. visit" value={secs(r.avg_duration)} />
      </div>

      <Funnel r={r} />

      <div className="post-context">
        {r.roop_opened > 0 && <span>Roop opened by {num(r.roop_opened)} ({pct(r.roop_rate, 1)})</span>}
        {r.pain_rate >= 0.1 && <span>{pct(r.pain_rate, 0)} encountered a problem</span>}
        {isAd && r.spend > 0 && <span>Spend {inr(r.spend)}{r.cost_per_order ? ` | ${inr(r.cost_per_order)} / order` : ''}</span>}
        {isAd && r.landing?.length > 0 && <span>Landing: {r.landing.map((l) => `${l.name} ${Math.round((l.count / r.sessions) * 100)}%`).join(', ')}</span>}
      </div>

      {r.notes?.length > 0 && <ul className="post-notes">{r.notes.map((note, i) => <li key={i}>{note}</li>)}</ul>}

      <footer className="post-actions">
        <button type="button" className="btn small" onClick={() => f.go('sessions', isAd ? { ad: r.ad_id } : { landing_product: r.product_id })}>See visits</button>
        {r.roop_opened > 0 && <button type="button" className="btn small" onClick={() => f.go('sessions', isAd ? { ad: r.ad_id, has: ['roop'] } : { landing_product: r.product_id, has: ['roop'] })}>Roop visits ({num(r.roop_opened)})</button>}
      </footer>
    </article>
  )
}

function SectionHead({ eyebrow, title, baseline }) {
  return (
    <div className="post-section-head">
      <div>
        <div className="post-eyebrow">{eyebrow}</div>
        <h2>{title}</h2>
      </div>
      <div className="post-baseline">
        <b>{num(baseline.sessions)}</b>
        <span>visits in this comparison</span>
        <small>{pct(baseline.bounce_rate, 0)} bounce | {pct(baseline.cart_rate, 1)} add to cart</small>
      </div>
    </div>
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
          <div className="post-analysis">
            <section className="post-section">
              <SectionHead eyebrow="Paid traffic" title="How each ad performed" baseline={d.meta_baseline} />
              {!d.meta_connected && <div className="banner">Meta Ads is not synced yet, so ads show only their id. Add the Meta token on the Meta Ads page and press Refresh to see creative images and names.</div>}
              {d.ads_without_image > 0 && d.meta_connected && <div className="post-helper">{d.ads_without_image} of {d.ads.length} ads have no picture yet. They may be outside the synced accounts, or will be saved at the next refresh.</div>}
              <div className="post-grid">
                {d.ads.map((r) => <PostCard key={r.ad_id} r={r} kind="ad" f={f} />)}
              </div>
              {!d.ads.length && <div className="muted">No Paid Meta visits with an ad id in these dates.</div>}
            </section>

            <section className="post-section">
              <SectionHead eyebrow="Landing experience" title="How landing products performed" baseline={d.product_baseline} />
              <div className="post-grid">
                {d.products.map((r) => <PostCard key={r.product_id} r={r} kind="product" f={f} />)}
              </div>
              {!d.products.length && <div className="muted">No product pages with 10 or more landing visits in these dates.</div>}
            </section>
          </div>
        )
      }}
    </Loading>
  )
}
