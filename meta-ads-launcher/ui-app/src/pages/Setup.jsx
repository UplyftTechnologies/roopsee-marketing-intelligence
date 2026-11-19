import { useState } from 'react'
import { api } from '../api'
import { Banner, Card, Field, Loading, useLoad } from '../ui'

function Result({ r }) {
  if (!r) return null
  return (
    <div style={{ marginTop: 10 }}>
      {r.errors.map((e, i) => <div key={i} className="banner err" style={{ marginBottom: 6 }}><div>{e}</div></div>)}
      {r.warnings.map((e, i) => <div key={i} className="banner" style={{ marginBottom: 6 }}><div>{e}</div></div>)}
      {!r.errors.length && <div className="banner ok"><div>Saved. Everything checks out.</div></div>}
    </div>
  )
}

export default function Setup({ ctx }) {
  const [st] = useLoad(() => api('/api/config'))
  return (
    <Loading state={st}>
      {(cfg) => (
        <>
          <Banner tone="ok">Campaigns, ad sets and audiences now have their own page: <button type="button" className="btn small" onClick={() => ctx.go('campaigns')}>Campaigns &amp; ad sets</button>. This page holds the web page links and the tracking tags.</Banner>
          <Destinations items={cfg.destinations.destinations || []} />
          <Account acc={cfg.account || {}} />
        </>
      )}
    </Loading>
  )
}

function Destinations({ items }) {
  const [rows, setRows] = useState(() => items.map((x) => ({ ...x })))
  const [res, setRes] = useState(null)
  const set = (i, k, v) => setRows(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)))
  const save = async () => { try { setRes(await api('/api/config/destinations', { method: 'PUT', body: { destinations: rows.filter((r) => r.label && r.url) } })) } catch (e) { setRes({ errors: [e.message], warnings: [] }) } }
  return (
    <Card title="Web page links" sub="The pages ads can send people to. They appear as a dropdown when you create a campaign.">
      {rows.map((r, i) => (
        <div key={i} className="fgrid" style={{ padding: '6px 0' }}>
          <Field label="Name"><input className="field" value={r.label} onChange={(e) => set(i, 'label', e.target.value)} /></Field>
          <Field label="Link (https://…)"><input className="field" value={r.url} onChange={(e) => set(i, 'url', e.target.value)} /></Field>
          <div style={{ alignSelf: 'end' }}><button type="button" className="btn small danger" onClick={() => setRows(rows.filter((_, j) => j !== i))}>Remove</button></div>
        </div>
      ))}
      <div className="row"><button type="button" className="btn" onClick={() => setRows([...rows, { label: '', url: 'https://' }])}>Add a link</button><button type="button" className="btn primary" onClick={save}>Save links</button></div>
      <Result r={res} />
    </Card>
  )
}

function Account({ acc }) {
  const [a, setA] = useState(acc)
  const [res, setRes] = useState(null)
  return (
    <Card title="Account and tracking">
      <div className="fgrid">
        <Field label="Currency"><input className="field" value={a.currency || ''} onChange={(e) => setA({ ...a, currency: e.target.value })} /></Field>
        <Field label="Smallest units per 1 currency unit" hint="100 for rupees and paise"><input className="field" type="number" min="1" value={a.currency_offset ?? 100} onChange={(e) => setA({ ...a, currency_offset: e.target.value === '' ? '' : Number(e.target.value) })} /></Field>
      </div>
      <Field label="Tracking tags added to every link" hint="Meta fills {{campaign.id}}, {{ad.id}} and {{adset.id}}. The dashboard uses these to match visits to campaigns."><textarea className="field" value={a.url_tags || ''} onChange={(e) => setA({ ...a, url_tags: e.target.value })} /></Field>
      <div className="row"><button type="button" className="btn primary" onClick={async () => { try { setRes(await api('/api/config/account', { method: 'PUT', body: { ...a, currency_offset: Number(a.currency_offset) > 0 ? Number(a.currency_offset) : 100 } })) } catch (e) { setRes({ errors: [e.message], warnings: [] }) } }}>Save</button></div>
      <Result r={res} />
    </Card>
  )
}
