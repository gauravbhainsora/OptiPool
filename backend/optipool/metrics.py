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
    observed = {p["uid"]: p for p in snapshot.get("context", {}).get("pods", [])}
    replicas = defaultdict(dict)
    warnings = list(snapshot["metrics"].get("warnings", []))
    memory_definition = snapshot["metrics"].get("memory_definition", "Unknown")
    for sample in snapshot["metrics"].get("samples", []):
        if start <= sample["time"] <= cutoff and sample.get("attributed"):
            for resource in ["cpu", "memory"]:
                if (
                    resource == "memory"
                    and sample.get("memory_definition", memory_definition) != memory_definition
                ):
                    warning = "Excluded samples with incompatible memory definition from saved window"
                    if warning not in warnings:
                        warnings.append(warning)
                    continue
                value = sample.get(resource)
                if value is not None and math.isfinite(value) and value >= 0:
                    point = replicas[(sample["workload"], sample["replica"])].setdefault(sample["time"], {})
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
                "memory_peak": None,
                "memory_peak_replica": None,
                "replicas_observed": 0,
                "samples": 0,
            },
        )
        target["replicas_observed"] += 1
        target["samples"] += len(points)
        created = observed.get(replica, {}).get("created") or start
        expected = max(1, int((cutoff - max(start, created)) / cadence) + 1) if cadence else None
        metric = {
            "workload": workload,
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
            if (
                resource == "memory"
                and metric["memory_peak"] is not None
                and (target["memory_peak"] is None or metric["memory_peak"] > target["memory_peak"])
            ):
                target["memory_peak"] = metric["memory_peak"]
                target["memory_peak_replica"] = replica
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
        "memory_definition": snapshot["metrics"].get("memory_definition", "Unknown"),
        "query_definition": snapshot["metrics"].get("query_definition"),
        "units": snapshot["metrics"].get("units"),
        "cpu_rate_window_seconds": snapshot["metrics"].get("cpu_rate_window_seconds"),
        "cpu_alignment_window_seconds": snapshot["metrics"].get("cpu_alignment_window_seconds"),
        "resource_status": snapshot["metrics"].get(
            "resource_status", {"cpu": "unknown", "memory": "unknown"}
        ),
        "fallback_reason": snapshot["metrics"].get("fallback_reason"),
        "coverage": snapshot["metrics"].get("coverage", "unavailable"),
        "cadence_seconds": cadence,
        "minimum_samples": minimum,
        "warnings": warnings,
    }
