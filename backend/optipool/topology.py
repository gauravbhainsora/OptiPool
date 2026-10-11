"""Hard topology-spread checks over saved cluster context and proposed nodes."""

from copy import deepcopy

from .resources import node_eligible, selector_matches


def spread_ok(candidate, spec, labels, namespace, pods, nodes):
    mapping = {n["name"]: n for n in nodes + [candidate]}
    for term in spec.get("topologySpreadConstraints") or []:
        if term["whenUnsatisfiable"] == "ScheduleAnyway" or term.get("matchLabelKeys"):
            continue
        key = term["topologyKey"]
        if key not in candidate["labels"]:
            return False
        affinity_policy = term.get("nodeAffinityPolicy", "Honor")
        taint_policy = term.get("nodeTaintsPolicy", "Ignore")
        eligible = {}
        for name, node in mapping.items():
            check = deepcopy(node)
            check.update(ready=True, unschedulable=False)
            if taint_policy == "Ignore":
                check["taints"] = []
            selectors = spec if affinity_policy == "Honor" else {"tolerations": spec.get("tolerations", [])}
            if key in node["labels"] and node_eligible(check, selectors):
                eligible[name] = node["labels"][key]
        counts = {domain: 0 for domain in eligible.values()}
        if candidate["name"] not in eligible:
            return False
        for pod in pods:
            if (
                pod.get("node") in eligible
                and pod["namespace"] == namespace
                and selector_matches(pod.get("labels", {}), term.get("labelSelector"))
            ):
                counts[eligible[pod["node"]]] += 1
        minimum = min(counts.values()) if len(counts) >= term.get("minDomains", 1) else 0
        increment = int(selector_matches(labels, term.get("labelSelector")))
        if counts[eligible[candidate["name"]]] + increment - minimum > term["maxSkew"]:
            return False
    return True
