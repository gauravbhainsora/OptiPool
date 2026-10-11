"""Kubernetes quantity and effective Pod request accounting."""

import re
from decimal import Decimal

SCALE = {
    "n": Decimal("1e-9"),
    "u": Decimal("1e-6"),
    "m": Decimal("1e-3"),
    "": Decimal(1),
    "k": Decimal(1000),
    "K": Decimal(1000),
    "M": Decimal(10) ** 6,
    "G": Decimal(10) ** 9,
    "T": Decimal(10) ** 12,
    "P": Decimal(10) ** 15,
    "E": Decimal(10) ** 18,
    **{f"{s}i": Decimal(1024) ** i for i, s in enumerate("KMGTPE", 1)},
}


def quantity(value) -> float:
    raw = str(value)
    match = re.fullmatch(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)([a-zA-Z]*)", raw)
    if not match or match[2] not in SCALE:
        raise ValueError(f"Invalid Kubernetes quantity: {raw}")
    result = float(Decimal(match[1]) * SCALE[match[2]])
    if result < 0 or result == float("inf"):
        raise ValueError("Resources must be finite and nonnegative")
    return result


def resources(container, field="requests"):
    data = container.get("resources") or {}
    values = data.get(field) or {}
    # Kubernetes defaults a limit into a missing request; admission may add other defaults.
    if field == "requests":
        values = {**(data.get("limits") or {}), **values}
    return {"cpu": quantity(values.get("cpu", 0)), "memory": quantity(values.get("memory", 0))}


def pod_resources(spec, field="requests"):
    total = {"cpu": 0.0, "memory": 0.0}
    for c in spec.get("containers", []):
        for k, value in resources(c, field).items():
            total[k] += value
    sidecars = {"cpu": 0.0, "memory": 0.0}
    init_peak = {"cpu": 0.0, "memory": 0.0}
    for c in spec.get("initContainers") or []:
        request = resources(c, field)
        if c.get("restartPolicy") == "Always":
            for k in sidecars:
                sidecars[k] += request[k]
                init_peak[k] = max(init_peak[k], sidecars[k])
        else:
            for k in init_peak:
                init_peak[k] = max(init_peak[k], sidecars[k] + request[k])
    for k in total:
        total[k] = max(total[k] + sidecars[k], init_peak[k])
        if ((spec.get("resources") or {}).get(field) or {}).get(k) is not None:
            total[k] = quantity(spec["resources"][field][k])
        total[k] += quantity((spec.get("overhead") or {}).get(k, 0))
    return total


def selector_matches(labels, selector):
    if selector is None:
        return False
    if any(labels.get(k) != v for k, v in selector.get("matchLabels", {}).items()):
        return False
    for rule in selector.get("matchExpressions", []):
        key, op, values = rule["key"], rule["operator"], rule.get("values", [])
        if op == "In" and labels.get(key) not in values:
            return False
        if op == "NotIn" and labels.get(key) in values:
            return False
        if op == "Exists" and key not in labels:
            return False
        if op == "DoesNotExist" and key in labels:
            return False
        if op in {"Gt", "Lt"}:
            try:
                actual, threshold = int(labels[key]), int(values[0])
                if (op == "Gt" and actual <= threshold) or (op == "Lt" and actual >= threshold):
                    return False
            except (KeyError, ValueError, IndexError):
                return False
        if op not in {"In", "NotIn", "Exists", "DoesNotExist", "Gt", "Lt"}:
            raise ValueError(f"Unsupported selector operator {op}")
    return True


def node_eligible(node, spec):
    if not node["ready"] or node.get("unschedulable"):
        return False
    if spec.get("nodeName") and spec["nodeName"] != node["name"]:
        return False
    if not selector_matches(node["labels"], {"matchLabels": spec.get("nodeSelector", {})}):
        return False
    required = (
        spec.get("affinity", {}).get("nodeAffinity", {}).get("requiredDuringSchedulingIgnoredDuringExecution")
    )
    if required:
        terms = required.get("nodeSelectorTerms", [])
        if not any(
            (term.get("matchExpressions") or term.get("matchFields"))
            and selector_matches(node["labels"], term)
            and selector_matches(
                {"metadata.name": node["name"]}, {"matchExpressions": term.get("matchFields", [])}
            )
            for term in terms
        ):
            return False
    for taint in node.get("taints", []):
        if taint.get("effect") not in {"NoSchedule", "NoExecute"}:
            continue

        def tolerates(t, taint=taint):
            return (not t.get("effect") or t["effect"] == taint["effect"]) and (
                (t.get("operator", "Equal") == "Exists" and (not t.get("key") or t["key"] == taint["key"]))
                or (
                    t.get("operator", "Equal") == "Equal"
                    and t.get("key") == taint["key"]
                    and t.get("value", "") == taint.get("value", "")
                )
            )

        if not any(tolerates(t) for t in spec.get("tolerations", [])):
            return False
    return True
