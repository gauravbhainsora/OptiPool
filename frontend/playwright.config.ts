import { defineConfig } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const data = mkdtempSync(join(tmpdir(), "optipool-e2e-"));
const port = process.env.OPTIPOOL_TEST_PORT ?? "8100";
export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    viewport: { width: 1440, height: 1000 },
    trace: "retain-on-failure",
  },
  webServer: {
    command: `../.venv/bin/uvicorn optipool.app:create_app --factory --host 127.0.0.1 --port ${port}`,
    url: `http://127.0.0.1:${port}/healthz`,
    reuseExistingServer: false,
    env: {
      OPTIPOOL_MODE: "demo",
      OPTIPOOL_AUTH_MODE: "local",
      OPTIPOOL_DATABASE: join(data, "e2e.db"),
    },
    timeout: 30_000,
  },
});
