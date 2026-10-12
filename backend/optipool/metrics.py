import math
from collections import defaultdict

from .risk import attach_risk


def percentile(values, p=0.99):
    values = sorted(v for v in values if math.isfinite(v))
    if not values:
        return None
    index = (len(values) - 1) * p
    low, high = math.floor(index), math.ceil(index)
    return values[low] + (values[high] - values[low]) * (index - low)


def resource_evidence(times, pod, resource, metadata, start, cutoff, policy, pool_id=None):
    """Count the union of valid evaluation intervals, never the first/last span."""
    cadence = metadata.get("cadence_seconds")
    cadence = cadence if isinstance(cadence, (int, float)) and cadence > 0 else None
    rate_window = metadata.get("cpu_rate_window_seconds")
    if rate_window is None:
        rate_window = metadata.get("cpu_alignment_window_seconds")
    definition_basis = "Saved metadata" if rate_window is not None else "Unknown"
    if rate_window is None:
        # Definitions of older saved collectors are known; arbitrary sources are not.
        rate_window = (
            0
            if metadata.get("source", "").startswith("Synthetic")
            else (300 if metadata.get("source") in {"GMP cAdvisor", "Native GKE Cloud Monitoring"} else None)
        )
        if rate_window is not None:
            definition_basis = "Inferred from documented legacy collector definition"
    created = pod.get("created")
    known = created is not None and cadence is not None and (resource != "cpu" or rate_window is not None)
    eligible_start = max(start, created + (rate_window if resource == "cpu" else 0)) if known else None
    intervals = [(eligible_start if known else start, cutoff)]
    if "memberships" in pod:
        bounded = []
        for membership in pod["memberships"]:
            if (
                membership.get("pool_id") != pool_id
                or created is None
                or (resource == "cpu" and rate_window is None)
            ):
                continue
            begin = max(start, max(created, membership["start"]) + (rate_window if resource == "cpu" else 0))
            end = min(cutoff, membership["end"])
            if begin <= end:
                bounded.append((begin, end))
        intervals = []
        for begin, end in sorted(bounded):
            if intervals and begin <= intervals[-1][1]:
                intervals[-1] = (intervals[-1][0], max(end, intervals[-1][1]))
            else:
                intervals.append((begin, end))
    times = sorted(t for t in times if any(begin <= t <= end for begin, end in intervals))
    duration = None
    expected = None
    lifetime_coverage = None
    if cadence is not None:
        duration = 0
        for boundary, limit in intervals:
            end = boundary
            for t in times:
                if not boundary <= t <= limit:
                    continue
                begin = max(boundary, t - cadence, end)
                duration += max(0, t - begin)
                end = max(end, t)
        if known:
            expected = sum(max(0, math.floor((end - begin) / cadence) + 1) for begin, end in intervals)
            eligible_seconds = sum(end - begin for begin, end in intervals)
            lifetime_coverage = min(1, duration / eligible_seconds) if eligible_seconds else None
    window_coverage = min(1, duration / (cutoff - start)) if duration is not None else None
    reasons = []
    if len(times) < policy["minimum_samples"]:
        reasons.append(f"sample count {len(times)} below {policy['minimum_samples']}")
    if duration is None or duration < policy["minimum_observation_seconds"]:
        reasons.append("represented observation duration is unknown or below policy minimum")
    if not known:
        reasons.append("Pod lifetime or resource sampling definition is unknown")
    if window_coverage is None or window_coverage < policy["minimum_coverage"]:
        reasons.append("selected-window coverage is unknown or below policy minimum")
    return {
        "valid_samples": len(times),
        "expected_samples": expected,
        "represented_seconds": duration,
        "lifetime_coverage": lifetime_coverage,
        "selected_window_coverage": window_coverage,
        "eligible": not reasons,
        "reasons": reasons,
        "partial": False,
        "replica": pod.get("uid"),
        "source": metadata.get("source", "Unavailable"),
        "cadence_seconds": cadence,
        "cpu_rate_window_seconds": rate_window if resource == "cpu" else None,
        "definition_basis": definition_basis if resource == "cpu" else "Saved metadata",
        "eligible_start": eligible_start,
        "eligible_intervals": intervals,
    }


def summarize(
    snapshot, days, minimum=20, minimum_observation_seconds=86400, minimum_coverage=0.9, risk_policy=None
):
    cutoff = snapshot["metrics"]["cutoff"]
    start = cutoff - days * 86400
    cadence = snapshot["metrics"].get("cadence_seconds")
    policy = {
        "minimum_samples": minimum,
        "minimum_observation_seconds": minimum_observation_seconds,
        "minimum_coverage": minimum_coverage,
    }
    selected_nodes = {n["name"] for n in snapshot.get("nodes", [])}
    observed = {
        p["uid"]: p for p in snapshot.get("context", {}).get("pods", []) if p.get("node") in selected_nodes
    }
    history = snapshot["metrics"].get("replica_evidence", {})
    evidence_pods = {**observed, **history}
    replicas = defaultdict(dict)
    warnings = list(snapshot["metrics"].get("warnings", []))
    memory_definition = snapshot["metrics"].get("memory_definition", "Unknown")
    excluded_resources = set()
    for sample in snapshot["metrics"].get("samples", []):
        if start <= sample["time"] <= cutoff and sample.get("attributed"):
            for resource in ["cpu", "memory"]:
                if (
                    resource == "memory"
                    and sample.get("memory_definition", memory_definition) != memory_definition
                ):
                    excluded_resources.add(resource)
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

        metric = {
            "workload": workload,
            "historical": historical,
            "identity": history.get(replica),
            "samples": len(points),
            "last_sample_at": max(points),
        }
        for resource in ["cpu", "memory"]:
            evidence = resource_evidence(
                [t for t, p in points.items() if resource in p],
                evidence_pods.get(replica, {"uid": replica}),
                resource,
                snapshot["metrics"],
                start,
                cutoff,
                policy,
                snapshot["pool"]["id"],
            )
            metric[resource + "_evidence"] = evidence
            values = [
                p[resource]
                for t, p in points.items()
                if resource in p and (any(begin <= t <= end for begin, end in evidence["eligible_intervals"]))
            ]
            metric[resource + "_samples"] = len(values)
            expected = evidence["expected_samples"]
            metric[resource + "_expected_samples"] = expected
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
            latest = max(
                (
                    t
                    for t, p in points.items()
                    if resource in p
                    and any(begin <= t <= end for begin, end in evidence["eligible_intervals"])
                ),
                default=None,
            )
            metric[resource + "_latest"] = points[latest][resource] if latest is not None else None
            metric[resource + "_sample_at"] = latest
            p99 = metric[resource + "_p99"]
            if p99 is not None and (target[resource + "_p99"] is None or p99 > target[resource + "_p99"]):
                target[resource + "_p99"], target[resource + "_replica"] = p99, replica
                target[resource + "_evidence"] = dict(evidence)
            for t, point in points.items():
                if resource in point and any(
                    begin <= t <= end for begin, end in evidence["eligible_intervals"]
                ):
                    timeline[t][resource] = (timeline[t][resource] or 0) + point[resource]
        pod_metrics[replica] = metric
    nodes = {n["name"] for n in snapshot.get("nodes", [])}
    for workload in snapshot.get("workloads", []):
        target = workloads.get(workload["id"])
        if target is None:
            continue
        current_members = [
            p for p in observed.values() if p.get("workload") == workload["id"] and p.get("node") in nodes
        ]
        current_uids = {member["uid"] for member in current_members}
        members = [
            p
            for p in evidence_pods.values()
            if p.get("workload") == workload["id"]
            and (
                p.get("uid") in current_uids
                or any(
                    membership.get("pool_id") == snapshot["pool"]["id"]
                    and membership.get("start", math.inf) <= cutoff
                    and membership.get("end", -math.inf) >= start
                    for membership in p.get("memberships", [])
                )
            )
        ]
        for resource in ["cpu", "memory"]:
            evidence = target.get(resource + "_evidence") or resource_evidence(
                [], {}, resource, snapshot["metrics"], start, cutoff, policy
            )
            member_evidence = [pod_metrics.get(p["uid"], {}).get(resource + "_evidence") for p in members]
            partial = (
                resource in excluded_resources
                or bool(snapshot["metrics"].get("attribution_gaps"))
                or len(current_members) < workload.get("pool_replicas", 0)
                or any(e is None or e["valid_samples"] < minimum for e in member_evidence)
            )
            reasons = list(evidence["reasons"])
            if partial:
                reasons.append("missing or excluded replica; observed maximum is partial")
            if any(e is None or not e["eligible"] for e in member_evidence):
                reasons.append("one or more replicas have insufficient evidence")
            for member, detail in zip(members, member_evidence, strict=True):
                for reason in detail["reasons"] if detail else ["Sampling evidence unavailable"]:
                    reasons.append(f"replica {member['uid']}: {reason}")
            evidence.update(partial=partial, eligible=not reasons, reasons=list(dict.fromkeys(reasons)))
            target[resource + "_evidence"] = evidence
    return attach_risk(
        snapshot,
        {
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
            "reduction_policy": policy,
            "warnings": warnings,
            "attribution_gaps": snapshot["metrics"].get("attribution_gaps", []),
            "historical_replicas": [{"uid": uid, **m} for uid, m in pod_metrics.items() if m["historical"]],
        },
        risk_policy,
    )
