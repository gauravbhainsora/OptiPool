"""Combine saved pool observations; retain independent capture times and pool identity."""

import json

from .exports import evidence_columns, iso, metric_provenance


def combine(project, location, cluster, views, missing):
    sources, nodes, pods, workloads = [], [], [], {}
    for value in views:
        pool, usage = value["pool"], value["usage"]
        source = {
            "pool_id": pool["id"],
            "pool_name": pool["name"],
            "snapshot_id": value["id"],
            "saved_at": value["saved_at"],
            "cutoff": usage["cutoff"],
            "source": usage["source"],
            "memory_definition": usage["memory_definition"],
            "coverage": usage["coverage"],
            "cadence_seconds": usage.get("cadence_seconds"),
            "reduction_policy": usage.get("reduction_policy"),
            "synthetic": pool.get("synthetic", False),
            **{
                key: usage.get(key)
                for key in [
                    "query_definition",
                    "units",
                    "cadence_seconds",
                    "cpu_rate_window_seconds",
                    "cpu_alignment_window_seconds",
                    "resource_status",
                    "fallback_reason",
                ]
            },
        }
        sources.append(source)
        for node in value["nodes"]:
            nodes.append({**node, **source, "environment": pool["environment"]})
        for pod in value["pods"]:
            pods.append({**pod, **source, "usage": usage["pods"].get(pod["uid"])})
        for workload in value["workloads"]:
            metric = usage["workloads"].get(workload["id"], {}) if workload["kind"] == "Deployment" else {}
            target = workloads.setdefault(
                workload["id"],
                {
                    "id": workload["id"],
                    "name": workload["name"],
                    "namespace": workload["namespace"],
                    "kind": workload["kind"],
                    "pool_replicas": 0,
                    "historical_replicas_observed": 0,
                    "historical_replica_uids": set(),
                    "requested": {"cpu": 0, "memory": 0},
                    "limits": {"cpu": 0, "memory": 0},
                    "services": set(),
                    "pools": [],
                    "cpu_p99": None,
                    "memory_p99": None,
                    "memory_peak": None,
                    "memory_peak_replica": None,
                    "memory_peak_pool": None,
                    "cpu_complete": True,
                    "memory_complete": True,
                    "memory_definitions": set(),
                    "cpu_replica": None,
                    "memory_replica": None,
                    "cpu_pool": None,
                    "memory_pool": None,
                    "cpu_evidence": None,
                    "memory_evidence": None,
                },
            )
            target["pool_replicas"] += workload["pool_replicas"]
            target["historical_replica_uids"].update(metric.get("historical_replica_uids", []))
            target["services"].update(workload["services"])
            for resource in ["cpu", "memory"]:
                target["requested"][resource] += workload["requested"][resource]
                target["limits"][resource] += workload["limits"][resource]
                p99 = metric.get(resource + "_p99")
                target[resource + "_complete"] &= p99 is not None and not (
                    metric.get(resource + "_evidence") or {}
                ).get("partial", False)
                if p99 is not None and (target[resource + "_p99"] is None or p99 > target[resource + "_p99"]):
                    target[resource + "_p99"] = p99
                    target[resource + "_replica"] = metric.get(resource + "_replica")
                    target[resource + "_pool"] = pool["name"]
                    target[resource + "_evidence"] = {
                        **(metric.get(resource + "_evidence") or {}),
                        "pool_id": pool["id"],
                        "pool_name": pool["name"],
                        "snapshot_id": value["id"],
                        "cutoff": usage["cutoff"],
                    }
            peak = metric.get("memory_peak")
            if peak is not None and (target["memory_peak"] is None or peak > target["memory_peak"]):
                target["memory_peak"] = peak
                target["memory_peak_replica"] = metric.get("memory_peak_replica")
                target["memory_peak_pool"] = pool["name"]
            if metric.get("memory_p99") is not None or peak is not None:
                target["memory_definitions"].add(usage["memory_definition"])
            target["pools"].append(
                {
                    **source,
                    "replicas": workload["pool_replicas"],
                    "cpu_evidence": metric.get("cpu_evidence"),
                    "memory_evidence": metric.get("memory_evidence"),
                }
            )
    for target in workloads.values():
        target["services"] = sorted(target["services"])
        target["historical_replica_uids"] = sorted(target["historical_replica_uids"])
        target["historical_replicas_observed"] = len(target["historical_replica_uids"])
        target["memory_definitions"] = sorted(target["memory_definitions"])
        if len(target["memory_definitions"]) > 1:
            target["memory_peak"] = None
            target["memory_peak_replica"] = None
            target["memory_peak_pool"] = None
            target["memory_p99"] = None
            target["memory_replica"] = None
            target["memory_pool"] = None
            target["memory_complete"] = False
            target["memory_evidence"] = None
    return {
        "project": project,
        "location": location,
        "cluster": cluster,
        "days": views[0]["usage"]["days"] if views else None,
        "sources": sources,
        "missing": missing,
        "nodes": nodes,
        "pods": pods,
        "workloads": list(workloads.values()),
    }


def workload_rows(scope):
    return [
        {
            "Project": scope["project"],
            "Cluster": scope["cluster"],
            "Location": scope["location"],
            "Namespace": w["namespace"],
            "Kind": w["kind"],
            "Workload": w["name"],
            "Node pools": ", ".join(p["pool_name"] for p in w["pools"]),
            "Replicas across selected pools": w["pool_replicas"],
            "Historical replicas observed across pool observations": w["historical_replicas_observed"],
            "Historical replica UIDs": ", ".join(w["historical_replica_uids"]),
            "CPU requests across pools": w["requested"]["cpu"],
            "Memory requests across pools GiB": w["requested"]["memory"] / 1024**3,
            "Highest replica p99 CPU cores": w["cpu_p99"],
            "Highest replica p99 memory GiB": w["memory_p99"] / 1024**3
            if w["memory_p99"] is not None
            else None,
            "Sampled memory peak GiB": w["memory_peak"] / 1024**3 if w["memory_peak"] is not None else None,
            "Sampled memory peak replica": w["memory_peak_replica"],
            "Sampled memory peak pool": w["memory_peak_pool"],
            "CPU coverage complete": w["cpu_complete"],
            "Memory coverage complete": w["memory_complete"],
            "Window days per pool": scope["days"],
            "Snapshot IDs": ", ".join(p["snapshot_id"] for p in w["pools"]),
            "Snapshot UTC per pool": "; ".join(f"{p['pool_name']}: {iso(p['saved_at'])}" for p in w["pools"]),
            "Metrics cutoff UTC per pool": "; ".join(
                f"{p['pool_name']}: {iso(p['cutoff'])}" for p in w["pools"]
            ),
            "Metric sources": ", ".join(sorted({p["source"] for p in w["pools"]})),
            "Memory definitions": ", ".join(w["memory_definitions"]),
            "Metric evidence per pool": json.dumps(
                {p["pool_name"]: metric_provenance(p) for p in w["pools"]}, sort_keys=True
            ),
            "CPU p99 pool": w["cpu_pool"],
            "CPU p99 replica": w["cpu_replica"],
            "Memory p99 pool": w["memory_pool"],
            "Memory p99 replica": w["memory_replica"],
            "Synthetic": any(p["synthetic"] for p in w["pools"]),
            **evidence_columns(w),
            "Evidence per pool": json.dumps(w["pools"], separators=(",", ":")),
        }
        for w in scope["workloads"]
    ]
