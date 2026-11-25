import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { api, inr, num, pct, useApi, useFilters, usePersisted } from '../api'
import { Card, Chips, Kpi, Loading, Table } from '../ui'

const COLORS = { visits: '#3b82f6', checkouts: '#f59e0b', orders: '#16a34a' }
const LAYER_LABEL = { visits: 'Visits', checkouts: 'Checkouts started', orders: 'Orders' }
const SHADES = [['visits', 'Visits'], ['checkouts', 'Checkouts started'], ['orders', 'Orders'], ['checkout_rate', 'Checkout rate'], ['order_rate', 'Order rate'], ['revenue_per_visit', 'Revenue per visit']]
const RATE = new Set(['checkout_rate', 'order_rate', 'revenue_per_visit'])
const MIN_VISITS_FOR_RATE = 30  // a rate from a handful of visits is noise
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
const shadeText = (k, v) => (k === 'checkout_rate' || k === 'order_rate' ? pct(v, 1) : k === 'revenue_per_visit' ? inr(v) : num(v))

function tip(a, basis) {
  return `<b>${esc(a.name)}</b><br>${basis === 'delivery' ? 'Visits with this address' : 'Visits'}: <b>${num(a.visits)}</b><br>`
    + `Checkouts started: <b>${num(a.checkouts)}</b> (${pct(a.checkout_rate, 1)})<br>`
    + `Orders: <b>${num(a.orders)}</b>${a.visits && basis === 'visitor' ? ` (${pct(a.order_rate, 1)})` : ''}<br>Revenue: <b>${inr(a.revenue)}</b>`
}

/** The map: state outlines shaded by one measure, with visits, checkouts and orders drawn as circles on top of each other (biggest at the bottom). */
function GeoMap({ areas, states, layers, shade, level, basis, focus, onOpen }) {
  const el = useRef(null)
  const map = useRef(null)
  const bubbles = useRef(null)
  const outlines = useRef(null)
  const byKey = useRef(new Map())
  const open = useRef(onOpen)
  open.current = onOpen

  useEffect(() => {
    const m = L.map(el.current, { center: [22.5, 80], zoom: 5, minZoom: 3, zoomSnap: 0.5, worldCopyJump: false })
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18, attribution: '© OpenStreetMap contributors' }).addTo(m)
    m.fitBounds([[7, 68], [35.5, 97.5]])
    bubbles.current = L.layerGroup().addTo(m)
    map.current = m
    return () => { m.remove(); map.current = null }
  }, [])

  // state outlines, shaded by the chosen measure at state level
  useEffect(() => {
    const m = map.current
    if (!m || !states) return
    if (outlines.current) outlines.current.remove()
    const byState = new Map(level === 'state' ? areas.map((a) => [a.name, a]) : [])
    const eligible = (a) => a && (!RATE.has(shade) || a.visits >= MIN_VISITS_FOR_RATE)
    const vals = [...byState.values()].filter(eligible).map((a) => a[shade] || 0)
    const max = Math.max(...vals, 0)
    outlines.current = L.geoJSON(states, {
      style: (f) => {
        const a = byState.get(f.properties.name)
        const t = max && eligible(a) ? (a[shade] || 0) / max : 0
        return { color: '#64748b', weight: 0.8, opacity: 0.7, fillColor: '#2563eb', fillOpacity: level === 'state' ? 0.04 + 0.5 * t : 0.03 }
      },
      onEachFeature: (f, layer) => {
        const a = byState.get(f.properties.name)
        if (level === 'state' && a) {
          layer.bindTooltip(`${tip(a, basis)}${RATE.has(shade) && a.visits < MIN_VISITS_FOR_RATE ? '<br><i>too few visits to shade by a rate</i>' : ''}`, { sticky: true })
          layer.on('click', () => open.current(a))
        } else layer.bindTooltip(esc(f.properties.name), { sticky: true })
      },
    }).addTo(m)
    outlines.current.bringToBack()
  }, [states, areas, shade, level, basis])

  // circles: visits (blue, biggest) under checkouts (amber) under orders (green)
  useEffect(() => {
    const g = bubbles.current
    if (!g) return
    g.clearLayers()
    byKey.current = new Map()
    const maxV = Math.max(1, ...areas.map((a) => a.visits), ...(layers.includes('orders') && basis === 'delivery' ? areas.map((a) => a.orders) : [0]))
    const R = level === 'state' ? 44 : level === 'city' ? 34 : 22
    const rad = (v) => (v > 0 ? Math.max(3, R * Math.sqrt(v / maxV)) : 0)
    for (const a of areas) {
      for (const k of ['visits', 'checkouts', 'orders']) {
        if (!layers.includes(k)) continue
        const r = rad(a[k])
        if (!r) continue
        const c = L.circleMarker([a.lat, a.lon], { radius: r, color: COLORS[k], weight: k === 'visits' ? 1 : 1.5, fillColor: COLORS[k], fillOpacity: k === 'visits' ? 0.22 : k === 'checkouts' ? 0.5 : 0.85 })
        c.bindTooltip(tip(a, basis), { sticky: true })
        c.on('click', () => open.current(a))
        c.addTo(g)
        if (!byKey.current.has(a.key)) byKey.current.set(a.key, c)
      }
    }
  }, [areas, layers, level, basis])

  // "show on map" from the table
  useEffect(() => {
    if (!focus || !map.current) return
    const a = areas.find((x) => x.key === focus.key)
    if (!a) return
    map.current.flyTo([a.lat, a.lon], level === 'state' ? 6 : level === 'city' ? 10 : 12, { duration: 0.8 })
    byKey.current.get(a.key)?.openTooltip()
  }, [focus]) // eslint-disable-line react-hooks/exhaustive-deps

  return <div ref={el} className="map-box" role="img" aria-label="Map of visits, checkouts started and orders by area" />
}

export default function MapPage() {
  const f = useFilters()
  const [level, setLevel] = usePersisted('map.level', 'state')
  const [basis, setBasis] = usePersisted('map.basis', 'visitor')
  const [layers, setLayers] = usePersisted('map.layers', ['visits', 'checkouts', 'orders'])
  const [shade, setShade] = usePersisted('map.shade', 'visits')
  const [states, setStates] = useState(null)
  const [focus, setFocus] = useState(null)
  useEffect(() => { api('/geo/states').then(setStates).catch(() => setStates(null)) }, [])
  const s = useApi('/geo/areas', { level, basis })
  const toggle = (k) => setLayers((l) => (l.includes(k) ? l.filter((x) => x !== k) : [...l, k]))
  const open = (a) => {  // the visits behind this area
    const sets = {}
    for (const fl of a.filters) for (const [k, v] of Object.entries(fl)) if (v) (sets[k] ||= new Set()).add(v)
    f.go('sessions', Object.fromEntries(Object.entries(sets).map(([k, v]) => [k, [...v].join(',')])))
  }
  const effBasis = level === 'pincode' ? 'delivery' : basis

  return (
    <>
      <Card title="Where visits, checkouts and orders come from" sub="circles: visits (blue, biggest), checkouts started (amber) and orders (green) drawn on top of each other · click an area to list its visits"
        right={<span className="chip-row"><Chips value={level} onChange={setLevel} options={[{ value: 'state', label: 'State' }, { value: 'city', label: 'City' }, { value: 'pincode', label: 'Pincode' }]} /></span>}>
        <div className="chip-row" style={{ marginBottom: 10, flexWrap: 'wrap', gap: 12 }}>
          <span className="chip-row">
            <span className="muted" style={{ fontSize: 12 }}>Place by</span>
            <Chips value={effBasis} onChange={setBasis} options={[{ value: 'visitor', label: 'Where visitors browse from', disabled: level === 'pincode' }, { value: 'delivery', label: 'Where orders are delivered' }]} />
          </span>
          <span className="chip-row">
            {Object.keys(COLORS).map((k) => (
              <label key={k} className="chk" style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                <input type="checkbox" checked={layers.includes(k)} onChange={() => toggle(k)} />
                <i style={{ width: 11, height: 11, borderRadius: '50%', background: COLORS[k], display: 'inline-block' }} /> {LAYER_LABEL[k]}
              </label>
            ))}
          </span>
          {level === 'state' && (
            <label className="muted" style={{ fontSize: 12 }}>Shade states by{' '}
              <select className="field" value={shade} onChange={(e) => setShade(e.target.value)} aria-label="Shade states by">{SHADES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
            </label>
          )}
        </div>
        <Loading state={s}>
          {(d) => {
            const t = d.totals
            const un = d.unplaced
            const delivery = d.basis === 'delivery'
            const placedVisits = delivery ? (t.visits_with_place ?? 0) - un.visits : t.visits - un.visits
            const denom = delivery ? t.visits_with_place || 0 : t.visits
            return (
              <>
                <div className="kpis" style={{ marginBottom: 10 }}>
                  <Kpi label={delivery ? 'Visits that gave a place' : 'Visits'} value={num(delivery ? t.visits_with_place || 0 : t.visits)} note={delivery ? `of ${num(t.visits)} visits (the rest never gave an address or pincode)` : `${pct(denom ? placedVisits / denom : 0, 0)} placed on the map`} />
                  <Kpi label="Checkouts started" value={num(t.checkouts)} note={`${pct(t.checkout_rate, 1)} of visits`} />
                  <Kpi label="Orders" value={num(t.orders)} note={delivery ? 'delivered orders, all of them' : 'visits that ordered'} />
                  <Kpi label="Revenue" value={inr(t.revenue)} note={`${num(d.area_count)} ${level === 'state' ? 'states' : level === 'city' ? 'cities' : 'pincodes'} on the map`} />
                </div>
                <GeoMap areas={d.areas} states={states} layers={layers} shade={shade} level={d.level} basis={d.basis} focus={focus} onOpen={open} />
                <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
                  {delivery
                    ? 'Orders are the delivered orders of the Orders page, by delivery address. Only the few visitors who gave an address or pincode have a place, so visits and checkouts here are a small part of the total.'
                    : 'Every number comes from the same visits: where they browsed from (the IP address), and whether they started a checkout or ordered. A visitor in Mumbai may have it delivered elsewhere: switch to “Where orders are delivered” for that.'}
                  {' '}The background map needs an internet connection; the circles do not. Outlines are for orientation only.
                  {level === 'state' && RATE.has(shade) ? ` States with fewer than ${MIN_VISITS_FOR_RATE} visits are not shaded by a rate.` : ''}
                </div>
                {(un.visits > 0 || un.orders > 0) && (
                  <div className="banner" style={{ marginTop: 10 }}>
                    <div><b>Not on the map:</b> {num(un.visits)} visits, {num(un.checkouts)} checkout{un.checkouts === 1 ? '' : 's'} started and {num(un.orders)} order{un.orders === 1 ? '' : 's'} ({inr(un.revenue)}) {un.visits + un.orders === 1 ? 'has' : 'have'} no place we can find{!delivery ? ' (no location from the IP address, or a place name we do not know)' : ''}.
                      {d.unplaced_rows.length > 0 && <span className="muted"> Most: {d.unplaced_rows.slice(0, 5).map((r) => `${r.name} (${num(r.visits)})`).join(', ')}</span>}</div>
                  </div>
                )}
              </>
            )
          }}
        </Loading>
      </Card>

      <Loading state={s}>
        {(d) => (
          <Card title={`By ${level === 'state' ? 'state' : level === 'city' ? 'city' : 'pincode'}`} sub="click a row to list its visits · “Show” flies to it on the map">
            <Table id={`geo-${level}`} rows={d.areas} onRow={open} empty="Nothing in this range." cols={[
              { label: level === 'state' ? 'State' : level === 'city' ? 'City' : 'Pincode', sortBy: 'name', render: (r) => <b>{level === 'city' && r.state ? r.name.replace(/, [^,]+$/, '') : r.name}</b> },
              ...(level !== 'state' ? [{ label: 'State', sortBy: 'state', render: (r) => r.state || '–' }] : []),
              { label: 'Visits', num: true, sortBy: 'visits', render: (r) => num(r.visits) },
              { label: 'Share', num: true, sortBy: (r) => r.visits, render: (r) => pct(d.totals.visits ? r.visits / d.totals.visits : 0, 1) },
              { label: 'Carts', hidden: true, num: true, sortBy: 'carts', render: (r) => num(r.carts) },
              { label: 'Checkouts started', num: true, sortBy: 'checkouts', render: (r) => num(r.checkouts) },
              { label: 'Checkout rate', num: true, sortBy: 'checkout_rate', render: (r) => pct(r.checkout_rate, 1) },
              { label: 'Orders', num: true, sortBy: 'orders', render: (r) => num(r.orders) },
              { label: 'Order rate', num: true, sortBy: 'order_rate', render: (r) => (r.visits ? pct(r.order_rate, 1) : '–') },
              { label: 'Revenue', num: true, sortBy: 'revenue', render: (r) => inr(r.revenue) },
              { label: 'Revenue / visit', hidden: true, num: true, sortBy: 'revenue_per_visit', render: (r) => (r.visits ? inr(r.revenue_per_visit) : '–') },
              { label: '', render: (r) => <button type="button" className="btn small" onClick={(e) => { e.stopPropagation(); setFocus({ key: r.key, n: Date.now() }); window.scrollTo({ top: 0, behavior: 'smooth' }) }}>Show</button> },
            ]} />
          </Card>
        )}
      </Loading>
    </>
  )
}
