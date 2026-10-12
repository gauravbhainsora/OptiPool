"""Historical source adapter and saved-publication boundary fixtures."""

import json
import time
from copy import deepcopy

from optipool.collector import CloudCollector
from optipool.config import Settings
from optipool.store import Store
from optipool.views import SavedViews


def response(series):
    return {"status": "success", "data": {"resultType": "matrix", "result": series}}


def metadata(pool, now, **changes):
    return {
        "project_id": pool["project"],
        "location": pool["location"],
        "cluster": pool["cluster"],
        "namespace": "shop",
        "pod": "api-old",
        "uid": "deleted-before-import",
        "controller_kind": "Deployment",
        "controller_name": "api",
        "controller_uid": "d",
        "owner_kind": "ReplicaSet",
        "owner_name": "api-old-rs",
        "owner_uid": "rs-old",
        "node": "deleted-node",
        "node_uid": "node-old-uid",
        "node_pool": pool["name"],
        "created": str(now - 20000),
        "start": str(now - 18000),
        "end": str(now - 1000),
        **changes,
    }


def adapter(settings, saved, labels=None, usage=None, failure=None, usage_identity=True):
    from optipool.collector import normalize
    from test_collectors import raw_fixture

    core = normalize(saved["pool"], raw_fixture(), [])
    now = int(time.time())
    labels = labels if labels is not None else [metadata(saved["pool"], now)]
    requests = []
    collector = object.__new__(CloudCollector)
    collector.settings = settings
    collector.pages = lambda *args: []

    def get(url, params):
        requests.append(params)
        query = params["query"]
        if query.startswith("optipool_pod_membership"):
            if failure:
                raise ValueError(failure)
            return response([{"metric": m, "values": [[now, "1"]]} for m in labels])
        if "sum by(namespace,pod,uid,node,node_uid)" in query:
            label = labels[0]
            match = {k: label[k] for k in ["namespace", "pod", "uid", "node", "node_uid"]}
            match.update({k: label[k] for k in ["project_id", "location", "cluster"]})
            if not usage_identity:
                match = {k: match[k] for k in ["namespace", "pod"]}
            values = usage or [
                [now - 16000 + i * 300, "9" if "rate(" in query else "8192"] for i in range(30)
            ]
            return response([{"metric": match, "values": values}])
        return response([])

    collector.get = get
    return collector, core, requests


def configured(settings):
    return Settings(**{**settings.model_dump(), "historical_metadata_metric": "optipool_pod_membership"})


def core_app(settings, core):
    from optipool.app import create_app
    from optipool.demo import DemoCollector

    class CoreCollector(DemoCollector):
        def discover(self):
            return [core["pool"]], [core["pool"]["project"]], []

        def collect(self, pool):
            return deepcopy(core)

    return create_app(settings, CoreCollector(settings))


def test_deleted_before_first_import_can_win_saved_highest_replica_p99(settings, saved):
    settings = configured(settings)
    collector, core, requests = adapter(settings, saved)
    core["metrics"] = collector.metrics(core["pool"], core)
    store = Store(settings.database)
    sid = store.publish_snapshot(core["pool"]["id"], core)
    view = json.loads(SavedViews(store).get(core["pool"]["id"], 1, sid))
    metric = view["usage"]["workloads"]["shop/Deployment/api"]
    assert metric["cpu_p99"] == 9
    assert metric["cpu_replica"] == "deleted-before-import"
    assert metric["historical_replicas_observed"] == 1
    assert view["workloads"][0]["pool_replicas"] == 1
    discovery = view["usage"]["historical_discovery"]
    assert discovery["status"] == "partial" and discovery["replicas_discovered"] == 1
    assert discovery["metadata_metric"] == "optipool_pod_membership"
    historical = [r for r in requests if 'pod="api-old"' in r["query"]]
    assert len(historical) == 2
    assert all(r["end"] <= int(time.time()) - 1000 for r in historical)
    assert all("sum by(namespace,pod,uid,node,node_uid)" in r["query"] for r in historical)
    store.close()


def test_discovery_rejects_ambiguous_names_foreign_pool_and_missing_labels(settings, saved):
    settings = configured(settings)
    now = int(time.time())
    first = metadata(saved["pool"], now)
    replacement = {**first, "uid": "replacement", "created": str(now - 18000)}
    foreign = {**first, "uid": "foreign", "pod": "foreign-name", "node_pool": "elsewhere"}
    missing = {**first, "uid": "missing", "pod": "missing-name"}
    missing.pop("controller_uid")
    collector, core, requests = adapter(settings, saved, [first, replacement, foreign, missing])
    core["metrics"] = collector.metrics(core["pool"], core)
    discovery = core["metrics"]["historical_discovery"]
    assert discovery["status"] == "unavailable"
    assert discovery["replicas_discovered"] == 0
    assert any("ambiguous" in reason for reason in discovery["reasons"])
    assert any("foreign pool" in reason for reason in discovery["reasons"])
    assert any("missing required" in reason for reason in discovery["reasons"])
    assert not any("sum by(namespace,pod,uid,node,node_uid)" in r["query"] for r in requests)


def test_rate_window_and_metadata_gaps_do_not_transfer_usage(settings, saved):
    settings = configured(settings)
    now = int(time.time())
    old = metadata(saved["pool"], now, start=str(now - 16000), end=str(now - 14000))
    replacement = {
        **old,
        "uid": "new-lifetime",
        "created": str(now - 13000),
        "start": str(now - 13000),
        "end": str(now - 1000),
    }
    # A returned same-name usage point is accepted only inside the evidenced lifetime;
    # optional UID mismatch also rejects it rather than transferring to a new lifetime.
    usage = [
        [now - 16100, "999"],
        [now - 16000, "999"],
        [now - 15800, "999"],
        [now - 15700, "7"],
        [now - 13500, "999"],
    ]
    collector, core, requests = adapter(settings, saved, [old, replacement], usage)
    core["metrics"] = collector.metrics(core["pool"], core)
    samples = core["metrics"]["samples"]
    assert [(p["time"], p["cpu"]) for p in samples if "cpu" in p] == [(now - 15700, 7)]
    assert not any(p["replica"] == "new-lifetime" for p in samples)
    assert any("CPU window" in reason for reason in core["metrics"]["historical_discovery"]["reasons"])
    assert all(r["end"] - r["start"] <= 864000 for r in requests)


def test_optional_source_failure_preserves_retained_history_and_core(settings, saved):
    settings = configured(settings)
    collector, core, _ = adapter(settings, saved)
    core["metrics"] = collector.metrics(core["pool"], core)
    store = Store(settings.database)
    old = store.publish_snapshot(core["pool"]["id"], core)
    failing, fresh, _ = adapter(settings, saved, failure="permission denied")
    fresh["metrics"] = failing.metrics(fresh["pool"], fresh)
    sid = store.publish_snapshot(fresh["pool"]["id"], fresh)
    value = json.loads(SavedViews(store).get(fresh["pool"]["id"], 1, sid))
    assert value["usage"]["workloads"]["shop/Deployment/api"]["cpu_p99"] == 9
    assert value["usage"]["historical_discovery"]["status"] == "unavailable"
    assert any("permission denied" in reason for reason in value["usage"]["attribution_gaps"])
    assert store.snapshot(snapshot_id=old)["core_complete"]
    store.close()


def test_historical_usage_budget_fails_atomically_and_config_rejects_promql(settings, saved):
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(historical_metadata_metric="rate(foo[5m])")
    settings = Settings(**{**configured(settings).model_dump(), "historical_metadata_max_requests": 2})
    now = int(time.time())
    labels = [metadata(saved["pool"], now), metadata(saved["pool"], now, uid="another", pod="another-name")]
    collector, core, requests = adapter(settings, saved, labels)
    metrics = collector.metrics(core["pool"], core)
    assert metrics["samples"] == []
    assert metrics["historical_discovery"]["status"] == "unavailable"
    assert any("request limit" in reason for reason in metrics["historical_discovery"]["reasons"])
    assert len([r for r in requests if "sum by(namespace,pod,uid,node,node_uid)" in r["query"]]) <= 2


def test_signed_saved_api_exports_refresh_restart_and_retention(settings, monkeypatch, tmp_path):
    import csv
    import io

    import jwt
    from cryptography.hazmat.primitives.asymmetric import ec
    from fastapi.testclient import TestClient
    from google.oauth2 import id_token
    from openpyxl import load_workbook
    from optipool.app import create_app
    from p99_upstream_fixture import UpstreamCollector
    from test_store_api import initialized, wait_job

    settings.auth_mode = "iap"
    settings.iap_audience = "/projects/123/global/backendServices/456"
    key = ec.generate_private_key(ec.SECP256R1())
    jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="test", alg="ES256", use="sig")
    monkeypatch.setattr(id_token, "_fetch_certs", lambda *args: {"keys": [jwk]})
    signed = jwt.encode(
        {
            "iss": "https://cloud.google.com/iap",
            "aud": settings.iap_audience,
            "sub": "123",
            "email": "user@example.org",
            "iat": int(time.time()) - 5,
            "exp": int(time.time()) + 300,
        },
        key,
        algorithm="ES256",
        headers={"kid": "test"},
    )
    headers = {"x-goog-iap-jwt-assertion": signed}
    collector = UpstreamCollector(settings)
    app = create_app(settings, collector)
    with TestClient(app, headers=headers) as client:
        inventory = initialized(client)
        selected, other = inventory["pools"][:2]
        other_saved = client.get("/api/snapshot", params={"pool_id": other["id"]}).json()
        query = {"pool_id": selected["id"], "days": 1}
        view = client.get("/api/snapshot", params=query).json()
        query["snapshot_id"] = view["id"]
        assert view["usage"]["workloads"]["shop/Deployment/api"]["cpu_replica"] == "deleted-before-import"
        request_count = len(collector.cloud_requests)
        for days in [1, 3, 10]:
            assert (
                client.get("/api/snapshot", params={**query, "days": days}).json()["usage"][
                    "historical_discovery"
                ]["status"]
                == "partial"
            )
        exported = client.get("/api/export/workloads", params=query)
        rows = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
        assert rows[0]["Historical discovery status"] == "partial"
        assert rows[0]["Historical metadata metric"] == "optipool_pod_membership"
        table = list(
            load_workbook(
                io.BytesIO(client.get("/api/export/workloads", params={**query, "format": "xlsx"}).content),
                read_only=True,
            ).active.values
        )
        assert "Historical discovery reasons" in table[0]
        assert len(collector.cloud_requests) == request_count
        collector.fail = True
        job = client.post("/api/refresh/pool", params={"pool_id": selected["id"]}, json={}).json()
        assert wait_job(client, job["id"])["state"] == "succeeded"
        latest = client.get("/api/snapshot", params={"pool_id": selected["id"], "days": 1}).json()
        assert latest["usage"]["workloads"]["shop/Deployment/api"]["cpu_p99"] == 9
        assert latest["usage"]["historical_discovery"]["status"] == "unavailable"
        assert client.get("/api/snapshot", params={"pool_id": other["id"]}).json() == other_saved
        assert client.get("/api/snapshot", params=query).json() == view
        with monkeypatch.context() as clock:
            clock.setattr(time, "time", lambda: latest["saved_at"] + 31 * 86400)
            app.state.store.prune()
        assert app.state.store.snapshot(snapshot_id=view["id"]) is None
        app.state.store.backup(str(tmp_path / "restore.db"))
        count = len(collector.cloud_requests)
    settings.database = str(tmp_path / "restore.db")
    with TestClient(create_app(settings, collector), headers=headers) as client:
        assert client.get("/api/snapshot", params={"pool_id": selected["id"], "days": 1}).json() == latest
        assert len(collector.cloud_requests) == count


def test_standard_usage_labels_work_only_with_exclusive_name_lifetime(settings, saved):
    settings = configured(settings)
    now = int(time.time())
    old = metadata(saved["pool"], now, end=str(now - 10000))
    reused = {
        **old,
        "uid": "reused-name",
        "created": str(now - 9000),
        "start": str(now - 9000),
        "end": str(now - 1000),
    }
    collector, core, _ = adapter(settings, saved, [old, reused], usage_identity=False)
    metrics = collector.metrics(core["pool"], core)
    assert (
        len(
            [
                point
                for point in metrics["samples"]
                if point.get("cpu") == 9 and point["replica"] == "deleted-before-import"
            ]
        )
        == 21
    )
    assert (
        len(
            [
                point
                for point in metrics["samples"]
                if point.get("cpu") == 9 and point["replica"] == "reused-name"
            ]
        )
        == 5
    )
    assert all(
        point["time"] >= now - 9000 for point in metrics["samples"] if point["replica"] == "reused-name"
    )
    assert metrics["historical_discovery"]["replicas_discovered"] == 2


def test_controller_replacement_invalid_interval_and_node_uid_conflict_are_saved_exclusions(settings, saved):
    settings = configured(settings)
    now = int(time.time())
    old = metadata(saved["pool"], now, controller_uid="replaced-controller")
    invalid = metadata(saved["pool"], now, uid="future-interval", end=str(now + 100))
    node = metadata(saved["pool"], now, uid="node-reuse", pod="node-reuse-pod")
    changed_node = {**node, "node_uid": "replacement-node-uid"}
    collector, core, _ = adapter(settings, saved, [old, invalid, node, changed_node])
    result = collector.metrics(core["pool"], core)
    assert result["samples"] == []
    assert result["historical_discovery"]["replicas_discovered"] == 0
    assert any("controller lifetime" in reason for reason in result["historical_discovery"]["reasons"])
    assert any("invalid" in reason for reason in result["historical_discovery"]["reasons"])
    assert any("ambiguous" in reason for reason in result["historical_discovery"]["reasons"])


def test_native_usage_stays_distinct_while_discovered_identity_is_saved(settings, saved):
    import datetime

    settings = configured(settings)
    collector, core, requests = adapter(settings, saved)
    now = int(time.time())
    collector.pages = lambda url, field, params: [
        {
            "resource": {"labels": {"namespace_name": "shop", "pod_name": "api-one"}},
            "points": [
                {
                    "interval": {"endTime": datetime.datetime.fromtimestamp(now, datetime.UTC).isoformat()},
                    "value": {"doubleValue": 0.5 if "cpu/" in params["filter"] else 4096},
                }
            ],
        }
    ]
    core["metrics"] = collector.metrics(core["pool"], core)
    metrics = core["metrics"]
    assert metrics["source"] == "Native GKE Cloud Monitoring"
    assert metrics["samples"][0]["memory"] == 4096
    assert (
        metrics["historical_discovery"]["replica_evidence"]["deleted-before-import"]["controller_uid"] == "d"
    )
    assert any("incompatible" in reason for reason in metrics["historical_discovery"]["reasons"])
    assert not any("sum by(namespace,pod,uid,node,node_uid)" in r["query"] for r in requests)
    store = Store(settings.database)
    sid = store.publish_snapshot(core["pool"]["id"], core)
    assert (
        store.snapshot(snapshot_id=sid)["metrics"]["historical_discovery"] == metrics["historical_discovery"]
    )
    store.close()


def test_discovered_missing_native_incompatible_replica_withholds_otherwise_eligible_reductions(
    settings, saved
):
    import datetime

    from fastapi.testclient import TestClient
    from test_store_api import initialized

    settings = Settings(
        **{
            **configured(settings).model_dump(),
            "min_reduction_observation_seconds": 1,
            "min_reduction_coverage": 0.01,
        }
    )
    now = int(time.time())
    collector, core, requests = adapter(settings, saved)
    current = core["context"]["pods"][0]
    labels = [
        metadata(core["pool"], now),
        metadata(
            core["pool"],
            now,
            uid=current["uid"],
            pod=current["name"],
            created=str(current["created"]),
            node=current["node"],
            start=str(now - 18000),
            end=str(now),
        ),
    ]
    collector, core, requests = adapter(settings, saved, labels)
    core["context"]["pods"][0]["restarts"] = 0
    collector.pages = lambda url, field, params: [
        {
            "resource": {"labels": {"namespace_name": "shop", "pod_name": "api-one"}},
            "points": [
                {
                    "interval": {
                        "endTime": datetime.datetime.fromtimestamp(
                            now - 15000 + i * 300, datetime.UTC
                        ).isoformat()
                    },
                    "value": {"doubleValue": 0.05 if "cpu/" in params["filter"] else 8192},
                }
                for i in range(30)
            ],
        }
    ]
    core["metrics"] = collector.metrics(core["pool"], core)
    with TestClient(core_app(settings, core)) as client:
        initialized(client)
        sid = client.app.state.store.publish_snapshot(core["pool"]["id"], core)
        query = {"pool_id": core["pool"]["id"], "days": 1, "snapshot_id": sid}
        view = client.get("/api/snapshot", params=query).json()
        assert view["usage"]["pods"]["p"]["cpu_evidence"]["eligible"]
        assert view["usage"]["workloads"]["shop/Deployment/api"]["cpu_evidence"]["partial"]
        row = client.get("/api/recommendations", params=query).json()["rows"][0]
        assert row["reduction_eligible"] == {"cpu": False, "memory": False}
        assert row["proposed"] == {"cpu": None, "memory": None}
        assert "deleted-before-import" in view["usage"]["historical_discovery"]["replica_evidence"]
        assert (
            "deleted-before-import"
            in client.app.state.store.snapshot(snapshot_id=sid)["metrics"]["replica_evidence"]
        )


def test_missing_historical_memory_does_not_withhold_separately_supported_cpu(settings, saved):
    from fastapi.testclient import TestClient
    from test_store_api import initialized

    settings = Settings(
        **{
            **configured(settings).model_dump(),
            "min_reduction_observation_seconds": 1,
            "min_reduction_coverage": 0.01,
        }
    )
    now = int(time.time())
    collector, core, _ = adapter(settings, saved)
    current = core["context"]["pods"][0]
    labels = [
        metadata(core["pool"], now),
        metadata(
            core["pool"],
            now,
            uid=current["uid"],
            pod=current["name"],
            created=str(current["created"]),
            node=current["node"],
            start=str(now - 18000),
            end=str(now),
        ),
    ]
    collector, core, _ = adapter(settings, saved, labels)
    base_get = collector.get

    def get(url, params):
        if params["query"].startswith("optipool_pod_membership"):
            return base_get(url, params)
        old = 'pod="api-old"' in params["query"]
        if old and "working_set" in params["query"]:
            return response([])
        return response(
            [
                {
                    "metric": {"namespace": "shop", "pod": "api-old" if old else "api-one"},
                    "values": [
                        [
                            now - 15000 + i * 300,
                            "0.1" if old else ("0.05" if "rate(" in params["query"] else "8192"),
                        ]
                        for i in range(30)
                    ],
                }
            ]
        )

    collector.get = get
    core["metrics"] = collector.metrics(core["pool"], core)
    core["context"]["pods"][0]["restarts"] = 0
    with TestClient(core_app(settings, core)) as client:
        initialized(client)
        sid = client.app.state.store.publish_snapshot(core["pool"]["id"], core)
        query = {"pool_id": core["pool"]["id"], "days": 1, "snapshot_id": sid}
        view = client.get("/api/snapshot", params=query).json()
        metric = view["usage"]["workloads"]["shop/Deployment/api"]
        assert metric["cpu_evidence"]["eligible"] and not metric["cpu_evidence"]["partial"]
        assert metric["memory_evidence"]["partial"] and not metric["memory_evidence"]["eligible"]
        row = client.get("/api/recommendations", params=query).json()["rows"][0]
        assert row["reduction_eligible"] == {"cpu": True, "memory": False}
        assert row["proposed"]["cpu"] == 0.12
        assert row["proposed"]["memory"] is None
