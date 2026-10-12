import csv
import io
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from optipool.app import create_app
from optipool.comparison import compare
from optipool.estimator import Scenario, estimate
from optipool.manifests import pod_spec
from optipool.metrics import summarize
from optipool.recommendations import recommend
from optipool.resources import node_eligible
from optipool.store import Store
from optipool.topology import spread_ok
from optipool.views import SavedViews
from test_store_api import CountingCollector, initialized, wait_job


def test_pod_window_coverage_and_independent_highest_p99(saved):
    usage = summarize(saved, 1)
    pod = saved["context"]["pods"][0]
    metric = usage["pods"][pod["uid"]]
    assert metric["cpu_p99"] > 0 and metric["cpu_latest"] is not None
    assert metric["cpu_samples"] == 49 and metric["cpu_coverage"] == 1
    assert metric["cpu_sample_at"] == usage["cutoff"]
    saved["metrics"]["samples"] = [
        {
            "time": usage["cutoff"],
            "workload": pod["workload"],
            "replica": pod["uid"],
            "attributed": True,
            "cpu": 0,
            "memory": None,
        }
    ]
    sparse = summarize(saved, 1)["pods"][pod["uid"]]
    assert sparse["cpu_latest"] == 0 and sparse["cpu_p99"] is None
    assert sparse["memory_latest"] is None and sparse["cpu_coverage"] < 0.1


def test_recommendations_peak_floor_oom_and_heterogeneous_delta(saved):
    usage = summarize(saved, 3)
    first = recommend(saved, usage)["rows"][0]
    assert first["proposed"]["memory"] >= max(
        m["memory_peak"] for m in usage["pods"].values() if m["workload"] == first["workload_id"]
    )
    member = next(p for p in saved["context"]["pods"] if p["workload"] == first["workload_id"])
    member["spec"] = deepcopy(member["spec"])
    member["spec"]["containers"][0]["resources"]["requests"]["memory"] = "4Gi"
    member["container_statuses"][0]["lastState"] = {"terminated": {"reason": "OOMKilled"}}
    guarded = recommend(saved, usage)["rows"][0]
    assert guarded["proposed"]["memory"] >= 4 * 1024**3 and guarded["recovered"]["memory"] <= 0
    assert any("OOMKilled" in w for w in guarded["warnings"])
    assert any("different effective requests" in w for w in guarded["warnings"])


def test_recommendations_missing_metrics_and_status(saved):
    saved["metrics"]["samples"] = []
    for pod in saved["context"]["pods"]:
        pod.pop("container_statuses", None)
    row = recommend(saved, summarize(saved, 10))["rows"][0]
    assert row["proposed"] == {"cpu": None, "memory": None}
    assert row["recovered"] == {"cpu": None, "memory": None}
    assert row["coverage"] is None and row["status"] == "Insufficient data"
    assert any("termination evidence is absent" in w for w in row["warnings"])


@pytest.mark.parametrize(
    "mode,cap,surge,peak",
    [
        ("steady", None, "25%", 3),
        ("rollout", None, "25%", 4),
        ("hpa", 5, "25%", 5),
        ("combined", 5, "25%", 7),
        ("combined", 5, "2", 7),
    ],
)
def test_peak_replica_planning(saved, mode, cap, surge, peak):
    result = estimate(saved, Scenario(replicas=3, planning_mode=mode, hpa_max_replicas=cap, max_surge=surge))
    assert result["replicas"] == peak and len(result["placements"]) == peak
    assert result["planning"]["peak_replicas"] == peak
    assert len(result["node_budgets"]) == len(saved["nodes"]) + result["candidate_nodes"]
    assert sum(len(n["placements"]) for n in result["node_budgets"]) == peak
    for node in result["node_budgets"]:
        assert node["remaining"]["cpu"] == pytest.approx(node["ceiling"]["cpu"] - node["after"]["cpu"])


def test_peak_bounds_and_hpa_validation(saved):
    with pytest.raises(ValueError, match="Peak replicas"):
        estimate(saved, Scenario(replicas=2000, planning_mode="rollout"))
    with pytest.raises(ValueError, match="HPA maximum"):
        estimate(saved, Scenario(replicas=3, planning_mode="hpa", hpa_max_replicas=2))
    with pytest.raises(ValueError, match="Max surge"):
        estimate(saved, Scenario(planning_mode="rollout", max_surge="-1"))


def test_estimation_does_not_mutate_saved_context_or_resources(saved):
    original = deepcopy(saved)
    estimate(saved, Scenario(replicas=20, planning_mode="combined", hpa_max_replicas=25, spread_zones=True))
    assert saved == original


def test_nullable_resources_and_invalid_nested_manifest_http(settings):
    with TestClient(create_app(settings)) as client:
        pool = initialized(client)["pools"][0]
        manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {"app": "test"}},
                "template": {
                    "metadata": {"labels": {"app": "test"}},
                    "spec": {"containers": [{"name": "test", "resources": None}]},
                },
            },
        }
        response = client.post(
            "/api/estimate", params={"pool_id": pool["id"]}, json={"manifest": json.dumps(manifest)}
        )
        assert response.status_code == 200 and response.json()["per_replica"] == {"cpu": 0, "memory": 0}
        manifest["spec"]["template"]["spec"]["containers"][0]["resources"] = []
        response = client.post(
            "/api/estimate", params={"pool_id": pool["id"]}, json={"manifest": json.dumps(manifest)}
        )
        assert response.status_code == 422 and "resources must be an object" in response.json()["detail"]


def test_cud_not_applicable_http(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        pool = initialized(client)["pools"][0]
        saved = app.state.store.snapshot(pool_id=pool["id"])
        for component in saved["pricing"]["components"]:
            component["cud_eligible"] = False
        app.state.store.publish_snapshot(pool["id"], saved)
        result = client.post(
            "/api/estimate", params={"pool_id": pool["id"]}, json={"replicas": 10, "cpu": "2"}
        ).json()
        assert result["cost"]["available"] and result["cost"]["on_demand_monthly"] > 0
        assert result["cost"]["cud_status"] == "not_applicable" and result["cost"]["cud_3y_monthly"] is None


def test_zero_cud_price_is_available(saved):
    from optipool.pricing import cost

    for component in saved["pricing"]["components"]:
        component["cud_eligible"] = True
        component["cud_3y_hourly"] = 0
    quote = cost(saved["pricing"], 2)
    assert quote["cud_status"] == "available" and quote["cud_3y_monthly"] == 0
    assert quote["commitment_3y_obligation"] == 0


def test_normalized_empty_node_selector_term_matches_no_nodes(saved):
    spec = pod_spec(
        {
            "containers": [{"name": "test", "resources": None}],
            "affinity": {
                "nodeAffinity": {
                    "requiredDuringSchedulingIgnoredDuringExecution": {"nodeSelectorTerms": [{}]}
                }
            },
        }
    )
    assert not node_eligible(saved["nodes"][0], spec)


def test_hard_spread_domains_affinity_and_min_domains(saved):
    nodes = deepcopy(saved["nodes"][:2])
    for i, node in enumerate(nodes):
        node["labels"]["topology.kubernetes.io/zone"] = f"zone-{i}"
        node["labels"]["pool"] = str(i)
    term = {
        "topologyKey": "topology.kubernetes.io/zone",
        "whenUnsatisfiable": "DoNotSchedule",
        "maxSkew": 1,
        "labelSelector": {"matchLabels": {"app": "new"}},
    }
    spec = {"topologySpreadConstraints": [term]}
    pods = [{"node": nodes[0]["name"], "namespace": "default", "labels": {"app": "new"}}]
    assert not spread_ok(nodes[0], spec, {"app": "new"}, "default", pods, nodes)
    assert spread_ok(nodes[1], spec, {"app": "new"}, "default", pods, nodes)
    spec["nodeSelector"] = {"pool": "0"}
    assert spread_ok(nodes[0], spec, {"app": "new"}, "default", pods, nodes)
    term["nodeAffinityPolicy"] = "Ignore"
    assert not spread_ok(nodes[0], spec, {"app": "new"}, "default", pods, nodes)
    term["nodeAffinityPolicy"] = "Honor"
    term["minDomains"] = 2
    assert not spread_ok(nodes[0], spec, {"app": "new"}, "default", pods, nodes)


def test_snapshot_comparison_uses_uid_and_reports_changes(saved):
    after = deepcopy(saved)
    after["id"] = "after"
    after["nodes"][0]["requested"]["cpu"] += 0.5
    after["context"]["pods"][0]["uid"] = "replacement-uid"
    after["workloads"][0]["desired"] += 1
    result = compare(saved, after)
    assert result["delta"]["cpu"] == pytest.approx(0.5)
    assert {r["change"] for r in result["changes"] if r["entity"] == "pods"} == {"Removed", "Added"}
    assert any("desired" in r["fields"] for r in result["changes"])


def test_cache_deduplicates_cold_reads_observes_refresh_and_bounds_memory(settings, saved, monkeypatch):
    import optipool.views as module

    store = Store(settings.database)
    first = store.publish_snapshot(saved["pool"]["id"], saved)
    calls = []
    original = module.summarize
    monkeypatch.setattr(module, "summarize", lambda *args: (calls.append(1), original(*args))[1])
    views = SavedViews(store)
    with ThreadPoolExecutor(max_workers=20) as workers:
        values = list(workers.map(lambda _: views.get(saved["pool"]["id"], 3), range(20)))
    assert len(calls) == 1 and all(v == values[0] for v in values)
    assert json.loads(values[0])["id"] == first
    second = store.publish_snapshot(saved["pool"]["id"], saved)
    assert json.loads(views.get(saved["pool"]["id"], 3))["id"] == second
    assert len(calls) == 2
    bounded = SavedViews(store, max_bytes=len(values[0]) + 100)
    bounded.get(saved["pool"]["id"], 3)
    bounded.get(saved["pool"]["id"], 1)
    assert bounded.bytes <= bounded.max_bytes and len(bounded.entries) <= 1
    assert views.get("unknown", 3) is None
    store.close()


def test_new_api_reads_exports_and_compare_preserve_collection_contract(settings):
    collector = CountingCollector(settings)
    app = create_app(settings, collector)
    with TestClient(app) as client:
        a, b = initialized(client)["pools"][:2]
        query = {"pool_id": a["id"], "days": 10}
        before = client.get("/api/snapshot", params=query).json()
        assert before["usage"]["pods"] and before["pods"][0]["containers"]
        assert client.get("/api/recommendations", params=query).json()["snapshot_id"] == before["id"]
        rows = list(
            csv.DictReader(
                io.StringIO(client.get("/api/export/pods", params=query).content.decode("utf-8-sig"))
            )
        )
        assert rows[0]["Window days"] == "10" and rows[0]["CPU p99 cores"]
        assert client.get("/api/recommendations", params={**query, "headroom": 101}).status_code == 422
        job = client.post("/api/refresh/pool", params={"pool_id": a["id"]}, json={}).json()
        assert wait_job(client, job["id"])["state"] == "succeeded"
        after = client.get("/api/snapshot", params=query).json()
        assert after["id"] != before["id"]
        assert (
            client.get("/api/recommendations", params={**query, "snapshot_id": before["id"]}).json()[
                "snapshot_id"
            ]
            == before["id"]
        )
        assert len(client.get("/api/snapshots", params=query).json()) == 2
        result = client.get(
            "/api/snapshots/compare", params={**query, "before": before["id"], "after": after["id"]}
        )
        assert result.status_code == 200 and result.json()["delta"]["cpu"] == 0
        foreign = client.get("/api/snapshot", params={"pool_id": b["id"]}).json()
        assert (
            client.get(
                "/api/snapshots/compare", params={**query, "before": foreign["id"], "after": after["id"]}
            ).status_code
            == 404
        )
        assert (
            client.get("/api/recommendations", params={**query, "snapshot_id": foreign["id"]}).status_code
            == 404
        )
        assert collector.calls == 9
        # Compact pool exports must not decompress any full snapshot.
        app.state.store.snapshot = lambda **kwargs: pytest.fail("pool export read full snapshot")
        assert client.get("/api/export/node-pools").status_code == 200


def test_inventory_and_pool_lookup_use_one_query(settings, saved):
    store = Store(settings.database)
    pool = saved["pool"]
    store.publish_inventory([pool], [pool["project"]], [])
    store.publish_snapshot(pool["id"], saved)
    queries = []
    store.db.set_trace_callback(queries.append)
    assert store.inventory()[0]["snapshot_summary"]["node_count"] == len(saved["nodes"])
    assert len(queries) == 1
    queries.clear()
    assert store.pool(pool["id"])["id"] == pool["id"] and len(queries) == 1
    store.close()


def test_compact_core_matches_full_snapshot_and_supports_legacy_rows(settings, saved):
    store = Store(settings.database)
    sid = store.publish_snapshot(saved["pool"]["id"], saved)
    full = store.snapshot(snapshot_id=sid)
    core = store.snapshot(snapshot_id=sid, include_metrics=False)
    assert core == {k: v for k, v in full.items() if k != "metrics"}
    with store.db:
        full_bytes, core_bytes = store.db.execute(
            "SELECT length(s.payload),length(c.payload) FROM snapshots s JOIN snapshot_core c ON c.snapshot_id=s.id WHERE s.id=?",
            (sid,),
        ).fetchone()
        assert core_bytes < full_bytes / 4
        store.db.execute("DELETE FROM snapshot_core WHERE snapshot_id=?", (sid,))
    assert store.snapshot(snapshot_id=sid, include_metrics=False) == core
    store.close()


def test_replica_window_excludes_incompatible_sample_memory_definition(saved):
    from optipool.metrics import summarize

    uid = saved["context"]["pods"][0]["uid"]
    workload = saved["context"]["pods"][0]["workload"]
    cutoff = saved["metrics"]["cutoff"]
    saved["metrics"].update(
        memory_definition="Working set",
        samples=[
            {
                "time": cutoff - i * 300,
                "replica": uid,
                "workload": workload,
                "attributed": True,
                "memory": 100,
                "memory_definition": "Working set",
            }
            for i in range(20)
        ],
    )
    saved["metrics"]["samples"].extend(
        [
            {
                "time": cutoff - i * 300,
                "replica": uid,
                "workload": workload,
                "attributed": True,
                "memory": 9999,
                "memory_definition": "Non-evictable memory",
            }
            for i in range(20)
        ]
    )
    usage = summarize(saved, 1)
    assert usage["pods"][uid]["memory_p99"] == 100
    assert any("incompatible" in warning for warning in usage["warnings"])


def test_sampled_memory_burst_is_separate_from_p99_and_preserved_as_historical_floor(saved):
    pod = saved["context"]["pods"][0]
    cutoff = saved["metrics"]["cutoff"]
    saved["metrics"].update(
        cadence_seconds=60,
        samples=[
            {
                "time": cutoff - i * 60,
                "replica": "deleted-replica",
                "workload": pod["workload"],
                "attributed": True,
                "cpu": 0.1,
                "memory": (4 if i == 1 else 1) * 1024**3,
            }
            for i in range(201)
        ],
    )
    usage = summarize(saved, 1)
    metric = usage["workloads"][pod["workload"]]
    assert metric["memory_p99"] == 1024**3
    assert metric["memory_peak"] == 4 * 1024**3
    assert metric["memory_peak_replica"] == "deleted-replica"
    row = next(r for r in recommend(saved, usage)["rows"] if r["workload_id"] == pod["workload"])
    assert row["proposed"]["memory"] >= 4 * 1024**3
