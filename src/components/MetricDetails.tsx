import { formatMetric, type Metrics } from "../model";
import { metricPathLabel } from "../metrics";

export function MetricDetails({ metrics }: { metrics: Metrics }) {
  return (
    <dl className="metric-details">
      {Object.entries(metrics).map(([key, value]) => (
        <div key={key}>
          <dt>{metricPathLabel([key])}</dt>
          <dd>
            {value !== null && typeof value === "object" ? (
              <pre>{JSON.stringify(value, null, 2)}</pre>
            ) : (
              <strong>{formatMetric(value)}</strong>
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}
