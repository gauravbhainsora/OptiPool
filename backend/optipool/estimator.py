"""Conservative, bounded greedy placement. A found placement is not proof of a minimum."""

from copy import deepcopy

import yaml
from pydantic import BaseModel, Field

from .pricing import cost
from .resources import node_eligible, pod_resources, quantity, selector_matches


class Scenario(BaseModel):
    name: str = Field(default="new-service", min_length=1, max_length=100)
    namespace: str = Field(default="default", min_length=1, max_length=253)
    cpu: str = "250m"
    memory: str = "256Mi"
    replicas: int = Field(default=3, ge=0, le=2000)
    manifest: str = Field(default="", max_length=200_000)

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
        spec = obj["spec"]
        pod = spec["template"]["spec"]
        if not isinstance(pod, dict) or not isinstance(pod.get("containers"), list):
            raise ValueError("Deployment template requires a Pod spec and container list")
        for key in ["affinity", "nodeSelector", "overhead", "resources"]:
            if pod.get(key) is None:
                pod.pop(key, None)
        if not pod.get("containers"):
            raise ValueError("Deployment must have containers")
        for c in pod["containers"] + (pod.get("initContainers") or []):
            if not isinstance(c, dict) or not c.get("name"):
                raise ValueError("Each container requires a name")
            requests, limits = (
                c.get("resources", {}).get("requests", {}),
                c.get("resources", {}).get("limits", {}),
            )
            if any(
                k in requests and quantity(requests[k]) > quantity(limits[k])
                for k in ["cpu", "memory"]
                if k in limits
            ):
                raise ValueError("Container request cannot exceed its configured limit")
        labels = spec["template"].get("metadata", {}).get("labels", {})
        if not spec.get("selector") or not selector_matches(labels, spec["selector"]):
            raise ValueError("Deployment requires a selector matching its template labels")
        replicas = int(spec.get("replicas", self.replicas))
        if replicas < 0 or replicas > 2000:
            raise ValueError("replicas must be between 0 and 2000")
        if obj.get("metadata", {}).get("namespace", self.namespace) != self.namespace:
            raise ValueError("Manifest namespace must match target namespace")
        return pod, spec["template"].get("metadata", {}).get("labels", {}), replicas


def unsupported(spec):
    reasons = []
    if spec.get("schedulerName", "default-scheduler") != "default-scheduler":
        reasons.append("Custom scheduler cannot be reproduced")
    for key, label in [
        ("topologySpreadConstraints", "Topology spread simulation"),
        ("runtimeClassName", "RuntimeClass admission overhead"),
        ("resourceClaims", "Dynamic resource allocation"),
    ]:
        if spec.get(key):
            reasons.append(label + " requires validation outside this simulator")
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


def estimate(snapshot, scenario: Scenario, max_added=100):
    spec, labels, replicas = scenario.pod()
    request = pod_resources(spec)
    nodes = deepcopy(snapshot["nodes"])
    pods = deepcopy(snapshot.get("context", {}).get("pods", []))
    factor = 0.8 if snapshot["pool"]["environment"] == "production" else 0.9
    warnings = list(dict.fromkeys(unsupported(spec) + snapshot.get("context", {}).get("uncertainties", [])))
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
        "per_replica": request,
        "replicas": replicas,
        "violations": violations,
        "warnings": warnings,
        "assumptions": [
            "Existing Pods remain fixed; no preemption or rollout surge",
            "Bounded greedy placement; a feasible result is not a proven minimum",
            "New nodes use saved observed allocatable capacity and conservative DaemonSet overhead",
        ],
        "search_bound": max_added,
        "placements": [],
    }
    namespace = scenario.namespace
    context = snapshot.get("context", {})
    known_namespaces = set(context.get("namespaces", [])) | {p["namespace"] for p in context.get("pods", [])}
    if context.get("namespace_context_complete") and namespace not in known_namespaces:
        return {
            **baseline,
            "outcome": "Blocked constraints",
            "reason": "Target namespace is absent from the saved cluster context",
            "additional_nodes": 0,
            "cost": {"available": False, "reason": "Namespace must exist before deployment"},
        }
    if not context.get("namespace_context_complete") and namespace not in known_namespaces:
        warnings.append("Target namespace existence could not be verified")
    quotas = snapshot.get("context", {}).get("quotas", [])
    for quota in quotas:
        if quota["metadata"]["namespace"] != namespace:
            continue
        hard, used = quota.get("status", {}).get("hard", {}), quota.get("status", {}).get("used", {})
        if quota.get("spec", {}).get("scopes") or quota.get("spec", {}).get("scopeSelector"):
            warnings.append("Scoped ResourceQuota needs external validation")
            continue
        for key, delta in {
            "requests.cpu": request["cpu"] * replicas,
            "requests.memory": request["memory"] * replicas,
            "pods": replicas,
        }.items():
            if key in hard and quantity(used.get(key, 0)) + delta > quantity(hard[key]):
                return {
                    **baseline,
                    "outcome": "Blocked constraints",
                    "reason": f"Namespace quota {key} exceeded",
                    "additional_nodes": 0,
                    "cost": cost(snapshot.get("pricing"), 0),
                }
        if any(k not in {"requests.cpu", "requests.memory", "pods", "count/pods"} for k in hard):
            warnings.append("Additional quota dimensions need external validation")
    if any(
        limit_range["metadata"]["namespace"] == namespace
        for limit_range in snapshot.get("context", {}).get("limit_ranges", [])
    ):
        warnings.append("Namespace LimitRange defaults and bounds need external validation")
    pending = snapshot.get("context", {}).get("pending", [])
    demand = [(p["spec"], p.get("labels", {}), p["namespace"], "existing:" + p["name"]) for p in pending]
    demand += [(spec, labels, namespace, f"{scenario.name}-{i + 1}") for i in range(replicas)]
    added, placements = [], []
    templates = snapshot.get("node_templates", [])

    def can_place(n, pod_spec, pod_labels, ns):
        req = pod_resources(pod_spec)
        return (
            node_eligible(n, pod_spec)
            and n["pod_count"] < n["allocatable"].get("pods", 110)
            and all(
                n["requested"][k] + req[k] <= n["allocatable"][k] * factor + 1e-9 for k in ["cpu", "memory"]
            )
            and affinity_ok(
                n, pod_spec, pod_labels, ns, pods, snapshot.get("context", {}).get("nodes", []) + nodes
            )
        )

    reason = None
    for pod_spec, pod_labels, ns, name in demand:
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
            req = pod_resources(pod_spec)
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
        req = pod_resources(pod_spec)
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
                "existing_demand": name.startswith("existing:"),
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
        "cost": cost(snapshot.get("pricing"), len(added))
        if not reason
        else {"available": False, "reason": "A complete feasible placement was not found"},
    }
