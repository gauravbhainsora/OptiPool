"""Read an explicitly configured immutable historical membership interval contract.

A metadata point is an upstream assertion about a bounded interval, never an
inference from a current object or from an unjoined kube-state-metrics sample.
"""

import json
import math
from collections import defaultdict
from copy import deepcopy

REQUIRED = (
    "project_id location cluster namespace pod uid controller_kind controller_name controller_uid "
    "owner_kind owner_name owner_uid node node_uid node_pool created start end"
).split()


def matrix(response):
    data = response.get("data", {})
    if (
        response.get("status") != "success"
        or data.get("resultType") != "matrix"
        or not isinstance(data.get("result"), list)
    ):
        raise ValueError("Historical source returned an invalid matrix")
    if response.get("warnings") or response.get("infos"):
        raise ValueError("Historical source reported incomplete query results")
    return data["result"]


def enrich_history(collector, pool, snapshot, metrics):
    settings = collector.settings
    metric = settings.historical_metadata_metric
    if not metric:
        metrics["historical_discovery"] = {
            "status": "disabled",
            "replicas_discovered": 0,
            "reasons": ["Historical metadata source is not configured"],
        }
        return metrics
    now = metrics["cutoff"]
    beginning = now - settings.historical_metadata_lookback_days * 86400
    report = {
        "status": "unavailable",
        "replicas_discovered": 0,
        "metadata_metric": metric,
        "step_seconds": settings.historical_metadata_step_seconds,
        "start": beginning,
        "cutoff": now,
        "reasons": [],
    }
    metrics["historical_discovery"] = report
    reasons, global_gaps, gap_details = set(), set(), []

    def note(reason, labels=None, resource=None):
        reasons.add(reason)
        labels = labels or {}
        workload = labels.get("workload")
        if not workload and all(labels.get(k) for k in ["namespace", "controller_kind", "controller_name"]):
            workload = "/".join(labels[k] for k in ["namespace", "controller_kind", "controller_name"])
        if workload:
            for key in [resource] if resource else ["cpu", "memory"]:
                detail = {
                    "workload": workload,
                    "replica": labels.get("uid"),
                    "resource": key,
                    "reason": reason,
                }
                if detail not in gap_details:
                    gap_details.append(detail)
        else:
            global_gaps.add(reason)

    endpoint = f"https://monitoring.googleapis.com/v1/projects/{pool['project']}/location/global/prometheus/api/v1/query_range"
    scope = {"project_id": pool["project"], "location": pool["location"], "cluster": pool["cluster"]}
    match = ",".join(k + "=" + json.dumps(v) for k, v in scope.items())
    records, invalid, names = {}, set(), defaultdict(list)
    active = {w["id"]: w for w in snapshot["workloads"]}
    inventory = {p["uid"]: p for p in snapshot.get("context", {}).get("pods", [])}
    try:
        # The pool label scopes collection; replies are independently validated.
        series = matrix(
            collector.get(
                endpoint,
                {
                    "query": metric + "{" + match + ",node_pool=" + json.dumps(pool["name"]) + "}",
                    "start": beginning,
                    "end": now,
                    "step": settings.historical_metadata_step_seconds,
                },
            )
        )
        if len(series) > settings.historical_metadata_max_replicas * 20:
            raise ValueError("Historical metadata series limit exceeded")
        total_points = 0
        for item in series:
            labels = item.get("metric", {})
            if any(
                not isinstance(labels.get(k), str) or not labels[k] or len(labels[k]) > 253 for k in REQUIRED
            ):
                note("Historical metadata missing required identity/interval labels", labels)
                if labels.get("uid"):
                    invalid.add(labels["uid"])
                continue
            uid = labels["uid"]
            if any(labels[k] != v for k, v in scope.items()):
                reasons.add("Historical metadata has foreign project/location/cluster")
                continue
            observations = item.get("values", [])
            total_points += len(observations)
            if total_points > 200000 or len(observations) > 15000:
                raise ValueError("Historical metadata point limit exceeded")
            try:
                created, start, end = (float(labels[k]) for k in ["created", "start", "end"])
                seen = [float(t) for t, value in observations if float(value) == 1]
                if (
                    not seen
                    or any(not math.isfinite(t) or not beginning <= t <= now for t in seen)
                    or not all(math.isfinite(t) for t in [created, start, end])
                    or not 0 < created <= start <= end <= max(seen)
                    or end < beginning
                ):
                    raise ValueError("Invalid interval")
            except (ValueError, TypeError):
                note("Historical metadata has invalid or unsupported lifetime interval", labels)
                invalid.add(uid)
                continue
            kind, controller = labels["controller_kind"], labels["controller_name"]
            owner = labels["owner_kind"]
            if kind not in {"Deployment", "ReplicaSet", "StatefulSet", "DaemonSet", "Job", "CronJob", "Pod"}:
                note("Historical controller kind is unsupported", labels)
                invalid.add(uid)
                continue
            if not (
                (
                    owner == kind
                    and labels["owner_name"] == controller
                    and labels["owner_uid"] == labels["controller_uid"]
                )
                or (
                    owner == "ReplicaSet"
                    and kind == "Deployment"
                    and labels["owner_uid"] != labels["controller_uid"]
                )
            ):
                note("Historical controller ownership chain is unsupported or ambiguous", labels)
                invalid.add(uid)
                continue
            workload = labels["namespace"] + "/" + kind + "/" + controller
            record = {
                "uid": uid,
                "name": labels["pod"],
                "namespace": labels["namespace"],
                "workload": workload,
                "controller_uid": labels["controller_uid"],
                "created": created,
                "observed_at": max(seen),
                "owner_kind": owner,
                "owner_name": labels["owner_name"],
                "owner_uid": labels["owner_uid"],
                "memberships": [],
            }
            known = records.get(uid)
            identity = [
                "name",
                "namespace",
                "workload",
                "controller_uid",
                "created",
                "owner_kind",
                "owner_name",
                "owner_uid",
            ]
            if known and any(known[k] != record[k] for k in identity):
                note("Historical replica has conflicting lifetime/owner identity", labels)
                invalid.add(uid)
                continue
            membership = {
                "pool_id": f"{pool['project']}/{pool['location']}/{pool['cluster']}/{labels['node_pool']}",
                "node": labels["node"],
                "node_uid": labels["node_uid"],
                "start": max(beginning, start),
                "end": end,
                "provenance": {
                    "contract": "optipool-membership-v1",
                    "metric": metric,
                    "observed_at": max(seen),
                },
            }
            # Pool ids follow the repository discovery identity, including region.
            if labels["node_pool"] == pool["name"]:
                membership["pool_id"] = pool["id"]
            record = records.setdefault(uid, record)
            if membership not in record["memberships"]:
                record["memberships"].append(membership)
                names[(record["namespace"], record["name"])].append((uid, membership))
        if len(records) > settings.historical_metadata_max_replicas:
            raise ValueError("Historical replica limit exceeded")
        for intervals in names.values():
            for index, (uid, member) in enumerate(intervals):
                for other_uid, other in intervals[index + 1 :]:
                    overlap = max(member["start"], other["start"]) <= min(member["end"], other["end"])
                    if overlap and (
                        uid != other_uid
                        or any(member[k] != other[k] for k in ["node", "node_uid", "pool_id"])
                    ):
                        invalid.update([uid, other_uid])
                        note("Historical name or node membership intervals are ambiguous", records[uid])
                        note("Historical name or node membership intervals are ambiguous", records[other_uid])
        accepted = {}
        for uid, record in records.items():
            if uid in invalid:
                continue
            current = inventory.get(uid)
            if current and any(
                current.get(key) != record[key]
                for key in ["name", "namespace", "workload", "controller_uid", "created"]
            ):
                note("Historical metadata conflicts with current replica identity", record)
                continue
            if (
                record["workload"] in active
                and active[record["workload"]].get("controller_uid") != record["controller_uid"]
            ):
                note("Historical controller lifetime differs from the current controller", record)
                continue
            record["memberships"] = [m for m in record["memberships"] if m["pool_id"] == pool["id"]]
            if not record["memberships"]:
                reasons.add("Historical replica belongs to a foreign pool")
                continue
            if current:
                record["spec"] = deepcopy(current.get("spec", {}))
                record["container_statuses"] = deepcopy(current.get("container_statuses", []))
            accepted[uid] = record
        report["replicas_discovered"] = len(accepted)
        report["replica_evidence"] = deepcopy(accepted)
        metrics.setdefault("replica_evidence", {}).update(deepcopy(accepted))
        if not accepted:
            note("No valid historical membership intervals found")
        elif metrics["source"] not in {"Unavailable", "GMP cAdvisor"}:
            reasons.add("Historical GMP usage is incompatible with the selected metric source")
        else:
            required_requests = 2 * sum(len(r["memberships"]) for r in accepted.values())
            if required_requests > settings.historical_metadata_max_requests:
                raise ValueError("Historical usage request limit exceeded")
            points = {}
            for uid, record in accepted.items():
                for membership in record["memberships"]:
                    selectors = {**scope, "namespace": record["namespace"], "pod": record["name"]}
                    scoped = (
                        ",".join(k + "=" + json.dumps(v) for k, v in selectors.items())
                        + ',container!="",container!="POD"'
                    )
                    for resource, expression in [
                        ("cpu", f"rate(container_cpu_usage_seconds_total{{{scoped}}}[5m])"),
                        ("memory", f"container_memory_working_set_bytes{{{scoped}}}"),
                    ]:
                        query = "sum by(namespace,pod,uid,node,node_uid)(" + expression + ")"
                        responses = matrix(
                            collector.get(
                                endpoint,
                                {
                                    "query": query,
                                    "start": membership["start"],
                                    "end": membership["end"],
                                    "step": settings.metric_cadence_seconds,
                                },
                            )
                        )
                        if len(responses) > 10:
                            raise ValueError("Historical usage series limit exceeded")
                        seen_times = set()
                        for series in responses:
                            labels = series.get("metric", {})
                            if (
                                labels.get("namespace") != record["namespace"]
                                or labels.get("pod") != record["name"]
                                or any(
                                    labels.get(k) and labels[k] != v
                                    for k, v in {
                                        **scope,
                                        "uid": uid,
                                        "node": membership["node"],
                                        "node_uid": membership["node_uid"],
                                    }.items()
                                )
                            ):
                                note(
                                    "Historical usage labels conflict with metadata identity",
                                    record,
                                    resource,
                                )
                                continue
                            values = series.get("values", [])
                            total_points += len(values)
                            if total_points > 200000 or len(values) > 15000:
                                raise ValueError("Historical usage point limit exceeded")
                            for t, value in values:
                                t, value = float(t), float(value)
                                if not math.isfinite(t) or not math.isfinite(value) or value < 0:
                                    continue
                                if (
                                    not membership["start"] + (300 if resource == "cpu" else 0)
                                    <= t
                                    <= membership["end"]
                                ):
                                    reasons.add("Historical usage outside supported membership or CPU window")
                                    continue
                                if t in seen_times:
                                    raise ValueError("Historical usage has duplicate ambiguous series")
                                seen_times.add(t)
                                points.setdefault(
                                    (uid, t),
                                    {
                                        "replica": uid,
                                        "workload": record["workload"],
                                        "time": t,
                                        "attributed": True,
                                    },
                                )[resource] = value
            if points:
                metrics["samples"].extend(points.values())
                metrics.setdefault("replica_evidence", {}).update(deepcopy(accepted))
                collector.describe_metrics(metrics, "GMP cAdvisor", "Working set")
                metrics["warnings"] = [
                    warning
                    for warning in metrics["warnings"]
                    if warning
                    != "Deleted replicas and earlier ownership/pool history are not reconstructed; highest p99 may be understated"
                ]
                # New historical controllers have zero current inventory counts/requests.
                for record in accepted.values():
                    if record["workload"] not in active:
                        namespace, kind, name = record["workload"].split("/", 2)
                        row = {
                            "id": record["workload"],
                            "namespace": namespace,
                            "kind": kind,
                            "name": name,
                            "controller_uid": record["controller_uid"],
                            "desired": 0,
                            "running": 0,
                            "pending": 0,
                            "pool_replicas": 0,
                            "services": [],
                            "per_replica": {"cpu": 0, "memory": 0},
                            "requested": {"cpu": 0, "memory": 0},
                            "limits": {"cpu": 0, "memory": 0},
                            "spec": {},
                            "historical_only": True,
                        }
                        snapshot["workloads"].append(row)
                        active[row["id"]] = row
            else:
                reasons.add("Historical usage unavailable within supported intervals")
        report["status"] = "partial" if accepted else "unavailable"
    except Exception as exc:
        reason = "Historical source unavailable: " + str(exc)[:200]
        if report.get("replica_evidence"):
            for record in report["replica_evidence"].values():
                note(reason, record)
        else:
            note(reason)
    for uid in report.get("replica_evidence", {}):
        for resource in ["cpu", "memory"]:
            if not any(point.get("replica") == uid and resource in point for point in metrics["samples"]):
                reasons.add(f"Historical {resource} observations unavailable for replica {uid}")
    reasons.add(
        "Historical metadata and usage gaps remain possible; discovery does not prove complete window coverage"
    )
    report["reasons"] = sorted(reasons)
    metrics.setdefault("attribution_gaps", []).extend(sorted(global_gaps))
    metrics.setdefault("attribution_gap_details", []).extend(gap_details)
    metrics["warnings"].extend(report["reasons"])
    return metrics
