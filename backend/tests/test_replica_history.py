import json
from copy import deepcopy

from optipool.exports import workload_rows
from optipool.store import Store
from optipool.views import SavedViews


def evidenced(snapshot):
    snapshot = deepcopy(snapshot)
    cutoff = snapshot["metrics"]["cutoff"]
    snapshot["metrics"]["replica_evidence"] = {
        p["uid"]: {
            "uid": p["uid"],
            "name": p["name"],
            "namespace": p["namespace"],
            "workload": p["workload"],
            "controller_uid": "controller-" + p["workload"],
            "created": p["created"],
            "observed_at": cutoff,
            "memberships": [
                {
                    "pool_id": snapshot["pool"]["id"],
                    "node": p["node"],
                    "start": p["created"],
                    "end": cutoff,
                    "provenance": "synthetic history",
                }
            ],
        }
        for p in snapshot["context"]["pods"]
    }
    for w in snapshot["workloads"]:
        w["controller_uid"] = "controller-" + w["id"]
    return snapshot


def test_deleted_replica_remains_independent_winner_in_saved_views_and_exports(settings, saved):
    first = evidenced(saved)
    deleted = first["context"]["pods"][0]
    memory_winner = first["context"]["pods"][1]
    for point in first["metrics"]["samples"]:
        if point["replica"] == deleted["uid"]:
            point["cpu"] = 9
        if point["replica"] == memory_winner["uid"]:
            point["memory"] = 99 * 1024**3
    store = Store(settings.database)
    old_id = store.publish_snapshot(first["pool"]["id"], first)
    old_view = SavedViews(store).get(first["pool"]["id"], 3, old_id)
    second = evidenced(saved)
    second["context"]["pods"] = [p for p in second["context"]["pods"] if p["uid"] != deleted["uid"]]
    second["metrics"]["samples"] = [p for p in second["metrics"]["samples"] if p["replica"] != deleted["uid"]]
    second["metrics"]["replica_evidence"].pop(deleted["uid"])
    for point in second["metrics"]["samples"]:
        if point["replica"] == memory_winner["uid"]:
            point["memory"] = 99 * 1024**3
    new_id = store.publish_snapshot(second["pool"]["id"], second)
    view = json.loads(SavedViews(store).get(second["pool"]["id"], 3, new_id))
    metric = view["usage"]["workloads"][deleted["workload"]]
    assert metric["cpu_p99"] == 9
    assert metric["cpu_replica"] == deleted["uid"]
    assert metric["memory_replica"] == memory_winner["uid"]
    assert metric["historical_replicas_observed"] == 1
    assert deleted["uid"] not in {p["uid"] for p in view["pods"]}
    row = workload_rows(view, view["usage"])[0]
    assert row["Historical replicas observed"] == 1
    assert row["Historical replica UIDs"] == deleted["uid"]
    assert SavedViews(store).get(first["pool"]["id"], 3, old_id) == old_view
    store.close()


def test_unknown_membership_and_changed_controller_are_excluded_without_rewriting_legacy(settings, saved):
    store = Store(settings.database)
    first = evidenced(saved)
    uid = first["context"]["pods"][0]["uid"]
    for point in first["metrics"]["samples"]:
        if point["replica"] == uid:
            point["cpu"] = 9
    old = store.publish_snapshot(first["pool"]["id"], first)
    second = evidenced(saved)
    second["workloads"][0]["controller_uid"] = "replacement-controller"
    for p in second["context"]["pods"]:
        if p["workload"] == second["workloads"][0]["id"]:
            record = second["metrics"]["replica_evidence"][p["uid"]]
            record["controller_uid"] = "replacement-controller"
            record["memberships"][0]["start"] = second["metrics"]["cutoff"]
    new = store.publish_snapshot(first["pool"]["id"], second)
    view = json.loads(SavedViews(store).get(first["pool"]["id"], 3, new))
    metric = view["usage"]["workloads"][first["workloads"][0]["id"]]
    assert metric["cpu_p99"] is None and metric["memory_p99"] is None
    assert "Changed or uncertain controller identity" in view["usage"]["attribution_gaps"]
    assert "Unknown pool membership or lifetime interval" in view["usage"]["attribution_gaps"]
    assert (
        json.loads(SavedViews(store).get(first["pool"]["id"], 3, old))["usage"]["workloads"][
            first["workloads"][0]["id"]
        ]["cpu_p99"]
        == 9
    )
    store.close()


def test_duplicate_values_keep_latest_value_and_origins_after_retention_and_restore(
    settings, saved, tmp_path, monkeypatch
):
    first = evidenced(saved)
    uid = first["context"]["pods"][0]["uid"]
    first["metrics"]["samples"] = [p for p in first["metrics"]["samples"] if p["replica"] == uid]
    for point in first["metrics"]["samples"]:
        point["cpu"] = 9
    store = Store(settings.database)
    old = store.publish_snapshot(first["pool"]["id"], first)
    second = deepcopy(first)
    for point in second["metrics"]["samples"]:
        point["cpu"] = 2
    new = store.publish_snapshot(first["pool"]["id"], second)
    merged = store.snapshot(snapshot_id=new)
    assert len(merged["metrics"]["samples"]) == len(first["metrics"]["samples"])
    assert {p["cpu"] for p in merged["metrics"]["samples"]} == {2}
    origins = merged["metrics"]["samples"][0]["provenance"]["cpu"]
    assert {o["value"] for o in origins} == {9, 2}
    assert {o["snapshot_id"] for o in origins} == {old, new}
    view = SavedViews(store).get(first["pool"]["id"], 3, new)
    import time

    with monkeypatch.context() as clock:
        future = time.time() + 31 * 86400
        clock.setattr(time, "time", lambda: future)
        store.prune()
    assert store.snapshot(snapshot_id=old) is None
    store.backup(str(tmp_path / "backup.db"))
    store.close()
    restored = Store(str(tmp_path / "backup.db"))
    assert SavedViews(restored).get(first["pool"]["id"], 3, new) == view
    restored.close()


def test_authenticated_rollout_saved_window_export_and_restart(settings, monkeypatch):
    import csv
    import io
    import time

    import jwt
    from cryptography.hazmat.primitives.asymmetric import ec
    from fastapi.testclient import TestClient
    from google.oauth2 import id_token
    from optipool.app import create_app
    from p99_history_fixture import RolloutCollector
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
    collector = RolloutCollector(settings)
    with TestClient(create_app(settings, collector), headers={"x-goog-iap-jwt-assertion": signed}) as client:
        pool = initialized(client)["pools"][0]["id"]
        original = client.get("/api/snapshot", params={"pool_id": pool, "days": 10}).json()
        job = client.post("/api/refresh/pool", params={"pool_id": pool}, json={}).json()
        assert wait_job(client, job["id"])["state"] == "succeeded"
        view = client.get("/api/snapshot", params={"pool_id": pool, "days": 10}).json()
        workload = view["workloads"][0]
        metric = view["usage"]["workloads"][workload["id"]]
        assert workload["pool_replicas"] == 2 and workload["running"] == 2
        assert metric["cpu_p99"] == 9 and metric["historical_replicas_observed"] == 1
        csv_result = client.get(
            "/api/export/workloads", params={"pool_id": pool, "days": 10, "snapshot_id": view["id"]}
        )
        rows = list(csv.DictReader(io.StringIO(csv_result.content.decode("utf-8-sig"))))
        assert rows[0]["Historical replicas observed"] == "1"
        assert rows[0]["Historical replica UIDs"] == "checkout-api-7cf88-1"
        cluster_query = {k: view["pool"][k] for k in ["project", "location", "cluster"]}
        cluster = client.get("/api/cluster-snapshot", params=cluster_query).json()
        assert cluster["workloads"][0]["historical_replicas_observed"] == 1
        body = {**cluster_query, "days": 10, "snapshots": {pool: view["id"]}}
        exported = client.post("/api/export-cluster/workloads", json=body)
        cluster_rows = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
        assert cluster_rows[0]["Historical replicas observed across pool observations"] == "1"
        pinned = client.get(
            "/api/snapshot", params={"pool_id": pool, "days": 10, "snapshot_id": original["id"]}
        ).json()
        assert pinned == original
        assert collector.calls == 2
    with TestClient(create_app(settings, collector), headers={"x-goog-iap-jwt-assertion": signed}) as client:
        assert client.get("/api/snapshot", params={"pool_id": pool, "days": 10}).json() == view
        assert collector.calls == 2


def test_reused_pod_name_keeps_distinct_uids_and_excludes_foreign_pool_and_lifetime_samples(settings, saved):
    first = evidenced(saved)
    old_uid = first["context"]["pods"][0]["uid"]
    for sample in first["metrics"]["samples"]:
        if sample["replica"] == old_uid:
            sample["cpu"] = 9
    store = Store(settings.database)
    store.publish_snapshot(first["pool"]["id"], first)
    second = evidenced(saved)
    new_uid = "replacement-pod-uid"
    pod = second["context"]["pods"][0]
    pod["uid"] = new_uid
    record = second["metrics"]["replica_evidence"].pop(old_uid)
    record["uid"] = new_uid
    record["created"] = second["metrics"]["cutoff"] - 86400
    record["memberships"][0]["start"] = record["created"]
    second["metrics"]["replica_evidence"][new_uid] = record
    for sample in second["metrics"]["samples"]:
        if sample["replica"] == old_uid:
            sample["replica"] = new_uid
            sample["cpu"] = 2
    second["metrics"]["samples"].extend(
        [
            {
                "replica": new_uid,
                "workload": record["workload"],
                "time": record["created"] - 1,
                "cpu": 100,
                "memory": 100 * 1024**3,
                "attributed": True,
            },
            {
                "replica": new_uid,
                "workload": record["workload"],
                "time": record["created"] + 60,
                "cpu": 100,
                "attributed": True,
            },
        ]
    )
    foreign = second["context"]["pods"][3]
    second["metrics"]["replica_evidence"][foreign["uid"]]["memberships"][0]["pool_id"] = "another-pool"
    sid = store.publish_snapshot(first["pool"]["id"], second)
    view = json.loads(SavedViews(store).get(first["pool"]["id"], 3, sid))
    metric = view["usage"]["workloads"][record["workload"]]
    assert metric["cpu_p99"] == 9 and metric["cpu_replica"] == old_uid
    assert metric["replicas_observed"] == 4 and metric["historical_replicas_observed"] == 1
    assert view["usage"]["pods"][new_uid]["cpu_peak"] == 2
    assert view["usage"]["pods"][new_uid]["memory_peak"] < 1024**3
    assert foreign["uid"] not in {
        p["replica"]
        for p in store.snapshot(snapshot_id=sid)["metrics"]["samples"]
        if p["time"] == second["metrics"]["cutoff"]
        and p.get("provenance", {}).get("cpu", [{}])[-1].get("snapshot_id") == sid
    }
    store.close()


def test_unknown_cpu_rate_window_does_not_infer_lifetime_attribution(settings, saved):
    snapshot = evidenced(saved)
    snapshot["metrics"]["cpu_rate_window_seconds"] = None
    store = Store(settings.database)
    sid = store.publish_snapshot(snapshot["pool"]["id"], snapshot)
    view = json.loads(SavedViews(store).get(snapshot["pool"]["id"], 3, sid))
    metric = view["usage"]["workloads"][snapshot["workloads"][0]["id"]]
    assert metric["cpu_p99"] is None and metric["memory_p99"] is not None
    assert "Unknown CPU rate window" in view["usage"]["attribution_gaps"]
    assert metric["memory_evidence"]["eligible"] and not metric["memory_evidence"]["partial"]
    details = view["usage"]["attribution_gap_details"]
    assert details and all(d["resource"] == "cpu" and d["replica"] and d["workload"] for d in details)
    store.close()


def test_unavailable_refresh_uses_one_compatible_retained_source(settings, saved):
    first = evidenced(saved)
    first["metrics"].update(
        source="GMP cAdvisor",
        memory_definition="Working set",
        query_definition={
            "cpu_metric": "container_cpu_usage_seconds_total",
            "cpu_aggregation": "sum of rate[5m]",
        },
        units={"cpu": "cores", "memory": "bytes"},
        cpu_alignment_window_seconds=None,
    )
    for point in first["metrics"]["samples"]:
        point.pop("memory")
    store = Store(settings.database)
    store.publish_snapshot(first["pool"]["id"], first)
    second = evidenced(saved)
    second["metrics"].update(source="Cloud Monitoring", memory_definition="Non-evictable")
    for point in second["metrics"]["samples"]:
        point.pop("cpu")
    store.publish_snapshot(second["pool"]["id"], second)
    unavailable = evidenced(saved)
    unavailable["metrics"].update(
        source="Unavailable",
        memory_definition="Unavailable",
        samples=[],
        query_definition=None,
        units=None,
        cpu_rate_window_seconds=None,
        cadence_seconds=None,
        resource_status={"cpu": "unavailable", "memory": "unavailable"},
        fallback_reason="Fresh monitoring reads failed",
    )
    unavailable["metrics"]["warnings"].append("Fresh monitoring reads failed")
    sid = store.publish_snapshot(unavailable["pool"]["id"], unavailable)
    view = json.loads(SavedViews(store).get(unavailable["pool"]["id"], 3, sid))
    assert view["usage"]["source"] == "GMP cAdvisor"
    assert view["usage"]["memory_definition"] == "Working set"
    assert view["usage"]["query_definition"] == first["metrics"]["query_definition"]
    assert view["usage"]["units"] == {"cpu": "cores", "memory": "bytes"}
    assert view["usage"]["cpu_rate_window_seconds"] == 300
    assert view["usage"]["cadence_seconds"] == 1800
    assert view["usage"]["resource_status"] == {"cpu": "available", "memory": "unavailable"}
    assert "Fresh monitoring reads failed" in view["usage"]["fallback_reason"]
    assert "Fresh monitoring reads failed" in view["usage"]["warnings"]
    assert all(
        m["cpu_p99"] is not None and m["memory_p99"] is None for m in view["usage"]["workloads"].values()
    )
    assert "Incompatible retained metric definition" in view["usage"]["attribution_gaps"]
    store.close()


def test_samples_with_conflicting_source_or_memory_definition_are_not_relabelled(settings, saved):
    snapshot = evidenced(saved)
    uid = snapshot["context"]["pods"][0]["uid"]
    for point in snapshot["metrics"]["samples"]:
        if point["replica"] == uid:
            point["memory"] = 100 * 1024**3
            point["memory_definition"] = "Different memory metric"
    store = Store(settings.database)
    sid = store.publish_snapshot(snapshot["pool"]["id"], snapshot)
    view = json.loads(SavedViews(store).get(snapshot["pool"]["id"], 3, sid))
    metric = view["usage"]["pods"][uid]
    assert metric["cpu_p99"] is not None and metric["memory_p99"] is None
    assert "Incompatible sample source or definition" in view["usage"]["attribution_gaps"]
    store.close()


def test_retained_samples_with_changed_units_are_excluded_visibly(settings, saved):
    first = evidenced(saved)
    deleted = first["context"]["pods"][0]["uid"]
    first["metrics"]["units"] = {"cpu": "millicores", "memory": "bytes"}
    for sample in first["metrics"]["samples"]:
        sample["cpu"] = 10000 if sample["replica"] == deleted else 2
    store = Store(settings.database)
    store.publish_snapshot(first["pool"]["id"], first)
    second = evidenced(saved)
    second["metrics"]["units"] = {"cpu": "cores", "memory": "bytes"}
    second["context"]["pods"] = [p for p in second["context"]["pods"] if p["uid"] != deleted]
    second["metrics"]["samples"] = [p for p in second["metrics"]["samples"] if p["replica"] != deleted]
    second["metrics"]["replica_evidence"].pop(deleted)
    for sample in second["metrics"]["samples"]:
        sample["cpu"] = 2
    sid = store.publish_snapshot(second["pool"]["id"], second)
    view = json.loads(SavedViews(store).get(second["pool"]["id"], 3, sid))
    metric = view["usage"]["workloads"][second["workloads"][0]["id"]]
    assert metric["cpu_p99"] == 2
    assert "Incompatible retained metric definition" in view["usage"]["attribution_gaps"]
    store.close()


def test_staging_history_keeps_saved_reads_and_other_pool_writes_available_and_serializes_same_pool(
    settings, saved, monkeypatch
):
    import threading
    import zlib
    from concurrent.futures import ThreadPoolExecutor

    store = Store(settings.database)
    first = evidenced(saved)
    pool = first["pool"]["id"]
    old = store.publish_snapshot(pool, first)
    store.publish_inventory([first["pool"]], [first["pool"]["project"]], [])
    uid = first["context"]["pods"][0]["uid"]
    second = deepcopy(first)
    second["metrics"]["samples"] = [p for p in second["metrics"]["samples"] if p["replica"] == uid]
    for sample in second["metrics"]["samples"]:
        sample["cpu"] = 9
    third = deepcopy(first)
    third["context"]["pods"] = [p for p in third["context"]["pods"] if p["uid"] != uid]
    third["metrics"]["replica_evidence"].pop(uid)
    third["metrics"]["samples"] = [p for p in third["metrics"]["samples"] if p["replica"] != uid]
    other = deepcopy(first)
    other["pool"]["id"] = "another-pool"
    staging, resume = threading.Event(), threading.Event()
    compress = zlib.compress

    def slow_compression(data, *args, **kwargs):
        if threading.current_thread().name == "staged-publication":
            staging.set()
            assert resume.wait(5), "test did not release staged publication"
        return compress(data, *args, **kwargs)

    monkeypatch.setattr(zlib, "compress", slow_compression)
    results = []
    publisher = threading.Thread(
        name="staged-publication", target=lambda: results.append(store.publish_snapshot(pool, second))
    )
    publisher.start()
    assert staging.wait(5)
    try:
        with ThreadPoolExecutor(max_workers=3) as workers:
            same_pool = workers.submit(store.publish_snapshot, pool, third)
            read = workers.submit(store.snapshot, snapshot_id=old)
            other_pool = workers.submit(store.publish_snapshot, other["pool"]["id"], other)
            try:
                assert read.result(timeout=1)["id"] == old
                assert other_pool.result(timeout=1)
                assert store.inventory()[0]["snapshot_id"] == old
                assert not same_pool.done()
            finally:
                resume.set()
            newest = same_pool.result(timeout=5)
        publisher.join(timeout=5)
        assert not publisher.is_alive()
        assert store.snapshot(pool_id=pool)["id"] == newest
        view = json.loads(SavedViews(store).get(pool, 3, newest))
        assert view["usage"]["workloads"][first["context"]["pods"][0]["workload"]]["cpu_p99"] == 9
        assert store.snapshot(snapshot_id=old)["metrics"]["samples"][0]["cpu"] != 9
    finally:
        resume.set()
        publisher.join(timeout=5)
        store.close()
