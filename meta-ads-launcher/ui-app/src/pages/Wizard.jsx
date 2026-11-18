import { useRef, useState } from 'react'
import Icon from '../Icon'
import { api, inr } from '../api'
import { Badge, Banner, Card, Field, JobPanel } from '../ui'
import { MetaImageGrid, MetaImg } from '../MetaImages'
import SpecAdCard from './SpecAd'

export const uid = () => 's' + Math.random().toString(36).slice(2, 7)

export const themeOf = (name, fallback) => { const m = /^RS_([A-Za-z0-9]+)_\d+/.exec(name || ''); return m ? m[1] : (fallback || 'meta') }
const CtaLabel = { LEARN_MORE: 'Learn more', SHOP_NOW: 'Shop now', SIGN_UP: 'Sign up', GET_OFFER: 'Get offer', ORDER_NOW: 'Order now', CONTACT_US: 'Contact us', SUBSCRIBE: 'Subscribe' }
export const audLabel = (o, s) => (s.audience === 'custom' ? `Custom (${s.custom.countries}, ${s.custom.age_min}-${s.custom.age_max}${s.custom.gender !== 'all' ? ', ' + s.custom.gender : ''})`
  : o.audiences.find((x) => x.id === s.audience)?.label || s.audience)
export const placeLabel = (o, s) => o.placements.find((x) => x.id === s.placements)?.label || s.placements

export function Counter({ label, value, limit, children }) {
  const n = (value || '').length
  return (
    <label className="lf">
      <span className="lf-label">{label}<span className={`cnt ${n > limit ? 'over' : ''}`}>{n}/{limit}</span></span>
      {children}
    </label>
  )
}

export function FeedPreview({ ad }) {
  let host = ''
  try { host = new URL(ad.destination).host } catch { /* ignore */ }
  return (
    <div className="fp">
      <div className="ph"><i>R</i>Roopsee.<small>Sponsored</small></div>
      <div className="pt">{ad.primary_text || 'Your main text appears here'}</div>
      {ad.image ? <img src={'/' + ad.image} alt="" /> : ad.preview_url ? <MetaImg src={ad.preview_url} alt="" /> : <div className="noimg">{ad.image_hash ? 'Image already on Meta' : 'No image yet'}</div>}
      <div className="cta"><div><small>{host}</small><b>{ad.headline || 'Your headline'}</b></div><span>{CtaLabel[ad.cta] || 'Learn more'}</span></div>
    </div>
  )
}

export function Step4({ o, a, setA, set, noPreview, saveTpl, renderKind }) {
  const d = a.defaults
  const [theme, setTheme] = useState(o.categories[0] || '')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const [lib, setLib] = useState(null)
  const [hash, setHash] = useState({ hash: '', key: '' })
  const [pick, setPick] = useState(false)
  const input = useRef(null)
  const setD = (k, v) => set('defaults', { ...d, [k]: v })
  const addAd = (extra) => setA((x) => ({ ...x, ads: [...x.ads, { ...x.defaults, ...extra }] }))
  const upd = (i, k, v) => setA((x) => ({ ...x, ads: x.ads.map((ad, j) => (j === i ? { ...ad, [k]: v } : ad)) }))
  const all = a.adsets.map((s) => s.uid)
  const toggleSet = (i, u) => {
    const cur = a.ads[i].sets || all
    let next = cur.includes(u) ? cur.filter((x) => x !== u) : [...cur, u]
    if (next.length === 0) return // an ad must appear somewhere
    if (next.length === all.length) next = null
    upd(i, 'sets', next)
  }

  const upload = async (files) => {
    if (!theme.trim()) { setMsg('Type a theme first (for example acne). It names the images.'); return }
    setBusy(true); setMsg(null)
    for (const f of files) {
      const fd = new FormData(); fd.append('file', f); fd.append('category', theme.trim().toLowerCase().replace(/[^a-z0-9_]/g, '_'))
      try { const r = await api('/api/creatives', { method: 'POST', body: fd }); addAd({ image: r.saved, ad_key: r.key }) } catch (e) { setMsg(`${f.name}: ${e.message}`) }
    }
    setBusy(false)
  }
  const addMeta = async (img) => {
    try {
      const key = (await api('/api/next-key?theme=' + encodeURIComponent(themeOf(img.name, theme)))).key
      addAd({ image_hash: img.hash, ad_key: key, preview_url: img.full || img.thumb })
      setMsg(null); setPick(false)
    } catch (e) { setMsg(e.message) }
  }
  const openLib = async () => setLib((await api('/api/creatives')).filter((c) => !c.used && !a.ads.some((x) => x.image === c.path)))

  return (
    <div className={noPreview ? "" : "wiz"}>
      <div className="stack">
        <Card title="Your ads" sub={a.adsets.length > 1 ? 'Each image becomes one ad. Choose which ad sets show it. An ad shown in two ad sets is created once for each.' : 'Each image becomes one ad. Write the text once below, then adjust any ad if you want.'}>
          <fieldset className="set"><legend>Text used for every new ad</legend>
            <div className="fgrid">
              <Counter label="Main text" value={d.primary_text} limit={125}><textarea className="field" value={d.primary_text} onChange={(e) => setD('primary_text', e.target.value)} placeholder="What do you want to say?" /></Counter>
              <div className="stack">
                <Counter label="Headline" value={d.headline} limit={40}><input className="field" value={d.headline} onChange={(e) => setD('headline', e.target.value)} /></Counter>
                <Field label="Button"><select className="field" value={d.cta} onChange={(e) => setD('cta', e.target.value)}>{o.ctas.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}</select></Field>
              </div>
              <DestPick o={o} value={d.destination} onChange={(v) => setD('destination', v)} />
            </div>
            {a.ads.some((ad) => !ad.creative_spec) && <button type="button" className="btn small" style={{ marginTop: 8 }} onClick={() => setA((x) => ({ ...x, ads: x.ads.map((ad) => (ad.creative_spec ? ad : { ...ad, primary_text: d.primary_text, headline: d.headline, cta: d.cta, destination: d.destination })) }))}>Apply this text to all {a.ads.filter((ad) => !ad.creative_spec).length} image ad(s)</button>}
          </fieldset>

          <div className="fgrid" style={{ margin: '14px 0 8px' }}>
            <Field label="Theme of the new images" hint="For example acne, pigmentation, trust. Used to name and group the image files you upload">
              <input className="field" list="wthemes" value={theme} onChange={(e) => setTheme(e.target.value)} placeholder="acne" />
            </Field>
          </div>
          <datalist id="wthemes">{o.categories.map((c) => <option key={c} value={c} />)}</datalist>
          <div className="drop" onClick={() => input.current.click()} onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); upload([...e.dataTransfer.files]) }}>
            {busy ? 'Uploading…' : 'Drop images here, or click to choose. You can pick several.'}
            <input ref={input} type="file" accept=".jpg,.jpeg,.png" multiple hidden onChange={(e) => { upload([...e.target.files]); e.target.value = '' }} />
          </div>
          {msg && <Banner tone="err">{msg}</Banner>}
          <div className="row" style={{ marginTop: 10 }}>
            <button type="button" className="btn small" onClick={openLib}>Pick from my library</button>
            <button type="button" className="btn small" onClick={() => setPick(!pick)}>{pick ? 'Close Meta images' : 'Pick an image already on Meta'}</button>
            <details><summary className="btn small" style={{ display: 'inline-block', cursor: 'pointer' }}>Or paste an image hash</summary>
              <div className="fgrid" style={{ marginTop: 8 }}>
                <Field label="Image hash"><input className="field" value={hash.hash} onChange={(e) => setHash({ ...hash, hash: e.target.value })} placeholder="32 letters and digits" /></Field>
              </div>
              <button type="button" className="btn small" style={{ marginTop: 8 }} onClick={async () => {
                const h = hash.hash.trim().toLowerCase()
                if (!/^[0-9a-f]{32}$/.test(h)) { setMsg('That image hash does not look right. It should be 32 letters and digits.'); return }
                let img
                try { img = (await api('/api/meta-images?hashes=' + h)).images?.[0] } catch (e) { setMsg(e.message); return }
                if (!img) { setMsg('That hash is not in this ad account. Use "Pick an image already on Meta" to see the ones you have.'); return }
                let key = hash.key.trim()
                if (!key) { try { key = (await api('/api/next-key?theme=' + encodeURIComponent(themeOf(img.name, theme)))).key } catch (e) { setMsg(e.message); return } }
                setMsg(null); addAd({ image_hash: img.hash, ad_key: key, preview_url: img.full || img.thumb }); setHash({ hash: '', key: '' })
              }}>Add this ad</button>
            </details>
          </div>
          {pick && <div style={{ marginTop: 12 }}><MetaImageGrid limit={24} actions={(i) => <button type="button" className="btn small primary" onClick={() => addMeta(i)}>Use this image</button>} /></div>}
          {lib && (lib.length === 0 ? <div className="muted" style={{ marginTop: 8 }}>No unused images in your library.</div> : (
            <div className="picker" style={{ marginTop: 10 }}>{lib.map((c) => <button type="button" key={c.path} className="pick" onClick={() => { addAd({ image: c.path, ad_key: c.key }); setLib(lib.filter((x) => x.path !== c.path)) }}><img src={'/' + c.path} alt="" /><span>{c.key}</span></button>)}</div>
          ))}
        </Card>

        {a.ads.map((ad, i) => ad.kind && renderKind ? renderKind(ad, i, { upd, toggleSet, all, remove: () => setA((x) => ({ ...x, ads: x.ads.filter((_, j) => j !== i) })) }) : ad.creative_spec ? (
          <SpecAdCard key={ad.ad_key + i} ad={ad} i={i} a={a} all={all} o={o} upd={upd} toggleSet={toggleSet} onSave={() => saveTpl && saveTpl('ad', ad)}
            remove={() => setA((x) => ({ ...x, ads: x.ads.filter((_, j) => j !== i) }))} />
        ) : (
          <div key={ad.ad_key + i} className="adcard">
            {ad.image ? <img className="pic" src={'/' + ad.image} alt="" /> : ad.preview_url ? <div className="pic metapic"><MetaImg src={ad.preview_url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} /></div> : <div className="pic">image hash<br />{(ad.image_hash || '').slice(0, 8)}…</div>}
            <div className="stack">
              <div className="row"><b>{ad.name || `Image ad ${i + 1}`}</b>{!ad.image && <span className="mini mono">hash {(ad.image_hash || '').slice(0, 10)}…</span>}
                <button type="button" className="btn small danger right" onClick={() => setA((x) => ({ ...x, ads: x.ads.filter((_, j) => j !== i) }))}><Icon name="trash" size={13} /> Remove</button></div>
              <label className="lf"><span className="lf-label">Ad name <span className="muted">(shown in Ads Manager; empty uses an automatic name)</span></span><input className="field" value={ad.name || ''} placeholder="For example Skincare | Serum | Image 1" onChange={(e) => upd(i, 'name', e.target.value)} /></label>
              {a.adsets.length > 1 && (
                <div><span className="lf-label">Show this ad in</span>
                  <div className="row" style={{ gap: 14 }}>{a.adsets.map((s, j) => <label key={s.uid} className="chk" title={`${audLabel(o, s)} · ${placeLabel(o, s)}`}><input type="checkbox" checked={(ad.sets || all).includes(s.uid)} onChange={() => toggleSet(i, s.uid)} />Ad set {j + 1}<span className="muted">· {s.audience === 'custom' ? 'Custom' : audLabel(o, s).split(',')[0]}</span></label>)}</div></div>
              )}
              <Counter label="Main text" value={ad.primary_text} limit={125}><textarea className="field" value={ad.primary_text} onChange={(e) => upd(i, 'primary_text', e.target.value)} /></Counter>
              <div className="fgrid">
                <Counter label="Headline" value={ad.headline} limit={40}><input className="field" value={ad.headline} onChange={(e) => upd(i, 'headline', e.target.value)} /></Counter>
                <Field label="Button"><select className="field" value={ad.cta} onChange={(e) => upd(i, 'cta', e.target.value)}>{o.ctas.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}</select></Field>
              </div>
              <DestPick o={o} value={ad.destination} onChange={(v) => upd(i, 'destination', v)} />
            </div>
          </div>
        ))}
      </div>
      {!noPreview && <div className="sticky">
        <div className="mini" style={{ marginBottom: 6 }}>How it will look</div>
        {a.ads.length === 0 ? <FeedPreview ad={{ ...d }} /> : a.ads.slice(0, 3).map((ad, i) => <FeedPreview key={i} ad={ad} />)}
        {a.ads.length > 3 && <div className="mini">+ {a.ads.length - 3} more</div>}
      </div>}
    </div>
  )
}

export function DestPick({ o, value, onChange }) {
  const known = o.destinations.some((x) => x.url === value)
  const [other, setOther] = useState(!known && !!value)
  return (
    <div className="stack">
      <Field label="Web page people land on">
        <select className="field" value={other ? '__other' : value} onChange={(e) => { if (e.target.value === '__other') setOther(true); else { setOther(false); onChange(e.target.value) } }}>
          {o.destinations.map((x) => <option key={x.url} value={x.url}>{x.label}</option>)}
          <option value="__other">Another link…</option>
        </select>
      </Field>
      {other && <input className="field" value={value} onChange={(e) => onChange(e.target.value)} placeholder="https://roopsee.com/…" />}
    </div>
  )
}

export function Progress({ job, phase, prod, ctx, retry, back, again, err }) {
  const r = job?.result
  const ok = job?.status === 'done' && job.ok
  return (
    <>
      {err && <Banner tone="err">{err}</Banner>}
      <Card title={phase === 'running' ? 'Creating your campaign…' : ok ? 'Done' : 'It did not finish'}>
        {ok && r && (
          <div className="big-ok" style={{ marginBottom: 12 }}>
            <div className="tick"><Icon name="check" size={24} /></div>
            <div><b style={{ fontSize: 16 }}>Your campaign is created and paused.</b><div className="muted">Nothing is running and nothing is being spent.</div></div>
          </div>
        )}
        <JobPanel job={job} />
        {phase === 'done' && !ok && (
          <div className="row" style={{ marginTop: 10 }}>
            <button type="button" className="btn primary" onClick={retry}>Try again</button>
            <button type="button" className="btn" onClick={back}>Go back and change something</button>
            <span className="muted">Trying again skips what already worked.</span>
          </div>
        )}
      </Card>
      {ok && r && (
        <Card title="What was created" sub={prod ? 'On your real ad account' : 'In the sandbox (not visible in Ads Manager)'}>
          <dl className="summary">
            <dt>Campaign</dt><dd>{r.campaign.name}<br /><span className="mono muted">{r.campaign.id}</span></dd>
            <dt>Ad sets</dt><dd>{r.adsets.map((x) => <div key={x.name}>{x.name} <span className="mono muted">{x.id}</span></div>)}</dd>
            <dt>Ads</dt><dd>{r.ads.map((x) => <div key={x.key}>{x.key} <Badge>{(x.status || 'paused').toLowerCase()}</Badge> <span className="mono muted">{x.id}</span></div>)}</dd>
          </dl>
          <div className="row" style={{ marginTop: 14 }}>
            {r.ads_manager_url && <a className="btn primary" href={r.ads_manager_url} target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>Open in Ads Manager <Icon name="external" size={14} /></a>}
            <button type="button" className="btn" onClick={() => ctx.go('overview')}>See it on the Overview</button>
            <button type="button" className="btn" onClick={() => ctx.go('run', { batch: r.batch })}>Turn it on…</button>
            <button type="button" className="btn" onClick={again}>Create another</button>
          </div>
          {r.ads_manager_url && <div className="mini" style={{ marginTop: 8 }}>If the Ads Manager link does not open the campaign, search for its name there.</div>}
        </Card>
      )}
    </>
  )
}
