"""Conservative, bounded greedy placement. A found placement is not proof of a minimum."""

import math
import re
import time
from collections import defaultdict
from copy import deepcopy
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from .manifests import mapping, selector
from .manifests import pod_spec as validate_pod_spec
from .pricing import cost
from .resources import node_eligible, pod_resources, quantity, selector_matches
from .topology import spread_ok


class Scenario(BaseModel):
    name: str = Field(default="new-service", min_length=1, max_length=100)
    namespace: str = Field(default="default", min_length=1, max_length=253)
    cpu: str = "250m"
    memory: str = "256Mi"
    replicas: int = Field(default=3, ge=0, le=2000)
    manifest: str = Field(default="", max_length=200_000)
    planning_mode: Literal["steady", "hpa", "rollout", "combined"] = "steady"
    hpa_max_replicas: int | None = Field(default=None, ge=0, le=2000)
    max_surge: str = Field(default="25%", max_length=10)
    spread_zones: bool = False

    def planning(self, replicas):
        peak = replicas
        if self.planning_mode in {"hpa", "combined"}:
            if self.hpa_max_replicas is None or self.hpa_max_replicas < replicas:
                raise ValueError("HPA maximum must be at least the requested replica count")
            peak = self.hpa_max_replicas
        surge = 0
        if self.planning_mode in {"rollout", "combined"}:
            if not re.fullmatch(r"\d+%?", self.max_surge):
                raise ValueError("Max surge must be a nonnegative integer or percentage")
            surge = (
                math.ceil(peak * int(self.max_surge[:-1]) / 100)
                if self.max_surge.endswith("%")
                else int(self.max_surge)
            )
        return {
            "mode": self.planning_mode,
            "steady_replicas": replicas,
            "hpa_replicas": peak,
            "surge_replicas": surge,
            "peak_replicas": peak + surge,
        }

    def pod(self):
        if not self.manifest.strip():
            req = {"cpu": self.cpu, "memory": self.memory}
            quantity(self.cpu)
            quantity(self.memory)
            return (
                {"containers": [{"name": self.name, "resources": {"requests": req}}]},
                {"app": self.name},
                self.replicas,
            )
        try:
            obj = yaml.safe_load(self.manifest)
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid Deployment YAML: {exc}") from None
        if not isinstance(obj, dict) or obj.get("kind") != "Deployment" or obj.get("apiVersion") != "apps/v1":
            raise ValueError("Advanced input must be one apps/v1 Deployment")
        spec = mapping(obj.get("spec"), "spec")
        template = mapping(spec.get("template"), "spec.template")
        pod = validate_pod_spec(template.get("spec"))
        metadata = mapping(template.get("metadata"), "spec.template.metadata", optional=True)
        labels = mapping(metadata.get("labels"), "template labels", optional=True)
        if not spec.get("selector") or not selector_matches(
            labels, selector(spec["selector"], "spec.selector")
        ):
            raise ValueError("Deployment requires a selector matching its template labels")
        replicas = int(spec.get("replicas", self.replicas))
        if replicas < 0 or replicas > 2000:
            raise ValueError("replicas must be between 0 and 2000")
        if (
            mapping(obj.get("metadata"), "metadata", optional=True).get("namespace", self.namespace)
            != self.namespace
        ):
            raise ValueError("Manifest namespace must match target namespace")
        return pod, labels, replicas


class ServiceBundle(BaseModel):
    services: list[Scenario] = Field(min_length=1, max_length=20)


def proposals_for(scenario, max_replicas):
    services = scenario.services if isinstance(scenario, ServiceBundle) else [scenario]
    proposals, identities = [], set()
    for service in services:
        key = f"{service.namespace}/{service.name}"
        if key in identities:
            raise ValueError("Service names must be unique within a namespace")
        identities.add(key)
        spec, labels, replicas = service.pod()
        planning = service.planning(replicas)
        if service.spread_zones:
            spec.setdefault("topologySpreadConstraints", []).append(
                {
                    "maxSkew": 1,
                    "topologyKey": "topology.kubernetes.io/zone",
                    "whenUnsatisfiable": "DoNotSchedule",
                    "labelSelector": {"matchLabels": labels},
                }
            )
        proposals.append(
            {
                "key": key,
                "name": service.name,
                "namespace": service.namespace,
                "spec": spec,
                "labels": labels,
                "planning": planning,
                "replicas": planning["peak_replicas"],
                "per_replica": pod_resources(spec),
            }
        )
    if sum(p["replicas"] for p in proposals) > max_replicas:
        raise ValueError("Peak replicas across services exceed the configured simulation bound")
    return proposals


def unsupported(spec):
    reasons = []
    if spec.get("schedulerName", "default-scheduler") != "default-scheduler":
        reasons.append("Custom scheduler cannot be reproduced")
    for key, label in [
        ("runtimeClassName", "RuntimeClass admission overhead"),
        ("resourceClaims", "Dynamic resource allocation"),
    ]:
        if spec.get(key):
            reasons.append(label + " requires validation outside this simulator")
    for term in spec.get("topologySpreadConstraints") or []:
        if (
            term.get("matchLabelKeys")
            or term.get("nodeAffinityPolicy", "Honor") not in {"Honor", "Ignore"}
            or term.get("nodeTaintsPolicy", "Ignore") not in {"Honor", "Ignore"}
        ):
            reasons.append(
                "Dynamic topology spread label keys or unknown inclusion policies need external validation"
            )
    if any("persistentVolumeClaim" in v or "ephemeral" in v or "csi" in v for v in spec.get("volumes", [])):
        reasons.append("Storage binding, attachment and topology require external validation")
    if any(c.get("ports") and any(p.get("hostPort") for p in c["ports"]) for c in spec.get("containers", [])):
        reasons.append("Host-port conflicts are not simulated")
    for container in spec.get("containers", []) + spec.get("initContainers", []):
        for field in ["requests", "limits"]:
            if any(k not in {"cpu", "memory"} for k in container.get("resources", {}).get(field, {})):
                reasons.append("Extended or ephemeral-storage resources are not simulated")
    for affinity in ["podAffinity", "podAntiAffinity"]:
        for term in (
            spec.get("affinity", {})
            .get(affinity, {})
            .get("requiredDuringSchedulingIgnoredDuringExecution", [])
        ):
            if (
                term.get("namespaceSelector") is not None
                or term.get("matchLabelKeys")
                or term.get("mismatchLabelKeys")
            ):
                reasons.append("Namespace selectors and dynamic affinity label keys are not simulated")
    return reasons


def affinity_ok(node, spec, labels, namespace, pods, nodes):
    mapping = {n["name"]: n for n in nodes}

    def matches(term, other):
        namespaces = term.get("namespaces") or [namespace]
        return other["namespace"] in namespaces and selector_matches(
            other.get("labels", {}), term.get("labelSelector", {})
        )

    def same_domain(term, other):
        key = term["topologyKey"]
        other_node = mapping.get(other.get("node"))
        return (
            other_node and key in node["labels"] and node["labels"].get(key) == other_node["labels"].get(key)
        )

    for kind in ["podAffinity", "podAntiAffinity"]:
        terms = (
            spec.get("affinity", {}).get(kind, {}).get("requiredDuringSchedulingIgnoredDuringExecution", [])
        )
        for term in terms:
            if term["topologyKey"] not in node["labels"]:
                return False
            selected = [p for p in pods if matches(term, p)]
            local = any(same_domain(term, p) for p in selected)
            if kind == "podAntiAffinity" and local:
                return False
            if kind == "podAffinity" and not local:
                # Self-affinity bootstrap: first replica can create the group if no matches exist.
                if (
                    selected
                    or namespace not in (term.get("namespaces") or [namespace])
                    or not selector_matches(labels, term.get("labelSelector", {}))
                ):
                    return False
    # Existing Pods' hard anti-affinity also protects their topology domains.
    for other in pods:
        for term in (
            other.get("spec", {})
            .get("affinity", {})
            .get("podAntiAffinity", {})
            .get("requiredDuringSchedulingIgnoredDuringExecution", [])
        ):
            if (
                namespace in (term.get("namespaces") or [other["namespace"]])
                and selector_matches(labels, term.get("labelSelector", {}))
                and same_domain(term, other)
            ):
                return False
    return True


def estimate(snapshot, scenario: Scenario | ServiceBundle, max_added=100, max_replicas=2000):
    proposals = proposals_for(scenario, max_replicas)
    first = proposals[0]
    spec, labels, namespace, request = (
        first["spec"],
        first["labels"],
        first["namespace"],
        first["per_replica"],
    )
    replicas = sum(p["replicas"] for p in proposals)
    planning = (
        first["planning"]
        if len(proposals) == 1
        else {
            "mode": "multi-service",
            **{
                k: sum(p["planning"][k] for p in proposals)
                for k in ["steady_replicas", "hpa_replicas", "surge_replicas", "peak_replicas"]
            },
        }
    )
    nodes = deepcopy(snapshot["nodes"])
    # Existing Pod records are read-only; only the placement list receives new entries.
    pods = list(snapshot.get("context", {}).get("pods", []))
    factor = 0.8 if snapshot["pool"]["environment"] == "production" else 0.9
    warnings = list(
        dict.fromkeys(
            [w for p in proposals for w in unsupported(p["spec"])]
            + snapshot.get("context", {}).get("uncertainties", [])
        )
    )
    violations = [
        n["name"]
        for n in nodes
        if any(n["requested"][k] > n["allocatable"][k] * factor for k in ["cpu", "memory"])
    ]
    baseline = {
        "target_pool": {k: snapshot["pool"][k] for k in ["id", "name", "cluster", "project", "environment"]},
        "snapshot_id": snapshot["id"],
        "snapshot_at": snapshot["saved_at"],
        "policy_factor": factor,
        "per_replica": request if len(proposals) == 1 else None,
        "kind": "capacity_bundle" if isinstance(scenario, ServiceBundle) else "capacity",
        "services": [
            {k: p[k] for k in ["key", "name", "namespace", "replicas", "per_replica", "planning"]}
            for p in proposals
        ],
        "total_requests": {
            k: sum(p["per_replica"][k] * p["replicas"] for p in proposals) for k in ["cpu", "memory"]
        },
        "replicas": replicas,
        "planning": planning,
        "confidence": {
            "status": "Conditional" if warnings else "Snapshot-based",
            "snapshot_age_seconds": max(0, time.time() - snapshot["saved_at"]),
            "stale": time.time() - snapshot["saved_at"] > 86400,
            "metrics_used_for_placement": False,
        },
        "violations": violations,
        "warnings": warnings,
        "assumptions": [
            "Existing Pods remain fixed; this is additional demand, not replacement of an existing workload",
            "Peak replicas include the selected HPA cap and rollout surge; terminating Pods and rollout sequencing are not modeled",
            "Bounded greedy placement; a feasible result is not a proven minimum",
            "New nodes use saved observed allocatable capacity and conservative DaemonSet overhead",
        ],
        "search_bound": max_added,
        "placements": [],
    }
    context = snapshot.get("context", {})
    known_namespaces = set(context.get("namespaces", [])) | {p["namespace"] for p in context.get("pods", [])}
    namespaces = {p["namespace"] for p in proposals}
    missing = namespaces - known_namespaces
    if context.get("namespace_context_complete") and missing:
        return {
            **baseline,
            "outcome": "Blocked constraints",
            "reason": "Target namespace is absent from the saved cluster context: "
            + ", ".join(sorted(missing)),
            "additional_nodes": 0,
            "cost": {"available": False, "reason": "Namespace must exist before deployment"},
        }
    if missing:
        warnings.append("Target namespace existence could not be verified: " + ", ".join(sorted(missing)))
    for quota in context.get("quotas", []):
        ns = quota["metadata"]["namespace"]
        if ns not in namespaces:
            continue
        hard, used = quota.get("status", {}).get("hard", {}), quota.get("status", {}).get("used", {})
        if quota.get("spec", {}).get("scopes") or quota.get("spec", {}).get("scopeSelector"):
            warnings.append("Scoped ResourceQuota needs external validation")
            continue
        local = [p for p in proposals if p["namespace"] == ns]
        count = sum(p["replicas"] for p in local)
        for key, delta in {
            "requests.cpu": sum(p["per_replica"]["cpu"] * p["replicas"] for p in local),
            "requests.memory": sum(p["per_replica"]["memory"] * p["replicas"] for p in local),
            "pods": count,
            "count/pods": count,
        }.items():
            if key in hard and quantity(used.get(key, 0)) + delta > quantity(hard[key]):
                return {
                    **baseline,
                    "outcome": "Blocked constraints",
                    "reason": f"Namespace {ns} quota {key} exceeded by combined service demand",
                    "additional_nodes": 0,
                    "cost": cost(snapshot.get("pricing"), 0),
                }
        if any(k not in {"requests.cpu", "requests.memory", "pods", "count/pods"} for k in hard):
            warnings.append("Additional quota dimensions need external validation")
    if any(lr["metadata"]["namespace"] in namespaces for lr in context.get("limit_ranges", [])):
        warnings.append("Namespace LimitRange defaults and bounds need external validation")
    pending = context.get("pending", [])
    demand = [
        (p["spec"], p.get("labels", {}), p["namespace"], "existing:" + p["name"], None) for p in pending
    ]
    for p in proposals:
        prefix = p["key"] if len(proposals) > 1 else p["name"]
        demand.extend(
            (p["spec"], p["labels"], p["namespace"], f"{prefix}-{i + 1}", p["key"])
            for i in range(p["replicas"])
        )
    added, placements = [], []
    templates = snapshot.get("node_templates", [])
    request_cache = {id(p["spec"]): p["per_replica"] for p in proposals}

    def effective(pod_spec):
        key = id(pod_spec)
        if key not in request_cache:
            request_cache[key] = pod_resources(pod_spec)
        return request_cache[key]

    def rejection_reasons(n, pod_spec, pod_labels, ns):
        req = effective(pod_spec)
        reasons = []
        if not n["ready"]:
            reasons.append("Node is not Ready")
        if n.get("unschedulable"):
            reasons.append("Node is cordoned")
        check = {**n, "ready": True, "unschedulable": False}
        if not node_eligible({**check, "taints": []}, pod_spec):
            reasons.append("Node name, selector or required node affinity does not match")
        if not node_eligible(check, {"tolerations": pod_spec.get("tolerations", [])}):
            reasons.append("Untolerated NoSchedule/NoExecute taint")
        if n["pod_count"] >= n["allocatable"].get("pods", 110):
            reasons.append("Pod slots exhausted")
        for k in ["cpu", "memory"]:
            if n["requested"][k] + req[k] > n["allocatable"][k] * factor + 1e-9:
                reasons.append(k.upper() + " request ceiling exceeded")
        context_nodes = snapshot.get("context", {}).get("nodes", []) + nodes
        if not affinity_ok(n, pod_spec, pod_labels, ns, pods, context_nodes):
            reasons.append("Required Pod affinity/anti-affinity")
        if not spread_ok(n, pod_spec, pod_labels, ns, pods, context_nodes):
            reasons.append("Hard topology spread constraint")
        return reasons

    def can_place(n, pod_spec, pod_labels, ns):
        req = effective(pod_spec)
        if not node_eligible(n, pod_spec) or n["pod_count"] >= n["allocatable"].get("pods", 110):
            return False
        if any(n["requested"][k] + req[k] > n["allocatable"][k] * factor + 1e-9 for k in ["cpu", "memory"]):
            return False
        context_nodes = snapshot.get("context", {}).get("nodes", []) + nodes
        return affinity_ok(n, pod_spec, pod_labels, ns, pods, context_nodes) and spread_ok(
            n, pod_spec, pod_labels, ns, pods, context_nodes
        )

    reason = None
    for pod_spec, pod_labels, ns, name, service_key in demand:
        warnings.extend(unsupported(pod_spec))
        eligible = [n for n in nodes if can_place(n, pod_spec, pod_labels, ns)]
        if not eligible and len(added) < max_added:
            for template in templates:
                candidate = deepcopy(template)
                candidate["name"] = f"planned-{len(added) + 1}-{template['zone']}"
                candidate["labels"]["kubernetes.io/hostname"] = candidate["name"]
                if can_place(candidate, pod_spec, pod_labels, ns):
                    added.append(candidate)
                    nodes.append(candidate)
                    eligible = [candidate]
                    break
        if not eligible:
            reason = (
                "Search bound reached; no conclusion about feasibility"
                if len(added) >= max_added
                else "No eligible node or saved node template can satisfy this Pod"
            )
            if not templates:
                warnings.append("No verified allocatable template for new nodes")
            req = effective(pod_spec)
            if any(
                node_eligible(n, pod_spec)
                and all(req[k] <= n["allocatable"][k] * factor for k in ["cpu", "memory"])
                for n in nodes + templates
            ):
                warnings.append(
                    "Greedy placement did not find a complete assignment; alternate assignments may exist"
                )
            break
        # Pack tighter nodes first, preserving larger remaining budgets.
        chosen = min(
            eligible, key=lambda n: sum(n["allocatable"][k] * factor - n["requested"][k] for k in ["cpu"])
        )
        req = effective(pod_spec)
        for k in ["cpu", "memory"]:
            chosen["requested"][k] += req[k]
        chosen["pod_count"] += 1
        pods.append(
            {"name": name, "namespace": ns, "labels": pod_labels, "node": chosen["name"], "spec": pod_spec}
        )
        placements.append(
            {
                "replica": name,
                "node": chosen["name"],
                "zone": chosen["zone"],
                "existing_demand": service_key is None,
                "service": service_key,
            }
        )
    permitted = (
        max(0, snapshot["pool"].get("autoscaler_max", len(snapshot["nodes"])) - len(snapshot["nodes"]))
        if snapshot["pool"].get("autoscaling")
        else 0
    )
    uncertain = bool(warnings) or (reason and len(added) >= max_added)
    outcome = (
        "Cannot fully assess"
        if uncertain
        else "Blocked constraints"
        if reason
        else "Needs nodes"
        if added
        else "Fits"
    )
    before = {n["name"]: n for n in snapshot["nodes"]}
    by_node, by_zone = defaultdict(list), defaultdict(int)
    for placement in placements:
        by_node[placement["node"]].append(placement["replica"])
        by_zone[placement["zone"]] += int(not placement["existing_demand"])
    node_budgets = [
        {
            "name": n["name"],
            "zone": n["zone"],
            "planned": n["name"] not in before,
            "allocatable": n["allocatable"],
            "ceiling": {k: n["allocatable"][k] * factor for k in ["cpu", "memory"]},
            "before": before.get(n["name"], next((t for t in templates if t["zone"] == n["zone"]), n))[
                "requested"
            ],
            "after": n["requested"],
            "remaining": {k: n["allocatable"][k] * factor - n["requested"][k] for k in ["cpu", "memory"]},
            "placements": by_node[n["name"]],
            "rejections": rejection_reasons(n, spec, labels, namespace),
            "service_rejections": {
                p["key"]: rejection_reasons(n, p["spec"], p["labels"], p["namespace"]) for p in proposals
            },
        }
        for n in nodes
    ]
    return {
        **baseline,
        "warnings": sorted(set(warnings)),
        "outcome": outcome,
        "reason": reason
        or (
            "Conditional placement found; resolve listed uncertainties"
            if uncertain
            else "Feasible placement found under saved snapshot assumptions"
        ),
        "additional_nodes": len(added) if not reason else None,
        "candidate_nodes": len(added),
        "permitted_growth": permitted,
        "exceeds_autoscaler_max": not reason and len(added) > permitted,
        "pending_replicas_accounted": len(pending),
        "placements": placements,
        "services": [
            {**p, "placed_replicas": sum(x["service"] == p["key"] for x in placements)}
            for p in baseline["services"]
        ],
        "node_budgets": node_budgets,
        "zone_distribution": {zone: by_zone[zone] for zone in sorted({n["zone"] for n in nodes})},
        "confidence": {**baseline["confidence"], "status": "Conditional" if uncertain else "Snapshot-based"},
        "cost": cost(snapshot.get("pricing"), len(added))
        if not reason
        else {"available": False, "reason": "A complete feasible placement was not found"},
    }
