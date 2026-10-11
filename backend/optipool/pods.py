from .resources import pod_resources


def selected_pods(snapshot):
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
        }
        for p in snapshot.get("context", {}).get("pods", [])
        if p.get("node") in names or p.get("uid") in pending_uids
    ]
