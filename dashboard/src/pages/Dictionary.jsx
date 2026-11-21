import { useState } from 'react'
import { Card, Search } from '../ui'

// One place that says exactly how every number in the dashboard is worked out. Keep this in step with mi/transform.py and mi/api.py.
const SECTIONS = [
  ['Visits and people', [
    ['Session (visit)', 'All events that share one session id from the website or app. A session id can stay alive for weeks, so time spent is counted only from gaps of 30 minutes or less between events.'],
    ['Time spent (active time)', 'The sum of the gaps between consecutive events in a session, ignoring any gap longer than 30 minutes. A session with one event has 0 seconds.'],
    ['Repeated events', 'The tracker often fires the same action several times in a row. Repeats of the same action in the same session within 2 seconds (1 second for clicks and scrolls) are flagged and left out of event counts. Nothing is deleted.'],
    ['Bounce', 'A session with at most one page view and no interaction (no click, search, cart action and so on).'],
    ['Person', 'A logged-in account, or an anonymous browser that never logged in. When a browser later logs in, its earlier visits are credited to that account. On a browser shared by several accounts, the most used (then most recent) account wins.'],
    ['Known user vs logged in this session', '“Known user” means the session belongs to an account, even if the login happened in another visit. “Logged in this session” means a login event happened during this visit.'],
  ]],
  ['Orders and revenue', [
    ['Sale (valid order)', 'An order whose status is not “payment cancelled” or “payment pending”, and that is not a test (total of ₹1 or less, or a test product). Sales are counted by the date the order was placed.'],
    ['Revenue and order value', 'The order total of valid sales (what the customer pays, including delivery fees, after discounts).'],
    ['Average order value', 'Revenue divided by the number of valid orders.'],
    ['Payment state', 'Confirmed: paid or cash collected. COD pending: cash on delivery, not collected yet (normal). Unconfirmed: counted as a sale but no payment is confirmed. Conflicting: the order moved on but the payment shows cancelled. Unconfirmed and conflicting sales are flagged as “at risk”.'],
    ['Repeat customer', 'A customer who ordered on at least two different days. Several orders on one day do not count.'],
    ['Internal and test orders', 'Orders from staff accounts, manually excluded customers and test orders are kept but hidden by default.'],
  ]],
  ['Where visits come from', [
    ['Channel', 'Worked out from the link the visitor arrived with. MyGate Partner: source is mygate. Paid Google: Google source with a click id or paid medium. Paid Meta: Instagram or Facebook with a click id or paid medium. Organic Social, Organic Search, Referral and Direct follow from the source and referrer.'],
    ['Direct (new) and Direct (returning)', 'Direct visits split by whether the same browser had visited before. A returning Direct visit is usually someone coming back, not a new source.'],
    ['Campaign', 'The campaign name from the link (utm_campaign, or the Google campaign id). “(not set)” means the link carried no campaign name.'],
    ['Same-session credit', 'An order is credited to the channel and campaign of the visit it was placed in.'],
    ['First-touch credit', 'An order is credited to the channel and campaign of the customer’s first ever visit.'],
    ['Last-campaign credit (7 days)', 'If an order was placed in a Direct visit, it is credited to the customer’s last non-Direct visit in the 7 days before the order. Otherwise it keeps its own channel.'],
  ]],
  ['Funnel and filters', [
    ['Funnel stages', 'Sessions → viewed a product → added to cart → reached checkout → started payment → placed an order. Each stage counts sessions that reached it.'],
    ['Ordered (Sessions filter)', 'A session that placed a real order (not payment cancelled or pending), or that fired an order-placed event.'],
    ['Cart / checkout abandoner', 'A session that added to cart (or reached checkout) but placed no order.'],
    ['Saved an address', 'A session with a save event (address saved, save clicked, address updated) that carries a valid 6-digit pincode.'],
    ['Chose pincode / location', 'A session where the visitor typed or picked a pincode or place (including checking delivery, using current location or choosing a saved address), whether or not they saved it.'],
    ['Had event', 'A session that contains the named event at least once (part of a name is enough).'],
    ['Did / Did not / Any', 'Did: the session did it. Did not: it did not. Any: ignore it. Several Did choices can be combined as All or Any.'],
  ]],
  ['Place', [
    ['City and state (visitor)', 'Looked up from the visitor’s IP address. Mobile networks and VPNs can put someone in the wrong city.'],
    ['Delivery pincode, city and state', 'Where the person wants delivery: their saved address first, then their latest order, then the last pincode they typed. The place for a pincode is learned from saved addresses and orders.'],
  ]],
  ['Data and trust', [
    ['Hidden (excluded) traffic', 'Staff, test, development, bot and non-India traffic, and anything you add on the Exclusions page. It is flagged, never deleted, and can be shown again from the “Internal traffic” menu.'],
    ['Dates and time zone', 'All dates and times are Indian Standard Time (IST).'],
    ['Tracking upgrade (14 Oct)', 'Tracking changed on 14 October, so session counts, bounce rate and time spent before that date are not comparable with later dates.'],
    ['Data as of', 'The time of the newest event pulled from Supabase. Press Refresh to pull newer events and rebuild all tables.'],
    ['Orders not in a table', 'Tables credit orders to visits. An order whose visit started before the chosen period, or that predates tracking (tracking began 1 June 2026), has no row there; the table says how many.'],
  ]],
]

export default function Dictionary() {
  const [q, setQ] = useState('')
  const needle = q.trim().toLowerCase()
  const shown = SECTIONS.map(([title, rows]) => [title, rows.filter(([t, d]) => !needle || `${t} ${d}`.toLowerCase().includes(needle))]).filter(([, rows]) => rows.length)
  return (
    <>
      <div className="chip-row"><Search value={q} onChange={setQ} placeholder="Find a term, for example sale, bounce, direct…" /></div>
      {shown.length === 0 && <div className="empty">Nothing matches “{q}”.</div>}
      {shown.map(([title, rows]) => (
        <Card key={title} title={title}>
          <dl className="facts dict">
            {rows.map(([t, d]) => (<div key={t} className="dict-row"><dt>{t}</dt><dd>{d}</dd></div>))}
          </dl>
        </Card>
      ))}
    </>
  )
}
