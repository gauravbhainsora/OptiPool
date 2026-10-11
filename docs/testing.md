# Local testing

The fixtures contain no production identifiers or collected observations. Use them for all CI and development checks. Python 3.13 and Node 22 are the supported container/CI baseline; this workstation also built successfully with Node 23.10.

## Fresh checkout

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements-dev.lock
.venv/bin/pip install --no-deps -e .
npm --prefix frontend ci
bash scripts/check.sh
bash scripts/dev.sh
```

Use `python3` on platforms where it resolves to Python 3.13+. Dependency versions are locked in `requirements*.lock` and `frontend/package-lock.json`.

## Manual dashboard walkthrough

1. Open http://127.0.0.1:8000. Confirm **DEMO DATA**, four synthetic projects and eight saved pools.
2. Filter project/cluster and select a pool. Open Nodes, inspect budgets and labels.
3. Open Workloads. Move the 1–10 day slider; the cutoff stays saved. Inspect the individual Pod table and search by Pod or node.
4. Export node pools, workloads and Pods as CSV and Excel. Confirm rows, units, synthetic indicator, snapshot ID/time, and the workload day window.
5. Open Capacity planner. The form names the target pool. Estimate `500m`, `1Gi`, six replicas; then try ten replicas at `2` CPU cores, and one Pod at `100Gi` memory. Observe Fits, Needs nodes and a blocked machine shape. Review added-node cost and autoscaler restrictions.
6. Paste a Deployment with hard anti-affinity or a PVC. Supported rules constrain placement; unresolved storage/admission features produce Cannot fully assess.
7. Save the snapshot IDs for two pools. Fetch one pool and verify only its ID changes. Refresh project inventory and verify neither existing snapshot changes.
8. Stop/restart the API. Existing IDs and saved estimates survive; no automatic refresh occurs after initialization.

## Automated checks

```bash
.venv/bin/pytest -q
.venv/bin/ruff check backend scripts
.venv/bin/ruff format --check backend scripts
npm --prefix frontend run build
.venv/bin/python scripts/verify-http.py http://127.0.0.1:8000
(cd frontend && npx playwright install chromium && npm test)
.venv/bin/python scripts/benchmark.py
```

Domain fixtures cover quantities, restartable init sidecars, overhead, request ceilings, fragmentation, fixed existing Pods, selectors/taints, hard anti-affinity, outstanding demand, unsupported storage, bounded search, independent p99 maxima, missing metrics, component prices and commitment obligation. API tests prove views/slider/exports/estimates never call collectors, refreshes are scoped/deduplicated, failures preserve old snapshots, and backup/restart/retention work. Signed ES256 tests reject missing/forged/expired/wrong-audience IAP assertions. Source adapter tests use mocked public REST responses, never real ADC.

## Container and packaged Helm chart

Start Docker, then:

```bash
bash scripts/kind-test.sh
```

The script builds `optipool:0.1.0`, creates a unique disposable Kind cluster with Kubernetes 1.32.2, loads the local image, packages and installs the chart, runs its smoke hook and HTTP flows, restarts the app and upgrades to a temporary chart 0.1.1 while asserting snapshot IDs persist. It checks uninstall retains the PVC, then removes only its own disposable cluster. Do not use this script against a live cluster. Local port 18080 must be free.

Chart schema checks reject two replicas, `latest` images and ingress with local auth. Ingress rendering with IAP is tested; Kind cannot validate GKE BackendConfig behavior or organization IAM. Hook Pods persist for log inspection until the next Helm test, or explicit removal/cluster cleanup.

For a reusable local installation:

```bash
docker build -t optipool:0.1.0 .
kind create cluster --name optipool-local --image kindest/node:v1.32.2
kind load docker-image optipool:0.1.0 --name optipool-local
helm package charts/optipool --destination /tmp
helm install demo /tmp/optipool-0.1.0.tgz --kube-context kind-optipool-local --namespace optipool --create-namespace --set image.pullPolicy=Never --wait
kubectl --context kind-optipool-local -n optipool port-forward service/demo-optipool 8000:80
```

Only delete the explicitly disposable local cluster when finished: `kind delete cluster --name optipool-local`. Cluster deletion also removes its local storage, regardless of Helm's PVC keep annotation.

## Live acceptance

Use the [configuration guide](configuration.md) for ADC/impersonation, project discovery and nonproduction classification. Validate complete collection of one chosen nonproduction pool, target API networking, actual monitoring source/coverage, exact SKU prices and conditional scheduling outcomes. Then benchmark 20 concurrent users at twice the actual discovered inventory; cached views/slider target p95 <2s and ordinary estimates <10s. Record series/node/Pod counts and disk/memory/refresh duration before sizing production resources. Synthetic benchmarks are supporting evidence only.
