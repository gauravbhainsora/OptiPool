# OptiPool

**Understand GKE capacity before deploying your next service.** OptiPool saves node-pool observations in SQLite, makes requests and usage visible, and estimates placement and incremental node cost without changing infrastructure.

The local demo works without Google Cloud credentials. This first release includes real read-only collectors; a service account and a nonproduction validation are required before production rollout.

![Dashboard](docs/dashboard-desktop.png)

See the [architecture diagram](docs/architecture.md) for collection, persistence and estimation boundaries.

The self-contained [architecture and build plan](docs/BUILD_PLAN.md) records requirements, implementation status, verification, release details and remaining work for sharing with another AI or engineer. Version 0.2.0 adds analytics and loading optimizations; version 0.1.0 retains its original artifacts. See the plan for publication and acceptance status.

For another AI to build or extend the complete product, use the self-contained [A–Z implementation prompt](docs/IMPLEMENTATION_PROMPT.md). It includes feature contracts, architecture, implementation phases, tests and deployment/release criteria.

## Run locally

Prerequisites: Python 3.13+, Node.js 22+, npm. Helm 3.17.3, Docker, kubectl and Kind 0.27.0 are needed for deployment tests.

```bash
git clone git@github.com:gauravbhainsora/OptiPool.git
cd OptiPool
bash scripts/dev.sh
```

Open **http://127.0.0.1:8000**. On the first launch, eight synthetic pools across four projects are imported. Later launches reuse `data/optipool.db`. Stop the server with Ctrl+C. The demo inventory, observations, and prices are labelled synthetic.

For development with frontend hot reloading, keep the API running and use `npm --prefix frontend run dev` in a second terminal, then open http://127.0.0.1:5173.

## Dashboard

| View | What it shows |
|---|---|
| Node pools | Project/cluster/pool selection, environment, machine configuration, autoscaler bounds, CPU/memory request totals, policy violations, snapshot time and saved-snapshot comparisons |
| Nodes | Readiness, cordons, allocatable CPU/memory, requests, configured limits, remaining request budgets, Pod slots, labels and taints |
| Workloads | Controller ownership, Services, replica counts, highest-replica p99 and advisory request proposals with headroom/coverage; per-Pod latest saved usage/p99, container requests/limits, conditions and available OOM evidence |
| Capacity planner | Up to 20 services assessed together, each with requests/replicas or Deployment YAML; steady/HPA/rollout envelopes, zone spread, before/after node budgets, placement explanations, growth limits and saved cost scenarios |

Node-pool, workload and Pod tables export **CSV and Excel**, with snapshot provenance. Workload and Pod usage exports follow the selected window and displayed snapshot. No export initiates a cloud fetch.

Choose a cluster and **All node pools** to combine its saved Nodes, Workloads and individual Pods. Capture times and metric cutoffs remain explicit per pool. Cluster workload/Pod CSV and Excel exports pin the displayed snapshots. Select an individual pool for live refresh, recommendations, comparisons and capacity planning. These selection changes are verified and pushed to main; they are not included in the 0.2.0 release.

Choose **Selected node pool** before estimating. The result names the target pool, cluster and project. The planner places proposed Pods only on that pool or new nodes using its saved configuration; it does not choose another pool automatically.

The 1–10 day slider ends at the saved metrics cutoff. Deployment CPU and memory p99 are independently the highest temporal replica p99, with missing data and historical attribution gaps exposed. Costs use hourly and 730-hour monthly periods regardless of the slider.

The **New node pool** tab designs an empty proposed pool for a service bundle using up to 10 observed configurations saved in the selected cluster. It compares required nodes and saved prices, shows assumptions and placement, and offers JSON download and saved history. The comparison covers saved profiles rather than the full GCP machine catalog. Provision the reviewed configuration outside OptiPool.

## Saved-data contract

Initial import collects discovered pools once. After that, browsing and estimation read SQLite. **Fetch latest live data** updates only the selected pool. **Refresh project inventory** discovers accessible projects, clusters and pools without replacing existing pool snapshots; new pools need an explicit fetch. Failed core collection preserves the last complete snapshot. Monitoring and prices are optional enrichment, with failures visible.

Dynamic live project discovery uses the collector's accessible projects, with an optional allowlist. Production and nonproduction classification is explicit configuration. Requests may use at most **80% of each production node's allocatable CPU and memory**, or **90% on nonproduction nodes**. These are request ceilings, independently enforced for both resources.

## Verify and deploy

```bash
bash scripts/check.sh
bash scripts/kind-test.sh
```

The second command builds the image and installs the packaged chart in its own disposable Kind cluster. It checks HTTP flows, Helm tests, restart persistence, chart upgrades and retained storage, then removes only its own cluster. It requires a running Docker engine. These tests use no GCP credentials.

Deployment uses [charts/optipool](charts/optipool), version **0.2.0**, app version **0.2.0**. SQLite has one database-owning process and one replica on a durable block volume. The chart enforces this and uses Recreate updates. Defaults are a private demo; public ingress requires signed IAP authentication.

Pull the published chart without cloning the source:

```bash
helm repo add optipool https://raw.githubusercontent.com/gauravbhainsora/OptiPool/main/docs/helm
helm repo update
helm pull optipool/optipool --version 0.2.0
```

The public container image is `ghcr.io/gauravbhainsora/optipool:0.2.0`, available for Linux AMD64 and ARM64. The [0.2.0 release](https://github.com/gauravbhainsora/OptiPool/releases/tag/v0.2.0) includes the chart, checksum and exact image digest. See the [deployment guide](docs/deployment.md) for installation and production prerequisites.

Read the [local testing guide](docs/testing.md), [configuration and live collector guide](docs/configuration.md), [GKE deployment guide](docs/deployment.md), [backup/restore guide](docs/operations.md), [scheduling support matrix](docs/estimation.md), and [verification evidence](docs/verification.md).

## Scope and limitations

GKE Standard is supported. This is a conservative simulator, not the Kubernetes scheduler. Node selectors, required node affinity, taints/tolerations, basic hard Pod affinity/anti-affinity, hard topology spread, Pod slots, effective requests, existing outstanding demand and simple namespace quotas are modeled. Storage binding, dynamic label keys, custom scheduling, admission effects and other unsupported features produce **Cannot fully assess**. Search is bounded; a found placement does not prove a minimum node count. HPA and surge inputs model additional peak demand; full rollout sequencing and failures are outside scope. Request proposals require review; per-container usage and CPU throttling history remain unavailable.

Live p99 covers surviving Pods within their current lifetime; deleted-replica history is not reconstructed. Current source/cadence and partial coverage are labelled. Live pricing requires an exact reviewed public SKU mapping, rather than guessed discounts. Missing prices do not prevent capacity assessment. CUD cost is a hypothetical new fully covered three-year resource commitment, not existing account savings.

Production readiness also needs real nonproduction collection validation, IAP/Workload Identity/network checks, exact pricing mappings, backup/restore validation and benchmarking at twice your actual inventory. Synthetic tests cannot establish these.

Apache 2.0 · [License](LICENSE) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [Changelog](CHANGELOG.md)

Saved risk evidence can gate advisory request reductions independently of usage coverage. By default `require_cpu_risk_evidence` and `require_memory_risk_evidence` are true; legacy snapshots remain readable, with unknown risk evidence withholding reductions. An operator may explicitly disable either requirement, which is shown as an opt-out. Risk does not block inventory, request-based capacity estimates or recommendations to increase requests.

Set `collect_risk_metrics: true` to read existing GMP counters during explicit pool refreshes. This does not enable metrics or change cloud/scrape configuration. CPU uses raw `container_cpu_cfs_throttled_periods_total` and `container_cpu_cfs_periods_total`: reset-aware increases are calculated within each saved container/source series, paired over matching intervals, then counts are summed. The denominator is elapsed enforcement periods; absent or zero denominators are unknown. The operational default `throttling_risk_threshold: 0.10` withholds CPU reductions if any eligible container meets or exceeds it, even if the displayed count-weighted workload ratio is lower. Percentages are never summed. Risk minimums default to 24 represented hours and 90% of the selected window (`min_risk_observation_seconds`, `min_risk_coverage`); these are configurable operating policies, not statistical guarantees.

Memory uses UID-scoped `kube_pod_container_status_restarts_total` where available and an optional configured `risk_oom_counter_metric`. The OOM source must already exist in GMP and expose `namespace`, `pod`, `uid`, `container`, project/location/cluster labels; its cumulative count must span the Pod UID/container lifetime across container restarts. Do not configure a last-termination gauge or generic memory-allocation-failure counter as an OOM counter. Without a compatible source, OOM history is unknown. Any observed OOM/restart increase withholds memory reductions. Captured Kubernetes current/last termination and restart status remains an additional conservative guard, never a claim of complete historical event coverage.

Eligible risk containers are ordinary containers plus restartable init sidecars. One-shot init histories are disclosed as incomplete. Counter intervals are clipped to the saved metrics window and evidenced Pod/pool lifetime; gaps longer than 1.5 evaluation cadences do not count as represented time. Counter resets contribute the observed post-reset value, a lower bound; events lost between samples are not reconstructed. API results, workload/Pod/recommendation details and CSV/Excel exports show source, counts, ratio, policy, coverage and limitations. Demo counters are explicitly synthetic. The [GKE managed cAdvisor metric definitions](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/cadvisor-kubelet-metrics) document the throttled and elapsed enforcement-period counters; [kube-state-metrics Pod definitions](https://github.com/kubernetes/kube-state-metrics/blob/main/docs/metrics/workload/pod-metrics.md) document restart counters and UID attribution. Actual source availability and live acceptance remain operator prerequisites.
