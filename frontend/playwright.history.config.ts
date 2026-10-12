import { defineConfig } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

process.env.OPTIPOOL_HISTORY_E2E = "1";
const data = mkdtempSync(join(tmpdir(), "optipool-history-e2e-"));
const port = process.env.OPTIPOOL_TEST_PORT ?? "8114";
export default defineConfig({
  testDir: "./tests",
  testMatch: "p99-history.spec.ts",
  workers: 1,
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    viewport: { width: 1440, height: 1000 },
    trace: "retain-on-failure",
  },
  webServer: {
    command: `../.venv/bin/uvicorn p99_history_fixture:history_app --factory --host 127.0.0.1 --port ${port}`,
    url: `http://127.0.0.1:${port}/healthz`,
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
