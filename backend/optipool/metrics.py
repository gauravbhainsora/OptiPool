import math
from collections import defaultdict


def percentile(values, p=0.99):
    values = sorted(v for v in values if math.isfinite(v))
    if not values:
        return None
    index = (len(values) - 1) * p
    low, high = math.floor(index), math.ceil(index)
    return values[low] + (values[high] - values[low]) * (index - low)


def summarize(snapshot, days, minimum=20):
    cutoff = snapshot["metrics"]["cutoff"]
    start = cutoff - days * 86400
    cadence = snapshot["metrics"].get("cadence_seconds")
    selected_nodes = {n["name"] for n in snapshot.get("nodes", [])}
    observed = {
        p["uid"]: p for p in snapshot.get("context", {}).get("pods", []) if p.get("node") in selected_nodes
    }
    history = snapshot["metrics"].get("replica_evidence", {})
    replicas = defaultdict(dict)
    for sample in snapshot["metrics"].get("samples", []):
        if start <= sample["time"] <= cutoff and sample.get("attributed"):
            point = replicas[(sample["workload"], sample["replica"])].setdefault(sample["time"], {})
            for resource in ["cpu", "memory"]:
                value = sample.get(resource)
                if value is not None and math.isfinite(value) and value >= 0:
                    point[resource] = value
    workloads, pod_metrics = {}, {}
    timeline = defaultdict(lambda: {"cpu": None, "memory": None})
    for (workload, replica), points in replicas.items():
        target = workloads.setdefault(
            workload,
            {
                "cpu_p99": None,
                "memory_p99": None,
                "cpu_replica": None,
                "memory_replica": None,
                "replicas_observed": 0,
                "historical_replicas_observed": 0,
                "historical_replica_uids": [],
                "samples": 0,
            },
        )
        target["replicas_observed"] += 1
        historical = replica not in observed
        if historical:
            target["historical_replicas_observed"] += 1
            target["historical_replica_uids"].append(replica)
        target["samples"] += len(points)
        created = observed.get(replica, history.get(replica, {})).get("created") or start
        expected = max(1, int((cutoff - max(start, created)) / cadence) + 1) if cadence else None
        metric = {
            "workload": workload,
            "historical": historical,
            "identity": history.get(replica),
            "samples": len(points),
            "last_sample_at": max(points),
            "expected_samples": expected,
        }
        for resource in ["cpu", "memory"]:
            values = [p[resource] for p in points.values() if resource in p]
            metric[resource + "_samples"] = len(values)
            metric[resource + "_coverage"] = min(1, len(values) / expected) if expected else None
            metric[resource + "_p99"] = percentile(values) if len(values) >= minimum else None
            metric[resource + "_peak"] = max(values) if values else None
            latest = max((t for t, p in points.items() if resource in p), default=None)
            metric[resource + "_latest"] = points[latest][resource] if latest is not None else None
            metric[resource + "_sample_at"] = latest
            p99 = metric[resource + "_p99"]
            if p99 is not None and (target[resource + "_p99"] is None or p99 > target[resource + "_p99"]):
                target[resource + "_p99"], target[resource + "_replica"] = p99, replica
            for t, point in points.items():
                if resource in point:
                    timeline[t][resource] = (timeline[t][resource] or 0) + point[resource]
        pod_metrics[replica] = metric
    return {
        "days": days,
        "start": start,
        "cutoff": cutoff,
        "workloads": workloads,
        "pods": pod_metrics,
        "timeline": [{"time": t, **v} for t, v in sorted(timeline.items())],
        "source": snapshot["metrics"].get("source", "Unavailable"),
        "memory_definition": snapshot["metrics"].get("memory_definition", "Unavailable"),
        "coverage": snapshot["metrics"].get("coverage", "unavailable"),
        "cadence_seconds": cadence,
        "minimum_samples": minimum,
        "warnings": snapshot["metrics"].get("warnings", []),
        "attribution_gaps": snapshot["metrics"].get("attribution_gaps", []),
        "historical_replicas": [{"uid": uid, **m} for uid, m in pod_metrics.items() if m["historical"]],
    }
