#!/usr/bin/env bash
# Creates and removes only its own disposable cluster; no live GCP credentials.
set -euo pipefail
cd "$(dirname "$0")/.."
task_cluster="optipool-verify-$$"
task_dir="$(mktemp -d)"
previous_context="$(kubectl config current-context 2>/dev/null || true)"
port_forward_pid=""
cleanup() {
  if [ -n "$port_forward_pid" ]; then kill "$port_forward_pid" 2>/dev/null || true; fi
  kind delete cluster --name "$task_cluster"
  if [ -n "$previous_context" ]; then kubectl config use-context "$previous_context" > /dev/null; fi
  rm -rf "$task_dir"
}
trap cleanup EXIT
docker build -t optipool:0.1.0 .
kind create cluster --name "$task_cluster" --image kindest/node:v1.32.2 --wait 120s
kind load docker-image optipool:0.1.0 --name "$task_cluster"
helm package charts/optipool --destination "$task_dir"
helm install demo "$task_dir/optipool-0.1.0.tgz" --kube-context "kind-$task_cluster" \
  --namespace optipool --create-namespace --set image.pullPolicy=Never --wait --timeout 180s
helm test demo --kube-context "kind-$task_cluster" --namespace optipool --logs --timeout 120s
kubectl --context "kind-$task_cluster" -n optipool port-forward service/demo-optipool 18080:80 >"$task_dir/forward.log" 2>&1 &
port_forward_pid=$!
for attempt in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:18080/api/inventory >"$task_dir/before.json"; then
    if python3 -c 'import json,sys; s=json.load(open(sys.argv[1])); assert s["initialized"] and all(p["snapshot_id"] for p in s["pools"])' "$task_dir/before.json"; then break; fi
  fi
  sleep 1
done
python3 scripts/verify-http.py http://127.0.0.1:18080
kill "$port_forward_pid"
port_forward_pid=""
kubectl --context "kind-$task_cluster" -n optipool rollout restart deployment/demo-optipool
kubectl --context "kind-$task_cluster" -n optipool rollout status deployment/demo-optipool --timeout=180s
cp -R charts/optipool "$task_dir/chart"
sed 's/^version: 0.1.0$/version: 0.1.1/' "$task_dir/chart/Chart.yaml" > "$task_dir/Chart.yaml"
mv "$task_dir/Chart.yaml" "$task_dir/chart/Chart.yaml"
helm package "$task_dir/chart" --destination "$task_dir"
helm upgrade demo "$task_dir/optipool-0.1.1.tgz" --kube-context "kind-$task_cluster" \
  --namespace optipool --set image.pullPolicy=Never --wait --timeout 180s
helm test demo --kube-context "kind-$task_cluster" --namespace optipool --logs --timeout 120s
kubectl --context "kind-$task_cluster" -n optipool port-forward service/demo-optipool 18080:80 >"$task_dir/forward.log" 2>&1 &
port_forward_pid=$!
for attempt in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:18080/api/inventory >"$task_dir/after.json"; then break; fi
  sleep 1
done
python3 - "$task_dir/before.json" "$task_dir/after.json" <<'PY'
import json,sys
before,after=(json.load(open(p)) for p in sys.argv[1:])
assert {p['id']:p['snapshot_id'] for p in before['pools']} == {p['id']:p['snapshot_id'] for p in after['pools']}
print('Packaged chart install, Helm tests, restart persistence and chart upgrade verified')
PY
helm uninstall demo --kube-context "kind-$task_cluster" -n optipool
kubectl --context "kind-$task_cluster" -n optipool get pvc demo-optipool
echo 'Retained PVC verified. Disposable cluster is removed by cleanup.'
