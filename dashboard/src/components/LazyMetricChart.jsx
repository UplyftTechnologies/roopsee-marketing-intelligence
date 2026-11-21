import { Suspense, lazy } from 'react'

const MetricChart = lazy(() => import('./MetricChart'))

/** MetricChart loads the chart library (the biggest file in the app) only when a chart is actually shown. */
export default function LazyMetricChart(props) {
  return (
    <Suspense fallback={<div className="skeleton" style={{ height: props.height || 280 }} />}>
      <MetricChart {...props} />
    </Suspense>
  )
}
