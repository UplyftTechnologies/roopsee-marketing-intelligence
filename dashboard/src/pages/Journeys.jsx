import { useEffect, useState } from 'react'
import { KEY_LABEL, dt, dur, inr, num, pct, useApi, useFilters, usePersisted } from '../api'
import { Badge, Card, Chips, ExportBtn, Kpi, Loading, Pager, Search, Table, delta, nextSort } from '../ui'
import { STAGE, STAGE_TONE } from '../shared'
import { Bars, NotBuilt, hours } from './deeper/common'
import JourneyPresets from './JourneyPresets'
import JourneyDetail, { HAS_DETAIL } from './JourneyDetail'

const label = (k) => KEY_LABEL[k] || k.replace(/_/g, ' ')
const CART_JOURNEYS = ['purchase', 'checkout', 'quiz', 'search', 'chat']

/** The funnel: a bar per step, the drop from the step before, and how many stopped right there. */
function FunnelBars({ funnel, prev, onStopped, active }) {
  const top = Math.max(funnel[0]?.count || 0, 1)
  const worst = funnel.reduce((w, x, i) => (i && funnel[i - 1].count >= 20 && (w === null || x.of_prev < funnel[w].of_prev) ? i : w), null)
  const stops = !!onStopped && funnel.some((x) => x.stopped > 0)
  return (
    <div className={`fbars ${stops ? 'with-stops' : ''}`}>
      {funnel.map((x, i) => {
        const d = prev ? delta(x.count, prev[i]) : null
        return (
          <div key={x.key} className="fbar-row">
            <div className="fbar-label">{i + 1}. {x.label}</div>
            <div className="fbar-track" title={`${num(x.count)} · ${pct(x.of_first, 1)} of the first step`}>
              <div className={`fbar-fill ${worst === i ? 'worst' : ''}`} style={{ width: `${Math.max(0.5, (x.count / top) * 100)}%` }} />
            </div>
            <div className="fbar-num">
              <b>{num(x.count)}</b> <span className="muted">{pct(x.of_first, 1)}</span>
              <div className="muted fbar-sub">{i ? `${pct(x.of_prev, 0)} of prev` : 'start'}{d ? ` · ${d.text}` : ''}</div>
            </div>
            {stops && (
              <div className="fbar-stop">
                {x.stopped > 0 && <button type="button" className="btn small" aria-pressed={active === x.key} onClick={() => onStopped(x.key)} title="People who got this far, went no further and never bought">{num(x.stopped)} stopped →</button>}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

/** People who stopped after a step (never bought in these dates). */
function Stopped({ journey, step, stepLabel, by, f, onClose }) {
  const [only, setOnly] = useState(false)
  const s = useApi('/journeys/people', { journey, step, only_reachable: only || undefined, limit: 300 })
  return (
    <Card title={`Stopped after “${stepLabel}”`} sub="people who got this far and went no further, and never bought in these dates · click a row for the person"
      right={<span className="chip-row"><label className="muted" style={{ fontSize: 12 }}><input type="checkbox" checked={only} onChange={(e) => setOnly(e.target.checked)} /> Only with a phone number</label>
        {s.data && <ExportBtn name={`journey-${journey}-after-${step}`} rows={s.data.people} fields={[['Name', 'name'], ['Phone', 'phone10'], ['City', 'city'], ['Last seen', 'last_seen'], ['Cart value', 'cart'], ['Visits', 'visits'], ['Stage', 'segment'], ['Session id', 'session_id']]} />}
        <button type="button" className="btn small" onClick={onClose}>Close</button></span>}>
      <Loading state={s}>
        {({ people, total }) => (
          <>
            <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>{num(total)} {total === 1 ? 'person' : 'people'}{total > people.length ? ` · showing the latest ${num(people.length)}` : ''}{by === 'sessions' ? ' (lists always count people)' : ''}</div>
            <Table scroll onRow={(r) => f.go('person', { key: r.person_key })} rows={people} empty="Nobody stopped here." cols={[
              { label: 'Who', cls: 'nw', render: (r) => r.name || (r.phone10 ? <span className="mono">{r.phone10}</span> : <span className="muted" title="Never logged in on this browser">Guest</span>) },
              { label: 'Phone', cls: 'mono nw', render: (r) => r.phone10 || <span className="muted">–</span> },
              { label: 'City', cls: 'nw', render: (r) => r.city || '–' },
              { label: 'Last seen', cls: 'nw', sortBy: 'last_seen', render: (r) => dt(r.last_seen) },
              { label: 'Cart', num: true, sortBy: 'cart', render: (r) => (r.cart ? inr(r.cart) : '–') },
              { label: 'Visits', num: true, render: (r) => num(r.visits) },
              { label: 'Visit', cls: 'mono nw', render: (r) => <a href={`#session/${encodeURIComponent(r.session_id)}`} onClick={(e) => { e.preventDefault(); e.stopPropagation(); f.go('session', { key: r.session_id }) }}>{r.session_id.slice(0, 10)}…</a> },
            ]} />
          </>
        )}
      </Loading>
    </Card>
  )
}

/** One funnel journey: tiles, the funnel with its biggest drop, what went wrong and who stopped. */
function FunnelJourney({ spec, by, setBy, how, setHow }) {
  const f = useFilters()
  const [open, setOpen] = useState('')
  useEffect(() => { setOpen('') }, [spec.key, by])
  const s = useApi('/journeys/funnel', { journey: spec.key, by, compare: f.compare || undefined })
  return (
    <Loading state={s}>
      {(d) => {
        if (!d.ready) return <NotBuilt />
        const p = d.prev
        const firstLabel = spec.steps[0].label
        const stepLabel = (k) => spec.steps.find((x) => x.key === k)?.label
        return (
          <>
            <div className="chip-row">
              <span className="muted" style={{ fontSize: 12 }}>Count</span>
              <Chips value={by} onChange={setBy} options={[{ value: 'people', label: 'People' }, { value: 'sessions', label: 'Visits' }]} />
              <button type="button" className="btn" aria-expanded={how} onClick={() => setHow(!how)}>{how ? 'Hide how this is counted' : 'How this is counted'}</button>
            </div>
            {how && <Card title={`How this is counted: ${spec.label}`}><ul style={{ margin: 0, paddingLeft: 18, display: 'grid', gap: 4, fontSize: 14 }}>
              {[...spec.how, ['People or visits', 'People counts each person once, however many visits; Visits counts every visit. A step counts for the earlier ones too.'], ['Left out', 'hidden internal traffic, unless “All traffic shown” is on.']].map(([k, v]) => <li key={k}><b>{k}:</b> {v}</li>)}
            </ul></Card>}
            <div className="kpis">
              <Kpi label={firstLabel} value={num(d.entry)} d={p ? delta(d.entry, p.reached[0]) : null} note={by === 'people' ? 'people' : 'visits'} />
              <Kpi label={spec.steps[spec.steps.length - 1].label} value={num(d.final)} d={p ? delta(d.final, p.reached[p.reached.length - 1]) : null} note={`${pct(d.conversion, 1)} of ${firstLabel.toLowerCase()}`} />
              <Kpi label="Biggest drop" value={d.biggest_drop ? pct(1 - d.biggest_drop.rate, 0) : '–'} note={d.biggest_drop ? `${d.biggest_drop.from} → ${d.biggest_drop.to}: ${num(d.biggest_drop.lost)} lost` : 'not enough data'} />
              {CART_JOURNEYS.includes(spec.key) && <Kpi label="Cart value left behind" value={inr(d.cart_at_risk)} d={p ? delta(d.cart_at_risk, p.cart_at_risk) : null} goodWhen="down" note="carts of people who did not buy" />}
              {!CART_JOURNEYS.includes(spec.key) && <Kpi label="Stopped on the way" value={num(d.stopped_total)} note="did not go on, and did not buy" />}
            </div>
            <div className="grid g-funnel">
              <Card title={`${spec.label}: the funnel`} sub={`${spec.blurb} · the orange bar is the biggest drop`}>
                <FunnelBars funnel={d.funnel} prev={p?.reached} active={open} onStopped={by === 'people' ? setOpen : undefined} />
                {by !== 'people' && <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>Switch to People to see who stopped at each step.</div>}
              </Card>
              <Card title={d.wrong.title} sub={d.wrong.sub}>
                <Bars items={d.wrong.items} empty="Nothing recorded." />
              </Card>
            </div>
            {open && <Stopped journey={spec.key} step={open} stepLabel={stepLabel(open)} by={by} f={f} onClose={() => setOpen('')} />}
            {HAS_DETAIL.includes(spec.key) && <JourneyDetail journey={spec.key} />}
          </>
        )
      }}
    </Loading>
  )
}

/** After the order: placed, picked up, out for delivery, delivered. */
function AfterOrder({ spec, how, setHow }) {
  const f = useFilters()
  const s = useApi('/journeys/after_order', { compare: f.compare || undefined })
  return (
    <Loading state={s}>
      {(d) => {
        const p = d.prev
        const t = d.times
        return (
          <>
            <div className="chip-row"><button type="button" className="btn" aria-expanded={how} onClick={() => setHow(!how)}>{how ? 'Hide how this is counted' : 'How this is counted'}</button></div>
            {how && <Card title={`How this is counted: ${spec.label}`}><ul style={{ margin: 0, paddingLeft: 18, display: 'grid', gap: 4, fontSize: 14 }}>{spec.how.map(([k, v]) => <li key={k}><b>{k}:</b> {v}</li>)}</ul></Card>}
            <div className="kpis">
              <Kpi label="Orders placed" value={num(d.orders)} d={p ? delta(d.orders, p.reached[0]) : null} note="valid sales in these dates" />
              <Kpi label="Delivered" value={num(d.funnel[3].count)} d={p ? delta(d.funnel[3].count, p.reached[3]) : null} note={`${pct(d.funnel[3].of_first, 0)} of orders`} />
              <Kpi label="Typical time to deliver" value={hours(t.placed_to_delivered)} note="from the order to the door" />
              <Kpi label="Stuck" value={num(d.stuck_total)} goodWhen="down" note="placed over 48 hours ago, not delivered" />
            </div>
            <div className="grid g2">
              <Card title="From order to door" sub="orders that reached each step">
                <FunnelBars funnel={d.funnel} prev={p?.reached} />
                <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
                  Typical wait: order → picked up {hours(t.placed_to_picked_up)} · picked up → out for delivery {hours(t.picked_up_to_out)} · out → delivered {hours(t.out_to_delivered)}. Payment confirmed: {num(d.confirmed)} of {num(d.orders)} orders.
                </div>
              </Card>
              <Card title="How long delivery takes" sub="from the order to delivery">
                <Bars items={d.buckets} empty="No delivered orders in these dates." />
                <Table rows={d.payment} cols={[{ label: 'Payment', key: 'name' }, { label: 'Orders', num: true, render: (r) => num(r.orders) }, { label: 'Delivered', num: true, render: (r) => num(r.delivered) }, { label: 'Typical time', num: true, render: (r) => hours(r.median_hours) }]} />
              </Card>
            </div>
            <Card title="Orders stuck on the way" sub="placed more than 48 hours ago and not delivered · click an order"
              right={<ExportBtn name="stuck-orders" rows={d.stuck} fields={[['Order', 'order_id'], ['Placed', 'ts'], ['Customer', 'customer_name'], ['Phone', 'phone10'], ['City', 'city'], ['Status', 'status'], ['Payment', 'payment_state'], ['Total', 'total'], ['Hours since placed', 'age_hours']]} />}>
              <Table scroll onRow={(r) => f.go('order', { key: r.order_id })} rows={d.stuck} empty="No order is stuck." cols={[
                { label: 'Placed', cls: 'nw', render: (r) => dt(r.ts) }, { label: 'Customer', render: (r) => r.customer_name || r.phone10 || '–' }, { label: 'City', render: (r) => r.city || '–' },
                { label: 'Status', render: (r) => <Badge>{String(r.status).replace(/_/g, ' ')}</Badge> }, { label: 'Payment', render: (r) => String(r.payment_state).replace(/_/g, ' ') },
                { label: 'Total', num: true, render: (r) => inr(r.total) }, { label: 'Waiting', num: true, sortBy: 'age_hours', render: (r) => hours(r.age_hours) }]} />
            </Card>
          </>
        )
      }}
    </Loading>
  )
}

/** A visit's key actions as a strip of steps. */
function PathStrip({ path, stage }) {
  const steps = path ? path.split(' > ') : []
  if (!steps.length) return <span className="muted">no key action</span>
  return <span>{steps.slice(0, 9).map((k, i) => <span key={i}>{i > 0 && <span className="muted"> → </span>}<span className="chip">{label(k)}</span></span>)}{steps.length > 9 ? <span className="muted"> +{steps.length - 9}</span> : null}</span>
}

const OUTCOMES = [['', 'Any outcome'], ['ordered', 'Ordered'], ['paying', 'Started paying'], ['checkout', 'Reached checkout'], ['cart', 'Added to cart'], ['product', 'Looked at a product'], ['browsed', 'Browsed only']]

/** Every journey: one row per visit or per person, with the path and where it ended. */
function Explorer({ meta }) {
  const f = useFilters()
  const [mode, setMode] = usePersisted('journeys.mode', 'visits')
  const [outcome, setOutcome] = usePersisted('journeys.outcome', '')
  const [journey, setJourney] = usePersisted('journeys.xj', '')
  const [reached, setReached] = usePersisted('journeys.xr', '')
  const [stuck, setStuck] = usePersisted('journeys.xs', false)
  const [ad, setAd] = usePersisted('journeys.ad', f.prefill?.ad ?? '', Boolean(f.prefill?.ad))
  const [roop, setRoop] = usePersisted('journeys.roop', f.prefill?.roop ?? '', Boolean(f.prefill?.roop))
  const [search, setSearch] = usePersisted('journeys.search', '')
  const [sort, setSort] = usePersisted('journeys.sort', { key: 'started_at', dir: 'desc' })
  const [limit, setLimit] = usePersisted('journeys.limit', 50)
  const [offset, setOffset] = useState(0)
  useEffect(() => { setOffset(0) }, [mode, outcome, journey, reached, stuck, ad, roop, search, sort, limit, f.from, f.to, f.includeExcluded, f.deviceType])
  const spec = meta.find((j) => j.key === journey)
  const s = useApi('/journeys/explore', { mode, outcome: outcome || undefined, journey: journey && reached ? journey : undefined, reached: journey && reached ? reached : undefined, stuck: stuck && reached ? true : undefined,
    search: search || undefined, ad: ad || undefined, roop: roop || undefined, sort: sort.key, direction: sort.dir, limit, offset })
  return (
    <>
      <div className="chip-row">
        <Search value={search} onChange={setSearch} placeholder="Search a name, phone, city, campaign, visit id or an action (add_to_cart)…" />
        <Chips value={mode} onChange={(v) => { setMode(v); setSort({ key: v === 'visits' ? 'started_at' : 'last_seen', dir: 'desc' }) }} options={[{ value: 'visits', label: 'Visits' }, { value: 'people', label: 'People (all their visits)' }]} />
        <select className="field" value={outcome} onChange={(e) => setOutcome(e.target.value)} aria-label="Outcome">{OUTCOMES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        <select className="field" value={journey} onChange={(e) => { setJourney(e.target.value); setReached('') }} aria-label="Journey">
          <option value="">Any journey</option>{meta.filter((j) => j.key !== 'after_order').map((j) => <option key={j.key} value={j.key}>{j.label}</option>)}
        </select>
        {spec && (
          <>
            <select className="field" value={reached} onChange={(e) => setReached(e.target.value)} aria-label="Reached step"><option value="">Reached…</option>{spec.steps.map((x) => <option key={x.key} value={x.key}>{x.label}</option>)}</select>
            <label className="muted" style={{ fontSize: 12 }}><input type="checkbox" checked={stuck} disabled={!reached} onChange={(e) => setStuck(e.target.checked)} /> and stopped there</label>
          </>
        )}
        <select className="field" value={roop} onChange={(e) => setRoop(e.target.value)} aria-label="Roop"><option value="">Roop: any</option><option value="opened">Opened Roop</option><option value="asked">Asked Roop</option></select>
        {ad && <button type="button" className="chip on" onClick={() => setAd('')} title="Remove this filter">Ad {ad} ✕</button>}
        {(outcome || journey || search || ad || roop) && <button type="button" className="btn" onClick={() => { setOutcome(''); setJourney(''); setReached(''); setStuck(false); setSearch(''); setAd(''); setRoop('') }}>Clear</button>}
      </div>
      <Loading state={s}>
        {(d) => {
          if (!d.ready) return <NotBuilt />
          return (
            <Card title={`${num(d.total)} ${mode === 'visits' ? 'visits' : 'people'}`} sub={mode === 'visits' ? 'each row is one visit with the key actions it took, in order · click a row for the full session' : 'each row is one person: their visits in order, each coloured by how far it got · click a row for the person'}
              right={<ExportBtn name={`journeys-${mode}`} rows={d.rows} fields={mode === 'visits'
                ? [['Started', 'started_at'], ['Name', 'name'], ['Phone', 'phone10'], ['Channel', 'channel'], ['Campaign', 'campaign'], ['City', 'city'], ['Device', 'device'], ['Path', 'key_events'], ['Outcome', 'stage_name'], ['Order value', 'order_value'], ['Seconds', 'duration_s'], ['Session id', 'session_id']]
                : [['Name', 'name'], ['Phone', 'phone10'], ['City', 'city'], ['First channel', 'first_channel'], ['Visits', 'visits'], ['First seen', 'first_seen'], ['Last seen', 'last_seen'], ['Days between first and last', 'days'], ['Best outcome', 'stage_name'], ['Orders', 'orders'], ['Revenue', 'revenue'], ['Stages', (r) => r.stages.map((x) => STAGE[x]).join(' > ')]]} />}>
              {mode === 'visits' ? (
                <Table scroll sort={sort} onSort={(k) => setSort(nextSort(sort, k, ['channel', 'city']))} onRow={(r) => f.go('session', { key: r.session_id })} rowClass={(r) => (r.is_excluded ? 'excluded' : '')} rows={d.rows}
                  empty="No visits match. Try clearing a filter or widening the dates." cols={[
                    { label: 'Started', cls: 'nw', sortBy: 'started_at', render: (r) => dt(r.started_at) },
                    { label: 'Who', cls: 'nw', render: (r) => r.name || (r.phone10 ? <span className="mono">{r.phone10}</span> : <span className="muted" title="Never logged in on this browser">Guest</span>) },
                    { label: 'Journey', render: (r) => <div style={{ minWidth: 240, maxWidth: 420 }}><PathStrip path={r.key_events} />{r.entered.length > 0 && <div className="muted" style={{ fontSize: 11 }}>also: {r.entered.join(', ')}{r.had_problem ? ' · hit a problem' : ''}</div>}</div> },
                    { label: 'Ended at', cls: 'nw', render: (r) => <Badge tone={STAGE_TONE[r.stage]}>{r.stage_name}</Badge> },
                    { label: 'Order', num: true, sortBy: 'order_value', render: (r) => (r.order_value ? inr(r.order_value) : <span className="muted">–</span>) },
                    { label: 'Channel', cls: 'nw', sortBy: 'channel', render: (r) => <span title={r.campaign}>{r.channel}</span> },
                    { label: 'Place · device', cls: 'nw', sortBy: 'city', render: (r) => `${r.city || '–'} · ${r.is_app ? 'App' : r.device || '–'}` },
                    { label: 'Time', num: true, sortBy: 'duration', render: (r) => dur(r.duration_s) }]} />
              ) : (
                <Table scroll sort={sort} onSort={(k) => setSort(nextSort(sort, k, []))} onRow={(r) => f.go('person', { key: r.person_key })} rows={d.rows} empty="Nobody matches." cols={[
                  { label: 'Who', cls: 'nw', render: (r) => r.name || (r.phone10 ? <span className="mono">{r.phone10}</span> : <span className="muted" title="Never logged in on this browser">Guest</span>) },
                  { label: 'Their visits, in order', render: (r) => (
                    <span>{r.stages.map((st, i) => <span key={i}>{i > 0 && <span className="muted"> → </span>}<span title={`${r.channels[i] || ''}`}><Badge tone={STAGE_TONE[st]}>{STAGE[st]}</Badge></span></span>)}{r.visits > r.stages.length ? <span className="muted"> … {num(r.visits)} visits</span> : null}</span>
                  ) },
                  { label: 'Visits', num: true, sortBy: 'visits', render: (r) => num(r.visits) },
                  { label: 'Span', num: true, render: (r) => (r.visits > 1 ? `${r.days < 1 ? '<1' : r.days} days` : '–') },
                  { label: 'First channel', cls: 'nw', render: (r) => r.first_channel || '–' },
                  { label: 'Best outcome', cls: 'nw', render: (r) => <Badge tone={STAGE_TONE[r.stage]}>{r.stage_name}</Badge> },
                  { label: 'Orders', num: true, sortBy: 'orders', render: (r) => num(r.orders) },
                  { label: 'Last seen', cls: 'nw', sortBy: 'last_seen', render: (r) => dt(r.last_seen) }]} />
              )}
              <Pager total={d.total} limit={limit} offset={offset} setOffset={setOffset} setLimit={setLimit} />
            </Card>
          )
        }}
      </Loading>
    </>
  )
}

export default function Journeys() {
  const m = useApi('/journeys/meta', {}, { scoped: false })
  const [tab, setTab] = usePersisted('journeys.tab', 'purchase')
  const [by, setBy] = usePersisted('journeys.by', 'people')
  const [how, setHow] = useState(false)
  return (
    <Loading state={m}>
      {(d) => {
        if (!d.ready) return <NotBuilt />
        const tabs = [...d.journeys.map((j) => ({ value: j.key, label: j.label })), { value: 'explore', label: 'Every journey' }, { value: 'presets', label: '★ My presets' }]
        const spec = d.journeys.find((j) => j.key === tab)
        return (
          <>
            <div className="chip-row" role="group" aria-label="Journey view"><Chips value={tab} onChange={(v) => { setTab(v); setHow(false) }} options={tabs} /></div>
            {tab === 'presets' ? <JourneyPresets />
              : tab === 'explore' ? <Explorer meta={d.journeys} />
              : tab === 'after_order' ? <AfterOrder spec={spec} how={how} setHow={setHow} />
                : spec ? <FunnelJourney key={tab} spec={spec} by={by} setBy={setBy} how={how} setHow={setHow} /> : null}
          </>
        )
      }}
    </Loading>
  )
}
