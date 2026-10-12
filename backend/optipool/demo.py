"""Deterministic synthetic inventory, usage and prices. No cloud credentials required."""

import math
import time
from copy import deepcopy


class DemoCollector:
    def __init__(self, settings):
        self.settings = settings

    def discover(self):
        pools = []
        for i, project in enumerate(["atlas-prod", "beacon-prod", "cedar-dev", "delta-staging"]):
            cluster = ["atlas-europe", "beacon-us", "cedar-sandbox", "delta-preview"][i]
            env = "production" if i < 2 else "nonproduction"
            for pool in ["services", "workers"]:
                pools.append(
                    {
                        "id": f"{project}/us-central1/{cluster}/{pool}",
                        "project": project,
                        "cluster": cluster,
                        "location": "us-central1",
                        "name": pool,
                        "environment": env,
                        "machine_type": "n2-standard-4",
                        "locations": ["us-central1-a", "us-central1-b"],
                        "autoscaler_min": 2,
                        "autoscaler_max": 6,
                        "autoscaling": True,
                        "provisioning_model": "STANDARD",
                        "disk_type": "pd-balanced",
                        "disk_gb": 100,
                        "synthetic": True,
                    }
                )
        return pools, list({p["project"] for p in pools}), []

    def collect(self, pool):
        now = int(time.time())
        nodes, pods, workloads, samples = [], [], [], []
        prefix = pool["cluster"].split("-")[0]
        node_count = 3 if pool["name"] == "services" else 2
        for i in range(node_count):
            name = f"gke-{prefix}-{pool['name']}-{i + 1:04d}"
            zone = pool["locations"][i % 2]
            nodes.append(
                {
                    "name": name,
                    "zone": zone,
                    "ready": True,
                    "unschedulable": False,
                    "allocatable": {"cpu": 3.92, "memory": 14.5 * 1024**3, "pods": 110},
                    "requested": {"cpu": 0.22, "memory": 0.45 * 1024**3},
                    "limits": {"cpu": 0.3, "memory": 0.8 * 1024**3},
                    "pod_count": 4,
                    "labels": {
                        "cloud.google.com/gke-nodepool": pool["name"],
                        "topology.kubernetes.io/zone": zone,
                        "kubernetes.io/hostname": name,
                        "kubernetes.io/arch": "amd64",
                    },
                    "taints": [],
                }
            )
        for w, (name, cpu, mem, count) in enumerate(
            [
                ("checkout-api", 0.5, 0.75, 3),
                ("catalog-api", 0.6, 1.2, 3),
                ("payment-worker", 0.8, 1.5, 2),
                ("telemetry", 0.12, 0.3, 2),
            ]
        ):
            key = f"commerce/Deployment/{name}"
            spec = {
                "containers": [
                    {
                        "name": name,
                        "resources": {
                            "requests": {"cpu": str(cpu), "memory": str(int(mem * 1024**3))},
                            "limits": {"cpu": str(cpu * 2), "memory": str(int(mem * 2 * 1024**3))},
                        },
                    }
                ],
                "nodeSelector": {"cloud.google.com/gke-nodepool": pool["name"]},
            }
            workload = {
                "id": key,
                "controller_uid": "synthetic-controller-" + key,
                "namespace": "commerce",
                "kind": "Deployment",
                "name": name,
                "desired": count,
                "running": count,
                "pending": 0,
                "pool_replicas": count,
                "services": [name] if w < 2 else [],
                "per_replica": {"cpu": cpu, "memory": mem * 1024**3},
                "requested": {"cpu": cpu * count, "memory": mem * 1024**3 * count},
                "limits": {"cpu": cpu * 2 * count, "memory": mem * 2 * 1024**3 * count},
                "spec": spec,
            }
            workloads.append(workload)
            for r in range(count):
                node = nodes[(w + r) % node_count]
                pod_name = f"{name}-7cf88-{r + 1}"
                pods.append(
                    {
                        "name": pod_name,
                        "namespace": "commerce",
                        "workload": key,
                        "controller_uid": "synthetic-controller-" + key,
                        "node": node["name"],
                        "labels": {"app": name},
                        "spec": spec,
                        "phase": "Running",
                        "ready": True,
                        "restarts": 0,
                        "conditions": [{"type": "Ready", "status": "True"}],
                        "container_statuses": [
                            {
                                "name": spec["containers"][0]["name"],
                                "ready": True,
                                "restartCount": 0,
                                "state": {"running": {}},
                            }
                        ],
                        "uid": pod_name,
                        "created": 1704067200,  # Stable synthetic UID lifetime (2024-01-01 UTC).
                    }
                )
                for k in ["cpu", "memory"]:
                    node["requested"][k] += workload["per_replica"][k]
                    node["limits"][k] += workload["per_replica"][k] * 2
                node["pod_count"] += 1
                for t in range(now - 10 * 86400, now + 1, 1800):
                    wave = (math.sin(t / 9000 + w + r) + 1) / 2
                    samples.append(
                        {
                            "time": t,
                            "workload": key,
                            "replica": pod_name,
                            "attributed": True,
                            "cpu": cpu * (0.15 + wave * 0.64) * (1 + r * 0.05),
                            "memory": mem * 1024**3 * (0.32 + wave * 0.4) * (1 + (count - r) * 0.025),
                        }
                    )
        templates = []
        for zone in pool["locations"]:
            n = deepcopy(nodes[0])
            n.update(zone=zone, pod_count=4, requested={"cpu": 0.22, "memory": 0.45 * 1024**3})
            n["labels"]["topology.kubernetes.io/zone"] = zone
            templates.append(n)
        return {
            "pool": pool,
            "core_complete": True,
            "collected_at": now,
            "nodes": nodes,
            "node_templates": templates,
            "workloads": workloads,
            "context": {
                "pods": pods,
                "nodes": nodes,
                "pending": [],
                "uncertainties": [],
                "quotas": [],
                "limit_ranges": [],
                "namespaces": ["default", "commerce", "kube-system"],
                "namespace_context_complete": True,
            },
            "metrics": {
                "cadence_seconds": 1800,
                "cpu_rate_window_seconds": 300,
                "replica_evidence": {
                    p["uid"]: {
                        "uid": p["uid"],
                        "name": p["name"],
                        "namespace": p["namespace"],
                        "workload": p["workload"],
                        "controller_uid": p["controller_uid"],
                        "created": p["created"],
                        "observed_at": now,
                        "memberships": [
                            {
                                "pool_id": pool["id"],
                                "node": p["node"],
                                "start": p["created"],
                                "end": now,
                                "provenance": "explicit synthetic placement history",
                            }
                        ],
                    }
                    for p in pods
                },
                "cutoff": now,
                "samples": samples,
                "source": "Synthetic fixtures",
                "memory_definition": "Synthetic working set",
                "coverage": "complete synthetic history",
                "warnings": [],
            },
            "pricing": {
                "saved_at": now,
                "source": "Synthetic fixtures — not GCP prices",
                "synthetic": True,
                "components": [
                    {
                        "name": "Compute CPU",
                        "on_demand_hourly": 0.12,
                        "cud_eligible": True,
                        "cud_3y_hourly": 0.058,
                    },
                    {
                        "name": "Compute memory",
                        "on_demand_hourly": 0.07,
                        "cud_eligible": True,
                        "cud_3y_hourly": 0.034,
                    },
                    {"name": "100 GiB boot disk", "on_demand_hourly": 0.014, "cud_eligible": False},
                ],
            },
        }
