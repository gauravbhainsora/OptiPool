import { BudgetBar, cores, gib, date, Notice } from "./components";
import type { Estimate } from "./types";

export default function PlacementView({ result }: { result: Estimate }) {
  const nodes = result.node_budgets ?? [];
  return (
    <section className="panel analytical-panel">
      <div className="panel-heading">
        <div>
          <h2>Placement and node budgets</h2>
          <p>Saved baseline → simulated peak. Existing Pods remain fixed.</p>
        </div>
        <span className="pill neutral">
          {result.confidence?.status ?? "Saved estimate"}
        </span>
      </div>
      <p className="form-hint">
        Snapshot {date(result.snapshot_at)} · assignments illustrate one
        feasible candidate; they do not predict scheduler scoring.
      </p>
      {result.confidence?.stale && (
        <Notice>
          This snapshot is over 24 hours old. Fetch fresh observations
          explicitly before relying on the assessment.
        </Notice>
      )}
      <div className="zone-distribution">
        {Object.entries(result.zone_distribution ?? {}).map(([zone, count]) => (
          <span className="service-tag" key={zone}>
            {zone}: {count} proposed Pods
          </span>
        ))}
      </div>
      <div className="placement-grid">
        {nodes.map((n) => (
          <article className="node-plan" key={n.name}>
            <div className="node-plan-title">
              <strong className="mono">{n.name}</strong>
              <span className="pill neutral">
                {n.planned ? "Planned node" : "Existing node"}
              </span>
            </div>
            <p className="muted">{n.zone}</p>
            <div className="before-after">
              <div>
                <h4>Before</h4>
                <span>{cores(n.before.cpu)}</span>
                <small>{gib(n.before.memory)}</small>
              </div>
              <div>
                <h4>After</h4>
                <BudgetBar
                  requested={n.after.cpu}
                  allocatable={n.allocatable.cpu}
                  cap={n.ceiling.cpu / n.allocatable.cpu}
                  unit="cores"
                />
                <BudgetBar
                  requested={n.after.memory}
                  allocatable={n.allocatable.memory}
                  cap={n.ceiling.memory / n.allocatable.memory}
                  unit="GiB"
                />
              </div>
            </div>
            <p>
              Remaining: {cores(n.remaining.cpu)} · {gib(n.remaining.memory)}
            </p>
            <div className="assigned-pods">
              {n.placements.map((p) => (
                <span className="service-tag" key={p}>
                  {p}
                </span>
              ))}
              {!n.placements.length && (
                <span className="muted">No proposed placements</span>
              )}
            </div>
            <details>
              <summary>Can another proposed Pod fit?</summary>
              {n.rejections.length ? (
                <ul>
                  {n.rejections.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              ) : (
                <p>No modeled constraint currently rejects another replica.</p>
              )}
            </details>
          </article>
        ))}
      </div>
      {!nodes.length && (
        <p className="muted">
          No node-level placement was produced for this assessment.
        </p>
      )}
    </section>
  );
}
