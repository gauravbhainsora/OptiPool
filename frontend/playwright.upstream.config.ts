import { defineConfig } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

process.env.OPTIPOOL_UPSTREAM_E2E = "1";
const data = mkdtempSync(join(tmpdir(), "optipool-upstream-e2e-"));
export default defineConfig({
  testDir: "./tests",
  testMatch: "p99-upstream.spec.ts",
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:8115",
    viewport: { width: 1440, height: 1000 },
    trace: "retain-on-failure",
  },
  webServer: {
    command:
      "../.venv/bin/uvicorn p99_upstream_fixture:upstream_app --factory --host 127.0.0.1 --port 8115",
    url: "http://127.0.0.1:8115/healthz",
    reuseExistingServer: false,
    env: {
      PYTHONPATH: `${resolve("../backend")}:${resolve("../backend/tests")}`,
      OPTIPOOL_MODE: "demo",
      OPTIPOOL_AUTH_MODE: "local",
      OPTIPOOL_DATABASE: join(data, "e2e.db"),
    },
    timeout: 30_000,
  },
});
