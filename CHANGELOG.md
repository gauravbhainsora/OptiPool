# Changelog

## Unreleased

- Memory requests overview beside CPU, with allocatable totals and unavailable-data handling.
- Pool-only names in the selected-pool input and unambiguous project/location/cluster selection.
- All node pools selection combining saved Nodes, Workloads and Pods, with per-pool provenance and snapshot-pinned CSV/Excel exports; individual-pool refresh and planning remain required.
- Clearer non-Deployment p99 captions for SparkApplication, DaemonSet and other controller types.
- Self-contained A–Z implementation prompt for rebuilding or continuing with another AI.
- Approved Matt Pocock skill configuration for GitHub Issues, default triage labels and existing glossary/ADR layout.

## 0.2.0 — 12 October 2026

- Advisory Deployment request proposals with configurable headroom, saved coverage, sampled memory-peak floors and OOM/restart review guards.
- Per-Pod saved latest usage/p99, timestamps, container resources, conditions and termination evidence; selected-window CSV/Excel exports.
- HPA maximum and rollout-surge envelopes, hard zone spread, node placement/budget visuals, rejection reasons and freshness disclosures.
- Same-pool saved-snapshot comparisons without live collection.
- Nullable manifest resource normalization and explicit inapplicable/unavailable CUD quotes.
- Single-query inventory/pool lookup, compact pool exports and planning-core storage, a 64 MiB immutable saved-view response cache, debounced window loads and shorter SQLite lock sections.
- Bounded concurrent cloud reads, connection reuse per worker, transient GET retries, selected-pool GMP query batches and indexed normalization.
- Self-contained architecture/build handoff maintained through repository agent instructions.

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
