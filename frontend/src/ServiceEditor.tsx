import { Plus, Trash2 } from "lucide-react";

export type ServiceDraft = {
  key: string;
  advanced: boolean;
  name: string;
  namespace: string;
  cpu: string;
  memory: string;
  replicas: number;
  manifest: string;
  planning_mode: string;
  hpa_max_replicas: number;
  max_surge: string;
  spread_zones: boolean;
};

export function newService(index = 1): ServiceDraft {
  return {
    key: crypto.randomUUID(),
    advanced: false,
    name: index === 1 ? "recommendation-api" : `service-${index}`,
    namespace: "commerce",
    cpu: "500m",
    memory: "1Gi",
    replicas: index === 1 ? 6 : 2,
    manifest: "",
    planning_mode: "steady",
    hpa_max_replicas: 12,
    max_surge: "25%",
    spread_zones: false,
  };
}

export function servicePayload({
  key: _key,
  advanced,
  ...service
}: ServiceDraft) {
  return { ...service, manifest: advanced ? service.manifest : "" };
}

export default function ServiceEditor({
  services,
  onChange,
}: {
  services: ServiceDraft[];
  onChange: (services: ServiceDraft[]) => void;
}) {
  function change(index: number, patch: Partial<ServiceDraft>) {
    onChange(services.map((s, i) => (i === index ? { ...s, ...patch } : s)));
  }
  return (
    <div className="service-editor">
      {services.map((s, i) => (
        <fieldset
          className="service-input"
          key={s.key}
          aria-label={`Service ${i + 1}`}
        >
          <legend>Service {i + 1}</legend>
          {services.length > 1 && (
            <button
              type="button"
              className="button small remove-service"
              aria-label={`Remove service ${i + 1}`}
              onClick={() =>
                onChange(services.filter((_, index) => index !== i))
              }
            >
              <Trash2 size={14} /> Remove
            </button>
          )}
          <div className="segmented">
            <button
              type="button"
              className={!s.advanced ? "active" : ""}
              onClick={() => change(i, { advanced: false })}
            >
              Simple input
            </button>
            <button
              type="button"
              className={s.advanced ? "active" : ""}
              onClick={() => change(i, { advanced: true })}
            >
              Deployment YAML
            </button>
          </div>
          <label>
            Service name
            <input
              required
              value={s.name}
              onChange={(e) => change(i, { name: e.target.value })}
            />
          </label>
          <label>
            Target namespace
            <input
              required
              value={s.namespace}
              onChange={(e) => change(i, { namespace: e.target.value })}
            />
          </label>
          {s.advanced ? (
            <label>
              apps/v1 Deployment
              <textarea
                required
                rows={10}
                placeholder="apiVersion: apps/v1&#10;kind: Deployment&#10;metadata: ..."
                value={s.manifest}
                onChange={(e) => change(i, { manifest: e.target.value })}
              />
            </label>
          ) : (
            <>
              <div className="form-pair">
                <label>
                  CPU request / replica
                  <input
                    required
                    value={s.cpu}
                    onChange={(e) => change(i, { cpu: e.target.value })}
                  />
                </label>
                <label>
                  Memory request / replica
                  <input
                    required
                    value={s.memory}
                    onChange={(e) => change(i, { memory: e.target.value })}
                  />
                </label>
              </div>
              <label>
                Replica count
                <input
                  type="number"
                  min="0"
                  max="2000"
                  required
                  value={s.replicas}
                  onChange={(e) =>
                    change(i, { replicas: Number(e.target.value) })
                  }
                />
              </label>
              <p className="form-hint">
                One regular container per Pod. Use YAML for affinity, selectors,
                taints and other scheduling requirements.
              </p>
            </>
          )}
          <label>
            Planning scenario
            <select
              aria-label="Planning scenario"
              value={s.planning_mode}
              onChange={(e) => change(i, { planning_mode: e.target.value })}
            >
              <option value="steady">Steady replicas</option>
              <option value="hpa">HPA maximum</option>
              <option value="rollout">Rollout headroom</option>
              <option value="combined">HPA maximum + rollout headroom</option>
            </select>
          </label>
          {["hpa", "combined"].includes(s.planning_mode) && (
            <label>
              HPA maximum replicas
              <input
                aria-label="HPA maximum replicas"
                type="number"
                required
                min="0"
                max="2000"
                value={s.hpa_max_replicas}
                onChange={(e) =>
                  change(i, { hpa_max_replicas: Number(e.target.value) })
                }
              />
            </label>
          )}
          {["rollout", "combined"].includes(s.planning_mode) && (
            <label>
              Surge headroom
              <input
                aria-label="Surge headroom"
                required
                value={s.max_surge}
                onChange={(e) => change(i, { max_surge: e.target.value })}
              />
              <small>Integer or percentage, rounded up.</small>
            </label>
          )}
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={s.spread_zones}
              onChange={(e) => change(i, { spread_zones: e.target.checked })}
            />
            Spread proposed Pods across zones
          </label>
        </fieldset>
      ))}
      <button
        className="button small"
        type="button"
        disabled={services.length >= 20}
        onClick={() => onChange([...services, newService(services.length + 1)])}
      >
        <Plus size={14} />
        Add service
      </button>
      <p className="form-hint">
        All services share node budgets and scheduling context. Up to 20
        services and 2,000 combined peak replicas; placement follows the listed
        order and is not a proven minimum. Peak scenarios model additional
        demand, not replacement or terminating-Pod sequencing.
      </p>
    </div>
  );
}
