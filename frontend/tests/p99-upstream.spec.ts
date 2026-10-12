import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";

test("upstream deleted replica wins p99 before first inventory, saved windows and exports retain proof", async ({
  page,
}) => {
  test.skip(
    process.env.OPTIPOOL_UPSTREAM_E2E !== "1",
    "Uses the isolated upstream source fixture",
  );
  await page.goto("/");
  await expect(
    page.getByRole("tab", { name: "Node pools 2", exact: true }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Workloads", exact: true }).click();
  await expect(
    page.getByText("1 replicas observed · 1 historical"),
  ).toBeVisible();
  await expect(page.getByText("1 running / 3 desired")).toBeVisible();
  const details = page.getByText(
    "Historical discovery: partial · 1 replicas discovered",
  );
  await expect(details).toBeVisible();
  await details.click();
  await expect(
    page.getByText("Metadata metric: optipool_pod_membership"),
  ).toBeVisible();
  await page.getByRole("slider", { name: "Usage lookback days" }).fill("1");
  const row = page
    .locator("tr")
    .filter({ has: page.getByText("api", { exact: true }) })
    .first();
  await expect(
    row.locator("td[title='deleted-before-import']").first(),
  ).toContainText("9");
  const downloading = page.waitForEvent("download");
  await page.getByRole("link", { name: "CSV", exact: true }).first().click();
  const download = await downloading;
  const csv = await readFile((await download.path())!, "utf8");
  expect(csv).toContain("Historical metadata metric");
  expect(csv).toContain("optipool_pod_membership");
  expect(csv).toContain("deleted-before-import");
  await page.reload();
  await page.getByRole("tab", { name: "Workloads", exact: true }).click();
  await expect(
    page.getByText("Historical discovery: partial · 1 replicas discovered"),
  ).toBeVisible();
  await expect(
    page.getByText("1 replicas observed · 1 historical"),
  ).toBeVisible();
});
