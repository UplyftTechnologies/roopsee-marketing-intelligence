import { useRef } from 'react'
import { api, num } from '../api'
import { Banner, Card, Loading, Tree, useLoad } from '../ui'

export default function Overview({ ctx }) {
  const force = useRef(false)
  const [st, reload] = useLoad(() => { const f = force.current; force.current = false; return api('/api/overview' + (f ? '?refresh=true' : '')) })
  const refresh = () => { force.current = true; reload() }
  return (
    <Loading state={st}>
      {(d) => {
        if (!d.configured) return <Banner tone="err">Finish the setup first. Missing in <span className="mono">.env</span>: {d.missing.join(', ')}</Banner>
        if (d.error) return <Banner tone="err">Could not read Meta: {d.error}</Banner>
        const c = d.counts
        const tiles = [['Campaigns', c.campaigns], ['Ad sets', c.adsets], ['Ads', c.ads], ['Active ads', c.active_ads], ['Paused ads', c.paused_ads]]
        return (
          <>
            <div className="scorecards">
              {tiles.map(([l, v]) => <div key={l} className="sc static"><div className="sc-label">{l}</div><div className="sc-value">{num(v)}</div><div className="sc-foot"><span className="sc-note">{l === 'Campaigns' ? d.account_name : ''}</span></div></div>)}
            </div>
            {d.attention.length > 0 && (
              <>
                <div className="section-head"><h2>Needs attention</h2><span className="muted">Things worth a look</span></div>
                <div className="insight-grid">
                  {d.attention.map((a, i) => (
                    <div key={i} className={`insight ${a.tone}`}>
                      <div className="insight-title">{a.title}</div>
                      <p>{a.text}</p>
                    </div>
                  ))}
                </div>
              </>
            )}
            <Card title="Everything on Meta" sub={`read live from ${d.account_name || d.account} · refreshed ${d.fetched} · click the arrow to open a level`}
              right={<><button type="button" className="btn small" onClick={refresh}>Refresh</button><button type="button" className="btn primary small" onClick={() => ctx.go('new')}>New campaign</button></>}>
              <Tree nodes={d.tree} />
            </Card>
          </>
        )
      }}
    </Loading>
  )
}
