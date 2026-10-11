"""Compare two immutable snapshots from the same pool; never fetch live data."""

from .pods import selected_pods


def compare(before, after):
    if before["pool"]["id"] != after["pool"]["id"]:
        raise ValueError("Snapshots must belong to the same node pool")

    def totals(snapshot):
        return {
            "nodes": len(snapshot["nodes"]),
            "pods": len(selected_pods(snapshot)),
            "cpu": sum(n["requested"]["cpu"] for n in snapshot["nodes"]),
            "memory": sum(n["requested"]["memory"] for n in snapshot["nodes"]),
        }

    a, b = totals(before), totals(after)
    changes = []
    for entity, key in [("nodes", "name"), ("pods", "uid"), ("workloads", "id")]:
        left = {v[key]: v for v in (selected_pods(before) if entity == "pods" else before[entity])}
        right = {v[key]: v for v in (selected_pods(after) if entity == "pods" else after[entity])}
        for ident in sorted(left.keys() | right.keys()):
            old, new = left.get(ident), right.get(ident)
            fields = [
                "requested",
                "limits",
                "ready",
                "phase",
                "restarts",
                "node",
                "allocatable",
                "desired",
                "pool_replicas",
            ]
            changed = {
                f: {"before": old.get(f), "after": new.get(f)}
                for f in fields
                if old and new and old.get(f) != new.get(f)
            }
            if not old or not new or changed:
                changes.append(
                    {
                        "entity": entity,
                        "name": (new or old)["name"],
                        "namespace": (new or old).get("namespace"),
                        "id": ident,
                        "change": "Added" if not old else "Removed" if not new else "Changed",
                        "fields": changed,
                    }
                )
    return {
        "pool_id": after["pool"]["id"],
        "before": {"id": before["id"], "saved_at": before["saved_at"], **a},
        "after": {"id": after["id"], "saved_at": after["saved_at"], **b},
        "delta": {k: b[k] - a[k] for k in a},
        "changes": changes,
    }
