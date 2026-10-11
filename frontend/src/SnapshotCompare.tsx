import { useEffect, useState } from "react";
import { api, params } from "./api";
import { cores, gib, date, Notice } from "./components";
import type { Comparison, Snapshot } from "./types";

type Saved = { id: string; saved_at: number };
export default function SnapshotCompare({ snapshot }: { snapshot: Snapshot }) {
  const [saved, setSaved] = useState<Saved[]>([]);
  const [before, setBefore] = useState("");
  const [after, setAfter] = useState("");
  const [result, setResult] = useState<Comparison | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setSaved([]);
    setResult(null);
    setError("");
    api<Saved[]>(
      `/snapshots?${params({ pool_id: snapshot.pool.id })}`,
      undefined,
      controller.signal,
    )
      .then((rows) => {
        setSaved(rows);
        setBefore(rows[1]?.id ?? "");
        setAfter(rows[0]?.id ?? "");
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [snapshot.id, snapshot.pool.id]);
  async function compare(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setResult(null);
    try {
      setResult(
        await api<Comparison>(
          `/snapshots/compare?${params({ pool_id: snapshot.pool.id, before, after })}`,
        ),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel analytical-panel">
      <div className="panel-heading">
        <div>
          <h2>Compare saved snapshots</h2>
          <p>
            {snapshot.pool.name} · changes between explicitly collected
            observations.
          </p>
        </div>
        <span className="pill neutral">Saved data only</span>
      </div>
      {saved.length < 2 ? (
        <p className="muted">
          Two saved snapshots are needed. Use Fetch latest live data for this
          pool when you want another observation.
        </p>
      ) : (
        <form className="comparison-controls" onSubmit={compare}>
          <label>
            Before
            <select
              value={before}
              onChange={(e) => {
                setBefore(e.target.value);
                setResult(null);
              }}
            >
              {saved.map((s) => (
                <option key={s.id} value={s.id}>
                  {date(s.saved_at)} · {s.id.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
          <label>
            After
            <select
              value={after}
              onChange={(e) => {
                setAfter(e.target.value);
                setResult(null);
              }}
            >
              {saved.map((s) => (
                <option key={s.id} value={s.id}>
                  {date(s.saved_at)} · {s.id.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
          <button
            className="button primary"
            disabled={busy || before === after}
          >
            {busy ? "Comparing…" : "Compare snapshots"}
          </button>
        </form>
      )}
      {error && <Notice>{error}</Notice>}
      {result && (
        <>
          <div className="comparison-deltas">
            <span>
              {result.delta.nodes >= 0 ? "+" : ""}
              {result.delta.nodes} nodes
            </span>
            <span>
              {result.delta.pods >= 0 ? "+" : ""}
              {result.delta.pods} Pods
            </span>
            <span>
              Requests: {cores(result.delta.cpu)} · {gib(result.delta.memory)}
            </span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Resource</th>
                  <th>Change</th>
                  <th>Observed differences</th>
                </tr>
              </thead>
              <tbody>
                {result.changes.map((c) => (
                  <tr key={`${c.entity}/${c.id}`}>
                    <td>
                      <strong>{c.name}</strong>
                      <small>
                        {c.entity} {c.namespace}
                      </small>
                    </td>
                    <td>{c.change}</td>
                    <td>
                      {Object.keys(c.fields).length ? (
                        <details>
                          <summary>Changed fields</summary>
                          <pre>{JSON.stringify(c.fields, null, 2)}</pre>
                        </details>
                      ) : (
                        "Present in one snapshot"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!result.changes.length && (
            <p className="muted">No changes in compared resource fields.</p>
          )}
          <p className="form-hint">
            Observation differences do not establish why a change happened.
            Metrics and Kubernetes observations may have different timestamps.
          </p>
        </>
      )}
    </section>
  );
}
