import csv
import io
from copy import deepcopy

from fastapi.testclient import TestClient
from optipool.app import create_app
from optipool.cluster_views import combine
from optipool.metrics import summarize
from optipool.pods import selected_pods
from test_store_api import CountingCollector, initialized, wait_job


def view(snapshot):
    return {**snapshot, "usage": summarize(snapshot, 3), "pods": selected_pods(snapshot)}


def test_combine_groups_controllers_and_keeps_independent_p99_and_sources(saved):
    a, b = view(saved), view(deepcopy(saved))
    b["pool"]["id"] += "-other"
    b["pool"]["name"] = "other"
    b["id"] = "second"
    b["saved_at"] += 3600
    key = a["workloads"][0]["id"]
    a["usage"]["workloads"][key].update(cpu_p99=2, memory_p99=10, cpu_replica="cpu-winner", memory_peak=100)
    b["usage"]["workloads"][key].update(
        cpu_p99=1,
        memory_p99=20,
        memory_replica="memory-winner",
        memory_peak=200,
        memory_peak_replica="peak-winner",
    )
    result = combine("project", "region", "cluster", [a, b], [])
    workload = result["workloads"][0]
    assert len(result["workloads"]) == len(a["workloads"])
    assert workload["pool_replicas"] == a["workloads"][0]["pool_replicas"] * 2
    assert workload["requested"]["cpu"] == a["workloads"][0]["requested"]["cpu"] * 2
    assert workload["cpu_p99"] == 2 and workload["memory_p99"] == 20
    assert workload["cpu_replica"] == "cpu-winner" and workload["memory_replica"] == "memory-winner"
    assert workload["memory_peak"] == 200 and workload["memory_peak_replica"] == "peak-winner"
    assert result["sources"][0]["saved_at"] != result["sources"][1]["saved_at"]
    assert "desired" not in workload  # Cluster totals must not be added across pool snapshots.
    b["usage"]["memory_definition"] = "Different definition"
    mixed = combine("project", "region", "cluster", [a, b], [])["workloads"][0]
    assert mixed["memory_peak"] is None
    assert mixed["memory_p99"] is None and not mixed["memory_complete"]
    b["usage"]["workloads"].clear()
    partial = combine("project", "region", "cluster", [a, b], [])["workloads"][0]
    assert partial["cpu_p99"] == 2 and not partial["cpu_complete"]


def test_cluster_api_reads_and_pinned_exports_do_not_collect(settings):
    collector = CountingCollector(settings)
    with TestClient(create_app(settings, collector)) as client:
        inventory = initialized(client)
        pool = inventory["pools"][0]
        query = {k: pool[k] for k in ["project", "location", "cluster"]}
        response = client.get("/api/cluster-snapshot", params={**query, "days": 10})
        assert response.status_code == 200
        scope = response.json()
        assert len(scope["sources"]) == 2 and len(scope["nodes"]) == 5 and len(scope["pods"]) == 20
        assert len(scope["workloads"]) == 4 and scope["workloads"][0]["pool_replicas"] == 6
        assert all(n["pool_id"].startswith(pool["project"] + "/") for n in scope["nodes"])
        pins = {s["pool_id"]: s["snapshot_id"] for s in scope["sources"]}
        body = {**query, "days": 10, "snapshots": pins}
        for table in ["workloads", "pods"]:
            exported = client.post(f"/api/export-cluster/{table}", json=body)
            assert exported.status_code == 200
            rows = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
            assert len(rows) == (4 if table == "workloads" else 20)
            assert client.post(f"/api/export-cluster/{table}?format=xlsx", json=body).content.startswith(
                b"PK"
            )
        assert collector.calls == 8
        job = client.post("/api/refresh/pool", params={"pool_id": pool["id"]}, json={}).json()
        assert wait_job(client, job["id"])["state"] == "succeeded"
        exported = client.post("/api/export-cluster/workloads", json=body)
        assert exported.status_code == 200 and all(sid.encode() in exported.content for sid in pins.values())
        latest = client.get("/api/cluster-snapshot", params=query).json()
        assert {s["pool_id"]: s["snapshot_id"] for s in latest["sources"]} != pins
        assert collector.calls == 9
        foreign = inventory["pools"][2]
        assert (
            client.post(
                "/api/export-cluster/workloads",
                json={**body, "snapshots": {foreign["id"]: foreign["snapshot_id"]}},
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/export-cluster/workloads",
                json={**body, "snapshots": {pool["id"]: foreign["snapshot_id"]}},
            ).status_code
            == 404
        )


def test_cluster_identity_missing_pools_and_location_filter(settings):
    collector = CountingCollector(settings)
    app = create_app(settings, collector)
    with TestClient(app) as client:
        pool = initialized(client)["pools"][0]
        query = {k: pool[k] for k in ["project", "location", "cluster"]}
        duplicate = {
            **pool,
            "project": "another-project",
            "id": "another-project/us-central1/atlas-europe/services",
        }
        app.state.store.publish_inventory([duplicate], [duplicate["project"]], [])
        empty = client.get("/api/cluster-snapshot", params={**query, "project": duplicate["project"]}).json()
        assert empty["sources"] == [] and empty["missing"][0]["pool_name"] == "services"
        assert len(client.get("/api/cluster-snapshot", params=query).json()["sources"]) == 2
        assert (
            client.get("/api/cluster-snapshot", params={**query, "location": "different-region"}).status_code
            == 404
        )
        assert client.get("/api/cluster-snapshot", params={**query, "days": 11}).status_code == 422
        exported = client.get("/api/export/node-pools", params=query)
        assert len(list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))) == 2
        assert collector.calls == 8


def test_all_pools_retains_source_metadata_and_export_evidence(saved):
    from optipool.cluster_views import workload_rows

    saved["metrics"].update(
        cpu_rate_window_seconds=300,
        query_definition={"memory_metric": "working-set"},
        resource_status={"cpu": "available", "memory": "unavailable"},
        fallback_reason="Native failed",
    )
    scope = combine("project", "region", "cluster", [view(saved)], [])
    assert scope["sources"][0]["cpu_rate_window_seconds"] == 300
    assert scope["sources"][0]["fallback_reason"] == "Native failed"
    assert "Native failed" in workload_rows(scope)[0]["Metric evidence per pool"]
