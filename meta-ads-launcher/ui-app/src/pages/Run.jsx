import { useState } from 'react'
import { api, runCommand } from '../api'
import { Badge, Banner, Card, JobPanel, Loading, useLoad } from '../ui'

const MODES = [['dry', 'Dry run', 'Shows what would be sent. Sends nothing.'], ['check', 'Check with Meta', 'Meta checks it. Nothing is created.'], ['real', 'Run for real', 'Creates things on Meta (paused).']]

export default function Run({ params }) {
  const [st, reload] = useLoad(() => api('/api/state'))
  return <Loading state={st}>{(s) => <Inner s={s} params={params} reload={reload} />}</Loading>
}

function Inner({ s, params, reload }) {
  const [batch, setBatch] = useState(params.batch || (s.batches.length ? s.batches[s.batches.length - 1].name : ''))
  const [mode, setMode] = useState('dry')
  const [prodOk, setProdOk] = useState(false)
  const [typed, setTyped] = useState('')
  const [job, setJob] = useState(null)
  const [busy, setBusy] = useState(false)
  const prod = s.env === 'production'
  const go = async (command, extra = {}) => {
    setBusy(true); setJob(null)
    try { await runCommand({ command, batch, mode, confirm_production: prodOk, ...extra }, setJob) } catch (e) { setJob({ steps: [], status: 'done', ok: false, log: e.message, hints: [] }) }
    setBusy(false); reload()
  }
  const toPublish = Object.entries(s.ads).filter(([, v]) => v.batch === batch && v.status !== 'ACTIVE')
  const needTick = mode === 'real' && prod && !prodOk
  const btn = (n, cmd, label, desc) => (
    <div className="list-row"><Badge>{n}</Badge><button type="button" className="btn primary" disabled={busy || !batch || needTick} onClick={() => go(cmd)}>{label}</button><span className="muted">{desc}</span></div>
  )
  return (
    <>
      <Card title="Run the steps by hand" sub="The New campaign page does all three steps for you. Use this when you want control over each one.">
        {s.batches.length === 0 ? <Banner>No batches yet. Create a campaign first.</Banner> : (
          <>
            <div className="fgrid">
              <label className="lf"><span className="lf-label">Batch</span>
                <select className="field" value={batch} onChange={(e) => setBatch(e.target.value)}>{s.batches.map((x) => <option key={x.name} value={x.name}>{x.name} · {x.ready}/{x.ads} ready{x.frozen ? ' · submitted' : ''}</option>)}</select>
              </label>
            </div>
            <div className="row" style={{ marginTop: 6 }}>
              {MODES.map(([v, l, d]) => <label key={v} className="chk" title={d}><input type="radio" name="mode" checked={mode === v} onChange={() => setMode(v)} />{l}</label>)}
            </div>
            <div className="sub">{MODES.find((m) => m[0] === mode)[2]}</div>
            {prod && mode === 'real' && <label className="chk"><input type="checkbox" checked={prodOk} onChange={(e) => setProdOk(e.target.checked)} /><b>I understand this is PRODUCTION (the real ad account)</b></label>}
            <div style={{ marginTop: 6 }}>
              {btn('1', 'upload', 'Upload images', 'Sends each image once and remembers its hash')}
              {btn('2', 'setup', 'Create campaign + ad set', 'Paused')}
              {btn('3', 'prepare', 'Create creative + ad', 'Paused. The batch is locked when this completes')}
            </div>
            <div className="row" style={{ marginTop: 10 }}>
              <button type="button" className="btn" disabled={busy || !batch} onClick={() => go('validate')}>Check the batch</button>
              <button type="button" className="btn" disabled={busy} onClick={() => go('live')}>Show live from Meta</button>
              <button type="button" className="btn" disabled={busy} onClick={() => go('status', { live: true })}>Status of my ads</button>
            </div>
          </>
        )}
      </Card>

      <Card title="Go live" sub="This is the only thing that can start spending money">
        {toPublish.length === 0 ? <div className="muted">No paused ads in this batch yet. Run the three steps first.</div> : (
          <>
            <table><thead><tr><th>Ad</th><th>Ad set</th><th>Now</th></tr></thead>
              <tbody>{toPublish.map(([k, v]) => <tr key={k}><td>{k}</td><td className="trunc">{v.adset_key}</td><td><Badge>{(v.status || '').toLowerCase()}</Badge></td></tr>)}</tbody></table>
            <div className="sub" style={{ margin: '8px 0' }}>Going live switches the campaign, ad set and ad on. Meta reviews the ad first, then it can spend.</div>
            <div className="row">
              <input className="field" style={{ maxWidth: 220 }} placeholder="type PUBLISH" value={typed} onChange={(e) => setTyped(e.target.value)} />
              <button type="button" className="btn danger" disabled={busy || typed !== 'PUBLISH' || (prod && !prodOk)} onClick={() => go('publish', { mode: 'real', confirm_text: typed })}>Go live</button>
              {prod && !prodOk && <span className="muted">Tick the production box above first.</span>}
            </div>
          </>
        )}
      </Card>
      {job && <Card title="Result"><JobPanel job={job} /></Card>}
    </>
  )
}
