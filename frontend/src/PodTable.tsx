import { useState } from "react";
import { Search } from "lucide-react";
import { cores, date, ExportButtons, gib } from "./components";
import type { Snapshot } from "./types";

export default function PodTable({ snapshot }: { snapshot: Snapshot }) {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const filtered = (snapshot.pods ?? []).filter((p) =>
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
            Active Pods on {snapshot.pool.name}, plus unscheduled Pods
            constrained to this pool.
          </p>
        </div>
        <ExportButtons
          table="pods"
          query={{ pool_id: snapshot.pool.id, pod_search: search }}
        />
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
          Effective Pod requests include init containers and overhead
        </span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Pod / namespace</th>
              <th>Owning workload</th>
              <th>Node</th>
              <th>Status / restarts</th>
              <th>Requests</th>
              <th>Limits</th>
              <th>Created</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.uid}>
                <td>
                  <strong className="mono">{p.name}</strong>
                  <small>{p.namespace}</small>
                </td>
                <td>{p.workload.split("/").slice(1).join(" / ")}</td>
                <td>
                  <span className="mono">{p.node ?? "Unscheduled"}</span>
                </td>
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
                <td>{date(p.created)}</td>
                <td>
                  <details>
                    <summary>Pod specification</summary>
                    <pre>
                      {JSON.stringify(
                        { uid: p.uid, labels: p.labels, spec: p.spec },
                        null,
                        2,
                      )}
                    </pre>
                  </details>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!rows.length && (
        <div className="empty">No saved Pods match this search.</div>
      )}
      <div className="panel-footer">
        <span>
          {filtered.length} Pods · page {activePage + 1} of {totalPages} ·
          snapshot {snapshot.id.slice(0, 8)}
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
