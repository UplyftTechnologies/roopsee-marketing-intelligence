import { useEffect, useState } from 'react'
import { api, day, dt, inr, num, pct, useApi, useFilters } from '../api'
import { Badge, Card, Chips, CopyTable, ExportBtn, Kpi, Loading, Table, verdictTone } from '../ui'
import { METRICS } from '../metrics'
import { Scorecard, ScorecardStrip } from '../components/Scorecard'
import MetricChart from '../components/MetricChart'
import { CopyBtn } from '../components/profile'

const CARDS = ['m_spend', 'm_clicks', 'm_ctr', 'm_cpc', 'm_sessions', 'm_carts']
const URL_PARAMS = 'utm_source=facebook&utm_medium=paid_social&utm_campaign={{campaign.id}}&utm_content={{ad.id}}&utm_term={{adset.id}}'
const VERDICT = { 'Paying back': 'good', Converting: 'good', Promising: 'warn', 'Wasting spend': 'bad', 'Too early': '' }
const rupee = (v) => (v == null ? '–' : '₹' + Number(v).toFixed(2))
const STATUS_TONE = { ACTIVE: 'good', PAUSED: '', CAMPAIGN_PAUSED: '', ADSET_PAUSED: '', ARCHIVED: '', DELETED: '', WITH_ISSUES: 'bad' }

function Status({ onSynced }) {
  const f = useFilters()
  const [st, setSt] = useState(null)
  const [busy, setBusy] = useState(false)
  const load = () => api('/meta/status', { params: { check: true } }).then(setSt).catch(() => {})
  useEffect(() => { load() }, [f.tick])
  if (!st) return null
  const exp = st.token?.expires_at ? new Date(st.token.expires_at) : null
  const daysLeft = exp ? Math.round((exp - new Date()) / 86400000) : null
  const sync = async () => { setBusy(true); try { await api('/meta/sync', { method: 'POST' }); f.reloadMeta() } catch { /* shown via job status */ } setBusy(false); onSynced?.() }
  return (
    <Card title="Connection" sub="read-only: this dashboard can only read your Meta data, never change your ads"
      right={<button type="button" className="btn primary small" disabled={busy || f.meta?.job?.running || !st.configured} onClick={sync}>{busy || f.meta?.job?.running ? 'Syncing…' : 'Sync Meta now'}</button>}>
      {!st.configured
        ? <div className="banner err">Add <span className="mono">META_ACCESS_TOKEN=…</span> to the <span className="mono">.env</span> file, then restart.</div>
        : (
          <div className="chip-row">
            <Badge tone={st.token?.valid ? 'good' : 'bad'}>{st.token?.valid ? `Connected as ${st.user || 'user'}` : 'Token problem'}</Badge>
            <Badge>{st.accounts.length} ad account{st.accounts.length === 1 ? '' : 's'}</Badge>
            <Badge>{num(st.rows)} daily rows · {st.first_day ? `${day(String(st.first_day))} – ${day(String(st.last_day))}` : 'not synced yet'}</Badge>
            <span className="muted" style={{ fontSize: 12 }}>last sync {st.last_sync ? dt(st.last_sync) : 'never'} · syncs automatically with “Refresh”</span>
          </div>
        )}
      {st.last_error && <div className="banner err" style={{ marginTop: 10 }}>Last sync failed: {st.last_error}</div>}
      {daysLeft !== null && daysLeft <= 30 && (
        <div className="banner" style={{ marginTop: 10 }}>
          <div><b>The Meta token expires on {exp.toLocaleDateString('en-IN', { day: 'numeric', month: 'long', year: 'numeric' })} ({Math.max(daysLeft, 0)} days).</b> After that, syncing stops.
            <div className="muted">Replace it with a System User token (Business Settings → System users) which does not expire, and update META_ACCESS_TOKEN in .env.</div></div>
        </div>
      )}
    </Card>
  )
}

function Levels({ campaigns }) {
  const f = useFilters()
  const [level, setLevel] = useState('campaign')
  const s = useApi('/meta/breakdown', { level: level === 'campaign' ? 'adset' : level }, { scoped: true })
  return (
    <Card title="Campaigns, ad sets and ads" sub="click a column title to sort · our sessions and orders are matched at campaign level"
      right={<Chips value={level} onChange={setLevel} options={[{ value: 'campaign', label: 'Campaigns' }, { value: 'adset', label: 'Ad sets' }, { value: 'ad', label: 'Ads' }]} />}>
      {level === 'campaign' ? (
        <Table rows={campaigns} empty="No Meta spend in this range" onRow={(r) => f.go('sessions', { channel: 'Paid Meta', search: r.campaign_id })} cols={[
          { label: 'Campaign', sortBy: 'name', render: (r) => <span className="trunc" style={{ display: 'block', maxWidth: 200 }} title={`${r.name} (${r.campaign_id})`}>{r.name}</span> },
          { label: 'Status', cls: 'nw', sortBy: 'status', render: (r) => (r.status ? <Badge tone={STATUS_TONE[r.status]}>{r.status.toLowerCase().replace(/_/g, ' ')}</Badge> : '–') },
          { label: 'Spend', num: true, sortBy: 'spend', render: (r) => <b>{inr(r.spend)}</b> },
          { label: 'Verdict', cls: 'nw', sortBy: 'verdict', render: (r) => <Badge tone={VERDICT[r.verdict]}>{r.verdict}</Badge> },
          { label: 'Our orders', num: true, sortBy: 'orders', render: (r) => num(r.orders) },
          { label: 'ROAS (matched orders)', num: true, sortBy: 'our_roas', render: (r) => (r.our_roas == null ? '–' : `${r.our_roas.toFixed(2)}×`) },
          { label: 'Carts', num: true, sortBy: 'carts', render: (r) => num(r.carts) },
          { label: 'Cost / cart', num: true, sortBy: 'cost_per_cart', render: (r) => rupee(r.cost_per_cart) },
          { label: 'Our sessions', num: true, sortBy: 'sessions', render: (r) => num(r.sessions) },
          { label: 'Clicks → sessions', num: true, sortBy: 'click_to_session', render: (r) => (r.click_to_session == null ? '–' : pct(r.click_to_session, 0)) },
          { label: 'Clicks', num: true, sortBy: 'link_clicks', render: (r) => num(r.link_clicks) },
          { label: 'CTR', num: true, sortBy: 'ctr', render: (r) => pct(r.ctr, 2) },
          { label: 'CPC', num: true, sortBy: 'cpc', render: (r) => rupee(r.cpc) },
          { label: 'Meta says', num: true, sortBy: 'meta_purchases', render: (r) => <span title={`Meta reports ${num(r.meta_purchases)} purchases worth ${inr(r.meta_value)}`}>{num(r.meta_purchases)} bought</span> },
        ]} />
      ) : (
        <Loading state={s}>
          {({ rows }) => (
            <Table rows={rows} empty="Nothing in this range" cols={[
              ...(level === 'ad' ? [{ label: '', render: (r) => (r.thumbnail_url ? <img src={r.thumbnail_url} alt="" width="40" height="40" style={{ borderRadius: 6, objectFit: 'cover' }} loading="lazy" /> : null) }] : []),
              { label: level === 'ad' ? 'Ad' : 'Ad set', sortBy: 'name', render: (r) => <span className="trunc" style={{ display: 'block', maxWidth: 240 }} title={r.name}>{r.name}</span> },
              { label: 'Campaign', sortBy: 'campaign', render: (r) => <span className="trunc muted" style={{ display: 'block', maxWidth: 190 }} title={r.campaign}>{r.campaign}</span> },
              { label: 'Spend', num: true, sortBy: 'spend', render: (r) => <b>{inr(r.spend)}</b> }, { label: 'Impressions', num: true, sortBy: 'impressions', render: (r) => num(r.impressions) },
              { label: 'Clicks', num: true, sortBy: 'link_clicks', render: (r) => num(r.link_clicks) }, { label: 'CTR', num: true, sortBy: 'ctr', render: (r) => pct(r.ctr, 2) },
              { label: 'CPC', num: true, sortBy: 'cpc', render: (r) => rupee(r.cpc) }, { label: 'Meta: carts', num: true, sortBy: 'meta_atc', render: (r) => num(r.meta_atc) },
              { label: 'Meta: purchases', num: true, sortBy: 'meta_purchases', render: (r) => num(r.meta_purchases) },
            ]} />
          )}
        </Loading>
      )}
    </Card>
  )
}

/** Campaign -> ad set -> ad as one expandable tree, with spend and results at every level. */
function Flow({ data, open, setOpen, q }) {
  const ql = q.trim().toLowerCase()
  const m = (n) => !ql || n.name.toLowerCase().includes(ql) || String(n.id).includes(ql)
  const has = (n) => m(n) || (n.children || []).some(has)
  const rows = []
  const push = (n, parent) => {
    rows.push({ n, parent })
    const kids = (n.children || []).filter(has)
    if (kids.length && (open.has(n.id) || ql)) kids.forEach((k) => push(k, n))
  }
  data.campaigns.filter(has).forEach((c) => push(c, null))
  const toggle = (id) => { const x = new Set(open); if (x.has(id)) x.delete(id); else x.add(id); setOpen(x) }
  if (!rows.length) return <div className="muted">Nothing matches.</div>
  return (
    <CopyTable cls="table-wrap">
      <table className="tree">
        <thead>
          <tr>
            <th>Campaign → ad set → ad</th><th>Status</th><th className="num">Budget / day</th><th className="num">Spend</th><th className="num">Impressions</th><th className="num">Clicks</th>
            <th className="num">CTR</th><th className="num">CPC</th><th className="num">Meta: carts</th><th className="num">Meta: purchases</th><th className="num">Meta ROAS</th><th className="num" title="Orders tied to this campaign by its id or name">Matched orders</th><th className="num" title="Revenue of the matched orders divided by spend">ROAS (matched)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ n, parent }) => {
            const kids = n.children ? n.children.length : 0
            const isOpen = open.has(n.id) || (!!ql && kids > 0)
            const share = parent && parent.spend ? Math.min(100, (n.spend / parent.spend) * 100) : null
            const camp = n.level === 'campaign'
            return (
              <tr key={`${n.level}-${n.id}`} className={`lv-${n.level}`}>
                <td>
                  <div className="nm">
                    {kids ? <button type="button" className="caret" aria-label={isOpen ? 'Collapse' : 'Expand'} aria-expanded={isOpen} onClick={() => toggle(n.id)}><span style={{ display: 'inline-block', transition: 'transform .12s', transform: isOpen ? 'rotate(90deg)' : 'none' }}>›</span></button> : <span className="caret" />}
                    {n.level === 'ad' && n.thumbnail_url && <img src={n.thumbnail_url} alt="" width="28" height="28" loading="lazy" />}
                    <span className="tag">{n.level === 'adset' ? 'ad set' : n.level}</span>
                    <span className="trunc" style={{ maxWidth: 260 }} title={`${n.name} (${n.id})`}>{n.name}</span>
                    {kids > 0 && <span className="muted" style={{ fontSize: 12 }}>{kids}</span>}
                  </div>
                </td>
                <td className="nw">{n.status ? <Badge tone={STATUS_TONE[n.status]}>{n.status.toLowerCase().replace(/_/g, ' ')}</Badge> : '–'}</td>
                <td className="num">{n.daily_budget ? inr(n.daily_budget) : '–'}</td>
                <td className="num"><b>{inr(n.spend)}</b>{share != null && <div className="share" style={{ width: `${Math.max(share, 2)}%` }} title={`${share.toFixed(0)}% of the parent's spend`} />}</td>
                <td className="num">{num(n.impressions)}</td>
                <td className="num">{num(n.link_clicks)}</td>
                <td className="num">{pct(n.ctr, 2)}</td>
                <td className="num">{rupee(n.cpc)}</td>
                <td className="num">{num(n.meta_atc)}</td>
                <td className="num">{num(n.meta_purchases)}</td>
                <td className="num">{n.meta_roas == null ? '–' : `${n.meta_roas.toFixed(2)}×`}</td>
                <td className="num">{camp ? num(n.orders) : <span className="muted" title="Our sessions and orders are matched to campaigns only">–</span>}</td>
                <td className="num">{camp ? (n.our_roas == null ? '–' : `${n.our_roas.toFixed(2)}×`) : <span className="muted">–</span>}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </CopyTable>
  )
}

function Hierarchy() {
  const [idle, setIdle] = useState(false)
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(() => new Set())
  const s = useApi('/meta/hierarchy', { include_idle: idle }, { scoped: true })
  return (
    <Card title="Campaign structure" sub="how spend flows from each campaign to its ad sets and ads · click the arrow to open a level">
      <Loading state={s}>
        {(d) => {
          if (!d.connected) return <div className="muted">No Meta data yet.</div>
          const all = d.campaigns.flatMap((c) => [c.id, ...c.children.map((a) => a.id)])
          return (
            <>
              <div className="chip-row" style={{ marginBottom: 10 }}>
                <button type="button" className="btn small" onClick={() => setOpen(new Set(all))}>Expand all</button>
                <button type="button" className="btn small" onClick={() => setOpen(new Set())}>Collapse all</button>
                <input className="field" style={{ maxWidth: 240 }} placeholder="Find a campaign, ad set or ad…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search the structure" />
                <label className="chk"><input type="checkbox" checked={idle} onChange={(e) => setIdle(e.target.checked)} /> Include items with no spend</label>
                <span className="muted" style={{ fontSize: 12 }}>{d.counts.campaigns} campaigns · {d.counts.adsets} ad sets · {d.counts.ads} ads</span>
              </div>
              <Flow data={d} open={open} setOpen={setOpen} q={q} />
              <div className="muted" style={{ marginTop: 8, fontSize: 12 }}>Spend, clicks and the “Meta” columns are Meta’s own numbers at every level. “Our orders / ROAS” come from your tracked sessions and can only be matched to campaigns, so they are shown on campaign rows only.</div>
            </>
          )
        }}
      </Loading>
    </Card>
  )
}

import MetaReconcile from '../components/MetaReconcile'

export default function MetaAds() {
  const f = useFilters()
  const [metric, setMetric] = useState('m_spend')
  const s = useApi('/meta/overview')
  const [tick, setTick] = useState(0)
  return (
    <>
      <Status onSynced={() => setTick(tick + 1)} key={tick} />
      <Loading state={s}>
        {(o) => {
          if (!o.connected) return <div className="banner">No Meta data yet. Press <b>Sync Meta now</b> above.</div>
          const ts = { dates: o.dates, current: o.current, previous: o.previous, prev_dates: o.prev_dates }
          const t = o.totals
          const cov = o.coverage
          const covPct = cov.paid_meta_sessions ? cov.matched / cov.paid_meta_sessions : 1
          const b = o.blended
          return (
            <>
              <ScorecardStrip>
                {CARDS.map((k) => <Scorecard key={k} metric={k} kpis={t} prev={o.prev} compare={f.compare} spark={METRICS[k].series ? o.current[METRICS[k].series] : undefined} active={metric === k} onClick={METRICS[k].series ? () => setMetric(k) : undefined} />)}
              </ScorecardStrip>
              <Card title={METRICS[metric].label} sub="Click a tile above to change the chart">
                <MetricChart ts={ts} metric={metric} compare={f.compare} height={230} ranges={{ cur: f.rangeText, prev: f.prevText }} />
              </Card>

              <Card title="What the spend brought in" sub="all Paid Meta traffic, including sessions whose campaign tag could not be matched to a Meta campaign">
                <div className="kpis">
                  <Kpi label="Meta spend" value={inr(b.spend)} note={`${num(t.impressions)} impressions`} />
                  <Kpi label="Orders from Paid Meta traffic" value={num(b.orders)} note={inr(b.revenue)} d={null} />
                  <Kpi label="Return on ad spend" value={b.roas == null ? '–' : `${b.roas.toFixed(2)}×`} note="tracked order value ÷ spend" />
                  <Kpi label="Cost per order" value={b.cost_per_order == null ? '–' : inr(b.cost_per_order)} note={`Meta itself reports ${num(t.meta_purchases)} purchases (${inr(t.meta_value)})`} />
                </div>
                <div className="muted" style={{ marginTop: 8, fontSize: 12 }}>
                  Of the {num(b.orders)} orders, <b>{num(t.orders)} ({inr(t.revenue)})</b> could be tied to a specific campaign: only those appear in the campaign table below, so its ROAS is lower than the figure above.
                  <br />Meta counts conversions within its own attribution window (7-day click, 1-day view) and can report orders your site never saw, so the two numbers rarely agree.
                  Your tracked orders are the conservative figure. Sales on cash-on-delivery orders that never linked to a session are missing from both.
                </div>
              </Card>

              <MetaReconcile />

              {covPct < 0.9 && (
                <div className="banner">
                  <div><b>{pct(covPct, 0)} of your Paid Meta sessions are linked to a campaign.</b> The rest carry hand-typed names that don't match anything in Meta, or are ambiguous:
                    <span className="mono"> {cov.unmatched.slice(0, 4).map((u) => `${u.campaign} (${u.sessions})`).join(' · ')}</span>
                    <div className="muted" style={{ marginTop: 6 }}>
                      Fix it at the source: in each Meta ad set URL parameters, paste this so every click carries the real IDs:
                      <div className="mono" style={{ margin: '4px 0', wordBreak: 'break-all' }}>{URL_PARAMS} <CopyBtn text={URL_PARAMS} title="Copy URL parameters" /></div>
                    </div></div>
                </div>
              )}

              <Levels campaigns={o.campaigns} />

              {o.wasted.length > 0 && (
                <Card title="Spending without results" sub="campaigns with ₹300+ spend and no add-to-cart from tracked sessions in this range">
                  <Table rows={o.wasted} cols={[{ label: 'Campaign', sortBy: 'name', render: (r) => r.name }, { label: 'Spend', num: true, sortBy: 'spend', render: (r) => <b>{inr(r.spend)}</b> },
                    { label: 'Clicks', num: true, sortBy: 'link_clicks', render: (r) => num(r.link_clicks) }, { label: 'Our sessions', num: true, sortBy: 'sessions', render: (r) => num(r.sessions) },
                    { label: 'Status', render: (r) => (r.status ? <Badge tone={STATUS_TONE[r.status]}>{r.status.toLowerCase().replace(/_/g, ' ')}</Badge> : '–') }]} />
                  <div className="muted" style={{ marginTop: 6, fontSize: 12 }}>A campaign showing 0 sessions may simply be an app-install campaign or one whose clicks go elsewhere, so check its objective before pausing it.</div>
                </Card>
              )}
              <Hierarchy />
              <ExportBtn name="meta-campaigns" rows={o.campaigns} fields={[['Campaign', 'name'], ['Status', 'status'], ['Spend', 'spend'], ['Impressions', 'impressions'], ['Link clicks', 'link_clicks'], ['CTR', 'ctr'], ['CPC', 'cpc'], ['Our sessions', 'sessions'], ['Carts', 'carts'], ['Our orders', 'orders'], ['Our revenue', 'revenue'], ['Meta purchases', 'meta_purchases'], ['Verdict', 'verdict']]} />
            </>
          )
        }}
      </Loading>
    </>
  )
}
