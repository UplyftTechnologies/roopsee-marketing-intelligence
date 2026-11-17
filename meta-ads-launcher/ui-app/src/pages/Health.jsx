import { useState } from 'react'
import { runCommand } from '../api'
import { Badge, Banner, Card } from '../ui'

export default function Health({ ctx }) {
  const [job, setJob] = useState(null)
  const [busy, setBusy] = useState(false)
  const env = ctx.env
  const run = async () => { setBusy(true); try { await runCommand({ command: 'doctor' }, setJob) } finally { setBusy(false) } }
  const lines = (job?.log || '').split('\n').map((l) => l.match(/^\s+(OK|FAIL|note|skip)\s+(.*)$/)).filter(Boolean)
  return (
    <>
      <Card title="Connection check" sub="Read-only. Checks the token, permissions, ad account and Page. Nothing is changed."
        right={<button type="button" className="btn primary" disabled={busy} onClick={run}>{busy ? 'Checking…' : 'Run check'}</button>}>
        {env?.missing?.length > 0 && <Banner tone="err">Missing in <span className="mono">.env</span>: {env.missing.join(', ')}</Banner>}
        {lines.length > 0 ? (
          <div className="checks">{lines.map((m, i) => <div key={i}><Badge tone={m[1] === 'OK' ? 'good' : m[1] === 'FAIL' ? 'bad' : 'warn'}>{m[1] === 'OK' ? 'OK' : m[1] === 'FAIL' ? 'Fix' : 'Note'}</Badge><span>{m[2]}</span></div>)}</div>
        ) : job ? <pre className="log">{job.log || '…'}</pre> : <div className="muted">Press Run check.</div>}
      </Card>
      <Card title="Where things are kept" sub="For reference">
        <dl className="facts">
          <dt>Environment</dt><dd>{env?.env}</dd>
          <dt>Ad account</dt><dd>{env?.account || 'not set'}</dd>
          <dt>Facebook Page</dt><dd>{env?.page_id || 'not set'}</dd>
          <dt>API version</dt><dd>{env?.version}</dd>
          <dt>Credentials file</dt><dd>.env in the launcher folder (the starting environment is set there; switch for this window with the Sandbox / Production button at the top right)</dd>
        </dl>
      </Card>
    </>
  )
}
