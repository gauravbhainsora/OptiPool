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
  const workloadExport = page
    .getByRole("link", { name: "Excel", exact: true })
    .first();
  await expect(workloadExport).toHaveAttribute("href", /days=10/);
  const download = page.waitForEvent("download");
  await workloadExport.click();
  expect((await download).suggestedFilename()).toBe("optipool-workloads.xlsx");
  await page.getByRole("textbox", { name: "Search Pods" }).fill("checkout");
  await expect(page.locator(".pod-panel tbody tr")).toHaveCount(3);
  await page
    .getByRole("tab", { name: "Capacity planner", exact: true })
    .click();
  await expect(
    page.getByText("Schedule onto selected node pool"),
  ).toBeVisible();
  await page.getByRole("textbox", { name: "CPU request / replica" }).fill("2");
  await page.getByRole("spinbutton", { name: "Replica count" }).fill("10");
  await page
    .getByRole("button", { name: "Estimate capacity", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Needs nodes", exact: true }),
  ).toBeVisible();
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
