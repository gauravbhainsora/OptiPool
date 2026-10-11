export type Resources = { cpu: number; memory: number; pods?: number };
export type Pool = {
  id: string;
  project: string;
  cluster: string;
  name: string;
  environment: string;
  location: string;
  machine_type: string;
  locations: string[];
  available: boolean;
  snapshot_id: string | null;
  snapshot_at: number | null;
  autoscaler_min: number;
  autoscaler_max: number;
  autoscaling: boolean;
  synthetic: boolean;
};
export type Node = {
  name: string;
  zone: string;
  ready: boolean;
  unschedulable: boolean;
  allocatable: Resources;
  requested: Resources;
  limits: Resources;
  pod_count: number;
  labels: Record<string, string>;
  taints: { key: string; value?: string; effect: string }[];
};
export type Workload = {
  id: string;
  name: string;
  namespace: string;
  kind: string;
  desired: number;
  running: number;
  pending: number;
  pool_replicas: number;
  requested: Resources;
  limits: Resources;
  per_replica: Resources;
  services: string[];
  spec: Record<string, unknown>;
};
export type Metric = {
  cpu_p99: number | null;
  memory_p99: number | null;
  cpu_replica: string | null;
  memory_replica: string | null;
  samples: number;
  replicas_observed: number;
};
export type Usage = {
  days: number;
  cutoff: number;
  start: number;
  source: string;
  memory_definition: string;
  coverage: string;
  minimum_samples: number;
  warnings: string[];
  workloads: Record<string, Metric>;
  timeline: { time: number; cpu: number | null; memory: number | null }[];
};
export type Snapshot = {
  pods: Pod[];
  id: string;
  saved_at: number;
  pool: Pool;
  nodes: Node[];
  workloads: Workload[];
  usage: Usage;
  context_warnings: string[];
  pending_demand: number;
};

export type Pod = {
  name: string;
  namespace: string;
  uid: string;
  workload: string;
  node: string | null;
  phase: string;
  created: number | null;
  ready: boolean | null;
  restarts: number;
  requested: Resources;
  limits: Resources;
  labels: Record<string, string>;
  spec: Record<string, unknown>;
};
export type Job = {
  id: string;
  state: string;
  error: string | null;
  scope: string;
};
export type Cost = {
  available: boolean;
  reason?: string;
  source?: string;
  synthetic?: boolean;
  on_demand_hourly?: number;
  on_demand_monthly?: number;
  cud_3y_hourly?: number | null;
  cud_3y_monthly?: number | null;
  commitment_3y_obligation?: number | null;
  assumption?: string;
};
export type Estimate = {
  target_pool?: Pick<
    Pool,
    "id" | "name" | "cluster" | "project" | "environment"
  >;
  id: string;
  snapshot_id: string;
  snapshot_at: number;
  outcome: string;
  reason: string;
  additional_nodes: number | null;
  candidate_nodes?: number;
  permitted_growth?: number;
  exceeds_autoscaler_max?: boolean;
  warnings: string[];
  assumptions: string[];
  replicas: number;
  per_replica: Resources;
  cost: Cost;
  placements: {
    replica: string;
    node: string;
    zone: string;
    existing_demand: boolean;
  }[];
};
