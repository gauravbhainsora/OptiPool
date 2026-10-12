import { useState } from "react";
import { Search } from "lucide-react";
import { cores, date, ExportButtons, gib } from "./components";
import ClusterExportButtons from "./ClusterExportButtons";
import MetricEvidence from "./MetricEvidence";
import type { ClusterSnapshot, Snapshot } from "./types";

export default function PodTable({
  snapshot,
  scope,
}:
  | { snapshot: Snapshot; scope?: never }
  | { scope: ClusterSnapshot; snapshot?: never }) {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const days = scope?.days ?? snapshot?.usage.days ?? 3;
  const filtered = (scope?.pods ?? snapshot?.pods ?? []).filter((p) =>
    `${p.name} ${p.namespace} ${p.workload} ${p.node}`
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
  const totalPages = Math.max(1, Math.ceil(filtered.length / 50));
  const activePage = Math.min(page, totalPages - 1);
  const rows = filtered.slice(activePage * 50, (activePage + 1) * 50);
  return (
    <section className="panel pod-panel">
      <div className="panel-heading">
        <div>
          <h2>
            Individual Pods <span className="count">{filtered.length}</span>
          </h2>
          <p>
            {scope
              ? `Saved Pods across all node pools in ${scope.cluster}.`
              : `Saved Pods on ${snapshot?.pool.name}, plus unscheduled Pods constrained to this pool.`}
          </p>
        </div>
        {scope ? (
          <ClusterExportButtons scope={scope} table="pods" search={search} />
        ) : (
          <ExportButtons
            table="pods"
            query={{
              pool_id: snapshot?.pool.id ?? "",
              snapshot_id: snapshot?.id ?? "",
              pod_search: search,
              days,
            }}
          />
        )}
      </div>
      <div className="table-toolbar">
        <div className="search">
          <Search size={15} />
          <input
            aria-label="Search Pods"
            placeholder="Search Pod, workload, namespace, node…"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(0);
            }}
          />
        </div>
        <span className="muted">
          Effective Pod requests include init containers and overhead · usage
          follows the selected saved window
        </span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Pod / namespace</th>
              <th>Owning workload</th>
              <th>Node</th>
              {scope && <th>Node pool / snapshot</th>}
              <th>Status / restarts</th>
              <th>Requests</th>
              <th>Limits</th>
              <th>Saved usage / p99</th>
              <th>Created</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => {
              const m = p.usage ?? snapshot?.usage.pods?.[p.uid];
              return (
                <tr key={`${p.pool_id ?? snapshot?.pool.id}/${p.uid}`}>
                  <td>
                    <strong className="mono">{p.name}</strong>
                    <small>{p.namespace}</small>
                  </td>
                  <td>{p.workload.split("/").slice(1).join(" / ")}</td>
                  <td>
                    <span className="mono">{p.node ?? "Unscheduled"}</span>
                  </td>
                  {scope && (
                    <td>
                      {p.pool_name}
                      <small>{date(p.saved_at)}</small>
                    </td>
                  )}
                  <td>
                    <span
                      className={`pill ${p.phase === "Running" ? "nonprod" : "production"}`}
                    >
                      {p.phase}
                    </span>
                    <small>
                      {p.ready === false ? "Not ready · " : ""}
                      {p.restarts} restarts
                    </small>
                  </td>
                  <td>
                    <strong>{cores(p.requested.cpu)}</strong>
                    <small>{gib(p.requested.memory)}</small>
                  </td>
                  <td>
                    <strong>{cores(p.limits.cpu)}</strong>
                    <small>{gib(p.limits.memory)}</small>
                  </td>
                  <td>
                    <strong>
                      {cores(m?.cpu_latest)} / {cores(m?.cpu_p99)}
                    </strong>
                    <small>
                      {gib(m?.memory_latest)} / {gib(m?.memory_p99)}
                    </small>
                    <small>Latest / p99 · {days} days</small>
                    <small>Sampled peak: {gib(m?.memory_peak)}</small>
                    <small>
                      CPU at {date(m?.cpu_sample_at)} · memory at{" "}
                      {date(m?.memory_sample_at)}
                    </small>
                  </td>
                  <td>{date(p.created)}</td>
                  <td>
                    <details>
                      <summary>Pod details</summary>
                      <p>
                        {p.status_available
                          ? p.oom_killed
                            ? "OOMKilled observed"
                            : "Saved container status available"
                          : "Container status not captured in this snapshot"}
                      </p>
                      <p>
                        CPU samples: {m?.cpu_samples ?? 0} · memory samples:{" "}
                        {m?.memory_samples ?? 0}. Coverage:{" "}
                        {m?.cpu_coverage == null
                          ? "unknown"
                          : `${Math.round(m.cpu_coverage * 100)}% CPU`}{" "}
                        /{" "}
                        {m?.memory_coverage == null
                          ? "unknown"
                          : `${Math.round(m.memory_coverage * 100)}% memory`}
                        . CPU throttling history is not collected.
                      </p>
                      <div className="table-wrap">
                        <MetricEvidence
                          resource="CPU"
                          evidence={m?.cpu_evidence}
                        />
                        <MetricEvidence
                          resource="Memory"
                          evidence={m?.memory_evidence}
                        />
                        <table>
                          <thead>
                            <tr>
                              <th>Container</th>
                              <th>Requests</th>
                              <th>Limits</th>
                            </tr>
                          </thead>
                          <tbody>
                            {(p.containers ?? []).map((c) => (
                              <tr key={`${c.kind}/${c.name}`}>
                                <td>
                                  {c.name}
                                  <small>{c.kind}</small>
                                </td>
                                <td>
                                  {cores(c.requested.cpu)}
                                  <small>{gib(c.requested.memory)}</small>
                                </td>
                                <td>
                                  {cores(c.limits.cpu)}
                                  <small>{gib(c.limits.memory)}</small>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      {(p.conditions ?? []).map((c) => (
                        <p key={c.type}>
                          {c.type}: {c.status} · {c.reason} {c.message}
                        </p>
                      ))}
                      <pre>
                        {JSON.stringify(
                          {
                            uid: p.uid,
                            labels: p.labels,
                            containers: p.containers,
                            spec: p.spec,
                          },
                          null,
                          2,
                        )}
                      </pre>
                    </details>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {!rows.length && (
        <div className="empty">No saved Pods match this search.</div>
      )}
      <div className="panel-footer">
        <span>
          {filtered.length} Pods · page {activePage + 1} of {totalPages} ·
          {scope
            ? `${scope.sources.length} pool snapshots`
            : `snapshot ${snapshot?.id.slice(0, 8)}`}
        </span>
        <div className="pagination">
          <button
            className="button small"
            disabled={activePage === 0}
            onClick={() => setPage(activePage - 1)}
          >
            Previous
          </button>
          <button
            className="button small"
            disabled={activePage + 1 >= totalPages}
            onClick={() => setPage(activePage + 1)}
          >
            Next
          </button>
        </div>
      </div>
    </section>
  );
}
