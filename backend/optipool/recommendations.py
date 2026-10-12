"""Advisory effective Pod request proposals from saved observations; no workload writes."""

import math

from .pods import selected_pods


def recommend(snapshot, usage, headroom=20):
    result = []
    pods = selected_pods(snapshot)
    for workload in snapshot["workloads"]:
        if workload["kind"] != "Deployment":
            continue
        members = [p for p in pods if p["workload"] == workload["id"]]
        metrics = usage["workloads"].get(workload["id"], {})
        warnings = list(usage["warnings"])
        warnings.append("CPU throttling history is not collected; inspect it before reducing CPU requests")
        if len({(p["requested"]["cpu"], p["requested"]["memory"]) for p in members}) > 1:
            warnings.append(
                "Replicas have different effective requests; proposal requires per-template review"
            )
        if any(p["restarts"] for p in members):
            warnings.append("Saved replicas have restarts; memory reductions are withheld")
        oom = any(p.get("oom_killed") for p in members)
        if oom:
            warnings.append("OOMKilled observed; memory reductions are withheld")
        if any(not p.get("status_available") for p in members):
            warnings.append(
                "Container termination evidence is absent in this snapshot; check OOM history before reducing memory"
            )
        current, proposed = workload["per_replica"], {}
        recovered = {}
        for key, step in [("cpu", 0.01), ("memory", 16 * 1024**2)]:
            p99 = metrics.get(key + "_p99")
            value = p99
            if key == "memory" and p99 is not None:
                value = max(
                    [p99, metrics.get("memory_peak") or 0]
                    + [usage["pods"].get(p["uid"], {}).get("memory_peak") or 0 for p in members]
                )
            proposed[key] = (
                max(step, math.ceil(value * (1 + headroom / 100) / step) * step)
                if value is not None
                else None
            )
            if key == "memory" and proposed[key] is not None and (oom or any(p["restarts"] for p in members)):
                proposed[key] = max([current[key], proposed[key]] + [p["requested"][key] for p in members])
            recovered[key] = (
                sum(p["requested"][key] for p in members) - proposed[key] * len(members)
                if proposed[key] is not None
                else None
            )
        covered = [usage["pods"].get(p["uid"], {}) for p in members]
        fractions = [m.get(k + "_coverage") for m in covered for k in ["cpu", "memory"]]
        coverage = min(fractions) if fractions and all(v is not None for v in fractions) else None
        if coverage is None or coverage < 0.8:
            warnings.append("Incomplete sample coverage; request proposals are provisional")
        if proposed["cpu"] is None or proposed["memory"] is None:
            warnings.append("Insufficient attributable samples for one or more resources")
        result.append(
            {
                "workload_id": workload["id"],
                "name": workload["name"],
                "namespace": workload["namespace"],
                "current": current,
                "proposed": proposed,
                "recovered": recovered,
                "cpu_p99": metrics.get("cpu_p99"),
                "memory_p99": metrics.get("memory_p99"),
                "coverage": coverage,
                "pool_replicas": workload["pool_replicas"],
                "status": "Insufficient data" if None in proposed.values() else "Review required",
                "warnings": list(dict.fromkeys(warnings)),
            }
        )
    return {
        "headroom_percent": headroom,
        "days": usage["days"],
        "snapshot_id": snapshot["id"],
        "rows": result,
        "assumption": "Effective Pod request proposals, not per-container limits. Memory uses observed peak as a floor. No automatic changes or guaranteed savings.",
    }
