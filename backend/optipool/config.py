import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator


class Settings(BaseModel):
    mode: str = "demo"
    auth_mode: str = "local"
    iap_audience: str = ""
    database: str = "data/optipool.db"
    project_allowlist: list[str] = Field(default_factory=list)
    environment: dict[str, str] = Field(default_factory=dict)
    pricing_mappings: dict[str, dict] = Field(default_factory=dict)
    min_metric_samples: int = Field(20, ge=1, le=100_000)
    min_reduction_observation_seconds: int = Field(86400, ge=1, le=864000)
    min_reduction_coverage: float = Field(0.9, ge=0, le=1)
    max_added_nodes: int = Field(100, ge=1, le=500)
    max_replicas: int = Field(2000, ge=1, le=2000)
    default_environment: str = "production"
    # Production remains gated until the operator records nonprod validation.
    live_validation_complete: bool = False

    @model_validator(mode="after")
    def validate_modes(self):
        if self.mode not in {"demo", "live"} or self.auth_mode not in {"local", "iap"}:
            raise ValueError("mode must be demo/live and auth_mode local/iap")
        if self.auth_mode == "iap" and not self.iap_audience:
            raise ValueError("IAP audience is required")
        if self.default_environment not in {"production", "nonproduction"}:
            raise ValueError("invalid default environment")
        if any(v not in {"production", "nonproduction"} for v in self.environment.values()):
            raise ValueError("environment values must be production/nonproduction")
        return self

    def pool_environment(self, project: str, cluster: str, pool: str) -> str:
        return next(
            (
                self.environment[k]
                for k in [f"{project}/{cluster}/{pool}", f"{project}/{cluster}", project]
                if k in self.environment
            ),
            self.default_environment,
        )


def load_settings() -> Settings:
    path = os.environ.get("OPTIPOOL_CONFIG", "config.local.yaml")
    values = yaml.safe_load(Path(path).read_text()) or {} if Path(path).exists() else {}
    for key in ["mode", "auth_mode", "iap_audience", "database"]:
        value = os.environ.get("OPTIPOOL_" + key.upper())
        if value is not None:
            values[key] = value
    return Settings(**values)
