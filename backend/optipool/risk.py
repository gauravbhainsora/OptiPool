"""Evaluate saved cumulative risk counters; no monitoring access on reads."""

import math
from collections import defaultdict

DEFAULT_POLICY = {
    "cpu_required": True,
    "memory_required": True,
    "throttling_threshold": 0.10,
    "minimum_observation_seconds": 86400,
    "minimum_coverage": 0.9,
}


def union_seconds(intervals):
    duration, last = 0, -math.inf
    for begin, end in sorted(intervals):
        duration += max(0, end - max(begin, last))
        last = max(last, end)
    return duration


def counter_intervals(series, boundaries, cadence):
    """Observed increases are lower bounds across resets, calculated before aggregation."""
    points = {}
    invalid = False
    for t, value in series.get("values", []):
        if not all(isinstance(v, (int, float)) and math.isfinite(v) and v >= 0 for v in [t, value]):
            invalid = True
            continue
        if t in points and points[t] != value:
            invalid = True
        points[t] = value
    intervals = {}
    resets = 0
    for (begin, before), (end, after) in zip(
        sorted(points.items()), sorted(points.items())[1:], strict=False
    ):
        if end - begin > cadence * 1.5 or not any(a <= begin < end <= b for a, b in boundaries):
            continue
        reset = after < before
        resets += reset
        intervals[begin, end] = after if reset else after - before
    return intervals, resets, invalid


def pod_risk(pod, metadata, start, cutoff, pool_id, policy):
    containers = [c["name"] for c in pod.get("spec", {}).get("containers", [])]
    # Restartable init sidecars run throughout the Pod; one-shot init execution has no
    # complete saved lifetime denominator and is reported as a limitation instead.
    containers += [
        c["name"] for c in pod.get("spec", {}).get("initContainers", []) if c.get("restartPolicy") == "Always"
    ]
    created = pod.get("created")
    boundaries = [(max(start, created), cutoff)] if created is not None else []
    if "memberships" in pod:
        boundaries = [
            (max(start, created or start, m["start"]), min(cutoff, m["end"]))
            for m in pod["memberships"]
            if m.get("pool_id") == pool_id
        ]
    cadence = metadata.get("cadence_seconds")
    cadence = cadence if isinstance(cadence, (int, float)) and cadence > 0 else None
    groups = defaultdict(dict)
    for series in metadata.get("series", []):
        if (
            series.get("replica") == pod.get("uid")
            and series.get("workload") == pod.get("workload")
            and series.get("container") in containers
        ):
            key = (series["container"], series.get("identity"))
            if not key[1]:
                continue
            kind = series.get("kind")
            if kind in groups[key]:
                # Ambiguous duplicate scrape sources must not double counts or hide gaps.
                groups[key][kind] = {"values": [[0, float("nan")]]}
            else:
                groups[key][kind] = series
    details = {"cpu": [], "memory": []}
    for container in containers:
        identities = [key for key in groups if key[0] == container] or [(container, None)]
        totals = {k: 0 for k in ["numerator", "denominator", "oom_events", "restarts", "counter_resets"]}
        cpu_intervals, memory_intervals = [], []
        invalid_cpu, invalid_memory = False, False
        cpu_present = memory_present = False
        event_present = {"oom_events": False, "restarts": False}
        reset_counts = {"cpu": 0, "memory": 0}
        for key in identities:
            counters = {}
            for kind, series in groups.get(key, {}).items():
                intervals, resets, invalid = (
                    counter_intervals(series, boundaries, cadence) if cadence else ({}, 0, True)
                )
                counters[kind] = intervals
                reset_counts["cpu" if kind in {"throttled_periods", "enforcement_periods"} else "memory"] += (
                    resets
                )
                if kind in {"throttled_periods", "enforcement_periods"}:
                    invalid_cpu |= invalid
                else:
                    invalid_memory |= invalid
            numerator, denominator = (
                counters.get("throttled_periods", {}),
                counters.get("enforcement_periods", {}),
            )
            paired = set(numerator) & set(denominator)
            cpu_present |= bool(paired)
            for interval in paired:
                if numerator[interval] > denominator[interval]:
                    invalid_cpu = True
                    continue
                totals["numerator"] += numerator[interval]
                totals["denominator"] += denominator[interval]
                cpu_intervals.append(interval)
            oom, restarts = counters.get("oom_events", {}), counters.get("restarts", {})
            for kind in ["oom_events", "restarts"]:
                totals[kind] += sum(counters.get(kind, {}).values())
                event_present[kind] |= bool(counters.get(kind))
            matched = set(oom) & set(restarts)
            memory_present |= bool(matched)
            memory_intervals.extend(matched)
        for resource, intervals, present, invalid in [
            ("cpu", cpu_intervals, cpu_present, invalid_cpu),
            ("memory", memory_intervals, memory_present, invalid_memory),
        ]:
            duration = union_seconds(intervals) if cadence and present else None
            coverage = duration / (cutoff - start) if duration is not None else None
            available = bool(
                not invalid
                and duration is not None
                and duration >= policy["minimum_observation_seconds"]
                and coverage >= policy["minimum_coverage"]
            )
            ratio = (
                totals["numerator"] / totals["denominator"]
                if cpu_present and totals["denominator"] > 0 and not invalid_cpu
                else None
            )
            if resource == "cpu" and ratio is None:
                available = False
            adverse = (
                ratio is not None and ratio >= policy["throttling_threshold"]
                if resource == "cpu"
                else totals["oom_events"] > 0 or totals["restarts"] > 0
            )
            selected_totals = dict(totals)
            selected_totals["counter_resets"] = reset_counts[resource] if present else None
            for kind in ["oom_events", "restarts"]:
                if resource == "cpu" or not event_present[kind]:
                    selected_totals[kind] = None
            if resource == "memory" or not cpu_present:
                selected_totals["numerator"] = selected_totals["denominator"] = None
            details[resource].append(
                dict(
                    container=container,
                    status="available" if available else "unknown",
                    represented_seconds=duration,
                    selected_window_coverage=coverage,
                    ratio=ratio if resource == "cpu" else None,
                    adverse=adverse,
                    **selected_totals,
                )
            )
    results = {}
    for resource in ["cpu", "memory"]:
        parts = details[resource]
        available = bool(parts) and all(p["status"] == "available" for p in parts)
        adverse = any(p["adverse"] for p in parts)
        reasons = []
        if adverse:
            reasons.append(
                "Historical CPU throttling meets the configured risk threshold"
                if resource == "cpu"
                else "Historical OOM/restart events observed"
            )
        if not available:
            reasons.append(
                f"Required {resource} risk evidence unavailable or below duration/coverage policy"
                if policy[resource + "_required"]
                else f"Optional {resource} risk evidence unknown"
            )
        totals = {
            k: sum(p[k] or 0 for p in parts) if parts and any(p[k] is not None for p in parts) else None
            for k in ["numerator", "denominator", "oom_events", "restarts", "counter_resets"]
        }
        ratio = totals["numerator"] / totals["denominator"] if totals["denominator"] else None
        results[resource + "_risk"] = dict(
            status="available" if available else "unknown",
            adverse=adverse,
            eligible=not adverse and (available or not policy[resource + "_required"]),
            required=policy[resource + "_required"],
            reasons=reasons,
            source=metadata.get("source", "Unavailable"),
            cadence_seconds=cadence,
            minimum_observation_seconds=policy["minimum_observation_seconds"],
            minimum_coverage=policy["minimum_coverage"],
            represented_seconds=min((p["represented_seconds"] for p in parts), default=None)
            if all(p["represented_seconds"] is not None for p in parts)
            else None,
            selected_window_coverage=min((p["selected_window_coverage"] for p in parts), default=None)
            if all(p["selected_window_coverage"] is not None for p in parts)
            else None,
            ratio=ratio if resource == "cpu" else None,
            threshold=policy["throttling_threshold"] if resource == "cpu" else None,
            containers=parts,
            **totals,
            limitations=[
                "Sampled counter increases are lower bounds; events between scrapes and resets may be missed",
                "Ordinary and restartable init containers; one-shot init history is incomplete",
                "Captured current/last Kubernetes termination state is additional evidence, not complete event history",
            ],
        )
    return results


def attach_risk(snapshot, usage, policy=None):
    policy = {**DEFAULT_POLICY, **(policy or {})}
    metadata = snapshot["metrics"].get("risk", {})
    observed = {
        p["uid"]: p
        for p in snapshot.get("context", {}).get("pods", [])
        if p.get("node") in {n["name"] for n in snapshot["nodes"]}
    }
    pods = dict(observed)
    for uid, record in snapshot["metrics"].get("replica_evidence", {}).items():
        same_identity = all(
            observed.get(uid, {}).get(key) == record.get(key) for key in ["uid", "workload", "created"]
        )
        pods[uid] = {**(observed.get(uid, {}) if same_identity else {}), **record}
    members = defaultdict(list)
    for uid, pod in pods.items():
        if uid not in observed and not any(
            m.get("pool_id") == snapshot["pool"]["id"]
            and m["start"] <= usage["cutoff"]
            and m["end"] >= usage["start"]
            for m in pod.get("memberships", [])
        ):
            continue
        risk = pod_risk(pod, metadata, usage["start"], usage["cutoff"], snapshot["pool"]["id"], policy)
        usage["pods"].setdefault(uid, {"workload": pod["workload"]}).update(risk)
        members[pod["workload"]].append((uid, risk))
    for workload in snapshot["workloads"]:
        metric = usage["workloads"].get(workload["id"])
        if metric is None:
            continue
        for resource in ["cpu", "memory"]:
            parts = [r[resource + "_risk"] for _, r in members[workload["id"]]]
            empty = pod_risk({}, metadata, usage["start"], usage["cutoff"], snapshot["pool"]["id"], policy)[
                resource + "_risk"
            ]
            risk = dict(parts[0] if parts else empty)
            risk["containers"] = [
                dict(c, replica=uid)
                for uid, r in members[workload["id"]]
                for c in r[resource + "_risk"]["containers"]
            ]
            risk["status"] = (
                "available"
                if parts
                and all(p["status"] == "available" for p in parts)
                and len([uid for uid, _ in members[workload["id"]] if uid in observed])
                >= workload.get("pool_replicas", 0)
                else "unknown"
            )
            risk["adverse"] = any(p["adverse"] for p in parts)
            risk["eligible"] = not risk["adverse"] and (risk["status"] == "available" or not risk["required"])
            risk["reasons"] = list(dict.fromkeys(reason for p in parts or [empty] for reason in p["reasons"]))
            if (
                risk["status"] == "unknown"
                and risk["required"]
                and not any("unavailable" in r for r in risk["reasons"])
            ):
                risk["reasons"].append(
                    f"Required {resource} risk evidence unavailable for one or more replicas"
                )
            for key in ["numerator", "denominator", "oom_events", "restarts", "counter_resets"]:
                risk[key] = (
                    sum(p[key] or 0 for p in parts)
                    if parts and any(p[key] is not None for p in parts)
                    else None
                )
            risk["ratio"] = (
                risk["numerator"] / risk["denominator"] if resource == "cpu" and risk["denominator"] else None
            )
            risk["represented_seconds"] = (
                min((p["represented_seconds"] for p in parts), default=None)
                if all(p["represented_seconds"] is not None for p in parts)
                else None
            )
            risk["selected_window_coverage"] = min(
                (p["selected_window_coverage"] or 0 for p in parts), default=None
            )
            metric[resource + "_risk"] = risk
    usage["historical_replicas"] = [
        {"uid": uid, **metric} for uid, metric in usage["pods"].items() if metric.get("historical")
    ]
    usage["risk_policy"] = policy
    usage["risk_warnings"] = metadata.get("warnings", [])
    return usage


def retain_risk(snapshot, previous, snapshot_id):
    """Embed only compatible counters for UID/pool intervals accepted by history merge."""
    from copy import deepcopy

    metrics = snapshot["metrics"]
    metadata = metrics.get("risk")
    if not metadata or metadata.get("source") == "Unavailable":
        return
    signature = {k: metadata.get(k) for k in ["source", "cadence_seconds", "definitions"]}
    records = metrics.get("replica_evidence", {})
    beginning, end = metrics["cutoff"] - 10 * 86400, metrics["cutoff"]
    saved = {}
    warnings = metadata.setdefault("warnings", [])
    for candidate, origin in [*previous, (snapshot, snapshot_id)]:
        evidence = candidate["metrics"].get("risk", {})
        if {k: evidence.get(k) for k in signature} != signature:
            if evidence.get("series"):
                warning = "Excluded retained risk counters with incompatible source/definition/cadence"
                if warning not in warnings:
                    warnings.append(warning)
            continue
        for series in evidence.get("series", []):
            record = records.get(series.get("replica"))
            if not record or record.get("workload") != series.get("workload"):
                continue
            key = tuple(series.get(k) for k in ["replica", "workload", "container", "identity", "kind"])
            if not all(key):
                continue
            value = saved.setdefault(
                key,
                {
                    **{k: deepcopy(v) for k, v in series.items() if k not in {"values", "provenance"}},
                    "points": {},
                    "provenance": [],
                },
            )
            for t, counter in series.get("values", []):
                if (
                    not isinstance(t, (int, float))
                    or not isinstance(counter, (int, float))
                    or not math.isfinite(t)
                    or not math.isfinite(counter)
                    or counter < 0
                ):
                    continue
                if (
                    beginning <= t <= end
                    and t >= record["created"]
                    and any(
                        m.get("pool_id") == snapshot["pool"]["id"]
                        and m.get("node")
                        and m.get("provenance")
                        and m["start"] <= t <= m["end"]
                        for m in record.get("memberships", [])
                    )
                ):
                    if t in value["points"] and value["points"][t] != counter:
                        warning = (
                            "Conflicting saved risk counter point; newest compatible observation selected"
                        )
                        if warning not in warnings:
                            warnings.append(warning)
                    value["points"][t] = counter
                    for old_origin in series.get("provenance", []) or [origin]:
                        if old_origin not in value["provenance"]:
                            value["provenance"].append(old_origin)
    metadata["series"] = []
    for value in saved.values():
        points = value.pop("points")
        if points:
            metadata["series"].append({**value, "values": [[t, v] for t, v in sorted(points.items())]})
