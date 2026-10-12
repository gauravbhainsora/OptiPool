from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from optipool.app import create_app
from optipool.estimator import Scenario, ServiceBundle, estimate
from optipool.pool_design import PoolDesign, design
from optipool.store import Store
from test_domain import deployment, empty_nodes
from test_store_api import CountingCollector, initialized, wait_job


def bundle(cpu="1700m"):
    return ServiceBundle(
        services=[Scenario(name="api", cpu=cpu, replicas=1), Scenario(name="worker", cpu=cpu, replicas=1)]
    )


def test_bundle_consumes_shared_capacity_and_preserves_inputs(saved):
    empty_nodes(saved)
    saved["nodes"] = saved["nodes"][:1]
    original = deepcopy(saved)
    assert estimate(saved, bundle().services[0])["outcome"] == "Fits"
    result = estimate(saved, bundle())
    assert result["outcome"] == "Needs nodes" and result["additional_nodes"] == 1
    assert result["per_replica"] is None and result["replicas"] == 2
    assert result["total_requests"]["cpu"] == pytest.approx(3.4)
    assert {p["service"] for p in result["placements"]} == {"default/api", "default/worker"}
    assert all(s["placed_replicas"] == 1 for s in result["services"])
    assert set(result["node_budgets"][0]["service_rejections"]) == {"default/api", "default/worker"}
    assert saved == original


def test_bundle_checks_aggregated_namespace_quotas_and_peak_bounds(saved):
    empty_nodes(saved)
    saved["context"]["quotas"] = [
        {"metadata": {"namespace": "default"}, "status": {"hard": {"requests.cpu": "3"}, "used": {}}}
    ]
    assert estimate(saved, bundle().services[0])["outcome"] == "Fits"
    result = estimate(saved, bundle())
    assert result["outcome"] == "Blocked constraints" and "combined service demand" in result["reason"]
    with pytest.raises(ValueError, match="Peak replicas"):
        estimate(
            saved,
            ServiceBundle(services=[Scenario(name="a", replicas=1500), Scenario(name="b", replicas=501)]),
        )
    with pytest.raises(ValueError, match="unique"):
        estimate(saved, ServiceBundle(services=[Scenario(name="same"), Scenario(name="same")]))
    saved["context"]["quotas"] = []
    result = estimate(
        saved,
        ServiceBundle(
            services=[
                Scenario(name="a", replicas=2, planning_mode="combined", hpa_max_replicas=4),
                Scenario(name="b", replicas=3),
            ]
        ),
    )
    assert result["replicas"] == 8 and result["planning"]["surge_replicas"] == 1


def test_bundle_respects_affinity_between_proposed_services(saved):
    empty_nodes(saved)
    saved["nodes"] = saved["nodes"][:1]
    spec = {
        "containers": [{"name": "alpha", "resources": {"requests": {"cpu": "100m"}}}],
        "affinity": {
            "podAntiAffinity": {
                "requiredDuringSchedulingIgnoredDuringExecution": [
                    {
                        "labelSelector": {"matchLabels": {"app": "beta"}},
                        "topologyKey": "kubernetes.io/hostname",
                    }
                ]
            }
        },
    }
    result = estimate(
        saved,
        ServiceBundle(
            services=[
                Scenario(name="alpha", manifest=deployment(spec, labels={"app": "alpha"}, replicas=1)),
                Scenario(name="beta", cpu="100m", replicas=1),
            ]
        ),
    )
    assert result["additional_nodes"] == 1
    assert len({p["node"] for p in result["placements"]}) == 2


def design_input(saved, **changes):
    p = saved["pool"]
    return PoolDesign(
        project=p["project"],
        location=p["location"],
        cluster=p["cluster"],
        name="new-services",
        snapshots={p["id"]: saved["id"]},
        services=[Scenario(name="api", cpu="1", replicas=4)],
        **changes,
    )


def test_design_uses_empty_pool_saved_overhead_prices_and_provenance(saved):
    empty_nodes(saved)
    original = deepcopy(saved)
    report = design([saved], design_input(saved))
    candidate = report["candidates"][0]
    assert candidate["complete"] and candidate["configuration"]["total_nodes"] == 2
    assert sum(candidate["configuration"]["nodes_by_zone"].values()) == 2
    assert all(n["planned"] for n in candidate["assessment"]["node_budgets"])
    assert candidate["assessment"]["policy_factor"] == 0.8
    assert candidate["assessment"]["cost"]["on_demand_hourly"] == pytest.approx(0.408)
    assert candidate["profile"]["snapshot_id"] == saved["id"]
    assert saved == original
    saved["node_templates"] = []
    unavailable = design([saved], design_input(saved))
    assert unavailable["recommended_profile"] is None
    assert not unavailable["candidates"][0]["complete"]


def test_design_ranking_prefers_supported_complete_quoted_profiles(saved):
    other = deepcopy(saved)
    other["pool"]["id"] += "-unquoted"
    other["pricing"] = {}
    report = design([other, saved], design_input(saved))
    assert report["recommended_profile"] == saved["pool"]["id"]
    assert report["candidates"][1]["assessment"]["cost"]["available"] is False
    assert "unquoted profiles may be cheaper" in report["ranking"]


def test_api_bundle_design_pins_history_and_no_collection(settings):
    collector = CountingCollector(settings)
    with TestClient(create_app(settings, collector)) as client:
        pools = initialized(client)["pools"]
        pool = pools[0]
        selection = {k: pool[k] for k in ["project", "location", "cluster"]}
        pins = {"pool_id": pool["id"], "snapshot_id": pool["snapshot_id"]}
        result = client.post("/api/estimate-bundle", params=pins, json=bundle("100m").model_dump())
        assert result.status_code == 200 and result.json()["kind"] == "capacity_bundle"
        profiles = client.get("/api/node-pool-profiles", params=selection).json()["profiles"]
        body = {
            **selection,
            "name": "new-services",
            "services": bundle("100m").model_dump()["services"],
            "snapshots": {p["pool_id"]: p["snapshot_id"] for p in profiles},
        }
        report = client.post("/api/node-pool-design", json=body)
        assert report.status_code == 200 and report.json()["id"]
        assert len(report.json()["candidates"]) == 2
        assert all(
            h["result"]["kind"] != "node_pool_design"
            for h in client.get("/api/estimates", params={"pool_id": pool["id"]}).json()
        )
        assert collector.calls == 8
        refresh = client.post("/api/refresh/pool", params={"pool_id": pool["id"]}, json={}).json()
        assert wait_job(client, refresh["id"])["state"] == "succeeded"
        assert (
            client.post("/api/estimate-bundle", params=pins, json=bundle("100m").model_dump()).json()[
                "snapshot_id"
            ]
            == pool["snapshot_id"]
        )
        assert (
            client.post("/api/node-pool-design", json=body).json()["candidates"][0]["profile"]["snapshot_id"]
            in body["snapshots"].values()
        )
        assert collector.calls == 9
        assert (
            client.post(
                "/api/estimate-bundle",
                params={**pins, "snapshot_id": pools[2]["snapshot_id"]},
                json=bundle().model_dump(),
            ).status_code
            == 404
        )
        assert client.post("/api/node-pool-design", json={**body, "name": pool["name"]}).status_code == 422
        assert (
            client.post(
                "/api/node-pool-design", json={**body, "snapshots": {pools[2]["id"]: pools[2]["snapshot_id"]}}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/node-pool-design", json={**body, "snapshots": {pool["id"]: pools[2]["snapshot_id"]}}
            ).status_code
            == 404
        )


def test_design_retains_all_supporting_snapshots_and_scopes_history(settings, saved, tmp_path):
    store = Store(settings.database)
    first = store.publish_snapshot(saved["pool"]["id"], saved)
    other = deepcopy(saved)
    other["pool"]["id"] += "-second"
    second = store.publish_snapshot(other["pool"]["id"], other)
    saved_report = store.save_estimate(
        first, {}, {"kind": "node_pool_design", "name": "report"}, "test", sources=[first, second]
    )
    store.publish_snapshot(saved["pool"]["id"], saved)
    store.publish_snapshot(other["pool"]["id"], other)
    with store.db:
        store.db.execute("UPDATE snapshots SET created=1 WHERE id IN (?,?)", (first, second))
    store.prune()
    assert store.snapshot(snapshot_id=first) and store.snapshot(snapshot_id=second)
    assert store.designs([saved["pool"]["id"]])[0]["id"] == saved_report
    assert store.designs(["foreign-pool"]) == [] and store.estimates(saved["pool"]["id"]) == []
    backup = str(tmp_path / "design-backup.db")
    store.backup(backup)
    restored = Store(backup)
    restored.prune()
    assert restored.snapshot(snapshot_id=second) and restored.designs([saved["pool"]["id"]])
    restored.close()
    with store.db:
        store.db.execute("DELETE FROM estimates WHERE id=?", (saved_report,))
    store.prune()
    assert store.snapshot(snapshot_id=first) is None and store.snapshot(snapshot_id=second) is None
    store.close()
