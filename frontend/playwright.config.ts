import { defineConfig } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const data = mkdtempSync(join(tmpdir(), "optipool-e2e-"));
export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:8100",
    viewport: { width: 1440, height: 1000 },
    trace: "retain-on-failure",
  },
  webServer: {
    command:
      "../.venv/bin/uvicorn optipool.app:create_app --factory --host 127.0.0.1 --port 8100",
    url: "http://127.0.0.1:8100/healthz",
    reuseExistingServer: false,
    env: {
      OPTIPOOL_MODE: "demo",
      OPTIPOOL_AUTH_MODE: "local",
      OPTIPOOL_DATABASE: join(data, "e2e.db"),
    },
    timeout: 30_000,
  },
});
