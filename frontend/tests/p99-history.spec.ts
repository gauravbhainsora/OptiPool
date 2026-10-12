import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";

test("rollout keeps deleted winner distinct from current replicas in saved windows and exports", async ({
  page,
}) => {
  test.skip(
    process.env.OPTIPOOL_HISTORY_E2E !== "1",
    "Uses the isolated historical rollout fixture",
  );
  await page.goto("/");
  await expect(
    page.getByRole("tab", { name: "Node pools 1", exact: true }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Workloads", exact: true }).click();
  await expect(
    page.getByText("3 replicas observed · 0 historical").first(),
  ).toBeVisible();
  // Exercise the real saved refresh with a terminal response, as a fast worker can produce.
  await page.route(
    "**/api/refresh/pool?*",
    async (route) => {
      const response = await route.fetch();
      const job = await response.json();
      let finished = job;
      await expect
        .poll(async () => {
          finished = await (
            await page.request.get(`/api/jobs/${job.id}`)
          ).json();
          return finished.state;
        })
        .toBe("succeeded");
      await route.fulfill({ response, json: finished });
    },
    { times: 1 },
  );
  await page
    .getByRole("button", { name: "Fetch latest live data", exact: true })
    .click();
  await expect(
    page.getByText("3 replicas observed · 1 historical"),
  ).toBeVisible();
  await expect(page.getByText("2 running / 3 desired")).toBeVisible();
  await page.getByRole("slider", { name: "Usage lookback days" }).fill("10");
  await expect(
    page.getByText("3 replicas observed · 1 historical"),
  ).toBeVisible();
  const row = page
    .locator("tr")
    .filter({ has: page.getByText("checkout-api", { exact: true }) })
    .first();
  await expect(
    row.locator("td[title='checkout-api-7cf88-1']").first(),
  ).toContainText("9");
  const downloading = page.waitForEvent("download");
  await page.getByRole("link", { name: "CSV", exact: true }).first().click();
  const download = await downloading;
  const content = await readFile((await download.path())!, "utf8");
  expect(content).toContain("Historical replicas observed");
  expect(content).toContain("checkout-api-7cf88-1");
  await page.reload();
  await page.getByRole("tab", { name: "Workloads", exact: true }).click();
  await expect(
    page.getByText("3 replicas observed · 1 historical"),
  ).toBeVisible();
});
