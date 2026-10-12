"""Standard-library HTTP smoke test for a synthetic local or Kind deployment."""

import io
import json
import sys
import urllib.parse
import urllib.request
import zipfile

base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"


def get(path):
    with urllib.request.urlopen(base + path, timeout=30) as response:
        return response.read()


inventory = json.loads(get("/api/inventory"))
assert inventory["mode"] == "demo" and inventory["initialized"]
assert len(inventory["pools"]) == 8
pool = inventory["pools"][0]
query = urllib.parse.urlencode({"pool_id": pool["id"], "days": 10})
snapshot = json.loads(get("/api/snapshot?" + query))
assert snapshot["usage"]["days"] == 10 and snapshot["workloads"]
assert snapshot["usage"]["pods"] and snapshot["pods"][0]["containers"]
recommendations = json.loads(get("/api/recommendations?" + query))
assert recommendations["snapshot_id"] == snapshot["id"] and recommendations["rows"]
assert json.loads(get("/api/snapshots?" + query))[0]["id"] == snapshot["id"]
comparison = json.loads(
    get("/api/snapshots/compare?" + query + "&before=" + snapshot["id"] + "&after=" + snapshot["id"])
)
assert comparison["changes"] == []
for table in ["node-pools", "workloads", "pods"]:
    csv = get("/api/export/" + table + "?" + query + "&format=csv")
    assert b"Snapshot ID" in csv and len(csv) > 100
    workbook = get("/api/export/" + table + "?" + query + "&format=xlsx")
    assert zipfile.is_zipfile(io.BytesIO(workbook))
cluster_selection = {k: pool[k] for k in ["project", "location", "cluster"]}
scope = json.loads(get("/api/cluster-snapshot?" + urllib.parse.urlencode({**cluster_selection, "days": 10})))
assert len(scope["sources"]) == 2 and len(scope["nodes"]) == 5 and len(scope["pods"]) == 20
assert len(scope["workloads"]) == 4 and scope["days"] == 10
pins = {s["pool_id"]: s["snapshot_id"] for s in scope["sources"]}
for table in ["workloads", "pods"]:
    for format in ["csv", "xlsx"]:
        export_request = urllib.request.Request(
            base + f"/api/export-cluster/{table}?format={format}",
            data=json.dumps({**cluster_selection, "days": 10, "snapshots": pins}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(export_request, timeout=30) as response:
            content = response.read()
        assert len(content) > 100
        if format == "xlsx":
            assert zipfile.is_zipfile(io.BytesIO(content))
        else:
            assert all(sid.encode() in content for sid in pins.values())
assert {p["id"]: p["snapshot_id"] for p in json.loads(get("/api/inventory"))["pools"]} == {
    p["id"]: p["snapshot_id"] for p in inventory["pools"]
}


def post(path, payload):
    request = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


services = [
    {"name": "smoke-api", "cpu": "500m", "memory": "1Gi", "replicas": 2},
    {"name": "smoke-worker", "cpu": "250m", "memory": "512Mi", "replicas": 3},
]
bundle = post(
    "/api/estimate-bundle?" + urllib.parse.urlencode({"pool_id": pool["id"], "snapshot_id": snapshot["id"]}),
    {"services": services},
)
assert bundle["replicas"] == 5 and len(bundle["services"]) == 2
profiles = json.loads(get("/api/node-pool-profiles?" + urllib.parse.urlencode(cluster_selection)))
report = post(
    "/api/node-pool-design",
    {
        **cluster_selection,
        "name": "smoke-new-pool",
        "services": services,
        "snapshots": {p["pool_id"]: p["snapshot_id"] for p in profiles["profiles"]},
    },
)
assert report["recommended_profile"] and all(
    c["configuration"]["total_nodes"] >= 1 for c in report["candidates"]
)
assert (
    json.loads(get("/api/node-pool-designs?" + urllib.parse.urlencode(cluster_selection)))[0]["id"]
    == report["id"]
)
req = urllib.request.Request(
    base + "/api/estimate?" + query,
    data=json.dumps(
        {
            "cpu": "500m",
            "memory": "1Gi",
            "replicas": 3,
            "planning_mode": "combined",
            "hpa_max_replicas": 6,
            "max_surge": "25%",
            "spread_zones": True,
        }
    ).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=30) as response:
    result = json.load(response)
assert result["snapshot_id"] == snapshot["id"] and result["placements"]
assert result["planning"]["peak_replicas"] == 8 and result["node_budgets"]
assert json.loads(get("/api/inventory"))["pools"][0]["snapshot_id"] == pool["snapshot_id"]
print(
    "HTTP pool/cluster views, pinned exports, multi-service capacity, new-pool design/history, Pod analytics and peak/zone scenario verified"
)
