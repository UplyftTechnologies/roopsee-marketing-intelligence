import { Banner } from '../ui'

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

/** Advanced options of one ad: Meta's enhancements (on / off / Meta's default) and a note about messaging. `extra` is the ad's Meta-named extra settings. */
export default function AdvancedAd({ extra, onChange }) {
  const setFeat = (k, v) => {
    const spec = { ...(extra?.degrees_of_freedom_spec?.creative_features_spec || {}) }
    if (v) spec[k] = { enroll_status: v }
    else delete spec[k]
    const next = { ...(extra || {}) }
    if (Object.keys(spec).length) next.degrees_of_freedom_spec = { ...(next.degrees_of_freedom_spec || {}), creative_features_spec: spec }
    else delete next.degrees_of_freedom_spec
    onChange(next)
  }
  const chosen = FEATURES.filter(([k]) => get(extra, k)).length
  return (
    <details className="more adv">
      <summary>Advanced options{chosen ? ` · ${chosen} set` : ''}</summary>
      <div className="tabpane" style={{ marginTop: 10 }}>
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
