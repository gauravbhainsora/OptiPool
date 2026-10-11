OptiPool 0.1.0 is the initial Apache 2.0 release: saved GKE node-pool, node, workload and Pod views; CSV/Excel exports; request-based capacity estimates; a versioned Helm chart; and synthetic local tests.

Download the chart:

```bash
helm repo add optipool https://raw.githubusercontent.com/gauravbhainsora/OptiPool/main/docs/helm
helm repo update
helm pull optipool/optipool --version 0.1.0
```

The release includes the chart archive, its SHA256 checksum, and the matching container image digest. The container image is `ghcr.io/gauravbhainsora/optipool:0.1.0` (linux/amd64 and linux/arm64). GitHub initializes new container packages as private; anonymous image access requires the package owner to make it public. Authenticated users may instead configure image pull secrets. The Helm chart itself is publicly downloadable.

Defaults run a private synthetic demo with one SQLite-owning instance and persistent storage. Live production collection remains gated pending real nonproduction collector, metrics, pricing, IAP/Workload Identity, storage and load validation. This release is not a claim of production acceptance.
