"""Validate the manifest shapes used by planning, with field-specific input errors."""

from .resources import quantity


def mapping(value, path, optional=False):
    if value is None and optional:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    return value


def sequence(value, path):
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(v, dict) for v in value):
        raise ValueError(f"{path} must be a list of objects")
    return value


def resource_fields(obj, path):
    data = mapping(obj.get("resources"), path + ".resources", optional=True)
    obj["resources"] = data
    for field in ["requests", "limits"]:
        data[field] = mapping(data.get(field), path + ".resources." + field, optional=True)
        for value in data[field].values():
            quantity(value)
    for key in ["cpu", "memory"]:
        if key in data["requests"] and key in data["limits"]:
            if quantity(data["requests"][key]) > quantity(data["limits"][key]):
                raise ValueError(f"{path}: request cannot exceed its configured limit")


def selector(value, path):
    value = mapping(value, path)
    value["matchLabels"] = mapping(value.get("matchLabels"), path + ".matchLabels", optional=True)
    if any(not isinstance(k, str) or not isinstance(v, str) for k, v in value["matchLabels"].items()):
        raise ValueError(f"{path}.matchLabels must contain string labels")
    value["matchExpressions"] = sequence(value.get("matchExpressions"), path + ".matchExpressions")
    for rule in value["matchExpressions"]:
        values = rule.get("values") or []
        if not isinstance(rule.get("key"), str) or not rule["key"]:
            raise ValueError(f"{path}: selector key is required")
        if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
            raise ValueError(f"{path}: selector values must be strings")
        rule["values"] = values
        op = rule.get("operator")
        if op not in {"In", "NotIn", "Exists", "DoesNotExist", "Gt", "Lt"}:
            raise ValueError(f"{path}: unsupported selector operator {op}")
        if (op in {"In", "NotIn"} and not values) or (op in {"Gt", "Lt"} and len(values) != 1):
            raise ValueError(f"{path}: operator {op} requires values")
    return value


def pod_spec(value):
    pod = mapping(value, "spec.template.spec")
    pod["containers"] = sequence(pod.get("containers"), "containers")
    if not pod["containers"]:
        raise ValueError("Deployment must have containers")
    for field in ["initContainers", "volumes", "tolerations", "topologySpreadConstraints"]:
        pod[field] = sequence(pod.get(field), field)
    for container in pod["containers"] + pod["initContainers"]:
        if not isinstance(container.get("name"), str) or not container["name"]:
            raise ValueError("Each container requires a name")
        resource_fields(container, "container " + container["name"])
        container["ports"] = sequence(container.get("ports"), "container ports")
    resource_fields(pod, "Pod")
    for field in ["nodeSelector", "overhead", "affinity"]:
        pod[field] = mapping(pod.get(field), field, optional=True)
    if any(not isinstance(k, str) or not isinstance(v, str) for k, v in pod["nodeSelector"].items()):
        raise ValueError("nodeSelector must contain string labels")
    for value in pod["overhead"].values():
        quantity(value)
    affinity = pod["affinity"]
    for kind in ["nodeAffinity", "podAffinity", "podAntiAffinity"]:
        if kind not in affinity or affinity[kind] is None:
            affinity.pop(kind, None)
            continue
        data = mapping(affinity[kind], "affinity." + kind)
        required = data.get("requiredDuringSchedulingIgnoredDuringExecution")
        if required is None:
            data.pop("requiredDuringSchedulingIgnoredDuringExecution", None)
        elif kind == "nodeAffinity":
            required = mapping(required, "nodeAffinity.required")
            required["nodeSelectorTerms"] = sequence(required.get("nodeSelectorTerms"), "nodeSelectorTerms")
            for term in required["nodeSelectorTerms"]:
                selector(term, "nodeSelectorTerm")
                term["matchFields"] = sequence(term.get("matchFields"), "matchFields")
        else:
            data["requiredDuringSchedulingIgnoredDuringExecution"] = sequence(required, kind + ".required")
            for term in required:
                if not isinstance(term.get("topologyKey"), str) or not term["topologyKey"]:
                    raise ValueError("Affinity topologyKey is required")
                if term.get("labelSelector") is not None:
                    selector(term["labelSelector"], "affinity labelSelector")
    for term in pod["topologySpreadConstraints"]:
        if not isinstance(term.get("topologyKey"), str) or not term["topologyKey"]:
            raise ValueError("Topology spread topologyKey is required")
        for key in ["maxSkew", "minDomains"]:
            val = term.get(key, 1)
            if type(val) is not int or val < 1:
                raise ValueError(f"Topology spread {key} must be a positive integer")
        if term.get("whenUnsatisfiable") not in {"DoNotSchedule", "ScheduleAnyway"}:
            raise ValueError("Topology spread whenUnsatisfiable is required")
        for key in ["nodeAffinityPolicy", "nodeTaintsPolicy"]:
            if key in term and term[key] not in {"Honor", "Ignore"}:
                raise ValueError(f"Topology spread {key} must be Honor or Ignore")
        if term.get("labelSelector") is not None:
            selector(term["labelSelector"], "topology spread labelSelector")
    return pod
