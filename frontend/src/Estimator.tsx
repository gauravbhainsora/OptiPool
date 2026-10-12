import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  Calculator,
  CheckCircle2,
  AlertTriangle,
  Clock3,
} from "lucide-react";
import { api, params } from "./api";
import { cores, gib, money, date, Notice } from "./components";
import ServiceSummary from "./ServiceSummary";
import ServiceEditor, { newService, servicePayload } from "./ServiceEditor";
import PlacementView from "./PlacementView";
import type { Estimate, Snapshot } from "./types";

export default function Estimator({ snapshot }: { snapshot: Snapshot }) {
  const [services, setServices] = useState(() => [newService()]);
  const [result, setResult] = useState<Estimate | null>(null);
  const [history, setHistory] = useState<
    { id: string; created: number; result: Estimate }[]
  >([]);
  const requestRef = useRef<AbortController | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    requestRef.current?.abort();
    setBusy(false);
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
    return () => {
      controller.abort();
      requestRef.current?.abort();
    };
  }, [snapshot.id, snapshot.pool.id]);
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setResult(null);
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    try {
      const value = await api<Estimate>(
        `/${services.length > 1 ? "estimate-bundle" : "estimate"}?${params({ pool_id: snapshot.pool.id, snapshot_id: snapshot.id })}`,
        {
          method: "POST",
          body: JSON.stringify(
            services.length > 1
              ? { services: services.map(servicePayload) }
              : servicePayload(services[0]),
          ),
        },
        controller.signal,
      );
      setResult(value);
      setHistory(
        await api(
          `/estimates?${params({ pool_id: snapshot.pool.id })}`,
          undefined,
          controller.signal,
        ),
      );
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError((e as Error).message);
    } finally {
      if (requestRef.current === controller) setBusy(false);
    }
  }
  return (
    <>
      <div className="section-heading">
        <div>
          <h2>Plan your next deployment</h2>
          <p>
            Assess services together against saved requests, placement rules,
            and node budgets.
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
          <ServiceEditor services={services} onChange={setServices} />
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
              {result.per_replica && (
                <p className="muted">
                  Per replica: {cores(result.per_replica.cpu)} ·{" "}
                  {gib(result.per_replica.memory)}
                </p>
              )}
              <ServiceSummary result={result} />
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
