"""Synthetic 20-user smoke benchmark; never substitutes for actual-inventory acceptance."""

import json
import platform
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from optipool.app import create_app
from optipool.config import Settings
from optipool.demo import DemoCollector
from optipool.metrics import percentile


class DoubleDemo(DemoCollector):
    def __init__(self, settings):
        super().__init__(settings)
        self.calls = 0

    def discover(self):
        original, _, errors = super().discover()
        extra = deepcopy(original)
        for p in extra:
            p["project"] += "-scale"
            p["id"] = f"{p['project']}/{p['location']}/{p['cluster']}/{p['name']}"
        pools = original + extra
        return pools, sorted({p["project"] for p in pools}), errors

    def collect(self, pool):
        self.calls += 1
        return super().collect(pool)


def main():
    with tempfile.TemporaryDirectory(prefix="optipool-benchmark-") as directory:
        settings = Settings(database=str(Path(directory) / "benchmark.db"))
        source = DoubleDemo(settings)
        with TestClient(create_app(settings, source)) as client:
            for _ in range(300):
                inventory = client.get("/api/inventory").json()
                if inventory["initialized"]:
                    break
                time.sleep(0.01)
            assert inventory["initialized"] and source.calls == 16
            pools = inventory["pools"]
            pool_id = pools[0]["id"]

            def cached(i):
                started = time.perf_counter()
                if i % 2:
                    response = client.get(
                        "/api/snapshot", params={"pool_id": pools[i % 16]["id"], "days": 10}
                    )
                else:
                    response = client.get("/api/inventory")
                assert response.status_code == 200
                return time.perf_counter() - started

            def cluster_read(i):
                started = time.perf_counter()
                pool = pools[i % len(pools)]
                response = client.get(
                    "/api/cluster-snapshot",
                    params={**{k: pool[k] for k in ["project", "location", "cluster"]}, "days": 10},
                )
                assert response.status_code == 200 and len(response.json()["sources"]) == 2
                return time.perf_counter() - started

            def scenario(i):
                started = time.perf_counter()
                response = client.post(
                    "/api/estimate",
                    params={"pool_id": pool_id},
                    json={"name": f"bench-{i}", "cpu": "500m", "memory": "1Gi", "replicas": 6},
                )
                assert response.status_code == 200
                return time.perf_counter() - started

            with ThreadPoolExecutor(max_workers=20) as workers:
                reads = list(workers.map(cached, range(100)))
                cluster_reads = list(workers.map(cluster_read, range(100)))
                estimates = list(workers.map(scenario, range(40)))
            assert source.calls == 16
            report = {
                "recorded_at": datetime.now(UTC).isoformat(),
                "scope": "2x synthetic demo only",
                "concurrent_users": 20,
                "pools": 16,
                "nodes": sum(s["node_count"] for s in inventory["summaries"].values()),
                "pods": 160,
                "replicas_per_estimate": 6,
                "cached_requests": len(reads),
                "cluster_requests": len(cluster_reads),
                "pools_per_cluster": 2,
                "cluster_p95_seconds": percentile(cluster_reads, 0.95),
                "estimate_requests": len(estimates),
                "cached_p95_seconds": percentile(reads, 0.95),
                "estimate_p95_seconds": percentile(estimates, 0.95),
                "cloud_calls_during_benchmark": 0,
                "runtime": f"Python {platform.python_version()} / {platform.system()} {platform.machine()}",
                "limitation": "In-process API benchmark with synthetic inventory; excludes network/IAP/browser and actual GCP scale",
            }
            Path("docs/benchmark-synthetic.json").write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps(report, indent=2))
            assert (
                report["cached_p95_seconds"] < 2
                and report["cluster_p95_seconds"] < 2
                and report["estimate_p95_seconds"] < 10
            )


if __name__ == "__main__":
    main()
