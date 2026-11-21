import { KEY_LABEL, inr, num, pct, useApi, useFilters } from '../../api'
import { Badge, Card, ExportBtn, Kpi, Loading, Table } from '../../ui'
import { Bars, NotBuilt, secs } from './common'

const VERDICT_TONE = { Ordering: 'good', Promising: 'warn', 'No carts': 'bad', 'High bounce': 'bad', 'Too early': '' }
const label = (k) => KEY_LABEL[k] || k.replace(/_/g, ' ')

/** A path of key actions as chips. */
function Path({ path }) {
  return <span>{path.split(' > ').map((k, i) => <span key={i}>{i > 0 && <span className="muted"> → </span>}<span className="chip">{label(k)}</span></span>)}</span>
}

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
        bounce {pct(r.bounce_rate, 0)} · cart {pct(r.cart_rate, 1)} · avg {secs(r.avg_duration)}{r.pain_rate >= 0.1 ? ` · ${pct(r.pain_rate, 0)} hit a problem` : ''}
        {kind === 'ad' && r.spend > 0 ? ` · spent ${inr(r.spend)}${r.cost_per_order ? ` (${inr(r.cost_per_order)} per order)` : ''}` : ''}
        {kind === 'ad' && r.landing?.length ? <><br />landed on: {r.landing.map((l) => `${l.name} ${Math.round((l.count / r.sessions) * 100)}%`).join(', ')}</> : null}
      </div>
      {r.notes.length > 0 && <ul style={{ margin: 0, paddingLeft: 16, fontSize: 13, display: 'grid', gap: 2 }}>{r.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
      <div>
        <button type="button" className="btn small" onClick={() => f.go('sessions', { search: kind === 'ad' ? r.ad_id : r.name })}>See the visits →</button>
      </div>
    </article>
  )
}

export default function Journeys({ onChain }) {
  const f = useFilters()
  const s = useApi('/deeper/journeys')
  return (
    <Loading state={s}>
      {(d) => {
        if (!d.ready) return <NotBuilt />
        const b = d.before_order
        return (
          <>
            <Card title="What led up to the first order" sub="every customer's first valid order in these dates, and the visits before it">
              {b.orders === 0 ? <div className="muted">No first orders in these dates.</div> : (
                <>
                  <div className="kpis">
                    <Kpi label="First orders" value={num(b.orders)} />
                    <Kpi label="Typical visits before it" value={b.median_visits ?? '–'} note="including the visit that ordered" />
                    <Kpi label="Typical time to order" value={b.median_days == null ? '–' : b.median_days < 1 ? 'same day' : `${b.median_days} days`} note="first visit to order" />
                    <Kpi label="Used 2+ channels" value={num(b.multi_channel)} note={`${pct(b.orders ? b.multi_channel / b.orders : 0, 0)} of first orders`} />
                  </div>
                  <div className="grid g3" style={{ marginTop: 12 }}>
                    <div><b>Visits before ordering</b><Bars items={b.visits} total={b.orders} /></div>
                    <div><b>Time from first visit</b><Bars items={b.days} total={b.orders} /></div>
                    <div><b>First landing page</b><Bars items={b.first_landing} total={b.orders} /></div>
                  </div>
                  <div style={{ marginTop: 12 }}>
                    <b>First channel that brought them</b>
                    <Table rows={b.first_channel} cols={[{ label: 'Channel', key: 'name' }, { label: 'First orders', num: true, sortBy: 'orders', render: (r) => num(r.orders) }, { label: 'Typical visits', num: true, render: (r) => r.median_visits ?? '–' }]} />
                  </div>
                </>
              )}
            </Card>

            <Card title="The paths visits take" sub={`the key actions of each visit, in order · ${num(d.totals.browse_only)} of ${num(d.totals.sessions)} visits did no key action · click a path to build on it`}
              right={<ExportBtn name="journey-paths" rows={d.paths} fields={[['Path', 'path'], ['Visits', 'sessions'], ['Ordered', 'ordered']]} />}>
              <Table rows={d.paths} onRow={(r) => onChain(r.path.split(' > '))} empty="No paths in these dates." cols={[
                { label: 'Path', render: (r) => <Path path={r.path} /> },
                { label: 'Visits', num: true, sortBy: 'sessions', render: (r) => num(r.sessions) },
                { label: 'Ordered', num: true, sortBy: 'ordered', render: (r) => num(r.ordered) },
                { label: 'Order rate', num: true, render: (r) => pct(r.sessions ? r.ordered / r.sessions : 0, 1) },
              ]} />
            </Card>

            <h3 style={{ margin: '8px 0 0' }}>Which ad they saw <span className="muted" style={{ fontWeight: 400, fontSize: 13 }}>· Paid Meta visits by ad, compared with all Paid Meta visits ({num(d.meta_baseline.sessions)} visits, {pct(d.meta_baseline.bounce_rate, 0)} bounce, {pct(d.meta_baseline.cart_rate, 1)} add to cart)</span></h3>
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
