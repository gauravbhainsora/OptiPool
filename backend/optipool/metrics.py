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
    samples = snapshot["metrics"].get("samples", [])
    replicas = defaultdict(lambda: {"cpu": [], "memory": [], "times": set()})
    timeline = defaultdict(lambda: {"cpu": None, "memory": None})
    for sample in samples:
        if not start <= sample["time"] <= cutoff:
            continue
        # A sample is emitted only with evidence of workload and selected-pool membership.
        if not sample.get("attributed"):
            continue
        r = replicas[(sample["workload"], sample["replica"])]
        r["times"].add(sample["time"])
        for k in ["cpu", "memory"]:
            value = sample.get(k)
            if value is not None and math.isfinite(value):
                r[k].append(value)
                timeline[sample["time"]][k] = (timeline[sample["time"]][k] or 0) + value
    workloads = {}
    for (workload, replica), data in replicas.items():
        target = workloads.setdefault(
            workload,
            {
                "cpu_p99": None,
                "memory_p99": None,
                "cpu_replica": None,
                "memory_replica": None,
                "replicas_observed": 0,
                "samples": 0,
            },
        )
        target["replicas_observed"] += 1
        target["samples"] += len(data["times"])
        for k in ["cpu", "memory"]:
            value = percentile(data[k]) if len(data[k]) >= minimum else None
            if value is not None and (target[k + "_p99"] is None or value > target[k + "_p99"]):
                target[k + "_p99"], target[k + "_replica"] = value, replica
    return {
        "days": days,
        "start": start,
        "cutoff": cutoff,
        "workloads": workloads,
        "timeline": [{"time": t, **v} for t, v in sorted(timeline.items())],
        "source": snapshot["metrics"].get("source", "Unavailable"),
        "memory_definition": snapshot["metrics"].get("memory_definition", "Unavailable"),
        "coverage": snapshot["metrics"].get("coverage", "unavailable"),
        "minimum_samples": minimum,
        "warnings": snapshot["metrics"].get("warnings", []),
    }
