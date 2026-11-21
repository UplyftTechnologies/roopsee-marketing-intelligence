import { useMemo, useState } from 'react'
import { num, pct, useApi } from '../../api'
import { Badge, Card, Loading } from '../../ui'
import { NotBuilt } from './common'

/** Rows of a column: a label, a count, a bar, and a click to pick. */
function Col({ title, sub, rows, sel, onPick, empty }) {
  const max = Math.max(...rows.map((r) => r.value), 1)
  return (
    <Card title={title} sub={sub}>
      {!rows.length ? <div className="muted">{empty}</div> : (
        <div style={{ display: 'grid', gap: 8, maxHeight: 520, overflow: 'auto' }}>
          {rows.map((r) => (
            <div key={r.key} role="button" tabIndex={0} onClick={() => onPick(sel === r.key ? null : r.key)} onKeyDown={(e) => { if (e.key === 'Enter') onPick(sel === r.key ? null : r.key) }}
              style={{ cursor: 'pointer', display: 'grid', gridTemplateColumns: r.image !== undefined ? '44px 1fr' : '1fr', gap: 8, alignItems: 'center', padding: 6, borderRadius: 8,
                border: `1px solid ${sel === r.key ? 'var(--accent)' : 'var(--border)'}`, background: sel === r.key ? 'var(--accent-soft)' : 'transparent', opacity: sel && sel !== r.key ? 0.6 : 1 }}>
              {r.image !== undefined && (
                <div style={{ width: 44, height: 44, borderRadius: 6, background: 'var(--surface-2)', overflow: 'hidden' }}>
                  {r.image && <img src={r.image} alt="" loading="lazy" style={{ width: '100%', height: '100%', objectFit: 'cover' }} onError={(e) => { e.currentTarget.style.display = 'none' }} />}
                </div>
              )}
              <div style={{ minWidth: 0 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 13 }}>
                  <span className="trunc" title={r.label} style={{ minWidth: 0 }}>{r.label}</span><b>{num(r.value)}</b>
                </div>
                <div className="mini-bar"><i style={{ width: `${(r.value / max) * 100}%` }} /></div>
                {r.note && <div className="muted" style={{ fontSize: 11 }}>{r.note}</div>}
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

export default function Flow() {
  const s = useApi('/deeper/flow')
  const [ad, setAd] = useState(null)
  const [concern, setConcern] = useState(null)
  return (
    <Loading state={s}>
      {(d) => {
        if (!d.ready) return <NotBuilt />
        return <FlowBody d={d} ad={ad} setAd={(v) => { setAd(v); setConcern(null) }} concern={concern} setConcern={setConcern} />
      }}
    </Loading>
  )
}

function FlowBody({ d, ad, setAd, concern, setConcern }) {
  const ads = d.ads
  const concerns = useMemo(() => {
    const m = new Map()
    for (const r of d.ad_concern || []) {
      if (ad && r.ad_id !== ad) continue
      const c = m.get(r.concern) || { key: r.concern, label: r.concern, value: 0, orders: 0, quiz: 0, inferred: 0 }
      c.value += r.sessions
      c.orders += r.orders
      c[r.source] += r.sessions
      m.set(r.concern, c)
    }
    return [...m.values()].sort((x, y) => y.value - x.value).slice(0, 12).map((c) => ({ ...c, note: `${c.quiz ? `${num(c.quiz)} from the quiz` : ''}${c.quiz && c.inferred ? ' · ' : ''}${c.inferred ? `${num(c.inferred)} inferred from products` : ''}${c.orders ? ` · ${c.orders} ordered` : ''}` }))
  }, [d, ad])
  const products = useMemo(() => {
    const m = new Map()
    for (const r of d.concern_product || []) {
      if ((ad && r.ad_id !== ad) || (concern && r.concern !== concern)) continue
      const p = m.get(r.product_name) || { key: r.product_name, label: r.product_name, value: 0, carted: 0, ordered: 0, image: r.image || null }
      p.value += r.sessions
      p.carted += r.carted
      p.ordered += r.ordered
      m.set(r.product_name, p)
    }
    return [...m.values()].sort((x, y) => y.value - x.value).slice(0, 14).map((p) => ({ ...p, note: `${p.carted} added to cart · ${p.ordered} ordered` }))
  }, [d, ad, concern])
  const adRows = ads.map((a) => ({ key: a.ad_id, label: a.name || `Ad ${a.ad_id}`, value: a.sessions, image: a.image || null, note: `${pct(a.sessions ? a.with_concern / a.sessions : 0, 0)} showed a concern${a.orders ? ` · ${a.orders} ordered` : ''}` }))
  return (
    <>
      <div className="banner" role="note">
        <span>Pick an ad to see the skin concerns of the visits it brought, then a concern to see the products those visits looked at. A concern is <Badge tone="good">from the quiz</Badge> when the visitor took it, otherwise <Badge>inferred</Badge> from the products they looked at (acne, pigmentation, sun protection and so on: the words are in <span className="mono">mi/deeper_defs.py</span>). Counts are visits.</span>
      </div>
      <div className="grid g3">
        <Col title="1. The ad" sub="Paid Meta ads with 5+ visits" rows={adRows} sel={ad} onPick={setAd} empty="No Paid Meta visits with an ad id in these dates." />
        <Col title="2. The skin concern" sub={ad ? 'for the picked ad' : 'for all these ads'} rows={concerns} sel={concern} onPick={setConcern} empty="No concern could be worked out for these visits." />
        <Col title="3. The products" sub={concern ? `looked at by visits with “${concern}”` : 'looked at, added or bought'} rows={products} sel={null} onPick={() => {}} empty="No product was looked at by these visits." />
      </div>
    </>
  )
}
