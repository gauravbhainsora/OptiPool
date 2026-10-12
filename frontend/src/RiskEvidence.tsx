import type { Risk } from "./types";

const percent = (v: number | null | undefined) =>
  v == null ? "unknown" : `${(v * 100).toFixed(1)}%`;

export default function RiskEvidence({
  resource,
  risk,
}: {
  resource: string;
  risk?: Risk;
}) {
  return (
    <div className="form-hint">
      <strong>
        {resource} risk evidence: {risk?.status ?? "unknown"}
        {risk?.adverse ? " · adverse" : ""}
      </strong>
      <small>
        {risk?.source ?? "Unavailable"} · risk cadence{" "}
        {risk?.cadence_seconds ?? "unknown"} seconds
      </small>
      <small>
        Risk policy minimum:{" "}
        {risk?.minimum_observation_seconds == null
          ? "unknown"
          : `${risk.minimum_observation_seconds / 3600} hours`}{" "}
        / {percent(risk?.minimum_coverage)} selected-window coverage
      </small>
      <small>
        Required risk evidence:{" "}
        {risk?.required === false ? "no (configured opt-out)" : "yes"}
      </small>
      {resource === "CPU" ? (
        <>
          <small>
            Throttled periods: {risk?.numerator ?? "unknown"} / elapsed
            enforcement periods: {risk?.denominator ?? "unknown"}
          </small>
          <small>
            Count-weighted ratio: {percent(risk?.ratio)} · per-container risk
            threshold: {percent(risk?.threshold)}
          </small>
        </>
      ) : (
        <small>
          Historical OOM count: {risk?.oom_events ?? "unknown"} · historical
          restarts: {risk?.restarts ?? "unknown"}
        </small>
      )}
      <small>
        Risk represented duration:{" "}
        {risk?.represented_seconds == null
          ? "unknown"
          : `${(risk.represented_seconds / 3600).toFixed(2)} hours`}{" "}
        · selected-window coverage: {percent(risk?.selected_window_coverage)}
      </small>
      {(risk?.reasons ?? ["Required risk evidence unavailable"]).map(
        (reason) => (
          <small key={reason}>{reason}</small>
        ),
      )}
      {risk?.containers && (
        <details>
          <summary>Container risk evidence</summary>
          {risk.containers.map((c, i) => (
            <small key={`${c.replica ?? "pod"}/${c.container}/${i}`}>
              {c.replica ? `${c.replica} / ` : ""}
              {c.container}: {c.status}
              {c.adverse ? " · adverse" : ""} ·{" "}
              {resource === "CPU"
                ? `${c.numerator ?? "unknown"} / ${c.denominator ?? "unknown"} periods (${percent(c.ratio)})`
                : `OOM ${c.oom_events ?? "unknown"}, restarts ${c.restarts ?? "unknown"}`}{" "}
              · counter resets {c.counter_resets ?? "unknown"}
            </small>
          ))}
        </details>
      )}
      {(risk?.limitations ?? []).map((limit) => (
        <small key={limit}>{limit}</small>
      ))}
    </div>
  );
}
