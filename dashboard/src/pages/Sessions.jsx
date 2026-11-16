import { useEffect, useState } from 'react'
import { KEY_LABEL, dt, dur, num, useApi, useFilters } from '../api'
import { Badge, Card, Chips, ExportBtn, Loading, Pager, Search, Table } from '../ui'
import { STAGE, STAGE_TONE } from '../shared'

export default function Sessions() {
  const f = useFilters()
  const pre = f.prefill || {}
  const [search, setSearch] = useState(pre.search || '')
  const [channel, setChannel] = useState(pre.channel || 'All')
  const [stage, setStage] = useState(0)
  const [only, setOnly] = useState('counted')
  const [offset, setOffset] = useState(0)
  const limit = 50
  const s = useApi('/sessions', { search, channel: channel === 'All' ? undefined : channel, min_stage: stage || undefined, only_excluded: only === 'excluded' || undefined, limit, offset })
  useEffect(() => setOffset(0), [search, stage, only, channel])
  return (
    <>
      <div className="chip-row">
        <Search value={search} onChange={setSearch} placeholder="Search session id, IP, phone, name, city, campaign…" />
        <Chips value={stage} onChange={setStage} options={[{ value: 0, label: 'All sessions' }, { value: 2, label: 'Added to cart+' }, { value: 3, label: 'Reached checkout+' }, { value: 5, label: 'Ordered' }]} />
        <Chips value={only} onChange={setOnly} options={[{ value: 'counted', label: 'Normal view' }, { value: 'excluded', label: 'Only hidden (excluded)' }]} />
      </div>
      <Chips value={channel} onChange={setChannel} options={['All', 'Paid Google', 'Paid Meta', 'MyGate Partner', 'Organic Search', 'Organic Social', 'Direct', 'Referral']} />
      <Loading state={s}>
        {({ rows, total }) => (
          <Card title={`${num(total)} sessions`} sub="click a row for the full session: every step, device, source and the person behind it"
            right={<ExportBtn name="sessions" rows={rows} fields={[['Started', 'started_at'], ['Name', 'name'], ['Phone', 'phone10'], ['Journey', 'key_events'], ['Channel', 'channel'], ['Campaign', 'campaign'], ['City', 'city'], ['Device', 'device'], ['Events', 'events'], ['Seconds', 'duration_s'], ['IP', 'ip'], ['Session id', 'session_id']]} />}>
            <Table onRow={(r) => f.go('session', { key: r.session_id })} rowClass={(r) => (r.is_excluded ? 'excluded' : '')} cols={[
              { label: 'Started', render: (r) => dt(r.started_at) },
              { label: 'Who', render: (r) => r.name || (r.phone10 ? <span className="mono">{r.phone10}</span> : <span className="muted">anonymous</span>) },
              { label: 'Journey', render: (r) => <span title={r.key_events}>{r.key_events ? r.key_events.split(' > ').map((k) => KEY_LABEL[k] || k).join(' → ') : <span className="muted">{r.events} event{r.events === 1 ? '' : 's'}, no key action</span>}</span> },
              { label: 'Stage', render: (r) => <Badge tone={STAGE_TONE[r.stage]}>{STAGE[r.stage]}</Badge> },
              { label: 'Channel', render: (r) => <span title={`${r.source} / ${r.medium} / ${r.campaign}`}>{r.channel}</span> },
              { label: 'Place', render: (r) => r.city || r.region || '–' },
              { label: 'Device', render: (r) => (r.is_app ? 'App' : r.device || '–') },
              { label: 'Events', num: true, render: (r) => r.events }, { label: 'Time', num: true, render: (r) => dur(r.duration_s) },
              { label: '', render: (r) => (r.is_excluded ? <Badge tone="bad">excluded</Badge> : null) },
            ]} rows={rows} />
            <Pager total={total} limit={limit} offset={offset} setOffset={setOffset} />
          </Card>
        )}
      </Loading>
    </>
  )
}
