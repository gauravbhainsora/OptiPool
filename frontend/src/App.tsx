import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  Boxes,
  ChevronRight,
  CircleHelp,
  Database,
  Layers3,
  MemoryStick,
  PlusCircle,
  LayoutGrid,
  RefreshCw,
  Server,
  Sparkles,
  ArrowUpRight,
  ShieldCheck,
  Search,
} from "lucide-react";
import { api, params } from "./api";
import {
  BudgetBar,
  cores,
  date,
  ExportButtons,
  gib,
  Notice,
  UsageChart,
} from "./components";
import Estimator from "./Estimator";
import PodTable from "./PodTable";
import RightSizing from "./RightSizing";
import SnapshotCompare from "./SnapshotCompare";
import PoolDesigner from "./PoolDesigner";
import ClusterView from "./ClusterView";
import type { ClusterSnapshot, Job, Pool, Snapshot, Workload } from "./types";

type Inventory = {
  discovery_job: Job | null;
  pools: Pool[];
  mode: string;
  actor: string;
  initialized: boolean;
  errors: { scope: string; error: string }[];
  inventory_at: string | null;
  summaries: Record<
    string,
    {
      node_count: number;
      cpu: number;
      memory: number;
      cpu_allocatable: number;
      memory_allocatable: number;
      violations: number;
    }
  >;
};
type Tab = "pools" | "nodes" | "workloads" | "estimator" | "design";
const tabs: { id: Tab; label: string; icon: typeof Boxes }[] = [
  { id: "pools", label: "Node pools", icon: Layers3 },
  { id: "nodes", label: "Nodes", icon: Server },
  { id: "workloads", label: "Workloads", icon: Boxes },
  { id: "estimator", label: "Capacity planner", icon: Sparkles },
  { id: "design", label: "New node pool", icon: PlusCircle },
];

export default function App() {
  const [inventory, setInventory] = useState<Inventory | null>(null);
  const [project, setProject] = useState("all");
  const [cluster, setCluster] = useState("all");
  const [poolId, setPoolId] = useState("");
  const [tab, setTab] = useState<Tab>("pools");
  const [days, setDays] = useState(3);
  const [loadedDays, setLoadedDays] = useState(3);
  useEffect(() => {
    const timer = setTimeout(() => setLoadedDays(days), 150);
    return () => clearTimeout(timer);
  }, [days]);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [clusterSnapshot, setClusterSnapshot] =
    useState<ClusterSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [search, setSearch] = useState("");
  const [generation, setGeneration] = useState(0);
  const loadInventory = useCallback(async (signal?: AbortSignal) => {
    const value = await api<Inventory>("/inventory", undefined, signal);
    setInventory(value);
    return value;
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    loadInventory(controller.signal).catch((e) => {
      if (e.name !== "AbortError") setError(e.message);
    });
    return () => controller.abort();
  }, [loadInventory]);
  useEffect(() => {
    if (inventory?.initialized || inventory?.discovery_job?.state === "failed")
      return;
    const timer = setInterval(() => {
      loadInventory().catch((e) => setError(e.message));
    }, 2000);
    return () => clearInterval(timer);
  }, [inventory?.initialized, inventory?.discovery_job?.state, loadInventory]);
  const clusters = [
    ...new Map(
      (inventory?.pools ?? [])
        .filter((p) => project === "all" || p.project === project)
        .map((p) => [
          `${p.project}/${p.location}/${p.cluster}`,
          {
            id: `${p.project}/${p.location}/${p.cluster}`,
            project: p.project,
            location: p.location,
            name: p.cluster,
          },
        ]),
    ).values(),
  ];
  const selectedCluster = clusters.find((c) => c.id === cluster);
  const allPoolsSelected = poolId === "__all_pools__";
  const pools = (inventory?.pools ?? []).filter(
    (p) =>
      (project === "all" || p.project === project) &&
      (cluster === "all" ||
        (p.project === selectedCluster?.project &&
          p.location === selectedCluster.location &&
          p.cluster === selectedCluster.name)),
  );
  const filtered = pools.filter((p) =>
    `${p.name} ${p.project} ${p.cluster}`
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
  useEffect(() => {
    if (allPoolsSelected && selectedCluster && pools.length) return;
    if (inventory && !pools.some((p) => p.id === poolId))
      setPoolId(pools[0]?.id ?? "");
  }, [inventory, project, cluster, poolId]);
  const pool = pools.find((p) => p.id === poolId);
  const designCluster =
    selectedCluster ??
    (pool
      ? { project: pool.project, location: pool.location, name: pool.cluster }
      : null);
  useEffect(() => {
    if (!poolId) return;
    const controller = new AbortController();
    setLoading(true);
    if (allPoolsSelected && selectedCluster) {
      setSnapshot(null);
      setClusterSnapshot((previous) =>
        previous?.project === selectedCluster.project &&
        previous.location === selectedCluster.location &&
        previous.cluster === selectedCluster.name
          ? previous
          : null,
      );
      setError("");
      api<ClusterSnapshot>(
        `/cluster-snapshot?${params({ project: selectedCluster.project, location: selectedCluster.location, cluster: selectedCluster.name, days: loadedDays })}`,
        undefined,
        controller.signal,
      )
        .then(setClusterSnapshot)
        .catch((e) => {
          if (e.name !== "AbortError") setError(e.message);
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
      return () => controller.abort();
    }
    setClusterSnapshot(null);
    setSnapshot((previous) => (previous?.pool.id === poolId ? previous : null));
    setError("");
    api<Snapshot>(
      `/snapshot?${params({ pool_id: poolId, days: loadedDays })}`,
      undefined,
      controller.signal,
    )
      .then(setSnapshot)
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [poolId, loadedDays, generation, cluster]);
  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.state)) return;
    const timer = setTimeout(async () => {
      try {
        const next = await api<Job>(`/jobs/${job.id}`);
        setJob(next);
        if (["succeeded", "failed"].includes(next.state)) {
          await loadInventory();
          setGeneration((v) => v + 1);
          if (next.error) setError(next.error);
        }
      } catch (e) {
        setError((e as Error).message);
        setJob({ ...job, state: "failed" });
      }
    }, 1000);
    return () => clearTimeout(timer);
  }, [job, loadInventory]);
  async function refresh(kind: "pool" | "inventory") {
    setError("");
    try {
      const next = await api<Job>(
        `/refresh/${kind}${kind === "pool" ? `?${params({ pool_id: poolId })}` : ""}`,
        { method: "POST", body: "{}" },
      );
      setJob(next);
      if (["succeeded", "failed"].includes(next.state)) {
        await loadInventory();
        setGeneration((v) => v + 1);
        if (next.error) setError(next.error);
      }
    } catch (e) {
      setError((e as Error).message);
    }
  }
  const activeJob = job && ["queued", "running"].includes(job.state);
  const summaries = inventory?.summaries ?? {};
  const aggregate = pools.reduce(
    (v, p) => {
      const s = summaries[p.id];
      return {
        nodes: v.nodes + (s?.node_count ?? 0),
        cpu: v.cpu + (s?.cpu ?? 0),
        alloc: v.alloc + (s?.cpu_allocatable ?? 0),
        memory: v.memory + (s?.memory ?? 0),
        memoryAlloc: v.memoryAlloc + (s?.memory_allocatable ?? 0),
        violations: v.violations + (s?.violations ?? 0),
        saved: v.saved + Number(!!p.snapshot_id),
      };
    },
    {
      nodes: 0,
      cpu: 0,
      alloc: 0,
      memory: 0,
      memoryAlloc: 0,
      violations: 0,
      saved: 0,
    },
  );
  const threshold = snapshot?.pool.environment === "production" ? 0.8 : 0.9;
  const exportQuery = {
    ...(selectedCluster
      ? {
          project: selectedCluster.project,
          cluster: selectedCluster.name,
          location: selectedCluster.location,
        }
      : project !== "all"
        ? { project }
        : {}),
  };
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="/">
          <span className="brand-icon">
            <Layers3 size={24} />
          </span>
          OptiPool<span className="brand-dot">.</span>
        </a>
        <div className="workspace">
          <span className="workspace-icon">
            <LayoutGrid size={18} />
          </span>
          <div>
            <strong>Cloud workspace</strong>
            <small>GKE Standard</small>
          </div>
          <ChevronRight size={14} />
        </div>
        <span className="nav-label">WORKSPACE</span>
        <nav aria-label="Main navigation">
          {tabs.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              className={tab === id ? "nav-item active" : "nav-item"}
              onClick={() => setTab(id)}
            >
              <Icon size={19} />
              {label}
              {id === "estimator" && <span className="new">PLAN</span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="saved-mode">
            <Database size={18} />
            <div>
              <strong>Saved data mode</strong>
              <p>Cloud fetches happen on demand.</p>
            </div>
          </div>
          <a
            href="https://github.com/gauravbhainsora/OptiPool"
            target="_blank"
            rel="noreferrer"
          >
            <CircleHelp size={16} />
            Docs & source
            <ArrowUpRight size={14} />
          </a>
          <div className="profile">
            <span>OP</span>
            <div>
              <strong>Shared workspace</strong>
              <small>
                {inventory?.mode === "demo"
                  ? "Local demo"
                  : (inventory?.actor ?? "Connecting…")}
              </small>
            </div>
            <ShieldCheck size={17} />
          </div>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <div className="breadcrumb">
            Workspace
            <ChevronRight size={13} />
            <strong>{tabs.find((t) => t.id === tab)?.label}</strong>
          </div>
          <span className="pill demo">
            <i />
            {inventory?.mode === "live" ? "LIVE COLLECTOR" : "DEMO DATA"}
          </span>
        </header>
        <div className="page-content">
          <div className="page-heading">
            <div>
              <span className="eyebrow">GKE RESOURCE INTELLIGENCE</span>
              <h1>
                {tab === "design"
                  ? "New node pool designer"
                  : tab === "estimator"
                    ? "Capacity planner"
                    : "Your infrastructure, in focus"}
              </h1>
              <p>
                {tab === "estimator"
                  ? "Understand the capacity and cost of your next service."
                  : "One view of your node pools, workloads, and room to grow."}
              </p>
            </div>
            <button
              className="button"
              onClick={() => refresh("inventory")}
              disabled={!!activeJob}
            >
              <RefreshCw size={15} />
              Refresh project inventory
            </button>
          </div>
          {inventory?.mode !== "live" && (
            <div className="demo-banner">
              <Activity size={16} />
              <span>
                <strong>Explore with synthetic data.</strong> Inventory, usage,
                and prices are demo fixtures. No GCP credentials required.
              </span>
            </div>
          )}
          <div className="filters">
            <label>
              Project
              <select
                aria-label="Project"
                value={project}
                onChange={(e) => {
                  setProject(e.target.value);
                  setCluster("all");
                }}
              >
                <option value="all">All projects</option>
                {[...new Set(inventory?.pools.map((p) => p.project))].map(
                  (p) => (
                    <option key={p}>{p}</option>
                  ),
                )}
              </select>
            </label>
            <label>
              Cluster
              <select
                aria-label="Cluster"
                value={cluster}
                onChange={(e) => setCluster(e.target.value)}
              >
                <option value="all">All clusters</option>
                {clusters.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                    {project === "all"
                      ? ` · ${c.project} · ${c.location}`
                      : ` · ${c.location}`}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Selected node pool
              <select
                aria-label="Selected node pool"
                value={poolId}
                onChange={(e) => setPoolId(e.target.value)}
              >
                <option value="__all_pools__" disabled={!selectedCluster}>
                  All node pools
                </option>
                {pools.map((p) => (
                  <option value={p.id} key={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
            <div className="filter-actions">
              <span className="saved-at">
                <Database size={14} />
                {allPoolsSelected
                  ? `Snapshots: ${clusterSnapshot?.sources.length ?? 0} saved pools`
                  : `Snapshot: ${date(snapshot?.saved_at)}`}
              </span>
              <button
                className="button primary"
                disabled={!pool?.available || !!activeJob}
                onClick={() => refresh("pool")}
              >
                <RefreshCw size={15} className={activeJob ? "spin" : ""} />
                {activeJob ? "Fetching…" : "Fetch latest live data"}
              </button>
            </div>
          </div>
          {allPoolsSelected && (
            <p className="help-note">
              All node pools in this cluster are selected. Choose an individual
              pool to fetch live data or estimate capacity.
            </p>
          )}
          {job && (
            <div className={`job-status ${job.state}`} role="status">
              Refresh {job.state}
              {job.state === "succeeded"
                ? " · saved snapshot is ready"
                : job.state === "failed"
                  ? ` · ${job.error}`
                  : " · browsing continues from the last complete snapshot"}
            </div>
          )}
          {error && <Notice>{error}</Notice>}
          {!inventory?.initialized &&
            inventory?.discovery_job?.state === "failed" && (
              <Notice>
                Initial discovery failed: {inventory.discovery_job.error}.
                Refresh project inventory to retry after correcting
                configuration.
              </Notice>
            )}
          {snapshot && Date.now() / 1000 - snapshot.saved_at > 86400 && (
            <Notice>
              This snapshot is over 24 hours old. Estimates use the saved state;
              fetch latest data when you need current evidence.
            </Notice>
          )}
          <div
            className="tabbar"
            role="tablist"
            aria-label="Infrastructure views"
          >
            {tabs.map(({ id, label, icon: Icon }) => (
              <button
                role="tab"
                aria-selected={tab === id}
                key={id}
                className={tab === id ? "active" : ""}
                onClick={() => setTab(id)}
              >
                <Icon size={16} />
                {label}
                {id === "pools" && <span>{pools.length}</span>}
              </button>
            ))}
          </div>
          {tab === "pools" ? (
            <>
              <div className="stats-grid">
                <Stat
                  label="Node pools"
                  value={String(pools.length)}
                  note={`${aggregate.saved} with saved snapshots`}
                  icon={Layers3}
                />
                <Stat
                  label="Observed nodes"
                  value={String(aggregate.nodes)}
                  note="Across your selected scope"
                  icon={Server}
                />
                <Stat
                  label="CPU requests"
                  value={`${aggregate.alloc ? ((aggregate.cpu / aggregate.alloc) * 100).toFixed(0) : "—"}%`}
                  note={`${aggregate.cpu.toFixed(1)} of ${aggregate.alloc.toFixed(1)} allocatable cores`}
                  icon={Activity}
                />
                <Stat
                  label="Memory requests"
                  value={
                    aggregate.memoryAlloc
                      ? `${((aggregate.memory / aggregate.memoryAlloc) * 100).toFixed(0)}%`
                      : "—"
                  }
                  note={
                    aggregate.memoryAlloc
                      ? `${gib(aggregate.memory)} of ${gib(aggregate.memoryAlloc)} allocatable`
                      : "No saved allocatable memory"
                  }
                  icon={MemoryStick}
                />
                <Stat
                  label="Policy violations"
                  value={String(aggregate.violations)}
                  note="Nodes above their request ceiling"
                  icon={ShieldCheck}
                  warning={aggregate.violations > 0}
                />
              </div>
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <h2>
                      Node pools <span className="count">{pools.length}</span>
                    </h2>
                    <p>
                      Saved pool configuration and resource requests. Select a
                      row to inspect.
                    </p>
                  </div>
                  <ExportButtons table="node-pools" query={exportQuery} />
                </div>
                <div className="table-toolbar">
                  <div className="search">
                    <Search size={15} />
                    <input
                      aria-label="Search node pools"
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                      placeholder="Search pools, projects, clusters…"
                    />
                  </div>
                  <span className="muted">
                    Request policy: 80% prod · 90% nonprod
                  </span>
                </div>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Node pool / project</th>
                        <th>Environment</th>
                        <th>Machine / nodes</th>
                        <th>CPU requests</th>
                        <th>Memory requests</th>
                        <th>Autoscaler</th>
                        <th>Snapshot</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {filtered.map((p) => {
                        const s = summaries[p.id];
                        return (
                          <tr
                            key={p.id}
                            className={
                              p.id === poolId || allPoolsSelected
                                ? "selected"
                                : ""
                            }
                          >
                            <td>
                              <button
                                className="pool-link"
                                onClick={() => {
                                  setPoolId(p.id);
                                  setTab("nodes");
                                }}
                              >
                                <span className="pool-glyph">
                                  <Layers3 size={18} />
                                </span>
                                <span>
                                  <strong>{p.name}</strong>
                                  <small>
                                    {p.project} / {p.cluster}
                                  </small>
                                </span>
                              </button>
                            </td>
                            <td>
                              <span
                                className={`pill ${p.environment === "production" ? "production" : "nonprod"}`}
                              >
                                {p.environment === "production"
                                  ? "Production"
                                  : "Non-prod"}
                              </span>
                              {!p.available && (
                                <small className="over">Unavailable</small>
                              )}
                            </td>
                            <td>
                              <strong className="mono">{p.machine_type}</strong>
                              <small>
                                {s?.node_count ?? "Unknown"} nodes ·{" "}
                                {p.location}
                              </small>
                            </td>
                            <td>
                              {s ? (
                                <BudgetBar
                                  requested={s.cpu}
                                  allocatable={s.cpu_allocatable}
                                  cap={
                                    p.environment === "production" ? 0.8 : 0.9
                                  }
                                  unit="cores"
                                />
                              ) : (
                                "Not fetched"
                              )}
                            </td>
                            <td>
                              {s ? (
                                <BudgetBar
                                  requested={s.memory}
                                  allocatable={s.memory_allocatable}
                                  cap={
                                    p.environment === "production" ? 0.8 : 0.9
                                  }
                                  unit="GiB"
                                />
                              ) : (
                                "Not fetched"
                              )}
                            </td>
                            <td>
                              <strong>
                                {p.autoscaler_min}–{p.autoscaler_max}
                              </strong>
                              <small>
                                {p.autoscaling
                                  ? "Autoscaling enabled"
                                  : "Autoscaling disabled"}
                              </small>
                            </td>
                            <td>
                              <span className="snapshot-dot" />
                              {date(p.snapshot_at)}
                            </td>
                            <td>
                              <button
                                aria-label={`Inspect ${p.cluster} ${p.name}`}
                                className="icon-button"
                                onClick={() => {
                                  setPoolId(p.id);
                                  setTab("nodes");
                                }}
                              >
                                <ChevronRight size={17} />
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                {!filtered.length && (
                  <div className="empty">
                    {inventory?.initialized
                      ? "No pools match this scope. Refresh inventory to discover accessible projects."
                      : "Discovering inventory and importing initial snapshots…"}
                  </div>
                )}
                <div className="panel-footer">
                  {filtered.length} pools · all values from saved observations
                  <span>CSV & Excel exports include snapshot provenance</span>
                </div>
              </section>
              {inventory?.errors.map((e) => (
                <Notice key={e.scope}>
                  {e.scope}: {e.error}
                </Notice>
              ))}
            </>
          ) : tab === "design" ? (
            designCluster ? (
              <PoolDesigner
                key={`${designCluster.project}/${designCluster.location}/${designCluster.name}`}
                project={designCluster.project}
                location={designCluster.location}
                cluster={designCluster.name}
              />
            ) : (
              <Notice>
                Select a cluster with saved node profiles to design a new pool.
              </Notice>
            )
          ) : allPoolsSelected ? (
            tab === "estimator" ? (
              <div className="panel empty">
                Select an individual node pool to estimate capacity.
              </div>
            ) : loading && !clusterSnapshot ? (
              <div className="empty">Loading saved cluster snapshots…</div>
            ) : clusterSnapshot ? (
              <ClusterView
                scope={clusterSnapshot}
                tab={tab}
                days={days}
                setDays={setDays}
              />
            ) : (
              <div className="panel empty">
                Select a cluster to view all of its node pools.
              </div>
            )
          ) : loading && !snapshot ? (
            <div className="empty">Loading saved snapshot…</div>
          ) : !snapshot ? (
            <div className="panel empty">
              No saved snapshot. Select an available pool and fetch its data.
            </div>
          ) : tab === "nodes" ? (
            <>
              <div className="section-heading">
                <div>
                  <h2>Nodes in {snapshot.pool.name}</h2>
                  <p>
                    {snapshot.pool.cluster} · {snapshot.nodes.length} nodes ·{" "}
                    {(threshold * 100).toFixed(0)}% request ceiling per node
                  </p>
                </div>
                <span className="pill neutral">
                  {snapshot.pool.machine_type}
                </span>
              </div>
              <section className="panel">
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Node / zone</th>
                        <th>State</th>
                        <th>CPU requests</th>
                        <th>Memory requests</th>
                        <th>Remaining budget</th>
                        <th>Pod slots</th>
                        <th>Details</th>
                      </tr>
                    </thead>
                    <tbody>
                      {snapshot.nodes.map((n) => (
                        <tr key={n.name}>
                          <td>
                            <strong className="mono">{n.name}</strong>
                            <small>{n.zone}</small>
                          </td>
                          <td>
                            <span
                              className={`pill ${n.ready && !n.unschedulable ? "nonprod" : "production"}`}
                            >
                              {!n.ready
                                ? "Not ready"
                                : n.unschedulable
                                  ? "Cordoned"
                                  : "Ready"}
                            </span>
                          </td>
                          <td>
                            <BudgetBar
                              requested={n.requested.cpu}
                              allocatable={n.allocatable.cpu}
                              cap={threshold}
                              unit="cores"
                            />
                          </td>
                          <td>
                            <BudgetBar
                              requested={n.requested.memory}
                              allocatable={n.allocatable.memory}
                              cap={threshold}
                              unit="GiB"
                            />
                          </td>
                          <td>
                            <strong
                              className={
                                n.allocatable.cpu * threshold -
                                  n.requested.cpu <
                                0
                                  ? "over"
                                  : ""
                              }
                            >
                              {cores(
                                n.allocatable.cpu * threshold - n.requested.cpu,
                              )}
                            </strong>
                            <small>
                              {gib(
                                n.allocatable.memory * threshold -
                                  n.requested.memory,
                              )}
                            </small>
                          </td>
                          <td>
                            {n.pod_count} / {n.allocatable.pods}
                          </td>
                          <td>
                            <details>
                              <summary>Labels & taints</summary>
                              <pre>
                                {JSON.stringify(
                                  {
                                    labels: n.labels,
                                    taints: n.taints,
                                    limits: n.limits,
                                  },
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
              </section>
              <div className="help-note">
                <ShieldCheck size={16} />
                Budgets use allocatable CPU and memory requests. Existing Pods
                remain fixed in capacity estimates.
              </div>
            </>
          ) : tab === "workloads" ? (
            <Workloads snapshot={snapshot} days={days} setDays={setDays} />
          ) : (
            <Estimator key={snapshot.id} snapshot={snapshot} />
          )}
          {tab === "pools" && snapshot && (
            <SnapshotCompare key={snapshot.id} snapshot={snapshot} />
          )}
          <footer className="page-footer">
            <span>
              OptiPool <b>v0.2.0</b> · read-only infrastructure planning
            </span>
            <span>
              <Database size={13} />
              Stored observations · explicit refresh
            </span>
          </footer>
        </div>
      </main>
    </div>
  );
}

function Stat({
  label,
  value,
  note,
  icon: Icon,
  warning = false,
}: {
  label: string;
  value: string;
  note: string;
  icon: typeof Boxes;
  warning?: boolean;
}) {
  return (
    <section className="stat">
      <div>
        <span>{label}</span>
        <Icon size={18} />
      </div>
      <strong className={warning ? "over" : ""}>{value}</strong>
      <p>{note}</p>
    </section>
  );
}
function Workloads({
  snapshot,
  days,
  setDays,
}: {
  snapshot: Snapshot;
  days: number;
  setDays: (n: number) => void;
}) {
  const [expanded, setExpanded] = useState<Workload | null>(null);
  return (
    <>
      <div className="section-heading">
        <div>
          <h2>Workloads on {snapshot.pool.name}</h2>
          <p>
            Controller ownership with associated Services · cluster totals shown
            separately.
          </p>
        </div>
        <ExportButtons
          table="workloads"
          query={{ pool_id: snapshot.pool.id, snapshot_id: snapshot.id, days }}
        />
      </div>
      <div className="window-controls">
        <div>
          <strong>Usage lookback</strong>
          <span>Ends at {date(snapshot.usage.cutoff)}</span>
        </div>
        <label htmlFor="window">
          {days} {days === 1 ? "day" : "days"}
        </label>
        <input
          id="window"
          aria-label="Usage lookback days"
          type="range"
          min="1"
          max="10"
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
        />
        <span className="muted">1–10 days</span>
      </div>
      <UsageChart usage={snapshot.usage} />
      <div className="metric-caption">
        <span>
          Highest-replica p99 · CPU and memory maxima calculated independently
        </span>
        <span>
          {snapshot.usage.memory_definition} · {snapshot.usage.coverage}
        </span>
      </div>
      {snapshot.usage.warnings.map((w) => (
        <Notice key={w}>{w}</Notice>
      ))}
      <section className="panel">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Workload / namespace</th>
                <th>Replicas on pool</th>
                <th>Cluster replicas</th>
                <th>Pool requests</th>
                <th>Highest-replica p99 CPU</th>
                <th>Highest-replica p99 memory</th>
                <th>Services</th>
              </tr>
            </thead>
            <tbody>
              {snapshot.workloads.map((w) => {
                const m =
                  w.kind === "Deployment"
                    ? snapshot.usage.workloads[w.id]
                    : undefined;
                return (
                  <tr key={w.id}>
                    <td>
                      <button
                        className="text-button"
                        onClick={() =>
                          setExpanded(expanded?.id === w.id ? null : w)
                        }
                      >
                        {w.name}
                      </button>
                      <small>
                        {w.kind} · {w.namespace}
                      </small>
                    </td>
                    <td>
                      <strong>{w.pool_replicas}</strong>
                    </td>
                    <td>
                      {w.running} running / {w.desired} desired
                      <small>{w.pending} pending</small>
                    </td>
                    <td>
                      <strong>{cores(w.requested.cpu)}</strong>
                      <small>{gib(w.requested.memory)}</small>
                    </td>
                    <td title={m?.cpu_replica ?? undefined}>
                      {w.kind === "Deployment"
                        ? cores(m?.cpu_p99)
                        : "Deployments only"}
                      <small>
                        {w.kind !== "Deployment"
                          ? `Workload type: ${w.kind}`
                          : m
                            ? `${m.replicas_observed} replicas observed · ${m.historical_replicas_observed ?? 0} historical`
                            : "No attributable history"}
                      </small>
                    </td>
                    <td title={m?.memory_replica ?? undefined}>
                      {w.kind === "Deployment"
                        ? gib(m?.memory_p99)
                        : "Deployments only"}
                      <small>
                        {w.kind !== "Deployment"
                          ? "Inspect individual Pod metrics below"
                          : m
                            ? `${m.samples.toLocaleString()} samples`
                            : `Minimum ${snapshot.usage.minimum_samples} samples`}
                      </small>
                    </td>
                    <td>
                      {w.services.length ? (
                        w.services.map((s) => (
                          <span className="service-tag" key={s}>
                            {s}
                          </span>
                        ))
                      ) : (
                        <span className="muted">None associated</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
      {expanded && (
        <section className="panel workload-detail">
          <div className="panel-heading">
            <h3>{expanded.name} · saved Pod specification</h3>
            <button className="button small" onClick={() => setExpanded(null)}>
              Close
            </button>
          </div>
          <p>
            Per replica: {cores(expanded.per_replica.cpu)} ·{" "}
            {gib(expanded.per_replica.memory)}. Pool limits:{" "}
            {cores(expanded.limits.cpu)} · {gib(expanded.limits.memory)}.
          </p>
          <pre>{JSON.stringify(expanded.spec, null, 2)}</pre>
        </section>
      )}
      <RightSizing snapshot={snapshot} />
      <PodTable snapshot={snapshot} />
      <div className="help-note">
        <Activity size={16} />
        Observed p99 helps tune requests. Capacity planning uses requests and
        saved placement rules.
      </div>
    </>
  );
}
