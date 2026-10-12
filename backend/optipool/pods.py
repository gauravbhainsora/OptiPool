from .resources import pod_resources, resources


def selected_pods(snapshot):
    if "pods" in snapshot:  # Already normalized saved view, never raw Kubernetes objects.
        return snapshot["pods"]
    names = {n["name"] for n in snapshot["nodes"]}
    pending_uids = {p.get("uid") for p in snapshot.get("context", {}).get("pending", []) if p.get("uid")}
    return [
        {
            "name": p["name"],
            "namespace": p["namespace"],
            "uid": p["uid"],
            "workload": p.get("workload", "Unknown"),
            "node": p.get("node"),
            "phase": p.get("phase", "Unknown"),
            "created": p.get("created"),
            "restarts": p.get("restarts", 0),
            "ready": p.get("ready"),
            "requested": pod_resources(p["spec"]),
            "limits": pod_resources(p["spec"], "limits"),
            "labels": p.get("labels", {}),
            "spec": p["spec"],
            "conditions": p.get("conditions", []),
            "status_available": "container_statuses" in p,
            "oom_killed": any(
                c.get("lastState", {}).get("terminated", {}).get("reason") == "OOMKilled"
                or c.get("state", {}).get("terminated", {}).get("reason") == "OOMKilled"
                for c in p.get("container_statuses", [])
            ),
            "containers": [
                {
                    "name": c["name"],
                    "kind": kind,
                    "requested": resources(c),
                    "limits": resources(c, "limits"),
                    "status": next(
                        (s for s in p.get("container_statuses", []) if s.get("name") == c["name"]), None
                    ),
                }
                for kind, field in [("App", "containers"), ("Init", "initContainers")]
                for c in p["spec"].get(field) or []
            ],
        }
        for p in snapshot.get("context", {}).get("pods", [])
        if p.get("node") in names or p.get("uid") in pending_uids
    ]


def steady_containers(spec):
    """Containers whose runtime risk evidence needs a full Pod-lifetime denominator."""
    return list(spec.get("containers", [])) + [
        c for c in spec.get("initContainers", []) if c.get("restartPolicy") == "Always"
    ]
