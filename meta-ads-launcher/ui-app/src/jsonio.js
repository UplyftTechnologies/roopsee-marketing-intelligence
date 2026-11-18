// Ad set form values <-> the launcher's friendly JSON format (the importer on the server reads this back).
const RESULT_WORD = {
  LINK_CLICKS: 'link_clicks', LANDING_PAGE_VIEWS: 'landing_page_views', OFFSITE_CONVERSIONS: 'purchases', VALUE: 'value', REACH: 'reach', IMPRESSIONS: 'impressions',
  VIDEO_VIEWS: 'video_views', THRUPLAY: 'thruplay', POST_ENGAGEMENT: 'engagement', LEAD_GENERATION: 'leads', CONVERSATIONS: 'messages', APP_INSTALLS: 'installs',
  AD_RECALL_LIFT: 'recall', PAGE_LIKES: 'page_likes', PROFILE_VISIT: 'profile_visits', QUALITY_CALL: 'calls',
}
const num = (v) => (v === '' || v == null || Number.isNaN(Number(v)) ? undefined : Number(v))
const has = (o) => o && typeof o === 'object' && Object.keys(o).length > 0

export function exportOne(s, i = 0) {
  const out = { format: 'roopsee-adset', version: 1, name: s.label || `Ad set ${i + 1}` }
  if (s.goal) out.result = RESULT_WORD[s.goal] || s.goal
  if (s.audience === 'custom') {
    out.audience = {
      countries: String(s.custom?.countries || 'IN').split(',').map((x) => x.trim().toUpperCase()).filter(Boolean),
      age: [Number(s.custom?.age_min) || 18, Number(s.custom?.age_max) || 45], gender: s.custom?.gender || 'all',
    }
  } else out.audience = s.audience
  if (s.placements) out.placements = s.placements
  const budget = {}
  if (num(s.daily_budget) && !num(s.lifetime_budget)) budget.daily = num(s.daily_budget)
  if (num(s.lifetime_budget)) budget.lifetime = num(s.lifetime_budget)
  if (has(budget)) out.budget = budget
  const schedule = {}
  if (s.start_date) schedule.start = s.start_date
  if (s.end_date) schedule.end = s.end_date
  if (has(schedule)) out.schedule = schedule
  const bid = {}
  if (s.bid_strategy) bid.strategy = s.bid_strategy
  if (num(s.bid_amount)) bid.amount = num(s.bid_amount)
  if (has(bid)) out.bid = bid
  if (s.event) out.conversion = { event: s.event }
  if (s.destination_type) out.destination = s.destination_type
  if (s.billing_event) out.billing_event = s.billing_event
  if (has(s.targeting_extra)) out.targeting_extra = s.targeting_extra
  if (has(s.extra)) out.extra = s.extra
  return out
}

/** One ad set -> an object; several -> { adsets: [...] }. */
export function exportAdSets(sets) {
  if (sets.length === 1) return exportOne(sets[0], 0)
  return { format: 'roopsee-adset', version: 1, adsets: sets.map((s, i) => exportOne(s, i)) }
}

/** One ad -> the launcher's ad JSON. `ids` are the ad set uids, used to turn the ad's chosen ad sets into positions. */
export function exportAd(ad, ids) {
  const sets = (ad.sets || ids).map((u) => ids.indexOf(u)).filter((i) => i >= 0)
  if (ad.kind) { const { sets: _s, ...rest } = ad; return { format: 'roopsee-ad', version: 1, ...rest, sets } }
  if (ad.creative_spec) return { format: 'roopsee-ad', version: 1, ad_key: ad.ad_key, name: ad.label || undefined, creative_spec: ad.creative_spec, sets }
  const { ad_key, image_hash, image, primary_text, headline, description, cta, destination, extra, link_extra } = ad
  return { ad_key, image_hash, image, primary_text, headline, description, cta, destination, extra: has(extra) ? extra : undefined, link_extra: has(link_extra) ? link_extra : undefined, sets }
}

/** The whole builder -> one JSON file that the campaign import reads back (amounts in rupees). */
export function exportCampaign(a) {
  const ids = a.adsets.map((s) => s.uid)
  const c = a.campaign || {}
  return {
    format: 'roopsee-campaign', version: 1,
    campaign: {
      goal: a.goal, budget_mode: a.budget_mode, daily_budget: num(a.daily_budget), start_date: a.start_date || undefined, end_date: a.end_date || undefined,
      spend_cap: num(c.spend_cap), bid_strategy: c.bid_strategy || undefined, special_ad_categories: c.special_ad_categories?.length ? c.special_ad_categories : undefined, extra: has(c.extra) ? c.extra : undefined,
    },
    adsets: a.adsets.map((s, i) => exportOne(s, i)),
    ads: a.ads.map((ad) => exportAd(ad, ids)),
  }
}

export function downloadJson(obj, filename) {
  const blob = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = filename
  document.body.appendChild(a)
  a.click()
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove() }, 500)
}
