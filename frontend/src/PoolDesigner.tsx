import { useEffect, useState } from "react";
import { Download, Sparkles } from "lucide-react";
import { api, params } from "./api";
import { cores, date, gib, money, Notice } from "./components";
import ServiceSummary from "./ServiceSummary";
import PlacementView from "./PlacementView";
import ServiceEditor, { newService, servicePayload } from "./ServiceEditor";
import type { Cost, Estimate, Resources } from "./types";

type Profile = {
  pool_id: string;
  pool_name: string;
  snapshot_id: string;
  saved_at: number;
  machine_type: string;
  disk_type: string;
  disk_gb: number;
  provisioning_model: string;
  synthetic: boolean;
  node_cost: Cost;
  templates: {
    zone: string;
    allocatable: Resources & { pods: number };
    requested: Resources;
    pod_count: number;
    labels: Record<string, string>;
    taints: unknown[];
  }[];
};
type Candidate = {
  profile: Profile;
  assessment: Omit<Estimate, "id">;
  complete: boolean;
  configuration: {
    name: string;
    machine_type: string;
    total_nodes: number | null;
    nodes_by_zone: Record<string, number>;
  };
};
type Report = {
  id: string;
  name: string;
  environment: string;
  recommended_profile: string | null;
  ranking: string;
  candidates: Candidate[];
  assumptions: string[];
};
type SavedDesign = {
  id: string;
  created: number;
  input: {
    name: string;
    environment: string;
    snapshots: Record<string, string>;
    services: (Omit<ReturnType<typeof servicePayload>, "hpa_max_replicas"> & {
      hpa_max_replicas: number | null;
    })[];
  };
  result: Omit<Report, "id">;
};

type Profiles = {
  profiles: Profile[];
  missing: { pool_name: string; reason: string }[];
};

export default function PoolDesigner({
  project,
  location,
  cluster,
}: {
  project: string;
  location: string;
  cluster: string;
}) {
  const [profiles, setProfiles] = useState<Profiles | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [services, setServices] = useState(() => [newService()]);
  const [name, setName] = useState("new-services");
  const [environment, setEnvironment] = useState("production");
  const [result, setResult] = useState<Report | null>(null);
  const [history, setHistory] = useState<SavedDesign[]>([]);
  const [active, setActive] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const query = params({ project, location, cluster });
  useEffect(() => {
    const controller = new AbortController();
    setProfiles(null);
    setResult(null);
    setError("");
    api<Profiles>(`/node-pool-profiles?${query}`, undefined, controller.signal)
      .then((value) => {
        setProfiles(value);
        setSelected(
          value.profiles
            .filter((p) => p.templates.length)
            .slice(0, 10)
            .map((p) => p.pool_id),
        );
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    api<typeof history>(
      `/node-pool-designs?${query}`,
      undefined,
      controller.signal,
    )
      .then(setHistory)
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => controller.abort();
  }, [query, reload]);
  function display(report: Report) {
    setResult(report);
    setActive(
      report.recommended_profile ?? report.candidates[0]?.profile.pool_id ?? "",
    );
  }
  function restore(h: SavedDesign) {
    display({ ...h.result, id: h.id });
    setName(h.input.name);
    setEnvironment(h.input.environment);
    setServices(
      h.input.services.map((s, i) => ({
        ...newService(i + 1),
        ...s,
        advanced: Boolean(s.manifest),
        hpa_max_replicas: s.hpa_max_replicas ?? Math.max(s.replicas, 12),
      })),
    );
    setSelected(
      Object.keys(h.input.snapshots).filter((id) =>
        profiles?.profiles.some((p) => p.pool_id === id && p.templates.length),
      ),
    );
  }
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const report = await api<Report>("/node-pool-design", {
        method: "POST",
        body: JSON.stringify({
          project,
          location,
          cluster,
          name,
          environment,
          services: services.map(servicePayload),
          snapshots: Object.fromEntries(
            (profiles?.profiles ?? [])
              .filter((p) => selected.includes(p.pool_id))
              .map((p) => [p.pool_id, p.snapshot_id]),
          ),
        }),
      });
      display(report);
      setHistory(await api(`/node-pool-designs?${query}`));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function download() {
    const anchor = document.createElement("a");
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }),
    );
    anchor.href = url;
    anchor.download = "optipool-node-pool-design.json";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const candidate = result?.candidates.find(
    (c) => c.profile.pool_id === active,
  );
  return (
    <>
      <div className="section-heading">
        <div>
          <h2>Design a new node pool</h2>
          <p>
            {project} / {cluster} / {location}
          </p>
        </div>
        <span className="pill neutral">
          <Sparkles size={14} />
          Design only
        </span>
      </div>
      <p className="help-note">
        Size an empty new pool for all entered services using node
        configurations already saved in this cluster. Profiles retain their own
        capture times and prices. Existing pool capacity is not reused. Review
        the design before provisioning outside OptiPool.
      </p>
      <div className="estimator-grid">
        <form className="panel scenario" onSubmit={submit}>
          <h3>New pool requirements</h3>
          <label>
            New node pool name
            <input
              required
              minLength={1}
              maxLength={40}
              pattern="[a-z]([a-z0-9-]*[a-z0-9])?"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label>
            Environment
            <select
              aria-label="New pool environment"
              value={environment}
              onChange={(e) => setEnvironment(e.target.value)}
            >
              <option value="production">
                Production · 80% request ceiling
              </option>
              <option value="nonproduction">
                Nonproduction · 90% request ceiling
              </option>
            </select>
          </label>
          <ServiceEditor services={services} onChange={setServices} />
          <h3>Candidate node profiles</h3>
          <p className="form-hint">
            Choose up to 10 observed configurations. This is a saved-profile
            comparison, not the full GCP machine catalog.
          </p>
          {!profiles && <p>Loading saved profiles…</p>}
          {profiles?.missing.map((p) => (
            <Notice key={p.pool_name}>
              {p.pool_name}: {p.reason}. Select that individual pool to fetch
              data explicitly.
            </Notice>
          ))}
          {profiles?.profiles.map((p) => (
            <div className="profile-choice" key={p.pool_id}>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  aria-label={`Use profile ${p.pool_name}`}
                  checked={selected.includes(p.pool_id)}
                  disabled={
                    !p.templates.length ||
                    (!selected.includes(p.pool_id) && selected.length >= 10)
                  }
                  onChange={(e) =>
                    setSelected(
                      e.target.checked
                        ? [...selected, p.pool_id]
                        : selected.filter((id) => id !== p.pool_id),
                    )
                  }
                />
                {p.machine_type} · {p.pool_name}
              </label>
              <p className="form-hint">
                {p.provisioning_model} · {p.disk_gb} GiB {p.disk_type} ·{" "}
                {date(p.saved_at)}
                {p.synthetic ? " · Synthetic" : ""}
              </p>
              {p.templates.map((t) => (
                <p className="form-hint" key={t.zone}>
                  {t.zone}: {cores(t.allocatable.cpu)} /{" "}
                  {gib(t.allocatable.memory)} allocatable · overhead{" "}
                  {cores(t.requested.cpu)} / {gib(t.requested.memory)} ·{" "}
                  {t.pod_count} baseline Pods
                </p>
              ))}
              <p className="form-hint">
                Saved node quote:{" "}
                {p.node_cost.available
                  ? `${money(p.node_cost.on_demand_monthly)} /mo`
                  : "Unavailable"}
              </p>
              {!p.templates.length && (
                <Notice>
                  No verified allocatable template. Fetch that pool explicitly
                  to collect evidence.
                </Notice>
              )}
            </div>
          ))}
          <button
            type="button"
            className="button small"
            onClick={() => setReload((n) => n + 1)}
            disabled={busy}
          >
            Reload saved profiles
          </button>
          <button
            className="button primary full"
            disabled={busy || !selected.length}
          >
            {busy ? "Comparing saved profiles…" : "Design node pool"}
          </button>
          {error && <Notice>{error}</Notice>}
        </form>
        <div>
          {result ? (
            <section className="panel result">
              <span className="eyebrow">NEW NODE POOL DESIGN</span>
              <h2>{result.name}</h2>
              <p>{result.ranking}</p>
              {!result.recommended_profile && (
                <Notice>
                  No complete modeled assignment was found. Review constraints
                  and missing evidence below.
                </Notice>
              )}
              <div className="table-wrap">
                <table aria-label="Node pool candidates">
                  <thead>
                    <tr>
                      <th>Saved profile</th>
                      <th>Total nodes</th>
                      <th>On-demand /mo</th>
                      <th>3-year resource CUD /mo</th>
                      <th>Assessment</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.candidates.map((c) => (
                      <tr key={c.profile.pool_id}>
                        <td>
                          <button
                            type="button"
                            className="button small"
                            aria-pressed={active === c.profile.pool_id}
                            onClick={() => setActive(c.profile.pool_id)}
                          >
                            {c.profile.machine_type} · {c.profile.pool_name}
                          </button>
                          {result.recommended_profile === c.profile.pool_id && (
                            <small>Recommended modeled candidate</small>
                          )}
                          <small>{date(c.profile.saved_at)}</small>
                        </td>
                        <td>{c.configuration.total_nodes ?? "Unknown"}</td>
                        <td>
                          {c.assessment.cost.available
                            ? money(c.assessment.cost.on_demand_monthly)
                            : "Unavailable"}
                        </td>
                        <td>
                          {c.assessment.cost.cud_status === "not_applicable"
                            ? "Not applicable"
                            : c.assessment.cost.cud_3y_monthly == null
                              ? "Unavailable"
                              : money(c.assessment.cost.cud_3y_monthly)}
                        </td>
                        <td>
                          {c.assessment.outcome}
                          <small>
                            {c.complete
                              ? "Complete modeled assignment"
                              : "Incomplete assignment"}
                          </small>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="form-hint">
                USD · 730h/month · quotations are saved assumptions. Regional
                per-zone creation, IPs, quotas and new-pool overhead require
                operator review.
              </p>
              <button type="button" className="button small" onClick={download}>
                <Download size={14} />
                Download design JSON
              </button>
              <ul>
                {result.assumptions.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
              <p className="form-hint">Saved design {result.id.slice(0, 8)}</p>
            </section>
          ) : (
            <section className="panel result-placeholder">
              <h3>Find a pool shape for your services</h3>
              <p>
                Compare complete workload placements, policy buffers and costs
                for saved node profiles. The output is an immutable design
                report for review.
              </p>
            </section>
          )}
        </div>
      </div>
      {candidate && (
        <>
          <section className="panel analytical-panel">
            <h3>Selected candidate: {candidate.profile.pool_name}</h3>
            <p>{candidate.assessment.reason}</p>
            <ServiceSummary result={candidate.assessment} />
            {candidate.assessment.warnings.map((w) => (
              <Notice key={w}>{w}</Notice>
            ))}
            <p>
              3-year eligible commitment obligation:{" "}
              {candidate.assessment.cost.commitment_3y_obligation == null
                ? "Not quoted"
                : money(candidate.assessment.cost.commitment_3y_obligation)}
            </p>
            <p className="muted">
              {candidate.assessment.cost.source ??
                candidate.assessment.cost.reason}
            </p>
            <p className="form-hint">{candidate.assessment.cost.assumption}</p>
          </section>
          <PlacementView result={{ ...candidate.assessment, id: result!.id }} />
        </>
      )}
      {history.length > 0 && (
        <section className="panel history">
          <h3>Saved node pool designs</h3>
          {history.map((h) => (
            <p key={h.id}>
              <button
                type="button"
                className="button small"
                onClick={() => restore(h)}
              >
                {h.result.name} · {date(h.created)}
              </button>
            </p>
          ))}
        </section>
      )}
    </>
  );
}
