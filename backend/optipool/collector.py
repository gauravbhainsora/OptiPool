"""Read-only REST adapters. No Kubernetes or Google Cloud mutation methods."""

import base64
import datetime as dt
import os
import tempfile
import time
from copy import deepcopy

import google.auth
from google.auth.transport.requests import AuthorizedSession

from .resources import node_eligible, pod_resources, quantity


def timestamp(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


class CloudCollector:
    def __init__(self, settings):
        self.settings = settings
        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        self.http = AuthorizedSession(credentials)

    def get(self, url, params=None, verify=True):
        r = self.http.get(url, params=params, timeout=(10, 60), verify=verify)
        r.raise_for_status()
        return r.json()

    def pages(self, url, field, params=None, verify=True, kubernetes=False):
        params = dict(params or {})
        result = []
        while True:
            page = self.get(url, params, verify)
            result.extend(page.get(field, []))
            token = page.get("metadata", {}).get("continue") if kubernetes else page.get("nextPageToken")
            if not token:
                return result
            params["continue" if kubernetes else "pageToken"] = token

    def discover(self):
        projects = self.pages("https://cloudresourcemanager.googleapis.com/v3/projects:search", "projects")
        projects = [
            p["projectId"]
            for p in projects
            if p.get("state") == "ACTIVE"
            and (not self.settings.project_allowlist or p["projectId"] in self.settings.project_allowlist)
        ]
        pools, successful, errors = [], [], []
        for project in projects:
            try:
                data = self.get(
                    f"https://container.googleapis.com/v1/projects/{project}/locations/-/clusters"
                )
                if data.get("missingZones"):
                    raise ValueError("GKE returned incomplete cluster discovery")
                found = []
                for c in data.get("clusters", []):
                    if c.get("autopilot", {}).get("enabled"):
                        errors.append(
                            {"scope": f"{project}/{c['name']}", "error": "Autopilot outside current scope"}
                        )
                        continue
                    for n in c.get("nodePools", []):
                        found.append(self.pool(project, c, n))
                pools.extend(found)
                successful.append(project)
            except Exception as exc:
                errors.append({"scope": project, "error": str(exc)[:500]})
        return pools, successful, errors

    def pool(self, project, cluster, pool):
        cfg, autoscaling = pool.get("config", {}), pool.get("autoscaling", {})
        locations = pool.get("locations") or cluster.get("locations") or [cluster["location"]]
        maximum = autoscaling.get("totalMaxNodeCount")
        minimum = autoscaling.get("totalMinNodeCount")
        if maximum is None:
            maximum = autoscaling.get("maxNodeCount", pool.get("initialNodeCount", 0)) * len(locations)
        if minimum is None:
            minimum = autoscaling.get("minNodeCount", 0) * len(locations)
        return {
            "id": f"{project}/{cluster['location']}/{cluster['name']}/{pool['name']}",
            "project": project,
            "cluster": cluster["name"],
            "location": cluster["location"],
            "name": pool["name"],
            "environment": self.settings.pool_environment(project, cluster["name"], pool["name"]),
            "machine_type": cfg.get("machineType", "unknown"),
            "locations": locations,
            "autoscaling": autoscaling.get("enabled", False),
            "autoscaler_min": minimum,
            "autoscaler_max": maximum,
            "provisioning_model": "SPOT" if cfg.get("spot") or cfg.get("preemptible") else "STANDARD",
            "disk_type": cfg.get("diskType", "pd-standard"),
            "disk_gb": cfg.get("diskSizeGb", 100),
            "raw_config": cfg,
            "synthetic": False,
        }

    def collect(self, pool):
        project, location, cluster_name = pool["project"], pool["location"], pool["cluster"]
        cluster = self.get(
            f"https://container.googleapis.com/v1/projects/{project}/locations/{location}/clusters/{cluster_name}"
        )
        selected = next(n for n in cluster["nodePools"] if n["name"] == pool["name"])
        pool = self.pool(project, cluster, selected)
        if pool["environment"] == "production" and not self.settings.live_validation_complete:
            raise ValueError(
                "Production collection gated: validate a nonproduction pool and set live_validation_complete"
            )
        fd, ca_path = tempfile.mkstemp(prefix="optipool-ca-")
        try:
            with os.fdopen(fd, "wb") as cert:
                cert.write(base64.b64decode(cluster["masterAuth"]["clusterCaCertificate"]))
            endpoint = cluster.get("endpoint")
            if not endpoint:
                raise ValueError(
                    "No reachable IP endpoint; DNS endpoint clusters need explicit adapter support"
                )
            base = f"https://{endpoint}"
            paths = {
                "nodes": "/api/v1/nodes",
                "pods": "/api/v1/pods",
                "services": "/api/v1/services",
                "namespaces": "/api/v1/namespaces",
                "quotas": "/api/v1/resourcequotas",
                "limit_ranges": "/api/v1/limitranges",
                "pv": "/api/v1/persistentvolumes",
                "pvc": "/api/v1/persistentvolumeclaims",
                "storage_classes": "/apis/storage.k8s.io/v1/storageclasses",
                "deployments": "/apis/apps/v1/deployments",
                "replicasets": "/apis/apps/v1/replicasets",
                "statefulsets": "/apis/apps/v1/statefulsets",
                "daemonsets": "/apis/apps/v1/daemonsets",
                "jobs": "/apis/batch/v1/jobs",
                "cronjobs": "/apis/batch/v1/cronjobs",
            }
            raw = {
                key: self.pages(base + path, "items", {"limit": 500}, ca_path, True)
                for key, path in paths.items()
            }
            uncertainties = []
            try:
                hooks = self.pages(
                    base + "/apis/admissionregistration.k8s.io/v1/mutatingwebhookconfigurations",
                    "items",
                    {"limit": 500},
                    ca_path,
                    True,
                )
                if hooks:
                    uncertainties.append(
                        "Mutating admission webhooks may change proposed Pods; inspect dry-run externally"
                    )
            except Exception:
                uncertainties.append("Mutating admission configuration could not be inspected")
        finally:
            os.unlink(ca_path)
        snapshot = normalize(pool, raw, uncertainties)
        snapshot["metrics"] = self.metrics(pool, snapshot)
        try:
            snapshot["pricing"] = self.prices(pool)
        except Exception as exc:
            snapshot["pricing"] = {
                "source": "Unavailable",
                "saved_at": time.time(),
                "components": [],
                "error": str(exc)[:500],
            }
        return snapshot

    def metrics(self, pool, snapshot):
        now, samples = int(time.time()), []
        result = {
            "cutoff": now,
            "samples": samples,
            "source": "Unavailable",
            "coverage": "unavailable",
            "memory_definition": "Unavailable",
            "warnings": [],
        }
        match = f'project_id="{pool["project"]}",location="{pool["location"]}",cluster="{pool["cluster"]}",container!="",container!="POD"'
        endpoint = f"https://monitoring.googleapis.com/v1/projects/{pool['project']}/location/global/prometheus/api/v1/query_range"
        try:
            queries = {
                "cpu": f"sum by(namespace,pod)(rate(container_cpu_usage_seconds_total{{{match}}}[5m]))",
                "memory": f"sum by(namespace,pod)(container_memory_working_set_bytes{{{match}}})",
            }
            series = {
                k: self.get(endpoint, {"query": q, "start": now - 10 * 86400, "end": now, "step": 300})
                for k, q in queries.items()
            }
            if all(s.get("status") == "success" and s.get("data", {}).get("result") for s in series.values()):
                result.update(source="GMP cAdvisor", memory_definition="Working set", cadence_seconds=300)
                values = {}
                pods = {
                    (p["namespace"], p["name"]): p
                    for p in snapshot["context"]["pods"]
                    if p.get("workload") and p["node"] in {n["name"] for n in snapshot["nodes"]}
                }
                for resource, response in series.items():
                    for s in response["data"]["result"]:
                        pod = pods.get((s["metric"].get("namespace"), s["metric"].get("pod")))
                        if not pod:
                            continue
                        for t, v in s.get("values", []):
                            if t < pod["created"] + (300 if resource == "cpu" else 0):
                                continue
                            item = values.setdefault(
                                (pod["uid"], t),
                                {
                                    "time": t,
                                    "replica": pod["uid"],
                                    "workload": pod["workload"],
                                    "attributed": True,
                                },
                            )
                            item[resource] = float(v) if v not in {"NaN", "+Inf", "-Inf"} else None
                samples.extend(values.values())
            else:
                self.native_metrics(pool, snapshot, result)
        except Exception as exc:
            result["warnings"].append("GMP unavailable: " + str(exc)[:200])
            try:
                self.native_metrics(pool, snapshot, result)
            except Exception as fallback:
                result["warnings"].append("Native metrics unavailable: " + str(fallback)[:200])
        if samples:
            result["coverage"] = "partial — surviving Pods within their observed current lifetime only"
            result["warnings"].append(
                "Deleted replicas and earlier ownership/pool history are not reconstructed; highest p99 may be understated"
            )
        return result

    def native_metrics(self, pool, snapshot, result):
        now = result["cutoff"]

        def iso(t):
            return dt.datetime.fromtimestamp(t, dt.UTC).isoformat()

        endpoint = f"https://monitoring.googleapis.com/v3/projects/{pool['project']}/timeSeries"
        pods = {
            (p["namespace"], p["name"]): p
            for p in snapshot["context"]["pods"]
            if p.get("workload") and p["node"] in {n["name"] for n in snapshot["nodes"]}
        }
        values = {}
        for resource, metric, aligner in [
            ("cpu", "cpu/core_usage_time", "ALIGN_RATE"),
            ("memory", "memory/used_bytes", "ALIGN_MEAN"),
        ]:
            filter_text = (
                f'metric.type="kubernetes.io/container/{metric}" AND '
                f'resource.labels.cluster_name="{pool["cluster"]}" AND '
                f'resource.labels.location="{pool["location"]}"'
            )
            if resource == "memory":
                filter_text += ' AND metric.labels.memory_type="non-evictable"'
            series = self.pages(
                endpoint,
                "timeSeries",
                {
                    "filter": filter_text,
                    "interval.startTime": iso(now - 10 * 86400),
                    "interval.endTime": iso(now),
                    "aggregation.alignmentPeriod": "300s",
                    "aggregation.perSeriesAligner": aligner,
                },
            )
            for s in series:
                labels = s["resource"]["labels"]
                pod = pods.get((labels.get("namespace_name"), labels.get("pod_name")))
                if not pod:
                    continue
                for p in s.get("points", []):
                    t = timestamp(p["interval"]["endTime"])
                    if t < pod["created"]:
                        continue
                    item = values.setdefault(
                        (pod["uid"], t),
                        {"time": t, "replica": pod["uid"], "workload": pod["workload"], "attributed": True},
                    )
                    value = p["value"].get("doubleValue", p["value"].get("int64Value"))
                    if value is not None:
                        item[resource] = item.get(resource, 0) + float(value)
        if values:
            result["samples"].extend(values.values())
            result.update(
                source="Native GKE Cloud Monitoring",
                memory_definition="Non-evictable memory",
                cadence_seconds=300,
            )

    def prices(self, pool):
        # Exact operator-reviewed mappings avoid ambiguous SKU description/discount guesses.
        key = f"{pool['location']}/{pool['machine_type']}/{pool['provisioning_model']}/{pool['disk_type']}/{pool['disk_gb']}"
        mapping = self.settings.pricing_mappings.get(key)
        result = {"source": "Google Cloud Billing public catalog", "saved_at": time.time(), "components": []}
        if not mapping:
            result["error"] = f"No exact public SKU mapping configured for {key}"
            return result
        catalog = self.pages(
            "https://cloudbilling.googleapis.com/v1/services/6F81-5844-456A/skus",
            "skus",
            {"currencyCode": "USD"},
        )
        by_id = {s["skuId"]: s for s in catalog}

        def rate(sku_id, expected_unit):
            sku = by_id[sku_id]
            if pool["location"] not in sku.get("serviceRegions", []):
                raise ValueError("SKU region does not match selected pool")
            info = sorted(sku["pricingInfo"], key=lambda p: p["effectiveTime"])[-1]
            expr = info["pricingExpression"]
            if expr["usageUnit"] != expected_unit or len(expr["tieredRates"]) != 1:
                raise ValueError("Price mapping unit or tier is unsupported")
            unit = expr["tieredRates"][0]["unitPrice"]
            if unit["currencyCode"] != "USD":
                raise ValueError("Expected USD")
            return float(unit.get("units", 0)) + float(unit.get("nanos", 0)) / 1e9

        for component in mapping["components"]:
            if component.get("cud_eligible") and (
                pool["provisioning_model"] != "STANDARD" or component.get("cud_model") != "resource-3y"
            ):
                raise ValueError("CUD mapping must be eligible standard provisioning and resource-3y")
            amount = component["quantity"]
            hourly_factor = component.get("hourly_factor", 1)
            result["components"].append(
                {
                    **component,
                    "on_demand_hourly": rate(component["on_demand_sku"], component["unit"])
                    * amount
                    * hourly_factor,
                    "cud_3y_hourly": rate(component["cud_3y_sku"], component["unit"]) * amount * hourly_factor
                    if component.get("cud_eligible")
                    else None,
                }
            )
        return result


def normalize(pool, raw, uncertainties):
    by_uid = {
        o["metadata"]["uid"]: o
        for key in ["deployments", "replicasets", "statefulsets", "daemonsets", "jobs", "cronjobs"]
        for o in raw.get(key, [])
    }

    def owner(p):
        obj = p
        seen = set()
        while True:
            refs = [r for r in obj["metadata"].get("ownerReferences", []) if r.get("controller")]
            if not refs:
                return obj
            ref = refs[0]
            if ref["uid"] in seen or ref["uid"] not in by_uid:
                return {
                    "kind": ref["kind"],
                    "metadata": {"name": ref["name"], "namespace": p["metadata"]["namespace"]},
                }
            seen.add(ref["uid"])
            obj = by_uid[ref["uid"]]

    all_nodes = []
    for n in raw["nodes"]:
        labels = n["metadata"].get("labels", {})
        all_nodes.append(
            {
                "name": n["metadata"]["name"],
                "labels": labels,
                "zone": labels.get("topology.kubernetes.io/zone", "unknown"),
                "ready": any(
                    c["type"] == "Ready" and c["status"] == "True" for c in n["status"].get("conditions", [])
                ),
                "unschedulable": n["spec"].get("unschedulable", False),
                "taints": n["spec"].get("taints", []),
                "allocatable": {
                    k: quantity(n["status"]["allocatable"].get(k, 0)) for k in ["cpu", "memory", "pods"]
                },
                "requested": {"cpu": 0.0, "memory": 0.0},
                "limits": {"cpu": 0.0, "memory": 0.0},
                "pod_count": 0,
            }
        )
    selected = [n for n in all_nodes if n["labels"].get("cloud.google.com/gke-nodepool") == pool["name"]]
    index = {n["name"]: n for n in all_nodes}
    pods, pending, workloads = [], [], {}
    for p in raw["pods"]:
        if p["status"].get("phase") in {"Succeeded", "Failed"}:
            continue
        o = owner(p)
        meta, spec = p["metadata"], p["spec"]
        key = f"{meta['namespace']}/{o['kind']}/{o['metadata']['name']}"
        node = index.get(spec.get("nodeName"))
        item = {
            "name": meta["name"],
            "namespace": meta["namespace"],
            "node": spec.get("nodeName"),
            "uid": meta["uid"],
            "created": timestamp(meta["creationTimestamp"]),
            "workload": key,
            "labels": meta.get("labels", {}),
            "spec": spec,
            "phase": p["status"].get("phase", "Unknown"),
            "restarts": sum(
                c.get("restartCount", 0)
                for c in p["status"].get("containerStatuses", [])
                + p["status"].get("initContainerStatuses", [])
            ),
            "ready": any(
                c["type"] == "Ready" and c["status"] == "True" for c in p["status"].get("conditions", [])
            ),
        }
        pods.append(item)
        if node:
            node["pod_count"] += 1
            for field in ["requested", "limits"]:
                req = pod_resources(spec, "requests" if field == "requested" else "limits")
                for k in req:
                    node[field][k] += req[k]
        if not node and any(node_eligible(n, spec) for n in selected):
            if any(node_eligible(n, spec) for n in all_nodes if n not in selected):
                uncertainties.append(
                    f"Pending {meta['namespace']}/{meta['name']} can compete across multiple pools"
                )
            else:
                pending.append(item)
        w = workloads.setdefault(
            key,
            {
                "id": key,
                "kind": o["kind"],
                "name": o["metadata"]["name"],
                "namespace": meta["namespace"],
                "desired": o.get("spec", {}).get("replicas", 0),
                "running": 0,
                "pending": 0,
                "pool_replicas": 0,
                "services": [],
                "per_replica": pod_resources(spec),
                "requested": {"cpu": 0.0, "memory": 0.0},
                "limits": {"cpu": 0.0, "memory": 0.0},
                "spec": spec,
            },
        )
        w["running"] += int(item["phase"] == "Running")
        w["pending"] += int(item["phase"] == "Pending")
        if node in selected:
            w["pool_replicas"] += 1
            for k in ["cpu", "memory"]:
                w["requested"][k] += pod_resources(spec)[k]
                w["limits"][k] += pod_resources(spec, "limits")[k]
            for service in raw["services"]:
                sm = service["metadata"]
                selector = service["spec"].get("selector", {})
                if (
                    sm["namespace"] == meta["namespace"]
                    and selector
                    and all(meta.get("labels", {}).get(k) == v for k, v in selector.items())
                ):
                    if sm["name"] not in w["services"]:
                        w["services"].append(sm["name"])
    # Include desired replicas not yet materialized as Pods, without double counting Pending Pods.
    for deployment in raw["deployments"] + raw["statefulsets"]:
        meta, ds = deployment["metadata"], deployment["spec"]
        key = f"{meta['namespace']}/{deployment['kind']}/{meta['name']}"
        template = ds["template"]
        spec = template["spec"]
        existing = sum(p["workload"] == key for p in pods)
        missing = max(0, ds.get("replicas", 1) - existing)
        if missing and any(node_eligible(n, spec) for n in selected):
            if any(node_eligible(n, spec) for n in all_nodes if n not in selected):
                uncertainties.append(
                    f"Unmaterialized desired replicas for {key} can compete across multiple pools"
                )
            else:
                pending.extend(
                    {
                        "name": f"{meta['name']}-desired-{i}",
                        "namespace": meta["namespace"],
                        "labels": template.get("metadata", {}).get("labels", {}),
                        "spec": spec,
                    }
                    for i in range(missing)
                )
                if key not in workloads:
                    workloads[key] = {
                        "id": key,
                        "kind": deployment["kind"],
                        "name": meta["name"],
                        "namespace": meta["namespace"],
                        "desired": ds.get("replicas", 1),
                        "running": 0,
                        "pending": 0,
                        "pool_replicas": 0,
                        "services": [],
                        "per_replica": pod_resources(spec),
                        "requested": {"cpu": 0, "memory": 0},
                        "limits": {"cpu": 0, "memory": 0},
                        "spec": spec,
                    }
    templates = []
    for zone in pool["locations"]:
        observed = [n for n in selected if n["zone"] == zone] or selected
        if not observed:
            continue
        n = deepcopy(observed[0])
        n["zone"] = zone
        n["labels"]["topology.kubernetes.io/zone"] = zone
        n.update(ready=True, unschedulable=False)
        # Preserve only labels configured on new nodes or well-known system labels.
        allowed = {
            "cloud.google.com/gke-nodepool",
            "topology.kubernetes.io/zone",
            "topology.kubernetes.io/region",
            "kubernetes.io/os",
            "kubernetes.io/arch",
            "node.kubernetes.io/instance-type",
            "kubernetes.io/hostname",
        }
        n["labels"] = {
            k: v for k, v in n["labels"].items() if k in allowed or k in pool["raw_config"].get("labels", {})
        }
        n["allocatable"] = {k: min(x["allocatable"][k] for x in observed) for k in ["cpu", "memory", "pods"]}
        overhead, count = {"cpu": 0.0, "memory": 0.0}, 0
        for daemon in raw["daemonsets"]:
            spec = daemon["spec"]["template"]["spec"]
            if node_eligible(n, spec):
                for k, v in pod_resources(spec).items():
                    overhead[k] += v
                count += 1
        # Capture non-controller system/static Pods too, conservatively across sampled nodes.
        static = [
            p
            for p in pods
            if p["node"] in {x["name"] for x in observed} and (p["workload"].split("/")[1] == "Pod")
        ]
        for k in overhead:
            overhead[k] += max(
                (
                    sum(pod_resources(p["spec"])[k] for p in static if p["node"] == x["name"])
                    for x in observed
                ),
                default=0,
            )
        n.update(
            requested=overhead,
            pod_count=count + max((sum(p["node"] == x["name"] for p in static) for x in observed), default=0),
        )
        templates.append(n)
    return {
        "pool": pool,
        "core_complete": True,
        "collected_at": time.time(),
        "nodes": selected,
        "node_templates": templates,
        "workloads": [
            w
            for w in workloads.values()
            if w["pool_replicas"]
            or any(p["namespace"] == w["namespace"] and p["name"].startswith(w["name"]) for p in pending)
        ],
        "context": {
            "pods": pods,
            "nodes": all_nodes,
            "pending": pending,
            "uncertainties": sorted(set(uncertainties)),
            "quotas": raw["quotas"],
            "namespaces": [n["metadata"]["name"] for n in raw.get("namespaces", [])],
            "namespace_context_complete": "namespaces" in raw,
            "limit_ranges": raw["limit_ranges"],
            "storage": {k: raw[k] for k in ["pv", "pvc", "storage_classes"]},
        },
    }
