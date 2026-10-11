OptiPool 0.2.0 adds saved-data analytics and faster loading while preserving explicit selected-pool refreshes.

- Advisory Deployment request recommendations with configurable headroom, coverage and OOM/restart guards.
- Per-Pod saved latest usage/p99, container resources, conditions and available termination evidence, including CSV/Excel export.
- HPA maximum and rollout-surge scenarios, hard zone spread, before/after node budgets and placement explanations.
- Same-pool snapshot comparison and a self-contained architecture/build handoff.
- Null-resource manifest fixes and explicit Not applicable/Unavailable CUD quotes.
- Single-query inventory reads, compact exports/planning snapshots, bounded immutable view caching, batched selected-pool GMP queries and concurrent cloud reads with transient GET retries.

Download the chart:

```bash
helm repo add optipool https://raw.githubusercontent.com/gauravbhainsora/OptiPool/main/docs/helm
helm repo update
helm pull optipool/optipool --version 0.2.0
```

The release includes the chart archive, SHA256 checksum and matching image digest. The container image is `ghcr.io/gauravbhainsora/optipool:0.2.0` for Linux AMD64 and ARM64. The existing image package is public. Version 0.1.0 remains available.

Older saved snapshots remain readable without automatic refresh. New container-status/cadence fields become available on explicit collection; missing historical fields stay unknown. SQLite adds a derived compact core table and indexes without changing existing immutable observations. Back up the PVC before upgrading; Helm rollback does not reverse database changes.

HPA/surge inputs model additional peak demand, not full rollout replacement sequencing. Recommendations remain advisory; CPU throttling and per-container usage history are not collected. Synthetic tests and Docker/Kind lifecycle checks verify local behavior; real GCP/IAP/pricing and inventory-sized acceptance remain pending the collector identity.

Defaults run a private synthetic demo with one SQLite-owning instance and persistent storage. Live production collection remains gated pending real nonproduction collector, metrics, pricing, IAP/Workload Identity, storage and load validation. This release is not a claim of production acceptance.
