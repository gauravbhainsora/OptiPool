# OptiPool chart

Chart 0.2.0 deploys app 0.2.0. See [deployment](../../docs/deployment.md), [local install tests](../../docs/testing.md) and [backup/restore](../../docs/operations.md).

Download the published package without cloning this repository:

```bash
helm repo add optipool https://raw.githubusercontent.com/gauravbhainsora/OptiPool/main/docs/helm
helm repo update
helm pull optipool/optipool --version 0.2.0
```

The index points to a version-tagged archive and includes its SHA256 digest. Container images use `ghcr.io/gauravbhainsora/optipool:0.2.0`; the existing OptiPool package is public. A newly created GHCR package may need an owner visibility change for anonymous pulls, or `imagePullSecrets` for private access. You can also build and use your own registry image. Chart downloads are public regardless of image visibility.

| Value | Default |
|---|---|
| `replicaCount` | 1, enforced by schema and template |
| `image.repository` / `tag` / `digest` | `ghcr.io/gauravbhainsora/optipool` / `0.2.0` / optional immutable SHA256 |
| `config.mode` / `auth_mode` | Private synthetic demo / local |
| `config.project_allowlist` | Empty = dynamic collector project discovery |
| `config.environment` | Explicit hierarchy; defaults to production |
| `config.live_validation_complete` | false, production live collection gated |
| `serviceAccount` | Created; name and Workload Identity annotations configurable |
| `resources` | 250m/512Mi requests, 2 CPU/2Gi limits; measure before production |
| `persistence` | 20Gi RWO claim, default storage class, retain on uninstall |
| `persistence.existingClaim` | Empty; use supplied claim if set |
| `ingress.enabled` | false; GKE Ingress requires IAP + host + existing cert/OAuth secret |
| `nodeSelector` / `tolerations` / `affinity` | Optional app placement, unrelated to simulated target pool |

No secret values are embedded. Backup automation is an external operator responsibility using the application's colocated SQLite backup script; WAL files must not be copied independently. Exactly one app process opens the live DB. Updates use Recreate. The single owner limit does not prevent someone manually installing another release against the same PVC; do not share the claim between releases.

`helm test --logs` retains its completed smoke Pod for inspection and deletes the prior hook before the next run. Test hooks verify unauthenticated health endpoints; application API flows are separately tested in the synthetic Kind workflow. Production IAP and collector identity are verified in nonproduction GKE.
