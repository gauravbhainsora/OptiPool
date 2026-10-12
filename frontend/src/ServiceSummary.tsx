import { cores, gib } from "./components";
import type { Estimate } from "./types";

export default function ServiceSummary({
  result,
}: {
  result: Pick<Estimate, "services" | "total_requests" | "replicas">;
}) {
  if (!result.services) return null;
  return (
    <>
      {result.total_requests && (
        <p className="form-hint">
          Submitted peak: {result.replicas} Pods ·{" "}
          {cores(result.total_requests.cpu)} /{" "}
          {gib(result.total_requests.memory)} combined requests. Changes to the
          form require a new assessment.
        </p>
      )}
      <div className="table-wrap">
        <table aria-label="Assessed services">
          <thead>
            <tr>
              <th>Service / namespace</th>
              <th>Per replica</th>
              <th>Base / peak</th>
              <th>Placed</th>
            </tr>
          </thead>
          <tbody>
            {result.services.map((s) => (
              <tr key={s.key}>
                <td>
                  {s.name}
                  <small>{s.namespace}</small>
                </td>
                <td>
                  {cores(s.per_replica.cpu)}
                  <small>{gib(s.per_replica.memory)}</small>
                </td>
                <td>
                  {s.planning.steady_replicas} / {s.replicas}
                </td>
                <td>{s.placed_replicas ?? 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
