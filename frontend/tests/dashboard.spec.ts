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
    page.getByText("CPU throttling history is not collected.").first(),
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
