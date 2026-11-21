import { usePersisted } from '../api'
import { Chips } from '../ui'
import Ads from './deeper/Ads'
import Flow from './deeper/Flow'

const TABS = [
  { value: 'ads', label: 'Ad & landing-page cards' },
  { value: 'flow', label: 'Ad → concern → products' },
]

/** Ads & landing pages (was "Deeper analysis"): what the visits each ad and landing product brought did, and ad -> skin concern -> products.
 *  Search, quiz, payment timing and the first-order lead-up are under Journeys › More detail; the journey builder is Journeys › My presets;
 *  segments are on Audiences. */
export default function Deeper() {
  const [tab, setTab] = usePersisted('deeper.tab2', 'ads')
  return (
    <>
      <div className="chip-row" role="tablist" aria-label="Ads and landing pages">
        <Chips value={tab} onChange={setTab} options={TABS} />
      </div>
      {tab === 'flow' ? <Flow /> : <Ads />}
    </>
  )
}
