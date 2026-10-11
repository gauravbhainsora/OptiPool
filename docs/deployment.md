# GKE deployment and Helm releases

The chart/app start at 0.1.0. Chart `version` is package SemVer; quoted `appVersion` identifies application compatibility. Pin your registry image tag or immutable digest. Do not deploy `latest`. Helm 3.17.3 / Kind 0.27.0 / Kubernetes 1.32.2 are the local verification baseline; GKE production compatibility must be checked on the target cluster.

## Private demo deployment

Pull the public chart:

```bash
helm repo add optipool https://raw.githubusercontent.com/gauravbhainsora/OptiPool/main/docs/helm
helm repo update
helm pull optipool/optipool --version 0.1.0
```

The repository index includes a SHA256 digest and points to the archive at the immutable `v0.1.0` Git tag. The release also carries a checksum file and an `image-digest.txt` containing the exact multi-platform image reference. The default image repository is `ghcr.io/gauravbhainsora/optipool`.

Release 0.1.0 is public: anonymous Helm package download and GHCR access for both Linux AMD64 and ARM64 were verified on 12 October 2026. The following visibility step applies when publishing a new package or using a private registry.

GitHub initializes new container packages as private. The repository owner should open [the image package](https://github.com/users/gauravbhainsora/packages/container/package/optipool), then **Package settings → Change visibility → Public** for anonymous image pulls. Verify with `docker pull ghcr.io/gauravbhainsora/optipool:0.1.0` without registry credentials. Chart downloads are public independently of this setting. If keeping the image private, pre-create an approved registry pull secret in the namespace and set `imagePullSecrets: [{name: your-pull-secret}]`; do not put credentials in values or Git. Alternatively override `image.repository` with your own published image.

After image access is confirmed, install the private demo:

```bash
helm upgrade --install optipool optipool/optipool --version 0.1.0 \
  --kube-context YOUR_CONTEXT --namespace optipool --create-namespace --wait --timeout 10m
helm test optipool --kube-context YOUR_CONTEXT --namespace optipool --logs
```

For building the chart and image yourself:

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

The public Helm repository is served from `docs/helm` on `main`, with packages addressed through their version Git tags. To publish a new version, update app/chart versions, record release notes, package the reviewed chart into `docs/helm`, write its checksum, and merge the old index with `helm repo index --merge` so older versions remain available. Never replace an existing version archive or move a release tag. Update the current Helm testing script's version references for the new release.

Push the reviewed commit and version tag (for example `v0.1.0`). The tag-triggered release workflow first runs the complete application/browser/Kind verification workflow, then publishes the amd64/arm64 image to GHCR and uploads the checked-in chart/checksum and exact image digest to a GitHub release. It uses the scoped Actions token; no personal registry password is stored in the repository. Container package visibility is a separate owner setting. Before enabling production collection, satisfy the live acceptance gate; publishing artifacts does not establish production readiness.
