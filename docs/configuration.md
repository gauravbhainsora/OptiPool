# Configuration and cloud collection

Set `OPTIPOOL_CONFIG` to a YAML file. Default: `config.local.yaml`. `OPTIPOOL_MODE`, `OPTIPOOL_AUTH_MODE`, `OPTIPOOL_IAP_AUDIENCE` and `OPTIPOOL_DATABASE` override their respective YAML keys. Keep private config, ADC and SQLite files out of Git. Use separate databases for demo and live modes.

| Setting | Default / behavior |
|---|---|
| `mode` | `demo` (synthetic) or `live` (read-only REST adapters) |
| `auth_mode` | `local` for loopback/private development; `iap` validates signed assertions |
| `iap_audience` | Required with IAP; `/projects/NUMBER/global/backendServices/ID` |
| `database` | `data/optipool.db`; chart enforces `/data/*.db` on its PVC |
| `project_allowlist` | Empty means dynamic discovery of all ACTIVE projects the collector can get |
| `environment` | Project → `project/cluster` → `project/cluster/pool`, most specific wins |
| `default_environment` | `production`; unclassified pools are not silently treated as nonproduction |
| `live_validation_complete` | `false`; production collection is blocked until operator validation |
| `min_metric_samples` | 20 samples per replica/resource before temporal p99 is displayed; not a statistical confidence guarantee |
| `min_reduction_observation_seconds` | 86,400 (24 hours) of represented valid sampling intervals before a request reduction |
| `min_reduction_coverage` | 0.9 selected-window coverage for every observed replica/resource before a reduction |
| `max_added_nodes` | 100; bounded greedy search, configurable up to 500 |
| `max_replicas` | 2,000; steady-state target, not rollout surge or HPA maximum |
| `pricing_mappings` | Exact region/machine/provisioning/disk public SKU mappings; otherwise cost unavailable |

## Local live mode

CLI login and ADC are separate. Use an approved identity and a nonproduction pool. OptiPool does not enumerate your existing gcloud configuration or change cloud resources during demo testing.

```bash
gcloud auth login
gcloud auth application-default login
```

If your organization requires service-account impersonation and grants you that permission:

```bash
gcloud auth application-default login --impersonate-service-account=COLLECTOR_EMAIL
```

Create an ignored config with `mode: live`, a different database (for example `data/live.db`), and explicit nonproduction classification. An empty allowlist discovers accessible projects through [Resource Manager projects.search](https://docs.cloud.google.com/resource-manager/reference/rest/v3/projects/search). Large accounts should restrict discovery with an allowlist during validation. Discovery failures are shown by project; a failed project's previous inventory is preserved.

The collector fetches GKE configuration, verifies the target API TLS certificate using the cluster CA, and reads cluster-wide Kubernetes scheduling context. Required core reads are nodes, Pods, namespaces, Services, Deployments, ReplicaSets, StatefulSets, DaemonSets, Jobs, CronJobs, quotas, LimitRanges, PVs, PVCs and StorageClasses. A missing core permission fails the pool refresh atomically. Mutating admission inspection is attempted; missing or potentially relevant admission context makes estimation conditional.

Endpoints must be reachable from the application. IP API endpoints are supported; DNS-only control-plane endpoints currently need an adapter extension. GKE Autopilot is reported as outside scope. No impersonation of browser users is used in production.

## Permissions

The collector needs `resourcemanager.projects.get` for discovery, GKE cluster read access (`roles/container.viewer` as a starting point), and monitoring read access (`roles/monitoring.viewer`) on each source/scoping project. Kubernetes list/get permissions must cover the resources above, through approved GKE IAM/RBAC. For admission inspection, allow list/get on `mutatingwebhookconfigurations`. Installing the hosting chart grants none of these permissions in remote clusters.

`roles/browser` or parent-level project visibility may widen discoverability; keep grants aligned with the intended project scope. [ADC](https://docs.cloud.google.com/docs/authentication/application-default-credentials), [Workload Identity](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/workload-identity) and [GKE API authentication](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/api-server-authentication) describe the distinct runtime and API requirements.

## Monitoring

GMP uses `sum by(namespace,pod)(rate(container_cpu_usage_seconds_total[5m]))` and working-set memory gauges, scoped by project/location/cluster, queried over ten days with a 300-second step. CPU is cores; memory is bytes. Required cAdvisor series must actually be enabled. Native fallback uses reset-aware `ALIGN_RATE` for CPU core usage time and `ALIGN_MEAN` for non-evictable memory, aligned every 300 seconds. These p99 values describe the saved sampled representation, not instantaneous spikes.

Attribution uses currently observed Pod UID, immutable binding, controller ownership and creation time. Samples before the current lifetime are omitted. Deleted Pods/owners and unavailable history are not guessed. Live coverage remains partial; the highest-replica p99 may be understated when a former replica was removed. No history means unavailable, never zero. Each saved window uses one source and one memory definition.

## Public price mapping

Matching SKU descriptions automatically is unsafe across families, consumption models and disk types. Supply an operator-reviewed mapping key:

`REGION/MACHINE_TYPE/STANDARD_OR_SPOT/DISK_TYPE/DISK_GB`

Each required component specifies `name`, `quantity`, `unit` (Catalog `usageUnit`), `on_demand_sku`, `cud_eligible`, and optionally `cud_3y_sku`, `cud_model: resource-3y`, and `hourly_factor`. For a per-GiB-month disk rate, set `hourly_factor: 0.00136986301369863` (1/730). Price compute CPU and memory or the exact bundled machine SKU, plus the boot disk and any additional configured chargeable components. GPU/local SSD/other configurations need complete mappings; do not omit a component to manufacture a total.

```yaml
pricing_mappings:
  us-central1/n2-standard-4/STANDARD/pd-balanced/100:
    components:
      - name: CPU
        quantity: 4
        unit: h
        on_demand_sku: REPLACE_WITH_VERIFIED_CPU_SKU
        cud_eligible: true
        cud_model: resource-3y
        cud_3y_sku: REPLACE_WITH_VERIFIED_RESOURCE_CUD_CPU_SKU
      - name: Memory
        quantity: 16
        unit: GiBy.h
        on_demand_sku: REPLACE_WITH_VERIFIED_MEMORY_SKU
        cud_eligible: true
        cud_model: resource-3y
        cud_3y_sku: REPLACE_WITH_VERIFIED_RESOURCE_CUD_MEMORY_SKU
      - name: Boot disk
        quantity: 100
        unit: GiBy.mo
        hourly_factor: 0.00136986301369863
        on_demand_sku: REPLACE_WITH_VERIFIED_DISK_SKU
        cud_eligible: false
```

This is a structural example, not verified pricing. SKU IDs/units must match the current [public Billing catalog](https://docs.cloud.google.com/billing/docs/how-to/get-pricing-information-api). Missing/unsupported tiers, units, regions or mappings make prices unavailable. Prices are saved only on explicit pool collection. Spot resources cannot use a resource-based commitment mapping. Existing CUD coverage, negotiation, credits and billed savings are outside scope.

## Request reduction evidence

A sampled p99 may remain visible when reduction evidence is insufficient. CPU and memory gates are independent: sample minimum, represented interval duration and selected-window coverage must all meet policy for every replica. Missing or excluded replicas make the observed workload maximum partial and prevent reductions. Unknown cadence, Pod lifetime or CPU rate-window semantics never imply eligibility. A complete two-hour Pod lifetime is still only two hours of a ten-day metrics window. Represented duration is the union of valid cadence intervals clipped to creation, CPU rate-window eligibility, the selected window and evidenced pool memberships; gaps do not count. Expected counts use each resource’s eligible lifetime/membership interval. Historical ended memberships stop at their saved endpoint.

Legacy GMP and native collector CPU rate definitions are inferred as five minutes and explicitly labelled as inferred; legacy synthetic fixtures use a zero warmup. Other missing definitions remain unknown. The 24-hour/90% defaults are operational policy rather than a statistical confidence guarantee. CPU smoothing, sampled memory peaks and unobserved deleted replicas remain limits. Policy keys participate in the immutable response cache. Combined pool views retain per-pool policy, cutoff and winner provenance; their observations need not be simultaneous. OOM/restart floors, memory peak floors and heterogeneous-template review still apply. Inventory and capacity planning remain available without monitoring. Reads and exports never collect cloud data.
