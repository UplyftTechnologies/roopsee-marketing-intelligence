import { useEffect, useState } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, day, dt, dur, inr, num, useApi, useFilters } from '../api'
import { Badge, Card, ExportBtn, axis, chartTip, Table } from '../ui'
import { CopyBtn, ExcludeMenu, Journey, SessionTimeline } from '../components/profile'
import Icon from '../components/Icon'

const IST = { timeZone: 'Asia/Kolkata' }
const hourOf = (v) => parseInt(new Date(v).toLocaleString('en-GB', { ...IST, hour: '2-digit', hour12: false }), 10) % 24
const weekdayOf = (v) => new Date(v).toLocaleDateString('en-IN', { ...IST, weekday: 'long' })
const BUCKETS = [[0, 5, 'late at night (12–6 am)'], [6, 11, 'in the morning (6 am–12 pm)'], [12, 16, 'in the afternoon (12–5 pm)'], [17, 21, 'in the evening (5–10 pm)'], [22, 23, 'at night (10 pm–12 am)']]
const top = (arr) => { const c = {}; arr.filter(Boolean).forEach((x) => { c[x] = (c[x] || 0) + 1 }); const e = Object.entries(c).sort((a, b) => b[1] - a[1]); return e.length ? e[0] : null }
const median = (a) => { const s = [...a].sort((x, y) => x - y); return s.length ? s[Math.floor(s.length / 2)] : 0 }

function Habits({ sessions }) {
  if (sessions.length < 3) return null
  const b = top(sessions.map((s) => { const h = hourOf(s.started_at); return BUCKETS.find((x) => h >= x[0] && h <= x[1])[2] }))
  const wd = top(sessions.map((s) => weekdayOf(s.started_at)))
  const dev = top(sessions.map((s) => (s.is_app ? 'the Android app' : s.device)))
  const ch = top(sessions.map((s) => s.channel))
  const parts = [b && `Usually visits ${b[0]}`, wd && wd[1] >= 2 && `most often on ${wd[0]}s`, dev && `mostly on ${dev[0]}`, ch && `usually arriving via ${ch[0]}`].filter(Boolean)
  return <div className="muted" style={{ marginTop: 4 }}>{parts.join(' · ')}.</div>
}

function SessionCard({ s, onOpen }) {
  const [open, setOpen] = useState(false)
  const [d, setD] = useState(null)
  useEffect(() => { if (open && !d) api(`/sessions/${encodeURIComponent(s.session_id)}`).then(setD).catch(() => setD({ events: [] })) }, [open])
  return (
    <div className="sess-card">
      <button type="button" className="sess-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="sess-when"><b>{dt(s.started_at)}</b><span className="muted">{dur(s.duration_s)} · {s.events} events</span></span>
        <span className="sess-mid"><Journey keyEvents={s.key_events} /></span>
        <span className="sess-meta muted">{s.channel} · {s.is_app ? 'App' : s.device || '–'}{s.is_excluded ? ' · excluded' : ''}</span>
        <Icon name="chevron" size={18} style={{ transform: open ? 'rotate(180deg)' : 'none' }} />
      </button>
      {open && (
        <div className="sess-body">
          <div className="row-between" style={{ padding: '0 0 8px' }}>
            <span className="muted">{[s.campaign !== '(not set)' && s.campaign, s.landing_path, [s.city, s.region].filter(Boolean).join(', ')].filter(Boolean).join(' · ')}</span>
            <button type="button" className="btn small" onClick={() => onOpen(s.session_id)}>Open full session →</button>
          </div>
          {d ? <SessionTimeline events={d.events} max={150} /> : <div className="skeleton" style={{ height: 80 }} />}
        </div>
      )}
    </div>
  )
}

export default function Person() {
  const f = useFilters()
  const key = f.prefill?.key
  const s = useApi('/person', { key }, { scoped: false })
  if (s.error) return <div className="banner err">Could not load this person: {s.error} <button className="btn small" onClick={() => f.go('users')}>Back to Users</button></div>
  if (!s.data) return <div className="skeleton" style={{ height: 320 }} />
  const d = s.data
  const p = d.profile || {}
  const t = d.totals
  const name = p.name || (p.is_registered ? 'Registered user (no name)' : 'Anonymous browser')
  const medianSession = median(d.sessions.map((x) => x.duration_s || 0))
  const validOrders = d.orders.filter((o) => o.is_valid && !o.is_test)
  const revenue = validOrders.reduce((a, o) => a + (o.total || 0), 0)
  const botLike = t.sessions >= 30 && t.browsers === 1 && t.seconds / t.sessions < 5
  const stillCounted = d.sessions.filter((x) => !x.is_excluded).length
  const first = d.sessions[d.sessions.length - 1]?.started_at
  const last = d.sessions[0]?.started_at
  const userId = p.is_registered ? p.user_id : null

  return (
    <>
      <div className="profile-head">
        <button type="button" className="icon-btn" onClick={() => f.go('users')} aria-label="Back to Users" title="Back to Users"><Icon name="left" /></button>
        <div className="avatar" aria-hidden>{(p.name || (p.is_registered ? 'U' : '?')).slice(0, 1).toUpperCase()}</div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <h2 style={{ fontSize: 20 }}>{name}</h2>
          <div className="muted">
            {[p.phone10, p.email, [p.city, p.state].filter(Boolean).join(', ')].filter(Boolean).join(' · ') || 'No contact details on file'}
          </div>
          <div className="chip-row" style={{ marginTop: 6 }}>
            {p.segment && <Badge>{p.segment}</Badge>}
            <Badge tone={p.is_registered ? 'good' : ''}>{p.is_registered ? 'Registered' : 'Anonymous'}</Badge>
            {p.is_excluded && <Badge tone="bad">Excluded from analytics</Badge>}
            {p.first_channel && <Badge>First seen via {p.first_channel}</Badge>}
            {p.age_bucket && <Badge>{p.age_bucket}</Badge>}{p.skin_type && <Badge>{p.skin_type}</Badge>}
          </div>
        </div>
        <ExportBtn name="person-sessions" rows={d.sessions} fields={[['Started', 'started_at'], ['Seconds', 'duration_s'], ['Events', 'events'], ['Journey', 'key_events'], ['Channel', 'channel'], ['Campaign', 'campaign'], ['Device', 'device'], ['Browser', 'browser'], ['City', 'city'], ['IP', 'ip'], ['Session id', 'session_id']]} />
        <ExcludeMenu items={[
          { label: userId ? 'This user (all their browsers)' : 'This browser', kind: userId ? 'user_id' : 'visitor_id', value: userId || key },
          { label: 'Their phone number', kind: 'phone', value: p.phone10 }, { label: 'Their main IP address', kind: 'ip', value: d.ips[0]?.ip },
        ]} />
      </div>

      {botLike && (
        <div className="banner">
          <div><b>This looks automated.</b> {num(t.sessions)} sessions from a single browser, averaging {(t.seconds / t.sessions).toFixed(1)} seconds each.
            <div className="muted">{stillCounted > 0 ? `${num(stillCounted)} of its sessions are still counted in your numbers. ` : 'All of its sessions are already excluded. '}A heuristic, not proof: if it is a bot or crawler, use Exclude… → “This browser” to remove all of it.</div></div>
        </div>
      )}

      <div className="scorecards">
        <div className="sc static"><span className="sc-label">Sessions</span><span className="sc-value">{num(t.sessions)}</span><span className="sc-note">{first ? `${day(first.slice(0, 10))} → ${day(last.slice(0, 10))}` : ' '}</span></div>
        <div className="sc static"><span className="sc-label">Browsers · devices</span><span className="sc-value">{num(t.browsers)} · {num(t.devices)}</span><span className="sc-note">{num(t.ips)} IP address{t.ips === 1 ? '' : 'es'}</span></div>
        <div className="sc static"><span className="sc-label">Events</span><span className="sc-value">{num(t.events)}</span><span className="sc-note">{num(t.pageviews)} page views</span></div>
        <div className="sc static" title="Typical session length. Sessions before the 14 Oct tracking upgrade can last for days."><span className="sc-label">Median session</span><span className="sc-value">{dur(medianSession)}</span><span className="sc-note">per visit</span></div>
        <div className="sc static"><span className="sc-label">Orders</span><span className="sc-value">{num(validOrders.length)}</span><span className="sc-note">{validOrders.length ? inr(revenue) : 'none yet'}</span></div>
        <div className="sc static"><span className="sc-label">Last seen</span><span className="sc-value" style={{ fontSize: 18 }}>{last ? dt(last) : '–'}</span><span className="sc-note">{p.is_registered ? `signed up ${p.signed_up_at ? dt(p.signed_up_at) : '–'}` : 'never logged in'}</span></div>
      </div>
      <Habits sessions={d.sessions} />

      <div className="grid g-main">
        <div>
          <Card title={`Sessions (${num(t.sessions)})`} sub="newest first · click a visit to see what they did inside it">
            {d.sessions.length === 0 ? <div className="empty">No sessions recorded</div> : d.sessions.slice(0, 60).map((x) => <SessionCard key={x.session_id} s={x} onOpen={(id) => f.go('session', { key: id })} />)}
            {d.sessions.length > 60 && <div className="muted" style={{ marginTop: 8 }}>Showing the latest 60 of {num(d.sessions.length)} sessions. Export CSV has them all.</div>}
          </Card>
        </div>
        <div className="grid" style={{ gap: 14 }}>
          {d.daily.length > 1 && (
            <Card title="Activity by day" sub="sessions per day">
              <ResponsiveContainer width="100%" height={140}>
                <BarChart data={d.daily} margin={{ left: -24, right: 4 }}>
                  <CartesianGrid stroke="var(--grid)" vertical={false} />
                  <XAxis dataKey="d" tickFormatter={day} {...axis} minTickGap={24} /><YAxis {...axis} allowDecimals={false} width={40} />
                  <Tooltip {...chartTip} labelFormatter={day} formatter={(v, n, pr) => [`${v} sessions, ${pr.payload.events} events`, '']} />
                  <Bar dataKey="sessions" fill="var(--series-1)" radius={[3, 3, 0, 0]} maxBarSize={16} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </Card>
          )}
          <Card title={`Browsers & devices (${d.browsers.length})`} sub="each browser id is one device or one cleared-cookie reset">
            <Table cols={[
              { label: 'Browser', render: (b) => <span title={b.visitor_key}><span className="mono">{b.visitor_key.slice(0, 10)}…</span><br /><span className="muted">{[b.is_app ? 'Android app' : b.device, b.platform, b.browser].filter(Boolean).join(' · ')}</span></span> },
              { label: 'Sessions', num: true, render: (b) => num(b.sessions) }, { label: 'Last seen', render: (b) => dt(b.last_seen) },
            ]} rows={d.browsers.slice(0, 10)} />
            {d.browsers.length > 10 && <div className="muted" style={{ marginTop: 6 }}>+ {d.browsers.length - 10} more browsers</div>}
          </Card>
          {d.orders.length > 0 && (
            <Card title={`Orders (${d.orders.length})`}>
              <Table cols={[
                { label: 'When', render: (o) => dt(o.ts) }, { label: 'Total', num: true, render: (o) => inr(o.total) },
                { label: 'Status', render: (o) => <Badge tone={o.is_valid && !o.is_test ? 'good' : o.is_test ? '' : 'warn'}>{o.is_test ? 'test' : o.status}</Badge> },
                { label: 'Items', render: (o) => <span className="trunc" style={{ display: 'block', maxWidth: 160 }} title={o.items}>{o.items || '–'}</span> },
              ]} rows={d.orders} />
            </Card>
          )}
          {d.ips.length > 0 && (
            <Card title={`IP addresses (${d.ips.length})`}>
              <Table cols={[{ label: 'IP', cls: 'mono', key: 'ip' }, { label: 'Place', key: 'city' }, { label: 'Sessions', num: true, render: (r) => num(r.sessions) }, { label: 'Last seen', render: (r) => dt(r.last_seen) }]} rows={d.ips.slice(0, 8)} />
            </Card>
          )}
          <Card title="Identifiers"><div className="muted" style={{ fontSize: 12, wordBreak: 'break-all' }}>
            Person key <span className="mono">{key}</span> <CopyBtn text={key} title="Copy person key" />
          </div></Card>
        </div>
      </div>
    </>
  )
}
