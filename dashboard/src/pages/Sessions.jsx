import { useEffect, useState } from 'react'
import { dt, dur, inr, num, useApi, useFilters, usePersisted } from '../api'
import { Badge, Card, Chips, ExportBtn, Loading, Pager, Search, Table, nextSort } from '../ui'
import { STAGE, STAGE_TONE } from '../shared'
import BulkExclude from '../components/BulkExclude'
import ShareLink from '../components/ShareLink'
import { Journey } from '../components/profile'

// what a session can have done, grouped; each row is a three-way choice: Any / Did / Did not
const GROUPS = [
  ['Shopping', [['product', 'Viewed a product'], ['cart', 'Added to cart'], ['checkout', 'Reached checkout'], ['pay', 'Started payment'], ['order', 'Ordered']]],
  ['Account', [['login', 'Known user', 'Logged in during this session or at any other time'], ['login_now', 'Logged in this session']]],
  ['Engagement', [['quiz', 'Finished the quiz'], ['search', 'Searched']]],
  ['Delivery', [['address', 'Saved an address', 'Saved a full address with a valid pincode'], ['location', 'Chose pincode / location', 'Typed a pincode, searched a place, used current location or picked a saved address']]],
]
const LABEL = Object.fromEntries(GROUPS.flatMap(([, rows]) => rows.map(([k, l]) => [k, l])))
const PRESETS = [
  ['all', 'All sessions', [], [], 'any', null],
  ['cart_abandoners', 'Cart abandoners', ['cart'], ['order'], 'any', 'cart_abandoners'],
  ['checkout_abandoners', 'Checkout abandoners', ['checkout'], ['order'], 'any', 'checkout_abandoners'],
  ['logged_in', 'Logged in', ['login'], [], 'any', 'logged_in'],
  ['ordered', 'Ordered', ['order'], [], 'any', 'ordered'],
]
const STAGE_SHORT = ['Browsed', 'Product', 'Cart', 'Checkout', 'Payment', 'Ordered']
const TEXT_SORTS = ['name', 'email', 'channel', 'city', 'device', 'campaign', 'pincode']
const same = (a, b) => a.length === b.length && a.every((x) => b.includes(x))

/** One behaviour as a three-way switch. */
function FlagRow({ label, hint, state, onChange }) {
  return (
    <div className="flag-row" title={hint}>
      <span className={`flag-name ${state !== 'any' ? 'on' : ''}`}>{label}</span>
      <span className="seg" role="group" aria-label={label}>
        {[['any', 'Any'], ['did', 'Did'], ['not', 'Did not']].map(([k, l]) => (
          <button key={k} type="button" className={state === k ? `on ${k}` : ''} aria-pressed={state === k} onClick={() => onChange(k)}>{l}</button>
        ))}
      </span>
    </div>
  )
}

function OrderValue({ r }) {
  if (r.order_value) return <span title={r.order_statuses}><b>{inr(r.order_value)}</b>{r.order_count > 1 ? <span className="muted"> ×{r.order_count}</span> : null}</span>
  if (r.order_other_value) return <span className="muted" title={`${r.order_statuses}: not counted as a sale`}>{inr(r.order_other_value)} <small>({(r.order_statuses || '').split(',')[0].replace('payment_', '')})</small></span>
  return <span className="muted">–</span>
}

export default function Sessions() {
  const f = useFilters()
  const pre = f.prefill || {}
  // filters are remembered while you open a session / person and come back; a drill-down from another tab starts fresh
  const sh = pre.share || null  // opened from a shared link
  const fresh = Boolean(pre.search || pre.channel || sh)
  const [search, setSearch] = usePersisted('sessions.search', sh?.search ?? (pre.search || ''), fresh)
  const [channel, setChannel] = usePersisted('sessions.channel', sh?.channel ?? (pre.channel || 'All'), fresh)
  const [has, setHas] = usePersisted('sessions.has', sh?.has ?? [], fresh)
  const [lacks, setLacks] = usePersisted('sessions.lacks', sh?.lacks ?? [], fresh)
  const [match, setMatch] = usePersisted('sessions.match2', sh?.match ?? 'all', fresh)
  const [only, setOnly] = usePersisted('sessions.only', sh?.only ?? 'counted', fresh)
  const [pincode, setPincode] = usePersisted('sessions.pincode', sh?.pincode ?? '', fresh)
  const [event, setEvent] = usePersisted('sessions.event', sh?.event ?? '', fresh)
  const evNames = useApi('/events/names', {}, { scoped: false })
  const [sort, setSort] = usePersisted('sessions.sort', sh?.sort ?? { key: 'started_at', dir: 'desc' }, fresh)
  const [limit, setLimit] = usePersisted('sessions.limit', 50)
  const [panel, setPanel] = usePersisted('sessions.panel', false)
  const [offset, setOffset] = useState(0)
  const [sel, setSel] = useState(new Set())
  const pins = pincode.split(/[\s,]+/).filter((x) => /^\d{6}$/.test(x)).join(',')
  const counts = useApi('/sessions/counts')
  const s = useApi('/sessions', {
    search, channel: channel === 'All' ? undefined : channel, has: has.join(',') || undefined, lacks: lacks.join(',') || undefined, match,
    only_excluded: only === 'excluded' || undefined, pincode: pins || undefined, event: event.trim() || undefined, sort: sort.key, direction: sort.dir, limit, offset,
  })
  useEffect(() => { setOffset(0); setSel(new Set()) }, [search, channel, has, lacks, match, only, pins, event, sort, limit])
  const activePreset = PRESETS.find(([, , h, l, m]) => same(h, has) && same(l, lacks) && (h.length < 2 || m === match))?.[0]
  const stateOf = (k) => (has.includes(k) ? 'did' : lacks.includes(k) ? 'not' : 'any')
  const setFlag = (k, st) => {
    setHas((h) => (st === 'did' ? [...h.filter((x) => x !== k), k] : h.filter((x) => x !== k)))
    setLacks((l) => (st === 'not' ? [...l.filter((x) => x !== k), k] : l.filter((x) => x !== k)))
  }
  const clearAll = () => { setHas([]); setLacks([]); setMatch('all'); setPincode(''); setEvent(''); setChannel('All'); setSearch(''); setOnly('counted') }
  const activeChips = [
    ...has.map((k) => ({ id: `d-${k}`, text: `Did: ${LABEL[k]}`, off: () => setFlag(k, 'any') })),
    ...lacks.map((k) => ({ id: `n-${k}`, text: `Did not: ${LABEL[k]}`, off: () => setFlag(k, 'any') })),
    ...(event.trim() ? [{ id: 'ev', text: `Had event: ${event.trim()}`, off: () => setEvent('') }] : []),
    ...(pins ? [{ id: 'pin', text: `Pincode: ${pins.split(',').join(', ')}`, off: () => setPincode('') }] : []),
    ...(channel !== 'All' ? [{ id: 'ch', text: `Channel: ${channel}`, off: () => setChannel('All') }] : []),
    ...(only === 'excluded' ? [{ id: 'ex', text: 'Only hidden sessions', off: () => setOnly('counted') }] : []),
  ]
  const nFilters = activeChips.length
  const toggle = (id) => setSel((p) => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n })
  const toggleAll = (ids, on) => setSel((p) => { const n = new Set(p); ids.forEach((i) => (on ? n.add(i) : n.delete(i))); return n })

  return (
    <>
      <div className="chip-row">
        <Search value={search} onChange={setSearch} placeholder="Search session id, IP, phone, name, email, city, campaign, pincode, or an event name (add_to_cart)…" />
        <Chips value={only} onChange={setOnly} options={[{ value: 'counted', label: 'Normal view' }, { value: 'excluded', label: 'Only hidden (excluded)' }]} />
        <button type="button" className={`btn ${nFilters ? 'primary' : ''}`} aria-expanded={panel} onClick={() => setPanel(!panel)}>
          Filters{nFilters ? ` · ${nFilters}` : ''} {panel ? '▴' : '▾'}
        </button>
        {(nFilters > 0 || search) && <button type="button" className="btn" onClick={clearAll}>Clear all</button>}
        <ShareLink tab="sessions" state={{ search, channel, has, lacks, match, only, pincode, event, sort }} />
      </div>
      <div className="chip-row" role="group" aria-label="Quick views">
        <span className="muted" style={{ fontSize: 12 }}>Quick views</span>
        {PRESETS.map(([id, label, h, l, m, key]) => (
          <button key={id} type="button" className={`chip ${activePreset === id ? 'on' : ''}`} onClick={() => { setHas(h); setLacks(l); setMatch('all') }}>
            {label}{key && counts.data ? ` (${num(counts.data[key])})` : ''}
          </button>
        ))}
      </div>
      {activeChips.length > 0 && (
        <div className="chip-row" role="status" aria-label="Active filters">
          <span className="muted" style={{ fontSize: 12 }}>Showing sessions with</span>
          {activeChips.map((c) => <button key={c.id} type="button" className="chip on" onClick={c.off} title="Remove this filter">{c.text} ✕</button>)}
        </div>
      )}
      {panel && (
        <Card title="Filter sessions" sub="for each action choose Any (ignore it), Did, or Did not. For example: Added to cart = Did, Ordered = Did not">
          <div className="filter-grid">
            {GROUPS.map(([title, rows]) => (
              <div key={title} className="filter-group">
                <div className="filter-title">{title}</div>
                {rows.map(([k, label, hint]) => <FlagRow key={k} label={label} hint={hint} state={stateOf(k)} onChange={(st) => setFlag(k, st)} />)}
              </div>
            ))}
            <div className="filter-group">
              <div className="filter-title">Source & place</div>
              <label className="flag-row"><span className="flag-name">Channel</span>
                <select className="field" value={channel} onChange={(e) => setChannel(e.target.value)} aria-label="Channel">
                  {['All', ...(counts.data?.channels || [])].map((c) => <option key={c}>{c}</option>)}
                </select>
              </label>
              <label className="flag-row" title="Sessions that contain this event. Pick from the list or type part of a name; separate several with commas (any of them)"><span className="flag-name">Had event</span>
                <input className="field" list="event-names" value={event} onChange={(e) => setEvent(e.target.value)} placeholder="checked_delivery_pincode" aria-label="Had event" style={{ width: 200 }} />
                <datalist id="event-names">{(evNames.data || []).map((e) => <option key={e.event_name} value={e.event_name}>{`${e.sessions} sessions`}</option>)}</datalist>
              </label>
              <label className="flag-row" title="The pincode the visitor typed or picked as their delivery location"><span className="flag-name">Pincode</span>
                <input className="field" value={pincode} onChange={(e) => setPincode(e.target.value)} placeholder="400001, 560001" aria-label="Pincode" style={{ width: 150 }} />
              </label>
              {pincode && pins === '' && <div className="muted" style={{ fontSize: 12 }}>6-digit pincodes, separated by commas</div>}
            </div>
          </div>
          {has.length > 1 && (
            <div className="chip-row" style={{ marginTop: 12 }}>
              <span className="muted" style={{ fontSize: 12 }}>With several Did choices, show sessions that did</span>
              <Chips value={match} onChange={setMatch} options={[{ value: 'all', label: 'All of them' }, { value: 'any', label: 'Any one of them' }]} />
            </div>
          )}
        </Card>
      )}
      <Loading state={s}>
        {({ rows, total }) => {
          const chosen = rows.filter((r) => sel.has(r.session_id))
          return (
            <Card title={`${num(total)} sessions`} sub="click a row for the full session · click a column title to sort · tick rows to exclude them in bulk"
              right={<ExportBtn name="sessions" rows={rows} fields={[['Started', 'started_at'], ['Name', 'name'], ['Email', 'email'], ['Phone', 'phone10'], ['Journey', 'key_events'], ['Order value', 'order_value'], ['Channel', 'channel'], ['Campaign', 'campaign'], ['City', 'city'], ['Pincode', 'pincode'], ['Device', 'device'], ['Events', 'events'], ['Seconds', 'duration_s'], ['IP', 'ip'], ['Session id', 'session_id']]} />}>
              <BulkExclude rows={chosen} noun="sessions" onClear={() => setSel(new Set())} fields={[
                { label: 'browser', kind: 'visitor_id', get: (r) => r.visitor_key }, { label: 'user account', kind: 'user_id', get: (r) => r.user_id },
                { label: 'phone number', kind: 'phone', get: (r) => r.phone10 }, { label: 'IP address', kind: 'ip', get: (r) => r.ip }, { label: 'session', kind: 'session_id', get: (r) => r.session_id },
              ]} />
              <Table scroll selectable selected={sel} onToggle={toggle} onToggleAll={toggleAll} rowId={(r) => r.session_id}
                sort={sort} onSort={(k) => setSort(nextSort(sort, k, TEXT_SORTS))}
                onRow={(r) => f.go('session', { key: r.session_id })} rowClass={(r) => (r.is_excluded ? 'excluded' : '')} cols={[
                  { label: 'Started', cls: 'nw', sortBy: 'started_at', render: (r) => <>{dt(r.started_at)}{r.is_excluded && <div><Badge tone="bad">excluded</Badge></div>}</> },
                  { label: 'Who', cls: 'nw', sortBy: 'name', render: (r) => r.name || (r.phone10 ? <span className="mono">{r.phone10}</span> : <span className="muted">anonymous</span>) },
                  { label: 'Email', cls: 'nw', sortBy: 'email', render: (r) => (r.email ? <span className="trunc" style={{ display: 'block', maxWidth: 160 }} title={r.email}>{r.email}</span> : <span className="muted">–</span>) },
                  { label: 'Journey', render: (r) => <div style={{ minWidth: 220, maxWidth: 300 }}>{r.key_events ? <Journey keyEvents={r.key_events} /> : <span className="muted">{r.events} event{r.events === 1 ? '' : 's'}, no key action</span>}</div> },
                  { label: 'Stage', cls: 'nw', sortBy: 'stage', render: (r) => <span title={STAGE[r.stage]}><Badge tone={STAGE_TONE[r.stage]}>{STAGE_SHORT[r.stage]}</Badge></span> },
                  { label: 'Order value', num: true, sortBy: 'order_value', render: (r) => <OrderValue r={r} /> },
                  { label: 'Channel', cls: 'nw', sortBy: 'channel', render: (r) => <span title={`${r.source} / ${r.medium} / ${r.campaign}`}>{r.channel}</span> },
                  { label: 'Place · device', cls: 'nw', sortBy: 'city', render: (r) => `${r.city || r.region || '–'} · ${r.is_app ? 'App' : r.device || '–'}` },
                  { label: 'Pincode', cls: 'mono nw', sortBy: 'pincode', render: (r) => r.pincode || <span className="muted">–</span> },
                  { label: 'Events', num: true, sortBy: 'events', render: (r) => r.events }, { label: 'Time', num: true, sortBy: 'duration_s', render: (r) => dur(r.duration_s) },
                ]} rows={rows} empty="No sessions match these filters. Try clearing a filter or widening the date range." />
              <Pager total={total} limit={limit} offset={offset} setOffset={setOffset} setLimit={setLimit} />
            </Card>
          )
        }}
      </Loading>
    </>
  )
}
