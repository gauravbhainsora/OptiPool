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
  memory_peak: number | null;
  memory_peak_replica: string | null;
  cpu_evidence?: ResourceEvidence;
  memory_evidence?: ResourceEvidence;
  cpu_p99: number | null;
  memory_p99: number | null;
  cpu_replica: string | null;
  memory_replica: string | null;
  samples: number;
  replicas_observed: number;
  historical_replicas_observed?: number;
  historical_replica_uids?: string[];
};
export type Usage = {
  reduction_policy: {
    minimum_samples: number;
    minimum_observation_seconds: number;
    minimum_coverage: number;
  };
  pods: Record<string, PodMetric>;
  days: number;
  cutoff: number;
  start: number;
  source: string;
  memory_definition: string;
  coverage: string;
  cadence_seconds: number | null;
  cpu_rate_window_seconds: number | null;
  cpu_alignment_window_seconds: number | null;
  query_definition: Record<string, string> | null;
  units: Record<string, string> | null;
  resource_status: { cpu: string; memory: string };
  fallback_reason: string | null;
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
  pool_id?: string;
  pool_name?: string;
  saved_at?: number;
  snapshot_id?: string;
  usage?: PodMetric | null;
  conditions: {
    type: string;
    status: string;
    reason?: string;
    message?: string;
  }[];
  status_available: boolean;
  oom_killed: boolean;
  containers: {
    name: string;
    kind: string;
    requested: Resources;
    limits: Resources;
    status: Record<string, unknown> | null;
  }[];
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
  cud_status?: "available" | "not_applicable" | "unavailable";
  cud_reason?: string | null;
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
  planning?: {
    mode: string;
    steady_replicas: number;
    hpa_replicas: number;
    surge_replicas: number;
    peak_replicas: number;
  };
  confidence?: { status: string; stale: boolean; snapshot_age_seconds: number };
  node_budgets?: NodeBudget[];
  zone_distribution?: Record<string, number>;
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
  per_replica: Resources | null;
  total_requests?: Resources;
  services?: {
    key: string;
    name: string;
    namespace: string;
    replicas: number;
    placed_replicas?: number;
    per_replica: Resources;
    planning: { steady_replicas: number; peak_replicas: number };
  }[];
  cost: Cost;
  placements: {
    replica: string;
    node: string;
    zone: string;
    existing_demand: boolean;
  }[];
};

export type PodMetric = {
  cpu_evidence?: ResourceEvidence;
  memory_evidence?: ResourceEvidence;
  cpu_p99: number | null;
  memory_p99: number | null;
  cpu_latest: number | null;
  memory_latest: number | null;
  cpu_sample_at: number | null;
  memory_sample_at: number | null;
  cpu_coverage: number | null;
  memory_coverage: number | null;
  cpu_samples: number;
  memory_samples: number;
  memory_peak: number | null;
  last_sample_at: number;
};
export type NodeBudget = {
  name: string;
  zone: string;
  planned: boolean;
  before: Resources;
  after: Resources;
  allocatable: Resources;
  ceiling: Resources;
  remaining: Resources;
  placements: string[];
  rejections: string[];
  service_rejections?: Record<string, string[]>;
};
export type Recommendation = {
  cpu_evidence?: ResourceEvidence;
  memory_evidence?: ResourceEvidence;
  reduction_eligible: { cpu: boolean; memory: boolean };
  reduction_reasons: { cpu: string[]; memory: string[] };
  workload_id: string;
  name: string;
  namespace: string;
  current: Resources;
  proposed: { cpu: number | null; memory: number | null };
  recovered: { cpu: number | null; memory: number | null };
  cpu_p99: number | null;
  memory_p99: number | null;
  coverage: number | null;
  pool_replicas: number;
  status: string;
  warnings: string[];
};

export type ResourceEvidence = {
  definition_basis?: string;
  cpu_rate_window_seconds?: number | null;
  valid_samples: number;
  expected_samples: number | null;
  represented_seconds: number | null;
  lifetime_coverage: number | null;
  selected_window_coverage: number | null;
  replica: string | null;
  source: string;
  cadence_seconds: number | null;
  eligible: boolean;
  partial: boolean;
  reasons: string[];
};
export type Comparison = {
  before: { id: string; saved_at: number };
  after: { id: string; saved_at: number };
  delta: { nodes: number; pods: number; cpu: number; memory: number };
  changes: {
    entity: string;
    name: string;
    namespace?: string;
    id: string;
    change: string;
    fields: Record<string, { before: unknown; after: unknown }>;
  }[];
};

export type ScopeSource = Pick<
  Usage,
  | "cadence_seconds"
  | "cpu_rate_window_seconds"
  | "cpu_alignment_window_seconds"
  | "query_definition"
  | "units"
  | "resource_status"
  | "fallback_reason"
> & {
  pool_id: string;
  pool_name: string;
  snapshot_id: string;
  saved_at: number;
  cutoff: number;
  source: string;
  memory_definition: string;
  coverage: string;
};
export type ClusterSnapshot = {
  project: string;
  location: string;
  cluster: string;
  days: number;
  sources: ScopeSource[];
  missing: { pool_id: string; pool_name: string; reason: string }[];
  nodes: (Node & ScopeSource & { environment: string })[];
  pods: (Pod & ScopeSource)[];
  workloads: (Pick<
    Workload,
    | "id"
    | "name"
    | "namespace"
    | "kind"
    | "pool_replicas"
    | "requested"
    | "limits"
    | "services"
  > & {
    pools: (ScopeSource & {
      replicas: number;
      cpu_evidence?: ResourceEvidence;
      memory_evidence?: ResourceEvidence;
    })[];
    cpu_evidence?: ResourceEvidence;
    memory_evidence?: ResourceEvidence;
    cpu_p99: number | null;
    memory_p99: number | null;
    historical_replicas_observed?: number;
    historical_replica_uids?: string[];
    memory_peak: number | null;
    memory_peak_replica: string | null;
    memory_peak_pool: string | null;
    cpu_complete: boolean;
    memory_complete: boolean;
    memory_definitions: string[];
  })[];
};
