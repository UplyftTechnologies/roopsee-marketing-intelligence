import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { dt, day, dur, inr, num, pct, useApi, useFilters, usePersisted } from '../api'
import { Card, Chips, ExportBtn, Kpi, Loading, Table, axis, chartTip, delta } from '../ui'

const ICON = { login: '🔐', address: '📍', order: '🧾', payment: '💳', speed: '🐢' }
const TREND = [['left_with_problem', 'Left with a problem'], ['with_problem', 'Hit a problem']]
const HOW = [
  ['Stage', 'Login, address, place order and payment are the steps from logging in to paying. “Speed & errors” covers slow pages and broken requests anywhere on the site.'],
  ['Tried', 'A visit that did something at the stage (for example sent an OTP) or hit a problem there.'],
  ['Stuck', 'Tried the stage and never got through it, or its last word there was a problem (saved an address, then was told we do not deliver there). Placing an order settles every stage.'],
  ['Hit a problem', 'Saw at least one error at the stage, even if it then got through (a wrong OTP, then the right one).'],
  ['Signs of struggle', 'Asking for the OTP again or closing a form. They help explain why a visit got stuck but do not make it stuck on their own.'],
  ['Left with a problem', 'A visit with no order that ended while a problem at a stage it got stuck in was still standing.'],
  ['Last problem before leaving', 'For each visit without an order, the last problem it had not got past. The likeliest reason they left.'],
  ['Sales lost', 'The biggest cart of people stuck at a stage who did not buy in any later visit in these dates. Speed & errors is not added in, to avoid counting a cart twice.'],
  ['Spike', 'An hour when one problem hit at least 5 visits and 4 times its usual hourly number. Often an outage: SMS, payments or our server.'],
  ['Repeats', 'The tracker often fires one action twice in a row. Repeats within 2 seconds are ignored, so retry counts can be a little lower than on the roopsee.com admin.'],
]

/** Ranked horizontal bars with counts and a share of `total`. */
function Ranked({ items, total, unit = '', empty, onPick }) {
  if (!items.length) return <div className="muted">{empty || 'Nothing here.'}</div>
  const max = Math.max(...items.map((i) => i.count), 1)
  return (
    <div className="mini-list">
      {items.map((i) => (
        <div key={i.name} className="mini-row" style={onPick ? { cursor: 'pointer' } : undefined} role={onPick ? 'button' : undefined} tabIndex={onPick ? 0 : undefined}
          onClick={onPick ? () => onPick(i.name) : undefined} onKeyDown={onPick ? (e) => { if (e.key === 'Enter') onPick(i.name) } : undefined}>
          <span className="name" title={i.label}>{i.label}</span>
          <span className="val">{num(i.count)}{unit}{total ? ` · ${Math.round((i.count / total) * 100)}%` : ''}</span>
          <span className="mini-bar"><i style={{ width: `${(i.count / max) * 100}%` }} /></span>
        </div>
      ))}
    </div>
  )
}

const reasonItems = (list) => list.map((r) => ({ name: r.key, count: r.visits, label: `${r.label}${r.details.length ? ` (${r.details.map((d) => `${d.name}${d.count > 1 ? ` ${d.count}×` : ''}`).join(', ')})` : ''}` }))

function StageCard({ s, before, active, worst, onPick }) {
  const isSpeed = s.key === 'speed'
  const big = isSpeed ? s.stuck_no_order : s.stuck
  const d = before ? delta(isSpeed ? s.stuck : s.stuck, before.stuck) : null
  return (
    <button type="button" className="kpi click" aria-pressed={active} onClick={onPick}
      style={{ textAlign: 'left', ...(active ? { borderColor: 'var(--accent)', boxShadow: 'inset 0 0 0 1px var(--accent)' } : worst ? { borderColor: 'var(--warning)' } : null) }}>
      <div className="label"><span aria-hidden="true">{ICON[s.key]}</span> {s.label}</div>
      <div className="value">{num(big)}</div>
      <div className="note">
        {isSpeed ? `${num(s.hit)} of ${num(s.tried)} visits had a slow or broken moment` : s.tried ? `stuck of ${num(s.tried)} that tried (${pct(s.stuck / s.tried, 0)})` : 'nobody tried'}
        {d && <> · <span className="muted">{d.text} vs before</span></>}
      </div>
    </button>
  )
}

export default function PainPoints() {
  const f = useFilters()
  const [channel, setChannel] = usePersisted('pain.channel', f.prefill?.channel || '', Boolean(f.prefill?.channel))
  const [picked, setPicked] = usePersisted('pain.stage', '')
  const [trend, setTrend] = useState('left_with_problem')
  const [how, setHow] = useState(false)
  const [who, setWho] = useState(false)
  const s = useApi('/pain', { channel: channel || undefined, compare: f.compare || undefined })
  return (
    <Loading state={s}>
      {(d) => {
        if (!d.ready) return <div className="banner err">The pain point tables are not built yet. Press <b>Refresh</b> (top right) to build them.</div>
        const t = d.totals
        const pt = d.prev?.totals
        const worst = [...d.stages].filter((x) => x.tried >= 5 && x.stuck).sort((a, b) => (b.key === 'speed' ? b.stuck_no_order : b.stuck) - (a.key === 'speed' ? a.stuck_no_order : a.stuck))[0]
        const cur = d.stages.find((x) => x.key === picked) || worst || d.stages[0]
        const top = d.last_before_leaving[0]
        const stageName = Object.fromEntries(d.stages.map((x) => [x.key, x.label]))
        const lost = d.stages.reduce((n, x) => n + (x.key === 'speed' ? 0 : x.after.lost_value), 0)
        const trends = [...TREND, ...d.stages.map((x) => [x.key, x.stuck_label])]
        const series = d.daily.map((r) => ({ date: r.day, value: r[trend] }))
        const pick = (k) => { setPicked(k); setWho(false) }
        return (
          <>
            <div className="chip-row">
              <Chips value={channel} onChange={setChannel} options={[{ value: '', label: 'All traffic' }, ...d.channels.map((c) => ({ value: c, label: c }))]} />
              <button type="button" className="btn" aria-expanded={how} onClick={() => setHow(!how)}>{how ? 'Hide how this is counted' : 'How this is counted'}</button>
            </div>
            {how && <Card title="How this is counted"><ul style={{ margin: 0, paddingLeft: 18, display: 'grid', gap: 4, fontSize: 14 }}>{HOW.map(([k, v]) => <li key={k}><b>{k}:</b> {v}</li>)}</ul></Card>}
            {d.silent.length > 0 && (
              <div className="banner" role="note">
                <span>The tracker has never sent these problem events, so a zero for them may not be a real zero: <span className="mono">{d.silent.join(', ')}</span>.</span>
              </div>
            )}

            <div className="kpis">
              <Kpi label="Visits that hit a problem" value={num(t.with_problem)} d={pt ? delta(t.with_problem, pt.with_problem) : null} goodWhen="down" note={`${pct(t.visits ? t.with_problem / t.visits : 0, 0)} of ${num(t.visits)} visits`} />
              <Kpi label="Left with a problem unsolved" value={num(t.left_with_problem)} d={pt ? delta(t.left_with_problem, pt.left_with_problem) : null} goodWhen="down" note="no order in that visit" />
              <Kpi label="Top reason for leaving" value={top ? num(top.visits) : '–'} note={top ? top.label : 'No problems recorded'} />
              <Kpi label="Sales lost" value={inr(lost)} d={d.prev ? delta(lost, d.prev.lost) : null} goodWhen="down" note="carts of people stuck who didn't buy later" />
            </div>

            {d.spikes.length > 0 && (
              <Card title="⚠ Sudden spikes" sub="an hour when one problem hit at least 5 visits and 4× its usual hourly number: often an outage">
                {d.spikes.map((x) => (
                  <button key={`${x.key}-${x.from}`} type="button" className="btn" style={{ display: 'block', textAlign: 'left', marginBottom: 6 }} onClick={() => pick(x.stage)}>
                    <b>{x.label}</b>: {num(x.visits)} visits on {dt(x.from)}, usually {x.usual} an hour{x.details.length ? ` (${x.details.map((y) => y.name).join(', ')})` : ''} →
                  </button>
                ))}
              </Card>
            )}

            <div className="kpis" role="group" aria-label="Stages" style={{ gridTemplateColumns: 'repeat(5, minmax(0, 1fr))' }}>
              {d.stages.map((x) => <StageCard key={x.key} s={x} before={d.prev?.stages[x.key]} active={cur.key === x.key} worst={worst?.key === x.key} onPick={() => pick(x.key)} />)}
            </div>

            <Stage s={cur} paths={d.login_paths} payment={d.payment} who={who} setWho={setWho} f={f} channel={channel} />

            <Card title="Why people left: the last problem before leaving" sub="for each visit that ended without an order, the last problem it hadn't got past (one fixed later, like a wrong OTP then the right one, doesn't count)"
              right={<ExportBtn name="pain-last-problem" rows={d.last_before_leaving} fields={[['Stage', (r) => stageName[r.stage]], ['Problem', 'label'], ['Visits', 'visits'], ['Details', (r) => r.details.map((x) => x.name).join(' | ')]]} />}>
              <Ranked total={t.left_with_problem} unit=" visits" empty="No visit left with a problem unsolved."
                items={d.last_before_leaving.map((r) => ({ name: r.key, count: r.visits, label: `${stageName[r.stage]} · ${r.label}${r.details.length ? ` (${r.details.map((x) => x.name).join(', ')})` : ''}` }))}
                onPick={(k) => { const r = d.last_before_leaving.find((x) => x.key === k); if (r) pick(r.stage) }} />
              <div className="muted" style={{ marginTop: 8, fontSize: 12 }}>{num(t.left_no_problem)} other visits ended without an order and with no problem recorded: they browsed and left.</div>
            </Card>

            <h3 style={{ margin: '8px 0 0' }}>Trends &amp; deeper look</h3>
            <Card title="Each day" sub="visits with problems, and visits stuck at each stage, per day">
              <Chips value={trend} onChange={setTrend} options={trends.map(([value, label]) => ({ value, label }))} />
              <div style={{ height: 220, marginTop: 8 }}>
                <ResponsiveContainer>
                  <BarChart data={series} margin={{ left: 0, right: 12, top: 8, bottom: 0 }}>
                    <CartesianGrid stroke="var(--grid)" vertical={false} />
                    <XAxis dataKey="date" tickFormatter={day} {...axis} minTickGap={32} />
                    <YAxis {...axis} width={48} allowDecimals={false} />
                    <Tooltip {...chartTip} labelFormatter={day} formatter={(v) => [num(v), 'visits']} />
                    <Bar dataKey="value" fill="var(--series-1)" radius={[2, 2, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
            <div className="grid g2">
              <Card title="Where we don't deliver" sub={d.not_served.visits ? `${num(d.not_served.visits)} visits asked for ${num(d.not_served.total_pincodes)} pincodes we don't deliver to` : "Nobody asked for a pincode we don't deliver to"}
                right={<ExportBtn name="pain-undeliverable-pincodes" rows={d.not_served.pincodes} fields={[['Pincode', 'pincode'], ['City', 'city'], ['Visits', 'visits'], ['At checkout', 'at_checkout'], ['Left, no order', 'left']]} />}>
                <Table rows={d.not_served.pincodes} empty="Nothing to show." cols={[
                  { label: 'Pincode', key: 'pincode', cls: 'mono' }, { label: 'City', key: 'city' },
                  { label: 'Visits', num: true, sortBy: 'visits', render: (r) => num(r.visits) }, { label: 'At checkout', num: true, sortBy: 'at_checkout', render: (r) => num(r.at_checkout) },
                  { label: 'Left, no order', num: true, sortBy: 'left', render: (r) => num(r.left) }]} />
                <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>At checkout: they had saved or picked that address and were ready to pay. Worth checking when adding delivery areas.</div>
              </Card>
              <Card title="Out of stock items people wanted" sub={d.out_of_stock.length ? `Most wanted: ${d.out_of_stock[0].name}` : 'No out-of-stock product was viewed in these dates'}
                right={<ExportBtn name="pain-out-of-stock" rows={d.out_of_stock} fields={[['Product', 'name'], ['Brand', 'brand'], ['Visits', 'visits'], ['Viewed', 'viewed'], ['Tried to add', 'tried_add'], ['Left, no order', 'left']]} />}>
                <Table rows={d.out_of_stock} empty="Nothing to show." cols={[
                  { label: 'Product', sortBy: 'name', render: (r) => <span className="trunc" style={{ display: 'block', maxWidth: 260 }} title={r.name}>{r.brand && !r.name.toLowerCase().startsWith(r.brand.toLowerCase()) ? `${r.brand} ${r.name}` : r.name}</span> },
                  { label: 'Visits', num: true, sortBy: 'visits', render: (r) => num(r.visits) }, { label: 'Viewed', num: true, sortBy: 'viewed', render: (r) => num(r.viewed) },
                  { label: 'Tried to add', num: true, sortBy: 'tried_add', render: (r) => num(r.tried_add) }, { label: 'Left, no order', num: true, sortBy: 'left', render: (r) => num(r.left) }]} />
              </Card>
            </div>
            <Card title="Slowest pages" sub={d.slow_pages.length ? `Most often slow: ${d.slow_pages[0].page} (${num(d.slow_pages[0].visits)} visits)` : 'No slow first loads in these dates'}
              right={<ExportBtn name="pain-slow-pages" rows={d.slow_pages} fields={[['Page', 'page'], ['Slow visits', 'visits'], ['Typical first content (ms)', 'median_ms'], ['Left, no order', 'left']]} />}>
              <Table rows={d.slow_pages} empty="Nothing to show." cols={[
                { label: 'Page', key: 'page', cls: 'mono' }, { label: 'Slow visits', num: true, sortBy: 'visits', render: (r) => num(r.visits) },
                { label: 'Typical first content', num: true, sortBy: 'median_ms', render: (r) => (r.median_ms ? `${(r.median_ms / 1000).toFixed(1)} s` : '–') },
                { label: 'Left, no order', num: true, sortBy: 'left', render: (r) => num(r.left) }]} />
              <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>Slow: the first page showed content after more than 3 seconds. More detail under Data &amp; ETL → page speed.</div>
            </Card>
          </>
        )
      }}
    </Loading>
  )
}

/** The picked stage: login paths, why visits got stuck, what they did next, and who. */
function Stage({ s, paths, payment, who, setWho, f, channel }) {
  const isSpeed = s.key === 'speed'
  const hard = s.reasons.filter((r) => !r.soft)
  const soft = s.reasons.filter((r) => r.soft)
  const a = s.after
  const goEvents = (key) => {  // open the Events tab on this problem's events
    const r = s.reasons.find((x) => x.key === key)
    if (r) f.go('events', { event: r.event, payload: r.error_names.length === 1 ? [`error_name=${r.error_names[0]}`] : undefined })
  }
  return (
    <Card title={<>{ICON[s.key]} {s.stuck_label}</>}
      sub={isSpeed ? `${num(s.hit)} visits had a slow or broken moment; ${num(s.stuck_no_order)} of them ended without an order.`
        : `${num(s.tried)} visits tried, ${num(s.stuck)} got stuck${s.recovered ? `, ${num(s.recovered)} hit a problem but got through` : ''}.`}
      right={s.list_total > 0 && <button type="button" className="btn primary" aria-expanded={who} onClick={() => setWho(!who)}>{who ? 'Hide who' : `See who (${num(s.list_total)})`}</button>}>
      {s.key === 'login' && (
        <div className="grid g2" style={{ marginBottom: 12 }}>
          {paths.map((p) => (
            <div key={p.key}>
              <b>{p.label}</b>
              {p.steps[0]?.visits ? <Ranked items={p.steps.map((x) => ({ name: x.key, label: x.label, count: x.visits }))} total={p.steps[0].visits} unit=" visits" /> : <div className="muted">Nobody used it in these dates.</div>}
            </div>
          ))}
        </div>
      )}
      {isSpeed && s.order_rate_hit != null && s.order_rate_clean != null && (
        <div className={s.order_rate_hit < s.order_rate_clean ? 'banner' : 'muted'} style={{ marginBottom: 12 }}>
          Visits with a slow or broken moment ordered <b>{(s.order_rate_hit * 100).toFixed(1)}%</b> of the time, against <b>{(s.order_rate_clean * 100).toFixed(1)}%</b> for the others.
          {s.quick_exit_hit ? ` ${num(s.quick_exit_hit)} left within 10 seconds.` : ''}
        </div>
      )}
      <div className="grid g2">
        <div>
          <b>{isSpeed ? 'What happened' : 'Why they got stuck'}</b>
          <Ranked onPick={goEvents} items={reasonItems(hard)} total={isSpeed ? s.stuck_no_order : s.stuck} unit=" visits" empty={s.stuck ? 'No error was recorded for these visits.' : 'Nobody got stuck here in these dates.'} />
          {soft.length > 0 && (<><div style={{ marginTop: 10 }}><b>Signs of struggle</b></div><Ranked onPick={goEvents} items={reasonItems(soft)} total={s.stuck} unit=" visits" /></>)}
          {(hard.length > 0 || soft.length > 0) && <div className="muted" style={{ marginTop: 8, fontSize: 12 }}>Click a reason to see those events in the Events tab.</div>}
          {!isSpeed && s.no_signal > 0 && <div className="muted" style={{ marginTop: 8, fontSize: 12 }}>{num(s.no_signal)} of {num(s.stuck)} stuck visits recorded no error: they just stopped here.</div>}
          {s.effort && s.stuck_no_order > 0 && (
            <div className="muted" style={{ marginTop: 8, fontSize: 12 }}>
              Typical time struggling: <b>{dur(s.effort.median_sec)}</b> · typical {s.effort.tries_label}: <b>{s.effort.median_tries ?? '–'}</b>{s.effort.three_plus ? ` · ${num(s.effort.three_plus)} visits with 3 or more` : ''}.
            </div>
          )}
        </div>
        <div>
          <b>After getting stuck</b> <span className="muted" style={{ fontSize: 12 }}>people stuck here in a visit without an order, and what they did later in these dates</span>
          <Ranked total={a.people} unit=" people" empty="Nobody to follow." items={a.people ? [
            { name: 'bought', label: 'Came back and bought', count: a.bought_after }, { name: 'returned', label: "Came back, didn't buy", count: a.returned_no_order },
            { name: 'gone', label: "Didn't come back", count: a.never_returned }] : []} />
          {a.lost_value > 0 && <div className="muted" style={{ marginTop: 8, fontSize: 12 }}><b>{inr(a.lost_value)}</b> in the carts of those who didn't buy.</div>}
        </div>
      </div>
      {s.key === 'payment' && payment.methods.length > 0 && (
        <div className="grid g2" style={{ marginTop: 12 }}>
          <div>
            <b>By how they paid</b>
            <Table rows={payment.methods} cols={[{ label: 'Method', key: 'name' }, { label: 'Tried', num: true, sortBy: 'tried', render: (r) => num(r.tried) }, { label: 'Stuck', num: true, sortBy: 'stuck', render: (r) => num(r.stuck) },
              { label: 'Stuck %', num: true, render: (r) => pct(r.tried ? r.stuck / r.tried : 0, 0) }]} />
          </div>
          <div>
            <b>Why payments failed</b> <span className="muted" style={{ fontSize: 12 }}>{num(payment.failed_attempts)} failed attempts</span>
            <Ranked items={payment.reasons.map((r) => ({ ...r, label: r.name }))} empty="No failure reason recorded." />
            {payment.steps.length > 0 && <Ranked items={payment.steps.map((r) => ({ ...r, label: `at: ${r.name}` }))} />}
          </div>
        </div>
      )}
      {who && <Who stage={s.key} f={f} channel={channel} />}
    </Card>
  )
}

/** The people stuck at a stage (newest first), with what went wrong. */
function Who({ stage, f, channel }) {
  const p = useApi('/pain/people', { stage, channel: channel || undefined, limit: 500 })
  return (
    <div style={{ marginTop: 14 }}>
      <Loading state={p}>
        {({ total, people }) => (
          <>
            <div className="row-between" style={{ marginBottom: 6 }}>
              <span className="muted" style={{ fontSize: 12 }}>{num(total)} people got stuck here and did not buy in these dates{total > people.length ? ` · showing the latest ${num(people.length)}` : ''}. Click a row for the person.</span>
              <ExportBtn name={`pain-${stage}-people`} rows={people} fields={[['Name', 'name'], ['Phone', 'phone10'], ['City', 'city'], ['Last seen', 'last_seen'], ['Cart value', 'cart_value'], ['What went wrong', 'why'], ['Visits', 'visits'], ['Session id', 'session_id']]} />
            </div>
            <Table scroll onRow={(r) => f.go('person', { key: r.person_key })} rows={people} empty="Nobody to follow up." cols={[
              { label: 'Who', cls: 'nw', sortBy: 'name', render: (r) => r.name || (r.phone10 ? <span className="mono">{r.phone10}</span> : <span className="muted">anonymous</span>) },
              { label: 'Phone', cls: 'mono nw', sortBy: 'phone10', render: (r) => r.phone10 || <span className="muted">–</span> },
              { label: 'City', cls: 'nw', sortBy: 'city', render: (r) => r.city || '–' },
              { label: 'Last seen', cls: 'nw', sortBy: 'last_seen', render: (r) => dt(r.last_seen) },
              { label: 'Cart', num: true, sortBy: 'cart_value', render: (r) => (r.cart_value ? inr(r.cart_value) : '–') },
              { label: 'What went wrong', render: (r) => <span title={r.why}>{r.why}</span> },
              { label: 'Visit', cls: 'mono nw', render: (r) => <a href={`#session/${encodeURIComponent(r.session_id)}`} onClick={(e) => { e.preventDefault(); e.stopPropagation(); f.go('session', { key: r.session_id }) }}>{r.session_id.slice(0, 10)}…</a> },
            ]} />
          </>
        )}
      </Loading>
    </div>
  )
}
