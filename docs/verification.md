# Local verification evidence

Verified on 11 October 2026 in the OptiPool working checkout. Fixtures are synthetic; no live Google Cloud credentials, projects or observations were used.

| Boundary | Result | Evidence |
|---|---|---|
| Application tests | Pass | 43 pytest cases: domain, snapshots/retention, HTTP, source contracts, signed IAP and export safety |
| Frontend build | Pass | TypeScript strict compilation and Vite production build |
| Python and frontend style | Pass | Ruff lint/format and Prettier checks |
| Desktop browser flow | Pass | Controller table, day window, per-Pod search, Excel download, named target-pool assessment, added-node and blocked shape outcomes |
| Mobile browser flow | Pass | 390×844 viewport; no document-level horizontal overflow |
| HTTP saved-data flow | Pass | 10-day window, CSV/Excel for pools/workloads/Pods, persisted estimate, unchanged snapshot ID |
| Container | Pass | Local multi-stage image built and ran as nonroot in Kind |
| Chart metadata/schema | Pass | Helm lint/render/package; multiple replicas and insecure ingress rejected |
| Packaged chart lifecycle | Pass | Actual 0.1.0 package installed, Helm smoke tests passed, restart + temporary chart 0.1.1 upgrade retained exact snapshot IDs |
| Uninstall storage behavior | Pass | Default generated PVC retained after Helm uninstall; disposable Kind cluster then removed |
| Consistent backup/restore | Pass | SQLite backup API restores into a fresh file with identical saved snapshot identity |
| Synthetic concurrent benchmark | Pass after optimization | 20 concurrent users; 16 pools, 40 nodes, 160 Pods; saved data only |

The first benchmark exposed repeated full-snapshot decoding in the inventory endpoint (cached-view p95 ≈2.96s). Atomic saved pool overviews eliminated that work; the recorded follow-up achieved cached-view p95 ≈0.353s and ordinary estimate p95 ≈0.172s. See [the machine-readable synthetic benchmark](benchmark-synthetic.json). This is an in-process API smoke benchmark, not real-inventory acceptance or end-user network/IAP latency.

The test dependency emits a Starlette deprecation warning for its current HTTPX-backed TestClient. Tests pass; migration to the future HTTPX2 test integration remains a dependency-maintenance item. Browser test output also includes the runner's FORCE_COLOR/NO_COLOR warning. Neither is a failed assertion.

## Published distribution: 12 October 2026

The [v0.1.0 publication workflow](https://github.com/gauravbhainsora/OptiPool/actions/runs/38165629349) passed its application/browser/benchmark and Kind lifecycle gates, then published the image and [GitHub release](https://github.com/gauravbhainsora/OptiPool/releases/tag/v0.1.0).

- `helm repo add`, repository update, and `helm pull optipool/optipool --version 0.1.0` succeeded against the public repository without credentials. The downloaded archive matches SHA256 `13791f414e33176ee08060db50a73fd6c4047582b5d4741704d088e96479a309`.
- The public GitHub release archive/checksum match the same package, and its `image-digest.txt` matches the GHCR image.
- Anonymous GHCR manifest access succeeds and includes Linux AMD64 and ARM64. The published image digest is `sha256:e4ba2ca19c82aeb24183510d830850bfd8856830a26c753955574070f12056f2`.

Artifact publication does not replace the pending live acceptance below.

## v0.2.0 local verification — 12 October 2026

- 71 backend cases passed, including analytics guards, manifest errors, scoped/pinned reads, cache deduplication/eviction/freshness, compact core compatibility and collector concurrency/failure contracts.
- Three browser flows passed: recommendations/Pod detail/window/export/peak scenario/comparison, CUD status display, and mobile overflow. TypeScript/Vite, Ruff, Prettier and chart lint/render/schema checks passed.
- Latest 20-user synthetic run: saved-view p95 **0.135s**, ordinary estimate p95 **0.071s**; 16 pools, 40 nodes and 160 Pods, with zero collection during read/estimate workloads. Compact planning cores avoid parsing unused usage histories. These figures do not establish live-cloud or actual-inventory performance.
- Matching v0.2.0 image/chart passed Docker Desktop / Kind install, Helm and HTTP analytics/scenario smoke checks, restart persistence and temporary 0.2.1-lifecycle.1 upgrade with identical saved IDs. Uninstall retained the PVC; the disposable cluster was removed.
- The [v0.2.0 release workflow](https://github.com/gauravbhainsora/OptiPool/actions/runs/38169391627) and main verification run `38169367740` passed. The [public release](https://github.com/gauravbhainsora/OptiPool/releases/tag/v0.2.0) has matching chart/checksum/image-digest assets.
- Anonymous Helm repository add/update/pull verifies 0.2.0 and unchanged 0.1.0. Chart 0.2.0 SHA256: `4fffdebf28d4ba6bd015fd1bbbcbdffb7d2cfbd26c31fbbc54fa7da331332730`. Anonymous GHCR manifest access includes AMD64 and ARM64 and matches `sha256:5cbcc2a5a27c34a49d555a8310a09cdda63b790be0033e1441710c79216897c3`. The final handoff is in [the build plan](BUILD_PLAN.md).

## Pending production acceptance (unchanged)

- Collector service-account identity and approved IAM/RBAC are supplied/provisioned by the operator.
- Read-only collection succeeds for one selected nonproduction pool, including target API networking and real current owner/spec/context data.
- Actual GMP/native series, saved cadence, metric window coverage and historical attribution are reviewed.
- Exact public SKU mappings and complete chargeable components are checked against the target pool configuration.
- Organization/group IAP grants, HTTPS ingress, signed backend audience and Workload Identity are validated in GKE.
- Off-volume backup/restore drill and sizing/retention are validated against actual metric volume.
- 20-user acceptance benchmark runs at twice the actual discovered inventory; large-scale refresh and simulation limits are measured.

Production collection defaults to gated until this validation is recorded. No production readiness, actual billing savings or complete deleted-Pod history is inferred from demo checks. Git/image/chart publication is separate from local implementation and packaging.
