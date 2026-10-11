# Contributing to OptiPool

Use Python 3.13+, Node 22+, npm and Helm 3.17.3. Follow [testing.md](docs/testing.md) for a fresh setup. Docker, kubectl and Kind 0.27.0 enable the packaged deployment checks. Demo fixtures and tests require no cloud credentials.

Before proposing changes, run `bash scripts/check.sh`; deployment changes also require `bash scripts/kind-test.sh`. Keep Python formatted with Ruff and TypeScript/CSS with Prettier. Tests should exercise behavior at boundaries: snapshot atomicity, saved-data reads, constrained placement, percentile attribution, export safety, identity verification and persistent upgrades.

Keep cloud adapters read-only. UI navigation, slider changes, exports and estimates must never fetch live observations. Preserve the latest successful snapshot on collection failure. Never silently convert unknown metrics, costs or placement context to zero/success. State assumptions and supported constraint boundaries. Update design, support matrix and changelog when behavior changes.

Include the concrete problem, resulting behavior and relevant validation in a pull request. Review schema/image compatibility explicitly; chart and application versions are independently versioned. A Helm rollback is not a database rollback.

Do not submit cloud credentials, account snapshots, real project/domain/identity config, private databases or production export artifacts. Use synthetic fixtures with clearly labelled prices. Reports concerning vulnerabilities should follow [SECURITY.md](SECURITY.md).

Contributions are offered under the project's Apache 2.0 license. This project does not require an additional CLA in this version.
