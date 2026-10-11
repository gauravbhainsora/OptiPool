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
for table in ["node-pools", "workloads", "pods"]:
    csv = get("/api/export/" + table + "?" + query + "&format=csv")
    assert b"Snapshot ID" in csv and len(csv) > 100
    workbook = get("/api/export/" + table + "?" + query + "&format=xlsx")
    assert zipfile.is_zipfile(io.BytesIO(workbook))
req = urllib.request.Request(
    base + "/api/estimate?" + query,
    data=json.dumps({"cpu": "500m", "memory": "1Gi", "replicas": 6}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=30) as response:
    result = json.load(response)
assert result["snapshot_id"] == snapshot["id"] and result["placements"]
assert json.loads(get("/api/inventory"))["pools"][0]["snapshot_id"] == pool["snapshot_id"]
print("HTTP saved views, 10-day window, CSV/Excel exports and saved estimate verified")
