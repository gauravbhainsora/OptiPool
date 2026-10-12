"""Read-only new-pool designs grounded in saved observed node profiles."""

from copy import deepcopy
from typing import Literal

from pydantic import Field

from .estimator import ServiceBundle, estimate, proposals_for
from .pricing import cost


class PoolDesign(ServiceBundle):
    project: str = Field(min_length=1, max_length=253)
    location: str = Field(min_length=1, max_length=253)
    cluster: str = Field(min_length=1, max_length=253)
    name: str = Field(min_length=1, max_length=40, pattern=r"^[a-z](?:[a-z0-9-]*[a-z0-9])?$")
    environment: Literal["production", "nonproduction"] = "production"
    snapshots: dict[str, str] = Field(min_length=1, max_length=10)


def profile(snapshot):
    pool = snapshot["pool"]
    return {
        "pool_id": pool["id"],
        "pool_name": pool["name"],
        "snapshot_id": snapshot["id"],
        "saved_at": snapshot["saved_at"],
        "machine_type": pool.get("machine_type"),
        "provisioning_model": pool.get("provisioning_model"),
        "disk_type": pool.get("disk_type"),
        "disk_gb": pool.get("disk_gb"),
        "synthetic": pool.get("synthetic", False),
        "templates": [
            {k: t.get(k) for k in ["zone", "allocatable", "requested", "pod_count", "labels", "taints"]}
            for t in snapshot.get("node_templates", [])
        ],
        "node_cost": cost(snapshot.get("pricing"), 1),
    }


def design(snapshots, scenario: PoolDesign, max_added=100, max_replicas=2000):
    proposals_for(scenario, max_replicas)  # Validate the whole bundle before candidate calculations.
    candidates = []
    for original in snapshots:
        value = deepcopy(original)
        value["nodes"] = []
        value["pool"] = {
            **value["pool"],
            "name": scenario.name,
            "id": f"{scenario.project}/{scenario.location}/{scenario.cluster}/{scenario.name}",
            "environment": scenario.environment,
            "autoscaling": True,
            "autoscaler_max": max_added,
        }
        value["context"]["pending"] = []
        for template in value.get("node_templates", []):
            template["labels"]["cloud.google.com/gke-nodepool"] = scenario.name
        result = estimate(value, scenario, max_added, max_replicas)
        source = profile(original)
        candidates.append(
            {
                "profile": source,
                "assessment": result,
                "complete": result["outcome"] != "Blocked constraints"
                and result["additional_nodes"] is not None
                and sum(not p["existing_demand"] for p in result["placements"]) == result["replicas"],
                "configuration": {
                    "name": scenario.name,
                    "project": scenario.project,
                    "cluster": scenario.cluster,
                    "location": scenario.location,
                    "environment": scenario.environment,
                    "machine_type": source["machine_type"],
                    "provisioning_model": source["provisioning_model"],
                    "disk_type": source["disk_type"],
                    "disk_gb": source["disk_gb"],
                    "total_nodes": result["additional_nodes"],
                    "node_profiles": [
                        {
                            "zone": t["zone"],
                            "allocatable": t["allocatable"],
                            "baseline_requests": t["requested"],
                            "baseline_pods": t["pod_count"],
                            "labels": t["labels"],
                            "taints": t.get("taints", []),
                        }
                        for t in value.get("node_templates", [])
                    ],
                    "nodes_by_zone": {
                        zone: sum(n["zone"] == zone for n in result.get("node_budgets", []))
                        for zone in sorted({t["zone"] for t in original.get("node_templates", [])})
                    },
                },
            }
        )

    def rank(candidate):
        result = candidate["assessment"]
        complete = candidate["complete"]
        conditional = result["outcome"] == "Cannot fully assess"
        quote = result["cost"].get("on_demand_hourly")
        return (
            not complete,
            conditional,
            quote is None,
            quote if quote is not None else float("inf"),
            result["additional_nodes"] or 0,
            candidate["profile"]["pool_id"],
        )

    candidates.sort(key=rank)
    recommended = next((c["profile"]["pool_id"] for c in candidates if c["complete"]), None)
    return {
        "kind": "node_pool_design",
        "project": scenario.project,
        "location": scenario.location,
        "cluster": scenario.cluster,
        "name": scenario.name,
        "environment": scenario.environment,
        "recommended_profile": recommended,
        "ranking": "Complete modeled placements first, then certainty and lowest available on-demand quote; unquoted profiles may be cheaper",
        "candidates": candidates,
        "assumptions": [
            "Design only: no GKE node pool is created and no cloud data is fetched",
            "Candidates use saved observed profiles; this is not the full GCP machine catalog",
            "Existing cluster Pods stay as scheduling context; existing pool capacity is not reused",
            "Existing pool-bound pending demand is excluded from the new-pool workload bundle",
            "Saved labels, taints, zones, allocatable and system/DaemonSet overhead are assumed; validate new-pool DaemonSet eligibility",
            "Review cluster IP ranges, Compute quotas, regional per-zone provisioning, IAM, network/storage and admission before provisioning",
            "The design reports total nodes and simulated zone counts, not an executable GKE create request",
        ],
    }
