# OptiPool

Language for inspecting node pools across GCP projects and evaluating capacity for new workloads.

## Language

**Node pool**:
A group of cluster nodes managed together with a shared node configuration.
_Avoid_: Cluster, server group

**Node**:
An individual compute instance in a cluster on which workload Pods can run.
_Avoid_: Node pool, replica

**Saved snapshot**:
The last collected observations of a node pool, its nodes, and the workloads running on those nodes.
_Avoid_: Live state, current state

**Pool refresh**:
A user-requested collection of fresh observations for one selected node pool.
_Avoid_: Global refresh, automatic sync

**Deployment scenario**:
A proposed new workload's resource needs and replica count, evaluated against a selected node pool.
_Avoid_: Deployment, live deployment

**Workload**:
A set of Pods associated with a Kubernetes workload controller, identified by namespace, controller kind, and controller name. Pods without an owning controller are represented separately.
_Avoid_: Service

**Kubernetes Service**:
A networking resource exposing a set of Pods, which may overlap with Pods exposed by another Service.
_Avoid_: Workload, Deployment

**Capacity estimate**:
An assessment of a deployment scenario against a saved snapshot, including whether more nodes would be needed. It describes feasibility under stated assumptions rather than guaranteeing a future deployment succeeds.
_Avoid_: Deployment guarantee

**Allocatable capacity**:
The resources a node exposes as available for Pods after its system reservations.
_Avoid_: Machine capacity, total VM resources

**Request ceiling**:
The maximum share of a node's allocatable CPU or memory that the environment's planning policy permits Pods to request.
_Avoid_: Usage limit, container resource limit

**Planning buffer**:
The portion of a node's allocatable capacity reserved by the environment's request-ceiling policy.
_Avoid_: System reservation, observed free capacity

**Metrics window**:
A trailing duration of observed resource usage ending at the saved metrics cutoff.
_Avoid_: Live window, inventory snapshot

**Highest-replica p99**:
The highest temporal p99 usage among a Deployment's observed replicas within the metrics window, evaluated separately for CPU and memory.
_Avoid_: Deployment total p99, average replica p99, pooled-sample p99

**Service bundle**:
A set of proposed service workload configurations assessed together against shared node-pool capacity.
_Avoid_: Batch job, combined Deployment

**Observed node profile**:
A captured node configuration used as a candidate shape for capacity planning, including allocatable capacity and baseline overhead.
_Avoid_: Machine catalog, verified new node

**Node-pool design**:
A proposed pool configuration and estimated node count for a service bundle, evaluated under stated assumptions.
_Avoid_: Provisioned node pool, creation operation
