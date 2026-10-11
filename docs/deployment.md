# GKE deployment and Helm releases

The chart/app start at 0.1.0. Chart `version` is package SemVer; quoted `appVersion` identifies application compatibility. Pin your registry image tag or immutable digest. Do not deploy `latest`. Helm 3.17.3 / Kind 0.27.0 / Kubernetes 1.32.2 are the local verification baseline; GKE production compatibility must be checked on the target cluster.

## Private demo deployment

```bash
docker build -t optipool:0.1.0 .
helm lint charts/optipool
helm template demo charts/optipool
helm package charts/optipool --destination /tmp
```

Load the image into Kind and install the actual package using [testing.md](testing.md). Defaults expose only a ClusterIP service with no ingress. Local authentication is allowed only in a trusted loopback or private test environment; it is not a production identity check.

## Production prerequisites

- Existing GKE cluster with block-backed durable storage, a reachable target control plane, and Workload Identity configured.
- An approved collector identity with read permissions across discovered projects and target Kubernetes clusters. Keep the configured scope narrow enough to review.
- A registry image available to that cluster, ideally pinned by digest.
- Organization-owned HTTPS domain, GKE Ingress/BackendConfig support, an existing ManagedCertificate, and a pre-created IAP OAuth client secret.
- An approved organization/group granted `roles/iap.httpsResourceAccessor` on the intended backend, not public unauthenticated access.
- Correct signed IAP audience for that load-balancer backend. The backend service ID is provisioned by the GKE ingress controller, so this may require a staged private install, ingress creation, then updating the audience. Use a nonempty placeholder audience to deny application requests while the real ID is being determined; never switch to local auth to bypass that step.
- A recorded nonproduction collection/estimation/metrics/pricing validation, and `live_validation_complete: true` only after the operator completes it.

See [GKE IAP configuration](https://docs.cloud.google.com/iap/docs/enabling-kubernetes-howto) and [signed assertion validation](https://docs.cloud.google.com/iap/docs/signed-headers-howto). The application verifies ES256 signature, audience, issuer, identity, issue/expiry times and token lifetime. Unsigned email headers are rejected. Health/readiness endpoints intentionally require no assertion; they expose no inventory.

Use [Workload Identity](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/workload-identity) rather than service-account key files. For IAM service-account impersonation, annotate the Kubernetes ServiceAccount and provision the required IAM binding. Alternatively use approved direct Workload Identity principal grants. The chart creates only the hosting ServiceAccount; project IAM and remote Kubernetes RBAC are provisioned separately.

## Install

Prepare an ignored `production-values.yaml` based on [values-gke.example.yaml](../charts/optipool/values-gke.example.yaml). It contains placeholders only. Do not commit real domain/project/identity configuration or OAuth secret contents.

```bash
helm upgrade --install optipool /tmp/optipool-0.1.0.tgz --namespace optipool --create-namespace -f production-values.yaml --wait --timeout 10m
helm test optipool --namespace optipool --logs
```

Choose an explicit `--kube-context` for your hosting cluster. The chart uses one replica, one Uvicorn worker and Recreate updates. Resource defaults are a starting point; measure actual metric volume, memory, disk, backup duration and refresh duration before sizing. Do not scale replicas over NFS or another network-shared SQLite file.

## Upgrade and rollback

1. Create a consistent off-volume backup and verify it can be restored.
2. Review the target chart's `appVersion`, image digest, changelog and database compatibility notes.
3. Package/install the new chart using the same release/namespace/PVC. Recreate briefly stops service.
4. Run Helm tests, inspect logs and verify saved snapshot/estimate IDs persist.

Schema v1 is created idempotently. This version introduces no destructive migration. Future schema changes need explicit upgrade and restore testing. **Helm rollback changes Kubernetes resources; it does not reverse a SQLite migration.** Restore the pre-upgrade database and compatible application only when necessary and with downtime.

## Uninstall and storage

The default generated PVC has `helm.sh/resource-policy: keep` and survives Helm uninstall. Test-hook Pods may remain for log inspection. Explicitly remove them if needed. A pre-existing claim (`persistence.existingClaim`) is never created or removed by the chart.

Retained PVCs still incur storage costs. Inspect and back up them before deciding to delete. For reinstall, prefer an existing claim reference to avoid Helm ownership conflicts. PersistentVolume reclaim policy belongs to the storage configuration; deleting a PVC can destroy its data. Deleting a Kind cluster removes its local volume data regardless of the keep annotation.

## Publishing

Local packaging is separate from publication. Before the first Git push, satisfy [release-readiness.md](release-readiness.md). Before a production release, satisfy the live acceptance gate. No public image/chart release is created by the included CI. Publish an immutable image, tag the application release, package the independently versioned chart, then upload it to your selected chart/OCI distribution channel after reviewing artifact versions and destination.
