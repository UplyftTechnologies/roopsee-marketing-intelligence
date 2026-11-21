import { useState } from 'react'
import { dt, dur, inr, num, tod, useApi, useFilters } from '../api'
import { Badge, Card, Table } from '../ui'
import { STAGE, STAGE_TONE } from '../shared'
import { AddressCard, CopyBtn, ExcludeMenu, Facts, Journey, SessionTimeline, pretty } from '../components/profile'
import Icon from '../components/Icon'

export default function SessionPage() {
  const f = useFilters()
  const id = f.prefill?.key
  const [evq, setEvq] = useState('')
  const s = useApi(`/sessions/${encodeURIComponent(id || '')}`, {}, { scoped: false })
  if (s.error) return <div className="banner err">Could not load this session: {s.error} <button className="btn small" onClick={() => f.go('sessions')}>Back to Sessions</button></div>
  if (!s.data) return <div className="skeleton" style={{ height: 320 }} />
  const { session: x, events, pages, event_types: types, extra, orders, addresses, duplicates_hidden: hiddenDups, person, prev, next } = s.data
  const who = person.name || (person.is_registered ? 'Registered user' : 'Anonymous browser')
  const maxType = Math.max(1, ...types.map((t) => t.n))
  const t0 = events.length ? new Date(events[0].at).getTime() : 0
  const place = [x.city, x.region, x.country].filter(Boolean).join(', ')

  return (
    <>
      <div className="profile-head">
        <button type="button" className="icon-btn" onClick={() => f.go('sessions')} aria-label="Back to Sessions" title="Back to Sessions"><Icon name="left" /></button>
        <div style={{ minWidth: 0, flex: 1 }}>
          <h2 style={{ fontSize: 20 }}>{dt(x.started_at)} <span className="muted" style={{ fontSize: 14, fontWeight: 400 }}>· {dur(x.duration_s)}</span></h2>
          <div className="muted mono" style={{ fontSize: 12 }}>{x.session_id} <CopyBtn text={x.session_id} title="Copy session id" /></div>
          <div className="chip-row" style={{ marginTop: 6 }}>
            <Badge tone={STAGE_TONE[x.stage]}>{STAGE[x.stage]}</Badge>
            <Badge>{x.channel}</Badge>
            {x.is_app && <Badge>Android app</Badge>}
            {x.is_excluded && <Badge tone="bad" >Excluded: {x.excl_reason}</Badge>}
          </div>
        </div>
        <button type="button" className="pill-btn" disabled={!prev} onClick={() => f.go('session', { key: prev.session_id })} title={prev ? `Earlier session: ${dt(prev.started_at)}` : 'This is their first session'}><Icon name="left" size={18} />Earlier</button>
        <button type="button" className="pill-btn" disabled={!next} onClick={() => f.go('session', { key: next.session_id })} title={next ? `Later session: ${dt(next.started_at)}` : 'This is their latest session'}>Later<Icon name="right" size={18} /></button>
        <ExcludeMenu items={[
          { label: 'This session only', kind: 'session_id', value: x.session_id }, { label: 'This browser (all its sessions)', kind: 'visitor_id', value: x.visitor_key },
          { label: 'This IP address', kind: 'ip', value: x.ip }, { label: 'This user', kind: 'user_id', value: x.user_id }, { label: 'Their phone number', kind: 'phone', value: x.phone10 },
        ]} />
      </div>

      <div className="scorecards">
        <div className="sc static"><span className="sc-label">Duration</span><span className="sc-value">{dur(x.duration_s)}</span><span className="sc-note">time active (idle gaps over 30 min ignored)</span></div>
        <div className="sc static"><span className="sc-label">Events</span><span className="sc-value">{num(x.events)}</span><span className="sc-note">{num(types.length)} kinds{hiddenDups > 0 ? ` · ${num(hiddenDups)} repeats hidden` : ''}</span></div>
        <div className="sc static"><span className="sc-label">Page views</span><span className="sc-value">{num(x.pageviews)}</span><span className="sc-note">{num(pages.length)} different pages</span></div>
        <div className="sc static"><span className="sc-label">Reached</span><span className="sc-value" style={{ fontSize: 18 }}>{STAGE[x.stage]}</span><span className="sc-note"><Journey keyEvents={x.key_events} /></span></div>
        <div className="sc static"><span className="sc-label">Orders placed</span><span className="sc-value">{num(orders.length)}</span><span className="sc-note">{orders.length ? inr(orders.reduce((a, o) => a + (o.total || 0), 0)) : 'none'}</span></div>
      </div>

      <div className="grid g-main">
        <Card title="What they did, step by step" sub="clock time and time since the session started · key actions are highlighted">
          <SessionTimeline events={events} max={600} query={evq} onQuery={setEvq} />
        </Card>
        <div className="grid" style={{ gap: 14 }}>
          <Card title="Who" right={person.person_key && <button type="button" className="btn small" onClick={() => f.go('person', { key: person.person_key })}>View full profile →</button>}>
            <Facts rows={[['Person', who], ['Phone', x.phone10], ['Email', person.email], ['Segment', person.segment], ['All sessions', person.sessions ? num(person.sessions) : null],
              ['Browser id', <span className="mono" key="b">{x.visitor_key}</span>], ['User id', x.user_id && <span className="mono" key="u">{x.user_id}</span>]]} />
          </Card>
          <AddressCard data={addresses} />
          <Card title="Where they came from">
            <Facts rows={[['Channel', x.channel], ['Source / medium', `${x.source} / ${x.medium}`], ['Campaign', x.campaign !== '(not set)' ? x.campaign : null], ['Ad content', extra.utm_content], ['Search term', extra.utm_term],
              ['Referrer', extra.referrer], ['Landing page', <span className="mono" key="l">{pretty(x.landing_path)}</span>], ['Click id', x.has_gclid ? 'Google click id (gclid)' : x.has_fbclid ? 'Meta click id (fbclid)' : null]]} />
          </Card>
          <Card title="Device & place">
            <Facts rows={[['Device', x.is_app ? 'Android app' : x.device], ['System', x.platform], ['Browser', extra.browser], ['IP address', x.ip && <span className="mono" key="i">{x.ip}</span>], ['Place', place]]} />
          </Card>
          <Card title="Pages visited">
            <Table cols={[
              { label: 'Page', render: (p) => <span className="mono trunc" style={{ display: 'block', maxWidth: 190 }} title={pretty(p.path)}>{pretty(p.path)}</span> },
              { label: 'First seen', render: (p) => <span title={tod(p.first_at)}>+{Math.round((new Date(p.first_at).getTime() - t0) / 1000)}s</span> },
              { label: 'Events', num: true, render: (p) => num(p.events) },
            ]} rows={pages.slice(0, 12)} />
            {pages.length > 12 && <div className="muted" style={{ marginTop: 6 }}>+ {pages.length - 12} more pages</div>}
          </Card>
          <Card title="Event types" right={<button type="button" className="btn small" onClick={() => f.go('events', { session: id })} title="Open every event of this session in the Events tab">All events of this session →</button>}>
            <div className="mini-list">
              {types.slice(0, 10).map((t) => (
                <div key={t.event_name} className="mini-row" style={{ cursor: 'pointer' }} role="button" tabIndex={0} title="Search the timeline for this event"
                  onClick={() => setEvq(t.event_name)} onKeyDown={(e) => { if (e.key === 'Enter') setEvq(t.event_name) }}>
                  <span className="name" title={t.event_name}>{t.event_name.replace(/_/g, ' ')}</span><span className="val">{num(t.n)}</span>
                  <span className="mini-bar"><i style={{ width: `${(t.n / maxType) * 100}%` }} /></span>
                </div>
              ))}
            </div>
          </Card>
          {orders.length > 0 && (
            <Card title="Orders from this session">
              <Table onRow={(o) => f.go('order', { key: o.order_id })} cols={[{ label: 'Total', num: true, render: (o) => inr(o.total) }, { label: 'Status', render: (o) => <Badge tone={o.is_valid && !o.is_test ? 'good' : ''}>{o.is_test ? 'test' : o.status}</Badge> },
                { label: 'Items', render: (o) => <span className="trunc" style={{ display: 'block', maxWidth: 170 }} title={o.items}>{o.items || '–'}</span> }]} rows={orders} />
            </Card>
          )}
        </div>
      </div>
    </>
  )
}
