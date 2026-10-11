# OptiPool release readiness

The destination repository is [gauravbhainsora/OptiPool](https://github.com/gauravbhainsora/OptiPool), with SSH remote `git@github.com:gauravbhainsora/OptiPool.git`. The user authorized implementation and selected Apache 2.0. Application, local guides and chart 0.1.0 are implemented; actual verification and remaining live gates are recorded in [verification.md](verification.md). No push is implied by local packaging.

## Required deliverables before the first code push

- A README explaining the project, supported scope, screenshots once the UI exists, architecture, quick start, and links to complete configuration/deployment/testing guides.
- An explicitly selected open-source license. Respect an existing repository license; if none exists, obtain the user's license decision before adding one.
- CONTRIBUTING guidance covering prerequisites, development commands, meaningful tests, style checks, pull requests, and compatibility expectations.
- Configuration examples containing placeholders and synthetic fixture data. Local SQLite databases, collected cloud snapshots, credentials, and private environment configuration are excluded from source control.
- A container build and a documented reproducible local run, both with a fixtures/demo mode that requires no live cloud access and a separately documented real-data mode.
- Unit/integration and end-to-end checks for collection, pool-scoped refresh, SQLite persistence, metrics-window/p99 behavior, scheduling estimates, pricing, and failure handling.
- CI that runs the applicable build, application tests, and Helm checks. CI credentials or production data must not be needed for the fixtures-based checks.
- A changelog/release procedure and documented supported application, chart, Helm, and Kubernetes versions.
- Security-reporting instructions and a permissions/configuration reference explaining collector IAM/RBAC, browser identity, and the explicit-refresh data model.

## Versioned Helm chart

The chart is at `charts/optipool/`. The following remain its release requirements.

- Include Chart.yaml, values.yaml, a values schema, configurable templates, installation notes, and chart-specific documentation.
- Version the chart independently from the application: the chart's SemVer `version` identifies its package; `appVersion` describes the application. Pin the intended image version or digest explicitly.
- Expose values for project/cluster configuration, environment defaults/overrides, monitoring source, service-account identity, application resources, service, ingress/IAP integration, retention, persistent storage, and backup configuration or documented external backup integration.
- Enforce the agreed single database-owning instance. SQLite is stored on durable block-backed storage; processes directly opening it remain colocated. Do not suggest scaling database-owning replicas over a shared network filesystem.
- Support an existing persistent volume claim and configurable storage settings. Document install, upgrade, restart, uninstall, volume retention, backup, restoration, and schema migration behavior.
- Prefer existing credentials/identity configuration over embedding secrets in chart values. Explain how target-cluster read permissions are provisioned separately; installing the host-cluster chart does not grant access to every target cluster.
- Provide a fixtures/demo values example for local testing, plus an example for the agreed GKE/IAP/Workload Identity deployment. Local fixtures mode must be explicitly configured, not an automatic production authentication fallback.

## Local testing guide

Document prerequisites and exact verified commands for:

1. Installing dependencies and running the UI/API/collector locally with SQLite and synthetic fixtures.
2. Running unit, integration, end-to-end, and concurrency/persistence checks.
3. Configuring real-data collection locally using the supported gcloud/application credential workflow or approved service-account impersonation; explain project, monitoring, and Kubernetes read permissions and network reachability.
4. Linting and rendering the chart, packaging it, building the local application image, and loading that image into a disposable Kind cluster.
5. Installing the actual packaged chart, checking readiness and application behavior, and running its Helm test hooks.
6. Refreshing fixture data, restarting the application, and confirming SQLite records survive.
7. Upgrading the chart with saved records and testing the documented backup/restore path. Helm resource rollback is not assumed to reverse database migrations.
8. Cleaning up the disposable environment while describing persistent-volume retention accurately.

Kind checks validate packaging and application behavior; GKE IAP, Workload Identity, private control-plane access, and real metric availability require the separately agreed non-production validation.

## Release gate

- Required build and application tests pass.
- Helm lint, render, package, install, Helm tests, persistence, and upgrade checks pass for the declared supported versions.
- A fresh checkout can follow the documented local quick start without private production access.
- Examples and fixture data are clearly synthetic; private snapshots and credentials are absent from the Git changes.
- The selected license, contributor guide, testing guide, chart guide, and changelog are present.
- Record the actual test results and any limits. Do not describe an unperformed live/GKE validation as passed.
- Confirm the application/chart versions and release destination before publication. Packaging a chart locally is separate from uploading it or creating a public release.

## References

- [Helm chart metadata](https://docs.helm.sh/docs/topics/charts/)
- [Helm package](https://helm.sh/docs/helm/helm_package/)
- [Helm chart tests](https://helm.sh/docs/topics/chart_tests/)
- [Kind quick start](https://kind.sigs.k8s.io/docs/user/quick-start)
- [Kubernetes persistent volumes](https://kubernetes.io/docs/concepts/storage/persistent-volumes/)
