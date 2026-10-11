# Capacity and cost assessment

The user selects a pool. Each saved estimate pins that pool's snapshot, inputs, policy, context and price data. Proposed Pods are placed on individual eligible nodes in that pool, or planned nodes with its saved shape. Existing Pods stay fixed.

For CPU and memory independently:

`remaining budget = allocatable × (0.8 production / 0.9 nonproduction) − existing effective requests`

Effective requests sum app containers, account for restartable init sidecars and the init peak, then include Pod overhead. Limit-only containers inherit their limit as a missing request. Observed p99 is not subtracted from capacity. Nodes already violating either ceiling get no new Pods. Current limits are displayed separately and are not request budgets.

## Support matrix

| Constraint | v0.1 behavior |
|---|---|
| CPU, memory, Pod slots | Checked per eligible node |
| Readiness and cordons | Unready/cordoned existing nodes excluded |
| Node selectors and required node affinity | Supported label/metadata.name expressions |
| NoSchedule/NoExecute taints | Required tolerations checked; PreferNoSchedule is a preference |
| Basic hard Pod affinity/anti-affinity | Saved cluster context + proposed replicas; namespace lists, selectors and topology labels; existing anti-affinity honored |
| Preferred affinity | Preference omitted; feasibility does not guarantee scheduler scoring or selected node |
| Namespace selectors/dynamic matchLabelKeys | Cannot fully assess |
| Topology spread | Cannot fully assess |
| Bound/dynamic storage and CSI volumes | Cannot fully assess; binding, attachment and provisioner are not reproduced |
| Custom scheduler/RuntimeClass/DRA | Cannot fully assess |
| GPU, extended resources, ephemeral-storage, host ports | Cannot fully assess |
| Basic requests CPU/memory and Pod quotas | Blocking check against saved used/hard values |
| LimitRange/scoped/additional quotas | Cannot fully assess |
| Mutating admission/injected sidecars | Cannot fully assess when potentially relevant or unavailable |
| Rollout surge, failures, HPA maximum, preemption | Outside steady-state scenario scope |

Pending Pods constrained to this pool are placed before the proposed workload. Desired controller replicas not materialized as Pods are accounted separately without double counting. Competing demand that can use multiple pools is flagged as uncertain rather than silently assigned or ignored.

New node prototypes use conservative observed allocatable capacity for the pool and saved DaemonSet/system overhead. Empty pools without a verified allocatable prototype cannot provide a confident growth estimate. Autoscaler bounds are shown separately from required growth; a pool with autoscaling disabled has zero automatic permitted growth.

The algorithm tries bounded greedy placements. A successful assignment is feasible under these assumptions, not a guaranteed minimum or a promise about scheduler scoring. Search exhaustion or a failed arrangement involving placement interactions returns Cannot fully assess. An intrinsic resource shape/selector contradiction or an explicit quota violation can block placement. Adding more small nodes cannot accommodate a single Pod larger than every node's request budget.

## Cost interpretation

On-demand and three-year resource-CUD totals use saved matching USD prices, with components priced separately. Monthly values assume 730 hours. The commitment obligation is the covered eligible hourly price × 24 × 365 × 3; disks and other on-demand-only components are outside that obligation. Partial/missing commitment pricing is unavailable rather than a guessed percentage. A complete feasible placement is required before reporting total added-node cost.

An estimate exceeding the configured autoscaler max still reports its feasible candidate node count and cost, with the configuration change clearly identified. The app never changes the pool, Pods, commitments or autoscaler.
