import { Download, ArrowUpRight, AlertCircle } from "lucide-react";
import { params } from "./api";
import type { Usage } from "./types";

export const gib = (n: number | null | undefined) =>
  n == null ? "Unavailable" : `${(n / 1024 ** 3).toFixed(2)} GiB`;
export const cores = (n: number | null | undefined) =>
  n == null ? "Unavailable" : `${n.toFixed(2)} cores`;
export const date = (n: number | null | undefined) =>
  n
    ? new Date(n * 1000).toLocaleString(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      })
    : "Not fetched";
export const money = (n: number | null | undefined) =>
  n == null
    ? "Unavailable"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 2,
      }).format(n);

export function ExportButtons({
  table,
  query,
}: {
  table: string;
  query: Record<string, string | number>;
}) {
  return (
    <div className="export-buttons">
      <span className="muted">Export</span>
      {["csv", "xlsx"].map((format) => (
        <a
          key={format}
          className="button small"
          href={`/api/export/${table}?${params({ ...query, format })}`}
          download
        >
          <Download size={14} />
          {format === "xlsx" ? "Excel" : "CSV"}
        </a>
      ))}
    </div>
  );
}
export function Notice({ children }: { children: React.ReactNode }) {
  return (
    <div className="notice">
      <AlertCircle size={17} />
      <div>{children}</div>
    </div>
  );
}
export function BudgetBar({
  requested,
  allocatable,
  cap,
  unit,
}: {
  requested: number;
  allocatable: number;
  cap: number;
  unit: string;
}) {
  const ratio = allocatable ? requested / allocatable : 0;
  return (
    <div className="budget">
      <div className="budget-text">
        <strong>
          {(requested / (unit === "GiB" ? 1024 ** 3 : 1)).toFixed(2)}{" "}
          <span>{unit}</span>
        </strong>
        <span className={ratio > cap ? "over" : ""}>
          {(ratio * 100).toFixed(0)}%
        </span>
      </div>
      <div className="bar">
        <i
          className={ratio > cap ? "red" : ""}
          style={{ width: `${Math.min(100, ratio * 100)}%` }}
        />
        <b style={{ left: `${cap * 100}%` }} />
      </div>
      <small>
        of {(allocatable / (unit === "GiB" ? 1024 ** 3 : 1)).toFixed(2)} {unit}{" "}
        allocatable
      </small>
    </div>
  );
}
export function UsageChart({ usage }: { usage: Usage }) {
  const raw = usage.timeline.filter((sample) => sample.cpu !== null);
  const stride = Math.max(1, Math.floor(raw.length / 160));
  const rows = raw.filter((_, i) => i % stride === 0);
  const max = Math.max(1, ...rows.map((r) => r.cpu ?? 0));
  const points = rows
    .map(
      (r, i) =>
        `${50 + (i / Math.max(1, rows.length - 1)) * 900},${152 - ((r.cpu ?? 0) / max) * 105}`,
    )
    .join(" ");
  return (
    <section className="panel chart-panel">
      <div className="panel-heading">
        <div>
          <h3>Observed CPU usage</h3>
          <p>Sum of attributed replicas at each sample · {usage.source}</p>
        </div>
        <span className="pill neutral">{usage.days}-day window</span>
      </div>
      {rows.length ? (
        <svg
          role="img"
          aria-label="CPU usage for the selected saved window"
          viewBox="0 0 1000 210"
          className="usage-chart"
        >
          {[0, 0.5, 1].map((p) => (
            <g key={p}>
              <line
                x1="50"
                y1={152 - p * 105}
                x2="950"
                y2={152 - p * 105}
                stroke="#e7ece9"
                strokeDasharray="4 5"
              />
              <text x="4" y={156 - p * 105}>
                {(max * p).toFixed(1)}
              </text>
            </g>
          ))}
          <polygon points={`50,152 ${points} 950,152`} fill="#edf5f1" />
          <polyline
            points={points}
            stroke="#368a72"
            strokeWidth="2.5"
            fill="none"
          />
          <text x="50" y="185">
            {date(usage.start)}
          </text>
          <text x="950" y="185" textAnchor="end">
            {date(usage.cutoff)}
          </text>
        </svg>
      ) : (
        <div className="empty">
          No attributed usage samples are available in this window.
        </div>
      )}
      <div className="chart-footer">
        <span>
          <i />
          CPU cores · {usage.coverage}
        </span>
        <span>
          Window ends at saved cutoff <ArrowUpRight size={13} />
        </span>
      </div>
    </section>
  );
}
