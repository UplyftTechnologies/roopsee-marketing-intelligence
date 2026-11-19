import { useState } from 'react'
import { api } from '../api'
import { Banner, Field } from '../ui'

// Meta's automatic creative enhancements (checked with Meta: each can be switched on or off).
const FEATURES = [
  ['image_brightness_and_contrast', 'Brighten and sharpen images', 'Meta adjusts brightness and contrast.'],
  ['image_touchups', 'Image touch-ups', 'Small automatic fixes to the picture.'],
  ['image_uncrop', 'Extend images to fit', 'Meta fills extra space when a placement needs a different shape.'],
  ['adapt_to_placement', 'Adapt to each placement', 'Resizes and recrops for stories, reels and feed.'],
  ['text_optimizations', 'Improve the text', 'Meta may reorder or rewrite your text for better results.'],
  ['text_translation', 'Translate the text', 'Shows translated text to people who use another language.'],
  ['enhance_cta', 'Improve the button', 'Meta may pick a more fitting button.'],
  ['inline_comment', 'Show a top comment', 'Highlights a relevant comment under the ad.'],
]
const get = (extra, k) => extra?.degrees_of_freedom_spec?.creative_features_spec?.[k]?.enroll_status || ''

const TOKENS = [['{{campaign.id}}', 'Campaign ID'], ['{{campaign.name}}', 'Campaign name'], ['{{adset.id}}', 'Ad set ID'], ['{{adset.name}}', 'Ad set name'], ['{{ad.id}}', 'Ad ID'], ['{{ad.name}}', 'Ad name'], ['{{placement}}', 'Placement'], ['{{site_source_name}}', 'Site (fb, ig …)']]
const STANDARD = 'utm_source=facebook&utm_medium=paid_social&utm_campaign={{campaign.id}}&utm_content={{ad.id}}&utm_term={{adset.id}}'
const parseTags = (str) => String(str || '').split('&').filter(Boolean).map((p) => { const i = p.indexOf('='); return i < 0 ? { k: p, v: '' } : { k: p.slice(0, i), v: p.slice(i + 1) } })
const joinTags = (rows) => rows.filter((r) => r.k.trim()).map((r) => `${r.k.trim()}=${r.v}`).join('&')

/** The tracking tags added to the ad's link, as rows (name = value) with Meta's dynamic tokens to pick from. */
function UrlTagsBuilder({ value, onChange }) {
  const [rows, setRows] = useState(() => parseTags(value))
  const commit = (r) => { setRows(r); onChange(joinTags(r)) }
  const upd = (i, p) => commit(rows.map((x, j) => (j === i ? { ...x, ...p } : x)))
  return (
    <div className="stack">
      <span className="lf-label">Link tracking tags <span className="muted">{value ? '(this ad only)' : '(empty: the standard tags from Links & tracking are used)'}</span></span>
      {rows.map((r, i) => (
        <div key={i} className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
          <input className="field" style={{ width: 140 }} value={r.k} placeholder="utm_source" aria-label="Tag name" onChange={(e) => upd(i, { k: e.target.value })} />
          <span className="muted">=</span>
          <input className="field" style={{ flex: 1, minWidth: 160 }} value={r.v} placeholder="facebook" aria-label="Tag value" onChange={(e) => upd(i, { v: e.target.value })} />
          <select className="field" style={{ width: 150 }} value="" aria-label="Insert a token" onChange={(e) => e.target.value && upd(i, { v: r.v + e.target.value })}>
            <option value="">+ token</option>{TOKENS.map(([t, l]) => <option key={t} value={t}>{l}</option>)}
          </select>
          <button type="button" className="btn small danger" onClick={() => commit(rows.filter((_, j) => j !== i))}>×</button>
        </div>
      ))}
      <div className="row">
        <button type="button" className="btn small" onClick={() => commit([...rows, { k: '', v: '' }])}>Add a tag</button>
        <button type="button" className="btn small" onClick={() => commit(parseTags(STANDARD))}>Fill in standard tags</button>
        {rows.length > 0 && <button type="button" className="btn small" onClick={() => commit([])}>Use the default tags</button>}
      </div>
      {value && <div className="mini mono" style={{ wordBreak: 'break-all' }}>{value}</div>}
    </div>
  )
}

/** Advanced options of one ad. `ad` is the ad card's data and `set(patch)` changes it. */
export default function AdvancedAd({ ad, set, o, isImage }) {
  const extra = ad.extra
  const [igs, setIgs] = useState(null)
  const [err, setErr] = useState(null)
  const setExtra = (next) => set({ extra: next })
  const setFeat = (k, v) => {
    const spec = { ...(extra?.degrees_of_freedom_spec?.creative_features_spec || {}) }
    if (v) spec[k] = { enroll_status: v }
    else delete spec[k]
    const next = { ...(extra || {}) }
    if (Object.keys(spec).length) next.degrees_of_freedom_spec = { ...(next.degrees_of_freedom_spec || {}), creative_features_spec: spec }
    else delete next.degrees_of_freedom_spec
    setExtra(next)
  }
  const multiOut = extra?.contextual_multi_ads?.enroll_status === 'OPT_OUT'
  const setMulti = (out) => { const next = { ...(extra || {}) }; if (out) next.contextual_multi_ads = { enroll_status: 'OPT_OUT' }; else delete next.contextual_multi_ads; setExtra(next) }
  const loadIgs = async () => { setErr(null); try { setIgs((await api('/api/meta/instagram-accounts')).accounts) } catch (e) { setErr(e.message) } }
  const caption = ad.link_extra?.caption || ''
  const setCaption = (v) => { const le = { ...(ad.link_extra || {}) }; if (v) le.caption = v; else delete le.caption; set({ link_extra: le }) }
  const chosen = FEATURES.filter(([k]) => get(extra, k)).length + (ad.instagram_id ? 1 : 0) + (multiOut ? 1 : 0) + (ad.labels ? 1 : 0) + (ad.url_tags ? 1 : 0) + (caption ? 1 : 0)
  return (
    <details className="more adv">
      <summary>Advanced options{chosen ? ` · ${chosen} set` : ''}</summary>
      <div className="tabpane" style={{ marginTop: 10 }}>
        <div className="fgrid">
          <Field label="Instagram account for this ad" hint="Leave on the default to use the one in .env">
            {igs ? (
              <select className="field" value={ad.instagram_id || ''} onChange={(e) => set({ instagram_id: e.target.value })}>
                <option value="">Default account</option>{igs.map((a) => <option key={a.id} value={a.id}>@{a.username} · {a.id}</option>)}
              </select>
            ) : <div><button type="button" className="btn small" onClick={loadIgs}>{ad.instagram_id ? `Account ${ad.instagram_id}` : 'Choose an Instagram account'}</button></div>}
          </Field>
          <Field label="Labels (optional)" hint="Comma separated. Ads Manager can filter by them"><input className="field" value={ad.labels || ''} onChange={(e) => set({ labels: e.target.value })} /></Field>
          {isImage && <Field label="Display link (optional)" hint="Shown under the ad instead of the full web address, for example roopsee.com"><input className="field" value={caption} onChange={(e) => setCaption(e.target.value)} /></Field>}
        </div>
        {err && <Banner tone="err">{err}</Banner>}
        <UrlTagsBuilder value={ad.url_tags || ''} onChange={(v) => set({ url_tags: v })} />
        <label className="chk"><input type="checkbox" checked={!multiOut} onChange={(e) => setMulti(!e.target.checked)} /><span><b>Allow this ad to appear next to other advertisers' ads</b> <span className="muted">(Meta's multi-advertiser ads, on by default)</span></span></label>

        <div className="lf-label">Meta's automatic enhancements</div>
        <div className="mini">Leave on "Meta's default" unless you want to force one on or off for this ad.</div>
        <div className="adv-list">
          {FEATURES.map(([k, label, help]) => (
            <label key={k} className="adv-row">
              <span className="grow"><b>{label}</b><span className="muted"> {help}</span></span>
              <select className="field" value={get(extra, k)} onChange={(e) => setFeat(k, e.target.value)}>
                <option value="">Meta's default</option><option value="OPT_IN">On</option><option value="OPT_OUT">Off</option>
              </select>
            </label>
          ))}
        </div>
        <Banner>
          <b>Chat buttons (WhatsApp, Messenger)</b> are not available yet. They need messaging permission on your Meta app. When an imported ad has one, it is left out and you are told.
        </Banner>
      </div>
    </details>
  )
}
