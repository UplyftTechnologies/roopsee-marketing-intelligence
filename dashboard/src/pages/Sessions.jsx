import { useEffect, useState } from 'react'
import { dt, dur, inr, num, useApi, useFilters, usePersisted } from '../api'
import { Badge, Card, Chips, ExportBtn, Loading, Pager, Search, Table, nextSort } from '../ui'
import { STAGE, STAGE_TONE } from '../shared'
import BulkExclude from '../components/BulkExclude'
import { Journey } from '../components/profile'

const FLAGS = [['product', 'Viewed a product'], ['cart', 'Added to cart'], ['checkout', 'Reached checkout'], ['pay', 'Started payment'], ['order', 'Ordered'], ['login', 'Logged in'], ['quiz', 'Finished the quiz'], ['search', 'Searched'], ['address', 'Gave an address']]
const NOT_FLAGS = FLAGS.filter(([k]) => ['cart', 'checkout', 'order', 'login', 'pay', 'address'].includes(k))
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

/** Multi-select chip group: click to add / remove a flag. */
function FlagPicker({ label, options, value, onChange, hint }) {
  return (
    <div className="chip-row" role="group" aria-label={label}>
      <span className="muted" style={{ fontSize: 12, minWidth: 96 }} title={hint}>{label}</span>
      {options.map(([k, l]) => {
        const on = value.includes(k)
        return <button key={k} type="button" className={`chip ${on ? 'on' : ''}`} aria-pressed={on} onClick={() => onChange(on ? value.filter((x) => x !== k) : [...value, k])}>{on ? '✓ ' : ''}{l}</button>
      })}
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
  const fresh = Boolean(pre.search || pre.channel)
  const [search, setSearch] = usePersisted('sessions.search', pre.search || '', fresh)
  const [channel, setChannel] = usePersisted('sessions.channel', pre.channel || 'All', fresh)
  const [has, setHas] = usePersisted('sessions.has', [], fresh)
  const [lacks, setLacks] = usePersisted('sessions.lacks', [], fresh)
  const [match, setMatch] = usePersisted('sessions.match', 'any', fresh)
  const [only, setOnly] = usePersisted('sessions.only', 'counted', fresh)
  const [pincode, setPincode] = usePersisted('sessions.pincode', '', fresh)
  const [sort, setSort] = usePersisted('sessions.sort', { key: 'started_at', dir: 'desc' }, fresh)
  const [limit, setLimit] = usePersisted('sessions.limit', 50)
  const [offset, setOffset] = useState(0)
  const [sel, setSel] = useState(new Set())
  const pins = pincode.split(/[\s,]+/).filter((x) => /^\d{6}$/.test(x)).join(',')
  const counts = useApi('/sessions/counts')
  const s = useApi('/sessions', {
    search, channel: channel === 'All' ? undefined : channel, has: has.join(',') || undefined, lacks: lacks.join(',') || undefined, match,
    only_excluded: only === 'excluded' || undefined, pincode: pins || undefined, sort: sort.key, direction: sort.dir, limit, offset,
  })
  useEffect(() => { setOffset(0); setSel(new Set()) }, [search, channel, has, lacks, match, only, pins, sort, limit])
  const activePreset = PRESETS.find(([, , h, l, m]) => same(h, has) && same(l, lacks) && (h.length < 2 || m === match))?.[0]
  const toggle = (id) => setSel((p) => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n })
  const toggleAll = (ids, on) => setSel((p) => { const n = new Set(p); ids.forEach((i) => (on ? n.add(i) : n.delete(i))); return n })

  return (
    <>
      <div className="chip-row">
        <Search value={search} onChange={setSearch} placeholder="Search session id, IP, phone, name, email, city, campaign…" />
        <Chips value={only} onChange={setOnly} options={[{ value: 'counted', label: 'Normal view' }, { value: 'excluded', label: 'Only hidden (excluded)' }]} />
      </div>
      <div className="chip-row" role="group" aria-label="Quick views">
        {PRESETS.map(([id, label, h, l, m, key]) => (
          <button key={id} type="button" className={`chip ${activePreset === id ? 'on' : ''}`} onClick={() => { setHas(h); setLacks(l); setMatch(m) }}>
            {label}{key && counts.data ? ` (${num(counts.data[key])})` : ''}
          </button>
        ))}
      </div>
      <Card title="Filter by what the session did" sub="pick any combination; “did not” removes sessions that did that action (for example: added to cart but did not order)">
        <FlagPicker label="Did" options={FLAGS} value={has} onChange={setHas} hint="Sessions where the visitor did these things" />
        {has.length > 1 && (
          <div className="chip-row" style={{ marginTop: 6 }}>
            <span className="muted" style={{ fontSize: 12, minWidth: 96 }}>Match</span>
            <Chips value={match} onChange={setMatch} options={[{ value: 'any', label: 'Any of them' }, { value: 'all', label: 'All of them' }]} />
          </div>
        )}
        <div style={{ marginTop: 6 }}><FlagPicker label="Did not" options={NOT_FLAGS} value={lacks} onChange={setLacks} hint="Exclude sessions that did these things" /></div>
        <div className="chip-row" style={{ marginTop: 6 }}>
          <span className="muted" style={{ fontSize: 12, minWidth: 96 }} title="The pincode the visitor typed or picked as their delivery location">Event pincode</span>
          <input className="field" value={pincode} onChange={(e) => setPincode(e.target.value)} placeholder="e.g. 400001, 560001" aria-label="Pincode" style={{ width: 200 }} />
          {pincode && pins === '' && <span className="muted" style={{ fontSize: 12 }}>enter 6-digit pincodes, separated by commas</span>}
        </div>
        {(has.length > 0 || lacks.length > 0 || pincode) && <div style={{ marginTop: 8 }}><button type="button" className="btn small" onClick={() => { setHas([]); setLacks([]); setMatch('any'); setPincode('') }}>Clear filters</button></div>}
      </Card>
      <Chips value={channel} onChange={setChannel} options={['All', 'Paid Google', 'Paid Meta', 'MyGate Partner', 'Organic Search', 'Organic Social', 'Direct', 'Referral']} />
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
              <Table selectable selected={sel} onToggle={toggle} onToggleAll={toggleAll} rowId={(r) => r.session_id}
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
