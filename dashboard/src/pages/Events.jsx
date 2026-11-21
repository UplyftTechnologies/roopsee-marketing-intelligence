import { useEffect, useState } from 'react'
import { api, dt, num, useApi, useFilters, usePersisted } from '../api'
import { Badge, Card, Chips, ExportBtn, Kpi, Loading, Pager, Search, Table, nextSort } from '../ui'
import ShareLink from '../components/ShareLink'

const KEY_ALL = '(not a key event)'
const TEXT_SORTS = ['event_name', 'session_id', 'page', 'product', 'search_term', 'city', 'who']
const DIMS = [['event_name', 'Event name'], ['event_key', 'Key-event group'], ['day', 'Day'], ['hour', 'Hour of day'], ['page_type', 'Page type'], ['path', 'Page'], ['product', 'Product'],
  ['search_term', 'Search term'], ['city', 'City'], ['device', 'Device'], ['channel', 'Channel'], ['campaign', 'Campaign']]
const DIM_LABEL = Object.fromEntries(DIMS)
const OPS = [['=', 'is'], ['~', 'contains'], ['?', 'has a value']]
const OP_TEXT = { '=': '=', '~': 'contains', '?': 'is set' }

const pretty = (p) => {  // 'field=value' -> {field, op, value}
  const m = /^([A-Za-z0-9_-]+)(?:([=~])(.*))?$/s.exec(p) || []
  return { field: m[1] || p, op: m[2] || '?', value: m[3] ?? '' }
}
const asText = (p) => { const x = pretty(p); return x.op === '?' ? `${x.field} is set` : `${x.field} ${OP_TEXT[x.op]} ${x.value}` }

/** Tiny trend line for a list of [date, count]. */
function Spark({ data }) {
  if (!data || data.length < 2) return <span className="muted">–</span>
  const w = 90; const h = 22
  const max = Math.max(...data.map((d) => d[1]), 1)
  const pts = data.map((d, i) => `${(i / (data.length - 1)) * w},${h - 2 - (d[1] / max) * (h - 4)}`).join(' ')
  return <svg width={w} height={h} aria-label="Trend by day" role="img"><polyline points={pts} fill="none" stroke="var(--series-1)" strokeWidth="1.5" /></svg>
}

export default function Events() {
  const f = useFilters()
  const pre = f.prefill || {}
  const sh = pre.share || null
  const fresh = Boolean(pre.event || pre.session || pre.person || pre.search || pre.payload || sh)
  const drill = Boolean(pre.event || pre.session || pre.person || pre.payload || sh?.view === 'rows')
  const [view, setView] = usePersisted('events.view', sh?.view ?? (drill ? 'rows' : 'catalogue'), fresh)
  const [names, setNames] = usePersisted('events.names', sh?.names ?? (pre.event ? String(pre.event).split(',').filter(Boolean) : []), fresh)
  const [key, setKey] = usePersisted('events.key', sh?.key ?? '', fresh)
  const [payload, setPayload] = usePersisted('events.payload', sh?.payload ?? pre.payload ?? [], fresh)
  const [session, setSession] = usePersisted('events.session', sh?.session ?? pre.session ?? '', fresh)
  const [person, setPerson] = usePersisted('events.person', sh?.person ?? pre.person ?? '', fresh)
  const [channel, setChannel] = usePersisted('events.channel', sh?.channel ?? '', fresh)
  const [search, setSearch] = usePersisted('events.search', sh?.search ?? pre.search ?? '', fresh)
  const [dup, setDup] = usePersisted('events.dup', sh?.dup ?? false, fresh)
  const [by, setBy] = usePersisted('events.by', sh?.by ?? '', fresh)
  const [cols, setCols] = usePersisted('events.cols', sh?.cols ?? [], fresh)
  const [sort, setSort] = usePersisted('events.sort', sh?.sort ?? { key: 'ts', dir: 'desc' }, fresh)
  const [limit, setLimit] = usePersisted('events.limit', 50)

  const scope = { event: names.join(',') || undefined, key: key || undefined, payload: payload.length ? payload : undefined, session: session || undefined,
    person: person || undefined, channel: channel || undefined, search: search || undefined, include_dup: dup || undefined }
  const chips = [
    ...names.map((n) => ({ id: `n-${n}`, text: `Event: ${n}`, off: () => setNames(names.filter((x) => x !== n)) })),
    ...(key ? [{ id: 'k', text: `Group: ${key}`, off: () => setKey('') }] : []),
    ...payload.map((p) => ({ id: `p-${p}`, text: asText(p), off: () => setPayload(payload.filter((x) => x !== p)) })),
    ...(session ? [{ id: 's', text: `Session: ${session.slice(0, 14)}…`, off: () => setSession('') }] : []),
    ...(person ? [{ id: 'pe', text: `Person: ${person.slice(0, 14)}…`, off: () => setPerson('') }] : []),
    ...(channel ? [{ id: 'c', text: `Channel: ${channel}`, off: () => setChannel('') }] : []),
  ]
  const clearAll = () => { setNames([]); setKey(''); setPayload([]); setSession(''); setPerson(''); setChannel(''); setSearch(''); setBy(''); setCols([]) }
  const drillTo = (patch) => { if (patch.names) setNames(patch.names); setView('rows') }
  const addPayload = (p) => setPayload((x) => (x.includes(p) ? x : [...x, p]))

  return (
    <>
      <div className="chip-row">
        <Search value={search} onChange={setSearch} placeholder="Search event name, session id, page, product, search term, phone, order id or any payload text…" />
        <Chips value={view} onChange={setView} options={[{ value: 'catalogue', label: 'Event catalogue' }, { value: 'rows', label: 'Event rows' }]} />
        <label className="muted" style={{ fontSize: 12 }} title="The tracker often fires the same action several times within 2 seconds. They are hidden by default.">
          <input type="checkbox" checked={dup} onChange={(e) => setDup(e.target.checked)} /> Include repeated events
        </label>
        {(chips.length > 0 || search) && <button type="button" className="btn" onClick={clearAll}>Clear all</button>}
        <ShareLink tab="events" state={{ view, names, key, payload, session, person, channel, search, dup, by, cols, sort }} />
      </div>
      {chips.length > 0 && (
        <div className="chip-row" role="status" aria-label="Active filters">
          <span className="muted" style={{ fontSize: 12 }}>Showing events where</span>
          {chips.map((c) => <button key={c.id} type="button" className="chip on" onClick={c.off} title="Remove this filter">{c.text} ✕</button>)}
        </div>
      )}
      {view === 'catalogue'
        ? <Catalogue scope={scope} key_={key} setKey={setKey} onPick={(n) => drillTo({ names: [n] })} search={search} />
        : <Rows scope={scope} names={names} setNames={setNames} payload={payload} addPayload={addPayload} by={by} setBy={setBy} cols={cols} setCols={setCols}
            sort={sort} setSort={setSort} limit={limit} setLimit={setLimit} setKey={setKey} setChannel={setChannel} resetKey={JSON.stringify(scope)} />}
    </>
  )
}

/* ---------------------------------------------------------------- high level */
function Catalogue({ scope, key_, setKey, onPick, search }) {
  const { event, payload, session, person, channel, search: _s, ...rest } = scope // the catalogue lists event names, so only dates / repeats / group apply
  const s = useApi('/events/summary', { include_dup: rest.include_dup, key: key_ || undefined, search: search || undefined })
  return (
    <Loading state={s}>
      {({ totals, rows, keys }) => (
        <>
          <div className="kpis">
            <Kpi label="Events" value={num(totals.events)} note="tracked in this range" />
            <Kpi label="Event names" value={num(totals.names)} />
            <Kpi label="Sessions" value={num(totals.sessions)} />
            <Kpi label="People" value={num(totals.people)} help="people" />
          </div>
          <div className="chip-row" role="group" aria-label="Key-event groups">
            <span className="muted" style={{ fontSize: 12 }}>Group</span>
            <button type="button" className={`chip ${!key_ ? 'on' : ''}`} onClick={() => setKey('')}>All</button>
            {keys.map((k) => <button key={k.k} type="button" className={`chip ${key_ === k.k ? 'on' : ''}`} onClick={() => setKey(k.k)}>{k.k} ({num(k.n)})</button>)}
          </div>
          <Card title={`${num(rows.length)} event names`} sub="click an event to see every row, its sessions and payload fields · click a title to sort"
            right={<ExportBtn name="event-catalogue" rows={rows} fields={[['Event', 'event_name'], ['Group', 'event_key'], ['Events', 'events'], ['Sessions', 'sessions'], ['People', 'people'], ['First seen', 'first_seen'], ['Last seen', 'last_seen']]} />}>
            <Table scroll onRow={(r) => onPick(r.event_name)} rows={rows} empty="No events in this range. Try a wider date range or include internal traffic." cols={[
              { label: 'Event', key: 'event_name', cls: 'mono', sortBy: 'event_name', render: (r) => r.event_name },
              { label: 'Group', sortBy: 'event_key', render: (r) => (r.event_key === KEY_ALL ? <span className="muted">–</span> : <Badge>{r.event_key}</Badge>) },
              { label: 'Events', num: true, sortBy: 'events', render: (r) => num(r.events) },
              { label: 'Sessions', num: true, sortBy: 'sessions', render: (r) => num(r.sessions) },
              { label: 'People', num: true, sortBy: 'people', render: (r) => num(r.people) },
              { label: 'Trend', render: (r) => <Spark data={r.trend} /> },
              { label: 'First seen', cls: 'nw', sortBy: 'first_seen', render: (r) => dt(r.first_seen) },
              { label: 'Last seen', cls: 'nw', sortBy: 'last_seen', render: (r) => dt(r.last_seen) },
            ]} />
          </Card>
        </>
      )}
    </Loading>
  )
}

/* ---------------------------------------------------------------- low level + slicing */
function Rows({ scope, names, setNames, payload, addPayload, by, setBy, cols, setCols, sort, setSort, limit, setLimit, setKey, setChannel, resetKey }) {
  const f = useFilters()
  const [offset, setOffset] = useState(0)
  const [open, setOpen] = useState(null)
  const [builder, setBuilder] = useState({ field: '', op: '=', value: '' })
  const [vals, setVals] = useState([])
  const evNames = useApi('/events/names', {}, { scoped: false })
  const fields = useApi('/events/fields', { event: scope.event })
  const fieldList = fields.data?.fields || []
  useEffect(() => { setOffset(0); setOpen(null) }, [resetKey, sort, limit])
  useEffect(() => {  // most common values of the chosen field, for the value box
    if (!builder.field) { setVals([]); return undefined }
    let live = true
    api('/events/values', { params: { field: builder.field, event: scope.event, date_from: f.from, date_to: f.to, include_excluded: f.includeExcluded, device_type: (f.deviceApplies && f.deviceType) || undefined, limit: 30 } })
      .then((d) => live && setVals(d.rows)).catch(() => live && setVals([]))
    return () => { live = false }
  }, [builder.field, scope.event, f.from, f.to, f.includeExcluded, f.deviceType, f.tick])  // eslint-disable-line react-hooks/exhaustive-deps

  const rows = useApi('/events/rows', { ...scope, cols: cols.join(',') || undefined, sort: sort.key, direction: sort.dir, limit, offset })
  const toggleCol = (c) => setCols((x) => (x.includes(c) ? x.filter((y) => y !== c) : x.length < 8 ? [...x, c] : x))
  const addFilter = () => {
    if (!builder.field) return
    if (builder.op !== '?' && builder.value === '') return
    addPayload(builder.op === '?' ? builder.field : `${builder.field}${builder.op}${builder.value}`)
    setBuilder({ ...builder, value: '' })
  }
  // clicking a value in the slice table narrows to it (only the dimensions the server can filter on)
  const sliceClick = (v) => {
    if (by.startsWith('payload:')) addPayload(`${by.slice(8)}=${v}`)
    else if (by === 'event_name') setNames([...new Set([...names, v])])
    else if (by === 'event_key') setKey(v)
    else if (by === 'channel') setChannel(v)
    else return
    setBy('')
  }
  const clickable = by.startsWith('payload:') || ['event_name', 'event_key', 'channel'].includes(by)
  const byLabel = by.startsWith('payload:') ? by.slice(8) : DIM_LABEL[by] || 'Event name'

  return (
    <>
      <Card title="Filter" sub="narrow by event name and by any field the event carries, for example quiz_option = acne">
        <div className="filter-grid">
          <div className="filter-group">
            <div className="filter-title">Event name</div>
            <input className="field" list="ev-list" placeholder="Type or pick an event, press Enter" aria-label="Add event name" style={{ width: 260 }}
              onKeyDown={(e) => { if (e.key === 'Enter' && e.currentTarget.value.trim()) { const v = e.currentTarget.value.trim(); setNames([...new Set([...names, v])]); e.currentTarget.value = '' } }}
              onChange={(e) => { const v = e.target.value; if ((evNames.data || []).some((n) => n.event_name === v)) { setNames([...new Set([...names, v])]); e.target.value = '' } }} />
            <datalist id="ev-list">{(evNames.data || []).map((n) => <option key={n.event_name} value={n.event_name}>{`${num(n.sessions)} sessions`}</option>)}</datalist>
          </div>
          <div className="filter-group">
            <div className="filter-title">Payload field</div>
            <div className="chip-row">
              <select className="field" value={builder.field} onChange={(e) => setBuilder({ ...builder, field: e.target.value, value: '' })} aria-label="Payload field">
                <option value="">Field…</option>
                {fieldList.map((x) => <option key={x.field} value={x.field}>{x.field} ({Math.round(x.share * 100)}%)</option>)}
              </select>
              <select className="field" value={builder.op} onChange={(e) => setBuilder({ ...builder, op: e.target.value })} aria-label="Operator">
                {OPS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
              {builder.op !== '?' && (
                <>
                  <input className="field" list="val-list" value={builder.value} placeholder={builder.field ? 'value' : 'pick a field first'} disabled={!builder.field} aria-label="Value"
                    onChange={(e) => setBuilder({ ...builder, value: e.target.value })} onKeyDown={(e) => { if (e.key === 'Enter') addFilter() }} style={{ width: 200 }} />
                  <datalist id="val-list">{vals.map((v) => <option key={v.value} value={v.value}>{`${num(v.events)} events`}</option>)}</datalist>
                </>
              )}
              <button type="button" className="btn" onClick={addFilter} disabled={!builder.field}>Add filter</button>
            </div>
            {fields.data && <div className="muted" style={{ fontSize: 12 }}>{fieldList.length} fields found in the latest {num(fields.data.sampled)} matching events. % = how many events carry it.</div>}
          </div>
        </div>
        {fieldList.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <div className="filter-title">Show payload fields as columns <span className="muted">(up to 8)</span></div>
            <div className="chip-row">
              {fieldList.slice(0, 40).map((x) => <button key={x.field} type="button" className={`chip ${cols.includes(x.field) ? 'on' : ''}`} onClick={() => toggleCol(x.field)} title={`e.g. ${x.example}`}>{x.field}</button>)}
            </div>
          </div>
        )}
      </Card>

      <Card title="Slice the data" sub="count the filtered events by anything, then click a value to dig into it"
        right={<select className="field" value={by} onChange={(e) => setBy(e.target.value)} aria-label="Group by">
          <option value="">Group by…</option>
          <optgroup label="Dimensions">{DIMS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</optgroup>
          <optgroup label="Payload fields">{fieldList.map((x) => <option key={x.field} value={`payload:${x.field}`}>{x.field}</option>)}</optgroup>
        </select>}>
        {!by ? <div className="muted">Choose what to group by, for example the payload field quiz_option, or Day to see the trend.</div>
          : <Slice scope={scope} by={by} byLabel={byLabel} onPick={clickable ? sliceClick : null} />}
      </Card>

      <Loading state={rows}>
        {({ rows: list, total, cols: pcols }) => (
          <>
            {open && <Detail id={open} onClose={() => setOpen(null)} go={f.go} />}
            <Card title={`${num(total)} events`} sub="click a row for everything the event carries · click a title to sort"
              right={<ExportBtn name="events" rows={list} fields={[['Time', 'at'], ['Event', 'event_name'], ['Who', 'who'], ['Phone', 'phone10'], ['Session id', 'session_id'], ['Page', 'path'], ['Product', 'product_name'],
                ['Search term', 'search_term'], ['Order', 'order_id'], ['City', 'city'], ['Device', 'device'], ['Channel', 'channel'], ['Campaign', 'campaign'], ...pcols.map((c) => [c, (r) => r.payload[c]])]} />}>
              <Table scroll sort={sort} onSort={(k) => setSort(nextSort(sort, k, TEXT_SORTS))} onRow={(r) => setOpen(r.id)} rowClass={(r) => (r.is_excluded ? 'excluded' : '')} rows={list}
                empty="No events match these filters. Try removing a filter or widening the date range." cols={[
                  { label: 'Time', cls: 'nw', sortBy: 'ts', render: (r) => <>{dt(r.at)}{r.is_dup && <div><Badge>repeat</Badge></div>}</> },
                  { label: 'Event', cls: 'mono', sortBy: 'event_name', render: (r) => r.event_name },
                  { label: 'Who', cls: 'nw', sortBy: 'who', render: (r) => r.who || (r.phone10 ? <span className="mono">{r.phone10}</span> : <span className="muted" title="Never logged in on this browser">Guest</span>) },
                  { label: 'Session', cls: 'mono nw', sortBy: 'session_id', render: (r) => <a href={`#session/${encodeURIComponent(r.session_id)}`} onClick={(e) => { e.preventDefault(); e.stopPropagation(); f.go('session', { key: r.session_id }) }} title="Open the session">{r.session_id.slice(0, 12)}…</a> },
                  { label: 'Page', sortBy: 'page', render: (r) => <span className="trunc" style={{ display: 'block', maxWidth: 200 }} title={r.path}>{r.path || '–'}</span> },
                  { label: 'Product', sortBy: 'product', render: (r) => (r.product_name ? <span className="trunc" style={{ display: 'block', maxWidth: 180 }} title={r.product_name}>{r.product_name}</span> : <span className="muted">–</span>) },
                  { label: 'Search term', sortBy: 'search_term', render: (r) => r.search_term || <span className="muted">–</span> },
                  ...pcols.map((c) => ({ label: c, cls: 'mono', render: (r) => r.payload[c] ?? <span className="muted">–</span> })),
                  { label: 'City · device', cls: 'nw', sortBy: 'city', render: (r) => `${r.city || '–'} · ${r.is_app ? 'App' : r.device || '–'}` },
                ]} />
              <Pager total={total} limit={limit} offset={offset} setOffset={setOffset} setLimit={setLimit} />
            </Card>
          </>
        )}
      </Loading>
    </>
  )
}

/** Counts of the filtered events by one dimension or payload field. */
function Slice({ scope, by, byLabel, onPick }) {
  const grp = useApi('/events/groupby', { ...scope, by, limit: 100 })
  return (
    <Loading state={grp}>
      {({ rows: g, totals }) => (
        <Table onRow={onPick ? (r) => onPick(r.value) : undefined} rows={g} empty="Nothing to group." cols={[
          { label: byLabel, sortBy: 'value', render: (r) => <span className="mono">{r.value}</span> },
          { label: 'Events', num: true, sortBy: 'events', render: (r) => <>{num(r.events)} <span className="muted">({totals.events ? ((r.events / totals.events) * 100).toFixed(1) : 0}%)</span></> },
          { label: 'Sessions', num: true, sortBy: 'sessions', render: (r) => num(r.sessions) },
          { label: 'People', num: true, sortBy: 'people', render: (r) => num(r.people) },
        ]} />
      )}
    </Loading>
  )
}

/** Everything one event carries. */
function Detail({ id, onClose, go }) {
  const [d, setD] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => { setD(null); setErr(''); api(`/event/${encodeURIComponent(id)}`).then(setD).catch((e) => setErr(e.message)) }, [id])
  return (
    <Card title={d ? d.event_name : 'Event'} sub={d ? `${dt(d.at)} · ${d.page_type || 'page'} ${d.path || ''}` : 'loading…'}
      right={<span className="chip-row">
        {d && <button type="button" className="btn" onClick={() => go('session', { key: d.session_id })}>Open session</button>}
        {d?.person_key && <button type="button" className="btn" onClick={() => go('person', { key: d.person_key })}>Open person</button>}
        {d?.order_id && <button type="button" className="btn" onClick={() => go('order', { key: d.order_id })}>Open order</button>}
        <button type="button" className="btn" onClick={onClose}>Close</button>
      </span>}>
      {err && <div className="banner err">Could not load: {err}</div>}
      {d && (
        <div className="filter-grid">
          <div className="filter-group">
            <div className="filter-title">Payload</div>
            {d.details.length === 0 ? <div className="muted">No extra fields.</div> : d.details.map((x) => <div key={x.k} className="flag-row"><span className="flag-name">{x.k}</span><span className="mono" style={{ wordBreak: 'break-all' }}>{x.v}</span></div>)}
          </div>
          <div className="filter-group">
            <div className="filter-title">Event</div>
            {[['Who', d.who], ['Phone', d.phone10], ['Session', d.session_id], ['Group', d.event_key], ['Product', d.product_name], ['Search term', d.search_term], ['Order', d.order_id], ['City', d.city], ['Device', d.is_app ? 'Android app' : d.device]]
              .filter(([, v]) => v).map(([k, v]) => <div key={k} className="flag-row"><span className="flag-name">{k}</span><span className="mono" style={{ wordBreak: 'break-all' }}>{v}</span></div>)}
          </div>
        </div>
      )}
    </Card>
  )
}
