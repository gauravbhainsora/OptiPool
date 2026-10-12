# Capacity and cost assessment

The user selects a pool. Each saved estimate pins that pool's snapshot, inputs, policy, context and price data. Proposed Pods are placed on individual eligible nodes in that pool, or planned nodes with its saved shape. Existing Pods stay fixed.

For CPU and memory independently:

`remaining budget = allocatable × (0.8 production / 0.9 nonproduction) − existing effective requests`

Effective requests sum app containers, account for restartable init sidecars and the init peak, then include Pod overhead. Limit-only containers inherit their limit as a missing request. Observed p99 is not subtracted from capacity. Nodes already violating either ceiling get no new Pods. Current limits are displayed separately and are not request budgets.

## Support matrix

| Constraint | v0.2.0 behavior |
|---|---|
| CPU, memory, Pod slots | Checked per eligible node |
| Readiness and cordons | Unready/cordoned existing nodes excluded |
| Node selectors and required node affinity | Supported label/metadata.name expressions |
| NoSchedule/NoExecute taints | Required tolerations checked; PreferNoSchedule is a preference |
| Basic hard Pod affinity/anti-affinity | Saved cluster context + proposed replicas; namespace lists, selectors and topology labels; existing anti-affinity honored |
| Preferred affinity | Preference omitted; feasibility does not guarantee scheduler scoring or selected node |
| Namespace selectors/dynamic matchLabelKeys | Cannot fully assess |
| Hard topology spread | Saved cluster context, proposed Pods and domain inclusion policies; dynamic label keys remain conditional |
| Soft topology spread | Scheduler scoring omitted |
| Bound/dynamic storage and CSI volumes | Cannot fully assess; binding, attachment and provisioner are not reproduced |
| Custom scheduler/RuntimeClass/DRA | Cannot fully assess |
| GPU, extended resources, ephemeral-storage, host ports | Cannot fully assess |
| Basic requests CPU/memory and Pod quotas | Blocking check against saved used/hard values |
| LimitRange/scoped/additional quotas | Cannot fully assess |
| Mutating admission/injected sidecars | Cannot fully assess when potentially relevant or unavailable |
| HPA maximum and rollout surge | Explicit additional-demand envelope; percentage surge rounds up; peak is bounded |
| Failures, rollout sequencing, terminating Pods, preemption | Outside scenario scope |

Pending Pods constrained to this pool are placed before the proposed workload. Desired controller replicas not materialized as Pods are accounted separately without double counting. Competing demand that can use multiple pools is flagged as uncertain rather than silently assigned or ignored.

New node prototypes use conservative observed allocatable capacity for the pool and saved DaemonSet/system overhead. Empty pools without a verified allocatable prototype cannot provide a confident growth estimate. Autoscaler bounds are shown separately from required growth; a pool with autoscaling disabled has zero automatic permitted growth.

The algorithm tries bounded greedy placements. A successful assignment is feasible under these assumptions, not a guaranteed minimum or a promise about scheduler scoring. Search exhaustion or a failed arrangement involving placement interactions returns Cannot fully assess. An intrinsic resource shape/selector contradiction or an explicit quota violation can block placement. Adding more small nodes cannot accommodate a single Pod larger than every node's request budget.

Steady mode uses the entered replica count. HPA mode uses an explicit maximum at least that count. Rollout mode adds integer or rounded-up percentage surge; combined mode adds surge to the HPA maximum. These are planning overrides for an additional service while existing Pods stay fixed, not a simulation of replacing an existing Deployment or automatic reading of its HPA/rollout configuration. Node cards show baseline and simulated requests, remaining ceilings, assignments, zone counts and reasons another proposed Pod cannot fit. Snapshot freshness and conditional evidence remain visible.

Request recommendations use the selected saved window, independently highest-replica p99, configurable usage headroom and a sampled memory-peak floor. OOM/restart evidence prevents memory reductions; heterogeneous requests require review; missing/sparse evidence withholds reductions independently per resource. Reduction defaults require 20 valid samples, 24 hours represented and 90% selected-window coverage for every replica; these are configurable operational policy, not statistical confidence guarantees. Capacity deltas use actual selected replica requests. They do not establish monetary savings or produce per-container resource changes. Saved termination evidence covers captured current/last states, not complete historical OOM events; CPU throttling history is unavailable.

## Cost interpretation

On-demand and three-year resource-CUD totals use saved matching USD prices, with components priced separately. Monthly values assume 730 hours. The commitment obligation is the covered eligible hourly price × 24 × 365 × 3; disks and other on-demand-only components are outside that obligation. Partial/missing commitment pricing is unavailable rather than a guessed percentage. A complete feasible placement is required before reporting total added-node cost.

With no eligible components the CUD quote is **Not applicable**, and on-demand cost remains available. Missing eligible commitment prices are **Unavailable**. A valid zero quote is preserved.

An estimate exceeding the configured autoscaler max still reports its feasible candidate node count and cost, with the configuration change clearly identified. The app never changes the pool, Pods, commitments or autoscaler.

## Service bundles and new-pool designs (unreleased)

Capacity planner supports up to 20 services with independent requests/YAML, replicas, HPA/surge and zone inputs. One joint simulation preserves shared budgets and scheduling context; same-namespace quotas and the 2,000-replica default bound apply to combined peak demand. Service order is the bounded greedy order; feasible placement is not a minimum-node proof. Per-service rows/placements/rejections expose results, and the UI pins its displayed snapshot.

New node pool uses up to 10 saved observed profiles in the selected cluster to design an empty proposed pool. It keeps saved allocatable and overhead evidence, relabels the pool, uses production/nonproduction ceilings and evaluates all proposed services together. Existing cluster Pods remain scheduling context, while existing pool capacity and pool-bound pending demand are excluded. Captured machine/provisioning/disk quotes remain exact saved assumptions; unknown prices are not guessed. Ranking prioritizes complete placements and fewer unknowns before available on-demand prices; unquoted profiles may be cheaper.

The review report includes candidate total/per-zone nodes, labels/taints/capacity assumptions, placements, costs and source timestamps. JSON and saved history are available. It is a design report, not a GKE create request; regional node counts, IP/Compute quotas, network/storage/admission and DaemonSet eligibility for the new pool require operator review. No cloud resources are created. [GKE NodePool fields](https://docs.cloud.google.com/kubernetes-engine/docs/reference/rest/v1/projects.locations.clusters.nodePools) describe the infrastructure configuration an operator must validate.
