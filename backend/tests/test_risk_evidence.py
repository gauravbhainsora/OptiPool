"""Risk evidence at saved HTTP/export and read-only monitoring adapter boundaries."""

import csv
import io

from fastapi.testclient import TestClient
from optipool.app import create_app
from test_p99_evidence import history
from test_store_api import CountingCollector, initialized


def risk_history(snapshot, throttled=20, periods=100, oom=0, restart=0):
    cutoff = snapshot["metrics"]["cutoff"]
    times = list(range(cutoff - 86400, cutoff + 1, 300))
    history(snapshot, times, times)
    series = []
    for pod in snapshot["context"]["pods"]:
        # Reset at noon. Literal delta over 288 intervals: throttle 5760 / periods 28800.
        for kind, increment in [
            ("throttled_periods", throttled),
            ("enforcement_periods", periods),
            ("oom_events", oom),
            ("restarts", restart),
        ]:
            values = [[t, (i % 144) * increment] for i, t in enumerate(times)]
            series.append(
                dict(
                    replica=pod["uid"],
                    workload=pod["workload"],
                    container=pod["spec"]["containers"][0]["name"],
                    identity="instance-1",
                    kind=kind,
                    values=values,
                )
            )
    snapshot["metrics"]["risk"] = dict(
        source="Synthetic reset-aware counters", cadence_seconds=300, series=series, warnings=[]
    )


def test_high_throttling_and_historical_oom_withhold_independent_reductions(settings):
    collector = CountingCollector(settings)
    app = create_app(settings, collector)
    with TestClient(app) as client:
        pool = initialized(client)["pools"][0]
        snapshot = app.state.store.snapshot(pool_id=pool["id"])
        risk_history(snapshot, oom=1)
        sid = app.state.store.publish_snapshot(pool["id"], snapshot)
        query = dict(pool_id=pool["id"], snapshot_id=sid, days=1)
        before = collector.calls
        saved = client.get("/api/snapshot", params=query).json()
        pod = saved["pods"][0]
        risk = saved["usage"]["pods"][pod["uid"]]["cpu_risk"]
        assert risk["numerator"] == 5720
        assert risk["denominator"] == 28600
        assert risk["ratio"] == 0.2 and risk["adverse"]
        row = client.get("/api/recommendations", params=query).json()["rows"][0]
        assert row["cpu_p99"] == 0.05
        assert row["proposed"] == {"cpu": None, "memory": None}
        assert any("throttl" in r for r in row["reduction_reasons"]["cpu"])
        assert any("OOM" in r for r in row["reduction_reasons"]["memory"])
        response = client.get("/api/export/workloads", params=query)
        exported = next(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
        assert exported["CPU risk ratio"] == "0.2"
        assert exported["CPU reduction eligible"] == "False"
        assert "OOM" in exported["Memory risk reasons"]
        assert collector.calls == before


def test_required_missing_denominator_and_legacy_risk_are_unknown_not_zero(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        pool = initialized(client)["pools"][0]
        snapshot = app.state.store.snapshot(pool_id=pool["id"])
        risk_history(snapshot, throttled=0)
        snapshot["metrics"]["risk"]["series"] = [
            s for s in snapshot["metrics"]["risk"]["series"] if s["kind"] != "enforcement_periods"
        ]
        sid = app.state.store.publish_snapshot(pool["id"], snapshot)
        query = dict(pool_id=pool["id"], snapshot_id=sid, days=1)
        row = client.get("/api/recommendations", params=query).json()["rows"][0]
        assert row["cpu_risk"]["denominator"] is None and row["cpu_risk"]["ratio"] is None
        assert row["proposed"]["cpu"] is None and row["proposed"]["memory"] is not None
        snapshot["metrics"].pop("risk")
        sid = app.state.store.publish_snapshot(pool["id"], snapshot)
        row = client.get("/api/recommendations", params={**query, "snapshot_id": sid}).json()["rows"][0]
        assert row["memory_risk"]["status"] == "unknown"
        assert row["memory_risk"]["oom_events"] is None
        assert row["proposed"] == {"cpu": None, "memory": None}


def test_risk_policy_threshold_and_explicit_optional_unknown(settings):
    settings.throttling_risk_threshold = 0.2
    settings.min_risk_observation_seconds = 43200
    settings.min_risk_coverage = 0.5
    app = create_app(settings)
    with TestClient(app) as client:
        pool = initialized(client)["pools"][0]
        snapshot = app.state.store.snapshot(pool_id=pool["id"])
        risk_history(snapshot, throttled=20)
        for series in snapshot["metrics"]["risk"]["series"]:
            series["values"] = [p for p in series["values"] if p[0] >= snapshot["metrics"]["cutoff"] - 43200]
        sid = app.state.store.publish_snapshot(pool["id"], snapshot)
        query = dict(pool_id=pool["id"], snapshot_id=sid, days=1)
        row = client.get("/api/recommendations", params=query).json()["rows"][0]
        assert row["cpu_risk"]["status"] == "available" and row["cpu_risk"]["adverse"]
        assert row["cpu_risk"]["selected_window_coverage"] == 0.5
        assert row["proposed"]["cpu"] is None


def test_read_only_gmp_risk_counters_scope_lifetimes_and_survive_optional_failures(saved, settings):
    import time

    from optipool.collector import CloudCollector

    settings.collect_risk_metrics = True
    settings.risk_oom_counter_metric = "existing_pod_container_oom_events_total"
    pod = saved["context"]["pods"][0]
    now = int(time.time())
    pod["created"] = now - 900
    collector = object.__new__(CloudCollector)
    collector.settings = settings
    queries = []

    def get(url, params):
        query = params["query"]
        queries.append(query)
        metric = dict(
            namespace=pod["namespace"],
            pod=pod["name"],
            container=pod["spec"]["containers"][0]["name"],
            uid=pod["uid"],
            id="container-generation-a",
        )
        if query.startswith("existing_pod_container_oom"):
            raise ValueError("optional OOM source forbidden")
        if query.startswith("container_cpu_cfs_") or query.startswith("kube_pod_container_status_restarts"):
            return dict(
                status="success",
                data=dict(
                    resultType="matrix",
                    result=[
                        dict(
                            metric=metric,
                            values=[
                                [now - 1200, "100"],
                                [now - 900, "100"],
                                [now - 600, "150"],
                                [now - 300, "5"],
                                [now, "25"],
                            ],
                        )
                    ],
                ),
            )
        return dict(status="success", data=dict(result=[dict(metric=metric, values=[[now, "0.2"]])]))

    collector.get = get
    result = collector.metrics(saved["pool"], saved)
    assert result["samples"] and result["risk"]["series"]
    cpu = next(s for s in result["risk"]["series"] if s["kind"] == "throttled_periods")
    assert min(t for t, _ in cpu["values"]) == pod["created"]
    assert cpu["replica"] == pod["uid"] and cpu["container"] == pod["spec"]["containers"][0]["name"]
    assert all("project_id=" in q and "namespace=" in q and "pod=~" in q for q in queries)
    assert "OOM" in " ".join(result["risk"]["warnings"])
    assert result["source"] == "GMP cAdvisor"


def test_container_counts_weighted_but_one_adverse_container_withholds_cpu(settings):
    from copy import deepcopy

    app = create_app(settings)
    with TestClient(app) as client:
        pool = initialized(client)["pools"][0]
        snapshot = app.state.store.snapshot(pool_id=pool["id"])
        risk_history(snapshot, throttled=1, periods=100)
        first = snapshot["context"]["pods"][0]
        sidecar = deepcopy(first["spec"]["containers"][0])
        sidecar["name"] = "small-throttled-sidecar"
        first["spec"]["containers"].append(sidecar)
        original = [s for s in snapshot["metrics"]["risk"]["series"] if s["replica"] == first["uid"]]
        for series in original:
            item = deepcopy(series)
            item["container"] = sidecar["name"]
            increment = dict(throttled_periods=1, enforcement_periods=2, oom_events=0, restarts=0)[
                item["kind"]
            ]
            item["values"] = [[t, i * increment] for i, (t, _) in enumerate(item["values"])]
            snapshot["metrics"]["risk"]["series"].append(item)
        sid = app.state.store.publish_snapshot(pool["id"], snapshot)
        query = dict(pool_id=pool["id"], snapshot_id=sid, days=1)
        saved = client.get("/api/snapshot", params=query).json()
        risk = saved["usage"]["pods"][first["uid"]]["cpu_risk"]
        assert abs(risk["ratio"] - 574 / 29176) < 1e-12
        assert risk["adverse"] and risk["ratio"] < 0.10
        row = client.get("/api/recommendations", params=query).json()["rows"][0]
        assert row["proposed"]["cpu"] is None


def test_signed_iap_risk_reads_exports_and_windows_use_only_saved_data(settings, monkeypatch):
    import json
    import time

    import jwt
    from cryptography.hazmat.primitives.asymmetric import ec
    from google.oauth2 import id_token
    from openpyxl import load_workbook

    settings.auth_mode = "iap"
    settings.iap_audience = "/projects/123/global/backendServices/456"
    key = ec.generate_private_key(ec.SECP256R1())
    jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="risk-test", alg="ES256", use="sig")
    monkeypatch.setattr(id_token, "_fetch_certs", lambda *args: {"keys": [jwk]})
    token = jwt.encode(
        dict(
            iss="https://cloud.google.com/iap",
            aud=settings.iap_audience,
            sub="123",
            email="test@example.org",
            iat=int(time.time()) - 5,
            exp=int(time.time()) + 300,
        ),
        key,
        algorithm="ES256",
        headers={"kid": "risk-test"},
    )
    collector = CountingCollector(settings)
    app = create_app(settings, collector)
    with TestClient(app, headers={"x-goog-iap-jwt-assertion": token}) as client:
        pool = initialized(client)["pools"][0]
        snapshot = app.state.store.snapshot(pool_id=pool["id"])
        risk_history(snapshot, throttled=0, restart=1)
        sid = app.state.store.publish_snapshot(pool["id"], snapshot)
        query = dict(pool_id=pool["id"], snapshot_id=sid, days=1)
        assert (
            client.get(
                "/api/recommendations", params=query, headers={"x-goog-iap-jwt-assertion": ""}
            ).status_code
            == 401
        )
        before = collector.calls
        row = client.get("/api/recommendations", params=query).json()["rows"][0]
        assert row["reduction_eligible"] == {"cpu": True, "memory": False}
        assert row["proposed"]["cpu"] is not None and row["proposed"]["memory"] is None
        row = client.get("/api/recommendations", params={**query, "days": 10}).json()["rows"][0]
        assert row["cpu_risk"]["status"] == "unknown" and row["memory_risk"]["adverse"]
        for table in ["pods", "workloads"]:
            response = client.get(f"/api/export/{table}", params={**query, "format": "xlsx"})
            values = list(load_workbook(io.BytesIO(response.content)).active.values)
            exported = dict(zip(values[0], values[1], strict=True))
            assert exported["Memory risk restarts"] > 0
            assert exported["CPU risk required"] is True
        assert collector.calls == before


def test_deleted_replica_risk_remains_bounded_reproducible_and_blocks_reduction(settings):
    from copy import deepcopy

    app = create_app(settings)
    with TestClient(app) as client:
        pool = initialized(client)["pools"][0]
        first = app.state.store.snapshot(pool_id=pool["id"])
        risk_history(first, throttled=0)
        deleted = first["context"]["pods"][0]
        for series in first["metrics"]["risk"]["series"]:
            if series["replica"] == deleted["uid"] and series["kind"] == "oom_events":
                series["values"][-1][1] = 3
        old_id = app.state.store.publish_snapshot(pool["id"], first)
        old_query = dict(pool_id=pool["id"], snapshot_id=old_id, days=1)
        before = client.get("/api/snapshot", params=old_query).json()
        second = deepcopy(first)
        second["context"]["pods"] = [p for p in second["context"]["pods"] if p["uid"] != deleted["uid"]]
        second["workloads"][0]["pool_replicas"] -= 1
        second["metrics"]["samples"] = [
            s for s in second["metrics"]["samples"] if s["replica"] != deleted["uid"]
        ]
        second["metrics"]["replica_evidence"].pop(deleted["uid"])
        second["metrics"]["risk"]["series"] = [
            s for s in second["metrics"]["risk"]["series"] if s["replica"] != deleted["uid"]
        ]
        new_id = app.state.store.publish_snapshot(pool["id"], second)
        query = dict(pool_id=pool["id"], snapshot_id=new_id, days=1)
        row = client.get("/api/recommendations", params=query).json()["rows"][0]
        assert row["memory_risk"]["oom_events"] == 3 and row["memory_risk"]["adverse"]
        assert row["proposed"]["memory"] is None
        new = client.get("/api/snapshot", params=query).json()
        historical = next(p for p in new["usage"]["historical_replicas"] if p["uid"] == deleted["uid"])
        assert historical["memory_risk"]["oom_events"] == 3
        assert client.get("/api/snapshot", params=old_query).json() == before


def test_zero_denominator_is_unknown_and_configured_opt_out_is_visible(settings):
    settings.require_cpu_risk_evidence = False
    app = create_app(settings)
    with TestClient(app) as client:
        pool = initialized(client)["pools"][0]
        snapshot = app.state.store.snapshot(pool_id=pool["id"])
        risk_history(snapshot, throttled=0, periods=0)
        sid = app.state.store.publish_snapshot(pool["id"], snapshot)
        row = client.get(
            "/api/recommendations", params=dict(pool_id=pool["id"], snapshot_id=sid, days=1)
        ).json()["rows"][0]
        assert row["cpu_risk"]["status"] == "unknown"
        assert row["cpu_risk"]["denominator"] == 0 and row["cpu_risk"]["ratio"] is None
        assert row["cpu_risk"]["required"] is False and row["proposed"]["cpu"] is not None
        assert "Optional" in " ".join(row["cpu_risk"]["reasons"])
