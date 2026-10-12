# Existing historical metadata source

Historical discovery is disabled by default. The operator may configure `historical_metadata_metric` with the name of an **existing** Prometheus-compatible metric accessible through the selected project's GMP query API. OptiPool performs GETs only, using the collector service account's existing Monitoring read permissions. It does not install exporters, recording rules, joined pipelines, or scrape configuration. The backend verifies returned labels and interval assertions during initial import or explicit selected-pool refresh; saved reads never query this source.

GMP/cAdvisor enablement alone does not establish this contract. Raw kube-state-metrics owner names lack top-controller UID proof through ReplicaSets, and current node labels do not prove past placement. A separately maintained historical pipeline must supply the joined identity and temporal evidence below. Operators must validate it against known deleted Pods, rollouts and pool transitions before relying on it. Synthetic tests validate OptiPool's adapter, not the existence or correctness of that pipeline in GCP.

## optipool-membership-v1 contract

Each `historical_metadata_metric` matrix series is a gauge of value `1`, with all of these **nonempty string labels**:

| Labels | Meaning |
| --- | --- |
| `project_id`, `location`, `cluster` | Exact GKE cluster identity |
| `namespace`, `pod`, `uid` | Pod name and immutable Kubernetes Pod UID |
| `controller_kind`, `controller_name`, `controller_uid` | Top owning controller and immutable UID |
| `owner_kind`, `owner_name`, `owner_uid` | Immediate owning controller and immutable UID |
| `node`, `node_uid`, `node_pool` | Node name, immutable node UID and pool name during the interval |
| `created` | Pod creation Unix timestamp in seconds |
| `start`, `end` | Inclusive proven membership interval, Unix seconds |

The pipeline asserts that the Pod UID continuously existed with this ownership and node/pool identity throughout `[start,end]`. It emits the assertion **after** that interval is established (`end <= metadata observation timestamp`), and never bridges evidence gaps or changes of identity. A point at a scrape time is not enough to invent a ten-day interval. Closed intervals at transitions must not overlap; leave unknown transition times uncovered. Preserve separate intervals across evidence gaps. Controller and node names may be reused; their UIDs must never be substituted.

The immediate owner must either match the top controller in kind, name and UID, or be a ReplicaSet with its own distinct UID joined to a Deployment's UID. A raw owner-name join cannot establish that proof. The upstream interval assertion must certify the full owner chain, including ReplicaSet lifetime. Unsupported chains, conflicting UID identities, overlapping same-name lifetimes or conflicting node mappings are excluded with saved reasons.

Example exposition (illustrative existing source, not an installation recipe):

```text
optipool_pod_membership{project_id="example-dev-project",location="us-central1",cluster="example-cluster",namespace="shop",pod="api-old",uid="pod-uid-1",controller_kind="Deployment",controller_name="api",controller_uid="deployment-uid-1",owner_kind="ReplicaSet",owner_name="api-old-rs",owner_uid="replicaset-uid-1",node="node-old",node_uid="node-uid-1",node_pool="services",created="1791750000",start="1791750300",end="1791760000"} 1
```

The timestamp on that metadata observation must be at least `1791760000`. The API must retain the series inside the configured lookback; an assertion not sampled by the metadata query is missing evidence. Historical usage comes from `container_cpu_usage_seconds_total` and `container_memory_working_set_bytes` at that same project's GMP endpoint. Usage queries are scoped to exact project/location/cluster/namespace/Pod and bounded to each proven membership interval. Standard usage without UID/node labels remains supported because Kubernetes enforces namespace/name exclusivity during a proven Pod lifetime. When usage does carry `uid`, `node` or `node_uid`, mismatches are rejected. The query preserves those optional labels so different identities cannot be silently summed together. Multiple same-time result series are ambiguous and fail the historical candidate.

CPU uses rate-before-container-sum over five minutes; an evaluation at `t` is accepted only if the entire `[t-300,t]` lies inside the proven lifetime and membership interval. Memory is sampled working set at `t`. Historical GMP samples are never mixed into a selected native non-evictable memory source. Existing current metrics and retained compatible snapshots remain usable if optional discovery or historical queries fail.

## Configuration and limits

```yaml
historical_metadata_metric: optipool_pod_membership
historical_metadata_step_seconds: 300
historical_metadata_lookback_days: 10
historical_metadata_max_replicas: 200
historical_metadata_max_requests: 400
```

Only a metric identifier is accepted, never arbitrary PromQL. Metadata evaluation step is 60–300 seconds; lookback is 1–10 days. Usage follows immutable `metric_cadence_seconds` (60 or 300) and the five-minute CPU definition. Maximum replicas is 1–1,000; historical usage request budget is 2–2,000. The adapter rejects a candidate before usage requests when twice its accepted membership intervals exceeds the budget. Metadata is limited to 20 times the replica setting in response series; each series has at most 15,000 points, with a 200,000 combined metadata/usage point limit. Exceeded limits, incomplete query responses or parsing errors produce saved unavailable reasons and do not publish a partial usage candidate. Existing HTTP concurrency, timeouts and read-only permissions apply.

Saved API, selected-pool/combined-pool dashboards and CSV/XLSX report discovery status, source metric, discovered replica count and reasons. Current running/requested replica counts remain inventory-based. Discovered historical replicas are counted separately and can independently win CPU or memory p99. Valid discovered identities remain expected replicas even when usage is missing or incompatible. Known exclusions carry workload/UID/resource attribution details so missing memory does not suppress independently supported CPU. Unknown discovery outages remain global gaps. Any missing/ambiguous metadata, unsupported ownership, foreign scope, missing usage, sampling gap or unknown coverage remains partial/unavailable; finding one interval never establishes complete workload history. Published snapshots own the evidence and samples, so pruning older snapshots, consistent backups and restarts do not change pinned results.
