import { test, expect } from "@playwright/test";

test("saved inventory, workload window, Pods, Excel export and named pool assessment", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(
    page.getByRole("tab", { name: "Node pools 8", exact: true }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Nodes", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Nodes in services" }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Workloads", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: /Individual Pods/ }),
  ).toBeVisible();
  await page.getByRole("slider", { name: "Usage lookback days" }).fill("10");
  await expect(page.getByText("10-day window", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Request recommendations" }),
  ).toBeVisible();
  await page.getByLabel("Recommendation headroom").selectOption("30");
  await expect(page.getByText("Review required").first()).toBeVisible();
  const workloadExport = page
    .getByRole("link", { name: "Excel", exact: true })
    .first();
  await expect(workloadExport).toHaveAttribute("href", /days=10/);
  const download = page.waitForEvent("download");
  await workloadExport.click();
  expect((await download).suggestedFilename()).toBe("optipool-workloads.xlsx");
  await page.getByRole("textbox", { name: "Search Pods" }).fill("checkout");
  await expect(
    page.locator(".pod-panel > .table-wrap > table > tbody > tr"),
  ).toHaveCount(3);
  await page
    .locator(".pod-panel")
    .getByText("Pod details", { exact: true })
    .first()
    .click();
  await expect(
    page
      .locator(".pod-panel")
      .getByText(/Throttled periods:/)
      .first(),
  ).toBeVisible();
  await page
    .getByRole("tab", { name: "Capacity planner", exact: true })
    .click();
  await expect(
    page.getByText("Schedule onto selected node pool"),
  ).toBeVisible();
  await page.getByRole("textbox", { name: "CPU request / replica" }).fill("2");
  await page.getByRole("spinbutton", { name: "Replica count" }).fill("10");
  await page.getByLabel("Planning scenario").selectOption("combined");
  await page.getByLabel("HPA maximum replicas").fill("12");
  await page.getByLabel("Surge headroom").fill("25%");
  await page
    .getByRole("button", { name: "Estimate capacity", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Needs nodes", exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/surge 3 = peak 15/)).toBeVisible();
  await expect(page.locator(".node-plan").first()).toBeVisible();
  await expect(
    page.getByText("Target node pool", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("atlas-prod / atlas-europe", { exact: true }).last(),
  ).toBeVisible();
  await expect(
    page.getByText("Synthetic fixtures — not GCP prices"),
  ).toBeVisible();
  await page
    .getByRole("textbox", { name: "Memory request / replica" })
    .fill("100Gi");
  await page
    .getByRole("button", { name: "Estimate capacity", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Blocked constraints", exact: true }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Node pools 8", exact: true }).click();
  await page
    .getByRole("button", { name: "Fetch latest live data", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Compare snapshots", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Compare snapshots", exact: true })
    .click();
  await expect(
    page.getByText("No changes in compared resource fields."),
  ).toBeVisible();
  await page.goto("/");
  await expect(
    page.getByRole("tab", { name: "Node pools 8", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "../docs/dashboard-desktop.png",
    fullPage: true,
  });
  expect(errors).toEqual([]);
});

test("CUD quote distinguishes inapplicable and unavailable prices", async ({
  page,
}) => {
  let status = "not_applicable";
  await page.route("**/api/estimate?*", async (route) => {
    const response = await route.fetch();
    const result = await response.json();
    await route.fulfill({
      response,
      json: {
        ...result,
        cost: {
          ...result.cost,
          cud_status: status,
          cud_3y_hourly: null,
          cud_3y_monthly: null,
          commitment_3y_obligation: null,
        },
      },
    });
  });
  await page.goto("/");
  await expect(
    page.getByRole("tab", { name: "Node pools 8", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("tab", { name: "Capacity planner", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Estimate capacity", exact: true })
    .click();
  await expect(page.getByText("Not applicable", { exact: true })).toBeVisible();
  status = "unavailable";
  await page
    .getByRole("button", { name: "Estimate capacity", exact: true })
    .click();
  await expect(page.getByText("Unavailable", { exact: true })).toBeVisible();
});

test("mobile layout keeps navigation and table overflow inside the page", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(
    page.getByRole("tab", { name: "Node pools 8", exact: true }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Workloads", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: /Individual Pods/ }),
  ).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth + 1,
  );
  expect(overflow).toBe(false);
  await page.screenshot({
    path: "../docs/dashboard-mobile.png",
    fullPage: true,
  });
});

test("cluster-wide saved views, memory summary, exports and individual planning target", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(
    page.getByRole("tab", { name: "Node pools 8", exact: true }),
  ).toBeVisible();
  const inv = await (await page.request.get("/api/inventory")).json();
  const pool = inv.pools[0];
  await page.getByLabel("Project", { exact: true }).selectOption(pool.project);
  await page
    .getByLabel("Cluster", { exact: true })
    .selectOption(`${pool.project}/${pool.location}/${pool.cluster}`);
  const selected = inv.pools.filter(
    (p: { project: string; location: string; cluster: string }) =>
      p.project === pool.project &&
      p.location === pool.location &&
      p.cluster === pool.cluster,
  );
  const requested = selected.reduce(
    (total: number, p: { id: string }) => total + inv.summaries[p.id].memory,
    0,
  );
  const allocatable = selected.reduce(
    (total: number, p: { id: string }) =>
      total + inv.summaries[p.id].memory_allocatable,
    0,
  );
  await expect(
    page
      .locator(".stat")
      .filter({ hasText: "Memory requests" })
      .locator("strong"),
  ).toHaveText(`${Math.round((requested / allocatable) * 100)}%`);
  await expect(
    page
      .getByLabel("Selected node pool", { exact: true })
      .locator("option")
      .filter({ hasText: "services" }),
  ).toHaveText("services");
  await page
    .getByLabel("Selected node pool", { exact: true })
    .selectOption("__all_pools__");
  await expect(
    page.getByRole("button", { name: "Fetch latest live data", exact: true }),
  ).toBeDisabled();
  await page.getByRole("tab", { name: "Nodes", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Nodes across all node pools" }),
  ).toBeVisible();
  await expect(page.locator(".cluster-nodes-panel tbody tr")).toHaveCount(5);
  await page.getByRole("tab", { name: "Workloads", exact: true }).click();
  await expect(page.locator(".cluster-workloads-panel tbody tr")).toHaveCount(
    4,
  );
  await expect(
    page.locator(".pod-panel > .table-wrap > table > tbody > tr"),
  ).toHaveCount(20);
  await page.getByRole("slider", { name: "Usage lookback days" }).fill("10");
  await expect(page.getByText("Latest / p99 · 10 days").first()).toBeVisible();
  const download = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Excel", exact: true })
    .first()
    .click();
  expect((await download).suggestedFilename()).toBe(
    "optipool-cluster-workloads.xlsx",
  );
  await page
    .getByRole("tab", { name: "Capacity planner", exact: true })
    .click();
  await expect(
    page.getByText("Select an individual node pool to estimate capacity.", {
      exact: true,
    }),
  ).toBeVisible();
  expect(
    (await (await page.request.get("/api/inventory")).json()).pools.map(
      (p: { snapshot_id: string }) => p.snapshot_id,
    ),
  ).toEqual(inv.pools.map((p: { snapshot_id: string }) => p.snapshot_id));
  await page.route("**/api/snapshot?*", async (route) => {
    const response = await route.fetch();
    const snapshot = await response.json();
    snapshot.workloads[0].kind = "SparkApplication";
    await route.fulfill({ response, json: snapshot });
  });
  await page
    .getByLabel("Selected node pool", { exact: true })
    .selectOption(pool.id);
  await page.getByRole("tab", { name: "Workloads", exact: true }).click();
  await expect(
    page.getByText("Workload type: SparkApplication", { exact: true }),
  ).toBeVisible();
  const row = page.locator("tr").filter({
    has: page.getByText("Workload type: SparkApplication", { exact: true }),
  });
  await expect(
    row.getByText("No attributable history", { exact: true }),
  ).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    ),
  ).toBe(false);
  expect(errors).toEqual([]);
});

test("multiple services share capacity and keep per-service placements", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("tab", { name: "Node pools 8", exact: true }),
  ).toBeVisible();
  const before = await (await page.request.get("/api/inventory")).json();
  await page.getByRole("tab", { name: /Capacity planner/ }).click();
  const first = page.getByRole("group", { name: "Service 1", exact: true });
  await first.getByLabel("Service name", { exact: true }).fill("bundle-api");
  await first.getByLabel("CPU request / replica", { exact: true }).fill("100m");
  await first
    .getByLabel("Memory request / replica", { exact: true })
    .fill("128Mi");
  await first.getByLabel("Replica count", { exact: true }).fill("2");
  await page.getByRole("button", { name: "Add service", exact: true }).click();
  const second = page.getByRole("group", { name: "Service 2", exact: true });
  await second
    .getByLabel("Service name", { exact: true })
    .fill("bundle-worker");
  await second
    .getByLabel("CPU request / replica", { exact: true })
    .fill("200m");
  await second
    .getByLabel("Memory request / replica", { exact: true })
    .fill("256Mi");
  await second.getByLabel("Replica count", { exact: true }).fill("3");
  const responsePromise = page.waitForResponse(
    (r) =>
      r.url().includes("/api/estimate-bundle") &&
      r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Estimate capacity", exact: true })
    .click();
  const assessment = await (await responsePromise).json();
  expect(assessment.replicas).toBe(5);
  expect(assessment.total_requests.cpu).toBeCloseTo(0.8);
  expect(
    assessment.services.map(
      (s: { placed_replicas: number }) => s.placed_replicas,
    ),
  ).toEqual([2, 3]);
  expect(
    new Set(assessment.placements.map((p: { service: string }) => p.service))
      .size,
  ).toBe(2);
  await expect(
    page.getByRole("table", { name: "Assessed services" }).getByRole("row"),
  ).toHaveCount(3);
  await expect(
    page.getByRole("heading", { name: "Fits", exact: true }),
  ).toBeVisible();
  let release!: () => void;
  let started!: () => void;
  let completed!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  const start = new Promise<void>((resolve) => {
    started = resolve;
  });
  const completion = new Promise<void>((resolve) => {
    completed = resolve;
  });
  await page.route("**/api/estimate-bundle?*", async (route) => {
    const response = await route.fetch();
    started();
    await held;
    // The browser may already have canceled this intentionally stale request.
    await route.fulfill({ response }).catch(() => {});
    completed();
  });
  await page
    .getByRole("button", { name: "Estimate capacity", exact: true })
    .click();
  await start;
  const worker = before.pools.find(
    (p: { name: string; project: string; cluster: string }) =>
      p.name === "workers" &&
      p.project === assessment.target_pool.project &&
      p.cluster === assessment.target_pool.cluster,
  );
  await page
    .getByLabel("Selected node pool", { exact: true })
    .selectOption(worker.id);
  await expect(
    page.getByRole("button", { name: "Estimate capacity", exact: true }),
  ).toBeEnabled();
  release();
  await completion;
  await expect(
    page.getByRole("table", { name: "Assessed services" }),
  ).toHaveCount(0);
  const after = await (await page.request.get("/api/inventory")).json();
  expect(
    after.pools.map((p: { snapshot_id: string }) => p.snapshot_id),
  ).toEqual(before.pools.map((p: { snapshot_id: string }) => p.snapshot_id));
});

test("new node pool design compares saved profiles, downloads and restores history", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(
    page.getByRole("tab", { name: "Node pools 8", exact: true }),
  ).toBeVisible();
  const before = await (await page.request.get("/api/inventory")).json();
  await page.getByRole("tab", { name: "New node pool", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Design a new node pool", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByLabel("Use profile services", { exact: true }),
  ).toBeChecked();
  await page
    .getByLabel("New node pool name", { exact: true })
    .fill("bundle-pool");
  const first = page.getByRole("group", { name: "Service 1", exact: true });
  await first.getByLabel("Service name", { exact: true }).fill("new-api");
  await first.getByLabel("CPU request / replica", { exact: true }).fill("1");
  await first.getByLabel("Replica count", { exact: true }).fill("4");
  await page.getByRole("button", { name: "Add service", exact: true }).click();
  const second = page.getByRole("group", { name: "Service 2", exact: true });
  await second.getByLabel("Service name", { exact: true }).fill("new-worker");
  const responsePromise = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/node-pool-design") &&
      r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Design node pool", exact: true })
    .click();
  const report = await (await responsePromise).json();
  expect(report.kind).toBe("node_pool_design");
  expect(report.candidates.length).toBe(2);
  expect(
    report.candidates.every(
      (c: { configuration: { total_nodes: number } }) =>
        c.configuration.total_nodes === 2,
    ),
  ).toBe(true);
  expect(
    report.candidates.every(
      (c: { assessment: { node_budgets: { planned: boolean }[] } }) =>
        c.assessment.node_budgets.every((n) => n.planned),
    ),
  ).toBe(true);
  await expect(
    page.getByRole("table", { name: "Node pool candidates" }).getByRole("row"),
  ).toHaveCount(3);
  await expect(
    page.getByRole("heading", { name: "Saved node pool designs", exact: true }),
  ).toBeVisible();
  const downloadPromise = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download design JSON", exact: true })
    .click();
  expect((await downloadPromise).suggestedFilename()).toBe(
    "optipool-node-pool-design.json",
  );
  await page.screenshot({
    path: "../docs/nodepool-designer.png",
    fullPage: true,
  });
  await page.reload();
  await page.getByRole("tab", { name: "New node pool", exact: true }).click();
  await page.getByRole("button", { name: /^bundle-pool ·/ }).click();
  await expect(
    page.getByRole("table", { name: "Node pool candidates" }),
  ).toBeVisible();
  await expect(
    page.getByLabel("New node pool name", { exact: true }),
  ).toHaveValue("bundle-pool");
  await expect(
    page
      .getByRole("group", { name: "Service 1", exact: true })
      .getByLabel("Service name", { exact: true }),
  ).toHaveValue("new-api");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    ),
  ).toBe(false);
  const after = await (await page.request.get("/api/inventory")).json();
  expect(
    after.pools.map((p: { snapshot_id: string }) => p.snapshot_id),
  ).toEqual(before.pools.map((p: { snapshot_id: string }) => p.snapshot_id));
  expect(errors).toEqual([]);
});

test("saved workload and Pod evidence explains independent reduction policy", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("tab", { name: "Workloads", exact: true }).click();
  await page
    .locator(".pod-panel")
    .getByText("Pod details", { exact: true })
    .first()
    .click();
  await expect(
    page
      .locator(".pod-panel")
      .getByText(/Selected-window coverage/)
      .first(),
  ).toBeVisible();
  await expect(
    page
      .locator(".pod-panel")
      .getByText(/Pod-lifetime coverage/)
      .first(),
  ).toBeVisible();
  await expect(
    page
      .locator(".pod-panel")
      .getByText(/Represented duration/)
      .first(),
  ).toBeVisible();
  await expect(page.getByText(/Reduction policy: at least 20/)).toBeVisible();
  await page.getByRole("slider", { name: "Usage lookback days" }).fill("10");
  await expect(page.getByText("10-day window", { exact: true })).toBeVisible();
  await page
    .locator(".analytical-panel")
    .getByText("Evidence and limits", { exact: true })
    .first()
    .click();
  await expect(
    page
      .locator(".analytical-panel")
      .getByText(/Selected-window coverage/)
      .first(),
  ).toBeVisible();
});

test("saved metric source details show partial resources and legacy unknown query fields", async ({
  page,
}) => {
  let collectionRequests = 0;
  page.on("request", (request) => {
    if (request.url().includes("/api/refresh/")) collectionRequests += 1;
  });
  await page.route("**/api/snapshot?**", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.usage.cpu_rate_window_seconds = null;
    body.usage.cpu_alignment_window_seconds = null;
    body.usage.query_definition = null;
    await route.fulfill({ response, json: body });
  });
  await page.goto("/");
  await page.getByRole("tab", { name: "Workloads", exact: true }).click();
  await expect(
    page.getByText("CPU rate window: Unknown", { exact: false }),
  ).toBeVisible();
  await page.route("**/api/snapshot?**", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.usage = {
      ...body.usage,
      workloads: Object.fromEntries(
        Object.entries(body.usage.workloads).map(([key, value]) => [
          key,
          { ...(value as object), memory_peak: 4 * 1024 ** 3 },
        ]),
      ),
      pods: Object.fromEntries(
        Object.entries(body.usage.pods).map(([key, value]) => [
          key,
          { ...(value as object), memory_peak: 4 * 1024 ** 3 },
        ]),
      ),
      source: "GMP cAdvisor",
      memory_definition: "Working set",
      cadence_seconds: 60,
      cpu_rate_window_seconds: 300,
      resource_status: { cpu: "available", memory: "unavailable" },
      units: { cpu: "cores", memory: "bytes" },
      query_definition: {
        cpu_metric: "container_cpu_usage_seconds_total",
        memory_metric: "container_memory_working_set_bytes",
        cpu_aggregation: "sum containers after rate[5m]",
        memory_aggregation: "sum container samples",
      },
      fallback_reason: "Native unavailable; selected GMP partial observations",
    };
    await route.fulfill({ response, json: body });
  });
  await page.getByRole("slider", { name: "Usage lookback days" }).fill("5");
  await expect(
    page.getByText("Source: GMP cAdvisor", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByText("Memory observations: unavailable", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByText("CPU rate window: 300s", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByText("Native unavailable; selected GMP partial observations", {
      exact: false,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("columnheader", {
      name: "Sampled memory peak",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("cell", {
        name: "4.00 GiB Highest observed replica sample",
        exact: true,
      })
      .first(),
  ).toBeVisible();
  await expect(
    page.getByText("Sampled peak: 4.00 GiB", { exact: false }).first(),
  ).toBeVisible();
  await page.getByText("Saved query definitions", { exact: true }).click();
  await expect(
    page.getByText("container_memory_working_set_bytes", { exact: false }),
  ).toBeVisible();
  expect(collectionRequests).toBe(0);
});

test("saved risk evidence is visible for workloads, Pods, recommendations and exports", async ({
  page,
}) => {
  let collections = 0;
  page.on("request", (r) => {
    if (r.method() === "POST" && /\/api\/(refresh|initialize)/.test(r.url()))
      collections++;
  });
  await page.goto("/");
  await expect(
    page.getByRole("tab", { name: "Node pools 8", exact: true }),
  ).toBeVisible();
  await page.getByRole("tab", { name: /^Workloads/ }).click();
  await page.getByText("CPU evidence", { exact: true }).first().click();
  await expect(
    page
      .getByText("Synthetic risk counters — not observed GCP evidence")
      .first(),
  ).toBeVisible();
  await expect(page.getByText(/Throttled periods:/).first()).toBeVisible();
  await expect(
    page.getByText(/Required risk evidence: yes/).first(),
  ).toBeVisible();
  await page.getByText("Memory evidence", { exact: true }).first().click();
  await expect(page.getByText(/Historical OOM count:/).first()).toBeVisible();
  await page
    .locator(".pod-panel")
    .getByText("Pod details", { exact: true })
    .first()
    .click();
  await expect(
    page
      .locator(".pod-panel")
      .getByText(/Throttled periods:/)
      .first(),
  ).toBeVisible();
  await page.getByText("Evidence and limits", { exact: true }).first().click();
  await expect(page.getByText(/Throttled periods:/).first()).toBeVisible();
  const inventory = await (await page.request.get("/api/inventory")).json();
  const response = await page.request.get(
    `/api/export/workloads?pool_id=${encodeURIComponent(inventory.pools[0].id)}&days=3`,
  );
  expect(await response.text()).toContain("CPU risk denominator");
  expect(await response.text()).toContain("Synthetic risk counters");
  expect(collections).toBe(0);
});
