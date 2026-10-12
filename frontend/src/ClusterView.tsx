import { BudgetBar, cores, date, gib, Notice } from "./components";
import ClusterExportButtons from "./ClusterExportButtons";
import PodTable from "./PodTable";
import MetricEvidence from "./MetricEvidence";
import type { ClusterSnapshot } from "./types";

export default function ClusterView({
  scope,
  tab,
  days,
  setDays,
}: {
  scope: ClusterSnapshot;
  tab: "nodes" | "workloads";
  days: number;
  setDays: (n: number) => void;
}) {
  return (
    <>
      <div className="section-heading">
        <div>
          <h2>
            {tab === "nodes" ? "Nodes" : "Workloads"} across all node pools
          </h2>
          <p>
            {scope.project} · {scope.cluster} · {scope.location} ·{" "}
            {scope.sources.length} saved pools
          </p>
        </div>
        {tab === "workloads" && (
          <ClusterExportButtons scope={scope} table="workloads" />
        )}
      </div>
      <p className="help-note">
        Each pool keeps its own snapshot time and metrics cutoff. Combined
        values describe saved observations collected at different times.
      </p>
      {scope.missing.map((p) => (
        <Notice key={p.pool_id}>
          {p.pool_name}: {p.reason}. Select that pool for an explicit live
          refresh.
        </Notice>
      ))}
      <details className="panel analytical-panel">
        <summary>Pool snapshots and metric coverage</summary>
        {scope.sources.map((s) => (
          <p key={s.pool_id}>
            <strong>{s.pool_name}</strong> · snapshot {date(s.saved_at)} ·
            metrics cutoff {date(s.cutoff)} · {s.source} · {s.memory_definition}{" "}
            · {s.coverage}
            <br />
            Query cadence:{" "}
            {s.cadence_seconds == null ? "Unknown" : `${s.cadence_seconds}s`} ·
            CPU rate window:{" "}
            {s.cpu_rate_window_seconds == null
              ? "Unknown"
              : `${s.cpu_rate_window_seconds}s`}
            <br />
            CPU observations: {s.resource_status?.cpu ?? "unknown"} · Memory
            observations: {s.resource_status?.memory ?? "unknown"}
            {s.historical_discovery && (
              <>
                <br />
                Historical discovery: {s.historical_discovery.status} ·{" "}
                {s.historical_discovery.replicas_discovered} replicas discovered
                <br />
                {s.historical_discovery.reasons.join("; ")}
              </>
            )}
            {s.fallback_reason && (
              <>
                <br />
                {s.fallback_reason}
              </>
            )}
          </p>
        ))}
      </details>
      {tab === "nodes" ? (
        <section className="panel cluster-nodes-panel">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Node / zone</th>
                  <th>Node pool</th>
                  <th>State</th>
                  <th>CPU requests</th>
                  <th>Memory requests</th>
                  <th>Remaining budget</th>
                  <th>Pod slots</th>
                  <th>Snapshot</th>
                </tr>
              </thead>
              <tbody>
                {scope.nodes.map((n) => {
                  const cap = n.environment === "production" ? 0.8 : 0.9;
                  return (
                    <tr key={`${n.pool_id}/${n.name}`}>
                      <td>
                        <strong className="mono">{n.name}</strong>
                        <small>{n.zone}</small>
                      </td>
                      <td>
                        {n.pool_name}
                        <small>{n.environment}</small>
                      </td>
                      <td>
                        {!n.ready
                          ? "Not ready"
                          : n.unschedulable
                            ? "Cordoned"
                            : "Ready"}
                      </td>
                      <td>
                        <BudgetBar
                          requested={n.requested.cpu}
                          allocatable={n.allocatable.cpu}
                          cap={cap}
                          unit="cores"
                        />
                      </td>
                      <td>
                        <BudgetBar
                          requested={n.requested.memory}
                          allocatable={n.allocatable.memory}
                          cap={cap}
                          unit="GiB"
                        />
                      </td>
                      <td>
                        {cores(n.allocatable.cpu * cap - n.requested.cpu)}
                        <small>
                          {gib(n.allocatable.memory * cap - n.requested.memory)}
                        </small>
                      </td>
                      <td>
                        {n.pod_count} / {n.allocatable.pods}
                      </td>
                      <td>{date(n.saved_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="panel-footer">
            {scope.nodes.length} nodes across saved pool snapshots
          </div>
        </section>
      ) : (
        <>
          <div className="window-controls">
            <strong>Usage lookback per pool</strong>
            <label htmlFor="cluster-window">{days} days</label>
            <input
              id="cluster-window"
              aria-label="Usage lookback days"
              type="range"
              min="1"
              max="10"
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
            />
            <span className="muted">Ends at each pool's saved cutoff</span>
          </div>
          <section className="panel cluster-workloads-panel">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Workload / namespace</th>
                    <th>Node pools / replicas</th>
                    <th>Combined requests</th>
                    <th>Highest-replica p99 CPU</th>
                    <th>Highest-replica p99 memory</th>
                    <th>Sampled memory peak</th>
                    <th>Services</th>
                  </tr>
                </thead>
                <tbody>
                  {scope.workloads.map((w) => (
                    <tr key={w.id}>
                      <td>
                        <strong>{w.name}</strong>
                        <small>
                          {w.kind} · {w.namespace}
                        </small>
                      </td>
                      <td>
                        <strong>{w.pool_replicas} across pools</strong>
                        {w.pools.map((p) => (
                          <small key={p.pool_id}>
                            {p.pool_name}: {p.replicas}
                          </small>
                        ))}
                      </td>
                      <td>
                        {cores(w.requested.cpu)}
                        <small>{gib(w.requested.memory)}</small>
                      </td>
                      <td>
                        {w.kind === "Deployment"
                          ? cores(w.cpu_p99)
                          : "Deployments only"}
                        {w.kind === "Deployment" ? (
                          <small>
                            {w.historical_replicas_observed ?? 0} historical
                            replicas observed
                          </small>
                        ) : null}
                        {w.kind !== "Deployment" ? (
                          <small>Workload type: {w.kind}</small>
                        ) : !w.cpu_complete ? (
                          <small>Partial or missing coverage</small>
                        ) : null}
                        {w.kind === "Deployment" && (
                          <details>
                            <summary>CPU evidence by pool</summary>
                            {w.pools.map((p) => (
                              <div key={p.pool_id}>
                                <small>
                                  {p.pool_name} · cutoff {date(p.cutoff)}
                                </small>
                                <MetricEvidence
                                  resource="CPU"
                                  evidence={p.cpu_evidence}
                                />
                              </div>
                            ))}
                          </details>
                        )}
                      </td>
                      <td>
                        {w.kind === "Deployment"
                          ? gib(w.memory_p99)
                          : "Deployments only"}
                        {w.kind !== "Deployment" ? (
                          <small>Inspect individual Pod metrics below</small>
                        ) : !w.memory_complete ? (
                          <small>
                            {w.memory_definitions.length > 1
                              ? "Mixed memory definitions; inspect pools separately"
                              : "Partial or missing coverage"}
                          </small>
                        ) : null}
                        {w.kind === "Deployment" && (
                          <details>
                            <summary>Memory evidence by pool</summary>
                            {w.pools.map((p) => (
                              <div key={p.pool_id}>
                                <small>
                                  {p.pool_name} · cutoff {date(p.cutoff)}
                                </small>
                                <MetricEvidence
                                  resource="Memory"
                                  evidence={p.memory_evidence}
                                />
                              </div>
                            ))}
                          </details>
                        )}
                      </td>
                      <td title={w.memory_peak_replica ?? undefined}>
                        {gib(w.memory_peak)}
                        <small>
                          {w.memory_peak_pool ?? "No attributable sample"}
                        </small>
                      </td>
                      <td>{w.services.join(", ") || "None associated"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="panel-footer">
              {scope.workloads.length} controllers · cluster replica totals are
              not added across snapshots
            </div>
          </section>
          <PodTable scope={scope} />
          <p className="help-note">
            Select an individual pool for request recommendations, usage
            timelines and capacity estimates.
          </p>
        </>
      )}
    </>
  );
}
