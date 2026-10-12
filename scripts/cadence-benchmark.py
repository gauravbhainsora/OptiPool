"""Synthetic GMP cadence comparison. No credentials, network, or existing database.

Run: PYTHONPATH=backend .venv/bin/python scripts/cadence-benchmark.py
"""

import json
import math
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from optipool.collector import CloudCollector
from optipool.config import Settings
from optipool.demo import DemoCollector
from optipool.store import Store
from optipool.views import SavedViews


def measure(cadence, directory):
    settings = Settings(metric_cadence_seconds=cadence)
    demo = DemoCollector(settings)
    pool = demo.discover()[0][0]
    snapshot = demo.collect(pool)
    clock = int(time.time())
    collector = object.__new__(CloudCollector)
    collector.settings = settings
    volume = {"requests": 0, "response_bytes": 0, "resource_points": 0}

    def gmp(url, params):
        volume["requests"] += 1
        memory = "working_set" in params["query"]
        series = []
        for i, pod in enumerate(snapshot["context"]["pods"]):
            points = []
            for t in range(params["start"], params["end"] + 1, params["step"]):
                wave = (math.sin(t / 9000 + i) + 1) / 2
                value = (0.25 + wave / 2) * (1024**3 if memory else 1)
                points.append([t, str(round(value, 6))])
            volume["resource_points"] += len(points)
            series.append({"metric": {"namespace": pod["namespace"], "pod": pod["name"]}, "values": points})
        response = {"status": "success", "data": {"resultType": "matrix", "result": series}}
        volume["response_bytes"] += len(json.dumps(response, separators=(",", ":")).encode())
        return response

    collector.get = gmp
    db = directory / f"cadence-{cadence}.db"
    store = Store(str(db))
    try:
        store.publish_inventory([pool], [pool["project"]], [])
        started = time.perf_counter()
        with patch("optipool.collector.time.time", return_value=clock):
            snapshot["metrics"] = collector.metrics(pool, snapshot)
        sid = store.publish_snapshot(pool["id"], snapshot)
        refresh_seconds = time.perf_counter() - started
        before_views = volume["requests"]
        views = SavedViews(store)
        cold = []
        for days in [1, 5, 10]:
            started = time.perf_counter()
            content = views.get(pool["id"], days, sid)
            cold.append(time.perf_counter() - started)
            view = json.loads(content)
            expected_samples = (days * 86400 // cadence + 1) * len(snapshot["context"]["pods"])
            assert sum(m["memory_samples"] for m in view["usage"]["pods"].values()) == expected_samples
            assert all(
                m["memory_p99"] > 0 and m["memory_peak"] >= m["memory_p99"]
                for m in view["usage"]["workloads"].values()
            )
        warm = []
        for _ in range(100):
            started = time.perf_counter()
            views.get(pool["id"], 10, sid)
            warm.append(time.perf_counter() - started)
        backup = directory / f"backup-{cadence}.db"
        store.backup(str(backup))
        result = {
            "cadence_seconds": cadence,
            "pods": len(snapshot["context"]["pods"]),
            "days": 10,
            **volume,
            "saved_samples": len(snapshot["metrics"]["samples"]),
            "refresh_seconds": round(refresh_seconds, 4),
            "sqlite_backup_bytes_one_snapshot": backup.stat().st_size,
            "cold_saved_view_seconds_1_5_10_days": [round(v, 4) for v in cold],
            "warm_saved_view_p95_ms": round(sorted(warm)[94] * 1000, 4),
            "ten_day_view_bytes": len(content),
        }
        # Public persistence/retention boundary: old snapshots prune, latest survives.
        with patch("optipool.store.time.time", return_value=clock + 31 * 86400):
            latest = store.publish_snapshot(pool["id"], snapshot)
            store.prune()
        result["retention_old_pruned_latest_kept"] = (
            store.snapshot(snapshot_id=sid) is None and store.snapshot(snapshot_id=latest) is not None
        )
        result["cloud_requests_for_saved_views"] = volume["requests"] - before_views
        return result
    finally:
        store.close()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="optipool-cadence-") as folder:
        print(json.dumps([measure(c, Path(folder)) for c in [300, 60]], indent=2))
