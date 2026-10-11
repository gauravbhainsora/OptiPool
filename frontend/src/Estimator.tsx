import { useEffect, useState } from "react";
import {
  ArrowRight,
  Calculator,
  CheckCircle2,
  AlertTriangle,
  Clock3,
} from "lucide-react";
import { api, params } from "./api";
import { cores, gib, money, date, Notice } from "./components";
import PlacementView from "./PlacementView";
import type { Estimate, Snapshot } from "./types";

export default function Estimator({ snapshot }: { snapshot: Snapshot }) {
  const [advanced, setAdvanced] = useState(false);
  const [form, setForm] = useState({
    name: "recommendation-api",
    namespace: "commerce",
    cpu: "500m",
    memory: "1Gi",
    replicas: 6,
    manifest: "",
    planning_mode: "steady",
    hpa_max_replicas: 12,
    max_surge: "25%",
    spread_zones: false,
  });
  const [result, setResult] = useState<Estimate | null>(null);
  const [history, setHistory] = useState<
    { id: string; created: number; result: Estimate }[]
  >([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    setResult(null);
    setHistory([]);
    const controller = new AbortController();
    api<typeof history>(
      `/estimates?${params({ pool_id: snapshot.pool.id })}`,
      undefined,
      controller.signal,
    )
      .then(setHistory)
      .catch(() => {});
    return () => controller.abort();
  }, [snapshot.id, snapshot.pool.id]);
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const value = await api<Estimate>(
        `/estimate?${params({ pool_id: snapshot.pool.id })}`,
        {
          method: "POST",
          body: JSON.stringify({
            ...form,
            manifest: advanced ? form.manifest : "",
          }),
        },
      );
      setResult(value);
      setHistory(
        await api(`/estimates?${params({ pool_id: snapshot.pool.id })}`),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="section-heading">
        <div>
          <h2>Plan your next deployment</h2>
          <p>
            Test a new service against saved requests, placement rules, and node
            budgets.
          </p>
        </div>
        <span className="pill neutral">
          <Calculator size={14} /> Planning only
        </span>
      </div>
      <div className="estimator-grid">
        <form className="panel scenario" onSubmit={submit}>
          <h3>Workload requirements</h3>
          <div className="target-pool">
            <span>Schedule onto selected node pool</span>
            <strong>{snapshot.pool.name}</strong>
            <small>
              {snapshot.pool.project} / {snapshot.pool.cluster}
            </small>
            <p>Choose a different target using Selected node pool above.</p>
          </div>
          <div className="segmented">
            <button
              type="button"
              className={!advanced ? "active" : ""}
              onClick={() => setAdvanced(false)}
            >
              Simple input
            </button>
            <button
              type="button"
              className={advanced ? "active" : ""}
              onClick={() => setAdvanced(true)}
            >
              Deployment YAML
            </button>
          </div>
          <label>
            Service name
            <input
              required
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </label>
          <label>
            Target namespace
            <input
              required
              value={form.namespace}
              onChange={(e) => setForm({ ...form, namespace: e.target.value })}
            />
          </label>
          {advanced ? (
            <label>
              apps/v1 Deployment
              <textarea
                required
                rows={14}
                placeholder={
                  "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: my-service\nspec: ..."
                }
                value={form.manifest}
                onChange={(e) => setForm({ ...form, manifest: e.target.value })}
              />
            </label>
          ) : (
            <>
              <div className="form-pair">
                <label>
                  CPU request / replica
                  <input
                    required
                    value={form.cpu}
                    onChange={(e) => setForm({ ...form, cpu: e.target.value })}
                  />
                </label>
                <label>
                  Memory request / replica
                  <input
                    required
                    value={form.memory}
                    onChange={(e) =>
                      setForm({ ...form, memory: e.target.value })
                    }
                  />
                </label>
              </div>
              <label>
                Replica count
                <input
                  type="number"
                  min="0"
                  max="2000"
                  required
                  value={form.replicas}
                  onChange={(e) =>
                    setForm({ ...form, replicas: Number(e.target.value) })
                  }
                />
              </label>
              <p className="form-hint">
                One regular container per Pod. No affinity, storage, or injected
                sidecars assumed. Existing demand is considered first.
              </p>
            </>
          )}
          <label>
            Planning scenario
            <select
              aria-label="Planning scenario"
              value={form.planning_mode}
              onChange={(e) =>
                setForm({ ...form, planning_mode: e.target.value })
              }
            >
              <option value="steady">Steady replicas</option>
              <option value="hpa">HPA maximum</option>
              <option value="rollout">Rollout headroom</option>
              <option value="combined">HPA maximum + rollout headroom</option>
            </select>
          </label>
          {["hpa", "combined"].includes(form.planning_mode) && (
            <label>
              HPA maximum replicas
              <input
                aria-label="HPA maximum replicas"
                type="number"
                min="0"
                max="2000"
                value={form.hpa_max_replicas}
                onChange={(e) =>
                  setForm({ ...form, hpa_max_replicas: Number(e.target.value) })
                }
              />
            </label>
          )}
          {["rollout", "combined"].includes(form.planning_mode) && (
            <label>
              Surge headroom
              <input
                aria-label="Surge headroom"
                value={form.max_surge}
                onChange={(e) =>
                  setForm({ ...form, max_surge: e.target.value })
                }
              />
              <small>
                Integer or percentage, rounded up; planning override.
              </small>
            </label>
          )}
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={form.spread_zones}
              onChange={(e) =>
                setForm({ ...form, spread_zones: e.target.checked })
              }
            />
            Spread proposed Pods across zones
          </label>
          <p className="form-hint">
            Additional demand with existing Pods fixed. Rollout headroom does
            not simulate replacement, terminating Pods or availability
            sequencing. HPA cap is a what-if input.
          </p>
          <button className="button primary full" disabled={busy}>
            {busy ? "Assessing saved capacity…" : "Estimate capacity"}
            <ArrowRight size={16} />
          </button>
          {error && <Notice>{error}</Notice>}
        </form>
        <div>
          {result ? (
            <section className="panel result">
              <div
                className={`result-icon ${result.outcome === "Fits" ? "success" : "warning"}`}
              >
                {result.outcome === "Fits" ? (
                  <CheckCircle2 size={25} />
                ) : (
                  <AlertTriangle size={25} />
                )}
              </div>
              <span className="eyebrow">CAPACITY ASSESSMENT</span>
              <div className="target-pool">
                <span>Target node pool</span>
                <strong>{(result.target_pool ?? snapshot.pool).name}</strong>
                <small>
                  {(result.target_pool ?? snapshot.pool).project} /{" "}
                  {(result.target_pool ?? snapshot.pool).cluster}
                </small>
              </div>
              <h2>{result.outcome}</h2>
              <p>{result.reason}</p>
              <div className="result-numbers">
                <div>
                  <strong>{result.additional_nodes ?? "?"}</strong>
                  <span>additional nodes</span>
                </div>
                <div>
                  <strong>{result.permitted_growth ?? "—"}</strong>
                  <span>permitted growth</span>
                </div>
                <div>
                  <strong>{result.replicas}</strong>
                  <span>peak proposed replicas</span>
                </div>
              </div>
              {result.planning && (
                <p className="form-hint">
                  Base {result.planning.steady_replicas} → HPA envelope{" "}
                  {result.planning.hpa_replicas} + surge{" "}
                  {result.planning.surge_replicas} = peak{" "}
                  {result.planning.peak_replicas}
                </p>
              )}
              <p className="muted">
                Per replica: {cores(result.per_replica.cpu)} ·{" "}
                {gib(result.per_replica.memory)}
              </p>
              {result.exceeds_autoscaler_max && (
                <Notice>
                  Required growth exceeds the saved autoscaler maximum. A
                  configuration change would be needed.
                </Notice>
              )}
              {result.warnings.map((w) => (
                <Notice key={w}>{w}</Notice>
              ))}
              <div className="cost-heading">
                <h3>Additional node cost</h3>
                <span className="pill neutral">USD · 730h/month</span>
              </div>
              {result.cost.available ? (
                <>
                  <div className="cost-grid">
                    <div>
                      <span>On-demand</span>
                      <strong>
                        {money(result.cost.on_demand_monthly)}
                        <small>/mo</small>
                      </strong>
                      <p>{money(result.cost.on_demand_hourly)} / hour</p>
                    </div>
                    <div>
                      <span>3-year resource CUD</span>
                      <strong>
                        {result.cost.cud_status === "not_applicable"
                          ? "Not applicable"
                          : result.cost.cud_3y_monthly == null
                            ? "Unavailable"
                            : money(result.cost.cud_3y_monthly)}
                        <small>
                          {result.cost.cud_3y_monthly != null ? "/mo" : ""}
                        </small>
                      </strong>
                      <p>
                        {result.cost.cud_3y_hourly != null
                          ? `${money(result.cost.cud_3y_hourly)} / hour`
                          : result.cost.cud_reason}
                      </p>
                    </div>
                  </div>
                  <p className="form-hint">
                    3-year commitment obligation:{" "}
                    {result.cost.commitment_3y_obligation == null
                      ? "Not quoted"
                      : money(result.cost.commitment_3y_obligation)}{" "}
                    for eligible resources. Boot disk priced separately.
                  </p>
                  <p className="form-hint">{result.cost.assumption}</p>
                  <p className="muted">{result.cost.source}</p>
                </>
              ) : (
                <Notice>{result.cost.reason}</Notice>
              )}
              <details>
                <summary>Placement and assumptions</summary>
                <ul>
                  {result.assumptions.map((a) => (
                    <li key={a}>{a}</li>
                  ))}
                </ul>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Replica</th>
                        <th>Assigned node</th>
                        <th>Zone</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.placements.map((p) => (
                        <tr key={p.replica}>
                          <td>{p.replica}</td>
                          <td>{p.node}</td>
                          <td>{p.zone}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
              <p className="form-hint">
                Saved estimate {result.id.slice(0, 8)} · snapshot{" "}
                {result.snapshot_id.slice(0, 8)} · {date(result.snapshot_at)}
              </p>
            </section>
          ) : (
            <section className="panel result-placeholder">
              <div className="illustrated-nodes">
                <i />
                <i />
                <i />
                <ArrowRight size={28} />
                <i className="planned" />
              </div>
              <h3>Make room for what’s next</h3>
              <p>
                Check individual node capacity before deploying. See feasible
                placement, added nodes, and a saved cost scenario.
              </p>
              <span className="pill neutral">
                {snapshot.pool.environment === "production" ? "20%" : "10%"}{" "}
                request buffer preserved
              </span>
            </section>
          )}
        </div>
      </div>
      {result && <PlacementView result={result} />}
      {history.length > 0 && (
        <section className="panel history">
          <h3>
            <Clock3 size={16} /> Saved estimates
          </h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Created</th>
                  <th>Outcome</th>
                  <th>Replicas</th>
                  <th>Added nodes</th>
                  <th>Snapshot</th>
                </tr>
              </thead>
              <tbody>
                {history.map((h) => (
                  <tr key={h.id}>
                    <td>{date(h.created)}</td>
                    <td>{h.result.outcome}</td>
                    <td>{h.result.replicas}</td>
                    <td>{h.result.additional_nodes ?? "Unknown"}</td>
                    <td>
                      <code>{h.result.snapshot_id.slice(0, 8)}</code>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}
