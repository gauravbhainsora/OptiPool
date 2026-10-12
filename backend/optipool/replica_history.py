"""Self-contained observed history; inventory points never imply past placement.

Only explicit membership intervals authorize samples. Publication copies evidence into
its immutable snapshot. Duplicate compatible points prefer the newest observation,
retaining each origin and conflicting value. Different definitions are excluded visibly.
"""

import math
from copy import deepcopy


def definition(metrics, resource):
    return {
        "source": metrics.get("source", "Unavailable"),
        "cadence_seconds": metrics.get("cadence_seconds"),
        "query": metrics.get("query_definition", {}),
        "meaning": metrics.get("memory_definition")
        if resource == "memory"
        else metrics.get("cpu_rate_window_seconds"),
    }


def inventory_evidence(snapshot):
    now = snapshot.get("collected_at", snapshot["metrics"]["cutoff"])
    nodes = {n["name"] for n in snapshot["nodes"]}
    return {
        p["uid"]: {
            "uid": p["uid"],
            "name": p["name"],
            "namespace": p["namespace"],
            "workload": p.get("workload"),
            "controller_uid": p.get("controller_uid"),
            "created": p.get("created"),
            "observed_at": now,
            "memberships": [
                {
                    "pool_id": snapshot["pool"]["id"],
                    "node": p["node"],
                    "start": now,
                    "end": now,
                    "provenance": "inventory observation",
                }
            ],
        }
        for p in snapshot.get("context", {}).get("pods", [])
        if p.get("uid") and p.get("node") in nodes and p.get("workload")
    }


def merge_history(snapshot, previous, snapshot_id):
    result = deepcopy(snapshot)
    metrics = result["metrics"]
    cutoff, pool_id = metrics["cutoff"], result["pool"]["id"]
    start = cutoff - 10 * 86400
    warnings = metrics.setdefault("warnings", [])
    evidence, points, definitions = {}, {}, {}
    retained_signature = None
    retained_metadata = None
    current = inventory_evidence(result)
    current.update(deepcopy(metrics.get("replica_evidence", {})))
    current_workloads = {w["id"]: w for w in result["workloads"]}
    rejected = set()
    rejected_pairs = {}

    def reject(uid, reason):
        rejected.add(reason)
        rejected_pairs.setdefault(reason, set()).update((uid, resource) for resource in ["cpu", "memory"])

    historical_workloads = {}
    # Oldest first; newest saved collection wins duplicate values deterministically.
    for item, origin in [*previous, (result, snapshot_id)]:
        source_metrics = item["metrics"]
        records = source_metrics.get("replica_evidence", {}) if origin != snapshot_id else current
        source_workloads = {w["id"]: w for w in item.get("workloads", [])}
        for sample in source_metrics.get("samples", []):
            uid, timestamp = sample.get("replica"), sample.get("time")
            if not isinstance(timestamp, (int, float)) or not start <= timestamp <= cutoff:
                continue
            record = records.get(uid)
            if (
                not record
                or record.get("uid") != uid
                or not record.get("created")
                or not record.get("controller_uid")
            ):
                reject(uid, "Legacy or missing replica/controller identity")
                continue
            workload = record.get("workload")
            if (
                not workload
                or workload != sample.get("workload")
                or not workload.startswith(record.get("namespace", "") + "/")
            ):
                reject(uid, "Uncertain workload ownership")
                continue
            active = current_workloads.get(workload)
            if active and active.get("controller_uid") != record["controller_uid"]:
                reject(uid, "Changed or uncertain controller identity")
                continue
            # A UID cannot silently acquire a different controller or creation time.
            known = evidence.get(uid)
            if known and any(
                known.get(k) != record.get(k) for k in ["workload", "controller_uid", "created"]
            ):
                reject(uid, "Conflicting replica identity")
                continue
            for resource in ["cpu", "memory"]:
                value = sample.get(resource)
                if (
                    value is None
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or value < 0
                ):
                    continue
                window = source_metrics.get("cpu_rate_window_seconds") if resource == "cpu" else 0
                if (
                    window is None
                    or not isinstance(window, (int, float))
                    or not math.isfinite(window)
                    or window < 0
                ):
                    reject(uid, "Unknown CPU rate window")
                    continue
                beginning = timestamp - window
                intervals = [
                    m
                    for m in record.get("memberships", [])
                    if m.get("pool_id") == pool_id
                    and m.get("node")
                    and m.get("provenance")
                    and m.get("start", math.inf) <= beginning
                    and timestamp <= m.get("end", -math.inf)
                ]
                if beginning < record["created"] or not intervals:
                    reject(uid, "Unknown pool membership or lifetime interval")
                    continue
                shape = definition(source_metrics, resource)
                wanted = definition(metrics, resource)
                # If the new monitoring source is unavailable, retained evidence supplies
                # one compatible definition, never a mix of incompatible histories.
                if wanted["source"] != "Unavailable" and shape != wanted:
                    reject(uid, "Incompatible retained metric definition")
                    continue
                if resource in definitions and shape != definitions[resource]:
                    reject(uid, "Incompatible retained metric definition")
                    continue
                signature = {
                    k: source_metrics.get(k)
                    for k in [
                        "source",
                        "query_definition",
                        "cadence_seconds",
                        "cpu_rate_window_seconds",
                        "memory_definition",
                        "units",
                    ]
                }
                if metrics.get("source") == "Unavailable":
                    if retained_signature is not None and signature != retained_signature:
                        reject(uid, "Incompatible retained metric definition")
                        continue
                    retained_signature, retained_metadata = signature, source_metrics
                definitions[resource] = shape
                evidence.setdefault(uid, deepcopy(record))
                for membership in intervals:
                    if membership not in evidence[uid]["memberships"]:
                        evidence[uid]["memberships"].append(deepcopy(membership))
                if workload in source_workloads:
                    historical_workloads[workload] = source_workloads[workload]
                point = points.setdefault(
                    (uid, timestamp),
                    {
                        "time": timestamp,
                        "replica": uid,
                        "workload": workload,
                        "attributed": True,
                        "provenance": {},
                    },
                )
                origins = point["provenance"].setdefault(resource, [])
                for old in sample.get("provenance", {}).get(resource, []):
                    if old not in origins:
                        origins.append(deepcopy(old))
                if not sample.get("provenance", {}).get(resource):
                    attribution = {
                        "snapshot_id": origin,
                        "value": value,
                        "definition": shape,
                        "memberships": deepcopy(intervals),
                    }
                    if attribution not in origins:
                        origins.append(attribution)
                point[resource] = value
    metrics["samples"] = [p for _, p in sorted(points.items())]
    metrics["replica_evidence"] = evidence
    metrics["history_version"] = 1
    metrics["history_policy"] = "Newest compatible observation wins duplicate values; all origins retained"
    accepted = {
        (point["replica"], resource)
        for point in points.values()
        for resource in ["cpu", "memory"]
        if resource in point
    }
    metrics["attribution_gaps"] = sorted(
        reason for reason, pairs in rejected_pairs.items() if pairs - accepted
    )
    metrics["history_exclusions"] = sorted(rejected)
    warnings.extend(
        "Historical evidence excluded: " + reason
        for reason in sorted(rejected)
        if "Historical evidence excluded: " + reason not in warnings
    )
    if metrics.get("source") == "Unavailable" and retained_metadata:
        for key in [
            "source",
            "query_definition",
            "cadence_seconds",
            "cpu_rate_window_seconds",
            "memory_definition",
            "units",
        ]:
            if key in retained_metadata:
                metrics[key] = deepcopy(retained_metadata[key])
    for workload, old in historical_workloads.items():
        if workload not in current_workloads:
            row = deepcopy(old)
            row.update(
                desired=0,
                running=0,
                pending=0,
                pool_replicas=0,
                requested={"cpu": 0, "memory": 0},
                limits={"cpu": 0, "memory": 0},
                historical_only=True,
            )
            result["workloads"].append(row)
    if points:
        metrics["coverage"] = (
            "partial — evidenced current and previously observed replicas; unobserved history may be missing"
        )
    else:
        metrics["coverage"] = "unavailable — no time-bounded attributable samples"
    return result
