import { useFilters, usePersisted } from '../api'
import { Chips } from '../ui'
import Journeys from './deeper/Journeys'
import Discovery from './deeper/Discovery'
import QuizPay from './deeper/QuizPay'
import Flow from './deeper/Flow'
import Chain from './deeper/Chain'
import Segments from './deeper/Segments'

const TABS = [
  { value: 'journeys', label: 'Pre-order journeys' },
  { value: 'discovery', label: 'Product discovery' },
  { value: 'quiz', label: 'Quiz & payment' },
  { value: 'flow', label: 'Ad → concern → products' },
  { value: 'chain', label: 'Journey builder' },
  { value: 'segments', label: 'Segments' },
]

/** Deeper analysis: postmortems that go below the headline numbers. */
export default function Deeper() {
  const f = useFilters()
  const [tab, setTab] = usePersisted('deeper.tab', 'journeys')
  const [steps, setSteps] = usePersisted('deeper.steps', [])
  const [unit, setUnit] = usePersisted('deeper.unit', 'key')
  const [mode, setMode] = usePersisted('deeper.mode', 'eventually')
  const [onlyOrdered, setOnlyOrdered] = usePersisted('deeper.ordered', false)
  const [label, setLabel] = usePersisted('deeper.label', '')
  // a path clicked on Pre-order journeys opens the builder on it
  const build = (keys) => { setUnit('key'); setMode('next'); setSteps(keys); setTab('chain'); window.scrollTo(0, 0) }
  void f
  return (
    <>
      <div className="chip-row" role="tablist" aria-label="Deeper analysis">
        <Chips value={tab} onChange={setTab} options={TABS} />
      </div>
      {tab === 'journeys' && <Journeys onChain={build} />}
      {tab === 'discovery' && <Discovery />}
      {tab === 'quiz' && <QuizPay />}
      {tab === 'flow' && <Flow />}
      {tab === 'chain' && <Chain steps={steps} setSteps={setSteps} unit={unit} setUnit={setUnit} mode={mode} setMode={setMode} onlyOrdered={onlyOrdered} setOnlyOrdered={setOnlyOrdered} />}
      {tab === 'segments' && <Segments label={label} setLabel={setLabel} />}
    </>
  )
}
