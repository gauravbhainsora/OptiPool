import type { ResourceEvidence } from "./types";

const percent = (v: number | null | undefined) =>
  v == null ? "unknown" : `${(v * 100).toFixed(1)}%`;

export default function MetricEvidence({
  resource,
  evidence,
}: {
  resource: string;
  evidence?: ResourceEvidence;
}) {
  return (
    <div className="form-hint">
      <strong>
        {resource}:{" "}
        {evidence?.eligible ? "Evidence policy met" : "Insufficient evidence"}
      </strong>
      {evidence?.partial && (
        <small>
          Observed maximum is partial: missing or excluded replicas.
        </small>
      )}
      <small>
        Valid samples: {evidence?.valid_samples ?? 0} / expected{" "}
        {evidence?.expected_samples ?? "unknown"}
      </small>
      <small>
        Represented duration:{" "}
        {evidence?.represented_seconds == null
          ? "unknown"
          : `${(evidence.represented_seconds / 3600).toFixed(2)} hours`}
      </small>
      <small>
        Pod-lifetime coverage: {percent(evidence?.lifetime_coverage)} ·
        Selected-window coverage: {percent(evidence?.selected_window_coverage)}
      </small>
      <small>Replica: {evidence?.replica ?? "Unavailable"}</small>
      <small>
        {evidence?.source ?? "Unavailable"} · cadence{" "}
        {evidence?.cadence_seconds ?? "unknown"} seconds
      </small>
      {resource === "CPU" && (
        <small>
          CPU averaging window: {evidence?.cpu_rate_window_seconds ?? "unknown"}{" "}
          seconds · {evidence?.definition_basis ?? "Unknown definition"}
        </small>
      )}
      {(evidence?.reasons ?? []).map((reason) => (
        <small key={reason}>{reason}</small>
      ))}
    </div>
  );
}
