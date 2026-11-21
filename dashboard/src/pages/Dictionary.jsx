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
  ['Roop chats', [
    ['Roop', 'The skin-care assistant on roopsee.com and in the app. Every question a shopper sends is a message; the messages of one chat window are a conversation (“New chat” starts another).'],
    ['Shopper', 'A logged-in account, or an anonymous guest (a guest session). A conversation with no identity counts as one shopper.'],
    ['Topic', 'Every question is sorted into the first topic whose words it contains (offers, delivery, routine, alternatives, does it suit me, ingredients, how to use, benefits, price, skin concerns), else Other.'],
    ['No answer', 'A message that failed, for example when the AI service was busy or the key was rejected. The reason is shown with it.'],
    ['Couldn’t answer', 'A reply where Roop says it cannot help (“we don’t stock it”, “not sure”): a gap in the shop or in Roop’s information.'],
    ['Visit of a chat', 'The visit a message was sent in, found from the answer event the site records, else from the guest id, else from the logged-in person’s visit running at that time. A few messages cannot be tied to a visit.'],
    ['Estimated AI cost', 'From the token counts saved with each answer at about ₹88 to the dollar, for the models we know the price of. An estimate, not your bill.'],
    ['Hidden traffic', 'A conversation with any message from hidden internal traffic is left out whole, unless “All traffic shown” is on.'],
  ]],
  ['Logins', [
    ['Login', 'A visit in which someone logged in, by phone OTP or Google. The several events of one login (OTP verified, login successful, existing user login) count once, so one visit with a login is one login.'],
    ['People who logged in', 'Distinct people with at least one login in the dates. One person can log in on several visits.'],
    ['New account', 'The login happened within an hour of the account being created: a sign-up. Every other login is returning.'],
    ['How they logged in', 'Google when the login says so, Phone OTP when an OTP was verified, otherwise “Not recorded”.'],
  ]],
  ['Pain points tab', [
    ['Pain point', 'Something that went wrong for a shopper on the way to buying: an OTP that failed, an address form with errors, an address we do not deliver to, a failed or cancelled payment, a slow page, a broken request. The tracker already sends each of these as an event.'],
    ['Stage', 'Log in, Address, Place order, Payment, and Speed & errors (slow or broken pages anywhere on the site).'],
    ['Tried / Got stuck', 'A visit tried a stage when it did something there or hit a problem there. It got stuck when it never got through, or its last word there was a problem. Placing an order settles every stage.'],
    ['Signs of struggle', 'Asking for the OTP again or closing a form. They explain why a visit got stuck but do not make it stuck on their own.'],
    ['Left with a problem unsolved', 'A visit with no order that ended while a problem at a stage it got stuck in was still standing.'],
    ['Sales lost', 'The biggest cart of people stuck at a stage (login to payment) who did not buy in any later visit in the dates. Speed & errors is not added, so no cart is counted twice.'],
    ['Spike', 'An hour when one problem hit at least 5 visits and 4 times its usual hourly number. Often an outage.'],
    ['Differences from roopsee.com admin', 'Repeated events within 2 seconds are ignored, people are matched with this dashboard’s own identity rules, and a page is shown by its path. Numbers can differ a little from the admin tab.'],
  ]],
  ['Events tab', [
    ['Event catalogue', 'One row per event name: how many times it fired, in how many sessions, by how many people, and its trend by day. Repeated events and hidden internal traffic are left out unless switched on.'],
    ['Event rows', 'One row per tracked event, newest first. Click a row to see everything it carries (its payload) and to jump to its session, person or order.'],
    ['Payload field', 'An extra detail the tracker sends with an event, for example quiz_option, search_term or pincode. Filters match it ignoring capitals; “contains” matches part of the value; “has a value” means the field is present.'],
    ['Slice the data', 'Counts the filtered events by a payload field or a dimension such as day, page, city or channel. Clicking a value (for a payload field, event name, group or channel) adds it as a filter.'],
    ['Data as of the last refresh', 'Events come from the local copy of the tracking table, so they are as fresh as the last Refresh. Payload fields the dashboard treats as plumbing (device, ip, user agent...) are not stored.'],
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
