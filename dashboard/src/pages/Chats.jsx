import { useEffect, useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { day, dt, dur, num, pct, useApi, useFilters, usePersisted } from '../api'
import { Badge, Card, Chips, ExportBtn, Kpi, Loading, Search, Table, axis, chartTip, delta } from '../ui'
import { STAGE } from '../shared'

const VIEWS = [
  ['all', 'All', null],
  ['disliked', '👎 Not helpful', (c) => c.thumbs_down > 0],
  ['liked', '👍 Helpful', (c) => c.thumbs_up > 0],
  ['failed', 'Failed', (c) => c.failed > 0],
  ['loggedin', 'Logged in', (c) => c.user_id],
]
const short = (id) => (id ? `${String(id).slice(0, 8)}…` : '')

/** Ranked horizontal bars. */
function Bars({ items, total, empty }) {
  if (!items.length) return <div className="muted">{empty}</div>
  const max = Math.max(...items.map((i) => i.count), 1)
  return (
    <div className="mini-list">
      {items.map((i) => (
        <div key={i.name} className="mini-row">
          <span className="name" title={i.label || i.name}>{i.label || i.name}</span>
          <span className="val">{num(i.count)}{total ? ` · ${Math.round((i.count / total) * 100)}%` : ''}</span>
          <span className="mini-bar"><i style={{ width: `${(i.count / max) * 100}%` }} /></span>
        </div>
      ))}
    </div>
  )
}

/** A question and Roop's reply (the "not helpful" and "couldn't answer" lists); opens the chat. */
function AnswerList({ items, onOpen, empty }) {
  if (!items.length) return <div className="muted">{empty}</div>
  return (
    <div className="mini-list" style={{ maxHeight: 360, overflow: 'auto', gap: 10 }}>
      {items.map((i, n) => (
        <div key={`${i.conversation}-${n}`} role="button" tabIndex={0} style={{ cursor: 'pointer' }} onClick={() => onOpen(i.conversation)} onKeyDown={(e) => { if (e.key === 'Enter') onOpen(i.conversation) }}>
          <div style={{ fontWeight: 600, overflowWrap: 'anywhere' }}>{i.question}</div>
          <div className="muted" style={{ fontSize: 12, overflowWrap: 'anywhere' }}>{i.reply.length > 180 ? `${i.reply.slice(0, 180)}…` : i.reply}</div>
          <div className="muted" style={{ fontSize: 12 }}>{dt(i.at)}{i.product_name ? ` · ${i.product_name}` : ''}</div>
        </div>
      ))}
    </div>
  )
}

export default function Chats() {
  const f = useFilters()
  const pre = f.prefill || {}
  const fresh = Boolean(pre.chat)
  const [open, setOpen] = usePersisted('chats.open', pre.chat || '', fresh)
  const [view, setView] = usePersisted('chats.view', 'all')
  const [text, setText] = usePersisted('chats.text', '')
  const [written, setWritten] = useState(false)
  const s = useApi('/chats', { compare: f.compare || undefined })
  return (
    <Loading state={s}>
      {(d) => {
        if (!d.ready) return <div className="banner err">The Roop chat table is not built yet. Press <b>Refresh</b> (top right) to pull and build it.</div>
        const t = d.totals
        const pt = d.prev?.totals
        const rated = t.thumbs_up + t.thumbs_down
        const daily = d.daily.map((r) => ({ date: r.day, value: r.messages, failed: r.failed }))
        return (
          <>
            <Card title="In short" sub={written ? 'Written from the numbers below, for the dates you picked.' : 'A written overview of these numbers, in plain sentences.'}
              right={<button type="button" className={`btn ${written ? '' : 'primary'}`} aria-expanded={written} onClick={() => setWritten(!written)}>{written ? 'Hide summary' : `Show written summary (${d.insights.length})`}</button>}>
              {written && <ul style={{ margin: 0, paddingLeft: 18, display: 'grid', gap: 4 }}>{d.insights.map((i, n) => <li key={n}><Badge tone={i.tone === 'good' ? 'good' : i.tone === 'warn' ? 'warn' : ''}>{i.tone}</Badge> {i.text}</li>)}</ul>}
            </Card>

            <div className="kpis" style={{ gridTemplateColumns: 'repeat(4, minmax(0, 1fr))' }}>
              <Kpi label="Messages" value={num(t.messages)} d={pt ? delta(t.messages, pt.messages) : null} note={`in ${num(t.chats)} chats, ${t.messages_per_chat} per chat`} />
              <Kpi label="Shoppers" value={num(t.shoppers)} d={pt ? delta(t.shoppers, pt.shoppers) : null} note={`${pct(t.shoppers ? t.logged_in_shoppers / t.shoppers : 0, 0)} logged in`} />
              <Kpi label="With a skin quiz" value={pct(t.shoppers ? t.shoppers_with_quiz / t.shoppers : 0, 0)} note={`${num(t.shoppers_with_quiz)} shoppers`} />
              <Kpi label="No answer" value={pct(t.messages ? t.failed / t.messages : 0, 0)} note={`${num(t.failed)} messages`} />
              <Kpi label="Helpful" value={rated ? pct(t.thumbs_up / rated, 0) : '–'} note={`👍 ${num(t.thumbs_up)} · 👎 ${num(t.thumbs_down)}`} />
              <Kpi label="Couldn't answer" value={pct(t.answered ? t.could_not_answer / t.answered : 0, 0)} note={`${num(t.could_not_answer)} answers`} />
              <Kpi label="Typical reply time" value={`${(t.median_latency_ms / 1000).toFixed(1)} sec`} note="half are quicker" />
              <Kpi label="Estimated AI cost" value={`₹${t.cost_inr.toFixed(2)}`} note={`₹${t.cost_inr_per_message.toFixed(3)} per message · ${num(t.tokens_per_message)} tokens`} />
            </div>
            {d.link.messages > d.link.with_visit && <div className="muted" style={{ fontSize: 12 }}>{num(d.link.with_visit)} of {num(d.link.messages)} messages could be tied to a visit; the rest were sent where the tracker did not record the answer.</div>}

            <Card title="Messages each day" sub="how many questions shoppers asked Roop">
              <div style={{ height: 220 }}>
                <ResponsiveContainer>
                  <BarChart data={daily} margin={{ left: 0, right: 12, top: 8, bottom: 0 }}>
                    <CartesianGrid stroke="var(--grid)" vertical={false} />
                    <XAxis dataKey="date" tickFormatter={day} {...axis} minTickGap={32} />
                    <YAxis {...axis} width={40} allowDecimals={false} />
                    <Tooltip {...chartTip} labelFormatter={day} formatter={(v, n, p) => [`${num(v)}${p.payload.failed ? ` (${p.payload.failed} without an answer)` : ''}`, 'messages']} />
                    <Bar dataKey="value" fill="var(--series-1)" radius={[2, 2, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>

            <div className="grid g3">
              <Card title="What they ask about" sub="every question sorted into a topic, from its words"><Bars items={d.topics} total={t.messages} empty="No questions in this period." /></Card>
              <Card title="Most asked questions" sub="the same words asked more than once"><Bars items={d.top_questions} empty="No questions in this period." /></Card>
              <Card title="Products they ask about" sub="the product pages Roop was opened on"><Bars items={d.products_asked_about} empty="No product pages in this period." /></Card>
              <Card title="Products Roop recommended" sub="other products shown as cards in its replies"><Bars items={d.products_recommended} empty="No recommendations in this period." /></Card>
              <Card title="Why messages got no answer" sub="shoppers saw an error instead of a reply"><Bars items={d.failures} total={t.failed} empty="Every message got an answer." /></Card>
              <Card title="AI model used"><Bars items={d.models} total={t.messages} empty="No messages in this period." /></Card>
            </div>

            <div className="grid g2">
              <Card title="Answers rated not helpful" sub="the clearest signal of what to improve. Click one to read the whole chat."><AnswerList items={d.disliked} onOpen={setOpen} empty="No answers were rated not helpful." /></Card>
              <Card title="Questions Roop couldn't answer" sub={'replies like "we don\'t stock it" or "not sure": gaps in the shop or in Roop\'s information'}><AnswerList items={d.could_not_answer} onOpen={setOpen} empty="Roop answered everything it was asked." /></Card>
            </div>

            <Conversations d={d} open={open} setOpen={setOpen} view={view} setView={setView} text={text} setText={setText} f={f} />
          </>
        )
      }}
    </Loading>
  )
}

function Conversations({ d, open, setOpen, view, setView, text, setText, f }) {
  const all = d.conversations
  const counts = useMemo(() => Object.fromEntries(VIEWS.map(([k, , test]) => [k, test ? all.filter(test).length : all.length])), [all])
  const list = useMemo(() => {
    const test = VIEWS.find(([k]) => k === view)?.[2]
    const q = text.trim().toLowerCase()
    return all.filter((c) => (!test || test(c)) && (!q || [c.product_name, c.user_id, c.key, c.visitor_id, c.guest_session_id, c.ip, c.city, c.channel, ...(c.sessions || []), ...c.questions].some((v) => String(v || '').toLowerCase().includes(q))))
  }, [all, view, text])
  return (
    <div className="grid g2">
      <Card title="Conversations" sub={d.conversations_total > all.length ? `The latest ${num(all.length)} of ${num(d.conversations_total)}. Pick fewer days to see the rest.` : 'click one to read it'}
        right={<ExportBtn name="roop-chats" rows={list} fields={[['Last message', 'updated_at'], ['Shopper', (c) => (c.user_id ? `logged in ${c.user_id}` : 'guest')], ['First question', (c) => c.questions[0]], ['Messages', 'messages'], ['Product', 'product_name'],
          ['Helpful', 'thumbs_up'], ['Not helpful', 'thumbs_down'], ['Failed', 'failed'], ['City', 'city'], ['IP', 'ip'], ['Channel', 'channel'], ['Device', 'device'], ['Session ids', (c) => c.sessions.join(' ')]]} />}>
        <div className="chip-row">
          <Search value={text} onChange={setText} placeholder="Filter: question, product, user, session, browser id, city or IP" />
          {VIEWS.map(([k, label]) => <button key={k} type="button" className={`chip ${view === k ? 'on' : ''}`} onClick={() => setView(k)}>{label} ({num(counts[k])})</button>)}
        </div>
        <Table scroll onRow={(c) => setOpen(c.key)} rowClass={(c) => (open === c.key ? 'active' : '')} rows={list} empty="No chats match." cols={[
          { label: 'Last message', cls: 'nw', sortBy: 'updated_at', render: (c) => dt(c.updated_at) },
          { label: 'Shopper', cls: 'nw', sortBy: 'user_id', render: (c) => (c.user_id ? <><b>Shopper {short(c.user_id)}</b> <Badge tone="good">logged in</Badge></> : 'Guest') },
          { label: 'First question', render: (c) => <span className="trunc" style={{ display: 'block', maxWidth: 260 }} title={c.questions[0]}>“{c.questions[0]}”</span> },
          { label: 'Msgs', num: true, sortBy: 'messages', render: (c) => c.messages },
          { label: 'Feedback', cls: 'nw', render: (c) => `${c.thumbs_up ? `👍 ${c.thumbs_up} ` : ''}${c.thumbs_down ? `👎 ${c.thumbs_down} ` : ''}${c.failed ? `${c.failed} failed` : ''}` || '–' },
          { label: 'Place · channel', cls: 'nw', sortBy: 'city', render: (c) => [c.city, c.channel].filter(Boolean).join(' · ') || '–' },
        ]} />
      </Card>
      <div>{open ? <Conversation chatKey={open} onClose={() => setOpen('')} f={f} /> : <Card title="Pick a conversation" sub="its full chat shows here, with times, ratings, the products Roop showed and the visit it happened in" />}</div>
    </div>
  )
}

/** The visit a chat happened in: the session data, with a way to open the whole session. */
function Visit({ s, f }) {
  return (
    <div style={{ borderTop: '1px solid var(--border)', paddingTop: 8 }}>
      <div className="row-between">
        <b>Visit {dt(s.started_at)}</b>
        <button type="button" className="btn small" onClick={() => f.go('session', { key: s.session_id })}>Open the session →</button>
      </div>
      <div className="muted" style={{ fontSize: 12, lineHeight: 1.6 }}>
        {dur(s.duration_s)} · {num(s.events)} events · {num(s.pageviews)} page views · reached: {STAGE[s.f_order ? 5 : s.stage]}<br />
        {s.channel} · {s.source} / {s.medium}{s.campaign && s.campaign !== '(not set)' ? ` · ${s.campaign}` : ''}<br />
        {[s.city, s.region].filter(Boolean).join(', ') || 'place unknown'} · {s.is_app ? 'Android app' : s.device || 'device unknown'}{s.platform ? ` (${s.platform})` : ''}{s.ip ? ` · IP ${s.ip}` : ''}<br />
        Browser <span className="mono">{short(s.visitor_key)}</span>{s.user_id ? <> · User <span className="mono">{short(s.user_id)}</span></> : ' · not logged in'} · {s.messages} message{s.messages === 1 ? '' : 's'} in this visit
        {s.is_excluded && <> · <Badge tone="bad">hidden internal traffic</Badge></>}
      </div>
    </div>
  )
}

/** One Roop conversation, turn by turn. */
function Conversation({ chatKey, onClose, f }) {
  const s = useApi(`/chats/${encodeURIComponent(chatKey)}`, {}, { scoped: false })
  useEffect(() => { document.getElementById('roop-chat')?.scrollIntoView({ block: 'nearest' }) }, [chatKey])
  const c = s.data
  return (
    <div id="roop-chat">
      <Card title={c?.product_name || 'Conversation'}
        sub={c ? `${c.user_id ? `Logged-in shopper ${short(c.user_id)}` : 'Guest'} · ${c.has_quiz ? 'has a skin quiz' : 'no skin quiz'} · ${c.turns.length} message${c.turns.length === 1 ? '' : 's'}` : s.error ? undefined : 'loading…'}
        right={<span className="chip-row">
          {c?.person && <button type="button" className="btn small" onClick={() => f.go('person', { key: c.person.person_key })}>Open person →</button>}
          <button type="button" className="btn small" onClick={onClose}>Close</button>
        </span>}>
        {s.error && <div className="banner err">Couldn't load this chat: {s.error}</div>}
        {c && (
          <div style={{ display: 'grid', gap: 10 }}>
            {c.person && <div className="muted" style={{ fontSize: 12 }}>{c.person.name || 'No name'}{c.person.phone10 ? ` · ${c.person.phone10}` : ''}{c.person.segment ? ` · ${c.person.segment}` : ''}{c.person.orders ? ` · ${c.person.orders} orders` : ''}</div>}
            {c.sessions.length ? c.sessions.map((x) => <Visit key={x.session_id} s={x} f={f} />) : <div className="muted">The visit for this chat wasn't found in the event log.</div>}
            {c.turns.map((t) => (
              <div key={t.id} style={{ display: 'grid', gap: 6, paddingTop: 10, borderTop: '1px solid var(--border)' }}>
                <div style={{ justifySelf: 'end', maxWidth: '88%', background: 'var(--text-primary)', color: 'var(--surface-1)', borderRadius: 12, padding: '8px 12px', overflowWrap: 'anywhere' }}>{t.question}</div>
                {t.error ? <div className="banner err">No answer: {t.error}</div>
                  : <div style={{ justifySelf: 'start', maxWidth: '92%', background: 'var(--surface-2)', borderRadius: 12, padding: '8px 12px', whiteSpace: 'pre-line', overflowWrap: 'anywhere' }}>{t.reply}</div>}
                <div className="muted" style={{ fontSize: 12 }}>
                  {dt(t.at)}{t.latency_ms ? ` · ${(t.latency_ms / 1000).toFixed(1)} sec` : ''}{t.tokens ? ` · ${num(t.tokens)} tokens` : ''}{` · ${t.topic}`}
                  {t.rating === 1 ? ' · 👍 helpful' : t.rating === -1 ? ' · 👎 not helpful' : ''}{t.products.length ? ` · showed: ${t.products.join(', ')}` : ''}
                  {t.session_id && c.sessions.length > 1 && <> · <a href={`#session/${encodeURIComponent(t.session_id)}`} onClick={(e) => { e.preventDefault(); f.go('session', { key: t.session_id }) }}>visit {short(t.session_id)}</a></>}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}
