import { useEffect, useState } from "react";
import { api, params } from "./api";
import { cores, gib, Notice } from "./components";
import type { Recommendation, Snapshot } from "./types";

export default function RightSizing({ snapshot }: { snapshot: Snapshot }) {
  const [headroom, setHeadroom] = useState(20);
  const [data, setData] = useState<{
    rows: Recommendation[];
    assumption: string;
  } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError("");
    api<{ rows: Recommendation[]; assumption: string }>(
      `/recommendations?${params({ pool_id: snapshot.pool.id, snapshot_id: snapshot.id, days: snapshot.usage.days, headroom })}`,
      undefined,
      controller.signal,
    )
      .then(setData)
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [snapshot.id, snapshot.pool.id, snapshot.usage.days, headroom]);
  return (
    <section className="panel analytical-panel">
      <div className="panel-heading">
        <div>
          <h2>Request recommendations</h2>
          <p>
            Advisory effective Pod requests from the {snapshot.usage.days}-day
            saved window.
          </p>
        </div>
        <label>
          Usage headroom
          <select
            aria-label="Recommendation headroom"
            value={headroom}
            onChange={(e) => setHeadroom(Number(e.target.value))}
          >
            {[10, 20, 30, 50, 100].map((v) => (
              <option value={v} key={v}>
                {v}%
              </option>
            ))}
          </select>
        </label>
      </div>
      {error && <Notice>{error}</Notice>}
      {data ? (
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Deployment</th>
                  <th>Current / Pod</th>
                  <th>Proposal / Pod</th>
                  <th>Pool capacity delta</th>
                  <th>Sample coverage</th>
                  <th>Review evidence</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={r.workload_id}>
                    <td>
                      <strong>{r.name}</strong>
                      <small>
                        {r.namespace} · {r.pool_replicas} pool replicas
                      </small>
                    </td>
                    <td>
                      {cores(r.current.cpu)}
                      <small>{gib(r.current.memory)}</small>
                    </td>
                    <td>
                      {cores(r.proposed.cpu)}
                      <small>{gib(r.proposed.memory)}</small>
                    </td>
                    <td>
                      {cores(r.recovered.cpu)}
                      <small>{gib(r.recovered.memory)}</small>
                      <small>
                        Positive frees requests; negative adds requests
                      </small>
                    </td>
                    <td>
                      {r.coverage == null
                        ? "Unknown"
                        : `${Math.round(r.coverage * 100)}%`}
                      <small>{r.status}</small>
                    </td>
                    <td>
                      <details>
                        <summary>Evidence and limits</summary>
                        <ul>
                          {r.warnings.map((w) => (
                            <li key={w}>{w}</li>
                          ))}
                        </ul>
                      </details>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="form-hint">{data.assumption}</p>
        </>
      ) : (
        !error && <p className="muted">Calculating from saved observations…</p>
      )}
    </section>
  );
}
