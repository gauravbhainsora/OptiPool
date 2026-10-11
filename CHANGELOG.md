# Changelog

## 0.1.0 — initial implementation

- React dashboard with project/cluster/pool selection and pool, node, workload and individual-Pod views.
- Saved observations in SQLite, one-time import, durable/deduplicated refresh jobs and atomic selected-pool publication.
- Dynamic accessible-project discovery, read-only GKE/Kubernetes/GMP/native Monitoring/public-price adapters, and a clearly synthetic local mode.
- Highest-replica Deployment p99 with a saved 1–10 day window and explicit coverage/source semantics.
- Conservative steady-state per-node placement, 80%/90% request ceilings, additional node/growth-limit reporting and saved on-demand/resource-CUD cost scenarios.
- CSV/Excel exports with snapshot/window provenance and formula injection escaping.
- Signed IAP identity verification, Workload Identity configuration examples, backup/restore tooling and developer/release documentation.
- Versioned Helm chart 0.1.0, app 0.1.0, single-owner persistent storage, private defaults and packaged install/persistence/upgrade checks.

Production validation is tracked separately in [verification](docs/verification.md). Live account pricing/identity/monitoring are not claimed validated by synthetic tests.
