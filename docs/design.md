# OptiPool dashboard design

Product requirements were captured through the design interview. The user authorized implementation with “start working”; implementation and synthetic local verification are now underway. The notice requested before implementation was provided.

The working checkout is `/Users/gaurav/Projects/OptiPool`, with remote `git@github.com:gauravbhainsora/OptiPool.git`. The user explicitly selected this location, overriding the global default of creating new projects under `/Users/gaurav/ProjectIdeas`. This is the authoritative location for subsequent project changes; the earlier interview documents remain preserved in `/Users/gaurav/Projects/NodePoolOptimization`.

## Confirmed requirements

- Dynamically discover accessible GCP projects, each containing clusters and node pools. The user replaced the original four-project configuration with identity-based discovery; an optional allowlist restricts scope.
- Let users select a project, cluster, and node pool.
- Provide node-pool, individual-node, and workload views.
- Add a separate searchable individual-Pod table in the workload view. Export node pools, workloads and Pods to CSV/Excel from saved data with provenance.
- Collect and persist observations initially; subsequent dashboard reads use saved data.
- Fetch live observations only on an explicit user request, updating only the selected pool's data.
- Evaluate a proposed workload's resource requirements and replica count against a selected pool, reporting additional node needs and estimated cost.
- Provide access to everyone inside the organisation, with identical permissions to view data, estimate capacity, and request a pool refresh.
- Fetch cloud data using a service account.
- Publish a refreshed pool snapshot only when collection of its pool details, nodes, and workloads succeeds completely; preserve the previous complete snapshot on failure.
- Allow estimates against older snapshots, showing collection time, age, and a stale-data warning; estimates do not trigger collection.
- Keep existing Pods on their current nodes when evaluating additional workloads.
- Provide a simple CPU/memory-request and replica-count form, plus an advanced Deployment-manifest and target-namespace input. The simple form states its placement assumptions; supported scheduling rules and unsupported cases still need specification.
- A selected-pool refresh may read other cluster resources needed for affinity, storage, and related checks. Save that supporting context with the selected pool's snapshot without replacing other pool snapshots. Missing essential context produces a cannot-fully-assess result.
- Production limits total CPU and memory requests to 80% of each node's allocatable resources, preserving a 20% buffer.
- Non-production limits total CPU and memory requests to 90% of each node's allocatable resources, preserving a 10% buffer.
- A node pool inherits its explicitly configured environment from its project or cluster, with a pool-level override when needed. Environment is not inferred solely from naming conventions.
- Existing nodes above their environment's request ceiling receive no additional proposed Pods. Their violations are shown, and placement may proceed on other eligible nodes without moving existing Pods.
- Account for existing workloads' current desired replicas, including Pending Pods that could compete for the selected pool. Report outstanding demand separately and surface placement uncertainty instead of an unconditional fit.
- Report additional-node requirements and estimated costs even when they exceed the pool's configured autoscaler maximum. Show the permitted growth and required configuration change explicitly; do not change cloud resources.
- Show only highest-replica p99 CPU and memory on each Deployment row, scoped to replicas that ran on the selected pool during the selected window. Compute each replica's temporal p99 over the selected window, then independently take the maximum CPU p99 and maximum memory p99 across observed replicas; the two maxima may come from different replicas. Label the pool scope and incomplete historical attribution. Do not display aggregate Deployment p99.
- Prefer working-set memory when available, with clearly labelled non-evictable memory as fallback. Record the metric source with each snapshot and keep its definition consistent throughout the selected window. Detailed coverage thresholds remain open.
- Each manual pool refresh collects up to ten days of available monitoring history. A 1–10 day slider selects trailing usage data ending at the saved metrics cutoff, reading only the database. Configuration and scheduling estimates remain tied to the selected saved inventory snapshot. The slider controls usage charts and p99; cost estimates remain hourly and monthly, independent of the selected day window.
- Include observed CPU/memory usage when monitoring data is available. Monitoring is optional enrichment; missing metrics must be visible and must not prevent request-based estimates from a complete core snapshot.
- Show on-demand and three-year resource-based CUD cost comparisons, initially in USD with hourly and 730-hour monthly estimates. The CUD scenario assumes a hypothetical commitment fully covering eligible additional resources, using matching public commitment prices with the commitment obligation visible and other components priced separately. It does not assume coverage from existing commitments. Compute flexible CUDs are outside the requested comparison.
- Retain previous pool snapshots and saved estimation results for 30 days. Saved estimates reference their exact snapshot, inputs, pricing, and environment policy.
- Provide an explicit project-inventory refresh that discovers clusters and pools without refreshing existing pool snapshots. New resources are marked not fetched; removed resources are marked unavailable while saved history is retained under the retention policy.
- Use SQLite with a single database-owning application instance on durable storage, serialized writes, and consistent backups. Brief downtime during restarts or maintenance is acceptable.
- Host production in an existing GKE cluster with persistent disk storage and organisation-only sign-in; also provide a local development setup. Workload sizing remains open.
- Return cannot fully assess when custom scheduling, admission behavior, or missing context could change placement and cannot be reproduced from saved observations. Show conditional capacity calculations with explicit unresolved requirements.
- Protect browser access with organisation Google sign-in through IAP. Local gcloud authentication and the production collector's service account remain separate identities and workflows.
- Target 20 simultaneous users, cached views and slider changes within two seconds at p95, and ordinary supported estimates within ten seconds at p95. Validate against twice the initially discovered inventory. These are acceptance targets, not measured results.
- Build and verify the complete application locally, including real collection adapters and representative fixtures, then validate read-only collection against one selected non-production pool before enabling production access.
- Prepare the project for open-source distribution. Before the first code push, provide a versioned Helm chart, complete local setup/testing instructions, reproducible checks, deployment/upgrade/persistence documentation, and contributor-facing documentation.
- The destination repository is `git@github.com:gauravbhainsora/OptiPool.git` (`gauravbhainsora/OptiPool`). Repository inspection and documentation preparation do not start application implementation or publish code.

## Working scope from the first interview round

- Inspection and planning; no infrastructure mutation from the dashboard.
- GKE Standard clusters for the initial release.
- Assess requests and eligible individual-node placement against the saved snapshot; utilization is a separate signal.
- Group workload rows by owning controller, with Kubernetes Services as associated networking resources.
- Initial background collection covers the configured pools.
- Initially estimate added nodes using the existing pool configuration and public pricing, with explicit assumptions.

## Confirmed delivery and access decisions

The user accepted the following closing decisions:

1. Protect browser access with organisation Google sign-in through IAP at the GKE ingress; allow the approved organisation/group to use the same dashboard capabilities. Validate the authenticated identity at the backend. Local gcloud authentication remains a separate development/operations workflow.
2. Target 20 simultaneous users, cached views and slider responses under two seconds at p95, and ordinary supported estimates under ten seconds at p95. Benchmark at twice the initially discovered inventory before production rollout; these are acceptance targets, not measured performance claims. Long collections run asynchronously with visible progress.
3. Build and verify the complete application locally, including real collection adapters and representative fixtures. Then validate read-only collection against a selected non-production pool before production access is enabled.

## Engineering defaults and implementation boundaries

The following defaults make the agreed requirements concrete. Implementation uses a bounded conservative simulator; the detailed support matrix is maintained in [estimation.md](estimation.md). Live acceptance remains required.

- Duplicate refresh requests for the same pool attach to its active job. Use bounded collection concurrency and serialize SQLite write transactions. Cloud/network collection occurs outside write transactions; stage results before atomic publication.
- Retain the latest successful snapshot for each pool even when older than 30 days. Expire older history after 30 days only when no retained saved estimate needs it. Pin the inventory, metric source/query definition, observations or sufficient reproducible metric summaries, prices, and policy needed by a retained estimate.
- Never treat missing metrics as zero. Show actual coverage and available duration when less than the requested window exists; show unavailable p99 where there is no meaningful evidence. Use a documented configurable minimum sample count, and do not imply that any sample threshold guarantees percentile accuracy.
- Attribute observations by project, location, cluster, namespace, workload identity, and replica identity wherever available. Pool membership is evaluated over observed history. Mark unknown ownership or historical pool membership explicitly; do not fabricate historical inventory from current objects.
- The entered replica count describes the new workload's steady-state target. Existing desired replicas and competing pending demand are included. Do not silently substitute an HPA maximum, assume preemption, or rearrange running Pods. Rollout-surge or failure-resilience scenarios are separate future scope unless explicitly requested.
- Evaluate resource requests and known overhead, node readiness/cordons, Pod slots, selectors, taints/tolerations, affinity/anti-affinity, topology constraints, known storage topology, and captured relevant quotas. Unsupported resource types, unmodelled scheduler/admission behavior, or unresolved storage provisioning produce conditional results or cannot fully assess.
- Search added nodes using the selected pool's saved configuration and eligible locations, including expected system/DaemonSet demand. Distinguish a feasible placement found from a proven minimum; exhausted search must not be reported as proof that no placement exists.
- Refresh prices as part of an explicit collection, persist their source and timestamp, and never invent a missing SKU/rate. Missing price data makes cost unavailable without suppressing an otherwise valid capacity result.
- Use health/readiness checks, structured logs, refresh/estimate audit records, durable job status, consistent off-volume backups, and a restore test. An interrupted job must not publish partial observations.
- Measure initial node/Pod/series counts and refresh concurrency before sizing disk, memory, retention representation, and the supported simulation bound. Avoid duplicating identical ten-day histories for every refresh while preserving reproducibility.

Implementation note: v0.1 compresses complete metrics with each snapshot and does not yet deduplicate repeated ten-day histories. The sizing/retention gate must account for this explicitly. Exact live public SKU mappings are operator-reviewed; missing mappings yield unavailable costs. Deleted-Pod historical ownership is labelled partial rather than inferred.

## Design tree

- Shared access and collection identity
  - Settled: service-account collection.
  - Settled: internal audience and identical dashboard permissions.
  - Settled: existing GKE cluster for hosting, with organisation-only access and a local development setup.
  - Settled: organisation Google sign-in through IAP. The user's gcloud authentication workflow is separate from production service-account collection and browser-user authentication.
  - Downstream: runtime credentials, project IAM, Kubernetes permissions, cluster connectivity.
- Saved observations and refresh
  - Settled: explicit refresh scoped to a selected pool.
  - Settled: publish complete snapshots only; preserve old data on failure; allow estimates with visible collection time and age.
  - Settled: 30-day snapshot/estimate history and an explicit inventory-discovery action.
  - Settled: collect available ten-day history on manual refresh; the slider reads saved metrics with its window anchored to the saved cutoff.
  - Open: metrics coverage and behavior when less than the selected duration is available.
  - Settled: collect and attach supporting cluster context to the selected pool snapshot; other pool snapshots remain unchanged.
  - Downstream: historical workload attribution, concurrent refreshes, handling history required by retained estimates.
- Capacity estimation
  - Working scope: per-node placement using requested resources.
  - Settled: existing Pods remain on their current nodes.
  - Settled: simple request/replica form and advanced Deployment-manifest/namespace input.
  - Settled: unresolved/custom scheduling or admission effects produce cannot fully assess, with conditional calculations labelled.
  - Open: detailed supported placement-rule set.
  - Settled: per-node CPU and memory request ceilings are 80% of allocatable in production and 90% in non-production.
  - Settled: explicit environment configuration with project/cluster defaults and pool-level overrides.
  - Settled: exclude over-ceiling nodes from new placement, retain existing Pods, and report existing violations.
  - Settled: include competing outstanding demand from existing desired replicas; report ambiguity.
  - Settled: show required added nodes and cost alongside configured growth restrictions.
  - Downstream: scheduling constraints, node health, rollout surge, unsupported scenarios.
- Cost estimation
  - Settled: compare on-demand with three-year resource-based CUD pricing, in USD, hourly and with a 730-hour monthly estimate.
  - Working scope: existing pool configuration, public prices, and boot disks; show price timestamp and assumptions.
  - Settled: hourly/monthly costs do not change their presentation period with the usage-window slider.
  - Settled: hypothetical full eligible coverage under a new resource-based commitment, matching public prices, with commitment obligation shown.
  - Downstream: pricing refresh policy, zone distribution, provisioning model and disk charges.
- Production operation
  - Settled: pool/node/workload views, including p99 CPU and memory and optional observed-usage data.
  - Settled: display only highest-replica CPU and memory p99 on Deployment rows, independently calculated over the selected metrics window.
  - Settled: selected-pool replica scope; prefer working-set memory, with labelled non-evictable fallback and a consistent source throughout each window.
  - Open: data-coverage rules.
  - Settled: SQLite, a single database-owning instance, durable storage, queued writes, and brief maintenance/restart downtime.
  - Settled: existing GKE cluster with persistent storage and a local development setup.
  - Settled: 20 simultaneous users, cached interactions within two seconds and ordinary estimates within ten seconds at p95, tested against twice the initial inventory.
  - Deployment inputs still needed: actual inventory size, project IDs, hosting cluster, service-account identity, approved organisation/group, domain, and network paths. These are configuration/discovery inputs rather than demonstrated capabilities.
  - Downstream: observability, audit records, acceptance criteria.

## Dashboard fields

| View | Initial fields |
|---|---|
| Node pools | Project, cluster, environment, locations, machine configuration, node count, autoscaling bounds, aggregate CPU/memory requests and allocatable capacity, policy violations, snapshot age |
| Nodes | Name, zone, readiness, schedulability, allocatable CPU/memory, requests, limits, remaining request budget, Pod count, labels and taints |
| Workloads | Namespace, controller kind/name, associated Services, desired/running/pending replicas, replicas on selected pool, per-replica and total requests/limits, placement rules |

Clearly distinguish cluster-wide workload totals from the portion on the selected pool. Deployment rows show only highest-replica CPU and memory p99 for replicas that ran on the selected pool during the selected metrics window; do not show aggregate Deployment p99. Historical attribution gaps must be labelled. Prefer working-set memory with a clearly labelled non-evictable fallback, consistently applied throughout each window. Detailed coverage thresholds remain open. Usage charts may be shown where metric data and attribution are available.

## Planned data sources and collection flow

| Data | Source |
|---|---|
| Project/cluster/node-pool configuration | GKE API |
| Nodes, Pods, Deployments, ReplicaSets, other controllers, Services, requests/limits, placement rules, and related scheduling context | Each cluster's Kubernetes API |
| Historical CPU and memory usage | GMP Prometheus query API where required series are available; native GKE Cloud Monitoring metrics as an explicitly labelled fallback |
| On-demand and resource-based CUD comparison prices | Matching public Google Cloud pricing data |

Follow Pod owner references through ReplicaSets to Deployments; use Service selectors to associate networking resources without treating them as workload owners. Join metric series to workload and historical pool identity where evidence exists; label missing historical attribution rather than assigning old samples using an unsupported guess.

During an explicit pool refresh, collect core inventory and supporting context, query up to ten days of available monitoring history, and persist observations to SQLite under the agreed snapshot-publication rules. Subsequent browsing, slider changes, and estimates read saved data. GMP's upstream scraping continues independently; it does not automatically refresh this application's database.

GMP's [Prometheus range-query API](https://docs.cloud.google.com/monitoring/api/ref_v3/rest/v1/projects.location.prometheus.api.v1/query_range) supplies time series. When enabled, the [managed cAdvisor package](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/cadvisor-kubelet-metrics) includes a CPU counter and working-set memory gauge. Verify metric availability instead of assuming GMP enablement includes all needed series. Compute reset-aware CPU rates, and keep source semantics consistent within each saved window.

The production service account requires both monitoring read access and read/list authorization for the relevant Kubernetes resources, plus reachable cluster API endpoints. Local gcloud authentication, runtime service-account identity, and organisation-only browser access are separate concerns.

## Metric and pricing facts informing open decisions

- [Native GKE metric definitions](https://docs.cloud.google.com/monitoring/api/metrics_kubernetes): CPU core usage time is cumulative and must be converted to a reset-aware rate before evaluating CPU usage percentiles. Native memory used bytes distinguishes evictable and non-evictable memory; neither should silently be renamed working set.
- [Managed cAdvisor metrics](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/cadvisor-kubelet-metrics) can expose working-set memory when configured. Show the actual metric source, units, cadence, and coverage.
- [Monitoring retention](https://docs.cloud.google.com/monitoring/quotas#data_retention) supports a ten-day lookback when the relevant metrics were collected. Available history and sampling resolution must be checked; absent samples are not zero usage.
- Percentiles over time and percentiles across replicas are different calculations. For node/pool total usage, align and aggregate usage at each timestamp before computing the temporal percentile. Do not sum individual p99 values and call the sum aggregate p99. See [Monitoring aggregation](https://docs.cloud.google.com/monitoring/api/v3/aggregation).
- Historical configuration and workload ownership cannot be reconstructed reliably from a current inventory alone. Expose missing historical attribution or snapshots rather than inventing them.
- [Compute Engine CUDs](https://docs.cloud.google.com/compute/docs/instances/committed-use-discounts-overview) include resource-based and Compute flexible models, with different eligibility and rates. Commitment charges persist through underutilization; public CUD scenario prices are not evidence of an account's actual incremental bill or unused commitment coverage.
- Price eligible components under their matching commitment model; price boot disks separately. Do not apply a universal CUD percentage to the entire node cost. [Compute pricing tables](https://cloud.google.com/products/compute/pricing/general-purpose) expose different consumption models.

## Request-capacity policy

For each resource independently (CPU and memory):

`policy ceiling = node allocatable resource × environment factor`

`remaining request budget = policy ceiling − existing effective Pod requests`

The environment factor is 0.80 for production and 0.90 for non-production. Placement of a proposed Pod must fit both remaining budgets as well as the applicable scheduling constraints. The policy measures requested resources, not observed usage or configured resource limits. Negative budgets identify existing policy violations: those nodes receive no additional proposed Pods, and the estimate visibly reports their existing violations while considering other eligible nodes.

Existing outstanding demand is evaluated before declaring capacity available for the proposed workload. A workload that can use multiple pools or whose placement cannot be resolved must not silently be assigned to this pool or ignored; report the assumption or uncertainty. Additional-node estimates distinguish required capacity from capacity allowed by the current pool configuration.

## Proposed acceptance checks

- Initial collection populates configured resources and reports collection failures by scope. After collection, browsing and slider changes make no cloud data requests.
- Refreshing pool A publishes a new complete snapshot for A and its supporting context while preserving pool B's saved observations. Core collection failure or an interrupted job preserves the previous successful snapshot.
- The slider selects one to ten days ending at the saved metrics cutoff. Fixtures verify independent highest-replica CPU and memory p99, selected-pool attribution, replica replacement, source consistency, and missing-data handling. Costs remain hourly/monthly when the slider changes.
- Scheduling fixtures verify the 80%/90% CPU and memory ceilings, fragmentation, existing violations, pending demand without double counting, applicable DaemonSet overhead on added nodes, known placement constraints, and explicit uncertainty for unsupported behavior.
- Added-node results show a feasible placement under stated assumptions, required growth, configured growth restrictions, and the source snapshot. Search exhaustion never masquerades as proof of impossibility or a guaranteed minimum.
- Pricing fixtures verify matched public on-demand and three-year resource-based CUD rates, separate component eligibility, hourly/730-hour monthly conversion, and visible missing prices and commitment assumptions.
- SQLite checks exercise concurrent reads, serialized writes, restart persistence, atomic publication, consistent backup, and restoration. Metrics volume and retention storage are measured before production rollout.
- Production browser access validates the IAP identity. Collection uses the service account with appropriate project and cluster read permissions; saved-data viewing does not require a viewer's personal gcloud login.
- Validate the full collection-to-dashboard-to-estimate flow on one non-production pool, then run the agreed performance benchmark before enabling production access.
- Complete the open-source and versioned Helm release checks in [release-readiness.md](./release-readiness.md) before the first code push.
