"""Saved-data HTTP/export evidence contract, with no monitoring access on reads."""

import csv
import io
from copy import deepcopy

from fastapi.testclient import TestClient
from optipool.app import create_app
from test_store_api import CountingCollector, initialized


def history(snapshot, cpu_times, memory_times, created=None):
    cutoff = snapshot["metrics"]["cutoff"]
    snapshot["metrics"].update(cadence_seconds=300, cpu_rate_window_seconds=300)
    snapshot["metrics"]["samples"] = []
    snapshot["metrics"]["replica_evidence"] = {}
    for pod in snapshot["context"]["pods"]:
        if created is not None:
            pod["created"] = created
            pod["uid"] += "-young"
        snapshot["metrics"]["replica_evidence"][pod["uid"]] = {
            **pod,
            "observed_at": cutoff,
            "memberships": [
                {
                    "pool_id": snapshot["pool"]["id"],
                    "node": pod["node"],
                    "start": pod["created"],
                    "end": cutoff,
                    "provenance": "explicit synthetic placement history",
                }
            ],
        }
        for t in sorted(set(cpu_times) | set(memory_times)):
            snapshot["metrics"]["samples"].append(
                dict(
                    time=t,
                    workload=pod["workload"],
                    replica=pod["uid"],
                    attributed=True,
                    cpu=0.05 if t in cpu_times else None,
                    memory=100 * 1024**2 if t in memory_times else None,
                )
            )
    return cutoff


def test_saved_api_counts_intervals_and_gates_resources_independently(settings):
    app = create_app(settings, CountingCollector(settings))
    with TestClient(app) as client:
        pool = initialized(client)["pools"][0]
        snapshot = app.state.store.snapshot(pool_id=pool["id"])
        cutoff = snapshot["metrics"]["cutoff"]
        continuous = list(range(cutoff - 86400, cutoff + 1, 300))
        sparse = [cutoff - 86400 + i * 3600 for i in range(25)]
        history(snapshot, sparse, continuous)
        sid = app.state.store.publish_snapshot(pool["id"], snapshot)
        query = dict(pool_id=pool["id"], snapshot_id=sid, days=1)
        saved = client.get("/api/snapshot", params=query).json()
        pod = saved["pods"][0]
        evidence = saved["usage"]["pods"][pod["uid"]]["cpu_evidence"]
        assert evidence["valid_samples"] == 25
        assert evidence["represented_seconds"] == 7200
        assert evidence["eligible"] is False
        row = client.get("/api/recommendations", params=query).json()["rows"][0]
        assert row["cpu_p99"] == 0.05
        assert row["proposed"]["cpu"] is None
        assert row["proposed"]["memory"] is not None
        assert row["reduction_eligible"] == {"cpu": False, "memory": True}
        assert any("duration" in reason for reason in row["reduction_reasons"]["cpu"])


def test_saved_exports_keep_independent_evidence_and_missing_replica_label(settings):
    from openpyxl import load_workbook

    collector = CountingCollector(settings)
    app = create_app(settings, collector)
    with TestClient(app) as client:
        pool = initialized(client)["pools"][0]
        snapshot = app.state.store.snapshot(pool_id=pool["id"])
        cutoff = snapshot["metrics"]["cutoff"]
        continuous = list(range(cutoff - 86400, cutoff + 1, 300))
        history(snapshot, continuous, continuous)
        first = snapshot["context"]["pods"][0]
        snapshot["metrics"]["samples"] = [
            p for p in snapshot["metrics"]["samples"] if p["replica"] != first["uid"] or p["time"] == cutoff
        ]
        sid = app.state.store.publish_snapshot(pool["id"], snapshot)
        query = dict(pool_id=pool["id"], snapshot_id=sid, days=1)
        saved = client.get("/api/snapshot", params=query).json()
        metric = saved["usage"]["workloads"][first["workload"]]
        assert metric["cpu_p99"] == 0.05 and metric["cpu_evidence"]["partial"]
        before = collector.calls
        response = client.get("/api/export/workloads", params=query)
        rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
        assert rows[0]["CPU valid samples"] == "289"
        assert rows[0]["CPU represented seconds"] == "86400"
        assert rows[0]["CPU evidence partial"] == "True"
        assert rows[0]["CPU reduction eligible"] == "False"
        xlsx = client.get("/api/export/pods", params={**query, "format": "xlsx"})
        table = list(load_workbook(io.BytesIO(xlsx.content), read_only=True).active.values)
        assert "Memory selected-window coverage" in table[0]
        assert collector.calls == before


def test_young_pods_distinguish_lifetime_from_selected_window_and_cpu_warmup(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        pool = initialized(client)["pools"][0]
        snapshot = app.state.store.snapshot(pool_id=pool["id"])
        cutoff = snapshot["metrics"]["cutoff"]
        history(
            snapshot,
            list(range(cutoff - 7200, cutoff + 1, 300)),
            list(range(cutoff - 7200, cutoff + 1, 300)),
            created=cutoff - 7200,
        )
        sid = app.state.store.publish_snapshot(pool["id"], snapshot)
        saved = client.get("/api/snapshot", params=dict(pool_id=pool["id"], snapshot_id=sid, days=10)).json()
        metric = saved["usage"]["pods"][saved["pods"][0]["uid"]]
        assert metric["cpu_samples"] == 24 and metric["memory_samples"] == 25
        assert metric["cpu_evidence"]["expected_samples"] == 24
        assert metric["cpu_evidence"]["lifetime_coverage"] == 1
        assert metric["cpu_evidence"]["represented_seconds"] == 6900
        assert metric["memory_evidence"]["represented_seconds"] == 7200
        assert metric["memory_evidence"]["selected_window_coverage"] < 0.01
        assert not metric["memory_evidence"]["eligible"]


def test_historical_replica_evidence_uses_saved_membership_end_not_current_cutoff(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        pool = initialized(client)["pools"][0]
        snapshot = app.state.store.snapshot(pool_id=pool["id"])
        cutoff = snapshot["metrics"]["cutoff"]
        first = deepcopy(snapshot["context"]["pods"][0])
        first["uid"] = "deleted-replica"
        first["created"] = cutoff - 2 * 86400
        beginning, end = cutoff - 86400, cutoff - 72000
        first["memberships"] = [
            dict(
                pool_id=pool["id"],
                node=first["node"],
                start=beginning,
                end=end,
                provenance="explicit synthetic placement history",
            )
        ]
        snapshot["metrics"].update(
            cadence_seconds=300, cpu_rate_window_seconds=300, replica_evidence={first["uid"]: first}
        )
        snapshot["metrics"]["samples"] = [
            dict(time=t, workload=first["workload"], replica=first["uid"], attributed=True, memory=100, cpu=1)
            for t in range(beginning, end + 1, 300)
        ]
        sid = app.state.store.publish_snapshot(pool["id"], snapshot)
        saved = client.get("/api/snapshot", params=dict(pool_id=pool["id"], snapshot_id=sid, days=10)).json()
        evidence = saved["usage"]["pods"][first["uid"]]["memory_evidence"]
        assert evidence["expected_samples"] == 49
        assert evidence["represented_seconds"] == 14400
        assert evidence["lifetime_coverage"] == 1
        assert evidence["selected_window_coverage"] < 0.02


def test_configurable_policy_boundaries_and_unknown_legacy_evidence(settings):
    settings.min_reduction_observation_seconds = 43200
    settings.min_reduction_coverage = 0.5
    app = create_app(settings)
    with TestClient(app) as client:
        pool = initialized(client)["pools"][0]
        snapshot = app.state.store.snapshot(pool_id=pool["id"])
        cutoff = snapshot["metrics"]["cutoff"]
        times = list(range(cutoff - 43200 + 300, cutoff + 1, 300))
        history(snapshot, times, times)
        sid = app.state.store.publish_snapshot(pool["id"], snapshot)
        query = dict(pool_id=pool["id"], snapshot_id=sid, days=1)
        row = client.get("/api/recommendations", params=query).json()["rows"][0]
        assert row["reduction_eligible"] == {"cpu": True, "memory": True}
        assert row["cpu_evidence"]["represented_seconds"] == 43200
        assert row["cpu_evidence"]["selected_window_coverage"] == 0.5
        snapshot["metrics"].pop("cadence_seconds")
        sid = app.state.store.publish_snapshot(pool["id"], snapshot)
        query["snapshot_id"] = sid
        row = client.get("/api/recommendations", params=query).json()["rows"][0]
        assert row["cpu_p99"] == 0.05
        assert row["cpu_evidence"]["expected_samples"] is None
        assert row["cpu_evidence"]["represented_seconds"] is None
        assert row["proposed"] == {"cpu": None, "memory": None}


def test_combined_pool_api_and_exports_preserve_winner_and_each_pool_evidence(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        pool = initialized(client)["pools"][0]
        query = {k: pool[k] for k in ["project", "location", "cluster"]}
        saved = client.get("/api/cluster-snapshot", params={**query, "days": 3}).json()
        workload = saved["workloads"][0]
        assert workload["cpu_evidence"]["replica"] == workload["cpu_replica"]
        assert workload["cpu_evidence"]["pool_name"] == workload["cpu_pool"]
        assert all(p["cpu_evidence"]["source"] for p in workload["pools"])
        body = {**query, "days": 3, "snapshots": {s["pool_id"]: s["snapshot_id"] for s in saved["sources"]}}
        response = client.post("/api/export-cluster/workloads", json=body)
        row = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))[0]
        assert row["CPU valid samples"]
        assert all(s["snapshot_id"] in row["Evidence per pool"] for s in saved["sources"])


def test_sparse_nonwinning_replica_cannot_make_workload_reduction_eligible(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        pool = initialized(client)["pools"][0]
        snapshot = app.state.store.snapshot(pool_id=pool["id"])
        cutoff = snapshot["metrics"]["cutoff"]
        continuous = list(range(cutoff - 86400, cutoff + 1, 300))
        history(snapshot, continuous, continuous)
        weak = snapshot["context"]["pods"][0]
        for sample in snapshot["metrics"]["samples"]:
            if sample["replica"] == weak["uid"]:
                sample["cpu"] = 0.01
        snapshot["metrics"]["samples"] = [
            s
            for s in snapshot["metrics"]["samples"]
            if s["replica"] != weak["uid"] or s["time"] >= cutoff - 7200
        ]
        sid = app.state.store.publish_snapshot(pool["id"], snapshot)
        query = dict(pool_id=pool["id"], snapshot_id=sid, days=1)
        row = client.get("/api/recommendations", params=query).json()["rows"][0]
        assert row["cpu_evidence"]["replica"] != weak["uid"]
        assert row["cpu_evidence"]["represented_seconds"] == 86400
        assert row["proposed"]["cpu"] is None
        assert any(
            weak["uid"] in reason and "duration" in reason for reason in row["reduction_reasons"]["cpu"]
        )
