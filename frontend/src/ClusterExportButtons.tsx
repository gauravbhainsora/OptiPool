import { useState } from "react";
import { Download } from "lucide-react";
import { Notice } from "./components";
import type { ClusterSnapshot } from "./types";

export default function ClusterExportButtons({
  scope,
  table,
  search = "",
}: {
  scope: ClusterSnapshot;
  table: "workloads" | "pods";
  search?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function download(format: string) {
    setBusy(true);
    setError("");
    try {
      const response = await fetch(
        `/api/export-cluster/${table}?format=${format}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project: scope.project,
            location: scope.location,
            cluster: scope.cluster,
            days: scope.days,
            snapshots: Object.fromEntries(
              scope.sources.map((s) => [s.pool_id, s.snapshot_id]),
            ),
            pod_search: search,
          }),
        },
      );
      if (!response.ok)
        throw new Error((await response.json()).detail ?? "Export failed");
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `optipool-cluster-${table}.${format}`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div>
      <div className="export-buttons">
        <span className="muted">Export</span>
        {["csv", "xlsx"].map((format) => (
          <button
            key={format}
            className="button small"
            disabled={busy || !scope.sources.length}
            onClick={() => download(format)}
          >
            <Download size={14} />
            {format === "csv" ? "CSV" : "Excel"}
          </button>
        ))}
      </div>
      {error && <Notice>{error}</Notice>}
    </div>
  );
}
