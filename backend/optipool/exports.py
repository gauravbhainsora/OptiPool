import csv
import io
from datetime import UTC, datetime

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from .pods import selected_pods


def iso(value):
    return datetime.fromtimestamp(value, UTC).isoformat() if value else "Not fetched"


def pool_rows(inventory, snapshots):
    rows = []
    for pool in inventory:
        s = snapshots.get(pool["id"])
        pool = {**pool, **(s["pool"] if s else {}), "available": pool["available"]}
        nodes = s["nodes"] if s else []
        factor = 0.8 if pool["environment"] == "production" else 0.9
        rows.append(
            {
                "Project": pool["project"],
                "Cluster": pool["cluster"],
                "Node pool": pool["name"],
                "Environment": pool["environment"],
                "Location": pool["location"],
                "Machine type": pool["machine_type"],
                "Available": pool["available"],
                "Nodes": len(nodes) if s else "Unknown",
                "Autoscaler min": pool["autoscaler_min"],
                "Autoscaler max": pool["autoscaler_max"],
                "Allocatable CPU cores": sum(n["allocatable"]["cpu"] for n in nodes) if s else None,
                "Requested CPU cores": sum(n["requested"]["cpu"] for n in nodes) if s else None,
                "Allocatable memory GiB": sum(n["allocatable"]["memory"] for n in nodes) / 1024**3
                if s
                else None,
                "Requested memory GiB": sum(n["requested"]["memory"] for n in nodes) / 1024**3 if s else None,
                "Policy violations": sum(
                    any(n["requested"][k] > n["allocatable"][k] * factor for k in ["cpu", "memory"])
                    for n in nodes
                )
                if s
                else None,
                "Snapshot UTC": iso(s["saved_at"]) if s else "Not fetched",
                "Snapshot ID": s["id"] if s else "",
                "Synthetic": pool.get("synthetic", False),
            }
        )
    return rows


def workload_rows(snapshot, usage):
    rows = []
    for w in snapshot["workloads"]:
        metric = usage["workloads"].get(w["id"], {}) if w["kind"] == "Deployment" else {}
        rows.append(
            {
                "Project": snapshot["pool"]["project"],
                "Cluster": snapshot["pool"]["cluster"],
                "Node pool": snapshot["pool"]["name"],
                "Namespace": w["namespace"],
                "Kind": w["kind"],
                "Workload": w["name"],
                "Services": ", ".join(w["services"]),
                "Desired replicas (cluster)": w["desired"],
                "Running replicas (cluster)": w["running"],
                "Pending replicas (cluster)": w["pending"],
                "Replicas on pool": w["pool_replicas"],
                "CPU requests on pool": w["requested"]["cpu"],
                "Memory requests on pool GiB": w["requested"]["memory"] / 1024**3,
                "Highest replica p99 CPU cores": metric.get("cpu_p99"),
                "Highest replica p99 memory GiB": metric["memory_p99"] / 1024**3
                if metric.get("memory_p99") is not None
                else None,
                "CPU p99 replica": metric.get("cpu_replica"),
                "Memory p99 replica": metric.get("memory_replica"),
                "Window days": usage["days"],
                "Metrics cutoff UTC": iso(usage["cutoff"]),
                "Metric source": usage["source"],
                "Memory definition": usage["memory_definition"],
                "Coverage": usage["coverage"],
                "Snapshot UTC": iso(snapshot["saved_at"]),
                "Snapshot ID": snapshot["id"],
                "Synthetic": snapshot["pool"].get("synthetic", False),
            }
        )
    return rows


def pod_rows(snapshot, search=""):
    rows = []
    for p in selected_pods(snapshot):
        if (
            search
            and search.lower() not in f"{p['name']} {p['namespace']} {p['workload']} {p['node']}".lower()
        ):
            continue
        rows.append(
            {
                "Project": snapshot["pool"]["project"],
                "Cluster": snapshot["pool"]["cluster"],
                "Node pool": snapshot["pool"]["name"],
                "Pod": p["name"],
                "Pod UID": p["uid"],
                "Namespace": p["namespace"],
                "Workload": p["workload"],
                "Node": p["node"],
                "Phase": p["phase"],
                "Ready": p["ready"],
                "Restarts": p["restarts"],
                "CPU request cores": p["requested"]["cpu"],
                "Memory request GiB": p["requested"]["memory"] / 1024**3,
                "CPU limit cores": p["limits"]["cpu"],
                "Memory limit GiB": p["limits"]["memory"] / 1024**3,
                "Created UTC": iso(p["created"]),
                "Snapshot UTC": iso(snapshot["saved_at"]),
                "Snapshot ID": snapshot["id"],
                "Synthetic": snapshot["pool"].get("synthetic", False),
            }
        )
    return rows


def safe_cell(value):
    # Prevent spreadsheet formula injection from untrusted cloud labels/names.
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def render(rows, format, table):
    columns = list(rows[0]) if rows else ["No saved rows"]
    if format == "csv":
        out = io.StringIO(newline="")
        writer = csv.writer(out)
        writer.writerow(columns)
        writer.writerows([[safe_cell(row.get(c)) for c in columns] for row in rows])
        return out.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = table
    sheet.append(columns)
    for row in rows:
        sheet.append([safe_cell(row.get(c)) for c in columns])
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="173B37")
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for col in sheet.columns:
        sheet.column_dimensions[col[0].column_letter].width = min(55, max(14, len(str(col[0].value)) + 2))
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
